"""
acquisition/roi.py

Region of Interest — a simple rectangle that restricts acquisition
and analysis to a sub-region of the camera frame.

ROI coordinates are always in full-frame pixel space (not relative).
All crop/apply operations are pure numpy — no extra dependencies.

Usage:
    roi = Roi(x=100, y=80, w=400, h=300)
    cropped = roi.crop(frame_data)          # returns sub-array
    full    = roi.embed(cropped, frame_data) # paste back into full frame
    mask    = roi.mask(frame_data.shape)    # boolean mask
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np


@dataclass
class Roi:
    """
    Axis-aligned rectangular ROI in pixel coordinates.

    x, y  — top-left corner (inclusive)
    w, h  — width and height in pixels

    All values are integers.  (0,0,0,0) means "full frame" (no crop).
    """
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    # ---------------------------------------------------------------- #

    @property
    def is_empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w * self.h)

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def clamp(self, frame_h: int, frame_w: int) -> "Roi":
        """Return a copy clamped to the frame bounds."""
        x  = max(0, min(self.x,  frame_w - 1))
        y  = max(0, min(self.y,  frame_h - 1))
        x2 = max(0, min(self.x2, frame_w))
        y2 = max(0, min(self.y2, frame_h))
        return Roi(x=x, y=y, w=x2 - x, h=y2 - y)

    def crop(self, image: np.ndarray) -> np.ndarray:
        """
        Return the sub-array of image corresponding to this ROI.
        If ROI is empty, returns the full image.
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
        Pixels outside the ROI keep their template values.
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
        """
        h, w = shape[:2]
        m    = np.zeros((h, w), dtype=bool)
        if self.is_empty:
            m[:] = True
            return m
        roi  = self.clamp(h, w)
        m[roi.y:roi.y2, roi.x:roi.x2] = True
        return m

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @staticmethod
    def from_dict(d: dict) -> "Roi":
        return Roi(x=d.get("x", 0), y=d.get("y", 0),
                   w=d.get("w", 0), h=d.get("h", 0))

    @staticmethod
    def full(frame_h: int, frame_w: int) -> "Roi":
        return Roi(x=0, y=0, w=frame_w, h=frame_h)

    def __str__(self):
        if self.is_empty:
            return "Roi(full frame)"
        return f"Roi(x={self.x}, y={self.y}, w={self.w}, h={self.h})"

    def __repr__(self):
        return str(self)
