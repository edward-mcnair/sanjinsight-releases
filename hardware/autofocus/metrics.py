"""
hardware/autofocus/metrics.py

Focus quality metrics — algorithms that score how "in focus" an image is.
Higher score always means sharper focus regardless of which metric is used.

Available metrics:
    laplacian     Fast, robust general purpose. Best default choice.
    tenengrad     Good for low-contrast samples.
    normalized    Laplacian normalized by mean — good for varying brightness.
    fft           Frequency-domain method — best for periodic structures
                  (e.g. IC bond pads, gratings).
    brenner       Simple gradient sum — fast, works on coarse focus sweeps.
    subpixel_weighted
                  Sobel gradient variance weighted by local intensity —
                  more robust than Laplacian for thermoreflectance images
                  (low contrast).  Based on SubpixelShiftKernel.vi.

Sub-pixel peak localisation:
    estimate_best_z_subpixel(z_values, scores) -> float
                  Gaussian fit on coarse Z-scan scores for sub-pixel Z.
                  Replaces the simpler parabola used by find_peak().

Reference:
    Pertuz et al., "Analysis of focus measure operators for shape-from-focus"
    Pattern Recognition, 2013.
"""

import numpy as np


def score(image: np.ndarray, metric: str = "laplacian") -> float:
    """
    Compute a focus score for the given image.
    Higher = sharper = better focus.

    image:  2D numpy array (uint16 or float32)
    metric: one of laplacian | tenengrad | normalized | fft | brenner
    """
    # Work in float32, normalize to 0-1
    img = image.astype(np.float32)
    if img.max() > 1.0:
        img = img / img.max()

    fn = {
        "laplacian":         _laplacian,
        "tenengrad":         _tenengrad,
        "normalized":        _normalized_laplacian,
        "fft":               _fft_power,
        "brenner":           _brenner,
        "subpixel_weighted": focus_metric_subpixel_weighted,
    }.get(metric, _laplacian)

    return float(fn(img))


