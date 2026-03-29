"""
ui/guidance  —  Centralized guidance, help, and tutorial system

Three tiers of user guidance, all sharing the same content database:

  Tier 1 — Contextual help cards and parameter popovers  (implemented)
  Tier 2 — Spotlight overlay walkthroughs                 (interface ready)
  Tier 3 — AI-driven adaptive tutorials                   (interface ready)

Public API
----------
Content access:
    get_help(topic_id)        → dict with title/what/do/range/warning/docs
    get_step(step_id)         → WorkflowStep namedtuple
    get_section_cards(section) → list of card content dicts for a section
    get_modality_info(cam_type) → (name, description) for "tr" or "ir"
    HELP_CONTENT              → full parameter-help dictionary
    WORKFLOW_STEPS            → ordered list of all WorkflowStep tuples

Card dismissal:
    is_dismissed(card_id)     → bool
    dismiss(card_id)          → persist dismissal
    reset_all()               → un-dismiss all cards (Settings → Reset Tips)

Widgets:
    GuidanceCard              → dismissable help card with step badge
    WorkflowFooter            → "What happens next?" preview strip
    HelpButton                → compact "?" popover trigger
    HelpPopover               → floating help panel
    help_row(label, topic)    → QHBoxLayout with label + ? button
    help_label(label, topic)  → QWidget with label + ? button
"""
from __future__ import annotations

# Content
from ui.guidance.content import (
    HELP_CONTENT,
    WORKFLOW_STEPS,
    SECTION_CARDS,
    MODALITY_INFO,
    get_help,
    get_step,
    get_section_cards,
    get_modality_info,
)

# Dismissal prefs
from ui.guidance.prefs import (
    is_dismissed,
    dismiss,
    reset_all,
)

# Widgets
from ui.guidance.cards import (
    GuidanceCard,
    WorkflowFooter,
)

# Re-export step type
from ui.guidance.steps import WorkflowStep
