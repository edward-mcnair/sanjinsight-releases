"""
hardware/fpga/simulated.py

Simulated FPGA for development and testing without hardware.
Counts frames at the configured frequency and toggles stimulus
state realistically.

Config keys:
    initial_freq_hz:  1000.0
    initial_duty:     0.5
"""

import time
import math
from .base import FpgaDriver, FpgaStatus

import logging
log = logging.getLogger(__name__)


class SimulatedFpga(FpgaDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._freq        = float(cfg.get("initial_freq_hz", 1000.0))
        self._duty        = float(cfg.get("initial_duty",    0.5))
        self._running     = False
        self._frame_count = 0
        self._start_time  = None
        self._sync_locked = False

    def open(self) -> None:
        self._open = True
        log.info("[SIM] FPGA open  (%.0f Hz, duty %.0f%%)", self._freq, self._duty * 100)

    def close(self) -> None:
        self.stop()
        self._open = False

    def start(self) -> None:
        self._running     = True
        self._start_time  = time.time()
        self._sync_locked = True
        log.info("[SIM] FPGA started")

    def stop(self) -> None:
        self._running     = False
        self._sync_locked = False

    def set_frequency(self, hz: float) -> None:
        self._freq = hz

    def set_duty_cycle(self, fraction: float) -> None:
        self._duty = max(0.0, min(1.0, fraction))

    def get_status(self) -> FpgaStatus:
        stimulus_on = False
        if self._running and self._start_time:
            elapsed = time.time() - self._start_time
            # Increment simulated frame count
            self._frame_count = int(elapsed * self._freq)
            # Stimulus is ON during the duty-cycle fraction of each period
            phase = math.fmod(elapsed * self._freq, 1.0)
            stimulus_on = phase < self._duty

        return FpgaStatus(
            running     = self._running,
            frame_count = self._frame_count,
            stimulus_on = stimulus_on,
            freq_hz     = self._freq,
            duty_cycle  = self._duty,
            sync_locked = self._sync_locked,
        )

    def frequency_range(self) -> tuple:
        return (0.1, 100_000.0)
