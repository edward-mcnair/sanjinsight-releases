"""
acquisition/session_manager.py

SessionManager maintains a live index of all sessions in a root directory.
Provides save, load, delete, and comparison operations.
"""

from __future__ import annotations
import logging
import os, shutil
import threading
from typing import List, Optional, Dict

import config as cfg_mod
from .session import Session, SessionMeta
from ._atomic import atomic_write_json

log = logging.getLogger(__name__)


class SessionManager:

    def __init__(self, root: str):
        self._root  = root
        self._index: Dict[str, SessionMeta] = {}
        self._lock  = threading.RLock()

    @property
    def root(self) -> str:
        return self._root

    @root.setter
    def root(self, path: str):
        with self._lock:
            self._root  = path
            self._index = {}

    # ---------------------------------------------------------------- #
    #  Index                                                            #
    # ---------------------------------------------------------------- #

    def scan(self) -> int:
        """Rebuild index by scanning root. Returns session count."""
        with self._lock:
            self._index = {}
            if not os.path.isdir(self._root):
                return 0
            for name in os.listdir(self._root):
                folder = os.path.join(self._root, name)
                if not os.path.isdir(folder):
                    continue
                meta = Session.load_meta(folder)
                if meta:
                    self._index[meta.uid] = meta
            return len(self._index)

    def all_metas(self) -> List[SessionMeta]:
        """All metadata, newest first."""
        with self._lock:
            return sorted(self._index.values(),
                          key=lambda m: m.timestamp, reverse=True)

    def get_meta(self, uid: str) -> Optional[SessionMeta]:
        with self._lock:
            return self._index.get(uid)

    def count(self) -> int:
        with self._lock:
            return len(self._index)

    # ---------------------------------------------------------------- #
    #  CRUD                                                             #
    # ---------------------------------------------------------------- #

    def save_result(self, result, label: str = "",
                    operator: str = "",
                    device_id: str = "",
                    project: str = "",
                    status: str = "",
                    tags: Optional[List[str]] = None,
                    auth_session=None,
                    result_type: str = "single_point",
                    scan_params: Optional[dict] = None,
                    cube_params: Optional[dict] = None) -> Session:
        """Save an acquisition result as a new session. Adds to index.

        Parameters
        ----------
        result
            The result object — AcquisitionResult (single_point),
            ScanResult (grid), or TransientResult (transient).
        result_type : str
            One of "single_point", "grid", "transient", "movie".
        scan_params : dict, optional
            Grid-specific metadata (n_rows, n_cols, step sizes, etc.).
        cube_params : dict, optional
            Transient/movie-specific metadata (n_delays, delay range, etc.).

        If *operator* is not supplied, it is resolved in priority order:
          1. ``auth_session.user.display_name`` (when auth is active)
          2. ``config.get_pref("lab.active_operator")`` (legacy fallback)
        Callers that pass ``operator=`` explicitly are unaffected.
        """
        os.makedirs(self._root, exist_ok=True)
        # Auto-stamp operator — auth session takes priority over pref
        if not operator:
            if auth_session is not None:
                operator = getattr(
                    getattr(auth_session, "user", None), "display_name", "") or ""
            if not operator:
                operator = cfg_mod.get_pref("lab.active_operator", "") or ""
        session = Session.from_result(
            result, label=label,
            operator=operator,
            device_id=device_id,
            project=project,
            status=status,
            tags=tags or [],
            result_type=result_type,
            scan_params=scan_params,
            cube_params=cube_params,
        )
        session.save(self._root)
        with self._lock:
            self._index[session.meta.uid] = session.meta
        return session

    def load(self, uid: str) -> Optional[Session]:
        """Load full session by uid (arrays lazy-loaded)."""
        with self._lock:
            meta = self._index.get(uid)
        if meta is None:
            return None
        try:
            return Session.load(meta.path)
        except Exception as e:
            log.warning("SessionManager.load(%s): %s", uid, e)
            return None

    def _update_field(self, uid: str, field: str, value):
        """Update a single metadata field on both disk and the in-memory index.

        Disk is written first via atomic_write_json.  The in-memory index
        is updated only after the disk commit succeeds, so the two never
        diverge on I/O failure.
        """
        import json
        with self._lock:
            meta = self._index.get(uid)
            if meta is None:
                return
            p = os.path.join(meta.path, "session.json")
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        d = json.load(f)
                    d[field] = value
                    atomic_write_json(p, d)
                except (OSError, json.JSONDecodeError) as e:
                    log.warning("SessionManager._update_field(%s, %s): %s",
                                uid, field, e)
                    return   # disk write failed — leave memory unchanged
            # Disk committed (or no file on disk yet) — safe to update memory
            setattr(meta, field, value)

    def update_label(self, uid: str, label: str):
        """Rename a session label in-place."""
        self._update_field(uid, "label", label)

    def update_notes(self, uid: str, notes: str):
        """Update session notes in-place."""
        self._update_field(uid, "notes", notes)

    def update_status(self, uid: str, status: str):
        """Update session status in-place (pending/reviewed/flagged/archived)."""
        self._update_field(uid, "status", status)

    def delete(self, uid: str) -> bool:
        """Delete session folder from disk, then remove from index.

        The folder is deleted *before* the index is updated so that a failed
        ``shutil.rmtree()`` leaves the session visible in the manager
        (the user can retry or inspect the folder).  Only on successful
        disk deletion is the in-memory index entry removed.
        """
        with self._lock:
            meta = self._index.get(uid)
        if meta is None:
            return False
        try:
            shutil.rmtree(meta.path)
        except Exception as e:
            log.warning("SessionManager.delete(%s): disk delete failed: %s", uid, e)
            return False
        # Disk delete succeeded — now safe to remove from index
        with self._lock:
            self._index.pop(uid, None)
        return True

    # ---------------------------------------------------------------- #
    #  Comparison helpers                                               #
    # ---------------------------------------------------------------- #

    def load_pair(self, uid_a: str, uid_b: str):
        """Load two sessions for side-by-side comparison."""
        return self.load(uid_a), self.load(uid_b)

    def diff_drr(self, uid_a: str, uid_b: str):
        """
        Compute (ΔR/R_a − ΔR/R_b) for two sessions.
        Arrays must have the same shape.
        Returns float32 difference array or None.
        """
        import numpy as np
        sa = self.load(uid_a)
        sb = self.load(uid_b)
        if sa is None or sb is None:
            return None
        da = sa.delta_r_over_r
        db = sb.delta_r_over_r
        if da is None or db is None:
            return None
        if da.shape != db.shape:
            return None
        return (da.astype(np.float64) - db.astype(np.float64))
