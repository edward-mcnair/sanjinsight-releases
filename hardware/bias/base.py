"""
hardware/bias/base.py

Abstract base class for all bias source drivers.

A bias source applies an electrical stimulus to the device under test (DUT).
This is what creates the "hot" condition in a thermoreflectance measurement —
the DUT heats up when bias is applied, and the camera captures the resulting
change in reflectance.

Supported modes:
    DC      — constant voltage or current
    Pulse   — single pulse of defined width
    Square  — repeating square wave (on/off at set frequency)

The bias source is intentionally decoupled from the FPGA trigger.
The FPGA handles camera sync timing; the bias source handles the
electrical stimulus. They are coordinated by the acquisition pipeline.

To add a new bias source:
    1. Create hardware/bias/my_source.py and subclass BiasDriver
    2. Add it to hardware/bias/factory.py
    3. Set driver: "my_source" under hardware.bias in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum, auto


class BiasMode(Enum):
    VOLTAGE = auto()    # voltage source, current compliance
    CURRENT = auto()    # current source, voltage compliance


@dataclass
class BiasStatus:
    """Current bias source status snapshot."""
    output_on:       bool  = False
    mode:            str   = "voltage"   # "voltage" or "current"
    setpoint:        float = 0.0         # V or A depending on mode
    actual_voltage:  float = 0.0         # V  (measured)
    actual_current:  float = 0.0         # A  (measured)
    actual_power:    float = 0.0         # W
    compliance:      float = 0.0         # current limit (A) or voltage limit (V)
    error:           Optional[str] = None


class BiasDriver(ABC):
    """
    Abstract bias source driver.

    Lifecycle:
        driver = SomeBias(config_dict)
        driver.connect()
        driver.set_mode("voltage")
        driver.set_level(3.3)           # 3.3 V
        driver.set_compliance(0.1)      # 100 mA current limit
        driver.enable()                 # output ON → DUT is biased (hot)
        status = driver.get_status()
        driver.disable()               # output OFF → DUT unbiased (cold)
        driver.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._connected = False
        self._mode      = cfg.get("mode", "voltage")
        self._level     = float(cfg.get("level", 0.0))
        self._compliance = float(cfg.get("compliance", 0.1))

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open connection to bias source. Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Turn off output and close connection."""

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def enable(self) -> None:
        """Turn output ON — DUT is now biased."""

    @abstractmethod
    def disable(self) -> None:
        """Turn output OFF — DUT is unbiased."""

    @abstractmethod
    def set_mode(self, mode: str) -> None:
        """Set source mode: "voltage" or "current"."""

    @abstractmethod
    def set_level(self, value: float) -> None:
        """Set output level. Volts if mode=voltage, Amps if mode=current."""

    @abstractmethod
    def set_compliance(self, value: float) -> None:
        """
        Set compliance limit.
        Current limit (A) when in voltage mode.
        Voltage limit (V) when in current mode.
        """

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> BiasStatus:
        """Return current BiasStatus snapshot including measured V and I."""

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    def voltage_range(self) -> tuple:
        """Return (min_v, max_v). Override for instrument limits."""
        return (-200.0, 200.0)

    def current_range(self) -> tuple:
        """Return (min_a, max_a). Override for instrument limits."""
        return (-1.0, 1.0)

    def compliance_range(self) -> tuple:
        """Return (min, max) for the compliance limit."""
        return (1e-6, 1.0)

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected} mode={self._mode}>")
