"""
ai/token_budget.py

Token-aware context budgeting for the SanjINSIGHT AI assistant.

Provides approximate token estimation and per-task budget allocation so
that context assembly never overflows the model's context window.

Design
------
  • Uses a ~4 chars/token heuristic (accurate ±15 % for English + JSON
    on Qwen/Llama/Phi tokenizers — good enough for budget decisions).
  • Each AI task type has a budget profile that allocates the available
    context window across: system prompt, task prompt, instrument context,
    RAG snippets, conversation history, and response headroom.
  • History trimming is token-aware: oldest messages are dropped until the
    history fits its allocated budget.
  • Debug logging exposes every budget decision for tuning.

Token estimation accuracy
-------------------------
  The 4-char heuristic is intentionally conservative (slightly over-
  estimates).  This is preferable to under-estimation because a few
  unused tokens are harmless, while overflow causes truncation or
  generation failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

# ── Token estimation ─────────────────────────────────────────────────────────

# Average characters per token for English text with technical/JSON content.
# Measured across Qwen2.5, Llama-3, Phi-3.5 tokenizers: range 3.5–4.2.
_CHARS_PER_TOKEN: float = 4.0


def estimate_tokens(text: str) -> int:
    """Approximate token count for *text* using the 4-char heuristic."""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN + 0.5))


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Approximate total tokens across a list of chat messages.

    Accounts for role labels and message framing overhead (~4 tokens each).
    """
    total = 0
    for msg in messages:
        total += 4  # role + framing overhead
        total += estimate_tokens(msg.get("content", ""))
    return total


# ── Task types ───────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    """AI task types — each gets a distinct budget profile."""
    CHAT           = "chat"
    EXPLAIN_TAB    = "explain_tab"
    DIAGNOSE       = "diagnose"
    SESSION_REPORT = "session_report"
    ADVISOR        = "advisor"


# ── Budget allocation ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenBudget:
    """Allocated token budget for one AI request.

    All values are approximate upper bounds.  The sum of all slots
    should be ≤ the model's n_ctx.
    """
    n_ctx:           int   # total context window
    system_prompt:   int   # persona + domain knowledge + guide
    task_prompt:     int   # per-query instructions + question
    instrument_ctx:  int   # live instrument state JSON
    rag_snippets:    int   # manual RAG sections
    history:         int   # conversation history turns
    response:        int   # reserved for model output
    task_type:       str   # for logging

    @property
    def available_for_history(self) -> int:
        """Tokens remaining after all other slots are filled."""
        used = (self.system_prompt + self.task_prompt +
                self.instrument_ctx + self.rag_snippets + self.response)
        return max(0, self.n_ctx - used)


# Budget profiles: fraction of n_ctx allocated to each slot.
# Fractions are tuned for typical content sizes at each tier.

@dataclass(frozen=True)
class _BudgetProfile:
    """Fractional budget allocation for one task type."""
    system_prompt:   float = 0.35   # fraction of n_ctx
    task_prompt:     float = 0.08
    instrument_ctx:  float = 0.10
    rag_snippets:    float = 0.10
    history:         float = 0.15
    response:        float = 0.22


# Per-task profiles — override defaults where a task needs more/less of a slot.
_PROFILES: dict[TaskType, _BudgetProfile] = {
    TaskType.CHAT: _BudgetProfile(
        system_prompt=0.30, task_prompt=0.06, instrument_ctx=0.08,
        rag_snippets=0.10, history=0.24, response=0.22,
    ),
    TaskType.EXPLAIN_TAB: _BudgetProfile(
        system_prompt=0.35, task_prompt=0.08, instrument_ctx=0.10,
        rag_snippets=0.12, history=0.10, response=0.25,
    ),
    TaskType.DIAGNOSE: _BudgetProfile(
        system_prompt=0.30, task_prompt=0.08, instrument_ctx=0.15,
        rag_snippets=0.12, history=0.10, response=0.25,
    ),
    TaskType.SESSION_REPORT: _BudgetProfile(
        system_prompt=0.25, task_prompt=0.15, instrument_ctx=0.10,
        rag_snippets=0.10, history=0.05, response=0.35,
    ),
    TaskType.ADVISOR: _BudgetProfile(
        system_prompt=0.25, task_prompt=0.15, instrument_ctx=0.12,
        rag_snippets=0.03, history=0.05, response=0.40,
    ),
}

