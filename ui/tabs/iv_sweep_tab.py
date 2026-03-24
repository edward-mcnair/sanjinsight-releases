"""
ui/tabs/iv_sweep_tab.py — IV Sweep control panel for SanjINSIGHT.

Provides a UI for configuring and running automated IV sweeps synchronized
with thermoreflectance image capture.  Based on the Voltage-Current GPIB
Automation3.vi from SanjVIEW.

Wired into StimulusTab as a third sub-tab alongside Modulation and Bias.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QGroupBox, QProgressBar, QFileDialog, QFrame, QSizePolicy,
)

from ui.theme import FONT, PALETTE
from ui.icons import IC, set_btn_icon

log = logging.getLogger(__name__)


# ── Worker thread ─────────────────────────────────────────────────────────────

class _SweepWorker(QObject):
    """Runs IVSweeper.run() in a background thread."""

    progress  = pyqtSignal(int, int)          # current_step, total_steps
    finished  = pyqtSignal(object)            # IVSweepResult
    error     = pyqtSignal(str)

    def __init__(self, sweeper, config, parent=None):
        super().__init__(parent)
        self._sweeper = sweeper
        self._config  = config

    def run(self):
        from hardware.bias.iv_sweep import IVSweeper
        try:
            result = self._sweeper.run(
                self._config,
                on_progress=lambda cur, tot, *_: self.progress.emit(cur, tot),
            )
            self.finished.emit(result)
        except Exception as exc:
            log.exception("IV sweep error")
            self.error.emit(str(exc))


# ── Main tab widget ───────────────────────────────────────────────────────────

class IVSweepTab(QWidget):
    """
    IV Sweep control — configure mode, range, steps, and run synchronized
    bias-sweep + thermoreflectance capture.

    Public API
    ----------
    set_drivers(bias_driver, camera_driver, pipeline)
        Called when hardware becomes available; enables the Run button.
    on_sweep_complete(result: IVSweepResult)
        Optional callback; subclass or replace to add post-processing.
    """

    sweep_complete = pyqtSignal(object)    # IVSweepResult

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bias_driver   = None
        self._camera_driver = None
        self._pipeline      = None
        self._worker        = None
        self._thread        = None
        self._last_result   = None

        self._build_ui()
        self._apply_styles()

    # ── Hardware wiring ───────────────────────────────────────────────────────

    def set_drivers(self, bias_driver, camera_driver=None, pipeline=None):
        """Wire hardware drivers; enables the Run button when bias_driver is set."""
        self._bias_driver   = bias_driver
        self._camera_driver = camera_driver
        self._pipeline      = pipeline
        self._run_btn.setEnabled(bias_driver is not None)
        self._status_lbl.setText(
            "Ready" if bias_driver is not None else "No bias driver connected")

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(self._build_config_group())
        root.addWidget(self._build_output_group())
        root.addWidget(self._build_control_row())
        root.addWidget(self._build_status_bar())
        root.addStretch(1)

    def _build_config_group(self) -> QGroupBox:
        grp = QGroupBox("Sweep Configuration")
        grid = QGridLayout(grp)
        grid.setContentsMargins(12, 16, 12, 12)
        grid.setSpacing(8)

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('textDim','#8892aa')};")
            return l

        # Mode
        grid.addWidget(_lbl("Mode"), 0, 0)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Voltage Source", "Current Source"])
        grid.addWidget(self._mode_combo, 0, 1)

        # Sweep type
        grid.addWidget(_lbl("Sweep Type"), 0, 2)
        self._sweep_type_combo = QComboBox()
        self._sweep_type_combo.addItems(["Linear", "Log"])
        grid.addWidget(self._sweep_type_combo, 0, 3)

        # Start / Stop
        grid.addWidget(_lbl("Start (V / A)"), 1, 0)
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(-100.0, 100.0)
        self._start_spin.setDecimals(4)
        self._start_spin.setValue(0.0)
        self._start_spin.setSingleStep(0.1)
        grid.addWidget(self._start_spin, 1, 1)

        grid.addWidget(_lbl("Stop (V / A)"), 1, 2)
        self._stop_spin = QDoubleSpinBox()
        self._stop_spin.setRange(-100.0, 100.0)
        self._stop_spin.setDecimals(4)
        self._stop_spin.setValue(3.3)
        self._stop_spin.setSingleStep(0.1)
        grid.addWidget(self._stop_spin, 1, 3)

        # Steps / Dwell
        grid.addWidget(_lbl("Steps"), 2, 0)
        self._steps_spin = QSpinBox()
        self._steps_spin.setRange(2, 500)
        self._steps_spin.setValue(20)
        grid.addWidget(self._steps_spin, 2, 1)

        grid.addWidget(_lbl("Dwell (ms)"), 2, 2)
        self._dwell_spin = QDoubleSpinBox()
        self._dwell_spin.setRange(10.0, 60000.0)
        self._dwell_spin.setDecimals(0)
        self._dwell_spin.setValue(500.0)
        self._dwell_spin.setSingleStep(50.0)
        grid.addWidget(self._dwell_spin, 2, 3)

        # Compliance
        grid.addWidget(_lbl("Compliance (A / V)"), 3, 0)
        self._compliance_spin = QDoubleSpinBox()
        self._compliance_spin.setRange(1e-6, 10.0)
        self._compliance_spin.setDecimals(4)
        self._compliance_spin.setValue(0.1)
        self._compliance_spin.setSingleStep(0.01)
        grid.addWidget(self._compliance_spin, 3, 1)

        # Quiescent + pulsed
        grid.addWidget(_lbl("Quiescent (V / A)"), 3, 2)
        self._quiescent_spin = QDoubleSpinBox()
        self._quiescent_spin.setRange(-100.0, 100.0)
        self._quiescent_spin.setDecimals(4)
        self._quiescent_spin.setValue(0.0)
        grid.addWidget(self._quiescent_spin, 3, 3)

        self._pulsed_chk = QCheckBox("Return to quiescent between steps (pulsed mode)")
        self._pulsed_chk.setChecked(True)
        grid.addWidget(self._pulsed_chk, 4, 0, 1, 4)

        self._capture_frames_chk = QCheckBox("Capture thermoreflectance frame at each setpoint")
        self._capture_frames_chk.setChecked(True)
        grid.addWidget(self._capture_frames_chk, 5, 0, 1, 4)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return grp

    def _build_output_group(self) -> QGroupBox:
        grp = QGroupBox("Output")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self._save_chk = QCheckBox("Auto-save results after sweep")
        self._save_chk.setChecked(True)
        lay.addWidget(self._save_chk)

        row = QHBoxLayout()
        self._save_path_lbl = QLabel(
            f"Default: {os.path.join(os.path.expanduser('~'), 'microsanj_sweeps')}"
        )
        self._save_path_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE.get('textDim','#8892aa')};")
        row.addWidget(self._save_path_lbl, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn)
        lay.addLayout(row)

        return grp

    def _build_control_row(self) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._run_btn = QPushButton("  Run IV Sweep")
        self._run_btn.setFixedHeight(40)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        set_btn_icon(self._run_btn, IC.PLAY)
        lay.addWidget(self._run_btn, 1)

        self._stop_btn = QPushButton("  Stop")
        self._stop_btn.setFixedHeight(40)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        set_btn_icon(self._stop_btn, IC.STOP)
        lay.addWidget(self._stop_btn)

        self._export_btn = QPushButton("  Export CSV")
        self._export_btn.setFixedHeight(40)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export_csv)
        set_btn_icon(self._export_btn, IC.EXPORT_CSV)
        lay.addWidget(self._export_btn)

        return row

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.hide()
        lay.addWidget(self._progress_bar)

        self._status_lbl = QLabel("No bias driver connected")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE.get('textDim','#8892aa')};")
        lay.addWidget(self._status_lbl)

        return bar

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(self, "Save IV sweeps to…")
        if path:
            self._save_path_lbl.setText(path)

    def _on_run(self):
        if self._bias_driver is None:
            return

        from hardware.bias.iv_sweep import IVSweepConfig, IVSweeper

        mode_str        = "current" if self._mode_combo.currentIndex() == 1 else "voltage"
        sweep_type_str  = "log" if self._sweep_type_combo.currentIndex() == 1 else "linear"

        cfg = IVSweepConfig(
            mode                = mode_str,
            sweep_type          = sweep_type_str,
            start               = self._start_spin.value(),
            stop                = self._stop_spin.value(),
            n_steps             = self._steps_spin.value(),
            dwell_ms            = self._dwell_spin.value(),
            quiescent_level     = self._quiescent_spin.value(),
            compliance          = self._compliance_spin.value(),
            return_to_quiescent = self._pulsed_chk.isChecked(),
        )

        camera = self._camera_driver if self._capture_frames_chk.isChecked() else None
        pipeline = self._pipeline if self._capture_frames_chk.isChecked() else None
        sweeper = IVSweeper(self._bias_driver, camera, pipeline)

        self._worker = _SweepWorker(sweeper, cfg)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._status_lbl.setText(f"Running sweep — 0/{cfg.n_steps} steps")
        self._thread.start()

    def _on_stop(self):
        if self._worker is not None and hasattr(self._worker, "_sweeper"):
            try:
                self._worker._sweeper.abort()
            except Exception:
                pass
        self._status_lbl.setText("Sweep aborted")
        self._stop_btn.setEnabled(False)

    def _on_progress(self, current: int, total: int):
        pct = int(100 * current / max(total, 1))
        self._progress_bar.setValue(pct)
        self._status_lbl.setText(f"Sweeping — {current}/{total} steps")

    def _on_finished(self, result):
        self._last_result = result
        n = len(result.setpoints)
        aborted = " (aborted)" if result.aborted else ""
        self._status_lbl.setText(
            f"Sweep complete{aborted} — {n} setpoints captured")
        self._progress_bar.setValue(100)
        self._progress_bar.hide()
        self._export_btn.setEnabled(True)

        if self._save_chk.isChecked():
            self._auto_save(result)

        self.sweep_complete.emit(result)

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"⚠ Error: {msg}")
        self._progress_bar.hide()
        log.error("IV sweep error: %s", msg)

    def _cleanup_thread(self):
        self._run_btn.setEnabled(self._bias_driver is not None)
        self._stop_btn.setEnabled(False)
        # Always quit+wait before nulling — prevents QThread leak/crash
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None

    def _on_export_csv(self):
        if self._last_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export IV Sweep CSV", "iv_sweep.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            df = self._last_result.as_dataframe()
            if hasattr(df, "to_csv"):
                df.to_csv(path, index=False)
            else:
                import csv
                with open(path, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(df.keys()))
                    w.writeheader()
                    for row in zip(*df.values()):
                        w.writerow(dict(zip(df.keys(), row)))
            self._status_lbl.setText(f"Exported → {os.path.basename(path)}")
        except Exception as exc:
            self._status_lbl.setText(f"⚠ Export failed: {exc}")
            log.exception("IV sweep CSV export failed")

    def _auto_save(self, result):
        import pathlib, time as _time
        save_dir_str = self._save_path_lbl.text()
        if save_dir_str.startswith("Default:"):
            save_dir = pathlib.Path.home() / "microsanj_sweeps"
        else:
            save_dir = pathlib.Path(save_dir_str)

        # Ensure directory exists before writing
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("IV sweep auto-save: cannot create directory %s: %s",
                        save_dir, exc)
            return

        # Build a timestamped base path *inside* the directory
        ts      = _time.strftime("%Y%m%d_%H%M%S")
        base    = str(save_dir / f"iv_{ts}")

        try:
            from hardware.bias.iv_sweep import IVSweeper
            saved = IVSweeper(None, None, None).save_result(result, base)
            log.info("IV sweep auto-saved to %s", saved)
        except Exception as exc:
            log.warning("IV sweep auto-save failed: %s", exc)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        P = PALETTE
        accent  = P.get("accent",   "#00d4aa")
        surface = P.get("surface",  "#1a1d28")
        surface2= P.get("surface2", "#20232e")
        border  = P.get("border",   "#2e3245")
        text    = P.get("text",     "#dde3f2")
        textDim = P.get("textDim",  "#8892aa")
        danger  = P.get("danger",   "#ff4444")

        self.setStyleSheet(f"""
            QGroupBox {{
                background: {surface2};
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 18px;
                font-size: {FONT['sublabel']}pt;
                font-weight: 600;
                color: {textDim};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
            QLabel {{ background: transparent; color: {text}; }}
            QDoubleSpinBox, QSpinBox, QComboBox {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 3px 6px;
                font-size: {FONT['body']}pt;
                min-height: 26px;
            }}
            QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
                border-color: {accent};
            }}
            QCheckBox {{
                color: {textDim};
                font-size: {FONT['body']}pt;
            }}
            QCheckBox::indicator:checked {{ background: {accent}; border: none; border-radius: 2px; }}
            QPushButton {{
                background: {surface2};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 18px;
                font-size: {FONT['body']}pt;
            }}
            QPushButton:hover {{ background: {P.get('surfaceHover','#262a38')}; }}
            QPushButton:pressed {{ background: {surface}; }}
            QPushButton:disabled {{ color: {textDim}; border-color: {border}; }}
            QProgressBar {{
                background: {surface2};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {accent};
                border-radius: 3px;
            }}
        """)

        # Run button — primary green
        self._run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {accent};
                color: #000;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: {FONT['body']}pt;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #00bfa5; }}
            QPushButton:pressed {{ background: #00a896; }}
            QPushButton:disabled {{ background: {surface2}; color: {textDim}; }}
        """)
        # Stop button — danger
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background: {danger}22;
                color: {danger};
                border: 1px solid {danger}55;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: {FONT['body']}pt;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {danger}44; }}
            QPushButton:disabled {{ background: {surface2}; color: {textDim}; border-color: {border}; }}
        """)

        # Update label colours
        for lbl in self.findChildren(QLabel):
            if lbl is not self._status_lbl and lbl is not self._save_path_lbl:
                lbl.setStyleSheet(
                    f"background:transparent; color:{textDim}; "
                    f"font-size:{FONT['sublabel']}pt;")
        self._status_lbl.setStyleSheet(
            f"background:transparent; color:{textDim}; font-size:{FONT['caption']}pt;")
        self._save_path_lbl.setStyleSheet(
            f"background:transparent; color:{textDim}; font-size:{FONT['caption']}pt;")
