"""
acquisition/image_filters.py — Image processing filters for thermoreflectance imaging.

All functions accept and return float32 numpy arrays (H, W) unless otherwise noted.
NaN values in input are preserved/handled gracefully throughout.

Algorithms derived from SanjVIEW LabVIEW implementation:
  shadow_correct()    ← shadow_filter2.vi
  bilinear_stitch()   ← BilinearInterpolation kernal.vi
  subpixel_register() ← find_shift_digital_subpixel_subset.vi + Subpixel_Shift.vi
  align_to_reference()← Align_2_Images.vi
  median_filter_2d()  ← Med Filter X.vi / Filter_1D_LP_Median.vi
  lowpass_gaussian()  ← Image_Filter_Low_pass.vi
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional

import numpy as np
from scipy.ndimage import (
    gaussian_filter,
    generic_filter,
    map_coordinates,
    shift as nd_shift,
)

log = logging.getLogger(__name__)


# ── NaN helpers ────────────────────────────────────────────────────────────────


def replace_nans(
    image: np.ndarray,
    method: str = "median",
    kernel_size: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Replace NaN pixels with a local estimate and return the filled image
    together with a boolean mask of the original NaN positions.

    Algorithm
    ---------
    For method "median" and "mean" the image is processed with
    scipy.ndimage.generic_filter using np.nanmedian / np.nanmean over a
    (kernel_size × kernel_size) neighbourhood.  NaN positions in the output
    of generic_filter are replaced by the global nanmedian/nanmean as a last
    resort (handles all-NaN patches).  For method "zero" every NaN is set
    directly to 0.

    Parameters
    ----------
    image       : float32 (H, W) input, may contain NaNs.
    method      : "median" | "mean" | "zero"
    kernel_size : neighbourhood diameter (must be odd, ≥ 3).

    Returns
    -------
    (filled_image, nan_mask)
        filled_image : float32 (H, W) with no NaNs.
        nan_mask     : bool   (H, W) — True where original image was NaN.
    """
    img = image.astype(np.float32)
    nan_mask = ~np.isfinite(img)

    if not nan_mask.any():
        return img.copy(), nan_mask

    if method == "zero":
        out = img.copy()
        out[nan_mask] = 0.0
        return out, nan_mask

    if kernel_size % 2 == 0:
        kernel_size += 1  # ensure odd

    if method == "median":
        fn = np.nanmedian
    elif method == "mean":
        fn = np.nanmean
    else:
        raise ValueError(f"replace_nans: unknown method {method!r}. "
                         "Use 'median', 'mean', or 'zero'.")

    # global fallback for all-NaN patches
    global_fill = float(fn(img[np.isfinite(img)])) if np.isfinite(img).any() else 0.0

    filtered = generic_filter(img, fn, size=kernel_size, mode="reflect")
    # generic_filter passes NaN through to np.nanmedian/mean when all
    # neighbours are NaN — use global_fill in that case.
    filtered = np.where(np.isfinite(filtered), filtered, global_fill)

    out = img.copy()
    out[nan_mask] = filtered[nan_mask]
    return out.astype(np.float32), nan_mask


# ── Core filters ───────────────────────────────────────────────────────────────


