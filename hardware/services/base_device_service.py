"""
hardware/services/base_device_service.py

Common infrastructure for all device services.
"""

from __future__ import annotations

import logging
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class BaseDeviceService(QObject):
    """Common infrastructure shared by all device services.

    Provides:
      * A shared ``_stop_event`` (owned by :class:`HardwareService`)
      * Thread launch helper (``_launch``)
      * Retry-with-backoff connection (``_connect_with_retry``)
      * Auto-reconnect loop (``_reconnect_loop``)
      * Off-thread dispatch helper (``_dispatch``)
    """

    # -- Signals common to every device service ----------------------------
    device_connected = pyqtSignal(str, bool)       # (device_key, is_connected)
    error            = pyqtSignal(str)
    log_message      = pyqtSignal(str)
    startup_status   = pyqtSignal(str, bool, str)   # (key, ok, detail)
    structured_error = pyqtSignal(object)           # DeviceError
    heartbeat        = pyqtSignal(str, float, float) # (device_key, unix_ts, response_time_ms)

    # -- Auto-reconnect policy (same defaults as HardwareService) ----------
    _MAX_CONSECUTIVE_ERRORS: int   = 3
    _RECONNECT_INITIAL_S:    float = 2.0
    _RECONNECT_MAX_S:        float = 30.0

    def __init__(self, stop_event: threading.Event, parent=None):
        super().__init__(parent)
        self._stop_event = stop_event   # shared with HardwareService
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        # Per-device state machines — populated by child services as devices
        # are discovered/connected.  Keyed by device_key ("camera", "tec0", etc.)
        from hardware.device_state import DeviceStateMachine
        self._states: dict[str, DeviceStateMachine] = {}

    # ================================================================ #
    #  Thread infrastructure                                            #
    # ================================================================ #

    def _launch(self, target, args=(), name="svc.thread") -> threading.Thread:
        t = threading.Thread(target=target, args=args, name=name, daemon=True)
        with self._lock:
            self._threads.append(t)
        t.start()
        return t

    def _connect_with_retry(self, connect_fn, *, label: str,
                             max_retries: int = 3,
                             initial_delay_s: float = 2.0) -> None:
        """
        Call *connect_fn()* up to *max_retries* times with exponential backoff.

        Returns silently on first success.
        Raises the last exception if all attempts fail.
        Sleep is interruptible via _stop_event so shutdown is instant.
        """
        delay    = initial_delay_s
        last_exc: Exception | None = None

        from hardware.device_state import DeviceState
        for attempt in range(1, max_retries + 1):
            if self._stop_event.is_set():
                raise RuntimeError("Service stopped during connect retry")
            self._set_device_state(label, DeviceState.CONNECTING)
            try:
                t0 = time.time()
                connect_fn()
                self._set_device_state(label, DeviceState.CONNECTED)
                log.info("[%s] Connected (attempt %d/%.2fs)",
                         label, attempt, time.time() - t0)
                return
            except Exception as exc:
                last_exc = exc
                self._set_device_state(label, DeviceState.ERROR)
                if attempt < max_retries:
                    log.warning(
                        "[%s] Attempt %d/%d failed: %s  -- retrying in %.1fs ...",
                        label, attempt, max_retries, exc, delay)
                    # Interruptible sleep: wakes immediately if service stops.
                    self._stop_event.wait(timeout=delay)
                    delay = min(delay * 1.5, 30.0)   # cap at 30 s
                else:
                    log.error("[%s] All %d attempts failed. Last error: %s",
                              label, max_retries, exc)

        raise last_exc  # type: ignore[misc]

    def _reconnect_loop(self, device_key: str, reconnect_fn, label: str) -> bool:
        """
        Repeatedly call *reconnect_fn()* with exponential back-off until it
        succeeds or the service stops.

        Parameters
        ----------
        device_key  : signal key ('camera', 'tec0', 'fpga', 'bias', 'stage')
        reconnect_fn: callable -- must raise on failure, return on success
        label       : human-readable name for log messages

        Returns
        -------
        True  -- reconnected successfully
        False -- _stop_event was set; caller should return without reconnecting
        """
        from hardware.device_state import DeviceState
        delay   = self._RECONNECT_INITIAL_S
        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            self._set_device_state(device_key, DeviceState.CONNECTING)
            try:
                reconnect_fn()
                self._set_device_state(device_key, DeviceState.CONNECTED)
                log.info("[%s] Auto-reconnect succeeded (attempt %d)", label, attempt)
                self.device_connected.emit(device_key, True)
                self.log_message.emit(f"{label}: reconnected automatically")
                return True
            except Exception as exc:
                self._set_device_state(device_key, DeviceState.ERROR)
                log.warning("[%s] Reconnect attempt %d failed: %s -- retry in %.0f s",
                            label, attempt, exc, delay)
            # Interruptible sleep: wakes instantly when service shuts down
            self._stop_event.wait(timeout=delay)
            delay = min(delay * 1.5, self._RECONNECT_MAX_S)
        return False

    def _set_device_state(self, device_key: str, state) -> None:
        """Transition a device's state machine, creating it on first use."""
        from hardware.device_state import DeviceStateMachine, DeviceState
        if device_key not in self._states:
            self._states[device_key] = DeviceStateMachine(device_key)
        self._states[device_key].transition(state)

    def _get_device_state(self, device_key: str):
        """Return the current DeviceState for *device_key*, or UNKNOWN."""
        from hardware.device_state import DeviceState
        sm = self._states.get(device_key)
        return sm.state if sm else DeviceState.UNKNOWN

    def _emit_heartbeat(self, device_key: str, response_time_s: float) -> None:
        """Emit a heartbeat after a successful poll/status read.

        Parameters
        ----------
        device_key : str
            Signal key (``"tec0"``, ``"camera"``, ``"fpga"``, etc.)
        response_time_s : float
            Wall-clock time of the poll round-trip, in **seconds**.
        """
        self.heartbeat.emit(device_key, time.time(), response_time_s * 1000.0)

    def _classify_and_emit(self, exc: Exception, device_uid: str = "") -> 'DeviceError':
        """Classify an exception and emit both structured_error and error signals.

        Returns the :class:`DeviceError` so callers can use its ``message``
        for the legacy ``startup_status`` detail string.
        """
        from hardware.error_taxonomy import classify_error
        from hardware.device_state import DeviceState
        dev_err = classify_error(exc, device_uid=device_uid)
        self._set_device_state(device_uid, DeviceState.ERROR)
        self.structured_error.emit(dev_err)
        self.error.emit(dev_err.short_message)
        return dev_err

    def _dispatch(self, fn, *args, **kwargs) -> None:
        """Execute fn(*args, **kwargs) on a daemon thread; emit error on failure."""
        name = getattr(fn, '__name__', 'ctrl')
        def _run():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                log.exception("Device service control call failed: %s", name)
                self.error.emit(str(e))
        threading.Thread(target=_run, daemon=True, name=f"svc.ctrl.{name}").start()
