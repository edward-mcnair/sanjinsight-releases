"""
events — lightweight in-process event bus + timeline ring buffer.

Module-level singletons
-----------------------
    event_bus  — :class:`EventBus`  (publish/subscribe)
    timeline   — :class:`TimelineStore` (ring buffer, capacity=500)

The timeline is permanently subscribed to *event_bus* so every
published event is automatically recorded.

Convenience helpers
-------------------
    emit_debug / emit_info / emit_warning / emit_error

Usage::

    from events import event_bus, timeline, emit_info, emit_warning

    # Subscribe (any callable; runs on the publishing thread)
    event_bus.subscribe(my_handler)

    # Publish
    emit_info("hardware.camera", "device_connect",
              "Basler acA1920 connected", address="COM3", firmware="1.4.0")

    # Export timeline for support bundle
    json_str = timeline.export_json(n=200)

    # Retrieve events for a single run
    run_events = timeline.export_for_run(start_ts, end_ts)
"""
from __future__ import annotations

from typing import Any

from .models import (
    Event,
    EVT_DEVICE_CONNECT, EVT_DEVICE_DISCONNECT, EVT_DEVICE_ERROR,
    EVT_SAFE_MODE_ACTIVE, EVT_SAFE_MODE_CLEARED,
    EVT_ACQ_START, EVT_ACQ_COMPLETE, EVT_ACQ_ABORT, EVT_ACQ_ERROR,
    EVT_SCAN_START, EVT_SCAN_COMPLETE, EVT_SCAN_ABORT,
    EVT_AUTOSAVE_SAVE, EVT_AUTOSAVE_LOAD, EVT_AUTOSAVE_CLEAR,
    EVT_PREFLIGHT_START, EVT_PREFLIGHT_COMPLETE,
    EVT_BUNDLE_START, EVT_BUNDLE_COMPLETE, EVT_BUNDLE_FAILED,
)
from .event_bus import EventBus
from .timeline_store import TimelineStore

# ── Module-level singletons ───────────────────────────────────────────────────
event_bus = EventBus()
timeline  = TimelineStore(capacity=500)

# Wire timeline as a permanent, first subscriber.
event_bus.subscribe(timeline.add)


# ── Emit helpers ──────────────────────────────────────────────────────────────

def _emit(level: str, source: str, event_type: str,
          message: str, **ctx: Any) -> None:
    event_bus.publish(Event(
        source=source, event_type=event_type,
        message=message, level=level, context=ctx,
    ))


def emit_debug(source: str, event_type: str, message: str, **ctx: Any) -> None:
    """Publish a *debug*-level event."""
    _emit("debug", source, event_type, message, **ctx)


def emit_info(source: str, event_type: str, message: str, **ctx: Any) -> None:
    """Publish an *info*-level event."""
    _emit("info", source, event_type, message, **ctx)


def emit_warning(source: str, event_type: str, message: str, **ctx: Any) -> None:
    """Publish a *warning*-level event."""
    _emit("warning", source, event_type, message, **ctx)


def emit_error(source: str, event_type: str, message: str, **ctx: Any) -> None:
    """Publish an *error*-level event."""
    _emit("error", source, event_type, message, **ctx)


__all__ = [
    "Event", "EventBus", "TimelineStore",
    "event_bus", "timeline",
    "emit_debug", "emit_info", "emit_warning", "emit_error",
    # event_type constants
    "EVT_DEVICE_CONNECT", "EVT_DEVICE_DISCONNECT", "EVT_DEVICE_ERROR",
    "EVT_SAFE_MODE_ACTIVE", "EVT_SAFE_MODE_CLEARED",
    "EVT_ACQ_START", "EVT_ACQ_COMPLETE", "EVT_ACQ_ABORT", "EVT_ACQ_ERROR",
    "EVT_SCAN_START", "EVT_SCAN_COMPLETE", "EVT_SCAN_ABORT",
    "EVT_AUTOSAVE_SAVE", "EVT_AUTOSAVE_LOAD", "EVT_AUTOSAVE_CLEAR",
    "EVT_PREFLIGHT_START", "EVT_PREFLIGHT_COMPLETE",
    "EVT_BUNDLE_START", "EVT_BUNDLE_COMPLETE", "EVT_BUNDLE_FAILED",
]
