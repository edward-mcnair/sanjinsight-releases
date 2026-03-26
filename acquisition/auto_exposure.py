"""
acquisition/auto_exposure.py

Standalone auto-exposure utility using binary search to target a
desired fraction of the sensor's dynamic range.

Can be run synchronously (blocking) or from a background QThread.
Progress is reported via an optional callback.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class AutoExposureResult:
    """Outcome of an auto-exposure run."""
    final_exposure_us: float = 0.0
    mean_intensity:    float = 0.0   # fraction of full scale (0–1)
    converged:         bool  = False
    iterations:        int   = 0
    elapsed_s:         float = 0.0
    skipped:           bool  = False
    reason:            str   = ""


class AutoExposure:
    """Binary-search auto-exposure targeting a fraction of dynamic range.

    Usage::

        ae = AutoExposure(camera)
        result = ae.run()          # blocking
        print(result.final_exposure_us, result.converged)
    """

    TARGET_INTENSITY = 0.70    # aim for 70 % of full scale
    SATURATION_LIMIT = 0.90    # never exceed 90 %
    MAX_ITERATIONS   = 10
    TOLERANCE        = 0.05    # converged when within 5 % of target
    EXP_MIN_US       = 50.0
    EXP_MAX_US       = 200_000.0

    def __init__(self, camera, *,
                 target: float = 0.0,
                 settle_frames: int = 2):
        """
        Parameters
        ----------
        camera : CameraDriver
            Must be open and streaming.
        target : float
            Target intensity as fraction of full scale (0–1).
            0 = use ``TARGET_INTENSITY``.
        settle_frames : int
            Frames to discard after changing exposure (allows sensor
            to reach new brightness before measuring).
        """
        self._cam = camera
        self._target = target or self.TARGET_INTENSITY
        self._settle = max(1, settle_frames)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(self, progress_cb: Optional[Callable[[int, int, float], None]] = None
            ) -> AutoExposureResult:
        """Run the binary-search exposure optimisation.

        Parameters
        ----------
        progress_cb : callable(iteration, max_iterations, current_intensity)
            Optional callback for UI progress updates.

        Returns
        -------
        AutoExposureResult
        """
        t0 = time.monotonic()
        info = self._cam.info

        # IR cameras have no adjustable exposure
        if getattr(info, "camera_type", "tr") == "ir":
            return AutoExposureResult(
                skipped=True,
                reason="IR cameras have no adjustable exposure")

        lo, hi = self.EXP_MIN_US, self.EXP_MAX_US
        exp_range = self._cam.exposure_range()
        if exp_range:
            lo = max(lo, exp_range[0])
            hi = min(hi, exp_range[1])

        best_exp = self._cam.get_exposure()
        best_intensity = 0.0

        for i in range(self.MAX_ITERATIONS):
            mid = (lo + hi) / 2.0
            self._cam.set_exposure(mid)

            # Let sensor settle at new exposure
            for _ in range(self._settle):
                self._cam.grab(timeout_ms=2000)

            intensity = self._measure_intensity()

            log.debug("AutoExposure: iter %d  exp=%.0f µs  intensity=%.3f",
                      i, mid, intensity)

            if progress_cb is not None:
                try:
                    progress_cb(i + 1, self.MAX_ITERATIONS, intensity)
                except Exception:
                    pass

            if intensity > self.SATURATION_LIMIT:
                hi = mid
            elif intensity < self._target - self.TOLERANCE:
                lo = mid
            else:
                # Within tolerance — converged
                best_exp = mid
                best_intensity = intensity
                self._cam.set_exposure(best_exp)
                return AutoExposureResult(
                    final_exposure_us=best_exp,
                    mean_intensity=best_intensity,
                    converged=True,
                    iterations=i + 1,
                    elapsed_s=time.monotonic() - t0)

            best_exp = mid
            best_intensity = intensity

        # Exhausted iterations — use best guess
        self._cam.set_exposure(best_exp)
        log.info("AutoExposure: finished after %d iters — exp=%.0f µs, "
                 "intensity=%.3f (target=%.2f)",
                 self.MAX_ITERATIONS, best_exp, best_intensity, self._target)

        return AutoExposureResult(
            final_exposure_us=best_exp,
            mean_intensity=best_intensity,
            converged=False,
            iterations=self.MAX_ITERATIONS,
            elapsed_s=time.monotonic() - t0)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _measure_intensity(self) -> float:
        """Grab a frame and return mean intensity as fraction of full scale."""
        frame = self._cam.grab(timeout_ms=2000)
        if frame is None:
            return 0.0
        data = frame.data
        bit_depth = frame.bit_depth or getattr(self._cam.info, "bit_depth", 12)
        full_scale = float((1 << bit_depth) - 1) or 4095.0
        return float(np.mean(data)) / full_scale
