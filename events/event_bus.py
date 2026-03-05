"""
events/event_bus.py

Thread-safe publish/subscribe event bus.

Design constraints:
  • Pure Python — zero Qt dependency so it can be used from any thread.
  • Subscriber exceptions are caught and logged; they never propagate to
    the publisher or affect other subscribers.
  • Subscriptions are weakly scoped (caller must keep a reference to
    handler; otherwise unsubscribe explicitly).
  • Filtering is optional — pass a predicate to subscribe() to receive
    only matching events.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

from .models import Event

log = logging.getLogger(__name__)

# Type aliases
_Handler   = Callable[[Event], None]
_FilterFn  = Callable[[Event], bool]
_SubEntry  = Tuple[_Handler, Optional[_FilterFn]]


class EventBus:
    """
    Minimal publish/subscribe bus.

    Usage::

        from events import event_bus
        event_bus.subscribe(my_handler)
        event_bus.subscribe(my_handler, lambda e: e.level == "error")
        event_bus.publish(Event("src", "type", "msg"))
        event_bus.unsubscribe(my_handler)
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._subs: List[_SubEntry] = []

    # ── Core API ──────────────────────────────────────────────────────

    def publish(self, event: Event) -> None:
        """
        Publish *event* to all matching subscribers.

        Runs synchronously on the calling thread.  Subscriber exceptions
        are suppressed so a broken subscriber never breaks the publisher.
        """
        with self._lock:
            subs = list(self._subs)          # snapshot under lock

        for handler, filter_fn in subs:
            if filter_fn is not None and not filter_fn(event):
                continue
            try:
                handler(event)
            except Exception:
                log.debug("EventBus: subscriber %r raised", handler, exc_info=True)

    def subscribe(self,
                  handler:   _Handler,
                  filter_fn: Optional[_FilterFn] = None) -> None:
        """
        Register *handler* to receive events.

        Parameters
        ----------
        handler   : Callable[[Event], None]
        filter_fn : optional predicate; handler is called only when
                    filter_fn(event) returns True.
        """
        with self._lock:
            # Avoid duplicate registration of the same handler.
            if not any(h is handler for h, _ in self._subs):
                self._subs.append((handler, filter_fn))

    def unsubscribe(self, handler: _Handler) -> None:
        """Remove *handler* from the subscriber list."""
        with self._lock:
            self._subs = [(h, f) for h, f in self._subs if h is not handler]

    def subscriber_count(self) -> int:
        """Return the current number of registered subscribers."""
        with self._lock:
            return len(self._subs)
