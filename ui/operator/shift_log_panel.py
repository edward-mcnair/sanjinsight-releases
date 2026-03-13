"""
ui/operator/shift_log_panel.py

ShiftLogPanel — scrollable today's-results sidebar in the Operator Shell.

Shows a card per scan (PASS / FAIL / REVIEW badge, part ID, time, recipe
label) plus running totals.  Supports CSV export.

Public API
----------
  append_result(verdict, part_id, recipe_label, timestamp)
      Add one result card to the top of the list.

  clear()
      Remove all cards (called at start of a new shift).

  entry_count() -> int
  pass_count()  -> int

Signals
-------
  (none — display-only panel)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from typing import List

from PyQt5.QtCore    import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QSizePolicy,
)

from ui.theme import FONT, PALETTE

log = logging.getLogger(__name__)

# ── Verdict badge colours ─────────────────────────────────────────────────────

_BADGE = {
    "PASS":    {"text": "PASS",   "fg": "#00d4aa", "bg": "#0a2e28"},
    "FAIL":    {"text": "FAIL",   "fg": "#ff4466", "bg": "#2a0810"},
    "WARNING": {"text": "REVIEW", "fg": "#ffaa44", "bg": "#2e1e08"},
}
_BADGE_DEFAULT = {"text": "?", "fg": "#888888", "bg": "#1a1a1a"}

_PANEL_BG  = "#0f1120"
_CARD_BG   = "#181b2e"
_CARD_BDR  = "#2a3249"


class _ResultCard(QFrame):
    """A single scan result card."""

    def __init__(self, verdict: str, part_id: str,
                 recipe_label: str, timestamp: float, parent=None):
        super().__init__(parent)
        self._verdict     = verdict
        self._part_id     = part_id
        self._recipe_label = recipe_label
        self._timestamp   = timestamp

        self.setStyleSheet(
            f"QFrame {{ background:{_CARD_BG}; border:1px solid {_CARD_BDR}; "
            "border-radius:6px; }}")
        self.setFixedHeight(68)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        # ── Badge ──────────────────────────────────────────────────────────
        cfg = _BADGE.get(verdict, _BADGE_DEFAULT)
        badge = QLabel(cfg["text"])
        badge.setFixedWidth(52)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background:{cfg['bg']}; color:{cfg['fg']}; "
            f"border:1px solid {cfg['fg']}; border-radius:4px; "
            f"font-size:{FONT.get('caption', 8)}pt; font-weight:800; "
            "letter-spacing:1px; padding:2px 0;")
        lay.addWidget(badge)

        # ── Text block ─────────────────────────────────────────────────────
        txt = QVBoxLayout()
        txt.setSpacing(1)

        part_lbl = QLabel(part_id or "—")
        part_lbl.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{PALETTE.get('text','#ebebeb')}; background:transparent;")
        txt.addWidget(part_lbl)

        meta_lbl = QLabel(
            f"{recipe_label}  ·  "
            f"{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}")
        meta_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; "
            f"color:{PALETTE.get('textDim','#999')}; background:transparent;")
        txt.addWidget(meta_lbl)
        lay.addLayout(txt, 1)

    # ── CSV row ────────────────────────────────────────────────────────────────

    def to_csv_row(self) -> list:
        ts = datetime.fromtimestamp(self._timestamp).isoformat()
        return [ts, self._verdict, self._part_id, self._recipe_label]


class ShiftLogPanel(QWidget):
    """
    Scrollable shift log sidebar.

    Parameters
    ----------
    parent : QWidget, optional
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: List[_ResultCard] = []

        self.setMinimumWidth(200)
        self.setMaximumWidth(300)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{_PANEL_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 10)
        root.setSpacing(8)

        # ── Header ─────────────────────────────────────────────────────────
        hdr = QLabel("Shift Log")
        hdr.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{PALETTE.get('text','#ebebeb')}; background:transparent;")
        root.addWidget(hdr)

        # ── Running totals ─────────────────────────────────────────────────
        self._totals_lbl = QLabel("0 scans")
        self._totals_lbl.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            f"color:{PALETTE.get('textDim','#999')}; background:transparent;")
        root.addWidget(self._totals_lbl)

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

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet("background:transparent;")
        self._cards_lay = QVBoxLayout(self._cards_widget)
        self._cards_lay.setContentsMargins(0, 0, 0, 0)
        self._cards_lay.setSpacing(6)
        self._cards_lay.addStretch(1)

        scroll.setWidget(self._cards_widget)
        root.addWidget(scroll, 1)

        # ── Export button ──────────────────────────────────────────────────
        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(30)
        self._export_btn.setStyleSheet(
            f"QPushButton {{ background:{PALETTE.get('surface2','#333')}; "
            f"color:{PALETTE.get('textDim','#999')}; "
            f"border:1px solid {PALETTE.get('border','#484')}; border-radius:4px; "
            f"font-size:{FONT.get('sublabel', 9)}pt; }}"
            f"QPushButton:hover {{ background:{PALETTE.get('surfaceHover','#404')}; "
            f"color:{PALETTE.get('text','#ebebeb')}; }}"
            "QPushButton:disabled { color:#444; border-color:#333; }")
        self._export_btn.setEnabled(False)
        root.addWidget(self._export_btn)

        self._export_btn.clicked.connect(self._export_csv)

    # ── Public API ─────────────────────────────────────────────────────────────

    def append_result(
        self,
        verdict:      str,
        part_id:      str,
        recipe_label: str,
        timestamp:    float,
    ) -> None:
        """Prepend a new result card to the log."""
        card = _ResultCard(verdict, part_id, recipe_label, timestamp)
        self._cards.insert(0, card)
        # Insert at top (before stretch at end)
        self._cards_lay.insertWidget(0, card)
        self._update_totals()
        self._export_btn.setEnabled(True)

    def clear(self) -> None:
        """Remove all result cards."""
        for card in self._cards:
            self._cards_lay.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._update_totals()
        self._export_btn.setEnabled(False)

    def entry_count(self) -> int:
        return len(self._cards)

    def pass_count(self) -> int:
        return sum(1 for c in self._cards if c._verdict == "PASS")

    # ── Private helpers ────────────────────────────────────────────────────────

    def _update_totals(self) -> None:
        n = len(self._cards)
        if n == 0:
            self._totals_lbl.setText("0 scans")
            return
        p = self.pass_count()
        pct = int(100 * p / n)
        self._totals_lbl.setText(f"{n} scan{'s' if n != 1 else ''}  ·  {pct}% pass")

    def _export_csv(self) -> None:
        if not self._cards:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Shift Log",
            f"shift_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Timestamp", "Verdict", "Part ID", "Recipe"])
                for card in self._cards:
                    writer.writerow(card.to_csv_row())
            log.info("ShiftLogPanel: exported %d rows to %s", len(self._cards), path)
        except OSError as exc:
            log.error("ShiftLogPanel: CSV export failed: %s", exc)

    def _apply_styles(self) -> None:
        """Re-apply theme when app theme changes."""
        pass   # panel uses fixed dark palette matching OperatorShell
