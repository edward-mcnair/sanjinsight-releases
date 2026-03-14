"""
ui/crash_reporter.py

Structured crash reporting for SanjINSIGHT.

Installs a sys.excepthook that captures all unhandled exceptions and writes
a machine-readable crash report to ~/.microsanj/crashes/crash_<timestamp>.txt.

Each report contains:
  - SanjINSIGHT version + build date
  - Python version + OS + platform
  - Active hardware driver names + connection state  (from app_state)
  - Last 50 lines from the application log buffer
  - Full traceback

Usage (call once from main_app.main()):
    from ui.crash_reporter import install_crash_reporter
    install_crash_reporter(app_state)
"""

from __future__ import annotations

import datetime
import logging
import os
import platform
import sys
import traceback
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CRASH_DIR = Path.home() / ".microsanj" / "crashes"

# ── In-memory log buffer (populated by _BufferHandler below) ──────────────────

_LOG_BUFFER: list[str] = []
_BUFFER_CAPACITY = 50   # keep the last 50 log lines


class _BufferHandler(logging.Handler):
    """Appends formatted log records to the module-level _LOG_BUFFER list."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            _LOG_BUFFER.append(line)
            if len(_LOG_BUFFER) > _BUFFER_CAPACITY:
                _LOG_BUFFER.pop(0)
        except Exception:
            pass


def _attach_log_buffer() -> None:
    """Add _BufferHandler to the root logger (called once at install time)."""
    handler = _BufferHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)


# ── Crash report writer ───────────────────────────────────────────────────────

def _write_report(
    exc_type,
    exc_value,
    exc_tb,
    app_state=None,
) -> Optional[Path]:
    """Build and write the crash report file. Returns the Path on success."""
    try:
        from version import __version__, BUILD_DATE
    except ImportError:
        __version__ = "unknown"
        BUILD_DATE  = "unknown"

    try:
        _CRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts        = datetime.datetime.now()
        ts_str    = ts.strftime("%Y%m%d_%H%M%S")
        filename  = _CRASH_DIR / f"crash_{ts_str}.txt"

        lines: list[str] = []

        # ── Header ────────────────────────────────────────────────────
        lines += [
            "=" * 72,
            f"SanjINSIGHT Crash Report  —  {ts.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 72,
            "",
            "VERSION",
            f"  SanjINSIGHT : {__version__}  (built {BUILD_DATE})",
            f"  Python      : {sys.version}",
            f"  Platform    : {platform.platform()}",
            f"  OS          : {platform.system()} {platform.release()}",
            f"  Machine     : {platform.machine()}",
            "",
        ]

        # ── Hardware state ─────────────────────────────────────────────
        lines.append("HARDWARE STATE")
        if app_state is not None:
            try:
                hw_lines = _describe_hardware(app_state)
                lines += [f"  {l}" for l in hw_lines]
            except Exception as hw_exc:
                lines.append(f"  (could not read app_state: {hw_exc})")
        else:
            lines.append("  (app_state not available)")
        lines.append("")

        # ── Recent log ────────────────────────────────────────────────
        lines.append("RECENT LOG (last 50 lines)")
        if _LOG_BUFFER:
            lines += [f"  {l}" for l in _LOG_BUFFER]
        else:
            lines.append("  (log buffer empty)")
        lines.append("")

        # ── Traceback ─────────────────────────────────────────────────
        lines.append("TRACEBACK")
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        for tb_line in tb_lines:
            lines += [f"  {l}" for l in tb_line.splitlines()]
        lines.append("")
        lines.append("=" * 72)

        filename.write_text("\n".join(lines), encoding="utf-8")
        return filename

    except Exception as write_exc:
        # Never let crash reporter itself crash the process
        try:
            print(f"[crash_reporter] Failed to write report: {write_exc}",
                  file=sys.stderr)
        except Exception:
            pass
        return None


def _describe_hardware(app_state) -> list[str]:
    """Return human-readable lines describing active hardware drivers."""
    lines: list[str] = []

    def _fmt(label: str, driver) -> str:
        if driver is None:
            return f"{label:<16} : (not connected)"
        name = type(driver).__name__
        return f"{label:<16} : {name}"

    lines.append(_fmt("Camera",    getattr(app_state, "cam",    None)))
    lines.append(_fmt("FPGA",      getattr(app_state, "fpga",   None)))
    lines.append(_fmt("Bias",      getattr(app_state, "bias",   None)))
    lines.append(_fmt("Stage",     getattr(app_state, "stage",  None)))
    lines.append(_fmt("Turret",    getattr(app_state, "turret", None)))
    lines.append(f"{'Demo mode':<16} : {getattr(app_state, 'demo_mode', False)}")

    tecs = getattr(app_state, "tecs", [])
    if tecs:
        for i, tec in enumerate(tecs):
            lines.append(_fmt(f"TEC[{i}]", tec))
    else:
        lines.append("TEC              : (none)")

    return lines


# ── Public install function ───────────────────────────────────────────────────

def install_crash_reporter(app_state=None) -> None:
    """
    Install the SanjINSIGHT crash reporter.

    Call once from ``main_app.main()`` immediately after the QApplication
    is created.  Installs:
      1. A log buffer handler on the root logger (captures the last 50 lines).
      2. A ``sys.excepthook`` that writes a crash report on any unhandled exception.

    Args:
        app_state : The ApplicationState singleton (optional but strongly
                    recommended — includes hardware driver names in the report).
    """
    _attach_log_buffer()

    _app_state_ref = app_state   # captured by closure

    def _hook(exc_type, exc_value, exc_tb):
        # Skip KeyboardInterrupt — not a crash
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        path = _write_report(exc_type, exc_value, exc_tb, _app_state_ref)

        # Always print the original traceback to stderr so it's visible
        # in the terminal / log file even if the GUI is gone.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

        if path:
            print(
                f"\n[SanjINSIGHT] Crash report saved to:\n  {path}\n"
                f"Please send this file to Microsanj support.",
                file=sys.stderr,
            )

        # Show a Qt message box if a QApplication is still alive
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                mb = QMessageBox()
                mb.setWindowTitle("SanjINSIGHT — Unexpected Error")
                mb.setIcon(QMessageBox.Critical)
                mb.setText(
                    "<b>SanjINSIGHT encountered an unexpected error and needs to close.</b>"
                )
                detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                if path:
                    detail += f"\n\nCrash report saved to:\n{path}"
                mb.setDetailedText(detail)
                mb.exec_()
        except Exception:
            pass

    sys.excepthook = _hook
    log.info("crash_reporter: installed (crash dir: %s)", _CRASH_DIR)
