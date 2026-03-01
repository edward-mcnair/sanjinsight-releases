"""
hardware/stage/thorlabs.py

Driver for Thorlabs motorized stages via the Thorlabs Kinesis Python API.
Supports: BBD302, KST101, KDC101, TDC001, MTS25/50, LTS150/300, Z825.

Requires:
    - Thorlabs Kinesis software installed
    - pip install thorlabs-apt-device  (or thorlabs-kinesis on Windows)

Connection: USB (each controller appears as a COM port)

Config keys (under hardware.stage):
    serial_x:   "27000001"   Serial number of X axis controller
    serial_y:   "27000002"   Serial number of Y axis controller
    serial_z:   "27000003"   Serial number of Z axis controller
    pitch:      1.0          Lead screw pitch in mm (stage-specific)
    steps_per_rev: 512       Motor steps per revolution

Leave serial_y / serial_z blank if those axes don't exist on your system.
"""

import logging
import time
from typing import Optional
from .base import StageDriver, StageStatus, StagePosition

log = logging.getLogger(__name__)


class ThorlabsDriver(StageDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._serial = {
            "x": str(cfg.get("serial_x", "")),
            "y": str(cfg.get("serial_y", "")),
            "z": str(cfg.get("serial_z", "")),
        }
        self._controllers = {}
        self._homed       = False

    def connect(self) -> None:
        try:
            from thorlabs_apt_device import APTDevice
        except ImportError:
            raise RuntimeError(
                "thorlabs_apt_device not installed.\n"
                "Run: pip install thorlabs-apt-device\n"
                "Also install Thorlabs Kinesis software.")

        for axis, serial in self._serial.items():
            if not serial:
                continue
            try:
                dev = APTDevice(serial_port=None, serial_number=serial)
                self._controllers[axis] = dev
                log.info("Thorlabs stage %s connected: %s", axis.upper(), serial)
            except Exception as e:
                raise RuntimeError(
                    f"Thorlabs {axis.upper()} axis ({serial}) failed: {e}\n"
                    f"Check USB connection and Kinesis software.")

        if not self._controllers:
            raise RuntimeError("No Thorlabs axes configured. "
                               "Set serial_x/y/z in config.yaml.")
        self._connected = True

    def disconnect(self) -> None:
        self.stop()
        for dev in self._controllers.values():
            try:
                dev.close()
            except Exception:
                pass
        self._connected = False

    def home(self, axes: str = "xyz") -> None:
        for ax in axes:
            if ax in self._controllers:
                self._controllers[ax].home()
        # Wait for all to complete
        for ax in axes:
            if ax in self._controllers:
                while self._controllers[ax].status.is_homing:
                    time.sleep(0.05)
        self._homed = True

    def move_to(self, x=None, y=None, z=None,
                speed=None, wait=True) -> None:
        moves = {"x": x, "y": y, "z": z}
        for ax, val in moves.items():
            if val is not None and ax in self._controllers:
                # Convert μm → encoder counts
                counts = self._um_to_counts(val)
                self._controllers[ax].move_to(counts)

        if wait:
            for ax in moves:
                if moves[ax] is not None and ax in self._controllers:
                    while self._controllers[ax].status.is_moving:
                        time.sleep(0.02)

        self._update_pos()

    def move_by(self, x=0.0, y=0.0, z=0.0,
                speed=None, wait=True) -> None:
        self.move_to(
            x=self._pos.x + x if x is not None else None,
            y=self._pos.y + y if y is not None else None,
            z=self._pos.z + z if z is not None else None,
            speed=speed, wait=wait)

    def stop(self) -> None:
        for dev in self._controllers.values():
            try:
                dev.stop_profiled()
            except Exception:
                pass

    def get_status(self) -> StageStatus:
        try:
            self._update_pos()
            moving = any(
                dev.status.is_moving
                for dev in self._controllers.values())
            return StageStatus(
                position = StagePosition(
                    x=self._pos.x, y=self._pos.y, z=self._pos.z),
                moving   = moving,
                homed    = self._homed,
            )
        except Exception as e:
            return StageStatus(error=str(e))

    def _update_pos(self):
        for ax, dev in self._controllers.items():
            um = self._counts_to_um(dev.status.position)
            setattr(self._pos, ax, um)

    def _um_to_counts(self, um: float) -> int:
        """Convert micrometers to encoder counts."""
        pitch_um   = self._cfg.get("pitch", 1.0) * 1000.0
        steps_rev  = self._cfg.get("steps_per_rev", 512)
        counts_um  = steps_rev / pitch_um
        return int(um * counts_um)

    def _counts_to_um(self, counts: int) -> float:
        pitch_um   = self._cfg.get("pitch", 1.0) * 1000.0
        steps_rev  = self._cfg.get("steps_per_rev", 512)
        counts_um  = steps_rev / pitch_um
        return counts / counts_um

    def travel_range(self) -> dict:
        return {"x": (0.0, 25_000.0), "y": (0.0, 25_000.0),
                "z": (0.0, 25_000.0)}
