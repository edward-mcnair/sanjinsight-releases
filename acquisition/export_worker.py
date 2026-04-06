"""
acquisition/export_worker.py

QThread worker for non-blocking session export.

Wraps ``SessionExporter.export()`` so the UI thread stays responsive
while TIFF / HDF5 / CSV / MATLAB / NPY files are written to disk.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from acquisition.storage.export import (
    ExportFormat, ExportResult, SessionExporter,
)

log = logging.getLogger(__name__)


class ExportWorker(QThread):
    """
    Runs *SessionExporter.export()* on a background thread.

    Signals
    -------
    finished : ExportResult
        Emitted when the export completes (may still contain per-format
        errors — check ``result.errors``).
    error : str
        Emitted if an unexpected exception prevents export entirely.
    progress : int
        Reserved for future per-format progress (0-100).  Currently
        emits 0 at start and 100 on completion.
    """

    finished = pyqtSignal(object)   # ExportResult
    error    = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(
        self,
        session,
        formats: List[ExportFormat],
        output_dir: str = ".",
        px_per_um: float = 0.0,
        prefix: str = "",
        analysis_result=None,
        parent=None,
    ):
        super().__init__(parent)
        self._session          = session
        self._formats          = formats
        self._output_dir       = output_dir
        self._px_per_um        = px_per_um
        self._prefix           = prefix
        self._analysis_result  = analysis_result

    # ---------------------------------------------------------------- #
    #  Thread entry point                                               #
    # ---------------------------------------------------------------- #

    def run(self):  # noqa: D401 — Qt override
        try:
            self.progress.emit(0)
            exporter = SessionExporter(
                session=self._session,
                output_dir=self._output_dir,
                px_per_um=self._px_per_um,
                prefix=self._prefix,
                analysis_result=self._analysis_result,
            )
            result = exporter.export(self._formats)
            self.progress.emit(100)
            self.finished.emit(result)
        except Exception as exc:
            log.exception("ExportWorker failed")
            self.error.emit(str(exc))
