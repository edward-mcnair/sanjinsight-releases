"""
session/manifest.py

Append-only run manifest — records the provenance of every acquisition or
scan run in a machine-readable JSON file co-located with ``session.json``.

File layout
-----------
Each session directory gets one ``manifest.json``::

    sessions/
        20250315_143022_device_A/
            session.json        ← acquisition metadata (unchanged)
            manifest.json       ← NEW: run provenance (this module)
            cold_avg.npy
            …

The manifest file is versioned independently from ``session.json`` via
``manifest_schema_version`` so it can evolve without touching existing
schema-migration code.

Atomicity
---------
Every write goes to a ``.tmp`` sibling first, then ``os.replace()``
promotes it atomically.  A crash between writes can only produce a
``.tmp`` orphan — the manifest itself is never left in a partial state.

Usage::

    from session.manifest import RunRecord, ManifestWriter
    import time

    record = RunRecord(
        run_uid      = "20250315_143022_acq_001",
        operation    = "acquire",
        started_at   = "2025-03-15T14:30:22",
        completed_at = "2025-03-15T14:30:45",
        duration_s   = 23.4,
        outcome      = "complete",
        session_uid  = "20250315_143022_device_A",
        snr_db       = 38.2,
        n_frames     = 100,
    )
    ManifestWriter(session_dir).append_run(record)
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Bump when the manifest schema changes in a backwards-incompatible way.
MANIFEST_SCHEMA_VERSION: int = 1

_MANIFEST_FILENAME = "manifest.json"


# ── RunRecord ─────────────────────────────────────────────────────────────────


@dataclass
class RunRecord:
    """
    Provenance record for one acquisition or scan run.

    All timestamps are ISO-8601 strings.  All lists default to empty so
    records can be partially filled at run start then finalised at
    completion via :meth:`ManifestWriter.append_run`.

    Attributes
    ----------
    run_uid             : Unique identifier for this run (auto-generated if empty)
    operation           : One of the OP_* constants from requirements_resolver
                          (``"acquire"``, ``"scan"``, ``"live"``, …)
    started_at          : ISO-8601 timestamp of acquisition start
    completed_at        : ISO-8601 timestamp of completion / abort
    duration_s          : Wall-clock duration in seconds
    outcome             : ``"complete"`` | ``"abort"`` | ``"error"``
    failure_reason      : Non-empty only when outcome == ``"error"`` or ``"abort"``
    session_uid         : UID of the parent session (links to session.json)
    device_inventory    : Serialised list of DeviceEntry.to_dict() snapshots
    settings_snapshot   : Dict of key acquisition parameters at run start
    calibration_uid     : UID of the calibration used (or "" if uncalibrated)
    calibration_status  : ``"ok"`` | ``"warn_proceeded"`` | ``"missing"`` | ``"stale"``
    quality_score       : Numeric quality score 0–100 (None if not computed)
    quality_reasons     : List of human-readable quality notes
    preflight_summary   : Dict summary of preflight check results
    degraded_mode       : True if any optional devices were absent
    optional_devices_missing : Device types that were optional but absent
    snr_db              : Measured signal-to-noise ratio in dB (acquire only)
    n_frames            : Frames captured per phase
    event_trace         : Timeline events that occurred during this run
    """

    run_uid:                  str              = field(default_factory=lambda: str(uuid.uuid4())[:13])
    operation:                str              = ""
    started_at:               str              = ""
    completed_at:             str              = ""
    duration_s:               float            = 0.0
    outcome:                  str              = "complete"   # complete|abort|error
    failure_reason:           str              = ""

    # Traceability
    session_uid:              str              = ""
    device_inventory:         List[dict]       = field(default_factory=list)
    settings_snapshot:        Dict[str, Any]   = field(default_factory=dict)

    # Calibration
    calibration_uid:          str              = ""
    calibration_status:       str              = "missing"    # ok|warn_proceeded|missing|stale

    # Quality
    quality_score:            Optional[float]  = None
    quality_reasons:          List[str]        = field(default_factory=list)

    # Preflight
    preflight_summary:        Dict[str, Any]   = field(default_factory=dict)

    # Degraded mode
    degraded_mode:            bool             = False
    optional_devices_missing: List[str]        = field(default_factory=list)

    # Run metrics
    snr_db:                   Optional[float]  = None
    n_frames:                 int              = 0

    # Event audit trail
    event_trace:              List[dict]       = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot."""
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RunRecord":
        r = RunRecord()
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r


# ── SessionManifest ───────────────────────────────────────────────────────────


@dataclass
class SessionManifest:
    """
    Top-level manifest for one session directory.

    Holds a header with session-level metadata and a ``runs`` list that
    accumulates one :class:`RunRecord` per acquisition or scan.

    Attributes
    ----------
    manifest_schema_version : Integer version for schema migration
    session_uid             : Matches the ``uid`` field in session.json
    app_version             : Application version string at creation time
    git_hash                : Short git hash of HEAD at creation time
    created_at              : ISO-8601 creation timestamp
    runs                    : Ordered list of RunRecord dicts (append-only)
    """

    manifest_schema_version: int            = MANIFEST_SCHEMA_VERSION
    session_uid:             str            = ""
    app_version:             str            = ""
    git_hash:                str            = ""
    created_at:              str            = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    runs:                    List[dict]     = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SessionManifest":
        m = SessionManifest()
        for k, v in d.items():
            if hasattr(m, k):
                setattr(m, k, v)
        return m


