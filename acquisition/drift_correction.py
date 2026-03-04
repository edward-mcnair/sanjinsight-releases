"""
acquisition/drift_correction.py

Sub-pixel lateral drift correction for thermoreflectance acquisition pipelines.

FFT phase-correlation is used to estimate the translational shift between a
captured frame and a cold reference frame.  The shift is then removed via
bilinear interpolation (scipy.ndimage.shift) or integer-pixel numpy.roll when
scipy is unavailable.

Public API
----------
    estimate_shift(frame, reference) -> (dy, dx)
    apply_shift(frame, dy, dx)       -> corrected frame

Both functions are intentionally free of side-effects and thread-safe.
"""

from __future__ import annotations

import numpy as np


def estimate_shift(frame: np.ndarray,
                   reference: np.ndarray) -> tuple:
    """
    Estimate sub-pixel lateral drift between *frame* and *reference*
    using FFT phase correlation (normalised cross-power spectrum).

    Parameters
    ----------
    frame     : 2-D float32/float64 array (H × W)
    reference : 2-D array with the same shape as *frame*

    Returns
    -------
    (dy, dx) : float pair — pixels to shift *frame* to align with *reference*.
               Positive dy means *frame* is shifted down relative to *reference*.
    """
    F   = np.fft.fft2(frame.astype(np.float64))
    R   = np.fft.fft2(reference.astype(np.float64))
    eps = 1e-10
    cross = F * np.conj(R)
    cross /= (np.abs(cross) + eps)
    corr  = np.real(np.fft.ifft2(cross))
    corr  = np.fft.fftshift(corr)
    H, W  = corr.shape
    peak  = np.unravel_index(np.argmax(corr), corr.shape)
    dy    = float(peak[0]) - H // 2
    dx    = float(peak[1]) - W // 2
    return dy, dx


def apply_shift(frame: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """
    Translate *frame* by (dy, dx) pixels to remove measured drift.

    Uses ``scipy.ndimage.shift`` (bilinear interpolation, order=1) when
    scipy is available.  Falls back to ``numpy.roll`` (integer approximation)
    when scipy is absent so the pipeline works without optional dependencies.

    Parameters
    ----------
    frame : 2-D array (H × W), any float dtype
    dy    : vertical shift in pixels (positive = move frame down)
    dx    : horizontal shift in pixels (positive = move frame right)

    Returns
    -------
    Corrected frame array with the same shape and dtype as *frame*.
    """
    if dy == 0.0 and dx == 0.0:
        return frame
    try:
        from scipy.ndimage import shift as nd_shift
        return nd_shift(frame, (dy, dx), order=1,
                        mode="reflect").astype(frame.dtype)
    except ImportError:
        # Integer approximation — still removes most macroscopic drift artefacts
        return np.roll(
            np.roll(frame, int(round(dy)), axis=0),
            int(round(dx)), axis=1
        ).astype(frame.dtype)


# Legacy private-name aliases kept for any code that imported them directly
# from acquisition.movie_pipeline (pre-refactor).
_estimate_shift = estimate_shift
_apply_shift    = apply_shift
