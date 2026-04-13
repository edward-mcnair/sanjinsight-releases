"""
ui/workspace.py  —  Workspace mode shim (legacy)

The guided/standard/expert mode system has been replaced by the
Recipe execution model.  This file is kept as a compatibility shim
so existing widgets that call ``get_manager()`` or
``set_workspace_mode()`` do not crash.

All queries return "standard" mode behavior.  ``mode_changed`` is
never emitted.  ``set_mode()`` is a no-op.
"""
from __future__ import annotations

from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal


class WorkspaceMode(str, Enum):
    """Legacy workspace modes — only STANDARD is active."""
    GUIDED   = "guided"
    STANDARD = "standard"
    EXPERT   = "expert"


MODE_DESCRIPTORS: dict[str, str] = {
    "guided":   "(deprecated)",
    "standard": "Default mode",
    "expert":   "(deprecated)",
}


class WorkspaceManager(QObject):
    """Compatibility shim — always returns standard mode."""

    mode_changed = pyqtSignal(str)   # never emitted

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = WorkspaceMode.STANDARD

    @property
    def mode(self) -> WorkspaceMode:
        return WorkspaceMode.STANDARD

    def set_mode(self, mode: str) -> None:
        """No-op — mode switching is deprecated."""
        pass

    # Query helpers — all return standard-mode behavior
    def show_phase_headers(self) -> bool:  return True
    def show_guidance_text(self) -> bool:  return False
    def show_phase_badges(self) -> bool:   return True
    def more_options_default_expanded(self) -> bool: return False
    def collapse_inactive_phases(self) -> bool: return False
    def console_visible_default(self) -> bool: return False
    def console_verbosity(self) -> str:    return "standard"


_manager: WorkspaceManager | None = None


def get_manager() -> WorkspaceManager:
    """Return the singleton WorkspaceManager shim."""
    global _manager
    if _manager is None:
        _manager = WorkspaceManager()
    return _manager
