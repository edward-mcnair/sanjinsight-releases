"""
hardware/cameras/base.py

Abstract base class for all camera drivers.
The application only ever calls this interface — never driver-specific code.

To add a new camera:
  1. Create hardware/cameras/my_camera.py
  2. Subclass CameraDriver and implement all abstract methods
  3. Add an entry to hardware/cameras/factory.py
  4. Set driver: "my_camera" in config.yaml

That's it. No other files change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class CameraFrame:
    """A single acquired frame with metadata."""
    data:        np.ndarray          # (H, W) grayscale or (H, W, 3) RGB
    frame_index: int      = 0
    exposure_us: float    = 0.0
    gain_db:     float    = 0.0
    timestamp:   float    = 0.0      # time.time() at grab
    channels:    int      = 1        # 1 = mono, 3 = RGB
    bit_depth:   int      = 12       # native sensor bit depth


@dataclass
class CameraInfo:
    """Static info reported by the driver after open()."""
    driver:      str   = ""
    model:       str   = ""
    serial:      str   = ""
    width:       int   = 0
    height:      int   = 0
    bit_depth:   int   = 12
    max_fps:     float = 0.0
    camera_type: str   = "tr"   # "tr" (thermoreflectance) | "ir" (infrared)
    pixel_format: str  = "mono" # "mono" | "bayer_rggb" | "rgb" | "bgr"


class CameraDriver(ABC):
    """
    Abstract camera driver.

    Lifecycle:
        driver = SomeDriver(config_dict)
        driver.open()
        frame = driver.grab()
        driver.set_exposure(5000.0)
        driver.close()

    All drivers must be thread-safe for grab() — it is called from a
    background thread. set_exposure / set_gain may briefly block.
    """

    def __init__(self, cfg: dict):
        self._cfg     = cfg
        self._open    = False
        self._info    = CameraInfo()

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def open(self) -> None:
        """
        Open the camera and prepare for acquisition.
        Raises RuntimeError on failure.
        """

    def connect(self) -> None:
        """Alias for open() — satisfies the DeviceManager driver interface."""
        self.open()

    def disconnect(self) -> None:
        """Alias for close() — satisfies the DeviceManager driver interface."""
        self.close()

    @abstractmethod
    def start(self) -> None:
        """Begin continuous acquisition."""

    @abstractmethod
    def stop(self) -> None:
        """Stop continuous acquisition without closing the camera."""

    @abstractmethod
    def close(self) -> None:
        """Stop acquisition and release all hardware resources."""

    # ---------------------------------------------------------------- #
    #  Acquisition                                                      #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        """
        Return the latest frame, or None on timeout.
        Must be safe to call from a background thread.
        """

    # ---------------------------------------------------------------- #
    #  Attribute control                                                #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def set_exposure(self, microseconds: float) -> None:
        """Set exposure time in microseconds."""

    def get_exposure(self) -> float:
        """Return current exposure time in microseconds. Override for live readback."""
        return self._cfg.get("exposure_us", 0.0)

    @abstractmethod
    def set_gain(self, db: float) -> None:
        """Set analog gain in dB."""

    def get_gain(self) -> float:
        """Return current gain in dB. Override for live readback."""
        return self._cfg.get("gain_db", 0.0)

    def set_trigger(self, mode: str) -> None:
        """
        Set trigger mode. Default implementation is a no-op —
        drivers that support triggering should override this.
        Modes: "Off", "Software", "Hardware"
        """
        pass

    def supports_runtime_resolution(self) -> bool:
        """
        Return True if this driver can change resolution after open().
        Real hardware drivers almost always return False — the sensor
        binning / ROI must be configured before streaming begins.
        The simulated driver returns True.
        """
        return False

    def set_resolution(self, width: int, height: int) -> None:
        """
        Change the capture resolution at runtime.

        Only meaningful for drivers where supports_runtime_resolution()
        returns True.  The default implementation is a no-op so callers
        can safely invoke it without checking the support flag first.

        Implementations must be thread-safe (called from the GUI thread
        while the camera grab loop runs on a background thread).
        After returning, info.width / info.height reflect the new size.
        """
        pass

    def set_fps(self, fps: float) -> None:
        """
        Change the target frame rate at runtime.

        Default implementation is a no-op.  Override in drivers that
        support runtime frame-rate adjustment.
        After returning, info.max_fps reflects the new rate.
        """
        pass

    # ---------------------------------------------------------------- #
    #  Flat-Field Correction (thermal cameras)                          #
    # ---------------------------------------------------------------- #

    def supports_ffc(self) -> bool:
        """Return True if this camera supports Flat-Field Correction."""
        return False

    def do_ffc(self) -> bool:
        """Trigger a Flat-Field Correction. Returns True on success."""
        return False

    @property
    def last_ffc_time(self):
        """Return ``time.time()`` of last successful FFC, or ``None``."""
        return getattr(self, "_last_ffc_time", None)

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def info(self) -> CameraInfo:
        return self._info

    @property
    def is_open(self) -> bool:
        return self._open

    def exposure_range(self) -> tuple:
        """Return (min_us, max_us). Override for tighter limits."""
        return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        """Return (min_db, max_db). Override for tighter limits."""
        return (0.0, 24.0)

    # ---------------------------------------------------------------- #
    #  Pre-flight validation                                           #
    # ---------------------------------------------------------------- #

    @classmethod
    def preflight(cls) -> tuple:
        """
        Check whether this driver's dependencies are satisfied
        **before** attempting to open hardware.

        Returns
        -------
        (ok: bool, issues: list[str])
            ok     — True if connect() is safe to call.
            issues — Human-readable list of problems found (empty when ok).

        Subclasses should override this to verify required Python packages
        are importable and any other prerequisites are met.  The default
        implementation always returns (True, []) so unimplemented drivers
        are not blocked.

        Called by DeviceManager._connect_worker() before instantiating
        the driver.  Any issue returned here is shown to the user as a
        clear, actionable message rather than a raw Python traceback.
        """
        return (True, [])

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"model={self._info.model!r} open={self._open}>")
