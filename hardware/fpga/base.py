"""
hardware/fpga/base.py

Abstract base class for FPGA drivers.
The NI 9637 is the current hardware target, but the interface is generic.

The FPGA is responsible for:
  - Generating the stimulus signal (bias current on/off)
  - Precise timing between stimulus and camera trigger
  - Counting frames and reporting sync status

Trigger modes (used by transient acquisition)
---------------------------------------------
  CONTINUOUS  — default; square-wave output at set frequency/duty-cycle
  SINGLE_SHOT — single pulse on arm_trigger(); camera captures at fixed delays
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FpgaTriggerMode(str, Enum):
    """FPGA output / trigger mode."""
    CONTINUOUS  = "continuous"    # Normal lock-in operation (default)
    SINGLE_SHOT = "single_shot"   # One pulse per arm_trigger() call (transient mode)


@dataclass
class FpgaStatus:
    """Current FPGA status snapshot."""
    running:        bool  = False
    frame_count:    int   = 0
    stimulus_on:    bool  = False   # current state of stimulus output
    freq_hz:        float = 0.0     # stimulus frequency
    duty_cycle:     float = 0.5     # 0.0 – 1.0
    sync_locked:    bool  = False
    trigger_mode:   str   = FpgaTriggerMode.CONTINUOUS  # current trigger mode
    trigger_armed:  bool  = False   # True between arm_trigger() and pulse completion
    error:          Optional[str] = None


class FpgaDriver(ABC):
    """
    Abstract FPGA driver.

    Lifecycle:
        driver = SomeFpga(config_dict)
        driver.open()
        driver.set_frequency(1000.0)
        driver.set_duty_cycle(0.5)
        driver.start()
        status = driver.get_status()
        driver.stop()
        driver.close()
    """

    def __init__(self, cfg: dict):
        self._cfg  = cfg
        self._open = False

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def open(self) -> None:
        """Load bitfile and open FPGA session. Raises RuntimeError on failure."""

    @abstractmethod
    def close(self) -> None:
        """Stop and close FPGA session."""

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def start(self) -> None:
        """Start stimulus output."""

    @abstractmethod
    def stop(self) -> None:
        """Stop stimulus output."""

    @abstractmethod
    def set_frequency(self, hz: float) -> None:
        """Set stimulus frequency in Hz."""

    @abstractmethod
    def set_duty_cycle(self, fraction: float) -> None:
        """Set duty cycle 0.0–1.0 (0.5 = 50%)."""

    def set_stimulus(self, on: bool) -> None:
        """
        Manually force stimulus on or off.
        Default: no-op. Override if hardware supports it.
        """
        pass

    # ---------------------------------------------------------------- #
    #  Trigger / transient mode (optional — not abstract)              #
    # ---------------------------------------------------------------- #

    def set_trigger_mode(self, mode: FpgaTriggerMode) -> None:
        """
        Switch between CONTINUOUS (lock-in) and SINGLE_SHOT (transient) mode.

        In SINGLE_SHOT mode the FPGA suspends its continuous output and waits
        for arm_trigger().  Each call to arm_trigger() fires exactly one pulse
        of the configured duration, then halts.

        Default implementation raises NotImplementedError — concrete drivers
        that do not support triggered mode can leave this as-is; the transient
        pipeline will check and warn the user accordingly.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support trigger mode switching.")

    def arm_trigger(self) -> None:
        """
        Arm the FPGA for a single-shot trigger pulse.

        In SINGLE_SHOT mode: the FPGA fires one pulse of the configured
        duration as soon as the trigger input is asserted (or immediately
        if internal trigger is selected).  Sets FpgaStatus.trigger_armed = True
        until the pulse completes.

        Default: raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support arm_trigger().")

    def set_pulse_duration(self, duration_us: float) -> None:
        """
        Set the single-shot pulse duration in microseconds.
        Only relevant in SINGLE_SHOT trigger mode.
        Default: raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support set_pulse_duration().")

    def supports_trigger_mode(self) -> bool:
        """Return True if this driver implements set_trigger_mode()/arm_trigger()."""
        return False

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> FpgaStatus:
        """Return current FpgaStatus snapshot."""

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_open(self) -> bool:
        return self._open

    def frequency_range(self) -> tuple:
        """Return (min_hz, max_hz)."""
        return (0.1, 100_000.0)

    def __repr__(self):
        return f"<{self.__class__.__name__} open={self._open}>"
