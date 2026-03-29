"""
ui/guidance/overlay.py  —  Tier 2: Spotlight overlay walkthrough engine

NOT YET IMPLEMENTED.  This module defines the public interface that
section widgets and the tutorial system will use to highlight UI
elements with spotlight cutouts, arrows, and step-by-step narration.

When implemented, the overlay will:
  - Accept a list of OverlayStep targets (widget + text)
  - Render a semi-transparent mask over the entire window
  - Cut out a rounded-rect spotlight around the target widget
  - Draw an arrow and tooltip near the spotlight
  - Advance through steps on click / keyboard
  - Be replayable from a "Tutorial" menu item

The GuidanceCard.target_widget field is the bridge: any card that
specifies a target_widget is overlay-ready.
"""
from __future__ import annotations

import logging
from typing import NamedTuple, Optional

from PyQt5.QtWidgets import QWidget

log = logging.getLogger(__name__)


class OverlayStep(NamedTuple):
    """One step in a spotlight walkthrough."""
    target: QWidget       # widget to highlight
    title: str            # step heading
    body: str             # explanatory text
    arrow_side: str = "right"   # "left", "right", "top", "bottom"


class OverlayEngine:
    """Spotlight overlay walkthrough engine.

    Tier 2 stub — interface only, no rendering yet.
    """

    def __init__(self, parent_window: QWidget) -> None:
        self._parent = parent_window
        self._steps: list[OverlayStep] = []
        self._current = 0
        self._active = False

    def set_steps(self, steps: list[OverlayStep]) -> None:
        """Load a sequence of overlay steps."""
        self._steps = list(steps)
        self._current = 0

    def start(self) -> None:
        """Begin the walkthrough from step 0."""
        if not self._steps:
            log.warning("OverlayEngine.start() called with no steps")
            return
        self._active = True
        self._current = 0
        log.info("Overlay walkthrough started (%d steps)", len(self._steps))
        # TODO: create overlay widget, render first spotlight

    def advance(self) -> None:
        """Move to the next step, or finish if at the end."""
        if not self._active:
            return
        self._current += 1
        if self._current >= len(self._steps):
            self.stop()
            return
        # TODO: animate spotlight to next target

    def stop(self) -> None:
        """End the walkthrough and remove the overlay."""
        self._active = False
        self._current = 0
        log.info("Overlay walkthrough stopped")
        # TODO: remove overlay widget

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def current_step(self) -> Optional[OverlayStep]:
        if self._active and 0 <= self._current < len(self._steps):
            return self._steps[self._current]
        return None
