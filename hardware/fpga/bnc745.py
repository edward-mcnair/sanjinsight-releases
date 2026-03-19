"""
hardware/fpga/bnc745.py

Driver for the Berkeley Nucleonics Corporation (BNC) Model 745
Digital Delay / Pulse Generator.

In the Microsanj PT-100B test setup the BNC 745 replaces the NI-9637 FPGA
as the precision timing source.  It generates multi-channel TTL/NIM pulses
with sub-nanosecond jitter to synchronise the bias stimulus and the camera
trigger.

Architecture
------------
  SanjINSIGHT ──► Bnc745Driver (FpgaDriver) ──► BNC 745 ──► Camera / AMCAD BILT
                    VISA / GPIB / USB / Serial

LabVIEW heritage
----------------
The PT-100B LabVIEW VIs (PT-100B_Set_Width.vi, PT-100B_Set_Timing.vi, etc.)
were built on top of the "MOD745" LabVIEW driver library from BNC.
This Python driver replicates the same SCPI commands over a VISA session,
making the BNC 745 usable without LabVIEW or the MOD745 DLL.

Channel mapping (default)
--------------------------
  T0  — internal master clock (sets period / frequency)
  Ch1 — camera trigger output
  Ch2 — auxiliary trigger (e.g. bias-enable gate)
  Ch3-8 — available; not driven by this driver by default

FpgaDriver mapping
------------------
``start()``              — enable Ch1 + Ch2 outputs (continuous mode)
``stop()``               — disable all outputs
``set_frequency(hz)``    — set T0 period = 1 / hz
``set_duty_cycle(f)``    — set Ch1 pulse width = f × period
``set_trigger_mode()``   — switch between CONTINUOUS (T0 free-runs) and
                           SINGLE_SHOT (T0 fires once per software trigger)
``arm_trigger()``        — issue one software trigger (*TRG)
``set_pulse_duration()`` — set Ch1 pulse width directly in µs
``get_status()``         — returns FpgaStatus snapshot

Config keys (under hardware.fpga):
    address:          "GPIB::12"          VISA resource string
                      "USB0::0x0A33::..."  USB (copy from NI MAX)
                      "ASRL/dev/ttyUSB0"  Serial (Linux/macOS)
    freq_hz:          1000.0              initial frequency (Hz)
    duty_cycle:       0.5                 initial Ch1 duty cycle (0.0-1.0)
    camera_channel:   1                   BNC channel driving camera trigger
    aux_channel:      2                   BNC channel for auxiliary gate
    output_amplitude: 3.3                 TTL output amplitude in V (3.3 or 5.0)
    timeout_ms:       5000                VISA timeout in ms

Notes
-----
- Requires pyvisa + a VISA backend (NI-VISA, pyvisa-py, or Keysight VISA).
  Install:  pip install pyvisa pyvisa-py
- Serial interface also requires pyserial:  pip install pyserial
- On Windows with NI-VISA, the USB device appears as USB0::0x0A33::0x0021::...
  (BNC VID=0x0A33).
"""

import logging
import time

from .base import FpgaDriver, FpgaStatus, FpgaTriggerMode

log = logging.getLogger(__name__)

# BNC 745 USB vendor ID (used for device_registry matching)
_BNC_USB_VID = 0x0A33
_BNC_USB_PID = 0x0021   # BNC 745 OEM product ID

# SCPI command templates
_CMD_PERIOD  = ":PULS0:PER {period:.9e}"    # T0 period in seconds
_CMD_WIDTH   = ":PULS{ch}:WIDT {width:.9e}" # channel pulse width in seconds
_CMD_DELAY   = ":PULS{ch}:DEL {delay:.9e}"  # channel delay in seconds
_CMD_POL     = ":PULS{ch}:POL {pol}"        # NORM or INV
_CMD_OUTP    = ":OUTP{ch} {state}"          # ON or OFF
_CMD_AMPL    = ":PULS{ch}:OUTP:AMPL {v:.2f}" # output amplitude in V
_CMD_TMODE   = ":PULS0:GATE:MOD {mode}"     # CONT or SING (trigger mode)
_CMD_TSRC    = ":PULS0:TRIG:INP:MOD {src}"  # INT (free-run) or BNC (external)


