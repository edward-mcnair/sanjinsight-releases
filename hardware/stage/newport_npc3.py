"""
hardware/stage/newport_npc3.py

Driver for the Newport / MKS Instruments NPC3 and NPC3SG Piezo Stack
Amplifier Controller.

The NPC3 is a 3-channel closed-loop (SG model) or open-loop piezo
controller that communicates over USB (FTDI virtual COM port) or RS-232
using a simple comma-delimited ASCII command protocol at 19200 baud.

The three channels map to the X, Y, Z axes of the StageDriver interface.
In closed-loop mode (SG model) positions are in micrometers; in open-loop
mode they are in volts.

Config keys (under hardware.stage):
    driver:    "newport_npc3"
    port:      "COM5"         Serial port (or USB-CDC virtual port)
    baudrate:  19200          Default per Newport manual
    timeout:   1.0            Serial read timeout (seconds)
    closed_loop: true         Use closed-loop position mode (SG models)

Protocol reference:
    NPC3 & NPC3SG User's Manual (Newport / MKS Instruments)
    https://www.newport.com/p/NPC3SG
"""

import logging
import time
import serial
from typing import Optional

from .base import StageDriver, StageStatus, StagePosition
from hardware.port_lock import PortLock, exclusive_serial_kwargs

log = logging.getLogger(__name__)

# Channel mapping: NPC3 channels 0, 1, 2 → X, Y, Z
_CH_X = 0
_CH_Y = 1
_CH_Z = 2
_CHANNELS = (_CH_X, _CH_Y, _CH_Z)


