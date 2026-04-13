"""
ui/guidance/content.py  —  Guidance content compatibility shim

The guided-mode content database has been replaced by the Recipe
execution model.  Help content now lives in ``ui/help.py`` directly.
This stub provides empty/default values for all previously exported
symbols.
"""
from __future__ import annotations

from ui.guidance.steps import WORKFLOW_STEPS, get_step  # noqa: F401


MODALITY_INFO: dict[str, tuple[str, str]] = {
    "tr": ("Thermoreflectance",
           "Measures relative reflectance change induced by thermal modulation."),
    "ir": ("IR Lock-in Thermography",
           "Measures thermal emission under periodic stimulus."),
}


def get_modality_info(cam_type: str) -> tuple[str, str]:
    """Return (name, description) for a camera type."""
    return MODALITY_INFO.get(cam_type, ("", ""))


SECTION_CARDS: dict[str, list[dict]] = {}

# HELP_CONTENT re-exported from ui.help would create a circular import.
# Provide an empty dict here — the authoritative content is in ui/help.py.
HELP_CONTENT: dict[str, dict] = {}


def get_help(topic_id: str) -> dict:
    """Return empty dict — help content lives in ui/help.py now."""
    return {}


def get_section_cards(section: str) -> list[dict]:
    """Return empty list — section cards are deprecated."""
    return SECTION_CARDS.get(section, [])
