"""
ui/widgets/temp_plot.py

TempPlot — a custom QWidget that draws a rolling temperature history chart
with actual vs target traces, alarm limit lines, and warning zones.
"""

from __future__ import annotations

import collections
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import QPainter, QColor, QPen, QFont

from ui.theme import PALETTE
from ui.font_utils import mono_font


class TempPlot(QWidget):
    HISTORY = 120

    def __init__(self, h=140):
        super().__init__()
        self.setFixedHeight(h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._actual = collections.deque([None]*self.HISTORY, maxlen=self.HISTORY)
        self._target = collections.deque([None]*self.HISTORY, maxlen=self.HISTORY)
        self._temp_min:    float | None = None
        self._temp_max:    float | None = None
        self._warn_margin: float        = 5.0

    def push(self, actual, target):
        self._actual.append(actual)
        self._target.append(target)
        self.update()

    def set_limits(self, temp_min: float, temp_max: float,
                   warn_margin: float = 5.0):
        self._temp_min    = temp_min
        self._temp_max    = temp_max
        self._warn_margin = warn_margin
        self.update()

    def _apply_styles(self):
        """Re-apply styles from PALETTE. Called on theme switch."""
        self.update()  # trigger repaint with new palette colours

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        # Scale pad with H//5 so shorter charts (e.g. 166 px) don't waste
        # nearly half their height on margins.  Floor at 20 px to keep limit
        # line labels readable; ceiling at 36 px for tall charts.
        pad = max(20, min(36, H // 5))
        p.fillRect(0, 0, W, H, QColor(PALETTE['canvas']))

        vals = [v for v in list(self._actual)+list(self._target) if v is not None]

        if not vals:
            # No data yet — draw a subtle placeholder so the widget doesn't
            # appear broken (plain black rectangle) on Windows or when hardware
            # is disconnected.
            p.setPen(QColor(PALETTE['canvasGrid']))
            p.setFont(mono_font(11))
            p.drawText(self.rect(), Qt.AlignCenter, "No data")
            p.end()
            return

        # Y-range: based on actual/target data only with a tight margin.
        data_span = max(vals) - min(vals)
        # 15% breathing room on each side, minimum ±5°C.
        margin = max(data_span * 0.15, 5.0)
        lo   = min(vals) - margin
        hi   = max(vals) + margin
        span = max(hi - lo, 1.0)

        def tx(i): return int(pad + i/(self.HISTORY-1)*(W-2*pad))
        def ty(v): return int(H-pad-(v-lo)/span*(H-2*pad))

        # Grid — pick the smallest "nice" step where consecutive labels are
        # at least 19 px apart (14 px font + 5 px gap).
        _inner = H - 2 * pad
        for step in [1, 2, 5, 10, 20, 50, 100, 200]:
            if _inner * step / span >= 19:
                break
        else:
            step = int(span) + 1
        t = (int(lo/step)-1)*step
        grid_color = QColor(PALETTE['canvasGrid'])
        text_color = QColor(PALETTE['canvasText'])
        p.setFont(mono_font(11))
        while t <= hi+step:
            y = ty(t)
            if pad <= y <= H-pad:
                p.setPen(QPen(grid_color, 1))
                p.drawLine(pad, y, W-pad, y)
                p.setPen(QPen(text_color, 1))
                p.drawText(2, y+4, f"{t:.0f}°")
            t += step

        # ── Alarm limit lines ─────────────────────────────────────────
        danger_color = QColor(PALETTE['danger'])
        warning_color = QColor(PALETTE['warning'])
        if self._temp_min is not None or self._temp_max is not None:
            for limit, warn_offset in [
                (self._temp_min,  +self._warn_margin),
                (self._temp_max,  -self._warn_margin),
            ]:
                if limit is None:
                    continue
                # Hard limit — dashed red
                pen = QPen(danger_color, 1, Qt.DashLine)
                p.setPen(pen)
                y = ty(limit)
                if 0 <= y <= H:
                    p.drawLine(pad, y, W-pad, y)
                    p.setFont(mono_font(10))
                    p.setPen(QPen(danger_color, 1))
                    is_min = warn_offset > 0
                    label  = f"{'min' if is_min else 'max'} {limit:.0f}°"
                    # Draw min label BELOW its line, max label ABOVE its line.
                    label_y = (y + 12) if is_min else (y - 2)
                    p.drawText(pad + 2, label_y, label)

                # Warning zone — dashed amber
                warn_limit = limit + warn_offset
                pen_w = QPen(warning_color, 1, Qt.DotLine)
                p.setPen(pen_w)
                yw = ty(warn_limit)
                if 0 <= yw <= H:
                    p.drawLine(pad, yw, W-pad, yw)

        # ── Temperature traces ────────────────────────────────────────
        actual_color = QColor(PALETTE['accent'])
        target_color = QColor(PALETTE['warning'])
        for series, col in [(self._actual, actual_color),
                             (self._target, target_color)]:
            p.setPen(QPen(col, 1))
            prev = None
            for i, v in enumerate(series):
                if v is None: prev = None; continue
                x, y = tx(i), ty(v)
                if prev: p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # Legend — 16 px row height so the text (approximately 13 px tall) never
        # overlaps the line below it.
        legend_text = QColor(PALETTE['canvasText'])
        p.setPen(QPen(actual_color, 1))
        p.drawLine(W-110, 10, W-95, 10)
        p.setPen(QPen(legend_text, 1))
        p.drawText(W-90, 14, "actual")
        p.setPen(QPen(target_color, 1))
        p.drawLine(W-110, 26, W-95, 26)
        p.setPen(QPen(legend_text, 1))
        p.drawText(W-90, 30, "target")
        p.end()
