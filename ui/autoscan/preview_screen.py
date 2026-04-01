"""
ui/autoscan/preview_screen.py

Screen B — Live Preview + Findings

Left  : Live thermal image with hotspot markers and suggested ROI overlay
Right : Findings panel — hotspot count, signal quality, scan area selection

The screen receives live frames via ``update_frame(frame)`` and analysis
results via ``set_analysis_result(result)``.  The "Scan →" button emits
``scan_requested(cfg)`` carrying the user-selected scan area override.
"""

from __future__ import annotations

import time
from typing import Optional, List

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QFrame, QSizePolicy, QScrollArea, QButtonGroup,
    QRadioButton, QProgressBar)
from PyQt5.QtCore  import Qt, pyqtSignal, QRect, QPoint, QSize, QTimer
from PyQt5.QtGui   import (QPixmap, QImage, QPainter, QPen, QColor,
                            QBrush, QFont, QFontMetrics)

from ui.theme import FONT, PALETTE, scaled_qss


# ── Live image view with overlay ─────────────────────────────────────

class _LiveImageView(QLabel):
    """Displays a thermal frame as a QPixmap.

    Overlays:
      - An amber dashed bounding box for the suggested ROI
      - Numbered coloured circles at each hotspot pixel location
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self._hotspots: list  = []          # list of (cx%, cy%, label, color_hex)
        self._roi: Optional[QRect] = None   # in percent coords [0..1]

    def set_frame_pixmap(self, px: QPixmap) -> None:
        self.setPixmap(px.scaled(self.size(), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))

    def set_overlays(self,
                     hotspots: list,
                     roi: Optional[tuple] = None) -> None:
        """hotspots: list of (cx_frac, cy_frac, label, color_hex).
           roi: (x0_frac, y0_frac, x1_frac, y1_frac) or None."""
        self._hotspots = hotspots
        if roi is not None:
            self._roi = roi
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not (self._hotspots or self._roi):
            return

        pm = self.pixmap()
        if pm is None or pm.isNull():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Compute image rect within label (centered, aspect-preserved)
        lw, lh = self.width(), self.height()
        iw, ih = pm.width(), pm.height()
        scale  = min(lw / max(iw, 1), lh / max(ih, 1))
        draw_w = int(iw * scale)
        draw_h = int(ih * scale)
        ox     = (lw - draw_w) // 2
        oy     = (lh - draw_h) // 2

        # ROI suggestion box (amber dashed)
        if self._roi:
            x0f, y0f, x1f, y1f = self._roi
            rx = ox + int(x0f * draw_w)
            ry = oy + int(y0f * draw_h)
            rw = int((x1f - x0f) * draw_w)
            rh = int((y1f - y0f) * draw_h)
            pen = QPen(QColor(PALETTE['warning']), 2, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(rx, ry, rw, rh)

        # Hotspot circles
        fnt = QFont()
        fnt.setPointSize(int(FONT.get("label", 9)))
        fnt.setBold(True)
        p.setFont(fnt)

        for (cx_f, cy_f, label, color_hex) in self._hotspots:
            cx = ox + int(cx_f * draw_w)
            cy = oy + int(cy_f * draw_h)
            r  = 12
            col = QColor(color_hex)
            col_dim = QColor(color_hex)
            col_dim.setAlpha(120)
            p.setBrush(QBrush(col_dim))
            p.setPen(QPen(col, 2))
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            p.setPen(QPen(QColor(PALETTE['text'])))
            p.drawText(cx - r, cy - r, r * 2, r * 2, Qt.AlignCenter, label)

        p.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.pixmap() and not self.pixmap().isNull():
            self.setPixmap(self.pixmap().scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


# ── Quality pill ──────────────────────────────────────────────────────

class _QualityPill(QWidget):
    """Compact inline row: label  ████████░░ value  status-icon."""

    def __init__(self, metric: str, parent=None):
        super().__init__(parent)
        self._metric = metric
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        self._lbl   = QLabel(metric)
        self._lbl.setFixedWidth(70)
        self._bar   = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setFixedWidth(90)
        self._val   = QLabel("—")
        self._val.setFixedWidth(60)
        self._icon  = QLabel("")
        self._icon.setFixedWidth(20)

        lay.addWidget(self._lbl)
        lay.addWidget(self._bar)
        lay.addWidget(self._val)
        lay.addWidget(self._icon)
        lay.addStretch()

    def set_value(self, value_str: str, fraction: float, status: str) -> None:
        """fraction: 0..1.  status: 'good'|'ok'|'warn'|'bad'."""
        self._val.setText(value_str)
        self._bar.setValue(int(fraction * 100))
        icons  = {"good": "✓", "ok": "✓", "warn": "⚠", "bad": "✗"}
        colors = {"good": PALETTE['accent'], "ok": PALETTE['accent'], "warn": PALETTE['warning'], "bad": PALETTE['danger']}
        col    = colors.get(status, PALETTE['textDim'])
        self._icon.setText(icons.get(status, ""))
        self._icon.setStyleSheet(f"color:{col}; font-size:{FONT['label']}pt;")
        self._bar.setStyleSheet(f"""
            QProgressBar {{ background: {PALETTE['surface2']};
                            border-radius: 3px; }}
            QProgressBar::chunk {{ background: {col}; border-radius: 3px; }}
        """)

    def _apply_styles(self) -> None:
        P   = PALETTE
        txt = P['text']
        dim = P['textDim']
        self._lbl.setStyleSheet(f"color:{dim}; font-size:{FONT['label']}pt;")
        self._val.setStyleSheet(f"color:{txt}; font-size:{FONT['label']}pt;")


# ── Main widget ───────────────────────────────────────────────────────

class PreviewScreen(QWidget):
    """Screen B: live preview + analysis findings."""

    back_clicked   = pyqtSignal()
    scan_requested = pyqtSignal(dict)   # carries scan_area override in cfg

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scan_cfg: dict    = {}
        self._analysis_result   = None
        self._is_scanning       = False

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: live image ──────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8)
        left_lay.setSpacing(4)

        self._image_view = _LiveImageView()
        left_lay.addWidget(self._image_view, 1)

        self._status_lbl = QLabel("Waiting for live feed…")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        left_lay.addWidget(self._status_lbl)

        splitter.addWidget(left)

        # ── Right: findings ───────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 12, 12, 12)
        right_lay.setSpacing(14)

        # Hotspot count card
        self._count_card = QWidget()
        self._count_card.setObjectName("countCard")
        count_lay = QVBoxLayout(self._count_card)
        count_lay.setContentsMargins(12, 10, 12, 10)
        self._count_lbl = QLabel("Previewing…")
        self._count_lbl.setWordWrap(True)
        self._conf_lbl  = QLabel("")
        count_lay.addWidget(self._count_lbl)
        count_lay.addWidget(self._conf_lbl)
        right_lay.addWidget(self._count_card)

        # Signal quality
        sq_lbl = QLabel("Signal Quality")
        sq_lbl.setObjectName("sectionHeader")
        right_lay.addWidget(sq_lbl)

        self._snr_pill  = _QualityPill("SNR")
        self._sat_pill  = _QualityPill("Saturation")
        self._drift_pill = _QualityPill("Drift")
        right_lay.addWidget(self._snr_pill)
        right_lay.addWidget(self._sat_pill)
        right_lay.addWidget(self._drift_pill)

        right_lay.addWidget(self._hline())

        # Scan area selection
        area_lbl = QLabel("Scan Area")
        area_lbl.setObjectName("sectionHeader")
        right_lay.addWidget(area_lbl)

        self._area_hottest = QRadioButton("Hottest region  (recommended)")
        self._area_roi     = QRadioButton("Selected ROI")
        self._area_full    = QRadioButton("Full view")
        self._area_hottest.setChecked(True)

        self._area_btn_grp = QButtonGroup(self)
        self._area_btn_grp.addButton(self._area_hottest, 0)
        self._area_btn_grp.addButton(self._area_roi,     1)
        self._area_btn_grp.addButton(self._area_full,    2)
        self._area_btn_grp.setExclusive(True)
        self._area_btn_grp.idClicked.connect(self._on_area_changed)

        self._est_time_lbl = QLabel("")
        right_lay.addWidget(self._area_hottest)
        right_lay.addWidget(self._area_roi)
        right_lay.addWidget(self._area_full)
        right_lay.addWidget(self._est_time_lbl)

        right_lay.addWidget(self._hline())

        # Auto-explanation label
        self._explain_lbl = QLabel("")
        self._explain_lbl.setObjectName("explainLabel")
        self._explain_lbl.setWordWrap(True)
        right_lay.addWidget(self._explain_lbl)

        right_lay.addStretch()
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setSizes([550, 320])

        # ── Footer ────────────────────────────────────────────────
        footer = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedHeight(32)
        self._scan_btn = QPushButton("Scan  →")
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.setMinimumWidth(140)
        self._scan_btn.setEnabled(False)
        self._back_btn.clicked.connect(self.back_clicked)
        self._scan_btn.clicked.connect(self._on_scan)
        footer.addWidget(self._back_btn)
        footer.addStretch()
        footer.addWidget(self._scan_btn)

        # ── Root layout ───────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(splitter, 1)

        footer_w = QWidget()
        footer_lay = QVBoxLayout(footer_w)
        footer_lay.setContentsMargins(12, 6, 12, 10)
        footer_lay.addWidget(self._hline())
        footer_lay.addLayout(footer)
        root.addWidget(footer_w)

        self._apply_styles()

    # ── Public API ────────────────────────────────────────────────────

    def start_preview(self, cfg: dict) -> None:
        """Called when navigating to Screen B.  Stores config and resets state."""
        self._scan_cfg    = cfg
        self._analysis_result = None
        self._is_scanning = False
        self._scan_btn.setEnabled(False)
        self._count_lbl.setText("Previewing — acquiring frames…")
        self._conf_lbl.setText("")
        self._explain_lbl.setText("")
        self._status_lbl.setText("Acquiring preview frames…")
        self._est_time_lbl.setText("")
        # Clear overlays
        self._image_view.set_overlays([], None)

    def update_frame(self, frame) -> None:
        """Receive a live frame and display it as a thermal image."""
        try:
            # frame is a LiveFrame namedtuple/object with display_image or delta_rr
            img = getattr(frame, "display_image", None)
            if img is None:
                arr = getattr(frame, "delta_rr", None)
                if arr is not None:
                    from acquisition.processing import apply_colormap
                    img = apply_colormap(arr, colormap_name="inferno")
            if img is not None:
                # img may be ndarray (H,W,3) or QPixmap
                if hasattr(img, "width"):   # already a QPixmap
                    self._image_view.set_frame_pixmap(img)
                else:
                    h, w = img.shape[:2]
                    qimg = QImage(img.tobytes(), w, h, w * 3, QImage.Format_RGB888)
                    self._image_view.set_frame_pixmap(QPixmap.fromImage(qimg))
                self._status_lbl.setText("Live preview")
        except Exception:
            pass

    def set_analysis_result(self, result) -> None:
        """Called when a preview acquisition completes.

        Runs ``ThermalAnalysisEngine`` on the result, populates findings panel.
        """
        if self._is_scanning:
            return
        self._analysis_result = result
        try:
            from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig
            cfg  = AnalysisConfig()
            eng  = ThermalAnalysisEngine(cfg)
            drr  = getattr(result, "delta_r_over_r", None)
            if drr is None:
                self._count_lbl.setText("Preview complete  — no thermal data")
                return
            ar   = eng.run(drr)
            self._populate_findings(ar, result)
            self._scan_btn.setEnabled(True)
        except Exception as exc:
            self._count_lbl.setText("Analysis unavailable")
            self._explain_lbl.setText(str(exc))
            self._scan_btn.setEnabled(True)

    def set_scanning_state(self, scanning: bool) -> None:
        """Called while the full scan is running (disable back/scan buttons)."""
        self._is_scanning = scanning
        self._back_btn.setEnabled(not scanning)
        self._scan_btn.setEnabled(not scanning)
        if scanning:
            self._status_lbl.setText("Scanning…")
            self._scan_btn.setText("Scanning…")
        else:
            self._scan_btn.setText(self._scan_label())

    # ── Internal helpers ─────────────────────────────────────────────

    def _populate_findings(self, ar, acq_result) -> None:
        """Populate findings panel from AnalysisResult + AcquisitionResult."""
        n  = len(ar.hotspots) if ar.hotspots else 0
        if n == 0:
            self._count_lbl.setText("No significant hotspots detected")
            conf_txt = ""
        else:
            # Confidence from average hotspot confidence
            avg_conf = sum(h.confidence for h in ar.hotspots) / n * 100
            conf_level = "High" if avg_conf >= 85 else "Medium" if avg_conf >= 65 else "Low"
            conf_col   = PALETTE['accent'] if avg_conf >= 85 else PALETTE['warning'] if avg_conf >= 65 else PALETTE['danger']
            self._count_lbl.setText(f"{n} hotspot{'s' if n != 1 else ''} detected")
            conf_txt = f"Confidence: <span style='color:{conf_col};'>{conf_level}</span>"

        self._conf_lbl.setText(conf_txt)
        self._conf_lbl.setTextFormat(Qt.RichText)

        # Signal quality from acquisition result
        snr_db = getattr(acq_result, "snr_db", None)
        if snr_db is not None:
            snr_frac   = min(max((snr_db + 10) / 50, 0.0), 1.0)
            snr_status = "good" if snr_db > 20 else "ok" if snr_db > 10 else "warn"
            self._snr_pill.set_value(f"{snr_db:.0f} dB", snr_frac, snr_status)

        sat_pct = getattr(acq_result, "saturation_pct", None)
        if sat_pct is not None:
            sat_frac   = min(sat_pct / 100, 1.0)
            sat_status = "good" if sat_pct < 1.0 else "ok" if sat_pct < 5.0 else "warn"
            self._sat_pill.set_value(f"{sat_pct:.1f}%", sat_frac, sat_status)

        drift = getattr(acq_result, "drift_estimate", None)
        if drift is not None:
            drift_frac   = min(abs(drift) / 5, 1.0)
            drift_status = "good" if abs(drift) < 0.5 else "ok" if abs(drift) < 2.0 else "warn"
            self._drift_pill.set_value(f"{drift:.2f}", drift_frac, drift_status)

        # Scan area estimated times (heuristic based on area + quality)
        self._est_time_lbl.setText("~45 sec  for hottest region")

        # Hotspot overlay on image
        if n > 0 and ar.hotspots:
            danger  = PALETTE['danger']
            warning = PALETTE['warning']
            info    = PALETTE['info']
            h_data = []
            h = ar.hotspots[0]
            drr = getattr(self._analysis_result, "delta_r_over_r", None)
            if drr is not None:
                rows, cols = drr.shape[:2]
                for j, hs in enumerate(ar.hotspots[:5]):
                    cx_f = hs.col / max(cols, 1)
                    cy_f = hs.row / max(rows, 1)
                    col  = danger if hs.confidence >= 0.8 else \
                           warning if hs.confidence >= 0.5 else info
                    h_data.append((cx_f, cy_f, str(j + 1), col))
                # Suggest ROI around hottest hotspot
                hs0    = ar.hotspots[0]
                margin = 0.15
                roi    = (max(0, hs0.col/cols - margin),
                          max(0, hs0.row/rows - margin),
                          min(1, hs0.col/cols + margin),
                          min(1, hs0.row/rows + margin))
                self._image_view.set_overlays(h_data, roi)

            # Explanation text
            hs0 = ar.hotspots[0]
            dt  = getattr(hs0, "delta_t", None) or getattr(hs0, "peak_dt", None)
            dt_str = f"{dt:.1f} K" if dt is not None else "notable"
            self._explain_lbl.setText(
                f"Hotspot #1 is {dt_str} above background with "
                f"{hs0.confidence*100:.0f}% confidence.")

        self._scan_btn.setText(self._scan_label())

    def _scan_label(self) -> str:
        area_labels = {0: "Hottest region", 1: "Selected ROI", 2: "Full view"}
        return f"Scan — {area_labels[self._area_btn_grp.checkedId()]}  →"

    def _on_area_changed(self, _idx: int) -> None:
        self._scan_btn.setText(self._scan_label())

    def _on_scan(self) -> None:
        area_map = {0: "hottest", 1: "roi", 2: "full"}
        cfg = dict(self._scan_cfg,
                   scan_area=area_map[self._area_btn_grp.checkedId()],
                   preview=False)
        self.scan_requested.emit(cfg)

    @staticmethod
    def _hline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{PALETTE['border']};")
        return f

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P    = PALETTE
        text = P['text']
        dim  = P['textDim']
        surf = P['surface']
        bdr  = P['border']
        acc  = P['accent']

        self.setStyleSheet(scaled_qss(f"""
            QWidget {{ background: {P['bg']}; }}
            QLabel {{ color: {text}; font-size: {FONT['body']}pt; background: transparent; }}
            QLabel#sectionHeader {{
                color: {dim}; font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QLabel#explainLabel {{
                color: {dim}; font-size: {FONT['label']}pt; font-style: italic;
            }}
            QRadioButton {{
                color: {text}; font-size: {FONT['body']}pt;
                spacing: 8px; background: transparent;
            }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
                border: 2px solid {bdr}; border-radius: 7px; background: {surf};
            }}
            QRadioButton::indicator:checked {{
                border-color: {acc}; background: {acc};
            }}
        """))

        # Count card
        self._count_card.setStyleSheet(
            f"#countCard {{ background:{surf}; border:1px solid {bdr}; border-radius:6px; }}")
        self._count_lbl.setStyleSheet(
            f"color:{text}; font-size:{FONT['body']}pt; font-weight:600; background:transparent;")
        self._conf_lbl.setStyleSheet(
            f"color:{dim}; font-size:{FONT['label']}pt; background:transparent;")
        self._status_lbl.setStyleSheet(
            f"color:{dim}; font-size:{FONT['label']}pt;")
        self._est_time_lbl.setStyleSheet(
            f"color:{dim}; font-size:{FONT['label']}pt; font-style:italic;")

        # Buttons
        self._back_btn.setStyleSheet(scaled_qss(f"""
            QPushButton {{
                background:{surf}; color:{dim};
                border:1px solid {bdr}; border-radius:4px;
                font-size:{FONT['body']}pt; padding:0 14px;
            }}
            QPushButton:hover {{ background:{P['surfaceHover']}; color:{text}; }}
        """))
        self._scan_btn.setStyleSheet(scaled_qss(f"""
            QPushButton {{
                background:{acc}; color:{P['textOnAccent']};
                border:none; border-radius:4px;
                font-size:{FONT['body']}pt; font-weight:700; padding:0 14px;
            }}
            QPushButton:disabled {{ background:{P['surface2']}; color:{dim}; }}
            QPushButton:hover {{ background:{P['accentHover']}; }}
        """))

        for pill in (self._snr_pill, self._sat_pill, self._drift_pill):
            pill._apply_styles()
