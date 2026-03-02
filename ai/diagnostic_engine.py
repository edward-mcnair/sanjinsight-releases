"""
ai/diagnostic_engine.py

DiagnosticEngine — evaluates diagnostic rules against the current instrument snapshot.

Design
------
  • Pure read layer — no Qt signals, no state, no I/O.
  • Rules live in diagnostic_rules.py as plain, testable functions.
  • evaluate() is safe to call at any frequency from any thread.

Usage
-----
    engine = DiagnosticEngine(metrics_service)

    # All results (ok / warn / fail)
    for result in engine.evaluate():
        print(result.rule_id, result.severity, result.observed)

    # Only active problems
    for issue in engine.active_issues():
        print(issue.display_name, "→", issue.hint)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai.diagnostic_rules import ALL_RULES, RuleResult

if TYPE_CHECKING:
    from ai.metrics_service import MetricsService

log = logging.getLogger(__name__)


class DiagnosticEngine:
    """
    Evaluates all registered diagnostic rules against the latest metrics snapshot.

    Parameters
    ----------
    metrics:
        Live MetricsService instance.  current_snapshot() is called on each
        evaluate() call so results are always fresh.
    """

    def __init__(self, metrics: "MetricsService") -> None:
        self._metrics = metrics

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def evaluate(self) -> list[RuleResult]:
        """
        Run all rules against the current snapshot.
        Returns a flat list of RuleResult; None returns from rules are dropped.
        Never raises — returns an empty list on snapshot failure.
        """
        try:
            snap = self._metrics.current_snapshot()
        except Exception:
            log.debug("DiagnosticEngine: snapshot failed", exc_info=True)
            return []

        results: list[RuleResult] = []
        for rule_fn in ALL_RULES:
            try:
                result = rule_fn(snap)
                if result is None:
                    continue
                if isinstance(result, list):
                    results.extend(r for r in result if r is not None)
                else:
                    results.append(result)
            except Exception:
                log.debug(
                    "DiagnosticEngine: rule %s raised an exception",
                    rule_fn.__name__, exc_info=True,
                )
        return results

    def active_issues(self) -> list[RuleResult]:
        """Return only rules with severity 'warn' or 'fail'."""
        return [r for r in self.evaluate() if r.severity != "ok"]

    def is_ready(self) -> bool:
        """True if no rule has severity 'fail'."""
        return not any(r.severity == "fail" for r in self.evaluate())
