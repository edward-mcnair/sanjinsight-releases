"""
tests/test_phase_handlers.py  —  Phase handler tests

Covers all 7 handlers, the handler registry, ExecutionContext,
AbortError, PhaseResult, and CheckResult.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from acquisition.phase_handlers import (
    AbortError,
    AcquisitionHandler,
    AnalysisHandler,
    CheckResult,
    ExecutionContext,
    HardwareSetupHandler,
    OutputHandler,
    PhaseResult,
    PhaseStatus,
    PreparationHandler,
    StabilizationHandler,
    ValidationHandler,
    get_handler,
)


# ── Helpers ────────────────────────────────────────────────────────


def _ctx(**kwargs) -> ExecutionContext:
    """Build an ExecutionContext with defaults."""
    return ExecutionContext(**kwargs)


def _make_cam(**kwargs):
    cam = MagicMock()
    cam.set_exposure = MagicMock()
    cam.set_gain = MagicMock()
    cam.get_exposure = MagicMock(return_value=kwargs.get("exposure", 1000))
    return cam


def _make_fpga():
    fpga = MagicMock()
    fpga.get_status = MagicMock()
    fpga.set_frequency = MagicMock()
    fpga.set_duty_cycle = MagicMock()
    fpga.set_trigger_mode = MagicMock()
    return fpga


def _make_bias():
    bias = MagicMock()
    bias.set_mode = MagicMock()
    bias.set_level = MagicMock()
    bias.set_compliance = MagicMock()
    return bias


def _make_tec(actual=25.0, target=25.0):
    tec = MagicMock()
    status = SimpleNamespace(actual_temp=actual, target_temp=target)
    tec.get_status = MagicMock(return_value=status)
    tec.enable = MagicMock()
    tec.set_target = MagicMock()
    return tec


# ── Data types ─────────────────────────────────────────────────────


class TestPhaseStatus:
    def test_values(self):
        assert PhaseStatus.SUCCESS.value == "success"
        assert PhaseStatus.FAILED.value == "failed"
        assert PhaseStatus.ABORTED.value == "aborted"
        assert PhaseStatus.SKIPPED.value == "skipped"
        assert PhaseStatus.WARNING.value == "warning"


class TestCheckResult:
    def test_defaults(self):
        cr = CheckResult(check_id="test", passed=True)
        assert cr.message == ""
        assert cr.value is None


class TestPhaseResult:
    def test_defaults(self):
        pr = PhaseResult(phase_type="test")
        assert pr.status == "success"
        assert pr.checks == []
        assert pr.data == {}
        assert pr.duration_s == 0.0


# ── ExecutionContext ───────────────────────────────────────────────


class TestExecutionContext:
    def test_check_abort_noop_when_false(self):
        ctx = _ctx()
        ctx.check_abort()  # should not raise

    def test_check_abort_raises_when_true(self):
        ctx = _ctx(abort_requested=True)
        with pytest.raises(AbortError):
            ctx.check_abort()

    def test_report_calls_callback(self):
        messages = []
        ctx = _ctx(on_progress=messages.append)
        ctx.report("hello")
        assert messages == ["hello"]

    def test_report_noop_without_callback(self):
        ctx = _ctx()
        ctx.report("hello")  # should not raise

    def test_report_swallows_callback_errors(self):
        def bad_callback(msg):
            raise RuntimeError("oops")
        ctx = _ctx(on_progress=bad_callback)
        ctx.report("hello")  # should not raise


# ── Handler registry ───────────────────────────────────────────────


class TestHandlerRegistry:
    def test_all_phase_types_registered(self):
        for pt in ["preparation", "hardware_setup", "stabilization",
                    "acquisition", "validation", "analysis", "output"]:
            assert get_handler(pt) is not None, f"No handler for {pt}"

    def test_unknown_returns_none(self):
        assert get_handler("nonexistent") is None


# ── PreparationHandler ─────────────────────────────────────────────


class TestPreparationHandler:
    def test_all_pass(self):
        handler = PreparationHandler()
        state = SimpleNamespace(cam=_make_cam(), fpga=_make_fpga())
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"checks": ["camera_connected", "fpga_responsive"]}, ctx)
        assert result.status == "success"
        assert len(result.checks) == 2
        assert all(c.passed for c in result.checks)

    def test_fails_when_camera_missing(self):
        handler = PreparationHandler()
        state = SimpleNamespace()
        ctx = _ctx(app_state=state)
        result = handler.execute({"checks": ["camera_connected"]}, ctx)
        assert result.status == "failed"
        assert not result.checks[0].passed

    def test_empty_checks_succeeds(self):
        handler = PreparationHandler()
        ctx = _ctx(app_state=SimpleNamespace())
        result = handler.execute({"checks": []}, ctx)
        assert result.status == "success"

    def test_unknown_check_fails(self):
        handler = PreparationHandler()
        ctx = _ctx(app_state=SimpleNamespace())
        result = handler.execute({"checks": ["bogus_check"]}, ctx)
        assert result.status == "failed"

    def test_abort_during_checks(self):
        handler = PreparationHandler()
        ctx = _ctx(app_state=SimpleNamespace(cam=_make_cam()),
                   abort_requested=True)
        with pytest.raises(AbortError):
            handler.execute({"checks": ["camera_connected"]}, ctx)

    def test_no_app_state(self):
        handler = PreparationHandler()
        ctx = _ctx()
        result = handler.execute({"checks": ["camera_connected"]}, ctx)
        assert result.status == "failed"

    def test_tec_connected(self):
        handler = PreparationHandler()
        state = SimpleNamespace(tecs=[_make_tec()])
        ctx = _ctx(app_state=state)
        result = handler.execute({"checks": ["tec_connected"]}, ctx)
        assert result.status == "success"

    def test_bias_connected(self):
        handler = PreparationHandler()
        state = SimpleNamespace(bias=_make_bias())
        ctx = _ctx(app_state=state)
        result = handler.execute({"checks": ["bias_connected"]}, ctx)
        assert result.status == "success"

    def test_stage_homed(self):
        handler = PreparationHandler()
        stage = MagicMock()
        stage.get_status.return_value = SimpleNamespace(homed=True)
        state = SimpleNamespace(stage=stage)
        ctx = _ctx(app_state=state)
        result = handler.execute({"checks": ["stage_homed"]}, ctx)
        assert result.status == "success"

    def test_stage_not_homed(self):
        handler = PreparationHandler()
        stage = MagicMock()
        stage.get_status.return_value = SimpleNamespace(homed=False)
        state = SimpleNamespace(stage=stage)
        ctx = _ctx(app_state=state)
        result = handler.execute({"checks": ["stage_homed"]}, ctx)
        assert result.status == "failed"


# ── HardwareSetupHandler ──────────────────────────────────────────


class TestHardwareSetupHandler:
    def test_camera_setup(self):
        handler = HardwareSetupHandler()
        cam = _make_cam()
        state = SimpleNamespace(cam=cam)
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"camera": {"exposure_us": 2000, "gain_db": 12}}, ctx)
        assert result.status == "success"
        cam.set_exposure.assert_called_once_with(2000)
        cam.set_gain.assert_called_once_with(12)

    def test_camera_not_available(self):
        handler = HardwareSetupHandler()
        state = SimpleNamespace()
        ctx = _ctx(app_state=state)
        result = handler.execute({"camera": {"exposure_us": 2000}}, ctx)
        assert result.status == "warning"
        assert "Camera not available" in result.message

    def test_fpga_setup(self):
        handler = HardwareSetupHandler()
        fpga = _make_fpga()
        state = SimpleNamespace(fpga=fpga)
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"fpga": {"frequency_hz": 1000, "duty_cycle": 0.5}}, ctx)
        assert result.status == "success"
        fpga.set_frequency.assert_called_once_with(1000)
        fpga.set_duty_cycle.assert_called_once_with(0.5)

    def test_bias_setup(self):
        handler = HardwareSetupHandler()
        bias = _make_bias()
        state = SimpleNamespace(bias=bias)
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"bias": {"enabled": True, "voltage_v": 3.3}}, ctx)
        assert result.status == "success"
        bias.set_mode.assert_called_once_with("voltage")
        bias.set_level.assert_called_once_with(3.3)

    def test_tec_setup(self):
        handler = HardwareSetupHandler()
        tec = _make_tec()
        state = SimpleNamespace(tecs=[tec])
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"tec": {"enabled": True, "setpoint_c": 30.0}}, ctx)
        assert result.status == "success"
        tec.enable.assert_called_once()
        tec.set_target.assert_called_once_with(30.0)

    def test_modality_set(self):
        handler = HardwareSetupHandler()
        state = SimpleNamespace()
        ctx = _ctx(app_state=state)
        handler.execute({"modality": "ir_lockin"}, ctx)
        assert state.active_modality == "ir_lockin"

    def test_abort_between_devices(self):
        handler = HardwareSetupHandler()
        cam = _make_cam()
        state = SimpleNamespace(cam=cam, fpga=_make_fpga())
        ctx = _ctx(app_state=state, abort_requested=True)
        with pytest.raises(AbortError):
            handler.execute(
                {"camera": {"exposure_us": 2000},
                 "fpga": {"frequency_hz": 1000}}, ctx)

    def test_empty_config_succeeds(self):
        handler = HardwareSetupHandler()
        ctx = _ctx(app_state=SimpleNamespace())
        result = handler.execute({}, ctx)
        assert result.status == "success"


# ── StabilizationHandler ──────────────────────────────────────────


class TestStabilizationHandler:
    def test_empty_config_succeeds(self):
        handler = StabilizationHandler()
        ctx = _ctx(app_state=SimpleNamespace())
        result = handler.execute({}, ctx)
        assert result.status == "success"

    def test_bias_settle(self):
        handler = StabilizationHandler()
        ctx = _ctx(app_state=SimpleNamespace())
        result = handler.execute({"bias_settle": {"delay_s": 0.01}}, ctx)
        assert result.status == "success"

    def test_tec_no_tecs(self):
        handler = StabilizationHandler()
        state = SimpleNamespace(tecs=[])
        ctx = _ctx(app_state=state)
        result = handler.execute(
            {"tec_settle": {"tolerance_c": 0.1, "timeout_s": 0.1}}, ctx)
        assert result.status == "failed"
        assert "not connected" in result.message

    def test_abort_during_bias_settle(self):
        handler = StabilizationHandler()
        ctx = _ctx(app_state=SimpleNamespace(), abort_requested=True)
        with pytest.raises(AbortError):
            handler.execute({"bias_settle": {"delay_s": 10}}, ctx)


# ── ValidationHandler ──────────────────────────────────────────────


class TestValidationHandler:
    def test_no_acquisition_result(self):
        handler = ValidationHandler()
        ctx = _ctx()
        result = handler.execute({"checks": ["snr_minimum"]}, ctx)
        assert result.status == "skipped"

    def test_snr_passes(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(snr_db=20.0)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute(
            {"checks": ["snr_minimum"], "snr_minimum_db": 10}, ctx)
        assert result.status == "success"
        assert result.checks[0].passed

    def test_snr_fails(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(snr_db=5.0)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute(
            {"checks": ["snr_minimum"], "snr_minimum_db": 10}, ctx)
        assert result.status == "warning"
        assert not result.checks[0].passed

    def test_no_saturation(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(dark_pixel_fraction=0.01)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute(
            {"checks": ["no_saturation"], "saturation_threshold": 0.05}, ctx)
        assert result.status == "success"
        assert result.checks[0].passed

    def test_saturation_exceeds(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(dark_pixel_fraction=0.10)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute(
            {"checks": ["no_saturation"], "saturation_threshold": 0.05}, ctx)
        assert result.status == "warning"

    def test_frame_count_passes(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(n_frames=16, cold_captured=16, hot_captured=16)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute({"checks": ["frame_count"]}, ctx)
        assert result.status == "success"

    def test_frame_count_fails(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(n_frames=16, cold_captured=10, hot_captured=16)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute({"checks": ["frame_count"]}, ctx)
        assert result.status == "warning"

    def test_unknown_check(self):
        handler = ValidationHandler()
        acq = SimpleNamespace()
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute({"checks": ["unknown_check"]}, ctx)
        assert result.status == "warning"
        assert not result.checks[0].passed

    def test_multiple_checks(self):
        handler = ValidationHandler()
        acq = SimpleNamespace(snr_db=20.0, dark_pixel_fraction=0.01)
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute(
            {"checks": ["snr_minimum", "no_saturation"]}, ctx)
        assert result.status == "success"
        assert len(result.checks) == 2


# ── AcquisitionHandler ─────────────────────────────────────────────


class TestAcquisitionHandler:
    def test_no_camera(self):
        handler = AcquisitionHandler()
        state = SimpleNamespace()
        ctx = _ctx(app_state=state)
        result = handler.execute({"type": "single_point"}, ctx)
        assert result.status == "failed"
        assert "Camera" in result.message

    def test_unknown_type(self):
        handler = AcquisitionHandler()
        state = SimpleNamespace(cam=_make_cam())
        ctx = _ctx(app_state=state)
        result = handler.execute({"type": "bogus"}, ctx)
        assert result.status == "failed"
        assert "Unknown" in result.message

    def test_grid_not_implemented(self):
        handler = AcquisitionHandler()
        state = SimpleNamespace(cam=_make_cam(), fpga=_make_fpga())
        ctx = _ctx(app_state=state)
        result = handler.execute({"type": "grid"}, ctx)
        assert result.status == "failed"

    def test_transient_not_implemented(self):
        handler = AcquisitionHandler()
        state = SimpleNamespace(cam=_make_cam())
        ctx = _ctx(app_state=state)
        result = handler.execute({"type": "transient"}, ctx)
        assert result.status == "failed"


# ── AnalysisHandler ────────────────────────────────────────────────


class TestAnalysisHandler:
    def test_no_acquisition_result(self):
        handler = AnalysisHandler()
        ctx = _ctx()
        result = handler.execute({}, ctx)
        assert result.status == "skipped"

    def test_no_drr_data(self):
        handler = AnalysisHandler()
        acq = SimpleNamespace()  # no delta_r_over_r
        ctx = _ctx(acquisition_result=acq)
        result = handler.execute({}, ctx)
        assert result.status == "failed"
        assert "ΔR/R" in result.message


# ── OutputHandler ──────────────────────────────────────────────────


class TestOutputHandler:
    def test_auto_save_disabled(self):
        handler = OutputHandler()
        ctx = _ctx()
        result = handler.execute({"auto_save": False}, ctx)
        assert result.status == "skipped"

    def test_no_acquisition_result(self):
        handler = OutputHandler()
        ctx = _ctx()
        result = handler.execute({"auto_save": True}, ctx)
        assert result.status == "skipped"
        assert "No acquisition" in result.message
