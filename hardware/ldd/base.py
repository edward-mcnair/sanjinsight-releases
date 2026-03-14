"""
hardware/ldd/base.py

Abstract base class for all Laser Diode Driver (LDD) interfaces.

The LDD controls the LED or pulsed-laser illumination source used in
Microsanj thermoreflectance systems.  In transient and movie-mode
acquisitions the FPGA drives the pulse pin directly (Pulse_Source = HW Pin);
the LDD driver is used to set the CW bias current, enable/disable the output,
and monitor diode temperature during operation.

To add a new LDD controller:
  1. Create hardware/ldd/my_ldd.py and subclass LddDriver
  2. Add it to hardware/ldd/factory.py
  3. Set driver: "my_ldd" under the ldd section in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ai.instrument_knowledge import (
    LDD_MAX_CURRENT_A,
    LDD_DIODE_MIN_C,
    LDD_DIODE_MAX_C,
)


@dataclass
class LddStatus:
    """Current status snapshot from the laser diode driver."""
    actual_current_a:  float = 0.0    # A   — measured output current
    actual_voltage_v:  float = 0.0    # V   — measured output voltage
    diode_temp_c:      float = 25.0   # °C  — laser diode NTC temperature
    enabled:           bool  = False  # True when LED/laser output is active
    mode:              str   = "cw"   # "cw" | "pulsed" | "hw_trigger"
    error:             Optional[str] = None


class LddDriver(ABC):
    """
    Abstract laser diode / LED driver.

    Lifecycle::

        driver = SomeLdd(config_dict)
        driver.connect()
        driver.set_current(1.5)
        driver.enable()
        status = driver.get_status()
        driver.disable()
        driver.disconnect()

    When the FPGA is driving the pulse pin (hw_trigger mode), only
    set_current() and enable() are needed from user code.  The
    actual pulse timing is controlled by the FPGA — not by this driver.
    """

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._connected = False

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open connection to the LDD controller.  Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection and release resources."""

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def enable(self) -> None:
        """Activate LED/laser current output."""

    @abstractmethod
    def disable(self) -> None:
        """De-activate LED/laser current output."""

    @abstractmethod
    def set_current(self, current_a: float) -> None:
        """
        Set CW LED/laser drive current in Amperes.

        current_a is silently clamped to [0, LDD_MAX_CURRENT_A].
        The physical ramp rate is limited by the controller's SlopeLimit.
        """

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> LddStatus:
        """Return a current LddStatus snapshot (non-blocking)."""

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    def current_range(self) -> tuple:
        """Return (min_a, max_a) from instrument_knowledge constants."""
        return (0.0, LDD_MAX_CURRENT_A)

    def diode_temp_range(self) -> tuple:
        """Return (min_c, max_c) safe operating range for the laser diode."""
        return (LDD_DIODE_MIN_C, LDD_DIODE_MAX_C)

    @classmethod
    def preflight(cls) -> tuple:
        """
        Check whether this driver's dependencies are satisfied before
        attempting to connect hardware.

        Returns (ok: bool, issues: list[str]).
        Subclasses should override this to verify required Python packages
        are importable.  The default always returns (True, []).
        """
        return (True, [])

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected}>")
