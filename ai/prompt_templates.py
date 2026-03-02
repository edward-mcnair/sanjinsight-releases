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

SYSTEM_PROMPT = """\
You are the SanjINSIGHT instrument assistant. SanjINSIGHT is a thermoreflectance \
microscopy system used for non-contact temperature mapping of electronic devices.
Your role: give concise, accurate guidance about instrument settings, acquisition \
quality, and troubleshooting.
When given instrument state in JSON, use it to ground your answer.
Keep responses brief (2-4 sentences). Use plain text — no markdown.
If you cannot help, say so honestly. Never invent hardware readings.\
"""


# ── Per-query templates ────────────────────────────────────────────────────────

def explain_tab(tab_name: str, context_json: str) -> list[dict]:
    """
    Ask the model to explain the active tab and what the user should do next.
    Returns a messages list ready for create_chat_completion().
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
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


def diagnose(context_json: str) -> list[dict]:
    """
    Ask the model to review current issues and suggest fixes.
    Returns a messages list.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
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


def free_ask(question: str, context_json: str) -> list[dict]:
    """
    Free-form question with instrument context.
    Returns a messages list.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Instrument state: {context_json}\n\n"
                f"Question: {question}"
            ),
        },
    ]
