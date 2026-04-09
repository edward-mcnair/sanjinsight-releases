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
  System prompt  ≈ 3 300 tokens  (persona base + domain knowledge +
                                   UI nav map + Quickstart Guide)
  Context JSON   ≈   250 tokens
  Question       ≈    30 tokens
  History (6T)   ≈   600 tokens
  Manual RAG     ≈   200 tokens
  ─────────────────────────────
  Total          ≈ 4 380 tokens  → requires n_ctx ≥ 8 192
                                   (DEFAULT_N_CTX = 8_192)
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

# Default llama-cpp n_ctx.
# The embedded Quickstart Guide alone is ~2,600 tokens; combined with
# domain knowledge, UI nav map, instrument state, conversation history,
# and manual RAG context, 4096 is too tight.  8192 fits comfortably and
# is natively supported by Qwen2.5-7B, Llama-3.x, Mistral-7B, and Phi-3.
DEFAULT_N_CTX: int = 8_192

# ── Response instructions ──────────────────────────────────────────────────────

# Two variants: one for models with the full Quickstart Guide embedded,
# one for small models that have only domain knowledge + UI nav.

_OUT_OF_SCOPE_WITH_GUIDE: str = (
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

_OUT_OF_SCOPE_NO_GUIDE: str = (
    "Your documentation knowledge comes from: the domain knowledge and UI "
    "navigation map above, any relevant User Manual sections provided with "
    "a question, and the live instrument state. "
    "If a user asks about detailed workflows, step-by-step procedures, "
    "calibration math, or topics not covered by the information above, "
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

# Minimum n_ctx required to embed the full Quickstart Guide.
# Below this the guide is skipped — AI still has domain knowledge + UI map.
_GUIDE_MIN_CTX: int = 8_192


def build_system_prompt(base: str, n_ctx: int = DEFAULT_N_CTX) -> str:
    """
    Assemble a complete system prompt from a persona base string.

    Appends AI_DOMAIN_KNOWLEDGE and UI_NAV_MAP unconditionally.
    The Quickstart Guide (~2 600 tokens) is only embedded when the
    model's context window is large enough to accommodate it alongside
    the instrument state, conversation history, and question.

    Parameters
    ----------
    base : str
        The persona-specific tone / style instructions (e.g. from PERSONAS).
    n_ctx : int
        The context window size the model was loaded with.  When n_ctx is
        below _GUIDE_MIN_CTX (8 192), the Quickstart Guide is omitted so
        that small/lightweight models still have headroom for responses.

    Returns
    -------
    str
        The assembled system prompt ready for create_chat_completion().
    """
    prompt = base + " " + AI_DOMAIN_KNOWLEDGE + " " + UI_NAV_MAP

    guide_included = bool(QUICKSTART_GUIDE) and n_ctx >= _GUIDE_MIN_CTX

    if guide_included:
        prompt += (
            "\n\n=== SanjINSIGHT Quickstart Guide ===\n"
            + QUICKSTART_GUIDE
            + "=== End of Quickstart Guide ===\n\n"
        )

    prompt += (
        _OUT_OF_SCOPE_WITH_GUIDE if guide_included else _OUT_OF_SCOPE_NO_GUIDE
    )
    return prompt


# Convenience constant for callers that don't use a persona (tests, CLI, etc.)
SYSTEM_PROMPT: str = build_system_prompt(_DEFAULT_BASE)


# ── Per-query templates ────────────────────────────────────────────────────────

def explain_tab(
    tab_name: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
    tier: int = 2,
) -> list[dict]:
    """
    Ask the model to explain the active tab and what the user should do next.

    Parameters
    ----------
    manual_context : str
        Optional User Manual snippet retrieved by manual_rag for this tab.
    tier : int
        AITier integer — controls response depth.

    Returns a messages list ready for create_chat_completion().
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    instruction = _TIER_EXPLAIN_INSTRUCTION.get(tier, _TIER_EXPLAIN_INSTRUCTION[2])
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"I am looking at the '{tab_name}' tab. "
                + instruction
                + extra
            ),
        },
    ]


def diagnose(
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
    tier: int = 2,
) -> list[dict]:
    """
    Ask the model to review current issues and suggest fixes.

    Parameters
    ----------
    manual_context : str
        Optional User Manual snippet retrieved by manual_rag for the active tab.
    tier : int
        AITier integer — controls diagnostic depth.

    Returns a messages list.
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    instruction = _TIER_DIAGNOSE_INSTRUCTION.get(tier, _TIER_DIAGNOSE_INSTRUCTION[2])
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                "Review the instrument state above. "
                + instruction
                + extra
            ),
        },
    ]


