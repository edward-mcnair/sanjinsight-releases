"""
ui/widgets/guided_banner.py  —  Guided-mode walkthrough banner

Shows contextual next-step hints at the top of the content area when
the workspace is in Guided mode.  Hidden in Standard/Expert.

The banner observes PhaseTracker state and suggests what the user
should do next.  Clicking the suggestion navigates to the relevant
section.  When a step completes, the banner briefly shows a checkmark
before auto-advancing to the next step.
"""
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from ui.theme import FONT, PALETTE
from ui.icons import IC, _FA5_TO_MDI, _safe_icon

log = logging.getLogger(__name__)


# ── Step definitions ──────────────────────────────────────────────────
# Each tuple: (phase, check_key, label_text, nav_target, icon)
# The first incomplete step is shown as the suggestion.

_STEPS = [
    (1, "camera_selected",     "Review your imaging modality",
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


def _icon_pixmap(icon_name: str, size: int = 16, color: str | None = None):
    """Return a QPixmap for the given MDI icon name, or None."""
    icon_name = _FA5_TO_MDI.get(icon_name, icon_name)
    icon_name = _safe_icon(icon_name)
    if color is None:
        color = PALETTE.get("textDim", "#8892aa")
    try:
        import qtawesome as qta
        return qta.icon(icon_name, color=color).pixmap(QSize(size, size))
    except Exception:
        return None


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
        self._icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon)

        self._label = QLabel()
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self._label, 1)

        self._progress_lbl = QLabel()
        self._progress_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._progress_lbl)

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
        self._current_step_idx: int = -1
        self._dismissed = False
        self._celebrating = False
        self._apply_styles()
        self.setVisible(False)

    # ── Public API ────────────────────────────────────────────────────

    def update_from_tracker(self, tracker) -> None:
        """Re-evaluate which step to suggest based on tracker state."""
        if self._dismissed:
            return

        # Count completed steps
        completed = 0
        first_incomplete_idx = -1
        for idx, (phase, key, text, nav, icon_name) in enumerate(_STEPS):
            checks = tracker._checks.get(phase, {})
            if checks.get(key, False):
                completed += 1
            elif first_incomplete_idx < 0:
                first_incomplete_idx = idx

        total = len(_STEPS)

        # If a step just completed, show brief celebration
        if (self._current_step_idx >= 0
                and first_incomplete_idx != self._current_step_idx
                and not self._celebrating):
            self._show_step_complete(completed, total, first_incomplete_idx)
            return

        if first_incomplete_idx >= 0:
            _phase, _key, text, nav, icon_name = _STEPS[first_incomplete_idx]
            self._current_nav = nav
            self._current_step_idx = first_incomplete_idx
            self._label.setText(f"Next step: {text}")
            self._set_icon(icon_name)
            self._progress_lbl.setText(f"{completed}/{total}")
            self._action_btn.setVisible(True)
            self.setVisible(True)
        else:
            # All steps complete
            self._label.setText("All steps complete — ready for analysis!")
            self._current_nav = "Sessions"
            self._current_step_idx = total
            self._set_icon(IC.CHECK, color=PALETTE.get("success", "#30d158"))
            self._progress_lbl.setText(f"{total}/{total}")
            self._action_btn.setText("View →")
            self._action_btn.setVisible(True)
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
        dim = PALETTE.get("textDim", "#8892aa")

        self.setStyleSheet(
            f"GuidedBanner {{ background:{bg}; "
            f"border:1px solid {border}44; border-radius:6px; }}")
        self._label.setStyleSheet(
            f"color:{text}; font-size:{FONT['body']}pt; background:transparent;")
        self._progress_lbl.setStyleSheet(
            f"color:{dim}; font-size:{FONT['caption']}pt; background:transparent;")
        self._action_btn.setStyleSheet(
            f"QPushButton {{ background:{accent}; color:#000; "
            f"border-radius:4px; font-size:{FONT['sublabel']}pt; "
            f"font-weight:bold; padding:0 12px; border:none; }}"
            f"QPushButton:hover {{ background:{accent}; color:#000; "
            f"border:1px solid #fff4; }}")
        self._dismiss_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{text}; "
            f"border:none; font-size:{FONT['body']}pt; }}"
            f"QPushButton:hover {{ background:{surface}; border-radius:4px; }}")

    # ── Private ───────────────────────────────────────────────────────

    def _set_icon(self, icon_name: str, color: str | None = None) -> None:
        """Set icon pixmap on the QLabel (not QPushButton.setIcon)."""
        pix = _icon_pixmap(icon_name, size=16, color=color)
        if pix is not None:
            self._icon.setPixmap(pix)
        else:
            self._icon.clear()

    def _show_step_complete(self, completed: int, total: int,
                            next_idx: int) -> None:
        """Briefly show a checkmark before advancing to the next step."""
        self._celebrating = True
        self._set_icon(IC.CHECK, color=PALETTE.get("success", "#30d158"))
        self._label.setText("Step complete!")
        self._action_btn.setVisible(False)
        self._progress_lbl.setText(f"{completed}/{total}")

        def _advance():
            self._celebrating = False
            if next_idx >= 0 and next_idx < len(_STEPS):
                _phase, _key, text, nav, icon_name = _STEPS[next_idx]
                self._current_nav = nav
                self._current_step_idx = next_idx
                self._label.setText(f"Next step: {text}")
                self._set_icon(icon_name)
                self._action_btn.setText("Go →")
                self._action_btn.setVisible(True)
                # Auto-navigate to the next step
                self.navigate_requested.emit(nav)
            else:
                self._label.setText("All steps complete — ready for analysis!")
                self._current_nav = "Sessions"
                self._current_step_idx = len(_STEPS)
                self._set_icon(IC.CHECK, color=PALETTE.get("success", "#30d158"))
                self._action_btn.setText("View →")
                self._action_btn.setVisible(True)

        QTimer.singleShot(1200, _advance)

    def _on_go(self) -> None:
        log.info("GuidedBanner: Go → clicked, navigating to %r",
                 self._current_nav)
        if self._current_nav:
            self.navigate_requested.emit(self._current_nav)

    def _on_dismiss(self) -> None:
        self._dismissed = True
        self.setVisible(False)
