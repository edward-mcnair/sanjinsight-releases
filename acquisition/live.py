"""
acquisition/live.py

LiveProcessor — continuous real-time thermoreflectance computation.

Architecture
------------
A single background thread alternates between COLD and HOT states,
driven either by FPGA hardware trigger or by software timing.

State machine (per cycle):
    1. COLD  — trigger FPGA output LOW, grab N_avg frames, accumulate cold
    2. HOT   — trigger FPGA output HIGH, grab N_avg frames, accumulate hot
    3. COMPUTE — compute ΔR/R from running averages, push to output queue

Running averages use an exponential moving average (EMA):
    I_cold_ema = α × I_cold_new + (1-α) × I_cold_ema_prev
    α = 1 / accumulation_depth

This gives smooth, continuously-updated thermoreflectance with
    - low latency   (updates every cycle, not after N full cycles)
    - noise reduction proportional to accumulation depth
    - instant response to changes in the device being measured

Output
------
    LiveFrame: dataclass pushed to a queue every cycle
        .drr          — float32 ΔR/R map
        .cold_avg     — float32 current cold EMA
        .hot_avg      — float32 current hot EMA
        .snr_db       — estimated SNR
        .cycle        — frame counter
        .fps          — measured update rate

Usage
-----
    proc = LiveProcessor(camera, fpga, config)
    proc.start()
    frame = proc.get_frame(timeout=0.1)   # non-blocking
    proc.stop()
"""

from __future__ import annotations
import time, threading, queue
import numpy as np
from dataclasses import dataclass
from typing      import Optional, Callable


@dataclass
class LiveConfig:
    """Runtime-configurable parameters for the live processor."""
    frames_per_half:  int   = 4       # frames to average per cold/hot half-cycle
    accumulation:     int   = 16      # EMA depth (higher = smoother, slower response)
    trigger_mode:     str   = "fpga"  # "fpga" | "software"
    trigger_delay_ms: float = 5.0     # ms to wait after trigger before grabbing
    display_fps:      float = 10.0    # max UI refresh rate
    roi_x: int = 0;  roi_y: int = 0
    roi_w: int = 0;  roi_h: int = 0  # 0 = full frame


@dataclass
class LiveFrame:
    """One processed live frame pushed to the output queue."""
    drr:       Optional[np.ndarray] = None   # float32 ΔR/R
    cold_avg:  Optional[np.ndarray] = None   # float32 cold EMA
    hot_avg:   Optional[np.ndarray] = None   # float32 hot EMA
    dt_map:    Optional[np.ndarray] = None   # float32 ΔT (if calibration active)
    snr_db:    float = 0.0
    cycle:     int   = 0
    fps:       float = 0.0
    timestamp: float = 0.0


