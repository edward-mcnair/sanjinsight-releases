"""
ui/tabs/home_tab.py

HomeTab — landing dashboard showing recent acquisitions.

Displays up to 5 most-recent session cards with thumbnail, label,
timestamp, status chip, and an [Open] button.  Emits signals for
opening a session or starting a new acquisition.
"""

from __future__ import annotations

import os
import datetime
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSpacerItem,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QPixmap, QColor

import config
from acquisition.session import Session, SessionMeta
from ui.theme import PALETTE, FONT


# ── Status chip colours (semantic, not from PALETTE) ──────────────────────────
_STATUS_COLOURS = {
    "reviewed": "#00d479",   # green  — pass / reviewed
    "pass":     "#00d479",
    "flagged":  "#ffb300",   # amber  — review / flagged
    "review":   "#ffb300",
    "archived": "#ff4444",   # red    — fail / archived
    "fail":     "#ff4444",
}

_STATUS_LABELS = {
    "reviewed": "PASS",
    "pass":     "PASS",
    "flagged":  "REVIEW",
    "review":   "REVIEW",
    "archived": "FAIL",
    "fail":     "FAIL",
    "pending":  "—",
    "":         "—",
}

CARD_W = 180
CARD_H = 220
THUMB_W = 160
THUMB_H = 100


class _SessionCard(QFrame):
    """Single session card widget."""

    open_requested = pyqtSignal(str)  # emits folder path

    def __init__(self, meta: SessionMeta, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._meta = meta
        self._build()
        self._apply_styles()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self.setFixedSize(CARD_W, CARD_H)
        self.setObjectName("SessionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── Thumbnail ──────────────────────────────────────────────
        thumb_path = os.path.join(self._meta.path, "thumbnail.png")
        pix = QPixmap(thumb_path) if os.path.exists(thumb_path) else QPixmap()

        if not pix.isNull():
            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(THUMB_W, THUMB_H)
            thumb_lbl.setAlignment(Qt.AlignCenter)
            thumb_lbl.setPixmap(
                pix.scaled(THUMB_W, THUMB_H,
                            Qt.KeepAspectRatio, Qt.SmoothTransformation))
            thumb_lbl.setStyleSheet(
                f"background: {PALETTE['surface2']}; border-radius: 4px;")
            layout.addWidget(thumb_lbl)
        else:
            placeholder = QFrame()
            placeholder.setFixedSize(THUMB_W, THUMB_H)
            placeholder.setStyleSheet(
                f"background: {PALETTE['surface2']};"
                f" border: 1px solid {PALETTE['border']};"
                f" border-radius: 4px;")
            ph_layout = QVBoxLayout(placeholder)
            ph_layout.setContentsMargins(0, 0, 0, 0)
            no_prev = QLabel("No preview")
            no_prev.setAlignment(Qt.AlignCenter)
            no_prev.setStyleSheet(
                f"color: {PALETTE['textDim']};"
                f" font-size: {FONT['caption']}pt;")
            ph_layout.addWidget(no_prev)
            layout.addWidget(placeholder)

        # ── Session label ──────────────────────────────────────────
        raw_label = self._meta.label or self._meta.uid or "Unnamed"
        display_label = (raw_label[:20] + "…") if len(raw_label) > 20 else raw_label

        label_lbl = QLabel(display_label)
        label_lbl.setToolTip(raw_label)
        lbl_font = QFont()
        lbl_font.setPointSize(FONT["label"])
        lbl_font.setWeight(QFont.DemiBold)
        label_lbl.setFont(lbl_font)
        label_lbl.setStyleSheet(f"color: {PALETTE['text']};")
        label_lbl.setWordWrap(False)
        layout.addWidget(label_lbl)

        # ── Timestamp ─────────────────────────────────────────────
        ts_text = self._meta.timestamp_str or self._format_ts(self._meta.timestamp)
        ts_lbl = QLabel(ts_text)
        ts_lbl.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: {FONT['caption']}pt;")
        layout.addWidget(ts_lbl)

        # ── Status chip ───────────────────────────────────────────
        status_key = (self._meta.status or "").lower()
        chip_color = _STATUS_COLOURS.get(status_key, PALETTE["textDim"])
        chip_text  = _STATUS_LABELS.get(status_key, "—")

        chip = QLabel(chip_text)
        chip.setAlignment(Qt.AlignCenter)
        chip.setFixedHeight(18)
        chip.setStyleSheet(
            f"background: {chip_color}22;"
            f" color: {chip_color};"
            f" border: 1px solid {chip_color}66;"
            f" border-radius: 4px;"
            f" font-size: {FONT['caption']}pt;"
            f" font-weight: 600;"
            f" padding: 0 6px;")
        layout.addWidget(chip)

        layout.addStretch(1)

        # ── Open button ───────────────────────────────────────────
        open_btn = QPushButton("Open")
        open_btn.setFixedHeight(26)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(lambda: self.open_requested.emit(self._meta.path))
        self._open_btn = open_btn
        layout.addWidget(open_btn)

    def _format_ts(self, ts: float) -> str:
        if not ts:
            return ""
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"#SessionCard {{"
            f"  background: {PALETTE['surface']};"
            f"  border: 1px solid {PALETTE['border']};"
            f"  border-radius: 6px;"
            f"}}"
            f"#SessionCard:hover {{"
            f"  border: 1px solid {PALETTE['accent']};"
            f"}}"
        )
        self._open_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['accent']}22;"
            f"  color: {PALETTE['accent']};"
            f"  border: 1px solid {PALETTE['accent']}66;"
            f"  border-radius: 4px;"
            f"  font-size: {FONT['label']}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['accentHover']}33;"
            f"  border: 1px solid {PALETTE['accentHover']};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: {PALETTE['accent']}44;"
            f"}}"
        )


