"""
tests/test_device_services.py

Unit tests for the device service classes introduced in Phase 4.

Covers:
  1. BaseDeviceService — thread launch, connect retry, reconnect loop, dispatch
  2. CameraService — signals, ack_camera_frame, control surface
  3. TecService — signals, control surface
  4. FpgaService, BiasService, StageService — signals exist
  5. HardwareService delegation — signal forwarding, property access
  6. Service lifecycle — stop_event terminates loops

All tests use stubs / mocks — no real hardware.

Run:
    cd sanjinsight
    pytest tests/test_device_services.py -v
"""

from __future__ import annotations

import os
import sys
import time
import threading

import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def qapp():
    """One QApplication for the whole module."""
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ================================================================== #
#  1. BaseDeviceService                                                #
# ================================================================== #

class TestBaseDeviceService:
    """Core infrastructure: thread launch, retry, reconnect, dispatch."""

    @pytest.fixture
    def stop_event(self):
        return threading.Event()

    @pytest.fixture
    def svc(self, qapp, stop_event):
        from hardware.services.base_device_service import BaseDeviceService
        return BaseDeviceService(stop_event)

    # ── Thread launch ─────────────────────────────────────────────────

    def test_launch_starts_daemon_thread(self, svc):
        """_launch() must start a daemon thread that appears in threading.enumerate."""
        flag = threading.Event()
        svc._launch(target=flag.wait, args=(2.0,), name="test.launch")
        t = [t for t in threading.enumerate() if t.name == "test.launch"]
        assert len(t) == 1
        assert t[0].daemon is True
        flag.set()  # let thread exit
        t[0].join(timeout=2)

    def test_launch_tracks_thread(self, svc):
        """_launch() must append the thread to _threads."""
        flag = threading.Event()
        svc._launch(target=flag.wait, args=(0.5,), name="test.tracked")
        assert len(svc._threads) == 1
        flag.set()
        svc._threads[0].join(timeout=2)

    # ── Connect with retry ────────────────────────────────────────────

    def test_connect_succeeds_first_try(self, svc):
        """_connect_with_retry completes when connect_fn succeeds immediately."""
        calls = []
        def _ok():
            calls.append(1)
        svc._connect_with_retry(_ok, label="test")
        assert len(calls) == 1

    def test_connect_retries_on_failure(self, svc):
        """_connect_with_retry retries the right number of times."""
        attempts = []
        def _fail_then_pass():
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("not yet")
        svc._connect_with_retry(
            _fail_then_pass, label="test", max_retries=3, initial_delay_s=0.01)
        assert len(attempts) == 3

    def test_connect_raises_after_max_retries(self, svc):
        """_connect_with_retry raises the last exception after exhausting retries."""
        def _always_fail():
            raise ConnectionError("permanent failure")
        with pytest.raises(ConnectionError, match="permanent failure"):
            svc._connect_with_retry(
                _always_fail, label="test", max_retries=2, initial_delay_s=0.01)

    def test_connect_interrupted_by_stop(self, svc, stop_event):
        """_connect_with_retry raises when stop_event is set during retry."""
        attempts = []
        def _fail():
            attempts.append(1)
            if len(attempts) == 1:
                stop_event.set()  # signal shutdown during first retry backoff
            raise ConnectionError("fail")
        with pytest.raises((ConnectionError, RuntimeError)):
            svc._connect_with_retry(
                _fail, label="test", max_retries=5, initial_delay_s=0.01)

    # ── Reconnect loop ────────────────────────────────────────────────

    def test_reconnect_loop_success(self, svc, qapp):
        """_reconnect_loop returns True when reconnect_fn succeeds."""
        connected = []
        svc.device_connected.connect(lambda k, v: connected.append((k, v)))

        result = svc._reconnect_loop("camera", lambda: None, "test")
        assert result is True
        assert ("camera", True) in connected

    def test_reconnect_loop_stops_on_stop_event(self, svc, stop_event, qapp):
        """_reconnect_loop returns False when stop_event is set."""
        call_count = []
        def _always_fail():
            call_count.append(1)
            if len(call_count) >= 2:
                stop_event.set()
            raise ConnectionError("fail")

        result = svc._reconnect_loop("camera", _always_fail, "test")
        assert result is False

    # ── Dispatch ──────────────────────────────────────────────────────

    def test_dispatch_runs_function(self, svc):
        """_dispatch() must execute the function in a daemon thread."""
        result = []
        svc._dispatch(lambda: result.append(42))
        time.sleep(0.2)
        assert 42 in result

    def test_dispatch_emits_error_on_failure(self, svc, qapp):
        """_dispatch() must emit error signal when the function raises."""
        errors = []
        svc.error.connect(lambda msg: errors.append(msg))

        def _boom():
            raise ValueError("test error")

        svc._dispatch(_boom)
        # The signal is emitted from a background thread; Qt needs event
        # processing to deliver cross-thread queued connections.
        deadline = time.monotonic() + 2.0
        while not errors and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        assert len(errors) == 1
        assert "test error" in errors[0]

    # ── Signal existence ──────────────────────────────────────────────

    def test_base_signals_exist(self, svc):
        """BaseDeviceService must define all documented signals."""
        assert hasattr(svc, 'device_connected')
        assert hasattr(svc, 'error')
        assert hasattr(svc, 'log_message')
        assert hasattr(svc, 'startup_status')


