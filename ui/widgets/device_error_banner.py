"""
ui/widgets/device_error_banner.py

Contextual error banner for hardware-bound tabs.

When a hardware device enters an error state, the banner appears at the top
of the owning tab with a plain-English explanation, a Reconnect button, and
a link to the Device Manager.  It is dismissible (×) and clears automatically
when the device reconnects.

Usage
-----
    from ui.widgets.device_error_banner import DeviceErrorBanner

    banner = DeviceErrorBanner()
    layout.insertWidget(0, banner)     # insert at top of tab layout

    banner.show_error("tec0", "TEC-1089", "The TEC-1089 has lost its …")
    banner.clear()                     # hide when device reconnects
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)


class DeviceErrorBanner(QFrame):
    """Dismissible banner that shows a device error with action buttons."""

    reconnect_clicked      = pyqtSignal(str)   # device_key
    device_manager_clicked = pyqtSignal()
    dismissed              = pyqtSignal()

    def __init__(self, parent: Optional[QFrame] = None):
        super().__init__(parent)
        self._device_key = ""
        self._build_ui()
        self._apply_styles()
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ── Build ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(12)

        # Left: warning icon
        self._icon_lbl = QLabel("⚠")
        self._icon_lbl.setFixedWidth(24)
        self._icon_lbl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        root.addWidget(self._icon_lbl)

        # Centre: text
        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        self._title_lbl = QLabel("")
        self._title_lbl.setWordWrap(True)
        text_col.addWidget(self._title_lbl)

        self._body_lbl = QLabel("")
        self._body_lbl.setWordWrap(True)
        text_col.addWidget(self._body_lbl)

        root.addLayout(text_col, 1)

        # Right: buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._reconnect_btn = QPushButton("Reconnect")
        self._reconnect_btn.setFixedWidth(110)
        self._reconnect_btn.setCursor(Qt.PointingHandCursor)
        self._reconnect_btn.clicked.connect(
            lambda: self.reconnect_clicked.emit(self._device_key))
        btn_col.addWidget(self._reconnect_btn)

        self._dm_btn = QPushButton("Device Manager")
        self._dm_btn.setFixedWidth(110)
        self._dm_btn.setCursor(Qt.PointingHandCursor)
        self._dm_btn.clicked.connect(self.device_manager_clicked.emit)
        btn_col.addWidget(self._dm_btn)

        btn_col.addStretch()
        root.addLayout(btn_col)

        # Dismiss (×)
        self._dismiss_btn = QPushButton("×")
        self._dismiss_btn.setFixedSize(24, 24)
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        root.addWidget(self._dismiss_btn, 0, Qt.AlignTop)

    # ── Public API ───────────────────────────────────────────────────────

    def show_error(
        self,
        device_key: str,
        display_name: str,
        message: str,
    ) -> None:
        """Show the banner with error details.

        Parameters
        ----------
        device_key : str
            Internal key (``"tec0"``, ``"camera"``, etc.) emitted on reconnect.
        display_name : str
            Short human name (``"TEC-1089"``).
        message : str
            Full narration paragraph or error description.
        """
        self._device_key = device_key
        self._title_lbl.setText(f"{display_name} — connection error")
        self._body_lbl.setText(message)
        self._apply_styles()
        self.setVisible(True)

    def clear(self) -> None:
        """Hide the banner (device reconnected or user dismissed)."""
        self.setVisible(False)
        self._device_key = ""

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        warning = PALETTE.get("warning", "#ffb300")
        danger  = PALETTE.get("danger", "#ff4444")
        surface = PALETTE.get("surface", "#1e1e1e")
        bg      = PALETTE.get("bg", "#121212")
        fg      = PALETTE.get("fg", "#e0e0e0")
        muted   = PALETTE.get("muted", "#888888")
        accent  = PALETTE.get("accent", "#00d479")
        base    = FONT.get("base", 11)
        sm      = FONT.get("sm", 10)

        # Frame: amber left border, dark surface background
        self.setStyleSheet(
            f"DeviceErrorBanner {{"
            f"  background: {surface};"
            f"  border-left: 4px solid {warning};"
            f"  border-top: 1px solid {warning}40;"
            f"  border-right: 1px solid {warning}40;"
            f"  border-bottom: 1px solid {warning}40;"
            f"  border-radius: 6px;"
            f"}}"
        )

        self._icon_lbl.setStyleSheet(
            f"font-size: 16px; color: {warning}; border: none; background: transparent;")
        self._title_lbl.setStyleSheet(
            f"font-size: {base}pt; font-weight: 700; "
            f"color: {warning}; border: none; background: transparent;")
        self._body_lbl.setStyleSheet(
            f"font-size: {sm}pt; color: {muted}; "
            f"border: none; background: transparent; line-height: 140%;")

        _btn_qss = (
            f"QPushButton {{"
            f"  background: transparent; color: {accent};"
            f"  border: 1px solid {accent}; border-radius: 4px;"
            f"  padding: 4px 8px; font-size: {sm}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {accent}; color: {bg};"
            f"}}"
        )
        self._reconnect_btn.setStyleSheet(_btn_qss)
        self._dm_btn.setStyleSheet(_btn_qss)

        self._dismiss_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {muted}; border: none;"
            f"  font-size: 14px; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {fg}; }}"
        )

    # ── Internal ─────────────────────────────────────────────────────────

    def _on_dismiss(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()
