"""
hardware/stage/base.py

Abstract base class for all positioning stage drivers.

A stage moves the sample (or objective) in XYZ space.
  X, Y  — lateral scan across the device under test
  Z      — focus axis (objective distance to sample)

Units are always micrometers (μm) internally.
Drivers convert to/from their native units (steps, mm, counts, etc.).

To add a new stage:
    1. Create hardware/stage/my_stage.py and subclass StageDriver
    2. Add it to hardware/stage/factory.py
    3. Set driver: "my_stage" under hardware.stage in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class StagePosition:
    """Current stage position in micrometers."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __str__(self):
        return f"X={self.x:.3f}  Y={self.y:.3f}  Z={self.z:.3f}  μm"


@dataclass
class StageStatus:
    """Current stage status snapshot."""
    position:   StagePosition = None
    moving:     bool          = False
    homed:      bool          = False
    x_limit:    bool          = False   # True if at a travel limit
    y_limit:    bool          = False
    z_limit:    bool          = False
    error:      Optional[str] = None

    def __post_init__(self):
        if self.position is None:
            self.position = StagePosition()


class StageDriver(ABC):
    """
    Abstract positioning stage driver.

    Lifecycle:
        driver = SomeStage(config_dict)
        driver.connect()
        driver.home()                       # find reference position
        driver.move_to(x=100, y=200, z=50)  # absolute move in μm
        driver.move_by(x=10)                # relative move in μm
        status = driver.get_status()
        driver.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._connected = False
        self._pos       = StagePosition()

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open connection to stage controller. Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Stop motion and close connection."""

    # ---------------------------------------------------------------- #
    #  Motion                                                           #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def home(self, axes: str = "xyz") -> None:
        """
        Home specified axes to find reference position.
        axes: any combination of "x", "y", "z"  e.g. "xy" or "xyz"
        Blocks until homing is complete.
        """

    @abstractmethod
    def move_to(self,
                x: Optional[float] = None,
                y: Optional[float] = None,
                z: Optional[float] = None,
                speed: Optional[float] = None,
                wait: bool = True) -> None:
        """
        Move to absolute position in μm.
        Pass only the axes you want to move — others stay put.
        speed: μm/s (None = use default speed)
        wait:  if True, block until motion completes
        """

    @abstractmethod
    def move_by(self,
                x: float = 0.0,
                y: float = 0.0,
                z: float = 0.0,
                speed: Optional[float] = None,
                wait: bool = True) -> None:
        """Move by a relative offset in μm."""

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop all motion."""

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> StageStatus:
        """Return current StageStatus snapshot."""

    @property
    def position(self) -> StagePosition:
        return self._pos

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    def travel_range(self) -> dict:
        """
        Return travel range per axis in μm.
        Override with actual instrument limits.
        """
        return {
            "x": (-50_000.0, 50_000.0),
            "y": (-50_000.0, 50_000.0),
            "z": (     0.0,  25_000.0),
        }

    def default_speed(self) -> dict:
        """Default speed per axis in μm/s."""
        return {"x": 1000.0, "y": 1000.0, "z": 100.0}

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected} pos={self._pos}>")
