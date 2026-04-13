"""
tests/test_recipe_v2.py  —  Unit tests for the v2 phase-based Recipe model.

Covers:
  - Recipe/RecipePhase/OperatorVariable/RetryPolicy construction
  - Serialization round-trip (to_dict / from_dict)
  - v1 → v2 migration
  - Factory methods (from_session, from_run_payload, from_current_state)
  - RecipeStore persistence
  - Phase access helpers
"""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from acquisition.recipe import (
    CURRENT_RECIPE_VERSION,
    HardwareRequirement,
    OperatorVariable,
    PhaseType,
    Recipe,
    RecipePhase,
    RecipeStore,
    RetryPolicy,
    _build_standard_phases,
    _migrate_v1_to_v2,
    can_run,
    format_missing_message,
    get_missing_requirements,
    infer_requirements,
    validate_requirements,
)


# ================================================================== #
#  RetryPolicy                                                        #
# ================================================================== #

class TestRetryPolicy:
    def test_defaults(self):
        rp = RetryPolicy()
        assert rp.max_retries == 0
        assert rp.backoff_s == 1.0
        assert rp.on_exhaust == "abort"

    def test_round_trip(self):
        rp = RetryPolicy(max_retries=3, backoff_s=2.5, on_exhaust="skip")
        restored = RetryPolicy.from_dict(rp.to_dict())
        assert restored.max_retries == 3
        assert restored.backoff_s == 2.5
        assert restored.on_exhaust == "skip"

    def test_unknown_keys_ignored(self):
        rp = RetryPolicy.from_dict({"max_retries": 1, "future_field": True})
        assert rp.max_retries == 1


# ================================================================== #
#  OperatorVariable                                                    #
# ================================================================== #

class TestOperatorVariable:
    def test_construction(self):
        v = OperatorVariable(
            field_path="hardware_setup.camera.exposure_us",
            display_label="Exposure",
            value_type="float",
            unit="us",
            min_value=1,
            max_value=1000000,
        )
        assert v.field_path == "hardware_setup.camera.exposure_us"
        assert v.min_value == 1

    def test_round_trip(self):
        v = OperatorVariable(
            field_path="hardware_setup.tec.setpoint_c",
            display_label="TEC Setpoint",
            value_type="float",
            unit="°C",
            default=25.0,
            min_value=10,
            max_value=80,
        )
        restored = OperatorVariable.from_dict(v.to_dict())
        assert restored.field_path == v.field_path
        assert restored.default == 25.0
        assert restored.min_value == 10

    def test_choice_type(self):
        v = OperatorVariable(
            field_path="hardware_setup.fpga.waveform",
            display_label="Waveform",
            value_type="choice",
            choices=["square", "sine"],
        )
        d = v.to_dict()
        assert d["choices"] == ["square", "sine"]


# ================================================================== #
#  RecipePhase                                                         #
# ================================================================== #

class TestRecipePhase:
    def test_defaults(self):
        p = RecipePhase(phase_type=PhaseType.PREPARATION.value)
        assert p.phase_type == "preparation"
        assert p.enabled is True
        assert p.config == {}
        assert p.timeout_s == 0

    def test_round_trip(self):
        p = RecipePhase(
            phase_type=PhaseType.HARDWARE_SETUP.value,
            config={"camera": {"exposure_us": 5000}},
            preconditions=["camera_connected"],
            validation=["exposure_set"],
            retry=RetryPolicy(max_retries=2),
            timeout_s=30,
        )
        restored = RecipePhase.from_dict(p.to_dict())
        assert restored.phase_type == "hardware_setup"
        assert restored.config["camera"]["exposure_us"] == 5000
        assert restored.preconditions == ["camera_connected"]
        assert restored.retry.max_retries == 2
        assert restored.timeout_s == 30

    def test_disabled_phase(self):
        p = RecipePhase(
            phase_type=PhaseType.STABILIZATION.value,
            enabled=False,
        )
        assert p.enabled is False
        d = p.to_dict()
        assert d["enabled"] is False


# ================================================================== #
#  Recipe                                                              #
# ================================================================== #

