"""
hardware/bias/iv_sweep.py — IV sweep sequencer synchronized with image acquisition.

Drives a BiasDriver through a sequence of voltage or current setpoints,
capturing a thermoreflectance frame at each point. Supports:
  - Linear sweep: start → stop, N steps
  - Log sweep: geomspace(start, stop, N steps)
  - Pulsed: set bias → wait dwell → capture → return to quiescent

Based on Voltage-Current GPIB Automation3.vi from SanjVIEW.

Usage
-----
    cfg = IVSweepConfig(mode="voltage", start=0.0, stop=3.3, n_steps=20)
    sweeper = IVSweeper(bias_driver, camera_driver, pipeline)
    result = sweeper.run(cfg, on_progress=my_cb)
    sweeper.save_result(result, "/path/to/sweep")
"""

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional

import numpy as np

log = logging.getLogger(__name__)

from hardware.bias.base import BiasDriver


# ─────────────────────────────────────────────────────────────────────────── #
#  Configuration                                                               #
# ─────────────────────────────────────────────────────────────────────────── #


@dataclass
class IVSweepConfig:
    """
    Configuration for one IV sweep run.

    Attributes
    ----------
    mode              : "voltage" — voltage-source sweep (compliance = current limit)
                        "current" — current-source sweep (compliance = voltage limit)
    sweep_type        : "linear"  — np.linspace(start, stop, n_steps)
                        "log"     — np.geomspace(start, stop, n_steps)
                                    Note: start and stop must have the same sign
                                    and be non-zero for log sweep.
    start             : First setpoint value (V or A)
    stop              : Last setpoint value (V or A)
    n_steps           : Number of setpoints (inclusive of start and stop)
    dwell_ms          : Time (ms) to wait at each setpoint before capturing
    quiescent_level   : Level applied between captures when return_to_quiescent
                        is True.  Typically 0.0 V for voltage sweeps.
    compliance        : Current limit (A) in voltage mode, or voltage limit (V)
                        in current mode.  Applied once before sweep starts.
    return_to_quiescent: If True, return to quiescent_level between each step
                         (pulsed mode — minimises DUT self-heating).
    """
    mode:                str   = "voltage"
    sweep_type:          str   = "linear"
    start:               float = 0.0
    stop:                float = 3.3
    n_steps:             int   = 20
    dwell_ms:            float = 500.0
    quiescent_level:     float = 0.0
    compliance:          float = 0.1
    return_to_quiescent: bool  = True

    # ── Derived setpoints ─────────────────────────────────────────────────── #

    def setpoints(self) -> List[float]:
        """
        Compute and return the ordered list of bias setpoints.

        For log sweeps: both start and stop must be positive (or both negative).
        A ValueError is raised if this constraint is violated.
        """
        if self.sweep_type == "log":
            if self.start <= 0 or self.stop <= 0:
                raise ValueError(
                    "Log sweep requires start > 0 and stop > 0.  "
                    f"Got start={self.start}, stop={self.stop}.  "
                    "Use a linear sweep for zero-crossing ranges, or "
                    "offset the start/stop values.")
            pts = np.geomspace(self.start, self.stop, max(2, self.n_steps))
        else:
            pts = np.linspace(self.start, self.stop, max(2, self.n_steps))

        return [float(v) for v in pts]


# ─────────────────────────────────────────────────────────────────────────── #
#  Result                                                                      #
# ─────────────────────────────────────────────────────────────────────────── #


@dataclass
class IVSweepResult:
    """
    Data collected during one IV sweep run.

    Attributes
    ----------
    setpoints   : Commanded bias values (V or A)
    measured_v  : Measured voltage at each setpoint (V)
    measured_i  : Measured current at each setpoint (A)
    frames      : ΔR/R frame (float32) captured at each setpoint, or None
                  if no camera/pipeline was connected.
    timestamp   : ISO-8601 string at sweep start
    config      : The IVSweepConfig used for this run
    aborted     : True if the sweep was cancelled before completion
    """
    setpoints:  List[float]
    measured_v: List[float]
    measured_i: List[float]
    frames:     Optional[List[np.ndarray]]
    timestamp:  str
    config:     IVSweepConfig
    aborted:    bool = False

    # ── Convenience accessors ─────────────────────────────────────────────── #

    def resistance(self) -> List[float]:
        """
        Per-setpoint apparent resistance R = V/I.
        Returns NaN where I == 0 to avoid ZeroDivisionError.
        """
        out = []
        for v, i in zip(self.measured_v, self.measured_i):
            out.append(v / i if abs(i) > 1e-15 else float("nan"))
        return out

    def power(self) -> List[float]:
        """Per-setpoint dissipated power P = V × I (W)."""
        return [abs(v * i) for v, i in zip(self.measured_v, self.measured_i)]

    # ── DataFrame export ──────────────────────────────────────────────────── #

    def as_dataframe(self):
        """
        Return a pandas DataFrame with columns:
            setpoint, voltage, current, resistance, power

        Falls back to a plain dict if pandas is not installed.
        """
        data = {
            "setpoint":   self.setpoints,
            "voltage":    self.measured_v,
            "current":    self.measured_i,
            "resistance": self.resistance(),
            "power":      self.power(),
        }
        try:
            import pandas as pd
            return pd.DataFrame(data)
        except ImportError:
            return data

    # ── Metadata dict (for JSON sidecar) ─────────────────────────────────── #

    def metadata_dict(self) -> dict:
        """
        Return a JSON-serialisable metadata dict (excludes frame arrays —
        those go into the .npz archive).
        """
        cfg = asdict(self.config)
        return {
            "timestamp":   self.timestamp,
            "aborted":     self.aborted,
            "n_setpoints": len(self.setpoints),
            "n_frames":    len(self.frames) if self.frames is not None else 0,
            "config":      cfg,
            "setpoints":   self.setpoints,
            "measured_v":  self.measured_v,
            "measured_i":  self.measured_i,
            "resistance":  self.resistance(),
            "power":       self.power(),
        }


