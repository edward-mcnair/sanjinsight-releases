"""
updater.py — Background update checker for SanjINSIGHT.

How it works
------------
1. On app startup (if auto-check is enabled in preferences), UpdateChecker
   runs on a background thread and hits the GitHub Releases API.
2. It parses ALL candidate releases from the API, selects the highest
   valid version that is newer than the running build, and emits
   update_available(info).
3. The UI connects to this signal and shows a badge + optional dialog.
4. Nothing is downloaded or installed automatically — the user is always
   in control.

GitHub API endpoint used:
    GET https://api.github.com/repos/edward-mcnair/sanjinsight-releases/releases
    Returns JSON array of releases with tag_name, body, assets[].browser_download_url

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
from dataclasses import dataclass
from typing import Optional, Callable

from version import (
    UPDATE_CHECK_URL, UPDATE_CHECK_ALL_URL, RELEASES_PAGE_URL,
    INSTALLER_PATTERN, SemVer, CURRENT_VERSION, is_newer, __version__,
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
    version:        str            # e.g. "0.43.0-beta.2"
    release_notes:  str            # Markdown text from GitHub release body
    download_url:   str            # Direct .exe URL, or releases page URL
    release_url:    str            # GitHub release HTML page
    is_prerelease:  bool = False
    asset_name:     str  = ""      # matched asset filename (empty = fallback)


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
        self._on_error     = on_error or (lambda msg: log.debug("Update check: %s", msg))
        self._on_no_update = on_no_update or (lambda: None)
        # When True, checks ALL releases (including pre-releases).
        # When False, uses /releases/latest which skips pre-releases.
        # If the current build is itself a pre-release, we force this on
        # so the user isn't stuck on an old beta.
        self._include_pre  = include_prerelease or CURRENT_VERSION.is_prerelease
        # Set to True after a successful API response — used by the
        # caller to decide whether to record the check date.
        self.api_succeeded = False

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
        self._fetch()

    def _fetch(self) -> Optional[UpdateInfo]:
        log.info("─── Update check started ───")
        log.info("  Running version:    %s", __version__)
        log.info("  Parsed as:          %r", CURRENT_VERSION)
        log.info("  include_prerelease: %s", self._include_pre)

        try:
            # Choose endpoint: /releases/latest (stable only) or
            # /releases?per_page=10 (includes pre-releases).
            url = UPDATE_CHECK_ALL_URL if self._include_pre else UPDATE_CHECK_URL
            log.info("  API endpoint:       %s", url)

            req = urllib.request.Request(
                url,
                headers={
                    "Accept":     "application/vnd.github+json",
                    "User-Agent": f"SanjINSIGHT/{__version__}",
                })
            ctx = _ssl_context()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            self.api_succeeded = True
            log.info("  API response OK — got %s release(s)",
                     len(raw) if isinstance(raw, list) else 1)

            # /releases returns a list; /releases/latest returns a single object.
            # Normalise to a list.
            releases = raw if isinstance(raw, list) else [raw]

            # ── Deterministic release selection ──────────────────────
            # Parse ALL candidates, pick the highest version that is
            # newer than the running build.
            best_data = None
            best_ver  = CURRENT_VERSION

            for rel in releases:
                if rel.get("draft", False):
                    log.debug("  [skip] draft release")
                    continue

                tag = rel.get("tag_name", "").lstrip("v")
                if not tag:
                    log.debug("  [skip] release with no tag_name")
                    continue

                sv = SemVer.parse(tag)
                if sv.numeric_tuple == (0, 0, 0):
                    log.debug("  [skip] unparseable tag: %r", tag)
                    continue

                # Filter prereleases if user opted out AND running
                # build is not itself a prerelease.
                if sv.is_prerelease and not self._include_pre:
                    log.debug("  [skip] prerelease %s (user opted out)", tag)
                    continue

                if sv > best_ver:
                    log.info("  [candidate] %s (newer than %s)", tag, best_ver)
                    best_data = rel
                    best_ver  = sv
                else:
                    log.debug("  [skip] %s (not newer than %s)", tag, best_ver)

            if best_data is None:
                log.info("  Result: up to date (running %s)", __version__)
                self._on_no_update()
                return None

            remote_version = best_data.get("tag_name", "").lstrip("v")
            log.info("  Selected release: %s", remote_version)

            # ── Tight asset matching ─────────────────────────────────
            download_url = RELEASES_PAGE_URL   # fallback
            asset_name   = ""

            # Build the exact expected filename for this version
            expected_name = f"SanjINSIGHT-Setup-{remote_version}.exe"

            for asset in best_data.get("assets", []):
                name = asset.get("name", "")
                aurl = asset.get("browser_download_url", "")

                # Prefer exact version match
                if name == expected_name:
                    download_url = aurl
                    asset_name   = name
                    log.info("  Asset exact match: %s", name)
                    break

                # Fall back to pattern match (handles minor naming variations)
                if not asset_name and INSTALLER_PATTERN.match(name):
                    download_url = aurl
                    asset_name   = name
                    log.info("  Asset pattern match: %s", name)

            if not asset_name:
                log.warning("  No matching installer asset found in release %s "
                            "— falling back to release page URL: %s",
                            remote_version, RELEASES_PAGE_URL)

            info = UpdateInfo(
                version       = remote_version,
                release_notes = best_data.get("body",
                                              "_No release notes provided._"),
                download_url  = download_url,
                release_url   = best_data.get("html_url", RELEASES_PAGE_URL),
                is_prerelease = best_data.get("prerelease", False),
                asset_name    = asset_name,
            )
            log.info("  Update available: v%s (download: %s)",
                     remote_version, download_url)
            log.info("─── Update check complete ───")

            try:
                self._on_update(info)
            except Exception as e:
                log.warning("Update callback error: %s", e)
            return info

        except urllib.error.URLError as e:
            log.warning("Update check failed — network error: %s", e.reason)
            self._on_error(f"Network error: {e.reason}")
        except json.JSONDecodeError as e:
            log.warning("Update check failed — malformed API response: %s", e)
            self._on_error(f"Malformed API response: {e}")
        except Exception as e:
            log.warning("Update check failed — unexpected error: %s", e)
            self._on_error(f"Unexpected error: {e}")

        log.info("─── Update check complete (failed) ───")
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
    'always'  -> check every launch
    'daily'   -> check once per calendar day
    'weekly'  -> check once per week

    NOTE: This only decides whether to START a check.  The check date
    is NOT recorded here — it is recorded AFTER a successful API response
    (see main_app.py _start_update_checker).
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
    """Save today's date so frequency logic knows when the last check was.

    This must ONLY be called AFTER a successful API response.
    Failed checks must NOT suppress future checks.
    """
    import datetime
    today = datetime.date.today().isoformat()
    prefs.set_pref("updates.last_check_date", today)
    log.info("Update check date recorded: %s", today)
