"""
hardware/cameras/auto_exposure.py

Histogram-based auto-exposure algorithm.

Given a camera and a target histogram peak position (as % of dynamic
range), iteratively adjusts exposure time using binary search until the
image brightness converges within tolerance.

Usage
-----
    from hardware.cameras.auto_exposure import auto_expose

    result = auto_expose(
        hw_service,
        target_pct=70.0,   # 70% of dynamic range
        roi="center50",    # "full" | "center50" | "center25"
        max_iters=6,
    )
    # result.exposure_us   — final exposure
    # result.actual_pct    — achieved histogram peak %
    # result.converged     — True if within tolerance
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class AutoExposeResult:
    """Result of an auto-exposure run."""
    exposure_us: float       # final exposure setting
    actual_pct: float        # achieved peak position (% of dynamic range)
    converged: bool          # True if within tolerance
    iterations: int          # number of adjustments made
    message: str             # human-readable summary


def _extract_roi(frame_data: np.ndarray, roi: str) -> np.ndarray:
    """Extract a region of interest from a frame."""
    h, w = frame_data.shape[:2]
    if roi == "center25":
        y0, y1 = h // 4 + h // 8, h // 4 + h // 8 + h // 4
        x0, x1 = w // 4 + w // 8, w // 4 + w // 8 + w // 4
    elif roi == "center50":
        y0, y1 = h // 4, h // 4 + h // 2
        x0, x1 = w // 4, w // 4 + w // 2
    else:  # full
        return frame_data
    return frame_data[y0:y1, x0:x1]


def _measure_brightness(frame_data: np.ndarray, bit_depth: int = 12) -> float:
    """Measure histogram peak position as % of dynamic range.

    Uses the 95th percentile to avoid being misled by saturated pixels
    or hot pixels.  Returns a value in [0, 100].
    """
    roi = frame_data.ravel()
    if roi.size == 0:
        return 0.0
    p95 = float(np.percentile(roi, 95))
    max_val = (1 << bit_depth) - 1  # e.g. 4095 for 12-bit
    return 100.0 * p95 / max_val


def auto_expose(
    hw_service,
    target_pct: float = 70.0,
    roi: str = "center50",
    max_iters: int = 6,
    tolerance_pct: float = 5.0,
    min_exposure_us: float = 100.0,
    max_exposure_us: float = 200_000.0,
    settle_ms: float = 150.0,
) -> AutoExposeResult:
    """Run histogram-based auto-exposure.

    Parameters
    ----------
    hw_service : HardwareService
        Hardware service (provides cam_set_exposure, grab helpers).
    target_pct : float
        Target brightness as % of dynamic range (0–100).
    roi : str
        ROI for brightness measurement: "full", "center50", "center25".
    max_iters : int
        Maximum binary search iterations.
    tolerance_pct : float
        Converge when |actual - target| < tolerance_pct.
    min_exposure_us, max_exposure_us : float
        Exposure search bounds.
    settle_ms : float
        Wait time after changing exposure before measuring.

    Returns
    -------
    AutoExposeResult
    """
    from hardware.app_state import app_state

    cam = app_state.cam
    if cam is None:
        return AutoExposeResult(
            exposure_us=5000.0, actual_pct=0.0, converged=False,
            iterations=0, message="No camera connected")

    bit_depth = getattr(getattr(cam, "info", None), "bit_depth", 12)

    # Current exposure as starting point
    current_us = getattr(cam, "_exposure_us",
                         getattr(getattr(cam, "info", None),
                                 "exposure_us", 5000.0))

    lo = min_exposure_us
    hi = max_exposure_us
    best_us = current_us
    best_pct = 0.0

    for i in range(max_iters):
        # Set exposure
        try:
            hw_service.cam_set_exposure(current_us)
        except Exception as e:
            log.warning("Auto-expose: set exposure failed: %s", e)
            break

        # Wait for sensor to settle
        time.sleep(settle_ms / 1000.0)

        # Grab a frame
        try:
            frame = cam.grab()
            if frame is None:
                log.warning("Auto-expose: grab returned None")
                break
            data = frame.data
            if data.ndim == 3:
                data = data[:, :, 0]  # use first channel
        except Exception as e:
            log.warning("Auto-expose: grab failed: %s", e)
            break

        # Measure brightness in ROI
        roi_data = _extract_roi(data, roi)
        actual = _measure_brightness(roi_data, bit_depth)
        best_us = current_us
        best_pct = actual

        log.debug("Auto-expose iter %d: exp=%.0f µs, brightness=%.1f%% "
                  "(target=%.1f%%)", i + 1, current_us, actual, target_pct)

        # Check convergence
        if abs(actual - target_pct) <= tolerance_pct:
            return AutoExposeResult(
                exposure_us=current_us, actual_pct=actual, converged=True,
                iterations=i + 1,
                message=f"Auto-exposure: {current_us:.0f} µs "
                        f"({actual:.0f}% brightness)")

        # Binary search adjustment
        if actual < target_pct:
            # Too dark — increase exposure
            lo = current_us
            current_us = (current_us + hi) / 2
        else:
            # Too bright — decrease exposure
            hi = current_us
            current_us = (lo + current_us) / 2

        # Clamp
        current_us = max(min_exposure_us, min(max_exposure_us, current_us))

    # Didn't converge — use best result
    return AutoExposeResult(
        exposure_us=best_us, actual_pct=best_pct, converged=False,
        iterations=max_iters,
        message=f"Auto-exposure: {best_us:.0f} µs "
                f"({best_pct:.0f}% — target was {target_pct:.0f}%)")
