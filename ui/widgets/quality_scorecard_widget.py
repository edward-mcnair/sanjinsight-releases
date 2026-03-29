"""
ui/widgets/quality_scorecard_widget.py

Compact widget that displays a QualityScorecard as a row of graded metric
pills plus an overall grade badge.

Usage
-----
    widget = QualityScorecardWidget()
    widget.set_scorecard(scorecard)       # QualityScorecard instance
    widget.set_scorecard(None)            # clears / hides
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT
from acquisition.quality_scorecard import QualityScorecard, GRADE_COLORS


# ── Human-friendly metric labels ────────────────────────────────────────────

_METRIC_LABELS: dict[str, str] = {
    "snr":               "SNR",
    "exposure":          "Exposure",
    "thermal_contrast":  "Contrast",
    "stability":         "Stability",
}


class QualityScorecardWidget(QWidget):
    """Compact row of graded metric pills + overall badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(4)

        # ── Header: overall grade badge ───────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setFixedSize(36, 36)

        self._title = QLabel("Quality Scorecard")
        self._title.setAlignment(Qt.AlignVCenter)

        header.addWidget(self._badge)
        header.addWidget(self._title)
        header.addStretch()
        outer.addLayout(header)

        # ── Metric pills row ──────────────────────────────────────────
        self._pills_frame = QFrame()
        pills_lay = QHBoxLayout(self._pills_frame)
        pills_lay.setContentsMargins(0, 0, 0, 0)
        pills_lay.setSpacing(6)

        self._pill_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("snr", "exposure", "thermal_contrast", "stability"):
            name_lbl = QLabel(_METRIC_LABELS[key])
            name_lbl.setAlignment(Qt.AlignCenter)

            grade_lbl = QLabel("—")
            grade_lbl.setAlignment(Qt.AlignCenter)
            grade_lbl.setFixedSize(28, 28)

            pill = QFrame()
            pill_lay = QHBoxLayout(pill)
            pill_lay.setContentsMargins(8, 4, 8, 4)
            pill_lay.setSpacing(4)
            pill_lay.addWidget(name_lbl)
            pill_lay.addWidget(grade_lbl)

            self._pill_labels[key] = (name_lbl, grade_lbl)
            pills_lay.addWidget(pill)

        pills_lay.addStretch()
        outer.addWidget(self._pills_frame)

        # ── Recommendations ──────────────────────────────────────────
        self._recs_label = QLabel()
        self._recs_label.setWordWrap(True)
        self._recs_label.setVisible(False)
        outer.addWidget(self._recs_label)

        self._scorecard: QualityScorecard | None = None

    # ── Public API ─────────────────────────────────────────────────────

    def set_scorecard(self, sc: QualityScorecard | None) -> None:
        """Display (or clear) a scorecard."""
        self._scorecard = sc
        if sc is None:
            self.setVisible(False)
            return

        self.setVisible(True)
        self._apply_styles()

        # Overall badge
        color = PALETTE.get(sc.overall_color, PALETTE.get("textDim", "#888"))
        self._badge.setText(sc.overall_grade)
        self._badge.setStyleSheet(
            f"background: {color}; color: {PALETTE.get('bg', '#111')}; "
            f"border-radius: 18px; font-size: {FONT['heading']}pt; "
            f"font-weight: 800;")
        self._title.setText(
            f"Quality: {sc.overall_grade}"
            f"  —  {', '.join(r for r in sc.recommendations[:1])}"
            if sc.recommendations else f"Quality: {sc.overall_grade}")

        # Individual metric pills
        for mg in sc.grades_list:
            if mg.metric not in self._pill_labels:
                continue
            name_lbl, grade_lbl = self._pill_labels[mg.metric]
            gc = PALETTE.get(GRADE_COLORS.get(mg.grade, "textDim"),
                             PALETTE.get("textDim", "#888"))
            grade_lbl.setText(mg.grade)
            grade_lbl.setStyleSheet(
                f"background: {gc}; color: {PALETTE.get('bg', '#111')}; "
                f"border-radius: 14px; font-size: {FONT['label']}pt; "
                f"font-weight: 800;")
            grade_lbl.setToolTip(f"{mg.display}\n{mg.threshold}")
            name_lbl.setToolTip(f"{mg.display}\n{mg.threshold}")

        # Recommendations
        if sc.recommendations:
            self._recs_label.setText(
                "\n".join(f"• {r}" for r in sc.recommendations))
            self._recs_label.setVisible(True)
        else:
            self._recs_label.setVisible(False)

    # ── Theme support ──────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Reapply theme-dependent styles."""
        dim = PALETTE.get("textDim", "#888")
        text = PALETTE.get("text", "#eee")
        bg2 = PALETTE.get("bg2", "#1a1a1c")

        self._title.setStyleSheet(
            f"color: {text}; font-size: {FONT['label']}pt; font-weight: 600;")

        self._pills_frame.setStyleSheet(
            f"QFrame {{ background: {bg2}; border-radius: 6px; }}")

        for key, (name_lbl, _) in self._pill_labels.items():
            name_lbl.setStyleSheet(
                f"color: {dim}; font-size: {FONT['sublabel']}pt;")

        self._recs_label.setStyleSheet(
            f"color: {dim}; font-size: {FONT['sublabel']}pt; "
            f"padding: 2px 4px;")
