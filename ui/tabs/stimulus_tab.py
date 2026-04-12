"""
ui/tabs/stimulus_tab.py

StimulusTab — unified hardware tab for FPGA modulation + Bias Source.

Replaces two separate sidebar entries ("FPGA" and "Bias Source") with a
single "Stimulus" entry.  Each sub-tab preserves its full existing UI.
"""
from __future__ import annotations

import logging

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTabWidget,
                             QScrollArea, QSizePolicy)
from PyQt5.QtCore    import Qt, pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon
from ui.widgets.tab_helpers import inner_tab_qss
from ui.widgets.tab_attention import TabAttentionMixin
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after

log = logging.getLogger(__name__)


class StimulusTab(QWidget, TabAttentionMixin):
    """Stimulus control: FPGA modulation + Bias source + IV Sweep as sub-tabs."""

    # Pass-through signals from inner tabs
    open_device_manager = pyqtSignal()
    navigate_requested = pyqtSignal(str)

    def __init__(self, fpga_tab: QWidget, bias_tab: QWidget, parent=None):
        super().__init__(parent)
        self._fpga_tab = fpga_tab
        self._bias_tab = bias_tab

        from ui.tabs.iv_sweep_tab import IVSweepTab
        self._iv_sweep_tab = IVSweepTab()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Guidance cards (Guided mode) — scrollable area ────────
        _cards = get_section_cards("stimulus")
        def _body(cid):
            for c in _cards:
                if c["card_id"] == cid:
                    return c["body"]
            return ""

        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "stimulus.overview",
            "Getting Started with Stimulus",
            _body("stimulus.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "stimulus.modulation",
            "Configure the Modulation Signal",
            _body("stimulus.modulation"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._guide_card2 = GuidanceCard(
            "stimulus.bias",
            "Set the Bias Current",
            _body("stimulus.bias"),
            step_number=2)
        self._guide_card2.setVisible(False)
        cards_lay.addWidget(self._guide_card2)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QScrollArea.NoFrame)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setMaximumHeight(280)
        self._cards_scroll.setWidget(self._cards_widget)
        self._cards_scroll.setVisible(False)
        root.addWidget(self._cards_scroll)

        for c in (self._overview_card, self._guide_card1, self._guide_card2):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Stimulus", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)

        # ── Sub-tabs ──────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_qss())
        self._tabs.addTab(fpga_tab,              "  Modulation")
        self._tabs.addTab(bias_tab,              "  Bias Source")
        self._tabs.addTab(self._iv_sweep_tab,    "  IV Sweep")
        self._apply_tab_icons()
        self._init_tab_attention(self._tabs)

        root.addWidget(self._tabs, 1)
        root.addWidget(self._workflow_footer)

        # Wire inner open_device_manager signals upward
        for tab in (fpga_tab, bias_tab):
            if hasattr(tab, "open_device_manager"):
                tab.open_device_manager.connect(self.open_device_manager)

    # ── Public API passthrough ────────────────────────────────────────

    def update_status(self, status) -> None:
        """Delegate to whichever inner tab cares about this status object."""
        for tab in (self._fpga_tab, self._bias_tab, self._iv_sweep_tab):
            if hasattr(tab, "update_status"):
                try:
                    tab.update_status(status)
                except Exception:
                    log.warning(
                        "StimulusTab.update_status: %s.update_status() raised",
                        type(tab).__name__, exc_info=True)

    def set_hardware_available(self, available: bool) -> None:
        for tab in (self._fpga_tab, self._bias_tab):
            if hasattr(tab, "set_hardware_available"):
                tab.set_hardware_available(available)

    def set_bias_driver(self, bias_driver, camera_driver=None, pipeline=None) -> None:
        """Wire bias/camera drivers into the IV Sweep sub-tab."""
        self._iv_sweep_tab.set_drivers(bias_driver, camera_driver, pipeline)

    # ── Workspace mode ────────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        is_guided = (mode == "guided")
        self._guide_card1.setVisible(is_guided)
        self._guide_card2.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._overview_card.setVisible(not is_guided)
        self._update_cards_scroll_visibility()

    def _update_cards_scroll_visibility(self) -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1, self._guide_card2))
        self._cards_scroll.setVisible(any_visible)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(self._tab_qss())
        self._apply_tab_icons()
        for sub in (self._fpga_tab, self._bias_tab, self._iv_sweep_tab):
            if hasattr(sub, "_apply_styles"):
                sub._apply_styles()
        for c in (self._overview_card, self._guide_card1, self._guide_card2):
            if hasattr(c, "_apply_styles"):
                c._apply_styles()
        self._workflow_footer._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.FPGA,     color=PALETTE["textDim"], size=14),
            make_icon(IC.BIAS,     color=PALETTE["textDim"], size=14),
            make_icon(IC.IV_SWEEP, color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)

    def _tab_qss(self) -> str:
        return _inner_tab_qss()


def _inner_tab_qss() -> str:
    return inner_tab_qss()
