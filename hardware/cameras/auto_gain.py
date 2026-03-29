"""
hardware/cameras/auto_gain.py

Temporal-noise-based auto-gain optimisation.

Complements auto-exposure by finding the highest gain that still improves
SNR.  As gain increases, both signal and noise are amplified — but above a
certain point, read-noise amplification dominates and SNR starts to drop.
This algorithm sweeps gain in coarse steps, measures temporal noise from
multiple frames, and picks the gain level with the best SNR.

Usage
-----
    from hardware.cameras.auto_gain import auto_gain

    result = auto_gain(cam, target_snr_db=20.0)
    # result.gain_db     — optimal gain
    # result.snr_db      — achieved SNR
    # result.converged   — True if a clear optimum was found
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class AutoGainResult:
    """Result of an auto-gain run."""
    gain_db:    float     # final gain setting
    snr_db:     float     # estimated SNR at that gain
    converged:  bool      # True if a clear optimum was found
    iterations: int       # number of gain levels tested
    elapsed_s:  float     # wall-clock time
    message:    str       # human-readable summary


def _measure_temporal_snr(cam, n_frames: int = 5,
                          settle_ms: float = 100.0) -> tuple[float, float]:
    """Measure signal mean and temporal noise from *n_frames*.

    Returns (signal_mean, noise_std) where both are in raw counts.
    Temporal noise is the per-pixel standard deviation across frames,
    then averaged over the frame — more robust than spatial noise on
    structured samples.
    """
    time.sleep(settle_ms / 1000.0)

    frames = []
    for _ in range(n_frames + 1):   # grab one extra to discard first
        try:
            f = cam.grab(timeout_ms=2000)
            if f is not None:
                d = f.data.astype(np.float32)
                if d.ndim == 3:
                    d = d[:, :, 0]
                frames.append(d)
        except Exception:
            break

    if len(frames) < 3:
        return 0.0, 1.0   # not enough frames

    # Discard first frame (may have old exposure)
    frames = frames[1:]
    stack = np.stack(frames, axis=0)               # (N, H, W)
    signal = float(stack.mean())
    noise  = float(stack.std(axis=0).mean())        # temporal noise
    return signal, max(noise, 1e-6)


def auto_gain(
    cam,
    target_snr_db: float = 20.0,
    max_gain_db: float = 18.0,
    step_db: float = 2.0,
    n_frames: int = 5,
    settle_ms: float = 150.0,
    progress_cb=None,
) -> AutoGainResult:
    """Find the gain level that maximises SNR up to *max_gain_db*.

    Parameters
    ----------
    cam : CameraDriver
        Camera instance (must support set_gain, get_gain, gain_range, grab).
    target_snr_db : float
        Minimum acceptable SNR in dB.  If achieved at minimum gain, the
        algorithm stops early.
    max_gain_db : float
        Safety cap — never exceed this gain regardless of SNR.
    step_db : float
        Coarse sweep step size in dB.
    n_frames : int
        Frames per measurement for temporal noise estimation.
    settle_ms : float
        Wait time after changing gain before measuring.
    progress_cb : callable, optional
        Called with (current_gain_db, snr_db, step_index, total_steps).

    Returns
    -------
    AutoGainResult
    """
    t0 = time.monotonic()

    if cam is None:
        return AutoGainResult(
            gain_db=0.0, snr_db=0.0, converged=False,
            iterations=0, elapsed_s=0.0, message="No camera connected")

    g_min, g_max = cam.gain_range()
    g_max = min(g_max, max_gain_db)
    original_gain = cam.get_gain()

    # Build sweep points
    gains = []
    g = g_min
    while g <= g_max:
        gains.append(round(g, 1))
        g += step_db
    if not gains:
        gains = [g_min]

    best_gain = g_min
    best_snr = 0.0
    results: list[tuple[float, float]] = []   # (gain, snr_db)

    for i, gain in enumerate(gains):
        cam.set_gain(gain)
        signal, noise = _measure_temporal_snr(cam, n_frames, settle_ms)

        snr_linear = signal / noise
        snr_db = 20.0 * np.log10(snr_linear) if snr_linear > 0 else 0.0
        results.append((gain, snr_db))

        log.debug("Auto-gain step %d/%d: gain=%.1f dB, SNR=%.1f dB",
                  i + 1, len(gains), gain, snr_db)

        if progress_cb:
            try:
                progress_cb(gain, snr_db, i, len(gains))
            except Exception:
                pass

        if snr_db > best_snr:
            best_snr = snr_db
            best_gain = gain

        # Early stop: if SNR already exceeds target at minimum gain,
        # no reason to add noise by increasing gain
        if i == 0 and snr_db >= target_snr_db:
            cam.set_gain(g_min)
            return AutoGainResult(
                gain_db=g_min, snr_db=snr_db, converged=True,
                iterations=1, elapsed_s=time.monotonic() - t0,
                message=f"SNR {snr_db:.1f} dB at minimum gain "
                        f"({g_min:.1f} dB) — no gain increase needed")

        # Early stop: if SNR is now dropping, we passed the optimum
        if len(results) >= 3:
            last3 = [r[1] for r in results[-3:]]
            if last3[-1] < last3[-2] < last3[-3]:
                log.debug("Auto-gain: SNR declining — stopping at %.1f dB",
                          best_gain)
                break

    # Apply best gain
    cam.set_gain(best_gain)

    converged = best_snr >= target_snr_db
    elapsed = time.monotonic() - t0

    return AutoGainResult(
        gain_db=best_gain,
        snr_db=best_snr,
        converged=converged,
        iterations=len(results),
        elapsed_s=elapsed,
        message=f"Auto-gain: {best_gain:.1f} dB "
                f"(SNR {best_snr:.1f} dB, {len(results)} steps, "
                f"{elapsed:.1f}s)")
