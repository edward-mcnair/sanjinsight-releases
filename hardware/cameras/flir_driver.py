"""
hardware/cameras/flir_driver.py

Camera driver for FLIR thermal cameras via the Spinnaker SDK (PySpin).

Targets the Microsanj Infrared Camera v1a — a FLIR-based uncooled
microbolometer thermal camera (4.9 mm fixed FL, OEMCameras.com PCB,
26 VDC supply) used for passive lock-in IR thermography.  Also
compatible with any other FLIR / Spinnaker-enumerable camera.

Installation
------------
  1. Download and install the FLIR Spinnaker SDK:
       https://www.flir.com/products/spinnaker-sdk/
  2. Install the Python bindings that match your Python version and OS:
       pip install spinnaker_python
     (The wheel is distributed by FLIR alongside the SDK installer.)

Config keys  (under hardware.camera in config.yaml)
---------------------------------------------------
  driver:         "flir"
  serial:         ""          Leave blank → first enumerated camera
  exposure_us:    5000        Integration time in microseconds
  gain:           0.0         Analog gain in dB
  trigger_mode:   "Off"       "Off" | "Software" | "Hardware"
  ffc_mode:       "auto"      Flat Field Correction: "auto" | "manual" | "external"
  ir_format:      "Mono14"    Pixel format passed to PixelFormat node.
                              Mono14 (14-bit) is standard for uncooled IR cores.
                              Other options: "Mono16", "Mono8"
  width:          0           Sensor width in pixels (0 = camera maximum)
  height:         0           Sensor height in pixels (0 = camera maximum)

Thread safety
-------------
``grab()`` is called from a background acquisition thread.
``set_exposure()`` / ``set_gain()`` may be called from the GUI thread
while streaming.  All node-map writes are serialised with ``_node_lock``.
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
    FLIR thermal camera driver via the official Spinnaker SDK (PySpin).

    Lifecycle::

        cam = FlirDriver(cfg)
        cam.open()          # enumerate, select, init, configure
        cam.start()         # BeginAcquisition (continuous)
        frame = cam.grab()  # CameraFrame or None on timeout
        cam.stop()          # EndAcquisition
        cam.close()         # DeInit + release system

    Extra API (beyond base class):

        cam.trigger_software()  — fire a SW trigger pulse
        cam.do_ffc()            — execute Flat Field Correction on demand
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._cam       : object = None   # PySpin.Camera
        self._system    : object = None   # PySpin.System
        self._cam_list  : object = None   # PySpin.CameraList
        self._serial    : str    = cfg.get("serial", "")
        self._frame_idx : int    = 0
        # Serialise node-map writes called from GUI vs. grab thread
        self._node_lock : threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        """
        Enumerate FLIR / Spinnaker cameras, open by serial (or first found),
        configure pixel format, resolution, exposure, gain, trigger and FFC.

        Raises
        ------
        RuntimeError
            Camera not found, SDK not installed, or hardware fault.
        """
        try:
            import PySpin  # noqa: F401 — confirm SDK present
        except ImportError:
            raise RuntimeError(
                "PySpin (Spinnaker SDK) not installed.\n"
                "Run:  pip install spinnaker_python\n"
                "Also install the FLIR Spinnaker SDK from:\n"
                "  https://www.flir.com/products/spinnaker-sdk/"
            )

        import PySpin

        # ------------------------------------------------------------------
        # Obtain system singleton and camera list
        # ------------------------------------------------------------------
        self._system   = PySpin.System.GetInstance()
        self._cam_list = self._system.GetCameras()

        n_cams = self._cam_list.GetSize()
        if n_cams == 0:
            self._cam_list.Clear()
            self._system.ReleaseInstance()
            self._system   = None
            self._cam_list = None
            raise RuntimeError(
                "No FLIR / Spinnaker cameras found. "
                "Check USB connection and Spinnaker SDK installation."
            )

        log.debug("FlirDriver: %d Spinnaker camera(s) found", n_cams)

        # ------------------------------------------------------------------
        # Select camera — by serial if supplied, otherwise first
        # ------------------------------------------------------------------
        cam = None
        if self._serial:
            for c in self._cam_list:
                try:
                    if c.GetUniqueID() == self._serial:
                        cam = c
                        break
                except Exception:
                    continue
            if cam is None:
                found = [c.GetUniqueID() for c in self._cam_list]
                self._cam_list.Clear()
                self._system.ReleaseInstance()
                raise RuntimeError(
                    f"FLIR camera serial '{self._serial}' not found. "
                    f"Available: {found}"
                )
        else:
            cam = self._cam_list.GetByIndex(0)

        self._cam = cam
        self._cam.Init()
        nm = self._cam.GetNodeMap()

        # ------------------------------------------------------------------
        # Pixel format
        # ------------------------------------------------------------------
        pf_req = self._cfg.get("ir_format", "Mono14")
        _set_enum(nm, "PixelFormat", pf_req, fallback="Mono14")

        # ------------------------------------------------------------------
        # Resolution  (0 = sensor maximum)
        # ------------------------------------------------------------------
        w_req = int(self._cfg.get("width",  0))
        h_req = int(self._cfg.get("height", 0))
        _set_int_clamped(nm, "OffsetX", 0)   # reset offsets first
        _set_int_clamped(nm, "OffsetY", 0)
        _set_int_max_if_zero(nm, "Width",  w_req)
        _set_int_max_if_zero(nm, "Height", h_req)

        actual_w = _get_int(nm, "Width")
        actual_h = _get_int(nm, "Height")

        # ------------------------------------------------------------------
        # Exposure
        # ------------------------------------------------------------------
        exp_us = float(self._cfg.get("exposure_us", 5000.0))
        _set_exposure(nm, exp_us)

        # ------------------------------------------------------------------
        # Gain
        # ------------------------------------------------------------------
        gain_db = float(self._cfg.get("gain", 0.0))
        _set_gain(nm, gain_db)

        # ------------------------------------------------------------------
        # Trigger
        # ------------------------------------------------------------------
        trig = self._cfg.get("trigger_mode", "Off")
        _set_enum(nm, "TriggerMode", "Off")          # disable before reconfigure
        if trig.lower() not in ("", "off"):
            src = "Software" if trig.lower() == "software" else "Line0"
            _set_enum(nm, "TriggerSource", src)
            _set_enum(nm, "TriggerMode", "On")

        # ------------------------------------------------------------------
        # Flat Field Correction (NUC / shutter correction)
        # Not all cameras expose this via GenICam — failure is non-fatal.
        # ------------------------------------------------------------------
        ffc_map = {"auto": "Auto", "manual": "Manual", "external": "External"}
        ffc_val = ffc_map.get(self._cfg.get("ffc_mode", "auto").lower(), "Auto")
        try:
            _set_enum(nm, "FFCMode", ffc_val)
        except Exception:
            log.debug("FlirDriver: FFCMode node not available on this model — skipped")

        # ------------------------------------------------------------------
        # Frame rate — if the camera supports runtime control, apply it
        # ------------------------------------------------------------------
        try:
            _set_bool(nm, "AcquisitionFrameRateEnable", False)  # free-running
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Populate CameraInfo
        # ------------------------------------------------------------------
        try:
            model = self._cam.TLDevice.DeviceModelName.GetValue()
        except Exception:
            model = self._cfg.get("model", "FLIR IR Camera")

        try:
            serial = self._cam.TLDevice.DeviceSerialNumber.GetValue()
        except Exception:
            serial = self._serial or ""

        try:
            max_fps = float(self._cam.AcquisitionFrameRate.GetValue())
        except Exception:
            max_fps = 0.0

        # Derive bit depth from the active pixel format
        pf_active = ""
        try:
            pf_active = self._cam.PixelFormat.GetCurrentEntry().GetSymbolic()
        except Exception:
            pass
        bd = 14 if "14" in pf_active else (16 if "16" in pf_active else 8)

        self._info = CameraInfo(
            driver    = "flir",
            model     = model,
            serial    = serial,
            width     = actual_w,
            height    = actual_h,
            bit_depth = bd,
            max_fps   = max_fps,
        )
        self._frame_idx = 0
        self._open      = True
        log.info(
            "FlirDriver: opened  %s  serial=%s  %d×%d  %d-bit  %.1f fps",
            model, serial, actual_w, actual_h, bd, max_fps,
        )

    def start(self) -> None:
        """Begin continuous free-running acquisition."""
        if self._cam is None:
            return
        import PySpin
        self._cam.AcquisitionMode.SetValue(PySpin.AcquisitionMode_Continuous)
        self._cam.BeginAcquisition()
        log.debug("FlirDriver: BeginAcquisition")

    def stop(self) -> None:
        """Stop streaming; camera stays open and configured."""
        if self._cam is None:
            return
        try:
            self._cam.EndAcquisition()
            log.debug("FlirDriver: EndAcquisition")
        except Exception as exc:
            log.debug("FlirDriver: stop() — %s", exc)

    def close(self) -> None:
        """Stop streaming, deinit camera, release Spinnaker system."""
        if not self._open:
            return
        self.stop()
        try:
            self._cam.DeInit()
        except Exception as exc:
            log.debug("FlirDriver: DeInit — %s", exc)
        if self._cam_list is not None:
            try:
                self._cam_list.Clear()
            except Exception:
                pass
        if self._system is not None:
            try:
                self._system.ReleaseInstance()
            except Exception:
                pass
        self._cam      = None
        self._cam_list = None
        self._system   = None
        self._open     = False
        log.info("FlirDriver: closed")

    # ------------------------------------------------------------------ #
    #  Acquisition                                                         #
    # ------------------------------------------------------------------ #

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        """
        Retrieve the next complete frame from the camera buffer.

        Returns ``None`` on timeout or hardware error (never raises).
        Safe to call from a background thread concurrently with
        ``set_exposure()`` / ``set_gain()`` on the GUI thread.
        """
        if self._cam is None:
            return None

        import PySpin

        try:
            image_result = self._cam.GetNextImage(timeout_ms)
        except PySpin.SpinnakerException as exc:
            msg = str(exc).lower()
            if "timeout" in msg or "-1011" in msg:
                log.debug("FlirDriver: grab timeout (%d ms)", timeout_ms)
            else:
                log.warning("FlirDriver: grab error: %s", exc)
            return None

        if image_result.IsIncomplete():
            log.debug(
                "FlirDriver: incomplete frame (status %d) — discarded",
                image_result.GetImageStatus(),
            )
            image_result.Release()
            return None

        try:
            # GetNDArray() returns uint16 for Mono14 / Mono16 pixel formats.
            # For Mono8 it returns uint8; we scale up to keep the pipeline uniform.
            arr = image_result.GetNDArray()
            idx = image_result.GetFrameID()
            ts  = time.time()
        except Exception as exc:
            log.warning("FlirDriver: frame data error: %s", exc)
            image_result.Release()
            return None
        finally:
            image_result.Release()

        # Normalise to uint16  —  8-bit → left-align into the upper 8 bits
        if arr.dtype == np.uint8:
            data = arr.astype(np.uint16) << 8
        else:
            data = arr.astype(np.uint16)

        # Collapse spurious channel dimension  (H, W, 1) → (H, W)
        if data.ndim == 3 and data.shape[2] == 1:
            data = data[:, :, 0]

        return CameraFrame(
            data        = data,
            frame_index = int(idx),
            exposure_us = self._cfg.get("exposure_us", 0.0),
            gain_db     = self._cfg.get("gain", 0.0),
            timestamp   = ts,
        )

    # ------------------------------------------------------------------ #
    #  Attribute control                                                   #
    # ------------------------------------------------------------------ #

    def set_exposure(self, microseconds: float) -> None:
        """
        Set integration time in microseconds.

        Disables auto-exposure, then writes ExposureTime.
        Thread-safe: serialised with ``_node_lock``.
        """
        self._cfg["exposure_us"] = microseconds
        with self._node_lock:
            if self._cam and self._open:
                try:
                    _set_exposure(self._cam.GetNodeMap(), microseconds)
                    log.debug("FlirDriver: exposure → %.0f µs", microseconds)
                except Exception as exc:
                    log.warning("FlirDriver: set_exposure failed: %s", exc)

    def get_exposure(self) -> float:
        """Live readback from ExposureTime node."""
        if self._cam and self._open:
            try:
                return float(self._cam.ExposureTime.GetValue())
            except Exception:
                pass
        return self._cfg.get("exposure_us", 0.0)

    def set_gain(self, db: float) -> None:
        """
        Set analog gain in dB.

        Disables auto-gain, then writes Gain node.
        Thread-safe: serialised with ``_node_lock``.
        """
        self._cfg["gain"] = db
        with self._node_lock:
            if self._cam and self._open:
                try:
                    _set_gain(self._cam.GetNodeMap(), db)
                    log.debug("FlirDriver: gain → %.1f dB", db)
                except Exception as exc:
                    log.warning("FlirDriver: set_gain failed: %s", exc)

    def get_gain(self) -> float:
        """Live readback from Gain node."""
        if self._cam and self._open:
            try:
                return float(self._cam.Gain.GetValue())
            except Exception:
                pass
        return self._cfg.get("gain", 0.0)

    def set_trigger(self, mode: str) -> None:
        """
        Set trigger mode.

        Parameters
        ----------
        mode : str
            ``"Off"``      — free-running continuous acquisition
            ``"Software"`` — trigger each frame via ``trigger_software()``
            ``"Hardware"`` — trigger from external Line0 signal
        """
        if not (self._cam and self._open):
            return
        with self._node_lock:
            try:
                nm = self._cam.GetNodeMap()
                _set_enum(nm, "TriggerMode", "Off")
                if mode.lower() not in ("", "off"):
                    src = "Software" if mode.lower() == "software" else "Line0"
                    _set_enum(nm, "TriggerSource", src)
                    _set_enum(nm, "TriggerMode", "On")
                log.debug("FlirDriver: trigger mode → %s", mode)
            except Exception as exc:
                log.warning("FlirDriver: set_trigger failed: %s", exc)

    def set_fps(self, fps: float) -> None:
        """Adjust target frame rate (if camera supports runtime control)."""
        if not (self._cam and self._open):
            return
        try:
            nm = self._cam.GetNodeMap()
            _set_bool(nm, "AcquisitionFrameRateEnable", True)
            _set_float(nm, "AcquisitionFrameRate", fps)
            self._info.max_fps = fps
            log.debug("FlirDriver: frame rate → %.1f fps", fps)
        except Exception as exc:
            log.debug("FlirDriver: set_fps: %s", exc)

    # ------------------------------------------------------------------ #
    #  Thermal-camera-specific extras                                      #
    # ------------------------------------------------------------------ #

    def trigger_software(self) -> None:
        """
        Execute a single software trigger pulse.

        Only meaningful when ``trigger_mode`` is ``"Software"``.
        """
        if self._cam and self._open:
            try:
                self._cam.TriggerSoftware.Execute()
                log.debug("FlirDriver: software trigger fired")
            except Exception as exc:
                log.warning("FlirDriver: trigger_software failed: %s", exc)

    def do_ffc(self) -> None:
        """
        Execute an on-demand Flat Field Correction (NUC / shutter correction).

        FFC corrects pixel-to-pixel non-uniformity and is typically performed:
        - On startup (done automatically if ``ffc_mode`` is ``"auto"``)
        - After large temperature changes in the scene or ambient environment
        - Before each calibration sequence
        """
        if not (self._cam and self._open):
            return
        with self._node_lock:
            try:
                nm = self._cam.GetNodeMap()
                # Try GenICam command nodes in order of vendor preference
                for cmd in ("CorrectImageEx", "FlatFieldCorrection", "DoFFC"):
                    try:
                        _execute_command(nm, cmd)
                        log.debug("FlirDriver: FFC executed via '%s'", cmd)
                        return
                    except Exception:
                        continue
                log.warning("FlirDriver: no FFC command node found on this camera")
            except Exception as exc:
                log.warning("FlirDriver: do_ffc failed: %s", exc)

    # ------------------------------------------------------------------ #
    #  Introspection                                                       #
    # ------------------------------------------------------------------ #

    def exposure_range(self) -> tuple:
        """Return ``(min_µs, max_µs)`` from the camera node-map."""
        if self._cam and self._open:
            try:
                import PySpin
                node = self._cam.GetNodeMap().GetNode("ExposureTime")
                n = PySpin.CFloatPtr(node)
                if PySpin.IsAvailable(n) and PySpin.IsReadable(n):
                    return (n.GetMin(), n.GetMax())
            except Exception:
                pass
        return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        """Return ``(min_dB, max_dB)`` from the camera node-map."""
        if self._cam and self._open:
            try:
                import PySpin
                node = self._cam.GetNodeMap().GetNode("Gain")
                n = PySpin.CFloatPtr(node)
                if PySpin.IsAvailable(n) and PySpin.IsReadable(n):
                    return (n.GetMin(), n.GetMax())
            except Exception:
                pass
        return (0.0, 24.0)


# =========================================================================== #
#  Private node-map helpers                                                    #
#                                                                              #
#  All helpers gracefully no-op when a node is unavailable so that the driver  #
#  works across different FLIR camera families (Tau 2, Boson, Blackfly, etc.)  #
#  that may not expose every GenICam feature node.                             #
# =========================================================================== #

def _available(node) -> bool:
    """Return True if *node* is non-null and available."""
    import PySpin
    return (node is not None
            and not node.IsNULL()
            and PySpin.IsAvailable(node))


def _set_enum(nm, node_name: str, value: str, fallback: str = None) -> None:
    """
    Set an enumeration node to *value* by symbolic name.

    If *value* is not a valid entry and *fallback* is provided, attempt
    *fallback* instead.  Silently skips unavailable or read-only nodes.
    """
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return
    enum_node = PySpin.CEnumerationPtr(node)
    if not (PySpin.IsAvailable(enum_node) and PySpin.IsWritable(enum_node)):
        return
    entry = enum_node.GetEntryByName(value)
    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
        enum_node.SetIntValue(entry.GetValue())
    elif fallback is not None and fallback != value:
        _set_enum(nm, node_name, fallback)


def _get_int(nm, node_name: str, default: int = 0) -> int:
    """Return integer node value, or *default* if unavailable."""
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return default
    n = PySpin.CIntegerPtr(node)
    if PySpin.IsAvailable(n) and PySpin.IsReadable(n):
        return int(n.GetValue())
    return default


def _set_int_clamped(nm, node_name: str, value: int) -> None:
    """Set integer node to *value*, clamped to [min, max] and aligned to increment."""
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return
    n = PySpin.CIntegerPtr(node)
    if not (PySpin.IsAvailable(n) and PySpin.IsWritable(n)):
        return
    lo  = int(n.GetMin())
    hi  = int(n.GetMax())
    inc = int(n.GetInc()) or 1
    val = max(lo, min(hi, value))
    val = lo + ((val - lo) // inc) * inc   # align to increment
    n.SetValue(val)


def _set_int_max_if_zero(nm, node_name: str, value: int) -> None:
    """Set integer node to *value*, or to its hardware maximum when *value* == 0."""
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return
    n = PySpin.CIntegerPtr(node)
    if not (PySpin.IsAvailable(n) and PySpin.IsWritable(n)):
        return
    lo  = int(n.GetMin())
    hi  = int(n.GetMax())
    inc = int(n.GetInc()) or 1
    target = hi if value == 0 else value
    target = max(lo, min(hi, target))
    target = lo + ((target - lo) // inc) * inc
    n.SetValue(target)


def _set_exposure(nm, microseconds: float) -> None:
    """Disable auto-exposure then write ExposureTime to *microseconds*."""
    import PySpin
    _set_enum(nm, "ExposureAuto", "Off")
    node = nm.GetNode("ExposureTime")
    if not _available(node):
        return
    n = PySpin.CFloatPtr(node)
    if PySpin.IsAvailable(n) and PySpin.IsWritable(n):
        val = max(n.GetMin(), min(n.GetMax(), float(microseconds)))
        n.SetValue(val)


def _set_gain(nm, db: float) -> None:
    """Disable auto-gain then write Gain to *db*."""
    import PySpin
    _set_enum(nm, "GainAuto", "Off")
    node = nm.GetNode("Gain")
    if not _available(node):
        return
    n = PySpin.CFloatPtr(node)
    if PySpin.IsAvailable(n) and PySpin.IsWritable(n):
        val = max(n.GetMin(), min(n.GetMax(), float(db)))
        n.SetValue(val)


def _set_bool(nm, node_name: str, value: bool) -> None:
    """Write a boolean node."""
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return
    n = PySpin.CBooleanPtr(node)
    if PySpin.IsAvailable(n) and PySpin.IsWritable(n):
        n.SetValue(value)


def _set_float(nm, node_name: str, value: float) -> None:
    """Write a float node, clamped to its [min, max] range."""
    import PySpin
    node = nm.GetNode(node_name)
    if not _available(node):
        return
    n = PySpin.CFloatPtr(node)
    if PySpin.IsAvailable(n) and PySpin.IsWritable(n):
        val = max(n.GetMin(), min(n.GetMax(), float(value)))
        n.SetValue(val)


def _execute_command(nm, command_name: str) -> None:
    """Execute a GenICam command node (e.g. FFC, software trigger)."""
    import PySpin
    node = nm.GetNode(command_name)
    if not _available(node):
        raise RuntimeError(f"Command node '{command_name}' not available")
    cmd = PySpin.CCommandPtr(node)
    if PySpin.IsAvailable(cmd) and PySpin.IsWritable(cmd):
        cmd.Execute()
    else:
        raise RuntimeError(f"Command node '{command_name}' is not executable")
