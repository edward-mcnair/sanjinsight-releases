"""
ui/widgets/preflight_dialog.py

Pre-capture validation dialog — shows preflight check results and lets
the user proceed or cancel.

Displayed only when at least one check is warn or fail.  When all checks
pass, acquisition starts immediately (no dialog).
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


# ── Status icons and colours ─────────────────────────────────────────────────

_STATUS_ICON = {
    "pass": "✓",
    "warn": "⚠",
    "fail": "✗",
}
_STATUS_COLOR = {
    "pass": lambda: PALETTE.get("success", "#00d479"),
    "warn": lambda: PALETTE.get("warning", "#ffb300"),
    "fail": lambda: PALETTE.get("danger",  "#ff4444"),
}


class PreflightDialog(QDialog):
    """
    Modal dialog displaying preflight validation results.

    Parameters
    ----------
    preflight : PreflightResult
        Result from PreflightValidator.run().
    parent : QWidget, optional
    """

    def __init__(self, preflight, parent=None):
        super().__init__(parent)
        self._preflight = preflight
        self.setWindowTitle("Pre-Capture Validation")
        self.setMinimumWidth(520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 16, 20, 16)

        # ── Header ────────────────────────────────────────────────────
        has_fail = any(c.status == "fail" for c in preflight.checks)
        has_warn = any(c.status == "warn" for c in preflight.checks)

        if has_fail:
            header_text = "Pre-capture checks found issues"
            header_color = _STATUS_COLOR["fail"]()
        elif has_warn:
            header_text = "Pre-capture checks have warnings"
            header_color = _STATUS_COLOR["warn"]()
        else:
            header_text = "All pre-capture checks passed"
            header_color = _STATUS_COLOR["pass"]()

        header = QLabel(header_text)
        header.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:700; "
            f"color:{header_color};")
        root.addWidget(header)

        # ── Check list ────────────────────────────────────────────────
        for check in preflight.checks:
            root.addWidget(self._build_check_row(check))

        # ── Timing ────────────────────────────────────────────────────
        timing = QLabel(f"Completed in {preflight.duration_ms:.0f} ms")
        timing.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE.get('textDim', '#888')};")
        root.addWidget(timing)

        # ── Separator ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE.get('border', '#444')};")
        root.addWidget(sep)

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        if has_fail:
            proceed_btn = QPushButton("Start Despite Failures")
            proceed_btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid {_STATUS_COLOR['fail']()}; "
                f"color: {_STATUS_COLOR['fail']()}; padding: 6px 16px; "
                f"border-radius: 4px; }}")
            cancel_btn.setDefault(True)
        elif has_warn:
            proceed_btn = QPushButton("Start Anyway")
            proceed_btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid {_STATUS_COLOR['warn']()}; "
                f"color: {_STATUS_COLOR['warn']()}; padding: 6px 16px; "
                f"border-radius: 4px; }}")
            proceed_btn.setDefault(True)
        else:
            proceed_btn = QPushButton("Start Acquisition")
            proceed_btn.setDefault(True)

        proceed_btn.clicked.connect(self.accept)
        btn_row.addWidget(proceed_btn)
        root.addLayout(btn_row)

    def _build_check_row(self, check) -> QFrame:
        """Build a single check result row."""
        row = QFrame()
        row.setFrameShape(QFrame.NoFrame)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        # Status icon
        icon = QLabel(_STATUS_ICON.get(check.status, "?"))
        color = _STATUS_COLOR.get(check.status, lambda: "#888")()
        icon.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; color:{color}; "
            f"font-weight:700; min-width:20px;")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        # Name + details column
        details = QVBoxLayout()
        details.setSpacing(2)

        name_lbl = QLabel(check.display_name)
        name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{PALETTE.get('text', '#eee')};")
        details.addWidget(name_lbl)

        obs_lbl = QLabel(check.observed)
        obs_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; "
            f"font-size:{FONT['caption']}pt; "
            f"color:{PALETTE.get('textDim', '#888')};")
        details.addWidget(obs_lbl)

        if check.hint and check.status != "pass":
            hint_lbl = QLabel(check.hint)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet(
                f"font-size:{FONT['caption']}pt; "
                f"color:{color}; padding-left:2px;")
            details.addWidget(hint_lbl)

        lay.addLayout(details, 1)
        return row
