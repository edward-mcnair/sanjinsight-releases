"""
acquisition/roi_widget.py

Multi-ROI selector — displays a camera frame and lets the user draw
multiple rectangular ROIs by click-dragging on the image.

Features:
    - Click-drag on empty space to draw a new ROI
    - Click on an existing ROI to select (activate) it
    - Each ROI rendered in its own colour (from ROI_COLORS)
    - Active ROI has thicker border + corner handles
    - Semi-transparent mask outside all ROIs
    - Emits signals via the shared RoiModel

Usage:
    from acquisition.roi_widget import MultiRoiSelector
    selector = MultiRoiSelector()
    selector.set_frame(frame.data)
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QSizePolicy,
                              QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore    import Qt, pyqtSignal, QPoint, QRect, QSize
from PyQt5.QtGui     import (QImage, QPixmap, QPainter, QPen, QColor,
                              QBrush, QFont, QCursor)

from .roi       import Roi
from .roi_model import roi_model
from ui.icons        import set_btn_icon
from ui.font_utils   import mono_font
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT


# ────────────────────────────────────────────────────────────────────
#  Canvas — image display + multi-ROI overlay + drawing
# ────────────────────────────────────────────────────────────────────

class MultiRoiCanvas(QWidget):
    """
    Drawing surface that renders the camera frame with all ROIs overlaid.
    Subscribes to the shared ``roi_model`` for data.
    """
    # Emitted when the user finishes drawing a new ROI on the canvas
    roi_drawn = pyqtSignal(object)   # Roi

    _HIT_MARGIN = 8   # pixels tolerance for click-to-select

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)

        self._pixmap     = None
        self._frame_hw   = (1, 1)
        self._drag_start = None
        self._drag_end   = None
        self._dragging   = False
        self._show_mask  = True

        # Repaint when model changes
        roi_model.rois_changed.connect(self.update)
        roi_model.active_changed.connect(lambda _: self.update())

    # ── public ───────────────────────────────────────────────────────

    def set_frame(self, data: np.ndarray):
        """Update displayed frame (uint16 or uint8, 2D or 3D)."""
        self._frame_hw = data.shape[:2]

        if data.dtype != np.uint8:
            d = data.astype(np.float32)
            lo, hi = np.percentile(d, (1, 99))
            d = np.clip((d - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
        else:
            d = data

        if d.ndim == 2:
            h, w = d.shape
            qi   = QImage(d.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = d.shape[:2]
            qi   = QImage(d.tobytes(), w, h, w * 3, QImage.Format_RGB888)

        self._pixmap = QPixmap.fromImage(qi)
        self.update()

    # ── coordinate transforms ────────────────────────────────────────

    def _image_rect(self) -> QRect:
        if self._pixmap is None:
            return QRect(0, 0, self.width(), self.height())
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        iw, ih = int(pw * scale), int(ph * scale)
        return QRect((ww - iw) // 2, (wh - ih) // 2, iw, ih)

    def _widget_to_frame(self, pt: QPoint) -> QPoint:
        r  = self._image_rect()
        fh, fw = self._frame_hw
        if r.width() == 0 or r.height() == 0:
            return QPoint(0, 0)
        fx = max(0, min(int((pt.x() - r.x()) / r.width()  * fw), fw - 1))
        fy = max(0, min(int((pt.y() - r.y()) / r.height() * fh), fh - 1))
        return QPoint(fx, fy)

    def _frame_to_widget(self, pt: QPoint) -> QPoint:
        r  = self._image_rect()
        fh, fw = self._frame_hw
        wx = int(r.x() + pt.x() / fw * r.width())
        wy = int(r.y() + pt.y() / fh * r.height())
        return QPoint(wx, wy)

    def _roi_to_widget_rect(self, roi: Roi) -> QRect:
        fh, fw = self._frame_hw
        clamped = roi.clamp(fh, fw)
        tl = self._frame_to_widget(QPoint(clamped.x,  clamped.y))
        br = self._frame_to_widget(QPoint(clamped.x2, clamped.y2))
        return QRect(tl, br)

    def _drag_to_roi(self) -> Roi:
        if self._drag_start is None or self._drag_end is None:
            return Roi()
        p1 = self._widget_to_frame(self._drag_start)
        p2 = self._widget_to_frame(self._drag_end)
        x  = min(p1.x(), p2.x())
        y  = min(p1.y(), p2.y())
        w  = abs(p2.x() - p1.x())
        h  = abs(p2.y() - p1.y())
        return Roi(x=x, y=y, w=w, h=h)

    # ── hit testing ──────────────────────────────────────────────────

    def _hit_test(self, pos: QPoint) -> str | None:
        """Return uid of ROI under *pos*, or None."""
        # Check in reverse (top-most drawn last)
        for roi in reversed(roi_model.rois):
            wr = self._roi_to_widget_rect(roi)
            inflated = wr.adjusted(
                -self._HIT_MARGIN, -self._HIT_MARGIN,
                self._HIT_MARGIN, self._HIT_MARGIN)
            if inflated.contains(pos):
                return roi.uid
        return None

    # ── mouse events ─────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        hit_uid = self._hit_test(e.pos())
        if hit_uid:
            roi_model.set_active(hit_uid)
        else:
            self._drag_start = e.pos()
            self._drag_end   = e.pos()
            self._dragging   = True

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._drag_end = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._dragging:
            self._drag_end = e.pos()
            self._dragging = False
            new_roi = self._drag_to_roi()
            if new_roi.area > 100:
                self.roi_drawn.emit(new_roi)
            self._drag_start = None
            self._drag_end   = None
            self.update()

    # ── paint ────────────────────────────────────────────────────────

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        # Background
        p.fillRect(self.rect(), QColor(PALETTE['canvas']))

        # Image
        if not self._pixmap:
            p.end()
            return
        ir = self._image_rect()
        p.drawPixmap(ir, self._pixmap)

        rois = roi_model.rois
        active_uid = roi_model.active_uid

        # Semi-transparent mask outside ALL ROIs (combined)
        if self._show_mask and rois:
            mask_color = QColor(0, 0, 0, 100)
            # Build list of widget rects for all ROIs
            roi_rects = [self._roi_to_widget_rect(r) for r in rois
                         if not r.is_empty]
            if roi_rects:
                # Simple approach: draw semi-transparent overlay over the
                # whole image, then clear (punch out) each ROI rect
                p.save()
                p.setClipRect(ir)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                overlay = QPixmap(ir.size())
                overlay.fill(Qt.transparent)
                op = QPainter(overlay)
                op.fillRect(overlay.rect(), mask_color)
                op.setCompositionMode(QPainter.CompositionMode_Clear)
                for wr in roi_rects:
                    local = wr.translated(-ir.topLeft())
                    op.fillRect(local, Qt.transparent)
                op.end()
                p.drawPixmap(ir.topLeft(), overlay)
                p.restore()

        # Draw each ROI rectangle
        for roi in rois:
            if roi.is_empty:
                continue
            wr = self._roi_to_widget_rect(roi)
            color = QColor(roi.color) if roi.color else QColor(PALETTE['accent'])
            is_active = (roi.uid == active_uid)

            # Border
            p.setBrush(Qt.NoBrush)
            pen_width = 3 if is_active else 1
            p.setPen(QPen(color, pen_width))
            p.drawRect(wr)

            # Corner handles (active ROI only)
            if is_active:
                hs = 7
                p.setBrush(QBrush(color))
                for cx, cy in [(wr.x(), wr.y()),
                               (wr.right(), wr.y()),
                               (wr.x(), wr.bottom()),
                               (wr.right(), wr.bottom())]:
                    p.drawRect(cx - hs // 2, cy - hs // 2, hs, hs)

            # Label
            if roi.label:
                p.setFont(mono_font(8))
                p.setPen(QPen(color))
                p.drawText(wr.x() + 3, wr.y() - 4, roi.label)

        # Live drag rectangle
        if self._dragging and self._drag_start and self._drag_end:
            drag_roi = self._drag_to_roi()
            drag_rect = QRect(
                self._drag_start.x(), self._drag_start.y(),
                self._drag_end.x() - self._drag_start.x(),
                self._drag_end.y() - self._drag_start.y())

            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(PALETTE['warning']), 1, Qt.DashLine))
            p.drawRect(drag_rect)

            if not drag_roi.is_empty:
                label = f"{drag_roi.w} \u00d7 {drag_roi.h} px"
                p.setFont(mono_font(8))
                p.setPen(QPen(QColor(PALETTE['warning'])))
                p.drawText(
                    min(self._drag_start.x(), self._drag_end.x()),
                    min(self._drag_start.y(), self._drag_end.y()) - 4,
                    label)

        p.end()

    def _apply_styles(self):
        self.update()


# ────────────────────────────────────────────────────────────────────
#  ROI list widget — shows all ROIs with colour swatches
# ────────────────────────────────────────────────────────────────────

class _RoiListWidget(QListWidget):
    """Compact list of ROIs with colour indicators."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(160)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setStyleSheet(scaled_qss(
            f"QListWidget {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; "
            f"color:{PALETTE['text']}; font-size:9pt; }}"
            f"QListWidget::item:selected {{ background:{PALETTE['accent']}22; }}"))
        self.currentRowChanged.connect(self._on_row)
        roi_model.rois_changed.connect(self._refresh)
        roi_model.active_changed.connect(lambda _: self._sync_selection())

    def _refresh(self):
        self.blockSignals(True)
        self.clear()
        for roi in roi_model.rois:
            txt = f"  {roi.label}  ({roi.w}\u00d7{roi.h})"
            item = QListWidgetItem(txt)
            item.setData(Qt.UserRole, roi.uid)
            if roi.color:
                item.setForeground(QColor(roi.color))
            self.addItem(item)
        self._sync_selection()
        self.blockSignals(False)

    def _sync_selection(self):
        uid = roi_model.active_uid
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == uid:
                self.blockSignals(True)
                self.setCurrentRow(i)
                self.blockSignals(False)
                return

    def _on_row(self, row: int):
        if 0 <= row < self.count():
            uid = self.item(row).data(Qt.UserRole)
            roi_model.set_active(uid)

    def _apply_styles(self):
        self.setStyleSheet(scaled_qss(
            f"QListWidget {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; "
            f"color:{PALETTE['text']}; font-size:9pt; }}"
            f"QListWidget::item:selected {{ background:{PALETTE['accent']}22; }}"))
        self._refresh()


