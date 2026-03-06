"""
hardware/cameras/simulated.py

Simulated camera for development and testing without hardware.
Generates realistic synthetic frames — thermoreflectance-like patterns
that respond correctly to exposure and gain changes.

Config keys (under hardware.camera):
    width:        1920
    height:       1200
    fps:          30
    exposure_us:  5000
    gain:         0.0
    noise_level:  50      ADU of simulated shot noise
"""

import time
import threading
import numpy as np
from typing import Optional

import logging
log = logging.getLogger(__name__)

from .base import CameraDriver, CameraFrame, CameraInfo


class SimulatedDriver(CameraDriver):
    """
    Synthetic camera — no hardware required.
    Frame brightness scales with exposure and gain, noise is Poisson.
    Useful for UI development, CI/CD testing, and demos.

    Thread-safety: set_resolution() and set_fps() may be called from the
    GUI thread while grab() runs on a background thread.  _lock serialises
    access to the mutable frame-geometry state (_W, _H, _pattern) so that
    grab() never reads a partially-updated pattern.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._W           = cfg.get("width",  1920)
        self._H           = cfg.get("height", 1200)
        self._fps         = cfg.get("fps",    30)
        self._noise       = cfg.get("noise_level", 50)
        self._exposure_us = float(cfg.get("exposure_us", 5000))
        self._gain_db     = float(cfg.get("gain", 0.0))
        self._frame_idx   = 0
        self._running     = False
        self._last_grab   = 0.0
        self._pattern     = None
        # Guards concurrent access to _W, _H, _fps, and _pattern.
        # grab() holds it only for the short array-math section, not the
        # time.sleep(), so set_resolution() is never blocked for long.
        self._lock        = threading.Lock()

    def _make_pattern(self) -> np.ndarray:
        """Generate a static synthetic thermoreflectance-like base pattern."""
        x = np.linspace(0, 4 * np.pi, self._W)
        y = np.linspace(0, 4 * np.pi, self._H)
        xx, yy    = np.meshgrid(x, y)
        pattern   = np.sin(xx) * np.cos(yy) * 0.5 + 0.5
        # Add a hot-spot in the center
        cx, cy    = self._W // 2, self._H // 2
        r2        = ((np.arange(self._W) - cx) ** 2)[None, :] + \
                    ((np.arange(self._H) - cy) ** 2)[:, None]
        hotspot   = np.exp(-r2 / (2 * (min(self._W, self._H) * 0.1) ** 2))
        pattern   = pattern * 0.4 + hotspot * 0.6
        # Scale to 12-bit range
        return (pattern * 4095).astype(np.float32)

    def open(self) -> None:
        self._pattern = self._make_pattern()
        self._info    = CameraInfo(
            driver    = "simulated",
            model     = "Simulated Camera",
            serial    = "SIM-00001",
            width     = self._W,
            height    = self._H,
            bit_depth = 12,
            max_fps   = float(self._fps),
        )
        self._open = True
        log.info(f"Simulated camera open ({self._W}x{self._H} @ {self._fps}fps)")
        log.info("(No hardware required — synthetic frames)")

    def start(self) -> None:
        self._running   = True
        self._last_grab = time.time()

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self.stop()
        self._open = False

    def grab(self, timeout_ms: int = 2000) -> Optional[CameraFrame]:
        if not self._running:
            return None

        # Simulate frame rate — sleep OUTSIDE the lock so set_resolution()
        # is never blocked during the inter-frame idle period.
        with self._lock:
            fps = self._fps
        period  = 1.0 / fps
        now     = time.time()
        elapsed = now - self._last_grab
        if elapsed < period:
            time.sleep(period - elapsed)
        self._last_grab = time.time()

        # Hold the lock only for the array-math section so that a concurrent
        # set_resolution() call never reads a partially-updated pattern.
        with self._lock:
            gain_linear = 10 ** (self._gain_db / 20.0)
            scale       = (self._exposure_us / 5000.0) * gain_linear
            base        = np.clip(self._pattern * scale, 0, 4095)

            # Add Poisson-like noise
            noise = np.random.normal(0, self._noise, base.shape).astype(np.float32)
            frame = np.clip(base + noise, 0, 4095).astype(np.uint16)

            # Add slow drift to simulate thermal change
            drift = int(50 * np.sin(time.time() * 0.2))
            frame = np.clip(frame.astype(np.int32) + drift, 0, 4095).astype(np.uint16)

            self._frame_idx += 1
            return CameraFrame(
                data        = frame,
                frame_index = self._frame_idx,
                exposure_us = self._exposure_us,
                gain_db     = self._gain_db,
                timestamp   = time.time(),
            )

    def supports_runtime_resolution(self) -> bool:
        return True

    def set_resolution(self, width: int, height: int) -> None:
        """Change the synthetic frame size at runtime (thread-safe)."""
        width  = max(1, int(width))
        height = max(1, int(height))
        with self._lock:
            if width == self._W and height == self._H:
                return
            self._W = width
            self._H = height
            self._pattern = self._make_pattern()          # regenerate under lock
            self._info = CameraInfo(
                driver    = self._info.driver,
                model     = self._info.model,
                serial    = self._info.serial,
                width     = self._W,
                height    = self._H,
                bit_depth = self._info.bit_depth,
                max_fps   = self._info.max_fps,
            )
            self._cfg["width"]  = width
            self._cfg["height"] = height
        log.debug("[SIM] Resolution = %dx%d", width, height)

    def set_fps(self, fps: float) -> None:
        """Change the target frame rate at runtime (thread-safe)."""
        fps = max(1.0, float(fps))
        with self._lock:
            self._fps          = fps
            self._cfg["fps"]   = fps
            self._info = CameraInfo(
                driver    = self._info.driver,
                model     = self._info.model,
                serial    = self._info.serial,
                width     = self._info.width,
                height    = self._info.height,
                bit_depth = self._info.bit_depth,
                max_fps   = fps,
            )
        log.debug("[SIM] FPS = %.1f", fps)

    def set_exposure(self, microseconds: float) -> None:
        self._exposure_us            = microseconds
        self._cfg["exposure_us"]     = microseconds
        log.debug(f"[SIM] ExposureTime = {microseconds:.0f} us")

    def set_gain(self, db: float) -> None:
        self._gain_db        = db
        self._cfg["gain"]    = db
        log.debug("[SIM] Gain = %.1f dB", db)

    def exposure_range(self) -> tuple:
        return (50.0, 200_000.0)

    def gain_range(self) -> tuple:
        return (0.0, 24.0)

# Backward-compatible alias used by tests and legacy tooling
SimulatedCamera = SimulatedDriver
