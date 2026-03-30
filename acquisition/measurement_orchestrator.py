"""
acquisition/measurement_orchestrator.py

Formal state machine that owns the full measurement lifecycle.

Wraps the pre-capture decision chain (readiness check, preflight validation,
diagnostic grade gate) and the post-capture pipeline (quality scoring,
calibration apply, session save, manifest write, autosave) into a single
coherent object with well-defined phases and signals.

The orchestrator does NOT directly drive the ``AcquisitionPipeline``.  The
existing pipeline (started by ``AcquireTab.start_acquisition()``) remains the
actual capture engine.  The orchestrator wraps the lifecycle *around* it:

    Pre-capture:  READINESS_CHECK → PREFLIGHT → GRADE_GATE → CAPTURING
    (caller starts actual capture when phase reaches CAPTURING)
    Post-capture: POST_PROCESSING → SAVING → COMPLETE

Two external entry points
-------------------------
1. ``start_measurement(n_frames, delay)`` — begins pre-capture phases
2. ``on_acquisition_complete(result)`` — drives post-processing and saving

Thread model
------------
Pre-capture phases run synchronously on the main (GUI) thread — they are fast
read-only checks.  Post-processing and saving run in a background thread to
avoid blocking the UI during disk I/O.

Usage
-----
    orch = MeasurementOrchestrator(hw_service, app_state, parent=self)
    orch.phase_changed.connect(on_phase)
    orch.user_decision_needed.connect(on_decision)
    orch.measurement_complete.connect(on_done)

    orch.start_measurement(n_frames=256, delay=0.0)
    # ... when phase reaches CAPTURING, caller starts real pipeline ...
    # ... when pipeline fires acq_complete, caller calls:
    orch.on_acquisition_complete(acq_result)
"""

from __future__ import annotations

import enum
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

import config

log = logging.getLogger(__name__)


# ── Phase enum ────────────────────────────────────────────────────────────────


class MeasurementPhase(enum.Enum):
    """All phases of a single measurement lifecycle."""
    IDLE              = "idle"
    READINESS_CHECK   = "readiness_check"
    PREFLIGHT         = "preflight"
    GRADE_GATE        = "grade_gate"
    PREPARING         = "preparing"
    CAPTURING         = "capturing"
    POST_PROCESSING   = "post_processing"
    SAVING            = "saving"
    COMPLETE          = "complete"
    ABORTED           = "aborted"
    ERROR             = "error"


_PHASE_LABELS = {
    MeasurementPhase.IDLE:              "Idle",
    MeasurementPhase.READINESS_CHECK:   "Readiness Check",
    MeasurementPhase.PREFLIGHT:         "Preflight Validation",
    MeasurementPhase.GRADE_GATE:        "Grade Gate",
    MeasurementPhase.PREPARING:         "Preparing",
    MeasurementPhase.CAPTURING:         "Capturing",
    MeasurementPhase.POST_PROCESSING:   "Post-Processing",
    MeasurementPhase.SAVING:            "Saving",
    MeasurementPhase.COMPLETE:          "Complete",
    MeasurementPhase.ABORTED:           "Aborted",
    MeasurementPhase.ERROR:             "Error",
}


# ── Context / Result dataclasses ──────────────────────────────────────────────


@dataclass
class MeasurementContext:
    """Snapshot of everything known *before* capture starts."""
    n_frames: int = 0
    delay: float = 0.0
    grade: str = "A"
    issues: list = field(default_factory=list)
    preflight_result: object = None       # PreflightResult | None
    start_ts: float = 0.0
    workflow: object = None               # WorkflowProfile (Phase 5, future)


@dataclass
class MeasurementResult:
    """Final output emitted on measurement_complete."""
    acquisition_result: object = None     # AcquisitionResult | None
    quality_scorecard: object = None      # QualityScorecard | None
    session_path: Optional[str] = None
    phase: MeasurementPhase = MeasurementPhase.COMPLETE
    duration_s: float = 0.0
    context: Optional[MeasurementContext] = None


