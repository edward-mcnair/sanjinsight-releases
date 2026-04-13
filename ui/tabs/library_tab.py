"""
ui/tabs/library_tab.py

LibraryTab — unified Library tab for Material Profiles and Recipes.

Combines ProfileTab (material/calibration profiles) and RecipeTab
(acquisition recipes) into a single "Library" sidebar entry.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon
from ui.widgets.tab_helpers import inner_tab_qss


class LibraryTab(QWidget):
    """Library: Material Profiles + Recipes as sub-tabs."""

    # Pass-through signals
    profile_applied = pyqtSignal(object)   # MaterialProfile
    recipe_run      = pyqtSignal(object)   # Recipe

    def __init__(self, profile_tab: QWidget, recipe_tab: QWidget, parent=None):
        super().__init__(parent)
        self._profile_tab = profile_tab
        self._recipe_tab  = recipe_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(inner_tab_qss())
        self._tabs.addTab(profile_tab, "Material Profiles")
        self._tabs.addTab(recipe_tab,  "Recipes")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        # Wire inner signals upward
        if hasattr(profile_tab, "profile_applied"):
            profile_tab.profile_applied.connect(self.profile_applied)
        if hasattr(recipe_tab, "recipe_run"):
            recipe_tab.recipe_run.connect(self.recipe_run)

    # ── Attention dots ─────────────────────────────────────────────

    _TAB_BASE = {0: "  Material Profiles", 1: "  Recipes"}
    _TAB_ICONS = {0: IC.PROFILES, 1: IC.RECIPES}
    _DOT = "\u2009\u25cf"

    def set_tab_attention(self, tab_index: int, needs_attention: bool) -> None:
        """Show/hide a red attention dot on a sub-tab."""
        if tab_index < 0 or tab_index >= self._tabs.count():
            return
        base = self._TAB_BASE.get(tab_index, "")
        if needs_attention:
            self._tabs.setTabText(tab_index, base + self._DOT)
            icon_name = self._TAB_ICONS.get(tab_index)
            if icon_name:
                icon = make_icon(icon_name, color=PALETTE["danger"], size=14)
                if icon:
                    self._tabs.setTabIcon(tab_index, icon)
        else:
            self._tabs.setTabText(tab_index, base)
            self._apply_tab_icons()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(inner_tab_qss())
        self._apply_tab_icons()
        for sub in (self._profile_tab, self._recipe_tab):
            if hasattr(sub, "_apply_styles"):
                sub._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.PROFILES, color=PALETTE["textDim"], size=14),
            make_icon(IC.RECIPES,  color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)
