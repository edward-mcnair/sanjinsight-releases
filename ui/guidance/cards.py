"""
ui/guidance/cards.py  —  Dismissable guidance cards and workflow footer

Tier 1 widgets for contextual help.  Each card has a unique ``card_id``
used to persist its dismissed state via ``ui.guidance.prefs``.

Architecture notes (Tier 2/3 forward-compatibility):
  - ``target_widget`` optional reference for spotlight overlay (Tier 2)
  - ``step_id``       unique identifier usable as an AI conversation anchor (Tier 3)
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT
from ui.guidance.prefs import is_dismissed, dismiss

log = logging.getLogger(__name__)


class GuidanceCard(QFrame):
    """Dismissable contextual help card with optional numbered step badge.

    Signals
    -------
    dismissed(str)
        Emitted with ``card_id`` when user clicks "Got it".
    """

    dismissed = pyqtSignal(str)

    def __init__(
        self,
        card_id: str,
        title: str,
        body: str,
        *,
        step_number: int | None = None,
        target_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.card_id = card_id
        self.step_id = card_id          # Tier 3 AI anchor alias
        self.target_widget = target_widget  # Tier 2 overlay target
        self._step_number = step_number

        self.setObjectName("GuidanceCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._apply_frame_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # ── Header row: badge + title + dismiss button ──────────────
        header = QHBoxLayout()
        header.setSpacing(8)
        layout.addLayout(header)

        if step_number is not None:
            self._badge = QLabel(str(step_number))
            self._badge.setFixedSize(26, 26)
            self._badge.setAlignment(Qt.AlignCenter)
            self._apply_badge_style()
            header.addWidget(self._badge)
        else:
            self._badge = None

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(self._title_qss())
        header.addWidget(self._title_lbl, 1)

        self._dismiss_btn = QPushButton("Got it")
        self._dismiss_btn.setFixedHeight(24)
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(self._dismiss_qss())
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        header.addWidget(self._dismiss_btn)

        # ── Body text ───────────────────────────────────────────────
        self._body_lbl = QLabel(body)
        self._body_lbl.setWordWrap(True)
        self._body_lbl.setStyleSheet(self._body_qss())
        layout.addWidget(self._body_lbl)

        # ── Slot for child widgets (combos, pickers injected by host)
        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(0, 4, 0, 0)
        self._content_layout.setSpacing(8)
        layout.addLayout(self._content_layout)

        # Auto-hide if previously dismissed
        if is_dismissed(card_id):
            self.setVisible(False)

    # ── Public API ──────────────────────────────────────────────────

    def add_content(self, widget: QWidget) -> None:
        """Add a widget below the body text (e.g. a combo or picker)."""
        self._content_layout.addWidget(widget)

    def set_body(self, text: str) -> None:
        """Update the body text dynamically."""
        self._body_lbl.setText(text)

    def restore(self) -> None:
        """Force-show a previously dismissed card (e.g. Reset Tips)."""
        from ui.guidance.prefs import _dismissed_cache, _PREF_PREFIX
        import config as cfg_mod
        _dismissed_cache.discard(self.card_id)
        cfg_mod.set_pref(f"{_PREF_PREFIX}{self.card_id}", False)
        self.setVisible(True)

    # ── Styling ─────────────────────────────────────────────────────

    def _apply_frame_style(self) -> None:
        accent = PALETTE['accent']
        self.setStyleSheet(
            f"QFrame#GuidanceCard {{"
            f"  background: {accent}0F;"
            f"  border: 1px solid {accent}33;"
            f"  border-radius: 8px;"
            f"}}")

    def _apply_badge_style(self) -> None:
        if self._badge is None:
            return
        accent = PALETTE['accent']
        self._badge.setStyleSheet(
            f"QLabel {{"
            f"  background: {accent}20;"
            f"  border: 2px solid {accent};"
            f"  border-radius: 13px;"
            f"  color: {accent};"
            f"  font-weight: 700;"
            f"  font-size: {FONT.get('label', 11)}pt;"
            f"}}")

    @staticmethod
    def _title_qss() -> str:
        return (
            f"font-weight: 600;"
            f"color: {PALETTE['accent']};"
            f"font-size: {FONT.get('body', 12)}pt;")

    @staticmethod
    def _body_qss() -> str:
        return (
            f"color: {PALETTE['text']};"
            f"font-size: {FONT.get('caption', 11)}pt;"
            f"line-height: 1.5;")

    @staticmethod
    def _dismiss_qss() -> str:
        accent = PALETTE['accent']
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid {accent}44;"
            f"  border-radius: 4px;"
            f"  color: {PALETTE['textDim']};"
            f"  padding: 2px 10px;"
            f"  font-size: {FONT.get('caption', 11)}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {PALETTE['text']};"
            f"  border-color: {accent}88;"
            f"}}")

    def _apply_styles(self) -> None:
        """Refresh all styles for theme change."""
        self._apply_frame_style()
        if self._badge is not None:
            self._apply_badge_style()
        self._title_lbl.setStyleSheet(self._title_qss())
        self._body_lbl.setStyleSheet(self._body_qss())
        self._dismiss_btn.setStyleSheet(self._dismiss_qss())

    # ── Dismiss handling ────────────────────────────────────────────

    def _on_dismiss(self) -> None:
        dismiss(self.card_id)
        self.setVisible(False)
        self.dismissed.emit(self.card_id)
        log.debug("Guidance card dismissed: %s", self.card_id)


class WorkflowFooter(QFrame):
    """'What happens next?' preview of upcoming workflow steps.

    Shows 2-3 upcoming steps with brief descriptions.
    Only visible in Guided mode.
    """

    navigate_requested = pyqtSignal(str)  # nav label

    def __init__(
        self,
        steps: list[tuple[str, str, str]],  # [(nav_label, title, description), ...]
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowFooter")
        self._steps = steps
        self._step_labels: list[tuple[QLabel, QLabel]] = []

        self._apply_frame_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header = QLabel("What happens next?")
        header.setStyleSheet(
            f"color: {PALETTE['textDim']};"
            f"font-size: {FONT.get('caption', 11)}pt;"
            f"font-weight: 600;")
        layout.addWidget(header)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(20)
        layout.addLayout(steps_row)

        for i, (nav, title, desc) in enumerate(steps):
            col = QVBoxLayout()
            col.setSpacing(2)

            t = QLabel(f"→ {title}")
            t.setStyleSheet(
                f"color: {PALETTE['accent' if i == 0 else 'textDim']};"
                f"font-weight: {'600' if i == 0 else '400'};"
                f"font-size: {FONT.get('caption', 11)}pt;")
            t.setCursor(Qt.PointingHandCursor)
            t.mousePressEvent = lambda e, n=nav: self.navigate_requested.emit(n)
            col.addWidget(t)

            d = QLabel(desc)
            d.setStyleSheet(
                f"color: {PALETTE['textDim']};"
                f"font-size: {FONT.get('caption', 11) - 1}pt;")
            d.setWordWrap(True)
            col.addWidget(d)

            self._step_labels.append((t, d))
            steps_row.addLayout(col, 1)

    def _apply_frame_style(self) -> None:
        self.setStyleSheet(
            f"QFrame#WorkflowFooter {{"
            f"  background: {PALETTE['surface']};"
            f"  border: 1px solid {PALETTE['border']};"
            f"  border-radius: 8px;"
            f"}}")

    def _apply_styles(self) -> None:
        self._apply_frame_style()
        for i, (t, d) in enumerate(self._step_labels):
            t.setStyleSheet(
                f"color: {PALETTE['accent' if i == 0 else 'textDim']};"
                f"font-weight: {'600' if i == 0 else '400'};"
                f"font-size: {FONT.get('caption', 11)}pt;")
            d.setStyleSheet(
                f"color: {PALETTE['textDim']};"
                f"font-size: {FONT.get('caption', 11) - 1}pt;")
