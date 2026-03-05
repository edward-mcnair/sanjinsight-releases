"""
ui/dialogs/support_dialog.py

SupportDialog — Collect system info + recent log, pre-fill a support email,
and open it in the user's default mail client.

Accessible from:
  •  Help → Get Support…              (always available)
  •  AI Assistant → "Get Support"     (button in the AI panel)

No AI model required — the dialog works entirely with local data.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import urllib.parse
from pathlib import Path

from PyQt5.QtCore    import Qt, QUrl
from PyQt5.QtGui     import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QSizePolicy, QFrame, QApplication,
)

import version
from logging_config import log_path
from ui.theme import PALETTE, FONT
from ui.icons import set_btn_icon

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SUPPORT_EMAIL = version.SUPPORT_EMAIL          # canonical source: version.py
_LOG_LINES    = 40                             # recent log lines to include
_MAILTO_LIMIT = 1_800                          # mailto: body char limit (most clients)

# ── Data collectors ────────────────────────────────────────────────────────────


def _read_log_tail(n: int = _LOG_LINES) -> str:
    """Return the last *n* lines of the rotating log file, or a short error note."""
    try:
        p = log_path()
        if not p.exists():
            return f"(log file not found at {p})"
        text  = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        tail  = lines[-n:] if len(lines) > n else lines
        return "\n".join(tail)
    except Exception as exc:
        return f"(could not read log: {exc})"


def _collect_system_info() -> str:
    """Return a compact multi-line block of OS / Python / application version info."""
    lines = [
        f"Application : {version.APP_NAME} {version.version_string()}"
        f"  (built {version.BUILD_DATE})",
        f"OS          : {platform.system()} {platform.version()}",
        f"Python      : {sys.version.split()[0]}",
        f"Platform    : {platform.platform(terse=True)}",
    ]
    return "\n".join(lines)


def _format_state(context_json: str) -> str:
    """Return a human-readable rendering of the instrument state JSON."""
    if not context_json or context_json.strip() in ("", "{}"):
        return "(not available)"
    try:
        data = json.loads(context_json)
        lines: list[str] = []
        for key, val in data.items():
            if isinstance(val, dict):
                inner = "  ".join(f"{k}={v}" for k, v in val.items())
                lines.append(f"  {key}: {inner}")
            else:
                lines.append(f"  {key}: {val}")
        return "\n".join(lines) or "(empty)"
    except Exception:
        return context_json[:500]


def _assemble_email(
    user_description: str,
    system_info:      str,
    state_text:       str,
    log_tail:         str,
) -> tuple[str, str]:
    """Return (subject, body) for the support email."""
    subject = f"SanjINSIGHT Support — {version.version_string()}"
    desc    = user_description.strip() or "(not provided)"

    body = (
        f"SanjINSIGHT Support Request\n"
        f"{'=' * 44}\n\n"
        f"Problem Description\n"
        f"{'-' * 44}\n"
        f"{desc}\n\n"
        f"System Information\n"
        f"{'-' * 44}\n"
        f"{system_info}\n\n"
        f"Instrument State\n"
        f"{'-' * 44}\n"
        f"{state_text}\n\n"
        f"Recent Log (last {_LOG_LINES} lines)\n"
        f"{'-' * 44}\n"
        f"{log_tail}\n"
    )
    return subject, body


# ── Button style helpers ───────────────────────────────────────────────────────

def _btn_primary_style() -> str:
    b = FONT["body"]
    return (
        f"QPushButton {{ background:#006b40; color:#fff; border:none; border-radius:4px; "
        f"padding:5px 16px; font-size:{b}pt; font-weight:600; }}"
        f"QPushButton:hover   {{ background:#008050; }}"
        f"QPushButton:pressed {{ background:#005030; }}"
    )


def _btn_secondary_style() -> str:
    b = FONT["body"]
    s, d, t = PALETTE["surface3"], PALETTE["border"], PALETTE["textDim"]
    return (
        f"QPushButton {{ background:{s}; color:{t}; border:1px solid {d}; "
        f"border-radius:4px; padding:5px 16px; font-size:{b}pt; }}"
        f"QPushButton:hover   {{ background:#252525; color:{PALETTE['text']}; }}"
        f"QPushButton:pressed {{ background:#111; }}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SupportDialog
# ══════════════════════════════════════════════════════════════════════════════


class SupportDialog(QDialog):
    """
    Pre-filled support email dialog.

    Collects system info + recent log on construction, displays a structured
    email the user can edit, then opens it in the default mail client via a
    mailto: URI or copies it to the clipboard.

    Parameters
    ----------
    context_json : str
        Current instrument state JSON string from ContextBuilder.build().
        Pass an empty string (or omit) when the AI service is not running.
    parent : QWidget, optional
    """

    def __init__(self, context_json: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Get Support")
        self.setMinimumWidth(680)
        self.setMinimumHeight(580)
        self.setStyleSheet(f"""
            QDialog   {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; }}
            QLabel    {{ color:{PALETTE['text']}; background:transparent; }}
            QFrame    {{ color:{PALETTE['border']}; }}
        """)

        # ── Gather data (fast — all local I/O) ──────────────────────────────
        self._system_info = _collect_system_info()
        self._state_text  = _format_state(context_json)
        self._log_tail    = _read_log_tail()

        # ── Layout ──────────────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        # ── Title ────────────────────────────────────────────────────────────
        title = QLabel("📧  Get Support")
        title.setStyleSheet(
            f"font-size:{FONT['heading']}pt; font-weight:700; "
            f"color:{PALETTE['accent']};"
        )
        lay.addWidget(title)

        intro = QLabel(
            "Describe your problem below. Your system information and recent log are "
            "included automatically. Click <b>Open in Mail Client</b> to send the email, "
            f"or <b>Copy to Clipboard</b> and paste it manually.<br>"
            f"<span style='color:{PALETTE['accent']};'>{SUPPORT_EMAIL}</span>"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;"
        )
        lay.addWidget(intro)

        # ── Problem description ───────────────────────────────────────────────
        desc_lbl = QLabel("What happened?  (briefly describe the issue)")
        desc_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;"
        )
        lay.addWidget(desc_lbl)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText(
            "e.g. 'Camera stopped responding during a scan…'"
        )
        self._desc_edit.setFixedHeight(72)
        self._desc_edit.setStyleSheet(
            f"QTextEdit {{ background:{PALETTE['surface3']}; color:{PALETTE['text']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:3px; "
            f"font-size:{FONT['body']}pt; padding:5px; }}"
        )
        lay.addWidget(self._desc_edit)

        # ── Divider ──────────────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        lay.addWidget(div)

        # ── Subject line ──────────────────────────────────────────────────────
        subj_row = QHBoxLayout()
        subj_lbl = QLabel("Subject:")
        subj_lbl.setFixedWidth(56)
        subj_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;"
        )
        self._subject_edit = QLineEdit()
        self._subject_edit.setText(
            f"SanjINSIGHT Support — {version.version_string()}"
        )
        self._subject_edit.setStyleSheet(
            f"QLineEdit {{ background:{PALETTE['surface3']}; color:{PALETTE['text']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:3px; "
            f"padding:4px 6px; font-size:{FONT['body']}pt; }}"
        )
        subj_row.addWidget(subj_lbl)
        subj_row.addWidget(self._subject_edit)
        lay.addLayout(subj_row)

        # ── Body preview (editable) ───────────────────────────────────────────
        body_lbl = QLabel(
            "Email body  (auto-assembled — you may edit before sending):"
        )
        body_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;"
        )
        lay.addWidget(body_lbl)

        self._body_edit = QTextEdit()
        self._body_edit.setStyleSheet(
            f"QTextEdit {{ background:{PALETTE['surface3']}; color:{PALETTE['text']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:3px; "
            f"font-size:{FONT['caption']}pt; font-family:Menlo,Consolas,monospace; "
            f"padding:6px; }}"
        )
        self._body_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._body_edit, 1)

        # Populate body and reconnect whenever the user edits the description
        self._refresh_body()
        self._desc_edit.textChanged.connect(self._refresh_body)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        copy_btn = QPushButton("Copy to Clipboard")
        set_btn_icon(copy_btn, "fa5s.clipboard")
        copy_btn.setStyleSheet(_btn_secondary_style())
        copy_btn.setToolTip(
            "Copy the full email (To + Subject + Body) to the clipboard.\n"
            "Paste into your email client manually."
        )
        copy_btn.clicked.connect(self._on_copy)

        close_btn = QPushButton("Close")
        set_btn_icon(close_btn, "fa5s.times")
        close_btn.setStyleSheet(_btn_secondary_style())
        close_btn.clicked.connect(self.reject)

        mail_btn = QPushButton("Open in Mail Client")
        set_btn_icon(mail_btn, "fa5s.envelope")
        mail_btn.setStyleSheet(_btn_primary_style())
        mail_btn.setToolTip(
            "Open your default mail client with this email pre-filled.\n\n"
            "If the body is truncated (some clients limit mailto: length),\n"
            f"attach the log file from {log_path()} for full diagnostics."
        )
        mail_btn.clicked.connect(self._on_open_mail)

        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(mail_btn)
        lay.addLayout(btn_row)

    # ── Private ───────────────────────────────────────────────────────────────

    def _refresh_body(self) -> None:
        """Rebuild the email body whenever the description changes."""
        desc = self._desc_edit.toPlainText()
        _, body = _assemble_email(
            desc, self._system_info, self._state_text, self._log_tail
        )
        # Block textChanged to avoid infinite loop
        self._body_edit.blockSignals(True)
        cursor_pos = self._body_edit.textCursor().position()
        self._body_edit.setPlainText(body)
        # Restore cursor position (capped to new length)
        cursor = self._body_edit.textCursor()
        cursor.setPosition(min(cursor_pos, len(body)))
        self._body_edit.setTextCursor(cursor)
        self._body_edit.blockSignals(False)

    def _on_copy(self) -> None:
        """Copy To + Subject + Body to the system clipboard."""
        subject = self._subject_edit.text().strip()
        body    = self._body_edit.toPlainText()
        full    = f"To: {SUPPORT_EMAIL}\nSubject: {subject}\n\n{body}"
        QApplication.clipboard().setText(full)

    def _on_open_mail(self) -> None:
        """Build a mailto: URI and hand it to the OS default mail client."""
        subject = self._subject_edit.text().strip()
        body    = self._body_edit.toPlainText()

        # Truncate body if it exceeds the mailto: URI length limit
        if len(body) > _MAILTO_LIMIT:
            note = (
                "\n\n[Body truncated — please attach the log file for complete "
                f"diagnostic data:\n{log_path()}]"
            )
            body = body[:_MAILTO_LIMIT] + note

        params = urllib.parse.urlencode(
            {"subject": subject, "body": body},
            quote_via=urllib.parse.quote,
        )
        url = QUrl(f"mailto:{SUPPORT_EMAIL}?{params}")
        if not QDesktopServices.openUrl(url):
            log.warning(
                "QDesktopServices.openUrl() returned False for mailto: URI — "
                "no mail client configured?"
            )
