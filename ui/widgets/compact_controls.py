"""
ui/widgets/compact_controls.py

Compact, embeddable hardware control widgets designed to appear in
multiple tabs (Acquire, Live View, Modality, etc.) without forcing
the user to navigate away.

Each widget is self-contained: it reads status from ``app_signals``
and sends commands via ``app_state``.
"""

from __future__ import annotations

import logging
from functools import partial

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSlider, QComboBox, QFrame, QSizePolicy,
    QGridLayout, QScrollArea)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.icons import set_btn_icon

log = logging.getLogger(__name__)


def _readout(initial: str = "--") -> QLabel:
    lbl = QLabel(initial)
    lbl.setStyleSheet(scaled_qss(
        f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl


def _caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(scaled_qss(
        f"font-size:8pt; color:{PALETTE['textDim']}; font-weight:bold;"))
    return lbl


# ────────────────────────────────────────────────────────────────────
#  TEC Quick Control
# ────────────────────────────────────────────────────────────────────

class TecQuickControl(QWidget):
    """Compact TEC control: setpoint spinbox, quick-temp buttons, readout."""

    def __init__(self, tec_index: int = 0, parent=None):
        super().__init__(parent)
        self._idx = tec_index

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        root.addWidget(_caption("TEC"))

        self._spin = QDoubleSpinBox()
        self._spin.setRange(-40, 150)
        self._spin.setValue(25.0)
        self._spin.setSuffix(" \u00b0C")
        self._spin.setDecimals(1)
        self._spin.setMinimumWidth(85)
        self._spin.setFixedHeight(26)
        root.addWidget(self._spin)

        self._set_btn = QPushButton("Set")
        self._set_btn.setMinimumWidth(42)
        self._set_btn.setFixedHeight(26)
        self._set_btn.clicked.connect(self._set_target)
        root.addWidget(self._set_btn)

        for temp in (25, 50, 85):
            b = QPushButton(f"{temp}")
            b.setMinimumWidth(34)
            b.setFixedHeight(26)
            b.clicked.connect(partial(self._quick_set, float(temp)))
            root.addWidget(b)

        self._temp_lbl = _readout("-- \u00b0C")
        self._temp_lbl.setMinimumWidth(60)
        root.addWidget(self._temp_lbl)

        from ui.app_signals import signals
        signals.tec_status.connect(self._on_status)

    def _set_target(self):
        from hardware.app_state import app_state
        val = self._spin.value()
        try:
            tecs = app_state.tecs
            if tecs and self._idx < len(tecs):
                tecs[self._idx].set_target(val)
        except Exception as exc:
            log.debug("TEC set_target failed: %s", exc)

    def _quick_set(self, temp: float):
        self._spin.setValue(temp)
        self._set_target()

    def _on_status(self, idx, status):
        if idx != self._idx:
            return
        try:
            t = status.temperature
            self._temp_lbl.setText(f"{t:.1f} \u00b0C")
        except Exception:
            pass

    def _apply_styles(self):
        self._temp_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))


# ────────────────────────────────────────────────────────────────────
#  Exposure / Gain Quick Control
# ────────────────────────────────────────────────────────────────────