# ────────────────────────────────────────────────────────────────────
#  MultiRoiSelector — canvas + list + controls
# ────────────────────────────────────────────────────────────────────

class MultiRoiSelector(QWidget):
    """
    Full multi-ROI selector panel: canvas, ROI list, and control buttons.
    Operates on the shared ``roi_model`` singleton.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Canvas
        self._canvas = MultiRoiCanvas()
        self._canvas.roi_drawn.connect(self._on_new_roi)
        root.addWidget(self._canvas, stretch=1)

        # Info label (active ROI details)
        self._info = QLabel("No ROIs defined — full frame")
        self._info.setStyleSheet(
            scaled_qss(f"font-family:{MONO_FONT}; font-size:9pt; "
                        f"color:{PALETTE['textDim']};"))
        root.addWidget(self._info)

        # ROI list
        self._list = _RoiListWidget()
        root.addWidget(self._list)

        # Button bar
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._remove_btn = QPushButton("Remove")
        set_btn_icon(self._remove_btn, "fa5s.trash")
        self._remove_btn.setFixedWidth(90)
        self._remove_btn.clicked.connect(self._remove_active)
        bar.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("Clear All")
        set_btn_icon(self._clear_btn, "fa5s.times")
        self._clear_btn.setFixedWidth(90)
        self._clear_btn.clicked.connect(roi_model.clear)
        bar.addWidget(self._clear_btn)

        bar.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            scaled_qss(f"font-size:8pt; color:{PALETTE['textDim']};"))
        bar.addWidget(self._count_label)

        root.addLayout(bar)

        # Wire model signals
        roi_model.rois_changed.connect(self._update_info)
        roi_model.active_changed.connect(lambda _: self._update_info())
        self._update_info()

    # ── public ───────────────────────────────────────────────────────

    def set_frame(self, data: np.ndarray):
        self._canvas.set_frame(data)

    # ── slots ────────────────────────────────────────────────────────

    def _on_new_roi(self, roi: Roi):
        roi_model.add(roi)

    def _remove_active(self):
        uid = roi_model.active_uid
        if uid:
            roi_model.remove(uid)

    def _update_info(self):
        active = roi_model.active_roi
        count = roi_model.count
        if active and not active.is_empty:
            self._info.setText(
                f"{active.label}  x={active.x}  y={active.y}  "
                f"w={active.w}  h={active.h}  ({active.area:,} px)")
        elif count == 0:
            self._info.setText("No ROIs defined \u2014 full frame")
        else:
            self._info.setText(f"{count} ROI(s) defined")
        self._count_label.setText(f"{count}/16 ROIs" if count else "")
        self._remove_btn.setEnabled(count > 0)
        self._clear_btn.setEnabled(count > 0)

    def _apply_styles(self):
        self._canvas._apply_styles()
        self._list._apply_styles()
        self._info.setStyleSheet(
            scaled_qss(f"font-family:{MONO_FONT}; font-size:9pt; "
                        f"color:{PALETTE['textDim']};"))
        self._count_label.setStyleSheet(
            scaled_qss(f"font-size:8pt; color:{PALETTE['textDim']};"))


# ────────────────────────────────────────────────────────────────────
#  Lightweight overlay — for embedding in non-ROI tabs
# ────────────────────────────────────────────────────────────────────

class RoiOverlay(QWidget):
    """
    Transparent overlay that draws ROI rectangles on top of any image
    widget.  Install over a QLabel or similar using a stacked layout.

    Does NOT handle mouse events — read-only visualisation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._frame_hw = (1, 1)

        roi_model.rois_changed.connect(self.update)
        roi_model.active_changed.connect(lambda _: self.update())

    def set_frame_size(self, h: int, w: int):
        self._frame_hw = (h, w)
        self.update()

    def paintEvent(self, e):
        if not roi_model.rois:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        fh, fw = self._frame_hw
        ww, wh = self.width(), self.height()
        sx = ww / fw if fw else 1
        sy = wh / fh if fh else 1

        for roi in roi_model.rois:
            if roi.is_empty:
                continue
            color = QColor(roi.color) if roi.color else QColor(PALETTE['accent'])
            is_active = (roi.uid == roi_model.active_uid)
            pen_width = 2 if is_active else 1
            p.setPen(QPen(color, pen_width))
            p.setBrush(Qt.NoBrush)
            rx = int(roi.x * sx)
            ry = int(roi.y * sy)
            rw = int(roi.w * sx)
            rh = int(roi.h * sy)
            p.drawRect(rx, ry, rw, rh)

            if roi.label and is_active:
                p.setFont(mono_font(7))
                p.drawText(rx + 2, ry - 3, roi.label)

        p.end()

    def _apply_styles(self):
        self.update()


