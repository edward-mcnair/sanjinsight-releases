"""
acquisition/calibration_tab.py

CalibrationTab — full UI for thermoreflectance calibration.

Left panel  : Temperature sequence setup + run controls + progress
Right panel : C_T coefficient map, R² map, coverage stats, save/load
"""

import os, time
import numpy as np
from typing import Optional

from ui.button_utils import RunningButton, apply_hand_cursor

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QTextEdit, QFileDialog, QSplitter, QFrame, QTabWidget,
    QSizePolicy, QToolButton, QScrollArea, QMessageBox, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import (QImage, QPixmap, QPainter, QPen, QColor,
                           QBrush, QFont, QLinearGradient)

from .calibration        import Calibration, CalibrationResult
from .calibration_runner import CalibrationRunner, CalibrationProgress
from .processing         import to_display


# ------------------------------------------------------------------ #
#  Colourbar widget                                                   #
# ------------------------------------------------------------------ #

class ColourBar(QWidget):
    """Horizontal colour bar with min/max labels."""

    def __init__(self, lo=0.0, hi=1.0, label="", fmt=".2e"):
        super().__init__()
        self.setFixedHeight(28)
        self._lo  = lo
        self._hi  = hi
        self._lbl = label
        self._fmt = fmt

    def set_range(self, lo, hi):
        self._lo = lo
        self._hi = hi
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        pad  = 50

        grad = QLinearGradient(pad, 0, W - pad, 0)
        grad.setColorAt(0.0, QColor(  0,   0, 255))
        grad.setColorAt(0.5, QColor(  0,   0,   0))
        grad.setColorAt(1.0, QColor(255,   0,   0))

        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRect(pad, 4, W - 2*pad, H - 8)

        p.setPen(QPen(QColor(120, 120, 120)))
        p.setFont(QFont("Menlo", 11))
        lo_s = format(self._lo, self._fmt)
        hi_s = format(self._hi, self._fmt)
        p.drawText(0, H - 2, lo_s)
        p.drawText(W - pad + 4, H - 2, hi_s)
        if self._lbl:
            p.drawText(W // 2 - 30, H - 2, self._lbl)

        p.end()


# ------------------------------------------------------------------ #
#  Map viewer pane                                                     #
# ------------------------------------------------------------------ #

class MapPane(QWidget):
    """Displays a float32 map with a colour bar and stats."""

    def __init__(self, title=""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        self._img_lbl = QLabel()
        self._img_lbl.setMinimumSize(300, 220)
        self._img_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img_lbl.setStyleSheet(
            "background:#0d0d0d; border:1px solid #2a2a2a;")
        self._img_lbl.setAlignment(Qt.AlignCenter)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(
            "font-size:12pt; color:#555; letter-spacing:1px;")

        self._bar  = ColourBar()
        self._stat = QLabel("")
        self._stat.setAlignment(Qt.AlignCenter)
        self._stat.setStyleSheet(
            "font-family:Menlo,monospace; font-size:12pt; color:#444;")

        lay.addWidget(self._img_lbl)
        lay.addWidget(self._title_lbl)
        lay.addWidget(self._bar)
        lay.addWidget(self._stat)

    def show_map(self, data: np.ndarray,
                 mask: np.ndarray = None,
                 cmap: str = "diverging"):
        """Render float32 map to display."""
        if data is None:
            self._img_lbl.clear()
            return

        d = data.astype(np.float32)
        if mask is not None:
            valid = d[mask] if mask.any() else d.ravel()
        else:
            valid = d.ravel()

        lo = float(np.percentile(valid, 1))
        hi = float(np.percentile(valid, 99))
        self._bar.set_range(lo, hi)

        span = max(hi - lo, 1e-30)

        if cmap == "diverging":
            abs_lim = max(abs(lo), abs(hi))
            abs_lim = abs_lim or 1e-30
            normed  = np.clip(d / abs_lim, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            rgb = np.stack([r, g, b], axis=-1)
        elif cmap == "hot":
            scaled = np.clip((d - lo) / span * 255, 0, 255).astype(np.uint8)
            try:
                import cv2
                rgb = cv2.applyColorMap(scaled, cv2.COLORMAP_HOT)
            except Exception:
                rgb = np.stack([scaled, scaled, scaled], axis=-1)
        elif cmap == "viridis":
            scaled = np.clip((d - lo) / span * 255, 0, 255).astype(np.uint8)
            try:
                import cv2
                rgb = cv2.applyColorMap(scaled, cv2.COLORMAP_VIRIDIS)
            except Exception:
                rgb = np.stack([scaled, scaled, scaled], axis=-1)
        else:  # gray
            scaled = np.clip((d - lo) / span * 255, 0, 255).astype(np.uint8)
            rgb = np.stack([scaled, scaled, scaled], axis=-1)

        # Dim masked-out pixels
        if mask is not None:
            dimmed  = (rgb.astype(np.float32) * 0.15).astype(np.uint8)
            mask3   = np.stack([mask]*3, axis=-1)
            rgb     = np.where(mask3, rgb, dimmed)

        h, w = rgb.shape[:2]
        qi   = QImage(rgb.tobytes(), w, h, w*3, QImage.Format_RGB888)
        sz   = self._img_lbl.size()
        pix  = QPixmap.fromImage(qi).scaled(
            sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img_lbl.setPixmap(pix)

        n_valid = int(mask.sum()) if mask is not None else d.size
        pct     = 100.0 * n_valid / d.size
        self._stat.setText(
            f"min {lo:.3e}   max {hi:.3e}   "
            f"μ {float(np.mean(valid)):.3e}   "
            f"valid px {pct:.1f}%")

    def clear(self):
        self._img_lbl.clear()
        self._stat.setText("")


# ------------------------------------------------------------------ #
#  Calibration tab                                                    #
# ------------------------------------------------------------------ #

class CalibrationTab(QWidget):

    def __init__(self):
        super().__init__()
        self._runner   = None
        self._result   = None    # last CalibrationResult
        self._temp_rows = []     # list of QDoubleSpinBox widgets

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([340, 860])

    # ---------------------------------------------------------------- #
    #  Left panel — setup + controls                                   #
    # ---------------------------------------------------------------- #

    def _build_left(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(300)
        w.setMaximumWidth(380)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        # ---- Temperature sequence ----
        seq_box = QGroupBox("Temperature Sequence  (°C)")
        sl = QVBoxLayout(seq_box)

        # Preset buttons
        pre_row = QHBoxLayout()
        for label, temps in [
            ("3-pt",  [25.0, 35.0, 45.0]),
            ("5-pt",  [25.0, 30.0, 35.0, 40.0, 45.0]),
            ("7-pt",  [25.0, 28.0, 31.0, 34.0, 37.0, 40.0, 43.0]),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(lambda _, t=temps: self._set_preset(t))
            pre_row.addWidget(b)
        sl.addLayout(pre_row)

        # Scrollable temp list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(180)
        scroll.setStyleSheet("QScrollArea { border:none; }")
        self._seq_container = QWidget()
        self._seq_layout    = QVBoxLayout(self._seq_container)
        self._seq_layout.setContentsMargins(0, 0, 0, 0)
        self._seq_layout.setSpacing(3)
        self._seq_layout.addStretch()
        scroll.setWidget(self._seq_container)
        sl.addWidget(scroll)

        add_row = QHBoxLayout()
        self._add_temp_spin = QDoubleSpinBox()
        self._add_temp_spin.setRange(-20, 100)
        self._add_temp_spin.setValue(25.0)
        self._add_temp_spin.setSuffix(" °C")
        self._add_temp_spin.setFixedWidth(100)
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_temp)
        add_row.addWidget(self._add_temp_spin)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        sl.addLayout(add_row)
        lay.addWidget(seq_box)

        # ---- Capture settings ----
        cfg_box = QGroupBox("Capture Settings")
        cl = QGridLayout(cfg_box)
        cl.setSpacing(6)

        def row(lbl, widget, r):
            cl.addWidget(self._sub(lbl), r, 0)
            cl.addWidget(widget, r, 1)

        self._n_avg     = QSpinBox();   self._n_avg.setRange(5, 200)
        self._n_avg.setValue(20);       self._n_avg.setFixedWidth(80)

        self._settle    = QDoubleSpinBox(); self._settle.setRange(1, 300)
        self._settle.setValue(30.0);        self._settle.setSuffix(" s")
        self._settle.setFixedWidth(90)

        self._stable_tol = QDoubleSpinBox(); self._stable_tol.setRange(0.01, 2.0)
        self._stable_tol.setValue(0.2);      self._stable_tol.setSuffix(" °C")
        self._stable_tol.setFixedWidth(90)

        self._stable_dur = QDoubleSpinBox(); self._stable_dur.setRange(1, 60)
        self._stable_dur.setValue(5.0);      self._stable_dur.setSuffix(" s")
        self._stable_dur.setFixedWidth(90)

        self._min_r2 = QDoubleSpinBox(); self._min_r2.setRange(0.1, 1.0)
        self._min_r2.setValue(0.80);     self._min_r2.setDecimals(2)
        self._min_r2.setFixedWidth(80)

        row("Avg frames/step",  self._n_avg,       0)
        row("Max settle time",  self._settle,      1)
        row("Stable tolerance", self._stable_tol,  2)
        row("Stable duration",  self._stable_dur,  3)
        row("Min R² threshold", self._min_r2,      4)
        lay.addWidget(cfg_box)

        # ---- Run controls ----
        run_box = QGroupBox("Run")
        rl = QVBoxLayout(run_box)

        self._run_btn   = QPushButton("▶  Run Calibration")
        self._run_btn.setObjectName("primary")
        self._abort_btn = QPushButton("■  Abort")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setEnabled(False)
        self._run_btn.setFixedHeight(34)
        self._abort_btn.setFixedHeight(32)
        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

        self._btn_runner = RunningButton(self._run_btn, idle_text="▶  Run Calibration")
        apply_hand_cursor(self._abort_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)

        self._step_lbl = QLabel("Ready")
        self._step_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        self._step_lbl.setWordWrap(True)

        rl.addWidget(self._run_btn)
        rl.addWidget(self._abort_btn)
        rl.addWidget(self._progress)
        rl.addWidget(self._step_lbl)
        lay.addWidget(run_box)
        lay.addStretch()

        # Load default temps
        self._set_preset([25.0, 30.0, 35.0, 40.0, 45.0])
        return w

    # ---------------------------------------------------------------- #
    #  Right panel — results                                           #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # ---- Stats row ----
        stats_box = QGroupBox("Calibration Stats")
        sl = QHBoxLayout(stats_box)
        self._stats = {}
        for key, label in [("state",    "State"),
                            ("t_range",  "T Range"),
                            ("n_pts",    "Points"),
                            ("valid_px", "Valid Pixels"),
                            ("ct_mean",  "Mean C_T"),
                            ("saved",    "Saved")]:
            w2 = QWidget()
            v  = QVBoxLayout(w2)
            v.setAlignment(Qt.AlignCenter)
            sub = QLabel(label)
            sub.setObjectName("sublabel")
            sub.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
            v.addWidget(sub)
            v.addWidget(val)
            w2._val = val
            sl.addWidget(w2)
            self._stats[key] = w2
        lay.addWidget(stats_box)

        # ---- Map tabs ----
        map_tabs = QTabWidget()
        map_tabs.setDocumentMode(True)

        self._ct_pane   = MapPane("C_T COEFFICIENT MAP  [1/K]")
        self._r2_pane   = MapPane("R² FIT QUALITY MAP")
        self._res_pane  = MapPane("RESIDUAL RMS MAP")

        # cmap selector
        cmap_row = QHBoxLayout()
        cmap_row.addWidget(QLabel("Colourmap:"))
        self._cmap_combo = QComboBox()
        for c in ["diverging", "hot", "viridis", "gray"]:
            self._cmap_combo.addItem(c)
        self._cmap_combo.setFixedWidth(100)
        self._cmap_combo.currentTextChanged.connect(self._redisplay)
        cmap_row.addWidget(self._cmap_combo)
        cmap_row.addStretch()

        ct_wrapper = QWidget()
        cw = QVBoxLayout(ct_wrapper)
        cw.setContentsMargins(4, 4, 4, 4)
        cw.addLayout(cmap_row)
        cw.addWidget(self._ct_pane)

        map_tabs.addTab(ct_wrapper,    " C_T Map ")
        map_tabs.addTab(self._r2_pane, " R² Map ")
        map_tabs.addTab(self._res_pane," Residual ")
        lay.addWidget(map_tabs, 1)

        # ---- Save / load ----
        file_box = QGroupBox("Calibration File")
        fl = QHBoxLayout(file_box)
        self._save_btn = QPushButton("💾  Save .cal")
        self._load_btn = QPushButton("📂  Load .cal")
        self._apply_btn = QPushButton("✓  Apply to Acquisitions")
        self._apply_btn.setObjectName("primary")
        self._apply_btn.setEnabled(False)
        self._file_lbl = QLabel("None loaded")
        self._file_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:12pt; color:#555;")
        for b in [self._save_btn, self._load_btn, self._apply_btn]:
            b.setFixedHeight(30)
            fl.addWidget(b)
        fl.addWidget(self._file_lbl, 1)
        lay.addWidget(file_box)

        self._save_btn.clicked.connect(self._save)
        self._load_btn.clicked.connect(self._load)
        self._apply_btn.clicked.connect(self._apply)

        return w

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def get_calibration(self) -> Optional[CalibrationResult]:
        """Return current (valid) calibration for use by acquisition."""
        return self._result if (self._result and self._result.valid) else None

    def update_progress(self, prog: CalibrationProgress):
        n      = prog.total_steps or 1
        pct    = int(prog.step / n * 100)
        states = {"settling": "🌡 Settling", "capturing": "📷 Capturing",
                  "moving":   "→ Moving",   "fitting":   "⚙ Fitting",
                  "complete": "✓ Complete", "error":     "✗ Error",
                  "aborted":  "■ Aborted"}
        label  = states.get(prog.state, prog.state.capitalize())

        self._progress.setValue(pct)
        self._step_lbl.setText(
            f"{label}  —  {prog.message}")
        self._stats["state"]._val.setText(label)
        self._stats["state"]._val.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:" +
            ("#00d4aa" if prog.state == "complete" else
             "#ff6666" if prog.state in ("error", "aborted") else "#ffaa44") + ";")

        if prog.result and prog.result.valid:
            self._show_result(prog.result)

    def update_complete(self, result: CalibrationResult):
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setValue(100 if result.valid else 0)

        if result.valid:
            self._result = result
            self._show_result(result)
            self._apply_btn.setEnabled(True)
        else:
            self._stats["state"]._val.setText("FAILED")

    # ---------------------------------------------------------------- #
    #  Temperature sequence helpers                                    #
    # ---------------------------------------------------------------- #

    def _set_preset(self, temps: list):
        self._clear_temps()
        for t in temps:
            self._add_temp_row(t)

    def _add_temp(self):
        self._add_temp_row(self._add_temp_spin.value())

    def _add_temp_row(self, t: float):
        row_w = QWidget()
        rl    = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        spin = QDoubleSpinBox()
        spin.setRange(-20, 100)
        spin.setValue(t)
        spin.setSuffix(" °C")
        spin.setFixedWidth(100)

        del_btn = QToolButton()
        del_btn.setText("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            "background:transparent; color:#555; border:none;")
        del_btn.clicked.connect(lambda: self._remove_temp_row(row_w))

        rl.addWidget(spin)
        rl.addWidget(del_btn)
        rl.addStretch()

        idx = self._seq_layout.count() - 1
        self._seq_layout.insertWidget(idx, row_w)
        self._temp_rows.append((row_w, spin))

    def _remove_temp_row(self, row_w):
        self._temp_rows = [(rw, sp) for rw, sp in self._temp_rows
                           if rw is not row_w]
        self._seq_layout.removeWidget(row_w)
        row_w.deleteLater()

    def _clear_temps(self):
        for row_w, _ in self._temp_rows:
            self._seq_layout.removeWidget(row_w)
            row_w.deleteLater()
        self._temp_rows.clear()

    def _get_temperatures(self) -> list:
        return sorted([sp.value() for _, sp in self._temp_rows])

    # ---------------------------------------------------------------- #
    #  Run                                                              #
    # ---------------------------------------------------------------- #

    def _build_cfg(self) -> dict:
        return {
            "temperatures": self._get_temperatures(),
            "n_avg":        self._n_avg.value(),
            "settle_s":     self._settle.value(),
            "stable_tol":   self._stable_tol.value(),
            "stable_dur":   self._stable_dur.value(),
            "min_r2":       self._min_r2.value(),
        }

    def _run(self):
        from .calibration_runner import CalibrationRunner
        import threading

        # Import globals from app_state at runtime to avoid circular imports
        try:
            from hardware.app_state import app_state
            _cam  = app_state.cam
            _tecs = app_state.tecs
        except Exception:
            _cam  = None
            _tecs = []

        cfg = self._build_cfg()
        if len(cfg["temperatures"]) < 2:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Calibration",
                                "Add at least 2 temperature steps.")
            return

        self._runner = CalibrationRunner(_cam, _tecs, cfg)

        # Connect progress via signals to stay on GUI thread
        try:
            from ui.app_signals import signals
            self._runner.on_progress = \
                lambda p: signals.cal_progress.emit(p)
            self._runner.on_complete = \
                lambda r: signals.cal_complete.emit(r)
        except Exception:
            pass

        self._btn_runner.set_running(True, "Calibrating")
        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._progress.setValue(0)
        self._ct_pane.clear()
        self._r2_pane.clear()

        n = len(cfg["temperatures"])
        self._stats["n_pts"]._val.setText(str(n))
        self._stats["t_range"]._val.setText(
            f"{cfg['temperatures'][0]:.0f}–"
            f"{cfg['temperatures'][-1]:.0f}°C")

        threading.Thread(target=self._runner.run, daemon=True).start()

    def _abort(self):
        if self._runner:
            self._runner.abort()

    # ---------------------------------------------------------------- #
    #  Display result                                                   #
    # ---------------------------------------------------------------- #

    def _show_result(self, result: CalibrationResult):
        cmap = self._cmap_combo.currentText()
        self._ct_pane.show_map(result.ct_map,  result.mask, cmap=cmap)
        self._r2_pane.show_map(result.r2_map,  result.mask, cmap="viridis")
        self._res_pane.show_map(result.residual_map, result.mask, cmap="hot")

        valid_pct = 100.0 * result.mask.mean() if result.mask is not None else 0
        ct_mean   = (float(result.ct_map[result.mask].mean())
                     if (result.mask is not None and result.mask.any())
                     else 0.0)

        self._stats["valid_px"]._val.setText(f"{valid_pct:.1f}%")
        self._stats["ct_mean"]._val.setText(f"{ct_mean:.3e}")
        self._stats["state"]._val.setText("COMPLETE ✓")
        self._stats["state"]._val.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")

    def _redisplay(self):
        if self._result and self._result.valid:
            self._show_result(self._result)

    # ---------------------------------------------------------------- #
    #  Save / load / apply                                              #
    # ---------------------------------------------------------------- #

    def _save(self):
        if not (self._result and self._result.valid):
            QMessageBox.warning(self, "No calibration",
                                "Run a calibration first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration", "calibration.cal",
            "Calibration files (*.cal *.npz);;All files (*)")
        if not path:
            return
        saved = self._result.save(path)
        self._file_lbl.setText(os.path.basename(saved))
        self._stats["saved"]._val.setText("Saved ✓")
        self._stats["saved"]._val.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Calibration", "",
            "Calibration files (*.cal *.npz);;All files (*)")
        if not path:
            return
        try:
            result = CalibrationResult.load(path)
            self._result = result
            self._show_result(result)
            self._apply_btn.setEnabled(True)
            self._file_lbl.setText(os.path.basename(path))
            valid_pct = 100.0 * result.mask.mean() if result.mask is not None else 0
            self._stats["n_pts"]._val.setText(str(result.n_points))
            self._stats["t_range"]._val.setText(
                f"{result.t_min:.0f}–{result.t_max:.0f}°C")
            self._stats["valid_px"]._val.setText(f"{valid_pct:.1f}%")
            self._stats["saved"]._val.setText("Loaded ✓")
            self._stats["saved"]._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        except Exception as e:
            QMessageBox.critical(self, "Load Failed", str(e))

    def _apply(self):
        """Store calibration in app_state for use by AcquireTab."""
        try:
            from hardware.app_state import app_state
            app_state.active_calibration = self._result
            self._stats["saved"]._val.setText("Applied ✓")
            self._stats["saved"]._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        except Exception as e:
            QMessageBox.warning(self, "Apply Failed", str(e))

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
