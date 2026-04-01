"""
ui/tabs/log_tab.py

LogTab — scrollable application log with timestamped messages and a clear button.
"""

from __future__ import annotations

import time
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QTextEdit)
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT


class LogTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        root.addWidget(self._log)
        clr = QPushButton("Clear")
        clr.setFixedWidth(80)
        clr.clicked.connect(self._log.clear)
        root.addWidget(clr)
        self._apply_styles()

    def _apply_styles(self):
        bg  = PALETTE['bg']
        dim = PALETTE['textDim']
        sub = PALETTE['textSub']
        self._log.setStyleSheet(
            f"background:{bg}; color:{dim}; "
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
            f"border:none;")
        self._ts_color = sub   # used by append()

    def set_verbosity(self, level: str) -> None:
        """Set log verbosity: 'simplified', 'standard', or 'debug'."""
        self._verbosity = level

    def append(self, msg, level: str = "info"):
        """Append a timestamped message.

        Parameters
        ----------
        msg : str
            The message text.
        level : str
            Severity: "debug", "info", "warn", "error".
            In simplified verbosity, only "warn" and "error" are shown.
        """
        verbosity = getattr(self, "_verbosity", "standard")
        if verbosity == "simplified" and level in ("debug", "info"):
            return
        if verbosity == "standard" and level == "debug":
            return
        ts    = time.strftime("%H:%M:%S")
        tscol = getattr(self, "_ts_color", PALETTE['textSub'])
        self._log.append(f"<span style='color:{tscol}'>[{ts}]</span>  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())

        # Persist to session log on disk (survives crashes)
        try:
            from logging_config import write_session
            # Strip HTML tags for the plain-text file
            write_session(f"[{ts}] {msg}"
                          .replace("<br>", "\n")
                          .replace("&amp;", "&")
                          .replace("&lt;", "<")
                          .replace("&gt;", ">"))
        except Exception:
            pass
