"""
ai/advisor.py

Proactive AI Advisor — analyses profile vs instrument state for conflicts.

When the user selects a camera + profile, the advisor asks the AI to
identify conflicts (e.g. exposure too high for the lock-in frequency)
and suggest corrective settings.

The advisor is **modality-aware**: it adapts its physics reasoning to
the active measurement technique (thermoreflectance, IR thermal imaging,
or future camera plugins).  New modalities are supported by adding an
entry to ``_MODALITY_CONTEXT``.

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
    summary: str = ""         # overall assessment (cloud models only)
    ready: bool = True
    raw_text: str = ""        # full AI response for fallback display
    parse_ok: bool = False    # True if JSON was parsed successfully


# ── Modality-specific context ────────────────────────────────────────────────
#
# Each measurement modality has distinct physics.  The advisor adapts its
# reasoning by injecting the relevant context.  To support a new camera /
# modality plugin, add an entry here — no other advisor code needs changing.

_MODALITY_CONTEXT: dict[str, dict] = {
    "thermoreflectance": {
        "instrument": "thermoreflectance microscope",
        "physics": (
            "lock-in timing, SNR, thermal settling, saturation risk, "
            "reflectance coefficient (C_T), LED wavelength matching"
        ),
        "adjustable": (
            "exposure_us, gain_db, stimulus_freq_hz, stimulus_duty, "
            "tec_setpoint_c, n_frames"
        ),
    },
    "ir_lockin": {
        "instrument": "IR thermal imaging microscope",
        "physics": (
            "emissivity, NUC/FFC calibration freshness, thermal range, "
            "integration time, stimulus frequency, DUT self-heating"
        ),
        "adjustable": (
            "exposure_us, stimulus_freq_hz, stimulus_duty, "
            "tec_setpoint_c, n_frames"
        ),
    },
}

# Fallback for unknown / future modalities — generic enough to be useful
_DEFAULT_MODALITY = {
    "instrument": "thermal measurement system",
    "physics": (
        "thermal settling, signal-to-noise ratio, exposure, "
        "stimulus timing, saturation risk"
    ),
    "adjustable": (
        "exposure_us, gain_db, stimulus_freq_hz, stimulus_duty, "
        "tec_setpoint_c, n_frames"
    ),
}


def _modality_info(modality: str) -> dict:
    """Return modality context dict, falling back to generic defaults."""
    return _MODALITY_CONTEXT.get(modality, _DEFAULT_MODALITY)


# ── Advisor system prompt ────────────────────────────────────────────────────

def _build_advisor_system(cloud: bool = False,
                          modality: str = "thermoreflectance") -> str:
    """
    Build the advisor system prompt, adapted to the active modality.

    Parameters
    ----------
    cloud : bool
        When True (cloud provider), requests physics explanations alongside
        JSON.  When False (local model), requests JSON only to minimise
        prefill and generation time.
    modality : str
        Active measurement modality (``"thermoreflectance"``, ``"ir_lockin"``,
        or any future modality string).  Controls the physics context and
        adjustable parameter list so the AI reasons correctly for the
        measurement technique in use.
    """
    from ai.instrument_knowledge import AI_DOMAIN_KNOWLEDGE

    info = _modality_info(modality)

    role = (
        f"You are an expert instrument configuration advisor for a "
        f"{info['instrument']} (Microsanj SanjINSIGHT). "
        f"Compare the selected material profile against the current "
        f"instrument state and identify conflicts or mismatches. "
        f"Valid adjustable parameters: {info['adjustable']}. "
    )

    if cloud:
        role += (
            f"For each conflict, explain WHY it matters in terms of "
            f"measurement physics ({info['physics']}) "
            f"so the user can make an informed decision. "
            f"Include a 'summary' field with a 1-2 sentence overall assessment. "
        )
    else:
        role += "Respond with ONLY a JSON object — no prose, no markdown headings. "

    return role + AI_DOMAIN_KNOWLEDGE


# Maximum tokens for the advisor response.
# Local: compact JSON is 100–300 tokens; 512 gives headroom.
# Cloud: richer explanations need more room; 1024 is comfortable.
ADVISOR_MAX_TOKENS_LOCAL: int = 512
ADVISOR_MAX_TOKENS_CLOUD: int = 1024


# ── Prompt builder ───────────────────────────────────────────────────────────

def build_advisor_prompt(
    profile_summary: dict,
    instrument_state: str,
    diagnostics_summary: str,
    cloud: bool = False,
    modality: str = "thermoreflectance",
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
    cloud : bool
        True when using a cloud provider (Claude/ChatGPT).  Produces a
        richer prompt that asks for explanations alongside the JSON.
    modality : str
        Active measurement modality — passed to the system prompt builder
        so the AI adapts its physics reasoning.
    """
    profile_json = json.dumps(
        profile_summary,
        separators=(",", ":") if not cloud else (", ", ": "),
        default=str,
    )

    user_content = (
        f"Instrument state:\n{instrument_state}\n\n"
        f"Selected profile:\n{profile_json}\n\n"
    ) if cloud else (
        f"State:{instrument_state}\n"
        f"Profile:{profile_json}\n"
    )

    if diagnostics_summary:
        user_content += (
            f"Current diagnostic issues:\n{diagnostics_summary}\n\n"
            if cloud else f"Issues:\n{diagnostics_summary}\n"
        )

    if cloud:
        user_content += (
            "Analyse this profile against the instrument state. "
            "Respond with a JSON object in this format:\n"
            "```json\n"
            "{\n"
            '  "summary": "1-2 sentence overall assessment",\n'
            '  "conflicts": [\n'
            '    {"issue": "what is wrong and WHY it matters physically",\n'
            '     "param": "setting_name", "value": suggested_value, "unit": "unit"}\n'
            "  ],\n"
            '  "suggestions": [\n'
            '    {"param": "setting_name", "value": suggested_value,\n'
            '     "unit": "unit", "reason": "physics-based explanation"}\n'
            "  ],\n"
            '  "ready": true\n'
            "}\n"
            "```\n"
            "Set ready=false if acquisition would produce poor results. "
            "Explain each conflict in terms of measurement physics "
            "(lock-in timing, SNR impact, thermal settling, saturation, etc.)."
        )
    else:
        user_content += (
            "\nRespond with ONLY this JSON:\n"
            '{"conflicts":[{"issue":"...","param":"...","value":N,"unit":"..."}],'
            '"suggestions":[{"param":"...","value":N,"unit":"...","reason":"..."}],'
            '"ready":true}\n'
            "ready=false if acquisition would fail without fixes. Be concise."
        )

    return [
        {"role": "system", "content": _build_advisor_system(
            cloud=cloud, modality=modality)},
        {"role": "user",   "content": user_content},
    ]


