"""
profiles/download_dialog.py

ProfileDownloadDialog — browse and install profiles from the
Microsanj online profile repository.

Layout
------
Top     : Status bar / error message
Centre  : Table of available profiles (name, category, version,
          wavelength, description, status)
Bottom  : Select All / Deselect All  |  Download Selected  |  Close

Network calls run in a QThread so the UI stays responsive.
"""

from __future__ import annotations
import threading
from typing import List, Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QAbstractItemView, QCheckBox, QWidget, QFrame, QMessageBox,
    QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui  import QColor, QFont

from .downloader import ProfileDownloader, RemoteProfileEntry, DownloadResult
from .profiles   import CATEGORY_ACCENTS


# ------------------------------------------------------------------ #
#  Worker signals (so background thread can talk to Qt safely)        #
# ------------------------------------------------------------------ #

class _WorkerSignals(QObject):
    progress  = pyqtSignal(str)
    index_done= pyqtSignal(list)   # List[RemoteProfileEntry]
    dl_done   = pyqtSignal(list)   # List[DownloadResult]
    error     = pyqtSignal(str)


# ------------------------------------------------------------------ #
#  Dialog                                                             #
# ------------------------------------------------------------------ #

class ProfileDownloadDialog(QDialog):

    # Emitted after successful downloads so the parent can refresh
    profiles_installed = pyqtSignal(list)   # List[str] of UIDs

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Microsanj Profile Repository")
        self.setMinimumSize(820, 520)
        self.setModal(True)

        self._mgr        = manager
        self._downloader = ProfileDownloader(manager)
        self._entries: List[RemoteProfileEntry] = []
        self._signals    = _WorkerSignals()
        self._busy       = False

        self._signals.progress.connect(self._on_progress)
        self._signals.index_done.connect(self._on_index)
        self._signals.dl_done.connect(self._on_dl_done)
        self._signals.error.connect(self._on_error)

        self._build_ui()
        self._fetch_index()

    # ---------------------------------------------------------------- #
    #  UI                                                               #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ---- Header ----
        hdr = QWidget()
        hdr.setStyleSheet(
            "background:#0d1f19; border-radius:4px; padding:2px;")
        hdr.setFixedHeight(46)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        icon = QLabel("🌐")
        icon.setStyleSheet("font-size:25pt;")
        title = QLabel("Microsanj Online Profile Repository")
        title.setStyleSheet(
            "font-size:18pt; color:#ccc; font-weight:bold;")
        sub = QLabel("Browse and install certified material profiles")
        sub.setStyleSheet("font-size:13pt; color:#555;")
        hl.addWidget(icon)
        hl.addSpacing(8)
        vl = QVBoxLayout()
        vl.setSpacing(0)
        vl.addWidget(title)
        vl.addWidget(sub)
        hl.addLayout(vl)
        hl.addStretch()
        lay.addWidget(hdr)

        # ---- Status bar ----
        self._status_lbl = QLabel("Fetching profile list…")
        self._status_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:13pt; color:#555;")
        lay.addWidget(self._status_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)   # indeterminate
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        lay.addWidget(self._progress_bar)

        # ---- Table ----
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["", "Name", "Category", "Ver.", "λ (nm)", "Status"])
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background:#141414; alternate-background-color:#181818;
                gridline-color:#222; border:none;
            }
            QHeaderView::section {
                background:#1a1a1a; color:#555;
                padding:4px 8px; border:none; border-bottom:1px solid #2a2a2a;
                font-size:12pt; letter-spacing:1px;
            }
        """)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setColumnWidth(0, 32)
        self._table.setColumnWidth(3, 46)
        self._table.setColumnWidth(4, 58)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setToolTip(
            "Check profiles to download. Already-installed profiles are greyed out.")
        lay.addWidget(self._table)

        # ---- Description panel ----
        self._desc_lbl = QLabel("")
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet(
            "font-size:13pt; color:#555; padding:4px;")
        self._desc_lbl.setFixedHeight(38)
        lay.addWidget(self._desc_lbl)

        # ---- Buttons ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#222;")
        lay.addWidget(sep)

        btn_row = QHBoxLayout()

        self._sel_all_btn   = QPushButton("☑  Select All New")
        self._desel_btn     = QPushButton("☐  Deselect All")
        self._refresh_btn   = QPushButton("↻  Refresh")
        self._download_btn  = QPushButton("⬇  Download Selected")
        self._download_btn.setObjectName("primary")
        self._download_btn.setFixedHeight(34)
        self._close_btn     = QPushButton("Close")

        for b in [self._sel_all_btn, self._desel_btn, self._refresh_btn]:
            b.setFixedHeight(28)
            btn_row.addWidget(b)

        btn_row.addStretch()
        btn_row.addWidget(self._download_btn)
        btn_row.addWidget(self._close_btn)
        lay.addLayout(btn_row)

        self._sel_all_btn.clicked.connect(self._select_all_new)
        self._desel_btn.clicked.connect(self._deselect_all)
        self._refresh_btn.clicked.connect(self._fetch_index)
        self._download_btn.clicked.connect(self._download_selected)
        self._close_btn.clicked.connect(self.accept)

        self._set_busy(True)

    # ---------------------------------------------------------------- #
    #  Network — runs in background thread                              #
    # ---------------------------------------------------------------- #

    def _fetch_index(self):
        self._set_busy(True)
        self._table.setRowCount(0)
        self._status_lbl.setText("Connecting to Microsanj profile repository…")

        def run():
            try:
                entries = self._downloader.fetch_index(
                    progress_cb=self._signals.progress.emit)
                self._signals.index_done.emit(entries)
            except Exception as e:
                self._signals.error.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _download_selected(self):
        to_download = [
            self._entries[r]
            for r in range(self._table.rowCount())
            if self._row_checkbox(r).isChecked()
        ]
        if not to_download:
            QMessageBox.information(self, "Nothing selected",
                                    "Check at least one profile to download.")
            return

        self._set_busy(True)
        self._status_lbl.setText(
            f"Downloading {len(to_download)} profile(s)…")

        def run():
            results = self._downloader.download_many(
                to_download,
                progress_cb=self._signals.progress.emit)
            self._signals.dl_done.emit(results)

        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- #
    #  Slots                                                            #
    # ---------------------------------------------------------------- #

    def _on_progress(self, msg: str):
        self._status_lbl.setText(msg)

    def _on_index(self, entries: List[RemoteProfileEntry]):
        self._entries = entries
        self._populate_table(entries)
        n_new = sum(1 for e in entries if not e.already_installed)
        self._status_lbl.setText(
            f"{len(entries)} profiles available  ·  "
            f"{n_new} not yet installed")
        self._set_busy(False)

    def _on_dl_done(self, results: List[DownloadResult]):
        ok  = [r for r in results if r.success]
        err = [r for r in results if not r.success]

        if ok:
            self.profiles_installed.emit([r.uid for r in ok])

        self._set_busy(False)
        self._fetch_index()   # refresh to update "installed" status

        msg = f"✓  {len(ok)} profile(s) installed."
        if err:
            msg += f"\n✗  {len(err)} failed:\n"
            msg += "\n".join(f"  • {r.uid}: {r.error}" for r in err)
            QMessageBox.warning(self, "Download Results", msg)
        else:
            self._status_lbl.setText(msg)

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._status_lbl.setText("⚠  Could not reach profile server.")
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        QMessageBox.critical(
            self, "Connection Error",
            f"{msg}\n\nMake sure you are connected to the internet "
            f"and try again.\n\nIf the problem persists, contact "
            f"Microsanj support at support@microsanj.com")

    # ---------------------------------------------------------------- #
    #  Table                                                            #
    # ---------------------------------------------------------------- #

    def _populate_table(self, entries: List[RemoteProfileEntry]):
        self._table.setRowCount(0)
        for entry in entries:
            r = self._table.rowCount()
            self._table.insertRow(r)

            # Checkbox
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(6, 0, 0, 0)
            cb = QCheckBox()
            cb.setChecked(not entry.already_installed)
            cb.setEnabled(not entry.already_installed)
            cb_layout.addWidget(cb)
            self._table.setCellWidget(r, 0, cb_widget)

            # Name
            name_item = QTableWidgetItem(entry.name)
            name_item.setFont(QFont("Helvetica", 14))
            if entry.already_installed:
                name_item.setForeground(QColor("#444"))
            else:
                name_item.setForeground(QColor("#ccc"))
            self._table.setItem(r, 1, name_item)

            # Category
            accent = CATEGORY_ACCENTS.get(entry.category, "#555")
            cat_item = QTableWidgetItem(entry.category)
            cat_item.setForeground(
                QColor("#444") if entry.already_installed
                else QColor(accent))
            cat_item.setFont(QFont("Helvetica", 12))
            self._table.setItem(r, 2, cat_item)

            # Version
            ver_item = QTableWidgetItem(f"v{entry.version}")
            ver_item.setTextAlignment(Qt.AlignCenter)
            ver_item.setForeground(QColor("#555"))
            self._table.setItem(r, 3, ver_item)

            # Wavelength
            wl_item = QTableWidgetItem(str(entry.wavelength_nm))
            wl_item.setTextAlignment(Qt.AlignCenter)
            wl_item.setForeground(QColor("#555"))
            self._table.setItem(r, 4, wl_item)

            # Status
            if entry.already_installed:
                status_item = QTableWidgetItem("✓  Installed")
                status_item.setForeground(QColor("#2a6a4a"))
            else:
                status_item = QTableWidgetItem("Available")
                status_item.setForeground(QColor("#4a8a6a"))
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setFont(QFont("Menlo", 12))
            self._table.setItem(r, 5, status_item)

            self._table.setRowHeight(r, 30)

            # Show description on row click
            name_item.setToolTip(entry.description)
            cat_item.setToolTip(entry.description)

        self._table.itemClicked.connect(self._on_row_click)

    def _on_row_click(self, item):
        r = item.row()
        if 0 <= r < len(self._entries):
            self._desc_lbl.setText(self._entries[r].description)

    # ---------------------------------------------------------------- #
    #  Selection helpers                                                #
    # ---------------------------------------------------------------- #

    def _row_checkbox(self, row: int) -> QCheckBox:
        widget = self._table.cellWidget(row, 0)
        return widget.findChild(QCheckBox)

    def _select_all_new(self):
        for r in range(self._table.rowCount()):
            cb = self._row_checkbox(r)
            if cb and cb.isEnabled():
                cb.setChecked(True)

    def _deselect_all(self):
        for r in range(self._table.rowCount()):
            cb = self._row_checkbox(r)
            if cb:
                cb.setChecked(False)

    # ---------------------------------------------------------------- #
    #  Busy state                                                       #
    # ---------------------------------------------------------------- #

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._progress_bar.setRange(0, 0 if busy else 1)
        self._progress_bar.setValue(0 if busy else 1)
        self._download_btn.setEnabled(not busy)
        self._refresh_btn.setEnabled(not busy)
        self._sel_all_btn.setEnabled(not busy)
        self._desel_btn.setEnabled(not busy)
