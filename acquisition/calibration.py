"""
acquisition/calibration.py

Thermoreflectance calibration engine.

Physical model
--------------
The thermoreflectance signal is linear in temperature change:

    ΔR/R = C_T × ΔT

where
    C_T   — thermoreflectance coefficient  [1/K],  material + wavelength dependent
    ΔR/R  — measured reflectance change    [dimensionless]
    ΔT    — temperature change             [K or °C, same scale]

Calibration procedure
---------------------
1. Set TEC to temperature T1, capture reference frame I_ref
2. Step through temperatures T2, T3, ..., Tn
3. At each Ti capture frame I_i
4. Compute per-pixel  ΔR/R_i = (I_i - I_ref) / I_ref
5. Fit linear model   ΔR/R = C_T × ΔT  per pixel (least squares)
6. Slope C_T is the calibration coefficient map

Applying calibration to a measurement
--------------------------------------
    ΔT_map = drr_map / C_T_map       [°C]

Where C_T values near zero (uniform/dark regions) are masked out.

Usage
-----
    cal = Calibration()
    cal.add_point(temperature=25.0, frame=frame_25C)
    cal.add_point(temperature=30.0, frame=frame_30C)
    cal.add_point(temperature=35.0, frame=frame_35C)
    result = cal.fit()                       # CalibrationResult
    delta_T = result.apply(drr_map)          # convert ΔR/R → °C
    result.save("/path/to/cal.npz")
    result = CalibrationResult.load("/path/to/cal.npz")
"""

from __future__ import annotations
import time
import numpy as np
from dataclasses import dataclass
from typing import List, Optional

from ai.instrument_knowledge import CTH_FILTER_MIN


@dataclass
class CalibrationPoint:
    """One temperature step captured during calibration."""
    temperature: float          # °C — actual TEC-measured temperature
    frame:       np.ndarray     # float32 averaged intensity image
    timestamp:   float = 0.0


@dataclass
class CalibrationResult:
    """
    Per-pixel thermoreflectance coefficient map C_T.

    After fitting, apply() converts any ΔR/R map → ΔT map in °C.
    """
    # Core coefficient map
    ct_map:       Optional[np.ndarray] = None   # float32, shape (H, W) [1/K]

    # Fit quality metrics
    r2_map:       Optional[np.ndarray] = None   # float32, R² per pixel
    residual_map: Optional[np.ndarray] = None   # float32, RMS residual

    # Calibration metadata
    n_points:     int   = 0
    t_min:        float = 0.0   # °C
    t_max:        float = 0.0   # °C
    t_ref:        float = 0.0   # °C — reference temperature (first point)
    frame_h:      int   = 0
    frame_w:      int   = 0
    timestamp:    float = 0.0
    timestamp_str: str  = ""
    notes:        str   = ""
    valid:        bool  = False  # True after successful fit

    # Mask: pixels where C_T is reliable
    mask:         Optional[np.ndarray] = None   # bool, shape (H, W)

    # Per-pixel min C_T threshold (pixels below are masked).
    # Sourced from SanjANALYZER baseline script (Filter Magnitude Cth = 3e-6 K⁻¹).
    MIN_CT = CTH_FILTER_MIN   # 3e-6 K⁻¹

    # ---------------------------------------------------------------- #
    #  Apply calibration                                                #
    # ---------------------------------------------------------------- #

    def apply(self, drr_map: np.ndarray,
              fill_value: float = np.nan) -> np.ndarray:
        """
        Convert a ΔR/R map to a ΔT map in °C.

        drr_map:    float32 array, same H×W as calibration frame
        fill_value: value assigned to masked (unreliable) pixels
        Returns float32 ΔT array in °C.
        """
        if not self.valid or self.ct_map is None:
            raise RuntimeError("Calibration not valid — run fit() first.")

        drr  = drr_map.astype(np.float64)
        ct   = self.ct_map.astype(np.float64)

        # Avoid divide-by-zero on masked pixels
        ct_safe = np.where(
            (self.mask if self.mask is not None else np.ones_like(ct, bool)),
            ct, 1.0)

        dt = drr / ct_safe

        # Apply mask
        if self.mask is not None:
            dt[~self.mask] = fill_value

        return dt.astype(np.float32)

    # ---------------------------------------------------------------- #
    #  Save / Load                                                      #
    # ---------------------------------------------------------------- #

    def save(self, path: str) -> str:
        """
        Save calibration to a .npz file.
        path: full file path (will add .npz if not present)
        Returns the actual saved path.
        """
        if not path.endswith(".npz"):
            path += ".npz"
        arrays = {"ct_map": self.ct_map}
        if self.r2_map is not None:
            arrays["r2_map"] = self.r2_map
        if self.residual_map is not None:
            arrays["residual_map"] = self.residual_map
        if self.mask is not None:
            arrays["mask"] = self.mask.astype(np.uint8)
        np.savez_compressed(path, **arrays,
                            n_points     = self.n_points,
                            t_min        = self.t_min,
                            t_max        = self.t_max,
                            t_ref        = self.t_ref,
                            frame_h      = self.frame_h,
                            frame_w      = self.frame_w,
                            timestamp    = self.timestamp,
                            timestamp_str= self.timestamp_str,
                            notes        = self.notes,
                            valid        = self.valid)
        return path

    @staticmethod
    def load(path: str) -> "CalibrationResult":
        """Load a calibration from a .npz file."""
        d   = np.load(path, allow_pickle=True)
        cal = CalibrationResult()
        if "ct_map"       in d: cal.ct_map       = d["ct_map"]
        if "r2_map"       in d: cal.r2_map        = d["r2_map"]
        if "residual_map" in d: cal.residual_map  = d["residual_map"]
        if "mask"         in d: cal.mask          = d["mask"].astype(bool)
        cal.n_points      = int(d["n_points"])
        cal.t_min         = float(d["t_min"])
        cal.t_max         = float(d["t_max"])
        cal.t_ref         = float(d["t_ref"])
        cal.frame_h       = int(d["frame_h"])
        cal.frame_w       = int(d["frame_w"])
        cal.timestamp     = float(d["timestamp"])
        cal.timestamp_str = str(d["timestamp_str"])
        cal.notes         = str(d["notes"])
        cal.valid         = bool(d["valid"])
        return cal

    def __repr__(self):
        return (f"<CalibrationResult valid={self.valid} "
                f"n_points={self.n_points} "
                f"T={self.t_min:.1f}–{self.t_max:.1f}°C>")


