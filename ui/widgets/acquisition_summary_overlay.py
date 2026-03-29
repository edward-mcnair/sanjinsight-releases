"""
ui/widgets/acquisition_summary_overlay.py

Post-acquisition summary overlay that appears briefly after capture completes.

Shows: overall quality grade, key metrics, duration, and recommendations
in a dismissible banner at the top of the acquisition area.

Usage
-----
    overlay = AcquisitionSummaryOverlay(parent_widget)
    overlay.show_summary(scorecard, duration_s=12.3, n_frames=256)
    # Auto-hides after 8 seconds, or user clicks ✕.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFrame, QGraphicsOpacityEffect, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont

from ui.theme import PALETTE, FONT
from acquisition.quality_scorecard import QualityScorecard, GRADE_COLORS


class AcquisitionSummaryOverlay(QFrame):
    """Dismissible post-acquisition summary banner."""

    AUTO_HIDE_MS = 8000   # auto-dismiss after 8 seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AcqSummaryOverlay")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(12)

        # ── Grade badge ───────────────────────────────────────────────
        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setFixedSize(48, 48)
        root.addWidget(self._badge)

        # ── Text area ────────────────────────────────────────────────
        text_area = QVBoxLayout()
        text_area.setSpacing(2)

        self._headline = QLabel()
        self._headline.setWordWrap(True)

        self._detail = QLabel()
        self._detail.setWordWrap(True)

        self._recs = QLabel()
        self._recs.setWordWrap(True)

        text_area.addWidget(self._headline)
        text_area.addWidget(self._detail)
        text_area.addWidget(self._recs)
        root.addLayout(text_area, 1)

        # ── Dismiss button ───────────────────────────────────────────
        dismiss = QPushButton("✕")
        dismiss.setFixedSize(24, 24)
        dismiss.setCursor(Qt.PointingHandCursor)
        dismiss.setToolTip("Dismiss")
        dismiss.clicked.connect(self._dismiss)
        root.addWidget(dismiss, 0, Qt.AlignTop)
        self._dismiss_btn = dismiss

        # ── Auto-hide timer ──────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)

        # ── Fade animation ───────────────────────────────────────────
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(1.0)

    # ── Public API ─────────────────────────────────────────────────────

    def show_summary(
        self,
        scorecard: QualityScorecard,
        duration_s: float = 0.0,
        n_frames: int = 0,
    ) -> None:
        """Display the overlay with the given scorecard."""
        self._apply_styles(scorecard)

        # Badge
        gc = PALETTE.get(scorecard.overall_color, PALETTE.get("textDim", "#888"))
        self._badge.setText(scorecard.overall_grade)
        self._badge.setStyleSheet(
            f"background: {gc}; color: {PALETTE.get('bg', '#111')}; "
            f"border-radius: 24px; "
            f"font-size: {FONT['title']}pt; font-weight: 800;")

        # Headline
        grade = scorecard.overall_grade
        if grade == "A":
            msg = "Excellent acquisition quality"
        elif grade == "B":
            msg = "Good acquisition quality"
        elif grade == "C":
            msg = "Acceptable acquisition quality"
        else:
            msg = "Acquisition quality needs attention"

        self._headline.setText(f"Grade {grade} — {msg}")

        # Detail line
        parts = []
        if n_frames:
            parts.append(f"{n_frames} frames")
        if duration_s > 0:
            if duration_s < 60:
                parts.append(f"{duration_s:.1f}s")
            else:
                m, s = divmod(int(duration_s), 60)
                parts.append(f"{m}m {s}s")
        for mg in scorecard.grades_list:
            if mg.grade != "N/A":
                parts.append(f"{mg.display}")
        self._detail.setText("  ·  ".join(parts))

        # Recommendations
        if scorecard.recommendations:
            self._recs.setText(
                " | ".join(scorecard.recommendations[:2]))
            self._recs.setVisible(True)
        else:
            self._recs.setVisible(False)

        # Show + auto-hide
        self._opacity.setOpacity(1.0)
        self.setVisible(True)
        self._timer.start(self.AUTO_HIDE_MS)

    # ── Theme support ──────────────────────────────────────────────────

    def _apply_styles(self, sc: QualityScorecard = None) -> None:
        """Reapply theme-dependent styles."""
        bg = PALETTE.get("bg2", "#1a1a1c")
        border = PALETTE.get("border", "#333")
        text = PALETTE.get("text", "#eee")
        dim = PALETTE.get("textDim", "#888")
        gc = PALETTE.get(sc.overall_color, dim) if sc is not None else border

        self.setStyleSheet(
            f"QFrame#AcqSummaryOverlay {{ "
            f"background: {bg}; "
            f"border: 1px solid {gc}; "
            f"border-radius: 8px; }}")

        self._headline.setStyleSheet(
            f"color: {text}; font-size: {FONT['body']}pt; font-weight: 700;")
        self._detail.setStyleSheet(
            f"color: {dim}; font-size: {FONT['sublabel']}pt;")
        self._recs.setStyleSheet(
            f"color: {dim}; font-size: {FONT['caption']}pt; "
            f"font-style: italic;")
        self._dismiss_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {dim}; "
            f"border: none; font-size: {FONT['body']}pt; }}"
            f"QPushButton:hover {{ color: {text}; }}")

    # ── Internal ───────────────────────────────────────────────────────

    def _dismiss(self) -> None:
        """Fade out and hide."""
        self._timer.stop()
        anim = QPropertyAnimation(self._opacity, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setVisible(False))
        anim.start()
        # prevent GC before animation finishes
        self._fade_anim = anim
