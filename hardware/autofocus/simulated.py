"""
hardware/autofocus/simulated.py

Simulated autofocus for development without hardware.
Generates a synthetic Gaussian focus curve centered at a known Z position
so the sweep and hill-climb strategies run and produce realistic results.
"""

import time
import math
import random
from .base  import AutofocusDriver, AfResult, AfState
from .sweep import SweepAutofocus


class SimulatedAutofocus(AutofocusDriver):
    """
    Wraps SweepAutofocus but overrides _grab_score() to return
    a synthetic score based on distance from a simulated best-focus Z.
    """

    def __init__(self, camera, stage, cfg: dict):
        super().__init__(camera, stage, cfg)
        # Simulated best-focus position — randomised slightly each run
        self._true_best_z   = cfg.get("true_best_z", 1250.0)
        self._focus_width   = cfg.get("focus_width",  200.0)  # σ in μm
        self._peak_score    = cfg.get("peak_score",    1.0)
        self._noise_level   = cfg.get("noise_level",   0.02)

    def _grab_score(self):
        """Return synthetic focus score based on current stage Z."""
        if self._stage is None:
            return random.gauss(0.5, self._noise_level)

        status = self._stage.get_status()
        z      = status.position.z if not status.error else 0.0

        # Gaussian focus curve
        dist  = z - self._true_best_z
        score = (self._peak_score *
                 math.exp(-0.5 * (dist / self._focus_width) ** 2))
        score += random.gauss(0, self._noise_level)
        return max(0.0, score)

    def run(self) -> AfResult:
        # Delegate to SweepAutofocus with our synthetic _grab_score
        self._abort = False
        self._state = AfState.RUNNING

        # Temporarily inject self into a SweepAutofocus instance
        sweeper = SweepAutofocus(self._cam, self._stage, self._cfg)
        sweeper._grab_score  = self._grab_score
        sweeper.on_progress  = self.on_progress
        sweeper.on_complete  = self.on_complete

        result = sweeper.run()
        self._state = result.state
        return result
