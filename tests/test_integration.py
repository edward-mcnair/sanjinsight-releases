"""
tests/test_integration.py

Integration tests — multi-component scenarios that verify the system
behaves correctly across module boundaries.

All tests use only simulated drivers and temporary files — no real
hardware or display is required.

Run:
    cd sanjinsight
    pytest tests/test_integration.py -v

Coverage
--------
1. Session schema migration — legacy v0 files load without error; new
   files carry schema_version; migration is logged.
2. Config robustness — corrupt / missing preferences file does not crash
   the application, and the failure is recorded in the log.
3. HardwareService lifecycle — demo-mode start + clean shutdown leaves
   no orphan hw.* threads alive.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import time

import numpy as np
import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. Session schema migration                                         #
# ================================================================== #

class TestSessionSchemaMigration:
    """
    Verify that legacy (v0) session.json files migrate transparently,
    that new saves include schema_version, and that the migration is
    written to the log.
    """

    @pytest.fixture
    def minimal_result(self):
        """AcquisitionResult with small synthetic arrays — no hardware needed."""
        from acquisition.pipeline import AcquisitionResult

        H, W   = 32, 32
        result = AcquisitionResult(
            n_frames=4, exposure_us=1000.0,
            gain_db=0.0, timestamp=time.time())
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 1000
        result.hot_avg        = result.cold_avg * 1.001
        result.delta_r_over_r = (
            (result.hot_avg - result.cold_avg) / result.cold_avg
        ).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = result.hot_captured = 4
        return result

    # ----------------------------------------------------------------

    def test_new_session_includes_schema_version(self, minimal_result, tmp_path):
        """Freshly saved sessions must write schema_version into session.json."""
        from acquisition.session import Session
        from acquisition.schema_migrations import CURRENT_SCHEMA

        session = Session.from_result(minimal_result, label="sv_test")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)

        assert "schema_version" in data, \
            "schema_version key missing from freshly saved session.json"
        assert data["schema_version"] == CURRENT_SCHEMA, \
            f"Expected schema_version={CURRENT_SCHEMA}, got {data['schema_version']}"

    def test_legacy_v0_session_loads_correctly(self, minimal_result, tmp_path):
        """
        A session.json without schema_version (legacy v0) must load
        without raising and return a fully populated SessionMeta.
        """
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="legacy_test")
        path    = session.save(str(tmp_path))

        # Simulate a v0 file by stripping the schema_version field
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)

        assert loaded.meta.label == "legacy_test", \
            f"Label mismatch after migration: {loaded.meta.label!r}"
        assert loaded.meta.uid == session.meta.uid, \
            "UID changed after v0 → v1 migration"

    def test_migration_is_logged(self, minimal_result, tmp_path, caplog):
        """The v0 → v1 migration must emit an INFO-level log message."""
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="log_test")
        path    = session.save(str(tmp_path))

        # Strip schema_version to trigger the migration path
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        with caplog.at_level(logging.INFO, logger="acquisition.schema_migrations"):
            Session.load(path)

        migration_msgs = [
            r.message for r in caplog.records
            if "v0" in r.message and "v1" in r.message
        ]
        assert migration_msgs, (
            "Expected a log message containing 'v0' and 'v1' from "
            "acquisition.schema_migrations — got none.\n"
            f"All records: {[r.message for r in caplog.records]}"
        )

    def test_load_meta_also_migrates(self, minimal_result, tmp_path):
        """Session.load_meta() uses from_dict() and must apply migrations too."""
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="meta_test")
        path    = session.save(str(tmp_path))

        # Simulate v0
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        meta = Session.load_meta(path)

        assert meta is not None, "load_meta returned None for a valid v0 session"
        assert meta.label == "meta_test", \
            f"Unexpected label after load_meta migration: {meta.label!r}"

    def test_unknown_fields_are_ignored(self, minimal_result, tmp_path):
        """
        Extra keys in session.json (from a newer version) must be silently
        ignored — forward-compatibility guard.
        """
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="fwd_compat")
        path    = session.save(str(tmp_path))

        # Inject a hypothetical future field
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data["future_field_xyz"] = "some_value"
        data["schema_version"]   = 999   # far-future schema
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Must not raise — unknown keys are ignored by from_dict()
        loaded = Session.load(path)
        assert loaded.meta.label == "fwd_compat"


# ================================================================== #
#  2. Config — preferences file robustness                            #
# ================================================================== #

class TestConfigRobustness:
    """
    Verify that config.py survives malformed or missing preference
    files without crashing, and that failures appear in the log.
    """

    def test_corrupt_prefs_returns_empty_dict(self, tmp_path, monkeypatch):
        """_load_prefs() must return {} and not raise on invalid JSON."""
        import config

        corrupt_path = tmp_path / "preferences.json"
        corrupt_path.write_text("{this is NOT valid JSON!!!}", encoding="utf-8")
        monkeypatch.setattr(config, "_PREFS_PATH", corrupt_path)

        result = config._load_prefs()

        assert result == {}, \
            f"Expected empty dict for corrupt prefs, got {result!r}"

    def test_corrupt_prefs_logs_exception(self, tmp_path, monkeypatch, caplog):
        """The load failure must be captured in the log (not silently dropped)."""
        import config

        corrupt_path = tmp_path / "preferences.json"
        corrupt_path.write_text("<<<NOT JSON>>>", encoding="utf-8")
        monkeypatch.setattr(config, "_PREFS_PATH", corrupt_path)

        with caplog.at_level(logging.ERROR):
            config._load_prefs()

        assert any("Preferences load failed" in r.message for r in caplog.records), (
            "Expected 'Preferences load failed' in log records.\n"
            f"Got: {[r.message for r in caplog.records]}"
        )

    def test_missing_prefs_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """_load_prefs() must return {} when the preferences file does not exist."""
        import config

        missing_path = tmp_path / "no_such_dir" / "preferences.json"
        monkeypatch.setattr(config, "_PREFS_PATH", missing_path)

        result = config._load_prefs()

        assert result == {}, \
            f"Expected empty dict for missing prefs file, got {result!r}"

    def test_get_pref_returns_default_when_prefs_empty(self, monkeypatch):
        """get_pref() must return the caller's default when _prefs is empty."""
        import config
        monkeypatch.setattr(config, "_prefs", {})

        assert config.get_pref("ui.theme", "light") == "light"
        assert config.get_pref("nonexistent.key") is None
        assert config.get_pref("a.b.c.d", 42) == 42

    def test_get_pref_reads_nested_key(self, monkeypatch):
        """get_pref() must navigate dot-separated nested keys."""
        import config
        monkeypatch.setattr(config, "_prefs", {
            "ui": {"theme": "dark", "zoom": 1.5},
            "scan": {"step_um": 5.0},
        })

        assert config.get_pref("ui.theme")    == "dark"
        assert config.get_pref("ui.zoom")     == 1.5
        assert config.get_pref("scan.step_um") == 5.0
        assert config.get_pref("ui.missing", "fallback") == "fallback"


