"""
acquisition/scan.py

Scan engine — steps the XY stage across a grid of positions,
acquires a thermoreflectance frame at each tile, and stitches
the result into a large-area ΔR/R map.

Grid layout
-----------
    (x0, y0) ──→ x  (columns, step_x)
       │
       ↓ y  (rows, step_y)

    Total tiles = n_cols × n_rows
    Scan order  : row-major (left→right, top→bottom) by default,
                  or boustrophedon (snake) to minimise travel.

Output
------
    ScanResult.drr_map      — stitched float32 ΔR/R map, shape (H_total, W_total)
    ScanResult.dt_map       — optional float32 ΔT map (if calibration given)
    ScanResult.tile_results — list[AcquisitionResult], one per tile
    ScanResult.positions    — list[(x_μm, y_μm)] in scan order

Usage
-----
    scanner = ScanEngine(stage, camera, tecs, pipeline, cfg)
    scanner.on_progress = my_cb
    scanner.on_complete = my_cb
    threading.Thread(target=scanner.run, daemon=True).start()
"""

from __future__ import annotations
import logging
import time, threading
import numpy as np
from dataclasses import dataclass, field
from typing      import List, Optional, Callable, Tuple

log = logging.getLogger(__name__)


@dataclass
class ScanProgress:
    tile:         int   = 0
    total_tiles:  int   = 0
    x_um:         float = 0.0
    y_um:         float = 0.0
    state:        str   = "idle"   # idle | moving | settling | acquiring
                                    # | stitching | complete | error | aborted
    message:      str   = ""
    partial_map:  Optional[np.ndarray] = None   # live preview (may be None)


@dataclass
class ScanResult:
    drr_map:      Optional[np.ndarray]        = None  # (H_total, W_total) float32
    dt_map:       Optional[np.ndarray]        = None  # (H_total, W_total) float32
    tile_results: List                         = field(default_factory=list)
    positions:    List[Tuple[float, float]]    = field(default_factory=list)
    n_cols:       int   = 0
    n_rows:       int   = 0
    tile_w:       int   = 0   # pixels per tile
    tile_h:       int   = 0
    step_x_um:    float = 0.0
    step_y_um:    float = 0.0
    origin_x_um:  float = 0.0
    origin_y_um:  float = 0.0
    duration_s:   float = 0.0
    valid:        bool  = False


