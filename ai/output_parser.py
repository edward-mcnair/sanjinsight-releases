"""
ai/output_parser.py

Structured output validation, repair, and fallback for the SanjINSIGHT AI
assistant.

Problems solved
---------------
  1. Small local models often produce malformed JSON — missing closing
     braces, trailing commas, markdown fences, or prose preamble.
  2. Different tiers need different schema complexity — BASIC models
     should produce simpler structures than FULL models.
  3. Parse failures should degrade gracefully to prose display, not crash.

Design
------
  • ``parse_json_response()`` — extract and validate JSON from raw AI text,
    with one repair attempt for common issues.
  • ``tier_schema()`` — returns the expected schema complexity for a tier.
  • Repair strategies: strip markdown fences, fix trailing commas, close
    unclosed braces/brackets, extract JSON from surrounding prose.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


# ── Parse result ─────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """Result of attempting to parse structured output from AI text."""
    data:       Optional[dict] = None    # parsed JSON object (None if failed)
    raw_text:   str = ""                 # original AI response
    parse_ok:   bool = False             # True if JSON was extracted
    repaired:   bool = False             # True if repair was needed
    error:      str = ""                 # parse error description (empty if ok)


# ── JSON extraction and repair ───────────────────────────────────────────────

def parse_json_response(
    raw_text: str,
    required_keys: tuple[str, ...] = (),
) -> ParseResult:
    """Extract a JSON object from raw AI text, with repair on failure.

    Parameters
    ----------
    raw_text : str
        The full AI response text (may contain prose, markdown, or fences).
    required_keys : tuple[str, ...]
        Keys that must be present in the parsed JSON for it to be valid.
        If any are missing after parsing, the result is marked as failed.

    Returns
    -------
    ParseResult
        Contains the parsed data (or None), plus metadata about the parse.
    """
    result = ParseResult(raw_text=raw_text.strip())

    if not raw_text or not raw_text.strip():
        result.error = "empty response"
        return result

    # Step 1: Try to extract JSON directly
    json_str = _extract_json_block(raw_text)
    if json_str:
        data = _try_parse(json_str)
        if data is not None:
            if _check_required_keys(data, required_keys):
                result.data = data
                result.parse_ok = True
                return result
            result.error = f"missing required keys: {required_keys}"
            result.data = data
            return result

    # Step 2: Try repair strategies
    repaired = _repair_json(raw_text)
    if repaired:
        data = _try_parse(repaired)
        if data is not None:
            if _check_required_keys(data, required_keys):
                result.data = data
                result.parse_ok = True
                result.repaired = True
                log.debug("output_parser: JSON repaired successfully")
                return result
            result.error = f"repaired but missing keys: {required_keys}"
            result.data = data
            result.repaired = True
            return result

    result.error = "no valid JSON found in response"
    log.debug("output_parser: parse failed — %s (text: %.100s…)",
              result.error, raw_text)
    return result


# ── Internal helpers ─────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> Optional[str]:
    """Extract a JSON object from text, handling markdown fences."""
    # Try ```json ... ``` fenced block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Try bare JSON object (first { to last })
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]

    return None


def _try_parse(json_str: str) -> Optional[dict]:
    """Try to parse a JSON string, returning None on failure."""
    try:
        data = json.loads(json_str)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _check_required_keys(data: dict, required: tuple[str, ...]) -> bool:
    """Return True if all required keys are present."""
    if not required:
        return True
    return all(k in data for k in required)


def _repair_json(text: str) -> Optional[str]:
    """Attempt to repair common JSON issues in AI output.

    Repair strategies (applied in order):
      1. Strip markdown fences and prose preamble
      2. Fix trailing commas before } or ]
      3. Close unclosed braces/brackets
      4. Remove control characters
    """
    # Extract the JSON-like portion
    candidate = _extract_json_block(text)
    if not candidate:
        # Try stripping everything before first {
        first_brace = text.find("{")
        if first_brace == -1:
            return None
        candidate = text[first_brace:]

    # Remove control characters (except \n, \t)
    candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', candidate)

    # Fix trailing commas: ,} → } and ,] → ]
    candidate = re.sub(r',\s*}', '}', candidate)
    candidate = re.sub(r',\s*]', ']', candidate)

    # Close unclosed braces/brackets
    open_braces = candidate.count('{') - candidate.count('}')
    open_brackets = candidate.count('[') - candidate.count(']')
    if open_braces > 0:
        candidate += '}' * open_braces
    if open_brackets > 0:
        candidate += ']' * open_brackets

    # Strip trailing content after the last }
    last_brace = candidate.rfind('}')
    if last_brace != -1:
        candidate = candidate[:last_brace + 1]

    return candidate if candidate else None


# ── Tier-aware schema complexity ─────────────────────────────────────────────

# BASIC tier: simpler schemas that small models can reliably produce
# STANDARD: moderate schemas
# FULL: rich schemas with explanations

class SchemaComplexity:
    """Schema complexity levels for structured output."""
    MINIMAL  = "minimal"    # 2-3 flat keys, no nesting
    MODERATE = "moderate"   # arrays of simple objects
    RICH     = "rich"       # nested objects with explanations


def tier_schema_complexity(tier: int) -> str:
    """Return the appropriate schema complexity for a model tier.

    Parameters
    ----------
    tier : int
        AITier integer (0=NONE, 1=BASIC, 2=STANDARD, 3=FULL).
    """
    if tier <= 1:
        return SchemaComplexity.MINIMAL
    if tier == 2:
        return SchemaComplexity.MODERATE
    return SchemaComplexity.RICH


# ── Advisor-specific schemas per tier ────────────────────────────────────────

def advisor_schema_prompt(tier: int) -> str:
    """Return the JSON schema instruction string for the advisor,
    adapted to the model's capability tier.

    BASIC: flat object with ready/fix fields
    STANDARD: conflicts array with param/value
    FULL: rich objects with physics explanations
    """
    complexity = tier_schema_complexity(tier)

    if complexity == SchemaComplexity.MINIMAL:
        return (
            'Respond with ONLY this JSON (no other text):\n'
            '{"ready":true,"fix":"one sentence describing what to change"}\n'
            'Set ready=false if acquisition would fail.'
        )

    if complexity == SchemaComplexity.MODERATE:
        return (
            'Respond with ONLY this JSON:\n'
            '{"conflicts":[{"issue":"...","param":"...","value":N,"unit":"..."}],'
            '"suggestions":[{"param":"...","value":N,"unit":"...","reason":"..."}],'
            '"ready":true}\n'
            'ready=false if acquisition would fail without fixes. Be concise.'
        )

    # RICH (FULL tier)
    return (
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
        "Explain each conflict in terms of measurement physics."
    )
