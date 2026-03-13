"""
hardware/app_state.py

ApplicationState — a thread-safe container for all live hardware driver
references and active measurement objects.

Replaces the module-level globals (cam, fpga, stage …) in main_app.py.
Every read or write goes through a single RLock, making compound
read-check-write operations safe across background threads.

Usage
-----
    from hardware.app_state import app_state

    # Read
    cam = app_state.cam
    if cam is not None:
        frame = cam.grab()

    # Write (from any thread)
    with app_state:
        app_state.cam      = new_driver
        app_state.pipeline = AcquisitionPipeline(new_driver)

    # Convenience helper — get camera or raise
    cam = app_state.require_cam()   # raises RuntimeError if None

Design notes
------------
•  Reentrant lock (RLock) — the same thread may acquire multiple times.
•  Simple attribute access without the lock is safe for individual Python
   reference reads (the GIL guarantees atomicity), but compound
   operations (read → check → write) must use the context manager.
•  Background status threads that only read a single attribute (e.g.
   tec.get_status()) are safe without the lock.
"""

from __future__ import annotations
import threading
from typing import Optional, List


class ApplicationState:
    """
    Thread-safe singleton container for all live hardware drivers and
    active measurement objects.
    """

    def __init__(self):
        self._lock = threading.RLock()

        # ── Hardware drivers ────────────────────────────────────────
        self._cam      = None    # CameraDriver (TR)    | None — primary / TR camera
        self._ir_cam   = None    # CameraDriver (IR)    | None — secondary IR camera (hybrid only)
        self._active_camera_type: str = "tr"   # "tr" | "ir" — drives computed cam property
        self._fpga     = None    # FpgaDriver           | None
        self._bias     = None    # BiasDriver           | None
        self._stage    = None    # StageDriver          | None — microscope scan stage
        self._prober   = None    # StageDriver (prober) | None — probe-station chuck
        self._af       = None    # AutofocusDriver      | None
        self._turret   = None    # ObjectiveTurretDriver| None — motorized objective
        self._tecs: List = []    # List[TecDriver]
        self._tec_guards: List = []   # List[ThermalGuard | None]
        self._ldd      = None    # LddDriver            | None

        # ── Acquisition objects ─────────────────────────────────────
        self._pipeline = None    # AcquisitionPipeline | None

        # ── Active measurement context ──────────────────────────────
        self._active_calibration  = None   # CalibrationResult | None
        self._active_profile      = None   # MaterialProfile   | None
        self._active_analysis     = None   # AnalysisResult    | None
        self._active_modality     = "thermoreflectance"  # str
        self._active_objective    = None   # ObjectiveSpec | None — from turret

        # ── System identification ────────────────────────────────────
        self._system_model: Optional[str] = None  # e.g. "EZ500" / "NT220" / "PT410A"

        # ── Demo mode ───────────────────────────────────────────────
        self._demo_mode: bool = False     # True when running on simulated hardware

        # ── License ──────────────────────────────────────────────────
        # Populated at startup by main_app._load_license().
        # Use app_state.license_info to read; never import LicenseInfo here
        # to keep this module free of the cryptography dependency.
        self._license_info = None         # LicenseInfo | None

    # ── Context manager (use for compound operations) ───────────────

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *_):
        self._lock.release()

    # ── License property ─────────────────────────────────────────────

    @property
    def license_info(self):
        """Current LicenseInfo (or None before startup completes)."""
        with self._lock:
            return self._license_info

    @license_info.setter
    def license_info(self, value) -> None:
        with self._lock:
            self._license_info = value

    @property
    def is_licensed(self) -> bool:
        """True when a valid, non-expired, non-UNLICENSED key is loaded."""
        info = self._license_info
        return info is not None and info.is_active

    # ── Demo mode property ───────────────────────────────────────────

    @property
    def demo_mode(self) -> bool:
        with self._lock:
            return self._demo_mode

    @demo_mode.setter
    def demo_mode(self, value: bool) -> None:
        with self._lock:
            self._demo_mode = bool(value)

    # ── Hardware driver properties ───────────────────────────────────

    @property
    def cam(self):
        """Active camera driver.

        On single-camera systems returns the primary (TR) camera.
        On hybrid systems returns tr_cam or ir_cam based on active_camera_type.
        The hardware grab loop re-reads this every iteration, so switching
        active_camera_type automatically redirects frame acquisition.
        """
        if self._ir_cam is not None:
            return self._cam if self._active_camera_type == "tr" else self._ir_cam
        return self._cam

    @cam.setter
    def cam(self, value):
        """Set the primary (TR) camera. Backward-compatible with all existing callers."""
        with self._lock:
            self._cam = value

    @property
    def ir_cam(self):
        """Secondary IR camera driver (None on non-hybrid systems)."""
        return self._ir_cam

    @ir_cam.setter
    def ir_cam(self, value):
        with self._lock:
            self._ir_cam = value

    @property
    def active_camera_type(self) -> str:
        """Currently selected camera type: 'tr' or 'ir'."""
        return self._active_camera_type

    @active_camera_type.setter
    def active_camera_type(self, value: str) -> None:
        if value not in ("tr", "ir"):
            raise ValueError(f"active_camera_type must be 'tr' or 'ir', got {value!r}")
        with self._lock:
            self._active_camera_type = value
            # Keep active_modality in sync
            self._active_modality = (
                "thermoreflectance" if value == "tr" else "ir_lockin"
            )

    @property
    def fpga(self):
        return self._fpga

    @fpga.setter
    def fpga(self, value):
        with self._lock:
            self._fpga = value

    @property
    def bias(self):
        return self._bias

    @bias.setter
    def bias(self, value):
        with self._lock:
            self._bias = value

    @property
    def stage(self):
        return self._stage

    @stage.setter
    def stage(self, value):
        with self._lock:
            self._stage = value

    @property
    def prober(self):
        """Probe-station chuck stage (distinct from microscope scan stage)."""
        return self._prober

    @prober.setter
    def prober(self, value):
        with self._lock:
            self._prober = value

    @property
    def turret(self):
        """Motorized objective turret driver."""
        return self._turret

    @turret.setter
    def turret(self, value):
        with self._lock:
            self._turret = value

    @property
    def af(self):
        return self._af

    @af.setter
    def af(self, value):
        with self._lock:
            self._af = value

    @property
    def tecs(self) -> list:
        return self._tecs

    @tecs.setter
    def tecs(self, value: list):
        with self._lock:
            self._tecs = list(value)

    def add_tec(self, tec) -> int:
        """Thread-safely append a TEC driver and return its index."""
        with self._lock:
            self._tecs.append(tec)
            self._tec_guards.append(None)   # guard registered separately
            return len(self._tecs) - 1

    @property
    def ldd(self):
        """Laser Diode Driver (LDD-1121 or simulated)."""
        return self._ldd

    @ldd.setter
    def ldd(self, value):
        with self._lock:
            self._ldd = value

    def set_tec_guard(self, index: int, guard) -> None:
        """Register a ThermalGuard for the given TEC index."""
        with self._lock:
            while len(self._tec_guards) <= index:
                self._tec_guards.append(None)
            self._tec_guards[index] = guard

    def get_tec_guard(self, index: int):
        """Return the ThermalGuard for the given index, or None."""
        with self._lock:
            if 0 <= index < len(self._tec_guards):
                return self._tec_guards[index]
            return None

    # ── Pipeline ────────────────────────────────────────────────────

    @property
    def pipeline(self):
        return self._pipeline

    @pipeline.setter
    def pipeline(self, value):
        with self._lock:
            self._pipeline = value

    # ── Active measurement context ───────────────────────────────────

    @property
    def active_calibration(self):
        return self._active_calibration

    @active_calibration.setter
    def active_calibration(self, value):
        with self._lock:
            self._active_calibration = value

    @property
    def active_profile(self):
        return self._active_profile

    @active_profile.setter
    def active_profile(self, value):
        with self._lock:
            self._active_profile = value

    @property
    def active_analysis(self):
        return self._active_analysis

    @active_analysis.setter
    def active_analysis(self, value):
        with self._lock:
            self._active_analysis = value

    @property
    def active_modality(self) -> str:
        return self._active_modality

    @active_modality.setter
    def active_modality(self, value: str):
        with self._lock:
            self._active_modality = value

    @property
    def active_objective(self):
        """Currently selected ObjectiveSpec (from turret), or None."""
        return self._active_objective

    @active_objective.setter
    def active_objective(self, value):
        with self._lock:
            self._active_objective = value

    # ── System identification ────────────────────────────────────────

    @property
    def system_model(self) -> Optional[str]:
        """Instrument model key (e.g. 'EZ500', 'NT220', 'PT410A'), or None."""
        return self._system_model

    @system_model.setter
    def system_model(self, value: Optional[str]) -> None:
        with self._lock:
            self._system_model = value if value is None else str(value)

    # ── Convenience helpers ──────────────────────────────────────────

    def require_cam(self):
        """Return active camera driver or raise RuntimeError if not connected."""
        c = self.cam   # computed property — returns active camera
        if c is None:
            raise RuntimeError("Camera not connected.")
        return c

    def require_fpga(self):
        """Return FPGA driver or raise RuntimeError if not connected."""
        f = self._fpga
        if f is None:
            raise RuntimeError("FPGA not connected.")
        return f

    def require_stage(self):
        """Return stage driver or raise RuntimeError if not connected."""
        s = self._stage
        if s is None:
            raise RuntimeError("Stage not connected.")
        return s

    def require_ldd(self):
        """Return LDD driver or raise RuntimeError if not connected."""
        d = self._ldd
        if d is None:
            raise RuntimeError("Laser diode driver not connected.")
        return d

    def snapshot(self) -> dict:
        """Return a dict snapshot of all driver references (for logging/debugging)."""
        with self._lock:
            obj = self._active_objective
            return {
                "cam":         type(self._cam).__name__    if self._cam    else None,
                "ir_cam":      type(self._ir_cam).__name__ if self._ir_cam else None,
                "active_camera_type": self._active_camera_type,
                "fpga":     type(self._fpga).__name__     if self._fpga     else None,
                "bias":     type(self._bias).__name__     if self._bias     else None,
                "ldd":      type(self._ldd).__name__      if self._ldd      else None,
                "stage":    type(self._stage).__name__    if self._stage    else None,
                "prober":   type(self._prober).__name__   if self._prober   else None,
                "turret":   type(self._turret).__name__   if self._turret   else None,
                "af":       type(self._af).__name__       if self._af       else None,
                "tecs":     [type(t).__name__ for t in self._tecs],
                "pipeline": type(self._pipeline).__name__ if self._pipeline else None,
                "calibration_valid": (
                    self._active_calibration.valid
                    if self._active_calibration else None),
                "profile":  (
                    self._active_profile.name
                    if self._active_profile else None),
                "modality":      self._active_modality,
                "system_model":  self._system_model,
                "objective": (
                    {"magnification": obj.magnification,
                     "na":            obj.numerical_aperture,
                     "label":         obj.label}
                    if obj else None),
            }

    def is_hardware_ready(self) -> bool:
        """True if at minimum a camera is connected."""
        return self._cam is not None


# ── Module-level singleton ───────────────────────────────────────────

app_state = ApplicationState()