class HomeTab(QWidget):
    """Landing dashboard with recent session cards and a New Acquisition button."""

    open_session_requested  = pyqtSignal(str)   # folder path
    new_acquisition_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: List[_SessionCard] = []
        self._build_skeleton()
        self.refresh()

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-scan the sessions directory and rebuild the cards area."""
        metas = self._load_recent_sessions()
        self._rebuild_cards(metas)

    def _apply_styles(self) -> None:
        """Called by MainWindow on every theme switch."""
        self.setStyleSheet(
            f"HomeTab {{ background: {PALETTE['bg']}; }}")
        self._header_lbl.setStyleSheet(
            f"color: {PALETTE['text']};"
            f" font-size: {FONT['title']}pt;"
            f" font-weight: 600;")
        self._subtitle_lbl.setStyleSheet(
            f"color: {PALETTE['textDim']};"
            f" font-size: {FONT['heading']}pt;")
        self._new_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['accent']};"
            f"  color: #000000;"
            f"  border: none;"
            f"  border-radius: 6px;"
            f"  font-size: {FONT['body']}pt;"
            f"  font-weight: 600;"
            f"  padding: 8px 24px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['accentHover']};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: {PALETTE['accent']};"
            f"}}"
        )
        # Refresh card styles too
        for card in self._cards:
            card._apply_styles()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_skeleton(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(0)

        # ── Welcome header ────────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(0)

        self._header_lbl = QLabel("SanjINSIGHT")
        hdr_font = QFont()
        hdr_font.setPointSize(FONT["title"])
        hdr_font.setWeight(QFont.Bold)
        self._header_lbl.setFont(hdr_font)
        self._header_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['title']}pt; font-weight: 600;")
        header_row.addWidget(self._header_lbl)
        header_row.addStretch(1)
        root.addLayout(header_row)

        root.addSpacing(4)

        self._subtitle_lbl = QLabel("Recent Acquisitions")
        self._subtitle_lbl.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: {FONT['heading']}pt;")
        root.addWidget(self._subtitle_lbl)

        root.addSpacing(20)

        # ── Cards area ────────────────────────────────────────────────────
        # Wrapped in a scroll area so it degrades gracefully on small windows
        self._cards_container = QWidget()
        self._cards_layout = QHBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(16)
        self._cards_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidget(self._cards_container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedHeight(CARD_H + 16)
        scroll.setStyleSheet("background: transparent;")
        self._cards_container.setStyleSheet("background: transparent;")

        root.addWidget(scroll)
        root.addSpacing(24)

        # ── New Acquisition button ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)

        self._new_btn = QPushButton("New Acquisition")
        self._new_btn.setFixedHeight(40)
        self._new_btn.setCursor(Qt.PointingHandCursor)
        self._new_btn.clicked.connect(self.new_acquisition_requested.emit)
        self._new_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['accent']};"
            f"  color: #000000;"
            f"  border: none;"
            f"  border-radius: 6px;"
            f"  font-size: {FONT['body']}pt;"
            f"  font-weight: 600;"
            f"  padding: 8px 24px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['accentHover']};"
            f"}}"
        )
        btn_row.addWidget(self._new_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        root.addStretch(1)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _sessions_dir(self) -> str:
        d = config.get_pref("sessions_dir", "")
        if not d:
            d = os.path.join(os.path.expanduser("~"), ".microsanj", "sessions")
        return d

    def _load_recent_sessions(self) -> List[SessionMeta]:
        sessions_dir = self._sessions_dir()
        if not os.path.isdir(sessions_dir):
            return []

        metas: List[SessionMeta] = []
        try:
            entries = os.listdir(sessions_dir)
        except OSError:
            return []

        for name in entries:
            folder = os.path.join(sessions_dir, name)
            if not os.path.isdir(folder):
                continue
            meta = Session.load_meta(folder)
            if meta is not None:
                metas.append(meta)

        # Sort descending by timestamp; most-recent first
        metas.sort(key=lambda m: m.timestamp, reverse=True)
        return metas[:5]

    # ── Cards rebuild ─────────────────────────────────────────────────────────

    def _rebuild_cards(self, metas: List[SessionMeta]) -> None:
        # Clear existing cards
        self._cards.clear()
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not metas:
            self._show_empty_state()
            return

        for meta in metas:
            card = _SessionCard(meta)
            card.open_requested.connect(self.open_session_requested.emit)
            self._cards_layout.addWidget(card)
            self._cards.append(card)

        self._cards_layout.addStretch(1)

    def _show_empty_state(self) -> None:
        empty = QLabel(
            "📷  No acquisitions yet.\n"
            "Run your first scan from the AutoScan or Capture tab."
        )
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet(
            f"color: {PALETTE['textDim']};"
            f" font-size: {FONT['body']}pt;"
            f" padding: 32px;")
        empty.setWordWrap(True)
        self._cards_layout.addWidget(empty)
        self._cards_layout.addStretch(1)
