"""
hardware/tec/simulated.py

Simulated TEC controller for development and testing without hardware.
Temperature moves realistically toward the setpoint with thermal lag,
overshoot, and noise — behaves like a real PID-controlled TEC.

Config keys:
    initial_temp:  25.0
    noise:         0.02    °C of simulated sensor noise
"""

import time
import math
import random
from .base import TecDriver, TecStatus

import logging
log = logging.getLogger(__name__)


class SimulatedTec(TecDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._actual      = float(cfg.get("initial_temp", 25.0))
        self._target      = float(cfg.get("initial_temp", 25.0))
        self._noise       = float(cfg.get("noise", 0.02))
        self._enabled     = False
        self._current     = 0.0
        self._voltage     = 0.0
        self._last_update = time.time()

    def connect(self) -> None:
        self._connected = True
        print(f"[SIM] TEC connected (initial temp: {self._actual:.1f}°C)")

    def disconnect(self) -> None:
        self._connected = False

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._current = 0.0
        self._voltage = 0.0

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c

    def _update(self):
        """Simulate thermal dynamics with lag and overshoot."""
        now = time.time()
        dt  = now - self._last_update
        self._last_update = now

        if not self._enabled:
            # Drift slowly back to ambient (25°C) when disabled
            self._actual += (25.0 - self._actual) * dt * 0.05
            return

        # Simple first-order thermal model with PID-like behavior
        error  = self._target - self._actual
        # Time constant: ~30 seconds to reach setpoint
        rate   = error * (1.0 - math.exp(-dt / 30.0)) * 3.0
        self._actual += rate

        # Simulated output current proportional to error (capped at 3A)
        self._current = max(-3.0, min(3.0, error * 0.3))
        self._voltage = self._current * 3.2   # ~3.2V per amp

    def get_status(self) -> TecStatus:
        self._update()
        noise  = random.gauss(0, self._noise)
        actual = self._actual + noise
        stable = abs(actual - self._target) <= self.stability_tolerance()
        return TecStatus(
            actual_temp    = round(actual, 3),
            target_temp    = self._target,
            output_current = round(self._current, 3),
            output_voltage = round(self._voltage, 3),
            output_power   = round(abs(self._current * self._voltage), 3),
            enabled        = self._enabled,
            stable         = stable,
        )

    def temp_range(self) -> tuple:
        return (-40.0, 150.0)
