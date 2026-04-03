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
    QFrame, QComboBox, QCheckBox, QInputDialog, QMessageBox, QStackedWidget,
    QScrollArea)
from PyQt5.QtCore    import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.widgets.collapsible_panel import CollapsiblePanel
from ai.instrument_knowledge import (
    BIAS_VO_INT_MAX_V, BIAS_AUX_INT_MAX_V, BIAS_VO_EXT_MAX_V,
    SHUNT_20MA_OHM)
from ui.icons import IC, make_icon_label, set_btn_icon


# (label, max_v, bipolar)
_PORTS = [
    ("VO INT  — pulsed  ±10 V",   BIAS_VO_INT_MAX_V,  True),
    ("AUX INT — DC      ±10 V",   BIAS_AUX_INT_MAX_V, True),
    ("VO EXT  — pulsed  ≤+60 V",  BIAS_VO_EXT_MAX_V,  False),
]


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE['border']};")
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

        # Error banner (hidden until a device error occurs)
        from ui.widgets.device_error_banner import DeviceErrorBanner
        self._error_banner = DeviceErrorBanner()
        self._error_banner.device_manager_clicked.connect(
            self.open_device_manager.emit)
        root.addWidget(self._error_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)  # empty state until device connects

        # Status readouts — drain channel (always visible)
        status_box = QGroupBox("Measured Output")
        from PyQt5.QtWidgets import QVBoxLayout as _VL
        sv = _VL(status_box)
        sv.setSpacing(4)
        sv.setContentsMargins(6, 6, 6, 6)

        drain_row = QWidget()
        sl = QHBoxLayout(drain_row)
        sl.setContentsMargins(0, 0, 0, 0)
        self._v_w      = self._readout("VOLTAGE",    "--",    "accent")
        self._i_w      = self._readout("CURRENT",    "--",    "warning")
        self._p_w      = self._readout("POWER",      "--",    "cta")
        self._comp_w   = self._readout("COMPLIANCE", "--",    "textDim")
        self._state_w  = self._readout("OUTPUT",     "OFF",   "textSub")
        for w in [self._v_w, self._i_w, self._p_w,
                  self._comp_w, self._state_w]:
            sl.addWidget(w)
        sv.addWidget(drain_row)

        # Gate-channel readouts — shown only when AMCAD BILT is connected
        self._gate_row = QWidget()
        gl = QHBoxLayout(self._gate_row)
        gl.setContentsMargins(0, 0, 0, 0)
        self._gate_v_w = self._readout("GATE Vg", "--", "info")
        self._gate_i_w = self._readout("GATE Ig", "--", "textDim")
        _gate_lbl = QLabel("Gate")
        _gate_lbl.setObjectName("sublabel")
        _gate_lbl.setAlignment(Qt.AlignVCenter)
        gl.addWidget(self._gate_v_w)
        gl.addWidget(self._gate_i_w)
        gl.addStretch()
        self._gate_row.setVisible(False)
        sv.addWidget(self._gate_row)

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
        load_btn.setMinimumWidth(76)
        load_btn.setToolTip("Apply the selected preset")
        load_btn.clicked.connect(self._load_preset)
        pl.addWidget(load_btn)

        save_btn = QPushButton("Save…")
        save_btn.setMinimumWidth(76)
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._save_preset)
        pl.addWidget(save_btn)

        del_btn = QPushButton("Delete")
        del_btn.setMinimumWidth(76)
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
        self._level_unit.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['body']}pt;")
        self._level_indicator = QLabel("✓")
        self._level_indicator.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT['body']}pt; padding-left:6px;")
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
            b.setMinimumWidth(58)
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
            b.setMinimumWidth(74)
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
        self._comp_unit.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['body']}pt;")
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
        set_btn_icon(self._on_btn, "fa5s.circle", PALETTE['accent'])
        self._off_btn = QPushButton("Output OFF")
        set_btn_icon(self._off_btn, "fa5s.circle", PALETTE['textSub'])
        _acc  = PALETTE['accent']
        _dng  = PALETTE['danger']
        _surf = PALETTE['surface']
        self._on_btn.setStyleSheet(
            f"background:{_surf}; color:{_acc}; border-color:{_acc}; font-weight:bold;")
        self._off_btn.setStyleSheet(
            f"background:{_surf}; color:{_dng}; border-color:{_dng}; font-weight:bold;")
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

        # ── AMCAD BILT pulse configuration (hidden until BILT connects) ─
        self._bilt_panel = CollapsiblePanel(
            "AMCAD BILT Pulse Configuration", start_collapsed=False)

        bilt_inner = QWidget()
        bg = QGridLayout(bilt_inner)
        bg.setContentsMargins(0, 4, 0, 0)
        bg.setSpacing(8)

        # Column headers
        for col, hdr in enumerate(["", "Bias (V)", "Pulse (V)",
                                    "Width (µs)", "Delay (µs)"], start=0):
            lbl = QLabel(hdr)
            lbl.setObjectName("sublabel")
            lbl.setAlignment(Qt.AlignCenter if col > 0 else Qt.AlignLeft)
            bg.addWidget(lbl, 0, col)

        def _bilt_spin(lo, hi, val, dec=3, step=0.1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setFixedWidth(100)
            return s

        # Gate channel (ch1)
        bg.addWidget(QLabel("Gate  (Ch 1)"), 1, 0)
        self._g_bias_sp  = _bilt_spin(-40, 40,   -5.0)
        self._g_pulse_sp = _bilt_spin(-40, 40,   -2.2)
        self._g_width_sp = _bilt_spin(0.1, 999999, 110.0, dec=1, step=10)
        self._g_delay_sp = _bilt_spin(0.0, 999999,   5.0, dec=1, step=1)
        bg.addWidget(self._g_bias_sp,  1, 1)
        bg.addWidget(self._g_pulse_sp, 1, 2)
        bg.addWidget(self._g_width_sp, 1, 3)
        bg.addWidget(self._g_delay_sp, 1, 4)

        # Drain channel (ch2)
        bg.addWidget(QLabel("Drain (Ch 2)"), 2, 0)
        self._d_bias_sp  = _bilt_spin(-40, 40,    0.0)
        self._d_pulse_sp = _bilt_spin(-40, 40,    1.0)
        self._d_width_sp = _bilt_spin(0.1, 999999, 100.0, dec=1, step=10)
        self._d_delay_sp = _bilt_spin(0.0, 999999,  10.0, dec=1, step=1)
        bg.addWidget(self._d_bias_sp,  2, 1)
        bg.addWidget(self._d_pulse_sp, 2, 2)
        bg.addWidget(self._d_width_sp, 2, 3)
        bg.addWidget(self._d_delay_sp, 2, 4)

        apply_bilt_btn = QPushButton("Apply Pulse Config")
        apply_bilt_btn.setFixedWidth(160)
        apply_bilt_btn.setToolTip(
            "Push Gate + Drain pulse parameters to the AMCAD BILT.\n"
            "Does not enable output — click 'Output ON' after.")
        apply_bilt_btn.clicked.connect(self._apply_bilt_pulse)
        bg.addWidget(apply_bilt_btn, 3, 1, 1, 2)

        self._bilt_panel.addWidget(bilt_inner)
        self._bilt_panel.setVisible(False)
        root.addWidget(self._bilt_panel)

        root.addStretch()

        # Driver reference (set by main_app when a bias device connects)
        self._bias_driver = None

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

        icon_lbl = make_icon_label(IC.LINK_OFF, color=PALETTE['textSub'], size=64)
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(f"{title} Not Connected")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; font-weight: bold; "
            f"color: {PALETTE['textDim']};")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: {PALETTE['textSub']};")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        _acc = PALETTE['accent']
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['surface']}; color: {_acc};
                border: 1px solid {_acc}66; border-radius: 5px;
                font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: {PALETTE['surface2']}; }}
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

    def show_device_error(self, key: str, name: str, message: str) -> None:
        self._error_banner.show_error(key, name, message)

    def clear_device_error(self) -> None:
        self._error_banner.clear()

    def set_hardware_available(self, available: bool) -> None:
        """Switch between empty state (page 0) and full controls (page 1)."""
        self._stack.setCurrentIndex(1 if available else 0)

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, pal_key):
        """Create a readout widget.  pal_key is a PALETTE key (e.g. "accent")."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        color = PALETTE[pal_key]
        val.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val     = val
        w._pal_key = pal_key
        return w

    def _apply_styles(self):
        """Re-apply PALETTE-driven colours on theme switch."""
        # Readout value labels
        for rw in (self._v_w, self._i_w, self._p_w, self._comp_w, self._state_w):
            color = PALETTE[rw._pal_key]
            rw._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{color};")
        # Unit / indicator labels
        dim  = PALETTE['textDim']
        acc  = PALETTE['accent']
        dng  = PALETTE['danger']
        surf = PALETTE['surface']
        if hasattr(self, "_level_unit"):
            self._level_unit.setStyleSheet(f"color:{dim}; font-size:{FONT['body']}pt;")
        if hasattr(self, "_comp_unit"):
            self._comp_unit.setStyleSheet(f"color:{dim}; font-size:{FONT['body']}pt;")
        # ON/OFF buttons
        if hasattr(self, "_on_btn"):
            set_btn_icon(self._on_btn,  "fa5s.circle", acc)
            self._on_btn.setStyleSheet(
                f"background:{surf}; color:{acc}; border-color:{acc}; font-weight:bold;")
        if hasattr(self, "_off_btn"):
            set_btn_icon(self._off_btn, "fa5s.circle", PALETTE['textSub'])
            self._off_btn.setStyleSheet(
                f"background:{surf}; color:{dng}; border-color:{dng}; font-weight:bold;")
        # Re-run level validation to update the indicator colour
        if hasattr(self, "_level_spin"):
            self._validate_level()

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
                f"color:{PALETTE['accent']}; font-size:{FONT['caption']}pt; padding-left:6px;")
        else:
            self._level_indicator.setText(f"\u2717 exceeds {limit_str} limit")
            self._level_indicator.setStyleSheet(
                f"color:{PALETTE['danger']}; font-size:{FONT['caption']}pt; padding-left:6px;")

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

    # ── Driver-aware wiring ───────────────────────────────────────────

    def set_bias_driver(self, driver) -> None:
        """
        Called by main_app when a bias device connects or disconnects.
        Reveals BILT-specific controls and Gate readout row for AmcadBiltDriver.
        """
        from hardware.bias.amcad_bilt import AmcadBiltDriver
        self._bias_driver = driver
        is_bilt = isinstance(driver, AmcadBiltDriver)
        self._bilt_panel.setVisible(is_bilt)
        self._gate_row.setVisible(is_bilt)

    def _apply_bilt_pulse(self) -> None:
        """Push Gate + Drain pulse parameters to the AMCAD BILT driver."""
        from hardware.bias.amcad_bilt import AmcadBiltDriver
        drv = self._bias_driver
        if not isinstance(drv, AmcadBiltDriver):
            drv = app_state.bias
        if not isinstance(drv, AmcadBiltDriver):
            return
        try:
            drv.configure_pulse(
                channel = 1,
                bias_v  = self._g_bias_sp.value(),
                pulse_v = self._g_pulse_sp.value(),
                width_s = self._g_width_sp.value() * 1e-6,
                delay_s = self._g_delay_sp.value() * 1e-6,
            )
            drv.configure_pulse(
                channel = 2,
                bias_v  = self._d_bias_sp.value(),
                pulse_v = self._d_pulse_sp.value(),
                width_s = self._d_width_sp.value() * 1e-6,
                delay_s = self._d_delay_sp.value() * 1e-6,
            )
            log.info("BILT pulse config applied.")
        except Exception as exc:
            log.error("BILT configure_pulse failed: %s", exc)

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
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
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
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['success']};")
        else:
            self._state_w._val.setText("OFF ○")
            self._state_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['textSub']};")

        # Gate-channel readout (AMCAD BILT only)
        if self._gate_row.isVisible() and hasattr(status, "gate_voltage"):
            self._gate_v_w._val.setText(f"{status.gate_voltage:.4f} V")
            self._gate_i_w._val.setText(f"{status.gate_current*1000:.3f} mA")
