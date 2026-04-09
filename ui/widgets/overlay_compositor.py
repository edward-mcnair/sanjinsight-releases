"""
ui/widgets/overlay_compositor.py

Compositing widget that blends multiple transparent overlay layers on top
of a base camera/image layer.  A slider controls the overlay opacity.

Overlay layers
--------------
  - **ROI outlines** — drawn from the global ROI model
  - **Thermal hotspots** — highlighted pixel regions from analysis results
  - **Custom annotations** — arbitrary painter callbacks

Usage
-----
::
    compositor = OverlayCompositor()
    compositor.set_base_frame(frame.data)
    compositor.add_overlay("roi", roi_paint_fn)
    compositor.add_overlay("hotspots", hotspot_paint_fn)
    compositor.set_opacity(0.5)

The widget is meant to be embedded in the Live View tab or any image
display context where layered information needs to be visualised.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QCheckBox,
    QFrame, QSizePolicy,
)

from ui.theme import PALETTE, FONT, MONO_FONT
from acquisition.processing import to_display
from acquisition import apply_colormap

log = logging.getLogger(__name__)

# Type alias for overlay paint functions.
# Signature: fn(painter: QPainter, widget_size: QSize, frame_hw: tuple[int, int])
OverlayPaintFn = Callable


class _ImageCanvas(QWidget):
    """Internal widget that composites base image + overlays via paintEvent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._base_pixmap: Optional[QPixmap] = None
        self._frame_hw = (1, 1)  # original frame (h, w) for coordinate mapping
        self._overlays: Dict[str, OverlayPaintFn] = {}
        self._overlay_opacity: float = 0.5
        self._overlay_visible: Dict[str, bool] = {}

    def set_base_pixmap(self, pix: QPixmap, frame_hw: tuple):
        self._base_pixmap = pix
        self._frame_hw = frame_hw
        self.update()

    def set_overlay_opacity(self, opacity: float):
        self._overlay_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def add_overlay(self, name: str, paint_fn: OverlayPaintFn):
        self._overlays[name] = paint_fn
        self._overlay_visible[name] = True
        self.update()

    def remove_overlay(self, name: str):
        self._overlays.pop(name, None)
        self._overlay_visible.pop(name, None)
        self.update()

    def set_overlay_visible(self, name: str, visible: bool):
        self._overlay_visible[name] = visible
        self.update()

    def paintEvent(self, event):
        if self._base_pixmap is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # Draw base image scaled to fill widget
        ws, hs = self.width(), self.height()
        scaled = self._base_pixmap.scaled(ws, hs, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation)
        x_off = (ws - scaled.width()) // 2
        y_off = (hs - scaled.height()) // 2
        p.drawPixmap(x_off, y_off, scaled)

        # Draw overlays with configurable opacity
        if self._overlays and self._overlay_opacity > 0:
            p.setOpacity(self._overlay_opacity)
            # Translate so (0,0) is at the image top-left
            p.save()
            p.translate(x_off, y_off)
            img_size = scaled.size()
            for name, paint_fn in self._overlays.items():
                if not self._overlay_visible.get(name, True):
                    continue
                try:
                    paint_fn(p, img_size, self._frame_hw)
                except Exception:
                    log.debug("Overlay %r paint failed", name, exc_info=True)
            p.restore()
            p.setOpacity(1.0)

        p.end()


