"""
acquisition/recipe_executor.py  —  Recipe execution engine

Orchestrates the sequential execution of a Recipe's phases.
Each enabled phase is dispatched to its handler via the registry.

The executor is a plain Python object — no Qt dependency.  The
RecipeExecutor owns the ExecutionContext and manages:

  - phase ordering and skip/disable logic
  - precondition checks before each phase
  - retry policy (backoff, max attempts, on_exhaust action)
  - per-phase timeout enforcement
  - abort handling (cooperative via ExecutionContext.abort_requested)
  - result accumulation into an ExecutionResult

Threading
---------
The executor's ``run()`` is a blocking call.  The caller (typically
a QThread worker) is responsible for running it off the main thread
and connecting the ``on_progress`` callback to a Qt signal.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from acquisition.phase_handlers import (
    AbortError,
    ExecutionContext,
    PhaseResult,
    PhaseStatus,
    get_handler,
)
from acquisition.recipe import Recipe, RecipePhase

log = logging.getLogger(__name__)


# ================================================================== #
#  Execution result                                                    #
# ================================================================== #

@dataclass
class ExecutionResult:
    """Aggregate outcome of running a complete recipe.

    Attributes
    ----------
    recipe_uid : str
        UID of the recipe that was executed.
    recipe_label : str
        Human-readable label.
    status : str
        Overall status: "success", "failed", "aborted", "partial".
    phase_results : list[PhaseResult]
        Result of each phase that was attempted.
    duration_s : float
        Wall-clock time for the full run.
    message : str
        Summary message (empty on clean success).
    """
    recipe_uid:    str = ""
    recipe_label:  str = ""
    status:        str = "success"
    phase_results: List[PhaseResult] = field(default_factory=list)
    duration_s:    float = 0.0
    message:       str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def failed_phases(self) -> List[PhaseResult]:
        return [pr for pr in self.phase_results
                if pr.status == PhaseStatus.FAILED.value]


# ================================================================== #
#  Recipe executor                                                     #
# ================================================================== #

class RecipeExecutor:
    """Execute a Recipe by running its phases in order.

    Parameters
    ----------
    recipe : Recipe
        The recipe to execute.
    app_state : object
        The ApplicationState singleton (live hardware references).
    on_progress : callable, optional
        ``(message: str) -> None`` callback for status updates.
    """

    def __init__(
        self,
        recipe: Recipe,
        app_state: Any = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self._recipe = recipe
        self._ctx = ExecutionContext(
            app_state=app_state,
            on_progress=on_progress,
        )

    # ── Public API ─────────────────────────────────────────────────

    @property
    def context(self) -> ExecutionContext:
        """Access the execution context (for post-run inspection)."""
        return self._ctx

    def abort(self) -> None:
        """Request cooperative cancellation."""
        self._ctx.abort_requested = True

    def run(self) -> ExecutionResult:
        """Execute all enabled phases sequentially.

        Returns an ExecutionResult with per-phase outcomes.
        This is a blocking call — run from a worker thread.
        """
        t0 = time.monotonic()
        result = ExecutionResult(
            recipe_uid=self._recipe.uid,
            recipe_label=self._recipe.label,
        )

        enabled_phases = [p for p in self._recipe.phases if p.enabled]
        if not enabled_phases:
            result.status = "success"
            result.message = "No enabled phases"
            result.duration_s = time.monotonic() - t0
            return result

        self._ctx.report(f"Starting recipe: {self._recipe.label}")

        try:
            for phase in enabled_phases:
                self._ctx.check_abort()
                pr = self._execute_phase(phase)
                result.phase_results.append(pr)

                if pr.status == PhaseStatus.FAILED.value:
                    # Check retry policy
                    retried, final_pr = self._retry_phase(phase)
                    if retried:
                        # Replace the failed result with the successful one
                        result.phase_results[-1] = final_pr
                        continue
                    else:
                        # on_exhaust determines what happens
                        action = phase.retry.on_exhaust
                        if action == "abort":
                            result.status = "failed"
                            result.message = (
                                f"Phase '{phase.phase_type}' failed: "
                                f"{pr.message}")
                            break
                        elif action == "skip":
                            self._ctx.report(
                                f"Skipping failed phase: {phase.phase_type}")
                            continue
                        else:  # warn_continue
                            self._ctx.report(
                                f"Continuing despite failure in "
                                f"{phase.phase_type}")
                            continue

                elif pr.status == PhaseStatus.ABORTED.value:
                    result.status = "aborted"
                    result.message = "Execution aborted by user"
                    break

        except AbortError:
            result.status = "aborted"
            result.message = "Execution aborted by user"
            self._ctx.report("Execution aborted")

        except Exception as exc:
            log.exception("Unexpected error during recipe execution")
            result.status = "failed"
            result.message = f"Unexpected error: {exc}"

        # Determine final status if not already set to failed/aborted
        if result.status == "success":
            result.status = self._compute_overall_status(result.phase_results)

        result.duration_s = time.monotonic() - t0
        self._ctx.report(
            f"Recipe complete: {result.status} "
            f"({result.duration_s:.1f}s)")
        return result

    # ── Phase execution ────────────────────────────────────────────

    def _execute_phase(self, phase: RecipePhase) -> PhaseResult:
        """Execute a single phase with its handler."""
        handler = get_handler(phase.phase_type)
        if handler is None:
            log.warning("No handler for phase type: %s", phase.phase_type)
            return PhaseResult(
                phase_type=phase.phase_type,
                status=PhaseStatus.SKIPPED.value,
                message=f"No handler for '{phase.phase_type}'",
            )

        self._ctx.report(f"Phase: {phase.phase_type}")

        # Timeout enforcement
        if phase.timeout_s > 0:
            return self._execute_with_timeout(handler, phase)

        try:
            return handler.execute(phase.config, self._ctx)
        except AbortError:
            raise
        except Exception as exc:
            log.exception("Phase %s raised", phase.phase_type)
            return PhaseResult(
                phase_type=phase.phase_type,
                status=PhaseStatus.FAILED.value,
                message=str(exc),
            )

    def _execute_with_timeout(
        self, handler, phase: RecipePhase
    ) -> PhaseResult:
        """Execute a phase handler with a wall-clock timeout.

        Since execution is single-threaded (blocking), we can only
        enforce the timeout after the handler returns.  True
        preemptive timeout requires threading — that is deferred
        to the QThread integration layer.
        """
        t0 = time.monotonic()
        try:
            result = handler.execute(phase.config, self._ctx)
        except AbortError:
            raise
        except Exception as exc:
            log.exception("Phase %s raised", phase.phase_type)
            result = PhaseResult(
                phase_type=phase.phase_type,
                status=PhaseStatus.FAILED.value,
                message=str(exc),
            )

        elapsed = time.monotonic() - t0
        if elapsed > phase.timeout_s:
            result.status = PhaseStatus.FAILED.value
            result.message = (
                f"Phase exceeded timeout "
                f"({elapsed:.1f}s > {phase.timeout_s:.1f}s)"
            )

        return result

    # ── Retry logic ────────────────────────────────────────────────

    def _retry_phase(
        self, phase: RecipePhase,
    ) -> tuple:
        """Retry a failed phase according to its RetryPolicy.

        Returns (True, PhaseResult) if a retry succeeded,
        or (False, None) if retries exhausted or not configured.
        """
        policy = phase.retry
        if policy.max_retries <= 0:
            return False, None

        for attempt in range(1, policy.max_retries + 1):
            self._ctx.check_abort()

            backoff = policy.backoff_s * attempt
            self._ctx.report(
                f"Retry {attempt}/{policy.max_retries} for "
                f"{phase.phase_type} (backoff {backoff:.1f}s)")

            # Interruptible backoff
            end = time.monotonic() + backoff
            while time.monotonic() < end:
                self._ctx.check_abort()
                remaining = end - time.monotonic()
                time.sleep(min(0.25, max(0, remaining)))

            pr = self._execute_phase(phase)

            if pr.status != PhaseStatus.FAILED.value:
                self._ctx.report(
                    f"Phase {phase.phase_type} succeeded on retry {attempt}")
                return True, pr

        self._ctx.report(
            f"Phase {phase.phase_type} failed after "
            f"{policy.max_retries} retries")
        return False, None

    # ── Status computation ─────────────────────────────────────────

    @staticmethod
    def _compute_overall_status(phase_results: List[PhaseResult]) -> str:
        """Derive overall status from individual phase results."""
        if not phase_results:
            return "success"

        statuses = {pr.status for pr in phase_results}

        if PhaseStatus.FAILED.value in statuses:
            return "failed"
        if PhaseStatus.ABORTED.value in statuses:
            return "aborted"
        if PhaseStatus.WARNING.value in statuses:
            return "partial"

        return "success"
