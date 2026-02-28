"""
hardware/bias/simulated.py

Simulated bias source for development and testing without hardware.
Responds realistically — voltage/current readback reflects setpoint
with small noise, compliance limiting, and output on/off state.

Config keys:
    mode:        "voltage"
    level:       0.0
    compliance:  0.1
    noise:       0.001    noise level on readback (V or A)
"""

import random
from .base import BiasDriver, BiasStatus

import logging
log = logging.getLogger(__name__)


class SimulatedBias(BiasDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._output_on = False
        self._noise     = float(cfg.get("noise", 0.001))

    def connect(self) -> None:
        self._connected = True
        log.info(f"[SIM] Bias source connected  "
              f"(mode={self._mode}, level={self._level})")

    def disconnect(self) -> None:
        self.disable()
        self._connected = False

    def enable(self) -> None:
        self._output_on = True

    def disable(self) -> None:
        self._output_on = False

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_level(self, value: float) -> None:
        self._level = value

    def set_compliance(self, value: float) -> None:
        self._compliance = value

    def get_status(self) -> BiasStatus:
        if not self._output_on:
            return BiasStatus(
                output_on      = False,
                mode           = self._mode,
                setpoint       = self._level,
                actual_voltage = 0.0,
                actual_current = 0.0,
                actual_power   = 0.0,
                compliance     = self._compliance,
            )

        noise = random.gauss(0, self._noise)

        if self._mode == "voltage":
            v = self._level + noise
            # Simulate current draw — compliance limited
            i = min(self._level / max(abs(self._level), 1e-3) * 0.05,
                    self._compliance) + random.gauss(0, self._noise * 0.1)
        else:
            i = self._level + noise
            v = min(self._level * 10.0, self._compliance) + \
                random.gauss(0, self._noise * 0.1)

        return BiasStatus(
            output_on      = True,
            mode           = self._mode,
            setpoint       = self._level,
            actual_voltage = round(v, 6),
            actual_current = round(i, 6),
            actual_power   = round(abs(v * i), 6),
            compliance     = self._compliance,
        )

    def voltage_range(self) -> tuple:
        return (-200.0, 200.0)

    def current_range(self) -> tuple:
        return (-1.0, 1.0)
