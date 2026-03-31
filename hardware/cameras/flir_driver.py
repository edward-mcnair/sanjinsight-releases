"""
hardware/cameras/flir_driver.py

Camera driver for the FLIR Boson thermal camera via flirpy.

Targets the Microsanj Infrared Camera v1a — a FLIR Boson-based uncooled
microbolometer (320×256 or 640×512, ~30 Hz) mounted in an OEMCameras.com
nosepiece housing for passive lock-in IR thermography.

The Boson connects as two USB devices simultaneously:
  • USB CDC (serial) — camera control commands  (handled by flirpy)
  • USB UVC (webcam) — 16-bit radiometric video stream (handled by flirpy)

Installation (end-user)
-----------------------
  Nothing extra — flirpy is bundled inside the SanjINSIGHT installer.

Config keys  (under hardware.camera in config.yaml)
---------------------------------------------------
  driver:       "flir"
  serial_port:  ""        Leave blank → first Boson CDC port auto-detected
  gain_mode:    "high"    "high" | "low"  (Boson has two fixed gain modes,
                          not a continuous dB value)
  ffc_mode:     "auto"    "auto" | "manual"
  width:        0         Expected frame width  (0 = accept whatever camera sends)
  height:       0         Expected frame height (0 = accept whatever camera sends)

Thread safety
-------------
``grab()`` is called from a background acquisition thread.
``do_ffc()`` / ``set_gain()`` may be called from the GUI thread.
All Boson serial commands are serialised with ``_cmd_lock``.
"""

import time
import threading
import logging
import numpy as np
from typing import Optional

from .base import CameraDriver, CameraFrame, CameraInfo

log = logging.getLogger(__name__)


