"""
ui/sidebar_nav.py  —  SanjINSIGHT sidebar navigation

Expanded : full-width panel with section headers + menu items
Collapsed: thin blue accent bar (22px) with a ▶ arrow — click to expand

Toggle lives in the logo header row (◀ arrow, right-aligned).
"""
from __future__ import annotations
from typing import List, Optional, NamedTuple

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolTip,
    QStackedWidget, QSizePolicy, QScrollArea, QFrame,
)
from PyQt5.QtCore  import Qt, pyqtSignal, QPoint
from PyQt5.QtGui   import (
    QColor, QFont, QPainter, QPen, QCursor,
    QPainterPath, QFontMetrics,
)

# ── Palette ────────────────────────────────────────────────────────
_BG         = "#1a1a1a"
_BG_HOVER   = "#222222"
_BG_ACTIVE  = "#0d2520"
_ACCENT     = "#00d4aa"
_TEXT_DIM   = "#777777"
_TEXT_NORM  = "#c0c0c0"
_TEXT_WHITE = "#ffffff"
_DIVIDER    = "#2a2a2a"
_HDR_BG     = "#111111"

# ── Sizes ──────────────────────────────────────────────────────────
_ITEM_H    = 30    # menu row height
_SECTION_H = 24    # section label height
_COLL_H    = 32    # collapsible group header height
_LOGO_H    = 56    # logo/header area
_W_FULL    = 240   # expanded width
_W_MINI    = 22    # collapsed — thin blue bar

# ── Fonts ──────────────────────────────────────────────────────────
_ITEM_FONT_PT    = 14   # menu item label
_SECTION_FONT_PT = 11   # section header caps label (slightly bigger feel via weight+spacing)
_ICON_FONT_PT    = 13   # icon glyphs


class NavItem(NamedTuple):
    label: str
    icon:  str
    panel: QWidget
    badge: str = ""


# ================================================================== #
#  _MenuItem                                                          #
# ================================================================== #
class _MenuItem(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, item: NavItem, indent: int = 0, parent=None):
        super().__init__(parent)
        self._item   = item
        self._indent = indent
        self._active = False
        self._hover  = False
        self.setFixedHeight(_ITEM_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip(item.label)

    @property
    def panel(self): return self._item.panel

    def set_active(self, v):
        if self._active != v:
            self._active = v
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._item.panel)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if self._active:
            p.fillRect(0, 0, w, h, QColor(_BG_ACTIVE))
            p.fillRect(0, 0, 3, h, QColor(_ACCENT))
        elif self._hover:
            p.fillRect(0, 0, w, h, QColor(_BG_HOVER))
        else:
            p.fillRect(0, 0, w, h, QColor(_BG))

        x = 18 + self._indent
        icon_col = QColor(_ACCENT if self._active else
                         (_TEXT_NORM if self._hover else _TEXT_DIM))

        p.setFont(QFont("Segoe UI Symbol", _ICON_FONT_PT))
        p.setPen(icon_col)
        p.drawText(x, 0, 26, h, Qt.AlignVCenter | Qt.AlignLeft, self._item.icon)

        lf = QFont("Segoe UI", _ITEM_FONT_PT)
        if self._active:
            lf.setWeight(QFont.DemiBold)
        p.setFont(lf)
        p.setPen(QColor(_TEXT_WHITE if (self._active or self._hover) else _TEXT_NORM))
        p.drawText(x + 30, 0, w - x - 38, h,
                   Qt.AlignVCenter | Qt.AlignLeft, self._item.label)

        if self._item.badge:
            bf = QFont("Segoe UI", 9)
            bf.setWeight(QFont.Bold)
            p.setFont(bf)
            fm = QFontMetrics(bf)
            bw = fm.horizontalAdvance(self._item.badge) + 10
            bh = 17
            bx = w - bw - 10
            by = (h - bh) // 2
            path = QPainterPath()
            path.addRoundedRect(bx, by, bw, bh, 8, 8)
            p.fillPath(path, QColor(_ACCENT))
            p.setPen(QColor("#fff"))
            p.drawText(bx, by, bw, bh, Qt.AlignCenter, self._item.badge)

        p.end()


