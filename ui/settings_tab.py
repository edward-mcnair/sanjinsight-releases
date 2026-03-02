"""
ui/settings_tab.py

Settings Tab
============
Provides user-configurable preferences for SanjINSIGHT.

Sections
--------
  • Software Updates   — auto-check on/off, frequency, channel, manual Check Now
  • Appearance         — (placeholder for future UI prefs)
  • Support            — About dialog shortcut, copy version info

This tab is added to the TOOLS section of the sidebar.
"""

from __future__ import annotations

import logging
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal, QUrl
from PyQt5.QtGui     import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QFrame, QSizePolicy,
    QScrollArea, QSpinBox, QLineEdit, QFileDialog,
)

import config as cfg_mod
from version import (
    __version__, BUILD_DATE, APP_NAME, APP_VENDOR,
    RELEASES_PAGE_URL, SUPPORT_EMAIL, version_string,
)

log = logging.getLogger(__name__)

# ── Style constants ───────────────────────────────────────────────────────────
_BG      = "#0e1120"
_BG2     = "#13172a"
_BORDER  = "#1e2337"
_TEXT    = "#c0c8e0"
_MUTED   = "#8892a4"
_ACCENT  = "#4e73df"
_GREEN   = "#00d4aa"
_AMBER   = "#f5a623"

_BTN_PRIMARY = f"""
    QPushButton {{
        background:{_ACCENT}; color:#fff; border:none;
        border-radius:5px; padding:7px 18px; font-size:12pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:#3a5fc8; }}
    QPushButton:pressed {{ background:#2e4fa8; }}
    QPushButton:disabled{{ background:#222; color:#555; }}
"""
_BTN_SECONDARY = f"""
    QPushButton {{
        background:{_BG2}; color:{_MUTED}; border:1px solid {_BORDER};
        border-radius:5px; padding:7px 18px; font-size:12pt;
    }}
    QPushButton:hover   {{ background:#1e2540; color:{_TEXT}; }}
    QPushButton:pressed {{ background:#1a1f33; }}
"""
_COMBO = f"""
    QComboBox {{
        background:{_BG2}; color:{_TEXT}; border:1px solid {_BORDER};
        border-radius:4px; padding:5px 10px; font-size:12pt;
    }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{ background:{_BG2}; color:{_TEXT}; border:1px solid {_BORDER}; }}
"""
_CHECK = f"""
    QCheckBox {{ color:{_TEXT}; font-size:12pt; spacing:8px; }}
    QCheckBox::indicator {{
        width:18px; height:18px; border-radius:3px;
        border:1px solid {_BORDER}; background:{_BG2};
    }}
    QCheckBox::indicator:checked {{
        background:{_ACCENT}; border-color:{_ACCENT};
    }}
"""


def _h2(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"font-size:13pt; font-weight:700; color:#fff;")
    return l


