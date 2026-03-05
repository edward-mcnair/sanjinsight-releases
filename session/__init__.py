"""
session — Run-manifest utilities.

Provides an append-only, atomically-written JSON manifest that records
the provenance of every acquisition or scan run.  The manifest lives
alongside ``session.json`` in each session directory.

Public exports
--------------
RunRecord       — dataclass describing one run (acquire / scan / movie…)
SessionManifest — dataclass containing session header + runs[]
ManifestWriter  — creates and appends to the manifest file atomically
"""
from .manifest import RunRecord, SessionManifest, ManifestWriter

__all__ = ["RunRecord", "SessionManifest", "ManifestWriter"]
