"""
hardware/cameras/ni_imaqdx.py

Camera driver for cameras accessed via NI IMAQdx (NI Vision Acquisition Software).
On this system: Basler acA1920-155um connected through NI-IMAQdx as "cam4".

Attribute control uses ImaqdxAttr.exe (built once from ImaqdxAttr.cs)
which calls IMAQdxSetAttribute from C# P/Invoke — the only reliable way
to call NI's variadic C function from Python on x64 Windows.

Config keys (under hardware.camera):
    camera_name:  "cam4"        NI MAX device name
    exposure_us:  5000
    gain:         0.0
"""

import ctypes
import os
import subprocess
import time
import numpy as np
from typing import Optional

import logging
log = logging.getLogger(__name__)

from .base import CameraDriver, CameraFrame, CameraInfo

# NI IMAQdx error codes
_NO_ERROR = 0

# Path to the C# helper exe (same folder as this file's project root)
_EXE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ImaqdxAttr.exe")

# NI attribute names for Basler acA1920-155um
_ATTR_EXPOSURE = "CameraAttributes::AcquisitionControl::ExposureTime"
_ATTR_GAIN     = "CameraAttributes::AnalogControl::Gain"


class NiImaqdxDriver(CameraDriver):
    """
    NI IMAQdx camera driver.
    Works with any camera that NI Vision Acquisition Software supports.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._dll       = None
        self._session   = ctypes.c_uint32(0)
        self._cam_name  = cfg.get("camera_name", "cam4").encode()
        self._W         = cfg.get("width",  1920)
        self._H         = cfg.get("height", 1200)
        self._buf       = None
        self._buf_size  = self._W * self._H * 2   # uint16
        self._frame_num = ctypes.c_uint64(0)
        self._exe_warned = False

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def open(self) -> None:
        dll_paths = [
            r"C:\Windows\System32\niimaqdx.dll",
            r"C:\Program Files\National Instruments\Shared\NI-IMAQdx\niimaqdx.dll",
        ]
        for path in dll_paths:
            try:
                self._dll = ctypes.windll.LoadLibrary(path)
                break
            except OSError:
                continue

        if self._dll is None:
            raise RuntimeError(
                "niimaqdx.dll not found. Install NI Vision Acquisition Software.")

        self._buf     = (ctypes.c_uint8 * self._buf_size)()
        session       = ctypes.c_uint32(0)
        status        = self._dll.IMAQdxOpenCamera(
            self._cam_name, ctypes.c_int32(0), ctypes.byref(session))

        if status != _NO_ERROR:
            raise RuntimeError(
                f"IMAQdxOpenCamera failed: {status}  "
                f"(check NI MAX — camera name should be "
                f"'{self._cam_name.decode()}')")

        self._session = session
        self._open    = True
        self._info    = CameraInfo(
            driver    = "ni_imaqdx",
            model     = self._cfg.get("model", "Unknown (NI IMAQdx)"),
            width     = self._W,
            height    = self._H,
            bit_depth = 12,
        )

    def start(self) -> None:
        self._dll.IMAQdxConfigureAcquisition(
            self._session, ctypes.c_int32(1), ctypes.c_int32(3))
        self._dll.IMAQdxStartAcquisition(self._session)

    def stop(self) -> None:
        self._dll.IMAQdxStopAcquisition(self._session)
        self._dll.IMAQdxUnconfigureAcquisition(self._session)

    def close(self) -> None:
        if not self._open:
            return
        try:
            self.stop()
        except Exception:
            pass
        self._dll.IMAQdxCloseCamera(self._session)
        self._open = False

    # ---------------------------------------------------------------- #
    #  Acquisition                                                      #
    # ---------------------------------------------------------------- #

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        status = self._dll.IMAQdxGetImageData(
            self._session,
            self._buf,
            ctypes.c_uint32(self._buf_size),
            ctypes.c_int32(3),               # mode: GetNext
            ctypes.c_uint32(0),
            ctypes.byref(self._frame_num))

        if status != _NO_ERROR:
            return None

        data = np.frombuffer(self._buf, dtype=np.uint16).reshape(
            self._H, self._W).copy()

        return CameraFrame(
            data        = data,
            frame_index = int(self._frame_num.value),
            exposure_us = self._cfg.get("exposure_us", 0.0),
            gain_db     = self._cfg.get("gain", 0.0),
            timestamp   = time.time(),
        )

    # ---------------------------------------------------------------- #
    #  Attribute control (via ImaqdxAttr.exe)                          #
    # ---------------------------------------------------------------- #

    def _set_attr(self, attr: str, value: float) -> bool:
        """
        Release session → call ImaqdxAttr.exe (C# P/Invoke) → reopen.
        This is required because:
          - IMAQdxSetAttribute is variadic; Python bridges crash on x64
          - C# P/Invoke correctly handles the x64 variadic ABI
          - NI requires exclusive access so exe must open its own session
        """
        if not os.path.exists(_EXE):
            if not self._exe_warned:
                log.info("Attribute control needs ImaqdxAttr.exe — build it once with build_csharp.bat")
                self._exe_warned = True
            return False

        cam_name = self._cam_name.decode()

        # 1. Release NI session
        self.stop()
        self._dll.IMAQdxCloseCamera(self._session)

        # 2. Exe opens its own session, sets attribute, closes
        success = False
        try:
            result = subprocess.run(
                [_EXE, cam_name, attr, "{:.6f}".format(value)],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                success = True
            else:
                log.debug(f"ImaqdxAttr.exe: {result.stderr.strip()}")
        except Exception as e:
            log.warning(f"ImaqdxAttr.exe error: {e}")

        # 3. Reopen NI session
        new_session = ctypes.c_uint32(0)
        status = self._dll.IMAQdxOpenCamera(
            self._cam_name, ctypes.c_int32(0), ctypes.byref(new_session))
        if status == _NO_ERROR:
            self._session = new_session
            self.start()
        else:
            log.warning(f"Session reopen failed: {status}")
            self._open = False

        return success

    def set_exposure(self, microseconds: float) -> None:
        self._cfg["exposure_us"] = microseconds
        label = _ATTR_EXPOSURE.split("::")[-1]
        if self._set_attr(_ATTR_EXPOSURE, microseconds):
            log.debug(f"{label} = {microseconds:.0f} us")

    def set_gain(self, db: float) -> None:
        self._cfg["gain"] = db
        label = _ATTR_GAIN.split("::")[-1]
        if self._set_attr(_ATTR_GAIN, db):
            log.debug(f"{label} = {db:.1f} dB")

    def exposure_range(self) -> tuple:
        return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        return (0.0, 23.9)
