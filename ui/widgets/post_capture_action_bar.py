"""
ui/widgets/post_capture_action_bar.py

Post-capture action bar — capability-driven next-step buttons shown after
any acquisition completes.

Unlike the AcquisitionSummaryOverlay (quality-grade banner, 8-second auto-dismiss),
this bar is a persistent, non-modal strip that shows *only* the actions available
for the current result type.  It remains visible until the user acts or dismisses.

Usage
-----
    bar = PostCaptureActionBar(parent)

    # Show after single-point capture (saved to Sessions, analysable)
    bar.show_actions(
        can_view_sessions=True,
        can_open_analysis=True,
        can_export=True,
        result_label="Single-point capture complete",
    )

    # Show after transient capture (NOT saved, exportable, no analysis)
    bar.show_actions(
        can_view_sessions=False,
        can_open_analysis=False,
        can_export=True,
        result_label="Transient acquisition complete — 24 delay steps",
    )

Signals
-------
    view_sessions_clicked   — user wants to navigate to Sessions tab
    open_analysis_clicked   — user wants to navigate to Analysis tab
    export_clicked          — user wants to export current result
    dismissed               — user clicked Dismiss
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QGraphicsOpacityEffect,
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal

from ui.theme import PALETTE, FONT


class PostCaptureActionBar(QFrame):
    """Persistent post-capture action strip with capability-driven buttons."""

    view_sessions_clicked = pyqtSignal()
    open_analysis_clicked = pyqtSignal()
    export_clicked        = pyqtSignal()
    dismissed             = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PostCaptureActionBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setVisible(False)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 6)
        root.setSpacing(10)

        # ── Result label ─────────────────────────────────────────────
        self._label = QLabel()
        self._label.setWordWrap(True)
        root.addWidget(self._label, 1)

        # ── Action buttons (created once, toggled per-show) ──────────
        self._sessions_btn = self._make_btn("View in Sessions", "sessions")
        self._analysis_btn = self._make_btn("Open in Analysis", "analysis")
        self._export_btn   = self._make_btn("Export", "export")

        self._sessions_btn.clicked.connect(self.view_sessions_clicked.emit)
        self._analysis_btn.clicked.connect(self.open_analysis_clicked.emit)
        self._export_btn.clicked.connect(self.export_clicked.emit)

        root.addWidget(self._sessions_btn)
        root.addWidget(self._analysis_btn)
        root.addWidget(self._export_btn)

        # ── Dismiss ──────────────────────────────────────────────────
        dismiss = QPushButton("✕")
        dismiss.setFixedSize(24, 24)
        dismiss.setCursor(Qt.PointingHandCursor)
        dismiss.setToolTip("Dismiss")
        dismiss.setObjectName("PostCaptureActionBarDismiss")
        dismiss.clicked.connect(self._dismiss)
        root.addWidget(dismiss, 0, Qt.AlignVCenter)
        self._dismiss_btn = dismiss

        # ── Fade effect ──────────────────────────────────────────────
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self._apply_styles()

    # ── Public API ───────────────────────────────────────────────────

    def show_actions(
        self,
        *,
        can_view_sessions: bool = False,
        can_open_analysis: bool = False,
        can_export: bool = False,
        result_label: str = "Acquisition complete",
    ) -> None:
        """Show the action bar with only the buttons that apply.

        Parameters
        ----------
        can_view_sessions : bool
            True if the result was auto-saved to Sessions.
        can_open_analysis : bool
            True if the result can be pushed to the Analysis tab.
        can_export : bool
            True if the result can be exported (npz, npy, video, etc.).
        result_label : str
            Human-readable description shown at left.
        """
        self._label.setText(result_label)
        self._sessions_btn.setVisible(can_view_sessions)
        self._analysis_btn.setVisible(can_open_analysis)
        self._export_btn.setVisible(can_export)

        self._opacity.setOpacity(1.0)
        self.setVisible(True)

    def hide_bar(self) -> None:
        """Programmatic hide (e.g. when a new acquisition starts)."""
        self.setVisible(False)

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self):
        bg = PALETTE["surface2"]
        border = PALETTE["border"]
        text = PALETTE["text"]
        accent = PALETTE["accent"]
        dim = PALETTE["textDim"]

        self.setStyleSheet(
            f"QFrame#PostCaptureActionBar {{"
            f"  background: {bg}; border: 1px solid {border};"
            f"  border-radius: 6px;"
            f"}}"
            f"QLabel {{"
            f"  color: {text}; font-size: {FONT['body']}pt;"
            f"  background: transparent; border: none;"
            f"}}"
            f"QPushButton#PostCaptureActionBarDismiss {{"
            f"  background: transparent; border: none;"
            f"  color: {dim}; font-size: 12pt;"
            f"}}"
            f"QPushButton#PostCaptureActionBarDismiss:hover {{"
            f"  color: {text};"
            f"}}"
        )
        # Action buttons get accent styling
        for btn in (self._sessions_btn, self._analysis_btn, self._export_btn):
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {accent}; color: #ffffff;"
                f"  border: none; border-radius: 4px;"
                f"  padding: 4px 12px; font-size: {FONT['body']}pt;"
                f"  font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background: {PALETTE.get('accentHover', accent)};"
                f"}}"
            )

    # ── Internal ─────────────────────────────────────────────────────

    @staticmethod
    def _make_btn(label: str, name: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName(f"pcab_{name}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(28)
        btn.setVisible(False)
        return btn

    def _dismiss(self):
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setVisible(False))
        anim.finished.connect(self.dismissed.emit)
        anim.start()
        self._anim = anim  # prevent GC
