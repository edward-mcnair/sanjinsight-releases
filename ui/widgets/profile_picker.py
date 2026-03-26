"""
ui/widgets/profile_picker.py

Compact inline profile picker for the Modality section.

Shows category filter pills and a scrollable list of material profiles.
Selecting a profile emits ``profile_selected`` with the full
``MaterialProfile`` object.  Choosing "Custom" emits ``custom_selected``
and clears the selection.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QButtonGroup,
)
from PyQt5.QtCore import Qt, pyqtSignal

from profiles.profiles import (
    MaterialProfile, BUILTIN_PROFILES, ALL_CATEGORIES,
    CATEGORY_ACCENTS, CATEGORY_COLORS,
)
from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
#  _ProfileCard  — single selectable row
# ────────────────────────────────────────────────────────────────────────

class _ProfileCard(QFrame):
    """A clickable row representing one MaterialProfile."""

    clicked = pyqtSignal(object)   # emits MaterialProfile

    def __init__(self, profile: MaterialProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._selected = False

        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(52)
        self.setFrameShape(QFrame.NoFrame)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        # Colour pip
        accent = CATEGORY_ACCENTS.get(profile.category, "#888")
        self._pip = QLabel()
        self._pip.setFixedSize(6, 6)
        self._pip.setStyleSheet(
            f"background:{accent}; border-radius:3px; margin-top:2px;")
        lay.addWidget(self._pip, 0, Qt.AlignTop)

        # Text column
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)

        self._name_lbl = QLabel(profile.name)
        self._detail_lbl = QLabel(self._detail_text())

        col.addWidget(self._name_lbl)
        col.addWidget(self._detail_lbl)
        lay.addLayout(col, 1)

        # C_T badge
        ct_text = f"C_T {profile.ct_value:.1e}"
        self._ct_lbl = QLabel(ct_text)
        lay.addWidget(self._ct_lbl, 0, Qt.AlignRight)

        self._apply_styles()

    def _detail_text(self) -> str:
        p = self.profile
        parts = [p.material]
        if p.stimulus_freq_hz:
            parts.append(f"{p.stimulus_freq_hz:.0f} Hz")
        if p.cal_temps:
            n = len(p.cal_temps.split(","))
            parts.append(f"{n}-pt cal")
        if p.bias_enabled:
            parts.append(f"Bias {p.bias_voltage_v:.1f} V")
        return "  ·  ".join(parts)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_styles()

    def _apply_styles(self) -> None:
        accent = CATEGORY_ACCENTS.get(self.profile.category, "#888")
        bg_sel = CATEGORY_COLORS.get(self.profile.category, "#1a1a1a")
        bg = bg_sel if self._selected else "transparent"
        border = f"1px solid {accent}88" if self._selected else "1px solid transparent"

        self.setStyleSheet(
            f"_ProfileCard {{ background:{bg}; border:{border}; "
            f"border-radius:6px; }}"
            f"_ProfileCard:hover {{ background:{bg_sel}; }}")
        self._name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{accent if self._selected else PALETTE['text']};")
        self._detail_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")
        self._ct_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            f"font-family:'Menlo','Consolas',monospace;")

    def mousePressEvent(self, event):
        self.clicked.emit(self.profile)


# ────────────────────────────────────────────────────────────────────────
#  ProfilePicker
# ────────────────────────────────────────────────────────────────────────

class ProfilePicker(QWidget):
    """Inline profile selector with category filters."""

    profile_selected = pyqtSignal(object)   # MaterialProfile
    custom_selected  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[_ProfileCard] = []
        self._active_profile: Optional[MaterialProfile] = None
        self._active_category: str = "All"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(6)

        # ── Header ───────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        title = QLabel("Material Profile")
        title.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:bold; "
            f"color:{PALETTE['text']};")
        hdr.addWidget(title)
        hdr.addStretch()

        self._custom_btn = QPushButton("Custom")
        self._custom_btn.setFixedHeight(24)
        self._custom_btn.setCursor(Qt.PointingHandCursor)
        self._custom_btn.clicked.connect(self._on_custom)
        hdr.addWidget(self._custom_btn)
        root.addLayout(hdr)

        # ── Category filter pills ────────────────────────────────────
        pill_row = QHBoxLayout()
        pill_row.setSpacing(4)
        self._pill_group = QButtonGroup(self)
        self._pill_group.setExclusive(True)

        categories = ["All"] + ALL_CATEGORIES
        for i, cat in enumerate(categories):
            btn = QPushButton(cat if cat != "User Defined" else "User")
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("cat", cat)
            if cat == "All":
                btn.setChecked(True)
            self._pill_group.addButton(btn, i)
            pill_row.addWidget(btn)

        self._pill_group.idClicked.connect(self._on_filter)
        pill_row.addStretch()
        root.addLayout(pill_row)

        # ── Scrollable card list ─────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setMaximumHeight(260)

        self._list_widget = QWidget()
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll)

        # ── Status label (shows after selection) ─────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")
        self._status_lbl.setVisible(False)
        root.addWidget(self._status_lbl)

        self._apply_styles()
        self._populate()

    # ── Public API ───────────────────────────────────────────────────

    @property
    def active_profile(self) -> Optional[MaterialProfile]:
        return self._active_profile

    def filter_by_wavelength(self, wavelength_nm: int) -> None:
        """Show only profiles matching a wavelength (0 = show all)."""
        for card in self._cards:
            if wavelength_nm == 0:
                card.setVisible(self._matches_category(card.profile))
            else:
                matches_wl = card.profile.wavelength_nm == wavelength_nm
                matches_cat = self._matches_category(card.profile)
                card.setVisible(matches_wl and matches_cat)

    def filter_by_modality(self, cam_type: str) -> None:
        """Filter to TR (visible/NIR) or IR profiles."""
        if cam_type == "ir":
            # IR profiles would have wavelength > 1000
            for card in self._cards:
                card.setVisible(card.profile.wavelength_nm > 1000
                                and self._matches_category(card.profile))
        else:
            # TR — show all visible/NIR wavelengths
            for card in self._cards:
                card.setVisible(card.profile.wavelength_nm <= 1000
                                and self._matches_category(card.profile))

    # ── Internal ─────────────────────────────────────────────────────

    def _populate(self) -> None:
        # Clear old cards
        for card in self._cards:
            self._list_lay.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        # Load built-in + user profiles
        profiles = list(BUILTIN_PROFILES)
        # TODO: load user profiles from ~/.microsanj/profiles/

        for p in profiles:
            card = _ProfileCard(p)
            card.clicked.connect(self._on_card_clicked)
            # Insert before the stretch
            self._list_lay.insertWidget(self._list_lay.count() - 1, card)
            self._cards.append(card)

    def _on_card_clicked(self, profile: MaterialProfile) -> None:
        self._active_profile = profile
        for card in self._cards:
            card.set_selected(card.profile.uid == profile.uid)
        self._status_lbl.setText(
            f"Selected: {profile.name}")
        self._status_lbl.setVisible(True)
        log.info("ProfilePicker: selected %r", profile.name)
        self.profile_selected.emit(profile)

    def _on_custom(self) -> None:
        self._active_profile = None
        for card in self._cards:
            card.set_selected(False)
        self._status_lbl.setText("Manual configuration — no profile applied")
        self._status_lbl.setVisible(True)
        self.custom_selected.emit()

    def _on_filter(self, btn_id: int) -> None:
        btn = self._pill_group.button(btn_id)
        cat = btn.property("cat") if btn else "All"
        self._active_category = cat
        for card in self._cards:
            card.setVisible(self._matches_category(card.profile))

    def _matches_category(self, profile: MaterialProfile) -> bool:
        if self._active_category == "All":
            return True
        return profile.category == self._active_category

    # ── Theme ────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        accent = PALETTE.get("accent", "#00d4aa")
        surface = PALETTE.get("surface", "#2d2d2d")
        text = PALETTE.get("text", "#e0e0e0")
        dim = PALETTE.get("textDim", "#888")

        # Custom button
        self._custom_btn.setStyleSheet(
            f"QPushButton {{ background:{surface}; color:{dim}; "
            f"border:1px solid {dim}44; border-radius:4px; "
            f"font-size:{FONT['caption']}pt; padding:0 8px; }}"
            f"QPushButton:hover {{ color:{text}; border-color:{accent}88; }}")

        # Category pills
        for btn in self._pill_group.buttons():
            btn.setStyleSheet(
                f"QPushButton {{ background:{surface}; color:{dim}; "
                f"border:1px solid transparent; border-radius:4px; "
                f"font-size:{FONT['caption']}pt; padding:0 8px; }}"
                f"QPushButton:checked {{ background:{accent}22; "
                f"color:{accent}; border:1px solid {accent}66; }}"
                f"QPushButton:hover {{ color:{text}; }}")

        # Status label
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{dim};")

        # Scroll area background
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background:transparent; }}"
            f"QWidget {{ background:transparent; }}")

        # Re-style cards
        for card in self._cards:
            card._apply_styles()
