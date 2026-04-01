"""
ui/update_dialog.py

Three UI components for the SanjINSIGHT update system:

  UpdateBadge      — compact header button that glows amber when an update is ready
  UpdateDialog     — full dialog shown when the user clicks the badge or "Check Now"
  AboutDialog      — Help → About  (version, system info, copy-for-support button)
"""

from __future__ import annotations

import platform
import sys
import os
import logging
from typing import Optional

from PyQt5.QtCore    import Qt, QUrl, pyqtSignal
from PyQt5.QtGui     import QDesktopServices, QFont, QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QTextEdit, QSizePolicy, QApplication,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)

from version import (
    __version__, BUILD_DATE, APP_NAME, APP_VENDOR,
    full_version_string, RELEASES_PAGE_URL, SUPPORT_EMAIL, DOCS_URL,
)
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT

log = logging.getLogger(__name__)

# ── Style helpers (read PALETTE at call time for theme-awareness) ─────────────
def _BG():      return PALETTE['bg']
def _BG2():     return PALETTE['surface']
def _BORDER():  return PALETTE['border']
def _TEXT():    return PALETTE['text']
def _MUTED():   return PALETTE['textDim']
def _ACCENT():  return PALETTE['accent']
def _GREEN():   return PALETTE['success']
def _AMBER():   return PALETTE['warning']
def _RED():     return PALETTE['danger']


def _btn_primary():
    return f"""
    QPushButton {{
        background:{_ACCENT()}; color:{PALETTE['textOnAccent']}; border:none;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:{PALETTE['accentHover']}; }}
    QPushButton:pressed {{ background:{PALETTE['accentDim']}; }}
"""

def _btn_secondary():
    return f"""
    QPushButton {{
        background:{_BG2()}; color:{_MUTED()}; border:1px solid {_BORDER()};
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt;
    }}
    QPushButton:hover   {{ background:{PALETTE['surfaceHover']}; color:{_TEXT()}; }}
    QPushButton:pressed {{ background:{PALETTE['surface2']}; }}
"""

def _btn_amber():
    return f"""
    QPushButton {{
        background:{_AMBER()}; color:{PALETTE['textOnWarn']}; border:none;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:700;
    }}
    QPushButton:hover   {{ background:{PALETTE['warning']}cc; }}
    QPushButton:pressed {{ background:{PALETTE['warning']}aa; }}
"""


# ══════════════════════════════════════════════════════════════════════════════
#  UpdateBadge — the amber button that lives in the StatusHeader
# ══════════════════════════════════════════════════════════════════════════════

class UpdateBadge(QPushButton):
    """
    Compact header button that is hidden by default.
    Call show_update(info) to make it visible with the version number.
    Clicking it opens the UpdateDialog.
    """

    clicked_with_info = pyqtSignal(object)   # emits UpdateInfo

    def __init__(self, parent=None):
        super().__init__(parent)
        self._info = None
        self.setFixedHeight(30)
        self.hide()
        self._apply_styles()
        self.setToolTip("A newer version of SanjINSIGHT is available — click for details")
        self.clicked.connect(self._on_click)

    def _apply_styles(self):
        """Re-apply all styles from PALETTE. Called on init and theme switch."""
        self.setStyleSheet(f"""
            QPushButton {{
                background:{_AMBER()}22; color:{_AMBER()};
                border:1px solid {_AMBER()}66; border-radius:4px;
                font-size:{FONT["label"]}pt; font-weight:700; padding:0 10px;
            }}
            QPushButton:hover {{
                background:{_AMBER()}44; border-color:{_AMBER()};
            }}
        """)

    def show_update(self, info) -> None:
        """Make the badge visible with the new version number."""
        self._info = info
        self.setText(f"↑ v{info.version} available")
        self.show()

    def _on_click(self):
        if self._info:
            self.clicked_with_info.emit(self._info)


# ══════════════════════════════════════════════════════════════════════════════
#  UpdateDialog — shown when badge is clicked or "Check Now" triggers a result
# ══════════════════════════════════════════════════════════════════════════════

