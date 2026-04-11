"""
acquisition/transient_tab.py

TransientTab — UI for FPGA-triggered time-resolved transient acquisition.

Transient acquisition maps the thermal impulse response of the DUT:
how ΔR/R (and hence temperature) evolves from microseconds to milliseconds
after a precisely timed power pulse.  The result is a 3D ΔR/R cube
(N_delays × H × W), one frame per delay step.

The UI shows:
  • Per-delay × per-average nested progress
  • HW-trigger availability indicator (green = FPGA single-shot, amber = SW fallback)
  • After completion: frame viewer at a selected delay index + mean ΔR/R curve

Layout
------
Left panel  : Timing, averaging, hardware status, run/abort controls
Right panel : Progress, result (frame viewer + mean curve)
"""

from __future__ import annotations

import time
import threading
import logging
import numpy as np
from typing import Optional, List

log = logging.getLogger(__name__)

from ui.button_utils import RunningButton, apply_hand_cursor
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE, MONO_FONT
from ui.widgets.time_estimate_label import TimeEstimateLabel

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QSlider, QComboBox, QSplitter, QSizePolicy, QFileDialog, QMessageBox,
    QCheckBox, QRadioButton, QButtonGroup, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PyQt5.QtCore import Qt, QTimer, QPointF, pyqtSignal
from PyQt5.QtGui  import (QImage, QPixmap, QPainter, QPen, QColor, QFont,
                          QPolygonF, QPainterPath)

from ui.font_utils import mono_font, sans_font
from .processing import to_display, apply_colormap, COLORMAP_OPTIONS, COLORMAP_TOOLTIPS, setup_cmap_combo
import config as cfg_mod
from .transient_pipeline import (
    TransientAcquisitionPipeline, TransientAcqState,
    TransientProgress, TransientResult)
from .transient_metrics import (
    compute_transient_metrics, compute_all_roi_metrics, TransientMetrics,
    baseline_window_size)
from .roi_extraction import extract_roi_signals as _extract_roi_signals_shared
from ai.instrument_knowledge import (
    TRANSIENT_DEFAULT_N_DELAYS, TRANSIENT_DEFAULT_N_AVERAGES,
    TRANSIENT_DEFAULT_PULSE_US, TRANSIENT_DEFAULT_DELAY_END_S,
    TRANSIENT_MIN_AVERAGES)


# ------------------------------------------------------------------ #
#  Mean ΔR/R curve widget                                             #
# ------------------------------------------------------------------ #

