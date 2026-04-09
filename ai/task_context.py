"""
ai/task_context.py

Task-specific context builders and cached state digest for the SanjINSIGHT
AI assistant.

Problems solved
---------------
  1. One-size-fits-all context — different tasks need different payloads.
     A diagnosis needs full device + issue data; a chat just needs a compact
     summary; a session report needs acquisition metrics not device details.
  2. Redundant rebuilding — rebuilding the full instrument state JSON on
     every keystroke is wasteful when state hasn't changed.

Design
------
  • ``StateDigest`` — a compact, cached snapshot of instrument state that
    is recomputed only when meaningful state changes (device connect/
    disconnect, TEC alarm, acquisition start/stop, etc.).
  • ``build_task_context()`` — assembles the context payload for a specific
    task type, using only the sections relevant to that task.
  • Disconnected devices are represented as a single line instead of a
    full JSON object, saving ~20 tokens per absent device.

The digest is designed to be cheap to hash-compare so callers can skip
context rebuilding when nothing has changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from ai.token_budget import TaskType, estimate_tokens, truncate_text

if TYPE_CHECKING:
    from ai.context_builder import ContextBuilder

log = logging.getLogger(__name__)


# ── State digest ─────────────────────────────────────────────────────────────

@dataclass
class StateDigest:
    """Compact, cached instrument state snapshot.

    The ``json_str`` is the canonical representation; ``fingerprint`` is
    a short hash for cheap equality checking.
    """
    json_str:     str   = ""
    fingerprint:  str   = ""
    token_count:  int   = 0
    built_at:     float = 0.0    # time.monotonic()
    stale:        bool  = True   # True until first build


class DigestCache:
    """Caches the instrument state digest, recomputing only when stale.

    Staleness is signalled externally (e.g. by device connect/disconnect
    events) or by a time-based TTL.
    """

    # Maximum age before forced refresh (seconds).
    # Even without explicit invalidation, state is refreshed periodically
    # so the AI always sees reasonably current data.
    _TTL_S: float = 5.0

    def __init__(self) -> None:
        self._digest = StateDigest()

    def invalidate(self) -> None:
        """Mark the cached digest as stale.  Next get() will rebuild."""
        self._digest.stale = True

    def get(self, context_builder: "ContextBuilder") -> StateDigest:
        """Return the current state digest, rebuilding if stale or expired."""
        now = time.monotonic()
        if (not self._digest.stale and
                (now - self._digest.built_at) < self._TTL_S):
            return self._digest

        # Rebuild
        try:
            raw_json = context_builder.build()
        except Exception:
            log.debug("DigestCache: build failed, keeping stale digest",
                      exc_info=True)
            return self._digest

        fp = hashlib.md5(raw_json.encode(), usedforsecurity=False).hexdigest()[:8]

        if fp != self._digest.fingerprint:
            log.debug("DigestCache: state changed (fp=%s→%s, %d tokens)",
                      self._digest.fingerprint, fp, estimate_tokens(raw_json))

        self._digest = StateDigest(
            json_str=raw_json,
            fingerprint=fp,
            token_count=estimate_tokens(raw_json),
            built_at=now,
            stale=False,
        )
        return self._digest


# ── Task-specific context sections ───────────────────────────────────────────
#
# Each task type declares which context sections it needs.  Sections not
# listed are omitted entirely, saving tokens for history and response.

_SECTION_KEYS_BY_TASK: dict[TaskType, set[str]] = {
    TaskType.CHAT: {
        "tab", "workspace_mode", "cam", "fpga", "tecs", "stage",
        "bias", "ldd", "modality", "profile", "metrics", "rules",
    },
    TaskType.EXPLAIN_TAB: {
        "tab", "workspace_mode", "cam", "fpga", "tecs", "stage",
        "bias", "ldd", "modality", "objective", "profile",
    },
    TaskType.DIAGNOSE: {
        "tab", "workspace_mode", "cam", "fpga", "tecs", "stage",
        "bias", "ldd", "gpio", "prober", "modality", "profile",
        "metrics", "rules", "system_model", "objective",
    },
    TaskType.SESSION_REPORT: {
        "tab", "cam", "fpga", "tecs", "modality", "profile",
        "metrics",
    },
    TaskType.ADVISOR: {
        "cam", "fpga", "tecs", "bias", "modality", "profile",
        "system_model", "objective", "rules",
    },
}


def _compact_device_line(key: str, data: dict) -> str:
    """Produce a compact one-line representation of a device section.

    Connected devices get their key values; disconnected devices get
    a single 'off' token.
    """
    if not data.get("connected", False) and key not in ("metrics", "rules",
                                                         "profile", "tab",
                                                         "workspace_mode",
                                                         "modality"):
        return f'"{key}":"off"'
    # Let json.dumps handle it compactly
    return f'"{key}":{json.dumps(data, separators=(",", ":"))}'


def build_task_context(
    task_type: TaskType,
    full_state_json: str,
    max_tokens: int = 0,
) -> str:
    """Build a task-specific context string from the full instrument state.

    Parameters
    ----------
    task_type : TaskType
        Determines which sections to include.
    full_state_json : str
        The full context JSON from ContextBuilder.build().
    max_tokens : int
        If > 0, truncate the result to fit this budget.

    Returns
    -------
    str
        Compact JSON string with only the relevant sections.
    """
    try:
        full_data = json.loads(full_state_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("build_task_context: invalid JSON input")
        return full_state_json  # fallback: pass through unchanged

    wanted_keys = _SECTION_KEYS_BY_TASK.get(task_type, set())
    if not wanted_keys:
        return full_state_json

    # Build filtered output — compact representation
    parts: list[str] = []
    for key in wanted_keys:
        if key not in full_data:
            continue
        val = full_data[key]
        if isinstance(val, dict):
            parts.append(_compact_device_line(key, val))
        elif isinstance(val, list):
            # Compact list (rules, tecs)
            parts.append(f'"{key}":{json.dumps(val, separators=(",", ":"))}')
        else:
            # Scalar (tab name, workspace_mode, modality)
            parts.append(f'"{key}":{json.dumps(val)}')

    # Include context_incomplete flag if present
    if full_data.get("context_incomplete"):
        parts.append('"context_incomplete":true')

    result = "{" + ",".join(parts) + "}"

    if max_tokens > 0:
        result = truncate_text(result, max_tokens)

    log.debug(
        "build_task_context[%s]: %d→%d tokens (%d/%d keys)",
        task_type.value,
        estimate_tokens(full_state_json), estimate_tokens(result),
        len(parts), len(full_data),
    )
    return result


# ── Compact state summary for BASIC tier ─────────────────────────────────────

def compact_state_summary(full_state_json: str) -> str:
    """Produce a minimal natural-language state summary for BASIC-tier models.

    BASIC models have tiny context windows (4K tokens).  Instead of raw
    JSON (which wastes tokens on syntax), this produces a terse English
    summary that small models handle better.

    Example output:
        "Camera: connected, 500µs exposure, 6dB gain. FPGA: running 1kHz 50%.
         TEC1: 25.0°C (stable). Stage: homed. Tab: Camera."
    """
    try:
        data = json.loads(full_state_json)
    except (json.JSONDecodeError, TypeError):
        return "Instrument state unavailable."

    lines: list[str] = []

    # Camera
    cam = data.get("cam", {})
    if cam.get("connected"):
        parts = ["connected"]
        if cam.get("exposure_us"):
            parts.append(f"{cam['exposure_us']:.0f}µs")
        if cam.get("gain_db"):
            parts.append(f"{cam['gain_db']:.1f}dB")
        lines.append(f"Camera: {', '.join(parts)}")
    else:
        lines.append("Camera: disconnected")

    # FPGA
    fpga = data.get("fpga", {})
    if fpga.get("connected"):
        state = "running" if fpga.get("running") else "stopped"
        parts = [state]
        if fpga.get("freq_hz"):
            hz = fpga["freq_hz"]
            parts.append(f"{hz/1000:.0f}kHz" if hz >= 1000 else f"{hz:.0f}Hz")
        if fpga.get("duty_pct") is not None:
            parts.append(f"{fpga['duty_pct']:.0f}%")
        lines.append(f"FPGA: {' '.join(parts)}")

    # TECs
    for tec in data.get("tecs", []):
        idx = tec.get("idx", 0)
        if tec.get("enabled"):
            temp = tec.get("actual_c", "?")
            sp = tec.get("setpoint_c", "?")
            lines.append(f"TEC{idx+1}: {temp}°C (set {sp}°C)")

    # Stage
    stage = data.get("stage", {})
    if stage.get("connected"):
        lines.append(f"Stage: {'homed' if stage.get('homed') else 'not homed'}")

    # Active issues
    rules = data.get("rules", [])
    if rules:
        issues = [r.get("id", "?") for r in rules if r.get("sev") in ("warn", "fail")]
        if issues:
            lines.append(f"Issues: {', '.join(issues[:5])}")

    # Active tab
    tab = data.get("tab", "")
    if tab:
        lines.append(f"Tab: {tab}")

    return ". ".join(lines) + "." if lines else "No instrument state."
