"""
acquisition/roi.py

Region of Interest — rectangular, elliptical, or freeform polygon region
that restricts acquisition and analysis to a sub-region of the camera frame.

ROI coordinates are always in full-frame pixel space (not relative).
All crop/apply operations are pure numpy — no extra dependencies.

Shapes
------
  rect     — axis-aligned rectangle (default)
  ellipse  — ellipse inscribed in the bounding rectangle (x, y, w, h)
  freeform — arbitrary polygon defined by a list of (x, y) vertices

Usage:
    roi = Roi(x=100, y=80, w=400, h=300)
    cropped = roi.crop(frame_data)          # returns sub-array
    full    = roi.embed(cropped, frame_data) # paste back into full frame
    mask    = roi.mask(frame_data.shape)    # boolean mask

    ellipse = Roi(x=100, y=80, w=400, h=300, shape="ellipse")
    m = ellipse.mask(frame.shape)           # True inside the ellipse

    freeform = Roi.from_vertices([(100, 80), (500, 80), (300, 380)])
    m = freeform.mask(frame.shape)          # True inside the polygon
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import math
import uuid
import numpy as np

# Default ROI colours — visually distinct, WCAG-friendly on dark & light BGs
ROI_COLORS = [
    "#00d479",  # green  (primary)
    "#3d8bef",  # blue
    "#f5a623",  # amber
    "#e040fb",  # magenta
    "#00bcd4",  # cyan
    "#ff5252",  # red
    "#7c4dff",  # purple
    "#64dd17",  # lime
]

# Valid shape types
SHAPE_RECT     = "rect"
SHAPE_ELLIPSE  = "ellipse"
SHAPE_FREEFORM = "freeform"
_VALID_SHAPES  = {SHAPE_RECT, SHAPE_ELLIPSE, SHAPE_FREEFORM}


@dataclass
class Roi:
    """
    Region of interest in pixel coordinates.

    x, y  — top-left corner of the bounding rectangle (inclusive)
    w, h  — width and height of the bounding rectangle in pixels
    shape — ``"rect"``, ``"ellipse"``, or ``"freeform"``

    uid      — unique identifier (auto-generated if omitted)
    label    — human-readable name ("ROI 1", "Hotspot A", etc.)
    color    — hex colour string for rendering overlays
    vertices — list of (x, y) tuples defining the polygon (freeform only)

    For ellipses the bounding box defines the inscribed ellipse:
      centre = (x + w/2, y + h/2), radii = (w/2, h/2).

    For freeform shapes the bounding box (x, y, w, h) is auto-computed
    from the vertices.  crop/embed still use the bounding box.

    All coordinate values are integers.  (0,0,0,0) means "full frame" (no crop).
    """
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    shape: str = SHAPE_RECT
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    label: str = ""
    color: str = ""
    vertices: List[Tuple[int, int]] = field(default_factory=list)

    # ---------------------------------------------------------------- #

    @property
    def is_rect(self) -> bool:
        return self.shape == SHAPE_RECT

    @property
    def is_ellipse(self) -> bool:
        return self.shape == SHAPE_ELLIPSE

    @property
    def is_freeform(self) -> bool:
        return self.shape == SHAPE_FREEFORM

    @property
    def is_empty(self) -> bool:
        if self.is_freeform:
            return len(self.vertices) < 3
        return self.w <= 0 or self.h <= 0

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        if self.is_freeform and self.vertices:
            return abs(_polygon_area(self.vertices))
        a = max(0, self.w * self.h)
        if self.is_ellipse:
            return int(math.pi * (self.w / 2) * (self.h / 2))
        return a

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def _recompute_bbox(self) -> None:
        """Recompute bounding box from vertices (freeform only)."""
        if not self.vertices:
            self.x = self.y = self.w = self.h = 0
            return
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        self.x = min(xs)
        self.y = min(ys)
        self.w = max(xs) - self.x
        self.h = max(ys) - self.y

    def clamp(self, frame_h: int, frame_w: int) -> "Roi":
        """Return a copy clamped to the frame bounds (preserves uid/label/color/shape/vertices)."""
        if self.is_freeform and self.vertices:
            clamped_verts = [
                (max(0, min(vx, frame_w - 1)),
                 max(0, min(vy, frame_h - 1)))
                for vx, vy in self.vertices]
            roi = Roi(shape=SHAPE_FREEFORM,
                      uid=self.uid, label=self.label, color=self.color,
                      vertices=clamped_verts)
            roi._recompute_bbox()
            return roi
        x  = max(0, min(self.x,  frame_w - 1))
        y  = max(0, min(self.y,  frame_h - 1))
        x2 = max(0, min(self.x2, frame_w))
        y2 = max(0, min(self.y2, frame_h))
        return Roi(x=x, y=y, w=x2 - x, h=y2 - y,
                   shape=self.shape,
                   uid=self.uid, label=self.label, color=self.color)

    def crop(self, image: np.ndarray) -> np.ndarray:
        """
        Return the sub-array of image corresponding to this ROI's bounding box.
        If ROI is empty, returns the full image.

        For ellipses this returns the bounding-box crop; use ``mask()``
        to exclude pixels outside the ellipse before aggregation.
        """
        if self.is_empty:
            return image
        h, w = image.shape[:2]
        roi  = self.clamp(h, w)
        return image[roi.y:roi.y2, roi.x:roi.x2]

    def embed(self,
              cropped:  np.ndarray,
              template: np.ndarray) -> np.ndarray:
        """
        Paste a cropped result back into a full-size copy of template.
        Pixels outside the ROI bounding box keep their template values.
        """
        if self.is_empty:
            return cropped
        out = template.copy()
        h, w = template.shape[:2]
        roi  = self.clamp(h, w)
        out[roi.y:roi.y2, roi.x:roi.x2] = cropped
        return out

    def mask(self, shape: Tuple[int, ...]) -> np.ndarray:
        """
        Return a boolean mask array (True inside ROI, False outside).
        shape: (H, W) or (H, W, C)

        For rectangular ROIs the mask is a filled rectangle.
        For elliptical ROIs the mask is a filled ellipse inscribed
        in the bounding box.
        For freeform ROIs the mask is a filled polygon.
        """
        h, w = shape[:2]
        m    = np.zeros((h, w), dtype=bool)
        if self.is_empty:
            m[:] = True
            return m
        roi  = self.clamp(h, w)
        if self.is_freeform:
            if len(roi.vertices) < 3:
                return m
            _fill_polygon(m, roi.vertices)
        elif self.is_ellipse:
            # Ellipse inscribed in the (clamped) bounding box
            cx = roi.x + roi.w / 2.0
            cy = roi.y + roi.h / 2.0
            rx = roi.w / 2.0
            ry = roi.h / 2.0
            if rx <= 0 or ry <= 0:
                return m
            # Build coordinate grids only for the bounding box (fast)
            yy, xx = np.mgrid[roi.y:roi.y2, roi.x:roi.x2]
            inside = ((xx - cx) ** 2 / (rx ** 2) +
                       (yy - cy) ** 2 / (ry ** 2)) <= 1.0
            m[roi.y:roi.y2, roi.x:roi.x2] = inside
        else:
            m[roi.y:roi.y2, roi.x:roi.x2] = True
        return m

    def to_dict(self) -> dict:
        d = {"x": self.x, "y": self.y, "w": self.w, "h": self.h}
        if self.shape != SHAPE_RECT:
            d["shape"] = self.shape
        if self.uid:
            d["uid"] = self.uid
        if self.label:
            d["label"] = self.label
        if self.color:
            d["color"] = self.color
        if self.vertices:
            d["vertices"] = [list(v) for v in self.vertices]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Roi":
        shape = d.get("shape", SHAPE_RECT)
        if shape not in _VALID_SHAPES:
            shape = SHAPE_RECT
        verts_raw = d.get("vertices", [])
        vertices = [(int(v[0]), int(v[1])) for v in verts_raw if len(v) >= 2]
        roi = Roi(
            x=d.get("x", 0), y=d.get("y", 0),
            w=d.get("w", 0), h=d.get("h", 0),
            shape=shape,
            uid=d.get("uid", uuid.uuid4().hex[:8]),
            label=d.get("label", ""),
            color=d.get("color", ""),
            vertices=vertices,
        )
        if shape == SHAPE_FREEFORM and vertices and roi.w == 0 and roi.h == 0:
            roi._recompute_bbox()
        return roi

    @staticmethod
    def from_vertices(vertices: List[Tuple[int, int]],
                      uid: str = "",
                      label: str = "",
                      color: str = "") -> "Roi":
        """Create a freeform ROI from a list of polygon vertices."""
        roi = Roi(
            shape=SHAPE_FREEFORM,
            uid=uid or uuid.uuid4().hex[:8],
            label=label, color=color,
            vertices=list(vertices),
        )
        roi._recompute_bbox()
        return roi

    @staticmethod
    def full(frame_h: int, frame_w: int) -> "Roi":
        return Roi(x=0, y=0, w=frame_w, h=frame_h)

    def __str__(self):
        if self.is_empty:
            return "Roi(full frame)"
        lbl = f" {self.label!r}" if self.label else ""
        if self.is_freeform:
            n = len(self.vertices)
            return f"Roi(freeform {n}pts, bbox={self.w}\u00d7{self.h}{lbl})"
        sh  = f" shape={self.shape}" if self.is_ellipse else ""
        return f"Roi(x={self.x}, y={self.y}, w={self.w}, h={self.h}{sh}{lbl})"

    def __repr__(self):
        return str(self)


# ────────────────────────────────────────────────────────────────────
#  Polygon helpers (pure NumPy — no cv2/skimage dependency)
# ────────────────────────────────────────────────────────────────────

def _polygon_area(vertices: List[Tuple[int, int]]) -> int:
    """Shoelace formula — returns signed area (positive if CCW)."""
    n = len(vertices)
    if n < 3:
        return 0
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += xs[i] * ys[j]
        area -= xs[j] * ys[i]
    return abs(area) // 2


def _fill_polygon(mask: np.ndarray, vertices: List[Tuple[int, int]]) -> None:
    """
    Rasterise a polygon into a boolean mask using ray-casting.

    For each pixel inside the bounding box, casts a horizontal ray and
    counts edge crossings to determine inside/outside (even-odd rule).
    Fully vectorized NumPy — no Python per-scanline loops.

    Operates in-place on *mask* (H, W bool array).
    """
    h, w = mask.shape
    n = len(vertices)
    if n < 3:
        return

    # Build edge arrays: each edge from vertices[i] → vertices[(i+1) % n]
    vx = np.array([v[0] for v in vertices], dtype=np.float64)
    vy = np.array([v[1] for v in vertices], dtype=np.float64)
    vx2 = np.roll(vx, -1)
    vy2 = np.roll(vy, -1)

    # Bounding box (clamped to mask dimensions)
    y_min = max(0, int(np.floor(vy.min())))
    y_max = min(h - 1, int(np.ceil(vy.max())))
    x_min = max(0, int(np.floor(vx.min())))
    x_max = min(w - 1, int(np.ceil(vx.max())))

    if y_min > y_max or x_min > x_max:
        return

    # Build coordinate grid over the bounding box only
    yy, xx = np.mgrid[y_min:y_max + 1, x_min:x_max + 1]
    yy = yy.astype(np.float64)
    xx = xx.astype(np.float64)

    # Ray-casting: for each pixel, count how many edges the horizontal
    # ray from (x, y) → (+∞, y) crosses.  Even-odd rule: odd = inside.
    inside = np.zeros(yy.shape, dtype=bool)

    for i in range(n):
        # Edge from (vx[i], vy[i]) → (vx2[i], vy2[i])
        y1, y2 = vy[i], vy2[i]
        x1, x2 = vx[i], vx2[i]

        # Does this edge straddle the pixel row?
        # Use consistent half-open interval: min(y1,y2) <= py < max(y1,y2)
        cond = ((y1 <= yy) & (yy < y2)) | ((y2 <= yy) & (yy < y1))

        # X-intercept of the edge at the pixel's y coordinate
        # x_cross = x1 + (yy - y1) * (x2 - x1) / (y2 - y1)
        dy = y2 - y1
        if abs(dy) < 1e-12:
            continue  # horizontal edge — skip
        x_cross = x1 + (yy - y1) * (x2 - x1) / dy

        # Ray crosses if the intercept is to the right of the pixel
        crossing = cond & (xx < x_cross)
        inside ^= crossing

    mask[y_min:y_max + 1, x_min:x_max + 1] |= inside
