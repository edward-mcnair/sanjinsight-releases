"""
hardware/bias/visa_generic.py

Generic SCPI bias source driver for any VISA-compatible instrument
that follows standard IEEE 488.2 / SCPI conventions.

Works with: Agilent/Keysight E36xx, B29xx, Rohde & Schwarz HMP series,
            Rigol DP8xx, BK Precision 9200 series, and most modern
            bench power supplies with USB/LAN/GPIB.

Config keys (under hardware.bias):
    address:     "TCPIP::192.168.1.10::INSTR"
    mode:        "voltage"
    level:       0.0
    compliance:  0.1
    channel:     1          output channel number (for multi-channel supplies)
    v_cmd:       ":VOLT"    override SCPI voltage command prefix if needed
    i_cmd:       ":CURR"    override SCPI current command prefix if needed
"""

from .base import BiasDriver, BiasStatus

import logging
log = logging.getLogger(__name__)


class VisaGenericDriver(BiasDriver):

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import pyvisa  # noqa: F401
        except ImportError:
            issues.append(
                "pyvisa not found — VISA instrument support unavailable.\n"
                "Install it with:  pip install pyvisa pyvisa-py\n"
                "For GPIB on Windows, also install NI-VISA from ni.com.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._address = cfg.get("address", "")
        self._channel = cfg.get("channel", 1)
        self._v_cmd   = cfg.get("v_cmd", ":VOLT")
        self._i_cmd   = cfg.get("i_cmd", ":CURR")
        self._rm      = None
        self._inst    = None

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError:
            raise RuntimeError(
                "pyvisa not installed.\n\n"
                "PyVISA provides the VISA communication layer needed to talk to "
                "SCPI instruments over USB, Ethernet, or GPIB.\n\n"
                "Install it with:\n"
                "    pip install pyvisa pyvisa-py\n\n"
                "Or use NI-VISA (recommended on Windows for GPIB):\n"
                "    https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html\n\n"
                "For Rigol DP832 over Ethernet without NI-VISA, use driver: 'rigol_dp832'\n"
                "    pip install pydp832  —  https://github.com/tspspi/pydp832\n\n"
                "After installing, restart the application."
            )

        try:
            self._rm   = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = 5000
            idn = self._inst.query("*IDN?").strip()
            log.info(f"VISA instrument connected: {idn}")
            self._write("*RST")
            self._connected = True
        except Exception as e:
            raise RuntimeError(
                f"VISA connect failed at {self._address}: {e}")

    def _write(self, cmd):
        self._inst.write(cmd)

    def _query(self, cmd):
        return self._inst.query(cmd).strip()

    def disconnect(self) -> None:
        try:
            self.disable()
            if self._inst:
                self._inst.close()
        except Exception:
            pass
        self._connected = False

    def enable(self) -> None:
        self._write(f":OUTP ON,(@{self._channel})")

    def disable(self) -> None:
        self._write(f":OUTP OFF,(@{self._channel})")

    def set_mode(self, mode: str) -> None:
        self._mode = mode   # Most supplies are fixed mode (voltage or current)

    def set_level(self, value: float) -> None:
        self._level = value
        cmd = self._v_cmd if self._mode == "voltage" else self._i_cmd
        self._write(f"{cmd} {value:.6e},(@{self._channel})")

    def set_compliance(self, value: float) -> None:
        self._compliance = value
        cmd = self._i_cmd if self._mode == "voltage" else self._v_cmd
        self._write(f"{cmd}:PROT {value:.6e},(@{self._channel})")

    def get_status(self) -> BiasStatus:
        try:
            v   = float(self._query(f":MEAS:VOLT? (@{self._channel})"))
            i   = float(self._query(f":MEAS:CURR? (@{self._channel})"))
            out = self._query(f":OUTP? (@{self._channel})")
            return BiasStatus(
                output_on      = out.strip() in ("1", "ON"),
                mode           = self._mode,
                setpoint       = self._level,
                actual_voltage = v,
                actual_current = i,
                actual_power   = abs(v * i),
                compliance     = self._compliance,
            )
        except Exception as e:
            return BiasStatus(error=str(e))
