"""
hardware/turret/simulated.py

Simulated objective turret for development and testing without hardware.
"""

import logging
import time
from .base import ObjectiveTurretDriver, ObjectiveSpec, TurretStatus

log = logging.getLogger(__name__)

_SIM_OBJECTIVES = [
    ObjectiveSpec(position=1, magnification=4,   numerical_aperture=0.10,
                  working_dist_mm=18.5, label=" 4× / 0.10 NA"),
    ObjectiveSpec(position=2, magnification=10,  numerical_aperture=0.25,
                  working_dist_mm=10.6, label="10× / 0.25 NA"),
    ObjectiveSpec(position=3, magnification=20,  numerical_aperture=0.45,
                  working_dist_mm= 8.2, label="20× / 0.45 NA"),
    ObjectiveSpec(position=4, magnification=50,  numerical_aperture=0.80,
                  working_dist_mm= 0.37,label="50× / 0.80 NA"),
    ObjectiveSpec(position=5, magnification=100, numerical_aperture=0.95,
                  working_dist_mm= 0.21,label="100× / 0.95 NA"),
]


class SimulatedTurret(ObjectiveTurretDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._objectives = list(_SIM_OBJECTIVES)
        self._cur_pos    = 2   # Start at 10× by default
        self._is_moving  = False

    def connect(self) -> None:
        self._connected = True
        log.info("[SIM] Turret connected  (positions: %d)", len(self._objectives))

    def disconnect(self) -> None:
        self._connected = False

    def move_to(self, position: int) -> None:
        if position < 1 or position > len(self._objectives):
            raise ValueError(f"Turret position {position} out of range.")
        self._is_moving = True
        time.sleep(0.3)   # simulate rotation time
        self._cur_pos   = position
        self._is_moving = False
        log.info("[SIM] Turret → position %d  (%s)",
                 position,
                 getattr(self.get_objective(position), 'label', '?'))

    def get_status(self) -> TurretStatus:
        return TurretStatus(
            position    = self._cur_pos,
            is_moving   = self._is_moving,
            n_positions = len(self._objectives),
        )

    def get_position(self) -> int:
        return self._cur_pos

    def n_positions(self) -> int:
        return len(self._objectives)
