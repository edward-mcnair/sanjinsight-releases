"""
ui/widgets/device_status_card.py

Lightweight proxy widget shown inside a HardwareCategoryPanel tab.

Each connected device gets one of these cards instead of embedding the
actual control widget (which lives in the workflow phases and can only
have one Qt parent).

Layout modes
------------
``camera``
    Preview-heavy: live thumbnail left, metric tiles + info card right.
``dashboard``
    Tile-first: horizontal row of hero metric tiles, info card below.
``generic``
    Compact card with info grid (no tiles) — fallback for devices
    not yet converted to tile layout.

Usage
-----
::
    card = DeviceStatusCard(
        device_key="tec0",
        display_name="Meerstetter TEC-1089",
        icon=IC.TEMPERATURE,
        layout="dashboard",
    )
    card.add_tile("Temperature", "—", "°C")
    card.add_info("Controller", "Meerstetter TEC-1089")
    card.configure_clicked.connect(
        lambda: nav.select_by_label("Temperature"))
"""

from __future__ import annotations

import logging
from typing import Optional, Union

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy,
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, make_icon_label, set_btn_icon
from ui.widgets.hardware_card_parts import (
    MetricTile, DeviceHeaderBar, InfoCard,
)

log = logging.getLogger(__name__)


# ── Compact live preview widget ──────────────────────────────────────

