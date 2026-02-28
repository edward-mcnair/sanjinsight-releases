"""
version.py — Single source of truth for SanjINSIGHT versioning.

Rules
-----
* This is the ONLY file that defines the version number.
* All other code imports from here — never hardcode a version string elsewhere.
* Bump this before every release commit, then tag the commit in Git:
      git tag -a v1.0.0 -m "Release 1.0.0"
      git push origin v1.0.0
* The GitHub release pipeline reads this tag to publish the installer.

Versioning scheme: Semantic Versioning  MAJOR.MINOR.PATCH
  MAJOR — breaking change or major new capability
  MINOR — new features, backwards-compatible
  PATCH — bug fixes only
"""

# ── Version number ────────────────────────────────────────────────────────────
__version__    = "1.0.0"
VERSION_TUPLE  = (1, 0, 0)          # for numeric comparisons
BUILD_DATE     = "2026-02-28"       # set by CI/CD on release; update manually otherwise

# ── Application identity ──────────────────────────────────────────────────────
APP_NAME       = "SanjINSIGHT"
APP_VENDOR     = "Microsanj"
APP_FULL_NAME  = f"{APP_VENDOR} {APP_NAME}"

# ── Update channel ────────────────────────────────────────────────────────────
# GitHub repo where releases are published.
# The updater hits:  https://api.github.com/repos/{GITHUB_REPO}/releases/latest
GITHUB_REPO         = "edward-mcnair/sanjinsight"
UPDATE_CHECK_URL    = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL   = f"https://github.com/{GITHUB_REPO}/releases"
DOCS_URL            = f"https://docs.microsanj.com/sanjinsight"
SUPPORT_EMAIL       = "support@microsanj.com"

# ── Helper ────────────────────────────────────────────────────────────────────

def version_string() -> str:
    """Human-readable version:  v1.0.0"""
    return f"v{__version__}"


def full_version_string() -> str:
    """Long form for About dialogs:  SanjINSIGHT v1.0.0  (built 2026-02-28)"""
    return f"{APP_NAME} {version_string()}  (built {BUILD_DATE})"


def parse_version(s: str) -> tuple:
    """
    Parse a version string like '1.2.3' or 'v1.2.3' into a comparable tuple.
    Returns (0, 0, 0) if the string is malformed.
    """
    import re
    s = s.lstrip("v").strip()
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (0, 0, 0)


def is_newer(remote_version: str) -> bool:
    """Return True if remote_version is strictly newer than the running version."""
    return parse_version(remote_version) > VERSION_TUPLE
