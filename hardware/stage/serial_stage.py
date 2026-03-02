"""
hardware/stage/serial_stage.py

Driver for serial-command stages — covers Prior Scientific, Ludl,
Marzhauser, ASI (Applied Scientific Instrumentation), and many others
that accept simple ASCII commands over RS-232 or USB-CDC.

Command dialects are selectable via the "dialect" config key.

Config keys (under hardware.stage):
    port:      "COM5"         Serial port
    baudrate:  9600
    dialect:   "prior"        prior | ludl | asi | marzhauser
    timeout:   1.0

Dialect summary:
    prior       G x,y / GZ z / P (position query) / H (home) / K (stop)
    ludl        MOVE x y / MOVEZ z / WHERE / HOME / HALT
    asi         MOVE X=x Y=y / MOVEREL X=dx / WHERE / HOME / HALT
    marzhauser  :move x y z CR  /  :pos CR  /  :home CR
"""

import logging
import serial
import time
from typing import Optional
from .base import StageDriver, StageStatus, StagePosition
from hardware.port_lock import PortLock, exclusive_serial_kwargs

log = logging.getLogger(__name__)


class SerialStageDriver(StageDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port    = cfg.get("port",    "COM5")
        self._baud    = cfg.get("baudrate", 9600)
        self._dialect = cfg.get("dialect", "prior").lower()
        self._timeout = cfg.get("timeout", 1.0)
        self._serial    = None
        self._homed     = False
        self._port_lock = PortLock(self._port)

    def connect(self) -> None:
        try:
            self._port_lock.acquire()
            self._serial = serial.Serial(
                port     = self._port,
                baudrate = self._baud,
                timeout  = self._timeout,
                **exclusive_serial_kwargs(),
            )
            self._connected = True
            log.info("Stage (%s) connected on %s", self._dialect, self._port)
        except ImportError:
            self._port_lock.release()
            raise RuntimeError(
                "pyserial not installed. Run: pip install pyserial")
        except serial.SerialException as e:
            self._port_lock.release()
            raise RuntimeError(
                f"Stage connect failed on {self._port}: {e}")
        except Exception:
            self._port_lock.release()
            raise

    def disconnect(self) -> None:
        self.stop()
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False
        self._port_lock.release()

    def _send(self, cmd: str) -> str:
        """Write cmd and return the response line.

        Uses read_until('\r') so the existing serial timeout governs how long
        we wait — no fixed sleep, no missed slow responses.
        reset_input_buffer() prevents stale bytes from a previous command
        contaminating the response.
        """
        self._serial.reset_input_buffer()
        self._serial.write((cmd + "\r").encode())
        resp = self._serial.read_until(b"\r", size=256)
        return resp.decode(errors="ignore").strip()

    def home(self, axes: str = "xyz") -> None:
        cmds = {
            "prior":      "H",
            "ludl":       "HOME",
            "asi":        "HOME",
            "marzhauser": ":home",
        }
        self._send(cmds.get(self._dialect, "H"))
        time.sleep(2.0)   # wait for homing to complete
        self._homed = True

    def move_to(self, x=None, y=None, z=None,
                speed=None, wait=True) -> None:
        cx = x if x is not None else self._pos.x
        cy = y if y is not None else self._pos.y
        cz = z if z is not None else self._pos.z

        if x is not None or y is not None:
            self._move_xy(cx, cy)
        if z is not None:
            self._move_z(cz)

        if wait:
            self._wait_idle()

        self._update_pos()

    def move_by(self, x=0.0, y=0.0, z=0.0,
                speed=None, wait=True) -> None:
        self.move_to(
            x=self._pos.x + x,
            y=self._pos.y + y,
            z=self._pos.z + z,
            wait=wait)

    def stop(self) -> None:
        cmds = {"prior": "K", "ludl": "HALT",
                "asi": "HALT", "marzhauser": ":stop"}
        self._send(cmds.get(self._dialect, "K"))

    def _move_xy(self, x: float, y: float):
        xi, yi = int(x), int(y)
        cmds = {
            "prior":      f"G {xi},{yi}",
            "ludl":       f"MOVE {xi} {yi}",
            "asi":        f"MOVE X={xi} Y={yi}",
            "marzhauser": f":move {xi} {yi} {int(self._pos.z)}",
        }
        self._send(cmds.get(self._dialect, f"G {xi},{yi}"))

    def _move_z(self, z: float):
        zi = int(z)
        cmds = {
            "prior":      f"GZ {zi}",
            "ludl":       f"MOVEZ {zi}",
            "asi":        f"MOVE Z={zi}",
            "marzhauser": f":movez {zi}",
        }
        self._send(cmds.get(self._dialect, f"GZ {zi}"))

    def _wait_idle(self, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            status = self._query_moving()
            if not status:
                return
            time.sleep(0.05)

    def _query_moving(self) -> bool:
        try:
            cmds = {"prior": "$", "ludl": "STATUS",
                    "asi": "/", "marzhauser": ":status"}
            resp = self._send(cmds.get(self._dialect, "$"))
            return resp not in ("R", "0", "N")
        except Exception:
            return False

    def _update_pos(self):
        try:
            cmds = {"prior": "P", "ludl": "WHERE",
                    "asi": "WHERE X Y Z", "marzhauser": ":pos"}
            resp = self._send(cmds.get(self._dialect, "P"))
            parts = resp.replace(",", " ").split()
            nums  = [float(p) for p in parts if self._is_number(p)]
            if len(nums) >= 2:
                self._pos.x = nums[0]
                self._pos.y = nums[1]
            if len(nums) >= 3:
                self._pos.z = nums[2]
        except Exception:
            pass

    def _is_number(self, s: str) -> bool:
        try:
            float(s)
            return True
        except ValueError:
            return False

    def get_status(self) -> StageStatus:
        try:
            self._update_pos()
            moving = self._query_moving()
            return StageStatus(
                position = StagePosition(
                    x=self._pos.x, y=self._pos.y, z=self._pos.z),
                moving   = moving,
                homed    = self._homed,
            )
        except Exception as e:
            return StageStatus(error=str(e))
