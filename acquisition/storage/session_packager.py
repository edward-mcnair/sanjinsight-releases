"""
acquisition/session_packager.py  —  Bundle sessions into a .zip archive

Creates a self-contained zip with:
  manifest.json          — machine-readable index of included sessions
  sessions/<uid>/...     — full session directory (json + npy + thumbnail)

The archive can be shared, archived, or imported on another machine.
"""
from __future__ import annotations

import json
import logging
import os
import time
import zipfile
from dataclasses import dataclass, asdict, field
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class PackageManifest:
    """Manifest describing the contents of a session package."""
    created: str                    # ISO-8601 timestamp
    creator: str                    # operator display name
    sessions: List[dict] = field(default_factory=list)  # [{uid, label, status, timestamp_str}]
    description: str = ""
    app_version: str = ""
    session_count: int = 0


class SessionPackager:
    """Bundle multiple sessions into a single .zip archive."""

    def __init__(self, session_manager):
        self._mgr = session_manager

    def package(
        self,
        uids: List[str],
        output_path: str,
        description: str = "",
        creator: str = "",
    ) -> str:
        """Create a .zip archive containing the selected sessions.

        Parameters
        ----------
        uids : list of session UIDs to include
        output_path : path to the output .zip file
        description : human-readable description for the manifest
        creator : operator name (embedded in manifest)

        Returns
        -------
        str : absolute path to the created .zip file
        """
        from datetime import datetime, timezone

        manifest = PackageManifest(
            created=datetime.now(timezone.utc).isoformat(),
            creator=creator,
            description=description,
            session_count=len(uids),
        )

        # Ensure output dir exists
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with zipfile.ZipFile(output_path, "w",
                             compression=zipfile.ZIP_DEFLATED) as zf:
            for uid in uids:
                meta = self._mgr.get_meta(uid)
                if meta is None:
                    log.warning("SessionPackager: uid %s not found, skipping", uid)
                    continue

                manifest.sessions.append({
                    "uid": meta.uid,
                    "label": meta.label,
                    "status": getattr(meta, "status", "") or "",
                    "timestamp_str": meta.timestamp_str,
                })

                # Walk session directory and add all files
                session_dir = meta.path
                if not os.path.isdir(session_dir):
                    continue
                for root, _dirs, files in os.walk(session_dir):
                    for fname in files:
                        abs_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(abs_path, session_dir)
                        arc_name = f"sessions/{uid}/{rel_path}"
                        zf.write(abs_path, arc_name)

            # Write manifest
            zf.writestr("manifest.json",
                        json.dumps(asdict(manifest), indent=2))

        log.info("Packaged %d sessions to %s", len(uids), output_path)
        return os.path.abspath(output_path)
