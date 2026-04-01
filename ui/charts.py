"""
ui/charts.py

Themed chart widgets built on PyQtGraph.

All widgets auto-apply PALETTE and FONT at construction and when
``_apply_styles()`` is called on a theme switch.

Graceful fallback
-----------------
If pyqtgraph is not installed every widget falls back to a placeholder label.
Install with::

    pip install pyqtgraph>=0.13.3

Available widgets
-----------------
StyledPlotWidget         — pg.PlotWidget subclass; base for all charts below
CalibrationQualityChart  — R² histogram + C_T histogram side-by-side
AnalysisHistogramChart   — dT-value histogram with threshold / verdict lines
TransientTraceChart      — mean ΔR/R vs delay time (replaces TransientCurve)
SessionTrendChart        — SNR / temperature trend across saved sessions
dTSparklineWidget        — rolling ~2-minute dT history strip
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from typing import List, Optional, Sequence

import numpy as np

log = logging.getLogger(__name__)

# ── PyQtGraph — graceful import ───────────────────────────────────────────────
try:
    import pyqtgraph as pg
    pg.setConfigOption("antialias",  True)
    pg.setConfigOption("useOpenGL",  False)   # stable on all platforms/GPUs
    _PG_OK = True
except ImportError:
    pg = None           # type: ignore[assignment]
    _PG_OK = False
    log.warning(
        "ui.charts: pyqtgraph not found — charts will show placeholders.\n"
        "  Install:  pip install pyqtgraph>=0.13.3"
    )

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui  import QFont, QColor

from ui.theme import FONT, PALETTE


# ─────────────────────────────────────────────────────────────────────────────
#  PyQtGraph global foreground / background
# ─────────────────────────────────────────────────────────────────────────────

def refresh_pyqtgraph_globals() -> None:
    """Re-apply PALETTE colours to the pyqtgraph global config options.

    Called once at startup and again from ``MainWindow._swap_visual_theme``
    whenever the user switches between dark / light themes.
    """
    if not _PG_OK:
        return
    pg.setConfigOption("foreground", PALETTE['textDim'])
    pg.setConfigOption("background", PALETTE['bg'])


# Apply once at import time so the first widgets created get the right colours.
refresh_pyqtgraph_globals()


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _placeholder(msg: str = "Install pyqtgraph for charts\npip install pyqtgraph>=0.13.3") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lbl = QLabel(msg)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color:{PALETTE['textDim']};"
        f"font-size:{FONT.get('body',9)}pt;"
    )
    lay.addWidget(lbl)
    return w


def _configure_plot(pw: "pg.PlotWidget",
                    x_label: str = "",
                    y_label: str = "") -> None:
    """Apply current PALETTE + FONT to a PlotWidget in-place."""
    if not _PG_OK:
        return
    bg        = PALETTE['bg']
    bdr       = PALETTE['border']
    text_dim  = PALETTE['textDim']
    pw.setBackground(bg)

    axis_pen   = pg.mkPen(color=bdr,      width=1)
    text_pen   = pg.mkPen(color=text_dim)
    tick_font  = QFont("Menlo") if sys.platform == "darwin" else QFont("Consolas")
    tick_font.setStyleHint(QFont.Monospace)
    tick_font.setPointSize(FONT.get("caption", 9))

    for ax_name in ("left", "bottom"):
        ax = pw.getAxis(ax_name)
        ax.setPen(axis_pen)
        ax.setTextPen(text_pen)
        ax.setStyle(tickFont=tick_font)

    pw.showGrid(x=True, y=True, alpha=0.18)
    lbl_style = {"color": text_dim, "font-size": f"{FONT.get('caption',9)}pt"}
    if x_label:
        pw.setLabel("bottom", x_label, **lbl_style)
    if y_label:
        pw.setLabel("left",   y_label, **lbl_style)


# ─────────────────────────────────────────────────────────────────────────────
#  StyledPlotWidget — base
# ─────────────────────────────────────────────────────────────────────────────

if _PG_OK:
    _PlotBase = pg.PlotWidget
else:
    _PlotBase = QWidget


class StyledPlotWidget(_PlotBase):  # type: ignore[valid-type]
    """
    ``pg.PlotWidget`` with PALETTE/FONT pre-applied.

    Behaves identically to ``pg.PlotWidget`` when pyqtgraph is installed.
    Falls back to a plain placeholder label otherwise — so host tabs never
    need to guard against ImportError.
    """

    def __init__(self, x_label: str = "", y_label: str = "", **kwargs):
        if not _PG_OK:
            super().__init__()
            lay = QVBoxLayout(self)
            lbl = QLabel("Install pyqtgraph\npip install pyqtgraph>=0.13.3")
            lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)
            return
        super().__init__(**kwargs)
        _configure_plot(self, x_label, y_label)

    def _apply_styles(self) -> None:
        if _PG_OK:
            _configure_plot(self)


# ─────────────────────────────────────────────────────────────────────────────
#  CalibrationQualityChart
# ─────────────────────────────────────────────────────────────────────────────

class CalibrationQualityChart(QWidget):
    """
    Side-by-side histograms: R² distribution (left) and C_T distribution
    (right), both for valid pixels only.

    Also shows an optional temperature → mean-signal calibration curve when
    ``CalibrationResult.temps_c`` / ``.mean_signals`` are populated.

    Parameters
    ----------
    show_curve : bool
        If True a third panel (calibration curve) is appended.
    """

    def __init__(self, parent=None, show_curve: bool = True):
        super().__init__(parent)
        self._show_curve = show_curve and _PG_OK

        if not _PG_OK:
            lay = QVBoxLayout(self)
            lay.addWidget(_placeholder())
            return

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ── Left: R² histogram ─────────────────────────────────────────────
        self._r2_plot = StyledPlotWidget(x_label="R² fit quality",
                                         y_label="Pixel count")
        self._r2_plot.setMinimumHeight(140)
        self._r2_bar  = None   # pg.BarGraphItem — created in update_data
        self._r2_thresh_line = None
        splitter.addWidget(self._r2_plot)

        # ── Centre: C_T histogram ──────────────────────────────────────────
        self._ct_plot = StyledPlotWidget(x_label="C_T  [×10⁻⁴  K⁻¹]",
                                         y_label="Pixel count")
        self._ct_plot.setMinimumHeight(140)
        self._ct_bar  = None
        splitter.addWidget(self._ct_plot)

        # ── Right: calibration curve (optional) ───────────────────────────
        if self._show_curve:
            self._curve_plot = StyledPlotWidget(x_label="Temperature  (°C)",
                                                 y_label="Mean ΔR/R")
            self._curve_plot.setMinimumHeight(140)
            self._curve_scatter = None
            self._curve_line    = None
            splitter.addWidget(self._curve_plot)

        lay.addWidget(splitter)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def update_data(self, result) -> None:
        """
        Refresh all panels from a ``CalibrationResult``.

        Safe to call even when pyqtgraph is not installed.
        """
        if not _PG_OK or result is None:
            return

        accent   = PALETTE['accent']
        warning  = PALETTE['warning']
        danger   = PALETTE['danger']
        text_dim = PALETTE['textDim']

        mask = result.mask

        # ── R² histogram ──────────────────────────────────────────────────
        if result.r2_map is not None:
            r2_vals = result.r2_map[mask].ravel() if (mask is not None and mask.any()) \
                      else result.r2_map.ravel()
            r2_finite = r2_vals[np.isfinite(r2_vals)]
            if r2_finite.size > 0:
                counts, edges = np.histogram(r2_finite, bins=40, range=(0.0, 1.0))
                x_mid = (edges[:-1] + edges[1:]) / 2
                width = edges[1] - edges[0]

                # Colour bars: green ≥ 0.9, amber 0.8–0.9, red < 0.8
                brushes = []
                for v in x_mid:
                    if v >= 0.90:
                        brushes.append(pg.mkBrush(accent))
                    elif v >= 0.80:
                        brushes.append(pg.mkBrush(warning))
                    else:
                        brushes.append(pg.mkBrush(danger))

                self._r2_plot.clear()
                bg = pg.BarGraphItem(x=x_mid, height=counts, width=width * 0.9,
                                     brushes=brushes,
                                     pen=pg.mkPen(None))
                self._r2_plot.addItem(bg)

                # 0.80 threshold line
                line = pg.InfiniteLine(
                    pos=0.80, angle=90,
                    pen=pg.mkPen(color=warning, width=1, style=Qt.DashLine),
                    label="0.80 threshold",
                    labelOpts={"color": warning,
                               "position": 0.9})
                self._r2_plot.addItem(line)

                _add_text(self._r2_plot,
                          f"median R² = {float(np.median(r2_finite)):.3f}",
                          text_dim)

        # ── C_T histogram ─────────────────────────────────────────────────
        if result.ct_map is not None:
            ct_vals = result.ct_map[mask].ravel() if (mask is not None and mask.any()) \
                      else result.ct_map.ravel()
            ct_finite = ct_vals[np.isfinite(ct_vals)]
            if ct_finite.size > 0:
                # Scale to ×10⁻⁴ for readability
                ct_scaled = ct_finite * 1e4
                lo  = float(np.percentile(ct_scaled,  1))
                hi  = float(np.percentile(ct_scaled, 99))
                counts, edges = np.histogram(ct_scaled, bins=40,
                                              range=(lo, hi))
                x_mid  = (edges[:-1] + edges[1:]) / 2
                width  = edges[1] - edges[0]

                self._ct_plot.clear()
                bg = pg.BarGraphItem(x=x_mid, height=counts, width=width * 0.9,
                                     brush=pg.mkBrush(accent + "bb"),
                                     pen=pg.mkPen(None))
                self._ct_plot.addItem(bg)

                mu  = float(np.median(ct_scaled))
                std = float(np.std(ct_scaled))
                _add_text(self._ct_plot,
                          f"median = {mu:.2f}  σ = {std:.2f}  (×10⁻⁴ K⁻¹)",
                          text_dim)

        # ── Calibration curve (optional) ───────────────────────────────────
        if self._show_curve:
            temps   = getattr(result, "temps_c",      None)
            signals = getattr(result, "mean_signals",  None)
            if (temps is not None and signals is not None
                    and len(temps) >= 2):
                temps   = np.asarray(temps,   dtype=float)
                signals = np.asarray(signals, dtype=float)
                self._curve_plot.clear()

                # Scatter points
                scatter = pg.ScatterPlotItem(
                    x=temps, y=signals,
                    symbol="o", size=8,
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(accent))
                self._curve_plot.addItem(scatter)

                # Linear fit line
                coeffs = np.polyfit(temps, signals, 1)
                t_fit  = np.linspace(temps.min(), temps.max(), 100)
                y_fit  = np.polyval(coeffs, t_fit)
                self._curve_plot.plot(t_fit, y_fit,
                                      pen=pg.mkPen(color=text_dim, width=1,
                                                   style=Qt.DashLine))

                r2_fit = _r2_score(signals, np.polyval(coeffs, temps))
                _add_text(self._curve_plot,
                          f"linear  R² = {r2_fit:.4f}",
                          text_dim)

    def clear(self) -> None:
        if not _PG_OK:
            return
        for pw in (self._r2_plot, self._ct_plot):
            pw.clear()
        if self._show_curve:
            self._curve_plot.clear()

    def _apply_styles(self) -> None:
        if not _PG_OK:
            return
        for pw in (self._r2_plot, self._ct_plot):
            _configure_plot(pw)
        if self._show_curve:
            _configure_plot(self._curve_plot)


# ─────────────────────────────────────────────────────────────────────────────
#  AnalysisHistogramChart
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisHistogramChart(QWidget):
    """
    Histogram of ΔT values across all pixels in the analysis result frame,
    with vertical lines marking the threshold (and FAIL peak if present).

    Colour coding mirrors the verdict system:
      • bars below threshold  — neutral (textDim)
      • bars at/above threshold — warning / danger gradient

    ``update_result(result)`` accepts any object with:
      - ``dt_map``      np.ndarray (H, W) float32 — the temperature map
      - ``threshold_k`` float — active threshold
      - ``verdict``     str — PASS / WARNING / FAIL
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        if not _PG_OK:
            lay = QVBoxLayout(self)
            lay.addWidget(_placeholder())
            return

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._plot = StyledPlotWidget(x_label="ΔT  (°C)", y_label="Pixel count")
        self._plot.setFixedHeight(160)
        lay.addWidget(self._plot)

    # ------------------------------------------------------------------ #

    def update_result(self, result) -> None:
        if not _PG_OK or result is None:
            return

        dt_map   = getattr(result, "dt_map", None)
        if dt_map is None:
            # Try extracting directly from engine result dict-like attributes
            return

        threshold = float(getattr(result, "threshold_k", 1.0))
        verdict   = getattr(result, "verdict", "PASS")

        accent   = PALETTE['accent']
        warning  = PALETTE['warning']
        danger   = PALETTE['danger']
        text_dim = PALETTE['textDim']

        finite = dt_map[np.isfinite(dt_map)]
        if finite.size == 0:
            return

        lo = float(np.percentile(finite,  0.5))
        hi = float(np.percentile(finite, 99.5))
        counts, edges = np.histogram(finite, bins=60, range=(lo, hi))
        x_mid  = (edges[:-1] + edges[1:]) / 2
        width  = edges[1] - edges[0]

        # Per-bar colour: below threshold = neutral, above = warm
        brushes = []
        for v in x_mid:
            if v < threshold:
                brushes.append(pg.mkBrush(text_dim + "55"))
            elif v < threshold * 2:
                brushes.append(pg.mkBrush(warning + "cc"))
            else:
                brushes.append(pg.mkBrush(danger + "cc"))

        self._plot.clear()
        bg = pg.BarGraphItem(x=x_mid, height=counts, width=width * 0.92,
                             brushes=brushes, pen=pg.mkPen(None))
        self._plot.addItem(bg)

        # Threshold line
        tl = pg.InfiniteLine(
            pos=threshold, angle=90,
            pen=pg.mkPen(color=warning, width=2),
            label=f"threshold {threshold:.1f} °C",
            labelOpts={"color": warning, "position": 0.85})
        self._plot.addItem(tl)

        # Summary annotation
        color = {"PASS": accent, "WARNING": warning, "FAIL": danger}.get(
            verdict, text_dim)
        _add_text(self._plot,
                  f"{verdict}   mean {float(np.mean(finite)):.2f} °C   "
                  f"σ {float(np.std(finite)):.2f} °C",
                  color)

    def clear(self) -> None:
        if _PG_OK:
            self._plot.clear()

    def _apply_styles(self) -> None:
        if _PG_OK:
            _configure_plot(self._plot)


