"""
ui/widgets/readiness_widget.py

ReadinessWidget — always-on acquisition readiness banner.

Displays a compact status bar above the Acquire tab that tells the user
whether the instrument is ready to acquire and, if not, exactly what to fix.

States
------
READY       Green banner: "● READY TO ACQUIRE"
NOT READY   Amber/red banner + list of issues; each issue with a "Fix it →"
            link that navigates directly to the relevant hardware tab.
UNKNOWN     Grey banner (no metrics received yet)

Signals
-------
navigate_requested(str)
    Emitted when the user clicks a "Fix it →" button.
    The string is a sidebar panel label (e.g. "Camera", "Temperature").
    Connect to SidebarNav.select_by_label() in MainWindow.

Usage
-----
    widget = ReadinessWidget()
    metrics_service.metrics_updated.connect(widget.update_metrics)
    widget.navigate_requested.connect(nav.select_by_label)
    acquire_tab.insert_readiness_widget(widget)
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSizePolicy, QPushButton,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT, MONO_FONT


# ── Issue code → sidebar panel label mapping ───────────────────────────────────
#
# ReadinessWidget uses this table to attach "Fix it →" buttons to issues that
# have a corresponding hardware tab.  Issue codes are those produced by
# ai/metrics_service.py.  Codes with dynamic suffixes (e.g. tec_not_stable_0)
# are matched via startswith().
#
# Note: FPGA issues map to "Stimulus" (the merged Stimulus tab that contains
# the FPGA modulation controls).  Stage homing issues map to "Stage".

_NAV_MAP: dict[str, str] = {
    "camera_disconnected":  "Camera",
    "camera_saturated":     "Camera",
    "camera_underexposed":  "Camera",
    "high_drift":           "Camera",
    "poor_focus":           "Camera",
    "fpga_not_running":     "Stimulus",
    "fpga_not_locked":      "Stimulus",
    "stage_not_homed":      "Stage",
    # TEC codes have a channel suffix: tec_not_stable_0, tec_not_stable_1
    # These are matched via the prefix check in _nav_target_for().
    "tec_not_stable":       "Temperature",
    "tec_disabled":         "Temperature",
    "tec_alarm":            "Temperature",
}


def _nav_target_for(code: str) -> str | None:
    """Return the sidebar label for *code*, or None if not navigable."""
    if code in _NAV_MAP:
        return _NAV_MAP[code]
    # Handle suffixed TEC codes (tec_not_stable_0, tec_not_stable_1 …)
    for prefix, target in _NAV_MAP.items():
        if code.startswith(prefix):
            return target
    return None


class ReadinessWidget(QWidget):
    """
    Compact readiness banner.  Receives metrics snapshots via update_metrics()
    and repaints itself each time.

    The widget is intentionally thin — ~36 px when ready, expanding to show
    the issue list (with Fix it links) when there are problems.
    """

    navigate_requested = pyqtSignal(str)   # emitted with sidebar panel label
    fix_requested      = pyqtSignal(str)   # emitted with issue code (e.g. "stage_not_homed")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(0)

        # ── Outer frame ────────────────────────────────────────────────
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
            f"font-family:{MONO_FONT}; "
            f"font-size: {FONT['label']}pt; font-weight: bold;")
        self._title.setToolTip(
            "Shows whether the instrument meets all acquisition prerequisites.\n"
            "Click 'Fix it →' next to any issue to jump to the relevant hardware tab."
        )

        header_row.addWidget(self._dot)
        header_row.addWidget(self._title)
        header_row.addStretch()

        # ── Trend indicators (drift + focus arrows) ──────────────────
        self._trend_widget = QWidget()
        trend_lay = QHBoxLayout(self._trend_widget)
        trend_lay.setContentsMargins(0, 0, 0, 0)
        trend_lay.setSpacing(6)
        self._drift_trend = QLabel()
        self._focus_trend = QLabel()
        trend_lay.addWidget(self._drift_trend)
        trend_lay.addWidget(self._focus_trend)
        self._trend_widget.setVisible(False)
        header_row.addWidget(self._trend_widget)

        inner.addLayout(header_row)

        # ── Issues area (hidden when ready) ───────────────────────────
        self._issues_widget = QWidget()
        self._issues_widget.setStyleSheet("background: transparent;")
        self._issues_layout = QVBoxLayout(self._issues_widget)
        self._issues_layout.setContentsMargins(24, 2, 0, 0)
        self._issues_layout.setSpacing(3)
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

        if not issues:
            self._apply_state("ready", "READY TO ACQUIRE", [])
        else:
            n = len(issues)
            label = f"NOT READY  —  {n} {'issue' if n == 1 else 'issues'}"
            self._apply_state("warn", label, issues)

        # ── Update trend indicators ──────────────────────────────────
        cam = snapshot.get("camera", {})
        self._update_trend(self._drift_trend, "Drift",
                           cam.get("drift_trend", "stable"))
        self._update_trend(self._focus_trend, "Focus",
                           cam.get("focus_trend", "stable"))
        has_trend = cam.get("drift_trend", "stable") != "stable" or \
                    cam.get("focus_trend", "stable") != "stable"
        self._trend_widget.setVisible(has_trend)

    # ================================================================ #
    #  Internal rendering                                               #
    # ================================================================ #

    def _apply_state(self, state: str, title: str, issues: list) -> None:
        """Re-render the widget for the given state."""
        if state == "ready":
            bg, border, fg = (PALETTE['readyBg'],
                              PALETTE['readyBorder'],
                              PALETTE['success'])
            dot = "●"
        elif state == "warn":
            bg, border, fg = (PALETTE['warnBg'],
                              PALETTE['warnBorder'],
                              PALETTE['warning'])
            dot = "⚠"
        elif state == "error":
            bg, border, fg = (PALETTE['errorBg'],
                              PALETTE['errorBorder'],
                              PALETTE['danger'])
            dot = "✗"
        else:  # unknown
            bg, border, fg = (PALETTE['unknownBg'],
                              PALETTE['unknownBorder'],
                              PALETTE['textDim'])
            dot = "○"

        self._frame.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 4px; }}")
        self._dot.setStyleSheet(f"color: {fg}; font-size: {FONT['label']}pt;")
        self._dot.setText(dot)
        self._title.setStyleSheet(
            f"font-family:{MONO_FONT}; "
            f"font-size: {FONT['label']}pt; font-weight: bold; color: {fg};")
        self._title.setText(title)

        # Rebuild the issue rows
        self._clear_issues()
        if issues:
            for issue in issues:
                msg  = issue.get("message", str(issue)) if isinstance(issue, dict) else str(issue)
                code = issue.get("code", "")            if isinstance(issue, dict) else ""
                nav  = _nav_target_for(code)
                self._issues_layout.addLayout(self._issue_row(msg, nav, code))
            self._issues_widget.show()
        else:
            self._issues_widget.hide()

    def _issue_row(self, message: str, nav_target: str | None,
                   code: str = "") -> QHBoxLayout:
        """Build one issue row: ✗ message text  [Fix it →]."""
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel(f"✗  {message}")
        lbl.setStyleSheet(
            f"background: transparent; color: {PALETTE['text']}; "
            f"font-family:{MONO_FONT}; font-size: {FONT['sublabel']}pt;")
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)

        if nav_target:
            fix_btn = QPushButton(f"Fix it →")
            fix_btn.setFixedHeight(20)
            fix_btn.setCursor(Qt.PointingHandCursor)
            fix_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {PALETTE['accent']};
                    border: none;
                    font-size: {FONT["caption"]}pt;
                    font-weight: 600;
                    padding: 0 4px;
                }}
                QPushButton:hover {{ color: {PALETTE['textOnAccent']}; }}
            """)
            fix_btn.setToolTip(
                f"Auto-fix this issue" if code else f"Open {nav_target} tab")
            # Emit fix_requested with the issue code so main_app can
            # auto-fix (e.g. home stage) or fall back to navigation.
            fix_btn.clicked.connect(
                lambda _, c=code, t=nav_target: (
                    self.fix_requested.emit(c) if c else
                    self.navigate_requested.emit(t)))
            row.addWidget(fix_btn)

        return row

    def _update_trend(self, label: QLabel, name: str, trend: str) -> None:
        """Update a single trend indicator label."""
        if trend == "improving":
            arrow = "↑"
            color = PALETTE['success']
            tip = f"{name} is improving"
        elif trend == "degrading":
            arrow = "↓"
            color = PALETTE['warning']
            tip = f"{name} is degrading"
        else:
            label.setText("")
            return
        label.setText(f"{name} {arrow}")
        label.setStyleSheet(
            f"color: {color}; font-size: {FONT['caption']}pt; "
            f"font-weight: 600;")
        label.setToolTip(tip)

    def _apply_styles(self) -> None:
        """Re-apply PALETTE / FONT styles after a theme change.

        Delegates to ``_apply_state`` which already sets every inline
        stylesheet on ``_frame``, ``_dot``, ``_title``, and rebuilds the
        issue rows.  We simply re-trigger whatever visual state the widget
        is currently showing.
        """
        # Determine the current logical state from the existing title text.
        title = self._title.text()
        if title.startswith("READY"):
            state = "ready"
        elif title.startswith("NOT READY"):
            state = "warn"
        elif title == "Checking instrument state…":
            state = "unknown"
        else:
            state = "unknown"

        # Collect current issue data from the existing layout (if any).
        # _apply_state will clear and re-render them, so we just need the
        # text that is already visible — but the issue dicts are not stored.
        # Re-rendering with the current title/state is sufficient because
        # update_metrics() will be called again shortly with fresh data.
        self._apply_state(state, title, [])

        # Refresh trend labels with current palette colours
        for lbl in (self._drift_trend, self._focus_trend):
            # Re-read the existing text to decide colour
            txt = lbl.text()
            if "↑" in txt:
                color = PALETTE['success']
            elif "↓" in txt:
                color = PALETTE['warning']
            else:
                continue
            lbl.setStyleSheet(
                f"color: {color}; font-size: {FONT['caption']}pt; "
                f"font-weight: 600;")

    def _clear_issues(self) -> None:
        """Remove all existing issue rows from the issues layout."""
        while self._issues_layout.count():
            item = self._issues_layout.takeAt(0)
            if item is None:
                break
            # item may be a layout (QHBoxLayout) or a widget
            if item.layout():
                sub = item.layout()
                while sub.count():
                    child = sub.takeAt(0)
                    if child and child.widget():
                        child.widget().deleteLater()
            elif item.widget():
                item.widget().deleteLater()
