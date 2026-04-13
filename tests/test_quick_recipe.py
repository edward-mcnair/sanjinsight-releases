"""
tests/test_quick_recipe.py  —  Quick Recipe generator tests

Covers all three entry points: from_state, from_session, from_preset.
Tests hardware snapshot fidelity, working-copy semantics, and edge cases.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from acquisition.quick_recipe import (
    quick_recipe_from_preset,
    quick_recipe_from_session,
    quick_recipe_from_state,
    _snapshot_state,
)
from acquisition.recipe import RecipeStore
from acquisition.working_copy import Origin


# ── Helpers ────────────────────────────────────────────────────────


def _make_cam(exposure=1000, gain=6.0, n_frames=16):
    cam = MagicMock()
    cam.get_exposure.return_value = exposure
    cam.get_gain.return_value = gain
    cam.get_n_frames.return_value = n_frames
    return cam


def _make_fpga(freq=1000, duty=0.5):
    fpga = MagicMock()
    fpga.get_frequency.return_value = freq
    fpga.get_duty_cycle.return_value = duty
    return fpga


def _make_bias(voltage=3.3, mode="voltage"):
    bias = MagicMock()
    bias.mode = mode
    bias.get_level.return_value = voltage
    return bias


def _make_tec(target=25.0):
    tec = MagicMock()
    status = SimpleNamespace(target_temp=target, actual_temp=target)
    tec.get_status.return_value = status
    return tec


def _make_profile(uid="prof-1", name="Silicon IC"):
    return SimpleNamespace(uid=uid, name=name)


def _full_state(**overrides):
    """Build a fully-populated app state."""
    return SimpleNamespace(
        cam=overrides.get("cam", _make_cam()),
        fpga=overrides.get("fpga", _make_fpga()),
        bias=overrides.get("bias", _make_bias()),
        tecs=overrides.get("tecs", [_make_tec()]),
        active_profile=overrides.get("active_profile", _make_profile()),
        active_modality=overrides.get("active_modality", "thermoreflectance"),
        acquisition_type=overrides.get("acquisition_type", "single_point"),
    )


def _minimal_state():
    """Bare app state with nothing connected."""
    return SimpleNamespace()


# ── _snapshot_state ────────────────────────────────────────────────


class TestSnapshotState:
    def test_captures_camera(self):
        state = _full_state(cam=_make_cam(exposure=2000, gain=12.0))
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 2000
        assert hw["camera"]["gain_db"] == 12.0

    def test_captures_fpga(self):
        state = _full_state(fpga=_make_fpga(freq=5000, duty=0.75))
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["fpga"]["frequency_hz"] == 5000
        assert hw["fpga"]["duty_cycle"] == 0.75

    def test_captures_bias(self):
        state = _full_state(bias=_make_bias(voltage=5.0))
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["bias"]["enabled"] is True
        assert hw["bias"]["voltage_v"] == 5.0

    def test_captures_tec(self):
        state = _full_state(tecs=[_make_tec(target=30.0)])
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["tec"]["enabled"] is True
        assert hw["tec"]["setpoint_c"] == 30.0

    def test_captures_profile(self):
        profile = _make_profile(uid="abc", name="GaN Power")
        state = _full_state(active_profile=profile)
        recipe = _snapshot_state(state)
        assert recipe.profile_uid == "abc"
        assert recipe.profile_name == "GaN Power"

    def test_captures_modality(self):
        state = _full_state(active_modality="ir_lockin")
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["modality"] == "ir_lockin"

    def test_captures_acquisition_type(self):
        state = _full_state(acquisition_type="grid")
        recipe = _snapshot_state(state)
        assert recipe.acquisition_type == "grid"

    def test_has_seven_phases(self):
        state = _full_state()
        recipe = _snapshot_state(state)
        assert len(recipe.phases) == 7

    def test_requirements_inferred(self):
        state = _full_state()
        recipe = _snapshot_state(state)
        assert len(recipe.requirements) > 0

    def test_minimal_state_produces_valid_recipe(self):
        recipe = _snapshot_state(_minimal_state())
        assert recipe.label != ""
        assert len(recipe.phases) == 7

    def test_label_default(self):
        recipe = _snapshot_state(_full_state())
        assert "Quick Recipe" in recipe.label

    def test_label_override(self):
        recipe = _snapshot_state(_full_state(), label="My Custom")
        assert recipe.label == "My Custom"

    def test_no_camera_still_works(self):
        state = SimpleNamespace(fpga=_make_fpga())
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        # Defaults should be used
        assert "exposure_us" in hw["camera"]

    def test_bias_disabled_when_error(self):
        bad_bias = MagicMock()
        bad_bias.mode = "voltage"
        bad_bias.get_level.side_effect = RuntimeError("disconnected")
        state = _full_state(bias=bad_bias)
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw.get("bias", {}).get("enabled") is not True

    def test_tec_absent_when_no_tecs(self):
        state = _full_state(tecs=[])
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert "tec" not in hw

    def test_n_frames_captured(self):
        state = _full_state(cam=_make_cam(n_frames=32))
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["n_frames"] == 32

    def test_bias_current_mode(self):
        bias = _make_bias(voltage=0.5, mode="current")
        state = _full_state(bias=bias)
        recipe = _snapshot_state(state)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["bias"]["enabled"] is True
        assert hw["bias"].get("current_a") == 0.5


# ── quick_recipe_from_state ────────────────────────────────────────


class TestQuickRecipeFromState:
    def test_returns_working_copy(self):
        wc = quick_recipe_from_state(_full_state())
        assert wc is not None
        assert wc.origin == Origin.GENERATED

    def test_display_label_shows_unsaved(self):
        wc = quick_recipe_from_state(_full_state())
        assert "Unsaved" in wc.display_label

    def test_cannot_save_directly(self):
        wc = quick_recipe_from_state(_full_state())
        assert not wc.can_save

    def test_can_save_as(self):
        wc = quick_recipe_from_state(_full_state())
        assert wc.can_save_as

    def test_save_as_with_store(self, tmp_path):
        store = RecipeStore(directory=tmp_path)
        wc = quick_recipe_from_state(_full_state(), store)
        result = wc.save_as("Saved Quick Recipe")
        assert result.uid != ""
        assert result.label == "Saved Quick Recipe"
        assert wc.origin == Origin.LOADED  # rebased

    def test_custom_label(self):
        wc = quick_recipe_from_state(_full_state(), label="Custom Name")
        assert wc.recipe.label == "Custom Name"

    def test_minimal_state(self):
        wc = quick_recipe_from_state(_minimal_state())
        assert wc.recipe.label != ""
        assert len(wc.recipe.phases) == 7


# ── quick_recipe_from_session ──────────────────────────────────────


class TestQuickRecipeFromSession:
    def test_returns_working_copy(self):
        meta = SimpleNamespace(
            exposure_us=5000, gain_db=0, n_frames=16,
            fpga_frequency_hz=1000, fpga_duty_cycle=0.5,
            bias_voltage=3.3, bias_current=0,
            tec_setpoint=25.0,
            imaging_mode="thermoreflectance",
            result_type="single_point",
            profile_uid="p1", profile_name="Test",
        )
        wc = quick_recipe_from_session(meta)
        assert wc.origin == Origin.GENERATED

    def test_captures_session_params(self):
        meta = SimpleNamespace(
            exposure_us=8000, gain_db=12, n_frames=32,
            fpga_frequency_hz=2000, fpga_duty_cycle=0.6,
            bias_voltage=5.0, bias_current=0,
            tec_setpoint=30.0,
            imaging_mode="ir_lockin",
            result_type="grid",
            profile_uid="", profile_name="",
        )
        wc = quick_recipe_from_session(meta)
        hw = wc.recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 8000
        assert hw["camera"]["n_frames"] == 32
        assert wc.recipe.acquisition_type == "grid"

    def test_custom_label(self):
        meta = SimpleNamespace(
            exposure_us=5000, gain_db=0, n_frames=16,
            fpga_frequency_hz=1000, fpga_duty_cycle=0.5,
        )
        wc = quick_recipe_from_session(meta, label="Reproduce #42")
        assert wc.recipe.label == "Reproduce #42"


# ── quick_recipe_from_preset ──────────────────────────────────────


class TestQuickRecipeFromPreset:
    def test_loads_quick_scan(self):
        wc = quick_recipe_from_preset("Quick Scan")
        assert wc is not None
        assert wc.origin == Origin.GENERATED
        assert wc.recipe.label == "Quick Scan"

    def test_loads_standard_silicon(self):
        wc = quick_recipe_from_preset("Standard Silicon IC")
        assert wc is not None

    def test_unknown_preset_returns_none(self):
        wc = quick_recipe_from_preset("Nonexistent Preset")
        assert wc is None

    def test_preset_has_phases(self):
        wc = quick_recipe_from_preset("Quick Scan")
        assert len(wc.recipe.phases) == 7

    def test_preset_cannot_save(self):
        wc = quick_recipe_from_preset("Quick Scan")
        assert not wc.can_save

    def test_preset_can_save_as(self, tmp_path):
        store = RecipeStore(directory=tmp_path)
        wc = quick_recipe_from_preset("Quick Scan", store=store)
        result = wc.save_as("My Custom Scan")
        assert result.label == "My Custom Scan"
        assert wc.origin == Origin.LOADED
