"""
hardware/tec/base.py

Abstract base class for all TEC (Thermoelectric Cooler) drivers.
The application only ever calls this interface — never driver-specific code.

To add a new TEC controller:
  1. Create hardware/tec/my_tec.py and subclass TecDriver
  2. Add it to hardware/tec/factory.py
  3. Set driver: "my_tec" under the tec section in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TecStatus:
    """Current status snapshot from the TEC controller."""
    actual_temp:    float = 0.0     # °C  — measured object temperature
    target_temp:    float = 0.0     # °C  — setpoint
    output_current: float = 0.0     # A
    output_voltage: float = 0.0     # V
    output_power:   float = 0.0     # W  (current × voltage)
    enabled:        bool  = False   # is the controller actively driving?
    stable:         bool  = False   # is temp within tolerance of setpoint?
    error:          Optional[str] = None


class TecDriver(ABC):
    """
    Abstract TEC driver.

    Lifecycle:
        driver = SomeTec(config_dict)
        driver.connect()
        driver.set_target(25.0)
        driver.enable()
        status = driver.get_status()
        driver.disable()
        driver.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._connected = False

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open serial connection. Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close serial connection and release resources."""

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def enable(self) -> None:
        """Start TEC output (begin driving temperature toward setpoint)."""

    @abstractmethod
    def disable(self) -> None:
        """Stop TEC output (turn off current)."""

    @abstractmethod
    def set_target(self, temperature_c: float) -> None:
        """Set the target temperature in °C."""

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> TecStatus:
        """Return a current TecStatus snapshot."""

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    def temp_range(self) -> tuple:
        """Return (min_c, max_c). Override for tighter limits."""
        return (-40.0, 150.0)

    def stability_tolerance(self) -> float:
        """°C within which temperature is considered stable."""
        return 0.1

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected}>")
