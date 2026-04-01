"""
ui/widgets/tag_input.py

TagInputWidget — a chip-bar tag input with autocomplete.

Appearance
----------
    ┌─────────────────────────────────────────────────────────┐
    │  thermal-soak ×   pre-etch ×   lot-42 ×   [add tag…]   │
    └─────────────────────────────────────────────────────────┘

Behaviour
---------
• Existing tags are shown as coloured pills.  Click the × on any pill to
  remove it.
• The text field at the right accepts free typing.  As the user types, a
  floating suggestion list appears showing previously-used tags that match.
• Pressing Enter, Tab, or comma commits the typed text as a new tag.
• The # prefix is accepted in input and stripped on commit.
• Pressing Backspace in an empty field removes the last chip.
• Arrow keys navigate the suggestion list without leaving the text field.
• Clicking a suggestion row picks that tag and hides the popup.
• Clicking outside the popup hides it (Qt.Popup behaviour).

Signals
-------
tags_changed(list[str])   Emitted whenever the tag list changes.

Public API
----------
tags() → list[str]          Current tag list (copies).
set_tags(list[str])         Replace all tags; does not emit tags_changed.
clear_tags()                Remove all tags; does not emit tags_changed.
_apply_styles()             Called by MainWindow on theme switch.
"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore  import Qt, pyqtSignal, QPoint, QTimer
from PyQt5.QtGui   import QKeyEvent
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QSizePolicy,
    QScrollArea, QApplication)

from acquisition.metadata import normalise_tag, get_registry
from ui.theme import PALETTE, FONT


# ── Suggestion popup ───────────────────────────────────────────────────────

class _SuggestionPopup(QListWidget):
    """Floating autocomplete list anchored below the tag input field.

    Created once per TagInputWidget and reused.  Shown / hidden as needed.
    Uses Qt.Popup window flag so it closes automatically on outside click.
    """

    tag_chosen = pyqtSignal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(None)           # top-level so it can float over siblings
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedWidth(220)
        self.setMaximumHeight(200)
        self.itemClicked.connect(lambda item: self.tag_chosen.emit(item.text()))
        self._apply_styles()

    def show_below(self, anchor: QWidget, suggestions: List[str],
                   current_text: str = "") -> None:
        """Populate and position the popup below *anchor*."""
        self.clear()
        for tag in suggestions:
            self.addItem(tag)
        # "Create new" entry when typed text is not an exact existing tag
        norm = normalise_tag(current_text)
        if norm and norm not in suggestions:
            item = QListWidgetItem(f'+ Create  "{norm}"')
            item.setData(Qt.UserRole, norm)   # carry the tag, not display text
            self.addItem(item)

        if self.count() == 0:
            self.hide()
            return

        # Position below the anchor widget
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        self.move(pos)
        self.show()
        self.setCurrentRow(-1)

    def _apply_styles(self) -> None:
        bg   = PALETTE['surface']
        txt  = PALETTE['text']
        sel  = PALETTE['accent']
        bdr  = PALETTE['border']
        self.setStyleSheet(
            f"QListWidget {{"
            f"  background:{bg}; color:{txt};"
            f"  border:1px solid {bdr}; border-radius:4px;"
            f"  font-size:{FONT.get('body', 11)}pt;"
            f"  outline:none;"
            f"}}"
            f"QListWidget::item {{ padding:5px 10px; }}"
            f"QListWidget::item:selected {{"
            f"  background:{sel}33; color:{txt};"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background:{sel}22;"
            f"}}"
        )

    def navigate(self, delta: int) -> None:
        """Move selection by *delta* rows (+1 down, -1 up)."""
        n = self.count()
        if n == 0:
            return
        cur = self.currentRow()
        self.setCurrentRow(max(0, min(n - 1, cur + delta)))

    def accept_selected(self) -> bool:
        """Emit tag_chosen for the currently selected row.  Returns True if done."""
        item = self.currentItem()
        if item is None:
            return False
        # Use UserRole data if set (for the "+ Create…" row), else display text
        tag = item.data(Qt.UserRole) or item.text()
        self.tag_chosen.emit(normalise_tag(tag))
        return True


# ── Tag chip ───────────────────────────────────────────────────────────────

class _TagChip(QFrame):
    """Single tag pill with a remove (×) button on the right."""

    remove_requested = pyqtSignal(str)    # emits the tag string

    def __init__(self, tag: str, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._tag = tag
        self.setObjectName("tag_chip")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 4, 2)
        lay.setSpacing(4)

        lbl = QLabel(tag)
        lbl.setObjectName("tag_chip_label")
        lay.addWidget(lbl)

        remove = QPushButton("×")
        remove.setObjectName("tag_chip_remove")
        remove.setFixedSize(16, 16)
        remove.setFlat(True)
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(lambda: self.remove_requested.emit(self._tag))
        lay.addWidget(remove)

    @property
    def tag(self) -> str:
        return self._tag


# ── Main widget ────────────────────────────────────────────────────────────

class TagInputWidget(QWidget):
    """Chip-bar tag input with autocomplete from the global TagRegistry.

    Embeds directly wherever a tag field is needed — metadata strip,
    session card, pre-scan config panel, etc.
    """

    tags_changed = pyqtSignal(list)   # list[str]

    def __init__(self, placeholder: str = "add tag…", parent: QWidget = None) -> None:
        super().__init__(parent)
        self._tags:    List[str]  = []
        self._placeholder         = placeholder

        self._popup   = _SuggestionPopup(self)
        self._popup.tag_chosen.connect(self._on_suggestion_chosen)

        self._build_ui()
        self._apply_styles()

    # ── Build ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The visible frame that looks like an input field
        self._frame = QFrame()
        self._frame.setObjectName("tag_input_frame")
        outer.addWidget(self._frame)

        self._frame_lay = QHBoxLayout(self._frame)
        self._frame_lay.setContentsMargins(6, 3, 6, 3)
        self._frame_lay.setSpacing(4)

        # Chip container (scrollable horizontally when many tags)
        self._chip_area = QWidget()
        self._chip_lay  = QHBoxLayout(self._chip_area)
        self._chip_lay.setContentsMargins(0, 0, 0, 0)
        self._chip_lay.setSpacing(4)
        self._chip_lay.addStretch()
        self._frame_lay.addWidget(self._chip_area, 1)

        # Text input
        self._input = QLineEdit()
        self._input.setObjectName("tag_input_field")
        self._input.setPlaceholderText(self._placeholder)
        self._input.setMinimumWidth(90)
        self._input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)
        self._frame_lay.addWidget(self._input)

        # Debounce timer for suggestion lookup
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(150)
        self._suggest_timer.timeout.connect(self._refresh_suggestions)

    # ── Public API ─────────────────────────────────────────────────────

    def tags(self) -> List[str]:
        """Return a copy of the current tag list."""
        return list(self._tags)

    def set_tags(self, tags: List[str]) -> None:
        """Replace all tags.  Does NOT emit tags_changed."""
        self._tags = [normalise_tag(t) for t in tags if normalise_tag(t)]
        self._rebuild_chips()

    def clear_tags(self) -> None:
        """Remove all tags.  Does NOT emit tags_changed."""
        self._tags = []
        self._rebuild_chips()

    def focus_input(self) -> None:
        """Move keyboard focus to the text input."""
        self._input.setFocus()

    # ── Chip management ────────────────────────────────────────────────

    def _rebuild_chips(self) -> None:
        """Tear down and recreate all chip widgets from self._tags."""
        # Remove all existing chips (everything except the stretch at end)
        while self._chip_lay.count() > 1:
            item = self._chip_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for tag in self._tags:
            chip = _TagChip(tag)
            chip.remove_requested.connect(self._on_remove_tag)
            self._chip_lay.insertWidget(self._chip_lay.count() - 1, chip)

    def _add_tag(self, tag: str) -> None:
        tag = normalise_tag(tag)
        if not tag or tag in self._tags:
            return
        self._tags.append(tag)
        self._rebuild_chips()
        self._input.clear()
        self._popup.hide()
        self.tags_changed.emit(list(self._tags))
        get_registry().record([tag])

    def _on_remove_tag(self, tag: str) -> None:
        if tag in self._tags:
            self._tags.remove(tag)
            self._rebuild_chips()
            self.tags_changed.emit(list(self._tags))

    def _commit_input(self) -> None:
        """Commit whatever is in the text field as a new tag."""
        text = self._input.text().strip()
        if text:
            self._add_tag(text)

    # ── Suggestion popup ───────────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        self._suggest_timer.start()

    def _refresh_suggestions(self) -> None:
        text = self._input.text().strip()
        suggestions = get_registry().suggest(prefix=text, limit=8)
        # Filter out tags already applied
        suggestions = [s for s in suggestions if s not in self._tags]
        if not suggestions and not text:
            self._popup.hide()
            return
        self._popup.show_below(self._input, suggestions, current_text=text)

    def _on_suggestion_chosen(self, tag: str) -> None:
        self._add_tag(tag)
        self._input.setFocus()

    # ── Event filter (keyboard handling in input) ──────────────────────

    def eventFilter(self, obj: QWidget, event) -> bool:
        if obj is not self._input:
            return super().eventFilter(obj, event)
        if not isinstance(event, QKeyEvent):
            return False

        key = event.key()

        # Navigate popup with Up/Down without stealing focus
        if key == Qt.Key_Down and self._popup.isVisible():
            self._popup.navigate(+1)
            return True
        if key == Qt.Key_Up and self._popup.isVisible():
            self._popup.navigate(-1)
            return True

        # Enter / Return: pick selected suggestion OR commit typed text
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._popup.isVisible() and self._popup.accept_selected():
                return True
            self._commit_input()
            return True

        # Tab / comma: commit typed text
        if key in (Qt.Key_Tab, Qt.Key_Comma):
            self._commit_input()
            return True

        # Escape: hide popup
        if key == Qt.Key_Escape:
            self._popup.hide()
            return True

        # Backspace on empty field: remove last tag
        if key == Qt.Key_Backspace and not self._input.text():
            if self._tags:
                self._on_remove_tag(self._tags[-1])
            return True

        return False

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        bg   = PALETTE['surface']
        txt  = PALETTE['text']
        dim  = PALETTE['textDim']
        bdr  = PALETTE['border']
        acc  = PALETTE['accent']

        self._frame.setStyleSheet(
            f"QFrame#tag_input_frame {{"
            f"  background:{bg}; border:1px solid {bdr}; border-radius:5px;"
            f"}}"
            f"QFrame#tag_input_frame:focus-within {{"
            f"  border-color:{acc};"
            f"}}"
        )
        self._input.setStyleSheet(
            f"QLineEdit#tag_input_field {{"
            f"  background:transparent; border:none; color:{txt};"
            f"  font-size:{FONT.get('body', 11)}pt;"
            f"  padding:0;"
            f"}}"
            f"QLineEdit#tag_input_field::placeholder {{ color:{dim}; }}"
        )

        # Chip style — teal-tinted pill
        chip_style = (
            f"QFrame#tag_chip {{"
            f"  background:{acc}1a; border:1px solid {acc}55; border-radius:3px;"
            f"}}"
            f"QLabel#tag_chip_label {{"
            f"  color:{acc}; font-size:{FONT.get('sublabel', 9)}pt;"
            f"  background:transparent; border:none;"
            f"}}"
            f"QPushButton#tag_chip_remove {{"
            f"  color:{dim}; background:transparent; border:none;"
            f"  font-size:{FONT.get('body', 11)}pt; padding:0;"
            f"}}"
            f"QPushButton#tag_chip_remove:hover {{ color:{txt}; }}"
        )
        for i in range(self._chip_lay.count()):
            item = self._chip_lay.itemAt(i)
            if item and isinstance(item.widget(), _TagChip):
                item.widget().setStyleSheet(chip_style)

        self._popup._apply_styles()