class TestRecipe:
    def test_defaults(self):
        r = Recipe()
        assert r.version == CURRENT_RECIPE_VERSION
        assert len(r.uid) == 8
        assert r.phases == []
        assert r.locked is False

    def test_round_trip(self):
        r = Recipe(
            label="Test Recipe",
            description="A test",
            profile_uid="abc12345",
            profile_name="Silicon 532nm",
            acquisition_type="grid",
            locked=True,
            approved_by="Admin",
            notes="test notes",
            tags=["silicon", "production"],
        )
        r.phases = _build_standard_phases(
            camera={"exposure_us": 8000, "gain_db": 3},
            tec={"enabled": True, "setpoint_c": 30},
        )
        r.variables = [
            OperatorVariable(
                field_path="hardware_setup.camera.exposure_us",
                display_label="Exposure",
                value_type="float",
                unit="us",
            ),
        ]

        d = r.to_dict()
        restored = Recipe.from_dict(d)

        assert restored.label == "Test Recipe"
        assert restored.profile_uid == "abc12345"
        assert restored.acquisition_type == "grid"
        assert restored.locked is True
        assert restored.tags == ["silicon", "production"]
        assert len(restored.phases) == 7
        assert len(restored.variables) == 1
        assert restored.variables[0].field_path == "hardware_setup.camera.exposure_us"

    def test_get_phase(self):
        r = Recipe()
        r.phases = _build_standard_phases()
        hw = r.get_phase(PhaseType.HARDWARE_SETUP.value)
        assert hw is not None
        assert hw.phase_type == "hardware_setup"
        assert "camera" in hw.config

    def test_get_phase_missing(self):
        r = Recipe()
        assert r.get_phase("nonexistent") is None

    def test_get_phase_config(self):
        r = Recipe()
        r.phases = _build_standard_phases(
            camera={"exposure_us": 9000},
        )
        cfg = r.get_phase_config(PhaseType.HARDWARE_SETUP.value)
        assert cfg["camera"]["exposure_us"] == 9000

    def test_get_phase_config_missing(self):
        r = Recipe()
        assert r.get_phase_config("nonexistent") == {}


# ================================================================== #
#  Standard phase builder                                              #
# ================================================================== #

class TestBuildStandardPhases:
    def test_creates_seven_phases(self):
        phases = _build_standard_phases()
        assert len(phases) == 7
        types = [p.phase_type for p in phases]
        assert types == [
            "preparation", "hardware_setup", "stabilization",
            "acquisition", "validation", "analysis", "output",
        ]

    def test_stabilization_disabled_without_tec_or_bias(self):
        phases = _build_standard_phases()
        stab = [p for p in phases if p.phase_type == "stabilization"][0]
        assert stab.enabled is False

    def test_stabilization_enabled_with_tec(self):
        phases = _build_standard_phases(tec={"enabled": True, "setpoint_c": 30})
        stab = [p for p in phases if p.phase_type == "stabilization"][0]
        assert stab.enabled is True
        assert "tec_settle" in stab.config

    def test_camera_params_in_hardware_setup(self):
        phases = _build_standard_phases(
            camera={"exposure_us": 12000, "gain_db": 6, "n_frames": 64},
        )
        hw = [p for p in phases if p.phase_type == "hardware_setup"][0]
        assert hw.config["camera"]["exposure_us"] == 12000
        assert hw.config["camera"]["gain_db"] == 6
        assert hw.config["camera"]["n_frames"] == 64

    def test_grid_acquisition_type(self):
        phases = _build_standard_phases(
            acquisition_type="grid",
            scan={"step_um": 50, "overlap_pct": 10},
        )
        acq = [p for p in phases if p.phase_type == "acquisition"][0]
        assert acq.config["type"] == "grid"
        assert acq.config["grid"]["step_um"] == 50

    def test_analysis_thresholds(self):
        phases = _build_standard_phases(
            analysis={"threshold_k": 2.0, "fail_peak_k": 15.0},
        )
        ana = [p for p in phases if p.phase_type == "analysis"][0]
        assert ana.config["threshold_k"] == 2.0
        assert ana.config["fail_peak_k"] == 15.0
        # defaults for unspecified
        assert ana.config["warn_hotspot_count"] == 1


# ================================================================== #
#  v1 → v2 migration                                                  #
# ================================================================== #

