"""
hardware/fpga/ni9637.py

Driver for NI sbRIO-9637 FPGA module via the nifpga Python library.

Requires:
  - NI-RIO drivers installed (Windows)
  - pip install nifpga
  - Compiled .lvbitx bitfile (bundled in installer at firmware/ez500_fpga.lvbitx)

Config keys (under hardware.fpga):
    bitfile:       "firmware/ez500_fpga.lvbitx"
    resource:      "rio://169.254.252.165/RIO0"
    reset_on_open: true

FPGA register names must match those compiled into the bitfile.
Register map was extracted from: ez500firmware_FPGATarget_FPGACODE_wPlAxJTjkzE.lvbitx
Source VI: FPGA_CODE.vi — BitfileVersion 4.0

Register reference (from bitfile):
─────────────────────────────────────────────────────────────────────────
  CONTROLS (write):
    Period(us)         U32      Stimulus period in microseconds
    LED Phase          U32      LED phase offset (µs ticks)
    LED Time ON        U32      LED on-duration per cycle
    Dev Time ON        U32      Device on-duration per cycle (stimulus)
    Dev Phase          U32      Device phase offset
    Dev Phase 2        U32      Device second phase offset
    Exposure Time      U32      Camera exposure window (µs ticks)
    Phase Select       Boolean  Select Dev Phase vs Dev Phase 2
    LED Pulsed Phase   U32      LED pulsed illumination phase
    LED Pulse Time     U32      LED pulsed illumination on-time
    Voltage Out        FXP20    Main voltage output (−16 V to +16 V)
    Aux Voltage        FXP20    Auxiliary voltage output (−16 V to +16 V)
    Output Vout        Boolean  Enable main voltage DAC output
    Output Vaux        Boolean  Enable auxiliary voltage DAC output
    SetVout            Boolean  Latch/apply main voltage setting
    SetVaux            Boolean  Latch/apply auxiliary voltage setting
    Vo Lim             FXP20    Main voltage limit (−16 V to +16 V)
    Va Lim             FXP20    Aux voltage limit (−16 V to +16 V)
    Set I Lim          Boolean  Apply current limit
    High Range         Boolean  High voltage range select
    Output SSR         Boolean  Solid-state relay output (stimulus enable)
    EnabSynch          Boolean  Enable synchronisation to ext. clock
    SynchPhase         U32      Synchronisation phase offset
    SampRate           U32      Analog input sample rate divisor
    GetV               Boolean  Trigger analog voltage readback
    IR Frame Trig      Boolean  IR camera frame trigger enable
    Trig Dir (F=out)   Boolean  Trigger direction (False = output)
    EN_TRANS           Boolean  Enable transient capture mode
    Event Trig         Boolean  Fire event trigger
    Event Time(us)     U32      Event pulse duration (µs)
    Event Phase(us)    U32      Event phase delay (µs)
    Event Source       I16      Event trigger source selector
    ArmEvent           Boolean  Arm event trigger system

  INDICATORS (read-only):
    AI0 … AI3          Array[115] of SGL   Analog input channels
    Trigger In         Boolean              External trigger state
    Version Num        U32                  Firmware version number
─────────────────────────────────────────────────────────────────────────
"""

from .base import FpgaDriver, FpgaStatus, FpgaTriggerMode

import logging
log = logging.getLogger(__name__)


# ── Register name constants (must match compiled bitfile) ────────────────
# Timing
_REG_PERIOD_US       = "Period(us)"
_REG_LED_PHASE       = "LED Phase"
_REG_LED_TIME_ON     = "LED Time ON"
_REG_DEV_TIME_ON     = "Dev Time ON"
_REG_DEV_PHASE       = "Dev Phase"
_REG_DEV_PHASE_2     = "Dev Phase 2"
_REG_EXPOSURE_TIME   = "Exposure Time"
_REG_PHASE_SELECT    = "Phase Select"
_REG_LED_PULSED_PH   = "LED Pulsed Phase"
_REG_LED_PULSE_TIME  = "LED Pulse Time"

# Voltage output
_REG_VOLTAGE_OUT     = "Voltage Out"       # FXP: −16 V to +16 V
_REG_AUX_VOLTAGE     = "Aux Voltage"       # FXP: −16 V to +16 V
_REG_OUTPUT_VOUT     = "Output Vout"        # Boolean: enable main V
_REG_OUTPUT_VAUX     = "Output Vaux"        # Boolean: enable aux V
_REG_SET_VOUT        = "SetVout"            # Boolean: latch Vout
_REG_SET_VAUX        = "SetVaux"            # Boolean: latch Vaux
_REG_VO_LIM          = "Vo Lim"             # FXP: main V limit
_REG_VA_LIM          = "Va Lim"             # FXP: aux V limit
_REG_SET_I_LIM       = "Set I Lim"          # Boolean: apply I limit
_REG_HIGH_RANGE      = "High Range"         # Boolean: high V range

