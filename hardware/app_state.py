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
        self._cam      = None    # CameraDriver | None
        self._fpga     = None    # FpgaDriver   | None
        self._bias     = None    # BiasDriver    | None
        self._stage    = None    # StageDriver   | None
        self._af       = None    # AutofocusDriver | None
        self._tecs: List = []    # List[TecDriver]

        # ── Acquisition objects ─────────────────────────────────────
        self._pipeline = None    # AcquisitionPipeline | None

        # ── Active measurement context ──────────────────────────────
        self._active_calibration = None   # CalibrationResult | None
        self._active_profile     = None   # MaterialProfile   | None
        self._active_analysis    = None   # AnalysisResult    | None
        self._active_modality    = "thermoreflectance"  # str

    # ── Context manager (use for compound operations) ───────────────

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *_):
        self._lock.release()

    # ── Hardware driver properties ───────────────────────────────────

    @property
    def cam(self):
        return self._cam

    @cam.setter
    def cam(self, value):
        with self._lock:
            self._cam = value

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
            return len(self._tecs) - 1

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

    # ── Convenience helpers ──────────────────────────────────────────

    def require_cam(self):
        """Return camera driver or raise RuntimeError if not connected."""
        c = self._cam
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

    def snapshot(self) -> dict:
        """Return a dict snapshot of all driver references (for logging/debugging)."""
        with self._lock:
            return {
                "cam":      type(self._cam).__name__      if self._cam      else None,
                "fpga":     type(self._fpga).__name__     if self._fpga     else None,
                "bias":     type(self._bias).__name__     if self._bias     else None,
                "stage":    type(self._stage).__name__    if self._stage    else None,
                "af":       type(self._af).__name__       if self._af       else None,
                "tecs":     [type(t).__name__ for t in self._tecs],
                "pipeline": type(self._pipeline).__name__ if self._pipeline else None,
                "calibration_valid": (
                    self._active_calibration.valid
                    if self._active_calibration else None),
                "profile":  (
                    self._active_profile.name
                    if self._active_profile else None),
                "modality": self._active_modality,
            }

    def is_hardware_ready(self) -> bool:
        """True if at minimum a camera is connected."""
        return self._cam is not None


# ── Module-level singleton ───────────────────────────────────────────

app_state = ApplicationState()
