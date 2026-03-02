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

_LOG_DIR  = Path.home() / ".microsanj" / "logs"
_LOG_FILE = _LOG_DIR / "sanjinsight.log"

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


def log_path() -> Path:
    """Return the current log file path (for display in Settings / About)."""
    return _LOG_FILE
