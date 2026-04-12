"""
ui/tabs/focus_stage_tab.py

FocusStageTab — merged Focus (Autofocus) + Stage + Prober.

Combines AutofocusTab, StageTab, and optionally ProberTab
under one sidebar entry with sub-tabs.
Phase 2 · IMAGE ACQUISITION
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QScrollArea
from PyQt5.QtCore import Qt, pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon
from ui.widgets.tab_helpers import inner_tab_qss
from ui.widgets.tab_attention import TabAttentionMixin
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after


_CARDS = get_section_cards("focus_stage")

def _card_body(card_id: str) -> str:
    for c in _CARDS:
        if c["card_id"] == card_id:
            return c["body"]
    return ""


class FocusStageTab(QWidget, TabAttentionMixin):
    """Focus & Stage: Autofocus, Stage control, and Prober as sub-tabs."""

    # Pass-through signals
    open_device_manager = pyqtSignal()
    navigate_requested = pyqtSignal(str)

    def __init__(self, af_tab: QWidget, stage_tab: QWidget,
                 prober_tab: QWidget | None = None, parent=None):
        super().__init__(parent)
        self._af_tab     = af_tab
        self._stage_tab  = stage_tab
        self._prober_tab = prober_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Guidance cards (Guided mode) — scrollable area ────────
        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "focus_stage.overview",
            "Getting Started with Focus & Stage",
            _card_body("focus_stage.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "focus_stage.home",
            "Home the Stage",
            _card_body("focus_stage.home"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._guide_card2 = GuidanceCard(
            "focus_stage.focus",
            "Focus on Your Sample",
            _card_body("focus_stage.focus"),
            step_number=2)
        self._guide_card2.setVisible(False)
        cards_lay.addWidget(self._guide_card2)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setObjectName("LeftPanelScroll")
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QScrollArea.NoFrame)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setMaximumHeight(280)
        self._cards_scroll.setWidget(self._cards_widget)
        self._cards_scroll.setVisible(False)
        root.addWidget(self._cards_scroll)

        # Hide scroll area when all cards are dismissed
        for c in (self._overview_card, self._guide_card1, self._guide_card2):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Focus & Stage", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)

        # ── Sub-tabs ──────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(inner_tab_qss())
        self._tabs.addTab(af_tab,    "Focus")
        self._tabs.addTab(stage_tab, "Stage")
        if prober_tab is not None:
            self._tabs.addTab(prober_tab, "Prober")
        self._apply_tab_icons()
        self._init_tab_attention(self._tabs)

        root.addWidget(self._tabs, 1)
        root.addWidget(self._workflow_footer)

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

    # ── Workspace mode ────────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        is_guided = (mode == "guided")
        self._guide_card1.setVisible(is_guided)
        self._guide_card2.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._overview_card.setVisible(not is_guided)
        # Show the scrollable card container when any card is visible
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1, self._guide_card2))
        self._cards_scroll.setVisible(any_visible)

    def _update_cards_scroll_visibility(self, _card_id: str = "") -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1, self._guide_card2))
        self._cards_scroll.setVisible(any_visible)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(inner_tab_qss())
        self._apply_tab_icons()
        for sub in (self._af_tab, self._stage_tab, self._prober_tab):
            if sub is not None and hasattr(sub, "_apply_styles"):
                sub._apply_styles()
        for card in (self._overview_card, self._guide_card1, self._guide_card2):
            card._apply_styles()
        self._workflow_footer._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.AUTOFOCUS, color=PALETTE["textDim"], size=14),
            make_icon(IC.STAGE,     color=PALETTE["textDim"], size=14),
        ]
        if self._prober_tab is not None:
            icons.append(
                make_icon(IC.PROBER, color=PALETTE["textDim"], size=14))
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)
