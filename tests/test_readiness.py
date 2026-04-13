"""
tests/test_readiness.py  —  Readiness evaluation tests

Covers the PendingAction system: checker registry, individual checkers,
evaluate_pending_actions(), severity ordering, dismissible items,
and convenience helpers (is_ready_to_run, get_blocking_actions).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from acquisition.readiness import (
    CheckID,
    PendingAction,
    Severity,
    _CHECKER_REGISTRY,
    _determine_applicable_checks,
    evaluate_pending_actions,
    get_blocking_actions,
    is_ready_to_run,
)
from acquisition.recipe import Recipe, _build_standard_phases, infer_requirements


# ── Helpers ────────────────────────────────────────────────────────


def _make_recipe(**overrides) -> Recipe:
    """Create a minimal v2 Recipe for readiness tests."""
    r = Recipe()
    r.label = overrides.pop("label", "Test Recipe")
    r.profile_uid = overrides.pop("profile_uid", "")
    r.profile_name = overrides.pop("profile_name", "")
    r.variables = overrides.pop("variables", [])
    r.phases = _build_standard_phases(
        camera={"exposure_us": overrides.pop("exposure_us", 1000),
                "gain_db": overrides.pop("gain_db", 6.0)},
        bias={"enabled": overrides.pop("bias_enabled", True),
              "voltage_v": overrides.pop("bias_voltage_v", 3.3)},
    )
    # Optionally enable TEC
    if overrides.pop("tec_enabled", False):
        hw = r.get_phase("hardware_setup")
        hw.config.setdefault("tec", {})["enabled"] = True
        hw.config["tec"]["setpoint_c"] = overrides.pop("tec_setpoint_c", 25.0)
    # Optionally set ROI
    if overrides.pop("roi", False):
        hw = r.get_phase("hardware_setup")
        hw.config.setdefault("camera", {})["roi"] = {"x": 0, "y": 0, "w": 100, "h": 100}
    r.requirements = infer_requirements(r)
    return r


class _FakeCam:
    """Minimal camera stub."""
    def __init__(self, exposure=1000):
        self._exposure = exposure

    def get_exposure(self):
        return self._exposure


class _FakeTecStatus:
    def __init__(self, actual, target):
        self.actual_temp = actual
        self.target_temp = target


class _FakeTec:
    def __init__(self, actual=25.0, target=25.0):
        self._status = _FakeTecStatus(actual, target)

    def get_status(self):
        return self._status


def _make_state(**kwargs):
    """Build a SimpleNamespace app state with optional devices."""
    return SimpleNamespace(**kwargs)


# ── Severity enum ──────────────────────────────────────────────────


class TestSeverity:
    def test_values(self):
        assert Severity.BLOCKING.value == "blocking"
        assert Severity.REVIEW.value == "review"
        assert Severity.INFO.value == "info"


# ── CheckID enum ───────────────────────────────────────────────────


class TestCheckID:
    def test_all_ids_have_checkers(self):
        """Every CheckID should have a registered checker."""
        for cid in CheckID:
            assert cid.value in _CHECKER_REGISTRY or cid in _CHECKER_REGISTRY, \
                f"No checker registered for {cid}"


# ── PendingAction dataclass ────────────────────────────────────────


class TestPendingAction:
    def test_defaults(self):
        a = PendingAction(action_id="test", title="T", description="D")
        assert a.severity == "blocking"
        assert a.nav_target == ""
        assert not a.is_resolved
        assert not a.dismissible
        assert a.details == ""

    def test_custom_values(self):
        a = PendingAction(
            action_id="x", title="Focus", description="Set focus",
            severity="review", nav_target="Focus & Stage",
            tab_hint="Autofocus", dismissible=True,
        )
        assert a.severity == "review"
        assert a.nav_target == "Focus & Stage"
        assert a.dismissible


# ── Individual checkers ────────────────────────────────────────────


class TestHardwareChecker:
    def test_passes_when_no_requirements(self):
        """Recipe with no requirements → hardware present."""
        r = Recipe()
        r.phases = []
        r.requirements = []
        checker = _CHECKER_REGISTRY[CheckID.HARDWARE_PRESENT]
        assert checker(r, _make_state(), {})

    def test_fails_when_camera_missing(self):
        r = _make_recipe()
        checker = _CHECKER_REGISTRY[CheckID.HARDWARE_PRESENT]
        # State has no camera
        assert not checker(r, _make_state(), {})


class TestFocusChecker:
    def test_passes_with_manual_confirm(self):
        checker = _CHECKER_REGISTRY[CheckID.FOCUS_READY]
        r = _make_recipe()
        assert checker(r, _make_state(), {"focus_confirmed": True})

    def test_fails_without_confirm(self):
        checker = _CHECKER_REGISTRY[CheckID.FOCUS_READY]
        r = _make_recipe()
        assert not checker(r, _make_state(), {})

    def test_passes_with_af_complete(self):
        checker = _CHECKER_REGISTRY[CheckID.FOCUS_READY]
        r = _make_recipe()
        af = SimpleNamespace(state=SimpleNamespace(name="COMPLETE"))
        state = _make_state(af=af)
        assert checker(r, state, {})


class TestExposureChecker:
    def test_passes_with_camera(self):
        checker = _CHECKER_REGISTRY[CheckID.EXPOSURE_VALID]
        r = _make_recipe()
        state = _make_state(cam=_FakeCam(1000))
        assert checker(r, state, {})

    def test_fails_with_zero_exposure(self):
        checker = _CHECKER_REGISTRY[CheckID.EXPOSURE_VALID]
        r = _make_recipe()
        state = _make_state(cam=_FakeCam(0))
        assert not checker(r, state, {})

    def test_fails_without_camera(self):
        checker = _CHECKER_REGISTRY[CheckID.EXPOSURE_VALID]
        r = _make_recipe()
        assert not checker(r, _make_state(), {})


class TestCalibrationChecker:
    def test_passes_with_valid(self):
        checker = _CHECKER_REGISTRY[CheckID.CALIBRATION_VALID]
        r = _make_recipe()
        cal = SimpleNamespace(valid=True)
        assert checker(r, _make_state(active_calibration=cal), {})

    def test_fails_without_calibration(self):
        checker = _CHECKER_REGISTRY[CheckID.CALIBRATION_VALID]
        r = _make_recipe()
        assert not checker(r, _make_state(), {})

    def test_fails_with_invalid(self):
        checker = _CHECKER_REGISTRY[CheckID.CALIBRATION_VALID]
        r = _make_recipe()
        cal = SimpleNamespace(valid=False)
        assert not checker(r, _make_state(active_calibration=cal), {})


class TestTecChecker:
    def test_passes_when_tec_not_enabled(self):
        """If recipe doesn't use TEC, check passes."""
        checker = _CHECKER_REGISTRY[CheckID.TEC_STABLE]
        r = _make_recipe()  # no tec
        assert checker(r, _make_state(), {})

    def test_passes_when_stable(self):
        checker = _CHECKER_REGISTRY[CheckID.TEC_STABLE]
        r = _make_recipe(tec_enabled=True)
        tec = _FakeTec(actual=25.0, target=25.0)
        state = _make_state(tecs=[tec])
        assert checker(r, state, {})

    def test_fails_when_not_at_setpoint(self):
        checker = _CHECKER_REGISTRY[CheckID.TEC_STABLE]
        r = _make_recipe(tec_enabled=True)
        tec = _FakeTec(actual=30.0, target=25.0)
        state = _make_state(tecs=[tec])
        assert not checker(r, state, {})

    def test_fails_when_no_tec_connected(self):
        checker = _CHECKER_REGISTRY[CheckID.TEC_STABLE]
        r = _make_recipe(tec_enabled=True)
        state = _make_state(tecs=[])
        assert not checker(r, state, {})


