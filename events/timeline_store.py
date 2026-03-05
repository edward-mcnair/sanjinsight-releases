"""
events/timeline_store.py

Ring-buffer store of recent events, exportable as JSON for support
bundles and run manifests.

The store is permanently subscribed to the module-level event_bus in
events/__init__.py; callers should not need to manage subscriptions.
"""
from __future__ import annotations

import collections
import json
import threading
from typing import List

from .models import Event


class TimelineStore:
    """
    Fixed-capacity FIFO ring buffer of :class:`Event` objects.

    Thread-safe; all operations acquire the internal lock.

    Parameters
    ----------
    capacity : int
        Maximum number of events retained.  Oldest events are evicted
        when the buffer is full.  Default: 500.
    """

    def __init__(self, capacity: int = 500) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._buf:  collections.deque = collections.deque(maxlen=capacity)
        self._capacity = capacity

    # ── Write ─────────────────────────────────────────────────────────

    def add(self, event: Event) -> None:
        """Append *event* to the ring buffer."""
        with self._lock:
            self._buf.append(event)

    def clear(self) -> None:
        """Discard all stored events."""
        with self._lock:
            self._buf.clear()

    # ── Read ──────────────────────────────────────────────────────────

    def recent(self, n: int = 200) -> List[Event]:
        """
        Return the last *n* events in chronological order.

        Returns fewer than *n* if the buffer holds fewer events.
        """
        with self._lock:
            events = list(self._buf)
        return events[-n:] if n < len(events) else events

    def all(self) -> List[Event]:
        """Return all stored events in chronological order."""
        with self._lock:
            return list(self._buf)

    # ── Export ────────────────────────────────────────────────────────

    def export_json(self, n: int = 200, indent: int = 2) -> str:
        """
        Serialise the last *n* events to a JSON string.

        Each event is represented as the dict produced by
        :meth:`Event.to_dict`.  Unknown object types are coerced to
        ``str`` so the export never raises.
        """
        records = [e.to_dict() for e in self.recent(n)]
        return json.dumps(records, indent=indent, default=str)

    def export_for_run(self, start_ts: float, end_ts: float) -> List[dict]:
        """
        Return serialised events whose timestamp falls within
        [start_ts, end_ts], for embedding in a run manifest.
        """
        with self._lock:
            events = list(self._buf)
        return [e.to_dict() for e in events
                if start_ts <= e.timestamp <= end_ts]

    # ── Introspection ─────────────────────────────────────────────────

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    @property
    def capacity(self) -> int:
        return self._capacity