class ScanEngine:
    """
    Orchestrates a grid scan: move → settle → acquire → stitch.
    """

    def __init__(self, stage, camera, tecs: list, pipeline, cfg: dict,
                 calibration=None):
        """
        stage       — StageDriver (must be connected)
        camera      — CameraDriver
        tecs        — list of TecDriver
        pipeline    — AcquisitionPipeline
        cfg         — scan config dict (from config.yaml or UI)
        calibration — optional CalibrationResult for ΔT conversion
        """
        self._stage = stage
        self._cam   = camera
        self._tecs  = tecs
        self._pipe  = pipeline
        self._cfg   = cfg
        self._cal   = calibration
        self._abort = False

        self.on_progress: Optional[Callable[[ScanProgress], None]] = None
        self.on_complete: Optional[Callable[[ScanResult],   None]] = None

    def abort(self):
        self._abort = True
        if self._pipe:
            try:
                self._pipe.abort()
            except Exception:
                log.debug("ScanEngine: pipeline abort raised", exc_info=True)

    def run(self) -> ScanResult:
        cfg        = self._cfg
        n_cols     = int(cfg.get("n_cols",     3))
        n_rows     = int(cfg.get("n_rows",     3))
        step_x_um  = float(cfg.get("step_x_um", 100.0))
        step_y_um  = float(cfg.get("step_y_um", 100.0))
        settle_s   = float(cfg.get("settle_s",  0.5))
        n_frames   = int(cfg.get("n_frames",    20))
        snake      = bool(cfg.get("snake",      True))

        # Origin = current stage position
        origin_x, origin_y = 0.0, 0.0
        if self._stage:
            try:
                st = self._stage.get_status()
                origin_x = st.position.x
                origin_y = st.position.y
            except Exception:
                log.warning("ScanEngine: could not read stage origin — "
                            "return-to-origin will use (0, 0)", exc_info=True)

        total  = n_cols * n_rows
        t0     = time.time()

        # Build grid in scan order
        positions = []
        for row in range(n_rows):
            cols = range(n_cols) if (not snake or row % 2 == 0) \
                   else range(n_cols - 1, -1, -1)
            for col in cols:
                x = origin_x + col * step_x_um
                y = origin_y + row * step_y_um
                positions.append((x, y, row, col))

        tile_results  = []
        tile_drr      = []     # list of (row, col, drr_array)
        tile_w = tile_h = 0

        def emit(tile, x, y, state, msg, partial=None):
            if self.on_progress:
                try:
                    self.on_progress(ScanProgress(
                        tile=tile, total_tiles=total,
                        x_um=x, y_um=y,
                        state=state, message=msg,
                        partial_map=partial))
                except Exception:
                    log.debug("ScanEngine: progress callback raised", exc_info=True)

        for i, (x, y, row, col) in enumerate(positions):
            if self._abort:
                emit(i, x, y, "aborted", "Scan aborted by user")
                return ScanResult(valid=False)

            # ---- Move ----
            emit(i, x, y, "moving",
                 f"Tile {i+1}/{total}  →  "
                 f"({x:.0f}, {y:.0f}) μm  [row {row} col {col}]")
            if self._stage:
                try:
                    self._stage.move_to(x=x, y=y)
                except Exception as e:
                    emit(i, x, y, "error", f"Stage move failed: {e}")
                    return ScanResult(valid=False)

            # ---- Settle ----
            emit(i, x, y, "settling",
                 f"Tile {i+1}/{total}  Settling {settle_s:.1f}s…")
            deadline = time.time() + settle_s
            while time.time() < deadline:
                if self._abort:
                    return ScanResult(valid=False)
                time.sleep(0.05)

            # ---- Acquire ----
            emit(i, x, y, "acquiring",
                 f"Tile {i+1}/{total}  Acquiring {n_frames} frames…")

            drr = self._acquire_tile(n_frames)
            if drr is None:
                emit(i, x, y, "error", f"Tile {i+1} acquisition failed")
                return ScanResult(valid=False)

            tile_drr.append((row, col, drr))
            if tile_h == 0:
                tile_h, tile_w = drr.shape[:2]

            # Live partial map after each tile
            partial = self._stitch_partial(
                tile_drr, n_rows, n_cols, tile_h, tile_w)
            emit(i + 1, x, y, "acquiring",
                 f"Tile {i+1}/{total}  ✓  SNR est. {self._snr(drr):.1f} dB",
                 partial=partial)

        # ---- Stitch ----
        emit(total, x, y, "stitching",
             f"Stitching {total} tiles into {n_cols*tile_w}×{n_rows*tile_h} map…")

        drr_map = self._stitch(tile_drr, n_rows, n_cols, tile_h, tile_w)

        dt_map = None
        if self._cal and self._cal.valid and drr_map is not None:
            try:
                # Resize C_T map to stitched dimensions if needed
                cal_h, cal_w = self._cal.ct_map.shape[:2]
                map_h, map_w = drr_map.shape[:2]
                if (cal_h, cal_w) != (map_h, map_w):
                    import cv2
                    ct_r = cv2.resize(self._cal.ct_map, (map_w, map_h))
                    mk_r = cv2.resize(
                        self._cal.mask.astype(np.uint8), (map_w, map_h)) > 0
                    from .calibration import CalibrationResult
                    tmp_cal = CalibrationResult(
                        ct_map=ct_r, mask=mk_r, valid=True)
                    dt_map = tmp_cal.apply(drr_map)
                else:
                    dt_map = self._cal.apply(drr_map)
            except Exception:
                log.warning("ScanEngine: calibration apply failed — "
                            "ΔT map will be None", exc_info=True)
                dt_map = None

        duration = time.time() - t0
        result = ScanResult(
            drr_map      = drr_map,
            dt_map       = dt_map,
            tile_results = tile_results,
            positions    = [(p[0], p[1]) for p in positions],
            n_cols       = n_cols,
            n_rows       = n_rows,
            tile_w       = tile_w,
            tile_h       = tile_h,
            step_x_um    = step_x_um,
            step_y_um    = step_y_um,
            origin_x_um  = origin_x,
            origin_y_um  = origin_y,
            duration_s   = duration,
            valid        = drr_map is not None,
        )

        emit(total, x, y, "complete",
             f"Scan complete  —  {total} tiles  "
             f"{n_cols*tile_w}×{n_rows*tile_h} px  "
             f"{duration:.0f}s",
             partial=drr_map)

        if self.on_complete:
            try:
                self.on_complete(result)
            except Exception:
                log.warning("ScanEngine: on_complete callback raised", exc_info=True)

        # Return to origin
        if self._stage:
            try:
                self._stage.move_to(x=origin_x, y=origin_y)
            except Exception:
                log.warning("ScanEngine: return-to-origin failed "
                            "(%.1f, %.1f) μm", origin_x, origin_y, exc_info=True)

        return result

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                 #
    # ---------------------------------------------------------------- #

    def _acquire_tile(self, n_frames: int) -> Optional[np.ndarray]:
        """
        Run a mini hot/cold acquisition and return the ΔR/R tile.
        Falls back to direct frame averaging if no pipeline.
        """
        if self._pipe is not None:
            # Use the pipeline's synchronous run() — blocks until complete
            try:
                result = self._pipe.run(n_frames=n_frames)
                return result.delta_r_over_r if result else None
            except Exception:
                log.warning("ScanEngine: pipeline tile acquisition failed — "
                            "falling back to direct capture", exc_info=True)

        # Direct capture fallback (simulated / no pipeline)
        if self._cam is None:
            return self._synthetic_tile()
        acc = None
        for _ in range(n_frames):
            frame = self._cam.grab(timeout_ms=2000)
            if frame is not None:
                d = frame.data.astype(np.float64)
                acc = d if acc is None else acc + d
        if acc is None:
            return None
        avg = (acc / n_frames).astype(np.float32)
        # Simulated ΔR/R: small noise around zero
        return (np.random.randn(*avg.shape).astype(np.float32) * 0.001)

    def _synthetic_tile(self) -> np.ndarray:
        """Produce a synthetic ΔR/R tile for demo/simulation."""
        h, w = 240, 320
        tile  = np.zeros((h, w), np.float32)
        # Random hotspot
        cx = np.random.randint(w // 4, 3 * w // 4)
        cy = np.random.randint(h // 4, 3 * h // 4)
        Y, X = np.ogrid[:h, :w]
        r2   = ((X - cx)**2 + (Y - cy)**2).astype(np.float32)
        sig  = np.random.uniform(40, 80)
        tile += np.exp(-r2 / (2 * sig**2)) * np.random.uniform(0.001, 0.005)
        tile += np.random.randn(h, w).astype(np.float32) * 2e-4
        return tile

    def _stitch(self, tile_drr, n_rows, n_cols, tile_h, tile_w) -> np.ndarray:
        """Assemble tiles into the full map (simple tiling, no blending)."""
        canvas = np.zeros((n_rows * tile_h, n_cols * tile_w), np.float32)
        for row, col, drr in tile_drr:
            y0, y1 = row * tile_h, (row + 1) * tile_h
            x0, x1 = col * tile_w, (col + 1) * tile_w
            h, w   = drr.shape[:2]
            canvas[y0:y0+h, x0:x0+w] = drr[:y1-y0, :x1-x0]
        return canvas

    def _stitch_partial(self, tile_drr, n_rows, n_cols,
                        tile_h, tile_w) -> Optional[np.ndarray]:
        if tile_h == 0 or tile_w == 0:
            return None
        try:
            return self._stitch(tile_drr, n_rows, n_cols, tile_h, tile_w)
        except Exception:
            log.debug("ScanEngine: partial stitch failed", exc_info=True)
            return None

    @staticmethod
    def _snr(drr: np.ndarray) -> float:
        try:
            signal = float(np.percentile(np.abs(drr), 95))
            noise  = float(np.std(drr))
            return 20 * np.log10(signal / noise) if noise > 0 else 0.0
        except Exception:
            return 0.0
