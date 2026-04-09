"""
hardware/thermal_guard.py

ThermalGuard — per-TEC temperature alarm system.

Monitors every TEC status poll and transitions through three states:

    NORMAL   — temperature within safe operating range
    WARNING  — temperature within `warning_margin` °C of a limit
               (user is notified but TEC keeps running)
    ALARM    — temperature has exceeded a hard limit
               (TEC output is immediately disabled, alarm latches)

The alarm LATCHES in ALARM state — the TEC cannot be re-enabled
until `acknowledge()` is called from the UI. This is intentional
safety behaviour: a momentary exceedance should not be silently
recovered from.

Hysteresis prevents oscillation at the boundary: the alarm clears
only when temperature returns `hysteresis` °C inside the limit.

Thread-safety
-------------
All state mutations happen under ``_lock``.  External side-effects —
``tec.disable()``, ``on_alarm()``, ``on_warning()``, ``on_clear()`` —
are executed **outside** the lock to prevent deadlock if a callback
re-enters the guard or acquires other locks.

Usage (called from HardwareService._run_tec poll loop)
------
    guard = ThermalGuard(
        index=0,
        tec=tec_driver,
        cfg={"temp_min": -10.0, "temp_max": 85.0,
             "temp_warning_margin": 5.0},
        on_alarm=lambda idx, msg, actual, limit: ...,
        on_warning=lambda idx, msg, actual, limit: ...,
        on_clear=lambda idx: ...,
    )

    # In poll loop:
    status = tec.get_status()
    guard.check(status)          # may call callbacks and/or disable TEC
"""

from __future__ import annotations
import logging
import math
import threading
from enum import Enum, auto
from typing import Callable, Optional

from hardware.tec.base import TecStatus

log = logging.getLogger(__name__)


class AlarmState(Enum):
    NORMAL  = auto()
    WARNING = auto()
    ALARM   = auto()


# Internal action descriptors — returned by locked state-decision code,
# executed outside the lock by the caller.
_ACTION_NONE    = "none"
_ACTION_ALARM   = "alarm"
_ACTION_WARNING = "warning"
_ACTION_CLEAR   = "clear"


