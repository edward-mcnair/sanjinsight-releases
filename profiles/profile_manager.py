"""
profiles/profile_manager.py

Three-tier protection model:
  builtin    — shipped with software. Read-only. Cannot be edited/deleted.
  downloaded — from Microsanj repository. Read-only.
               Stored in: ~/.microsanj/profiles/downloaded/
  user       — created locally. Full CRUD.
               Stored in: ~/.microsanj/profiles/user/
"""

from __future__ import annotations
import os, time
from typing import List, Optional, Dict

from .profiles import (MaterialProfile, BUILTIN_PROFILES,
                        PROFILE_REGISTRY, CATEGORY_USER)

SOURCE_BUILTIN    = "builtin"
SOURCE_DOWNLOADED = "downloaded"
SOURCE_USER       = "user"
SOURCE_IMPORTED   = "imported"


def is_protected(profile: MaterialProfile) -> bool:
    """True if the profile cannot be edited or deleted."""
    return profile.source in (SOURCE_BUILTIN, SOURCE_DOWNLOADED)


class ProfileManager:

    BASE_DIR = os.path.join(os.path.expanduser("~"), ".microsanj", "profiles")

    def __init__(self, base_dir: str = None):
        self._base     = base_dir or self.BASE_DIR
        self._dl_dir   = os.path.join(self._base, "downloaded")
        self._user_dir = os.path.join(self._base, "user")
        self._downloaded: Dict[str, MaterialProfile] = {}
        self._user:       Dict[str, MaterialProfile] = {}

    # --- Index ---

    def scan(self) -> int:
        self._downloaded = self._load_dir(self._dl_dir,   SOURCE_DOWNLOADED)
        self._user       = self._load_dir(self._user_dir, SOURCE_USER)
        return len(self._downloaded) + len(self._user)

    def _load_dir(self, directory, enforce_source):
        result = {}
        if not os.path.isdir(directory):
            return result
        for fname in os.listdir(directory):
            if not fname.endswith(".json"):
                continue
            try:
                p = MaterialProfile.load(os.path.join(directory, fname))
                p.source = enforce_source
                result[p.uid] = p
            except Exception:
                pass
        return result

    # --- Query ---

    def all(self, category: str = None) -> List[MaterialProfile]:
        result = (list(BUILTIN_PROFILES)
                  + list(self._downloaded.values())
                  + list(self._user.values()))
        if category:
            result = [p for p in result if p.category == category]
        return result

    def builtin(self)        -> List[MaterialProfile]: return list(BUILTIN_PROFILES)
    def downloaded(self)     -> List[MaterialProfile]: return list(self._downloaded.values())
    def user_profiles(self)  -> List[MaterialProfile]: return list(self._user.values())

    def categories(self) -> List[str]:
        seen = []
        for p in self.all():
            if p.category not in seen:
                seen.append(p.category)
        return seen

    def get(self, uid: str) -> Optional[MaterialProfile]:
        if uid in PROFILE_REGISTRY:     return PROFILE_REGISTRY[uid]
        if uid in self._downloaded:     return self._downloaded[uid]
        return self._user.get(uid)

    def count(self) -> int:
        return len(BUILTIN_PROFILES) + len(self._downloaded) + len(self._user)

    # --- Downloaded (protected) ---

    def save_downloaded(self, profile: MaterialProfile) -> str:
        os.makedirs(self._dl_dir, exist_ok=True)
        profile.source   = SOURCE_DOWNLOADED
        profile.modified = time.time()
        if not profile.created:
            profile.created = profile.modified
        path = os.path.join(self._dl_dir, f"{profile.uid}.json")
        profile.save(path)
        self._downloaded[profile.uid] = profile
        return path

    # --- User profiles (full CRUD) ---

    def save_user(self, profile: MaterialProfile) -> str:
        os.makedirs(self._user_dir, exist_ok=True)
        profile.source   = SOURCE_USER
        profile.modified = time.time()
        if not profile.created:
            profile.created = profile.modified
        if not profile.uid:
            safe = (profile.name.lower()
                    .replace(" ", "_").replace("/", "_")
                    .replace("\u2014", "").strip("_"))
            profile.uid = f"{safe}_{int(profile.created)}"
        if profile.uid in PROFILE_REGISTRY or profile.uid in self._downloaded:
            profile.uid += "_user"
        path = os.path.join(self._user_dir, f"{profile.uid}.json")
        profile.save(path)
        self._user[profile.uid] = profile
        return path

    def delete_user(self, uid: str) -> bool:
        if uid in PROFILE_REGISTRY or uid in self._downloaded:
            return False
        profile = self._user.pop(uid, None)
        if profile is None:
            return False
        try:
            os.remove(os.path.join(self._user_dir, f"{uid}.json"))
            return True
        except Exception:
            return False

    def duplicate_as_user(self, uid: str,
                          new_name: str = "") -> Optional[MaterialProfile]:
        src = self.get(uid)
        if src is None:
            return None
        import copy
        p         = copy.deepcopy(src)
        p.uid     = ""
        p.name    = new_name or f"{src.name} (custom)"
        p.source  = SOURCE_USER
        p.created = p.modified = time.time()
        self.save_user(p)
        return p

    # --- Import / Export ---

    def export_profile(self, uid: str, path: str) -> bool:
        p = self.get(uid)
        if p is None:
            return False
        try:
            p.save(path); return True
        except Exception:
            return False

    def import_profile(self, path: str) -> Optional[MaterialProfile]:
        try:
            p = MaterialProfile.load(path)
            p.source = SOURCE_USER
            self.save_user(p)
            return p
        except Exception:
            return None
