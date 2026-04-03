"""
hardware/hw_debug_log.py — Centralised hardware debug-logging helpers.

Every hardware driver imports ``hw_log`` from this module and uses it to
emit wire-level TX/RX messages, command timing, and connection diagnostics.

The ``enable()`` / ``disable()`` functions toggle **all** ``hardware.*``
loggers between DEBUG and INFO at runtime.  The toggle is wired to the
"Hardware debug logging" checkbox in Settings → Diagnostics and persisted
in the user's preferences (``logging.hardware_debug``).

Usage in a driver::

    from hardware.hw_debug_log import hw_log

    hw_log.tx(log, "set,1,50.000")       # logs TX bytes
    hw_log.rx(log, "rk,1,50.001")        # logs RX bytes
    with hw_log.timed(log, "rk query"):  # logs round-trip time
        resp = ser.read_until(b"\\r")
    hw_log.connect_ok(log, port="/dev/cu.usbmodem14101", baud=19200, extra="closed-loop")
    hw_log.connect_fail(log, port="COM3", error=exc, attempts=2)
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

_HW_ROOT = "hardware"
_active = False

# ── Toggle API ──────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """Return *True* if hardware debug logging is currently active."""
    return _active


def enable() -> None:
    """Set all ``hardware.*`` loggers to DEBUG."""
    global _active
    _active = True
    logging.getLogger(_HW_ROOT).setLevel(logging.DEBUG)
    logging.getLogger(_HW_ROOT).debug(
        "Hardware debug logging ENABLED — wire-level TX/RX will appear in the log file")


def disable() -> None:
    """Restore ``hardware.*`` loggers to INFO (default)."""
    global _active
    _active = False
    logging.getLogger(_HW_ROOT).setLevel(logging.INFO)
    logging.getLogger(_HW_ROOT).info("Hardware debug logging disabled")


def apply_from_prefs() -> None:
    """Read the saved preference and apply the appropriate level.

    Call once at startup (after ``logging_config.setup()``).
    """
    try:
        import config as cfg_mod
        if cfg_mod.get_pref("logging.hardware_debug", False):
            enable()
    except Exception:
        pass  # config not loaded yet — stay at default


# ── Logging helpers ──────────────────────────────────────────────────────────

def tx(logger: logging.Logger, data: str | bytes, *, label: str = "") -> None:
    """Log a transmitted (sent) frame or command at DEBUG level."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    prefix = f"[{label}] " if label else ""
    if isinstance(data, bytes):
        logger.debug("%sTX → %r  (%d bytes)", prefix, data, len(data))
    else:
        logger.debug("%sTX → %s", prefix, data)


def rx(logger: logging.Logger, data: str | bytes, *, label: str = "") -> None:
    """Log a received frame or response at DEBUG level."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    prefix = f"[{label}] " if label else ""
    if isinstance(data, bytes):
        logger.debug("%sRX ← %r  (%d bytes)", prefix, data, len(data))
    else:
        logger.debug("%sRX ← %s", prefix, data)


@contextlib.contextmanager
def timed(logger: logging.Logger, operation: str = "command"):
    """Context manager that logs elapsed time for a serial round-trip.

    Usage::

        with hw_log.timed(log, "rk query"):
            resp = ser.read_until(b"\\r")
    """
    t0 = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s completed in %.1f ms", operation, elapsed_ms)


def connect_ok(
    logger: logging.Logger,
    *,
    port: str = "",
    host: str = "",
    baud: int = 0,
    address: int | None = None,
    extra: str = "",
) -> None:
    """Log a structured connection-success summary at INFO level."""
    parts: list[str] = []
    if port:
        parts.append(f"port={port}")
    if host:
        parts.append(f"host={host}")
    if baud:
        parts.append(f"baud={baud}")
    if address is not None:
        parts.append(f"addr={address}")
    if extra:
        parts.append(extra)
    logger.info("Connected  (%s)", ", ".join(parts))


def connect_fail(
    logger: logging.Logger,
    *,
    port: str = "",
    host: str = "",
    error: BaseException | str = "",
    attempts: int = 1,
    context: dict[str, Any] | None = None,
) -> None:
    """Log a structured connection-failure summary at WARNING level.

    Includes optional diagnostic context dict for the support bundle.
    """
    parts: list[str] = []
    if port:
        parts.append(f"port={port}")
    if host:
        parts.append(f"host={host}")
    parts.append(f"attempts={attempts}")
    if context:
        parts.append(f"ctx={context}")
    logger.warning("Connect FAILED  (%s): %s", ", ".join(parts), error)
