"""
ai/prompt_templates.py

System prompt and per-query message templates for the SanjINSIGHT assistant.

Design goals
------------
  • The Quickstart Guide is ALWAYS embedded in the system prompt so every
    user gets workflow and navigation answers out of the box.
  • Out-of-scope questions (topics not in the Quickstart Guide) receive a
    polite canned response with a link to the full User Manual online.
  • Use unambiguous formatting — model produces plain text, not markdown.
  • Ground every response in the JSON instrument state injected at runtime.
  • Include UI_NAV_MAP so the AI can answer "where is X?" with the correct
    sidebar panel name rather than a generic non-answer.

Token budget (approximate)
--------------------------
  System prompt  ≈ 2 600 tokens  (persona base + domain knowledge +
                                   UI nav map + Quickstart Guide)
  Context JSON   ≈   250 tokens
  Question       ≈    30 tokens
  ─────────────────────────────
  Total          ≈ 2 880 tokens  → fits in any 4 096-token context window
"""

from __future__ import annotations

import pathlib

from version import DOCS_URL
from ai.instrument_knowledge import AI_DOMAIN_KNOWLEDGE, UI_NAV_MAP


# ── Load Quickstart Guide from disk ───────────────────────────────────────────
#
# Resolved relative to this file so it works regardless of working directory.
# Falls back to an empty string if the file is missing (packaged builds).

_DOCS_DIR = pathlib.Path(__file__).parent.parent / "docs"

QUICKSTART_GUIDE: str = (
    (_DOCS_DIR / "QuickstartGuide.md").read_text(encoding="utf-8")
    if (_DOCS_DIR / "QuickstartGuide.md").exists() else ""
)

# URL shown in out-of-scope responses  (canonical source: version.py)
USER_MANUAL_URL: str = DOCS_URL

# Default llama-cpp n_ctx — fits the Quickstart prompt comfortably.
DEFAULT_N_CTX: int = 4_096

# ── Response instructions ──────────────────────────────────────────────────────

# Guides the model to return a canned response for out-of-scope questions.
_OUT_OF_SCOPE_INSTRUCTION: str = (
    "Your documentation knowledge comes from: the Quickstart Guide above, "
    "any relevant User Manual sections provided with a question, "
    "and the live instrument state. "
    "If a user asks about something covered in neither the Quickstart Guide "
    "nor the provided manual sections "
    "(such as detailed calibration math, configuration file syntax, advanced "
    "scan settings, or hardware specifications not listed above), "
    "respond with exactly: "
    "\"Due to my current token limit, I can only access selected sections of "
    "the documentation. "
    "You can find the complete User Manual here: "
    f"{USER_MANUAL_URL}\" "
    "Do not attempt to guess or infer information not present in the "
    "documentation provided."
)


# ── Prompt builder ─────────────────────────────────────────────────────────────

# Default base string used when no persona is active (e.g. tests, direct calls).
_DEFAULT_BASE: str = (
    "You are the SanjINSIGHT instrument assistant for thermoreflectance microscopy. "
    "Give concise, accurate guidance about instrument settings, acquisition quality, "
    "and troubleshooting. "
    "Use the JSON instrument state to ground every answer. "
    "When users ask where to find a control, name the exact sidebar panel. "
    "Keep responses 2-4 sentences. Plain text only — no markdown. "
    "Say so honestly if you cannot help. Never invent hardware readings. "
)

def build_system_prompt(base: str) -> str:
    """
    Assemble a complete system prompt from a persona base string.

    Always appends AI_DOMAIN_KNOWLEDGE, UI_NAV_MAP, the Quickstart Guide,
    and the out-of-scope canned-response instruction.

    Parameters
    ----------
    base : str
        The persona-specific tone / style instructions (e.g. from PERSONAS).

    Returns
    -------
    str
        The assembled system prompt ready for create_chat_completion().
    """
    prompt = base + " " + AI_DOMAIN_KNOWLEDGE + " " + UI_NAV_MAP

    if QUICKSTART_GUIDE:
        prompt += (
            "\n\n=== SanjINSIGHT Quickstart Guide ===\n"
            + QUICKSTART_GUIDE
            + "=== End of Quickstart Guide ===\n\n"
        )

    prompt += _OUT_OF_SCOPE_INSTRUCTION
    return prompt


