"""
utils.py

Shared utility helpers for SanjINSIGHT.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Callable, Optional, Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

log = logging.getLogger(__name__)


def safe_call(
    fn: Callable[..., Any],
    *args: Any,
    label: str = "",
    level: int = logging.WARNING,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """
    Call *fn* with *args*/*kwargs*, catching and logging all exceptions.

    Parameters
    ----------
    fn      : callable to invoke
    *args   : positional arguments forwarded to fn
    label   : human-readable name used in the log message
              (defaults to fn.__qualname__ if omitted)
    level   : logging level for caught exceptions (default: WARNING)
    default : value to return when an exception is caught (default: None)
    **kwargs: keyword arguments forwarded to fn

    Returns
    -------
    The return value of fn(*args, **kwargs), or *default* on exception.

    Examples
    --------
    >>> safe_call(cam.close, label="camera close", level=logging.DEBUG)
    >>> result = safe_call(callback, data, label="on_complete callback")
    """
    name = label or getattr(fn, "__qualname__", repr(fn))
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.log(level, "safe_call: %s raised", name, exc_info=True)
        return default


# ------------------------------------------------------------------ #
#  Atomic file-write primitives                                       #
# ------------------------------------------------------------------ #

def atomic_write(path: str, write_fn: Callable, *, mode: str = "w") -> None:
    """Write to *path* crash-safely via temp + flush + fsync + rename.

    Parameters
    ----------
    path:
        Target file path.
    write_fn:
        Callable that receives an open file handle and writes content.
        Example: ``lambda f: json.dump(data, f, indent=2)``
    mode:
        File open mode (default ``"w"`` for text).

    Raises
    ------
    OSError
        On any I/O failure.  The original file is left untouched.
    """
    parent = os.path.dirname(path) or "."
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", prefix=".atomic_", dir=parent)
        with os.fdopen(fd, mode) as f:
            fd = None
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def atomic_write_json(path: str, data: dict, *, indent: int = 2) -> None:
    """Write *data* as JSON to *path* crash-safely.

    Convenience wrapper around :func:`atomic_write` for JSON dicts.
    """
    atomic_write(path, lambda f: json.dump(data, f, indent=indent))
