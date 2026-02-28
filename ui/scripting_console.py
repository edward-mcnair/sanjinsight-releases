"""
ui/scripting_console.py

Built-in Python scripting console for the Microsanj Thermal Analysis System.

Provides a QPlainTextEdit-based REPL that gives operators direct access to
hardware objects, acquisition pipelines, and session data via Python.

Key use-cases
-------------
  • Sweep bias voltage across a range and acquire a session at each step
  • Run a calibration loop at multiple temperatures
  • Trigger wafer-prober integration (wafer step → acquire → log result)
  • Post-process session data (slice ROIs, fit curves, export CSVs)
  • Explore undocumented hardware register values during bring-up

Pre-injected namespace
----------------------
The console starts with these names bound:

    app       — ApplicationState singleton (app_state)
    cam       — shorthand for app_state.cam
    fpga      — shorthand for app_state.fpga
    bias      — shorthand for app_state.bias
    stage     — shorthand for app_state.stage
    tecs      — shorthand for app_state.tecs  (list)
    pipeline  — shorthand for app_state.pipeline
    np        — numpy
    log       — logging.getLogger("console")

All names update lazily (re-fetched from app_state on each execution) so
they remain valid after hardware reconnects.

Usage (Advanced tab)
--------------------
    from ui.scripting_console import ScriptingConsoleTab
    console = ScriptingConsoleTab(app_state)
    self._tabs.addTab(console, "Console")
"""

from __future__ import annotations

import code
import io
import logging
import sys
import textwrap
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import List, Optional

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPlainTextEdit,
    QPushButton, QLabel, QFrame, QShortcut, QSizePolicy,
    QCheckBox, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QTextDocument, QKeySequence,
)

log = logging.getLogger(__name__)

_BANNER = textwrap.dedent("""
    ╔══════════════════════════════════════════════════════════════╗
    ║       Microsanj Python Scripting Console                     ║
    ║  Pre-bound: app, cam, fpga, bias, stage, tecs, pipeline, np ║
    ║  Press Shift+Enter or click Run to execute.                  ║
    ║  History: ↑ / ↓ to navigate previous commands.             ║
    ╚══════════════════════════════════════════════════════════════╝
""").strip()

_STARTER_SCRIPT = textwrap.dedent("""
# Example — acquire a session and inspect the result
# pipeline.start(n_frames=16, inter_phase_delay=0.1)
# result = pipeline.wait()
# print("SNR:", result.snr_db)
# print("Shape:", result.delta_r_over_r.shape)
""").strip()


# ================================================================== #
#  Syntax highlighter (minimal Python)                                #
# ================================================================== #

class _PySyntaxHighlighter(QSyntaxHighlighter):
    """Very lightweight Python syntax highlighter for the editor pane."""

    import re as _re

    _KEYWORD_PAT = _re.compile(
        r'\b(import|from|def|class|return|if|elif|else|for|while|'
        r'with|as|try|except|finally|raise|pass|break|continue|'
        r'and|or|not|in|is|None|True|False|lambda|yield|global|'
        r'nonlocal|del|assert|print)\b'
    )
    _STRING_PAT  = _re.compile(r'(""".*?"""|\'\'\'.*?\'\'\'|".*?"|\'.*?\')',
                                _re.DOTALL)
    _COMMENT_PAT = _re.compile(r'#.*')
    _NUMBER_PAT  = _re.compile(r'\b\d+(\.\d+)?\b')

    def __init__(self, doc):
        super().__init__(doc)
        self._kw_fmt  = self._fmt("#569cd6", bold=True)
        self._str_fmt = self._fmt("#ce9178")
        self._cm_fmt  = self._fmt("#6a9955", italic=True)
        self._nm_fmt  = self._fmt("#b5cea8")

    @staticmethod
    def _fmt(hex_color: str, bold=False, italic=False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(hex_color))
        if bold:
            f.setFontWeight(QFont.Bold)
        if italic:
            f.setFontItalic(True)
        return f

    def highlightBlock(self, text: str):
        for pat, fmt in [
            (self._STRING_PAT,  self._str_fmt),
            (self._COMMENT_PAT, self._cm_fmt),
            (self._KEYWORD_PAT, self._kw_fmt),
            (self._NUMBER_PAT,  self._nm_fmt),
        ]:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ================================================================== #
