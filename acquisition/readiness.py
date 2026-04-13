"""
acquisition/readiness.py  —  Recipe readiness evaluation

Evaluates what a user still needs to do before a recipe can run.
Returns a live, shrinking list of PendingAction items — each linked
to the exact sidebar section and sub-tab where it can be resolved.

Actions are categorised by severity:

  blocking    — cannot run until resolved
  review      — recommended, but not run-blocking
  info        — acknowledgeable; user should read but it won't block

The list is recipe-aware (different recipes need different actions)
and state-aware (items vanish when the underlying condition is
satisfied, not when the user merely visits a tab).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Literal, Optional

log = logging.getLogger(__name__)


# ================================================================== #
#  Severity                                                            #
# ================================================================== #

class Severity(str, Enum):
    BLOCKING = "blocking"
    REVIEW   = "review"
    INFO     = "info"


# ================================================================== #
#  Check IDs                                                           #
# ================================================================== #

class CheckID(str, Enum):
    """Unique identifiers for readiness checks.

    Each ID maps to a checker function in the registry that inspects
    live state and returns True when the condition is satisfied.
    """
    # Hardware presence (from recipe.validate_requirements)
    HARDWARE_PRESENT       = "hardware_present"

    # Camera & optics
    FOCUS_READY            = "focus_ready"
    ROI_DEFINED            = "roi_defined"
    EXPOSURE_VALID         = "exposure_valid"

    # Calibration
    CALIBRATION_VALID      = "calibration_valid"

    # Temperature
    TEC_STABLE             = "tec_stable"

    # Recipe completeness
    PROFILE_SELECTED       = "profile_selected"
    OPERATOR_VARS_REVIEWED = "operator_vars_reviewed"

    # Informational
    SAMPLE_PREP            = "sample_prep"


# ================================================================== #
#  PendingAction                                                       #
# ================================================================== #

@dataclass
class PendingAction:
    """A single item on the readiness list.

    Parameters
    ----------
    action_id : CheckID
        Unique identifier for this check.
    title : str
        Short label shown in the readiness list, e.g. "Set Focus".
    description : str
        One-line explanation, e.g. "Adjust focus on the area of interest".
    severity : Severity
        blocking / review / info.
    nav_target : str
        NavLabel constant for the sidebar destination.
    tab_hint : str, optional
        Sub-tab name within the destination, e.g. "Autofocus".
    is_resolved : bool
        True when the underlying condition is satisfied.
    dismissible : bool
        True for info-only items the user can acknowledge and dismiss.
    details : str
        Optional extra detail (e.g. "Missing: TEC Controller, Bias Source").
    """
    action_id:   str
    title:       str
    description: str
    severity:    str = Severity.BLOCKING.value
    nav_target:  str = ""
    tab_hint:    str = ""
    is_resolved: bool = False
    dismissible: bool = False
    details:     str = ""


# ================================================================== #
#  Checker registry                                                    #
# ================================================================== #

# Each checker is a callable(recipe, app_state, context) -> bool
# where context is a dict of session-level state (dismissed items, etc.)
CheckerFn = Callable[..., bool]

_CHECKER_REGISTRY: Dict[str, CheckerFn] = {}


def register_checker(check_id: str):
    """Decorator to register a readiness checker function."""
    def decorator(fn: CheckerFn) -> CheckerFn:
        _CHECKER_REGISTRY[check_id] = fn
        return fn
    return decorator


# ── Hardware presence ───────────────────────────────────────────────

@register_checker(CheckID.HARDWARE_PRESENT)
def _check_hardware(recipe, app_state, context) -> bool:
    """True if all mandatory hardware requirements are satisfied."""
    from acquisition.recipe import get_missing_requirements
    missing = get_missing_requirements(recipe, app_state)
    return len(missing) == 0


# ── Focus ───────────────────────────────────────────────────────────

@register_checker(CheckID.FOCUS_READY)
def _check_focus(recipe, app_state, context) -> bool:
    """True if autofocus has completed or manual focus is confirmed."""
    # Check if autofocus driver reports completion
    af = getattr(app_state, "af", None)
    if af is not None:
        state = getattr(af, "state", None)
        if state is not None:
            # AfState.COMPLETE (value varies by driver impl)
            state_name = getattr(state, "name", str(state))
            if state_name.upper() == "COMPLETE":
                return True

    # Check context for manual focus confirmation
    return context.get("focus_confirmed", False)


# ── ROI ─────────────────────────────────────────────────────────────

@register_checker(CheckID.ROI_DEFINED)
def _check_roi(recipe, app_state, context) -> bool:
    """True if at least one ROI is defined (or recipe uses full frame)."""
    # If the recipe doesn't specify an ROI, full frame is fine
    hw = recipe.get_phase_config("hardware_setup")
    cam_cfg = hw.get("camera", {})
    if cam_cfg.get("roi") is None and not context.get("roi_required", False):
        return True

    # Check if ROI model has active regions
    try:
        from acquisition.roi_model import roi_model
        return roi_model.count > 0 or roi_model.active_roi is not None
    except Exception:
        return False


# ── Exposure ────────────────────────────────────────────────────────

@register_checker(CheckID.EXPOSURE_VALID)
def _check_exposure(recipe, app_state, context) -> bool:
    """True if camera exposure is set and within reasonable bounds."""
    cam = getattr(app_state, "cam", None)
    if cam is None:
        return False
    try:
        exposure = cam.get_exposure()
        return exposure > 0
    except Exception:
        return False


# ── Calibration ─────────────────────────────────────────────────────

@register_checker(CheckID.CALIBRATION_VALID)
def _check_calibration(recipe, app_state, context) -> bool:
    """True if a valid C_T calibration map is active."""
    cal = getattr(app_state, "active_calibration", None)
    if cal is not None and getattr(cal, "valid", False):
        return True
    return False


# ── TEC stability ──────────────────────────────────────────────────

@register_checker(CheckID.TEC_STABLE)
def _check_tec_stable(recipe, app_state, context) -> bool:
    """True if TEC is at setpoint within tolerance."""
    hw = recipe.get_phase_config("hardware_setup")
    tec_cfg = hw.get("tec", {})
    if not tec_cfg.get("enabled"):
        return True  # not needed

    tecs = getattr(app_state, "tecs", [])
    if not tecs:
        return False  # required but not connected (caught by hardware check)
    try:
        status = tecs[0].get_status()
        target = getattr(status, "target_temp", None)
        actual = getattr(status, "actual_temp", None)
        if target is not None and actual is not None:
            return abs(actual - target) < 0.5  # 0.5°C default tolerance
    except Exception:
        pass
    return False


# ── Profile selection ──────────────────────────────────────────────

@register_checker(CheckID.PROFILE_SELECTED)
def _check_profile(recipe, app_state, context) -> bool:
    """True if the recipe's material profile is loaded."""
    if not recipe.profile_uid and not recipe.profile_name:
        return True  # recipe doesn't reference a profile
    active = getattr(app_state, "active_profile", None)
    if active is None:
        return False
    # Match by UID first, then by name
    active_uid = getattr(active, "uid", "")
    active_name = getattr(active, "name", "")
    if recipe.profile_uid and active_uid == recipe.profile_uid:
        return True
    if recipe.profile_name and active_name == recipe.profile_name:
        return True
    return False


