"""
ui/widgets/detached_viewer.py  —  Detachable image viewer window (v4)

A top-level window that displays a synced copy of the current image from
a source screen (Capture live feed, Movie frame, Transient frame, etc.).

Features (v1 — base):
  - Freely resizable, movable to second monitor
  - Full-screen toggle (F11 or double-click)
  - Push-based sync: source calls update_image() to push new pixmaps
  - Compact info strip at bottom (optional context text)

Features (v3 — light interaction):
  - Colormap selector (local override or synced from source)
  - ROI overlay toggle
  - Cursor readout — pixel coords + data value at mouse position

Features (v4 — app-wide consistency):
  - ``source_id`` tag for geometry persistence + session restore
  - Geometry saved to config prefs on close / move / resize
  - Geometry restored on open if a previous position exists
  - Static mode (snapshot badge, "← Source" cmap hidden)
  - ``update_context()`` for info-bar updates without a new image

Design: display-focused tool.  No acquisition controls, no editing.

Usage:
    viewer = DetachedViewer("Live Feed", source_id="capture.live")
    viewer.show()
    # Source pushes updates (with optional raw data for cursor readout):
    viewer.update_image(pixmap, "Basler acA1920 · 1920×1080 · Live",
                        data=frame_array, rois=[(x0,y0,x1,y1)],
                        cmap="Thermal Delta")
    viewer.closed.connect(on_viewer_closed)
"""
from __future__ import annotations

from typing import Optional, List, Tuple

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint, QEvent
from PyQt5.QtGui import (
    QPixmap, QPainter, QColor, QKeyEvent, QMouseEvent,
    QPen, QImage,
)

from ui.theme import PALETTE, FONT, MONO_FONT


# ── Canvas ───────────────────────────────────────────────────────────

