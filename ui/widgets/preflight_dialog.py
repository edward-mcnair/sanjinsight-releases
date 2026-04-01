"""
ui/widgets/preflight_dialog.py

Pre-capture validation dialog — shows preflight check results and lets
the user proceed or cancel.

Displayed only when at least one check is warn or fail.  When all checks
pass, acquisition starts immediately (no dialog).
"""

from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer

from ui.theme import PALETTE, FONT, MONO_FONT

log = logging.getLogger(__name__)


# ── Status icons and colours ─────────────────────────────────────────────────

_STATUS_ICON = {
    "pass": "✓",
    "warn": "⚠",
    "fail": "✗",
}
_STATUS_COLOR = {
    "pass": lambda: PALETTE['success'],
    "warn": lambda: PALETTE['warning'],
    "fail": lambda: PALETTE['danger'],
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

    def __init__(self, preflight, remediations=None, parent=None):
        super().__init__(parent)
        self._preflight = preflight
        self._remediations = {r.rule_id: r for r in (remediations or [])}
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
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")
        root.addWidget(timing)

        # ── Separator ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['border']};")
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
            f"color:{PALETTE['text']};")
        details.addWidget(name_lbl)

        obs_lbl = QLabel(check.observed)
        obs_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; "
            f"font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']};")
        details.addWidget(obs_lbl)

        if check.hint and check.status != "pass":
            hint_lbl = QLabel(check.hint)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet(
                f"font-size:{FONT['caption']}pt; "
                f"color:{color}; padding-left:2px;")
            details.addWidget(hint_lbl)

        lay.addLayout(details, 1)

        # ── Auto-fix button (if remediation available) ────────────────
        remediation = self._remediations.get(check.rule_id)
        if remediation and check.status != "pass":
            fix_btn = QPushButton(f"⚡ {remediation.label}")
            fix_btn.setCursor(Qt.PointingHandCursor)
            fix_btn.setToolTip(remediation.description)
            fix_btn.setStyleSheet(
                f"QPushButton {{ "
                f"background: {PALETTE['accent']}; "
                f"color: {PALETTE['bg']}; "
                f"border: none; border-radius: 4px; "
                f"font-size: {FONT['caption']}pt; font-weight: 700; "
                f"padding: 4px 12px; }}"
                f"QPushButton:hover {{ "
                f"background: {PALETTE['accentHover']}; }}"
                f"QPushButton:disabled {{ "
                f"background: {PALETTE['textDim']}; }}")
            fix_btn.clicked.connect(
                lambda _, r=remediation, b=fix_btn: self._run_fix(r, b))
            lay.addWidget(fix_btn, 0, Qt.AlignTop)

        return row

    def _run_fix(self, remediation, btn: QPushButton) -> None:
        """Execute a remediation action and update the button state."""
        btn.setEnabled(False)
        btn.setText("Applying…")
        # Use a timer to let the UI repaint before the (possibly blocking) action
        QTimer.singleShot(50, lambda: self._do_fix(remediation, btn))

    def _do_fix(self, remediation, btn: QPushButton) -> None:
        try:
            ok = remediation.action()
        except Exception:
            log.exception("Remediation %s failed", remediation.rule_id)
            ok = False

        if ok:
            btn.setText("✓ Applied")
            btn.setStyleSheet(
                f"QPushButton {{ "
                f"background: {PALETTE['success']}; "
                f"color: {PALETTE['bg']}; "
                f"border: none; border-radius: 4px; "
                f"font-size: {FONT['caption']}pt; font-weight: 700; "
                f"padding: 4px 12px; }}")
        else:
            btn.setText("✗ Failed")
            btn.setEnabled(True)
