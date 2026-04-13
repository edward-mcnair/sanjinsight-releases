"""
ui/guidance  —  Guidance system compatibility shims

The guided-mode guidance system has been replaced by the Recipe
execution model.  These stubs prevent import errors from existing
widgets that reference guidance cards, workflow steps, and content.

All widgets are invisible no-ops.  All content accessors return
empty/default values.
"""
from __future__ import annotations

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

from ui.guidance.prefs import (
    is_dismissed,
    dismiss,
    reset_all,
)

from ui.guidance.cards import (
    GuidanceCard,
    WorkflowFooter,
)

from ui.guidance.steps import WorkflowStep
