"""
hardware/cameras/boson_driver.py

FLIR Boson thermal camera driver for SanjINSIGHT.

The Boson (320×256 or 640×512 uncooled LWIR microbolometer) exposes two
interfaces over a single USB connection:
  • Control channel — UART/serial via FLIR FSLP protocol (SDK commands)
  • Video channel   — USB Video Class (UVC); appears as a webcam on every OS

This driver:
  1. Opens the control channel with the bundled Boson Python SDK
     (hardware/cameras/boson/) using pure-Python serial (pyserial).
     No native DLL is required — useDll=False selects the PySerial FSLP path.
  2. Opens the video channel with cv2.VideoCapture.
  3. Maps the Boson's 14-bit radiometric output to a uint16 CameraFrame
     expected by the rest of SanjINSIGHT.

Config keys (under hardware.camera):
    driver:        "boson"
    serial_port:   "/dev/cu.usbmodemXXX"   # macOS  (or "COM3" on Windows)
    video_index:   0                        # cv2.VideoCapture device index
    width:         320                      # 320 or 640
    height:        256                      # 256 or 512
    fps:           60
    camera_type:   "ir"                     # always infrared for Boson

Requires: pyserial (already in requirements.txt), opencv-python.
"""

import time
import threading
import logging
from typing import Optional

import numpy as np

from .base import CameraDriver, CameraFrame, CameraInfo

log = logging.getLogger(__name__)

# ── Boson sensor geometry ─────────────────────────────────────────────────────
_BOSON_MODELS = {
    (320, 256): "Boson 320",
    (640, 512): "Boson 640",
}

# Default baud rate for the Boson UART control channel
_DEFAULT_BAUD = 921600


