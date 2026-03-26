"""
ui/workspace.py  —  Workspace mode manager

Three workspace modes control presentation density, defaults, AI behavior,
and console verbosity across the entire application:

    Guided   — step-by-step workflow for production testing and new users
    Standard — balanced layout for investigation and daily use
    Expert   — full control for research and experiment design

Usage
-----
    from ui.workspace import get_manager, WorkspaceMode

    mgr = get_manager()
    mgr.mode_changed.connect(my_widget.on_mode_changed)

    if mgr.show_phase_headers():
        ...
"""
from __future__ import annotations

from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal

import config as cfg_mod


class WorkspaceMode(str, Enum):
    """Workspace presentation modes."""
    GUIDED   = "guided"
    STANDARD = "standard"
    EXPERT   = "expert"


# Descriptors shown in the UI next to mode names
MODE_DESCRIPTORS: dict[str, str] = {
    "guided":   "Step-by-step workflow for production testing and new users",
    "standard": "Balanced layout for investigation and daily use",
    "expert":   "Full control for research and experiment design",
}


class WorkspaceManager(QObject):
    """Singleton authority for workspace mode state.

    Emits ``mode_changed(str)`` whenever the mode is switched.
    Widgets connect to this signal or call the query helpers at paint time.
    """

    mode_changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        raw = cfg_mod.get_pref("ui.workspace", "standard")
        try:
            self._mode = WorkspaceMode(raw)
        except ValueError:
            self._mode = WorkspaceMode.STANDARD

    # ── Properties ───────────────────────────────────────────────────

    @property
    def mode(self) -> WorkspaceMode:
        return self._mode

    # ── Mutator ──────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Switch workspace mode, persist, and notify listeners."""
        try:
            new_mode = WorkspaceMode(mode)
        except ValueError:
            return
        if new_mode == self._mode:
            return
        self._mode = new_mode
        cfg_mod.set_pref("ui.workspace", mode)
        self.mode_changed.emit(mode)

    # ── Query helpers (widgets call these instead of checking mode) ──

    def show_phase_headers(self) -> bool:
        """Phase group headers visible in sidebar (hidden in Expert)."""
        return self._mode != WorkspaceMode.EXPERT

    def show_guidance_text(self) -> bool:
        """Contextual hints below phase headers (Guided only)."""
        return self._mode == WorkspaceMode.GUIDED

    def show_phase_badges(self) -> bool:
        """Phase completion badges (hidden in Expert)."""
        return self._mode in (WorkspaceMode.GUIDED, WorkspaceMode.STANDARD)

    def more_options_default_expanded(self) -> bool:
        """'More Options' panels start expanded (Expert only)."""
        return self._mode == WorkspaceMode.EXPERT

    def collapse_inactive_phases(self) -> bool:
        """Non-active phases start collapsed (Guided only)."""
        return self._mode == WorkspaceMode.GUIDED

    def console_visible_default(self) -> bool:
        """Bottom drawer visible on startup (Expert only)."""
        return self._mode == WorkspaceMode.EXPERT

    def console_verbosity(self) -> str:
        """Log verbosity level for the current mode."""
        return {
            WorkspaceMode.GUIDED:   "simplified",
            WorkspaceMode.STANDARD: "standard",
            WorkspaceMode.EXPERT:   "debug",
        }[self._mode]


# ── Module-level singleton ───────────────────────────────────────────

_manager: WorkspaceManager | None = None


def get_manager() -> WorkspaceManager:
    """Return the singleton WorkspaceManager, creating it on first call."""
    global _manager
    if _manager is None:
        _manager = WorkspaceManager()
    return _manager
