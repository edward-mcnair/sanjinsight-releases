"""
ui/tabs/arduino_tab.py

ArduinoTab -- LED wavelength selector + GPIO control for Arduino Nano.

Layout:
    Page 0 (empty state): Connect prompt with Device Manager button
    Page 1 (connected):
        - LED Wavelength Selector (exclusive radio buttons)
        - GPIO Output pins (toggle buttons)
        - Analog Inputs (read-only displays, polled)
        - Firmware info / status
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QButtonGroup, QRadioButton,
    QFrame, QStackedWidget, QScrollArea, QSpinBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from hardware.app_state import app_state
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.icons import IC, set_btn_icon


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


class ArduinoTab(QWidget):
    """LED wavelength selector and GPIO control panel for Arduino Nano."""

    open_device_manager = pyqtSignal()

    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: empty state
        self._stack.addWidget(self._build_empty_state())

        # Page 1: full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── LED Wavelength Selector ──────────────────────────────
        led_box = QGroupBox("LED Wavelength")
        led_layout = QVBoxLayout(led_box)
        led_layout.setSpacing(6)

        self._led_group = QButtonGroup(self)
        self._led_group.setExclusive(True)
        self._led_radios: list = []

        # "All Off" radio
        off_radio = QRadioButton("All LEDs Off")
        off_radio.setChecked(True)
        self._led_group.addButton(off_radio, -1)
        led_layout.addWidget(off_radio)
        self._led_radios.append((-1, off_radio))

        # Channel radios (populated when connected)
        self._led_channels_layout = led_layout

        self._led_group.buttonClicked.connect(self._on_led_selected)
        root.addWidget(led_box)

        root.addWidget(_hline())

        # ── GPIO Output Pins ─────────────────────────────────────
        gpio_box = QGroupBox("Digital GPIO Output")
        gpio_grid = QGridLayout(gpio_box)
        gpio_grid.setSpacing(6)
        self._gpio_buttons: dict = {}  # pin → QPushButton

        # D6–D13 as general-purpose outputs (D2–D5 reserved for LEDs)
        for i, pin in enumerate(range(6, 14)):
            lbl = QLabel(f"D{pin}")
            lbl.setFixedWidth(30)
            btn = QPushButton("LOW")
            btn.setCheckable(True)
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda checked, p=pin: self._on_gpio_toggled(p, checked))
            gpio_grid.addWidget(lbl, i // 4, (i % 4) * 2)
            gpio_grid.addWidget(btn, i // 4, (i % 4) * 2 + 1)
            self._gpio_buttons[pin] = btn

        root.addWidget(gpio_box)

        root.addWidget(_hline())

        # ── Analog Inputs ────────────────────────────────────────
        adc_box = QGroupBox("Analog Inputs (10-bit ADC)")
        adc_grid = QGridLayout(adc_box)
        adc_grid.setSpacing(4)
        self._adc_labels: dict = {}  # channel → QLabel

        for ch in range(8):
            name_lbl = QLabel(f"A{ch}")
            name_lbl.setFixedWidth(25)
            val_lbl = QLabel("---")
            val_lbl.setMinimumWidth(60)
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            volt_lbl = QLabel("")
            volt_lbl.setMinimumWidth(50)
            volt_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            adc_grid.addWidget(name_lbl, ch // 4, (ch % 4) * 3)
            adc_grid.addWidget(val_lbl,  ch // 4, (ch % 4) * 3 + 1)
            adc_grid.addWidget(volt_lbl, ch // 4, (ch % 4) * 3 + 2)
            self._adc_labels[ch] = (val_lbl, volt_lbl)

        self._adc_poll_btn = QPushButton("Read All")
        set_btn_icon(self._adc_poll_btn, IC.REFRESH)
        self._adc_poll_btn.clicked.connect(self._poll_adc)
        adc_grid.addWidget(self._adc_poll_btn, 2, 0, 1, 12)
        root.addWidget(adc_box)

        root.addWidget(_hline())

        # ── Status ───────────────────────────────────────────────
        status_box = QGroupBox("Controller Status")
        sl = QHBoxLayout(status_box)
        self._fw_label     = QLabel("Firmware: --")
        self._uptime_label = QLabel("Uptime: --")
        self._led_label    = QLabel("Active LED: None")
        sl.addWidget(self._fw_label)
        sl.addWidget(self._uptime_label)
        sl.addWidget(self._led_label)
        sl.addStretch()
        root.addWidget(status_box)

        root.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)

        # Periodic status poll
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.setInterval(2000)

        self._apply_styles()

    # ---------------------------------------------------------------- #
    #  Empty state (page 0)                                             #
    # ---------------------------------------------------------------- #

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel()
        from ui.icons import make_icon_label
        icon_lbl = make_icon_label(IC.FPGA, 48, PALETTE['textDim'])
        v.addWidget(icon_lbl, alignment=Qt.AlignCenter)

        title = QLabel("Arduino Nano")
        title.setStyleSheet(
            f"font-size: {FONT['title']}pt; font-weight: bold; "
            f"color: {PALETTE['text']};")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        desc = QLabel("LED wavelength selector and general-purpose I/O controller")
        desc.setStyleSheet(f"color: {PALETTE['textDim']};")
        desc.setAlignment(Qt.AlignCenter)
        v.addWidget(desc)

        hint = QLabel(
            "Connect an Arduino Nano in Device Manager to enable controls.")
        hint.setStyleSheet(f"color: {PALETTE['textSub']};")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        v.addWidget(hint)

        btn = QPushButton("Open Device Manager")
        set_btn_icon(btn, IC.SETTINGS)
        btn.setFixedWidth(200)
        btn.clicked.connect(self.open_device_manager.emit)
        v.addWidget(btn, alignment=Qt.AlignCenter)

        return w

    # ---------------------------------------------------------------- #
    #  Connect / disconnect                                             #
    # ---------------------------------------------------------------- #

    def on_device_connected(self):
        """Called when an Arduino GPIO device connects."""
        gpio = app_state.gpio
        if gpio is None:
            return

        # Populate LED channel radios from driver config
        channels = gpio.channels
        for ch in channels:
            radio = QRadioButton(f"{ch.label}  (D{ch.pin})")
            self._led_group.addButton(radio, ch.index)
            self._led_channels_layout.addWidget(radio)
            self._led_radios.append((ch.index, radio))

        self._stack.setCurrentIndex(1)
        self._poll_timer.start()
        self._poll_status()
        log.info("ArduinoTab: device connected, %d LED channels", len(channels))

    def on_device_disconnected(self):
        """Called when the Arduino GPIO device disconnects."""
        self._poll_timer.stop()
        # Remove dynamic channel radios (keep "All Off" at index 0)
        while len(self._led_radios) > 1:
            _, radio = self._led_radios.pop()
            self._led_group.removeButton(radio)
            self._led_channels_layout.removeWidget(radio)
            radio.deleteLater()
        # Reset to empty state
        self._stack.setCurrentIndex(0)

    # ---------------------------------------------------------------- #
    #  LED selection                                                    #
    # ---------------------------------------------------------------- #

    def _on_led_selected(self, button):
        gpio = app_state.gpio
        if gpio is None:
            return
        ch_id = self._led_group.id(button)
        try:
            gpio.select_led(ch_id)
        except Exception as exc:
            log.warning("LED select failed: %s", exc)

    # ---------------------------------------------------------------- #
    #  GPIO toggle                                                      #
    # ---------------------------------------------------------------- #

    def _on_gpio_toggled(self, pin: int, checked: bool):
        gpio = app_state.gpio
        if gpio is None:
            return
        btn = self._gpio_buttons.get(pin)
        try:
            gpio.set_pin(pin, checked)
            if btn:
                btn.setText("HIGH" if checked else "LOW")
                btn.setStyleSheet(
                    f"background: {PALETTE['pass']}; color: #000;"
                    if checked else "")
        except Exception as exc:
            log.warning("GPIO set_pin(%d) failed: %s", pin, exc)

    # ---------------------------------------------------------------- #
    #  ADC poll                                                         #
    # ---------------------------------------------------------------- #

    def _poll_adc(self):
        gpio = app_state.gpio
        if gpio is None:
            return
        for ch in range(8):
            try:
                val = gpio.read_analog(ch)
                volts = val * 5.0 / 1023.0
                val_lbl, volt_lbl = self._adc_labels[ch]
                val_lbl.setText(str(val))
                volt_lbl.setText(f"{volts:.2f} V")
            except Exception:
                pass

    # ---------------------------------------------------------------- #
    #  Status poll                                                      #
    # ---------------------------------------------------------------- #

    def _poll_status(self):
        gpio = app_state.gpio
        if gpio is None:
            return
        try:
            st = gpio.get_status()
            self._fw_label.setText(f"Firmware: {st.firmware_version}")
            uptime_s = st.uptime_ms / 1000.0
            if uptime_s < 60:
                self._uptime_label.setText(f"Uptime: {uptime_s:.0f}s")
            else:
                m, s = divmod(int(uptime_s), 60)
                self._uptime_label.setText(f"Uptime: {m}m {s}s")
            if st.active_led >= 0:
                channels = gpio.channels
                if st.active_led < len(channels):
                    self._led_label.setText(
                        f"Active LED: {channels[st.active_led].label}")
                else:
                    self._led_label.setText(f"Active LED: Ch {st.active_led}")
            else:
                self._led_label.setText("Active LED: None")
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Theming                                                          #
    # ---------------------------------------------------------------- #

    def _apply_styles(self):
        self.setStyleSheet(scaled_qss(f"""
            QGroupBox {{
                font-weight: bold;
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 14px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
            QRadioButton {{
                color: {PALETTE['text']};
                spacing: 6px;
            }}
            QLabel {{
                color: {PALETTE['textDim']};
                font-family: {MONO_FONT};
            }}
            QPushButton {{
                background: {PALETTE['surface']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
                border-radius: 3px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background: {PALETTE['hover']};
            }}
        """))
