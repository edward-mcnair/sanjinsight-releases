"""
hardware/hardware_service.py

HardwareService
===============
Central owner of all hardware device lifecycles for SanjINSIGHT.

Responsibilities
----------------
  • Instantiate and connect every driver (camera, TEC ×2, FPGA, bias, stage)
    from config.yaml using the existing factory functions.
  • Start and supervise all poll/capture background threads.
  • Expose PyQt5 signals that the rest of the UI can connect to (status updates,
    new frames, errors, log messages) — identical signals to what main_app.py
    emitted directly before the refactor.
  • Provide a clean shutdown() that stops all threads and closes all drivers
    in the correct order.
  • Expose connect_device() / disconnect_device() so the Device Manager dialog
    can reconnect individual devices without restarting the app.

Design principles
-----------------
  • MainWindow does NOT touch drivers directly — it only connects signals and
    calls service methods.
  • All driver creation / open / connect calls happen on background threads to
    avoid blocking the Qt event loop.
  • The global `app_state` object is still updated by this service so legacy
    code that reads app_state.cam etc. continues to work unchanged.
  • The global `running` flag in main_app.py is replaced by an internal
    threading.Event so shutdown is deterministic.
"""

from __future__ import annotations

import logging
import threading
import time
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

import config as config_module
from hardware.app_state import app_state
from events import (emit_info, emit_warning,
                    EVT_DEVICE_CONNECT, EVT_DEVICE_DISCONNECT)
from hardware.cameras.factory  import create_camera
from hardware.tec.factory      import create_tec
from hardware.fpga.factory     import create_fpga

log = logging.getLogger(__name__)

# Optional hardware (may not be present on all installations)
try:
    from hardware.stage.factory import create_stage
    _HAS_STAGE = True
except ImportError:
    _HAS_STAGE = False

try:
    from hardware.bias.factory import create_bias
    _HAS_BIAS = True
except ImportError:
    _HAS_BIAS = False

try:
    from acquisition.pipeline import AcquisitionPipeline, AcqState
    _HAS_PIPELINE = True
except ImportError:
    _HAS_PIPELINE = False


