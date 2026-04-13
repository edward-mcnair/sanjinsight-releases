"""
acquisition/quick_recipe.py  —  Quick Recipe generator

Provides a one-call path to create a ready-to-run Recipe from live
hardware state.  This is the "just measure" entry point — the user
presses a single button and the system snapshots every connected
device into a complete Recipe, wraps it in a WorkingCopy (generated
origin), and returns it.

Three entry points
------------------
    quick_recipe_from_state(app_state, store)
        → WorkingCopy with a generated Recipe from live hardware.

    quick_recipe_from_session(session_meta, store)
        → WorkingCopy that reproduces a previous measurement.

    quick_recipe_from_preset(preset_label, store)
        → WorkingCopy from a named preset.

All return a WorkingCopy with Origin.GENERATED so the user can
run immediately, then optionally Save As to keep it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from acquisition.recipe import Recipe, RecipeStore, _build_standard_phases, infer_requirements
from acquisition.working_copy import WorkingCopy, Origin, generated_working_copy

log = logging.getLogger(__name__)


# ================================================================== #
#  From live hardware state                                            #
# ================================================================== #

def quick_recipe_from_state(
    app_state: Any,
    store: Optional[RecipeStore] = None,
    *,
    label: str = "",
) -> WorkingCopy:
    """Snapshot all connected hardware into a ready-to-run Recipe.

    Reads camera, FPGA, bias, TEC, and active profile from
    ``app_state`` to build a complete seven-phase recipe.
    Unlike ``Recipe.from_current_state()``, this also captures
    bias and TEC state when those devices are connected.

    Parameters
    ----------
    app_state
        The ApplicationState singleton.
    store : RecipeStore, optional
        For Save As support.  Not required for immediate execution.
    label : str, optional
        Recipe label.  Falls back to a timestamped default.

    Returns
    -------
    WorkingCopy
        A generated working copy ready for execution or Save As.
    """
    recipe = _snapshot_state(app_state, label=label)
    return generated_working_copy(recipe, store=store)


def _snapshot_state(app_state: Any, *, label: str = "") -> Recipe:
    """Build a Recipe from live hardware.  Internal helper."""
    r = Recipe()
    r.label = label or f"Quick Recipe {time.strftime('%H:%M:%S')}"
    r.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    r.description = "Generated from current hardware state"

    # Profile reference
    prof = getattr(app_state, "active_profile", None)
    if prof:
        r.profile_uid = getattr(prof, "uid", "")
        r.profile_name = getattr(prof, "name", "")

    # Camera
    cam_cfg = {}
    cam = getattr(app_state, "cam", None)
    if cam:
        try:
            cam_cfg["exposure_us"] = cam.get_exposure()
        except Exception:
            pass
        try:
            cam_cfg["gain_db"] = cam.get_gain()
        except Exception:
            pass
        try:
            n = cam.get_n_frames()
            if n and n > 0:
                cam_cfg["n_frames"] = n
        except Exception:
            pass

    # FPGA
    fpga_cfg = {}
    fpga = getattr(app_state, "fpga", None)
    if fpga:
        try:
            fpga_cfg["frequency_hz"] = fpga.get_frequency()
        except Exception:
            pass
        try:
            fpga_cfg["duty_cycle"] = fpga.get_duty_cycle()
        except Exception:
            pass

    # Bias
    bias_cfg = {}
    bias = getattr(app_state, "bias", None)
    if bias:
        try:
            bias_cfg["enabled"] = True
            mode = getattr(bias, "mode", "voltage")
            if mode == "current":
                bias_cfg["current_a"] = bias.get_level()
            else:
                bias_cfg["voltage_v"] = bias.get_level()
        except Exception:
            bias_cfg["enabled"] = False

    # TEC
    tec_cfg = {}
    tecs = getattr(app_state, "tecs", [])
    if tecs:
        try:
            status = tecs[0].get_status()
            target = getattr(status, "target_temp", None)
            if target is not None:
                tec_cfg["enabled"] = True
                tec_cfg["setpoint_c"] = target
        except Exception:
            pass

    # Modality
    modality = getattr(app_state, "active_modality", "thermoreflectance")

    # Acquisition type
    acq_type = getattr(app_state, "acquisition_type", "single_point")
    r.acquisition_type = acq_type

    # Build phases
    r.phases = _build_standard_phases(
        camera=cam_cfg,
        fpga=fpga_cfg,
        bias=bias_cfg,
        tec=tec_cfg,
        modality=modality,
        acquisition_type=acq_type,
    )
    r.requirements = infer_requirements(r)
    return r


# ================================================================== #
#  From completed session                                              #
# ================================================================== #

def quick_recipe_from_session(
    session_meta: Any,
    store: Optional[RecipeStore] = None,
    *,
    label: str = "",
) -> WorkingCopy:
    """Reproduce a previous measurement as a ready-to-run Recipe.

    Parameters
    ----------
    session_meta
        A SessionMeta (or compatible object).
    store : RecipeStore, optional
        For Save As support.
    label : str, optional
        Override label.

    Returns
    -------
    WorkingCopy
        A generated working copy with the session's exact parameters.
    """
    recipe = Recipe.from_session(session_meta, label=label)
    return generated_working_copy(recipe, store=store)


# ================================================================== #
#  From named preset                                                   #
# ================================================================== #

def quick_recipe_from_preset(
    preset_label: str,
    store: Optional[RecipeStore] = None,
) -> Optional[WorkingCopy]:
    """Load a named preset as a ready-to-run Recipe.

    Parameters
    ----------
    preset_label : str
        The label of the preset to load (e.g. "Quick Scan").
    store : RecipeStore, optional
        For Save As support.

    Returns
    -------
    WorkingCopy or None
        A generated working copy, or None if the preset was not found.
    """
    from acquisition.recipe_presets import PRESETS
    for preset in PRESETS:
        if preset.label == preset_label:
            return generated_working_copy(preset, store=store)
    log.warning("Preset not found: %s", preset_label)
    return None
