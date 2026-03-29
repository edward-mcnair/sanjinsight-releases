"""
ui/guidance/prefs.py  —  Guidance card dismissal state

Persistent per-card dismissal tracking.  When a user clicks "Got it"
on a GuidanceCard, the card_id is stored in config prefs and the card
stays hidden across sessions.  "Reset Tips" in Settings calls
``reset_all()`` to bring everything back.
"""
from __future__ import annotations

import config as cfg_mod

# Config key prefix for dismissed cards
_PREF_PREFIX = "guidance.dismissed."

# Session-level cache for fast lookup (avoids repeated config reads)
_dismissed_cache: set[str] = set()


def is_dismissed(card_id: str) -> bool:
    """Check whether a guidance card has been dismissed."""
    if card_id in _dismissed_cache:
        return True
    val = cfg_mod.get_pref(f"{_PREF_PREFIX}{card_id}", False)
    if val:
        _dismissed_cache.add(card_id)
    return bool(val)


def dismiss(card_id: str) -> None:
    """Persist dismissal of a guidance card."""
    _dismissed_cache.add(card_id)
    cfg_mod.set_pref(f"{_PREF_PREFIX}{card_id}", True)


def reset_all() -> None:
    """Un-dismiss all guidance cards (called from Settings → Reset Tips).

    Clears the session cache and resets all ``guidance.dismissed.*`` prefs.
    """
    _dismissed_cache.clear()
    # Walk all known prefs and reset guidance.dismissed.* entries
    if hasattr(cfg_mod, "get_all_prefs"):
        all_prefs = cfg_mod.get_all_prefs()
        for key in list(all_prefs.keys()):
            if key.startswith(_PREF_PREFIX):
                cfg_mod.set_pref(key, False)
    # Also clear any card_ids we know about from the content registry
    from ui.guidance.content import SECTION_CARDS
    for section_cards in SECTION_CARDS.values():
        for card in section_cards:
            cfg_mod.set_pref(f"{_PREF_PREFIX}{card['card_id']}", False)
