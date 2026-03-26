"""
ui/widgets/profile_picker.py

Compact profile picker — a single combo-box dropdown.

Selecting a profile emits ``profile_selected`` with the full
``MaterialProfile`` object.  The dropdown filters by camera modality
so only relevant profiles appear.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from profiles.profiles import (
    MaterialProfile, BUILTIN_PROFILES, ALL_CATEGORIES,
    CATEGORY_ACCENTS,
)
from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)


class ProfilePicker(QWidget):
    """Compact profile selector — dropdown combo box."""

    profile_selected = pyqtSignal(object)   # MaterialProfile
    custom_selected  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_profiles: list[MaterialProfile] = list(BUILTIN_PROFILES)
        self._visible_profiles: list[MaterialProfile] = []
        self._active_profile: Optional[MaterialProfile] = None
        self._modality_filter: str = ""  # "" = all, "tr"/"ir" = filter

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(4)

        # ── Hint text ──────────────────────────────────────────────────
        self._hint_lbl = QLabel(
            "Select a profile or skip to configure settings manually.")
        self._hint_lbl.setWordWrap(True)
        root.addWidget(self._hint_lbl)

        # ── Dropdown ───────────────────────────────────────────────────
        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        root.addWidget(self._combo)

        # ── Detail label (shows after selection) ───────────────────────
        self._detail_lbl = QLabel("")
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setVisible(False)
        root.addWidget(self._detail_lbl)

        self._apply_styles()
        self._rebuild_combo()

    # ── Public API ───────────────────────────────────────────────────

    @property
    def active_profile(self) -> Optional[MaterialProfile]:
        return self._active_profile

    def filter_by_modality(self, cam_type: str) -> None:
        """Filter profiles by camera modality ('tr' or 'ir')."""
        if cam_type != self._modality_filter:
            self._modality_filter = cam_type
            self._rebuild_combo()

    def set_modality_filter(self, modality: str) -> None:
        """Alias for filter_by_modality."""
        self.filter_by_modality(modality)

    def filter_by_wavelength(self, wavelength_nm: int) -> None:
        """Legacy — filter by wavelength (0 = show all)."""
        # Modality filter is the primary mechanism now; wavelength is
        # implicit in the profile's modality tag.
        pass

    # ── Internal ─────────────────────────────────────────────────────

    def _rebuild_combo(self) -> None:
        """Rebuild the combo box items from the filtered profile list."""
        self._combo.blockSignals(True)
        self._combo.clear()

        # Placeholder item
        self._combo.addItem("Select a Profile…")

        # Filter profiles by modality
        self._visible_profiles = []
        for p in self._all_profiles:
            pm = getattr(p, "modality", "tr")
            if self._modality_filter and pm not in (self._modality_filter, "any"):
                continue
            self._visible_profiles.append(p)

        # Group by category
        seen_cats: list[str] = []
        for p in self._visible_profiles:
            if p.category not in seen_cats:
                seen_cats.append(p.category)

        for cat in seen_cats:
            # Category separator (disabled item)
            self._combo.addItem(f"── {cat} ──")
            idx = self._combo.count() - 1
            self._combo.model().item(idx).setEnabled(False)

            for p in self._visible_profiles:
                if p.category == cat:
                    label = p.name
                    if p.ct_value > 0:
                        label += f"  (C_T {p.ct_value:.1e})"
                    self._combo.addItem(label, p.uid)

        self._combo.blockSignals(False)

        # Restore selection if the active profile is still visible
        if self._active_profile:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == self._active_profile.uid:
                    self._combo.setCurrentIndex(i)
                    return
        self._combo.setCurrentIndex(0)

    def _on_combo_changed(self, index: int) -> None:
        uid = self._combo.itemData(index)
        if uid is None:
            # Placeholder or separator selected
            if self._active_profile is not None:
                self._active_profile = None
                self._detail_lbl.setVisible(False)
                self.custom_selected.emit()
            return

        # Find the matching profile
        for p in self._visible_profiles:
            if p.uid == uid:
                self._active_profile = p
                self._show_detail(p)
                log.info("ProfilePicker: selected %r", p.name)
                self.profile_selected.emit(p)
                return

    def _show_detail(self, p: MaterialProfile) -> None:
        """Show a brief summary below the dropdown."""
        parts = []
        if p.material:
            parts.append(p.material)
        if p.stimulus_freq_hz:
            parts.append(f"{p.stimulus_freq_hz:.0f} Hz")
        if p.cal_temps:
            n = len(p.cal_temps.split(","))
            parts.append(f"{n}-pt cal")
        if p.bias_enabled:
            parts.append(f"Bias {p.bias_voltage_v:.1f} V")
        if p.recommended_objective:
            parts.append(p.recommended_objective)

        accent = CATEGORY_ACCENTS.get(p.category, PALETTE.get("accent", "#00d4aa"))
        self._detail_lbl.setText("  ·  ".join(parts))
        self._detail_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{accent}; padding-left:2px;")
        self._detail_lbl.setVisible(True)

    # ── Theme ────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        accent = PALETTE.get("accent", "#00d4aa")
        surface = PALETTE.get("surface", "#2d2d2d")
        surface2 = PALETTE.get("surface2", "#242424")
        text = PALETTE.get("text", "#e0e0e0")
        dim = PALETTE.get("textDim", "#888")

        self._hint_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{dim}; padding:0;")

        self._combo.setStyleSheet(
            f"QComboBox {{ background:{surface2}; color:{text}; "
            f"border:1px solid {dim}44; border-radius:4px; "
            f"font-size:{FONT['label']}pt; padding:4px 8px; }}"
            f"QComboBox:hover {{ border-color:{accent}88; }}"
            f"QComboBox::drop-down {{ border:none; width:20px; }}"
            f"QComboBox QAbstractItemView {{ "
            f"background:{surface2}; color:{text}; "
            f"selection-background-color:{accent}33; "
            f"selection-color:{accent}; "
            f"border:1px solid {dim}44; }}")

        if hasattr(self, "_detail_lbl"):
            self._detail_lbl.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{dim}; padding-left:2px;")
