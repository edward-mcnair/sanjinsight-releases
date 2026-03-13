"""
acquisition/pipeline.py

Thermoreflectance acquisition pipeline.

Measurement sequence:
  1. Capture N frames at baseline state  → cold_frames  (device OFF)
  2. Capture N frames at stimulus state  → hot_frames   (device ON)
  3. Average each set to suppress noise
  4. Compute thermoreflectance signal:   ΔR/R = (hot - cold) / cold

The pipeline is camera-agnostic — it works with any CameraDriver.
Progress and completion are reported via callbacks so any UI can subscribe.
"""

from __future__ import annotations

import time
import threading
import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum, auto

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Data structures                                                    #
# ------------------------------------------------------------------ #

class AcqState(Enum):
    IDLE       = auto()
    CAPTURING  = auto()
    PROCESSING = auto()
    COMPLETE   = auto()
    ABORTED    = auto()
    ERROR      = auto()


@dataclass
class AcquisitionResult:
    """All data produced by one complete hot/cold acquisition."""

    # Raw averaged frames (uint16, shape H×W)
    cold_avg:   Optional[np.ndarray] = None
    hot_avg:    Optional[np.ndarray] = None

    # Thermoreflectance signal  ΔR/R  (float32, shape H×W)
    # Values typically in range ±1e-4 to ±1e-2
    delta_r_over_r: Optional[np.ndarray] = None

    # Difference image (hot - cold) — useful for quick visual check
    difference: Optional[np.ndarray] = None

    # Metadata
    n_frames:       int   = 0
    cold_captured:      int   = 0
    hot_captured:       int   = 0

    # Dark-pixel statistics from _compute()
    dark_pixel_count:    int   = 0     # number of pixels masked as dark/noise
    dark_pixel_fraction: float = 0.0   # fraction 0.0–1.0
    exposure_us:    float = 0.0
    gain_db:        float = 0.0
    timestamp:      float = 0.0
    duration_s:     float = 0.0
    notes:          str   = ""

    @property
    def is_complete(self) -> bool:
        return self.delta_r_over_r is not None

    @property
    def snr_db(self) -> Optional[float]:
        """Signal-to-noise ratio of the ΔR/R image in dB.

        Dark pixels are stored as NaN and excluded from both the signal
        mean and the noise standard deviation.
        """
        if self.delta_r_over_r is None:
            return None
        sig   = float(np.nanmean(np.abs(self.delta_r_over_r)))
        noise = float(np.nanstd(self.delta_r_over_r))
        if not np.isfinite(sig) or sig <= 0:
            return None
        if noise == 0:
            return float('inf')
        return float(20 * np.log10(sig / noise))


@dataclass
class AcquisitionProgress:
    """Progress update emitted during capture."""
    state:        AcqState
    phase:        str    = ""    # "cold" or "hot"
    frames_done:  int    = 0
    frames_total: int    = 0
    message:      str    = ""

    @property
    def fraction(self) -> float:
        if self.frames_total == 0:
            return 0.0
        return self.frames_done / self.frames_total


# ------------------------------------------------------------------ #
#  Pipeline                                                           #
# ------------------------------------------------------------------ #