# ────────────────────────────────────────────────────────────────────
#  Backward-compatible aliases
# ────────────────────────────────────────────────────────────────────

# Legacy single-ROI classes — thin wrappers so existing imports don't break
class RoiCanvas(MultiRoiCanvas):
    """Backward-compatible alias for MultiRoiCanvas."""
    roi_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        roi_model.rois_changed.connect(self._emit_compat)

    @property
    def roi(self) -> Roi:
        return roi_model.active_roi or Roi()

    def set_roi(self, roi: Roi):
        roi_model.clear()
        if not roi.is_empty:
            roi_model.add(roi)
        self.roi_changed.emit(roi)

    def clear_roi(self):
        roi_model.clear()
        self.roi_changed.emit(Roi())

    def _emit_compat(self):
        self.roi_changed.emit(roi_model.active_roi or Roi())


class RoiSelector(QWidget):
    """Backward-compatible single-ROI selector."""
    roi_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._canvas = RoiCanvas()
        self._canvas.roi_changed.connect(self._on_roi)
        root.addWidget(self._canvas)

        bar = QHBoxLayout()
        self._info = QLabel("No ROI \u2014 full frame")
        self._info.setStyleSheet(
            scaled_qss(f"font-family:{MONO_FONT}; font-size:9pt; "
                        f"color:{PALETTE['textDim']};"))
        bar.addWidget(self._info)
        bar.addStretch()

        self._clear_btn = QPushButton("Clear ROI")
        set_btn_icon(self._clear_btn, "fa5s.times")
        self._clear_btn.setFixedWidth(100)
        self._clear_btn.clicked.connect(self._canvas.clear_roi)
        bar.addWidget(self._clear_btn)
        root.addLayout(bar)

    @property
    def roi(self) -> Roi:
        return self._canvas.roi

    def set_frame(self, data: np.ndarray):
        self._canvas.set_frame(data)

    def _apply_styles(self):
        self._canvas._apply_styles()
        self._info.setStyleSheet(
            scaled_qss(f"font-family:{MONO_FONT}; font-size:9pt; "
                        f"color:{PALETTE['textDim']};"))

    def _on_roi(self, roi: Roi):
        if roi.is_empty:
            self._info.setText("No ROI \u2014 full frame")
        else:
            self._info.setText(
                f"ROI  x={roi.x}  y={roi.y}  "
                f"w={roi.w}  h={roi.h}  "
                f"({roi.area:,} px)")
        self.roi_changed.emit(roi)
