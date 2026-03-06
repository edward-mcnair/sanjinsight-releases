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
from ui.theme import FONT, PALETTE

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QSlider, QSplitter, QSizePolicy, QFileDialog, QMessageBox,
    QCheckBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui  import QImage, QPixmap, QPainter, QPen, QColor, QFont

from ui.font_utils import mono_font, sans_font
from .transient_pipeline import (
    TransientAcquisitionPipeline, TransientAcqState,
    TransientProgress, TransientResult)
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

        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        if self._values is None or len(self._values) < 2:
            p.setPen(QColor(50, 50, 50))
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
            p.setPen(QPen(QColor(55, 55, 55), 1, Qt.DotLine))
            p.drawLine(PAD, zy, W - PAD, zy)

        # Cursor line (selected delay)
        if 0 <= self._cursor_idx < n:
            cx = _x(self._cursor_idx)
            p.setPen(QPen(QColor(255, 170, 60, 140), 1, Qt.DashLine))
            p.drawLine(cx, PAD, cx, H - PAD - 14)

        # Curve
        pen = QPen(QColor(0, 212, 170), 1, Qt.SolidLine)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        pts = [(_x(i), _y(float(v) if np.isfinite(v) else lo))
               for i, v in enumerate(vals)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

        # X-axis label (first and last delay in ms)
        p.setPen(QColor(80, 80, 80))
        p.setFont(mono_font(8))
        if self._times_s is not None and len(self._times_s) >= 2:
            t0 = self._times_s[0] * 1e3
            t1 = self._times_s[-1] * 1e3
            p.drawText(PAD, H - 4, f"{t0:.2f} ms")
            p.drawText(W - 64, H - 4, f"{t1:.2f} ms")

        # Value labels
        p.setPen(QColor(80, 80, 80))
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

    def __init__(self):
        super().__init__()
        self._pipeline: Optional[TransientAcquisitionPipeline] = None
        self._result:   Optional[TransientResult]              = None
        self._last_progress: Optional[TransientProgress]       = None

        # Voltage-series sweep state (written from worker thread, read by timer)
        self._vsweep_results: List[tuple]               = []   # [(v, TransientResult)]
        self._vsweep_thread:  Optional[threading.Thread] = None
        self._sweep_abort_flag: bool                    = False
        self._sweep_status: Optional[str]               = None  # thread → timer
        self._sweep_complete_result: Optional[TransientResult] = None

        # Poll timer
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([270, 700])
        root.addWidget(splitter, 1)

    # ---------------------------------------------------------------- #
    #  Left panel                                                       #
    # ---------------------------------------------------------------- #

    def _build_left(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(240)
        w.setMaximumWidth(300)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        # ── Timing ───────────────────────────────────────────────────
        tim_box = QGroupBox("Timing")
        tl = QGridLayout(tim_box)
        tl.setSpacing(6)

        self._n_delays = QSpinBox()
        self._n_delays.setRange(2, 500)
        self._n_delays.setValue(TRANSIENT_DEFAULT_N_DELAYS)
        self._n_delays.setFixedWidth(90)
        self._n_delays.setToolTip("Number of discrete delay steps in the output cube.")

        self._delay_start = QDoubleSpinBox()
        self._delay_start.setRange(0.0, 1000.0)
        self._delay_start.setValue(0.0)
        self._delay_start.setDecimals(3)
        self._delay_start.setSuffix(" ms")
        self._delay_start.setFixedWidth(100)
        self._delay_start.setToolTip("First delay from pulse leading edge (ms).")

        self._delay_end = QDoubleSpinBox()
        self._delay_end.setRange(0.001, 10000.0)
        self._delay_end.setValue(TRANSIENT_DEFAULT_DELAY_END_S * 1e3)
        self._delay_end.setDecimals(2)
        self._delay_end.setSuffix(" ms")
        self._delay_end.setFixedWidth(100)
        self._delay_end.setToolTip("Last delay from pulse leading edge (ms).")

        self._pulse_us = QDoubleSpinBox()
        self._pulse_us.setRange(1.0, 100_000.0)
        self._pulse_us.setValue(TRANSIENT_DEFAULT_PULSE_US)
        self._pulse_us.setDecimals(1)
        self._pulse_us.setSuffix(" µs")
        self._pulse_us.setFixedWidth(100)
        self._pulse_us.setToolTip(
            "Duration of each power pulse in microseconds.\n"
            "The FPGA fires this pulse, then waits `delay` before camera capture.")

        tl.addWidget(self._sub("Delays"),      0, 0)
        tl.addWidget(self._n_delays,           0, 1)
        tl.addWidget(self._sub("Delay start"), 1, 0)
        tl.addWidget(self._delay_start,        1, 1)
        tl.addWidget(self._sub("Delay end"),   2, 0)
        tl.addWidget(self._delay_end,          2, 1)
        tl.addWidget(self._sub("Pulse width"), 3, 0)
        tl.addWidget(self._pulse_us,           3, 1)
        lay.addWidget(tim_box)

        # ── Averaging ────────────────────────────────────────────────
        avg_box = QGroupBox("Averaging")
        al = QGridLayout(avg_box)
        al.setSpacing(6)

        self._n_avg = QSpinBox()
        self._n_avg.setRange(1, 1000)
        self._n_avg.setValue(TRANSIENT_DEFAULT_N_AVERAGES)
        self._n_avg.setFixedWidth(90)
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
                f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
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

        self._vsweep_start = QDoubleSpinBox()
        self._vsweep_start.setRange(-60.0, 60.0)
        self._vsweep_start.setValue(0.5)
        self._vsweep_start.setSuffix(" V")
        self._vsweep_start.setDecimals(3)
        self._vsweep_start.setFixedWidth(100)
        self._vsweep_start.setToolTip("First bias voltage in the sweep.")

        self._vsweep_step = QDoubleSpinBox()
        self._vsweep_step.setRange(0.001, 30.0)
        self._vsweep_step.setValue(0.5)
        self._vsweep_step.setSuffix(" V")
        self._vsweep_step.setDecimals(3)
        self._vsweep_step.setFixedWidth(100)
        self._vsweep_step.setToolTip("Voltage increment between steps.")

        self._vsweep_end = QDoubleSpinBox()
        self._vsweep_end.setRange(-60.0, 60.0)
        self._vsweep_end.setValue(3.0)
        self._vsweep_end.setSuffix(" V")
        self._vsweep_end.setDecimals(3)
        self._vsweep_end.setFixedWidth(100)
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

        # ── Run controls ──────────────────────────────────────────────
        run_box = QGroupBox("Run")
        rl = QVBoxLayout(run_box)

        self._run_btn   = QPushButton("Run Transient")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(34)
        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", "#ff6666")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setFixedHeight(32)
        self._abort_btn.setEnabled(False)

        self._btn_runner = RunningButton(
            self._run_btn, idle_text="▶  Run Transient")
        apply_hand_cursor(self._abort_btn)
        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']};")
        self._status_lbl.setWordWrap(True)

        rl.addWidget(self._run_btn)
        rl.addWidget(self._abort_btn)
        rl.addWidget(self._progress)
        rl.addWidget(self._status_lbl)
        lay.addWidget(run_box)

        # ── Save ──────────────────────────────────────────────────────
        self._save_btn = QPushButton("Save Cube…")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedHeight(30)
        self._save_btn.clicked.connect(self._save)
        lay.addWidget(self._save_btn)

        lay.addStretch()
        self._refresh_hw()
        return w

    # ---------------------------------------------------------------- #
    #  Right panel                                                      #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # ── Result stats ──────────────────────────────────────────────
        stats_box = QGroupBox("Result")
        sl = QHBoxLayout(stats_box)
        self._stats: dict = {}
        for key, label in [
            ("delays",  "Delays"),
            ("avgs",    "Averages"),
            ("dur",     "Duration"),
            ("hw_trig", "HW Trigger"),
            ("max_drr", "Peak |ΔR/R|"),
        ]:
            w2 = QWidget()
            v  = QVBoxLayout(w2)
            v.setAlignment(Qt.AlignCenter)
            sub = QLabel(label)
            sub.setObjectName("sublabel")
            sub.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt; "
                f"color:{PALETTE['accent']};")
            v.addWidget(sub)
            v.addWidget(val)
            sl.addWidget(w2)
            self._stats[key] = val
        lay.addWidget(stats_box)

        # ── Delay index slider + label ─────────────────────────────────
        slider_row = QHBoxLayout()
        slider_row.addWidget(self._sub("Delay index:"))
        self._delay_slider = QSlider(Qt.Horizontal)
        self._delay_slider.setRange(0, 49)
        self._delay_slider.setValue(0)
        self._delay_slider.setEnabled(False)
        self._delay_slider.valueChanged.connect(self._on_slider_changed)
        self._delay_time_lbl = QLabel("—")
        self._delay_time_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']}; min-width:70px;")
        slider_row.addWidget(self._delay_slider, 1)
        slider_row.addWidget(self._delay_time_lbl)
        lay.addLayout(slider_row)

        # ── ΔR/R frame at selected delay ──────────────────────────────
        img_box = QGroupBox("ΔR/R Frame at Selected Delay")
        il = QVBoxLayout(img_box)
        self._img_lbl = QLabel()
        self._img_lbl.setMinimumSize(400, 280)
        self._img_lbl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img_lbl.setStyleSheet(
            f"background:#0d0d0d; border:1px solid {PALETTE['border']};")
        self._img_lbl.setAlignment(Qt.AlignCenter)
        _dim  = PALETTE['textDim']
        _body = FONT['body']
        self._img_lbl.setText(
            f"<span style='color:{_dim};font-size:{_body}pt'>"
            f"Run Transient to capture</span>")
        il.addWidget(self._img_lbl)
        lay.addWidget(img_box, 1)

        # ── Mean ΔR/R vs time curve ───────────────────────────────────
        curve_box = QGroupBox("Mean ΔR/R vs Delay Time  (full-frame average)")
        cl = QVBoxLayout(curve_box)
        self._curve = TransientCurve()
        cl.addWidget(self._curve)
        lay.addWidget(curve_box)

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
        # ── Sweep thread status/completion (thread-safe reads) ────────
        sweep_msg = self._sweep_status
        if sweep_msg is not None:
            self._sweep_status = None
            self._status_lbl.setText(sweep_msg)

        sweep_done = self._sweep_complete_result
        if sweep_done is not None:
            self._sweep_complete_result = None
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
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setValue(100)
        self._save_btn.setEnabled(True)

        self._status_lbl.setText(
            f"Complete — {result.n_delays} delays × {result.n_averages} avg  "
            f"({'HW trigger' if result.hw_triggered else 'SW fallback'})")

        # Update stats
        self._stats["delays"].setText(str(result.n_delays))
        self._stats["avgs"].setText(str(result.n_averages))
        dur = getattr(result, 'duration_s', 0.0) or 0.0
        self._stats["dur"].setText(f"{dur:.1f} s")
        self._stats["hw_trig"].setText("Yes" if result.hw_triggered else "No (SW)")
        self._stats["hw_trig"].setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt; "
            f"color:{'#00d4aa' if result.hw_triggered else PALETTE['warning']};")

        # Delay slider
        n = result.n_delays
        self._delay_slider.setRange(0, max(n - 1, 0))
        self._delay_slider.setValue(0)
        self._delay_slider.setEnabled(True)

        # Mean curve
        if result.delta_r_cube is not None:
            cube = result.delta_r_cube
            means = np.nanmean(cube.reshape(n, -1), axis=1)
            self._curve.update_data(means, result.delay_times_s, 0)

            finite = cube[np.isfinite(cube)]
            if finite.size > 0:
                self._stats["max_drr"].setText(f"{float(np.abs(finite).max()):.3e}")

            self._show_frame(0)

        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            log.debug("TransientTab._on_complete: could not reset active_modality",
                      exc_info=True)

    # ---------------------------------------------------------------- #
    #  Frame / slice display                                           #
    # ---------------------------------------------------------------- #

    def _on_slider_changed(self, idx: int):
        if self._result is None:
            return
        if self._result.delay_times_s is not None and idx < len(self._result.delay_times_s):
            t_ms = self._result.delay_times_s[idx] * 1e3
            self._delay_time_lbl.setText(f"{t_ms:.3f} ms")

        # Update curve cursor
        if self._result.delta_r_cube is not None and self._result.delay_times_s is not None:
            n = self._result.n_delays
            means = np.nanmean(
                self._result.delta_r_cube.reshape(n, -1), axis=1)
            self._curve.update_data(means, self._result.delay_times_s, idx)

        self._show_frame(idx)

    def _show_frame(self, idx: int):
        if self._result is None or self._result.delta_r_cube is None:
            return
        cube = self._result.delta_r_cube
        if idx < 0 or idx >= cube.shape[0]:
            return
        frame = cube[idx].astype(np.float32)
        finite = frame[np.isfinite(frame)]
        if finite.size == 0:
            return
        limit = float(np.percentile(np.abs(finite), 99.5)) or 1e-9
        normed = np.clip(frame / limit, -1.0, 1.0)
        r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
        b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
        g = np.zeros_like(r)
        rgb = np.stack([r, g, b], axis=-1)
        h, w = rgb.shape[:2]
        qi  = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        px  = QPixmap.fromImage(qi)
        self._img_lbl.setPixmap(
            px.scaled(self._img_lbl.size(),
                      Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---------------------------------------------------------------- #
    #  Save                                                             #
    # ---------------------------------------------------------------- #

    def _save(self):
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Transient Cube",
            f"transient_{int(time.time())}.npz",
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
            QMessageBox.information(self, "Saved",
                                    f"Transient cube saved to:\n{path}")
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
                # Post completion to main thread via timer
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
            base = (f"font-family:Menlo,monospace; "
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

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
