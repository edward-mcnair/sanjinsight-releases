"""
tests/test_profile_bridge.py  —  MaterialProfile ↔ Recipe bridge tests

Covers: apply_profile_to_recipe, recipe_from_profile,
quick_recipe_from_profile, and the individual config extractors.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from acquisition.profile_bridge import (
    apply_profile_to_recipe,
    quick_recipe_from_profile,
    recipe_from_profile,
    _analysis_config_from_profile,
    _bias_config_from_profile,
    _camera_config_from_profile,
    _fpga_config_from_profile,
    _tec_config_from_profile,
)
from acquisition.recipe import Recipe, RecipeStore, _build_standard_phases, infer_requirements
from acquisition.working_copy import Origin


# ── Helpers ────────────────────────────────────────────────────────


def _make_profile(**overrides) -> SimpleNamespace:
    """Build a fake MaterialProfile with sensible defaults."""
    defaults = dict(
        uid="test-prof",
        name="Test Material",
        modality="tr",
        ct_value=1.5e-4,
        wavelength_nm=532,
        exposure_us=5000,
        gain_db=6.0,
        n_frames=32,
        stimulus_freq_hz=2000,
        stimulus_duty=0.5,
        bias_enabled=True,
        bias_voltage_v=3.3,
        bias_compliance_ma=100,
        tec_enabled=True,
        tec_setpoint_c=30.0,
        roi_strategy="center50",
        analysis_threshold_k=8.0,
        analysis_fail_hotspot_n=3,
        analysis_fail_peak_k=20.0,
        analysis_warn_hotspot_n=1,
        analysis_warn_peak_k=10.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_recipe() -> Recipe:
    """Build a basic recipe with standard phases."""
    r = Recipe()
    r.label = "Base Recipe"
    r.phases = _build_standard_phases(
        camera={"exposure_us": 1000, "gain_db": 0},
    )
    r.requirements = infer_requirements(r)
    return r


# ── Config extractors ──────────────────────────────────────────────


class TestCameraConfig:
    def test_basic_extraction(self):
        profile = _make_profile(exposure_us=8000, gain_db=12, n_frames=64)
        cfg = _camera_config_from_profile(profile)
        assert cfg["exposure_us"] == 8000
        assert cfg["gain_db"] == 12
        assert cfg["n_frames"] == 64

    def test_roi_strategy(self):
        profile = _make_profile(roi_strategy="center25")
        cfg = _camera_config_from_profile(profile)
        assert cfg["roi_strategy"] == "center25"

    def test_full_roi_excluded(self):
        profile = _make_profile(roi_strategy="full")
        cfg = _camera_config_from_profile(profile)
        assert "roi_strategy" not in cfg


class TestFpgaConfig:
    def test_basic_extraction(self):
        profile = _make_profile(stimulus_freq_hz=5000, stimulus_duty=0.75)
        cfg = _fpga_config_from_profile(profile)
        assert cfg["frequency_hz"] == 5000
        assert cfg["duty_cycle"] == 0.75


class TestBiasConfig:
    def test_enabled(self):
        profile = _make_profile(bias_enabled=True, bias_voltage_v=5.0)
        cfg = _bias_config_from_profile(profile)
        assert cfg["enabled"] is True
        assert cfg["voltage_v"] == 5.0

    def test_disabled(self):
        profile = _make_profile(bias_enabled=False)
        cfg = _bias_config_from_profile(profile)
        assert cfg["enabled"] is False
        assert cfg["voltage_v"] == 0


class TestTecConfig:
    def test_enabled(self):
        profile = _make_profile(tec_enabled=True, tec_setpoint_c=35.0)
        cfg = _tec_config_from_profile(profile)
        assert cfg["enabled"] is True
        assert cfg["setpoint_c"] == 35.0

    def test_disabled(self):
        profile = _make_profile(tec_enabled=False)
        cfg = _tec_config_from_profile(profile)
        assert cfg["enabled"] is False


class TestAnalysisConfig:
    def test_basic_extraction(self):
        profile = _make_profile(analysis_threshold_k=10.0)
        cfg = _analysis_config_from_profile(profile)
        assert cfg["threshold_k"] == 10.0

    def test_nonzero_thresholds_included(self):
        profile = _make_profile(
            analysis_fail_hotspot_n=5,
            analysis_fail_peak_k=25.0,
        )
        cfg = _analysis_config_from_profile(profile)
        assert cfg["fail_hotspot_count"] == 5
        assert cfg["fail_peak_k"] == 25.0

    def test_zero_thresholds_excluded(self):
        profile = _make_profile(
            analysis_fail_hotspot_n=0,
            analysis_warn_peak_k=0,
        )
        cfg = _analysis_config_from_profile(profile)
        assert "fail_hotspot_count" not in cfg
        assert "warn_peak_k" not in cfg


# ── apply_profile_to_recipe ────────────────────────────────────────


class TestApplyProfileToRecipe:
    def test_sets_profile_reference(self):
        recipe = _make_recipe()
        profile = _make_profile(uid="abc-123", name="Silicon IC")
        apply_profile_to_recipe(recipe, profile)
        assert recipe.profile_uid == "abc-123"
        assert recipe.profile_name == "Silicon IC"

    def test_updates_camera(self):
        recipe = _make_recipe()
        profile = _make_profile(exposure_us=8000, gain_db=12)
        apply_profile_to_recipe(recipe, profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 8000
        assert hw["camera"]["gain_db"] == 12

    def test_updates_fpga(self):
        recipe = _make_recipe()
        profile = _make_profile(stimulus_freq_hz=5000)
        apply_profile_to_recipe(recipe, profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["fpga"]["frequency_hz"] == 5000

    def test_enables_bias(self):
        recipe = _make_recipe()
        profile = _make_profile(bias_enabled=True, bias_voltage_v=5.0)
        apply_profile_to_recipe(recipe, profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["bias"]["enabled"] is True
        assert hw["bias"]["voltage_v"] == 5.0

    def test_disables_bias(self):
        # Start with bias enabled
        r = Recipe()
        r.phases = _build_standard_phases(
            bias={"enabled": True, "voltage_v": 3.3})
        profile = _make_profile(bias_enabled=False)
        apply_profile_to_recipe(r, profile)
        hw = r.get_phase_config("hardware_setup")
        assert hw["bias"]["enabled"] is False

    def test_enables_tec(self):
        recipe = _make_recipe()
        profile = _make_profile(tec_enabled=True, tec_setpoint_c=40.0)
        apply_profile_to_recipe(recipe, profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["tec"]["enabled"] is True
        assert hw["tec"]["setpoint_c"] == 40.0

    def test_enables_stabilization_for_tec(self):
        recipe = _make_recipe()
        profile = _make_profile(tec_enabled=True)
        apply_profile_to_recipe(recipe, profile)
        stab = recipe.get_phase("stabilization")
        assert stab.enabled is True
        assert "tec_settle" in stab.config

    def test_disables_stabilization_when_nothing_needed(self):
        recipe = _make_recipe()
        profile = _make_profile(tec_enabled=False, bias_enabled=False)
        apply_profile_to_recipe(recipe, profile)
        stab = recipe.get_phase("stabilization")
        assert stab.enabled is False

    def test_updates_analysis(self):
        recipe = _make_recipe()
        profile = _make_profile(analysis_threshold_k=15.0)
        apply_profile_to_recipe(recipe, profile)
        analysis = recipe.get_phase_config("analysis")
        assert analysis["threshold_k"] == 15.0

    def test_reinfers_requirements(self):
        recipe = _make_recipe()
        orig_reqs = len(recipe.requirements)
        profile = _make_profile(tec_enabled=True, bias_enabled=True)
        apply_profile_to_recipe(recipe, profile)
        # Should now require TEC and bias
        types = {r.device_type for r in recipe.requirements}
        assert "tec" in types
        assert "bias" in types

    def test_preserves_other_phase_configs(self):
        recipe = _make_recipe()
        # Add custom validation config
        val = recipe.get_phase("validation")
        val.config["custom_key"] = "preserved"
        profile = _make_profile()
        apply_profile_to_recipe(recipe, profile)
        assert recipe.get_phase_config("validation")["custom_key"] == "preserved"


# ── recipe_from_profile ────────────────────────────────────────────


class TestRecipeFromProfile:
    def test_creates_valid_recipe(self):
        profile = _make_profile()
        recipe = recipe_from_profile(profile)
        assert len(recipe.phases) == 7
        assert recipe.profile_uid == "test-prof"
        assert recipe.profile_name == "Test Material"

    def test_label_from_profile(self):
        profile = _make_profile(name="GaN Power")
        recipe = recipe_from_profile(profile)
        assert recipe.label == "GaN Power"

    def test_label_override(self):
        profile = _make_profile(name="GaN Power")
        recipe = recipe_from_profile(profile, label="Custom")
        assert recipe.label == "Custom"

    def test_modality_tr(self):
        profile = _make_profile(modality="tr")
        recipe = recipe_from_profile(profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["modality"] == "thermoreflectance"

    def test_modality_ir(self):
        profile = _make_profile(modality="ir")
        recipe = recipe_from_profile(profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["modality"] == "ir_lockin"

    def test_camera_from_profile(self):
        profile = _make_profile(exposure_us=10000, gain_db=18, n_frames=64)
        recipe = recipe_from_profile(profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 10000
        assert hw["camera"]["gain_db"] == 18
        assert hw["camera"]["n_frames"] == 64

    def test_bias_from_profile(self):
        profile = _make_profile(bias_enabled=True, bias_voltage_v=5.0)
        recipe = recipe_from_profile(profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["bias"]["enabled"] is True
        assert hw["bias"]["voltage_v"] == 5.0

    def test_tec_from_profile(self):
        profile = _make_profile(tec_enabled=True, tec_setpoint_c=45.0)
        recipe = recipe_from_profile(profile)
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["tec"]["enabled"] is True
        assert hw["tec"]["setpoint_c"] == 45.0

    def test_analysis_from_profile(self):
        profile = _make_profile(analysis_threshold_k=12.0)
        recipe = recipe_from_profile(profile)
        analysis = recipe.get_phase_config("analysis")
        assert analysis["threshold_k"] == 12.0

    def test_requirements_inferred(self):
        profile = _make_profile(bias_enabled=True, tec_enabled=True)
        recipe = recipe_from_profile(profile)
        types = {r.device_type for r in recipe.requirements}
        assert "camera_tr" in types
        assert "fpga" in types

    def test_has_description(self):
        profile = _make_profile(name="Silicon IC")
        recipe = recipe_from_profile(profile)
        assert "Silicon IC" in recipe.description

    def test_stabilization_enabled_for_tec(self):
        profile = _make_profile(tec_enabled=True)
        recipe = recipe_from_profile(profile)
        stab = recipe.get_phase("stabilization")
        assert stab.enabled is True

    def test_stabilization_disabled_without_tec_or_bias(self):
        profile = _make_profile(tec_enabled=False, bias_enabled=False)
        recipe = recipe_from_profile(profile)
        stab = recipe.get_phase("stabilization")
        assert stab.enabled is False


# ── quick_recipe_from_profile ──────────────────────────────────────


class TestQuickRecipeFromProfile:
    def test_returns_generated_working_copy(self):
        profile = _make_profile()
        wc = quick_recipe_from_profile(profile)
        assert wc.origin == Origin.GENERATED

    def test_display_label_unsaved(self):
        profile = _make_profile(name="GaN Power")
        wc = quick_recipe_from_profile(profile)
        assert "Unsaved" in wc.display_label

    def test_cannot_save(self):
        profile = _make_profile()
        wc = quick_recipe_from_profile(profile)
        assert not wc.can_save

    def test_can_save_as(self, tmp_path):
        store = RecipeStore(directory=tmp_path)
        profile = _make_profile(name="Test")
        wc = quick_recipe_from_profile(profile, store=store)
        result = wc.save_as("Saved From Profile")
        assert result.label == "Saved From Profile"
        assert wc.origin == Origin.LOADED

    def test_profile_reference_set(self):
        profile = _make_profile(uid="p-123", name="Silicon")
        wc = quick_recipe_from_profile(profile)
        assert wc.recipe.profile_uid == "p-123"
        assert wc.recipe.profile_name == "Silicon"

    def test_custom_label(self):
        profile = _make_profile(name="Default Name")
        wc = quick_recipe_from_profile(profile, label="Override")
        assert wc.recipe.label == "Override"


# ── Integration: real MaterialProfile ──────────────────────────────


class TestWithRealProfile:
    def test_builtin_silicon_profile(self):
        """Use an actual built-in MaterialProfile."""
        try:
            from profiles.profiles import BUILTIN_PROFILES
        except ImportError:
            pytest.skip("profiles package not available")

        si = next((p for p in BUILTIN_PROFILES if p.uid == "si_532"), None)
        if si is None:
            pytest.skip("si_532 not in BUILTIN_PROFILES")

        recipe = recipe_from_profile(si)
        assert recipe.profile_uid == "si_532"
        assert recipe.profile_name == "Silicon — 532 nm"
        assert len(recipe.phases) == 7

        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == si.exposure_us
        assert hw["fpga"]["frequency_hz"] == si.stimulus_freq_hz

    def test_apply_builtin_to_existing_recipe(self):
        try:
            from profiles.profiles import BUILTIN_PROFILES
        except ImportError:
            pytest.skip("profiles package not available")

        gaas = next((p for p in BUILTIN_PROFILES if p.uid == "gaas_532"), None)
        if gaas is None:
            pytest.skip("gaas_532 not in BUILTIN_PROFILES")

        recipe = _make_recipe()
        apply_profile_to_recipe(recipe, gaas)
        assert recipe.profile_uid == "gaas_532"
        hw = recipe.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == gaas.exposure_us