# ── Operator variables reviewed ────────────────────────────────────

@register_checker(CheckID.OPERATOR_VARS_REVIEWED)
def _check_operator_vars(recipe, app_state, context) -> bool:
    """True if all operator variables have been reviewed (or none exist)."""
    if not recipe.variables:
        return True
    return context.get("operator_vars_reviewed", False)


# ── Sample prep (informational) ────────────────────────────────────

@register_checker(CheckID.SAMPLE_PREP)
def _check_sample_prep(recipe, app_state, context) -> bool:
    """True if user has dismissed the sample prep reminder."""
    return context.get("sample_prep_dismissed", False)


# ================================================================== #
#  Action templates                                                    #
# ================================================================== #

# Maps CheckID → PendingAction template.
# nav_target uses NavLabel string values; these must match NL.* constants
# from ui/nav_labels.py.

_ACTION_TEMPLATES: Dict[str, dict] = {
    CheckID.HARDWARE_PRESENT: {
        "title": "Connect hardware",
        "description": "Required hardware is not detected",
        "severity": Severity.BLOCKING.value,
        "nav_target": "Settings",
        "tab_hint": "Hardware",
        "dismissible": False,
    },
    CheckID.FOCUS_READY: {
        "title": "Set focus",
        "description": "Adjust focus on the sample area of interest",
        "severity": Severity.REVIEW.value,
        "nav_target": "Focus & Stage",
        "tab_hint": "Autofocus",
        "dismissible": False,
    },
    CheckID.ROI_DEFINED: {
        "title": "Define ROI",
        "description": "Select the region to analyse for this run",
        "severity": Severity.REVIEW.value,
        "nav_target": "ROI",
        "tab_hint": "",
        "dismissible": False,
    },
    CheckID.EXPOSURE_VALID: {
        "title": "Check exposure",
        "description": "Camera exposure needs to be set",
        "severity": Severity.BLOCKING.value,
        "nav_target": "Cameras",
        "tab_hint": "Exposure",
        "dismissible": False,
    },
    CheckID.CALIBRATION_VALID: {
        "title": "Load or create calibration",
        "description": "A valid C_T calibration map is needed for quantitative results",
        "severity": Severity.REVIEW.value,
        "nav_target": "Calibration",
        "tab_hint": "C_T Map",
        "dismissible": False,
    },
    CheckID.TEC_STABLE: {
        "title": "Wait for TEC",
        "description": "TEC has not reached target temperature",
        "severity": Severity.BLOCKING.value,
        "nav_target": "Thermal Control",
        "tab_hint": "",
        "dismissible": False,
    },
    CheckID.PROFILE_SELECTED: {
        "title": "Load material profile",
        "description": "The recipe references a material profile that is not active",
        "severity": Severity.BLOCKING.value,
        "nav_target": "Measurement Setup",
        "tab_hint": "",
        "dismissible": False,
    },
    CheckID.OPERATOR_VARS_REVIEWED: {
        "title": "Review operator variables",
        "description": "One or more adjustable recipe values need review",
        "severity": Severity.REVIEW.value,
        "nav_target": "Measurement Setup",
        "tab_hint": "Variables",
        "dismissible": False,
    },
    CheckID.SAMPLE_PREP: {
        "title": "Verify sample preparation",
        "description": "Confirm sample is clean, mounted, and positioned",
        "severity": Severity.INFO.value,
        "nav_target": "Live View",
        "tab_hint": "",
        "dismissible": True,
    },
}