class TestV1Migration:
    def _v1_recipe(self) -> dict:
        """A representative v1 recipe dict."""
        return {
            "uid": "v1test01",
            "label": "Legacy Recipe",
            "description": "From v1",
            "created_at": "2025-01-01 12:00:00",
            "version": 1,
            "profile_name": "Silicon 532nm",
            "camera": {
                "exposure_us": 5000,
                "gain_db": 0,
                "n_frames": 32,
                "roi": None,
            },
            "acquisition": {
                "inter_phase_delay_s": 0.1,
                "modality": "thermoreflectance",
                "wavelength_nm": 532,
            },
            "analysis": {
                "threshold_k": 5.0,
                "fail_hotspot_count": 3,
                "fail_peak_k": 20.0,
                "fail_area_fraction": 0.05,
                "warn_hotspot_count": 1,
                "warn_peak_k": 10.0,
                "warn_area_fraction": 0.01,
            },
            "bias": {"enabled": False, "voltage_v": 0, "current_a": 0},
            "tec": {"enabled": False, "setpoint_c": 25.0},
            "notes": "test notes",
            "locked": False,
            "approved_by": "",
            "approved_at": "",
            "scan_type": "single",
            "variables": ["camera.exposure_us", "bias.voltage_v"],
        }

    def test_migration_produces_v2(self):
        v1 = self._v1_recipe()
        r = Recipe.from_dict(v1)
        assert r.version == CURRENT_RECIPE_VERSION
        assert len(r.phases) == 7
        assert r.uid == "v1test01"
        assert r.label == "Legacy Recipe"
        assert r.profile_name == "Silicon 532nm"

    def test_migration_preserves_camera(self):
        v1 = self._v1_recipe()
        r = Recipe.from_dict(v1)
        hw = r.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 5000
        assert hw["camera"]["n_frames"] == 32

    def test_migration_preserves_analysis(self):
        v1 = self._v1_recipe()
        r = Recipe.from_dict(v1)
        ana = r.get_phase_config("analysis")
        assert ana["threshold_k"] == 5.0
        assert ana["fail_peak_k"] == 20.0

    def test_migration_maps_scan_type(self):
        v1 = self._v1_recipe()
        v1["scan_type"] = "autoscan"
        r = Recipe.from_dict(v1)
        assert r.acquisition_type == "grid"

    def test_migration_converts_variables(self):
        v1 = self._v1_recipe()
        r = Recipe.from_dict(v1)
        assert len(r.variables) == 2
        paths = [v.field_path for v in r.variables]
        assert "hardware_setup.camera.exposure_us" in paths
        assert "hardware_setup.bias.voltage_v" in paths

    def test_migration_preserves_lock_state(self):
        v1 = self._v1_recipe()
        v1["locked"] = True
        v1["approved_by"] = "Engineer"
        r = Recipe.from_dict(v1)
        assert r.locked is True
        assert r.approved_by == "Engineer"

    def test_v2_skips_migration(self):
        """A v2 dict should not go through migration."""
        r = Recipe(label="Native V2")
        r.phases = _build_standard_phases()
        d = r.to_dict()
        assert d["version"] == 2
        restored = Recipe.from_dict(d)
        assert restored.label == "Native V2"
        assert len(restored.phases) == 7


# ================================================================== #
#  Factory: from_run_payload                                           #
# ================================================================== #

class TestFromRunPayload:
    def test_basic_payload(self):
        payload = {
            "recipe_label": "Post-Run",
            "scan_type": "single",
            "exposure_us": 8000,
            "gain_db": 3,
            "n_frames": 64,
            "modality": "thermoreflectance",
            "bias_enabled": True,
            "bias_voltage_v": 3.3,
            "tec_enabled": True,
            "tec_setpoint_c": 30.0,
            "threshold_k": 2.0,
            "profile_name": "GaN HEMT",
        }
        r = Recipe.from_run_payload(payload)
        assert r.label == "Post-Run"
        assert r.acquisition_type == "single_point"
        assert r.profile_name == "GaN HEMT"
        assert len(r.phases) == 7

        hw = r.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 8000
        assert hw["bias"]["voltage_v"] == 3.3
        assert hw["tec"]["setpoint_c"] == 30.0

    def test_label_override(self):
        r = Recipe.from_run_payload({}, label="My Label")
        assert r.label == "My Label"


# ================================================================== #
#  Factory: from_session                                               #
# ================================================================== #

