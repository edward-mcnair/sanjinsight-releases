"""
ui/operator/recipe_selector_panel.py

RecipeSelectorPanel — approved recipe browser for the Operator Shell.

Shows only recipes where ``recipe.locked == True`` (Phase D adds the
``locked`` flag; the panel gracefully shows all recipes in the
meantime and filters to locked-only once the field exists).

Layout  (320 px fixed width)
------
  "Recipe" header
  [🔍 Search…                          ]
  ─────────────────────────────────────
  Scrollable recipe card list:
    ┌─────────────────────────────────┐
    │  ■ Recipe Label           v2    │
    │  Description (dim, capped)      │
    │  Approved by Jane Smith         │
    └─────────────────────────────────┘
  Empty state (no recipes / no search results)

Signals
-------
  recipe_selected(Recipe)   Emitted when the user clicks a recipe card.
                            Also emitted with None when selection is cleared.

Public API
----------
  refresh()                 Reload from RecipeStore.
  selected_recipe() -> Recipe | None
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5.QtCore    import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QFrame, QSizePolicy,
)

from ui.theme import FONT, PALETTE

log = logging.getLogger(__name__)

_PANEL_BG  = "#0f1120"
_CARD_BG   = "#181b2e"
_CARD_SEL  = "#1e2640"
_CARD_BDR  = "#2a3249"
_CARD_ABDR = PALETTE.get("accent", "#00d4aa")


class _RecipeCard(QFrame):
    """Single recipe card — clickable."""

    clicked = pyqtSignal(object)   # Recipe

    def __init__(self, recipe, parent=None):
        super().__init__(parent)
        self._recipe   = recipe
        self._selected = False

        self.setCursor(Qt.PointingHandCursor)
        self._refresh_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)

        # ── Title row ──────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        label_txt = recipe.label or "Untitled Recipe"
        self._title_lbl = QLabel(label_txt)
        self._title_lbl.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{PALETTE.get('text','#ebebeb')}; background:transparent;")
        title_row.addWidget(self._title_lbl, 1)

        version = getattr(recipe, "version", 1)
        ver_lbl = QLabel(f"v{version}")
        ver_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; "
            f"color:{PALETTE.get('textDim','#999')}; background:transparent;")
        ver_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(ver_lbl)
        lay.addLayout(title_row)

        # ── Description ────────────────────────────────────────────────────
        desc = recipe.description or ""
        if len(desc) > 80:
            desc = desc[:77] + "…"
        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(
                f"font-size:{FONT.get('sublabel', 9)}pt; "
                f"color:{PALETTE.get('textDim','#999')}; background:transparent;")
            desc_lbl.setWordWrap(True)
            lay.addWidget(desc_lbl)

        # ── Approval line (Phase D: recipe.locked + approved_by) ───────────
        approved_by = getattr(recipe, "approved_by", "")
        if approved_by:
            appr_lbl = QLabel(f"Approved by {approved_by}")
            appr_lbl.setStyleSheet(
                f"font-size:{FONT.get('caption', 8)}pt; "
                f"color:{PALETTE.get('accent','#00d4aa')}; background:transparent;")
            lay.addWidget(appr_lbl)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QFrame {{ background:{_CARD_SEL}; "
                f"border:1px solid {_CARD_ABDR}; border-radius:6px; }}")
        else:
            self.setStyleSheet(
                f"QFrame {{ background:{_CARD_BG}; "
                f"border:1px solid {_CARD_BDR}; border-radius:6px; }}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._recipe)
        super().mousePressEvent(event)

    @property
    def recipe(self):
        return self._recipe


class RecipeSelectorPanel(QWidget):
    """
    Approved recipe browser panel.

    Parameters
    ----------
    parent : QWidget, optional
    """

    recipe_selected = pyqtSignal(object)   # Recipe | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_cards: List[_RecipeCard] = []
        self._active_card: Optional[_RecipeCard] = None

        self.setFixedWidth(300)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{_PANEL_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 10)
        root.setSpacing(8)

        # ── Header ─────────────────────────────────────────────────────────
        hdr = QLabel("Select Recipe")
        hdr.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{PALETTE.get('text','#ebebeb')}; background:transparent;")
        root.addWidget(hdr)

        # ── Search box ─────────────────────────────────────────────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search recipes…")
        self._search.setFixedHeight(32)
        self._search.setStyleSheet(
            f"QLineEdit {{ background:#13172a; color:{PALETTE.get('text','#ebebeb')}; "
            f"border:1px solid {_CARD_BDR}; border-radius:4px; "
            f"padding:4px 8px; font-size:{FONT.get('body', 11)}pt; }}"
            f"QLineEdit:focus {{ border-color:{PALETTE.get('accent','#00d4aa')}; }}")
        root.addWidget(self._search)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_CARD_BDR};")
        root.addWidget(sep)

        # ── Scroll area ────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
            f"QScrollBar:vertical {{ background:{_PANEL_BG}; width:6px; border:none; }}"
            "QScrollBar::handle:vertical { background:#333; border-radius:3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background:transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 4, 0)
        self._list_lay.setSpacing(6)
        self._list_lay.addStretch(1)

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, 1)

        # ── Empty-state label ──────────────────────────────────────────────
        self._empty_lbl = QLabel(
            "No approved recipes.\n\n"
            "Ask your engineer to approve a recipe\n"
            "from the Library tab.")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            f"color:{PALETTE.get('textSub','#6a6a6a')}; "
            "background:transparent; padding:20px;")
        self._empty_lbl.setVisible(False)
        root.addWidget(self._empty_lbl)

        # ── Wire signals ───────────────────────────────────────────────────
        self._search.textChanged.connect(self._filter)

        # Load recipes after event loop starts
        QTimer.singleShot(0, self.refresh)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload approved recipes from RecipeStore."""
        try:
            from acquisition.recipe_tab import RecipeStore
            store   = RecipeStore()
            recipes = store.list()
        except Exception as exc:
            log.warning("RecipeSelectorPanel.refresh: %s", exc)
            recipes = []

        # Filter: show only locked recipes (gracefully handles missing field)
        approved = [r for r in recipes if getattr(r, "locked", False)]

        # Clear existing cards
        for card in self._all_cards:
            self._list_lay.removeWidget(card)
            card.deleteLater()
        self._all_cards.clear()
        self._active_card = None

        for recipe in approved:
            card = _RecipeCard(recipe)
            card.clicked.connect(self._on_card_clicked)
            self._all_cards.append(card)
            # Insert before the stretch at end
            self._list_lay.insertWidget(
                self._list_lay.count() - 1, card)

        self._filter(self._search.text())

    def selected_recipe(self):
        """Return the currently selected Recipe, or None."""
        return self._active_card.recipe if self._active_card else None

    # ── Private helpers ────────────────────────────────────────────────────────

    def _on_card_clicked(self, recipe) -> None:
        # Deselect previous
        if self._active_card is not None:
            self._active_card.set_selected(False)

        # Find the card that was clicked
        for card in self._all_cards:
            if card.recipe is recipe:
                card.set_selected(True)
                self._active_card = card
                break

        self.recipe_selected.emit(recipe)

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        visible_count = 0
        for card in self._all_cards:
            recipe = card.recipe
            match = (
                query == ""
                or query in (recipe.label or "").lower()
                or query in (recipe.description or "").lower()
            )
            card.setVisible(match)
            if match:
                visible_count += 1

        # Show empty state only when no results
        has_any_approved = len(self._all_cards) > 0
        self._empty_lbl.setVisible(
            visible_count == 0 and not has_any_approved
            if query == "" else visible_count == 0
        )

        # Show "no search results" vs "no approved recipes"
        if visible_count == 0:
            if not has_any_approved:
                self._empty_lbl.setText(
                    "No approved recipes.\n\n"
                    "Ask your engineer to approve a recipe\n"
                    "from the Library tab.")
            elif query:
                self._empty_lbl.setText(
                    f"No recipes matching\n\"{text.strip()}\"")
            self._empty_lbl.setVisible(True)
        else:
            self._empty_lbl.setVisible(False)