class HardwareService(QObject):
    """
    Owns all hardware driver lifecycles and background poll threads.

    Signals
    -------
    camera_frame(frame)         — new live frame from the camera
    tec_status(index, status)   — periodic TEC poll result
    fpga_status(status)         — periodic FPGA poll result
    bias_status(status)         — periodic bias-source poll result
    stage_status(status)        — periodic stage poll result
    acq_progress(progress)      — acquisition pipeline progress update
    acq_complete(result)        — acquisition pipeline finished
    error(message)              — any device error (shown in status bar / log)
    log_message(message)        — informational messages for the log tab
    device_connected(key, ok)   — fired when a device connects or disconnects
                                   key in: camera, tec0, tec1, fpga, bias, stage
    """

    # ── Signals ───────────────────────────────────────────────────────
    camera_frame     = pyqtSignal(object)
    tec_status       = pyqtSignal(int, object)
    fpga_status      = pyqtSignal(object)
    bias_status      = pyqtSignal(object)
    stage_status     = pyqtSignal(object)
    acq_progress     = pyqtSignal(object)
    acq_complete     = pyqtSignal(object)
    error            = pyqtSignal(str)
    log_message      = pyqtSignal(str)
    device_connected = pyqtSignal(str, bool)   # (device_key, is_connected)
    startup_status          = pyqtSignal(str, bool, str)         # (key, ok, detail)
    tec_alarm               = pyqtSignal(int, str, float, float) # (idx, msg, actual, limit)
    tec_warning             = pyqtSignal(int, str, float, float) # (idx, msg, actual, limit)
    tec_alarm_clear         = pyqtSignal(int)                    # alarm/warning cleared
    emergency_stop_complete = pyqtSignal(str)                    # summary of what was stopped

    # ── Poll intervals ────────────────────────────────────────────────
    _TEC_POLL_S:   float = 0.50
    _FPGA_POLL_S:  float = 0.25
    _BIAS_POLL_S:  float = 0.25
    _STAGE_POLL_S: float = 0.10

    # ── Auto-reconnect policy ─────────────────────────────────────────
    # Consecutive poll failures before the device is declared offline
    # and a reconnect attempt begins.
    _MAX_CONSECUTIVE_ERRORS: int   = 3
    # First reconnect retry delay (subsequent delays double, capped at max)
    _RECONNECT_INITIAL_S:    float = 2.0
    _RECONNECT_MAX_S:        float = 30.0
    # Camera-specific: seconds without a frame before reconnect triggers
    _CAMERA_RECONNECT_TIMEOUT_S: float = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._stop_event = threading.Event()   # set to request all loops to exit
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

        # ── Camera preview back-pressure gate ─────────────────────────
        # camera_frame is a cross-thread Qt signal.  Every emit() serialises
        # the 4+ MB numpy array into Qt's queued-connection event queue.  If
        # the camera produces frames faster than the GUI thread drains them
        # (common in VMs / Parallels where the event loop is slower), the
        # queue grows without bound and the process runs out of memory.
        #
        # _cam_preview_free starts SET ("slot is free").  _run_camera() only
        # emits when it is set, then immediately clears it.  The GUI calls
        # ack_camera_frame() at the top of _on_frame() to re-set the flag,
        # allowing the next frame to be queued.  This guarantees at most ONE
        # camera frame is ever pending in Qt's event queue, regardless of the
        # camera frame rate or VM event-loop latency.
        self._cam_preview_free = threading.Event()
        self._cam_preview_free.set()   # initially free

        # Mirror device_connected Qt signal → event bus timeline.
        self.device_connected.connect(self._on_device_connected_evt)

        # Pull poll intervals from config (class-level values are defaults).
        try:
            poll = (config_module.get("hardware") or {}).get("polling", {})
            self._TEC_POLL_S   = float(poll.get("tec_interval_s",   self._TEC_POLL_S))
            self._FPGA_POLL_S  = float(poll.get("fpga_interval_s",  self._FPGA_POLL_S))
            self._BIAS_POLL_S  = float(poll.get("bias_interval_s",  self._BIAS_POLL_S))
            self._STAGE_POLL_S = float(poll.get("stage_interval_s", self._STAGE_POLL_S))
        except Exception:
            log.debug("HardwareService: polling config parse failed — using defaults",
                      exc_info=True)

    @pyqtSlot(str, bool)
    def _on_device_connected_evt(self, key: str, ok: bool) -> None:
        """Mirror device_connected signal into the event bus timeline."""
        if ok:
            emit_info("hardware.service", EVT_DEVICE_CONNECT,
                      f"{key}: connected", device=key)
        else:
            emit_warning("hardware.service", EVT_DEVICE_DISCONNECT,
                         f"{key}: disconnected or failed", device=key)

    def ack_camera_frame(self) -> None:
        """Signal that the GUI has finished with the last delivered frame.

        Call this at the TOP of the camera_frame slot (before doing any widget
        updates) so the next frame can be queued into Qt's event loop as soon
        as possible, minimising the chance of dropping frames while still
        preventing unbounded queue growth.
        """
        self._cam_preview_free.set()

    # ================================================================ #
    #  Public API                                                       #
    # ================================================================ #

    def start(self) -> None:
        """
        Start all hardware drivers and poll threads based on current config.
        Call once after the Qt application and MainWindow are created.
        Non-blocking — all connect/open calls happen on background threads.
        """
        self._stop_event.clear()
        hw = config_module.get("hardware")

        # Camera (also creates the AcquisitionPipeline)
        # Support new multi-camera list format: hardware.cameras
        _cameras_list = hw.get("cameras") if hw else None
        if _cameras_list and isinstance(_cameras_list, list):
            for _i, _cam_cfg in enumerate(_cameras_list):
                if not isinstance(_cam_cfg, dict):
                    continue
                _cam_type = str(_cam_cfg.get("camera_type", "tr")).lower()
                _name = f"hw.camera_{_cam_type}"
                self._launch(self._run_camera, args=(_cam_cfg,), name=_name)
        else:
            # Legacy single-camera format
            self._launch(self._run_camera, name="hw.camera")

        # TEC controllers
        for key in ["tec_meerstetter", "tec_atec"]:
            cfg = hw.get(key, {})
            if cfg.get("enabled", False):
                self._launch(self._run_tec, args=(key, cfg), name=f"hw.{key}")

        # FPGA
        fpga_cfg = hw.get("fpga", {})
        if fpga_cfg.get("enabled", False):
            self._launch(self._run_fpga, args=(fpga_cfg,), name="hw.fpga")

        # Bias source
        if _HAS_BIAS:
            bias_cfg = hw.get("bias", {})
            if bias_cfg.get("enabled", False):
                self._launch(self._run_bias, args=(bias_cfg,), name="hw.bias")

        # Stage
        if _HAS_STAGE:
            stage_cfg = hw.get("stage", {})
            if stage_cfg.get("enabled", False):
                self._launch(self._run_stage, args=(stage_cfg,), name="hw.stage")

    def start_demo(self) -> None:
        """
        Start all hardware using simulated drivers regardless of config.
        Called when the user chooses "Continue in Demo Mode" from the
        startup dialog, or when all hardware initialization fails.

        Emits startup_status for each simulated device so the startup
        dialog shows the correct result, then sets app_state.demo_mode=True.
        """
        log.info("HardwareService: starting in DEMO MODE (all simulated drivers)")
        self._stop_event.clear()
        app_state.demo_mode = True

        # Simulated configs — realistic defaults
        _sim_fpga   = {"driver": "simulated", "initial_freq_hz": 1000.0,
                       "initial_duty": 0.5}
        _sim_tec    = {"driver": "simulated", "initial_temp": 25.0, "noise": 0.02}
        _sim_bias   = {"driver": "simulated", "mode": "voltage", "level": 0.0}
        _sim_stage  = {"driver": "simulated", "speed_xy": 1000.0, "speed_z": 100.0}

        # Demo mode always shows both a TR and an IR camera so users can be
        # trained on the camera-selection workflow without real hardware.
        _sim_tr = {"driver": "simulated", "camera_type": "tr",
                   "model": "Basler acA1920-155um",
                   "width": 1920, "height": 1200,
                   "fps": 30, "exposure_us": 5000, "noise_level": 40}
        _sim_ir = {"driver": "simulated", "camera_type": "ir",
                   "model": "Microsanj IR Camera",
                   "width": 320, "height": 240,
                   "fps": 30, "exposure_us": 8333, "noise_level": 60}

        self._launch(self._run_camera, args=(_sim_tr,), name="hw.camera")
        self._launch(self._run_demo_ir_camera, args=(_sim_ir,),
                     name="hw.ir_camera")

        self._launch(self._run_demo_fpga,   args=(_sim_fpga,),  name="hw.fpga")
        self._launch(self._run_demo_tec,    args=(_sim_tec, "tec0"), name="hw.tec0")
        self._launch(self._run_demo_tec,    args=(_sim_tec, "tec1"), name="hw.tec1")
        self._launch(self._run_demo_bias,   args=(_sim_bias,),  name="hw.bias")
        self._launch(self._run_demo_stage,  args=(_sim_stage,), name="hw.stage")

    def _run_demo_ir_camera(self, cfg: dict):
        """IR camera demo thread — creates a second simulated camera for hybrid demo mode."""
        from hardware.cameras.simulated import SimulatedDriver
        try:
            ir_cam = SimulatedDriver(cfg)
            ir_cam.open()
            ir_cam.start()
            app_state.ir_cam = ir_cam
            detail = f"{ir_cam.info.model}  {ir_cam.info.width}×{ir_cam.info.height}"
            self.log_message.emit(
                f"IR Camera: simulated | {ir_cam.info.model} "
                f"| {ir_cam.info.width}×{ir_cam.info.height}")
            self.device_connected.emit("ir_camera", True)
            self.startup_status.emit("ir_camera", True, detail)
        except Exception as e:
            self.startup_status.emit("ir_camera", False, str(e)[:60])
            log.error("HardwareService IR camera demo init: %s", e, exc_info=True)

    def _run_demo_fpga(self, cfg: dict):
        """FPGA demo thread — uses simulated driver, overrides config."""
        from hardware.fpga.simulated import SimulatedFpga
        try:
            fpga = SimulatedFpga(cfg)
            fpga.open()
            fpga.start()
            app_state.fpga = fpga
            if app_state.pipeline and _HAS_PIPELINE:
                app_state.pipeline.update_hardware(fpga=fpga, bias=app_state.bias)
            self.log_message.emit("FPGA: demo mode (simulated)")
            self.device_connected.emit("fpga", True)
            self.startup_status.emit("fpga", True, "Simulated")
        except Exception as e:
            self.startup_status.emit("fpga", False, str(e)[:60])
            return
        while not self._stop_event.is_set():
            try:
                from hardware.fpga.base import FpgaStatus
                self.fpga_status.emit(fpga.get_status())
            except Exception as e:
                from hardware.fpga.base import FpgaStatus
                self.fpga_status.emit(FpgaStatus(error=str(e)))
            self._stop_event.wait(timeout=self._FPGA_POLL_S)

    def _run_demo_tec(self, cfg: dict, tec_key: str):
        """TEC demo thread — uses simulated driver."""
        from hardware.tec.simulated import SimulatedTec
        try:
            tec = SimulatedTec(cfg)
            tec.connect()
            tec.enable()
            idx = app_state.add_tec(tec)
            self.log_message.emit(f"TEC {idx+1}: demo mode (simulated)")
            self.device_connected.emit(tec_key, True)
            self.startup_status.emit(tec_key, True, "Simulated")
        except Exception as e:
            self.startup_status.emit(tec_key, False, str(e)[:60])
            return

        from hardware.thermal_guard import ThermalGuard
        guard = ThermalGuard(
            index      = idx,
            tec        = tec,
            cfg        = cfg,
            on_alarm   = lambda i, msg, a, l: self.tec_alarm.emit(i, msg, a, l),
            on_warning = lambda i, msg, a, l: self.tec_warning.emit(i, msg, a, l),
            on_clear   = lambda i: self.tec_alarm_clear.emit(i),
        )
        app_state.set_tec_guard(idx, guard)

        while not self._stop_event.is_set():
            try:
                status = tec.get_status()
                guard.check(status)
                self.tec_status.emit(idx, status)
            except Exception as e:
                from hardware.tec.base import TecStatus
                self.tec_status.emit(idx, TecStatus(error=str(e)))
            self._stop_event.wait(timeout=self._TEC_POLL_S)

    def _run_demo_bias(self, cfg: dict):
        """Bias source demo thread — uses simulated driver."""
        from hardware.bias.simulated import SimulatedBias
        try:
            bias = SimulatedBias(cfg)
            bias.connect()
            app_state.bias = bias
            self.log_message.emit("Bias: demo mode (simulated)")
            self.device_connected.emit("bias", True)
            self.startup_status.emit("bias", True, "Simulated")
        except Exception as e:
            self.startup_status.emit("bias", False, str(e)[:60])
            return
        while not self._stop_event.is_set():
            try:
                self.bias_status.emit(bias.get_status())
            except Exception as e:
                from hardware.bias.base import BiasStatus
                self.bias_status.emit(BiasStatus(error=str(e)))
            self._stop_event.wait(timeout=self._BIAS_POLL_S)

    def _run_demo_stage(self, cfg: dict):
        """Stage demo thread — uses simulated driver."""
        from hardware.stage.simulated import SimulatedStage
        try:
            stage = SimulatedStage(cfg)
            stage.connect()
            app_state.stage = stage
            self.log_message.emit("Stage: demo mode (simulated)")
            self.device_connected.emit("stage", True)
            self.startup_status.emit("stage", True, "Simulated")
        except Exception as e:
            self.startup_status.emit("stage", False, str(e)[:60])
            return
        while not self._stop_event.is_set():
            try:
                self.stage_status.emit(stage.get_status())
            except Exception as e:
                from hardware.stage.base import StageStatus
                self.stage_status.emit(StageStatus(error=str(e)))
            self._stop_event.wait(timeout=self._STAGE_POLL_S)

    def shutdown(self) -> None:
        """
        Deterministic shutdown:
          1. Signal all poll loops to stop.
          2. Abort any running acquisition.
          3. Join all background threads (up to 4 s each).
          4. Close every driver in safe order.
        """
        log.info("HardwareService: shutdown requested")
        self._stop_event.set()

        # Abort pipeline
        pipeline = app_state.pipeline
        if pipeline:
            try:
                pipeline.abort()
            except Exception as e:
                log.warning(f"HardwareService: pipeline abort: {e}")

        # Join threads
        for t in self._threads:
            t.join(timeout=4.0)
            if t.is_alive():
                log.warning(f"HardwareService: thread {t.name!r} did not stop in time")
        self._threads.clear()

        # Close drivers in safe order (TECs → stage → bias → FPGA → camera)
        self._safe_close_tecs()
        self._safe_close("stage",  lambda d: (d.stop(), d.disconnect()))
        self._safe_close("bias",   lambda d: d.disconnect())
        self._safe_close("fpga",   lambda d: (d.stop(), d.close()))
        self._safe_close("camera", lambda d: (d.stop(), d.close()))

        log.info("HardwareService: shutdown complete")

    def emergency_stop(self) -> None:
        """
        Emergency stop — immediately makes the instrument safe.

        Executed on a dedicated daemon thread so the UI never blocks.
        Does NOT shut down drivers or kill the application — the instrument
        stays connected and can be restarted after the user investigates.

        Stop sequence (fastest-to-safest order):
          1. Abort any running acquisition
          2. Disable bias source output (stops current flow through DUT)
          3. Disable all TEC outputs (stops heating/cooling)
          4. Stop stage motion
          5. Emit emergency_stop_complete with a summary
        """
        import threading as _t
        _t.Thread(target=self._do_emergency_stop, daemon=True,
                  name="hw.emergency_stop").start()

    def _do_emergency_stop(self) -> None:
        """Worker — runs off the main thread."""
        stopped = []
        failed  = []

        log.warning("HardwareService: *** EMERGENCY STOP ***")

        # 1. Abort acquisition pipeline
        pipeline = app_state.pipeline
        if pipeline:
            try:
                pipeline.abort()
                stopped.append("acquisition")
                log.info("HardwareService: E-STOP — acquisition aborted")
            except Exception as e:
                failed.append(f"acquisition ({e})")
                log.error(f"HardwareService: E-STOP — acquisition abort failed: {e}")

        # 2. Disable bias source (highest priority — stops current through DUT)
        bias = app_state.bias
        if bias:
            try:
                bias.disable()
                stopped.append("bias output")
                log.info("HardwareService: E-STOP — bias output disabled")
            except Exception as e:
                failed.append(f"bias ({e})")
                log.error(f"HardwareService: E-STOP — bias disable failed: {e}")

        # 3. Disable all TEC outputs
        for i, tec in enumerate(app_state.tecs):
            try:
                tec.disable()
                stopped.append(f"TEC {i+1}")
                log.info(f"HardwareService: E-STOP — TEC {i+1} disabled")
            except Exception as e:
                failed.append(f"TEC {i+1} ({e})")
                log.error(f"HardwareService: E-STOP — TEC {i+1} disable failed: {e}")

        # 4. Stop stage motion
        stage = app_state.stage
        if stage:
            try:
                stage.stop()
                stopped.append("stage")
                log.info("HardwareService: E-STOP — stage stopped")
            except Exception as e:
                failed.append(f"stage ({e})")
                log.error(f"HardwareService: E-STOP — stage stop failed: {e}")

        # Build summary
        summary_parts = []
        if stopped:
            summary_parts.append("Stopped: " + ", ".join(stopped))
        if failed:
            summary_parts.append("FAILED to stop: " + ", ".join(failed))
        summary = " | ".join(summary_parts) if summary_parts else "Nothing to stop"

        log.warning(f"HardwareService: E-STOP complete — {summary}")
        self.emergency_stop_complete.emit(summary)

    def reconnect_device(self, key: str) -> None:
        """
        Reconnect a single device by key without restarting the whole service.
        key in: 'camera', 'tec_meerstetter', 'tec_atec', 'fpga', 'bias', 'stage'
        """
        hw = config_module.get("hardware")
        cfg = hw.get(key, {})
        dispatch = {
            "camera":          lambda: self._launch(self._run_camera,       name="hw.camera"),
            "tec_meerstetter": lambda: self._launch(self._run_tec,  args=(key, cfg), name=f"hw.{key}"),
            "tec_atec":        lambda: self._launch(self._run_tec,  args=(key, cfg), name=f"hw.{key}"),
            "fpga":            lambda: self._launch(self._run_fpga, args=(cfg,),     name="hw.fpga"),
            "bias":            lambda: self._launch(self._run_bias, args=(cfg,),     name="hw.bias"),
            "stage":           lambda: self._launch(self._run_stage, args=(cfg,),   name="hw.stage"),
        }
        if key in dispatch:
            dispatch[key]()
        else:
            log.warning(f"HardwareService.reconnect_device: unknown key {key!r}")

    # ================================================================ #
    #  Control Surface — public API for UI to command hardware          #
    #  All methods are non-blocking: driver calls run on daemon threads #
    #  and errors are reported via self.error signal.                   #
    # ================================================================ #

    def _dispatch(self, fn, *args, **kwargs) -> None:
        """Execute fn(*args, **kwargs) on a daemon thread; emit error on failure."""
        name = getattr(fn, '__name__', 'ctrl')
        def _run():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                log.exception("HardwareService control call failed: %s", name)
                self.error.emit(str(e))
        threading.Thread(target=_run, daemon=True, name=f"hw.ctrl.{name}").start()

    # ── Camera ────────────────────────────────────────────────────────

    def cam_set_exposure(self, us: float) -> None:
        """Set camera exposure time in microseconds."""
        cam = app_state.cam
        if cam:
            self._dispatch(cam.set_exposure, float(us))

    def cam_set_gain(self, db: float) -> None:
        """Set camera gain in dB."""
        cam = app_state.cam
        if cam:
            self._dispatch(cam.set_gain, float(db))

    def cam_set_resolution(self, width: int, height: int) -> None:
        """
        Change the camera resolution at runtime.

        Only has effect for drivers where supports_runtime_resolution()
        returns True (currently only SimulatedDriver).  Silently ignored
        for real hardware so callers do not need to check the flag first.
        """
        cam = app_state.cam
        if cam and getattr(cam, "supports_runtime_resolution", lambda: False)():
            self._dispatch(cam.set_resolution, int(width), int(height))

    def cam_set_fps(self, fps: float) -> None:
        """Change the camera target frame rate at runtime (simulated cameras only)."""
        cam = app_state.cam
        if cam and getattr(cam, "supports_runtime_resolution", lambda: False)():
            self._dispatch(cam.set_fps, float(fps))

    # ── TEC ───────────────────────────────────────────────────────────

    def tec_enable(self, idx: int) -> None:
        """Enable TEC channel idx."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].enable)

    def tec_disable(self, idx: int) -> None:
        """Disable TEC channel idx."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].disable)

    def tec_set_target(self, idx: int, temp_c: float) -> None:
        """Set TEC channel idx target temperature in °C."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].set_target, temp_c)

    # ── FPGA ──────────────────────────────────────────────────────────

    def fpga_set_frequency(self, hz: float) -> None:
        """Set FPGA modulation frequency in Hz."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_frequency, hz)

    def fpga_set_duty_cycle(self, fraction: float) -> None:
        """Set FPGA duty cycle (0.0–1.0)."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_duty_cycle, fraction)

    def fpga_start(self) -> None:
        """Start FPGA modulation output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.start)

    def fpga_stop(self) -> None:
        """Stop FPGA modulation output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.stop)

    def fpga_set_stimulus(self, on: bool) -> None:
        """Enable or disable FPGA stimulus output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_stimulus, on)

    # ── Bias source ───────────────────────────────────────────────────

    def bias_set_mode(self, mode: str) -> None:
        """Set bias source mode ('voltage' or 'current')."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_mode, mode)

    def bias_set_level(self, value: float) -> None:
        """Set bias source output level (V or A depending on mode)."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_level, value)

    def bias_set_compliance(self, value: float) -> None:
        """Set bias source compliance limit."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_compliance, value)

    def bias_enable(self) -> None:
        """Enable bias source output."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.enable)

    def bias_disable(self) -> None:
        """Disable bias source output."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.disable)

    # ── Stage ─────────────────────────────────────────────────────────

    def stage_move_by(self, x: float = 0.0, y: float = 0.0,
                      z: float = 0.0) -> None:
        """Move stage by relative distances in μm."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.move_by, x=x, y=y, z=z, wait=False)

    def stage_move_to(self, x: float, y: float, z: float) -> None:
        """Move stage to absolute position in μm."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.move_to, x=x, y=y, z=z, wait=False)

    def stage_home(self, axes: str = "xyz") -> None:
        """Home stage axes ('xyz', 'xy', or 'z')."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.home, axes)

    def stage_stop(self) -> None:
        """Stop all stage motion immediately."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.stop)

    def stage_move_z(self, distance_um: float) -> None:
        """Move Z stage by distance_um (positive = up, negative = down)."""
        stage = app_state.stage
        if stage:
            if hasattr(stage, 'move_z'):
                self._dispatch(stage.move_z, distance_um)
            else:
                self._dispatch(stage.move_by, z=distance_um, wait=False)

    # ================================================================ #
    #  Internal thread launchers                                        #
    # ================================================================ #

    def _connect_with_retry(self, connect_fn, *, label: str,
                             max_retries: int = 3,
                             initial_delay_s: float = 2.0) -> None:
        """
        Call *connect_fn()* up to *max_retries* times with exponential backoff.

        Returns silently on first success.
        Raises the last exception if all attempts fail.
        Sleep is interruptible via _stop_event so shutdown is instant.
        """
        delay    = initial_delay_s
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            if self._stop_event.is_set():
                raise RuntimeError("Service stopped during connect retry")
            try:
                t0 = time.time()
                connect_fn()
                log.info("[%s] Connected (attempt %d/%.2fs)",
                         label, attempt, time.time() - t0)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    log.warning(
                        "[%s] Attempt %d/%d failed: %s  — retrying in %.1fs …",
                        label, attempt, max_retries, exc, delay)
                    # Interruptible sleep: wakes immediately if service stops.
                    self._stop_event.wait(timeout=delay)
                    delay = min(delay * 1.5, 30.0)   # cap at 30 s
                else:
                    log.error("[%s] All %d attempts failed. Last error: %s",
                              label, max_retries, exc)

        raise last_exc  # type: ignore[misc]

    def _launch(self, target, args=(), name="hw.thread") -> threading.Thread:
        t = threading.Thread(target=target, args=args, name=name, daemon=True)
        with self._lock:
            self._threads.append(t)
        t.start()
        return t

    def _reconnect_loop(self, device_key: str, reconnect_fn, label: str) -> bool:
        """
        Repeatedly call *reconnect_fn()* with exponential back-off until it
        succeeds or the service stops.

        Parameters
        ----------
        device_key  : signal key ('camera', 'tec0', 'fpga', 'bias', 'stage')
        reconnect_fn: callable — must raise on failure, return on success
        label       : human-readable name for log messages

        Returns
        -------
        True  — reconnected successfully
        False — _stop_event was set; caller should return without reconnecting
        """
        delay   = self._RECONNECT_INITIAL_S
        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            try:
                reconnect_fn()
                log.info("[%s] Auto-reconnect succeeded (attempt %d)", label, attempt)
                self.device_connected.emit(device_key, True)
                self.log_message.emit(f"{label}: reconnected automatically")
                return True
            except Exception as exc:
                log.warning("[%s] Reconnect attempt %d failed: %s — retry in %.0f s",
                            label, attempt, exc, delay)
            # Interruptible sleep: wakes instantly when service shuts down
            self._stop_event.wait(timeout=delay)
            delay = min(delay * 1.5, self._RECONNECT_MAX_S)
        return False

    # ── Camera + pipeline ─────────────────────────────────────────────

    def _run_camera(self, cam_cfg: dict = None):
        """Camera grab thread.

        Parameters
        ----------
        cam_cfg : dict, optional
            Camera config dict.  When None (legacy single-camera mode) the
            config is read from hardware.camera in config.yaml.
            When provided (multi-camera list mode) the dict is used directly —
            camera_type "ir" routes the driver to app_state.ir_cam instead of
            app_state.cam.
        """
        if cam_cfg is None:
            cam_cfg = config_module.get("hardware", {}).get("camera", {})

        cam_type = str(cam_cfg.get("camera_type", "tr")).lower()
        is_ir    = cam_type == "ir"

        # In demo mode always use the simulated driver regardless of config.
        if app_state.demo_mode:
            cam_cfg = {
                "driver":      "simulated",
                "camera_type": cam_type,
                "model":       cam_cfg.get("model", ""),   # preserve for realistic names
                "width":       cam_cfg.get("width",       640 if not is_ir else 320),
                "height":      cam_cfg.get("height",      480 if not is_ir else 240),
                "fps":         cam_cfg.get("fps",         30),
                "exposure_us": cam_cfg.get("exposure_us", 5000),
                "noise_level": cam_cfg.get("noise_level", 40),
            }

        # Device key used for status / Connected-Devices header
        import config as _cfg_mod
        _imaging_sys = _cfg_mod.get("hardware", {}).get("imaging_system", "tr_only")
        _cam_key = ("ir_camera" if is_ir
                    else ("tr_camera" if _imaging_sys == "hybrid" else "camera"))

        try:
            cam = create_camera(cam_cfg)
            self._connect_with_retry(cam.open, label=_cam_key)
            cam.start()

            if is_ir:
                # IR camera goes into the secondary slot — no pipeline
                with app_state:
                    app_state.ir_cam = cam
            else:
                if _HAS_PIPELINE:
                    pipeline = AcquisitionPipeline(
                        cam,
                        fpga=app_state.fpga,
                        bias=app_state.bias)
                    pipeline.on_progress = lambda p: self.acq_progress.emit(p)
                    pipeline.on_complete = lambda r: self.acq_complete.emit(r)
                    pipeline.on_error    = lambda e: self.error.emit(e)
                    with app_state:
                        app_state.cam      = cam
                        app_state.pipeline = pipeline
                else:
                    with app_state:
                        app_state.cam = cam

            detail = f"{cam.info.model}  {cam.info.width}×{cam.info.height}"
            self.log_message.emit(
                f"Camera ({cam_type.upper()}): {cam.info.driver} | "
                f"{cam.info.model} | {cam.info.width}×{cam.info.height}")
            self.device_connected.emit(_cam_key, True)
            self.startup_status.emit(_cam_key, True, detail)

        except Exception as e:
            self.error.emit(f"Camera ({cam_type.upper()}): {e}")
            self.device_connected.emit(_cam_key, False)
            self.startup_status.emit(_cam_key, False, str(e)[:60])
            log.error("HardwareService camera (%s) init: %s", cam_type, e, exc_info=True)
            return

        # IR cameras don't need their own grab loop — the TR grab loop reads
        # app_state.cam (computed property) which returns ir_cam when the user
        # has selected the IR camera as active.
        if is_ir:
            return

        # Live-frame grab loop (TR / primary camera only)
        last_frame_t = time.monotonic()
        try:
            while not self._stop_event.is_set():
                pipeline = app_state.pipeline
                if pipeline and _HAS_PIPELINE and pipeline.state == AcqState.CAPTURING:
                    last_frame_t = time.monotonic()   # acquisition is producing frames
                    self._stop_event.wait(0.05)
                    continue
                cam = app_state.cam
                if cam is None:
                    self._stop_event.wait(0.1)
                    continue
                try:
                    frame = cam.grab(timeout_ms=500)
                    if frame:
                        # Only queue a preview frame when the GUI has finished
                        # with the previous one.  This keeps the Qt queued-
                        # connection event queue bounded to ≤1 frame at all
                        # times — critical on slow/VM hosts where the event loop
                        # runs at well below the camera frame rate.
                        if self._cam_preview_free.is_set():
                            self._cam_preview_free.clear()
                            self.camera_frame.emit(frame)
                        last_frame_t = time.monotonic()
                    elif (time.monotonic() - last_frame_t
                            > self._CAMERA_RECONNECT_TIMEOUT_S):
                        raise RuntimeError(
                            f"No frame received for "
                            f"{self._CAMERA_RECONNECT_TIMEOUT_S:.0f} s")
                except Exception as e:
                    if (time.monotonic() - last_frame_t
                            > self._CAMERA_RECONNECT_TIMEOUT_S):
                        log.warning("Camera: %s — triggering reconnect", e)
                        import config as _cfg_mod
                        _is_hybrid = _cfg_mod.get("hardware", {}).get(
                            "imaging_system", "tr_only") == "hybrid"
                        self.device_connected.emit(
                            "tr_camera" if _is_hybrid else "camera", False)
                        self.error.emit(
                            "Camera: no frames received — reconnecting"
                            " automatically…")
                        def _cam_reconnect(cam=cam):
                            try:
                                cam.stop()
                                cam.close()
                            except Exception:
                                log.debug("Camera: cleanup failed before reconnect",
                                          exc_info=True)
                            cam.open()
                            cam.start()
                        if not self._reconnect_loop(
                                "camera", _cam_reconnect, "camera"):
                            return
                        last_frame_t = time.monotonic()
                    else:
                        log.debug("HardwareService camera grab: %s", e)
                    self._stop_event.wait(0.1)
        except Exception as e:
            log.error("[camera] Poll thread died unexpectedly: %s",
                      e, exc_info=True)
            self.error.emit(f"Camera: poll thread crashed — {e}")
            self.device_connected.emit("camera", False)

    # ── TEC ───────────────────────────────────────────────────────────

    def _run_tec(self, key: str, cfg: dict):
        tec_key = "tec0" if "meerstetter" in key else "tec1"
        try:
            tec = create_tec(cfg)
            self._connect_with_retry(tec.connect, label=key)
            idx = app_state.add_tec(tec)
            self.log_message.emit(f"{key}: connected ({cfg.get('driver','?')})")
            self.device_connected.emit(tec_key, True)
            self.startup_status.emit(tec_key, True, cfg.get('driver', 'connected'))
        except Exception as e:
            self.error.emit(f"{key}: {e}")
            self.device_connected.emit(tec_key, False)
            self.startup_status.emit(tec_key, False, str(e)[:60])
            log.error(f"HardwareService TEC init ({key}): {e}")
            return

        # Attach a ThermalGuard to this TEC channel
        from hardware.thermal_guard import ThermalGuard
        guard = ThermalGuard(
            index      = idx,
            tec        = tec,
            cfg        = cfg,
            on_alarm   = lambda i, msg, a, l: self.tec_alarm.emit(i, msg, a, l),
            on_warning = lambda i, msg, a, l: self.tec_warning.emit(i, msg, a, l),
            on_clear   = lambda i: self.tec_alarm_clear.emit(i),
        )
        # Expose guard so UI can call acknowledge() and update_limits()
        app_state.set_tec_guard(idx, guard)

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = tec.get_status()
                    guard.check(status)          # safety check every poll
                    self.tec_status.emit(idx, status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.tec.base import TecStatus
                    self.tec_status.emit(idx, TecStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit(tec_key, False)
                        self.error.emit(
                            f"{key}: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(tec=tec):
                            try:
                                tec.disconnect()
                            except Exception:
                                log.debug("TEC: cleanup failed before reconnect",
                                          exc_info=True)
                            tec.connect()
                        if not self._reconnect_loop(tec_key, _do_reconnect, key):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._TEC_POLL_S)
        except Exception as e:
            log.error("[%s] Poll thread died unexpectedly: %s", key, e, exc_info=True)
            self.error.emit(f"{key}: poll thread crashed — {e}")
            self.device_connected.emit(tec_key, False)

    # ── FPGA ──────────────────────────────────────────────────────────

    def _run_fpga(self, cfg: dict):
        try:
            fpga = create_fpga(cfg)
            self._connect_with_retry(fpga.open, label="fpga")
            app_state.fpga = fpga
            # Wire existing pipeline to FPGA if camera already up
            if app_state.pipeline and _HAS_PIPELINE:
                app_state.pipeline.update_hardware(fpga=fpga, bias=app_state.bias)
            self.log_message.emit(f"FPGA: open ({cfg.get('driver','?')})")
            self.device_connected.emit("fpga", True)
            self.startup_status.emit("fpga", True, cfg.get('driver', 'connected'))
        except Exception as e:
            self.error.emit(f"FPGA: {e}")
            self.device_connected.emit("fpga", False)
            self.startup_status.emit("fpga", False, str(e)[:60])
            log.error(f"HardwareService FPGA init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = fpga.get_status()
                    self.fpga_status.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.fpga.base import FpgaStatus
                    self.fpga_status.emit(FpgaStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("fpga", False)
                        self.error.emit(
                            f"FPGA: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(fpga=fpga):
                            try:
                                fpga.stop()
                                fpga.close()
                            except Exception:
                                log.debug("FPGA: cleanup failed before reconnect",
                                          exc_info=True)
                            fpga.open()
                            fpga.start()
                        if not self._reconnect_loop("fpga", _do_reconnect, "fpga"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._FPGA_POLL_S)
        except Exception as e:
            log.error("[fpga] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"FPGA: poll thread crashed — {e}")
            self.device_connected.emit("fpga", False)

    # ── Bias source ───────────────────────────────────────────────────

    def _run_bias(self, cfg: dict):
        try:
            bias = create_bias(cfg)
            self._connect_with_retry(bias.connect, label="bias")
            app_state.bias = bias
            if app_state.pipeline and _HAS_PIPELINE and app_state.fpga is None:
                app_state.pipeline.update_hardware(fpga=None, bias=bias)
            self.log_message.emit(f"Bias: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("bias", True)
            self.startup_status.emit("bias", True, cfg.get('driver', 'connected'))
        except Exception as e:
            self.error.emit(f"Bias: {e}")
            self.device_connected.emit("bias", False)
            self.startup_status.emit("bias", False, str(e)[:60])
            log.error(f"HardwareService bias init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = bias.get_status()
                    self.bias_status.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.bias.base import BiasStatus
                    self.bias_status.emit(BiasStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("bias", False)
                        self.error.emit(
                            f"Bias: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(bias=bias):
                            try:
                                bias.disconnect()
                            except Exception:
                                log.debug("Bias: cleanup failed before reconnect",
                                          exc_info=True)
                            bias.connect()
                        if not self._reconnect_loop("bias", _do_reconnect, "bias"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._BIAS_POLL_S)
        except Exception as e:
            log.error("[bias] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"Bias: poll thread crashed — {e}")
            self.device_connected.emit("bias", False)

    # ── Stage ─────────────────────────────────────────────────────────

    def _run_stage(self, cfg: dict):
        try:
            stage = create_stage(cfg)
            self._connect_with_retry(stage.connect, label="stage")
            app_state.stage = stage
            self.log_message.emit(f"Stage: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("stage", True)
            self.startup_status.emit("stage", True, cfg.get('driver', 'connected'))
        except Exception as e:
            self.error.emit(f"Stage: {e}")
            self.device_connected.emit("stage", False)
            self.startup_status.emit("stage", False, str(e)[:60])
            log.error(f"HardwareService stage init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = stage.get_status()
                    self.stage_status.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.stage.base import StageStatus
                    self.stage_status.emit(StageStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("stage", False)
                        self.error.emit(
                            f"Stage: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(stage=stage):
                            try:
                                stage.stop()
                                stage.disconnect()
                            except Exception:
                                log.debug("Stage: cleanup failed before reconnect",
                                          exc_info=True)
                            stage.connect()
                        if not self._reconnect_loop("stage", _do_reconnect, "stage"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._STAGE_POLL_S)
        except Exception as e:
            log.error("[stage] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"Stage: poll thread crashed — {e}")
            self.device_connected.emit("stage", False)

    # ================================================================ #
    #  Safe close helpers                                               #
    # ================================================================ #

    def _safe_close(self, attr: str, close_fn):
        """Close a single device stored in app_state by attribute name."""
        driver = getattr(app_state, attr, None)
        if driver is None:
            return
        try:
            close_fn(driver)
            log.info(f"HardwareService: {attr} closed")
        except Exception as e:
            log.warning(f"HardwareService: {attr} close error: {e}")

    def _safe_close_tecs(self):
        for i, tec in enumerate(app_state.tecs):
            try:
                tec.disconnect()
                log.info(f"HardwareService: TEC {i} disconnected")
            except Exception as e:
                log.warning(f"HardwareService: TEC {i} disconnect error: {e}")
