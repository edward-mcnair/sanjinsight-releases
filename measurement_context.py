"""
measurement_context.py  —  Observable measurement session context

Lightweight, thread-safe container for the *identifiers and summaries*
that describe the current measurement setup.  Consumers (dashboard,
guided banner, status bar) subscribe to changes rather than polling
widget-local state.

Design principles:
  - Stores IDs and labels, never full mutable domain objects.
  - Uses the same RLock + subscribe/notify pattern as ApplicationState.
  - Fields are added only when a real consumer exists.

Usage
-----
::
    from measurement_context import measurement_context

    measurement_context.scan_profile_uid = "abc-123"
    measurement_context.scan_profile_label = "Gold on SiO2"

    measurement_context.subscribe("scan_profile_uid", my_callback)
    measurement_context.clear_scan_profile()
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# Listener signature: (key, old_value, new_value) -> None
ContextListener = Callable[[str, Any, Any], None]


class MeasurementContext:
    """Observable context for the active measurement setup.

    Thread-safe singleton.  All property setters notify subscribers
    when a value actually changes.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: dict[str, list[ContextListener]] = {}

        # ── Camera ──────────────────────────────────────────────────
        self._camera_key: str = "tr"            # "tr" | "ir"

        # ── Material profile ────────────────────────────────────────
        self._material_profile_id: Optional[str] = None
        self._material_profile_name: Optional[str] = None

        # ── Scan profile (recipe) ──────────────────────────────────
        self._scan_profile_uid: Optional[str] = None
        self._scan_profile_label: Optional[str] = None
        self._scan_profile_modified: bool = False

    # ── Subscription API ────────────────────────────────────────────

    def subscribe(self, key: str, callback: ContextListener) -> None:
        """Register *callback* for changes to *key*.

        Use ``key=""`` to subscribe to **all** changes.
        Callback signature: ``(key, old_value, new_value) -> None``.
        Called under the lock — must not block or re-acquire.
        """
        with self._lock:
            self._listeners.setdefault(key, [])
            if callback not in self._listeners[key]:
                self._listeners[key].append(callback)

    def unsubscribe(self, key: str, callback: ContextListener) -> None:
        """Remove a previously registered listener."""
        with self._lock:
            cbs = self._listeners.get(key, [])
            try:
                cbs.remove(callback)
            except ValueError:
                pass

    def _notify(self, key: str, old: Any, new: Any) -> None:
        """Fire listeners for *key* and wildcard "".  Must hold lock."""
        for cb in self._listeners.get(key, ()):
            try:
                cb(key, old, new)
            except Exception:
                log.warning("MeasurementContext listener error for %r",
                            key, exc_info=True)
        for cb in self._listeners.get("", ()):
            try:
                cb(key, old, new)
            except Exception:
                log.warning("MeasurementContext wildcard listener error for %r",
                            key, exc_info=True)

    # ── Camera ──────────────────────────────────────────────────────

    @property
    def camera_key(self) -> str:
        with self._lock:
            return self._camera_key

    @camera_key.setter
    def camera_key(self, value: str) -> None:
        with self._lock:
            old = self._camera_key
            if old != value:
                self._camera_key = value
                self._notify("camera_key", old, value)

    # ── Material profile ────────────────────────────────────────────

    @property
    def material_profile_id(self) -> Optional[str]:
        with self._lock:
            return self._material_profile_id

    @property
    def material_profile_name(self) -> Optional[str]:
        with self._lock:
            return self._material_profile_name

    def set_material_profile(self, profile_id: Optional[str],
                             name: Optional[str]) -> None:
        """Set or clear the active material profile (atomic update)."""
        with self._lock:
            old_id = self._material_profile_id
            old_name = self._material_profile_name
            if old_id != profile_id:
                self._material_profile_id = profile_id
                self._notify("material_profile_id", old_id, profile_id)
            if old_name != name:
                self._material_profile_name = name
                self._notify("material_profile_name", old_name, name)

    def clear_material_profile(self) -> None:
        """Reset material profile to unset."""
        self.set_material_profile(None, None)

    # ── Scan profile ────────────────────────────────────────────────

    @property
    def scan_profile_uid(self) -> Optional[str]:
        with self._lock:
            return self._scan_profile_uid

    @property
    def scan_profile_label(self) -> Optional[str]:
        with self._lock:
            return self._scan_profile_label

    @property
    def scan_profile_modified(self) -> bool:
        with self._lock:
            return self._scan_profile_modified

    @scan_profile_modified.setter
    def scan_profile_modified(self, value: bool) -> None:
        with self._lock:
            old = self._scan_profile_modified
            if old != value:
                self._scan_profile_modified = value
                self._notify("scan_profile_modified", old, value)

    def set_scan_profile(self, uid: Optional[str],
                         label: Optional[str]) -> None:
        """Set the active scan profile (atomic uid + label update)."""
        with self._lock:
            old_uid = self._scan_profile_uid
            old_label = self._scan_profile_label
            if old_uid != uid:
                self._scan_profile_uid = uid
                self._notify("scan_profile_uid", old_uid, uid)
            if old_label != label:
                self._scan_profile_label = label
                self._notify("scan_profile_label", old_label, label)
            # Clear modified flag when switching profiles
            if old_uid != uid and self._scan_profile_modified:
                self._scan_profile_modified = False
                self._notify("scan_profile_modified", True, False)

    def clear_scan_profile(self) -> None:
        """Reset scan profile to unset (deselection or mode change)."""
        self.set_scan_profile(None, None)

    # ── Bulk reset ──────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all context fields.  Used on session reset or mode change."""
        with self._lock:
            self.camera_key = "tr"
            self.clear_material_profile()
            self.clear_scan_profile()


# ── Module-level singleton ──────────────────────────────────────────
measurement_context = MeasurementContext()
