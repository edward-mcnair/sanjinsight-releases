"""
ai/capability_tier.py

AI capability tier system for SanjINSIGHT.

Features are gated by model capability so small local models get a useful
but limited experience, while large local or cloud models unlock the full
AI-assisted workflow.

Tier hierarchy
--------------
  NONE      No model loaded — all AI features hidden.
  BASIC     Small local models (<=3.8B params, 4K context).
            Text Q&A, explain tab, diagnose issues.
  STANDARD  Medium local models (7B+, 8K context).
            Adds quickstart guide, session reports, richer history.
  FULL      Large local (14B+) or any cloud provider.
            Adds proactive advisor, structured suggestions, voice,
            AI-assisted acquisition automation.

Ollama models are classified at runtime by parameter count from the
``/api/show`` endpoint.  Curated GGUF models carry a ``tier`` field
in model_catalog.py.
"""

from __future__ import annotations

import enum
import logging
from typing import Optional

log = logging.getLogger(__name__)


class AITier(enum.IntEnum):
    """AI capability tier — higher value means more features."""
    NONE     = 0
    BASIC    = 1
    STANDARD = 2
    FULL     = 3


# ── Tier lookup for catalog models ───────────────────────────────────────────

def tier_for_catalog_model(model_path: str) -> AITier:
    """
    Return the tier for a local GGUF model by matching its filename
    against MODEL_CATALOG entries.

    Falls back to STANDARD for unknown/custom models (reasonable middle
    ground — custom models are usually 7B+).
    """
    from pathlib import Path
    from ai.model_catalog import MODEL_CATALOG

    filename = Path(model_path).name
    for entry in MODEL_CATALOG.values():
        if entry["filename"] == filename:
            return AITier(entry.get("tier", AITier.STANDARD))
    # Unknown model — assume at least STANDARD capability
    log.info("Unknown model file %r — defaulting to STANDARD tier", filename)
    return AITier.STANDARD


