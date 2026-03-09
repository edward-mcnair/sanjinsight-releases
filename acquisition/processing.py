"""
acquisition/processing.py

Utilities for processing and displaying AcquisitionResult data.

- Scale ΔR/R to displayable images
- Apply scientific colormaps
- Export to TIFF, NPY, CSV
"""

import logging
import numpy as np
import os
import time
from typing import Optional, Tuple

log = logging.getLogger(__name__)


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


# ── Colormap registry ─────────────────────────────────────────────────────────
# Single source of truth for all colormap combo-boxes in the UI.
# Order determines the order shown in drop-downs.
# Keys are passed to apply_colormap() and to the canvas _rebuild methods.
COLORMAP_OPTIONS: list[str] = [
    "Thermal Delta",  # Diverging blue-black-red — default for ΔR/R
    "Emberline",      # Black→purple→orange→white  (INFERNO)
    "Polarflare",     # Grayscale: warm = white
    "Umbra Heat",     # Grayscale: warm = black  (inverted)
    "Prismshift",     # Full spectrum low→high    (RAINBOW)
    "Magmafall",      # Black→red→yellow→white    (HOT)
    "Borealis",       # Cool blue-green arctic palette (WINTER)
    "Hearthtone",     # Warm sepia-autumn tones   (AUTUMN)
    "Ghostscale",     # Blue-tinted grayscale      (BONE)
    "plasma",         # Purple→magenta→orange      (perceptually uniform)
    "viridis",        # Blue→green→yellow          (perceptually uniform)
    "turbo",          # High-contrast rainbow
    "jet",            # Classic rainbow            (legacy / reference)
    "cool",           # Cyan→magenta
]

# Tooltip shown next to each palette name in UI combo-boxes.
COLORMAP_TOOLTIPS: dict[str, str] = {
    "Thermal Delta": "Diverging: blue = cooling, red = heating. Default for ΔR/R maps.",
    "Emberline":     "Black → purple → orange → white. Ideal for locating hot spots.",
    "Polarflare":    "Grayscale — bright = hot, dark = cold. Classic thermal imaging.",
    "Umbra Heat":    "Inverted grayscale — dark = hot, bright = cold. High-contrast alternative.",
    "Prismshift":    "Full visible spectrum. Good for revealing subtle temperature gradients.",
    "Magmafall":     "Black → red → yellow → white. Emphasises intense heat sources.",
    "Borealis":      "Cool blue-green palette. Useful when working with cold regions.",
    "Hearthtone":    "Warm amber-sepia tones. Softer display for extended viewing sessions.",
    "Ghostscale":    "Cool blue-tinted grayscale. Distinguishable from standard white-hot.",
    "plasma":        "Purple → magenta → orange. Perceptually uniform, print-safe.",
    "viridis":       "Blue → green → yellow. Perceptually uniform, accessible to colour-blind users.",
    "turbo":         "High-contrast rainbow. Maximum discrimination across the full range.",
    "jet":           "Classic blue-cyan-yellow-red rainbow. Legacy reference palette.",
    "cool":          "Cyan → magenta. Useful for cold-dominant thermal scenes.",
}


def _build_cv_maps() -> dict:
    """Build the key→cv2 constant mapping, skipping entries absent in older OpenCV."""
    try:
        import cv2
    except ImportError:
        return {}
    m = {
        # Branded palette names
        "Emberline":  cv2.COLORMAP_INFERNO,
        "Prismshift": cv2.COLORMAP_RAINBOW,
        "Magmafall":  cv2.COLORMAP_HOT,
        "Borealis":   cv2.COLORMAP_WINTER,
        "Hearthtone": cv2.COLORMAP_AUTUMN,
        "Ghostscale": cv2.COLORMAP_BONE,
        # Generic scientific names
        "plasma":     cv2.COLORMAP_PLASMA,
        "viridis":    cv2.COLORMAP_VIRIDIS,
        "jet":        cv2.COLORMAP_JET,
        "cool":       cv2.COLORMAP_COOL,
        # Legacy keys — not shown in UI, kept for backwards compatibility
        "hot":        cv2.COLORMAP_HOT,
        "ironbow":    cv2.COLORMAP_INFERNO,
        "rainbow":    cv2.COLORMAP_RAINBOW,
        "lava":       cv2.COLORMAP_HOT,
    }
    # COLORMAP_TURBO added in OpenCV 4.1 — skip gracefully on older installs
    if hasattr(cv2, "COLORMAP_TURBO"):
        m["turbo"] = cv2.COLORMAP_TURBO
    else:
        m["turbo"] = cv2.COLORMAP_JET       # reasonable fallback
    return m


# Module-level cache (populated on first use of apply_colormap)
_CV_MAPS = None  # type: dict | None

# ── Matplotlib fallback (used when opencv-python is not installed) ─────────────
# Maps branded palette names → matplotlib colormap names.
_MPL_NAMES: dict = {
    "Emberline":  "inferno",
    "Prismshift": "rainbow",
    "Magmafall":  "hot",
    "Borealis":   "winter",
    "Hearthtone": "autumn",
    "Ghostscale": "bone",
    "plasma":     "plasma",
    "viridis":    "viridis",
    "turbo":      "turbo",
    "jet":        "jet",
    "cool":       "cool",
    # Legacy aliases
    "hot":        "hot",
    "ironbow":    "inferno",
    "rainbow":    "rainbow",
    "lava":       "hot",
}
_MPL_LUTS: dict = {}  # mpl_name → (256, 3) uint8 LUT, built once per name