# Tier-specific n_ctx overrides for cloud providers (effectively unlimited).
_TIER_N_CTX_OVERRIDE: dict[int, Optional[int]] = {
    0: None,      # NONE — no model
    1: 4_096,     # BASIC — small local
    2: 8_192,     # STANDARD — medium local
    3: 32_000,    # FULL — cap cloud context to avoid waste
}


def allocate_budget(
    task_type: TaskType,
    n_ctx: int,
    tier: int = 2,
) -> TokenBudget:
    """Allocate a token budget for the given task type and model.

    Parameters
    ----------
    task_type : TaskType
        The AI task being performed.
    n_ctx : int
        The model's context window size.
    tier : int
        AITier integer value (0=NONE, 1=BASIC, 2=STANDARD, 3=FULL).

    Returns
    -------
    TokenBudget
        Allocated budget with approximate token counts per slot.
    """
    # Cap effective n_ctx for cloud models to avoid wasting tokens on
    # huge history that doesn't improve response quality.
    cap = _TIER_N_CTX_OVERRIDE.get(tier)
    effective_ctx = min(n_ctx, cap) if cap else n_ctx

    profile = _PROFILES.get(task_type, _BudgetProfile())

    budget = TokenBudget(
        n_ctx          = effective_ctx,
        system_prompt  = int(effective_ctx * profile.system_prompt),
        task_prompt    = int(effective_ctx * profile.task_prompt),
        instrument_ctx = int(effective_ctx * profile.instrument_ctx),
        rag_snippets   = int(effective_ctx * profile.rag_snippets),
        history        = int(effective_ctx * profile.history),
        response       = int(effective_ctx * profile.response),
        task_type      = task_type.value,
    )

    log.debug(
        "TokenBudget[%s] n_ctx=%d: sys=%d task=%d ctx=%d rag=%d hist=%d resp=%d",
        task_type.value, effective_ctx,
        budget.system_prompt, budget.task_prompt, budget.instrument_ctx,
        budget.rag_snippets, budget.history, budget.response,
    )
    return budget


# ── Token-aware history trimming ─────────────────────────────────────────────

def trim_history(
    history: list[dict],
    max_tokens: int,
    max_turns: int = 20,
) -> list[dict]:
    """Trim conversation history to fit within *max_tokens*.

    Drops the oldest messages first, preserving the most recent exchanges.
    Also enforces a hard turn-count cap as a safety net.

    Parameters
    ----------
    history : list[dict]
        List of message dicts with 'role' and 'content' keys.
    max_tokens : int
        Maximum approximate tokens allowed for history.
    max_turns : int
        Hard cap on number of exchange pairs (safety net).

    Returns
    -------
    list[dict]
        Trimmed history (may be empty if budget is 0).
    """
    if not history or max_tokens <= 0:
        return []

    # Hard turn-count cap first (pairs = turns)
    max_msgs = max_turns * 2
    trimmed = history[-max_msgs:] if len(history) > max_msgs else list(history)

    # Token-aware trimming: drop oldest messages until we fit
    while trimmed and estimate_messages_tokens(trimmed) > max_tokens:
        trimmed.pop(0)

    if trimmed != history:
        dropped = len(history) - len(trimmed)
        log.debug(
            "trim_history: dropped %d messages (budget=%d tokens, kept=%d)",
            dropped, max_tokens, len(trimmed),
        )
    return trimmed


def truncate_text(text: str, max_tokens: int) -> str:
    """Truncate *text* to approximately *max_tokens* tokens.

    Cuts at a word boundary and appends ' [truncated]' if shortened.
    """
    if not text or max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text

    # Approximate character limit
    max_chars = int(max_tokens * _CHARS_PER_TOKEN)
    truncated = text[:max_chars]
    # Cut at last space for clean word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + " [truncated]"
