"""
acquisition/analysis_tab.py

AnalysisTab — Pass / Warning / Fail thermal analysis results.

Layout
------
Left   : Threshold & verdict-rule controls, Run Analysis button
Centre : Annotated overlay (greyscale base + coloured hotspot contours
         + verdict badge)
Right  : Verdict banner, summary stats, per-hotspot table,
         export buttons (PNG, CSV, add to PDF report)
"""

from __future__ import annotations
import csv, os, time
from typing import Optional

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QSplitter,
    QSizePolicy, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QFrame, QComboBox)
from PyQt5.QtCore  import Qt, pyqtSignal, QTimer
from PyQt5.QtGui   import QImage, QPixmap, QPainter, QColor, QFont, QPen

from .analysis import (ThermalAnalysisEngine, AnalysisConfig,
                        AnalysisResult, Hotspot,
                        VERDICT_PASS, VERDICT_WARNING, VERDICT_FAIL)


# ------------------------------------------------------------------ #
#  Verdict banner                                                      #
# ------------------------------------------------------------------ #

class VerdictBanner(QWidget):
    """Large, colour-coded PASS / WARNING / FAIL indicator."""

    STYLES = {
        VERDICT_PASS:    ("PASS",    "#00d479", "#0d2a1a", "#1a4a2a"),
        VERDICT_WARNING: ("WARNING", "#ffb300", "#2a1e00", "#4a3800"),
        VERDICT_FAIL:    ("FAIL",    "#ff3b3b", "#2a0d0d", "#4a1a1a"),
        "NONE":          ("—",       "#333333", "#111111", "#1a1a1a"),
    }

    def __init__(self):
        super().__init__()
        self.setFixedHeight(72)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._outer = QWidget()
        ol = QHBoxLayout(self._outer)
        ol.setContentsMargins(20, 0, 20, 0)

        self._icon  = QLabel("—")
        self._icon.setStyleSheet(
            "font-size:44pt; font-weight:bold; font-family:Menlo,monospace;")
        self._icon.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._sub = QLabel("Run analysis to see verdict")
        self._sub.setStyleSheet("font-size:14pt; color:#555;")
        self._sub.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self._sub.setWordWrap(False)

        ol.addWidget(self._icon, 1)
        ol.addWidget(self._sub)
        lay.addWidget(self._outer)
        self._set("NONE", "")

    def _set(self, verdict: str, subtitle: str):
        _, fg, bg, border = self.STYLES.get(verdict, self.STYLES["NONE"])
        self._outer.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; border-radius:4px;")
        self._icon.setText(verdict if verdict != "NONE" else "—")
        self._icon.setStyleSheet(
            f"font-size:44pt; font-weight:bold; "
            f"font-family:Menlo,monospace; color:{fg};")
        self._sub.setText(subtitle)
        self._sub.setStyleSheet(f"font-size:14pt; color:{fg}88;")

    def update_verdict(self, result: AnalysisResult):
        n  = result.n_hotspots
        pk = result.max_peak_k
        hs = "hotspot" if n == 1 else "hotspots"
        if result.verdict == VERDICT_PASS:
            sub = f"No hotspots above threshold ({result.threshold_k:.1f} °C)"
        elif result.verdict == VERDICT_WARNING:
            sub = f"{n} {hs} detected  ·  peak {pk:.1f} °C"
        else:
            sub = f"{n} {hs} detected  ·  peak {pk:.1f} °C"
        self._set(result.verdict, sub)

    def reset(self):
        self._set("NONE", "Run analysis to see verdict")


# ------------------------------------------------------------------ #
#  Overlay canvas                                                      #
# ------------------------------------------------------------------ #

