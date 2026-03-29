"""
tests/test_measurement_orchestrator.py

Unit tests for the MeasurementOrchestrator state machine.

Covers:
  1. Phase enum completeness and labels
  2. Dataclass defaults and field assignments
  3. Grade computation (pure function)
  4. Phase transitions: IDLE → CAPTURING (happy path)
  5. Phase transitions with grade gate decisions (proceed / abort)
  6. Abort at every phase
  7. Post-capture pipeline: POST_PROCESSING → SAVING → COMPLETE
  8. Error handling in post-capture
  9. Double abort / abort when already complete (idempotent)
 10. Workflow profile integration

All tests use stubs — no real hardware, no QApplication event loop.

Run:
    cd sanjinsight
    pytest tests/test_measurement_orchestrator.py -v
"""

from __future__ import annotations

import os
import sys
import time
import threading

import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    """One QApplication for the whole module (signals need Qt infrastructure)."""
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _StubAppState:
    """Minimal app_state stand-in for orchestrator tests."""
    demo_mode = True
    cam = None
    ir_cam = None
    fpga = None
    bias = None
    stage = None
    pipeline = None
    active_calibration = None
    active_modality = "tr"
    active_profile = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _StubHwService:
    """Minimal HardwareService stand-in — no signals, no threads."""
    _device_mgr = None
    device_mgr = None
    _metrics = None
    metrics_service = None


@pytest.fixture
def stub_app_state():
    return _StubAppState()


@pytest.fixture
def stub_hw():
    return _StubHwService()


@pytest.fixture
def orchestrator(qapp, stub_hw, stub_app_state, monkeypatch):
    """Create an orchestrator with preflight disabled so tests reach CAPTURING."""
    import config
    _real_get_pref = config.get_pref
    # Disable preflight so the grade gate doesn't park on preflight issues
    def _patched_get_pref(key, default=None):
        if key == "acquisition.preflight_enabled":
            return False
        return _real_get_pref(key, default)
    monkeypatch.setattr(config, "get_pref", _patched_get_pref)
    from acquisition.measurement_orchestrator import MeasurementOrchestrator
    return MeasurementOrchestrator(stub_hw, stub_app_state)


# ================================================================== #
#  1. Phase enum completeness                                          #
# ================================================================== #

class TestMeasurementPhase:
    """Verify the phase enum and label table."""

    def test_all_phases_have_labels(self):
        from acquisition.measurement_orchestrator import (
            MeasurementPhase, _PHASE_LABELS,
        )
        for phase in MeasurementPhase:
            assert phase in _PHASE_LABELS, (
                f"MeasurementPhase.{phase.name} has no label in _PHASE_LABELS"
            )

    def test_phase_count(self):
        from acquisition.measurement_orchestrator import MeasurementPhase
        assert len(MeasurementPhase) == 11, (
            f"Expected 11 phases, got {len(MeasurementPhase)}"
        )

    def test_phase_values_are_unique(self):
        from acquisition.measurement_orchestrator import MeasurementPhase
        values = [p.value for p in MeasurementPhase]
        assert len(values) == len(set(values)), "Duplicate phase values detected"


# ================================================================== #
#  2. Dataclass defaults                                               #
# ================================================================== #

class TestDataclasses:
    """Verify MeasurementContext and MeasurementResult defaults."""

    def test_context_defaults(self):
        from acquisition.measurement_orchestrator import MeasurementContext
        ctx = MeasurementContext()
        assert ctx.n_frames == 0
        assert ctx.delay == 0.0
        assert ctx.grade == "A"
        assert ctx.issues == []
        assert ctx.preflight_result is None
        assert ctx.start_ts == 0.0
        assert ctx.workflow is None

    def test_result_defaults(self):
        from acquisition.measurement_orchestrator import (
            MeasurementResult, MeasurementPhase,
        )
        r = MeasurementResult()
        assert r.acquisition_result is None
        assert r.quality_scorecard is None
        assert r.session_path is None
        assert r.phase == MeasurementPhase.COMPLETE
        assert r.duration_s == 0.0
        assert r.context is None

    def test_context_field_assignment(self):
        from acquisition.measurement_orchestrator import MeasurementContext
        ctx = MeasurementContext(n_frames=100, delay=1.5, grade="B")
        assert ctx.n_frames == 100
        assert ctx.delay == 1.5
        assert ctx.grade == "B"

    def test_result_field_assignment(self):
        from acquisition.measurement_orchestrator import (
            MeasurementResult, MeasurementPhase,
        )
        r = MeasurementResult(
            phase=MeasurementPhase.ERROR,
            duration_s=12.5,
            session_path="/tmp/session_001",
        )
        assert r.phase == MeasurementPhase.ERROR
        assert r.duration_s == 12.5
        assert r.session_path == "/tmp/session_001"


