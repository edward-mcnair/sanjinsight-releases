"""
acquisition/video_export.py

Export a frame cube (N × H × W) to MP4 or AVI video.

Tries OpenCV (cv2.VideoWriter) first, falls back to imageio if available.
If neither is installed, raises ImportError with install instructions.

Usage:
    from acquisition.video_export import export_video

    export_video(
        frame_cube,        # (N, H, W) float64
        output_path,       # "movie.mp4"
        fps=10.0,
        colormap="inferno",
    )
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def export_video(
    frame_cube: np.ndarray,
    output_path: str | Path,
    *,
    fps: float = 10.0,
    colormap: str = "inferno",
    normalize: str = "global",
) -> Path:
    """Write a video file from a 3D numpy array.

    Parameters
    ----------
    frame_cube : ndarray  (N, H, W) float
        Stack of frames to encode.
    output_path : str or Path
        Destination file.  Extension determines format (.mp4 / .avi).
    fps : float
        Playback frame rate.
    colormap : str
        OpenCV colormap name (e.g. "inferno", "hot", "viridis", "gray").
    normalize : str
        "global" normalizes to (min, max) across entire cube.
        "per_frame" normalizes each frame independently.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    ImportError
        If neither OpenCV nor imageio is available.
    """
    output_path = Path(output_path)
    cube = np.asarray(frame_cube)
    if cube.ndim != 3:
        raise ValueError(f"Expected 3D array (N,H,W), got shape {cube.shape}")
    n_frames, h, w = cube.shape

    # Normalise to uint8
    frames_u8 = _normalise_cube(cube, normalize)

    # Apply colormap and write
    try:
        return _write_opencv(frames_u8, output_path, fps, colormap)
    except ImportError:
        pass

    try:
        return _write_imageio(frames_u8, output_path, fps, colormap)
    except ImportError:
        pass

    raise ImportError(
        "Video export requires OpenCV or imageio.\n"
        "Install one of:\n"
        "  pip install opencv-python\n"
        "  pip install imageio imageio-ffmpeg"
    )


def available_formats() -> list[str]:
    """Return list of supported video extensions."""
    return [".mp4", ".avi"]


def _normalise_cube(cube: np.ndarray, mode: str) -> np.ndarray:
    """Convert float cube to uint8."""
    if mode == "global":
        lo = np.nanmin(cube)
        hi = np.nanmax(cube)
        span = hi - lo if hi != lo else 1.0
        normed = ((cube - lo) / span * 255).clip(0, 255).astype(np.uint8)
    else:
        normed = np.empty_like(cube, dtype=np.uint8)
        for i in range(cube.shape[0]):
            frame = cube[i]
            lo = np.nanmin(frame)
            hi = np.nanmax(frame)
            span = hi - lo if hi != lo else 1.0
            normed[i] = ((frame - lo) / span * 255).clip(0, 255).astype(np.uint8)
    return normed


# ── OpenCV backend ───────────────────────────────────────────────────

_CV_CMAPS = {
    "gray":     None,
    "hot":      11,    # cv2.COLORMAP_HOT
    "inferno":  20,    # cv2.COLORMAP_INFERNO
    "viridis":  16,    # cv2.COLORMAP_VIRIDIS
    "jet":      2,     # cv2.COLORMAP_JET
    "turbo":    20,    # cv2.COLORMAP_TURBO (same slot as inferno on older cv2)
    "magma":    13,    # cv2.COLORMAP_MAGMA
    "plasma":   15,    # cv2.COLORMAP_PLASMA
}


def _write_opencv(
    frames_u8: np.ndarray,
    output_path: Path,
    fps: float,
    colormap: str,
) -> Path:
    import cv2

    n, h, w = frames_u8.shape
    suffix = output_path.suffix.lower()

    if suffix == ".mp4":
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    elif suffix == ".avi":
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    else:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h), isColor=True)
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open VideoWriter for {output_path}")

    cmap_id = _CV_CMAPS.get(colormap)

    try:
        for i in range(n):
            frame = frames_u8[i]
            if cmap_id is not None:
                bgr = cv2.applyColorMap(frame, cmap_id)
            else:
                bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            writer.write(bgr)
    finally:
        writer.release()

    log.info("Video exported (OpenCV): %s  (%d frames, %.1f fps)", output_path, n, fps)
    return output_path


# ── imageio backend ──────────────────────────────────────────────────

def _write_imageio(
    frames_u8: np.ndarray,
    output_path: Path,
    fps: float,
    colormap: str,
) -> Path:
    import imageio.v3 as iio

    n, h, w = frames_u8.shape

    # Apply colormap via matplotlib if available
    try:
        from matplotlib import cm
        cmap_fn = cm.get_cmap(colormap)
        colored_frames = []
        for i in range(n):
            rgba = cmap_fn(frames_u8[i] / 255.0)
            rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
            colored_frames.append(rgb)
    except (ImportError, ValueError):
        # No matplotlib or unknown cmap — write grayscale as RGB
        colored_frames = [np.stack([frames_u8[i]] * 3, axis=-1) for i in range(n)]

    stack = np.stack(colored_frames, axis=0)
    iio.imwrite(str(output_path), stack, fps=fps)

    log.info("Video exported (imageio): %s  (%d frames, %.1f fps)", output_path, n, fps)
    return output_path
