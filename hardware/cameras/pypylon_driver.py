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

    @classmethod
    def preflight(cls) -> tuple:
        """
        Validate that pypylon is importable AND that the Pylon SDK it links
        against is present and compatible.

        A bare ``import pypylon.pylon`` succeeds even when the installed Pylon
        SDK version doesn't match the pypylon wheel, because the Python import
        only loads the pure-Python layer.  The mismatch only surfaces when the
        first GenICam call (TlFactory.GetInstance) tries to load the SDK DLLs.
        On Windows that causes a hard process crash — no Python exception, no
        log output, nothing.

        This preflight makes that call deliberately, while we are still on the
        DM connect thread where exceptions (not crashes) are catchable, so any
        SDK problem surfaces as a user-visible error instead of a silent kill.
        """
        issues = []

        # ── Step 1: can we import pypylon at all? ────────────────────────────
        try:
            from pypylon import pylon as _pylon  # noqa: F401
        except ImportError:
            issues.append(
                "pypylon package not found.\n"
                "Reinstall SanjINSIGHT — pypylon is bundled with the installer.\n"
                "If the problem persists, contact Microsanj support."
            )
            return (False, issues)
        except Exception as e:
            issues.append(
                f"pypylon failed to import: {e}\n"
                "This usually means the Basler Pylon SDK DLLs are missing or "
                "the installation is corrupt.  Reinstall the Basler Pylon SDK "
                "(https://www.baslerweb.com) and then reinstall SanjINSIGHT."
            )
            return (False, issues)

        # ── Step 2: probe TlFactory to catch SDK version mismatches ─────────
        # This is the call that hard-crashes the process on a version mismatch.
        # Running it here (still inside a try/except) means a mismatch surfaces
        # as a Python RuntimeError rather than an unrecoverable native crash.
        try:
            from pypylon import pylon as _pylon
            _factory = _pylon.TlFactory.GetInstance()
        except Exception as e:
            sdk_hint = (
                "Version mismatch: the pypylon wheel was built against a "
                "different Pylon SDK than what is installed.\n\n"
                "Fix: uninstall the current Pylon SDK, install Pylon SDK 8.x "
                "from https://www.baslerweb.com, then reinstall SanjINSIGHT "
                "so pypylon is rebuilt against the correct SDK."
            )
            issues.append(
                f"Pylon SDK initialisation failed: {e}\n\n{sdk_hint}"
            )
            return (False, issues)

        # ── Step 3: confirm at least one camera is visible to the SDK ────────
        # USB3 cameras can take several seconds to enumerate after being
        # plugged in or after system boot.  Retry a few times with short
        # delays so a slow USB enumeration doesn't cause a premature
        # preflight failure.
        import time as _time
        _ENUM_RETRIES  = 4     # total attempts (first + 3 retries)
        _ENUM_DELAY_S  = 1.5   # seconds between attempts
        _devices = None
        for _attempt in range(_ENUM_RETRIES):
            try:
                _devices = _factory.EnumerateDevices()
                if _devices:
                    break   # found at least one camera
                if _attempt < _ENUM_RETRIES - 1:
                    log.debug(
                        "pypylon preflight: no cameras on attempt %d/%d, "
                        "retrying in %.1fs…",
                        _attempt + 1, _ENUM_RETRIES, _ENUM_DELAY_S)
                    _time.sleep(_ENUM_DELAY_S)
            except Exception as e:
                # EnumerateDevices failure is non-fatal at preflight — the
                # open() call will give a clearer error with device context.
                log.warning("pypylon preflight EnumerateDevices warning: %s", e)
                break   # don't retry on SDK exceptions

        if not _devices:
            issues.append(
                "No Basler cameras found by the Pylon SDK.\n"
                "Check that the camera is powered and the USB/GigE cable "
                "is connected, then click Connect again.\n"
                "(The Basler Pylon Viewer can confirm the camera is "
                "visible at the OS level.)"
            )
            return (False, issues)

        return (True, issues)

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

        # Detect color vs mono sensor from pixel format name
        pf_name = self._cam.PixelFormat.GetValue() if hasattr(self._cam, 'PixelFormat') else ""
        self._is_color = ("Bayer" in str(pf_name))
        self._color_mode = self._cfg.get("color_mode", self._is_color)

        # Set up Bayer converter if color sensor is detected
        self._converter = None
        if self._color_mode and self._is_color:
            try:
                self._converter = pylon.ImageFormatConverter()
                self._converter.OutputPixelFormat = pylon.PixelType_RGB8packed
                self._converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
                log.info("pypylon: Color sensor detected (%s), RGB conversion enabled.",
                         pf_name)
            except Exception as exc:
                log.warning("pypylon: Failed to set up Bayer converter: %s", exc)
                self._converter = None
                self._color_mode = False

        self._info = CameraInfo(
            driver       = "pypylon",
            model        = self._cam.GetDeviceInfo().GetModelName(),
            serial       = self._cam.GetDeviceInfo().GetSerialNumber(),
            width        = self._cam.Width.GetValue(),
            height       = self._cam.Height.GetValue(),
            bit_depth    = 12,
            max_fps      = self._cam.ResultingFrameRate.GetValue()
                           if hasattr(self._cam, 'ResultingFrameRate') else 0.0,
            camera_type  = self._cfg.get("camera_type", "tr"),
            pixel_format = "rgb" if self._color_mode else "mono",
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
                idx = result.ImageNumber

                # Color: demosaic Bayer → RGB via pypylon converter
                if self._converter is not None:
                    try:
                        converted = self._converter.Convert(result)
                        # RGB8packed → (H, W, 3) uint8 → scale to 12-bit uint16
                        rgb = converted.GetArray().copy()
                        data = (rgb.astype(np.uint16) * 4095 // 255).astype(np.uint16)
                        n_ch = 3
                    except Exception:
                        data = result.Array.copy().astype(np.uint16)
                        n_ch = 1
                else:
                    data = result.Array.copy().astype(np.uint16)
                    n_ch = 1

                result.Release()
                return CameraFrame(
                    data        = data,
                    frame_index = idx,
                    exposure_us = self._cfg.get("exposure_us", 0.0),
                    gain_db     = self._cfg.get("gain", 0.0),
                    timestamp   = time.time(),
                    channels    = n_ch,
                    bit_depth   = 12,
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
        try:
            node = self._cam.GetNodeMap().GetNode("ExposureTime")
            if node is None:
                return
            from pypylon import genicam
            if genicam.IsWritable(node):
                genicam.IFloat(node).SetValue(float(microseconds))
                log.debug("ExposureTime = %.0f us", microseconds)
        except Exception as e:
            log.debug("set_exposure failed: %s", e)

    def set_gain(self, db: float) -> None:
        self._cfg["gain"] = db
        try:
            node = self._cam.GetNodeMap().GetNode("Gain")
            if node is None:
                return
            from pypylon import genicam
            if genicam.IsWritable(node):
                genicam.IFloat(node).SetValue(float(db))
                log.debug("Gain = %.1f dB", db)
        except Exception as e:
            log.debug("set_gain failed: %s", e)

    def exposure_range(self) -> tuple:
        try:
            node = self._cam.GetNodeMap().GetNode("ExposureTime")
            if node is None:
                return (50.0, 200_000.0)
            from pypylon import genicam
            n = genicam.IFloat(node)
            return (n.GetMin(), n.GetMax())
        except Exception:
            return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        try:
            node = self._cam.GetNodeMap().GetNode("Gain")
            if node is None:
                return (0.0, 24.0)
            from pypylon import genicam
            n = genicam.IFloat(node)
            return (n.GetMin(), n.GetMax())
        except Exception:
            return (0.0, 24.0)
