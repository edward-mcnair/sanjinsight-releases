"""
ui/tabs/emissivity_cal_tab.py — Emissivity calibration panel for IR camera mode.

EmissivityCalTab provides a UI for building and applying an emissivity
calibration using known-temperature reference surfaces.  It wraps the
EmissivityCalibration engine from acquisition/emissivity_cal.py.

Intended use:
    - Instantiated by CalibrationTab (or the Camera pipeline) when an IR
      camera is detected.
    - Exposed as a sub-tab inside CameraControlTab or CalibrationTab.
    - After fitting, call get_result() to retrieve the EmissivityCalResult
      for use in the acquisition pipeline.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QLineEdit, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QFileDialog, QSizePolicy, QMessageBox,
    QFrame, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import QColor, QFont

from ui.theme import FONT, PALETTE, MONO_FONT
from ui.icons import set_btn_icon
from acquisition.emissivity_cal import (
    EmissivityCalibration, EmissivityCalResult,
)


# ────────────────────────────────────────────────────────────────────────── #
#  Helpers                                                                    #
# ────────────────────────────────────────────────────────────────────────────#


def _sub(text: str) -> QLabel:
    """Dimmed subscript / field-label widget consistent with calibration_tab."""
    lbl = QLabel(text)
    lbl.setObjectName("sublabel")
    return lbl


def _hline() -> QFrame:
    """Horizontal separator line."""
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


def _stat_widget(label: str, value: str = "—") -> tuple:
    """Return (container QWidget, value QLabel) for a stat readout cell."""
    container = QWidget()
    vl = QVBoxLayout(container)
    vl.setContentsMargins(4, 4, 4, 4)
    vl.setAlignment(Qt.AlignCenter)

    lbl = QLabel(label)
    lbl.setObjectName("sublabel")
    lbl.setAlignment(Qt.AlignCenter)

    val = QLabel(value)
    val.setAlignment(Qt.AlignCenter)
    val.setStyleSheet(
        f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; "
        f"color:{PALETTE['accent']};")

    vl.addWidget(lbl)
    vl.addWidget(val)
    container._val = val   # type: ignore[attr-defined]
    return container, val


# ────────────────────────────────────────────────────────────────────────── #
#  Main widget                                                                 #
# ────────────────────────────────────────────────────────────────────────────#


class EmissivityCalTab(QWidget):
    """
    UI panel for IR-camera emissivity calibration.

    Signals
    -------
    calibration_applied(EmissivityCalResult)
        Emitted when the user clicks "Apply to Session".
    """

    calibration_applied = pyqtSignal(object)   # payload: EmissivityCalResult

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._cal    = EmissivityCalibration()
        self._result: Optional[EmissivityCalResult] = None

        # External hook — set this to a callable() → float that reads the
        # current mean IR temperature from the live camera frame.  When None
        # the "Capture from camera" button is disabled.
        self.get_camera_temp: Optional[callable] = None

        self._build_ui()
        self._apply_styles()

    # ── UI construction ──────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(_scroll)
        _inner = QWidget()
        _scroll.setWidget(_inner)
        root = QVBoxLayout(_inner)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Title row
        title = QLabel("Emissivity Calibration  (IR Camera)")
        title.setStyleSheet(
            f"font-size:{FONT['heading']}pt; "
            f"font-weight:600; color:{PALETTE['text']};")
        root.addWidget(title)

        root.addWidget(_hline())

        # ── Reference Points group ────────────────────────────────────────
        pts_box = QGroupBox("Reference Points")
        pts_lay = QVBoxLayout(pts_box)
        pts_lay.setSpacing(6)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["#", "True Temp (°C)", "Measured (°C)", "Label"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 32)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                    QAbstractItemView.SelectedClicked |
                                    QAbstractItemView.AnyKeyPressed)
        self._table.setMinimumHeight(140)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Propagate edits back to the calibration engine
        self._table.itemChanged.connect(self._on_table_edit)
        pts_lay.addWidget(self._table)

        # Input row — add new point manually
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._true_spin = QDoubleSpinBox()
        self._true_spin.setRange(-100.0, 500.0)
        self._true_spin.setValue(25.0)
        self._true_spin.setSuffix(" °C")
        self._true_spin.setDecimals(2)
        self._true_spin.setFixedWidth(110)
        self._true_spin.setToolTip("Known true surface temperature (°C)")

        self._meas_spin = QDoubleSpinBox()
        self._meas_spin.setRange(-100.0, 500.0)
        self._meas_spin.setValue(23.0)
        self._meas_spin.setSuffix(" °C")
        self._meas_spin.setDecimals(2)
        self._meas_spin.setFixedWidth(110)
        self._meas_spin.setToolTip("IR camera apparent temperature for this surface (°C)")

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Label (optional)")
        self._label_edit.setMaximumWidth(160)

        self._add_btn = QPushButton("+ Add Point")
        set_btn_icon(self._add_btn, "fa5s.plus")
        self._add_btn.setFixedHeight(28)
        self._add_btn.clicked.connect(self._add_point)

        self._remove_btn = QPushButton("✕ Remove")
        self._remove_btn.setFixedHeight(28)
        self._remove_btn.clicked.connect(self._remove_selected)

        self._capture_btn = QPushButton("Capture from camera")
        set_btn_icon(self._capture_btn, "fa5s.crosshairs", PALETTE['accent'])
        self._capture_btn.setFixedHeight(28)
        self._capture_btn.setEnabled(False)
        self._capture_btn.setToolTip(
            "Read the current mean IR temperature from the live frame "
            "and fill it into the Measured field.")
        self._capture_btn.clicked.connect(self._capture_from_camera)

        input_row.addWidget(_sub("True:"))
        input_row.addWidget(self._true_spin)
        input_row.addWidget(_sub("Measured:"))
        input_row.addWidget(self._meas_spin)
        input_row.addWidget(self._label_edit)
        input_row.addWidget(self._add_btn)
        input_row.addWidget(self._remove_btn)
        input_row.addStretch()
        input_row.addWidget(self._capture_btn)
        pts_lay.addLayout(input_row)

        root.addWidget(pts_box)

        # ── Fit Results group ─────────────────────────────────────────────
        fit_box = QGroupBox("Fit Results")
        fit_outer = QVBoxLayout(fit_box)
        fit_outer.setSpacing(8)

        # Stat row
        stat_row = QHBoxLayout()
        stat_row.setSpacing(0)

        c_eps, self._eps_val   = _stat_widget("Emissivity (ε)")
        c_r2,  self._r2_val    = _stat_widget("R²")
        c_tbg, self._tbg_val   = _stat_widget("T_background")
        c_npt, self._npt_val   = _stat_widget("Points")

        for c in (c_eps, c_r2, c_tbg, c_npt):
            stat_row.addWidget(c, 1)
        fit_outer.addLayout(stat_row)

        # Residuals label
        self._resid_lbl = QLabel("")
        self._resid_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['label']}pt; "
            f"color:{PALETTE['textDim']}; padding-left:4px;")
        self._resid_lbl.setWordWrap(True)
        fit_outer.addWidget(self._resid_lbl)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._fit_btn = QPushButton("◉  Fit")
        set_btn_icon(self._fit_btn, "fa5s.chart-line", PALETTE['accent'])
        self._fit_btn.setObjectName("primary")
        self._fit_btn.setFixedHeight(32)
        self._fit_btn.clicked.connect(self._run_fit)

        self._apply_btn = QPushButton("Apply to Session")
        set_btn_icon(self._apply_btn, "fa5s.check", PALETTE['accent'])
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply_to_session)

        self._save_btn = QPushButton("Save Cal")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._save_btn.setFixedHeight(32)
        self._save_btn.clicked.connect(self._save)

        self._load_btn = QPushButton("Load Cal")
        set_btn_icon(self._load_btn, "fa5s.folder-open")
        self._load_btn.setFixedHeight(32)
        self._load_btn.clicked.connect(self._load)

        btn_row.addWidget(self._fit_btn)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._load_btn)
        btn_row.addStretch()
        fit_outer.addLayout(btn_row)

        root.addWidget(fit_box)

        # ── Status bar ────────────────────────────────────────────────────
        self._status_lbl = QLabel("Add at least 2 reference points to fit.")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; "
            f"color:{PALETTE['textDim']}; "
            f"padding:4px 2px;")
        root.addWidget(self._status_lbl)
        root.addStretch()

        # Populate table from any pre-existing calibration points
        self._refresh_table()

    # ── Public API ────────────────────────────────────────────────────────── #

    def get_result(self) -> Optional[EmissivityCalResult]:
        """Return the most recently fitted EmissivityCalResult, or None."""
        return self._result

    def set_camera_temp_source(self, fn: callable) -> None:
        """
        Register a callable that returns the current IR mean temperature (°C).
        Enables the "Capture from camera" button.

        fn: callable() -> float
        """
        self.get_camera_temp = fn
        self._capture_btn.setEnabled(fn is not None)

    def load_from_path(self, path: str) -> bool:
        """
        Load calibration from path programmatically (no dialog).
        Returns True on success.
        """
        try:
            self._cal.load(path)
            self._result = self._cal.result
            self._refresh_table()
            if self._result is not None:
                self._show_result(self._result)
            self._set_status(f"Loaded: {os.path.basename(path)}", ok=True)
            return True
        except Exception as exc:
            self._set_status(f"Load failed: {exc}", ok=False)
            return False

    # ── Theme support ─────────────────────────────────────────────────────── #

    def _apply_styles(self) -> None:
        P = PALETTE
        self.setStyleSheet(f"""
            QGroupBox {{
                font-size: {FONT['label']}pt;
                font-weight: 600;
                color: {P['textDim']};
                border: 1px solid {P['border']};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 6px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px; top: -1px;
                padding: 0 4px;
            }}
            QTableWidget {{
                background: {P['surface2']};
                alternate-background-color: {P['surface']};
                color: {P['text']};
                gridline-color: {P['border']};
                border: 1px solid {P['border']};
                font-size: {FONT['label']}pt;
            }}
            QTableWidget QHeaderView::section {{
                background: {P['surface3']};
                color: {P['textDim']};
                border: none;
                border-bottom: 1px solid {P['border']};
                padding: 3px 6px;
                font-size: {FONT['label']}pt;
            }}
            QTableWidget::item:selected {{
                background: {P['accentDim']};
                color: {P['text']};
            }}
        """)
        # Update status line and resid colours in case theme changed
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; "
            f"color:{PALETTE['textDim']}; padding:4px 2px;")

    # ── Calibration point management ──────────────────────────────────────── #

    def _add_point(self) -> None:
        true_c = self._true_spin.value()
        meas_c = self._meas_spin.value()
        label  = self._label_edit.text().strip()
        self._cal.add_point(true_c, meas_c, label)
        self._append_table_row(self._cal.n_points, true_c, meas_c, label)
        self._label_edit.clear()
        self._invalidate_result()

    def _remove_selected(self) -> None:
        rows = sorted(set(idx.row() for idx in self._table.selectedIndexes()),
                      reverse=True)
        for row in rows:
            self._cal.remove_point(row)
            self._table.removeRow(row)
        self._renumber_table()
        self._invalidate_result()

    def _capture_from_camera(self) -> None:
        """Read current mean IR temperature and fill into the Measured spin."""
        if self.get_camera_temp is None:
            return
        try:
            temp_c = float(self.get_camera_temp())
            self._meas_spin.setValue(temp_c)
            self._set_status(
                f"Captured {temp_c:.2f} °C from camera — "
                "adjust True Temp and click Add Point.", ok=True)
        except Exception as exc:
            self._set_status(f"Camera read failed: {exc}", ok=False)

    # ── Table helpers ─────────────────────────────────────────────────────── #

    def _refresh_table(self) -> None:
        """Rebuild the table from self._cal.points."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for i, pt in enumerate(self._cal.points):
            self._append_table_row(i + 1, pt.temp_true_c, pt.temp_measured_c, pt.label)
        self._table.blockSignals(False)

    def _append_table_row(self, row_num: int, true_c: float,
                          meas_c: float, label: str) -> None:
        self._table.blockSignals(True)
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Column 0: row number (read-only)
        num_item = QTableWidgetItem(str(row_num))
        num_item.setFlags(Qt.ItemIsEnabled)
        num_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, 0, num_item)

        # Columns 1–3: editable values
        for col, val in enumerate([true_c, meas_c, label], start=1):
            item = QTableWidgetItem(
                f"{val:.4f}" if isinstance(val, float) else str(val))
            item.setTextAlignment(Qt.AlignCenter if col < 3 else Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(row, col, item)

        self._table.blockSignals(False)

    def _renumber_table(self) -> None:
        """Re-synchronise the # column after row removal."""
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                item.setText(str(row + 1))
        self._table.blockSignals(False)

    def _on_table_edit(self, item: QTableWidgetItem) -> None:
        """Propagate inline edits back to the calibration engine."""
        col = item.column()
        row = item.row()
        if col == 0 or row >= self._cal.n_points:
            return
        try:
            pts = self._cal.points
            pt  = pts[row]
            if col == 1:
                pt.temp_true_c     = float(item.text())
            elif col == 2:
                pt.temp_measured_c = float(item.text())
            elif col == 3:
                pt.label           = item.text()
            # Patch directly (dataclass is mutable)
            self._cal._points[row] = pt
            self._invalidate_result()
        except ValueError:
            pass  # User may be mid-edit; ignore transient parse errors

    # ── Fitting ───────────────────────────────────────────────────────────── #

    def _run_fit(self) -> None:
        if self._cal.n_points < 2:
            self._set_status(
                "Need at least 2 reference points to fit emissivity.", ok=False)
            return

        try:
            result = self._cal.fit()
            self._result = result
            self._show_result(result)
            self._apply_btn.setEnabled(True)
        except Exception as exc:
            self._set_status(f"Fit failed: {exc}", ok=False)
            self._apply_btn.setEnabled(False)

    def _show_result(self, result: EmissivityCalResult) -> None:
        self._eps_val.setText(f"{result.emissivity:.4f}")
        self._r2_val.setText(f"{result.r_squared:.4f}")
        self._tbg_val.setText(f"{result.t_background_c:.2f} °C")
        self._npt_val.setText(str(result.n_points))

        # Colour R² by quality
        r2_color = (
            PALETTE["success"] if result.r_squared >= 0.995 else
            PALETTE["warning"] if result.r_squared >= 0.98  else
            PALETTE["danger"]
        )
        self._r2_val.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; color:{r2_color};")

        # Residuals summary
        if result.residuals:
            rms = float(np.sqrt(np.mean(np.array(result.residuals) ** 2)))
            parts = [f"{r:+.3f}" for r in result.residuals]
            self._resid_lbl.setText(
                f"Residuals (°C): {',  '.join(parts)}    RMS = {rms:.4f} °C")
        else:
            self._resid_lbl.setText("")

        n = result.n_points
        self._set_status(
            f"✓ Calibration valid — {n} point{'s' if n != 1 else ''}  "
            f"ε = {result.emissivity:.4f}  R² = {result.r_squared:.4f}",
            ok=True)

    def _invalidate_result(self) -> None:
        """Clear result display when points change."""
        self._result = None
        self._cal._result = None
        self._apply_btn.setEnabled(False)
        for val in (self._eps_val, self._r2_val, self._tbg_val, self._npt_val):
            val.setText("—")
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; "
                f"color:{PALETTE['accent']};")
        self._resid_lbl.setText("")
        n = self._cal.n_points
        if n >= 2:
            self._set_status(
                f"{n} points loaded — click Fit to compute emissivity.", ok=True)
        else:
            self._set_status(
                f"{n} point{'s' if n != 1 else ''} — add at least 2 to fit.",
                ok=(n == 0))

    # ── Apply / Save / Load ───────────────────────────────────────────────── #

    def _apply_to_session(self) -> None:
        if self._result is None:
            return
        try:
            from hardware.app_state import app_state
            app_state.active_emissivity_cal = self._result
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "EmissivityCalTab: could not set app_state.active_emissivity_cal "
                "— app_state may not have this attribute in this build",
                exc_info=True
            )
        self.calibration_applied.emit(self._result)
        self._set_status(
            f"✓ Applied to session — ε = {self._result.emissivity:.4f}",
            ok=True)

    def _save(self) -> None:
        if self._cal.n_points == 0:
            QMessageBox.warning(self, "Nothing to save",
                                "Add at least one calibration point first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Emissivity Calibration", "emissivity_cal.json",
            "Emissivity calibration (*.json);;All files (*)")
        if not path:
            return
        try:
            saved = self._cal.save(path)
            self._set_status(f"Saved: {os.path.basename(saved)}", ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Emissivity Calibration", "",
            "Emissivity calibration (*.json);;All files (*)")
        if not path:
            return
        self.load_from_path(path)

    # ── Status helper ─────────────────────────────────────────────────────── #

    def _set_status(self, message: str, ok: bool = True) -> None:
        color = PALETTE["success"] if ok else PALETTE["danger"]
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; "
            f"color:{color}; padding:4px 2px;")
        self._status_lbl.setText(message)
