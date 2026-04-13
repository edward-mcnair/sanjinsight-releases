"""
ui/guidance/steps.py  —  Workflow step compatibility shim

The guided walkthrough has been replaced by the Recipe execution model.
This stub provides the WorkflowStep type and empty registries so
existing imports continue to work.
"""
from __future__ import annotations

from typing import NamedTuple


class WorkflowStep(NamedTuple):
    """One step in the (deprecated) guided workflow."""
    phase: int
    key: str
    label: str
    nav_target: str
    icon: str
    hint: str


WORKFLOW_STEPS: list[WorkflowStep] = []


def get_step(step_id: str) -> WorkflowStep | None:
    """Return None — no guided steps are defined."""
    return None


def next_steps_after(section: str, count: int = 3) -> list[WorkflowStep]:
    """Return an empty list — workflow footer has no steps to show."""
    return []