# ================================================================== #
#  2. CameraService                                                    #
# ================================================================== #

class TestCameraService:
    """CameraService signals, ack_camera_frame, control surface."""

    @pytest.fixture
    def cam_svc(self, qapp):
        from hardware.services.camera_service import CameraService
        stop = threading.Event()
        return CameraService(stop)

    def test_camera_signals_exist(self, cam_svc):
        """CameraService must define frame_ready, acq_progress, acq_complete."""
        assert hasattr(cam_svc, 'frame_ready')
        assert hasattr(cam_svc, 'acq_progress')
        assert hasattr(cam_svc, 'acq_complete')

    def test_inherits_base_signals(self, cam_svc):
        """CameraService must inherit all BaseDeviceService signals."""
        assert hasattr(cam_svc, 'device_connected')
        assert hasattr(cam_svc, 'error')
        assert hasattr(cam_svc, 'log_message')

    def test_ack_camera_frame(self, cam_svc):
        """ack_camera_frame() must set the preview free event."""
        cam_svc._cam_preview_free.clear()
        assert not cam_svc._cam_preview_free.is_set()

        cam_svc.ack_camera_frame()
        assert cam_svc._cam_preview_free.is_set()

    def test_preview_free_initially_set(self, cam_svc):
        """The preview free event must be set initially (no back-pressure)."""
        assert cam_svc._cam_preview_free.is_set()

    def test_cam_set_exposure_no_crash_when_no_camera(self, cam_svc):
        """cam_set_exposure must not crash when no camera is in app_state."""
        cam_svc.cam_set_exposure(5000.0)  # should be a silent no-op

    def test_cam_set_gain_no_crash_when_no_camera(self, cam_svc):
        cam_svc.cam_set_gain(0.0)  # silent no-op


# ================================================================== #
#  3. TecService                                                       #
# ================================================================== #

class TestTecService:
    """TecService signals and control surface."""

    @pytest.fixture
    def tec_svc(self, qapp):
        from hardware.services.tec_service import TecService
        stop = threading.Event()
        return TecService(stop)

    def test_tec_signals_exist(self, tec_svc):
        """TecService must define status_update, alarm, warning, alarm_clear."""
        assert hasattr(tec_svc, 'status_update')
        assert hasattr(tec_svc, 'alarm')
        assert hasattr(tec_svc, 'warning')
        assert hasattr(tec_svc, 'alarm_clear')

    def test_inherits_base_signals(self, tec_svc):
        assert hasattr(tec_svc, 'device_connected')
        assert hasattr(tec_svc, 'error')

    def test_poll_interval_has_default(self, tec_svc):
        """Default TEC poll interval must be positive."""
        assert tec_svc._TEC_POLL_S > 0


# ================================================================== #
#  4. FpgaService, BiasService, StageService                           #
# ================================================================== #

class TestFpgaService:
    @pytest.fixture
    def svc(self, qapp):
        from hardware.services.fpga_service import FpgaService
        return FpgaService(threading.Event())

    def test_signals_exist(self, svc):
        assert hasattr(svc, 'status_update')
        assert hasattr(svc, 'device_connected')

    def test_inherits_base(self, svc):
        from hardware.services.base_device_service import BaseDeviceService
        assert isinstance(svc, BaseDeviceService)


