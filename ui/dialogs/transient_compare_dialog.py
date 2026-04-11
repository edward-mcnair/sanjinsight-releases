"""
ui/dialogs/transient_compare_dialog.py

Modal dialog for comparing two transient sessions side by side.

Shows:
  • Session summary header (metadata for both)
  • Grid-difference warning (if delay grids differ)
  • Full-frame overlaid trace chart
  • Side-by-side metrics table with delta column
  • Per-ROI trace overlays (matched labels only)
  • Unmatched ROI notes
  • Export comparison summary (CSV / JSON)

Entry point: ``TransientCompareDialog.run(session_mgr, current_uid, parent)``
"""

from __future__ import annotations

import csv
import json
import logging
import time
from typing import Optional, List

import numpy as np

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QComboBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSizePolicy, QWidget, QScrollArea,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from ui.theme import FONT, PALETTE, MONO_FONT
from ui.icons import set_btn_icon

log = logging.getLogger(__name__)


class TransientCompareDialog(QDialog):
    """Modal dialog comparing two transient sessions."""

    def __init__(self, session_mgr, current_uid: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Compare Transient Sessions")
        self.setMinimumSize(900, 650)
        self.resize(1050, 750)

        self._mgr = session_mgr
        self._current_uid = current_uid
        self._comparison = None  # ComparisonResult once computed

        # Collect transient session metas
        self._transient_metas = [
            m for m in session_mgr.all_metas()
            if (getattr(m, "result_type", "") or "") == "transient"
            and getattr(m, "has_drr", False)
        ]

        self._build_ui()
        self._pre_select()

    # ---------------------------------------------------------------- #
    #  UI construction                                                  #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Session pickers ───────────────────────────────────────────
        picker_box = QGroupBox("Select Sessions")
        pl = QGridLayout(picker_box)
        pl.setSpacing(8)

        pl.addWidget(self._sub("Session A:"), 0, 0)
        self._combo_a = QComboBox()
        self._combo_a.setMinimumWidth(350)
        pl.addWidget(self._combo_a, 0, 1)

        pl.addWidget(self._sub("Session B:"), 1, 0)
        self._combo_b = QComboBox()
        self._combo_b.setMinimumWidth(350)
        pl.addWidget(self._combo_b, 1, 1)

        self._compare_btn = QPushButton("Compare")
        set_btn_icon(self._compare_btn, "fa5s.balance-scale")
        self._compare_btn.setObjectName("primary")
        self._compare_btn.setFixedHeight(32)
        self._compare_btn.clicked.connect(self._on_compare)
        pl.addWidget(self._compare_btn, 0, 2, 2, 1)

        # Populate combos
        for m in self._transient_metas:
            display = f"{m.label or m.uid}  ({m.n_frames}f, {m.timestamp_str})"
            self._combo_a.addItem(display, m.uid)
            self._combo_b.addItem(display, m.uid)

        root.addWidget(picker_box)

        # ── Grid-difference banner ────────────────────────────────────
        self._grid_banner = QLabel("")
        self._grid_banner.setWordWrap(True)
        self._grid_banner.setStyleSheet(
            f"background:{PALETTE['surface']}; color:{PALETTE['warning']}; "
            f"padding:6px; border-radius:4px; "
            f"font-size:{FONT['caption']}pt;")
        self._grid_banner.setVisible(False)
        root.addWidget(self._grid_banner)

        # ── Scrollable content area ───────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._content = QWidget()
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(10)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        # Placeholder
        self._placeholder = QLabel("Select two sessions and click Compare")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['body']}pt; "
            f"padding:40px;")
        self._content_lay.addWidget(self._placeholder)

        # ── Bottom buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("Export Comparison…")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._export_btn.setEnabled(False)
        self._export_btn.setFixedHeight(30)
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _pre_select(self):
        """Pre-select current session in combo A if it's transient."""
        if self._current_uid:
            for i in range(self._combo_a.count()):
                if self._combo_a.itemData(i) == self._current_uid:
                    self._combo_a.setCurrentIndex(i)
                    # Select the next different session for B
                    for j in range(self._combo_b.count()):
                        if self._combo_b.itemData(j) != self._current_uid:
                            self._combo_b.setCurrentIndex(j)
                            break
                    break

    # ---------------------------------------------------------------- #
    #  Compare                                                          #
    # ---------------------------------------------------------------- #

    def _on_compare(self):
        uid_a = self._combo_a.currentData()
        uid_b = self._combo_b.currentData()
        if not uid_a or not uid_b:
            QMessageBox.warning(self, "Compare", "Select two sessions.")
            return
        if uid_a == uid_b:
            QMessageBox.warning(self, "Compare",
                                "Please select two different sessions.")
            return

        # Load sessions
        session_a = self._mgr.load(uid_a)
        session_b = self._mgr.load(uid_b)
        if session_a is None or session_b is None:
            QMessageBox.warning(self, "Compare",
                                "Could not load one or both sessions.")
            return

        # Reconstruct TransientResults
        from acquisition.transient_pipeline import TransientResult
        result_a = self._session_to_result(session_a)
        result_b = self._session_to_result(session_b)

        if result_a.delta_r_cube is None or result_b.delta_r_cube is None:
            QMessageBox.warning(self, "Compare",
                                "One or both sessions have no ΔR/R cube data.")
            return

        # Extract ROI signals
        from acquisition.roi_extraction import extract_roi_signals
        try:
            from acquisition.roi_model import roi_model
            rois = roi_model.rois
        except ImportError:
            rois = []

        roi_a = extract_roi_signals(result_a.delta_r_cube, rois)
        roi_b = extract_roi_signals(result_b.delta_r_cube, rois)

        # Compute comparison
        from acquisition.transient_comparison import compare_transient_sessions
        label_a = getattr(session_a.meta, "label", "") or session_a.meta.uid
        label_b = getattr(session_b.meta, "label", "") or session_b.meta.uid

        self._comparison = compare_transient_sessions(
            result_a, result_b,
            label_a=label_a, label_b=label_b,
            uid_a=uid_a, uid_b=uid_b,
            roi_signals_a=roi_a, roi_signals_b=roi_b,
        )

        self._display_comparison()

    @staticmethod
    def _session_to_result(session) -> "TransientResult":
        from acquisition.transient_pipeline import TransientResult
        cp = getattr(session.meta, "cube_params", None) or {}
        return TransientResult(
            delta_r_cube=session.delta_r_cube,
            reference=session.reference,
            delay_times_s=session.delay_times_s,
            raw_cube=None,
            n_delays=cp.get("n_delays", 0),
            n_averages=cp.get("n_averages", 0),
            pulse_dur_us=cp.get("pulse_dur_us", 0.0),
            delay_start_s=cp.get("delay_start_s", 0.0),
            delay_end_s=cp.get("delay_end_s", 0.0),
            exposure_us=session.meta.exposure_us,
            gain_db=session.meta.gain_db,
            duration_s=session.meta.duration_s,
            hw_triggered=cp.get("hw_triggered", False),
        )

    # ---------------------------------------------------------------- #
    #  Display comparison results                                       #
    # ---------------------------------------------------------------- #

    def _display_comparison(self):
        cr = self._comparison
        if cr is None:
            return

        # Clear previous content
        self._clear_content()

        # Grid banner
        if cr.grids_differ:
            self._grid_banner.setText(
                f"⚠  Delay grids differ: {cr.grid_note}")
            self._grid_banner.setVisible(True)
        else:
            self._grid_banner.setVisible(False)

        # ── Session summary ───────────────────────────────────────────
        summ_box = QGroupBox("Session Summary")
        sl = QGridLayout(summ_box)
        sl.setSpacing(4)
        headers = ["", "Session A", "Session B"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setStyleSheet(
                f"font-weight:bold; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['textSub']};")
            sl.addWidget(lbl, 0, col)

        rows = [
            ("Label",     cr.summary_a.label,     cr.summary_b.label),
            ("Delays",    str(cr.summary_a.n_delays), str(cr.summary_b.n_delays)),
            ("Averages",  str(cr.summary_a.n_averages), str(cr.summary_b.n_averages)),
            ("Delay range",
             f"{cr.summary_a.delay_start_s*1e3:.3f}–{cr.summary_a.delay_end_s*1e3:.2f} ms",
             f"{cr.summary_b.delay_start_s*1e3:.3f}–{cr.summary_b.delay_end_s*1e3:.2f} ms"),
            ("Pulse",     f"{cr.summary_a.pulse_dur_us:.1f} µs",
                          f"{cr.summary_b.pulse_dur_us:.1f} µs"),
            ("HW Trigger", "Yes" if cr.summary_a.hw_triggered else "No",
                           "Yes" if cr.summary_b.hw_triggered else "No"),
        ]
        for r, (name, va, vb) in enumerate(rows, start=1):
            sl.addWidget(self._dim(name), r, 0)
            sl.addWidget(self._mono(va), r, 1)
            sl.addWidget(self._mono(vb), r, 2)
        self._content_lay.addWidget(summ_box)

        # ── Full-frame trace overlay ──────────────────────────────────
        chart_box = QGroupBox("Full-Frame ΔR/R Trace Overlay")
        cl = QVBoxLayout(chart_box)
        self._build_overlay_chart(cl, cr.full_frame_overlay,
                                  cr.summary_a.label, cr.summary_b.label)
        self._content_lay.addWidget(chart_box)

        # ── Metrics table ─────────────────────────────────────────────
        metrics_box = QGroupBox("Metrics Comparison")
        ml = QVBoxLayout(metrics_box)
        self._build_metrics_table(ml, cr)
        self._content_lay.addWidget(metrics_box)

        # ── Per-ROI overlays ──────────────────────────────────────────
        matched_overlays = [o for o in cr.roi_overlays if not o.only_in]
        if matched_overlays:
            roi_box = QGroupBox("ROI Trace Overlays")
            rl = QVBoxLayout(roi_box)
            for ov in matched_overlays:
                rl.addWidget(QLabel(f"ROI: {ov.label}"))
                self._build_overlay_chart(rl, ov,
                                          cr.summary_a.label,
                                          cr.summary_b.label)
            self._content_lay.addWidget(roi_box)

        # ── Unmatched ROI notes ───────────────────────────────────────
        if cr.unmatched_notes:
            note_box = QGroupBox("Unmatched ROIs")
            nl = QVBoxLayout(note_box)
            for note in cr.unmatched_notes:
                lbl = QLabel(f"• {note}")
                lbl.setStyleSheet(
                    f"color:{PALETTE['textDim']}; "
                    f"font-size:{FONT['caption']}pt;")
                nl.addWidget(lbl)
            self._content_lay.addWidget(note_box)

        self._content_lay.addStretch()
        self._export_btn.setEnabled(True)

    def _build_overlay_chart(self, layout, overlay, label_a: str, label_b: str):
        """Add a pyqtgraph chart with two overlaid traces."""
        try:
            from ui.charts import TransientTraceChart
            import pyqtgraph as pg
            _PG_OK = True
        except ImportError:
            _PG_OK = False

        if not _PG_OK:
            layout.addWidget(QLabel("(pyqtgraph not available)"))
            return

        from ui.charts import StyledPlotWidget
        chart = StyledPlotWidget(x_label="Delay  (ms)", y_label="ΔR/R")
        chart.setMinimumHeight(180)
        chart.setMaximumHeight(250)

        # Session A trace (solid)
        if overlay.signal_a is not None and overlay.times_a_s is not None:
            ts_ms_a = overlay.times_a_s * 1e3
            color_a = overlay.color_a or "#4fc3f7"
            chart.plot(ts_ms_a, overlay.signal_a,
                       pen=pg.mkPen(color=color_a, width=2),
                       name=f"{label_a}")

        # Session B trace (dashed)
        if overlay.signal_b is not None and overlay.times_b_s is not None:
            ts_ms_b = overlay.times_b_s * 1e3
            color_b = overlay.color_b or "#ff8a65"
            chart.plot(ts_ms_b, overlay.signal_b,
                       pen=pg.mkPen(color=color_b, width=2,
                                    style=Qt.DashLine),
                       name=f"{label_b}")

        # Zero line
        zero = pg.InfiniteLine(pos=0, angle=0,
                               pen=pg.mkPen(color=PALETTE['border'], width=1,
                                            style=Qt.DotLine),
                               movable=False)
        chart.addItem(zero)

        layout.addWidget(chart)

    def _build_metrics_table(self, layout, cr):
        """Build the side-by-side metrics table with delta column."""
        # Collect all rows: full-frame + per-ROI
        all_deltas = [cr.full_frame] + cr.roi_deltas

        cols = ["ROI", "Peak ΔR/R (A)", "Peak ΔR/R (B)", "Δ Peak",
                "SNR (A)", "SNR (B)", "Δ SNR",
                "Recovery (A)", "Recovery (B)", "Δ Recovery"]
        table = QTableWidget(len(all_deltas), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setMaximumHeight(min(40 + len(all_deltas) * 28, 250))
        table.setStyleSheet(
            f"QTableWidget {{ font-family:{MONO_FONT}; "
            f"font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; }}"
            f"QHeaderView::section {{ font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['surface']}; color:{PALETTE['textSub']}; "
            f"padding:2px 4px; }}")

        for row, md in enumerate(all_deltas):
            def _item(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                return it

            def _val(m, attr: str, fmt: str = ".4e") -> str:
                if m is None:
                    return "—"
                v = getattr(m, attr, None)
                if v is None:
                    return "—"
                return f"{v:{fmt}}"

            def _delta(v: float, fmt: str = ".4e") -> str:
                if not md.has_both:
                    return "—"
                return f"{v:+{fmt}}"

            table.setItem(row, 0, _item(md.label))
            table.setItem(row, 1, _item(_val(md.metrics_a, "peak_drr", "+.4e")))
            table.setItem(row, 2, _item(_val(md.metrics_b, "peak_drr", "+.4e")))
            table.setItem(row, 3, _item(_delta(md.delta_peak_drr, ".4e")))
            table.setItem(row, 4, _item(_val(md.metrics_a, "peak_snr", ".1f")))
            table.setItem(row, 5, _item(_val(md.metrics_b, "peak_snr", ".1f")))
            table.setItem(row, 6, _item(_delta(md.delta_peak_snr, ".1f")))
            table.setItem(row, 7, _item(_val(md.metrics_a, "recovery_ratio", ".2f")))
            table.setItem(row, 8, _item(_val(md.metrics_b, "recovery_ratio", ".2f")))
            table.setItem(row, 9, _item(_delta(md.delta_recovery_ratio, ".2f")))

        layout.addWidget(table)
        self._metrics_table = table

    # ---------------------------------------------------------------- #
    #  Export                                                            #
    # ---------------------------------------------------------------- #

    def _on_export(self):
        if self._comparison is None:
            return
        default_name = f"transient_comparison_{int(time.time())}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Comparison",
            default_name + ".json",
            "JSON (*.json);;CSV (*.csv);;All files (*)")
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                self._export_csv(path)
            else:
                self._export_json(path)
            QMessageBox.information(self, "Exported",
                                   f"Comparison saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _export_json(self, path: str):
        from acquisition.transient_comparison import comparison_to_dict
        doc = comparison_to_dict(self._comparison)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)

    def _export_csv(self, path: str):
        cr = self._comparison
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["# Transient Session Comparison"])
            w.writerow(["# Session A", cr.summary_a.label, cr.summary_a.uid])
            w.writerow(["# Session B", cr.summary_b.label, cr.summary_b.uid])
            if cr.grids_differ:
                w.writerow(["# Grid note", cr.grid_note])
            w.writerow([])

            # Metrics section
            w.writerow(["# Metrics"])
            w.writerow(["roi",
                        "peak_drr_a", "peak_drr_b", "delta_peak_drr",
                        "snr_a", "snr_b", "delta_snr",
                        "recovery_a", "recovery_b", "delta_recovery",
                        "ttp_a_ms", "ttp_b_ms", "delta_ttp_ms"])
            all_deltas = [cr.full_frame] + cr.roi_deltas
            for md in all_deltas:
                def _v(m, attr, default=""):
                    if m is None:
                        return default
                    return f"{getattr(m, attr, 0):.6e}"
                def _d(v):
                    return f"{v:+.6e}" if md.has_both else ""

                w.writerow([
                    md.label,
                    _v(md.metrics_a, "peak_drr"),
                    _v(md.metrics_b, "peak_drr"),
                    _d(md.delta_peak_drr),
                    _v(md.metrics_a, "peak_snr"),
                    _v(md.metrics_b, "peak_snr"),
                    _d(md.delta_peak_snr),
                    _v(md.metrics_a, "recovery_ratio"),
                    _v(md.metrics_b, "recovery_ratio"),
                    _d(md.delta_recovery_ratio),
                    _v(md.metrics_a, "time_to_peak_s"),
                    _v(md.metrics_b, "time_to_peak_s"),
                    _d(md.delta_time_to_peak_s),
                ])
            w.writerow([])

            # Trace section — full-frame
            w.writerow(["# Full-frame traces"])
            ov = cr.full_frame_overlay
            if ov.signal_a is not None and ov.signal_b is not None:
                max_n = max(
                    len(ov.signal_a) if ov.signal_a is not None else 0,
                    len(ov.signal_b) if ov.signal_b is not None else 0)
                w.writerow(["time_a_ms", "signal_a",
                           "time_b_ms", "signal_b"])
                for i in range(max_n):
                    row = []
                    if ov.times_a_s is not None and i < len(ov.times_a_s):
                        row.extend([f"{ov.times_a_s[i]*1e3:.6f}",
                                   f"{ov.signal_a[i]:.8e}"])
                    else:
                        row.extend(["", ""])
                    if ov.times_b_s is not None and i < len(ov.times_b_s):
                        row.extend([f"{ov.times_b_s[i]*1e3:.6f}",
                                   f"{ov.signal_b[i]:.8e}"])
                    else:
                        row.extend(["", ""])
                    w.writerow(row)

            if cr.unmatched_notes:
                w.writerow([])
                w.writerow(["# Unmatched ROIs"])
                for note in cr.unmatched_notes:
                    w.writerow([note])

    # ---------------------------------------------------------------- #
    #  Content management                                               #
    # ---------------------------------------------------------------- #

    def _clear_content(self):
        """Remove all widgets from the content layout."""
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _dim(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
        return l

    def _mono(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['text']};")
        return l

    # ---------------------------------------------------------------- #
    #  Class-level entry point                                          #
    # ---------------------------------------------------------------- #

    @classmethod
    def run(cls, session_mgr, current_uid: str = "",
            parent: Optional[QWidget] = None):
        """Open the comparison dialog modally.

        Parameters
        ----------
        session_mgr : SessionManager
            The application's session manager (for listing + loading).
        current_uid : str
            UID of the currently loaded transient session (pre-selected
            as Session A).
        parent : QWidget, optional
            Parent widget for modality.
        """
        dlg = cls(session_mgr, current_uid, parent)
        dlg.exec_()
