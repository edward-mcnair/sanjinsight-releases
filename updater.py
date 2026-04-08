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
    GET https://api.github.com/repos/edward-mcnair/sanjinsight-releases/releases/latest
    Returns JSON with tag_name, body (markdown release notes), assets[].browser_download_url

Release workflow
----------------
Source code lives in a private repo (edward-mcnair/sanjinsight).
Releases are published to a separate PUBLIC repo (edward-mcnair/sanjinsight-releases)
so the update checker can reach the API without authentication.

To publish a release:
1. Build the Windows installer (.exe)
2. Go to github.com/edward-mcnair/sanjinsight-releases/releases/new
3. Tag: v{version}  |  Title: SanjINSIGHT v{version}
4. Paste the CHANGELOG.md section as the release body
5. Attach SanjINSIGHT-Setup-{version}.exe as a release asset
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional, Callable

from version import (
    UPDATE_CHECK_URL, UPDATE_CHECK_ALL_URL, RELEASES_PAGE_URL,
    is_newer, parse_version, __version__, PRERELEASE,
)

log = logging.getLogger(__name__)

# Seconds to wait before the first update check (let the UI finish loading)
_STARTUP_DELAY_S = 8


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works in PyInstaller-frozen builds.

    PyInstaller bundles may not find the system CA certificates.
    We try certifi first (pip-installed CA bundle), then the default
    system context, then fall back to unverified as a last resort
    (with a warning).
    """
    # 1. Try certifi (bundled by pip-install or PyInstaller hook)
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except (ImportError, OSError):
        pass

    # 2. Try default system context
    try:
        ctx = ssl.create_default_context()
        return ctx
    except ssl.SSLError:
        pass

    # 3. Fallback — allow unverified (only for update check, not general use)
    log.warning("SSL certificate verification unavailable — using unverified "
                "context for update check only")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


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
        include_prerelease: bool = False,
    ):
        self._on_update    = on_update
        self._on_error     = on_error or (lambda msg: log.debug(f"Update check: {msg}"))
        self._on_no_update = on_no_update or (lambda: None)
        # When True, checks ALL releases (including pre-releases).
        # When False, uses /releases/latest which skips pre-releases.
        # Users on a beta channel should always set this to True so they
        # see newer betas.  If the current build is itself a pre-release
        # we also force this on so the user isn't stuck on an old beta.
        self._include_pre  = include_prerelease or bool(PRERELEASE)

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
            time.sleep(delay_s)
        self._fetch()   # callbacks (_on_update / _on_no_update / _on_error) fired inside

    def _fetch(self) -> Optional[UpdateInfo]:
        try:
            # Choose endpoint: /releases/latest (stable only) or
            # /releases?per_page=5 (includes pre-releases).
            url = UPDATE_CHECK_ALL_URL if self._include_pre else UPDATE_CHECK_URL
            log.info("Update check: include_pre=%s, url=%s", self._include_pre, url)
            req = urllib.request.Request(
                url,
                headers={
                    "Accept":     "application/vnd.github+json",
                    "User-Agent": f"SanjINSIGHT/{__version__}",
                })
            ctx = _ssl_context()
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            log.info("Update check: got %s release(s)",
                     len(raw) if isinstance(raw, list) else 1)

            # /releases returns a list; /releases/latest returns a single object.
            # Normalise to a single release dict — pick the newest that is
            # newer than the running version.
            if isinstance(raw, list):
                data = self._pick_best(raw)
                if data is None:
                    log.debug("Up to date — no newer release in list "
                              f"(running {__version__})")
                    self._on_no_update()
                    return None
            else:
                data = raw

            remote_version = data.get("tag_name", "").lstrip("v")
            if not remote_version:
                self._on_error("Unexpected API response — no tag_name")
                return None

            if not is_newer(remote_version):
                log.debug(f"Up to date (running {__version__}, "
                          f"latest {remote_version})")
                self._on_no_update()
                return None

            # Find Windows installer asset
            assets       = data.get("assets", [])
            download_url = RELEASES_PAGE_URL   # fallback to releases page
            for asset in assets:
                name = asset.get("name", "")
                if name.lower().endswith(".exe") and "setup" in name.lower():
                    download_url = asset.get("browser_download_url",
                                             download_url)
                    break

            info = UpdateInfo(
                version       = remote_version,
                release_notes = data.get("body",
                                         "_No release notes provided._"),
                download_url  = download_url,
                release_url   = data.get("html_url", RELEASES_PAGE_URL),
                is_prerelease = data.get("prerelease", False),
            )
            log.info(f"Update available: v{remote_version} "
                     f"(running v{__version__})")
            try:
                self._on_update(info)
            except Exception as e:
                log.warning(f"Update callback error: {e}")
            return info

        except urllib.error.URLError as e:
            self._on_error(f"Network error: {e.reason}")
        except json.JSONDecodeError as e:
            self._on_error(f"Malformed API response: {e}")
        except Exception as e:
            self._on_error(f"Unexpected error: {e}")
        return None

    def _pick_best(self, releases: list) -> Optional[dict]:
        """From a list of GitHub releases, return the newest that is newer
        than the running version, respecting the prerelease preference."""
        for rel in releases:
            if rel.get("draft", False):
                continue
            tag = rel.get("tag_name", "").lstrip("v")
            if not tag:
                continue
            # If user opted out of pre-releases, skip them — unless the
            # running build is itself a pre-release (always show upgrades).
            if rel.get("prerelease", False) and not self._include_pre:
                continue
            if is_newer(tag):
                return rel
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
