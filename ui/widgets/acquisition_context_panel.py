"""
ui/widgets/acquisition_context_panel.py

Collapsible acquisition context panel — shows the acquisition parameters
that produced the result currently loaded in the Analysis tab.

Displayed as a compact, collapsible header strip above the analysis
body.  When a session is loaded (via Sessions -> Analyze), the context
panel populates with the session's metadata so the user knows what
they're looking at without switching tabs.

Usage
-----
    panel = AcquisitionContextPanel()
    layout.addWidget(panel)

    # Populate from SessionMeta dict:
    panel.set_context({
        "label": "chip_A_25C",
        "imaging_mode": "thermoreflectance",
        "n_frames": 256,
        "exposure_us": 500.0,
        "gain_db": 6.0,
        "fpga_frequency_hz": 1000.0,
        "fpga_duty_cycle": 0.5,
        "tec_temperature": 25.0,
        "bias_voltage": 3.3,
        "profile_name": "Silicon",
        "ct_value": 1.6e-4,
        "camera_id": "TR-Basler-acA1920",
        "timestamp_str": "2025-04-10 14:32",
        "quality_scorecard": {"overall_grade": "A", ...},
    })

    # Clear when no context available:
    panel.clear_context()
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QFrame, QSizePolicy, QPushButton,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT, MONO_FONT


class AcquisitionContextPanel(QFrame):
    """Collapsible acquisition context strip for the Analysis tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AcqContextPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(4)

        # ── Header row (title + collapse toggle) ────────────────────
        header = QHBoxLayout()
        header.setSpacing(6)

        self._title = QLabel("Acquisition Context")
        header.addWidget(self._title, 1)

        self._toggle_btn = QPushButton("\u25b2")  # ▲ collapse
        self._toggle_btn.setFixedSize(22, 22)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setToolTip("Collapse / expand acquisition context")
        self._toggle_btn.clicked.connect(self._toggle_body)
        header.addWidget(self._toggle_btn)

        dismiss = QPushButton("\u2715")  # ✕
        dismiss.setFixedSize(22, 22)
        dismiss.setCursor(Qt.PointingHandCursor)
        dismiss.setToolTip("Hide context panel")
        dismiss.clicked.connect(lambda: self.setVisible(False))
        header.addWidget(dismiss)

        root.addLayout(header)

        # ── Body: metadata grid ─────────────────────────────────────
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 2, 0, 0)
        body_lay.setSpacing(2)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(2)
        body_lay.addLayout(self._grid)

        root.addWidget(self._body)

        self._collapsed = False
        self._fields = {}  # key → QLabel (value)
        self._apply_styles()

    # ── Public API ───────────────────────────────────────────────────

    def set_context(self, ctx: dict) -> None:
        """Populate the panel from a context dict (typically SessionMeta.to_dict()).

        Only shows fields that are present and non-empty.
        """
        self._clear_grid()

        # Define display rows: (label, key, formatter)
        rows = [
            ("Session",     "label",              None),
            ("Time",        "timestamp_str",      None),
            ("Mode",        "imaging_mode",       self._fmt_mode),
            ("Camera",      "camera_id",          None),
            ("Frames",      "n_frames",           lambda v: str(v)),
            ("Exposure",    "exposure_us",        lambda v: f"{v:.0f} \u00b5s"),
            ("Gain",        "gain_db",            lambda v: f"{v:.1f} dB"),
            ("Modulation",  "fpga_frequency_hz",  self._fmt_modulation),
            ("Temperature", "tec_temperature",    lambda v: f"{v:.1f} \u00b0C"),
            ("Bias",        "bias_voltage",       self._fmt_bias),
            ("Profile",     "profile_name",       None),
            ("C\u209c",     "ct_value",           lambda v: f"{v:.2e}" if v else None),
            ("Grade",       "quality_scorecard",  self._fmt_grade),
        ]

        row_idx = 0
        for label_text, key, fmt in rows:
            val = ctx.get(key)
            if val is None or val == "" or val == 0:
                continue

            # Some formatters need the full context dict
            if fmt == self._fmt_modulation:
                display = self._fmt_modulation(val, ctx)
            elif fmt == self._fmt_bias:
                display = self._fmt_bias(val, ctx)
            elif fmt:
                display = fmt(val)
            else:
                display = str(val)

            if display is None:
                continue

            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {PALETTE['textDim']}; font-size: {FONT['label']}pt;"
                f" background: transparent;")
            val_lbl = QLabel(display)
            val_lbl.setStyleSheet(
                f"color: {PALETTE['text']}; font-size: {FONT['label']}pt;"
                f" font-family: {MONO_FONT}; background: transparent;")

            col = (row_idx % 2) * 2  # two-column layout
            row = row_idx // 2
            self._grid.addWidget(lbl, row, col, Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(val_lbl, row, col + 1, Qt.AlignLeft | Qt.AlignVCenter)
            self._fields[key] = val_lbl
            row_idx += 1

        # Update title with session label if available
        session_label = ctx.get("label", "")
        if session_label:
            self._title.setText(
                f"Acquisition Context  \u2014  {session_label}")
        else:
            self._title.setText("Acquisition Context")

        self._body.setVisible(not self._collapsed)
        self.setVisible(True)

    def clear_context(self) -> None:
        """Hide the panel and clear all fields."""
        self._clear_grid()
        self.setVisible(False)

    # ── Formatting helpers ───────────────────────────────────────────

    @staticmethod
    def _fmt_mode(v):
        modes = {
            "thermoreflectance": "Thermoreflectance",
            "ir_lockin": "IR Lock-in",
            "optical_pump_probe": "Optical Pump-Probe",
        }
        return modes.get(v, str(v))

    @staticmethod
    def _fmt_modulation(freq_hz, ctx):
        duty = ctx.get("fpga_duty_cycle", 0)
        if not freq_hz:
            return None
        parts = [f"{freq_hz:.0f} Hz"]
        if duty:
            parts.append(f"{duty * 100:.0f}% duty")
        return "  ".join(parts)

    @staticmethod
    def _fmt_bias(voltage, ctx):
        current = ctx.get("bias_current", 0)
        parts = []
        if voltage:
            parts.append(f"{voltage:.2f} V")
        if current:
            parts.append(f"{current * 1000:.1f} mA")
        return "  ".join(parts) if parts else None

    @staticmethod
    def _fmt_grade(scorecard):
        if isinstance(scorecard, dict):
            grade = scorecard.get("overall_grade", "")
            if grade:
                return f"Grade {grade}"
        return None

    # ── Internal ─────────────────────────────────────────────────────

    def _clear_grid(self):
        """Remove all widgets from the metadata grid."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._fields.clear()

    def _toggle_body(self):
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            "\u25bc" if self._collapsed else "\u25b2")  # ▼ / ▲

    def _apply_styles(self):
        self.setStyleSheet(
            f"QFrame#AcqContextPanel {{"
            f"  background: {PALETTE['surface2']};"
            f"  border: 1px solid {PALETTE['border']};"
            f"  border-radius: 4px;"
            f"}}")
        self._title.setStyleSheet(
            f"font-size: {FONT['body']}pt; font-weight: 600;"
            f" color: {PALETTE['text']}; background: transparent;")
        for btn in (self._toggle_btn,):
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent; border: none;"
                f"  color: {PALETTE['textDim']}; font-size: 10pt;"
                f"}}"
                f"QPushButton:hover {{ color: {PALETTE['text']}; }}")
