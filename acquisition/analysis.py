"""
acquisition/analysis.py

ThermalAnalysisEngine — converts a ΔT map (or ΔR/R map) into a
structured Pass / Warning / Fail verdict with labelled hotspots.

Pipeline
--------
    1. Threshold  — pixels above limit_k are candidates
    2. Morphology — small-open to remove noise specks, then close to
                    fill gaps within a real hotspot
    3. Label      — scipy.ndimage connected-component labelling
    4. Filter     — drop regions below min_area_px
    5. Stats      — per-region peak, mean, area, centroid, bbox
    6. Verdict    — compare against user-defined pass/warning/fail rules
    7. Overlay    — draw annotated colour image for display and PDF

All parameters live in AnalysisConfig so the entire run is
reproducible from a saved config dict.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing      import List, Optional, Tuple
import numpy as np


# ------------------------------------------------------------------ #
#  Configuration                                                       #
# ------------------------------------------------------------------ #

@dataclass
class AnalysisConfig:
    # Threshold
    threshold_k:      float = 5.0    # ΔT above this → hotspot candidate  [°C or K]
    use_dt:           bool  = True   # True = use ΔT map; False = use ΔR/R map

    # Morphology (in pixels)
    open_radius:      int   = 2      # remove noise specks smaller than this
    close_radius:     int   = 4      # fill gaps within hotspots

    # Region filter
    min_area_px:      int   = 20     # ignore regions smaller than this [px]
    max_hotspots:     int   = 999    # used only for display/sorting

    # Verdict rules
    fail_hotspot_count:  int   = 1    # ≥ this many hotspots → FAIL  (0 = disabled)
    warn_hotspot_count:  int   = 0    # ≥ this many → WARNING        (0 = disabled)
    fail_peak_k:         float = 10.0 # any hotspot peak ≥ this → FAIL
    warn_peak_k:         float = 5.0  # any hotspot peak ≥ this → WARNING
    fail_area_fraction:  float = 0.05 # hotspot area / total area ≥ this → FAIL
    warn_area_fraction:  float = 0.02 # → WARNING

    # Scale (optional — for μm² reporting)
    px_per_um:        float = 0.0    # 0 = unknown

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AnalysisConfig":
        cfg = AnalysisConfig()
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


# ------------------------------------------------------------------ #
#  Per-hotspot result                                                  #
# ------------------------------------------------------------------ #

@dataclass
class Hotspot:
    index:      int          # 1-based label
    peak_k:     float        # maximum ΔT in this region  [°C]
    mean_k:     float        # mean ΔT
    area_px:    int          # area in pixels
    area_um2:   float        # area in μm² (0 if scale unknown)
    centroid:   Tuple[int, int]   # (col, row) in image coords
    bbox:       Tuple[int, int, int, int]  # (x, y, w, h)
    severity:   str          # "warning" | "fail"


# ------------------------------------------------------------------ #
#  Overall analysis result                                            #
# ------------------------------------------------------------------ #

VERDICT_PASS    = "PASS"
VERDICT_WARNING = "WARNING"
VERDICT_FAIL    = "FAIL"


@dataclass
class AnalysisResult:
    verdict:       str                    # PASS | WARNING | FAIL
    hotspots:      List[Hotspot]          = field(default_factory=list)
    n_hotspots:    int                    = 0
    max_peak_k:    float                  = 0.0   # highest ΔT across all hotspots
    total_area_px: int                    = 0     # all hotspot pixels combined
    area_fraction: float                  = 0.0   # hotspot px / map px
    map_mean_k:    float                  = 0.0
    map_std_k:     float                  = 0.0
    threshold_k:   float                  = 0.0
    overlay_rgb:   Optional[np.ndarray]   = None  # uint8 H×W×3
    binary_mask:   Optional[np.ndarray]   = None  # bool H×W
    timestamp:     float                  = 0.0
    timestamp_str: str                    = ""
    config:        Optional[AnalysisConfig] = None
    notes:         str                    = ""
    valid:         bool                   = False


# ------------------------------------------------------------------ #
#  Engine                                                              #
# ------------------------------------------------------------------ #

class ThermalAnalysisEngine:

    VERDICT_COLOURS = {
        VERDICT_PASS:    (0,   210, 120),   # green
        VERDICT_WARNING: (255, 180,   0),   # amber
        VERDICT_FAIL:    (220,  40,  40),   # red
    }
    HOTSPOT_COLOURS = {
        "fail":    (220,  40,  40),
        "warning": (255, 180,   0),
    }

    def __init__(self, cfg: AnalysisConfig = None):
        self._cfg = cfg or AnalysisConfig()

    def update_config(self, cfg: AnalysisConfig):
        self._cfg = cfg

    # ---------------------------------------------------------------- #
    #  Main entry point                                                 #
    # ---------------------------------------------------------------- #

    def run(self,
            dt_map:  Optional[np.ndarray],
            drr_map: Optional[np.ndarray],
            base_image: Optional[np.ndarray] = None) -> AnalysisResult:
        """
        Run the full analysis pipeline.

        dt_map    : float32 ΔT map in °C (preferred)
        drr_map   : float32 ΔR/R map (fallback if dt_map is None)
        base_image: uint8 or uint16 greyscale frame for overlay background
        """
        cfg = self._cfg

        # Choose input map
        if cfg.use_dt and dt_map is not None:
            data = dt_map.astype(np.float32)
            unit = "°C"
        elif drr_map is not None:
            data = drr_map.astype(np.float32)
            unit = "ΔR/R"
        else:
            return AnalysisResult(verdict=VERDICT_FAIL,
                                  notes="No input map available.",
                                  valid=False)

        # Multi-channel (H,W,3) → reduce to luminance for analysis.
        # Morphology and thresholding require a 2-D map.
        if data.ndim == 3:
            data = (0.2126 * data[:, :, 0]
                    + 0.7152 * data[:, :, 1]
                    + 0.0722 * data[:, :, 2])

        H, W   = data.shape[:2]
        total_px = H * W

        # ---- 1. Threshold ----
        above = (data >= cfg.threshold_k).astype(np.uint8)

        # ---- 2. Morphology ----
        try:
            import cv2
            def disk(r):
                return cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE, (2*r+1, 2*r+1))
            if cfg.open_radius  > 0:
                above = cv2.morphologyEx(above, cv2.MORPH_OPEN,
                                         disk(cfg.open_radius))
            if cfg.close_radius > 0:
                above = cv2.morphologyEx(above, cv2.MORPH_CLOSE,
                                         disk(cfg.close_radius))
        except ImportError:
            pass   # skip morphology if cv2 unavailable

        binary_mask = above.astype(bool)

        # ---- 3. Label ----
        try:
            from scipy.ndimage import label as ndlabel
        except ImportError:
            raise RuntimeError(
                "scipy is required for hotspot analysis.\n"
                "Install it with:  pip install scipy")
        labelled, n_found = ndlabel(binary_mask)

        # ---- 4 + 5. Filter + stats ----
        hotspots: List[Hotspot] = []
        px_per_um = cfg.px_per_um

        for idx in range(1, n_found + 1):
            region_mask = labelled == idx
            area_px     = int(region_mask.sum())
            if area_px < cfg.min_area_px:
                continue

            vals      = data[region_mask]
            peak_k    = float(vals.max())
            mean_k    = float(vals.mean())
            area_um2  = (area_px / (px_per_um ** 2)) if px_per_um > 0 else 0.0

            # Centroid
            rows, cols = np.where(region_mask)
            cy, cx     = int(rows.mean()), int(cols.mean())

            # Bounding box
            r0, r1 = int(rows.min()), int(rows.max())
            c0, c1 = int(cols.min()), int(cols.max())
            bbox   = (c0, r0, c1 - c0, r1 - r0)

            # Per-hotspot severity
            severity = "warning"
            if (cfg.fail_peak_k > 0 and peak_k >= cfg.fail_peak_k):
                severity = "fail"

            hotspots.append(Hotspot(
                index    = 0,   # renumbered after sort
                peak_k   = peak_k,
                mean_k   = mean_k,
                area_px  = area_px,
                area_um2 = area_um2,
                centroid = (cx, cy),
                bbox     = bbox,
                severity = severity,
            ))

        # Sort by peak ΔT descending
        hotspots.sort(key=lambda h: h.peak_k, reverse=True)
        for i, h in enumerate(hotspots):
            h.index = i + 1

        # Limit display count
        display_hotspots = hotspots[:cfg.max_hotspots]

        # ---- 6. Verdict ----
        total_hotspot_px = int(binary_mask.sum())
        area_fraction    = total_hotspot_px / total_px if total_px > 0 else 0.0
        max_peak         = hotspots[0].peak_k if hotspots else 0.0
        n_hs             = len(hotspots)

        verdict = self._compute_verdict(cfg, n_hs, max_peak, area_fraction)

        # ---- 7. Overlay ----
        overlay = self._make_overlay(
            data, binary_mask, labelled, hotspots,
            base_image, verdict, cfg)

        return AnalysisResult(
            verdict       = verdict,
            hotspots      = display_hotspots,
            n_hotspots    = n_hs,
            max_peak_k    = max_peak,
            total_area_px = total_hotspot_px,
            area_fraction = area_fraction,
            map_mean_k    = float(data.mean()),
            map_std_k     = float(data.std()),
            threshold_k   = cfg.threshold_k,
            overlay_rgb   = overlay,
            binary_mask   = binary_mask,
            timestamp     = time.time(),
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S"),
            config        = cfg,
            valid         = True,
        )

    # ---------------------------------------------------------------- #
    #  Verdict logic                                                    #
    # ---------------------------------------------------------------- #

    def _compute_verdict(self, cfg: AnalysisConfig,
                          n_hs: int, max_peak: float,
                          area_fraction: float) -> str:
        # FAIL conditions (any one triggers FAIL)
        fail = False
        if cfg.fail_hotspot_count > 0 and n_hs >= cfg.fail_hotspot_count:
            fail = True
        if cfg.fail_peak_k > 0 and max_peak >= cfg.fail_peak_k:
            fail = True
        if cfg.fail_area_fraction > 0 and area_fraction >= cfg.fail_area_fraction:
            fail = True
        if fail:
            return VERDICT_FAIL

        # WARNING conditions
        warn = False
        if cfg.warn_hotspot_count > 0 and n_hs >= cfg.warn_hotspot_count:
            warn = True
        if cfg.warn_peak_k > 0 and max_peak >= cfg.warn_peak_k:
            warn = True
        if cfg.warn_area_fraction > 0 and area_fraction >= cfg.warn_area_fraction:
            warn = True
        if warn:
            return VERDICT_WARNING

        return VERDICT_PASS

    # ---------------------------------------------------------------- #
    #  Overlay renderer                                                 #
    # ---------------------------------------------------------------- #

    def _make_overlay(self, data, binary_mask, labelled,
                      hotspots, base_image, verdict, cfg) -> np.ndarray:
        H, W = data.shape[:2]

        # Background: base_image (greyscale) or normalised data.
        # Multi-channel base images are reduced to luminance.
        if base_image is not None:
            bg = base_image.astype(np.float32)
            if bg.ndim == 3:
                bg = 0.2126 * bg[:, :, 0] + 0.7152 * bg[:, :, 1] + 0.0722 * bg[:, :, 2]
            bg = ((bg - bg.min()) / (bg.max() - bg.min() + 1e-9) * 200
                  ).clip(0, 200).astype(np.uint8)
        else:
            # Normalise data to 0-180 so hotspots stand out
            d = data.astype(np.float32)
            lo, hi = float(np.percentile(d, 1)), float(np.percentile(d, 99))
            bg = ((d - lo) / (hi - lo + 1e-9) * 180).clip(0, 180).astype(np.uint8)

        # RGB canvas — dark greyscale background
        canvas = np.stack([bg, bg, bg], axis=-1).copy()

        # Tint hotspot regions with a semi-transparent severity colour
        for h in hotspots:
            region = labelled == h.index
            color  = self.HOTSPOT_COLOURS[h.severity]
            for c, val in enumerate(color):
                canvas[:, :, c][region] = np.clip(
                    canvas[:, :, c][region].astype(int) * 0.35 + val * 0.65,
                    0, 255).astype(np.uint8)

        try:
            import cv2

            # Contour outlines
            for h in hotspots:
                region_u8 = (labelled == h.index).astype(np.uint8) * 255
                contours, _ = cv2.findContours(
                    region_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                color = self.HOTSPOT_COLOURS[h.severity]
                cv2.drawContours(canvas, contours, -1, color, 1)

                # Hotspot number label
                cx, cy = h.centroid
                label  = str(h.index)
                fs     = 0.38
                thick  = 1
                (tw, th), _ = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, fs, thick)
                # Small filled circle behind number
                cv2.circle(canvas, (cx, cy), max(tw, th) // 2 + 4,
                           color, -1)
                cv2.putText(canvas, label,
                            (cx - tw // 2, cy + th // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, fs,
                            (255, 255, 255), thick, cv2.LINE_AA)

            # Verdict badge (top-right corner)
            badge_color = self.VERDICT_COLOURS[verdict]
            bx, by, bw, bh = W - 110, 8, 102, 28
            cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh),
                          badge_color, -1)
            cv2.putText(canvas, verdict,
                        (bx + 8, by + bh - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 1, cv2.LINE_AA)

            # Threshold annotation (bottom-left)
            ann = f"thresh {cfg.threshold_k:.1f}  |  {len(hotspots)} hotspot(s)"
            cv2.putText(canvas, ann, (8, H - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32,
                        (120, 120, 120), 1, cv2.LINE_AA)

        except ImportError:
            pass

        return canvas
