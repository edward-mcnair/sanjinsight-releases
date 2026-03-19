"""
hardware/bias/amcad_bilt.py

Driver for the AMCAD BILT Pulsed I-V system.

The BILT is a two-channel (Gate + Drain) pulsed voltage/current source
primarily designed for transistor characterisation.  It communicates via
TCP/IP to a companion Windows process called ``pivserver64.exe`` (or
``pivserver.exe`` on 32-bit hosts) that speaks SCPI over a raw socket.

Architecture
------------
                    ┌──────────────┐   TCP/SCPI   ┌─────────────┐
  SanjINSIGHT  ───► │ AmcadBilt    │ ──────────► │ pivserver64  │ ──► BILT hardware
                    │ Driver       │   port 5035  └─────────────┘
                    └──────────────┘

pivserver64.exe must be running on the same host (or a remote Windows
machine) before ``connect()`` is called.  Launch it from the AMCAD
installation directory, e.g.::

    pivserver64.exe -p 5035

The server connects to the BILT hardware over GPIB and translates SCPI to
the native PIV library calls.

Channels
--------
  Channel 1 — Gate probe  (low-current gate-voltage pulse)
  Channel 2 — Drain probe (high-current drain-voltage/current pulse)

Both channels support independent DC bias and pulsed levels with
per-channel timing (pulse width and delay).

BiasDriver mapping
------------------
``set_mode()``        — both channels to "voltage" or "current" mode
``set_level()``       — drain pulse level (main stimulus)
``set_compliance()``  — ignored (BILT enforces hardware probe limits)
``enable()``          — :OUTPut ON
``disable()``         — :OUTPut OFF
``get_status()``      — reads V/I from both channels via :MEASure

Pulse configuration (BILT-specific)
------------------------------------
Use the ``configure_pulse()`` method to set per-channel bias, pulse
level, and timing before calling ``enable()``.

Config keys (under hardware.bias):
    host:              "127.0.0.1"    IP of machine running pivserver64
    port:              5035           TCP port (default: 5035)
    mode:              "voltage"      channel mode ("voltage" or "current")
    timeout:           5.0            socket timeout in seconds

    # Per-channel pulse defaults (all optional — good for most DUTs)
    gate_bias_v:       -5.0           Gate DC bias (V)
    gate_pulse_v:      -2.2           Gate pulse voltage (V)
    gate_width_s:      1.1e-4         Gate pulse width (s)
    gate_delay_s:      5.0e-6         Gate pulse delay after trigger (s)

    drain_bias_v:       0.0           Drain DC bias (V)
    drain_pulse_v:      1.0           Drain pulse voltage (V)
    drain_width_s:      1.0e-4        Drain pulse width (s)
    drain_delay_s:      1.0e-5        Drain pulse delay after trigger (s)

Notes
-----
- pivserver64.exe is Windows-only; on macOS/Linux use a remote pivot host
  and set ``host`` to its IP address.
- The BILT does not expose a Python API; all control is through SCPI/TCP.
- No third-party Python packages are required for this driver.
"""

import socket
import time
import logging

from .base import BiasDriver, BiasStatus

log = logging.getLogger(__name__)

# SCPI channel indices: BILT enumerates probe channels from 1
_CH_GATE  = 1
_CH_DRAIN = 2

# Default timing from Microsanj PIV1.txt configuration
_DEF_GATE_BIAS    = -5.0
_DEF_GATE_PULSE   = -2.2
_DEF_GATE_WIDTH   = 1.1e-4
_DEF_GATE_DELAY   = 5.0e-6
_DEF_DRAIN_BIAS   =  0.0
_DEF_DRAIN_PULSE  =  1.0
_DEF_DRAIN_WIDTH  = 1.0e-4
_DEF_DRAIN_DELAY  = 1.0e-5