class TestBiasService:
    @pytest.fixture
    def svc(self, qapp):
        from hardware.services.bias_service import BiasService
        return BiasService(threading.Event())

    def test_signals_exist(self, svc):
        assert hasattr(svc, 'status_update')
        assert hasattr(svc, 'device_connected')

    def test_inherits_base(self, svc):
        from hardware.services.base_device_service import BaseDeviceService
        assert isinstance(svc, BaseDeviceService)


class TestStageService:
    @pytest.fixture
    def svc(self, qapp):
        from hardware.services.stage_service import StageService
        return StageService(threading.Event())

    def test_signals_exist(self, svc):
        assert hasattr(svc, 'status_update')
        assert hasattr(svc, 'device_connected')

    def test_inherits_base(self, svc):
        from hardware.services.base_device_service import BaseDeviceService
        assert isinstance(svc, BaseDeviceService)


# ================================================================== #
#  5. HardwareService delegation                                       #
# ================================================================== #

class TestHardwareServiceDelegation:
    """Verify HardwareService creates child services and exposes properties."""

    @pytest.fixture(autouse=True)
    def reset_app_state(self):
        from hardware.app_state import app_state
        yield
        try:
            with app_state:
                app_state._cam = None
                app_state._fpga = None
                app_state._bias = None
                app_state._stage = None
                app_state._pipeline = None
                app_state._tecs = []
                app_state._demo_mode = False
        except Exception:
            pass

    @pytest.fixture
    def hw_svc(self, qapp):
        from hardware.hardware_service import HardwareService
        return HardwareService()

    def test_child_services_created(self, hw_svc):
        """HardwareService must create all 5 child service instances."""
        assert hw_svc.camera_service is not None
        assert hw_svc.tec_service is not None
        assert hw_svc.fpga_service is not None
        assert hw_svc.bias_service is not None
        assert hw_svc.stage_service is not None

    def test_child_services_are_correct_types(self, hw_svc):
        from hardware.services.camera_service import CameraService
        from hardware.services.tec_service import TecService
        from hardware.services.fpga_service import FpgaService
        from hardware.services.bias_service import BiasService
        from hardware.services.stage_service import StageService

        assert isinstance(hw_svc.camera_service, CameraService)
        assert isinstance(hw_svc.tec_service, TecService)
        assert isinstance(hw_svc.fpga_service, FpgaService)
        assert isinstance(hw_svc.bias_service, BiasService)
        assert isinstance(hw_svc.stage_service, StageService)

    def test_signal_forwarding_attributes_exist(self, hw_svc):
        """Key signals must be accessible on HardwareService (forwarded from children)."""
        # Camera signals
        assert hasattr(hw_svc, 'camera_frame')
        # TEC signals
        assert hasattr(hw_svc, 'tec_status')
        # Shared signals
        assert hasattr(hw_svc, 'device_connected')

    def test_services_share_stop_event(self, hw_svc):
        """All child services must share the same stop event as HardwareService."""
        stop = hw_svc._stop_event
        assert hw_svc.camera_service._stop_event is stop
        assert hw_svc.tec_service._stop_event is stop
        assert hw_svc.fpga_service._stop_event is stop
        assert hw_svc.bias_service._stop_event is stop
        assert hw_svc.stage_service._stop_event is stop


# ================================================================== #
#  6. Service lifecycle — stop_event                                   #
# ================================================================== #

class TestServiceLifecycle:
    """Verify stop_event terminates service loops cleanly."""

    def test_stop_event_interrupts_connect_retry(self, qapp):
        """Setting stop_event during _connect_with_retry must abort quickly."""
        from hardware.services.base_device_service import BaseDeviceService

        stop = threading.Event()
        svc = BaseDeviceService(stop)

        def _slow_fail():
            raise ConnectionError("nope")

        stop.set()  # set before calling
        with pytest.raises((ConnectionError, RuntimeError)):
            svc._connect_with_retry(
                _slow_fail, label="test", max_retries=10, initial_delay_s=1.0)
        # Should have returned very quickly, not waited 10+ seconds

    def test_launched_threads_are_daemon(self, qapp):
        """All threads launched via _launch() must be daemon threads."""
        from hardware.services.base_device_service import BaseDeviceService

        stop = threading.Event()
        svc = BaseDeviceService(stop)

        flag = threading.Event()
        t = svc._launch(target=flag.wait, args=(1.0,), name="test.daemon")
        assert t.daemon is True
        flag.set()
        t.join(timeout=2)
