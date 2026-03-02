"""
ui/tabs/fpga_tab.py

FpgaTab — FPGA control tab with frequency, duty cycle, and stimulus controls.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QFrame)
from PyQt5.QtCore    import Qt

from hardware.app_state import app_state


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #2a2a2a;")
    return f


class FpgaTab(QWidget):
    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Status readouts
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._freq_w    = self._readout("FREQUENCY",   "--",    "#00d4aa")
        self._duty_w    = self._readout("DUTY CYCLE",  "--",    "#ffaa44")
        self._frames_w  = self._readout("FRAME COUNT", "--",    "#6699ff")
        self._sync_w    = self._readout("SYNC",        "UNKNOWN","#555")
        self._stim_w    = self._readout("STIMULUS",    "OFF",   "#555")
        for w in [self._freq_w, self._duty_w, self._frames_w,
                  self._sync_w, self._stim_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        cl.addWidget(self._sub("Frequency (Hz)"), 0, 0)
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(0.1, 100000)
        self._freq_spin.setValue(1000)
        self._freq_spin.setDecimals(1)
        self._freq_spin.setFixedWidth(110)
        cl.addWidget(self._freq_spin, 0, 1)

        # Frequency presets
        freq_row = QHBoxLayout()
        for lbl, val in [("1 Hz",1),("10 Hz",10),("100 Hz",100),
                         ("1 kHz",1000),("10 kHz",10000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(62)
            b.clicked.connect(
                lambda _, v=val: (self._freq_spin.setValue(v),
                                  self._set_freq(v)))
            freq_row.addWidget(b)
        freq_row.addStretch()
        cl.addLayout(freq_row, 1, 1)

        cl.addWidget(self._sub("Duty Cycle (%)"), 2, 0)
        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(1, 99)
        self._duty_spin.setValue(50)
        self._duty_spin.setDecimals(0)
        self._duty_spin.setFixedWidth(110)
        cl.addWidget(self._duty_spin, 2, 1)

        duty_row = QHBoxLayout()
        for lbl, val in [("10%",10),("25%",25),("50%",50),
                         ("75%",75),("90%",90)]:
            b = QPushButton(lbl)
            b.setFixedWidth(52)
            b.clicked.connect(
                lambda _, v=val: (self._duty_spin.setValue(v),
                                  self._set_duty(v/100.0)))
            duty_row.addWidget(b)
        duty_row.addStretch()
        cl.addLayout(duty_row, 3, 1)

        cl.addWidget(hline(), 4, 0, 1, 3)

        # Apply + run buttons
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Settings")
        apply_btn.clicked.connect(self._apply)
        start_btn = QPushButton("▶  Start")
        start_btn.setObjectName("primary")
        stop_btn  = QPushButton("■  Stop")
        stop_btn.setObjectName("danger")
        stim_on   = QPushButton("Stimulus ON")
        stim_off  = QPushButton("Stimulus OFF")
        stim_on.setStyleSheet(
            "background:#331a00; color:#ffaa44; border-color:#cc6600;")
        stim_off.setStyleSheet(
            "background:#1a1a2e; color:#6699ff; border-color:#3355aa;")

        for b in [apply_btn, start_btn, stop_btn, stim_on, stim_off]:
            b.setFixedWidth(110)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row, 5, 0, 1, 3)

        start_btn.clicked.connect(self._start)
        stop_btn.clicked.connect(self._stop)
        stim_on.clicked.connect(lambda: self._set_stimulus(True))
        stim_off.clicked.connect(lambda: self._set_stimulus(False))

        root.addWidget(ctrl_box)
        root.addStretch()

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
            f"font-family:Menlo,monospace; font-size:28pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def update_status(self, status):
        if status.error:
            self._sync_w._val.setText("ERROR")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ff6666;")
            return

        self._freq_w._val.setText(f"{status.freq_hz:,.0f} Hz")
        self._duty_w._val.setText(f"{status.duty_cycle*100:.0f}%")
        self._frames_w._val.setText(f"{status.frame_count:,}")

        if status.sync_locked:
            self._sync_w._val.setText("LOCKED ✓")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#00d4aa;")
        else:
            self._sync_w._val.setText("UNLOCKED")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#555;")

        if status.stimulus_on:
            self._stim_w._val.setText("ON ●")
            self._stim_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ffaa44;")
        else:
            self._stim_w._val.setText("OFF ○")
            self._stim_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#444;")

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
