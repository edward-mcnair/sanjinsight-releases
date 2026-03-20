"""
hardware/tec/thermal_chuck.py

Driver for thermal chuck controllers — temperature-controlled wafer-holding
platforms used in probe stations for wafer-level device testing.

Implements the standard TecDriver interface so the thermal chuck appears as
an additional temperature controller in the Temperature tab alongside any
Meerstetter TECs.  The ThermalGuard overtemperature protection applies equally.

Supported controllers (all use ASCII serial):
  - Temptronic ATS-series (Thermostream compatible)
  - FormFactor / Cascade Microtech thermal chuck controllers
  - Wentworth Laboratories thermal chuck systems
  - Generic ASCII chuck (configurable command templates)

Protocol (Temptronic / compatible):
  Set temp   → "SETP <value>\\r\\n"  (or "SETP?<value>" — variant 1)
  Get temp   → "TEMP?\\r\\n"         response: "<float>\\r\\n"
  Output ON  → "COND\\r\\n"          or "OPER\\r\\n" depending on controller model
  Output OFF → "STBY\\r\\n"          (standby)
  Query stable → "RAMP?\\r\\n"       response: "0" (ramp done) or "1" (ramping)

All commands and responses are ASCII.  The protocol variant (standard or
alternate command set) is selectable via config key "protocol".

Config keys (under hardware.thermal_chuck):
    port:       "COM5"          Serial port
    baud:       9600            Baud rate (Temptronic default: 9600)
    timeout:    5.0             Serial timeout in seconds (chuck ramp is slow)
    protocol:   "temptronic"    "temptronic" | "cascade" | "wentworth" | "generic"

    # For "generic" protocol, override the command strings:
    cmd_set_temp:    "SETP {temp:.1f}"
    cmd_get_temp:    "TEMP?"
    cmd_output_on:   "COND"
    cmd_output_off:  "STBY"
    cmd_is_stable:   "RAMP?"
    resp_stable:     "0"        # Response string indicating "not ramping" = stable

Temperature range (override defaults from TecDriver base):
    temp_min:   -65.0           °C (chuck can cool significantly below ambient)
    temp_max:   250.0           °C (high-temp chuck)
"""

import logging
import time
import threading
from .base import TecDriver, TecStatus
from hardware.port_lock import PortLock

log = logging.getLogger(__name__)


# ── Protocol command sets ─────────────────────────────────────────────────────

_PROTOCOLS: dict[str, dict] = {
    "temptronic": {
        "cmd_set_temp":  "SETP {temp:.1f}",
        "cmd_get_temp":  "TEMP?",
        "cmd_output_on": "COND",
        "cmd_output_off":"STBY",
        "cmd_is_stable": "RAMP?",
        "resp_stable":   "0",
    },
    "cascade": {
        # Cascade / FormFactor uses same structure with slightly different keywords
        "cmd_set_temp":  "SETP {temp:.2f}",
        "cmd_get_temp":  "MEAS:TEMP?",
        "cmd_output_on": "OPER",
        "cmd_output_off":"STBY",
        "cmd_is_stable": "STAT?",
        "resp_stable":   "READY",
    },
    "wentworth": {
        "cmd_set_temp":  "ST {temp:.1f}",
        "cmd_get_temp":  "RT",
        "cmd_output_on": "ON",
        "cmd_output_off":"OFF",
        "cmd_is_stable": "IS",
        "resp_stable":   "1",
    },
    "generic": {
        # Filled in from config at runtime
        "cmd_set_temp":  "SETP {temp:.1f}",
        "cmd_get_temp":  "TEMP?",
        "cmd_output_on": "ON",
        "cmd_output_off":"OFF",
        "cmd_is_stable": "STABLE?",
        "resp_stable":   "1",
    },
}