def _laplacian(img: np.ndarray) -> float:
    """Variance of Laplacian — fast and reliable."""
    # Simple discrete Laplacian kernel
    kern = np.array([[0, 1, 0],
                     [1,-4, 1],
                     [0, 1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import as_strided
    # Manual 2D convolution using numpy (avoids scipy/cv2 dependency)
    lap = _convolve2d(img, kern)
    return float(np.var(lap))


def _tenengrad(img: np.ndarray) -> float:
    """Tenengrad — sum of squared Sobel gradient magnitudes."""
    sx = _convolve2d(img, np.array([[-1,0,1],[-2,0,2],[-1,0,1]],
                                    dtype=np.float32))
    sy = _convolve2d(img, np.array([[-1,-2,-1],[0,0,0],[1,2,1]],
                                    dtype=np.float32))
    return float(np.mean(sx**2 + sy**2))


def _normalized_laplacian(img: np.ndarray) -> float:
    """Laplacian variance normalized by mean intensity."""
    mean = float(img.mean())
    if mean < 1e-6:
        return 0.0
    kern = np.array([[0,1,0],[1,-4,1],[0,1,0]], dtype=np.float32)
    lap  = _convolve2d(img, kern)
    return float(np.var(lap) / mean)


def _fft_power(img: np.ndarray) -> float:
    """High-frequency power in FFT — good for periodic structures."""
    F    = np.fft.fft2(img)
    Fsh  = np.fft.fftshift(F)
    mag  = np.abs(Fsh)
    h, w = mag.shape
    # Mask out center (low frequency) — keep outer 50%
    cy, cx = h // 2, w // 2
    Y, X   = np.ogrid[:h, :w]
    r      = np.sqrt((X - cx)**2 + (Y - cy)**2)
    mask   = r > min(h, w) * 0.15
    return float(mag[mask].mean())


def _brenner(img: np.ndarray) -> float:
    """Brenner gradient — simple and fast for coarse sweeps."""
    diff = img[:, 2:] - img[:, :-2]
    return float(np.sum(diff**2))


def _convolve2d(img: np.ndarray, kern: np.ndarray) -> np.ndarray:
    """Simple valid 2D convolution using numpy stride tricks."""
    img = np.ascontiguousarray(img)   # ensure C-contiguous before stride tricks
    kh, kw = kern.shape
    oh = img.shape[0] - kh + 1
    ow = img.shape[1] - kw + 1
    # Build view of all patches
    shape   = (oh, ow, kh, kw)
    strides = img.strides + img.strides
    patches = np.lib.stride_tricks.as_strided(img, shape=shape,
                                               strides=strides)
    return np.einsum('ijkl,kl->ij', patches, kern)


def find_peak(z_positions: list, scores: list) -> float:
    """
    Fit a parabola to the focus scores and return the Z position
    of the peak. Falls back to the position with the maximum score
    if fitting fails.

    z_positions: list of Z values (μm)
    scores:      corresponding focus scores
    """
    if len(z_positions) < 3:
        return z_positions[np.argmax(scores)]

    z = np.array(z_positions, dtype=np.float64)
    s = np.array(scores,      dtype=np.float64)

    try:
        coeffs = np.polyfit(z, s, 2)   # fit ax^2 + bx + c
        a, b   = coeffs[0], coeffs[1]
        if a < 0:                       # parabola opens downward — valid
            z_peak = -b / (2 * a)
            # Only trust if within the measured range
            if z.min() <= z_peak <= z.max():
                return float(z_peak)
    except Exception:
        pass

    return float(z[np.argmax(s)])


# ────────────────────────────────────────────────────────────────────────── #
#  Sub-pixel metric (SubpixelShiftKernel.vi)                                  #
# ────────────────────────────────────────────────────────────────────────────#


def focus_metric_subpixel_weighted(frame: np.ndarray,
                                   roi: tuple = None) -> float:
    """
    Compute a focus score using intensity-weighted Sobel gradient variance.

    More robust than the pure Laplacian for thermoreflectance images, which
    have low absolute contrast.  The intensity weighting suppresses the dark
    pixel bias that inflates Laplacian variance on images with large dark
    regions (e.g. bond pads outside the ROI).

    Based on SubpixelShiftKernel.vi (SanjVIEW FPGA autofocus kernel).

    Parameters
    ----------
    frame : 2-D numpy array, uint16 or float32.
    roi   : optional (y0, x0, y1, x1) tuple to restrict computation.
            Ignored if None.

    Returns
    -------
    float — focus score; higher = sharper.  Returns 0.0 for degenerate input.

    Algorithm
    ---------
    1. Extract ROI (if provided) and convert to float32 in [0, 1].
    2. Compute x- and y-gradient magnitude using Sobel operators via
       scipy.ndimage.sobel (full-frame, sub-pixel accurate).
    3. Weight gradient magnitude by normalised local intensity to suppress
       dark-pixel noise.
    4. Return variance of the weighted gradient map.
    """
    try:
        from scipy.ndimage import sobel as _sobel
    except ImportError:
        # scipy not available — fall back to the built-in tenengrad metric
        return _tenengrad(frame.astype(np.float32) /
                          (frame.max() or 1.0))

    img = frame.astype(np.float32)

    # ---- Apply ROI ----
    if roi is not None:
        y0, x0, y1, x1 = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
        img = img[y0:y1, x0:x1]

    if img.size == 0:
        return 0.0

    # ---- Normalise to [0, 1] ----
    i_max = float(img.max())
    if i_max < 1e-6:
        return 0.0
    img = img / i_max

    # ---- Sobel gradient magnitude ----
    gx  = _sobel(img, axis=1, mode="reflect")
    gy  = _sobel(img, axis=0, mode="reflect")
    mag = np.sqrt(gx ** 2 + gy ** 2)

    # ---- Intensity weight — local brightness in [0, 1] ----
    # Dark pixels contribute very little; bright (active) pixels dominate.
    weight      = img                          # simple intensity weight
    weight_sum  = float(weight.sum())
    if weight_sum < 1e-9:
        return 0.0

    weighted_mag = mag * weight

    # ---- Normalised variance of weighted gradient ----
    # Divide by mean to make the score invariant to overall brightness scale.
    wm_mean = float(weighted_mag.mean())
    if wm_mean < 1e-9:
        return 0.0

    return float(np.var(weighted_mag) / wm_mean)


# ────────────────────────────────────────────────────────────────────────── #
#  Sub-pixel Z-peak estimation                                                 #
# ────────────────────────────────────────────────────────────────────────────#


def estimate_best_z_subpixel(z_values: list, scores: list) -> float:
    """
    Estimate the true focus peak position with sub-pixel (sub-step) precision
    by fitting a Gaussian model to the score curve.

    This supersedes the simpler parabola fit used by find_peak() and is more
    accurate when the focus curve is slightly asymmetric (common in high-NA
    objectives or when the sample is tilted).

    Parameters
    ----------
    z_values : list of Z positions (μm) from a coarse or fine sweep.
    scores   : corresponding focus scores (higher = better).

    Returns
    -------
    float — sub-pixel Z position of the focus peak.

    Algorithm
    ---------
    1. Normalise scores to [0, 1] to improve numerical conditioning.
    2. Attempt a Gaussian fit:
           f(z) = A * exp(-0.5 * ((z - z0) / sigma)^2) + baseline
       with initial guesses from the data (argmax position, score range).
    3. Accept the Gaussian peak z0 only if:
         - The fit converged without exception.
         - The fitted peak lies within [z_min, z_max].
         - The score dynamic range is at least 5 % of the max (avoids
           fitting noise on flat score curves, which is common when the
           sample is very far from focus on a coarse sweep).
         - sigma is positive and physically plausible (> 0.1 µm).
    4. Fall back to the parabola fit (find_peak) if the Gaussian fails.
    5. Fall back to argmax if the parabola fit also fails.

    Notes
    -----
    Requires scipy.  If scipy is not installed, falls back to find_peak().
    """
    if len(z_values) < 3:
        idx = int(np.argmax(scores))
        return float(z_values[idx])

    z = np.array(z_values, dtype=np.float64)
    s = np.array(scores,   dtype=np.float64)

    # ---- Dynamic range check ----
    s_max = float(s.max())
    s_min = float(s.min())
    dynamic_range = s_max - s_min
    if s_max < 1e-30 or dynamic_range / s_max < 0.05:
        # Score curve is essentially flat — argmax is as good as any fit.
        return float(z[np.argmax(s)])

    # ---- Normalise ----
    s_norm = (s - s_min) / dynamic_range   # [0, 1]

    best_idx = int(np.argmax(s_norm))
    z0_guess = float(z[best_idx])

    # Estimate sigma from the half-width at half-maximum (HWHM) region
    half_max    = 0.5
    above_half  = z[s_norm >= half_max]
    sigma_guess = (float(above_half.max() - above_half.min()) / 2.35
                   if len(above_half) >= 2 else
                   abs(float(z[-1] - z[0])) / 4.0)
    sigma_guess = max(sigma_guess, abs(z[1] - z[0]) * 0.5)

    # ---- Attempt Gaussian fit ----
    try:
        from scipy.optimize import curve_fit as _curve_fit

        def _gaussian(z_arr, amplitude, z_center, sigma, baseline):
            return (amplitude * np.exp(-0.5 * ((z_arr - z_center) / sigma) ** 2)
                    + baseline)

        p0     = [1.0, z0_guess, sigma_guess, 0.0]
        bounds = ([0.0, z.min(), 1e-4, -0.5],
                  [1.5, z.max(), abs(z[-1] - z[0]) * 2.0, 0.5])

        popt, _ = _curve_fit(_gaussian, z, s_norm,
                             p0=p0, bounds=bounds, maxfev=2000)

        amplitude, z_center, sigma, baseline = popt

        # Validate result
        if (amplitude > 0.02
                and z.min() <= z_center <= z.max()
                and sigma > 0.1):
            return float(z_center)

    except Exception:
        pass

    # ---- Fall back to parabola (find_peak) ----
    return find_peak(z_values, scores)
