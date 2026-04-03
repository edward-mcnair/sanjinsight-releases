"""
hardware/services/camera_service.py

Camera device service — owns camera lifecycle, grab loops, and control surface.
"""

from __future__ import annotations

import logging
import time
import threading

from PyQt5.QtCore import pyqtSignal

from hardware.services.base_device_service import BaseDeviceService
from hardware.app_state import app_state
from hardware.cameras.factory import create_camera

try:
    from acquisition.pipeline import AcquisitionPipeline, AcqState
    _HAS_PIPELINE = True
except ImportError:
    _HAS_PIPELINE = False

log = logging.getLogger(__name__)


class CameraService(BaseDeviceService):
    """Camera grab loops, demo init, and control-surface methods."""

    # -- Camera-specific signals -------------------------------------------
    frame_ready  = pyqtSignal(object)
    acq_progress = pyqtSignal(object)
    acq_complete = pyqtSignal(object)

    # Camera-specific: seconds without a frame before reconnect triggers
    _CAMERA_RECONNECT_TIMEOUT_S: float = 10.0

    def __init__(self, stop_event: threading.Event, parent=None):
        super().__init__(stop_event, parent)
        # -- Camera preview back-pressure gate -----------------------------
        self._cam_preview_free = threading.Event()
        self._cam_preview_free.set()   # initially free

    # ── Camera poll loops ─────────────────────────────────────────────

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
        import config as config_module

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
            dev_err = self._classify_and_emit(e, _cam_key)
            self.device_connected.emit(_cam_key, False)
            self.startup_status.emit(_cam_key, False, dev_err.short_message)
            log.error("CameraService camera (%s) init: %s", cam_type, e, exc_info=True)
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
                    self._stop_event.wait(0.01)
                    continue
                cam = app_state.cam
                if cam is None:
                    self._stop_event.wait(0.1)
                    continue
                try:
                    _grab_t0 = time.monotonic()
                    frame = cam.grab(timeout_ms=500)
                    if frame:
                        # Only queue a preview frame when the GUI has finished
                        # with the previous one.  This keeps the Qt queued-
                        # connection event queue bounded to ≤1 frame at all
                        # times — critical on slow/VM hosts where the event loop
                        # runs at well below the camera frame rate.
                        if self._cam_preview_free.is_set():
                            self._cam_preview_free.clear()
                            self.frame_ready.emit(frame)
                        last_frame_t = time.monotonic()
                        # Throttle heartbeat to ~1/s (not every frame)
                        if last_frame_t - getattr(self, '_last_cam_hb', 0) > 1.0:
                            self._emit_heartbeat("camera", last_frame_t - _grab_t0)
                            self._last_cam_hb = last_frame_t
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
                        log.debug("CameraService camera grab: %s", e)
                    self._stop_event.wait(0.1)
        except Exception as e:
            log.error("[camera] Poll thread died unexpectedly: %s",
                      e, exc_info=True)
            self.error.emit(f"Camera: poll thread crashed — {e}")
            self.device_connected.emit("camera", False)

    def _run_camera_idle(self):
        """Grab loop for Device-Manager-injected cameras.

        Unlike _run_camera(), this does NOT open or start a driver.  It
        simply waits for app_state.cam to become non-None (set by
        DeviceManager._inject_into_app) and then delivers frames exactly
        as the normal grab loop does.
        """
        last_frame_t = time.monotonic()
        while not self._stop_event.is_set():
            cam = app_state.cam
            if cam is None:
                self._stop_event.wait(0.1)
                continue
            try:
                frame = cam.grab(timeout_ms=500)
                if frame:
                    if self._cam_preview_free.is_set():
                        self._cam_preview_free.clear()
                        self.frame_ready.emit(frame)
                    last_frame_t = time.monotonic()
            except Exception as e:
                log.debug("CameraService idle camera grab: %s", e)
                self._stop_event.wait(0.1)

    # ── Demo ──────────────────────────────────────────────────────────

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
            dev_err = self._classify_and_emit(e, "ir_camera")
            self.startup_status.emit("ir_camera", False, dev_err.short_message)
            log.error("CameraService IR camera demo init: %s", e, exc_info=True)

    # ── Control surface ───────────────────────────────────────────────

    def ack_camera_frame(self) -> None:
        """Signal that the GUI has finished with the last delivered frame.

        Call this at the TOP of the camera_frame slot (before doing any widget
        updates) so the next frame can be queued into Qt's event loop as soon
        as possible, minimising the chance of dropping frames while still
        preventing unbounded queue growth.
        """
        self._cam_preview_free.set()

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
