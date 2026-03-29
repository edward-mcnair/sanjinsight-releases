"""
acquisition/image_metrics.py

Shared, stateless image-quality metrics used by both the real-time
MetricsService (ai/metrics_service.py) and the pre-capture preflight
validator (acquisition/preflight.py).

All functions are pure NumPy — no Qt, no hardware, no side-effects.
"""

from __future__ import annotations

import numpy as np


def compute_focus(data: np.ndarray) -> float:
    """
    Variance of the discrete Laplacian on a 4x downsampled frame.

    Higher values indicate sharper focus.  Uses second finite differences
    so no boundary padding is needed.  Fast even on 1920x1200 frames
    because the downsampled array is only 480x300.

    For multi-channel (H, W, 3) input, luminance is used.
    """
    if data.ndim == 3:
        data = data.mean(axis=2)
    ds = data[::4, ::4].astype(np.float32)
    if ds.shape[0] < 3 or ds.shape[1] < 3:
        return 0.0
    d2y = ds[2:, :] - 2.0 * ds[1:-1, :] + ds[:-2, :]
    d2x = ds[:, 2:] - 2.0 * ds[:, 1:-1] + ds[:, :-2]
    r = min(d2y.shape[0], d2x.shape[0])
    c = min(d2y.shape[1], d2x.shape[1])
    lap = d2y[:r, :c] + d2x[:r, :c]
    return float(np.var(lap))


def compute_intensity_stats(data: np.ndarray, bit_depth: int = 12) -> dict:
    """
    Compute exposure-related statistics for a single frame.

    Returns
    -------
    dict with keys:
        mean_frac  — mean intensity as fraction of dynamic range (0-1)
        max_frac   — max intensity as fraction of dynamic range (0-1)
        sat_pct    — % of pixels >= 98% of full scale
        under_pct  — % of pixels <= 1.5% of full scale
    """
    if data.ndim == 3:
        data = data.mean(axis=2)
    d = data.astype(np.float64)
    full_scale = float((1 << bit_depth) - 1) or 4095.0
    n_pixels = max(d.size, 1)

    mean_frac = float(d.mean()) / full_scale
    max_frac = float(d.max()) / full_scale
    sat_pct = float(np.count_nonzero(d >= full_scale * 0.98)) / n_pixels * 100.0
    under_pct = float(np.count_nonzero(d <= full_scale * 0.015)) / n_pixels * 100.0

    return {
        "mean_frac": mean_frac,
        "max_frac": max_frac,
        "sat_pct": sat_pct,
        "under_pct": under_pct,
    }


def compute_frame_stability(means: list) -> float:
    """
    Coefficient of variation (CV) across a sequence of per-frame mean values.

    CV = std(means) / mean(means).  Returns 0.0 if fewer than 2 values
    or if the mean is zero.
    """
    if len(means) < 2:
        return 0.0
    arr = np.array(means, dtype=np.float64)
    m = float(arr.mean())
    if m == 0.0:
        return 0.0
    return float(arr.std()) / m
