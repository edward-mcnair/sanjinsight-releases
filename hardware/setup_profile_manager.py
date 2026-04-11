"""
hardware/setup_profile_manager.py

Manages named hardware setup profiles and the "last used" auto-profile.

Storage layout
--------------
    ~/.microsanj/hw_setup_profiles.json   — named profiles  {name: profile_dict}
    ~/.microsanj/hw_last_used.json        — single auto-saved profile

The manager is a thin persistence layer — all safety logic (safe vs pending
classification, signal blocking, hardware identity matching) lives in
``hardware.setup_profile``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from .setup_profile import SetupProfile

log = logging.getLogger(__name__)

_PREFS_DIR    = os.path.join(os.path.expanduser("~"), ".microsanj")
_PROFILES_FILE = os.path.join(_PREFS_DIR, "hw_setup_profiles.json")
_LAST_USED_FILE = os.path.join(_PREFS_DIR, "hw_last_used.json")


class SetupProfileManager:
    """Save, load, list, and delete named hardware setup profiles."""

    def __init__(self,
                 profiles_path: str = _PROFILES_FILE,
                 last_used_path: str = _LAST_USED_FILE):
        self._profiles_path  = profiles_path
        self._last_used_path = last_used_path
        self._profiles: dict[str, dict] = {}
        self._load_profiles()

    # ── Named profiles ────────────────────────────────────────────────────────

    def names(self) -> List[str]:
        """Return all saved profile names, alphabetically sorted."""
        return sorted(self._profiles.keys())

    def save(self, profile: SetupProfile) -> None:
        """Save (or overwrite) a named profile."""
        if not profile.name:
            raise ValueError("Profile must have a name")
        self._profiles[profile.name] = profile.to_dict()
        self._write_profiles()
        log.info("SetupProfileManager: saved profile '%s'", profile.name)

    def load(self, name: str) -> Optional[SetupProfile]:
        """Load a named profile by name.  Returns None if not found."""
        data = self._profiles.get(name)
        if data is None:
            return None
        try:
            return SetupProfile.from_dict(data)
        except Exception as exc:
            log.warning("SetupProfileManager: could not parse profile '%s': %s",
                        name, exc)
            return None

    def delete(self, name: str) -> bool:
        """Delete a named profile.  Returns True if it existed."""
        if name in self._profiles:
            del self._profiles[name]
            self._write_profiles()
            log.info("SetupProfileManager: deleted profile '%s'", name)
            return True
        return False

    def count(self) -> int:
        return len(self._profiles)

    # ── Last-used auto-profile ────────────────────────────────────────────────

    def save_last_used(self, profile: SetupProfile) -> None:
        """Auto-save the current hardware state as the last-used profile.

        Called on a debounced timer after any setting change.
        """
        data = profile.to_dict()
        data["name"] = ""  # last-used has no name
        try:
            os.makedirs(os.path.dirname(self._last_used_path), exist_ok=True)
            with open(self._last_used_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log.warning("SetupProfileManager: could not save last-used: %s", exc)

    def load_last_used(self) -> Optional[SetupProfile]:
        """Load the last-used auto-profile.  Returns None if absent or corrupt."""
        try:
            if not os.path.isfile(self._last_used_path):
                return None
            with open(self._last_used_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SetupProfile.from_dict(data)
        except Exception as exc:
            log.warning("SetupProfileManager: could not load last-used: %s", exc)
            return None

    def has_last_used(self) -> bool:
        return os.path.isfile(self._last_used_path)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_profiles(self):
        try:
            if os.path.isfile(self._profiles_path):
                with open(self._profiles_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._profiles = {k: v for k, v in data.items()
                                  if isinstance(v, dict)}
        except Exception as exc:
            log.warning("SetupProfileManager: could not load profiles: %s", exc)
            self._profiles = {}

    def _write_profiles(self):
        try:
            os.makedirs(os.path.dirname(self._profiles_path), exist_ok=True)
            with open(self._profiles_path, "w", encoding="utf-8") as f:
                json.dump(self._profiles, f, indent=2)
        except Exception as exc:
            log.warning("SetupProfileManager: could not write profiles: %s", exc)