class LiveProcessor:
    """
    Continuously acquires and processes thermoreflectance frames.

    Thread-safe: start() / stop() / get_frame() may be called from any thread.
    update_config() can be called at runtime to change parameters.
    """

    def __init__(self, camera, fpga, cfg: LiveConfig, calibration=None):
        self._cam   = camera
        self._fpga  = fpga
        self._cal   = calibration
        self._cfg   = cfg

        self._running  = False
        self._thread   = None
        self._queue: queue.Queue[LiveFrame] = queue.Queue(maxsize=2)
        self._lock  = threading.Lock()

        # EMA state
        self._cold_ema: Optional[np.ndarray] = None
        self._hot_ema:  Optional[np.ndarray] = None
        self._cycle     = 0
        self._last_push = 0.0

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def start(self):
        # Acquire the lock to make the check-then-set atomic, preventing two
        # concurrent callers (permitted by the "Thread-safe" contract) from
        # each passing the guard and spawning a second worker thread.
        with self._lock:
            if self._running:
                return
            self._running  = True
            self._cold_ema = None
            self._hot_ema  = None
            self._cycle    = 0
            t = threading.Thread(
                target=self._loop, daemon=True, name="LiveProcessor")
            self._thread = t
        # Start OUTSIDE the lock — the thread must be able to acquire _lock
        # on its very first iteration; starting under the lock would deadlock.
        t.start()

    def stop(self):
        # Signal the loop to exit, then wait for it to finish.  The join()
        # is intentionally outside the lock so the worker thread can acquire
        # it one final time (to read cfg) before observing _running=False.
        with self._lock:
            self._running = False
            t = self._thread
            self._thread  = None
        if t:
            t.join(timeout=3.0)

    def get_frame(self, timeout: float = 0.05) -> Optional[LiveFrame]:
        """Return the latest LiveFrame, or None if none available yet."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def update_config(self, cfg: LiveConfig):
        with self._lock:
            self._cfg = cfg

    def reset_ema(self):
        """Force EMA restart (e.g. after sample change)."""
        # Guard with the same lock used by _loop() so we cannot write None into
        # _cold_ema between the worker's ``is None`` check and its subsequent
        # arithmetic — which would produce a TypeError at runtime.
        with self._lock:
            self._cold_ema = None
            self._hot_ema  = None
            self._cycle    = 0

    @property
    def is_running(self) -> bool:
        return self._running

    # ---------------------------------------------------------------- #
    #  Main loop                                                        #
    # ---------------------------------------------------------------- #

    def _loop(self):
        t_fps   = time.time()
        fps_cnt = 0
        fps_val = 0.0

        while self._running:
            with self._lock:
                cfg = self._cfg

            # ---- Cold half-cycle ----
            self._set_trigger(False, cfg)
            cold_frame = self._grab_avg(cfg.frames_per_half, cfg)
            if cold_frame is None:
                time.sleep(0.02)
                continue

            # ---- Hot half-cycle ----
            self._set_trigger(True, cfg)
            hot_frame = self._grab_avg(cfg.frames_per_half, cfg)
            if hot_frame is None:
                time.sleep(0.02)
                continue

            # ---- EMA update (lock guards against reset_ema() race) ----
            # reset_ema() may be called from the GUI thread at any time.
            # Without the lock, reset_ema() could set _cold_ema = None between
            # the ``is None`` check below and the arithmetic in the else-branch,
            # producing a TypeError.  Hold _lock for the entire read-modify-write
            # and take local snapshots so downstream ΔR/R is also race-free.
            #
            # Shape-change guard: if the camera resolution changed (e.g. the user
            # picked a new resolution in the simulated camera panel), the new frame
            # shape will differ from the stored EMA.  Treat this as a reset so we
            # never attempt to blend arrays of incompatible shapes.
            alpha = 1.0 / max(cfg.accumulation, 1)

            with self._lock:
                if (self._cold_ema is None or
                        cold_frame.shape != self._cold_ema.shape):
                    self._cold_ema = cold_frame.copy()
                    self._hot_ema  = hot_frame.copy()
                else:
                    self._cold_ema = (alpha * cold_frame +
                                      (1.0 - alpha) * self._cold_ema)
                    self._hot_ema  = (alpha * hot_frame +
                                      (1.0 - alpha) * self._hot_ema)

                self._cycle += 1
                # Snapshot under the lock — subsequent reads use these locals
                # and cannot be interrupted by a concurrent reset_ema().
                cold_ema = self._cold_ema
                hot_ema  = self._hot_ema

            # ---- ΔR/R ----
            cold_safe = np.where(cold_ema > 1.0, cold_ema, 1.0)
            drr = ((hot_ema - cold_ema) / cold_safe).astype(np.float64)

            # ---- SNR estimate ----
            snr = self._estimate_snr(drr)

            # ---- ΔT (if calibration) ----
            dt = None
            if self._cal and self._cal.valid:
                try:
                    dt = self._cal.apply(drr)
                except Exception:
                    pass

            # ---- FPS ----
            fps_cnt += 1
            now = time.time()
            elapsed = now - t_fps
            if elapsed >= 1.0:
                fps_val = fps_cnt / elapsed
                fps_cnt = 0
                t_fps   = now

            # ---- Throttle display rate ----
            min_interval = 1.0 / max(cfg.display_fps, 1.0)
            if now - self._last_push < min_interval:
                continue
            self._last_push = now

            frame = LiveFrame(
                drr      = drr,
                cold_avg = cold_ema.copy(),   # use local snapshot, not self._*
                hot_avg  = hot_ema.copy(),
                dt_map   = dt,
                snr_db   = snr,
                cycle    = self._cycle,
                fps      = fps_val,
                timestamp= now,
            )

            # Push to queue, drop oldest if full
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                pass

        # Restore trigger to OFF on exit
        self._set_trigger(False, self._cfg)

    # ---------------------------------------------------------------- #
    #  Hardware helpers                                                 #
    # ---------------------------------------------------------------- #

    def _set_trigger(self, high: bool, cfg: LiveConfig):
        """Set FPGA digital output HIGH (hot) or LOW (cold)."""
        if self._fpga is None or cfg.trigger_mode != "fpga":
            return
        try:
            self._fpga.set_stimulus(high)
        except Exception:
            pass
        if cfg.trigger_delay_ms > 0:
            time.sleep(cfg.trigger_delay_ms / 1000.0)

    def _grab_avg(self, n: int, cfg: LiveConfig) -> Optional[np.ndarray]:
        """Grab N full-frame images and return their float64 average.

        ROI cropping is NOT applied here — consumers apply ROI crops
        from the shared RoiModel so multiple ROIs can be visualised
        simultaneously.

        If the frame shape changes mid-accumulation (e.g. because
        set_resolution() was called on a simulated camera), the
        accumulator is restarted.
        """
        if self._cam is None:
            return self._synthetic_frame(cfg)

        acc   = None
        count = 0
        while count < n and self._running:
            frame = self._cam.grab(timeout_ms=500)
            if frame is None:
                continue
            data = frame.data.astype(np.float64)

            # Shape-change guard: restart accumulator if the resolution changed
            # mid-accumulation so we never add arrays of incompatible shapes.
            if acc is not None and data.shape != acc.shape:
                acc   = None
                count = 0

            acc   = data if acc is None else acc + data
            count += 1

        if acc is None or count == 0:
            return None
        return (acc / count).astype(np.float64)

    def _synthetic_frame(self, cfg: LiveConfig) -> np.ndarray:
        """Generate a synthetic full-frame camera image for simulation."""
        h, w = 480, 640
        base = np.ones((h, w), np.float32) * 2000.0
        noise = np.random.randn(h, w).astype(np.float32) * 5.0
        return base + noise

    @staticmethod
    def _estimate_snr(drr: np.ndarray) -> float:
        try:
            signal = float(np.nanpercentile(np.abs(drr), 95))
            noise  = float(np.nanstd(drr))
            if noise < 1e-15 or not np.isfinite(signal) or not np.isfinite(noise):
                return 0.0
            return float(20.0 * np.log10(signal / noise))
        except Exception:
            return 0.0