def _mpl_colormap(gray: np.ndarray, cmap: str) -> np.ndarray:
    """Apply a matplotlib colormap via a prebuilt 256-entry LUT → uint8 RGB."""
    mpl_name = _MPL_NAMES.get(cmap, "gray")
    lut = _MPL_LUTS.get(mpl_name)
    if lut is None:
        try:
            from matplotlib import colormaps
            lut = (colormaps[mpl_name](np.linspace(0, 1, 256)) * 255
                   ).astype(np.uint8)[:, :3]
        except Exception:
            lut = np.column_stack([np.arange(256, dtype=np.uint8)] * 3)  # gray
        _MPL_LUTS[mpl_name] = lut
    return lut[gray]  # fancy indexing: (H, W) → (H, W, 3)


def apply_colormap(gray: np.ndarray, cmap: str = "Emberline") -> np.ndarray:
    """
    Apply a named colormap to a uint8 grayscale image.
    Returns uint8 RGB (H, W, 3).

    Special cases handled without any library:
        "Polarflare" / "white hot" / "gray" — identity grayscale (warm = white)
        "Umbra Heat" / "black hot"           — inverted grayscale (warm = black)

    "Thermal Delta" and "signed" are handled by to_display(mode="signed") upstream;
    if passed here directly, falls back to grayscale.

    All other keys use cv2.COLORMAP_* when opencv-python is installed, or fall
    back to equivalent matplotlib colormaps (always available).
    """
    global _CV_MAPS
    # Grayscale variants — no library needed
    if cmap in ("Polarflare", "white hot", "gray"):
        return np.stack([gray, gray, gray], axis=-1)
    if cmap in ("Umbra Heat", "black hot"):
        inv = 255 - gray
        return np.stack([inv, inv, inv], axis=-1)

    # Prefer OpenCV (faster); fall back to matplotlib
    if _CV_MAPS is None:
        _CV_MAPS = _build_cv_maps()
    if _CV_MAPS and cmap in _CV_MAPS:
        import cv2
        bgr = cv2.applyColorMap(gray, _CV_MAPS[cmap])
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    # matplotlib fallback — works without opencv-python
    if cmap in _MPL_NAMES:
        return _mpl_colormap(gray, cmap)

    return np.stack([gray, gray, gray], axis=-1)


# ── Colormap preview colours ───────────────────────────────────────────────────
# LUT sample indices chosen to land on the most visually distinctive / saturated
# region of each palette so the text label gives an instant colour hint.
_CMAP_SAMPLE_IDX: dict = {
    "Emberline":  210,   # bright orange (inferno ~82 %)
    "Prismshift":  88,   # vivid green   (rainbow ~35 %)
    "Magmafall":  185,   # red-orange    (hot     ~73 %)
    "Borealis":    60,   # cyan          (winter  ~24 %)
    "Hearthtone": 130,   # amber-orange  (autumn  ~51 %)
    "Ghostscale": 160,   # blue-grey     (bone    ~63 %)
    "plasma":     175,   # pink-magenta  (plasma  ~69 %)
    "viridis":    140,   # teal          (viridis ~55 %)
    "turbo":      205,   # orange-red    (turbo   ~80 %)
    "jet":        185,   # yellow        (jet     ~73 %)
    "cool":       128,   # cyan-magenta  (cool    ~50 %)
}


def get_cmap_preview_color(cmap: str) -> tuple:
    """Return (r, g, b) as a visually representative colour for *cmap*.

    Used to tint combo-box item labels so users can identify each palette
    at a glance without opening the drop-down.
    """
    if cmap in ("Thermal Delta", "signed"):
        return (220, 60, 60)           # red  — the "hot" end of the diverging map
    if cmap in ("Polarflare", "white hot", "gray"):
        return (210, 210, 210)         # bright grey — warm = white
    if cmap in ("Umbra Heat", "black hot"):
        return (130, 130, 130)         # dim grey  — warm = black (inverted)
    idx = _CMAP_SAMPLE_IDX.get(cmap, 160)
    try:
        rgb = _mpl_colormap(np.array([[idx]], dtype=np.uint8), cmap)
        return int(rgb[0, 0, 0]), int(rgb[0, 0, 1]), int(rgb[0, 0, 2])
    except Exception:
        return (150, 150, 150)


def setup_cmap_combo(combo, saved_cmap: str = "Thermal Delta") -> None:
    """Populate *combo* (QComboBox) with COLORMAP_OPTIONS.

    For each item this function:
      - adds the display name
      - sets a tooltip from COLORMAP_TOOLTIPS
      - tints the label text with a representative preview colour

    The caller is responsible for setFixedWidth() and signal connections.
    """
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui  import QBrush, QColor
    for i, c in enumerate(COLORMAP_OPTIONS):
        combo.addItem(c)
        combo.setItemData(i, COLORMAP_TOOLTIPS.get(c, ""), Qt.ToolTipRole)
        r, g, b = get_cmap_preview_color(c)
        combo.model().item(i).setForeground(QBrush(QColor(r, g, b)))
    if saved_cmap in COLORMAP_OPTIONS:
        combo.setCurrentText(saved_cmap)


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

    log.info("Saved %d files to %s", len(saved), output_dir)
    return saved