# ------------------------------------------------------------------ #
#  Calibration builder                                                #
# ------------------------------------------------------------------ #

class Calibration:
    """
    Accumulates calibration points and fits the C_T coefficient map.

    Typical usage:
        cal = Calibration()
        for T, frame in zip(temperatures, frames):
            cal.add_point(T, frame)
        result = cal.fit()
    """

    def __init__(self):
        self._points: List[CalibrationPoint] = []

    def add_point(self, temperature: float,
                  frame: np.ndarray) -> None:
        """Add one calibration point."""
        self._points.append(CalibrationPoint(
            temperature = temperature,
            frame       = frame.astype(np.float32),
            timestamp   = time.time(),
        ))

    def clear(self):
        self._points.clear()

    @property
    def n_points(self) -> int:
        return len(self._points)

    @property
    def temperatures(self) -> List[float]:
        return [p.temperature for p in self._points]

    def fit(self, min_intensity: float = 10.0,
            min_r2: float = 0.80) -> CalibrationResult:
        """
        Fit per-pixel C_T from accumulated calibration points.

        min_intensity : pixels with reference intensity below this are masked
        min_r2        : pixels with R² below this are masked (poor linearity)

        Returns a CalibrationResult.
        """
        if len(self._points) < 2:
            raise ValueError(
                "Need at least 2 calibration points to fit C_T.")

        # Sort by temperature
        pts = sorted(self._points, key=lambda p: p.temperature)

        ref   = pts[0]
        t_ref = ref.temperature
        I_ref = ref.frame.astype(np.float64)
        H, W  = I_ref.shape[:2]

        temps  = np.array([p.temperature for p in pts], dtype=np.float64)
        dTs    = temps - t_ref     # [n_points] temperature offsets

        # Build ΔR/R array: shape (n_points, H, W)
        drr_stack = np.zeros((len(pts), H, W), dtype=np.float64)
        I_ref_safe = np.where(I_ref > min_intensity, I_ref, 1.0)
        for i, pt in enumerate(pts):
            drr_stack[i] = (pt.frame.astype(np.float64) - I_ref) / I_ref_safe

        # ---- Per-pixel linear least squares: ΔR/R = C_T × ΔT ----
        # Using the closed-form solution for y = m*x (no intercept,
        # forced through origin because ΔR/R = 0 when ΔT = 0)
        #
        # C_T = Σ(ΔT_i × ΔR/R_i) / Σ(ΔT_i²)
        #
        dT_col  = dTs.reshape(-1, 1, 1)              # (n, 1, 1)
        sum_xy  = np.sum(dT_col * drr_stack, axis=0) # (H, W)
        sum_x2  = np.sum(dTs**2)                      # scalar
        ct_map  = (sum_xy / sum_x2).astype(np.float32)

        # ---- R² per pixel ----
        drr_pred  = dT_col * ct_map[np.newaxis]          # predicted
        ss_res    = np.sum((drr_stack - drr_pred)**2, axis=0)
        drr_mean  = np.mean(drr_stack, axis=0)
        ss_tot    = np.sum((drr_stack - drr_mean[np.newaxis])**2, axis=0)
        ss_tot_safe = np.where(ss_tot > 1e-30, ss_tot, 1.0)
        r2_map    = (1.0 - ss_res / ss_tot_safe).astype(np.float32)

        # ---- RMS residual ----
        residual_map = np.sqrt(ss_res / len(pts)).astype(np.float32)

        # ---- Mask: reliable pixels ----
        mask = (
            (I_ref > min_intensity) &           # sufficient signal
            (np.abs(ct_map) > CalibrationResult.MIN_CT) &  # non-zero C_T
            (r2_map > min_r2)                   # good linear fit
        )

        ts  = time.time()
        result = CalibrationResult(
            ct_map        = ct_map,
            r2_map        = r2_map,
            residual_map  = residual_map,
            mask          = mask,
            n_points      = len(pts),
            t_min         = float(temps.min()),
            t_max         = float(temps.max()),
            t_ref         = t_ref,
            frame_h       = H,
            frame_w       = W,
            timestamp     = ts,
            timestamp_str = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            valid         = True,
        )
        return result
