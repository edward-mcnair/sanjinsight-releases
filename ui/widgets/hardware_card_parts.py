"""
ui/widgets/hardware_card_parts.py

Reusable sub-widgets for the hardware device status cards:

  • MetricTile     — compact tile: label on top, large value below
  • DeviceHeaderBar — shared header: status dot, name, summary, badge, actions
  • InfoCard       — bordered card with title + key-value grid

These are building blocks consumed by DeviceStatusCard.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGridLayout, QSizePolicy, QWidget,
)

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, make_icon_label, set_btn_icon


# ── Metric Tile ────────────────────────────────────────────────────────

class MetricTile(QFrame):
    """Compact metric display tile.

    Shows a small label on top and a large monospace value below,
    with an optional unit suffix.  Designed to be placed in rows of
    3–4 tiles for at-a-glance readouts.

    Usage::

        tile = MetricTile("Temperature", "—", "°C")
        tile.set_value("25.0")
        tile.set_accent("#00d479")   # green left-bar
    """

    def __init__(self, label: str = "", value: str = "\u2014",
                 unit: str = "", *, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("MetricTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(72)
        self.setMinimumWidth(100)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        # Label row
        self._label_lbl = QLabel(label.upper())
        self._label_lbl.setObjectName("tileLbl")
        lay.addWidget(self._label_lbl)

        # Value + unit row
        val_row = QHBoxLayout()
        val_row.setSpacing(3)
        val_row.setContentsMargins(0, 0, 0, 0)

        self._value_lbl = QLabel(value)
        self._value_lbl.setObjectName("tileVal")
        val_row.addWidget(self._value_lbl)

        self._unit_lbl = QLabel(unit)
        self._unit_lbl.setObjectName("tileUnit")
        val_row.addWidget(self._unit_lbl, 0, Qt.AlignBottom)
        val_row.addStretch()
        lay.addLayout(val_row)

        self._accent_color: str = ""
        self._apply_styles()

    # ── Public API ────────────────────────────────────────────────

    def set_value(self, text: str) -> None:
        """Update the displayed value."""
        self._value_lbl.setText(text)

    def set_accent(self, color: str) -> None:
        """Set a coloured left-bar accent (empty string clears it)."""
        self._accent_color = color
        self._apply_frame_style()

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P, F = PALETTE, FONT
        self._apply_frame_style()
        self._label_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['sublabel']}pt; color: {P['textDim']}; "
            f"font-weight: 600; letter-spacing: 0.5px;")
        self._value_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-family: {MONO_FONT}; font-size: {F['readoutSm']}pt; "
            f"color: {P['text']}; font-weight: 600;")
        self._unit_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['label']}pt; color: {P['textDim']};")

    def _apply_frame_style(self) -> None:
        P = PALETTE
        accent = self._accent_color
        if accent:
            self.setStyleSheet(
                f"MetricTile {{ background: {P['surface']}; "
                f"border: 1px solid {P['border']}; "
                f"border-left: 3px solid {accent}; border-radius: 6px; }}")
        else:
            self.setStyleSheet(
                f"MetricTile {{ background: {P['surface']}; "
                f"border: 1px solid {P['border']}; border-radius: 6px; }}")


# ── Device Header Bar ──────────────────────────────────────────────────

class DeviceHeaderBar(QFrame):
    """Shared header bar for all hardware device cards.

    Shows status dot, device name, subtitle, one-line status summary,
    connection badge, and a prominent Configure button.
    """

    configure_clicked = pyqtSignal()

    def __init__(self, display_name: str = "", device_key: str = "",
                 icon: str = IC.CONNECT, *,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("DeviceHeaderBar")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        # ── Status dot ────────────────────────────────────────────
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        lay.addWidget(self._dot, 0, Qt.AlignVCenter)

        # ── Icon ──────────────────────────────────────────────────
        self._icon_lbl = make_icon_label(icon, color=PALETTE["accent"],
                                         size=24)
        lay.addWidget(self._icon_lbl, 0, Qt.AlignVCenter)

        # ── Text column: name / subtitle / summary ────────────────
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(display_name)
        self._name_lbl.setObjectName("hdrName")
        text_col.addWidget(self._name_lbl)

        self._subtitle_lbl = QLabel(device_key)
        self._subtitle_lbl.setObjectName("hdrSub")
        text_col.addWidget(self._subtitle_lbl)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setObjectName("hdrSummary")
        self._summary_lbl.setVisible(False)
        text_col.addWidget(self._summary_lbl)

        lay.addLayout(text_col, 1)

        # ── Connection badge ──────────────────────────────────────
        self._badge = QLabel("  Connected  ")
        self._badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._badge, 0, Qt.AlignVCenter)

        # ── Configure button ──────────────────────────────────────
        self._configure_btn = QPushButton("  Configure")
        set_btn_icon(self._configure_btn, IC.SETTINGS,
                     color=PALETTE.get("textOnAccent", "#fff"), size=14)
        self._configure_btn.setCursor(Qt.PointingHandCursor)
        self._configure_btn.setFixedHeight(32)
        self._configure_btn.setMinimumWidth(120)
        self._configure_btn.clicked.connect(self.configure_clicked.emit)
        lay.addWidget(self._configure_btn, 0, Qt.AlignVCenter)

        self._connected = True
        self._apply_styles()

    # ── Public API ────────────────────────────────────────────────

    def set_display_name(self, name: str) -> None:
        self._name_lbl.setText(name)

    def set_subtitle(self, text: str) -> None:
        self._subtitle_lbl.setText(text)

    def set_summary(self, text: str, color: str = "") -> None:
        """Set the one-line status summary (e.g. 'Streaming at 30 FPS').

        *color* overrides the text color for this update.  Pass an empty
        string to revert to the default accent color.
        """
        self._summary_lbl.setText(text)
        self._summary_lbl.setVisible(bool(text))
        P, F = PALETTE, FONT
        c = color or P['accent']
        self._summary_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['label']}pt; color: {c}; "
            f"font-style: italic;")

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._apply_badge()
        self._apply_dot()

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P, F = PALETTE, FONT
        self.setStyleSheet(
            f"DeviceHeaderBar {{ background: {P['surface']}; "
            f"border: 1px solid {P['border']}; border-radius: 8px; }}")
        self._name_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['heading']}pt; font-weight: 600; "
            f"color: {P['text']};")
        self._subtitle_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['label']}pt; color: {P['textSub']};")
        self._summary_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {F['label']}pt; color: {P['accent']}; "
            f"font-style: italic;")
        self._configure_btn.setStyleSheet(
            f"QPushButton {{ background: {P['accent']}; "
            f"color: {P.get('textOnAccent', '#fff')}; "
            f"border: none; border-radius: 6px; "
            f"font-size: {F['body']}pt; font-weight: 600; "
            f"padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {P.get('accentHover', P['accent'])}; }}")
        self._apply_badge()
        self._apply_dot()

    def _apply_badge(self) -> None:
        P, F = PALETTE, FONT
        if self._connected:
            self._badge.setText("  Connected  ")
            self._badge.setStyleSheet(
                f"background: {P['accent']}22; color: {P['accent']}; "
                f"border: 1px solid {P['accent']}44; border-radius: 10px; "
                f"font-size: {F['sublabel']}pt; font-weight: 600; "
                f"padding: 2px 8px;")
        else:
            self._badge.setText("  Disconnected  ")
            self._badge.setStyleSheet(
                f"background: {P['danger']}22; color: {P['danger']}; "
                f"border: 1px solid {P['danger']}44; border-radius: 10px; "
                f"font-size: {F['sublabel']}pt; font-weight: 600; "
                f"padding: 2px 8px;")

    def _apply_dot(self) -> None:
        P = PALETTE
        color = P['accent'] if self._connected else P['danger']
        self._dot.setStyleSheet(
            f"background: {color}; border-radius: 5px; border: none;")


# ── Info Card ──────────────────────────────────────────────────────────

class InfoCard(QFrame):
    """Bordered card with a title and compact key-value grid.

    Used for secondary device information (model, serial, driver, etc.)
    that should be visible but not visually dominant.
    """

    def __init__(self, title: str = "Device Info", *,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(4)

        self._title_lbl = QLabel(title.upper())
        self._title_lbl.setObjectName("infoTitle")
        lay.addWidget(self._title_lbl)

        self._grid = QGridLayout()
        self._grid.setSpacing(4)
        self._grid.setContentsMargins(0, 4, 0, 0)
        self._grid.setColumnMinimumWidth(0, 80)
        lay.addLayout(self._grid)

        self._info_labels: dict[str, QLabel] = {}
        self._section_labels: list[QLabel] = []
        self._row = 0

        self._apply_styles()

    # ── Public API ────────────────────────────────────────────────

    def add_section(self, title: str) -> None:
        """Add a section divider with an uppercase label."""
        P, F = PALETTE, FONT
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {P['border']};")
        self._grid.addWidget(line, self._row, 0, 1, 2)
        self._row += 1

        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            f"font-size: {max(7, F['label'] - 1)}pt; font-weight: 600; "
            f"color: {P['textSub']}; letter-spacing: 1px; "
            f"padding-top: 4px; padding-bottom: 2px;")
        self._grid.addWidget(lbl, self._row, 0, 1, 2)
        self._section_labels.append(lbl)
        self._row += 1

    def add_info(self, label: str, value: str = "\u2014",
                 monospace: bool = False) -> QLabel:
        """Add a key-value row. Returns the value QLabel for external tracking."""
        P, F = PALETTE, FONT
        key_lbl = QLabel(label)
        key_lbl.setStyleSheet(
            f"font-size: {F['sublabel']}pt; color: {P['textDim']}; "
            f"padding: 1px 6px 1px 0;")

        val_lbl = QLabel(value)
        ff = f"font-family: {MONO_FONT}; " if monospace else ""
        val_lbl.setStyleSheet(
            f"{ff}font-size: {F['sublabel']}pt; color: {P['text']}; "
            f"font-weight: 500;")
        val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._grid.addWidget(key_lbl, self._row, 0,
                             Qt.AlignRight | Qt.AlignTop)
        self._grid.addWidget(val_lbl, self._row, 1,
                             Qt.AlignLeft | Qt.AlignTop)
        self._info_labels[label] = val_lbl
        self._row += 1
        return val_lbl

    def update_info(self, label: str, value: str) -> bool:
        """Update an existing row value. Returns True if found."""
        lbl = self._info_labels.get(label)
        if lbl is not None:
            lbl.setText(value)
            return True
        return False

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P, F = PALETTE, FONT
        self.setStyleSheet(
            f"InfoCard {{ background: {P['surface']}; "
            f"border: 1px solid {P['border']}; border-radius: 6px; }}")
        self._title_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"font-size: {max(7, F['sublabel'] - 1)}pt; font-weight: 600; "
            f"color: {P['textSub']}; letter-spacing: 1px;")
        # Re-apply key/value styles
        for row_idx in range(self._grid.rowCount()):
            key_item = self._grid.itemAtPosition(row_idx, 0)
            val_item = self._grid.itemAtPosition(row_idx, 1)
            if key_item and key_item.widget():
                w = key_item.widget()
                if w not in self._section_labels and not isinstance(w, QFrame):
                    w.setStyleSheet(
                        f"font-size: {F['sublabel']}pt; color: {P['textDim']}; "
                        f"padding: 1px 6px 1px 0;")
            if val_item and val_item.widget():
                val_item.widget().setStyleSheet(
                    f"font-size: {F['sublabel']}pt; color: {P['text']}; "
                    f"font-weight: 500;")
        for lbl in self._section_labels:
            lbl.setStyleSheet(
                f"font-size: {max(7, F['sublabel'] - 1)}pt; font-weight: 600; "
                f"color: {P['textSub']}; letter-spacing: 1px; "
                f"padding-top: 4px; padding-bottom: 2px;")
