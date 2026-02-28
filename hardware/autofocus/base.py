"""
hardware/autofocus/base.py

Abstract base class for autofocus routines.

Autofocus uses the camera to score image sharpness at multiple Z
positions, then moves the stage to the sharpest position found.

Two strategies are available:
    sweep     — scan a Z range in fixed steps, find the peak (reliable)
    hill_climb — move toward improving focus (faster, can get trapped)

Both strategies are implemented here as concrete methods so subclasses
only need to provide _grab_score() — the one-liner that gets a frame
and returns its focus score.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, List
from enum import Enum, auto
import time

import logging
log = logging.getLogger(__name__)


class AfState(Enum):
    IDLE      = auto()
    RUNNING   = auto()
    COMPLETE  = auto()
    FAILED    = auto()
    ABORTED   = auto()


@dataclass
class AfResult:
    """Result of one autofocus run."""
    state:          AfState = AfState.IDLE
    best_z:         float   = 0.0      # μm — Z position of best focus
    best_score:     float   = 0.0      # focus score at best_z
    z_positions:    list    = field(default_factory=list)
    scores:         list    = field(default_factory=list)
    duration_s:     float   = 0.0
    message:        str     = ""


class AutofocusDriver(ABC):
    """
    Abstract autofocus driver.

    Lifecycle:
        af = SomeAutofocus(camera, stage, config_dict)
        af.on_progress = my_callback    # optional, called each Z step
        result = af.run()               # blocks until complete
        log.info(f"Best focus at Z={result.best_z:.2f} μm")
    """

    def __init__(self, camera, stage, cfg: dict):
        self._cam     = camera
        self._stage   = stage
        self._cfg     = cfg
        self._abort   = False
        self._state   = AfState.IDLE

        # Callbacks
        self.on_progress: Optional[Callable[[AfResult], None]] = None
        self.on_complete: Optional[Callable[[AfResult], None]] = None

    @property
    def state(self) -> AfState:
        return self._state

    def abort(self):
        self._abort = True

    @abstractmethod
    def run(self) -> AfResult:
        """Run autofocus and return AfResult. Blocks until done."""

    # ---------------------------------------------------------------- #
    #  Shared helpers available to all subclasses                      #
    # ---------------------------------------------------------------- #

    def _grab_score(self) -> Optional[float]:
        """Grab one frame and return its focus score."""
        if self._cam is None:
            return None
        frame = self._cam.grab(timeout_ms=2000)
        if frame is None:
            return None
        from .metrics import score
        metric = self._cfg.get("metric", "laplacian")
        return score(frame.data, metric)

    def _emit(self, result: AfResult):
        if self.on_progress:
            try:
                self.on_progress(result)
            except Exception:
                pass

    def _sweep(self,
               z_start: float,
               z_end:   float,
               z_step:  float,
               n_avg:   int = 1) -> AfResult:
        """
        Sweep Z from z_start to z_end in z_step increments.
        Scores each position, returns AfResult with all data.
        """
        from .metrics import find_peak

        result = AfResult(state=AfState.RUNNING)
        t0     = time.time()

        z = z_start
        direction = 1 if z_end >= z_start else -1
        steps = []
        while direction * (z - z_end) <= 0:
            steps.append(z)
            z += direction * abs(z_step)

        for z_pos in steps:
            if self._abort:
                result.state   = AfState.ABORTED
                result.message = "Aborted"
                return result

            if self._stage:
                self._stage.move_to(z=z_pos, wait=True)
                time.sleep(self._cfg.get("settle_ms", 50) / 1000.0)

            # Average multiple frames for stability
            scores = []
            for _ in range(max(1, n_avg)):
                s = self._grab_score()
                if s is not None:
                    scores.append(s)
            if not scores:
                continue

            avg_score = sum(scores) / len(scores)
            result.z_positions.append(z_pos)
            result.scores.append(avg_score)

            result.best_score = max(result.scores)
            result.best_z     = result.z_positions[
                result.scores.index(result.best_score)]
            result.message    = (
                f"Z={z_pos:.1f}μm  score={avg_score:.4f}  "
                f"best={result.best_z:.1f}μm")
            self._emit(result)

        result.duration_s = time.time() - t0

        if result.z_positions:
            # Fit parabola for sub-step precision
            result.best_z = find_peak(result.z_positions, result.scores)
            result.state  = AfState.COMPLETE
        else:
            result.state   = AfState.FAILED
            result.message = "No frames captured during sweep"

        return result
