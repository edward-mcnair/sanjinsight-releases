"""
ui/widgets/calibration_indicator.py

Calibration status indicator — small widget placed on each capture tab
showing the current calibration state at a glance.

Three states:
  - Active    (green dot)  — valid calibration loaded, age within threshold
  - Stale     (amber dot)  — valid calibration but older than STALE_DAYS
  - None      (dim dot)    — no calibration loaded

Clicking the indicator navigates to the Calibration tab.

Usage
-----
    indicator = CalibrationIndicator()
    some_layout.addWidget(indicator)

    # Update when calibration changes:
    indicator.update_state(app_state.active_calibration)

    # Wire navigation:
    indicator.navigate_requested.connect(
        lambda: nav.select_by_label(NL.CALIBRATION))
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT


# Default threshold: calibration older than this many days shows as "stale"
STALE_DAYS = 7.0


class CalibrationIndicator(QWidget):
    """Compact calibration status badge for capture tabs."""

    navigate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(28)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)

        self._dot = QLabel("\u25cf")  # ● filled circle
        self._dot.setFixedWidth(14)
        self._dot.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._dot)

        self._text = QLabel("Calibration: checking...")
        self._text.setWordWrap(False)
        lay.addWidget(self._text, 1)

        self._nav_btn = QPushButton("Calibrate")
        self._nav_btn.setFixedHeight(22)
        self._nav_btn.setCursor(Qt.PointingHandCursor)
        self._nav_btn.setToolTip("Go to Calibration tab")
        self._nav_btn.clicked.connect(self.navigate_requested.emit)
        lay.addWidget(self._nav_btn)

        self._state = "none"  # "active" | "stale" | "none"
        self._apply_styles()
        self.update_state(None)

    # ── Public API ───────────────────────────────────────────────────

    def update_state(self, cal_result) -> None:
        """Update indicator from a CalibrationResult (or None).

        Parameters
        ----------
        cal_result
            The CalibrationResult object, or None if no calibration is
            loaded.  Must have `.valid`, `.timestamp`, `.n_points`,
            `.t_min`, `.t_max`, `.timestamp_str` attributes.
        """
        if cal_result is None or not getattr(cal_result, "valid", False):
            self._set_none()
            return

        age_s = time.time() - getattr(cal_result, "timestamp", 0)
        age_days = age_s / 86400.0

        n_pts = getattr(cal_result, "n_points", 0)
        t_min = getattr(cal_result, "t_min", 0)
        t_max = getattr(cal_result, "t_max", 0)
        ts_str = getattr(cal_result, "timestamp_str", "")

        if age_days > STALE_DAYS:
            self._set_stale(n_pts, t_min, t_max, ts_str, age_days)
        else:
            self._set_active(n_pts, t_min, t_max, ts_str)

    # ── Internal state setters ───────────────────────────────────────

    def _set_active(self, n_pts, t_min, t_max, ts_str):
        self._state = "active"
        self._dot.setStyleSheet(
            f"color: {PALETTE['success']}; font-size: 11pt;"
            f" background: transparent;")
        self._text.setText(
            f"Calibrated  \u2014  {n_pts}-pt, "
            f"{t_min:.0f}\u2013{t_max:.0f}\u00b0C, {ts_str}")
        self._text.setStyleSheet(
            f"color: {PALETTE['textSub']}; font-size: {FONT['label']}pt;"
            f" background: transparent;")
        self._nav_btn.setText("Recalibrate")
        self._apply_btn_style("dim")

    def _set_stale(self, n_pts, t_min, t_max, ts_str, age_days):
        self._state = "stale"
        self._dot.setStyleSheet(
            f"color: {PALETTE['warning']}; font-size: 11pt;"
            f" background: transparent;")
        self._text.setText(
            f"Stale calibration  \u2014  {age_days:.0f} days old "
            f"({n_pts}-pt, {ts_str})")
        self._text.setStyleSheet(
            f"color: {PALETTE['warning']}; font-size: {FONT['label']}pt;"
            f" background: transparent;")
        self._nav_btn.setText("Recalibrate")
        self._apply_btn_style("warn")

    def _set_none(self):
        self._state = "none"
        self._dot.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: 11pt;"
            f" background: transparent;")
        self._text.setText("No calibration active")
        self._text.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: {FONT['label']}pt;"
            f" background: transparent;")
        self._nav_btn.setText("Calibrate")
        self._apply_btn_style("accent")

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self):
        """Re-apply palette-driven styles (called on theme switch)."""
        self.setStyleSheet(
            f"CalibrationIndicator {{"
            f"  background: {PALETTE['surface2']};"
            f"  border: 1px solid {PALETTE['border']};"
            f"  border-radius: 4px;"
            f"}}")
        # Re-apply current state
        if hasattr(self, "_state"):
            # Force refresh via current state
            pass  # The state methods set styles inline

    def _apply_btn_style(self, mode: str):
        if mode == "accent":
            bg = PALETTE["accent"]
            fg = "#ffffff"
        elif mode == "warn":
            bg = PALETTE["warning"]
            fg = "#ffffff"
        else:
            bg = PALETTE["surface2"]
            fg = PALETTE["textSub"]
        self._nav_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {fg};"
            f"  border: none; border-radius: 3px;"
            f"  padding: 2px 8px; font-size: {FONT['label']}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  opacity: 0.85;"
            f"}}")
