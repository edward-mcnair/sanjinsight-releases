"""
ui/widgets/readiness_panel.py  —  PendingAction readiness list

Displays the live, shrinking checklist of items that need user
attention before a recipe can run.  Each item shows its severity,
title, description, and a clickable link to the exact sidebar
section where it can be resolved.

The panel is a pure display widget — it does not evaluate readiness
itself.  Call ``update_actions(actions)`` to refresh the list from
the readiness evaluator's output.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ui.theme import FONT, PALETTE

log = logging.getLogger(__name__)


# Severity → display config
_SEVERITY_CONFIG = {
    "blocking": {"icon": "\u26d4", "color_key": "danger",  "label": "Required"},
    "review":   {"icon": "\u26a0", "color_key": "warning", "label": "Review"},
    "info":     {"icon": "\u2139", "color_key": "accent",  "label": "Info"},
}


class ReadinessPanel(QWidget):
    """Displays PendingAction items as a vertical checklist.

    Signals
    -------
    navigate_requested(nav_target, tab_hint)
        Emitted when the user clicks a "Go" link on an action.
    action_dismissed(action_id)
        Emitted when the user dismisses an informational item.
    """

    navigate_requested = pyqtSignal(str, str)   # nav_target, tab_hint
    action_dismissed   = pyqtSignal(str)         # action_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = QLabel("Readiness Checklist")
        self._header.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt; "
            f"font-weight:600; padding:6px 8px;")
        root.addWidget(self._header)

        # Status summary
        self._summary = QLabel()
        self._summary.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt; "
            f"padding:0 8px 4px 8px;")
        root.addWidget(self._summary)

        # Scrollable action list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(4, 0, 4, 4)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, 1)

        # Ready banner (shown when all clear)
        self._ready_banner = QLabel("\u2705  Ready to run")
        self._ready_banner.setAlignment(Qt.AlignCenter)
        self._ready_banner.setStyleSheet(
            f"color:{PALETTE['pass']}; font-size:{FONT['label']}pt; "
            f"font-weight:600; padding:12px;")
        self._ready_banner.hide()
        root.addWidget(self._ready_banner)

    # ── Public API ─────────────────────────────────────────────────

    def update_actions(self, actions: list) -> None:
        """Replace the displayed list with fresh PendingAction items.

        Parameters
        ----------
        actions : list[PendingAction]
            Unresolved actions from ``evaluate_pending_actions()``.
        """
        self._actions = list(actions)
        self._rebuild_list()

    @property
    def has_blocking(self) -> bool:
        return any(a.severity == "blocking" for a in self._actions)

    @property
    def action_count(self) -> int:
        return len(self._actions)

    # ── Internal ───────────────────────────────────────────────────

    def _rebuild_list(self):
        # Clear existing items
        while self._list_layout.count() > 1:  # keep stretch
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._actions:
            self._summary.setText("All checks passed")
            self._ready_banner.show()
            self._header.setText("Readiness Checklist")
            return

        self._ready_banner.hide()
        blocking = sum(1 for a in self._actions if a.severity == "blocking")
        review = sum(1 for a in self._actions if a.severity == "review")
        info = sum(1 for a in self._actions if a.severity == "info")

        parts = []
        if blocking:
            parts.append(f"{blocking} blocking")
        if review:
            parts.append(f"{review} to review")
        if info:
            parts.append(f"{info} info")
        self._summary.setText(" \u00b7 ".join(parts))

        self._header.setText(f"Readiness Checklist ({len(self._actions)})")

        for action in self._actions:
            row = self._make_action_row(action)
            # Insert before the stretch
            self._list_layout.insertWidget(
                self._list_layout.count() - 1, row)

    def _make_action_row(self, action) -> QFrame:
        """Build a single action row widget."""
        sev_cfg = _SEVERITY_CONFIG.get(
            action.severity, _SEVERITY_CONFIG["info"])
        color = PALETTE.get(sev_cfg["color_key"], PALETTE["text"])

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{PALETTE['surface']}; "
            f"border-left:3px solid {color}; "
            f"border-radius:3px; padding:4px 6px; }}")

        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(6)

        # Severity icon
        icon_lbl = QLabel(sev_cfg["icon"])
        icon_lbl.setFixedWidth(18)
        icon_lbl.setStyleSheet(f"font-size:12pt; color:{color};")
        lay.addWidget(icon_lbl)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        title = QLabel(action.title)
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt; "
            f"font-weight:600;")
        text_col.addWidget(title)

        desc = QLabel(action.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
        text_col.addWidget(desc)

        if action.details:
            details = QLabel(action.details)
            details.setWordWrap(True)
            details.setStyleSheet(
                f"color:{PALETTE['textDim']}; "
                f"font-size:{FONT['caption']}pt; font-style:italic;")
            text_col.addWidget(details)

        lay.addLayout(text_col, 1)

        # Action buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(2)

        if action.nav_target:
            go_btn = QPushButton("Go")
            go_btn.setFixedSize(44, 24)
            go_btn.setStyleSheet(
                f"QPushButton {{ background:{PALETTE['accent']}; "
                f"color:{PALETTE['textOnAccent']}; border-radius:3px; "
                f"font-size:{FONT['caption']}pt; font-weight:600; }}"
                f"QPushButton:hover {{ background:{PALETTE['accentHover']}; }}")
            nav = action.nav_target
            hint = action.tab_hint
            go_btn.clicked.connect(
                lambda checked=False, n=nav, h=hint:
                    self.navigate_requested.emit(n, h))
            btn_col.addWidget(go_btn)

        if action.dismissible:
            dismiss_btn = QPushButton("\u2715")
            dismiss_btn.setFixedSize(24, 24)
            dismiss_btn.setToolTip("Dismiss")
            dismiss_btn.setStyleSheet(
                f"QPushButton {{ color:{PALETTE['textDim']}; "
                f"border:1px solid {PALETTE['border']}; border-radius:3px; }}"
                f"QPushButton:hover {{ color:{PALETTE['text']}; "
                f"background:{PALETTE['surfaceHover']}; }}")
            aid = action.action_id
            dismiss_btn.clicked.connect(
                lambda checked=False, a=aid:
                    self.action_dismissed.emit(a))
            btn_col.addWidget(dismiss_btn)

        lay.addLayout(btn_col)
        return frame

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self):
        self._header.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt; "
            f"font-weight:600; padding:6px 8px;")
        self._summary.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt; "
            f"padding:0 8px 4px 8px;")
        self._ready_banner.setStyleSheet(
            f"color:{PALETTE['pass']}; font-size:{FONT['label']}pt; "
            f"font-weight:600; padding:12px;")
        self._rebuild_list()