#  Output capture helper                                              #
# ================================================================== #

class _OutputBuffer(io.StringIO):
    """StringIO that also emits a Qt signal on write."""
    pass


# ================================================================== #
#  ScriptingConsoleTab                                                #
# ================================================================== #

class ScriptingConsoleTab(QWidget):
    """
    Split-pane Python scripting console.

    Left pane  — multi-line script editor with syntax highlighting.
    Right pane — REPL output log (read-only).

    The namespace is rebuilt before each execution so that hardware
    references (cam, fpga, …) always reflect the current app_state.
    """

    def __init__(self, app_state=None, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._history:    List[str] = []
        self._hist_idx:   int       = -1
        self._build()

    # ── UI ──────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ─ Toolbar ─
        toolbar = QHBoxLayout()
        root.addLayout(toolbar)

        title_lbl = QLabel("Python Console")
        title_lbl.setStyleSheet(
            "color:#ccc; font-size:14pt; font-weight:600; font-family:Menlo,monospace;")
        toolbar.addWidget(title_lbl)
        toolbar.addStretch(1)

        self._run_btn = QPushButton("▶  Run  (Shift+Enter)")
        self._run_btn.setFixedHeight(28)
        self._run_btn.setStyleSheet(
            "background:#005a30; color:#fff; font-weight:600; "
            "border-radius:3px; padding:0 10px;")
        self._run_btn.clicked.connect(self._run_script)
        toolbar.addWidget(self._run_btn)

        self._clear_btn = QPushButton("Clear Output")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.clicked.connect(self._output.clear
                                         if hasattr(self, "_output") else lambda: None)
        toolbar.addWidget(self._clear_btn)

        self._save_btn = QPushButton("Save Script…")
        self._save_btn.setFixedHeight(28)
        self._save_btn.clicked.connect(self._save_script)
        toolbar.addWidget(self._save_btn)

        self._load_btn = QPushButton("Load Script…")
        self._load_btn.setFixedHeight(28)
        self._load_btn.clicked.connect(self._load_script)
        toolbar.addWidget(self._load_btn)

        # ─ Split pane ─
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # Editor (left)
        editor_frame = QFrame()
        editor_frame.setStyleSheet("border:1px solid #2a2a2a; border-radius:4px;")
        editor_lay   = QVBoxLayout(editor_frame)
        editor_lay.setContentsMargins(0, 0, 0, 0)

        editor_lbl = QLabel("  Script Editor")
        editor_lbl.setStyleSheet(
            "color:#888; font-size:12pt; padding:3px 0; "
            "background:#161616; border-bottom:1px solid #2a2a2a;")
        editor_lay.addWidget(editor_lbl)

        self._editor = QPlainTextEdit()
        self._editor.setFont(self._mono_font())
        self._editor.setStyleSheet(
            "background:#0d0d0d; color:#d4d4d4; border:none; "
            "selection-background-color:#264f78;")
        self._editor.setPlainText(_STARTER_SCRIPT)
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor_lay.addWidget(self._editor)

        # Syntax highlighting
        _PySyntaxHighlighter(self._editor.document())

        # Shift+Enter shortcut
        _run_sc = QShortcut(QKeySequence("Shift+Return"), self._editor)
        _run_sc.activated.connect(self._run_script)

        splitter.addWidget(editor_frame)

        # Output (right)
        output_frame = QFrame()
        output_frame.setStyleSheet("border:1px solid #2a2a2a; border-radius:4px;")
        output_lay = QVBoxLayout(output_frame)
        output_lay.setContentsMargins(0, 0, 0, 0)

        output_lbl = QLabel("  Output")
        output_lbl.setStyleSheet(
            "color:#888; font-size:12pt; padding:3px 0; "
            "background:#161616; border-bottom:1px solid #2a2a2a;")
        output_lay.addWidget(output_lbl)

        self._output = QPlainTextEdit()
        self._output.setFont(self._mono_font())
        self._output.setStyleSheet(
            "background:#0d0d0d; color:#b0b0b0; border:none;")
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QPlainTextEdit.NoWrap)
        output_lay.addWidget(self._output)

        splitter.addWidget(output_frame)
        splitter.setSizes([500, 500])

        # Fix the clear button now that _output exists
        self._clear_btn.clicked.disconnect()
        self._clear_btn.clicked.connect(self._output.clear)

        # ─ Namespace info ─
        ns_lbl = QLabel(
            "Namespace: app · cam · fpga · bias · stage · tecs · pipeline · np · log")
        ns_lbl.setStyleSheet("color:#555; font-size:12pt; font-family:Menlo,monospace;"
                             " padding:2px 4px;")
        root.addWidget(ns_lbl)

        # Print banner
        self._print_to_output(_BANNER, color="#5ec4a0")

    @staticmethod
    def _mono_font() -> QFont:
        font = QFont("Menlo")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(14)
        return font

    # ── Namespace ────────────────────────────────────────────────────

    def _build_namespace(self) -> dict:
        """Build the execution namespace, pulling live references from app_state."""
        ns: dict = {
            "__name__": "__console__",
            "__builtins__": __builtins__,
            "np":  np,
            "log": logging.getLogger("console"),
            "time": time,
        }
        if self._app_state is not None:
            s = self._app_state
            ns.update({
                "app":      s,
                "cam":      s.cam,
                "fpga":     s.fpga,
                "bias":     s.bias,
                "stage":    s.stage,
                "tecs":     s.tecs,
                "pipeline": s.pipeline,
                "active_calibration": s.active_calibration,
                "active_profile":     s.active_profile,
                "active_analysis":    s.active_analysis,
            })
        return ns

    # ── Execution ────────────────────────────────────────────────────

    def _run_script(self):
        script = self._editor.toPlainText().strip()
        if not script:
            return

        self._history.append(script)
        self._hist_idx = len(self._history)

        self._print_to_output(
            f"\n{'─' * 60}\n▶  {time.strftime('%H:%M:%S')}\n{'─' * 60}",
            color="#444"
        )

        ns  = self._build_namespace()
        buf = io.StringIO()

        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                exec(compile(script, "<console>", "exec"), ns)   # noqa: S102
            output = buf.getvalue()
            if output:
                self._print_to_output(output, color="#d4d4d4")
            self._print_to_output("✓  Done", color="#4ec94e")
        except SystemExit:
            self._print_to_output("SystemExit caught — ignoring.", color="#ffaa00")
        except Exception:
            tb = traceback.format_exc()
            self._print_to_output(tb, color="#f44747")

    def _print_to_output(self, text: str, color: str = "#b0b0b0"):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self._output.textCursor()
        cursor.movePosition(cursor.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    # ── History navigation ────────────────────────────────────────────

    def keyPressEvent(self, event):
        if self._editor.hasFocus():
            if event.key() == Qt.Key_Up and event.modifiers() == Qt.ControlModifier:
                self._hist_back()
                return
            if event.key() == Qt.Key_Down and event.modifiers() == Qt.ControlModifier:
                self._hist_forward()
                return
        super().keyPressEvent(event)

    def _hist_back(self):
        if not self._history:
            return
        self._hist_idx = max(0, self._hist_idx - 1)
        self._editor.setPlainText(self._history[self._hist_idx])

    def _hist_forward(self):
        if not self._history:
            return
        self._hist_idx = min(len(self._history), self._hist_idx + 1)
        if self._hist_idx < len(self._history):
            self._editor.setPlainText(self._history[self._hist_idx])
        else:
            self._editor.clear()

    # ── File I/O ─────────────────────────────────────────────────────

    def _save_script(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Script",
            str(__import__("pathlib").Path.home() / "script.py"),
            "Python Script (*.py)"
        )
        if path:
            try:
                with open(path, "w") as f:
                    f.write(self._editor.toPlainText())
                self._print_to_output(f"Script saved → {path}", color="#4ec94e")
            except Exception as e:
                self._print_to_output(f"Save error: {e}", color="#f44747")

    def _load_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Script",
            str(__import__("pathlib").Path.home()),
            "Python Script (*.py);;All files (*)"
        )
        if path:
            try:
                with open(path) as f:
                    self._editor.setPlainText(f.read())
                self._print_to_output(f"Loaded → {path}", color="#4ec94e")
            except Exception as e:
                self._print_to_output(f"Load error: {e}", color="#f44747")
