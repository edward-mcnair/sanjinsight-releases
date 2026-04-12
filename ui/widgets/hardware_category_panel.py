"""
ui/widgets/hardware_category_panel.py

Dynamic QTabWidget wrapper for a hardware category (Cameras, Stages, etc.).

Each connected device within the category gets its own named tab.
When no devices are connected, an empty-state placeholder is shown.
Tabs are added/removed in response to ``device_connected`` signals
from the hardware service layer.

Usage
-----
::
    panel = HardwareCategoryPanel(
        category="cameras",
        label="Cameras",
        parent=self,
    )
    # Register a device-type → widget mapping
    panel.register_device("camera", camera_tab_widget, display_name="Basler acA1920")
    # Later, on disconnect:
    panel.unregister_device("camera")
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QTabWidget, QStackedLayout, QVBoxLayout,
)

from ui.theme import PALETTE
from ui.widgets.empty_state import build_empty_state
from ui.widgets.tab_helpers import inner_tab_qss

log = logging.getLogger(__name__)


class HardwareCategoryPanel(QWidget):
    """Container for one hardware category's device tabs.

    Manages a QTabWidget overlaid with an empty-state placeholder.
    When at least one device is registered, the tab widget is shown.
    When all devices are removed, the empty state is shown.
    """

    open_device_manager = pyqtSignal()
    start_demo_mode = pyqtSignal()

    def __init__(
        self,
        category: str,
        label: str,
        *,
        empty_description: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._category = category
        self._label = label
        # device_key → (widget, display_name)
        self._devices: Dict[str, tuple] = {}

        # ── Stacked layout: empty state vs tab widget ────────────────
        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)

        # Empty state placeholder
        desc = empty_description or (
            f"No {label.lower()} connected.\n"
            f"Connect a device in Device Manager, or start "
            f"Demo Mode to explore the interface."
        )
        self._empty = build_empty_state(
            title=label,
            description=desc,
            btn_text="Open Device Manager",
            on_action=self.open_device_manager.emit,
            secondary_btn_text="Start Demo Mode",
            on_secondary_action=self.start_demo_mode.emit,
        )
        self._stack.addWidget(self._empty)

        # Tab widget for device tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setStyleSheet(inner_tab_qss())
        self._stack.addWidget(self._tabs)

        # Start with empty state
        self._stack.setCurrentWidget(self._empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._stack)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def category(self) -> str:
        return self._category

    @property
    def device_count(self) -> int:
        return len(self._devices)

    def register_device(
        self,
        device_key: str,
        widget: QWidget,
        display_name: str = "",
    ) -> None:
        """Add a device tab (or update its name if already registered).

        Parameters
        ----------
        device_key : str
            Unique key for this device (e.g. ``"camera"``, ``"tec0"``).
        widget : QWidget
            The control/status widget for this device.
        display_name : str
            Tab label — should be the device name (e.g. "Basler acA1920-155um").
        """
        name = display_name or device_key
        if device_key in self._devices:
            # Update display name if device already registered
            old_widget, _old_name = self._devices[device_key]
            idx = self._tabs.indexOf(old_widget)
            if idx >= 0:
                self._tabs.setTabText(idx, name)
            self._devices[device_key] = (old_widget, name)
            return

        self._devices[device_key] = (widget, name)
        self._tabs.addTab(widget, name)
        self._update_visibility()
        log.debug("HardwareCategoryPanel[%s]: registered %s (%s)",
                  self._category, device_key, name)

    def unregister_device(self, device_key: str) -> None:
        """Remove a device tab."""
        if device_key not in self._devices:
            return
        widget, name = self._devices.pop(device_key)
        idx = self._tabs.indexOf(widget)
        if idx >= 0:
            self._tabs.removeTab(idx)
        self._update_visibility()
        log.debug("HardwareCategoryPanel[%s]: unregistered %s (%s)",
                  self._category, device_key, name)

    def has_device(self, device_key: str) -> bool:
        return device_key in self._devices

    def set_device_name(self, device_key: str, display_name: str) -> None:
        """Update the tab label for an already-registered device."""
        if device_key not in self._devices:
            return
        widget, _old = self._devices[device_key]
        self._devices[device_key] = (widget, display_name)
        idx = self._tabs.indexOf(widget)
        if idx >= 0:
            self._tabs.setTabText(idx, display_name)

    def select_device(self, device_key: str) -> None:
        """Bring the tab for *device_key* to the front."""
        if device_key not in self._devices:
            return
        widget, _ = self._devices[device_key]
        idx = self._tabs.indexOf(widget)
        if idx >= 0:
            self._tabs.setCurrentIndex(idx)

    # ── Theme support ─────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Refresh styles after a theme switch."""
        self._tabs.setStyleSheet(inner_tab_qss())
        # Rebuild empty state description color
        if hasattr(self._empty, 'desc_lbl'):
            self._empty.desc_lbl.setStyleSheet(
                f"color: {PALETTE['textSub']};"
            )

    # ── Internal ──────────────────────────────────────────────────────

    def _update_visibility(self) -> None:
        """Toggle between empty state and tab widget."""
        if self._devices:
            self._stack.setCurrentWidget(self._tabs)
        else:
            self._stack.setCurrentWidget(self._empty)
