"""
acquisition/processing.py

Utilities for processing and displaying AcquisitionResult data.

- Scale ΔR/R to displayable images
- Apply scientific colormaps
- Export to TIFF, NPY, CSV
"""

import numpy as np
import os
import time
from typing import Optional, Tuple


def to_display(
    data: np.ndarray,
    mode: str = "auto",
    clip_percentile: float = 99.5
) -> np.ndarray:
    """
    Convert a float32 or uint16 array to uint8 for display.

    mode:
        "auto"       — stretch to min/max
        "percentile" — clip to clip_percentile before stretching (removes outliers)
        "fixed"      — assume 12-bit data (0–4095 → 0–255)
        "signed"     — for ΔR/R maps, center on zero (blue=negative, red=positive)
                        returns shape (H, W, 3) RGB
    """
    d = data.astype(np.float32)

    if mode == "signed":
        return _signed_colormap(d, clip_percentile)

    if mode == "percentile":
        lo = float(np.percentile(d, 100 - clip_percentile))
        hi = float(np.percentile(d, clip_percentile))
    elif mode == "auto":
        lo, hi = float(d.min()), float(d.max())
    elif mode == "fixed":
        lo, hi = 0.0, 4095.0
    else:
        lo, hi = float(d.min()), float(d.max())

    span = hi - lo
    if span == 0:
        return np.zeros(d.shape, dtype=np.uint8)

    scaled = np.clip((d - lo) / span * 255, 0, 255).astype(np.uint8)
    return scaled


def _signed_colormap(data: np.ndarray, clip_pct: float) -> np.ndarray:
    """
    Scientific diverging colormap for ΔR/R:
        negative → blue
        zero     → black
        positive → red
    Returns uint8 RGB (H, W, 3).
    """
    limit = float(np.percentile(np.abs(data), clip_pct))
    if limit == 0:
        limit = 1e-9

    normed = np.clip(data / limit, -1.0, 1.0)

    r = np.clip( normed, 0, 1) * 255
    b = np.clip(-normed, 0, 1) * 255
    g = np.zeros_like(r)

    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def apply_colormap(gray: np.ndarray, cmap: str = "hot") -> np.ndarray:
    """
    Apply a named colormap to a uint8 grayscale image.
    Returns uint8 RGB (H, W, 3).

    Available: "hot", "cool", "viridis", "gray"
    Requires opencv-python.
    """
    import cv2
    maps = {
        "hot":     cv2.COLORMAP_HOT,
        "cool":    cv2.COLORMAP_COOL,
        "viridis": cv2.COLORMAP_VIRIDIS,
        "jet":     cv2.COLORMAP_JET,
        "gray":    None,
    }
    if cmap == "gray" or cmap not in maps:
        return np.stack([gray, gray, gray], axis=-1)
    return cv2.applyColorMap(gray, maps[cmap])


def export_result(result, output_dir: str = ".") -> dict:
    """
    Save acquisition result to files.

    Saves:
        cold_avg.tiff        — baseline averaged frame (uint16)
        hot_avg.tiff         — stimulus averaged frame (uint16)
        delta_r_over_r.npy   — thermoreflectance signal (float32)
        delta_r_over_r.tiff  — 32-bit TIFF for ImageJ/Fiji
        metadata.txt         — acquisition parameters

    Returns dict of saved file paths.
    """
    import cv2

    os.makedirs(output_dir, exist_ok=True)
    ts    = time.strftime("%Y%m%d_%H%M%S")
    saved = {}

    def path(name):
        return os.path.join(output_dir, f"{ts}_{name}")

    if result.cold_avg is not None:
        p = path("cold_avg.tiff")
        cv2.imwrite(p, result.cold_avg.astype(np.uint16))
        saved["cold_avg"] = p

    if result.hot_avg is not None:
        p = path("hot_avg.tiff")
        cv2.imwrite(p, result.hot_avg.astype(np.uint16))
        saved["hot_avg"] = p

    if result.delta_r_over_r is not None:
        # NumPy binary — preserves full float32 precision
        p = path("delta_r_over_r.npy")
        np.save(p, result.delta_r_over_r)
        saved["delta_r_over_r_npy"] = p

        # 32-bit TIFF for ImageJ/Fiji
        p = path("delta_r_over_r.tiff")
        cv2.imwrite(p, result.delta_r_over_r)
        saved["delta_r_over_r_tiff"] = p

    # Metadata
    p = path("metadata.txt")
    with open(p, "w") as f:
        f.write(f"Timestamp:       {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Frames:          {result.n_frames}\n")
        f.write(f"Cold captured:   {result.cold_captured}\n")
        f.write(f"Hot captured:    {result.hot_captured}\n")
        f.write(f"Exposure (us):   {result.exposure_us:.1f}\n")
        f.write(f"Gain (dB):       {result.gain_db:.1f}\n")
        f.write(f"Duration (s):    {result.duration_s:.2f}\n")
        if result.snr_db is not None:
            f.write(f"SNR (dB):        {result.snr_db:.1f}\n")
        if result.notes:
            f.write(f"Notes:           {result.notes}\n")
    saved["metadata"] = p

    print(f"Saved {len(saved)} files to {output_dir}")
    return saved
