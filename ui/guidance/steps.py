"""
ui/guidance/steps.py  —  Workflow step definitions

The canonical definition of all guided-walkthrough steps.  Both the
GuidedBanner and section-level guidance cards pull from this registry
rather than maintaining parallel step lists.

Each step has:
  phase       int     1=Configuration, 2=Image Acquisition, 3=Analysis
  key         str     PhaseTracker check key (e.g. "camera_selected")
  label       str     Human-readable action text
  nav_target  str     Sidebar nav label to navigate to
  icon        str     MDI icon constant name (from IC)
  hint        str     Contextual tip shown when user is on this step's page

The ordered list WORKFLOW_STEPS is the single source of truth.
"""
from __future__ import annotations

from typing import NamedTuple

from ui.icons import IC


class WorkflowStep(NamedTuple):
    """One step in the guided workflow."""
    phase: int
    key: str
    label: str
    nav_target: str
    icon: str
    hint: str


# ── Master step list (ordered) ─────────────────────────────────────────
# This is the single source of truth for the guided walkthrough.
# guided_banner.py reads from here instead of maintaining its own copy.

WORKFLOW_STEPS: list[WorkflowStep] = [
    # Phase 1: CONFIGURATION
    WorkflowStep(
        1, "camera_selected", "Select your camera",
        "Measurement Setup", IC.CAMERA,
        "Choose the camera for this measurement (TR or IR)."),
    WorkflowStep(
        1, "profile_selected", "Select a material profile",
        "Measurement Setup", IC.LIBRARY,
        "Pick a profile to auto-fill stimulus, temperature, and analysis settings."),
    WorkflowStep(
        1, "stimulus_configured", "Verify stimulus settings",
        "Stimulus", IC.SETTINGS,
        "Settings were loaded from your profile — verify or adjust if needed."),
    WorkflowStep(
        1, "temperature_set", "Set the TEC temperature",
        "Temperature", IC.TEMPERATURE,
        "Set a target temperature and wait for it to stabilise."),

    # Phase 2: IMAGE ACQUISITION
    WorkflowStep(
        2, "live_viewed", "Start the live view",
        "Live View", IC.LIVE,
        "The live feed starts automatically — verify you can see the sample."),
    WorkflowStep(
        2, "focused", "Focus and auto-expose",
        "Focus & Stage", IC.AUTOFOCUS,
        "Run autofocus or manually adjust. Look for red dots on tabs that need attention."),
    WorkflowStep(
        2, "signal_checked", "Check the signal quality",
        "Signal Check", IC.CHECK,
        "Run the signal check. If it fails, adjust focus or exposure, then retry."),

    # Phase 3: ANALYSIS
    WorkflowStep(
        3, "captured", "Run an acquisition",
        "Capture", IC.PLAY,
        "Start a single-point or grid acquisition."),
    WorkflowStep(
        3, "calibrated", "Calibrate the measurement",
        "Calibration", IC.CHART_LINE,
        "Run a calibration sweep, or skip if using a saved .cal file."),
    WorkflowStep(
        3, "recipe_run", "Run a scan profile",
        "Run Scan", IC.RECIPES,
        "Select a saved scan profile and run it for consistent, repeatable measurements."),

    # Phase 4: HARDWARE AUTOMATION
    WorkflowStep(
        4, "hardware_ready", "Verify hardware readiness",
        "Cameras", IC.CONNECT,
        "Run the readiness check to ensure all hardware is configured."),
    WorkflowStep(
        4, "optimization_applied", "Apply optimization suggestions",
        "Capture", IC.SETTINGS,
        "Review and apply the auto-gain and exposure optimization tips."),

    # Phase 5: DATA & REPORTING
    WorkflowStep(
        5, "session_reviewed", "Review session results",
        "Sessions", IC.CHECK,
        "Open a session and mark it as reviewed after inspecting the data."),
    WorkflowStep(
        5, "data_exported", "Export measurement data",
        "Sessions", IC.EXPORT,
        "Export your session in one or more formats (TIFF, HDF5, CSV, etc.)."),
    WorkflowStep(
        5, "report_generated", "Generate a report",
        "Sessions", IC.EXPORT_PDF,
        "Generate a PDF or HTML report with your analysis results."),
]


def get_step(key: str) -> WorkflowStep | None:
    """Look up a step by its check key (e.g. 'camera_selected')."""
    for step in WORKFLOW_STEPS:
        if step.key == key:
            return step
    return None


def steps_for_phase(phase: int) -> list[WorkflowStep]:
    """Return all steps belonging to a phase number."""
    return [s for s in WORKFLOW_STEPS if s.phase == phase]


def next_steps_after(nav_target: str, count: int = 3) -> list[WorkflowStep]:
    """Return the next N steps (unique targets) after a given nav target.

    Used by WorkflowFooter to show "What happens next?" from any section.
    Steps whose nav_target matches the source are excluded so the footer
    only shows *different* sections.
    """
    found = False
    result: list[WorkflowStep] = []
    seen_targets: set[str] = {nav_target}  # exclude source target
    for step in WORKFLOW_STEPS:
        if found and step.nav_target not in seen_targets:
            result.append(step)
            seen_targets.add(step.nav_target)
            if len(result) >= count:
                break
        if step.nav_target == nav_target:
            found = True
    return result