def shadow_correct(
    image: np.ndarray,
    reference: Optional[np.ndarray] = None,
    kernel_size: int = 64,
) -> np.ndarray:
    """
    Remove non-uniform illumination (shading / shadow) from a thermoreflectance
    image.

    Algorithm
    ---------
    Corresponds to shadow_filter2.vi in the SanjVIEW LabVIEW implementation.

    Two modes:

    *Self-correction* (reference is None):
        A smooth estimate of the illumination envelope is built by applying a
        large-sigma Gaussian blur (sigma = kernel_size pixels) to the image
        itself.  The image is then divided by that envelope.  This works well
        when the signal of interest (ΔR/R) is small compared to the
        illumination variation, which is typically the case in
        thermoreflectance.

    *Reference correction* (reference provided):
        The image is divided element-wise by the reference frame.  The
        reference should be a flat-field or shading reference captured under
        identical illumination conditions (see compute_shading_reference()).

    In both cases the result is mean-normalised: multiplied by the mean of the
    reference (or smoothed self) so that the absolute intensity scale is
    preserved.

    NaN handling: NaN pixels are filled with the local median before Gaussian
    filtering, then restored after normalisation.

    Parameters
    ----------
    image       : float32 (H, W) input frame.
    reference   : float32 (H, W) flat-field reference, or None for
                  self-correction.
    kernel_size : Gaussian sigma in pixels used in self-correction mode.
                  Should be large relative to the spatial frequency of the
                  signal of interest (default 64 px).

    Returns
    -------
    float32 (H, W) shading-corrected image at the same mean intensity level
    as the reference (or smoothed image).
    """
    img = image.astype(np.float32)
    nan_mask = ~np.isfinite(img)

    # Fill NaNs before filtering so the Gaussian is not contaminated.
    if nan_mask.any():
        img_filled, _ = replace_nans(img, method="median", kernel_size=5)
    else:
        img_filled = img.copy()

    if reference is None:
        # Build illumination envelope from the image itself.
        envelope = gaussian_filter(img_filled.astype(np.float64),
                                   sigma=float(kernel_size))
        ref_mean = float(np.nanmean(img_filled))
    else:
        ref = reference.astype(np.float32)
        ref_filled, _ = replace_nans(ref, method="median", kernel_size=5)
        envelope = ref_filled.astype(np.float64)
        ref_mean = float(np.nanmean(ref_filled))

    # Avoid division by zero: clamp envelope to a small positive floor.
    env_floor = max(np.finfo(np.float32).eps, float(np.nanmax(np.abs(envelope))) * 1e-6)
    envelope_safe = np.where(np.abs(envelope) < env_floor, env_floor, envelope)

    corrected = (img_filled.astype(np.float64) / envelope_safe) * ref_mean

    # Restore NaN positions.
    result = corrected.astype(np.float32)
    if nan_mask.any():
        result[nan_mask] = np.nan

    return result


