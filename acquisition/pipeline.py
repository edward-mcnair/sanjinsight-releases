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

import queue
import time
import threading
import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum, auto

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Async checkpoint writer                                            #
# ------------------------------------------------------------------ #

class _CheckpointWriter:
    """Background thread that serialises checkpoint saves off the capture loop.

    The capture loop pushes checkpoint dicts onto a queue; this writer
    drains and writes them one at a time.  If the queue backs up, older
    entries are silently dropped (only the latest matters for recovery).

    ``start()`` and ``stop()`` are idempotent and thread-safe: calling
    ``start()`` twice is harmless, and ``stop()`` on an already-stopped
    writer is a no-op.
    """

    _SENTINEL = object()

    def __init__(self):
        self._queue: queue.Queue = queue.Queue(maxsize=4)
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return  # already running — idempotent
            # Drain any stale items from a previous run
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="ckpt-writer")
            self._thread.start()

    def stop(self):
        with self._lock:
            thread = self._thread
            if thread is None:
                return  # already stopped — idempotent
            self._thread = None
        # Signal and join outside the lock to avoid deadlock
        try:
            self._queue.put(self._SENTINEL, timeout=1.0)
        except queue.Full:
            pass
        thread.join(timeout=3.0)
        if thread.is_alive():
            log.warning("Checkpoint writer did not stop within timeout")

    def enqueue(self, phase: str, accumulator: np.ndarray,
                count: int, n_frames: int):
        item = (phase, accumulator.copy(), count, n_frames)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Drop oldest, enqueue latest (only the newest checkpoint matters)
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

    def _run(self):
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                break
            phase, acc, count, n_frames = item
            try:
                from acquisition.storage.autosave import acquire_autosave
                acquire_autosave.save(
                    arrays={f"{phase}_accumulator": acc},
                    metadata={
                        "phase": phase,
                        "frames_done": count,
                        "frames_total": n_frames,
                        "checkpoint": True,
                    },
                )
            except Exception as exc:
                log.debug("Checkpoint write failed (non-fatal): %s", exc)


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

    # Raw averaged frames (float64, shape H×W or H×W×3)
    # When an ROI is active these are cropped to the ROI region.
    cold_avg:   Optional[np.ndarray] = None
    hot_avg:    Optional[np.ndarray] = None

    # Full-frame averages (always full sensor resolution).
    # Available for multi-ROI post-processing even when a single
    # ROI was active during capture.
    full_cold_avg: Optional[np.ndarray] = None
    full_hot_avg:  Optional[np.ndarray] = None

    # Thermoreflectance signal  ΔR/R  (float64, shape H×W or H×W×3)
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

    def __init__(self, camera, fpga=None, bias=None,
                 shadow_correct: bool = False):
        """
        camera         : CameraDriver — must be open and streaming.
        fpga           : FpgaDriver | None — if provided, set_output() is
                         called to switch the DUT drive between cold (False)
                         and hot (True).
        bias           : BiasDriver | None — if provided and fpga is None,
                         enable() / disable() are called for hot/cold
                         switching.
        shadow_correct : bool — if True, apply shading correction to the cold
                         average before computing ΔR/R.  Uses
                         image_filters.shadow_correct() in self-correction
                         mode (large-Gaussian envelope division).  This
                         reduces non-uniform illumination artefacts at the
                         cost of a small amount of processing time.
        """
        self._cam              = camera
        self._fpga             = fpga
        self._bias             = bias
        self._shadow_correct   = shadow_correct
        self._state            = AcqState.IDLE
        self._result           = None
        self._thread           = None
        self._abort_event      = threading.Event()
        self._lifecycle_lock   = threading.Lock()
        self._roi              = None
        self._ckpt_writer      = _CheckpointWriter()

        self.on_progress: Optional[Callable[[AcquisitionProgress], None]] = None
        self.on_complete: Optional[Callable[[AcquisitionResult],   None]] = None
        self.on_error:    Optional[Callable[[str],                  None]] = None

        # Processing hooks — callables invoked at defined pipeline stages.
        # pre_capture_hooks run before each capture phase (cold/hot).
        # post_average_hooks transform the averaged frame after capture.
        self.pre_capture_hooks:  list = []   # [Callable[[], None], ...]
        self.post_average_hooks: list = []   # [Callable[[ndarray], ndarray], ...]

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
        """Start acquisition in a background thread (non-blocking).

        Thread-safe: a lifecycle lock serialises ``start()`` / ``abort()``
        so two concurrent ``start()`` calls cannot race.

        n_frames:           Number of frames to capture per phase (hot + cold)
        inter_phase_delay:  Seconds to wait between cold and hot capture.
                            Use this time to toggle your stimulus (e.g. bias current).
        """
        with self._lifecycle_lock:
            if self._state in (AcqState.CAPTURING, AcqState.PROCESSING):
                # If the thread is dead despite an active state, reset it
                if self._thread is not None and not self._thread.is_alive():
                    log.warning("Pipeline state stuck at %s with dead thread "
                                "— resetting", self._state.name)
                    self._state = AcqState.IDLE
                else:
                    raise RuntimeError("Acquisition already in progress.")
            self._state = AcqState.IDLE
            self._result = None
            self._abort_event.clear()
            self._ckpt_writer.start()
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
        """Request abort. Returns immediately — check state for ABORTED.

        Thread-safe via the lifecycle lock.
        """
        with self._lifecycle_lock:
            self._abort_event.set()

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
                log.debug("Progress callback failed", exc_info=True)

    @staticmethod
    def _run_hooks(hooks: list, label: str = ""):
        """Run a list of hook callables, logging failures without aborting."""
        for hook in hooks:
            try:
                hook()
            except Exception as exc:
                log.warning("Hook %s (%s) failed: %s",
                            getattr(hook, '__name__', hook), label, exc)

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
            self._run_hooks(self.pre_capture_hooks, "pre_capture (cold)")
            self._set_stimulus(False)
            self._emit_progress(
                state=AcqState.CAPTURING, phase="cold",
                frames_done=0, frames_total=n_frames,
                message="Capturing cold frames (stimulus OFF)...")

            cold_full = self._capture_phase("cold", n_frames)
            if cold_full is None:
                return

            # Store full-frame as float32 to halve memory; _compute()
            # up-casts to float64 internally where precision matters.
            cold_full_f32 = cold_full.astype(np.float32)
            del cold_full  # release float64 copy early

            self._result.full_cold_avg = cold_full_f32
            self._result.cold_avg      = (self._roi.crop(cold_full_f32)
                                          if self._roi else cold_full_f32)
            self._result.cold_captured = n_frames

            if self._abort_event.is_set():
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
            self._run_hooks(self.pre_capture_hooks, "pre_capture (hot)")
            self._set_stimulus(True)
            self._emit_progress(
                state=AcqState.CAPTURING, phase="hot",
                frames_done=0, frames_total=n_frames,
                message="Capturing hot frames (stimulus ON)...")

            hot_full = self._capture_phase("hot", n_frames)
            if hot_full is None:
                return

            hot_full_f32 = hot_full.astype(np.float32)
            del hot_full

            self._result.full_hot_avg = hot_full_f32
            self._result.hot_avg      = (self._roi.crop(hot_full_f32)
                                         if self._roi else hot_full_f32)
            self._result.hot_captured = n_frames

            # --- Processing ---
            self._state = AcqState.PROCESSING
            self._emit_progress(
                state=AcqState.PROCESSING, phase="processing",
                frames_done=0, frames_total=0,
                message="Computing ΔR/R...")

            self._compute(self._result)

            # Release full-frame copies if an ROI was active — the
            # session only persists the cropped cold_avg / hot_avg.
            if self._roi:
                self._result.full_cold_avg = None
                self._result.full_hot_avg  = None

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
            self._state = AcqState.ERROR
            msg = f"Acquisition error: {e}"
            self._emit_progress(
                state=AcqState.ERROR, phase="error",
                frames_done=0, frames_total=0, message=msg)
            if self.on_error:
                self.on_error(msg)
        finally:
            self._ckpt_writer.stop()
            self._stimulus_safe_off()

    def _stimulus_safe_off(self) -> None:
        """
        Unconditionally turn the stimulus off.

        Called from the ``finally`` block of ``_run()`` to guarantee the
        DUT is never left in the powered (hot) state after any acquisition
        exit path — normal completion, abort, or exception.
        """
        if self._fpga is not None:
            try:
                self._fpga.set_stimulus(False)
            except Exception as exc:
                log.warning("_stimulus_safe_off: FPGA set_stimulus(False) failed: %s", exc)
        if self._bias is not None:
            try:
                self._bias.disable()
            except Exception as exc:
                log.warning("_stimulus_safe_off: bias.disable() failed: %s", exc)

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
            except Exception as exc:
                log.warning("Bias %s failed: %s",
                            "enable" if active else "disable", exc)

    # Checkpoint every 25% of frames (at least every 50 frames)
    _CHECKPOINT_FRAC = 0.25
    _CHECKPOINT_MIN  = 50

    def _capture_phase(self, phase: str, n_frames: int) -> Optional[np.ndarray]:
        """
        Capture n_frames at full sensor resolution and return their
        float64 average.  ROI cropping is NOT applied here — callers
        receive a full-frame average so that multiple ROIs can be
        extracted in post-processing.

        Periodically checkpoints the accumulator for crash recovery.
        """
        accumulator = None
        count       = 0
        ckpt_interval = max(self._CHECKPOINT_MIN,
                            int(n_frames * self._CHECKPOINT_FRAC))

        while count < n_frames:
            if self._abort_event.is_set():
                self._state = AcqState.ABORTED
                self._emit_progress(
                    state=AcqState.ABORTED, phase=phase,
                    frames_done=count, frames_total=n_frames,
                    message="Aborted.")
                return None

            frame = self._cam.grab(timeout_ms=2000)
            if frame is None:
                continue

            data = frame.data.astype(np.float64)

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

            # Periodic checkpoint for crash recovery
            if count % ckpt_interval == 0 and accumulator is not None:
                self._save_capture_checkpoint(
                    phase, accumulator, count, n_frames)

        avg = (accumulator / n_frames).astype(np.float64)
        for hook in self.post_average_hooks:
            try:
                avg = hook(avg)
            except Exception as exc:
                log.warning("post_average hook %s failed: %s",
                            getattr(hook, '__name__', hook), exc)
        return avg

    def _save_capture_checkpoint(self, phase: str, accumulator: np.ndarray,
                                 count: int, n_frames: int) -> None:
        """Queue a mid-capture checkpoint (written asynchronously so the
        frame loop is never blocked by disk I/O)."""
        self._ckpt_writer.enqueue(phase, accumulator, count, n_frames)

    # Pixels with cold intensity below this threshold are treated as dark/noise.
    # Values below it are masked to NaN in ΔR/R to prevent garbage data.
    # Expressed as a fraction of the dtype maximum (uint16 → 65535).
    # 0.5% of full scale ≈ 328 counts for a 16-bit camera.
    DARK_THRESHOLD_FRACTION: float = 0.005

    def _compute(self, result: AcquisitionResult):
        """
        Compute thermoreflectance signal from averaged frames.

        ΔR/R = (R_hot - R_cold) / R_cold

        Where R is proportional to the camera intensity.
        Small values (typically 1e-4 to 1e-2) indicate temperature change.

        Shadow correction (optional)
        ----------------------------
        When the pipeline was constructed with shadow_correct=True the cold
        average is passed through image_filters.shadow_correct() before the
        ΔR/R computation.  This removes non-uniform illumination (shading)
        using a large-Gaussian envelope division, which can significantly
        reduce low-spatial-frequency artefacts in the ΔR/R map.

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

        # ── Optional shadow / shading correction ──────────────────────
        if self._shadow_correct:
            try:
                from acquisition.image_filters import (
                    shadow_correct as _shadow_correct,
                )
                cold = _shadow_correct(
                    cold.astype(np.float32)
                ).astype(np.float64)
                log.debug("_compute: shadow correction applied to cold_avg.")
            except Exception as exc:
                log.warning(
                    "_compute: shadow correction failed (%s); "
                    "proceeding without it.", exc
                )

        # ── Dark-pixel mask ───────────────────────────────────────────
        # cold_avg is float64 (averaged and cast by _capture_phase), so
        # np.issubdtype → integer check would always return False and
        # dtype_max would be 1.0, making the threshold 0.005 counts — far
        # too low.  Instead infer range from the actual peak value so we
        # work correctly with both uint8 (≤255) and uint16 (≤65535) cameras.
        #
        # For multi-channel (RGB) data, compute the dark mask from the
        # luminance (mean across channels) so a single 2D mask applies
        # uniformly to all channels.
        if cold.ndim == 3:
            cold_lum = cold.mean(axis=2)
        else:
            cold_lum = cold

        cold_peak  = float(cold_lum.max())
        dtype_max  = (65535.0 if cold_peak > 256.0
                      else 255.0  if cold_peak > 1.0
                      else 1.0)
        threshold  = AcquisitionPipeline.DARK_THRESHOLD_FRACTION * dtype_max
        dark_mask_2d = cold_lum < threshold     # (H, W) bool

        # ── Safe division — clamp cold to avoid divide-by-zero ────────
        # Dark pixels will be NaN'd out afterward, so the clamped value
        # (1.0) only affects those locations — no scientific impact.
        if cold.ndim == 3:
            # Broadcast 2D mask to 3D for element-wise operations
            dark_mask = dark_mask_2d[:, :, np.newaxis]
        else:
            dark_mask = dark_mask_2d
        cold_safe  = np.where(dark_mask, 1.0, cold)

        # ── Compute ΔR/R ─────────────────────────────────────────────
        delta_r_r  = (hot - cold) / cold_safe

        # Apply mask: set dark pixels to NaN so they don't pollute statistics
        # or appear as false signal in the display.
        delta_r_r[np.broadcast_to(dark_mask, delta_r_r.shape)] = np.nan

        difference = (hot - cold).astype(np.float64)

        # Store results as float32 — ΔR/R values are small (1e-4 to 1e-2)
        # and 23 bits of mantissa gives ~7 decimal digits, which is more
        # than sufficient.  This halves the memory footprint of the result.
        result.delta_r_over_r = delta_r_r.astype(np.float32)
        result.difference     = difference.astype(np.float32)
        result.dark_pixel_count = int(dark_mask_2d.sum())
        result.dark_pixel_fraction = float(dark_mask_2d.mean())