class OverlayCanvas(QWidget):
    hotspot_hovered = pyqtSignal(int)   # hotspot index (1-based), -1 = none

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#0d0d0d;")
        self.setMouseTracking(True)
        self._pixmap = None
        self._result: Optional[AnalysisResult] = None

    def update_result(self, result: AnalysisResult):
        self._result = result
        if result and result.overlay_rgb is not None:
            rgb = result.overlay_rgb
            h, w = rgb.shape[:2]
            qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qi)
        else:
            self._pixmap = None
        self.update()

    def clear(self):
        self._pixmap = None
        self._result = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(13, 13, 13))
        if self._pixmap is None:
            p.setPen(QColor(40, 40, 40))
            p.setFont(QFont("Helvetica", 18))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No analysis result\n\nPress  ▶  Run Analysis")
            p.end()
            return
        W, H   = self.width(), self.height()
        PAD    = 8
        scaled = self._pixmap.scaled(
            W - 2*PAD, H - 2*PAD,
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ox = (W - scaled.width())  // 2
        oy = (H - scaled.height()) // 2
        p.drawPixmap(ox, oy, scaled)
        p.end()

    def save_png(self, path: str):
        if self._pixmap:
            self._pixmap.save(path)
            return True
        return False


# ------------------------------------------------------------------ #
#  Hotspot table                                                       #
# ------------------------------------------------------------------ #

class HotspotTable(QTableWidget):

    COLS = ["#", "Peak ΔT (°C)", "Mean ΔT (°C)", "Area (px)", "Area (μm²)",
            "Centroid", "Severity"]

    def __init__(self):
        super().__init__(0, len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QTableWidget {
                background:#141414; alternate-background-color:#181818;
                gridline-color:#222; border:none;
                font-family:Menlo,monospace; font-size:12pt;
            }
            QHeaderView::section {
                background:#1a1a1a; color:#555;
                padding:3px 6px; border:none;
                border-bottom:1px solid #2a2a2a;
                font-size:13pt; letter-spacing:1px;
            }
        """)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)

    SEVERITY_COLORS = {
        "fail":    ("#4a1010", "#ff3b3b"),
        "warning": ("#2a1e00", "#ffb300"),
    }

    def update_hotspots(self, hotspots: list):
        self.setRowCount(0)
        for h in hotspots:
            r = self.rowCount()
            self.insertRow(r)
            bg, fg = self.SEVERITY_COLORS.get(h.severity, ("#1a1a1a", "#888"))

            def cell(text, align=Qt.AlignCenter):
                it = QTableWidgetItem(text)
                it.setTextAlignment(align)
                it.setForeground(QColor(fg))
                it.setBackground(QColor(bg))
                return it

            area_um2 = f"{h.area_um2:.1f}" if h.area_um2 > 0 else "—"
            cx, cy   = h.centroid

            self.setItem(r, 0, cell(str(h.index)))
            self.setItem(r, 1, cell(f"{h.peak_k:.2f}"))
            self.setItem(r, 2, cell(f"{h.mean_k:.2f}"))
            self.setItem(r, 3, cell(f"{h.area_px:,}"))
            self.setItem(r, 4, cell(area_um2))
            self.setItem(r, 5, cell(f"({cx}, {cy})"))
            self.setItem(r, 6, cell(h.severity.upper()))
            self.setRowHeight(r, 24)


# ------------------------------------------------------------------ #
#  Main tab                                                            #
# ------------------------------------------------------------------ #

class AnalysisTab(QWidget):
    """
    Pass / Warning / Fail thermal analysis.

    Can be driven two ways:
      1. push_result(dt_map, drr_map, base_image)  — called by AcquireTab /
         LiveTab after acquisition
      2. User clicks "▶ Run Analysis" to reprocess with new thresholds
    """

    analysis_complete = pyqtSignal(object)   # AnalysisResult

    def __init__(self):
        super().__init__()
        self._engine = ThermalAnalysisEngine()
        self._result: Optional[AnalysisResult] = None
        self._dt_map:    Optional[np.ndarray] = None
        self._drr_map:   Optional[np.ndarray] = None
        self._base_img:  Optional[np.ndarray] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._build_controls())
        body.addWidget(self._build_canvas())
        body.addWidget(self._build_results())
        body.setSizes([230, 780, 290])
        root.addWidget(body, 1)

    # ---------------------------------------------------------------- #
    #  Toolbar                                                          #
    # ---------------------------------------------------------------- #

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            "background:#151515; border-bottom:1px solid #1e1e1e;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self._run_btn    = QPushButton("▶  Run Analysis")
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(30)
        self._run_btn.clicked.connect(self._run)

        self._clear_btn  = QPushButton("✕  Clear")
        self._clear_btn.setFixedHeight(30)
        self._clear_btn.clicked.connect(self._clear)

        self._auto_cb    = QCheckBox("Auto-run after acquisition")
        self._auto_cb.setChecked(True)
        self._auto_cb.setStyleSheet("font-size:14pt; color:#555;")

        lay.addWidget(self._run_btn)
        lay.addWidget(self._clear_btn)
        lay.addWidget(self._auto_cb)
        lay.addStretch()

        # Source indicator
        self._source_lbl = self._badge("No data", "#1a1a1a", "#333")
        lay.addWidget(self._source_lbl)

        return bar

    def _badge(self, text, bg, fg) -> QLabel:
        l = QLabel(text)
        l.setFixedHeight(24)
        l.setStyleSheet(
            f"background:{bg}; color:{fg}; padding:0 10px; "
            f"border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")
        return l

    # ---------------------------------------------------------------- #
    #  Left: controls                                                   #
    # ---------------------------------------------------------------- #

    def _build_controls(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(210); w.setMaximumWidth(260)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        from ui.help import HelpButton, help_label

        # ---- Threshold ----
        th_box = QGroupBox("Detection Threshold")
        tl = QGridLayout(th_box)
        tl.setSpacing(6)

        self._thresh_spin = QDoubleSpinBox()
        self._thresh_spin.setRange(0.1, 200.0)
        self._thresh_spin.setValue(5.0)
        self._thresh_spin.setSuffix(" °C")
        self._thresh_spin.setSingleStep(0.5)
        self._thresh_spin.setFixedWidth(100)

        self._use_dt_cb = QCheckBox("Use ΔT map (°C)")
        self._use_dt_cb.setChecked(True)

        tl.addWidget(help_label("Minimum ΔT", "threshold_k"), 0, 0)
        tl.addWidget(self._thresh_spin,        0, 1)
        tl.addWidget(self._use_dt_cb,          1, 0, 1, 2)
        lay.addWidget(th_box)

        # ---- Pass / Fail rules ----
        pf_box = QGroupBox("Pass / Fail Rules")
        pl = QGridLayout(pf_box)
        pl.setSpacing(5)

        def dbl(val, lo=0.0, hi=500.0, suf=""):
            s = QDoubleSpinBox()
            s.setRange(lo, hi); s.setValue(val)
            if suf: s.setSuffix(suf)
            s.setFixedWidth(90)
            return s

        def sp(val, lo=0, hi=999):
            s = QSpinBox()
            s.setRange(lo, hi); s.setValue(val)
            s.setFixedWidth(90)
            return s

        self._fail_count  = sp(1,   lo=0)
        self._fail_peak   = dbl(10.0, suf=" °C")
        self._fail_area   = dbl(5.0,  lo=0.0, hi=100.0, suf=" %")
        self._warn_count  = sp(1,   lo=0)
        self._warn_peak   = dbl(5.0,  suf=" °C")
        self._warn_area   = dbl(2.0,  lo=0.0, hi=100.0, suf=" %")

        pf_rows = [
            ("FAIL if count ≥",  self._fail_count,  "fail_hotspot_count"),
            ("FAIL if peak ≥",   self._fail_peak,   "fail_peak_k"),
            ("FAIL if area ≥",   self._fail_area,   "fail_area_fraction"),
            ("WARN if count ≥",  self._warn_count,  "fail_hotspot_count"),
            ("WARN if peak ≥",   self._warn_peak,   "warn_peak_k"),
            ("WARN if area ≥",   self._warn_area,   "fail_area_fraction"),
        ]
        for row, (lbl, widget, topic) in enumerate(pf_rows):
            pl.addWidget(help_label(lbl, topic), row, 0)
            pl.addWidget(widget, row, 1)

        lay.addWidget(pf_box)

        # ---- Morphology ----
        mo_box = QGroupBox("Noise Filtering")
        ml = QGridLayout(mo_box)
        ml.setSpacing(5)

        self._open_radius  = sp(2, lo=0, hi=20)
        self._close_radius = sp(4, lo=0, hi=20)
        self._min_area_px  = sp(20, lo=1, hi=9999)

        for row, (lbl, widget) in enumerate([
            ("Open radius (px)",  self._open_radius),
            ("Close radius (px)", self._close_radius),
            ("Min area (px)",     self._min_area_px),
        ]):
            l = QLabel(lbl)
            l.setStyleSheet("font-size:12pt; color:#555;")
            ml.addWidget(l, row, 0)
            ml.addWidget(widget, row, 1)

        lay.addWidget(mo_box)

        # ---- Presets ----
        pre_box = QGroupBox("Quick Presets")
        prlay = QVBoxLayout(pre_box)
        for label, fn in [
            ("PCB / Trace heating",    self._preset_pcb),
            ("Semiconductor hotspot",  self._preset_semi),
            ("EV power module",        self._preset_ev),
            ("Sensitive (research)",   self._preset_research),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(fn)
            prlay.addWidget(b)
        lay.addWidget(pre_box)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Centre: canvas                                                   #
    # ---------------------------------------------------------------- #

    def _build_canvas(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self._canvas = OverlayCanvas()
        lay.addWidget(self._canvas)
        return w

    # ---------------------------------------------------------------- #
    #  Right: results                                                   #
    # ---------------------------------------------------------------- #

    def _build_results(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(250); w.setMaximumWidth(340)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # Verdict banner
        self._banner = VerdictBanner()
        lay.addWidget(self._banner)

        # Summary stats
        stats_box = QGroupBox("Summary")
        sg = QGridLayout(stats_box)
        sg.setSpacing(4)
        self._stat_vals = {}
        for r, (key, lbl) in enumerate([
            ("hotspots",  "Hotspots"),
            ("peak",      "Peak ΔT"),
            ("area_frac", "Hotspot area"),
            ("map_mean",  "Map mean ΔT"),
            ("map_std",   "Map std dev"),
            ("threshold", "Threshold"),
        ]):
            sg.addWidget(self._sub(lbl), r, 0)
            v = QLabel("—")
            v.setAlignment(Qt.AlignRight)
            v.setStyleSheet(
                "font-family:Menlo,monospace; font-size:13pt; color:#aaa;")
            sg.addWidget(v, r, 1)
            self._stat_vals[key] = v
        lay.addWidget(stats_box)

        # Hotspot table
        lay.addWidget(self._sub("Hotspot Detail"))
        self._table = HotspotTable()
        lay.addWidget(self._table, 1)

        # Export
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#222;")
        lay.addWidget(sep)

        btn_row = QHBoxLayout()
        self._save_png_btn = QPushButton("🖼  Save PNG")
        self._save_csv_btn = QPushButton("📊  Save CSV")
        self._add_rpt_btn  = QPushButton("📄  Add to Report")
        for b in [self._save_png_btn, self._save_csv_btn, self._add_rpt_btn]:
            b.setFixedHeight(28); b.setEnabled(False)
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._save_png_btn.clicked.connect(self._export_png)
        self._save_csv_btn.clicked.connect(self._export_csv)
        self._add_rpt_btn.clicked.connect(self._add_to_report)

        return w

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def push_result(self, dt_map: Optional[np.ndarray],
                    drr_map: Optional[np.ndarray],
                    base_image: Optional[np.ndarray] = None,
                    source_label: str = "Acquisition"):
        """Feed new maps into the tab. Runs automatically if auto-run is on."""
        self._dt_map   = dt_map
        self._drr_map  = drr_map
        self._base_img = base_image
        self._source_lbl.setText(source_label)
        self._source_lbl.setStyleSheet(
            "background:#1a2a1a; color:#00d4aa; padding:0 10px; "
            "border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")
        if self._auto_cb.isChecked():
            self._run()

    def get_result(self) -> Optional[AnalysisResult]:
        return self._result

    # ---------------------------------------------------------------- #
    #  Run / Clear                                                      #
    # ---------------------------------------------------------------- #

    def _build_config(self) -> AnalysisConfig:
        return AnalysisConfig(
            threshold_k         = self._thresh_spin.value(),
            use_dt              = self._use_dt_cb.isChecked(),
            open_radius         = self._open_radius.value(),
            close_radius        = self._close_radius.value(),
            min_area_px         = self._min_area_px.value(),
            fail_hotspot_count  = self._fail_count.value(),
            fail_peak_k         = self._fail_peak.value(),
            fail_area_fraction  = self._fail_area.value() / 100.0,
            warn_hotspot_count  = self._warn_count.value(),
            warn_peak_k         = self._warn_peak.value(),
            warn_area_fraction  = self._warn_area.value() / 100.0,
        )

    def _run(self):
        if self._dt_map is None and self._drr_map is None:
            self._banner.reset()
            return

        cfg = self._build_config()
        self._engine.update_config(cfg)

        result = self._engine.run(
            dt_map    = self._dt_map,
            drr_map   = self._drr_map,
            base_image= self._base_img)

        self._result = result
        self._canvas.update_result(result)
        self._banner.update_verdict(result)
        self._update_stats(result)
        self._table.update_hotspots(result.hotspots)

        for b in [self._save_png_btn, self._save_csv_btn, self._add_rpt_btn]:
            b.setEnabled(True)

        self.analysis_complete.emit(result)

        # Log to main app
        try:
            from ui.app_signals import signals
            signals.log_message.emit(
                f"Analysis: {result.verdict}  ·  "
                f"{result.n_hotspots} hotspot(s)  ·  "
                f"peak {result.max_peak_k:.1f} °C  ·  "
                f"threshold {result.threshold_k:.1f} °C")
        except Exception:
            pass

    def _clear(self):
        self._result   = None
        self._dt_map   = None
        self._drr_map  = None
        self._base_img = None
        self._canvas.clear()
        self._banner.reset()
        self._table.setRowCount(0)
        for v in self._stat_vals.values():
            v.setText("—")
        for b in [self._save_png_btn, self._save_csv_btn, self._add_rpt_btn]:
            b.setEnabled(False)
        self._source_lbl.setText("No data")
        self._source_lbl.setStyleSheet(
            "background:#1a1a1a; color:#333; padding:0 10px; "
            "border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")

    # ---------------------------------------------------------------- #
    #  Stats update                                                     #
    # ---------------------------------------------------------------- #

    def _update_stats(self, r: AnalysisResult):
        self._stat_vals["hotspots"].setText(str(r.n_hotspots))
        self._stat_vals["peak"].setText(
            f"{r.max_peak_k:.2f} °C" if r.n_hotspots else "—")
        self._stat_vals["area_frac"].setText(
            f"{r.area_fraction * 100:.2f} %")
        self._stat_vals["map_mean"].setText(f"{r.map_mean_k:.3f} °C")
        self._stat_vals["map_std"].setText(f"{r.map_std_k:.3f} °C")
        self._stat_vals["threshold"].setText(f"{r.threshold_k:.1f} °C")

        # Colour the stat values by verdict
        colors = {VERDICT_PASS: "#00d479",
                  VERDICT_WARNING: "#ffb300",
                  VERDICT_FAIL: "#ff3b3b"}
        c = colors.get(r.verdict, "#aaa")
        for key in ["hotspots", "peak", "area_frac"]:
            self._stat_vals[key].setStyleSheet(
                f"font-family:Menlo,monospace; font-size:13pt; color:{c};")

    # ---------------------------------------------------------------- #
    #  Presets                                                          #
    # ---------------------------------------------------------------- #

    def _apply_preset(self, thresh, fail_count, fail_peak,
                      fail_area, warn_count, warn_peak, warn_area):
        self._thresh_spin.setValue(thresh)
        self._fail_count.setValue(fail_count)
        self._fail_peak.setValue(fail_peak)
        self._fail_area.setValue(fail_area)
        self._warn_count.setValue(warn_count)
        self._warn_peak.setValue(warn_peak)
        self._warn_area.setValue(warn_area)

    def _preset_pcb(self):
        # PCB traces — moderate sensitivity, fail on significant heating
        self._apply_preset(
            thresh=3.0, fail_count=1, fail_peak=15.0, fail_area=3.0,
            warn_count=1, warn_peak=5.0, warn_area=1.0)

    def _preset_semi(self):
        # Semiconductor die — tight thresholds, any hotspot is notable
        self._apply_preset(
            thresh=2.0, fail_count=1, fail_peak=8.0, fail_area=2.0,
            warn_count=1, warn_peak=3.0, warn_area=0.5)

    def _preset_ev(self):
        # EV power module — higher absolute temperatures expected
        self._apply_preset(
            thresh=8.0, fail_count=1, fail_peak=30.0, fail_area=5.0,
            warn_count=1, warn_peak=15.0, warn_area=2.0)

    def _preset_research(self):
        # Research / discovery mode — sensitive, no automatic fail
        self._apply_preset(
            thresh=1.0, fail_count=0, fail_peak=0.0, fail_area=0.0,
            warn_count=1, warn_peak=2.0, warn_area=0.5)

    # ---------------------------------------------------------------- #
    #  Export                                                           #
    # ---------------------------------------------------------------- #

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Analysis Image", "analysis.png",
            "PNG images (*.png);;All files (*)")
        if path and self._canvas.save_png(path):
            QMessageBox.information(self, "Saved", f"Image saved to:\n{path}")

    def _export_csv(self):
        if not self._result or not self._result.hotspots:
            QMessageBox.information(self, "No Data", "No hotspots to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Hotspot Data", "hotspots.csv",
            "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["index", "peak_dt_c", "mean_dt_c",
                            "area_px", "area_um2",
                            "centroid_x", "centroid_y", "severity"])
                for h in self._result.hotspots:
                    cx, cy = h.centroid
                    w.writerow([h.index, f"{h.peak_k:.4f}",
                                f"{h.mean_k:.4f}", h.area_px,
                                f"{h.area_um2:.2f}", cx, cy, h.severity])
            # Also write summary row
            r = self._result
            with open(path.replace(".csv", "_summary.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["verdict", "n_hotspots", "max_peak_c",
                            "area_fraction_pct", "map_mean_c",
                            "map_std_c", "threshold_c", "timestamp"])
                w.writerow([r.verdict, r.n_hotspots,
                            f"{r.max_peak_k:.4f}",
                            f"{r.area_fraction*100:.3f}",
                            f"{r.map_mean_k:.4f}",
                            f"{r.map_std_k:.4f}",
                            f"{r.threshold_k:.2f}",
                            r.timestamp_str])
            QMessageBox.information(
                self, "Exported", f"Saved to:\n{path}\n{path.replace('.csv','_summary.csv')}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _add_to_report(self):
        """Store the current analysis result so the PDF report includes it."""
        if not self._result:
            return
        try:
            from hardware.app_state import app_state
            app_state.active_analysis = self._result
            QMessageBox.information(
                self, "Added to Report",
                "Analysis result will be included in the next PDF report.\n\n"
                "Generate a report from the DATA tab.")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    # ---------------------------------------------------------------- #
    #  Helper                                                           #
    # ---------------------------------------------------------------- #

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
