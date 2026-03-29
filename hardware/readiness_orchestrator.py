"""
hardware/readiness_orchestrator.py

Multi-step hardware preparation sequencer for "Optimize & Acquire".

Coordinates: auto-expose → auto-gain → TEC preconditioning → preflight
validation in a single background sequence with progress signals.

Thread model
------------
The orchestrator runs its sequence on a background QThread.  Progress is
reported via Qt signals (auto-queued to the GUI thread).  Individual step
modules (auto_expose, auto_gain, TecPreconditioning) are thread-safe.

Usage
-----
    orch = ReadinessOrchestrator(hw_service, metrics_service)
    orch.configure(steps=[Step.AUTO_EXPOSE, Step.AUTO_GAIN, Step.PREFLIGHT])
    orch.progress.connect(on_progress)
    orch.complete.connect(on_complete)
    orch.start()
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

log = logging.getLogger(__name__)


# ── Step definitions ──────────────────────────────────────────────────────────

class Step(enum.Enum):
    AUTO_EXPOSE      = "auto_expose"
    AUTO_GAIN        = "auto_gain"
    TEC_PRECONDITION = "tec_precondition"
    PREFLIGHT        = "preflight"


# Canonical execution order
_STEP_ORDER = [Step.AUTO_EXPOSE, Step.AUTO_GAIN,
               Step.TEC_PRECONDITION, Step.PREFLIGHT]

_STEP_LABELS = {
    Step.AUTO_EXPOSE:      "Auto-Expose",
    Step.AUTO_GAIN:        "Auto-Gain",
    Step.TEC_PRECONDITION: "TEC Preconditioning",
    Step.PREFLIGHT:        "Preflight Validation",
}


@dataclass
class StepProgress:
    """Progress update for the UI."""
    current_step:   Step
    step_label:     str
    step_index:     int
    total_steps:    int
    step_progress:  float = 0.0   # 0–1 within the step
    message:        str   = ""
    can_skip:       bool  = False


@dataclass
class OrchestratorResult:
    """Aggregate result of the full preparation sequence."""
    success:         bool
    steps_completed: list[Step] = field(default_factory=list)
    steps_skipped:   list[Step] = field(default_factory=list)
    auto_expose_result: object = None   # AutoExposeResult
    auto_gain_result:   object = None   # AutoGainResult
    tec_result:         object = None   # TecPreconditionResult
    preflight_result:   object = None   # PreflightResult
    duration_s:      float = 0.0
    message:         str   = ""


# ── Worker thread ─────────────────────────────────────────────────────────────

class _Worker(QThread):
    """Background thread executing the preparation sequence."""

    progress = pyqtSignal(object)     # StepProgress
    step_done = pyqtSignal(str, bool) # (step_name, success)
    complete = pyqtSignal(object)     # OrchestratorResult

    def __init__(self, steps, hw_service, metrics_service, kwargs):
        super().__init__()
        self._steps = steps
        self._hw = hw_service
        self._metrics = metrics_service
        self._kwargs = kwargs
        self._abort = False
        self._skip_current = False

    def abort(self):
        self._abort = True

    def skip_current(self):
        self._skip_current = True

    def run(self):
        t0 = time.monotonic()
        result = OrchestratorResult(success=True)
        total = len(self._steps)

        for idx, step in enumerate(self._steps):
            if self._abort:
                result.success = False
                result.message = "Aborted by user"
                break

            self._skip_current = False
            label = _STEP_LABELS.get(step, step.value)
            self.progress.emit(StepProgress(
                current_step=step, step_label=label,
                step_index=idx, total_steps=total,
                message=f"Starting {label}…"))

            try:
                ok = self._run_step(step, result, idx, total)
            except Exception as e:
                log.exception("Orchestrator step %s failed", step.value)
                ok = False

            if self._skip_current:
                result.steps_skipped.append(step)
                self.step_done.emit(step.value, True)
                continue

            if ok:
                result.steps_completed.append(step)
            else:
                result.steps_skipped.append(step)

            self.step_done.emit(step.value, ok)

        result.duration_s = time.monotonic() - t0
        if not result.message:
            result.message = (
                f"Preparation complete — {len(result.steps_completed)}/"
                f"{total} steps passed in {result.duration_s:.1f}s")
        self.complete.emit(result)

    def _run_step(self, step, result, idx, total):
        if step == Step.AUTO_EXPOSE:
            return self._do_auto_expose(result, idx, total)
        elif step == Step.AUTO_GAIN:
            return self._do_auto_gain(result, idx, total)
        elif step == Step.TEC_PRECONDITION:
            return self._do_tec_precondition(result, idx, total)
        elif step == Step.PREFLIGHT:
            return self._do_preflight(result, idx, total)
        return True

    def _do_auto_expose(self, result, idx, total):
        from hardware.cameras.auto_exposure import auto_expose
        r = auto_expose(
            self._hw,
            target_pct=self._kwargs.get("ae_target_pct", 70.0),
            roi=self._kwargs.get("ae_roi", "center50"),
            max_iters=self._kwargs.get("ae_max_iters", 6),
        )
        result.auto_expose_result = r
        self.progress.emit(StepProgress(
            current_step=Step.AUTO_EXPOSE,
            step_label="Auto-Expose",
            step_index=idx, total_steps=total,
            step_progress=1.0,
            message=r.message))
        return r.converged

    def _do_auto_gain(self, result, idx, total):
        from hardware.cameras.auto_gain import auto_gain
        from hardware.app_state import app_state

        cam = app_state.cam
        if cam is None:
            return True   # skip silently

        def _progress(gain, snr, i, n):
            if self._abort:
                return
            self.progress.emit(StepProgress(
                current_step=Step.AUTO_GAIN,
                step_label="Auto-Gain",
                step_index=idx, total_steps=total,
                step_progress=(i + 1) / max(n, 1),
                message=f"Testing gain {gain:.1f} dB — SNR {snr:.1f} dB"))

        r = auto_gain(
            cam,
            target_snr_db=self._kwargs.get("ag_target_snr", 20.0),
            max_gain_db=self._kwargs.get("ag_max_gain", 18.0),
            progress_cb=_progress,
        )
        result.auto_gain_result = r
        self.progress.emit(StepProgress(
            current_step=Step.AUTO_GAIN,
            step_label="Auto-Gain",
            step_index=idx, total_steps=total,
            step_progress=1.0,
            message=r.message))
        return r.converged

    def _do_tec_precondition(self, result, idx, total):
        from hardware.app_state import app_state
        from hardware.tec.preconditioning import TecPreconditioning

        tecs = app_state.tecs if hasattr(app_state, 'tecs') else []
        if not tecs:
            return True   # no TECs → skip

        # Only include enabled TECs
        active = [t for t in tecs
                  if hasattr(t, 'get_status')
                  and getattr(t.get_status(), 'enabled', False)]
        if not active:
            return True

        precond = TecPreconditioning(
            active,
            tolerance_c=self._kwargs.get("tec_tolerance", 0.20),
            dwell_s=self._kwargs.get("tec_dwell", 30.0),
            timeout_s=self._kwargs.get("tec_timeout", 300.0),
        )

        def _progress(elapsed, deltas, band_times):
            if self._abort:
                precond.abort()
            msg_parts = []
            for i, (d, bt) in enumerate(zip(deltas, band_times)):
                if d is not None:
                    msg_parts.append(f"CH{i}: Δ{d:.2f}°C ({bt:.0f}s)")
            self.progress.emit(StepProgress(
                current_step=Step.TEC_PRECONDITION,
                step_label="TEC Preconditioning",
                step_index=idx, total_steps=total,
                step_progress=min(elapsed / 60.0, 0.99),
                message="  ".join(msg_parts) or "Waiting for TEC…",
                can_skip=True))

        r = precond.run(progress_cb=_progress)
        result.tec_result = r
        return r.stable or r.timed_out  # timeout is soft-fail

    def _do_preflight(self, result, idx, total):
        from hardware.app_state import app_state
        from acquisition.preflight import PreflightValidator

        metrics_snap = {}
        if self._metrics and hasattr(self._metrics, 'current_snapshot'):
            metrics_snap = self._metrics.current_snapshot()

        validator = PreflightValidator(app_state, metrics_snap)
        operation = self._kwargs.get("operation", "acquire")
        pf = validator.run(operation=operation)
        result.preflight_result = pf

        self.progress.emit(StepProgress(
            current_step=Step.PREFLIGHT,
            step_label="Preflight Validation",
            step_index=idx, total_steps=total,
            step_progress=1.0,
            message=self._preflight_summary(pf)))
        return pf.passed

    @staticmethod
    def _preflight_summary(pf) -> str:
        n_issues = sum(1 for c in pf.checks if c.status != "pass")
        if n_issues == 0:
            return "Preflight: all clear"
        return f"Preflight: {n_issues} issues"


# ── Public API ────────────────────────────────────────────────────────────────

class ReadinessOrchestrator(QObject):
    """Coordinates multi-step hardware preparation.

    Signals
    -------
    progress(StepProgress)
        Emitted during each step with progress updates.
    step_complete(str, bool)
        Emitted when a step finishes: (step_name, success).
    complete(OrchestratorResult)
        Emitted when the full sequence finishes.
    """

    progress      = pyqtSignal(object)
    step_complete = pyqtSignal(str, bool)
    complete      = pyqtSignal(object)

    def __init__(self, hw_service, metrics_service=None, parent=None):
        super().__init__(parent)
        self._hw = hw_service
        self._metrics = metrics_service
        self._worker: Optional[_Worker] = None
        self._steps: list[Step] = list(_STEP_ORDER)
        self._kwargs: dict = {}

    def configure(self, steps: list[Step] | None = None, **kwargs) -> None:
        """Select which steps to run and pass step-specific parameters.

        Parameters
        ----------
        steps : list[Step], optional
            Steps to include, in execution order.  Defaults to all.
        **kwargs
            Step-specific parameters (ae_target_pct, ag_max_gain,
            tec_timeout, operation, etc.).
        """
        if steps is not None:
            # Enforce canonical order
            self._steps = [s for s in _STEP_ORDER if s in steps]
        self._kwargs.update(kwargs)

    def start(self) -> None:
        """Launch the preparation sequence on a background thread."""
        if self._worker and self._worker.isRunning():
            log.warning("Orchestrator already running")
            return

        self._worker = _Worker(
            self._steps, self._hw, self._metrics, self._kwargs)
        self._worker.progress.connect(self.progress)
        self._worker.step_done.connect(self.step_complete)
        self._worker.complete.connect(self._on_complete)
        self._worker.start()

    def abort(self) -> None:
        """Abort the current sequence."""
        if self._worker:
            self._worker.abort()

    def skip_current_step(self) -> None:
        """Skip the currently running step."""
        if self._worker:
            self._worker.skip_current()

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _on_complete(self, result: OrchestratorResult) -> None:
        self.complete.emit(result)
        self._worker = None
