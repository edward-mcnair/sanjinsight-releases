"""
ui/widgets/guidance_card.py  —  Backwards-compatibility shim

All guidance card and workflow footer code has moved to
``ui.guidance.cards``.  This file re-exports the public API so
existing imports continue to work.

Prefer importing from ``ui.guidance`` or ``ui.guidance.cards`` in new code.
"""
# Re-export everything from the new canonical location
from ui.guidance.cards import GuidanceCard, WorkflowFooter  # noqa: F401
from ui.guidance.prefs import (                              # noqa: F401
    is_dismissed  as is_card_dismissed,
    dismiss       as dismiss_card,
    reset_all     as reset_all_cards,
)
