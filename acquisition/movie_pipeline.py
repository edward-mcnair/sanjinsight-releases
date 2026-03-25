"""
acquisition/movie_pipeline.py

Movie Mode acquisition pipeline — high-speed burst capture for thermal transient imaging.

Movie mode captures a sequence of N frames at the camera's maximum frame rate,
with the DUT powered on (or immediately after a power step).  The result is a
3D time-ordered frame cube from which per-frame ΔR/R images can be computed if
a cold reference frame is available.

Signal chain:
  1. (Optionally) capture a cold reference frame (device OFF)
  2. Apply DUT power ON via bias or FPGA
  3. Capture N frames as fast as possible → 3D cube (N × H × W)
  4. (Optionally) compute ΔR/R cube: (frame[i] - reference) / reference

Output
------
  MovieResult.frame_cube      : np.ndarray (N × H × W, float32) — raw intensity
  MovieResult.delta_r_cube    : np.ndarray (N × H × W, float32) — ΔR/R, or None
  MovieResult.timestamps_s    : np.ndarray (N,) — relative capture times in seconds

Typical use:
  pipeline = MovieAcquisitionPipeline(camera, bias=bias_driver)
  pipeline.on_complete = handle_result
  pipeline.start(n_frames=200, capture_reference=True)
"""

from __future__ import annotations

import time
import threading
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum, auto

log = logging.getLogger(__name__)


from acquisition.drift_correction import estimate_shift as _estimate_shift
from acquisition.drift_correction import apply_shift  as _apply_shift


# ------------------------------------------------------------------ #
#  Data structures                                                    #
# ------------------------------------------------------------------ #

class MovieAcqState(Enum):
    IDLE        = auto()
    CAPTURING   = auto()
    PROCESSING  = auto()
    COMPLETE    = auto()
    ABORTED     = auto()
    ERROR       = auto()


@dataclass
class MovieResult:
    """All data produced by one movie-mode burst acquisition."""

    # 3D frame cube: (N_frames, H, W), float32
    frame_cube:   Optional[np.ndarray] = None

    # Per-frame ΔR/R cube: (N_frames, H, W), float32 — None if no reference
    delta_r_cube: Optional[np.ndarray] = None

    # Reference (cold) frame used for ΔR/R computation; uint16/float32, (H, W)
    reference:    Optional[np.ndarray] = None

    # Relative timestamps in seconds from start of burst
    timestamps_s: Optional[np.ndarray] = None

    # Metadata
    n_frames:     int   = 0
    frames_captured: int = 0
    exposure_us:  float = 0.0
    gain_db:      float = 0.0
    timestamp:    float = 0.0       # wall-clock time of burst start
    duration_s:   float = 0.0
    fps_achieved: float = 0.0       # actual achieved frame rate
    notes:        str   = ""

    @property
    def is_complete(self) -> bool:
        return self.frame_cube is not None

    @property
    def n_delays(self) -> int:
        if self.frame_cube is None:
            return 0
        return self.frame_cube.shape[0]

    def frame_at(self, index: int) -> Optional[np.ndarray]:
        """Return the frame at a given time index, or None."""
        if self.frame_cube is None or index < 0 or index >= self.n_delays:
            return None
        return self.frame_cube[index]

    def delta_r_at(self, index: int) -> Optional[np.ndarray]:
        """Return the ΔR/R slice at a given time index, or None."""
        if self.delta_r_cube is None or index < 0 or index >= self.n_delays:
            return None
        return self.delta_r_cube[index]


@dataclass
class MovieProgress:
    """Progress update emitted during burst capture."""
    state:        MovieAcqState
    phase:        str    = ""    # "reference", "burst", "processing"
    frames_done:  int    = 0
    frames_total: int    = 0
    message:      str    = ""

    @property
    def fraction(self) -> float:
        if self.frames_total == 0:
            return 0.0
        return min(1.0, self.frames_done / self.frames_total)


# ------------------------------------------------------------------ #
#  Pipeline                                                           #
# ------------------------------------------------------------------ #

