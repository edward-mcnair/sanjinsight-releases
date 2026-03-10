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
from PyQt5.QtCore    import Qt, QThread, QTimer, pyqtSignal, QUrl
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
_DANGER  = "#ff5555"

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


# ── Ollama background worker threads ──────────────────────────────────────────

class _OllamaInstallThread(QThread):
    """
    Downloads the Ollama Windows installer to the system temp directory and
    launches it.  Emits progress(int, str) during download and
    finished(bool, str) when done.

    Only used on Windows.  On macOS/Linux the caller opens the browser directly.

    Supports mid-download cancellation via QThread.requestInterruption():
    the reporthook checks isInterruptionRequested() on every block and raises
    InterruptedError to abort urlretrieve cleanly.  The finished signal is
    then emitted with (False, "cancelled") so the UI can distinguish a
    cancellation from a real download error.
    """

    progress = pyqtSignal(int, str)   # (percent 0-100, human-readable message)
    finished = pyqtSignal(bool, str)  # (success, message)

    def run(self) -> None:
        import os
        import tempfile
        import subprocess
        import urllib.request

        url      = "https://ollama.com/download/OllamaSetup.exe"
        tmp_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

        def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if self.isInterruptionRequested():
                raise InterruptedError("download cancelled")
            if total_size > 0:
                pct    = min(int(block_num * block_size / total_size * 100), 99)
                mb     = block_num * block_size // 1_000_000
                total  = total_size // 1_000_000
                self.progress.emit(pct, f"Downloading…  {pct}%  ({mb} / {total} MB)")

        try:
            self.progress.emit(0, "Connecting to ollama.com…")
            urllib.request.urlretrieve(url, tmp_path, _reporthook)
            self.progress.emit(100, "Launching installer…")
            subprocess.Popen([tmp_path], shell=False)
            self.finished.emit(
                True,
                "Installer launched.  Complete the setup window, "
                "then click  ⟳ Check Again  below.",
            )
        except InterruptedError:
            self.finished.emit(False, "cancelled")
        except Exception as exc:
            self.finished.emit(False, f"Download failed: {exc}")


