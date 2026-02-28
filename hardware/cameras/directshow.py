"""
hardware/cameras/directshow.py

Camera driver for cameras accessible via Windows DirectShow (cv2.VideoCapture).
Use for: FLIR Boson thermal cameras, generic USB cameras, webcams.
NOT for the Basler acA1920-155um (it uses NI IMAQdx, not DirectShow).

Requires: pip install opencv-python

Config keys (under hardware.camera):
    device_index:   0       DirectShow device index (use find_camera.py to find it)
    width:          640     Requested width (driver may override)
    height:         512     Requested height
    fourcc:         "Y16 "  Four-character pixel format code
    exposure_us:    5000    Note: DirectShow exposure control is limited
    gain:           0.0
"""

import time
import numpy as np
import cv2
from typing import Optional

import logging
log = logging.getLogger(__name__)

from .base import CameraDriver, CameraFrame, CameraInfo


class DirectShowDriver(CameraDriver):
    """
    DirectShow camera driver via OpenCV.
    Works with FLIR Boson, FLIR Lepton, USB webcams, and any
    Windows DirectShow-compatible camera.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._cap    = None
        self._idx    = cfg.get("device_index", 0)
        self._W      = cfg.get("width",  640)
        self._H      = cfg.get("height", 512)
        self._fourcc = cfg.get("fourcc", "")   # e.g. "Y16 " for 16-bit mono

    def open(self) -> None:
        cap = cv2.VideoCapture(self._idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError(
                f"DirectShow device {self._idx} not found. "
                f"Run find_camera.py to identify the correct index.")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._H)

        if self._fourcc:
            cc = self._fourcc.ljust(4)[:4]
            cap.set(cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter.fourcc(*cc))

        # Read back actual resolution
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        self._cap  = cap
        self._W    = w
        self._H    = h
        self._open = True
        self._info = CameraInfo(
            driver    = "directshow",
            model     = self._cfg.get("model", f"DirectShow device {self._idx}"),
            width     = w,
            height    = h,
            bit_depth = 16 if "16" in self._fourcc else 8,
            max_fps   = cap.get(cv2.CAP_PROP_FPS),
        )

    def start(self) -> None:
        pass   # DirectShow streams automatically on VideoCapture open

    def stop(self) -> None:
        pass

    def close(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
        self._open = False

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None

        # Handle 16-bit frames (Y16 fourcc)
        if frame.dtype == np.uint8 and self._info.bit_depth == 16:
            # cv2 delivers 16-bit data as uint8 pairs — reinterpret
            raw = frame.view(np.uint16)
            if raw.ndim == 3:
                raw = raw[:, :, 0]
            try:
                raw = raw.reshape(self._H, self._W)
            except ValueError:
                return None
            data = raw.copy()
        elif frame.ndim == 3:
            # 8-bit color → grayscale uint16
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            data = gray.astype(np.uint16) << 4   # scale to 12-bit range
        else:
            data = frame.astype(np.uint16)

        return CameraFrame(
            data        = data,
            frame_index = 0,
            exposure_us = self._cfg.get("exposure_us", 0.0),
            gain_db     = self._cfg.get("gain", 0.0),
            timestamp   = time.time(),
        )

    def set_exposure(self, microseconds: float) -> None:
        # DirectShow uses log2 exposure in seconds for some cameras
        # This is best-effort — not all DirectShow cameras support it
        self._cfg["exposure_us"] = microseconds
        seconds = microseconds / 1_000_000.0
        import math
        log2_val = math.log2(seconds) if seconds > 0 else -10
        self._cap.set(cv2.CAP_PROP_EXPOSURE, log2_val)
        log.debug(f"Exposure = {microseconds:.0f} us (DirectShow best-effort)")

    def set_gain(self, db: float) -> None:
        self._cfg["gain"] = db
        self._cap.set(cv2.CAP_PROP_GAIN, db)
        log.debug(f"Gain = {db:.1f} dB (DirectShow best-effort)")