# Output / relay
_REG_OUTPUT_SSR      = "Output SSR"         # Boolean: solid-state relay

# Sync
_REG_ENAB_SYNCH      = "EnabSynch"
_REG_SYNCH_PHASE     = "SynchPhase"
_REG_SAMP_RATE       = "SampRate"
_REG_GET_V           = "GetV"               # Boolean: trigger V readback

# Triggering
_REG_IR_FRAME_TRIG   = "IR Frame Trig"
_REG_TRIG_DIR        = "Trig Dir (F=out)"
_REG_EN_TRANS        = "EN_TRANS"
_REG_EVENT_TRIG      = "Event Trig"
_REG_EVENT_TIME_US   = "Event Time(us)"
_REG_EVENT_PHASE_US  = "Event Phase(us)"
_REG_EVENT_SOURCE    = "Event Source"
_REG_ARM_EVENT       = "ArmEvent"

# Indicators (read-only)
_REG_AI0             = "AI0"
_REG_AI1             = "AI1"
_REG_AI2             = "AI2"
_REG_AI3             = "AI3"
_REG_TRIGGER_IN      = "Trigger In"
_REG_VERSION_NUM     = "Version Num"


class Ni9637Driver(FpgaDriver):
    """
    NI sbRIO-9637 FPGA driver for the EZ-500 chassis.

    Loads a compiled LabVIEW FPGA bitfile and controls it via nifpga.
    The firmware provides:
      - Programmable stimulus timing (period, duty cycle, phase)
      - Dual voltage DAC outputs (Vout, Vaux) with ±16 V range
      - Analog input acquisition (4 channels × 115 samples)
      - Camera exposure and trigger timing
      - LED illumination timing (CW and pulsed modes)
      - Transient event trigger system
      - Solid-state relay for stimulus enable
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import nifpga  # noqa: F401
        except ImportError:
            issues.append(
                "nifpga Python package not found — NI sbRIO-9637 FPGA support "
                "unavailable.\n"
                "Install it with:  pip install nifpga\n"
                "Also ensure NI-RIO drivers are installed from ni.com.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._session     = None
        self._bitfile     = cfg.get("bitfile", "")
        self._resource    = cfg.get("resource", "RIO0")
        self._reset       = cfg.get("reset_on_open", True)

        # Cached state
        self._period_us   = float(cfg.get("initial_period_us", 1000.0))
        self._duty        = float(cfg.get("initial_duty", 0.5))
        self._running     = False
        self._trigger_mode = FpgaTriggerMode.CONTINUOUS
        self._trigger_armed = False
        self._fw_version  = 0

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        import os

        # ── 1. Check nifpga Python package ───────────────────────────
        try:
            import nifpga
        except ImportError:
            raise RuntimeError(
                "nifpga Python package is not installed.\n"
                "Fix: pip install nifpga\n"
                "Also ensure NI-RIO drivers are installed from ni.com.")

        # ── 2. Check bitfile path is configured ──────────────────────
        if not self._bitfile:
            raise RuntimeError(
                "No FPGA bitfile path configured.\n"
                "Fix: set  hardware.fpga.bitfile  in config.yaml.\n"
                'Example:  bitfile: "firmware/ez500_fpga.lvbitx"')

        # ── 3. Resolve relative path (relative to app directory) ─────
        bitfile_path = self._bitfile
        if not os.path.isabs(bitfile_path):
            # Try relative to the application's working directory
            bitfile_path = os.path.abspath(bitfile_path)

        # ── 4. Check bitfile actually exists on disk ─────────────────
        if not os.path.isfile(bitfile_path):
            folder = os.path.dirname(bitfile_path) or "."
            if os.path.isdir(folder):
                found = [f for f in os.listdir(folder)
                         if f.lower().endswith(".lvbitx")]
                hint = (f"  Folder {folder!r} contains: {found}"
                        if found else
                        f"  Folder {folder!r} contains no .lvbitx files.")
            else:
                hint = f"  Folder {folder!r} does not exist."
            raise FileNotFoundError(
                f"FPGA bitfile not found: {bitfile_path!r}\n"
                f"{hint}\n"
                "Fix: copy the compiled .lvbitx file to that path, or update "
                "hardware.fpga.bitfile in config.yaml.")

        # ── 5. Check resource string is set ──────────────────────────
        if not self._resource:
            raise RuntimeError(
                "No FPGA resource string configured.\n"
                "Fix: set  hardware.fpga.resource  in config.yaml.\n"
                'Example:  resource: "RIO0"  or  "rio://169.254.x.x/RIO0"\n'
                "Find the correct string in NI MAX under Remote Systems.")

        # ── 6. Open the session ──────────────────────────────────────
        try:
            self._open_session(bitfile_path)
        except Exception as e:
            err = str(e)
            hint = ""
            if "-61202" in err or "FpgaBusyFpgaInterface" in err:
                hint = ("\nHint: The FPGA is already in use by another "
                        "application (NI MAX, LabVIEW, or a previous "
                        "SanjINSIGHT session that didn't close cleanly). "
                        "Close the other application and try again, or "
                        "reboot the sbRIO via NI MAX → Remote Systems.")
            elif "-61046" in err or "SignatureMismatch" in err:
                hint = ("\nHint: Bitfile signature mismatch — the .lvbitx file "
                        "does not match the firmware running on the FPGA. "
                        "Re-deploy the bitfile via NI MAX or LabVIEW.")
            elif "RIO" in err and ("not found" in err.lower() or "-63192" in err):
                hint = ("\nHint: The FPGA resource was not found. "
                        "Check NI MAX → Remote Systems and verify the target "
                        f"is reachable at {self._resource!r}.")
            elif "license" in err.lower():
                hint = ("\nHint: NI-RIO license issue. Verify NI-RIO drivers "
                        "are properly activated on this machine.")
            raise RuntimeError(
                f"FPGA session failed to open.\n"
                f"Resource: {self._resource!r}\n"
                f"Bitfile:  {bitfile_path!r}\n"
                f"Error:    {err}{hint}")

        # ── 7. Read firmware version ─────────────────────────────────
        try:
            self._fw_version = int(
                self._session.registers[_REG_VERSION_NUM].read())
            log.info("FPGA firmware version: %d", self._fw_version)
        except Exception:
            log.warning("Could not read FPGA firmware version register")

        # ── 8. Apply initial timing ──────────────────────────────────
        try:
            self._write_timing()
            log.info("FPGA initial timing: period=%.0f µs, duty=%.1f%%",
                     self._period_us, self._duty * 100)
        except Exception as e:
            log.warning("Could not set initial FPGA timing: %s", e)

    def _open_session(self, bitfile_path: str) -> None:
        """Open the nifpga session, retrying once if the FPGA is busy."""
        import nifpga
        try:
            self._session = nifpga.Session(
                bitfile  = bitfile_path,
                resource = self._resource,
                reset_if_last_session_on_exit=self._reset)
            if self._reset:
                self._session.reset()
            self._session.run()
            self._open = True
            log.info("FPGA session opened  resource=%s  bitfile=%s",
                     self._resource, bitfile_path)
        except Exception as e1:
            err1 = str(e1)
            if "-61202" not in err1 and "FpgaBusyFpgaInterface" not in err1:
                raise   # not a busy error — propagate immediately
            # ── FPGA busy: force-close stale session and retry ───────
            log.warning("FPGA busy (-61202) — closing stale session and "
                        "retrying...")
            try:
                stale = nifpga.Session(
                    bitfile  = bitfile_path,
                    resource = self._resource,
                    no_run=True)
                stale.close()
            except Exception:
                pass   # best-effort cleanup
            # Retry the open
            self._session = nifpga.Session(
                bitfile  = bitfile_path,
                resource = self._resource,
                reset_if_last_session_on_exit=self._reset)
            if self._reset:
                self._session.reset()
            self._session.run()
            self._open = True
            log.info("FPGA session opened on retry  resource=%s", self._resource)

    def close(self) -> None:
        if self._session:
            try:
                self.stop()
                self._session.close()
            except Exception:
                pass
            self._session = None
        self._open    = False
        self._running = False

    # ------------------------------------------------------------------ #
    #  Control — basic interface (matches FpgaDriver ABC)                 #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Enable the solid-state relay → starts stimulus output."""
        self._session.registers[_REG_OUTPUT_SSR].write(True)
        self._running = True
        log.info("FPGA stimulus started (SSR on)")

    def stop(self) -> None:
        """Disable the solid-state relay → stops stimulus output."""
        try:
            self._session.registers[_REG_OUTPUT_SSR].write(False)
        except Exception:
            pass
        self._running = False
        log.info("FPGA stimulus stopped (SSR off)")

    def set_frequency(self, hz: float) -> None:
        """Set stimulus frequency in Hz → writes Period(us) register."""
        if hz <= 0:
            raise ValueError(f"Frequency must be positive, got {hz}")
        self._period_us = 1_000_000.0 / hz
        self._write_timing()
        log.debug("FPGA frequency → %.1f Hz  (period %.0f µs)", hz, self._period_us)

    def set_duty_cycle(self, fraction: float) -> None:
        """Set duty cycle 0.0–1.0 → writes Dev Time ON register."""
        self._duty = max(0.0, min(1.0, fraction))
        self._write_timing()
        log.debug("FPGA duty cycle → %.1f%%", self._duty * 100)

    def set_stimulus(self, on: bool) -> None:
        """Direct control of solid-state relay."""
        self._session.registers[_REG_OUTPUT_SSR].write(on)
        self._running = on

    # ------------------------------------------------------------------ #
    #  Trigger / transient mode                                           #
    # ------------------------------------------------------------------ #

    def set_trigger_mode(self, mode: FpgaTriggerMode) -> None:
        """Switch between CONTINUOUS and SINGLE_SHOT (transient) mode."""
        self._trigger_mode = mode
        self._trigger_armed = False
        is_trans = (mode == FpgaTriggerMode.SINGLE_SHOT)
        self._session.registers[_REG_EN_TRANS].write(is_trans)
        log.info("FPGA trigger mode → %s  (EN_TRANS=%s)", mode, is_trans)

    def arm_trigger(self) -> None:
        """Arm the event trigger system for a single-shot pulse."""
        if self._trigger_mode != FpgaTriggerMode.SINGLE_SHOT:
            raise RuntimeError("arm_trigger() requires SINGLE_SHOT mode.")
        self._session.registers[_REG_ARM_EVENT].write(True)
        self._session.registers[_REG_EVENT_TRIG].write(True)
        self._trigger_armed = True
        log.info("FPGA event trigger armed")

    def set_pulse_duration(self, duration_us: float) -> None:
        """Set the event pulse duration in microseconds."""
        self._session.registers[_REG_EVENT_TIME_US].write(int(round(duration_us)))
        log.debug("FPGA event pulse duration → %.0f µs", duration_us)

    def supports_trigger_mode(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    #  EZ-500–specific controls (beyond base FpgaDriver interface)        #
    # ------------------------------------------------------------------ #

    def set_period_us(self, period_us: float) -> None:
        """Set stimulus period directly in microseconds."""
        if period_us <= 0:
            raise ValueError(f"Period must be positive, got {period_us}")
        self._period_us = period_us
        self._write_timing()

    def set_voltage(self, volts: float) -> None:
        """Set main voltage output (−16 V to +16 V) and enable it."""
        volts = max(-16.0, min(15.999, volts))
        self._session.registers[_REG_VOLTAGE_OUT].write(volts)
        self._session.registers[_REG_SET_VOUT].write(True)
        self._session.registers[_REG_OUTPUT_VOUT].write(True)
        log.debug("FPGA Vout → %.4f V (enabled)", volts)

    def set_aux_voltage(self, volts: float) -> None:
        """Set auxiliary voltage output (−16 V to +16 V) and enable it."""
        volts = max(-16.0, min(15.999, volts))
        self._session.registers[_REG_AUX_VOLTAGE].write(volts)
        self._session.registers[_REG_SET_VAUX].write(True)
        self._session.registers[_REG_OUTPUT_VAUX].write(True)
        log.debug("FPGA Vaux → %.4f V (enabled)", volts)

    def disable_voltage(self) -> None:
        """Disable both voltage outputs."""
        self._session.registers[_REG_OUTPUT_VOUT].write(False)
        self._session.registers[_REG_OUTPUT_VAUX].write(False)
        log.debug("FPGA voltage outputs disabled")

    def set_voltage_limits(self, vo_lim: float, va_lim: float) -> None:
        """Set voltage limits for main and aux outputs."""
        self._session.registers[_REG_VO_LIM].write(
            max(-16.0, min(15.999, vo_lim)))
        self._session.registers[_REG_VA_LIM].write(
            max(-16.0, min(15.999, va_lim)))
        self._session.registers[_REG_SET_I_LIM].write(True)
        log.debug("FPGA voltage limits: Vo=%.2f V, Va=%.2f V", vo_lim, va_lim)

    def set_exposure_time(self, ticks: int) -> None:
        """Set the camera exposure timing register."""
        self._session.registers[_REG_EXPOSURE_TIME].write(int(ticks))

    def set_led_timing(self, phase: int, time_on: int) -> None:
        """Set LED illumination timing (CW mode)."""
        self._session.registers[_REG_LED_PHASE].write(int(phase))
        self._session.registers[_REG_LED_TIME_ON].write(int(time_on))

    def set_led_pulsed(self, phase: int, pulse_time: int) -> None:
        """Set LED pulsed illumination timing."""
        self._session.registers[_REG_LED_PULSED_PH].write(int(phase))
        self._session.registers[_REG_LED_PULSE_TIME].write(int(pulse_time))

    def set_device_phase(self, phase: int, phase2: int = 0,
                         use_phase2: bool = False) -> None:
        """Set device phase offset(s)."""
        self._session.registers[_REG_DEV_PHASE].write(int(phase))
        self._session.registers[_REG_DEV_PHASE_2].write(int(phase2))
        self._session.registers[_REG_PHASE_SELECT].write(use_phase2)

    def set_synch(self, enabled: bool, phase: int = 0) -> None:
        """Enable/disable external synchronisation."""
        self._session.registers[_REG_ENAB_SYNCH].write(enabled)
        self._session.registers[_REG_SYNCH_PHASE].write(int(phase))

    def set_sample_rate(self, rate: int) -> None:
        """Set analog input sample rate divisor."""
        self._session.registers[_REG_SAMP_RATE].write(int(rate))

    def set_trigger_direction(self, output: bool) -> None:
        """Set trigger BNC direction. False = output, True = input."""
        # Register name is "Trig Dir (F=out)" — False means output
        self._session.registers[_REG_TRIG_DIR].write(not output)

    def set_high_range(self, enabled: bool) -> None:
        """Enable high voltage range on analog outputs."""
        self._session.registers[_REG_HIGH_RANGE].write(enabled)

    def set_ir_frame_trigger(self, enabled: bool) -> None:
        """Enable/disable IR camera frame trigger output."""
        self._session.registers[_REG_IR_FRAME_TRIG].write(enabled)

    def set_event_source(self, source: int) -> None:
        """Set event trigger source (I16 enum)."""
        self._session.registers[_REG_EVENT_SOURCE].write(int(source))

    def set_event_phase(self, phase_us: int) -> None:
        """Set event trigger phase delay in microseconds."""
        self._session.registers[_REG_EVENT_PHASE_US].write(int(phase_us))

    def read_analog_inputs(self) -> dict:
        """Read all four analog input arrays (115 samples each).

        Returns dict with keys 'ai0'–'ai3', each a list of float values.
        """
        result = {}
        for i, reg in enumerate([_REG_AI0, _REG_AI1, _REG_AI2, _REG_AI3]):
            try:
                result[f"ai{i}"] = list(self._session.registers[reg].read())
            except Exception as e:
                log.warning("Failed to read %s: %s", reg, e)
                result[f"ai{i}"] = []
        return result

    def trigger_voltage_readback(self) -> None:
        """Pulse the GetV register to trigger analog voltage readback."""
        self._session.registers[_REG_GET_V].write(True)

    @property
    def firmware_version(self) -> int:
        """Return the firmware version read at session open."""
        return self._fw_version

    # ------------------------------------------------------------------ #
    #  Status readback                                                    #
    # ------------------------------------------------------------------ #

    def get_status(self) -> FpgaStatus:
        try:
            # Read external trigger state as a proxy for sync lock
            trigger_in = bool(
                self._session.registers[_REG_TRIGGER_IN].read())
            return FpgaStatus(
                running       = self._running,
                frame_count   = 0,  # no frame counter in this firmware
                stimulus_on   = self._running,
                freq_hz       = 1_000_000.0 / self._period_us if self._period_us > 0 else 0,
                duty_cycle    = self._duty,
                sync_locked   = trigger_in,
                trigger_mode  = self._trigger_mode,
                trigger_armed = self._trigger_armed,
            )
        except Exception as e:
            return FpgaStatus(error=str(e))

    def frequency_range(self) -> tuple:
        """Return (min_hz, max_hz) supported by the firmware.

        Period(us) is U32: 1 µs → 1 MHz max, 4294967295 µs → ~0.00023 Hz min.
        Practical range clamped to 0.1 Hz – 1 MHz.
        """
        return (0.1, 1_000_000.0)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _write_timing(self) -> None:
        """Write period and device on-time to FPGA registers."""
        period = int(round(self._period_us))
        dev_on = int(round(self._period_us * self._duty))

        self._session.registers[_REG_PERIOD_US].write(max(1, period))
        self._session.registers[_REG_DEV_TIME_ON].write(max(0, dev_on))
        log.debug("FPGA timing: Period(us)=%d  Dev Time ON=%d", period, dev_on)
