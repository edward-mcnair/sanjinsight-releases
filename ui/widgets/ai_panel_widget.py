"""
ui/widgets/ai_panel_widget.py

AIPanelWidget — dockable AI assistant panel.

Layout
------
  ┌─────────────────────────────────────────┐
  │ [●] AI Assistant     status           ✕ │  ← header row
  ├─────────────────────────────────────────┤
  │  [A] Instrument ready                   │  ← evidence panel (grade + issues)
  │   ⊗ TEC 1 stable     Δ0.25°C  fail     │
  │   ⚠ Focus quality    42       warn     │
  ├─────────────────────────────────────────┤
  │  [Explain this tab]   [Diagnose]         │  ← quick actions
  ├─────────────────────────────────────────┤
  │                                         │
  │  Streaming text display (QTextEdit)     │
  │                                         │
  ├─────────────────────────────────────────┤
  │  ┌──────────────────────┐ [Ask]         │  ← free-form input
  └─────────────────────────────────────────┘

When llama-cpp-python is not installed, only a "not installed" notice
and an install hint are shown.
"""

from __future__ import annotations

import logging
import time

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QSizePolicy, QFrame, QFileDialog)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QTextCharFormat, QColor, QFont
from ui.icons      import set_btn_icon
from ui.font_utils import mono_font
from ui.theme      import FONT, PALETTE, scaled_qss

log = logging.getLogger(__name__)

# ── Style helpers — read PALETTE at call-time so they respond to theme switches ─
def _BG():     return PALETTE.get('bg',       '#242424')
def _BG2():    return PALETTE.get('surface',  '#2d2d2d')
def _BORDER(): return PALETTE.get('border',   '#484848')
def _TEXT():   return PALETTE.get('text',     '#ebebeb')
def _MUTED():  return PALETTE.get('textSub',  '#6a6a6a')
_GREEN  = "#00d4aa"
_AMBER  = "#ffaa44"
_RED    = "#ff5555"
_PURPLE = "#8888ff"

_STATUS_COLORS = {
    "off":      None,       # resolved dynamically via _MUTED()
    "loading":  _AMBER,
    "ready":    _GREEN,
    "thinking": _PURPLE,
    "error":    _RED,
}

_STATUS_ICONS = {
    "off":      "○",
    "loading":  "◌",
    "ready":    "●",
    "thinking": "◉",
    "error":    "⊗",
}

def _BTN() -> str:
    surf = PALETTE.get('surface2', '#3d3d3d')
    bdr  = PALETTE.get('border',   '#484848')
    sub  = PALETTE.get('textSub',  '#6a6a6a')
    text = PALETTE.get('text',     '#ebebeb')
    dim  = PALETTE.get('textDim',  '#999999')
    return f"""
    QPushButton {{
        background:{surf}; color:{sub};
        border:1px solid {bdr}; border-radius:4px;
        font-size:{FONT["label"]}pt; padding:5px 10px;
    }}
    QPushButton:hover   {{ color:{text}; border-color:{PALETTE.get('accent','#00d4aa')}44; }}
    QPushButton:pressed {{ background:{PALETTE.get('surface','#2d2d2d')}; }}
    QPushButton:disabled{{ color:{dim}; border-color:{bdr}; }}
"""


def _BTN_PRIMARY() -> str:
    acc  = PALETTE.get('accent',   '#00d4aa')
    surf = PALETTE.get('surface2', '#3d3d3d')
    return f"""
    QPushButton {{
        background:{surf}; color:{acc};
        border:1px solid {acc}44; border-radius:4px;
        font-size:{FONT["label"]}pt; padding:5px 14px;
    }}
    QPushButton:hover   {{ border-color:{acc}88; }}
    QPushButton:pressed {{ background:{PALETTE.get('surface','#2d2d2d')}; }}
    QPushButton:disabled{{ color:{PALETTE.get('textDim','#999999')}; border-color:{PALETTE.get('border','#484848')}; }}
"""


