"""
ai/advisor.py

Proactive AI Advisor — analyses profile vs instrument state for conflicts.

When the user selects a camera + profile, the advisor asks the AI to
identify conflicts (e.g. exposure too high for the lock-in frequency)
and suggest corrective settings.  Requires FULL tier because reliable
structured JSON output is needed.

The advisor prompt requests a JSON response; ``parse_advice()`` extracts
it with graceful fallback if the model returns prose instead of JSON.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class Conflict:
    """One conflict between profile and instrument state."""
    issue: str = ""
    param: str = ""     # setting to change (e.g. "exposure")
    value: object = None  # suggested value
    unit: str = ""

@dataclass
class Suggestion:
    """One optional improvement suggestion."""
    param: str = ""
    value: object = None
    unit: str = ""
    reason: str = ""

@dataclass
class AdvisorResult:
    """Parsed result from the AI advisor analysis."""
    conflicts: list[Conflict] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    ready: bool = True
    raw_text: str = ""        # full AI response for fallback display
    parse_ok: bool = False    # True if JSON was parsed successfully


# ── Advisor system prompt (compact — no guides, nav map, or domain corpus) ───
#
# The full system prompt used for chat is ~3 000 tokens.  The advisor needs
# only instrument-analysis capability, so we use a focused ~150-token prompt
# to minimise prefill time on local models.

def _build_advisor_system() -> str:
    """Compact system prompt: role + domain knowledge, no nav map or guide."""
    from ai.instrument_knowledge import AI_DOMAIN_KNOWLEDGE
    return (
        "You are an instrument configuration advisor for a thermoreflectance "
        "microscope. Compare the selected material profile against the current "
        "instrument state and identify conflicts or mismatches. "
        "Valid adjustable parameters: exposure_us, gain_db, stimulus_freq_hz, "
        "stimulus_duty, tec_setpoint_c, n_frames. "
        "Respond with ONLY a JSON object — no prose, no markdown headings. "
        + AI_DOMAIN_KNOWLEDGE
    )

# Maximum tokens for the advisor response.  A typical structured JSON
# response is 100–300 tokens; 512 gives headroom without wasting time.
ADVISOR_MAX_TOKENS: int = 512


# ── Prompt builder ───────────────────────────────────────────────────────────

def build_advisor_prompt(
    profile_summary: dict,
    instrument_state: str,
    diagnostics_summary: str,
    system_prompt: str = "",
) -> list[dict]:
    """
    Build the messages list for the advisor analysis.

    Parameters
    ----------
    profile_summary : dict
        Key profile fields (name, material, exposure, gain, freq, etc.).
    instrument_state : str
        JSON from ContextBuilder.build().
    diagnostics_summary : str
        Human-readable summary of current diagnostic issues.
    system_prompt : str
        Ignored — kept for API compatibility.  The advisor uses its own
        compact system prompt to minimise inference time.
    """
    profile_json = json.dumps(profile_summary, separators=(",", ":"), default=str)

    user_content = (
        f"State:{instrument_state}\n"
        f"Profile:{profile_json}\n"
    )
    if diagnostics_summary:
        user_content += f"Issues:\n{diagnostics_summary}\n"

    user_content += (
        "\nRespond with ONLY this JSON:\n"
        '{"conflicts":[{"issue":"...","param":"...","value":N,"unit":"..."}],'
        '"suggestions":[{"param":"...","value":N,"unit":"...","reason":"..."}],'
        '"ready":true}\n'
        "ready=false if acquisition would fail without fixes. Be concise."
    )

    return [
        {"role": "system", "content": _build_advisor_system()},
        {"role": "user",   "content": user_content},
    ]


def profile_to_summary(profile) -> dict:
    """Extract key profile fields into a compact dict for the prompt.

    Omits None values to reduce token count.
    """
    raw = {
        "name":              getattr(profile, "name", "?"),
        "material":          getattr(profile, "material", "?"),
        "modality":          getattr(profile, "modality", "any"),
        "exposure_us":       getattr(profile, "exposure_us", None),
        "gain_db":           getattr(profile, "gain_db", None),
        "n_frames":          getattr(profile, "n_frames", None),
        "stimulus_freq_hz":  getattr(profile, "stimulus_freq_hz", None),
        "stimulus_duty":     getattr(profile, "stimulus_duty", None),
        "tec_enabled":       getattr(profile, "tec_enabled", False),
        "tec_setpoint_c":    getattr(profile, "tec_setpoint_c", None),
        "bias_enabled":      getattr(profile, "bias_enabled", False),
        "bias_voltage_v":    getattr(profile, "bias_voltage_v", None),
        "ct_value":          getattr(profile, "ct_value", None),
        "wavelength_nm":     getattr(profile, "wavelength_nm", None),
    }
    return {k: v for k, v in raw.items() if v is not None}


# ── Response parser ──────────────────────────────────────────────────────────

def parse_advice(raw_text: str) -> AdvisorResult:
    """
    Parse the AI response into an AdvisorResult.

    Tries to extract JSON from the response.  If the model returned prose
    instead of JSON, returns a result with parse_ok=False and the raw text
    so the dialog can display it as fallback.
    """
    result = AdvisorResult(raw_text=raw_text.strip())

    # Try to find JSON in the response (may be wrapped in ```json ... ```)
    json_str = _extract_json(raw_text)
    if not json_str:
        return result

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return result

    if not isinstance(data, dict):
        return result

    result.parse_ok = True
    result.ready = data.get("ready", True)

    for c in data.get("conflicts", []):
        if isinstance(c, dict):
            result.conflicts.append(Conflict(
                issue=c.get("issue", ""),
                param=c.get("param", ""),
                value=c.get("value"),
                unit=c.get("unit", ""),
            ))

    for s in data.get("suggestions", []):
        if isinstance(s, dict):
            result.suggestions.append(Suggestion(
                param=s.get("param", ""),
                value=s.get("value"),
                unit=s.get("unit", ""),
                reason=s.get("reason", ""),
            ))

    return result


def _extract_json(text: str) -> Optional[str]:
    """Pull a JSON object from text, handling ```json fences."""
    # Try fenced code block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Try bare JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return None
