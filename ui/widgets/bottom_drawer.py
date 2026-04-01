"""
ui/widgets/bottom_drawer.py

BottomDrawer — collapsible bottom panel containing Console and Log.
DrawerToggleBar — always-visible control strip above the drawer.

Layout inside MainWindow (root QVBoxLayout):
    ├── _header
    ├── _safe_banner
    ├── _content_splitter (QSplitter Vertical, stretch=1)
    │   ├── _SplitterTop (nav widget)
    │   └── _bottom_drawer     ← height 0 when closed
    └── _drawer_toggle_bar     ← always visible, 34 px

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
from PyQt5.QtGui  import QPainter, QPainterPath, QColor

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
        console_icon = make_icon(IC.CONSOLE, color=PALETTE["textDim"], size=14)
        log_icon     = make_icon(IC.LOG,     color=PALETTE["textDim"], size=14)
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

    def add_tab(self, widget: QWidget, label: str, icon_name: str = "") -> int:
        """Add a plugin-contributed tab to the drawer.

        Returns the new tab index.
        """
        idx = self._tabs.addTab(widget, f"  {label}")
        if icon_name:
            icon = make_icon(icon_name, color=PALETTE["textDim"], size=14)
            if icon:
                self._tabs.setTabIcon(idx, icon)
        return idx

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(self._tab_qss())
        self._apply_tab_icons()

    def _tab_qss(self) -> str:
        P = PALETTE
        return f"""
            QTabWidget::pane {{
                border-top: 1px solid {P['border']};
                background: {P['surface']};
            }}
            QTabBar::tab {{
                background: {P['surface2']};
                color: {P['textDim']};
                border: none;
                border-right: 1px solid {P['border']};
                padding: 5px 16px;
                font-size: {FONT['label']}pt;
            }}
            QTabBar::tab:selected {{
                background: {P['surface']};
                color: {P['text']};
                border-bottom: 2px solid {P['accent']};
            }}
            QTabBar::tab:hover:!selected {{
                background: {P['surfaceHover']};
                color: {P['text']};
            }}
        """


# ── Grip pill indicator ─────────────────────────────────────────────────────

class _GripPill(QWidget):
    """Pill-shaped grab handle centered inside DrawerToggleBar.

    Acts like an iOS/macOS bottom-sheet handle — visually communicates
    "this bar opens a panel below".  Draws a short rounded rectangle that
    brightens on hover.  Clicking anywhere on the pill emits ``clicked``.
    """

    clicked = pyqtSignal()

    # Pill dimensions (drawn, not the widget)
    _PILL_W = 36
    _PILL_H = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(72, 34)           # same height as the toggle bar
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle panel  (Ctrl+`)")
        self._hovered = False

    # ── Events ─────────────────────────────────────────────────────────

    def enterEvent(self, e) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hovered = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Resting: textDim at 30 % opacity — subtle but clearly not a hairline.
        # Hover:   textDim at 100 % — immediately obvious.
        # Using alpha rather than a separate palette key so both light and
        # dark themes look correct without extra configuration.
        col = QColor(PALETTE["textDim"])
        if not self._hovered:
            col.setAlphaF(0.30)

        x = (self.width()  - self._PILL_W) // 2
        y = (self.height() - self._PILL_H) // 2
        r = self._PILL_H / 2.0

        path = QPainterPath()
        path.addRoundedRect(float(x), float(y),
                            float(self._PILL_W), float(self._PILL_H), r, r)
        p.fillPath(path, col)
        p.end()


# ── Always-visible toggle bar ──────────────────────────────────────────────

class DrawerToggleBar(QWidget):
    """Persistent 34 px strip at the bottom of the window.

    Always visible — even when the drawer is fully collapsed.  Contains:
      • Console / Log quick-access buttons on the left
      • A centered grip pill (visual affordance + click-to-toggle)
      • A clearly-labeled "Panel ∧ / ∨" button on the right

    The entire bar highlights on hover (WA_Hover + QSS :hover) so users
    intuitively understand it's an interactive strip, not just a divider.

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
        self.setFixedHeight(34)
        # Enable :hover QSS selector on this widget (stays active even when
        # the pointer is over child buttons, unlike enterEvent/leaveEvent).
        self.setAttribute(Qt.WA_Hover, True)
        self._is_open = False
        self._build()
        self._apply_styles()

    # ── Build ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)

        # Left — quick-access tab buttons
        self._console_btn = QPushButton("  Console")
        self._log_btn     = QPushButton("  Log")
        for btn in (self._console_btn, self._log_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(26)

        self._console_btn.clicked.connect(self._on_console)
        self._log_btn.clicked.connect(self._on_log)

        lay.addWidget(self._console_btn)
        lay.addWidget(self._log_btn)
        lay.addStretch(1)

        # Center — grip pill (visual affordance)
        self._grip = _GripPill()
        self._grip.clicked.connect(self.toggle_requested)
        lay.addWidget(self._grip)

        lay.addStretch(1)

        # Right — clearly-labeled toggle button
        self._chevron_btn = QPushButton("Panel  ∧")
        self._chevron_btn.setFixedHeight(26)
        self._chevron_btn.setMinimumWidth(88)
        self._chevron_btn.setToolTip("Toggle panel  (Ctrl+`)")
        self._chevron_btn.clicked.connect(self.toggle_requested)
        lay.addWidget(self._chevron_btn)

    # ── Public API ─────────────────────────────────────────────────────

    def set_open(self, is_open: bool) -> None:
        self._is_open = is_open
        self._chevron_btn.setText("Panel  ∨" if is_open else "Panel  ∧")
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
        P       = PALETTE
        bg      = P["surface3"]
        border  = P["border"]
        accent  = P["accent"]
        text    = P["text"]
        textdim = P["textDim"]
        hover   = P["surfaceHover"]
        sz      = FONT["label"]

        # Bar: normal bg + gentle hover highlight across the whole strip.
        # WA_Hover (set in __init__) keeps :hover active even over child widgets.
        self.setStyleSheet(
            f"DrawerToggleBar {{ background:{bg}; border-top:1px solid {border}; }}"
            f"DrawerToggleBar:hover {{ background:{hover}; }}"
        )

        # Console / Log quick-access buttons
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

        # "Panel ∧/∨" — slightly bordered to signal it's the primary action
        chevron_style = f"""
            QPushButton {{
                background: transparent;
                color: {textdim};
                border: 1px solid transparent;
                font-size: {sz}pt;
                border-radius: 3px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: {hover};
                color: {text};
                border-color: {border};
            }}
        """

        self._console_btn.setStyleSheet(btn_base)
        self._log_btn.setStyleSheet(btn_base)
        self._chevron_btn.setStyleSheet(chevron_style)
        # Repaint the grip pill so its color reflects the current palette
        self._grip.update()
