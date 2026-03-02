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
    QScrollArea, QSlider, QLineEdit, QFileDialog, QProgressBar,
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
    check_for_updates_requested       — emitted when user clicks "Check Now"
    ai_enable_requested(str, int)     — (model_path, n_gpu_layers) when user enables AI
    ai_disable_requested              — emitted when user disables AI
    download_model_requested(str,str) — (url, dest_path) to start a model download
    download_cancel_requested         — emitted when user cancels a download
    """

    check_for_updates_requested = pyqtSignal()
    ai_enable_requested         = pyqtSignal(str, int)
    ai_disable_requested        = pyqtSignal()
    download_model_requested    = pyqtSignal(str, str)
    download_cancel_requested   = pyqtSignal()

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
        from ai.model_downloader import find_existing_model, DEFAULT_MODELS_DIR
        from ai.model_catalog   import MODEL_CATALOG, MODEL_ORDER
        from ai.hardware_probe  import probe_hardware

        # Probe runs synchronously but is fast (<300 ms)
        try:
            _hw = probe_hardware()
        except Exception:
            from ai.hardware_probe import HardwareProfile
            _hw = HardwareProfile(ram_gb=8.0)

        g = _group("AI Assistant  (local, offline)")
        lay = QVBoxLayout(g)
        lay.setSpacing(14)

        # ── Privacy guarantee frame ──────────────────────────────────────────
        privacy_frame = QFrame()
        privacy_frame.setStyleSheet(
            f"QFrame {{ background:#0a1f18; border:1px solid {_GREEN}55; "
            f"border-radius:5px; }}"
        )
        pf_lay = QHBoxLayout(privacy_frame)
        pf_lay.setContentsMargins(10, 8, 10, 8)
        pf_lay.setSpacing(10)

        import os as _os
        _bug_svg = _os.path.join(
            _os.path.dirname(__file__), "..", "assets", "microsanj-bug.svg")
        _bug_loaded = False
        if _os.path.exists(_bug_svg):
            try:
                from PyQt5.QtSvg import QSvgWidget
                _bug_w = QSvgWidget(_bug_svg)
                _bug_w.setFixedSize(40, 40)
                _bug_w.setStyleSheet("background:transparent; border:none;")
                pf_lay.addWidget(_bug_w)
                _bug_loaded = True
            except Exception:
                pass
        if not _bug_loaded:
            lock_lbl = QLabel("🔒")
            lock_lbl.setStyleSheet("font-size:16pt; border:none;")
            lock_lbl.setFixedWidth(28)
            pf_lay.addWidget(lock_lbl)

        privacy_text = QLabel(
            "<b>Privacy guarantee:</b> the AI assistant runs 100% locally on "
            "this machine. It never communicates with external servers, cloud "
            "services, or the internet under any circumstances."
        )
        privacy_text.setWordWrap(True)
        privacy_text.setStyleSheet(f"font-size:11pt; color:{_GREEN}; border:none;")
        pf_lay.addWidget(privacy_text, 1)
        lay.addWidget(privacy_frame)

        # ── "AI disabled" notice (hidden when enabled) ────────────────────
        self._ai_disabled_notice = _body(
            "AI Assistant is currently disabled. Enable the checkbox below "
            "and download a model to get started."
        )
        lay.addWidget(self._ai_disabled_notice)

        # ── Enable toggle ─────────────────────────────────────────────────
        self._ai_enable_chk = QCheckBox("Enable AI Assistant")
        self._ai_enable_chk.setStyleSheet(_CHECK)
        self._ai_enable_chk.setChecked(cfg_mod.get_pref("ai.enabled", False))
        self._ai_enable_chk.toggled.connect(self._on_ai_enable_changed)
        lay.addWidget(self._ai_enable_chk)

        # ── Download section (visible when enabled) ───────────────────────
        self._ai_download_widget = QWidget()
        dl_lay = QVBoxLayout(self._ai_download_widget)
        dl_lay.setContentsMargins(0, 0, 0, 0)
        dl_lay.setSpacing(8)

        # Hardware summary card
        hw_frame = QFrame()
        hw_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2}; border:1px solid {_BORDER}; "
            f"border-radius:4px; }}"
        )
        hw_lay = QHBoxLayout(hw_frame)
        hw_lay.setContentsMargins(10, 6, 10, 6)
        hw_icon = QLabel("💻")
        hw_icon.setStyleSheet("font-size:14pt; border:none;")
        hw_icon.setFixedWidth(24)
        hw_lay.addWidget(hw_icon)
        hw_lbl = QLabel(_hw.hw_summary or "Hardware details unavailable")
        hw_lbl.setStyleSheet(f"font-size:11pt; color:{_TEXT}; border:none;")
        hw_lbl.setWordWrap(True)
        hw_lay.addWidget(hw_lbl, 1)
        dl_lay.addWidget(hw_frame)

        # Model selector combo
        combo_row = QHBoxLayout()
        combo_lbl = QLabel("Select model:")
        combo_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        combo_row.addWidget(combo_lbl)

        self._ai_model_ids = list(MODEL_ORDER)
        self._ai_model_combo = QComboBox()
        self._ai_model_combo.setStyleSheet(_COMBO)
        for mid in self._ai_model_ids:
            m   = MODEL_CATALOG[mid]
            tag = "  ✓ Recommended" if mid == _hw.recommended_model_id else ""
            self._ai_model_combo.addItem(
                f"{m['name']}  ·  {m['size_gb']:.1f} GB{tag}")
        # Pre-select the recommended model
        try:
            rec_idx = self._ai_model_ids.index(_hw.recommended_model_id)
        except ValueError:
            rec_idx = 0
        self._ai_model_combo.setCurrentIndex(rec_idx)
        self._ai_model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        combo_row.addWidget(self._ai_model_combo, 1)
        dl_lay.addLayout(combo_row)

        # Model description + recommendation reason
        self._ai_model_desc_lbl = _body(
            MODEL_CATALOG[self._ai_model_ids[rec_idx]]["description"])
        dl_lay.addWidget(self._ai_model_desc_lbl)

        self._ai_rec_reason_lbl = _body(_hw.rec_reason)
        self._ai_rec_reason_lbl.setStyleSheet(f"font-size:10pt; color:{_GREEN};")
        dl_lay.addWidget(self._ai_rec_reason_lbl)

        # Auto-fill GPU layers with hardware recommendation
        # (applied after the spinner is built, stored here for deferred use)
        self._ai_probe_gpu_layers = _hw.recommended_n_gpu_layers

        # Download / Cancel buttons
        dl_btn_row = QHBoxLayout()
        self._ai_download_btn = QPushButton("Download Selected Model")
        self._ai_download_btn.setStyleSheet(_BTN_PRIMARY)
        self._ai_download_btn.clicked.connect(self._on_download_clicked)
        dl_btn_row.addWidget(self._ai_download_btn)

        self._ai_cancel_btn = QPushButton("Cancel")
        self._ai_cancel_btn.setStyleSheet(_BTN_SECONDARY)
        self._ai_cancel_btn.setFixedWidth(80)
        self._ai_cancel_btn.setVisible(False)
        self._ai_cancel_btn.clicked.connect(self.download_cancel_requested)
        dl_btn_row.addWidget(self._ai_cancel_btn)
        dl_btn_row.addStretch(1)
        dl_lay.addLayout(dl_btn_row)

        self._ai_progress_bar = QProgressBar()
        self._ai_progress_bar.setRange(0, 100)
        self._ai_progress_bar.setValue(0)
        self._ai_progress_bar.setTextVisible(True)
        self._ai_progress_bar.setVisible(False)
        self._ai_progress_bar.setFixedHeight(16)
        self._ai_progress_bar.setStyleSheet(
            f"QProgressBar {{ background:{_BG2}; border:1px solid {_BORDER}; "
            f"border-radius:4px; font-size:10pt; color:{_TEXT}; }}"
            f"QProgressBar::chunk {{ background:{_GREEN}; border-radius:3px; }}"
        )
        dl_lay.addWidget(self._ai_progress_bar)

        self._ai_dl_status_lbl = QLabel("")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._ai_dl_status_lbl.setVisible(False)
        dl_lay.addWidget(self._ai_dl_status_lbl)

        lay.addWidget(self._ai_download_widget)

        # ── Model path row ────────────────────────────────────────────────
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

        # ── GPU acceleration slider ───────────────────────────────────────
        gpu_section_lbl = QLabel("GPU acceleration")
        gpu_section_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        lay.addWidget(gpu_section_lbl)

        _init_n_layers = MODEL_CATALOG[self._ai_model_ids[rec_idx]].get("n_layers", 32)

        self._ai_gpu_slider = QSlider(Qt.Horizontal)
        self._ai_gpu_slider.setMinimum(0)
        self._ai_gpu_slider.setMaximum(_init_n_layers)
        self._ai_gpu_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background:{_BG2}; border:1px solid {_BORDER};
                height:6px; border-radius:3px;
            }}
            QSlider::handle:horizontal {{
                background:{_ACCENT}; border:none;
                width:16px; height:16px; margin:-5px 0;
                border-radius:8px;
            }}
            QSlider::sub-page:horizontal {{
                background:{_ACCENT}55; border-radius:3px;
            }}
            QSlider:disabled::handle:horizontal {{ background:{_BORDER}; }}
            QSlider:disabled::sub-page:horizontal {{ background:{_BG2}; }}
        """)

        slider_row = QHBoxLayout()
        cpu_end = QLabel("CPU")
        cpu_end.setStyleSheet(f"font-size:10pt; color:{_MUTED};")
        cpu_end.setFixedWidth(36)
        slider_row.addWidget(cpu_end)
        slider_row.addWidget(self._ai_gpu_slider, 1)
        gpu_end = QLabel("Full GPU")
        gpu_end.setStyleSheet(f"font-size:10pt; color:{_MUTED};")
        gpu_end.setFixedWidth(60)
        gpu_end.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider_row.addWidget(gpu_end)
        lay.addLayout(slider_row)

        self._ai_gpu_label = QLabel("")
        self._ai_gpu_label.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        lay.addWidget(self._ai_gpu_label)

        # Initial slider value: saved preference, or hardware probe recommendation
        _saved_layers = cfg_mod.get_pref("ai.n_gpu_layers", 0)
        _probe_layers  = getattr(self, "_ai_probe_gpu_layers", 0)
        if _saved_layers == 0 and _probe_layers > 0:
            _init_val = min(_probe_layers, _init_n_layers)
        else:
            _init_val = min(_saved_layers, _init_n_layers)
        self._ai_gpu_slider.setValue(_init_val)
        self._on_gpu_slider_changed(_init_val)          # set initial label
        self._ai_gpu_slider.valueChanged.connect(self._on_gpu_slider_changed)

        lay.addWidget(_sep())

        # ── Load Model / status row ───────────────────────────────────────
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

        # ── AI Mode (persona) ─────────────────────────────────────────────
        from ai.personas import PERSONAS, PERSONA_ORDER, DEFAULT_PERSONA_ID

        mode_lbl = QLabel("AI Mode")
        mode_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        lay.addWidget(mode_lbl)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self._ai_persona_btns: dict[str, QPushButton] = {}
        _saved_pid = cfg_mod.get_pref("ai.persona", DEFAULT_PERSONA_ID)
        for pid in PERSONA_ORDER:
            p   = PERSONAS[pid]
            btn = QPushButton(p.display_name)
            btn.setCheckable(True)
            btn.setChecked(pid == _saved_pid)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{_BG2}; color:{_MUTED};
                    border:1px solid {_BORDER}; border-radius:5px;
                    padding:6px 14px; font-size:11pt;
                }}
                QPushButton:checked {{
                    background:{_ACCENT}22; color:{_TEXT};
                    border:1px solid {_ACCENT};
                }}
                QPushButton:hover:!checked {{ background:#1e2540; color:{_TEXT}; }}
            """)
            btn.clicked.connect(lambda checked, _pid=pid: self._on_persona_clicked(_pid))
            mode_row.addWidget(btn)
            self._ai_persona_btns[pid] = btn
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        self._ai_persona_desc_lbl = _body(PERSONAS[_saved_pid].description)
        lay.addWidget(self._ai_persona_desc_lbl)

        # Auto-detect existing model from ~/.microsanj/models/
        existing = find_existing_model(DEFAULT_MODELS_DIR)
        if existing and not cfg_mod.get_pref("ai.model_path", ""):
            self._ai_path_edit.setText(existing)
            cfg_mod.set_pref("ai.model_path", existing)
            self._ai_status_lbl.setText("Model found — click Load Model to enable")
            self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:{_GREEN};")

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
        n_gpu = self._ai_gpu_slider.value()
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

    def _on_persona_clicked(self, pid: str) -> None:
        """Persist persona selection and update button states."""
        from ai.personas import PERSONAS
        cfg_mod.set_pref("ai.persona", pid)
        for _pid, btn in self._ai_persona_btns.items():
            btn.setChecked(_pid == pid)
        if hasattr(self, "_ai_persona_desc_lbl"):
            self._ai_persona_desc_lbl.setText(PERSONAS[pid].description)

    def _on_model_combo_changed(self, idx: int) -> None:
        """Update description label and slider range when user changes model selection."""
        from ai.model_catalog import MODEL_CATALOG
        if not hasattr(self, "_ai_model_ids") or idx >= len(self._ai_model_ids):
            return
        mid = self._ai_model_ids[idx]
        m   = MODEL_CATALOG[mid]
        if hasattr(self, "_ai_model_desc_lbl"):
            self._ai_model_desc_lbl.setText(m["description"])
        # Update slider range and label for the newly selected model
        if hasattr(self, "_ai_gpu_slider"):
            n_layers    = m.get("n_layers", 32)
            current_val = self._ai_gpu_slider.value()
            self._ai_gpu_slider.setMaximum(n_layers)
            clamped = min(current_val, n_layers)
            if clamped != current_val:
                self._ai_gpu_slider.setValue(clamped)   # triggers _on_gpu_slider_changed
            else:
                self._on_gpu_slider_changed(clamped)    # re-render label for new model

    def _on_gpu_slider_changed(self, val: int) -> None:
        """Update GPU layer label and persist preference when slider moves."""
        from ai.model_catalog import MODEL_CATALOG
        if not hasattr(self, "_ai_model_ids") or not hasattr(self, "_ai_gpu_label"):
            return
        idx = self._ai_model_combo.currentIndex() \
              if hasattr(self, "_ai_model_combo") else 0
        mid      = self._ai_model_ids[idx] if idx < len(self._ai_model_ids) \
                   else "phi35_mini_q4"
        m        = MODEL_CATALOG[mid]
        n_layers = m.get("n_layers", 32)
        vram_gb  = val * (m["size_gb"] / n_layers)

        if val == 0:
            text  = "CPU only — no GPU required"
            color = _MUTED
        elif val >= n_layers:
            text  = f"Full GPU — all {n_layers} layers  ·  ~{vram_gb:.1f} GB VRAM"
            color = _GREEN
        else:
            text  = f"{val} / {n_layers} layers on GPU  ·  ~{vram_gb:.1f} GB VRAM"
            color = _AMBER

        self._ai_gpu_label.setText(text)
        self._ai_gpu_label.setStyleSheet(f"font-size:11pt; color:{color};")
        cfg_mod.set_pref("ai.n_gpu_layers", val)

    def _on_download_clicked(self) -> None:
        from ai.model_downloader import DEFAULT_MODELS_DIR
        from ai.model_catalog   import MODEL_CATALOG
        # Use selected model from combo, fall back to first entry
        idx = self._ai_model_combo.currentIndex() \
              if hasattr(self, "_ai_model_combo") else 0
        mid = self._ai_model_ids[idx] if hasattr(self, "_ai_model_ids") \
              and idx < len(self._ai_model_ids) else "phi35_mini_q4"
        m    = MODEL_CATALOG[mid]
        dest = str(DEFAULT_MODELS_DIR / m["filename"])
        self._ai_download_btn.setEnabled(False)
        self._ai_cancel_btn.setVisible(True)
        self._ai_progress_bar.setValue(0)
        self._ai_progress_bar.setVisible(True)
        self._ai_dl_status_lbl.setVisible(True)
        self._ai_dl_status_lbl.setText(f"Starting download of {m['name']}…")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self.download_model_requested.emit(m["url"], dest)

    def set_download_progress(self, done: int, total: int, speed_mbps: float) -> None:
        """Called by MainWindow during model download."""
        if not hasattr(self, "_ai_progress_bar"):
            return
        done_mb   = done  / 1024 / 1024
        speed_str = f"  {speed_mbps:.1f} MB/s" if speed_mbps > 0 else ""
        if total > 0:
            # Content-Length known — determinate progress
            self._ai_progress_bar.setRange(0, 100)
            self._ai_progress_bar.setValue(int(done / total * 100))
            total_mb = total / 1024 / 1024
            self._ai_dl_status_lbl.setText(
                f"Downloading… {done_mb:.0f} / {total_mb:.0f} MB{speed_str}")
        else:
            # Content-Length unknown (CDN redirect) — indeterminate animation
            self._ai_progress_bar.setRange(0, 0)
            self._ai_dl_status_lbl.setText(
                f"Downloading… {done_mb:.0f} MB{speed_str}")

    def set_download_complete(self, path: str) -> None:
        """Called by MainWindow when model download finishes successfully."""
        if not hasattr(self, "_ai_progress_bar"):
            return
        self._ai_progress_bar.setRange(0, 100)  # restore from indeterminate if needed
        self._ai_progress_bar.setValue(100)
        self._ai_cancel_btn.setVisible(False)
        self._ai_download_btn.setEnabled(True)
        self._ai_download_btn.setText("Re-download Model")
        self._ai_dl_status_lbl.setText("Download complete — model is ready")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:11pt; color:{_GREEN};")
        self._ai_path_edit.setText(path)
        self._ai_status_lbl.setText("Model ready — click Load Model")
        self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:{_GREEN};")

    def set_download_failed(self, msg: str) -> None:
        """Called by MainWindow when model download fails or is cancelled."""
        if not hasattr(self, "_ai_progress_bar"):
            return
        self._ai_progress_bar.setVisible(False)
        self._ai_cancel_btn.setVisible(False)
        self._ai_download_btn.setEnabled(True)
        self._ai_dl_status_lbl.setVisible(True)
        if msg == "Cancelled":
            self._ai_dl_status_lbl.setText("Download cancelled")
            self._ai_dl_status_lbl.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        else:
            self._ai_dl_status_lbl.setText(f"Download failed: {msg}")
            self._ai_dl_status_lbl.setStyleSheet(f"font-size:11pt; color:#ff5555;")

    def _update_ai_controls(self):
        enabled = self._ai_enable_chk.isChecked()
        if hasattr(self, "_ai_disabled_notice"):
            self._ai_disabled_notice.setVisible(not enabled)
        if hasattr(self, "_ai_download_widget"):
            self._ai_download_widget.setVisible(enabled)
        if hasattr(self, "_ai_path_edit"):
            self._ai_path_edit.setEnabled(enabled)
        if hasattr(self, "_ai_gpu_slider"):
            self._ai_gpu_slider.setEnabled(enabled)
        if hasattr(self, "_ai_apply_btn"):
            self._ai_apply_btn.setEnabled(enabled)
        for btn in getattr(self, "_ai_persona_btns", {}).values():
            btn.setEnabled(enabled)

    def _open_about(self):
        from ui.update_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec_()