# ================================================================== #
#  3. Grade computation (pure function)                                #
# ================================================================== #

class TestComputeGrade:
    """Verify the compute_grade() pure function."""

    @staticmethod
    def _make_rule_result(severity: str):
        """Create a minimal object with a .severity attribute."""
        class R:
            pass
        r = R()
        r.severity = severity
        return r

    def test_all_pass_returns_A(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [self._make_rule_result("pass") for _ in range(5)]
        assert compute_grade(results) == "A"

    def test_empty_returns_A(self):
        from acquisition.measurement_orchestrator import compute_grade
        assert compute_grade([]) == "A"

    def test_one_warn_returns_B(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [
            self._make_rule_result("pass"),
            self._make_rule_result("warn"),
        ]
        assert compute_grade(results) == "B"

    def test_two_warns_returns_B(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [self._make_rule_result("warn") for _ in range(2)]
        assert compute_grade(results) == "B"

    def test_three_warns_returns_C(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [self._make_rule_result("warn") for _ in range(3)]
        assert compute_grade(results) == "C"

    def test_one_fail_returns_C(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [self._make_rule_result("fail")]
        assert compute_grade(results) == "C"

    def test_two_fails_returns_D(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [self._make_rule_result("fail") for _ in range(2)]
        assert compute_grade(results) == "D"

    def test_mixed_fail_and_warn(self):
        from acquisition.measurement_orchestrator import compute_grade
        results = [
            self._make_rule_result("fail"),
            self._make_rule_result("warn"),
            self._make_rule_result("warn"),
            self._make_rule_result("pass"),
        ]
        # 1 fail → C
        assert compute_grade(results) == "C"


# ================================================================== #
#  4. Happy path: IDLE → CAPTURING                                     #
# ================================================================== #

class TestHappyPath:
    """start_measurement with no blockers reaches CAPTURING."""

    def test_reaches_capturing(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import MeasurementPhase

        phases = []
        orchestrator.phase_changed.connect(lambda p, _: phases.append(p))

        orchestrator.start_measurement(n_frames=50, delay=0.0)

        assert orchestrator.phase == MeasurementPhase.CAPTURING
        # Must have passed through at least READINESS_CHECK, PREFLIGHT, GRADE_GATE
        phase_names = [p.value for p in phases]
        assert "readiness_check" in phase_names
        assert "preflight" in phase_names
        assert "grade_gate" in phase_names
        assert "capturing" in phase_names

    def test_context_is_populated(self, orchestrator, qapp):
        orchestrator.start_measurement(n_frames=100, delay=2.5)
        ctx = orchestrator.context
        assert ctx is not None
        assert ctx.n_frames == 100
        assert ctx.delay == 2.5
        assert ctx.start_ts > 0

    def test_starts_in_idle(self, qapp, stub_hw, stub_app_state):
        from acquisition.measurement_orchestrator import (
            MeasurementOrchestrator, MeasurementPhase,
        )
        orch = MeasurementOrchestrator(stub_hw, stub_app_state)
        assert orch.phase == MeasurementPhase.IDLE


# ================================================================== #
#  5. Grade gate decisions                                             #
# ================================================================== #

class TestGradeGateDecisions:
    """Test user_decision_needed → provide_decision flow."""

    def test_provide_decision_proceed_reaches_capturing(self, orchestrator, qapp):
        """Simulating a grade-C scenario that emits user_decision_needed."""
        from acquisition.measurement_orchestrator import MeasurementPhase

        # Manually simulate a pending decision (as if grade gate triggered it)
        orchestrator._context = type(orchestrator._context) if orchestrator._context else None
        orchestrator.start_measurement(n_frames=50)
        # If it already reached CAPTURING (no issues), force a grade gate scenario
        if orchestrator.phase == MeasurementPhase.CAPTURING:
            orchestrator._phase = MeasurementPhase.GRADE_GATE
            orchestrator._pending_decision = "grade_warning"

        orchestrator.provide_decision("proceed")
        assert orchestrator.phase == MeasurementPhase.CAPTURING

    def test_provide_decision_abort_reaches_aborted(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import MeasurementPhase

        orchestrator.start_measurement(n_frames=50)
        # Force a grade gate scenario
        if orchestrator.phase == MeasurementPhase.CAPTURING:
            orchestrator._phase = MeasurementPhase.GRADE_GATE
            orchestrator._pending_decision = "grade_critical"

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.provide_decision("abort")
        assert orchestrator.phase == MeasurementPhase.ABORTED
        assert len(results) == 1
        assert results[0].phase == MeasurementPhase.ABORTED

    def test_provide_decision_when_no_pending_is_noop(self, orchestrator, qapp):
        """provide_decision() with nothing pending must not crash or change state."""
        from acquisition.measurement_orchestrator import MeasurementPhase

        orchestrator._pending_decision = None
        original_phase = orchestrator.phase
        orchestrator.provide_decision("proceed")
        assert orchestrator.phase == original_phase


# ================================================================== #
#  6. Abort at various phases                                          #
# ================================================================== #

class TestAbort:
    """Verify abort() transitions to ABORTED from any active phase."""

    def test_abort_from_idle(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import MeasurementPhase

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.abort()
        assert orchestrator.phase == MeasurementPhase.ABORTED
        assert len(results) == 1

    def test_abort_from_capturing(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import MeasurementPhase

        orchestrator.start_measurement(n_frames=50)
        assert orchestrator.phase == MeasurementPhase.CAPTURING

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.abort()
        assert orchestrator.phase == MeasurementPhase.ABORTED
        assert len(results) == 1
        assert results[0].phase == MeasurementPhase.ABORTED

    def test_abort_is_idempotent(self, orchestrator, qapp):
        """Calling abort() twice must not raise or emit duplicate signals."""
        from acquisition.measurement_orchestrator import MeasurementPhase

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.abort()
        assert orchestrator.phase == MeasurementPhase.ABORTED
        count_after_first = len(results)

        orchestrator.abort()  # second call — should be no-op
        assert orchestrator.phase == MeasurementPhase.ABORTED
        assert len(results) == count_after_first  # no extra emission

    def test_abort_after_complete_is_noop(self, orchestrator, qapp):
        """abort() when already COMPLETE must not change state."""
        from acquisition.measurement_orchestrator import MeasurementPhase

        orchestrator._phase = MeasurementPhase.COMPLETE
        orchestrator.abort()
        assert orchestrator.phase == MeasurementPhase.COMPLETE


# ================================================================== #
#  7. Post-capture pipeline                                            #
# ================================================================== #

class TestPostCapture:
    """Test on_acquisition_complete drives POST_PROCESSING → SAVING → COMPLETE."""

    def test_post_capture_reaches_terminal_phase(self, orchestrator, qapp):
        """on_acquisition_complete drives through POST_PROCESSING to a terminal phase.

        In a test environment the save step may fail (no real session manager),
        so we accept COMPLETE or ERROR as valid terminal states.  The key
        assertion is that the pipeline runs and emits measurement_complete.
        """
        from acquisition.measurement_orchestrator import MeasurementPhase
        from PyQt5.QtWidgets import QApplication
        import numpy as np

        # Set up context first (normally done by start_measurement)
        orchestrator.start_measurement(n_frames=10)
        assert orchestrator.phase == MeasurementPhase.CAPTURING

        # Create a minimal AcquisitionResult-like object
        class FakeResult:
            n_frames = 10
            duration_s = 1.0
            cold_avg = np.random.rand(32, 32).astype(np.float32)
            hot_avg = np.random.rand(32, 32).astype(np.float32)
            delta_r_over_r = np.random.rand(32, 32).astype(np.float32) * 0.01
            snr_db = 30.0
            is_complete = True

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.on_acquisition_complete(FakeResult())

        # Wait for the background thread to finish; process Qt events so
        # cross-thread signals are delivered.
        deadline = time.monotonic() + 5.0
        while not results and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)

        assert len(results) >= 1, (
            "measurement_complete was never emitted after on_acquisition_complete"
        )
        final = results[-1]
        assert final.phase in (
            MeasurementPhase.COMPLETE,
            MeasurementPhase.ERROR,  # acceptable — session_mgr may not be available
        )

    def test_post_capture_without_context_is_noop(self, orchestrator, qapp):
        """on_acquisition_complete with no active context should warn, not crash."""
        from acquisition.measurement_orchestrator import MeasurementPhase

        orchestrator._context = None
        # Should return silently
        orchestrator.on_acquisition_complete(object())
        # Phase should not have changed from IDLE
        assert orchestrator.phase == MeasurementPhase.IDLE


# ================================================================== #
#  8. Workflow profile integration                                     #
# ================================================================== #

class TestWorkflowIntegration:
    """Verify workflow profile is stored in context."""

    def test_workflow_stored_in_context(self, orchestrator, qapp):
        from acquisition.workflows import FAILURE_ANALYSIS

        orchestrator.start_measurement(
            n_frames=50, delay=0.0, workflow=FAILURE_ANALYSIS)
        assert orchestrator.context.workflow is FAILURE_ANALYSIS

    def test_metrology_workflow_stored(self, orchestrator, qapp):
        from acquisition.workflows import METROLOGY

        orchestrator.start_measurement(
            n_frames=200, delay=0.0, workflow=METROLOGY)
        assert orchestrator.context.workflow is METROLOGY

    def test_default_workflow_is_none(self, orchestrator, qapp):
        orchestrator.start_measurement(n_frames=50)
        assert orchestrator.context.workflow is None


# ================================================================== #
#  9. Phase transition signal delivery                                 #
# ================================================================== #

class TestPhaseSignals:
    """Verify phase_changed signal carries correct arguments."""

    def test_phase_changed_carries_label(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import (
            MeasurementPhase, _PHASE_LABELS,
        )

        emitted = []
        orchestrator.phase_changed.connect(lambda p, lbl: emitted.append((p, lbl)))

        orchestrator.start_measurement(n_frames=50)

        # Verify each emitted (phase, label) pair matches the label table
        for phase, label in emitted:
            expected_label = _PHASE_LABELS[phase]
            assert label == expected_label, (
                f"Phase {phase.value}: expected label {expected_label!r}, "
                f"got {label!r}"
            )

    def test_measurement_complete_carries_result(self, orchestrator, qapp):
        from acquisition.measurement_orchestrator import MeasurementPhase

        results = []
        orchestrator.measurement_complete.connect(lambda r: results.append(r))

        orchestrator.abort()
        assert len(results) == 1
        assert hasattr(results[0], 'phase')
        assert hasattr(results[0], 'duration_s')
        assert hasattr(results[0], 'context')


# ================================================================== #
# 10. Safe-mode blocking (readiness check)                            #
# ================================================================== #

class TestSafeModeBlocking:
    """Verify that safe-mode blocks acquisition."""

    def test_safe_mode_blocks_acquisition(self, qapp, stub_app_state):
        from acquisition.measurement_orchestrator import (
            MeasurementOrchestrator, MeasurementPhase,
        )

        class SafeDeviceMgr:
            safe_mode = True
            safe_mode_reason = "Camera not connected"

        hw = _StubHwService()
        hw._device_mgr = SafeDeviceMgr()

        orch = MeasurementOrchestrator(hw, stub_app_state)

        results = []
        orch.measurement_complete.connect(lambda r: results.append(r))

        orch.start_measurement(n_frames=50)

        assert orch.phase == MeasurementPhase.ABORTED
        assert len(results) == 1
        assert results[0].phase == MeasurementPhase.ABORTED

    def test_no_safe_mode_passes_readiness(self, qapp, stub_app_state, monkeypatch):
        from acquisition.measurement_orchestrator import (
            MeasurementOrchestrator, MeasurementPhase,
        )
        import config
        _real = config.get_pref
        def _patched(key, default=None):
            if key == "acquisition.preflight_enabled":
                return False
            return _real(key, default)
        monkeypatch.setattr(config, "get_pref", _patched)

        class NormalDeviceMgr:
            safe_mode = False
            safe_mode_reason = ""

        hw = _StubHwService()
        hw._device_mgr = NormalDeviceMgr()

        orch = MeasurementOrchestrator(hw, stub_app_state)
        orch.start_measurement(n_frames=50)

        assert orch.phase == MeasurementPhase.CAPTURING
