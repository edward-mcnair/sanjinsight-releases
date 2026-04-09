"""
ai/request_lifecycle.py

Request lifecycle manager for the SanjINSIGHT AI assistant.

Solves three problems:
  1. Stale responses — tokens from a cancelled/superseded request must not
     update the UI.
  2. Cancellation races — cancel() must immediately invalidate the active
     request so that worker-thread completions are silently dropped.
  3. Single-flight semantics — a new request of the same type auto-cancels
     the previous one.

Design
------
  • Every AI request gets a monotonically increasing integer ``request_id``.
  • The ``RequestManager`` tracks the *current* request ID per flow type.
  • Signal handlers call ``is_current(rid)`` before acting on tokens or
    completions.  If the request has been superseded, the event is dropped.
  • ``cancel()`` bumps the generation counter so all in-flight events for
    the old request become stale.
  • Thread-safe: all state is guarded by a threading.Lock.

Flow types
----------
  CHAT       — conversational Q&A, explain_tab, diagnose (mutually exclusive)
  REPORT     — session quality report (can run alongside CHAT)
  ADVISOR    — proactive profile advisor (exclusive with REPORT)

Mutual exclusivity means a new CHAT request auto-cancels a previous CHAT
request, but does NOT cancel an in-flight REPORT.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


class FlowType(str, enum.Enum):
    """Mutually exclusive request flow types."""
    CHAT    = "chat"       # ask, explain_tab, diagnose
    REPORT  = "report"     # session_report
    ADVISOR = "advisor"    # proactive advisor


@dataclass
class RequestInfo:
    """Metadata for one AI request."""
    request_id:   int
    flow_type:    FlowType
    task_label:   str       # human-readable label for logging
    start_time:   float     # time.monotonic()
    cancelled:    bool = False
    completed:    bool = False


class RequestManager:
    """Tracks the lifecycle of AI requests.

    Thread-safe.  Designed to be owned by AIService on the main thread
    and queried from runner worker threads via is_current().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter: int = 0
        # One active request per flow type
        self._active: dict[FlowType, RequestInfo] = {}

    # ── Public API ───────────────────────────────────────────────────────

    def new_request(self, flow_type: FlowType, task_label: str = "") -> int:
        """Register a new request, auto-cancelling any previous request of
        the same flow type.

        Returns the new request_id.
        """
        with self._lock:
            self._counter += 1
            rid = self._counter

            # Auto-cancel previous request of the same flow type
            prev = self._active.get(flow_type)
            if prev and not prev.completed:
                prev.cancelled = True
                log.debug(
                    "Request #%d (%s/%s) auto-cancelled by new request #%d",
                    prev.request_id, prev.flow_type.value, prev.task_label,
                    rid,
                )

            info = RequestInfo(
                request_id=rid,
                flow_type=flow_type,
                task_label=task_label or flow_type.value,
                start_time=time.monotonic(),
            )
            self._active[flow_type] = info

        log.debug(
            "Request #%d started: flow=%s task=%s",
            rid, flow_type.value, task_label,
        )
        return rid

    def is_current(self, request_id: int) -> bool:
        """Return True if *request_id* is still the active, non-cancelled
        request for its flow type.

        Safe to call from any thread.
        """
        with self._lock:
            for info in self._active.values():
                if info.request_id == request_id:
                    return not info.cancelled and not info.completed
        return False

    def cancel(self, flow_type: FlowType) -> int | None:
        """Cancel the active request for *flow_type*.

        Returns the cancelled request_id, or None if nothing was active.
        """
        with self._lock:
            info = self._active.get(flow_type)
            if info and not info.completed:
                info.cancelled = True
                log.debug(
                    "Request #%d cancelled: flow=%s task=%s (elapsed=%.1fs)",
                    info.request_id, info.flow_type.value, info.task_label,
                    time.monotonic() - info.start_time,
                )
                return info.request_id
        return None

    def cancel_all(self) -> list[int]:
        """Cancel all active requests.  Returns list of cancelled IDs."""
        cancelled = []
        with self._lock:
            for info in self._active.values():
                if not info.completed and not info.cancelled:
                    info.cancelled = True
                    cancelled.append(info.request_id)
        if cancelled:
            log.debug("Cancelled all active requests: %s", cancelled)
        return cancelled

    def complete(self, request_id: int) -> bool:
        """Mark a request as completed.

        Returns True if the request was current (not stale/cancelled),
        False if it was already cancelled or superseded.

        The caller should only act on the completion if this returns True.
        """
        with self._lock:
            for info in self._active.values():
                if info.request_id == request_id:
                    if info.cancelled:
                        log.debug(
                            "Request #%d completion ignored (cancelled): %s",
                            request_id, info.task_label,
                        )
                        return False
                    info.completed = True
                    elapsed = time.monotonic() - info.start_time
                    log.debug(
                        "Request #%d completed: %s (%.1fs)",
                        request_id, info.task_label, elapsed,
                    )
                    return True
        # Request ID not found — likely already replaced
        log.debug("Request #%d completion ignored (not found)", request_id)
        return False

    def active_request(self, flow_type: FlowType) -> RequestInfo | None:
        """Return the active request for *flow_type*, or None."""
        with self._lock:
            info = self._active.get(flow_type)
            if info and not info.completed and not info.cancelled:
                return info
        return None

    def elapsed(self, request_id: int) -> float:
        """Return elapsed seconds since the request started, or 0.0."""
        with self._lock:
            for info in self._active.values():
                if info.request_id == request_id:
                    return time.monotonic() - info.start_time
        return 0.0

    def reset(self) -> None:
        """Clear all tracking state.  Called when AI is disabled."""
        with self._lock:
            self._active.clear()
            # Don't reset _counter — IDs should stay monotonic
