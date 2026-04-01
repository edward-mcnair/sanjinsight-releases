"""
ui/dialogs/bundle_dialog.py

BundleDialog — non-blocking UI for creating a diagnostic support bundle.

The dialog lets the user choose a destination path, then kicks off a
:class:`BundleWorker` QThread to assemble the zip without blocking the
UI.  Progress is shown in a status label; on completion a "Show in
Finder / Explorer" button appears.

Accessible from:  Help → Create Support Bundle…
"""
from __future__ import annotations

import os
import sys
import logging

from PyQt5.QtCore    import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QProgressBar, QFrame, QSizePolicy,
)

from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)

_PT = FONT.get("body", 12)


def _btn_primary(text: str) -> QPushButton:
    btn = QPushButton(text)
    cta  = PALETTE['cta']
    ctah = PALETTE['ctaHover']
    ctad = PALETTE['ctaDim']
    pt   = FONT.get("body", 13)
    btn.setStyleSheet(
        f"QPushButton {{ background:{cta}; color:{PALETTE['textOnAccent']}; border:none; "
        f"border-radius:4px; padding:5px 16px; font-size:{pt}pt; font-weight:600; }}"
        f"QPushButton:hover   {{ background:{ctah}; }}"
        f"QPushButton:pressed {{ background:{cta}; }}"
        f"QPushButton:disabled {{ background:{ctad}; color:{PALETTE['textOnAccent']}66; }}"
    )
    return btn


def _btn_secondary(text: str) -> QPushButton:
    btn = QPushButton(text)
    s    = PALETTE['surface3']
    sh   = PALETTE['surfaceHover']
    d    = PALETTE['border']
    t    = PALETTE['textDim']
    tn   = PALETTE['text']
    pt   = FONT.get("body", 13)
    btn.setStyleSheet(
        f"QPushButton {{ background:{s}; color:{t}; border:1px solid {d}; "
        f"border-radius:4px; padding:5px 16px; font-size:{pt}pt; }}"
        f"QPushButton:hover   {{ background:{sh}; color:{tn}; }}"
        f"QPushButton:pressed {{ background:{d}; }}"
        f"QPushButton:disabled {{ color:{d}; border-color:{d}; }}"
    )
    return btn


class BundleDialog(QDialog):
    """
    Dialog for creating a diagnostic support bundle zip.

    Parameters
    ----------
    device_manager : DeviceManager | None
        Passed to BundleWorker for the device inventory section.
    parent : QWidget, optional
    """

    def __init__(self, device_manager=None, parent=None):
        super().__init__(parent)
        self._dm     = device_manager
        self._worker = None

        self.setWindowTitle("Create Support Bundle")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background:{PALETTE['surface']}; "
            f"color:{PALETTE['text']}; }}"
            f"QLabel  {{ color:{PALETTE['text']}; background:transparent; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("Create Support Bundle")
        title.setStyleSheet(
            f"font-size:{FONT.get('heading', 15)}pt; font-weight:700; "
            f"color:{PALETTE['accent']};"
        )
        lay.addWidget(title)

        intro = QLabel(
            "Creates a <b>.zip</b> archive containing your system information, "
            "application log, device inventory, event timeline, and sanitised "
            "configuration.  No passwords or credentials are included.<br><br>"
            "Attach the file to a support email using "
            "<b>Help → Get Support…</b>"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT.get('label', 11)}pt;"
        )
        lay.addWidget(intro)

        # ── Destination path ──────────────────────────────────────────
        path_row = QHBoxLayout()
        path_lbl = QLabel("Save to:")
        path_lbl.setFixedWidth(60)
        path_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{_PT}pt;"
        )

        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(
            os.path.expanduser("~"), "Desktop",
            f"sanjinsight_bundle_{ts}.zip",
        )
        self._path_edit = QLineEdit(default_path)
        self._path_edit.setStyleSheet(
            f"QLineEdit {{ background:{PALETTE['surface3']}; "
            f"color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"border-radius:3px; padding:4px 6px; font-size:{_PT}pt; }}"
        )

        browse_btn = _btn_secondary("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)

        path_row.addWidget(path_lbl)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse_btn)
        lay.addLayout(path_row)

        # ── Progress ──────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)       # indeterminate
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ border:none; background:{PALETTE['surface3']}; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['accent']}; }}"
        )
        self._progress_bar.setVisible(False)
        lay.addWidget(self._progress_bar)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT.get('label', 11)}pt;"
        )
        lay.addWidget(self._status_lbl)

        # ── Divider ───────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color:{PALETTE['border']};")
        lay.addWidget(div)

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._show_btn = _btn_secondary("Show in Finder")
        self._show_btn.setVisible(False)
        self._show_btn.clicked.connect(self._show_in_explorer)
        btn_row.addWidget(self._show_btn)

        btn_row.addStretch()

        self._close_btn = _btn_secondary("Close")
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)

        btn_row.addSpacing(6)

        self._create_btn = _btn_primary("Create Bundle")
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._start_build)
        btn_row.addWidget(self._create_btn)

        lay.addLayout(btn_row)

        # Adjust "Show in Finder" label for Windows
        if sys.platform == "win32":
            self._show_btn.setText("Show in Explorer")

    # ── Private ───────────────────────────────────────────────────────

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Support Bundle As",
            self._path_edit.text(),
            "Zip Archives (*.zip)",
        )
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self._path_edit.setText(path)

    def _start_build(self) -> None:
        from support.bundle_builder import BundleWorker

        dest = self._path_edit.text().strip()
        if not dest:
            self._status_lbl.setText("Please choose a destination path.")
            return

        self._create_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._show_btn.setVisible(False)
        self._progress_bar.setVisible(True)
        self._status_lbl.setText("Starting …")

        self._worker = BundleWorker(
            device_manager=self._dm,
            dest_path=dest,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._status_lbl.setText(msg)

    def _on_finished(self, path: str) -> None:
        self._bundle_path = path
        self._progress_bar.setVisible(False)
        self._status_lbl.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT.get('label', 11)}pt;"
        )
        self._status_lbl.setText(f"✓  Bundle saved: {path}")
        self._create_btn.setText("Create Again")
        self._create_btn.setEnabled(True)
        self._close_btn.setEnabled(True)
        self._show_btn.setVisible(True)

    def _on_failed(self, msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._status_lbl.setStyleSheet(
            f"color:{PALETTE['danger']}; "
            f"font-size:{FONT.get('label', 11)}pt;"
        )
        self._status_lbl.setText(f"✗  Failed: {msg}")
        self._create_btn.setEnabled(True)
        self._close_btn.setEnabled(True)

    def _show_in_explorer(self) -> None:
        """Reveal the bundle in Finder / Explorer."""
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui  import QDesktopServices
        path = getattr(self, "_bundle_path", self._path_edit.text())
        if sys.platform == "win32":
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
        else:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(path)))