# ================================================================== #
#  _SectionLabel                                                      #
# ================================================================== #
class _SectionLabel(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self.setFixedHeight(_SECTION_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), self.height(), QColor(_BG))
        # Thin top rule
        p.setPen(QPen(QColor(_DIVIDER), 1))
        p.drawLine(16, 8, self.width() - 16, 8)
        # Label — bold, spaced caps, slightly larger than items
        f = QFont("Segoe UI", _SECTION_FONT_PT)
        f.setWeight(QFont.Black)          # heaviest weight for visual dominance
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(QColor(_TEXT_NORM))      # brighter than _TEXT_DIM
        p.drawText(18, 8, self.width() - 22, _SECTION_H - 8,
                   Qt.AlignVCenter | Qt.AlignLeft, self._title.upper())
        p.end()


# ================================================================== #
#  _CollapseHeader  (Hardware group etc)                              #
# ================================================================== #
class _CollapseHeader(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, icon: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._title     = title
        self._icon      = icon
        self._collapsed = collapsed
        self._hover     = False
        self.setFixedHeight(_COLL_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip(title)

    def enterEvent(self, e): self._hover = True;  self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._collapsed = not self._collapsed
            self.toggled.emit(self._collapsed)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG_HOVER if self._hover else _BG))
        col = QColor(_TEXT_NORM if self._hover else _TEXT_DIM)

        p.setFont(QFont("Segoe UI Symbol", _ICON_FONT_PT))
        p.setPen(col)
        p.drawText(18, 0, 26, h, Qt.AlignVCenter | Qt.AlignLeft, self._icon)

        f = QFont("Segoe UI", _ITEM_FONT_PT)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(col)
        p.drawText(48, 0, w - 70, h, Qt.AlignVCenter | Qt.AlignLeft, self._title)

        p.setFont(QFont("Segoe UI Symbol", 10))
        p.setPen(QColor(_TEXT_DIM))
        p.drawText(w - 26, 0, 20, h, Qt.AlignVCenter | Qt.AlignLeft,
                   "▾" if not self._collapsed else "▸")
        p.end()


# ================================================================== #
#  _LogoHeader  — app name + collapse arrow                          #
# ================================================================== #
class _LogoHeader(QWidget):
    collapse_clicked = pyqtSignal()

    _ARROW_W = 34   # width of the clickable arrow zone on the right

    def __init__(self, app_name: str, parent=None):
        super().__init__(parent)
        self._app_name   = app_name
        self._arrow_hover = False
        self.setFixedHeight(_LOGO_H)
        self.setStyleSheet(f"background:{_HDR_BG};")
        self.setMouseTracking(True)

    def _arrow_rect(self):
        """Returns (x, y, w, h) of the clickable arrow area."""
        return (self.width() - self._ARROW_W, 0, self._ARROW_W, self.height())

    def mouseMoveEvent(self, e):
        ax, ay, aw, ah = self._arrow_rect()
        in_arrow = ax <= e.x() < ax + aw
        if in_arrow != self._arrow_hover:
            self._arrow_hover = in_arrow
            self.setCursor(QCursor(Qt.PointingHandCursor if in_arrow else Qt.ArrowCursor))
            self.update()

    def leaveEvent(self, e):
        if self._arrow_hover:
            self._arrow_hover = False
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            ax, ay, aw, ah = self._arrow_rect()
            if ax <= e.x() < ax + aw:
                self.collapse_clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(_HDR_BG))

        # Bottom border
        p.setPen(QPen(QColor(_DIVIDER), 1))
        p.drawLine(0, h - 1, w, h - 1)

        # App name
        f = QFont("Segoe UI", 17)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor(_TEXT_WHITE))
        p.drawText(18, 0, w - self._ARROW_W - 20, h,
                   Qt.AlignVCenter | Qt.AlignLeft, self._app_name)

        # Collapse arrow ◀  (right edge, subtle unless hovered)
        af = QFont("Segoe UI Symbol", 13)
        p.setFont(af)
        arrow_col = QColor(_TEXT_WHITE) if self._arrow_hover else QColor(_TEXT_DIM)
        p.setPen(arrow_col)
        ax, ay, aw, ah = self._arrow_rect()
        p.drawText(ax, ay, aw - 4, ah, Qt.AlignVCenter | Qt.AlignLeft, "◀")

        p.end()


