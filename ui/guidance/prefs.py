"""
ui/guidance/prefs.py  —  Card dismissal compatibility shim

The guidance card system has been replaced by the Recipe execution
model.  These stubs maintain the API so existing code does not crash.
"""
from __future__ import annotations


def is_dismissed(card_id: str) -> bool:
    """Always return True — all guidance cards are considered dismissed."""
    return True


def dismiss(card_id: str) -> None:
    """No-op — dismissal persistence is deprecated."""
    pass


def reset_all() -> None:
    """No-op — no guidance cards to reset."""
    pass
