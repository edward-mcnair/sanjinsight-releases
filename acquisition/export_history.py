"""
acquisition/export_history.py  —  Persistent log of export/report/package actions

A simple JSON-array file at ``<sessions_root>/.export_history.json``
capped at MAX_ENTRIES.  Each entry records what was exported, when,
and where the output went.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class ExportRecord:
    """One export/report/package action."""
    timestamp: str          # ISO-8601
    session_uid: str
    session_label: str
    action: str             # "export", "report", "package"
    format: str             # "tiff+csv", "pdf", "html", "zip"
    output_path: str
    success: bool
    error: str = ""


class ExportHistory:
    """Persists recent export/report activity to a JSON file."""

    MAX_ENTRIES = 200

    def __init__(self, history_path: str = ""):
        self._path = history_path

    @property
    def path(self) -> str:
        return self._path

    @path.setter
    def path(self, value: str):
        self._path = value

    def _load(self) -> List[dict]:
        if not self._path or not os.path.isfile(self._path):
            return []
        try:
            with open(self._path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, records: List[dict]):
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        try:
            with open(self._path, "w") as f:
                json.dump(records[-self.MAX_ENTRIES:], f, indent=1)
        except Exception:
            log.debug("Failed to save export history", exc_info=True)

    def add(self, record: ExportRecord) -> None:
        """Append a record to the history."""
        records = self._load()
        records.append(asdict(record))
        self._save(records)

    def recent(self, n: int = 50) -> List[ExportRecord]:
        """Return the most recent N records, newest first."""
        records = self._load()
        out: List[ExportRecord] = []
        for d in reversed(records[-n:]):
            try:
                out.append(ExportRecord(**d))
            except Exception:
                continue
        return out

    def clear(self) -> None:
        """Delete all history entries."""
        self._save([])


def make_record(
    session_uid: str,
    session_label: str,
    action: str,
    fmt: str,
    output_path: str,
    success: bool,
    error: str = "",
) -> ExportRecord:
    """Convenience factory with auto-timestamping."""
    return ExportRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_uid=session_uid,
        session_label=session_label,
        action=action,
        format=fmt,
        output_path=output_path,
        success=success,
        error=error,
    )
