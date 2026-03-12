"""
ui/widgets/bottom_drawer.py

BottomDrawer — collapsible bottom panel containing Console and Log.
DrawerToggleBar — always-visible control strip above the drawer.

Layout inside MainWindow (root QVBoxLayout):
    ├── _header
    ├── _safe_banner
    ├── _content_splitter (QSplitter Vertical, stretch=1)
    │   ├── _mode_stack
    │   └── _bottom_drawer     ← height 0 when closed
    └── _drawer_toggle_bar     ← always visible, 28 px

Toggle keyboard shortcut
------------------------
    Ctrl+`  (grave accent)  →  toggle open / closed
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


# ── Bottom drawer (tab content) ────────────────────────────────────────────

class BottomDrawer(QWidget):
    """Tabbed panel holding Console and Log.

    Height is controlled externally by the QSplitter.  When collapsed,
    height == 0 — the DrawerToggleBar (always visible) provides the affordance
    to reopen it.
    """

    HEIGHT_OPEN = 240   # pixels when toggled open

    def __init__(self, console_tab: QWidget, log_tab: QWidget, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._build(console_tab, log_tab)

    # ── Build ──────────────────────────────────────────────────────────

    def _build(self, console_tab: QWidget, log_tab: QWidget) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_qss())
        self._tabs.addTab(console_tab, "  Console")
        self._tabs.addTab(log_tab,     "  Log")
        self._apply_tab_icons()
        root.addWidget(self._tabs, 1)

    def _apply_tab_icons(self) -> None:
        console_icon = make_icon(IC.CONSOLE, color=PALETTE.get("textDim", "#8892aa"), size=14)
        log_icon     = make_icon(IC.LOG,     color=PALETTE.get("textDim", "#8892aa"), size=14)
        if console_icon:
            self._tabs.setTabIcon(0, console_icon)
        if log_icon:
            self._tabs.setTabIcon(1, log_icon)
        self._tabs.setIconSize(QSize(14, 14))

    # ── Public API ─────────────────────────────────────────────────────

    def show_console(self) -> None:
        self._tabs.setCurrentIndex(0)

    def show_log(self) -> None:
        self._tabs.setCurrentIndex(1)

    def current_tab_index(self) -> int:
        return self._tabs.currentIndex()

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(self._tab_qss())
        self._apply_tab_icons()

    def _tab_qss(self) -> str:
        P = PALETTE
        return f"""
            QTabWidget::pane {{
                border-top: 1px solid {P.get('border', '#2e3245')};
                background: {P.get('surface', '#1a1d28')};
            }}
            QTabBar::tab {{
                background: {P.get('surface2', '#20232e')};
                color: {P.get('textDim', '#8892aa')};
                border: none;
                border-right: 1px solid {P.get('border', '#2e3245')};
                padding: 5px 16px;
                font-size: {FONT['label']}pt;
            }}
            QTabBar::tab:selected {{
                background: {P.get('surface', '#1a1d28')};
                color: {P.get('text', '#dde3f2')};
                border-bottom: 2px solid {P.get('accent', '#00d4aa')};
            }}
            QTabBar::tab:hover:!selected {{
                background: {P.get('surfaceHover', '#262a38')};
                color: {P.get('text', '#dde3f2')};
            }}
        """


# ── Always-visible toggle bar ──────────────────────────────────────────────

class DrawerToggleBar(QWidget):
    """Persistent 28 px strip at the bottom of the window.

    Always visible — even when the drawer is fully collapsed.  Contains
    Console / Log tab-switcher buttons and a chevron to open/close.

    Signals
    -------
    console_requested   Activate Console tab (open drawer if closed)
    log_requested       Activate Log tab (open drawer if closed)
    toggle_requested    Toggle the drawer open/closed
    """

    console_requested = pyqtSignal()
    log_requested     = pyqtSignal()
    toggle_requested  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self._is_open = False
        self._build()
        self._apply_styles()

    # ── Build ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)

        self._console_btn = QPushButton("  Console")
        self._log_btn     = QPushButton("  Log")
        for btn in (self._console_btn, self._log_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(22)

        self._console_btn.clicked.connect(self._on_console)
        self._log_btn.clicked.connect(self._on_log)

        lay.addWidget(self._console_btn)
        lay.addWidget(self._log_btn)
        lay.addStretch()

        self._chevron_btn = QPushButton("∧")
        self._chevron_btn.setFixedSize(22, 22)
        self._chevron_btn.setToolTip("Toggle panel  (Ctrl+`)")
        self._chevron_btn.clicked.connect(self.toggle_requested)
        lay.addWidget(self._chevron_btn)

    # ── Public API ─────────────────────────────────────────────────────

    def set_open(self, is_open: bool) -> None:
        self._is_open = is_open
        self._chevron_btn.setText("∨" if is_open else "∧")
        self._apply_styles()

    def set_active_tab(self, idx: int) -> None:
        self._console_btn.setChecked(self._is_open and idx == 0)
        self._log_btn.setChecked(self._is_open and idx == 1)

    # ── Slots ──────────────────────────────────────────────────────────

    def _on_console(self) -> None:
        if not self._is_open:
            self.toggle_requested.emit()
        self.console_requested.emit()

    def _on_log(self) -> None:
        if not self._is_open:
            self.toggle_requested.emit()
        self.log_requested.emit()

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P = PALETTE
        bg      = P.get("surface3",    "#252830")
        border  = P.get("border",      "#2e3245")
        accent  = P.get("accent",      "#00d4aa")
        text    = P.get("text",        "#dde3f2")
        textdim = P.get("textDim",     "#8892aa")
        hover   = P.get("surfaceHover","#262a38")
        sz      = FONT["label"]

        self.setStyleSheet(
            f"DrawerToggleBar {{ background:{bg}; border-top:1px solid {border}; }}"
        )

        btn_base = f"""
            QPushButton {{
                background: transparent;
                color: {textdim};
                border: none;
                font-size: {sz}pt;
                border-radius: 3px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: {hover};
                color: {text};
            }}
            QPushButton:checked {{
                color: {accent};
                font-weight: bold;
            }}
        """
        chevron_style = f"""
            QPushButton {{
                background: transparent;
                color: {textdim};
                border: none;
                font-size: {sz}pt;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {hover};
                color: {text};
            }}
        """
        self._console_btn.setStyleSheet(btn_base)
        self._log_btn.setStyleSheet(btn_base)
        self._chevron_btn.setStyleSheet(chevron_style)
