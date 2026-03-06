"""
ai/metrics_service.py

MetricsService — deterministic real-time quality metrics for SanjINSIGHT.

Subscribes to HardwareService signals and continuously computes:

  Camera
    saturation_pct    — % pixels at or near the sensor's full-scale value
    underexposure_pct — % pixels at or near black
    drift_score       — normalised mean-absolute inter-frame difference
    focus_score       — variance of Laplacian (higher = sharper)

  TEC (per channel)
    delta_c           — |actual − target| temperature error
    time_in_band_s    — seconds continuously within ±tolerance of setpoint
    stable            — True once in-band for >= TEC_DWELL_S seconds

  FPGA
    running, sync_locked

  Stage
    homed, moving

Emits
------
metrics_updated(dict)     Throttled snapshot at EMIT_RATE_HZ; always contains
                          keys: camera, tec, fpga, stage, issues, ready.
issue_detected(str, str)  Fires once when an issue first becomes active:
                          (issue_code, human_readable_message).
issue_cleared(str)        Fires once when an issue is resolved: (issue_code,).

No AI or LLM is involved — all logic is deterministic threshold comparisons.
The metrics dict is the foundation that a future LLM layer will use as its
grounded context snapshot.

Thread-safety
-------------
HardwareService emits signals from background threads; Qt routes them to the
main thread via queued connections.  All MetricsService slots therefore run on
the main thread — no locking is required.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Set

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


# ── Issue codes ────────────────────────────────────────────────────────────

CAM_DISCONNECTED   = "camera_disconnected"
CAM_SATURATED      = "camera_saturated"
CAM_UNDEREXPOSED   = "camera_underexposed"
HIGH_DRIFT         = "high_drift"
POOR_FOCUS         = "poor_focus"
TEC_NOT_STABLE     = "tec_not_stable"    # suffixed with _{idx} per channel
FPGA_NOT_RUNNING   = "fpga_not_running"
FPGA_NOT_LOCKED    = "fpga_not_locked"
STAGE_NOT_HOMED    = "stage_not_homed"


class MetricsService(QObject):
    """
    Real-time instrument quality and readiness monitor.

    Instantiate once and pass the live HardwareService.  Connect
    metrics_updated to any widget that needs to display status.

    Parameters
    ----------
    hw_service:
        The live HardwareService instance whose signals this service
        subscribes to.  Must be a QObject that emits camera_frame,
        tec_status, fpga_status, stage_status, and device_connected.
    parent:
        Optional Qt parent.
    """

    # ── Public signals ─────────────────────────────────────────────────────
    metrics_updated = pyqtSignal(dict)    # throttled snapshot
    issue_detected  = pyqtSignal(str, str)  # (code, human message) — rising edge
    issue_cleared   = pyqtSignal(str)       # (code)                — falling edge

    # ── Thresholds (class-level; override on instance for testing) ─────────
    SAT_THRESHOLD_PCT   = 2.0    # % pixels >= 98 % of max_val → warning
    UNDER_THRESHOLD_PCT = 40.0   # % pixels <= 1.5 % of max_val → warning
    DRIFT_THRESHOLD     = 0.03   # normalised mean-abs inter-frame diff
    FOCUS_THRESHOLD     = 80.0   # Laplacian variance; below this → warning
    TEC_TOLERANCE_C     = 0.20   # ±°C band considered "in setpoint"
    TEC_DWELL_S         = 30.0   # seconds in-band before stable=True
    EMIT_RATE_HZ        = 4.0    # max metrics_updated emissions / second

    def __init__(self, hw_service, parent=None):
        super().__init__(parent)

        # ── Camera state ──────────────────────────────────────────────
        self._cam_connected                   = False
        self._prev_frame: np.ndarray | None   = None
        self._cam_metrics: dict               = {}
        self._last_frame_time: float          = 0.0

        # ── TEC state — list indexed by channel ───────────────────────
        # Each entry: {"in_band_since": float|None, "last_status": TecStatus|None}
        self._tec_state: list[dict] = []

        # ── FPGA / stage state ────────────────────────────────────────
        self._fpga_metrics: dict  = {}
        self._stage_metrics: dict = {}

        # ── Issue tracking ────────────────────────────────────────────
        self._active_issues: Set[str]         = set()
        self._issue_messages: Dict[str, str]  = {}

        # ── Frame-processing throttle ─────────────────────────────────
        # The camera emits up to 30 fps; computing saturation, drift, and
        # focus on every frame at 30 Hz saturates the GUI thread on Windows.
        # We only need metrics at EMIT_RATE_HZ (4 Hz), so skip frames that
        # arrive before the next processing window opens.
        self._last_proc_t: float = 0.0

        # ── Emit throttle ─────────────────────────────────────────────
        self._last_emit_t: float = 0.0

        # ── Wire up ───────────────────────────────────────────────────
        hw_service.camera_frame.connect(self._on_camera_frame)
        hw_service.tec_status.connect(self._on_tec_status)
        hw_service.fpga_status.connect(self._on_fpga_status)
        hw_service.stage_status.connect(self._on_stage_status)
        hw_service.device_connected.connect(self._on_device_connected)

    # ================================================================ #
    #  Signal handlers — all run on the Qt main thread                 #
    # ================================================================ #

    def _on_device_connected(self, key: str, ok: bool) -> None:
        if key == "camera":
            self._cam_connected = ok
            if ok:
                self._clear_issue(CAM_DISCONNECTED)
            else:
                self._cam_metrics = {}
                self._prev_frame  = None
                self._set_issue(CAM_DISCONNECTED, "Camera not connected")
        self._maybe_emit()

    def _on_camera_frame(self, frame) -> None:
        self._cam_connected = True
        self._clear_issue(CAM_DISCONNECTED)

        # Skip expensive NumPy work (saturation, drift, focus) unless the
        # processing window has elapsed OR there are active issues that need
        # a chance to clear.  The camera fires at up to 30 fps; when the
        # instrument is healthy we only need 4 Hz — saving ~26 full-frame
        # reductions per second on the GUI thread.  When an issue is already
        # flagged we skip the gate so the next normal frame clears it promptly
        # (rather than waiting up to 250 ms for the window to reopen).
        now = time.monotonic()
        if (now - self._last_proc_t < (1.0 / self.EMIT_RATE_HZ)
                and not self._active_issues):
            return
        self._last_proc_t = now

        data = frame.data.astype(np.float32)
        h, w = data.shape[:2]

        # Bit depth: read from the live camera driver once per frame.
        # Falls back to 12-bit if camera info is unavailable.
        bit_depth = self._get_bit_depth()
        max_val   = float(2 ** bit_depth - 1)

        # ── Saturation & underexposure ─────────────────────────────────
        sat_thresh   = max_val * 0.98
        under_thresh = max_val * 0.015   # ≈60 counts at 12-bit
        n_pixels     = h * w

        sat_pct   = float(np.count_nonzero(data >= sat_thresh))   / n_pixels * 100.0
        under_pct = float(np.count_nonzero(data <= under_thresh)) / n_pixels * 100.0

        # ── Inter-frame drift ─────────────────────────────────────────
        drift = 0.0
        if self._prev_frame is not None and self._prev_frame.shape == data.shape:
            drift = float(np.abs(data - self._prev_frame).mean()) / max_val
        self._prev_frame = data

        # ── Focus quality (Laplacian variance on 4× downsampled frame) ─
        focus = self._compute_focus(data)

        self._cam_metrics = {
            "connected":         True,
            "saturation_pct":    round(sat_pct,   2),
            "underexposure_pct": round(under_pct, 2),
            "drift_score":       round(drift,     4),
            "focus_score":       round(focus,     1),
            "max_pixel":         int(data.max()),   # peak value for C3 pixel-headroom rule
        }

        # ── Update issues ─────────────────────────────────────────────
        self._set_or_clear(
            CAM_SATURATED, sat_pct > self.SAT_THRESHOLD_PCT,
            f"Camera: {sat_pct:.1f}% saturated pixels "
            f"(threshold {self.SAT_THRESHOLD_PCT}%)")
        self._set_or_clear(
            CAM_UNDEREXPOSED, under_pct > self.UNDER_THRESHOLD_PCT,
            f"Camera: {under_pct:.1f}% underexposed pixels "
            f"(threshold {self.UNDER_THRESHOLD_PCT}%)")
        self._set_or_clear(
            HIGH_DRIFT, drift > self.DRIFT_THRESHOLD,
            f"High frame drift detected "
            f"(score {drift:.3f}, threshold {self.DRIFT_THRESHOLD})")
        self._set_or_clear(
            POOR_FOCUS, focus < self.FOCUS_THRESHOLD,
            f"Poor focus: score {focus:.0f} "
            f"(threshold {self.FOCUS_THRESHOLD:.0f})")

        self._maybe_emit()

    def _on_tec_status(self, idx: int, status) -> None:
        # Grow the per-channel list on first sight of each index.
        while len(self._tec_state) <= idx:
            self._tec_state.append({"in_band_since": None, "last_status": None})

        state = self._tec_state[idx]
        state["last_status"] = status

        code = f"{TEC_NOT_STABLE}_{idx}"

        if status.error or not status.enabled:
            # No active TEC → reset in-band timer, don't flag as an issue
            state["in_band_since"] = None
            self._clear_issue(code)
            self._maybe_emit()
            return

        delta   = abs(status.actual_temp - status.target_temp)
        in_band = delta <= self.TEC_TOLERANCE_C

        if in_band:
            if state["in_band_since"] is None:
                state["in_band_since"] = time.monotonic()
        else:
            state["in_band_since"] = None

        time_in_band = (
            time.monotonic() - state["in_band_since"]
            if state["in_band_since"] is not None else 0.0
        )
        is_stable = time_in_band >= self.TEC_DWELL_S

        self._set_or_clear(
            code, not is_stable,
            f"TEC {idx + 1}: Δ{delta:.2f}°C after {time_in_band:.0f}s "
            f"(need {self.TEC_DWELL_S:.0f}s within ±{self.TEC_TOLERANCE_C}°C)")

        self._maybe_emit()

    def _on_fpga_status(self, status) -> None:
        if status.error:
            self._fpga_metrics = {"connected": True, "running": False,
                                  "sync_locked": False}
            self._maybe_emit()
            return

        self._fpga_metrics = {
            "connected":   True,
            "running":     status.running,
            "sync_locked": status.sync_locked,
            "freq_hz":     status.freq_hz,
            "duty_cycle":  status.duty_cycle,
        }
        self._set_or_clear(
            FPGA_NOT_RUNNING, not status.running,
            "FPGA modulation not running — stimulus output is off")
        self._set_or_clear(
            FPGA_NOT_LOCKED, not status.sync_locked,
            "FPGA sync not locked — modulation may be unstable")
        self._maybe_emit()

    def _on_stage_status(self, status) -> None:
        if status.error:
            self._stage_metrics = {"connected": True, "homed": False, "moving": False}
            self._maybe_emit()
            return

        self._stage_metrics = {
            "connected": True,
            "homed":     status.homed,
            "moving":    status.moving,
        }
        self._set_or_clear(
            STAGE_NOT_HOMED, not status.homed,
            "Stage not homed — absolute position accuracy not guaranteed")
        self._maybe_emit()

    # ================================================================ #
    #  Public helpers                                                   #
    # ================================================================ #

    @property
    def active_issue_codes(self) -> Set[str]:
        """Current set of active issue codes (read-only view)."""
        return frozenset(self._active_issues)

    def current_snapshot(self) -> dict:
        """Return the latest metrics snapshot without emitting a signal."""
        return self._build_snapshot()

    # ================================================================ #
    #  Internal helpers                                                 #
    # ================================================================ #

    def _maybe_emit(self) -> None:
        """Emit metrics_updated at most EMIT_RATE_HZ times per second."""
        now = time.monotonic()
        if now - self._last_emit_t < 1.0 / self.EMIT_RATE_HZ:
            return
        self._last_emit_t = now
        self.metrics_updated.emit(self._build_snapshot())

    def _build_snapshot(self) -> dict:
        """Assemble the full metrics dict from current state."""
        # TEC per-channel metrics
        tec_list = []
        for i, state in enumerate(self._tec_state):
            s = state["last_status"]
            if s is None:
                continue
            in_band_since = state["in_band_since"]
            time_in_band  = (
                time.monotonic() - in_band_since
                if in_band_since is not None else 0.0
            )
            delta     = abs(s.actual_temp - s.target_temp) if not s.error else 0.0
            is_stable = (time_in_band >= self.TEC_DWELL_S) and (not s.error) and s.enabled
            tec_list.append({
                "idx":            i,
                "connected":      True,
                "enabled":        s.enabled,
                "actual_c":       round(s.actual_temp, 3),
                "target_c":       round(s.target_temp, 3),
                "delta_c":        round(delta, 3),
                "time_in_band_s": round(time_in_band, 1),
                "stable":         is_stable,
                "error":          s.error,
            })

        # Active issues (sorted for deterministic output)
        issues = [
            {"code": code, "message": self._issue_messages.get(code, code)}
            for code in sorted(self._active_issues)
        ]

        # Overall readiness: any active issue → not ready
        ready = len(self._active_issues) == 0

        cam = dict(self._cam_metrics) if self._cam_metrics else {
            "connected": self._cam_connected
        }

        return {
            "camera": cam,
            "tec":    tec_list,
            "fpga":   dict(self._fpga_metrics),
            "stage":  dict(self._stage_metrics),
            "issues": issues,
            "ready":  ready,
        }

    def _set_or_clear(self, code: str, condition: bool, message: str) -> None:
        """Set or clear an issue based on *condition*."""
        if condition:
            self._set_issue(code, message)
        else:
            self._clear_issue(code)

    def _set_issue(self, code: str, message: str) -> None:
        """Activate an issue and emit issue_detected on the rising edge."""
        self._issue_messages[code] = message
        if code not in self._active_issues:
            self._active_issues.add(code)
            self.issue_detected.emit(code, message)
            log.debug("MetricsService: issue detected [%s] %s", code, message)

    def _clear_issue(self, code: str) -> None:
        """Deactivate an issue and emit issue_cleared on the falling edge."""
        if code in self._active_issues:
            self._active_issues.discard(code)
            self._issue_messages.pop(code, None)
            self.issue_cleared.emit(code)
            log.debug("MetricsService: issue cleared [%s]", code)

    @staticmethod
    def _compute_focus(data: np.ndarray) -> float:
        """
        Variance of the discrete Laplacian on a 4× downsampled frame.

        Higher values indicate sharper focus.  Uses second finite differences
        so no boundary padding is needed.  Fast even on 1920×1200 frames because
        the downsampled array is only 480×300.
        """
        ds = data[::4, ::4].astype(np.float32)
        if ds.shape[0] < 3 or ds.shape[1] < 3:
            return 0.0
        d2y = ds[2:, :]   - 2.0 * ds[1:-1, :] + ds[:-2, :]
        d2x = ds[:, 2:]   - 2.0 * ds[:, 1:-1] + ds[:, :-2]
        # Use the interior region common to both
        r = min(d2y.shape[0], d2x.shape[0])
        c = min(d2y.shape[1], d2x.shape[1])
        lap = d2y[:r, :c] + d2x[:r, :c]
        return float(np.var(lap))

    @staticmethod
    def _get_bit_depth() -> int:
        """Read bit depth from the live camera driver; default 12-bit."""
        try:
            from hardware.app_state import app_state
            cam = app_state.cam
            if cam is not None:
                return getattr(getattr(cam, "info", None), "bit_depth", 12)
        except Exception:
            pass
        return 12
