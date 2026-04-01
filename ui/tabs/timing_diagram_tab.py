"""
ui/tabs/timing_diagram_tab.py — Timing Diagram tab for SanjINSIGHT.

Shows a live, parameter-driven timing diagram for two standard
power-device characterization topologies:

  • Double-Pulse / Pulsed-IV  (matches the BA2531D02 reference diagram)
  • Pulsed RF transistor characterization  (matches ANBD2510)

All timing is computed from editable parameters.  "Sync from Hardware"
buttons pull live values from the FPGA and Transient tabs so the diagram
always matches the actual hardware configuration.

Usage (main_app.py)
-------------------
    self._timing_tab = TimingDiagramTab()
    self._timing_tab.set_fpga_source(self._fpga_tab)
    self._timing_tab.set_transient_source(self._transient_tab)
    # wire into sidebar as NI("Timing", _I["Timing"], self._timing_tab)
"""

from __future__ import annotations

import logging
import os

from PyQt5.QtCore    import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QComboBox, QGroupBox, QFrame, QScrollArea,
    QSizePolicy, QFileDialog,
)

from ui.theme import FONT, PALETTE
from ui.icons import IC, set_btn_icon
from ui.widgets.timing_diagram import TimingDiagramWidget, TimingDiagramParams

log = logging.getLogger(__name__)


