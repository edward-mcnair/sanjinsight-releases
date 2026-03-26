"""
ui/phase_tracker.py  —  Phase completion state manager

Tracks passive completion checks for each workflow phase and emits
badge updates for the sidebar phase headers.

Checks are passive observations — they never block or enforce.

Usage
-----
    tracker = PhaseTracker()
    tracker.mark(1, "camera_selected")
    tracker.phase_updated.connect(sidebar.set_phase_badge)
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class PhaseTracker(QObject):
    """Tracks completion state for the three workflow phases.

    Emits ``phase_updated(phase_number, badge_text)`` whenever a check
    changes state.  Badge text is ``"2/3"`` (partial) or ``"✓"`` (all done).
    """

    phase_updated = pyqtSignal(int, str)   # (phase_number, badge_text)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checks: dict[int, dict[str, bool]] = {
            1: {  # CONFIGURATION
                "camera_selected":      False,
                "profile_selected":     False,
                "stimulus_configured":  False,
                "temperature_set":      False,
            },
            2: {  # IMAGE ACQUISITION
                "live_viewed":    False,
                "focused":        False,
                "signal_checked": False,
            },
            3: {  # MEASUREMENT & ANALYSIS
                "captured":   False,
                "calibrated": False,
            },
        }

    # ── Public API ───────────────────────────────────────────────────

    def mark(self, phase: int, key: str, done: bool = True) -> None:
        """Mark a check as done (or undone) and emit badge update."""
        if phase not in self._checks:
            return
        checks = self._checks[phase]
        if key not in checks:
            return
        if checks[key] == done:
            return
        checks[key] = done
        self.phase_updated.emit(phase, self.badge_for(phase))

    def badge_for(self, phase: int) -> str:
        """Return badge text for a phase: '✓' if all done, else '2/3'."""
        checks = self._checks.get(phase, {})
        if not checks:
            return ""
        done = sum(1 for v in checks.values() if v)
        total = len(checks)
        if done == total:
            return "✓"
        return f"{done}/{total}"

    def reset(self) -> None:
        """Reset all checks to False and emit updates."""
        for phase, checks in self._checks.items():
            for key in checks:
                checks[key] = False
            self.phase_updated.emit(phase, self.badge_for(phase))

    def is_phase_complete(self, phase: int) -> bool:
        checks = self._checks.get(phase, {})
        return all(checks.values()) if checks else False
