"""USB hot-plug detection for SanjINSIGHT.

Monitors USB serial device connect/disconnect events and emits PyQt5 signals
so that the rest of the application can react to hardware changes without
polling device handles directly.

Usage::

    monitor = create_hotplug_monitor()
    monitor.device_arrived.connect(on_device_arrived)
    monitor.device_removed.connect(on_device_removed)
    monitor.start()

    # Later, during teardown:
    monitor.stop()

Signals carry ``(port, vid, pid)`` where *port* is the OS device path
(e.g. ``COM3`` or ``/dev/ttyUSB0``), and *vid*/*pid* are the USB vendor /
product IDs as integers (0 when unknown).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

import serial.tools.list_ports

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VID:PID parsing
# ---------------------------------------------------------------------------

_VID_PID_RE = re.compile(r"VID[_:]PID[=:]([0-9A-Fa-f]{4})[:]([0-9A-Fa-f]{4})")


def parse_vid_pid(hwid: str) -> Tuple[int, int]:
    """Extract (vid, pid) from a pyserial *hwid* string.

    Returns ``(0, 0)`` when the string does not contain identifiable USB IDs.
    """
    m = _VID_PID_RE.search(hwid)
    if m:
        return int(m.group(1), 16), int(m.group(2), 16)
    return 0, 0


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

class _PortInfo:
    """Lightweight snapshot of a single serial port."""

    __slots__ = ("device", "vid", "pid")

    def __init__(self, device: str, vid: int, pid: int) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid

    def __repr__(self) -> str:  # pragma: no cover
        return f"_PortInfo({self.device!r}, vid=0x{self.vid:04X}, pid=0x{self.pid:04X})"


def _take_snapshot() -> Dict[str, _PortInfo]:
    """Return a dict mapping device path to :class:`_PortInfo`."""
    snapshot: Dict[str, _PortInfo] = {}
    for port in serial.tools.list_ports.comports():
        vid, pid = parse_vid_pid(port.hwid or "")
        snapshot[port.device] = _PortInfo(port.device, vid, pid)
    return snapshot


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class HotPlugMonitor(QObject):
    """Abstract base for USB hot-plug monitors.

    Subclasses must implement :meth:`start` and :meth:`stop`.

    Signals
    -------
    device_arrived(str, int, int)
        Emitted when a new USB serial device appears.  Arguments are
        *(port, vid, pid)*.
    device_removed(str, int, int)
        Emitted when a previously-visible USB serial device disappears.
        Arguments are *(port, vid, pid)*.
    """

    device_arrived = pyqtSignal(str, int, int)
    device_removed = pyqtSignal(str, int, int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    # -- public interface (abstract) ----------------------------------------

    def start(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Polling implementation
# ---------------------------------------------------------------------------

_POLL_INTERVAL_MS = 2000
_DEBOUNCE_ARRIVAL_MS = 500


class PollingHotPlugMonitor(HotPlugMonitor):
    """Universal fallback monitor that polls ``serial.tools.list_ports``.

    Uses a :class:`QTimer` (daemon-style — does not prevent app exit) to
    periodically compare port snapshots.  Arrival events are debounced by
    500 ms to accommodate USB enumeration jitter; removal events are emitted
    immediately.
    """

    def __init__(
        self,
        interval_ms: int = _POLL_INTERVAL_MS,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self._interval_ms = interval_ms
        self._previous: Dict[str, _PortInfo] = {}

        # Pending arrivals: device -> (PortInfo, monotonic timestamp when first seen)
        self._pending_arrivals: Dict[str, Tuple[_PortInfo, float]] = {}

        # -- poll timer -----------------------------------------------------
        self._timer = QTimer(self)
        self._timer.setTimerType(2)  # Qt.CoarseTimer
        self._timer.timeout.connect(self._poll)

    # -- public interface ---------------------------------------------------

    def start(self) -> None:
        """Begin monitoring.  Takes an initial snapshot without emitting."""
        log.info("PollingHotPlugMonitor: starting (interval=%d ms)", self._interval_ms)
        self._previous = _take_snapshot()
        self._pending_arrivals.clear()
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        """Stop monitoring."""
        self._timer.stop()
        self._pending_arrivals.clear()
        log.info("PollingHotPlugMonitor: stopped")

    # -- internals ----------------------------------------------------------

    def _poll(self) -> None:
        """Compare current ports against the previous snapshot."""
        try:
            current = _take_snapshot()
        except Exception:
            log.exception("PollingHotPlugMonitor: failed to enumerate ports")
            return

        now = time.monotonic()

        # --- removals (immediate) ------------------------------------------
        removed = self._previous.keys() - current.keys()
        for dev in removed:
            info = self._previous[dev]
            # Also discard any pending arrival for this device.
            self._pending_arrivals.pop(dev, None)
            log.info(
                "USB device removed: %s (VID=0x%04X PID=0x%04X)",
                info.device, info.vid, info.pid,
            )
            self.device_removed.emit(info.device, info.vid, info.pid)

        # --- arrivals (debounced) ------------------------------------------
        added = current.keys() - self._previous.keys()
        for dev in added:
            if dev not in self._pending_arrivals:
                self._pending_arrivals[dev] = (current[dev], now)

        # Flush arrivals that have survived the debounce window.
        flushed: list[str] = []
        for dev, (info, first_seen) in self._pending_arrivals.items():
            elapsed_ms = (now - first_seen) * 1000.0
            if elapsed_ms >= _DEBOUNCE_ARRIVAL_MS:
                # Only emit if the device is still present.
                if dev in current:
                    log.info(
                        "USB device arrived: %s (VID=0x%04X PID=0x%04X)",
                        info.device, info.vid, info.pid,
                    )
                    self.device_arrived.emit(info.device, info.vid, info.pid)
                flushed.append(dev)

        for dev in flushed:
            self._pending_arrivals.pop(dev, None)

        self._previous = current


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_hotplug_monitor(
    parent: Optional[QObject] = None,
) -> HotPlugMonitor:
    """Create and return the best available :class:`HotPlugMonitor`.

    Currently returns a :class:`PollingHotPlugMonitor` on all platforms.
    Future versions may return platform-specific implementations (e.g.
    ``libudev`` on Linux or ``IOKit`` on macOS) when available.
    """
    return PollingHotPlugMonitor(parent=parent)
