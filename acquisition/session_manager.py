"""
acquisition/session_manager.py

SessionManager maintains a live index of all sessions in a root directory.
Provides save, load, delete, and comparison operations.
"""

from __future__ import annotations
import logging
import os, shutil
from typing import List, Optional, Dict

import config as cfg_mod
from .session import Session, SessionMeta

log = logging.getLogger(__name__)


class SessionManager:

    def __init__(self, root: str):
        self._root  = root
        self._index: Dict[str, SessionMeta] = {}

    @property
    def root(self) -> str:
        return self._root

    @root.setter
    def root(self, path: str):
        self._root  = path
        self._index = {}

    # ---------------------------------------------------------------- #
    #  Index                                                            #
    # ---------------------------------------------------------------- #

    def scan(self) -> int:
        """Rebuild index by scanning root. Returns session count."""
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
        return sorted(self._index.values(),
                      key=lambda m: m.timestamp, reverse=True)

    def get_meta(self, uid: str) -> Optional[SessionMeta]:
        return self._index.get(uid)

    def count(self) -> int:
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
                    auth_session=None) -> Session:
        """Save an AcquisitionResult as a new session. Adds to index.

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
        )
        session.save(self._root)
        self._index[session.meta.uid] = session.meta
        return session

    def load(self, uid: str) -> Optional[Session]:
        """Load full session by uid (arrays lazy-loaded)."""
        meta = self._index.get(uid)
        if meta is None:
            return None
        try:
            return Session.load(meta.path)
        except Exception as e:
            log.warning("SessionManager.load(%s): %s", uid, e)
            return None

    def update_label(self, uid: str, label: str):
        """Rename a session label in-place."""
        import json
        meta = self._index.get(uid)
        if meta is None:
            return
        meta.label = label
        p = os.path.join(meta.path, "session.json")
        if os.path.exists(p):
            with open(p) as f:
                d = json.load(f)
            d["label"] = label
            with open(p, "w") as f:
                json.dump(d, f, indent=2)

    def update_notes(self, uid: str, notes: str):
        """Update session notes in-place."""
        import json
        meta = self._index.get(uid)
        if meta is None:
            return
        meta.notes = notes
        p = os.path.join(meta.path, "session.json")
        if os.path.exists(p):
            with open(p) as f:
                d = json.load(f)
            d["notes"] = notes
            with open(p, "w") as f:
                json.dump(d, f, indent=2)

    def delete(self, uid: str) -> bool:
        """Delete session folder from disk and remove from index."""
        meta = self._index.pop(uid, None)
        if meta is None:
            return False
        try:
            shutil.rmtree(meta.path)
            return True
        except Exception as e:
            log.warning("SessionManager.delete(%s): %s", uid, e)
            return False

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
        return (da.astype(np.float64) - db.astype(np.float64)).astype(np.float32)
