"""
ui/tabs/acquisition_settings_section.py  —  Acquisition settings section

Frame count, exposure, gain, averaging mode, quality gating.
Phase 1 · CONFIGURATION
"""
from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QSlider, QPushButton, QSpinBox, QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.theme import PALETTE, FONT, MONO_FONT

log = logging.getLogger(__name__)


def _mono_style() -> str:
    return (f"font-family:{MONO_FONT}; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


def _fmt_exp(us: int) -> str:
    if us >= 1000:
        return f"{us / 1000:.1f} ms  ({us} μs)"
    return f"{us} μs"


class AcquisitionSettingsSection(QWidget):
    """Frame count, exposure, gain, averaging — Phase 1 CONFIGURATION."""

    settings_changed = pyqtSignal()

    def __init__(self, hw_service=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hw = hw_service

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("Acquisition Settings")
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            "font-weight:bold;")
        root.addWidget(title)

        # ── Grid ──────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(8)
        root.addLayout(grid)

        # Row 0: Frame count
        grid.addWidget(QLabel("Frames / phase"), 0, 0)
        self._frames_spin = QSpinBox()
        self._frames_spin.setRange(1, 10000)
        self._frames_spin.setValue(100)
        self._frames_spin.setSuffix("  frames")
        self._frames_spin.setFixedWidth(160)
        self._frames_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        grid.addWidget(self._frames_spin, 0, 1)

        # Frame presets
        presets = QHBoxLayout()
        for label, val in [("100", 100), ("500", 500), ("1000", 1000), ("5000", 5000)]:
            b = QPushButton(label)
            b.setMinimumWidth(60)
            b.clicked.connect(lambda _, v=val: self._frames_spin.setValue(v))
            presets.addWidget(b)
        presets.addStretch()
        grid.addLayout(presets, 1, 1)

        sub_frames = QLabel("more frames → better SNR, longer capture time")
        sub_frames.setStyleSheet(_dim_style())
        grid.addWidget(sub_frames, 2, 1, 1, 2)

        # Row 3: Exposure — TR only (IR cameras have fixed exposure)
        self._exp_label = QLabel("Exposure (μs)")
        grid.addWidget(self._exp_label, 3, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(50, 200000)
        self._exp_slider.setValue(5000)
        self._exp_lbl = QLabel(_fmt_exp(5000))
        self._exp_lbl.setStyleSheet(_mono_style())
        self._exp_slider.valueChanged.connect(
            lambda v: self._exp_lbl.setText(_fmt_exp(v)))
        self._exp_slider.sliderReleased.connect(self._on_exp)
        grid.addWidget(self._exp_slider, 3, 1)
        grid.addWidget(self._exp_lbl, 3, 2)

        self._exp_sub = QLabel("image brightness  ·  longer = brighter, risk of saturation")
        self._exp_sub.setStyleSheet(_dim_style())
        grid.addWidget(self._exp_sub, 4, 1, 1, 2)

        # Exposure presets
        self._exp_presets_w = QWidget()
        exp_pr = QHBoxLayout(self._exp_presets_w)
        exp_pr.setContentsMargins(0, 0, 0, 0)
        for label, v in [("50μs", 50), ("1ms", 1000), ("5ms", 5000),
                         ("20ms", 20000), ("100ms", 100000)]:
            b = QPushButton(label)
            b.setMinimumWidth(60)
            b.clicked.connect(lambda _, val=v: self._set_exp(val))
            exp_pr.addWidget(b)
        exp_pr.addStretch()
        grid.addWidget(self._exp_presets_w, 5, 1)

        self._tr_exposure_widgets = [
            self._exp_label, self._exp_slider, self._exp_lbl,
            self._exp_sub, self._exp_presets_w,
        ]

        # Row 6: Gain — TR: continuous dB slider; IR: High/Low combo
        self._gain_label_tr = QLabel("Gain (dB)")
        grid.addWidget(self._gain_label_tr, 6, 0)
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 239)
        self._gain_slider.setValue(0)
        self._gain_lbl = QLabel("0.0")
        self._gain_lbl.setStyleSheet(_mono_style())
        self._gain_slider.valueChanged.connect(
            lambda v: self._gain_lbl.setText(f"{v / 10:.1f}"))
        self._gain_slider.sliderReleased.connect(self._on_gain)
        grid.addWidget(self._gain_slider, 6, 1)
        grid.addWidget(self._gain_lbl, 6, 2)

        self._gain_sub_tr = QLabel("amplification  ·  0 dB ideal for best SNR")
        self._gain_sub_tr.setStyleSheet(_dim_style())
        grid.addWidget(self._gain_sub_tr, 7, 1, 1, 2)

        # IR gain mode (overlaid in same grid row, initially hidden)
        self._gain_label_ir = QLabel("Gain Mode")
        self._gain_combo_ir = QComboBox()
        self._gain_combo_ir.addItems(["High", "Low"])
        self._gain_combo_ir.setFixedWidth(120)
        self._gain_combo_ir.setToolTip(
            "Boson gain mode — High gain for small signals,\n"
            "Low gain for wider dynamic range")
        self._gain_combo_ir.currentTextChanged.connect(self._on_ir_gain_mode)
        self._gain_sub_ir = QLabel("High = more sensitive  ·  Low = wider dynamic range")
        self._gain_sub_ir.setStyleSheet(_dim_style())
        grid.addWidget(self._gain_label_ir, 6, 0)
        grid.addWidget(self._gain_combo_ir, 6, 1)
        grid.addWidget(self._gain_sub_ir, 7, 1, 1, 2)
        self._gain_label_ir.setVisible(False)
        self._gain_combo_ir.setVisible(False)
        self._gain_sub_ir.setVisible(False)

        self._tr_gain_widgets = [
            self._gain_label_tr, self._gain_slider, self._gain_lbl,
            self._gain_sub_tr,
        ]
        self._ir_gain_widgets = [
            self._gain_label_ir, self._gain_combo_ir, self._gain_sub_ir,
        ]

        # Row 8: Averaging
        grid.addWidget(QLabel("Averaging"), 8, 0)
        self._avg_combo = QComboBox()
        self._avg_combo.addItems(["None", "Temporal (frame avg)", "Spatial (pixel bin)"])
        self._avg_combo.setFixedWidth(200)
        self._avg_combo.currentIndexChanged.connect(lambda _: self.settings_changed.emit())
        grid.addWidget(self._avg_combo, 8, 1)

        # ── More Options ──────────────────────────────────────────────
        from ui.widgets.more_options import MoreOptionsPanel

        opts = MoreOptionsPanel(section_key="acquisition_settings")
        opts_inner = QWidget()
        opts_grid = QGridLayout(opts_inner)
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setSpacing(8)

        opts_grid.addWidget(QLabel("Quality Gate (dB)"), 0, 0)
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 60.0)
        self._quality_spin.setValue(20.0)
        self._quality_spin.setDecimals(1)
        self._quality_spin.setSuffix(" dB")
        self._quality_spin.setFixedWidth(100)
        self._quality_spin.setToolTip(
            "Minimum SNR threshold — results below this will be flagged.")
        opts_grid.addWidget(self._quality_spin, 0, 1)

        opts_grid.addWidget(QLabel("Binning"), 1, 0)
        self._bin_combo = QComboBox()
        self._bin_combo.addItems(["1×1", "2×2", "4×4"])
        self._bin_combo.setFixedWidth(100)
        opts_grid.addWidget(self._bin_combo, 1, 1)

        opts_grid.addWidget(QLabel("Trigger Mode"), 2, 0)
        self._trig_combo = QComboBox()
        self._trig_combo.addItems(["Continuous", "External", "Software"])
        self._trig_combo.setFixedWidth(140)
        opts_grid.addWidget(self._trig_combo, 2, 1)

        opts.addWidget(opts_inner)
        root.addWidget(opts)
        root.addStretch()

        # ── Hardware-dependent controls ────────────────────────────────
        self._hw_controls = [self._exp_slider, self._gain_slider]

    # ── Public API ─────────────────────────────────────────────────────

    def set_hardware_available(self, available: bool) -> None:
        for w in self._hw_controls:
            w.setEnabled(available)
        if available:
            self.refresh_camera_mode()

    def refresh_camera_mode(self) -> None:
        """Update controls for TR vs IR camera mode."""
        is_ir = getattr(app_state, "active_camera_type", "tr") == "ir"
        for w in self._tr_exposure_widgets:
            w.setVisible(not is_ir)
        for w in self._tr_gain_widgets:
            w.setVisible(not is_ir)
        for w in self._ir_gain_widgets:
            w.setVisible(is_ir)

    def get_settings(self) -> dict:
        return {
            "n_frames":     self._frames_spin.value(),
            "exposure_us":  self._exp_slider.value(),
            "gain_db":      self._gain_slider.value() / 10.0,
            "averaging":    self._avg_combo.currentText(),
            "quality_gate": self._quality_spin.value(),
            "binning":      self._bin_combo.currentText(),
            "trigger_mode": self._trig_combo.currentText(),
        }

    def set_settings(self, d: dict) -> None:
        if "n_frames" in d:
            self._frames_spin.setValue(d["n_frames"])
        if "exposure_us" in d:
            self._set_exp(d["exposure_us"])
        if "gain_db" in d:
            self._gain_slider.setValue(int(d["gain_db"] * 10))

    # ── Slots ──────────────────────────────────────────────────────────

    def _set_exp(self, us: int) -> None:
        self._exp_slider.setValue(us)
        self._on_exp()

    def _on_exp(self) -> None:
        us = self._exp_slider.value()
        cam = app_state.cam
        if cam is not None:
            try:
                cam.set_exposure(us)
            except Exception as e:
                log.debug("set_exposure failed: %s", e)
        self.settings_changed.emit()

    def _on_gain(self) -> None:
        db = self._gain_slider.value() / 10.0
        cam = app_state.cam
        if cam is not None:
            try:
                cam.set_gain(db)
            except Exception as e:
                log.debug("set_gain failed: %s", e)
        self.settings_changed.emit()

    def _on_ir_gain_mode(self, mode_text: str) -> None:
        """Set Boson High/Low gain mode from the IR combo."""
        cam = app_state.cam
        if cam is None:
            return
        db = 1.0 if mode_text == "High" else 0.0
        try:
            cam.set_gain(db)
        except Exception as e:
            log.debug("IR gain mode change failed: %s", e)
        self.settings_changed.emit()

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._exp_lbl.setStyleSheet(_mono_style())
        self._gain_lbl.setStyleSheet(_mono_style())
        self.update()
