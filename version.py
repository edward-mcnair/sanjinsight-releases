"""
version.py — Single source of truth for SanjINSIGHT versioning.

Rules
-----
* This is the ONLY file that defines the version number.
* All other code imports from here — never hardcode a version string elsewhere.
* Bump this before every release commit, then tag the commit in Git:
      git tag -a v0.43.0-beta.1 -m "Beta 0.43.0-beta.1"
      git push origin v0.43.0-beta.1
* The GitHub release pipeline reads this tag to publish the installer.

Versioning scheme: Semantic Versioning  MAJOR.MINOR.PATCH[-PRERELEASE]
  MAJOR      — breaking change or major new capability
  MINOR      — new features, backwards-compatible
  PATCH      — bug fixes only
  PRERELEASE — "beta.N" or "rc.N" while the product is in active testing.
               Omit for general-availability (GA) releases.
               Ordering: beta.1 < beta.2 < rc.1 < rc.2 < GA
                 0.43.0-beta.1  <  0.43.0-beta.2  <  0.43.0-rc.1  <  0.43.0

Prerelease numbering was reset from the 1.50.x-beta track to 0.43.0-beta.1
in April 2026.  No migration logic from the old numbering exists — the two
existing beta users performed a one-time manual install.
"""

from __future__ import annotations

import re as _re

# ── Version number ────────────────────────────────────────────────────────────
__version__    = "0.44.0-beta.1"
PRERELEASE     = "beta.1"           # empty string "" for GA releases
BUILD_DATE     = "2026-04-10"       # set by CI/CD on release; update manually otherwise

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
UPDATE_CHECK_ALL_URL = f"https://api.github.com/repos/{RELEASES_REPO}/releases?per_page=10"
RELEASES_PAGE_URL   = f"https://github.com/{RELEASES_REPO}/releases"
DOCS_URL            = f"https://docs.microsanj.com/sanjinsight"
SUPPORT_EMAIL       = "software-support@microsanj.com"

# Expected installer filename pattern.  Used by the updater for tight asset
# matching instead of loose heuristics.
INSTALLER_PATTERN   = _re.compile(
    r"^SanjINSIGHT-Setup-[\d]+\.[\d]+\.[\d]+(?:-[\w.]+)?\.exe$", _re.IGNORECASE)


# ── Semver parsing and comparison ─────────────────────────────────────────────
#
# The old version.py used a flat (MAJOR, MINOR, PATCH) tuple and a separate
# PRERELEASE string, with ad-hoc is_newer() logic.  This was fragile:
#   - beta.2 vs beta.1 was not compared
#   - rc.1 vs beta.3 was not compared
#   - the comparison only checked "has prerelease or not"
#
# The new implementation parses the full semver string into a SemVer dataclass
# and compares correctly:
#   0.43.0-beta.1 < 0.43.0-beta.2 < 0.43.0-rc.1 < 0.43.0

# Prerelease type ordering — lower number = earlier in the release cycle.
_PRE_TYPE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}


class SemVer:
    """Parsed semantic version with correct prerelease comparison.

    Instances are fully ordered::

        SemVer.parse("0.43.0-beta.1") < SemVer.parse("0.43.0-beta.2")
        SemVer.parse("0.43.0-beta.2") < SemVer.parse("0.43.0-rc.1")
        SemVer.parse("0.43.0-rc.1")   < SemVer.parse("0.43.0")
    """

    __slots__ = ("major", "minor", "patch", "pre_type", "pre_num", "raw")

    def __init__(self, major: int, minor: int, patch: int,
                 pre_type: str = "", pre_num: int = 0, raw: str = ""):
        self.major    = major
        self.minor    = minor
        self.patch    = patch
        self.pre_type = pre_type   # "beta", "rc", "" (GA)
        self.pre_num  = pre_num    # 1, 2, … (0 for GA)
        self.raw      = raw

    @classmethod
    def parse(cls, s: str) -> "SemVer":
        """Parse a version string like '0.43.0', 'v0.43.0-beta.1', '1.50.47-beta'.

        Handles both dotted ('beta.1') and bare ('beta') prerelease formats.
        A bare 'beta' is treated as 'beta.0' for comparison purposes.
        Returns SemVer(0,0,0) for unparseable input.
        """
        s = s.strip().lstrip("v")
        m = _re.match(
            r"^(\d+)\.(\d+)\.(\d+)"           # MAJOR.MINOR.PATCH
            r"(?:-([A-Za-z]+)(?:\.(\d+))?)?$", # optional -type.N
            s,
        )
        if not m:
            return cls(0, 0, 0, raw=s)
        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
        pre_type = (m.group(4) or "").lower()
        pre_num  = int(m.group(5)) if m.group(5) else 0
        return cls(major, minor, patch, pre_type, pre_num, raw=s)

    @property
    def is_prerelease(self) -> bool:
        return bool(self.pre_type)

    @property
    def numeric_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @property
    def _sort_key(self) -> tuple:
        """Comparison key.  GA sorts AFTER all prereleases of the same version.

        Layout: (major, minor, patch, is_ga, pre_type_order, pre_num)
        is_ga=0 for prerelease, is_ga=1 for GA — so GA always wins a tie.
        """
        if self.pre_type:
            type_order = _PRE_TYPE_ORDER.get(self.pre_type, 99)
            return (self.major, self.minor, self.patch, 0, type_order, self.pre_num)
        else:
            return (self.major, self.minor, self.patch, 1, 0, 0)

    def __eq__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key == other._sort_key

    def __lt__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key < other._sort_key

    def __le__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key <= other._sort_key

    def __gt__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key > other._sort_key

    def __ge__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key >= other._sort_key

    def __repr__(self):
        return f"SemVer({self.raw!r})"

    def __str__(self):
        return self.raw or f"{self.major}.{self.minor}.{self.patch}"


# Parsed version of the running build — used by is_newer() and the updater.
CURRENT_VERSION = SemVer.parse(__version__)

# Legacy compatibility: some code still uses VERSION_TUPLE for numeric checks.
VERSION_TUPLE   = CURRENT_VERSION.numeric_tuple


# ── Public helpers ────────────────────────────────────────────────────────────

def is_prerelease() -> bool:
    """Return True if this build carries a pre-release identifier (beta, rc, etc.)."""
    return CURRENT_VERSION.is_prerelease


def version_string() -> str:
    """Human-readable version:  v0.43.0-beta.1"""
    return f"v{__version__}"


def full_version_string() -> str:
    """Long form for About dialogs:  SanjINSIGHT v0.43.0-beta.1  (built 2026-04-09)"""
    return f"{APP_NAME} {version_string()}  (built {BUILD_DATE})"


def parse_version(s: str) -> tuple:
    """Parse a version string into a numeric (MAJOR, MINOR, PATCH) tuple.

    This is a **legacy** helper kept for backward compatibility.
    New code should use ``SemVer.parse()`` directly for full prerelease
    comparison support.
    """
    sv = SemVer.parse(s)
    return sv.numeric_tuple


def is_newer(remote_version: str) -> bool:
    """Return True if *remote_version* is strictly newer than the running build.

    Uses full semver comparison::

        0.43.0-beta.2  is newer than  0.43.0-beta.1
        0.43.0-rc.1    is newer than  0.43.0-beta.2
        0.43.0         is newer than  0.43.0-rc.1
        0.44.0-beta.1  is newer than  0.43.0
    """
    remote = SemVer.parse(remote_version)
    return remote > CURRENT_VERSION
