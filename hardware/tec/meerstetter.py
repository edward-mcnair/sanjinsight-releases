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
from .base import TecDriver, TecStatus
from hardware.port_lock import PortLock

log = logging.getLogger(__name__)

log = logging.getLogger(__name__)


class MeerstetterDriver(TecDriver):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port    = cfg.get("port",    "COM3")
        self._address = cfg.get("address", 2)
        self._timeout = cfg.get("timeout", 1.0)
        self._tec       = None
        self._target    = 25.0
        self._port_lock = PortLock(self._port)

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
                "pyMeCom not installed. Run: pip install pyMeCom")
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
                pass
        self._connected = False
        self._port_lock.release()

    def enable(self) -> None:
        # Parameter 2010: Output Enable (1 = on)
        self._tec.set_parameter(parameter_id=2010, value=1,
                                address=self._address, instance=1)

    def disable(self) -> None:
        self._tec.set_parameter(parameter_id=2010, value=0,
                                address=self._address, instance=1)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        # Parameter 3000: Target Object Temperature
        self._tec.set_parameter(parameter_id=3000, value=temperature_c,
                                address=self._address, instance=1)

    def get_status(self) -> TecStatus:
        try:
            # Parameter 1000: Object Temperature
            actual = self._tec.get_parameter(
                parameter_id=1000, address=self._address, instance=1)
            # Parameter 1001: Output Current
            current = self._tec.get_parameter(
                parameter_id=1001, address=self._address, instance=1)
            # Parameter 1002: Output Voltage
            voltage = self._tec.get_parameter(
                parameter_id=1002, address=self._address, instance=1)
            # Parameter 2010: Output Enable status
            enabled = bool(self._tec.get_parameter(
                parameter_id=2010, address=self._address, instance=1))

            stable = abs(actual - self._target) <= self.stability_tolerance()

            return TecStatus(
                actual_temp    = float(actual),
                target_temp    = self._target,
                output_current = float(current),
                output_voltage = float(voltage),
                output_power   = abs(float(current) * float(voltage)),
                enabled        = enabled,
                stable         = stable,
            )
        except Exception as e:
            return TecStatus(error=str(e))

    def temp_range(self) -> tuple:
        return (-40.0, 150.0)
