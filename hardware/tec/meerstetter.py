"""
hardware/tec/meerstetter.py

Driver for Meerstetter TEC-1089 controller via pyMeCom library.

Requires: pip install pyMeCom

Config keys (under hardware.tec_meerstetter):
    port:     ""        Serial port (Windows: COMx, macOS: /dev/cu.usbmodemXXX)
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

    # ── TEC-1089 MeCom parameter IDs (Meerstetter application note) ──────────
    # PID parameters
    _PARAM_PID_KP              = 3010   # Proportional gain
    _PARAM_PID_TI              = 3011   # Integral time constant (s)
    _PARAM_PID_TD              = 3012   # Derivative time constant (s)
    # Current limit
    _PARAM_MAX_CURRENT         = 2030   # Maximum current (A)
    # Stability window (software-side; hardware flag 1200 is primary)
    _PARAM_STABILITY_WINDOW    = 3100   # Temperature stability window (°C)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port    = cfg.get("port",    "")
        self._address = cfg.get("address", 2)
        self._timeout = cfg.get("timeout", 2)

        # PID and current parameters — read from config with production defaults
        self._pid_kp             = float(cfg.get("pid_kp",              35.0))
        self._pid_ti             = float(cfg.get("pid_ti",               5.0))
        self._pid_td             = float(cfg.get("pid_td",               0.5))
        self._max_current_a      = float(cfg.get("max_current_a",        9.25))
        self._stability_tol_c    = float(cfg.get("stability_tolerance_c", 1.0))
        self._stability_dur_s    = float(cfg.get("stability_duration_s", 10.0))

        self._tec       = None
        self._target    = 25.0
        self._port_lock = PortLock(self._port)
        # pyMeCom MeCom is not thread-safe; the poll thread and control
        # threads (set_target, enable, disable) must not call it concurrently
        # or they will corrupt each other's serial frames and cause CRC errors.
        self._api_lock  = threading.Lock()

    def connect(self) -> None:
        # Acquire port lock first; release it on any failure (try/finally ensures
        # the lock is released even on BaseException such as KeyboardInterrupt — L-5 fix).
        if not self._port:
            raise RuntimeError(
                "No serial port configured for Meerstetter TEC.\n\n"
                "Set the port in Device Manager (e.g. COM3 on Windows, "
                "/dev/cu.usbmodemXXX on macOS).")
        self._port_lock.acquire()
        _connected_ok = False
        try:
            from mecom import MeCom
            log.info("Meerstetter: opening %s (address=%d, timeout=%.1fs)",
                     self._port, self._address, self._timeout)
            self._tec = MeCom(serialport=self._port,
                              timeout=self._timeout,
                              metype='TEC')
            # Try configured address first, then common defaults, then
            # broadcast (0) as a last resort.  Factory default for the
            # TEC-1089 is address 2; for LDD-1121 it is address 1.
            _identified = False
            _addrs = [self._address]
            for _a in (2, 1, 0):
                if _a not in _addrs:
                    _addrs.append(_a)
            for _try_addr in _addrs:
                try:
                    dev_addr = self._tec.identify(address=_try_addr)
                    log.info("Meerstetter TEC-1089 identified at MeCom "
                             "address %s (queried %d) on %s",
                             dev_addr, _try_addr, self._port)
                    _identified = True
                    break
                except Exception as _id_err:
                    log.debug("identify(address=%d) failed: %s",
                              _try_addr, _id_err)
            if not _identified:
                raise RuntimeError(
                    f"TEC did not respond to identify on {self._port} "
                    f"(tried addresses {_addrs})")
            self._connected = True
            _connected_ok = True
        except ImportError:
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
            err = str(e)
            hints = []
            if "timeout" in err.lower():
                hints.append(
                    "The TEC did not respond — check that:\n"
                    "  • The correct COM port is selected in Device Manager\n"
                    "  • The TEC-1089 is powered on\n"
                    "  • The FTDI USB-serial driver is installed "
                    "(Device Manager → Ports should show the TEC)\n"
                    "  • No other software has the port open")
            raise RuntimeError(
                f"Meerstetter connect failed on {self._port}: {e}\n"
                + ("\n".join(hints) if hints else
                   "Check port name and that nothing else is using it."))
        finally:
            # Release on any exception path; keep held on success (released by disconnect())
            if not _connected_ok:
                self._port_lock.release()

        # Apply production defaults from config after successful connect
        try:
            self._apply_config_params()
        except Exception:
            log.warning(
                "MeerstetterDriver: failed to apply config parameters on connect — "
                "controller will use its stored firmware defaults. "
                "This is non-fatal; check parameter IDs if values are unexpected.",
                exc_info=True)

    def _apply_config_params(self) -> None:
        """
        Push PID gains, current limit, and stability window from config to the
        TEC-1089 over MeCom.  Called once after a successful connect().

        Parameter IDs follow the Meerstetter TEC-1089 firmware parameter table.
        Each write is attempted individually so a single unsupported parameter
        does not abort the rest.
        """
        params = [
            (self._PARAM_PID_KP,           self._pid_kp,          "PID Kp"),
            (self._PARAM_PID_TI,           self._pid_ti,          "PID Ti"),
            (self._PARAM_PID_TD,           self._pid_td,          "PID Td"),
            (self._PARAM_MAX_CURRENT,      self._max_current_a,   "Max current (A)"),
            (self._PARAM_STABILITY_WINDOW, self._stability_tol_c, "Stability window (°C)"),
        ]
        with self._api_lock:
            for param_id, value, name in params:
                try:
                    self._tec.set_parameter(
                        parameter_id=param_id,
                        value=value,
                        address=self._address,
                        parameter_instance=1,
                    )
                    log.debug("TEC-1089 param %d (%s) → %s", param_id, name, value)
                except Exception as exc:
                    log.warning(
                        "TEC-1089 param %d (%s) write failed: %s — skipping",
                        param_id, name, exc)

    def disconnect(self) -> None:
        if self._tec:
            try:
                self._tec.stop()
            except Exception:
                log.debug("MeerstetterDriver.disconnect: stop() failed — "
                          "port will still be released", exc_info=True)
        self._connected = False
        self._port_lock.release()

    def enable(self) -> None:
        # Parameter 2010: Output Enable (1 = on)
        if self._tec is None:
            log.warning("MeerstetterDriver.enable() called before connect()")
            return
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=1,
                                    address=self._address, parameter_instance=1)

    def disable(self) -> None:
        if self._tec is None:
            log.warning("MeerstetterDriver.disable() called before connect()")
            return
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=0,
                                    address=self._address, parameter_instance=1)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        if self._tec is None:
            log.warning("MeerstetterDriver.set_target() called before connect()")
            return
        # Parameter 3000: Target Object Temperature
        with self._api_lock:
            self._tec.set_parameter(parameter_id=3000, value=temperature_c,
                                    address=self._address, parameter_instance=1)

    def get_status(self) -> TecStatus:
        try:
            with self._api_lock:
                # Parameter 1000: Object Temperature (°C)
                actual = self._tec.get_parameter(
                    parameter_id=1000, address=self._address, parameter_instance=1)
                # Parameter 1001: Sink Temperature (°C)
                sink = self._tec.get_parameter(
                    parameter_id=1001, address=self._address, parameter_instance=1)
                # Parameter 1020: Actual Output Current (A)
                current = self._tec.get_parameter(
                    parameter_id=1020, address=self._address, parameter_instance=1)
                # Parameter 1021: Actual Output Voltage (V)
                voltage = self._tec.get_parameter(
                    parameter_id=1021, address=self._address, parameter_instance=1)
                # Parameter 1200: Temperature Is Stable flag (0/1)
                hw_stable = bool(self._tec.get_parameter(
                    parameter_id=1200, address=self._address, parameter_instance=1))
                # Parameter 2010: Output Enable status (0/1)
                enabled = bool(self._tec.get_parameter(
                    parameter_id=2010, address=self._address, parameter_instance=1))

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