def tier_for_ollama_model(model_id: str, timeout: float = 3.0) -> AITier:
    """
    Classify an Ollama model by parameter count from ``/api/show``.

    Parameter-count ranges::

        <= 4B   → BASIC
        5B–13B  → STANDARD
        14B+    → FULL

    Falls back to STANDARD if the Ollama server is unreachable or the
    model metadata cannot be parsed.
    """
    import http.client
    import json
    from ai.ollama import OLLAMA_HOST, OLLAMA_PORT

    try:
        conn = http.client.HTTPConnection(
            OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
        body = json.dumps({"name": model_id}).encode()
        conn.request("POST", "/api/show", body=body,
                     headers={"content-type": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            return AITier.STANDARD

        data = json.loads(resp.read())
        conn.close()

        # Ollama returns model_info or details with parameter counts
        params = _extract_param_count(data)
        if params is None:
            return AITier.STANDARD

        if params <= 4_000_000_000:
            return AITier.BASIC
        if params <= 13_000_000_000:
            return AITier.STANDARD
        return AITier.FULL

    except Exception:
        log.debug("Could not query Ollama for model %r — defaulting STANDARD",
                  model_id)
        return AITier.STANDARD


def _extract_param_count(show_data: dict) -> Optional[int]:
    """
    Extract parameter count from Ollama /api/show response.

    Ollama returns this in several places depending on version:
      - model_info["general.parameter_count"]  (int)
      - details["parameter_size"]              ("7B", "14.2B", "1.5B")
    """
    # Try model_info first (most reliable, integer)
    model_info = show_data.get("model_info", {})
    if isinstance(model_info, dict):
        count = model_info.get("general.parameter_count")
        if isinstance(count, (int, float)) and count > 0:
            return int(count)

    # Fall back to details.parameter_size string ("7B", "14.2B", etc.)
    details = show_data.get("details", {})
    if isinstance(details, dict):
        size_str = details.get("parameter_size", "")
        return _parse_param_size(size_str)

    return None


def _parse_param_size(size_str: str) -> Optional[int]:
    """Parse ``"7B"`` / ``"14.2B"`` / ``"1.5B"`` → integer parameter count."""
    if not size_str:
        return None
    s = size_str.strip().upper()
    multiplier = 1
    if s.endswith("B"):
        s = s[:-1]
        multiplier = 1_000_000_000
    elif s.endswith("M"):
        s = s[:-1]
        multiplier = 1_000_000
    try:
        return int(float(s) * multiplier)
    except (ValueError, OverflowError):
        return None


# ── Token budget per tier ────────────────────────────────────────────────────

# Controls how much context is injected per tier to avoid stuffing small
# models beyond their effective capacity.

TIER_TOKEN_BUDGET = {
    AITier.NONE: {
        "max_history_turns": 0,
        "include_guide":     False,
        "include_manual_rag": False,
        "max_tokens_reply":  0,
    },
    AITier.BASIC: {
        "max_history_turns": 2,
        "include_guide":     False,
        "include_manual_rag": False,
        "max_tokens_reply":  512,
    },
    AITier.STANDARD: {
        "max_history_turns": 6,
        "include_guide":     True,
        "include_manual_rag": True,
        "max_tokens_reply":  1024,
    },
    AITier.FULL: {
        "max_history_turns": 6,
        "include_guide":     True,
        "include_manual_rag": True,
        "max_tokens_reply":  2048,
    },
}


def budget_for(tier: AITier) -> dict:
    """Return the token budget dict for the given tier."""
    return TIER_TOKEN_BUDGET.get(tier, TIER_TOKEN_BUDGET[AITier.STANDARD])


# ── Feature availability ─────────────────────────────────────────────────────

# Simple lookup: ``can(tier, "proactive_advisor")`` → bool.
# New features are registered here as the roadmap progresses.

_FEATURE_GATES: dict[str, AITier] = {
    # BASIC tier (text Q&A)
    "chat":                AITier.BASIC,
    "explain_tab":         AITier.BASIC,
    "diagnose":            AITier.BASIC,

    # STANDARD tier (richer context, reports)
    "session_report":      AITier.STANDARD,
    "manual_rag":          AITier.STANDARD,
    "quickstart_guide":    AITier.STANDARD,

    # STANDARD tier (structured output)
    "proactive_advisor":   AITier.STANDARD,

    # FULL tier (interactive automation)
    "structured_response": AITier.FULL,
    "voice_commands":      AITier.FULL,
    "ai_acquisition":      AITier.FULL,
    "batch_insights":      AITier.FULL,
    "explain_diagnostics": AITier.FULL,
}


def can(tier: AITier, feature: str) -> bool:
    """Return True if *tier* supports *feature*."""
    min_tier = _FEATURE_GATES.get(feature)
    if min_tier is None:
        log.warning("Unknown AI feature %r — denying", feature)
        return False
    return tier >= min_tier


def available_features(tier: AITier) -> list[str]:
    """Return a sorted list of feature names available at *tier*."""
    return sorted(f for f, min_t in _FEATURE_GATES.items() if tier >= min_t)


def tier_display_name(tier: AITier) -> str:
    """Human-readable tier name for UI display."""
    return {
        AITier.NONE:     "Off",
        AITier.BASIC:    "Basic",
        AITier.STANDARD: "Standard",
        AITier.FULL:     "Full",
    }.get(tier, "Unknown")


def tier_description(tier: AITier) -> str:
    """Short description of the tier's capabilities for tooltips / UI."""
    return {
        AITier.NONE:     "No AI model loaded.",
        AITier.BASIC:    "Text Q&A, tab explanations, issue diagnosis.",
        AITier.STANDARD: "Adds session reports, quickstart guide, AI advisor.",
        AITier.FULL:     "Full AI: voice commands, smart suggestions, automation.",
    }.get(tier, "")


def upgrade_message(feature: str, current_tier: AITier) -> str:
    """
    Return a user-facing message explaining why *feature* is unavailable
    and how to upgrade.  Returns ``""`` if the feature is already available.
    """
    min_tier = _FEATURE_GATES.get(feature)
    if min_tier is None or current_tier >= min_tier:
        return ""

    _feature_labels = {
        "session_report":      "Session Reports",
        "manual_rag":          "Manual Search",
        "quickstart_guide":    "Quickstart Guide",
        "proactive_advisor":   "AI Advisor",
        "structured_response": "Smart Suggestions",
        "voice_commands":      "Voice Commands",
        "ai_acquisition":      "AI-Assisted Acquisition",
        "batch_insights":      "Batch Insights",
        "explain_diagnostics": "Diagnostic Insights",
    }
    label = _feature_labels.get(feature, feature)
    target = tier_display_name(min_tier)

    if min_tier == AITier.FULL:
        how = ("Upgrade to Qwen 2.5 — 14B (8.8 GB) or connect a cloud "
               "provider (Claude / ChatGPT) in Settings → AI.")
    elif min_tier == AITier.STANDARD:
        how = ("Upgrade to Qwen 2.5 — 7B (4.5 GB) or larger in "
               "Settings → AI → Local Model.")
    else:
        how = "Enable an AI model in Settings → AI."

    return f"{label} requires {target} tier.  {how}"
