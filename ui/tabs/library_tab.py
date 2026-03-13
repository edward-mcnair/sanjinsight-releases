"""
ui/tabs/library_tab.py

LibraryTab — unified Library tab for Material Profiles and Scan Profiles.

Combines ProfileTab (material/calibration profiles) and RecipeTab
(acquisition scan profiles) into a single "Library" sidebar entry.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class LibraryTab(QWidget):
    """Library: Material Profiles + Scan Profiles as sub-tabs."""

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
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._tabs.addTab(profile_tab, "  Material Profiles")
        self._tabs.addTab(recipe_tab,  "  Scan Profiles")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        # Wire inner signals upward
        if hasattr(profile_tab, "profile_applied"):
            profile_tab.profile_applied.connect(self.profile_applied)
        if hasattr(recipe_tab, "recipe_run"):
            recipe_tab.recipe_run.connect(self.recipe_run)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.PROFILES, color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.RECIPES,  color=PALETTE.get("textDim", "#8892aa"), size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)


def _inner_tab_qss() -> str:
    P = PALETTE
    return f"""
        QTabWidget::pane {{ border:none; background:{P.get('bg','#12151f')}; }}
        QTabBar::tab {{
            background:{P.get('surface2','#20232e')}; color:{P.get('textDim','#8892aa')};
            border:none; border-right:1px solid {P.get('border','#2e3245')};
            padding:6px 20px; font-size:{FONT['label']}pt;
        }}
        QTabBar::tab:selected {{
            background:{P.get('surface','#1a1d28')}; color:{P.get('text','#dde3f2')};
            border-bottom:2px solid {P.get('accent','#00d4aa')};
        }}
        QTabBar::tab:hover:!selected {{
            background:{P.get('surfaceHover','#262a38')}; color:{P.get('text','#dde3f2')};
        }}
    """
