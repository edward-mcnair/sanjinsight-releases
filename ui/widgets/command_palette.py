"""
ui/widgets/command_palette.py

CommandPalette — floating search overlay for quick navigation.

Open with Ctrl+K. Type to filter tabs and actions. Arrow keys to navigate.
Enter or click to activate. Escape to close.

Usage
-----
    from ui.widgets.command_palette import CommandPalette

    # In MainWindow.__init__ (after all tabs are created):
    self._cmd_palette = CommandPalette(self)
    self._cmd_palette.set_items(self._build_palette_items())
    QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._cmd_palette.show_palette)

    # Build the items list:
    def _build_palette_items(self):
        return [
            PaletteItem("Acquire", "Acquisition", lambda: self._nav.navigate_to(self._acquire_tab)),
            PaletteItem("Analysis", "Analysis", lambda: self._nav.navigate_to(self._analysis_tab)),
            # ... etc
        ]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PyQt5.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
    QHBoxLayout, QLabel, QWidget, QFrame,
)
from PyQt5.QtCore import Qt, QPoint, QSize, pyqtSignal
from PyQt5.QtGui import QKeyEvent, QColor, QFont

from ui.theme import FONT, PALETTE
from ui.font_utils import sans_font


@dataclass
class PaletteItem:
    """A single entry in the command palette."""
    label: str          # primary display text (e.g. "Analysis")
    group: str          # section/group (e.g. "Navigation", "Hardware")
    action: Callable    # called when selected
    keywords: List[str] = field(default_factory=list)  # extra search terms
    icon: str = "→"


class CommandPalette(QDialog):
    """
    Floating search-and-launch overlay, styled like VS Code or Spotlight.

    Shows a search box and filtered list of all sidebar items + common
    actions. Arrow keys navigate; Enter activates; Escape closes.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(False)
        self._items: List[PaletteItem] = []

        # ── Outer wrapper (transparent for click-outside to close) ───────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Card ─────────────────────────────────────────────────────────
        card = QWidget()
        card.setObjectName("cmdCard")
        card.setStyleSheet("""
            QWidget#cmdCard {
                background: #0f0f16;
                border: 1px solid #2a2a3a;
                border-radius: 10px;
            }
        """)
        card.setFixedWidth(560)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 12, 12, 12)
        card_lay.setSpacing(8)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search tabs and actions…")
        self._search.setFixedHeight(40)
        self._search.setStyleSheet("""
            QLineEdit {
                background: #1a1a28;
                border: 1px solid #333;
                border-radius: 6px;
                color: #eee;
                font-size: 14pt;
                padding: 4px 12px;
            }
            QLineEdit:focus { border-color: #00d4aa; }
        """)
        self._search.textChanged.connect(self._filter)
        self._search.returnPressed.connect(self._activate_current)

        # Results list
        self._list = QListWidget()
        self._list.setFixedHeight(320)
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                color: #ccc;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12pt;
            }
            QListWidget::item:hover { background: #1e2a40; }
            QListWidget::item:selected { background: #0d3028; color: #00d4aa; }
        """)
        self._list.itemActivated.connect(self._on_item_activated)

        # Footer hint
        hint = QLabel("↑↓ navigate  ·  ↵ select  ·  Esc close")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size: 9pt; color: #333;")

        card_lay.addWidget(self._search)
        card_lay.addWidget(self._list)
        card_lay.addWidget(hint)

        outer.addWidget(card, 0, Qt.AlignTop | Qt.AlignHCenter)
        self.setMinimumHeight(420)

    # ── Public API ───────────────────────────────────────────────────

    def set_items(self, items: List[PaletteItem]) -> None:
        """Set the full list of palette items (call after all tabs are created)."""
        self._items = items
        self._populate(items)

    def show_palette(self) -> None:
        """Show the palette centered above the parent window."""
        self._search.clear()
        self._populate(self._items)
        if self.parent():
            pw = self.parent()
            cx = pw.geometry().center().x()
            cy = pw.geometry().top() + 80
            self.move(cx - self.width() // 2, cy)
        self.show()
        self.activateWindow()
        self._search.setFocus()

    # ── Filtering & selection ────────────────────────────────────────

    def _populate(self, items: List[PaletteItem]) -> None:
        self._list.clear()
        cur_group = None
        for item in items:
            if item.group != cur_group:
                cur_group = item.group
                sep = QListWidgetItem(f"  {cur_group.upper()}")
                sep.setFlags(Qt.NoItemFlags)
                sep.setForeground(QColor("#555"))
                f = sans_font(FONT["caption"])
                f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
                sep.setFont(f)
                sep.setData(Qt.UserRole, None)
                self._list.addItem(sep)
            li = QListWidgetItem(f"  {item.icon}  {item.label}")
            li.setData(Qt.UserRole, item)
            li.setFont(sans_font(FONT["body"]))
            self._list.addItem(li)
        if self._list.count() > 0:
            # select first selectable item
            for i in range(self._list.count()):
                li = self._list.item(i)
                if li.flags() != Qt.NoItemFlags:
                    self._list.setCurrentRow(i)
                    break

    def _filter(self, text: str) -> None:
        text = text.lower().strip()
        if not text:
            self._populate(self._items)
            return
        filtered = [
            it for it in self._items
            if text in it.label.lower()
            or text in it.group.lower()
            or any(text in kw.lower() for kw in it.keywords)
        ]
        self._populate(filtered)

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item:
            pi: Optional[PaletteItem] = item.data(Qt.UserRole)
            if pi and pi.action:
                self.close()
                pi.action()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        pi: Optional[PaletteItem] = item.data(Qt.UserRole)
        if pi and pi.action:
            self.close()
            pi.action()

    # ── Event handling ───────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        elif key == Qt.Key_Down:
            self._move_selection(1)
        elif key == Qt.Key_Up:
            self._move_selection(-1)
        else:
            super().keyPressEvent(event)

    def _move_selection(self, delta: int) -> None:
        cur = self._list.currentRow()
        n = self._list.count()
        new = cur + delta
        while 0 <= new < n:
            if self._list.item(new).flags() != Qt.NoItemFlags:
                self._list.setCurrentRow(new)
                return
            new += delta

    def mousePressEvent(self, event) -> None:
        """Clicking outside the card closes the palette."""
        card = self.findChild(QWidget, "cmdCard")
        if card and not card.geometry().contains(event.pos()):
            self.close()
        super().mousePressEvent(event)