class OverlayCompositor(QWidget):
    """Image display with composited overlay layers and opacity control.

    Signals
    -------
    opacity_changed : float
        Emitted when the user drags the opacity slider.
    """

    opacity_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        P, F = PALETTE, FONT

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ── Image canvas ─────────────────────────────────────────────
        self._canvas = _ImageCanvas()
        self._canvas.setStyleSheet(
            f"background: {P['canvas']}; border: 1px solid {P['border']};")
        outer.addWidget(self._canvas, 1)

        # ── Controls bar ─────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(4, 2, 4, 2)
        ctrl.setSpacing(8)

        lbl = QLabel("Overlay:")
        lbl.setStyleSheet(
            f"font-size: {F['label']}pt; color: {P['textDim']};")
        ctrl.addWidget(lbl)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(50)
        self._opacity_slider.setFixedWidth(140)
        self._opacity_slider.setToolTip("Overlay opacity")
        self._opacity_slider.valueChanged.connect(self._on_opacity)
        ctrl.addWidget(self._opacity_slider)

        self._opacity_lbl = QLabel("50%")
        self._opacity_lbl.setFixedWidth(36)
        self._opacity_lbl.setStyleSheet(
            f"font-family: {MONO_FONT}; font-size: {F['label']}pt; "
            f"color: {P['textDim']};")
        ctrl.addWidget(self._opacity_lbl)

        ctrl.addSpacing(12)

        # Layer toggle checkboxes (populated via add_overlay)
        self._layer_toggles: Dict[str, QCheckBox] = {}
        self._toggle_layout = ctrl

        ctrl.addStretch()
        outer.addLayout(ctrl)

    # ── Public API ────────────────────────────────────────────────────

    def set_base_frame(self, data, mode: str = "auto",
                       cmap: str = "gray") -> None:
        """Display a numpy array as the base image layer."""
        if data is None:
            return
        disp = to_display(data, mode=mode)
        if cmap != "gray" and disp.ndim == 2:
            disp = apply_colormap(disp, cmap)
        if disp.ndim == 2:
            h, w = disp.shape
            disp = np.ascontiguousarray(disp)
            qi = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = disp.shape[:2]
            qi = QImage(disp.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qi)
        self._canvas.set_base_pixmap(pix, (data.shape[0], data.shape[1]))

    def add_overlay(self, name: str, paint_fn: OverlayPaintFn,
                    label: str = "") -> None:
        """Register a named overlay layer with a paint callback.

        Parameters
        ----------
        name : str
            Unique key for this overlay (e.g. ``"roi"``, ``"hotspots"``).
        paint_fn : callable
            ``fn(painter, img_size, frame_hw)`` — draws on the painter
            in image-relative coordinates.
        label : str
            Human-readable label for the toggle checkbox.
        """
        self._canvas.add_overlay(name, paint_fn)
        if name not in self._layer_toggles:
            cb = QCheckBox(label or name.replace("_", " ").title())
            cb.setChecked(True)
            cb.setStyleSheet(
                f"font-size: {FONT['label']}pt; color: {PALETTE['textDim']};")
            cb.toggled.connect(
                lambda on, _n=name: self._canvas.set_overlay_visible(_n, on))
            # Insert before the stretch
            idx = self._toggle_layout.count() - 1
            self._toggle_layout.insertWidget(idx, cb)
            self._layer_toggles[name] = cb

    def remove_overlay(self, name: str) -> None:
        """Remove a named overlay layer."""
        self._canvas.remove_overlay(name)
        cb = self._layer_toggles.pop(name, None)
        if cb is not None:
            cb.setParent(None)
            cb.deleteLater()

    def set_opacity(self, value: float) -> None:
        """Programmatically set overlay opacity (0.0–1.0)."""
        self._opacity_slider.setValue(int(value * 100))

    def get_opacity(self) -> float:
        return self._opacity_slider.value() / 100.0

    # ── Theme support ─────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P, F = PALETTE, FONT
        self._canvas.setStyleSheet(
            f"background: {P['canvas']}; border: 1px solid {P['border']};")
        self._opacity_lbl.setStyleSheet(
            f"font-family: {MONO_FONT}; font-size: {F['label']}pt; "
            f"color: {P['textDim']};")
        for cb in self._layer_toggles.values():
            cb.setStyleSheet(
                f"font-size: {F['label']}pt; color: {P['textDim']};")

    # ── Internal ──────────────────────────────────────────────────────

    def _on_opacity(self, value: int) -> None:
        opacity = value / 100.0
        self._canvas.set_overlay_opacity(opacity)
        self._opacity_lbl.setText(f"{value}%")
        self.opacity_changed.emit(opacity)
