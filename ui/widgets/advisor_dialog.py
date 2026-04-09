"""
ui/widgets/advisor_dialog.py

AdvisorDialog — modal AI advisor shown after profile selection.

Displays conflicts and suggestions identified by the AI, with
Proceed and Cancel buttons.  Proceed applies the suggested fixes
and continues; Cancel dismisses without changes.

Requires FULL AI tier — callers must check before showing.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import set_btn_icon

log = logging.getLogger(__name__)


class AdvisorDialog(QDialog):
    """
    Modal dialog showing AI advisor analysis results.

    Signals
    -------
    proceed_clicked(list)
        Emitted with a list of dicts ``[{"param": ..., "value": ..., "unit": ...}]``
        representing all fixes the user accepted.
    """

    proceed_clicked  = pyqtSignal(list)
    quick_fix        = pyqtSignal(dict)   # single fix dict: {param, value, unit}
    cancel_requested = pyqtSignal()   # emitted when user cancels during thinking

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Advisor")
        self.setMinimumWidth(460)
        self.setMaximumWidth(560)
        self.setMinimumHeight(300)
        self._is_thinking = False

        self._fixes: list[dict] = []

        bg    = PALETTE['bg']
        text  = PALETTE['text']
        sub   = PALETTE['textSub']
        bdr   = PALETTE['border']
        sur   = PALETTE['surface']
        sur2  = PALETTE['surface2']
        acc   = PALETTE['accent']
        green = PALETTE['success']
        amber = PALETTE['warning']
        red   = PALETTE['danger']

        self.setStyleSheet(f"QDialog {{ background:{bg}; color:{text}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # ── Header ──
        hdr = QHBoxLayout()
        icon_lbl = QLabel("◉")
        icon_lbl.setStyleSheet(
            f"color:{PALETTE['systemIndigo']}; font-size:{FONT['readout']}pt;")
        title_lbl = QLabel("AI Advisor")
        title_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; font-weight:700; color:{text};")
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(6)
        hdr.addWidget(title_lbl)
        hdr.addStretch()
        lay.addLayout(hdr)

        # ── Status line ──
        self._status_lbl = QLabel("Analysing profile vs instrument state…")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{sub};")
        self._status_lbl.setWordWrap(True)
        lay.addWidget(self._status_lbl)

        # ── Scrollable content area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background:{bg}; border:none; }}")

        self._content = QWidget()
        self._content.setStyleSheet(f"background:{bg};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(6)
        scroll.setWidget(self._content)
        lay.addWidget(scroll, 1)

        # ── Thinking indicator (shown during streaming) ──
        self._thinking_lbl = QLabel("◌  Thinking…")
        self._thinking_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['systemIndigo']}; "
            f"font-family:{MONO_FONT};")
        self._thinking_lbl.setAlignment(Qt.AlignCenter)
        self._content_lay.addWidget(self._thinking_lbl)

        # ── Button row ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background:{sur2}; color:{text}; "
            f"border:1px solid {bdr}; border-radius:5px; "
            f"font-size:{FONT['label']}pt; font-weight:600; padding:7px 20px; }}"
            f"QPushButton:hover {{ background:{PALETTE['danger']}18; "
            f"color:{PALETTE['danger']}; border-color:{PALETTE['danger']}66; }}")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)

        self._proceed_btn = QPushButton("Proceed")
        set_btn_icon(self._proceed_btn, "fa5s.check-circle")
        self._proceed_btn.setStyleSheet(
            f"QPushButton {{ background:{acc}; color:{PALETTE['textOnAccent']}; "
            f"border:none; border-radius:5px; "
            f"font-size:{FONT['label']}pt; font-weight:600; padding:7px 24px; }}"
            f"QPushButton:hover {{ background:{acc}dd; }}"
            f"QPushButton:disabled {{ background:{sur2}; color:{PALETTE['textDim']}; "
            f"border:1px solid {bdr}; }}")
        self._proceed_btn.setEnabled(False)
        self._proceed_btn.clicked.connect(self._on_proceed)
        btn_row.addWidget(self._proceed_btn)

        lay.addLayout(btn_row)

    # ================================================================ #
    #  Public API                                                      #
    # ================================================================ #

    def show_thinking(self) -> None:
        """Show the thinking state while AI is analysing."""
        self._is_thinking = True
        self._thinking_lbl.setVisible(True)
        self._proceed_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status_lbl.setText("Analysing profile vs instrument state…")

    def show_result(self, result, repaired: bool = False) -> None:
        """
        Populate the dialog with an AdvisorResult.

        Parameters
        ----------
        result : ai.advisor.AdvisorResult
        repaired : bool
            True if the AI's JSON output needed repair (trailing commas,
            unclosed braces, etc.).  Shows a subtle indicator so the user
            knows the output quality was degraded.
        """
        self._is_thinking = False
        self._thinking_lbl.setVisible(False)

        # Clear previous content (keep thinking_lbl reference)
        while self._content_lay.count() > 0:
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w and w is not self._thinking_lbl:
                w.deleteLater()

        if not result.parse_ok:
            # Fallback: show raw AI response as prose
            self._show_fallback(result.raw_text)
            return

        self._fixes.clear()
        bg   = PALETTE['bg']
        text = PALETTE['text']
        sub  = PALETTE['textSub']
        bdr  = PALETTE['border']

        # ── Repaired-output indicator ──
        if repaired:
            repair_lbl = QLabel("⚙  Output was auto-repaired from malformed JSON")
            repair_lbl.setWordWrap(True)
            repair_lbl.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
                f"background:{PALETTE['surface2']}; "
                f"border:1px solid {PALETTE['warning']}33; border-radius:3px; "
                f"padding:4px 8px;")
            repair_lbl.setToolTip(
                "The AI model produced slightly malformed JSON that was\n"
                "automatically fixed (e.g. trailing commas, unclosed braces).\n"
                "Results may be less reliable than clean output.\n\n"
                "Consider upgrading to a larger model for more consistent output.")
            self._content_lay.addWidget(repair_lbl)

        # ── Summary (cloud models provide a physics-based assessment) ──
        if result.summary:
            summary_lbl = QLabel(result.summary)
            summary_lbl.setWordWrap(True)
            summary_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{PALETTE['text']}; "
                f"background:{PALETTE['surface']}; "
                f"border:1px solid {PALETTE['accent']}33; border-radius:4px; "
                f"padding:8px 10px;")
            self._content_lay.addWidget(summary_lbl)

        # ── Conflicts ──
        if result.conflicts:
            n = len(result.conflicts)
            self._status_lbl.setText(
                f"Found {n} {'conflict' if n == 1 else 'conflicts'}"
                + (" — review before proceeding." if not result.ready
                   else " — instrument can still proceed."))
            self._status_lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; "
                f"color:{PALETTE['warning'] if not result.ready else PALETTE['accent']};")

            for c in result.conflicts:
                fix = ({"param": c.param, "value": c.value, "unit": c.unit}
                       if c.param and c.value is not None else None)
                card = self._make_card(
                    icon="⚠", icon_color=PALETTE['warning'],
                    title=c.issue,
                    detail=(f"Suggested: set {c.param} to {c.value} {c.unit}"
                            if c.param else ""),
                    fix_dict=fix)
                self._content_lay.addWidget(card)
                if fix:
                    self._fixes.append(fix)
        else:
            self._status_lbl.setText("No conflicts found — instrument looks good.")
            self._status_lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['success']};")

        # ── Suggestions ──
        if result.suggestions:
            sep = QLabel("Suggestions")
            sep.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{sub}; "
                f"font-weight:600; padding-top:6px;")
            self._content_lay.addWidget(sep)

            for s in result.suggestions:
                detail = ""
                if s.param:
                    detail = f"Set {s.param} to {s.value} {s.unit}"
                if s.reason:
                    detail += f" — {s.reason}" if detail else s.reason
                fix = ({"param": s.param, "value": s.value, "unit": s.unit}
                       if s.param and s.value is not None else None)
                card = self._make_card(
                    icon="→", icon_color=PALETTE['accent'],
                    title=detail or s.reason,
                    detail="",
                    fix_dict=fix)
                self._content_lay.addWidget(card)
                if fix:
                    self._fixes.append(fix)

        self._content_lay.addStretch()

        # Enable proceed — even with 0 fixes, user may want to dismiss and continue
        self._proceed_btn.setEnabled(True)
        if self._fixes:
            self._proceed_btn.setText(f"Apply {len(self._fixes)} fixes & proceed")
        else:
            self._proceed_btn.setText("Proceed")

    def show_error(self, msg: str) -> None:
        """Show an error state in the dialog."""
        self._is_thinking = False
        self._thinking_lbl.setVisible(False)
        self._status_lbl.setText(f"Advisor error: {msg}")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['danger']};")
        # Let user dismiss
        self._proceed_btn.setText("Close")
        self._proceed_btn.setEnabled(True)

    # ================================================================ #
    #  Internal                                                        #
    # ================================================================ #

    def _show_fallback(self, raw_text: str) -> None:
        """Display raw AI text when JSON parsing failed."""
        self._status_lbl.setText(
            "AI provided advice in text form (structured analysis unavailable):")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textSub']};")

        lbl = QLabel(raw_text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['text']}; "
            f"font-family:{MONO_FONT}; background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:4px; "
            f"padding:10px;")
        self._content_lay.addWidget(lbl)
        self._content_lay.addStretch()

        self._proceed_btn.setText("Proceed")
        self._proceed_btn.setEnabled(True)

    # Parameters considered safe for one-click quick-fix application.
    # Must match the allowlist in MainWindow._on_advisor_proceed().
    _SAFE_PARAMS: set[str] = {
        "exposure", "exposure_us", "gain", "gain_db",
        "stimulus_freq", "stimulus_freq_hz", "stimulus_duty",
        "tec_setpoint", "tec_setpoint_c", "n_frames",
    }

    _PARAM_UNITS: dict[str, str] = {
        "exposure": "µs", "exposure_us": "µs",
        "gain": "dB", "gain_db": "dB",
        "stimulus_freq": "Hz", "stimulus_freq_hz": "Hz",
        "stimulus_duty": "%",
        "tec_setpoint": "°C", "tec_setpoint_c": "°C",
        "n_frames": "",
    }

    def _make_card(self, icon: str, icon_color: str,
                   title: str, detail: str,
                   fix_dict: dict | None = None) -> QFrame:
        """Build a compact issue/suggestion card.

        Parameters
        ----------
        fix_dict : dict | None
            If provided and the param is in _SAFE_PARAMS, a quick-apply
            button is shown on the card.
        """
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:4px; }}")

        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(8, 6, 8, 6)
        card_lay.setSpacing(8)

        icon_w = QLabel(icon)
        icon_w.setFixedWidth(20)
        icon_w.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        icon_w.setStyleSheet(
            f"color:{icon_color}; font-size:{FONT['label']}pt; "
            f"background:transparent; border:none;")
        card_lay.addWidget(icon_w)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_w = QLabel(title)
        title_w.setWordWrap(True)
        title_w.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['text']}; "
            f"background:transparent; border:none;")
        text_col.addWidget(title_w)

        if detail:
            detail_w = QLabel(detail)
            detail_w.setWordWrap(True)
            detail_w.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textSub']}; "
                f"font-family:{MONO_FONT}; background:transparent; border:none;")
            text_col.addWidget(detail_w)

        card_lay.addLayout(text_col, 1)

        # Quick-apply button for safe, reversible parameter changes
        if (fix_dict and fix_dict.get("param") in self._SAFE_PARAMS
                and fix_dict.get("value") is not None):
            param = fix_dict["param"]
            value = fix_dict["value"]
            unit  = fix_dict.get("unit") or self._PARAM_UNITS.get(param, "")
            apply_btn = QPushButton(f"Apply {value}{' ' + unit if unit else ''}")
            apply_btn.setCursor(QCursor(Qt.PointingHandCursor))
            apply_btn.setFixedHeight(24)
            apply_btn.setMaximumWidth(140)
            apply_btn.setStyleSheet(
                f"QPushButton {{ background:{PALETTE['surface2']}; "
                f"color:{PALETTE['accent']}; "
                f"border:1px solid {PALETTE['accent']}44; border-radius:3px; "
                f"font-size:{FONT['caption']}pt; padding:2px 8px; }}"
                f"QPushButton:hover {{ background:{PALETTE['accent']}18; "
                f"border-color:{PALETTE['accent']}88; }}"
                f"QPushButton:pressed {{ background:{PALETTE['accent']}30; }}")
            apply_btn.setToolTip(
                f"Apply this single change now: {param} → {value} {unit}")
            _fix = dict(fix_dict)  # capture for lambda
            apply_btn.clicked.connect(
                lambda checked, f=_fix, b=apply_btn: self._on_quick_apply(f, b))
            card_lay.addWidget(apply_btn)

        return card

    def _on_quick_apply(self, fix: dict, btn: QPushButton) -> None:
        """Emit a single fix and visually confirm the button was clicked."""
        self.quick_fix.emit(fix)
        btn.setText("✓ Applied")
        btn.setEnabled(False)
        btn.setStyleSheet(
            f"QPushButton {{ background:{PALETTE['surface2']}; "
            f"color:{PALETTE['success']}; "
            f"border:1px solid {PALETTE['success']}44; border-radius:3px; "
            f"font-size:{FONT['caption']}pt; padding:2px 8px; }}")

    def _apply_styles(self):
        """Refresh inline stylesheets from the current PALETTE values."""
        bg   = PALETTE['bg']
        text = PALETTE['text']
        sub  = PALETTE['textSub']
        bdr  = PALETTE['border']
        sur2 = PALETTE['surface2']
        acc  = PALETTE['accent']
        self.setStyleSheet(f"QDialog {{ background:{bg}; color:{text}; }}")
        self._content.setStyleSheet(f"background:{bg};")
        self._thinking_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['systemIndigo']}; "
            f"font-family:{MONO_FONT};")
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background:{sur2}; color:{text}; "
            f"border:1px solid {bdr}; border-radius:5px; "
            f"font-size:{FONT['label']}pt; font-weight:600; padding:7px 20px; }}"
            f"QPushButton:hover {{ background:{PALETTE['danger']}18; "
            f"color:{PALETTE['danger']}; border-color:{PALETTE['danger']}66; }}")
        self._proceed_btn.setStyleSheet(
            f"QPushButton {{ background:{acc}; color:{PALETTE['textOnAccent']}; "
            f"border:none; border-radius:5px; "
            f"font-size:{FONT['label']}pt; font-weight:600; padding:7px 24px; }}"
            f"QPushButton:hover {{ background:{acc}dd; }}"
            f"QPushButton:disabled {{ background:{sur2}; color:{PALETTE['textDim']}; "
            f"border:1px solid {bdr}; }}")

    def _on_cancel(self) -> None:
        """Cancel inference if still thinking, then close."""
        if self._is_thinking:
            self.cancel_requested.emit()
        self.reject()

    def _on_proceed(self) -> None:
        """Emit fixes and close."""
        self.proceed_clicked.emit(self._fixes)
        self.accept()
