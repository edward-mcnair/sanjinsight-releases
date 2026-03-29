"""
hardware/tec/preconditioning.py

TEC thermal preconditioning — waits for all active TEC channels to
reach stable setpoint before proceeding with acquisition.

Designed to run on a background thread with progress callbacks for the UI.

Usage
-----
    from hardware.tec.preconditioning import TecPreconditioning

    precond = TecPreconditioning(tec_drivers)
    result = precond.run(progress_cb=my_callback)
    if result.stable:
        # all channels stable — safe to acquire
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class TecPreconditionResult:
    """Result of a TEC preconditioning wait."""
    stable:       bool           # all channels stable
    wait_time_s:  float          # total wall-clock wait
    channels:     list[dict] = field(default_factory=list)  # per-channel status
    timed_out:    bool  = False
    aborted:      bool  = False
    message:      str   = ""


class TecPreconditioning:
    """Wait for TEC channels to reach thermal stability.

    Parameters
    ----------
    tec_drivers : list
        List of TecDriver instances.  Empty list → immediate success.
    tolerance_c : float
        Acceptable |actual − target| in °C.
    dwell_s : float
        Seconds continuously in-band before declaring stable.
    timeout_s : float
        Maximum wait time before giving up.
    poll_interval_s : float
        How often to poll TEC status.
    """

    def __init__(
        self,
        tec_drivers: list,
        tolerance_c: float = 0.20,
        dwell_s: float = 30.0,
        timeout_s: float = 300.0,
        poll_interval_s: float = 1.0,
    ):
        self._drivers = tec_drivers
        self._tolerance = tolerance_c
        self._dwell = dwell_s
        self._timeout = timeout_s
        self._poll = poll_interval_s
        self._abort = False

    def abort(self) -> None:
        """Request abort (thread-safe)."""
        self._abort = True

    def run(self, progress_cb=None) -> TecPreconditionResult:
        """Block until all enabled TEC channels are stable or timeout.

        Parameters
        ----------
        progress_cb : callable, optional
            Called at each poll with (elapsed_s, channel_deltas, channel_in_band_s).
        """
        if not self._drivers:
            return TecPreconditionResult(
                stable=True, wait_time_s=0.0,
                message="No TEC channels — skipping preconditioning")

        self._abort = False
        t0 = time.monotonic()

        # Per-channel in-band tracking
        n = len(self._drivers)
        in_band_since: list[Optional[float]] = [None] * n

        while True:
            elapsed = time.monotonic() - t0

            if self._abort:
                return TecPreconditionResult(
                    stable=False, wait_time_s=elapsed,
                    aborted=True, message="Preconditioning aborted by user")

            if elapsed > self._timeout:
                ch_info = self._channel_info(in_band_since, elapsed)
                return TecPreconditionResult(
                    stable=False, wait_time_s=elapsed,
                    channels=ch_info, timed_out=True,
                    message=f"TEC preconditioning timed out after "
                            f"{elapsed:.0f}s")

            # Poll each channel
            all_stable = True
            deltas = []
            band_times = []

            for i, drv in enumerate(self._drivers):
                try:
                    status = drv.get_status()
                except Exception:
                    in_band_since[i] = None
                    all_stable = False
                    deltas.append(None)
                    band_times.append(0.0)
                    continue

                if not status.enabled or status.error:
                    # Disabled/errored channels don't block
                    deltas.append(None)
                    band_times.append(0.0)
                    continue

                delta = abs(status.actual_temp - status.target_temp)
                deltas.append(delta)
                in_band = delta <= self._tolerance

                now = time.monotonic()
                if in_band:
                    if in_band_since[i] is None:
                        in_band_since[i] = now
                    bt = now - in_band_since[i]
                else:
                    in_band_since[i] = None
                    bt = 0.0

                band_times.append(bt)
                if bt < self._dwell:
                    all_stable = False

            if progress_cb:
                try:
                    progress_cb(elapsed, deltas, band_times)
                except Exception:
                    pass

            if all_stable:
                ch_info = self._channel_info(in_band_since, time.monotonic() - t0)
                return TecPreconditionResult(
                    stable=True, wait_time_s=time.monotonic() - t0,
                    channels=ch_info,
                    message=f"All TEC channels stable after "
                            f"{time.monotonic() - t0:.0f}s")

            time.sleep(self._poll)

    def _channel_info(self, in_band_since, elapsed):
        """Build per-channel status dicts."""
        info = []
        for i, drv in enumerate(self._drivers):
            try:
                s = drv.get_status()
                info.append({
                    "index": i,
                    "actual_c": s.actual_temp,
                    "target_c": s.target_temp,
                    "delta_c": abs(s.actual_temp - s.target_temp),
                    "enabled": s.enabled,
                    "stable": (in_band_since[i] is not None
                               and (time.monotonic() - in_band_since[i])
                               >= self._dwell),
                })
            except Exception:
                info.append({"index": i, "error": True})
        return info
