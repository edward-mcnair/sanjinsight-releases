"""
acquisition.workflows — Measurement workflow profiles.

Provides distinct configuration profiles for Failure Analysis (rapid defect
localization) and Metrology (precision calibrated measurement) workflows.
"""

from .workflow_profile import (                       # noqa: F401
    WorkflowProfile,
    FAILURE_ANALYSIS,
    METROLOGY,
    WORKFLOWS,
    get_workflow,
)
