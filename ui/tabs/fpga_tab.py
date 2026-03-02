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
    QHBoxLayout, QGridLayout, QGroupBox, QFrame)
from PyQt5.QtCore    import Qt

from hardware.app_state import app_state
from ui.widgets.collapsible_panel import CollapsiblePanel
from ui.theme import FONT, PALETTE


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


class FpgaTab(QWidget):
    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── Status readouts ───────────────────────────────────────────
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._freq_w   = self._readout("FREQUENCY",   "--",     PALETTE["accent"])
        self._duty_w   = self._readout("DUTY CYCLE",  "--",     PALETTE["warning"])
        self._frames_w = self._readout("FRAME COUNT", "--",     PALETTE["info"])
        self._sync_w   = self._readout("SYNC",        "UNKNOWN",PALETTE["textDim"])
        self._stim_w   = self._readout("STIMULUS",    "OFF",    PALETTE["textDim"])
        for w in [self._freq_w, self._duty_w, self._frames_w,
                  self._sync_w, self._stim_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

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
            b.setFixedWidth(72)
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

        cl.addWidget(hline())

        # Start / Stop / Stimulus row
        btn_row = QHBoxLayout()
        start_btn = QPushButton("▶  Start")
        start_btn.setObjectName("primary")
        stop_btn  = QPushButton("■  Stop")
        stop_btn.setObjectName("danger")
        stim_on   = QPushButton("Stimulus ON")
        stim_off  = QPushButton("Stimulus OFF")
        stim_on.setStyleSheet(
            f"background:#331a00; color:{PALETTE['warning']}; border-color:#cc6600;")
        stim_off.setStyleSheet(
            f"background:#1a1a2e; color:{PALETTE['info']}; border-color:#3355aa;")
        for b in [start_btn, stop_btn, stim_on, stim_off]:
            b.setFixedWidth(110)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row)

        start_btn.clicked.connect(self._start)
        stop_btn.clicked.connect(self._stop)
        stim_on.clicked.connect(lambda: self._set_stimulus(True))
        stim_off.clicked.connect(lambda: self._set_stimulus(False))

        root.addWidget(ctrl_box)

        # ── Advanced: exact value spinboxes (collapsible) ─────────────
        adv_panel = CollapsiblePanel(
            "Manual frequency & duty cycle", start_collapsed=True)

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

        apply_btn = QPushButton("Apply Settings")
        apply_btn.clicked.connect(self._apply)
        adv_grid.addWidget(apply_btn, 2, 1)

        adv_panel.addWidget(adv_inner)
        root.addWidget(adv_panel)
        root.addStretch()

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
            f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    # ── Status update ─────────────────────────────────────────────────

    def update_status(self, status):
        if status.error:
            self._sync_w._val.setText("ERROR")
            self._sync_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['danger']};")
            return

        self._freq_w._val.setText(f"{status.freq_hz:,.0f} Hz")
        self._duty_w._val.setText(f"{status.duty_cycle*100:.0f}%")
        self._frames_w._val.setText(f"{status.frame_count:,}")

        if status.sync_locked:
            self._sync_w._val.setText("LOCKED ✓")
            self._sync_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['accent']};")
        else:
            self._sync_w._val.setText("UNLOCKED")
            self._sync_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['textDim']};")

        if status.stimulus_on:
            self._stim_w._val.setText("ON ●")
            self._stim_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; "
                f"color:{PALETTE['warning']};")
        else:
            self._stim_w._val.setText("OFF ○")
            self._stim_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; "
                f"color:#444;")

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