# ── ManifestWriter ────────────────────────────────────────────────────────────


class ManifestWriter:
    """
    Creates and appends to a ``manifest.json`` inside a session directory.

    Parameters
    ----------
    session_dir : str | Path
        The session folder that already contains (or will contain)
        ``session.json``.  The manifest is written to
        ``<session_dir>/manifest.json``.

    Thread safety
    -------------
    ``append_run()`` is not thread-safe.  Call it from a single writer
    thread (the background save thread in ``main_app.py`` is fine).
    """

    def __init__(self, session_dir: str | Path) -> None:
        self._dir  = Path(session_dir)
        self._path = self._dir / _MANIFEST_FILENAME

    # ── Public ────────────────────────────────────────────────────────

    def append_run(self, record: RunRecord) -> None:
        """
        Append *record* to the manifest and write atomically.

        If no manifest exists yet, one is created with a header derived
        from the current application state.

        Parameters
        ----------
        record : RunRecord
            Completed run record to persist.
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            manifest = self._load_or_create(record.session_uid)
            manifest.runs.append(record.to_dict())
            self._write(manifest)
            log.debug("ManifestWriter: appended run %s → %s",
                      record.run_uid, self._path)
        except Exception:
            log.warning("ManifestWriter: failed to write manifest for run %s",
                        record.run_uid, exc_info=True)

    def load(self) -> Optional[SessionManifest]:
        """Load and return the manifest, or None if it does not exist."""
        if not self._path.exists():
            return None
        try:
            with open(self._path, encoding="utf-8") as f:
                return SessionManifest.from_dict(json.load(f))
        except Exception:
            log.warning("ManifestWriter: failed to load %s", self._path,
                        exc_info=True)
            return None

    # ── Private ───────────────────────────────────────────────────────

    def _load_or_create(self, session_uid: str) -> SessionManifest:
        """Return the existing manifest or build a fresh one."""
        existing = self.load()
        if existing is not None:
            return existing
        return SessionManifest(
            session_uid = session_uid,
            app_version = _app_version(),
            git_hash    = _git_hash(),
        )

    def _write(self, manifest: SessionManifest) -> None:
        """Write manifest atomically via temp-file + os.replace()."""
        tmp = self._path.with_suffix(".tmp.json")
        try:
            data = json.dumps(manifest.to_dict(), indent=2, default=str)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise


# ── Helpers ───────────────────────────────────────────────────────────────────


def _app_version() -> str:
    try:
        import version as _ver
        return _ver.version_string()
    except Exception:
        return "unknown"


def _git_hash() -> str:
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def build_device_inventory(device_manager=None) -> List[dict]:
    """
    Return a serialisable list of all device states.

    Parameters
    ----------
    device_manager : DeviceManager | None
        If None, returns an empty list.
    """
    if device_manager is None:
        return []
    try:
        return [e.to_dict() for e in device_manager.all()]
    except Exception:
        return []


def build_settings_snapshot(app_state=None) -> Dict[str, Any]:
    """
    Capture key acquisition settings from the current app_state for the manifest.

    Returns a flat dict of scalar values — no numpy arrays.
    """
    snap: Dict[str, Any] = {}
    if app_state is None:
        return snap
    try:
        cam = getattr(app_state, "cam", None)
        if cam:
            try:
                st = cam.get_status()
                snap["exposure_us"] = getattr(st, "exposure_us", None)
                snap["gain_db"]     = getattr(st, "gain_db",     None)
            except Exception:
                pass

        fpga = getattr(app_state, "fpga", None)
        if fpga:
            try:
                st = fpga.get_status()
                snap["fpga_frequency_hz"] = getattr(st, "frequency_hz", None)
            except Exception:
                pass

        tecs = getattr(app_state, "tecs", [])
        if tecs:
            try:
                st = tecs[0].get_status()
                snap["tec_setpoint_c"]  = getattr(st, "target_temp",  None)
                snap["tec_actual_c"]    = getattr(st, "actual_temp",   None)
            except Exception:
                pass

        profile = getattr(app_state, "active_profile", None)
        if profile:
            snap["profile_uid"]  = getattr(profile, "uid",      "")
            snap["profile_name"] = getattr(profile, "name",     "")
            snap["ct_value"]     = getattr(profile, "ct_value", None)

        modality = getattr(app_state, "active_modality", None)
        if modality is not None:
            snap["imaging_mode"] = str(modality.value if hasattr(modality, "value")
                                       else modality)
    except Exception:
        log.debug("build_settings_snapshot: unexpected error", exc_info=True)
    return snap