class TestFromSession:
    def test_basic_session(self):
        class FakeMeta:
            profile_uid = "prof1234"
            profile_name = "Silicon 532nm"
            result_type = "single_point"
            exposure_us = 5000
            gain_db = 0
            n_frames = 32
            roi = None
            fpga_frequency_hz = 1000
            fpga_duty_cycle = 0.5
            bias_voltage = 3.3
            bias_current = 0.1
            tec_setpoint = 25.0
            imaging_mode = "thermoreflectance"
            quality_scorecard = None
            scan_params = None
            cube_params = None

        meta = FakeMeta()
        r = Recipe.from_session(meta, label="From Session")

        assert r.label == "From Session"
        assert r.profile_uid == "prof1234"
        assert r.acquisition_type == "single_point"
        assert len(r.phases) == 7

        hw = r.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 5000
        assert hw["bias"]["voltage_v"] == 3.3

    def test_grid_session(self):
        class GridMeta:
            profile_uid = "grid0001"
            profile_name = "FR4 PCB"
            result_type = "grid"
            exposure_us = 3000
            gain_db = 0
            n_frames = 16
            roi = None
            fpga_frequency_hz = 500
            fpga_duty_cycle = 0.5
            bias_voltage = 0
            bias_current = 0
            tec_setpoint = 0
            imaging_mode = "ir_lockin"
            quality_scorecard = None
            scan_params = {"step_um": 100, "overlap_pct": 15}
            cube_params = None

        r = Recipe.from_session(GridMeta())
        assert r.acquisition_type == "grid"
        acq = r.get_phase_config("acquisition")
        assert acq["type"] == "grid"
        assert acq["grid"]["step_um"] == 100


# ================================================================== #
#  Factory: from_current_state                                         #
# ================================================================== #

class TestFromCurrentState:
    def test_with_camera(self):
        class FakeCam:
            def get_exposure(self): return 7500
            def get_gain(self): return 6.0

        class FakeState:
            cam = FakeCam()
            fpga = None
            active_profile = None
            active_modality = "thermoreflectance"

        r = Recipe.from_current_state(FakeState(), label="Live Snap")
        assert r.label == "Live Snap"
        hw = r.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 7500
        assert hw["camera"]["gain_db"] == 6.0

    def test_with_profile(self):
        class FakeProfile:
            uid = "prf00001"
            name = "GaN"

        class FakeState:
            cam = None
            fpga = None
            active_profile = FakeProfile()
            active_modality = "thermoreflectance"

        r = Recipe.from_current_state(FakeState())
        assert r.profile_uid == "prf00001"
        assert r.profile_name == "GaN"


# ================================================================== #
#  RecipeStore                                                         #
# ================================================================== #

