"""
ai/ai_metrics.py

Lightweight instrumentation counters for the SanjINSIGHT AI subsystem.

Tracks observable events that inform model selection, prompt tuning,
and UX decisions:
  - Request lifecycle (completions, cancellations, stale suppressions)
  - Output parsing (success, repaired, failed)
  - Token budget trimming events
  - RAG retrieval usage
  - Response timing

Design
------
  * Thread-safe counters via threading.Lock.
  * ``snapshot()`` returns a frozen dict of all counters — safe to read
    from any thread or serialize to JSON.
  * ``AIMetricsCollector`` is a singleton-style object owned by AIService.
  * No Qt dependency — pure Python so it's testable without a QApplication.
  * Counters are monotonic (only increment); ``reset()`` zeros everything.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class _Counters:
    """Raw counter storage.  Access only via AIMetricsCollector."""
    # Request lifecycle
    requests_started:       int = 0
    requests_completed:     int = 0
    requests_cancelled:     int = 0
    stale_tokens_dropped:   int = 0
    stale_completions_dropped: int = 0

    # Output parsing
    parse_success:          int = 0
    parse_repaired:         int = 0
    parse_failed:           int = 0

    # Token budget
    history_trim_events:    int = 0
    history_messages_dropped: int = 0
    context_truncations:    int = 0

    # RAG retrieval
    rag_queries:            int = 0
    rag_hits:               int = 0   # query returned ≥1 section
    rag_misses:             int = 0   # query returned empty

    # Response timing (running averages)
    total_response_time_s:  float = 0.0
    total_tokens_generated: int = 0


class AIMetricsCollector:
    """Thread-safe AI subsystem metrics collector.

    Usage::

        metrics = AIMetricsCollector()
        metrics.on_request_started()
        metrics.on_stale_token()
        snap = metrics.snapshot()
        print(snap["stale_tokens_dropped"])
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._c = _Counters()
        self._started_at = time.monotonic()

    # ── Request lifecycle ────────────────────────────────────────────────

    def on_request_started(self) -> None:
        with self._lock:
            self._c.requests_started += 1

    def on_request_completed(self, elapsed_s: float = 0.0,
                              tokens: int = 0) -> None:
        with self._lock:
            self._c.requests_completed += 1
            self._c.total_response_time_s += elapsed_s
            self._c.total_tokens_generated += tokens

    def on_request_cancelled(self) -> None:
        with self._lock:
            self._c.requests_cancelled += 1

    def on_stale_token(self) -> None:
        with self._lock:
            self._c.stale_tokens_dropped += 1

    def on_stale_completion(self) -> None:
        with self._lock:
            self._c.stale_completions_dropped += 1

    # ── Output parsing ───────────────────────────────────────────────────

    def on_parse_success(self, repaired: bool = False) -> None:
        with self._lock:
            if repaired:
                self._c.parse_repaired += 1
            else:
                self._c.parse_success += 1

    def on_parse_failed(self) -> None:
        with self._lock:
            self._c.parse_failed += 1

    # ── Token budget ─────────────────────────────────────────────────────

    def on_history_trimmed(self, messages_dropped: int = 0) -> None:
        with self._lock:
            self._c.history_trim_events += 1
            self._c.history_messages_dropped += messages_dropped

    def on_context_truncated(self) -> None:
        with self._lock:
            self._c.context_truncations += 1

    # ── RAG retrieval ────────────────────────────────────────────────────

    def on_rag_query(self, hit: bool) -> None:
        with self._lock:
            self._c.rag_queries += 1
            if hit:
                self._c.rag_hits += 1
            else:
                self._c.rag_misses += 1

    # ── Snapshot ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a frozen dict of all counters.

        Safe to call from any thread.  Includes derived metrics:
          - ``avg_response_s``: mean response time (0 if no completions)
          - ``parse_repair_rate``: fraction of successful parses that needed repair
          - ``rag_hit_rate``: fraction of RAG queries that returned results
          - ``stale_rate``: fraction of started requests that were stale-dropped
          - ``uptime_s``: seconds since collector was created
        """
        with self._lock:
            c = self._c
            completed = c.requests_completed or 1  # avoid div/0
            parse_total = c.parse_success + c.parse_repaired + c.parse_failed
            rag_total = c.rag_queries or 1

            return {
                # Raw counters
                "requests_started":       c.requests_started,
                "requests_completed":     c.requests_completed,
                "requests_cancelled":     c.requests_cancelled,
                "stale_tokens_dropped":   c.stale_tokens_dropped,
                "stale_completions_dropped": c.stale_completions_dropped,
                "parse_success":          c.parse_success,
                "parse_repaired":         c.parse_repaired,
                "parse_failed":           c.parse_failed,
                "history_trim_events":    c.history_trim_events,
                "history_messages_dropped": c.history_messages_dropped,
                "context_truncations":    c.context_truncations,
                "rag_queries":            c.rag_queries,
                "rag_hits":               c.rag_hits,
                "rag_misses":             c.rag_misses,
                "total_tokens_generated": c.total_tokens_generated,
                # Derived
                "avg_response_s":  round(c.total_response_time_s / completed, 2),
                "parse_repair_rate": (
                    round(c.parse_repaired / parse_total, 3) if parse_total else 0.0),
                "rag_hit_rate": round(c.rag_hits / rag_total, 3),
                "stale_rate": (
                    round((c.stale_completions_dropped + c.requests_cancelled)
                          / max(c.requests_started, 1), 3)),
                "uptime_s": round(time.monotonic() - self._started_at, 1),
            }

    def reset(self) -> None:
        """Zero all counters.  Called when AI is disabled."""
        with self._lock:
            self._c = _Counters()
            self._started_at = time.monotonic()
        log.debug("AIMetricsCollector: counters reset")

    def log_summary(self) -> None:
        """Log a one-line summary of key metrics at INFO level."""
        s = self.snapshot()
        log.info(
            "AI metrics: %d requests (%d completed, %d cancelled, %d stale), "
            "parse %d/%d/%d (ok/repaired/fail), RAG %d/%d hits, "
            "avg %.1fs/response",
            s["requests_started"], s["requests_completed"],
            s["requests_cancelled"], s["stale_completions_dropped"],
            s["parse_success"], s["parse_repaired"], s["parse_failed"],
            s["rag_hits"], s["rag_queries"],
            s["avg_response_s"],
        )
