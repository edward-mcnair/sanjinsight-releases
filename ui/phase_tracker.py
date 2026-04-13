"""
ui/phase_tracker.py  —  PhaseTracker compatibility shim

The guided-mode phase tracking system has been replaced by the
Recipe execution model.  This stub prevents import errors from
existing code that references PhaseTracker.

All methods are no-ops.  The phase_updated signal is defined but
never emitted.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class PhaseTracker(QObject):
    """Compatibility shim — all methods are no-ops."""

    phase_updated = pyqtSignal(int, str)   # never emitted

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks: dict = {}

    def mark(self, phase: int, key: str, value: bool = True) -> None:
        """No-op — phase tracking is deprecated."""
        pass

    def badge_for(self, phase: int) -> str:
        return ""

    def reset(self) -> None:
        pass

    def is_phase_complete(self, phase: int) -> bool:
        return False
