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
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

import config as config_module
from hardware.app_state import app_state
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

    # ── Poll intervals ────────────────────────────────────────────────
    _TEC_POLL_S:   float = 0.50
    _FPGA_POLL_S:  float = 0.25
    _BIAS_POLL_S:  float = 0.25
    _STAGE_POLL_S: float = 0.10

    def __init__(self, parent=None):
        super().__init__(parent)

        self._stop_event = threading.Event()   # set to request all loops to exit
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

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
    #  Internal thread launchers                                        #
    # ================================================================ #

    def _launch(self, target, args=(), name="hw.thread") -> threading.Thread:
        t = threading.Thread(target=target, args=args, name=name, daemon=True)
        with self._lock:
            self._threads.append(t)
        t.start()
        return t

    # ── Camera + pipeline ─────────────────────────────────────────────

    def _run_camera(self):
        cfg = config_module.get("hardware").get("camera", {})
        try:
            cam = create_camera(cfg)
            cam.open()
            cam.start()

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

            self.log_message.emit(
                f"Camera: {cam.info.driver} | {cam.info.model} "
                f"| {cam.info.width}×{cam.info.height}")
            self.device_connected.emit("camera", True)

        except Exception as e:
            self.error.emit(f"Camera: {e}")
            self.device_connected.emit("camera", False)
            log.error(f"HardwareService camera init: {e}", exc_info=True)
            return

        # Live-frame grab loop
        while not self._stop_event.is_set():
            pipeline = app_state.pipeline
            if pipeline and _HAS_PIPELINE and pipeline.state == AcqState.CAPTURING:
                time.sleep(0.05)
                continue
            cam = app_state.cam
            if cam is None:
                time.sleep(0.1)
                continue
            try:
                frame = cam.grab(timeout_ms=500)
                if frame:
                    self.camera_frame.emit(frame)
            except Exception as e:
                log.debug(f"HardwareService camera grab: {e}")
                time.sleep(0.1)

    # ── TEC ───────────────────────────────────────────────────────────

    def _run_tec(self, key: str, cfg: dict):
        tec_key = "tec0" if "meerstetter" in key else "tec1"
        try:
            tec = create_tec(cfg)
            tec.connect()
            idx = app_state.add_tec(tec)
            self.log_message.emit(f"{key}: connected ({cfg.get('driver','?')})")
            self.device_connected.emit(tec_key, True)
        except Exception as e:
            self.error.emit(f"{key}: {e}")
            self.device_connected.emit(tec_key, False)
            log.error(f"HardwareService TEC init ({key}): {e}")
            return

        while not self._stop_event.is_set():
            try:
                status = tec.get_status()
                self.tec_status.emit(idx, status)
            except Exception as e:
                from hardware.tec.base import TecStatus
                self.tec_status.emit(idx, TecStatus(error=str(e)))
            time.sleep(self._TEC_POLL_S)

    # ── FPGA ──────────────────────────────────────────────────────────

    def _run_fpga(self, cfg: dict):
        try:
            fpga = create_fpga(cfg)
            fpga.open()
            app_state.fpga = fpga
            # Wire existing pipeline to FPGA if camera already up
            if app_state.pipeline and _HAS_PIPELINE:
                app_state.pipeline.update_hardware(fpga=fpga, bias=app_state.bias)
            self.log_message.emit(f"FPGA: open ({cfg.get('driver','?')})")
            self.device_connected.emit("fpga", True)
        except Exception as e:
            self.error.emit(f"FPGA: {e}")
            self.device_connected.emit("fpga", False)
            log.error(f"HardwareService FPGA init: {e}")
            return

        while not self._stop_event.is_set():
            try:
                status = fpga.get_status()
                self.fpga_status.emit(status)
            except Exception as e:
                from hardware.fpga.base import FpgaStatus
                self.fpga_status.emit(FpgaStatus(error=str(e)))
            time.sleep(self._FPGA_POLL_S)

    # ── Bias source ───────────────────────────────────────────────────

    def _run_bias(self, cfg: dict):
        try:
            bias = create_bias(cfg)
            bias.connect()
            app_state.bias = bias
            if app_state.pipeline and _HAS_PIPELINE and app_state.fpga is None:
                app_state.pipeline.update_hardware(fpga=None, bias=bias)
            self.log_message.emit(f"Bias: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("bias", True)
        except Exception as e:
            self.error.emit(f"Bias: {e}")
            self.device_connected.emit("bias", False)
            log.error(f"HardwareService bias init: {e}")
            return

        while not self._stop_event.is_set():
            try:
                status = bias.get_status()
                self.bias_status.emit(status)
            except Exception as e:
                from hardware.bias.base import BiasStatus
                self.bias_status.emit(BiasStatus(error=str(e)))
            time.sleep(self._BIAS_POLL_S)

    # ── Stage ─────────────────────────────────────────────────────────

    def _run_stage(self, cfg: dict):
        try:
            stage = create_stage(cfg)
            stage.connect()
            app_state.stage = stage
            self.log_message.emit(f"Stage: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("stage", True)
        except Exception as e:
            self.error.emit(f"Stage: {e}")
            self.device_connected.emit("stage", False)
            log.error(f"HardwareService stage init: {e}")
            return

        while not self._stop_event.is_set():
            try:
                status = stage.get_status()
                self.stage_status.emit(status)
            except Exception as e:
                from hardware.stage.base import StageStatus
                self.stage_status.emit(StageStatus(error=str(e)))
            time.sleep(self._STAGE_POLL_S)

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