class MovieAcquisitionPipeline:
    """
    Orchestrates a high-speed burst acquisition for movie mode.

    Usage (non-blocking):
        pipeline = MovieAcquisitionPipeline(camera, bias=bias_driver)
        pipeline.on_progress = my_progress_cb
        pipeline.on_complete = my_complete_cb
        pipeline.start(n_frames=200, capture_reference=True)

    Usage (blocking):
        result = pipeline.run(n_frames=200, capture_reference=True)
    """

    # Dark pixel threshold — frames below this fraction of dtype max are masked
    DARK_THRESHOLD_FRACTION: float = 0.005

    def __init__(self, camera, bias=None, fpga=None):
        """
        camera : CameraDriver — must be open and streaming.
        bias   : BiasDriver | None — toggled ON for burst, OFF before reference.
        fpga   : FpgaDriver | None — set_stimulus() called if bias is None.
        """
        self._cam         = camera
        self._bias        = bias
        self._fpga        = fpga
        self._state       = MovieAcqState.IDLE
        self._result      = None
        self._thread      = None
        self._abort_flag  = False
        self._roi         = None

        self.on_progress: Optional[Callable[[MovieProgress], None]] = None
        self.on_complete: Optional[Callable[[MovieResult],   None]] = None
        self.on_error:    Optional[Callable[[str],           None]] = None

    # ---------------------------------------------------------------- #
    #  Properties                                                       #
    # ---------------------------------------------------------------- #

    @property
    def state(self) -> MovieAcqState:
        return self._state

    @property
    def result(self) -> Optional[MovieResult]:
        return self._result

    @property
    def roi(self):
        return self._roi

    @roi.setter
    def roi(self, value):
        from acquisition.roi import Roi
        if value is None or (isinstance(value, Roi) and value.is_empty):
            self._roi = None
        else:
            self._roi = value

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def start(self,
              n_frames: int = 200,
              capture_reference: bool = True,
              settle_s: float = 0.05,
              drift_correction: bool = False) -> None:
        """
        Start movie burst in a background thread (non-blocking).

        n_frames          : Number of frames to capture in the burst.
        capture_reference : If True, capture one reference (cold) frame first
                            and compute ΔR/R for each burst frame.
        settle_s          : Seconds to wait after power-on before burst starts.
        drift_correction  : If True (and a cold reference was captured), apply
                            FFT phase-correlation drift correction to every
                            burst frame before stacking into the cube.
        """
        if self._state == MovieAcqState.CAPTURING:
            raise RuntimeError("Movie acquisition already in progress.")
        self._abort_flag = False
        self._thread = threading.Thread(
            target=self._run,
            args=(n_frames, capture_reference, settle_s, drift_correction),
            daemon=True)
        self._thread.start()

    def run(self,
            n_frames: int = 200,
            capture_reference: bool = True,
            settle_s: float = 0.05,
            drift_correction: bool = False) -> MovieResult:
        """Synchronous version of start() — blocks until complete."""
        self.start(n_frames, capture_reference, settle_s, drift_correction)
        self._thread.join()
        return self._result

    def abort(self) -> None:
        """Request abort (non-blocking)."""
        self._abort_flag = True

    # ---------------------------------------------------------------- #
    #  Internal                                                         #
    # ---------------------------------------------------------------- #

    def _emit(self, **kwargs):
        p = MovieProgress(**kwargs)
        if self.on_progress:
            try:
                self.on_progress(p)
            except Exception:
                pass

    def _set_power(self, on: bool):
        """Toggle DUT power via FPGA then bias (priority order)."""
        if self._fpga is not None:
            try:
                self._fpga.set_stimulus(on)
                return
            except Exception as e:
                log.warning("FPGA set_stimulus(%s) failed: %s", on, e)
        if self._bias is not None:
            try:
                if on:
                    self._bias.enable()
                else:
                    self._bias.disable()
            except Exception as e:
                log.warning("Bias toggle failed: %s", e)

    def _grab_one(self) -> Optional[tuple]:
        """Grab one frame; return (data_array, timestamp) or None."""
        frame = self._cam.grab(timeout_ms=2000)
        if frame is None:
            return None
        t = time.time()
        data = frame.data
        if self._roi is not None:
            data = self._roi.crop(data)
        return data.astype(np.float64), t

    def _run(self, n_frames: int, capture_reference: bool, settle_s: float,
             drift_correction: bool = False):
        self._state = MovieAcqState.CAPTURING
        self._result = MovieResult(
            n_frames    = n_frames,
            exposure_us = getattr(self._cam, '_cfg', {}).get('exposure_us', 0),
            gain_db     = getattr(self._cam, '_cfg', {}).get('gain', 0),
            timestamp   = time.time(),
        )
        t_start = time.time()

        try:
            # ── Phase 1: Optional cold reference ────────────────────────
            reference = None
            if capture_reference:
                self._set_power(False)
                self._emit(state=MovieAcqState.CAPTURING, phase="reference",
                           frames_done=0, frames_total=1,
                           message="Capturing cold reference frame...")
                r = self._grab_one()
                if r is None:
                    raise RuntimeError("Failed to capture reference frame.")
                reference = r[0]   # float32 (H × W)
                self._result.reference = reference
                self._emit(state=MovieAcqState.CAPTURING, phase="reference",
                           frames_done=1, frames_total=1,
                           message="Reference captured.")

            if self._abort_flag:
                self._state = MovieAcqState.ABORTED
                return

            # ── Phase 2: Power ON + settle ───────────────────────────────
            self._set_power(True)
            if settle_s > 0.0:
                self._emit(state=MovieAcqState.CAPTURING, phase="settle",
                           frames_done=0, frames_total=0,
                           message=f"Settling {settle_s * 1000:.0f} ms...")
                time.sleep(settle_s)

            # ── Phase 3: Burst capture ───────────────────────────────────
            frames   : list[np.ndarray] = []
            times_abs: list[float]      = []
            t_burst_start = time.time()

            self._emit(state=MovieAcqState.CAPTURING, phase="burst",
                       frames_done=0, frames_total=n_frames,
                       message=f"Burst: 0/{n_frames} frames...")

            while len(frames) < n_frames:
                if self._abort_flag:
                    self._state = MovieAcqState.ABORTED
                    self._set_power(False)
                    return
                r = self._grab_one()
                if r is None:
                    continue
                frame_data = r[0]
                if drift_correction and reference is not None:
                    # Drift estimation requires 2-D input; use
                    # luminance for multi-channel frames.
                    f_mono = frame_data.mean(axis=2) if frame_data.ndim == 3 else frame_data
                    r_mono = reference.mean(axis=2) if reference.ndim == 3 else reference
                    dy, dx = _estimate_shift(f_mono, r_mono)
                    frame_data = _apply_shift(frame_data, dy, dx)
                frames.append(frame_data)
                times_abs.append(r[1])
                self._emit(state=MovieAcqState.CAPTURING, phase="burst",
                           frames_done=len(frames), frames_total=n_frames,
                           message=f"Burst: {len(frames)}/{n_frames} frames")

            # ── Power OFF ────────────────────────────────────────────────
            self._set_power(False)

            # ── Phase 4: Processing ──────────────────────────────────────
            self._state = MovieAcqState.PROCESSING
            self._emit(state=MovieAcqState.PROCESSING, phase="processing",
                       frames_done=0, frames_total=0,
                       message="Building frame cube...")

            frame_cube = np.stack(frames, axis=0)         # (N, H, W) float64
            timestamps_s = np.array(times_abs) - times_abs[0]  # relative times

            self._result.frame_cube     = frame_cube
            self._result.timestamps_s   = timestamps_s
            self._result.frames_captured= len(frames)

            if len(frames) > 1:
                self._result.fps_achieved = (
                    len(frames) / (times_abs[-1] - times_abs[0]))

            # Per-frame ΔR/R cube
            if reference is not None:
                self._emit(state=MovieAcqState.PROCESSING, phase="processing",
                           frames_done=0, frames_total=0,
                           message="Computing ΔR/R cube...")
                dtype_max  = float(
                    np.iinfo(np.uint16).max)   # assume 16-bit source
                threshold  = self.DARK_THRESHOLD_FRACTION * dtype_max

                # Dark-pixel mask: for multi-channel, threshold on luminance
                # then broadcast the 2-D mask to match the data shape.
                if reference.ndim == 3:
                    ref_lum = reference.mean(axis=2)
                    dark_mask_2d = ref_lum < threshold
                    dark_mask = dark_mask_2d[:, :, np.newaxis]
                else:
                    dark_mask = reference < threshold
                ref_safe = np.where(dark_mask, 1.0, reference)

                delta_cube = np.empty_like(frame_cube)
                for i in range(frame_cube.shape[0]):
                    dr = (frame_cube[i] - reference) / ref_safe
                    dr[np.broadcast_to(dark_mask, dr.shape)] = np.nan
                    delta_cube[i] = dr
                self._result.delta_r_cube = delta_cube

            self._result.duration_s = time.time() - t_start
            self._state = MovieAcqState.COMPLETE

            fps_str = (f"  {self._result.fps_achieved:.1f} fps"
                       if self._result.fps_achieved > 0 else "")
            self._emit(state=MovieAcqState.COMPLETE, phase="complete",
                       frames_done=n_frames, frames_total=n_frames,
                       message=f"Complete: {n_frames} frames captured{fps_str}.")

            if self.on_complete:
                self.on_complete(self._result)

        except Exception as e:
            try:
                self._set_power(False)
            except Exception:
                pass
            self._state = MovieAcqState.ERROR
            msg = f"Movie acquisition error: {e}"
            log.error(msg, exc_info=True)
            self._emit(state=MovieAcqState.ERROR, phase="error",
                       frames_done=0, frames_total=0, message=msg)
            if self.on_error:
                self.on_error(msg)
