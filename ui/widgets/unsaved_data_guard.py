"""
ui/widgets/unsaved_data_guard.py

Unsaved-data guard — prevents silent loss of ephemeral acquisition results
in Transient, Movie, and Grid Scan tabs.

Shows a confirmation dialog when the user attempts to:
  - Close the application while holding unsaved results
  - Switch away from a tab that holds unsaved results (if wired)
  - Start a new acquisition that would overwrite the current result

The dialog offers only actions that are *actually available* for the result
type.  "Save to Sessions" is NOT offered because these result types don't
support session auto-save yet (that's Phase 2).

Usage
-----
    from ui.widgets.unsaved_data_guard import check_unsaved_results

    # In MainWindow.closeEvent:
    unsaved = check_unsaved_results(transient_tab, movie_tab, scan_tab)
    if unsaved:
        action = UnsavedDataDialog.ask(unsaved, parent=self)
        if action == "cancel":
            event.ignore()
            return

Helper functions
----------------
    check_unsaved_results(*tabs)
        Returns list of (tab_name, tab_widget) for tabs with unsaved data.

    UnsavedDataDialog.ask(unsaved_tabs, parent)
        Shows dialog, returns "export" | "discard" | "cancel".
"""

from __future__ import annotations

from typing import List, Tuple, Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QWidget,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


# ── Guard check ──────────────────────────────────────────────────────

def check_unsaved_results(*tabs: Tuple[str, QWidget]) -> List[Tuple[str, QWidget]]:
    """Return list of (display_name, tab_widget) pairs that hold unsaved data.

    Parameters
    ----------
    *tabs : tuple of (str, QWidget)
        Each tuple is (human-readable name, tab widget instance).
        The widget must have a ``_result`` attribute to be checked.

    Example
    -------
        unsaved = check_unsaved_results(
            ("Time-Resolved", self._transient_tab),
            ("Burst",         self._movie_tab),
            ("Grid Scan",     self._scan_tab),
        )
    """
    unsaved = []
    for display_name, widget in tabs:
        result = getattr(widget, "_result", None)
        if result is not None:
            unsaved.append((display_name, widget))
    return unsaved


# ── Dialog ───────────────────────────────────────────────────────────

class UnsavedDataDialog(QDialog):
    """Confirmation dialog for tabs with unsaved ephemeral results.

    Offers three actions:
      - Export   — user will export manually (dialog closes, app stays open)
      - Discard  — throw away the result and proceed
      - Cancel   — abort the close/navigation and stay put

    Returns the chosen action as a string.
    """

    def __init__(self, unsaved_tabs: List[Tuple[str, QWidget]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unsaved Results")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._action = "cancel"

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 16, 20, 16)

        # ── Warning icon + headline ─────────────────────────────────
        headline = QLabel("You have unsaved acquisition results")
        headline.setStyleSheet(
            f"font-size: {FONT['header']}pt; font-weight: 700;"
            f" color: {PALETTE['text']};")
        lay.addWidget(headline)

        # ── List affected tabs ───────────────────────────────────────
        names = [name for name, _w in unsaved_tabs]
        detail_text = (
            f"The following tab{'s hold' if len(names) > 1 else ' holds'} "
            f"results that have not been exported:\n\n"
            f"  •  {'  •  '.join(names)}\n\n"
            f"These results exist only in memory. If you proceed without "
            f"exporting, they will be lost permanently."
        )
        detail = QLabel(detail_text)
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"font-size: {FONT['body']}pt; color: {PALETTE['textSub']};"
            f" line-height: 1.5;")
        lay.addWidget(detail)

        # ── Separator ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['border']};")
        lay.addWidget(sep)

        # ── Buttons ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setToolTip("Stay here — don't close or navigate away")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(lambda: self._choose("cancel"))

        discard_btn = QPushButton("Discard")
        discard_btn.setToolTip("Discard unsaved results and proceed")
        discard_btn.setFixedHeight(32)
        discard_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['danger']}; color: #ffffff;"
            f"  border: none; border-radius: 4px; padding: 4px 16px;"
            f"  font-size: {FONT['body']}pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE.get('dangerHover', PALETTE['danger'])};"
            f"}}")

        discard_btn.clicked.connect(lambda: self._choose("discard"))

        export_btn = QPushButton("Go Back and Export")
        export_btn.setToolTip("Stay here so you can export first")
        export_btn.setFixedHeight(32)
        export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['accent']}; color: #ffffff;"
            f"  border: none; border-radius: 4px; padding: 4px 16px;"
            f"  font-size: {FONT['body']}pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE.get('accentHover', PALETTE['accent'])};"
            f"}}")
        export_btn.clicked.connect(lambda: self._choose("export"))

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(discard_btn)
        btn_row.addWidget(export_btn)

        lay.addLayout(btn_row)

        # ── Dialog styling ───────────────────────────────────────────
        self.setStyleSheet(
            f"QDialog {{"
            f"  background: {PALETTE['surface']};"
            f"}}"
            f"QPushButton {{"
            f"  background: {PALETTE['surface2']}; color: {PALETTE['text']};"
            f"  border: 1px solid {PALETTE['border']}; border-radius: 4px;"
            f"  padding: 4px 16px; font-size: {FONT['body']}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['border']};"
            f"}}")

    # ── Public API ───────────────────────────────────────────────────

    @classmethod
    def ask(cls, unsaved_tabs: List[Tuple[str, QWidget]],
            parent: Optional[QWidget] = None) -> str:
        """Show dialog and return the user's choice.

        Returns
        -------
        str
            "export"  — user wants to go back and export first
            "discard" — user is OK losing the data
            "cancel"  — user wants to abort the operation
        """
        dlg = cls(unsaved_tabs, parent)
        dlg.exec_()
        return dlg._action

    # ── Internal ─────────────────────────────────────────────────────

    def _choose(self, action: str):
        self._action = action
        self.accept()
