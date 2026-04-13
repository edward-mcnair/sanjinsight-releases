"""
ui/widgets/live_preview_dock.py

Dockable live camera preview — a QDockWidget that shows the camera feed
(raw or false-colour) and overlays multi-ROI rectangles.  Persists
across all tab switches so the user always has visual context.

Features:
    - Raw camera feed (colour, grayscale, or false-colour)
    - Optional live ΔR/R overlay when stimulus is active
    - ROI overlay from the shared RoiModel
    - Dockable / floatable / closable
    - View mode toggle: Native / Grayscale / False-colour
    - Reopenable from View menu

Usage (in MainWindow):
    self._preview_dock = LivePreviewDock(self)
    self.addDockWidget(Qt.RightDockWidgetArea, self._preview_dock)
    # Feed frames:
    self._preview_dock.update_frame(frame.data)
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt5.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSizePolicy)
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor

from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.widgets.detach_helpers import DetachableFrame, open_detached_viewer
from ui.font_utils import mono_font

log = logging.getLogger(__name__)


class _PreviewCanvas(QWidget):
    """Inner widget that renders the camera frame + ROI overlays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 150)
        self._pixmap = None
        self._frame_hw = (1, 1)
        self._view_mode = "native"  # native | grayscale | falsecolor

        from acquisition.roi_model import roi_model
        self._roi_model = roi_model
        roi_model.rois_changed.connect(self.update)
        roi_model.active_changed.connect(lambda _: self.update())

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        self.update()

    def set_frame(self, data: np.ndarray):
        """Accept a raw camera frame (uint8/uint16, 2D grayscale or 3D RGB)."""
        self._frame_hw = data.shape[:2]

        if self._view_mode == "grayscale" and data.ndim == 3:
            # Convert colour to grayscale
            data = np.mean(data, axis=2).astype(data.dtype)

        if self._view_mode == "falsecolor":
            # Apply inferno-like false colour to intensity
            if data.ndim == 3:
                gray = np.mean(data, axis=2)
            else:
                gray = data.astype(np.float32)
            lo, hi = np.percentile(gray, (1, 99))
            normed = np.clip((gray - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
            # Simple inferno approximation using lookup
            rgb = _apply_inferno(normed)
            h, w = rgb.shape[:2]
            qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        elif data.dtype != np.uint8:
            d = data.astype(np.float32)
            lo, hi = np.percentile(d, (1, 99))
            d = np.clip((d - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
            if d.ndim == 2:
                h, w = d.shape
                qi = QImage(d.data, w, h, w, QImage.Format_Grayscale8)
            else:
                h, w = d.shape[:2]
                qi = QImage(d.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        else:
            d = data
            if d.ndim == 2:
                h, w = d.shape
                qi = QImage(d.data, w, h, w, QImage.Format_Grayscale8)
            else:
                h, w = d.shape[:2]
                qi = QImage(d.tobytes(), w, h, w * 3, QImage.Format_RGB888)

        self._pixmap = QPixmap.fromImage(qi)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PALETTE['canvas']))

        if not self._pixmap:
            p.setPen(QColor(PALETTE['textDim']))
            p.setFont(mono_font(9))
            p.drawText(self.rect(), Qt.AlignCenter, "No camera feed")
            p.end()
            return

        # Scale image to fit
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        iw, ih = int(pw * scale), int(ph * scale)
        ox, oy = (ww - iw) // 2, (wh - ih) // 2
        p.drawPixmap(ox, oy, iw, ih, self._pixmap)

        # Draw ROI overlays
        fh, fw = self._frame_hw
        rois = self._roi_model.rois
        active_uid = self._roi_model.active_uid

        for roi in rois:
            if roi.is_empty:
                continue
            clamped = roi.clamp(fh, fw)
            color = QColor(roi.color) if roi.color else QColor(PALETTE['accent'])
            is_active = (roi.uid == active_uid)

            # Map frame coords to widget coords
            rx = int(ox + clamped.x / fw * iw)
            ry = int(oy + clamped.y / fh * ih)
            rw = int(clamped.w / fw * iw)
            rh = int(clamped.h / fh * ih)

            pen_width = 2 if is_active else 1
            p.setPen(QPen(color, pen_width))
            p.setBrush(Qt.NoBrush)
            p.drawRect(rx, ry, rw, rh)

            if roi.label and is_active:
                p.setFont(mono_font(7))
                p.drawText(rx + 2, ry - 3, roi.label)

        p.end()

    def _apply_styles(self):
        self.update()


def _apply_inferno(gray_u8: np.ndarray) -> np.ndarray:
    """Apply an inferno-like colormap to a uint8 grayscale array.

    Returns (H, W, 3) uint8 RGB.
    """
    # Build a simple 256-entry LUT approximating inferno
    try:
        import cv2
        bgr = cv2.applyColorMap(gray_u8, 20)  # COLORMAP_INFERNO
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except ImportError:
        pass

    try:
        from matplotlib import cm
        cmap = cm.get_cmap("inferno")
        rgba = cmap(gray_u8 / 255.0)
        return (rgba[:, :, :3] * 255).astype(np.uint8)
    except (ImportError, ValueError):
        pass

    # Fallback: just return grayscale as RGB
    return np.stack([gray_u8, gray_u8, gray_u8], axis=-1)


class LivePreviewDock(QDockWidget):
    """
    Floating/dockable live camera preview panel.

    Add to MainWindow via::

        dock = LivePreviewDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
    """

    def __init__(self, parent=None):
        super().__init__("Live Preview", parent)
        self.setObjectName("LivePreviewDock")
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea |
            Qt.BottomDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetClosable |
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Toolbar: view mode selector
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        lbl = QLabel("View:")
        lbl.setStyleSheet(scaled_qss(
            f"font-size:8pt; color:{PALETTE['textDim']};"))
        toolbar.addWidget(lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Native", "Grayscale", "False Color"])
        self._mode_combo.setFixedHeight(24)
        self._mode_combo.currentTextChanged.connect(self._on_mode)
        toolbar.addWidget(self._mode_combo)
        toolbar.addStretch()

        # Status label
        self._status_lbl = QLabel("No feed")
        self._status_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:8pt; "
            f"color:{PALETTE['textDim']};"))
        toolbar.addWidget(self._status_lbl)
        root.addLayout(toolbar)

        # Canvas
        self._canvas = _PreviewCanvas()
        self._canvas_frame = DetachableFrame(self._canvas)
        self._canvas_frame.detach_requested.connect(self._on_detach_preview)
        root.addWidget(self._canvas_frame, stretch=1)

        self.setWidget(container)
        self.setMinimumSize(250, 200)
        self.resize(350, 280)

        self._frame_count = 0

    def update_frame(self, data: np.ndarray):
        """Feed a camera frame to the preview."""
        if not self.isVisible():
            return
        self._canvas.set_frame(data)
        self._frame_count += 1
        h, w = data.shape[:2]
        ch = "RGB" if data.ndim == 3 else "Mono"
        self._status_lbl.setText(f"{w}\u00d7{h} {ch}")

    def _on_mode(self, text: str):
        mode_map = {"Native": "native", "Grayscale": "grayscale",
                    "False Color": "falsecolor"}
        self._canvas.set_view_mode(mode_map.get(text, "native"))

    _detached_preview = None

    def _on_detach_preview(self) -> None:
        """Open a detached viewer for the live camera preview."""
        def _push(viewer):
            pix = self._canvas.grab()
            if pix is not None and not pix.isNull():
                viewer.update_image(pix, "Live Preview")

        open_detached_viewer(
            self, "_detached_preview",
            source_id="live_preview.camera",
            title="Live Preview",
            initial_push=_push)

    def _apply_styles(self):
        self._canvas._apply_styles()
        self._status_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:8pt; "
            f"color:{PALETTE['textDim']};"))