class _ViewerCanvas(QWidget):
    """Paint-based image display with aspect-ratio preservation,
    ROI overlays, and cursor tracking."""

    double_clicked = pyqtSignal()
    cursor_value   = pyqtSignal(int, int, str)  # x, y, formatted value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._data: np.ndarray | None = None
        self._rois: list = []
        self._show_rois: bool = True
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)

    def set_pixmap(self, pix: QPixmap) -> None:
        self._pixmap = pix
        self.update()

    def set_data(self, data: np.ndarray | None) -> None:
        self._data = data

    def set_rois(self, rois: list) -> None:
        self._rois = rois or []
        self.update()

    def set_show_rois(self, show: bool) -> None:
        self._show_rois = show
        self.update()

    # ── geometry helpers ──────────────────────────────────────────

    def _image_rect(self):
        """Return (x, y, w, h) of the scaled image within the widget."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        scaled = self._pixmap.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return x, y, scaled.width(), scaled.height()

    def _widget_to_data(self, wx: int, wy: int):
        """Map widget pixel (wx, wy) → data coords (dx, dy) or None."""
        r = self._image_rect()
        if r is None or self._data is None:
            return None
        ix, iy, iw, ih = r
        if wx < ix or wx >= ix + iw or wy < iy or wy >= iy + ih:
            return None
        dh, dw = self._data.shape[:2]
        dx = int((wx - ix) / max(iw, 1) * dw)
        dy = int((wy - iy) / max(ih, 1) * dh)
        dx = max(0, min(dx, dw - 1))
        dy = max(0, min(dy, dh - 1))
        return dx, dy

    # ── paint ─────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # Background
        p.fillRect(self.rect(), QColor(PALETTE.get('bg', '#1e1e1e')))

        if self._pixmap is None or self._pixmap.isNull():
            p.setPen(QColor(PALETTE.get('textDim', '#888888')))
            p.drawText(self.rect(), Qt.AlignCenter, "No image")
            p.end()
            return

        r = self._image_rect()
        ix, iy, iw, ih = r
        scaled = self._pixmap.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(ix, iy, scaled)

        # ── ROI overlays ──────────────────────────────────────────
        if self._show_rois and self._rois and self._data is not None:
            dh, dw = self._data.shape[:2]
            p.setPen(QPen(QColor(255, 200, 0, 180), 2, Qt.DashLine))
            p.setBrush(QColor(255, 200, 0, 18))
            for roi in self._rois:
                if len(roi) < 4:
                    continue
                x0, y0, x1, y1 = roi[:4]
                rx = ix + int(x0 / max(dw, 1) * iw)
                ry = iy + int(y0 / max(dh, 1) * ih)
                rw = int((x1 - x0) / max(dw, 1) * iw)
                rh = int((y1 - y0) / max(dh, 1) * ih)
                p.drawRect(rx, ry, rw, rh)
            p.setBrush(Qt.NoBrush)

        p.end()

    # ── mouse tracking ────────────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pt = self._widget_to_data(event.x(), event.y())
        if pt is not None and self._data is not None:
            dx, dy = pt
            val = self._data[dy, dx]
            if isinstance(val, (np.floating, float)):
                fmt = f"{float(val):.4e}"
            else:
                fmt = str(val)
            self.cursor_value.emit(dx, dy, fmt)
        else:
            self.cursor_value.emit(-1, -1, "")
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.double_clicked.emit()

    def leaveEvent(self, event) -> None:
        self.cursor_value.emit(-1, -1, "")
        super().leaveEvent(event)


# ── DetachedViewer ───────────────────────────────────────────────────

class DetachedViewer(QWidget):
    """Detached image viewer window with light interaction (v4).

    Signals
    -------
    closed()
        Emitted when the viewer window is closed.
    """

    closed    = pyqtSignal()
    activated = pyqtSignal()   # emitted when the window gains focus

    def __init__(self, title: str = "Viewer",
                 parent: QWidget | None = None, *,
                 source_id: str = "") -> None:
        # Top-level window — no parent ownership (freely movable)
        super().__init__(None, Qt.Window)
        self._source_id = source_id
        self.setWindowTitle(f"SanjINSIGHT \u2014 {title}")
        self.setMinimumSize(640, 480)
        self.resize(960, 720)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._source_cmap: str = ""      # colormap last pushed by source
        self._local_cmap: str = ""       # user-selected colormap (empty = follow source)
        self._data: np.ndarray | None = None
        self._source_pixmap: QPixmap | None = None
        self._static_mode: bool = False

        # Restore geometry from prefs if we have a source_id
        self._restore_geometry()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Canvas (expanding, takes all space)
        self._canvas = _ViewerCanvas()
        self._canvas.double_clicked.connect(self._toggle_fullscreen)
        self._canvas.cursor_value.connect(self._on_cursor)
        layout.addWidget(self._canvas, 1)

        # Bottom control + info bar
        self._bottom = self._build_bottom_bar()
        layout.addWidget(self._bottom)

    # ── Bottom bar ────────────────────────────────────────────────

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        mono_css = (f"font-family:{MONO_FONT}; "
                    f"font-size:{FONT.get('caption', 11)}pt; ")

        # ── Colormap combo ────────────────────────────────────────
        cmap_lbl = QLabel("Cmap:")
        cmap_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 11)}pt; "
            f"color:{PALETTE.get('textDim', '#888')};")
        lay.addWidget(cmap_lbl)
        self._cmap_lbl = cmap_lbl

        self._cmap_combo = QComboBox()
        self._cmap_combo.setFixedHeight(22)
        self._cmap_combo.setMinimumWidth(120)
        from acquisition.processing import setup_cmap_combo
        setup_cmap_combo(self._cmap_combo, "Thermal Delta")
        # Insert "Follow Source" sentinel at index 0
        self._cmap_combo.insertItem(0, "\u2190 Source")
        self._cmap_combo.setCurrentIndex(0)
        self._cmap_combo.currentIndexChanged.connect(self._on_cmap_changed)
        lay.addWidget(self._cmap_combo)

        lay.addSpacing(6)

        # ── ROI toggle ────────────────────────────────────────────
        self._roi_cb = QCheckBox("ROI")
        self._roi_cb.setChecked(True)
        self._roi_cb.setStyleSheet(
            f"font-size:{FONT.get('caption', 11)}pt; "
            f"color:{PALETTE.get('textDim', '#888')};")
        self._roi_cb.toggled.connect(self._canvas.set_show_rois)
        lay.addWidget(self._roi_cb)

        # ── Divider ───────────────────────────────────────────────
        div = QLabel("\u2502")
        div.setFixedWidth(16)
        div.setAlignment(Qt.AlignCenter)
        div.setStyleSheet(f"color:{PALETTE.get('border', '#3a3a3a')};")
        self._div = div
        lay.addWidget(div)

        # ── Context info (from source) ────────────────────────────
        self._info = QLabel("")
        self._info.setStyleSheet(
            f"{mono_css} color:{PALETTE.get('textDim', '#888')};")
        lay.addWidget(self._info)

        lay.addStretch()

        # ── Cursor readout (right-aligned) ────────────────────────
        self._cursor_lbl = QLabel("")
        self._cursor_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._cursor_lbl.setStyleSheet(
            f"{mono_css} color:{PALETTE.get('accent', '#4fc3f7')};")
        lay.addWidget(self._cursor_lbl)

        # Bar styling
        bar.setStyleSheet(
            f"background:{PALETTE.get('surface', '#2a2a2a')}; "
            f"border-top:1px solid {PALETTE.get('border', '#3a3a3a')};")

        return bar

    # ── Public API ────────────────────────────────────────────────

    def update_image(self, pixmap: QPixmap, info: str = "", *,
                     data: np.ndarray | None = None,
                     rois: list | None = None,
                     cmap: str = "") -> None:
        """Push a new image to the detached viewer.

        Called by the source screen whenever its displayed image changes.

        Parameters
        ----------
        pixmap : QPixmap
            The rendered image (already colormapped/composited).
        info : str
            Optional one-line context string (camera model, frame info, etc.).
        data : np.ndarray | None
            Raw measurement array (ΔR/R, ΔT, etc.) for cursor readout.
            When provided, enables value-under-cursor display.
        rois : list | None
            List of ROI tuples ``(x0, y0, x1, y1)`` in data coordinates.
        cmap : str
            Colormap name used to render *pixmap*.  When the viewer's local
            colormap differs, it re-renders from *data* locally.
        """
        self._source_pixmap = pixmap
        self._source_cmap = cmap
        self._data = data
        self._canvas.set_data(data)
        self._canvas.set_rois(rois)

        # Re-render locally if user chose a different colormap
        if (self._local_cmap and data is not None
                and self._local_cmap != cmap):
            self._rerender()
        else:
            self._canvas.set_pixmap(pixmap)

        if info:
            self._info.setText(info)

    # ── Source ID / static mode ──────────────────────────────────

    @property
    def source_id(self) -> str:
        return self._source_id

    def set_static_mode(self, static: bool) -> None:
        """Enable/disable static (snapshot) mode.

        In static mode the "← Source" colormap option is hidden and
        a "Snapshot" badge appears in the info bar.
        """
        self._static_mode = static
        if static:
            # Hide "← Source" sentinel (index 0)
            if self._cmap_combo.count() > 0 and \
                    self._cmap_combo.itemText(0).startswith("\u2190"):
                self._cmap_combo.removeItem(0)
            if not self._info.text():
                self._info.setText("Snapshot")
        else:
            # Re-insert "← Source" if missing
            if self._cmap_combo.count() == 0 or \
                    not self._cmap_combo.itemText(0).startswith("\u2190"):
                self._cmap_combo.insertItem(0, "\u2190 Source")
                self._cmap_combo.setCurrentIndex(0)

    def update_context(self, info: str) -> None:
        """Update the bottom info-bar text without pushing a new image."""
        self._info.setText(info)

    # ── Geometry persistence ─────────────────────────────────────

    def _restore_geometry(self) -> None:
        """Restore window position/size from user prefs."""
        if not self._source_id:
            return
        try:
            import config as _cfg
            from PyQt5.QtCore import QByteArray
            geo = _cfg.get_pref(f"ui.detach.{self._source_id}.geometry", "")
            if geo:
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
        except Exception:
            pass

    def _save_geometry(self) -> None:
        """Persist window position/size to user prefs."""
        if not self._source_id:
            return
        try:
            import config as _cfg
            _cfg.set_pref(
                f"ui.detach.{self._source_id}.geometry",
                self.saveGeometry().toHex().data().decode())
        except Exception:
            pass

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowActivate:
            self.activated.emit()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._save_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._save_geometry()

    # ── Colormap ──────────────────────────────────────────────────

    def _on_cmap_changed(self, idx: int) -> None:
        if idx == 0:
            # "← Source" — follow source colormap
            self._local_cmap = ""
            if self._source_pixmap is not None:
                self._canvas.set_pixmap(self._source_pixmap)
        else:
            self._local_cmap = self._cmap_combo.currentText()
            if self._data is not None:
                self._rerender()

    def _rerender(self) -> None:
        """Re-render from raw data using the local colormap."""
        if self._data is None:
            return
        try:
            from acquisition.processing import to_display, apply_colormap
            cmap = self._local_cmap or self._source_cmap or "Thermal Delta"

            d = self._data.astype(np.float32)
            if cmap in ("Thermal Delta", "signed"):
                limit = float(np.percentile(np.abs(d), 99.5)) or 1e-9
                normed = np.clip(d / limit, -1.0, 1.0)
                r = (np.clip(normed, 0, 1) * 255).astype(np.uint8)
                b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
                g = np.zeros_like(r)
                rgb = np.stack([r, g, b], axis=-1)
            else:
                disp = to_display(d, mode="percentile")
                rgb = apply_colormap(disp, cmap)

            h, w = rgb.shape[:2]
            qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
            self._canvas.set_pixmap(QPixmap.fromImage(qi))
        except Exception:
            # Fall back to source pixmap on any error
            if self._source_pixmap is not None:
                self._canvas.set_pixmap(self._source_pixmap)

    # ── Cursor readout ────────────────────────────────────────────

    def _on_cursor(self, x: int, y: int, val: str) -> None:
        if x < 0:
            self._cursor_lbl.setText("")
        else:
            self._cursor_lbl.setText(f"({x}, {y})  {val}")

    # ── Full-screen toggle ────────────────────────────────────────

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._bottom.setVisible(True)
        else:
            self.showFullScreen()
            self._bottom.setVisible(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_F11:
            self._toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            self._bottom.setVisible(True)
        else:
            super().keyPressEvent(event)

    # ── Lifecycle ─────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_geometry()
        self.closed.emit()
        super().closeEvent(event)

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P = PALETTE
        mono_css = (f"font-family:{MONO_FONT}; "
                    f"font-size:{FONT.get('caption', 11)}pt; ")

        self._bottom.setStyleSheet(
            f"background:{P.get('surface', '#2a2a2a')}; "
            f"border-top:1px solid {P.get('border', '#3a3a3a')};")

        dim = f"font-size:{FONT.get('caption', 11)}pt; color:{P.get('textDim', '#888')};"
        self._cmap_lbl.setStyleSheet(dim)
        self._roi_cb.setStyleSheet(dim)
        self._div.setStyleSheet(f"color:{P.get('border', '#3a3a3a')};")
        self._info.setStyleSheet(f"{mono_css} color:{P.get('textDim', '#888')};")
        self._cursor_lbl.setStyleSheet(
            f"{mono_css} color:{P.get('accent', '#4fc3f7')};")
        self._canvas.update()
