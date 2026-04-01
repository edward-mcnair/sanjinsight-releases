"""
ui/operator/verdict_overlay.py

VerdictOverlay — full-screen modal shown immediately after each scan
in the Operator Shell.

The overlay shows an unambiguous PASS / FAIL / REVIEW verdict with
key metrics, then lets the operator move on to the next part, flag
the result for engineering review, or open the full detail view.

Layout  (full-screen semi-transparent background + centred card)
------
  Background: PALETTE success / danger / warning at 15 % opacity
  Centre card  600 × 480 px:

    ✓ PASS                (72 pt bold, white)   — or ✗ FAIL / ⚠ REVIEW
    Part: SN-A12346
    ──────────────────────────────────────────
    Max hotspot:   4.2 °C    (limit: 20 °C)
    Hotspots:      0          Scan time: 8.3 s
    ──────────────────────────────────────────
    [ Flag for Review ]          [ ▶ Next Part ]
                [ View Details ]

Signals
-------
  next_part()              Operator clicks "Next Part" / presses Space / Enter
  flagged(part_id: str)    Operator clicks "Flag for Review"
  view_details()           Operator clicks "View Details"

Construction
------------
  overlay = VerdictOverlay(
      result    = analysis_result,   # AnalysisResult from ThermalAnalysisEngine
      part_id   = "SN-A12346",
      recipe    = recipe,            # Recipe — for fail_peak_k limit display
      scan_time_s = 8.3,
      parent    = operator_shell,
  )
  overlay.next_part.connect(...)
  overlay.exec_()
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy,
)
from PyQt5.QtGui import QColor, QPalette

from ui.theme import FONT, PALETTE

log = logging.getLogger(__name__)

# ── Verdict visual config ─────────────────────────────────────────────────────

_VERDICT_CFG = {
    "PASS":    {"glyph": "✓", "label": "PASS",   "key": "success"},
    "FAIL":    {"glyph": "✗", "label": "FAIL",   "key": "danger"},
    "WARNING": {"glyph": "⚠", "label": "REVIEW", "key": "warning"},
}
_DEFAULT_CFG = {"glyph": "?", "label": "UNKNOWN", "key": "info"}


# Module-level constants removed — use PALETTE directly.


def _hex_at_opacity(hex_color: str, opacity: float) -> str:
    """Return a CSS rgba() string for *hex_color* at *opacity* (0.0–1.0)."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{opacity:.2f})"


