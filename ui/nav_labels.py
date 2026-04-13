"""
ui/nav_labels.py  —  Centralised sidebar navigation label constants

Every sidebar label used in the application is defined here as a named
constant.  All navigation-coupled code (select_by_label, WORKFLOW_STEPS,
_STEP_NAV_MAP, next_steps_after, navigate_requested signals) must
reference these constants instead of hardcoding raw strings.

This eliminates the class of bugs where renaming a sidebar label
requires synchronised changes across 6+ files.

Usage
-----
::
    from ui.nav_labels import NavLabel as NL

    select_by_label(NL.CAPTURE)
    next_steps_after(NL.STIMULUS, count=3)

Aliases
-------
Legacy navigation strings that no longer match a sidebar label are
defined separately in ``LABEL_ALIASES``.  The sidebar's
``select_by_label()`` resolves aliases before matching.
"""


class NavLabel:
    """String constants for every sidebar navigation item.

    Values MUST match the label strings passed to ``NavItem()`` in
    ``main_app.py._build_ui()``.  Do not rename values without also
    updating the NI() registration.
    """

    # ── Phase 1: CONFIGURATION ───────────────────────────────────────
    MEASUREMENT_SETUP    = "Measurement Setup"
    STIMULUS             = "Stimulus"
    TIMING               = "Timing"
    TEMPERATURE          = "Temperature"
    ACQUISITION_SETTINGS = "Acquisition Settings"

    # ── Phase 2: IMAGE ACQUISITION ───────────────────────────────────
    LIVE_VIEW            = "Live View"
    ROI                  = "ROI"
    FOCUS_STAGE          = "Focus & Stage"
    SIGNAL_CHECK         = "Signal Check"
    TRANSIENT            = "Transient"
    MOVIE                = "Movie"

    # ── Phase 3: ANALYSIS ────────────────────────────────────────────
    CAPTURE              = "Capture"
    CALIBRATION          = "Calibration"
    SURFACE_3D           = "3D Surface"
    SESSIONS             = "Sessions"
    EMISSIVITY           = "Emissivity"

    # ── HARDWARE (collapsible) ───────────────────────────────────────
    CAMERAS              = "Cameras"
    STAGES               = "Stages"
    THERMAL_CONTROL      = "Thermal Control"
    STIMULUS_TIMING      = "Stimulus & Timing"
    PROBES               = "Probes"
    SENSORS              = "Sensors"

    # ── WORKFLOW ─────────────────────────────────────────────────────
    RUN_SCAN             = "Run Scan"
    EXPERIMENT_LOG       = "Experiment Log"

    # ── SYSTEM ───────────────────────────────────────────────────────
    LIBRARY              = "Library"
    SETTINGS             = "Settings"


# ── Legacy aliases (old name → current sidebar label) ────────────────
# Used by select_by_label() to support navigation strings that no
# longer match any sidebar item.

LABEL_ALIASES: dict[str, str] = {
    "Live":       NavLabel.LIVE_VIEW,
    "Stage":      NavLabel.FOCUS_STAGE,
    "Autofocus":  NavLabel.FOCUS_STAGE,
    "Analysis":   NavLabel.SESSIONS,
    "Compare":    NavLabel.SESSIONS,
    "3D Surface": NavLabel.SESSIONS,
}


def all_labels() -> set[str]:
    """Return the set of all registered sidebar label values."""
    return {
        v for k, v in vars(NavLabel).items()
        if not k.startswith("_") and isinstance(v, str)
    }


def validate_nav_targets(step_targets: list[str], sidebar_labels: set[str],
                         *, strict: bool = False) -> None:
    """Check that every workflow step nav_target exists in the sidebar.

    Parameters
    ----------
    step_targets : list[str]
        The ``nav_target`` values from ``WORKFLOW_STEPS``.
    sidebar_labels : set[str]
        The set of labels actually registered in the sidebar.
    strict : bool
        If True (dev mode), raise ``RuntimeError`` on mismatch.
        If False (production), log a warning.
    """
    import logging
    log = logging.getLogger(__name__)

    missing = set(step_targets) - sidebar_labels
    if not missing:
        return

    msg = (f"NavLabel validation: {len(missing)} workflow step nav_target(s) "
           f"not found in sidebar: {sorted(missing)}")
    if strict:
        raise RuntimeError(msg)
    log.warning(msg)