# Convenience constant for callers that don't use a persona (tests, CLI, etc.)
SYSTEM_PROMPT: str = build_system_prompt(_DEFAULT_BASE)


# ── Per-query templates ────────────────────────────────────────────────────────

def explain_tab(
    tab_name: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
) -> list[dict]:
    """
    Ask the model to explain the active tab and what the user should do next.

    Parameters
    ----------
    manual_context : str
        Optional User Manual snippet retrieved by manual_rag for this tab.

    Returns a messages list ready for create_chat_completion().
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"I am looking at the '{tab_name}' tab. "
                "In 2-3 sentences, explain what this tab does and what I should "
                "check or adjust given the current instrument state."
                + extra
            ),
        },
    ]


def diagnose(
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
) -> list[dict]:
    """
    Ask the model to review current issues and suggest fixes.

    Parameters
    ----------
    manual_context : str
        Optional User Manual snippet retrieved by manual_rag for the active tab.

    Returns a messages list.
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                "Review the instrument state above. List any problems you see and, "
                "for each, suggest one concrete fix. Be specific about settings or "
                "actions. If everything looks good, say so briefly."
                + extra
            ),
        },
    ]


def free_ask(
    question: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
) -> list[dict]:
    """
    Free-form question with instrument context.

    Parameters
    ----------
    manual_context : str
        Optional snippet from the User Manual retrieved by manual_rag.retrieve().
        Injected after the question so the model can cite manual details.

    Returns a messages list.
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"Question: {question}"
                + extra
            ),
        },
    ]


def session_report(
    result_data: dict,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """
    Ask the model to generate a one-paragraph post-acquisition quality report.

    result_data keys (all optional, use whatever is available):
      grade           str   instrument grade at acquisition start (A/B/C/D)
      issues          list  dicts with keys name, sev, obs
      n_frames        int   total frames requested
      cold_captured   int   cold frames captured
      hot_captured    int   hot frames captured
      duration_s      float wall-clock duration
      exposure_us     float camera exposure in µs
      gain_db         float camera gain in dB
      snr_db          float ΔR/R signal-to-noise ratio in dB (None if unavailable)
      dark_pixel_pct  float percentage of dark/masked pixels
      complete        bool  whether ΔR/R computation succeeded

    Returns a messages list ready for create_chat_completion().
    """
    grade     = result_data.get("grade", "?")
    issues    = result_data.get("issues", [])
    n_frames  = result_data.get("n_frames", "?")
    cold      = result_data.get("cold_captured", "?")
    hot       = result_data.get("hot_captured", "?")
    dur       = result_data.get("duration_s", None)
    exp_us    = result_data.get("exposure_us", None)
    gain      = result_data.get("gain_db", None)
    snr       = result_data.get("snr_db", None)
    dark_pct  = result_data.get("dark_pixel_pct", None)
    complete  = result_data.get("complete", False)

    issue_lines = ""
    if issues:
        issue_lines = "Active issues at start:\n" + "\n".join(
            f"  {i.get('sev','?').upper()}: {i.get('name','?')} — {i.get('obs','?')}"
            for i in issues
        ) + "\n"

    metrics = [f"Frames: {cold} cold + {hot} hot (of {n_frames} requested)"]
    if dur    is not None: metrics.append(f"Duration: {dur:.1f} s")
    if exp_us is not None: metrics.append(f"Exposure: {exp_us:.0f} µs")
    if gain   is not None: metrics.append(f"Gain: {gain:.1f} dB")
    if snr    is not None: metrics.append(f"SNR: {snr:.1f} dB")
    if dark_pct is not None: metrics.append(f"Dark pixels: {dark_pct:.1f}%")
    metrics.append(f"Status: {'Complete' if complete else 'Incomplete'}")

    content = (
        f"Instrument state: {context_json}\n\n"
        f"Acquisition just completed. Pre-acquisition grade: {grade}.\n"
        f"{issue_lines}"
        f"Result metrics:\n" + "\n".join(f"  {m}" for m in metrics) + "\n\n"
        "In 3-4 sentences, give a quality assessment of this acquisition. "
        "Comment on SNR, dark pixel fraction, and any pre-existing issues that "
        "may have affected the result. Suggest one concrete improvement for the "
        "next acquisition if warranted. Plain text only."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": content},
    ]