class ThermalChuckDriver(TecDriver):
    """
    TEC-compatible driver for serial ASCII thermal chuck controllers.

    The chuck uses TecDriver's interface exactly:
        connect() / disconnect()
        set_target(temp_c)
        enable()  / disable()
        get_status() → TecStatus
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port    = cfg.get("port",     "")
        self._baud    = int(cfg.get("baud",  9600))
        self._timeout = float(cfg.get("timeout", 5.0))

        # Temperature range — chuck has much wider range than TEC1089
        self._temp_min = float(cfg.get("temp_min", -65.0))
        self._temp_max = float(cfg.get("temp_max", 250.0))

        # Stability window (chucks are slower / less precise than Meerstetter)
        self._stab_tol = float(cfg.get("stability_tolerance_c", 2.0))

        # Protocol
        proto_name = cfg.get("protocol", "temptronic").lower()
        proto = dict(_PROTOCOLS.get(proto_name, _PROTOCOLS["generic"]))
        # Allow per-key overrides in config
        for key in ("cmd_set_temp", "cmd_get_temp", "cmd_output_on",
                    "cmd_output_off", "cmd_is_stable", "resp_stable"):
            if key in cfg:
                proto[key] = cfg[key]
        self._proto = proto

        self._ser       = None
        self._target    = 25.0
        self._enabled   = False
        self._port_lock = PortLock(self._port)
        self._lock      = threading.Lock()

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        if not self._port:
            raise RuntimeError(
                "No serial port configured for thermal chuck.\n\n"
                "Set the port in Device Manager (e.g. COM5 on Windows, "
                "/dev/cu.usbmodemXXX on macOS).")
        try:
            import serial
        except ImportError:
            raise RuntimeError(
                "pyserial not installed.  Run: pip install pyserial")
        try:
            self._port_lock.acquire()
            self._ser = serial.Serial(
                self._port, self._baud,
                timeout=self._timeout,
                write_timeout=self._timeout)
            self._connected = True
            log.info("Thermal chuck connected on %s  (%d baud)",
                     self._port, self._baud)
        except Exception as e:
            self._port_lock.release()
            raise RuntimeError(
                f"Thermal chuck connect failed on {self._port}: {e}")

    def disconnect(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self._connected = False
        self._enabled   = False
        try:
            self._port_lock.release()
        except Exception:
            pass
        log.info("Thermal chuck disconnected from %s", self._port)

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    def enable(self) -> None:
        with self._lock:
            self._send(self._proto["cmd_output_on"])
            self._enabled = True
            log.info("[CHUCK] Output ON (setpoint %.1f°C)", self._target)

    def disable(self) -> None:
        with self._lock:
            self._send(self._proto["cmd_output_off"])
            self._enabled = False
            log.info("[CHUCK] Output OFF (standby)")

    def set_target(self, temperature_c: float) -> None:
        t = max(self._temp_min, min(self._temp_max, temperature_c))
        with self._lock:
            cmd = self._proto["cmd_set_temp"].format(temp=t)
            self._send(cmd)
            self._target = t
            log.info("[CHUCK] Setpoint → %.1f°C", t)

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> TecStatus:
        with self._lock:
            try:
                # Read actual temperature
                resp = self._query(self._proto["cmd_get_temp"])
                actual = float(resp.strip())

                # Check stability
                stable_resp = self._query(self._proto["cmd_is_stable"])
                is_stable = (stable_resp.strip() == self._proto["resp_stable"])

                return TecStatus(
                    actual_temp    = actual,
                    target_temp    = self._target,
                    sink_temp      = 0.0,      # chuck does not report sink temp
                    output_current = 0.0,      # not reported by ASCII protocol
                    output_voltage = 0.0,
                    output_power   = 0.0,
                    enabled        = self._enabled,
                    stable         = is_stable,
                )
            except Exception as e:
                return TecStatus(
                    target_temp = self._target,
                    enabled     = self._enabled,
                    error       = str(e),
                )

    # ---------------------------------------------------------------- #
    #  Range overrides                                                  #
    # ---------------------------------------------------------------- #

    def temp_range(self) -> tuple:
        """Thermal chuck has much wider range than TEC1089."""
        return (self._temp_min, self._temp_max)

    def stability_tolerance(self) -> float:
        """Chucks are slower and less precise than Meerstetter TECs."""
        return self._stab_tol

    # ---------------------------------------------------------------- #
    #  Serial helpers                                                   #
    # ---------------------------------------------------------------- #

    def _send(self, command: str) -> None:
        """Send a command string (adds \\r\\n, flushes)."""
        if self._ser is None:
            raise RuntimeError("Chuck not connected.")
        raw = (command + "\r\n").encode("ascii")
        self._ser.write(raw)
        self._ser.flush()

    def _query(self, command: str) -> str:
        """Send a command and return the response line."""
        self._send(command)
        time.sleep(0.05)   # brief delay for controller response
        raw = self._ser.readline()
        return raw.decode("ascii", errors="replace").strip()
