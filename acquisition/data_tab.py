"""
acquisition/data_tab.py

DataTab — the session browser and comparison UI.

Left panel  : scrollable session list with thumbnails, labels, SNR, date
Right panel : detail view for the selected session, with tabs for
              Cold/Hot/Diff/ΔR/R images and metadata
Bottom bar  : Compare mode — pick two sessions and diff their ΔR/R maps
"""

import os, time
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QGroupBox, QTextEdit,
    QLineEdit, QFileDialog, QSplitter, QComboBox, QTabWidget,
    QSizePolicy, QMessageBox, QInputDialog, QToolButton,
    QDialog, QDialogButtonBox, QCheckBox, QDoubleSpinBox)
from PyQt5.QtCore    import Qt, pyqtSignal, QSize
from PyQt5.QtGui     import (QPixmap, QImage, QFont, QColor,
                              QPainter, QPen)

from .session         import Session, SessionMeta
from .session_manager import SessionManager
from .processing      import to_display, apply_colormap, COLORMAP_OPTIONS
import config as cfg_mod
from ui.icons import set_btn_icon


# ------------------------------------------------------------------ #
#  Notes dialog                                                        #
# ------------------------------------------------------------------ #

class NotesDialog(QDialog):
    """
    Full-featured notes editor with quick-insert tag chips.
    Replaces the bare QInputDialog for a much better UX.
    """

    QUICK_TAGS = [
        "25°C", "-20°C", "50°C", "85°C",
        "dark room", "ambient light",
        "no bias", "Vbias=1.5 V", "Vbias=3.3 V",
        "after reflow", "before reflow",
        "calibrated", "uncalibrated",
        "reference sample", "fresh sample",
        "repeat measurement",
    ]

    def __init__(self, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Notes")
        self.setMinimumWidth(560)
        self.setMinimumHeight(340)
        self.setStyleSheet(
            "QDialog  { background:#1a1a1a; }"
            "QLabel   { color:#aaa; font-size:14pt; }"
            "QGroupBox { color:#666; font-size:13pt; border:1px solid #2a2a2a; "
            "            border-radius:3px; margin-top:8px; padding-top:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:8px; }"
            "QPushButton { background:#252525; color:#aaa; border:1px solid #333; "
            "              border-radius:2px; padding:4px 10px; font-size:13pt; }"
            "QPushButton:hover { background:#2e2e2e; color:#fff; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # Title
        title = QLabel("Edit Notes")
        title.setStyleSheet("font-size:18pt; font-weight:bold; color:#ccc;")
        lay.addWidget(title)

        hint = QLabel(
            "Describe the sample, conditions, DUT ID, or anything needed "
            "to reproduce this measurement.")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:13pt; color:#555;")
        lay.addWidget(hint)

        # Main text editor
        self._edit = QTextEdit()
        self._edit.setPlainText(initial_text)
        self._edit.setStyleSheet(
            "background:#161616; color:#ccc; border:1px solid #2a2a2a; "
            "font-size:14pt; font-family:Menlo,monospace;")
        self._edit.setMinimumHeight(120)
        lay.addWidget(self._edit)

        # Quick-insert chips
        chips_box = QGroupBox("Quick tags — click to insert")
        chips_lay = QGridLayout(chips_box)
        chips_lay.setSpacing(5)
        cols = 4
        for i, tag in enumerate(self.QUICK_TAGS):
            btn = QPushButton(tag)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { background:#1e2a28; color:#00d4aa; "
                "border:1px solid #00d4aa33; border-radius:12px; "
                "font-size:12pt; padding:0 8px; }"
                "QPushButton:hover { background:#254d42; border-color:#00d4aa99; }")
            btn.clicked.connect(lambda _, t=tag: self._insert(t))
            chips_lay.addWidget(btn, i // cols, i % cols)
        lay.addWidget(chips_box)

        # Character count
        self._char_lbl = QLabel()
        self._char_lbl.setStyleSheet("color:#444; font-size:12pt;")
        self._edit.textChanged.connect(self._update_char_count)
        self._update_char_count()
        lay.addWidget(self._char_lbl)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Save Notes")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        # Focus the editor, cursor at end
        self._edit.setFocus()
        c = self._edit.textCursor()
        c.movePosition(c.End)
        self._edit.setTextCursor(c)

    def notes(self) -> str:
        return self._edit.toPlainText().strip()

    def _insert(self, text: str):
        cursor = self._edit.textCursor()
        existing = self._edit.toPlainText()
        if existing and not existing.endswith(", ") and not existing.endswith("\n"):
            cursor.insertText(", ")
        cursor.insertText(text)
        self._edit.setFocus()

    def _update_char_count(self):
        n = len(self._edit.toPlainText())
        self._char_lbl.setText(f"{n} characters")


# ------------------------------------------------------------------ #
#  Thumbnail card widget                                               #
# ------------------------------------------------------------------ #

class SessionCard(QFrame):
    """One row in the session list."""
    clicked  = pyqtSignal(str)   # uid
    deleted  = pyqtSignal(str)   # uid

    THUMB_W, THUMB_H = 80, 60

    def __init__(self, meta: SessionMeta, parent=None):
        super().__init__(parent)
        self.uid = meta.uid
        self.setFixedHeight(80)
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        # Thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self._thumb.setStyleSheet("background:#0d0d0d; border:1px solid #2a2a2a;")
        self._thumb.setAlignment(Qt.AlignCenter)
        self._load_thumbnail(meta)
        lay.addWidget(self._thumb)

        # Text info
        info = QVBoxLayout()
        info.setSpacing(2)

        self._label_lbl = QLabel(meta.label or meta.uid)
        self._label_lbl.setStyleSheet(
            "font-size:15pt; color:#ccc; font-weight:bold;")
        self._label_lbl.setWordWrap(False)

        snr_str = f"SNR {meta.snr_db:.1f} dB" if meta.snr_db else "SNR —"
        size_str = f"{meta.frame_w}×{meta.frame_h}" if meta.frame_w else ""
        sub = QLabel(
            f"{meta.timestamp_str}   ·   {meta.n_frames} frames   ·   "
            f"{snr_str}   ·   {size_str}")
        sub.setStyleSheet("font-size:12pt; color:#555;")

        info.addWidget(self._label_lbl)
        info.addWidget(sub)
        lay.addLayout(info, 1)

        # Notes badge — visible only when the session has notes
        self._notes_badge = QLabel("📝")
        self._notes_badge.setFixedSize(20, 20)
        self._notes_badge.setAlignment(Qt.AlignCenter)
        self._notes_badge.setStyleSheet("color:#00d4aa66; font-size:13pt;")
        self._notes_badge.setToolTip("This session has notes")
        self._notes_badge.setVisible(bool(meta.notes))
        lay.addWidget(self._notes_badge)

        # Delete button
        del_btn = QToolButton()
        del_btn.setText("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            "background:transparent; color:#444; border:none; font-size:15pt;")
        del_btn.clicked.connect(lambda: self.deleted.emit(self.uid))
        lay.addWidget(del_btn)

    def _load_thumbnail(self, meta: SessionMeta):
        thumb_path = os.path.join(meta.path, "thumbnail.png")
        if os.path.exists(thumb_path):
            pix = QPixmap(thumb_path).scaled(
                self.THUMB_W, self.THUMB_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._thumb.setPixmap(pix)
        else:
            self._thumb.setText("No\npreview")
            self._thumb.setStyleSheet(
                "background:#0d0d0d; border:1px solid #2a2a2a; "
                "color:#333; font-size:16.5pt;")

    def set_has_notes(self, has_notes: bool):
        """Show or hide the notes badge."""
        self._notes_badge.setVisible(has_notes)

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(
                "SessionCard { background:#1e2d2a; border:1px solid #00d4aa; "
                "border-radius:3px; }")
        else:
            self.setStyleSheet(
                "SessionCard { background:#1e1e1e; border:1px solid #2a2a2a; "
                "border-radius:3px; }"
                "SessionCard:hover { background:#222; border-color:#333; }")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)


# ------------------------------------------------------------------ #
#  Image pane (reused from main_app pattern)                          #
# ------------------------------------------------------------------ #

class DataImagePane(QWidget):
    def __init__(self, title: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self._lbl = QLabel()
        self._lbl.setMinimumSize(300, 220)
        self._lbl.setStyleSheet("background:#0d0d0d; border:1px solid #2a2a2a;")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "font-size:12pt; color:#444; letter-spacing:1px;")
        self._stats = QLabel("")
        self._stats.setAlignment(Qt.AlignCenter)
        self._stats.setStyleSheet(
            "font-family:Menlo,monospace; font-size:12pt; color:#444;")
        lay.addWidget(self._lbl)
        lay.addWidget(self._title)
        lay.addWidget(self._stats)

    def show_array(self, data, mode="auto", cmap="gray"):
        if data is None:
            self._lbl.clear()
            self._stats.setText("")
            return
        disp = to_display(data, mode=mode)
        if cmap != "gray" and disp.ndim == 2:
            disp = apply_colormap(disp, cmap)
        if disp.ndim == 2:
            h, w = disp.shape
            qi   = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = disp.shape[:2]
            qi   = QImage(disp.tobytes(), w, h, w*3, QImage.Format_RGB888)
        sz  = self._lbl.size()
        pix = QPixmap.fromImage(qi).scaled(
            sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl.setPixmap(pix)
        self._stats.setText(
            f"min {data.min():.4g}   max {data.max():.4g}   μ {data.mean():.4g}")

    def clear(self):
        self._lbl.clear()
        self._stats.setText("")


# ------------------------------------------------------------------ #
#  Data tab                                                           #
# ------------------------------------------------------------------ #

class DataTab(QWidget):
    """Session browser and data management tab."""

    def __init__(self, manager: SessionManager):
        super().__init__()
        self._mgr      = manager
        self._cards    = {}           # uid → SessionCard
        self._selected = None         # uid of selected session
        self._compare_a = None
        self._compare_b = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setSizes([320, 900])

    # ---------------------------------------------------------------- #
    #  List panel (left)                                                #
    # ---------------------------------------------------------------- #

    def _build_list_panel(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(280)
        w.setMaximumWidth(360)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Sessions")
        title.setStyleSheet(
            "font-size:15pt; color:#888; letter-spacing:2px; "
            "text-transform:uppercase;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#444;")
        hdr.addWidget(self._count_lbl)
        lay.addLayout(hdr)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by label…")
        self._search.textChanged.connect(self._filter_cards)
        lay.addWidget(self._search)

        # Scrollable card list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:#181818; }")

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(3)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        lay.addWidget(scroll)

        # Buttons
        btns = QHBoxLayout()
        self._folder_btn = QPushButton("Set Folder")
        set_btn_icon(self._folder_btn, "fa5s.folder")
        self._refresh_btn = QPushButton("Refresh")
        set_btn_icon(self._refresh_btn, "fa5s.sync-alt")
        self._folder_btn.clicked.connect(self._set_folder)
        self._refresh_btn.clicked.connect(self._refresh)
        for b in [self._folder_btn, self._refresh_btn]:
            b.setFixedHeight(28)
            btns.addWidget(b)
        lay.addLayout(btns)

        return w

    # ---------------------------------------------------------------- #
    #  Detail panel (right)                                             #
    # ---------------------------------------------------------------- #

    def _build_detail_panel(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # ---- Top: metadata + controls ----
        top = QHBoxLayout()
        lay.addLayout(top)

        # Metadata
        meta_box = QGroupBox("Session Info")
        ml = QGridLayout(meta_box)
        ml.setSpacing(6)
        self._meta_fields = {}
        rows = [("Label",     "label"),
                ("Date",      "timestamp_str"),
                ("Frames",    "n_frames"),
                ("SNR",       "snr_db"),
                ("Size",      "frame_size"),
                ("Exposure",  "exposure_us"),
                ("Duration",  "duration_s"),
                ("ROI",       "roi")]
        for r, (lbl, key) in enumerate(rows):
            ml.addWidget(self._sub(lbl), r, 0)
            val = QLabel("—")
            val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:14pt; color:#aaa;")
            val.setWordWrap(True)
            ml.addWidget(val, r, 1)
            self._meta_fields[key] = val

        # Notes — inline editable, auto-saves on focus-out
        notes_row = len(rows)
        ml.addWidget(self._sub("Notes"), notes_row, 0, Qt.AlignTop)
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Click to add notes…")
        self._notes_edit.setFixedHeight(72)
        self._notes_edit.setStyleSheet(
            "background:#161616; color:#bbb; border:1px solid #2a2a2a; "
            "font-size:13pt; font-family:Menlo,monospace;")
        self._notes_edit.focusOutEvent = self._notes_focus_out
        ml.addWidget(self._notes_edit, notes_row, 1)
        top.addWidget(meta_box, 1)

        # Controls
        ctrl_box = QGroupBox("Actions")
        cl = QVBoxLayout(ctrl_box)
        cl.setSpacing(6)

        self._rename_btn   = QPushButton("Rename")
        set_btn_icon(self._rename_btn, "fa5s.pencil-alt")
        self._notes_btn    = QPushButton("Edit Notes")
        set_btn_icon(self._notes_btn, "fa5s.sticky-note")
        self._export_btn   = QPushButton("Export Files")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._report_btn   = QPushButton("Generate PDF Report")
        set_btn_icon(self._report_btn, "fa5s.file-pdf")
        self._report_btn.setObjectName("primary")
        self._delete_btn   = QPushButton("Delete")
        set_btn_icon(self._delete_btn, "fa5s.trash", "#ff6666")
        self._delete_btn.setObjectName("danger")
        self._cmp_a_btn    = QPushButton("Set as A")
        self._cmp_b_btn    = QPushButton("Set as B")

        for b in [self._rename_btn, self._notes_btn, self._export_btn,
                  self._report_btn, self._delete_btn]:
            b.setFixedHeight(30)
            cl.addWidget(b)

        cl.addWidget(self._hline())

        cmp_lbl = QLabel("Compare")
        cmp_lbl.setStyleSheet(
            "font-size:12pt; color:#555; letter-spacing:1px;")
        cl.addWidget(cmp_lbl)

        self._cmp_a_lbl = QLabel("A: —")
        self._cmp_b_lbl = QLabel("B: —")
        for l in [self._cmp_a_lbl, self._cmp_b_lbl]:
            l.setStyleSheet(
                "font-family:Menlo,monospace; font-size:12pt; color:#666;")
            l.setWordWrap(True)

        for b in [self._cmp_a_btn, self._cmp_b_btn]:
            b.setFixedHeight(28)
            cl.addWidget(b)
        cl.addWidget(self._cmp_a_lbl)
        cl.addWidget(self._cmp_b_lbl)

        self._compare_btn = QPushButton("Compare A vs B")
        set_btn_icon(self._compare_btn, "fa5s.exchange-alt", "#00d4aa")
        self._compare_btn.setObjectName("primary")
        self._compare_btn.setFixedHeight(32)
        self._compare_btn.setEnabled(False)
        cl.addWidget(self._compare_btn)
        cl.addStretch()
        top.addWidget(ctrl_box)

        # ---- Bottom: image viewer tabs ----
        img_tabs = QTabWidget()
        img_tabs.setDocumentMode(True)

        self._pane_cold = DataImagePane("COLD  (baseline)")
        self._pane_hot  = DataImagePane("HOT  (stimulus)")
        self._pane_diff = DataImagePane("DIFFERENCE  hot − cold")
        self._pane_drr  = DataImagePane("ΔR/R  thermoreflectance")
        self._pane_cmp  = DataImagePane("COMPARISON  A − B  ΔR/R")

        self._cmap_combo = QComboBox()
        for c in COLORMAP_OPTIONS:
            self._cmap_combo.addItem(c)
        self._cmap_combo.setFixedWidth(110)
        saved_cmap = cfg_mod.get_pref("display.colormap", "signed")
        if saved_cmap in COLORMAP_OPTIONS:
            self._cmap_combo.setCurrentText(saved_cmap)
        self._cmap_combo.currentTextChanged.connect(self._redisplay_drr)
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))

        drr_wrapper = QWidget()
        dw = QVBoxLayout(drr_wrapper)
        dw.setContentsMargins(4, 4, 4, 4)
        cmap_row = QHBoxLayout()
        cmap_row.addWidget(QLabel("Colormap:"))
        cmap_row.addWidget(self._cmap_combo)
        cmap_row.addStretch()
        dw.addLayout(cmap_row)
        dw.addWidget(self._pane_drr)

        img_tabs.addTab(self._pane_cold, " Cold ")
        img_tabs.addTab(self._pane_hot,  " Hot ")
        img_tabs.addTab(self._pane_diff, " Difference ")
        img_tabs.addTab(drr_wrapper,     " ΔR/R ")
        img_tabs.addTab(self._pane_cmp,  " Compare ")

        lay.addWidget(img_tabs, 1)

        # Wire buttons
        self._rename_btn.clicked.connect(self._rename)
        self._notes_btn.clicked.connect(self._edit_notes)
        self._export_btn.clicked.connect(self._export)
        self._report_btn.clicked.connect(self._generate_report)
        self._delete_btn.clicked.connect(self._delete)
        self._cmp_a_btn.clicked.connect(lambda: self._set_compare("a"))
        self._cmp_b_btn.clicked.connect(lambda: self._set_compare("b"))
        self._compare_btn.clicked.connect(self._run_compare)

        return w

    # ---------------------------------------------------------------- #
    #  Public API — called by main window                              #
    # ---------------------------------------------------------------- #

    def add_session(self, session: Session):
        """Called immediately after a new acquisition is saved."""
        self._add_card(session.meta)
        self._count_lbl.setText(str(self._mgr.count()))

    def refresh(self):
        self._refresh()

    # ---------------------------------------------------------------- #
    #  Card management                                                  #
    # ---------------------------------------------------------------- #

    def _refresh(self):
        n = self._mgr.scan()
        # Remove all existing cards
        for uid, card in list(self._cards.items()):
            self._list_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._selected = None

        for meta in self._mgr.all_metas():
            self._add_card(meta)

        self._count_lbl.setText(str(n))

    def _add_card(self, meta: SessionMeta):
        if meta.uid in self._cards:
            return
        card = SessionCard(meta)
        card.clicked.connect(self._on_card_clicked)
        card.deleted.connect(self._on_card_delete_btn)
        # Insert before the trailing stretch
        idx = self._list_layout.count() - 1
        self._list_layout.insertWidget(idx, card)
        self._cards[meta.uid] = card

    def _remove_card(self, uid: str):
        card = self._cards.pop(uid, None)
        if card:
            self._list_layout.removeWidget(card)
            card.deleteLater()
        self._count_lbl.setText(str(self._mgr.count()))

    def _filter_cards(self, text: str):
        text = text.lower()
        for uid, card in self._cards.items():
            meta = self._mgr.get_meta(uid)
            match = (not text) or (meta and text in meta.label.lower())
            card.setVisible(match)

    # ---------------------------------------------------------------- #
    #  Selection & display                                              #
    # ---------------------------------------------------------------- #

    def _on_card_clicked(self, uid: str):
        # Deselect previous
        if self._selected and self._selected in self._cards:
            self._cards[self._selected].set_selected(False)
        self._selected = uid
        if uid in self._cards:
            self._cards[uid].set_selected(True)
        self._load_and_display(uid)

    def _load_and_display(self, uid: str):
        meta = self._mgr.get_meta(uid)
        if meta is None:
            return

        # Metadata fields
        snr = f"{meta.snr_db:.1f} dB" if meta.snr_db else "—"
        roi = (f"x={meta.roi['x']} y={meta.roi['y']} "
               f"w={meta.roi['w']} h={meta.roi['h']}"
               if meta.roi else "Full frame")
        self._meta_fields["label"].setText(meta.label)
        self._meta_fields["timestamp_str"].setText(meta.timestamp_str)
        self._meta_fields["n_frames"].setText(str(meta.n_frames))
        self._meta_fields["snr_db"].setText(snr)
        self._meta_fields["frame_size"].setText(
            f"{meta.frame_w} × {meta.frame_h}")
        self._meta_fields["exposure_us"].setText(f"{meta.exposure_us:.0f} μs")
        self._meta_fields["duration_s"].setText(f"{meta.duration_s:.1f} s")
        self._meta_fields["roi"].setText(roi)
        # Populate the inline notes editor (block signals to avoid premature save)
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(meta.notes or "")
        self._notes_edit.blockSignals(False)

        # Load session arrays (lazy)
        session = self._mgr.load(uid)
        if session is None:
            return
        self._pane_cold.show_array(session.cold_avg)
        self._pane_hot.show_array(session.hot_avg)
        self._pane_diff.show_array(session.difference, mode="percentile")
        cmap = self._cmap_combo.currentText()
        mode = "signed" if cmap == "signed" else "percentile"
        self._pane_drr.show_array(session.delta_r_over_r, mode=mode, cmap=cmap)
        self._pane_cmp.clear()
        session.unload()   # free memory after display

    def _redisplay_drr(self):
        if self._selected:
            self._load_and_display(self._selected)

    # ---------------------------------------------------------------- #
    #  Actions                                                          #
    # ---------------------------------------------------------------- #

    def _notes_focus_out(self, event):
        """Auto-save notes when the inline editor loses focus."""
        if self._selected:
            notes = self._notes_edit.toPlainText().strip()
            self._mgr.update_notes(self._selected, notes)
            # Update the card badge
            card = self._cards.get(self._selected)
            if card:
                card.set_has_notes(bool(notes))
        # Call original focusOutEvent
        QTextEdit.focusOutEvent(self._notes_edit, event)

    def _rename(self):
        if not self._selected:
            return
        meta = self._mgr.get_meta(self._selected)
        if meta is None:
            return
        text, ok = QInputDialog.getText(
            self, "Rename Session", "New label:", text=meta.label)
        if ok and text:
            self._mgr.update_label(self._selected, text)
            if self._selected in self._cards:
                self._cards[self._selected]._label_lbl.setText(text)
            self._meta_fields["label"].setText(text)

    def _edit_notes(self):
        if not self._selected:
            return
        meta = self._mgr.get_meta(self._selected)
        if meta is None:
            return
        dlg = NotesDialog(meta.notes or "", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            text = dlg.notes()
            self._mgr.update_notes(self._selected, text)
            self._notes_edit.blockSignals(True)
            self._notes_edit.setPlainText(text)
            self._notes_edit.blockSignals(False)
            card = self._cards.get(self._selected)
            if card:
                card.set_has_notes(bool(text))

    def _generate_report(self):
        if not self._selected:
            return
        session = self._mgr.load(self._selected)
        if session is None:
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Save Report To", session.meta.path)
        if not out_dir:
            return

        try:
            from hardware.app_state import app_state
            cal      = app_state.active_calibration
            analysis = app_state.active_analysis
        except Exception:
            cal, analysis = None, None

        try:
            from .report import generate_report
            import os
            assets_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "assets", "microsanj-logo.svg")
            pdf_path = generate_report(
                session,
                output_dir  = out_dir,
                calibration = cal,
                logo_svg    = assets_dir,
                analysis    = analysis)
            QMessageBox.information(
                self, "Report Generated",
                f"PDF report saved to:\n{pdf_path}")
        except Exception as e:
            QMessageBox.critical(
                self, "Report Failed",
                f"Could not generate report:\n{e}")

    def _export(self):
        if not self._selected:
            return

        # ── Format selection dialog ────────────────────────────────
        from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QCheckBox
        from acquisition.export import ExportFormat, SessionExporter

        dlg = QDialog(self)
        dlg.setWindowTitle("Export Session")
        dlg.setStyleSheet(
            "QDialog { background:#1e1e1e; } "
            "QLabel  { color:#ccc; font-size:15pt; } "
            "QCheckBox { color:#ccc; font-size:15pt; } "
            "QPushButton { background:#2a2a2a; color:#ccc; "
            "  border:1px solid #444; border-radius:2px; padding:5px 14px; } "
            "QPushButton:hover { background:#333; color:#fff; }")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)

        title = QLabel("Select export formats")
        title.setStyleSheet("font-size:18pt; font-weight:bold; color:#ccc;")
        v.addWidget(title)
        sub = QLabel("All selected formats will be written to a single output folder.")
        sub.setStyleSheet("font-size:14pt; color:#666;")
        v.addWidget(sub)
        v.addSpacing(4)

        fmt_options = [
            (ExportFormat.TIFF,   "32-bit TIFF     — ImageJ / FIJI / Olympus compatible"),
            (ExportFormat.HDF5,   "HDF5 (.h5)      — All data + metadata in one file"),
            (ExportFormat.CSV,    "CSV              — ΔT values with spatial coordinates"),
            (ExportFormat.MATLAB, "MATLAB (.mat)    — Open directly in MATLAB"),
            (ExportFormat.NPY,    "NumPy (.npy)     — Full-precision arrays + JSON metadata"),
        ]
        checks = {}
        for fmt, label in fmt_options:
            cb = QCheckBox(label)
            cb.setChecked(True)
            v.addWidget(cb)
            checks[fmt] = cb

        v.addSpacing(8)
        px_row = QHBoxLayout()
        px_lbl = QLabel("Spatial calibration (px/μm, 0 = unknown):")
        px_lbl.setStyleSheet("color:#888; font-size:14pt;")
        px_spin = QDoubleSpinBox()
        px_spin.setRange(0, 100)
        px_spin.setValue(0)
        px_spin.setDecimals(4)
        px_spin.setFixedWidth(100)
        px_spin.setStyleSheet(
            "background:#222; color:#ccc; border:1px solid #444; "
            "padding:3px 6px;")
        px_row.addWidget(px_lbl)
        px_row.addWidget(px_spin)
        px_row.addStretch()
        v.addLayout(px_row)
        v.addSpacing(8)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        btns.button(QDialogButtonBox.Ok).setText("Export…")
        v.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        selected_fmts = [f for f, cb in checks.items() if cb.isChecked()]
        if not selected_fmts:
            return

        px_per_um = px_spin.value()

        # ── Choose output directory ────────────────────────────────
        d = QFileDialog.getExistingDirectory(self, "Export to folder", ".")
        if not d:
            return

        session = self._mgr.load(self._selected)
        if session is None:
            return

        folder = os.path.join(d, session.meta.uid)

        # ── Run export in background thread ─────────────────────────
        def _run():
            exporter = SessionExporter(session, output_dir=folder,
                                       px_per_um=px_per_um)
            result = exporter.export(selected_fmts)
            msg = (f"Exported {result.n_files} file(s) to:\n{folder}"
                   if result.success
                   else f"Export failed:\n"
                        + "\n".join(result.errors.values()))
            QTimer.singleShot(0, lambda: QMessageBox.information(
                self, "Export complete" if result.success else "Export error",
                msg))

        import threading
        from PyQt5.QtCore import QTimer
        threading.Thread(target=_run, daemon=True).start()

    def _delete(self):
        if not self._selected:
            return
        meta = self._mgr.get_meta(self._selected)
        if meta is None:
            return
        r = QMessageBox.question(
            self, "Delete Session",
            f"Permanently delete session:\n{meta.label}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            uid = self._selected
            self._selected = None
            self._mgr.delete(uid)
            self._remove_card(uid)
            for pane in [self._pane_cold, self._pane_hot,
                         self._pane_diff, self._pane_drr]:
                pane.clear()

    def _on_card_delete_btn(self, uid: str):
        """Delete button on the card itself."""
        meta = self._mgr.get_meta(uid)
        if meta is None:
            return
        r = QMessageBox.question(
            self, "Delete Session",
            f"Delete:\n{meta.label}?",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            if self._selected == uid:
                self._selected = None
            self._mgr.delete(uid)
            self._remove_card(uid)

    def _set_compare(self, slot: str):
        if not self._selected:
            return
        meta = self._mgr.get_meta(self._selected)
        if meta is None:
            return
        if slot == "a":
            self._compare_a = self._selected
            self._cmp_a_lbl.setText(f"A: {meta.label[:30]}")
        else:
            self._compare_b = self._selected
            self._cmp_b_lbl.setText(f"B: {meta.label[:30]}")

        self._compare_btn.setEnabled(
            bool(self._compare_a and self._compare_b))

    def _run_compare(self):
        if not (self._compare_a and self._compare_b):
            return
        diff = self._mgr.diff_drr(self._compare_a, self._compare_b)
        if diff is None:
            QMessageBox.warning(
                self, "Compare Failed",
                "Could not compute difference.\n"
                "Sessions must have ΔR/R data of the same dimensions.")
            return
        cmap = self._cmap_combo.currentText()
        mode = "signed" if cmap == "signed" else "percentile"
        self._pane_cmp.show_array(diff, mode=mode, cmap=cmap)

        ma = self._mgr.get_meta(self._compare_a)
        mb = self._mgr.get_meta(self._compare_b)
        self._pane_cmp._title.setText(
            f"A: {ma.label[:20]}  −  B: {mb.label[:20]}")

    # ---------------------------------------------------------------- #
    #  Folder management                                                #
    # ---------------------------------------------------------------- #

    def _set_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Sessions Folder",
            self._mgr.root if self._mgr.root else ".")
        if d:
            self._mgr.root = d
            self._refresh()

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#2a2a2a;")
        return f
