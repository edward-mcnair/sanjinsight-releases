"""
profiles/profile_manager.py

ProfileManager — loads, saves, and indexes MaterialProfile objects from
~/.microsanj/profiles/

Usage
-----
    mgr = ProfileManager()
    mgr.scan()                    # discover profiles on disk
    profiles = mgr.all()          # list of MaterialProfile
    mgr.save(profile)             # persist one profile
    mgr.delete(profile)           # remove a profile
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .profiles import MaterialProfile, CATEGORY_USER

log = logging.getLogger(__name__)

_PROFILES_DIR = Path.home() / ".microsanj" / "profiles"


class ProfileManager:
    """
    Manages the collection of MaterialProfile objects.

    Scans ~/.microsanj/profiles/ for *.json files on demand.
    Profiles are kept in memory after the first scan.
    """

    def __init__(self, directory: Path = None):
        self._dir      = Path(directory) if directory else _PROFILES_DIR
        self._profiles: List[MaterialProfile] = []
        self._scanned  = False

    # ---------------------------------------------------------------- #
    #  Public API                                                        #
    # ---------------------------------------------------------------- #

    def scan(self) -> None:
        """Re-read all profile JSON files from disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        profiles = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                profiles.append(MaterialProfile.load(path))
            except Exception as e:
                log.warning("Skipping malformed profile %s: %s", path.name, e)
        self._profiles = sorted(profiles, key=lambda p: p.name.lower())
        self._scanned  = True
        log.debug("ProfileManager: loaded %d profiles from %s",
                  len(self._profiles), self._dir)

    def all(self) -> List[MaterialProfile]:
        if not self._scanned:
            self.scan()
        return list(self._profiles)

    def by_category(self, category: str) -> List[MaterialProfile]:
        return [p for p in self.all() if p.category == category]

    def find(self, name: str) -> Optional[MaterialProfile]:
        for p in self.all():
            if p.name == name:
                return p
        return None

    def save(self, profile: MaterialProfile) -> Path:
        path = profile.save(self._dir)
        # Refresh in-memory list
        self.scan()
        return path

    def delete(self, profile: MaterialProfile) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in profile.name).strip("_") or profile.uid
        path = self._dir / f"{safe}.json"
        if path.exists():
            path.unlink()
            log.info("Profile deleted: %s", path)
        # Refresh in-memory list
        self.scan()