class FlirDriver(CameraDriver):
    """
    FLIR Boson thermal camera driver via flirpy.

    Lifecycle::

        cam = FlirDriver(cfg)
        cam.open()          # detect serial port, open UVC stream
        cam.start()         # begin frame acquisition
        frame = cam.grab()  # CameraFrame (16-bit radiometric) or None on timeout
        cam.stop()          # pause acquisition
        cam.close()         # release Boson serial + UVC

    Extra API (beyond base class):

        cam.do_ffc()        — execute Flat Field Correction on demand
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import flirpy  # noqa: F401
        except ImportError:
            issues.append(
                "flirpy not found — Microsanj IR Camera support is not bundled.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._boson      : object           = None   # flirpy.camera.boson.Boson
        self._serial_port: str              = cfg.get("serial_port", "")
        self._frame_idx  : int              = 0
        self._streaming  : bool             = False
        # Serialise Boson serial-command calls from multiple threads
        self._cmd_lock   : threading.Lock   = threading.Lock()
        self._last_ffc_time: float = None   # time.time() of last successful FFC

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        """
        Detect and open the FLIR Boson.

        Raises
        ------
        RuntimeError
            flirpy not available, no Boson found, or hardware fault.
        """
        try:
            from flirpy.camera.boson import Boson
        except ImportError as exc:
            raise RuntimeError(
                "flirpy not found — cannot open Microsanj IR Camera.\n"
                "This should be bundled with SanjINSIGHT. "
                "Try reinstalling the application."
            ) from exc

        port = self._serial_port or None   # None → flirpy auto-detects

        try:
            self._boson = Boson(port=port)
        except Exception as exc:
            raise RuntimeError(
                f"Could not open FLIR Boson: {exc}\n"
                "Check that the camera is connected via USB and that no other "
                "application (e.g. FLIR ResearchIR) has it open."
            ) from exc

        # ------------------------------------------------------------------
        # Read camera identity
        # ------------------------------------------------------------------
        try:
            model  = self._boson.get_camera_part_number()
        except Exception:
            model  = "FLIR Boson"

        try:
            serial = self._boson.get_camera_serial()
        except Exception:
            serial = ""

        # Boson is always 16-bit radiometric
        try:
            width, height = self._boson.get_camera_video_standard()
        except Exception:
            width, height = 0, 0

        # Override from config if auto-detect failed
        w_cfg = int(self._cfg.get("width",  0))
        h_cfg = int(self._cfg.get("height", 0))
        if w_cfg:
            width  = w_cfg
        if h_cfg:
            height = h_cfg

        # ------------------------------------------------------------------
        # Apply initial settings
        # ------------------------------------------------------------------
        self._apply_gain_mode(self._cfg.get("gain_mode", "high"))
        self._apply_ffc_mode(self._cfg.get("ffc_mode", "auto"))

        # ------------------------------------------------------------------
        # Populate CameraInfo
        # ------------------------------------------------------------------
        self._info = CameraInfo(
            driver    = "flir",
            model     = model,
            serial    = serial,
            width     = width  or 320,
            height    = height or 256,
            bit_depth = 16,
            max_fps   = 30.0,
        )
        self._frame_idx = 0
        self._open      = True
        log.info(
            "FlirDriver: opened  %s  serial=%s  %d×%d  16-bit  ~30 fps",
            model, serial, self._info.width, self._info.height,
        )

    def start(self) -> None:
        """Begin frame acquisition (Boson streams continuously; just mark ready)."""
        if self._boson is None:
            return
        self._streaming = True
        log.debug("FlirDriver: streaming started")

    def stop(self) -> None:
        """Pause acquisition (does not close the serial or UVC connection)."""
        self._streaming = False
        log.debug("FlirDriver: streaming stopped")

    def close(self) -> None:
        """Close the Boson serial and UVC connections."""
        if not self._open:
            return
        self._streaming = False
        if self._boson is not None:
            try:
                self._boson.close()
            except Exception as exc:
                log.debug("FlirDriver: close() — %s", exc)
            self._boson = None
        self._open = False
        log.info("FlirDriver: closed")

    # ------------------------------------------------------------------ #
    #  Acquisition                                                         #
    # ------------------------------------------------------------------ #

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        """
        Retrieve the next frame from the Boson UVC stream.

        Returns ``None`` on timeout or hardware error (never raises).
        Safe to call from a background thread.
        """
        if self._boson is None or not self._streaming:
            return None

        deadline = time.time() + timeout_ms / 1000.0
        arr = None

        while time.time() < deadline:
            try:
                arr = self._boson.grab()
                if arr is not None:
                    break
            except Exception as exc:
                log.debug("FlirDriver: grab error: %s", exc)
                return None
            time.sleep(0.005)

        if arr is None:
            log.debug("FlirDriver: grab timeout (%d ms)", timeout_ms)
            return None

        # Boson always delivers uint16 radiometric data
        if arr.dtype != np.uint16:
            arr = arr.astype(np.uint16)

        # Collapse spurious channel dim (H, W, 1) → (H, W)
        if arr.ndim == 3 and arr.shape[2] == 1:
            arr = arr[:, :, 0]

        self._frame_idx += 1
        return CameraFrame(
            data        = arr,
            frame_index = self._frame_idx,
            exposure_us = 0.0,   # microbolometers don't have a settable exposure
            gain_db     = 0.0,
            timestamp   = time.time(),
            channels    = 1,
            bit_depth   = 16,
        )

    # ------------------------------------------------------------------ #
    #  Attribute control                                                   #
    # ------------------------------------------------------------------ #

    def set_exposure(self, microseconds: float) -> None:
        """No-op: FLIR Boson microbolometers do not have a settable exposure time."""
        log.debug(
            "FlirDriver: set_exposure ignored — Boson microbolometer "
            "does not support exposure control"
        )

    def get_exposure(self) -> float:
        """Returns 0 — Boson does not expose an integration time register."""
        return 0.0

    def set_gain(self, db: float) -> None:
        """
        Switch Boson gain mode.

        The Boson has two fixed gain modes (High / Low), not a continuous
        dB scale.  Values ≥ 1 dB → High gain; values < 1 dB → Low gain.
        """
        mode = "high" if db >= 1.0 else "low"
        self._cfg["gain"] = db
        self._apply_gain_mode(mode)

    def get_gain(self) -> float:
        """Returns 1.0 for High gain, 0.0 for Low gain."""
        return 1.0 if self._cfg.get("gain_mode", "high") == "high" else 0.0

    def set_trigger(self, mode: str) -> None:
        """No-op: Boson trigger is handled via the stimulus sync signal, not SDK."""
        log.debug("FlirDriver: set_trigger('%s') — Boson trigger is hardware-only", mode)

    def set_fps(self, fps: float) -> None:
        """No-op: Boson frame rate is fixed by the hardware revision."""
        log.debug("FlirDriver: set_fps ignored — Boson frame rate is not software-adjustable")

    def exposure_range(self) -> tuple:
        """Boson has no settable exposure; returns (0, 0)."""
        return (0.0, 0.0)

    def gain_range(self) -> tuple:
        """Boson gain is binary (Low=0 / High=1)."""
        return (0.0, 1.0)

    # ------------------------------------------------------------------ #
    #  Thermal-camera-specific extras                                      #
    # ------------------------------------------------------------------ #

    def supports_ffc(self) -> bool:
        return True

    def do_ffc(self) -> bool:
        """
        Execute an on-demand Flat Field Correction (Non-Uniformity Correction).

        FFC closes the internal shutter briefly to calibrate pixel offsets.
        Perform before each calibration sequence or after large ambient
        temperature changes.
        """
        if self._boson is None or not self._open:
            return False
        with self._cmd_lock:
            try:
                self._boson.do_ffc()
                self._last_ffc_time = time.time()
                log.debug("FlirDriver: FFC executed")
                return True
            except Exception as exc:
                log.warning("FlirDriver: do_ffc failed: %s", exc)
                return False

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _apply_gain_mode(self, mode: str) -> None:
        """Set High or Low gain mode on the Boson."""
        if self._boson is None:
            return
        with self._cmd_lock:
            try:
                from flirpy.camera.boson import Boson
                if mode.lower() == "high":
                    self._boson.set_gain_mode(Boson.GAIN_MODE_HIGH)
                else:
                    self._boson.set_gain_mode(Boson.GAIN_MODE_LOW)
                self._cfg["gain_mode"] = mode.lower()
                log.debug("FlirDriver: gain mode → %s", mode)
            except Exception as exc:
                log.debug("FlirDriver: set_gain_mode failed: %s", exc)

    def _apply_ffc_mode(self, mode: str) -> None:
        """Configure automatic or manual FFC scheduling."""
        if self._boson is None:
            return
        with self._cmd_lock:
            try:
                from flirpy.camera.boson import Boson
                ffc_val = (Boson.FFC_MODE_AUTO
                           if mode.lower() == "auto"
                           else Boson.FFC_MODE_MANUAL)
                self._boson.set_ffc_mode(ffc_val)
                log.debug("FlirDriver: FFC mode → %s", mode)
            except Exception as exc:
                log.debug("FlirDriver: set_ffc_mode failed: %s", exc)
