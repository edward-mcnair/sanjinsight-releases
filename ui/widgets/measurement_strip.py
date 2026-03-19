"""
ui/widgets/measurement_strip.py

MeasurementReadoutStrip  —  compact horizontal strip showing live
BT / dT / CT acquisition readouts.

┌──────────────────────────────────────────────────┐
│ BT  29.4°C    dT  +1.24°C    CT  25.0°C         │
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
    strip.update(bt_c=29.4, dt_c=+1.24, ct_c=25.0)   # ct_c=None hides CT cell
    strip.update(bt_c=None, dt_c=None)                  # shows N/A
    strip._apply_styles()                                # called on theme change

Height is fixed at 36 px.  The strip is transparent by default so it sits
cleanly inside toolbars, status bars, or header widgets.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame, QSizePolicy
from PyQt5.QtCore    import Qt

from ui.theme import FONT, PALETTE

# ── Colour constants ─────────────────────────────────────────────────────────
# dT positive (heating) → warm orange-amber; dT negative (cooling) → sky blue.
# These are chosen to be legible on both dark and light backgrounds.
_DT_POS_COLOR  = "#f5a623"   # amber/warm — heating
_DT_NEG_COLOR  = "#5ac8fa"   # sky blue — cooling
_DT_ZERO_COLOR = None        # falls back to PALETTE["textSub"]

_STRIP_HEIGHT = 36


class MeasurementReadoutStrip(QWidget):
    """
    Compact 36 px horizontal strip showing BT / dT / CT readouts.

    Parameters
    ----------
    parent : QWidget, optional
    show_ct : bool
        If False the CT cell is never shown regardless of the value passed
        to update().  Default True (CT shown when ct_c is not None).
    """

    def __init__(self, parent: QWidget | None = None, show_ct: bool = True):
        super().__init__(parent)
        self._show_ct = show_ct
        self._setFixedHeight()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(10, 0, 10, 0)
        self._root.setSpacing(0)

        # ── BT cell ───────────────────────────────────────────────────
        self._bt_sub, self._bt_val = self._make_cell("BT")
        self._root.addWidget(self._bt_sub)
        self._root.addSpacing(4)
        self._root.addWidget(self._bt_val)

        # ── Divider ───────────────────────────────────────────────────
        self._root.addWidget(self._make_divider())

        # ── dT cell ───────────────────────────────────────────────────
        self._dt_sub, self._dt_val = self._make_cell("dT")
        self._root.addWidget(self._dt_sub)
        self._root.addSpacing(4)
        self._root.addWidget(self._dt_val)

        # ── CT cell (optional) ────────────────────────────────────────
        self._ct_divider = self._make_divider()
        self._ct_sub, self._ct_val = self._make_cell("CT")
        self._root.addWidget(self._ct_divider)
        self._root.addWidget(self._ct_sub)
        self._root.addSpacing(4)
        self._root.addWidget(self._ct_val)

        # Initially hide CT
        self._ct_divider.setVisible(False)
        self._ct_sub.setVisible(False)
        self._ct_val.setVisible(False)

        self._root.addStretch()

        self._apply_styles()

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def update(self,
               bt_c: Optional[float],
               dt_c: Optional[float],
               ct_c: Optional[float] = None) -> None:
        """
        Refresh all readout cells.

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
        # ── BT ───────────────────────────────────────────────────────
        if bt_c is None:
            self._bt_val.setText("N/A")
            self._bt_val.setStyleSheet(self._val_style("textSub"))
        else:
            self._bt_val.setText(f"{bt_c:.1f}°C")
            self._bt_val.setStyleSheet(self._val_style("text"))

        # ── dT ───────────────────────────────────────────────────────
        if dt_c is None:
            self._dt_val.setText("N/A")
            self._dt_val.setStyleSheet(self._val_style("textSub"))
        elif dt_c > 0.005:
            self._dt_val.setText(f"+{dt_c:.2f}°C")
            self._dt_val.setStyleSheet(
                self._val_style_raw(_DT_POS_COLOR))
        elif dt_c < -0.005:
            self._dt_val.setText(f"{dt_c:.2f}°C")
            self._dt_val.setStyleSheet(
                self._val_style_raw(_DT_NEG_COLOR))
        else:
            # Effectively zero — show as "±0.00°C" in neutral colour
            self._dt_val.setText(f"±{abs(dt_c):.2f}°C")
            self._dt_val.setStyleSheet(self._val_style("textSub"))

        # ── CT ───────────────────────────────────────────────────────
        show_ct = self._show_ct and ct_c is not None
        self._ct_divider.setVisible(show_ct)
        self._ct_sub.setVisible(show_ct)
        self._ct_val.setVisible(show_ct)
        if show_ct:
            self._ct_val.setText(f"{ct_c:.1f}°C")
            self._ct_val.setStyleSheet(self._val_style("text"))

    # ---------------------------------------------------------------- #
    #  Theme                                                            #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        """Re-apply PALETTE-sourced styles.  Called on theme change."""
        bg    = PALETTE.get("surface",  "#1c1c1e")
        bdr   = PALETTE.get("border",   "#3a3a3a")
        _dim  = PALETTE.get("textDim",  "#666666")
        _sub  = PALETTE.get("textSub",  "#9a9a9a")
        _text = PALETTE.get("text",     "#ffffff")

        self.setStyleSheet(
            f"MeasurementReadoutStrip {{"
            f"  background:{bg};"
            f"  border-top:1px solid {bdr};"
            f"  border-bottom:1px solid {bdr};"
            f"}}"
        )

        # Sub-labels
        sub_style = (
            f"color:{_dim}; "
            f"font-size:{FONT['caption']}pt; "
            f"letter-spacing:0.5px;"
        )
        for sub in (self._bt_sub, self._dt_sub, self._ct_sub):
            sub.setStyleSheet(sub_style)

        # Value labels — reset to neutral; update() will tint dT
        val_style = (
            f"font-family:Menlo,monospace; "
            f"font-size:{FONT['body']}pt; "
            f"color:{_text};"
        )
        for val in (self._bt_val, self._dt_val, self._ct_val):
            val.setStyleSheet(val_style)

        # Dividers
        div_style = f"background:{bdr};"
        for div in (self._ct_divider,):
            div.setStyleSheet(div_style)
        # The inline dividers are QFrames; style them directly
        for child in self.findChildren(QFrame):
            child.setStyleSheet(f"background:{bdr};")

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _setFixedHeight(self) -> None:
        self.setFixedHeight(_STRIP_HEIGHT)

    def _make_cell(self, label: str) -> tuple[QLabel, QLabel]:
        """Return (sub_label, value_label) for one readout cell."""
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        sub.setContentsMargins(8, 0, 0, 0)

        val = QLabel("N/A")
        val.setObjectName("readout_val")
        val.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        val.setMinimumWidth(64)

        return sub, val

    def _make_divider(self) -> QFrame:
        """Thin vertical separator between cells."""
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setFixedWidth(1)
        div.setContentsMargins(8, 6, 8, 6)
        _bdr = PALETTE.get("border", "#3a3a3a")
        div.setStyleSheet(f"background:{_bdr};")
        return div

    def _val_style(self, pal_key: str) -> str:
        color = PALETTE.get(pal_key, "#ffffff")
        return self._val_style_raw(color)

    def _val_style_raw(self, color: str) -> str:
        return (
            f"font-family:Menlo,monospace; "
            f"font-size:{FONT['body']}pt; "
            f"color:{color};"
        )
