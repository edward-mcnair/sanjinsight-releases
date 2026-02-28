"""
hardware/fpga/base.py

Abstract base class for FPGA drivers.
The NI 9637 is the current hardware target, but the interface is generic.

The FPGA is responsible for:
  - Generating the stimulus signal (bias current on/off)
  - Precise timing between stimulus and camera trigger
  - Counting frames and reporting sync status
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FpgaStatus:
    """Current FPGA status snapshot."""
    running:       bool  = False
    frame_count:   int   = 0
    stimulus_on:   bool  = False   # current state of stimulus output
    freq_hz:       float = 0.0     # stimulus frequency
    duty_cycle:    float = 0.5     # 0.0 – 1.0
    sync_locked:   bool  = False
    error:         Optional[str] = None


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
