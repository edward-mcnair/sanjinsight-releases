"""
hardware/fpga/ni9637.py

Driver for NI 9637 FPGA module via the nifpga Python library.

Requires:
  - NI-RIO drivers installed (Windows)
  - pip install nifpga
  - Compiled .lvbitx bitfile at the path specified in config.yaml

Config keys (under hardware.fpga):
    bitfile:       "C:/path/to/firmware.lvbitx"
    resource:      "rio://169.254.19.194/RIO0"
    reset_on_open: false

FPGA register names must match those compiled into the bitfile.
If register names differ, update _REG_* constants below.
"""

from .base import FpgaDriver, FpgaStatus


# Register names as compiled into the FPGA bitfile
# Adjust these if your bitfile uses different names
_REG_FREQUENCY    = "Frequency"
_REG_DUTY_CYCLE   = "Duty Cycle"
_REG_START        = "Start"
_REG_STOP         = "Stop"
_REG_STIMULUS_ON  = "Stimulus On"
_REG_FRAME_COUNT  = "Frame Count"
_REG_SYNC_LOCKED  = "Sync Locked"


class Ni9637Driver(FpgaDriver):
    """
    NI 9637 FPGA driver.
    Loads a compiled LabVIEW FPGA bitfile and controls it via nifpga.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._session     = None
        self._bitfile     = cfg.get("bitfile", "")
        self._resource    = cfg.get("resource", "RIO0")
        self._reset       = cfg.get("reset_on_open", False)
        self._freq        = 1000.0
        self._duty        = 0.5
        self._running     = False

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
                "Example:  bitfile: \"C:/Microsanj/firmware/bonaire.lvbitx\"")

        # ── 3. Check bitfile actually exists on disk ──────────────────
        if not os.path.isfile(self._bitfile):
            # Give the user a helpful directory listing if the folder exists
            folder = os.path.dirname(self._bitfile) or "."
            if os.path.isdir(folder):
                found = [f for f in os.listdir(folder)
                         if f.lower().endswith(".lvbitx")]
                hint = (f"  Folder {folder!r} contains: {found}"
                        if found else
                        f"  Folder {folder!r} contains no .lvbitx files.")
            else:
                hint = f"  Folder {folder!r} does not exist."
            raise FileNotFoundError(
                f"FPGA bitfile not found: {self._bitfile!r}\n"
                f"{hint}\n"
                "Fix: copy the compiled .lvbitx file to that path, or update "
                "hardware.fpga.bitfile in config.yaml.")

        # ── 4. Check resource string is set ──────────────────────────
        if not self._resource:
            raise RuntimeError(
                "No FPGA resource string configured.\n"
                "Fix: set  hardware.fpga.resource  in config.yaml.\n"
                "Example:  resource: \"RIO0\"  or  \"rio://169.254.x.x/RIO0\"\n"
                "Find the correct string in NI MAX under Remote Systems.")

        # ── 5. Open the session ───────────────────────────────────────
        try:
            self._session = nifpga.Session(
                bitfile       = self._bitfile,
                resource      = self._resource,
                reset_if_last_session_on_exit = self._reset)
            self._open = True
        except Exception as e:
            err = str(e)
            # Provide targeted guidance for common NI error codes
            hint = ""
            if "RIO" in err and ("not found" in err.lower() or "-63192" in err):
                hint = ("\nHint: The FPGA resource was not found. "
                        "Check NI MAX → Remote Systems and verify the target "
                        f"is reachable at {self._resource!r}.")
            elif "signature" in err.lower() or "-61046" in err:
                hint = ("\nHint: Bitfile signature mismatch — the .lvbitx file "
                        "does not match the firmware running on the FPGA. "
                        "Re-deploy the bitfile via NI MAX or LabVIEW.")
            elif "license" in err.lower():
                hint = ("\nHint: NI-RIO license issue. Verify NI-RIO drivers "
                        "are properly activated on this machine.")
            raise RuntimeError(
                f"FPGA session failed to open.\n"
                f"Resource: {self._resource!r}\n"
                f"Bitfile:  {self._bitfile!r}\n"
                f"Error:    {err}{hint}")

    def close(self) -> None:
        if self._session:
            try:
                self.stop()
                self._session.close()
            except Exception:
                pass
        self._open    = False
        self._running = False

    def start(self) -> None:
        self._session.registers[_REG_START].write(True)
        self._running = True

    def stop(self) -> None:
        self._session.registers[_REG_STOP].write(True)
        self._running = False

    def set_frequency(self, hz: float) -> None:
        self._freq = hz
        self._session.registers[_REG_FREQUENCY].write(float(hz))

    def set_duty_cycle(self, fraction: float) -> None:
        self._duty = max(0.0, min(1.0, fraction))
        self._session.registers[_REG_DUTY_CYCLE].write(self._duty)

    def set_stimulus(self, on: bool) -> None:
        self._session.registers[_REG_STIMULUS_ON].write(on)

    def get_status(self) -> FpgaStatus:
        try:
            frame_count = int(
                self._session.registers[_REG_FRAME_COUNT].read())
            sync_locked = bool(
                self._session.registers[_REG_SYNC_LOCKED].read())
            stimulus_on = bool(
                self._session.registers[_REG_STIMULUS_ON].read())
            return FpgaStatus(
                running     = self._running,
                frame_count = frame_count,
                stimulus_on = stimulus_on,
                freq_hz     = self._freq,
                duty_cycle  = self._duty,
                sync_locked = sync_locked,
            )
        except Exception as e:
            return FpgaStatus(error=str(e))

    def frequency_range(self) -> tuple:
        return (0.1, 100_000.0)