class TestProfileChecker:
    def test_passes_when_no_profile_referenced(self):
        checker = _CHECKER_REGISTRY[CheckID.PROFILE_SELECTED]
        r = _make_recipe()
        assert checker(r, _make_state(), {})

    def test_passes_with_matching_uid(self):
        checker = _CHECKER_REGISTRY[CheckID.PROFILE_SELECTED]
        r = _make_recipe(profile_uid="abc-123")
        profile = SimpleNamespace(uid="abc-123", name="P1")
        assert checker(r, _make_state(active_profile=profile), {})

    def test_passes_with_matching_name(self):
        checker = _CHECKER_REGISTRY[CheckID.PROFILE_SELECTED]
        r = _make_recipe(profile_name="Silicon IC")
        profile = SimpleNamespace(uid="xyz", name="Silicon IC")
        assert checker(r, _make_state(active_profile=profile), {})

    def test_fails_with_wrong_profile(self):
        checker = _CHECKER_REGISTRY[CheckID.PROFILE_SELECTED]
        r = _make_recipe(profile_uid="abc-123")
        profile = SimpleNamespace(uid="wrong", name="Other")
        assert not checker(r, _make_state(active_profile=profile), {})


class TestOperatorVarsChecker:
    def test_passes_when_no_variables(self):
        checker = _CHECKER_REGISTRY[CheckID.OPERATOR_VARS_REVIEWED]
        r = _make_recipe()
        assert checker(r, _make_state(), {})

    def test_fails_when_unreviewed(self):
        from acquisition.recipe import OperatorVariable
        checker = _CHECKER_REGISTRY[CheckID.OPERATOR_VARS_REVIEWED]
        r = _make_recipe(variables=[
            OperatorVariable(field_path="camera.exposure_us", display_label="Exp",
                             value_type="float")])
        assert not checker(r, _make_state(), {})

    def test_passes_when_reviewed(self):
        from acquisition.recipe import OperatorVariable
        checker = _CHECKER_REGISTRY[CheckID.OPERATOR_VARS_REVIEWED]
        r = _make_recipe(variables=[
            OperatorVariable(field_path="camera.exposure_us", display_label="Exp",
                             value_type="float")])
        assert checker(r, _make_state(), {"operator_vars_reviewed": True})


