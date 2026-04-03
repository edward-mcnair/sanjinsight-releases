"""
logging_config.py

Centralised logging setup for SanjINSIGHT.

Call ``setup()`` as the very first thing in ``__main__`` — before QApplication
is created and before ``config`` is imported — so that every log message from
every module (including hardware drivers and background threads) is captured.

Output
------
File   : ~/.microsanj/logs/sanjinsight.log  (5 × 2 MB rotating)
Console: WARNING and above only (suppress with env var SANJINSIGHT_NO_CONSOLE=1)

The file handler is always enabled regardless of the ``log_to_file`` flag in
config.yaml, because field support depends on having a log the customer can
e-mail.  The file stays small (10 MB total) and rotates automatically.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_DIR      = Path.home() / ".microsanj" / "logs"
_LOG_FILE     = _LOG_DIR / "sanjinsight.log"
_SESSION_LOG  = _LOG_DIR / "session.log"
_CLEAN_EXIT   = _LOG_DIR / ".clean_exit"

_FMT = logging.Formatter(
    fmt     = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)


def setup(level: str = "INFO") -> None:
    """Configure application-wide logging.

    Safe to call multiple times — adds the rotating file handler only once.
    The console handler from ``config.basicConfig`` is left in place.
    """
    root = logging.getLogger()

    # Already has a RotatingFileHandler — nothing to do
    if any(isinstance(h, logging.handlers.RotatingFileHandler)
           for h in root.handlers):
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(min(root.level or logging.WARNING, numeric_level))

    # ── Rotating file handler (always on) ─────────────────────────────
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            _LOG_FILE,
            maxBytes   = 2 * 1024 * 1024,   # 2 MB per file
            backupCount= 5,                   # keep 5 rotations = 10 MB total
            encoding   = "utf-8",
        )
        fh.setLevel(numeric_level)
        fh.setFormatter(_FMT)
        root.addHandler(fh)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not create log file %s: %s — logging to console only",
            _LOG_FILE, exc,
        )
        return

    # ── Optional console handler ──────────────────────────────────────
    # Only add if no StreamHandler already exists (config.basicConfig adds one).
    # Set to WARNING so normal INFO chatter doesn't flood stdout/stderr.
    if not any(isinstance(h, logging.StreamHandler) and
               not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        if not os.environ.get("SANJINSIGHT_NO_CONSOLE"):
            ch = logging.StreamHandler()
            ch.setLevel(logging.WARNING)
            ch.setFormatter(_FMT)
            root.addHandler(ch)

    logging.getLogger(__name__).info(
        "Log file: %s  (level=%s)", _LOG_FILE, level.upper()
    )


def set_hardware_debug(enabled: bool) -> None:
    """Toggle hardware-driver debug logging at runtime.

    When *enabled*, all ``hardware.*`` loggers are lowered to DEBUG and
    wire-level TX/RX messages appear in the log file.  When disabled,
    they return to INFO (normal).

    Called from Settings → Diagnostics checkbox and at startup.
    """
    from hardware.hw_debug_log import enable, disable
    if enabled:
        enable()
    else:
        disable()


def log_path() -> Path:
    """Return the current log file path (for display in Settings / About)."""
    return _LOG_FILE


def session_log_path() -> Path:
    """Return the session log path (user-visible messages, one per launch)."""
    return _SESSION_LOG


# ── Session log file (mirrors LogTab to disk) ────────────────────────────

_session_fh = None


def open_session_log() -> None:
    """Open (truncate) the session log for this launch and clear the exit marker.

    Called once at startup, before the MainWindow is created.
    """
    global _session_fh
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Remove the clean-exit marker so a crash leaves it absent
        _CLEAN_EXIT.unlink(missing_ok=True)
        _session_fh = open(_SESSION_LOG, "w", encoding="utf-8", buffering=1)
        import time
        _session_fh.write(
            f"=== SanjINSIGHT session started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except OSError:
        _session_fh = None


def write_session(line: str) -> None:
    """Append a line to the session log (no-op if file not open)."""
    if _session_fh is not None:
        try:
            _session_fh.write(line + "\n")
        except OSError:
            pass


def mark_clean_exit() -> None:
    """Write the clean-exit marker.  Called from MainWindow.closeEvent()."""
    global _session_fh
    try:
        if _session_fh is not None:
            import time
            _session_fh.write(
                f"=== Clean shutdown {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            _session_fh.close()
            _session_fh = None
        _CLEAN_EXIT.write_text("ok", encoding="utf-8")
    except OSError:
        pass


def previous_crash_log() -> str | None:
    """If the previous session crashed, return the session log contents.

    Returns None if the last exit was clean or no session log exists.
    """
    try:
        if _CLEAN_EXIT.exists():
            return None  # previous exit was clean
        if not _SESSION_LOG.exists():
            return None  # no previous session
        text = _SESSION_LOG.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return None
        return text
    except OSError:
        return None
