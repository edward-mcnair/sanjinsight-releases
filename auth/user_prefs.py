"""
auth/user_prefs.py

Per-user preference layer for SanjINSIGHT.

Layered lookup
--------------
1. Per-user file:  ~/.microsanj/users/{uid}/prefs.json
2. Global prefs:   config.get_pref()  (via config module)

Users can write their own prefs (ui.theme, etc.).
Only admins can write global prefs (hardware.*, auth.*).

Usage
-----
    prefs = UserPrefs(session)          # from an active AuthSession
    prefs = UserPrefs.for_session(s)    # convenience factory

    prefs.get("ui.theme", "auto")       # reads user-level, falls back to global
    prefs.set("ui.theme", "dark")       # writes to user-level only

    prefs.get_global("auth.require_login", False)   # reads global pref directly
    prefs.set_global("auth.require_login", True)    # admin only; raises if not admin

No PyQt5 imports — safe in tests and background threads.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

import config as _cfg

log = logging.getLogger(__name__)

_MICROSANJ_DIR = Path.home() / ".microsanj"
_USERS_DIR     = _MICROSANJ_DIR / "users"

# Keys that are admin-only (only admins may write these via set_global)
_ADMIN_ONLY_PREFIXES = ("hardware.", "auth.")

# Per-user keys that are never inherited from global prefs
# (i.e. always user-specific with their own defaults)
_USER_ONLY_KEYS = (
    "ui.theme",
    "ui.sidebar_collapsed",
    "autoscan.last_objective_mag",
    "lab.default_recipe",
    "ai.persona",
)


class UserPrefs:
    """
    Per-user preference layer.

    Reads from the user's own prefs.json first; falls back to the global
    config.get_pref() for keys the user has not overridden.  Writes always
    go to the user's own file.
    """

    def __init__(self, uid: str, is_admin: bool = False) -> None:
        self._uid      = uid
        self._is_admin = is_admin
        self._path     = _USERS_DIR / uid / "prefs.json"
        self._lock     = threading.Lock()   # cheap hardening for future cross-thread use
        self._prefs: dict = {}
        self._load()

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def for_session(cls, session) -> "UserPrefs":
        """Convenience factory — accepts an AuthSession."""
        return cls(uid=session.user.uid, is_admin=session.user.is_admin)

    @classmethod
    def for_uid(cls, uid: str, is_admin: bool = False) -> "UserPrefs":
        return cls(uid=uid, is_admin=is_admin)

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._prefs = loaded
        except Exception:
            log.exception("UserPrefs: failed to load %s", self._path)
            self._prefs = {}

    def _save(self, snapshot=None) -> None:
        data = snapshot if snapshot is not None else self._prefs
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            from utils import atomic_write_json
            atomic_write_json(str(self._path), data)
        except Exception:
            log.exception("UserPrefs: failed to save %s", self._path)

    # ── Dot-notation helpers ──────────────────────────────────────────────

    @staticmethod
    def _get_nested(d: dict, key: str) -> Any:
        """Read a dot-notation key from a nested dict. Returns _MISSING on absent."""
        parts = key.split(".")
        node  = d
        for p in parts:
            if not isinstance(node, dict):
                return _MISSING
            node = node.get(p, _MISSING)
            if node is _MISSING:
                return _MISSING
        return node

    @staticmethod
    def _set_nested(d: dict, key: str, value: Any) -> None:
        """Write a dot-notation key into a nested dict, creating intermediate dicts."""
        parts = key.split(".")
        node  = d
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Read a preference.

        Lookup order:
          1. This user's prefs.json
          2. Global config.get_pref() (for keys not in _USER_ONLY_KEYS)
          3. *default*
        """
        with self._lock:
            val = self._get_nested(self._prefs, key)
        if val is not _MISSING:
            return val

        # Don't fall through to global for purely user-local keys
        for prefix in _USER_ONLY_KEYS:
            if key == prefix:
                return default

        return _cfg.get_pref(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write a preference to this user's file.

        Raises PermissionError if the key is in _ADMIN_ONLY_PREFIXES and
        this user is not an admin.
        """
        for prefix in _ADMIN_ONLY_PREFIXES:
            if key.startswith(prefix) and not self._is_admin:
                raise PermissionError(
                    f"Preference '{key}' requires administrator privileges."
                )
        import copy
        with self._lock:
            self._set_nested(self._prefs, key, value)
            snapshot = copy.deepcopy(self._prefs)
        self._save(snapshot)

    def get_global(self, key: str, default: Any = None) -> Any:
        """Read directly from the global config.get_pref() (bypasses user file)."""
        return _cfg.get_pref(key, default)

    def set_global(self, key: str, value: Any) -> None:
        """Write to the global config.set_pref().

        Raises PermissionError if the calling user is not an admin.
        """
        if not self._is_admin:
            raise PermissionError(
                f"Writing global preference '{key}' requires administrator privileges."
            )
        _cfg.set_pref(key, value)

    def has_user_override(self, key: str) -> bool:
        """True if the user has explicitly set this key in their own file."""
        with self._lock:
            return self._get_nested(self._prefs, key) is not _MISSING

    def reset(self, key: str) -> None:
        """Remove a user-level override, reverting to the global default."""
        import copy
        with self._lock:
            parts = key.split(".")
            node  = self._prefs
            for p in parts[:-1]:
                if not isinstance(node, dict) or p not in node:
                    return
                node = node[p]
            node.pop(parts[-1], None)
            snapshot = copy.deepcopy(self._prefs)
        self._save(snapshot)

    def reset_all(self) -> None:
        """Wipe all user-level preferences (resets to global / built-in defaults)."""
        with self._lock:
            self._prefs = {}
        self._save({})

    def uid(self) -> str:
        return self._uid

    def prefs_path(self) -> Path:
        return self._path


# ── Sentinel ──────────────────────────────────────────────────────────────────

class _MissingType:
    """Sentinel for absent dict keys — distinct from None."""
    __slots__ = ()
    def __repr__(self) -> str:
        return "<MISSING>"

_MISSING = _MissingType()
