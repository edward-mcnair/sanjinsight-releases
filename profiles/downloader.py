"""
profiles/downloader.py

ProfileDownloader — fetches the Microsanj profile index and downloads
individual profiles from the official profile repository.

Index format (hosted at MICROSANJ_PROFILE_INDEX_URL):
-------------------------------------------------------
{
  "version": 1,
  "updated": "2025-06-01",
  "profiles": [
    {
      "uid":          "si_532_v2",
      "name":         "Silicon — 532 nm  (v2)",
      "category":     "Semiconductor / IC",
      "version":      "2.0",
      "wavelength_nm": 532,
      "description":  "Revised C_T from 2025 calibration campaign.",
      "tags":         ["Semiconductor / IC", "Electronics / PCB"],
      "download_url": "https://profiles.microsanj.com/si_532_v2.json"
    },
    ...
  ]
}

The download_url for each entry points to a full MaterialProfile JSON
(same format as local user profiles).

This module is network-only and has no Qt dependencies — it can be
called from a background thread.
"""

from __future__ import annotations
import json, time, os
from typing      import List, Optional, Dict, Callable
from dataclasses import dataclass, field
from urllib      import request, error as url_error

# ------------------------------------------------------------------ #
#  Configuration                                                       #
# ------------------------------------------------------------------ #

MICROSANJ_PROFILE_INDEX_URL = (
    "https://raw.githubusercontent.com/microsanj/profiles/main/index.json"
)

# Allow override via environment variable for enterprise / air-gapped installs
INDEX_URL = os.environ.get(
    "MICROSANJ_PROFILE_REPO", MICROSANJ_PROFILE_INDEX_URL)

REQUEST_TIMEOUT = 10   # seconds


# ------------------------------------------------------------------ #
#  Data model for index entries                                        #
# ------------------------------------------------------------------ #

@dataclass
class RemoteProfileEntry:
    """One entry from the remote index — not yet downloaded."""
    uid:          str
    name:         str
    category:     str
    version:      str
    wavelength_nm: int
    description:  str
    download_url: str
    tags:         List[str] = field(default_factory=list)
    already_installed: bool = False   # filled in by ProfileDownloader.check()


@dataclass
class DownloadResult:
    uid:     str
    success: bool
    path:    str   = ""
    error:   str   = ""


# ------------------------------------------------------------------ #
#  Downloader                                                          #
# ------------------------------------------------------------------ #

class ProfileDownloader:
    """
    Fetches the profile index and downloads selected profiles.
    All network operations happen synchronously — call from a thread.
    """

    def __init__(self, manager):
        """
        manager: ProfileManager — used to check for already-installed
                 profiles and to save downloaded ones.
        """
        self._mgr = manager

    # ---------------------------------------------------------------- #
    #  Index                                                            #
    # ---------------------------------------------------------------- #

    def fetch_index(self,
                    progress_cb: Optional[Callable[[str], None]] = None
                    ) -> List[RemoteProfileEntry]:
        """
        Download and parse the profile index.
        Returns a list of RemoteProfileEntry.
        Raises RuntimeError on network or parse failure.
        """
        if progress_cb:
            progress_cb("Connecting to Microsanj profile repository…")

        try:
            req = request.Request(
                INDEX_URL,
                headers={"User-Agent": "MicrosanjThermalAnalysis/1.0"})
            with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
        except url_error.URLError as e:
            raise RuntimeError(
                f"Cannot reach profile server:\n{e}\n\n"
                f"Check your internet connection or contact Microsanj support."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Network error: {e}") from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid index format from server: {e}") from e

        entries: List[RemoteProfileEntry] = []
        installed_uids = {p.uid for p in self._mgr.all()}

        for item in data.get("profiles", []):
            try:
                entry = RemoteProfileEntry(
                    uid          = item["uid"],
                    name         = item["name"],
                    category     = item.get("category", ""),
                    version      = item.get("version", "1.0"),
                    wavelength_nm= item.get("wavelength_nm", 532),
                    description  = item.get("description", ""),
                    download_url = item["download_url"],
                    tags         = item.get("tags", []),
                    already_installed = item["uid"] in installed_uids,
                )
                entries.append(entry)
            except KeyError:
                continue   # skip malformed entries

        if progress_cb:
            progress_cb(
                f"Found {len(entries)} profiles "
                f"({sum(1 for e in entries if not e.already_installed)} new).")
        return entries

    # ---------------------------------------------------------------- #
    #  Download                                                         #
    # ---------------------------------------------------------------- #

    def download(self,
                 entry: RemoteProfileEntry,
                 progress_cb: Optional[Callable[[str], None]] = None
                 ) -> DownloadResult:
        """
        Download a single profile and install it via the manager.
        Returns a DownloadResult.
        """
        if progress_cb:
            progress_cb(f"Downloading  {entry.name}…")

        try:
            req = request.Request(
                entry.download_url,
                headers={"User-Agent": "MicrosanjThermalAnalysis/1.0"})
            with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as e:
            return DownloadResult(uid=entry.uid, success=False,
                                  error=f"Download failed: {e}")

        try:
            profile_data = json.loads(raw)
        except Exception as e:
            return DownloadResult(uid=entry.uid, success=False,
                                  error=f"Invalid profile JSON: {e}")

        try:
            from .profiles import MaterialProfile
            profile = MaterialProfile.from_dict(profile_data)
            profile.source = "downloaded"
            path = self._mgr.save_downloaded(profile)
        except Exception as e:
            return DownloadResult(uid=entry.uid, success=False,
                                  error=f"Could not save profile: {e}")

        if progress_cb:
            progress_cb(f"✓  Installed: {entry.name}")

        return DownloadResult(uid=entry.uid, success=True, path=path)

    def download_many(self,
                      entries: List[RemoteProfileEntry],
                      progress_cb: Optional[Callable[[str], None]] = None
                      ) -> List[DownloadResult]:
        """Download and install multiple profiles."""
        results = []
        for i, entry in enumerate(entries):
            if progress_cb:
                progress_cb(
                    f"[{i+1}/{len(entries)}]  {entry.name}…")
            results.append(self.download(entry, progress_cb))
        return results
