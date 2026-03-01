"""
hardware/port_lock.py

Cross-platform exclusive lock for serial / USB-serial ports.

Purpose
-------
Prevents two processes (or two instances of SanjINSIGHT) from opening
the same COM port / tty simultaneously, which leads to garbled I/O,
silent failures, or firmware-level corruption on some devices.

Usage
-----
    from hardware.port_lock import PortLock

    lock = PortLock("/dev/tty.usbserial-ABC123")
    with lock:
        serial.Serial(port, ...)
        # do work
    # lock released when exiting the 'with' block

    # Or manual acquire/release:
    lock.acquire(timeout_s=3.0)
    try:
        ...
    finally:
        lock.release()

How it works
------------
* Unix / macOS  — writes a PID file to /tmp and uses fcntl.flock()
                  (LOCK_EX | LOCK_NB) for an advisory exclusive lock.
                  The OS releases the lock automatically if the process
                  crashes without calling release().

* Windows       — pyserial's  exclusive=True  requests OS-level exclusive
                  access via CreateFile / GENERIC_READ.  A separate
                  PortLock is still created but is a no-op (pyserial
                  handles it at the driver level).

The lock is per-port-path, not per-PortLock instance, so two PortLock
objects pointing at the same path will serialise correctly.
"""

from __future__ import annotations

import logging
import os
import sys
import time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def exclusive_serial_kwargs() -> dict:
    """Return kwargs to pass to serial.Serial() for exclusive access.

    Usage::

        import serial
        from hardware.port_lock import exclusive_serial_kwargs

        ser = serial.Serial(port, baud, **exclusive_serial_kwargs())

    On pyserial >= 3.3 this passes ``exclusive=True``, which on POSIX sets
    O_EXLOCK / O_NOCTTY, preventing the OS from granting a second open().
    Older pyserial ignores unknown kwargs, so this is safe to always include.
    """
    try:
        import serial
        import inspect
        if "exclusive" in inspect.signature(serial.Serial.__init__).parameters:
            return {"exclusive": True}
    except Exception:
        pass
    return {}


class PortLock:
    """Advisory exclusive lock for a serial port path.

    Parameters
    ----------
    port : str
        The port identifier, e.g. ``/dev/tty.usbserial-ABC123`` or ``COM3``.
    """

    def __init__(self, port: str) -> None:
        self._port = port
        self._fd: object = None          # file descriptor / handle
        self._lock_path: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self, timeout_s: float = 3.0) -> None:
        """Acquire the lock.

        Raises
        ------
        RuntimeError
            If the port is held by another process within *timeout_s*.
        """
        if sys.platform == "win32":
            # pyserial's exclusive=True handles this at the driver level.
            return

        self._lock_path = _lockfile_path(self._port)
        deadline = time.monotonic() + timeout_s
        warned = False

        while True:
            try:
                self._fd = open(self._lock_path, "w")
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Write our PID so users can diagnose stale locks.
                self._fd.write(str(os.getpid()))
                self._fd.flush()
                log.debug("PortLock acquired: %s (lockfile: %s)", self._port, self._lock_path)
                return

            except (IOError, OSError):
                # Lock held by another process.
                try:
                    self._fd.close()
                except Exception:
                    pass
                self._fd = None

                if time.monotonic() >= deadline:
                    holder = _read_pid(self._lock_path)
                    hint = f" (held by PID {holder})" if holder else ""
                    raise RuntimeError(
                        f"Port {self._port!r} is already in use by another process{hint}.\n"
                        f"Close any other software that may be connected to this device "
                        f"(terminal emulators, firmware updaters, other measurement software) "
                        f"and try again."
                    ) from None

                if not warned:
                    log.warning(
                        "PortLock: %s is busy, waiting up to %.1fs …",
                        self._port, timeout_s
                    )
                    warned = True

                time.sleep(0.1)

    def release(self) -> None:
        """Release the lock."""
        if sys.platform == "win32":
            return

        if self._fd is not None:
            try:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except Exception as exc:
                log.debug("PortLock release error (ignored): %s", exc)
            self._fd = None

        if self._lock_path and os.path.exists(self._lock_path):
            try:
                os.remove(self._lock_path)
            except OSError:
                pass
        self._lock_path = None

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "PortLock":
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        self.release()

    def __repr__(self) -> str:
        held = self._fd is not None
        return f"PortLock({self._port!r}, held={held})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lockfile_path(port: str) -> str:
    """Return a safe /tmp path for the lock file of *port*."""
    safe = port.replace("/", "_").replace("\\", "_").replace(":", "_")
    return os.path.join("/tmp", f"sanjinsight_port{safe}.lock")


def _read_pid(lock_path: str) -> str | None:
    """Try to read the PID written by the lock holder."""
    try:
        with open(lock_path) as f:
            return f.read().strip() or None
    except Exception:
        return None
