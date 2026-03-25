"""
acquisition/fps_optimizer.py

Auto-optimize acquisition throughput following the priority rules
defined by the measurement protocol:

  1. Maximize LED intensity — increase FPGA duty cycle (pulse width)
  2. Maximize frame rate   — set camera to its maximum FPS
  3. Adjust exposure       — tune camera exposure to hit a target
                             intensity (fraction of dynamic range)

The Boson IR camera has no FPS/exposure control and is skipped.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

log = logging.getLogger(__name__)


class FpsOptimizer:
    """Auto-optimize acquisition throughput following priority rules."""

    # Target intensity as a fraction of the sensor's dynamic range.
    # 0.70 = aim for ~70% of full scale (good SNR without saturation risk).
    DEFAULT_TARGET_INTENSITY = 0.70

    # Saturation guard — never exceed this fraction of full scale.
    SATURATION_LIMIT = 0.90

    # Exposure search: binary-search iterations and bounds (microseconds).
    MAX_ITERATIONS = 8
    EXP_MIN_US     = 50.0
    EXP_MAX_US     = 200_000.0

    def __init__(self, camera, fpga=None, target_intensity: float = 0.0):
        """
        camera : CameraDriver (must be open and streaming)
        fpga   : FpgaDriver | None
        target_intensity : 0.0 = use DEFAULT_TARGET_INTENSITY
        """
        self._cam   = camera
        self._fpga  = fpga
        self._target = target_intensity or self.DEFAULT_TARGET_INTENSITY

    def optimize(self) -> dict:
        """
        Run the three-step optimization and return a summary dict:

            {
                "duty_cycle":  float,  # final FPGA duty cycle (0-1)
                "fps":         float,  # camera max_fps after optimization
                "exposure_us": float,  # final camera exposure
                "mean_intensity": float,  # measured image mean (fraction of full scale)
                "skipped":     bool,   # True if camera type is IR (no optimization)
            }
        """
        info = self._cam.info
        result = {
            "duty_cycle": 0.0,
            "fps": info.max_fps,
            "exposure_us": self._cam.get_exposure(),
            "mean_intensity": 0.0,
            "skipped": False,
        }

        # IR cameras (e.g. Boson) have no user-controllable FPS or exposure.
        if info.camera_type == "ir":
            log.info("FpsOptimizer: IR camera — skipping optimization.")
            result["skipped"] = True
            result["reason"] = "IR cameras have no adjustable FPS/exposure"
            return result

        # Ensure camera is streaming so grab() returns frames.
        self._started_streaming = False
        if hasattr(self._cam, '_running') and not self._cam._running:
            try:
                self._cam.start()
                self._started_streaming = True
            except Exception as exc:
                log.warning("FpsOptimizer: could not start camera: %s", exc)

        # ── Step 1: Maximize LED duty cycle ────────────────────────────
        if self._fpga is not None:
            try:
                self._fpga.set_duty_cycle(1.0)
                result["duty_cycle"] = 1.0
                log.info("FpsOptimizer: FPGA duty cycle set to 1.0 "
                         "(maximum LED pulse width).")
            except Exception as exc:
                log.warning("FpsOptimizer: set_duty_cycle(1.0) failed: %s", exc)

        # ── Step 2: Maximize frame rate ────────────────────────────────
        max_fps = info.max_fps
        if max_fps > 0:
            try:
                self._cam.set_fps(max_fps)
                result["fps"] = max_fps
                log.info("FpsOptimizer: Camera FPS set to %.1f.", max_fps)
            except Exception as exc:
                log.warning("FpsOptimizer: set_fps(%.1f) failed: %s",
                            max_fps, exc)

        # ── Step 3: Auto-adjust exposure for target intensity ──────────
        result["exposure_us"] = self._auto_exposure()
        result["mean_intensity"] = self._measure_intensity()

        # Stop camera if we started it ourselves
        if self._started_streaming:
            try:
                self._cam.stop()
            except Exception:
                pass

        return result

    def _auto_exposure(self) -> float:
        """Binary-search exposure to hit target intensity."""
        lo, hi = self.EXP_MIN_US, self.EXP_MAX_US
        exp_range = self._cam.exposure_range()
        if exp_range:
            lo = max(lo, exp_range[0])
            hi = min(hi, exp_range[1])

        best_exp = self._cam.get_exposure()

        for i in range(self.MAX_ITERATIONS):
            mid = (lo + hi) / 2.0
            self._cam.set_exposure(mid)

            intensity = self._measure_intensity()
            log.debug("FpsOptimizer: iter %d  exp=%.0f μs  intensity=%.3f",
                      i, mid, intensity)

            if intensity > self.SATURATION_LIMIT:
                hi = mid  # too bright — reduce exposure
            elif intensity < self._target * 0.95:
                lo = mid  # too dim — increase exposure
            else:
                best_exp = mid
                break
            best_exp = mid

        self._cam.set_exposure(best_exp)
        log.info("FpsOptimizer: Final exposure = %.0f μs "
                 "(intensity = %.3f).", best_exp, self._measure_intensity())
        return best_exp

    def _measure_intensity(self) -> float:
        """Grab a frame and return mean intensity as fraction of full scale."""
        frame = self._cam.grab(timeout_ms=2000)
        if frame is None:
            return 0.0
        data = frame.data
        bit_depth = frame.bit_depth or self._cam.info.bit_depth or 12
        full_scale = float((1 << bit_depth) - 1)
        if full_scale <= 0:
            full_scale = 4095.0
        # For multi-channel data, use luminance (mean across channels)
        return float(np.mean(data)) / full_scale
