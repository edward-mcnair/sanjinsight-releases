"""
ai/prompt_templates.py

System prompt and per-query message templates for the SanjINSIGHT assistant.

Design goals
------------
  • Keep the system prompt short (< 200 tokens) so every context snapshot fits
    within a 2 048-token context window on small (3B) models.
  • Use unambiguous formatting — model produces plain text, not markdown.
  • Ground every response in the JSON instrument state injected at runtime.
"""

from __future__ import annotations

from ai.instrument_knowledge import AI_DOMAIN_KNOWLEDGE

SYSTEM_PROMPT = (
    "You are the SanjINSIGHT instrument assistant for thermoreflectance microscopy. "
    "Give concise, accurate guidance about instrument settings, acquisition quality, "
    "and troubleshooting. "
    "Use the JSON instrument state to ground every answer. "
    "Keep responses 2-4 sentences. Plain text only — no markdown. "
    "Say so honestly if you cannot help. Never invent hardware readings. "
    + AI_DOMAIN_KNOWLEDGE
)


# ── Per-query templates ────────────────────────────────────────────────────────

def explain_tab(
    tab_name: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """
    Ask the model to explain the active tab and what the user should do next.
    Returns a messages list ready for create_chat_completion().
    """
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"I am looking at the '{tab_name}' tab. "
                "In 2-3 sentences, explain what this tab does and what I should "
                "check or adjust given the current instrument state."
            ),
        },
    ]


def diagnose(
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """
    Ask the model to review current issues and suggest fixes.
    Returns a messages list.
    """
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                "Review the instrument state above. List any problems you see and, "
                "for each, suggest one concrete fix. Be specific about settings or "
                "actions. If everything looks good, say so briefly."
            ),
        },
    ]


def free_ask(
    question: str,
    context_json: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """
    Free-form question with instrument context.
    Returns a messages list.
    """
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"Question: {question}"
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
