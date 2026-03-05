"""
support/system_info.py

Lightweight system-information collector.

Returns a pure-Python dict that can be serialised to JSON and included
in support bundles, run manifests, or the Get Support email dialog.

No Qt dependency — safe to call from any thread.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import time
from typing import Any, Dict

log = logging.getLogger(__name__)


def collect_system_info() -> Dict[str, Any]:
    """
    Return a dict of OS, Python, and application metadata.

    Keys
    ----
    app_name, app_version, app_build_date, app_git_hash
    os_name, os_version, os_release, machine, processor
    python_version, python_impl
    cpu_count, collected_at
    """
    info: Dict[str, Any] = {}

    # ── Application ────────────────────────────────────────────────────
    try:
        import version as _ver
        info["app_name"]       = _ver.APP_NAME
        info["app_version"]    = _ver.version_string()
        info["app_build_date"] = getattr(_ver, "BUILD_DATE", "")
        info["app_git_hash"]   = _git_hash()
    except Exception as exc:
        log.debug("system_info: version import failed: %s", exc)
        info["app_name"]    = "SanjINSIGHT"
        info["app_version"] = "unknown"

    # ── Operating system ───────────────────────────────────────────────
    info["os_name"]    = platform.system()          # Windows / Darwin / Linux
    info["os_version"] = platform.version()
    info["os_release"] = platform.release()
    info["machine"]    = platform.machine()
    info["processor"]  = platform.processor() or "unknown"

    # ── Python ─────────────────────────────────────────────────────────
    info["python_version"] = sys.version.split()[0]
    info["python_impl"]    = platform.python_implementation()

    # ── Hardware resources ─────────────────────────────────────────────
    try:
        info["cpu_count"] = os.cpu_count() or 1
    except Exception:
        info["cpu_count"] = "unknown"

    info["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return info


def _git_hash() -> str:
    """Return the short git hash of HEAD, or '' if git is unavailable."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
