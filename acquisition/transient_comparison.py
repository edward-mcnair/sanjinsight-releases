"""
acquisition/transient_comparison.py

Pure-data comparison of two transient sessions.

Given two TransientResult objects (reconstructed from stored sessions),
computes:

  • Full-frame metrics for both, plus deltas
  • Per-ROI metrics for matching ROI labels, plus deltas
  • Full-frame and per-ROI signal arrays for overlay charting
  • Delay-grid metadata for both sessions (visible if they differ)

All functions are numpy-only — no Qt dependency.  The UI dialog
consumes the ComparisonResult returned here.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .transient_metrics import (
    compute_transient_metrics, TransientMetrics)
from .transient_pipeline import TransientResult


@dataclass
class MetricsDelta:
    """Side-by-side metrics for one ROI (or full-frame) across two sessions."""

    label:    str = ""
    color_a:  str = "#ffffff"
    color_b:  str = "#ffffff"

    metrics_a: Optional[TransientMetrics] = None
    metrics_b: Optional[TransientMetrics] = None

    # Signed deltas: B − A  (positive = B is larger)
    delta_peak_drr:       float = 0.0
    delta_peak_abs:       float = 0.0
    delta_time_to_peak_s: float = 0.0
    delta_baseline_mean:  float = 0.0
    delta_baseline_std:   float = 0.0
    delta_peak_snr:       float = 0.0
    delta_recovery_ratio: float = 0.0

    @property
    def has_both(self) -> bool:
        return self.metrics_a is not None and self.metrics_b is not None


def _compute_delta(a: Optional[TransientMetrics],
                   b: Optional[TransientMetrics]) -> MetricsDelta:
    """Compute B − A deltas for all numeric fields."""
    md = MetricsDelta()
    md.metrics_a = a
    md.metrics_b = b
    if a is not None:
        md.label = a.roi_label
        md.color_a = a.roi_color
    if b is not None:
        if not md.label:
            md.label = b.roi_label
        md.color_b = b.roi_color
    if a is not None and b is not None:
        md.delta_peak_drr       = b.peak_drr       - a.peak_drr
        md.delta_peak_abs       = b.peak_abs        - a.peak_abs
        md.delta_time_to_peak_s = b.time_to_peak_s  - a.time_to_peak_s
        md.delta_baseline_mean  = b.baseline_mean   - a.baseline_mean
        md.delta_baseline_std   = b.baseline_std    - a.baseline_std
        md.delta_peak_snr       = b.peak_snr        - a.peak_snr
        md.delta_recovery_ratio = b.recovery_ratio  - a.recovery_ratio
    return md


@dataclass
class SessionSummary:
    """Lightweight summary of one session for display in comparison header."""
    label:       str   = ""
    uid:         str   = ""
    n_delays:    int   = 0
    n_averages:  int   = 0
    delay_start_s: float = 0.0
    delay_end_s:   float = 0.0
    pulse_dur_us:  float = 0.0
    exposure_us:   float = 0.0
    gain_db:       float = 0.0
    hw_triggered:  bool  = False
    duration_s:    float = 0.0


@dataclass
class TraceOverlay:
    """Paired signals for one ROI (or full-frame) across two sessions."""
    label:      str = ""
    color_a:    str = "#4fc3f7"   # light blue
    color_b:    str = "#ff8a65"   # light orange
    signal_a:   Optional[np.ndarray] = None   # (N_a,) float
    times_a_s:  Optional[np.ndarray] = None   # (N_a,) float — seconds
    signal_b:   Optional[np.ndarray] = None   # (N_b,) float
    times_b_s:  Optional[np.ndarray] = None   # (N_b,) float — seconds
    only_in:    str = ""  # "" = both, "A" = only in A, "B" = only in B


@dataclass
class ComparisonResult:
    """Everything the dialog needs to display a two-session comparison."""

    summary_a:  SessionSummary = field(default_factory=SessionSummary)
    summary_b:  SessionSummary = field(default_factory=SessionSummary)

    # Delay-grid metadata
    grids_differ: bool = False
    grid_note:    str  = ""    # human-readable note about grid differences

    # Full-frame comparison
    full_frame: MetricsDelta = field(default_factory=MetricsDelta)
    full_frame_overlay: TraceOverlay = field(default_factory=TraceOverlay)

    # Per-ROI comparisons (matched + unmatched)
    roi_deltas:   List[MetricsDelta] = field(default_factory=list)
    roi_overlays: List[TraceOverlay] = field(default_factory=list)
    unmatched_notes: List[str] = field(default_factory=list)


def _make_summary(result: TransientResult, label: str, uid: str
                  ) -> SessionSummary:
    return SessionSummary(
        label=label, uid=uid,
        n_delays=result.n_delays,
        n_averages=result.n_averages,
        delay_start_s=result.delay_start_s,
        delay_end_s=result.delay_end_s,
        pulse_dur_us=result.pulse_dur_us,
        exposure_us=result.exposure_us,
        gain_db=result.gain_db,
        hw_triggered=result.hw_triggered,
        duration_s=result.duration_s,
    )


def _full_frame_signal(result: TransientResult) -> Optional[np.ndarray]:
    if result.delta_r_cube is None:
        return None
    n = result.n_delays
    return np.nanmean(result.delta_r_cube.reshape(n, -1), axis=1)


def compare_transient_sessions(
    result_a: TransientResult,
    result_b: TransientResult,
    label_a: str = "Session A",
    label_b: str = "Session B",
    uid_a: str = "",
    uid_b: str = "",
    roi_signals_a: Optional[list[tuple[str, str, np.ndarray]]] = None,
    roi_signals_b: Optional[list[tuple[str, str, np.ndarray]]] = None,
) -> ComparisonResult:
    """Compare two transient sessions.

    Parameters
    ----------
    result_a, result_b : TransientResult
        Reconstructed results from stored sessions.
    label_a, label_b : str
        Human-readable session labels.
    uid_a, uid_b : str
        Session UIDs for traceability.
    roi_signals_a, roi_signals_b : list of (label, color, signal_1d), optional
        Pre-extracted ROI signals.  If None, ROI comparison is skipped
        (full-frame comparison still works).

    Returns
    -------
    ComparisonResult
    """
    cr = ComparisonResult()
    cr.summary_a = _make_summary(result_a, label_a, uid_a)
    cr.summary_b = _make_summary(result_b, label_b, uid_b)

    # ── Delay-grid comparison ─────────────────────────────────────
    diffs = []
    if result_a.n_delays != result_b.n_delays:
        diffs.append(
            f"Delay count: A={result_a.n_delays}, B={result_b.n_delays}")
    if abs(result_a.delay_start_s - result_b.delay_start_s) > 1e-9:
        diffs.append(
            f"Delay start: A={result_a.delay_start_s*1e3:.3f} ms, "
            f"B={result_b.delay_start_s*1e3:.3f} ms")
    if abs(result_a.delay_end_s - result_b.delay_end_s) > 1e-9:
        diffs.append(
            f"Delay end: A={result_a.delay_end_s*1e3:.3f} ms, "
            f"B={result_b.delay_end_s*1e3:.3f} ms")
    cr.grids_differ = bool(diffs)
    cr.grid_note = "; ".join(diffs) if diffs else "Identical delay grids"

    # ── Full-frame metrics + overlay ──────────────────────────────
    ts_a = result_a.delay_times_s
    ts_b = result_b.delay_times_s
    ff_a = _full_frame_signal(result_a)
    ff_b = _full_frame_signal(result_b)

    m_a = (compute_transient_metrics(ff_a, ts_a, "Full frame")
           if ff_a is not None and ts_a is not None else None)
    m_b = (compute_transient_metrics(ff_b, ts_b, "Full frame")
           if ff_b is not None and ts_b is not None else None)
    cr.full_frame = _compute_delta(m_a, m_b)
    cr.full_frame.label = "Full frame"

    cr.full_frame_overlay = TraceOverlay(
        label="Full frame",
        signal_a=ff_a, times_a_s=ts_a,
        signal_b=ff_b, times_b_s=ts_b,
    )

    # ── Per-ROI matching + comparison ─────────────────────────────
    if roi_signals_a is None:
        roi_signals_a = []
    if roi_signals_b is None:
        roi_signals_b = []

    rois_a = {label: (color, sig) for label, color, sig in roi_signals_a}
    rois_b = {label: (color, sig) for label, color, sig in roi_signals_b}
    all_labels = list(dict.fromkeys(
        list(rois_a.keys()) + list(rois_b.keys())))

    for lbl in all_labels:
        in_a = lbl in rois_a
        in_b = lbl in rois_b

        if in_a and in_b:
            # Matched ROI — compute metrics and overlay
            ca, sa = rois_a[lbl]
            cb, sb = rois_b[lbl]
            ma = compute_transient_metrics(sa, ts_a, lbl, ca) if ts_a is not None else None
            mb = compute_transient_metrics(sb, ts_b, lbl, cb) if ts_b is not None else None
            cr.roi_deltas.append(_compute_delta(ma, mb))
            cr.roi_overlays.append(TraceOverlay(
                label=lbl,
                color_a=ca, color_b=cb,
                signal_a=sa, times_a_s=ts_a,
                signal_b=sb, times_b_s=ts_b,
            ))
        elif in_a:
            ca, sa = rois_a[lbl]
            ma = compute_transient_metrics(sa, ts_a, lbl, ca) if ts_a is not None else None
            cr.roi_deltas.append(_compute_delta(ma, None))
            cr.roi_overlays.append(TraceOverlay(
                label=lbl, color_a=ca,
                signal_a=sa, times_a_s=ts_a, only_in="A"))
            cr.unmatched_notes.append(f"ROI '{lbl}' present in A only")
        else:
            cb, sb = rois_b[lbl]
            mb = compute_transient_metrics(sb, ts_b, lbl, cb) if ts_b is not None else None
            cr.roi_deltas.append(_compute_delta(None, mb))
            cr.roi_overlays.append(TraceOverlay(
                label=lbl, color_b=cb,
                signal_b=sb, times_b_s=ts_b, only_in="B"))
            cr.unmatched_notes.append(f"ROI '{lbl}' present in B only")

    return cr


def comparison_to_dict(cr: ComparisonResult) -> dict:
    """Serialise a ComparisonResult for JSON export."""
    def _metrics_dict(m: Optional[TransientMetrics]) -> Optional[dict]:
        return m.to_dict() if m is not None else None

    def _overlay_dict(ov: TraceOverlay) -> dict:
        d: dict = {"label": ov.label}
        if ov.signal_a is not None:
            d["signal_a"] = ov.signal_a.tolist()
            d["times_a_s"] = ov.times_a_s.tolist() if ov.times_a_s is not None else None
        if ov.signal_b is not None:
            d["signal_b"] = ov.signal_b.tolist()
            d["times_b_s"] = ov.times_b_s.tolist() if ov.times_b_s is not None else None
        if ov.only_in:
            d["only_in"] = ov.only_in
        return d

    def _delta_dict(md: MetricsDelta) -> dict:
        d: dict = {
            "label": md.label,
            "metrics_a": _metrics_dict(md.metrics_a),
            "metrics_b": _metrics_dict(md.metrics_b),
        }
        if md.has_both:
            d["deltas"] = {
                "peak_drr": md.delta_peak_drr,
                "peak_abs": md.delta_peak_abs,
                "time_to_peak_s": md.delta_time_to_peak_s,
                "baseline_mean": md.delta_baseline_mean,
                "baseline_std": md.delta_baseline_std,
                "peak_snr": md.delta_peak_snr,
                "recovery_ratio": md.delta_recovery_ratio,
            }
        return d

    return {
        "format": "sanjinsight_transient_comparison_v1",
        "summary_a": {
            "label": cr.summary_a.label,
            "uid": cr.summary_a.uid,
            "n_delays": cr.summary_a.n_delays,
            "n_averages": cr.summary_a.n_averages,
            "delay_start_s": cr.summary_a.delay_start_s,
            "delay_end_s": cr.summary_a.delay_end_s,
            "pulse_dur_us": cr.summary_a.pulse_dur_us,
            "hw_triggered": cr.summary_a.hw_triggered,
        },
        "summary_b": {
            "label": cr.summary_b.label,
            "uid": cr.summary_b.uid,
            "n_delays": cr.summary_b.n_delays,
            "n_averages": cr.summary_b.n_averages,
            "delay_start_s": cr.summary_b.delay_start_s,
            "delay_end_s": cr.summary_b.delay_end_s,
            "pulse_dur_us": cr.summary_b.pulse_dur_us,
            "hw_triggered": cr.summary_b.hw_triggered,
        },
        "grids_differ": cr.grids_differ,
        "grid_note": cr.grid_note,
        "full_frame": _delta_dict(cr.full_frame),
        "full_frame_overlay": _overlay_dict(cr.full_frame_overlay),
        "roi_comparisons": [_delta_dict(d) for d in cr.roi_deltas],
        "roi_overlays": [_overlay_dict(o) for o in cr.roi_overlays],
        "unmatched_notes": cr.unmatched_notes,
    }
