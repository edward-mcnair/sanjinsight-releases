"""
hardware/ldd/meerstetter_ldd1121.py

Driver for the Meerstetter LDD-1121 Laser Diode Driver via pyMeCom.

The LDD-1121 is the illumination source controller in Microsanj NT220 and
EZ-Therm systems.  It controls an LED or pulsed-diode laser via the same
Meerstetter MeCom serial protocol used by the TEC-1089 temperature controller.

Both devices share the same RS-485 bus at 57 600 baud; each is assigned a
unique device address (TEC=2, LDD=1 per verified LabVIEW config files).

Key MeCom parameter IDs used
-----------------------------
  1000  Object Temperature (°C)    — laser diode NTC thermistor readback
  1020  Actual Output Current (A)  — measured LED drive current
  1021  Actual Output Voltage (V)  — measured LED drive voltage
  2010  Output Enable              — 0 = off, 1 = on
  3000  Target Current Set Point   — CW drive current (A)

Pulse timing (when Pulse_Source = HW Pin) is driven entirely by the FPGA
hardware; this driver only sets the amplitude and enables the output.

Requires: pip install pyMeCom

Config keys (under hardware.ldd_meerstetter):
    port:     "COM3"    Serial port (shared with TEC on same RS-485 bus)
    address:  1         Device address (LDD default = 1, TEC default = 2)
    timeout:  1.0
"""

import logging
import threading
from .base import LddDriver, LddStatus
from hardware.port_lock import PortLock
from ai.instrument_knowledge import (
    LDD_MAX_CURRENT_A,
    LDD_START_CURRENT_A,
)

log = logging.getLogger(__name__)


class MeerstetterLdd1121(LddDriver):
    """Meerstetter LDD-1121 driver via pyMeCom."""

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import mecom  # noqa: F401
        except ImportError:
            issues.append(
                "pyMeCom library not found — Meerstetter LDD-1121 support is not bundled.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    # MeCom parameter IDs
    _PID_OBJECT_TEMP   = 1000   # °C   — diode NTC temperature
    _PID_ACT_CURRENT   = 1020   # A    — actual output current
    _PID_ACT_VOLTAGE   = 1021   # V    — actual output voltage
    _PID_OUTPUT_ENABLE = 2010   # 0/1  — output on/off
    _PID_TARGET_CURR   = 3000   # A    — CW current setpoint

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port     = cfg.get("port",    "COM3")
        self._address  = cfg.get("address", 1)      # LDD-1121 default address = 1
        self._timeout  = cfg.get("timeout", 1.0)
        self._ldd      = None
        self._target_a = LDD_START_CURRENT_A        # safe start current from INI
        self._port_lock = PortLock(self._port)
        # pyMeCom is not thread-safe — gate all API calls behind a lock.
        self._api_lock  = threading.Lock()

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        try:
            self._port_lock.acquire()
            from mecom import MeComAPI
            self._ldd = MeComAPI(self._port)
            self._ldd.identify()
            self._connected = True
            log.info("Meerstetter LDD-1121 connected on %s (address %d)",
                     self._port, self._address)
        except ImportError:
            self._port_lock.release()
            raise RuntimeError(
                "pyMeCom library not found.\n\n"
                "pyMeCom provides the MeCom serial protocol used to talk to "
                "Meerstetter TEC and LDD controllers.\n\n"
                "Install it with:\n"
                "    pip install pyMeCom\n\n"
                "Or download from GitHub:\n"
                "    https://github.com/meerstetter/pyMeCom\n\n"
                "After installing, restart the application."
            )
        except Exception as e:
            self._port_lock.release()
            raise RuntimeError(
                f"Meerstetter LDD-1121 connect failed on {self._port}: {e}\n"
                f"Check port name and that nothing else is holding it open.")

    def disconnect(self) -> None:
        if self._ldd:
            try:
                self._ldd.session.close()
            except Exception:
                pass
        self._connected = False
        try:
            self._port_lock.release()
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    def enable(self) -> None:
        """Activate LED output (Output Enable = 1)."""
        with self._api_lock:
            self._ldd.set_parameter(
                parameter_id=self._PID_OUTPUT_ENABLE, value=1,
                address=self._address, instance=1)

    def disable(self) -> None:
        """De-activate LED output (Output Enable = 0)."""
        with self._api_lock:
            self._ldd.set_parameter(
                parameter_id=self._PID_OUTPUT_ENABLE, value=0,
                address=self._address, instance=1)

    def set_current(self, current_a: float) -> None:
        """
        Set CW LED drive current in Amperes.

        Clamped to [0, LDD_MAX_CURRENT_A].  Writes MeCom parameter 3000
        (Target Current Set Point).  The hardware ramp rate (SlopeLimit = 0.2 A)
        means sudden large changes are applied gradually by the firmware.
        """
        clamped = max(0.0, min(current_a, LDD_MAX_CURRENT_A))
        self._target_a = clamped
        with self._api_lock:
            self._ldd.set_parameter(
                parameter_id=self._PID_TARGET_CURR, value=clamped,
                address=self._address, instance=1)

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> LddStatus:
        try:
            with self._api_lock:
                temp = self._ldd.get_parameter(
                    parameter_id=self._PID_OBJECT_TEMP,
                    address=self._address, instance=1)
                current = self._ldd.get_parameter(
                    parameter_id=self._PID_ACT_CURRENT,
                    address=self._address, instance=1)
                voltage = self._ldd.get_parameter(
                    parameter_id=self._PID_ACT_VOLTAGE,
                    address=self._address, instance=1)
                enabled = bool(self._ldd.get_parameter(
                    parameter_id=self._PID_OUTPUT_ENABLE,
                    address=self._address, instance=1))

            return LddStatus(
                actual_current_a = float(current),
                actual_voltage_v = float(voltage),
                diode_temp_c     = float(temp),
                enabled          = enabled,
                mode             = "hw_trigger" if enabled else "cw",
            )
        except Exception as e:
            return LddStatus(error=str(e))
