"""
hardware/support_bundle.py

Diagnostic support bundle generator.

Collects system info, device state, config, and logs into a zip archive
that users can send to support for troubleshooting.  Can be triggered
manually (Help menu) or automatically after repeated connection failures.

Pure Python + stdlib — no Qt in the generator itself (the trigger is a
QObject for signal integration).

Usage
-----
    # Manual generation
    from hardware.support_bundle import generate_support_bundle
    path = generate_support_bundle()
    print(f"Bundle saved to {path}")

    # Auto-trigger (wired via HardwareService)
    trigger = SupportBundleTrigger()
    trigger.bundle_suggested.connect(on_bundle_suggested)
    trigger.on_device_error(dev_err)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import platform
import socket
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_BUNDLE_DIR = Path.home() / ".microsanj" / "support_bundles"
_LOG_DIR    = Path.home() / ".microsanj" / "logs"
_CACHE_FILE = Path.home() / ".microsanj" / "device_cache.json"
_PREFS_FILE = Path.home() / ".microsanj" / "preferences.json"


def generate_support_bundle(
    error_context: Optional[list] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Generate a diagnostic support bundle as a zip archive.

    Parameters
    ----------
    error_context : list[DeviceError] | None
        Recent structured errors to include in the bundle.
    output_dir : Path | None
        Override output directory (default: ``~/.microsanj/support_bundles/``).

    Returns
    -------
    Path
        Path to the generated zip file.
    """
    out = output_dir or _BUNDLE_DIR
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out / f"sanjinsight_support_{ts}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_system_info(zf)
        _add_python_info(zf)
        _add_config(zf)
        _add_device_cache(zf)
        _add_serial_ports(zf)
        _add_network_info(zf)
        _add_logs(zf)
        _add_discovery_report(zf)
        if error_context:
            _add_error_context(zf, error_context)

    log.info("Support bundle generated: %s (%.1f KB)",
             zip_path, zip_path.stat().st_size / 1024)
    return zip_path


# ── Section collectors ──────────────────────────────────────────────────────

def _add_system_info(zf: zipfile.ZipFile) -> None:
    info = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version,
        "executable": sys.executable,
        "frozen": getattr(sys, "frozen", False),
        "hostname": socket.gethostname(),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    zf.writestr("system_info.json", json.dumps(info, indent=2))


def _add_python_info(zf: zipfile.ZipFile) -> None:
    """Installed packages (pip list equivalent) and key versions."""
    packages = {}
    try:
        import importlib.metadata
        for dist in importlib.metadata.distributions():
            packages[dist.metadata["Name"]] = dist.version
    except Exception:
        packages["error"] = "Could not enumerate installed packages"

    # Highlight key hardware packages
    key_pkgs = [
        "pypylon", "pyMeCom", "mecom", "pyvisa", "pyvisa-py",
        "nifpga", "pyserial", "thorlabs-apt-device", "pydp832",
        "opencv-python", "flirpy", "PySpin", "spinnaker-python",
        "numpy", "scipy", "PyQt5",
    ]
    key_versions = {}
    for pkg in key_pkgs:
        # Package names may differ in case
        for name, ver in packages.items():
            if name.lower().replace("-", "_") == pkg.lower().replace("-", "_"):
                key_versions[pkg] = ver
                break
        else:
            key_versions[pkg] = "NOT INSTALLED"

    zf.writestr("python_packages.json", json.dumps({
        "key_packages": key_versions,
        "all_packages_count": len(packages),
        "all_packages": dict(sorted(packages.items())),
    }, indent=2))


def _add_config(zf: zipfile.ZipFile) -> None:
    """Sanitized hardware config (passwords/keys redacted)."""
    try:
        import config as cfg_mod
        raw = cfg_mod.get("hardware") or {}
        sanitized = _sanitize_dict(raw)
        zf.writestr("hardware_config.json", json.dumps(sanitized, indent=2))
    except Exception as exc:
        zf.writestr("hardware_config.json",
                     json.dumps({"error": str(exc)}))


def _add_device_cache(zf: zipfile.ZipFile) -> None:
    try:
        if _CACHE_FILE.exists():
            zf.write(_CACHE_FILE, "device_cache.json")
    except Exception:
        pass


def _add_serial_ports(zf: zipfile.ZipFile) -> None:
    """List all serial ports with VID/PID and descriptions."""
    ports_info = []
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            ports_info.append({
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "vid": f"0x{p.vid:04x}" if p.vid else None,
                "pid": f"0x{p.pid:04x}" if p.pid else None,
                "serial_number": p.serial_number,
                "manufacturer": p.manufacturer,
            })
    except ImportError:
        ports_info = [{"error": "pyserial not installed"}]
    except Exception as exc:
        ports_info = [{"error": str(exc)}]
    zf.writestr("serial_ports.json", json.dumps(ports_info, indent=2))


