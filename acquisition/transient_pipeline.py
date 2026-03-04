"""
acquisition/transient_pipeline.py

Time-resolved transient acquisition pipeline.

Transient acquisition captures the full thermal impulse response of a device:
how temperature rises and falls after a step change in applied power.  Unlike
movie mode (free-running burst), transient mode uses FPGA-synchronized triggered
capture:

  1. FPGA fires a precise single-shot power pulse.
  2. Camera captures N_delays frames at fixed intervals after the trigger edge.
  3. Steps 1–2 repeat N_averages times and frames are averaged (boxcar integration).
  4. The result is a 3D ΔR/R cube  (N_delays × H × W)  where each slice is the
     thermoreflectance image at a specific time after the pulse.

Requirements:
  - An FpgaDriver that returns supports_trigger_mode() == True.
  - A camera that supports hardware or software triggering.

If the FPGA does not support triggered mode, the pipeline falls back to a
software-timed approximation using bias on/off and time.sleep().

Output
------
  TransientResult.delta_r_cube  : (N_delays, H, W) float32  — ΔR/R at each delay
  TransientResult.delay_times_s : (N_delays,)      float64  — delay from pulse edge
  TransientResult.raw_cube      : (N_delays, H, W) float32  — averaged raw intensity

Typical use:
  pipeline = TransientAcquisitionPipeline(camera, fpga=fpga_driver, bias=bias_driver)
  pipeline.on_complete = handle_result
  pipeline.start(
      n_delays        = 50,
      delay_start_s   = 0.0,
      delay_end_s     = 0.005,    # 5 ms transient window
      pulse_dur_us    = 500.0,    # 500 μs power pulse
      n_averages      = 50,       # average 50 trigger cycles per delay
  )
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

from acquisition.drift_correction import estimate_shift as _estimate_shift
from acquisition.drift_correction import apply_shift  as _apply_shift


# ------------------------------------------------------------------ #
#  Data structures                                                    #
# ------------------------------------------------------------------ #

class TransientAcqState(Enum):
    IDLE        = auto()
    ARMING      = auto()
    CAPTURING   = auto()
    PROCESSING  = auto()
    COMPLETE    = auto()
    ABORTED     = auto()
    ERROR       = auto()


@dataclass
class TransientResult:
    """All data from one complete transient acquisition run."""

    # ΔR/R cube: (N_delays, H, W), float32
    delta_r_cube:   Optional[np.ndarray] = None

    # Averaged raw intensity cube: (N_delays, H, W), float32
    raw_cube:       Optional[np.ndarray] = None

    # Delay times in seconds from pulse leading edge
    delay_times_s:  Optional[np.ndarray] = None

    # Cold (pre-pulse) reference frame (H, W), float32
    reference:      Optional[np.ndarray] = None

    # Metadata
    n_delays:       int   = 0
    n_averages:     int   = 0
    pulse_dur_us:   float = 0.0
    delay_start_s:  float = 0.0
    delay_end_s:    float = 0.0
    exposure_us:    float = 0.0
    gain_db:        float = 0.0
    timestamp:      float = 0.0
    duration_s:     float = 0.0
    hw_triggered:   bool  = False   # True = FPGA trigger; False = SW fallback
    notes:          str   = ""

    @property
    def is_complete(self) -> bool:
        return self.delta_r_cube is not None


@dataclass
class TransientProgress:
    """Progress update emitted during transient acquisition."""
    state:          TransientAcqState
    phase:          str   = ""
    delay_index:    int   = 0
    n_delays:       int   = 0
    avg_done:       int   = 0
    n_averages:     int   = 0
    message:        str   = ""

    @property
    def fraction(self) -> float:
        if self.n_delays == 0 or self.n_averages == 0:
            return 0.0
        total = self.n_delays * self.n_averages
        done  = self.delay_index * self.n_averages + self.avg_done
        return min(1.0, done / total)


# ------------------------------------------------------------------ #
#  Pipeline                                                           #
# ------------------------------------------------------------------ #

class TransientAcquisitionPipeline:
    """
    Orchestrates FPGA-triggered time-resolved transient acquisition.

    If the FPGA supports trigger mode (supports_trigger_mode() == True), the
    pipeline uses hardware-synchronized single-shot pulses for maximum accuracy.

    If no FPGA trigger support is available, the pipeline falls back to a
    software-timed mode: it turns bias ON for pulse_dur_us, sleeps to the target
    delay, captures a frame, then turns bias OFF.  This is slower and less
    accurate but works with any hardware combination.

    Usage:
        pipeline = TransientAcquisitionPipeline(camera, fpga=fpga, bias=bias)
        pipeline.on_complete = cb
        pipeline.start(n_delays=50, delay_end_s=0.01, pulse_dur_us=500)
    """

    # Minimum recommended averages for reasonable SNR
    MIN_AVERAGES_RECOMMENDED = 10

    # Dark pixel threshold (fraction of dtype max)
    DARK_THRESHOLD_FRACTION: float = 0.005

    def __init__(self, camera, fpga=None, bias=None):
        self._cam         = camera
        self._fpga        = fpga
        self._bias        = bias
        self._state       = TransientAcqState.IDLE
        self._result      = None
        self._thread      = None
        self._abort_flag  = False
        self._roi         = None

        self.on_progress: Optional[Callable[[TransientProgress], None]] = None
        self.on_complete: Optional[Callable[[TransientResult],   None]] = None
        self.on_error:    Optional[Callable[[str],               None]] = None

    # ---------------------------------------------------------------- #
    #  Properties                                                       #
    # ---------------------------------------------------------------- #

    @property
    def state(self) -> TransientAcqState:
        return self._state

    @property
    def result(self) -> Optional[TransientResult]:
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
              n_delays:         int   = 50,
              delay_start_s:    float = 0.0,
              delay_end_s:      float = 0.005,
              pulse_dur_us:     float = 500.0,
              n_averages:       int   = 50,
              drift_correction: bool  = False) -> None:
        """
        Start transient acquisition in a background thread.

        n_delays         : Number of time-delay steps in the output cube.
        delay_start_s    : First delay from pulse edge (seconds).
        delay_end_s      : Last delay from pulse edge (seconds).
        pulse_dur_us     : Duration of each power pulse in microseconds.
        n_averages       : Number of trigger cycles averaged per delay step.
        drift_correction : If True, apply FFT phase-correlation drift
                           correction to each captured frame before
                           accumulating into the per-delay average.
        """
        if self._state == TransientAcqState.CAPTURING:
            raise RuntimeError("Transient acquisition already in progress.")
        if n_averages < 1:
            raise ValueError("n_averages must be >= 1.")
        self._abort_flag = False
        self._thread = threading.Thread(
            target=self._run,
            args=(n_delays, delay_start_s, delay_end_s,
                  pulse_dur_us, n_averages, drift_correction),
            daemon=True)
        self._thread.start()

    def run(self,
            n_delays:         int   = 50,
            delay_start_s:    float = 0.0,
            delay_end_s:      float = 0.005,
            pulse_dur_us:     float = 500.0,
            n_averages:       int   = 50,
            drift_correction: bool  = False) -> TransientResult:
        """Synchronous version — blocks until complete."""
        self.start(n_delays, delay_start_s, delay_end_s,
                   pulse_dur_us, n_averages, drift_correction)
        self._thread.join()
        return self._result

    def abort(self) -> None:
        self._abort_flag = True

    @property
    def uses_hw_trigger(self) -> bool:
        """True if the connected FPGA supports hardware trigger mode."""
        return (self._fpga is not None
                and getattr(self._fpga, 'supports_trigger_mode', lambda: False)())

    # ---------------------------------------------------------------- #
    #  Internal                                                         #
    # ---------------------------------------------------------------- #

    def _emit(self, **kwargs):
        p = TransientProgress(**kwargs)
        if self.on_progress:
            try:
                self.on_progress(p)
            except Exception:
                pass

    def _set_power(self, on: bool):
        if self._fpga is not None:
            try:
                self._fpga.set_stimulus(on)
                return
            except Exception:
                pass
        if self._bias is not None:
            try:
                (self._bias.enable if on else self._bias.disable)()
            except Exception:
                pass

    def _grab_one(self) -> Optional[np.ndarray]:
        frame = self._cam.grab(timeout_ms=2000)
        if frame is None:
            return None
        data = frame.data
        if self._roi is not None:
            data = self._roi.crop(data)
        return data.astype(np.float32)

    def _run(self,
             n_delays:         int,
             delay_start_s:    float,
             delay_end_s:      float,
             pulse_dur_us:     float,
             n_averages:       int,
             drift_correction: bool = False):
        self._state = TransientAcqState.CAPTURING
        hw_triggered = self.uses_hw_trigger
        t_start = time.time()

        delays = np.linspace(delay_start_s, delay_end_s, n_delays)

        self._result = TransientResult(
            n_delays      = n_delays,
            n_averages    = n_averages,
            pulse_dur_us  = pulse_dur_us,
            delay_start_s = delay_start_s,
            delay_end_s   = delay_end_s,
            exposure_us   = getattr(self._cam, '_cfg', {}).get('exposure_us', 0),
            gain_db       = getattr(self._cam, '_cfg', {}).get('gain', 0),
            timestamp     = t_start,
            hw_triggered  = hw_triggered,
            delay_times_s = delays,
        )

        # Configure FPGA trigger mode if supported
        if hw_triggered:
            try:
                from hardware.fpga.base import FpgaTriggerMode
                self._fpga.set_trigger_mode(FpgaTriggerMode.SINGLE_SHOT)
                self._fpga.set_pulse_duration(pulse_dur_us)
            except Exception as e:
                log.warning("FPGA trigger config failed: %s — using SW fallback", e)
                hw_triggered = False

        try:
            # ── Capture cold reference ───────────────────────────────────
            self._set_power(False)
            time.sleep(0.05)   # brief settle in off state
            self._emit(state=TransientAcqState.CAPTURING, phase="reference",
                       delay_index=0, n_delays=n_delays,
                       avg_done=0, n_averages=n_averages,
                       message="Capturing cold reference...")
            reference = self._grab_one()
            if reference is None:
                raise RuntimeError("Failed to capture cold reference frame.")
            self._result.reference = reference

            # ── Per-delay accumulation ───────────────────────────────────
            # raw_accum[i] accumulates the averaged frame for delay i
            h, w = reference.shape
            raw_accum = np.zeros((n_delays, h, w), dtype=np.float64)

            for di, delay_s in enumerate(delays):
                if self._abort_flag:
                    self._state = TransientAcqState.ABORTED
                    self._set_power(False)
                    return

                acc = np.zeros((h, w), dtype=np.float64)
                for ai in range(n_averages):
                    if self._abort_flag:
                        self._state = TransientAcqState.ABORTED
                        self._set_power(False)
                        return

                    self._emit(
                        state=TransientAcqState.CAPTURING, phase="acquire",
                        delay_index=di, n_delays=n_delays,
                        avg_done=ai, n_averages=n_averages,
                        message=(f"Delay {di+1}/{n_delays}  "
                                 f"avg {ai+1}/{n_averages}  "
                                 f"({delay_s*1e3:.2f} ms)"))

                    if hw_triggered:
                        # Arm FPGA → pulse fires → sleep to delay → grab frame
                        self._fpga.arm_trigger()
                        time.sleep(delay_s)
                        frame = self._grab_one()
                    else:
                        # SW fallback: power ON → sleep to delay → grab → power OFF
                        self._set_power(True)
                        time.sleep(delay_s)
                        frame = self._grab_one()
                        self._set_power(False)
                        time.sleep(pulse_dur_us * 1e-6)   # off-time between pulses

                    if frame is not None:
                        if drift_correction:
                            dy, dx = _estimate_shift(frame, reference)
                            frame  = _apply_shift(frame, dy, dx)
                        acc += frame

                raw_accum[di] = acc / n_averages

            # ── Power OFF (ensure) ───────────────────────────────────────
            self._set_power(False)

            # Restore FPGA to continuous mode
            if hw_triggered:
                try:
                    from hardware.fpga.base import FpgaTriggerMode
                    self._fpga.set_trigger_mode(FpgaTriggerMode.CONTINUOUS)
                except Exception:
                    pass

            # ── Processing — compute ΔR/R cube ───────────────────────────
            self._state = TransientAcqState.PROCESSING
            self._emit(state=TransientAcqState.PROCESSING, phase="processing",
                       delay_index=0, n_delays=n_delays,
                       avg_done=0, n_averages=n_averages,
                       message="Computing ΔR/R cube...")

            dtype_max  = float(np.iinfo(np.uint16).max)
            threshold  = self.DARK_THRESHOLD_FRACTION * dtype_max
            dark_mask  = reference < threshold
            ref_safe   = np.where(dark_mask, 1.0, reference)

            raw_cube    = raw_accum.astype(np.float32)
            delta_cube  = np.empty_like(raw_cube)
            for i in range(n_delays):
                dr = (raw_cube[i] - reference) / ref_safe
                dr[dark_mask] = np.nan
                delta_cube[i] = dr

            self._result.raw_cube     = raw_cube
            self._result.delta_r_cube = delta_cube
            self._result.duration_s   = time.time() - t_start
            self._state = TransientAcqState.COMPLETE

            self._emit(state=TransientAcqState.COMPLETE, phase="complete",
                       delay_index=n_delays, n_delays=n_delays,
                       avg_done=n_averages, n_averages=n_averages,
                       message=(f"Complete: {n_delays} delay steps × "
                                f"{n_averages} averages.  "
                                f"{'HW trigger' if hw_triggered else 'SW fallback'}."))

            if self.on_complete:
                self.on_complete(self._result)

        except Exception as e:
            try:
                self._set_power(False)
                if hw_triggered:
                    from hardware.fpga.base import FpgaTriggerMode
                    self._fpga.set_trigger_mode(FpgaTriggerMode.CONTINUOUS)
            except Exception:
                pass
            self._state = TransientAcqState.ERROR
            msg = f"Transient acquisition error: {e}"
            log.error(msg, exc_info=True)
            self._emit(state=TransientAcqState.ERROR, phase="error",
                       delay_index=0, n_delays=n_delays,
                       avg_done=0, n_averages=n_averages,
                       message=msg)
            if self.on_error:
                self.on_error(msg)
