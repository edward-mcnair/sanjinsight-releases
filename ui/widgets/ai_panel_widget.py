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

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QSizePolicy, QFrame)
from PyQt5.QtCore import Qt, pyqtSignal

log = logging.getLogger(__name__)

# ── Style ──────────────────────────────────────────────────────────────────────
_BG     = "#0d0d0d"
_BG2    = "#141414"
_BORDER = "#1e1e1e"
_TEXT   = "#c8c8c8"
_MUTED  = "#555"
_GREEN  = "#00d4aa"
_AMBER  = "#ffaa44"
_RED    = "#ff5555"
_PURPLE = "#8888ff"

_STATUS_COLORS = {
    "off":      _MUTED,
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

_BTN = f"""
    QPushButton {{
        background:#1a1a1a; color:#888;
        border:1px solid #252525; border-radius:4px;
        font-size:12pt; padding:5px 10px;
    }}
    QPushButton:hover   {{ background:#222; color:#bbb; border-color:#333; }}
    QPushButton:pressed {{ background:#181818; }}
    QPushButton:disabled{{ color:#333; border-color:#1a1a1a; }}
"""

_BTN_PRIMARY = f"""
    QPushButton {{
        background:#1e2a28; color:{_GREEN};
        border:1px solid {_GREEN}44; border-radius:4px;
        font-size:12pt; padding:5px 14px;
    }}
    QPushButton:hover   {{ background:#254d42; border-color:{_GREEN}88; }}
    QPushButton:pressed {{ background:#1a3530; }}
    QPushButton:disabled{{ color:#2a4a40; border-color:#1a2a28; background:#101a18; }}
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
    """

    explain_requested  = pyqtSignal()
    diagnose_requested = pyqtSignal()
    ask_requested      = pyqtSignal(str)
    close_requested    = pyqtSignal()
    clear_requested    = pyqtSignal()   # user clicked "Clear" — reset conversation

    def __init__(self, llama_installed: bool = True, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        self.setStyleSheet(f"background:{_BG}; color:{_TEXT};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)

        # ── Header row ──
        hdr = QHBoxLayout()
        self._status_dot = QLabel("○")
        self._status_dot.setStyleSheet(f"color:{_MUTED}; font-size:16pt;")
        self._title_lbl = QLabel("AI Assistant")
        self._title_lbl.setStyleSheet("font-size:13pt; font-weight:700; color:#ccc;")
        self._status_state = QLabel("off")
        self._status_state.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#444; border:none; font-size:13pt; }"
            "QPushButton:hover { color:#888; }"
        )
        close_btn.clicked.connect(self.close_requested)
        hdr.addWidget(self._status_dot)
        hdr.addSpacing(4)
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        hdr.addWidget(self._status_state)
        hdr.addSpacing(6)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        # ── Divider ──
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color:{_BORDER};")
        lay.addWidget(div)

        if not llama_installed:
            self._build_not_installed_view(lay)
            return

        # ── Evidence panel ──
        self._evidence_frame = QFrame()
        self._evidence_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2}; border:1px solid {_BORDER}; border-radius:4px; }}"
        )
        ev_lay = QVBoxLayout(self._evidence_frame)
        ev_lay.setContentsMargins(8, 6, 8, 6)
        ev_lay.setSpacing(3)

        grade_row = QHBoxLayout()
        self._grade_lbl = QLabel("—")
        self._grade_lbl.setStyleSheet(
            f"font-size:16pt; font-weight:700; color:{_MUTED}; "
            f"background:#1a1a1a; border-radius:3px; padding:1px 7px;"
        )
        self._grade_lbl.setFixedWidth(36)
        self._grade_lbl.setAlignment(Qt.AlignCenter)
        self._grade_summary_lbl = QLabel("No model loaded")
        self._grade_summary_lbl.setStyleSheet(f"font-size:11pt; color:{_MUTED};")
        grade_row.addWidget(self._grade_lbl)
        grade_row.addSpacing(8)
        grade_row.addWidget(self._grade_summary_lbl)
        grade_row.addStretch()
        ev_lay.addLayout(grade_row)

        # Up to 5 issue rows; extras collapsed by default
        self._issue_rows: list[QLabel] = []
        for _ in range(5):
            lbl = QLabel("")
            lbl.setStyleSheet(f"font-size:10pt; color:{_MUTED}; padding-left:4px;")
            lbl.setVisible(False)
            ev_lay.addWidget(lbl)
            self._issue_rows.append(lbl)

        lay.addWidget(self._evidence_frame)

        # ── Quick action buttons ──
        action_row = QHBoxLayout()
        self._explain_btn = QPushButton("Explain this tab")
        self._explain_btn.setStyleSheet(_BTN)
        self._explain_btn.setEnabled(False)
        self._explain_btn.setToolTip(
            "Ask the AI to explain what the current tab does\n"
            "and what you should check given the instrument state.")
        self._explain_btn.clicked.connect(self.explain_requested)

        self._diagnose_btn = QPushButton("Diagnose")
        self._diagnose_btn.setStyleSheet(_BTN)
        self._diagnose_btn.setEnabled(False)
        self._diagnose_btn.setToolTip(
            "Ask the AI to review the current instrument state\n"
            "and suggest fixes for any problems it finds.")
        self._diagnose_btn.clicked.connect(self.diagnose_requested)

        action_row.addWidget(self._explain_btn)
        action_row.addWidget(self._diagnose_btn)
        lay.addLayout(action_row)

        # ── Response display ──
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setStyleSheet(
            f"QTextEdit {{ background:{_BG2}; color:{_TEXT}; "
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f"font-size:12pt; font-family:Menlo,monospace; padding:6px; }}"
        )
        self._display.setPlaceholderText(
            "AI responses will appear here.\n\n"
            "Load a model in Settings → AI Assistant, then click\n"
            "\"Explain this tab\" or \"Diagnose\" to get started."
        )
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._display, 1)

        # ── Free-form input ──
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask a question…")
        self._input.setStyleSheet(
            f"QLineEdit {{ background:{_BG2}; color:{_TEXT}; "
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f"font-size:12pt; padding:5px 8px; }}"
        )
        self._input.returnPressed.connect(self._on_ask)

        self._ask_btn = QPushButton("Ask")
        self._ask_btn.setStyleSheet(_BTN_PRIMARY)
        self._ask_btn.setFixedWidth(60)
        self._ask_btn.setEnabled(False)
        self._ask_btn.clicked.connect(self._on_ask)

        input_row.addWidget(self._input)
        input_row.addWidget(self._ask_btn)
        lay.addLayout(input_row)

        # ── Token rate + Clear row ──
        rate_row = QHBoxLayout()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED}; "
            f"border:none; font-size:10pt; padding:0px 4px; }}"
            f"QPushButton:hover {{ color:#888; }}"
        )
        self._clear_btn.setToolTip("Clear conversation history")
        self._clear_btn.clicked.connect(self._on_clear)
        self._rate_lbl = QLabel("")
        self._rate_lbl.setStyleSheet(f"font-size:10pt; color:{_MUTED};")
        self._rate_lbl.setAlignment(Qt.AlignRight)
        rate_row.addWidget(self._clear_btn)
        rate_row.addStretch()
        rate_row.addWidget(self._rate_lbl)
        lay.addLayout(rate_row)

    # ------------------------------------------------------------------ #
    #  Public API (called by MainWindow via AIService signals)             #
    # ------------------------------------------------------------------ #

    def on_status_changed(self, status: str) -> None:
        """Update status indicator and enable/disable buttons."""
        color = _STATUS_COLORS.get(status, _MUTED)
        icon  = _STATUS_ICONS.get(status, "○")
        self._status_dot.setText(icon)
        self._status_dot.setStyleSheet(f"color:{color}; font-size:16pt;")
        self._status_state.setText(status)
        self._status_state.setStyleSheet(f"font-size:11pt; color:{color};")

        can_act = (status == "ready")
        if hasattr(self, "_explain_btn"):
            self._explain_btn.setEnabled(can_act)
            self._diagnose_btn.setEnabled(can_act)
            self._ask_btn.setEnabled(can_act)
        if hasattr(self, "_input"):
            self._input.setEnabled(status != "thinking")

    def on_token(self, token: str) -> None:
        """Append a streaming token to the display."""
        cursor = self._display.textCursor()
        cursor.movePosition(cursor.End)
        self._display.setTextCursor(cursor)
        self._display.insertPlainText(token)
        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_response_complete(self, text: str, elapsed: float) -> None:
        """Show token rate after a response completes."""
        tok_count = len(text.split())
        rate = tok_count / elapsed if elapsed > 0 else 0
        self._rate_lbl.setText(f"{rate:.0f} tok/s  ·  {elapsed:.1f}s")

    def on_error(self, msg: str) -> None:
        """Display an error message in the response area."""
        if hasattr(self, "_display"):
            self._display.append(f"\n⚠  {msg}")
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
            f"font-size:16pt; font-weight:700; color:{color}; "
            f"background:#1a1a1a; border-radius:3px; padding:1px 7px;"
        )

        parts: list[str] = []
        if n_fail:
            parts.append(f"{n_fail} fail")
        if n_warn:
            parts.append(f"{n_warn} warn")
        summary = "Instrument ready" if not parts else "  ·  ".join(parts)
        self._grade_summary_lbl.setText(summary)
        self._grade_summary_lbl.setStyleSheet(
            f"font-size:11pt; color:{color if parts else _GREEN};"
        )

        # ── Issue rows (fail first, then warn) ──
        active = fails + warns
        for i, row_lbl in enumerate(self._issue_rows):
            if i < min(len(active), 5):
                # Last slot: show "…and N more" when list is truncated
                if i == 4 and len(active) > 5:
                    row_lbl.setText(f"  …and {len(active) - 4} more issues")
                    row_lbl.setStyleSheet(
                        f"font-size:10pt; color:{_MUTED}; padding-left:4px;"
                    )
                else:
                    r = active[i]
                    icon = "⊗" if r.severity == "fail" else "⚠"
                    clr  = _RED if r.severity == "fail" else _AMBER
                    row_lbl.setText(f"{icon}  {r.display_name}  ·  {r.observed}")
                    row_lbl.setStyleSheet(
                        f"font-size:10pt; color:{clr}; padding-left:4px;"
                    )
                    row_lbl.setToolTip(r.hint)
                row_lbl.setVisible(True)
            else:
                row_lbl.setVisible(False)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _on_clear(self) -> None:
        self.clear_display()
        self.clear_requested.emit()

    def _on_ask(self) -> None:
        if not hasattr(self, "_input"):
            return
        q = self._input.text().strip()
        if not q:
            return
        self._input.clear()
        self._display.append(f"\n▷  {q}\n")
        self.ask_requested.emit(q)

    def _build_not_installed_view(self, lay: QVBoxLayout) -> None:
        lay.addStretch()

        icon = QLabel("🤖")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size:32pt;")
        lay.addWidget(icon)

        msg = QLabel(
            "AI assistant requires llama-cpp-python.\n\n"
            "Install it with:\n\n"
            "pip install llama-cpp-python\n\n"
            "For GPU acceleration (Metal/CUDA):\n"
            "CMAKE_ARGS=\"-DGGML_METAL=on\" pip install llama-cpp-python"
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"font-size:12pt; color:{_MUTED};")
        lay.addWidget(msg)
        lay.addStretch()