# ─────────────────────────────────────────────────────────────────────────── #
#  Sweeper                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #


class IVSweeper:
    """
    Runs an IV sweep — sets bias, waits dwell, reads back V+I, captures frame.

    The sweeper is intentionally synchronous (runs in the calling thread).
    Callers that need a non-blocking sweep should wrap in QThread or
    threading.Thread.

    Parameters
    ----------
    bias_driver    : Connected BiasDriver instance.
    camera_driver  : Camera driver with a .grab(timeout_ms) method; may be None.
    pipeline       : Acquisition pipeline providing background subtraction /
                     ΔR/R computation; may be None.  When provided its
                     .get_drr_frame() method is called after the camera grab.
    """

    def __init__(self,
                 bias_driver:   BiasDriver,
                 camera_driver=None,
                 pipeline=None):
        self._bias    = bias_driver
        self._cam     = camera_driver
        self._pipe    = pipeline
        self._abort_flag = threading.Event()

    # ── Control ───────────────────────────────────────────────────────────── #

    def abort(self) -> None:
        """
        Request an early stop.  Thread-safe.  The running sweep will
        complete the current step, return to quiescent, then return with
        IVSweepResult.aborted == True.
        """
        self._abort_flag.set()

    # ── Main sweep ────────────────────────────────────────────────────────── #

    def run(self,
            config: IVSweepConfig,
            on_progress: Optional[Callable] = None,
            on_frame:    Optional[Callable] = None,
            ) -> IVSweepResult:
        """
        Execute the sweep defined by *config*.

        Parameters
        ----------
        config      : IVSweepConfig
        on_progress : callable(step, total, setpoint, measured_v, measured_i)
                      Called after each step completes (still in sweep thread).
        on_frame    : callable(step, frame_ndarray)
                      Called immediately after each frame capture.

        Returns
        -------
        IVSweepResult — always returned, even if aborted mid-sweep.
        """
        self._abort_flag.clear()

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        setpoints = config.setpoints()
        total     = len(setpoints)

        measured_v: List[float] = []
        measured_i: List[float] = []
        frames:     List[np.ndarray] = []

        dwell_s    = config.dwell_ms / 1000.0
        quiescent  = config.quiescent_level

        # ── Instrument setup ─────────────────────────────────────────────── #
        self._bias.set_mode(config.mode)
        self._bias.set_compliance(config.compliance)
        self._bias.set_level(quiescent)
        self._bias.enable()

        # Short settling pause after enabling output
        time.sleep(0.05)

        aborted = False

        try:
            for step_idx, setpoint in enumerate(setpoints):
                if self._abort_flag.is_set():
                    aborted = True
                    break

                # ── 1. Apply setpoint ────────────────────────────────────── #
                self._bias.set_level(setpoint)
                time.sleep(dwell_s)

                # ── 2. Read back V and I ─────────────────────────────────── #
                status = self._bias.get_status()
                v = status.actual_voltage if status.error is None else float("nan")
                i = status.actual_current if status.error is None else float("nan")

                measured_v.append(v)
                measured_i.append(i)

                # ── 3. Capture frame ─────────────────────────────────────── #
                frame = self._capture_frame()
                if frame is not None:
                    frames.append(frame)
                    if on_frame is not None:
                        try:
                            on_frame(step_idx, frame)
                        except Exception:
                            log.warning("IVSweeper: on_frame callback raised at "
                                        "step %d", step_idx, exc_info=True)

                # ── 4. Return to quiescent (pulsed mode) ─────────────────── #
                if config.return_to_quiescent and step_idx < total - 1:
                    self._bias.set_level(quiescent)
                    # Brief inter-step settling — keeps DUT cool between pulses
                    time.sleep(max(0.01, dwell_s * 0.25))

                # ── 5. Progress callback ──────────────────────────────────── #
                if on_progress is not None:
                    try:
                        on_progress(step_idx + 1, total, setpoint, v, i)
                    except Exception:
                        log.warning("IVSweeper: on_progress callback raised at "
                                    "step %d", step_idx, exc_info=True)

        finally:
            # Always return to quiescent and leave output on (caller decides
            # when to disable; leaving it on prevents output transients).
            try:
                self._bias.set_level(quiescent)
            except Exception:
                pass

        result = IVSweepResult(
            setpoints  = setpoints[:len(measured_v)],
            measured_v = measured_v,
            measured_i = measured_i,
            frames     = frames if frames else None,
            timestamp  = timestamp,
            config     = config,
            aborted    = aborted,
        )
        return result

    # ── Frame capture ─────────────────────────────────────────────────────── #

    def _capture_frame(self) -> Optional[np.ndarray]:
        """
        Grab one frame.  If a pipeline is attached return its ΔR/R output;
        otherwise return the raw camera frame as float32.
        Returns None if no camera is connected.
        """
        if self._cam is None:
            return None

        try:
            raw = self._cam.grab(timeout_ms=2000)
            if raw is None:
                return None

            data = raw.data if hasattr(raw, "data") else np.asarray(raw)

            if self._pipe is not None and hasattr(self._pipe, "get_drr_frame"):
                return self._pipe.get_drr_frame(data)

            return data.astype(np.float32)

        except Exception:
            log.warning("IVSweeper._capture_frame: frame capture failed",
                        exc_info=True)
            return None

    # ── Persistence ───────────────────────────────────────────────────────── #

    def save_result(self, result: IVSweepResult, path: str) -> str:
        """
        Save sweep result to disk.

        Creates two files:
            <path>.npz   — compressed numpy archive of frame stack and 1-D arrays
            <path>.json  — human-readable metadata, setpoints, V/I readings

        path: base path without extension.
        Returns: the .npz path actually written.
        """
        npz_path  = path if path.endswith(".npz") else path + ".npz"
        json_path = npz_path[:-4] + ".json"

        # ── Build numpy archive ───────────────────────────────────────────── #
        arrays: dict = {
            "setpoints":  np.array(result.setpoints,  dtype=np.float64),
            "measured_v": np.array(result.measured_v, dtype=np.float64),
            "measured_i": np.array(result.measured_i, dtype=np.float64),
        }
        if result.frames is not None and len(result.frames) > 0:
            # Stack frames along first axis → shape (N, H, W)
            try:
                arrays["frames"] = np.stack(result.frames, axis=0).astype(np.float32)
            except ValueError:
                # Frames may have mismatched shapes if sweep was aborted mid-way
                for k, fr in enumerate(result.frames):
                    arrays[f"frame_{k:04d}"] = fr.astype(np.float32)

        np.savez_compressed(npz_path, **arrays)

        # ── Write JSON sidecar ────────────────────────────────────────────── #
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(result.metadata_dict(), fh, indent=2)

        return npz_path

    @staticmethod
    def load_result(path: str) -> IVSweepResult:
        """
        Load a previously saved IVSweepResult from <path>.npz + <path>.json.

        path: base path without extension, or the .npz path directly.
        Raises FileNotFoundError / KeyError on missing files or corrupt data.
        """
        npz_path  = path if path.endswith(".npz") else path + ".npz"
        json_path = npz_path[:-4] + ".json"

        archive = np.load(npz_path, allow_pickle=False)
        with open(json_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        # Reconstruct frames list (single stack or per-frame keys)
        frames: Optional[List[np.ndarray]] = None
        if "frames" in archive:
            stacked = archive["frames"]  # (N, H, W)
            frames  = [stacked[i] for i in range(stacked.shape[0])]
        else:
            frame_keys = sorted(k for k in archive.files
                                if k.startswith("frame_"))
            if frame_keys:
                frames = [archive[k] for k in frame_keys]

        cfg_dict = meta.get("config", {})
        config   = IVSweepConfig(
            mode                = str( cfg_dict.get("mode",                "voltage")),
            sweep_type          = str( cfg_dict.get("sweep_type",          "linear")),
            start               = float(cfg_dict.get("start",              0.0)),
            stop                = float(cfg_dict.get("stop",               3.3)),
            n_steps             = int(  cfg_dict.get("n_steps",            20)),
            dwell_ms            = float(cfg_dict.get("dwell_ms",           500.0)),
            quiescent_level     = float(cfg_dict.get("quiescent_level",    0.0)),
            compliance          = float(cfg_dict.get("compliance",         0.1)),
            return_to_quiescent = bool( cfg_dict.get("return_to_quiescent",True)),
        )

        return IVSweepResult(
            setpoints  = [float(v) for v in archive["setpoints"]],
            measured_v = [float(v) for v in archive["measured_v"]],
            measured_i = [float(v) for v in archive["measured_i"]],
            frames     = frames,
            timestamp  = str(meta.get("timestamp", "")),
            config     = config,
            aborted    = bool(meta.get("aborted", False)),
        )
