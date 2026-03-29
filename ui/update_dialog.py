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
from ui.theme import FONT, scaled_qss, MONO_FONT

log = logging.getLogger(__name__)

# ── Shared style constants ────────────────────────────────────────────────────

_BG        = "#0e1120"
_BG2       = "#13172a"
_BORDER    = "#1e2337"
_TEXT      = "#c0c8e0"
_MUTED     = "#8892a4"
_ACCENT    = "#4e73df"
_GREEN     = "#00d4aa"
_AMBER     = "#f5a623"
_RED       = "#ff4444"

_BTN_PRIMARY = f"""
    QPushButton {{
        background:{_ACCENT}; color:#fff; border:none;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:#3a5fc8; }}
    QPushButton:pressed {{ background:#2e4fa8; }}
"""
_BTN_SECONDARY = f"""
    QPushButton {{
        background:{_BG2}; color:{_MUTED}; border:1px solid {_BORDER};
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt;
    }}
    QPushButton:hover   {{ background:#1e2540; color:{_TEXT}; }}
    QPushButton:pressed {{ background:#1a1f33; }}
"""
_BTN_AMBER = f"""
    QPushButton {{
        background:{_AMBER}; color:#1a1200; border:none;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:700;
    }}
    QPushButton:hover   {{ background:#e6961a; }}
    QPushButton:pressed {{ background:#cc8615; }}
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
        self.setStyleSheet(f"""
            QPushButton {{
                background:{_AMBER}22; color:{_AMBER};
                border:1px solid {_AMBER}66; border-radius:4px;
                font-size:{FONT["label"]}pt; font-weight:700; padding:0 10px;
            }}
            QPushButton:hover {{
                background:{_AMBER}44; border-color:{_AMBER};
            }}
        """)
        self.setToolTip("A newer version of SanjINSIGHT is available — click for details")
        self.clicked.connect(self._on_click)

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
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }} QLabel {{ background:transparent; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header band ───────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{_AMBER}18; border-bottom:1px solid {_AMBER}44;")
        hdr.setFixedHeight(80)
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(30, 0, 30, 0)

        icon = QLabel("↑")
        icon.setStyleSheet(scaled_qss(f"font-size:30pt; color:{_AMBER}; font-weight:700;"))
        hdr_lay.addWidget(icon)
        hdr_lay.addSpacing(16)

        title_col = QVBoxLayout()
        t1 = QLabel(f"Update available for {APP_NAME}")
        t1.setStyleSheet(scaled_qss(f"font-size:15pt; font-weight:700; color:#fff;"))
        t2 = QLabel(f"v{__version__}  →  v{info.version}")
        t2.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_AMBER};")
        title_col.addWidget(t1)
        title_col.addWidget(t2)
        hdr_lay.addLayout(title_col, 1)

        if info.is_prerelease:
            pre = QLabel("PRE-RELEASE")
            pre.setStyleSheet(
                f"background:{_RED}22; color:{_RED}; border:1px solid {_RED}66; "
                f"border-radius:4px; font-size:{FONT['caption']}pt; font-weight:700; padding:2px 6px;")
            hdr_lay.addWidget(pre)

        root.addWidget(hdr)

        # ── Release notes ─────────────────────────────────────────────
        notes_area = QWidget()
        notes_area.setStyleSheet(f"background:{_BG};")
        notes_lay = QVBoxLayout(notes_area)
        notes_lay.setContentsMargins(30, 20, 30, 10)

        rn_title = QLabel("What's new:")
        rn_title.setStyleSheet(f"font-size:{FONT['label']}pt; font-weight:700; color:{_TEXT};")
        notes_lay.addWidget(rn_title)

        rn_text = QTextEdit()
        rn_text.setReadOnly(True)
        rn_text.setPlainText(info.release_notes or "No release notes available.")
        rn_text.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2}; color:{_MUTED};
                border:1px solid {_BORDER}; border-radius:4px;
                font-size:{FONT["label"]}pt; padding:10px;
                font-family:{MONO_FONT};
            }}
        """)
        rn_text.setMinimumHeight(200)
        notes_lay.addWidget(rn_text)

        root.addWidget(notes_area, 1)

        # ── Separator ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER};")
        root.addWidget(sep)

        # ── Button row ────────────────────────────────────────────────
        btn_row = QWidget()
        btn_row.setFixedHeight(60)
        btn_row.setStyleSheet(f"background:{_BG2};")
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(30, 0, 30, 0)
        btn_lay.setSpacing(10)

        view_btn = QPushButton("View Release on GitHub")
        view_btn.setStyleSheet(_BTN_SECONDARY)
        view_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(info.release_url)))
        btn_lay.addWidget(view_btn)

        btn_lay.addStretch(1)

        remind_btn = QPushButton("Remind Me Later")
        remind_btn.setStyleSheet(_BTN_SECONDARY)
        remind_btn.clicked.connect(self.reject)
        btn_lay.addWidget(remind_btn)

        download_btn = QPushButton(f"⬇  Download v{info.version}")
        download_btn.setStyleSheet(_BTN_AMBER)
        download_btn.clicked.connect(self._on_download)
        btn_lay.addWidget(download_btn)

        root.addWidget(btn_row)

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
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }} QLabel {{ background:transparent; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(100)
        hdr.setStyleSheet(f"background:{_BG2}; border-bottom:1px solid {_BORDER};")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(30, 16, 30, 16)
        hdr_lay.setSpacing(4)

        app_name = QLabel(f"{APP_VENDOR}  {APP_NAME}")
        app_name.setStyleSheet(
            scaled_qss("font-size:18pt; font-weight:700; color:#fff; letter-spacing:1px;"))
        hdr_lay.addWidget(app_name)

        ver_lbl = QLabel(full_version_string())
        ver_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_GREEN};")
        hdr_lay.addWidget(ver_lbl)

        root.addWidget(hdr)

        # ── Tabbed body ───────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {_BORDER}; background: {_BG};
            }}
            QTabBar::tab {{
                background: {_BG2}; color: {_MUTED};
                padding: 6px 18px; border: 1px solid {_BORDER};
                border-bottom: none; margin-right: 2px;
            }}
            QTabBar::tab:selected {{ background: {_BG}; color: #fff; }}
        """)

        # ── "About" tab ───────────────────────────────────────────────
        about_widget = QWidget()
        about_lay = QVBoxLayout(about_widget)
        about_lay.setContentsMargins(20, 16, 20, 10)
        about_lay.setSpacing(6)

        self._sys_info = self._build_sys_info()

        info_box = QTextEdit()
        info_box.setReadOnly(True)
        info_box.setPlainText(self._sys_info)
        info_box.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2}; color:{_MUTED};
                border:1px solid {_BORDER}; border-radius:4px;
                font-size:{FONT["sublabel"]}pt; padding:10px;
                font-family:{MONO_FONT};
            }}
        """)
        info_box.setFixedHeight(170)
        about_lay.addWidget(info_box)

        copy_btn = QPushButton("📋  Copy Info to Clipboard  (for support tickets)")
        copy_btn.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:6px 14px"))
        copy_btn.setToolTip(
            "Copies version + system info to clipboard so you can paste it\n"
            "into a support ticket or email to " + SUPPORT_EMAIL)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        about_lay.addWidget(copy_btn)
        about_lay.addStretch(1)

        tabs.addTab(about_widget, "About")

        # ── "Shortcuts" tab ───────────────────────────────────────────
        tabs.addTab(self._build_shortcuts_tab(), "Keyboard Shortcuts")

        root.addWidget(tabs, 1)

        # ── Separator ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER};")
        root.addWidget(sep)

        # ── Footer links ──────────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(56)
        footer.setStyleSheet(f"background:{_BG2};")
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(30, 0, 30, 0)
        foot_lay.setSpacing(12)

        def _link(text, url):
            btn = QPushButton(text)
            btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{_ACCENT}; border:none; "
                f"font-size:{FONT['label']}pt; text-decoration:underline; }}"
                f"QPushButton:hover {{ color:#6b8ef7; }}")
            btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            return btn

        foot_lay.addWidget(_link("Documentation", DOCS_URL))
        foot_lay.addWidget(_link("Releases", RELEASES_PAGE_URL))

        foot_lay.addStretch(1)

        support_lbl = QLabel(f"Support: {SUPPORT_EMAIL}")
        support_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        foot_lay.addWidget(support_lbl)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:6px 16px"))
        close_btn.clicked.connect(self.accept)
        foot_lay.addWidget(close_btn)

        root.addWidget(footer)

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
                background:{_BG}; alternate-background-color:{_BG2};
                border:none; font-size:{FONT["sublabel"]}pt; color:{_MUTED};
                selection-background-color:#252525; outline:none;
            }}
            QHeaderView::section {{
                background:{_BG2}; color:#555;
                padding:4px 8px; border:none;
                border-bottom:1px solid {_BORDER};
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
