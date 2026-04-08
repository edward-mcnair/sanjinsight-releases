"""
hardware/fpga/tdg7.py

Driver for the Fastlaser Tech TDG-VII 7-channel picosecond delay generator
(also sold as the Microsanj PT-100 timing module).

The TDG-VII is a USB-serial instrument built around an STM32 MCU.  It provides
seven independent delay channels with picosecond-class resolution:

  Ch 1–4  — 0 to 999,999.99 ns delay, 0.01 ns resolution
  Ch 5–7  — 0 to 9,999,999.9 ns delay, 0.1 ns resolution

Each channel has configurable pulse width, output mode (TTL/NIM/2×TTL/2×NIM),
and an independent gate (enable/disable).

Architecture
------------
  SanjINSIGHT ──► Tdg7Driver (FpgaDriver) ──► TDG-VII ──► Camera / DUT / Bias
                    USB-serial (STM32 VCP)

FpgaDriver mapping
------------------
``start()``              — enable all gated channels (ungate)
``stop()``               — gate (disable) all channels
``set_frequency(hz)``    — set master frequency (all channels share one clock)
``set_duty_cycle(f)``    — set Ch1 pulse width = f × period
``set_trigger_mode()``   — TDG-VII supports external trigger via TrigSel
``arm_trigger()``        — not applicable (no software trigger)
``set_pulse_duration()`` — set Ch1 pulse width directly in µs
``get_status()``         — returns FpgaStatus snapshot

Extended methods (TDG-VII-specific)
-----------------------------------
``set_channel_delay(ch, ns)``     — per-channel delay in nanoseconds
``set_channel_width(ch, ns)``     — per-channel pulse width in nanoseconds
``set_channel_output(ch, mode)``  — output mode (TTL / NIM / 2×TTL / 2×NIM)
``set_channel_gate(ch, on)``      — enable/disable individual channel
``set_trigger_source(src)``       — internal / external trigger
``set_rf_output(enabled)``        — enable/disable RF reference output
``read_frequency_counter()``      — read built-in frequency counter

Serial protocol (ASCII line-based, \\n terminated)
---------------------------------------------------
Commands are sent as ASCII strings terminated by \\n.  For reliability,
each command is sent twice (firmware quirk — the STM32 UART sometimes
drops the first byte after idle).  Responses are line-based but most
set-commands do not echo a response.

Command reference:
    D<ch> <value>         Set delay — value is integer (0.01 ns units ch1-4,
                          0.1 ns units ch5-7)
    W<ch> <value>         Set pulse width (same units as delay)
    F <value>             Set frequency in Hz (integer)
    ChOut<ch> <mode>      Output mode: 0=TTL, 1=NIM, 2=2×TTL, 3=2×NIM
    Gtd<ch> <0|1>         Gate channel (1=enabled, 0=disabled)
    FrC                   Read frequency counter → "<value> Hz"
    RfOut <0|1>           Enable/disable RF reference output
    TrigSel <0|1|2>       Trigger source: 0=internal, 1=ext rising, 2=ext falling
    RfSel <0|1>           RF source: 0=internal, 1=external
    ExtRfV <value>        External RF voltage threshold (mV)
    LockKeyIn             Lock front-panel keys (remote mode)
    UnlockKeyIn           Unlock front-panel keys

Config keys (under hardware.fpga):
    driver:       "tdg7"
    port:         "COM5" or "/dev/ttyACM0"   (auto-detected if omitted)
    baud:         115200
    timeout:      2.0
    freq_hz:      1000.0         initial frequency (Hz)
    duty_cycle:   0.5            initial Ch1 duty cycle (0.0–1.0)
    camera_channel: 1            channel used for camera trigger
    aux_channel:    2            channel used for bias gate

Notes
-----
- USB VID:PID = 0483:5740 (STM32 Virtual COM Port)
- Requires pyserial:  pip install pyserial
- Commands are sent twice with a 50 ms gap for reliability.
- Inter-command delay of 50 ms minimum (firmware processing time).
- The PT-100 and TDG-VII are the same hardware.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import IntEnum
from typing import Optional

from .base import FpgaDriver, FpgaStatus, FpgaTriggerMode

log = logging.getLogger(__name__)

# STM32 VCP USB identifiers
_STM32_VCP_VID = 0x0483
_STM32_VCP_PID = 0x5740

# Delay resolution per channel group (in nanoseconds per count)
_RES_CH1_4 = 0.01   # 10 ps
_RES_CH5_7 = 0.1    # 100 ps

# Maximum delay per channel group (nanoseconds)
_MAX_DELAY_CH1_4 = 999_999.99
_MAX_DELAY_CH5_7 = 9_999_999.9

# Maximum width per channel group (nanoseconds)
_MAX_WIDTH_CH1_4 = 999_999.99
_MAX_WIDTH_CH5_7 = 9_999_999.9

# Inter-command delay (seconds)
_CMD_GAP = 0.05

# Number of channels
_NUM_CHANNELS = 7


class OutputMode(IntEnum):
    """TDG-VII channel output modes."""
    TTL       = 0
    NIM       = 1
    TTL_DUAL  = 2   # 2× TTL (doubled output)
    NIM_DUAL  = 3   # 2× NIM (doubled output)


class TriggerSource(IntEnum):
    """TDG-VII trigger source selection."""
    INTERNAL      = 0
    EXT_RISING    = 1
    EXT_FALLING   = 2


class Tdg7Driver(FpgaDriver):
    """
    Fastlaser Tech TDG-VII / Microsanj PT-100 picosecond delay generator.

    Implements the FpgaDriver interface over USB-serial (STM32 VCP).
    Provides 7 independent delay channels with per-channel width, delay,
    output mode, and gate control.
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import serial  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial not found — TDG-VII driver unavailable.\n"
                "Install it with:  pip install pyserial"
            )
        return (len(issues) == 0, issues)

    # ---------------------------------------------------------------- #
    #  Construction                                                     #
    # ---------------------------------------------------------------- #

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port: Optional[str] = cfg.get("port")
        self._baud: int = int(cfg.get("baud", 115200))
        self._timeout: float = float(cfg.get("timeout", 2.0))
        self._freq_hz: float = float(cfg.get("freq_hz", 1000.0))
        self._duty: float = float(cfg.get("duty_cycle", 0.5))
        self._cam_ch: int = int(cfg.get("camera_channel", 1))
        self._aux_ch: int = int(cfg.get("aux_channel", 2))
        self._serial = None
        self._lock = threading.Lock()
        self._running = False
        self._trigger_mode = FpgaTriggerMode.CONTINUOUS
        self._trigger_source = TriggerSource.INTERNAL
        self._frame_count = 0
        # Per-channel state (1-indexed, index 0 unused)
        self._delays = [0.0] * (_NUM_CHANNELS + 1)   # ns
        self._widths = [0.0] * (_NUM_CHANNELS + 1)    # ns
        self._gates  = [False] * (_NUM_CHANNELS + 1)
        self._modes  = [OutputMode.TTL] * (_NUM_CHANNELS + 1)

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def open(self) -> None:
        import serial as _serial

        port = self._port
        if not port:
            port = self._auto_detect_port()
            if not port:
                raise RuntimeError(
                    "TDG-VII / PT-100 not found on any serial port.\n"
                    "Specify 'port' in config.yaml or connect the device.\n"
                    "The TDG-VII uses an STM32 VCP (VID:PID 0483:5740).")

        try:
            self._serial = _serial.Serial(
                port=port,
                baudrate=self._baud,
                timeout=self._timeout,
            )
            time.sleep(0.5)  # STM32 VCP settle time
            self._serial.reset_input_buffer()

            # Lock front panel for remote operation
            self._send("LockKeyIn")

            # Apply initial configuration
            self._send(f"F {int(self._freq_hz)}")
            self._send(f"TrigSel {int(self._trigger_source)}")

            # Set initial duty cycle on camera channel
            period_ns = 1e9 / self._freq_hz if self._freq_hz > 0 else 1e6
            width_ns = period_ns * self._duty
            self._set_width_raw(self._cam_ch, width_ns)

            # Gate all channels off until start()
            for ch in range(1, _NUM_CHANNELS + 1):
                self._send(f"Gtd{ch} 0")
                self._gates[ch] = False

            self._port = port
            self._open = True
            log.info("TDG-VII connected on %s (freq=%.0f Hz)", port, self._freq_hz)

        except Exception as exc:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            from hardware.hw_debug_log import connect_fail
            connect_fail(log, port=port, error=exc, context={
                "baud": self._baud, "timeout": self._timeout,
            })
            raise RuntimeError(
                f"TDG-VII open failed on {port}: {exc}\n"
                f"Check that the STM32 VCP driver is installed "
                f"(Windows: STM32 Virtual COM Port driver)."
            ) from exc

    def close(self) -> None:
        if self._open:
            try:
                self.stop()
            except Exception:
                pass
            try:
                self._send("UnlockKeyIn")
            except Exception:
                pass
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._open = False
        log.info("TDG-VII disconnected")

    # ---------------------------------------------------------------- #
    #  FpgaDriver control                                               #
    # ---------------------------------------------------------------- #

    def start(self) -> None:
        """Enable camera and aux channel outputs (ungate)."""
        self.set_channel_gate(self._cam_ch, True)
        self.set_channel_gate(self._aux_ch, True)
        self._running = True

    def stop(self) -> None:
        """Gate (disable) all channels."""
        for ch in range(1, _NUM_CHANNELS + 1):
            try:
                self._send(f"Gtd{ch} 0")
                self._gates[ch] = False
            except Exception:
                pass
        self._running = False

    def set_frequency(self, hz: float) -> None:
        """Set the master clock frequency in Hz (shared by all channels)."""
        if hz <= 0:
            raise ValueError(f"Frequency must be > 0 Hz, got {hz}")
        old_freq = self._freq_hz
        self._freq_hz = hz
        self._send(f"F {int(hz)}")
        # Update camera channel width to preserve duty cycle
        if old_freq > 0:
            period_ns = 1e9 / hz
            width_ns = period_ns * self._duty
            self._set_width_raw(self._cam_ch, width_ns)

    def set_duty_cycle(self, fraction: float) -> None:
        """Set camera-channel duty cycle (0.0–1.0)."""
        fraction = max(0.001, min(0.999, fraction))
        self._duty = fraction
        if self._freq_hz > 0:
            period_ns = 1e9 / self._freq_hz
            width_ns = period_ns * fraction
            self._set_width_raw(self._cam_ch, width_ns)

    def set_stimulus(self, on: bool) -> None:
        """Enable or disable stimulus by gating the camera channel."""
        self.set_channel_gate(self._cam_ch, on)

    # ---------------------------------------------------------------- #
    #  Trigger / transient mode                                         #
    # ---------------------------------------------------------------- #

    def supports_trigger_mode(self) -> bool:
        return True

    def set_trigger_mode(self, mode: FpgaTriggerMode) -> None:
        """
        Switch between continuous and external-trigger modes.

        CONTINUOUS  — internal trigger, free-running at set frequency.
        SINGLE_SHOT — external trigger (rising edge); frequency command
                      is ignored, pulses fire on external trigger input.
        """
        self._trigger_mode = mode
        if mode == FpgaTriggerMode.CONTINUOUS:
            self._trigger_source = TriggerSource.INTERNAL
            self._send("TrigSel 0")
            log.debug("TDG-VII: continuous mode (internal trigger)")
        else:
            self._trigger_source = TriggerSource.EXT_RISING
            self._send("TrigSel 1")
            log.debug("TDG-VII: single-shot mode (external trigger)")

    def arm_trigger(self) -> None:
        """
        The TDG-VII does not support software-triggered single-shot.
        In SINGLE_SHOT mode it fires on external trigger input.
        This method increments the frame counter for bookkeeping.
        """
        if self._trigger_mode != FpgaTriggerMode.SINGLE_SHOT:
            raise RuntimeError(
                "arm_trigger() called in CONTINUOUS mode. "
                "Call set_trigger_mode(SINGLE_SHOT) first.")
        self._frame_count += 1

    def set_pulse_duration(self, duration_us: float) -> None:
        """Set camera-channel pulse width in microseconds."""
        width_ns = duration_us * 1000.0
        self._set_width_raw(self._cam_ch, width_ns)
        log.debug("TDG-VII Ch%d pulse width set to %.2f µs",
                  self._cam_ch, duration_us)

    # ---------------------------------------------------------------- #
    #  TDG-VII extended methods                                         #
    # ---------------------------------------------------------------- #

    def set_channel_delay(self, ch: int, ns: float) -> None:
        """Set delay for a channel in nanoseconds."""
        self._validate_channel(ch)
        max_ns = _MAX_DELAY_CH1_4 if ch <= 4 else _MAX_DELAY_CH5_7
        if ns < 0 or ns > max_ns:
            raise ValueError(
                f"Ch{ch} delay {ns} ns out of range (0–{max_ns} ns)")
        res = _RES_CH1_4 if ch <= 4 else _RES_CH5_7
        counts = int(round(ns / res))
        self._send(f"D{ch} {counts}")
        self._delays[ch] = counts * res

    def set_channel_width(self, ch: int, ns: float) -> None:
        """Set pulse width for a channel in nanoseconds."""
        self._validate_channel(ch)
        self._set_width_raw(ch, ns)

    def set_channel_output(self, ch: int, mode: OutputMode) -> None:
        """Set output mode for a channel (TTL / NIM / 2×TTL / 2×NIM)."""
        self._validate_channel(ch)
        self._send(f"ChOut{ch} {int(mode)}")
        self._modes[ch] = mode

    def set_channel_gate(self, ch: int, enabled: bool) -> None:
        """Enable or disable a channel's output gate."""
        self._validate_channel(ch)
        val = 1 if enabled else 0
        self._send(f"Gtd{ch} {val}")
        self._gates[ch] = enabled

    def set_trigger_source(self, source: TriggerSource) -> None:
        """Set trigger source (internal / external rising / external falling)."""
        self._trigger_source = source
        self._send(f"TrigSel {int(source)}")

    def set_rf_output(self, enabled: bool) -> None:
        """Enable or disable the RF reference output."""
        self._send(f"RfOut {1 if enabled else 0}")

    def set_rf_source(self, external: bool) -> None:
        """Select RF source: internal (False) or external (True)."""
        self._send(f"RfSel {1 if external else 0}")

    def set_ext_rf_threshold(self, mv: int) -> None:
        """Set external RF input voltage threshold in millivolts."""
        self._send(f"ExtRfV {int(mv)}")

    def read_frequency_counter(self) -> float:
        """Read the built-in frequency counter. Returns Hz."""
        resp = self._query("FrC")
        if resp:
            # Response format: "<value> Hz" or just "<value>"
            parts = resp.strip().split()
            if parts:
                try:
                    return float(parts[0])
                except ValueError:
                    log.warning("TDG-VII: could not parse freq counter: %r", resp)
        return 0.0

    def lock_front_panel(self) -> None:
        """Lock front-panel keys (remote operation mode)."""
        self._send("LockKeyIn")

    def unlock_front_panel(self) -> None:
        """Unlock front-panel keys."""
        self._send("UnlockKeyIn")

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> FpgaStatus:
        """Return current status snapshot."""
        # The TDG-VII doesn't have a STATUS query — we track state locally
        # and optionally read the frequency counter for verification.
        try:
            measured_freq = 0.0
            if self._running:
                measured_freq = self.read_frequency_counter()

            return FpgaStatus(
                running       = self._running,
                frame_count   = self._frame_count,
                stimulus_on   = self._gates[self._cam_ch],
                freq_hz       = measured_freq if measured_freq > 0 else self._freq_hz,
                duty_cycle    = self._duty,
                sync_locked   = True,
                trigger_mode  = self._trigger_mode,
                trigger_armed = False,
            )
        except Exception as exc:
            log.warning("TDG-VII get_status failed: %s", exc)
            return FpgaStatus(
                running      = self._running,
                freq_hz      = self._freq_hz,
                duty_cycle   = self._duty,
                trigger_mode = self._trigger_mode,
                error        = str(exc),
            )

    # ---------------------------------------------------------------- #
    #  Introspection                                                    #
    # ---------------------------------------------------------------- #

    def frequency_range(self) -> tuple:
        # TDG-VII: integer Hz, typically 1 Hz to ~25 MHz
        return (1.0, 25_000_000.0)

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                 #
    # ---------------------------------------------------------------- #

    def _validate_channel(self, ch: int) -> None:
        if ch < 1 or ch > _NUM_CHANNELS:
            raise ValueError(
                f"Channel {ch} out of range (1–{_NUM_CHANNELS})")

    def _set_width_raw(self, ch: int, ns: float) -> None:
        """Set channel width in nanoseconds (internal)."""
        max_ns = _MAX_WIDTH_CH1_4 if ch <= 4 else _MAX_WIDTH_CH5_7
        ns = max(0.0, min(ns, max_ns))
        res = _RES_CH1_4 if ch <= 4 else _RES_CH5_7
        counts = int(round(ns / res))
        self._send(f"W{ch} {counts}")
        self._widths[ch] = counts * res

    def _send(self, command: str) -> None:
        """
        Send a command to the TDG-VII.

        Commands are sent twice with a short gap — the STM32 firmware
        sometimes drops the first byte after an idle period.
        """
        with self._lock:
            if self._serial is None:
                return
            try:
                raw = (command + "\n").encode("ascii")
                log.debug("TDG7 ← %s", command)
                self._serial.write(raw)
                time.sleep(_CMD_GAP)
                # Send again for reliability
                self._serial.write(raw)
                self._serial.flush()
                time.sleep(_CMD_GAP)
            except Exception as exc:
                log.warning("TDG-VII serial error on '%s': %s", command, exc)

    def _query(self, command: str) -> str:
        """Send a command and read one response line."""
        with self._lock:
            if self._serial is None:
                return ""
            try:
                raw = (command + "\n").encode("ascii")
                self._serial.reset_input_buffer()
                log.debug("TDG7 ← %s", command)
                self._serial.write(raw)
                self._serial.flush()
                time.sleep(_CMD_GAP)
                line = self._serial.readline().decode("ascii", errors="replace").strip()
                log.debug("TDG7 → %s", line)
                return line
            except Exception as exc:
                log.warning("TDG-VII serial error on query '%s': %s", command, exc)
                return ""

    @staticmethod
    def _auto_detect_port() -> Optional[str]:
        """Scan serial ports for an STM32 VCP (TDG-VII / PT-100)."""
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return None

        for port_info in comports():
            vid = port_info.vid
            pid = port_info.pid
            if vid == _STM32_VCP_VID and pid == _STM32_VCP_PID:
                log.info("Auto-detected TDG-VII on %s (VID=%04X PID=%04X)",
                         port_info.device, vid, pid)
                return port_info.device

            # Fallback: match description strings
            desc = (port_info.description or "").lower()
            if any(s in desc for s in ("stm32", "stmicroelectronics",
                                       "tdg", "pt-100", "fastlaser")):
                log.info("Auto-detected TDG-VII on %s (desc=%s)",
                         port_info.device, port_info.description)
                return port_info.device

        return None

    def __repr__(self):
        return (
            f"<Tdg7Driver port='{self._port}' "
            f"open={self._open} freq={self._freq_hz:.0f}Hz>")