class TimingDiagramTab(QWidget):
    """
    Full timing diagram panel: parameter controls on the left,
    live waveform diagram on the right.

    Parameters can be edited manually or synced from live hardware tabs.
    The diagram redraws immediately on every parameter change.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._fpga_tab      = None
        self._transient_tab = None
        self._bias_tab      = None
        self._rebuild_pending = False

        self._build_ui()
        self._apply_styles()
        self._update_diagram()

    # ── Hardware source wiring ────────────────────────────────────────────────

    def set_fpga_source(self, fpga_tab) -> None:
        """Wire FPGA tab so 'Sync from FPGA' can read live settings."""
        self._fpga_tab = fpga_tab

    def set_transient_source(self, transient_tab) -> None:
        """Wire Transient tab so 'Sync from Transient' can read delays."""
        self._transient_tab = transient_tab

    def set_bias_source(self, bias_tab) -> None:
        """Wire Bias tab for voltage level sync."""
        self._bias_tab = bias_tab

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left panel: controls (scrollable) ─────────────────────────────────
        left = QWidget()
        self._left_panel = left
        left.setStyleSheet(
            f".QWidget {{ background:{PALETTE['surface2']};"
            f"border-right:1px solid {PALETTE['border']}; }}"
        )
        llay = QVBoxLayout(left)
        llay.setContentsMargins(12, 14, 12, 14)
        llay.setSpacing(10)

        # Mode selector
        llay.addWidget(self._build_mode_group())
        llay.addWidget(self._build_timing_group())
        llay.addWidget(self._build_bias_group())
        llay.addWidget(self._build_sync_group())
        llay.addStretch(1)
        llay.addWidget(self._build_export_btn())

        left_scroll = QScrollArea()
        left_scroll.setFixedWidth(264)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)
        root.addWidget(left_scroll)

        # ── Right panel: diagram ──────────────────────────────────────────────
        right = QWidget()
        rlay  = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(0)

        self._diagram = TimingDiagramWidget()

        # Wrap in a scroll area so it stays usable at small window sizes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(self._diagram)

        rlay.addWidget(scroll, 1)
        root.addWidget(right, 1)

    # ── Control groups ────────────────────────────────────────────────────────

    def _build_mode_group(self) -> QGroupBox:
        grp = QGroupBox("Mode")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(6)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Double-Pulse / Pulsed IV", "Pulsed RF"])
        self._mode_combo.currentIndexChanged.connect(self._on_param_changed)
        lay.addWidget(self._mode_combo)

        info = QLabel("Double-Pulse: power device switching\n"
                      "Pulsed RF: transistor pulsed S-params")
        info.setWordWrap(True)
        info.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};"
            "background:transparent;")
        lay.addWidget(info)
        return grp

    def _build_timing_group(self) -> QGroupBox:
        grp = QGroupBox("Timing")
        grid = QGridLayout(grp)
        grid.setContentsMargins(8, 12, 8, 8)
        grid.setSpacing(6)

        def _row(label_text, widget, row):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};"
                "background:transparent;")
            grid.addWidget(lbl,    row, 0)
            grid.addWidget(widget, row, 1)
            grid.setColumnStretch(1, 1)

        self._period_spin = QDoubleSpinBox()
        self._period_spin.setRange(0.1, 1_000_000.0)
        self._period_spin.setDecimals(1)
        self._period_spin.setSuffix(" μs")
        self._period_spin.setValue(100.0)
        self._period_spin.valueChanged.connect(self._on_param_changed)
        _row("Period T", self._period_spin, 0)

        self._n_pulses_spin = QSpinBox()
        self._n_pulses_spin.setRange(1, 20)
        self._n_pulses_spin.setValue(3)
        self._n_pulses_spin.valueChanged.connect(self._on_param_changed)
        _row("N pulses", self._n_pulses_spin, 1)

        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(0.05, 0.90)
        self._duty_spin.setDecimals(2)
        self._duty_spin.setSingleStep(0.05)
        self._duty_spin.setValue(0.45)
        self._duty_spin.valueChanged.connect(self._on_param_changed)
        _row("Duty cycle", self._duty_spin, 2)

        self._mask_spin = QDoubleSpinBox()
        self._mask_spin.setRange(1.0, 100_000.0)
        self._mask_spin.setDecimals(0)
        self._mask_spin.setSuffix(" ns")
        self._mask_spin.setValue(200.0)
        self._mask_spin.valueChanged.connect(self._on_param_changed)
        _row("Transient mask", self._mask_spin, 3)

        self._stop_spin = QDoubleSpinBox()
        self._stop_spin.setRange(1.0, 100_000.0)
        self._stop_spin.setDecimals(0)
        self._stop_spin.setSuffix(" ns")
        self._stop_spin.setValue(100.0)
        self._stop_spin.valueChanged.connect(self._on_param_changed)
        _row("Stop blanking", self._stop_spin, 4)

        # Pulsed-RF extras (shown/hidden by mode)
        self._rf_duty_spin = QDoubleSpinBox()
        self._rf_duty_spin.setRange(0.05, 0.90)
        self._rf_duty_spin.setDecimals(2)
        self._rf_duty_spin.setSingleStep(0.05)
        self._rf_duty_spin.setValue(0.30)
        self._rf_duty_spin.valueChanged.connect(self._on_param_changed)
        self._rf_duty_lbl = QLabel("RF duty")
        self._rf_duty_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};"
            "background:transparent;")
        grid.addWidget(self._rf_duty_lbl,  5, 0)
        grid.addWidget(self._rf_duty_spin, 5, 1)

        return grp

    def _build_bias_group(self) -> QGroupBox:
        grp = QGroupBox("Bias")
        grid = QGridLayout(grp)
        grid.setContentsMargins(8, 12, 8, 8)
        grid.setSpacing(6)

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};"
                "background:transparent;")
            return l

        grid.addWidget(_lbl("Bias mode"), 0, 0)
        self._bias_mode_combo = QComboBox()
        self._bias_mode_combo.addItems(["Pulsed", "Constant"])
        self._bias_mode_combo.currentIndexChanged.connect(self._on_param_changed)
        grid.addWidget(self._bias_mode_combo, 0, 1)

        grid.addWidget(_lbl("Level (V)"), 1, 0)
        self._bias_level_spin = QDoubleSpinBox()
        self._bias_level_spin.setRange(-100.0, 100.0)
        self._bias_level_spin.setDecimals(2)
        self._bias_level_spin.setValue(3.3)
        self._bias_level_spin.valueChanged.connect(self._on_param_changed)
        grid.addWidget(self._bias_level_spin, 1, 1)

        grid.addWidget(_lbl("Threshold (A)"), 2, 0)
        self._compliance_spin = QDoubleSpinBox()
        self._compliance_spin.setRange(0.001, 100.0)
        self._compliance_spin.setDecimals(3)
        self._compliance_spin.setValue(2.0)
        self._compliance_spin.valueChanged.connect(self._on_param_changed)
        grid.addWidget(self._compliance_spin, 2, 1)

        grid.setColumnStretch(1, 1)
        return grp

    def _build_sync_group(self) -> QGroupBox:
        grp = QGroupBox("Sync from Hardware")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(6)

        self._sync_fpga_btn = QPushButton("  Sync from FPGA")
        self._sync_fpga_btn.setFixedHeight(32)
        self._sync_fpga_btn.clicked.connect(self._on_sync_fpga)
        set_btn_icon(self._sync_fpga_btn, IC.SYNC)
        lay.addWidget(self._sync_fpga_btn)

        self._sync_transient_btn = QPushButton("  Sync from Transient")
        self._sync_transient_btn.setFixedHeight(32)
        self._sync_transient_btn.clicked.connect(self._on_sync_transient)
        set_btn_icon(self._sync_transient_btn, IC.SYNC)
        lay.addWidget(self._sync_transient_btn)

        self._sync_bias_btn = QPushButton("  Sync from Bias")
        self._sync_bias_btn.setFixedHeight(32)
        self._sync_bias_btn.clicked.connect(self._on_sync_bias)
        set_btn_icon(self._sync_bias_btn, IC.SYNC)
        lay.addWidget(self._sync_bias_btn)

        self._sync_status_lbl = QLabel("")
        self._sync_status_lbl.setWordWrap(True)
        self._sync_status_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};"
            "background:transparent;")
        lay.addWidget(self._sync_status_lbl)

        return grp

    def _build_export_btn(self) -> QPushButton:
        btn = QPushButton("  Export PNG")
        btn.setFixedHeight(36)
        btn.clicked.connect(self._on_export)
        set_btn_icon(btn, IC.EXPORT_IMG)
        self._export_btn = btn
        return btn

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_param_changed(self, *_):
        """Debounce rapid spin-box changes with a 50 ms timer."""
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(50, self._update_diagram)

    def _update_diagram(self):
        self._rebuild_pending = False
        mode_idx = self._mode_combo.currentIndex()

        # Show/hide RF-only controls
        is_rf = (mode_idx == 1)
        self._rf_duty_lbl.setVisible(is_rf)
        self._rf_duty_spin.setVisible(is_rf)
        self._n_pulses_spin.setEnabled(not is_rf)

        params = TimingDiagramParams(
            mode              = "pulsed_rf" if is_rf else "double_pulse",
            period_us         = self._period_spin.value(),
            n_pulses          = self._n_pulses_spin.value(),
            duty_cycle        = self._duty_spin.value(),
            transient_mask_ns = self._mask_spin.value(),
            stop_blanking_ns  = self._stop_spin.value(),
            bias_mode         = "constant" if self._bias_mode_combo.currentIndex() == 1
                                else "pulsed",
            bias_level_v      = self._bias_level_spin.value(),
            compliance_a      = self._compliance_spin.value(),
            rf_duty           = self._rf_duty_spin.value(),
        )
        self._diagram.set_params(params)

    def _on_sync_fpga(self):
        """Pull period and duty cycle from the live FPGA tab."""
        if self._fpga_tab is None:
            self._sync_status_lbl.setText("⚠ No FPGA tab connected")
            return
        try:
            # Try common attribute names used by FpgaTab
            freq = None
            duty = None
            for attr in ("_freq_spin", "_frequency_spin", "_freq"):
                w = getattr(self._fpga_tab, attr, None)
                if w is not None and hasattr(w, "value"):
                    freq = w.value()
                    break
            for attr in ("_duty_spin", "_duty_cycle_spin", "_duty"):
                w = getattr(self._fpga_tab, attr, None)
                if w is not None and hasattr(w, "value"):
                    duty = w.value()
                    break
            if freq is not None and freq > 0:
                self._period_spin.setValue(1_000_000.0 / freq)   # Hz → μs
            if duty is not None:
                self._duty_spin.setValue(duty / 100.0 if duty > 1.0 else duty)
            self._sync_status_lbl.setText("✓ Synced from FPGA")
        except Exception as exc:
            self._sync_status_lbl.setText(f"⚠ Sync failed: {exc}")
            log.warning("FPGA sync error: %s", exc)

    def _on_sync_transient(self):
        """Pull delay times from the live Transient tab."""
        if self._transient_tab is None:
            self._sync_status_lbl.setText("⚠ No Transient tab connected")
            return
        try:
            import numpy as np
            delays = None
            # Try to call the tab's build_delay_times helper
            if hasattr(self._transient_tab, "_build_delay_times"):
                delays = self._transient_tab._build_delay_times()
            if delays is not None and len(delays) > 1:
                total_us = float(np.sum(delays)) * 1e6
                self._period_spin.setValue(total_us)
            # Try n_delays
            for attr in ("_n_delays_spin", "_n_delays"):
                w = getattr(self._transient_tab, attr, None)
                if w is not None and hasattr(w, "value"):
                    self._n_pulses_spin.setValue(int(w.value()))
                    break
            self._sync_status_lbl.setText("✓ Synced from Transient")
        except Exception as exc:
            self._sync_status_lbl.setText(f"⚠ Sync failed: {exc}")
            log.warning("Transient sync error: %s", exc)

    def _on_sync_bias(self):
        """Pull voltage level from the live Bias tab."""
        if self._bias_tab is None:
            self._sync_status_lbl.setText("⚠ No Bias tab connected")
            return
        try:
            for attr in ("_level_spin", "_voltage_spin", "_volt_spin"):
                w = getattr(self._bias_tab, attr, None)
                if w is not None and hasattr(w, "value"):
                    self._bias_level_spin.setValue(w.value())
                    break
            for attr in ("_compliance_spin", "_current_spin"):
                w = getattr(self._bias_tab, attr, None)
                if w is not None and hasattr(w, "value"):
                    self._compliance_spin.setValue(w.value())
                    break
            self._sync_status_lbl.setText("✓ Synced from Bias")
        except Exception as exc:
            self._sync_status_lbl.setText(f"⚠ Sync failed: {exc}")
            log.warning("Bias sync error: %s", exc)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Timing Diagram", "timing_diagram.png",
            "PNG images (*.png)")
        if not path:
            return
        if self._diagram.export_png(path):
            self._sync_status_lbl.setText(
                f"✓ Saved {os.path.basename(path)}")
        else:
            self._sync_status_lbl.setText("⚠ Export failed")

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        P = PALETTE
        surface2 = P["surface2"]
        surface  = P["surface"]
        border   = P["border"]
        text     = P["text"]
        textDim  = P["textDim"]
        accent   = P["accent"]

        # Left panel
        self.setStyleSheet(f"""
            QGroupBox {{
                background: {surface2};
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 18px;
                font-size: {FONT['sublabel']}pt;
                font-weight: 600;
                color: {textDim};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
            QLabel {{ background: transparent; color: {text}; }}
            QDoubleSpinBox, QSpinBox, QComboBox {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: {FONT['body']}pt;
                min-height: 24px;
            }}
            QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
                border-color: {accent};
            }}
            QPushButton {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 5px;
                padding: 4px 12px;
                font-size: {FONT['body']}pt;
            }}
            QPushButton:hover  {{ background: {P['surfaceHover']}; }}
            QPushButton:pressed {{ background: {surface2}; }}
        """)

        if hasattr(self, "_left_panel"):
            self._left_panel.setStyleSheet(
                f".QWidget {{ background: {surface2};"
                f"border-right: 1px solid {border}; }}"
            )
        if hasattr(self, "_diagram"):
            self._diagram._apply_styles()
