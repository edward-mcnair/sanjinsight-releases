"""
ui/widgets/measurement_strip.py

MeasurementReadoutStrip  —  compact horizontal strip showing live
BT / dT / CT acquisition readouts.

┌──────────────────────────────────────────────────┐
│ BT  29.4°C    DT  +1.24°C    CT  25.0°C         │
└──────────────────────────────────────────────────┘

BT  — Base Temperature: TEC object temperature at the time of acquisition.
dT  — Delta Temperature: change from baseline (tec_actual − tec_setpoint, or
      vs cold reference).  Positive (heating) shown in a warm colour; negative
      (cooling) shown in a cool colour.
CT  — Chuck Temperature: TCAT fixture temperature.  Shown only when a chuck
      controller is configured; hidden otherwise.

Public API
----------
    strip = MeasurementReadoutStrip(parent)
    strip.set_values(bt_c=29.4, dt_c=+1.24, ct_c=25.0)   # ct_c=None hides CT cell
    strip.set_values(bt_c=None, dt_c=None)                  # shows N/A
    strip._apply_styles()                                    # called on theme change

Height is fixed at 36 px.  All text is painted directly in ``paintEvent`` —
there are **no QLabel child widgets** — which eliminates the Qt/macOS Cocoa
stylesheet grey-box artefact that appears whenever ``QLabel.setStyleSheet()``
is applied on macOS.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore    import Qt, QRect
from PyQt5.QtGui     import QPainter, QColor, QFont, QFontMetrics

from ui.theme import FONT, PALETTE, _DPI_SCALE

# ── Colour constants ─────────────────────────────────────────────────────────
_DT_POS_COLOR = "#f5a623"   # amber/warm — heating; also used for BT label
_DT_NEG_COLOR = "#5ac8fa"   # sky blue — cooling

# ── Layout constants (logical pixels, DPI-scaled) ─────────────────────────────
def _s(px: int) -> int:
    """Scale a logical-pixel constant by the platform DPI factor."""
    return max(1, int(round(px * _DPI_SCALE)))

_STRIP_HEIGHT = _s(36)
_MARGIN       = _s(12)   # left / right padding
_SUB_GAP      = _s( 5)   # gap between sublabel ("BT") and its value ("25.0 °C")
_CELL_GAP     = _s(14)   # gap from end of value to divider (and divider to next sublabel)
_DIV_H_INSET  = _s( 6)   # vertical inset for divider line


class MeasurementReadoutStrip(QWidget):
    """
    Compact 36 px horizontal strip showing BT / dT / CT readouts.

    All text is rendered directly via ``QPainter.drawText`` — there are no
    ``QLabel`` child widgets.  This eliminates the macOS Cocoa system-background
    paint that Qt applies beneath any ``QLabel`` that has ``setStyleSheet()``
    called on it, producing grey boxes regardless of ``background: transparent``
    or ``setAutoFillBackground(False)``.

    Parameters
    ----------
    parent : QWidget, optional
    show_ct : bool
        If False the CT cell is never shown regardless of the value passed
        to ``set_values()``.  Default True.
    """

    def __init__(self, parent: QWidget | None = None, show_ct: bool = True):
        super().__init__(parent)
        self._show_ct = show_ct
        self.setFixedHeight(_STRIP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # ── Readout state — written by set_values(), read by paintEvent ───
        self._bt_text  : str  = "N/A"
        self._bt_color : str  = PALETTE.get("textSub", "#9696a8")
        self._dt_text  : str  = "N/A"
        self._dt_color : str  = PALETTE.get("textSub", "#9696a8")
        self._ct_text  : str  = ""
        self._ct_vis   : bool = False

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def set_values(self,
                   bt_c: Optional[float],
                   dt_c: Optional[float],
                   ct_c: Optional[float] = None) -> None:
        """
        Refresh all readout cells and schedule a repaint.

        Named ``set_values`` (not ``update``) to avoid shadowing
        ``QWidget.update()``, which Qt calls internally with zero args to
        schedule a repaint — overriding it causes ``TypeError`` on every
        internal repaint.

        Parameters
        ----------
        bt_c : float or None
            Base Temperature in °C.  None → "N/A".
        dt_c : float or None
            Delta Temperature in °C.  None → "N/A".
            Positive values (heating) shown in amber; negative (cooling) in blue.
        ct_c : float or None
            Chuck Temperature in °C.  None → CT cell hidden.
        """
        # BT — label and value share amber so they read as one warm unit.
        if bt_c is None:
            self._bt_text  = "N/A"
            self._bt_color = PALETTE.get("textSub", "#9696a8")
        else:
            self._bt_text  = f"{bt_c:.1f} °C"
            self._bt_color = _DT_POS_COLOR

        # dT
        if dt_c is None:
            self._dt_text  = "N/A"
            self._dt_color = PALETTE.get("textSub", "#9696a8")
        elif dt_c > 0.005:
            self._dt_text  = f"+{dt_c:.2f}°C"
            self._dt_color = _DT_POS_COLOR
        elif dt_c < -0.005:
            self._dt_text  = f"{dt_c:.2f}°C"
            self._dt_color = _DT_NEG_COLOR
        else:
            # Effectively zero — show as "±0.00°C" in neutral colour
            self._dt_text  = f"±{abs(dt_c):.2f}°C"
            self._dt_color = PALETTE.get("textSub", "#9696a8")

        # CT
        self._ct_vis = self._show_ct and ct_c is not None
        if self._ct_vis:
            self._ct_text = f"{ct_c:.1f}°C"

        self.update()

    def _apply_styles(self) -> None:
        """Called on theme change; PALETTE is read live in paintEvent."""
        self.update()

    # ---------------------------------------------------------------- #
    #  Paint                                                            #
    # ---------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802
        """
        Render the strip background and all cell text directly.

        Drawing directly with QPainter (rather than relying on child QLabel
        widgets + stylesheets) gives us complete control over what appears on
        screen and bypasses the macOS Cocoa layer that paints an opaque system
        background behind styled QLabels.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)

        h = self.height()
        w = self.width()

        # ── PALETTE colours (read live → theme changes are instant) ───────
        bg   = QColor(PALETTE.get("surface",  "#1c1c1e"))
        bdr  = QColor(PALETTE.get("border",   "#3a3a3a"))
        dim  = QColor(PALETTE.get("textDim",  "#9696a8"))
        text = QColor(PALETTE.get("text",     "#ffffff"))

        # ── Fonts ─────────────────────────────────────────────────────────
        # BT sublabel — bold, amber (matches its value so the pair reads
        # as a single warm readout unit).
        bt_sub_font = QFont()
        bt_sub_font.setPointSize(FONT["caption"])
        bt_sub_font.setBold(True)

        # DT / CT sublabels — normal weight, dimmed.
        dt_sub_font = QFont()
        dt_sub_font.setPointSize(FONT["caption"])
        dt_sub_font.setBold(False)

        # Value text — monospace for stable column width as digits change.
        val_font = QFont("Menlo")
        val_font.setStyleHint(QFont.Monospace)
        val_font.setPointSize(FONT["body"])

        # ── Fill background ────────────────────────────────────────────────
        p.fillRect(0, 0, w, h, bg)

        # ── Drawing cursor ─────────────────────────────────────────────────
        x = _MARGIN

        def sub_w(txt: str, font: QFont) -> int:
            return QFontMetrics(font).horizontalAdvance(txt)

        def val_w(txt: str) -> int:
            return QFontMetrics(val_font).horizontalAdvance(txt)

        def draw_sub(txt: str, font: QFont, color: QColor) -> None:
            p.setFont(font)
            p.setPen(color)
            p.drawText(QRect(x, 0, sub_w(txt, font), h),
                       Qt.AlignVCenter | Qt.AlignLeft, txt)

        def draw_val(txt: str, color: QColor) -> None:
            p.setFont(val_font)
            p.setPen(color)
            p.drawText(QRect(x, 0, val_w(txt), h),
                       Qt.AlignVCenter | Qt.AlignLeft, txt)

        def draw_div() -> None:
            p.setPen(bdr)
            p.drawLine(x, _DIV_H_INSET, x, h - _DIV_H_INSET)

        # ── BT cell ────────────────────────────────────────────────────────
        draw_sub("BT", bt_sub_font, QColor(_DT_POS_COLOR))
        x += sub_w("BT", bt_sub_font) + _SUB_GAP

        draw_val(self._bt_text, QColor(self._bt_color))
        x += val_w(self._bt_text) + _CELL_GAP

        # ── Divider ────────────────────────────────────────────────────────
        draw_div()
        x += 1 + _CELL_GAP

        # ── dT cell ────────────────────────────────────────────────────────
        draw_sub("DT", dt_sub_font, dim)
        x += sub_w("DT", dt_sub_font) + _SUB_GAP

        draw_val(self._dt_text, QColor(self._dt_color))

        # ── CT cell (optional) ─────────────────────────────────────────────
        if self._ct_vis:
            x += val_w(self._dt_text) + _CELL_GAP
            draw_div()
            x += 1 + _CELL_GAP

            draw_sub("CT", dt_sub_font, dim)
            x += sub_w("CT", dt_sub_font) + _SUB_GAP

            draw_val(self._ct_text, text)
