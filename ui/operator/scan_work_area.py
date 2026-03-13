"""
ui/operator/scan_work_area.py

ScanWorkArea — the central panel of the Operator Shell.

Contains:
  • Part ID / serial number entry (Enter auto-starts scan when recipe selected)
  • Aspect-ratio–preserving live camera preview
  • START SCAN button (56 px tall, green / accent)
  • Progress bar (hidden until scan is active)

Signals
-------
  scan_requested(recipe, part_id: str)
      Emitted when the operator presses START SCAN or hits Enter in the
      Part ID field.  Payload includes the currently selected Recipe
      and the entered part ID.

  scan_aborted()
      Emitted if the operator presses the ABORT button while a scan is
      running.

Public API
----------
  set_recipe(recipe | None)
      Called by OperatorShell when the recipe selection changes.

  set_scanning(scanning: bool, label: str = "")
      OperatorShell calls this to toggle the in-progress state.

  set_progress(value: int, total: int)
      Update the progress bar (0–total).

  on_live_frame(frame)
      Feed a raw CameraFrame (frame.data: uint16 H×W numpy) for display.
      Converts to uint8 grayscale via percentile stretch and renders into
      the live canvas.

  clear_part_id()
      Clear the part ID field after a scan completes.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QFrame, QSizePolicy,
)
from PyQt5.QtGui import QImage, QPixmap, QPainter

from ui.theme import FONT, PALETTE

log = logging.getLogger(__name__)

_BG        = "#0b0e1a"
_SURF      = "#0f1120"
_CANVAS_BG = "#080a12"


# ── Live canvas ───────────────────────────────────────────────────────────────

class _LiveCanvas(QWidget):
    """Aspect-preserving live camera display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{_CANVAS_BG};")

    def update_frame(self, frame) -> None:
        """Accept a CameraFrame (frame.data uint16 H×W) and render it."""
        try:
            data = np.asarray(frame.data, dtype=np.uint16)
        except Exception:
            return

        # Percentile stretch to uint8 for display
        lo = float(np.percentile(data, 1))
        hi = float(np.percentile(data, 99))
        if hi <= lo:
            hi = lo + 1.0
        scaled = np.clip((data.astype(np.float32) - lo) / (hi - lo), 0, 1)
        gray   = (scaled * 255).astype(np.uint8)
        rgb    = np.stack([gray, gray, gray], axis=-1)

        h, w = rgb.shape[:2]
        buf  = rgb.tobytes()
        qi   = QImage(buf, w, h, w * 3, QImage.Format_RGB888)
        # keep a copy so buf stays alive for the duration of the QImage
        qi   = qi.copy()
        self._pixmap = QPixmap.fromImage(qi)
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self._pixmap is None:
            p.setPen(
                __import__("PyQt5.QtGui", fromlist=["QColor"])
                .QColor(PALETTE.get("textSub", "#6a6a6a")))
            p.drawText(self.rect(), Qt.AlignCenter, "No signal")
            return

        # Aspect-ratio–preserving scale
        cw, ch = self.width(), self.height()
        pm = self._pixmap.scaled(cw, ch, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ox = (cw - pm.width())  // 2
        oy = (ch - pm.height()) // 2
        p.drawPixmap(ox, oy, pm)


# ── ScanWorkArea ──────────────────────────────────────────────────────────────

class ScanWorkArea(QWidget):
    """
    Central operator workspace: live view + part ID + scan controls.

    Parameters
    ----------
    parent : QWidget, optional
    """

    scan_requested = pyqtSignal(object, str)   # (Recipe, part_id)
    scan_aborted   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recipe    = None
        self._scanning  = False

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Part ID row ────────────────────────────────────────────────────
        pid_row = QHBoxLayout()
        pid_row.setSpacing(8)

        pid_lbl = QLabel("Part ID / Serial:")
        pid_lbl.setFixedWidth(140)
        pid_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; "
            f"color:{PALETTE.get('textDim','#999')}; background:transparent;")
        pid_row.addWidget(pid_lbl)

        self._pid_edit = QLineEdit()
        self._pid_edit.setPlaceholderText(
            "Enter or scan barcode — press Enter to start")
        self._pid_edit.setFixedHeight(36)
        self._pid_edit.setStyleSheet(
            f"QLineEdit {{ background:#13172a; color:{PALETTE.get('text','#ebebeb')}; "
            f"border:1px solid #2a3249; border-radius:4px; "
            f"padding:4px 10px; font-size:{FONT.get('body', 11)}pt; }}"
            f"QLineEdit:focus {{ border-color:{PALETTE.get('accent','#00d4aa')}; }}")
        pid_row.addWidget(self._pid_edit, 1)

        self._clear_btn = QPushButton("⟳")
        self._clear_btn.setToolTip("Clear part ID")
        self._clear_btn.setFixedSize(36, 36)
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background:#1a1e30; color:#777; "
            f"border:1px solid #2a3249; border-radius:4px; "
            f"font-size:14pt; }}"
            "QPushButton:hover { background:#2a3249; color:#ccc; }")
        pid_row.addWidget(self._clear_btn)
        root.addLayout(pid_row)

        # ── Live canvas ────────────────────────────────────────────────────
        self._canvas = _LiveCanvas()
        root.addWidget(self._canvas, 1)

        # ── Recipe note (shown when no recipe selected) ────────────────────
        self._recipe_note = QLabel(
            "← Select a recipe to enable scanning")
        self._recipe_note.setAlignment(Qt.AlignCenter)
        self._recipe_note.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            f"color:{PALETTE.get('textSub','#6a6a6a')}; background:transparent;")
        root.addWidget(self._recipe_note)

        # ── START SCAN button ──────────────────────────────────────────────
        self._scan_btn = QPushButton("▶  START SCAN")
        self._scan_btn.setFixedHeight(56)
        self._scan_btn.setEnabled(False)
        self._scan_btn.setStyleSheet(self._scan_btn_qss(enabled=False))
        root.addWidget(self._scan_btn)

        # ── Progress bar ───────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background:#1a1e30; border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{PALETTE.get('accent','#00d4aa')}; "
            "border-radius:4px; }}")
        root.addWidget(self._progress)

        # ── Wire signals ───────────────────────────────────────────────────
        self._scan_btn.clicked.connect(self._on_scan_btn)
        self._clear_btn.clicked.connect(self.clear_part_id)
        self._pid_edit.returnPressed.connect(self._on_enter_in_pid)
        self._pid_edit.textChanged.connect(self._update_scan_btn)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_recipe(self, recipe) -> None:
        """Called when the recipe selection changes (None = no recipe)."""
        self._recipe = recipe
        self._recipe_note.setVisible(recipe is None)
        self._update_scan_btn()

    def set_scanning(self, scanning: bool, label: str = "") -> None:
        """OperatorShell calls this to toggle the in-progress state."""
        self._scanning = scanning
        self._pid_edit.setEnabled(not scanning)
        self._clear_btn.setEnabled(not scanning)
        self._progress.setVisible(scanning)
        if scanning:
            self._scan_btn.setText("■  ABORT SCAN")
            self._scan_btn.setEnabled(True)
            self._scan_btn.setStyleSheet(self._abort_btn_qss())
            if label:
                self._scan_btn.setText(f"■  {label}")
        else:
            self._progress.setValue(0)
            self._scan_btn.setText("▶  START SCAN")
            self._scan_btn.setStyleSheet(
                self._scan_btn_qss(enabled=self._can_scan()))
            self._update_scan_btn()

    def set_progress(self, value: int, total: int) -> None:
        """Update the progress bar."""
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(value)

    def on_live_frame(self, frame) -> None:
        """Feed a raw CameraFrame for display in the live canvas."""
        self._canvas.update_frame(frame)

    def clear_part_id(self) -> None:
        """Clear the part ID field."""
        self._pid_edit.clear()
        self._pid_edit.setFocus()

    # ── Private helpers ────────────────────────────────────────────────────────

    def _can_scan(self) -> bool:
        return (
            self._recipe is not None
            and bool(self._pid_edit.text().strip())
        )

    def _update_scan_btn(self) -> None:
        if self._scanning:
            return
        can = self._can_scan()
        self._scan_btn.setEnabled(can)
        self._scan_btn.setStyleSheet(self._scan_btn_qss(enabled=can))

    def _on_enter_in_pid(self) -> None:
        """Enter key in the part ID field — auto-start if ready."""
        if self._scanning:
            return
        if self._can_scan():
            self._start_scan()
        elif self._recipe is None:
            # Helpful hint
            pass  # recipe note is already visible

    def _on_scan_btn(self) -> None:
        if self._scanning:
            self.scan_aborted.emit()
        else:
            self._start_scan()

    def _start_scan(self) -> None:
        part_id = self._pid_edit.text().strip()
        if not part_id or self._recipe is None:
            return
        self.scan_requested.emit(self._recipe, part_id)

    # ── Stylesheets ────────────────────────────────────────────────────────────

    @staticmethod
    def _scan_btn_qss(enabled: bool) -> str:
        if enabled:
            acc = PALETTE.get("accent", "#00d4aa")
            return (
                f"QPushButton {{ background:{acc}22; color:{acc}; "
                f"border:2px solid {acc}; border-radius:8px; "
                f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
                "letter-spacing:2px; }}"
                f"QPushButton:hover {{ background:{acc}44; }}"
                f"QPushButton:pressed {{ background:{acc}66; }}"
            )
        else:
            return (
                "QPushButton { background:#151825; color:#333344; "
                "border:2px solid #1e2235; border-radius:8px; "
                f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
                "letter-spacing:2px; }"
            )

    @staticmethod
    def _abort_btn_qss() -> str:
        dng = PALETTE.get("danger", "#ff4466")
        return (
            f"QPushButton {{ background:{dng}22; color:{dng}; "
            f"border:2px solid {dng}; border-radius:8px; "
            f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
            "letter-spacing:2px; }}"
            f"QPushButton:hover {{ background:{dng}44; }}"
        )
