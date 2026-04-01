"""
ui/widgets/time_estimate_label.py — Indigo pill showing estimated duration

Replaces the faint gray ``QLabel`` time estimates scattered across tabs
with a visually distinct, PALETTE-aware pill.  Formula breakdowns are
shown in the tooltip so they never truncate.

Usage
-----
    from ui.widgets.time_estimate_label import TimeEstimateLabel

    self._time_est = TimeEstimateLabel()
    layout.addWidget(self._time_est)

    # When parameters change:
    self._time_est.set_estimate(
        seconds=805,
        tooltip_detail="7 steps × (35 s ramp + 60 s settle + 20 s capture)")

    # When there's nothing to show:
    self._time_est.clear()
"""
from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt


# ── Shared duration formatter ─────────────────────────────────────────────────
# Replaces the duplicated _fmt_duration() static methods in acquire_tab,
# autofocus_tab, scan_tab, and transient_tab.

def fmt_duration(seconds: float) -> str:
    """Zero-padded clock-style duration string, always ``HH:MM:SS``.

    Returns
    -------
    str
        ``"~00:00:05"`` for 5 s, ``"~00:09:35"`` for 9 min 35 s,
        ``"~01:13:00"`` for 1 h 13 min.
    """
    seconds = max(0, int(round(seconds)))
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"~{h:02d}:{m:02d}:{s:02d}"


# ── Widget ────────────────────────────────────────────────────────────────────

class TimeEstimateLabel(QFrame):
    """Indigo pill showing a clock icon and formatted duration.

    Uses QFrame (not QWidget) so that ``background`` and ``border-radius``
    from setStyleSheet are painted natively without needing
    WA_StyledBackground or a custom paintEvent.

    Hidden by default.  Call ``set_estimate(seconds)`` to populate and
    show; ``clear()`` to hide.  Tooltip carries the optional formula
    breakdown so the pill itself stays compact.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TimeEstimatePill")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(0)

        # Single label carries the stopwatch symbol + clock time
        self._text_lbl = QLabel()
        self._text_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._text_lbl)

        self.setVisible(False)
        self._apply_styles()

    # ── Public API ────────────────────────────────────────────────────

    def set_estimate(self, seconds: float,
                     tooltip_detail: str = "") -> None:
        """Format *seconds* as a human-readable duration and show the pill.

        Parameters
        ----------
        seconds:
            Estimated wall-clock duration in seconds.
        tooltip_detail:
            Optional formula breakdown shown on hover, e.g.
            ``"7 steps × (35 s ramp + 60 s settle + 20 s capture)"``.
        """
        dur = fmt_duration(seconds)
        self._text_lbl.setText(f"⏱ {dur}")
        tip = f"Estimated duration: {dur}"
        if tooltip_detail:
            tip += f"\n{tooltip_detail}"
        self.setToolTip(tip)
        self._apply_styles()
        self.setVisible(True)

    def text(self) -> str:
        """Return the current display text (delegates to the inner label)."""
        return self._text_lbl.text()

    def clear(self) -> None:
        """Hide the pill and reset its text."""
        self._text_lbl.clear()
        self.setToolTip("")
        self.setVisible(False)

    # ── Theme support ─────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Re-apply palette-derived styles (call after theme switch)."""
        from ui.theme import PALETTE, FONT
        color = PALETTE['systemIndigo']
        bg    = PALETTE['bg']
        self.setStyleSheet(
            f"QFrame#TimeEstimatePill {{ "
            f"background: {color}; border: none; "
            f"border-radius: 14px; }}")
        self._text_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {bg}; font-size: {FONT['body']}pt; font-weight: 700;")
