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


# ── Prompt builder ───────────────────────────────────────────────────────────

def build_advisor_prompt(
    profile_summary: dict,
    instrument_state: str,
    diagnostics_summary: str,
    system_prompt: str,
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
        The active system prompt (persona + domain knowledge).
    """
    profile_json = json.dumps(profile_summary, indent=2, default=str)

    user_content = (
        f"Instrument state:\n{instrument_state}\n\n"
        f"Selected profile:\n{profile_json}\n\n"
    )
    if diagnostics_summary:
        user_content += f"Current diagnostic issues:\n{diagnostics_summary}\n\n"

    user_content += (
        "Analyse the selected profile against the current instrument state. "
        "Identify any conflicts where the instrument's current settings "
        "don't match what the profile requires, and suggest fixes.\n\n"
        "Respond with ONLY a JSON object in this exact format:\n"
        "```json\n"
        "{\n"
        '  "conflicts": [\n'
        '    {"issue": "description", "param": "setting_name", '
        '"value": suggested_value, "unit": "unit"}\n'
        "  ],\n"
        '  "suggestions": [\n'
        '    {"param": "setting_name", "value": suggested_value, '
        '"unit": "unit", "reason": "why"}\n'
        "  ],\n"
        '  "ready": true\n'
        "}\n"
        "```\n\n"
        "Set ready=true if the instrument can proceed as-is (conflicts are "
        "warnings only). Set ready=false if acquisition would produce poor "
        "results without fixes. Keep the response concise."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ]


def profile_to_summary(profile) -> dict:
    """Extract key profile fields into a flat dict for the prompt."""
    return {
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
        "snr_threshold_db":  getattr(profile, "snr_threshold_db", None),
        "roi_strategy":      getattr(profile, "roi_strategy", None),
    }


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
