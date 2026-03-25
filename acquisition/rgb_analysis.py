"""
acquisition/rgb_analysis.py

Utilities for per-channel RGB thermoreflectance analysis.

When using a color camera, the ΔR/R result is a (H, W, 3) array where
each channel represents a separate wavelength-dependent thermoreflectance
response.  This module provides tools to split, analyze, and compare
individual R/G/B thermoreflectance maps.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional, Dict

log = logging.getLogger(__name__)

CHANNEL_NAMES = {0: "red", 1: "green", 2: "blue"}


def split_channels(drr_rgb: np.ndarray) -> Dict[str, np.ndarray]:
    """Split an (H, W, 3) ΔR/R array into individual channel maps.

    Parameters
    ----------
    drr_rgb : ndarray, shape (H, W, 3) or (H, W)
        Multi-channel or single-channel ΔR/R data.

    Returns
    -------
    dict
        {"red": (H,W), "green": (H,W), "blue": (H,W)} for RGB input,
        or {"mono": (H,W)} for single-channel input.
    """
    if drr_rgb.ndim == 3 and drr_rgb.shape[2] == 3:
        return {
            "red":   drr_rgb[:, :, 0],
            "green": drr_rgb[:, :, 1],
            "blue":  drr_rgb[:, :, 2],
        }
    return {"mono": drr_rgb}


def to_luminance(drr_rgb: np.ndarray) -> np.ndarray:
    """Convert (H, W, 3) RGB ΔR/R to a single (H, W) luminance map.

    Uses Rec. 709 weights: Y = 0.2126·R + 0.7152·G + 0.0722·B.
    Returns the input unchanged if already 2D.
    """
    if drr_rgb.ndim == 3 and drr_rgb.shape[2] == 3:
        return (0.2126 * drr_rgb[:, :, 0]
                + 0.7152 * drr_rgb[:, :, 1]
                + 0.0722 * drr_rgb[:, :, 2])
    return drr_rgb


def per_channel_stats(drr_rgb: np.ndarray) -> Dict[str, dict]:
    """Compute basic statistics for each RGB channel.

    Returns
    -------
    dict
        {channel_name: {"mean": float, "std": float, "min": float,
                        "max": float, "peak_abs": float}}
    """
    channels = split_channels(drr_rgb)
    stats = {}
    for name, ch_data in channels.items():
        finite = ch_data[np.isfinite(ch_data)]
        if finite.size == 0:
            stats[name] = {"mean": 0.0, "std": 0.0, "min": 0.0,
                           "max": 0.0, "peak_abs": 0.0}
            continue
        stats[name] = {
            "mean":     float(np.mean(finite)),
            "std":      float(np.std(finite)),
            "min":      float(np.min(finite)),
            "max":      float(np.max(finite)),
            "peak_abs": float(np.max(np.abs(finite))),
        }
    return stats


def per_channel_analysis(drr_rgb: np.ndarray,
                         analysis_engine,
                         calibration=None) -> Dict[str, object]:
    """Run the analysis engine on each RGB channel independently.

    Parameters
    ----------
    drr_rgb : ndarray, shape (H, W, 3)
        Multi-channel ΔR/R data.
    analysis_engine : ThermalAnalysisEngine
        The analysis engine to run on each channel.
    calibration : optional
        Calibration object for ΔT conversion.

    Returns
    -------
    dict
        {channel_name: AnalysisResult} for each channel.
    """
    channels = split_channels(drr_rgb)
    results = {}
    for name, ch_data in channels.items():
        try:
            result = analysis_engine.run(ch_data, calibration=calibration)
            results[name] = result
        except Exception as exc:
            log.warning("Per-channel analysis failed for %s: %s", name, exc)
            results[name] = None   # preserve key so caller knows it was attempted
    return results
