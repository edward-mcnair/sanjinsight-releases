"""
hardware/tec/atec.py

Driver for ATEC-302 TEC controller via Modbus-style serial communication.

Requires: pip install pyserial

Config keys (under hardware.tec_atec):
    port:     "COM4"
    baudrate: 9600
    address:  1
    timeout:  1.0
"""

import logging
import struct
import serial
from .base import TecDriver, TecStatus
from hardware.port_lock import PortLock, exclusive_serial_kwargs

log = logging.getLogger(__name__)


class AtecDriver(TecDriver):
    """
    ATEC-302 driver using Modbus RTU over RS-232.
    Register map based on ATEC-302 communication protocol.
    """

    # Modbus register addresses (ATEC-302 protocol)
    REG_ACTUAL_TEMP    = 0x0000
    REG_TARGET_TEMP    = 0x0001
    REG_OUTPUT_CURRENT = 0x0002
    REG_OUTPUT_VOLTAGE = 0x0003
    REG_ENABLE         = 0x0010

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port     = cfg.get("port",     "COM4")
        self._baudrate = cfg.get("baudrate", 9600)
        self._address  = cfg.get("address",  1)
        self._timeout  = cfg.get("timeout",  1.0)
        self._serial   = None
        self._target   = 25.0
        self._port_lock = PortLock(self._port)

    def connect(self) -> None:
        try:
            self._port_lock.acquire()
            self._serial = serial.Serial(
                port     = self._port,
                baudrate = self._baudrate,
                bytesize = serial.EIGHTBITS,
                parity   = serial.PARITY_NONE,
                stopbits = serial.STOPBITS_ONE,
                timeout  = self._timeout,
                **exclusive_serial_kwargs(),
            )
            self._connected = True
            log.info("ATEC-302 connected on %s", self._port)
        except ImportError:
            self._port_lock.release()
            raise RuntimeError(
                "pyserial not installed. Run: pip install pyserial")
        except serial.SerialException as e:
            self._port_lock.release()
            raise RuntimeError(
                f"ATEC-302 connect failed on {self._port}: {e}\n"
                f"Check port name and cable connection.")
        except Exception:
            self._port_lock.release()
            raise

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False
        self._port_lock.release()

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
        """Read a single holding register (Modbus FC03)."""
        request = struct.pack('>BBHH', self._address, 0x03, reg, 1)
        crc     = self._crc16(request)
        request += struct.pack('<H', crc)
        self._serial.write(request)
        response = self._serial.read(7)
        if len(response) < 7:
            raise IOError(f"Short response reading register {reg:#06x}")
        value_raw = struct.unpack('>H', response[3:5])[0]
        # ATEC-302 encodes temperature as signed int16 × 0.1
        signed = struct.unpack('>h', struct.pack('>H', value_raw))[0]
        return signed * 0.1

    def _write_register(self, reg: int, value: int) -> None:
        """Write a single holding register (Modbus FC06)."""
        request = struct.pack('>BBHH', self._address, 0x06, reg, value)
        crc     = self._crc16(request)
        request += struct.pack('<H', crc)
        self._serial.write(request)
        self._serial.read(8)   # echo response

    def enable(self) -> None:
        self._write_register(self.REG_ENABLE, 1)

    def disable(self) -> None:
        self._write_register(self.REG_ENABLE, 0)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        raw = int(temperature_c * 10) & 0xFFFF
        self._write_register(self.REG_TARGET_TEMP, raw)

    def get_status(self) -> TecStatus:
        try:
            actual  = self._read_register(self.REG_ACTUAL_TEMP)
            current = self._read_register(self.REG_OUTPUT_CURRENT)
            voltage = self._read_register(self.REG_OUTPUT_VOLTAGE)
            enabled = bool(int(self._read_register(self.REG_ENABLE)))
            stable  = abs(actual - self._target) <= self.stability_tolerance()
            return TecStatus(
                actual_temp    = actual,
                target_temp    = self._target,
                output_current = current,
                output_voltage = voltage,
                output_power   = abs(current * voltage),
                enabled        = enabled,
                stable         = stable,
            )
        except Exception as e:
            return TecStatus(error=str(e))

    def temp_range(self) -> tuple:
        return (-40.0, 100.0)
