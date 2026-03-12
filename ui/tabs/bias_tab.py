"""
ui/tabs/bias_tab.py

BiasTab — source-measure unit control with voltage/current mode and compliance.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QButtonGroup, QRadioButton,
    QFrame, QComboBox, QCheckBox, QInputDialog, QMessageBox, QStackedWidget)
from PyQt5.QtCore    import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.theme import FONT, PALETTE, scaled_qss
from ai.instrument_knowledge import (
    BIAS_VO_INT_MAX_V, BIAS_AUX_INT_MAX_V, BIAS_VO_EXT_MAX_V,
    SHUNT_20MA_OHM)
from ui.icons import set_btn_icon


# (label, max_v, bipolar)
_PORTS = [
    ("VO INT  — pulsed  ±10 V",   BIAS_VO_INT_MAX_V,  True),
    ("AUX INT — DC      ±10 V",   BIAS_AUX_INT_MAX_V, True),
    ("VO EXT  — pulsed  ≤+60 V",  BIAS_VO_EXT_MAX_V,  False),
]


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE.get('border','#484848')};")
    return f


class BiasTab(QWidget):
    open_device_manager = pyqtSignal()

    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "Bias SMU", "Keithley source-measure unit",
            "Connect the Keithley source-measure unit in Device Manager to enable controls."))

        # Page 1: full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self._stack.addWidget(controls)
        self._stack.setCurrentIndex(1)  # show controls by default

        # Status readouts
        status_box = QGroupBox("Measured Output")
        sl = QHBoxLayout(status_box)
        self._v_w      = self._readout("VOLTAGE",    "--",    "#00d4aa")
        self._i_w      = self._readout("CURRENT",    "--",    "#ffaa44")
        self._p_w      = self._readout("POWER",      "--",    "#6699ff")
        self._comp_w   = self._readout("COMPLIANCE", "--",    "#888")
        self._state_w  = self._readout("OUTPUT",     "OFF",   "#555")
        for w in [self._v_w, self._i_w, self._p_w,
                  self._comp_w, self._state_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # ── Configuration presets ──────────────────────────────────────
        from hardware.hardware_preset_manager import (
            HardwarePresetManager, BIAS_FACTORY_PRESETS)
        self._preset_mgr = HardwarePresetManager("bias", BIAS_FACTORY_PRESETS)

        preset_box = QGroupBox("Configuration Presets")
        pl = QHBoxLayout(preset_box)
        pl.setContentsMargins(8, 6, 8, 6)
        pl.setSpacing(6)

        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(220)
        self._preset_combo.setToolTip("Load a named bias configuration preset")
        self._refresh_preset_combo()
        pl.addWidget(self._preset_combo)

        load_btn = QPushButton("Load")
        load_btn.setFixedWidth(60)
        load_btn.setToolTip("Apply the selected preset")
        load_btn.clicked.connect(self._load_preset)
        pl.addWidget(load_btn)

        save_btn = QPushButton("Save…")
        save_btn.setFixedWidth(60)
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._save_preset)
        pl.addWidget(save_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(60)
        del_btn.setToolTip("Delete the selected user preset")
        del_btn.clicked.connect(self._delete_preset)
        pl.addWidget(del_btn)
        pl.addStretch()
        root.addWidget(preset_box)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        # ── Row 0: Output Port selector ───────────────────────────────
        cl.addWidget(self._sub("Output Port"), 0, 0)
        self._port_combo = QComboBox()
        for lbl, max_v, bipolar in _PORTS:
            self._port_combo.addItem(lbl, (max_v, bipolar))
        self._port_combo.setFixedWidth(230)
        self._port_combo.currentIndexChanged.connect(self._on_port_change)
        cl.addWidget(self._port_combo, 0, 1)

        # ── Row 1: VO EXT safety warning (hidden unless VO EXT selected) ─
        self._port_warn_lbl = QLabel(
            "⚠  VO EXT routes the external supply directly to the DUT. "
            "Confirm external supply current limit before enabling output.")
        self._port_warn_lbl.setStyleSheet(
            f"color:{PALETTE['warning']}; font-size:{FONT['caption']}pt;")
        self._port_warn_lbl.setWordWrap(True)
        self._port_warn_lbl.setVisible(False)
        cl.addWidget(self._port_warn_lbl, 1, 0, 1, 3)

        # ── Row 2: Mode selector (was row 0) ─────────────────────────
        cl.addWidget(self._sub("Source Mode"), 2, 0)
        mode_row = QHBoxLayout()
        self._mode_bg = QButtonGroup()
        for i, m in enumerate(["Voltage", "Current"]):
            rb = QRadioButton(m)
            self._mode_bg.addButton(rb, i)
            mode_row.addWidget(rb)
        self._mode_bg.button(0).setChecked(True)
        self._mode_bg.buttonClicked.connect(self._on_mode_change)
        mode_row.addStretch()
        cl.addLayout(mode_row, 2, 1)

        # ── Row 3: Level (was row 1) ──────────────────────────────────
        cl.addWidget(self._sub("Output Level"), 3, 0)
        level_row = QHBoxLayout()
        self._level_spin = QDoubleSpinBox()
        self._level_spin.setRange(-BIAS_VO_INT_MAX_V, BIAS_VO_INT_MAX_V)
        self._level_spin.setValue(0.0)
        self._level_spin.setDecimals(4)
        self._level_spin.setSingleStep(0.1)
        self._level_spin.setFixedWidth(120)
        self._level_unit = QLabel("V")
        self._level_unit.setStyleSheet(f"color:#666; font-size:{FONT['body']}pt;")
        self._level_indicator = QLabel("✓")
        self._level_indicator.setStyleSheet(
            f"color:#00d4aa; font-size:{FONT['body']}pt; padding-left:6px;")
        level_row.addWidget(self._level_spin)
        level_row.addWidget(self._level_unit)
        level_row.addWidget(self._level_indicator)
        level_row.addStretch()
        cl.addLayout(level_row, 3, 1)

        # ── Row 4: Voltage presets (was row 2) ───────────────────────
        self._v_presets = QHBoxLayout()
        for lbl, val in [("0V",0),("0.5V",0.5),("1V",1),
                          ("1.8V",1.8),("3.3V",3.3),("5V",5)]:
            b = QPushButton(lbl)
            b.setFixedWidth(52)
            b.clicked.connect(
                lambda _, v=val: (self._level_spin.setValue(v),
                                  self._set_level(v)))
            self._v_presets.addWidget(b)
        self._v_presets.addStretch()
        cl.addLayout(self._v_presets, 4, 1)

        # ── Row 5: Current presets (was row 3) ───────────────────────
        self._i_presets = QHBoxLayout()
        for lbl, val in [("0A",0),("1mA",0.001),("10mA",0.01),
                          ("100mA",0.1),("500mA",0.5),("1A",1.0)]:
            b = QPushButton(lbl)
            b.setFixedWidth(56)
            b.clicked.connect(
                lambda _, v=val: (self._level_spin.setValue(v),
                                  self._set_level(v)))
            self._i_presets.addWidget(b)
        self._i_presets.addStretch()
        cl.addLayout(self._i_presets, 5, 1)

        # ── Row 6: Compliance (was row 4) ────────────────────────────
        cl.addWidget(self._sub("Compliance Limit"), 6, 0)
        comp_row = QHBoxLayout()
        self._comp_spin = QDoubleSpinBox()
        self._comp_spin.setRange(0.000001, 1.0)
        self._comp_spin.setValue(0.1)
        self._comp_spin.setDecimals(4)
        self._comp_spin.setSingleStep(0.01)
        self._comp_spin.setFixedWidth(120)
        self._comp_unit = QLabel("A limit")
        self._comp_unit.setStyleSheet(f"color:#666; font-size:{FONT['body']}pt;")
        comp_row.addWidget(self._comp_spin)
        comp_row.addWidget(self._comp_unit)
        comp_row.addStretch()
        cl.addLayout(comp_row, 6, 1)

        # ── Row 7: 20 mA Range Mode (new) ────────────────────────────
        self._ma_range_cb = QCheckBox("20 mA Range Mode")
        self._ma_range_cb.setChecked(True)
        _ma_limit_mA = int(round(BIAS_VO_INT_MAX_V / SHUNT_20MA_OHM * 1000))
        self._ma_range_cb.setToolTip(
            f"Checked: a {SHUNT_20MA_OHM:.0f} Ω series resistor limits device "
            f"current to ≤{_ma_limit_mA} mA at max VO ({BIAS_VO_INT_MAX_V:.0f} V).\n"
            "Uncheck when using IR camera FA / Movie mode — hotspot\n"
            "detection requires >20 mA. Always verify device thermal\n"
            "budget before unchecking.")
        ma_note = QLabel("(Uncheck for IR FA / Movie mode)")
        ma_note.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
        ma_row = QHBoxLayout()
        ma_row.addWidget(self._ma_range_cb)
        ma_row.addWidget(ma_note)
        ma_row.addStretch()
        cl.addLayout(ma_row, 7, 0, 1, 3)

        cl.addWidget(hline(), 8, 0, 1, 3)

        # Action buttons
        btn_row = QHBoxLayout()
        apply_btn  = QPushButton("Apply Settings")
        self._on_btn  = QPushButton("Output ON")
        set_btn_icon(self._on_btn, "fa5s.circle", "#00d4aa")
        self._off_btn = QPushButton("Output OFF")
        set_btn_icon(self._off_btn, "fa5s.circle", "#555555")
        self._on_btn.setStyleSheet(
            "background:#003322; color:#00d4aa; border-color:#00d4aa; font-weight:bold;")
        self._off_btn.setStyleSheet(
            "background:#330000; color:#ff6666; border-color:#ff4444; font-weight:bold;")
        for b in [apply_btn, self._on_btn, self._off_btn]:
            b.setFixedWidth(130)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row, 9, 0, 1, 3)

        apply_btn.clicked.connect(self._apply)
        self._on_btn.clicked.connect(self._enable)
        self._off_btn.clicked.connect(self._disable)

        # Wire level spinbox and port/mode changes to inline validation
        self._level_spin.valueChanged.connect(lambda _: self._validate_level())
        self._port_combo.currentIndexChanged.connect(lambda _: self._validate_level())
        self._mode_bg.buttonClicked.connect(lambda _: self._validate_level())

        root.addWidget(ctrl_box)
        root.addStretch()

        # Initialise to port defaults and show voltage presets
        self._on_port_change()
        self._show_presets("voltage")
        self._validate_level()

    # ── Empty state ───────────────────────────────────────────────────

    def _build_empty_state(self, title: str, device: str, tip: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        try:
            import qtawesome as qta
            icon_lbl = QLabel()
            icon_lbl.setPixmap(qta.icon("fa5s.unlink", color="#555").pixmap(64, 64))
        except Exception:
            icon_lbl = QLabel("⚡")
            icon_lbl.setStyleSheet(scaled_qss("font-size: 48pt; color: #333;"))
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(f"{title} Not Connected")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(f"font-size: {FONT['readoutSm']}pt; font-weight: bold; color: #888;")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: #555;")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE.get('surface','#2d2d2d')}; color: #00d4aa;
                border: 1px solid #00d4aa66; border-radius: 5px;
                font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: {PALETTE.get('surface2','#3d3d3d')}; }}
        """)
        btn.clicked.connect(self.open_device_manager)

        lay.addStretch()
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addWidget(tip_lbl)
        lay.addSpacing(8)
        lay.addWidget(btn, 0, Qt.AlignCenter)
        lay.addStretch()
        return w

    def set_hardware_available(self, available: bool) -> None:
        """Switch between empty state (page 0) and full controls (page 1)."""
        self._stack.setCurrentIndex(1 if available else 0)

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

    def _show_presets(self, mode):
        """Show voltage or current preset buttons."""
        for i in range(self._v_presets.count()):
            item = self._v_presets.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(mode == "voltage")
        for i in range(self._i_presets.count()):
            item = self._i_presets.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(mode == "current")

    def _validate_level(self) -> None:
        """Update the inline level indicator based on the current port and mode."""
        data = self._port_combo.currentData()
        if data is None:
            return
        max_v, bipolar = data
        value = self._level_spin.value()
        is_voltage_mode = self._mode_bg.checkedId() == 0

        if is_voltage_mode:
            if bipolar:
                valid = -max_v <= value <= max_v
                limit_str = f"\xb1{max_v:g} V"
            else:
                valid = 0.0 <= value <= max_v
                limit_str = f"\u2264+{max_v:g} V"
        else:
            # Current mode: range is fixed at ±1 A; compliance is what limits
            valid = -1.0 <= value <= 1.0
            limit_str = "\xb11 A"

        if valid:
            self._level_indicator.setText(f"\u2713 (within {limit_str})")
            self._level_indicator.setStyleSheet(
                f"color:#00d4aa; font-size:{FONT['caption']}pt; padding-left:6px;")
        else:
            self._level_indicator.setText(f"\u2717 exceeds {limit_str} limit")
            self._level_indicator.setStyleSheet(
                f"color:#ff5555; font-size:{FONT['caption']}pt; padding-left:6px;")

    def _on_port_change(self):
        """Update level spinbox limits and VO EXT warning for the selected port."""
        data = self._port_combo.currentData()
        if data is None:
            return
        max_v, bipolar = data
        if self._mode_bg.checkedId() == 0:   # voltage mode
            if bipolar:
                self._level_spin.setRange(-max_v, max_v)
            else:
                self._level_spin.setRange(0.0, max_v)
        # VO EXT (index 2) is the only external passthrough port
        self._port_warn_lbl.setVisible(self._port_combo.currentIndex() == 2)

    def _on_mode_change(self):
        mode = "voltage" if self._mode_bg.checkedId() == 0 else "current"
        self._level_unit.setText("V" if mode == "voltage" else "A")
        self._comp_unit.setText(
            "A limit" if mode == "voltage" else "V limit")
        if mode == "voltage":
            self._on_port_change()          # apply per-port voltage limits
        else:
            self._level_spin.setRange(-1, 1)
        self._comp_spin.setRange(
            *( (0.000001, 1.0) if mode == "voltage" else (0.001, 200) ))
        self._show_presets(mode)
        if self._hw:
            self._hw.bias_set_mode(mode)
        else:
            bias = app_state.bias
            if bias:
                bias.set_mode(mode)

    def _apply(self):
        self._set_level(self._level_spin.value())
        self._set_compliance(self._comp_spin.value())

    def _set_level(self, val):
        if self._hw:
            self._hw.bias_set_level(val)
        else:
            bias = app_state.bias
            if bias:
                bias.set_level(val)

    def _set_compliance(self, val):
        if self._hw:
            self._hw.bias_set_compliance(val)
        else:
            bias = app_state.bias
            if bias:
                bias.set_compliance(val)

    def _enable(self):
        self._apply()
        if self._hw:
            self._hw.bias_enable()
        else:
            bias = app_state.bias
            if bias:
                bias.enable()

    def _disable(self):
        if self._hw:
            self._hw.bias_disable()
        else:
            bias = app_state.bias
            if bias:
                bias.disable()

    # ── Preset helpers ────────────────────────────────────────────────

    def _refresh_preset_combo(self):
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for name in self._preset_mgr.names():
            self._preset_combo.addItem(name)
        self._preset_combo.blockSignals(False)

    def _load_preset(self):
        name = self._preset_combo.currentText()
        cfg  = self._preset_mgr.get(name)
        if not cfg:
            return
        level_v = cfg.get("level_v")
        comp_ma = cfg.get("compliance_ma")
        if level_v is not None:
            self._level_spin.setValue(float(level_v))
            self._set_level(float(level_v))
        if comp_ma is not None:
            # Factory presets store compliance in mA; spinbox uses A
            self._comp_spin.setValue(float(comp_ma) / 1000.0)
            self._set_compliance(float(comp_ma) / 1000.0)

    def _save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:")
        if not (ok and name.strip()):
            return
        cfg = {
            "level_v":       self._level_spin.value(),
            "compliance_ma": self._comp_spin.value() * 1000.0,  # A → mA
        }
        self._preset_mgr.save(name.strip(), cfg)
        self._refresh_preset_combo()
        idx = self._preset_combo.findText(name.strip())
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _delete_preset(self):
        name = self._preset_combo.currentText()
        if not self._preset_mgr.is_user_preset(name):
            QMessageBox.information(
                self, "Cannot Delete",
                f"'{name}' is a factory preset and cannot be deleted.")
            return
        r = QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self._preset_mgr.delete(name)
            self._refresh_preset_combo()

    # ─────────────────────────────────────────────────────────────────

    def update_status(self, status):
        if status.error:
            self._state_w._val.setText("ERROR")
            self._state_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            return

        self._v_w._val.setText(f"{status.actual_voltage:.4f} V")
        self._i_w._val.setText(f"{status.actual_current*1000:.3f} mA")
        self._p_w._val.setText(f"{status.actual_power*1000:.2f} mW")
        self._comp_w._val.setText(
            f"{status.compliance*1000:.1f} mA"
            if status.mode == "voltage"
            else f"{status.compliance:.2f} V")

        if status.output_on:
            self._state_w._val.setText("ON ●")
            self._state_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['success']};")
        else:
            self._state_w._val.setText("OFF ○")
            self._state_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:#444;")
