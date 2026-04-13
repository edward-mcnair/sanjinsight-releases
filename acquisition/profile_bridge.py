"""
acquisition/profile_bridge.py  —  MaterialProfile ↔ Recipe bridge

Maps MaterialProfile fields into Recipe phase configurations.
A profile defines *what the material needs*; this module translates
that into *how the recipe should be configured*.

Entry points
------------
    apply_profile_to_recipe(recipe, profile)
        Update an existing recipe's phase configs from a profile.

    recipe_from_profile(profile)
        Create a brand-new Recipe fully configured from a profile.

    quick_recipe_from_profile(profile, store)
        Create a generated WorkingCopy from a profile, ready to run.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from acquisition.recipe import Recipe, RecipeStore, _build_standard_phases, infer_requirements
from acquisition.working_copy import generated_working_copy, WorkingCopy

log = logging.getLogger(__name__)


# ================================================================== #
#  Profile → phase config mapping                                      #
# ================================================================== #

def _camera_config_from_profile(profile) -> dict:
    """Extract camera phase config from a MaterialProfile."""
    cfg = {
        "exposure_us": getattr(profile, "exposure_us", 5000),
        "gain_db": getattr(profile, "gain_db", 0),
        "n_frames": getattr(profile, "n_frames", 16),
    }
    roi = getattr(profile, "roi_strategy", "")
    if roi and roi != "full":
        cfg["roi_strategy"] = roi
    return cfg


def _fpga_config_from_profile(profile) -> dict:
    """Extract FPGA/stimulus phase config from a MaterialProfile."""
    return {
        "frequency_hz": getattr(profile, "stimulus_freq_hz", 1000),
        "duty_cycle": getattr(profile, "stimulus_duty", 0.5),
    }


def _bias_config_from_profile(profile) -> dict:
    """Extract bias source phase config from a MaterialProfile."""
    enabled = getattr(profile, "bias_enabled", False)
    return {
        "enabled": enabled,
        "voltage_v": getattr(profile, "bias_voltage_v", 0) if enabled else 0,
        "compliance_ma": getattr(profile, "bias_compliance_ma", 100),
    }


def _tec_config_from_profile(profile) -> dict:
    """Extract TEC phase config from a MaterialProfile."""
    enabled = getattr(profile, "tec_enabled", False)
    return {
        "enabled": enabled,
        "setpoint_c": getattr(profile, "tec_setpoint_c", 25.0) if enabled else 25.0,
    }


def _analysis_config_from_profile(profile) -> dict:
    """Extract analysis phase config from a MaterialProfile."""
    cfg = {
        "threshold_k": getattr(profile, "analysis_threshold_k", 5.0),
    }
    # Only include non-zero thresholds (0 = use default)
    for attr, key in [
        ("analysis_fail_hotspot_n", "fail_hotspot_count"),
        ("analysis_fail_peak_k", "fail_peak_k"),
        ("analysis_warn_hotspot_n", "warn_hotspot_count"),
        ("analysis_warn_peak_k", "warn_peak_k"),
    ]:
        val = getattr(profile, attr, 0)
        if val:
            cfg[key] = val
    return cfg


# ================================================================== #
#  Apply profile to existing recipe                                    #
# ================================================================== #

def apply_profile_to_recipe(recipe: Recipe, profile) -> None:
    """Update a recipe's phase configs from a MaterialProfile.

    Overwrites camera, FPGA, bias, TEC, and analysis settings in the
    recipe's phases with values from the profile.  Also sets the
    profile reference (uid + name) on the recipe.

    Parameters
    ----------
    recipe : Recipe
        The recipe to update (mutated in place).
    profile
        A MaterialProfile (or any object with the standard fields).
    """
    # Set profile reference
    recipe.profile_uid = getattr(profile, "uid", "")
    recipe.profile_name = getattr(profile, "name", "")

    # Update hardware_setup phase
    hw_phase = recipe.get_phase("hardware_setup")
    if hw_phase is not None:
        cam_cfg = _camera_config_from_profile(profile)
        hw_phase.config.setdefault("camera", {}).update(cam_cfg)

        fpga_cfg = _fpga_config_from_profile(profile)
        hw_phase.config.setdefault("fpga", {}).update(fpga_cfg)

        bias_cfg = _bias_config_from_profile(profile)
        if bias_cfg["enabled"]:
            hw_phase.config["bias"] = bias_cfg
        elif "bias" in hw_phase.config:
            hw_phase.config["bias"]["enabled"] = False

        tec_cfg = _tec_config_from_profile(profile)
        if tec_cfg["enabled"]:
            hw_phase.config["tec"] = tec_cfg
        elif "tec" in hw_phase.config:
            hw_phase.config["tec"]["enabled"] = False

    # Update stabilization phase
    stab_phase = recipe.get_phase("stabilization")
    if stab_phase is not None:
        tec_cfg = _tec_config_from_profile(profile)
        bias_cfg = _bias_config_from_profile(profile)
        needs_stab = tec_cfg["enabled"] or bias_cfg["enabled"]
        stab_phase.enabled = needs_stab

        if tec_cfg["enabled"]:
            stab_phase.config["tec_settle"] = {
                "tolerance_c": 0.1,
                "duration_s": 10,
                "timeout_s": 120,
            }
        elif "tec_settle" in stab_phase.config:
            del stab_phase.config["tec_settle"]

        if bias_cfg["enabled"]:
            stab_phase.config["bias_settle"] = {"delay_s": 2.0}
        elif "bias_settle" in stab_phase.config:
            del stab_phase.config["bias_settle"]

    # Update analysis phase
    analysis_phase = recipe.get_phase("analysis")
    if analysis_phase is not None:
        analysis_cfg = _analysis_config_from_profile(profile)
        analysis_phase.config.update(analysis_cfg)

    # Re-infer requirements
    recipe.requirements = infer_requirements(recipe)
    log.info("Applied profile %s to recipe %s",
             getattr(profile, "name", "?"), recipe.uid)


# ================================================================== #
#  Create recipe from profile                                          #
# ================================================================== #

def recipe_from_profile(profile, *, label: str = "") -> Recipe:
    """Create a new Recipe fully configured from a MaterialProfile.

    Builds a seven-phase recipe using the profile's recommended
    settings for camera, FPGA, bias, TEC, and analysis.

    Parameters
    ----------
    profile
        A MaterialProfile.
    label : str, optional
        Override label.  Defaults to the profile name.

    Returns
    -------
    Recipe
    """
    r = Recipe()
    r.label = label or getattr(profile, "name", "Untitled")
    r.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    r.description = f"From material profile: {getattr(profile, 'name', '')}"
    r.profile_uid = getattr(profile, "uid", "")
    r.profile_name = getattr(profile, "name", "")

    # Determine modality
    modality_map = {"tr": "thermoreflectance", "ir": "ir_lockin"}
    raw_modality = getattr(profile, "modality", "tr")
    modality = modality_map.get(raw_modality, "thermoreflectance")

    r.phases = _build_standard_phases(
        camera=_camera_config_from_profile(profile),
        fpga=_fpga_config_from_profile(profile),
        bias=_bias_config_from_profile(profile),
        tec=_tec_config_from_profile(profile),
        modality=modality,
        analysis=_analysis_config_from_profile(profile),
    )
    r.requirements = infer_requirements(r)
    return r


# ================================================================== #
#  Quick recipe from profile                                           #
# ================================================================== #

def quick_recipe_from_profile(
    profile,
    store: Optional[RecipeStore] = None,
    *,
    label: str = "",
) -> WorkingCopy:
    """Create a generated WorkingCopy from a MaterialProfile.

    This is the "Apply Profile → Measure" one-click path.

    Parameters
    ----------
    profile
        A MaterialProfile.
    store : RecipeStore, optional
        For Save As support.
    label : str, optional
        Override label.

    Returns
    -------
    WorkingCopy
        Generated working copy ready for execution or Save As.
    """
    recipe = recipe_from_profile(profile, label=label)
    return generated_working_copy(recipe, store=store)
