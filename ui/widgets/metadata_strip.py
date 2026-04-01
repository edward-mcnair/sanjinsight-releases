"""
ui/widgets/metadata_strip.py

MetadataStrip — compact post-scan annotation bar.

Appearance (two rows below the live/result image)
--------------------------------------------------
    ┌──────────────────────────────────────────────────────┐
    │ Tags   thermal-soak ×   pre-etch ×   [add tag…]      │
    ├──────────────────────────────────────────────────────┤
    │ Notes  2026-03-13 14:22  "Initial run looks good"    │
    │        [Add note…                              [Add]] │
    └──────────────────────────────────────────────────────┘

Behaviour
---------
• Hidden on init; call show_strip() after a scan completes.
• Tags row embeds TagInputWidget (chip-bar autocomplete).
• Notes row shows an append-only scrollable log; text field + Add button
  create new NoteEntry objects.
• Author is read from config (optional); can be empty.
• Call reset() to clear for a new scan.

Signals
-------
tags_changed(list[str])          Forwarded from TagInputWidget.
note_added(NoteEntry)            Emitted when user confirms a note.

Public API
----------
show_strip()                     Reveal the strip (call after scan done).
reset(tags, notes)               Set initial tags/notes without emitting.
tags() → list[str]               Current tags.
notes() → list[NoteEntry]        All note entries in order.
set_metadata(ResultMetadata)     Bulk-load tags + notes; no signals.
get_metadata() → ResultMetadata  Return a ResultMetadata snapshot.
_apply_styles()                  Called on theme switch.
"""

from __future__ import annotations

import time
from typing import List, Optional

from PyQt5.QtCore    import Qt, pyqtSignal, QSize
from PyQt5.QtGui     import QKeyEvent
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy)

from acquisition.metadata import NoteEntry, ResultMetadata, get_registry
from ui.theme             import PALETTE, FONT
from ui.widgets.tag_input import TagInputWidget


# ── Note log entry (one row in the log) ────────────────────────────────────

