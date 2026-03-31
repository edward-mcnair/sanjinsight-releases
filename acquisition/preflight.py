"""
acquisition/preflight.py

Pre-capture validation system for SanjINSIGHT.

Runs a fast, one-shot set of read-only checks immediately before acquisition
starts.  Every check observes the current hardware state but never modifies
camera exposure, gain, or any other setting.

Usage
-----
    from acquisition.preflight import PreflightValidator
    validator = PreflightValidator(app_state)
    result = validator.run(operation="acquire")
    if not result.passed:
        # show dialog, let user override or cancel
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import numpy as np

log = logging.getLogger(__name__)


# ── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class PreflightCheck:
    """Result of a single preflight check."""
    rule_id:      str            # e.g. "PF_EXPOSURE"
    display_name: str            # e.g. "Exposure Quality"
    status:       str            # "pass" | "warn" | "fail"
    observed:     str            # e.g. "Mean 62% of dynamic range"
    threshold:    str = ""       # e.g. "Ideal: 40-70%"
    hint:         str = ""       # e.g. "Reduce exposure in Camera tab"
    observed_values: dict = field(default_factory=dict)  # raw numerics for remediation

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreflightResult:
    """Aggregate result of all preflight checks."""
    checks:       List[PreflightCheck] = field(default_factory=list)
    duration_ms:  float = 0.0
    timestamp:    float = 0.0

    @property
    def passed(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.status == "warn" for c in self.checks)

    @property
    def all_clear(self) -> bool:
        return all(c.status == "pass" for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "passed": self.passed,
            "has_warnings": self.has_warnings,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


# ── Validator ────────────────────────────────────────────────────────────────

class PreflightValidator:
    """
    Read-only pre-capture validation.

    All checks observe current state without modifying hardware.
    Total runtime target: < 1.5 seconds.

    Parameters
    ----------
    app_state :
        The global app_state singleton (hardware.app_state.app_state).
    metrics_snapshot : dict, optional
        Latest snapshot from MetricsService.  If provided, TEC and FPGA
        state is read from the snapshot rather than re-querying hardware.
    """

    # ── Exposure thresholds ──────────────────────────────────────────
    MEAN_IDEAL_LO   = 0.30    # below this: warn (low signal)
    MEAN_IDEAL_HI   = 0.80    # above this: warn (little headroom)
    MEAN_CRITICAL_LO = 0.15   # below this: fail (severely underexposed)
    MAX_CRITICAL     = 0.90   # max above this: fail (will clip in hot phase)

    # ── Stability thresholds (CV) ────────────────────────────────────
    CV_WARN  = 0.005
    CV_FAIL  = 0.02

    # ── Focus thresholds (Laplacian variance) ────────────────────────
    FOCUS_FAIL = 40.0
    FOCUS_WARN = 100.0

    def __init__(self, app_state, metrics_snapshot: Optional[dict] = None):
        self._as = app_state
        self._metrics = metrics_snapshot or {}

    def run(self, operation: str = "acquire") -> PreflightResult:
        """
        Run all applicable checks.

        Parameters
        ----------
        operation : "acquire" | "scan" | "transient" | "movie"
            Controls which hardware checks are included.

        Returns
        -------
        PreflightResult
        """
        t0 = time.time()
        checks: List[PreflightCheck] = []

        cam = self._as.cam

        # Hardware connectivity
        checks.extend(self._check_hardware(operation))

        if cam is None or not getattr(cam, '_open', False):
            # Can't run camera-based checks without a camera
            return PreflightResult(
                checks=checks,
                duration_ms=(time.time() - t0) * 1000,
                timestamp=t0,
            )

        # Grab frames for exposure + stability checks
        bit_depth = getattr(cam.info, 'bit_depth', 12) if cam.info else 12
        frames = self._grab_frames(cam)

        if frames:
            checks.append(self._check_exposure(frames[0], bit_depth))
            checks.append(self._check_stability(frames, bit_depth))
            checks.append(self._check_focus(frames[-1]))

        # TEC stability (from metrics snapshot, no hardware query)
        tec_checks = self._check_tec()
        checks.extend(tec_checks)

        # FFC freshness (IR cameras only)
        ffc_check = self._check_ffc_freshness()
        if ffc_check is not None:
            checks.append(ffc_check)

        return PreflightResult(
            checks=checks,
            duration_ms=(time.time() - t0) * 1000,
            timestamp=t0,
        )

    # ── Frame grabber ────────────────────────────────────────────────

    def _grab_frames(self, cam) -> List[np.ndarray]:
        """Grab a short burst of frames for analysis.  Read-only."""
        fps = getattr(cam.info, 'max_fps', 30) if cam.info else 30
        n = min(8, max(3, int(fps * 0.4)))
        frames = []
        for _ in range(n + 2):      # grab a couple extra in case of drops
            try:
                f = cam.grab(timeout_ms=2000)
                if f is not None:
                    frames.append(f.data)
                if len(frames) >= n:
                    break
            except Exception:
                break
        return frames

    # ── Individual checks ────────────────────────────────────────────

    def _check_exposure(self, data: np.ndarray,
                        bit_depth: int) -> PreflightCheck:
        """Check that exposure is in a useful range."""
        from acquisition.image_metrics import compute_intensity_stats
        stats = compute_intensity_stats(data, bit_depth)
        mean_f = stats["mean_frac"]
        max_f = stats["max_frac"]

        observed = (f"Mean {mean_f:.0%} of dynamic range, "
                    f"peak {max_f:.0%}")
        obs_vals = {"mean_frac": mean_f, "max_frac": max_f}

        if max_f > self.MAX_CRITICAL:
            return PreflightCheck(
                rule_id="PF_EXPOSURE",
                display_name="Exposure Quality",
                status="fail",
                observed=observed,
                threshold=f"Peak must be < {self.MAX_CRITICAL:.0%} "
                          f"to avoid clipping during hot phase",
                hint="Reduce exposure time or gain in the Camera tab.",
                observed_values=obs_vals,
            )
        if mean_f < self.MEAN_CRITICAL_LO:
            return PreflightCheck(
                rule_id="PF_EXPOSURE",
                display_name="Exposure Quality",
                status="fail",
                observed=observed,
                threshold=f"Mean must be > {self.MEAN_CRITICAL_LO:.0%} "
                          f"for usable SNR",
                hint="Increase exposure time or gain in the Camera tab.",
                observed_values=obs_vals,
            )
        if mean_f < self.MEAN_IDEAL_LO:
            return PreflightCheck(
                rule_id="PF_EXPOSURE",
                display_name="Exposure Quality",
                status="warn",
                observed=observed,
                threshold=f"Ideal mean: {self.MEAN_IDEAL_LO:.0%}–"
                          f"{self.MEAN_IDEAL_HI:.0%}",
                hint="Consider increasing exposure for better SNR.",
                observed_values=obs_vals,
            )
        if mean_f > self.MEAN_IDEAL_HI:
            return PreflightCheck(
                rule_id="PF_EXPOSURE",
                display_name="Exposure Quality",
                status="warn",
                observed=observed,
                threshold=f"Ideal mean: {self.MEAN_IDEAL_LO:.0%}–"
                          f"{self.MEAN_IDEAL_HI:.0%}",
                hint="Consider reducing exposure — little headroom "
                     "for hot-phase intensity increase.",
                observed_values=obs_vals,
            )
        return PreflightCheck(
            rule_id="PF_EXPOSURE",
            display_name="Exposure Quality",
            status="pass",
            observed=observed,
            observed_values=obs_vals,
        )

    def _check_stability(self, frames: List[np.ndarray],
                         bit_depth: int) -> PreflightCheck:
        """Check frame-to-frame intensity stability."""
        from acquisition.image_metrics import compute_frame_stability
        full_scale = float((1 << bit_depth) - 1) or 4095.0
        means = []
        for f in frames:
            d = f.mean(axis=2) if f.ndim == 3 else f
            means.append(float(d.mean()) / full_scale)

        cv = compute_frame_stability(means)
        observed = f"CV = {cv:.4f} across {len(frames)} frames"
        obs_vals = {"cv": cv, "n_frames": len(frames)}

        if cv > self.CV_FAIL:
            return PreflightCheck(
                rule_id="PF_STABILITY",
                display_name="Frame Stability",
                status="fail",
                observed=observed,
                threshold=f"CV must be < {self.CV_FAIL}",
                hint="System may not have settled — wait for thermal "
                     "equilibrium or check for vibration.",
                observed_values=obs_vals,
            )
        if cv > self.CV_WARN:
            return PreflightCheck(
                rule_id="PF_STABILITY",
                display_name="Frame Stability",
                status="warn",
                observed=observed,
                threshold=f"Ideal CV < {self.CV_WARN}",
                hint="Mild intensity drift detected — consider "
                     "waiting a few seconds.",
                observed_values=obs_vals,
            )
        return PreflightCheck(
            rule_id="PF_STABILITY",
            display_name="Frame Stability",
            status="pass",
            observed=observed,
            observed_values=obs_vals,
        )

    def _check_focus(self, data: np.ndarray) -> PreflightCheck:
        """Check image focus quality via Laplacian variance."""
        from acquisition.image_metrics import compute_focus
        score = compute_focus(data)
        observed = f"Focus score = {score:.1f}"
        obs_vals = {"focus_score": score}

        if score < self.FOCUS_FAIL:
            return PreflightCheck(
                rule_id="PF_FOCUS",
                display_name="Focus Quality",
                status="fail",
                observed=observed,
                threshold=f"Minimum: {self.FOCUS_FAIL:.0f}",
                hint="Image appears severely out of focus. "
                     "Use the Autofocus tab or adjust manually.",
                observed_values=obs_vals,
            )
        if score < self.FOCUS_WARN:
            return PreflightCheck(
                rule_id="PF_FOCUS",
                display_name="Focus Quality",
                status="warn",
                observed=observed,
                threshold=f"Ideal: > {self.FOCUS_WARN:.0f}",
                hint="Focus quality is marginal — consider running "
                     "autofocus for sharper results.",
                observed_values=obs_vals,
            )
        return PreflightCheck(
            rule_id="PF_FOCUS",
            display_name="Focus Quality",
            status="pass",
            observed=observed,
            observed_values=obs_vals,
        )

    def _check_hardware(self, operation: str) -> List[PreflightCheck]:
        """Check that required hardware is connected and ready."""
        checks = []

        cam = self._as.cam
        if cam is None or not getattr(cam, '_open', False):
            checks.append(PreflightCheck(
                rule_id="PF_CAMERA",
                display_name="Camera",
                status="fail",
                observed="Not connected",
                hint="Connect a camera in Device Manager.",
            ))
        else:
            checks.append(PreflightCheck(
                rule_id="PF_CAMERA",
                display_name="Camera",
                status="pass",
                observed=f"{cam.info.model} connected" if cam.info else "Connected",
            ))

        # FPGA required for modulated acquisition
        if operation in ("acquire", "scan", "transient"):
            fpga = self._as.fpga
            if fpga is None:
                checks.append(PreflightCheck(
                    rule_id="PF_FPGA",
                    display_name="FPGA / Stimulus",
                    status="warn",
                    observed="Not connected",
                    hint="Without FPGA, acquisition uses software "
                         "triggering (lower throughput).",
                ))

        # Stage required for scan operations
        if operation == "scan":
            stage = self._as.stage
            if stage is None:
                checks.append(PreflightCheck(
                    rule_id="PF_STAGE",
                    display_name="Motorized Stage",
                    status="fail",
                    observed="Not connected",
                    hint="Grid scan requires a motorized stage.",
                ))

        return checks

    # FFC freshness threshold (seconds)
    _FFC_WARN_AGE = 3600   # 1 hour

    def _check_ffc_freshness(self) -> Optional[PreflightCheck]:
        """Check FFC freshness for IR cameras.  Returns None if N/A."""
        # Only relevant when IR modality is active
        if getattr(self._as, "active_camera_type", "tr") != "ir":
            return None
        cam = None
        for c in (getattr(self._as, "ir_cam", None),
                  getattr(self._as, "cam", None)):
            if c is not None and getattr(c, "supports_ffc", lambda: False)():
                cam = c
                break
        if cam is None:
            return None

        last_ffc = getattr(cam, "last_ffc_time", None)
        if last_ffc is None:
            return PreflightCheck(
                rule_id="PF_FFC",
                display_name="Flat-Field Correction",
                status="warn",
                observed="FFC has not been run this session",
                threshold="Recommended before first acquisition",
                hint="Run FFC to calibrate pixel offsets. This removes "
                     "fixed-pattern noise from the thermal sensor.",
                observed_values={"last_ffc_age_sec": None},
            )

        age_sec = time.time() - last_ffc
        age_min = age_sec / 60.0

        if age_sec > self._FFC_WARN_AGE:
            return PreflightCheck(
                rule_id="PF_FFC",
                display_name="Flat-Field Correction",
                status="warn",
                observed=f"FFC last run {age_min:.0f} minutes ago",
                threshold="Recommended: re-run every 60 minutes",
                hint="Run FFC to recalibrate pixel offsets. Temperature "
                     "drift degrades measurement accuracy over time.",
                observed_values={"last_ffc_age_sec": age_sec},
            )

        return PreflightCheck(
            rule_id="PF_FFC",
            display_name="Flat-Field Correction",
            status="pass",
            observed=f"FFC current ({age_min:.1f} min ago)",
            observed_values={"last_ffc_age_sec": age_sec},
        )

    def _check_tec(self) -> List[PreflightCheck]:
        """Check TEC stability from the metrics snapshot."""
        tec = self._metrics.get("tec", {})
        if not tec:
            return []
        channels = tec.get("channels", [])
        checks = []
        for i, ch in enumerate(channels):
            if not ch.get("enabled", False):
                continue
            stable = ch.get("stable", False)
            delta = ch.get("delta_c", 0.0)
            if not stable:
                checks.append(PreflightCheck(
                    rule_id=f"PF_TEC_{i}",
                    display_name=f"TEC Channel {i}",
                    status="warn",
                    observed=f"Not stable (ΔT = {delta:.2f} °C)",
                    hint="TEC has not reached setpoint — temperature "
                         "drift may affect measurements.",
                ))
        return checks