class ExposureGainControl(QWidget):
    """Compact exposure slider + gain slider + readouts."""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QGridLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(2)
        root.setColumnStretch(1, 1)   # slider column stretches

        # Exposure row
        root.addWidget(_caption("Exp"), 0, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(50, 200_000)
        self._exp_slider.setValue(1000)
        self._exp_slider.setMinimumWidth(80)
        self._exp_slider.setFixedHeight(20)
        self._exp_slider.sliderReleased.connect(self._on_exp)
        root.addWidget(self._exp_slider, 0, 1)
        self._exp_lbl = _readout("1.0 ms")
        self._exp_lbl.setMinimumWidth(60)
        root.addWidget(self._exp_lbl, 0, 2)

        # Gain row
        root.addWidget(_caption("Gain"), 1, 0)
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 239)
        self._gain_slider.setValue(0)
        self._gain_slider.setMinimumWidth(80)
        self._gain_slider.setFixedHeight(20)
        self._gain_slider.sliderReleased.connect(self._on_gain)
        root.addWidget(self._gain_slider, 1, 1)
        self._gain_lbl = _readout("0.0 dB")
        self._gain_lbl.setMinimumWidth(60)
        root.addWidget(self._gain_lbl, 1, 2)

        # Live label updates
        self._exp_slider.valueChanged.connect(self._update_exp_label)
        self._gain_slider.valueChanged.connect(self._update_gain_label)

    def _update_exp_label(self, val):
        if val >= 1000:
            self._exp_lbl.setText(f"{val / 1000:.1f} ms")
        else:
            self._exp_lbl.setText(f"{val} \u00b5s")

    def _update_gain_label(self, val):
        self._gain_lbl.setText(f"{val / 10:.1f} dB")

    def _on_exp(self):
        from hardware.app_state import app_state
        val = self._exp_slider.value()
        try:
            cam = app_state.camera
            if cam:
                cam.set_exposure(float(val))
        except Exception as exc:
            log.debug("Exposure set failed: %s", exc)

    def _on_gain(self):
        from hardware.app_state import app_state
        val = self._gain_slider.value()
        try:
            cam = app_state.camera
            if cam:
                cam.set_gain(val / 10.0)
        except Exception as exc:
            log.debug("Gain set failed: %s", exc)

    def set_exposure(self, us: float):
        self._exp_slider.blockSignals(True)
        self._exp_slider.setValue(int(us))
        self._exp_slider.blockSignals(False)
        self._update_exp_label(int(us))

    def set_gain(self, db: float):
        self._gain_slider.blockSignals(True)
        self._gain_slider.setValue(int(db * 10))
        self._gain_slider.blockSignals(False)
        self._update_gain_label(int(db * 10))

    def _apply_styles(self):
        self._exp_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))
        self._gain_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))


# ────────────────────────────────────────────────────────────────────
#  Stimulus Quick Toggle
# ────────────────────────────────────────────────────────────────────

class StimulusToggle(QWidget):
    """Compact stimulus ON/OFF toggle with frequency readout."""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        root.addWidget(_caption("Stim"))

        self._on_btn = QPushButton("ON")
        self._on_btn.setMinimumWidth(38)
        self._on_btn.setFixedHeight(26)
        self._on_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{ background:{PALETTE['accent']}33; "
            f"color:{PALETTE['accent']}; font-size:9pt; "
            f"border:1px solid {PALETTE['accent']}; border-radius:3px; "
            f"padding:2px 6px; }}"))
        self._on_btn.clicked.connect(lambda: self._toggle(True))
        root.addWidget(self._on_btn)

        self._off_btn = QPushButton("OFF")
        self._off_btn.setMinimumWidth(38)
        self._off_btn.setFixedHeight(26)
        self._off_btn.clicked.connect(lambda: self._toggle(False))
        root.addWidget(self._off_btn)

        self._freq_lbl = _readout("--")
        self._freq_lbl.setMinimumWidth(60)
        root.addWidget(self._freq_lbl)

        from ui.app_signals import signals
        signals.fpga_status.connect(self._on_fpga)

    def _toggle(self, on: bool):
        from hardware.app_state import app_state
        try:
            fpga = app_state.fpga
            if fpga:
                if on:
                    fpga.start()
                else:
                    fpga.stop()
        except Exception as exc:
            log.debug("Stimulus toggle failed: %s", exc)

    def _on_fpga(self, status):
        try:
            freq = status.frequency
            if freq >= 1000:
                self._freq_lbl.setText(f"{freq / 1000:.1f} kHz")
            else:
                self._freq_lbl.setText(f"{freq:.0f} Hz")
        except Exception:
            pass

    def _apply_styles(self):
        self._on_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{ background:{PALETTE['accent']}33; "
            f"color:{PALETTE['accent']}; font-size:9pt; "
            f"border:1px solid {PALETTE['accent']}; border-radius:3px; "
            f"padding:2px 6px; }}"))
        self._freq_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))


