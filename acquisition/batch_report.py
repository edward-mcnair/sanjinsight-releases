"""
acquisition/batch_report.py  —  Multi-session report generation

Generates one report per session in a background thread, emitting
progress updates as each report completes.  Follows the same pattern
as ``BatchAnalysisWorker`` in ``batch_reprocessor.py``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


# ── Result dataclasses ─────────────────────────────────────────────

@dataclass
class BatchReportUpdate:
    """Progress / result for one session's report."""
    uid: str
    label: str
    success: bool
    error: str = ""
    report_path: str = ""
    duration_s: float = 0.0


@dataclass
class BatchReportResult:
    """Summary of a completed batch run."""
    total: int
    ok: int
    failed: int
    duration_s: float
    report_paths: List[str] = field(default_factory=list)


# ── Generator ──────────────────────────────────────────────────────

class BatchReportGenerator:
    """Generates reports for multiple sessions (single-threaded iterator)."""

    def __init__(self, session_manager):
        self._mgr = session_manager

    def generate(
        self,
        uids: List[str],
        report_config,
        output_dir: str,
        calibration=None,
    ) -> Iterator[BatchReportUpdate]:
        """Yield a ``BatchReportUpdate`` for each session."""
        for uid in uids:
            meta = self._mgr.get_meta(uid)
            label = meta.label if meta else uid
            yield self._generate_one(uid, label, report_config,
                                     output_dir, calibration)

    def _generate_one(
        self, uid: str, label: str, report_config,
        output_dir: str, calibration,
    ) -> BatchReportUpdate:
        t0 = time.monotonic()
        try:
            session = self._mgr.load(uid)
            if session is None:
                return BatchReportUpdate(uid, label, success=False,
                                         error="Session not found")

            # Load persisted analysis + scorecard
            analysis = session.load_analysis()
            scorecard = session.meta.quality_scorecard

            from .report import generate_report_any_format
            path = generate_report_any_format(
                session,
                output_dir=output_dir,
                calibration=calibration,
                analysis=analysis,
                report_config=report_config,
                quality_scorecard=scorecard,
            )
            dt = time.monotonic() - t0
            return BatchReportUpdate(uid, label, success=True,
                                     report_path=path, duration_s=dt)
        except Exception as exc:
            dt = time.monotonic() - t0
            log.warning("Batch report failed for %s: %s", uid, exc,
                        exc_info=True)
            return BatchReportUpdate(uid, label, success=False,
                                     error=str(exc), duration_s=dt)


# ── QThread wrapper ────────────────────────────────────────────────

class BatchReportWorker(QThread):
    """Runs batch report generation in a background thread."""

    progress = pyqtSignal(object)   # BatchReportUpdate
    finished = pyqtSignal(object)   # BatchReportResult

    def __init__(
        self,
        session_manager,
        uids: List[str],
        report_config,
        output_dir: str,
        calibration=None,
        parent=None,
    ):
        super().__init__(parent)
        self._mgr = session_manager
        self._uids = uids
        self._config = report_config
        self._output_dir = output_dir
        self._calibration = calibration
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        t0 = time.monotonic()
        gen = BatchReportGenerator(self._mgr)
        ok = 0
        failed = 0
        paths: list[str] = []
        for update in gen.generate(self._uids, self._config,
                                   self._output_dir, self._calibration):
            if self._abort:
                break
            if update.success:
                ok += 1
                paths.append(update.report_path)
            else:
                failed += 1
            self.progress.emit(update)
        dt = time.monotonic() - t0
        self.finished.emit(BatchReportResult(
            total=len(self._uids), ok=ok, failed=failed,
            duration_s=dt, report_paths=paths))
