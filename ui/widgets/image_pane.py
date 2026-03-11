"""
ui/widgets/image_pane.py

ImagePane — a simple widget that displays a numpy array as a scaled QLabel image,
with min/max/mean statistics below it.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import QImage, QPixmap

from acquisition.processing import to_display
from acquisition             import apply_colormap
from ui.theme import FONT, scaled_qss


class ImagePane(QWidget):
    def __init__(self, title: str = "", w: int = 400, h: int = 300):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._lbl = QLabel()
        self._lbl.setFixedSize(w, h)
        self._lbl.setStyleSheet("background:#0d0d0d; border:1px solid #2a2a2a;")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(f"font-size:{FONT['body']}pt; color:#666; letter-spacing:1px;")
        self._stats = QLabel("")
        self._stats.setAlignment(Qt.AlignCenter)
        self._stats.setStyleSheet(f"font-family:Menlo,monospace; font-size:{FONT['body']}pt; color:#666;")
        layout.addWidget(self._lbl)
        layout.addWidget(self._title)
        layout.addWidget(self._stats)

    def show_array(self, data, mode="auto", cmap="gray"):
        if data is None:
            return
        disp = to_display(data, mode=mode)
        if cmap != "gray" and disp.ndim == 2:
            disp = apply_colormap(disp, cmap)
        if disp.ndim == 2:
            h, w = disp.shape
            qi = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = disp.shape[:2]
            qi = QImage(disp.tobytes(), w, h, w*3, QImage.Format_RGB888)
        sz  = self._lbl.size()
        pix = QPixmap.fromImage(qi).scaled(sz, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation)
        self._lbl.setPixmap(pix)
        self._stats.setText(
            f"min {data.min():.3g}   max {data.max():.3g}   "
            f"μ {data.mean():.3g}")

    def set_title(self, t):
        self._title.setText(t)

    def clear(self):
        """Reset the pane to a blank state (no image, no stats)."""
        self._lbl.setPixmap(QPixmap())
        self._lbl.setText("")
        self._stats.setText("")
