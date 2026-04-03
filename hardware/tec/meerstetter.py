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
        self._port     = cfg.get("port",     "")
        self._address  = cfg.get("address",  2)
        self._timeout  = cfg.get("timeout",  2)
        self._baudrate = int(cfg.get("baudrate", 57600))

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
        # ── Auto-port detection ──────────────────────────────────────────
        # If no port is configured, or the configured port doesn't respond,
        # scan all FTDI serial ports for a Meerstetter device at the expected
        # MeCom address.  This eliminates the #1 support issue: wrong COM port.
        if not self._port:
            log.info("Meerstetter: no port configured — running auto-detection…")
            self._auto_detect_port()
        if not self._port:
            raise RuntimeError(
                "No serial port configured for Meerstetter TEC.\n\n"
                "Set the port in Device Manager (e.g. COM3 on Windows, "
                "/dev/cu.usbmodemXXX on macOS).")
        self._port_lock.acquire()
        _connected_ok = False
        try:
            from mecom import MeCom
            log.info("Meerstetter: opening %s (baud=%d, address=%d, timeout=%.1fs)",
                     self._port, self._baudrate, self._address, self._timeout)
            self._tec = MeCom(serialport=self._port,
                              baudrate=self._baudrate,
                              timeout=self._timeout,
                              metype='TEC')
            # Try configured address first, then common defaults, then
            # broadcast (0) as a last resort.  Factory default for the
            # TEC-1089 is address 2; for LDD-1121 it is address 1.
            #
            # Two full passes: USB hubs (especially Thunderbolt docks) can
            # add latency to the first serial transaction after opening the
            # port.  A second pass catches devices that were slow to respond
            # on the first attempt.
            _identified = False
            _addrs = [self._address]
            for _a in (2, 1, 0):
                if _a not in _addrs:
                    _addrs.append(_a)
            _last_err = None
            for _pass_num in range(2):
                for _try_addr in _addrs:
                    try:
                        dev_addr = self._tec.identify(address=_try_addr)
                        log.info("Meerstetter TEC-1089 identified at MeCom "
                                 "address %s (queried %d) on %s (pass %d)",
                                 dev_addr, _try_addr, self._port, _pass_num + 1)
                        _identified = True
                        break
                    except Exception as _id_err:
                        _last_err = _id_err
                        log.debug("identify(address=%d, pass=%d) failed: %s",
                                  _try_addr, _pass_num + 1, _id_err)
                if _identified:
                    break
                if _pass_num == 0:
                    # Brief pause before retry — gives USB hub time to settle
                    import time
                    time.sleep(0.5)
                    log.debug("Meerstetter: first pass failed, retrying...")
            if not _identified:
                # ── Fallback: scan other ports before giving up ──────────
                log.info("Meerstetter: %s did not respond — scanning other ports…",
                         self._port)
                try:
                    self._tec.stop()
                except Exception:
                    pass
                self._tec = None
                self._port_lock.release()
                _connected_ok = False  # ensure lock release in finally

                alt_port = self._auto_detect_port(exclude=[self._port])
                if alt_port:
                    # Retry on the newly discovered port
                    log.info("Meerstetter: retrying on auto-detected port %s", alt_port)
                    self._port = alt_port
                    self._port_lock = PortLock(self._port)
                    self._port_lock.acquire()
                    self._tec = MeCom(serialport=self._port,
                                      baudrate=self._baudrate,
                                      timeout=self._timeout,
                                      metype='TEC')
                    dev_addr = self._tec.identify(address=self._address)
                    log.info("Meerstetter TEC-1089 identified at address %s on %s "
                             "(auto-detected)", dev_addr, self._port)
                    _identified = True
                else:
                    # Build a detailed diagnostic message
                    _diag = (
                        f"TEC did not respond on {self._port} or any other port "
                        f"(tried addresses {_addrs}, 2 passes, full port scan)\n\n"
                        f"Last error: {_last_err}\n\n"
                        "Troubleshooting:\n"
                        "  1. Is the TEC-1089 powered on? (check front-panel LED)\n"
                        "     The TEC needs its own DC power supply — USB alone\n"
                        "     is not sufficient.\n"
                        "  2. Is the USB cable connected? Check Device Manager →\n"
                        "     Ports for an FTDI USB Serial Port.\n"
                        "  3. If using a USB hub, try connecting directly to the\n"
                        "     computer.\n"
                        "  4. Verify the FTDI driver is installed (Device Manager\n"
                        "     should show 'USB Serial Port', not 'Unknown Device').\n"
                        "  5. Try unplugging and re-plugging the USB cable.\n\n"
                        "Run tools/scan_hardware.py for detailed diagnostics."
                    )
                    raise RuntimeError(_diag)
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
        log.debug("TEC set_parameter(2010, 1) — Output Enable ON")
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=1,
                                    address=self._address, parameter_instance=1)

    def disable(self) -> None:
        if self._tec is None:
            log.warning("MeerstetterDriver.disable() called before connect()")
            return
        log.debug("TEC set_parameter(2010, 0) — Output Enable OFF")
        with self._api_lock:
            self._tec.set_parameter(parameter_id=2010, value=0,
                                    address=self._address, parameter_instance=1)

    def set_target(self, temperature_c: float) -> None:
        self._target = temperature_c
        if self._tec is None:
            log.warning("MeerstetterDriver.set_target() called before connect()")
            return
        log.debug("TEC set_parameter(3000, %.3f) — Target Temperature", temperature_c)
        # Parameter 3000: Target Object Temperature
        with self._api_lock:
            self._tec.set_parameter(parameter_id=3000, value=temperature_c,
                                    address=self._address, parameter_instance=1)

    def get_status(self) -> TecStatus:
        import time as _time
        try:
            _t0 = _time.perf_counter()
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

            _elapsed = (_time.perf_counter() - _t0) * 1000.0
            log.debug("TEC get_status: T=%.2f°C sink=%.2f°C I=%.3fA V=%.2fV "
                       "stable=%s enabled=%s  (%.0f ms)",
                       float(actual), float(sink), float(current),
                       float(voltage), hw_stable, enabled, _elapsed)

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
            log.debug("TEC get_status FAILED: %s", e)
            return TecStatus(error=str(e))

    def _auto_detect_port(self, exclude: list[str] | None = None) -> str | None:
        """Scan FTDI serial ports for a Meerstetter device at our address.

        Returns the port path if found, or None.  Does NOT modify self._port
        — the caller is responsible for updating.
        """
        try:
            from hardware.protocol_prober import find_device_port, _MECOM_ADDRESS_MAP

            # Determine our device UID from our address
            device_uid = _MECOM_ADDRESS_MAP.get(self._address, "")
            if not device_uid:
                device_uid = "meerstetter_tec_1089"  # sensible default

            found = find_device_port(
                device_uid=device_uid,
                baudrate=self._baudrate,
                timeout=1.5,
                progress_cb=lambda msg: log.info("AutoDetect: %s", msg),
            )

            if found and (not exclude or found not in exclude):
                log.info("Meerstetter auto-detect: found %s on %s", device_uid, found)
                # Persist the port change so the user doesn't hit this again
                try:
                    from hardware.smart_connect import _persist_port_change
                    _persist_port_change(device_uid, found)
                except Exception:
                    log.debug("Auto-detect: could not persist port change",
                              exc_info=True)
                return found

        except ImportError:
            log.debug("Auto-detect: protocol_prober not available", exc_info=True)
        except Exception:
            log.debug("Auto-detect: scan failed", exc_info=True)

        return None

    # temp_range() and stability_tolerance() are inherited from TecDriver base class,
    # which now correctly sources TEC_OBJECT_MIN_C (15 °C), TEC_OBJECT_MAX_C (130 °C),
    # and TEC_STABILITY_WINDOW_C (±1 °C) from ai.instrument_knowledge.
