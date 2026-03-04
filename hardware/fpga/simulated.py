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
from .base import FpgaDriver, FpgaStatus, FpgaTriggerMode

import logging
log = logging.getLogger(__name__)


class SimulatedFpga(FpgaDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._freq           = float(cfg.get("initial_freq_hz", 1000.0))
        self._duty           = float(cfg.get("initial_duty",    0.5))
        self._running        = False
        self._frame_count    = 0
        self._start_time     = None
        self._sync_locked    = False
        self._trigger_mode   = FpgaTriggerMode.CONTINUOUS
        self._trigger_armed  = False
        self._pulse_dur_us   = 1000.0   # μs
        self._pulse_fire_t   = None     # time.time() when last arm fired

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

    def set_trigger_mode(self, mode: FpgaTriggerMode) -> None:
        self._trigger_mode  = mode
        self._trigger_armed = False
        log.info("[SIM] FPGA trigger mode → %s", mode)

    def arm_trigger(self) -> None:
        if self._trigger_mode != FpgaTriggerMode.SINGLE_SHOT:
            raise RuntimeError("arm_trigger() requires SINGLE_SHOT mode.")
        self._trigger_armed = True
        self._pulse_fire_t  = time.time()
        log.info("[SIM] FPGA trigger armed (pulse %.0f μs)", self._pulse_dur_us)

    def set_pulse_duration(self, duration_us: float) -> None:
        self._pulse_dur_us = max(1.0, duration_us)

    def supports_trigger_mode(self) -> bool:
        return True

    def get_status(self) -> FpgaStatus:
        stimulus_on = False
        now         = time.time()

        if self._trigger_mode == FpgaTriggerMode.SINGLE_SHOT:
            if self._trigger_armed and self._pulse_fire_t is not None:
                elapsed_us = (now - self._pulse_fire_t) * 1e6
                if elapsed_us < self._pulse_dur_us:
                    stimulus_on = True
                else:
                    self._trigger_armed = False   # pulse complete
        elif self._running and self._start_time:
            elapsed = now - self._start_time
            # Increment simulated frame count
            self._frame_count = int(elapsed * self._freq)
            # Stimulus is ON during the duty-cycle fraction of each period
            phase = math.fmod(elapsed * self._freq, 1.0)
            stimulus_on = phase < self._duty

        return FpgaStatus(
            running        = self._running,
            frame_count    = self._frame_count,
            stimulus_on    = stimulus_on,
            freq_hz        = self._freq,
            duty_cycle     = self._duty,
            sync_locked    = self._sync_locked,
            trigger_mode   = self._trigger_mode,
            trigger_armed  = self._trigger_armed,
        )

    def frequency_range(self) -> tuple:
        return (0.1, 100_000.0)
