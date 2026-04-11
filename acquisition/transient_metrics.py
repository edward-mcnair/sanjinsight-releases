"""
acquisition/transient_metrics.py

Pure-numpy per-ROI transient metric computation.

Given a 1-D ΔR/R signal and its corresponding delay-time array, computes:

  • Peak ΔR/R          — signed peak value (at argmax of |signal|)
  • Peak |ΔR/R|        — absolute magnitude of the peak
  • Time-to-peak (s)   — delay at which peak occurs
  • Baseline mean      — mean of the earliest baseline window
  • Baseline noise σ   — std-dev of the baseline window
  • Peak SNR           — |peak − baseline_mean| / baseline_σ
  • Recovery ratio     — how far the signal returns toward baseline at the end
                         (1.0 = full recovery, 0.0 = no recovery)

Baseline window: the earliest  max(3, ceil(0.1 × N))  points of the signal.
Peak detection : argmax(abs(signal)), preserving the signed value.

All functions are numpy-only — no Qt, no external dependencies.
"""

from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class TransientMetrics:
    """Computed metrics for a single ROI (or full-frame) transient signal."""

    roi_label:      str   = ""
    roi_color:      str   = "#ffffff"

    peak_drr:       float = 0.0   # signed peak ΔR/R
    peak_abs:       float = 0.0   # |peak ΔR/R|
    peak_index:     int   = 0     # index of peak in signal array
    time_to_peak_s: float = 0.0   # delay at peak

    baseline_mean:  float = 0.0
    baseline_std:   float = 0.0   # σ of the baseline window

    peak_snr:       float = 0.0   # |peak − baseline_mean| / σ
    recovery_ratio: float = 0.0   # 1.0 = full recovery toward baseline

    n_points:       int   = 0
    baseline_n:     int   = 0     # how many points used for baseline

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TransientMetrics":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def baseline_window_size(n: int) -> int:
    """Return the number of earliest points to use as baseline.

    Rule: max(3, ceil(0.1 × N))  — always at least 3 points, or 10% of
    the signal length, whichever is larger.
    """
    return max(3, math.ceil(0.1 * n))


def compute_transient_metrics(
    signal: np.ndarray,
    delay_times_s: np.ndarray,
    roi_label: str = "",
    roi_color: str = "#ffffff",
) -> TransientMetrics:
    """Compute transient metrics for a single 1-D ΔR/R signal.

    Parameters
    ----------
    signal : (N,) float
        Per-delay mean ΔR/R values for one ROI (or full frame).
    delay_times_s : (N,) float
        Corresponding delay times in seconds.
    roi_label : str
        Human-readable label for the ROI.
    roi_color : str
        Hex colour string for display.

    Returns
    -------
    TransientMetrics
        Fully populated metrics dataclass.
    """
    sig = np.asarray(signal, dtype=np.float64)
    ts  = np.asarray(delay_times_s, dtype=np.float64)
    n   = len(sig)

    if n < 2:
        return TransientMetrics(roi_label=roi_label, roi_color=roi_color,
                                n_points=n)

    # ── Baseline ──────────────────────────────────────────────────────
    bw = baseline_window_size(n)
    baseline = sig[:bw]
    bl_mean  = float(np.nanmean(baseline))
    bl_std   = float(np.nanstd(baseline, ddof=0))

    # ── Peak (argmax of |signal|) ─────────────────────────────────────
    abs_sig    = np.abs(sig)
    peak_idx   = int(np.nanargmax(abs_sig))
    peak_val   = float(sig[peak_idx])           # signed
    peak_abs   = float(abs_sig[peak_idx])
    ttp        = float(ts[peak_idx]) if peak_idx < len(ts) else 0.0

    # ── SNR ───────────────────────────────────────────────────────────
    if bl_std > 0:
        snr = abs(peak_val - bl_mean) / bl_std
    else:
        snr = 0.0

    # ── Recovery ratio ────────────────────────────────────────────────
    # Recovery = how much the signal returns toward baseline at the end.
    # We use the mean of the last `bw` points as the "tail" value.
    tail = sig[-bw:]
    tail_mean = float(np.nanmean(tail))
    deviation_at_peak = peak_val - bl_mean
    deviation_at_tail = tail_mean - bl_mean
    if abs(deviation_at_peak) > 1e-30:
        # fraction recovered: 1 − (remaining deviation / peak deviation)
        recovery = 1.0 - (deviation_at_tail / deviation_at_peak)
        recovery = float(np.clip(recovery, 0.0, 1.0))
    else:
        recovery = 1.0  # flat signal — "fully recovered"

    return TransientMetrics(
        roi_label      = roi_label,
        roi_color      = roi_color,
        peak_drr       = peak_val,
        peak_abs       = peak_abs,
        peak_index     = peak_idx,
        time_to_peak_s = ttp,
        baseline_mean  = bl_mean,
        baseline_std   = bl_std,
        peak_snr       = snr,
        recovery_ratio = recovery,
        n_points       = n,
        baseline_n     = bw,
    )


def compute_all_roi_metrics(
    roi_signals: list[tuple[str, str, np.ndarray]],
    delay_times_s: np.ndarray,
) -> list[TransientMetrics]:
    """Compute metrics for every ROI signal.

    Parameters
    ----------
    roi_signals : list of (label, hex_color, signal_1d)
        Same format as TransientTraceChart.set_roi_curves() input.
    delay_times_s : (N,) float
        Shared delay times.

    Returns
    -------
    list of TransientMetrics
    """
    return [
        compute_transient_metrics(sig, delay_times_s, label, color)
        for label, color, sig in roi_signals
    ]