# ────────────────────────────────────────────────────────────────────
#  Stage Jog Pad (compact)
# ────────────────────────────────────────────────────────────────────

class StageJogPad(QWidget):
    """Compact XY jog pad with arrow buttons and step-size selector."""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Left column: label + step + position
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(_caption("Stage"))
        self._step_combo = QComboBox()
        self._step_combo.setMinimumWidth(78)
        self._step_combo.setFixedHeight(24)
        for label, val in [("1 \u00b5m", 1.0), ("10 \u00b5m", 10.0),
                           ("100 \u00b5m", 100.0), ("1 mm", 1000.0)]:
            self._step_combo.addItem(label, val)
        self._step_combo.setCurrentIndex(1)
        left.addWidget(self._step_combo)
        self._pos_lbl = _readout("-- , --")
        self._pos_lbl.setMinimumWidth(75)
        left.addWidget(self._pos_lbl)
        root.addLayout(left)

        # Right: 3x3 arrow grid
        grid = QGridLayout()
        grid.setSpacing(2)
        arrows = [
            (0, 1, "\u25b2", ( 0,  1)),
            (2, 1, "\u25bc", ( 0, -1)),
            (1, 0, "\u25c0", (-1,  0)),
            (1, 2, "\u25b6", ( 1,  0)),
        ]
        for row, col, sym, (dx, dy) in arrows:
            b = QPushButton(sym)
            b.setFixedSize(28, 28)
            b.clicked.connect(partial(self._jog, dx, dy))
            grid.addWidget(b, row, col)
        root.addLayout(grid)

        from ui.app_signals import signals
        signals.stage_status.connect(self._on_status)

    def _step(self) -> float:
        return self._step_combo.currentData() or 10.0

    def _jog(self, dx: int, dy: int):
        from hardware.app_state import app_state
        step = self._step()
        try:
            stage = app_state.stage
            if stage:
                stage.move_by(x=dx * step, y=dy * step, wait=False)
        except Exception as exc:
            log.debug("Stage jog failed: %s", exc)

    def _on_status(self, status):
        try:
            x = status.x
            y = status.y
            self._pos_lbl.setText(f"{x:.0f},{y:.0f}")
        except Exception:
            pass

    def _apply_styles(self):
        self._pos_lbl.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:9pt; color:{PALETTE['accent']};"))


# ────────────────────────────────────────────────────────────────────
#  Combined quick-controls bar (two-row layout)
# ────────────────────────────────────────────────────────────────────

def _vline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setFixedWidth(1)
    f.setStyleSheet(f"background:{PALETTE['border']};")
    return f


class QuickControlsBar(QWidget):
    """
    Two-row compact bar: Row 1 = TEC + Stimulus, Row 2 = Exp/Gain + Stage.
    Fits comfortably in a narrow panel without overflow.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(scaled_qss(
            f"QuickControlsBar {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:4px; }}"))

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(0)

        # Row 1: TEC + Stimulus
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.tec = TecQuickControl()
        self.stimulus = StimulusToggle()
        row1.addWidget(self.tec, 1)
        row1.addWidget(_vline())
        row1.addWidget(self.stimulus)
        root.addLayout(row1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{PALETTE['border']};")
        root.addWidget(sep)

        # Row 2: Exposure/Gain + Stage
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.exposure = ExposureGainControl()
        self.stage_jog = StageJogPad()
        row2.addWidget(self.exposure, 1)
        row2.addWidget(_vline())
        row2.addWidget(self.stage_jog)
        root.addLayout(row2)

    def _apply_styles(self):
        self.setStyleSheet(scaled_qss(
            f"QuickControlsBar {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:4px; }}"))
        self.tec._apply_styles()
        self.exposure._apply_styles()
        self.stimulus._apply_styles()
        self.stage_jog._apply_styles()
