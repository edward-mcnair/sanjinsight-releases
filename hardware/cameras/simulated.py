"""
hardware/cameras/simulated.py

Simulated camera for development and testing without hardware.
Generates realistic synthetic frames — thermoreflectance-like patterns
that respond correctly to exposure and gain changes.

Pattern source (in priority order):
  1. assets/demo_background.png  +  assets/demo_signal.png  — real images
  2. Parametric IC model          — geometry extracted from the TEN TTC-1002 /
                                    JVD274 sample visible in the demo photos
  3. (legacy) sine-wave fallback  — only if numpy itself is missing

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
import pathlib
import numpy as np
from typing import Optional, Tuple

import logging
log = logging.getLogger(__name__)

from .base import CameraDriver, CameraFrame, CameraInfo

# Path to the optional real-image assets (relative to this file's package root)
_ASSETS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "assets"
_BG_PATH    = _ASSETS_DIR / "demo_background.png"
_SIG_PATH   = _ASSETS_DIR / "demo_signal.png"


class SimulatedDriver(CameraDriver):
    """
    Synthetic camera — no hardware required.
    Frame brightness scales with exposure and gain, noise is Poisson.
    Useful for UI development, CI/CD testing, and demos.

    Pattern source
    --------------
    If  assets/demo_background.png  exists it is used as the base reflectance
    image (loaded once, resized to the current resolution on each resolution
    change).  If  assets/demo_signal.png  also exists its jet-colormap encoding
    is decoded back to a floating-point amplitude map which drives spatially-
    varying thermal drift — so the resulting frames show realistic hot-spots
    in the right locations.

    When neither file is present the driver falls back to a parametric model
    of the TEN TTC-1002 / JVD274 IC sample: two stacked die regions, a ring
    of 14 bond-wire pads on each side, L-shaped metal traces, and a Gaussian
    thermal distribution centred on each die.  This is dramatically more
    realistic than the original sine-wave pattern while requiring no external
    files.

    Thread-safety
    -------------
    set_resolution() and set_fps() may be called from the GUI thread while
    grab() runs on a background thread.  _lock serialises access to the mutable
    frame-geometry state (_W, _H, _pattern, _signal_map) so that grab() never
    reads a partially-updated pattern.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._W           = cfg.get("width",  1920)
        self._H           = cfg.get("height", 1200)
        self._fps         = cfg.get("fps",    30)
        self._noise       = cfg.get("noise_level", 50)
        self._exposure_us = float(cfg.get("exposure_us", 5000))
        self._gain_db     = float(cfg.get("gain", 0.0))
        self._camera_type = cfg.get("camera_type", "tr")   # "tr" | "ir"
        self._color_mode  = cfg.get("color_mode", False)  # True → RGB (H,W,3)
        self._frame_idx   = 0
        self._running     = False
        self._last_grab   = 0.0
        self._pattern     = None
        self._signal_map  = None   # float32 H×W, 0–1; None = uniform drift
        # Guards concurrent access to _W, _H, _fps, _pattern, and _signal_map.
        # grab() holds it only for the short array-math section, not the
        # time.sleep(), so set_resolution() is never blocked for long.
        self._lock        = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Pattern generation                                                  #
    # ------------------------------------------------------------------ #

    def _make_pattern(self) -> np.ndarray:
        """Build the base reflectance pattern for the current resolution.

        Tries real demo images first; falls back to the parametric IC model.
        Also stores self._signal_map (spatially-varying thermal amplitude).
        Must be called under self._lock when resolution has already changed.
        """
        bg, sig = self._load_demo_assets()
        if bg is None:
            bg, sig = self._make_parametric_ic()
        self._signal_map = sig
        return bg

    # ── Real-image loader ─────────────────────────────────────────────── #

    def _load_demo_assets(self) -> Tuple[Optional[np.ndarray],
                                         Optional[np.ndarray]]:
        """Load assets/demo_background.png and assets/demo_signal.png.

        Returns (bg, sig) where:
          bg  — float32 H×W scaled to 12-bit (0–4095), or None if not found
          sig — float32 H×W normalised to 0–1 (warm=1), or None if not found

        Both arrays are resized to (self._H, self._W) using Lanczos resampling.
        Requires Pillow (already a project dependency).
        """
        if not _BG_PATH.exists():
            return None, None

        try:
            from PIL import Image
        except ImportError:
            log.warning("[SIM] Pillow not available — using parametric IC model")
            return None, None

        try:
            # ── Background / reflectance image ─────────────────────── #
            img = Image.open(_BG_PATH).convert("L")
            img = img.resize((self._W, self._H), Image.LANCZOS)
            bg  = np.array(img, dtype=np.float32) * (4095.0 / 255.0)
            log.info("[SIM] Loaded demo background from %s", _BG_PATH.name)

            # ── Signal / thermoreflectance map ──────────────────────── #
            sig = None
            if _SIG_PATH.exists():
                sig_img = Image.open(_SIG_PATH).convert("RGB")
                sig_img = sig_img.resize((self._W, self._H), Image.LANCZOS)
                rgb = np.array(sig_img, dtype=np.float32) / 255.0
                # Jet colourmap inversion: warm pixels have high R and low B.
                # raw = R − B  →  positive = warm, negative = cool.
                raw = rgb[:, :, 0] - rgb[:, :, 2]
                mn, mx = float(raw.min()), float(raw.max())
                if mx > mn:
                    sig = ((raw - mn) / (mx - mn)).astype(np.float32)
                else:
                    sig = np.zeros((self._H, self._W), dtype=np.float32)
                log.info("[SIM] Loaded demo signal map from %s", _SIG_PATH.name)

            return bg, sig

        except Exception as exc:
            log.warning("[SIM] Could not load demo assets: %s — "
                        "falling back to parametric IC model", exc)
            return None, None

    # ── Parametric IC model ───────────────────────────────────────────── #

    def _make_parametric_ic(self) -> Tuple[np.ndarray, np.ndarray]:
        """Generate a synthetic IC background + thermal signal map.

        The geometry is derived from visual analysis of the TEN TTC-1002 /
        JVD274 sample in the demo photos:
          • Two stacked rectangular die regions (upper and lower half)
          • 14 bond-wire pads on each side (left / right columns)
          • L-shaped metal traces around each die perimeter
          • Gaussian thermal distribution centred on each die
          • Occasional bright specks (particle contamination)

        Returns (bg, sig) as float32 arrays of shape (H, W):
          bg  — 12-bit scale (0–4095)
          sig — normalised 0–1
        """
        H, W = self._H, self._W

        # Normalised coordinate grids (0 → 1)
        xs = np.linspace(0.0, 1.0, W, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, H, dtype=np.float32)
        XX, YY = np.meshgrid(xs, ys)

        # ── Base reflectance ─────────────────────────────────────── #
        # Substrate / PCB background
        bg = np.full((H, W), 0.37, dtype=np.float32)

        # Die geometry: two rectangular regions stacked vertically
        _DIE_X0, _DIE_X1 = 0.26, 0.88
        _DIES = [
            (0.07, 0.47),   # upper die  (y0, y1)
            (0.53, 0.93),   # lower die
        ]
        for dy0, dy1 in _DIES:
            die_mask = (
                (XX >= _DIE_X0) & (XX <= _DIE_X1) &
                (YY >= dy0)     & (YY <= dy1)
            )
            bg[die_mask] = 0.50   # metal surface — brighter than substrate

            # Inner active area (slightly recessed / darker)
            ax0 = _DIE_X0 + 0.06
            ax1 = _DIE_X1 - 0.04
            ay0 = dy0 + 0.04
            ay1 = dy1 - 0.04
            active = (
                (XX >= ax0) & (XX <= ax1) &
                (YY >= ay0) & (YY <= ay1)
            )
            bg[active] = 0.43

        # L-shaped metal traces (bright) around each die
        for dy0, dy1 in _DIES:
            # Top horizontal trace
            bg[(YY >= dy0) & (YY <= dy0 + 0.022) &
               (XX >= _DIE_X0) & (XX <= _DIE_X1)] = 0.64
            # Bottom horizontal trace
            bg[(YY >= dy1 - 0.022) & (YY <= dy1) &
               (XX >= _DIE_X0) & (XX <= _DIE_X1)] = 0.64
            # Left vertical trace
            bg[(XX >= _DIE_X0) & (XX <= _DIE_X0 + 0.04) &
               (YY >= dy0) & (YY <= dy1)] = 0.58
            # Right vertical trace
            bg[(XX >= _DIE_X1 - 0.04) & (XX <= _DIE_X1) &
               (YY >= dy0) & (YY <= dy1)] = 0.58

        # Separator / gap between the two dies
        bg[(YY >= 0.47) & (YY <= 0.53)] = 0.34

        # Bond-wire pads — 14 per side (left / right)
        n_pads = 14
        # Radius in normalised coords (equal visual size regardless of aspect)
        pad_r  = 0.025
        aspect = W / H   # compensate for non-square pixels when comparing x & y
        for side_x in [0.065, 0.935]:
            for i in range(n_pads):
                cy = 0.07 + i * (0.86 / max(n_pads - 1, 1))
                # Distance with aspect correction
                dist = np.sqrt(((XX - side_x) * aspect) ** 2 +
                               (YY - cy) ** 2)
                bg[dist < pad_r]          = 0.16   # dark pad body
                bg[dist < pad_r * 0.35]   = 0.28   # slightly lighter centre

        # Particle contamination — tiny bright specks (deterministic seed)
        rng   = np.random.default_rng(42)
        n_sp  = max(1, int(H * W * 0.00003))
        sy    = rng.integers(0, H, n_sp)
        sx    = rng.integers(0, W, n_sp)
        bg[sy, sx] = np.clip(bg[sy, sx] + 0.55, 0.0, 1.0)

        # Scale to 12-bit ADU
        bg_12 = (bg * 4095.0).astype(np.float32)

        # ── Thermal / signal map ─────────────────────────────────── #
        sig = np.zeros((H, W), dtype=np.float32)

        # Gaussian hot-spot centred on each die
        die_centres = [0.27, 0.73]   # fractional y centres
        die_cx      = 0.57           # fractional x centre
        for cy in die_centres:
            r2   = (XX - die_cx) ** 2 + (YY - cy) ** 2
            sig += np.exp(-r2 / (2.0 * 0.13 ** 2))

        # Mild warming along horizontal traces
        for dy0, dy1 in _DIES:
            for ty in [dy0 + 0.011, dy1 - 0.011]:
                sig += 0.25 * np.exp(-((YY - ty) ** 2) / (2.0 * 0.008 ** 2))

        # Bond-pad ring runs slightly cooler (acts as heat sink)
        for side_x in [0.065, 0.935]:
            for i in range(n_pads):
                cy   = 0.07 + i * (0.86 / max(n_pads - 1, 1))
                dist = np.sqrt(((XX - side_x) * aspect) ** 2 +
                               (YY - cy) ** 2)
                sig[dist < pad_r * 1.5] *= 0.15

        # Normalise to [0, 1]
        mx = float(sig.max())
        if mx > 0.0:
            sig /= mx

        log.debug("[SIM] Parametric IC model generated (%dx%d)", W, H)
        return bg_12, sig.astype(np.float32)

    # ------------------------------------------------------------------ #
    #  CameraDriver interface                                              #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        with self._lock:
            self._pattern    = self._make_pattern()
        _model  = (self._cfg.get("model")
                   or ("Simulated TR Camera" if self._camera_type == "tr"
                       else "Simulated IR Camera"))
        _serial = "SIM-TR-001" if self._camera_type == "tr" else "SIM-IR-001"
        self._info = CameraInfo(
            driver       = "simulated",
            model        = _model,
            serial       = _serial,
            width        = self._W,
            height       = self._H,
            bit_depth    = 12,
            max_fps      = float(self._fps),
            camera_type  = self._camera_type,
            pixel_format = "rgb" if self._color_mode else "mono",
        )
        self._open = True
        log.info("[SIM] Camera open (%dx%d @ %.0ffps)", self._W, self._H, self._fps)

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

            # Poisson-like shot noise
            noise = np.random.normal(0, self._noise, base.shape).astype(np.float32)
            frame = np.clip(base + noise, 0, 4095).astype(np.uint16)

            # Spatially-varying thermal drift — mimics the thermoreflectance
            # modulation: pixels on the hot-spot oscillate more than cool ones.
            drift_amp = 50.0 * np.sin(time.time() * 0.2)
            if self._signal_map is not None:
                drift_arr = (drift_amp * self._signal_map).astype(np.int32)
            else:
                drift_arr = int(drift_amp)
            frame = np.clip(
                frame.astype(np.int32) + drift_arr, 0, 4095
            ).astype(np.uint16)

            # Color mode: replicate grayscale into 3 channels with slight
            # per-channel gain differences to simulate spectral variation.
            if self._color_mode:
                rgb = np.stack([
                    np.clip(frame * 1.02, 0, 4095).astype(np.uint16),  # R
                    frame,                                               # G
                    np.clip(frame * 0.97, 0, 4095).astype(np.uint16),  # B
                ], axis=-1)
                out_data = rgb
                n_ch = 3
            else:
                out_data = frame
                n_ch = 1

            self._frame_idx += 1
            return CameraFrame(
                data        = out_data,
                frame_index = self._frame_idx,
                exposure_us = self._exposure_us,
                gain_db     = self._gain_db,
                timestamp   = time.time(),
                channels    = n_ch,
                bit_depth   = 12,
            )

    # ------------------------------------------------------------------ #
    #  Runtime controls (thread-safe)                                     #
    # ------------------------------------------------------------------ #

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
            self._pattern    = self._make_pattern()   # also updates _signal_map
            self._info = CameraInfo(
                driver       = self._info.driver,
                model        = self._info.model,
                serial       = self._info.serial,
                width        = self._W,
                height       = self._H,
                bit_depth    = self._info.bit_depth,
                max_fps      = self._info.max_fps,
                camera_type  = self._info.camera_type,
                pixel_format = self._info.pixel_format,
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
                driver       = self._info.driver,
                model        = self._info.model,
                serial       = self._info.serial,
                width        = self._info.width,
                height       = self._info.height,
                bit_depth    = self._info.bit_depth,
                max_fps      = fps,
                camera_type  = self._info.camera_type,
                pixel_format = self._info.pixel_format,
            )
        log.debug("[SIM] FPS = %.1f", fps)

    def set_exposure(self, microseconds: float) -> None:
        self._exposure_us            = microseconds
        self._cfg["exposure_us"]     = microseconds
        log.debug("[SIM] ExposureTime = %.0f µs", microseconds)

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
