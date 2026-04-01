"""
hardware/arduino/simulated.py

Simulated Arduino Nano for development and testing without hardware.
Responds realistically — LED selection, GPIO, and ADC readback with
small random noise on analog channels.

Config keys:
    noise:  0.5    ADC noise level (±LSBs)
"""

import random
import logging
import time

from .base import ArduinoDriver, ArduinoStatus

log = logging.getLogger(__name__)


class SimulatedArduino(ArduinoDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._active_led: int = -1
        self._pin_state: dict = {}      # pin → bool
        self._noise: float = float(cfg.get("noise", 0.5))
        self._start_time: float = 0.0

    def connect(self) -> None:
        self._connected = True
        self._start_time = time.time()
        log.info("[SIM] Arduino Nano connected  "
                 "(channels=%d)", len(self._channels))

    def disconnect(self) -> None:
        self._active_led = -1
        self._pin_state.clear()
        self._connected = False

    # ── LED ──────────────────────────────────────────────────────────

    def select_led(self, channel: int) -> None:
        if channel < -1 or channel >= len(self._channels):
            raise ValueError(
                f"LED channel {channel} out of range "
                f"(-1..{len(self._channels) - 1})")
        self._active_led = channel
        for ch in self._channels:
            ch.enabled = (ch.index == channel)

    def get_active_led(self) -> int:
        return self._active_led

    # ── Digital GPIO ────────────────────────────────────────────────

    def set_pin(self, pin: int, state: bool) -> None:
        self._pin_state[pin] = state

    def get_pin(self, pin: int) -> bool:
        return self._pin_state.get(pin, False)

    # ── Analog input ────────────────────────────────────────────────

    def read_analog(self, channel: int) -> int:
        if channel < 0 or channel > 7:
            raise ValueError(f"Analog channel {channel} out of range (0–7)")
        # Simulate different baseline values per channel
        base = {
            0: 512,   # ~2.5 V (photodiode midpoint)
            1: 200,   # ~1.0 V
            2: 800,   # ~3.9 V
            3: 100,
            4: 0, 5: 0, 6: 0, 7: 0,
        }.get(channel, 0)
        noise = round(random.gauss(0, self._noise))
        return max(0, min(1023, base + noise))

    # ── Status ──────────────────────────────────────────────────────

    def get_status(self) -> ArduinoStatus:
        uptime = int((time.time() - self._start_time) * 1000)
        return ArduinoStatus(
            firmware_version="SanjIO 1.0 (SIM)",
            active_led=self._active_led,
            digital_pins=dict(self._pin_state),
            analog_values={ch: self.read_analog(ch) for ch in range(4)},
            uptime_ms=uptime,
        )