def profile_to_summary(profile, camera_type: str = "tr") -> dict:
    """Extract key profile fields into a compact dict for the prompt.

    Parameters
    ----------
    profile
        MaterialProfile (or any object with the expected attributes).
    camera_type : str
        Active camera type (``"tr"``, ``"ir"``, etc.).  Included so the
        AI knows which camera is in use regardless of profile modality.

    Omits None values to reduce token count.
    """
    raw: dict = {
        "name":              getattr(profile, "name", "?"),
        "material":          getattr(profile, "material", "?"),
        "modality":          getattr(profile, "modality", "any"),
        "camera_type":       camera_type,
        "exposure_us":       getattr(profile, "exposure_us", None),
        "n_frames":          getattr(profile, "n_frames", None),
        "stimulus_freq_hz":  getattr(profile, "stimulus_freq_hz", None),
        "stimulus_duty":     getattr(profile, "stimulus_duty", None),
        "tec_enabled":       getattr(profile, "tec_enabled", False),
        "tec_setpoint_c":    getattr(profile, "tec_setpoint_c", None),
        "bias_enabled":      getattr(profile, "bias_enabled", False),
        "bias_voltage_v":    getattr(profile, "bias_voltage_v", None),
    }
    # TR-specific fields (irrelevant for IR cameras)
    if camera_type == "tr" or getattr(profile, "modality", "") == "tr":
        raw["gain_db"]       = getattr(profile, "gain_db", None)
        raw["ct_value"]      = getattr(profile, "ct_value", None)
        raw["wavelength_nm"] = getattr(profile, "wavelength_nm", None)
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
    result.summary = data.get("summary", "")

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