class _NoteRow(QWidget):
    """Single read-only note row: timestamp + author (dim) + text."""

    def __init__(self, entry: NoteEntry, parent: QWidget = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        meta = entry.timestamp_str
        if entry.author:
            meta += f"  ·  {entry.author}"

        self._meta_lbl = QLabel(meta)
        self._meta_lbl.setObjectName("note_meta")
        self._meta_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._text_lbl = QLabel(entry.text)
        self._text_lbl.setObjectName("note_text")
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        lay.addWidget(self._meta_lbl)
        lay.addWidget(self._text_lbl, 1)

    def apply_styles(self) -> None:
        dim = PALETTE['textDim']
        txt = PALETTE['text']
        sz  = FONT.get("sublabel", 9)
        self._meta_lbl.setStyleSheet(
            f"QLabel#note_meta {{ color:{dim}; font-size:{sz}pt; }}")
        self._text_lbl.setStyleSheet(
            f"QLabel#note_text {{ color:{txt}; font-size:{sz}pt; }}")


# ── Main strip widget ───────────────────────────────────────────────────────

class MetadataStrip(QWidget):
    """Compact two-row annotation bar shown below the scan result image.

    Embed below the live view in AutoScanTab (and elsewhere).  Call
    ``show_strip()`` after a scan completes; call ``reset()`` before a new
    scan begins.
    """

    tags_changed = pyqtSignal(list)    # list[str]
    note_added   = pyqtSignal(object)  # NoteEntry

    def __init__(self, author: str = "", parent: QWidget = None) -> None:
        super().__init__(parent)
        self._author  = author
        self._notes:  List[NoteEntry] = []
        self._visible = False

        self._build_ui()
        self._apply_styles()
        self.hide()

    # ── Build ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._frame = QFrame()
        self._frame.setObjectName("metadata_strip_frame")
        root.addWidget(self._frame)

        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(4)

        # ── Row 1: Tags ──────────────────────────────────────────
        tag_row = QHBoxLayout()
        tag_row.setSpacing(8)

        self._tag_lbl = QLabel("Tags")
        self._tag_lbl.setObjectName("strip_section_lbl")
        self._tag_lbl.setFixedWidth(40)
        tag_row.addWidget(self._tag_lbl)

        self._tag_input = TagInputWidget(placeholder="add tag…")
        self._tag_input.tags_changed.connect(self.tags_changed)
        tag_row.addWidget(self._tag_input, 1)

        inner.addLayout(tag_row)

        # Separator
        sep = QFrame()
        sep.setObjectName("strip_sep")
        sep.setFrameShape(QFrame.HLine)
        inner.addWidget(sep)

        # ── Row 2: Notes ─────────────────────────────────────────
        note_col = QVBoxLayout()
        note_col.setSpacing(4)

        # Header
        note_hdr = QHBoxLayout()
        self._note_lbl = QLabel("Notes")
        self._note_lbl.setObjectName("strip_section_lbl")
        self._note_lbl.setFixedWidth(40)
        note_hdr.addWidget(self._note_lbl)
        note_hdr.addStretch(1)
        note_col.addLayout(note_hdr)

        # Scrollable log of existing notes
        self._log_scroll = QScrollArea()
        self._log_scroll.setObjectName("note_log_scroll")
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log_scroll.setFixedHeight(64)
        self._log_scroll.hide()   # hidden until first note exists

        self._log_container = QWidget()
        self._log_lay = QVBoxLayout(self._log_container)
        self._log_lay.setContentsMargins(0, 0, 0, 0)
        self._log_lay.setSpacing(0)
        self._log_lay.addStretch()

        self._log_scroll.setWidget(self._log_container)
        note_col.addWidget(self._log_scroll)

        # Input row
        note_input_row = QHBoxLayout()
        note_input_row.setSpacing(6)

        self._note_input = QLineEdit()
        self._note_input.setObjectName("note_input_field")
        self._note_input.setPlaceholderText("Add observation…")
        self._note_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._note_input.returnPressed.connect(self._commit_note)
        note_input_row.addWidget(self._note_input, 1)

        self._add_btn = QPushButton("Add")
        self._add_btn.setObjectName("note_add_btn")
        self._add_btn.setFixedWidth(48)
        self._add_btn.clicked.connect(self._commit_note)
        note_input_row.addWidget(self._add_btn)

        note_col.addLayout(note_input_row)

        # Combine label + note column
        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        note_row.addLayout(note_col, 1)

        inner.addLayout(note_row)

    # ── Public API ─────────────────────────────────────────────────────

    def show_strip(self) -> None:
        """Reveal the strip.  Call after a scan completes."""
        self._visible = True
        self.show()

    def reset(self, tags: List[str] = None, notes: List[NoteEntry] = None) -> None:
        """Clear and optionally pre-populate without emitting signals."""
        self._notes = list(notes) if notes else []
        self._tag_input.set_tags(tags or [])
        self._rebuild_log()
        # Keep hidden until explicitly shown
        self._visible = False
        self.hide()

    def tags(self) -> List[str]:
        return self._tag_input.tags()

    def notes(self) -> List[NoteEntry]:
        return list(self._notes)

    def set_metadata(self, meta: ResultMetadata) -> None:
        """Bulk-load from a ResultMetadata instance.  No signals emitted."""
        self._tag_input.set_tags(meta.tags)
        self._notes = list(meta.notes)
        self._rebuild_log()

    def get_metadata(self) -> ResultMetadata:
        """Return a ResultMetadata snapshot of current tags + notes."""
        rm = ResultMetadata()
        rm.tags  = self._tag_input.tags()
        rm.notes = list(self._notes)
        return rm

    def set_author(self, author: str) -> None:
        self._author = author

    # ── Note management ────────────────────────────────────────────────

    def _commit_note(self) -> None:
        text = self._note_input.text().strip()
        if not text:
            return
        entry = NoteEntry(text=text, author=self._author)
        self._notes.append(entry)
        self._note_input.clear()
        self._append_note_row(entry)
        # Auto-scroll to bottom
        sb = self._log_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.note_added.emit(entry)

    def _append_note_row(self, entry: NoteEntry) -> None:
        row = _NoteRow(entry)
        row.apply_styles()
        # Insert before the trailing stretch
        self._log_lay.insertWidget(self._log_lay.count() - 1, row)
        if not self._log_scroll.isVisible():
            self._log_scroll.show()

    def _rebuild_log(self) -> None:
        """Tear down and rebuild the note log from self._notes."""
        while self._log_lay.count() > 1:
            item = self._log_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for entry in self._notes:
            self._append_note_row(entry)
        self._log_scroll.setVisible(bool(self._notes))

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        bg  = PALETTE['bg']
        bdr = PALETTE['border']
        dim = PALETTE['textDim']
        txt = PALETTE['text']
        acc = PALETTE['accent']
        sz  = FONT.get("sublabel", 9)
        body = FONT.get("body", 11)

        self._frame.setStyleSheet(
            f"QFrame#metadata_strip_frame {{"
            f"  background:{bg}; border-top:1px solid {bdr};"
            f"}}"
            f"QFrame#strip_sep {{"
            f"  background:{bdr}; max-height:1px; border:none;"
            f"}}"
        )

        lbl_style = (
            f"QLabel#strip_section_lbl {{"
            f"  color:{dim}; font-size:{sz}pt;"
            f"  font-weight:600; text-transform:uppercase;"
            f"}}"
        )
        self._tag_lbl.setStyleSheet(lbl_style)
        self._note_lbl.setStyleSheet(lbl_style)

        self._note_input.setStyleSheet(
            f"QLineEdit#note_input_field {{"
            f"  background:{PALETTE['surface']};"
            f"  color:{txt}; border:1px solid {bdr}; border-radius:4px;"
            f"  font-size:{body}pt; padding:3px 6px;"
            f"}}"
            f"QLineEdit#note_input_field:focus {{ border-color:{acc}; }}"
        )

        self._add_btn.setStyleSheet(
            f"QPushButton#note_add_btn {{"
            f"  background:{acc}; color:{PALETTE['textOnAccent']}; border:none; border-radius:4px;"
            f"  font-size:{sz}pt; font-weight:600; padding:4px 0;"
            f"}}"
            f"QPushButton#note_add_btn:hover {{ background:{acc}cc; }}"
            f"QPushButton#note_add_btn:pressed {{ background:{acc}99; }}"
        )

        self._log_scroll.setStyleSheet(
            f"QScrollArea#note_log_scroll {{"
            f"  background:transparent; border:none;"
            f"}}"
        )

        self._tag_input._apply_styles()

        # Re-style any existing note rows
        for i in range(self._log_lay.count()):
            item = self._log_lay.itemAt(i)
            if item and isinstance(item.widget(), _NoteRow):
                item.widget().apply_styles()