# ================================================================== #
#  Evaluate pending actions                                            #
# ================================================================== #

def evaluate_pending_actions(
    recipe,
    app_state,
    context: Optional[Dict[str, Any]] = None,
) -> List[PendingAction]:
    """Evaluate all readiness checks for a recipe against live state.

    Parameters
    ----------
    recipe
        The Recipe to validate.
    app_state
        The ApplicationState singleton.
    context : dict, optional
        Session-level state: dismissed items, confirmed actions, etc.
        Keys used:
          - ``focus_confirmed``: bool
          - ``roi_required``: bool
          - ``operator_vars_reviewed``: bool
          - ``sample_prep_dismissed``: bool
          - ``dismissed_checks``: set of CheckID strings

    Returns
    -------
    list of PendingAction
        Unresolved items, ordered by severity (blocking first).
        Resolved items are excluded unless they are informational
        and not yet dismissed.
    """
    if context is None:
        context = {}
    dismissed = set(context.get("dismissed_checks", set()))

    # Determine which checks apply to this recipe
    checks_to_run = _determine_applicable_checks(recipe)

    actions: List[PendingAction] = []
    for check_id in checks_to_run:
        # Skip dismissed informational items
        if check_id in dismissed:
            continue

        # Run the checker
        checker = _CHECKER_REGISTRY.get(check_id)
        if checker is None:
            log.warning("No checker registered for %s", check_id)
            continue

        is_resolved = False
        try:
            is_resolved = checker(recipe, app_state, context)
        except Exception as exc:
            log.debug("Checker %s raised: %s", check_id, exc)

        if is_resolved:
            continue  # condition satisfied — don't show

        # Build the PendingAction from template
        template = _ACTION_TEMPLATES.get(check_id, {})
        action = PendingAction(
            action_id=check_id,
            title=template.get("title", check_id),
            description=template.get("description", ""),
            severity=template.get("severity", Severity.BLOCKING.value),
            nav_target=template.get("nav_target", ""),
            tab_hint=template.get("tab_hint", ""),
            is_resolved=False,
            dismissible=template.get("dismissible", False),
        )

        # Add details for hardware check
        if check_id == CheckID.HARDWARE_PRESENT:
            from acquisition.recipe import get_missing_requirements
            missing = get_missing_requirements(recipe, app_state)
            if missing:
                labels = [r.label or r.device_type for r in missing]
                action.details = "Missing: " + ", ".join(labels)

        actions.append(action)

    # Sort: blocking → review → info
    _SEVERITY_ORDER = {
        Severity.BLOCKING.value: 0,
        Severity.REVIEW.value: 1,
        Severity.INFO.value: 2,
    }
    actions.sort(key=lambda a: _SEVERITY_ORDER.get(a.severity, 9))

    return actions