class AcquisitionPipeline:
    """
    Orchestrates a thermoreflectance hot/cold capture sequence.

    The pipeline is responsible for:
      1. Toggling the FPGA digital output (or bias source) between
         cold (OFF) and hot (ON) phases.
      2. Capturing N frames per phase and averaging them.
      3. Computing ΔR/R = (hot - cold) / cold.

    Usage:
        pipeline = AcquisitionPipeline(camera, fpga=fpga_driver,
                                        bias=bias_driver)
        pipeline.on_progress = my_progress_callback
        pipeline.on_complete = my_complete_callback

        # Non-blocking
        pipeline.start(n_frames=100)

        # Blocking
        result = pipeline.run(n_frames=100)
    """

    def __init__(self, camera, fpga=None, bias=None):
        """
        camera : CameraDriver — must be open and streaming.
        fpga   : FpgaDriver | None — if provided, set_output() is called
                 to switch the DUT drive between cold (False) and hot (True).
        bias   : BiasDriver | None — if provided and fpga is None, enable()
                 and disable() are called for hot/cold switching.
        """
        self._cam         = camera
        self._fpga        = fpga
        self._bias        = bias
        self._state       = AcqState.IDLE
        self._result      = None
        self._thread      = None
        self._abort_flag  = False
        self._roi         = None

        self.on_progress: Optional[Callable[[AcquisitionProgress], None]] = None
        self.on_complete: Optional[Callable[[AcquisitionResult],   None]] = None
        self.on_error:    Optional[Callable[[str],                  None]] = None

    def update_hardware(self, fpga=None, bias=None):
        """
        Update the hardware references used for stimulus control.
        Safe to call between acquisitions (not during).
        """
        self._fpga = fpga
        self._bias = bias

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    @property
    def roi(self):
        """Current Roi (None = full frame)."""
        return self._roi

    @roi.setter
    def roi(self, value):
        """Set Roi.  Pass None or an empty Roi() for full frame."""
        from acquisition.roi import Roi
        if value is None or (isinstance(value, Roi) and value.is_empty):
            self._roi = None
        else:
            self._roi = value

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    @property
    def state(self) -> AcqState:
        return self._state

    @property
    def result(self) -> Optional[AcquisitionResult]:
        return self._result

    def start(self, n_frames: int = 100,
              inter_phase_delay: float = 0.0) -> None:
        """
        Start acquisition in a background thread (non-blocking).

        n_frames:           Number of frames to capture per phase (hot + cold)
        inter_phase_delay:  Seconds to wait between cold and hot capture.
                            Use this time to toggle your stimulus (e.g. bias current).
        """
        if self._state == AcqState.CAPTURING:
            raise RuntimeError("Acquisition already in progress.")
        self._abort_flag = False
        self._thread = threading.Thread(
            target=self._run,
            args=(n_frames, inter_phase_delay),
            daemon=True)
        self._thread.start()

    def run(self, n_frames: int = 100,
            inter_phase_delay: float = 0.0) -> AcquisitionResult:
        """
        Run acquisition and block until complete (synchronous).
        Returns the AcquisitionResult.
        """
        self.start(n_frames, inter_phase_delay)
        self._thread.join()
        return self._result

    def abort(self) -> None:
        """Request abort. Returns immediately — check state for ABORTED."""
        self._abort_flag = True

    def capture_reference(self, n_frames: int = 100) -> Optional[np.ndarray]:
        """
        Capture N frames and return the averaged result.
        Use to capture a single phase (cold or hot) independently.
        Returns uint16 averaged frame, or None on failure.
        """
        return self._capture_phase("reference", n_frames)

    # ---------------------------------------------------------------- #
    #  Internal                                                         #
    # ---------------------------------------------------------------- #

    def _emit_progress(self, **kwargs):
        p = AcquisitionProgress(**kwargs)
        if self.on_progress:
            try:
                self.on_progress(p)
            except Exception:
                pass

    def _run(self, n_frames: int, inter_phase_delay: float):
        self._state  = AcqState.CAPTURING
        self._result = AcquisitionResult(
            n_frames    = n_frames,
            exposure_us = getattr(self._cam, '_cfg', {}).get('exposure_us', 0),
            gain_db     = getattr(self._cam, '_cfg', {}).get('gain', 0),
            timestamp   = time.time(),
        )
        t_start = time.time()

        try:
            # --- Phase 1: Cold (baseline — stimulus OFF) ---
            self._set_stimulus(False)
            self._emit_progress(
                state=AcqState.CAPTURING, phase="cold",
                frames_done=0, frames_total=n_frames,
                message="Capturing cold frames (stimulus OFF)...")

            cold_frames = self._capture_phase("cold", n_frames)
            if cold_frames is None:
                return

            self._result.cold_avg      = cold_frames
            self._result.cold_captured = n_frames

            if self._abort_flag:
                self._state = AcqState.ABORTED
                return

            # --- Inter-phase delay ---
            if inter_phase_delay > 0:
                self._emit_progress(
                    state=AcqState.CAPTURING, phase="delay",
                    frames_done=0, frames_total=0,
                    message=f"Waiting {inter_phase_delay:.1f}s before hot phase...")
                time.sleep(inter_phase_delay)

            # --- Phase 2: Hot (stimulus ON) ---
            self._set_stimulus(True)
            self._emit_progress(
                state=AcqState.CAPTURING, phase="hot",
                frames_done=0, frames_total=n_frames,
                message="Capturing hot frames (stimulus ON)...")

            hot_frames = self._capture_phase("hot", n_frames)
            if hot_frames is None:
                return

            self._result.hot_avg      = hot_frames
            self._result.hot_captured = n_frames

            # --- Restore stimulus to OFF after capture ---
            self._set_stimulus(False)

            # --- Processing ---
            self._state = AcqState.PROCESSING
            self._emit_progress(
                state=AcqState.PROCESSING, phase="processing",
                frames_done=0, frames_total=0,
                message="Computing ΔR/R...")

            self._compute(self._result)
            self._result.duration_s = time.time() - t_start
            self._state = AcqState.COMPLETE

            self._emit_progress(
                state=AcqState.COMPLETE, phase="complete",
                frames_done=n_frames * 2, frames_total=n_frames * 2,
                message=f"Complete. SNR: {self._result.snr_db:.1f} dB"
                        if self._result.snr_db else "Complete.")

            if self.on_complete:
                self.on_complete(self._result)

        except Exception as e:
            # Always restore stimulus to OFF on error
            try:
                self._set_stimulus(False)
            except Exception:
                pass
            self._state = AcqState.ERROR
            msg = f"Acquisition error: {e}"
            self._emit_progress(
                state=AcqState.ERROR, phase="error",
                frames_done=0, frames_total=0, message=msg)
            if self.on_error:
                self.on_error(msg)

    def _set_stimulus(self, active: bool):
        """
        Toggle the DUT stimulus (device ON = hot, OFF = cold).

        Priority:
          1. FPGA digital output  — cleanest hardware trigger
          2. Bias source enable/disable — software toggle fallback
          3. No hardware wired  — nothing to do (manual toggle assumed)
        """
        if self._fpga is not None:
            try:
                self._fpga.set_stimulus(active)
            except Exception as e:
                log.warning("FPGA set_stimulus(%s) failed: %s — "
                            "falling through to bias source", active, e)
            else:
                return   # FPGA handled it — don't also toggle bias

        if self._bias is not None:
            try:
                if active:
                    self._bias.enable()
                else:
                    self._bias.disable()
            except Exception:
                pass

    def _capture_phase(self, phase: str, n_frames: int) -> Optional[np.ndarray]:
        """
        Capture n_frames and return their float32 average as uint16.
        If a ROI is set, only the cropped region is accumulated.
        """
        accumulator = None
        count       = 0

        while count < n_frames:
            if self._abort_flag:
                self._state = AcqState.ABORTED
                self._emit_progress(
                    state=AcqState.ABORTED, phase=phase,
                    frames_done=count, frames_total=n_frames,
                    message="Aborted.")
                return None

            frame = self._cam.grab(timeout_ms=2000)
            if frame is None:
                continue

            # Apply ROI crop if set
            data = frame.data
            if self._roi is not None:
                data = self._roi.crop(data)
            data = data.astype(np.float64)

            if accumulator is None:
                accumulator = data
            else:
                accumulator += data

            count += 1
            self._emit_progress(
                state=AcqState.CAPTURING, phase=phase,
                frames_done=count, frames_total=n_frames,
                message=f"{phase.capitalize()}: {count}/{n_frames} frames"
                        + (f"  [ROI {self._roi.w}×{self._roi.h}]"
                           if self._roi else ""))

        avg = (accumulator / n_frames).astype(np.float32)
        return avg

    # Pixels with cold intensity below this threshold are treated as dark/noise.
    # Values below it are masked to NaN in ΔR/R to prevent garbage data.
    # Expressed as a fraction of the dtype maximum (uint16 → 65535).
    # 0.5% of full scale ≈ 328 counts for a 16-bit camera.
    DARK_THRESHOLD_FRACTION: float = 0.005

    @staticmethod
    def _compute(result: AcquisitionResult):
        """
        Compute thermoreflectance signal from averaged frames.

        ΔR/R = (R_hot - R_cold) / R_cold

        Where R is proportional to the camera intensity.
        Small values (typically 1e-4 to 1e-2) indicate temperature change.

        Dark-pixel masking
        ------------------
        Pixels where the cold (baseline) frame intensity is below
        DARK_THRESHOLD_FRACTION × dtype_max are masked to NaN.  These pixels
        are on unilluminated or shadowed regions of the device and produce
        scientifically meaningless (and numerically explosive) ΔR/R values.

        Downstream display code should treat NaN as "no data" and render them
        as black / transparent rather than as extreme signal values.
        """
        cold = result.cold_avg.astype(np.float64)
        hot  = result.hot_avg.astype(np.float64)

        # ── Dark-pixel mask ───────────────────────────────────────────
        # Determine threshold from the original dtype (uint8 → 255, uint16 → 65535)
        dtype_max  = float(np.iinfo(result.cold_avg.dtype).max)                      if np.issubdtype(result.cold_avg.dtype, np.integer) else 1.0
        threshold  = AcquisitionPipeline.DARK_THRESHOLD_FRACTION * dtype_max
        dark_mask  = cold < threshold          # True where pixel is too dark

        # ── Safe division — clamp cold to avoid divide-by-zero ────────
        # Dark pixels will be NaN'd out afterward, so the clamped value
        # (1.0) only affects those locations — no scientific impact.
        cold_safe  = np.where(dark_mask, 1.0, cold)

        # ── Compute ΔR/R ─────────────────────────────────────────────
        delta_r_r  = (hot - cold) / cold_safe

        # Apply mask: set dark pixels to NaN so they don't pollute statistics
        # or appear as false signal in the display.
        delta_r_r[dark_mask] = np.nan

        difference = (hot - cold).astype(np.float32)

        result.delta_r_over_r = delta_r_r.astype(np.float32)
        result.difference     = difference
        result.dark_pixel_count = int(dark_mask.sum())
        result.dark_pixel_fraction = float(dark_mask.mean())
