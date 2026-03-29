"""
ui/license_prompt.py — First-run license activation prompt for SanjINSIGHT.

Shown once at startup when no valid license is found and the user has not
previously dismissed the prompt.  Offers two paths:

  • Activate License   — paste a key, validate inline, close on success.
  • Continue in Demo   — dismiss permanently; demo mode continues as normal.

The calling code (main_app.py) sets the ``ui.license_prompted`` pref to True
when this dialog closes so it is never shown again (even if later the user
removes their license — they know where Settings → License is at that point).

Emits:
    license_activated()  — key was validated and saved; caller should reload.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QTextEdit, QSizePolicy,
)

from version import APP_NAME, APP_VENDOR, SUPPORT_EMAIL
from ui.icons import IC, make_icon_label
from ui.theme import FONT, scaled_qss, MONO_FONT

log = logging.getLogger(__name__)

# ── Shared style constants (mirrors license_dialog.py) ───────────────────────
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
        border-radius:6px; padding:9px 26px;
        font-size:{FONT["body"]}pt; font-weight:600;
    }}
    QPushButton:hover    {{ background:#3a5fc8; }}
    QPushButton:pressed  {{ background:#2e4fa8; }}
    QPushButton:disabled {{ background:#2a3050; color:#555; }}
"""
_BTN_SECONDARY = f"""
    QPushButton {{
        background:{_BG2}; color:{_MUTED}; border:1px solid {_BORDER};
        border-radius:6px; padding:9px 26px;
        font-size:{FONT["body"]}pt;
    }}
    QPushButton:hover   {{ background:#1e2540; color:{_TEXT}; }}
    QPushButton:pressed {{ background:#1a1f33; }}
"""


class LicenseActivationPrompt(QDialog):
    """
    Lightweight first-run dialog: activate a license key or enter demo mode.

    Usage::

        dlg = LicenseActivationPrompt(parent=window)
        dlg.license_activated.connect(window._load_license)
        dlg.exec_()
        # After the dialog closes, set the ``ui.license_prompted`` pref so
        # the prompt never re-appears (handled by the caller).
    """

    license_activated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Activate License")
        self.setModal(True)
        self.setFixedSize(580, 400)
        self.setStyleSheet(
            f"QDialog {{ background:{_BG}; }} "
            f"QLabel  {{ background:transparent; }}"
        )
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setFixedHeight(72)
        hdr.setStyleSheet(f"background:{_BG2}; border-bottom:1px solid {_BORDER};")
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(12)

        icon = make_icon_label(IC.KEY, color="#ffffff", size=28)
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        t1 = QLabel(f"Activate {APP_VENDOR} {APP_NAME}")
        t1.setStyleSheet(scaled_qss("font-size:15pt; font-weight:700; color:#fff;"))
        t2 = QLabel("Enter your license key, or continue with simulated hardware")
        t2.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        col.addWidget(t1)
        col.addWidget(t2)
        lay.addLayout(col, 1)
        return hdr

    def _build_body(self) -> QVBoxLayout:
        lay = QVBoxLayout()
        lay.setContentsMargins(28, 22, 28, 18)
        lay.setSpacing(10)

        intro = QLabel(
            "Paste your license key below to unlock full hardware access.\n"
            "Without a license, SanjINSIGHT runs in <b>demo mode</b> with "
            "simulated hardware — no real instrument is required."
        )
        intro.setStyleSheet(f"font-size:{FONT['body']}pt; color:{_TEXT}; line-height:150%;")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self._key_input = QTextEdit()
        self._key_input.setPlaceholderText(
            "Paste license key here…\n\n"
            "Example:  eyJjdXN0b21lciI6Ii4uLiJ9.AAAA…"
        )
        self._key_input.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2}; color:{_TEXT};
                border:1px solid {_BORDER}; border-radius:4px;
                font-size:{FONT["caption"]}pt; font-family:{MONO_FONT};
                padding:8px;
            }}
            QTextEdit:focus {{ border-color:{_ACCENT}; }}
        """)
        self._key_input.setFixedHeight(88)
        self._key_input.textChanged.connect(self._on_key_changed)
        lay.addWidget(self._key_input)

        # Inline status message (hidden until activation is attempted)
        self._msg_lbl = QLabel("")
        self._msg_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.hide()
        lay.addWidget(self._msg_lbl)

        lay.addStretch(1)
        return lay

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(64)
        footer.setStyleSheet(f"background:{_BG2}; border-top:1px solid {_BORDER};")
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(10)

        contact = QLabel(f"To purchase a license, contact <a href='mailto:{SUPPORT_EMAIL}'>{SUPPORT_EMAIL}</a>")
        contact.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_MUTED};"
            f" qproperty-openExternalLinks: true;"
        )
        contact.setOpenExternalLinks(True)
        lay.addWidget(contact, 1)

        self._demo_btn = QPushButton("Continue in Demo Mode")
        self._demo_btn.setStyleSheet(_BTN_SECONDARY)
        self._demo_btn.setFixedHeight(38)
        self._demo_btn.clicked.connect(self._on_demo)
        lay.addWidget(self._demo_btn)

        self._activate_btn = QPushButton("Activate License")
        self._activate_btn.setStyleSheet(_BTN_PRIMARY)
        self._activate_btn.setFixedHeight(38)
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate)
        lay.addWidget(self._activate_btn)

        return footer

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_message(self, text: str, color: str = _MUTED):
        self._msg_lbl.setText(text)
        self._msg_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{color};")
        self._msg_lbl.show()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_key_changed(self):
        has_text = bool(self._key_input.toPlainText().strip())
        self._activate_btn.setEnabled(has_text)
        self._msg_lbl.hide()

    def _on_activate(self):
        key_string = self._key_input.toPlainText().strip()
        if not key_string:
            return

        import config as _cfg
        from licensing.license_validator import save_license_key

        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Validating…")

        info = save_license_key(_cfg, key_string)

        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Activate License")

        if info is None:
            self._set_message(
                f"⚠  Invalid license key — check the key and try again, "
                f"or contact {SUPPORT_EMAIL}.",
                _RED,
            )
            log.warning("License activation failed — invalid key entered at prompt")
        else:
            self._set_message(
                f"✓  License activated for {info.customer}  ({info.tier_display})",
                _GREEN,
            )
            log.info(
                "License activated at first-run prompt: %s / %s",
                info.tier_display, info.customer,
            )
            self.license_activated.emit()
            # Brief pause so the user sees the success message before close
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(900, self.accept)

    def _on_demo(self):
        log.info("User chose demo mode at license prompt")
        self.reject()   # reject() → caller treats both accept/reject as "done"