class Bnc745Driver(FpgaDriver):
    """
    BNC Model 745 Digital Delay Generator — FpgaDriver implementation.

    Communicates via VISA (GPIB, USB, or Serial) using pyvisa.
    Implements continuous and single-shot trigger modes for thermoreflectance
    lock-in acquisition and transient-mode capture.
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import pyvisa  # noqa: F401
        except ImportError:
            issues.append(
                "pyvisa not found — BNC 745 driver unavailable.\n"
                "Install it with:  pip install pyvisa pyvisa-py\n"
                "For GPIB on Windows also install NI-VISA from ni.com.\n"
                "For USB/Serial without NI-VISA:  pip install pyvisa-py pyserial"
            )
        return (len(issues) == 0, issues)

    # ---------------------------------------------------------------- #
    #  Construction                                                     #
    # ---------------------------------------------------------------- #

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._address    = cfg.get("address", "GPIB::12")
        self._freq_hz    = float(cfg.get("freq_hz",    1000.0))
        self._duty       = float(cfg.get("duty_cycle", 0.5))
        self._cam_ch     = int(cfg.get("camera_channel",   1))
        self._aux_ch     = int(cfg.get("aux_channel",      2))
        self._amplitude  = float(cfg.get("output_amplitude", 3.3))
        self._timeout_ms = int(cfg.get("timeout_ms", 5000))
        self._rm         = None
        self._inst       = None
        self._trigger_mode = FpgaTriggerMode.CONTINUOUS
        self._trigger_armed = False
        self._running    = False
        self._frame_count = 0

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def open(self) -> None:
        try:
            import pyvisa
        except ImportError:
            raise RuntimeError(
                "pyvisa is not installed.\n\n"
                "The BNC 745 driver requires PyVISA to communicate over "
                "GPIB, USB, or Serial.\n\n"
                "Install it with:\n"
                "    pip install pyvisa pyvisa-py\n\n"
                "For GPIB on Windows, NI-VISA is recommended:\n"
                "    https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html"
            )
        try:
            self._rm   = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = self._timeout_ms
            # Serial instruments need termination characters
            if "ASRL" in self._address.upper():
                self._inst.read_termination  = "\n"
                self._inst.write_termination = "\n"
                self._inst.baud_rate = 57600

            idn = self._query("*IDN?")
            if "745" not in idn and "BNC" not in idn.upper():
                log.warning(
                    "BNC 745: unexpected IDN response '%s' — "
                    "check address and instrument type.", idn)
            log.info("BNC 745 connected: %s", idn)

            self._reset_instrument()
            self._configure_outputs()
            self._open = True

        except Exception as exc:
            self._close_visa()
            raise RuntimeError(
                f"BNC 745 open failed at '{self._address}': {exc}\n"
                f"Verify the VISA address in NI MAX (Windows) or "
                f"'python -c \"import pyvisa; rm=pyvisa.ResourceManager(); "
                f"print(rm.list_resources())\"' (macOS/Linux)."
            ) from exc

    def close(self) -> None:
        if self._open:
            try:
                self.stop()
            except Exception:
                pass
        self._close_visa()
        self._open = False

    def _close_visa(self):
        try:
            if self._inst:
                self._inst.close()
            if self._rm:
                self._rm.close()
        except Exception:
            pass
        self._inst = None
        self._rm   = None

    # ---------------------------------------------------------------- #
    #  Instrument initialisation                                        #
    # ---------------------------------------------------------------- #

    def _reset_instrument(self):
        self._write("*RST")
        time.sleep(0.3)
        self._write("*CLS")

    def _configure_outputs(self):
        """Apply initial frequency, duty cycle, and amplitude to both channels."""
        period = 1.0 / self._freq_hz
        self._write(_CMD_PERIOD.format(period=period))

        width = period * self._duty
        for ch in (self._cam_ch, self._aux_ch):
            self._write(_CMD_WIDTH.format(ch=ch, width=width))
            self._write(_CMD_DELAY.format(ch=ch, delay=0.0))
            self._write(_CMD_POL.format(ch=ch, pol="NORM"))
            self._write(_CMD_AMPL.format(ch=ch, v=self._amplitude))
            # Keep outputs OFF until start() is called
            self._write(_CMD_OUTP.format(ch=ch, state="OFF"))

        # Start in continuous (free-running) mode
        self._write(_CMD_TMODE.format(mode="CONT"))
        self._write(_CMD_TSRC.format(src="INT"))

    # ---------------------------------------------------------------- #
    #  FpgaDriver control                                               #
    # ---------------------------------------------------------------- #

    def start(self) -> None:
        """Enable camera and aux outputs; begin continuous pulsing."""
        self._write(_CMD_OUTP.format(ch=self._cam_ch, state="ON"))
        self._write(_CMD_OUTP.format(ch=self._aux_ch, state="ON"))
        self._running = True

    def stop(self) -> None:
        """Disable all outputs."""
        for ch in range(1, 9):   # channels 1-8
            try:
                self._write(_CMD_OUTP.format(ch=ch, state="OFF"))
            except Exception:
                pass
        self._running       = False
        self._trigger_armed = False

    def set_frequency(self, hz: float) -> None:
        """Set T0 repetition frequency in Hz (period = 1/hz)."""
        if hz <= 0:
            raise ValueError(f"Frequency must be > 0 Hz, got {hz}")
        self._freq_hz = hz
        period = 1.0 / hz
        self._write(_CMD_PERIOD.format(period=period))
        # Update channel widths to preserve duty cycle
        self._apply_duty_cycle(self._duty)

    def set_duty_cycle(self, fraction: float) -> None:
        """
        Set camera-channel duty cycle (0.0–1.0).
        Computes pulse width = fraction × period.
        """
        fraction = max(0.001, min(0.999, fraction))
        self._duty = fraction
        self._apply_duty_cycle(fraction)

    def _apply_duty_cycle(self, fraction: float):
        width = (1.0 / self._freq_hz) * fraction
        self._write(_CMD_WIDTH.format(ch=self._cam_ch, width=width))

    # ---------------------------------------------------------------- #
    #  Trigger / transient mode                                         #
    # ---------------------------------------------------------------- #

    def supports_trigger_mode(self) -> bool:
        return True

    def set_trigger_mode(self, mode: FpgaTriggerMode) -> None:
        """
        Switch between continuous and single-shot trigger modes.

        CONTINUOUS  — T0 free-runs at the configured frequency; outputs pulse
                      continuously (normal lock-in operation).
        SINGLE_SHOT — T0 is halted; one pulse fires per ``arm_trigger()`` call.
        """
        self._trigger_mode = mode
        if mode == FpgaTriggerMode.CONTINUOUS:
            self._write(_CMD_TMODE.format(mode="CONT"))
            self._write(_CMD_TSRC.format(src="INT"))
            log.debug("BNC 745: continuous mode")
        else:  # SINGLE_SHOT
            self._write(_CMD_TMODE.format(mode="SING"))
            self._write(_CMD_TSRC.format(src="INT"))  # software trigger via *TRG
            log.debug("BNC 745: single-shot mode")
        self._trigger_armed = False

    def arm_trigger(self) -> None:
        """
        Fire one single-shot pulse via software trigger.
        Only valid in SINGLE_SHOT mode.
        """
        if self._trigger_mode != FpgaTriggerMode.SINGLE_SHOT:
            raise RuntimeError(
                "arm_trigger() called in CONTINUOUS mode. "
                "Call set_trigger_mode(SINGLE_SHOT) first."
            )
        self._trigger_armed = True
        self._write("*TRG")
        self._frame_count += 1
        # The armed flag resets automatically after the pulse completes.
        # We use a short delay then clear it; the actual pulse duration is µs-ms
        # so 10 ms is a safe margin for polling-based callers.
        # For tighter synchronisation use the BNC 745 DONE output as a GPIO.
        time.sleep(0.01)
        self._trigger_armed = False

    def set_pulse_duration(self, duration_us: float) -> None:
        """
        Set the camera-channel pulse width in microseconds.
        Overrides any duty-cycle derived width.
        """
        width_s = duration_us * 1e-6
        self._write(_CMD_WIDTH.format(ch=self._cam_ch, width=width_s))
        log.debug("BNC 745 Ch%d pulse width set to %.2f µs",
                  self._cam_ch, duration_us)

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> FpgaStatus:
        try:
            period_raw = self._query(":PULS0:PER?")
            period_s   = float(period_raw)
            freq_hz    = 1.0 / period_s if period_s > 0 else 0.0

            width_raw  = self._query(f":PULS{self._cam_ch}:WIDT?")
            width_s    = float(width_raw)
            duty       = (width_s / period_s) if period_s > 0 else 0.0

            return FpgaStatus(
                running       = self._running,
                frame_count   = self._frame_count,
                stimulus_on   = self._running,
                freq_hz       = freq_hz,
                duty_cycle    = duty,
                sync_locked   = True,
                trigger_mode  = self._trigger_mode,
                trigger_armed = self._trigger_armed,
            )
        except Exception as exc:
            log.warning("BNC 745 get_status failed: %s", exc)
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
        # BNC 745: 0.001 Hz to 10 MHz (model-dependent)
        return (0.001, 10_000_000.0)

    # ---------------------------------------------------------------- #
    #  Internal VISA helpers                                            #
    # ---------------------------------------------------------------- #

    def _write(self, cmd: str) -> None:
        if self._inst is None:
            raise RuntimeError("BNC 745 is not open.")
        self._inst.write(cmd)
        log.debug("BNC745 ← %s", cmd)

    def _query(self, cmd: str) -> str:
        if self._inst is None:
            raise RuntimeError("BNC 745 is not open.")
        resp = self._inst.query(cmd).strip()
        log.debug("BNC745 → %s", resp)
        return resp

    def __repr__(self):
        return (
            f"<Bnc745Driver address='{self._address}' "
            f"open={self._open} freq={self._freq_hz:.1f}Hz>"
        )