class BosonDriver(CameraDriver):
    """
    FLIR Boson thermal camera driver.

    Control is exercised via the bundled FLIR Boson Python SDK over serial
    (pure-Python FSLP — no DLL required, works on macOS, Windows, Linux).
    Video frames are captured via OpenCV's UVC backend, which is natively
    available on all supported platforms.
    """

    # ── Preflight ─────────────────────────────────────────────────────────────

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import cv2  # noqa: F401
        except ImportError:
            issues.append(
                "opencv-python is not installed.\n"
                "  Fix: pip install opencv-python"
            )
        try:
            import serial  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial is not installed.\n"
                "  Fix: pip install pyserial"
            )
        try:
            from hardware.cameras.boson.ClientFiles_Python.Client_API import pyClient  # noqa: F401
        except ImportError as exc:
            issues.append(
                f"FLIR Boson SDK not found in the installation: {exc}\n"
                "  The Boson SDK should be bundled — reinstall SanjINSIGHT."
            )
        return (len(issues) == 0, issues)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._serial_port  = cfg.get("serial_port", "")
        self._baud         = int(cfg.get("baud", _DEFAULT_BAUD))
        self._video_index  = int(cfg.get("video_index", 0))
        self._W            = int(cfg.get("width",  320))
        self._H            = int(cfg.get("height", 256))
        self._fps          = float(cfg.get("fps",  60.0))

        self._client       = None   # pyClient (SDK control)
        self._cap          = None   # cv2.VideoCapture (video)
        self._lock         = threading.Lock()
        self._frame_idx    = 0

        self._info = CameraInfo(
            driver      = "boson",
            model       = _BOSON_MODELS.get((self._W, self._H), "FLIR Boson"),
            serial      = "",
            width       = self._W,
            height      = self._H,
            bit_depth   = 14,
            max_fps     = self._fps,
            camera_type = cfg.get("camera_type", "ir"),
        )

    def open(self) -> None:
        if self._open:
            return

        import cv2

        # ── 1. Control channel ────────────────────────────────────────────────
        if self._serial_port:
            try:
                from hardware.cameras.boson.ClientFiles_Python.Client_API import pyClient
                from hardware.cameras.boson.CommunicationFiles.CommonFslp import (
                    CommonFslp, FSLP_TYPE_E,
                )
                fslp = CommonFslp.getFslp(
                    self._serial_port, self._baud,
                    FSLP_TYPE_E.FSLP_PY_SERIAL,
                )
                fslp.port.open()
                self._client = pyClient(fslp=fslp, useDll=False, ex=False)
                # Read serial number from camera
                result, sn = self._client.systemGetCameraSerialNumber()
                if str(result) == "FLR_RESULT.R_SUCCESS":
                    self._info.serial = str(sn)
                    log.info("Boson serial number: %s", self._info.serial)
            except Exception as exc:
                log.warning(
                    "Boson control channel failed on %s — "
                    "video-only mode (no SDK commands): %s",
                    self._serial_port, exc,
                )
                self._client = None
        else:
            log.info(
                "Boson: no serial_port configured — video-only mode. "
                "Set serial_port in config.yaml for full camera control."
            )

        # ── 2. Video channel ──────────────────────────────────────────────────
        cap = cv2.VideoCapture(self._video_index)
        if not cap.isOpened():
            if self._client:
                self._client.Close()
                self._client = None
            raise RuntimeError(
                f"FLIR Boson: could not open video device index {self._video_index}.\n"
                "Check:\n"
                "  1. Boson is connected via USB.\n"
                "  2. video_index in config.yaml matches the Boson UVC device.\n"
                "  3. On macOS, grant Camera access in System Preferences → Privacy."
            )

        # Configure video for raw 16-bit output (Y16 pixel format)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"Y16 "))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._H)
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)  # raw, no colour conversion

        self._cap   = cap
        self._open  = True
        log.info(
            "Boson opened: model=%s serial=%s video_index=%d",
            self._info.model, self._info.serial or "unknown", self._video_index,
        )

    def start(self) -> None:
        # VideoCapture begins delivering frames as soon as it's opened.
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        with self._lock:
            if self._client:
                try:
                    self._client.Close()
                except Exception:
                    pass
                self._client = None
            if self._cap:
                self._cap.release()
                self._cap = None
        self._open = False
        log.info("Boson closed")

    # ── Acquisition ───────────────────────────────────────────────────────────

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        import cv2
        deadline = time.monotonic() + timeout_ms / 1000.0
        with self._lock:
            if not self._cap or not self._cap.isOpened():
                return None
            while time.monotonic() < deadline:
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    break
            else:
                log.debug("Boson grab timeout (%d ms)", timeout_ms)
                return None

        # The Boson delivers 16-bit grayscale frames over UVC (Y16).
        # If OpenCV decodes to uint8 (AGC output mode), scale up to uint16.
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.dtype != np.uint16:
            frame = frame.astype(np.uint16) * 256  # 8→16-bit, preserves ordering

        self._frame_idx += 1
        return CameraFrame(
            data        = frame,
            frame_index = self._frame_idx,
            exposure_us = 0.0,   # Boson auto-exposes internally
            gain_db     = 0.0,
            timestamp   = time.time(),
        )

    # ── Attribute control ─────────────────────────────────────────────────────

    def set_exposure(self, microseconds: float) -> None:
        """
        Boson manages integration time internally (auto-exposure microbolometer).
        This is a no-op; the UI slider is intentionally not wired for Boson.
        """
        pass

    def set_gain(self, db: float) -> None:
        """Boson has no user-adjustable analog gain — no-op."""
        pass

    def exposure_range(self) -> tuple:
        return (0.0, 0.0)   # not applicable

    def gain_range(self) -> tuple:
        return (0.0, 0.0)   # not applicable

    # ── SDK passthrough ───────────────────────────────────────────────────────

    @property
    def sdk_client(self):
        """
        Direct access to the FLIR Boson pyClient for SDK commands.
        Returns None if the control channel is not open.

        Example:
            client = driver.sdk_client
            if client:
                result, temp = client.bosonGetCameraStatus()
        """
        return self._client

    def send_ffc(self) -> bool:
        """
        Trigger a Flat Field Correction (FFC / shutter correction).
        Returns True on success, False if the control channel is unavailable.
        """
        if not self._client:
            log.warning("Boson: FFC requested but control channel is not open")
            return False
        try:
            result = self._client.bosonRunFFC()
            ok = str(result) == "FLR_RESULT.R_SUCCESS"
            if ok:
                log.info("Boson: FFC triggered")
            else:
                log.warning("Boson: FFC returned %s", result)
            return ok
        except Exception as exc:
            log.error("Boson: FFC failed: %s", exc)
            return False
