"""
acquisition/schema_migrations.py

Session file schema migration framework.

When the session.json format changes, bump CURRENT_SCHEMA and add a
migration function here.  The migrate() entry point is called by
SessionMeta.from_dict() whenever it encounters an older schema version.

Adding a new migration
----------------------
1. Increment CURRENT_SCHEMA.
2. Add a ``_vN_to_vN1(data: dict) -> dict`` function below.
3. Add a ``if from_version < N+1: data = _vN_to_vN1(data)`` line in migrate().

Each step is cumulative, so a very old file will walk through every
migration in order and arrive at the current schema.
"""

from __future__ import annotations

import logging
import os
import shutil

log = logging.getLogger(__name__)

CURRENT_SCHEMA: int = 5


class FutureSchemaError(Exception):
    """Raised when a session file has a schema_version newer than we support."""


def backup_before_migration(session_json_path: str, from_version: int) -> str | None:
    """Create a backup of session.json before migrating.

    The backup is named ``session.json.v{N}.bak`` where *N* is the
    original schema version.  If the backup already exists (a previous
    migration was interrupted and retried) the existing backup is kept
    and no new copy is made.

    Returns the backup path, or ``None`` if the backup could not be
    created (logged as a warning; migration proceeds anyway).
    """
    if not session_json_path or not os.path.isfile(session_json_path):
        return None
    bak_path = f"{session_json_path}.v{from_version}.bak"
    if os.path.exists(bak_path):
        log.debug("Migration backup already exists: %s", bak_path)
        return bak_path
    try:
        shutil.copy2(session_json_path, bak_path)
        log.info("Created pre-migration backup: %s", bak_path)
        return bak_path
    except OSError as exc:
        log.warning("Could not create migration backup for %s: %s",
                     session_json_path, exc)
        return None


def reject_future_schema(version: int, path: str = "") -> None:
    """Raise ``FutureSchemaError`` if *version* is from a newer build.

    Called by ``SessionMeta.from_dict()`` so that a session written by a
    newer SanjINSIGHT version is refused cleanly rather than silently
    dropping unknown fields.
    """
    if version > CURRENT_SCHEMA:
        raise FutureSchemaError(
            f"Session at '{path or '(unknown)'}' has schema v{version}, "
            f"but this build only supports up to v{CURRENT_SCHEMA}. "
            f"Upgrade SanjINSIGHT to open this session."
        )


def migrate(data: dict, from_version: int, *,
            session_json_path: str = "") -> dict:
    """Migrate *data* dict from *from_version* up to CURRENT_SCHEMA.

    Each step is applied in sequence so a v0 file passes through every
    migration on the way to the current version.

    Parameters
    ----------
    data:
        Raw dict read from session.json.
    from_version:
        The schema_version found in the file (0 if the key was absent).
    session_json_path:
        Optional path to the file on disk.  If provided a backup is
        created before the first migration step is applied.

    Returns
    -------
    dict
        A *new* dict (the original is never mutated) upgraded to
        CURRENT_SCHEMA.
    """
    # Create a safety backup before touching anything
    if session_json_path:
        backup_before_migration(session_json_path, from_version)

    if from_version < 1:
        data = _v0_to_v1(data)
    if from_version < 2:
        data = _v1_to_v2(data)
    if from_version < 3:
        data = _v2_to_v3(data)
    if from_version < 4:
        data = _v3_to_v4(data)
    if from_version < 5:
        data = _v4_to_v5(data)
    return data


# ---------------------------------------------------------------------------
# Individual migration steps
# ---------------------------------------------------------------------------

def _v0_to_v1(data: dict) -> dict:
    """v0 → v1: Introduce schema_version field.

    v0 sessions have no ``schema_version`` key.  This migration adds one
    and is a no-op for all existing field values — every field carries
    forward as-is.
    """
    log.info("Migrating session schema v0 → v1")
    data = dict(data)           # never mutate the caller's dict
    data.setdefault("schema_version", 1)
    return data


def _v1_to_v2(data: dict) -> dict:
    """v1 → v2: Add camera_id and notes_log fields.

    Adds the hardware identity field (camera_id) and the structured
    notes log (notes_log) introduced in ResultMetadata.  Old sessions
    carry an empty camera_id and an empty notes_log; the flat ``notes``
    string from v1 is preserved as-is for backward display.
    """
    log.info("Migrating session schema v1 → v2")
    data = dict(data)
    data.setdefault("camera_id", "")
    data.setdefault("notes_log", [])
    data["schema_version"] = 2
    return data


def _v2_to_v3(data: dict) -> dict:
    """v2 → v3: Add multi-channel and bit-depth metadata.

    Adds frame_channels, frame_bit_depth, and pixel_format fields to
    support color (RGB) cameras alongside traditional monochrome sensors.
    Existing sessions default to single-channel monochrome.  bit_depth
    defaults to 16 (conservative upper bound) since the original sensor's
    native depth cannot be inferred from a v2 session; actual bit depth
    (12 for TR, 14 for Boson, 16 for FLIR) is recorded at capture time
    in new sessions.
    """
    log.info("Migrating session schema v2 → v3")
    data = dict(data)
    data.setdefault("frame_channels", 1)
    data.setdefault("frame_bit_depth", 16)
    data.setdefault("pixel_format", "mono")
    data["schema_version"] = 3
    return data


def _v3_to_v4(data: dict) -> dict:
    """v3 → v4: Add post-acquisition quality scorecard.

    Stores the deterministic quality scorecard (SNR grade, exposure grade,
    thermal contrast grade, stability grade, overall grade, and actionable
    recommendations) computed by QualityScoringEngine after each acquisition.
    Old sessions get None (no retroactive scoring).
    """
    log.info("Migrating session schema v3 → v4")
    data = dict(data)
    data.setdefault("quality_scorecard", None)
    data["schema_version"] = 4
    return data


def _v4_to_v5(data: dict) -> dict:
    """v4 → v5: Add analysis result persistence.

    Stores the serialized AnalysisResult (verdict, hotspots, statistics,
    config) alongside the session.  Overlay and mask arrays are stored as
    separate .npy files.  Old sessions get None (no retroactive analysis).
    """
    log.info("Migrating session schema v4 → v5")
    data = dict(data)
    data.setdefault("analysis_result", None)
    data["schema_version"] = 5
    return data