def _determine_applicable_checks(recipe) -> List[str]:
    """Decide which checks apply based on the recipe's configuration."""
    checks = []

    # Hardware is always checked
    checks.append(CheckID.HARDWARE_PRESENT)

    # Profile check — only if recipe references one
    if recipe.profile_uid or recipe.profile_name:
        checks.append(CheckID.PROFILE_SELECTED)

    # Exposure — always relevant if there's a camera
    checks.append(CheckID.EXPOSURE_VALID)

    # Focus — always recommended
    checks.append(CheckID.FOCUS_READY)

    # ROI — check if recipe specifies one
    hw = recipe.get_phase_config("hardware_setup")
    cam_cfg = hw.get("camera", {})
    if cam_cfg.get("roi"):
        checks.append(CheckID.ROI_DEFINED)

    # TEC — only if recipe enables it
    tec_cfg = hw.get("tec", {})
    if tec_cfg.get("enabled"):
        checks.append(CheckID.TEC_STABLE)

    # Calibration — recommended for quantitative measurements
    checks.append(CheckID.CALIBRATION_VALID)

    # Operator variables — only if recipe has them
    if recipe.variables:
        checks.append(CheckID.OPERATOR_VARS_REVIEWED)

    # Sample prep — always shown as info
    checks.append(CheckID.SAMPLE_PREP)

    return checks


# ================================================================== #
#  Convenience helpers                                                 #
# ================================================================== #

def is_ready_to_run(
    recipe,
    app_state,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """True if no blocking actions remain."""
    actions = evaluate_pending_actions(recipe, app_state, context)
    return not any(a.severity == Severity.BLOCKING.value for a in actions)


def get_blocking_actions(
    recipe,
    app_state,
    context: Optional[Dict[str, Any]] = None,
) -> List[PendingAction]:
    """Return only the blocking (run-preventing) actions."""
    actions = evaluate_pending_actions(recipe, app_state, context)
    return [a for a in actions if a.severity == Severity.BLOCKING.value]
