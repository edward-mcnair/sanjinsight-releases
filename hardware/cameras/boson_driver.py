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
     No native DLL is required — FSLP_PY_SERIAL selects the PySerial path.
  2. Opens the video channel with cv2.VideoCapture.
  3. Maps the Boson's 14-bit radiometric output to a uint16 CameraFrame
     expected by the rest of SanjINSIGHT.

Config keys (under hardware.camera):
    driver:        "boson"
    serial_port:   "/dev/cu.usbmodemXXX"   # macOS (or "COM3" on Windows)
                   Leave blank for video-only mode (no SDK control).
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
    (320, 256): "FLIR Boson 320",
    (640, 512): "FLIR Boson 640",
}

# Default baud rate for the Boson UART control channel
_DEFAULT_BAUD = 921600


class BosonDriver(CameraDriver):
    """
    FLIR Boson thermal camera driver.

    Control is exercised via the bundled FLIR Boson Python SDK over serial
    (pure-Python FSLP — no DLL required, works on macOS, Windows, Linux).
    Video frames are captured via OpenCV's UVC backend.

    Thread safety
    -------------
    grab() must be safe to call from a background thread while close() may
    be called from the GUI thread.  _cap_lock serialises VideoCapture access
    only — the lock is NOT held during the blocking cap.read() call, so
    close() is never blocked by an in-progress grab.
    """

    # ── Preflight ─────────────────────────────────────────────────────────────

    @classmethod
    def preflight(cls) -> tuple:
        import sys as _sys
        _frozen = getattr(_sys, 'frozen', False)

        issues = []
        try:
            import cv2  # noqa: F401
        except ImportError:
            if _frozen:
                issues.append(
                    "opencv-python (cv2) could not be loaded from the application bundle.\n"
                    "  This is an internal packaging error.\n"
                    "  Fix: reinstall SanjINSIGHT from the latest installer."
                )
            else:
                issues.append(
                    "opencv-python is not installed.\n"
                    "  Fix: pip install opencv-python"
                )
        try:
            import serial  # noqa: F401
        except ImportError:
            if _frozen:
                issues.append(
                    "pyserial could not be loaded from the application bundle.\n"
                    "  Fix: reinstall SanjINSIGHT from the latest installer."
                )
            else:
                issues.append(
                    "pyserial is not installed.\n"
                    "  Fix: pip install pyserial"
                )
        # Use a relative-style import-by-path so the check works both in the
        # source tree and inside a frozen PyInstaller bundle.
        try:
            import importlib
            importlib.import_module(
                "hardware.cameras.boson.ClientFiles_Python.Client_API"
            )
        except ImportError as exc:
            issues.append(
                f"FLIR Boson SDK not found in the installation: {exc}\n"
                "  The Boson SDK should be bundled — reinstall SanjINSIGHT."
            )
        return (len(issues) == 0, issues)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._serial_port = cfg.get("serial_port", "")
        self._baud        = int(cfg.get("baud", _DEFAULT_BAUD))
        self._video_index = int(cfg.get("video_index", 0))
        self._W           = int(cfg.get("width",  320))
        self._H           = int(cfg.get("height", 256))
        self._fps         = float(cfg.get("fps",  60.0))

        self._client      = None   # pyClient (SDK control)
        self._cap         = None   # cv2.VideoCapture (video)
        self._cap_lock    = threading.Lock()   # guards _cap reference only
        self._state_lock  = threading.Lock()   # guards _open flag
        self._frame_idx   = 0                  # monotonic; only written in grab()

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
        with self._state_lock:
            if self._open:
                return
            self._open_locked()

    def _open_locked(self) -> None:
        """Must be called with _state_lock held."""
        import cv2

        fslp = None  # track separately so we can clean up on partial failure

        # ── 1. Control channel (optional) ─────────────────────────────────────
        if self._serial_port:
            try:
                from hardware.cameras.boson.CommunicationFiles.CommonFslp import (
                    CommonFslp, FSLP_TYPE_E,
                )
                from hardware.cameras.boson.ClientFiles_Python.Client_API import pyClient

                fslp = CommonFslp.getFslp(
                    self._serial_port, self._baud,
                    FSLP_TYPE_E.FSLP_PY_SERIAL,
                )
                fslp.port.open()
                self._client = pyClient(fslp=fslp, useDll=False, ex=False)

                # Read serial number via bosonGetCameraSN() (uint32)
                from hardware.cameras.boson.ClientFiles_Python.ReturnCodes import FLR_RESULT
                result, sn = self._client.bosonGetCameraSN()
                if result is FLR_RESULT.R_SUCCESS and sn is not None:
                    self._info.serial = str(sn)
                    log.info("Boson serial number: %s", self._info.serial)
                else:
                    log.warning("Boson: could not read serial number (%s)", result)

            except Exception as exc:
                log.warning(
                    "Boson control channel failed on %s — "
                    "continuing in video-only mode (no SDK commands): %s",
                    self._serial_port, exc,
                )
                # Clean up serial port if it was opened before the failure
                if fslp is not None:
                    try:
                        fslp.port.close()
                    except Exception:
                        pass
                self._client = None
        else:
            log.info(
                "Boson: no serial_port configured — video-only mode. "
                "Set serial_port in config.yaml for full SDK control."
            )

        # ── 2. Video channel ──────────────────────────────────────────────────
        # On Windows, cv2.VideoCapture() defaults to the MSMF (Media Foundation)
        # backend, which rejects non-standard resolutions like the Boson's native
        # 320×256 and 640×512 sizes — resulting in failure to open or black frames.
        # DirectShow (CAP_DSHOW) handles these sizes correctly and is the
        # recommended backend for UVC thermal cameras on Windows.
        import sys as _sys
        video_idx = self._auto_detect_video_index()
        if _sys.platform == "win32":
            cap = cv2.VideoCapture(video_idx, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(video_idx)

        if not cap.isOpened():
            # Serial was opened successfully — close it before raising
            if self._client:
                try:
                    self._client.Close()
                except Exception:
                    pass
                self._client = None
            cam_list = self._enumerate_video_devices()
            cam_list_str = ("\n  Available video devices:\n" + cam_list) if cam_list else ""
            if _sys.platform == "win32":
                hint = (
                    "\n  3. Set 'Video Device Index' in Device Manager to the correct"
                    " DirectShow index.\n"
                    "     Run: python -c \"import cv2; [print(i, cv2.VideoCapture(i,"
                    " cv2.CAP_DSHOW).isOpened()) for i in range(5)]\""
                )
            else:
                hint = (
                    "\n  3. Grant Camera access to Terminal (or SanjINSIGHT):\n"
                    "     System Settings → Privacy & Security → Camera → enable it,\n"
                    "     then quit and restart the app."
                    "\n  4. Set the correct 'Video Device Index' in Device Manager."
                )
            raise RuntimeError(
                f"FLIR Boson: could not open video device index {video_idx}.\n"
                "Check:\n"
                "  1. Boson is physically connected via USB (run Scan to refresh).\n"
                "  2. No other app (QuickTime, Photo Booth) is using the camera."
                + hint + cam_list_str
            )

        # Request 16-bit greyscale (Y16) pixel format for radiometric data.
        # cap.set() returns False silently on unsupported formats — we log a
        # warning so the user knows the data may be 8-bit AGC output instead.
        y16_fourcc = cv2.VideoWriter_fourcc(*"Y16 ")
        cap.set(cv2.CAP_PROP_FOURCC, y16_fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._H)
        cap.set(cv2.CAP_PROP_FPS,          self._fps)
        cap.set(cv2.CAP_PROP_CONVERT_RGB,  0)   # raw, no colour conversion

        # Validate that Y16 was accepted.
        # macOS AVFoundation does not expose Y16 over UVC — 8-bit AGC fallback
        # is expected and normal on macOS; log at INFO rather than WARNING there.
        actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        if actual_fourcc != y16_fourcc:
            four = "".join(chr((actual_fourcc >> (8 * i)) & 0xFF) for i in range(4))
            _y16_log = log.info if _sys.platform == "darwin" else log.warning
            _y16_log(
                "Boson: Y16 pixel format not available on this platform "
                "(got FOURCC '%s'). Running in 8-bit AGC mode — frames scaled "
                "to uint16. Radiometric accuracy is reduced on macOS; "
                "full 14-bit output is available on Windows.", four.strip()
            )
            self._y16_mode = False
        else:
            self._y16_mode = True

        # Verify the video device by reading a test frame and logging its
        # resolution.  This catches the common macOS issue where system_profiler
        # indices don't match OpenCV AVFoundation indices, so a webcam at index 1
        # gets opened instead of the Boson's 320×256 (or 640×512) UVC stream.
        ret, test_frame = cap.read()
        if ret and test_frame is not None:
            h, w = test_frame.shape[:2]
            log.info("Boson: test frame from index %d: %dx%d dtype=%s",
                     video_idx, w, h, test_frame.dtype)
            # If the frame is much larger than the expected Boson resolution
            # (e.g. 1280x720 from a webcam), try other indices to find the
            # actual Boson UVC stream.
            if w > self._W * 2 or h > self._H * 2:
                log.warning(
                    "Boson: frame %dx%d at index %d does not match expected "
                    "%dx%d — probing other indices for the Boson UVC stream.",
                    w, h, video_idx, self._W, self._H)
                found = self._probe_video_indices(cap, video_idx)
                if found is not None:
                    cap, video_idx = found

        with self._cap_lock:
            self._cap = cap
        self._open = True

        log.info(
            "Boson opened: model=%s serial=%s video_index=%d y16=%s",
            self._info.model, self._info.serial or "unknown",
            video_idx, self._y16_mode,
        )

    def _probe_video_indices(self, wrong_cap, wrong_idx):
        """Try other OpenCV indices to find the actual Boson UVC stream.

        Returns (cap, index) tuple on success, or None if no match found.
        The wrong_cap is released if a better match is found.
        """
        import cv2
        import sys as _sys
        for idx in range(6):
            if idx == wrong_idx:
                continue
            try:
                if _sys.platform == "win32":
                    probe = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                else:
                    probe = cv2.VideoCapture(idx)
                if not probe.isOpened():
                    continue
                ret, f = probe.read()
                if not ret or f is None:
                    probe.release()
                    continue
                h, w = f.shape[:2]
                log.info("Boson: probe index %d → %dx%d", idx, w, h)
                # Accept if resolution matches expected Boson output (±10%)
                if (abs(w - self._W) <= self._W * 0.1 and
                        abs(h - self._H) <= self._H * 0.1):
                    log.info(
                        "Boson: found matching %dx%d stream at index %d. "
                        "Update 'Video Device Index' to %d in Device Manager.",
                        w, h, idx, idx)
                    # Apply Y16 / resolution settings to the new capture
                    y16_fourcc = cv2.VideoWriter_fourcc(*"Y16 ")
                    probe.set(cv2.CAP_PROP_FOURCC, y16_fourcc)
                    probe.set(cv2.CAP_PROP_FRAME_WIDTH,  self._W)
                    probe.set(cv2.CAP_PROP_FRAME_HEIGHT, self._H)
                    probe.set(cv2.CAP_PROP_FPS,          self._fps)
                    probe.set(cv2.CAP_PROP_CONVERT_RGB,  0)
                    wrong_cap.release()
                    return probe, idx
                probe.release()
            except Exception:
                continue
        log.warning(
            "Boson: could not find a matching video stream at any index. "
            "Using index %d despite resolution mismatch.", wrong_idx)
        return None

    # ── Video device helpers ───────────────────────────────────────────────────

    def _auto_detect_video_index(self) -> int:
        """
        On macOS, use system_profiler to find the AVFoundation index of the
        first FLIR camera (VID 09CB).  Falls back to the configured video_index
        on failure or on other platforms.

        This avoids the common mistake of index 0 being the built-in FaceTime
        camera while the Boson is at index 1 or 2.
        """
        import sys as _sys
        if _sys.platform != "darwin":
            return self._video_index
        try:
            import subprocess, json
            r = subprocess.run(
                ["system_profiler", "SPCameraDataType", "-json"],
                capture_output=True, text=True, timeout=5,
            )
            cameras = json.loads(r.stdout).get("SPCameraDataType", [])
            for i, cam in enumerate(cameras):
                name = cam.get("_name", "").lower()
                uid  = cam.get("spcamera_unique-id", "").lower()
                if "flir" in name or "09cb" in uid:
                    if i != self._video_index:
                        log.info(
                            "Boson: auto-detected UVC at index %d ('%s'). "
                            "Update 'Video Device Index' in Device Manager to %d "
                            "to avoid this scan on every connect.",
                            i, cam.get("_name", ""), i,
                        )
                    return i
        except Exception as exc:
            log.debug("Boson: video index auto-detect failed: %s", exc)
        return self._video_index

    def _enumerate_video_devices(self) -> str:
        """Return a human-readable list of available video devices (best-effort)."""
        import sys as _sys
        try:
            if _sys.platform == "darwin":
                import subprocess, json
                r = subprocess.run(
                    ["system_profiler", "SPCameraDataType", "-json"],
                    capture_output=True, text=True, timeout=5,
                )
                cameras = json.loads(r.stdout).get("SPCameraDataType", [])
                return "\n".join(
                    f"    [{i}] {c.get('_name', 'Unknown')}"
                    for i, c in enumerate(cameras)
                )
            elif _sys.platform == "win32":
                # Quick DirectShow probe — only test indices that open instantly
                import cv2
                lines = []
                for i in range(6):
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    if cap.isOpened():
                        lines.append(f"    [{i}] (device found)")
                        cap.release()
                return "\n".join(lines)
        except Exception as exc:
            log.debug("Boson: enumerate_video_devices failed: %s", exc)
        return ""

    def start(self) -> None:
        # VideoCapture begins delivering frames as soon as it is opened.
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        # Swap out _cap reference under cap_lock so any in-progress grab()
        # that already read _cap will finish naturally, while new grab() calls
        # see None and return immediately.
        with self._cap_lock:
            cap = self._cap
            self._cap = None

        if cap is not None:
            cap.release()

        if self._client is not None:
            try:
                self._client.Close()
            except Exception:
                pass
            self._client = None

        with self._state_lock:
            self._open = False

        log.info("Boson closed")

    # ── Acquisition ───────────────────────────────────────────────────────────

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        import cv2

        # Read _cap reference without holding the lock during the blocking call.
        with self._cap_lock:
            cap = self._cap
        if cap is None:
            return None

        deadline = time.monotonic() + timeout_ms / 1000.0
        frame = None
        while time.monotonic() < deadline:
            ret, f = cap.read()
            if ret and f is not None:
                frame = f
                break

        if frame is None:
            log.debug("Boson grab timeout (%d ms)", timeout_ms)
            return None

        # Normalise to uint16.
        # Y16 mode: OpenCV delivers single-channel uint16 — use directly.
        # AGC/fallback: may be BGR uint8 or single-channel uint8 — scale up.
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.dtype != np.uint16:
            if not getattr(self, '_y16_warned', False):
                log.warning(
                    "Boson: received uint8 frame — scaling ×256. "
                    "Radiometric data unavailable (AGC output mode)."
                )
                self._y16_warned = True
            frame = frame.astype(np.uint16) * 256

        self._frame_idx += 1   # only written here (single grab-thread pattern)
        return CameraFrame(
            data        = frame,
            frame_index = self._frame_idx,
            exposure_us = 0.0,   # Boson auto-exposes internally
            gain_db     = 0.0,
            timestamp   = time.time(),
        )

    # ── Attribute control ─────────────────────────────────────────────────────

    def set_exposure(self, microseconds: float) -> None:
        """Boson manages integration time internally — no-op."""
        pass

    def set_gain(self, db: float) -> None:
        """Boson has no user-adjustable analog gain — no-op."""
        pass

    def exposure_range(self) -> tuple:
        return (0.0, 0.0)

    def gain_range(self) -> tuple:
        return (0.0, 0.0)

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
            from hardware.cameras.boson.ClientFiles_Python.ReturnCodes import FLR_RESULT
            result = self._client.bosonRunFFC()
            ok = (result is FLR_RESULT.R_SUCCESS)
            if ok:
                log.info("Boson: FFC triggered successfully")
            else:
                log.warning("Boson: FFC returned %s", result)
            return ok
        except Exception as exc:
            log.error("Boson: FFC failed: %s", exc)
            return False
