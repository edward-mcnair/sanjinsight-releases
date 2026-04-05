"""
ui/services/estop_service.py

Extracts emergency-stop logic from MainWindow into a reusable service.
"""

import logging

log = logging.getLogger(__name__)


class EStopService:
    """Manages E-Stop trigger, completion notification, and clear/re-arm."""

    def __init__(self, *, header, status_bar, log_tab, toasts, hw_service):
        self._header = header
        self._status = status_bar
        self._log_tab = log_tab
        self._toasts = toasts
        self._hw = hw_service

    def trigger(self):
        """User pressed E-Stop — latch the UI then fire the stop sequence."""
        self._header.set_estop_triggered()
        self._status.showMessage(
            "⚠  EMERGENCY STOP — stopping all hardware outputs…", 0)
        self._log_tab.append("⊗ EMERGENCY STOP triggered by user")
        self._hw.emergency_stop()

    def on_complete(self, summary: str):
        """Called on UI thread when all outputs are confirmed stopped."""
        self._log_tab.append(f"⊗ E-STOP complete — {summary}")
        self._status.showMessage(f"⚠  STOPPED — {summary}", 0)
        self._toasts._show(
            title="Emergency Stop — Hardware Outputs Disabled",
            message=summary,
            level="error",
            guidance=[
                "Bias output, all TECs, and stage motion have been stopped",
                "Acquisition has been aborted",
                "Inspect the instrument before proceeding",
                "Click '⚠ STOPPED — Click to Clear' in the header when safe"
                " to re-arm",
            ],
            auto_dismiss_ms=0)

    def clear(self):
        """User clicked the latched STOPPED button to re-arm."""
        self._header.set_estop_armed()
        self._status.showMessage(
            "Emergency stop cleared — hardware ready", 4000)
        self._log_tab.append(
            "✓ Emergency stop cleared — outputs can be re-enabled")
