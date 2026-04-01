"""
ui/autoscan/results_screen.py

Screen C — Results + Next Actions

Left  : Result map image with hotspot markers
Right : Run quality card, hotspot list, recommended next actions

Emits:
  back_clicked      — "← Back" button
  new_scan_clicked  — "New AutoScan" button
  send_to_analysis  — "Send to Analysis" button (carries result)
  switch_to_manual  — "Next →" button (goes to Manual mode)
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QFrame, QSizePolicy, QScrollArea, QProgressBar,
    QCheckBox)
from PyQt5.QtCore  import Qt, pyqtSignal
from PyQt5.QtGui   import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont

from ui.theme import FONT, PALETTE, scaled_qss


# ── Hotspot card ──────────────────────────────────────────────────────

class _HotspotCard(QWidget):
    """Compact card showing a single hotspot summary."""

    def __init__(self, index: int, hotspot, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("hotspotCard")

        # Determine border color from confidence
        conf = getattr(hotspot, "confidence", 0.0)
        if conf >= 0.80:
            border_col = PALETTE['danger']
        elif conf >= 0.50:
            border_col = PALETTE['warning']
        else:
            border_col = PALETTE['info']

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(0)

        # Coloured left accent bar
        self._accent = QWidget()
        self._accent.setFixedWidth(4)
        self._accent.setStyleSheet(f"background:{border_col}; border-radius:2px 0 0 2px;")
        lay.addWidget(self._accent)

        # Card body
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(10, 8, 8, 8)
        body_lay.setSpacing(2)

        # Title
        dt     = getattr(hotspot, "delta_t",   None) or getattr(hotspot, "peak_dt",   None)
        area   = getattr(hotspot, "area_um2",  None) or getattr(hotspot, "area",      None)
        title  = f"Hotspot #{index + 1}"
        if dt is not None:
            title += f"  —  Peak +{dt:.1f} K"

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color:{PALETTE['text']}; "
            f"font-size:{FONT['body']}pt; font-weight:600; background:transparent;")

        # Detail line
        details = []
        details.append(f"{conf*100:.0f}% confidence")
        if area is not None:
            details.append(f"{area:.0f} μm²")
        detail_lbl = QLabel("  ·  ".join(details))
        detail_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; "
            f"font-size:{FONT['label']}pt; background:transparent;")

        body_lay.addWidget(title_lbl)
        body_lay.addWidget(detail_lbl)
        lay.addWidget(body, 1)

        # Background + border
        surf = PALETTE['surface']
        bdr  = PALETTE['border']
        self.setStyleSheet(
            f"#hotspotCard {{ background:{surf}; border:1px solid {bdr}; "
            f"border-left:none; border-radius:0 4px 4px 0; }}")

    def _apply_styles(self) -> None:
        surf = PALETTE['surface']
        bdr  = PALETTE['border']
        self.setStyleSheet(
            f"#hotspotCard {{ background:{surf}; border:1px solid {bdr}; "
            f"border-left:none; border-radius:0 4px 4px 0; }}")


# ── Result image view ─────────────────────────────────────────────────

class _ResultImageView(QLabel):
    """Displays the result map with optional hotspot circles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 220)
        self._hotspots: list = []   # (cx_frac, cy_frac, label, color_hex)

    def set_pixmap_with_hotspots(self, px: QPixmap, hotspots: list) -> None:
        self._hotspots = hotspots
        self.setPixmap(px.scaled(self.size(), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._hotspots:
            return
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        lw, lh = self.width(), self.height()
        iw, ih = pm.width(), pm.height()
        scale  = min(lw / max(iw, 1), lh / max(ih, 1))
        draw_w = int(iw * scale)
        draw_h = int(ih * scale)
        ox     = (lw - draw_w) // 2
        oy     = (lh - draw_h) // 2

        fnt = QFont()
        fnt.setPointSize(int(FONT.get("label", 9)))
        fnt.setBold(True)
        p.setFont(fnt)

        for (cx_f, cy_f, label, color_hex) in self._hotspots:
            cx  = ox + int(cx_f * draw_w)
            cy  = oy + int(cy_f * draw_h)
            r   = 12
            col = QColor(color_hex)
            dim = QColor(color_hex)
            dim.setAlpha(120)
            p.setBrush(QBrush(dim))
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


# ── Main widget ───────────────────────────────────────────────────────

class ResultsScreen(QWidget):
    """Screen C: results + recommended next actions."""

    back_clicked     = pyqtSignal()
    new_scan_clicked = pyqtSignal()
    send_to_analysis = pyqtSignal(object)
    switch_to_manual = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._result = None
        self._hotspot_cards: list = []

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: result map ──────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8)
        left_lay.setSpacing(4)

        self._image_view = _ResultImageView()
        left_lay.addWidget(self._image_view, 1)

        self._map_label = QLabel("Scan result")
        self._map_label.setAlignment(Qt.AlignCenter)
        left_lay.addWidget(self._map_label)

        splitter.addWidget(left)

        # ── Right: details ────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        right = QWidget()
        self._right_lay = QVBoxLayout(right)
        self._right_lay.setContentsMargins(8, 12, 12, 12)
        self._right_lay.setSpacing(14)

        # Run quality card
        self._quality_card = QWidget()
        self._quality_card.setObjectName("qualityCard")
        qc_lay = QVBoxLayout(self._quality_card)
        qc_lay.setContentsMargins(12, 10, 12, 10)
        qc_lay.setSpacing(4)

        qc_title = QLabel("Run Quality")
        qc_title.setObjectName("cardTitle")
        self._quality_score = QLabel("—")
        self._quality_score.setObjectName("qualityScore")
        self._quality_bar = QProgressBar()
        self._quality_bar.setRange(0, 100)
        self._quality_bar.setValue(0)
        self._quality_bar.setTextVisible(False)
        self._quality_bar.setFixedHeight(6)
        self._quality_notes = QLabel("")
        self._quality_notes.setObjectName("qualityNotes")
        self._quality_notes.setWordWrap(True)

        qc_lay.addWidget(qc_title)
        score_row = QHBoxLayout()
        score_row.addWidget(self._quality_score)
        score_row.addWidget(self._quality_bar, 1)
        qc_lay.addLayout(score_row)
        qc_lay.addWidget(self._quality_notes)
        self._right_lay.addWidget(self._quality_card)

        # Hotspot section header
        self._hs_header = QLabel("Hotspots")
        self._hs_header.setObjectName("sectionHeader")
        self._right_lay.addWidget(self._hs_header)

        # Hotspot cards are inserted dynamically in set_result()
        self._hs_placeholder = QLabel("No hotspot data yet")
        self._hs_placeholder.setObjectName("placeholderLabel")
        self._right_lay.addWidget(self._hs_placeholder)

        self._right_lay.addWidget(self._hline())

        # Recommended next actions
        rec_header = QLabel("Recommended Next")
        rec_header.setObjectName("sectionHeader")
        self._right_lay.addWidget(rec_header)

        self._action_zoom    = QCheckBox("Zoom scan → hotspot #1")
        self._action_trans   = QCheckBox("Transient analysis")
        self._action_export  = QCheckBox("Export to report")
        self._action_zoom.setChecked(True)
        for cb in (self._action_zoom, self._action_trans, self._action_export):
            self._right_lay.addWidget(cb)

        self._right_lay.addStretch()
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setSizes([550, 320])

        # ── Footer ────────────────────────────────────────────────
        self._back_btn     = QPushButton("← Back")
        self._new_btn      = QPushButton("New AutoScan")
        self._analysis_btn = QPushButton("Send to Analysis")
        self._next_btn     = QPushButton("Next  →")
        for btn in (self._back_btn, self._new_btn,
                    self._analysis_btn, self._next_btn):
            btn.setFixedHeight(32)

        self._back_btn.clicked.connect(self.back_clicked)
        self._new_btn.clicked.connect(self.new_scan_clicked)
        self._analysis_btn.clicked.connect(self._on_send_to_analysis)
        self._next_btn.clicked.connect(self.switch_to_manual)

        footer = QHBoxLayout()
        footer.addWidget(self._back_btn)
        footer.addWidget(self._new_btn)
        footer.addStretch()
        footer.addWidget(self._analysis_btn)
        footer.addWidget(self._next_btn)

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

    def set_result(self, result) -> None:
        """Populate the screen from a ScanResult or AcquisitionResult."""
        self._result = result

        # Try to get map data
        _dt_map_a  = getattr(result, "dt_map",           None)
        _dt_map_b  = getattr(result, "delta_t",         None)
        dt_map     = _dt_map_a  if _dt_map_a  is not None else _dt_map_b

        _drr_map_a = getattr(result, "drr_map",          None)
        _drr_map_b = getattr(result, "delta_r_over_r",   None)
        drr_map    = _drr_map_a if _drr_map_a is not None else _drr_map_b

        display_map = dt_map if dt_map is not None else drr_map
        label_txt   = "ΔT map  (°C)" if dt_map is not None else "ΔR/R map"

        # Render map image
        hotspot_data = []
        ar = None
        if display_map is not None:
            try:
                from acquisition.processing import apply_colormap
                img = apply_colormap(display_map, colormap_name="inferno")
                h, w = img.shape[:2]
                qimg = QImage(img.tobytes(), w, h, w * 3, QImage.Format_RGB888)
                px   = QPixmap.fromImage(qimg)

                # Run analysis for hotspot positions
                try:
                    from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig
                    ar  = ThermalAnalysisEngine(AnalysisConfig()).run(display_map)
                    rows, cols = display_map.shape[:2]
                    danger  = PALETTE['danger']
                    warning = PALETTE['warning']
                    info    = PALETTE['info']
                    for j, hs in enumerate(ar.hotspots[:6]):
                        col = danger if hs.confidence >= 0.8 else \
                              warning if hs.confidence >= 0.5 else info
                        hotspot_data.append((hs.col / max(cols, 1),
                                             hs.row / max(rows, 1),
                                             str(j + 1), col))
                except Exception:
                    pass

                self._image_view.set_pixmap_with_hotspots(px, hotspot_data)
                self._map_label.setText(label_txt)
            except Exception:
                self._image_view.setText("Map rendering unavailable")

        # Populate run quality
        if ar is not None:
            score    = getattr(ar, "score", None)
            verdict  = getattr(ar, "verdict", None)
            if score is not None:
                pct = int(score * 100) if score <= 1.0 else int(score)
                self._quality_score.setText(f"{pct}/100")
                self._quality_bar.setValue(pct)
                level = "Excellent" if pct >= 90 else \
                        "Good"      if pct >= 75 else \
                        "Fair"      if pct >= 55 else "Poor"
                self._quality_notes.setText(level)
        else:
            # Fallback from result attributes
            score = getattr(result, "quality_score", None)
            if score is not None:
                pct = int(score * 100) if score <= 1.0 else int(score)
                self._quality_score.setText(f"{pct}/100")
                self._quality_bar.setValue(pct)

        # Build hotspot cards
        self._clear_hotspot_cards()
        hotspots = ar.hotspots if (ar and ar.hotspots) else []
        if hotspots:
            self._hs_placeholder.setVisible(False)
            insert_idx = self._right_lay.indexOf(self._hs_placeholder)
            for i, hs in enumerate(hotspots[:6]):
                card = _HotspotCard(i, hs)
                self._hotspot_cards.append(card)
                self._right_lay.insertWidget(insert_idx + i, card)
        else:
            self._hs_placeholder.setVisible(True)
            self._hs_placeholder.setText("No hotspots detected")

        # Update action labels
        if hotspots:
            self._action_zoom.setText(f"Zoom scan → hotspot #1")
            self._action_zoom.setEnabled(True)

    # ── Internal ─────────────────────────────────────────────────────

    def _clear_hotspot_cards(self) -> None:
        for card in self._hotspot_cards:
            self._right_lay.removeWidget(card)
            card.deleteLater()
        self._hotspot_cards.clear()

    def _on_send_to_analysis(self) -> None:
        self.send_to_analysis.emit(self._result)

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
        danger = P['danger']

        self.setStyleSheet(scaled_qss(f"""
            QWidget {{ background: {P['bg']}; }}
            QLabel {{ color:{text}; font-size:{FONT['body']}pt; background:transparent; }}
            QLabel#sectionHeader {{
                color:{dim}; font-size:{FONT['label']}pt; font-weight:600;
            }}
            QLabel#placeholderLabel {{ color:{dim}; font-style:italic; }}
            QLabel#qualityScore {{
                color:{acc}; font-size:{FONT['title']}pt; font-weight:700;
            }}
            QLabel#qualityNotes {{ color:{dim}; font-size:{FONT['label']}pt; }}
            QCheckBox {{
                color:{text}; font-size:{FONT['body']}pt; spacing:8px;
                background:transparent;
            }}
            QCheckBox::indicator {{
                width:14px; height:14px;
                border:2px solid {bdr}; border-radius:3px; background:{surf};
            }}
            QCheckBox::indicator:checked {{
                border-color:{acc}; background:{acc};
            }}
        """))

        # Quality card
        self._quality_card.setStyleSheet(
            f"#qualityCard {{ background:{surf}; border:1px solid {bdr}; border-radius:6px; }}")
        self._quality_bar.setStyleSheet(f"""
            QProgressBar {{ background:{P['surface2']};
                            border-radius:3px; }}
            QProgressBar::chunk {{ background:{acc}; border-radius:3px; }}
        """)

        # Map label
        self._map_label.setStyleSheet(
            f"color:{dim}; font-size:{FONT['label']}pt; background:transparent;")

        # Footer buttons
        _back_style = scaled_qss(f"""
            QPushButton {{
                background:{surf}; color:{dim};
                border:1px solid {bdr}; border-radius:4px;
                font-size:{FONT['body']}pt; padding:0 14px;
            }}
            QPushButton:hover {{ background:{P['surfaceHover']}; color:{text}; }}
        """)
        _acc_style = scaled_qss(f"""
            QPushButton {{
                background:{acc}; color:{P['textOnAccent']};
                border:none; border-radius:4px;
                font-size:{FONT['body']}pt; font-weight:700; padding:0 14px;
            }}
            QPushButton:hover {{ background:{P['accentHover']}; }}
        """)
        _analysis_style = scaled_qss(f"""
            QPushButton {{
                background:{P['info']}33; color:{P['info']};
                border:1px solid {P['info']}66; border-radius:4px;
                font-size:{FONT['body']}pt; font-weight:600; padding:0 14px;
            }}
            QPushButton:hover {{ background:{P['info']}55; }}
        """)
        self._back_btn.setStyleSheet(_back_style)
        self._new_btn.setStyleSheet(_back_style)
        self._analysis_btn.setStyleSheet(_analysis_style)
        self._next_btn.setStyleSheet(_acc_style)

        # Re-style existing hotspot cards
        for card in self._hotspot_cards:
            card._apply_styles()
