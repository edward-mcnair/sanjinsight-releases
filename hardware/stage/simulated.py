"""
hardware/stage/simulated.py

Simulated XYZ stage for development and testing without hardware.
Moves at realistic speed with linear interpolation so the UI
shows smooth position changes during a move.

Config keys:
    speed_xy:   1000.0   μm/s lateral speed
    speed_z:    100.0    μm/s focus speed
    noise:      0.05     position readback noise in μm
"""

import time
import threading
import random
from .base import StageDriver, StageStatus, StagePosition

import logging
log = logging.getLogger(__name__)


class SimulatedStage(StageDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._speed_xy  = float(cfg.get("speed_xy", 1000.0))
        self._speed_z   = float(cfg.get("speed_z",  100.0))
        self._noise     = float(cfg.get("noise",    0.05))
        self._target    = StagePosition(0.0, 0.0, 0.0)
        self._moving    = False
        self._homed     = False
        self._lock      = threading.Lock()

    def connect(self) -> None:
        self._connected = True
        print(f"[SIM] Stage connected  "
              f"(XY {self._speed_xy:.0f}μm/s, Z {self._speed_z:.0f}μm/s)")

    def disconnect(self) -> None:
        self.stop()
        self._connected = False

    def home(self, axes: str = "xyz") -> None:
        self._moving = True
        self.move_to(
            x=0.0 if "x" in axes else None,
            y=0.0 if "y" in axes else None,
            z=0.0 if "z" in axes else None,
            wait=True)
        self._homed  = True
        self._moving = False

    def move_to(self, x=None, y=None, z=None,
                speed=None, wait=True) -> None:
        with self._lock:
            if x is not None: self._target.x = x
            if y is not None: self._target.y = y
            if z is not None: self._target.z = z

        if wait:
            self._execute_move()
        else:
            threading.Thread(target=self._execute_move,
                             daemon=True).start()

    def move_by(self, x=0.0, y=0.0, z=0.0,
                speed=None, wait=True) -> None:
        self.move_to(
            x=self._pos.x + x,
            y=self._pos.y + y,
            z=self._pos.z + z,
            speed=speed, wait=wait)

    def _execute_move(self):
        self._moving = True
        step_ms = 0.02   # 20ms update interval

        while True:
            with self._lock:
                dx = self._target.x - self._pos.x
                dy = self._target.y - self._pos.y
                dz = self._target.z - self._pos.z

            dist_xy = (dx**2 + dy**2) ** 0.5
            dist_z  = abs(dz)

            if dist_xy < 0.1 and dist_z < 0.1:
                self._pos.x = self._target.x
                self._pos.y = self._target.y
                self._pos.z = self._target.z
                break

            step_xy = self._speed_xy * step_ms
            step_z  = self._speed_z  * step_ms

            if dist_xy > 0:
                ratio = min(step_xy / dist_xy, 1.0)
                self._pos.x += dx * ratio
                self._pos.y += dy * ratio

            if dist_z > 0:
                ratio = min(step_z / dist_z, 1.0)
                self._pos.z += dz * ratio

            time.sleep(step_ms)

        self._moving = False

    def stop(self) -> None:
        with self._lock:
            self._target.x = self._pos.x
            self._target.y = self._pos.y
            self._target.z = self._pos.z
        self._moving = False

    def get_status(self) -> StageStatus:
        noise = lambda: random.gauss(0, self._noise)
        return StageStatus(
            position = StagePosition(
                x = self._pos.x + noise(),
                y = self._pos.y + noise(),
                z = self._pos.z + noise()),
            moving   = self._moving,
            homed    = self._homed,
        )

    def travel_range(self) -> dict:
        return {"x": (-50_000.0, 50_000.0),
                "y": (-50_000.0, 50_000.0),
                "z": (     0.0,  25_000.0)}