class TestRecipeStore:
    @pytest.fixture
    def tmp_store(self, tmp_path):
        return RecipeStore(directory=tmp_path)

    def test_save_and_list(self, tmp_store):
        r = Recipe(label="Alpha")
        r.phases = _build_standard_phases()
        tmp_store.save(r)

        recipes = tmp_store.list()
        assert len(recipes) == 1
        assert recipes[0].label == "Alpha"
        assert recipes[0].version == CURRENT_RECIPE_VERSION

    def test_save_uses_uid(self, tmp_store, tmp_path):
        r = Recipe(label="Beta")
        r.phases = _build_standard_phases()
        path = tmp_store.save(r)
        assert path == tmp_path / f"{r.uid}.json"

    def test_delete(self, tmp_store):
        r = Recipe(label="Gamma")
        tmp_store.save(r)
        assert len(tmp_store.list()) == 1
        tmp_store.delete(r)
        assert len(tmp_store.list()) == 0

    def test_delete_legacy_fallback(self, tmp_store, tmp_path):
        """v1 files are label-keyed; delete should find them."""
        r = Recipe(label="OldStyle")
        # Manually write a label-keyed file
        safe = "OldStyle"
        path = tmp_path / f"{safe}.json"
        with open(path, "w") as f:
            json.dump(r.to_dict(), f)
        assert path.exists()
        tmp_store.delete(r)
        # Should delete via UID first (won't find), then label (will find)
        # Actually, save wrote UID-keyed, so let's test the label path
        r2 = Recipe(uid="no_match", label="OldStyle")
        path2 = tmp_path / "OldStyle.json"
        with open(path2, "w") as f:
            json.dump(r2.to_dict(), f)
        tmp_store.delete(r2)
        assert not path2.exists()

    def test_load_by_uid(self, tmp_store):
        r = Recipe(label="Delta")
        r.phases = _build_standard_phases()
        tmp_store.save(r)
        loaded = tmp_store.load(r.uid)
        assert loaded is not None
        assert loaded.label == "Delta"

    def test_load_missing(self, tmp_store):
        assert tmp_store.load("nonexistent") is None

    def test_save_as_new(self, tmp_store):
        r = Recipe(label="Epsilon")
        r.phases = _build_standard_phases()
        path = tmp_store.save_as_new(r)
        assert path.name == f"{r.uid}.json"
        loaded = tmp_store.load(r.uid)
        assert loaded.label == "Epsilon"

    def test_list_sorts_by_label(self, tmp_store):
        for name in ["Zebra", "Apple", "Mango"]:
            r = Recipe(label=name)
            tmp_store.save(r)
        labels = [r.label for r in tmp_store.list()]
        assert labels == ["Apple", "Mango", "Zebra"]

    def test_v1_file_loads_as_v2(self, tmp_store, tmp_path):
        """A v1 JSON on disk should be auto-migrated on load."""
        v1 = {
            "uid": "legacy01",
            "label": "V1 Legacy",
            "version": 1,
            "camera": {"exposure_us": 3000, "gain_db": 0, "n_frames": 16},
            "acquisition": {"modality": "thermoreflectance"},
            "analysis": {"threshold_k": 5.0},
            "bias": {"enabled": False},
            "tec": {"enabled": False},
            "scan_type": "single",
            "variables": [],
        }
        path = tmp_path / "legacy01.json"
        with open(path, "w") as f:
            json.dump(v1, f)

        loaded = tmp_store.load("legacy01")
        assert loaded is not None
        assert loaded.version == CURRENT_RECIPE_VERSION
        assert len(loaded.phases) == 7
        hw = loaded.get_phase_config("hardware_setup")
        assert hw["camera"]["exposure_us"] == 3000

    def test_malformed_file_skipped(self, tmp_store, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{")
        recipes = tmp_store.list()
        assert len(recipes) == 0


# ================================================================== #
#  PhaseType enum                                                      #
# ================================================================== #

class TestPhaseType:
    def test_values(self):
        assert PhaseType.PREPARATION.value == "preparation"
        assert PhaseType.HARDWARE_SETUP.value == "hardware_setup"
        assert PhaseType.STABILIZATION.value == "stabilization"
        assert PhaseType.ACQUISITION.value == "acquisition"
        assert PhaseType.VALIDATION.value == "validation"
        assert PhaseType.ANALYSIS.value == "analysis"
        assert PhaseType.OUTPUT.value == "output"

    def test_is_str_enum(self):
        assert isinstance(PhaseType.PREPARATION, str)
        assert PhaseType.PREPARATION == "preparation"


# ================================================================== #
#  HardwareRequirement                                                 #
# ================================================================== #

class TestHardwareRequirement:
    def test_construction(self):
        req = HardwareRequirement(
            device_type="camera_tr",
            label="TR Camera",
        )
        assert req.device_type == "camera_tr"
        assert req.optional is False

    def test_optional(self):
        req = HardwareRequirement(
            device_type="ldd",
            label="Laser Diode Driver",
            optional=True,
        )
        assert req.optional is True

    def test_round_trip(self):
        req = HardwareRequirement(
            device_type="tec",
            label="TEC Controller",
            optional=False,
        )
        restored = HardwareRequirement.from_dict(req.to_dict())
        assert restored.device_type == "tec"
        assert restored.label == "TEC Controller"


# ================================================================== #
#  infer_requirements                                                  #
# ================================================================== #

class TestInferRequirements:
    def test_tr_recipe_requires_camera_and_fpga(self):
        r = Recipe()
        r.phases = _build_standard_phases(modality="thermoreflectance")
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "camera_tr" in types
        assert "fpga" in types

    def test_ir_recipe_requires_ir_camera(self):
        r = Recipe()
        r.phases = _build_standard_phases(modality="ir_lockin")
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "camera_ir" in types
        assert "fpga" in types

    def test_bias_adds_requirement(self):
        r = Recipe()
        r.phases = _build_standard_phases(
            bias={"enabled": True, "voltage_v": 3.3},
        )
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "bias" in types

    def test_tec_adds_requirement(self):
        r = Recipe()
        r.phases = _build_standard_phases(
            tec={"enabled": True, "setpoint_c": 30},
        )
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "tec" in types

    def test_grid_adds_stage_requirement(self):
        r = Recipe()
        r.phases = _build_standard_phases(
            acquisition_type="grid",
            scan={"step_um": 50},
        )
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "stage" in types

    def test_no_bias_no_tec_no_extras(self):
        r = Recipe()
        r.phases = _build_standard_phases()
        reqs = infer_requirements(r)
        types = [req.device_type for req in reqs]
        assert "bias" not in types
        assert "tec" not in types
        assert "stage" not in types

    def test_factory_auto_populates(self):
        """Factory methods should auto-populate requirements."""
        payload = {
            "bias_enabled": True,
            "tec_enabled": True,
        }
        r = Recipe.from_run_payload(payload)
        types = [req.device_type for req in r.requirements]
        assert "bias" in types
        assert "tec" in types

    def test_v1_migration_infers_requirements(self):
        """v1 recipes should get requirements inferred on load."""
        v1 = {
            "version": 1,
            "uid": "v1req01",
            "label": "V1 With Bias",
            "camera": {"exposure_us": 5000},
            "acquisition": {"modality": "thermoreflectance"},
            "analysis": {},
            "bias": {"enabled": True, "voltage_v": 5.0},
            "tec": {"enabled": True, "setpoint_c": 30},
            "scan_type": "single",
        }
        r = Recipe.from_dict(v1)
        types = [req.device_type for req in r.requirements]
        assert "camera_tr" in types
        assert "bias" in types
        assert "tec" in types


# ================================================================== #
#  validate_requirements                                               #
# ================================================================== #

class _FakeAppState:
    """Minimal ApplicationState mock for requirement validation."""
    def __init__(self, **devices):
        self.cam = devices.get("cam")
        self.ir_cam = devices.get("ir_cam")
        self.fpga = devices.get("fpga")
        self.bias = devices.get("bias")
        self.tecs = devices.get("tecs", [])
        self.stage = devices.get("stage")
        self.ldd = devices.get("ldd")
        self.gpio = devices.get("gpio")
        self.prober = devices.get("prober")
        self.turret = devices.get("turret")


class TestValidateRequirements:
    def test_all_satisfied(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="fpga", label="FPGA"),
        ]
        state = _FakeAppState(cam=object(), fpga=object())
        results = validate_requirements(r, state)
        assert all(satisfied for _, satisfied in results)

    def test_camera_missing(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
        ]
        state = _FakeAppState()  # no cam
        results = validate_requirements(r, state)
        assert results[0][1] is False

    def test_tec_checks_list(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="tec", label="TEC"),
        ]
        # Empty list = not satisfied
        state_empty = _FakeAppState(tecs=[])
        results = validate_requirements(r, state_empty)
        assert results[0][1] is False

        # Non-empty list = satisfied
        state_full = _FakeAppState(tecs=[object()])
        results = validate_requirements(r, state_full)
        assert results[0][1] is True

    def test_unknown_device_type(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="flux_capacitor", label="DeLorean"),
        ]
        state = _FakeAppState()
        results = validate_requirements(r, state)
        assert results[0][1] is False


