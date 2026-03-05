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


class LogTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background:#0d0d0d; color:#666; "
            "font-family:Menlo,monospace; font-size:14pt; "
            "border:none;")
        root.addWidget(self._log)
        clr = QPushButton("Clear")
        clr.setFixedWidth(80)
        clr.clicked.connect(self._log.clear)
        root.addWidget(clr)

    def append(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"<span style='color:#444'>[{ts}]</span>  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())
