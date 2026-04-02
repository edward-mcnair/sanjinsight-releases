"""
hardware/device_state.py

Formal device state machine for tracking hardware connection lifecycle.

Provides a small enum of states and a state-machine class that enforces
valid transitions. Each device in BaseDeviceService gets its own instance.

Pure Python — no Qt dependency.

Usage
-----
    from hardware.device_state import DeviceState, DeviceStateMachine

    sm = DeviceStateMachine()
    sm.transition(DeviceState.CONNECTING)
    sm.transition(DeviceState.CONNECTED)
    print(sm.state)  # DeviceState.CONNECTED
"""

from __future__ import annotations

import enum
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class DeviceState(enum.Enum):
    """Lifecycle states for a hardware device."""

    UNKNOWN       = "unknown"
    DISCONNECTED  = "disconnected"
    DISCOVERING   = "discovering"
    CONNECTING    = "connecting"
    CONNECTED     = "connected"
    DEGRADED      = "degraded"       # connected but experiencing poll errors
    ERROR         = "error"          # connection lost / repeated failures
    SAFE_MODE     = "safe_mode"      # manual intervention required


# Valid state transitions.  Each key lists the states reachable from it.
_TRANSITIONS: dict[DeviceState, set[DeviceState]] = {
    DeviceState.UNKNOWN:      {DeviceState.DISCONNECTED, DeviceState.DISCOVERING,
                               DeviceState.CONNECTING, DeviceState.CONNECTED},
    DeviceState.DISCONNECTED: {DeviceState.DISCOVERING, DeviceState.CONNECTING,
                               DeviceState.CONNECTED},
    DeviceState.DISCOVERING:  {DeviceState.CONNECTING, DeviceState.CONNECTED,
                               DeviceState.DISCONNECTED, DeviceState.ERROR},
    DeviceState.CONNECTING:   {DeviceState.CONNECTED, DeviceState.ERROR,
                               DeviceState.DISCONNECTED},
    DeviceState.CONNECTED:    {DeviceState.DEGRADED, DeviceState.ERROR,
                               DeviceState.DISCONNECTED},
    DeviceState.DEGRADED:     {DeviceState.CONNECTED, DeviceState.ERROR,
                               DeviceState.DISCONNECTED},
    DeviceState.ERROR:        {DeviceState.CONNECTING, DeviceState.DISCOVERING,
                               DeviceState.DISCONNECTED, DeviceState.SAFE_MODE},
    DeviceState.SAFE_MODE:    {DeviceState.CONNECTING, DeviceState.DISCOVERING,
                               DeviceState.DISCONNECTED},
}


class DeviceStateMachine:
    """Tracks and enforces device state transitions.

    Parameters
    ----------
    device_uid : str
        Identifier for logging.
    initial : DeviceState
        Starting state (default ``UNKNOWN``).
    """

    def __init__(self, device_uid: str = "", initial: DeviceState = DeviceState.UNKNOWN):
        self._uid = device_uid
        self._state = initial
        self._last_transition: float = time.monotonic()
        self._history: list[tuple[float, DeviceState]] = [(time.monotonic(), initial)]

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def seconds_in_state(self) -> float:
        return time.monotonic() - self._last_transition

    def transition(self, new_state: DeviceState) -> bool:
        """Attempt a state transition.

        Returns True if the transition was valid and applied.
        Returns False (and logs a warning) if the transition is invalid.
        """
        if new_state == self._state:
            return True  # no-op, not an error

        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            log.warning(
                "[%s] Invalid state transition: %s → %s (allowed: %s)",
                self._uid, self._state.value, new_state.value,
                ", ".join(s.value for s in sorted(allowed, key=lambda s: s.value)),
            )
            return False

        old = self._state
        self._state = new_state
        self._last_transition = time.monotonic()
        self._history.append((time.monotonic(), new_state))
        # Cap history at 50 entries
        if len(self._history) > 50:
            self._history = self._history[-30:]

        log.debug("[%s] State: %s → %s", self._uid, old.value, new_state.value)
        return True

    def to_health_panel_state(self) -> str:
        """Map to ConnectionHealthPanel state constants."""
        _MAP = {
            DeviceState.CONNECTED:    "connected",
            DeviceState.CONNECTING:   "connecting",
            DeviceState.DISCOVERING:  "connecting",
            DeviceState.ERROR:        "error",
            DeviceState.SAFE_MODE:    "error",
            DeviceState.DEGRADED:     "error",
            DeviceState.DISCONNECTED: "absent",
            DeviceState.UNKNOWN:      "absent",
        }
        return _MAP.get(self._state, "absent")

    @property
    def history(self) -> list[tuple[float, DeviceState]]:
        """Recent state transition history (timestamp, state) pairs."""
        return list(self._history)
