"""
hardware/turret/base.py

Abstract base class for motorized objective turret / nose-piece drivers.

An objective turret rotates to select one of N objective lenses
(e.g. 4×, 10×, 20×, 50×, 100×).  Each objective position has a
unique set of optical properties that affect:

  - Camera field of view (FOV) and pixel size (μm/px)
  - Autofocus Z-search range (different working distances)
  - AI context (objective metadata in context JSON)
  - Diagnostic rules (warn if objective ≠ expected for measurement profile)

The turret driver manages hardware positioning; the objective metadata
(magnification, NA, working distance) is stored in ai/instrument_knowledge.py.

To add a new turret controller:
    1. Create hardware/turret/my_turret.py and subclass ObjectiveTurretDriver
    2. Add it to hardware/turret/factory.py
    3. Set driver: "my_turret" under hardware.turret in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List


# ── Objective specification ───────────────────────────────────────────────────

@dataclass
class ObjectiveSpec:
    """Optical properties of one objective lens position."""
    position:        int    # Turret position index (1-based)
    magnification:   int    # Nominal magnification (e.g. 10, 20, 50, 100)
    numerical_aperture: float  # NA (e.g. 0.25, 0.45, 0.80, 0.95)
    working_dist_mm: float  # Working distance in mm
    label:           str    # Display label (e.g. "10× / 0.25 NA")

    # Per-camera pixel sizes (filled from instrument_knowledge FOV table)
    px_size_acA1920_um: float = 0.0   # μm/px for Basler acA1920-155um
    px_size_acA640_um:  float = 0.0   # μm/px for Basler acA640-750um

    def __str__(self):
        return self.label


# ── Turret status ─────────────────────────────────────────────────────────────

@dataclass
class TurretStatus:
    """Current turret status snapshot."""
    position:        int   = 0       # Current position (1-based; 0 = unknown)
    is_moving:       bool  = False
    n_positions:     int   = 0       # Total positions on this turret
    error:           Optional[str] = None


# ── Abstract driver ───────────────────────────────────────────────────────────

class ObjectiveTurretDriver(ABC):
    """
    Abstract objective turret driver.

    Lifecycle:
        driver = SomeTurret(config_dict)
        driver.connect()
        driver.move_to(position=2)           # rotate to position 2
        spec = driver.get_objective(position=2)
        status = driver.get_status()
        driver.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg        = cfg
        self._connected  = False
        self._objectives: List[ObjectiveSpec] = []   # Populated by subclass or config

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def connect(self) -> None:
        """Open connection to turret controller. Raises RuntimeError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection and release resources."""

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def move_to(self, position: int) -> None:
        """
        Rotate turret to the given position (1-based).
        Blocks until the turret reaches the requested position.
        Raises ValueError for out-of-range positions.
        """

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def get_status(self) -> TurretStatus:
        """Return current TurretStatus snapshot."""

    @abstractmethod
    def get_position(self) -> int:
        """Return current turret position (1-based; 0 if unknown)."""

    # ---------------------------------------------------------------- #
    #  Objective metadata                                               #
    # ---------------------------------------------------------------- #

    def get_objective(self, position: Optional[int] = None) -> Optional[ObjectiveSpec]:
        """
        Return ObjectiveSpec for the given position (or current position).
        Returns None if no objective registered for that slot.
        """
        pos = position if position is not None else self.get_position()
        for obj in self._objectives:
            if obj.position == pos:
                return obj
        return None

    def list_objectives(self) -> List[ObjectiveSpec]:
        """Return all configured objective specifications, sorted by position."""
        return sorted(self._objectives, key=lambda o: o.position)

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    @property
    def is_connected(self) -> bool:
        return self._connected

    def n_positions(self) -> int:
        """Number of turret positions (objective slots)."""
        return len(self._objectives) if self._objectives else 6  # Olympus default

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"connected={self._connected}>")
