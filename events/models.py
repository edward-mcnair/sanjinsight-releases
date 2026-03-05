"""
events/models.py

Structured event schema for the SanjINSIGHT event bus.

Every event carries:
  timestamp   — float (time.time()) — seconds since epoch
  level       — "debug" | "info" | "warning" | "error"
  source      — dotted string identifying the emitting subsystem
                e.g. "hardware.camera", "acquisition.pipeline"
  event_type  — snake_case identifier for the event kind
                e.g. "device_connect", "acq_start", "autosave_save"
  message     — human-readable one-line summary
  context     — optional arbitrary key-value pairs for structured data

All fields are JSON-serialisable so the timeline can be exported as
a flat list of dicts for support bundles and run manifests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Event:
    """Immutable structured event."""

    source:     str                    # emitting subsystem
    event_type: str                    # event kind identifier
    message:    str                    # human-readable summary
    level:      str = "info"           # debug | info | warning | error
    context:    Dict[str, Any] = field(default_factory=dict)
    timestamp:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "timestamp":  self.timestamp,
            "level":      self.level,
            "source":     self.source,
            "type":       self.event_type,
            "message":    self.message,
            "context":    self.context,
        }


# ── Canonical event_type constants ───────────────────────────────────────────
# Use these instead of bare strings to avoid typos.

# Hardware lifecycle
EVT_DEVICE_CONNECT    = "device_connect"
EVT_DEVICE_DISCONNECT = "device_disconnect"
EVT_DEVICE_ERROR      = "device_error"
EVT_SAFE_MODE_ACTIVE  = "safe_mode_active"
EVT_SAFE_MODE_CLEARED = "safe_mode_cleared"

# Acquisition lifecycle
EVT_ACQ_START    = "acq_start"
EVT_ACQ_COMPLETE = "acq_complete"
EVT_ACQ_ABORT    = "acq_abort"
EVT_ACQ_ERROR    = "acq_error"

# Scan lifecycle
EVT_SCAN_START    = "scan_start"
EVT_SCAN_COMPLETE = "scan_complete"
EVT_SCAN_ABORT    = "scan_abort"

# Autosave lifecycle
EVT_AUTOSAVE_SAVE  = "autosave_save"
EVT_AUTOSAVE_LOAD  = "autosave_load"
EVT_AUTOSAVE_CLEAR = "autosave_clear"

# Preflight / health
EVT_PREFLIGHT_START    = "preflight_start"
EVT_PREFLIGHT_COMPLETE = "preflight_complete"

# Support bundle
EVT_BUNDLE_START    = "bundle_start"
EVT_BUNDLE_COMPLETE = "bundle_complete"
EVT_BUNDLE_FAILED   = "bundle_failed"