class AIPanelWidget(QWidget):
    """
    Dockable AI assistant panel.

    Signals
    -------
    explain_requested         user clicked "Explain this tab"
    diagnose_requested        user clicked "Diagnose"
    ask_requested(str)        user submitted a free-form question
    close_requested           user clicked ✕
    support_requested         user clicked "Get Support" (opens SupportDialog)
    """

    explain_requested  = pyqtSignal()
    diagnose_requested = pyqtSignal()
    ask_requested      = pyqtSignal(str)
    close_requested    = pyqtSignal()
    clear_requested    = pyqtSignal()    # user clicked "Clear" — reset conversation
    cancel_requested   = pyqtSignal()    # user clicked "Stop" — cancel inference
    export_requested   = pyqtSignal(str) # user chose an export path (file path)
    support_requested  = pyqtSignal()    # user clicked "Get Support"

    def __init__(self, llama_installed: bool = True, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        self.setStyleSheet(f"background:{_BG()}; color:{_TEXT()};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)

        # ── Header row ──
        hdr = QHBoxLayout()
        self._status_dot = QLabel("○")
        self._status_dot.setStyleSheet(f"color:{_MUTED()}; font-size:{FONT['readoutSm']}pt;")
        self._title_lbl = QLabel("AI Assistant")
        self._title_lbl.setStyleSheet(f"font-size:{FONT['body']}pt; font-weight:700; color:{_TEXT()};")
        self._status_state = QLabel("off")
        self._status_state.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; border:none; font-size:{FONT['body']}pt; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}"
        )
        self._close_btn.clicked.connect(self.close_requested)
        hdr.addWidget(self._status_dot)
        hdr.addSpacing(4)
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        hdr.addWidget(self._status_state)
        hdr.addSpacing(6)
        hdr.addWidget(self._close_btn)
        lay.addLayout(hdr)

        # ── Divider ──
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color:{_BORDER()};")
        lay.addWidget(div)

        # ── Evidence panel ──
        self._evidence_frame = QFrame()
        self._evidence_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_BORDER()}; border-radius:4px; }}"
        )
        ev_lay = QVBoxLayout(self._evidence_frame)
        ev_lay.setContentsMargins(8, 6, 8, 6)
        ev_lay.setSpacing(3)

        grade_row = QHBoxLayout()
        self._grade_lbl = QLabel("—")
        self._grade_lbl.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:700; color:{_MUTED()}; "
            f"background:{_BG2()}; border-radius:3px; padding:1px 7px;"
        )
        self._grade_lbl.setFixedWidth(36)
        self._grade_lbl.setAlignment(Qt.AlignCenter)
        self._grade_summary_lbl = QLabel("No model loaded")
        self._grade_summary_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        grade_row.addWidget(self._grade_lbl)
        grade_row.addSpacing(8)
        grade_row.addWidget(self._grade_summary_lbl)
        grade_row.addStretch()
        ev_lay.addLayout(grade_row)

        # Up to 5 issue rows — clickable buttons that fire a targeted AI query
        self._issue_rows: list[QPushButton] = []
        self._active_issues: list = []   # latest RuleResult objects, set by refresh_evidence
        for i in range(5):
            btn = QPushButton("")
            btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{_MUTED()}; "
                f"border:none; text-align:left; padding:1px 4px; font-size:{FONT['caption']}pt; }}"
                f"QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; border-radius:3px; }}"
            )
            btn.setVisible(False)
            btn.clicked.connect(lambda checked, idx=i: self._on_issue_clicked(idx))
            ev_lay.addWidget(btn)
            self._issue_rows.append(btn)

        lay.addWidget(self._evidence_frame)

        # ── Quick action buttons ──
        action_row = QHBoxLayout()
        self._explain_btn = QPushButton("Explain this tab")
        set_btn_icon(self._explain_btn, "fa5s.info-circle")
        self._explain_btn.setStyleSheet(_BTN())
        self._explain_btn.setEnabled(False)
        self._explain_btn.setToolTip(
            "Ask the AI to explain what the current tab does\n"
            "and what you should check given the instrument state.")
        self._explain_btn.clicked.connect(self.explain_requested)

        self._diagnose_btn = QPushButton("Diagnose")
        set_btn_icon(self._diagnose_btn, "fa5s.stethoscope")
        self._diagnose_btn.setStyleSheet(_BTN())
        self._diagnose_btn.setEnabled(False)
        self._diagnose_btn.setToolTip(
            "Ask the AI to review the current instrument state\n"
            "and suggest fixes for any problems it finds.")
        self._diagnose_btn.clicked.connect(self.diagnose_requested)

        action_row.addWidget(self._explain_btn)
        action_row.addWidget(self._diagnose_btn)
        lay.addLayout(action_row)

        # ── Get Support button (always enabled — no AI model required) ──
        support_row = QHBoxLayout()
        self._support_btn = QPushButton("Get Support")
        set_btn_icon(self._support_btn, "fa5s.envelope")
        self._support_btn.setStyleSheet(
            f"QPushButton {{ background:{_BG2()}; color:#88aacc; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['sublabel']}pt; padding:4px 10px; }}"
            f"QPushButton:hover   {{ border-color:#88aacc55; color:#aaccee; }}"
            f"QPushButton:pressed {{ background:{_BG()}; }}"
        )
        self._support_btn.setToolTip(
            "Open a support email pre-filled with your system information\n"
            "and recent log — ready to send to software-support@microsanj.com."
        )
        self._support_btn.clicked.connect(self.support_requested)
        support_row.addWidget(self._support_btn)
        support_row.addStretch()
        lay.addLayout(support_row)

        # ── Response display ──
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setStyleSheet(
            f"QTextEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; font-family:Menlo,monospace; padding:6px; }}"
        )
        self._display.setPlaceholderText(
            "AI not connected yet.\n\n"
            "Quick start with Ollama (free, local, GPU-accelerated):\n"
            "  1. Open  Settings → Ollama  section\n"
            "  2. Click  ⬇ Install Ollama for me  (if not installed)\n"
            "  3. Click  ⬇ Pull Model  to download phi3\n"
            "  4. Click  Connect\n\n"
            "Or connect a cloud model (Claude / ChatGPT) in\n"
            "Settings → Cloud AI — just paste an API key."
        )
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._display, 1)

        # ── Free-form input ──
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask a question…")
        self._input.setStyleSheet(
            f"QLineEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; padding:5px 8px; }}"
        )
        self._input.returnPressed.connect(self._on_ask)

        self._ask_btn = QPushButton("Ask")
        set_btn_icon(self._ask_btn, "fa5s.paper-plane", "#00d4aa")
        self._ask_btn.setStyleSheet(_BTN_PRIMARY())
        self._ask_btn.setFixedWidth(60)
        self._ask_btn.setEnabled(False)
        self._ask_btn.clicked.connect(self._on_ask)

        # Stop button — visible only while "thinking", replaces Ask semantically
        self._stop_btn = QPushButton("Stop")
        set_btn_icon(self._stop_btn, "fa5s.stop-circle", "#ff5555")
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background:{_BG2()}; color:{_RED};
                border:1px solid {_RED}44; border-radius:4px;
                font-size:{FONT["label"]}pt; padding:5px 10px;
            }}
            QPushButton:hover   {{ border-color:{_RED}88; }}
            QPushButton:pressed {{ background:{_BG()}; }}
        """)
        self._stop_btn.setFixedWidth(60)
        self._stop_btn.setVisible(False)
        self._stop_btn.setToolTip("Cancel the current AI response")
        self._stop_btn.clicked.connect(self._on_stop)

        input_row.addWidget(self._input)
        input_row.addWidget(self._ask_btn)
        input_row.addWidget(self._stop_btn)
        lay.addLayout(input_row)

        # ── Token rate + Clear + Export row ──
        rate_row = QHBoxLayout()
        self._clear_btn = QPushButton("Clear")
        set_btn_icon(self._clear_btn, "fa5s.trash")
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; "
            f"border:none; font-size:{FONT['caption']}pt; padding:0px 4px; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}"
        )
        self._clear_btn.setToolTip("Clear conversation history")
        self._clear_btn.clicked.connect(self._on_clear)

        self._export_btn = QPushButton("Export")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._export_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; "
            f"border:none; font-size:{FONT['caption']}pt; padding:0px 4px; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}"
        )
        self._export_btn.setToolTip("Save conversation to a text file")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)

        self._rate_lbl = QLabel("")
        self._rate_lbl.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_MUTED()};")
        self._rate_lbl.setAlignment(Qt.AlignRight)
        rate_row.addWidget(self._clear_btn)
        rate_row.addSpacing(4)
        rate_row.addWidget(self._export_btn)
        rate_row.addStretch()
        rate_row.addWidget(self._rate_lbl)
        lay.addLayout(rate_row)

    # ------------------------------------------------------------------ #
    #  Public API (called by MainWindow via AIService signals)             #
    # ------------------------------------------------------------------ #

    def start_user_turn(self, label: str) -> None:
        """
        Insert a user message bubble and an AI response header into the
        chat log, ready for streaming tokens.

        Call this BEFORE emitting ask_requested (or before calling the AI
        service for explain/diagnose) so the user can see their prompt
        immediately.
        """
        if not hasattr(self, "_display"):
            return
        ts = time.strftime("%H:%M")
        cursor = self._display.textCursor()
        cursor.movePosition(cursor.End)

        # ── User header ──────────────────────────────────────────────────
        fmt_you = QTextCharFormat()
        fmt_you.setForeground(QColor(_GREEN))
        fmt_you.setFont(mono_font(11, bold=True))
        cursor.insertText(f"\n▷ You  {ts}\n", fmt_you)

        # ── User question body ───────────────────────────────────────────
        fmt_body = QTextCharFormat()
        fmt_body.setForeground(QColor(_TEXT()))
        fmt_body.setFont(mono_font(11))
        cursor.insertText(f"  {label}\n\n", fmt_body)

        # ── AI response header ───────────────────────────────────────────
        fmt_ai_hdr = QTextCharFormat()
        fmt_ai_hdr.setForeground(QColor(_PURPLE))
        fmt_ai_hdr.setFont(mono_font(11, bold=True))
        cursor.insertText("◉ AI\n", fmt_ai_hdr)

        # Reset char format so streaming tokens arrive in normal colour
        fmt_reset = QTextCharFormat()
        fmt_reset.setForeground(QColor(_TEXT()))
        fmt_reset.setFont(mono_font(11))
        cursor.setCharFormat(fmt_reset)
        self._display.setTextCursor(cursor)

        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_status_changed(self, status: str) -> None:
        """Update status indicator and enable/disable buttons."""
        color = _STATUS_COLORS.get(status) or _MUTED()
        icon  = _STATUS_ICONS.get(status, "○")
        self._status_dot.setText(icon)
        self._status_dot.setStyleSheet(f"color:{color}; font-size:{FONT['readoutSm']}pt;")
        self._status_state.setText(status)
        self._status_state.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{color};")

        can_act    = (status == "ready")
        thinking   = (status == "thinking")
        has_model  = status not in ("off", "error")

        if hasattr(self, "_explain_btn"):
            self._explain_btn.setEnabled(can_act)
            self._diagnose_btn.setEnabled(can_act)
        if hasattr(self, "_ask_btn"):
            self._ask_btn.setEnabled(can_act)
            self._ask_btn.setVisible(not thinking)
        if hasattr(self, "_stop_btn"):
            self._stop_btn.setVisible(thinking)
        if hasattr(self, "_input"):
            self._input.setEnabled(not thinking)
        if hasattr(self, "_export_btn"):
            self._export_btn.setEnabled(has_model)

    def on_token(self, token: str) -> None:
        """Append a streaming token to the display."""
        cursor = self._display.textCursor()
        cursor.movePosition(cursor.End)
        self._display.setTextCursor(cursor)
        self._display.insertPlainText(token)
        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_response_complete(self, text: str, elapsed: float) -> None:
        """Append a turn separator and show token rate after a response completes."""
        tok_count = len(text.split())
        rate = tok_count / elapsed if elapsed > 0 else 0
        self._rate_lbl.setText(f"{rate:.0f} tok/s  ·  {elapsed:.1f}s")

        if hasattr(self, "_display"):
            cursor = self._display.textCursor()
            cursor.movePosition(cursor.End)
            fmt_sep = QTextCharFormat()
            fmt_sep.setForeground(QColor(_MUTED()))
            fmt_sep.setFont(mono_font(9))
            cursor.insertText(
                "\n─────────────────────────────────────────────\n\n",
                fmt_sep)
            self._display.setTextCursor(cursor)
            sb = self._display.verticalScrollBar()
            sb.setValue(sb.maximum())

    def on_error(self, msg: str) -> None:
        """Display an error message in the chat log."""
        if hasattr(self, "_display"):
            cursor = self._display.textCursor()
            cursor.movePosition(cursor.End)
            fmt_err = QTextCharFormat()
            fmt_err.setForeground(QColor(_RED))
            fmt_err.setFont(mono_font(11))
            cursor.insertText(f"\n⚠  {msg}\n", fmt_err)
            fmt_sep = QTextCharFormat()
            fmt_sep.setForeground(QColor(_MUTED()))
            fmt_sep.setFont(mono_font(9))
            cursor.insertText(
                "\n─────────────────────────────────────────────\n\n",
                fmt_sep)
            self._display.setTextCursor(cursor)
            sb = self._display.verticalScrollBar()
            sb.setValue(sb.maximum())
        if hasattr(self, "_rate_lbl"):
            self._rate_lbl.setText("")

    def clear_display(self) -> None:
        """Clear the response display."""
        if hasattr(self, "_display"):
            self._display.clear()
        if hasattr(self, "_rate_lbl"):
            self._rate_lbl.setText("")

    def refresh_evidence(self, results: list) -> None:
        """
        Update the evidence panel from a list of RuleResult objects.

        Called periodically by MainWindow with DiagnosticEngine.evaluate() output.
        Safe to call from the main thread at any time.
        """
        if not hasattr(self, "_grade_lbl"):
            return

        fails = [r for r in results if r.severity == "fail"]
        warns = [r for r in results if r.severity == "warn"]
        n_fail, n_warn = len(fails), len(warns)

        # ── Grade ──
        if n_fail >= 2:
            grade, color = "D", _RED
        elif n_fail == 1:
            grade, color = "C", _AMBER
        elif n_warn >= 3:
            grade, color = "C", _AMBER
        elif n_warn >= 1:
            grade, color = "B", "#88cc88"
        else:
            grade, color = "A", _GREEN

        self._grade_lbl.setText(grade)
        self._grade_lbl.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:700; color:{color}; "
            f"background:{_BG2()}; border-radius:3px; padding:1px 7px;"
        )
        _grade_tips = {
            "A": "Grade A — All checks passed. Instrument is ready for acquisition.",
            "B": "Grade B — Minor warnings present. Review issues below.",
            "C": "Grade C — Significant issue or multiple warnings. Address before acquiring.",
            "D": "Grade D — Critical failures detected. Acquisition may be unreliable.",
        }
        self._grade_lbl.setToolTip(_grade_tips.get(grade, ""))

        parts: list[str] = []
        if n_fail:
            parts.append(f"{n_fail} fail")
        if n_warn:
            parts.append(f"{n_warn} warn")
        summary = "Instrument ready" if not parts else "  ·  ".join(parts)
        self._grade_summary_lbl.setText(summary)
        self._grade_summary_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{color if parts else _GREEN};"
        )

        # ── Issue rows (fail first, then warn) ──
        active = fails + warns
        self._active_issues = active   # store for click handler

        for i, btn in enumerate(self._issue_rows):
            if i < min(len(active), 5):
                # Last slot: overflow indicator (not clickable as an issue)
                if i == 4 and len(active) > 5:
                    btn.setText(f"  …and {len(active) - 4} more issues")
                    btn.setStyleSheet(
                        f"QPushButton {{ background:transparent; color:{_MUTED()}; "
                        f"border:none; text-align:left; padding:1px 4px; font-size:{FONT['caption']}pt; }}"
                    )
                    btn.setToolTip("")
                    btn.setCursor(Qt.ArrowCursor)
                else:
                    r = active[i]
                    icon = "⊗" if r.severity == "fail" else "⚠"
                    clr  = _RED if r.severity == "fail" else _AMBER
                    btn.setText(f"{icon}  {r.display_name}  ·  {r.observed}")
                    btn.setStyleSheet(
                        f"QPushButton {{ background:transparent; color:{clr}; "
                        f"border:none; text-align:left; padding:1px 4px; font-size:{FONT['caption']}pt; }}"
                        f"QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; border-radius:3px; }}"
                    )
                    btn.setToolTip(f"{r.hint}\n\nClick to ask AI for guidance.")
                    btn.setCursor(Qt.PointingHandCursor)
                btn.setVisible(True)
            else:
                btn.setVisible(False)

    # ------------------------------------------------------------------ #
    #  Theme support                                                       #
    # ------------------------------------------------------------------ #

    def _apply_styles(self) -> None:
        """Re-apply all PALETTE-driven styles. Called by MainWindow on theme switch."""
        self.setStyleSheet(f"background:{_BG()}; color:{_TEXT()};")

        # Header
        self._status_dot.setStyleSheet(
            f"color:{_MUTED()}; font-size:{FONT['readoutSm']}pt;")
        self._title_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; font-weight:700; color:{_TEXT()};")
        self._status_state.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; border:none; font-size:{FONT['body']}pt; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}")

        # Evidence panel
        self._evidence_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2()}; border:1px solid {_BORDER()}; border-radius:4px; }}")
        self._grade_lbl.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:700; color:{_MUTED()}; "
            f"background:{_BG2()}; border-radius:3px; padding:1px 7px;")
        self._grade_summary_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        for btn in self._issue_rows:
            btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{_MUTED()}; "
                f"border:none; text-align:left; padding:1px 4px; font-size:{FONT['caption']}pt; }}"
                f"QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; border-radius:3px; }}")

        # Action buttons
        self._explain_btn.setStyleSheet(_BTN())
        self._diagnose_btn.setStyleSheet(_BTN())
        self._support_btn.setStyleSheet(
            f"QPushButton {{ background:{_BG2()}; color:#88aacc; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['sublabel']}pt; padding:4px 10px; }}"
            f"QPushButton:hover   {{ border-color:#88aacc55; color:#aaccee; }}"
            f"QPushButton:pressed {{ background:{_BG()}; }}")

        # Response display
        self._display.setStyleSheet(
            f"QTextEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; font-family:Menlo,monospace; padding:6px; }}")

        # Input row
        self._input.setStyleSheet(
            f"QLineEdit {{ background:{_BG2()}; color:{_TEXT()}; "
            f"border:1px solid {_BORDER()}; border-radius:4px; "
            f"font-size:{FONT['label']}pt; padding:5px 8px; }}")
        self._ask_btn.setStyleSheet(_BTN_PRIMARY())
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background:{_BG2()}; color:{_RED};
                border:1px solid {_RED}44; border-radius:4px;
                font-size:{FONT["label"]}pt; padding:5px 10px;
            }}
            QPushButton:hover   {{ border-color:{_RED}88; }}
            QPushButton:pressed {{ background:{_BG()}; }}
        """)

        # Utility row
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; "
            f"border:none; font-size:{FONT['caption']}pt; padding:0px 4px; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}")
        self._export_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED()}; "
            f"border:none; font-size:{FONT['caption']}pt; padding:0px 4px; }}"
            f"QPushButton:hover {{ color:{_TEXT()}; }}")
        self._rate_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_MUTED()};")

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _on_issue_clicked(self, idx: int) -> None:
        """Send a targeted AI query about the issue at position idx."""
        if idx >= len(self._active_issues):
            return
        r = self._active_issues[idx]
        question = (
            f"Diagnostic check '{r.display_name}' is {r.severity.upper()}: "
            f"{r.observed}. "
            f"Please give me step-by-step guidance to resolve this."
        )
        self.start_user_turn(
            f"Fix: {r.display_name}  ({r.severity.upper()}: {r.observed})")
        self.ask_requested.emit(question)

    def _on_clear(self) -> None:
        self.clear_display()
        self.clear_requested.emit()

    def _on_stop(self) -> None:
        """Cancel the in-progress inference."""
        self.cancel_requested.emit()
        # Append a visual cue in the display so the user knows it was cancelled
        if hasattr(self, "_display"):
            cursor = self._display.textCursor()
            cursor.movePosition(cursor.End)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_AMBER))
            fmt.setFont(mono_font(9))
            cursor.insertText(" [stopped]\n", fmt)
            self._display.setTextCursor(cursor)
            sb = self._display.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_export(self) -> None:
        """Open a save dialog and emit export_requested with the chosen path."""
        import time as _time
        default_name = f"sanjinsight_conversation_{_time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Conversation",
            default_name,
            "Text files (*.txt);;All files (*)",
        )
        if path:
            self.export_requested.emit(path)

    def _on_ask(self) -> None:
        if not hasattr(self, "_input"):
            return
        q = self._input.text().strip()
        if not q:
            return
        self._input.clear()
        self.start_user_turn(q)
        self.ask_requested.emit(q)

    # _build_not_installed_view() was removed — the panel now always builds
    # the full chat UI.  "Not connected" state is communicated through the
    # display widget's placeholder text and the status dot in the header.
