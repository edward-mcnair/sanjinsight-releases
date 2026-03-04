"""
hardware/ldd/simulated.py

Simulated LDD driver for development and testing without real hardware.

Behaves like a Meerstetter LDD-1121 but all values are generated
in software.  Useful for running the full UI without hardware attached.
"""

import time
import math
import logging
from .base import LddDriver, LddStatus
from ai.instrument_knowledge import LDD_MAX_CURRENT_A

log = logging.getLogger(__name__)


class SimulatedLdd(LddDriver):
    """
    Simulated laser diode driver.

    Simulates:
      - Smooth current ramp (slew rate ≈ 0.2 A per call to get_status)
      - Stable diode temperature: 25 °C + 3 °C × (current / max_current)
      - enable() / disable() with ~50 ms settle
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._target_a   = 0.0
        self._actual_a   = 0.0
        self._enabled    = False
        self._t_enable   = 0.0

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        self._connected = True
        log.info("SimulatedLdd connected.")

    def disconnect(self) -> None:
        self._connected = False
        log.info("SimulatedLdd disconnected.")

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    def enable(self) -> None:
        self._enabled  = True
        self._t_enable = time.time()

    def disable(self) -> None:
        self._enabled = False

    def set_current(self, current_a: float) -> None:
        self._target_a = max(0.0, min(current_a, LDD_MAX_CURRENT_A))

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> LddStatus:
        # Simulate slew toward target at ≈ 0.2 A per poll
        if self._enabled:
            diff = self._target_a - self._actual_a
            slew = min(abs(diff), 0.2)
            self._actual_a += math.copysign(slew, diff)
        else:
            self._actual_a = max(0.0, self._actual_a - 0.2)

        # Diode warms slightly with current
        base_t = 25.0
        load_t = 3.0 * (self._actual_a / max(LDD_MAX_CURRENT_A, 1e-9))
        diode_t = base_t + load_t + 0.05 * math.sin(time.time() * 0.3)

        return LddStatus(
            actual_current_a = round(self._actual_a, 3),
            actual_voltage_v = round(self._actual_a * 2.2, 3),  # ≈ 2.2 V/A forward drop
            diode_temp_c     = round(diode_t, 2),
            enabled          = self._enabled,
            mode             = "hw_trigger" if self._enabled else "cw",
        )
