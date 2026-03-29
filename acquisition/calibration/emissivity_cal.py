"""
acquisition/emissivity_cal.py — Emissivity calibration for IR camera mode.

Emissivity calibration maps the IR camera's apparent temperature to true
surface temperature. Requires known-temperature reference surface.

Physical model
--------------
In the IR camera the detector integrates radiance from two sources:

    L_measured = ε × L_surface(T_true) + (1 - ε) × L_background

For the narrow temperature ranges used in semiconductor metrology
(roughly 20–200 °C) the Planck function is well-approximated by a
linear function of temperature, so the radiance model collapses to:

    T_measured = ε × T_true + (1 - ε) × T_background     [Kelvin]

which is equivalent in °C (the K offset cancels):

    T_meas_C = ε × T_true_C + (1 - ε) × T_bg_C

Rearranging to apply calibration (forward transform):

    T_true_C = (T_meas_C - (1 - ε) × T_bg_C) / ε

Usage
-----
    cal = EmissivityCalibration()
    cal.add_point(25.0, 23.1, "ambient")
    cal.add_point(80.0, 73.6, "hot plate")
    result = cal.fit()
    true_frame = result.apply(ir_frame_c)
    result.save("/path/to/emis_cal.json")
    result = EmissivityCalibration.load_result("/path/to/emis_cal.json")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import numpy as np


# ────────────────────────────────────────────────────────────────────────── #
#  Data types                                                                 #
# ────────────────────────────────────────────────────────────────────────────#


@dataclass
class EmissivityCalPoint:
    """One known-temperature reference point."""
    temp_true_c:    float        # Actual (thermocouple-verified) temperature °C
    temp_measured_c: float       # IR camera apparent temperature °C
    label:          str = ""     # Human-readable label (e.g. "ambient", "hot plate")


@dataclass
class EmissivityCalResult:
    """
    Fitted emissivity calibration.

    Fields
    ------
    emissivity    : ε in [0, 1] — surface emissivity
    t_background_c: T_bg in °C — effective background/environment temperature
    r_squared     : goodness-of-fit (0–1; >0.99 is excellent for 2+ points)
    n_points      : number of calibration points used in the fit
    residuals     : list of per-point residuals (T_pred - T_meas) in °C
    timestamp     : ISO-8601 string at fit time
    """
    emissivity:      float
    t_background_c:  float
    r_squared:       float
    n_points:        int
    residuals:       List[float]
    timestamp:       str

    # ── Apply calibration ────────────────────────────────────────────────── #

    def apply(self, ir_frame_c: np.ndarray) -> np.ndarray:
        """
        Convert an apparent-temperature IR frame to true surface temperature.

        ir_frame_c : float32/float64 array of apparent temperatures in °C
        Returns     : float32 array of corrected true temperatures in °C

        Formula:
            T_true = (T_meas - (1 - ε) × T_bg) / ε
        """
        if self.emissivity <= 0.0:
            raise ValueError(
                f"Emissivity is {self.emissivity:.4f} — cannot divide by zero. "
                "Refit calibration with valid reference points.")

        frame = np.asarray(ir_frame_c, dtype=np.float64)
        t_bg  = self.t_background_c
        eps   = self.emissivity
        true  = (frame - (1.0 - eps) * t_bg) / eps
        return true.astype(np.float32)

    # ── Serialisation ────────────────────────────────────────────────────── #

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "EmissivityCalResult":
        return EmissivityCalResult(
            emissivity     = float(d["emissivity"]),
            t_background_c = float(d["t_background_c"]),
            r_squared      = float(d["r_squared"]),
            n_points       = int(d["n_points"]),
            residuals      = [float(r) for r in d.get("residuals", [])],
            timestamp      = str(d.get("timestamp", "")),
        )

    def __repr__(self) -> str:
        return (f"<EmissivityCalResult ε={self.emissivity:.4f} "
                f"T_bg={self.t_background_c:.2f}°C "
                f"R²={self.r_squared:.4f} "
                f"n={self.n_points}>")


# ────────────────────────────────────────────────────────────────────────── #
#  Calibration builder                                                        #
# ────────────────────────────────────────────────────────────────────────────#


class EmissivityCalibration:
    """
    Accumulates known-temperature reference points and fits ε and T_background.

    The fit solves the linear model:

        T_meas_i = ε × T_true_i + (1 - ε) × T_bg

    by rewriting it as a two-parameter linear regression:

        T_meas_i = a × T_true_i + b

    where
        a = ε               (slope)
        b = (1 - ε) × T_bg  (intercept)

    Closed-form OLS is used (minimum 2 points required).
    For 2 points the fit is exact (R² = 1.0); for 3+ points R² reflects
    how well the linear model describes the data.
    """

    def __init__(self):
        self._points: List[EmissivityCalPoint] = []
        self._result: Optional[EmissivityCalResult] = None

    # ── Point management ─────────────────────────────────────────────────── #

    def add_point(self, temp_true_c: float,
                  temp_measured_c: float,
                  label: str = "") -> None:
        """Add one calibration reference point."""
        self._points.append(EmissivityCalPoint(
            temp_true_c     = float(temp_true_c),
            temp_measured_c = float(temp_measured_c),
            label           = label,
        ))
        self._result = None   # invalidate cached fit

    def remove_point(self, index: int) -> None:
        """Remove calibration point by list index."""
        del self._points[index]
        self._result = None

    def reset(self) -> None:
        """Remove all calibration points and clear any fitted result."""
        self._points.clear()
        self._result = None

    @property
    def n_points(self) -> int:
        return len(self._points)

    @property
    def points(self) -> List[EmissivityCalPoint]:
        return list(self._points)

    # ── Fit ──────────────────────────────────────────────────────────────── #

    def fit(self) -> EmissivityCalResult:
        """
        Fit emissivity and background temperature from accumulated points.

        Returns EmissivityCalResult.  Raises ValueError if fewer than 2
        points have been added, or if the true-temperature range is zero
        (duplicate temperatures).
        """
        if len(self._points) < 2:
            raise ValueError(
                "At least 2 calibration points are required to fit emissivity. "
                f"Currently have {len(self._points)}.")

        x = np.array([p.temp_true_c     for p in self._points], dtype=np.float64)
        y = np.array([p.temp_measured_c for p in self._points], dtype=np.float64)

        # ---- OLS: y = a*x + b ----
        # a = Σ((xi - x̄)(yi - ȳ)) / Σ((xi - x̄)²)
        # b = ȳ - a * x̄
        x_mean = x.mean()
        y_mean = y.mean()
        ss_xx  = np.sum((x - x_mean) ** 2)

        if ss_xx < 1e-12:
            raise ValueError(
                "All calibration points have the same true temperature — "
                "cannot fit a slope.  Add points at different temperatures.")

        ss_xy = np.sum((x - x_mean) * (y - y_mean))
        a     = ss_xy / ss_xx           # slope  = ε
        b     = y_mean - a * x_mean    # intercept = (1-ε) × T_bg

        # Clamp ε to a physically sensible range.
        # Values outside (0, 1] indicate bad calibration data.
        eps = float(np.clip(a, 1e-4, 1.0))

        # T_bg from intercept: b = (1 - ε) × T_bg  →  T_bg = b / (1 - ε)
        # Guard the (1-ε) ≈ 0 edge case (near-perfect emitter).
        denom = 1.0 - eps
        t_bg  = float(b / denom) if abs(denom) > 1e-6 else 0.0

        # ---- R² ----
        y_pred = a * x + b
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - y_mean) ** 2))
        r2     = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 1.0

        residuals = (y - y_pred).tolist()

        self._result = EmissivityCalResult(
            emissivity     = eps,
            t_background_c = t_bg,
            r_squared      = float(np.clip(r2, 0.0, 1.0)),
            n_points       = len(self._points),
            residuals      = residuals,
            timestamp      = time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime()),
        )
        return self._result

    @property
    def result(self) -> Optional[EmissivityCalResult]:
        """Return the most recently fitted result, or None if not yet fitted."""
        return self._result

    # ── Apply (convenience) ───────────────────────────────────────────────── #

    def apply(self, ir_frame: np.ndarray) -> np.ndarray:
        """
        Convert apparent-temperature IR frame → true temperature.
        Requires fit() to have been called first.
        """
        if self._result is None:
            raise RuntimeError(
                "No calibration has been fitted yet — call fit() first.")
        return self._result.apply(ir_frame)

    # ── Persistence ───────────────────────────────────────────────────────── #

    def save(self, path: str) -> str:
        """
        Save calibration points and the fitted result (if available) to JSON.

        path: full file path (.json extension added if absent)
        Returns: actual saved path.
        """
        if not path.endswith(".json"):
            path += ".json"

        payload = {
            "version":   1,
            "saved_at":  time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "points": [
                {
                    "temp_true_c":     p.temp_true_c,
                    "temp_measured_c": p.temp_measured_c,
                    "label":           p.label,
                }
                for p in self._points
            ],
            "result": self._result.to_dict() if self._result is not None else None,
        }

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        return path

    def load(self, path: str) -> Optional[EmissivityCalResult]:
        """
        Load calibration points and fitted result from a JSON file.

        Replaces the current points list and cached result.
        Returns the loaded EmissivityCalResult, or None if none was saved.
        """
        if not path.endswith(".json"):
            path += ".json"

        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        self._points = [
            EmissivityCalPoint(
                temp_true_c     = float(pt["temp_true_c"]),
                temp_measured_c = float(pt["temp_measured_c"]),
                label           = str(pt.get("label", "")),
            )
            for pt in payload.get("points", [])
        ]

        raw_result  = payload.get("result")
        self._result = (EmissivityCalResult.from_dict(raw_result)
                        if raw_result is not None else None)
        return self._result

    @staticmethod
    def load_result(path: str) -> Optional[EmissivityCalResult]:
        """
        Convenience static method: load just the fitted result from JSON,
        without reconstructing the full EmissivityCalibration object.

        Returns None if the file contains no fitted result.
        """
        if not path.endswith(".json"):
            path += ".json"

        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        raw = payload.get("result")
        return EmissivityCalResult.from_dict(raw) if raw is not None else None

    def __repr__(self) -> str:
        return (f"<EmissivityCalibration n_points={self.n_points} "
                f"fitted={self._result is not None}>")