class AmcadBiltDriver(BiasDriver):
    """
    AMCAD BILT pulsed I-V source driver.

    Implements the standard ``BiasDriver`` interface and adds BILT-specific
    pulse-configuration helpers (``configure_pulse()``, ``apply_defaults()``).
    """

    @classmethod
    def preflight(cls) -> tuple:
        # No third-party packages required — stdlib socket only.
        return (True, [])

    # ---------------------------------------------------------------- #
    #  Construction                                                     #
    # ---------------------------------------------------------------- #

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._host    = cfg.get("host",    "127.0.0.1")
        self._port    = int(cfg.get("port", 5035))
        self._timeout = float(cfg.get("timeout", 5.0))
        self._sock: socket.socket | None = None

        # Per-channel pulse defaults (overridable via config)
        self._gate_bias_v   = float(cfg.get("gate_bias_v",   _DEF_GATE_BIAS))
        self._gate_pulse_v  = float(cfg.get("gate_pulse_v",  _DEF_GATE_PULSE))
        self._gate_width_s  = float(cfg.get("gate_width_s",  _DEF_GATE_WIDTH))
        self._gate_delay_s  = float(cfg.get("gate_delay_s",  _DEF_GATE_DELAY))

        self._drain_bias_v  = float(cfg.get("drain_bias_v",  _DEF_DRAIN_BIAS))
        self._drain_pulse_v = float(cfg.get("drain_pulse_v", _DEF_DRAIN_PULSE))
        self._drain_width_s = float(cfg.get("drain_width_s", _DEF_DRAIN_WIDTH))
        self._drain_delay_s = float(cfg.get("drain_delay_s", _DEF_DRAIN_DELAY))

        # Cache last measured values for get_status() fallback
        self._last_vg = 0.0
        self._last_ig = 0.0
        self._last_vd = 0.0
        self._last_id = 0.0
        self._output_on = False

    # ---------------------------------------------------------------- #
    #  BiasDriver lifecycle                                             #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        """Open TCP connection to pivserver64 and initialise the BILT."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self._timeout)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock.connect((self._host, self._port))
        except OSError as exc:
            self._sock = None
            raise RuntimeError(
                f"Cannot connect to AMCAD pivserver64 at "
                f"{self._host}:{self._port} — {exc}\n\n"
                f"Ensure pivserver64.exe is running on the instrument PC.\n"
                f"Launch it with:  pivserver64.exe -p {self._port}\n"
                f"Then verify network connectivity:  ping {self._host}"
            ) from exc

        try:
            idn = self._query("*IDN?")
            log.info("AMCAD BILT connected: %s", idn)
            self._write("*RST")
            time.sleep(0.5)   # BILT needs time to reset

            # Push default pulse configuration
            self.apply_defaults()
            self._connected = True

        except Exception as exc:
            self._close_socket()
            raise RuntimeError(
                f"AMCAD BILT initialisation failed: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Disable output and close TCP socket."""
        if self._connected:
            try:
                self.disable()
            except Exception:
                pass
        self._close_socket()
        self._connected = False

    def _close_socket(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ---------------------------------------------------------------- #
    #  BiasDriver control                                               #
    # ---------------------------------------------------------------- #

    def enable(self) -> None:
        self._write(":OUTPut ON")
        self._output_on = True

    def disable(self) -> None:
        self._write(":OUTPut OFF")
        self._output_on = False

    def set_mode(self, mode: str) -> None:
        """
        Set both channels to voltage or current mode.
        Note: the BILT only supports voltage mode in standard pulsed-IV
        operation.  Current mode is rarely used.
        """
        self._mode = mode
        scpi_mode = "VOLT" if mode == "voltage" else "CURR"
        for ch in (_CH_GATE, _CH_DRAIN):
            self._write(f":SOURce:CHANnel{ch}:FUNCtion {scpi_mode}")

    def set_level(self, value: float) -> None:
        """Set the drain-channel pulse voltage (the primary stimulus level)."""
        self._level = value
        self._drain_pulse_v = value
        attr = "VOLTage:PULSe" if self._mode == "voltage" else "CURRent:PULSe"
        self._write(f":SOURce:CHANnel{_CH_DRAIN}:{attr} {value:.6e}")

    def set_compliance(self, value: float) -> None:
        """
        Compliance is hardware-enforced by the BILT probe itself and cannot
        be set via SCPI.  This method is a no-op but stores the value for
        status reporting consistency.
        """
        self._compliance = value
        log.debug("AMCAD BILT: compliance is probe-limited; "
                  "software override not supported.")

    # ---------------------------------------------------------------- #
    #  BILT-specific pulse configuration                               #
    # ---------------------------------------------------------------- #

    def configure_pulse(
        self, *,
        channel:  int,
        bias_v:   float,
        pulse_v:  float,
        width_s:  float,
        delay_s:  float,
    ) -> None:
        """
        Configure bias, pulse voltage, and timing for one channel.

        Parameters
        ----------
        channel : int
            1 = Gate, 2 = Drain
        bias_v : float
            DC bias voltage applied outside the pulse window (V)
        pulse_v : float
            Voltage during the pulse window (V)
        width_s : float
            Pulse width in seconds (e.g. 1e-4 = 100 µs)
        delay_s : float
            Delay from trigger to pulse start in seconds
        """
        ch = channel
        self._write(f":SOURce:CHANnel{ch}:VOLTage:BIAS  {bias_v:.6e}")
        self._write(f":SOURce:CHANnel{ch}:VOLTage:PULSe {pulse_v:.6e}")
        self._write(f":SOURce:CHANnel{ch}:PULSe:WIDTh   {width_s:.6e}")
        self._write(f":SOURce:CHANnel{ch}:PULSe:DELay   {delay_s:.6e}")
        log.debug(
            "BILT CH%d configured: bias=%.3fV pulse=%.3fV "
            "width=%.2eµs delay=%.2eµs",
            ch, bias_v, pulse_v, width_s * 1e6, delay_s * 1e6
        )

    def apply_defaults(self) -> None:
        """Push the configured default pulse parameters to both channels."""
        self.configure_pulse(
            channel = _CH_GATE,
            bias_v  = self._gate_bias_v,
            pulse_v = self._gate_pulse_v,
            width_s = self._gate_width_s,
            delay_s = self._gate_delay_s,
        )
        self.configure_pulse(
            channel = _CH_DRAIN,
            bias_v  = self._drain_bias_v,
            pulse_v = self._drain_pulse_v,
            width_s = self._drain_width_s,
            delay_s = self._drain_delay_s,
        )

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> BiasStatus:
        """
        Return current BiasStatus.

        Reads actual V/I from both channels via :MEASure:INTernal:DATA:ALL?
        The BILT returns a comma-separated list:
            Vg, Ig, Vd, Id   (all float, SI units)
        """
        try:
            raw = self._query(":MEASure:INTernal:DATA:ALL?")
            # Response: "Vg,Ig,Vd,Id" — may be in scientific notation
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) >= 4:
                self._last_vg = float(parts[0])
                self._last_ig = float(parts[1])
                self._last_vd = float(parts[2])
                self._last_id = float(parts[3])
        except Exception as exc:
            log.warning("BILT get_status measurement failed: %s", exc)
            return BiasStatus(
                output_on      = self._output_on,
                mode           = self._mode,
                setpoint       = self._level,
                actual_voltage = self._last_vd,
                actual_current = self._last_id,
                actual_power   = abs(self._last_vd * self._last_id),
                compliance     = self._compliance,
                error          = str(exc),
            )

        return BiasStatus(
            output_on      = self._output_on,
            mode           = self._mode,
            setpoint       = self._drain_pulse_v,
            actual_voltage = self._last_vd,
            actual_current = self._last_id,
            actual_power   = abs(self._last_vd * self._last_id),
            compliance     = self._compliance,
        )

    # ---------------------------------------------------------------- #
    #  Voltage / current ranges                                         #
    # ---------------------------------------------------------------- #

    def voltage_range(self) -> tuple:
        # BILT-B1 / BILT-B2 modules: ±200 V pulse capability; typical probe ±40 V
        return (-40.0, 40.0)

    def current_range(self) -> tuple:
        # Probe 241 (drain): ±2 A; Gate probe: ±200 mA
        return (-2.0, 2.0)

    # ---------------------------------------------------------------- #
    #  Internal SCPI helpers                                            #
    # ---------------------------------------------------------------- #

    def _write(self, cmd: str) -> None:
        """Send a SCPI command (no response expected)."""
        if self._sock is None:
            raise RuntimeError("AMCAD BILT not connected.")
        msg = (cmd.strip() + "\n").encode()
        self._sock.sendall(msg)
        log.debug("BILT ← %s", cmd.strip())

    def _query(self, cmd: str) -> str:
        """Send a SCPI query and return the response string."""
        self._write(cmd)
        return self._recv()

    def _recv(self) -> str:
        """Read one newline-terminated response line from the socket."""
        buf = b""
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("AMCAD pivserver closed the connection.")
            buf += chunk
            if b"\n" in buf:
                break
        response = buf.split(b"\n")[0].decode(errors="replace").strip()
        log.debug("BILT → %s", response)
        return response

    def __repr__(self):
        return (
            f"<AmcadBiltDriver host={self._host}:{self._port} "
            f"connected={self._connected}>"
        )
