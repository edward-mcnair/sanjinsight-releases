"""
ui/widgets/batch_progress_widget.py

A compact, non-modal progress indicator for batch operations
(batch reports, batch reprocessing, batch analysis).

Intended to live in the status bar or bottom drawer so the user
can continue working while a batch runs in the background.
"""

from __future__ import annotations

import logging
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PyQt5.QtCore import Qt
from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)


class BatchProgressWidget(QWidget):
    """Compact inline progress bar for background batch operations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = 0
        self._done = 0
        self._worker = None
        self._build()
        self.hide()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        self._label = QLabel("Batch:")
        self._label.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt;")
        lay.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(16)
        self._bar.setTextVisible(True)
        lay.addWidget(self._bar, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
        lay.addWidget(self._status)

        self._abort_btn = QPushButton("Cancel")
        self._abort_btn.setFixedHeight(22)
        self._abort_btn.clicked.connect(self._on_abort)
        lay.addWidget(self._abort_btn)

    # ── Public API ────────────────────────────────────────────────────

    def start(self, label: str, total: int, worker=None):
        """Show the widget and begin tracking a batch of *total* items."""
        self._total = total
        self._done = 0
        self._worker = worker
        self._label.setText(f"{label}:")
        self._bar.setRange(0, total)
        self._bar.setValue(0)
        self._status.setText(f"0 / {total}")
        self._abort_btn.setEnabled(True)
        self.show()

    def on_progress(self, update):
        """Slot for batch worker ``progress`` signals."""
        self._done += 1
        self._bar.setValue(self._done)
        label = getattr(update, "label", "")
        ok = getattr(update, "success", True)
        icon = "\u2713" if ok else "\u2717"
        self._status.setText(f"{self._done}/{self._total}  {icon} {label}")

    def on_finished(self, result=None):
        """Slot for batch worker ``finished`` signals."""
        ok = getattr(result, "ok", self._done)
        failed = getattr(result, "failed", 0)
        dur = getattr(result, "duration_s", 0)
        self._status.setText(
            f"Done: {ok} ok, {failed} failed ({dur:.1f}s)")
        self._abort_btn.setEnabled(False)
        self._worker = None

    def reset(self):
        """Hide and reset state."""
        self.hide()
        self._worker = None
        self._total = 0
        self._done = 0

    # ── Internal ──────────────────────────────────────────────────────

    def _on_abort(self):
        if self._worker is not None and hasattr(self._worker, "abort"):
            self._worker.abort()
            self._status.setText("Cancelling…")
            self._abort_btn.setEnabled(False)

    def _apply_styles(self):
        """Re-apply theme colours (called by MainWindow on theme switch)."""
        self._label.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt;")
        self._status.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
