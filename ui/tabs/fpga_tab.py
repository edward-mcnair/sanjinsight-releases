"""
ui/tabs/fpga_tab.py

FpgaTab — FPGA modulation controller (frequency, duty cycle, stimulus).

Layout
------
Basic (always visible)
  • Status readouts (FREQUENCY / DUTY CYCLE / FRAME COUNT / SYNC / STIMULUS)
  • Quick frequency presets (1 Hz – 10 kHz)
  • Quick duty-cycle presets (10 % – 90 %)
  • Start / Stop / Stimulus On / Off buttons

Advanced (collapsible, hidden by default)
  • Exact frequency spinbox + duty cycle spinbox
  • Apply Settings button
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QFrame, QComboBox,
    QInputDialog, QMessageBox, QStackedWidget, QButtonGroup, QRadioButton,
    QScrollArea)
from PyQt5.QtCore    import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.widgets.collapsible_panel import CollapsiblePanel
from ui.widgets.more_options import MoreOptionsPanel
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.icons import IC, make_icon_label, set_btn_icon


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


class FpgaTab(QWidget):
    open_device_manager = pyqtSignal()

    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service
        from hardware.hardware_preset_manager import (
            HardwarePresetManager, FPGA_FACTORY_PRESETS)
        self._preset_mgr = HardwarePresetManager("fpga", FPGA_FACTORY_PRESETS)

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "FPGA", "NI FPGA controller",
            "Connect the NI FPGA controller in Device Manager to enable controls."))

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

        # ── Status readouts ───────────────────────────────────────────
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._freq_w   = self._readout("FREQUENCY",   "--",     PALETTE['accent'])
        self._duty_w   = self._readout("DUTY CYCLE",  "--",     PALETTE['warning'])
        self._frames_w = self._readout("FRAME COUNT", "--",     PALETTE['info'])
        self._sync_w   = self._readout("SYNC",        "UNKNOWN",PALETTE['textDim'])
        self._stim_w   = self._readout("STIMULUS",    "OFF",    PALETTE['textDim'])
        self._trig_w   = self._readout("TRIGGER",     "CONT",   PALETTE['textDim'])
        self._trig_w.setVisible(False)   # shown only for BNC 745
        for w in [self._freq_w, self._duty_w, self._frames_w,
                  self._sync_w, self._stim_w, self._trig_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # Sync-lock hint (shown only when FPGA sync is UNLOCKED)
        self._sync_hint_lbl = QLabel(
            "ℹ  Sync UNLOCKED — modulation is running but the clock is not "
            "phase-locked to the camera. Check the FPGA–camera trigger cable and "
            "restart modulation. Acquisition will not be synchronised until locked.")
        self._sync_hint_lbl.setStyleSheet(
            f"color:{PALETTE['info']}; font-size:{FONT['caption']}pt;")
        self._sync_hint_lbl.setWordWrap(True)
        self._sync_hint_lbl.setVisible(False)
        root.addWidget(self._sync_hint_lbl)

        # ── Configuration presets ──────────────────────────────────────
        preset_box = QGroupBox("Configuration Presets")
        pl = QHBoxLayout(preset_box)
        pl.setContentsMargins(8, 6, 8, 6)
        pl.setSpacing(6)

        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(240)
        self._preset_combo.setToolTip("Load a named FPGA configuration preset")
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

        # ── Quick controls (basic) ─────────────────────────────────────
        ctrl_box = QGroupBox("Quick Controls")
        cl = QVBoxLayout(ctrl_box)
        cl.setSpacing(8)

        # Frequency presets row
        freq_hdr = QLabel("Modulation frequency")
        freq_hdr.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']};")
        cl.addWidget(freq_hdr)

        freq_row = QHBoxLayout()
        for lbl, val in [("1 Hz", 1), ("10 Hz", 10), ("100 Hz", 100),
                         ("1 kHz", 1000), ("10 kHz", 10000)]:
            b = QPushButton(lbl)
            b.setMinimumWidth(80)
            b.clicked.connect(
                lambda _, v=val: (self._freq_spin.setValue(v), self._set_freq(v)))
            freq_row.addWidget(b)
        freq_row.addStretch()
        cl.addLayout(freq_row)

        # Duty cycle presets row
        duty_hdr = QLabel("Duty cycle  (hot / cold timing ratio)")
        duty_hdr.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']};")
        cl.addWidget(duty_hdr)

        duty_row = QHBoxLayout()
        for lbl, val in [("10%", 10), ("25%", 25), ("50%", 50),
                         ("75%", 75), ("90%", 90)]:
            b = QPushButton(lbl)
            b.setFixedWidth(62)
            b.clicked.connect(
                lambda _, v=val: (self._duty_spin.setValue(v),
                                  self._set_duty(v / 100.0)))
            duty_row.addWidget(b)
        duty_row.addStretch()
        cl.addLayout(duty_row)

        # Duty cycle overheating warning (shown when duty ≥ 50 %)
        self._dc_warn_lbl = QLabel(
            "⚠  Duty cycle ≥ 50 % increases average power delivered to the DUT. "
            "Monitor device temperature closely — risk of overheating.")
        self._dc_warn_lbl.setStyleSheet(
            f"color:{PALETTE['warning']}; font-size:{FONT['caption']}pt;")
        self._dc_warn_lbl.setWordWrap(True)
        self._dc_warn_lbl.setVisible(False)
        cl.addWidget(self._dc_warn_lbl)

        cl.addWidget(hline())

        # Start / Stop / Output row
        btn_row = QHBoxLayout()
        start_btn = QPushButton("Start Modulation")
        set_btn_icon(start_btn, "fa5s.play", PALETTE['accent'])
        start_btn.setObjectName("primary")
        stop_btn  = QPushButton("Stop")
        set_btn_icon(stop_btn, "fa5s.stop", PALETTE['danger'])
        stop_btn.setObjectName("danger")
        self._stim_on_btn  = QPushButton("Output ON")
        self._stim_off_btn = QPushButton("Output OFF")
        stim_on  = self._stim_on_btn
        stim_off = self._stim_off_btn
        stim_on.setStyleSheet(
            f"background:{PALETTE['warningBg']}; color:{PALETTE['warning']}; "
            f"border:1px solid {PALETTE['warning']}55; border-radius:6px;")
        stim_off.setStyleSheet(
            f"background:{PALETTE['infoBg']}; color:{PALETTE['info']}; "
            f"border:1px solid {PALETTE['info']}55; border-radius:6px;")
        start_btn.setFixedWidth(150)
        for b in [stop_btn, stim_on, stim_off]:
            b.setFixedWidth(110)
        for b in [start_btn, stop_btn, stim_on, stim_off]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row)

        start_btn.clicked.connect(self._start)
        stop_btn.clicked.connect(self._stop)
        stim_on.clicked.connect(lambda: self._set_stimulus(True))
        stim_off.clicked.connect(lambda: self._set_stimulus(False))

        root.addWidget(ctrl_box)

        # ── Advanced: exact value spinboxes (collapsible) ─────────────
        adv_panel = MoreOptionsPanel(
            "Manual frequency & duty cycle", section_key="fpga_manual")

        adv_inner = QWidget()
        adv_grid  = QGridLayout(adv_inner)
        adv_grid.setContentsMargins(0, 0, 0, 0)
        adv_grid.setSpacing(10)

        adv_grid.addWidget(self._sub("Exact frequency (Hz)"), 0, 0)
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(0.1, 100000)
        self._freq_spin.setValue(1000)
        self._freq_spin.setDecimals(1)
        self._freq_spin.setFixedWidth(120)
        self._freq_spin.setToolTip(
            "Modulation rate — the FPGA switches the stimulus at this frequency.\n"
            "Use the quick-preset buttons above for common values.")
        adv_grid.addWidget(self._freq_spin, 0, 1)
        self._freq_indicator = QLabel("✓")
        self._freq_indicator.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT['body']}pt; padding-left:4px;")
        adv_grid.addWidget(self._freq_indicator, 0, 2)

        adv_grid.addWidget(self._sub("Exact duty cycle (%)"), 1, 0)
        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(1, 99)
        self._duty_spin.setValue(50)
        self._duty_spin.setDecimals(0)
        self._duty_spin.setFixedWidth(120)
        self._duty_spin.setToolTip(
            "Fraction of each cycle that the stimulus is ON.\n"
            "50 % = equal hot and cold dwell time.")
        adv_grid.addWidget(self._duty_spin, 1, 1)
        self._duty_indicator = QLabel("✓")
        self._duty_indicator.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT['body']}pt; padding-left:4px;")
        adv_grid.addWidget(self._duty_indicator, 1, 2)

        apply_btn = QPushButton("Apply Only (no start)")
        apply_btn.setToolTip(
            "Push frequency and duty cycle to the FPGA without starting modulation.\n"
            "Use '▶  Start Modulation' in Quick Controls to apply AND start.")
        apply_btn.clicked.connect(self._apply)
        adv_grid.addWidget(apply_btn, 2, 1)

        # Connect duty spinbox to the overheating warning
        self._duty_spin.valueChanged.connect(self._on_duty_changed)

        # Connect spinboxes to inline validation indicators
        self._freq_spin.valueChanged.connect(
            lambda v: self._validate_indicator(self._freq_indicator, v, 0.1, 100000))
        self._duty_spin.valueChanged.connect(
            lambda v: self._validate_indicator(self._duty_indicator, v, 1, 99))

        # Initialise indicators to reflect default values
        self._validate_indicator(self._freq_indicator, self._freq_spin.value(), 0.1, 100000)
        self._validate_indicator(self._duty_indicator, self._duty_spin.value(), 1, 99)

        adv_panel.addWidget(adv_inner)
        root.addWidget(adv_panel)

        # ── Trigger mode (BNC 745 / single-shot capable devices) ──────
        # Hidden until set_fpga_driver() reveals it for a capable driver.
        self._trigger_panel = CollapsiblePanel(
            "Trigger Mode  (BNC 745)", start_collapsed=False)

        trig_inner = QWidget()
        trig_grid  = QGridLayout(trig_inner)
        trig_grid.setContentsMargins(0, 0, 0, 0)
        trig_grid.setSpacing(10)

        trig_grid.addWidget(self._sub("Mode"), 0, 0)
        mode_row = QHBoxLayout()
        self._trig_mode_bg   = QButtonGroup()
        self._trig_cont_rb   = QRadioButton("Continuous")
        self._trig_single_rb = QRadioButton("Single-shot")
        self._trig_cont_rb.setChecked(True)
        self._trig_mode_bg.addButton(self._trig_cont_rb,   0)
        self._trig_mode_bg.addButton(self._trig_single_rb, 1)
        mode_row.addWidget(self._trig_cont_rb)
        mode_row.addWidget(self._trig_single_rb)
        mode_row.addStretch()
        trig_grid.addLayout(mode_row, 0, 1)
        self._trig_mode_bg.buttonClicked.connect(self._on_trig_mode_change)

        trig_grid.addWidget(self._sub("Pulse Duration (µs)"), 1, 0)
        pulse_row = QHBoxLayout()
        self._pulse_dur_spin = QDoubleSpinBox()
        self._pulse_dur_spin.setRange(0.1, 999_999.0)
        self._pulse_dur_spin.setValue(100.0)
        self._pulse_dur_spin.setDecimals(1)
        self._pulse_dur_spin.setSingleStep(10.0)
        self._pulse_dur_spin.setFixedWidth(120)
        self._pulse_dur_spin.setToolTip(
            "Override camera-channel pulse width in single-shot mode (BNC 745 Ch1).")
        apply_pulse_btn = QPushButton("Set Width")
        apply_pulse_btn.setFixedWidth(90)
        apply_pulse_btn.clicked.connect(self._apply_pulse_duration)
        pulse_row.addWidget(self._pulse_dur_spin)
        pulse_row.addWidget(apply_pulse_btn)
        pulse_row.addStretch()
        trig_grid.addLayout(pulse_row, 1, 1)

        self._arm_btn = QPushButton("▶  Arm Trigger")
        self._arm_btn.setFixedWidth(130)
        self._arm_btn.setEnabled(False)
        self._arm_btn.setToolTip(
            "Fire one single-shot pulse.\nSwitch to Single-shot mode first.")
        self._arm_btn.clicked.connect(self._arm_trigger)
        trig_grid.addWidget(self._arm_btn, 2, 1)

        self._trigger_panel.addWidget(trig_inner)
        self._trigger_panel.setVisible(False)
        root.addWidget(self._trigger_panel)

        # ── Voltage output controls (EZ-500 only, collapsible) ────────
        self._voltage_panel = MoreOptionsPanel(
            "Voltage Output  (±16 V DAC)", section_key="fpga_voltage")

        v_inner = QWidget()
        v_grid  = QGridLayout(v_inner)
        v_grid.setContentsMargins(0, 0, 0, 0)
        v_grid.setSpacing(8)

        v_grid.addWidget(self._sub("Main Voltage (V)"), 0, 0)
        self._vout_spin = QDoubleSpinBox()
        self._vout_spin.setRange(-16.0, 15.999)
        self._vout_spin.setValue(0.0)
        self._vout_spin.setDecimals(3)
        self._vout_spin.setSingleStep(0.1)
        self._vout_spin.setFixedWidth(120)
        self._vout_spin.setToolTip("Main DAC voltage output (−16 V to +16 V)")
        v_grid.addWidget(self._vout_spin, 0, 1)

        v_grid.addWidget(self._sub("Aux Voltage (V)"), 1, 0)
        self._vaux_spin = QDoubleSpinBox()
        self._vaux_spin.setRange(-16.0, 15.999)
        self._vaux_spin.setValue(0.0)
        self._vaux_spin.setDecimals(3)
        self._vaux_spin.setSingleStep(0.1)
        self._vaux_spin.setFixedWidth(120)
        self._vaux_spin.setToolTip("Auxiliary DAC voltage output (−16 V to +16 V)")
        v_grid.addWidget(self._vaux_spin, 1, 1)

        v_grid.addWidget(self._sub("Vout Limit (V)"), 2, 0)
        self._vo_lim_spin = QDoubleSpinBox()
        self._vo_lim_spin.setRange(-16.0, 15.999)
        self._vo_lim_spin.setValue(5.0)
        self._vo_lim_spin.setDecimals(3)
        self._vo_lim_spin.setFixedWidth(120)
        v_grid.addWidget(self._vo_lim_spin, 2, 1)

        v_grid.addWidget(self._sub("Vaux Limit (V)"), 3, 0)
        self._va_lim_spin = QDoubleSpinBox()
        self._va_lim_spin.setRange(-16.0, 15.999)
        self._va_lim_spin.setValue(5.0)
        self._va_lim_spin.setDecimals(3)
        self._va_lim_spin.setFixedWidth(120)
        v_grid.addWidget(self._va_lim_spin, 3, 1)

        self._high_range_cb = QPushButton("High Range")
        self._high_range_cb.setCheckable(True)
        self._high_range_cb.setFixedWidth(110)
        self._high_range_cb.setToolTip("Enable high voltage range on analog outputs")
        self._high_range_cb.toggled.connect(self._set_high_range)
        v_grid.addWidget(self._high_range_cb, 0, 2)

        v_btn_row = QHBoxLayout()
        apply_v_btn = QPushButton("Apply Voltages")
        apply_v_btn.setFixedWidth(130)
        apply_v_btn.clicked.connect(self._apply_voltages)
        disable_v_btn = QPushButton("Disable All")
        disable_v_btn.setFixedWidth(110)
        disable_v_btn.setObjectName("danger")
        disable_v_btn.clicked.connect(self._disable_voltages)
        v_btn_row.addWidget(apply_v_btn)
        v_btn_row.addWidget(disable_v_btn)
        v_btn_row.addStretch()
        v_grid.addLayout(v_btn_row, 4, 0, 1, 3)

        self._voltage_panel.addWidget(v_inner)
        self._voltage_panel.setVisible(False)
        root.addWidget(self._voltage_panel)

        # ── LED illumination controls (EZ-500 only, collapsible) ──────
        self._led_panel = MoreOptionsPanel(
            "LED Illumination Timing", section_key="fpga_led")

        led_inner = QWidget()
        led_grid  = QGridLayout(led_inner)
        led_grid.setContentsMargins(0, 0, 0, 0)
        led_grid.setSpacing(8)

        led_grid.addWidget(self._sub("LED Phase (ticks)"), 0, 0)
        self._led_phase_spin = QDoubleSpinBox()
        self._led_phase_spin.setRange(0, 4294967295)
        self._led_phase_spin.setDecimals(0)
        self._led_phase_spin.setFixedWidth(120)
        led_grid.addWidget(self._led_phase_spin, 0, 1)

        led_grid.addWidget(self._sub("LED Time ON (ticks)"), 1, 0)
        self._led_ton_spin = QDoubleSpinBox()
        self._led_ton_spin.setRange(0, 4294967295)
        self._led_ton_spin.setDecimals(0)
        self._led_ton_spin.setFixedWidth(120)
        led_grid.addWidget(self._led_ton_spin, 1, 1)

        led_grid.addWidget(self._sub("LED Pulse Phase (ticks)"), 2, 0)
        self._led_pulse_ph_spin = QDoubleSpinBox()
        self._led_pulse_ph_spin.setRange(0, 4294967295)
        self._led_pulse_ph_spin.setDecimals(0)
        self._led_pulse_ph_spin.setFixedWidth(120)
        led_grid.addWidget(self._led_pulse_ph_spin, 2, 1)

        led_grid.addWidget(self._sub("LED Pulse Time (ticks)"), 3, 0)
        self._led_pulse_time_spin = QDoubleSpinBox()
        self._led_pulse_time_spin.setRange(0, 4294967295)
        self._led_pulse_time_spin.setDecimals(0)
        self._led_pulse_time_spin.setFixedWidth(120)
        led_grid.addWidget(self._led_pulse_time_spin, 3, 1)

        apply_led_btn = QPushButton("Apply LED Timing")
        apply_led_btn.setFixedWidth(140)
        apply_led_btn.clicked.connect(self._apply_led_timing)
        led_grid.addWidget(apply_led_btn, 4, 1)

        self._led_panel.addWidget(led_inner)
        self._led_panel.setVisible(False)
        root.addWidget(self._led_panel)

        # ── Phase / timing controls (EZ-500 only, collapsible) ────────
        self._phase_panel = MoreOptionsPanel(
            "Phase Offsets & Timing", section_key="fpga_phase")

        ph_inner = QWidget()
        ph_grid  = QGridLayout(ph_inner)
        ph_grid.setContentsMargins(0, 0, 0, 0)
        ph_grid.setSpacing(8)

        ph_grid.addWidget(self._sub("Device Phase (ticks)"), 0, 0)
        self._dev_phase_spin = QDoubleSpinBox()
        self._dev_phase_spin.setRange(0, 4294967295)
        self._dev_phase_spin.setDecimals(0)
        self._dev_phase_spin.setFixedWidth(120)
        ph_grid.addWidget(self._dev_phase_spin, 0, 1)

        ph_grid.addWidget(self._sub("Device Phase 2 (ticks)"), 1, 0)
        self._dev_phase2_spin = QDoubleSpinBox()
        self._dev_phase2_spin.setRange(0, 4294967295)
        self._dev_phase2_spin.setDecimals(0)
        self._dev_phase2_spin.setFixedWidth(120)
        ph_grid.addWidget(self._dev_phase2_spin, 1, 1)

        self._use_phase2_cb = QPushButton("Use Phase 2")
        self._use_phase2_cb.setCheckable(True)
        self._use_phase2_cb.setFixedWidth(110)
        ph_grid.addWidget(self._use_phase2_cb, 1, 2)

        ph_grid.addWidget(self._sub("Exposure Time (ticks)"), 2, 0)
        self._exposure_spin = QDoubleSpinBox()
        self._exposure_spin.setRange(0, 4294967295)
        self._exposure_spin.setDecimals(0)
        self._exposure_spin.setFixedWidth(120)
        ph_grid.addWidget(self._exposure_spin, 2, 1)

        ph_grid.addWidget(self._sub("Sample Rate (divisor)"), 3, 0)
        self._samp_rate_spin = QDoubleSpinBox()
        self._samp_rate_spin.setRange(1, 4294967295)
        self._samp_rate_spin.setValue(1)
        self._samp_rate_spin.setDecimals(0)
        self._samp_rate_spin.setFixedWidth(120)
        ph_grid.addWidget(self._samp_rate_spin, 3, 1)

        apply_ph_btn = QPushButton("Apply Phase & Timing")
        apply_ph_btn.setFixedWidth(160)
        apply_ph_btn.clicked.connect(self._apply_phase_timing)
        ph_grid.addWidget(apply_ph_btn, 4, 1)

        self._phase_panel.addWidget(ph_inner)
        self._phase_panel.setVisible(False)
        root.addWidget(self._phase_panel)

        # ── Synchronisation & trigger I/O (EZ-500 only, collapsible) ──
        self._sync_panel = MoreOptionsPanel(
            "Synchronisation & Trigger I/O", section_key="fpga_sync")

        sync_inner = QWidget()
        sync_grid  = QGridLayout(sync_inner)
        sync_grid.setContentsMargins(0, 0, 0, 0)
        sync_grid.setSpacing(8)

        self._synch_enable_cb = QPushButton("Enable Ext. Sync")
        self._synch_enable_cb.setCheckable(True)
        self._synch_enable_cb.setFixedWidth(140)
        self._synch_enable_cb.toggled.connect(self._set_synch)
        sync_grid.addWidget(self._synch_enable_cb, 0, 0)

        sync_grid.addWidget(self._sub("Sync Phase (ticks)"), 0, 1)
        self._synch_phase_spin = QDoubleSpinBox()
        self._synch_phase_spin.setRange(0, 4294967295)
        self._synch_phase_spin.setDecimals(0)
        self._synch_phase_spin.setFixedWidth(120)
        sync_grid.addWidget(self._synch_phase_spin, 0, 2)

        self._trig_dir_cb = QPushButton("Trigger = Output")
        self._trig_dir_cb.setCheckable(True)
        self._trig_dir_cb.setChecked(True)
        self._trig_dir_cb.setFixedWidth(140)
        self._trig_dir_cb.setToolTip("When checked, FPGA drives the trigger BNC as output")
        self._trig_dir_cb.toggled.connect(self._set_trig_direction)
        sync_grid.addWidget(self._trig_dir_cb, 1, 0)

        self._ir_trig_cb = QPushButton("IR Frame Trigger")
        self._ir_trig_cb.setCheckable(True)
        self._ir_trig_cb.setFixedWidth(140)
        self._ir_trig_cb.setToolTip("Enable IR camera frame trigger output")
        self._ir_trig_cb.toggled.connect(self._set_ir_frame_trigger)
        sync_grid.addWidget(self._ir_trig_cb, 1, 1)

        self._sync_panel.addWidget(sync_inner)
        self._sync_panel.setVisible(False)
        root.addWidget(self._sync_panel)

        # ── Event trigger (EZ-500 only, collapsible) ──────────────────
        self._event_panel = MoreOptionsPanel(
            "Event Trigger System", section_key="fpga_event")

        ev_inner = QWidget()
        ev_grid  = QGridLayout(ev_inner)
        ev_grid.setContentsMargins(0, 0, 0, 0)
        ev_grid.setSpacing(8)

        ev_grid.addWidget(self._sub("Event Source"), 0, 0)
        self._event_src_spin = QDoubleSpinBox()
        self._event_src_spin.setRange(0, 32767)
        self._event_src_spin.setDecimals(0)
        self._event_src_spin.setFixedWidth(120)
        ev_grid.addWidget(self._event_src_spin, 0, 1)

        ev_grid.addWidget(self._sub("Event Time (µs)"), 1, 0)
        self._event_time_spin = QDoubleSpinBox()
        self._event_time_spin.setRange(0, 4294967295)
        self._event_time_spin.setDecimals(0)
        self._event_time_spin.setFixedWidth(120)
        self._event_time_spin.setValue(100)
        ev_grid.addWidget(self._event_time_spin, 1, 1)

        ev_grid.addWidget(self._sub("Event Phase (µs)"), 2, 0)
        self._event_phase_spin = QDoubleSpinBox()
        self._event_phase_spin.setRange(0, 4294967295)
        self._event_phase_spin.setDecimals(0)
        self._event_phase_spin.setFixedWidth(120)
        self._event_phase_spin.setValue(100)
        ev_grid.addWidget(self._event_phase_spin, 2, 1)

        ev_btn_row = QHBoxLayout()
        apply_ev_btn = QPushButton("Apply Event Settings")
        apply_ev_btn.setFixedWidth(160)
        apply_ev_btn.clicked.connect(self._apply_event_settings)
        self._arm_event_btn = QPushButton("Arm Event")
        self._arm_event_btn.setFixedWidth(110)
        self._arm_event_btn.clicked.connect(self._arm_event)
        ev_btn_row.addWidget(apply_ev_btn)
        ev_btn_row.addWidget(self._arm_event_btn)
        ev_btn_row.addStretch()
        ev_grid.addLayout(ev_btn_row, 3, 0, 1, 3)

        self._event_panel.addWidget(ev_inner)
        self._event_panel.setVisible(False)
        root.addWidget(self._event_panel)

        root.addStretch()

        # Driver reference (set by main_app when a device connects)
        self._fpga_driver = None

        # Initialise warning state from the spinbox default (50 %)
        self._on_duty_changed(self._duty_spin.value())

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
        title_lbl.setStyleSheet(f"font-size: {FONT['readoutSm']}pt; font-weight: bold; color: {PALETTE['textDim']};")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: {PALETTE['textSub']};")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['surface']}; color: {PALETTE['accent']};
                border: 1px solid {PALETTE['accent']}66; border-radius: 5px;
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

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P   = PALETTE
        warn = P['warning']
        info = P['info']
        if hasattr(self, "_stim_on_btn"):
            self._stim_on_btn.setStyleSheet(
                f"background:{P['warningBg']}; color:{warn}; "
                f"border:1px solid {warn}55; border-radius:6px;")
        if hasattr(self, "_stim_off_btn"):
            self._stim_off_btn.setStyleSheet(
                f"background:{P['infoBg']}; color:{info}; "
                f"border:1px solid {info}55; border-radius:6px;")

    # ── Inline validation indicator ───────────────────────────────────

    def _validate_indicator(self, label: QLabel, value: float,
                             min_val: float, max_val: float) -> None:
        """Update *label* with a green ✓ or red ✗ depending on range."""
        if min_val <= value <= max_val:
            label.setText("✓")
            label.setStyleSheet(
                f"color:{PALETTE['accent']}; font-size:{FONT['body']}pt; padding-left:4px;")
        else:
            label.setText("✗")
            label.setStyleSheet(
                f"color:{PALETTE['danger']}; font-size:{FONT['body']}pt; padding-left:4px;")

    # ── Duty cycle overheating warning ───────────────────────────────

    def _on_duty_changed(self, val: float):
        from ai.instrument_knowledge import DUTY_CYCLE_WARN_PCT, DUTY_CYCLE_FAIL_PCT
        visible = val >= DUTY_CYCLE_WARN_PCT
        self._dc_warn_lbl.setVisible(visible)
        if visible:
            color = PALETTE['danger'] if val >= DUTY_CYCLE_FAIL_PCT else PALETTE['warning']
            self._dc_warn_lbl.setStyleSheet(
                f"color:{color}; font-size:{FONT['caption']}pt;")

    # ── Readout widget ────────────────────────────────────────────────

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
            f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

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
        freq = cfg.get("freq_hz")
        duty = cfg.get("duty_pct")
        if freq is not None:
            self._freq_spin.setValue(float(freq))
            self._set_freq(float(freq))
        if duty is not None:
            self._duty_spin.setValue(float(duty))
            self._set_duty(float(duty) / 100.0)

    def _save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:")
        if not (ok and name.strip()):
            return
        cfg = {
            "freq_hz":  self._freq_spin.value(),
            "duty_pct": self._duty_spin.value(),
        }
        self._preset_mgr.save(name.strip(), cfg)
        self._refresh_preset_combo()
        # Select the newly saved preset
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

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    # ── Status update ─────────────────────────────────────────────────

    def update_status(self, status):
        if status.error:
            self._sync_w._val.setText("ERROR")
            self._sync_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['danger']};")
            self._sync_hint_lbl.setVisible(False)
            return

        self._freq_w._val.setText(f"{status.freq_hz:,.0f} Hz")
        self._duty_w._val.setText(f"{status.duty_cycle*100:.0f}%")
        self._frames_w._val.setText(f"{status.frame_count:,}")

        if status.sync_locked:
            self._sync_w._val.setText("LOCKED ✓")
            self._sync_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['accent']};")
            self._sync_hint_lbl.setVisible(False)
        else:
            self._sync_w._val.setText("UNLOCKED")
            self._sync_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['warning']};")
            self._sync_hint_lbl.setVisible(True)

        if status.stimulus_on:
            self._stim_w._val.setText("ON ●")
            self._stim_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['warning']};")
        else:
            self._stim_w._val.setText("OFF ○")
            self._stim_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['textSub']};")

        # Trigger mode readout (BNC 745 only — hidden for NI-9637)
        if self._trig_w.isVisible():
            from hardware.fpga.base import FpgaTriggerMode
            if status.trigger_mode == FpgaTriggerMode.SINGLE_SHOT:
                label = "SINGLE ✦" if status.trigger_armed else "SINGLE"
                color = PALETTE['warning']
            else:
                label = "CONT"
                color = PALETTE['textDim']
            self._trig_w._val.setText(label)
            self._trig_w._val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; "
                f"color:{color};")

    # ── Driver-aware wiring ───────────────────────────────────────────

    def set_fpga_driver(self, driver) -> None:
        """
        Called by main_app when an FPGA device connects or disconnects.
        Reveals / hides panels based on driver capabilities.
        """
        self._fpga_driver = driver

        # Trigger mode panel (BNC 745 / NI-9637)
        capable = driver is not None and driver.supports_trigger_mode()
        self._trigger_panel.setVisible(capable)
        self._trig_w.setVisible(capable)
        if not capable:
            self._trig_cont_rb.setChecked(True)
            self._arm_btn.setEnabled(False)

        # EZ-500 extended panels — shown only for the NI9637 driver
        is_ez500 = driver is not None and hasattr(driver, 'set_voltage')
        self._voltage_panel.setVisible(is_ez500)
        self._led_panel.setVisible(is_ez500)
        self._phase_panel.setVisible(is_ez500)
        self._sync_panel.setVisible(is_ez500)
        self._event_panel.setVisible(is_ez500)

    # ── Trigger mode controls (BNC 745) ──────────────────────────────

    def _on_trig_mode_change(self) -> None:
        from hardware.fpga.base import FpgaTriggerMode
        single = self._trig_single_rb.isChecked()
        self._arm_btn.setEnabled(single)
        mode = FpgaTriggerMode.SINGLE_SHOT if single else FpgaTriggerMode.CONTINUOUS
        drv = self._fpga_driver
        if drv and drv.supports_trigger_mode():
            try:
                drv.set_trigger_mode(mode)
            except Exception as exc:
                log.error("set_trigger_mode failed: %s", exc)
        elif self._hw:
            try:
                self._hw.fpga_set_trigger_mode(mode)
            except Exception:
                pass

    def _apply_pulse_duration(self) -> None:
        us = self._pulse_dur_spin.value()
        drv = self._fpga_driver
        if drv and drv.supports_trigger_mode():
            try:
                drv.set_pulse_duration(us)
            except Exception as exc:
                log.error("set_pulse_duration failed: %s", exc)

    def _arm_trigger(self) -> None:
        drv = self._fpga_driver
        if drv and drv.supports_trigger_mode():
            try:
                drv.arm_trigger()
            except Exception as exc:
                log.error("arm_trigger failed: %s", exc)

    # ── Hardware commands ─────────────────────────────────────────────

    def _apply(self):
        self._set_freq(self._freq_spin.value())
        self._set_duty(self._duty_spin.value() / 100.0)

    def _set_freq(self, val):
        if self._hw:
            self._hw.fpga_set_frequency(val)
        else:
            fpga = app_state.fpga
            if fpga:
                fpga.set_frequency(val)

    def _set_duty(self, val):
        if self._hw:
            self._hw.fpga_set_duty_cycle(val)
        else:
            fpga = app_state.fpga
            if fpga:
                fpga.set_duty_cycle(val)

    def _start(self):
        self._apply()
        if self._hw:
            self._hw.fpga_start()
        else:
            fpga = app_state.fpga
            if fpga:
                fpga.start()

    def _stop(self):
        if self._hw:
            self._hw.fpga_stop()
        else:
            fpga = app_state.fpga
            if fpga:
                fpga.stop()

    def _set_stimulus(self, on: bool):
        if self._hw:
            self._hw.fpga_set_stimulus(on)
        else:
            fpga = app_state.fpga
            if fpga:
                fpga.set_stimulus(on)

    # ── EZ-500 voltage controls ───────────────────────────────────────

    def _apply_voltages(self):
        vout = self._vout_spin.value()
        vaux = self._vaux_spin.value()
        vo_lim = self._vo_lim_spin.value()
        va_lim = self._va_lim_spin.value()
        if self._hw:
            self._hw.fpga_set_voltage_limits(vo_lim, va_lim)
            self._hw.fpga_set_voltage(vout)
            self._hw.fpga_set_aux_voltage(vaux)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_voltage'):
                fpga.set_voltage_limits(vo_lim, va_lim)
                fpga.set_voltage(vout)
                fpga.set_aux_voltage(vaux)

    def _disable_voltages(self):
        if self._hw:
            self._hw.fpga_disable_voltage()
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'disable_voltage'):
                fpga.disable_voltage()

    def _set_high_range(self, checked: bool):
        if self._hw:
            self._hw.fpga_set_high_range(checked)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_high_range'):
                fpga.set_high_range(checked)

    # ── EZ-500 LED timing controls ────────────────────────────────────

    def _apply_led_timing(self):
        phase    = int(self._led_phase_spin.value())
        time_on  = int(self._led_ton_spin.value())
        p_phase  = int(self._led_pulse_ph_spin.value())
        p_time   = int(self._led_pulse_time_spin.value())
        if self._hw:
            self._hw.fpga_set_led_timing(phase, time_on)
            self._hw.fpga_set_led_pulsed(p_phase, p_time)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_led_timing'):
                fpga.set_led_timing(phase, time_on)
                fpga.set_led_pulsed(p_phase, p_time)

    # ── EZ-500 phase / timing controls ────────────────────────────────

    def _apply_phase_timing(self):
        phase  = int(self._dev_phase_spin.value())
        phase2 = int(self._dev_phase2_spin.value())
        use_p2 = self._use_phase2_cb.isChecked()
        exp    = int(self._exposure_spin.value())
        rate   = int(self._samp_rate_spin.value())
        if self._hw:
            self._hw.fpga_set_device_phase(phase, phase2, use_p2)
            self._hw.fpga_set_exposure_time(exp)
            self._hw.fpga_set_sample_rate(rate)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_device_phase'):
                fpga.set_device_phase(phase, phase2, use_p2)
                fpga.set_exposure_time(exp)
                fpga.set_sample_rate(rate)

    # ── EZ-500 sync / trigger I/O controls ────────────────────────────

    def _set_synch(self, checked: bool):
        phase = int(self._synch_phase_spin.value())
        if self._hw:
            self._hw.fpga_set_synch(checked, phase)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_synch'):
                fpga.set_synch(checked, phase)

    def _set_trig_direction(self, checked: bool):
        if self._hw:
            self._hw.fpga_set_trigger_direction(checked)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_trigger_direction'):
                fpga.set_trigger_direction(checked)

    def _set_ir_frame_trigger(self, checked: bool):
        if self._hw:
            self._hw.fpga_set_ir_frame_trigger(checked)
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_ir_frame_trigger'):
                fpga.set_ir_frame_trigger(checked)

    # ── EZ-500 event trigger controls ─────────────────────────────────

    def _apply_event_settings(self):
        source   = int(self._event_src_spin.value())
        time_us  = int(self._event_time_spin.value())
        phase_us = int(self._event_phase_spin.value())
        if self._hw:
            self._hw.fpga_set_event_source(source)
            self._hw.fpga_set_event_phase(phase_us)
            # Pulse duration is the event time register
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_pulse_duration'):
                fpga.set_pulse_duration(float(time_us))
        else:
            fpga = app_state.fpga
            if fpga and hasattr(fpga, 'set_event_source'):
                fpga.set_event_source(source)
                fpga.set_event_phase(phase_us)
                fpga.set_pulse_duration(float(time_us))

    def _arm_event(self):
        """Arm the event trigger."""
        drv = self._fpga_driver
        if drv and hasattr(drv, 'arm_trigger'):
            try:
                drv.arm_trigger()
            except Exception as exc:
                log.error("arm_trigger (event) failed: %s", exc)
