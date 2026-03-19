"""
hardware/monochromator/cornerstone.py

Driver for Newport / Oriel Cornerstone 130, 260, and 74000 series
monochromators via their ASCII serial command protocol.

Communication
-------------
The Cornerstone family uses a simple RS-232 command protocol:
  - Commands are ASCII strings terminated with ``\\r\\n``.
  - Responses end with ``\\r\\n``.
  - Long-running commands (GOWAVE) respond with ``ok\\r\\n`` when done.

Key commands used by this driver
---------------------------------
    MONO-RESET          Initialise the monochromator (sent on connect)
    GOWAVE <nm>         Move grating to wavelength; blocks until ``ok``
    WAVE?               Query current wavelength → "WAVE 532.000\\r\\n"
    SHUTTER OPEN        Open internal shutter
    SHUTTER CLOSE       Close internal shutter
    SHUTTER?            Query shutter state → "SHUTTER OPEN\\r\\n" / "SHUTTER CLOSE\\r\\n"
    MONO-WMIN?          Query minimum wavelength → "MONO-WMIN 0.000\\r\\n"
    MONO-WMAX?          Query maximum wavelength → "MONO-WMAX 1400.000\\r\\n"

Requires
--------
    pyserial  (pip install pyserial)

Config keys (under hardware.monochromator)
------------------------------------------
    port:       "COM5"   Serial port (Windows: COMx, Mac/Linux: /dev/ttyUSBx)
    baudrate:   9600     Default baud rate for Cornerstone instruments
    timeout:    10.0     Seconds to wait for each response (moves can be slow)
"""

import logging
import threading
import time

from .base import MonochromatorDriver, MonochromatorStatus

log = logging.getLogger(__name__)

# Newport Cornerstone default communication parameters
_DEFAULT_BAUDRATE  = 9600
_DEFAULT_TIMEOUT   = 10.0    # seconds — grating moves can take several seconds
_RESET_TIMEOUT     = 30.0    # seconds — MONO-RESET can take up to ~20 s
_INTER_CMD_DELAY   = 0.05    # seconds — small guard between sequential commands
_TERMINATOR        = b"\r\n"