# ─────────────────────────────────────────────────────────────────────────────
#  TransientTraceChart
# ─────────────────────────────────────────────────────────────────────────────

class TransientTraceChart(QWidget):
    """
    Interactive replacement for ``TransientCurve``.

    Plots mean ΔR/R vs delay time with:
      • proper axis labels and grid
      • zero-reference line
      • cursor line linked to the delay-index slider
      • user-zoomable / pannable (PyQtGraph native)

    API is a superset of the old ``TransientCurve.update_data()``:

        chart.update_data(values, times_s, cursor_idx)

    Parameters accepted by ``update_data``
    ----------------------------------------
    values    : (N,) array of mean ΔR/R values, one per delay step
    times_s   : (N,) array of delay times in seconds
    cursor_idx: int — current delay-slider index; a vertical cursor is drawn
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 120)

        if not _PG_OK:
            lay = QVBoxLayout(self)
            lay.addWidget(_placeholder())
            return

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._plot = StyledPlotWidget(x_label="Delay  (ms)",
                                      y_label="Mean ΔR/R")
        lay.addWidget(self._plot)

        # Persistent plot items (updated in update_data)
        accent = PALETTE['accent']
        self._curve_item   = self._plot.plot([], [],
                                             pen=pg.mkPen(color=accent, width=2))
        self._cursor_line  = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen(color=PALETTE['warning'], width=1, style=Qt.DashLine),
            movable=False)
        self._zero_line    = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen(color=PALETTE['border'], width=1,
                         style=Qt.DotLine),
            movable=False)
        self._plot.addItem(self._cursor_line)
        self._plot.addItem(self._zero_line)

    # ------------------------------------------------------------------ #

    def update_data(self,
                    values:     np.ndarray,
                    times_s:    np.ndarray,
                    cursor_idx: int = -1) -> None:
        """Update the chart.  Mirrors the old TransientCurve.update_data() API."""
        if not _PG_OK:
            return

        vals = np.asarray(values,  dtype=float)
        ts   = np.asarray(times_s, dtype=float)
        ts_ms = ts * 1e3   # convert to milliseconds for display

        finite = vals[np.isfinite(vals)]
        if finite.size < 2:
            return

        self._curve_item.setData(x=ts_ms, y=vals)

        if 0 <= cursor_idx < len(ts_ms):
            self._cursor_line.setValue(ts_ms[cursor_idx])
            self._cursor_line.setVisible(True)
        else:
            self._cursor_line.setVisible(False)

    def clear(self) -> None:
        if _PG_OK:
            self._curve_item.setData([], [])

    def _apply_styles(self) -> None:
        if not _PG_OK:
            return
        _configure_plot(self._plot)
        accent = PALETTE['accent']
        self._curve_item.setPen(pg.mkPen(color=accent, width=2))
        self._cursor_line.setPen(
            pg.mkPen(color=PALETTE['warning'], width=1, style=Qt.DashLine))
        self._zero_line.setPen(
            pg.mkPen(color=PALETTE['border'], width=1,
                     style=Qt.DotLine))


# ─────────────────────────────────────────────────────────────────────────────
#  SessionTrendChart
# ─────────────────────────────────────────────────────────────────────────────

class SessionTrendChart(QWidget):
    """
    Scatter / line chart showing measurement metrics over saved sessions.

    Two stacked panels:
      • Top:    SNR (dB) per session
      • Bottom: TEC temperature per session

    Points are coloured by ``meta.status``:
      reviewed → accent (teal)
      flagged  → danger (red)
      pending  → textDim (grey)
      default  → textSub

    Call ``update_sessions(metas)`` with a list of ``SessionMeta`` objects
    sorted by timestamp.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        if not _PG_OK:
            lay = QVBoxLayout(self)
            lay.addWidget(_placeholder())
            return

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._snr_plot  = StyledPlotWidget(x_label="Session #",
                                            y_label="SNR  (dB)")
        self._snr_plot.setFixedHeight(130)
        self._temp_plot = StyledPlotWidget(x_label="Session #",
                                            y_label="TEC temp  (°C)")
        self._temp_plot.setFixedHeight(130)

        # Link x-axes so panning one pans the other
        self._temp_plot.setXLink(self._snr_plot)

        lay.addWidget(self._snr_plot)
        lay.addWidget(self._temp_plot)

    # ------------------------------------------------------------------ #

    def update_sessions(self, metas: list) -> None:
        """Refresh both panels from a list of SessionMeta objects."""
        if not _PG_OK or not metas:
            return

        accent  = PALETTE['accent']
        warning = PALETTE['warning']
        danger  = PALETTE['danger']
        dim     = PALETTE['textDim']

        def _color(meta) -> str:
            s = getattr(meta, "status", "")
            return {"reviewed": accent,
                    "flagged":  danger,
                    "pending":  dim}.get(s, dim)

        xs    = list(range(len(metas)))
        snrs  = [m.snr_db         if getattr(m, "snr_db",         None) is not None else float("nan")
                 for m in metas]
        temps = [m.tec_temperature if getattr(m, "tec_temperature", None) is not None else float("nan")
                 for m in metas]
        brushes = [pg.mkBrush(_color(m)) for m in metas]

        self._snr_plot.clear()
        if any(np.isfinite(snrs)):
            snr_scatter = pg.ScatterPlotItem(
                x=xs, y=snrs, size=8,
                pen=pg.mkPen(None), brushes=brushes)
            self._snr_plot.addItem(snr_scatter)
            # Connect line
            pen = pg.mkPen(color=dim + "55", width=1)
            self._snr_plot.plot(xs, snrs, pen=pen, connect="finite")

        self._temp_plot.clear()
        if any(np.isfinite(temps)):
            temp_scatter = pg.ScatterPlotItem(
                x=xs, y=temps, size=8,
                pen=pg.mkPen(None), brushes=brushes)
            self._temp_plot.addItem(temp_scatter)
            pen = pg.mkPen(color=dim + "55", width=1)
            self._temp_plot.plot(xs, temps, pen=pen, connect="finite")

        # Legend note (small text)
        for pw, label in ((self._snr_plot, "SNR"),
                          (self._temp_plot, "TEC temp")):
            if metas:
                _add_text(pw, f"{len(metas)} sessions", dim)

    def clear(self) -> None:
        if _PG_OK:
            self._snr_plot.clear()
            self._temp_plot.clear()

    def _apply_styles(self) -> None:
        if not _PG_OK:
            return
        _configure_plot(self._snr_plot)
        _configure_plot(self._temp_plot)


