"""
hardware/cameras/pypylon.py

Camera driver for Basler cameras using the official pypylon SDK.
Use this when NI Vision Acquisition Software is NOT installed.
Requires: pip install pypylon  (and Basler Pylon SDK installed)

Config keys (under hardware.camera):
    serial:       ""       Leave blank to use first found camera
    exposure_us:  5000
    gain:         0.0
"""

import time
import logging
import numpy as np
from typing import Optional

from .base import CameraDriver, CameraFrame, CameraInfo

log = logging.getLogger(__name__)


class PylonDriver(CameraDriver):
    """
    Basler camera driver via official pypylon SDK.
    Full attribute control — no workarounds needed.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._cam    = None
        self._serial = cfg.get("serial", "")

    def open(self) -> None:
        try:
            from pypylon import pylon
        except ImportError:
            raise RuntimeError(
                "pypylon not installed. Run: pip install pypylon\n"
                "Also install Basler Pylon SDK from https://www.baslerweb.com")

        factory = pylon.TlFactory.GetInstance()
        devices = factory.EnumerateDevices()

        if not devices:
            raise RuntimeError(
                "No Basler cameras found. Check USB/GigE connection.")

        # Pick by serial if specified, otherwise first device
        device = None
        if self._serial:
            for d in devices:
                if d.GetSerialNumber() == self._serial:
                    device = d
                    break
            if device is None:
                raise RuntimeError(
                    f"Basler camera serial '{self._serial}' not found. "
                    f"Available: {[d.GetSerialNumber() for d in devices]}")
        else:
            device = devices[0]

        self._cam = pylon.InstantCamera(factory.CreateDevice(device))
        self._cam.Open()

        nm = self._cam.GetNodeMap()

        self._info = CameraInfo(
            driver    = "pypylon",
            model     = self._cam.GetDeviceInfo().GetModelName(),
            serial    = self._cam.GetDeviceInfo().GetSerialNumber(),
            width     = self._cam.Width.GetValue(),
            height    = self._cam.Height.GetValue(),
            bit_depth = 12,
            max_fps   = self._cam.ResultingFrameRate.GetValue()
                        if hasattr(self._cam, 'ResultingFrameRate') else 0.0,
        )
        self._open = True

    def start(self) -> None:
        self._cam.StartGrabbing(
            __import__('pypylon').pylon.GrabStrategy_LatestImageOnly)

    def stop(self) -> None:
        if self._cam and self._cam.IsGrabbing():
            self._cam.StopGrabbing()

    def close(self) -> None:
        if not self._open:
            return
        self.stop()
        self._cam.Close()
        self._open = False

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        if self._cam is None:
            return None
        from pypylon import pylon, genicam
        try:
            result = self._cam.RetrieveResult(
                timeout_ms, pylon.TimeoutHandling_ThrowException)
            if result.GrabSucceeded():
                data = result.Array.copy()
                idx  = result.ImageNumber
                result.Release()
                return CameraFrame(
                    data        = data.astype(np.uint16),
                    frame_index = idx,
                    exposure_us = self._cfg.get("exposure_us", 0.0),
                    gain_db     = self._cfg.get("gain", 0.0),
                    timestamp   = time.time(),
                )
            result.Release()
        except genicam.TimeoutException:
            # Normal during low-frame-rate acquisition; not an error
            log.debug("pypylon grab timeout (%d ms)", timeout_ms)
        except Exception as e:
            # Device disconnect, CRC error, or other hardware fault —
            # log it so the user can see what happened
            log.warning("pypylon grab error: %s", e)
        return None

    def set_exposure(self, microseconds: float) -> None:
        self._cfg["exposure_us"] = microseconds
        from pypylon import genicam
        node = self._cam.GetNodeMap().GetNode("ExposureTime")
        if node and node.IsWritable():
            genicam.IFloat(node).SetValue(float(microseconds))
            log.debug("ExposureTime = %.0f us", microseconds)

    def set_gain(self, db: float) -> None:
        self._cfg["gain"] = db
        from pypylon import genicam
        node = self._cam.GetNodeMap().GetNode("Gain")
        if node and node.IsWritable():
            genicam.IFloat(node).SetValue(float(db))
            log.debug("Gain = %.1f dB", db)

    def exposure_range(self) -> tuple:
        try:
            node = self._cam.GetNodeMap().GetNode("ExposureTime")
            from pypylon import genicam
            n = genicam.IFloat(node)
            return (n.GetMin(), n.GetMax())
        except Exception:
            return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        try:
            node = self._cam.GetNodeMap().GetNode("Gain")
            from pypylon import genicam
            n = genicam.IFloat(node)
            return (n.GetMin(), n.GetMax())
        except Exception:
            return (0.0, 24.0)
