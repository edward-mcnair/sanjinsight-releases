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
        "laplacian":  _laplacian,
        "tenengrad":  _tenengrad,
        "normalized": _normalized_laplacian,
        "fft":        _fft_power,
        "brenner":    _brenner,
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
