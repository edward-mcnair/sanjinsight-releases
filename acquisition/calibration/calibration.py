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

try:
    from ai.instrument_knowledge import CTH_FILTER_MIN
except ImportError:
    # ai package not available (e.g. lightweight deployment) — use physics default.
    # Minimum meaningful thermoreflectance coefficient for silicon at 532 nm.
    CTH_FILTER_MIN = 1e-5   # 1/K


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

    Extended model support
    ----------------------
    In addition to the classic linear model  ΔR/R = C_T × ΔT  this class
    optionally stores the results of an exponential fit:

        ΔR/R = A × exp(B × ΔT)

    When fit_auto() is used, a per-pixel model-selection map (fit_type_map)
    records which model was chosen:
        0 = linear      (stored in ct_map)
        1 = exponential (A stored in exp_a_map, B stored in exp_b_map)

    apply_exponential() inverts the exponential model to return ΔT.
    """
    # Core coefficient map (linear model)
    ct_map:       Optional[np.ndarray] = None   # float32, shape (H, W) [1/K]

    # Exponential model coefficient maps: ΔR/R = A × exp(B × ΔT)
    exp_a_map:    Optional[np.ndarray] = None   # float32, shape (H, W)
    exp_b_map:    Optional[np.ndarray] = None   # float32, shape (H, W) [1/K]

    # Fit quality metrics
    r2_map:       Optional[np.ndarray] = None   # float32, R² per pixel
    residual_map: Optional[np.ndarray] = None   # float32, RMS residual

    # Per-pixel model-selection map (0 = linear, 1 = exponential).
    # Populated by fit_auto(); None when only one model was fitted.
    fit_type_map: Optional[np.ndarray] = None   # uint8, shape (H, W)

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

    # Per-step curve data — populated by Calibration.fit(); absent when loading
    # older .cal files.  Used by CalibrationQualityChart to draw the actual
    # temperature → mean-signal calibration curve.
    temps_c:      Optional[np.ndarray] = None   # float64 (n_points,)  °C
    mean_signals: Optional[np.ndarray] = None   # float64 (n_points,)  mean ΔR/R per step

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

    def apply_exponential(
        self,
        drr_map: np.ndarray,
        fill_value: float = np.nan,
    ) -> np.ndarray:
        """
        Convert a ΔR/R map to a ΔT map using the exponential model.

        Exponential model (per pixel):
            ΔR/R = A × exp(B × ΔT)
            → ΔT  = ln(ΔR/R / A) / B

        This is the inversion of the model fitted by Calibration.fit_exponential().
        Pixels where A ≈ 0, B ≈ 0, or the argument of ln is non-positive are
        masked out (set to fill_value).

        Parameters
        ----------
        drr_map    : float32 (H, W) thermoreflectance map.
        fill_value : value assigned to masked or invalid pixels (default NaN).

        Returns
        -------
        float32 (H, W) ΔT map in °C.
        """
        if self.exp_a_map is None or self.exp_b_map is None:
            raise RuntimeError(
                "Exponential model not fitted — run fit_exponential() first."
            )

        drr = drr_map.astype(np.float64)
        A   = self.exp_a_map.astype(np.float64)
        B   = self.exp_b_map.astype(np.float64)

        # Argument of ln must be positive.
        eps = np.finfo(np.float64).eps
        arg = np.where(np.abs(A) > eps, drr / A, np.nan)

        # B must be non-zero to divide.
        b_safe = np.where(np.abs(B) > eps, B, np.nan)

        # ln of non-positive argument is undefined.
        with np.errstate(invalid="ignore", divide="ignore"):
            dt = np.where(arg > 0, np.log(arg) / b_safe, np.nan)

        # Apply validity mask.
        if self.mask is not None:
            dt[~self.mask] = fill_value

        # Replace any remaining NaN/inf introduced by bad pixels.
        dt[~np.isfinite(dt)] = fill_value

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
        arrays: dict = {}
        if self.ct_map is not None:
            arrays["ct_map"] = self.ct_map
        if self.exp_a_map is not None:
            arrays["exp_a_map"] = self.exp_a_map
        if self.exp_b_map is not None:
            arrays["exp_b_map"] = self.exp_b_map
        if self.r2_map is not None:
            arrays["r2_map"] = self.r2_map
        if self.residual_map is not None:
            arrays["residual_map"] = self.residual_map
        if self.mask is not None:
            arrays["mask"] = self.mask.astype(np.uint8)
        if self.fit_type_map is not None:
            arrays["fit_type_map"] = self.fit_type_map.astype(np.uint8)
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
        if "ct_map"       in d: cal.ct_map        = d["ct_map"]
        if "exp_a_map"    in d: cal.exp_a_map      = d["exp_a_map"]
        if "exp_b_map"    in d: cal.exp_b_map      = d["exp_b_map"]
        if "r2_map"       in d: cal.r2_map         = d["r2_map"]
        if "residual_map" in d: cal.residual_map   = d["residual_map"]
        if "mask"         in d: cal.mask           = d["mask"].astype(bool)
        if "fit_type_map" in d: cal.fit_type_map   = d["fit_type_map"].astype(np.uint8)
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

    # ---------------------------------------------------------------- #
    #  Shared helpers (private)                                         #
    # ---------------------------------------------------------------- #

    def _build_drr_stack(
        self,
        min_intensity: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int, int]:
        """
        Sort calibration points by temperature, build the ΔR/R stack, and
        return the components needed by all fit methods.

        Returns
        -------
        (drr_stack, dTs, I_ref, t_ref, H, W)
            drr_stack : float64 (n_points, H, W) — per-pixel ΔR/R at each step
            dTs       : float64 (n_points,)      — temperature offsets from ref
            I_ref     : float64 (H, W)            — reference intensity
            t_ref     : float — reference temperature (°C)
            H, W      : image height and width
        """
        if len(self._points) < 2:
            raise ValueError(
                "Need at least 2 calibration points to fit."
            )
        pts   = sorted(self._points, key=lambda p: p.temperature)
        ref   = pts[0]
        t_ref = ref.temperature
        I_ref = ref.frame.astype(np.float64)
        H, W  = I_ref.shape[:2]

        temps  = np.array([p.temperature for p in pts], dtype=np.float64)
        dTs    = temps - t_ref

        I_ref_safe = np.where(I_ref > min_intensity, I_ref, 1.0)
        drr_stack  = np.zeros((len(pts), H, W), dtype=np.float64)
        for i, pt in enumerate(pts):
            drr_stack[i] = (pt.frame.astype(np.float64) - I_ref) / I_ref_safe

        return drr_stack, dTs, I_ref, t_ref, H, W

    @staticmethod
    def _compute_r2(
        drr_stack: np.ndarray,
        drr_pred: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute per-pixel R² and RMS residual.

        Parameters
        ----------
        drr_stack : float64 (n, H, W) — observed ΔR/R values.
        drr_pred  : float64 (n, H, W) — model-predicted ΔR/R values.

        Returns
        -------
        (r2_map, residual_map) — both float32 (H, W).
        """
        n      = drr_stack.shape[0]
        ss_res = np.sum((drr_stack - drr_pred) ** 2, axis=0)
        drr_mean  = np.mean(drr_stack, axis=0)
        ss_tot    = np.sum((drr_stack - drr_mean[np.newaxis]) ** 2, axis=0)
        ss_tot_safe = np.where(ss_tot > 1e-30, ss_tot, 1.0)
        r2_map      = (1.0 - ss_res / ss_tot_safe).astype(np.float32)
        residual_map = np.sqrt(ss_res / n).astype(np.float32)
        return r2_map, residual_map

    # ---------------------------------------------------------------- #
    #  Fit methods                                                      #
    # ---------------------------------------------------------------- #

    def fit(self, min_intensity: float = 10.0,
            min_r2: float = 0.80) -> CalibrationResult:
        """
        Fit per-pixel C_T from accumulated calibration points (linear model).

        Physical model: ΔR/R = C_T × ΔT

        The fit is performed by closed-form ordinary least squares with the
        intercept forced through the origin (ΔR/R = 0 when ΔT = 0):

            C_T = Σ(ΔT_i × ΔR/R_i) / Σ(ΔT_i²)

        All operations are fully vectorised over pixels (H × W).

        Parameters
        ----------
        min_intensity : pixels whose reference-frame intensity is below this
                        count threshold are masked as dark/unreliable.
        min_r2        : pixels with R² below this are masked (poor linearity).

        Returns
        -------
        CalibrationResult with ct_map, r2_map, residual_map, and mask.
        """
        drr_stack, dTs, I_ref, t_ref, H, W = self._build_drr_stack(
            min_intensity
        )
        pts   = sorted(self._points, key=lambda p: p.temperature)
        temps = np.array([p.temperature for p in pts], dtype=np.float64)

        # ---- Per-pixel linear least squares: ΔR/R = C_T × ΔT ----
        dT_col  = dTs.reshape(-1, 1, 1)               # (n, 1, 1)
        sum_xy  = np.sum(dT_col * drr_stack, axis=0)  # (H, W)
        sum_x2  = float(np.sum(dTs ** 2))              # scalar
        if sum_x2 == 0.0:
            raise ValueError("All temperature offsets are zero — cannot fit.")
        ct_map  = (sum_xy / sum_x2).astype(np.float32)

        drr_pred  = dT_col * ct_map[np.newaxis]
        r2_map, residual_map = self._compute_r2(drr_stack, drr_pred)

        # ---- Mask: reliable pixels ----
        mask = (
            (I_ref > min_intensity) &
            (np.abs(ct_map) > CalibrationResult.MIN_CT) &
            (r2_map > min_r2)
        )

        # Per-step mean ΔR/R (spatial average) — used by CalibrationQualityChart
        # to draw the temperature → mean-signal curve.
        mean_signals = np.array(
            [float(drr_stack[i].mean()) for i in range(len(pts))],
            dtype=np.float64,
        )

        ts = time.time()
        return CalibrationResult(
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
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(ts)),
            temps_c       = temps,
            mean_signals  = mean_signals,
            valid         = True,
        )

    def fit_exponential(
        self,
        min_intensity: float = 10.0,
        min_r2: float = 0.80,
    ) -> CalibrationResult:
        """
        Fit per-pixel exponential model from accumulated calibration points.

        Physical model: ΔR/R = A × exp(B × ΔT)

        Linearised by taking the natural logarithm of both sides:

            ln(ΔR/R) = ln(A) + B × ΔT

        This is an ordinary least-squares problem in {ln(A), B}.  The fit is
        only attempted at pixels where all ΔR/R values are strictly positive
        (required for the logarithm), and where |ΔR/R| > ε at every
        temperature step.  Pixels that fail these criteria fall back to the
        linear model (ct_map) and are flagged in the mask.

        All pixel-loop operations are fully vectorised using 2-D numpy arrays.

        Parameters
        ----------
        min_intensity : dark-pixel intensity threshold (same as fit()).
        min_r2        : R² threshold below which pixels are masked.

        Returns
        -------
        CalibrationResult with:
            ct_map      — linear fallback coefficient (set to NaN for pixels
                          that could not use the linear model; present for API
                          compatibility)
            exp_a_map   — A coefficient map (float32, H × W)
            exp_b_map   — B coefficient map (float32, H × W) [1/K]
            r2_map      — R² of the exponential fit per pixel
            residual_map— RMS residual of the exponential fit
            mask        — reliable pixels (bool, H × W)
        """
        drr_stack, dTs, I_ref, t_ref, H, W = self._build_drr_stack(
            min_intensity
        )
        pts   = sorted(self._points, key=lambda p: p.temperature)
        temps = np.array([p.temperature for p in pts], dtype=np.float64)
        n     = len(pts)

        # ---- Pixels eligible for exponential fit ----
        # All ΔR/R values must be strictly positive for ln() to be defined.
        drr_min = np.min(drr_stack, axis=0)   # (H, W)
        eps     = np.finfo(np.float64).eps
        can_exp = drr_min > eps                # (H, W) bool

        # Work on float64 for numerical stability.
        ln_drr = np.where(
            can_exp[np.newaxis] & (drr_stack > eps),
            np.log(np.where(drr_stack > eps, drr_stack, 1.0)),
            np.nan,
        )  # (n, H, W)

        # ---- Vectorised OLS for ln(ΔR/R) = ln(A) + B × ΔT ----
        # Design matrix columns: [1, ΔT].
        # Closed-form solution (no pixel loop):
        #   [ln_A, B] = (XᵀX)⁻¹ Xᵀ Y  per pixel.
        #
        # Because X is the same for all pixels, XᵀX is a scalar 2×2 matrix;
        # only Xᵀ Y varies per pixel.
        #
        # X shape: (n, 2)   — the design matrix (same for every pixel)
        # Y shape: (n,H,W)  — ln(ΔR/R) at each pixel

        X     = np.column_stack([np.ones(n), dTs])          # (n, 2)
        XtX   = X.T @ X                                      # (2, 2) — scalar
        # Use pinv instead of inv — handles degenerate calibration data
        # (e.g. all identical temperatures) without raising LinAlgError.
        XtX_inv = np.linalg.pinv(XtX)                        # (2, 2)

        # Xᵀ Y  — shape (2, H, W).
        # ln_drr: (n, H, W) → treat NaN as 0 in sum, track counts separately.
        valid_mask = np.isfinite(ln_drr)                     # (n, H, W)
        ln_drr_safe = np.where(valid_mask, ln_drr, 0.0)

        # XtY[k, i, j] = Σ_m X[m, k] * ln_drr[m, i, j]
        XtY = np.tensordot(X.T, ln_drr_safe, axes=([1], [0]))  # (2, H, W)

        # Coefficients: (2, H, W)
        # coeffs[0] = ln(A),  coeffs[1] = B
        coeffs = np.tensordot(XtX_inv, XtY, axes=([1], [0]))   # (2, H, W)

        ln_A_map = coeffs[0]                                  # (H, W)
        B_map    = coeffs[1]                                  # (H, W)
        A_map    = np.exp(ln_A_map)                           # (H, W)

        # ---- Predicted ΔR/R from exponential model ----
        dT_col   = dTs.reshape(-1, 1, 1)
        drr_pred = A_map[np.newaxis] * np.exp(B_map[np.newaxis] * dT_col)
        # (n, H, W)

        r2_map, residual_map = self._compute_r2(drr_stack, drr_pred)

        # For pixels where exponential fit was not applicable, zero the maps.
        A_map = np.where(can_exp, A_map, np.nan).astype(np.float32)
        B_map = np.where(can_exp, B_map, np.nan).astype(np.float32)

        # ---- Mask: reliable pixels ----
        mask = (
            (I_ref > min_intensity) &
            can_exp &
            np.isfinite(A_map) &
            np.isfinite(B_map) &
            (r2_map > min_r2)
        )

        ts = time.time()
        return CalibrationResult(
            # No ct_map for pure exponential result; set to NaN array for
            # API compatibility (apply() will raise if called on this result).
            ct_map        = np.full((H, W), np.nan, dtype=np.float32),
            exp_a_map     = A_map,
            exp_b_map     = B_map,
            r2_map        = r2_map.astype(np.float32),
            residual_map  = residual_map.astype(np.float32),
            mask          = mask,
            n_points      = n,
            t_min         = float(temps.min()),
            t_max         = float(temps.max()),
            t_ref         = t_ref,
            frame_h       = H,
            frame_w       = W,
            timestamp     = ts,
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(ts)),
            valid         = True,
        )

    def fit_auto(
        self,
        min_intensity: float = 10.0,
        min_r2_linear: float = 0.90,
        min_r2_exp: float = 0.80,
    ) -> CalibrationResult:
        """
        Per-pixel automatic model selection: linear vs. exponential.

        Algorithm
        ---------
        1. Fit the linear model (ΔR/R = C_T × ΔT) for all pixels.
        2. Fit the exponential model (ΔR/R = A × exp(B × ΔT)) for all pixels.
        3. For each pixel, choose the model that gives the higher R²:
           - If linear R² ≥ min_r2_linear and linear R² ≥ exponential R²,
             use linear.
           - Otherwise, if exponential R² ≥ min_r2_exp, use exponential.
           - Pixels where neither model achieves threshold R² are masked out.
        4. Populate fit_type_map: 0 = linear, 1 = exponential.

        The returned CalibrationResult contains coefficient maps for both
        models.  apply() uses ct_map (linear), apply_exponential() uses
        exp_a_map/exp_b_map.  The caller can inspect fit_type_map to determine
        which method to invoke per pixel, or implement a combined converter.

        Parameters
        ----------
        min_intensity  : dark-pixel intensity threshold.
        min_r2_linear  : minimum R² to accept linear model (default 0.90).
        min_r2_exp     : minimum R² to accept exponential model (default 0.80,
                         slightly lower to allow fallback for non-linear pixels).

        Returns
        -------
        CalibrationResult with:
            ct_map       — linear coefficient (NaN where exponential was chosen)
            exp_a_map    — exponential A (NaN where linear was chosen)
            exp_b_map    — exponential B (NaN where linear was chosen)
            r2_map       — best R² per pixel (from whichever model was selected)
            residual_map — best-model residual per pixel
            fit_type_map — uint8 (H, W): 0 = linear, 1 = exponential
            mask         — pixels where at least one model was accepted
        """
        lin_result = self.fit(
            min_intensity=min_intensity,
            min_r2=0.0,          # no threshold yet — select after comparison
        )
        exp_result = self.fit_exponential(
            min_intensity=min_intensity,
            min_r2=0.0,
        )

        r2_lin = lin_result.r2_map.astype(np.float64)   # (H, W)
        r2_exp = exp_result.r2_map.astype(np.float64)   # (H, W)

        H, W = r2_lin.shape

        # Pixels where each model achieves its threshold.
        lin_ok = r2_lin >= min_r2_linear
        exp_ok = r2_exp >= min_r2_exp

        # Per-pixel model selection.
        # Prefer linear if it meets threshold AND is as good as exponential.
        use_linear = lin_ok & (r2_lin >= r2_exp)
        use_exp    = exp_ok & ~use_linear

        # Mask: at least one model accepted.
        mask = use_linear | use_exp

        # Build combined coefficient maps.
        ct_map_out = np.where(use_linear,
                              lin_result.ct_map.astype(np.float64),
                              np.nan).astype(np.float32)

        exp_a_out  = np.where(use_exp,
                              exp_result.exp_a_map.astype(np.float64),
                              np.nan).astype(np.float32)

        exp_b_out  = np.where(use_exp,
                              exp_result.exp_b_map.astype(np.float64),
                              np.nan).astype(np.float32)

        # Best R² and residual per pixel.
        r2_best       = np.where(use_linear, r2_lin, r2_exp).astype(np.float32)
        resid_lin     = lin_result.residual_map.astype(np.float64)
        resid_exp     = exp_result.residual_map.astype(np.float64)
        residual_best = np.where(use_linear, resid_lin, resid_exp).astype(np.float32)

        fit_type_map = np.where(use_exp, np.uint8(1), np.uint8(0)).astype(np.uint8)

        ts = time.time()
        pts   = sorted(self._points, key=lambda p: p.temperature)
        temps = np.array([p.temperature for p in pts], dtype=np.float64)
        t_ref = pts[0].temperature

        return CalibrationResult(
            ct_map        = ct_map_out,
            exp_a_map     = exp_a_out,
            exp_b_map     = exp_b_out,
            r2_map        = r2_best,
            residual_map  = residual_best,
            fit_type_map  = fit_type_map,
            mask          = mask,
            n_points      = len(pts),
            t_min         = float(temps.min()),
            t_max         = float(temps.max()),
            t_ref         = t_ref,
            frame_h       = H,
            frame_w       = W,
            timestamp     = ts,
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(ts)),
            valid         = True,
        )
