"""
ui/tabs/capture_tab.py

CaptureTab — unified acquisition tab: Single Capture + Grid Scan.

Combines AcquireTab (single-point acquisition) and ScanTab (spatial scan)
under one sidebar entry with "Single" / "Grid" mode tabs.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QScrollArea
from PyQt5.QtCore    import Qt, pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon
from ui.widgets.tab_helpers import inner_tab_qss
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after


_CARDS = get_section_cards("capture")

def _card_body(card_id: str) -> str:
    for c in _CARDS:
        if c["card_id"] == card_id:
            return c["body"]
    return ""


class CaptureTab(QWidget):
    """Capture: Single-point (Acquire) and Grid Scan as mode tabs."""

    # Pass-through from AcquireTab
    acquire_requested = pyqtSignal(int, float)   # n_frames, inter_phase_delay
    navigate_requested = pyqtSignal(str)

    def __init__(self, acquire_tab: QWidget, scan_tab: QWidget, parent=None):
        super().__init__(parent)
        self._acquire_tab = acquire_tab
        self._scan_tab    = scan_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Guidance cards — scrollable area ──────────────────────
        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "capture.overview",
            "Getting Started with Capture",
            _card_body("capture.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "capture.settings",
            "Review Capture Settings",
            _card_body("capture.settings"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._guide_card2 = GuidanceCard(
            "capture.acquire",
            "Start the Acquisition",
            _card_body("capture.acquire"),
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

        for c in (self._overview_card, self._guide_card1, self._guide_card2):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Capture", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)

        # ── Sub-tabs ──────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(inner_tab_qss())
        self._tabs.addTab(acquire_tab, "Single")
        self._tabs.addTab(scan_tab,    "Grid")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)
        root.addWidget(self._workflow_footer)

        if hasattr(acquire_tab, "acquire_requested"):
            acquire_tab.acquire_requested.connect(self.acquire_requested)

    # ── Public API passthrough ────────────────────────────────────────

    def update_live(self, frame) -> None:
        if hasattr(self._acquire_tab, "update_live"):
            self._acquire_tab.update_live(frame)

    def update_progress(self, p) -> None:
        if hasattr(self._acquire_tab, "update_progress"):
            self._acquire_tab.update_progress(p)

    def update_result(self, result) -> None:
        if hasattr(self._acquire_tab, "update_result"):
            self._acquire_tab.update_result(result)

    def set_active_recipe_name(self, name: str) -> None:
        if hasattr(self._acquire_tab, "set_active_recipe_name"):
            self._acquire_tab.set_active_recipe_name(name)

    def set_n_frames(self, n: int) -> None:
        if hasattr(self._acquire_tab, "set_n_frames"):
            self._acquire_tab.set_n_frames(n)

    def get_notes(self) -> str:
        if hasattr(self._acquire_tab, "get_notes"):
            return self._acquire_tab.get_notes()
        return ""

    def insert_readiness_widget(self, widget: QWidget) -> None:
        if hasattr(self._acquire_tab, "insert_readiness_widget"):
            self._acquire_tab.insert_readiness_widget(widget)

    def start_acquisition(self, *args, **kwargs) -> None:
        if hasattr(self._acquire_tab, "start_acquisition"):
            self._acquire_tab.start_acquisition(*args, **kwargs)

    # ── Workspace mode ────────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        is_guided = (mode == "guided")
        self._guide_card1.setVisible(is_guided)
        self._guide_card2.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._overview_card.setVisible(not is_guided)
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1, self._guide_card2))
        self._cards_scroll.setVisible(any_visible)

    def _update_cards_scroll_visibility(self, _card_id: str = "") -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1, self._guide_card2))
        self._cards_scroll.setVisible(any_visible)

    # ── Attention dots ─────────────────────────────────────────────

    _TAB_BASE = {0: "  Single", 1: "  Grid"}
    _TAB_ICONS = {0: IC.CAPTURE, 1: IC.SCAN_GRID}
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
        for sub in (self._acquire_tab, self._scan_tab):
            if hasattr(sub, "_apply_styles"):
                sub._apply_styles()
        for card in (self._overview_card, self._guide_card1, self._guide_card2):
            card._apply_styles()
        self._workflow_footer._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.CAPTURE,   color=PALETTE["textDim"], size=14),
            make_icon(IC.SCAN_GRID, color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)
