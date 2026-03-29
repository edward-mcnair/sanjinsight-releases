"""
acquisition.workflows.workflow_profile

Defines WorkflowProfile — a frozen configuration dataclass that tailors the
measurement pipeline for a specific use case (Failure Analysis vs Metrology).

The MeasurementOrchestrator accepts an optional WorkflowProfile to configure
preflight strictness, calibration requirements, default frame counts, and
post-processing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class WorkflowProfile:
    """Configuration profile for a measurement workflow.

    Parameters
    ----------
    name : str
        Machine-readable key (e.g. ``"failure_analysis"``).
    display_name : str
        Human-readable label shown in the UI.
    description : str
        One-liner for tooltips / help text.

    default_n_frames : int
        Pre-filled frame count when this workflow is selected.
    min_n_frames : int
        Hard floor — the UI should not allow fewer.
    recommended_n_frames : int
        Displayed as a recommendation badge.

    preflight_level : str
        ``"relaxed"`` — only critical checks, warnings allowed.
        ``"standard"`` — default set of checks.
        ``"strict"`` — all checks, tighter thresholds.
    require_calibration : bool
        If True, the orchestrator blocks capture when no valid calibration
        is loaded.
    require_tec_stable : bool
        If True, the orchestrator waits for TEC stability before capture.

    auto_quality_score : bool
        Automatically compute a quality scorecard after capture.
    auto_analysis : bool
        Automatically push results to the analysis tab.
    export_formats : list[str]
        Default export format(s) when auto-exporting.

    show_calibration_warning : bool
        Show a yellow banner when calibration is missing.
    show_uncertainty : bool
        Display measurement uncertainty estimates in the results view.
    """

    # Identity
    name: str
    display_name: str
    description: str

    # Pipeline configuration
    default_n_frames: int = 100
    min_n_frames: int = 10
    recommended_n_frames: int = 100

    # Preflight strictness
    preflight_level: str = "standard"
    require_calibration: bool = False
    require_tec_stable: bool = False

    # Post-processing
    auto_quality_score: bool = True
    auto_analysis: bool = True
    export_formats: List[str] = field(default_factory=lambda: ["tiff"])

    # UI hints
    show_calibration_warning: bool = False
    show_uncertainty: bool = False


# ── Built-in workflow profiles ──────────────────────────────────────

FAILURE_ANALYSIS = WorkflowProfile(
    name="failure_analysis",
    display_name="Failure Analysis",
    description="Rapid thermal imaging for defect localization",
    default_n_frames=50,
    min_n_frames=10,
    recommended_n_frames=50,
    preflight_level="relaxed",
    require_calibration=False,
    require_tec_stable=False,
    auto_quality_score=True,
    auto_analysis=True,
    export_formats=["tiff", "png"],
    show_calibration_warning=False,
    show_uncertainty=False,
)

METROLOGY = WorkflowProfile(
    name="metrology",
    display_name="Metrology",
    description="Precision calibrated thermal measurements",
    default_n_frames=200,
    min_n_frames=100,
    recommended_n_frames=200,
    preflight_level="strict",
    require_calibration=True,
    require_tec_stable=True,
    auto_quality_score=True,
    auto_analysis=True,
    export_formats=["hdf5", "tiff", "csv"],
    show_calibration_warning=True,
    show_uncertainty=True,
)


# ── Registry ────────────────────────────────────────────────────────

WORKFLOWS: Dict[str, WorkflowProfile] = {
    FAILURE_ANALYSIS.name: FAILURE_ANALYSIS,
    METROLOGY.name: METROLOGY,
}


def get_workflow(name: str) -> Optional[WorkflowProfile]:
    """Look up a workflow profile by name.  Returns None if not found."""
    return WORKFLOWS.get(name)
