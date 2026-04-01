"""
hardware/arduino/base.py

Abstract base class for Arduino-based GPIO / LED wavelength selector.

The Arduino Nano (ATmega328P) serves as a general-purpose I/O controller
in Microsanj thermoreflectance systems.  Primary functions:

  1. **LED wavelength selection** — switch between multiple illumination
     wavelengths (e.g. 470 nm, 530 nm, 590 nm, 625 nm) by driving
     individual enable pins connected to the LED driver board.
  2. **Digital GPIO** — read/write individual pins for auxiliary control
     (shutters, triggers, indicator LEDs, interlock signals).
  3. **Analog input (ADC)** — read 10-bit analog values from A0–A7
     for monitoring photodiode feedback, temperature sensors, or
     other analog signals.

Communication is via USB-serial (CH340 on most Nano clones) at
115200 baud using a simple line-based ASCII protocol.

To add a new Arduino-class controller:
  1. Create hardware/arduino/my_board.py and subclass ArduinoDriver
  2. Add it to hardware/arduino/factory.py
  3. Set driver: "my_board" under hardware.arduino in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ------------------------------------------------------------------ #
#  LED channel definitions                                             #
# ------------------------------------------------------------------ #

@dataclass
class LedChannel:
    """One selectable LED wavelength channel."""
    index:         int            # 0-based channel number
    wavelength_nm: int            # nominal wavelength (nm)
    label:         str            # display label (e.g. "470 nm Blue")
    pin:           int            # Arduino digital pin number
    enabled:       bool = False   # True when this channel is active


# Pre-defined channels for the standard Microsanj LED board
DEFAULT_LED_CHANNELS: List[LedChannel] = [
    LedChannel(index=0, wavelength_nm=470, label="470 nm Blue",   pin=2),
    LedChannel(index=1, wavelength_nm=530, label="530 nm Green",  pin=3),
    LedChannel(index=2, wavelength_nm=590, label="590 nm Amber",  pin=4),
    LedChannel(index=3, wavelength_nm=625, label="625 nm Red",    pin=5),
]


# ------------------------------------------------------------------ #
#  Status dataclass                                                    #
# ------------------------------------------------------------------ #

@dataclass
class ArduinoStatus:
    """Snapshot of the Arduino controller state."""
    firmware_version: str          = ""        # e.g. "SanjIO 1.0"
    active_led:       int          = -1        # active LED channel index (-1 = none)
    digital_pins:     Dict[int, bool]  = field(default_factory=dict)
    analog_values:    Dict[int, int]   = field(default_factory=dict)  # pin → 0..1023
    uptime_ms:        int          = 0
    error:            Optional[str] = None


# ------------------------------------------------------------------ #
#  Abstract driver                                                     #
# ------------------------------------------------------------------ #

class ArduinoDriver(ABC):
    """
    Abstract Arduino GPIO / LED controller.

    Lifecycle::

        driver = SomeArduino(config_dict)
        driver.connect()
        driver.select_led(0)             # activate 470 nm
        driver.set_pin(8, True)          # digital output HIGH
        val = driver.read_analog(0)      # read A0
        status = driver.get_status()
        driver.select_led(-1)            # all LEDs off
        driver.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._connected = False
        self._channels: List[LedChannel] = list(DEFAULT_LED_CHANNELS)

        # Allow config to override default channel map
        ch_cfg = cfg.get("led_channels")
        if ch_cfg and isinstance(ch_cfg, list):
            self._channels = [
                LedChannel(
                    index=i,
                    wavelength_nm=int(ch.get("wavelength_nm", 0)),
                    label=ch.get("label", f"Ch {i}"),
                    pin=int(ch.get("pin", 2 + i)),
                )
                for i, ch in enumerate(ch_cfg)
            ]

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open serial connection to Arduino. Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Turn off all outputs and close connection."""

    # ---------------------------------------------------------------- #
    #  LED wavelength selection                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def select_led(self, channel: int) -> None:
        """Activate a single LED channel (0-based index).

        Pass -1 to turn all LEDs off.  Only one LED is active at a time —
        selecting a new channel automatically deactivates the previous one.
        """

    @abstractmethod
    def get_active_led(self) -> int:
        """Return the currently active LED channel index, or -1 if none."""

    # ---------------------------------------------------------------- #
    #  Digital GPIO                                                     #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def set_pin(self, pin: int, state: bool) -> None:
        """Set a digital output pin HIGH (True) or LOW (False)."""

    @abstractmethod
    def get_pin(self, pin: int) -> bool:
        """Read the state of a digital pin (True = HIGH)."""

    # ---------------------------------------------------------------- #
    #  Analog input (ADC)                                               #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def read_analog(self, channel: int) -> int:
        """Read a 10-bit analog value (0–1023) from an analog input pin.

        channel: 0–7 maps to Arduino pins A0–A7.
        """

    # ---------------------------------------------------------------- #
    #  Status                                                           #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> ArduinoStatus:
        """Return current ArduinoStatus snapshot."""

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def channels(self) -> List[LedChannel]:
        """Return the list of configured LED channels."""
        return self._channels

    @classmethod
    def preflight(cls) -> tuple:
        """Check whether dependencies (pyserial) are available.

        Returns (ok: bool, issues: list[str]).
        """
        try:
            import serial  # noqa: F401
            return (True, [])
        except ImportError:
            return (False, [
                "pyserial is not installed.\n"
                "Fix: pip install pyserial"
            ])

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected}>")
