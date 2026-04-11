"""
acquisition/roi_extraction.py

Shared ROI-signal extraction from 3-D cubes.

Given a (N, H, W) cube (ΔR/R or raw intensity) and the current ROI set,
extracts the per-ROI mean signal as a list of (label, color, signal_1d)
tuples — the format consumed by TransientTraceChart.set_roi_curves().

Used by both TransientTab and MovieTab to avoid duplicated extraction logic.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np


def extract_roi_signals(
    cube: np.ndarray,
    rois,
    mask_cache: Optional[dict] = None,
) -> List[Tuple[str, str, np.ndarray]]:
    """Extract per-ROI mean signal from a 3-D cube.

    Parameters
    ----------
    cube : (N, H, W) ndarray
        Time-resolved data cube (ΔR/R or raw frames).
    rois : iterable of Roi
        ROI objects with ``is_empty``, ``clamp(h, w)``, ``is_ellipse``,
        ``is_freeform``, ``mask(shape)``, ``uid``, ``label``, ``color`` attrs.
    mask_cache : dict or None
        Optional mutable dict for caching boolean masks of non-rectangular
        ROIs.  Keyed on ``(roi.uid, H, W)``.  Pass the same dict across
        calls to avoid recomputation.  ``None`` disables caching.

    Returns
    -------
    list of (label, hex_color, signal_1d)
        Each ``signal_1d`` is a (N,) float64 array of the per-frame
        spatial mean within the ROI.
    """
    n, h, w = cube.shape
    signals: List[Tuple[str, str, np.ndarray]] = []

    for roi in rois:
        if roi.is_empty:
            continue
        clamped = roi.clamp(h, w)
        if clamped.w <= 0 or clamped.h <= 0:
            continue

        if roi.is_ellipse or roi.is_freeform:
            # Mask-based extraction for non-rectangular shapes
            cache_key = (roi.uid, h, w)
            m = None
            if mask_cache is not None:
                m = mask_cache.get(cache_key)
            if m is None:
                m = clamped.mask((h, w))
                if mask_cache is not None:
                    mask_cache[cache_key] = m
            # Vectorised: apply mask once to flattened spatial dims
            signal = np.nanmean(cube[:, m], axis=1)
        else:
            sub = cube[:, clamped.y:clamped.y2, clamped.x:clamped.x2]
            signal = np.nanmean(sub.reshape(n, -1), axis=1)

        label = roi.label or roi.uid[:6]
        color = roi.color or "#ffffff"
        signals.append((label, color, signal))

    return signals
