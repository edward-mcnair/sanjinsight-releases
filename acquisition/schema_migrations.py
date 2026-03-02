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

log = logging.getLogger(__name__)

CURRENT_SCHEMA: int = 1


def migrate(data: dict, from_version: int) -> dict:
    """Migrate *data* dict from *from_version* up to CURRENT_SCHEMA.

    Each step is applied in sequence so a v0 file passes through every
    migration on the way to the current version.

    Parameters
    ----------
    data:
        Raw dict read from session.json.
    from_version:
        The schema_version found in the file (0 if the key was absent).

    Returns
    -------
    dict
        A *new* dict (the original is never mutated) upgraded to
        CURRENT_SCHEMA.
    """
    if from_version < 1:
        data = _v0_to_v1(data)
    # Future migrations:
    # if from_version < 2:
    #     data = _v1_to_v2(data)
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