# ================================================================== #
#  _CollapseBar  — the thin blue bar shown when sidebar is collapsed  #
# ================================================================== #
class _CollapseBar(QWidget):
    expand_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setFixedWidth(_W_MINI)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip("Expand sidebar")

    def enterEvent(self, e): self._hover = True;  self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.expand_clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Blue accent bar fill
        bar_color = QColor(_ACCENT).lighter(115) if self._hover else QColor(_ACCENT)
        p.fillRect(0, 0, w, h, bar_color)

        # Centred ▶ arrow, vertically centred
        f = QFont("Segoe UI Symbol", 10)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(0, h // 2 - 40, w, 80, Qt.AlignCenter, "▶")

        p.end()


# ================================================================== #
#  _Sidebar  — the full expandable panel                             #
# ================================================================== #
class _Sidebar(QWidget):
    item_selected    = pyqtSignal(object)
    collapse_clicked = pyqtSignal()

    def __init__(self, app_name: str = "SanjINSIGHT", parent=None):
        super().__init__(parent)
        self._items:       List[_MenuItem]       = []
        self._sections:    List[_SectionLabel]   = []
        self._cheaders:    List[_CollapseHeader] = []
        self._containers:  List[QWidget]         = []
        self._coll_states: List[bool]            = []
        self._active:      Optional[_MenuItem]   = None

        self.setFixedWidth(_W_FULL)
        self.setStyleSheet(f"background:{_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Logo header with built-in collapse arrow
        self._logo_hdr = _LogoHeader(app_name)
        self._logo_hdr.collapse_clicked.connect(self.collapse_clicked)
        root.addWidget(self._logo_hdr)

        # Scrollable menu
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background:{_BG}; border:none; }}
            QScrollBar:vertical {{ background:{_BG}; width:5px; margin:0; }}
            QScrollBar::handle:vertical {{ background:#3a3a3a; border-radius:2px; min-height:20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self._menu_w = QWidget()
        self._menu_w.setStyleSheet(f"background:{_BG};")
        self._lay = QVBoxLayout(self._menu_w)
        self._lay.setContentsMargins(0, 4, 0, 4)
        self._lay.setSpacing(0)
        scroll.setWidget(self._menu_w)
        root.addWidget(scroll, 1)

    # ── Group builders ──────────────────────────────────────────────

    def add_section(self, title: str, items: List[NavItem]):
        lbl = _SectionLabel(title)
        self._sections.append(lbl)
        self._lay.addWidget(lbl)
        for item in items:
            mi = _MenuItem(item)
            mi.clicked.connect(self._on_click)
            self._items.append(mi)
            self._lay.addWidget(mi)

    def add_collapsible(self, title: str, icon: str,
                        items: List[NavItem], collapsed: bool = False):
        hdr = _CollapseHeader(title, icon, collapsed=collapsed)
        self._cheaders.append(hdr)
        self._coll_states.append(collapsed)

        c = QWidget()
        c.setStyleSheet(f"background:{_BG};")
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        for item in items:
            mi = _MenuItem(item, indent=14)
            mi.clicked.connect(self._on_click)
            self._items.append(mi)
            cl.addWidget(mi)
        c.setVisible(not collapsed)
        self._containers.append(c)

        idx = len(self._containers) - 1
        hdr.toggled.connect(lambda col, _c=c, _i=idx: (
            self._coll_states.__setitem__(_i, col) or _c.setVisible(not col)
        ))
        self._lay.addWidget(hdr)
        self._lay.addWidget(c)

    def finish(self):
        self._lay.addStretch(1)

    # ── Selection ────────────────────────────────────────────────────

    def _on_click(self, panel):
        for mi in self._items:
            mi.set_active(mi.panel is panel)
            if mi.panel is panel:
                self._active = mi
        self.item_selected.emit(panel)

    def select_panel(self, panel):
        for mi in self._items:
            mi.set_active(mi.panel is panel)
            if mi.panel is panel:
                self._active = mi

    def select_first(self):
        if self._items:
            self._on_click(self._items[0].panel)


# ================================================================== #
#  SidebarNav  — public composite widget                             #
# ================================================================== #
class SidebarNav(QWidget):
    """
    Bootstrap-style sidebar that collapses to a thin blue accent bar.

    Expanded : full panel with logo, section headers, menu items.
    Collapsed: 22px blue bar with ▶ — click anywhere to expand.
    Collapse : click the ◀ arrow in the logo header area.
    """
    panel_changed = pyqtSignal(object)

    def __init__(self, app_name: str = "SanjINSIGHT", parent=None):
        super().__init__(parent)
        self._mini = False

        self._sidebar = _Sidebar(app_name)
        self._bar     = _CollapseBar()
        self._stack   = QStackedWidget()
        self._stack.setStyleSheet("background:#1a1a1a;")

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.VLine)
        self._sep.setStyleSheet(f"color:{_DIVIDER}; max-width:1px;")

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._lay.addWidget(self._sidebar)
        self._lay.addWidget(self._sep)
        self._lay.addWidget(self._stack, 1)

        # Collapse bar is hidden by default
        self._bar.setParent(self)
        self._bar.hide()

        self._sidebar.item_selected.connect(self._on_select)
        self._sidebar.collapse_clicked.connect(self._collapse)
        self._bar.expand_clicked.connect(self._expand)

    # ── Public API ──────────────────────────────────────────────────

    def add_section(self, title: str, items: List[NavItem]):
        for item in items:
            if self._stack.indexOf(item.panel) == -1:
                self._stack.addWidget(item.panel)
        self._sidebar.add_section(title, items)

    def add_collapsible(self, title: str, icon: str,
                        items: List[NavItem], collapsed: bool = False):
        for item in items:
            if self._stack.indexOf(item.panel) == -1:
                self._stack.addWidget(item.panel)
        self._sidebar.add_collapsible(title, icon, items, collapsed=collapsed)

    def finish(self):       self._sidebar.finish()
    def select_first(self): self._sidebar.select_first()

    def navigate_to(self, panel: QWidget):
        idx = self._stack.indexOf(panel)
        if idx >= 0:
            self._stack.setCurrentIndex(idx)
            self._sidebar.select_panel(panel)
            self.panel_changed.emit(panel)

    def select_by_label(self, label: str):
        """Navigate to the sidebar item whose label matches (case-insensitive)."""
        for item in self._sidebar._items:
            if item.label.lower() == label.lower():
                self.navigate_to(item.panel)
                return

    # ── Collapse / expand ────────────────────────────────────────────

    def _collapse(self):
        """Hide sidebar, show thin blue bar."""
        self._mini = True
        self._sidebar.hide()
        self._sep.hide()

        # Insert bar at position 0 in the layout
        self._lay.insertWidget(0, self._bar)
        self._bar.show()

    def _expand(self):
        """Restore sidebar, hide bar."""
        self._mini = False
        self._bar.hide()
        self._lay.removeWidget(self._bar)

        self._sidebar.show()
        self._sep.show()

    # ── Internal ────────────────────────────────────────────────────

    def _on_select(self, panel: QWidget):
        idx = self._stack.indexOf(panel)
        if idx >= 0:
            self._stack.setCurrentIndex(idx)
        self.panel_changed.emit(panel)