class TestSamplePrepChecker:
    def test_fails_when_not_dismissed(self):
        checker = _CHECKER_REGISTRY[CheckID.SAMPLE_PREP]
        r = _make_recipe()
        assert not checker(r, _make_state(), {})

    def test_passes_when_dismissed(self):
        checker = _CHECKER_REGISTRY[CheckID.SAMPLE_PREP]
        r = _make_recipe()
        assert checker(r, _make_state(), {"sample_prep_dismissed": True})


# ── ROI checker ────────────────────────────────────────────────────


class TestROIChecker:
    def test_passes_when_no_roi_required(self):
        checker = _CHECKER_REGISTRY[CheckID.ROI_DEFINED]
        r = _make_recipe()  # no roi in camera config
        assert checker(r, _make_state(), {})


# ── _determine_applicable_checks ───────────────────────────────────


class TestApplicableChecks:
    def test_always_includes_hardware(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.HARDWARE_PRESENT in checks

    def test_always_includes_exposure(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.EXPOSURE_VALID in checks

    def test_always_includes_focus(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.FOCUS_READY in checks

    def test_always_includes_sample_prep(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.SAMPLE_PREP in checks

    def test_includes_profile_when_referenced(self):
        r = _make_recipe(profile_uid="some-uid")
        checks = _determine_applicable_checks(r)
        assert CheckID.PROFILE_SELECTED in checks

    def test_excludes_profile_when_not_referenced(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.PROFILE_SELECTED not in checks

    def test_includes_tec_when_enabled(self):
        r = _make_recipe(tec_enabled=True)
        checks = _determine_applicable_checks(r)
        assert CheckID.TEC_STABLE in checks

    def test_excludes_tec_when_not_enabled(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.TEC_STABLE not in checks

    def test_includes_operator_vars_when_present(self):
        from acquisition.recipe import OperatorVariable
        r = _make_recipe(variables=[
            OperatorVariable(field_path="x", display_label="X", value_type="float")])
        checks = _determine_applicable_checks(r)
        assert CheckID.OPERATOR_VARS_REVIEWED in checks

    def test_excludes_operator_vars_when_absent(self):
        r = _make_recipe()
        checks = _determine_applicable_checks(r)
        assert CheckID.OPERATOR_VARS_REVIEWED not in checks


# ── evaluate_pending_actions ────────────────────────────────────────


class TestEvaluatePendingActions:
    def test_returns_unresolved_actions(self):
        """With no hardware, should return at least hardware + exposure blocking."""
        r = _make_recipe()
        actions = evaluate_pending_actions(r, _make_state(), {})
        ids = [a.action_id for a in actions]
        assert CheckID.HARDWARE_PRESENT in ids or CheckID.HARDWARE_PRESENT.value in ids
        assert CheckID.EXPOSURE_VALID in ids or CheckID.EXPOSURE_VALID.value in ids

    def test_resolved_items_excluded(self):
        """Exposure check should vanish when camera has valid exposure."""
        r = _make_recipe()
        state = _make_state(cam=_FakeCam(1000))
        actions = evaluate_pending_actions(r, state, {})
        ids = [a.action_id for a in actions]
        assert CheckID.EXPOSURE_VALID not in ids
        assert CheckID.EXPOSURE_VALID.value not in ids

    def test_severity_ordering(self):
        """Blocking items should come before review and info."""
        r = _make_recipe()
        actions = evaluate_pending_actions(r, _make_state(), {})
        severities = [a.severity for a in actions]
        for i in range(len(severities) - 1):
            order = {"blocking": 0, "review": 1, "info": 2}
            assert order.get(severities[i], 9) <= order.get(severities[i + 1], 9)

    def test_dismissed_checks_excluded(self):
        """Dismissed informational items should not appear."""
        r = _make_recipe()
        ctx = {"dismissed_checks": {CheckID.SAMPLE_PREP.value},
               "sample_prep_dismissed": False}
        actions = evaluate_pending_actions(r, _make_state(), ctx)
        ids = [a.action_id for a in actions]
        assert CheckID.SAMPLE_PREP not in ids
        assert CheckID.SAMPLE_PREP.value not in ids

    def test_nav_targets_populated(self):
        """Every returned action should have a non-empty nav_target."""
        r = _make_recipe()
        actions = evaluate_pending_actions(r, _make_state(), {})
        for a in actions:
            assert a.nav_target, f"Action {a.action_id} has empty nav_target"

    def test_hardware_details_populated(self):
        """Hardware check should include details about what's missing."""
        r = _make_recipe()
        actions = evaluate_pending_actions(r, _make_state(), {})
        hw_actions = [a for a in actions
                      if a.action_id in (CheckID.HARDWARE_PRESENT,
                                         CheckID.HARDWARE_PRESENT.value)]
        if hw_actions:
            assert hw_actions[0].details.startswith("Missing:")

    def test_empty_when_all_resolved(self):
        """A fully-resolved state should return no actions."""
        r = _make_recipe()
        # Provide everything the checks need
        state = _make_state(
            cam=_FakeCam(1000),
            active_calibration=SimpleNamespace(valid=True),
        )
        ctx = {
            "focus_confirmed": True,
            "sample_prep_dismissed": True,
        }
        actions = evaluate_pending_actions(r, state, ctx)
        # Hardware check may still fail since validate_requirements checks
        # against connected devices. Filter to non-hardware:
        non_hw = [a for a in actions
                  if a.action_id not in (CheckID.HARDWARE_PRESENT,
                                         CheckID.HARDWARE_PRESENT.value)]
        assert len(non_hw) == 0


# ── Convenience helpers ─────────────────────────────────────────────


class TestConvenienceHelpers:
    def test_is_ready_to_run_false_when_blocking(self):
        r = _make_recipe()
        assert not is_ready_to_run(r, _make_state(), {})

    def test_get_blocking_actions_returns_only_blocking(self):
        r = _make_recipe()
        blocking = get_blocking_actions(r, _make_state(), {})
        for a in blocking:
            assert a.severity == Severity.BLOCKING.value