class VerdictOverlay(QDialog):
    """
    Full-screen post-scan verdict overlay.

    Parameters
    ----------
    result      : AnalysisResult
    part_id     : str           Serial number / barcode of the scanned part
    recipe      : Recipe        Used for fail_peak_k limit in the metrics row
    scan_time_s : float         Wall-clock duration of the scan
    parent      : QWidget
    """

    next_part   = pyqtSignal()
    flagged     = pyqtSignal(str)   # part_id
    view_details = pyqtSignal()

    def __init__(
        self,
        result,
        part_id:    str,
        recipe,
        scan_time_s: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)
        self._result      = result
        self._part_id     = part_id
        self._recipe      = recipe
        self._scan_time_s = scan_time_s

        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Fill the parent window
        if parent is not None:
            self.resize(parent.size())

        verdict     = getattr(result, "verdict", "UNKNOWN")
        cfg         = _VERDICT_CFG.get(verdict, _DEFAULT_CFG)
        accent_hex  = PALETTE[cfg["key"]]
        bg_rgba     = _hex_at_opacity(accent_hex, 0.12)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Semi-transparent full-screen background ────────────────────────
        bg_frame = QFrame()
        bg_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bg_frame.setStyleSheet(f"QFrame {{ background:{bg_rgba}; border:none; }}")
        bg_lay = QVBoxLayout(bg_frame)
        bg_lay.setContentsMargins(0, 0, 0, 0)
        bg_lay.addStretch(1)

        # ── Centre card ────────────────────────────────────────────────────
        card_row = QHBoxLayout()
        card_row.addStretch(1)

        card = QFrame()
        card.setFixedSize(620, 480)
        card.setStyleSheet(
            f"QFrame {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:16px; }}")

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(52, 44, 52, 40)
        card_lay.setSpacing(0)

        # ── Glyph + verdict label ──────────────────────────────────────────
        glyph_lbl = QLabel(f"{cfg['glyph']}  {cfg['label']}")
        glyph_lbl.setAlignment(Qt.AlignCenter)
        glyph_lbl.setStyleSheet(
            f"font-size:64pt; font-weight:800; color:{accent_hex}; "
            "background:transparent;")
        card_lay.addWidget(glyph_lbl)
        card_lay.addSpacing(12)

        # ── Part ID ────────────────────────────────────────────────────────
        part_lbl = QLabel(f"Part:  {part_id}")
        part_lbl.setAlignment(Qt.AlignCenter)
        part_lbl.setStyleSheet(
            f"font-size:{FONT['h3']}pt; color:{PALETTE['textDim']}; "
            "background:transparent;")
        card_lay.addWidget(part_lbl)
        card_lay.addSpacing(24)

        # ── Divider ────────────────────────────────────────────────────────
        card_lay.addWidget(self._hline())
        card_lay.addSpacing(16)

        # ── Metrics grid ───────────────────────────────────────────────────
        max_peak  = getattr(result, "max_peak_k",  0.0)
        n_hot     = getattr(result, "n_hotspots",  0)
        fail_limit = getattr(
            getattr(recipe, "analysis", None), "fail_peak_k", None)

        metrics_lay = QHBoxLayout()
        metrics_lay.setSpacing(32)

        # Column 1
        col1 = QVBoxLayout()
        col1.setSpacing(6)
        col1.addWidget(self._metric_row(
            "Max hotspot",
            f"{max_peak:.1f} °C",
            f"(limit: {fail_limit:.1f} °C)" if fail_limit is not None else "",
            accent_hex,
        ))
        col1.addWidget(self._metric_row(
            "Hotspots detected",
            str(n_hot),
            "",
            accent_hex,
        ))
        metrics_lay.addLayout(col1)

        # Vertical separator
        vsep = QFrame()
        vsep.setFrameShape(QFrame.VLine)
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(f"color:{PALETTE['border']};")
        metrics_lay.addWidget(vsep)

        # Column 2
        col2 = QVBoxLayout()
        col2.setSpacing(6)
        col2.addWidget(self._metric_row(
            "Scan time",
            f"{scan_time_s:.1f} s",
            "",
            accent_hex,
        ))
        recipe_label = getattr(recipe, "label", "")
        col2.addWidget(self._metric_row(
            "Scan Profile",
            recipe_label or "—",
            "",
            accent_hex,
        ))
        metrics_lay.addLayout(col2)

        card_lay.addLayout(metrics_lay)
        card_lay.addSpacing(16)
        card_lay.addWidget(self._hline())
        card_lay.addSpacing(24)

        # ── Action buttons ────────────────────────────────────────────────
        btn_top = QHBoxLayout()
        btn_top.setSpacing(12)

        self._flag_btn = QPushButton("Flag for Review")
        self._flag_btn.setFixedHeight(40)
        self._flag_btn.setStyleSheet(self._btn_secondary_qss())

        self._next_btn = QPushButton("▶  Next Part")
        self._next_btn.setFixedHeight(40)
        self._next_btn.setStyleSheet(self._btn_primary_qss(accent_hex))

        btn_top.addWidget(self._flag_btn)
        btn_top.addWidget(self._next_btn)
        card_lay.addLayout(btn_top)

        card_lay.addSpacing(10)

        self._details_btn = QPushButton("View Details")
        self._details_btn.setFixedHeight(34)
        self._details_btn.setStyleSheet(self._btn_text_qss())
        card_lay.addWidget(self._details_btn, 0, Qt.AlignCenter)

        card_row.addWidget(card)
        card_row.addStretch(1)

        bg_lay.addLayout(card_row)
        bg_lay.addStretch(1)
        root.addWidget(bg_frame)

        # ── Wire signals ───────────────────────────────────────────────────
        self._next_btn.clicked.connect(self._on_next)
        self._flag_btn.clicked.connect(self._on_flag)
        self._details_btn.clicked.connect(self._on_details)

    # ── Button helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _btn_primary_qss(color: str) -> str:
        return (
            f"QPushButton {{ background:{color}22; color:{color}; "
            f"border:1px solid {color}; border-radius:6px; "
            f"font-size:{FONT['body']}pt; font-weight:700; "
            "padding:0 20px; }"
            f"QPushButton:hover {{ background:{color}44; }}"
            f"QPushButton:pressed {{ background:{color}66; }}"
        )

    @staticmethod
    def _btn_secondary_qss() -> str:
        P = PALETTE
        return (
            f"QPushButton {{ background:{P['surface2']}; "
            f"color:{P['textDim']}; "
            f"border:1px solid {P['border']}; border-radius:6px; "
            f"font-size:{FONT['body']}pt; padding:0 20px; }}"
            f"QPushButton:hover {{ background:{P['surfaceHover']}; "
            f"color:{P['text']}; }}"
        )

    @staticmethod
    def _btn_text_qss() -> str:
        P = PALETTE
        return (
            f"QPushButton {{ background:transparent; "
            f"color:{P['textDim']}; border:none; "
            f"font-size:{FONT['sublabel']}pt; padding:0 12px; }}"
            f"QPushButton:hover {{ color:{P['text']}; "
            f"text-decoration:underline; }}"
        )

    @staticmethod
    def _hline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{PALETTE['border']};")
        return f

    @staticmethod
    def _metric_row(
        label: str, value: str, sub: str, accent: str
    ) -> QWidget:
        w = QFrame()
        w.setStyleSheet("QFrame { background:transparent; }")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textSub']}; "
            "background:transparent;")
        lay.addWidget(lbl)

        val_row = QHBoxLayout()
        val_row.setSpacing(8)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"font-size:{FONT['h3']}pt; font-weight:700; "
            f"color:{accent}; background:transparent;")
        val_row.addWidget(val_lbl)

        if sub:
            sub_lbl = QLabel(sub)
            sub_lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textSub']}; "
                "background:transparent;")
            val_row.addWidget(sub_lbl)

        val_row.addStretch(1)
        lay.addLayout(val_row)
        return w

    # ── Actions ────────────────────────────────────────────────────────────────

    def _on_next(self) -> None:
        self.next_part.emit()
        self.accept()

    def _on_flag(self) -> None:
        self.flagged.emit(self._part_id)
        self.accept()

    def _on_details(self) -> None:
        self.view_details.emit()
        self.accept()

    def keyPressEvent(self, event) -> None:
        """Space / Enter → Next Part."""
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._on_next()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        """Keep overlay filling the parent window on resize."""
        if self.parent() is not None:
            self.resize(self.parent().size())
        super().resizeEvent(event)