def _add_network_info(zf: zipfile.ZipFile) -> None:
    """Basic network adapter info for GigE camera / Ethernet instrument support."""
    info = {}
    try:
        info["hostname"] = socket.gethostname()
        info["fqdn"] = socket.getfqdn()
        # Get all addresses for hostname
        try:
            addrs = socket.getaddrinfo(socket.gethostname(), None)
            info["addresses"] = list({
                addr[4][0] for addr in addrs
                if not addr[4][0].startswith("fe80")  # skip link-local IPv6
            })
        except Exception:
            info["addresses"] = []
    except Exception as exc:
        info["error"] = str(exc)
    zf.writestr("network_info.json", json.dumps(info, indent=2))


def _add_logs(zf: zipfile.ZipFile) -> None:
    """Last 500 lines from each log file in ~/.microsanj/logs/."""
    if not _LOG_DIR.exists():
        return
    for log_file in sorted(_LOG_DIR.glob("*.log*"))[:5]:  # cap at 5 files
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-500:])
            zf.writestr(f"logs/{log_file.name}", tail)
        except Exception:
            pass


def _add_discovery_report(zf: zipfile.ZipFile) -> None:
    """Run a quick discovery scan and include results."""
    try:
        from hardware.discovery_engine import DiscoveryEngine
        engine = DiscoveryEngine()
        report = engine.discover(use_cache=True, probe_timeout=1.0)
        report_dict = {
            "resolved": [
                {
                    "device_uid": d.device_uid,
                    "display_name": d.display_name,
                    "port": d.port,
                    "confidence": d.confidence,
                    "serial_number": d.serial_number,
                }
                for d in report.resolved
            ],
            "unresolved_ports": report.unresolved_ports,
            "errors": report.errors,
            "scan_duration_s": report.scan_duration_s,
        }
        zf.writestr("discovery_report.json", json.dumps(report_dict, indent=2))
    except Exception as exc:
        zf.writestr("discovery_report.json",
                     json.dumps({"error": str(exc)}))


def _add_error_context(zf: zipfile.ZipFile, errors: list) -> None:
    """Include recent structured DeviceError objects."""
    error_list = []
    for err in errors:
        try:
            if hasattr(err, "category"):
                error_list.append({
                    "category": err.category.value,
                    "device_uid": err.device_uid,
                    "message": err.message,
                    "suggested_fix": err.suggested_fix,
                    "raw_exception": err.raw_exception,
                    "exception_type": err.exception_type,
                })
            else:
                error_list.append({"raw": str(err)})
        except Exception:
            error_list.append({"raw": str(err)})
    zf.writestr("error_context.json", json.dumps(error_list, indent=2))


# ── Helpers ──────────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = {"password", "secret", "token", "key", "api_key", "apikey"}


def _sanitize_dict(d: dict) -> dict:
    """Recursively redact sensitive keys."""
    out = {}
    for k, v in d.items():
        if any(s in k.lower() for s in _SENSITIVE_KEYS):
            out[k] = "***REDACTED***"
        elif isinstance(v, dict):
            out[k] = _sanitize_dict(v)
        else:
            out[k] = v
    return out


# ── Auto-trigger (Qt) ──────────────────────────────────────────────────────

try:
    from PyQt5.QtCore import QObject, pyqtSignal

    class SupportBundleTrigger(QObject):
        """Tracks per-device failure counts and suggests bundle generation.

        Emits ``bundle_suggested(device_uid, reason)`` after
        ``_FAILURE_THRESHOLD`` consecutive failures for the same device.
        """

        bundle_suggested = pyqtSignal(str, str)   # (device_uid, reason)

        _FAILURE_THRESHOLD = 3

        def __init__(self, parent=None):
            super().__init__(parent)
            self._failure_counts: dict[str, int] = {}
            self._recent_errors: list = []

        def on_device_error(self, dev_err) -> None:
            """Called when a structured DeviceError is emitted."""
            uid = getattr(dev_err, "device_uid", "") or "unknown"
            self._failure_counts[uid] = self._failure_counts.get(uid, 0) + 1
            self._recent_errors.append(dev_err)
            # Cap stored errors
            if len(self._recent_errors) > 50:
                self._recent_errors = self._recent_errors[-30:]

            if self._failure_counts[uid] == self._FAILURE_THRESHOLD:
                reason = (
                    f"{uid} has failed to connect {self._FAILURE_THRESHOLD} times. "
                    "A support bundle can help diagnose the issue."
                )
                self.bundle_suggested.emit(uid, reason)

        def reset(self, device_uid: str) -> None:
            """Reset failure count for a device (e.g. on successful connect)."""
            self._failure_counts.pop(device_uid, None)

        @property
        def recent_errors(self) -> list:
            """Return recent errors for inclusion in bundle."""
            return list(self._recent_errors)

except ImportError:
    # No Qt available (CLI usage) — provide a no-op stub
    class SupportBundleTrigger:  # type: ignore[no-redef]
        def on_device_error(self, dev_err): pass
        def reset(self, device_uid: str): pass
        recent_errors = []
