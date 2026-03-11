"""
ui/tabs/autofocus_tab.py

AutofocusTab — automated Z-focus sweep with live focus-curve plot.
FocusPlot     — custom widget that draws focus score vs Z position.
"""

from __future__ import annotations

import time
import threading
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QProgressBar, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QComboBox, QTextEdit, QSizePolicy)
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import QPainter, QColor, QPen, QFont, QBrush

from hardware.app_state  import app_state
from hardware.autofocus  import create_autofocus, AfState
from ui.theme      import FONT, PALETTE, progress_bar_qss
from ui.font_utils import mono_font
from ui.icons import set_btn_icon

# Module-level autofocus driver (set by AutofocusTab._run())
af_driver = None


class AutofocusTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- Status row ----
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._state_w  = self._readout("STATE",     "IDLE",  "#555")
        self._best_z_w = self._readout("BEST Z",    "--",    "#00d4aa")
        self._score_w  = self._readout("SCORE",     "--",    "#ffaa44")
        self._time_w   = self._readout("TIME",      "--",    "#6699ff")
        for w in [self._state_w, self._best_z_w,
                  self._score_w, self._time_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # ---- Settings + Plot side by side ----
        mid = QHBoxLayout()
        root.addLayout(mid)

        # Settings
        cfg_box = QGroupBox("Settings")
        cl = QGridLayout(cfg_box)
        cl.setSpacing(8)

        from ui.help import help_label

        def row(label, widget, r, topic=None):
            lbl_widget = help_label(label, topic) if topic else self._sub(label)
            cl.addWidget(lbl_widget, r, 0)
            cl.addWidget(widget,     r, 1)

        self._strategy = QComboBox()
        for s in ["sweep", "hill_climb"]:
            self._strategy.addItem(s)
        row("Strategy", self._strategy, 0, "autofocus")

        self._metric = QComboBox()
        for m in ["laplacian","tenengrad","normalized","fft","brenner"]:
            self._metric.addItem(m)
        row("Focus metric", self._metric, 1)

        self._z_start = self._dspin(-2000, 0,     -500, "μm")
        self._z_end   = self._dspin(0,     2000,   500, "μm")
        row("Z start (rel)", self._z_start, 2, "af_sweep_range")
        row("Z end (rel)",   self._z_end,   3)

        self._coarse = self._dspin(1, 500,  50, "μm")
        self._fine   = self._dspin(0.1, 50,  5, "μm")
        row("Coarse step", self._coarse, 4)
        row("Fine step",   self._fine,   5)

        self._n_avg    = QSpinBox()
        self._n_avg.setRange(1, 20)
        self._n_avg.setValue(2)
        self._n_avg.setFixedWidth(80)
        row("Avg frames", self._n_avg, 6)

        self._settle = QSpinBox()
        self._settle.setRange(0, 2000)
        self._settle.setValue(50)
        self._settle.setSuffix(" ms")
        self._settle.setFixedWidth(80)
        row("Settle delay", self._settle, 7)

        # ── Objective Z-range preset button (row 8) ───────────────────
        self._obj_preset_btn = QPushButton("Use Objective Z-Range")
        set_btn_icon(self._obj_preset_btn, "fa5s.crosshairs")
        self._obj_preset_btn.setToolTip(
            "Auto-fill Z start / end / step from the active objective's\n"
            "working distance.  Requires a motorized turret to be connected.")
        self._obj_preset_btn.clicked.connect(self._apply_objective_preset)
        cl.addWidget(self._obj_preset_btn, 8, 0, 1, 2)

        self._obj_preset_lbl = QLabel("")
        self._obj_preset_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            f"padding-left:2px;")
        cl.addWidget(self._obj_preset_lbl, 9, 0, 1, 2)

        mid.addWidget(cfg_box, 1)

        # Focus curve plot
        plot_box = QGroupBox("Focus Curve")
        pl = QVBoxLayout(plot_box)
        self._plot = FocusPlot()
        pl.addWidget(self._plot)
        mid.addWidget(plot_box, 2)

        # ---- Run controls ----
        ctrl = QHBoxLayout()
        self._run_btn   = QPushButton("Run Autofocus")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setObjectName("primary")
        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", "#ff6666")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setEnabled(False)
        self._run_btn.setFixedWidth(150)
        self._abort_btn.setFixedWidth(100)
        ctrl.addWidget(self._run_btn)
        ctrl.addWidget(self._abort_btn)
        ctrl.addStretch()
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setFixedWidth(300)
        self._prog.setStyleSheet(progress_bar_qss())
        ctrl.addWidget(self._prog)
        root.addLayout(ctrl)

        # ---- Log ----
        log_box = QGroupBox("Log")
        ll = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(80)
        self._log.setMaximumHeight(140)
        ll.addWidget(self._log)
        root.addWidget(log_box)

        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _dspin(self, lo, hi, val, suffix=""):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setDecimals(1)
        s.setSingleStep(10)
        s.setFixedWidth(100)
        if suffix:
            s.setSuffix(f" {suffix}")
        return s

    # ── Objective Z-range preset ──────────────────────────────────────

    def showEvent(self, e):
        self._refresh_obj_label()
        super().showEvent(e)

    def _refresh_obj_label(self):
        """Update the objective preset label to show the active objective."""
        obj = app_state.active_objective
        if obj is not None:
            self._obj_preset_lbl.setText(
                f"Active: {obj.label}  (WD {obj.working_dist_mm:.1f} mm)")
        else:
            self._obj_preset_lbl.setText("No objective active (turret not connected)")

    def _apply_objective_preset(self):
        """
        Set Z-start, Z-end, coarse step, and fine step based on the
        active objective's working distance.
        """
        obj = app_state.active_objective
        if obj is None:
            self.log("No active objective — connect a motorized turret first.")
            return

        wd_um   = obj.working_dist_mm * 1000.0      # working distance in µm
        # Sweep ±(WD / 3), capped at ±2000 µm (spinbox maximum)
        z_half  = min(wd_um / 3.0, 2000.0)
        # Coarse step ≈ z_half / 10 (10 steps covers the range), clamped
        coarse  = max(5.0,   min(z_half / 10.0, 200.0))
        # Fine step ≈ coarse / 10, clamped
        fine    = max(0.5,   min(coarse  / 10.0, 20.0))

        self._z_start.setValue(-z_half)
        self._z_end.setValue(  z_half)
        self._coarse.setValue(coarse)
        self._fine.setValue(  fine)

        self._obj_preset_lbl.setText(
            f"Applied {obj.label}  (WD {obj.working_dist_mm:.1f} mm)  →  "
            f"Z ±{z_half:.0f} µm  coarse {coarse:.0f} µm  fine {fine:.1f} µm")
        self.log(
            f"Objective preset applied: {obj.label}  "
            f"Z start={-z_half:.0f} µm  end=+{z_half:.0f} µm  "
            f"coarse={coarse:.0f} µm  fine={fine:.1f} µm")

    def _build_cfg(self) -> dict:
        """Read current UI settings into a config dict."""
        return {
            "driver":       "sweep" if self._strategy.currentText() == "sweep"
                            else "hill_climb",
            "strategy":     self._strategy.currentText(),
            "metric":       self._metric.currentText(),
            "z_start":      self._z_start.value(),
            "z_end":        self._z_end.value(),
            "coarse_step":  self._coarse.value(),
            "fine_step":    self._fine.value(),
            "n_avg":        self._n_avg.value(),
            "settle_ms":    self._settle.value(),
            "move_to_best": True,
        }

    def _run(self):
        global af_driver
        cam   = app_state.cam
        stage = app_state.stage
        if cam is None:
            self.log("No camera connected")
            return

        cfg = self._build_cfg()
        af_driver = create_autofocus(cfg, cam, stage)
        from ui.app_signals import signals
        af_driver.on_progress = lambda r: signals.af_progress.emit(r)
        af_driver.on_complete = lambda r: signals.af_complete.emit(r)

        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._prog.setValue(0)
        self._plot.clear()
        self.log(f"Starting {cfg['strategy']} autofocus "
                 f"(metric: {cfg['metric']})...")

        import threading
        threading.Thread(target=af_driver.run, daemon=True).start()

    def _abort(self):
        if af_driver:
            af_driver.abort()

    def _set_busy(self, busy):
        self._run_btn.setEnabled(not busy)
        self._abort_btn.setEnabled(busy)

    def update_progress(self, result):
        self._plot.set_data(result.z_positions, result.scores)
        self.log(result.message)

        # Estimate progress as fraction of z range covered
        if result.z_positions:
            z_arr  = result.z_positions
            z_span = abs(self._z_end.value() - self._z_start.value()) * 2
            covered = abs(max(z_arr) - min(z_arr))
            pct = min(int(covered / max(z_span, 1) * 100), 95)
            self._prog.setValue(pct)

        self._state_w._val.setText("RUNNING")
        self._state_w._val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")

    def update_complete(self, result):
        self._set_busy(False)
        self._prog.setValue(100)
        self._plot.set_data(result.z_positions, result.scores,
                            best_z=result.best_z)
        self.log(result.message)

        if result.state == AfState.COMPLETE:
            self._state_w._val.setText("COMPLETE ✓")
            self._state_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['success']};")
            self._best_z_w._val.setText(f"{result.best_z:.2f} μm")
            self._score_w._val.setText(f"{result.best_score:.4f}")
            self._time_w._val.setText(f"{result.duration_s:.1f} s")
        else:
            self._state_w._val.setText(result.state.name)
            self._state_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}]  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())