# ─────────────────────────────────────────────────────────────────────────────
#  dTSparklineWidget
# ─────────────────────────────────────────────────────────────────────────────

_SPARKLINE_WINDOW_S = 120   # rolling window in seconds
_SPARKLINE_HEIGHT   = 56    # fixed widget height px


class dTSparklineWidget(QWidget):
    """
    Rolling 2-minute history of dT (ΔT from TEC setpoint).

    Call ``push_dt(dt_c)`` from the TEC status slot; the chart scrolls
    automatically.

    The widget is hidden by default; show it with ``setVisible(True)``.
    It is typically placed immediately below ``MeasurementReadoutStrip``
    in the main window's root layout.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_SPARKLINE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._times: deque  = deque()    # float timestamps (seconds)
        self._dts:   deque  = deque()    # float dT values

        if not _PG_OK:
            lay = QVBoxLayout(self)
            lbl = QLabel("pyqtgraph not installed")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"color:{PALETTE['textDim']};"
                f"font-size:{FONT.get('caption',9)}pt;")
            lay.addWidget(lbl)
            return

        import time as _time
        self._time = _time

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._plot = StyledPlotWidget(x_label="", y_label="dT  (°C)")
        # Hide x-axis ticks — time scrolls right-to-left and exact values
        # are shown in the measurement strip; the sparkline shows SHAPE only.
        self._plot.getAxis("bottom").setStyle(showValues=False)
        lay.addWidget(self._plot)

        accent = PALETTE['accent']
        self._line  = self._plot.plot([], [],
                                      pen=pg.mkPen(color=accent, width=1))
        self._zero  = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen(color=PALETTE['border'],
                         width=1, style=Qt.DotLine))
        self._plot.addItem(self._zero)

    # ------------------------------------------------------------------ #

    def push_dt(self, dt_c: Optional[float]) -> None:
        """Append a new dT reading.  None readings are silently skipped."""
        if not _PG_OK or dt_c is None:
            return
        import time as _time
        now = _time.monotonic()
        self._times.append(now)
        self._dts.append(float(dt_c))

        # Expire readings older than the window
        cutoff = now - _SPARKLINE_WINDOW_S
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
            self._dts.popleft()

        if len(self._times) < 2:
            return

        # Normalise x-axis to "seconds ago" (0 = now, negative = past)
        xs = np.array(self._times) - now
        ys = np.array(self._dts)
        self._line.setData(x=xs, y=ys)

    def clear(self) -> None:
        self._times.clear()
        self._dts.clear()
        if _PG_OK:
            self._line.setData([], [])

    def _apply_styles(self) -> None:
        if not _PG_OK:
            return
        _configure_plot(self._plot)
        self._line.setPen(
            pg.mkPen(color=PALETTE['accent'], width=1))
        self._zero.setPen(
            pg.mkPen(color=PALETTE['border'],
                     width=1, style=Qt.DotLine))


# ─────────────────────────────────────────────────────────────────────────────
#  Private utilities
# ─────────────────────────────────────────────────────────────────────────────

def _add_text(pw: "pg.PlotWidget", text: str, color: str) -> None:
    """Add a small annotation label in the top-left of a PlotWidget."""
    if not _PG_OK:
        return
    item = pg.TextItem(
        text=text,
        color=color,
        anchor=(0, 0),
    )
    font = QFont("Menlo") if sys.platform == "darwin" else QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(FONT.get("caption", 9))
    item.setFont(font)
    pw.addItem(item)
    # Position in view coordinates — use a lambda so it re-positions on zoom
    vr = pw.viewRect()
    item.setPos(vr.left() + vr.width() * 0.02,
                vr.top()  + vr.height() * 0.95)


def _r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Simple R² coefficient of determination."""
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 0.0
