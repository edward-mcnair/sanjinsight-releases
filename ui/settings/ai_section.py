"""
ui/settings/ai_section.py

AI-related settings extracted from settings_tab.py.

Contains:
  - _OllamaInstallThread / _OllamaPullThread  (background workers)
  - AISettingsMixin  (mixin injected into SettingsTab)

All methods reference ``self`` which is a SettingsTab instance at runtime.
Signals (ai_enable_requested, cloud_ai_connect_requested, …) are defined
on SettingsTab and accessed through ``self``.
"""

from __future__ import annotations

import logging
from PyQt5.QtCore    import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui     import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QFrame, QSlider,
    QLineEdit, QFileDialog, QProgressBar, QToolButton,
)

import config as cfg_mod
from ui.theme import FONT, PALETTE, MONO_FONT

from ui.settings._helpers import (
    _BG, _BG2, _BORDER, _TEXT, _MUTED, _ACCENT, _ACCENT_H,
    _GREEN, _AMBER, _DANGER,
    BTN_PRIMARY  as _BTN_PRIMARY,
    BTN_SECONDARY as _BTN_SECONDARY,
    COMBO        as _COMBO,
    CHECK        as _CHECK,
    h2           as _h2,
    body         as _body,
    sep          as _sep,
    group        as _group,
)

log = logging.getLogger(__name__)


