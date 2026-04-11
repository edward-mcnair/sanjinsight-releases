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
                              QBrush, QFont, QCursor, QPainterPath,
                              QPolygonF)
from PyQt5.QtCore    import QPointF

from .roi       import Roi, SHAPE_FREEFORM
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
        self._draw_shape: str = "rect"   # shape for new ROIs drawn on canvas

        # Freeform drawing state
        self._freeform_pts: list[QPoint] = []  # widget-space vertices
        self._freeform_drawing = False

        # Repaint when model changes
        roi_model.rois_changed.connect(self.update)
        roi_model.active_changed.connect(lambda _: self.update())

    # ── public ───────────────────────────────────────────────────────

    def set_draw_shape(self, shape: str) -> None:
        """Set the shape type for new ROIs drawn on the canvas.

        If a freeform drawing is in progress it is cancelled automatically
        so the canvas never gets stuck in an orphaned freeform state.
        """
        if self._freeform_drawing and shape != "freeform":
            self._cancel_freeform()
        self._draw_shape = shape

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

    def _roi_to_widget_polygon(self, roi: Roi) -> QPolygonF:
        """Convert a freeform ROI's vertices to widget-space QPolygonF."""
        poly = QPolygonF()
        for vx, vy in roi.vertices:
            wp = self._frame_to_widget(QPoint(vx, vy))
            poly.append(QPointF(wp.x(), wp.y()))
        return poly

    def _drag_to_roi(self) -> Roi:
        if self._drag_start is None or self._drag_end is None:
            return Roi()
        p1 = self._widget_to_frame(self._drag_start)
        p2 = self._widget_to_frame(self._drag_end)
        x  = min(p1.x(), p2.x())
        y  = min(p1.y(), p2.y())
        w  = abs(p2.x() - p1.x())
        h  = abs(p2.y() - p1.y())
        return Roi(x=x, y=y, w=w, h=h, shape=self._draw_shape)

    # ── hit testing ──────────────────────────────────────────────────

    def _hit_test(self, pos: QPoint) -> str | None:
        """Return uid of ROI under *pos*, or None."""
        # Check in reverse (top-most drawn last)
        for roi in reversed(roi_model.rois):
            if roi.is_freeform and roi.vertices:
                poly = self._roi_to_widget_polygon(roi)
                if poly.containsPoint(QPointF(pos.x(), pos.y()), Qt.OddEvenFill):
                    return roi.uid
                continue
            wr = self._roi_to_widget_rect(roi)
            inflated = wr.adjusted(
                -self._HIT_MARGIN, -self._HIT_MARGIN,
                self._HIT_MARGIN, self._HIT_MARGIN)
            if inflated.contains(pos):
                return roi.uid
        return None

    # ── freeform helpers ────────────────────────────────────────────

    def _finish_freeform(self):
        """Close the freeform polygon and emit the ROI."""
        if len(self._freeform_pts) < 3:
            self._freeform_pts.clear()
            self._freeform_drawing = False
            self.update()
            return
        # Convert widget points to frame-space vertices
        vertices = []
        for pt in self._freeform_pts:
            fp = self._widget_to_frame(pt)
            vertices.append((fp.x(), fp.y()))
        self._freeform_pts.clear()
        self._freeform_drawing = False
        roi = Roi.from_vertices(vertices)
        if roi.area > 30:
            self.roi_drawn.emit(roi)
        self.update()

    def _cancel_freeform(self):
        """Cancel the current freeform drawing without creating an ROI."""
        self._freeform_pts.clear()
        self._freeform_drawing = False
        self.update()

    # ── mouse events ─────────────────────────────────────────────────

    def mousePressEvent(self, e):
        # Freeform mode: click adds a vertex
        if self._draw_shape == "freeform":
            if e.button() == Qt.LeftButton:
                if not self._freeform_drawing:
                    # First click — start a new polygon
                    hit_uid = self._hit_test(e.pos())
                    if hit_uid and not self._freeform_pts:
                        roi_model.set_active(hit_uid)
                        return
                    self._freeform_drawing = True
                    self._freeform_pts = [e.pos()]
                else:
                    # Check if clicking near start point to close
                    if len(self._freeform_pts) >= 3:
                        d = (e.pos() - self._freeform_pts[0])
                        dist = (d.x() ** 2 + d.y() ** 2) ** 0.5
                        if dist < 12:
                            self._finish_freeform()
                            return
                    self._freeform_pts.append(e.pos())
                self.update()
            elif e.button() == Qt.RightButton:
                if self._freeform_drawing:
                    self._cancel_freeform()
            return

        # Rect / ellipse mode: drag to draw
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
        if self._freeform_drawing:
            self.update()  # repaint to show rubber-band line to cursor
            return
        if self._dragging:
            self._drag_end = e.pos()
            self.update()

    def mouseDoubleClickEvent(self, e):
        """Double-click closes the freeform polygon."""
        if self._draw_shape == "freeform" and self._freeform_drawing:
            if e.button() == Qt.LeftButton:
                self._finish_freeform()
            return

    def mouseReleaseEvent(self, e):
        if self._draw_shape == "freeform":
            return  # freeform is click-based, not drag-based
        if e.button() == Qt.LeftButton and self._dragging:
            self._drag_end = e.pos()
            self._dragging = False
            new_roi = self._drag_to_roi()
            if new_roi.area > 100:
                self.roi_drawn.emit(new_roi)
            self._drag_start = None
            self._drag_end   = None
            self.update()

    def keyPressEvent(self, e):
        """Escape cancels freeform drawing; Enter/Return closes it."""
        if self._freeform_drawing:
            if e.key() == Qt.Key_Escape:
                self._cancel_freeform()
                return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_freeform()
                return
        super().keyPressEvent(e)

    # ── paint ────────────────────────────────────────────────────────

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

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
            visible = [r for r in rois if not r.is_empty]
            if visible:
                # Draw semi-transparent overlay over the whole image,
                # then clear (punch out) each ROI shape
                p.save()
                p.setClipRect(ir)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                overlay = QPixmap(ir.size())
                overlay.fill(Qt.transparent)
                op = QPainter(overlay)
                op.setRenderHint(QPainter.Antialiasing, True)
                op.fillRect(overlay.rect(), mask_color)
                op.setCompositionMode(QPainter.CompositionMode_Clear)
                op.setPen(Qt.NoPen)
                op.setBrush(Qt.transparent)
                for roi in visible:
                    if roi.is_freeform and roi.vertices:
                        poly = self._roi_to_widget_polygon(roi)
                        local = poly.translated(-ir.x(), -ir.y())
                        path = QPainterPath()
                        path.addPolygon(local)
                        op.fillPath(path, Qt.transparent)
                    else:
                        wr = self._roi_to_widget_rect(roi)
                        local = wr.translated(-ir.topLeft())
                        if roi.is_ellipse:
                            op.drawEllipse(local)
                        else:
                            op.fillRect(local, Qt.transparent)
                op.end()
                p.drawPixmap(ir.topLeft(), overlay)
                p.restore()

        # Draw each ROI shape
        for roi in rois:
            if roi.is_empty:
                continue
            color = QColor(roi.color) if roi.color else QColor(PALETTE['accent'])
            is_active = (roi.uid == active_uid)

            # Border
            p.setBrush(Qt.NoBrush)
            pen_width = 3 if is_active else 1
            p.setPen(QPen(color, pen_width))

            if roi.is_freeform and roi.vertices:
                poly = self._roi_to_widget_polygon(roi)
                p.drawPolygon(poly)
                # Vertex handles (active ROI only)
                if is_active:
                    hs = 6
                    p.setBrush(QBrush(color))
                    for i in range(poly.count()):
                        pt = poly.at(i)
                        p.drawEllipse(pt, hs // 2, hs // 2)
            else:
                wr = self._roi_to_widget_rect(roi)
                if roi.is_ellipse:
                    p.drawEllipse(wr)
                else:
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
                wr = self._roi_to_widget_rect(roi)
                p.drawText(wr.x() + 3, wr.y() - 4, roi.label)

        # Live drag preview (rect / ellipse)
        if self._dragging and self._drag_start and self._drag_end:
            drag_roi = self._drag_to_roi()
            drag_rect = QRect(
                self._drag_start.x(), self._drag_start.y(),
                self._drag_end.x() - self._drag_start.x(),
                self._drag_end.y() - self._drag_start.y())

            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(PALETTE['warning']), 1, Qt.DashLine))
            if self._draw_shape == "ellipse":
                p.drawEllipse(drag_rect)
            else:
                p.drawRect(drag_rect)

            if not drag_roi.is_empty:
                label = f"{drag_roi.w} \u00d7 {drag_roi.h} px"
                p.setFont(mono_font(8))
                p.setPen(QPen(QColor(PALETTE['warning'])))
                p.drawText(
                    min(self._drag_start.x(), self._drag_end.x()),
                    min(self._drag_start.y(), self._drag_end.y()) - 4,
                    label)

        # Live freeform polygon preview
        if self._freeform_drawing and self._freeform_pts:
            warn = QColor(PALETTE['warning'])
            p.setPen(QPen(warn, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)

            # Draw completed edges
            for i in range(len(self._freeform_pts) - 1):
                p.drawLine(self._freeform_pts[i], self._freeform_pts[i + 1])

            # Rubber-band line from last point to cursor
            cursor_pos = self.mapFromGlobal(QCursor.pos())
            if self._freeform_pts:
                p.setPen(QPen(warn, 1, Qt.DotLine))
                p.drawLine(self._freeform_pts[-1], cursor_pos)
                # Also show closing line to start
                if len(self._freeform_pts) >= 3:
                    close_col = QColor(PALETTE['accent'])
                    close_col.setAlpha(100)
                    p.setPen(QPen(close_col, 1, Qt.DotLine))
                    p.drawLine(cursor_pos, self._freeform_pts[0])

            # Draw vertex dots
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(warn))
            for pt in self._freeform_pts:
                p.drawEllipse(pt, 4, 4)

            # Start-point highlight (close target)
            if len(self._freeform_pts) >= 3:
                start = self._freeform_pts[0]
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(PALETTE['accent']), 2))
                p.drawEllipse(start, 10, 10)

            # Vertex count label
            n = len(self._freeform_pts)
            p.setFont(mono_font(8))
            p.setPen(QPen(warn))
            p.drawText(self._freeform_pts[0].x() + 8,
                        self._freeform_pts[0].y() - 8,
                        f"{n} pts")

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
            sh = "\u2B53" if roi.is_freeform else ("\u2B2D" if roi.is_ellipse else "\u25AD")  # ⬓ ⬭ ▭
            txt = f"  {sh} {roi.label}  ({roi.w}\u00d7{roi.h})"
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

    def set_draw_shape(self, shape: str) -> None:
        """Set the shape type for new ROIs drawn on the canvas."""
        self._canvas.set_draw_shape(shape)

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
            if active.is_freeform:
                sh = f"freeform {len(active.vertices)}pts"
            elif active.is_ellipse:
                sh = "ellipse"
            else:
                sh = "rect"
            self._info.setText(
                f"{active.label}  [{sh}]  x={active.x}  y={active.y}  "
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
    Transparent overlay that draws ROI shapes (rect or ellipse) on top
    of any image widget.  Install over a QLabel or similar using a
    stacked layout.

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
        p.setRenderHint(QPainter.Antialiasing, True)
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

            if roi.is_freeform and roi.vertices:
                poly = QPolygonF()
                for vx, vy in roi.vertices:
                    poly.append(QPointF(vx * sx, vy * sy))
                p.drawPolygon(poly)
            elif roi.is_ellipse:
                rx = int(roi.x * sx)
                ry = int(roi.y * sy)
                rw = int(roi.w * sx)
                rh = int(roi.h * sy)
                p.drawEllipse(rx, ry, rw, rh)
            else:
                rx = int(roi.x * sx)
                ry = int(roi.y * sy)
                rw = int(roi.w * sx)
                rh = int(roi.h * sy)
                p.drawRect(rx, ry, rw, rh)

            if roi.label and is_active:
                p.setFont(mono_font(7))
                p.drawText(int(roi.x * sx) + 2, int(roi.y * sy) - 3, roi.label)

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
