"""
ui/tabs/wavelength_tab.py

WavelengthTab — monochromator control panel.

Layout
------
┌─ Monochromator ──────────────────────────────────┐
│  Wavelength   [──────────●──────────]  532.0 nm  │
│               300 nm              900 nm          │
│                                                   │
│  [Set]  Input: [___532.0___] nm                  │
│                                                   │
│  Shutter:  [● OPEN]  [CLOSE]                     │
│                                                   │
│  ─── Wavelength Sweep ──────────────────────     │
│  Start: [300] nm   Stop: [800] nm   Step: [50]   │
│  Dwell: [500] ms                                 │
│  [▶ Run Sweep]  [■ Stop]      Progress: ─────    │
│                                                   │
│  Status: ● Connected  532.0 nm  Shutter: OPEN    │
└──────────────────────────────────────────────────┘

Public API
----------
    tab.set_driver(driver)          — connect to a real driver
    tab.update_status(status)       — push a MonochromatorStatus snapshot
    tab.wavelength_changed(float)   — signal emitted when user sets a wavelength
"""
from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QDoubleSpinBox, QSpinBox, QGroupBox, QProgressBar,
    QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject

from ui.theme import FONT, PALETTE, scaled_qss

log = logging.getLogger(__name__)

# Default wavelength range shown in the UI before the driver reports its limits
_DEFAULT_MIN_NM = 300.0
_DEFAULT_MAX_NM = 900.0


# ---------------------------------------------------------------------------
# Sweep worker thread
# ---------------------------------------------------------------------------

class _SweepWorker(QObject):
    """
    Runs ``driver.scan_wavelengths(...)`` in a dedicated thread.

    Signals
    -------
    progress(current_nm, step_index, total_steps)
    finished()
    error(message)
    """
    progress = pyqtSignal(float, int, int)   # (nm, step_idx, total)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(
        self,
        driver,
        start_nm:  float,
        end_nm:    float,
        step_nm:   float,
        dwell_ms:  float,
    ):
        super().__init__()
        self._driver   = driver
        self._start_nm = start_nm
        self._end_nm   = end_nm
        self._step_nm  = step_nm
        self._dwell_ms = dwell_ms
        self._cancel   = False

    def cancel(self) -> None:
        self._cancel = True
        if hasattr(self._driver, "_cancel_sweep"):
            self._driver._cancel_sweep = True

    def run(self) -> None:
        try:
            self._driver.scan_wavelengths(
                start_nm  = self._start_nm,
                end_nm    = self._end_nm,
                step_nm   = self._step_nm,
                dwell_ms  = self._dwell_ms,
                callback  = self._on_step,
            )
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))

    def _on_step(self, nm: float, idx: int, total: int) -> None:
        if self._cancel:
            raise StopIteration("Sweep cancelled by user")
        self.progress.emit(nm, idx, total)


# ---------------------------------------------------------------------------
# WavelengthTab
# ---------------------------------------------------------------------------

