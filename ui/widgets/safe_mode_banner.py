"""
ui/widgets/safe_mode_banner.py

SafeModeBanner — a persistent, top-of-window warning strip shown whenever
a required device is absent and acquisition operations must be blocked.

The banner is hidden by default and surfaces via
:meth:`MainWindow._update_safe_mode` whenever the requirements resolver
detects a missing required device.

Visual design
-------------
* Solid amber/orange strip full-width between the StatusHeader and the
  content area.
* ⊗ icon + short reason text on the left.
* "Open Device Manager" button on the right.
* Clicking anywhere on the banner (or the button) opens the Device Manager.
"""
from __future__ import annotations

import sys

from PyQt5.QtCore    import pyqtSignal, Qt
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

# Amber palette — high visibility without looking like an error
_BG       = "#5a3a00"
_BORDER   = "#f5a623"
_FG       = "#ffcc66"
_BTN_BG   = "#3a2400"
_BTN_FG   = "#f5a623"
_BTN_HVR  = "#4a2e00"

_PT = 9 if sys.platform == "win32" else 12   # match main_app _style_pt scaling


class SafeModeBanner(QWidget):
    """
    Collapsible amber banner that blocks acquisition when shown.

    Signals
    -------
    device_manager_requested : emitted when the user clicks the action button
    """

    device_manager_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)      # hidden until safe mode is active

        self.setStyleSheet(
            f"SafeModeBanner {{ "
            f"    background: {_BG}; "
            f"    border-bottom: 2px solid {_BORDER}; "
            f"}}"
        )
        self.setFixedHeight(36)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(10)

        # Icon + reason label — use CSS font-size so Qt picks the correct
        # system UI font on every platform (Segoe UI on Windows, SF on macOS).
        self._label = QLabel()
        self._label.setStyleSheet(
            f"color: {_FG}; background: transparent; font-size: {_PT}pt;")
        self._label.setTextFormat(Qt.PlainText)
        lay.addWidget(self._label, stretch=1)

        # Action button
        self._btn = QPushButton("Open Device Manager")
        self._btn.setFixedHeight(24)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton {{ "
            f"    background: {_BTN_BG}; color: {_BTN_FG}; "
            f"    border: 1px solid {_BORDER}; border-radius: 3px; "
            f"    padding: 2px 10px; font-size: {_PT}pt; "
            f"}}"
            f"QPushButton:hover {{ background: {_BTN_HVR}; }}"
        )
        self._btn.clicked.connect(self.device_manager_requested)
        lay.addWidget(self._btn)

    # ── Public API ────────────────────────────────────────────────────

    def activate(self, reason: str) -> None:
        """Show the banner with *reason* as the blocking explanation."""
        self._label.setText(f"⊗  Safe Mode — {reason}")
        self.setVisible(True)

    def deactivate(self) -> None:
        """Hide the banner (all required devices are now present)."""
        self.setVisible(False)
        self._label.setText("")
