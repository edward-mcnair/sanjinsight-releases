"""
version.py — Single source of truth for SanjINSIGHT versioning.

Rules
-----
* This is the ONLY file that defines the version number.
* All other code imports from here — never hardcode a version string elsewhere.
* Bump this before every release commit, then tag the commit in Git:
      git tag -a v1.4.0-beta.1 -m "Beta 1.4.0-beta.1"
      git push origin v1.4.0-beta.1
* The GitHub release pipeline reads this tag to publish the installer.

Versioning scheme: Semantic Versioning  MAJOR.MINOR.PATCH[-PRERELEASE]
  MAJOR      — breaking change or major new capability
  MINOR      — new features, backwards-compatible
  PATCH      — bug fixes only
  PRERELEASE — "beta.N" while the product is in active beta testing.
               Omit for general-availability (GA) releases.
               Beta releases sort BEFORE the corresponding GA release:
                 1.4.0-beta.1  <  1.4.0-beta.2  <  1.4.0
"""

# ── Version number ────────────────────────────────────────────────────────────
__version__    = "1.50.40-beta"
PRERELEASE     = "beta"             # empty string "" for GA releases
VERSION_TUPLE  = (1, 50, 40)        # numeric-only, for < / > comparisons
BUILD_DATE     = "2026-04-08"       # set by CI/CD on release; update manually otherwise

# ── Application identity ──────────────────────────────────────────────────────
APP_NAME       = "SanjINSIGHT"
APP_VENDOR     = "Microsanj"
APP_FULL_NAME  = f"{APP_VENDOR} {APP_NAME}"

# ── Update channel ────────────────────────────────────────────────────────────
# Public releases-only repo (no source code).  The source repo is kept private.
# To publish a new release:
#   1. Build the installer
#   2. Create a GitHub Release on RELEASES_REPO (not the source repo)
#   3. Attach the .exe as a release asset
# The updater hits:  https://api.github.com/repos/{RELEASES_REPO}/releases/latest
SOURCE_REPO         = "edward-mcnair/sanjinsight"          # private — source code
RELEASES_REPO       = "edward-mcnair/sanjinsight-releases" # public  — installers only
GITHUB_REPO         = RELEASES_REPO                        # alias used by updater
UPDATE_CHECK_URL    = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
# /releases (list all) needed when include_prerelease is True, because
# /releases/latest only returns the most recent non-prerelease release.
UPDATE_CHECK_ALL_URL = f"https://api.github.com/repos/{RELEASES_REPO}/releases?per_page=5"
RELEASES_PAGE_URL   = f"https://github.com/{RELEASES_REPO}/releases"
DOCS_URL            = f"https://docs.microsanj.com/sanjinsight"
SUPPORT_EMAIL       = "software-support@microsanj.com"

# ── Helper ────────────────────────────────────────────────────────────────────

import re as _re  # used by is_newer(); import at module level to avoid repeated lazy imports


def is_prerelease() -> bool:
    """Return True if this build carries a pre-release identifier (beta, rc, etc.)."""
    return bool(PRERELEASE)


def version_string() -> str:
    """Human-readable version:  v1.4.0-beta.1"""
    return f"v{__version__}"


def full_version_string() -> str:
    """Long form for About dialogs:  SanjINSIGHT v1.4.0-beta.1  (built 2026-03-19)"""
    return f"{APP_NAME} {version_string()}  (built {BUILD_DATE})"


def parse_version(s: str) -> tuple:
    """
    Parse a version string like '1.2.3', 'v1.2.3', or '1.2.3-beta.1' into a
    comparable numeric tuple (MAJOR, MINOR, PATCH).  Pre-release suffixes are
    ignored for numeric comparison — use is_newer() for update checks.
    Returns (0, 0, 0) if the string is malformed.
    """
    s = s.lstrip("v").strip()
    m = _re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (0, 0, 0)


def is_newer(remote_version: str) -> bool:
    """
    Return True if remote_version is strictly newer than the running version.
    A GA release (1.4.0) is considered newer than the equivalent beta (1.4.0-beta.N)
    because the numeric tuples are equal but the GA has no pre-release suffix.
    """
    remote_tuple = parse_version(remote_version)
    if remote_tuple > VERSION_TUPLE:
        return True
    # Same numeric version: a GA remote is newer than our beta
    if remote_tuple == VERSION_TUPLE and PRERELEASE:
        remote_pre = _re.search(r"-(.+)$", remote_version.lstrip("v"))
        return remote_pre is None   # remote has no pre-release → it's GA → newer
    return False
