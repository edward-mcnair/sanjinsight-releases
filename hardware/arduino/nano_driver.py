"""
hardware/arduino/nano_driver.py

Arduino Nano serial driver for LED wavelength selection and GPIO control.

Communicates with an ATmega328P running the SanjINSIGHT I/O firmware
(firmware/arduino_nano/sanjinsight_io.ino) over USB-serial at 115200 baud.

Serial protocol (line-based ASCII, \\n terminated)
--------------------------------------------------
Commands sent to Arduino:
    LED <ch>          Select LED channel (0-based), or -1 for all off
    PIN <pin> <0|1>   Set digital pin LOW/HIGH
    READ <pin>        Read digital pin → "PIN <pin> <0|1>"
    ADC <ch>          Read analog channel → "ADC <ch> <value>"
    STATUS            Request full status → "STATUS ..." (see below)
    IDENT             Request firmware identity → "IDENT <firmware_version>"

Responses from Arduino:
    OK                Command accepted (LED, PIN)
    PIN <pin> <0|1>   Digital pin readback
    ADC <ch> <value>  Analog readback (0–1023)
    STATUS <led> <uptime_ms>   Current state summary
    IDENT <version>   Firmware version string
    ERR <message>     Error from firmware

Config keys (config.yaml → hardware.arduino):
    driver:      "nano"
    port:        "COM3" or "/dev/ttyUSB0"  (auto-detected if omitted)
    baud:        115200
    timeout:     2.0
    led_channels:  [{wavelength_nm: 470, label: "Blue", pin: 2}, ...]
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .base import ArduinoDriver, ArduinoStatus

log = logging.getLogger(__name__)


class ArduinoNanoDriver(ArduinoDriver):
    """Concrete Arduino Nano driver over USB-serial (CH340/FTDI)."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port: Optional[str] = cfg.get("port")
        self._baud: int = int(cfg.get("baud", 115200))
        self._timeout: float = float(cfg.get("timeout", 2.0))
        self._serial = None  # serial.Serial instance
        self._lock = threading.Lock()
        self._firmware_version: str = ""
        self._active_led: int = -1

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        import serial

        port = self._port
        if not port:
            port = self._auto_detect_port()
            if not port:
                raise RuntimeError(
                    "Arduino Nano not found. Specify 'port' in config.yaml "
                    "or connect an Arduino Nano with CH340 USB-serial chip.")

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=self._baud,
                timeout=self._timeout,
            )
            # Arduino resets on serial open — wait for bootloader
            time.sleep(2.0)
            # Flush any bootloader output
            self._serial.reset_input_buffer()

            # Identify firmware — the response MUST be a printable ASCII
            # string starting with "IDENT" to confirm we're talking to an
            # Arduino running the SanjINSIGHT I/O firmware, and NOT to a
            # Meerstetter TEC/LDD that shares the same FTDI VID:PID.
            raw_ident = self._cmd("IDENT")
            if not raw_ident:
                raise RuntimeError(
                    f"No IDENT response from {port}. "
                    "This port may not be an Arduino (Meerstetter TEC/LDD "
                    "devices share the same FTDI USB ID)."
                )
            # Validate: must be printable ASCII and start with "IDENT"
            _is_ascii = all(32 <= ord(c) < 127 or c in '\r\n\t' for c in raw_ident)
            if not _is_ascii or not raw_ident.startswith("IDENT"):
                raise RuntimeError(
                    f"Unexpected response from {port}: {raw_ident!r:.60}  "
                    "— this does not look like an Arduino running "
                    "SanjINSIGHT I/O firmware. The port may belong to a "
                    "Meerstetter TEC or LDD."
                )

            self._firmware_version = raw_ident[6:].strip() if raw_ident.startswith("IDENT ") else raw_ident
            self._connected = True
            self._port = port
            log.info("Arduino Nano connected on %s  (firmware: %s)",
                     port, self._firmware_version)

        except Exception as exc:
            self._serial = None
            from hardware.hw_debug_log import connect_fail
            connect_fail(log, port=port, error=exc, context={
                "baud": self._baud, "timeout": self._timeout,
            })
            raise RuntimeError(
                f"Failed to connect to Arduino Nano on {port}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                # Turn off all LEDs before disconnecting
                self._cmd("LED -1")
            except Exception:
                pass
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._connected = False
        self._active_led = -1
        log.info("Arduino Nano disconnected")

    # ---------------------------------------------------------------- #
    #  LED wavelength selection                                         #
    # ---------------------------------------------------------------- #

    def select_led(self, channel: int) -> None:
        if channel < -1 or channel >= len(self._channels):
            raise ValueError(
                f"LED channel {channel} out of range "
                f"(-1..{len(self._channels) - 1})")
        resp = self._cmd(f"LED {channel}")
        if resp and resp.startswith("ERR"):
            raise RuntimeError(f"Arduino LED select failed: {resp}")
        self._active_led = channel
        # Update channel state
        for ch in self._channels:
            ch.enabled = (ch.index == channel)
        if channel >= 0:
            log.info("LED channel %d (%s) selected",
                     channel, self._channels[channel].label)
        else:
            log.info("All LEDs off")

    def get_active_led(self) -> int:
        return self._active_led

    # ---------------------------------------------------------------- #
    #  Digital GPIO                                                     #
    # ---------------------------------------------------------------- #

    def set_pin(self, pin: int, state: bool) -> None:
        val = 1 if state else 0
        resp = self._cmd(f"PIN {pin} {val}")
        if resp and resp.startswith("ERR"):
            raise RuntimeError(f"Arduino set_pin failed: {resp}")

    def get_pin(self, pin: int) -> bool:
        resp = self._cmd(f"READ {pin}")
        if resp and resp.startswith("PIN"):
            # "PIN <pin> <0|1>"
            parts = resp.split()
            if len(parts) >= 3:
                return parts[2] == "1"
        return False

    # ---------------------------------------------------------------- #
    #  Analog input                                                     #
    # ---------------------------------------------------------------- #

    def read_analog(self, channel: int) -> int:
        if channel < 0 or channel > 7:
            raise ValueError(f"Analog channel {channel} out of range (0–7)")
        resp = self._cmd(f"ADC {channel}")
        if resp and resp.startswith("ADC"):
            # "ADC <ch> <value>"
            parts = resp.split()
            if len(parts) >= 3:
                return int(parts[2])
        return 0

    # ---------------------------------------------------------------- #
    #  Status                                                           #
    # ---------------------------------------------------------------- #

    def get_status(self) -> ArduinoStatus:
        resp = self._cmd("STATUS")
        uptime = 0
        led = self._active_led
        if resp and resp.startswith("STATUS"):
            parts = resp.split()
            if len(parts) >= 3:
                try:
                    led = int(parts[1])
                except ValueError:
                    pass
                try:
                    uptime = int(parts[2])
                except ValueError:
                    pass
            self._active_led = led

        return ArduinoStatus(
            firmware_version=self._firmware_version,
            active_led=led,
            uptime_ms=uptime,
        )

    # ---------------------------------------------------------------- #
    #  Internal: serial I/O                                             #
    # ---------------------------------------------------------------- #

    def _cmd(self, command: str) -> str:
        """Send a command and read the response line. Thread-safe."""
        from hardware.hw_debug_log import tx as _tx, rx as _rx, timed as _timed

        with self._lock:
            if self._serial is None:
                return ""
            try:
                raw = (command + "\n").encode("ascii")
                _tx(log, raw, label="Arduino")
                self._serial.write(raw)
                self._serial.flush()
                with _timed(log, f"Arduino '{command}' response"):
                    line = self._serial.readline().decode("ascii", errors="replace").strip()
                _rx(log, line, label="Arduino")
                return line
            except Exception as exc:
                log.warning("Arduino serial error on '%s': %s", command, exc)
                return ""

    @staticmethod
    def _auto_detect_port() -> Optional[str]:
        """Scan serial ports for a CH340-based Arduino Nano."""
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return None

        # CH340 VID:PID  = 1A86:7523
        # FTDI VID:PID   = 0403:6001  (some Nano clones)
        # Arduino.cc      = 2341:0043  (UNO R3)
        # Arduino.cc      = 2341:0069  (UNO R4 Minima)
        _VIDS_PIDS = {
            (0x1A86, 0x7523),  # CH340
            (0x0403, 0x6001),  # FTDI FT232R
            (0x2341, 0x0043),  # Arduino UNO R3
            (0x2341, 0x0069),  # Arduino UNO R4 Minima
        }

        for port_info in comports():
            vid = port_info.vid
            pid = port_info.pid
            if vid is not None and pid is not None:
                if (vid, pid) in _VIDS_PIDS:
                    log.info("Auto-detected Arduino on %s "
                             "(VID=%04X PID=%04X)",
                             port_info.device, vid, pid)
                    return port_info.device

            # Fallback: match description strings
            desc = (port_info.description or "").lower()
            if any(s in desc for s in ("ch340", "arduino nano",
                                       "arduino uno", "ttyacm")):
                log.info("Auto-detected Arduino on %s (desc=%s)",
                         port_info.device, port_info.description)
                return port_info.device

        return None

    @classmethod
    def preflight(cls) -> tuple:
        try:
            import serial  # noqa: F401
            return (True, [])
        except ImportError:
            return (False, [
                "pyserial is not installed.\n"
                "Fix: pip install pyserial"
            ])
