"""
updater.py — Background update checker for SanjINSIGHT.

How it works
------------
1. On app startup (if auto-check is enabled in preferences), UpdateChecker
   runs on a background thread and hits the GitHub Releases API.
2. If a newer version is available it emits update_available(info) where
   info is an UpdateInfo dataclass with version, release notes, download URL.
3. The UI connects to this signal and shows a badge + optional dialog.
4. Nothing is downloaded or installed automatically — the user is always
   in control.

GitHub API endpoint used:
    GET https://api.github.com/repos/microsanj/sanjinsight/releases/latest
    Returns JSON with tag_name, body (markdown release notes), assets[].browser_download_url

Adding a real GitHub repo
--------------------------
1. Create the repo at github.com/microsanj/sanjinsight
2. Publish releases with tags matching v{version.py __version__}
3. Attach the Windows installer .exe as a release asset named
   SanjINSIGHT-Setup-{version}.exe
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional, Callable

from version import (
    UPDATE_CHECK_URL, RELEASES_PAGE_URL,
    is_newer, parse_version, __version__,
)

log = logging.getLogger(__name__)

# Seconds to wait before the first update check (let the UI finish loading)
_STARTUP_DELAY_S = 8


@dataclass
class UpdateInfo:
    """All information about an available update."""
    version:        str            # e.g. "1.2.0"
    release_notes:  str            # Markdown text from GitHub release body
    download_url:   str            # Direct .exe URL, or releases page URL
    release_url:    str            # GitHub release HTML page
    is_prerelease:  bool = False


class UpdateChecker:
    """
    Runs a one-shot background check against the GitHub Releases API.

    Usage
    -----
        checker = UpdateChecker(on_update=my_callback, on_error=log.debug)
        checker.check_async()          # non-blocking
        checker.check_sync()           # blocking (for "Check Now" button)
    """

    def __init__(
        self,
        on_update:  Callable[[UpdateInfo], None],
        on_error:   Optional[Callable[[str], None]] = None,
        on_no_update: Optional[Callable[[], None]]  = None,
    ):
        self._on_update    = on_update
        self._on_error     = on_error or (lambda msg: log.debug(f"Update check: {msg}"))
        self._on_no_update = on_no_update or (lambda: None)

    def check_async(self, delay_s: float = 0) -> None:
        """Fire-and-forget background check. Optional startup delay."""
        t = threading.Thread(
            target=self._run, args=(delay_s,),
            name="updater", daemon=True)
        t.start()

    def check_sync(self) -> Optional[UpdateInfo]:
        """
        Blocking check — call from the UI thread only via a button.
        Returns UpdateInfo if newer, None if already up to date or on error.
        """
        return self._fetch()

    # ── Internal ──────────────────────────────────────────────────────

    def _run(self, delay_s: float) -> None:
        if delay_s:
            threading.Event().wait(delay_s)
        result = self._fetch()
        if result:
            try:
                self._on_update(result)
            except Exception as e:
                log.warning(f"Update callback error: {e}")

    def _fetch(self) -> Optional[UpdateInfo]:
        try:
            req = urllib.request.Request(
                UPDATE_CHECK_URL,
                headers={
                    "Accept":     "application/vnd.github+json",
                    "User-Agent": f"SanjINSIGHT/{__version__}",
                })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            remote_version = data.get("tag_name", "").lstrip("v")
            if not remote_version:
                self._on_error("Unexpected API response — no tag_name")
                return None

            if not is_newer(remote_version):
                log.debug(f"Up to date (running {__version__}, latest {remote_version})")
                self._on_no_update()
                return None

            # Find Windows installer asset
            assets       = data.get("assets", [])
            download_url = RELEASES_PAGE_URL   # fallback to releases page
            for asset in assets:
                name = asset.get("name", "")
                if name.lower().endswith(".exe") and "setup" in name.lower():
                    download_url = asset.get("browser_download_url", download_url)
                    break

            info = UpdateInfo(
                version       = remote_version,
                release_notes = data.get("body", "_No release notes provided._"),
                download_url  = download_url,
                release_url   = data.get("html_url", RELEASES_PAGE_URL),
                is_prerelease = data.get("prerelease", False),
            )
            log.info(f"Update available: v{remote_version} (running v{__version__})")
            return info

        except urllib.error.URLError as e:
            self._on_error(f"Network error: {e.reason}")
        except json.JSONDecodeError as e:
            self._on_error(f"Malformed API response: {e}")
        except Exception as e:
            self._on_error(f"Unexpected error: {e}")
        return None


def should_check_on_startup(prefs) -> bool:
    """
    Returns True if auto-update checks are enabled in user preferences.
    prefs is the config module (has get_pref / set_pref).
    Defaults to True — new installs check automatically.
    """
    return prefs.get_pref("updates.auto_check", True)


def get_check_frequency(prefs) -> str:
    """Returns 'always' | 'daily' | 'weekly'. Default: 'always'."""
    return prefs.get_pref("updates.frequency", "always")


def should_check_now(prefs) -> bool:
    """
    Combines auto_check + frequency to decide if a check is due.
    'always'  → check every launch
    'daily'   → check once per calendar day
    'weekly'  → check once per week
    """
    import datetime
    if not should_check_on_startup(prefs):
        return False

    freq = get_check_frequency(prefs)
    if freq == "always":
        return True

    last_check_str = prefs.get_pref("updates.last_check_date", "")
    if not last_check_str:
        return True

    try:
        last = datetime.date.fromisoformat(last_check_str)
        today = datetime.date.today()
        delta = (today - last).days
        if freq == "daily":
            return delta >= 1
        if freq == "weekly":
            return delta >= 7
    except ValueError:
        return True

    return False


def record_check_date(prefs) -> None:
    """Save today's date so frequency logic knows when the last check was."""
    import datetime
    prefs.set_pref("updates.last_check_date",
                   datetime.date.today().isoformat())