def free_ask(
    question: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
    tier: int = 2,
) -> list[dict]:
    """
    Free-form question with instrument context.

    Parameters
    ----------
    manual_context : str
        Optional snippet from the User Manual retrieved by manual_rag.retrieve().
        Injected after the question so the model can cite manual details.
    tier : int
        AITier integer — controls response depth.

    Returns a messages list.
    """
    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )
    instruction = _TIER_CHAT_INSTRUCTION.get(tier, _TIER_CHAT_INSTRUCTION[2])
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"Question: {question}\n\n{instruction}"
                + extra
            ),
        },
    ]


def session_report(
    result_data: dict,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
    manual_context: str = "",
    tier: int = 2,
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

    manual_context : str
        Optional User Manual snippet retrieved by manual_rag for acquisition
        quality topics (SNR, dark pixels, exposure, calibration).
    tier : int
        AITier integer (1=BASIC, 2=STANDARD, 3=FULL) — controls response
        complexity and length.

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

    extra = (
        f"\n\nRelevant User Manual sections:\n{manual_context}"
        if manual_context else ""
    )

    # Tier-specific task envelope
    task_instruction = _TIER_REPORT_INSTRUCTION.get(tier, _TIER_REPORT_INSTRUCTION[2])

    content = (
        f"Instrument state: {context_json}\n\n"
        f"Acquisition just completed. Pre-acquisition grade: {grade}.\n"
        f"{issue_lines}"
        f"Result metrics:\n" + "\n".join(f"  {m}" for m in metrics) + "\n\n"
        + task_instruction
        + extra
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": content},
    ]


# ── Tier-specific task envelopes ─────────────────────────────────────────────
#
# Small models need narrower, more directive asks.  Large models benefit
# from richer synthesis instructions.  These envelopes shape the task
# independently of the persona (which shapes tone).

_TIER_CHAT_INSTRUCTION: dict[int, str] = {
    1: "Answer in 1-2 sentences. Plain text only. One concrete suggestion.",
    2: "Answer in 2-4 sentences. Be specific about settings. Plain text only.",
    3: ("Answer thoroughly in 3-6 sentences. Reference specific instrument "
        "readings from the state above. Explain the reasoning. Plain text only."),
}

_TIER_DIAGNOSE_INSTRUCTION: dict[int, str] = {
    1: ("List the single most important problem and one fix. "
        "One sentence each. Plain text only."),
    2: ("List any problems you see and, for each, suggest one concrete fix. "
        "Be specific about settings or actions. If everything looks good, "
        "say so briefly."),
    3: ("Review the instrument state above thoroughly. For each problem: "
        "state the issue, explain why it matters for measurement quality, "
        "and suggest a specific fix with the exact setting to change. "
        "If everything looks good, confirm readiness briefly."),
}

_TIER_EXPLAIN_INSTRUCTION: dict[int, str] = {
    1: "In 1-2 sentences, say what this tab does and what to check.",
    2: ("In 2-3 sentences, explain what this tab does and what I should "
        "check or adjust given the current instrument state."),
    3: ("In 3-5 sentences, explain what this tab does, how it relates to "
        "the current measurement workflow, and what I should check or "
        "adjust given the current instrument state. Reference specific "
        "readings where relevant."),
}

_TIER_REPORT_INSTRUCTION: dict[int, str] = {
    1: ("In 2 sentences, assess this acquisition quality. "
        "Note the biggest issue. Plain text only."),
    2: ("In 3-4 sentences, give a quality assessment of this acquisition. "
        "Comment on SNR, dark pixel fraction, and any pre-existing issues that "
        "may have affected the result. Suggest one concrete improvement for the "
        "next acquisition if warranted. Plain text only."),
    3: ("In 4-6 sentences, give a detailed quality assessment. Comment on SNR, "
        "dark pixel fraction, frame completeness, and any pre-existing issues. "
        "Explain how each issue affects the measurement result. Suggest 1-2 "
        "concrete improvements for the next acquisition, with specific settings "
        "to change. Plain text only."),
}


def get_tier_instruction(task_type: str, tier: int) -> str:
    """Return the tier-appropriate task instruction for the given task type.

    Parameters
    ----------
    task_type : str
        One of 'chat', 'diagnose', 'explain_tab', 'session_report'.
    tier : int
        AITier integer (1=BASIC, 2=STANDARD, 3=FULL).
    """
    tables = {
        "chat":           _TIER_CHAT_INSTRUCTION,
        "diagnose":       _TIER_DIAGNOSE_INSTRUCTION,
        "explain_tab":    _TIER_EXPLAIN_INSTRUCTION,
        "session_report": _TIER_REPORT_INSTRUCTION,
    }
    table = tables.get(task_type, _TIER_CHAT_INSTRUCTION)
    return table.get(tier, table.get(2, ""))