def median_filter_2d(image: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """
    Spatial median filter with NaN-aware implementation.

    Algorithm
    ---------
    Corresponds to Med Filter X.vi / Filter_1D_LP_Median.vi in SanjVIEW.
    Uses scipy.ndimage.generic_filter with np.nanmedian as the footprint
    function so that NaN pixels in the neighbourhood are ignored rather than
    propagated.  The NaN mask of the input is restored in the output.

    Parameters
    ----------
    image       : float32 (H, W).
    kernel_size : square kernel side length in pixels (must be odd; if even,
                  incremented by 1).

    Returns
    -------
    float32 (H, W) median-filtered image.
    """
    if kernel_size < 1:
        raise ValueError("kernel_size must be ≥ 1.")
    if kernel_size % 2 == 0:
        kernel_size += 1

    img = image.astype(np.float32)
    nan_mask = ~np.isfinite(img)

    # Replace NaNs so generic_filter has a full grid to work on.
    if nan_mask.any():
        img_filled, _ = replace_nans(img, method="median", kernel_size=kernel_size)
    else:
        img_filled = img.copy()

    result = generic_filter(img_filled.astype(np.float64),
                            np.nanmedian, size=kernel_size,
                            mode="reflect").astype(np.float32)

    if nan_mask.any():
        result[nan_mask] = np.nan

    return result


def lowpass_gaussian(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """
    Gaussian spatial low-pass filter with NaN-aware normalisation.

    Algorithm
    ---------
    Corresponds to Image_Filter_Low_pass.vi in SanjVIEW.
    A standard Gaussian blur (scipy.ndimage.gaussian_filter) is applied.  To
    handle NaN pixels correctly the filtered image is divided by a similarly
    filtered binary validity mask so that NaN pixels do not introduce a pull
    towards zero in their neighbourhood — equivalent to computing a
    weighted-average that excludes missing data.

    This is the standard approach for NaN-aware Gaussian smoothing without
    requiring a pixel-by-pixel loop.

    Parameters
    ----------
    image : float32 (H, W).
    sigma : Gaussian standard deviation in pixels.

    Returns
    -------
    float32 (H, W) low-pass filtered image.  Pixels where the validity mask
    falls below 1% (nearly isolated NaN clusters) are set to NaN.
    """
    if sigma <= 0:
        raise ValueError("sigma must be > 0.")

    img = image.astype(np.float64)
    valid = np.where(np.isfinite(img), 1.0, 0.0)
    img_filled = np.where(np.isfinite(img), img, 0.0)

    # Filter numerator (zero-filled data) and denominator (validity weight).
    num = gaussian_filter(img_filled, sigma=sigma)
    den = gaussian_filter(valid,      sigma=sigma)

    # Avoid divide-by-near-zero at isolated NaN clusters.
    result = np.where(den > 0.01, num / den, np.nan)

    nan_mask = ~np.isfinite(image)
    out = result.astype(np.float32)
    if nan_mask.any():
        out[nan_mask] = np.nan

    return out


# ── Registration ───────────────────────────────────────────────────────────────


def subpixel_register(
    image: np.ndarray,
    reference: np.ndarray,
    upsample_factor: int = 10,
    max_shift_px: float = 20.0,
) -> tuple[np.ndarray, tuple[float, float]]:
    """
    Sub-pixel image registration via FFT phase-correlation with DFT upsampling.

    Algorithm
    ---------
    Corresponds to find_shift_digital_subpixel_subset.vi + Subpixel_Shift.vi
    in SanjVIEW.

    The normalised cross-power spectrum of the two images is computed via FFT.
    An initial integer-pixel shift is found from the location of the peak of
    the inverse FFT.  A Discrete Fourier Transform (DFT) upsampled by
    *upsample_factor* is then evaluated over a small neighbourhood around that
    peak to achieve sub-pixel precision.  This is the method of Guizar-Sicairos
    et al. (2008), "Efficient subpixel image registration algorithms," Optics
    Letters 33(2):156-158.

    The resulting shift is applied with scipy.ndimage.shift (bilinear
    interpolation, order=1) to produce the registered image.

    Parameters
    ----------
    image          : float32 (H, W) — the frame to be registered.
    reference      : float32 (H, W) — the reference frame.
    upsample_factor: registration precision = 1/upsample_factor pixels
                     (10 → 0.1 px, 20 → 0.05 px).
    max_shift_px   : reject shifts larger than this in either axis.
                     Returns (image, (0.0, 0.0)) with a warning if exceeded.

    Returns
    -------
    (registered_image, (shift_row, shift_col))
        registered_image : float32 (H, W) — image shifted to align with ref.
        (shift_row, shift_col) : sub-pixel shift applied, in pixels.
    """
    if image.shape != reference.shape:
        raise ValueError("image and reference must have the same shape.")

    img = image.astype(np.float64)
    ref = reference.astype(np.float64)

    # Fill NaNs with zero for FFT (NaN in FFT produces all-NaN output).
    img_fft = np.where(np.isfinite(img), img, 0.0)
    ref_fft = np.where(np.isfinite(ref), ref, 0.0)

    H, W = img_fft.shape

    F = np.fft.fft2(img_fft)
    R = np.fft.fft2(ref_fft)

    # Normalised cross-power spectrum.
    eps = 1e-10
    cross = F * np.conj(R)
    cross /= (np.abs(cross) + eps)

    # Coarse integer-pixel shift from IFFT peak.
    corr = np.real(np.fft.ifft2(cross))
    peak_idx = np.unravel_index(np.argmax(corr), corr.shape)
    # Convert to signed shift (wrap around image edges).
    coarse_r = int(peak_idx[0]) if peak_idx[0] <= H // 2 else int(peak_idx[0]) - H
    coarse_c = int(peak_idx[1]) if peak_idx[1] <= W // 2 else int(peak_idx[1]) - W

    # Sanity check before upsampled DFT.
    if abs(coarse_r) > max_shift_px or abs(coarse_c) > max_shift_px:
        log.warning(
            "subpixel_register: coarse shift (%d, %d) exceeds max_shift_px=%.1f; "
            "returning unregistered image.",
            coarse_r, coarse_c, max_shift_px,
        )
        return image.astype(np.float32), (0.0, 0.0)

    # ---- DFT upsampled refinement (Guizar-Sicairos et al. 2008) ----
    # Evaluate the cross-correlation over a (2×upsample_factor + 1) kernel
    # centred on the coarse peak in the upsampled DFT domain.
    uf = int(upsample_factor)
    upsampled_region_size = 2 * uf + 1

    # DFT shift: move origin to coarse peak.
    # Build row/col frequency vectors for the full image.
    freqs_r = np.fft.fftfreq(H)   # shape (H,)
    freqs_c = np.fft.fftfreq(W)   # shape (W,)

    # Sub-sample neighbourhood around coarse peak in upsampled space.
    # Each step is 1/uf pixels.
    sample_r = (np.arange(upsampled_region_size) - uf) / uf + coarse_r
    sample_c = (np.arange(upsampled_region_size) - uf) / uf + coarse_c

    # Compute upsampled DFT of cross-power spectrum at the sample points.
    # upsampled[i, j] = sum_{m,n} cross[m,n] * exp(2πi (m*sample_r[i]/H +
    #                                                      n*sample_c[j]/W))
    # Using matrix form: upsampled = exp_r @ cross_flat @ exp_c^T
    # where exp_r[i,m] = exp(2πi m sample_r[i] / H)
    #       exp_c[j,n] = exp(2πi n sample_c[j] / W)
    kern_r = np.exp(
        2j * np.pi * np.outer(sample_r, freqs_r)
    )  # (upsampled_region_size, H)
    kern_c = np.exp(
        2j * np.pi * np.outer(freqs_c, sample_c)
    )  # (W, upsampled_region_size)

    upsampled = np.real(kern_r @ cross @ kern_c)  # (size, size)

    # Peak of the upsampled correlation.
    sub_peak = np.unravel_index(np.argmax(upsampled), upsampled.shape)
    # Convert sub-peak index to shift offset (relative to coarse peak).
    fine_r = coarse_r + (sub_peak[0] - uf) / uf
    fine_c = coarse_c + (sub_peak[1] - uf) / uf

    # Final sanity check after refinement.
    if abs(fine_r) > max_shift_px or abs(fine_c) > max_shift_px:
        log.warning(
            "subpixel_register: refined shift (%.3f, %.3f) exceeds "
            "max_shift_px=%.1f; returning unregistered image.",
            fine_r, fine_c, max_shift_px,
        )
        return image.astype(np.float32), (0.0, 0.0)

    # Apply sub-pixel shift via scipy bilinear interpolation.
    nan_mask = ~np.isfinite(img)
    img_nofill = np.where(nan_mask, 0.0, img)
    shifted = nd_shift(img_nofill, shift=(-fine_r, -fine_c),
                       order=1, mode="reflect")

    # Restore NaN mask shifted by integer amount (best approximation).
    if nan_mask.any():
        shifted_mask = nd_shift(nan_mask.astype(np.float32),
                                shift=(-fine_r, -fine_c),
                                order=1, mode="constant", cval=0.0)
        shifted = np.where(shifted_mask > 0.5, np.nan, shifted)

    return shifted.astype(np.float32), (float(fine_r), float(fine_c))


def align_to_reference(
    image: np.ndarray,
    reference: np.ndarray,
    roi: Optional[tuple[int, int, int, int]] = None,
    upsample_factor: int = 20,
) -> tuple[np.ndarray, tuple[float, float]]:
    """
    Align *image* to *reference* using a subset ROI for shift estimation.

    Algorithm
    ---------
    Corresponds to Align_2_Images.vi in the SanjVIEW LabVIEW implementation.

    Using a centre ROI rather than the full frame for shift estimation gives
    two benefits:
      1. Faster — smaller FFT.
      2. Avoids edge artefacts (vignetting, stitching seams) that can
         dominate the cross-correlation and produce incorrect shifts.

    The shift is estimated from the ROI crops of image and reference, then
    applied to the *entire* image so no data is lost.

    Parameters
    ----------
    image          : float32 (H, W) — frame to align.
    reference      : float32 (H, W) — target reference frame.
    roi            : (r0, c0, r1, c1) pixel ROI used for shift estimation.
                     If None, the centre 50% of the image is used.
    upsample_factor: passed to subpixel_register(); 20 → 0.05 px precision.

    Returns
    -------
    (aligned_image, (shift_row, shift_col))
        aligned_image          : float32 (H, W) — image after shift correction.
        (shift_row, shift_col) : shift that was applied, in pixels.
    """
    if image.shape != reference.shape:
        raise ValueError("image and reference must have the same shape.")

    H, W = image.shape

    if roi is None:
        # Centre 50% of image.
        r0 = H // 4
        r1 = H - H // 4
        c0 = W // 4
        c1 = W - W // 4
    else:
        r0, c0, r1, c1 = roi

    # Clamp ROI to image bounds.
    r0, r1 = max(0, r0), min(H, r1)
    c0, c1 = max(0, c0), min(W, c1)

    if r1 <= r0 or c1 <= c0:
        raise ValueError(f"ROI ({r0},{c0},{r1},{c1}) is degenerate after clamping.")

    img_crop = image[r0:r1, c0:c1]
    ref_crop = reference[r0:r1, c0:c1]

    # Estimate sub-pixel shift from the ROI.
    _, (shift_r, shift_c) = subpixel_register(
        img_crop, ref_crop, upsample_factor=upsample_factor
    )

    # Apply the estimated shift to the full image.
    img_full = image.astype(np.float64)
    nan_mask = ~np.isfinite(img_full)
    img_nofill = np.where(nan_mask, 0.0, img_full)

    shifted = nd_shift(img_nofill, shift=(-shift_r, -shift_c),
                       order=1, mode="reflect")

    if nan_mask.any():
        shifted_mask = nd_shift(nan_mask.astype(np.float32),
                                shift=(-shift_r, -shift_c),
                                order=1, mode="constant", cval=0.0)
        shifted = np.where(shifted_mask > 0.5, np.nan, shifted)

    return shifted.astype(np.float32), (float(shift_r), float(shift_c))


# ── Stitching ──────────────────────────────────────────────────────────────────


def bilinear_stitch(
    tiles: list[np.ndarray],
    positions_px: list[tuple[float, float]],
    output_shape: tuple[int, int],
    overlap_blend: bool = True,
) -> np.ndarray:
    """
    Stitch a list of image tiles at given pixel positions using bilinear
    interpolation, with optional distance-weighted blending in overlapping
    regions.

    Algorithm
    ---------
    Corresponds to BilinearInterpolation kernal.vi in SanjVIEW.

    For each tile, scipy.ndimage.map_coordinates is used to resample the tile
    onto the output grid at sub-pixel precision.  Where tiles overlap,
    a distance-weighted average (using the distance to the nearest tile edge as
    the weight) is accumulated — this produces a smooth blend that eliminates
    hard seams at tile boundaries.

    NaN pixels within a tile are excluded from the blend (they contribute zero
    weight) so that dead pixels in one tile do not contaminate neighbours.

    Parameters
    ----------
    tiles        : list of float32 (H_i, W_i) arrays.  Tiles need not all be
                   the same size.
    positions_px : list of (row, col) top-left corner positions for each tile
                   in the output coordinate system.  Values may be fractional.
    output_shape : (H_out, W_out) of the final stitched image.
    overlap_blend: if True, compute a distance-weighted average in overlapping
                   regions.  If False, later tiles overwrite earlier ones
                   (last-write-wins).

    Returns
    -------
    float32 (H_out, W_out) stitched image.  Pixels not covered by any tile
    are set to NaN.
    """
    if len(tiles) != len(positions_px):
        raise ValueError("tiles and positions_px must have the same length.")

    H_out, W_out = output_shape
    accumulator = np.zeros((H_out, W_out), dtype=np.float64)
    weight_sum  = np.zeros((H_out, W_out), dtype=np.float64)

    for tile, (row0, col0) in zip(tiles, positions_px):
        tile = np.asarray(tile, dtype=np.float64)
        th, tw = tile.shape

        # Bounding box of this tile in output coordinates.
        r_lo = int(np.floor(row0))
        r_hi = int(np.ceil(row0 + th)) + 1
        c_lo = int(np.floor(col0))
        c_hi = int(np.ceil(col0 + tw)) + 1

        # Clamp to output bounds.
        r_lo = max(r_lo, 0)
        r_hi = min(r_hi, H_out)
        c_lo = max(c_lo, 0)
        c_hi = min(c_hi, W_out)

        if r_lo >= r_hi or c_lo >= c_hi:
            continue  # tile is entirely outside output image

        # Build output pixel grid → tile coordinate mapping.
        out_rows = np.arange(r_lo, r_hi, dtype=np.float64)
        out_cols = np.arange(c_lo, c_hi, dtype=np.float64)
        out_rr, out_cc = np.meshgrid(out_rows, out_cols, indexing="ij")

        # Coordinates in the tile's own pixel space.
        tile_rr = out_rr - row0
        tile_cc = out_cc - col0

        # Mask: only resample points that fall within the tile bounds.
        valid = (
            (tile_rr >= 0) & (tile_rr <= th - 1) &
            (tile_cc >= 0) & (tile_cc <= tw - 1)
        )

        if not valid.any():
            continue

        # map_coordinates for sub-pixel bilinear interpolation.
        sampled = np.full_like(out_rr, np.nan)
        coords = np.array([tile_rr[valid], tile_cc[valid]])
        sampled[valid] = map_coordinates(tile, coords, order=1,
                                         mode="reflect", prefilter=False)

        # Replace positions where tile has NaN (dead pixels) with nan.
        # We detect them by querying the nearest-integer coordinate.
        tile_nan_mask = ~np.isfinite(tile)
        if tile_nan_mask.any():
            # nearest-integer sample to find NaN tile positions.
            tile_rr_int = np.clip(np.round(tile_rr[valid]).astype(int), 0, th - 1)
            tile_cc_int = np.clip(np.round(tile_cc[valid]).astype(int), 0, tw - 1)
            is_nan_sample = tile_nan_mask[tile_rr_int, tile_cc_int]
            sampled_valid = sampled[valid]
            sampled_valid[is_nan_sample] = np.nan
            sampled[valid] = sampled_valid

        if overlap_blend:
            # Distance weight = distance to nearest tile edge (taxicab).
            dist_r = np.minimum(tile_rr - 0, (th - 1) - tile_rr)
            dist_c = np.minimum(tile_cc - 0, (tw - 1) - tile_cc)
            dist = np.minimum(dist_r, dist_c) + 1.0  # avoid zero weight
            w = np.where(np.isfinite(sampled), dist, 0.0)

            accumulator[r_lo:r_hi, c_lo:c_hi] += np.where(
                np.isfinite(sampled), sampled * w, 0.0
            )
            weight_sum[r_lo:r_hi, c_lo:c_hi] += w
        else:
            # Last-write-wins: overwrite with finite values only.
            region = accumulator[r_lo:r_hi, c_lo:c_hi]
            region[np.isfinite(sampled)] = sampled[np.isfinite(sampled)]
            accumulator[r_lo:r_hi, c_lo:c_hi] = region
            weight_sum[r_lo:r_hi, c_lo:c_hi] = np.where(
                np.isfinite(sampled), 1.0, weight_sum[r_lo:r_hi, c_lo:c_hi]
            )

    # Normalise by accumulated weights; uncovered pixels → NaN.
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(weight_sum > 0, accumulator / weight_sum, np.nan)

    return result.astype(np.float32)


# ── Reference frame utilities ──────────────────────────────────────────────────


def compute_shading_reference(frames: list[np.ndarray]) -> np.ndarray:
    """
    Compute a shading reference frame from a list of flat-field frames.

    Algorithm
    ---------
    The frames are averaged (per-pixel mean) to suppress shot noise, then
    smoothed with a large Gaussian (sigma = 64 px) to remove any residual
    high-spatial-frequency content (device features, dust).  The result is a
    smooth estimate of the illumination envelope suitable for use as the
    *reference* argument to shadow_correct().

    Flat-field frames should be captured with the device uniformly illuminated
    and no stimulus applied (e.g. a featureless area or a reference mirror).

    Parameters
    ----------
    frames : list of float32 (H, W) flat-field frames.  All frames must have
             the same shape.

    Returns
    -------
    float32 (H, W) shading reference frame (mean + large Gaussian smooth).
    """
    if not frames:
        raise ValueError("frames list is empty.")

    stack = np.stack([f.astype(np.float64) for f in frames], axis=0)
    mean_frame = np.nanmean(stack, axis=0)

    # Large-sigma Gaussian to retain only the illumination envelope.
    smoothed = gaussian_filter(
        np.where(np.isfinite(mean_frame), mean_frame, 0.0),
        sigma=64.0,
    )

    return smoothed.astype(np.float32)