class NewportNPC3Driver(StageDriver):
    """Driver for Newport NPC3 / NPC3SG 3-channel piezo controller."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port        = cfg.get("port", "")
        self._baud        = cfg.get("baudrate", 19200)
        self._timeout     = cfg.get("timeout", 1.0)
        self._closed_loop = cfg.get("closed_loop", True)
        self._ser: Optional[serial.Serial] = None
        self._lock: Optional[PortLock] = None

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        if self._connected:
            return
        if not self._port:
            raise RuntimeError(
                "No serial port configured for Newport NPC3. "
                "Set 'port' under hardware.stage in config.yaml.")

        try:
            self._lock = PortLock(self._port)
            self._ser = serial.Serial(
                port          = self._port,
                baudrate      = self._baud,
                bytesize      = serial.EIGHTBITS,
                parity        = serial.PARITY_NONE,
                stopbits      = serial.STOPBITS_ONE,
                timeout       = self._timeout,
                write_timeout = self._timeout,   # prevent indefinite write blocks
                xonxoff       = True,             # NPC3 uses software flow control
                **exclusive_serial_kwargs(),
            )
        except serial.SerialException as e:
            from hardware.hw_debug_log import connect_fail
            connect_fail(log, port=self._port, error=e, context={
                "baud": self._baud, "xonxoff": True,
                "closed_loop": self._closed_loop,
            })
            raise RuntimeError(
                f"Cannot open {self._port} for Newport NPC3: {e}") from e

        # Small delay for controller to become responsive after port open
        time.sleep(0.3)
        self._ser.reset_input_buffer()

        # Enable remote control on all three channels
        for ch in _CHANNELS:
            self._send(f"setk,{ch},1", expect_reply=False)

        # Set closed-loop mode if requested (SG models only)
        if self._closed_loop:
            for ch in _CHANNELS:
                self._send(f"cloop,{ch},1", expect_reply=False)

        # Read initial positions
        self._update_pos()
        self._connected = True
        log.info("Newport NPC3 connected on %s (%s-loop)",
                 self._port, "closed" if self._closed_loop else "open")

    def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            # Disable remote control — returns knob control to user
            for ch in _CHANNELS:
                try:
                    self._send(f"setk,{ch},0", expect_reply=False)
                except Exception:
                    pass
        finally:
            self._connected = False
            if self._ser and self._ser.is_open:
                try:
                    self._ser.close()
                except Exception:
                    pass
            self._ser = None
            if self._lock is not None:
                try:
                    self._lock.release()
                except Exception:
                    log.debug("Port lock release failed", exc_info=True)
            self._lock = None
            log.info("Newport NPC3 disconnected")

    # ---------------------------------------------------------------- #
    #  Motion                                                           #
    # ---------------------------------------------------------------- #

    def home(self, axes: str = "xyz") -> None:
        """
        Zero the specified axes.

        The NPC3 has no mechanical homing routine — it uses strain-gauge
        feedback for absolute position.  "Home" sets each axis to 0 μm.
        """
        vals = [None, None, None]
        if "x" in axes.lower():
            vals[0] = 0.0
        if "y" in axes.lower():
            vals[1] = 0.0
        if "z" in axes.lower():
            vals[2] = 0.0
        self._set_channels(vals[0], vals[1], vals[2])
        self._update_pos()

    def move_to(self,
                x: Optional[float] = None,
                y: Optional[float] = None,
                z: Optional[float] = None,
                speed: Optional[float] = None,
                wait: bool = True) -> None:
        """
        Move to absolute position in micrometers (closed-loop) or volts
        (open-loop).

        The NPC3 does not support speed control — piezo motion is
        effectively instantaneous.  The speed parameter is accepted
        for interface compatibility but ignored.
        """
        self._set_channels(x, y, z)
        if wait:
            # Piezo settling time — allow strain-gauge feedback to stabilise
            time.sleep(0.05)
        self._update_pos()

    def move_by(self,
                x: float = 0.0,
                y: float = 0.0,
                z: float = 0.0,
                speed: Optional[float] = None,
                wait: bool = True) -> None:
        """Move by a relative offset in μm (or volts in open-loop)."""
        self._update_pos()
        new_x = self._pos.x + x if x else None
        new_y = self._pos.y + y if y else None
        new_z = self._pos.z + z if z else None
        self.move_to(x=new_x, y=new_y, z=new_z, speed=speed, wait=wait)

    def stop(self) -> None:
        """
        Stop all motion.

        Piezo actuators don't have continuous motion to stop — they
        move to a setpoint and hold.  This is a no-op, but we update
        position for consistency.
        """
        self._update_pos()

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> StageStatus:
        self._update_pos()
        return StageStatus(
            position = StagePosition(
                x=self._pos.x, y=self._pos.y, z=self._pos.z),
            moving = False,    # piezo motion is effectively instantaneous
            homed  = True,     # strain gauge gives absolute position
        )

    def travel_range(self) -> dict:
        """
        NPC3SG typical travel range depends on the attached piezo actuator.
        Common Newport NPA-series actuators: 15 μm, 30 μm, or 60 μm.
        Override in config if your actuator differs.
        """
        _range = self._cfg.get("travel_range_um", 30.0)
        return {
            "x": (0.0, _range),
            "y": (0.0, _range),
            "z": (0.0, _range),
        }

    def default_speed(self) -> dict:
        # Piezo motion is near-instantaneous; these are nominal values
        return {"x": 1000.0, "y": 1000.0, "z": 1000.0}

    # ---------------------------------------------------------------- #
    #  Preflight                                                        #
    # ---------------------------------------------------------------- #

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import serial as _s  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial package not found.\n"
                "Fix: pip install pyserial")
            return (False, issues)
        return (True, issues)

    # ---------------------------------------------------------------- #
    #  Internal serial I/O                                              #
    # ---------------------------------------------------------------- #

    def _send(self, cmd: str, expect_reply: bool = True) -> str:
        """
        Send an ASCII command and optionally read a response line.

        The NPC3 protocol uses comma-delimited commands terminated with
        CR (\\r).  Responses (from query commands like ``rk``) are
        terminated with CR.  Write-only commands (``set``, ``setall``,
        ``setk``, ``cloop``) produce no response — pass
        *expect_reply=False* to skip the read and avoid a timeout.
        """
        from hardware.hw_debug_log import tx as _tx, rx as _rx, timed as _timed

        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Newport NPC3 serial port is not open")

        self._ser.reset_input_buffer()
        raw = f"{cmd}\r".encode("ascii")
        _tx(log, raw, label="NPC3")
        self._ser.write(raw)
        self._ser.flush()

        if not expect_reply:
            # Give the controller a brief moment to process the command
            time.sleep(0.01)
            return ""

        # Read response — query commands echo the command + value
        with _timed(log, f"NPC3 '{cmd.split(',')[0]}' response"):
            resp_raw = self._ser.read_until(b"\r", size=256)
        _rx(log, resp_raw, label="NPC3")
        return resp_raw.decode("ascii", errors="replace").strip()

    def _set_channels(self,
                      x: Optional[float] = None,
                      y: Optional[float] = None,
                      z: Optional[float] = None) -> None:
        """
        Set one or more channel values.

        Uses setall when all three are specified (single command, atomic);
        uses individual set commands otherwise.
        """
        if x is not None and y is not None and z is not None:
            self._send(f"setall,{x:.3f},{y:.3f},{z:.3f}", expect_reply=False)
        else:
            if x is not None:
                self._send(f"set,{_CH_X},{x:.3f}", expect_reply=False)
            if y is not None:
                self._send(f"set,{_CH_Y},{y:.3f}", expect_reply=False)
            if z is not None:
                self._send(f"set,{_CH_Z},{z:.3f}", expect_reply=False)

    def _read_channel(self, ch: int) -> float:
        """Query one channel's current value (μm in closed-loop, V in open-loop)."""
        resp = self._send(f"rk,{ch}")
        # Expected response format: "rk,<ch>,<value>"
        try:
            parts = resp.split(",")
            if len(parts) >= 3:
                return float(parts[2])
            # Some firmware versions may return just the value
            return float(parts[-1])
        except (ValueError, IndexError):
            log.warning("NPC3 rk,%d unexpected response: %r", ch, resp)
            return 0.0

    def _update_pos(self) -> None:
        """Read all three channels and update self._pos."""
        if self._ser is None or not self._ser.is_open:
            return
        try:
            self._pos.x = self._read_channel(_CH_X)
            self._pos.y = self._read_channel(_CH_Y)
            self._pos.z = self._read_channel(_CH_Z)
        except Exception as e:
            log.debug("NPC3 position read failed: %s", e)

    def __repr__(self):
        return (f"<NewportNPC3Driver port={self._port} "
                f"connected={self._connected} pos={self._pos}>")
