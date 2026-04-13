"""
ui/widgets/hw_summary_strip.py  --  Compact hardware status strip

A thin single-row bar that shows the most important timing (FPGA/modulation)
and bias (source-measure) values inline on image-centric screens.  Designed
to keep hardware context visible without stealing vertical space from the
image/result surface.

Usage
-----
    strip = HwSummaryStrip()
    layout.addWidget(strip)
    # Wire to status signals:
    strip.update_timing(status)
    strip.update_bias(status)
Height: ~28 px.  Read-only -- no controls, no navigation side-effects.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT, MONO_FONT


# -- Formatting helpers --------------------------------------------------------

def _fmt_freq(hz: float) -> str:
    if hz <= 0:
        return "--"
    if hz >= 1_000_000:
        return f"{hz / 1_000_000:.1f} MHz"
    if hz >= 1_000:
        return f"{hz / 1_000:.1f} kHz"
    return f"{hz:.1f} Hz"


def _fmt_duty(pct: float) -> str:
    if pct <= 0:
        return "--"
    return f"{pct:.0f}%"


def _dot(ok: bool) -> str:
    """Small coloured dot for boolean indicators."""
    return "\u25cf" if ok else "\u25cb"   # ● / ○


# -- Widget --------------------------------------------------------------------

class HwSummaryStrip(QWidget):
    """Compact single-row hardware status bar (timing + bias).

    Shows key timing/bias values in a thin horizontal strip.  Read-only.
    Designed for embedding in image-centric screens (Live View, Capture).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self._build_ui()
        self._apply_styles()

    # ---- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(0)

        mono = f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt;"

        # -- Timing section --
        self._timing_icon = QLabel("\u26a1")  # ⚡
        self._timing_icon.setFixedWidth(16)
        self._timing_icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._timing_icon)

        self._timing_lbl = QLabel("Mod:")
        self._timing_lbl.setFixedWidth(32)
        lay.addWidget(self._timing_lbl)

        self._freq_val = QLabel("--")
        self._freq_val.setStyleSheet(mono)
        lay.addWidget(self._freq_val)

        lay.addWidget(self._sep())

        self._duty_val = QLabel("--")
        self._duty_val.setStyleSheet(mono)
        lay.addWidget(self._duty_val)

        lay.addWidget(self._sep())

        self._sync_val = QLabel("\u25cb Sync")
        self._sync_val.setStyleSheet(mono)
        lay.addWidget(self._sync_val)

        lay.addWidget(self._sep())

        self._stim_val = QLabel("Stim OFF")
        self._stim_val.setStyleSheet(mono)
        lay.addWidget(self._stim_val)

        # -- Divider --
        div = QLabel("\u2502")  # │
        div.setFixedWidth(20)
        div.setAlignment(Qt.AlignCenter)
        self._divider = div
        lay.addWidget(div)

        # -- Bias section --
        self._bias_icon = QLabel("\u26a1")  # ⚡
        self._bias_icon.setFixedWidth(16)
        self._bias_icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._bias_icon)

        self._bias_lbl = QLabel("Bias:")
        self._bias_lbl.setFixedWidth(34)
        lay.addWidget(self._bias_lbl)

        self._volt_val = QLabel("--")
        self._volt_val.setStyleSheet(mono)
        lay.addWidget(self._volt_val)

        lay.addWidget(self._sep())

        self._curr_val = QLabel("--")
        self._curr_val.setStyleSheet(mono)
        lay.addWidget(self._curr_val)

        lay.addWidget(self._sep())

        self._out_val = QLabel("OUT OFF")
        self._out_val.setStyleSheet(mono)
        lay.addWidget(self._out_val)

        lay.addStretch()

    def _sep(self) -> QLabel:
        """Thin dot separator between values."""
        s = QLabel(" \u00b7 ")  # · with spaces
        s.setFixedWidth(16)
        s.setAlignment(Qt.AlignCenter)
        return s

    # ---- public API ----------------------------------------------------------

    def update_timing(self, status) -> None:
        """Update timing section from an FPGA status object.

        Expected attributes: freq_hz, duty_cycle, sync_locked, stimulus_on,
        running, error.
        """
        if status is None:
            return
        err = getattr(status, "error", None)
        if err:
            self._freq_val.setText("ERR")
            self._duty_val.setText("--")
            self._sync_val.setText(f"{_dot(False)} Sync")
            self._stim_val.setText("Stim --")
            self._apply_color(self._freq_val, "danger")
            return

        running = getattr(status, "running", False)
        freq = getattr(status, "freq_hz", 0.0)
        duty = getattr(status, "duty_cycle", 0.0) * 100
        sync = getattr(status, "sync_locked", False)
        stim = getattr(status, "stimulus_on", False)

        self._freq_val.setText(_fmt_freq(freq) if running else "IDLE")
        self._duty_val.setText(_fmt_duty(duty) if running else "--")

        self._sync_val.setText(f"{_dot(sync)} Sync")
        self._apply_color(self._sync_val,
                          "success" if sync else "textDim")

        self._stim_val.setText(f"Stim {'ON' if stim else 'OFF'}")
        self._apply_color(self._stim_val,
                          "success" if stim else "textDim")

        self._apply_color(self._freq_val,
                          "accent" if running else "textDim")
        self._apply_color(self._duty_val,
                          "warning" if running else "textDim")

    def update_bias(self, status) -> None:
        """Update bias section from a bias status object.

        Expected attributes: actual_voltage, actual_current, output_on, error.
        """
        if status is None:
            return
        err = getattr(status, "error", None)
        if err:
            self._volt_val.setText("ERR")
            self._curr_val.setText("--")
            self._out_val.setText("OUT --")
            self._apply_color(self._volt_val, "danger")
            return

        on = getattr(status, "output_on", False)
        v = getattr(status, "actual_voltage", 0.0)
        i_ma = getattr(status, "actual_current", 0.0) * 1000

        self._volt_val.setText(f"{v:.3f} V" if on else "-- V")
        self._curr_val.setText(f"{i_ma:.2f} mA" if on else "-- mA")
        self._out_val.setText(f"OUT {'ON' if on else 'OFF'}")

        self._apply_color(self._volt_val,
                          "accent" if on else "textDim")
        self._apply_color(self._curr_val,
                          "warning" if on else "textDim")
        self._apply_color(self._out_val,
                          "success" if on else "textDim")

    # ---- styling -------------------------------------------------------------

    def _apply_color(self, lbl: QLabel, pal_key: str) -> None:
        """Set a label's text colour from a PALETTE key."""
        lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE[pal_key]};")

    def _apply_styles(self) -> None:
        """Re-apply palette colours (called on theme switch)."""
        P = PALETTE
        self.setStyleSheet(
            f"HwSummaryStrip {{ "
            f"  background: {P['surface']}; "
            f"  border-bottom: 1px solid {P['border']}; "
            f"}}")

        dim = (f"font-size:{FONT['caption']}pt; "
               f"color:{PALETTE['textDim']};")
        for lbl in (self._timing_lbl, self._bias_lbl,
                    self._timing_icon, self._bias_icon, self._divider):
            lbl.setStyleSheet(dim)

        # Reset value labels to dim (they'll be coloured on next update)
        mono_dim = (f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                    f"color:{P['textDim']};")
        for lbl in (self._freq_val, self._duty_val, self._sync_val,
                    self._stim_val, self._volt_val, self._curr_val,
                    self._out_val):
            lbl.setStyleSheet(mono_dim)