class FocusPlot(QWidget):
    """Live focus score vs Z plot with best-focus marker."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._z      = []
        self._scores = []
        self._best_z = None

    def clear(self):
        self._z      = []
        self._scores = []
        self._best_z = None
        self.repaint()

    def set_data(self, z, scores, best_z=None):
        self._z      = list(z)
        self._scores = list(scores)
        self._best_z = best_z
        self.repaint()

    def paintEvent(self, e):
        p   = QPainter(self)
        W   = self.width()
        H   = self.height()
        pad = 40

        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        if len(self._z) < 2:
            p.setPen(QPen(QColor(60, 60, 60)))
            p.setFont(mono_font(14))
            p.drawText(W//2 - 80, H//2, "No data yet")
            p.end()
            return

        z_min, z_max = min(self._z), max(self._z)
        s_min, s_max = min(self._scores), max(self._scores)
        z_span = max(z_max - z_min, 1e-6)
        s_span = max(s_max - s_min, 1e-6)

        def tx(z): return int(pad + (z - z_min) / z_span * (W - 2*pad))
        def ty(s): return int(H - pad - (s - s_min) / s_span * (H - 2*pad))

        # Grid
        p.setFont(mono_font(11))
        for i in range(5):
            frac = i / 4
            y    = int(pad + frac * (H - 2*pad))
            sv   = s_max - frac * s_span
            p.setPen(QPen(QColor(35, 35, 35)))
            p.drawLine(pad, y, W - pad, y)
            p.setPen(QPen(QColor(70, 70, 70)))
            p.drawText(2, y + 4, f"{sv:.3f}")

        for i in range(5):
            frac = i / 4
            x    = int(pad + frac * (W - 2*pad))
            zv   = z_min + frac * z_span
            p.setPen(QPen(QColor(35, 35, 35)))
            p.drawLine(x, pad, x, H - pad)
            p.setPen(QPen(QColor(70, 70, 70)))
            p.drawText(x - 15, H - 5, f"{zv:.0f}")

        # Score curve
        p.setPen(QPen(QColor(0, 212, 170), 2))
        pts = [(tx(z), ty(s)) for z, s in zip(self._z, self._scores)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

        # Data points
        p.setBrush(QBrush(QColor(0, 212, 170)))
        for x, y in pts:
            p.drawEllipse(x-3, y-3, 6, 6)

        # Best-focus marker
        if self._best_z is not None:
            bx = tx(self._best_z)
            p.setPen(QPen(QColor(255, 170, 68), 1, Qt.DashLine))
            p.drawLine(bx, pad, bx, H - pad)
            p.setPen(QPen(QColor(255, 170, 68)))
            p.setFont(mono_font(12))
            p.drawText(bx + 4, pad + 14,
                       f"best: {self._best_z:.1f}μm")

        # Axis labels
        p.setPen(QPen(QColor(80, 80, 80)))
        p.setFont(mono_font(12))
        p.drawText(W//2 - 20, H - 1, "Z position (μm)")

        p.end()