def _body(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
    l.setWordWrap(True)
    return l


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{_BORDER};")
    return f


def _group(title: str) -> QGroupBox:
    g = QGroupBox(title)
    g.setStyleSheet(f"""
        QGroupBox {{
            color:{_MUTED}; font-size:11pt; font-weight:600;
            border:1px solid {_BORDER}; border-radius:5px;
            margin-top:10px; padding:14px 14px 14px 14px;
        }}
        QGroupBox::title {{
            subcontrol-origin:margin; left:12px; padding:0 6px;
            background:{_BG};
        }}
    """)
    return g


# ══════════════════════════════════════════════════════════════════════════════
#  SettingsTab
# ══════════════════════════════════════════════════════════════════════════════

class SettingsTab(QWidget):
    """
    Settings tab content.  Added to the TOOLS nav section.

    Signals
    -------
    check_for_updates_requested   — emitted when user clicks "Check Now"
    ai_enable_requested(str, int) — (model_path, n_gpu_layers) when user enables AI
    ai_disable_requested          — emitted when user disables AI
    """

    check_for_updates_requested = pyqtSignal()
    ai_enable_requested         = pyqtSignal(str, int)
    ai_disable_requested        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_BG};")

        # Outer scroll area so content works on small screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background:{_BG};")
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(30, 24, 30, 30)
        lay.setSpacing(20)

        # ── Page title ────────────────────────────────────────────────
        pg_title = QLabel("Settings")
        pg_title.setStyleSheet("font-size:20pt; font-weight:700; color:#fff;")
        lay.addWidget(pg_title)

        lay.addWidget(_sep())

        # ── Software version card ─────────────────────────────────────
        lay.addWidget(self._build_version_card())

        # ── Software updates ──────────────────────────────────────────
        lay.addWidget(self._build_updates_group())

        # ── AI Assistant ──────────────────────────────────────────────
        lay.addWidget(self._build_ai_group())

        # ── Support ───────────────────────────────────────────────────
        lay.addWidget(self._build_support_group())

        lay.addStretch(1)

    # ── Section builders ──────────────────────────────────────────────

    def _build_version_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{_BG2}; border:1px solid {_BORDER}; border-radius:6px;")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(0)

        col = QVBoxLayout()
        name_lbl = QLabel(f"{APP_VENDOR}  {APP_NAME}")
        name_lbl.setStyleSheet("font-size:15pt; font-weight:700; color:#fff;")
        col.addWidget(name_lbl)

        ver_lbl = QLabel(f"Version {version_string()}  ·  Built {BUILD_DATE}")
        ver_lbl.setStyleSheet(f"font-size:11pt; color:{_GREEN};")
        col.addWidget(ver_lbl)

        lay.addLayout(col, 1)

        self._update_status_lbl = QLabel("")
        self._update_status_lbl.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._update_status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._update_status_lbl)

        return card

    def _build_updates_group(self) -> QGroupBox:
        g = _group("Software Updates")
        lay = QVBoxLayout(g)
        lay.setSpacing(14)

        # Auto-check toggle
        self._auto_check = QCheckBox("Automatically check for updates on startup")
        self._auto_check.setStyleSheet(_CHECK)
        self._auto_check.setChecked(cfg_mod.get_pref("updates.auto_check", True))
        self._auto_check.toggled.connect(self._on_auto_check_changed)
        lay.addWidget(self._auto_check)

        # Frequency
        freq_row = QHBoxLayout()
        freq_row.setSpacing(10)
        freq_lbl = QLabel("Check frequency:")
        freq_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        freq_row.addWidget(freq_lbl)

        self._freq_combo = QComboBox()
        self._freq_combo.addItems(["Every launch", "Daily", "Weekly"])
        freq_map = {"always": 0, "daily": 1, "weekly": 2}
        saved_freq = cfg_mod.get_pref("updates.frequency", "always")
        self._freq_combo.setCurrentIndex(freq_map.get(saved_freq, 0))
        self._freq_combo.setStyleSheet(_COMBO)
        self._freq_combo.setFixedWidth(160)
        self._freq_combo.currentIndexChanged.connect(self._on_freq_changed)
        freq_row.addWidget(self._freq_combo)
        freq_row.addStretch(1)
        lay.addLayout(freq_row)

        # Channel
        ch_row = QHBoxLayout()
        ch_row.setSpacing(10)
        ch_lbl = QLabel("Release channel:")
        ch_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        ch_row.addWidget(ch_lbl)

        self._channel_combo = QComboBox()
        self._channel_combo.addItems(["Stable releases only", "Include pre-releases (beta)"])
        include_pre = cfg_mod.get_pref("updates.include_prerelease", False)
        self._channel_combo.setCurrentIndex(1 if include_pre else 0)
        self._channel_combo.setStyleSheet(_COMBO)
        self._channel_combo.setFixedWidth(260)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._channel_combo)
        ch_row.addStretch(1)
        lay.addLayout(ch_row)

        lay.addWidget(_sep())

        # Manual check row
        check_row = QHBoxLayout()
        self._check_btn = QPushButton("Check Now")
        self._check_btn.setStyleSheet(_BTN_PRIMARY)
        self._check_btn.setFixedWidth(130)
        self._check_btn.clicked.connect(self._on_check_now)
        check_row.addWidget(self._check_btn)

        self._check_result = QLabel("")
        self._check_result.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        check_row.addWidget(self._check_result, 1)
        lay.addLayout(check_row)

        note = _body(
            "When an update is available, an indicator will appear in the application "
            "header. You can also view all releases on the Microsanj GitHub page.")
        lay.addWidget(note)

        releases_btn = QPushButton("View All Releases on GitHub ↗")
        releases_btn.setStyleSheet(_BTN_SECONDARY)
        releases_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL)))
        lay.addWidget(releases_btn)

        self._update_freq_enabled()
        return g

    def _build_ai_group(self) -> QGroupBox:
        g = _group("AI Assistant  (local, offline)")
        lay = QVBoxLayout(g)
        lay.setSpacing(14)

        intro = _body(
            "Enable an on-device AI assistant powered by a local GGUF model "
            "(e.g. Phi-3.5-mini, Qwen2.5-3B). All inference runs on this machine — "
            "no data ever leaves your network.")
        lay.addWidget(intro)

        # Enable toggle
        self._ai_enable_chk = QCheckBox("Enable AI Assistant")
        self._ai_enable_chk.setStyleSheet(_CHECK)
        self._ai_enable_chk.setChecked(cfg_mod.get_pref("ai.enabled", False))
        self._ai_enable_chk.toggled.connect(self._on_ai_enable_changed)
        lay.addWidget(self._ai_enable_chk)

        # Model path row
        path_row = QHBoxLayout()
        path_lbl = QLabel("Model file (.gguf):")
        path_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        path_row.addWidget(path_lbl)

        self._ai_path_edit = QLineEdit()
        self._ai_path_edit.setPlaceholderText("Path to .gguf model file…")
        self._ai_path_edit.setText(cfg_mod.get_pref("ai.model_path", ""))
        self._ai_path_edit.setStyleSheet(
            f"QLineEdit {{ background:{_BG2}; color:{_TEXT}; "
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f"font-size:12pt; padding:5px 8px; }}"
        )
        self._ai_path_edit.textChanged.connect(
            lambda t: cfg_mod.set_pref("ai.model_path", t))
        path_row.addWidget(self._ai_path_edit, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.setStyleSheet(_BTN_SECONDARY)
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_model)
        path_row.addWidget(browse_btn)
        lay.addLayout(path_row)

        # GPU layers row
        gpu_row = QHBoxLayout()
        gpu_lbl = QLabel("GPU layers (0 = CPU only):")
        gpu_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        gpu_row.addWidget(gpu_lbl)

        self._ai_gpu_spin = QSpinBox()
        self._ai_gpu_spin.setRange(0, 999)
        self._ai_gpu_spin.setValue(cfg_mod.get_pref("ai.n_gpu_layers", 0))
        self._ai_gpu_spin.setFixedWidth(80)
        self._ai_gpu_spin.setStyleSheet(
            f"QSpinBox {{ background:{_BG2}; color:{_TEXT}; "
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f"font-size:12pt; padding:4px; }}"
        )
        self._ai_gpu_spin.setToolTip(
            "Number of model layers to offload to GPU.\n"
            "Set to 0 for CPU-only inference (slower, no GPU required).\n"
            "Set to a large number (e.g. 999) to offload as much as possible.")
        self._ai_gpu_spin.valueChanged.connect(
            lambda v: cfg_mod.set_pref("ai.n_gpu_layers", v))
        gpu_row.addWidget(self._ai_gpu_spin)
        gpu_row.addStretch(1)
        lay.addLayout(gpu_row)

        lay.addWidget(_sep())

        # Apply / status row
        apply_row = QHBoxLayout()
        self._ai_apply_btn = QPushButton("Load Model")
        self._ai_apply_btn.setStyleSheet(_BTN_PRIMARY)
        self._ai_apply_btn.setFixedWidth(120)
        self._ai_apply_btn.clicked.connect(self._on_ai_apply)
        apply_row.addWidget(self._ai_apply_btn)

        self._ai_status_lbl = QLabel("")
        self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        apply_row.addWidget(self._ai_status_lbl, 1)
        lay.addLayout(apply_row)

        note = _body(
            "Good free models: Phi-3.5-mini-instruct-Q4_K_M.gguf (~2.4 GB), "
            "Qwen2.5-3B-Instruct-Q4_K_M.gguf (~2.0 GB). "
            "Download from Hugging Face (GGUF format, Q4_K_M recommended).")
        lay.addWidget(note)

        self._update_ai_controls()
        return g

    def _build_support_group(self) -> QGroupBox:
        g = _group("Support & About")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        info = _body(
            "When contacting Microsanj support, please include your version number "
            "and system information. Use the button below to copy it to your clipboard.")
        lay.addWidget(info)

        about_btn = QPushButton("About SanjINSIGHT…")
        about_btn.setStyleSheet(_BTN_SECONDARY)
        about_btn.clicked.connect(self._open_about)
        lay.addWidget(about_btn)

        contact_row = QHBoxLayout()
        contact_lbl = QLabel(f"Support email:  {SUPPORT_EMAIL}")
        contact_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        contact_row.addWidget(contact_lbl)
        contact_row.addStretch(1)
        lay.addLayout(contact_row)

        return g

    # ── Event handlers ────────────────────────────────────────────────

    def _on_auto_check_changed(self, checked: bool):
        cfg_mod.set_pref("updates.auto_check", checked)
        self._update_freq_enabled()

    def _on_freq_changed(self, idx: int):
        mapping = {0: "always", 1: "daily", 2: "weekly"}
        cfg_mod.set_pref("updates.frequency", mapping[idx])

    def _on_channel_changed(self, idx: int):
        cfg_mod.set_pref("updates.include_prerelease", idx == 1)

    def _update_freq_enabled(self):
        enabled = self._auto_check.isChecked()
        self._freq_combo.setEnabled(enabled)
        self._channel_combo.setEnabled(enabled)

    def _on_check_now(self):
        self._check_btn.setEnabled(False)
        self._check_result.setText("Checking…")
        self._check_result.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        self.check_for_updates_requested.emit()

    def set_check_result(self, message: str, color: str = None):
        """Called by MainWindow after a manual check completes."""
        self._check_result.setText(message)
        self._check_result.setStyleSheet(
            f"font-size:12pt; color:{color or _MUTED};")
        self._check_btn.setEnabled(True)

    def set_update_status(self, message: str, color: str = None):
        """Update the version card status label."""
        self._update_status_lbl.setText(message)
        if color:
            self._update_status_lbl.setStyleSheet(
                f"font-size:11pt; color:{color};")

    def _on_ai_enable_changed(self, checked: bool):
        cfg_mod.set_pref("ai.enabled", checked)
        self._update_ai_controls()
        if not checked:
            self.ai_disable_requested.emit()

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF model file", "",
            "GGUF models (*.gguf);;All files (*)")
        if path:
            self._ai_path_edit.setText(path)
            cfg_mod.set_pref("ai.model_path", path)

    def _on_ai_apply(self):
        path = self._ai_path_edit.text().strip()
        if not path:
            self._ai_status_lbl.setText("No model file selected")
            self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:#ff5555;")
            return
        n_gpu = self._ai_gpu_spin.value()
        self._ai_apply_btn.setEnabled(False)
        self._ai_status_lbl.setText("Loading…")
        self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:#ffaa44;")
        self.ai_enable_requested.emit(path, n_gpu)

    def set_ai_status(self, status: str) -> None:
        """Called by MainWindow when AIService.status_changed fires."""
        if not hasattr(self, "_ai_status_lbl"):
            return
        _msgs = {
            "off":      ("Off", _MUTED),
            "loading":  ("Loading model…", "#ffaa44"),
            "ready":    ("Ready", _GREEN),
            "thinking": ("Thinking…", "#8888ff"),
            "error":    ("Error — see AI panel", "#ff5555"),
        }
        msg, color = _msgs.get(status, (status, _MUTED))
        self._ai_status_lbl.setText(msg)
        self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:{color};")
        if hasattr(self, "_ai_apply_btn"):
            self._ai_apply_btn.setEnabled(status not in ("loading", "thinking"))

    def _update_ai_controls(self):
        enabled = self._ai_enable_chk.isChecked()
        if hasattr(self, "_ai_path_edit"):
            self._ai_path_edit.setEnabled(enabled)
        if hasattr(self, "_ai_gpu_spin"):
            self._ai_gpu_spin.setEnabled(enabled)
        if hasattr(self, "_ai_apply_btn"):
            self._ai_apply_btn.setEnabled(enabled)

    def _open_about(self):
        from ui.update_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec_()