class _LivePreviewThumbnail(QWidget):
    """Small live camera preview that fits inside a DeviceStatusCard.

    Displays the latest camera frame scaled to fit the widget with a
    dark canvas background.  No ROI overlays — keeps it lightweight.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 150)
        self._pixmap: Optional[QPixmap] = None

    def set_frame(self, data: np.ndarray) -> None:
        """Accept a raw camera frame (uint8/uint16, 2D or 3D)."""
        if data.dtype != np.uint8:
            d = data.astype(np.float32)
            lo, hi = np.percentile(d, (1, 99))
            d = np.clip((d - lo) / max(hi - lo, 1) * 255, 0, 255).astype(
                np.uint8)
        else:
            d = data

        if d.ndim == 2:
            h, w = d.shape
            qi = QImage(d.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = d.shape[:2]
            qi = QImage(d.tobytes(), w, h, w * 3, QImage.Format_RGB888)

        self._pixmap = QPixmap.fromImage(qi)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(PALETTE['canvas']))

        if not self._pixmap:
            from ui.font_utils import mono_font
            p.setPen(QColor(PALETTE['textDim']))
            p.setFont(mono_font(8))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Waiting for frame\u2026")
            p.end()
            return

        # Scale to fit, centred
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        iw, ih = int(pw * scale), int(ph * scale)
        ox, oy = (ww - iw) // 2, (wh - ih) // 2
        p.drawPixmap(ox, oy, iw, ih, self._pixmap)

        # Subtle border
        p.setPen(QColor(PALETTE['border']))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def _apply_styles(self) -> None:
        self.update()


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
        layout: str = "generic",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._device_key = device_key
        self._display_name = display_name
        self._icon_name = icon
        self._layout_mode = layout

        # Unified lookup for update_info() routing.
        # Maps label → MetricTile | QLabel.
        self._updatable: dict[str, Union[MetricTile, QLabel]] = {}

        self._tiles: list[MetricTile] = []
        self._preview: Optional[_LivePreviewThumbnail] = None
        self._info_card: Optional[InfoCard] = None

        # Wrap everything in a scroll area for safety
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        self._outer_lay = QVBoxLayout(inner)
        self._outer_lay.setContentsMargins(12, 10, 12, 10)
        self._outer_lay.setSpacing(10)

        # ── Header (shared across all modes) ─────────────────────
        self._header = DeviceHeaderBar(
            display_name, device_key, icon)
        self._header.configure_clicked.connect(
            self.configure_clicked.emit)
        self._outer_lay.addWidget(self._header)

        # ── Body (mode-specific, built lazily by populate calls) ─
        if layout == "camera":
            self._build_camera_body()
        elif layout == "dashboard":
            self._build_dashboard_body()
        else:
            self._build_generic_body()

        self._outer_lay.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    # ── Body builders ─────────────────────────────────────────────

    def _build_camera_body(self) -> None:
        """Preview left, tiles + info card right."""
        body = QHBoxLayout()
        body.setSpacing(12)
        body.setContentsMargins(0, 0, 0, 0)

        # Preview (left, flex=1)
        self._preview = _LivePreviewThumbnail()
        body.addWidget(self._preview, 1)

        # Right column: tiles + info card
        right = QVBoxLayout()
        right.setSpacing(8)
        right.setContentsMargins(0, 0, 0, 0)

        self._tiles_layout = QVBoxLayout()
        self._tiles_layout.setSpacing(6)
        self._tiles_layout.setContentsMargins(0, 0, 0, 0)
        right.addLayout(self._tiles_layout)

        self._info_card = InfoCard("Device Info")
        right.addWidget(self._info_card)
        right.addStretch()

        body.addLayout(right, 0)
        self._outer_lay.addLayout(body, 1)

    def _build_dashboard_body(self) -> None:
        """Hero tiles on top, info card below."""
        self._tiles_layout = QHBoxLayout()
        self._tiles_layout.setSpacing(8)
        self._tiles_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_lay.addLayout(self._tiles_layout)

        self._info_card = InfoCard("Device Info")
        self._outer_lay.addWidget(self._info_card)

    def _build_generic_body(self) -> None:
        """Classic info grid (fallback for non-redesigned devices)."""
        self._info_card = InfoCard("Device Info")
        self._outer_lay.addWidget(self._info_card)

    # ── Public API ────────────────────────────────────────────────

    @property
    def device_key(self) -> str:
        return self._device_key

    def set_display_name(self, name: str) -> None:
        self._display_name = name
        self._header.set_display_name(name)

    def set_subtitle(self, text: str) -> None:
        self._header.set_subtitle(text)

    def set_connected(self, connected: bool) -> None:
        self._header.set_connected(connected)

    def set_summary(self, text: str, color: str = "") -> None:
        """Set the one-line status summary in the header."""
        self._header.set_summary(text, color)

    def set_tile_accent(self, label: str, color: str) -> None:
        """Set the accent color on a tile identified by *label*.

        Pass an empty string to clear the accent.
        """
        target = self._updatable.get(label)
        if target is not None and isinstance(target, MetricTile):
            target.set_accent(color)

    # ── Tile API (new) ────────────────────────────────────────────

    def add_tile(self, label: str, value: str = "\u2014",
                 unit: str = "") -> MetricTile:
        """Add a metric tile. Returns the tile for external reference.

        The tile's label is registered in the unified updatable map so
        that ``update_info(label, value)`` routes to the tile.
        """
        tile = MetricTile(label, value, unit)
        self._tiles.append(tile)
        if hasattr(self, "_tiles_layout") and self._tiles_layout is not None:
            self._tiles_layout.addWidget(tile)
        self._updatable[label] = tile
        return tile

    # ── Info API (backward-compatible) ────────────────────────────

    def add_section(self, title: str) -> None:
        """Add a section divider (delegated to the InfoCard)."""
        if self._info_card is not None:
            self._info_card.add_section(title)

    def add_info(self, label: str, value: str = "\u2014",
                 monospace: bool = False) -> None:
        """Add a key-value info row (delegated to the InfoCard).

        The value label is registered in the updatable map so that
        ``update_info(label, value)`` works transparently.
        """
        if self._info_card is not None:
            val_lbl = self._info_card.add_info(label, value, monospace)
            self._updatable[label] = val_lbl

    def update_info(self, label: str, value: str) -> None:
        """Update any registered field — tile or info row.

        This is the primary compatibility entry point used by the
        coordinator's ``update_*_readouts()`` methods.
        """
        target = self._updatable.get(label)
        if target is None:
            return
        if isinstance(target, MetricTile):
            target.set_value(value)
        elif isinstance(target, QLabel):
            target.setText(value)

    # ── Camera preview ────────────────────────────────────────────

    def enable_live_preview(self) -> None:
        """Enable the live preview (camera mode builds it in __init__).

        For backward compatibility: if called on a non-camera card,
        this is a no-op (preview was not built).
        """
        # In camera layout mode, the preview is already created.
        # This method exists for API compatibility with the coordinator.
        pass

    def update_preview(self, data: np.ndarray) -> None:
        """Push a live camera frame to the preview thumbnail."""
        if self._preview is not None:
            self._preview.set_frame(data)

    # ── Theme support ─────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Refresh all sub-widgets after a theme switch."""
        self._header._apply_styles()
        for tile in self._tiles:
            tile._apply_styles()
        if self._info_card is not None:
            self._info_card._apply_styles()
        if self._preview is not None:
            self._preview._apply_styles()
