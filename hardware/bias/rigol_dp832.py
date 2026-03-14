"""
hardware/bias/rigol_dp832.py

Native driver for the Rigol DP832 3-channel programmable DC power supply
using the pydp832 library (Ethernet/LAN — no NI-VISA installation required).

Requires: pip install pydp832
GitHub:   https://github.com/tspspi/pydp832

This driver communicates directly over a TCP socket to the instrument's
built-in LAN port (default port 5025 / SCPI-raw).  It is a lighter-weight
alternative to the visa_generic driver for labs that do not have NI-VISA.

Config keys (under hardware.bias):
    host:        "192.168.1.20"   IP address of the DP832 (set on front panel)
    channel:     1                Output channel to use (1, 2, or 3)
    mode:        "voltage"        Fixed — DP832 is a programmable voltage source
    level:       0.0              Initial output voltage (V)
    compliance:  0.5              Current limit / OCP threshold (A)

Rigol DP832 channel ranges
--------------------------
    Channel 1 / 2:  0–30 V, 0–3 A
    Channel 3:      0–5.3 V, 0–3 A   (5 V auxiliary rail)
"""

from .base import BiasDriver, BiasStatus

import logging
log = logging.getLogger(__name__)


class RigolDP832Driver(BiasDriver):
    """Rigol DP832 driver via pydp832 (LAN, no VISA required)."""

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        import importlib
        found = False
        for mod_path in ("pydp832", "pydp832.dp832lan", "dp832"):
            try:
                importlib.import_module(mod_path)
                found = True
                break
            except ImportError:
                continue
        if not found:
            issues.append(
                "pydp832 library not found — Rigol DP832 support unavailable.\n"
                "Install it with:  pip install pydp832\n"
                "Alternatively, use driver: 'visa_generic' with pyvisa if NI-VISA is installed.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._host    = cfg.get("host", "192.168.1.20")
        self._channel = int(cfg.get("channel", 1))
        self._dp      = None

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        # pydp832 may expose DP832LAN from the top-level package or from a
        # sub-module depending on the installed version; try both paths.
        DP832LAN = None
        try:
            from pydp832 import DP832LAN  # type: ignore
        except ImportError:
            try:
                from pydp832.dp832lan import DP832LAN  # type: ignore
            except ImportError:
                try:
                    from dp832 import DP832LAN  # type: ignore
                except ImportError:
                    raise RuntimeError(
                        "pydp832 library not found.\n\n"
                        "pydp832 provides native Ethernet control of the Rigol DP832 "
                        "without requiring NI-VISA.\n\n"
                        "Install it with:\n"
                        "    pip install pydp832\n\n"
                        "Or download from GitHub:\n"
                        "    https://github.com/tspspi/pydp832\n\n"
                        "After installing, restart the application.\n\n"
                        "Alternatively, use driver: 'visa_generic' with pyvisa if "
                        "you already have NI-VISA installed."
                    )

        try:
            self._dp = DP832LAN(self._host)
            idn = self._dp.idn()
            log.info("Rigol DP832 connected at %s: %s", self._host, idn)
            self._connected = True
        except Exception as e:
            self._dp = None
            raise RuntimeError(
                f"Rigol DP832 connect failed at {self._host}: {e}\n"
                f"Check that:\n"
                f"  • The IP address matches the front-panel LAN setting\n"
                f"  • The instrument is reachable (try pinging {self._host})\n"
                f"  • LAN control is enabled on the DP832 (Utility → I/O → LAN)"
            )

    def disconnect(self) -> None:
        try:
            if self._dp:
                self.disable()
        except Exception:
            pass
        self._connected = False
        self._dp = None

    # ------------------------------------------------------------------ #
    #  Output control                                                      #
    # ------------------------------------------------------------------ #

    def enable(self) -> None:
        self._dp.setChannelEnable(True, self._channel)

    def disable(self) -> None:
        self._dp.setChannelEnable(False, self._channel)

    def set_mode(self, mode: str) -> None:
        # The DP832 is a DC voltage source; mode is recorded for compatibility
        # with the BiasDriver interface but does not alter instrument function.
        self._mode = mode

    def set_level(self, value: float) -> None:
        self._level = value
        if self._mode == "voltage":
            self._dp.setVoltage(value, self._channel)
        else:
            # Current-source mode: set current, leave voltage limit unchanged
            self._dp.setCurrent(value, self._channel)

    def set_compliance(self, value: float) -> None:
        self._compliance = value
        if self._mode == "voltage":
            # In voltage mode the compliance is the current limit (OCP)
            self._dp.setCurrent(value, self._channel)
        else:
            # In current mode the compliance is the voltage limit (OVP)
            self._dp.setVoltage(value, self._channel)

    # ------------------------------------------------------------------ #
    #  Status readback                                                     #
    # ------------------------------------------------------------------ #

    def get_status(self) -> BiasStatus:
        try:
            v = float(self._dp.getVoltage(self._channel))
            i = float(self._dp.getCurrent(self._channel))
            return BiasStatus(
                output_on      = True,     # pydp832 ≤0.0.4 has no query for output state
                mode           = self._mode,
                setpoint       = self._level,
                actual_voltage = v,
                actual_current = i,
                actual_power   = abs(v * i),
                compliance     = self._compliance,
            )
        except Exception as e:
            return BiasStatus(error=str(e))

    # ------------------------------------------------------------------ #
    #  Range metadata                                                      #
    # ------------------------------------------------------------------ #

    def voltage_range(self) -> tuple[float, float]:
        # Ch1 and Ch2 are 0–30 V; Ch3 is the 5 V auxiliary output (0–5.3 V)
        return (0.0, 30.0) if self._channel in (1, 2) else (0.0, 5.3)

    def current_range(self) -> tuple[float, float]:
        return (0.0, 3.0)
