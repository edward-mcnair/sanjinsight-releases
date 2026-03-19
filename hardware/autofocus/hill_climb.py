"""
hardware/autofocus/hill_climb.py

Hill-climb autofocus — moves in the direction of improving focus,
accelerates when improving, backs off and narrows step when it overshoots.

Faster than sweep for samples already near focus.
Can get trapped in local maxima on complex samples — use sweep for those.

Config keys (under hardware.autofocus):
    strategy:       "hill_climb"
    metric:         "laplacian"
    initial_step:   20.0          μm — starting step size
    min_step:       0.5           μm — stop when step shrinks below this
    step_shrink:    0.5           factor to reduce step on direction reversal
    step_grow:      1.2           factor to grow step on continued improvement
    max_steps:      80            hard limit on total Z moves
    n_avg:          2             frames to average per position
    settle_ms:      50            ms to wait after each Z move
    move_to_best:   true
"""

import time
from .base import AutofocusDriver, AfResult, AfState


class HillClimbAutofocus(AutofocusDriver):

    def run(self) -> AfResult:
        self._abort = False
        self._state = AfState.RUNNING

        cfg          = self._cfg
        step         = float(cfg.get("initial_step",  20.0))
        min_step     = float(cfg.get("min_step",       0.5))
        step_shrink  = float(cfg.get("step_shrink",    0.5))
        step_grow    = float(cfg.get("step_grow",      1.2))
        max_steps    = int(  cfg.get("max_steps",       80))
        n_avg        = int(  cfg.get("n_avg",            2))
        settle_ms    = float(cfg.get("settle_ms",       50)) / 1000.0
        move_best    = cfg.get("move_to_best", True)

        result = AfResult(state=AfState.RUNNING)
        t0     = time.time()

        # Get starting position
        current_z = 0.0
        if self._stage:
            s = self._stage.get_status()
            current_z = s.position.z if not s.error else 0.0

        z         = current_z
        direction = 1.0

        def score_at(z_pos):
            if self._stage:
                self._stage.move_to(z=z_pos, wait=True)
                time.sleep(settle_ms)
            scores = []
            for _ in range(max(1, n_avg)):
                s = self._grab_score()
                if s is not None:
                    scores.append(s)
            return (sum(scores) / len(scores)) if scores else 0.0

        current_score = score_at(z)
        result.z_positions.append(z)
        result.scores.append(current_score)

        for _ in range(max_steps):
            if self._abort:
                result.state   = AfState.ABORTED
                result.message = "Aborted"
                break

            next_z     = z + direction * step
            next_score = score_at(next_z)

            result.z_positions.append(next_z)
            result.scores.append(next_score)

            if next_score > current_score:
                # Improving — accept move and maybe grow step
                z             = next_z
                current_score = next_score
                step          = min(step * step_grow, 200.0)
            else:
                # Getting worse — reverse direction, shrink step
                direction = -direction
                step      = step * step_shrink

            # Track best
            best_idx          = result.scores.index(max(result.scores))
            result.best_z     = result.z_positions[best_idx]
            result.best_score = result.scores[best_idx]
            result.message    = (
                f"Z={next_z:.1f}μm  score={next_score:.4f}  "
                f"step={step:.1f}μm  best={result.best_z:.1f}μm")
            self._emit(result)

            if step < min_step:
                break

        result.duration_s = time.time() - t0

        if result.state != AfState.ABORTED:
            from .metrics import estimate_best_z_subpixel
            result.best_z = estimate_best_z_subpixel(
                result.z_positions, result.scores)
            result.state  = AfState.COMPLETE

            if move_best and self._stage:
                self._stage.move_to(z=result.best_z, wait=True)
                result.message = (
                    f"Complete — best focus at Z={result.best_z:.2f}μm  "
                    f"score={result.best_score:.4f}  "
                    f"({result.duration_s:.1f}s)")

        self._state = result.state
        if self.on_complete:
            self.on_complete(result)

        return result