# ── Ollama background worker threads ────────────────────────────────────────

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
                self.progress.emit(pct, f"Downloading\u2026  {pct}%  ({mb} / {total} MB)")

        try:
            self.progress.emit(0, "Connecting to ollama.com\u2026")
            urllib.request.urlretrieve(url, tmp_path, _reporthook)
            self.progress.emit(100, "Launching installer\u2026")
            subprocess.Popen([tmp_path], shell=False)
            self.finished.emit(
                True,
                "Installer launched.  Complete the setup window, "
                "then click  \u27f3 Check Again  below.",
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
                "ollama command not found \u2014 is the Ollama installation complete?",
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
                self.finished.emit(True,  f"\u2713  {self._model} is ready")
            elif self._proc.returncode in (-15, -9, 1) and \
                    self.isInterruptionRequested():
                # SIGTERM / SIGKILL / Windows terminate -> treat as user cancel
                self.finished.emit(False, "cancelled")
            else:
                self.finished.emit(
                    False, f"Pull failed (exit {self._proc.returncode})")
        except Exception as exc:
            self.finished.emit(False, str(exc))
        finally:
            self._proc = None


# ── AISettingsMixin ─────────────────────────────────────────────────────────

class AISettingsMixin:
    """
    Mixin for SettingsTab that provides all AI-related builder methods
    and event handlers.

    At runtime ``self`` is a SettingsTab (QWidget) instance.  Signals
    such as ``ai_enable_requested`` and ``cloud_ai_connect_requested``
    are defined on SettingsTab and are accessed through ``self``.
    """

    # ── Builders ─────────────────────────────────────────────────────

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

        # -- Privacy guarantee frame ------------------------------------------
        self._ai_privacy_frame = QFrame()
        privacy_frame = self._ai_privacy_frame
        privacy_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_GREEN()}55; "
            f"border-radius:5px; }}"
        )
        pf_lay = QHBoxLayout(privacy_frame)
        pf_lay.setContentsMargins(10, 8, 10, 8)
        pf_lay.setSpacing(10)

        import os as _os
        _bug_svg = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "assets", "microsanj-bug.svg")
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
            lock_lbl = QLabel("\U0001f512")
            lock_lbl.setStyleSheet(f"font-size:{FONT['readoutSm']}pt; border:none;")
            lock_lbl.setFixedWidth(28)
            pf_lay.addWidget(lock_lbl)

        privacy_text = QLabel(
            "<b>Privacy guarantee:</b> the AI assistant runs 100% locally on "
            "this machine. It never communicates with external servers, cloud "
            "services, or the internet under any circumstances."
        )
        privacy_text.setWordWrap(True)
        privacy_text.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_GREEN()}; border:none;")
        pf_lay.addWidget(privacy_text, 1)
        lay.addWidget(privacy_frame)

        # -- Check if llama-cpp-python is available ----------------------------
        from ai.model_runner import llama_available as _llama_ok
        self._llama_available = _llama_ok()

        if not self._llama_available:
            # Show a helpful message instead of the broken local-model UI
            self._ai_no_llama_frame = QFrame()
            nf = self._ai_no_llama_frame
            nf.setStyleSheet(
                f"QFrame {{ background:{_BG2()}; border:1px solid {_AMBER()}55; "
                f"border-radius:5px; }}")
            nf_lay = QVBoxLayout(nf)
            nf_lay.setContentsMargins(12, 10, 12, 10)
            nf_lay.setSpacing(6)
            nf_title = QLabel("Local AI runtime not installed")
            nf_title.setStyleSheet(
                f"font-size:{FONT['label']}pt; font-weight:bold; "
                f"color:{_AMBER()}; border:none;")
            nf_lay.addWidget(nf_title)
            nf_body = QLabel(
                "The <b>llama-cpp-python</b> package is required for local "
                "GGUF model inference but is not installed on this machine."
                "<br><br>"
                "You can still use AI through <b>Cloud AI</b> (Claude or "
                "ChatGPT with an API key) or <b>Ollama</b> (free, local, "
                "no Python compilation needed) in the section below."
                "<br><br>"
                "<i>To install the local runtime later:</i><br>"
                "<code>pip install llama-cpp-python</code>")
            nf_body.setWordWrap(True)
            nf_body.setTextFormat(Qt.RichText)
            nf_body.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_TEXT()}; border:none;")
            nf_lay.addWidget(nf_body)
            lay.addWidget(nf)

            # Hide the download/enable controls -- skip the rest of the group
            self._ai_disabled_notice = QLabel()
            self._ai_disabled_notice.setVisible(False)
            self._ai_enable_chk = QCheckBox()
            self._ai_enable_chk.setVisible(False)
            self._ai_download_widget = QWidget()
            self._ai_download_widget.setVisible(False)
            # Create stub attributes so the rest of the code doesn't crash
            self._ai_model_combo = QComboBox()
            self._ai_model_ids = []
            self._ai_path_edit = QLineEdit()
            self._ai_gpu_slider = QSlider()
            self._ai_status_lbl = QLabel()
            self._ai_load_btn = QPushButton()
            self._ai_dl_btn = QPushButton()
            self._ai_dl_progress = QProgressBar()
            return g

        # -- "AI disabled" notice (hidden when enabled) ------------------------
        self._ai_disabled_notice = _body(
            "AI Assistant is currently disabled. Enable the checkbox below "
            "and download a model to get started."
        )
        lay.addWidget(self._ai_disabled_notice)

        # -- Enable toggle -----------------------------------------------------
        self._ai_enable_chk = QCheckBox("Enable AI Assistant")
        self._ai_enable_chk.setStyleSheet(_CHECK())
        self._ai_enable_chk.setChecked(cfg_mod.get_pref("ai.enabled", False))
        self._ai_enable_chk.toggled.connect(self._on_ai_enable_changed)
        lay.addWidget(self._ai_enable_chk)

        # -- Download section (visible when enabled) ---------------------------
        self._ai_download_widget = QWidget()
        dl_lay = QVBoxLayout(self._ai_download_widget)
        dl_lay.setContentsMargins(0, 0, 0, 0)
        dl_lay.setSpacing(8)

        # Hardware summary card
        self._ai_hw_frame = QFrame()
        hw_frame = self._ai_hw_frame
        hw_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_BORDER()}; "
            f"border-radius:4px; }}"
        )
        hw_lay = QHBoxLayout(hw_frame)
        hw_lay.setContentsMargins(10, 6, 10, 6)
        hw_icon = QLabel("\U0001f4bb")
        hw_icon.setStyleSheet(f"font-size:{FONT['heading']}pt; border:none;")
        hw_icon.setFixedWidth(24)
        hw_lay.addWidget(hw_icon)
        hw_lbl = QLabel(_hw.hw_summary or "Hardware details unavailable")
        hw_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_TEXT()}; border:none;")
        hw_lbl.setWordWrap(True)
        hw_lay.addWidget(hw_lbl, 1)
        dl_lay.addWidget(hw_frame)

        # Model selector combo
        combo_row = QHBoxLayout()
        combo_lbl = QLabel("Select model:")
        combo_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        combo_row.addWidget(combo_lbl)

        self._ai_model_ids = list(MODEL_ORDER)
        self._ai_model_combo = QComboBox()
        self._ai_model_combo.setMaximumWidth(360)
        self._ai_model_combo.setStyleSheet(_COMBO())
        for mid in self._ai_model_ids:
            m   = MODEL_CATALOG[mid]
            tag = "  \u2713 Recommended" if mid == _hw.recommended_model_id else ""
            self._ai_model_combo.addItem(
                f"{m['name']}  \u00b7  {m['size_gb']:.1f} GB{tag}")
        # Pre-select the recommended model
        try:
            rec_idx = self._ai_model_ids.index(_hw.recommended_model_id)
        except ValueError:
            rec_idx = 0
        self._ai_model_combo.setCurrentIndex(rec_idx)
        self._ai_model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        combo_row.addWidget(self._ai_model_combo)
        combo_row.addStretch()
        dl_lay.addLayout(combo_row)

        # Model description + recommendation reason
        self._ai_model_desc_lbl = _body(
            MODEL_CATALOG[self._ai_model_ids[rec_idx]]["description"])
        dl_lay.addWidget(self._ai_model_desc_lbl)

        self._ai_rec_reason_lbl = _body(_hw.rec_reason)
        self._ai_rec_reason_lbl.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_GREEN()};")
        dl_lay.addWidget(self._ai_rec_reason_lbl)

        # Auto-fill GPU layers with hardware recommendation
        # (applied after the spinner is built, stored here for deferred use)
        self._ai_probe_gpu_layers = _hw.recommended_n_gpu_layers

        # Download / Cancel buttons
        dl_btn_row = QHBoxLayout()
        self._ai_download_btn = QPushButton("Download Selected Model")
        self._ai_download_btn.setStyleSheet(_BTN_PRIMARY())
        self._ai_download_btn.clicked.connect(self._on_download_clicked)
        dl_btn_row.addWidget(self._ai_download_btn)

        self._ai_cancel_btn = QPushButton("Cancel")
        self._ai_cancel_btn.setStyleSheet(_BTN_SECONDARY())
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
            f"QProgressBar {{ background:{_BG2()}; border:1px solid {_BORDER()}; "
            f"border-radius:4px; font-size:{FONT['caption']}pt; color:{_TEXT()}; }}"
            f"QProgressBar::chunk {{ background:{_GREEN()}; border-radius:3px; }}"
        )
        dl_lay.addWidget(self._ai_progress_bar)

        self._ai_dl_status_lbl = QLabel("")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._ai_dl_status_lbl.setVisible(False)
        dl_lay.addWidget(self._ai_dl_status_lbl)

        lay.addWidget(self._ai_download_widget)

        # -- Model path row ----------------------------------------------------
        path_row = QHBoxLayout()
        path_lbl = QLabel("Model file (.gguf):")
        path_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        path_row.addWidget(path_lbl)

        self._ai_path_edit = QLineEdit()
        self._ai_path_edit.setPlaceholderText("Path to .gguf model file\u2026")
        self._ai_path_edit.setText(cfg_mod.get_pref("ai.model_path", ""))
        self._ai_path_edit.setStyleSheet(
            f"QLineEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; padding:5px 8px; }}"
        )
        self._ai_path_edit.textChanged.connect(
            lambda t: cfg_mod.set_pref("ai.model_path", t))
        path_row.addWidget(self._ai_path_edit, 1)

        self._ai_browse_btn = QPushButton("Browse\u2026")
        browse_btn = self._ai_browse_btn
        browse_btn.setStyleSheet(_BTN_SECONDARY())
        browse_btn.setFixedWidth(120)  # was 90 -- too narrow for "Browse..." at 12pt + 18px padding
        browse_btn.clicked.connect(self._browse_model)
        path_row.addWidget(browse_btn)
        lay.addLayout(path_row)

        # -- GPU acceleration slider -------------------------------------------
        gpu_section_lbl = QLabel("GPU acceleration")
        gpu_section_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        lay.addWidget(gpu_section_lbl)

        _init_n_layers = MODEL_CATALOG[self._ai_model_ids[rec_idx]].get("n_layers", 32)

        self._ai_gpu_slider = QSlider(Qt.Horizontal)
        self._ai_gpu_slider.setMinimum(0)
        self._ai_gpu_slider.setMaximum(_init_n_layers)
        self._ai_gpu_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background:{_BG2()}; border:1px solid {_BORDER()};
                height:6px; border-radius:3px;
            }}
            QSlider::handle:horizontal {{
                background:{_ACCENT()}; border:none;
                width:16px; height:16px; margin:-5px 0;
                border-radius:8px;
            }}
            QSlider::sub-page:horizontal {{
                background:{_ACCENT()}55; border-radius:3px;
            }}
            QSlider:disabled::handle:horizontal {{ background:{_BORDER()}; }}
            QSlider:disabled::sub-page:horizontal {{ background:{_BG2()}; }}
        """)

        slider_row = QHBoxLayout()
        cpu_end = QLabel("CPU")
        cpu_end.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_MUTED()};")
        cpu_end.setFixedWidth(36)
        slider_row.addWidget(cpu_end)
        slider_row.addWidget(self._ai_gpu_slider, 1)
        gpu_end = QLabel("Full GPU")
        gpu_end.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_MUTED()};")
        gpu_end.setFixedWidth(60)
        gpu_end.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider_row.addWidget(gpu_end)
        lay.addLayout(slider_row)

        self._ai_gpu_label = QLabel("")
        self._ai_gpu_label.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
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

        # -- Load Model / status row -------------------------------------------
        apply_row = QHBoxLayout()
        self._ai_apply_btn = QPushButton("Load Model")
        self._ai_apply_btn.setStyleSheet(_BTN_PRIMARY())
        self._ai_apply_btn.setFixedWidth(120)
        self._ai_apply_btn.clicked.connect(self._on_ai_apply)
        apply_row.addWidget(self._ai_apply_btn)

        self._ai_status_lbl = QLabel("")
        self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        apply_row.addWidget(self._ai_status_lbl, 1)
        lay.addLayout(apply_row)

        # -- Tier info strip (hidden until a model loads) ----------------------
        self._ai_tier_frame = QFrame()
        self._ai_tier_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_BORDER()}; "
            f"border-radius:4px; }}")
        tier_lay = QHBoxLayout(self._ai_tier_frame)
        tier_lay.setContentsMargins(10, 6, 10, 6)
        tier_lay.setSpacing(8)

        self._ai_tier_badge = QLabel("")
        self._ai_tier_badge.setStyleSheet(
            f"font-size:{FONT['caption']}pt; font-weight:700; color:{_MUTED()}; "
            f"background:{_BG()}; border:1px solid {_BORDER()}; "
            f"border-radius:3px; padding:2px 8px;")
        tier_lay.addWidget(self._ai_tier_badge)

        self._ai_tier_desc = QLabel("")
        self._ai_tier_desc.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_MUTED()};")
        self._ai_tier_desc.setWordWrap(True)
        tier_lay.addWidget(self._ai_tier_desc, 1)

        self._ai_tier_frame.setVisible(False)
        lay.addWidget(self._ai_tier_frame)

        # -- AI Mode (persona) -------------------------------------------------
        from ai.personas import PERSONAS, PERSONA_ORDER, DEFAULT_PERSONA_ID

        mode_lbl = QLabel("AI Mode")
        mode_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
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
                    background:{_BG2()}; color:{_MUTED()};
                    border:1px solid {_BORDER()}; border-radius:5px;
                    padding:6px 14px; font-size:{FONT["sublabel"]}pt;
                }}
                QPushButton:checked {{
                    background:{_ACCENT()}22; color:{_TEXT()};
                    border:1px solid {_ACCENT()};
                }}
                QPushButton:hover:!checked {{ background:{_BG()}; color:{_TEXT()}; }}
            """)
            btn.clicked.connect(lambda checked, _pid=pid: self._on_persona_clicked(_pid))
            mode_row.addWidget(btn)
            self._ai_persona_btns[pid] = btn
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        self._ai_persona_desc_lbl = _body(PERSONAS[_saved_pid].description)
        lay.addWidget(self._ai_persona_desc_lbl)

        lay.addWidget(_sep())

        # -- Knowledge scope ---------------------------------------------------
        scope_lbl = QLabel("AI knowledge scope")
        scope_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        lay.addWidget(scope_lbl)

        from version import DOCS_URL
        from ai.manual_rag import _load_sections

        qs_always_lbl = QLabel(
            "\u2713  Quickstart Guide \u2014 always included in every AI response.")
        qs_always_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_GREEN()};")
        lay.addWidget(qs_always_lbl)

        n_manual_sections = len(_load_sections())
        if n_manual_sections:
            rag_lbl = QLabel(
                f"\u2713  User Manual \u2014 {n_manual_sections} sections indexed for "
                "context-aware answers.")
        else:
            rag_lbl = QLabel(
                "\u26a0  User Manual not found \u2014 docs/ directory missing or not bundled.")
        rag_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_GREEN() if n_manual_sections else _AMBER()};")
        lay.addWidget(rag_lbl)

        qs_note_lbl = QLabel(
            "Out-of-scope questions receive a link to the full User Manual at "
            + DOCS_URL)
        qs_note_lbl.setWordWrap(True)
        qs_note_lbl.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_MUTED()};")
        lay.addWidget(qs_note_lbl)

        # Auto-detect existing model from ~/.microsanj/models/
        existing = find_existing_model(DEFAULT_MODELS_DIR)
        if existing and not cfg_mod.get_pref("ai.model_path", ""):
            self._ai_path_edit.setText(existing)
            cfg_mod.set_pref("ai.model_path", existing)
            self._ai_status_lbl.setText("Model found \u2014 click Load Model to enable")
            self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_GREEN()};")

        self._update_ai_controls()
        return g

    def _build_alt_ai_container(self) -> QGroupBox:
        """
        Collapsible wrapper that groups Cloud AI and Ollama under a single
        'Alternative AI Sources' header.  Both sections stay intact inside;
        users who don't need cloud/Ollama see just one collapsed row.
        """
        g = _group("Alternative AI Sources  (Cloud / Ollama)")
        outer = QVBoxLayout(g)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # -- Toggle button -----------------------------------------------------
        toggle = QToolButton()
        toggle.setText("\u25b8  Show Cloud AI and Ollama options")
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setStyleSheet(
            f"QToolButton {{ border:none; color:{_MUTED()}; "
            f"font-size:{FONT['sublabel']}pt; padding:6px 0; "
            f"background:transparent; text-align:left; }}"
            f"QToolButton:checked {{ color:{_TEXT()}; }}"
        )
        outer.addWidget(toggle)

        # -- Collapsible body --------------------------------------------------
        body = QWidget()
        body.setVisible(False)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 8, 0, 0)
        body_lay.setSpacing(12)
        body_lay.addWidget(self._build_cloud_ai_group())
        body_lay.addWidget(self._build_ollama_group())
        outer.addWidget(body)

        def _toggle(checked: bool):
            body.setVisible(checked)
            toggle.setText(
                ("\u25be  Hide" if checked else "\u25b8  Show")
                + "  Cloud AI and Ollama options"
            )

        toggle.toggled.connect(_toggle)
        self._alt_ai_toggle = toggle

        # Auto-expand when local AI is unavailable so users find the
        # working alternatives immediately.
        if not getattr(self, "_llama_available", True):
            toggle.setChecked(True)

        return g

    def _build_cloud_ai_group(self) -> QGroupBox:
        from ai.remote_runner import CLOUD_PROVIDERS

        g = _group("Cloud AI  (Optional \u2014 requires API key)")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # -- Privacy notice ----------------------------------------------------
        warn_frame = QFrame()
        warn_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_AMBER()}55; "
            f"border-radius:5px; }}"
        )
        wf_lay = QHBoxLayout(warn_frame)
        wf_lay.setContentsMargins(10, 8, 10, 8)
        wf_lay.setSpacing(10)
        warn_icon = QLabel("\u26a0")
        warn_icon.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{_AMBER()}; border:none;")
        warn_icon.setFixedWidth(22)
        wf_lay.addWidget(warn_icon)
        warn_text = QLabel(
            "Questions and instrument data will be sent to the provider's servers. "
            "Do not use Cloud AI if your work is confidential or export-controlled."
        )
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_AMBER()}; border:none;")
        wf_lay.addWidget(warn_text, 1)
        lay.addWidget(warn_frame)

        # -- Provider selector -------------------------------------------------
        provider_row = QHBoxLayout()
        provider_lbl = QLabel("Provider:")
        provider_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        provider_row.addWidget(provider_lbl)

        self._cloud_provider_combo = QComboBox()
        self._cloud_provider_combo.setMaximumWidth(300)
        self._cloud_provider_combo.setStyleSheet(_COMBO())
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
        provider_row.addWidget(self._cloud_provider_combo)
        provider_row.addStretch()
        lay.addLayout(provider_row)

        # -- Model selector ----------------------------------------------------
        model_row = QHBoxLayout()
        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        model_row.addWidget(model_lbl)

        self._cloud_model_combo = QComboBox()
        self._cloud_model_combo.setMaximumWidth(360)
        self._cloud_model_combo.setStyleSheet(_COMBO())
        self._cloud_model_ids: list[str] = []
        self._cloud_model_combo.currentIndexChanged.connect(
            self._on_cloud_model_changed)
        model_row.addWidget(self._cloud_model_combo)
        model_row.addStretch()
        lay.addLayout(model_row)

        # Populate model combo from initial provider selection
        self._refresh_cloud_model_combo()

        # -- API key input -----------------------------------------------------
        key_row = QHBoxLayout()
        key_lbl = QLabel("API Key:")
        key_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        key_row.addWidget(key_lbl)

        self._cloud_key_edit = QLineEdit()
        self._cloud_key_edit.setPlaceholderText("Paste your API key here\u2026")
        self._cloud_key_edit.setEchoMode(QLineEdit.Password)
        self._cloud_key_edit.setStyleSheet(
            f"QLineEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; padding:5px 8px; }}"
        )
        saved_key = cfg_mod.get_pref("ai.cloud.api_key", "")
        self._cloud_key_edit.setText(saved_key)
        self._cloud_key_edit.textChanged.connect(
            lambda t: cfg_mod.set_pref("ai.cloud.api_key", t))
        key_row.addWidget(self._cloud_key_edit, 1)

        self._cloud_key_show_btn = QPushButton("Show")
        self._cloud_key_show_btn.setStyleSheet(_BTN_SECONDARY())
        self._cloud_key_show_btn.setFixedWidth(70)
        self._cloud_key_show_btn.setCheckable(True)
        self._cloud_key_show_btn.toggled.connect(self._on_cloud_key_show_toggled)
        key_row.addWidget(self._cloud_key_show_btn)
        lay.addLayout(key_row)

        # Get key link
        self._cloud_key_link_lbl = QLabel("")
        self._cloud_key_link_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_ACCENT()};")
        self._cloud_key_link_lbl.setOpenExternalLinks(True)
        lay.addWidget(self._cloud_key_link_lbl)
        self._update_cloud_key_link()

        lay.addWidget(_sep())

        # -- Connect / Disconnect row ------------------------------------------
        action_row = QHBoxLayout()
        self._cloud_connect_btn = QPushButton("Connect")
        self._cloud_connect_btn.setStyleSheet(_BTN_PRIMARY())
        self._cloud_connect_btn.setFixedWidth(120)
        self._cloud_connect_btn.clicked.connect(self._on_cloud_connect_clicked)
        action_row.addWidget(self._cloud_connect_btn)

        self._cloud_status_lbl = QLabel("\u25cb  Not connected")
        self._cloud_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        action_row.addWidget(self._cloud_status_lbl, 1)
        lay.addLayout(action_row)

        return g

    # -- Ollama (local AI server) ------------------------------------------

    def _build_ollama_group(self) -> QGroupBox:
        g = _group("Ollama  (Local AI Server \u2014 free, private, GPU-accelerated)")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # -- Description -------------------------------------------------------
        desc = QLabel(
            "Ollama runs AI models locally on your PC \u2014 no internet or API key needed. "
            "It supports dozens of open-source models (Llama 3, Mistral, Gemma \u2026) "
            "and uses your GPU automatically when available.  "
            "SanjINSIGHT connects to the Ollama server running on this machine."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        lay.addWidget(desc)

        # -- Install Ollama box (hidden when already installed) ----------------
        self._ollama_install_box = QFrame()
        self._ollama_install_box.setStyleSheet(
            f"background:{_BG2()}; border:1px solid {PALETTE['warning']}55; border-radius:6px;")
        ib = QVBoxLayout(self._ollama_install_box)
        ib.setContentsMargins(14, 12, 14, 12)
        ib.setSpacing(8)

        install_notice = QLabel("Ollama is not installed on this machine.")
        install_notice.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; color:{_AMBER()};")
        ib.addWidget(install_notice)

        install_hint = QLabel(
            "Ollama is a free, lightweight AI server.  "
            "Click below and it will download and install automatically "
            "(Windows), or open the download page on other systems.")
        install_hint.setWordWrap(True)
        install_hint.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        ib.addWidget(install_hint)

        btn_link_row = QHBoxLayout()
        self._ollama_install_btn = QPushButton("\u2b07  Install Ollama for me")
        self._ollama_install_btn.setStyleSheet(_BTN_PRIMARY())
        self._ollama_install_btn.setFixedWidth(230)
        self._ollama_install_btn.clicked.connect(self._on_install_ollama_clicked)
        btn_link_row.addWidget(self._ollama_install_btn)
        btn_link_row.addSpacing(16)

        manual_link = QLabel(
            f'or &nbsp;<a href="https://ollama.com/download" style="color:{_ACCENT()};">'
            "download manually \u2197</a>")
        manual_link.setOpenExternalLinks(True)
        manual_link.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        btn_link_row.addWidget(manual_link)
        btn_link_row.addStretch(1)
        ib.addLayout(btn_link_row)

        self._ollama_install_prog = QProgressBar()
        self._ollama_install_prog.setRange(0, 100)
        self._ollama_install_prog.setTextVisible(True)
        self._ollama_install_prog.setFixedHeight(18)
        self._ollama_install_prog.setVisible(False)
        ib.addWidget(self._ollama_install_prog)

        # Cancel button -- visible only while the download is in progress.
        self._ollama_install_cancel_btn = QPushButton("\u2715  Cancel Download")
        self._ollama_install_cancel_btn.setStyleSheet(_BTN_SECONDARY())
        self._ollama_install_cancel_btn.setFixedWidth(180)
        self._ollama_install_cancel_btn.setVisible(False)
        self._ollama_install_cancel_btn.clicked.connect(
            self._on_install_cancel_clicked)
        ib.addWidget(self._ollama_install_cancel_btn)

        self._ollama_install_msg = QLabel("")
        self._ollama_install_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._ollama_install_msg.setWordWrap(True)
        self._ollama_install_msg.setVisible(False)
        ib.addWidget(self._ollama_install_msg)

        lay.addWidget(self._ollama_install_box)

        # -- Pull model box (shown when installed but no models yet) -----------
        self._ollama_pull_box = QFrame()
        self._ollama_pull_box.setStyleSheet(
            f"background:{_BG2()}; border:1px solid {PALETTE['accent']}55; border-radius:6px;")
        pb2 = QVBoxLayout(self._ollama_pull_box)
        pb2.setContentsMargins(14, 12, 14, 12)
        pb2.setSpacing(8)

        pull_notice = QLabel("\u2713  Ollama installed.  Download a model to get started:")
        pull_notice.setStyleSheet(f"font-size:{FONT['label']}pt; font-weight:600; color:{_GREEN()};")
        pb2.addWidget(pull_notice)

        pull_hint = QLabel(
            "Phi-3 Mini is recommended (2.3 GB, works well on 4 GB GPU)."
            "  Mistral / Llama 3 are larger but more capable.")
        pull_hint.setWordWrap(True)
        pull_hint.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        pb2.addWidget(pull_hint)

        pull_row = QHBoxLayout()
        pull_lbl = QLabel("Model:")
        pull_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        pull_lbl.setFixedWidth(55)
        pull_row.addWidget(pull_lbl)

        self._ollama_pull_combo = QComboBox()
        self._ollama_pull_combo.setMaximumWidth(360)
        self._ollama_pull_combo.setStyleSheet(_COMBO())
        for m in ["phi3", "phi3:mini", "mistral", "llama3:8b", "gemma2:2b"]:
            self._ollama_pull_combo.addItem(m)
        self._ollama_pull_combo.setCurrentText("phi3")
        pull_row.addWidget(self._ollama_pull_combo)

        self._ollama_pull_btn = QPushButton("\u2b07  Pull Model")
        self._ollama_pull_btn.setStyleSheet(_BTN_PRIMARY())
        self._ollama_pull_btn.setFixedWidth(140)
        self._ollama_pull_btn.clicked.connect(self._on_pull_model_clicked)
        pull_row.addWidget(self._ollama_pull_btn)

        # Cancel button shown next to Pull Model while pulling.
        self._ollama_pull_cancel_btn = QPushButton("\u2715  Cancel")
        self._ollama_pull_cancel_btn.setStyleSheet(_BTN_SECONDARY())
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
        self._ollama_pull_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._ollama_pull_msg.setWordWrap(True)
        self._ollama_pull_msg.setVisible(False)
        pb2.addWidget(self._ollama_pull_msg)

        lay.addWidget(self._ollama_pull_box)

        lay.addWidget(_sep())

        # -- Model selector + Refresh ------------------------------------------
        model_row = QHBoxLayout()
        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        model_lbl.setFixedWidth(70)
        model_row.addWidget(model_lbl)

        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setMaximumWidth(360)
        self._ollama_model_combo.setStyleSheet(_COMBO())
        self._ollama_model_combo.setEditable(False)
        self._ollama_model_combo.setPlaceholderText("(refresh to load installed models)")
        model_row.addWidget(self._ollama_model_combo)

        self._ollama_refresh_btn = QPushButton("\u27f3 Check Again")
        self._ollama_refresh_btn.setStyleSheet(_BTN_SECONDARY())
        self._ollama_refresh_btn.setFixedWidth(120)
        self._ollama_refresh_btn.setToolTip(
            "Re-detect Ollama and refresh the model list")
        self._ollama_refresh_btn.clicked.connect(self._ollama_refresh_models)
        model_row.addWidget(self._ollama_refresh_btn)
        lay.addLayout(model_row)

        # -- Status + Connect row ----------------------------------------------
        action_row = QHBoxLayout()
        self._ollama_connect_btn = QPushButton("Connect")
        self._ollama_connect_btn.setStyleSheet(_BTN_PRIMARY())
        self._ollama_connect_btn.setFixedWidth(120)
        self._ollama_connect_btn.clicked.connect(self._on_ollama_connect_clicked)
        action_row.addWidget(self._ollama_connect_btn)

        self._ollama_status_lbl = QLabel("\u25cb  Not connected")
        self._ollama_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        action_row.addWidget(self._ollama_status_lbl, 1)
        lay.addLayout(action_row)

        # Pre-populate models from a saved preference or live query
        self._ollama_refresh_models(silent=True)
        return g

    # ── Ollama handlers ──────────────────────────────────────────────

    def _ollama_refresh_models(self, silent: bool = False) -> None:
        """
        Detect Ollama state and update the UI accordingly.

        State machine
        -------------
        NOT INSTALLED -> show install box, hide pull box, set status "not installed"
        INSTALLED, NOT RUNNING -> hide both boxes, report "not running"
        RUNNING, NO MODELS -> hide install box, show pull box, report "pull needed"
        RUNNING, MODELS OK -> hide both boxes, populate combo, report "ready"
        """
        from ai.remote_runner import (
            get_ollama_models, is_ollama_running, is_ollama_installed,
        )
        if not hasattr(self, "_ollama_model_combo"):
            return

        # -- 1. Is Ollama installed? -------------------------------------------
        installed = is_ollama_installed()
        if hasattr(self, "_ollama_install_box"):
            self._ollama_install_box.setVisible(not installed)

        if not installed:
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(False)
            self._ollama_status_lbl.setText(
                "\u2297  Ollama is not installed \u2014 use the Install button above")
            self._ollama_status_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{_AMBER()};")
            return

        # -- 2. Is the Ollama server running? ----------------------------------
        running = is_ollama_running(timeout=1.5)
        if not running:
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(False)
            if not silent:
                self._ollama_status_lbl.setText(
                    "\u2297  Ollama installed but not running \u2014 "
                    "launch the Ollama app, then click  \u27f3 Check Again")
                self._ollama_status_lbl.setStyleSheet(
                    f"font-size:{FONT['label']}pt; color:{_DANGER()};")
            return

        # -- 3. Any models pulled? ---------------------------------------------
        models = get_ollama_models()
        self._ollama_model_combo.blockSignals(True)
        self._ollama_model_combo.clear()

        if not models:
            # Running but empty -- show the pull section
            if hasattr(self, "_ollama_pull_box"):
                self._ollama_pull_box.setVisible(True)
            self._ollama_model_ids = []
            self._ollama_status_lbl.setText(
                "\u26a0  No models pulled yet \u2014 use the Pull Model section above")
            self._ollama_status_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{_AMBER()};")
            self._ollama_model_combo.blockSignals(False)
            return

        # -- 4. All good -- populate combo and report ready --------------------
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
            f"\u2713  Ollama ready \u2014 {len(models)} model(s) \u2014 click Connect")
        self._ollama_status_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_GREEN()};")

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
        self.set_ollama_status("loading", "\u25cc  Connecting to Ollama\u2026")
        self.ollama_connect_requested.emit(model_id)

    def set_ollama_status(self, status: str, message: str = "") -> None:
        """
        Called by main_app.py when the Ollama connection state changes.

        status: "loading" | "ready" | "error" | "off"
        """
        if not hasattr(self, "_ollama_status_lbl"):
            return
        if status == "loading":
            self._ollama_status_lbl.setText(message or "\u25cc  Connecting\u2026")
            self._ollama_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
            self._ollama_connect_btn.setEnabled(False)
        elif status == "ready":
            self._ollama_status_lbl.setText("\u25cf  Connected")
            self._ollama_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_GREEN()};")
            self._ollama_connect_btn.setText("Disconnect")
            self._ollama_connect_btn.setEnabled(True)
        elif status == "error":
            self._ollama_status_lbl.setText(f"\u2297  {message}" if message else "\u2297  Error")
            self._ollama_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_DANGER()};")
            self._ollama_connect_btn.setText("Connect")
            self._ollama_connect_btn.setEnabled(True)
        else:   # "off"
            self._ollama_status_lbl.setText("\u25cb  Not connected")
            self._ollama_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
            self._ollama_connect_btn.setText("Connect")
            self._ollama_connect_btn.setEnabled(True)

    # -- Ollama install / pull handlers ----------------------------------------

    def _on_install_ollama_clicked(self) -> None:
        """
        Triggered by the  Download Install Ollama for me  button.

        * Windows -- downloads OllamaSetup.exe to the system temp folder via a
          background thread, then launches it; a progress bar shows download
          progress.
        * macOS / Linux -- opens https://ollama.com/download in the browser
          (the native packages are not trivially installable by the app).

        After the installer is launched, the user completes installation
        normally and then clicks  Check Again  to re-detect Ollama.
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
            self._ollama_install_msg.setText("Connecting to ollama.com\u2026")
            self._ollama_install_msg.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
            self._ollama_install_msg.setVisible(True)

            self._install_thread = _OllamaInstallThread(self)
            self._install_thread.progress.connect(self._on_install_progress)
            self._install_thread.finished.connect(self._on_install_finished)
            self._install_thread.start()
        else:
            # macOS / Linux -- open the download page
            QDesktopServices.openUrl(QUrl("https://ollama.com/download"))
            if hasattr(self, "_ollama_install_msg"):
                self._ollama_install_msg.setText(
                    "Opened  ollama.com/download  in your browser.  "
                    "Install Ollama, then click  \u27f3 Check Again.")
                self._ollama_install_msg.setStyleSheet(
                    f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
                self._ollama_install_msg.setVisible(True)

    def _on_install_progress(self, pct: int, msg: str) -> None:
        if hasattr(self, "_ollama_install_prog"):
            self._ollama_install_prog.setValue(pct)
        if hasattr(self, "_ollama_install_msg"):
            self._ollama_install_msg.setText(msg)

    def _on_install_cancel_clicked(self) -> None:
        """User hit Cancel Download -- interrupt the download thread."""
        if hasattr(self, "_install_thread") and self._install_thread.isRunning():
            self._install_thread.requestInterruption()
        if hasattr(self, "_ollama_install_cancel_btn"):
            self._ollama_install_cancel_btn.setEnabled(False)
            self._ollama_install_cancel_btn.setText("Cancelling\u2026")

    def _on_install_finished(self, ok: bool, msg: str) -> None:
        if hasattr(self, "_ollama_install_prog"):
            self._ollama_install_prog.setVisible(False)
        if hasattr(self, "_ollama_install_cancel_btn"):
            self._ollama_install_cancel_btn.setVisible(False)
            self._ollama_install_cancel_btn.setEnabled(True)
            self._ollama_install_cancel_btn.setText("\u2715  Cancel Download")
        _cancelled = (msg == "cancelled")
        if hasattr(self, "_ollama_install_msg"):
            self._ollama_install_msg.setText(
                "Download cancelled." if _cancelled else msg)
            self._ollama_install_msg.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_MUTED() if _cancelled else (_GREEN() if ok else _DANGER())};")
        if hasattr(self, "_ollama_install_btn"):
            self._ollama_install_btn.setEnabled(True)
            if ok:
                self._ollama_install_btn.setText("\u27f3 Check Again")
        # After a successful launch wait a moment, then re-detect
        if ok:
            QTimer.singleShot(4000, lambda: self._ollama_refresh_models(silent=False))

    def _on_pull_model_clicked(self) -> None:
        """Triggered by the  Pull Model  button; runs  ollama pull <model>."""
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
            f"Downloading  {model} \u2026  (this may take a few minutes)")
        self._ollama_pull_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
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
        """User hit Cancel -- terminate the ollama pull subprocess."""
        if hasattr(self, "_pull_thread") and self._pull_thread.isRunning():
            self._pull_thread.requestInterruption()
            self._pull_thread.cancel()
        if hasattr(self, "_ollama_pull_cancel_btn"):
            self._ollama_pull_cancel_btn.setEnabled(False)
            self._ollama_pull_cancel_btn.setText("Cancelling\u2026")

    def _on_pull_finished(self, ok: bool, msg: str) -> None:
        if hasattr(self, "_ollama_pull_prog"):
            self._ollama_pull_prog.setVisible(False)
        if hasattr(self, "_ollama_pull_cancel_btn"):
            self._ollama_pull_cancel_btn.setVisible(False)
            self._ollama_pull_cancel_btn.setEnabled(True)
            self._ollama_pull_cancel_btn.setText("\u2715  Cancel")
        if hasattr(self, "_ollama_pull_btn"):
            self._ollama_pull_btn.setEnabled(True)
        _cancelled = (msg == "cancelled")
        if hasattr(self, "_ollama_pull_msg"):
            self._ollama_pull_msg.setText(
                "Pull cancelled." if _cancelled else msg)
            self._ollama_pull_msg.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_MUTED() if _cancelled else (_GREEN() if ok else _DANGER())};")
        if ok:
            # Re-detect -- pull box will hide and model combo will populate
            QTimer.singleShot(500, lambda: self._ollama_refresh_models(silent=False))

    # -- Cloud AI helpers --------------------------------------------------

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
                f'<a href="{url}" style="color:{_ACCENT()};">'
                f'Get a {name} API key \u2197</a>')
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
        self.set_cloud_ai_status("loading", "\u25cc  Connecting\u2026")
        self.cloud_ai_connect_requested.emit(provider, api_key, model_id)

    def set_cloud_ai_status(self, status: str, message: str = "") -> None:
        """Called by MainWindow when cloud AI connection changes."""
        if not hasattr(self, "_cloud_status_lbl"):
            return
        _colors = {
            "off":      _MUTED(),
            "loading":  _AMBER(),
            "ready":    _GREEN(),
            "error":    PALETTE['danger'],
        }
        color = _colors.get(status, _MUTED())
        if not message:
            _msgs = {
                "off":     "\u25cb  Not connected",
                "loading": "\u25cc  Connecting\u2026",
                "ready":   "\u25cf  Connected",
                "error":   "\u2297  Connection failed",
            }
            message = _msgs.get(status, status)
        self._cloud_status_lbl.setText(message)
        self._cloud_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{color};")

        if hasattr(self, "_cloud_connect_btn"):
            if status == "ready":
                self._cloud_connect_btn.setText("Disconnect")
                self._cloud_connect_btn.setEnabled(True)
            elif status in ("off", "error"):
                self._cloud_connect_btn.setText("Connect")
                self._cloud_connect_btn.setEnabled(True)
            else:
                self._cloud_connect_btn.setEnabled(False)

    # -- Local AI handlers -------------------------------------------------

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
            self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{PALETTE['danger']};")
            return
        n_gpu = self._ai_gpu_slider.value()
        self._ai_apply_btn.setEnabled(False)
        self._ai_status_lbl.setText("Loading\u2026")
        self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{PALETTE['warning']};")
        self.ai_enable_requested.emit(path, n_gpu)

    def set_ai_status(self, status: str) -> None:
        """Called by MainWindow when AIService.status_changed fires."""
        if not hasattr(self, "_ai_status_lbl"):
            return
        _msgs = {
            "off":      ("Off", _MUTED()),
            "loading":  ("Loading model\u2026", PALETTE['warning']),
            "ready":    ("Ready", _GREEN()),
            "thinking": ("Thinking\u2026", PALETTE['systemIndigo']),
            "error":    ("Local model failed \u2014 scroll down to use Ollama instead \u2193",
                         PALETTE['warning']),
        }
        msg, color = _msgs.get(status, (status, _MUTED()))
        self._ai_status_lbl.setText(msg)
        self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{color};")
        if hasattr(self, "_ai_apply_btn"):
            self._ai_apply_btn.setEnabled(status not in ("loading", "thinking"))

    def set_ai_tier(self, tier_value: int) -> None:
        """Called by MainWindow when AIService.tier_changed fires."""
        if not hasattr(self, "_ai_tier_frame"):
            return
        from ai.capability_tier import (
            AITier, tier_display_name, tier_description, available_features)

        tier = AITier(tier_value)
        if tier == AITier.NONE:
            self._ai_tier_frame.setVisible(False)
            return

        name = tier_display_name(tier)
        desc = tier_description(tier)
        features = available_features(tier)

        _tier_colors = {
            AITier.BASIC:    _MUTED(),
            AITier.STANDARD: PALETTE['accent'],
            AITier.FULL:     _GREEN(),
        }
        color = _tier_colors.get(tier, _MUTED())

        self._ai_tier_badge.setText(name)
        self._ai_tier_badge.setStyleSheet(
            f"font-size:{FONT['caption']}pt; font-weight:700; color:{color}; "
            f"background:{PALETTE['bg']}; border:1px solid {color}44; "
            f"border-radius:3px; padding:2px 8px;")

        # Build feature summary
        feature_names = {
            "chat": "Chat", "explain_tab": "Explain Tab",
            "diagnose": "Diagnose", "session_report": "Session Reports",
            "manual_rag": "Manual Search", "quickstart_guide": "Quickstart Guide",
            "proactive_advisor": "AI Advisor", "structured_response": "Smart Suggestions",
            "voice_commands": "Voice Commands", "ai_acquisition": "AI Acquisition",
            "batch_insights": "Batch Insights", "explain_diagnostics": "Diagnostic Insights",
        }
        enabled = [feature_names.get(f, f) for f in features if f in feature_names]
        self._ai_tier_desc.setText(
            f"{desc}  Enabled: {', '.join(enabled)}.")
        self._ai_tier_desc.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textSub']};")

        self._ai_tier_frame.setStyleSheet(
            f"QFrame {{ background:{PALETTE['surface']}; "
            f"border:1px solid {color}22; border-radius:4px; }}")
        self._ai_tier_frame.setVisible(True)

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
            text  = "CPU only \u2014 no GPU required"
            color = _MUTED()
        elif val >= n_layers:
            text  = f"Full GPU \u2014 all {n_layers} layers  \u00b7  ~{vram_gb:.1f} GB VRAM"
            color = _GREEN()
        else:
            text  = f"{val} / {n_layers} layers on GPU  \u00b7  ~{vram_gb:.1f} GB VRAM"
            color = _AMBER()

        self._ai_gpu_label.setText(text)
        self._ai_gpu_label.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{color};")
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
        self._ai_dl_status_lbl.setText(f"Starting download of {m['name']}\u2026")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        # Store expected file size so progress display can fall back to it
        # when CDN returns an incorrect Content-Length after redirect.
        self._ai_dl_expected_bytes = int(m.get("size_gb", 0) * 1024 * 1024 * 1024)
        self.download_model_requested.emit(m["url"], dest)

    def set_download_progress(self, done: int, total: int, speed_mbps: float) -> None:
        """Called by MainWindow during model download."""
        if not hasattr(self, "_ai_progress_bar"):
            return

        # CDN redirects can return an incorrect Content-Length (e.g. the
        # compressed size instead of the actual file).  Fall back to the
        # catalog's expected size when the header looks wrong.
        expected = getattr(self, "_ai_dl_expected_bytes", 0)
        if expected > 0 and (total <= 0 or total < expected * 0.5):
            total = expected

        done_mb   = done  / 1024 / 1024
        speed_str = f"  {speed_mbps:.1f} MB/s" if speed_mbps > 0 else ""
        if total > 0:
            # Content-Length known -- determinate progress
            pct = min(int(done / total * 100), 100)
            self._ai_progress_bar.setRange(0, 100)
            self._ai_progress_bar.setValue(pct)
            total_mb = total / 1024 / 1024
            self._ai_dl_status_lbl.setText(
                f"Downloading\u2026 {done_mb:.0f} / {total_mb:.0f} MB{speed_str}")
        else:
            # Content-Length unknown (CDN redirect) -- indeterminate animation
            self._ai_progress_bar.setRange(0, 0)
            self._ai_dl_status_lbl.setText(
                f"Downloading\u2026 {done_mb:.0f} MB{speed_str}")

    def set_download_complete(self, path: str) -> None:
        """Called by MainWindow when model download finishes successfully."""
        if not hasattr(self, "_ai_progress_bar"):
            return
        self._ai_progress_bar.setRange(0, 100)  # restore from indeterminate if needed
        self._ai_progress_bar.setValue(100)
        self._ai_cancel_btn.setVisible(False)
        self._ai_download_btn.setEnabled(True)
        self._ai_download_btn.setText("Re-download Model")
        self._ai_dl_status_lbl.setText("Download complete \u2014 model is ready")
        self._ai_dl_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_GREEN()};")
        self._ai_path_edit.setText(path)
        self._ai_status_lbl.setText("Model ready \u2014 click Load Model")
        self._ai_status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_GREEN()};")

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
            self._ai_dl_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        else:
            self._ai_dl_status_lbl.setText(f"Download failed: {msg}")
            self._ai_dl_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE['danger']};")

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
