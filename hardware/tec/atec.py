"""
hardware/tec/atec.py

Driver for ATEC-302 TEC controller via Modbus-style serial communication.

Requires: pip install pyserial

Config keys (under hardware.tec_atec):
    port:     ""        Serial port (Windows: COMx, macOS: /dev/cu.usbmodemXXX)
    baudrate: 9600
    address:  1
    timeout:  1.0
"""

import logging
import struct
import threading
import serial
from .base import TecDriver, TecStatus
from hardware.port_lock import PortLock, serial_connect, serial_disconnect

log = logging.getLogger(__name__)


class AtecDriver(TecDriver):
    """
    ATEC-302 driver using Modbus RTU over RS-232.
    Register map based on ATEC-302 communication protocol.
    """

    # Modbus register addresses (ATEC-302 Reference Manual v1.10)
    REG_ACTUAL_TEMP    = 0x0000   # PV — process value (actual temp, read)
    REG_TARGET_TEMP    = 0x0001   # SV — set value (target temp, read/write)
    REG_HIGH_LIMIT     = 0x0002   # Upper temperature safety limit
    REG_LOW_LIMIT      = 0x0003   # Lower temperature safety limit
    REG_CTRL_MODE      = 0x0023   # Control mode (PID / open-loop)
    REG_ENABLE         = 0x0010   # Output enable flag
    REG_ALARM_STATUS   = 0x0200   # Alarm flags (read)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port     = cfg.get("port",     "")
        self._baudrate = cfg.get("baudrate", 9600)
        self._address  = cfg.get("address",  1)
        self._timeout  = cfg.get("timeout",  1.0)
        self._serial   = None
        self._target   = 25.0
        self._port_lock  = PortLock(self._port)
        # pyserial is not thread-safe; poll thread and control threads
        # must not interleave Modbus frames on the serial bus
        self._serial_lock = threading.Lock()

    def connect(self) -> None:
        self._serial = serial_connect(
            self._port, self._port_lock,
            baudrate=self._baudrate,
            stopbits=serial.STOPBITS_TWO,  # N-8-2 per ATEC-302 spec
            timeout=self._timeout,
            device_name="ATEC-302 TEC",
        )
        self._connected = True

    def disconnect(self) -> None:
        serial_disconnect(self._serial, self._port_lock,
                          device_name="ATEC-302 TEC")
        self._serial = None
        self._connected = False

    def _crc16(self, data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def _read_register(self, reg: int) -> float:
        """Read a single holding register (Modbus FC03).

        Returns value as float (÷10 for temperature registers).
        """
        request = struct.pack('>BBHH', self._address, 0x03, reg, 1)
        crc     = self._crc16(request)
        request += struct.pack('<H', crc)
        self._serial.reset_input_buffer()
        self._serial.write(request)
        response = self._serial.read(7)
        if len(response) < 7:
            raise IOError(f"Short response reading register {reg:#06x}")
        value_raw = struct.unpack('>H', response[3:5])[0]
        # ATEC-302 encodes temperature as signed int16 × 0.1
        signed = struct.unpack('>h', struct.pack('>H', value_raw))[0]
        return signed * 0.1

    def _read_register_raw(self, reg: int) -> int:
        """Read a single holding register, returning the raw U16 value."""
        request = struct.pack('>BBHH', self._address, 0x03, reg, 1)
        crc     = self._crc16(request)
        request += struct.pack('<H', crc)
        self._serial.reset_input_buffer()
        self._serial.write(request)
        response = self._serial.read(7)
        if len(response) < 7:
            raise IOError(f"Short response reading register {reg:#06x}")
        return struct.unpack('>H', response[3:5])[0]

    def _write_register(self, reg: int, value: int) -> None:
        """Write a single holding register (Modbus FC06)."""
        request = struct.pack('>BBHH', self._address, 0x06, reg, value)
        crc     = self._crc16(request)
        request += struct.pack('<H', crc)
        self._serial.reset_input_buffer()
        self._serial.write(request)
        self._serial.read(8)   # echo response

    def enable(self) -> None:
        with self._serial_lock:
            self._write_register(self.REG_ENABLE, 1)

    def disable(self) -> None:
        with self._serial_lock:
            self._write_register(self.REG_ENABLE, 0)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        raw = int(round(temperature_c * 10)) & 0xFFFF
        with self._serial_lock:
            self._write_register(self.REG_TARGET_TEMP, raw)

    def set_temperature_limits(self, low_c: float, high_c: float) -> None:
        """Set upper and lower temperature safety limits in °C."""
        with self._serial_lock:
            self._write_register(self.REG_HIGH_LIMIT,
                                 int(round(high_c * 10)) & 0xFFFF)
            self._write_register(self.REG_LOW_LIMIT,
                                 int(round(low_c * 10)) & 0xFFFF)
        log.info("ATEC-302 temp limits set: %.1f°C – %.1f°C", low_c, high_c)

    def get_alarm_status(self) -> int:
        """Read alarm status flags (0 = no alarms)."""
        with self._serial_lock:
            return self._read_register_raw(self.REG_ALARM_STATUS)

    def set_control_mode(self, mode: int) -> None:
        """Set the TEC control mode (ATEC-302 register 0x0023).

        Parameters
        ----------
        mode : int
            0 = PID (closed-loop) control.
            Other values select open-loop operation per the ATEC-302 manual.
        """
        with self._serial_lock:
            self._write_register(self.REG_CTRL_MODE, mode & 0xFFFF)
        log.info("ATEC-302 control mode set to %d (%s)",
                 mode, "PID" if mode == 0 else "open-loop")

    def get_status(self) -> TecStatus:
        try:
            with self._serial_lock:
                actual  = self._read_register(self.REG_ACTUAL_TEMP)
                enabled = bool(int(self._read_register(self.REG_ENABLE)))
            stable  = abs(actual - self._target) <= self.stability_tolerance()
            return TecStatus(
                actual_temp    = actual,
                target_temp    = self._target,
                # ATEC-302 does not expose output current/voltage via
                # Modbus.  Registers 0x0002 and 0x0003 are temperature
                # limits, not electrical outputs.
                output_current = 0.0,
                output_voltage = 0.0,
                output_power   = 0.0,
                enabled        = enabled,
                stable         = stable,
            )
        except Exception as e:
            return TecStatus(error=str(e))

    def temp_range(self) -> tuple:
        return (-40.0, 100.0)
