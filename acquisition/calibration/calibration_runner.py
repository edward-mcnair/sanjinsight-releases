"""
acquisition/calibration_runner.py

CalibrationRunner orchestrates the full calibration sequence:
    1. Step TEC through a list of target temperatures
    2. Wait for temperature to stabilise at each step
    3. Capture N averaged frames
    4. Hand the (temperature, frame) pairs to Calibration.fit()

The runner runs in a background thread and emits progress via callbacks,
following the same on_progress / on_complete pattern used everywhere else.

Usage:
    runner = CalibrationRunner(camera, tec_list, config)
    runner.on_progress = my_callback    # optional
    runner.on_complete = my_callback    # optional
    threading.Thread(target=runner.run, daemon=True).start()
"""

from __future__ import annotations
import time
import threading
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Callable

from .calibration import Calibration, CalibrationResult


@dataclass
class CalibrationProgress:
    step:         int   = 0
    total_steps:  int   = 0
    temperature:  float = 0.0
    actual_temp:  float = 0.0
    state:        str   = "idle"   # idle | moving | settling | capturing | fitting | complete | error | aborted
    message:      str   = ""
    result:       Optional[CalibrationResult] = None


class CalibrationRunner:
    """
    Drives the TEC through a temperature sequence and builds
    the C_T calibration map.
    """

    def __init__(self, camera, tecs: list, cfg: dict):
        """
        camera  — CameraDriver (must be open and streaming)
        tecs    — list of TecDriver instances (first one is used for
                  temperature control; all are read for stability check)
        cfg     — calibration config dict (from config.yaml or UI)
        """
        self._cam    = camera
        self._tecs   = tecs
        self._cfg    = cfg
        self._abort  = False

        self.on_progress: Optional[Callable[[CalibrationProgress], None]] = None
        self.on_complete: Optional[Callable[[CalibrationResult],   None]] = None

    def abort(self):
        self._abort = True

    def run(self) -> CalibrationResult:
        """
        Run the full calibration sequence. Blocks until complete.
        Returns CalibrationResult (valid=False on error/abort).
        """
        temps       = self._cfg.get("temperatures", [25.0, 30.0, 35.0, 40.0])
        n_avg       = self._cfg.get("n_avg",       20)
        settle_s    = self._cfg.get("settle_s",    30.0)
        stable_tol  = self._cfg.get("stable_tol",   0.2)  # °C
        stable_dur  = self._cfg.get("stable_dur",   5.0)  # s
        min_intens  = self._cfg.get("min_intensity",10.0)
        min_r2      = self._cfg.get("min_r2",        0.80)

        cal = Calibration()
        n   = len(temps)

        def emit(step, T, actual, state, msg, result=None):
            if self.on_progress:
                try:
                    self.on_progress(CalibrationProgress(
                        step=step, total_steps=n,
                        temperature=T, actual_temp=actual,
                        state=state, message=msg, result=result))
                except Exception:
                    pass

        for i, T_target in enumerate(temps):
            if self._abort:
                emit(i, T_target, 0, "aborted", "Aborted by user")
                return CalibrationResult(valid=False)

            # --- Set TEC setpoint ---
            if self._tecs:
                try:
                    self._tecs[0].set_target(T_target)
                    emit(i, T_target, 0, "moving",
                         f"Step {i+1}/{n}: moving to {T_target:.1f}°C…")
                except Exception as e:
                    emit(i, T_target, 0, "error",
                         f"TEC set_target failed: {e}")
                    return CalibrationResult(valid=False)

            # --- Wait for temperature to stabilise ---
            actual = T_target  # fallback if no TEC readback
            stable_since = None
            deadline = time.time() + settle_s

            while time.time() < deadline:
                if self._abort:
                    emit(i, T_target, actual, "aborted", "Aborted")
                    return CalibrationResult(valid=False)

                actual = self._read_temp()
                diff   = abs(actual - T_target)
                now    = time.time()

                if diff <= stable_tol:
                    if stable_since is None:
                        stable_since = now
                    elif now - stable_since >= stable_dur:
                        break   # stable for long enough
                else:
                    stable_since = None

                emit(i, T_target, actual, "settling",
                     f"Step {i+1}/{n}: {T_target:.1f}°C target  "
                     f"actual {actual:.2f}°C  Δ{diff:.2f}°C")
                time.sleep(0.5)

            # --- Capture frames ---
            emit(i, T_target, actual, "capturing",
                 f"Step {i+1}/{n}: capturing {n_avg} frames at {actual:.2f}°C…")

            avg_frame = self._capture_avg(n_avg)
            if avg_frame is None:
                emit(i, T_target, actual, "error", "Frame capture failed")
                return CalibrationResult(valid=False)

            cal.add_point(temperature=actual, frame=avg_frame)
            emit(i, T_target, actual, "capturing",
                 f"Step {i+1}/{n}: captured at {actual:.2f}°C  ✓")

        # --- Fit ---
        emit(n, temps[-1], actual, "fitting",
             f"Fitting C_T map from {n} temperature points…")

        try:
            result = cal.fit(min_intensity=min_intens, min_r2=min_r2)
        except Exception as e:
            emit(n, temps[-1], 0, "error", f"Fit failed: {e}")
            return CalibrationResult(valid=False)

        pct_valid = (result.mask.mean() * 100) if result.mask is not None else 0
        msg = (f"Calibration complete — "
               f"{result.n_points} points, "
               f"T {result.t_min:.1f}–{result.t_max:.1f}°C, "
               f"{pct_valid:.0f}% pixels valid")

        emit(n, temps[-1], actual, "complete", msg, result)

        if self.on_complete:
            try:
                self.on_complete(result)
            except Exception:
                pass

        return result

    def _read_temp(self) -> float:
        """Read current temperature from first TEC."""
        if not self._tecs:
            return 0.0
        try:
            status = self._tecs[0].get_status()
            return status.actual_temp if not status.error else 0.0
        except Exception:
            return 0.0

    def _capture_avg(self, n: int) -> Optional[np.ndarray]:
        """Capture N frames and return their float32 average."""
        if self._cam is None:
            return None
        acc       = None
        count     = 0
        max_tries = n * 5   # at most 5× retries total before giving up
        tries     = 0
        while count < n:
            if self._abort:
                return None
            if tries >= max_tries:
                break
            tries += 1
            frame = self._cam.grab(timeout_ms=2000)
            if frame is None:
                continue
            data = frame.data.astype(np.float64)
            acc  = data if acc is None else acc + data
            count += 1
        if acc is None or count == 0:
            return None
        return (acc / count).astype(np.float32)
