"""
ui/tabs/focus_stage_tab.py

FocusStageTab — merged Focus (Autofocus) + Stage + Prober.

Combines AutofocusTab, StageTab, and optionally ProberTab
under one sidebar entry with sub-tabs.
Phase 2 · IMAGE ACQUISITION
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class FocusStageTab(QWidget):
    """Focus & Stage: Autofocus, Stage control, and Prober as sub-tabs."""

    # Pass-through signals
    open_device_manager = pyqtSignal()

    def __init__(self, af_tab: QWidget, stage_tab: QWidget,
                 prober_tab: QWidget | None = None, parent=None):
        super().__init__(parent)
        self._af_tab     = af_tab
        self._stage_tab  = stage_tab
        self._prober_tab = prober_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._tabs.addTab(af_tab,    "  Focus")
        self._tabs.addTab(stage_tab, "  Stage")
        if prober_tab is not None:
            self._tabs.addTab(prober_tab, "  Prober")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        # Pass through open_device_manager from sub-tabs
        if hasattr(stage_tab, "open_device_manager"):
            stage_tab.open_device_manager.connect(self.open_device_manager)
        if prober_tab is not None and hasattr(prober_tab, "open_device_manager"):
            prober_tab.open_device_manager.connect(self.open_device_manager)

    def set_prober_visible(self, visible: bool) -> None:
        """Show or hide the Prober sub-tab."""
        if self._prober_tab is not None:
            idx = self._tabs.indexOf(self._prober_tab)
            if idx >= 0:
                self._tabs.setTabVisible(idx, visible)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()
        for sub in (self._af_tab, self._stage_tab, self._prober_tab):
            if sub is not None and hasattr(sub, "_apply_styles"):
                sub._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.AUTOFOCUS, color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.STAGE,     color=PALETTE.get("textDim", "#8892aa"), size=14),
        ]
        if self._prober_tab is not None:
            icons.append(
                make_icon(IC.PROBER, color=PALETTE.get("textDim", "#8892aa"), size=14))
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
