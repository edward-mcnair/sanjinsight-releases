"""
utils.py

Shared utility helpers for SanjINSIGHT.
"""
from __future__ import annotations

import logging
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
