"""
acquisition/movie_comparison.py

Pure-data comparison of two movie sessions.

Given two MovieResult objects (reconstructed from stored sessions),
computes:

  • Full-frame metrics for both, plus deltas
  • Per-ROI metrics for matching ROI labels, plus deltas
  • Full-frame and per-ROI signal arrays for overlay charting
  • Timing-grid metadata for both sessions (visible if they differ)

All functions are numpy-only — no Qt dependency.  The UI dialog
consumes the MovieComparisonResult returned here.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional

from .movie_metrics import compute_movie_metrics, MovieMetrics
from .movie_pipeline import MovieResult


@dataclass
class MovieMetricsDelta:
    """Side-by-side metrics for one ROI (or full-frame) across two movie sessions."""

    label:    str = ""
    color_a:  str = "#ffffff"
    color_b:  str = "#ffffff"

    metrics_a: Optional[MovieMetrics] = None
    metrics_b: Optional[MovieMetrics] = None

    # Signed deltas: B − A  (positive = B is larger)
    delta_peak_drr:     float = 0.0
    delta_peak_abs:     float = 0.0
    delta_peak_time_s:  float = 0.0
    delta_mean_drr:     float = 0.0
    delta_temporal_std: float = 0.0

    @property
    def has_both(self) -> bool:
        return self.metrics_a is not None and self.metrics_b is not None


def _compute_movie_delta(
    a: Optional[MovieMetrics],
    b: Optional[MovieMetrics],
) -> MovieMetricsDelta:
    """Compute B − A deltas for all numeric movie metric fields."""
    md = MovieMetricsDelta()
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
        md.delta_peak_drr     = b.peak_drr     - a.peak_drr
        md.delta_peak_abs     = b.peak_abs      - a.peak_abs
        md.delta_peak_time_s  = b.peak_time_s   - a.peak_time_s
        md.delta_mean_drr     = b.mean_drr      - a.mean_drr
        md.delta_temporal_std = b.temporal_std   - a.temporal_std
    return md


@dataclass
class MovieSessionSummary:
    """Lightweight summary of one movie session for the comparison header."""
    label:        str   = ""
    uid:          str   = ""
    n_frames:     int   = 0
    fps_achieved: float = 0.0
    exposure_us:  float = 0.0
    gain_db:      float = 0.0
    duration_s:   float = 0.0


@dataclass
class MovieTraceOverlay:
    """Paired signals for one ROI (or full-frame) across two movie sessions."""
    label:      str = ""
    color_a:    str = "#4fc3f7"   # light blue
    color_b:    str = "#ff8a65"   # light orange
    signal_a:   Optional[np.ndarray] = None   # (N_a,) float
    times_a_s:  Optional[np.ndarray] = None   # (N_a,) float — seconds
    signal_b:   Optional[np.ndarray] = None   # (N_b,) float
    times_b_s:  Optional[np.ndarray] = None   # (N_b,) float — seconds
    only_in:    str = ""  # "" = both, "A" = only in A, "B" = only in B


@dataclass
class MovieComparisonResult:
    """Everything the dialog needs to display a two-session movie comparison."""

    summary_a:  MovieSessionSummary = field(default_factory=MovieSessionSummary)
    summary_b:  MovieSessionSummary = field(default_factory=MovieSessionSummary)

    # Timing-grid metadata
    grids_differ: bool = False
    grid_note:    str  = ""    # human-readable note about timing differences

    # Full-frame comparison
    full_frame: MovieMetricsDelta = field(default_factory=MovieMetricsDelta)
    full_frame_overlay: MovieTraceOverlay = field(
        default_factory=MovieTraceOverlay)

    # Per-ROI comparisons (matched + unmatched)
    roi_deltas:   List[MovieMetricsDelta] = field(default_factory=list)
    roi_overlays: List[MovieTraceOverlay] = field(default_factory=list)
    unmatched_notes: List[str] = field(default_factory=list)


def _make_movie_summary(
    result: MovieResult, label: str, uid: str,
) -> MovieSessionSummary:
    return MovieSessionSummary(
        label=label, uid=uid,
        n_frames=result.n_frames,
        fps_achieved=result.fps_achieved,
        exposure_us=result.exposure_us,
        gain_db=result.gain_db,
        duration_s=result.duration_s,
    )


def _full_frame_signal(result: MovieResult) -> Optional[np.ndarray]:
    if result.delta_r_cube is None:
        return None
    n = result.delta_r_cube.shape[0]
    return np.nanmean(result.delta_r_cube.reshape(n, -1), axis=1)


def compare_movie_sessions(
    result_a: MovieResult,
    result_b: MovieResult,
    label_a: str = "Session A",
    label_b: str = "Session B",
    uid_a: str = "",
    uid_b: str = "",
    roi_signals_a: Optional[list[tuple[str, str, np.ndarray]]] = None,
    roi_signals_b: Optional[list[tuple[str, str, np.ndarray]]] = None,
) -> MovieComparisonResult:
    """Compare two movie sessions.

    Parameters
    ----------
    result_a, result_b : MovieResult
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
    MovieComparisonResult
    """
    cr = MovieComparisonResult()
    cr.summary_a = _make_movie_summary(result_a, label_a, uid_a)
    cr.summary_b = _make_movie_summary(result_b, label_b, uid_b)

    # ── Timing-grid comparison ────────────────────────────────────
    diffs = []
    if result_a.n_frames != result_b.n_frames:
        diffs.append(
            f"Frame count: A={result_a.n_frames}, B={result_b.n_frames}")
    if abs(result_a.fps_achieved - result_b.fps_achieved) > 0.5:
        diffs.append(
            f"FPS: A={result_a.fps_achieved:.1f}, "
            f"B={result_b.fps_achieved:.1f}")
    if abs(result_a.duration_s - result_b.duration_s) > 0.01:
        diffs.append(
            f"Duration: A={result_a.duration_s:.2f} s, "
            f"B={result_b.duration_s:.2f} s")
    cr.grids_differ = bool(diffs)
    cr.grid_note = "; ".join(diffs) if diffs else "Identical timing grids"

    # ── Full-frame metrics + overlay ──────────────────────────────
    ts_a = result_a.timestamps_s
    ts_b = result_b.timestamps_s
    ff_a = _full_frame_signal(result_a)
    ff_b = _full_frame_signal(result_b)

    m_a = (compute_movie_metrics(ff_a, ts_a, "Full frame")
           if ff_a is not None and ts_a is not None else None)
    m_b = (compute_movie_metrics(ff_b, ts_b, "Full frame")
           if ff_b is not None and ts_b is not None else None)
    cr.full_frame = _compute_movie_delta(m_a, m_b)
    cr.full_frame.label = "Full frame"

    cr.full_frame_overlay = MovieTraceOverlay(
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
            ca, sa = rois_a[lbl]
            cb, sb = rois_b[lbl]
            ma = (compute_movie_metrics(sa, ts_a, lbl, ca)
                  if ts_a is not None else None)
            mb = (compute_movie_metrics(sb, ts_b, lbl, cb)
                  if ts_b is not None else None)
            cr.roi_deltas.append(_compute_movie_delta(ma, mb))
            cr.roi_overlays.append(MovieTraceOverlay(
                label=lbl, color_a=ca, color_b=cb,
                signal_a=sa, times_a_s=ts_a,
                signal_b=sb, times_b_s=ts_b,
            ))
        elif in_a:
            ca, sa = rois_a[lbl]
            ma = (compute_movie_metrics(sa, ts_a, lbl, ca)
                  if ts_a is not None else None)
            cr.roi_deltas.append(_compute_movie_delta(ma, None))
            cr.roi_overlays.append(MovieTraceOverlay(
                label=lbl, color_a=ca,
                signal_a=sa, times_a_s=ts_a, only_in="A"))
            cr.unmatched_notes.append(f"ROI '{lbl}' present in A only")
        else:
            cb, sb = rois_b[lbl]
            mb = (compute_movie_metrics(sb, ts_b, lbl, cb)
                  if ts_b is not None else None)
            cr.roi_deltas.append(_compute_movie_delta(None, mb))
            cr.roi_overlays.append(MovieTraceOverlay(
                label=lbl, color_b=cb,
                signal_b=sb, times_b_s=ts_b, only_in="B"))
            cr.unmatched_notes.append(f"ROI '{lbl}' present in B only")

    return cr


def movie_comparison_to_dict(cr: MovieComparisonResult) -> dict:
    """Serialise a MovieComparisonResult for JSON export."""

    def _metrics_dict(m: Optional[MovieMetrics]) -> Optional[dict]:
        return m.to_dict() if m is not None else None

    def _overlay_dict(ov: MovieTraceOverlay) -> dict:
        d: dict = {"label": ov.label}
        if ov.signal_a is not None:
            d["signal_a"] = ov.signal_a.tolist()
            d["times_a_s"] = (ov.times_a_s.tolist()
                              if ov.times_a_s is not None else None)
        if ov.signal_b is not None:
            d["signal_b"] = ov.signal_b.tolist()
            d["times_b_s"] = (ov.times_b_s.tolist()
                              if ov.times_b_s is not None else None)
        if ov.only_in:
            d["only_in"] = ov.only_in
        return d

    def _delta_dict(md: MovieMetricsDelta) -> dict:
        d: dict = {
            "label": md.label,
            "metrics_a": _metrics_dict(md.metrics_a),
            "metrics_b": _metrics_dict(md.metrics_b),
        }
        if md.has_both:
            d["deltas"] = {
                "peak_drr": md.delta_peak_drr,
                "peak_abs": md.delta_peak_abs,
                "peak_time_s": md.delta_peak_time_s,
                "mean_drr": md.delta_mean_drr,
                "temporal_std": md.delta_temporal_std,
            }
        return d

    def _summary_dict(s: MovieSessionSummary) -> dict:
        return {
            "label": s.label,
            "uid": s.uid,
            "n_frames": s.n_frames,
            "fps_achieved": s.fps_achieved,
            "exposure_us": s.exposure_us,
            "gain_db": s.gain_db,
            "duration_s": s.duration_s,
        }

    return {
        "format": "sanjinsight_movie_comparison_v1",
        "summary_a": _summary_dict(cr.summary_a),
        "summary_b": _summary_dict(cr.summary_b),
        "grids_differ": cr.grids_differ,
        "grid_note": cr.grid_note,
        "full_frame": _delta_dict(cr.full_frame),
        "full_frame_overlay": _overlay_dict(cr.full_frame_overlay),
        "roi_comparisons": [_delta_dict(d) for d in cr.roi_deltas],
        "roi_overlays": [_overlay_dict(o) for o in cr.roi_overlays],
        "unmatched_notes": cr.unmatched_notes,
    }
