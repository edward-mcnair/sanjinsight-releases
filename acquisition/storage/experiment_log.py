"""
acquisition/storage/experiment_log.py  —  Structured experiment run log

Append-only log of acquisition runs with automatic ROI/analysis recording.
Every recipe run or manually-analysed acquisition appends a RunEntry.

Dual persistence:
  - JSON  (full fidelity, machine-readable)
  - CSV   (flat, opens in Excel / Google Sheets)

Both files live at ``~/.microsanj/experiment_log.{json,csv}``.

Design principles (v1):
  - Append-only: entries are never modified after creation
  - Stable schema: SCHEMA_VERSION tracks breaking changes
  - Session linkage: every entry carries the session UID for drill-down
  - Recipe + manual: ``source`` field distinguishes recipe runs from
    manual acquisitions that were analysed after the fact
  - Thread-safe: all mutations go through a lock
  - Bounded: MAX_ENTRIES cap with oldest-first eviction on save
  - Atomic writes: JSON uses temp+fsync+rename via utils.atomic_write_json

v2 deferred:
  - Custom / user-defined columns
  - Calculated / derived columns
  - Excel (.xlsx) export
  - Date-range filtering in the data layer (v1 exposes hooks; UI filters)
  - Column reordering / hide preferences
  - Comparison report generation from selected entries
  - Per-project or per-recipe sub-logs
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Sequence

from utils import atomic_write_json, atomic_write

log = logging.getLogger(__name__)

# Schema version — bump on breaking field changes
SCHEMA_VERSION = 1

# Maximum retained entries (oldest evicted first on save)
MAX_ENTRIES = 10_000

# ── CSV column order (stable — append new columns at the end) ────────
CSV_COLUMNS = [
    "entry_uid",
    "timestamp",
    "source",
    "recipe_uid",
    "recipe_label",
    "modality",
    "session_uid",
    "session_label",
    "operator",
    "device_id",
    "project",
    "n_frames",
    "exposure_us",
    "gain_db",
    "roi_peak_k",
    "roi_mean_k",
    "roi_max_delta_t_k",
    "roi_area_px",
    "roi_area_fraction",
    "verdict",
    "hotspot_count",
    "outcome",
    "duration_s",
    "analysis_skipped",
    "notes",
    "test_variables",
]


# ── RunEntry dataclass ───────────────────────────────────────────────

@dataclass
class RunEntry:
    """One row in the experiment log.

    Represents a single acquisition run (recipe or manual) with its
    analysis results.  Designed to be flat enough for CSV export while
    preserving structured data (test_variables) in the JSON form.

    Fields are grouped into:
      Identity — who, when, what triggered it
      Acquisition — camera/modality snapshot
      ROI / Analysis — the "auto-recorded ROI data" James requested
      Outcome — verdict, timing, operator notes
    """

    # ── Identity ─────────────────────────────────────────────────────
    entry_uid: str = ""                 # auto-generated if empty
    timestamp: str = ""                 # ISO-8601 UTC, auto-set if empty

    # ── Source ───────────────────────────────────────────────────────
    source: str = "manual"              # "recipe" | "manual"
    recipe_uid: str = ""                # populated when source == "recipe"
    recipe_label: str = ""              # human-readable recipe name

    # ── Test variables (recipe run-time inputs) ──────────────────────
    # Dict of {variable_name: value} filled by the operator at run time.
    # Empty for manual acquisitions.  Stored as JSON object; flattened
    # to a JSON string in the CSV column.
    test_variables: Dict[str, Any] = field(default_factory=dict)

    # ── Acquisition context ──────────────────────────────────────────
    modality: str = ""                  # e.g. "thermoreflectance", "infrared"
    session_uid: str = ""               # links to session for drill-down
    session_label: str = ""             # human-readable session label
    operator: str = ""                  # who ran it
    device_id: str = ""                 # DUT identifier
    project: str = ""                   # project/lot name

    # ── Acquisition params (snapshot) ────────────────────────────────
    n_frames: int = 0
    exposure_us: float = 0.0
    gain_db: float = 0.0

    # ── ROI / Analysis results ───────────────────────────────────────
    # These are the "automatically records ROI and other data" fields.
    # Populated from AnalysisResult when analysis runs; None when
    # analysis is skipped or not applicable.
    roi_peak_k: Optional[float] = None       # peak ΔT in ROI (K)
    roi_mean_k: Optional[float] = None       # mean ΔT in ROI (K)
    roi_max_delta_t_k: Optional[float] = None  # max hotspot ΔT (K)
    roi_area_px: Optional[int] = None        # total hotspot area (px)
    roi_area_fraction: Optional[float] = None  # hotspot area / total area

    # ── Verdict ──────────────────────────────────────────────────────
    verdict: str = ""                   # "pass" | "warning" | "fail" | ""
    hotspot_count: int = 0

    # ── Outcome ──────────────────────────────────────────────────────
    outcome: str = ""                   # "complete" | "error" | "aborted"
    duration_s: float = 0.0             # wall-clock acquisition time
    analysis_skipped: bool = False      # True when "bypass analyser" used
    notes: str = ""                     # operator notes (free text)

    def __post_init__(self):
        if not self.entry_uid:
            self.entry_uid = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    # ── Serialisation ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict of all fields."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunEntry":
        """Construct from a dict, ignoring unknown keys gracefully."""
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def to_csv_row(self) -> Dict[str, str]:
        """Return a flat dict suitable for csv.DictWriter.

        - None values become empty strings
        - test_variables dict is serialised as a JSON string
        - Floats are formatted to reasonable precision
        """
        row: Dict[str, str] = {}
        for col in CSV_COLUMNS:
            val = getattr(self, col, "")
            if val is None:
                row[col] = ""
            elif col == "test_variables":
                row[col] = json.dumps(val) if val else ""
            elif isinstance(val, float):
                row[col] = f"{val:.6g}"
            elif isinstance(val, bool):
                row[col] = str(val)
            else:
                row[col] = str(val)
        return row


# ── Factory helpers ──────────────────────────────────────────────────

def make_entry(
    *,
    source: str = "manual",
    recipe_uid: str = "",
    recipe_label: str = "",
    test_variables: Optional[Dict[str, Any]] = None,
    modality: str = "",
    session_uid: str = "",
    session_label: str = "",
    operator: str = "",
    device_id: str = "",
    project: str = "",
    n_frames: int = 0,
    exposure_us: float = 0.0,
    gain_db: float = 0.0,
    outcome: str = "complete",
    duration_s: float = 0.0,
    analysis_skipped: bool = False,
    notes: str = "",
    analysis_result: Optional[Any] = None,
) -> RunEntry:
    """Create a RunEntry, populating ROI fields from an AnalysisResult.

    Parameters
    ----------
    analysis_result
        An AnalysisResult object (or any object with .verdict, .hotspots,
        .max_peak_k, .total_area_px, .area_fraction, .map_mean_k attrs).
        If None or analysis_skipped is True, ROI fields remain None.
    """
    entry = RunEntry(
        source=source,
        recipe_uid=recipe_uid,
        recipe_label=recipe_label,
        test_variables=test_variables or {},
        modality=modality,
        session_uid=session_uid,
        session_label=session_label,
        operator=operator,
        device_id=device_id,
        project=project,
        n_frames=n_frames,
        exposure_us=exposure_us,
        gain_db=gain_db,
        outcome=outcome,
        duration_s=duration_s,
        analysis_skipped=analysis_skipped,
        notes=notes,
    )

    # Populate ROI fields from AnalysisResult when available
    if analysis_result is not None and not analysis_skipped:
        ar = analysis_result
        entry.verdict = getattr(ar, "verdict", "") or ""
        entry.hotspot_count = len(getattr(ar, "hotspots", []))
        entry.roi_peak_k = getattr(ar, "max_peak_k", None)
        entry.roi_mean_k = getattr(ar, "map_mean_k", None)
        entry.roi_area_px = getattr(ar, "total_area_px", None)
        entry.roi_area_fraction = getattr(ar, "area_fraction", None)

        # max_delta_t from highest-severity hotspot
        hotspots = getattr(ar, "hotspots", [])
        if hotspots:
            entry.roi_max_delta_t_k = max(
                getattr(h, "peak_k", 0.0) for h in hotspots
            )

    return entry


# ── ExperimentLog (persistence layer) ────────────────────────────────

class ExperimentLog:
    """Append-only experiment log with dual JSON + CSV persistence.

    Thread-safe.  All public methods acquire the internal lock.

    Parameters
    ----------
    log_dir : str
        Directory for ``experiment_log.json`` and ``experiment_log.csv``.
        Typically ``~/.microsanj/``.
    """

    def __init__(self, log_dir: str = "") -> None:
        self._dir = log_dir
        self._lock = threading.RLock()

    # ── Path helpers ─────────────────────────────────────────────────

    @property
    def json_path(self) -> str:
        return os.path.join(self._dir, "experiment_log.json") if self._dir else ""

    @property
    def csv_path(self) -> str:
        return os.path.join(self._dir, "experiment_log.csv") if self._dir else ""

    # ── Core operations ──────────────────────────────────────────────

    def append(self, entry: RunEntry) -> None:
        """Append a single entry and persist to both JSON and CSV."""
        with self._lock:
            entries = self._load_json()
            entries.append(entry.to_dict())
            self._save_json(entries)
            self._append_csv(entry)

    def all_entries(self) -> List[RunEntry]:
        """Return all entries, oldest first."""
        with self._lock:
            return [RunEntry.from_dict(d) for d in self._load_json()]

    def recent(self, n: int = 50) -> List[RunEntry]:
        """Return the most recent N entries, newest first."""
        with self._lock:
            raw = self._load_json()
            return [RunEntry.from_dict(d) for d in reversed(raw[-n:])]

    def count(self) -> int:
        """Return total number of entries."""
        with self._lock:
            return len(self._load_json())

    # ── Query hooks (v1 — simple, in-memory filtering) ───────────────

    def find(
        self,
        *,
        source: Optional[str] = None,
        recipe_uid: Optional[str] = None,
        verdict: Optional[str] = None,
        modality: Optional[str] = None,
        operator: Optional[str] = None,
        device_id: Optional[str] = None,
        project: Optional[str] = None,
        session_uid: Optional[str] = None,
        limit: int = 0,
    ) -> List[RunEntry]:
        """Filter entries by field values.  All filters are AND-combined.

        Parameters
        ----------
        limit : int
            Maximum entries to return (0 = unlimited).  Applied after
            filtering, newest first.

        Returns
        -------
        List of matching RunEntry objects, newest first.
        """
        with self._lock:
            raw = self._load_json()

        results: List[RunEntry] = []
        for d in reversed(raw):
            if source is not None and d.get("source") != source:
                continue
            if recipe_uid is not None and d.get("recipe_uid") != recipe_uid:
                continue
            if verdict is not None and d.get("verdict") != verdict:
                continue
            if modality is not None and d.get("modality") != modality:
                continue
            if operator is not None and d.get("operator") != operator:
                continue
            if device_id is not None and d.get("device_id") != device_id:
                continue
            if project is not None and d.get("project") != project:
                continue
            if session_uid is not None and d.get("session_uid") != session_uid:
                continue
            results.append(RunEntry.from_dict(d))
            if limit and len(results) >= limit:
                break
        return results

    # ── Export ────────────────────────────────────────────────────────

    def export_csv(self, path: str) -> int:
        """Write all entries to a CSV file at *path*.

        Returns the number of rows written.  This is a full rewrite
        (not append), suitable for "Export to CSV" user action.
        """
        with self._lock:
            entries = self._load_json()

        def _write(f):
            writer = csv.DictWriter(
                f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for d in entries:
                try:
                    entry = RunEntry.from_dict(d)
                    writer.writerow(entry.to_csv_row())
                except Exception:
                    log.debug("Skipped malformed entry during CSV export",
                              exc_info=True)
            return len(entries)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        count = 0
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for d in entries:
                try:
                    entry = RunEntry.from_dict(d)
                    writer.writerow(entry.to_csv_row())
                    count += 1
                except Exception:
                    log.debug("Skipped malformed entry during CSV export",
                              exc_info=True)
        return count

    # ── JSON persistence ─────────────────────────────────────────────

    def _load_json(self) -> List[dict]:
        """Load the JSON log.  Returns [] on missing or corrupt file."""
        path = self.json_path
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            if data.get("schema_version", 1) > SCHEMA_VERSION:
                log.warning(
                    "experiment_log.json schema %s > supported %s — "
                    "refusing to load (data written by newer app version)",
                    data.get("schema_version"), SCHEMA_VERSION)
                return []
            entries = data.get("entries", [])
            return entries if isinstance(entries, list) else []
        except Exception:
            log.debug("Failed to load experiment log JSON", exc_info=True)
            return []

    def _save_json(self, entries: List[dict]) -> None:
        """Atomically save the JSON log, capping at MAX_ENTRIES."""
        path = self.json_path
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        # Evict oldest entries if over cap
        capped = entries[-MAX_ENTRIES:]

        envelope = {
            "schema_version": SCHEMA_VERSION,
            "entry_count": len(capped),
            "entries": capped,
        }
        try:
            atomic_write_json(path, envelope)
        except Exception:
            log.debug("Failed to save experiment log JSON", exc_info=True)

    # ── CSV persistence (append-only) ────────────────────────────────

    def _append_csv(self, entry: RunEntry) -> None:
        """Append a single row to the CSV file.

        Creates the file with headers if it doesn't exist.
        The CSV is a convenience mirror — JSON is the source of truth.
        If the CSV drifts (manual edits, corruption), it can be
        regenerated from JSON via ``export_csv(self.csv_path)``.
        """
        path = self.csv_path
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                if write_header:
                    writer.writeheader()
                writer.writerow(entry.to_csv_row())
        except Exception:
            log.debug("Failed to append to experiment log CSV", exc_info=True)

    # ── Maintenance ──────────────────────────────────────────────────

    def rebuild_csv(self) -> int:
        """Regenerate the CSV file from the JSON source of truth.

        Returns the number of rows written.
        """
        return self.export_csv(self.csv_path)

    def clear(self) -> None:
        """Remove all entries from both JSON and CSV.

        Use with caution — this is irreversible.
        """
        with self._lock:
            self._save_json([])
            path = self.csv_path
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    log.debug("Failed to remove CSV file", exc_info=True)