class TransientCurve(QWidget):
    """
    Plots mean ΔR/R vs delay time.

    Receives a (N_delays,) array of mean values and the corresponding
    delay_times_s array.  Renders a simple sparkline with tick marks.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 100)
        self.setFixedHeight(120)
        self._values:  Optional[np.ndarray] = None
        self._times_s: Optional[np.ndarray] = None
        self._cursor_idx: int = -1   # highlighted delay index

    def update_data(self, values: np.ndarray, times_s: np.ndarray,
                    cursor_idx: int = -1):
        self._values     = values
        self._times_s    = times_s
        self._cursor_idx = cursor_idx
        self.update()

    def paintEvent(self, e):
        p  = QPainter(self)
        W, H = self.width(), self.height()
        PAD = 6

        p.fillRect(0, 0, W, H, QColor(PALETTE['bg']))

        if self._values is None or len(self._values) < 2:
            p.setPen(QColor(PALETTE['border']))
            p.setFont(sans_font(10))
            p.drawText(self.rect(), Qt.AlignCenter, "No data")
            p.end()
            return

        vals = np.asarray(self._values, dtype=float)
        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            p.end()
            return

        lo, hi = float(finite.min()), float(finite.max())
        if hi == lo:
            lo -= 1e-12; hi += 1e-12
        span    = hi - lo
        n       = len(vals)
        plot_w  = W - 2 * PAD
        plot_h  = H - 2 * PAD - 14   # leave 14 px for x-axis label

        def _x(i):
            return int(PAD + i / (n - 1) * plot_w)

        def _y(v):
            return int(H - PAD - 14 - (v - lo) / span * plot_h)

        # Zero reference
        if lo < 0 < hi:
            zy = _y(0.0)
            p.setPen(QPen(QColor(PALETTE['border']), 1, Qt.DotLine))
            p.drawLine(PAD, zy, W - PAD, zy)

        # Cursor line (selected delay)
        if 0 <= self._cursor_idx < n:
            cx = _x(self._cursor_idx)
            _warn = QColor(PALETTE['warning']); _warn.setAlpha(140)
            p.setPen(QPen(_warn, 1, Qt.DashLine))
            p.drawLine(cx, PAD, cx, H - PAD - 14)

        # Curve
        pen = QPen(QColor(PALETTE['accent']), 1, Qt.SolidLine)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        pts = [(_x(i), _y(float(v) if np.isfinite(v) else lo))
               for i, v in enumerate(vals)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

        # X-axis label (first and last delay in ms)
        p.setPen(QColor(PALETTE['textSub']))
        p.setFont(mono_font(8))
        if self._times_s is not None and len(self._times_s) >= 2:
            t0 = self._times_s[0] * 1e3
            t1 = self._times_s[-1] * 1e3
            p.drawText(PAD, H - 4, f"{t0:.2f} ms")
            p.drawText(W - 64, H - 4, f"{t1:.2f} ms")

        # Value labels
        p.setPen(QColor(PALETTE['textSub']))
        p.drawText(PAD + 2, PAD + 10, f"{hi:.3e}")
        p.drawText(PAD + 2, H - 16,   f"{lo:.3e}")

        p.end()


# ------------------------------------------------------------------ #
#  TransientTab                                                        #
# ------------------------------------------------------------------ #

class TransientTab(QWidget):
    """
    UI tab for FPGA-triggered time-resolved transient acquisition.

    Wires up TransientAcquisitionPipeline, shows nested delay/average
    progress, and displays the ΔR/R frame at the selected delay index
    together with the mean ΔR/R vs time curve after completion.
    """

    compare_requested = pyqtSignal()  # emitted when user clicks "Compare…"

    def __init__(self):
        super().__init__()
        self._pipeline: Optional[TransientAcquisitionPipeline] = None
        self._result:   Optional[TransientResult]              = None
        self._loaded_session_label: str                        = ""
        self._last_progress: Optional[TransientProgress]       = None

        # Voltage-series sweep state (written from worker thread, read by timer)
        self._vsweep_results: List[tuple]               = []   # [(v, TransientResult)]
        self._vsweep_thread:  Optional[threading.Thread] = None
        self._sweep_abort_flag: bool                    = False
        self._sweep_status: Optional[str]               = None  # thread → timer
        self._sweep_complete_result: Optional[TransientResult] = None
        # Lock protecting _sweep_complete_result and _sweep_status shared
        # between the worker thread and the QTimer poll slot (M-4 fix).
        self._sweep_lock: threading.Lock                = threading.Lock()

        # Poll timer
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(240)
        left_scroll.setMaximumWidth(320)
        left_scroll.setWidget(self._build_left())

        splitter.addWidget(left_scroll)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setWidget(self._build_right())
        splitter.addWidget(right_scroll)
        splitter.setSizes([290, 700])
        root.addWidget(splitter, 1)

        # Re-extract ROI curves when ROIs change
        try:
            from acquisition.roi_model import roi_model
            roi_model.rois_changed.connect(self._invalidate_roi_mask_cache)
            roi_model.rois_changed.connect(self._update_roi_curves)
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Left panel                                                       #
    # ---------------------------------------------------------------- #

    def _build_left(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 6, 10)
        lay.setSpacing(10)

        # ── Timing ───────────────────────────────────────────────────
        tim_box = QGroupBox("Timing")
        tl = QGridLayout(tim_box)
        tl.setSpacing(6)
        tl.setColumnStretch(1, 1)

        self._n_delays = QSpinBox()
        self._n_delays.setRange(2, 500)
        self._n_delays.setValue(TRANSIENT_DEFAULT_N_DELAYS)
        self._n_delays.setMinimumWidth(80)
        self._n_delays.setToolTip("Number of discrete delay steps in the output cube.")

        self._delay_start = QDoubleSpinBox()
        self._delay_start.setRange(0.0, 1000.0)
        self._delay_start.setValue(0.0)
        self._delay_start.setDecimals(3)
        self._delay_start.setSuffix(" ms")
        self._delay_start.setMinimumWidth(80)
        self._delay_start.setToolTip("First delay from pulse leading edge (ms).")

        self._delay_end = QDoubleSpinBox()
        self._delay_end.setRange(0.001, 10000.0)
        self._delay_end.setValue(TRANSIENT_DEFAULT_DELAY_END_S * 1e3)
        self._delay_end.setDecimals(2)
        self._delay_end.setSuffix(" ms")
        self._delay_end.setMinimumWidth(80)
        self._delay_end.setToolTip("Last delay from pulse leading edge (ms).")

        self._pulse_us = QDoubleSpinBox()
        self._pulse_us.setRange(1.0, 100_000.0)
        self._pulse_us.setValue(TRANSIENT_DEFAULT_PULSE_US)
        self._pulse_us.setDecimals(1)
        self._pulse_us.setSuffix(" µs")
        self._pulse_us.setMinimumWidth(80)
        self._pulse_us.setToolTip(
            "Duration of each power pulse in microseconds.\n"
            "The FPGA fires this pulse, then waits `delay` before camera capture.")

        # ── Sweep Mode: Linear | Logarithmic ─────────────────────────
        self._sweep_linear_rb = QRadioButton("Linear")
        self._sweep_log_rb    = QRadioButton("Logarithmic")
        self._sweep_linear_rb.setChecked(True)
        self._sweep_mode_grp  = QButtonGroup(self)
        self._sweep_mode_grp.addButton(self._sweep_linear_rb, 0)
        self._sweep_mode_grp.addButton(self._sweep_log_rb,    1)
        self._sweep_linear_rb.setToolTip(
            "Delay points are evenly spaced: np.linspace(start, stop, n_steps)")
        self._sweep_log_rb.setToolTip(
            "Delay points are logarithmically spaced: np.geomspace(start, stop, n_steps)\n"
            "Ideal for capturing fast transient onset with slower long-term tail.\n"
            "Note: delay start must be > 0 for log spacing.")

        sweep_mode_w = QWidget()
        sweep_mode_h = QHBoxLayout(sweep_mode_w)
        sweep_mode_h.setContentsMargins(0, 0, 0, 0)
        sweep_mode_h.setSpacing(8)
        sweep_mode_h.addWidget(self._sweep_linear_rb)
        sweep_mode_h.addWidget(self._sweep_log_rb)
        sweep_mode_h.addStretch()

        tl.addWidget(self._sub("Delays"),      0, 0)
        tl.addWidget(self._n_delays,           0, 1)
        tl.addWidget(self._sub("Delay start"), 1, 0)
        tl.addWidget(self._delay_start,        1, 1)
        tl.addWidget(self._sub("Delay end"),   2, 0)
        tl.addWidget(self._delay_end,          2, 1)
        tl.addWidget(self._sub("Sweep mode"),  3, 0)
        tl.addWidget(sweep_mode_w,             3, 1)
        tl.addWidget(self._sub("Pulse width"), 4, 0)
        tl.addWidget(self._pulse_us,           4, 1)
        lay.addWidget(tim_box)

        # ── Averaging ────────────────────────────────────────────────
        avg_box = QGroupBox("Averaging")
        al = QGridLayout(avg_box)
        al.setSpacing(6)
        al.setColumnStretch(1, 1)

        self._n_avg = QSpinBox()
        self._n_avg.setRange(1, 1000)
        self._n_avg.setValue(TRANSIENT_DEFAULT_N_AVERAGES)
        self._n_avg.setMinimumWidth(80)
        self._n_avg.setToolTip(
            f"Number of trigger cycles averaged per delay step.\n"
            f"Minimum recommended: {TRANSIENT_MIN_AVERAGES} for acceptable SNR.")

        self._drift_cb = QCheckBox("Use drift correction (image shift)")
        self._drift_cb.setChecked(False)
        self._drift_cb.setToolTip(
            "Apply FFT phase-correlation drift correction to each captured frame\n"
            "before accumulating into the per-delay average.\n"
            "Compensates for slow sample drift during long acquisitions.\n"
            "Equivalent to 'Use Image Shift' in the LabVIEW interface.\n"
            "Note: adds ~1 ms per frame; disable for maximum throughput.")

        al.addWidget(self._sub("Averages/delay"), 0, 0)
        al.addWidget(self._n_avg,                 0, 1)
        al.addWidget(self._drift_cb,              1, 0, 1, 2)
        lay.addWidget(avg_box)

        # ── Hardware status ───────────────────────────────────────────
        hw_box = QGroupBox("Hardware")
        hl = QGridLayout(hw_box)
        hl.setSpacing(4)
        self._hw_cam_lbl    = QLabel("—")
        self._hw_fpga_lbl   = QLabel("—")
        self._hw_trig_lbl   = QLabel("—")   # HW trigger availability
        for l in [self._hw_cam_lbl, self._hw_fpga_lbl, self._hw_trig_lbl]:
            l.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['textDim']};")
        hl.addWidget(self._sub("Camera"),        0, 0)
        hl.addWidget(self._hw_cam_lbl,           0, 1)
        hl.addWidget(self._sub("FPGA"),          1, 0)
        hl.addWidget(self._hw_fpga_lbl,          1, 1)
        hl.addWidget(self._sub("HW Trigger"),    2, 0)
        hl.addWidget(self._hw_trig_lbl,          2, 1)
        lay.addWidget(hw_box)

        # ── Voltage Series ────────────────────────────────────────────
        vs_box = QGroupBox("Voltage Series")
        vs_box.setCheckable(True)
        vs_box.setChecked(False)
        vs_box.setToolTip(
            "Run a full transient acquisition at each voltage step.\n"
            "Requires a connected bias source.  Power is set and settled\n"
            "before each step; bias is disabled after the final step.")
        self._vsweep_box = vs_box
        vl = QGridLayout(vs_box)
        vl.setSpacing(6)
        vl.setColumnStretch(1, 1)

        self._vsweep_start = QDoubleSpinBox()
        self._vsweep_start.setRange(-60.0, 60.0)
        self._vsweep_start.setValue(0.5)
        self._vsweep_start.setSuffix(" V")
        self._vsweep_start.setDecimals(3)
        self._vsweep_start.setMinimumWidth(80)
        self._vsweep_start.setToolTip("First bias voltage in the sweep.")

        self._vsweep_step = QDoubleSpinBox()
        self._vsweep_step.setRange(0.001, 30.0)
        self._vsweep_step.setValue(0.5)
        self._vsweep_step.setSuffix(" V")
        self._vsweep_step.setDecimals(3)
        self._vsweep_step.setMinimumWidth(80)
        self._vsweep_step.setToolTip("Voltage increment between steps.")

        self._vsweep_end = QDoubleSpinBox()
        self._vsweep_end.setRange(-60.0, 60.0)
        self._vsweep_end.setValue(3.0)
        self._vsweep_end.setSuffix(" V")
        self._vsweep_end.setDecimals(3)
        self._vsweep_end.setMinimumWidth(80)
        self._vsweep_end.setToolTip("Last bias voltage in the sweep.")

        self._vsweep_n_lbl = QLabel("—")
        self._vsweep_n_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")

        for sp in [self._vsweep_start, self._vsweep_step, self._vsweep_end]:
            sp.valueChanged.connect(self._update_vsweep_label)
        vs_box.toggled.connect(lambda _: self._update_vsweep_label())

        vl.addWidget(self._sub("V start"), 0, 0)
        vl.addWidget(self._vsweep_start,   0, 1)
        vl.addWidget(self._sub("V step"),  1, 0)
        vl.addWidget(self._vsweep_step,    1, 1)
        vl.addWidget(self._sub("V end"),   2, 0)
        vl.addWidget(self._vsweep_end,     2, 1)
        vl.addWidget(self._vsweep_n_lbl,   3, 0, 1, 2)
        lay.addWidget(vs_box)
        self._update_vsweep_label()

        # Connect time-estimation updates
        self._n_delays.valueChanged.connect(self._update_time_est)
        self._n_avg.valueChanged.connect(self._update_time_est)
        self._vsweep_box.toggled.connect(lambda _: self._update_time_est())
        for sp in [self._vsweep_start, self._vsweep_step, self._vsweep_end]:
            sp.valueChanged.connect(self._update_time_est)

        # ── Run controls ──────────────────────────────────────────────
        run_box = QGroupBox("Run")
        rl = QVBoxLayout(run_box)

        self._time_est_lbl = TimeEstimateLabel()
        rl.addWidget(self._time_est_lbl)
        self._update_time_est()

        self._run_btn   = QPushButton("Run Transient")
        set_btn_icon(self._run_btn, "fa5s.play", PALETTE['accent'])
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(34)
        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", PALETTE['danger'])
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setFixedHeight(32)
        self._abort_btn.setEnabled(False)

        self._btn_runner = RunningButton(
            self._run_btn, idle_text="▶  Run Transient")
        apply_hand_cursor(self._abort_btn)
        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

        self._save_sweep_cb = QCheckBox("Save sweep data (.npy cube)")
        self._save_sweep_cb.setChecked(False)
        self._save_sweep_cb.setToolTip(
            "After acquisition completes, save the full time-resolved ΔR/R cube\n"
            "as a .npy file alongside the session directory.\n"
            "File name: transient_cube_<timestamp>.npy")

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']};")
        self._status_lbl.setWordWrap(True)

        rl.addWidget(self._run_btn)
        rl.addWidget(self._abort_btn)
        rl.addWidget(self._save_sweep_cb)
        rl.addWidget(self._progress)
        rl.addWidget(self._status_lbl)
        lay.addWidget(run_box)

        # ── Save + Compare ────────────────────────────────────────────
        self._save_btn = QPushButton("Save Cube…")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedHeight(30)
        self._save_btn.clicked.connect(self._save)
        lay.addWidget(self._save_btn)

        self._compare_btn = QPushButton("Compare…")
        set_btn_icon(self._compare_btn, "fa5s.balance-scale")
        self._compare_btn.setEnabled(False)
        self._compare_btn.setFixedHeight(30)
        self._compare_btn.setToolTip(
            "Compare the current transient result with another saved session.")
        self._compare_btn.clicked.connect(self.compare_requested.emit)
        lay.addWidget(self._compare_btn)

        lay.addStretch()
        self._refresh_hw()
        return w

    # ---------------------------------------------------------------- #
    #  Right panel                                                      #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        """Right panel — viewer-first layout.

        Hierarchy (top to bottom):
          1. Compact result strip (single line)
          2. View mode + colormap controls
          3. Frame viewer (stretch=3, dominates)
          4. Delay slider (directly below viewer)
          5. ΔR/R chart (stretch=1, capped height)
          6. ROI Metrics (collapsed by default)
          7. Save Analysis button
        """
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 6, 8, 8)
        lay.setSpacing(4)

        # ── Compact result strip (single line) ────────────────────────
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(12)
        self._stats: dict = {}
        for key, label in [
            ("delays",  "Delays"),
            ("avgs",    "Averages"),
            ("dur",     "Duration"),
            ("hw_trig", "HW Trigger"),
            ("max_drr", "Peak |ΔR/R|"),
        ]:
            sub = QLabel(f"{label}:")
            sub.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")
            val = QLabel("—")
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['accent']};")
            strip.addWidget(sub)
            strip.addWidget(val)
            self._stats[key] = val
        strip.addStretch()
        lay.addLayout(strip)
        lay.addSpacing(2)

        # ── View mode + colormap row ──────────────────────────────────
        view_row = QHBoxLayout()
        from ui.widgets.segmented_control import SegmentedControl
        self._view_seg = SegmentedControl(["Thermal", "Merge"], seg_width=72, height=24)
        self._view_seg.selection_changed.connect(self._on_view_mode)
        view_row.addWidget(self._view_seg)
        view_row.addSpacing(12)

        view_row.addWidget(self._sub("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        self._cmap_combo.currentTextChanged.connect(
            lambda _: self._show_frame(self._delay_slider.value()))
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        view_row.addWidget(self._cmap_combo)

        self._detach_btn = QPushButton()
        set_btn_icon(self._detach_btn, "mdi.open-in-new", PALETTE['textDim'])
        self._detach_btn.setFixedSize(24, 24)
        self._detach_btn.setToolTip(
            "Open a detached large viewer window.\n"
            "Can be moved to a second monitor or made full-screen (F11).")
        self._detach_btn.setFlat(True)
        self._detach_btn.clicked.connect(self._on_detach_viewer)
        view_row.addWidget(self._detach_btn)

        view_row.addStretch()
        lay.addLayout(view_row)

        # ── Frame viewer (dominant — stretch=3) ───────────────────────
        from ui.widgets.overlay_compositor import OverlayCompositor
        self._compositor = OverlayCompositor()
        self._compositor.setMinimumSize(400, 280)
        self._compositor.add_overlay("rois", self._paint_rois, label="ROIs")
        lay.addWidget(self._compositor, 3)

        # ── Delay slider (directly below viewer) ─────────────────────
        slider_row = QHBoxLayout()
        slider_row.addWidget(self._sub("Delay:"))
        self._delay_slider = QSlider(Qt.Horizontal)
        self._delay_slider.setRange(0, 49)
        self._delay_slider.setValue(0)
        self._delay_slider.setEnabled(False)
        self._delay_slider.valueChanged.connect(self._on_slider_changed)
        self._delay_time_lbl = QLabel("—")
        self._delay_time_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']}; min-width:70px;")
        slider_row.addWidget(self._delay_slider, 1)
        slider_row.addWidget(self._delay_time_lbl)
        lay.addLayout(slider_row)

        # ── ΔR/R chart (secondary — stretch=1, capped) ───────────────
        curve_box = QGroupBox("ΔR/R vs Delay Time")
        curve_box.setMaximumHeight(200)
        cl = QVBoxLayout(curve_box)
        from ui.charts import TransientTraceChart
        self._curve = TransientTraceChart()
        self._curve.cursor_moved.connect(self._on_chart_cursor)
        cl.addWidget(self._curve)
        lay.addWidget(curve_box, 1)

        # ── ROI Metrics (collapsed by default) ────────────────────────
        from ui.widgets.collapsible_panel import CollapsiblePanel
        self._metrics_panel = CollapsiblePanel(
            "ROI Metrics", start_collapsed=True)

        self._metrics_table = QTableWidget(0, 7)
        self._metrics_table.setHorizontalHeaderLabels([
            "ROI", "Peak ΔR/R", "Time-to-peak", "Baseline μ",
            "Baseline σ", "Peak SNR", "Recovery",
        ])
        self._metrics_table.horizontalHeader().setStretchLastSection(True)
        self._metrics_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self._metrics_table.verticalHeader().setVisible(False)
        self._metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._metrics_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._metrics_table.setMaximumHeight(160)
        self._metrics_table.setStyleSheet(
            f"QTableWidget {{ font-family:{MONO_FONT}; "
            f"font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; }}"
            f"QHeaderView::section {{ font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['surface']}; color:{PALETTE['textSub']}; "
            f"padding:2px 4px; }}")
        self._metrics_panel.addWidget(self._metrics_table)
        lay.addWidget(self._metrics_panel)

        # Cache for computed metrics (updated in _compute_and_display_metrics)
        self._current_metrics: list[TransientMetrics] = []
        self._ff_metrics: Optional[TransientMetrics] = None

        # ── Save Analysis ─────────────────────────────────────────────
        save_row = QHBoxLayout()
        self._save_analysis_btn = QPushButton("Save Analysis…")
        set_btn_icon(self._save_analysis_btn, "fa5s.file-export")
        self._save_analysis_btn.setEnabled(False)
        self._save_analysis_btn.setFixedHeight(28)
        self._save_analysis_btn.clicked.connect(self._save_analysis)
        save_row.addWidget(self._save_analysis_btn)
        save_row.addStretch()
        lay.addLayout(save_row)

        return w

    # ---------------------------------------------------------------- #
    #  Run / Abort                                                      #
    # ---------------------------------------------------------------- #

    def _run(self):
        from hardware.app_state import app_state
        cam  = app_state.cam
        fpga = app_state.fpga
        bias = app_state.bias

        if cam is None:
            QMessageBox.warning(self, "Transient", "Camera not connected.")
            return

        if self._n_avg.value() < TRANSIENT_MIN_AVERAGES:
            QMessageBox.warning(
                self, "Transient",
                f"Averaging below {TRANSIENT_MIN_AVERAGES} cycles gives poor SNR.\n"
                f"Increase N averages to at least {TRANSIENT_MIN_AVERAGES}.")

        # ── Voltage-series sweep mode ──────────────────────────────────
        if self._vsweep_box.isChecked():
            if bias is None:
                QMessageBox.warning(self, "Transient",
                    "Voltage series sweep requires a connected bias source.")
                return
            voltages = self._vsweep_voltage_list()
            if not voltages:
                QMessageBox.warning(self, "Transient",
                    "Invalid voltage series: start must be < end and step > 0.")
                return
            self._start_vsweep(voltages, cam, fpga, bias)
            return

        # ── Single-shot mode ───────────────────────────────────────────
        self._pipeline = TransientAcquisitionPipeline(cam, fpga=fpga, bias=bias)

        try:
            from ui.app_signals import signals
            self._pipeline.on_progress = lambda p: signals.transient_progress.emit(p)
            self._pipeline.on_complete = lambda r: signals.transient_complete.emit(r)
            self._pipeline.on_error    = lambda e: signals.error.emit(e)
            # Disconnect stale connections before reconnecting to avoid the
            # slot firing N times on the Nth successive run.
            try:
                signals.transient_progress.disconnect(self._on_progress)
                signals.transient_complete.disconnect(self._on_complete)
            except Exception:
                log.debug("TransientTab._run: signal disconnect (stale) — "
                          "no previous connection to remove", exc_info=True)
            signals.transient_progress.connect(self._on_progress)
            signals.transient_complete.connect(self._on_complete)
        except Exception:
            log.warning("TransientTab._run: app_signals unavailable — "
                        "using direct pipeline callbacks", exc_info=True)
            self._pipeline.on_progress = lambda p: setattr(self, '_last_progress', p)
            self._pipeline.on_complete = self._on_complete

        self._pipeline.start(
            n_delays         = self._n_delays.value(),
            delay_start_s    = self._delay_start.value() / 1000.0,
            delay_end_s      = self._delay_end.value() / 1000.0,
            pulse_dur_us     = self._pulse_us.value(),
            n_averages       = self._n_avg.value(),
            drift_correction = self._drift_cb.isChecked(),
            delay_times_s    = self._build_delay_times(),
        )

        self._timer.start()
        self._btn_runner.set_running(True, "Acquiring")
        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._save_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status_lbl.setText("Starting…")
        self._delay_slider.setEnabled(False)

        try:
            app_state.active_modality = "transient"
        except Exception:
            log.debug("TransientTab._run: could not set active_modality", exc_info=True)

    def _abort(self):
        self._sweep_abort_flag = True   # signals sweep worker to stop between steps
        if self._pipeline:
            self._pipeline.abort()
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._status_lbl.setText("Aborted")
        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            log.debug("TransientTab._abort: could not reset active_modality",
                      exc_info=True)

    # ---------------------------------------------------------------- #
    #  Poll + callbacks                                                 #
    # ---------------------------------------------------------------- #

    def _poll(self):
        # ── Sweep thread status/completion (lock-protected reads) ─────
        with self._sweep_lock:
            sweep_msg  = self._sweep_status
            sweep_done = self._sweep_complete_result
            if sweep_msg  is not None: self._sweep_status          = None
            if sweep_done is not None: self._sweep_complete_result = None

        if sweep_msg is not None:
            self._status_lbl.setText(sweep_msg)

        if sweep_done is not None:
            self._on_complete(sweep_done)
            return

        # ── Single-shot pipeline poll ──────────────────────────────────
        if self._pipeline is None:
            return
        state = self._pipeline.state
        if state in (TransientAcqState.COMPLETE,
                     TransientAcqState.ABORTED,
                     TransientAcqState.ERROR):
            self._timer.stop()
        p = self._last_progress
        if p is not None:
            self._last_progress = None
            self._on_progress(p)

    def _on_progress(self, p: TransientProgress):
        pct = int(p.fraction * 100)
        self._progress.setValue(pct)
        self._status_lbl.setText(p.message)

    def _on_complete(self, result: TransientResult):
        self._result = result
        self._loaded_session_label = ""   # clear any "loaded from" indicator
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setValue(100)
        self._save_btn.setEnabled(True)
        self._compare_btn.setEnabled(True)

        self._status_lbl.setText(
            f"Complete — {result.n_delays} delays × {result.n_averages} avg  "
            f"({'HW trigger' if result.hw_triggered else 'SW fallback'})")

        self._display_result(result)

        # ── Auto-save sweep cube if checkbox is set ───────────────────
        if self._save_sweep_cb.isChecked() and result.delta_r_cube is not None:
            self._auto_save_cube(result)

        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            log.debug("TransientTab._on_complete: could not reset active_modality",
                      exc_info=True)

    def _display_result(self, result: TransientResult):
        """Populate all display widgets from a TransientResult.

        Shared by live acquisition (_on_complete) and session reload
        (load_session).  Does NOT touch run/abort button state or
        auto-save — callers handle those concerns separately.
        """
        # Stats
        self._stats["delays"].setText(str(result.n_delays))
        self._stats["avgs"].setText(str(result.n_averages))
        dur = getattr(result, 'duration_s', 0.0) or 0.0
        self._stats["dur"].setText(f"{dur:.1f} s")
        self._stats["hw_trig"].setText("Yes" if result.hw_triggered else "No (SW)")
        self._stats["hw_trig"].setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; "
            f"color:{PALETTE['accent'] if result.hw_triggered else PALETTE['warning']};")

        # Delay slider
        n = result.n_delays
        self._delay_slider.setRange(0, max(n - 1, 0))
        self._delay_slider.setValue(0)
        self._delay_slider.setEnabled(True)

        # Mean curve + ROI curves + metrics
        if result.delta_r_cube is not None:
            cube = result.delta_r_cube
            means = np.nanmean(cube.reshape(n, -1), axis=1)
            self._curve.update_data(means, result.delay_times_s, 0)
            self._update_roi_curves(full_frame_signal=means)

            finite = cube[np.isfinite(cube)]
            if finite.size > 0:
                self._stats["max_drr"].setText(f"{float(np.abs(finite).max()):.3e}")

            self._show_frame(0)

    def load_session(self, session) -> None:
        """Populate the tab from a stored transient Session.

        Reconstructs a TransientResult from the session's lazy-loaded
        arrays and cube_params metadata, then displays it.  The tab
        shows a "Loaded from: <label>" indicator to distinguish reloaded
        data from a live acquisition.

        Parameters
        ----------
        session
            A ``Session`` object with ``result_type == "transient"``
            and cube arrays available via lazy-load properties.
        """
        cp = getattr(session.meta, "cube_params", None) or {}
        result = TransientResult(
            delta_r_cube  = session.delta_r_cube,
            reference     = session.reference,
            delay_times_s = session.delay_times_s,
            raw_cube      = None,   # not persisted
            n_delays      = cp.get("n_delays", 0),
            n_averages    = cp.get("n_averages", 0),
            pulse_dur_us  = cp.get("pulse_dur_us", 0.0),
            delay_start_s = cp.get("delay_start_s", 0.0),
            delay_end_s   = cp.get("delay_end_s", 0.0),
            exposure_us   = session.meta.exposure_us,
            gain_db       = session.meta.gain_db,
            duration_s    = session.meta.duration_s,
            hw_triggered  = cp.get("hw_triggered", False),
        )
        self._result = result
        label = getattr(session.meta, "label", session.meta.uid) or session.meta.uid
        self._loaded_session_label = label

        # UI state for a loaded session (not a live acquisition)
        self._save_btn.setEnabled(True)
        self._compare_btn.setEnabled(True)
        self._status_lbl.setText(
            f"Loaded from session: {label}  —  "
            f"{result.n_delays} delays × {result.n_averages} avg")

        self._display_result(result)

    def _auto_save_cube(self, result) -> None:
        """
        Automatically save the ΔR/R cube to a .npy file alongside the session.

        The file is written to the current working directory (or the session
        folder if app_state exposes one) with a timestamp-based name.
        Any error is logged but does not interrupt the UI.
        """
        import os, pathlib
        ts = int(time.time())
        # Prefer session directory if available; fall back to ~/microsanj/sweeps
        # (never "." — on Windows the install dir may require elevation, W-2 fix).
        try:
            from hardware.app_state import app_state
            session_dir = getattr(app_state, "session_dir", None) or ""
        except Exception:
            session_dir = ""
        if not session_dir:
            fallback = pathlib.Path.home() / "microsanj" / "sweeps"
            try:
                fallback.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            session_dir = str(fallback)
        filename = os.path.join(session_dir, f"transient_cube_{ts}.npy")
        try:
            np.save(filename, result.delta_r_cube)
            log.info("TransientTab: sweep cube saved → %s  shape=%s",
                     filename, result.delta_r_cube.shape)
            self._status_lbl.setText(
                self._status_lbl.text() + f"\nCube saved → {os.path.basename(filename)}")
        except Exception as exc:
            log.warning("TransientTab._auto_save_cube: save failed: %s", exc)

    # ---------------------------------------------------------------- #
    #  Frame / slice display                                           #
    # ---------------------------------------------------------------- #

    def _on_slider_changed(self, idx: int):
        if self._result is None:
            return
        if self._result.delay_times_s is not None and idx < len(self._result.delay_times_s):
            t_ms = self._result.delay_times_s[idx] * 1e3
            self._delay_time_lbl.setText(f"{t_ms:.3f} ms")

        # Update curve cursor (ROI curves are cube-invariant, not recomputed here)
        if self._result.delta_r_cube is not None and self._result.delay_times_s is not None:
            n = self._result.n_delays
            means = np.nanmean(
                self._result.delta_r_cube.reshape(n, -1), axis=1)
            self._curve.update_data(means, self._result.delay_times_s, idx)

        self._show_frame(idx)

    def _on_chart_cursor(self, idx: int):
        """Handle interactive cursor click/drag on the chart."""
        if self._result is None:
            return
        n = self._result.n_delays
        idx = max(0, min(idx, n - 1))
        # Update slider (which triggers _on_slider_changed → _show_frame)
        self._delay_slider.setValue(idx)

    def _update_roi_curves(self, full_frame_signal: Optional[np.ndarray] = None):
        """Extract per-ROI mean signal from the cube and push to chart + metrics."""
        if self._result is None or self._result.delta_r_cube is None:
            self._curve.set_roi_curves([])
            self._curve.clear_annotations()
            return

        roi_signals = self._extract_roi_signals()
        self._curve.set_roi_curves(roi_signals)

        # Compute full-frame signal if not provided
        if full_frame_signal is None and self._result.delta_r_cube is not None:
            n = self._result.n_delays
            full_frame_signal = np.nanmean(
                self._result.delta_r_cube.reshape(n, -1), axis=1)

        self._compute_and_display_metrics(roi_signals, full_frame_signal)

    def _invalidate_roi_mask_cache(self):
        """Clear cached ROI masks when ROIs change geometry."""
        if hasattr(self, '_roi_mask_cache'):
            self._roi_mask_cache.clear()

    # ---------------------------------------------------------------- #
    #  Metrics computation + display                                    #
    # ---------------------------------------------------------------- #

    def _compute_and_display_metrics(self,
                                     roi_signals: list[tuple[str, str, np.ndarray]],
                                     full_frame_signal: Optional[np.ndarray] = None,
                                     ) -> None:
        """Compute per-ROI + full-frame metrics and populate the table.

        Also updates chart annotations (peak marker, baseline band) for the
        full-frame signal — or the first ROI if no full-frame is available.
        """
        if self._result is None or self._result.delay_times_s is None:
            return
        ts = self._result.delay_times_s

        # Full-frame metrics
        if full_frame_signal is not None and len(full_frame_signal) == len(ts):
            self._ff_metrics = compute_transient_metrics(
                full_frame_signal, ts, roi_label="Full frame",
                roi_color=PALETTE['accent'])
        else:
            self._ff_metrics = None

        # Per-ROI metrics
        self._current_metrics = compute_all_roi_metrics(roi_signals, ts)

        # Populate table
        self._populate_metrics_table()

        # Chart annotations — use full-frame if available, else first ROI
        ref = self._ff_metrics
        if ref is None and self._current_metrics:
            ref = self._current_metrics[0]
        if ref is not None and ref.n_points >= 2:
            self._curve.set_peak_marker(ref.time_to_peak_s, ref.peak_drr)
            # Baseline band up to end of baseline window
            bl_end_idx = min(ref.baseline_n, len(ts) - 1)
            self._curve.set_baseline_band(
                ts[bl_end_idx], ref.baseline_mean, ref.baseline_std)
        else:
            self._curve.clear_annotations()

        # Enable export button when we have metrics
        self._save_analysis_btn.setEnabled(
            bool(self._current_metrics or self._ff_metrics))

    def _populate_metrics_table(self) -> None:
        """Fill the ROI metrics table from cached metrics."""
        table = self._metrics_table
        all_m = []
        if self._ff_metrics is not None:
            all_m.append(self._ff_metrics)
        all_m.extend(self._current_metrics)

        table.setRowCount(len(all_m))
        for row, m in enumerate(all_m):
            def _item(text: str, color: str = "") -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if color:
                    it.setForeground(QColor(color))
                return it

            table.setItem(row, 0, _item(m.roi_label, m.roi_color))
            table.setItem(row, 1, _item(f"{m.peak_drr:+.4e}"))
            table.setItem(row, 2, _item(f"{m.time_to_peak_s * 1e3:.3f} ms"))
            table.setItem(row, 3, _item(f"{m.baseline_mean:.4e}"))
            table.setItem(row, 4, _item(f"{m.baseline_std:.4e}"))
            table.setItem(row, 5, _item(f"{m.peak_snr:.1f}"))
            table.setItem(row, 6, _item(f"{m.recovery_ratio:.2f}"))

    # ---------------------------------------------------------------- #
    #  Save Analysis                                                    #
    # ---------------------------------------------------------------- #

    def _save_analysis(self) -> None:
        """Export ROI traces + summary metrics + acquisition metadata."""
        if self._result is None:
            return
        default_name = f"transient_analysis_{int(time.time())}"
        if self._loaded_session_label:
            slug = self._loaded_session_label.replace(" ", "_")
            default_name = f"{slug}_analysis"

        path, filt = QFileDialog.getSaveFileName(
            self, "Save Transient Analysis",
            default_name + ".csv",
            "CSV (*.csv);;JSON (*.json);;All files (*)")
        if not path:
            return

        try:
            import json as _json
            ts = self._result.delay_times_s

            # Collect all ROI signals for export
            roi_signals = self._extract_roi_signals()
            ff_signal = None
            if self._result.delta_r_cube is not None:
                n = self._result.n_delays
                ff_signal = np.nanmean(
                    self._result.delta_r_cube.reshape(n, -1), axis=1)

            if path.lower().endswith(".json"):
                self._save_analysis_json(path, ts, ff_signal, roi_signals)
            else:
                self._save_analysis_csv(path, ts, ff_signal, roi_signals)

            QMessageBox.information(
                self, "Saved",
                f"Transient analysis saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _extract_roi_signals(self) -> list[tuple[str, str, np.ndarray]]:
        """Extract current ROI signals from the cube via shared helper."""
        if self._result is None or self._result.delta_r_cube is None:
            return []
        try:
            from acquisition.roi_model import roi_model
        except ImportError:
            return []
        if not hasattr(self, '_roi_mask_cache'):
            self._roi_mask_cache: dict = {}
        return _extract_roi_signals_shared(
            self._result.delta_r_cube, roi_model.rois, self._roi_mask_cache)

    def _save_analysis_csv(self, path: str, ts: np.ndarray,
                           ff_signal: Optional[np.ndarray],
                           roi_signals: list) -> None:
        """Write traces + metrics to CSV."""
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)

            # Header: metadata
            w.writerow(["# Transient Analysis Export"])
            w.writerow(["# n_delays", self._result.n_delays])
            w.writerow(["# n_averages", self._result.n_averages])
            w.writerow(["# pulse_dur_us", self._result.pulse_dur_us])
            w.writerow(["# hw_triggered", self._result.hw_triggered])
            w.writerow([])

            # Traces section
            headers = ["delay_s", "delay_ms"]
            columns = [ts, ts * 1e3]
            if ff_signal is not None:
                headers.append("full_frame")
                columns.append(ff_signal)
            for label, _color, sig in roi_signals:
                headers.append(label)
                columns.append(sig)
            w.writerow(headers)
            for i in range(len(ts)):
                w.writerow([f"{col[i]:.8e}" if i < len(col) else ""
                            for col in columns])
            w.writerow([])

            # Metrics section
            w.writerow(["# Metrics"])
            w.writerow(["roi", "peak_drr", "time_to_peak_ms",
                        "baseline_mean", "baseline_std", "peak_snr",
                        "recovery_ratio"])
            all_m = []
            if self._ff_metrics is not None:
                all_m.append(self._ff_metrics)
            all_m.extend(self._current_metrics)
            for m in all_m:
                w.writerow([m.roi_label, f"{m.peak_drr:.6e}",
                           f"{m.time_to_peak_s * 1e3:.4f}",
                           f"{m.baseline_mean:.6e}",
                           f"{m.baseline_std:.6e}",
                           f"{m.peak_snr:.2f}",
                           f"{m.recovery_ratio:.4f}"])

    def _save_analysis_json(self, path: str, ts: np.ndarray,
                            ff_signal: Optional[np.ndarray],
                            roi_signals: list) -> None:
        """Write traces + metrics to JSON."""
        import json as _json

        doc = {
            "format": "sanjinsight_transient_analysis_v1",
            "metadata": {
                "n_delays": self._result.n_delays,
                "n_averages": self._result.n_averages,
                "pulse_dur_us": self._result.pulse_dur_us,
                "delay_start_s": self._result.delay_start_s,
                "delay_end_s": self._result.delay_end_s,
                "exposure_us": self._result.exposure_us,
                "gain_db": self._result.gain_db,
                "hw_triggered": self._result.hw_triggered,
                "duration_s": self._result.duration_s,
            },
            "delay_times_s": ts.tolist(),
            "traces": {},
            "metrics": [],
        }
        if ff_signal is not None:
            doc["traces"]["full_frame"] = ff_signal.tolist()
        for label, color, sig in roi_signals:
            doc["traces"][label] = sig.tolist()

        all_m = []
        if self._ff_metrics is not None:
            all_m.append(self._ff_metrics)
        all_m.extend(self._current_metrics)
        doc["metrics"] = [m.to_dict() for m in all_m]

        with open(path, "w", encoding="utf-8") as f:
            _json.dump(doc, f, indent=2)

    def _render_thermal_rgb(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Render a single ΔR/R frame to RGB using the active colormap."""
        finite = frame[np.isfinite(frame)]
        if finite.size == 0:
            return None
        cmap = self._cmap_combo.currentText()
        if cmap in ("Thermal Delta", "signed"):
            limit = float(np.percentile(np.abs(finite), 99.5)) or 1e-9
            normed = np.clip(frame / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            return np.stack([r, g, b], axis=-1)
        disp = to_display(frame, mode="percentile")
        return apply_colormap(disp, cmap)

    def _show_frame(self, idx: int):
        if self._result is None or self._result.delta_r_cube is None:
            return
        cube = self._result.delta_r_cube
        if idx < 0 or idx >= cube.shape[0]:
            return
        frame = cube[idx].astype(np.float32)

        merge = self._view_seg.index() == 1  # Merge mode
        if merge and self._result.reference is not None:
            # Base = reference (grayscale DC image)
            ref = self._result.reference.astype(np.float32)
            self._compositor.set_base_frame(ref, cmap="gray")
            # Thermal overlay
            rgb = self._render_thermal_rgb(frame)
            if rgb is not None:
                self._last_thermal_rgb = rgb
                self._compositor.add_overlay(
                    "thermal", self._make_thermal_paint(rgb),
                    label="Thermal")
        else:
            # Pure thermal view — thermal is the base, no thermal overlay
            rgb = self._render_thermal_rgb(frame)
            if rgb is None:
                return
            self._compositor.set_base_frame(rgb)
            self._compositor.remove_overlay("thermal")

        # Push to detached viewer if open
        self._push_to_detached(idx)

    def _on_view_mode(self, idx: int):
        """Handle Thermal / Merge toggle."""
        self._show_frame(self._delay_slider.value())

    @staticmethod
    def _make_thermal_paint(rgb: np.ndarray):
        """Return a paint function that draws the thermal RGB as an overlay."""
        h, w = rgb.shape[:2]
        qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qi)
        def _paint(painter, img_size, frame_hw):
            scaled = pix.scaled(img_size, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled)
        return _paint

    def _paint_rois(self, painter, img_size, frame_hw):
        """Overlay paint function for ROI shapes (rect, ellipse, freeform)."""
        try:
            from acquisition.roi_model import roi_model
        except ImportError:
            return
        fh, fw = frame_hw
        iw, ih = img_size.width(), img_size.height()
        if fw <= 0 or fh <= 0:
            return
        sx, sy = iw / fw, ih / fh
        painter.setRenderHint(QPainter.Antialiasing, True)
        for roi in roi_model.rois:
            if roi.is_empty:
                continue
            color = QColor(roi.color or "#ffffff")
            color.setAlpha(200)
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            if roi.is_freeform and roi.vertices:
                poly = QPolygonF()
                for vx, vy in roi.vertices:
                    poly.append(QPointF(vx * sx, vy * sy))
                painter.drawPolygon(poly)
            elif roi.is_ellipse:
                painter.drawEllipse(int(roi.x * sx), int(roi.y * sy),
                                    int(roi.w * sx), int(roi.h * sy))
            else:
                painter.drawRect(int(roi.x * sx), int(roi.y * sy),
                                 int(roi.w * sx), int(roi.h * sy))
            if roi.label:
                painter.setFont(QFont(MONO_FONT, 8))
                painter.drawText(int(roi.x * sx) + 3, int(roi.y * sy) - 4,
                                 roi.label)

    # ---------------------------------------------------------------- #
    #  Save                                                             #
    # ---------------------------------------------------------------- #

    def _save(self):
        if self._result is None:
            return
        default_name = f"transient_{int(time.time())}.npz"
        if self._loaded_session_label:
            slug = self._loaded_session_label.replace(" ", "_")
            default_name = f"{slug}.npz"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Transient Cube",
            default_name,
            "NumPy archives (*.npz);;All files (*)")
        if not path:
            return
        try:
            save_kw: dict = {}
            if self._result.delta_r_cube is not None:
                save_kw["delta_r_cube"] = self._result.delta_r_cube
            if self._result.raw_cube is not None:
                save_kw["raw_cube"] = self._result.raw_cube
            if self._result.delay_times_s is not None:
                save_kw["delay_times_s"] = self._result.delay_times_s
            if self._result.reference is not None:
                save_kw["reference"] = self._result.reference
            np.savez_compressed(path, **save_kw)
            # Inform user about what was included
            contents = list(save_kw.keys())
            note = ""
            if self._loaded_session_label and "raw_cube" not in save_kw:
                note = "\n\nNote: raw_cube is not available for reloaded sessions."
            QMessageBox.information(
                self, "Saved",
                f"Transient cube saved to:\n{path}\n\n"
                f"Contents: {', '.join(contents)}{note}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    # ---------------------------------------------------------------- #
    #  Hardware readiness                                               #
    # ---------------------------------------------------------------- #

    # ---------------------------------------------------------------- #
    #  Voltage series helpers                                          #
    # ---------------------------------------------------------------- #

    def _vsweep_voltage_list(self) -> List[float]:
        """Compute the ordered list of voltages for the sweep."""
        start = self._vsweep_start.value()
        step  = self._vsweep_step.value()
        end   = self._vsweep_end.value()
        if step <= 0 or start > end:
            return []
        n = max(1, int(round((end - start) / step)) + 1)
        return [round(start + i * step, 6) for i in range(n)]

    def _update_vsweep_label(self):
        """Update the step-count summary label below the sweep spinboxes."""
        if not self._vsweep_box.isChecked():
            self._vsweep_n_lbl.setText("—")
            return
        vlist = self._vsweep_voltage_list()
        n = len(vlist)
        if n == 0:
            _warn = PALETTE['warning']
            self._vsweep_n_lbl.setText(
                f"<span style='color:{_warn};'>"
                "No steps — check start/end/step</span>")
        elif n == 1:
            self._vsweep_n_lbl.setText(f"1 step: {vlist[0]:.3f} V")
        else:
            self._vsweep_n_lbl.setText(
                f"{n} steps: {vlist[0]:.3f} – {vlist[-1]:.3f} V")

    # ---------------------------------------------------------------- #
    #  Time estimation                                                   #
    # ---------------------------------------------------------------- #

    def _update_time_est(self):
        """Recompute and display estimated acquisition time."""
        n_delays  = self._n_delays.value()
        n_avg     = self._n_avg.value()

        # Trigger cycle time from FPGA frequency, fallback 1 kHz (1 ms)
        try:
            from hardware.app_state import app_state
            fpga = app_state.fpga
            freq = getattr(fpga, 'frequency', 1000.0) if fpga else 1000.0
        except Exception:
            freq = 1000.0
        cycle = 1.0 / max(freq, 1.0)  # seconds

        total = n_delays * n_avg * cycle

        # Voltage sweep multiplier
        if self._vsweep_box.isChecked():
            vlist = self._vsweep_voltage_list()
            n_vsteps = max(len(vlist), 1)
            total *= n_vsteps

        # 10% overhead for readout/processing
        total *= 1.10

        parts = [f"{n_delays} delays × {n_avg} avg × {cycle*1000:.2f} ms/cycle"]
        if self._vsweep_box.isChecked():
            parts.append(f"× {n_vsteps} V-steps")
        parts.append("+ 10% overhead")
        detail = " ".join(parts)
        self._time_est_lbl.set_estimate(total, detail)

    def _start_vsweep(self, voltages: List[float], cam, fpga, bias):
        """Launch the voltage-series sweep worker thread."""
        self._vsweep_results     = []
        self._sweep_abort_flag   = False
        self._sweep_status       = None
        self._sweep_complete_result = None

        params = dict(
            n_delays         = self._n_delays.value(),
            delay_start_s    = self._delay_start.value() / 1000.0,
            delay_end_s      = self._delay_end.value() / 1000.0,
            pulse_dur_us     = self._pulse_us.value(),
            n_averages       = self._n_avg.value(),
            drift_correction = self._drift_cb.isChecked(),
            delay_times_s    = self._build_delay_times(),
        )
        n_v = len(voltages)

        def worker():
            try:
                for i, v in enumerate(voltages):
                    if self._sweep_abort_flag:
                        self._sweep_status = "Sweep aborted."
                        break

                    self._sweep_status = (
                        f"Step {i + 1}/{n_v} — setting {v:.3f} V…")

                    try:
                        bias.set_level(v)
                        bias.enable()
                        time.sleep(0.10)   # 100 ms settle
                    except Exception as exc:
                        log.warning("Bias set_level(%.3f V) failed: %s", v, exc)

                    self._sweep_status = (
                        f"Step {i + 1}/{n_v} — acquiring at {v:.3f} V…")
                    try:
                        self._pipeline = TransientAcquisitionPipeline(cam,
                                                                      fpga=fpga,
                                                                      bias=bias)
                        result = self._pipeline.run(**params)
                        self._vsweep_results.append((v, result))
                    except Exception as exc:
                        # Log and continue to next voltage step; bias will still
                        # be disabled in the finally block.
                        log.warning("Step %.3f V pipeline failed: %s", v, exc)

            finally:
                # Guarantee bias is disabled after last step, on abort,
                # or on any unhandled exception — whichever comes first.
                try:
                    bias.disable()
                except Exception:
                    log.warning("TransientTab vsweep worker: bias.disable() failed "
                                "in finally block — bias may still be active",
                                exc_info=True)

            if not self._sweep_abort_flag and self._vsweep_results:
                _, last_result = self._vsweep_results[-1]
                last_result.notes = (
                    f"Voltage series  {n_v} steps  "
                    f"({voltages[0]:.3f}–{voltages[-1]:.3f} V)  "
                    f"displayed: last step {voltages[-1]:.3f} V")
                # Post completion to main thread via timer (lock-protected write)
                with self._sweep_lock:
                    self._sweep_complete_result = last_result

        self._vsweep_thread = threading.Thread(target=worker, daemon=True)
        self._vsweep_thread.start()

        self._timer.start()
        n_label = f"{n_v} V-step sweep"
        self._btn_runner.set_running(True, n_label)
        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._save_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status_lbl.setText(f"Starting {n_label}…")
        self._delay_slider.setEnabled(False)

        try:
            from hardware.app_state import app_state
            app_state.active_modality = "transient"
        except Exception:
            log.debug("TransientTab._start_vsweep: could not set active_modality",
                      exc_info=True)

    # ---------------------------------------------------------------- #
    #  Hardware readiness                                               #
    # ---------------------------------------------------------------- #

    def _refresh_hw(self):
        try:
            from hardware.app_state import app_state
            ok  = f"color:{PALETTE['success']};"
            wrn = f"color:{PALETTE['warning']};"
            dim = f"color:{PALETTE['textDim']};"
            base = (f"font-family:{MONO_FONT}; "
                    f"font-size:{FONT['caption']}pt; ")

            self._hw_cam_lbl.setText("Connected" if app_state.cam  else "—")
            self._hw_cam_lbl.setStyleSheet(
                base + (ok if app_state.cam else dim))

            fpga = app_state.fpga
            self._hw_fpga_lbl.setText("Connected" if fpga else "—")
            self._hw_fpga_lbl.setStyleSheet(
                base + (ok if fpga else dim))

            # HW trigger check
            has_trig = (fpga is not None and
                        getattr(fpga, 'supports_trigger_mode', lambda: False)())
            self._hw_trig_lbl.setText("Available" if has_trig else "SW fallback")
            self._hw_trig_lbl.setStyleSheet(
                base + (ok if has_trig else wrn))
        except Exception:
            log.debug("TransientTab._refresh_hw: could not read hardware state",
                      exc_info=True)

    def showEvent(self, e):
        self._refresh_hw()
        super().showEvent(e)

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    # ── Detached viewer ──────────────────────────────────────────

    _detached_viewer = None

    def _on_detach_viewer(self) -> None:
        """Open (or bring to front) a detached large viewer window."""
        if self._detached_viewer is not None:
            self._detached_viewer.raise_()
            self._detached_viewer.activateWindow()
            return
        from ui.widgets.detached_viewer import DetachedViewer
        self._detached_viewer = DetachedViewer("Transient — Playback")
        self._detached_viewer.closed.connect(self._on_viewer_closed)
        self._detached_viewer.show()

        # Push current frame immediately if available
        self._push_to_detached(self._delay_slider.value())

    def _on_viewer_closed(self) -> None:
        """Clean up reference when the detached viewer is closed."""
        self._detached_viewer = None

    def _push_to_detached(self, idx: int) -> None:
        """Send the current compositor pixmap to the detached viewer."""
        if self._detached_viewer is None:
            return
        try:
            pix = self._compositor.grab()
            n = self._delay_slider.maximum() + 1
            info = f"Delay {idx + 1}/{n}"
            # Provide raw data for cursor readout + colormap
            data = None
            cmap = ""
            if self._result is not None:
                cube = self._result.delta_r_cube
                if cube is not None and 0 <= idx < cube.shape[0]:
                    data = cube[idx].astype("float32")
                cmap = self._cmap_combo.currentText()
            self._detached_viewer.update_image(
                pix, info, data=data, cmap=cmap)
        except Exception:
            pass

    def _apply_styles(self):
        """Refresh inline stylesheets from the current PALETTE values."""
        mono_base = (f"font-family:{MONO_FONT}; "
                     f"font-size:{FONT['caption']}pt; ")
        for lbl in [self._hw_cam_lbl, self._hw_fpga_lbl, self._hw_trig_lbl]:
            lbl.setStyleSheet(mono_base + f"color:{PALETTE['textDim']};")
        self._status_lbl.setStyleSheet(
            mono_base + f"color:{PALETTE['textDim']};")
        self._delay_time_lbl.setStyleSheet(
            mono_base + f"color:{PALETTE['textDim']}; min-width:70px;")
        self._vsweep_n_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
        if hasattr(self, '_compositor'):
            self._compositor._apply_styles()
        # Compact result strip values
        for val in self._stats.values():
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['accent']};")
        if hasattr(self, '_curve'):
            self._curve._apply_styles()
        if hasattr(self, '_metrics_table'):
            self._metrics_table.setStyleSheet(
                f"QTableWidget {{ font-family:{MONO_FONT}; "
                f"font-size:{FONT['caption']}pt; "
                f"background:{PALETTE['bg']}; color:{PALETTE['text']}; }}"
                f"QHeaderView::section {{ font-size:{FONT['caption']}pt; "
                f"background:{PALETTE['surface']}; color:{PALETTE['textSub']}; "
                f"padding:2px 4px; }}")
        if hasattr(self, '_metrics_panel'):
            self._metrics_panel._apply_styles()
        self._refresh_hw()

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _build_delay_times(self) -> Optional[np.ndarray]:
        """
        Build the delay time array in seconds using the current sweep mode.

        Returns
        -------
        np.ndarray or None
            None means the pipeline will fall back to np.linspace (same result
            as Linear mode but computed internally).  We always return an array
            so the mode is always explicit.
        """
        n      = self._n_delays.value()
        start  = self._delay_start.value() / 1000.0  # ms → s
        stop   = self._delay_end.value()   / 1000.0

        if self._sweep_log_rb.isChecked():
            # Logarithmic spacing — start must be > 0
            if start <= 0.0:
                # Clamp to a small positive value and warn
                clamped = max(stop / 1e6, 1e-9)
                log.warning(
                    "Log sweep: delay start (%.4f ms) must be > 0; "
                    "clamping to %.2e s", self._delay_start.value(), clamped)
                start = clamped
            return np.geomspace(start, stop, n)
        else:
            return np.linspace(start, stop, n)
