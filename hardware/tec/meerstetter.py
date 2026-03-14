"""
hardware/tec/meerstetter.py

Driver for Meerstetter TEC-1089 controller via pyMeCom library.

Requires: pip install pyMeCom

Config keys (under hardware.tec_meerstetter):
    port:     "COM3"    Serial port (Windows: COMx, Mac/Linux: /dev/ttyUSBx)
    address:  2         Device address set on the unit
    timeout:  1.0
"""

import logging
import threading
from .base import TecDriver, TecStatus
from hardware.port_lock import PortLock

log = logging.getLogger(__name__)


class MeerstetterDriver(TecDriver):

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import mecom  # noqa: F401
        except ImportError:
            issues.append(
                "pyMeCom library not found — Meerstetter TEC support is not bundled.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port    = cfg.get("port",    "COM3")
        self._address = cfg.get("address", 2)
        self._timeout = cfg.get("timeout", 1.0)
        self._tec       = None
        self._target    = 25.0
        self._port_lock = PortLock(self._port)
        # pyMeCom MeComAPI is not thread-safe; the poll thread and control
        # threads (set_target, enable, disable) must not call it concurrently
        # or they will corrupt each other's serial frames and cause CRC errors.
        self._api_lock  = threading.Lock()

    def connect(self) -> None:
        try:
            self._port_lock.acquire()
            from mecom import MeComAPI, MeComQuerySet, MeComQuery
            self._tec = MeComAPI(self._port)
            self._tec.identify()
            self._connected = True
            log.info("Meerstetter TEC-1089 connected on %s", self._port)
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
                f"Meerstetter connect failed on {self._port}: {e}\n"
                f"Check port name and that nothing else is using it.")

    def disconnect(self) -> None:
        if self._tec:
            try:
                self._tec.session.close()
            except Exception:
                log.debug("MeerstetterDriver.disconnect: session.close() failed — "
                          "port will still be released", exc_info=True)
        self._connected = False
        self._port_lock.release()

    def enable(self) -> None:
        # Parameter 2010: Output Enable (1 = on)
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=1,
                                    address=self._address, instance=1)

    def disable(self) -> None:
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=0,
                                    address=self._address, instance=1)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        # Parameter 3000: Target Object Temperature
        with self._api_lock:
            self._tec.set_parameter(parameter_id=3000, value=temperature_c,
                                    address=self._address, instance=1)

    def get_status(self) -> TecStatus:
        try:
            with self._api_lock:
                # Parameter 1000: Object Temperature (°C)
                actual = self._tec.get_parameter(
                    parameter_id=1000, address=self._address, instance=1)
                # Parameter 1001: Sink Temperature (°C)
                sink = self._tec.get_parameter(
                    parameter_id=1001, address=self._address, instance=1)
                # Parameter 1020: Actual Output Current (A)
                current = self._tec.get_parameter(
                    parameter_id=1020, address=self._address, instance=1)
                # Parameter 1021: Actual Output Voltage (V)
                voltage = self._tec.get_parameter(
                    parameter_id=1021, address=self._address, instance=1)
                # Parameter 1200: Temperature Is Stable flag (0/1)
                hw_stable = bool(self._tec.get_parameter(
                    parameter_id=1200, address=self._address, instance=1))
                # Parameter 2010: Output Enable status (0/1)
                enabled = bool(self._tec.get_parameter(
                    parameter_id=2010, address=self._address, instance=1))

            return TecStatus(
                actual_temp    = float(actual),
                target_temp    = self._target,
                sink_temp      = float(sink),
                output_current = float(current),
                output_voltage = float(voltage),
                output_power   = abs(float(current) * float(voltage)),
                enabled        = enabled,
                stable         = hw_stable,
            )
        except Exception as e:
            return TecStatus(error=str(e))

    # temp_range() and stability_tolerance() are inherited from TecDriver base class,
    # which now correctly sources TEC_OBJECT_MIN_C (15 °C), TEC_OBJECT_MAX_C (130 °C),
    # and TEC_STABILITY_WINDOW_C (±1 °C) from ai.instrument_knowledge.
