"""
acquisition.processing.image_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared helpers for converting numpy arrays to PNG images (as raw bytes,
temp-file paths, or base64 data-URIs).  Extracted from the near-duplicate
``_array_to_tmpimg`` (report.py) and ``_array_to_b64`` (report_html.py).
"""

from __future__ import annotations

import base64
import io
import tempfile
from typing import Optional, Tuple

import numpy as np

from acquisition.processing.processing import to_display


# ------------------------------------------------------------------ #
#  Core renderer                                                      #
# ------------------------------------------------------------------ #

def render_array(
    arr: np.ndarray,
    *,
    mode: str = "percentile",
    colormap: str = "Thermal Delta",
    width: int = 300,
    height: int = 220,
) -> Optional[bytes]:
    """Normalise *arr*, apply *colormap*, resize, and encode to PNG bytes.

    Parameters
    ----------
    arr : numpy.ndarray
        2-D or 3-D image data.
    mode : str
        Display-normalisation mode forwarded to ``to_display()``.
    colormap : str
        One of ``"Thermal Delta"`` / ``"signed"`` (red-blue diverging),
        ``"gray"``, or an OpenCV named map (``"hot"``, ``"cool"``,
        ``"viridis"``).
    width, height : int
        Target pixel dimensions after resize.

    Returns
    -------
    bytes or None
        Raw PNG bytes, or *None* if no encoder is available.
    """
    disp = to_display(arr, mode=mode)

    # -- build RGB array ------------------------------------------------
    if colormap in ("Thermal Delta", "signed") and arr is not None:
        d = arr.astype(np.float32)
        limit = float(np.percentile(np.abs(d), 99.5)) or 1e-9
        normed = np.clip(d / limit, -1.0, 1.0)
        r = (np.clip(normed, 0, 1) * 255).astype(np.uint8)
        b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
        g = np.zeros_like(r)
        rgb = np.stack([r, g, b], axis=-1)

    elif colormap != "gray" and disp.ndim == 2:
        try:
            import cv2
            cv_maps = {
                "hot": cv2.COLORMAP_HOT,
                "cool": cv2.COLORMAP_COOL,
                "viridis": cv2.COLORMAP_VIRIDIS,
            }
            if colormap in cv_maps:
                # applyColorMap returns BGR; convert to RGB for consistency.
                bgr = cv2.applyColorMap(disp, cv_maps[colormap])
                rgb = bgr[:, :, ::-1].copy()
            else:
                rgb = np.stack([disp] * 3, axis=-1)
        except ImportError:
            rgb = np.stack([disp] * 3, axis=-1)

    elif disp.ndim == 2:
        rgb = np.stack([disp] * 3, axis=-1)
    else:
        rgb = disp

    # -- resize ---------------------------------------------------------
    h, w = rgb.shape[:2]
    if h > 0 and w > 0:
        try:
            import cv2
            rgb = cv2.resize(rgb, (width, height))
        except ImportError:
            pass  # use original size

    # -- encode to PNG --------------------------------------------------
    return _encode_png(rgb)


# ------------------------------------------------------------------ #
#  Convenience wrappers                                               #
# ------------------------------------------------------------------ #

def render_to_tmpfile(
    arr: np.ndarray,
    *,
    mode: str = "percentile",
    colormap: str = "Thermal Delta",
    width: int = 300,
    height: int = 220,
    suffix: str = ".png",
) -> Optional[str]:
    """Render *arr* and write the PNG to a temporary file.

    Returns the file path, or *None* on failure.
    """
    png_bytes = render_array(
        arr, mode=mode, colormap=colormap, width=width, height=height,
    )
    if png_bytes is None:
        return None

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(png_bytes)
    finally:
        tmp.close()
    return tmp.name


def render_to_b64(
    arr: np.ndarray,
    *,
    mode: str = "percentile",
    colormap: str = "Thermal Delta",
    width: int = 600,
    height: int = 440,
) -> str:
    """Render *arr* and return a ``data:image/png;base64,…`` URI string.

    Returns an empty string on failure.
    """
    png_bytes = render_array(
        arr, mode=mode, colormap=colormap, width=width, height=height,
    )
    if png_bytes is None:
        return ""

    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ------------------------------------------------------------------ #
#  Internal encoder                                                   #
# ------------------------------------------------------------------ #

def _encode_png(rgb: np.ndarray) -> Optional[bytes]:
    """Encode an RGB uint8 array to PNG bytes.

    Tries OpenCV first, then Pillow.  Returns *None* if neither is
    available.
    """
    try:
        import cv2
        # cv2.imencode expects BGR
        _, buf = cv2.imencode(".png", rgb[:, :, ::-1])
        return buf.tobytes()
    except ImportError:
        pass

    try:
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(rgb)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        pass

    return None