class CornerstoneMonochromator(MonochromatorDriver):
    """
    Newport / Oriel Cornerstone monochromator driver via RS-232.

    All public methods are thread-safe: a single lock serialises access to the
    serial port so that the UI can poll ``get_status()`` concurrently while a
    sweep is running in a worker thread.
    """

    DRIVER_TYPE = "cornerstone"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        port:     str   = "COM5",
        baudrate: int   = _DEFAULT_BAUDRATE,
        timeout:  float = _DEFAULT_TIMEOUT,
    ):
        super().__init__()
        self._port     = port
        self._baudrate = baudrate
        self._timeout  = timeout
        self._serial   = None          # pyserial Serial instance
        self._lock     = threading.Lock()
        self._min_nm   = 0.0           # populated from MONO-WMIN? on connect
        self._max_nm   = 9999.0        # populated from MONO-WMAX? on connect
        # Use a threading.Event so that _cancel_sweep is set/cleared atomically
        # from any thread without needing the lock (L-8 fix).
        self._cancel_sweep = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def preflight(cls) -> tuple[bool, list[str]]:
        issues: list[str] = []
        try:
            import serial  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial not found — Newport Cornerstone support unavailable.\n"
                "Install it with:  pip install pyserial\n"
                "After installing, restart the application."
            )
        return (len(issues) == 0, issues)

    def connect(self) -> None:
        """Open the serial port and reset the monochromator.

        .. warning::
            This method blocks for up to ``_RESET_TIMEOUT`` seconds (30 s by
            default) while the MONO-RESET homing sequence runs.  Always call
            ``connect()`` from a background thread — never from a UI slot or
            the main event loop.
        """
        # W-1 — reject /dev/tty* port names on Windows where only COMx is valid
        import sys as _sys
        if _sys.platform == "win32" and self._port.startswith("/dev/"):
            raise RuntimeError(
                f"Invalid serial port {self._port!r} on Windows.\n\n"
                f"Windows serial ports are named 'COMx' (e.g. 'COM5').\n"
                f"Update hardware.monochromator.port in config.yaml."
            )
        try:
            import serial
        except ImportError:
            raise RuntimeError(
                "pyserial is not installed.\n\n"
                "The Newport Cornerstone driver requires pyserial for serial "
                "communication.\n\n"
                "Install it with:\n"
                "    pip install pyserial\n\n"
                "After installing, restart the application."
            )

        with self._lock:
            try:
                self._serial = serial.Serial(
                    port=self._port,
                    baudrate=self._baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=self._timeout,
                )
            except serial.SerialException as exc:
                raise RuntimeError(
                    f"Cannot open serial port {self._port!r}.\n\n"
                    f"Check that:\n"
                    f"  • The Cornerstone USB-to-serial adapter is connected.\n"
                    f"  • The port name is correct (config.yaml → hardware.monochromator.port).\n"
                    f"  • No other application has the port open.\n\n"
                    f"System error: {exc}"
                ) from exc

            # Allow the adapter's internal UART to settle
            time.sleep(0.1)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # MONO-RESET homes the grating and can take up to ~20 seconds
            old_timeout = self._serial.timeout
            self._serial.timeout = _RESET_TIMEOUT
            try:
                response = self._transact_locked("MONO-RESET")
                if response.lower() not in ("ok", "mono-reset"):
                    log.warning(
                        "Unexpected response to MONO-RESET: %r", response)
            finally:
                self._serial.timeout = old_timeout

            # Read wavelength limits from the instrument
            try:
                wmin_resp = self._transact_locked("MONO-WMIN?")
                self._min_nm = self._parse_float_response(wmin_resp, "MONO-WMIN")
            except Exception as exc:
                log.warning("Could not read MONO-WMIN?: %s — using 0.0 nm", exc)
                self._min_nm = 0.0

            try:
                wmax_resp = self._transact_locked("MONO-WMAX?")
                self._max_nm = self._parse_float_response(wmax_resp, "MONO-WMAX")
            except Exception as exc:
                log.warning(
                    "Could not read MONO-WMAX?: %s — using 9999.0 nm", exc)
                self._max_nm = 9999.0

            self._connected = True
            log.info(
                "Cornerstone connected on %s  (%.0f–%.0f nm)",
                self._port, self._min_nm, self._max_nm,
            )

    def disconnect(self) -> None:
        """Close shutter, cancel any running sweep, and close the port."""
        self._cancel_sweep.set()
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._transact_locked("SHUTTER CLOSE")
                except Exception:
                    pass
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial    = None
            self._connected = False
        log.info("Cornerstone disconnected from %s", self._port)

    # ------------------------------------------------------------------
    # Wavelength control
    # ------------------------------------------------------------------

    def set_wavelength(self, nm: float) -> None:
        """Move the grating to ``nm`` nanometres (blocking)."""
        self._assert_connected()
        self._validate_wavelength(nm)
        with self._lock:
            response = self._transact_locked(f"GOWAVE {nm:.3f}")
        if response.lower() != "ok":
            raise RuntimeError(
                f"Cornerstone did not acknowledge GOWAVE {nm:.3f}: {response!r}"
            )
        log.debug("Cornerstone → %.3f nm", nm)

    def get_wavelength(self) -> float:
        """Query and return current wavelength in nm."""
        self._assert_connected()
        with self._lock:
            response = self._transact_locked("WAVE?")
        return self._parse_float_response(response, "WAVE")

    # ------------------------------------------------------------------
    # Shutter control
    # ------------------------------------------------------------------

    def set_shutter(self, open: bool) -> None:
        """Open or close the internal shutter."""
        self._assert_connected()
        cmd = "SHUTTER OPEN" if open else "SHUTTER CLOSE"
        with self._lock:
            response = self._transact_locked(cmd)
        if response.lower() != "ok":
            raise RuntimeError(
                f"Cornerstone did not acknowledge {cmd}: {response!r}"
            )

    def get_shutter(self) -> bool:
        """Return ``True`` if the shutter is open."""
        self._assert_connected()
        with self._lock:
            response = self._transact_locked("SHUTTER?")
        # Response: "SHUTTER OPEN" or "SHUTTER CLOSE"
        return "OPEN" in response.upper()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> MonochromatorStatus:
        """Return a status snapshot without raising on transient errors."""
        if not self._connected:
            return MonochromatorStatus(connected=False)
        try:
            with self._lock:
                wave_resp    = self._transact_locked("WAVE?")
                shutter_resp = self._transact_locked("SHUTTER?")
            wavelength = self._parse_float_response(wave_resp, "WAVE")
            shutter    = "OPEN" in shutter_resp.upper()
            return MonochromatorStatus(
                wavelength_nm=wavelength,
                shutter_open=shutter,
                connected=True,
                error_msg=None,
            )
        except Exception as exc:
            return MonochromatorStatus(
                connected=True,
                error_msg=str(exc),
            )

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------

    def scan_wavelengths(
        self,
        start_nm:  float,
        end_nm:    float,
        step_nm:   float,
        dwell_ms:  float,
        callback,
    ) -> None:
        """
        Sweep from ``start_nm`` to ``end_nm`` in ``step_nm`` increments.
        Blocks until the sweep is complete or cancelled.
        """
        self._assert_connected()
        if step_nm <= 0:
            raise ValueError(f"step_nm must be positive, got {step_nm!r}")
        self._validate_wavelength(start_nm)
        self._validate_wavelength(end_nm)

        # Build step list up front so total is known
        steps: list[float] = []
        nm = start_nm
        while nm <= end_nm + 1e-9:
            steps.append(round(nm, 4))
            nm += step_nm
        total = len(steps)

        dwell_s = dwell_ms / 1000.0
        self._cancel_sweep.clear()

        for i, target_nm in enumerate(steps):
            if self._cancel_sweep.is_set():
                log.debug("Sweep cancelled at step %d/%d", i, total)
                break

            # Move grating (blocking — instrument sends "ok" when done)
            self.set_wavelength(target_nm)

            # Dwell
            if dwell_s > 0:
                time.sleep(dwell_s)

            try:
                callback(target_nm, i, total)
            except StopIteration:
                log.debug(
                    "Sweep cancelled by callback at %.1f nm", target_nm)
                break

        log.debug("Sweep complete")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def wavelength_range(self) -> tuple[float, float]:
        return (self._min_nm, self._max_nm)

    @property
    def name(self) -> str:
        return f"Newport Cornerstone ({self._port})"

    # ------------------------------------------------------------------
    # Internal helpers  (must be called with self._lock already held
    #                    where indicated, or hold it explicitly)
    # ------------------------------------------------------------------

    def _transact_locked(self, command: str) -> str:
        """
        Send ``command`` and return the stripped response string.

        Must be called while ``self._lock`` is held (or from connect/disconnect
        which hold the lock themselves when needed).  This helper does NOT
        acquire the lock.
        """
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial port is not open.")

        raw_cmd = (command + "\r\n").encode("ascii")
        self._serial.write(raw_cmd)
        self._serial.flush()
        time.sleep(_INTER_CMD_DELAY)

        raw_resp = self._serial.read_until(_TERMINATOR)
        if not raw_resp:
            raise RuntimeError(
                f"Timeout waiting for response to {command!r} on {self._port}. "
                f"Check that the instrument is powered on and the cable is secure."
            )
        return raw_resp.decode("ascii", errors="replace").strip()

    @staticmethod
    def _parse_float_response(response: str, prefix: str) -> float:
        """
        Extract a float from a response of the form ``"PREFIX 532.000"``.

        Parameters
        ----------
        response:
            The stripped response string from the instrument.
        prefix:
            The expected keyword prefix (e.g. ``"WAVE"``).

        Returns
        -------
        float

        Raises
        ------
        ValueError
            If the response cannot be parsed.
        """
        upper = response.upper()
        token = prefix.upper()
        if upper.startswith(token):
            tail = response[len(token):].strip()
        else:
            # Fallback: try to parse whatever is there
            tail = response.strip()
        try:
            return float(tail)
        except ValueError:
            raise ValueError(
                f"Cannot parse float from Cornerstone response: {response!r} "
                f"(expected prefix {prefix!r})"
            )

    def _assert_connected(self) -> None:
        if not self._connected or self._serial is None:
            raise RuntimeError(
                "Cornerstone monochromator is not connected. Call connect() first."
            )

    def _validate_wavelength(self, nm: float) -> None:
        if not (self._min_nm <= nm <= self._max_nm):
            raise ValueError(
                f"Wavelength {nm:.3f} nm is outside the instrument range "
                f"({self._min_nm:.0f}–{self._max_nm:.0f} nm)."
            )
