"""
ui/widgets/readiness_widget.py

ReadinessWidget — always-on acquisition readiness banner.

Displays a compact status bar above the Acquire tab that tells the user
whether the instrument is ready to acquire and, if not, exactly what to fix.

States
------
READY       Green banner: "● READY TO ACQUIRE"
NOT READY   Amber/red banner + list of issues with human-readable messages
UNKNOWN     Grey banner (no metrics received yet)

Usage
-----
    widget = ReadinessWidget()
    metrics_service.metrics_updated.connect(widget.update_metrics)
    acquire_tab.insert_readiness_widget(widget)

The widget updates itself via update_metrics(snapshot_dict) where the dict
is the structure produced by MetricsService._build_snapshot().
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt


# ── Style constants (match the app's dark theme) ───────────────────────────

_READY_BG       = "#0d2b22"
_READY_BORDER   = "#00d4aa"
_READY_TEXT     = "#00d4aa"

_WARN_BG        = "#2b1e0a"
_WARN_BORDER    = "#ffaa44"
_WARN_TEXT      = "#ffaa44"

_ERROR_BG       = "#2b0a0a"
_ERROR_BORDER   = "#ff6666"
_ERROR_TEXT     = "#ff6666"

_UNKNOWN_BG     = "#181818"
_UNKNOWN_BORDER = "#333"
_UNKNOWN_TEXT   = "#555"

_ISSUE_TEXT     = "#bbb"
_ISSUE_FONT     = "font-family: Menlo, monospace; font-size: 11pt;"


class ReadinessWidget(QWidget):
    """
    Compact readiness banner.  Receives metrics snapshots via update_metrics()
    and repaints itself each time.

    The widget is intentionally thin — roughly 36 px when ready, expanding
    to show the issue list when there are problems.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(0)

        # ── Outer frame (border + background change per state) ─────────
        self._frame = QFrame()
        self._frame.setFrameShape(QFrame.StyledPanel)
        self._frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        outer.addWidget(self._frame)

        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(3)

        # ── Header row: dot + title ────────────────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._dot.setAlignment(Qt.AlignVCenter)

        self._title = QLabel("Checking instrument state…")
        self._title.setAlignment(Qt.AlignVCenter)
        self._title.setStyleSheet(
            "font-family: Menlo, monospace; font-size: 13pt; font-weight: bold;")

        header_row.addWidget(self._dot)
        header_row.addWidget(self._title)
        header_row.addStretch()
        inner.addLayout(header_row)

        # ── Issues area (hidden when ready) ───────────────────────────
        self._issues_widget = QWidget()
        self._issues_layout = QVBoxLayout(self._issues_widget)
        self._issues_layout.setContentsMargins(24, 2, 0, 0)
        self._issues_layout.setSpacing(2)
        inner.addWidget(self._issues_widget)
        self._issues_widget.hide()

        # ── Set initial (unknown) state ───────────────────────────────
        self._apply_state("unknown", "Checking instrument state…", [])

    # ================================================================ #
    #  Public slot                                                      #
    # ================================================================ #

    def update_metrics(self, snapshot: dict) -> None:
        """
        Slot connected to MetricsService.metrics_updated.

        Parameters
        ----------
        snapshot:
            dict produced by MetricsService._build_snapshot() with keys:
            ready (bool), issues (list of {code, message}).
        """
        issues = snapshot.get("issues", [])
        ready  = snapshot.get("ready", False)

        if not issues:
            self._apply_state("ready", "READY TO ACQUIRE", [])
        else:
            n = len(issues)
            label = f"NOT READY  —  {n} {'issue' if n == 1 else 'issues'}"
            msgs  = [i["message"] for i in issues]
            self._apply_state("warn", label, msgs)

    # ================================================================ #
    #  Internal rendering                                               #
    # ================================================================ #

    def _apply_state(self, state: str, title: str, messages: list[str]) -> None:
        """Re-render the widget for the given state."""
        if state == "ready":
            bg, border, fg = _READY_BG, _READY_BORDER, _READY_TEXT
            dot = "●"
        elif state == "warn":
            bg, border, fg = _WARN_BG, _WARN_BORDER, _WARN_TEXT
            dot = "⚠"
        elif state == "error":
            bg, border, fg = _ERROR_BG, _ERROR_BORDER, _ERROR_TEXT
            dot = "✗"
        else:  # unknown
            bg, border, fg = _UNKNOWN_BG, _UNKNOWN_BORDER, _UNKNOWN_TEXT
            dot = "○"

        self._frame.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 4px; }}")
        self._dot.setStyleSheet(f"color: {fg}; font-size: 14pt;")
        self._dot.setText(dot)
        self._title.setStyleSheet(
            f"font-family: Menlo, monospace; font-size: 13pt; "
            f"font-weight: bold; color: {fg};")
        self._title.setText(title)

        # Rebuild the issue labels
        self._clear_issues()
        if messages:
            for msg in messages:
                lbl = QLabel(f"✗  {msg}")
                lbl.setStyleSheet(f"color: {_ISSUE_TEXT}; {_ISSUE_FONT}")
                lbl.setWordWrap(True)
                self._issues_layout.addWidget(lbl)
            self._issues_widget.show()
        else:
            self._issues_widget.hide()

    def _clear_issues(self) -> None:
        """Remove all existing issue labels from the issues layout."""
        while self._issues_layout.count():
            item = self._issues_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
