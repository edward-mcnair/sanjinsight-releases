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
from ui.theme import FONT, PALETTE, scaled_qss


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
        bg  = PALETTE.get("bg",      "#242424")
        dim = PALETTE.get("textDim", "#999999")
        sub = PALETTE.get("textSub", "#6a6a6a")
        self._log.setStyleSheet(
            f"background:{bg}; color:{dim}; "
            f"font-family:Menlo,monospace; font-size:{FONT['heading']}pt; "
            f"border:none;")
        self._ts_color = sub   # used by append()

    def append(self, msg):
        ts    = time.strftime("%H:%M:%S")
        tscol = getattr(self, "_ts_color", PALETTE.get("textSub", "#6a6a6a"))
        self._log.append(f"<span style='color:{tscol}'>[{ts}]</span>  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())