# ── Grade computation (mirrors MainWindow._compute_grade) ─────────────────────


def compute_grade(results: list) -> str:
    """Derive A/B/C/D grade string from a list of RuleResult objects.

    This is a pure function extracted from ``MainWindow._compute_grade``
    so the orchestrator can use it without a widget reference.
    """
    fails = sum(1 for r in results if r.severity == "fail")
    warns = sum(1 for r in results if r.severity == "warn")
    if fails >= 2:
        return "D"
    if fails >= 1:
        return "C"
    if warns >= 3:
        return "C"
    if warns >= 1:
        return "B"
    return "A"


# ── Orchestrator ──────────────────────────────────────────────────────────────


class MeasurementOrchestrator(QObject):
    """State machine for the full measurement lifecycle.

    Signals
    -------
    phase_changed(MeasurementPhase, str)
        Emitted on every phase transition.  The string is a human-readable
        label (from ``_PHASE_LABELS``).
    user_decision_needed(str, str, dict)
        Emitted when the orchestrator needs a user decision before it can
        proceed.  Arguments: (decision_type, message, context_dict).
        The caller must invoke ``provide_decision("proceed")`` or
        ``provide_decision("abort")`` to unblock the state machine.
    measurement_complete(MeasurementResult)
        Emitted when the entire lifecycle reaches COMPLETE, ABORTED, or ERROR.
    """

    phase_changed          = pyqtSignal(object, str)
    user_decision_needed   = pyqtSignal(str, str, object)
    measurement_complete   = pyqtSignal(object)

    def __init__(
        self,
        hw_service: object,
        app_state: object,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._hw_service = hw_service
        self._app_state = app_state

        # Internal state
        self._phase = MeasurementPhase.IDLE
        self._context: Optional[MeasurementContext] = None
        self._result: Optional[MeasurementResult] = None
        self._pending_decision: Optional[str] = None  # decision_type awaiting response
        self._aborted = False

    # ── Properties ────────────────────────────────────────────────────

    @property
    def phase(self) -> MeasurementPhase:
        """Current lifecycle phase."""
        return self._phase

    @property
    def context(self) -> Optional[MeasurementContext]:
        """The measurement context for the current/last run."""
        return self._context

    # ── Phase transitions ─────────────────────────────────────────────

    def _set_phase(self, new_phase: MeasurementPhase) -> None:
        """Transition to *new_phase* and emit ``phase_changed``."""
        old = self._phase
        self._phase = new_phase
        label = _PHASE_LABELS.get(new_phase, new_phase.value)
        log.debug("MeasurementOrchestrator: %s → %s", old.value, new_phase.value)
        self.phase_changed.emit(new_phase, label)

    # ── Public API: start ─────────────────────────────────────────────

    def start_measurement(
        self,
        n_frames: int,
        delay: float = 0.0,
        workflow: object = None,
    ) -> None:
        """Begin the pre-capture phase chain.

        Runs synchronously on the calling (GUI) thread.  When the method
        returns, the orchestrator is in one of:
        - CAPTURING  (caller should start the real pipeline)
        - ABORTED    (user or safe-mode blocked it)
        - ERROR      (unexpected failure)
        - or it has emitted ``user_decision_needed`` and is parked in
          GRADE_GATE waiting for ``provide_decision()``.
        """
        self._aborted = False
        self._pending_decision = None
        self._context = MeasurementContext(
            n_frames=n_frames,
            delay=delay,
            start_ts=time.time(),
            workflow=workflow,
        )
        self._result = MeasurementResult(context=self._context)

        try:
            self._run_readiness_check()
            if self._aborted or self._phase in (
                MeasurementPhase.ABORTED, MeasurementPhase.ERROR,
            ):
                return

            self._run_preflight()
            if self._aborted or self._phase in (
                MeasurementPhase.ABORTED, MeasurementPhase.ERROR,
            ):
                return

            self._run_grade_gate()
            # If grade gate emitted user_decision_needed, we stop here.
            # The caller must invoke provide_decision() later.
            if self._pending_decision is not None:
                return

            if self._aborted or self._phase in (
                MeasurementPhase.ABORTED, MeasurementPhase.ERROR,
            ):
                return

            # All pre-capture checks passed — transition to CAPTURING
            self._set_phase(MeasurementPhase.CAPTURING)

        except Exception as exc:
            log.error("MeasurementOrchestrator: unexpected error in "
                      "pre-capture chain: %s", exc, exc_info=True)
            self._set_phase(MeasurementPhase.ERROR)
            self._result.phase = MeasurementPhase.ERROR
            self.measurement_complete.emit(self._result)

    # ── Public API: provide user decision ─────────────────────────────

    def provide_decision(self, decision: str) -> None:
        """Unblock the state machine after a ``user_decision_needed`` signal.

        Parameters
        ----------
        decision : str
            ``"proceed"`` to continue to CAPTURING, or ``"abort"`` to cancel.
        """
        if self._pending_decision is None:
            log.warning("provide_decision('%s') called but no decision pending",
                        decision)
            return

        decision_type = self._pending_decision
        self._pending_decision = None
        log.debug("MeasurementOrchestrator: user decision for %s → %s",
                  decision_type, decision)

        if decision == "proceed":
            self._set_phase(MeasurementPhase.CAPTURING)
        else:
            self._set_phase(MeasurementPhase.ABORTED)
            self._aborted = True
            self._result.phase = MeasurementPhase.ABORTED
            self.measurement_complete.emit(self._result)

    # ── Public API: abort ─────────────────────────────────────────────

    def abort(self) -> None:
        """Abort the measurement at whatever phase it is in.

        If the orchestrator is in a pre-capture phase, it transitions to
        ABORTED immediately.  If it is in POST_PROCESSING or SAVING the
        background thread will notice the flag and stop early.
        """
        self._aborted = True
        if self._phase not in (
            MeasurementPhase.COMPLETE,
            MeasurementPhase.ABORTED,
            MeasurementPhase.ERROR,
        ):
            self._set_phase(MeasurementPhase.ABORTED)
            if self._result is not None:
                self._result.phase = MeasurementPhase.ABORTED
            self.measurement_complete.emit(
                self._result or MeasurementResult(phase=MeasurementPhase.ABORTED))

    # ── Public API: post-capture entry point ──────────────────────────

    def on_acquisition_complete(self, acq_result: object) -> None:
        """Called by MainWindow when the pipeline's ``acq_complete`` fires.

        Drives post-processing (quality scoring, calibration apply) and saving
        (session persist, manifest write, autosave) in a background thread.
        """
        if self._context is None:
            log.warning("on_acquisition_complete called but no active context")
            return

        self._result.acquisition_result = acq_result
        self._set_phase(MeasurementPhase.POST_PROCESSING)

        # Run post-processing + save in a background thread
        threading.Thread(
            target=self._post_capture_pipeline,
            args=(acq_result,),
            daemon=True,
            name="MeasurementOrchestrator-post",
        ).start()

    # ══════════════════════════════════════════════════════════════════
    #  Pre-capture phases (main thread, synchronous)
    # ══════════════════════════════════════════════════════════════════

    def _run_readiness_check(self) -> None:
        """Phase 1: Check safe-mode / required-device gate."""
        self._set_phase(MeasurementPhase.READINESS_CHECK)

        device_mgr = getattr(self._hw_service, '_device_mgr', None)
        if device_mgr is None:
            device_mgr = getattr(self._hw_service, 'device_mgr', None)

        if device_mgr is None:
            # No device manager available — skip readiness check
            log.debug("Readiness check: no device manager found, skipping")
            return

        if not device_mgr.safe_mode:
            log.debug("Readiness check: not in safe mode — OK")
            return

        # Safe mode is active — acquisition is blocked
        reason = device_mgr.safe_mode_reason or "Required device missing"

        # Also try the readiness subsystem for a richer message
        try:
            from hardware.readiness import check_readiness, OP_ACQUIRE
            rdns = check_readiness(OP_ACQUIRE, self._app_state)
            if rdns.blocked_reason:
                reason = rdns.blocked_reason
        except Exception:
            pass

        log.info("Readiness check: safe mode active — %s", reason)
        self._pending_decision = "safe_mode_block"
        self._set_phase(MeasurementPhase.READINESS_CHECK)
        self.user_decision_needed.emit(
            "safe_mode_block",
            f"Acquisition is blocked because a required device is missing.\n\n"
            f"{reason}\n\n"
            f"Connect the device in Device Manager to proceed.",
            {},
        )
        # For safe-mode, we go directly to ABORTED — no override path
        self._pending_decision = None
        self._aborted = True
        self._set_phase(MeasurementPhase.ABORTED)
        self._result.phase = MeasurementPhase.ABORTED
        self.measurement_complete.emit(self._result)

    def _run_preflight(self) -> None:
        """Phase 2: Run preflight validation checks."""
        self._set_phase(MeasurementPhase.PREFLIGHT)

        if not config.get_pref("acquisition.preflight_enabled", True):
            log.debug("Preflight: disabled by user preference")
            return

        try:
            from acquisition.preflight import PreflightValidator

            # Build metrics snapshot if the hw_service has a metrics ref
            metrics = getattr(self._hw_service, '_metrics', None)
            if metrics is None:
                metrics = getattr(self._hw_service, 'metrics_service', None)
            metrics_snap = {}
            if metrics is not None and hasattr(metrics, 'latest_snapshot'):
                metrics_snap = metrics.latest_snapshot()

            validator = PreflightValidator(self._app_state, metrics_snap)
            preflight = validator.run(operation="acquire")
            self._context.preflight_result = preflight
            log.debug("Preflight: passed=%s  warnings=%s  checks=%d",
                      preflight.passed, preflight.has_warnings,
                      len(preflight.checks))
        except Exception:
            log.debug("Preflight validation failed — proceeding anyway",
                      exc_info=True)
            self._context.preflight_result = None

    def _run_grade_gate(self) -> None:
        """Phase 3: Evaluate diagnostic grade and decide proceed/warn/block."""
        self._set_phase(MeasurementPhase.GRADE_GATE)

        # ── Compute diagnostic grade ──────────────────────────────────
        grade = "A"
        results = []
        try:
            from ai.diagnostic_engine import DiagnosticEngine

            metrics = getattr(self._hw_service, '_metrics', None)
            if metrics is None:
                metrics = getattr(self._hw_service, 'metrics_service', None)

            if metrics is not None:
                engine = DiagnosticEngine(metrics)
                results = engine.evaluate()
                grade = compute_grade(results)
            else:
                log.debug("Grade gate: no metrics service — defaulting to A")
        except Exception:
            log.debug("Diagnostic evaluation failed — defaulting to A",
                      exc_info=True)

        # Store in context
        self._context.grade = grade
        self._context.issues = [
            r for r in results if r.severity in ("fail", "warn")
        ]

        log.debug("Grade gate: grade=%s  issues=%d", grade,
                  len(self._context.issues))

        # ── Decision logic ────────────────────────────────────────────
        preflight = self._context.preflight_result
        preflight_ok = (preflight is None or preflight.all_clear)

        # Fast path: everything green
        if grade in ("A", "B") and preflight_ok:
            return

        # Preflight has issues but grade is OK — signal preflight issues
        if preflight is not None and not preflight.all_clear and grade in ("A", "B"):
            issue_summary = _format_preflight_issues(preflight)
            self._pending_decision = "preflight_issues"
            self.user_decision_needed.emit(
                "preflight_issues",
                f"Preflight validation found issues:\n\n{issue_summary}",
                {
                    "grade": grade,
                    "preflight": preflight,
                    "issues": self._context.issues,
                },
            )
            return

        # Grade C — warning, user can override
        if grade == "C":
            issue_lines = _format_grade_issues(self._context.issues)
            self._pending_decision = "grade_warning"
            self.user_decision_needed.emit(
                "grade_warning",
                f"The instrument has active warnings (Grade C).\n\n"
                f"{issue_lines}\n\n"
                f"Proceeding may affect data quality.",
                {
                    "grade": grade,
                    "issues": self._context.issues,
                    "preflight": preflight,
                },
            )
            return

        # Grade D — critical, strong warning
        if grade == "D":
            issue_lines = _format_grade_issues(self._context.issues)
            self._pending_decision = "grade_critical"
            self.user_decision_needed.emit(
                "grade_critical",
                f"The instrument has critical failures (Grade D).\n\n"
                f"{issue_lines}\n\n"
                f"Acquisition results will likely be unreliable.\n"
                f"Resolve failures before proceeding if possible.",
                {
                    "grade": grade,
                    "issues": self._context.issues,
                    "preflight": preflight,
                },
            )
            return

    # ══════════════════════════════════════════════════════════════════
    #  Post-capture pipeline (background thread)
    # ══════════════════════════════════════════════════════════════════

    def _post_capture_pipeline(self, acq_result: object) -> None:
        """Run post-processing and saving in a background thread.

        The method transitions through POST_PROCESSING → SAVING → COMPLETE
        (or ERROR if something goes wrong).  Phase transitions emit signals
        that are auto-queued to the GUI thread by Qt.
        """
        try:
            # ── Post-processing: quality scoring ──────────────────────
            self.phase_changed.emit(
                MeasurementPhase.POST_PROCESSING, "Scoring quality…")
            scorecard = self._compute_quality_scorecard(acq_result)
            if self._aborted:
                return

            # ── Post-processing: calibration apply ────────────────────
            self.phase_changed.emit(
                MeasurementPhase.POST_PROCESSING, "Applying calibration…")
            self._apply_calibration(acq_result)
            if self._aborted:
                return

            # ── Saving ────────────────────────────────────────────────
            self._set_phase(MeasurementPhase.SAVING)
            self.phase_changed.emit(
                MeasurementPhase.SAVING, "Saving session…")
            session_path = self._save_session(acq_result, scorecard)
            if self._aborted:
                return

            self.phase_changed.emit(
                MeasurementPhase.SAVING, "Writing manifest…")

            # ── Complete ──────────────────────────────────────────────
            duration = time.time() - self._context.start_ts
            self._result.quality_scorecard = scorecard
            self._result.session_path = session_path
            self._result.duration_s = duration
            self._result.phase = MeasurementPhase.COMPLETE

            self._set_phase(MeasurementPhase.COMPLETE)
            self.measurement_complete.emit(self._result)

        except Exception as exc:
            log.error("Post-capture pipeline failed: %s", exc, exc_info=True)
            self._result.phase = MeasurementPhase.ERROR
            self._set_phase(MeasurementPhase.ERROR)
            self.measurement_complete.emit(self._result)

    def _compute_quality_scorecard(self, acq_result: object) -> object:
        """Compute quality scorecard from the acquisition result.

        Returns a ``QualityScorecard`` or *None* if computation fails.
        """
        try:
            from acquisition.quality_scorecard import QualityScoringEngine
            from acquisition.image_metrics import (
                compute_intensity_stats, compute_frame_stability,
            )

            cold = getattr(acq_result, "cold_avg", None)
            bit_depth = 12
            if cold is not None:
                cam = self._app_state.cam
                if cam and cam.info:
                    bit_depth = cam.info.bit_depth
                stats = compute_intensity_stats(cold, bit_depth)
                mean_f = stats["mean_frac"]
                max_f = stats["max_frac"]
            else:
                mean_f, max_f = 0.5, 0.7

            drr = getattr(acq_result, "delta_r_over_r", None)
            peak_drr = float(abs(drr).max()) if drr is not None else None

            scorecard = QualityScoringEngine.compute(
                snr_db=getattr(acq_result, "snr_db", None),
                mean_frac=mean_f,
                max_frac=max_f,
                peak_drr=peak_drr,
                frame_cv=None,
                n_frames=getattr(acq_result, "n_frames", 0),
                duration_s=getattr(acq_result, "duration_s", 0.0),
            )
            # Store on the result object for downstream consumers
            acq_result._quality_scorecard = scorecard.to_dict()
            log.debug("Quality scorecard: overall=%s", scorecard.overall_grade)
            return scorecard

        except Exception:
            log.debug("Quality scorecard computation failed", exc_info=True)
            return None

    def _apply_calibration(self, acq_result: object) -> None:
        """Apply active calibration to produce a delta-T map."""
        cal = self._app_state.active_calibration
        if cal and cal.valid:
            try:
                drr = getattr(acq_result, "delta_r_over_r", None)
                if drr is not None:
                    acq_result.delta_t = cal.apply(drr)
                    log.debug("Calibration applied successfully")
            except Exception as exc:
                log.debug("Calibration apply failed: %s", exc)
                acq_result.delta_t = None

    def _save_session(
        self, acq_result: object, scorecard: object,
    ) -> Optional[str]:
        """Persist the acquisition to the session manager.

        Returns the session directory path or *None* on failure.
        """
        try:
            from acquisition.session_manager import SessionManager

            # Locate the session manager — try the hw_service parent chain
            # or fall back to creating from config
            session_mgr = self._find_session_manager()
            if session_mgr is None:
                log.debug("No session manager found — skipping save")
                return None

            profile = self._app_state.active_profile
            fpga = self._app_state.fpga
            label = time.strftime("acq_%Y%m%d_%H%M%S")

            fpga_freq = 0.0
            if fpga and hasattr(fpga, "get_status"):
                status = fpga.get_status()
                fpga_freq = getattr(status, "frequency_hz", 0.0)

            session = session_mgr.save_result(
                acq_result,
                label=label,
                imaging_mode=self._app_state.active_modality,
                profile_uid=profile.uid if profile else "",
                profile_name=profile.name if profile else "",
                ct_value=profile.ct_value if profile else 0.0,
                fpga_frequency_hz=fpga_freq,
                notes="",
            )

            # Attach quality scorecard to session metadata
            sc_dict = getattr(acq_result, '_quality_scorecard', None)
            if sc_dict and session.meta and session.meta.path:
                session.meta.quality_scorecard = sc_dict
                try:
                    import json as _json
                    meta_path = os.path.join(session.meta.path, "session.json")
                    with open(meta_path, "w") as fp:
                        _json.dump(session.meta.to_dict(), fp, indent=2)
                except Exception:
                    log.debug("Failed to save scorecard to session",
                              exc_info=True)

            # Write run manifest
            self._write_manifest(acq_result, session)

            log.debug("Session saved: %s", session.meta.uid)

            # Emit saved signal via app signals
            try:
                from ui.app_signals import signals
                signals.acq_saved.emit(session)
                signals.log_message.emit(
                    f"Session saved: {session.meta.uid}")
            except Exception:
                pass

            return session.meta.path if session.meta else None

        except Exception as exc:
            log.error("Session save failed: %s", exc, exc_info=True)
            return None

    def _write_manifest(self, acq_result: object, session: object) -> None:
        """Write a RunRecord to the session manifest."""
        try:
            from session.manifest import (
                RunRecord, ManifestWriter,
                build_device_inventory, build_settings_snapshot,
            )

            device_mgr = getattr(self._hw_service, '_device_mgr', None)
            if device_mgr is None:
                device_mgr = getattr(self._hw_service, 'device_mgr', None)

            now = time.time()
            cal = self._app_state.active_calibration
            cal_status = "ok" if (cal and cal.valid) else "missing"
            cal_uid = getattr(cal, "uid", "") if (cal and cal.valid) else ""

            # Readiness snapshot for degraded-mode flag
            degraded = False
            optional_missing = []
            try:
                from hardware.readiness import check_readiness, OP_ACQUIRE
                rdns = check_readiness(OP_ACQUIRE, self._app_state)
                degraded = rdns.degraded
                optional_missing = rdns.optional_missing
            except Exception:
                pass

            # Event trace from timeline
            event_trace = []
            try:
                from events import timeline as _tl
                event_trace = _tl.export_for_run(
                    self._context.start_ts, now)
            except Exception:
                pass

            record = RunRecord(
                operation="acquire",
                started_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(self._context.start_ts)),
                completed_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(now)),
                duration_s=getattr(acq_result, "duration_s", 0.0),
                outcome=(
                    "complete" if acq_result.is_complete else "abort"),
                session_uid=session.meta.uid,
                device_inventory=(
                    build_device_inventory(device_mgr)
                    if device_mgr else {}),
                settings_snapshot=build_settings_snapshot(self._app_state),
                calibration_uid=cal_uid,
                calibration_status=cal_status,
                degraded_mode=degraded,
                optional_devices_missing=optional_missing,
                snr_db=getattr(acq_result, "snr_db", None),
                n_frames=getattr(acq_result, "n_frames", 0),
                event_trace=event_trace,
            )
            ManifestWriter(session.meta.path).append_run(record)

            # Emit ACQ_COMPLETE event
            try:
                from events import emit_info, EVT_ACQ_COMPLETE
                emit_info(
                    "acquisition", EVT_ACQ_COMPLETE,
                    f"Acquisition complete — snr={record.snr_db} dB  "
                    f"outcome={record.outcome}",
                    session_uid=session.meta.uid,
                    outcome=record.outcome,
                    snr_db=record.snr_db,
                    label="EVT_ACQ_COMPLETE",
                    level=logging.DEBUG,
                )
            except ImportError:
                pass

        except Exception as exc:
            log.debug("Manifest write failed: %s", exc)

    def _find_session_manager(self) -> object:
        """Locate the active SessionManager instance.

        Tries the parent widget chain (MainWindow typically holds it),
        then falls back to importing the module-level singleton.
        """
        # Walk up the parent chain looking for a session_mgr attribute
        parent = self.parent()
        while parent is not None:
            mgr = getattr(parent, '_session_mgr', None)
            if mgr is not None:
                return mgr
            # Also check the common pattern of a bare `session_mgr` attr
            mgr = getattr(parent, 'session_mgr', None)
            if mgr is not None:
                return mgr
            parent = parent.parent() if hasattr(parent, 'parent') else None

        # Fall back to the module-level singleton in main_app
        try:
            import main_app
            return getattr(main_app, 'session_mgr', None)
        except Exception:
            return None


# ── Formatting helpers (module-level) ─────────────────────────────────────────


def _format_grade_issues(issues: list, max_lines: int = 6) -> str:
    """Format diagnostic issues for display in a user-facing message."""
    lines = []
    for r in issues[:max_lines]:
        icon = "\u2297" if r.severity == "fail" else "\u26A0"  # ⊗ or ⚠
        display = getattr(r, 'display_name', str(r))
        observed = getattr(r, 'observed', '')
        lines.append(f"  {icon}  {display}: {observed}")
    if len(issues) > max_lines:
        lines.append(f"  ... and {len(issues) - max_lines} more")
    return "\n".join(lines)


def _format_preflight_issues(preflight: object, max_lines: int = 6) -> str:
    """Format preflight check results for display."""
    lines = []
    for check in getattr(preflight, 'checks', []):
        if check.status == "pass":
            continue
        icon = "\u2297" if check.status == "fail" else "\u26A0"
        lines.append(f"  {icon}  {check.display_name}: {check.observed}")
        if len(lines) >= max_lines:
            remaining = sum(
                1 for c in preflight.checks if c.status != "pass"
            ) - max_lines
            if remaining > 0:
                lines.append(f"  ... and {remaining} more")
            break
    return "\n".join(lines)
