"""
ui/widgets/guided_banner.py  —  Guided-mode walkthrough banner

Shows contextual next-step hints at the top of the content area when
the workspace is in Guided mode.  Hidden in Standard/Expert.

The banner observes PhaseTracker state and suggests what the user
should do next.  Clicking the suggestion navigates to the relevant
section.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from ui.theme import FONT, PALETTE
from ui.icons import IC, set_btn_icon


# ── Step definitions ──────────────────────────────────────────────────
# Each tuple: (phase, check_key, label_text, nav_target, icon)
# The first incomplete step is shown as the suggestion.

_STEPS = [
    (1, "camera_selected",     "Connect a camera",
     "Modality", IC.CAMERA),
    (1, "stimulus_configured", "Configure the stimulus source",
     "Stimulus", IC.SETTINGS),
    (1, "temperature_set",     "Set the TEC temperature",
     "Temperature", IC.TEMPERATURE),
    (2, "live_viewed",         "Start the live view",
     "Live View", IC.LIVE),
    (2, "focused",             "Focus and position the stage",
     "Focus & Stage", IC.AUTOFOCUS),
    (2, "signal_checked",      "Check the signal quality",
     "Signal Check", IC.CHECK),
    (3, "captured",            "Run an acquisition",
     "Capture", IC.PLAY),
    (3, "calibrated",          "Calibrate the measurement",
     "Calibration", IC.CHART_LINE),
]


class GuidedBanner(QWidget):
    """Horizontal banner suggesting the next workflow step.

    Signals
    -------
    navigate_requested(str)
        Emitted with the sidebar label to navigate to when the user
        clicks the suggestion action button.
    """

    navigate_requested = pyqtSignal(str)   # sidebar nav label

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        self._icon = QLabel()
        self._icon.setFixedSize(20, 20)
        lay.addWidget(self._icon)

        self._label = QLabel()
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self._label, 1)

        self._action_btn = QPushButton("Go →")
        self._action_btn.setFixedHeight(26)
        self._action_btn.setCursor(Qt.PointingHandCursor)
        self._action_btn.clicked.connect(self._on_go)
        lay.addWidget(self._action_btn)

        self._dismiss_btn = QPushButton("✕")
        self._dismiss_btn.setFixedSize(26, 26)
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.setToolTip("Dismiss this hint")
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        lay.addWidget(self._dismiss_btn)

        self._current_nav: str = ""
        self._dismissed = False
        self._apply_styles()
        self.setVisible(False)

    # ── Public API ────────────────────────────────────────────────────

    def update_from_tracker(self, tracker) -> None:
        """Re-evaluate which step to suggest based on tracker state."""
        if self._dismissed:
            return

        for phase, key, text, nav, icon_name in _STEPS:
            checks = tracker._checks.get(phase, {})
            if not checks.get(key, False):
                self._current_nav = nav
                self._label.setText(f"Next step: {text}")
                set_btn_icon(self._icon, icon_name, size=16)
                self.setVisible(True)
                return

        # All steps complete
        self._label.setText("All steps complete — ready for analysis!")
        self._current_nav = "Sessions"
        self._icon.clear()
        self.setVisible(True)

    def set_guided_visible(self, guided: bool) -> None:
        """Show/hide based on workspace mode."""
        if not guided:
            self.setVisible(False)
            self._dismissed = False  # reset for next time
        elif not self._dismissed:
            self.setVisible(True)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        accent = PALETTE.get("accent", "#00d4aa")
        bg = PALETTE.get("accentDim", "#00d4aa1a")
        text = PALETTE.get("text", "#ebebeb")
        border = PALETTE.get("accent", "#00d4aa")
        surface = PALETTE.get("surface", "#2d2d2d")

        self.setStyleSheet(
            f"GuidedBanner {{ background:{bg}; "
            f"border:1px solid {border}44; border-radius:6px; }}")
        self._label.setStyleSheet(
            f"color:{text}; font-size:{FONT['body']}pt; background:transparent;")
        self._action_btn.setStyleSheet(
            f"QPushButton {{ background:{accent}; color:#000; "
            f"border-radius:4px; font-size:{FONT['sublabel']}pt; "
            f"font-weight:bold; padding:0 12px; border:none; }}"
            f"QPushButton:hover {{ background:{accent}cc; }}")
        self._dismiss_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{text}; "
            f"border:none; font-size:{FONT['body']}pt; }}"
            f"QPushButton:hover {{ background:{surface}; border-radius:4px; }}")

    # ── Private ───────────────────────────────────────────────────────

    def _on_go(self) -> None:
        if self._current_nav:
            self.navigate_requested.emit(self._current_nav)

    def _on_dismiss(self) -> None:
        self._dismissed = True
        self.setVisible(False)