class WavelengthTab(QWidget):
    """Monochromator control tab — wavelength, shutter, and sweep."""

    wavelength_changed = pyqtSignal(float)  # emitted when user sets a new wavelength

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._driver = None
        self._min_nm = _DEFAULT_MIN_NM
        self._max_nm = _DEFAULT_MAX_NM

        self._sweep_thread: QThread | None = None
        self._sweep_worker: _SweepWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Wavelength control group ───────────────────────────────────
        wl_group = QGroupBox("Monochromator")
        wl_lay = QVBoxLayout(wl_group)
        wl_lay.setSpacing(8)

        # Slider row
        slider_row = QHBoxLayout()
        slider_lbl = QLabel("Wavelength")
        slider_lbl.setObjectName("sublabel")
        slider_lbl.setFixedWidth(88)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(int(_DEFAULT_MIN_NM), int(_DEFAULT_MAX_NM))
        self._slider.setValue(532)
        self._slider.setTickInterval(100)
        self._slider.setTickPosition(QSlider.TicksBelow)
        self._slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._wl_readout = QLabel("532.0 nm")
        self._wl_readout.setMinimumWidth(72)
        self._wl_readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider_row.addWidget(slider_lbl)
        slider_row.addWidget(self._slider, 1)
        slider_row.addWidget(self._wl_readout)
        wl_lay.addLayout(slider_row)

        # Slider range labels
        range_row = QHBoxLayout()
        range_row.addSpacing(92)
        self._min_lbl = QLabel(f"{int(_DEFAULT_MIN_NM)} nm")
        self._min_lbl.setObjectName("sublabel")
        range_row.addWidget(self._min_lbl)
        range_row.addStretch(1)
        self._max_lbl = QLabel(f"{int(_DEFAULT_MAX_NM)} nm")
        self._max_lbl.setObjectName("sublabel")
        range_row.addWidget(self._max_lbl)
        wl_lay.addLayout(range_row)

        # Exact entry row
        entry_row = QHBoxLayout()
        self._set_btn = QPushButton("Set")
        self._set_btn.setFixedWidth(54)
        entry_row.addWidget(self._set_btn)
        entry_lbl = QLabel("Input:")
        entry_lbl.setObjectName("sublabel")
        entry_row.addWidget(entry_lbl)
        self._nm_spin = QDoubleSpinBox()
        self._nm_spin.setRange(_DEFAULT_MIN_NM, _DEFAULT_MAX_NM)
        self._nm_spin.setValue(532.0)
        self._nm_spin.setDecimals(1)
        self._nm_spin.setSingleStep(1.0)
        self._nm_spin.setSuffix(" nm")
        self._nm_spin.setFixedWidth(110)
        entry_row.addWidget(self._nm_spin)
        entry_row.addStretch()
        wl_lay.addLayout(entry_row)

        # Divider
        wl_lay.addWidget(self._hline())

        # Shutter row
        shutter_row = QHBoxLayout()
        shutter_lbl = QLabel("Shutter:")
        shutter_lbl.setFixedWidth(60)
        self._shutter_open_btn  = QPushButton("OPEN")
        self._shutter_close_btn = QPushButton("CLOSE")
        self._shutter_open_btn.setFixedWidth(90)
        self._shutter_close_btn.setFixedWidth(90)
        self._shutter_open_btn.setCheckable(True)
        self._shutter_close_btn.setCheckable(True)
        self._shutter_close_btn.setChecked(True)
        shutter_row.addWidget(shutter_lbl)
        shutter_row.addWidget(self._shutter_open_btn)
        shutter_row.addWidget(self._shutter_close_btn)
        shutter_row.addStretch()
        wl_lay.addLayout(shutter_row)

        root.addWidget(wl_group)

        # ── Sweep group ────────────────────────────────────────────────
        sweep_group = QGroupBox("Wavelength Sweep")
        sweep_lay = QVBoxLayout(sweep_group)
        sweep_lay.setSpacing(8)

        params_row = QHBoxLayout()
        params_row.setSpacing(6)

        for lbl, attr, val, lo, hi, dec, suf in [
            ("Start:",  "_sweep_start", 300.0,   0.0, 9999.0, 1, " nm"),
            ("Stop:",   "_sweep_stop",  800.0,   0.0, 9999.0, 1, " nm"),
            ("Step:",   "_sweep_step",   50.0,   0.1, 9999.0, 1, " nm"),
            ("Dwell:",  "_sweep_dwell", 500.0,   1.0, 60000.0, 0, " ms"),
        ]:
            row_lbl = QLabel(lbl)
            row_lbl.setObjectName("sublabel")
            params_row.addWidget(row_lbl)
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(val)
            spin.setDecimals(dec)
            spin.setSuffix(suf)
            spin.setFixedWidth(100)
            setattr(self, attr, spin)
            params_row.addWidget(spin)
            params_row.addSpacing(6)

        params_row.addStretch()
        sweep_lay.addLayout(params_row)

        # Run / Stop / Progress row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self._run_btn  = QPushButton("▶  Run Sweep")
        self._stop_btn = QPushButton("■  Stop")
        self._run_btn.setFixedWidth(120)
        self._stop_btn.setFixedWidth(80)
        self._stop_btn.setEnabled(False)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")
        self._progress.setFixedHeight(14)
        self._progress_lbl = QLabel("Idle")
        self._progress_lbl.setObjectName("sublabel")
        ctrl_row.addWidget(self._run_btn)
        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(QLabel("Progress:"))
        ctrl_row.addWidget(self._progress, 1)
        ctrl_row.addWidget(self._progress_lbl)
        sweep_lay.addLayout(ctrl_row)

        root.addWidget(sweep_group)

        # ── Status bar ─────────────────────────────────────────────────
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._conn_dot  = QLabel("●")
        self._conn_dot.setObjectName("sublabel")
        self._conn_lbl  = QLabel("Not connected")
        self._conn_lbl.setObjectName("sublabel")
        self._status_wl = QLabel("")
        self._status_wl.setObjectName("sublabel")
        self._status_sh = QLabel("")
        self._status_sh.setObjectName("sublabel")
        status_row.addWidget(self._conn_dot)
        status_row.addWidget(self._conn_lbl)
        status_row.addWidget(self._status_wl)
        status_row.addWidget(self._status_sh)
        status_row.addStretch()
        root.addLayout(status_row)

        root.addStretch()

        # ── Wire signals ───────────────────────────────────────────────
        self._slider.valueChanged.connect(self._on_slider_moved)
        self._nm_spin.editingFinished.connect(self._on_spin_committed)
        self._set_btn.clicked.connect(self._on_set_clicked)
        self._shutter_open_btn.clicked.connect(self._on_shutter_open)
        self._shutter_close_btn.clicked.connect(self._on_shutter_close)
        self._run_btn.clicked.connect(self._on_run_sweep)
        self._stop_btn.clicked.connect(self._on_stop_sweep)

        # Apply initial theme styling
        self._apply_styles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_driver(self, driver) -> None:
        """
        Attach a ``MonochromatorDriver`` instance.  Pass ``None`` to detach.

        When a driver is attached the slider and spinbox ranges are updated to
        match the instrument's wavelength limits.
        """
        self._driver = driver
        if driver is not None:
            try:
                lo, hi = driver.wavelength_range
                self._update_range(lo, hi)
            except Exception as exc:
                log.warning("Could not read wavelength range from driver: %s", exc)
        self._update_controls_enabled()

    def update_status(self, status) -> None:
        """
        Push a ``MonochromatorStatus`` snapshot into the UI.

        Called by a background poll timer in the main window.
        """
        if status is None:
            return

        P = PALETTE
        # Connection dot
        if status.connected:
            self._conn_dot.setStyleSheet(
                f"color: {P.get('accent', '#00d4aa')}; font-size: {FONT['label']}pt;")
            self._conn_lbl.setText("Connected")
        else:
            self._conn_dot.setStyleSheet(
                f"color: {P.get('danger', '#ff453a')}; font-size: {FONT['label']}pt;")
            self._conn_lbl.setText("Not connected")

        if status.error_msg:
            self._conn_lbl.setText(f"Error: {status.error_msg[:60]}")
            self._conn_lbl.setStyleSheet(
                f"color: {P.get('danger', '#ff453a')}; font-size: {FONT['label']}pt;")
        else:
            self._conn_lbl.setStyleSheet(
                f"color: {P.get('textDim', '#8892aa')}; font-size: {FONT['label']}pt;")

        # Wavelength readout
        self._status_wl.setText(f"  {status.wavelength_nm:.1f} nm")

        # Shutter state
        if status.shutter_open:
            self._status_sh.setText("  Shutter: OPEN")
            self._status_sh.setStyleSheet(
                f"color: {P.get('accent', '#00d4aa')}; font-size: {FONT['label']}pt;")
            self._shutter_open_btn.setChecked(True)
            self._shutter_close_btn.setChecked(False)
        else:
            self._status_sh.setText("  Shutter: CLOSED")
            self._status_sh.setStyleSheet(
                f"color: {P.get('danger', '#ff453a')}; font-size: {FONT['label']}pt;")
            self._shutter_open_btn.setChecked(False)
            self._shutter_close_btn.setChecked(True)

        # Sync slider & spinbox only if not being edited and value differs
        nm = status.wavelength_nm
        if abs(self._nm_spin.value() - nm) > 0.05:
            blocked = self._slider.blockSignals(True)
            self._slider.setValue(int(round(nm)))
            self._slider.blockSignals(blocked)
            blocked = self._nm_spin.blockSignals(True)
            self._nm_spin.setValue(nm)
            self._nm_spin.blockSignals(blocked)
            self._wl_readout.setText(f"{nm:.1f} nm")

        self._apply_shutter_button_styles()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_styles(self) -> None:
        P = PALETTE
        F = FONT

        accent  = P.get("accent",   "#00d4aa")
        danger  = P.get("danger",   "#ff453a")
        surface = P.get("surface",  "#1a1d28")
        surf2   = P.get("surface2", "#20232e")
        border  = P.get("border",   "#2e3245")
        text    = P.get("text",     "#dde3f2")
        textDim = P.get("textDim",  "#8892aa")
        cta     = P.get("cta",      "#3d8bef")

        def _rgb(h: str) -> tuple[int, int, int]:
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        ar, ag, ab = _rgb(accent)
        cr, cg, cb = _rgb(cta)
        dr, dg, db = _rgb(danger)

        # Wavelength readout label
        self._wl_readout.setStyleSheet(
            f"font-family: Menlo, monospace; font-size: {F['readoutSm']}pt; "
            f"color: {accent};"
        )

        # Set button — cta style
        self._set_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: rgba({cr},{cg},{cb}, 0.15);"
            f"  color: {cta};"
            f"  border: 1px solid rgba({cr},{cg},{cb}, 0.40);"
            f"  border-radius: 4px;"
            f"  font-size: {F['body']}pt;"
            f"  padding: 0 10px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: rgba({cr},{cg},{cb}, 0.25);"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: rgba({cr},{cg},{cb}, 0.35);"
            f"}}"
        )

        # Run Sweep button — cta style
        self._run_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: rgba({cr},{cg},{cb}, 0.15);"
            f"  color: {cta};"
            f"  border: 1px solid rgba({cr},{cg},{cb}, 0.40);"
            f"  border-radius: 4px;"
            f"  font-size: {F['body']}pt;"
            f"  padding: 0 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: rgba({cr},{cg},{cb}, 0.25);"
            f"}}"
            f"QPushButton:disabled {{"
            f"  color: {textDim};"
            f"  border-color: {border};"
            f"  background: transparent;"
            f"}}"
        )

        # Stop button — danger style
        self._stop_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: rgba({dr},{dg},{db}, 0.13);"
            f"  color: {danger};"
            f"  border: 1px solid rgba({dr},{dg},{db}, 0.35);"
            f"  border-radius: 4px;"
            f"  font-size: {F['body']}pt;"
            f"  padding: 0 10px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: rgba({dr},{dg},{db}, 0.22);"
            f"}}"
            f"QPushButton:disabled {{"
            f"  color: {textDim};"
            f"  border-color: {border};"
            f"  background: transparent;"
            f"}}"
        )

        self._apply_shutter_button_styles()

        # Progress bar
        self._progress.setStyleSheet(
            f"QProgressBar {{"
            f"  background: {surf2};"
            f"  border: 1px solid {border};"
            f"  border-radius: 3px;"
            f"  text-align: center;"
            f"  color: {textDim};"
            f"  font-size: {F['sublabel']}pt;"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background: {accent};"
            f"  border-radius: 2px;"
            f"}}"
        )

        # Spinboxes
        spin_qss = (
            f"QDoubleSpinBox, QSpinBox {{"
            f"  background: {surf2};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"  font-size: {F['body']}pt;"
            f"}}"
            f"QDoubleSpinBox:focus, QSpinBox:focus {{"
            f"  border-color: {accent};"
            f"}}"
        )
        for spin in (
            self._nm_spin,
            self._sweep_start, self._sweep_stop,
            self._sweep_step, self._sweep_dwell,
        ):
            spin.setStyleSheet(spin_qss)

        # Slider
        self._slider.setStyleSheet(
            f"QSlider::groove:horizontal {{"
            f"  background: {surf2};"
            f"  height: 4px;"
            f"  border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {accent};"
            f"  width: 14px; height: 14px;"
            f"  margin: -5px 0;"
            f"  border-radius: 7px;"
            f"}}"
            f"QSlider::sub-page:horizontal {{"
            f"  background: {accent}88;"
            f"  border-radius: 2px;"
            f"}}"
        )

        # Status bar labels
        for lbl in (
            self._conn_dot, self._conn_lbl,
            self._status_wl, self._status_sh,
            self._progress_lbl,
        ):
            if not lbl.styleSheet():
                lbl.setStyleSheet(
                    f"color: {textDim}; font-size: {F['label']}pt;")

    def _apply_shutter_button_styles(self) -> None:
        """Re-style the OPEN/CLOSE shutter buttons to reflect current state."""
        P = PALETTE
        F = FONT
        accent = P.get("accent",  "#00d4aa")
        danger = P.get("danger",  "#ff453a")
        border = P.get("border",  "#2e3245")
        surf2  = P.get("surface2","#20232e")
        textDim = P.get("textDim","#8892aa")

        def _rgb(h: str) -> tuple[int, int, int]:
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        ar, ag, ab = _rgb(accent)
        dr, dg, db = _rgb(danger)

        open_active  = self._shutter_open_btn.isChecked()
        close_active = self._shutter_close_btn.isChecked()

        def _btn_qss(active: bool, r, g, b, hex_color) -> str:
            if active:
                return (
                    f"QPushButton {{"
                    f"  background: rgba({r},{g},{b}, 0.20);"
                    f"  color: {hex_color};"
                    f"  border: 1px solid rgba({r},{g},{b}, 0.55);"
                    f"  border-radius: 4px;"
                    f"  font-size: {F['body']}pt;"
                    f"  font-weight: 600;"
                    f"  padding: 0 12px;"
                    f"}}"
                )
            else:
                return (
                    f"QPushButton {{"
                    f"  background: {surf2};"
                    f"  color: {textDim};"
                    f"  border: 1px solid {border};"
                    f"  border-radius: 4px;"
                    f"  font-size: {F['body']}pt;"
                    f"  padding: 0 12px;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"  color: {hex_color};"
                    f"  border-color: rgba({r},{g},{b}, 0.40);"
                    f"}}"
                )

        self._shutter_open_btn.setStyleSheet(
            _btn_qss(open_active,  ar, ag, ab, accent))
        self._shutter_close_btn.setStyleSheet(
            _btn_qss(close_active, dr, dg, db, danger))

    # ------------------------------------------------------------------
    # Slots — wavelength
    # ------------------------------------------------------------------

    def _on_slider_moved(self, value: int) -> None:
        """Slider position changed — sync spinbox readout only (do not send to hardware)."""
        blocked = self._nm_spin.blockSignals(True)
        self._nm_spin.setValue(float(value))
        self._nm_spin.blockSignals(blocked)
        self._wl_readout.setText(f"{value:.0f}.0 nm")

    def _on_spin_committed(self) -> None:
        """User pressed Enter or left the spinbox — sync slider readout."""
        nm = self._nm_spin.value()
        blocked = self._slider.blockSignals(True)
        self._slider.setValue(int(round(nm)))
        self._slider.blockSignals(blocked)
        self._wl_readout.setText(f"{nm:.1f} nm")

    def _on_set_clicked(self) -> None:
        """Send the current spinbox value to the driver."""
        nm = self._nm_spin.value()
        self._wl_readout.setText(f"{nm:.1f} nm")
        if self._driver is not None:
            try:
                self._driver.set_wavelength(nm)
                log.debug("Wavelength set to %.3f nm", nm)
            except Exception as exc:
                log.error("set_wavelength failed: %s", exc)
        self.wavelength_changed.emit(nm)

    # ------------------------------------------------------------------
    # Slots — shutter
    # ------------------------------------------------------------------

    def _on_shutter_open(self) -> None:
        self._shutter_open_btn.setChecked(True)
        self._shutter_close_btn.setChecked(False)
        self._apply_shutter_button_styles()
        if self._driver is not None:
            try:
                self._driver.set_shutter(True)
            except Exception as exc:
                log.error("set_shutter(open) failed: %s", exc)

    def _on_shutter_close(self) -> None:
        self._shutter_open_btn.setChecked(False)
        self._shutter_close_btn.setChecked(True)
        self._apply_shutter_button_styles()
        if self._driver is not None:
            try:
                self._driver.set_shutter(False)
            except Exception as exc:
                log.error("set_shutter(close) failed: %s", exc)

    # ------------------------------------------------------------------
    # Slots — sweep
    # ------------------------------------------------------------------

    def _on_run_sweep(self) -> None:
        if self._driver is None:
            log.warning("No monochromator driver attached — cannot run sweep")
            return
        if self._sweep_thread is not None and self._sweep_thread.isRunning():
            return

        start = self._sweep_start.value()
        stop  = self._sweep_stop.value()
        step  = self._sweep_step.value()
        dwell = self._sweep_dwell.value()

        if start >= stop:
            log.warning("Sweep start (%.1f) must be less than stop (%.1f)", start, stop)
            return
        if step <= 0:
            log.warning("Sweep step must be positive")
            return

        self._progress.setValue(0)
        self._progress_lbl.setText("Running…")
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._set_btn.setEnabled(False)

        self._sweep_worker = _SweepWorker(
            driver   = self._driver,
            start_nm = start,
            end_nm   = stop,
            step_nm  = step,
            dwell_ms = dwell,
        )
        self._sweep_thread = QThread(self)
        self._sweep_worker.moveToThread(self._sweep_thread)

        self._sweep_thread.started.connect(self._sweep_worker.run)
        self._sweep_worker.progress.connect(self._on_sweep_progress)
        self._sweep_worker.finished.connect(self._on_sweep_finished)
        self._sweep_worker.error.connect(self._on_sweep_error)
        self._sweep_worker.finished.connect(self._sweep_thread.quit)
        self._sweep_worker.error.connect(self._sweep_thread.quit)
        self._sweep_thread.finished.connect(self._on_thread_done)

        self._sweep_thread.start()

    def _on_stop_sweep(self) -> None:
        if self._sweep_worker is not None:
            self._sweep_worker.cancel()
        self._progress_lbl.setText("Stopping…")

    def _on_sweep_progress(self, nm: float, idx: int, total: int) -> None:
        pct = int((idx + 1) / max(total, 1) * 100)
        self._progress.setValue(pct)
        self._progress_lbl.setText(f"{nm:.1f} nm  ({idx+1}/{total})")
        # Sync slider and readout
        blocked = self._slider.blockSignals(True)
        self._slider.setValue(int(round(nm)))
        self._slider.blockSignals(blocked)
        blocked = self._nm_spin.blockSignals(True)
        self._nm_spin.setValue(nm)
        self._nm_spin.blockSignals(blocked)
        self._wl_readout.setText(f"{nm:.1f} nm")

    def _on_sweep_finished(self) -> None:
        self._progress.setValue(100)
        self._progress_lbl.setText("Done")

    def _on_sweep_error(self, message: str) -> None:
        self._progress_lbl.setText(f"Error: {message[:60]}")
        log.error("Sweep error: %s", message)

    def _on_thread_done(self) -> None:
        """Re-enable UI controls after sweep thread exits."""
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_btn.setEnabled(True)
        if self._sweep_thread is not None:
            self._sweep_thread.deleteLater()
            self._sweep_thread = None
        if self._sweep_worker is not None:
            self._sweep_worker.deleteLater()
            self._sweep_worker = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_range(self, min_nm: float, max_nm: float) -> None:
        """Update slider, spinbox, and range labels to match the driver's range."""
        self._min_nm = min_nm
        self._max_nm = max_nm
        self._slider.setRange(int(min_nm), int(max_nm))
        self._nm_spin.setRange(min_nm, max_nm)
        self._sweep_start.setRange(min_nm, max_nm)
        self._sweep_stop.setRange(min_nm, max_nm)
        self._min_lbl.setText(f"{int(min_nm)} nm")
        self._max_lbl.setText(f"{int(max_nm)} nm")

    def _update_controls_enabled(self) -> None:
        connected = self._driver is not None
        for w in (
            self._set_btn, self._slider, self._nm_spin,
            self._shutter_open_btn, self._shutter_close_btn,
            self._run_btn,
        ):
            w.setEnabled(connected)

    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet(
            f"color: {PALETTE.get('border', '#2e3245')};"
        )
        return line
