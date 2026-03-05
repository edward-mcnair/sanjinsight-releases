"""
support/bundle_builder.py

BundleBuilder — assembles a self-contained diagnostic zip archive.

The bundle is intended to be attached to a support email or filed with
a bug report.  It contains everything Microsanj support needs to
diagnose software issues without remote access.

Bundle contents
---------------
::

    sanjinsight_bundle_<timestamp>/
        system_info.json     — OS, Python, app version, git hash
        config_sanitised.yaml— active config with sensitive keys redacted
        device_inventory.json— connected / disconnected device list
        timeline.json        — last 200 events from the in-process bus
        warnings.txt         — WARNING / ERROR lines from the log tail
        sanjinsight.log      — full rotating log file (if present)
        MANIFEST.txt         — bundle metadata (timestamp, app version)

Thread safety
-------------
``BundleBuilder.build()`` is a blocking call and should never be
invoked on the Qt main thread.  Use :class:`BundleWorker` (a QThread)
to keep the UI responsive.

Usage::

    from support.bundle_builder import BundleWorker

    worker = BundleWorker(device_manager)
    worker.progress.connect(label.setText)
    worker.finished.connect(lambda path: ...)
    worker.failed.connect(lambda msg:  ...)
    worker.start()
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from .system_info import collect_system_info

log = logging.getLogger(__name__)

# Keys whose values should be redacted in the sanitised config snapshot
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "auth", "credential", "private_key",
})

# Number of recent events to include in timeline.json
_TIMELINE_EVENTS = 200

# Number of log-file lines to scan for warnings/errors
_LOG_SCAN_LINES = 500


class BundleBuilder:
    """
    Assembles the diagnostic bundle synchronously.

    Parameters
    ----------
    device_manager : DeviceManager | None
        Used to build the device inventory.  If None, the inventory
        section is omitted.
    dest_path : str | Path
        Full path for the output ``.zip`` file.
    progress_cb : callable(str), optional
        Called with short status strings during construction.
    """

    def __init__(
        self,
        device_manager=None,
        dest_path: Optional[str | Path] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ):
        self._dm          = device_manager
        self._dest        = Path(dest_path) if dest_path else self._default_path()
        self._progress_cb = progress_cb or (lambda msg: None)

    # ── Public ────────────────────────────────────────────────────────

    def build(self) -> Path:
        """
        Build the bundle zip.

        Returns
        -------
        Path
            The path of the written ``.zip`` file.

        Raises
        ------
        Exception
            On any unrecoverable write error.
        """
        self._dest.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file first; rename atomically on success.
        tmp_path = self._dest.with_suffix(".tmp.zip")
        try:
            with zipfile.ZipFile(tmp_path, "w",
                                 compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=True) as zf:
                prefix = self._prefix()
                self._write_manifest(zf, prefix)
                self._write_system_info(zf, prefix)
                self._write_config(zf, prefix)
                self._write_device_inventory(zf, prefix)
                self._write_timeline(zf, prefix)
                self._write_warnings(zf, prefix)
                self._write_log(zf, prefix)

            os.replace(tmp_path, self._dest)
            log.info("BundleBuilder: bundle written to %s", self._dest)
            return self._dest

        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise

    # ── Section writers ───────────────────────────────────────────────

    def _write_manifest(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Writing MANIFEST.txt …")
        sysinfo = collect_system_info()
        text = (
            f"SanjINSIGHT Support Bundle\n"
            f"==========================\n"
            f"Created    : {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
            f"App version: {sysinfo.get('app_version', 'unknown')}\n"
            f"Git hash   : {sysinfo.get('app_git_hash', 'n/a')}\n"
            f"OS         : {sysinfo.get('os_name', '')} "
            f"{sysinfo.get('os_release', '')}\n"
            f"Python     : {sysinfo.get('python_version', '')}\n"
        )
        zf.writestr(f"{prefix}/MANIFEST.txt", text)

    def _write_system_info(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Collecting system information …")
        data = collect_system_info()
        zf.writestr(
            f"{prefix}/system_info.json",
            json.dumps(data, indent=2, default=str),
        )

    def _write_config(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Sanitising configuration …")
        try:
            import config as cfg_mod
            import yaml
            raw = cfg_mod._config or {}
            sanitised = _sanitise_dict(raw)
            text = yaml.safe_dump(sanitised, default_flow_style=False,
                                  allow_unicode=True)
        except Exception as exc:
            text = f"# Could not read config: {exc}\n"
        zf.writestr(f"{prefix}/config_sanitised.yaml", text)

    def _write_device_inventory(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Building device inventory …")
        try:
            if self._dm is None:
                inventory = {"note": "DeviceManager not available"}
            else:
                inventory = {
                    "devices": [e.to_dict() for e in self._dm.all()],
                    "safe_mode":        self._dm.safe_mode,
                    "safe_mode_reason": self._dm.safe_mode_reason,
                }
        except Exception as exc:
            inventory = {"error": str(exc)}
        zf.writestr(
            f"{prefix}/device_inventory.json",
            json.dumps(inventory, indent=2, default=str),
        )

    def _write_timeline(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Exporting event timeline …")
        try:
            from events import timeline
            text = timeline.export_json(n=_TIMELINE_EVENTS)
        except Exception as exc:
            text = json.dumps({"error": str(exc)})
        zf.writestr(f"{prefix}/timeline.json", text)
        try:
            from events import emit_info, EVT_BUNDLE_COMPLETE
            emit_info("support.bundle_builder", EVT_BUNDLE_COMPLETE,
                      "Support bundle written", path=str(self._dest))
        except Exception:
            pass

    def _write_warnings(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Extracting warnings and errors …")
        try:
            from logging_config import log_path
            p = log_path()
            if not p.exists():
                zf.writestr(f"{prefix}/warnings.txt",
                            "(log file not found)\n")
                return
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            tail  = lines[-_LOG_SCAN_LINES:]
            warns = [l for l in tail
                     if re.search(r"\bWARNING\b|\bERROR\b|\bCRITICAL\b",
                                  l, re.IGNORECASE)]
            text  = "\n".join(warns) or "(no warnings or errors found)\n"
        except Exception as exc:
            text = f"(could not read warnings: {exc})"
        zf.writestr(f"{prefix}/warnings.txt", text)

    def _write_log(self, zf: zipfile.ZipFile, prefix: str) -> None:
        self._progress_cb("Attaching log file …")
        try:
            from logging_config import log_path
            p = log_path()
            if p.exists():
                zf.write(str(p), arcname=f"{prefix}/sanjinsight.log")
            else:
                zf.writestr(f"{prefix}/sanjinsight.log",
                            "(log file not found)\n")
        except Exception as exc:
            log.debug("BundleBuilder: could not attach log: %s", exc)
            zf.writestr(f"{prefix}/sanjinsight.log",
                        f"(could not attach log: {exc})\n")

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _default_path() -> Path:
        ts   = time.strftime("%Y%m%d_%H%M%S")
        name = f"sanjinsight_bundle_{ts}.zip"
        return Path.home() / "Desktop" / name

    @staticmethod
    def _prefix() -> str:
        return f"sanjinsight_bundle_{time.strftime('%Y%m%d_%H%M%S')}"


# ── Qt worker ─────────────────────────────────────────────────────────────────


class BundleWorker(QThread):
    """
    QThread wrapper around :class:`BundleBuilder`.

    Signals
    -------
    progress(str)  — short status message for the UI label
    finished(str)  — emitted with the bundle path string on success
    failed(str)    — emitted with an error message on failure
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(str)   # bundle path
    failed   = pyqtSignal(str)   # error message

    def __init__(self, device_manager=None, dest_path=None, parent=None):
        super().__init__(parent)
        self._dm   = device_manager
        self._dest = dest_path

    def run(self) -> None:
        try:
            from events import emit_info, EVT_BUNDLE_START
            emit_info("support.bundle_builder", EVT_BUNDLE_START,
                      "Support bundle creation started")
        except Exception:
            pass

        try:
            builder = BundleBuilder(
                device_manager=self._dm,
                dest_path=self._dest,
                progress_cb=lambda msg: self.progress.emit(msg),
            )
            path = builder.build()
            self.finished.emit(str(path))
        except Exception as exc:
            log.error("BundleWorker: bundle creation failed: %s", exc,
                      exc_info=True)
            try:
                from events import emit_error, EVT_BUNDLE_FAILED
                emit_error("support.bundle_builder", EVT_BUNDLE_FAILED,
                           f"Bundle creation failed: {exc}")
            except Exception:
                pass
            self.failed.emit(str(exc))


# ── Utility ───────────────────────────────────────────────────────────────────


def _sanitise_dict(d: dict) -> dict:
    """Recursively redact values whose key matches _SENSITIVE_KEYS."""
    out = {}
    for k, v in d.items():
        if any(s in k.lower() for s in _SENSITIVE_KEYS):
            out[k] = "***REDACTED***"
        elif isinstance(v, dict):
            out[k] = _sanitise_dict(v)
        else:
            out[k] = v
    return out
