"""
ui/widgets/orchestrator_dialog.py

Modal progress dialog for the "Optimize & Acquire" preparation sequence.

Shows a vertical list of step cards, each with a status icon, label, and
progress message.  The dialog auto-closes on success or prompts the user
on failure.
"""

from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QSizePolicy,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)


# ── Step status icons ─────────────────────────────────────────────────────────

_ICONS = {
    "pending":  "○",
    "running":  "◉",
    "complete": "✓",
    "skipped":  "—",
    "failed":   "✗",
}


class OrchestratorDialog(QDialog):
    """Modal dialog showing multi-step preparation progress.

    Parameters
    ----------
    orchestrator : ReadinessOrchestrator
        The orchestrator to monitor.
    parent : QWidget, optional
    """

    def __init__(self, orchestrator, parent=None):
        super().__init__(parent)
        self._orch = orchestrator
        self.setWindowTitle("Optimize & Acquire")
        self.setMinimumWidth(480)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 16, 20, 16)

        # ── Header ────────────────────────────────────────────────────
        header = QLabel("Preparing instrument…")
        header.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; font-weight: 700; "
            f"color: {PALETTE['text']};")
        root.addWidget(header)
        self._header = header

        # ── Step cards ────────────────────────────────────────────────
        self._step_cards: dict[str, dict] = {}

        from hardware.readiness_orchestrator import _STEP_LABELS
        for step in orchestrator._steps:
            card = self._build_step_card(step.value, _STEP_LABELS.get(step, step.value))
            root.addWidget(card["frame"])
            self._step_cards[step.value] = card

        # ── Overall progress ──────────────────────────────────────────
        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, len(orchestrator._steps))
        self._overall_bar.setValue(0)
        self._overall_bar.setFixedHeight(6)
        self._overall_bar.setTextVisible(False)
        self._overall_bar.setStyleSheet(
            f"QProgressBar {{ background: {PALETTE['surface']}; "
            f"border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {PALETTE['accent']}; "
            f"border-radius: 3px; }}")
        root.addWidget(self._overall_bar)

        # ── Button row ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['border']};")
        root.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._skip_btn = QPushButton("Skip Step")
        self._skip_btn.setEnabled(False)
        self._skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(self._skip_btn)

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.clicked.connect(self._on_abort)
        btn_row.addWidget(self._abort_btn)

        root.addLayout(btn_row)

        self._completed_count = 0

        # ── Connect orchestrator signals ──────────────────────────────
        orchestrator.progress.connect(self._on_progress)
        orchestrator.step_complete.connect(self._on_step_complete)
        orchestrator.complete.connect(self._on_complete)

    def _build_step_card(self, step_id: str, label: str) -> dict:
        """Build a single step status card."""
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        icon = QLabel(_ICONS["pending"])
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; "
            f"color: {PALETTE['textDim']};")
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)

        name = QLabel(label)
        name.setStyleSheet(
            f"font-size: {FONT['label']}pt; font-weight: 600; "
            f"color: {PALETTE['text']};")
        col.addWidget(name)

        msg = QLabel("Pending")
        msg.setStyleSheet(
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['textDim']};")
        msg.setWordWrap(True)
        col.addWidget(msg)

        lay.addLayout(col, 1)

        return {"frame": frame, "icon": icon, "name": name, "msg": msg,
                "step_id": step_id, "status": "pending"}

    def _on_progress(self, sp) -> None:
        """Handle step progress updates."""
        step_id = sp.current_step.value
        card = self._step_cards.get(step_id)
        if not card:
            return

        card["status"] = "running"
        card["icon"].setText(_ICONS["running"])
        card["icon"].setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; "
            f"color: {PALETTE['accent']};")
        card["msg"].setText(sp.message)

        self._skip_btn.setEnabled(sp.can_skip)
        self._header.setText(f"Running: {sp.step_label}…")

    def _on_step_complete(self, step_name: str, success: bool) -> None:
        """Handle step completion."""
        card = self._step_cards.get(step_name)
        if not card:
            return

        self._completed_count += 1
        self._overall_bar.setValue(self._completed_count)

        if success:
            card["status"] = "complete"
            card["icon"].setText(_ICONS["complete"])
            card["icon"].setStyleSheet(
                f"font-size: {FONT['readoutSm']}pt; "
                f"color: {PALETTE['success']};")
        else:
            card["status"] = "failed"
            card["icon"].setText(_ICONS["failed"])
            card["icon"].setStyleSheet(
                f"font-size: {FONT['readoutSm']}pt; "
                f"color: {PALETTE['danger']};")

    def _on_complete(self, result) -> None:
        """Handle sequence completion."""
        self._skip_btn.setEnabled(False)
        self._abort_btn.setText("Close")
        self._abort_btn.clicked.disconnect()
        self._abort_btn.clicked.connect(
            lambda: self.accept() if result.success else self.reject())

        if result.success:
            self._header.setText("Preparation complete")
            self._header.setStyleSheet(
                f"font-size: {FONT['readoutSm']}pt; font-weight: 700; "
                f"color: {PALETTE['success']};")
            # Auto-close after short delay on full success
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(800, self.accept)
        else:
            self._header.setText(result.message or "Preparation incomplete")
            self._header.setStyleSheet(
                f"font-size: {FONT['readoutSm']}pt; font-weight: 700; "
                f"color: {PALETTE['warning']};")

            # Add "Proceed Anyway" button
            proceed_btn = QPushButton("Proceed Anyway")
            proceed_btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid {PALETTE['warning']}; "
                f"color: {PALETTE['warning']}; padding: 6px 16px; "
                f"border-radius: 4px; }}")
            proceed_btn.clicked.connect(self.accept)
            self.layout().addWidget(proceed_btn, alignment=Qt.AlignRight)

    def _on_skip(self) -> None:
        self._orch.skip_current_step()

    def _on_abort(self) -> None:
        self._orch.abort()
        self.reject()
