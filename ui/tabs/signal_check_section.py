"""
ui/tabs/signal_check_section.py  —  Signal check section

Live SNR readout, saturation indicator, signal verification badge,
and frame preview with ROI overlay for measurement-quality confirmation.
Phase 2 · IMAGE ACQUISITION

Layout: two-card architecture
  LEFT  — Metrics card: readout strip, controls, options
  RIGHT — Preview card: live frame with ROI overlay, camera identity, ROI badge
"""
from __future__ import annotations

import time
import logging
import math

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QGroupBox, QStackedWidget, QPushButton, QCheckBox,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen

from hardware.app_state import app_state
from ui.theme import PALETTE, FONT, MONO_FONT
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after

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

# ── Preview constants ─────────────────────────────────────────────────
_PREVIEW_MIN_W = 320
_PREVIEW_MIN_H = 240
_PREVIEW_DECIM = 3   # update every Nth update_frame call (~1.7 fps at 5 Hz)


# ── Helpers (same card/separator pattern as modality_section) ─────────

def _mono_style() -> str:
    return (f"font-family:{MONO_FONT}; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


def _color_for_level(level: str) -> str:
    """Return PALETTE colour for 'good', 'warn', 'bad'."""
    if level == "good":
        return PALETTE['success']
    elif level == "warn":
        return PALETTE['warning']
    return PALETTE['danger']


def _card_frame_qss() -> str:
    """Bordered card container QSS."""
    return (
        f"QFrame#CardFrame {{"
        f"  background: {PALETTE['surface']};"
        f"  border: 1px solid {PALETTE['border']};"
        f"  border-radius: 8px;"
        f"}}")


def _separator() -> QFrame:
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {PALETTE['border']}; border: none;")
    return line


class SignalCheckSection(QWidget):
    """Live signal quality verification — Phase 2 IMAGE ACQUISITION.

    Two-card layout: LEFT = metrics + controls, RIGHT = frame preview
    with ROI overlay for measurement-quality confirmation.
    """

    open_device_manager = pyqtSignal()
    signal_check_passed = pyqtSignal()

    navigate_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_update = 0.0
        self._passed = False
        self._snr_good = _SNR_GOOD
        self._snr_warn = _SNR_WARN
        self._preview_frame_n = 0
        self._preview_live = False
        self._last_verdict_level = "text"   # for ROI overlay colour

        _cards = get_section_cards("signal_check")
        def _body(cid):
            for c in _cards:
                if c["card_id"] == cid:
                    return c["body"]
            return ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Guidance cards — scrollable area ──────────────────────
        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "signal_check.overview",
            "Getting Started with Signal Check",
            _body("signal_check.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "signal_check.run",
            "Run the Signal Quality Check",
            _body("signal_check.run"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setObjectName("LeftPanelScroll")
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QScrollArea.NoFrame)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setMaximumHeight(280)
        self._cards_scroll.setWidget(self._cards_widget)
        self._cards_scroll.setVisible(False)
        outer.addWidget(self._cards_scroll)

        for c in (self._overview_card, self._guide_card1):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Signal Check", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        # Page 0 — empty state
        self._stack.addWidget(self._build_empty_state())

        # Page 1 — two-card layout
        controls = self._build_controls_page()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)

        outer.addWidget(self._workflow_footer)

        # ── Accumulated frames for manual "Run Check" ─────────────────
        self._check_frames: list = []
        self._check_target = 10

        # Show placeholder in preview
        self._show_placeholder()

    # ── Controls page (two-card layout) ────────────────────────────────

    def _build_controls_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 8, 16, 12)
        root.setSpacing(0)

        # ══════════════════════════════════════════════════════════════
        # Two-card body: LEFT = metrics/controls, RIGHT = preview
        # ══════════════════════════════════════════════════════════════
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # ── LEFT CARD: Metrics & Controls ────────────────────────────
        left_card = QFrame()
        left_card.setObjectName("CardFrame")
        left_card.setStyleSheet(_card_frame_qss())
        left_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        left_card.setMinimumWidth(320)

        lc = QVBoxLayout(left_card)
        lc.setContentsMargins(14, 12, 14, 12)
        lc.setSpacing(0)

        # ── Section header ────────────────────────────────────────────
        title = QLabel("Signal Check")
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            "font-weight:bold;")
        lc.addWidget(title)
        lc.addSpacing(2)

        desc = QLabel("Verify signal quality before capture.")
        desc.setStyleSheet(_dim_style())
        lc.addWidget(desc)

        lc.addSpacing(8)
        self._sep1 = _separator()
        lc.addWidget(self._sep1)
        lc.addSpacing(8)

        # ── Readout strip ─────────────────────────────────────────────
        strip_lbl = QLabel("Signal Quality")
        strip_lbl.setStyleSheet(self._section_label_qss())
        lc.addWidget(strip_lbl)
        lc.addSpacing(4)

        strip = QHBoxLayout()
        strip.setSpacing(20)

        self._snr_val = self._readout_widget("SNR (dB)")
        self._sat_val = self._readout_widget("SATURATION")
        self._verdict = self._readout_widget("VERDICT")

        strip.addWidget(self._snr_val)
        strip.addWidget(self._sat_val)
        strip.addWidget(self._verdict)
        strip.addStretch()

        lc.addLayout(strip)

        lc.addSpacing(8)
        self._sep2 = _separator()
        lc.addWidget(self._sep2)
        lc.addSpacing(6)

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
        lc.addLayout(ctrl_row)

        lc.addSpacing(4)

        # ── More Options ──────────────────────────────────────────────
        from ui.widgets.more_options import MoreOptionsPanel

        opts = MoreOptionsPanel(section_key="signal_check")
        opts_inner = QWidget()
        opts_grid = QGridLayout(opts_inner)
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setSpacing(6)

        opts_grid.addWidget(QLabel("SNR ROI"), 0, 0)
        self._roi_combo = QComboBox()
        self._roi_combo.addItems(["Full Frame", "Center 50%", "Center 25%"])
        self._roi_combo.setFixedWidth(140)
        opts_grid.addWidget(self._roi_combo, 0, 1)

        opts_grid.addWidget(QLabel("Min SNR Threshold"), 1, 0)
        self._thresh_lbl = QLabel(f"{self._snr_good:.0f} dB")
        self._thresh_lbl.setStyleSheet(_mono_style())
        opts_grid.addWidget(self._thresh_lbl, 1, 1)

        opts.addWidget(opts_inner)
        lc.addWidget(opts)

        body.addWidget(left_card, 3)

        # ── RIGHT CARD: Preview / Confirmation ───────────────────────
        right_card = QFrame()
        right_card.setObjectName("CardFrame")
        right_card.setStyleSheet(_card_frame_qss())
        right_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_card.setMinimumWidth(300)
        self._right_card = right_card

        rc = QVBoxLayout(right_card)
        rc.setContentsMargins(12, 12, 12, 12)
        rc.setSpacing(8)

        # Live preview with ROI overlay (expanding)
        self._preview_lbl = QLabel()
        self._preview_lbl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_lbl.setMinimumSize(_PREVIEW_MIN_W, _PREVIEW_MIN_H)
        self._preview_lbl.setAlignment(Qt.AlignCenter)
        self._preview_lbl.setStyleSheet(self._preview_frame_qss())
        rc.addWidget(self._preview_lbl, 1)

        # ── Info footer (confirmation panel) ──────────────────────────
        self._preview_sep = _separator()
        rc.addWidget(self._preview_sep)
        rc.addSpacing(4)

        # Footer label
        self._footer_label = QLabel("Measurement Region")
        self._footer_label.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            f"font-weight:500; text-transform:uppercase; letter-spacing:0.5px;")
        rc.addWidget(self._footer_label)
        rc.addSpacing(2)

        # Camera identity (bold)
        self._cam_identity_lbl = QLabel("")
        self._cam_identity_lbl.setAlignment(Qt.AlignLeft)
        self._cam_identity_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; color:{PALETTE['text']}; "
            f"font-weight:600;")
        rc.addWidget(self._cam_identity_lbl)

        # Camera detail (resolution — mono)
        self._cam_detail_lbl = QLabel("")
        self._cam_detail_lbl.setAlignment(Qt.AlignLeft)
        self._cam_detail_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; "
            f"color:{PALETTE['textDim']};")
        rc.addWidget(self._cam_detail_lbl)
        rc.addSpacing(4)

        # ROI badge + status caption row
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)

        self._roi_badge = QLabel("Full Frame")
        self._roi_badge.setAlignment(Qt.AlignCenter)
        self._roi_badge.setFixedHeight(22)
        self._roi_badge.setMinimumWidth(80)
        self._roi_badge.setMaximumWidth(160)
        self._apply_roi_badge_style()
        badge_row.addWidget(self._roi_badge)
        badge_row.addStretch()

        self._preview_caption = QLabel("No Preview")
        self._preview_caption.setAlignment(Qt.AlignRight)
        self._preview_caption.setStyleSheet(_dim_style())
        badge_row.addWidget(self._preview_caption)

        rc.addLayout(badge_row)

        body.addWidget(right_card, 3)

        return page

    # ── Section label style ────────────────────────────────────────────

    @staticmethod
    def _section_label_qss() -> str:
        return (f"font-size:{FONT['label']}pt; font-weight:600; "
                f"color:{PALETTE['text']};")

    # ── ROI badge ──────────────────────────────────────────────────────

    def _apply_roi_badge_style(self) -> None:
        """Apply colored pill style to the ROI mode badge."""
        mode = self._roi_combo.currentText() if hasattr(self, '_roi_combo') else "Full Frame"
        bg = PALETTE.get("accent", "#00d4aa")
        self._roi_badge.setText(mode)
        self._roi_badge.setStyleSheet(
            f"background: {bg}22; color: {bg}; "
            f"border: 1px solid {bg}44; border-radius: 10px; "
            f"font-size: {FONT['sublabel']}pt; font-weight: 600; "
            f"padding: 2px 10px;")

    def _refresh_preview_card_info(self) -> None:
        """Update camera identity + detail in the preview card."""
        cam = app_state.cam
        if cam is not None and hasattr(cam, "info"):
            model = getattr(cam.info, "model", "") or "Camera"
            w = getattr(cam.info, "width", 0)
            h = getattr(cam.info, "height", 0)
            self._cam_identity_lbl.setText(model)
            if w and h:
                fmt = getattr(cam.info, "pixel_format", "")
                detail = f"{w} × {h}"
                if fmt:
                    detail += f"  ·  {fmt}"
                self._cam_detail_lbl.setText(detail)
            else:
                self._cam_detail_lbl.setText("")
        else:
            self._cam_identity_lbl.setText("No camera")
            self._cam_detail_lbl.setText("")
        self._apply_roi_badge_style()

    # ── Live preview with ROI overlay ─────────────────────────────────

    def _render_preview(self, data) -> None:
        """Render a frame into the preview label with ROI overlay."""
        self._preview_frame_n += 1
        if self._preview_frame_n % _PREVIEW_DECIM != 0:
            return

        pw = self._preview_lbl.width()
        ph = self._preview_lbl.height()
        if pw < 10:
            pw = _PREVIEW_MIN_W
        if ph < 10:
            ph = _PREVIEW_MIN_H

        try:
            from acquisition.processing import to_display
            disp = to_display(data, mode="auto")

            if disp.ndim == 2:
                img_h, img_w = disp.shape
                disp = np.ascontiguousarray(disp)
                qi = QImage(disp.data, img_w, img_h, img_w,
                            QImage.Format_Grayscale8)
            else:
                img_h, img_w = disp.shape[:2]
                qi = QImage(disp.tobytes(), img_w, img_h, img_w * 3,
                            QImage.Format_RGB888)

            pix = QPixmap.fromImage(qi).scaled(
                pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            # Draw ROI overlay if not Full Frame
            roi_mode = self._roi_combo.currentText()
            if roi_mode != "Full Frame":
                pix = self._draw_roi_overlay(pix, img_w, img_h, roi_mode)

            self._preview_lbl.setPixmap(pix)
        except Exception:
            log.debug("Signal check preview render failed", exc_info=True)
            return

        self._preview_live = True
        cam = app_state.cam
        if cam is not None and hasattr(cam, "info"):
            model = getattr(cam.info, "model", "") or "Camera"
            self._preview_caption.setText(f"{model} · Live")
        else:
            self._preview_caption.setText("Live")

    def _draw_roi_overlay(self, pix: QPixmap, img_w: int, img_h: int,
                          roi_mode: str) -> QPixmap:
        """Draw a semi-transparent ROI rectangle on the preview pixmap."""
        # Compute ROI bounds in image coordinates
        if roi_mode == "Center 50%":
            rx, ry = img_w // 4, img_h // 4
            rw, rh = img_w // 2, img_h // 2
        elif roi_mode == "Center 25%":
            rx, ry = 3 * img_w // 8, 3 * img_h // 8
            rw, rh = img_w // 4, img_h // 4
        else:
            return pix

        # Scale ROI bounds to pixmap coordinates
        pw, ph = pix.width(), pix.height()
        # The image was aspect-ratio-scaled, so compute actual drawn area
        scale = min(pw / img_w, ph / img_h)
        offset_x = (pw - img_w * scale) / 2
        offset_y = (ph - img_h * scale) / 2

        sx = offset_x + rx * scale
        sy = offset_y + ry * scale
        sw = rw * scale
        sh = rh * scale

        # Pick colour based on current verdict
        level = self._last_verdict_level
        if level == "good":
            color = QColor(PALETTE.get("success", "#00d479"))
        elif level == "warn":
            color = QColor(PALETTE.get("warning", "#ffb300"))
        else:
            color = QColor(PALETTE.get("accent", "#00d4aa"))

        result = QPixmap(pix)
        p = QPainter(result)
        p.setRenderHint(QPainter.Antialiasing)

        # Semi-transparent fill
        fill = QColor(color)
        fill.setAlpha(30)
        p.fillRect(int(sx), int(sy), int(sw), int(sh), fill)

        # Border
        pen = QPen(color)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(int(sx), int(sy), int(sw), int(sh))

        p.end()
        return result

    def _show_placeholder(self) -> None:
        """Render a generic icon as the preview placeholder."""
        self._preview_live = False

        pw = self._preview_lbl.width()
        ph = self._preview_lbl.height()
        if pw < 10:
            pw = _PREVIEW_MIN_W
        if ph < 10:
            ph = _PREVIEW_MIN_H

        bg_col = QColor(PALETTE['bg'])
        dim_col = QColor(PALETTE['textDim'])

        canvas = QPixmap(pw, ph)
        canvas.fill(bg_col)

        try:
            from ui.icons import make_icon, IC
            icon = make_icon("mdi.signal-variant", color=dim_col.name(), size=80)
            if icon is None:
                icon = make_icon(IC.CAMERA, color=dim_col.name(), size=80)
            if icon is not None:
                icon_px = icon.pixmap(80, 80)
                p = QPainter(canvas)
                p.drawPixmap((pw - 80) // 2, (ph - 80) // 2, icon_px)
                p.end()
        except Exception:
            pass

        self._preview_lbl.setPixmap(canvas)
        self._preview_caption.setText("No Preview")

    @staticmethod
    def _preview_frame_qss() -> str:
        return (
            f"QLabel {{"
            f"  background:{PALETTE['bg']};"
            f"  border:1px solid {PALETTE['border']};"
            f"  border-radius:6px;"
            f"}}")

    # ── Public API ─────────────────────────────────────────────────────

    def showEvent(self, event):
        """Refresh preview card info when section becomes visible."""
        super().showEvent(event)
        self._refresh_preview_card_info()

    def set_snr_threshold(self, good_db: float, warn_db: float | None = None) -> None:
        """Set SNR pass/warn thresholds. Called when a profile is applied."""
        self._snr_good = good_db
        if warn_db is not None:
            self._snr_warn = warn_db
        self._thresh_lbl.setText(f"{self._snr_good:.0f} dB")

    def set_roi_strategy(self, strategy: str) -> None:
        """Set ROI combo from profile ('full', 'center50', 'center25')."""
        _map = {"full": 0, "center50": 1, "center25": 2}
        idx = _map.get(strategy, 1)
        self._roi_combo.setCurrentIndex(idx)

    def set_hardware_available(self, available: bool) -> None:
        self._stack.setCurrentIndex(1 if available else 0)
        if available:
            self._refresh_preview_card_info()
        else:
            self.reset()
            self._show_placeholder()

    def reset(self) -> None:
        self._passed = False
        self._check_frames.clear()
        self._temporal_buf: list = []   # rolling buffer for temporal SNR
        self._set_readout(self._snr_val, "--", "text")
        self._set_readout(self._sat_val, "--", "text")
        self._set_readout(self._verdict, "--", "text")
        self._last_verdict_level = "text"

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
            roi = self._extract_roi(data)
            snr = self._compute_temporal_snr(roi)
            sat_pct = self._compute_saturation(data)

            # Update readouts
            snr_level = "good" if snr >= self._snr_good else ("warn" if snr >= self._snr_warn else "bad")
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
            passed = snr >= self._snr_good and sat_pct < 95.0
            if passed:
                self._set_readout(self._verdict, "PASS", "good")
                self._last_verdict_level = "good"
                if not self._passed and self._auto_cb.isChecked():
                    self._passed = True
                    self.signal_check_passed.emit()
            else:
                self._set_readout(self._verdict, "FAIL", "bad")
                self._last_verdict_level = "bad"
                self._passed = False

            # Accumulate for manual check
            if self._check_frames is not None and len(self._check_frames) < self._check_target:
                self._check_frames.append(snr)

            # Render preview with ROI overlay
            self._render_preview(data)

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
        n_sat = int(np.sum(data >= CAMERA_SAT_LIMIT))
        total = data.size
        return (n_sat / total) * 100.0 if total > 0 else 0.0

    def _extract_roi(self, data):
        """Extract ROI from frame data based on combo selection."""
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
            color = PALETTE['textDim']
        else:
            color = _color_for_level(level)
        val_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; "
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
        from ui.widgets.empty_state import build_empty_state
        return build_empty_state(
            title="No Live Feed",
            description="Connect a camera and start the live view to "
                        "verify signal quality.",
            on_action=self.open_device_manager.emit,
        )

    def _update_cards_scroll_visibility(self, _card_id: str = "") -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1))
        self._cards_scroll.setVisible(any_visible)

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        for w in [self._snr_val, self._sat_val, self._verdict]:
            w._sub.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
        # Card frames
        card_qss = _card_frame_qss()
        for child in self.findChildren(QFrame, "CardFrame"):
            child.setStyleSheet(card_qss)
        # Separators
        for sep in (self._sep1, self._sep2, self._preview_sep):
            sep.setStyleSheet(
                f"background: {PALETTE['border']}; border: none;")
        # Preview
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setStyleSheet(self._preview_frame_qss())
            self._preview_caption.setStyleSheet(_dim_style())
            if not self._preview_live:
                self._show_placeholder()
        # Footer
        if hasattr(self, "_footer_label"):
            self._footer_label.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
                f"font-weight:500; text-transform:uppercase; letter-spacing:0.5px;")
        if hasattr(self, "_cam_identity_lbl"):
            self._cam_identity_lbl.setStyleSheet(
                f"font-size:{FONT['body']}pt; color:{PALETTE['text']}; "
                f"font-weight:600;")
            self._cam_detail_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; "
                f"color:{PALETTE['textDim']};")
        # ROI badge
        if hasattr(self, "_roi_badge"):
            self._apply_roi_badge_style()
        # Guidance cards
        for card in (self._overview_card, self._guide_card1):
            card._apply_styles()
        self._workflow_footer._apply_styles()
        self.update()
