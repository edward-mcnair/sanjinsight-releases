"""
acquisition/report_html.py

Generates a self-contained HTML report for a thermoreflectance session.

The report uses inline CSS and base64-encoded images so it can be opened
in any browser without external dependencies.  It respects the same
ReportConfig toggles as the PDF generator.
"""

from __future__ import annotations
import os
import time
import numpy as np
from typing import Optional

from acquisition.storage.session        import Session
from acquisition.calibration.calibration import CalibrationResult
from .report      import ReportConfig
from acquisition.processing.image_rendering import render_to_b64


# ------------------------------------------------------------------ #
#  Image helpers                                                       #
# ------------------------------------------------------------------ #

def _array_to_b64(data: np.ndarray, mode: str = "percentile",
                  cmap: str = "Thermal Delta",
                  size: tuple = (600, 440)) -> str:
    """Convert a numpy array to a base64-encoded PNG data URI.

    Delegates to :func:`render_to_b64` from the shared image-rendering
    module.
    """
    tw, th = size
    return render_to_b64(
        data, mode=mode, colormap=cmap, width=tw, height=th,
    )


# ------------------------------------------------------------------ #
#  CSS                                                                 #
# ------------------------------------------------------------------ #

_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    max-width: 960px; margin: 0 auto; padding: 0; background: #fff; color: #1a1a2e;
}
.header { background: #1a1a2e; color: #fff; padding: 16px 24px; }
.header h1 { margin: 0; font-size: 18px; }
.header .subtitle { color: #aab; font-size: 12px; margin-top: 4px; }
.teal-rule { border: none; height: 2px; background: #00a88a; margin: 0; }
.content { padding: 20px 24px; }
h2 { color: #1a1a2e; font-size: 15px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }
th { background: #1a1a2e; color: #fff; padding: 6px 10px; font-size: 9pt; text-align: left; }
td { padding: 5px 10px; font-size: 9pt; border: 1px solid #ddd; }
tr:nth-child(even) { background: #f8f8fc; }
.mono { font-family:'Menlo','Consolas','Courier New',monospace; }
.img-container { text-align: center; margin: 12px 0; }
.img-container img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.caption { text-align: center; font-size: 8pt; color: #4a4a6a; margin-top: 4px; }
.verdict-badge {
    display: inline-block; padding: 10px 24px; border-radius: 6px;
    font-size: 18px; font-weight: bold; color: #fff; margin-right: 12px;
}
.grade-badge {
    display: inline-block; padding: 8px 16px; border-radius: 6px;
    font-size: 20px; font-weight: bold; color: #fff; margin-right: 12px;
}
.panel-row { display: flex; gap: 8px; margin: 12px 0; }
.panel-row .panel { flex: 1; text-align: center; }
.panel-row img { width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.footer {
    text-align: center; padding: 12px; font-size: 8pt; color: #aaa;
    border-top: 1px solid #00a88a;
}
.rec-list { list-style-type: disc; padding-left: 20px; }
.rec-list li { font-size: 9pt; margin-bottom: 4px; }
"""


# ------------------------------------------------------------------ #
#  HTML report generator                                              #
# ------------------------------------------------------------------ #

def generate_html_report(session: Session,
                         output_dir: str = ".",
                         calibration: Optional[CalibrationResult] = None,
                         analysis=None,
                         config: Optional[ReportConfig] = None,
                         quality_scorecard=None) -> str:
    """
    Generate a self-contained HTML report.

    Returns the path to the saved .html file.
    """
    os.makedirs(output_dir, exist_ok=True)
    cfg = config or ReportConfig()
    meta = session.meta

    # Apply metadata overrides
    operator = cfg.operator or meta.operator or ""
    customer = cfg.customer or ""
    report_notes = cfg.notes or meta.notes or ""

    parts = [f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Thermal Analysis Report — {_esc(meta.label)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="header">
    <h1>Thermoreflectance Measurement Report</h1>
    <div class="subtitle">{_esc(meta.label)}</div>
</div>
<hr class="teal-rule">
<div class="content">
"""]

    # ── Measurement parameters ────────────────────────────────────
    if cfg.measurement_params:
        snr_str = f"{meta.snr_db:.1f} dB" if meta.snr_db else "—"
        roi_str = (f"x={meta.roi['x']} y={meta.roi['y']} "
                   f"w={meta.roi['w']} h={meta.roi['h']}"
                   if meta.roi else "Full frame")
        cal_str = (f"{calibration.t_min:.1f}–{calibration.t_max:.1f}°C "
                   f"({calibration.n_points} pts)"
                   if (calibration and calibration.valid) else "Not applied")

        parts.append("<h2>Acquisition Parameters</h2>")
        parts.append(_kv_table([
            ("Date / Time", meta.timestamp_str),
            ("Frames (N)", str(meta.n_frames)),
            ("Exposure", f"{meta.exposure_us:.0f} μs"),
            ("Gain", f"{meta.gain_db:.1f} dB"),
            ("Duration", f"{meta.duration_s:.1f} s"),
            ("SNR", snr_str),
            ("Frame size", f"{meta.frame_w} × {meta.frame_h} px"),
            ("ROI", roi_str),
            ("Calibration", cal_str),
            ("Session ID", meta.uid[:28]),
        ]))

    # ── Device info ────────────────────────────────────────────────
    if cfg.device_info:
        mode_str = (meta.imaging_mode.replace("_", " ").title()
                    if meta.imaging_mode else "—")
        wl_str = f"{meta.wavelength_nm} nm" if meta.wavelength_nm else "—"
        tec_str = (f"{meta.tec_temperature:.1f}°C (setpoint "
                   f"{meta.tec_setpoint:.1f}°C)"
                   if meta.tec_temperature else "—")
        bias_str = (f"{meta.bias_voltage:.3f} V / "
                    f"{meta.bias_current*1e3:.2f} mA"
                    if (meta.bias_voltage or meta.bias_current) else "—")
        ct_str = (f"{meta.ct_value:.4e} K⁻¹"
                  if meta.ct_value else "— (uncalibrated)")

        rows = [
            ("Imaging mode", mode_str),
            ("Wavelength", wl_str),
            ("TEC temp", tec_str),
            ("Bias", bias_str),
            ("Material profile", meta.profile_name or "—"),
            ("C_T coefficient", ct_str),
        ]
        if operator:
            rows.append(("Operator", operator))
        if customer:
            rows.append(("Customer", customer))
        parts.append("<h2>Instrument &amp; DUT Conditions</h2>")
        parts.append(_kv_table(rows))

    # ── Thermal map ───────────────────────────────────────────────
    drr = session.delta_r_over_r
    if cfg.thermal_map and drr is not None:
        b64 = _array_to_b64(drr, mode="percentile", cmap="Thermal Delta")
        if b64:
            parts.append("<h2>Thermoreflectance Map (ΔR/R)</h2>")
            parts.append(f'<div class="img-container">'
                         f'<img src="{b64}" alt="ΔR/R map"></div>')
            parts.append('<p class="caption">Blue = negative (cooling), '
                         'Red = positive (heating). '
                         'Clipped to 0.5–99.5 percentile.</p>')

    # ── Raw data summary (supporting images) ──────────────────────
    if cfg.raw_data_summary:
        parts.append("<h2>Supporting Images</h2>")
        parts.append('<div class="panel-row">')
        for arr, label, mode, cmap in [
            (session.cold_avg,   "Cold (baseline)",   "auto",       "gray"),
            (session.hot_avg,    "Hot (stimulus)",    "auto",       "gray"),
            (session.difference, "Difference (H−C)", "percentile", "signed"),
        ]:
            parts.append('<div class="panel">')
            if arr is not None:
                b64 = _array_to_b64(arr, mode=mode, cmap=cmap, size=(300, 220))
                if b64:
                    parts.append(f'<img src="{b64}" alt="{_esc(label)}">')
            parts.append(f'<p class="caption">{_esc(label)}</p></div>')
        parts.append("</div>")

    # ── Calibrated ΔT map ─────────────────────────────────────────
    dt_arr = getattr(session, "_delta_t", None)
    if dt_arr is None and calibration and calibration.valid and drr is not None:
        try:
            dt_arr = calibration.apply(drr)
        except Exception:
            dt_arr = None

    if cfg.calibration_details and dt_arr is not None:
        b64 = _array_to_b64(dt_arr, mode="percentile", cmap="Thermal Delta")
        if b64:
            parts.append("<h2>Calibrated Temperature Map (ΔT, °C)</h2>")
            parts.append(f'<div class="img-container">'
                         f'<img src="{b64}" alt="ΔT map"></div>')

    # ── Verdict & analysis ────────────────────────────────────────
    if cfg.verdict_and_recommendations and analysis and analysis.valid:
        VERDICT_COLORS = {"PASS": "#00c070", "WARNING": "#ffb300",
                          "FAIL": "#e03030"}
        vc = VERDICT_COLORS.get(analysis.verdict, "#888")
        parts.append("<h2>Pass / Fail Thermal Analysis</h2>")
        parts.append(f'<span class="verdict-badge" '
                     f'style="background:{vc}">{_esc(analysis.verdict)}'
                     f'</span>')
        parts.append(_kv_table([
            ("Hotspots detected", str(analysis.n_hotspots)),
            ("Peak ΔT", f"{analysis.max_peak_k:.2f} °C"),
            ("Hotspot area", f"{analysis.area_fraction*100:.2f} %"),
            ("Map mean ΔT", f"{analysis.map_mean_k:.3f} °C"),
            ("Detection threshold", f"{analysis.threshold_k:.1f} °C"),
        ]))

        # Overlay image
        if analysis.overlay_rgb is not None:
            b64 = _array_to_b64(analysis.overlay_rgb)
            if b64:
                parts.append(f'<div class="img-container">'
                             f'<img src="{b64}" alt="Analysis overlay">'
                             f'</div>')

        # Hotspot table
        if cfg.hotspot_table and analysis.hotspots:
            parts.append("<h2>Hotspot Detail</h2><table>")
            parts.append("<tr><th>#</th><th>Peak ΔT (°C)</th>"
                         "<th>Mean ΔT (°C)</th><th>Area (px)</th>"
                         "<th>Centroid</th><th>Severity</th></tr>")
            for h in analysis.hotspots:
                cx, cy = h.centroid
                parts.append(
                    f"<tr><td>{h.index}</td>"
                    f'<td class="mono">{h.peak_k:.2f}</td>'
                    f'<td class="mono">{h.mean_k:.2f}</td>'
                    f'<td class="mono">{h.area_px:,}</td>'
                    f"<td>({cx}, {cy})</td>"
                    f"<td>{_esc(h.severity.upper())}</td></tr>")
            parts.append("</table>")

    # ── Quality scorecard ─────────────────────────────────────────
    if cfg.quality_scorecard and quality_scorecard is not None:
        GRADE_COLORS = {"A": "#00c070", "B": "#00a88a", "C": "#ffb300",
                        "D": "#e03030", "F": "#e03030"}
        overall = quality_scorecard.get("overall_grade", "—")
        gc = GRADE_COLORS.get(overall, "#888")
        parts.append("<h2>Acquisition Quality Scorecard</h2>")
        parts.append(f'<span class="grade-badge" style="background:{gc}">'
                     f'{_esc(overall)}</span>')

        metrics = quality_scorecard.get("metrics", [])
        if metrics:
            parts.append("<table><tr><th>Metric</th><th>Grade</th>"
                         "<th>Value</th><th>Threshold</th></tr>")
            for m in metrics:
                mg = m.get("grade", "—")
                mc = GRADE_COLORS.get(mg, "#888")
                parts.append(
                    f"<tr><td>{_esc(m.get('metric', ''))}</td>"
                    f'<td style="color:{mc};font-weight:bold">{_esc(mg)}</td>'
                    f'<td class="mono">{_esc(m.get("display", "—"))}</td>'
                    f"<td>{_esc(m.get('threshold', '—'))}</td></tr>")
            parts.append("</table>")

        recs = quality_scorecard.get("recommendations", [])
        if recs:
            parts.append("<h2>Recommendations</h2><ul class='rec-list'>")
            for rec in recs:
                parts.append(f"<li>{_esc(rec)}</li>")
            parts.append("</ul>")

    # ── Transient section ────────────────────────────────────────
    rt = getattr(meta, "result_type", "single_point") or "single_point"
    if cfg.transient_section and rt == "transient":
        parts.append(_render_transient_section(session, meta))

    # ── Movie section ────────────────────────────────────────────
    if cfg.movie_section and rt == "movie":
        parts.append(_render_movie_section(session, meta))

    # ── Notes ─────────────────────────────────────────────────────
    if report_notes:
        parts.append("<h2>Notes</h2>")
        parts.append(f"<p>{_esc(report_notes)}</p>")

    # ── Footer ────────────────────────────────────────────────────
    ts = time.strftime("%Y-%m-%d %H:%M")
    parts.append(f"""
</div>
<div class="footer">
    Generated {ts} · Microsanj Thermal Analysis System · CONFIDENTIAL
</div>
</body>
</html>""")

    # Write
    safe_label = meta.label.replace(" ", "_").replace("/", "-")[:40]
    html_name = f"{meta.uid}_{safe_label}.html"
    html_path = os.path.join(output_dir, html_name)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    session.unload()
    return html_path


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
#  Transient report section                                           #
# ------------------------------------------------------------------ #

def _render_transient_section(session, meta) -> str:
    """Render the transient acquisition report section as HTML."""
    import numpy as np
    from acquisition.transient_metrics import (
        compute_transient_metrics, compute_all_roi_metrics)
    from acquisition.roi_extraction import extract_roi_signals

    cp = getattr(meta, "cube_params", None) or {}
    parts = ['<h2>Transient Acquisition</h2>']

    # ── Acquisition metadata table ────────────────────────────────
    parts.append(_kv_table([
        ("Delays", str(cp.get("n_delays", meta.n_frames or "—"))),
        ("Averages / delay", str(cp.get("n_averages", "—"))),
        ("Pulse width", f"{cp.get('pulse_dur_us', 0):.1f} µs"),
        ("Delay range",
         f"{cp.get('delay_start_s', 0)*1e3:.3f}–"
         f"{cp.get('delay_end_s', 0)*1e3:.2f} ms"),
        ("HW Trigger", "Yes" if cp.get("hw_triggered") else "No (SW)"),
        ("Exposure", f"{meta.exposure_us:.0f} µs"),
        ("Gain", f"{meta.gain_db:.1f} dB"),
        ("Duration", f"{meta.duration_s:.1f} s"),
    ]))

    # ── Peak-frame thermal thumbnail ──────────────────────────────
    cube = session.delta_r_cube
    ts = session.delay_times_s
    if cube is not None and cube.ndim == 3 and cube.shape[0] > 0:
        n = cube.shape[0]
        ff_signal = np.nanmean(cube.reshape(n, -1), axis=1)
        peak_idx = int(np.nanargmax(np.abs(ff_signal)))
        peak_frame = cube[peak_idx]

        b64 = _array_to_b64(peak_frame, mode="percentile",
                            cmap="Thermal Delta", size=(500, 360))
        if b64:
            peak_time_ms = (ts[peak_idx] * 1e3
                            if ts is not None and peak_idx < len(ts)
                            else 0)
            parts.append(
                f'<div class="img-container">'
                f'<img src="{b64}" alt="Peak frame ΔR/R"></div>')
            parts.append(
                f'<p class="caption">Peak-frame ΔR/R at delay index '
                f'{peak_idx} ({peak_time_ms:.3f} ms)</p>')

        # ── Trace chart as inline SVG-style table (text-based) ────
        # Render a simple ASCII-friendly trace summary since we cannot
        # use pyqtgraph off the main thread. Show key trace values.
        parts.append('<h2>Full-Frame ΔR/R Trace Summary</h2>')
        if ts is not None and len(ff_signal) == len(ts):
            ff_metrics = compute_transient_metrics(
                ff_signal, ts, "Full frame")

            parts.append(_kv_table([
                ("Peak ΔR/R (signed)", f"{ff_metrics.peak_drr:+.4e}"),
                ("Peak |ΔR/R|", f"{ff_metrics.peak_abs:.4e}"),
                ("Time-to-peak", f"{ff_metrics.time_to_peak_s*1e3:.3f} ms"),
                ("Baseline mean", f"{ff_metrics.baseline_mean:.4e}"),
                ("Baseline σ", f"{ff_metrics.baseline_std:.4e}"),
                ("Peak SNR", f"{ff_metrics.peak_snr:.1f}"),
                ("Recovery ratio", f"{ff_metrics.recovery_ratio:.2f}"),
            ]))

        # ── Per-ROI metrics table ─────────────────────────────────
        try:
            from acquisition.roi_model import roi_model
            rois = roi_model.rois
        except ImportError:
            rois = []

        if rois and ts is not None:
            roi_signals = extract_roi_signals(cube, rois)
            if roi_signals:
                roi_metrics = compute_all_roi_metrics(roi_signals, ts)
                parts.append('<h2>ROI Metrics</h2>')
                parts.append(
                    '<table><tr>'
                    '<th>ROI</th><th>Peak ΔR/R</th><th>Time-to-peak</th>'
                    '<th>Baseline σ</th><th>Peak SNR</th>'
                    '<th>Recovery</th></tr>')
                for m in roi_metrics:
                    parts.append(
                        f'<tr><td>{_esc(m.roi_label)}</td>'
                        f'<td class="mono">{m.peak_drr:+.4e}</td>'
                        f'<td class="mono">{m.time_to_peak_s*1e3:.3f} ms</td>'
                        f'<td class="mono">{m.baseline_std:.4e}</td>'
                        f'<td class="mono">{m.peak_snr:.1f}</td>'
                        f'<td class="mono">{m.recovery_ratio:.2f}</td></tr>')
                parts.append('</table>')

    return "\n".join(parts)


# ------------------------------------------------------------------ #
#  Movie report section                                               #
# ------------------------------------------------------------------ #

def _render_movie_section(session, meta) -> str:
    """Render the movie acquisition report section as HTML."""
    import numpy as np
    from acquisition.movie_metrics import (
        compute_movie_metrics, compute_all_movie_roi_metrics)
    from acquisition.roi_extraction import extract_roi_signals

    cp = getattr(meta, "cube_params", None) or {}
    parts = ['<h2>Movie Acquisition</h2>']

    # ── Acquisition metadata table ────────────────────────────────
    fps = cp.get("fps_achieved", 0)
    parts.append(_kv_table([
        ("Frames", str(cp.get("n_frames", meta.n_frames or "—"))),
        ("Frame rate", f"{fps:.1f} fps" if fps else "—"),
        ("Exposure", f"{meta.exposure_us:.0f} µs"),
        ("Gain", f"{meta.gain_db:.1f} dB"),
        ("Duration", f"{meta.duration_s:.2f} s"),
    ]))

    # ── Peak-frame thermal thumbnail ──────────────────────────────
    cube = session.delta_r_cube
    ts = session.timestamps_s
    if cube is None:
        # Fall back to raw frame cube
        cube = getattr(session, 'frame_cube', None)
    if cube is not None and cube.ndim == 3 and cube.shape[0] > 0:
        n = cube.shape[0]
        ff_signal = np.nanmean(cube.reshape(n, -1), axis=1)
        peak_idx = int(np.nanargmax(np.abs(ff_signal)))
        peak_frame = cube[peak_idx]

        b64 = _array_to_b64(peak_frame, mode="percentile",
                            cmap="Thermal Delta", size=(500, 360))
        if b64:
            peak_time_ms = (ts[peak_idx] * 1e3
                            if ts is not None and peak_idx < len(ts)
                            else 0)
            parts.append(
                f'<div class="img-container">'
                f'<img src="{b64}" alt="Peak frame"></div>')
            parts.append(
                f'<p class="caption">Peak-frame at frame {peak_idx}'
                f' ({peak_time_ms:.1f} ms)</p>')

        # ── Full-frame metrics summary ────────────────────────────
        if ts is None:
            ts = np.arange(n, dtype=np.float64)

        parts.append('<h2>Full-Frame Signal Summary</h2>')
        if len(ff_signal) == len(ts):
            ff_metrics = compute_movie_metrics(ff_signal, ts, "Full frame")
            parts.append(_kv_table([
                ("Peak ΔR/R (signed)", f"{ff_metrics.peak_drr:+.4e}"),
                ("Peak |ΔR/R|", f"{ff_metrics.peak_abs:.4e}"),
                ("Peak frame", str(ff_metrics.peak_index)),
                ("Peak time", f"{ff_metrics.peak_time_s*1e3:.1f} ms"),
                ("Mean ΔR/R", f"{ff_metrics.mean_drr:+.4e}"),
                ("Temporal σ", f"{ff_metrics.temporal_std:.4e}"),
            ]))

        # ── Per-ROI metrics table ─────────────────────────────────
        try:
            from acquisition.roi_model import roi_model
            rois = roi_model.rois
        except ImportError:
            rois = []

        if rois:
            roi_signals = extract_roi_signals(cube, rois)
            if roi_signals:
                roi_metrics = compute_all_movie_roi_metrics(
                    roi_signals, ts)
                parts.append('<h2>ROI Metrics</h2>')
                parts.append(
                    '<table><tr>'
                    '<th>ROI</th><th>Peak ΔR/R</th><th>Peak |ΔR/R|</th>'
                    '<th>Peak time</th><th>Mean ΔR/R</th>'
                    '<th>Temporal σ</th></tr>')
                for m in roi_metrics:
                    parts.append(
                        f'<tr><td>{_esc(m.roi_label)}</td>'
                        f'<td class="mono">{m.peak_drr:+.4e}</td>'
                        f'<td class="mono">{m.peak_abs:.4e}</td>'
                        f'<td class="mono">{m.peak_time_s*1e3:.1f} ms</td>'
                        f'<td class="mono">{m.mean_drr:+.4e}</td>'
                        f'<td class="mono">{m.temporal_std:.4e}</td></tr>')
                parts.append('</table>')

    return "\n".join(parts)


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _kv_table(rows: list) -> str:
    """Build a simple two-column key-value HTML table."""
    lines = ["<table>"]
    for key, val in rows:
        lines.append(f"<tr><td><b>{_esc(key)}</b></td>"
                     f'<td class="mono">{_esc(val)}</td></tr>')
    lines.append("</table>")
    return "\n".join(lines)
