"""
hardware/autofocus/sweep.py

Two-pass sweep autofocus — the most reliable general-purpose strategy.

Pass 1 (coarse): sweep the full Z range in large steps → find rough peak
Pass 2 (fine):   sweep a tight window around the rough peak in small steps
                 → fit parabola for sub-step precision

Config keys (under hardware.autofocus):
    strategy:       "sweep"
    metric:         "laplacian"   laplacian | tenengrad | normalized | fft | brenner
    z_start:        -500.0        μm from current Z position
    z_end:          500.0         μm from current Z position
    coarse_step:    50.0          μm — first pass step size
    fine_step:      5.0           μm — second pass step size
    fine_range:     100.0         μm — window around coarse peak for fine pass
    n_avg:          2             frames to average at each Z step
    settle_ms:      50            ms to wait after each Z move
    move_to_best:   true          move to best Z when done
"""

import time
from .base import AutofocusDriver, AfResult, AfState


class SweepAutofocus(AutofocusDriver):

    def run(self) -> AfResult:
        self._abort  = False
        self._state  = AfState.RUNNING

        cfg         = self._cfg
        n_avg       = cfg.get("n_avg",       2)
        coarse_step = cfg.get("coarse_step", 50.0)
        fine_step   = cfg.get("fine_step",   5.0)
        fine_range  = cfg.get("fine_range",  100.0)
        move_best   = cfg.get("move_to_best", True)

        # Range relative to current Z position
        current_z = 0.0
        if self._stage:
            s = self._stage.get_status()
            current_z = s.position.z if not s.error else 0.0

        z_start = current_z + cfg.get("z_start", -500.0)
        z_end   = current_z + cfg.get("z_end",    500.0)

        # ---- Pass 1: Coarse sweep ----
        result = self._sweep(z_start, z_end, coarse_step, n_avg)
        if result.state in (AfState.ABORTED, AfState.FAILED):
            self._state = result.state
            return result

        coarse_best = result.best_z

        # ---- Pass 2: Fine sweep around coarse peak ----
        fine_start = coarse_best - fine_range / 2
        fine_end   = coarse_best + fine_range / 2

        fine_result = self._sweep(fine_start, fine_end, fine_step, n_avg)

        if fine_result.z_positions:
            # Merge data
            result.z_positions += fine_result.z_positions
            result.scores      += fine_result.scores
            result.best_z       = fine_result.best_z
            result.best_score   = fine_result.best_score
            result.duration_s  += fine_result.duration_s

        # ---- Move to best focus ----
        if move_best and self._stage and not self._abort:
            self._stage.move_to(z=result.best_z, wait=True)
            result.message = (
                f"Complete — best focus at Z={result.best_z:.2f}μm  "
                f"score={result.best_score:.4f}  "
                f"({result.duration_s:.1f}s)")

        result.state = AfState.ABORTED if self._abort else AfState.COMPLETE
        self._state  = result.state

        if self.on_complete:
            self.on_complete(result)

        return result
