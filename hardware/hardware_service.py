"""
hardware/hardware_service.py

HardwareService
===============
Central owner of all hardware device lifecycles for SanjINSIGHT.

Responsibilities
----------------
  * Instantiate and connect every driver (camera, TEC x2, FPGA, bias, stage)
    from config.yaml using the existing factory functions.
  * Start and supervise all poll/capture background threads.
  * Expose PyQt5 signals that the rest of the UI can connect to (status updates,
    new frames, errors, log messages) -- identical signals to what main_app.py
    emitted directly before the refactor.
  * Provide a clean shutdown() that stops all threads and closes all drivers
    in the correct order.
  * Expose connect_device() / disconnect_device() so the Device Manager dialog
    can reconnect individual devices without restarting the app.

Design principles
-----------------
  * MainWindow does NOT touch drivers directly -- it only connects signals and
    calls service methods.
  * All driver creation / open / connect calls happen on background threads to
    avoid blocking the Qt event loop.
  * The global `app_state` object is still updated by this service so legacy
    code that reads app_state.cam etc. continues to work unchanged.
  * The global `running` flag in main_app.py is replaced by an internal
    threading.Event so shutdown is deterministic.
  * Device-specific logic lives in child service classes under
    hardware/services/.  HardwareService creates them, forwards their
    signals for backward compatibility, and delegates all control-surface
    methods.
"""

from __future__ import annotations

import logging
import threading
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

import config as config_module
from hardware.app_state import app_state
from events import (emit_info, emit_warning,
                    EVT_DEVICE_CONNECT, EVT_DEVICE_DISCONNECT)

