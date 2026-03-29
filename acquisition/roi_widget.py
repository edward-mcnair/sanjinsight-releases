"""
acquisition/roi_widget.py

RoiSelector — a QWidget that displays a camera frame and lets the user
draw a rectangular ROI by click-dragging on the image.

Features:
    - Click-drag to draw a new ROI
    - Displays ROI dimensions as you drag
    - "Clear ROI" button resets to full frame
    - Emits roi_changed(Roi) signal whenever the ROI updates
    - Overlays the ROI rectangle on the live image
    - Optionally shows a semi-transparent mask outside the ROI

Usage:
    selector = RoiSelector()
    selector.roi_changed.connect(my_callback)
    selector.set_frame(frame.data)         # update displayed image
    current_roi = selector.roi             # read current ROI
"""

import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QSizePolicy)
from PyQt5.QtCore    import Qt, pyqtSignal, QPoint, QRect
from PyQt5.QtGui     import (QImage, QPixmap, QPainter, QPen, QColor,
                              QBrush, QFont, QCursor)

from .roi import Roi
from ui.icons        import set_btn_icon
from ui.font_utils   import mono_font
from ui.theme import FONT, scaled_qss, MONO_FONT


class RoiCanvas(QWidget):
    """
    Inner widget — shows the image and handles mouse drawing.
    """
    roi_changed = pyqtSignal(object)   # Roi

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)

        self._pixmap     = None
        self._frame_hw   = (1, 1)      # (H, W) of the source frame
        self._roi        = Roi()       # current confirmed ROI
        self._drag_start = None        # QPoint in widget coords
        self._drag_end   = None        # QPoint in widget coords
        self._dragging   = False
        self._show_mask  = True

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    @property
    def roi(self) -> Roi:
        return self._roi

    def set_roi(self, roi: Roi):
        self._roi = roi
        self.update()
        self.roi_changed.emit(roi)

    def set_frame(self, data: np.ndarray):
        """Update displayed frame (uint16 or uint8, 2D or 3D)."""
        self._frame_hw = data.shape[:2]

        # Convert to uint8 for display
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

    def clear_roi(self):
        self._roi      = Roi()
        self._dragging = False
        self.update()
        self.roi_changed.emit(self._roi)

    # ---------------------------------------------------------------- #
    #  Coordinate transforms                                           #
    # ---------------------------------------------------------------- #

    def _image_rect(self) -> QRect:
        """QRect of the scaled image within the widget."""
        if self._pixmap is None:
            return QRect(0, 0, self.width(), self.height())
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = self.width()
        wh = self.height()
        scale = min(ww / pw, wh / ph)
        iw = int(pw * scale)
        ih = int(ph * scale)
        ox = (ww - iw) // 2
        oy = (wh - ih) // 2
        return QRect(ox, oy, iw, ih)

    def _widget_to_frame(self, pt: QPoint) -> QPoint:
        """Convert widget pixel → frame pixel."""
        r  = self._image_rect()
        fh, fw = self._frame_hw
        if r.width() == 0 or r.height() == 0:
            return QPoint(0, 0)
        fx = int((pt.x() - r.x()) / r.width()  * fw)
        fy = int((pt.y() - r.y()) / r.height() * fh)
        fx = max(0, min(fx, fw - 1))
        fy = max(0, min(fy, fh - 1))
        return QPoint(fx, fy)

    def _frame_to_widget(self, pt: QPoint) -> QPoint:
        """Convert frame pixel → widget pixel."""
        r  = self._image_rect()
        fh, fw = self._frame_hw
        wx = int(r.x() + pt.x() / fw * r.width())
        wy = int(r.y() + pt.y() / fh * r.height())
        return QPoint(wx, wy)

    def _drag_to_roi(self) -> Roi:
        """Convert current drag points to a frame-space Roi."""
        if self._drag_start is None or self._drag_end is None:
            return Roi()
        p1 = self._widget_to_frame(self._drag_start)
        p2 = self._widget_to_frame(self._drag_end)
        x  = min(p1.x(), p2.x())
        y  = min(p1.y(), p2.y())
        w  = abs(p2.x() - p1.x())
        h  = abs(p2.y() - p1.y())
        return Roi(x=x, y=y, w=w, h=h)

    # ---------------------------------------------------------------- #
    #  Mouse events                                                     #
    # ---------------------------------------------------------------- #

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
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
            if new_roi.area > 100:        # ignore tiny accidental clicks
                self._roi = new_roi
                self.roi_changed.emit(self._roi)
            self._drag_start = None
            self._drag_end   = None
            self.update()

    # ---------------------------------------------------------------- #
    #  Paint                                                            #
    # ---------------------------------------------------------------- #

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        # Background
        p.fillRect(self.rect(), QColor(13, 13, 13))

        # Image
        if self._pixmap:
            r = self._image_rect()
            p.drawPixmap(r, self._pixmap)

            # Semi-transparent mask outside confirmed ROI
            if self._show_mask and not self._roi.is_empty:
                fh, fw = self._frame_hw
                roi    = self._roi.clamp(fh, fw)
                r1 = self._frame_to_widget(QPoint(roi.x,  roi.y))
                r2 = self._frame_to_widget(QPoint(roi.x2, roi.y2))
                roi_rect = QRect(r1, r2)

                p.setBrush(QBrush(QColor(0, 0, 0, 120)))
                p.setPen(Qt.NoPen)
                ir = self._image_rect()
                # Draw 4 darkened rectangles around the ROI
                p.drawRect(QRect(ir.x(), ir.y(),
                                 ir.width(), roi_rect.y() - ir.y()))
                p.drawRect(QRect(ir.x(), roi_rect.bottom(),
                                 ir.width(), ir.bottom() - roi_rect.bottom()))
                p.drawRect(QRect(ir.x(), roi_rect.y(),
                                 roi_rect.x() - ir.x(), roi_rect.height()))
                p.drawRect(QRect(roi_rect.right(), roi_rect.y(),
                                 ir.right() - roi_rect.right(), roi_rect.height()))

                # ROI border
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(0, 212, 170), 2))
                p.drawRect(roi_rect)

                # Corner handles
                hs = 6
                p.setBrush(QBrush(QColor(0, 212, 170)))
                for cx, cy in [(roi_rect.x(), roi_rect.y()),
                               (roi_rect.right(), roi_rect.y()),
                               (roi_rect.x(), roi_rect.bottom()),
                               (roi_rect.right(), roi_rect.bottom())]:
                    p.drawRect(cx - hs//2, cy - hs//2, hs, hs)

        # Live drag rectangle
        if self._dragging and self._drag_start and self._drag_end:
            drag_roi = self._drag_to_roi()
            p1 = self._frame_to_widget(
                QPoint(drag_roi.x, drag_roi.y))
            p2 = self._frame_to_widget(
                QPoint(drag_roi.x2, drag_roi.y2))
            drag_rect = QRect(
                self._drag_start.x(), self._drag_start.y(),
                self._drag_end.x() - self._drag_start.x(),
                self._drag_end.y() - self._drag_start.y())

            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 0), 1, Qt.DashLine))
            p.drawRect(drag_rect)

            # Dimension label
            if not drag_roi.is_empty:
                label = f"{drag_roi.w} × {drag_roi.h} px"
                p.setFont(mono_font(8))
                p.setPen(QPen(QColor(255, 255, 0)))
                p.drawText(
                    min(self._drag_start.x(), self._drag_end.x()),
                    min(self._drag_start.y(), self._drag_end.y()) - 4,
                    label)

        p.end()


class RoiSelector(QWidget):
    """
    Full ROI selector panel: canvas + info bar + controls.
    """
    roi_changed = pyqtSignal(object)   # Roi

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Canvas
        self._canvas = RoiCanvas()
        self._canvas.roi_changed.connect(self._on_roi)
        root.addWidget(self._canvas)

        # Info bar
        bar = QHBoxLayout()
        self._info = QLabel("No ROI — full frame")
        self._info.setStyleSheet(
            scaled_qss(f"font-family:{MONO_FONT}; font-size:9pt; color:#555;"))
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

    def _on_roi(self, roi: Roi):
        if roi.is_empty:
            self._info.setText("No ROI — full frame")
        else:
            self._info.setText(
                f"ROI  x={roi.x}  y={roi.y}  "
                f"w={roi.w}  h={roi.h}  "
                f"({roi.area:,} px)")
        self.roi_changed.emit(roi)
