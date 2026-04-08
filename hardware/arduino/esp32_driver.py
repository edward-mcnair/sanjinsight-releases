"""
hardware/arduino/esp32_driver.py

ESP32 serial driver for LED wavelength selection and GPIO control.

Communicates with an ESP32 (any variant: ESP32, ESP32-S2, ESP32-S3, ESP32-C3)
running the SanjINSIGHT I/O firmware over USB-serial at 115200 baud.

The ESP32 speaks the **same ASCII protocol** as the Arduino Nano firmware
(see nano_driver.py for the full command reference).  The only differences
are hardware-level:

  • USB chip: CP2102/CP2104 (Silicon Labs), or native USB (ESP32-S2/S3/C3)
  • GPIO pin numbering: ESP32 uses its own pin map (configurable via
    ``led_channels`` in config.yaml)
  • ADC resolution: ESP32 has 12-bit ADC (0–4095) vs Nano's 10-bit (0–1023).
    The firmware should scale to 10-bit for protocol compatibility, or callers
    can read the raw 12-bit value via the ``adc_bits`` config key.
  • No bootloader reset: ESP32 does not reset on serial open, so the 2-second
    post-connect delay used by the Nano driver is skipped.

Config keys (config.yaml → hardware.arduino):
    driver:      "esp32"
    port:        "/dev/tty.usbserial-0001"  (auto-detected if omitted)
    baud:        115200
    timeout:     2.0
    adc_bits:    12       (default; set to 10 if firmware scales output)
    led_channels:  [{wavelength_nm: 470, label: "Blue", pin: 16}, ...]

Auto-detection
--------------
Scans for:
  • Silicon Labs CP210x  — VID 10C4, PID EA60 (most common ESP32 dev boards)
  • Espressif native USB — VID 303A, PID 1001 (ESP32-S2/S3/C3 built-in USB)
  • Description-string fallback: "CP210", "ESP32", "Espressif"
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .base import ArduinoDriver, ArduinoStatus, LedChannel

log = logging.getLogger(__name__)

# Default LED channels for ESP32 — sensible GPIO pins that avoid
# boot-strapping pins (GPIO0, GPIO2, GPIO12) and flash pins (GPIO6–11).
_ESP32_DEFAULT_LED_CHANNELS = [
    LedChannel(index=0, wavelength_nm=470, label="470 nm Blue",   pin=16),
    LedChannel(index=1, wavelength_nm=530, label="530 nm Green",  pin=17),
    LedChannel(index=2, wavelength_nm=590, label="590 nm Amber",  pin=18),
    LedChannel(index=3, wavelength_nm=625, label="625 nm Red",    pin=19),
]


class Esp32Driver(ArduinoDriver):
    """Concrete ESP32 driver over USB-serial (CP2102 or native USB)."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port: Optional[str] = cfg.get("port")
        self._baud: int = int(cfg.get("baud", 115200))
        self._timeout: float = float(cfg.get("timeout", 2.0))
        self._adc_bits: int = int(cfg.get("adc_bits", 12))
        self._serial = None  # serial.Serial instance
        self._lock = threading.Lock()
        self._firmware_version: str = ""
        self._active_led: int = -1

        # Use ESP32 default pin map if no custom channels were loaded
        if not cfg.get("led_channels"):
            self._channels = list(_ESP32_DEFAULT_LED_CHANNELS)

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        import serial

        # Build candidate list: saved port first, then auto-detected ports.
        saved_port = self._port
        candidates: list[str] = []
        if saved_port:
            candidates.append(saved_port)
        for ap in self._auto_detect_ports():
            if ap not in candidates:
                candidates.append(ap)

        if not candidates:
            raise RuntimeError(
                "ESP32 not found. Specify 'port' in config.yaml "
                "or connect an ESP32 board with CP2102 or native USB.")

        last_error: Optional[Exception] = None
        for port in candidates:
            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=self._baud,
                    timeout=self._timeout,
                )
                # ESP32 does NOT reset on serial open (unlike Arduino Nano),
                # but give a short settle for the USB-serial bridge.
                time.sleep(0.3)
                self._serial.reset_input_buffer()

                # Identify firmware — validate response to avoid connecting
                # to a non-ESP32 device on the same port.
                raw_ident = self._cmd("IDENT")
                if not raw_ident:
                    raise RuntimeError(
                        f"No IDENT response from {port}. "
                        "This port may not be an ESP32 running "
                        "SanjINSIGHT I/O firmware."
                    )
                _is_ascii = all(
                    32 <= ord(c) < 127 or c in '\r\n\t' for c in raw_ident
                )
                if not _is_ascii or not raw_ident.startswith("IDENT"):
                    raise RuntimeError(
                        f"Unexpected response from {port}: "
                        f"{raw_ident!r:.60}  — not an ESP32."
                    )

                self._firmware_version = (
                    raw_ident[6:].strip()
                    if raw_ident.startswith("IDENT ")
                    else raw_ident
                )
                self._connected = True
                self._port = port
                if port != saved_port:
                    log.info("ESP32: saved port %s failed, found ESP32 "
                             "on %s instead", saved_port, port)
                log.info("ESP32 connected on %s  (firmware: %s)",
                         port, self._firmware_version)
                return

            except Exception as exc:
                last_error = exc
                log.info("ESP32: port %s rejected — %s", port, exc)
                if self._serial is not None:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None

        from hardware.hw_debug_log import connect_fail
        connect_fail(log, port=saved_port or "(auto)", error=last_error,
                     context={"baud": self._baud, "timeout": self._timeout,
                              "candidates_tried": candidates})
        raise RuntimeError(
            f"Failed to connect to ESP32 on "
            f"{', '.join(candidates)}: {last_error}"
        )

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
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
        log.info("ESP32 disconnected")

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
            raise RuntimeError(f"ESP32 LED select failed: {resp}")
        self._active_led = channel
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
            raise RuntimeError(f"ESP32 set_pin failed: {resp}")

    def get_pin(self, pin: int) -> bool:
        resp = self._cmd(f"READ {pin}")
        if resp and resp.startswith("PIN"):
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
                _tx(log, raw, label="ESP32")
                self._serial.write(raw)
                self._serial.flush()
                with _timed(log, f"ESP32 '{command}' response"):
                    line = self._serial.readline().decode(
                        "ascii", errors="replace").strip()
                _rx(log, line, label="ESP32")
                return line
            except Exception as exc:
                log.warning("ESP32 serial error on '%s': %s", command, exc)
                return ""

    @staticmethod
    def _auto_detect_port() -> Optional[str]:
        """Scan serial ports for an ESP32 board (returns first match)."""
        ports = Esp32Driver._auto_detect_ports()
        return ports[0] if ports else None

    @staticmethod
    def _auto_detect_ports() -> list[str]:
        """Return ALL serial ports that could be an ESP32 board."""
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return []

        # Known ESP32 VID:PID pairs
        _ESP32_VIDS_PIDS = {
            (0x10C4, 0xEA60),  # Silicon Labs CP210x
            (0x303A, 0x1001),  # Espressif native USB (ESP32-S2/S3/C3)
            (0x2341, 0x0070),  # Arduino Nano ESP32 (u-blox NORA-W106)
        }

        results: list[str] = []
        for port_info in comports():
            vid = port_info.vid
            pid = port_info.pid
            if vid is not None and pid is not None:
                if (vid, pid) in _ESP32_VIDS_PIDS:
                    log.info("Auto-detected candidate ESP32 port %s "
                             "(VID=%04X PID=%04X, desc=%s)",
                             port_info.device, vid, pid,
                             port_info.description)
                    results.append(port_info.device)
                    continue

            # Fallback: match description strings
            desc = (port_info.description or "").lower()
            if any(s in desc for s in ("cp210", "esp32", "espressif",
                                       "nano esp32")):
                log.info("Auto-detected candidate ESP32 port %s (desc=%s)",
                         port_info.device, port_info.description)
                results.append(port_info.device)

        return results

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