class ThermalGuard:
    """
    Safety monitor for a single TEC channel.

    Parameters
    ----------
    index           : int            — TEC index (0, 1, …)
    tec             : TecDriver      — driver to call .disable() on alarm
    cfg             : dict           — hardware config for this TEC
    on_alarm        : callable       — (index, message, actual, limit) → None
    on_warning      : callable       — (index, message, actual, limit) → None
    on_clear        : callable       — (index) → None
    """

    # How far inside the limit temperature must return before WARNING clears
    _HYSTERESIS_C: float = 1.0

    def __init__(
        self,
        index: int,
        tec,
        cfg: dict,
        on_alarm:   Optional[Callable] = None,
        on_warning: Optional[Callable] = None,
        on_clear:   Optional[Callable] = None,
    ):
        self._index   = index
        self._tec     = tec
        self._lock    = threading.Lock()

        # Limits from config — with sane defaults
        self._temp_min = float(cfg.get("temp_min", -20.0))
        self._temp_max = float(cfg.get("temp_max",  85.0))
        self._warning_margin = float(cfg.get("temp_warning_margin", 5.0))

        # Callbacks
        self._on_alarm   = on_alarm   or (lambda *a: None)
        self._on_warning = on_warning or (lambda *a: None)
        self._on_clear   = on_clear   or (lambda *a: None)

        # State
        self._state:        AlarmState = AlarmState.NORMAL
        self._acknowledged: bool       = True   # no alarm yet, so trivially ack'd
        self._disabled_by_guard: bool  = False  # did WE disable the TEC?

        log.info(
            f"ThermalGuard[{index}]: limits [{self._temp_min}°C, "
            f"{self._temp_max}°C], warning margin ±{self._warning_margin}°C")

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def state(self) -> AlarmState:
        return self._state

    @property
    def temp_min(self) -> float:
        return self._temp_min

    @property
    def temp_max(self) -> float:
        return self._temp_max

    @property
    def warning_margin(self) -> float:
        return self._warning_margin

    @property
    def is_alarmed(self) -> bool:
        return self._state == AlarmState.ALARM

    @property
    def acknowledged(self) -> bool:
        return self._acknowledged

    def acknowledge(self):
        """
        User has acknowledged the alarm.
        Clears the latch so the TEC can be re-enabled.
        Does NOT automatically re-enable the TEC.
        """
        fire_clear = False
        with self._lock:
            if self._state == AlarmState.ALARM:
                self._state        = AlarmState.NORMAL
                self._acknowledged = True
                self._disabled_by_guard = False
                log.info(f"ThermalGuard[{self._index}]: alarm acknowledged")
                fire_clear = True

        # Callback outside lock
        if fire_clear:
            self._on_clear(self._index)

    def update_limits(self, temp_min: float, temp_max: float,
                      warning_margin: float = None):
        """Update limits at runtime (e.g. from the UI)."""
        with self._lock:
            self._temp_min = temp_min
            self._temp_max = temp_max
            if warning_margin is not None:
                self._warning_margin = warning_margin
            log.info(
                f"ThermalGuard[{self._index}]: limits updated "
                f"[{temp_min}°C, {temp_max}°C]")

    def check(self, status: TecStatus) -> AlarmState:
        """
        Evaluate the latest TecStatus against the limits.

        Called from the hardware poll loop on every sample.
        Handles state transitions, fires callbacks, and disables
        the TEC driver directly on ALARM transition.

        Returns the current AlarmState after evaluation.
        """
        if status.error:
            # Don't evaluate limits if we can't trust the reading
            return self._state

        actual = status.actual_temp

        # Guard against None / NaN / non-finite readings — treat as
        # untrustworthy, just like an explicit error flag.
        if actual is None or not isinstance(actual, (int, float)):
            log.warning("ThermalGuard[%d]: actual_temp is %r — skipping check",
                        self._index, actual)
            return self._state
        if not math.isfinite(actual):
            log.warning("ThermalGuard[%d]: actual_temp is %s — skipping check",
                        self._index, actual)
            return self._state

        # Phase 1: decide state transition under lock (no external calls)
        action, action_args = self._evaluate(actual)

        # Phase 2: execute side-effects outside lock
        if action == _ACTION_ALARM:
            self._do_alarm(actual, *action_args)
        elif action == _ACTION_WARNING:
            self._on_warning(*action_args)
        elif action == _ACTION_CLEAR:
            self._on_clear(self._index)

        return self._state

    # ── Private: lock-protected state decision ─────────────────────────

    def _evaluate(self, actual: float):
        """Decide the state transition under lock.

        Returns (action, action_args) describing what side-effects to fire.
        No external calls are made inside this method.
        """
        with self._lock:
            # ── Already in latched ALARM — don't re-evaluate ──────────
            if self._state == AlarmState.ALARM:
                return _ACTION_NONE, ()

            # ── Check hard limits ─────────────────────────────────────
            if actual < self._temp_min:
                self._state        = AlarmState.ALARM
                self._acknowledged = False
                return _ACTION_ALARM, (self._temp_min, "LOW")

            if actual > self._temp_max:
                self._state        = AlarmState.ALARM
                self._acknowledged = False
                return _ACTION_ALARM, (self._temp_max, "HIGH")

            # ── Check warning zone ────────────────────────────────────
            warn_lo = self._temp_min + self._warning_margin
            warn_hi = self._temp_max - self._warning_margin

            if actual < warn_lo or actual > warn_hi:
                if self._state != AlarmState.WARNING:
                    self._state = AlarmState.WARNING
                    if actual < warn_lo:
                        limit = self._temp_min
                        msg = (f"TEC {self._index+1} approaching low limit: "
                               f"{actual:.2f}°C  (min {limit:.1f}°C)")
                    else:
                        limit = self._temp_max
                        msg = (f"TEC {self._index+1} approaching high limit: "
                               f"{actual:.2f}°C  (max {limit:.1f}°C)")
                    log.warning(f"ThermalGuard[{self._index}]: WARNING — {msg}")
                    return _ACTION_WARNING, (
                        self._index, msg, actual,
                        self._temp_min if actual < warn_lo else self._temp_max)
                return _ACTION_NONE, ()

            # ── Temperature is comfortably within limits ──────────────
            # Apply hysteresis: only clear WARNING if we're a full margin inside
            if self._state == AlarmState.WARNING:
                inner_lo = self._temp_min + self._warning_margin + self._HYSTERESIS_C
                inner_hi = self._temp_max - self._warning_margin - self._HYSTERESIS_C
                if inner_lo <= actual <= inner_hi:
                    self._state = AlarmState.NORMAL
                    log.info(f"ThermalGuard[{self._index}]: WARNING cleared")
                    return _ACTION_CLEAR, ()

            return _ACTION_NONE, ()

    # ── Private: side-effects (outside lock) ───────────────────────────

    def _do_alarm(self, actual: float, limit: float, direction: str):
        """Execute alarm side-effects: disable TEC, fire callback.

        Called OUTSIDE the lock.
        """
        direction_word = "below minimum" if direction == "LOW" else "above maximum"
        msg = (f"TEC {self._index+1} TEMPERATURE {direction} LIMIT — "
               f"{actual:.2f}°C  ({direction_word} {limit:.1f}°C). "
               f"Output disabled.")

        log.error(f"ThermalGuard[{self._index}]: ALARM — {msg}")

        # Disable TEC output immediately on this thread (poll thread)
        try:
            self._tec.disable()
            self._disabled_by_guard = True
            log.info(f"ThermalGuard[{self._index}]: TEC output disabled by guard")
        except Exception as e:
            # CRITICAL: TEC disable failed — the device may still be heating.
            # Log at CRITICAL so operators and monitoring tools notice.
            log.critical(
                "ThermalGuard[%d]: FAILED to disable TEC — manual intervention "
                "required! (actual=%.2f°C, limit=%.1f°C): %s",
                self._index, actual, limit, e,
            )
            # Append failure note to alarm message so the UI shows it
            msg += (
                " \u26a0 CRITICAL: automatic TEC disable FAILED — "
                "disconnect power manually!"
            )

        # Fire callback (will emit Qt signal in HardwareService)
        self._on_alarm(self._index, msg, actual, limit)