class TestGetMissingRequirements:
    def test_returns_only_missing(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="fpga", label="FPGA"),
            HardwareRequirement(device_type="bias", label="Bias"),
        ]
        state = _FakeAppState(cam=object(), fpga=object())  # no bias
        missing = get_missing_requirements(r, state)
        assert len(missing) == 1
        assert missing[0].device_type == "bias"

    def test_excludes_optional_by_default(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="ldd", label="LDD", optional=True),
        ]
        state = _FakeAppState()  # nothing connected
        missing = get_missing_requirements(r, state)
        assert len(missing) == 1  # only mandatory
        assert missing[0].device_type == "camera_tr"

    def test_includes_optional_when_requested(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="ldd", label="LDD", optional=True),
        ]
        state = _FakeAppState()
        missing = get_missing_requirements(r, state, include_optional=True)
        assert len(missing) == 2


class TestCanRun:
    def test_can_run_all_satisfied(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
        ]
        state = _FakeAppState(cam=object())
        assert can_run(r, state) is True

    def test_cannot_run_missing(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
        ]
        state = _FakeAppState()
        assert can_run(r, state) is False

    def test_can_run_with_only_optional_missing(self):
        r = Recipe()
        r.requirements = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="ldd", label="LDD", optional=True),
        ]
        state = _FakeAppState(cam=object())
        assert can_run(r, state) is True


class TestFormatMissingMessage:
    def test_empty_returns_empty(self):
        assert format_missing_message([]) == ""

    def test_formats_missing(self):
        missing = [
            HardwareRequirement(device_type="camera_tr", label="TR Camera"),
            HardwareRequirement(device_type="tec", label="TEC Controller"),
        ]
        msg = format_missing_message(missing)
        assert "TR Camera" in msg
        assert "TEC Controller" in msg
        assert "not connected" in msg
        assert "attached and powered on" in msg

    def test_uses_device_type_as_fallback(self):
        missing = [HardwareRequirement(device_type="bilt")]
        msg = format_missing_message(missing)
        assert "bilt" in msg