from hardware.services.camera_service import CameraService
from hardware.services.tec_service import TecService
from hardware.services.fpga_service import FpgaService
from hardware.services.bias_service import BiasService
from hardware.services.stage_service import StageService

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
    camera_frame(frame)         -- new live frame from the camera
    tec_status(index, status)   -- periodic TEC poll result
    fpga_status(status)         -- periodic FPGA poll result
    bias_status(status)         -- periodic bias-source poll result
    stage_status(status)        -- periodic stage poll result
    acq_progress(progress)      -- acquisition pipeline progress update
    acq_complete(result)        -- acquisition pipeline finished
    error(message)              -- any device error (shown in status bar / log)
    log_message(message)        -- informational messages for the log tab
    device_connected(key, ok)   -- fired when a device connects or disconnects
                                   key in: camera, tec0, tec1, fpga, bias, stage
    """

    # -- Signals -----------------------------------------------------------
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

    def __init__(self, parent=None):
        super().__init__(parent)

        self._stop_event = threading.Event()   # set to request all loops to exit

        # -- Create child device services ----------------------------------
        self._camera_svc = CameraService(self._stop_event, parent=self)
        self._tec_svc    = TecService(self._stop_event, parent=self)
        self._fpga_svc   = FpgaService(self._stop_event, parent=self)
        self._bias_svc   = BiasService(self._stop_event, parent=self)
        self._stage_svc  = StageService(self._stop_event, parent=self)

        # -- Forward device-specific signals for backward compat -----------
        self._camera_svc.frame_ready.connect(self.camera_frame)
        self._camera_svc.acq_progress.connect(self.acq_progress)
        self._camera_svc.acq_complete.connect(self.acq_complete)
        self._tec_svc.status_update.connect(self.tec_status)
        self._tec_svc.alarm.connect(self.tec_alarm)
        self._tec_svc.warning.connect(self.tec_warning)
        self._tec_svc.alarm_clear.connect(self.tec_alarm_clear)
        self._fpga_svc.status_update.connect(self.fpga_status)
        self._bias_svc.status_update.connect(self.bias_status)
        self._stage_svc.status_update.connect(self.stage_status)

        # -- Forward common signals from all services ----------------------
        for svc in (self._camera_svc, self._tec_svc, self._fpga_svc,
                    self._bias_svc, self._stage_svc):
            svc.device_connected.connect(self.device_connected)
            svc.error.connect(self.error)
            svc.log_message.connect(self.log_message)
            svc.startup_status.connect(self.startup_status)

        # Mirror device_connected Qt signal -> event bus timeline.
        self.device_connected.connect(self._on_device_connected_evt)

    @pyqtSlot(str, bool)
    def _on_device_connected_evt(self, key: str, ok: bool) -> None:
        """Mirror device_connected signal into the event bus timeline."""
        if ok:
            emit_info("hardware.service", EVT_DEVICE_CONNECT,
                      f"{key}: connected", device=key)
        else:
            emit_warning("hardware.service", EVT_DEVICE_DISCONNECT,
                         f"{key}: disconnected or failed", device=key)

    # ================================================================ #
    #  Service properties                                               #
    # ================================================================ #

    @property
    def camera_service(self) -> CameraService:
        return self._camera_svc

    @property
    def tec_service(self) -> TecService:
        return self._tec_svc

    @property
    def fpga_service(self) -> FpgaService:
        return self._fpga_svc

    @property
    def bias_service(self) -> BiasService:
        return self._bias_svc

    @property
    def stage_service(self) -> StageService:
        return self._stage_svc

    # ================================================================ #
    #  Public API                                                       #
    # ================================================================ #

    def start(self, skip_cameras: bool = False) -> None:
        """
        Start all hardware drivers and poll threads based on current config.
        Call once after the Qt application and MainWindow are created.
        Non-blocking -- all connect/open calls happen on background threads.

        Parameters
        ----------
        skip_cameras : bool
            When True, skip camera init from config.yaml and start only
            the idle grab loop.  Use this when Device Manager auto-reconnect
            will handle camera connections -- prevents both paths from trying
            to open the same USB camera simultaneously ("exclusively opened"
            errors on Windows).  Non-camera devices (TEC, FPGA, bias, stage)
            are still started from config as usual.
        """
        self._stop_event.clear()
        hw = config_module.get("hardware")

        # Camera (also creates the AcquisitionPipeline)
        if skip_cameras:
            # Device Manager will inject camera drivers into app_state via
            # _inject_into_app.  Start only the idle grab loop which polls
            # app_state.cam and begins delivering frames as soon as a driver
            # appears -- no double-open race.
            log.info("HardwareService: skip_cameras=True -- starting idle "
                     "grab loop (Device Manager will handle camera connections)")
            self._camera_svc._cam_preview_free.set()
            self._camera_svc._launch(self._camera_svc._run_camera_idle,
                                     name="hw.camera_idle")
        else:
            # Support new multi-camera list format: hardware.cameras
            _cameras_list = hw.get("cameras") if hw else None
            if _cameras_list and isinstance(_cameras_list, list):
                for _i, _cam_cfg in enumerate(_cameras_list):
                    if not isinstance(_cam_cfg, dict):
                        continue
                    _cam_type = str(_cam_cfg.get("camera_type", "tr")).lower()
                    _name = f"hw.camera_{_cam_type}"
                    self._camera_svc._launch(self._camera_svc._run_camera,
                                             args=(_cam_cfg,), name=_name)
            else:
                # Legacy single-camera format
                self._camera_svc._launch(self._camera_svc._run_camera,
                                         name="hw.camera")

        # TEC controllers
        for key in ["tec_meerstetter", "tec_atec"]:
            cfg = hw.get(key, {})
            if cfg.get("enabled", False):
                self._tec_svc._launch(self._tec_svc._run_tec,
                                      args=(key, cfg), name=f"hw.{key}")

        # FPGA
        fpga_cfg = hw.get("fpga", {})
        if fpga_cfg.get("enabled", False):
            self._fpga_svc._launch(self._fpga_svc._run_fpga,
                                   args=(fpga_cfg,), name="hw.fpga")

        # Bias source
        if _HAS_BIAS:
            bias_cfg = hw.get("bias", {})
            if bias_cfg.get("enabled", False):
                self._bias_svc._launch(self._bias_svc._run_bias,
                                       args=(bias_cfg,), name="hw.bias")

        # Stage
        if _HAS_STAGE:
            stage_cfg = hw.get("stage", {})
            if stage_cfg.get("enabled", False):
                self._stage_svc._launch(self._stage_svc._run_stage,
                                        args=(stage_cfg,), name="hw.stage")

    def start_idle(self) -> None:
        """Restart just the camera grab loop without opening any driver from config.

        Call this after shutdown() when the Device Manager will populate
        app_state.cam / app_state.ir_cam directly via _inject_into_app.
        The grab loop polls those slots and starts delivering camera_frame
        signals as soon as a driver appears -- no driver re-initialisation needed.
        """
        self._stop_event.clear()
        self._camera_svc._cam_preview_free.set()   # reset back-pressure gate
        self._camera_svc._launch(self._camera_svc._run_camera_idle,
                                 name="hw.camera_idle")

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

        # Simulated configs -- realistic defaults
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
                   "fps": 30, "exposure_us": 5000, "noise_level": 12}
        _sim_ir = {"driver": "simulated", "camera_type": "ir",
                   "model": "Microsanj IR Camera",
                   "width": 320, "height": 240,
                   "fps": 30, "exposure_us": 8333, "noise_level": 60}

        self._camera_svc._launch(self._camera_svc._run_camera,
                                 args=(_sim_tr,), name="hw.camera")
        self._camera_svc._launch(self._camera_svc._run_demo_ir_camera,
                                 args=(_sim_ir,), name="hw.ir_camera")

        self._fpga_svc._launch(self._fpga_svc._run_demo_fpga,
                               args=(_sim_fpga,), name="hw.fpga")
        self._tec_svc._launch(self._tec_svc._run_demo_tec,
                              args=(_sim_tec, "tec0"), name="hw.tec0")
        self._tec_svc._launch(self._tec_svc._run_demo_tec,
                              args=(_sim_tec, "tec1"), name="hw.tec1")
        self._bias_svc._launch(self._bias_svc._run_demo_bias,
                               args=(_sim_bias,), name="hw.bias")
        self._stage_svc._launch(self._stage_svc._run_demo_stage,
                                args=(_sim_stage,), name="hw.stage")

        # Simulated Arduino GPIO / LED selector (lightweight — no child service)
        try:
            from hardware.arduino.simulated import SimulatedArduino
            gpio = SimulatedArduino({"driver": "simulated"})
            gpio.connect()
            app_state.gpio = gpio
            self.device_connected.emit("gpio", True)
            self.startup_status.emit("gpio", True, "Simulated")
        except Exception as exc:
            log.debug("Demo GPIO init failed: %s", exc, exc_info=True)

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

        # Join threads from all child services
        all_threads: list[threading.Thread] = []
        for svc in (self._camera_svc, self._tec_svc, self._fpga_svc,
                    self._bias_svc, self._stage_svc):
            all_threads.extend(svc._threads)

        for t in all_threads:
            t.join(timeout=4.0)
            if t.is_alive():
                log.warning(f"HardwareService: thread {t.name!r} did not stop in time")

        for svc in (self._camera_svc, self._tec_svc, self._fpga_svc,
                    self._bias_svc, self._stage_svc):
            svc._threads.clear()

        # Close drivers in safe order (TECs -> stage -> bias -> FPGA -> camera)
        self._safe_close_tecs()
        self._safe_close("stage",  lambda d: (d.stop(), d.disconnect()))
        self._safe_close("bias",   lambda d: d.disconnect())
        self._safe_close("fpga",   lambda d: (d.stop(), d.close()))
        self._safe_close("camera", lambda d: (d.stop(), d.close()))

        # Close GPIO (Arduino) if connected
        try:
            gpio = app_state.gpio
            if gpio is not None and gpio.is_connected:
                gpio.disconnect()
                app_state.gpio = None
        except Exception:
            log.debug("GPIO shutdown failed", exc_info=True)

        log.info("HardwareService: shutdown complete")

    def emergency_stop(self) -> None:
        """
        Emergency stop -- immediately makes the instrument safe.

        Executed on a dedicated daemon thread so the UI never blocks.
        Does NOT shut down drivers or kill the application -- the instrument
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
        """Worker -- runs off the main thread."""
        stopped = []
        failed  = []

        log.warning("HardwareService: *** EMERGENCY STOP ***")

        # 1. Abort acquisition pipeline
        pipeline = app_state.pipeline
        if pipeline:
            try:
                pipeline.abort()
                stopped.append("acquisition")
                log.info("HardwareService: E-STOP -- acquisition aborted")
            except Exception as e:
                failed.append(f"acquisition ({e})")
                log.error(f"HardwareService: E-STOP -- acquisition abort failed: {e}")

        # 2. Disable bias source (highest priority -- stops current through DUT)
        bias = app_state.bias
        if bias:
            try:
                bias.disable()
                stopped.append("bias output")
                log.info("HardwareService: E-STOP -- bias output disabled")
            except Exception as e:
                failed.append(f"bias ({e})")
                log.error(f"HardwareService: E-STOP -- bias disable failed: {e}")

        # 3. Disable all TEC outputs
        for i, tec in enumerate(app_state.tecs):
            try:
                tec.disable()
                stopped.append(f"TEC {i+1}")
                log.info(f"HardwareService: E-STOP -- TEC {i+1} disabled")
            except Exception as e:
                failed.append(f"TEC {i+1} ({e})")
                log.error(f"HardwareService: E-STOP -- TEC {i+1} disable failed: {e}")

        # 4. Stop stage motion
        stage = app_state.stage
        if stage:
            try:
                stage.stop()
                stopped.append("stage")
                log.info("HardwareService: E-STOP -- stage stopped")
            except Exception as e:
                failed.append(f"stage ({e})")
                log.error(f"HardwareService: E-STOP -- stage stop failed: {e}")

        # Build summary
        summary_parts = []
        if stopped:
            summary_parts.append("Stopped: " + ", ".join(stopped))
        if failed:
            summary_parts.append("FAILED to stop: " + ", ".join(failed))
        summary = " | ".join(summary_parts) if summary_parts else "Nothing to stop"

        log.warning(f"HardwareService: E-STOP complete -- {summary}")
        self.emergency_stop_complete.emit(summary)

    def reconnect_device(self, key: str) -> None:
        """
        Reconnect a single device by key without restarting the whole service.
        key in: 'camera', 'tec_meerstetter', 'tec_atec', 'fpga', 'bias', 'stage'
        """
        hw = config_module.get("hardware")
        cfg = hw.get(key, {})
        dispatch = {
            "camera":          lambda: self._camera_svc._launch(
                self._camera_svc._run_camera, name="hw.camera"),
            "tec_meerstetter": lambda: self._tec_svc._launch(
                self._tec_svc._run_tec, args=(key, cfg), name=f"hw.{key}"),
            "tec_atec":        lambda: self._tec_svc._launch(
                self._tec_svc._run_tec, args=(key, cfg), name=f"hw.{key}"),
            "fpga":            lambda: self._fpga_svc._launch(
                self._fpga_svc._run_fpga, args=(cfg,), name="hw.fpga"),
            "bias":            lambda: self._bias_svc._launch(
                self._bias_svc._run_bias, args=(cfg,), name="hw.bias"),
            "stage":           lambda: self._stage_svc._launch(
                self._stage_svc._run_stage, args=(cfg,), name="hw.stage"),
        }
        if key in dispatch:
            dispatch[key]()
        else:
            log.warning(f"HardwareService.reconnect_device: unknown key {key!r}")

    # ================================================================ #
    #  Control Surface -- thin forwarding to child services             #
    # ================================================================ #

    # Camera
    def ack_camera_frame(self) -> None:
        """Signal that the GUI has finished with the last delivered frame."""
        self._camera_svc.ack_camera_frame()

    def cam_set_exposure(self, us: float) -> None:
        """Set camera exposure time in microseconds."""
        self._camera_svc.cam_set_exposure(us)

    def cam_set_gain(self, db: float) -> None:
        """Set camera gain in dB."""
        self._camera_svc.cam_set_gain(db)

    def cam_set_resolution(self, width: int, height: int) -> None:
        """Change the camera resolution at runtime."""
        self._camera_svc.cam_set_resolution(width, height)

    def cam_set_fps(self, fps: float) -> None:
        """Change the camera target frame rate at runtime (simulated cameras only)."""
        self._camera_svc.cam_set_fps(fps)

    # TEC
    def tec_enable(self, idx: int) -> None:
        """Enable TEC channel idx."""
        self._tec_svc.tec_enable(idx)

    def tec_disable(self, idx: int) -> None:
        """Disable TEC channel idx."""
        self._tec_svc.tec_disable(idx)

    def tec_set_target(self, idx: int, temp_c: float) -> None:
        """Set TEC channel idx target temperature in C."""
        self._tec_svc.tec_set_target(idx, temp_c)

    # FPGA
    def fpga_set_frequency(self, hz: float) -> None:
        """Set FPGA modulation frequency in Hz."""
        self._fpga_svc.fpga_set_frequency(hz)

    def fpga_set_duty_cycle(self, fraction: float) -> None:
        """Set FPGA duty cycle (0.0-1.0)."""
        self._fpga_svc.fpga_set_duty_cycle(fraction)

    def fpga_start(self) -> None:
        """Start FPGA modulation output."""
        self._fpga_svc.fpga_start()

    def fpga_stop(self) -> None:
        """Stop FPGA modulation output."""
        self._fpga_svc.fpga_stop()

    def fpga_set_stimulus(self, on: bool) -> None:
        """Enable or disable FPGA stimulus output."""
        self._fpga_svc.fpga_set_stimulus(on)

    # Bias
    def bias_set_mode(self, mode: str) -> None:
        """Set bias source mode ('voltage' or 'current')."""
        self._bias_svc.bias_set_mode(mode)

    def bias_set_level(self, value: float) -> None:
        """Set bias source output level (V or A depending on mode)."""
        self._bias_svc.bias_set_level(value)

    def bias_set_compliance(self, value: float) -> None:
        """Set bias source compliance limit."""
        self._bias_svc.bias_set_compliance(value)

    def bias_enable(self) -> None:
        """Enable bias source output."""
        self._bias_svc.bias_enable()

    def bias_disable(self) -> None:
        """Disable bias source output."""
        self._bias_svc.bias_disable()

    # Stage
    def stage_move_by(self, x: float = 0.0, y: float = 0.0,
                      z: float = 0.0) -> None:
        """Move stage by relative distances in um."""
        self._stage_svc.stage_move_by(x, y, z)

    def stage_move_to(self, x: float, y: float, z: float) -> None:
        """Move stage to absolute position in um."""
        self._stage_svc.stage_move_to(x, y, z)

    def stage_home(self, axes: str = "xyz") -> None:
        """Home stage axes ('xyz', 'xy', or 'z')."""
        self._stage_svc.stage_home(axes)

    def stage_stop(self) -> None:
        """Stop all stage motion immediately."""
        self._stage_svc.stage_stop()

    def stage_move_z(self, distance_um: float) -> None:
        """Move Z stage by distance_um (positive = up, negative = down)."""
        self._stage_svc.stage_move_z(distance_um)

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
