"""
ui/widgets/device_status_card.py

Lightweight proxy widget shown inside a HardwareCategoryPanel tab.

Each connected device gets one of these cards instead of embedding the
actual control widget (which lives in the workflow phases and can only
have one Qt parent).  The card shows:

  - Device name + connection status badge
  - Static device info (model, serial, driver, etc.)
  - Live readouts section (exposure, temperature, position)
  - A "Configure" button that navigates to the full settings tab

Usage
-----
::
    card = DeviceStatusCard(
        device_key="tec0",
        display_name="Meerstetter TEC-1089",
        icon=IC.TEMPERATURE,
    )
    card.configure_clicked.connect(
        lambda: nav.select_by_label("Temperature"))
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame, QScrollArea,
)

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, make_icon_label, set_btn_icon

log = logging.getLogger(__name__)


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {PALETTE['border']};")
    return f


class DeviceStatusCard(QWidget):
    """Proxy widget for a device inside a hardware category panel.

    Emits ``configure_clicked`` when the user wants to open the full
    settings tab for this device.
    """

    configure_clicked = pyqtSignal()

    def __init__(
        self,
        device_key: str,
        display_name: str,
        icon: str = IC.CONNECT,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._device_key = device_key
        self._display_name = display_name
        self._icon_name = icon
        self._info_labels: dict[str, QLabel] = {}
        self._section_labels: list[QLabel] = []

        P, F = PALETTE, FONT

        # Wrap everything in a scroll area so tall cards are usable
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(0)

        # ── Header row: icon + name + status badge ───────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        self._icon_lbl = make_icon_label(icon, color=P["accent"], size=32)
        hdr.addWidget(self._icon_lbl)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self._name_lbl = QLabel(display_name)
        self._name_lbl.setStyleSheet(
            f"font-size: {F['readoutSm']}pt; font-weight: 600; "
            f"color: {P['text']};")
        name_col.addWidget(self._name_lbl)

        self._subtitle_lbl = QLabel(device_key)
        self._subtitle_lbl.setStyleSheet(
            f"font-size: {F['label']}pt; color: {P['textSub']};")
        name_col.addWidget(self._subtitle_lbl)
        hdr.addLayout(name_col)

        hdr.addStretch()

        # Status badge (pill shape)
        self._status_badge = QLabel("  Connected  ")
        self._status_badge.setAlignment(Qt.AlignCenter)
        self._set_badge_connected(True)
        hdr.addWidget(self._status_badge, 0, Qt.AlignVCenter)

        outer.addLayout(hdr)
        outer.addSpacing(12)

        # ── Device info grid ─────────────────────────────────────────
        self._info_grid = QGridLayout()
        self._info_grid.setSpacing(5)
        self._info_grid.setContentsMargins(0, 0, 0, 0)
        self._info_grid.setColumnMinimumWidth(0, 90)
        outer.addLayout(self._info_grid)
        self._info_row = 0

        # ── Configure button ─────────────────────────────────────────
        outer.addSpacing(16)

        self._configure_btn = QPushButton("  Configure")
        set_btn_icon(self._configure_btn, IC.SETTINGS, color=P["accent"], size=14)
        self._configure_btn.setFixedHeight(34)
        self._configure_btn.setMaximumWidth(180)
        self._configure_btn.setCursor(Qt.PointingHandCursor)
        self._configure_btn.setStyleSheet(f"""
            QPushButton {{
                background: {P['surface']}; color: {P['accent']};
                border: 1px solid {P['accent']}66; border-radius: 6px;
                font-size: {F['label']}pt; font-weight: 600;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {P['surface2']}; }}
        """)
        self._configure_btn.clicked.connect(self.configure_clicked.emit)
        outer.addWidget(self._configure_btn, 0, Qt.AlignLeft)

        outer.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def device_key(self) -> str:
        return self._device_key

    def set_display_name(self, name: str) -> None:
        self._display_name = name
        self._name_lbl.setText(name)

    def set_subtitle(self, text: str) -> None:
        self._subtitle_lbl.setText(text)

    def set_connected(self, connected: bool) -> None:
        """Update the status badge."""
        self._set_badge_connected(connected)

    def add_section(self, title: str) -> None:
        """Add a section divider with a label (e.g. 'Live Readouts')."""
        P, F = PALETTE, FONT
        # Divider line
        line = _hline()
        self._info_grid.addWidget(line, self._info_row, 0, 1, 2)
        self._info_row += 1
        # Section label
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            f"font-size: {max(7, F['label'] - 1)}pt; font-weight: 600; "
            f"color: {P['textSub']}; letter-spacing: 1px; "
            f"padding-top: 6px; padding-bottom: 2px;")
        self._info_grid.addWidget(lbl, self._info_row, 0, 1, 2)
        self._section_labels.append(lbl)
        self._info_row += 1

    def add_info(self, label: str, value: str = "\u2014",
                 monospace: bool = False) -> None:
        """Add a key-value row to the info grid."""
        P, F = PALETTE, FONT
        key_lbl = QLabel(label)
        key_lbl.setStyleSheet(
            f"font-size: {F['label']}pt; color: {P['textDim']}; "
            f"padding: 1px 6px 1px 0;")
        val_lbl = QLabel(value)
        font_family = MONO_FONT if monospace else ""
        ff_css = f"font-family: {font_family}; " if font_family else ""
        val_lbl.setStyleSheet(
            f"{ff_css}font-size: {F['label']}pt; color: {P['text']}; "
            f"font-weight: 500;")
        val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._info_grid.addWidget(key_lbl, self._info_row, 0,
                                  Qt.AlignRight | Qt.AlignTop)
        self._info_grid.addWidget(val_lbl, self._info_row, 1,
                                  Qt.AlignLeft | Qt.AlignTop)
        self._info_labels[label] = val_lbl
        self._info_row += 1

    def update_info(self, label: str, value: str) -> None:
        """Update the value of an existing info row."""
        lbl = self._info_labels.get(label)
        if lbl is not None:
            lbl.setText(value)

    # ── Theme support ─────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Refresh after a theme switch."""
        P, F = PALETTE, FONT
        self._name_lbl.setStyleSheet(
            f"font-size: {F['readoutSm']}pt; font-weight: 600; "
            f"color: {P['text']};")
        self._subtitle_lbl.setStyleSheet(
            f"font-size: {F['label']}pt; color: {P['textSub']};")
        self._configure_btn.setStyleSheet(f"""
            QPushButton {{
                background: {P['surface']}; color: {P['accent']};
                border: 1px solid {P['accent']}66; border-radius: 6px;
                font-size: {F['label']}pt; font-weight: 600;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {P['surface2']}; }}
        """)
        # Re-apply badge
        is_connected = "Connected" in self._status_badge.text()
        self._set_badge_connected(is_connected)
        # Re-apply info label colours
        for row in range(self._info_grid.rowCount()):
            key_item = self._info_grid.itemAtPosition(row, 0)
            val_item = self._info_grid.itemAtPosition(row, 1)
            if key_item and key_item.widget():
                w = key_item.widget()
                if w not in self._section_labels and not isinstance(w, QFrame):
                    w.setStyleSheet(
                        f"font-size: {F['label']}pt; color: {P['textDim']}; "
                        f"padding: 1px 6px 1px 0;")
            if val_item and val_item.widget():
                val_item.widget().setStyleSheet(
                    f"font-size: {F['label']}pt; color: {P['text']}; "
                    f"font-weight: 500;")
        for lbl in self._section_labels:
            lbl.setStyleSheet(
                f"font-size: {max(7, F['label'] - 1)}pt; font-weight: 600; "
                f"color: {P['textSub']}; letter-spacing: 1px; "
                f"padding-top: 6px; padding-bottom: 2px;")

    # ── Internal ──────────────────────────────────────────────────────

    def _set_badge_connected(self, connected: bool) -> None:
        P, F = PALETTE, FONT
        if connected:
            self._status_badge.setText("  Connected  ")
            self._status_badge.setStyleSheet(
                f"background: {P['accent']}22; color: {P['accent']}; "
                f"border: 1px solid {P['accent']}44; border-radius: 10px; "
                f"font-size: {F['label']}pt; font-weight: 600; "
                f"padding: 2px 8px;")
        else:
            self._status_badge.setText("  Disconnected  ")
            self._status_badge.setStyleSheet(
                f"background: {P['danger']}22; color: {P['danger']}; "
                f"border: 1px solid {P['danger']}44; border-radius: 10px; "
                f"font-size: {F['label']}pt; font-weight: 600; "
                f"padding: 2px 8px;")
