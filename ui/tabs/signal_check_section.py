"""
ui/tabs/signal_check_section.py  —  Signal check section

Live SNR readout, saturation indicator, signal verification badge.
Phase 2 · IMAGE ACQUISITION
"""
from __future__ import annotations

import time
import logging
import math

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QGroupBox, QStackedWidget, QPushButton, QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.theme import PALETTE, FONT
from ui.icons import IC, make_icon, make_icon_label

log = logging.getLogger(__name__)

# Saturation thresholds from instrument knowledge
try:
    from ai.instrument_knowledge import CAMERA_SAT_LIMIT, CAMERA_SAT_WARN
except ImportError:
    CAMERA_SAT_LIMIT = 4095
    CAMERA_SAT_WARN = 3900

_SNR_GOOD = 20.0    # dB — green
_SNR_WARN = 10.0    # dB — amber
_UPDATE_HZ = 5      # throttle live readout updates


def _mono_style() -> str:
    return (f"font-family:'Menlo','Consolas','Courier New',monospace; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


def _color_for_level(level: str) -> str:
    """Return PALETTE colour for 'good', 'warn', 'bad'."""
    if level == "good":
        return PALETTE.get("success", "#30d158")
    elif level == "warn":
        return PALETTE.get("warning", "#ff9f0a")
    return PALETTE.get("danger", "#ff453a")


class SignalCheckSection(QWidget):
    """Live signal quality verification — Phase 2 IMAGE ACQUISITION."""

    open_device_manager = pyqtSignal()
    signal_check_passed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_update = 0.0
        self._passed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0 — empty state
        self._stack.addWidget(self._build_empty_state())

        # Page 1 — readouts
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)
        self._stack.addWidget(controls)
        self._stack.setCurrentIndex(0)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("Signal Check")
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            "font-weight:bold;")
        root.addWidget(title)

        desc = QLabel("Verify signal quality before starting a capture.")
        desc.setStyleSheet(_dim_style())
        root.addWidget(desc)

        # ── Readout strip ─────────────────────────────────────────────
        strip = QGroupBox("Signal Quality")
        strip_lay = QHBoxLayout(strip)
        strip_lay.setSpacing(24)

        self._snr_val = self._readout_widget("SNR (dB)")
        self._sat_val = self._readout_widget("SATURATION")
        self._verdict = self._readout_widget("VERDICT")

        strip_lay.addWidget(self._snr_val)
        strip_lay.addWidget(self._sat_val)
        strip_lay.addWidget(self._verdict)
        strip_lay.addStretch()

        root.addWidget(strip)

        # ── Controls row ──────────────────────────────────────────────
        ctrl_row = QHBoxLayout()

        self._run_btn = QPushButton("Run Check")
        self._run_btn.setFixedWidth(120)
        self._run_btn.clicked.connect(self._on_run_check)
        ctrl_row.addWidget(self._run_btn)

        self._auto_cb = QCheckBox("Auto-verify")
        self._auto_cb.setToolTip(
            "Continuously evaluate signal quality and mark check as passed "
            "when conditions are met.")
        self._auto_cb.setChecked(True)
        ctrl_row.addWidget(self._auto_cb)

        ctrl_row.addStretch()
        root.addLayout(ctrl_row)

        # ── More Options ──────────────────────────────────────────────
        from ui.widgets.more_options import MoreOptionsPanel

        opts = MoreOptionsPanel(section_key="signal_check")
        opts_inner = QWidget()
        opts_grid = QGridLayout(opts_inner)
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setSpacing(8)

        opts_grid.addWidget(QLabel("SNR ROI"), 0, 0)
        self._roi_combo = QComboBox()
        self._roi_combo.addItems(["Full Frame", "Center 50%", "Center 25%"])
        self._roi_combo.setFixedWidth(140)
        opts_grid.addWidget(self._roi_combo, 0, 1)

        opts_grid.addWidget(QLabel("Min SNR Threshold"), 1, 0)
        self._thresh_lbl = QLabel(f"{_SNR_GOOD:.0f} dB")
        self._thresh_lbl.setStyleSheet(_mono_style())
        opts_grid.addWidget(self._thresh_lbl, 1, 1)

        opts.addWidget(opts_inner)
        root.addWidget(opts)
        root.addStretch()

        # ── Accumulated frames for manual "Run Check" ─────────────────
        self._check_frames: list = []
        self._check_target = 10

    # ── Public API ─────────────────────────────────────────────────────

    def set_hardware_available(self, available: bool) -> None:
        self._stack.setCurrentIndex(1 if available else 0)
        if not available:
            self.reset()

    def reset(self) -> None:
        self._passed = False
        self._check_frames.clear()
        self._temporal_buf: list = []   # rolling buffer for temporal SNR
        self._set_readout(self._snr_val, "--", "text")
        self._set_readout(self._sat_val, "--", "text")
        self._set_readout(self._verdict, "--", "text")

    def update_frame(self, frame) -> None:
        """Called from main_app._on_frame() with each live frame."""
        now = time.monotonic()
        if now - self._last_update < 1.0 / _UPDATE_HZ:
            return
        self._last_update = now

        data = getattr(frame, 'data', None)
        if data is None:
            return

        try:
            import numpy as np
            roi = self._extract_roi(data)
            snr = self._compute_temporal_snr(roi)
            sat_pct = self._compute_saturation(data)

            # Update readouts
            snr_level = "good" if snr >= _SNR_GOOD else ("warn" if snr >= _SNR_WARN else "bad")
            self._set_readout(self._snr_val, f"{snr:.1f}", snr_level)

            if sat_pct >= 100.0:
                sat_level = "bad"
                sat_text = "CLIPPED"
            elif sat_pct >= 80.0:
                sat_level = "warn"
                sat_text = f"{sat_pct:.0f}%"
            else:
                sat_level = "good"
                sat_text = f"{sat_pct:.0f}%"
            self._set_readout(self._sat_val, sat_text, sat_level)

            # Evaluate pass/fail
            passed = snr >= _SNR_GOOD and sat_pct < 95.0
            if passed:
                self._set_readout(self._verdict, "PASS", "good")
                if not self._passed and self._auto_cb.isChecked():
                    self._passed = True
                    self.signal_check_passed.emit()
            else:
                self._set_readout(self._verdict, "FAIL", "bad")
                self._passed = False

            # Accumulate for manual check
            if self._check_frames is not None and len(self._check_frames) < self._check_target:
                self._check_frames.append(snr)

        except Exception:
            log.debug("Signal check update failed", exc_info=True)

    # ── Internal ───────────────────────────────────────────────────────

    _TEMPORAL_BUF_SIZE = 8  # frames to accumulate for temporal SNR

    def _compute_temporal_snr(self, roi) -> float:
        """Compute temporal SNR from a rolling buffer of ROI frames.

        Temporal SNR = mean(signal) / mean(temporal_noise) where temporal
        noise is the standard deviation at each pixel across frames.
        This correctly measures noise without being confused by spatial
        signal structure (die edges, bond pads, etc.).

        Falls back to single-frame spatial SNR until enough frames
        accumulate.
        """
        import numpy as np

        if not hasattr(self, '_temporal_buf'):
            self._temporal_buf = []

        # Downsample to keep memory bounded (every 4th pixel)
        small = roi[::4, ::4].astype(np.float32) if roi.ndim == 2 else roi[::4, ::4, 0].astype(np.float32)
        self._temporal_buf.append(small)
        if len(self._temporal_buf) > self._TEMPORAL_BUF_SIZE:
            self._temporal_buf.pop(0)

        mean_signal = float(np.mean(small))
        if mean_signal <= 0:
            return 0.0

        if len(self._temporal_buf) >= 3:
            # Temporal noise: per-pixel std across frames
            stack = np.stack(self._temporal_buf, axis=0)
            temporal_std = np.mean(np.std(stack, axis=0))
            if temporal_std < 1e-10:
                return 60.0
            return 10.0 * math.log10(mean_signal / temporal_std)
        else:
            # Not enough frames yet — show a provisional estimate
            std = float(np.std(small))
            if std < 1e-10:
                return 60.0
            return 10.0 * math.log10(mean_signal / std)

    @staticmethod
    def _compute_saturation(data) -> float:
        import numpy as np
        n_sat = int(np.sum(data >= CAMERA_SAT_LIMIT))
        total = data.size
        return (n_sat / total) * 100.0 if total > 0 else 0.0

    def _extract_roi(self, data):
        """Extract ROI from frame data based on combo selection."""
        import numpy as np
        mode = self._roi_combo.currentText()
        h, w = data.shape[:2]
        if mode == "Center 50%":
            y0, x0 = h // 4, w // 4
            return data[y0:y0 + h // 2, x0:x0 + w // 2]
        elif mode == "Center 25%":
            y0, x0 = 3 * h // 8, 3 * w // 8
            return data[y0:y0 + h // 4, x0:x0 + w // 4]
        return data

    def _on_run_check(self) -> None:
        self._check_frames.clear()
        self._set_readout(self._verdict, "CHECKING…", "warn")

    def _set_readout(self, widget, text: str, level: str) -> None:
        val_lbl = widget._val
        val_lbl.setText(text)
        if level == "text":
            color = PALETTE.get("textDim", "#888")
        else:
            color = _color_for_level(level)
        val_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; "
            f"font-size:{FONT['readoutSm']}pt; color:{color};")

    def _readout_widget(self, label: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setContentsMargins(0, 0, 0, 0)
        sub = QLabel(label)
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
        val = QLabel("--")
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(_mono_style())
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        w._sub = sub
        return w

    # ── Empty state ────────────────────────────────────────────────────

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        self._es_icon = make_icon_label(
            IC.LINK_OFF, color=PALETTE.get("textDim", "#555555"), size=64)
        self._es_icon.setAlignment(Qt.AlignCenter)

        self._es_title = QLabel("No Live Feed")
        self._es_title.setAlignment(Qt.AlignCenter)

        self._es_tip = QLabel(
            "Connect a camera and start the live view to verify signal quality.")
        self._es_tip.setAlignment(Qt.AlignCenter)
        self._es_tip.setWordWrap(True)
        self._es_tip.setMaximumWidth(400)

        self._es_btn = QPushButton("Open Device Manager")
        self._es_btn.setFixedWidth(200)
        self._es_btn.setFixedHeight(36)
        self._es_btn.clicked.connect(self.open_device_manager)

        self._apply_empty_state_styles()

        lay.addStretch()
        lay.addWidget(self._es_icon)
        lay.addWidget(self._es_title)
        lay.addWidget(self._es_tip)
        lay.addSpacing(8)
        lay.addWidget(self._es_btn, 0, Qt.AlignCenter)
        lay.addStretch()
        return w

    def _apply_empty_state_styles(self) -> None:
        dim = PALETTE.get("textDim", "#888888")
        accent = PALETTE.get("accent", "#00d4aa")
        self._es_title.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:bold; color:{dim};")
        self._es_tip.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{dim};")
        self._es_btn.setStyleSheet(f"""
            QPushButton {{
                background:{PALETTE.get('surface','#2d2d2d')}; color:{accent};
                border:1px solid {accent}66; border-radius:5px;
                font-size:{FONT['label']}pt; font-weight:600;
            }}
            QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; }}
        """)
        icon = make_icon(IC.LINK_OFF, color=dim, size=64)
        if icon:
            self._es_icon.setPixmap(icon.pixmap(64, 64))

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        for w in [self._snr_val, self._sat_val, self._verdict]:
            w._sub.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
        if hasattr(self, "_es_btn"):
            self._apply_empty_state_styles()
        self.update()
