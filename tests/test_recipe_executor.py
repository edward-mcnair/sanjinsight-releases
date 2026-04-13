"""
tests/test_recipe_executor.py  —  RecipeExecutor tests

Covers: sequential phase execution, skip/disable logic, retry policy,
abort handling, timeout enforcement, overall status computation,
ExecutionResult properties, and progress reporting.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from acquisition.phase_handlers import (
    AbortError,
    ExecutionContext,
    PhaseResult,
    PhaseStatus,
    _HANDLER_REGISTRY,
)
from acquisition.recipe import Recipe, RecipePhase, RetryPolicy, _build_standard_phases
from acquisition.recipe_executor import ExecutionResult, RecipeExecutor


# ── Helpers ────────────────────────────────────────────────────────


def _make_recipe(**kw) -> Recipe:
    """Minimal recipe with standard phases."""
    r = Recipe()
    r.label = kw.pop("label", "Test")
    r.phases = _build_standard_phases(
        camera={"exposure_us": 1000, "gain_db": 6.0},
        bias={"enabled": True, "voltage_v": 3.3},
    )
    return r


def _make_simple_recipe(phase_types: list[str]) -> Recipe:
    """Recipe with only specified phase types (all with empty config)."""
    r = Recipe()
    r.label = "Simple"
    r.phases = [
        RecipePhase(phase_type=pt, enabled=True, config={})
        for pt in phase_types
    ]
    return r


class _SuccessHandler:
    """Handler that always succeeds."""
    def execute(self, config, ctx):
        return PhaseResult(phase_type="test", status="success")


class _FailHandler:
    """Handler that always fails."""
    def execute(self, config, ctx):
        return PhaseResult(phase_type="test", status="failed",
                           message="always fails")


class _CountingHandler:
    """Handler that fails N times then succeeds."""
    def __init__(self, fail_count=1):
        self._fail_count = fail_count
        self.call_count = 0

    def execute(self, config, ctx):
        self.call_count += 1
        if self.call_count <= self._fail_count:
            return PhaseResult(phase_type="test", status="failed",
                               message=f"fail #{self.call_count}")
        return PhaseResult(phase_type="test", status="success")


class _AbortingHandler:
    """Handler that raises AbortError."""
    def execute(self, config, ctx):
        raise AbortError("user cancelled")


class _SlowHandler:
    """Handler that takes configurable time."""
    def __init__(self, duration_s=0.0):
        self._duration = duration_s

    def execute(self, config, ctx):
        import time
        time.sleep(self._duration)
        return PhaseResult(phase_type="test", status="success")


class _WarningHandler:
    """Handler that returns warning status."""
    def execute(self, config, ctx):
        return PhaseResult(phase_type="test", status="warning",
                           message="minor issue")


class _ExplodingHandler:
    """Handler that raises an unexpected exception."""
    def execute(self, config, ctx):
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _restore_registry():
    """Save and restore handler registry around each test."""
    original = dict(_HANDLER_REGISTRY)
    yield
    _HANDLER_REGISTRY.clear()
    _HANDLER_REGISTRY.update(original)


def _register(phase_type, handler):
    """Register a test handler."""
    _HANDLER_REGISTRY[phase_type] = handler


# ── ExecutionResult ────────────────────────────────────────────────


class TestExecutionResult:
    def test_defaults(self):
        er = ExecutionResult()
        assert er.succeeded
        assert er.failed_phases == []
        assert er.duration_s == 0.0

    def test_succeeded_false_when_failed(self):
        er = ExecutionResult(status="failed")
        assert not er.succeeded

    def test_failed_phases(self):
        er = ExecutionResult(phase_results=[
            PhaseResult(phase_type="a", status="success"),
            PhaseResult(phase_type="b", status="failed"),
            PhaseResult(phase_type="c", status="success"),
        ])
        assert len(er.failed_phases) == 1
        assert er.failed_phases[0].phase_type == "b"


# ── Basic execution ───────────────────────────────────────────────


class TestBasicExecution:
    def test_empty_phases(self):
        r = Recipe()
        r.phases = []
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded
        assert result.message == "No enabled phases"

    def test_single_phase_success(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.phases = [RecipePhase(phase_type="test_phase", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded
        assert len(result.phase_results) == 1

    def test_multiple_phases_all_succeed(self):
        _register("phase_a", _SuccessHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={}),
            RecipePhase(phase_type="phase_b", config={}),
        ]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded
        assert len(result.phase_results) == 2

    def test_disabled_phases_skipped(self):
        _register("phase_a", _SuccessHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={}, enabled=True),
            RecipePhase(phase_type="phase_b", config={}, enabled=False),
        ]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded
        assert len(result.phase_results) == 1

    def test_unknown_phase_type_skipped(self):
        # No handler registered for "unknown_phase"
        r = Recipe()
        r.phases = [RecipePhase(phase_type="unknown_phase", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert len(result.phase_results) == 1
        assert result.phase_results[0].status == "skipped"

    def test_duration_recorded(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.phases = [RecipePhase(phase_type="test_phase", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.duration_s >= 0

    def test_recipe_uid_and_label(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.uid = "abc-123"
        r.label = "My Recipe"
        r.phases = [RecipePhase(phase_type="test_phase", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.recipe_uid == "abc-123"
        assert result.recipe_label == "My Recipe"


# ── Failure and abort ──────────────────────────────────────────────


class TestFailureAndAbort:
    def test_phase_failure_aborts_by_default(self):
        _register("phase_a", _FailHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={}),
            RecipePhase(phase_type="phase_b", config={}),
        ]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.status == "failed"
        # phase_b should not have been attempted
        types = [pr.phase_type for pr in result.phase_results]
        assert "phase_b" not in types

    def test_on_exhaust_skip(self):
        _register("phase_a", _FailHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={},
                        retry=RetryPolicy(on_exhaust="skip")),
            RecipePhase(phase_type="phase_b", config={}),
        ]
        executor = RecipeExecutor(r)
        result = executor.run()
        # Both phases should have been attempted (skip doesn't abort)
        assert len(result.phase_results) == 2

    def test_on_exhaust_warn_continue(self):
        _register("phase_a", _FailHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={},
                        retry=RetryPolicy(on_exhaust="warn_continue")),
            RecipePhase(phase_type="phase_b", config={}),
        ]
        executor = RecipeExecutor(r)
        result = executor.run()
        # Both phases should have been attempted
        assert len(result.phase_results) == 2

    def test_abort_stops_execution(self):
        _register("phase_a", _SuccessHandler())
        _register("phase_b", _SuccessHandler())
        r = Recipe()
        r.phases = [
            RecipePhase(phase_type="phase_a", config={}),
            RecipePhase(phase_type="phase_b", config={}),
        ]
        executor = RecipeExecutor(r)
        executor.abort()  # set before run
        result = executor.run()
        assert result.status == "aborted"

    def test_abort_via_handler(self):
        _register("phase_a", _AbortingHandler())
        r = Recipe()
        r.phases = [RecipePhase(phase_type="phase_a", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.status == "aborted"

    def test_unexpected_exception(self):
        _register("phase_a", _ExplodingHandler())
        r = Recipe()
        r.phases = [RecipePhase(phase_type="phase_a", config={})]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.status == "failed"
        assert len(result.phase_results) == 1


# ── Retry logic ────────────────────────────────────────────────────


class TestRetryLogic:
    def test_retry_succeeds_on_second_attempt(self):
        handler = _CountingHandler(fail_count=1)
        _register("retry_phase", handler)
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="retry_phase", config={},
            retry=RetryPolicy(max_retries=2, backoff_s=0.01),
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded or result.status == "success"
        assert handler.call_count == 2  # 1 fail + 1 success

    def test_retry_exhausted(self):
        handler = _CountingHandler(fail_count=5)
        _register("retry_phase", handler)
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="retry_phase", config={},
            retry=RetryPolicy(max_retries=2, backoff_s=0.01,
                              on_exhaust="abort"),
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.status == "failed"
        # 1 initial + 2 retries = 3 calls
        assert handler.call_count == 3

    def test_no_retry_when_max_zero(self):
        handler = _CountingHandler(fail_count=5)
        _register("retry_phase", handler)
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="retry_phase", config={},
            retry=RetryPolicy(max_retries=0),
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.status == "failed"
        assert handler.call_count == 1

    def test_retry_replaces_failed_result(self):
        handler = _CountingHandler(fail_count=1)
        _register("retry_phase", handler)
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="retry_phase", config={},
            retry=RetryPolicy(max_retries=2, backoff_s=0.01),
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        # Successful retry replaces the failure
        assert len(result.phase_results) == 1
        assert result.phase_results[0].status == "success"

    def test_abort_during_retry_backoff(self):
        handler = _CountingHandler(fail_count=5)
        _register("retry_phase", handler)
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="retry_phase", config={},
            retry=RetryPolicy(max_retries=3, backoff_s=10),
        )]
        executor = RecipeExecutor(r)
        # Abort before retries can complete
        executor._ctx.abort_requested = True
        result = executor.run()
        assert result.status == "aborted"


# ── Timeout ────────────────────────────────────────────────────────


class TestTimeout:
    def test_timeout_exceeded(self):
        _register("slow_phase", _SlowHandler(duration_s=0.15))
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="slow_phase", config={},
            timeout_s=0.05,
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.phase_results[0].status == "failed"
        assert "timeout" in result.phase_results[0].message.lower()

    def test_within_timeout(self):
        _register("fast_phase", _SlowHandler(duration_s=0.01))
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="fast_phase", config={},
            timeout_s=5.0,
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.phase_results[0].status == "success"

    def test_no_timeout_when_zero(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="test_phase", config={},
            timeout_s=0,
        )]
        executor = RecipeExecutor(r)
        result = executor.run()
        assert result.succeeded


# ── Overall status computation ─────────────────────────────────────


class TestOverallStatus:
    def test_all_success(self):
        assert RecipeExecutor._compute_overall_status([
            PhaseResult(phase_type="a", status="success"),
            PhaseResult(phase_type="b", status="success"),
        ]) == "success"

    def test_any_failed(self):
        assert RecipeExecutor._compute_overall_status([
            PhaseResult(phase_type="a", status="success"),
            PhaseResult(phase_type="b", status="failed"),
        ]) == "failed"

    def test_any_warning(self):
        assert RecipeExecutor._compute_overall_status([
            PhaseResult(phase_type="a", status="success"),
            PhaseResult(phase_type="b", status="warning"),
        ]) == "partial"

    def test_aborted(self):
        assert RecipeExecutor._compute_overall_status([
            PhaseResult(phase_type="a", status="aborted"),
        ]) == "aborted"

    def test_empty(self):
        assert RecipeExecutor._compute_overall_status([]) == "success"

    def test_failed_takes_precedence_over_warning(self):
        assert RecipeExecutor._compute_overall_status([
            PhaseResult(phase_type="a", status="warning"),
            PhaseResult(phase_type="b", status="failed"),
        ]) == "failed"


# ── Progress reporting ─────────────────────────────────────────────


class TestProgressReporting:
    def test_progress_messages_emitted(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.label = "My Recipe"
        r.phases = [RecipePhase(phase_type="test_phase", config={})]
        messages = []
        executor = RecipeExecutor(r, on_progress=messages.append)
        executor.run()
        assert any("Starting recipe" in m for m in messages)
        assert any("test_phase" in m for m in messages)
        assert any("complete" in m.lower() for m in messages)

    def test_context_accessible(self):
        _register("test_phase", _SuccessHandler())
        r = Recipe()
        r.phases = [RecipePhase(phase_type="test_phase", config={})]
        executor = RecipeExecutor(r)
        assert executor.context is executor._ctx


# ── Integration with real handlers ─────────────────────────────────


class TestRealHandlers:
    def test_preparation_with_camera(self):
        """Run the real preparation handler via the executor."""
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="preparation",
            config={"checks": ["camera_connected"]},
        )]
        cam = MagicMock()
        state = SimpleNamespace(cam=cam)
        executor = RecipeExecutor(r, app_state=state)
        result = executor.run()
        assert result.succeeded

    def test_preparation_fails_without_camera(self):
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="preparation",
            config={"checks": ["camera_connected"]},
        )]
        executor = RecipeExecutor(r, app_state=SimpleNamespace())
        result = executor.run()
        assert result.status == "failed"

    def test_hardware_setup_configures_camera(self):
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="hardware_setup",
            config={"camera": {"exposure_us": 2000}},
        )]
        cam = MagicMock()
        state = SimpleNamespace(cam=cam)
        executor = RecipeExecutor(r, app_state=state)
        result = executor.run()
        assert result.succeeded
        cam.set_exposure.assert_called_once_with(2000)

    def test_validation_skips_without_acquisition(self):
        r = Recipe()
        r.phases = [RecipePhase(
            phase_type="validation",
            config={"checks": ["snr_minimum"]},
        )]
        executor = RecipeExecutor(r, app_state=SimpleNamespace())
        result = executor.run()
        assert result.phase_results[0].status == "skipped"
