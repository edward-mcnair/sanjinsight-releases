"""
acquisition/calibration_library.py

Named calibration library for SanjINSIGHT.

Engineers create and save calibrations under descriptive names; analysts
and technicians load the right one by name, device_id, or temperature
range without manually hunting for .npz files.

Storage
-------
Individual calibrations  : ~/.microsanj/calibrations/<name>.npz
Index (fast lookup)      : ~/.microsanj/calibrations/index.json

Index entry fields
------------------
name        : str   — unique key, slug-normalised (lowercase, hyphens)
display_name: str   — original un-normalised name
device_id   : str   — camera / instrument identifier, "" if unspecified
t_min       : float — minimum temperature in calibration range (°C)
t_max       : float — maximum temperature in calibration range (°C)
n_points    : int   — number of temperature points in the calibration
timestamp   : float — Unix timestamp of the calibration run
timestamp_str: str  — human-readable ISO timestamp
notes       : str   — free-text notes from the engineer
path        : str   — absolute path to the .npz file

Usage
-----
    from acquisition.calibration_library import CalibrationLibrary

    lib = CalibrationLibrary()

    # Save a calibration
    lib.save(cal_result, name="GaN Basler 25°C", device_id="basler_001")

    # List all calibrations
    entries = lib.list()

    # Load by name
    cal = lib.load("GaN Basler 25°C")

    # Auto-match by device + temperature
    cal = lib.best_match(device_id="basler_001", temperature_c=25.0)
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional

from acquisition.calibration.calibration import CalibrationResult

log = logging.getLogger(__name__)

_CAL_DIR = Path.home() / ".microsanj" / "calibrations"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """
    Convert a display name to a filesystem-safe slug.
    e.g. "GaN Basler 25°C" → "gan-basler-25c"
    """
    s = name.lower()
    s = re.sub(r"[°%/\\]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unnamed"


# ── CalibrationEntry ─────────────────────────────────────────────────────────

class CalibrationEntry:
    """Metadata for one calibration in the library (no array data loaded)."""

    __slots__ = (
        "name", "display_name", "device_id",
        "t_min", "t_max", "n_points",
        "timestamp", "timestamp_str", "notes", "path",
    )

    def __init__(
        self,
        name:          str,
        display_name:  str,
        device_id:     str   = "",
        t_min:         float = 0.0,
        t_max:         float = 0.0,
        n_points:      int   = 0,
        timestamp:     float = 0.0,
        timestamp_str: str   = "",
        notes:         str   = "",
        path:          str   = "",
    ) -> None:
        self.name          = name
        self.display_name  = display_name
        self.device_id     = device_id
        self.t_min         = t_min
        self.t_max         = t_max
        self.n_points      = n_points
        self.timestamp     = timestamp
        self.timestamp_str = timestamp_str
        self.notes         = notes
        self.path          = path

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @staticmethod
    def from_dict(d: dict) -> "CalibrationEntry":
        return CalibrationEntry(**{k: d[k] for k in CalibrationEntry.__slots__ if k in d})

    def __repr__(self) -> str:
        return (
            f"<CalibrationEntry {self.display_name!r} "
            f"device={self.device_id!r} "
            f"T={self.t_min:.1f}–{self.t_max:.1f}°C "
            f"pts={self.n_points}>"
        )


# ── CalibrationLibrary ───────────────────────────────────────────────────────

class CalibrationLibrary:
    """
    Named persistent store for CalibrationResult objects.

    Thread-safe for concurrent reads; writes are serialised by the GIL
    (sufficient for a single-process desktop app).
    """

    def __init__(self, cal_dir: Path = _CAL_DIR) -> None:
        self._dir   = cal_dir
        self._index_path = cal_dir / "index.json"
        self._index: dict[str, CalibrationEntry] = {}
        self._load_index()

    # ── Index persistence ─────────────────────────────────────────────

    def _load_index(self) -> None:
        """Load the index from disk; create an empty one if absent."""
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._index = {
                    k: CalibrationEntry.from_dict(v)
                    for k, v in raw.items()
                }
                log.debug("CalibrationLibrary: loaded %d entries", len(self._index))
            except Exception:
                log.exception("CalibrationLibrary: failed to load index %s",
                              self._index_path)
                self._index = {}
        else:
            self._index = {}

    def _save_index(self) -> None:
        """Persist the index to disk."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(
                    {k: v.to_dict() for k, v in self._index.items()},
                    f, indent=2,
                )
        except Exception:
            log.exception("CalibrationLibrary: failed to save index")

    # ── Public API ────────────────────────────────────────────────────

    def save(
        self,
        cal:         CalibrationResult,
        name:        str,
        device_id:   str = "",
        notes:       str = "",
        overwrite:   bool = False,
    ) -> CalibrationEntry:
        """
        Save a CalibrationResult under *name*.

        Parameters
        ----------
        cal        : Fitted CalibrationResult (must have valid=True).
        name       : Human-readable display name, e.g. "GaN Basler 25°C".
        device_id  : Camera or instrument identifier for auto-matching.
        notes      : Optional free-text description.
        overwrite  : If False (default), raises ValueError if the name
                     already exists in the library.

        Returns
        -------
        CalibrationEntry  — the newly created index entry.
        """
        if not cal.valid:
            raise ValueError("Cannot save an invalid calibration.")

        slug = _slugify(name)
        if slug in self._index and not overwrite:
            raise ValueError(
                f"A calibration named {name!r} (slug={slug!r}) already "
                f"exists. Pass overwrite=True to replace it."
            )

        self._dir.mkdir(parents=True, exist_ok=True)
        npz_path = self._dir / f"{slug}.npz"
        cal.notes = notes or cal.notes
        cal.save(str(npz_path.with_suffix("")))   # save() appends .npz itself

        ts_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(cal.timestamp or time.time())
        )
        entry = CalibrationEntry(
            name          = slug,
            display_name  = name,
            device_id     = device_id,
            t_min         = cal.t_min,
            t_max         = cal.t_max,
            n_points      = cal.n_points,
            timestamp     = cal.timestamp or time.time(),
            timestamp_str = ts_str,
            notes         = cal.notes,
            path          = str(npz_path),
        )
        self._index[slug] = entry
        self._save_index()
        log.info("CalibrationLibrary: saved %r (device=%r, T=%.1f–%.1f°C)",
                 name, device_id, cal.t_min, cal.t_max)
        return entry

    def list(self, device_id: str = "") -> List[CalibrationEntry]:
        """
        Return all calibration entries, newest first.

        If *device_id* is non-empty, returns only entries whose
        device_id matches (exact, case-insensitive) or is empty.
        """
        entries = sorted(
            self._index.values(),
            key=lambda e: e.timestamp,
            reverse=True,
        )
        if device_id:
            entries = [
                e for e in entries
                if not e.device_id
                or e.device_id.lower() == device_id.lower()
            ]
        return entries

    def get_entry(self, name: str) -> Optional[CalibrationEntry]:
        """Return the index entry for *name* (slug or display name), or None."""
        slug = _slugify(name)
        return self._index.get(slug)

    def load(self, name: str) -> Optional[CalibrationResult]:
        """
        Load and return a CalibrationResult by display name or slug.
        Returns None if the name is not found or the .npz is missing.
        """
        entry = self.get_entry(name)
        if entry is None:
            log.warning("CalibrationLibrary: %r not found in index", name)
            return None
        path = Path(entry.path)
        if not path.exists():
            log.warning("CalibrationLibrary: .npz missing for %r: %s",
                        name, path)
            return None
        try:
            cal = CalibrationResult.load(str(path))
            return cal
        except Exception:
            log.exception("CalibrationLibrary: failed to load %s", path)
            return None

    def best_match(
        self,
        device_id:     str   = "",
        temperature_c: float = 25.0,
    ) -> Optional[CalibrationResult]:
        """
        Return the best matching calibration for *device_id* at *temperature_c*.

        Scoring:
          1. Exact device_id match preferred over generic (empty device_id).
          2. Among matching device entries, prefer the one whose [t_min, t_max]
             range contains *temperature_c*.
          3. If none contain the temperature, prefer the one with the closest
             midpoint.

        Returns None if the library is empty.
        """
        candidates = self.list(device_id=device_id)
        if not candidates:
            candidates = self.list()   # fall back to all entries
        if not candidates:
            return None

        def _score(e: CalibrationEntry) -> tuple:
            device_match = int(
                bool(device_id) and e.device_id.lower() == device_id.lower()
            )
            in_range = int(e.t_min <= temperature_c <= e.t_max)
            midpoint_dist = abs((e.t_min + e.t_max) / 2.0 - temperature_c)
            # Higher score = better. Sort ascending by (-device_match, -in_range, dist).
            return (-device_match, -in_range, midpoint_dist)

        best_entry = min(candidates, key=_score)
        return self.load(best_entry.display_name)

    def delete(self, name: str) -> bool:
        """
        Remove a calibration from the library and delete its .npz file.
        Returns True on success, False if the name was not found.
        """
        slug = _slugify(name)
        entry = self._index.pop(slug, None)
        if entry is None:
            return False
        try:
            Path(entry.path).unlink(missing_ok=True)
        except Exception as exc:
            log.warning("CalibrationLibrary.delete: could not remove %s: %s",
                        entry.path, exc)
        self._save_index()
        log.info("CalibrationLibrary: deleted %r", name)
        return True

    def rename(self, old_name: str, new_name: str) -> CalibrationEntry:
        """
        Rename a calibration entry (display name and slug key).

        Does NOT rename the .npz file on disk — the path field in the
        index entry keeps pointing at the old slug filename.
        """
        old_slug = _slugify(old_name)
        new_slug = _slugify(new_name)
        entry = self._index.pop(old_slug, None)
        if entry is None:
            raise KeyError(f"No calibration named {old_name!r}")
        if new_slug in self._index:
            raise ValueError(f"A calibration named {new_name!r} already exists.")
        entry.name         = new_slug
        entry.display_name = new_name
        self._index[new_slug] = entry
        self._save_index()
        return entry

    def count(self) -> int:
        return len(self._index)

    def reload(self) -> None:
        """Re-read the index from disk (useful after external modifications)."""
        self._load_index()