class UpdateDialog(QDialog):
    """
    Full update information dialog.

    Shows:
      • Current version vs available version
      • Full release notes (Markdown rendered as plain text)
      • Download button (opens browser to GitHub release / installer URL)
      • "Remind me later" dismiss button
    """

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info
        self.setWindowTitle(f"{APP_NAME} — Update Available")
        self.setModal(True)
        self.resize(620, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header band ───────────────────────────────────────────────
        self._hdr = QWidget()
        self._hdr.setFixedHeight(80)
        hdr_lay = QHBoxLayout(self._hdr)
        hdr_lay.setContentsMargins(30, 0, 30, 0)

        self._hdr_icon = QLabel("↑")
        hdr_lay.addWidget(self._hdr_icon)
        hdr_lay.addSpacing(16)

        title_col = QVBoxLayout()
        self._hdr_title = QLabel(f"Update available for {APP_NAME}")
        self._hdr_ver = QLabel(f"v{__version__}  →  v{info.version}")
        title_col.addWidget(self._hdr_title)
        title_col.addWidget(self._hdr_ver)
        hdr_lay.addLayout(title_col, 1)

        self._pre_lbl = None
        if info.is_prerelease:
            self._pre_lbl = QLabel("PRE-RELEASE")
            hdr_lay.addWidget(self._pre_lbl)

        root.addWidget(self._hdr)

        # ── Release notes ─────────────────────────────────────────────
        self._notes_area = QWidget()
        notes_lay = QVBoxLayout(self._notes_area)
        notes_lay.setContentsMargins(30, 20, 30, 10)

        self._rn_title = QLabel("What's new:")
        notes_lay.addWidget(self._rn_title)

        self._rn_text = QTextEdit()
        self._rn_text.setReadOnly(True)
        self._rn_text.setPlainText(info.release_notes or "No release notes available.")
        self._rn_text.setMinimumHeight(200)
        notes_lay.addWidget(self._rn_text)

        root.addWidget(self._notes_area, 1)

        # ── Separator ─────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        root.addWidget(self._sep)

        # ── Button row ────────────────────────────────────────────────
        self._btn_row = QWidget()
        self._btn_row.setFixedHeight(60)
        btn_lay = QHBoxLayout(self._btn_row)
        btn_lay.setContentsMargins(30, 0, 30, 0)
        btn_lay.setSpacing(10)

        self._view_btn = QPushButton("View Release on GitHub")
        self._view_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(info.release_url)))
        btn_lay.addWidget(self._view_btn)

        btn_lay.addStretch(1)

        self._remind_btn = QPushButton("Remind Me Later")
        self._remind_btn.clicked.connect(self.reject)
        btn_lay.addWidget(self._remind_btn)

        self._download_btn = QPushButton(f"⬇  Download v{info.version}")
        self._download_btn.clicked.connect(self._on_download)
        btn_lay.addWidget(self._download_btn)

        root.addWidget(self._btn_row)
        self._apply_styles()

    def _apply_styles(self):
        """Re-apply all styles from PALETTE. Called on init and theme switch."""
        self.setStyleSheet(
            f"QDialog {{ background:{_BG()}; }} QLabel {{ background:transparent; }}")
        self._hdr.setStyleSheet(
            f"background:{_AMBER()}18; border-bottom:1px solid {_AMBER()}44;")
        self._hdr_icon.setStyleSheet(
            scaled_qss(f"font-size:30pt; color:{_AMBER()}; font-weight:700;"))
        self._hdr_title.setStyleSheet(
            scaled_qss(f"font-size:15pt; font-weight:700; color:{PALETTE['text']};"))
        self._hdr_ver.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_AMBER()};")
        if self._pre_lbl:
            self._pre_lbl.setStyleSheet(
                f"background:{_RED()}22; color:{_RED()}; border:1px solid {_RED()}66; "
                f"border-radius:4px; font-size:{FONT['caption']}pt; font-weight:700; padding:2px 6px;")
        self._notes_area.setStyleSheet(f"background:{_BG()};")
        self._rn_title.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; color:{_TEXT()};")
        self._rn_text.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2()}; color:{_MUTED()};
                border:1px solid {_BORDER()}; border-radius:4px;
                font-size:{FONT["label"]}pt; padding:10px;
                font-family:{MONO_FONT};
            }}
        """)
        self._sep.setStyleSheet(f"color:{_BORDER()};")
        self._btn_row.setStyleSheet(f"background:{_BG2()};")
        self._view_btn.setStyleSheet(_btn_secondary())
        self._remind_btn.setStyleSheet(_btn_secondary())
        self._download_btn.setStyleSheet(_btn_amber())

    def _on_download(self):
        QDesktopServices.openUrl(QUrl(self._info.download_url))
        self.accept()


# ══════════════════════════════════════════════════════════════════════════════
#  AboutDialog — Help → About
# ══════════════════════════════════════════════════════════════════════════════

class AboutDialog(QDialog):
    """
    Professional About dialog.

    Shows:
      • App name, version, build date
      • System information (OS, Python, Qt versions)
      • "Copy Info to Clipboard" button — for support tickets
      • Links to documentation and support email
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setModal(True)
        self.setFixedSize(560, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        self._about_hdr = QWidget()
        self._about_hdr.setFixedHeight(100)
        hdr_lay = QVBoxLayout(self._about_hdr)
        hdr_lay.setContentsMargins(30, 16, 30, 16)
        hdr_lay.setSpacing(4)

        self._app_name_lbl = QLabel(f"{APP_VENDOR}  {APP_NAME}")
        hdr_lay.addWidget(self._app_name_lbl)

        self._ver_lbl = QLabel(full_version_string())
        hdr_lay.addWidget(self._ver_lbl)

        root.addWidget(self._about_hdr)

        # ── Tabbed body ───────────────────────────────────────────────
        self._tabs = QTabWidget()

        # ── "About" tab ───────────────────────────────────────────────
        about_widget = QWidget()
        about_lay = QVBoxLayout(about_widget)
        about_lay.setContentsMargins(20, 16, 20, 10)
        about_lay.setSpacing(6)

        self._sys_info = self._build_sys_info()

        self._info_box = QTextEdit()
        self._info_box.setReadOnly(True)
        self._info_box.setPlainText(self._sys_info)
        self._info_box.setFixedHeight(170)
        about_lay.addWidget(self._info_box)

        self._copy_btn = QPushButton("Copy Info to Clipboard  (for support tickets)")
        self._copy_btn.setToolTip(
            "Copies version + system info to clipboard so you can paste it\n"
            "into a support ticket or email to " + SUPPORT_EMAIL)
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        about_lay.addWidget(self._copy_btn)
        about_lay.addStretch(1)

        self._tabs.addTab(about_widget, "About")

        # ── "Shortcuts" tab ───────────────────────────────────────────
        self._tabs.addTab(self._build_shortcuts_tab(), "Keyboard Shortcuts")

        root.addWidget(self._tabs, 1)

        # ── Separator ─────────────────────────────────────────────────
        self._about_sep = QFrame()
        self._about_sep.setFrameShape(QFrame.HLine)
        root.addWidget(self._about_sep)

        # ── Footer links ──────────────────────────────────────────────
        self._about_footer = QWidget()
        self._about_footer.setFixedHeight(56)
        foot_lay = QHBoxLayout(self._about_footer)
        foot_lay.setContentsMargins(30, 0, 30, 0)
        foot_lay.setSpacing(12)

        self._docs_btn = QPushButton("Documentation")
        self._docs_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        foot_lay.addWidget(self._docs_btn)

        self._releases_btn = QPushButton("Releases")
        self._releases_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL)))
        foot_lay.addWidget(self._releases_btn)

        foot_lay.addStretch(1)

        self._support_lbl = QLabel(f"Support: {SUPPORT_EMAIL}")
        foot_lay.addWidget(self._support_lbl)

        self._about_close_btn = QPushButton("Close")
        self._about_close_btn.clicked.connect(self.accept)
        foot_lay.addWidget(self._about_close_btn)

        root.addWidget(self._about_footer)
        self._apply_styles()

    def _apply_styles(self):
        """Re-apply all styles from PALETTE. Called on init and theme switch."""
        self.setStyleSheet(
            f"QDialog {{ background:{_BG()}; }} QLabel {{ background:transparent; }}")
        self._about_hdr.setStyleSheet(
            f"background:{_BG2()}; border-bottom:1px solid {_BORDER()};")
        self._app_name_lbl.setStyleSheet(
            scaled_qss(f"font-size:18pt; font-weight:700; color:{PALETTE['text']}; letter-spacing:1px;"))
        self._ver_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_GREEN()};")
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {_BORDER()}; background: {_BG()};
            }}
            QTabBar::tab {{
                background: {_BG2()}; color: {_MUTED()};
                padding: 6px 18px; border: 1px solid {_BORDER()};
                border-bottom: none; margin-right: 2px;
            }}
            QTabBar::tab:selected {{ background: {_BG()}; color: {PALETTE['text']}; }}
        """)
        self._info_box.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2()}; color:{_MUTED()};
                border:1px solid {_BORDER()}; border-radius:4px;
                font-size:{FONT["sublabel"]}pt; padding:10px;
                font-family:{MONO_FONT};
            }}
        """)
        self._copy_btn.setStyleSheet(
            _btn_secondary().replace("padding:8px 22px", "padding:6px 14px"))
        self._about_sep.setStyleSheet(f"color:{_BORDER()};")
        self._about_footer.setStyleSheet(f"background:{_BG2()};")
        _link_qss = (
            f"QPushButton {{ background:transparent; color:{_ACCENT()}; border:none; "
            f"font-size:{FONT['label']}pt; text-decoration:underline; }}"
            f"QPushButton:hover {{ color:{PALETTE['accentHover']}; }}")
        self._docs_btn.setStyleSheet(_link_qss)
        self._releases_btn.setStyleSheet(_link_qss)
        self._support_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._about_close_btn.setStyleSheet(
            _btn_secondary().replace("padding:8px 22px", "padding:6px 16px"))

    # ── Helpers ───────────────────────────────────────────────────────

    def _build_sys_info(self) -> str:
        """Build the system information block shown in the dialog and copied to clipboard."""
        try:
            from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
            qt_ver  = QT_VERSION_STR
            pyqt_ver = PYQT_VERSION_STR
        except Exception:
            qt_ver = pyqt_ver = "unknown"

        import config as cfg_mod
        hw = cfg_mod.get("hardware")
        cam_drv   = hw.get("camera", {}).get("driver", "?")
        fpga_drv  = hw.get("fpga",   {}).get("driver", "?")

        lines = [
            f"Application  : {APP_VENDOR} {APP_NAME}",
            f"Version      : v{__version__}",
            f"Build date   : {BUILD_DATE}",
            f"",
            f"OS           : {platform.system()} {platform.release()} ({platform.machine()})",
            f"Python       : {sys.version.split()[0]}",
            f"Qt           : {qt_ver}",
            f"PyQt5        : {pyqt_ver}",
            f"",
            f"Camera driver: {cam_drv}",
            f"FPGA driver  : {fpga_drv}",
        ]
        return "\n".join(lines)

    def _copy_to_clipboard(self):
        clip = QApplication.clipboard()
        clip.setText(self._sys_info)

        # Brief visual feedback
        sender = self.sender()
        if sender:
            original = sender.text()
            sender.setText("✓ Copied!")
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(1500, lambda: sender.setText(original))

    def _build_shortcuts_tab(self) -> QWidget:
        """Build the Keyboard Shortcuts tab with a categorised table."""
        SHORTCUTS = [
            # (Category, Key, Action)
            ("Acquisition", "Ctrl+R",       "Run Sequence (Acquire tab)"),
            ("Acquisition", "Escape",        "Abort current operation"),
            ("Acquisition", "F5",            "Start Live Stream"),
            ("Acquisition", "F6",            "Stop Live Stream"),
            ("Acquisition", "F7",            "Freeze / Resume live display"),
            ("Acquisition", "F8",            "Run Analysis"),
            ("Acquisition", "F9",            "Start / Stop Scan"),
            ("Navigation",  "Ctrl+L",        "Switch to Live tab"),
            ("Navigation",  "Ctrl+Shift+S",  "Switch to Scan tab"),
            ("Navigation",  "Ctrl+1",        "Switch to Acquire tab"),
            ("Navigation",  "Ctrl+2",        "Switch to Camera tab"),
            ("Navigation",  "Ctrl+3",        "Switch to Temperature tab"),
            ("Navigation",  "Ctrl+4",        "Switch to Stage tab"),
            ("Navigation",  "Ctrl+5",        "Switch to Analysis tab"),
            ("Hardware",    "Ctrl+D",        "Open Device Manager"),
            ("Hardware",    "Ctrl+Shift+H",  "Hardware Setup Wizard"),
            ("Safety",      "Ctrl+.",        "Emergency Stop"),
            ("App",         "Ctrl+,",        "Open Settings"),
        ]

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(4)

        table = QTableWidget(len(SHORTCUTS), 3)
        table.setHorizontalHeaderLabels(["Category", "Shortcut", "Action"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.NoFocus)
        table.setStyleSheet(f"""
            QTableWidget {{
                background:{_BG()}; alternate-background-color:{_BG2()};
                border:none; font-size:{FONT["sublabel"]}pt; color:{_MUTED()};
                selection-background-color:{PALETTE['selectionBg']}; outline:none;
            }}
            QHeaderView::section {{
                background:{_BG2()}; color:{PALETTE['textDim']};
                padding:4px 8px; border:none;
                border-bottom:1px solid {_BORDER()};
            }}
        """)
        mono = QFont("Menlo, Consolas, monospace")
        mono.setPointSize(11)
        for row, (section, key, action) in enumerate(SHORTCUTS):
            for col, val in enumerate([section, key, action]):
                item = QTableWidgetItem(val)
                if col == 1:
                    item.setFont(mono)
                table.setItem(row, col, item)

        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.resizeRowsToContents()
        lay.addWidget(table)
        return w
