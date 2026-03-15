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

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        # Scale pad with H//5 so shorter charts (e.g. 166 px) don't waste
        # nearly half their height on margins.  Floor at 20 px to keep limit
        # line labels readable; ceiling at 36 px for tall charts.
        pad = max(20, min(36, H // 5))
        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        vals = [v for v in list(self._actual)+list(self._target) if v is not None]

        if not vals:
            # No data yet — draw a subtle placeholder so the widget doesn't
            # appear broken (plain black rectangle) on Windows or when hardware
            # is disconnected.
            p.setPen(QColor(40, 40, 40))
            p.setFont(mono_font(11))
            p.drawText(self.rect(), Qt.AlignCenter, "No data")
            p.end()
            return

        # Y-range: based on actual/target data only with a tight margin.
        # Previously the hard limits (-20° / 85°) were included in the range,
        # compressing the data traces into a tiny band.  A ±5°C minimum margin
        # (half the previous ±10°C) keeps the chart zoomed in on the actual
        # operating region, doubling pixel density so small fluctuations (e.g.
        # ±0.05°C when a TEC is locked) are clearly visible.
        data_span = max(vals) - min(vals)
        # 15% breathing room on each side, minimum ±5°C.
        # Using data_span * 2 would inflate the Y-range 3× during a temperature
        # ramp, pushing step=100 and leaving only 2-3 visible gridlines.
        margin = max(data_span * 0.15, 5.0)
        lo   = min(vals) - margin
        hi   = max(vals) + margin
        span = max(hi - lo, 1.0)

        def tx(i): return int(pad + i/(self.HISTORY-1)*(W-2*pad))
        def ty(v): return int(H-pad-(v-lo)/span*(H-2*pad))

        # Grid — pick the smallest "nice" step where consecutive labels are
        # at least 19 px apart (14 px font + 5 px gap).  Checking px/step
        # directly avoids the float boundary bug where span=10.03 with
        # max_labels=5 gives _raw=2.006, skipping step=2 → step=5 (3 lines).
        _inner = H - 2 * pad
        for step in [1, 2, 5, 10, 20, 50, 100, 200]:
            if _inner * step / span >= 19:
                break
        else:
            step = int(span) + 1
        t = (int(lo/step)-1)*step
        p.setFont(mono_font(11))
        while t <= hi+step:
            y = ty(t)
            if pad <= y <= H-pad:
                p.drawLine(pad, y, W-pad, y)
                p.setPen(QPen(QColor(80,80,80), 1))
                p.drawText(2, y+4, f"{t:.0f}°")
                p.setPen(QPen(QColor(35,35,35), 1))
            t += step

        # ── Alarm limit lines ─────────────────────────────────────────
        if self._temp_min is not None or self._temp_max is not None:
            dash = [6, 4]
            for limit, color, warn_offset in [
                (self._temp_min, QColor(255,68,68),   +self._warn_margin),
                (self._temp_max, QColor(255,68,68),   -self._warn_margin),
            ]:
                if limit is None:
                    continue
                # Hard limit — dashed red
                pen = QPen(QColor(255, 68, 68), 1, Qt.DashLine)
                p.setPen(pen)
                y = ty(limit)
                if 0 <= y <= H:
                    p.drawLine(pad, y, W-pad, y)
                    p.setFont(mono_font(10))
                    p.setPen(QPen(QColor(255, 100, 100), 1))
                    is_min = warn_offset > 0
                    label  = f"{'min' if is_min else 'max'} {limit:.0f}°"
                    # Draw min label BELOW its line, max label ABOVE its line.
                    # This keeps both labels away from the centre of the chart
                    # and prevents them collapsing together when the widget is
                    # near its minimum height.
                    label_y = (y + 12) if is_min else (y - 2)
                    p.drawText(pad + 2, label_y, label)

                # Warning zone — dashed amber
                warn_limit = limit + warn_offset
                pen_w = QPen(QColor(255, 153, 0), 1, Qt.DotLine)
                p.setPen(pen_w)
                yw = ty(warn_limit)
                if 0 <= yw <= H:
                    p.drawLine(pad, yw, W-pad, yw)

        # ── Temperature traces ────────────────────────────────────────
        for series, col in [(self._actual, QColor(0,212,170)),
                             (self._target, QColor(255,170,68))]:
            p.setPen(QPen(col, 1))
            prev = None
            for i, v in enumerate(series):
                if v is None: prev = None; continue
                x, y = tx(i), ty(v)
                if prev: p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # Legend — 16 px row height so the text (≈13 px tall) never
        # overlaps the line below it (was 12 px, causing visual bleed).
        p.setPen(QPen(QColor(0,212,170), 1))
        p.drawLine(W-110, 10, W-95, 10)
        p.setPen(QPen(QColor(100,100,100), 1))
        p.drawText(W-90, 14, "actual")
        p.setPen(QPen(QColor(255,170,68), 1))
        p.drawLine(W-110, 26, W-95, 26)
        p.setPen(QPen(QColor(100,100,100), 1))
        p.drawText(W-90, 30, "target")
        p.end()
