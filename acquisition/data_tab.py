"""
acquisition/data_tab.py

DataTab — the session browser and comparison UI.

Left panel  : scrollable session list with thumbnails, labels, SNR, date
Right panel : detail view for the selected session, with tabs for
              Cold/Hot/Diff/ΔR/R images and metadata
Bottom bar  : Compare mode — pick two sessions and diff their ΔR/R maps
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QGroupBox, QTextEdit,
    QLineEdit, QFileDialog, QSplitter, QComboBox, QTabWidget,
    QMessageBox, QInputDialog, QToolButton, QStackedWidget,
    QDialog, QDialogButtonBox, QCheckBox, QDoubleSpinBox,
    QSizePolicy)
from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtGui     import QPixmap, QImage

from .session         import Session, SessionMeta
from .session_manager import SessionManager
from .processing      import to_display, apply_colormap, setup_cmap_combo
import config as cfg_mod
from ui.icons import IC, make_icon_label, set_btn_icon
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.charts import SessionTrendChart


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
            f"QDialog  {{ background:{PALETTE['bg']}; }}"
            f"QLabel   {{ color:{PALETTE['text']}; font-size:{FONT['heading']}pt; }}"
            f"QGroupBox {{ color:{PALETTE['textDim']}; font-size:{FONT['body']}pt; border:1px solid {PALETTE['border']}; "
            f"            border-radius:3px; margin-top:8px; padding-top:6px; }}"
            f"QGroupBox::title {{ subcontrol-origin:margin; left:8px; }}"
            f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['textSub']}; border:1px solid {PALETTE['border']}; "
            f"              border-radius:2px; padding:4px 10px; font-size:{FONT['body']}pt; }}"
            f"QPushButton:hover {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # Title
        title = QLabel("Edit Notes")
        title.setStyleSheet(scaled_qss(f"font-size:18pt; font-weight:bold; color:{PALETTE['text']};"))
        lay.addWidget(title)

        hint = QLabel(
            "Describe the sample, conditions, DUT ID, or anything needed "
            "to reproduce this measurement.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:{FONT['body']}pt; color:{PALETTE['textDim']};")
        lay.addWidget(hint)

        # Main text editor
        self._edit = QTextEdit()
        self._edit.setPlainText(initial_text)
        self._edit.setStyleSheet(
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"font-size:{FONT['heading']}pt; font-family:{MONO_FONT};")
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
                f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['accent']}; "
                f"border:1px solid {PALETTE['accent']}33; border-radius:12px; "
                f"font-size:{FONT['label']}pt; padding:0 8px; }}"
                f"QPushButton:hover {{ background:{PALETTE['surface']}; border-color:{PALETTE['accent']}99; }}")
            btn.clicked.connect(lambda _, t=tag: self._insert(t))
            chips_lay.addWidget(btn, i // cols, i % cols)
        lay.addWidget(chips_box)

        # Character count
        self._char_lbl = QLabel()
        self._char_lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
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
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        # Determine if this session has lab context to show an extra chips row
        _has_chips = bool(
            getattr(meta, "operator",  "") or
            getattr(meta, "device_id", "") or
            getattr(meta, "project",   "") or
            getattr(meta, "tags",      [])
        )
        self.setFixedHeight(100 if _has_chips else 80)
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        # Thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self._thumb.setStyleSheet(f"background:{PALETTE['surface']}; border:1px solid {PALETTE['border']};")
        self._thumb.setAlignment(Qt.AlignCenter)
        self._load_thumbnail(meta)
        lay.addWidget(self._thumb)

        # Text info
        info = QVBoxLayout()
        info.setSpacing(2)

        self._label_lbl = QLabel(meta.label or meta.uid)
        self._label_lbl.setStyleSheet(
            scaled_qss(f"font-size:15pt; color:{PALETTE['text']}; font-weight:bold;"))
        self._label_lbl.setWordWrap(False)

        snr_str = f"SNR {meta.snr_db:.1f} dB" if meta.snr_db else "SNR —"
        size_str = f"{meta.frame_w}×{meta.frame_h}" if meta.frame_w else ""
        sub = QLabel(
            f"{meta.timestamp_str}   ·   {meta.n_frames} frames   ·   "
            f"{snr_str}   ·   {size_str}")
        sub.setStyleSheet(f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']};")

        info.addWidget(self._label_lbl)
        info.addWidget(sub)

        # ── Lab-context chip row ──────────────────────────────────────
        if _has_chips:
            chips_w = QWidget()
            chips_w.setStyleSheet("background:transparent;")
            chips_lay = QHBoxLayout(chips_w)
            chips_lay.setContentsMargins(0, 2, 0, 0)
            chips_lay.setSpacing(4)

            op = getattr(meta, "operator",  "") or ""
            dev = getattr(meta, "device_id", "") or ""
            proj = getattr(meta, "project",   "") or ""
            free_tags = list(getattr(meta, "tags", []) or [])

            if op:
                chips_lay.addWidget(self._chip(op, PALETTE['info'], filled=True))
            if dev:
                chips_lay.addWidget(self._chip(dev, PALETTE['accent']))
            if proj:
                chips_lay.addWidget(self._chip(proj, PALETTE['warning']))
            for t in free_tags[:4]:          # show at most 4 free tags
                chips_lay.addWidget(self._chip(t, PALETTE['textDim']))

            chips_lay.addStretch()
            info.addWidget(chips_w)

        lay.addLayout(info, 1)

        # Status badge — pill showing review status
        self._status_badge = QLabel()
        self._status_badge.setFixedHeight(16)
        self._status_badge.setAlignment(Qt.AlignCenter)
        self._set_status_badge(getattr(meta, "status", "") or "")
        lay.addWidget(self._status_badge)

        # Notes badge — visible only when the session has notes
        self._notes_badge = make_icon_label(IC.NOTE, color=f"{PALETTE['accent']}66", size=14)
        self._notes_badge.setFixedSize(20, 20)
        self._notes_badge.setToolTip("This session has notes")
        self._notes_badge.setVisible(bool(meta.notes))
        lay.addWidget(self._notes_badge)

        # A/B compare slot badge — hidden until assigned
        self._cmp_badge = QLabel()
        self._cmp_badge.setFixedSize(20, 20)
        self._cmp_badge.setAlignment(Qt.AlignCenter)
        self._cmp_badge.setVisible(False)
        lay.addWidget(self._cmp_badge)

        # Delete button
        del_btn = QToolButton()
        del_btn.setText("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            scaled_qss(f"background:transparent; color:{PALETTE['textDim']}; border:none; font-size:15pt;"))
        del_btn.clicked.connect(lambda: self.deleted.emit(self.uid))
        lay.addWidget(del_btn)

    @staticmethod
    def _chip(text: str, color: str, filled: bool = False) -> QLabel:
        """Return a small pill label styled as a tag chip."""
        lbl = QLabel(text)
        lbl.setFixedHeight(16)
        if filled:
            lbl.setStyleSheet(
                f"color:{PALETTE['textOnAccent']}; background:{color}; border-radius:7px; "
                f"padding:0 6px; font-size:{FONT['sublabel']}pt;")
        else:
            lbl.setStyleSheet(
                f"color:{color}; border:1px solid {color}55; border-radius:7px; "
                f"padding:0 6px; font-size:{FONT['sublabel']}pt; background:transparent;")
        return lbl

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
                scaled_qss(f"background:{PALETTE['canvas']}; border:1px solid {PALETTE['border']}; "
                           f"color:{PALETTE['textSub']}; font-size:16.5pt;"))

    _STATUS_COLORS = {
        "pending":  PALETTE['warning'],
        "reviewed": PALETTE['accent'],
        "flagged":  PALETTE['danger'],
        "archived": PALETTE['textSub'],
    }

    def _set_status_badge(self, status: str):
        """Update the status pill label."""
        color = self._STATUS_COLORS.get(status, "")
        if not color or not status:
            self._status_badge.setVisible(False)
            return
        self._status_badge.setText(status.capitalize())
        self._status_badge.setToolTip(f"Status: {status}")
        self._status_badge.setStyleSheet(
            f"color:{PALETTE['textOnAccent']}; background:{color}; border-radius:7px; "
            f"padding:0 6px; font-size:{FONT['sublabel']}pt;")
        self._status_badge.setVisible(True)

    def set_status(self, status: str):
        """Public setter for status badge (called after status change)."""
        self._set_status_badge(status)

    def set_has_notes(self, has_notes: bool):
        """Show or hide the notes badge."""
        self._notes_badge.setVisible(has_notes)

    def set_compare_slot(self, slot):  # slot: str | None
        """Show 'A' (teal) or 'B' (blue) badge, or hide if slot is None."""
        if slot is None:
            self._cmp_badge.setVisible(False)
            return
        color = PALETTE['accent'] if slot == "a" else PALETTE['info']
        letter = slot.upper()
        self._cmp_badge.setText(letter)
        self._cmp_badge.setToolTip(f"Assigned to compare slot {letter}")
        self._cmp_badge.setStyleSheet(
            f"background:{color}; color:{PALETTE['textOnAccent']}; border-radius:10px; "
            f"font-size:{FONT['sublabel']}pt; font-weight:700;"
        )
        self._cmp_badge.setVisible(True)

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def _apply_style(self):
        acc  = PALETTE['accent']
        surf = PALETTE['surface']
        surf2 = PALETTE['surface2']
        bdr  = PALETTE['border']
        if self._selected:
            self.setStyleSheet(
                f"SessionCard {{ background:{surf2}; border:1px solid {acc}; "
                f"border-radius:3px; }}")
        else:
            self.setStyleSheet(
                f"SessionCard {{ background:{surf}; border:1px solid {bdr}; "
                f"border-radius:3px; }}"
                f"SessionCard:hover {{ background:{surf2}; border-color:{bdr}; }}")

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
        self._lbl.setStyleSheet(f"background:{PALETTE['canvas']}; border:1px solid {PALETTE['border']};")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textSub']}; letter-spacing:1px;")
        self._stats = QLabel("")
        self._stats.setAlignment(Qt.AlignCenter)
        self._stats.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['label']}pt; color:{PALETTE['textSub']};")
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

    navigate_requested = pyqtSignal(str)          # sidebar label
    status_changed     = pyqtSignal(str, str)     # (uid, new_status)
    export_completed   = pyqtSignal(str)          # uid
    report_completed   = pyqtSignal(str)          # uid

    def __init__(self, manager: SessionManager):
        super().__init__()
        self._mgr      = manager
        self._cards    = {}           # uid → SessionCard
        self._selected = None         # uid of selected session
        self._compare_a = None
        self._compare_b = None
        self._batch_worker = None     # keep reference to prevent GC

        # Export history log
        from acquisition.export_history import ExportHistory
        hist_path = os.path.join(manager.root, ".export_history.json") if manager.root else ""
        self._export_history = ExportHistory(hist_path)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        splitter.addWidget(self._build_list_panel())

        # Right side: stacked widget — empty state vs detail view
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._build_empty_state())   # idx 0
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)
        detail_scroll.setWidget(self._build_detail_panel())
        self._right_stack.addWidget(detail_scroll)               # idx 1
        self._right_stack.setCurrentIndex(0)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([320, 900])

    # ---------------------------------------------------------------- #
    #  Theme refresh                                                    #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        P   = PALETTE
        bg  = P['bg']
        bdr = P['border']
        dim = P.get("textDim", PALETTE['textDim'])
        txt = P['text']
        # Inline-styled notes editor — the most visibly affected widget
        if hasattr(self, "_notes_edit"):
            self._notes_edit.setStyleSheet(
                f"background:{bg}; color:{txt}; border:1px solid {bdr}; "
                f"font-size:{FONT['body']}pt; font-family:{MONO_FONT};")
        if hasattr(self, "_trend_chart"):
            self._trend_chart._apply_styles()

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
            scaled_qss(f"font-size:15pt; color:{PALETTE['textDim']}; letter-spacing:2px; "
                       "text-transform:uppercase;"))
        hdr.addWidget(title)
        hdr.addStretch()

        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{PALETTE['textSub']};")
        hdr.addWidget(self._count_lbl)
        lay.addLayout(hdr)

        # Search + status filter
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by label…")
        self._search.textChanged.connect(self._filter_cards)
        lay.addWidget(self._search)

        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "Pending", "Reviewed", "Flagged", "Archived"])
        self._status_filter.setFixedHeight(26)
        self._status_filter.setStyleSheet(
            f"QComboBox {{ background:{PALETTE['surface2']}; "
            f"color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"padding:2px 8px; font-size:{FONT['body']}pt; }}")
        self._status_filter.currentTextChanged.connect(
            lambda _: self._filter_cards(self._search.text()))
        lay.addWidget(self._status_filter)

        # Scrollable card list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border:none; background:{PALETTE['bg']}; }}")

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

        # Batch actions
        batch_row = QHBoxLayout()
        self._batch_report_btn = QPushButton("Batch Report")
        set_btn_icon(self._batch_report_btn, IC.EXPORT_PDF)
        self._package_btn = QPushButton("Package…")
        set_btn_icon(self._package_btn, IC.SAVE_AS)
        self._batch_report_btn.clicked.connect(self._batch_report)
        self._package_btn.clicked.connect(self._package_sessions)
        for b in [self._batch_report_btn, self._package_btn]:
            b.setFixedHeight(28)
            batch_row.addWidget(b)
        lay.addLayout(batch_row)

        return w

    # ---------------------------------------------------------------- #
    #  Empty state (shown when no sessions exist)                       #
    # ---------------------------------------------------------------- #

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)

        # Icon
        try:
            import qtawesome as qta
            icon_lbl = QLabel()
            px = qta.icon(IC.FOLDER, color=PALETTE['textDim']).pixmap(64, 64)
            icon_lbl.setPixmap(px)
            icon_lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(icon_lbl)
        except Exception:
            pass

        lay.addSpacing(12)

        title = QLabel("No sessions yet")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: {FONT.get('title', 16)}pt;"
            f"font-weight: 600;"
            f"color: {PALETTE['textSub']};")
        lay.addWidget(title)

        lay.addSpacing(6)

        desc = QLabel(
            "Complete an acquisition to see your first measurement here.\n"
            "Each session is saved with images, metadata, and notes.")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setMaximumWidth(420)
        desc.setStyleSheet(
            f"font-size: {FONT.get('body', 12)}pt;"
            f"color: {PALETTE['textDim']};")
        lay.addWidget(desc, 0, Qt.AlignCenter)

        lay.addSpacing(16)

        go_btn = QPushButton("  Go to Capture  ")
        go_btn.setObjectName("primary")
        go_btn.setFixedHeight(34)
        go_btn.setCursor(Qt.PointingHandCursor)
        set_btn_icon(go_btn, IC.PLAY, PALETTE['accent'])
        go_btn.clicked.connect(lambda: self.navigate_requested.emit("Capture"))
        lay.addWidget(go_btn, 0, Qt.AlignCenter)

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
                ("ROI",       "roi"),
                ("Operator",  "operator"),
                ("Device ID", "device_id"),
                ("Project",   "project"),
                ("Tags",      "tags")]
        for r, (lbl, key) in enumerate(rows):
            ml.addWidget(self._sub(lbl), r, 0)
            val = QLabel("—")
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{PALETTE['textDim']};")
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
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"font-size:{FONT['body']}pt; font-family:{MONO_FONT};")
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
        self._report_btn   = QPushButton("Generate Report")
        set_btn_icon(self._report_btn, "fa5s.file-pdf")
        self._report_btn.setObjectName("primary")

        # Status transition
        status_row = QHBoxLayout()
        status_lbl = QLabel("Status:")
        status_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; color:{PALETTE['textDim']};")
        self._status_combo = QComboBox()
        self._status_combo.setMaximumWidth(200)
        self._status_combo.addItems(["pending", "reviewed", "flagged", "archived"])
        self._status_combo.setFixedHeight(26)
        self._status_combo.setStyleSheet(
            f"QComboBox {{ background:{PALETTE['surface2']}; "
            f"color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"padding:2px 6px; font-size:{FONT['body']}pt; }}")
        self._status_combo.currentTextChanged.connect(self._on_status_changed)
        status_row.addWidget(status_lbl)
        status_row.addWidget(self._status_combo)

        self._delete_btn   = QPushButton("Delete")
        set_btn_icon(self._delete_btn, "fa5s.trash", PALETTE['danger'])
        self._delete_btn.setObjectName("danger")
        self._cmp_a_btn    = QPushButton("Set as A")
        self._cmp_b_btn    = QPushButton("Set as B")

        for b in [self._rename_btn, self._notes_btn, self._export_btn,
                  self._report_btn]:
            b.setFixedHeight(30)
            cl.addWidget(b)

        cl.addLayout(status_row)

        self._delete_btn.setFixedHeight(30)
        cl.addWidget(self._delete_btn)

        cl.addWidget(self._hline())

        cmp_lbl = QLabel("Compare")
        cmp_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textSub']}; letter-spacing:1px;")
        cl.addWidget(cmp_lbl)

        self._cmp_a_lbl = QLabel("A: —")
        self._cmp_b_lbl = QLabel("B: —")
        for l in [self._cmp_a_lbl, self._cmp_b_lbl]:
            l.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['label']}pt; color:{PALETTE['textSub']};")
            l.setWordWrap(True)

        for b in [self._cmp_a_btn, self._cmp_b_btn]:
            b.setFixedHeight(28)
            cl.addWidget(b)
        cl.addWidget(self._cmp_a_lbl)
        cl.addWidget(self._cmp_b_lbl)

        self._compare_btn = QPushButton("Compare A vs B")
        set_btn_icon(self._compare_btn, "fa5s.exchange-alt", PALETTE['accent'])
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
        self._cmap_combo.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
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

        self._trend_chart = SessionTrendChart()

        img_tabs.addTab(self._pane_cold,      " Cold ")
        img_tabs.addTab(self._pane_hot,       " Hot ")
        img_tabs.addTab(self._pane_diff,      " Difference ")
        img_tabs.addTab(drr_wrapper,          " ΔR/R ")
        img_tabs.addTab(self._pane_cmp,       " Compare ")
        img_tabs.addTab(self._trend_chart,    " Trends ✦ ")

        # Export history tab
        self._history_pane = self._build_history_tab()
        img_tabs.addTab(self._history_pane,   " History ")

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
        self._trend_chart.update_sessions(list(self._mgr.all_metas()))

    def select_latest(self) -> None:
        """Auto-select the most recent session (newest first)."""
        metas = self._mgr.all_metas()
        if metas:
            self._on_card_clicked(metas[0].uid)

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
        self._trend_chart.update_sessions(list(self._mgr.all_metas()))
        # Toggle empty state vs detail view
        self._right_stack.setCurrentIndex(1 if n > 0 else 0)

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
        status_sel = self._status_filter.currentText().lower()
        for uid, card in self._cards.items():
            meta = self._mgr.get_meta(uid)
            text_match = (not text) or (meta and text in meta.label.lower())
            if status_sel == "all":
                status_match = True
            else:
                meta_status = (getattr(meta, "status", "") or "").lower()
                status_match = meta_status == status_sel
            card.setVisible(text_match and status_match)

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
        self._right_stack.setCurrentIndex(1)  # show detail view
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

        # Lab-context fields (gracefully absent on old sessions)
        self._meta_fields["operator"].setText(getattr(meta, "operator", "") or "—")
        self._meta_fields["device_id"].setText(getattr(meta, "device_id", "") or "—")
        self._meta_fields["project"].setText(getattr(meta, "project", "") or "—")
        raw_tags = getattr(meta, "tags", []) or []
        self._meta_fields["tags"].setText(", ".join(raw_tags) if raw_tags else "—")

        # Sync status combo (block signals to avoid premature save)
        self._status_combo.blockSignals(True)
        status_val = getattr(meta, "status", "") or "pending"
        idx = self._status_combo.findText(status_val)
        if idx >= 0:
            self._status_combo.setCurrentIndex(idx)
        self._status_combo.blockSignals(False)

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
        mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
        self._pane_drr.show_array(session.delta_r_over_r, mode=mode, cmap=cmap)
        self._pane_cmp.clear()
        session.unload()   # free memory after display

    def _redisplay_drr(self):
        if self._selected:
            self._load_and_display(self._selected)

    # ---------------------------------------------------------------- #
    #  Actions                                                          #
    # ---------------------------------------------------------------- #

    def _on_status_changed(self, new_status: str):
        """Persist status change and update card badge."""
        if not self._selected:
            return
        self._mgr.update_status(self._selected, new_status)
        card = self._cards.get(self._selected)
        if card:
            card.set_status(new_status)
        self.status_changed.emit(self._selected, new_status)

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

        from ui.widgets.report_dialog import ReportDialog
        dlg = ReportDialog(session_label=session.meta.label, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        report_config = dlg.get_config()

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

        # Load persisted analysis if none active
        if analysis is None:
            analysis = session.load_analysis()

        # Load quality scorecard from session meta
        scorecard = session.meta.quality_scorecard

        try:
            from .report import generate_report_any_format
            import os
            report_path = generate_report_any_format(
                session,
                output_dir       = out_dir,
                calibration      = cal,
                analysis         = analysis,
                report_config    = report_config,
                quality_scorecard= scorecard)
            fmt_label = "HTML" if report_config.format == "html" else "PDF"
            self._record_history(session.meta.uid, session.meta.label,
                                 "report", report_config.format,
                                 report_path, True)
            self.report_completed.emit(session.meta.uid)
            QMessageBox.information(
                self, "Report Generated",
                f"{fmt_label} report saved to:\n{report_path}")
        except Exception as e:
            self._record_history(session.meta.uid, session.meta.label,
                                 "report", report_config.format,
                                 out_dir, False, str(e))
            QMessageBox.critical(
                self, "Report Failed",
                f"Could not generate report:\n{e}")

    def _export(self):
        if not self._selected:
            return

        # ── Format selection dialog with preset support ──────────
        from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QCheckBox
        from acquisition.export import ExportFormat, SessionExporter
        from acquisition.export_presets import (
            list_presets as _list_ep, load_preset as _load_ep,
            save_preset as _save_ep, delete_preset as _del_ep,
            ExportPreset)

        dlg = QDialog(self)
        dlg.setWindowTitle("Export Session")
        dlg.setStyleSheet(scaled_qss(
            f"QDialog {{ background:{PALETTE['bg']}; }} "
            f"QLabel  {{ color:{PALETTE['text']}; font-size:15pt; }} "
            f"QCheckBox {{ color:{PALETTE['text']}; font-size:15pt; }} "
            f"QComboBox {{ background:{PALETTE['surface2']}; "
            f"  color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"  padding:3px 8px; font-size:{FONT['heading']}pt; }} "
            f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['textSub']}; "
            f"  border:1px solid {PALETTE['border']}; border-radius:2px; padding:5px 14px; }} "
            f"QPushButton:hover {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; }}"))
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)

        title = QLabel("Select export formats")
        title.setStyleSheet(scaled_qss(f"font-size:18pt; font-weight:bold; color:{PALETTE['text']};"))
        v.addWidget(title)
        sub = QLabel("All selected formats will be written to a single output folder.")
        sub.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{PALETTE['textDim']};")
        v.addWidget(sub)
        v.addSpacing(4)

        # Preset selector row
        preset_row = QHBoxLayout()
        preset_lbl = QLabel("Preset:")
        preset_lbl.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{PALETTE['textDim']};")
        preset_combo = QComboBox()
        preset_combo.setMaximumWidth(300)
        preset_combo.addItem("Custom")
        preset_combo.addItems(_list_ep())
        preset_combo.setFixedHeight(28)
        save_preset_btn = QPushButton("Save…")
        save_preset_btn.setFixedHeight(28)
        del_preset_btn = QPushButton("Delete")
        del_preset_btn.setFixedHeight(28)
        del_preset_btn.setEnabled(False)
        preset_row.addWidget(preset_lbl)
        preset_row.addWidget(preset_combo)
        preset_row.addWidget(save_preset_btn)
        preset_row.addWidget(del_preset_btn)
        preset_row.addStretch()
        v.addLayout(preset_row)
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
        px_lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['heading']}pt;")
        px_spin = QDoubleSpinBox()
        px_spin.setRange(0, 100)
        px_spin.setValue(0)
        px_spin.setDecimals(4)
        px_spin.setFixedWidth(100)
        px_spin.setStyleSheet(
            f"background:{PALETTE['surface2']}; color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            "padding:3px 6px;")
        px_row.addWidget(px_lbl)
        px_row.addWidget(px_spin)
        px_row.addStretch()
        v.addLayout(px_row)
        v.addSpacing(8)

        # Preset load/save/delete wiring
        fmt_by_value = {f.value: f for f in ExportFormat}

        def _on_preset_selected(name):
            del_preset_btn.setEnabled(name != "Custom")
            if name == "Custom":
                return
            p = _load_ep(name)
            if p is None:
                return
            for fmt, cb in checks.items():
                cb.setChecked(fmt.value in p.formats)
            px_spin.setValue(p.px_per_um)

        def _on_save_preset():
            name, ok = QInputDialog.getText(dlg, "Save Export Preset",
                                            "Preset name:")
            if not ok or not name.strip():
                return
            name = name.strip()
            fmts = [f.value for f, cb in checks.items() if cb.isChecked()]
            _save_ep(ExportPreset(name=name, formats=fmts,
                                  px_per_um=px_spin.value()))
            preset_combo.blockSignals(True)
            if preset_combo.findText(name) < 0:
                preset_combo.addItem(name)
            preset_combo.setCurrentText(name)
            preset_combo.blockSignals(False)
            del_preset_btn.setEnabled(True)

        def _on_del_preset():
            name = preset_combo.currentText()
            if name == "Custom":
                return
            _del_ep(name)
            preset_combo.removeItem(preset_combo.currentIndex())
            preset_combo.setCurrentIndex(0)

        preset_combo.currentTextChanged.connect(_on_preset_selected)
        save_preset_btn.clicked.connect(_on_save_preset)
        del_preset_btn.clicked.connect(_on_del_preset)

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
        _uid = session.meta.uid
        _label = session.meta.label
        _fmt_str = "+".join(f.value for f in selected_fmts)

        def _run():
            ar = session.load_analysis()
            exporter = SessionExporter(session, output_dir=folder,
                                       px_per_um=px_per_um,
                                       analysis_result=ar)
            result = exporter.export(selected_fmts)
            # Record in export history
            self._record_history(_uid, _label, "export", _fmt_str,
                                 folder, result.success,
                                 "; ".join(result.errors.values()) if result.errors else "")
            msg = (f"Exported {result.n_files} file(s) to:\n{folder}"
                   if result.success
                   else f"Export failed:\n"
                        + "\n".join(result.errors.values()))
            if result.success:
                QTimer.singleShot(0, lambda: self.export_completed.emit(_uid))
            QTimer.singleShot(0, lambda: QMessageBox.information(
                self, "Export complete" if result.success else "Export error",
                msg))

        import threading
        from PyQt5.QtCore import QTimer
        threading.Thread(target=_run, daemon=True).start()

    def _batch_report(self):
        """Generate reports for multiple sessions at once."""
        metas = self._mgr.all_metas()
        if not metas:
            QMessageBox.information(self, "No Sessions",
                                    "No sessions available for batch report.")
            return

        # Session selection dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Batch Report Generation")
        dlg.setMinimumSize(560, 480)
        dlg.setStyleSheet(scaled_qss(
            f"QDialog {{ background:{PALETTE['bg']}; }} "
            f"QLabel  {{ color:{PALETTE['text']}; font-size:{FONT['heading']}pt; }} "
            f"QCheckBox {{ color:{PALETTE['text']}; font-size:{FONT['body']}pt; }} "
            f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['textSub']}; "
            f"  border:1px solid {PALETTE['border']}; border-radius:2px; padding:5px 14px; }} "
            f"QPushButton:hover {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; }}"))
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        title = QLabel("Select sessions for batch report")
        title.setStyleSheet(scaled_qss(
            f"font-size:18pt; font-weight:bold; color:{PALETTE['text']};"))
        v.addWidget(title)

        # Select all / none
        sel_row = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_none = QPushButton("Select None")
        sel_all.setFixedHeight(26)
        sel_none.setFixedHeight(26)
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        sel_row.addStretch()
        v.addLayout(sel_row)

        # Session checklist
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_w = QWidget()
        scroll_lay = QVBoxLayout(scroll_w)
        scroll_lay.setSpacing(2)
        session_checks: dict[str, QCheckBox] = {}

        # Determine visible sessions (matching current filter)
        visible_uids = {uid for uid, card in self._cards.items()
                        if card.isVisible()}

        for m in metas:
            cb = QCheckBox(f"{m.label}  ({m.timestamp_str})")
            cb.setChecked(m.uid in visible_uids)
            scroll_lay.addWidget(cb)
            session_checks[m.uid] = cb
        scroll_lay.addStretch()
        scroll.setWidget(scroll_w)
        v.addWidget(scroll)

        sel_all.clicked.connect(
            lambda: [cb.setChecked(True) for cb in session_checks.values()])
        sel_none.clicked.connect(
            lambda: [cb.setChecked(False) for cb in session_checks.values()])

        # Report config (reuse ReportDialog or build inline)
        from ui.widgets.report_dialog import ReportDialog
        v.addWidget(QLabel("Report settings:"))
        from acquisition.report import ReportConfig
        # Simple format selector
        fmt_row = QHBoxLayout()
        from PyQt5.QtWidgets import QRadioButton, QButtonGroup
        fmt_grp = QButtonGroup(dlg)
        r_pdf = QRadioButton("PDF")
        r_html = QRadioButton("HTML")
        r_pdf.setChecked(True)
        r_pdf.setStyleSheet(f"color:{PALETTE['text']};")
        r_html.setStyleSheet(f"color:{PALETTE['text']};")
        fmt_grp.addButton(r_pdf, 0)
        fmt_grp.addButton(r_html, 1)
        fmt_row.addWidget(QLabel("Format:"))
        fmt_row.addWidget(r_pdf)
        fmt_row.addWidget(r_html)
        fmt_row.addStretch()
        v.addLayout(fmt_row)

        from PyQt5.QtWidgets import QDialogButtonBox
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        btns.button(QDialogButtonBox.Ok).setText("Generate Reports")
        v.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        selected_uids = [uid for uid, cb in session_checks.items()
                         if cb.isChecked()]
        if not selected_uids:
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Save Reports To", self._mgr.root)
        if not out_dir:
            return

        rcfg = ReportConfig(
            format="html" if r_html.isChecked() else "pdf")

        # Run in background
        from acquisition.batch_report import BatchReportWorker
        try:
            from hardware.app_state import app_state
            cal = app_state.active_calibration
        except Exception:
            cal = None

        self._batch_worker = BatchReportWorker(
            self._mgr, selected_uids, rcfg, out_dir,
            calibration=cal, parent=self)

        # Progress dialog
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("Generating Reports…")
        progress_dlg.setMinimumWidth(400)
        progress_dlg.setStyleSheet(
            f"QDialog {{ background:{PALETTE['bg']}; }} "
            f"QLabel  {{ color:{PALETTE['text']}; font-size:{FONT['body']}pt; }}")
        pl = QVBoxLayout(progress_dlg)
        progress_label = QLabel(f"0 / {len(selected_uids)}")
        progress_label.setAlignment(Qt.AlignCenter)
        progress_label.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:bold;")
        status_label = QLabel("Starting…")
        pl.addWidget(progress_label)
        pl.addWidget(status_label)
        abort_btn = QPushButton("Abort")
        abort_btn.setFixedHeight(30)
        abort_btn.clicked.connect(self._batch_worker.abort)
        pl.addWidget(abort_btn)

        _count = [0]

        def _on_progress(update):
            _count[0] += 1
            progress_label.setText(
                f"{_count[0]} / {len(selected_uids)}")
            icon = "✓" if update.success else "✗"
            status_label.setText(f"{icon} {update.label}")

        def _on_finished(result):
            progress_dlg.accept()
            QMessageBox.information(
                self, "Batch Report Complete",
                f"Generated {result.ok} report(s) in "
                f"{result.duration_s:.1f}s.\n"
                f"Failed: {result.failed}")

        self._batch_worker.progress.connect(_on_progress)
        self._batch_worker.finished.connect(_on_finished)
        self._batch_worker.start()
        progress_dlg.exec_()

    def _package_sessions(self):
        """Bundle selected sessions into a .zip archive for sharing."""
        metas = self._mgr.all_metas()
        if not metas:
            QMessageBox.information(self, "No Sessions",
                                    "No sessions available to package.")
            return

        # Session selection dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Package Sessions")
        dlg.setMinimumSize(480, 400)
        dlg.setStyleSheet(scaled_qss(
            f"QDialog {{ background:{PALETTE['bg']}; }} "
            f"QLabel  {{ color:{PALETTE['text']}; font-size:{FONT['heading']}pt; }} "
            f"QCheckBox {{ color:{PALETTE['text']}; font-size:{FONT['body']}pt; }} "
            f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['textSub']}; "
            f"  border:1px solid {PALETTE['border']}; border-radius:2px; padding:5px 14px; }} "
            f"QPushButton:hover {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; }}"))
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        title = QLabel("Select sessions to package")
        title.setStyleSheet(scaled_qss(
            f"font-size:18pt; font-weight:bold; color:{PALETTE['text']};"))
        v.addWidget(title)

        # Session checklist
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_w = QWidget()
        scroll_lay = QVBoxLayout(scroll_w)
        scroll_lay.setSpacing(2)
        session_checks: dict[str, QCheckBox] = {}
        visible_uids = {uid for uid, card in self._cards.items()
                        if card.isVisible()}
        for m in metas:
            cb = QCheckBox(f"{m.label}  ({m.timestamp_str})")
            cb.setChecked(m.uid in visible_uids)
            scroll_lay.addWidget(cb)
            session_checks[m.uid] = cb
        scroll_lay.addStretch()
        scroll.setWidget(scroll_w)
        v.addWidget(scroll)

        # Description field
        desc_lbl = QLabel("Description (optional):")
        desc_lbl.setStyleSheet(f"font-size:{FONT['body']}pt; color:{PALETTE['textDim']};")
        v.addWidget(desc_lbl)
        from PyQt5.QtWidgets import QTextEdit as _QTE
        desc_edit = _QTE()
        desc_edit.setMaximumHeight(60)
        desc_edit.setStyleSheet(
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; "
            f"border:1px solid {PALETTE['border']}; font-size:{FONT['body']}pt;")
        v.addWidget(desc_edit)

        from PyQt5.QtWidgets import QDialogButtonBox
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        btns.button(QDialogButtonBox.Ok).setText("Package…")
        v.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        selected_uids = [uid for uid, cb in session_checks.items()
                         if cb.isChecked()]
        if not selected_uids:
            return

        # Choose output path
        default_name = f"session_package_{len(selected_uids)}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Package", default_name,
            "ZIP Archives (*.zip)")
        if not path:
            return

        # Run in background
        from acquisition.session_packager import SessionPackager
        import config as _cfg

        def _run():
            from PyQt5.QtCore import QTimer
            try:
                packager = SessionPackager(self._mgr)
                creator = _cfg.get_pref("lab.active_operator", "")
                result_path = packager.package(
                    selected_uids, path,
                    description=desc_edit.toPlainText().strip(),
                    creator=creator)
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, "Package Created",
                    f"Packaged {len(selected_uids)} session(s) to:\n{result_path}"))
            except Exception as e:
                QTimer.singleShot(0, lambda: QMessageBox.critical(
                    self, "Package Failed", f"Error: {e}"))

        import threading
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
            # Clear previous A badge if different card
            if self._compare_a and self._compare_a != self._selected:
                prev = self._cards.get(self._compare_a)
                if prev:
                    prev.set_compare_slot(None)
            self._compare_a = self._selected
            self._cmp_a_lbl.setText(f"A: {meta.label[:30]}")
        else:
            # Clear previous B badge if different card
            if self._compare_b and self._compare_b != self._selected:
                prev = self._cards.get(self._compare_b)
                if prev:
                    prev.set_compare_slot(None)
            self._compare_b = self._selected
            self._cmp_b_lbl.setText(f"B: {meta.label[:30]}")

        # Set badge on the newly assigned card (may overwrite if same card gets both)
        card = self._cards.get(self._selected)
        if card:
            card.set_compare_slot(slot)

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
        mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
        self._pane_cmp.show_array(diff, mode=mode, cmap=cmap)

        ma = self._mgr.get_meta(self._compare_a)
        mb = self._mgr.get_meta(self._compare_b)
        if ma is not None and mb is not None:
            self._pane_cmp._title.setText(
                f"A: {ma.label[:20]}  −  B: {mb.label[:20]}")

    # ---------------------------------------------------------------- #
    #  Export history                                                    #
    # ---------------------------------------------------------------- #

    def _build_history_tab(self) -> QWidget:
        from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Recent export / report / package activity"))
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(24)
        refresh_btn.clicked.connect(self._refresh_history)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear_history)
        hdr.addStretch()
        hdr.addWidget(refresh_btn)
        hdr.addWidget(clear_btn)
        lay.addLayout(hdr)

        self._history_table = QTableWidget(0, 6)
        self._history_table.setHorizontalHeaderLabels(
            ["Date", "Session", "Action", "Format", "Path", "Status"])
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self._history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setStyleSheet(
            f"QTableWidget {{ background:{PALETTE['bg']}; "
            f"color:{PALETTE['text']}; gridline-color:{PALETTE['border']}; "
            f"font-size:{FONT['body']}pt; }} "
            f"QHeaderView::section {{ background:{PALETTE['surface']}; "
            f"color:{PALETTE['textDim']}; border:1px solid {PALETTE['border']}; "
            f"padding:3px; font-size:{FONT['label']}pt; }}")
        lay.addWidget(self._history_table)
        return w

    def _refresh_history(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        records = self._export_history.recent(50)
        self._history_table.setRowCount(len(records))
        for i, rec in enumerate(records):
            ts = rec.timestamp[:19].replace("T", " ") if rec.timestamp else ""
            self._history_table.setItem(i, 0, QTableWidgetItem(ts))
            self._history_table.setItem(i, 1, QTableWidgetItem(rec.session_label))
            self._history_table.setItem(i, 2, QTableWidgetItem(rec.action))
            self._history_table.setItem(i, 3, QTableWidgetItem(rec.format))
            self._history_table.setItem(i, 4, QTableWidgetItem(rec.output_path))
            status = "OK" if rec.success else f"FAIL: {rec.error}"
            self._history_table.setItem(i, 5, QTableWidgetItem(status))

    def _clear_history(self):
        self._export_history.clear()
        self._history_table.setRowCount(0)

    def _record_history(self, session_uid: str, session_label: str,
                        action: str, fmt: str, output_path: str,
                        success: bool, error: str = ""):
        """Helper to add an export history record."""
        from acquisition.export_history import make_record
        self._export_history.add(make_record(
            session_uid, session_label, action, fmt, output_path, success, error))

    # ---------------------------------------------------------------- #
    #  Folder management                                                #
    # ---------------------------------------------------------------- #

    def _set_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Sessions Folder",
            self._mgr.root if self._mgr.root else ".")
        if d:
            self._mgr.root = d
            self._export_history.path = os.path.join(d, ".export_history.json")
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
        f.setStyleSheet(f"color:{PALETTE['border']};")
        return f
