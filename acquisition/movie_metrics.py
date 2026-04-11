"""
acquisition/movie_metrics.py

Pure-numpy per-ROI metric computation for movie-mode acquisitions.

Movie mode is a free-running burst capture with no trigger synchronisation.
The metrics reflect continuous thermal evolution — no pulse-response
semantics (no baseline window, no recovery ratio).

Given a 1-D mean ΔR/R signal and its corresponding timestamp array, computes:

  • Peak ΔR/R          — signed value at argmax(|signal|)
  • Peak |ΔR/R|        — absolute magnitude of the peak
  • Peak frame index   — integer index where peak occurs
  • Peak time (s)      — timestamp at peak frame
  • Mean ΔR/R          — temporal mean of the entire signal
  • Temporal σ          — std-dev across all frames (noise / activity indicator)

All functions are numpy-only — no Qt, no external dependencies.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class MovieMetrics:
    """Computed metrics for a single ROI (or full-frame) movie signal."""

    roi_label:      str   = ""
    roi_color:      str   = "#ffffff"

    peak_drr:       float = 0.0   # signed peak ΔR/R
    peak_abs:       float = 0.0   # |peak ΔR/R|
    peak_index:     int   = 0     # frame index of peak
    peak_time_s:    float = 0.0   # timestamp at peak

    mean_drr:       float = 0.0   # temporal mean
    temporal_std:   float = 0.0   # temporal σ

    n_frames:       int   = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MovieMetrics":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def compute_movie_metrics(
    signal: np.ndarray,
    timestamps_s: np.ndarray,
    roi_label: str = "",
    roi_color: str = "#ffffff",
) -> MovieMetrics:
    """Compute movie metrics for a single 1-D signal.

    Parameters
    ----------
    signal : (N,) float
        Per-frame mean ΔR/R values for one ROI (or full frame).
    timestamps_s : (N,) float
        Corresponding timestamps in seconds from recording start.
    roi_label : str
        Human-readable label for the ROI.
    roi_color : str
        Hex colour string for display.

    Returns
    -------
    MovieMetrics
        Fully populated metrics dataclass.
    """
    sig = np.asarray(signal, dtype=np.float64)
    ts  = np.asarray(timestamps_s, dtype=np.float64)
    n   = len(sig)

    if n < 1:
        return MovieMetrics(roi_label=roi_label, roi_color=roi_color)

    # ── Peak (argmax of |signal|) ─────────────────────────────────────
    abs_sig   = np.abs(sig)
    peak_idx  = int(np.nanargmax(abs_sig))
    peak_val  = float(sig[peak_idx])           # signed
    peak_abs  = float(abs_sig[peak_idx])
    peak_time = float(ts[peak_idx]) if peak_idx < len(ts) else 0.0

    # ── Mean and σ ────────────────────────────────────────────────────
    mean_val  = float(np.nanmean(sig))
    std_val   = float(np.nanstd(sig, ddof=0))

    return MovieMetrics(
        roi_label    = roi_label,
        roi_color    = roi_color,
        peak_drr     = peak_val,
        peak_abs     = peak_abs,
        peak_index   = peak_idx,
        peak_time_s  = peak_time,
        mean_drr     = mean_val,
        temporal_std = std_val,
        n_frames     = n,
    )


def compute_all_movie_roi_metrics(
    roi_signals: list[tuple[str, str, np.ndarray]],
    timestamps_s: np.ndarray,
) -> List[MovieMetrics]:
    """Compute metrics for every ROI signal.

    Parameters
    ----------
    roi_signals : list of (label, hex_color, signal_1d)
        Same format as TransientTraceChart.set_roi_curves() input.
    timestamps_s : (N,) float
        Shared timestamps.

    Returns
    -------
    list of MovieMetrics
    """
    return [
        compute_movie_metrics(sig, timestamps_s, label, color)
        for label, color, sig in roi_signals
    ]
