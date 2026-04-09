"""
acquisition/storage/_atomic.py

Crash-safe file-write primitives for session persistence.

Delegates to the shared ``utils.atomic_write_json()`` implementation.
This module exists so that existing imports within the acquisition
subsystem (``from acquisition.storage._atomic import atomic_write_json``)
continue to work unchanged.
"""

from utils import atomic_write_json  # noqa: F401 — re-export
