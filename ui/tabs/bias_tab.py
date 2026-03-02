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
    QFrame)
from PyQt5.QtCore    import Qt

from hardware.app_state import app_state
from ui.theme import FONT, PALETTE


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #2a2a2a;")
    return f


class BiasTab(QWidget):
    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

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

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        # Mode selector
        cl.addWidget(self._sub("Source Mode"), 0, 0)
        mode_row = QHBoxLayout()
        self._mode_bg = QButtonGroup()
        for i, m in enumerate(["Voltage", "Current"]):
            rb = QRadioButton(m)
            self._mode_bg.addButton(rb, i)
            mode_row.addWidget(rb)
        self._mode_bg.button(0).setChecked(True)
        self._mode_bg.buttonClicked.connect(self._on_mode_change)
        mode_row.addStretch()
        cl.addLayout(mode_row, 0, 1)

        # Level
        cl.addWidget(self._sub("Output Level"), 1, 0)
        level_row = QHBoxLayout()
        self._level_spin = QDoubleSpinBox()
        self._level_spin.setRange(-200, 200)
        self._level_spin.setValue(0.0)
        self._level_spin.setDecimals(4)
        self._level_spin.setSingleStep(0.1)
        self._level_spin.setFixedWidth(120)
        self._level_unit = QLabel("V")
        self._level_unit.setStyleSheet(f"color:#666; font-size:{FONT['body']}pt;")
        level_row.addWidget(self._level_spin)
        level_row.addWidget(self._level_unit)
        level_row.addStretch()
        cl.addLayout(level_row, 1, 1)

        # Voltage presets
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
        cl.addLayout(self._v_presets, 2, 1)

        # Current presets
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
        cl.addLayout(self._i_presets, 3, 1)

        # Compliance
        cl.addWidget(self._sub("Compliance Limit"), 4, 0)
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
        cl.addLayout(comp_row, 4, 1)

        cl.addWidget(hline(), 5, 0, 1, 3)

        # Action buttons
        btn_row = QHBoxLayout()
        apply_btn  = QPushButton("Apply Settings")
        self._on_btn  = QPushButton("⬤  Output ON")
        self._off_btn = QPushButton("⬤  Output OFF")
        self._on_btn.setStyleSheet(
            "background:#003322; color:#00d4aa; border-color:#00d4aa; font-weight:bold;")
        self._off_btn.setStyleSheet(
            "background:#330000; color:#ff6666; border-color:#ff4444; font-weight:bold;")
        for b in [apply_btn, self._on_btn, self._off_btn]:
            b.setFixedWidth(130)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row, 6, 0, 1, 3)

        apply_btn.clicked.connect(self._apply)
        self._on_btn.clicked.connect(self._enable)
        self._off_btn.clicked.connect(self._disable)

        root.addWidget(ctrl_box)
        root.addStretch()

        # Show voltage presets by default
        self._show_presets("voltage")

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

    def _on_mode_change(self):
        mode = "voltage" if self._mode_bg.checkedId() == 0 else "current"
        self._level_unit.setText("V" if mode == "voltage" else "A")
        self._comp_unit.setText(
            "A limit" if mode == "voltage" else "V limit")
        self._level_spin.setRange(
            *( (-200, 200) if mode == "voltage" else (-1, 1) ))
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
