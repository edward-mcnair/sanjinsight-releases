"""
ui/widgets/segmented_control.py  —  Pill-style segmented control

Renders as a rounded-rect track with a sliding accent-coloured pill
behind the active segment.  Matches the sidebar _ModePill aesthetic.

Usage
-----
    seg = SegmentedControl(["Auto", "Dark", "Light"])
    seg.set_index(0)
    seg.selection_changed.connect(lambda idx: ...)
"""
from __future__ import annotations

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtGui     import QColor, QPainter, QPainterPath, QCursor
from PyQt5.QtWidgets import QWidget, QSizePolicy

from ui.theme      import PALETTE, FONT as _FONT
from ui.font_utils import sans_font as _sans_font

# ── Palette helpers (read at paint-time) ────────────────────────────
def _BG():         return PALETTE['surface']
def _ACCENT():     return PALETTE['accent']
def _TEXT_ON():    return PALETTE['textOnAccent']
def _TEXT_DIM():   return PALETTE['textDim']
def _TEXT_NORM():  return PALETTE['text']
def _BORDER():     return PALETTE['border']


class SegmentedControl(QWidget):
    """Pill-style N-segment toggle matching the sidebar mode pill."""

    selection_changed = pyqtSignal(int)   # emits selected index

    def __init__(self, labels: list[str], *, seg_width: int = 80,
                 height: int = 28, parent: QWidget | None = None):
        super().__init__(parent)
        self._labels    = list(labels)
        self._sel       = 0
        self._hover_idx = -1

        total_w = seg_width * len(labels)
        self.setFixedSize(total_w, height)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ── Public API ───────────────────────────────────────────────────
    def index(self) -> int:
        return self._sel

    def set_index(self, idx: int) -> None:
        idx = max(0, min(len(self._labels) - 1, idx))
        if idx != self._sel:
            self._sel = idx
            self.update()

    def labels(self) -> list[str]:
        return list(self._labels)

    # ── Mouse handling ───────────────────────────────────────────────
    def _idx_at(self, x: int) -> int:
        seg_w = self.width() / len(self._labels)
        return max(0, min(len(self._labels) - 1, int(x / seg_w)))

    def mouseMoveEvent(self, e):
        idx = self._idx_at(e.x())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def leaveEvent(self, e):
        self._hover_idx = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self._idx_at(e.x())
            if idx != self._sel:
                self._sel = idx
                self.selection_changed.emit(idx)
                self.update()

    # ── Painting ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._labels)
        seg_w = w / n

        # Track background
        track = QPainterPath()
        track.addRoundedRect(0.5, 0.5, w - 1, h - 1, h / 2, h / 2)
        p.fillPath(track, QColor(_BG()))
        p.setPen(QColor(_BORDER()))
        p.drawPath(track)

        # Active segment pill
        pad = 2
        ax = self._sel * seg_w + pad
        aw = seg_w - 2 * pad
        ah = h - 2 * pad
        pill = QPainterPath()
        pill.addRoundedRect(ax, pad, aw, ah, ah / 2, ah / 2)
        p.fillPath(pill, QColor(_ACCENT()))

        # Labels
        font_size = _FONT.get("caption", 8)
        normal_font = _sans_font(font_size, bold=False)
        bold_font   = _sans_font(font_size, bold=True)

        for i, label in enumerate(self._labels):
            sx = i * seg_w
            if i == self._sel:
                p.setPen(QColor(_TEXT_ON()))
                p.setFont(bold_font)
            elif i == self._hover_idx:
                p.setPen(QColor(_TEXT_NORM()))
                p.setFont(normal_font)
            else:
                p.setPen(QColor(_TEXT_DIM()))
                p.setFont(normal_font)
            p.drawText(int(sx), 0, int(seg_w), h, Qt.AlignCenter, label)

        p.end()

    # ── Theme refresh ────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        """Trigger repaint with current PALETTE colours."""
        self.update()
