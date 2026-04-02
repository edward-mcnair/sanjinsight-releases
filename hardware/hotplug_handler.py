"""
hardware/hotplug_handler.py

Application-level handler for USB hot-plug events.

Connects :class:`HotPlugMonitor` signals (device_arrived / device_removed)
to the SanjINSIGHT device-management system: looks up the VID:PID in the
device registry, emits user-facing toast messages, and attempts background
reconnection for known devices.

Usage
-----
    handler = HotPlugHandler(device_registry, smart_connect_cb)
    monitor.device_arrived.connect(handler.on_device_arrived)
    monitor.device_removed.connect(handler.on_device_removed)
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal

from hardware.device_registry import find_all_by_usb
from hardware.protocol_prober import probe_mecom_port

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background reconnection worker
# ---------------------------------------------------------------------------

class _ReconnectWorker(QThread):
    """Run a reconnect attempt off the GUI thread."""

    succeeded = pyqtSignal(str, str)   # (device_uid, port)
    failed    = pyqtSignal(str, str)   # (device_uid, error_message)

    def __init__(
        self,
        port: str,
        device_uid: str,
        display_name: str,
        smart_connect_cb: Callable,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._device_uid = device_uid
        self._display_name = display_name
        self._smart_connect_cb = smart_connect_cb

    def run(self) -> None:  # noqa: D401 — Qt override
        try:
            self._smart_connect_cb(self._port, self._device_uid)
            self.succeeded.emit(self._device_uid, self._port)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Reconnect failed for %s on %s: %s",
                self._display_name, self._port, exc,
            )
            self.failed.emit(self._device_uid, str(exc))


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

class HotPlugHandler(QObject):
    """Translates raw USB plug/unplug events into device-level actions.

    Parameters
    ----------
    device_registry :
        The ``hardware.device_registry`` module (or any object that exposes
        ``find_all_by_usb``).
    smart_connect_cb : callable
        ``smart_connect_cb(port, device_uid)`` — called in a background
        thread to re-establish a connection after a device is plugged in.
    """

    # -- Signals ----------------------------------------------------------
    toast_message      = pyqtSignal(str, str)   # (title, body)
    device_reconnected = pyqtSignal(str)        # device_uid
    device_lost        = pyqtSignal(str)        # device_uid

    # Per-port cooldown (seconds) to suppress rapid-fire reconnect attempts.
    _COOLDOWN_SECS = 1.0

    def __init__(
        self,
        device_registry,
        smart_connect_cb: Callable,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._registry = device_registry
        self._smart_connect_cb = smart_connect_cb

        # port → timestamp of last reconnect attempt
        self._last_attempt: dict[str, float] = {}

        # Keep references to running workers so they aren't garbage-collected
        self._workers: list[_ReconnectWorker] = []

    # -- Slots ------------------------------------------------------------

    def on_device_arrived(self, port: str, vid: int, pid: int) -> None:
        """Handle a newly-arrived USB device.

        Looks up the VID:PID in the device registry.  For every matching
        descriptor that represents a Meerstetter device, emits a toast and
        kicks off a background reconnection attempt.
        """
        descriptors = find_all_by_usb(vid, pid)
        if not descriptors:
            log.debug(
                "Hotplug: device arrived on %s (VID=%04X PID=%04X) — "
                "no registry match",
                port, vid, pid,
            )
            return

        # Per-port cooldown check
        now = time.monotonic()
        last = self._last_attempt.get(port, 0.0)
        if (now - last) < self._COOLDOWN_SECS:
            log.debug(
                "Hotplug: cooldown active for %s — skipping reconnect",
                port,
            )
            return
        self._last_attempt[port] = now

        for desc in descriptors:
            log.info(
                "Hotplug: %s detected on %s (VID=%04X PID=%04X)",
                desc.display_name, port, vid, pid,
            )
            self.toast_message.emit(
                "Device detected",
                f"{desc.display_name} detected on {port}",
            )
            self._start_reconnect(port, desc.uid, desc.display_name)

    def on_device_removed(self, port: str, vid: int, pid: int) -> None:
        """Handle a USB device removal."""
        # Try to identify which device was on this port
        descriptors = find_all_by_usb(vid, pid)

        self.toast_message.emit(
            "Device disconnected",
            f"Device disconnected from {port}",
        )

        if descriptors:
            for desc in descriptors:
                log.info(
                    "Hotplug: %s lost on %s",
                    desc.display_name, port,
                )
                self.device_lost.emit(desc.uid)
        else:
            log.info("Hotplug: unknown device removed from %s", port)
            self.device_lost.emit("")

    # -- Internal ---------------------------------------------------------

    def _start_reconnect(
        self, port: str, device_uid: str, display_name: str,
    ) -> None:
        """Spawn a background thread to attempt smart reconnection."""
        worker = _ReconnectWorker(
            port=port,
            device_uid=device_uid,
            display_name=display_name,
            smart_connect_cb=self._smart_connect_cb,
            parent=self,
        )
        worker.succeeded.connect(self._on_reconnect_success)
        worker.failed.connect(self._on_reconnect_failure)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()

    def _on_reconnect_success(self, device_uid: str, port: str) -> None:
        log.info("Hotplug: reconnected %s on %s", device_uid, port)
        self.toast_message.emit(
            "Reconnected",
            f"{device_uid} reconnected on {port}",
        )
        self.device_reconnected.emit(device_uid)

    def _on_reconnect_failure(self, device_uid: str, error: str) -> None:
        log.warning("Hotplug: reconnect failed for %s — %s", device_uid, error)
        self.toast_message.emit(
            "Reconnect failed",
            f"Could not reconnect {device_uid}: {error}",
        )

    def _cleanup_worker(self, worker: _ReconnectWorker) -> None:
        """Remove finished worker from the active list."""
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
