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
from ui.widgets.detach_helpers import DetachableFrame, open_detached_viewer

log = logging.getLogger(__name__)


# Module-level constants removed — use PALETTE directly.


# ── Live canvas ───────────────────────────────────────────────────────────────

class _LiveCanvas(QWidget):
    """Aspect-preserving live camera display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"background:{PALETTE['canvas']};")

    def update_frame(self, frame) -> None:
        """Accept a CameraFrame (frame.data uint16 H×W) and render it."""
        try:
            data = np.asarray(frame.data, dtype=np.uint16)
        except Exception:
            return

        # Fast approximate percentile stretch — O(n) vs O(n log n) for
        # np.percentile.  Subsample for speed on large frames.
        flat = data.ravel()
        if flat.size > 50_000:
            flat = flat[::flat.size // 50_000]
        flat_sorted = np.partition(flat, (len(flat) // 100, -len(flat) // 100))
        lo = float(flat_sorted[len(flat) // 100])
        hi = float(flat_sorted[-len(flat) // 100])
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
                .QColor(PALETTE['textSub']))
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

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Part ID row ────────────────────────────────────────────────────
        pid_row = QHBoxLayout()
        pid_row.setSpacing(8)

        self._pid_lbl = QLabel("Part ID / Serial:")
        self._pid_lbl.setFixedWidth(140)
        pid_row.addWidget(self._pid_lbl)

        self._pid_edit = QLineEdit()
        self._pid_edit.setPlaceholderText(
            "Enter or scan barcode — press Enter to start")
        self._pid_edit.setFixedHeight(36)
        pid_row.addWidget(self._pid_edit, 1)

        self._clear_btn = QPushButton("⟳")
        self._clear_btn.setToolTip("Clear part ID")
        self._clear_btn.setFixedSize(36, 36)
        pid_row.addWidget(self._clear_btn)
        root.addLayout(pid_row)

        # ── Live canvas ────────────────────────────────────────────────────
        self._canvas = _LiveCanvas()
        self._canvas_frame = DetachableFrame(self._canvas)
        self._canvas_frame.detach_requested.connect(self._on_detach_live)
        root.addWidget(self._canvas_frame, 1)

        # ── Recipe note (shown when no recipe selected) ────────────────────
        self._recipe_note = QLabel(
            "← Select a recipe to enable scanning")
        self._recipe_note.setAlignment(Qt.AlignCenter)
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
        root.addWidget(self._progress)

        # ── Wire signals ───────────────────────────────────────────────────
        self._scan_btn.clicked.connect(self._on_scan_btn)
        self._clear_btn.clicked.connect(self.clear_part_id)
        self._pid_edit.returnPressed.connect(self._on_enter_in_pid)
        self._pid_edit.textChanged.connect(self._update_scan_btn)

        self._apply_styles()

    # ── Detached viewer ──────────────────────────────────────────────────────────

    _detached_live = None

    def _on_detach_live(self) -> None:
        """Open a detached viewer for the operator live camera feed."""
        def _push(viewer):
            pix = self._canvas.grab()
            if pix is not None and not pix.isNull():
                viewer.update_image(pix, "Operator — Live Feed")

        open_detached_viewer(
            self, "_detached_live",
            source_id="operator.live",
            title="Operator — Live Feed",
            initial_push=_push)

    # ── Theming ─────────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Re-apply PALETTE-driven styles."""
        P = PALETTE
        self.setStyleSheet(f"background:{P['bg']};")
        self._pid_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; "
            f"color:{P['textDim']}; background:transparent;")
        self._pid_edit.setStyleSheet(
            f"QLineEdit {{ background:{P['surface']}; color:{P['text']}; "
            f"border:1px solid {P['border']}; border-radius:4px; "
            f"padding:4px 10px; font-size:{FONT.get('body', 11)}pt; }}"
            f"QLineEdit:focus {{ border-color:{P['accent']}; }}")
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background:{P['surface']}; color:{P['textDim']}; "
            f"border:1px solid {P['border']}; border-radius:4px; "
            f"font-size:{FONT['subhead']}pt; }}"
            f"QPushButton:hover {{ background:{P['border']}; color:{P['text']}; }}")
        self._recipe_note.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            f"color:{P['textSub']}; background:transparent;")
        self._progress.setStyleSheet(
            f"QProgressBar {{ background:{P['surface']}; border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{P['accent']}; border-radius:4px; }}")
        self._canvas._apply_styles()

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
            acc = PALETTE['accent']
            return (
                f"QPushButton {{ background:{acc}22; color:{acc}; "
                f"border:2px solid {acc}; border-radius:8px; "
                f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
                "letter-spacing:2px; }}"
                f"QPushButton:hover {{ background:{acc}44; }}"
                f"QPushButton:pressed {{ background:{acc}66; }}"
            )
        else:
            P = PALETTE
            return (
                f"QPushButton {{ background:{P['surface']}; color:{P['textSub']}; "
                f"border:2px solid {P['border']}; border-radius:8px; "
                f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
                "letter-spacing:2px; }"
            )

    @staticmethod
    def _abort_btn_qss() -> str:
        dng = PALETTE['danger']
        return (
            f"QPushButton {{ background:{dng}22; color:{dng}; "
            f"border:2px solid {dng}; border-radius:8px; "
            f"font-size:{FONT.get('h3', 13)}pt; font-weight:800; "
            "letter-spacing:2px; }}"
            f"QPushButton:hover {{ background:{dng}44; }}"
        )