# ================================================================== #
#  3. HardwareService — demo-mode start → clean shutdown              #
# ================================================================== #

class TestHardwareServiceLifecycle:
    """
    Verify that HardwareService.start_demo() + shutdown() leaves no
    orphaned hw.* threads alive.

    Uses only simulated drivers; PyQt5 is required for signal/slot
    infrastructure but no physical display is needed.
    """

    @pytest.fixture(autouse=True)
    def reset_app_state(self):
        """
        Clear the global app_state hardware references before and after
        each test so successive tests don't see stale driver objects.
        """
        from hardware.app_state import app_state
        yield
        # Tear-down: null out hardware refs left by the service
        try:
            with app_state:
                app_state._cam      = None
                app_state._fpga     = None
                app_state._bias     = None
                app_state._stage    = None
                app_state._pipeline = None
                app_state._tecs     = []
                app_state._demo_mode = False
        except Exception:
            pass    # best-effort cleanup

    @pytest.fixture(scope="class")
    def qapp(self):
        """One QApplication for all tests in this class."""
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    # ----------------------------------------------------------------

    def test_demo_start_and_shutdown_no_orphan_threads(self, qapp):
        """start_demo() + shutdown() must leave no hw.* threads running."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        try:
            svc.start_demo()
            time.sleep(0.35)   # let all six demo threads reach their poll loops

            hw_before = [t for t in threading.enumerate()
                         if t.name.startswith("hw.")]
            assert len(hw_before) > 0, \
                "Expected ≥1 hw.* thread after start_demo() — none found"

            svc.shutdown()
        finally:
            # Safety net: ensure shutdown was called even if the assert above fails
            try:
                svc.shutdown()
            except Exception:
                pass

        hw_after = [t for t in threading.enumerate()
                    if t.name.startswith("hw.")]
        assert len(hw_after) == 0, (
            f"hw.* threads still alive after shutdown(): "
            f"{[t.name for t in hw_after]}"
        )

    def test_shutdown_is_idempotent(self, qapp):
        """Calling shutdown() twice on the same service must not raise."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        svc.start_demo()
        time.sleep(0.2)

        svc.shutdown()          # first shutdown — normal path
        svc.shutdown()          # second — must be a no-op, not an exception

    def test_shutdown_on_never_started_service(self, qapp):
        """shutdown() on a service that was never started must not raise."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        svc.shutdown()   # nothing started — should be a clean no-op


# ================================================================== #
#  4. MetricsService — deterministic quality metrics                  #
# ================================================================== #

class TestMetricsService:
    """
    Verify that MetricsService correctly computes and emits quality metrics
    and issues from simulated hardware signal data.

    Uses a minimal stub QObject that exposes the same signals as
    HardwareService so no real hardware is needed.
    """

    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    @pytest.fixture
    def hw_stub(self, qapp):
        """Minimal HardwareService stub that exposes the required signals."""
        from PyQt5.QtCore import QObject, pyqtSignal

        class HwStub(QObject):
            camera_frame     = pyqtSignal(object)
            tec_status       = pyqtSignal(int, object)
            fpga_status      = pyqtSignal(object)
            stage_status     = pyqtSignal(object)
            device_connected = pyqtSignal(str, bool)

        return HwStub()

    @pytest.fixture
    def svc(self, hw_stub):
        from ai.metrics_service import MetricsService
        return MetricsService(hw_stub)

    @staticmethod
    def _make_frame(data: np.ndarray, bit_depth: int = 12):
        """Wrap a numpy array in a minimal CameraFrame-like object."""
        class Frame:
            pass
        f = Frame()
        f.data        = data.astype(np.uint16)
        f.frame_index = 0
        f.exposure_us = 5000.0
        f.gain_db     = 0.0
        f.timestamp   = time.time()
        return f

    # ----------------------------------------------------------------

    def test_initial_state_has_no_issues(self, svc):
        """Before any signals arrive, there must be no active issues."""
        assert len(svc.active_issue_codes) == 0

    def test_camera_disconnected_issue_on_device_disconnected(
            self, hw_stub, svc):
        """device_connected('camera', False) → camera_disconnected issue."""
        from ai.metrics_service import CAM_DISCONNECTED
        detected = []
        svc.issue_detected.connect(lambda code, msg: detected.append(code))

        hw_stub.device_connected.emit("camera", False)

        assert CAM_DISCONNECTED in svc.active_issue_codes
        assert CAM_DISCONNECTED in detected

    def test_camera_disconnected_clears_on_reconnect(self, hw_stub, svc):
        """device_connected('camera', True) → camera_disconnected issue clears."""
        from ai.metrics_service import CAM_DISCONNECTED
        hw_stub.device_connected.emit("camera", False)   # set it
        assert CAM_DISCONNECTED in svc.active_issue_codes

        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        hw_stub.device_connected.emit("camera", True)    # clear it

        assert CAM_DISCONNECTED not in svc.active_issue_codes
        assert CAM_DISCONNECTED in cleared

    def test_saturation_issue_detected_on_bright_frame(self, hw_stub, svc):
        """A frame with >2% saturated pixels triggers camera_saturated."""
        from ai.metrics_service import CAM_SATURATED
        # 12-bit sensor, fill 10% of pixels to saturation (value = 4095)
        data        = np.zeros((100, 100), dtype=np.uint16)
        data[:10, :] = 4095   # 10 rows × 100 cols = 10% saturated
        hw_stub.camera_frame.emit(self._make_frame(data))

        assert CAM_SATURATED in svc.active_issue_codes

    def test_saturation_issue_clears_on_normal_frame(self, hw_stub, svc):
        """After saturation detected, a normal frame must clear the issue."""
        from ai.metrics_service import CAM_SATURATED
        # First: emit a saturated frame
        sat_data = np.full((100, 100), 4095, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(sat_data))
        assert CAM_SATURATED in svc.active_issue_codes

        # Then: emit a normal mid-range frame
        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        normal_data = np.full((100, 100), 2000, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(normal_data))

        assert CAM_SATURATED not in svc.active_issue_codes
        assert CAM_SATURATED in cleared

    def test_tec_stability_tracks_in_band_duration(self, hw_stub, svc):
        """
        TEC issue clears only after TEC_DWELL_S seconds in-band.
        We shorten TEC_DWELL_S to near-zero for a fast test.
        """
        from ai.metrics_service import TEC_NOT_STABLE
        from hardware.tec.base import TecStatus

        svc.TEC_DWELL_S = 0.05   # 50 ms dwell for test speed

        # Emit in-band status multiple times over > 50 ms
        stable_status = TecStatus(
            actual_temp=25.05, target_temp=25.0,
            enabled=True, stable=False)
        hw_stub.tec_status.emit(0, stable_status)
        time.sleep(0.07)
        hw_stub.tec_status.emit(0, stable_status)

        assert f"{TEC_NOT_STABLE}_0" not in svc.active_issue_codes

    def test_tec_not_stable_while_out_of_band(self, hw_stub, svc):
        """TEC with |actual - target| > tolerance must flag tec_not_stable."""
        from ai.metrics_service import TEC_NOT_STABLE
        from hardware.tec.base import TecStatus

        svc.TEC_DWELL_S = 30.0   # restore default so issue is raised

        unstable = TecStatus(
            actual_temp=26.5, target_temp=25.0,
            enabled=True, stable=False)
        hw_stub.tec_status.emit(0, unstable)

        assert f"{TEC_NOT_STABLE}_0" in svc.active_issue_codes

    def test_fpga_not_running_issue(self, hw_stub, svc):
        """FPGA status with running=False triggers fpga_not_running."""
        from ai.metrics_service import FPGA_NOT_RUNNING
        from hardware.fpga.base import FpgaStatus

        hw_stub.fpga_status.emit(FpgaStatus(running=False, sync_locked=True))

        assert FPGA_NOT_RUNNING in svc.active_issue_codes

    def test_fpga_issues_clear_when_running_and_locked(self, hw_stub, svc):
        """FPGA running + locked must clear both FPGA issues."""
        from ai.metrics_service import FPGA_NOT_RUNNING, FPGA_NOT_LOCKED
        from hardware.fpga.base import FpgaStatus

        # Set issues first
        hw_stub.fpga_status.emit(FpgaStatus(running=False, sync_locked=False))
        assert FPGA_NOT_RUNNING in svc.active_issue_codes

        # Clear them
        hw_stub.fpga_status.emit(FpgaStatus(running=True, sync_locked=True))
        assert FPGA_NOT_RUNNING not in svc.active_issue_codes
        assert FPGA_NOT_LOCKED  not in svc.active_issue_codes

    def test_stage_not_homed_issue(self, hw_stub, svc):
        """Stage status with homed=False triggers stage_not_homed."""
        from ai.metrics_service import STAGE_NOT_HOMED
        from hardware.stage.base import StageStatus

        hw_stub.stage_status.emit(StageStatus(homed=False))

        assert STAGE_NOT_HOMED in svc.active_issue_codes

    def test_ready_flag_false_when_issues_present(self, hw_stub, svc):
        """snapshot['ready'] must be False when any issue is active."""
        from hardware.stage.base import StageStatus
        hw_stub.stage_status.emit(StageStatus(homed=False))

        snap = svc.current_snapshot()
        assert snap["ready"] is False
        assert len(snap["issues"]) > 0

    def test_ready_flag_true_with_no_issues(self, svc):
        """A freshly constructed service with no signals has ready=True."""
        snap = svc.current_snapshot()
        assert snap["ready"] is True
        assert snap["issues"] == []

    def test_snapshot_structure(self, svc):
        """current_snapshot() must contain all required top-level keys."""
        snap = svc.current_snapshot()
        for key in ("camera", "tec", "fpga", "stage", "issues", "ready"):
            assert key in snap, f"Missing key {key!r} in snapshot"

    def test_focus_computation_nonzero_for_sharp_image(self):
        """_compute_focus() must return a positive value for a non-uniform image."""
        from ai.metrics_service import MetricsService
        # Sharp vertical step edge — creates a non-zero second derivative that
        # survives the 4× downsampling (unlike a 2-pixel-period checkerboard).
        data = np.zeros((64, 64), dtype=np.float32)
        data[:, 32:] = 4000   # left half dark, right half at full scale
        score = MetricsService._compute_focus(data)
        assert score > 0.0

    def test_focus_computation_zero_for_flat_image(self):
        """_compute_focus() must return 0 for a completely flat image."""
        from ai.metrics_service import MetricsService
        flat = np.full((64, 64), 2000.0, dtype=np.float32)
        score = MetricsService._compute_focus(flat)
        assert score == 0.0

    def test_throttle_bypassed_when_active_issues(self, hw_stub, svc):
        """
        The frame-rate throttle must be bypassed when active issues exist,
        so issues clear promptly even if frames arrive faster than EMIT_RATE_HZ.
        """
        from ai.metrics_service import CAM_SATURATED
        # Step 1: emit saturated frame → issue is raised and _last_proc_t is set
        sat = np.full((100, 100), 4095, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(sat))
        assert CAM_SATURATED in svc.active_issue_codes

        # Step 2: immediately emit a normal frame (within throttle window).
        # With the issue-aware bypass, this MUST be processed.
        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        normal = np.full((100, 100), 2000, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(normal))

        assert CAM_SATURATED not in svc.active_issue_codes, (
            "throttle incorrectly blocked the normal frame — "
            "active-issue bypass is not working"
        )
        assert CAM_SATURATED in cleared

    def test_throttle_applied_when_no_active_issues(self, hw_stub, svc):
        """
        When there are no active issues, rapid duplicate frames within the
        throttle window must be dropped (only the first is processed).
        """
        # Ensure no active issues and reset the throttle clock
        svc._last_proc_t = 0.0
        assert len(svc.active_issue_codes) == 0

        emit_count = []
        svc.metrics_updated.connect(lambda snap: emit_count.append(1))

        # Emit first frame — should be processed (resets throttle clock)
        svc._last_proc_t = 0.0
        hw_stub.camera_frame.emit(self._make_frame(
            np.full((50, 50), 2000, dtype=np.uint16)))
        count_after_first = len(emit_count)

        # Immediately emit a second frame — throttle window not yet elapsed
        hw_stub.camera_frame.emit(self._make_frame(
            np.full((50, 50), 2001, dtype=np.uint16)))
        count_after_second = len(emit_count)

        # The second frame should have been dropped by the throttle
        assert count_after_second == count_after_first, (
            "throttle did not drop the rapid second frame"
        )


# ================================================================== #
#  5. HardwareService — demo-mode camera config override              #
# ================================================================== #

class TestDemoModeCamera:
    """
    Verify that _run_camera() replaces the config driver with "simulated"
    when app_state.demo_mode is True, regardless of what config.yaml says.

    We test this by monkeypatching the camera factory so no thread is
    actually started — only the config argument is captured and inspected.
    """

    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    def test_demo_mode_forces_simulated_driver(self, monkeypatch, qapp):
        """When demo_mode=True the camera factory must receive driver='simulated'."""
        import hardware.hardware_service as hs_mod
        from hardware.app_state import app_state

        # Capture the config dict passed to create_camera
        captured = []

        class _FakeCamera:
            class info:
                model = "Simulated"
                width = 320
                height = 240
            def open(self): pass
            def start(self): pass
            def stop(self): pass

        def _fake_create_camera(cfg):
            captured.append(dict(cfg))
            return _FakeCamera()

        monkeypatch.setattr(hs_mod, "create_camera", _fake_create_camera)
        # Patch _connect_with_retry to a no-op so it doesn't actually retry
        monkeypatch.setattr(hs_mod.HardwareService, "_connect_with_retry",
                            lambda self, fn, **kw: fn())
        # Ensure app_state reports demo mode
        with app_state:
            app_state._demo_mode = True

        try:
            svc = hs_mod.HardwareService()
            svc._running = True          # prevent the thread from exiting early
            svc._run_camera()            # call directly (no thread needed)
        except Exception:
            pass                          # cleanup failures from missing pipeline etc.
        finally:
            with app_state:
                app_state._demo_mode = False
                app_state._cam = None

        assert len(captured) > 0, "_run_camera() never called create_camera()"
        assert captured[0]["driver"] == "simulated", (
            f"Expected driver='simulated' in demo mode, got {captured[0]['driver']!r}"
        )