class _OllamaPullThread(QThread):
    """
    Runs  ``ollama pull <model>``  in a subprocess and streams its output.

    Signals
    -------
    output_line(str)       one line of stdout/stderr from the pull command
    finished(bool, str)    (success, summary message)

    Call cancel() to terminate the subprocess mid-pull.  The finished signal
    is then emitted with (False, "cancelled").
    """

    output_line = pyqtSignal(str)
    finished    = pyqtSignal(bool, str)

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self._model = model
        self._proc  = None   # set once the subprocess is running

    def cancel(self) -> None:
        """Terminate the ollama pull subprocess immediately."""
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        import subprocess
        from ai.remote_runner import ollama_exe_path

        exe = ollama_exe_path()
        if not exe:
            self.finished.emit(
                False,
                "ollama command not found — is the Ollama installation complete?",
            )
            return
        try:
            self._proc = subprocess.Popen(
                [exe, "pull", self._model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for raw_line in self._proc.stdout:
                line = raw_line.rstrip()
                if line:
                    self.output_line.emit(line)
            self._proc.wait()
            if self._proc.returncode == 0:
                self.finished.emit(True,  f"✓  {self._model} is ready")
            elif self._proc.returncode in (-15, -9, 1) and \
                    self.isInterruptionRequested():
                # SIGTERM / SIGKILL / Windows terminate → treat as user cancel
                self.finished.emit(False, "cancelled")
            else:
                self.finished.emit(
                    False, f"Pull failed (exit {self._proc.returncode})")
        except Exception as exc:
            self.finished.emit(False, str(exc))
        finally:
            self._proc = None


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

    check_for_updates_requested   = pyqtSignal()
    ai_enable_requested           = pyqtSignal(str, int)
    ai_disable_requested          = pyqtSignal()
    download_model_requested      = pyqtSignal(str, str)
    download_cancel_requested     = pyqtSignal()
    cloud_ai_connect_requested    = pyqtSignal(str, str, str)  # provider, api_key, model_id
    cloud_ai_disconnect_requested = pyqtSignal()
    ollama_connect_requested      = pyqtSignal(str)   # model_id
    ollama_disconnect_requested   = pyqtSignal()

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

        # ── AI Assistant (local) ──────────────────────────────────────
        lay.addWidget(self._build_ai_group())

        # ── Cloud AI ──────────────────────────────────────────────────
        lay.addWidget(self._build_cloud_ai_group())

        # ── Ollama (local AI server) ───────────────────────────────────
        lay.addWidget(self._build_ollama_group())

        # ── License ───────────────────────────────────────────────────
        lay.addWidget(self._build_license_group())

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
        browse_btn.setFixedWidth(120)  # was 90 — too narrow for "Browse…" at 12pt + 18px padding
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

        lay.addWidget(_sep())

        # ── Knowledge scope ────────────────────────────────────────────────
        scope_lbl = QLabel("AI knowledge scope")
        scope_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        lay.addWidget(scope_lbl)

        from version import DOCS_URL
        from ai.manual_rag import _load_sections

        qs_always_lbl = QLabel(
            "✓  Quickstart Guide — always included in every AI response.")
        qs_always_lbl.setStyleSheet(f"font-size:11pt; color:{_GREEN};")
        lay.addWidget(qs_always_lbl)

        n_manual_sections = len(_load_sections())
        if n_manual_sections:
            rag_lbl = QLabel(
                f"✓  User Manual — {n_manual_sections} sections indexed for "
                "context-aware answers.")
        else:
            rag_lbl = QLabel(
                "⚠  User Manual not found — docs/ directory missing or not bundled.")
        rag_lbl.setStyleSheet(
            f"font-size:11pt; color:{_GREEN if n_manual_sections else _AMBER};")
        lay.addWidget(rag_lbl)

        qs_note_lbl = QLabel(
            "Out-of-scope questions receive a link to the full User Manual at "
            + DOCS_URL)
        qs_note_lbl.setWordWrap(True)
        qs_note_lbl.setStyleSheet(f"font-size:10pt; color:{_MUTED};")
        lay.addWidget(qs_note_lbl)

        # Auto-detect existing model from ~/.microsanj/models/
        existing = find_existing_model(DEFAULT_MODELS_DIR)
        if existing and not cfg_mod.get_pref("ai.model_path", ""):
            self._ai_path_edit.setText(existing)
            cfg_mod.set_pref("ai.model_path", existing)
            self._ai_status_lbl.setText("Model found — click Load Model to enable")
            self._ai_status_lbl.setStyleSheet(f"font-size:12pt; color:{_GREEN};")

        self._update_ai_controls()
        return g

    def _build_cloud_ai_group(self) -> QGroupBox:
        from ai.remote_runner import CLOUD_PROVIDERS

        g = _group("Cloud AI  (Optional — requires API key)")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # ── Privacy notice ────────────────────────────────────────────────
        warn_frame = QFrame()
        warn_frame.setStyleSheet(
            f"QFrame {{ background:#1f1a0a; border:1px solid {_AMBER}55; "
            f"border-radius:5px; }}"
        )
        wf_lay = QHBoxLayout(warn_frame)
        wf_lay.setContentsMargins(10, 8, 10, 8)
        wf_lay.setSpacing(10)
        warn_icon = QLabel("⚠")
        warn_icon.setStyleSheet(f"font-size:14pt; color:{_AMBER}; border:none;")
        warn_icon.setFixedWidth(22)
        wf_lay.addWidget(warn_icon)
        warn_text = QLabel(
            "Questions and instrument data will be sent to the provider's servers. "
            "Do not use Cloud AI if your work is confidential or export-controlled."
        )
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet(f"font-size:11pt; color:{_AMBER}; border:none;")
        wf_lay.addWidget(warn_text, 1)
        lay.addWidget(warn_frame)

        # ── Provider selector ─────────────────────────────────────────────
        provider_row = QHBoxLayout()
        provider_lbl = QLabel("Provider:")
        provider_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        provider_row.addWidget(provider_lbl)

        self._cloud_provider_combo = QComboBox()
        self._cloud_provider_combo.setStyleSheet(_COMBO)
        self._cloud_provider_ids: list[str] = []
        for pid, pdata in CLOUD_PROVIDERS.items():
            self._cloud_provider_ids.append(pid)
            self._cloud_provider_combo.addItem(pdata["name"])
        saved_provider = cfg_mod.get_pref("ai.cloud.provider", "claude")
        try:
            self._cloud_provider_combo.setCurrentIndex(
                self._cloud_provider_ids.index(saved_provider))
        except ValueError:
            pass
        self._cloud_provider_combo.currentIndexChanged.connect(
            self._on_cloud_provider_changed)
        provider_row.addWidget(self._cloud_provider_combo, 1)
        lay.addLayout(provider_row)

        # ── Model selector ────────────────────────────────────────────────
        model_row = QHBoxLayout()
        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        model_row.addWidget(model_lbl)

        self._cloud_model_combo = QComboBox()
        self._cloud_model_combo.setStyleSheet(_COMBO)
        self._cloud_model_ids: list[str] = []
        self._cloud_model_combo.currentIndexChanged.connect(
            self._on_cloud_model_changed)
        model_row.addWidget(self._cloud_model_combo, 1)
        lay.addLayout(model_row)

        # Populate model combo from initial provider selection
        self._refresh_cloud_model_combo()

        # ── API key input ─────────────────────────────────────────────────
        key_row = QHBoxLayout()
        key_lbl = QLabel("API Key:")
        key_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        key_row.addWidget(key_lbl)

        self._cloud_key_edit = QLineEdit()
        self._cloud_key_edit.setPlaceholderText("Paste your API key here…")
        self._cloud_key_edit.setEchoMode(QLineEdit.Password)
        self._cloud_key_edit.setStyleSheet(
            f"QLineEdit {{ background:{_BG2}; color:{_TEXT}; "
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f"font-size:12pt; padding:5px 8px; }}"
        )
        saved_key = cfg_mod.get_pref("ai.cloud.api_key", "")
        self._cloud_key_edit.setText(saved_key)
        self._cloud_key_edit.textChanged.connect(
            lambda t: cfg_mod.set_pref("ai.cloud.api_key", t))
        key_row.addWidget(self._cloud_key_edit, 1)

        self._cloud_key_show_btn = QPushButton("Show")
        self._cloud_key_show_btn.setStyleSheet(_BTN_SECONDARY)
        self._cloud_key_show_btn.setFixedWidth(70)
        self._cloud_key_show_btn.setCheckable(True)
        self._cloud_key_show_btn.toggled.connect(self._on_cloud_key_show_toggled)
        key_row.addWidget(self._cloud_key_show_btn)
        lay.addLayout(key_row)

        # Get key link
        self._cloud_key_link_lbl = QLabel("")
        self._cloud_key_link_lbl.setStyleSheet(
            f"font-size:10pt; color:{_ACCENT};")
        self._cloud_key_link_lbl.setOpenExternalLinks(True)
        lay.addWidget(self._cloud_key_link_lbl)
        self._update_cloud_key_link()

        lay.addWidget(_sep())

        # ── Connect / Disconnect row ──────────────────────────────────────
        action_row = QHBoxLayout()
        self._cloud_connect_btn = QPushButton("Connect")
        self._cloud_connect_btn.setStyleSheet(_BTN_PRIMARY)
        self._cloud_connect_btn.setFixedWidth(120)
        self._cloud_connect_btn.clicked.connect(self._on_cloud_connect_clicked)
        action_row.addWidget(self._cloud_connect_btn)

        self._cloud_status_lbl = QLabel("○  Not connected")
        self._cloud_status_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        action_row.addWidget(self._cloud_status_lbl, 1)
        lay.addLayout(action_row)

        return g

    # ── Ollama (local AI server) ──────────────────────────────────────

    def _build_ollama_group(self) -> QGroupBox:
        g = _group("Ollama  (Local AI Server — free, private, GPU-accelerated)")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # ── Description ───────────────────────────────────────────────────
        desc = QLabel(
            "Ollama runs AI models locally on your PC — no internet or API key needed. "
            "It supports dozens of open-source models (Llama 3, Mistral, Gemma …) "
            "and uses your GPU automatically when available.  "
            "SanjINSIGHT connects to the Ollama server running on this machine."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        lay.addWidget(desc)

        # ── Install Ollama box (hidden when already installed) ────────────
        self._ollama_install_box = QFrame()
        self._ollama_install_box.setStyleSheet(
            f"background:{_BG2}; border:1px solid #f5a62355; border-radius:6px;")
        ib = QVBoxLayout(self._ollama_install_box)
        ib.setContentsMargins(14, 12, 14, 12)
        ib.setSpacing(8)

        install_notice = QLabel("⚡  Ollama is not installed on this machine.")
        install_notice.setStyleSheet(
            f"font-size:12pt; font-weight:600; color:{_AMBER};")
        ib.addWidget(install_notice)

        install_hint = QLabel(
            "Ollama is a free, lightweight AI server.  "
            "Click below and it will download and install automatically "
            "(Windows), or open the download page on other systems.")
        install_hint.setWordWrap(True)
        install_hint.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        ib.addWidget(install_hint)

        btn_link_row = QHBoxLayout()
        self._ollama_install_btn = QPushButton("⬇  Install Ollama for me")
        self._ollama_install_btn.setStyleSheet(_BTN_PRIMARY)
        self._ollama_install_btn.setFixedWidth(230)
        self._ollama_install_btn.clicked.connect(self._on_install_ollama_clicked)
        btn_link_row.addWidget(self._ollama_install_btn)
        btn_link_row.addSpacing(16)

        manual_link = QLabel(
            f'or &nbsp;<a href="https://ollama.com/download" style="color:{_ACCENT};">'
            "download manually ↗</a>")
        manual_link.setOpenExternalLinks(True)
        manual_link.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        btn_link_row.addWidget(manual_link)
        btn_link_row.addStretch(1)
        ib.addLayout(btn_link_row)

        self._ollama_install_prog = QProgressBar()
        self._ollama_install_prog.setRange(0, 100)
        self._ollama_install_prog.setTextVisible(True)
        self._ollama_install_prog.setFixedHeight(18)
        self._ollama_install_prog.setVisible(False)
        ib.addWidget(self._ollama_install_prog)

        # Cancel button — visible only while the download is in progress.
        self._ollama_install_cancel_btn = QPushButton("✕  Cancel Download")
        self._ollama_install_cancel_btn.setStyleSheet(_BTN_SECONDARY)
        self._ollama_install_cancel_btn.setFixedWidth(180)
        self._ollama_install_cancel_btn.setVisible(False)
        self._ollama_install_cancel_btn.clicked.connect(
            self._on_install_cancel_clicked)
        ib.addWidget(self._ollama_install_cancel_btn)

        self._ollama_install_msg = QLabel("")
        self._ollama_install_msg.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._ollama_install_msg.setWordWrap(True)
        self._ollama_install_msg.setVisible(False)
        ib.addWidget(self._ollama_install_msg)

        lay.addWidget(self._ollama_install_box)

        # ── Pull model box (shown when installed but no models yet) ───────
        self._ollama_pull_box = QFrame()
        self._ollama_pull_box.setStyleSheet(
            f"background:{_BG2}; border:1px solid #00d4aa55; border-radius:6px;")
        pb2 = QVBoxLayout(self._ollama_pull_box)
        pb2.setContentsMargins(14, 12, 14, 12)
        pb2.setSpacing(8)

        pull_notice = QLabel("✓  Ollama installed.  Download a model to get started:")
        pull_notice.setStyleSheet(f"font-size:12pt; font-weight:600; color:{_GREEN};")
        pb2.addWidget(pull_notice)

        pull_hint = QLabel(
            "Phi-3 Mini is recommended (2.3 GB, works well on 4 GB GPU)."
            "  Mistral / Llama 3 are larger but more capable.")
        pull_hint.setWordWrap(True)
        pull_hint.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        pb2.addWidget(pull_hint)

        pull_row = QHBoxLayout()
        pull_lbl = QLabel("Model:")
        pull_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        pull_lbl.setFixedWidth(55)
        pull_row.addWidget(pull_lbl)

        self._ollama_pull_combo = QComboBox()
        self._ollama_pull_combo.setStyleSheet(_COMBO)
        for m in ["phi3", "phi3:mini", "mistral", "llama3:8b", "gemma2:2b"]:
            self._ollama_pull_combo.addItem(m)
        self._ollama_pull_combo.setCurrentText("phi3")
        pull_row.addWidget(self._ollama_pull_combo, 1)

        self._ollama_pull_btn = QPushButton("⬇  Pull Model")
        self._ollama_pull_btn.setStyleSheet(_BTN_PRIMARY)
        self._ollama_pull_btn.setFixedWidth(140)
        self._ollama_pull_btn.clicked.connect(self._on_pull_model_clicked)
        pull_row.addWidget(self._ollama_pull_btn)

        # Cancel button shown next to Pull Model while pulling.
        self._ollama_pull_cancel_btn = QPushButton("✕  Cancel")
        self._ollama_pull_cancel_btn.setStyleSheet(_BTN_SECONDARY)
        self._ollama_pull_cancel_btn.setFixedWidth(100)
        self._ollama_pull_cancel_btn.setVisible(False)
        self._ollama_pull_cancel_btn.clicked.connect(self._on_pull_cancel_clicked)
        pull_row.addWidget(self._ollama_pull_cancel_btn)
        pb2.addLayout(pull_row)

        self._ollama_pull_prog = QProgressBar()
        self._ollama_pull_prog.setRange(0, 0)          # indeterminate spinner
        self._ollama_pull_prog.setFixedHeight(18)
        self._ollama_pull_prog.setVisible(False)
        pb2.addWidget(self._ollama_pull_prog)

        self._ollama_pull_msg = QLabel("")
        self._ollama_pull_msg.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._ollama_pull_msg.setWordWrap(True)
        self._ollama_pull_msg.setVisible(False)
        pb2.addWidget(self._ollama_pull_msg)

        lay.addWidget(self._ollama_pull_box)

        lay.addWidget(_sep())

        # ── Model selector + Refresh ──────────────────────────────────────
        model_row = QHBoxLayout()
        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        model_lbl.setFixedWidth(70)
        model_row.addWidget(model_lbl)

        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setStyleSheet(_COMBO)
        self._ollama_model_combo.setEditable(False)
        self._ollama_model_combo.setPlaceholderText("(refresh to load installed models)")
        model_row.addWidget(self._ollama_model_combo, 1)

        self._ollama_refresh_btn = QPushButton("⟳ Check Again")
        self._ollama_refresh_btn.setStyleSheet(_BTN_SECONDARY)
        self._ollama_refresh_btn.setFixedWidth(120)
        self._ollama_refresh_btn.setToolTip(
            "Re-detect Ollama and refresh the model list")
        self._ollama_refresh_btn.clicked.connect(self._ollama_refresh_models)
        model_row.addWidget(self._ollama_refresh_btn)
        lay.addLayout(model_row)

        # ── Status + Connect row ──────────────────────────────────────────
        action_row = QHBoxLayout()
        self._ollama_connect_btn = QPushButton("Connect")
        self._ollama_connect_btn.setStyleSheet(_BTN_PRIMARY)
        self._ollama_connect_btn.setFixedWidth(120)
        self._ollama_connect_btn.clicked.connect(self._on_ollama_connect_clicked)
        action_row.addWidget(self._ollama_connect_btn)

        self._ollama_status_lbl = QLabel("○  Not connected")
        self._ollama_status_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        action_row.addWidget(self._ollama_status_lbl, 1)
        lay.addLayout(action_row)

        # Pre-populate models from a saved preference or live query
        self._ollama_refresh_models(silent=True)
        return g

    def _ollama_refresh_models(self, silent: bool = False) -> None:
        """
        Detect Ollama state and update the UI accordingly.

        State machine
        -------------
        NOT INSTALLED → show install box, hide pull box, set status "not installed"
        INSTALLED, NOT RUNNING → hide both boxes, report "not running"
        RUNNING, NO MODELS → hide install box, show pull box, report "pull needed"
        RUNNING, MODELS OK → hide both boxes, populate combo, report "ready"
        """
        from ai.remote_runner import (
            get_ollama_models, is_ollama_running, is_ollama_installed,
        )
        if not hasattr(self, "_ollama_model_combo"):
            return

        # ── 1. Is Ollama installed? ────────────────────────────────────────
        installed = is_ollama_installed()
        if hasattr(self, "_ollama_install_box"):
            self._ollama_install_box.setVisible(not installed)

        if not installed:
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(False)
            self._ollama_status_lbl.setText(
                "⊗  Ollama is not installed — use the Install button above")
            self._ollama_status_lbl.setStyleSheet(
                f"font-size:12pt; color:{_AMBER};")
            return

        # ── 2. Is the Ollama server running? ──────────────────────────────
        running = is_ollama_running(timeout=1.5)
        if not running:
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(False)
            if not silent:
                self._ollama_status_lbl.setText(
                    "⊗  Ollama installed but not running — "
                    "launch the Ollama app, then click  ⟳ Check Again")
                self._ollama_status_lbl.setStyleSheet(
                    f"font-size:12pt; color:{_DANGER};")
            return

        # ── 3. Any models pulled? ──────────────────────────────────────────
        models = get_ollama_models()
        self._ollama_model_combo.blockSignals(True)
        self._ollama_model_combo.clear()

        if not models:
            # Running but empty — show the pull section
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(True)
            self._ollama_model_ids = []
            self._ollama_status_lbl.setText(
                "⚠  No models pulled yet — use the Pull Model section above")
            self._ollama_status_lbl.setStyleSheet(
                f"font-size:12pt; color:{_AMBER};")
            self._ollama_model_combo.blockSignals(False)
            return

        # ── 4. All good — populate combo and report ready ─────────────────
        if hasattr(self, "_ollama_pull_box"):
            self._ollama_pull_box.setVisible(False)

        self._ollama_model_ids = [m["id"] for m in models]
        for m in models:
            self._ollama_model_combo.addItem(m["name"])
        saved = cfg_mod.get_pref("ai.ollama.model", "")
        try:
            self._ollama_model_combo.setCurrentIndex(
                self._ollama_model_ids.index(saved))
        except ValueError:
            self._ollama_model_combo.setCurrentIndex(0)

        # Always show the "ready" status even on silent refresh so the user
        # immediately knows Ollama is available on opening the Settings tab.
        self._ollama_status_lbl.setText(
            f"✓  Ollama ready — {len(models)} model(s) — click Connect")
        self._ollama_status_lbl.setStyleSheet(
            f"font-size:12pt; color:{_GREEN};")

        self._ollama_model_combo.blockSignals(False)

    def _on_ollama_connect_clicked(self) -> None:
        if not hasattr(self, "_ollama_connect_btn"):
            return
        if self._ollama_connect_btn.text() == "Disconnect":
            self.ollama_disconnect_requested.emit()
            return

        if not hasattr(self, "_ollama_model_ids") or not self._ollama_model_ids:
            self._ollama_refresh_models(silent=False)
            if not hasattr(self, "_ollama_model_ids") or not self._ollama_model_ids:
                return

        idx = self._ollama_model_combo.currentIndex()
        if idx < 0 or idx >= len(self._ollama_model_ids):
            return
        model_id = self._ollama_model_ids[idx]
        cfg_mod.set_pref("ai.ollama.model", model_id)
        self.set_ollama_status("loading", "◌  Connecting to Ollama…")
        self.ollama_connect_requested.emit(model_id)

    def set_ollama_status(self, status: str, message: str = "") -> None:
        """
        Called by main_app.py when the Ollama connection state changes.

        status: "loading" | "ready" | "error" | "off"
        """
        if not hasattr(self, "_ollama_status_lbl"):
            return
        if status == "loading":
            self._ollama_status_lbl.setText(message or "◌  Connecting…")
            self._ollama_status_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
            self._ollama_connect_btn.setEnabled(False)
        elif status == "ready":
            self._ollama_status_lbl.setText("●  Connected")
            self._ollama_status_lbl.setStyleSheet(f"font-size:12pt; color:{_GREEN};")
            self._ollama_connect_btn.setText("Disconnect")
            self._ollama_connect_btn.setEnabled(True)
        elif status == "error":
            self._ollama_status_lbl.setText(f"⊗  {message}" if message else "⊗  Error")
            self._ollama_status_lbl.setStyleSheet(f"font-size:12pt; color:{_DANGER};")
            self._ollama_connect_btn.setText("Connect")
            self._ollama_connect_btn.setEnabled(True)
        else:   # "off"
            self._ollama_status_lbl.setText("○  Not connected")
            self._ollama_status_lbl.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
            self._ollama_connect_btn.setText("Connect")
            self._ollama_connect_btn.setEnabled(True)

    # ── Ollama install / pull handlers ────────────────────────────────

    def _on_install_ollama_clicked(self) -> None:
        """
        Triggered by the  ⬇ Install Ollama for me  button.

        • Windows — downloads OllamaSetup.exe to the system temp folder via a
          background thread, then launches it; a progress bar shows download
          progress.
        • macOS / Linux — opens https://ollama.com/download in the browser
          (the native packages are not trivially installable by the app).

        After the installer is launched, the user completes installation
        normally and then clicks  ⟳ Check Again  to re-detect Ollama.
        """
        import sys
        if not hasattr(self, "_ollama_install_btn"):
            return

        if sys.platform == "win32":
            # Download + launch via background thread
            self._ollama_install_btn.setEnabled(False)
            self._ollama_install_prog.setValue(0)
            self._ollama_install_prog.setVisible(True)
            self._ollama_install_cancel_btn.setVisible(True)
            self._ollama_install_msg.setText("Connecting to ollama.com…")
            self._ollama_install_msg.setStyleSheet(
                f"font-size:11pt; color:{_MUTED};")
            self._ollama_install_msg.setVisible(True)

            self._install_thread = _OllamaInstallThread(self)
            self._install_thread.progress.connect(self._on_install_progress)
            self._install_thread.finished.connect(self._on_install_finished)
            self._install_thread.start()
        else:
            # macOS / Linux — open the download page
            QDesktopServices.openUrl(QUrl("https://ollama.com/download"))
            if hasattr(self, "_ollama_install_msg"):
                self._ollama_install_msg.setText(
                    "Opened  ollama.com/download  in your browser.  "
                    "Install Ollama, then click  ⟳ Check Again.")
                self._ollama_install_msg.setStyleSheet(
                    f"font-size:11pt; color:{_MUTED};")
                self._ollama_install_msg.setVisible(True)

    def _on_install_progress(self, pct: int, msg: str) -> None:
        if hasattr(self, "_ollama_install_prog"):
            self._ollama_install_prog.setValue(pct)
        if hasattr(self, "_ollama_install_msg"):
            self._ollama_install_msg.setText(msg)

    def _on_install_cancel_clicked(self) -> None:
        """User hit ✕ Cancel Download — interrupt the download thread."""
        if hasattr(self, "_install_thread") and self._install_thread.isRunning():
            self._install_thread.requestInterruption()
        if hasattr(self, "_ollama_install_cancel_btn"):
            self._ollama_install_cancel_btn.setEnabled(False)
            self._ollama_install_cancel_btn.setText("Cancelling…")

    def _on_install_finished(self, ok: bool, msg: str) -> None:
        if hasattr(self, "_ollama_install_prog"):
            self._ollama_install_prog.setVisible(False)
        if hasattr(self, "_ollama_install_cancel_btn"):
            self._ollama_install_cancel_btn.setVisible(False)
            self._ollama_install_cancel_btn.setEnabled(True)
            self._ollama_install_cancel_btn.setText("✕  Cancel Download")
        _cancelled = (msg == "cancelled")
        if hasattr(self, "_ollama_install_msg"):
            self._ollama_install_msg.setText(
                "Download cancelled." if _cancelled else msg)
            self._ollama_install_msg.setStyleSheet(
                f"font-size:11pt; color:{_MUTED if _cancelled else (_GREEN if ok else _DANGER)};")
        if hasattr(self, "_ollama_install_btn"):
            self._ollama_install_btn.setEnabled(True)
            if ok:
                self._ollama_install_btn.setText("⟳ Check Again")
        # After a successful launch wait a moment, then re-detect
        if ok:
            QTimer.singleShot(4000, lambda: self._ollama_refresh_models(silent=False))

    def _on_pull_model_clicked(self) -> None:
        """Triggered by the  ⬇ Pull Model  button; runs  ollama pull <model>."""
        if not hasattr(self, "_ollama_pull_combo"):
            return
        model = self._ollama_pull_combo.currentText().strip()
        if not model:
            return

        self._ollama_pull_btn.setEnabled(False)
        self._ollama_pull_cancel_btn.setVisible(True)
        self._ollama_pull_cancel_btn.setEnabled(True)
        self._ollama_pull_prog.setVisible(True)
        self._ollama_pull_msg.setText(
            f"Downloading  {model} …  (this may take a few minutes)")
        self._ollama_pull_msg.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._ollama_pull_msg.setVisible(True)

        self._pull_thread = _OllamaPullThread(model, self)
        self._pull_thread.output_line.connect(self._on_pull_output)
        self._pull_thread.finished.connect(self._on_pull_finished)
        self._pull_thread.start()

    def _on_pull_output(self, line: str) -> None:
        """Update the pull status label with the latest line from ollama pull."""
        if hasattr(self, "_ollama_pull_msg") and line.strip():
            # Trim to 80 chars so it fits on one line
            self._ollama_pull_msg.setText(line[:80])

    def _on_pull_cancel_clicked(self) -> None:
        """User hit ✕ Cancel — terminate the ollama pull subprocess."""
        if hasattr(self, "_pull_thread") and self._pull_thread.isRunning():
            self._pull_thread.requestInterruption()
            self._pull_thread.cancel()
        if hasattr(self, "_ollama_pull_cancel_btn"):
            self._ollama_pull_cancel_btn.setEnabled(False)
            self._ollama_pull_cancel_btn.setText("Cancelling…")

    def _on_pull_finished(self, ok: bool, msg: str) -> None:
        if hasattr(self, "_ollama_pull_prog"):
            self._ollama_pull_prog.setVisible(False)
        if hasattr(self, "_ollama_pull_cancel_btn"):
            self._ollama_pull_cancel_btn.setVisible(False)
            self._ollama_pull_cancel_btn.setEnabled(True)
            self._ollama_pull_cancel_btn.setText("✕  Cancel")
        if hasattr(self, "_ollama_pull_btn"):
            self._ollama_pull_btn.setEnabled(True)
        _cancelled = (msg == "cancelled")
        if hasattr(self, "_ollama_pull_msg"):
            self._ollama_pull_msg.setText(
                "Pull cancelled." if _cancelled else msg)
            self._ollama_pull_msg.setStyleSheet(
                f"font-size:11pt; color:{_MUTED if _cancelled else (_GREEN if ok else _DANGER)};")
        if ok:
            # Re-detect — pull box will hide and model combo will populate
            QTimer.singleShot(500, lambda: self._ollama_refresh_models(silent=False))

    # ── Cloud AI helpers ──────────────────────────────────────────────

    def _refresh_cloud_model_combo(self) -> None:
        from ai.remote_runner import CLOUD_PROVIDERS
        idx = self._cloud_provider_combo.currentIndex() \
              if hasattr(self, "_cloud_provider_combo") else 0
        if idx < 0 or idx >= len(self._cloud_provider_ids):
            return
        pid    = self._cloud_provider_ids[idx]
        models = CLOUD_PROVIDERS[pid]["models"]
        self._cloud_model_ids = [m["id"] for m in models]

        self._cloud_model_combo.blockSignals(True)
        self._cloud_model_combo.clear()
        for m in models:
            self._cloud_model_combo.addItem(m["name"])

        saved_model = cfg_mod.get_pref("ai.cloud.model", "")
        try:
            self._cloud_model_combo.setCurrentIndex(
                self._cloud_model_ids.index(saved_model))
        except ValueError:
            self._cloud_model_combo.setCurrentIndex(1)   # default: Recommended
        self._cloud_model_combo.blockSignals(False)

    def _update_cloud_key_link(self) -> None:
        from ai.remote_runner import CLOUD_PROVIDERS
        if not hasattr(self, "_cloud_provider_ids") \
                or not hasattr(self, "_cloud_key_link_lbl"):
            return
        idx = self._cloud_provider_combo.currentIndex() \
              if hasattr(self, "_cloud_provider_combo") else 0
        if idx < 0 or idx >= len(self._cloud_provider_ids):
            return
        pid = self._cloud_provider_ids[idx]
        url = CLOUD_PROVIDERS[pid].get("api_key_url", "")
        if url:
            name = CLOUD_PROVIDERS[pid]["name"]
            self._cloud_key_link_lbl.setText(
                f'<a href="{url}" style="color:{_ACCENT};">'
                f'Get a {name} API key ↗</a>')
        else:
            self._cloud_key_link_lbl.setText("")

    def _on_cloud_provider_changed(self, idx: int) -> None:
        if idx >= 0 and idx < len(self._cloud_provider_ids):
            cfg_mod.set_pref("ai.cloud.provider", self._cloud_provider_ids[idx])
        self._refresh_cloud_model_combo()
        self._update_cloud_key_link()

    def _on_cloud_model_changed(self, idx: int) -> None:
        if hasattr(self, "_cloud_model_ids") and 0 <= idx < len(self._cloud_model_ids):
            cfg_mod.set_pref("ai.cloud.model", self._cloud_model_ids[idx])

    def _on_cloud_key_show_toggled(self, checked: bool) -> None:
        if hasattr(self, "_cloud_key_edit"):
            self._cloud_key_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password)
        if hasattr(self, "_cloud_key_show_btn"):
            self._cloud_key_show_btn.setText("Hide" if checked else "Show")

    def _on_cloud_connect_clicked(self) -> None:
        if not hasattr(self, "_cloud_connect_btn"):
            return
        # If currently connected, disconnect
        if self._cloud_connect_btn.text() == "Disconnect":
            self.cloud_ai_disconnect_requested.emit()
            return

        provider = self._cloud_provider_ids[
            self._cloud_provider_combo.currentIndex()]
        api_key = self._cloud_key_edit.text().strip() \
                  if hasattr(self, "_cloud_key_edit") else ""
        if not api_key:
            self.set_cloud_ai_status("error", "No API key entered")
            return
        idx      = self._cloud_model_combo.currentIndex() \
                   if hasattr(self, "_cloud_model_combo") else 0
        model_id = self._cloud_model_ids[idx] \
                   if hasattr(self, "_cloud_model_ids") and \
                   0 <= idx < len(self._cloud_model_ids) else ""

        self._cloud_connect_btn.setEnabled(False)
        self.set_cloud_ai_status("loading", "◌  Connecting…")
        self.cloud_ai_connect_requested.emit(provider, api_key, model_id)

    def set_cloud_ai_status(self, status: str, message: str = "") -> None:
        """Called by MainWindow when cloud AI connection changes."""
        if not hasattr(self, "_cloud_status_lbl"):
            return
        _colors = {
            "off":      _MUTED,
            "loading":  _AMBER,
            "ready":    _GREEN,
            "error":    "#ff5555",
        }
        color = _colors.get(status, _MUTED)
        if not message:
            _msgs = {
                "off":     "○  Not connected",
                "loading": "◌  Connecting…",
                "ready":   "●  Connected",
                "error":   "⊗  Connection failed",
            }
            message = _msgs.get(status, status)
        self._cloud_status_lbl.setText(message)
        self._cloud_status_lbl.setStyleSheet(f"font-size:12pt; color:{color};")

        if hasattr(self, "_cloud_connect_btn"):
            if status == "ready":
                self._cloud_connect_btn.setText("Disconnect")
                self._cloud_connect_btn.setEnabled(True)
            elif status in ("off", "error"):
                self._cloud_connect_btn.setText("Connect")
                self._cloud_connect_btn.setEnabled(True)
            else:
                self._cloud_connect_btn.setEnabled(False)

    def _build_license_group(self) -> QGroupBox:
        """License status card with a shortcut to the License dialog."""
        g = _group("License")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # Status row
        status_row = QWidget()
        status_row.setStyleSheet("background:transparent;")
        sr_lay = QHBoxLayout(status_row)
        sr_lay.setContentsMargins(0, 0, 0, 0)
        sr_lay.setSpacing(10)

        self._lic_status_icon  = QLabel("○")
        self._lic_status_icon.setStyleSheet(f"font-size:14pt; color:{_AMBER};")
        self._lic_status_label = QLabel("Loading…")
        self._lic_status_label.setStyleSheet(f"font-size:12pt; color:{_TEXT};")

        sr_lay.addWidget(self._lic_status_icon)
        sr_lay.addWidget(self._lic_status_label, 1)

        manage_btn = QPushButton("Manage License…")
        manage_btn.setStyleSheet(_BTN_PRIMARY)
        manage_btn.setFixedHeight(30)
        manage_btn.setToolTip("View license details or activate a new key")
        manage_btn.clicked.connect(self._on_manage_license)
        sr_lay.addWidget(manage_btn)

        lay.addWidget(status_row)

        # Detail line (customer name / expiry)
        self._lic_detail_label = QLabel("")
        self._lic_detail_label.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        self._lic_detail_label.setWordWrap(True)
        lay.addWidget(self._lic_detail_label)

        # Populate immediately
        self.refresh_license_status()

        return g

    def refresh_license_status(self):
        """Re-read the current license from app_state and update the card."""
        from hardware.app_state import app_state
        from licensing.license_model import LicenseTier

        info = app_state.license_info

        if info is None or info.tier == LicenseTier.UNLICENSED:
            self._lic_status_icon.setText("○")
            self._lic_status_icon.setStyleSheet(f"font-size:14pt; color:{_AMBER};")
            self._lic_status_label.setText("Unlicensed — demo mode only")
            self._lic_status_label.setStyleSheet(f"font-size:12pt; color:{_AMBER};")
            self._lic_detail_label.setText(
                "Activate a license key to enable full hardware access.")
        else:
            days = info.days_until_expiry
            if days is not None and days <= 30:
                icon_color = _AMBER
                status_text = f"Active — expires in {days} day{'s' if days != 1 else ''}"
            else:
                icon_color = _GREEN
                status_text = "Active"

            self._lic_status_icon.setText("●")
            self._lic_status_icon.setStyleSheet(f"font-size:14pt; color:{icon_color};")
            self._lic_status_label.setText(status_text)
            self._lic_status_label.setStyleSheet(f"font-size:12pt; color:{icon_color};")

            detail_parts = [f"{info.tier_display}  ·  {info.customer}"]
            if info.email:
                detail_parts.append(info.email)
            if not info.is_perpetual:
                detail_parts.append(f"Expires {info.expires}")
            self._lic_detail_label.setText("  ·  ".join(detail_parts))

    def _on_manage_license(self):
        """Open the License dialog from the Settings tab."""
        from ui.license_dialog import LicenseDialog
        from PyQt5.QtWidgets import QApplication
        parent = QApplication.activeWindow()
        dlg = LicenseDialog(parent=parent)
        dlg.license_changed.connect(self.refresh_license_status)
        dlg.exec_()

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
            "error":    ("Local model failed — scroll down to use Ollama instead ↓",
                         "#ff8800"),
        }
        msg, color = _msgs.get(status, (status, _MUTED))
        self._ai_status_lbl.setText(msg)
        self._ai_status_lbl.setStyleSheet(f"font-size:11pt; color:{color};")
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
