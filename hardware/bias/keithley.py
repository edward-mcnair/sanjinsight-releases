"""
hardware/bias/keithley.py

Driver for Keithley 2400/2450/2600 series SourceMeters.
Connects via GPIB, USB, or Ethernet using PyVISA.

Requires: pip install pyvisa pyvisa-py

Config keys (under hardware.bias):
    address:     "GPIB::24"           VISA resource string
                 "USB0::0x05E6::..."  USB (copy from NI MAX or Keithley software)
                 "TCPIP::192.168.1.5::INSTR"  Ethernet
    mode:        "voltage"            or "current"
    level:       0.0                  initial output level (V or A)
    compliance:  0.1                  initial compliance (A or V)
    model:       "2400"               used to select correct command dialect

Supported models:
    2400, 2410, 2420, 2425, 2430, 2450  — SMU command set
    2601, 2602, 2611, 2612, 2635, 2636  — TSP command set (auto-detected)
"""

from .base import BiasDriver, BiasStatus

import logging
log = logging.getLogger(__name__)


class KeithleyDriver(BiasDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._address = cfg.get("address", "GPIB::24")
        self._model   = str(cfg.get("model", "2400"))
        self._rm      = None
        self._inst    = None
        self._tsp     = self._model.startswith("26")  # TSP vs SCPI dialect

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError:
            raise RuntimeError(
                "pyvisa not installed. Run: pip install pyvisa pyvisa-py")

        try:
            self._rm   = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = 5000

            idn = self._inst.query("*IDN?").strip()
            log.info(f"Keithley connected: {idn}")

            self._reset()
            self._connected = True

        except Exception as e:
            raise RuntimeError(
                f"Keithley connect failed at {self._address}: {e}\n"
                f"Check VISA address in NI MAX or Keithley software.")

    def _reset(self):
        self._write("*RST")
        if not self._tsp:
            self._write(":SYST:BEEP:STAT OFF")
            self._write(":DISP:ENAB OFF")   # faster comms

    def _write(self, cmd: str):
        self._inst.write(cmd)

    def _query(self, cmd: str) -> str:
        return self._inst.query(cmd).strip()

    def disconnect(self) -> None:
        try:
            self.disable()
            if self._inst:
                self._inst.close()
            if self._rm:
                self._rm.close()
        except Exception:
            pass
        self._connected = False

    def enable(self) -> None:
        if self._tsp:
            self._write("smua.source.output = smua.OUTPUT_ON")
        else:
            self._write(":OUTP ON")

    def disable(self) -> None:
        if self._tsp:
            self._write("smua.source.output = smua.OUTPUT_OFF")
        else:
            self._write(":OUTP OFF")

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if self._tsp:
            fn = "smua.SOURCE_DCVOLTS" if mode == "voltage" \
                 else "smua.SOURCE_DCAMPS"
            self._write(f"smua.source.func = {fn}")
        else:
            fn = "VOLT" if mode == "voltage" else "CURR"
            self._write(f":SOUR:FUNC {fn}")

    def set_level(self, value: float) -> None:
        self._level = value
        if self._tsp:
            attr = "smua.source.levelv" if self._mode == "voltage" \
                   else "smua.source.leveli"
            self._write(f"{attr} = {value:.6e}")
        else:
            attr = "VOLT" if self._mode == "voltage" else "CURR"
            self._write(f":SOUR:{attr}:LEV {value:.6e}")

    def set_compliance(self, value: float) -> None:
        self._compliance = value
        if self._tsp:
            attr = "smua.source.limiti" if self._mode == "voltage" \
                   else "smua.source.limitv"
            self._write(f"{attr} = {value:.6e}")
        else:
            attr = "CURR" if self._mode == "voltage" else "VOLT"
            self._write(f":SENS:{attr}:PROT {value:.6e}")

    def get_status(self) -> BiasStatus:
        try:
            if self._tsp:
                raw = self._query(
                    "print(smua.measure.iv(smua.nvbuffer1, smua.nvbuffer2))")
                # TSP returns "i\tv" or similar — parse carefully
                parts = raw.replace('\t', ' ').split()
                current = float(parts[0]) if parts else 0.0
                voltage = float(parts[1]) if len(parts) > 1 else 0.0
            else:
                # Use separate :MEAS:VOLT? and :MEAS:CURR? queries —
                # the combined ":MEAS:CURR:VOLT?" command is not a valid SCPI command.
                raw_v = self._query(":MEAS:VOLT?")
                raw_i = self._query(":MEAS:CURR?")
                voltage = float(raw_v.split(',')[0]) if raw_v else 0.0
                current = float(raw_i.split(',')[0]) if raw_i else 0.0

            out_raw = self._query(
                "print(smua.source.output)" if self._tsp else ":OUTP?")
            output_on = out_raw.strip() in ("1", "ON", "smua.OUTPUT_ON")

            return BiasStatus(
                output_on      = output_on,
                mode           = self._mode,
                setpoint       = self._level,
                actual_voltage = voltage,
                actual_current = current,
                actual_power   = abs(voltage * current),
                compliance     = self._compliance,
            )
        except Exception as e:
            return BiasStatus(error=str(e))

    def voltage_range(self) -> tuple:
        ranges = {
            "2400": (-210.0, 210.0),
            "2450": (-210.0, 210.0),
            "2601": (-40.0,  40.0),
            "2611": (-200.0, 200.0),
        }
        return ranges.get(self._model, (-200.0, 200.0))

    def current_range(self) -> tuple:
        ranges = {
            "2400": (-1.05, 1.05),
            "2450": (-1.05, 1.05),
            "2601": (-3.0,  3.0),
            "2611": (-1.5,  1.5),
        }
        return ranges.get(self._model, (-1.0, 1.0))
