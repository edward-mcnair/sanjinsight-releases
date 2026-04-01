"""
ui/widgets/timing_diagram.py — QPainter-based timing diagram for SanjINSIGHT.

Renders two standard power-device characterization topologies:

  Double-Pulse / Pulsed-IV
  ─────────────────────────
  Strig / Ptrig / Mes.sampling / Switch / Voltage / Current
  (matches the BA2531D02 reference diagram)

  Pulsed RF
  ──────────
  Master trigger / Gate / Drain / RF / M1 / M2 / Drain voltage
  (matches the ANBD2510 reference diagram)

All geometry is computed from TimingDiagramParams — no static data.
Uses pure QPainter; no matplotlib or numpy dependency.

Public API
----------
    widget = TimingDiagramWidget(parent)
    widget.set_params(TimingDiagramParams(...))
    widget.export_png("/path/diagram.png")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from PyQt5.QtCore  import Qt, QRect, QPoint, QSize, QRectF
from PyQt5.QtGui   import (
    QPainter, QPen, QColor, QBrush, QFont,
    QPainterPath, QPolygon, QPixmap,
)
from PyQt5.QtWidgets import QWidget, QSizePolicy

from ui.theme import PALETTE, FONT as THEME_FONT


# ── Parameter dataclass ───────────────────────────────────────────────────────

@dataclass
class TimingDiagramParams:
    """
    All parameters that drive the timing diagram.

    Timing relationships
    --------------------
    period_us       : Total ON-window duration T (μs).  For Pulsed RF this is Tp.
    n_pulses        : Number of Ptrig pulses within T (Double-Pulse mode).
    duty_cycle      : Fraction of pulse-slot that the switch is ON (0.0–1.0).
    transient_mask_ns : Blanking after leading edge — samples ignored (ns).
    stop_blanking_ns  : Blanking before trailing edge — samples ignored (ns).
    bias_mode       : "pulsed" draws the green pulsed trace;
                      "constant" draws only the blue constant-level trace.
    bias_level_v    : Voltage level for the pulsed/constant bias trace.
    compliance_a    : Compliance / threshold shown as red dashed line on current row.
    sample_fracs    : Normalised positions (0=pulse-start, 1=pulse-end) of the
                      measurement-sampling arrows.  Applied to each non-last pulse.
    rf_duty         : RF burst fraction within Tp (Pulsed RF mode).
    gate_delay_frac : Gate leading-edge offset as fraction of Tp (Pulsed RF mode).
    m1_frac / m2_frac : M1/M2 window centres as fraction of Tp (Pulsed RF mode).
    """

    mode:               str   = "double_pulse"   # "double_pulse" | "pulsed_rf"

    # ── Timing ────────────────────────────────────────────────────────────────
    period_us:          float = 100.0
    n_pulses:           int   = 3
    duty_cycle:         float = 0.45

    # ── Blanking ──────────────────────────────────────────────────────────────
    transient_mask_ns:  float = 200.0
    stop_blanking_ns:   float = 100.0

    # ── Bias ──────────────────────────────────────────────────────────────────
    bias_mode:          str   = "pulsed"    # "constant" | "pulsed"
    bias_level_v:       float = 3.3
    compliance_a:       float = 2.0

    # ── Measurement sample positions (0–1 within each non-last pulse) ─────────
    sample_fracs: List[float] = field(
        default_factory=lambda: [0.35, 0.55, 0.75])

    # ── Pulsed-RF specific ────────────────────────────────────────────────────
    rf_duty:            float = 0.30
    gate_delay_frac:    float = 0.06
    m1_frac:            float = 0.15
    m2_frac:            float = 0.55


# ── Widget ────────────────────────────────────────────────────────────────────

class TimingDiagramWidget(QWidget):
    """
    Scalable QPainter-based timing diagram.

    The diagram redraws automatically when the widget is resized.
    Call set_params() to update parameters and redraw.
    """

    # ── Layout constants (pixels) ─────────────────────────────────────────────
    LM    = 112   # left margin — signal name labels
    RM    = 28    # right margin
    TM    = 16    # top margin
    BM    = 42    # bottom margin — time-axis labels
    ROW_H = 66    # pixel height of each signal row
    SIG_H = 36    # waveform amplitude within ROW_H (vertically centred)

    # ── Colours — read from PALETTE at paint time via properties ─────────────
    @property
    def _C_DIGITAL(self):
        return PALETTE['text']

    @property
    def _C_PULSED(self):
        return PALETTE['accent']

    @property
    def _C_CONST(self):
        return PALETTE['info']

    @property
    def _C_CURRENT(self):
        return PALETTE['danger']

    @property
    def _C_ANNOT(self):
        return PALETTE['textDim']

    @property
    def _C_MASK(self):
        return PALETTE['warning'] + "30"

    @property
    def _C_M1(self):
        return PALETTE['info'] + "44"

    @property
    def _C_M2(self):
        return PALETTE['accent'] + "44"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._params = TimingDiagramParams()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(560, 400)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_params(self, params: TimingDiagramParams) -> None:
        self._params = params
        self.update()

    def sizeHint(self) -> QSize:
        n = 6 if self._params.mode == "double_pulse" else 7
        return QSize(900, self.TM + n * self.ROW_H + self.BM + 16)

    def export_png(self, path: str) -> bool:
        """Render the current diagram to a PNG file. Returns True on success."""
        px = self.grab()
        return px.save(path, "PNG")

    # ── paintEvent ────────────────────────────────────────────────────────────

    def paintEvent(self, event):                            # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        bg = PALETTE['bg']
        p.fillRect(self.rect(), QColor(bg))

        # Thin vertical separator between label column and plot area
        sep_x = self.LM - 2
        pen = QPen(QColor(PALETTE['border']), 1)
        p.setPen(pen)
        n_rows = 6 if self._params.mode == "double_pulse" else 7
        p.drawLine(sep_x, self.TM,
                   sep_x, self.TM + n_rows * self.ROW_H)

        if self._params.mode == "double_pulse":
            self._paint_double_pulse(p)
        else:
            self._paint_pulsed_rf(p)
        p.end()

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _pw(self) -> int:
        """Plot width (pixels)."""
        return max(10, self.width() - self.LM - self.RM)

    def _x(self, t: float) -> int:
        """Normalised time [0,1] → x pixel."""
        return int(self.LM + t * self._pw())

    def _y(self, row: int, v: float) -> int:
        """row index, normalised value [0=low, 1=high] → y pixel."""
        top = self.TM + row * self.ROW_H + (self.ROW_H - self.SIG_H) // 2
        return int(top + (1.0 - v) * self.SIG_H)

    def _row_mid(self, row: int) -> int:
        return self.TM + row * self.ROW_H + self.ROW_H // 2

    # ── Double-Pulse / Pulsed-IV renderer ────────────────────────────────────

    def _paint_double_pulse(self, p: QPainter):
        pr = self._params

        # Normalised geometry
        t_on   = 0.08          # Strig rise
        t_off  = 0.89          # Strig fall
        t_span = t_off - t_on  # ON window (normalised)
        spc    = t_span / max(pr.n_pulses, 1)     # slot per pulse
        pw_n   = spc * min(max(pr.duty_cycle, 0.05), 0.85)  # pulse width

        pulses: List[Tuple[float, float]] = []
        for i in range(pr.n_pulses):
            rise = t_on + i * spc + spc * 0.10
            fall = rise + pw_n
            pulses.append((rise, fall))

        # Nothing to draw without at least one pulse — draw only the time axis
        # and return to avoid IndexError on pulses[0] accesses below.
        if not pulses:
            self._label(p, "Strig", 0)
            self._time_axis(p, pr.period_us)
            return

        # Blanking widths in normalised coords
        period_ns    = pr.period_us * 1000.0
        per_slot_ns  = period_ns / max(pr.n_pulses, 1)
        mask_n  = min(pr.transient_mask_ns / period_ns * t_span,
                      pw_n * 0.4)
        stop_n  = min(pr.stop_blanking_ns  / period_ns * t_span,
                      pw_n * 0.3)

        # ── Row 0: Strig ─────────────────────────────────────────────────────
        row = 0
        self._label(p, "Strig", row)
        self._digital(p, row, [
            (0, 0), (t_on, 0), (t_on, 1),
            (t_off, 1), (t_off, 0), (1.0, 0)
        ], self._C_DIGITAL)
        tc = self._C_ANNOT
        self._text(p, self._x(t_on * 0.5),       self._row_mid(row),    "OFF", tc, center=True)
        self._text(p, self._x((t_on+t_off)*0.5), self._y(row, 1) - 8,   "ON",  tc, center=True)
        self._text(p, self._x((t_off+1.0)*0.5),  self._row_mid(row),    "OFF", tc, center=True)
        # T double-arrow
        self._harrow(p,
                     self._x(t_on), self._x(t_off),
                     self.TM + self.ROW_H - 10,
                     "T", self._C_ANNOT)

        # ── Row 1: Ptrig ─────────────────────────────────────────────────────
        row = 1
        self._label(p, "Ptrig", row)
        pts = [(0, 0)]
        for (r, f) in pulses:
            pts += [(r, 0), (r, 1), (f, 1), (f, 0)]
        pts.append((1.0, 0))
        self._digital(p, row, pts, self._C_DIGITAL)

        # ── Row 2: Mes. sampling ─────────────────────────────────────────────
        row = 2
        self._label(p, "Mes.\nsampling", row)
        for pi, (r, f) in enumerate(pulses[:-1]):
            usable = (f - stop_n) - (r + mask_n)
            if usable <= 0.004:
                continue
            for sf in pr.sample_fracs:
                t_s = r + mask_n + sf * usable
                self._up_arrow(p,
                               self._x(t_s),
                               self._y(row, 0.08),
                               self.SIG_H // 2 + 4,
                               QColor(self._C_DIGITAL))

        # ── Row 3: Switch ─────────────────────────────────────────────────────
        row = 3
        self._label(p, "switch", row)
        # Constant level — blue dashed
        if pr.bias_mode == "constant":
            y_c = self._y(row, 0.76)
            p.setPen(QPen(QColor(self._C_CONST), 1.8, Qt.SolidLine))
            p.drawLine(self._x(t_on), y_c, self._x(t_off), y_c)
            self._text(p, self._x(t_on + 0.02), y_c - 9,
                       "constant level", self._C_CONST, small=True)
        else:
            y_c = self._y(row, 0.76)
            p.setPen(QPen(QColor(self._C_CONST), 1.4, Qt.DashLine))
            p.drawLine(self._x(t_on), y_c, self._x(t_off), y_c)
            self._text(p, self._x(t_on + 0.02), y_c - 9,
                       "constant level", self._C_CONST, small=True)
            # Pulsed — green solid
            pts2 = [(0, 0)]
            for (r, f) in pulses:
                pts2 += [(r, 0), (r, 1), (f, 1), (f, 0)]
            pts2.append((1.0, 0))
            self._digital(p, row, pts2, self._C_PULSED)
            self._text(p,
                       self._x(pulses[0][0] + 0.01),
                       self._y(row, 1) + 13,
                       "Pulsed", self._C_PULSED, small=True)

        # ── Row 4: Voltage ────────────────────────────────────────────────────
        row = 4
        self._label(p, "voltage", row)
        y_c = self._y(row, 0.73)
        p.setPen(QPen(QColor(self._C_CONST), 1.4, Qt.DashLine))
        p.drawLine(self._x(t_on), y_c, self._x(t_off), y_c)
        self._text(p, self._x(t_on + 0.02), y_c - 9,
                   "constant level", self._C_CONST, small=True)
        if pr.bias_mode == "pulsed":
            path = QPainterPath()
            path.moveTo(self._x(0), self._y(row, 0.02))
            path.lineTo(self._x(t_on), self._y(row, 0.02))
            for i, (r, f) in enumerate(pulses):
                path.lineTo(self._x(r),           self._y(row, 0.02))
                path.lineTo(self._x(r + 0.004),   self._y(row, 0.95))  # fast rise
                path.lineTo(self._x(r + 0.012),   self._y(row, 0.82))  # slight droop
                path.lineTo(self._x(f - 0.004),   self._y(row, 0.82))
                path.lineTo(self._x(f),            self._y(row, 0.02))
            path.lineTo(self._x(1.0), self._y(row, 0.02))
            p.setPen(QPen(QColor(self._C_PULSED), 1.8))
            p.drawPath(path)
            self._text(p,
                       self._x(pulses[0][0] + 0.01),
                       self._y(row, 1) + 13,
                       "Pulsed", self._C_PULSED, small=True)

        # ── Row 5: Current ────────────────────────────────────────────────────
        row = 5
        self._label(p, "current", row)
        # Shaded mask + stop regions
        for (r, f) in pulses:
            me = r + mask_n
            if me < f:
                p.fillRect(QRectF(self._x(r), self._y(row, 1) - 2,
                                  self._x(me) - self._x(r), self.SIG_H + 4),
                           QColor(self._C_MASK))
            ss = f - stop_n
            if ss > r:
                p.fillRect(QRectF(self._x(ss), self._y(row, 1) - 2,
                                  self._x(f) - self._x(ss), self.SIG_H + 4),
                           QColor(self._C_MASK))
        # Threshold dashed line
        thresh_y = self._y(row, 0.60)
        p.setPen(QPen(QColor(self._C_CURRENT), 1.0, Qt.DashLine))
        p.drawLine(self._x(0.0), thresh_y, self._x(1.0), thresh_y)
        self._text(p, self._x(0.50), thresh_y - 7,
                   "threshold", self._C_CURRENT, small=True)
        # Current waveform
        path = QPainterPath()
        path.moveTo(self._x(0), self._y(row, 0.02))
        path.lineTo(self._x(t_on - 0.004), self._y(row, 0.02))
        for gi, (r, f) in enumerate(pulses):
            path.lineTo(self._x(r - 0.002),  self._y(row, 0.02))
            path.lineTo(self._x(r + 0.003),  self._y(row, 1.02))  # spike
            path.lineTo(self._x(r + 0.007),  self._y(row, 0.88))
            path.lineTo(self._x(r + 0.016),  self._y(row, 0.76))  # settle
            path.lineTo(self._x(f - stop_n - 0.003), self._y(row, 0.45))
            path.lineTo(self._x(f - 0.003),  self._y(row, 0.64))  # pre-off spike
            if gi == len(pulses) - 1:
                # Last pulse — ringing after turn-off
                path.lineTo(self._x(f + 0.006),  self._y(row, 0.28))
                path.lineTo(self._x(f + 0.014),  self._y(row, 0.08))
                path.lineTo(self._x(1.0),         self._y(row, 0.02))
            else:
                path.lineTo(self._x(f), self._y(row, 0.02))
        p.setPen(QPen(QColor(self._C_CURRENT), 1.8))
        p.drawPath(path)
        # "transient mask" bracket annotation (first pulse)
        if pulses:
            r0, f0 = pulses[0]
            brace_y = self._y(row, 0) + 11
            self._harrow(p, self._x(r0), self._x(r0 + mask_n), brace_y,
                         "transient mask", self._C_ANNOT)
        # "100ns stop" annotation (last pulse trailing edge)
        if pulses:
            lr, lf = pulses[-1]
            self._text(p,
                       self._x(lf + 0.012),
                       self._y(row, 0.50),
                       "100ns stop", PALETTE['warning'], small=True)

        # ── Time axis ─────────────────────────────────────────────────────────
        self._time_axis(p, 6, pr.period_us, pr.n_pulses)

    # ── Pulsed-RF renderer ────────────────────────────────────────────────────

    def _paint_pulsed_rf(self, p: QPainter):
        pr = self._params

        t_on   = 0.08
        t_off  = 0.88
        t_span = t_off - t_on

        g_rise = t_on + t_span * (0.05 + pr.gate_delay_frac)
        g_fall = min(g_rise + t_span * pr.rf_duty, t_off - t_span * 0.04)

        m_w  = t_span * 0.055                          # window width
        m1_t = t_on + t_span * pr.m1_frac
        m2_t = g_rise + (g_fall - g_rise) * 0.50

        tc = self._C_ANNOT

        # ── Row 0: Master trigger / Tp ─────────────────────────────────────
        row = 0
        self._label(p, "master\ntrigger", row)
        self._digital(p, row, [
            (0, 0), (t_on, 0), (t_on, 1), (t_on + 0.018, 1),
            (t_on + 0.018, 0), (1.0, 0)
        ], self._C_DIGITAL)
        self._harrow(p, self._x(t_on), self._x(t_off),
                     self.TM + self.ROW_H - 10, "Tp", tc)

        # ── Row 1: Gate ───────────────────────────────────────────────────
        row = 1
        self._label(p, "Gate", row)
        self._digital(p, row, [
            (0, 0), (g_rise, 0), (g_rise, 1), (g_fall, 1), (g_fall, 0), (1.0, 0)
        ], self._C_DIGITAL)
        # Gate delay arrow
        self._harrow(p,
                     self._x(t_on + 0.018),
                     self._x(g_rise),
                     self._y(row, 0) + 10,
                     "", tc)

        # ── Row 2: Drain ──────────────────────────────────────────────────
        row = 2
        self._label(p, "Drain", row)
        self._digital(p, row, [
            (0, 0), (t_on, 0), (t_on, 0.68),
            (g_rise, 0.68), (g_rise, 0.10),
            (g_fall, 0.10), (g_fall, 0.68),
            (t_off, 0.68), (t_off, 0), (1.0, 0)
        ], self._C_DIGITAL)

        # ── Row 3: RF burst ───────────────────────────────────────────────
        row = 3
        self._label(p, "RF", row)
        path = QPainterPath()
        path.moveTo(self._x(0), self._y(row, 0.02))
        path.lineTo(self._x(g_rise - 0.002), self._y(row, 0.02))
        n_cyc = max(4, int((g_fall - g_rise) * self._pw() / 16))
        cw    = (g_fall - g_rise) / n_cyc
        for i in range(n_cyc):
            t0 = g_rise + i * cw
            t1 = t0 + cw * 0.5
            t2 = t0 + cw
            path.lineTo(self._x(t0 + 0.001), self._y(row, 0.88))
            path.lineTo(self._x(t1 - 0.001), self._y(row, 0.88))
            path.lineTo(self._x(t1 + 0.001), self._y(row, 0.12))
            path.lineTo(self._x(t2 - 0.001), self._y(row, 0.12))
        path.lineTo(self._x(g_fall),   self._y(row, 0.02))
        path.lineTo(self._x(1.0),      self._y(row, 0.02))
        p.setPen(QPen(QColor(self._C_DIGITAL), 1.5))
        p.drawPath(path)

        # ── Row 4: M1 (quiescent measurement window) ──────────────────────
        row = 4
        self._label(p, "M1", row)
        self._measurement_window(p, row, m1_t, m_w, self._C_M1, QColor(self._C_CONST))

        # ── Row 5: M2 (pulsed measurement window) ─────────────────────────
        row = 5
        self._label(p, "M2", row)
        self._measurement_window(p, row, m2_t, m_w, self._C_M2, QColor(self._C_PULSED))

        # ── Row 6: Drain voltage ──────────────────────────────────────────
        row = 6
        self._label(p, "Drain\nvoltage", row)
        y_c = self._y(row, 0.74)
        p.setPen(QPen(QColor(self._C_CONST), 1.4, Qt.DashLine))
        p.drawLine(self._x(t_on), y_c, self._x(t_off), y_c)
        self._text(p, self._x(t_on + 0.02), y_c - 9,
                   "constant level", self._C_CONST, small=True)
        # Pulsed drain — drops during gate ON
        path = QPainterPath()
        path.moveTo(self._x(0), self._y(row, 0.02))
        path.lineTo(self._x(t_on),           self._y(row, 0.02))
        path.lineTo(self._x(g_rise - 0.004), self._y(row, 0.74))
        path.lineTo(self._x(g_rise),         self._y(row, 0.10))
        path.lineTo(self._x(g_fall),         self._y(row, 0.10))
        path.lineTo(self._x(g_fall + 0.004), self._y(row, 0.74))
        path.lineTo(self._x(t_off),          self._y(row, 0.74))
        path.lineTo(self._x(t_off),          self._y(row, 0.02))
        path.lineTo(self._x(1.0),            self._y(row, 0.02))
        p.setPen(QPen(QColor(self._C_PULSED), 1.8))
        p.drawPath(path)
        self._text(p, self._x(g_rise + 0.01), self._y(row, 0) - 4,
                   "Pulsed", self._C_PULSED, small=True)

        # ── Time axis ─────────────────────────────────────────────────────
        self._time_axis(p, 7, pr.period_us, 1)

    # ── Drawing primitives ────────────────────────────────────────────────────

    def _label(self, p: QPainter, text: str, row: int) -> None:
        """Signal name label in the left margin, right-aligned, vertically centred."""
        color = QColor(PALETTE['text'])
        pt    = max(7, THEME_FONT.get("caption", 9) - 1)
        font  = QFont("Menlo, Consolas, monospace", pt)
        p.setFont(font)
        p.setPen(QPen(color))
        rect = QRect(4, self.TM + row * self.ROW_H, self.LM - 8, self.ROW_H)
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignRight, text)

    def _digital(self, p: QPainter, row: int,
                 pts: List[Tuple[float, float]],
                 color, pen_w: float = 1.8) -> None:
        """Step waveform from list of (t_norm, v_norm) pairs."""
        if isinstance(color, str):
            color = QColor(color)
        pen = QPen(color, pen_w)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(self._x(pts[0][0]), self._y(row, pts[0][1]))
        for t, v in pts[1:]:
            path.lineTo(self._x(t), self._y(row, v))
        p.drawPath(path)

    def _up_arrow(self, p: QPainter, cx: int, base_y: int,
                  length: int, color: QColor) -> None:
        """Upward arrow (measurement marker)."""
        tip_y = base_y - length
        p.setPen(QPen(color, 1.5))
        p.drawLine(cx, base_y, cx, tip_y)
        ah = 6
        pts = [QPoint(cx, tip_y),
               QPoint(cx - ah // 2, tip_y + ah),
               QPoint(cx + ah // 2, tip_y + ah)]
        p.setBrush(QBrush(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon(pts))
        p.setBrush(Qt.NoBrush)

    def _harrow(self, p: QPainter, x1: int, x2: int, ay: int,
                label: str, color_str: str) -> None:
        """Horizontal double-headed arrow with label."""
        if x2 - x1 < 4:
            return
        color = QColor(color_str)
        p.setPen(QPen(color, 1.0))
        p.drawLine(x1, ay, x2, ay)
        p.drawLine(x1, ay - 4, x1, ay + 4)   # tick
        p.drawLine(x2, ay - 4, x2, ay + 4)   # tick
        ah = 5
        for tip_x, sign in ((x1, +1), (x2, -1)):
            pts = [QPoint(tip_x, ay),
                   QPoint(tip_x + sign * ah, ay - ah // 2),
                   QPoint(tip_x + sign * ah, ay + ah // 2)]
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygon(pts))
        p.setBrush(Qt.NoBrush)
        if label:
            pt   = max(7, THEME_FONT.get("caption", 9))
            font = QFont("Arial", pt)
            font.setItalic(True)
            p.setFont(font)
            p.setPen(QPen(color))
            mid = (x1 + x2) // 2
            p.drawText(mid - 24, ay - 15, 48, 14, Qt.AlignCenter, label)

    def _text(self, p: QPainter, x: int, y: int, text: str,
              color: str, center: bool = False, small: bool = False) -> None:
        pt   = max(7, THEME_FONT.get("caption", 9) - (1 if small else 0))
        font = QFont("Arial", pt)
        p.setFont(font)
        p.setPen(QPen(QColor(color)))
        w = 130
        if center:
            p.drawText(x - w // 2, y - 8, w, 16, Qt.AlignCenter, text)
        else:
            p.drawText(x, y - 8, w, 16, Qt.AlignLeft | Qt.AlignVCenter, text)

    def _measurement_window(self, p: QPainter, row: int, t_centre: float,
                             t_width: float, fill_hex: str,
                             border_color: QColor) -> None:
        """Shaded rectangle representing a measurement window."""
        x1  = self._x(t_centre - t_width / 2)
        x2  = self._x(t_centre + t_width / 2)
        y_t = self._y(row, 1) - 2
        ht  = self.SIG_H + 4
        rect = QRectF(x1, y_t, x2 - x1, ht)
        p.fillRect(rect, QColor(fill_hex))
        p.setPen(QPen(border_color, 1.4))
        p.drawRect(rect.toRect())

    def _time_axis(self, p: QPainter, n_rows: int,
                   period_us: float, n_pulses: int) -> None:
        ax_y = self.TM + n_rows * self.ROW_H + 8
        dim  = QColor(PALETTE['textDim'])
        bdr  = QColor(PALETTE['border'])
        # Axis line
        p.setPen(QPen(bdr, 1.0))
        p.drawLine(self.LM, ax_y, self.LM + self._pw(), ax_y)
        # Label
        pt   = max(7, THEME_FONT.get("caption", 9) - 1)
        font = QFont("Arial", pt)
        p.setFont(font)
        p.setPen(QPen(dim))
        lbl = (f"Period T = {period_us:.1f} μs  ·  "
               f"{n_pulses} pulse{'s' if n_pulses != 1 else ''} per window")
        p.drawText(self.LM, ax_y + 6, self._pw(), 20, Qt.AlignCenter, lbl)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        bg = PALETTE['bg']
        self.setStyleSheet(f"TimingDiagramWidget {{ background: {bg}; }}")
        self.update()
