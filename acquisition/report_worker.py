"""
acquisition/report_worker.py

QThread worker for non-blocking report generation.

Wraps ``generate_report_any_format()`` so the UI thread stays
responsive while PDF / HTML reports are rendered.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class ReportWorker(QThread):
    """
    Runs *generate_report_any_format()* on a background thread.

    Signals
    -------
    finished : str
        Emitted with the absolute path to the generated report file.
    error : str
        Emitted if report generation fails.
    progress : int
        Reserved for future granular progress (0-100).  Currently
        emits 0 at start and 100 on completion.
    """

    finished = pyqtSignal(str)   # output path
    error    = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(
        self,
        session,
        output_dir: str = ".",
        calibration=None,
        analysis=None,
        report_config=None,
        quality_scorecard=None,
        parent=None,
    ):
        super().__init__(parent)
        self._session           = session
        self._output_dir        = output_dir
        self._calibration       = calibration
        self._analysis          = analysis
        self._report_config     = report_config
        self._quality_scorecard = quality_scorecard

    # ---------------------------------------------------------------- #
    #  Thread entry point                                               #
    # ---------------------------------------------------------------- #

    def run(self):  # noqa: D401 — Qt override
        try:
            self.progress.emit(0)
            from acquisition.reporting.report import generate_report_any_format

            path = generate_report_any_format(
                self._session,
                output_dir=self._output_dir,
                calibration=self._calibration,
                analysis=self._analysis,
                report_config=self._report_config,
                quality_scorecard=self._quality_scorecard,
            )
            self.progress.emit(100)
            self.finished.emit(path)
        except Exception as exc:
            log.exception("ReportWorker failed")
            self.error.emit(str(exc))
