"""
ai/diagnostic_rules.py

Diagnostic rule functions for SanjINSIGHT.

Each rule is a pure function:
    (snapshot: dict) -> RuleResult | list[RuleResult] | None

  • Returns None when the rule is not applicable (device absent/unconfigured).
  • Returns a list for rules that produce one result per channel (e.g., TECs).
  • The snapshot dict is the output of MetricsService.current_snapshot().

Rules are grouped by category:
  R-series   Readiness and safety gates
  C-series   Camera signal quality
  F-series   Focus and motion
  L-series   FPGA / modulation coherence

Thresholds are module-level constants so they are easy to locate and tune
once real baseline data is collected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from ai.instrument_knowledge import (
    DUTY_CYCLE_WARN_PCT as _DC_WARN_PCT,   # T1 duty cycle overheating warning
    DUTY_CYCLE_FAIL_PCT as _DC_FAIL_PCT,   # T1 duty cycle overheating fail
    CAMERA_SAT_WARN     as _PIX_WARN,      # C3 pixel headroom warning
    CAMERA_SAT_LIMIT    as _PIX_FAIL,      # C3 pixel at 12-bit saturation
    TEC_OBJECT_MIN_C    as _TEMP_MIN_C,    # R5 min safe TEC setpoint  (15 °C, TEC1089)
    TEC_OBJECT_MAX_C    as _TEMP_MAX_C,    # R5 max safe TEC setpoint (130 °C, TEC1089)
    TEC_STABILITY_WINDOW_C,                # R4 stability band ±°C     (1 °C,  TEC1089)
    TEC_STABILITY_TIME_S,                  # R4 seconds in-band needed  (10 s,  TEC1089)
)


# ── Result type ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuleResult:
    """Outcome of a single diagnostic rule evaluation."""
    rule_id:      str
    display_name: str
    severity:     Literal["ok", "warn", "fail"]
    observed:     str   # human-readable observed value  e.g. "0.8%"
    threshold:    str   # human-readable threshold        e.g. "> 1.0% = fail"
    hint:         str   # one-line corrective hint


# ── Tunable thresholds ─────────────────────────────────────────────────────
# Calibrate these once real baseline data is available.

_SAT_WARN_PCT    = 0.2    # % clipped pixels  → warn
_SAT_FAIL_PCT    = 1.0    # % clipped pixels  → fail
_UNDER_WARN_PCT  = 5.0    # % near-black px   → warn
_UNDER_FAIL_PCT  = 15.0   # % near-black px   → fail
_DRIFT_WARN      = 0.02   # normalised drift  → warn
_DRIFT_FAIL      = 0.05   # normalised drift  → fail
_FOCUS_WARN      = 100.0  # Laplacian variance → warn below this
_FOCUS_FAIL      = 40.0   # Laplacian variance → fail below this
_TEC_WARN_C      = 0.10   # TEC Δ°C           → warn
_TEC_FAIL_C      = 0.20   # TEC Δ°C           → fail

# ── Thresholds imported from ai/instrument_knowledge.py ────────────────────
# _DC_WARN_PCT, _DC_FAIL_PCT, _PIX_WARN, _PIX_FAIL,
# _TEMP_MIN_C, _TEMP_MAX_C, TEC_STABILITY_WINDOW_C, TEC_STABILITY_TIME_S
# are all imported at the top of this file — do not duplicate here.


# ══════════════════════════════════════════════════════════════════════════════
#  R-series — Readiness and safety gates
# ══════════════════════════════════════════════════════════════════════════════

def rule_camera_connected(snap: dict) -> RuleResult:
    """R1 — camera must be connected."""
    connected = snap.get("camera", {}).get("connected", False)
    return RuleResult(
        rule_id      = "R1_cam_connected",
        display_name = "Camera connected",
        severity     = "ok" if connected else "fail",
        observed     = "Connected" if connected else "Not connected",
        threshold    = "Must be connected",
        hint         = "Check USB cable and camera power; reconnect in the Camera panel (Hardware group).",
    )


def rule_stage_homed(snap: dict) -> Optional[RuleResult]:
    """R3 — stage should be homed before automated moves."""
    stage = snap.get("stage", {})
    if not stage:
        return None
    # Skip rule when no real stage is connected (avoids false warnings
    # from stale simulated-driver data after demo mode exit).
    try:
        from hardware.app_state import app_state as _as
        if not _as.demo_mode and _as.stage is None:
            return None
    except Exception:
        pass
    homed = stage.get("homed", False)
    return RuleResult(
        rule_id      = "R3_stage_homed",
        display_name = "Stage homed",
        severity     = "ok" if homed else "warn",
        observed     = "Homed" if homed else "Not homed",
        threshold    = "Should be homed for automated moves",
        hint         = "Open the Stage panel (Hardware group, left sidebar) and click 'Home All' at the bottom to set the home reference position.",
    )


def rule_tec_stable(snap: dict) -> list[RuleResult]:
    """R4 — each enabled TEC should be within setpoint tolerance."""
    # Skip rule when no real TECs are connected (avoids false warnings
    # from stale simulated-driver data after demo mode exit).
    try:
        from hardware.app_state import app_state as _as
        if not _as.demo_mode and not getattr(_as, 'tecs', None):
            return []
    except Exception:
        pass
    results: list[RuleResult] = []
    for tec in snap.get("tec", []):
        if tec.get("error") or not tec.get("enabled"):
            continue  # TEC not active — skip
        idx     = tec["idx"]
        delta   = tec.get("delta_c", 0.0)
        stable  = tec.get("stable", False)
        t_band  = tec.get("time_in_band_s", 0.0)
        target  = tec.get("target_c", 0.0)

        if stable:
            severity = "ok"
        elif delta > _TEC_FAIL_C:
            severity = "fail"
        else:
            severity = "warn"

        results.append(RuleResult(
            rule_id      = f"R4_tec{idx}_stable",
            display_name = f"TEC {idx + 1} stable",
            severity     = severity,
            observed     = f"Δ{delta:.2f}°C  ({t_band:.0f} s in-band)",
            threshold    = (
                f"Δ< {_TEC_WARN_C}°C = ok  "
                f"Δ> {_TEC_FAIL_C}°C = fail"
            ),
            hint = (
                f"Wait for TEC {idx + 1} to stabilise at {target:.1f}°C "
                f"(controller requires ±{TEC_STABILITY_WINDOW_C:.0f} °C for "
                f"{TEC_STABILITY_TIME_S} s). "
                "Open the Temperature panel to monitor progress; "
                "reduce FPGA duty cycle to lower sample heating."
            ),
        ))
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  C-series — Camera signal quality
# ══════════════════════════════════════════════════════════════════════════════

def rule_saturation(snap: dict) -> Optional[RuleResult]:
    """C1 — clipped pixels degrade ΔR/R accuracy."""
    cam = snap.get("camera", {})
    if not cam.get("connected"):
        return None
    pct = cam.get("saturation_pct", 0.0)
    if pct >= _SAT_FAIL_PCT:
        severity = "fail"
    elif pct >= _SAT_WARN_PCT:
        severity = "warn"
    else:
        severity = "ok"
    return RuleResult(
        rule_id      = "C1_saturation",
        display_name = "Pixel saturation",
        severity     = severity,
        observed     = f"{pct:.2f}% clipped",
        threshold    = f"Warn > {_SAT_WARN_PCT}%   Fail > {_SAT_FAIL_PCT}%",
        hint         = "Reduce exposure time in the Camera panel, or lower the illumination intensity, to eliminate clipped pixels.",
    )


def rule_underexposure(snap: dict) -> Optional[RuleResult]:
    """C2 — too many near-black pixels indicate insufficient signal."""
    cam = snap.get("camera", {})
    if not cam.get("connected"):
        return None
    pct = cam.get("underexposure_pct", 0.0)
    if pct >= _UNDER_FAIL_PCT:
        severity = "fail"
    elif pct >= _UNDER_WARN_PCT:
        severity = "warn"
    else:
        severity = "ok"
    return RuleResult(
        rule_id      = "C2_underexposure",
        display_name = "Underexposure",
        severity     = severity,
        observed     = f"{pct:.1f}% near-black pixels",
        threshold    = f"Warn > {_UNDER_WARN_PCT}%   Fail > {_UNDER_FAIL_PCT}%",
        hint         = "Increase exposure in the Camera panel or raise illumination; use the ROI panel to recentre over the sample.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  F-series — Focus and motion
# ══════════════════════════════════════════════════════════════════════════════

def rule_focus(snap: dict) -> Optional[RuleResult]:
    """F1 — low focus score degrades spatial resolution and hotspot detection."""
    cam = snap.get("camera", {})
    if not cam.get("connected"):
        return None
    score = cam.get("focus_score", 0.0)
    if score < _FOCUS_FAIL:
        severity = "fail"
    elif score < _FOCUS_WARN:
        severity = "warn"
    else:
        severity = "ok"
    return RuleResult(
        rule_id      = "F1_focus",
        display_name = "Focus quality",
        severity     = severity,
        observed     = f"{score:.0f}",
        threshold    = f"Warn < {_FOCUS_WARN:.0f}   Fail < {_FOCUS_FAIL:.0f}",
        hint         = "Adjust the focus knob until the score rises above the warn threshold.",
    )


def rule_drift(snap: dict) -> Optional[RuleResult]:
    """F2 — high inter-frame drift indicates thermal or mechanical instability."""
    cam = snap.get("camera", {})
    if not cam.get("connected"):
        return None
    score = cam.get("drift_score", 0.0)
    if score >= _DRIFT_FAIL:
        severity = "fail"
    elif score >= _DRIFT_WARN:
        severity = "warn"
    else:
        severity = "ok"
    return RuleResult(
        rule_id      = "F2_drift",
        display_name = "Frame drift",
        severity     = severity,
        observed     = f"{score:.4f}",
        threshold    = f"Warn > {_DRIFT_WARN}   Fail > {_DRIFT_FAIL}",
        hint         = (
            "Wait for thermal stabilisation, confirm stage is stationary, "
            "and reduce external vibration sources."
        ),
    )


def rule_stage_not_moving(snap: dict) -> Optional[RuleResult]:
    """M1 — stage movement during acquisition blurs the image."""
    stage = snap.get("stage", {})
    if not stage:
        return None
    moving = stage.get("moving", False)
    return RuleResult(
        rule_id      = "M1_stage_stationary",
        display_name = "Stage stationary",
        severity     = "fail" if moving else "ok",
        observed     = "Moving" if moving else "Stationary",
        threshold    = "Must be stationary during acquisition",
        hint         = "Wait for the stage move to complete before starting acquisition.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  L-series — FPGA / modulation coherence
# ══════════════════════════════════════════════════════════════════════════════

def rule_fpga_running(snap: dict) -> Optional[RuleResult]:
    """L1 — modulation must be running for lock-in acquisition."""
    fpga = snap.get("fpga", {})
    if not fpga:
        return None
    running = fpga.get("running", False)
    return RuleResult(
        rule_id      = "L1_fpga_running",
        display_name = "Modulation running",
        severity     = "ok" if running else "warn",
        observed     = "Running" if running else "Stopped",
        threshold    = "Should be running for lock-in acquisition",
        hint         = "Click the 'Start' button in the FPGA panel (Hardware group) to begin modulation before acquiring.",
    )


def rule_fpga_locked(snap: dict) -> Optional[RuleResult]:
    """L2 — sync lock ensures phase-stable modulation."""
    fpga = snap.get("fpga", {})
    if not fpga or not fpga.get("running"):
        return None   # not applicable if not running
    locked = fpga.get("sync_locked", False)
    return RuleResult(
        rule_id      = "L2_fpga_locked",
        display_name = "Sync locked",
        severity     = "ok" if locked else "warn",
        observed     = "Locked" if locked else "Not locked",
        threshold    = "Sync should be locked for stable modulation",
        hint         = (
            "In the FPGA panel, check the sync source and reference cable; "
            "try a lower modulation frequency if sync lock cannot be achieved."
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  T-series — Thermal safety (DUT overheating)
# ══════════════════════════════════════════════════════════════════════════════

def rule_duty_cycle_thermal(snap: dict) -> Optional[RuleResult]:
    """T1 — high FPGA duty cycle risks DUT overheating.

    duty_cycle in the snapshot is a 0–1 fraction (from MetricsService).
    """
    fpga = snap.get("fpga", {})
    if not fpga.get("connected") or not fpga.get("running"):
        return None
    dc_pct = fpga.get("duty_cycle", 0.0) * 100.0   # convert fraction → %
    if dc_pct > _DC_FAIL_PCT:
        sev = "fail"
    elif dc_pct > _DC_WARN_PCT:
        sev = "warn"
    else:
        sev = "ok"
    return RuleResult(
        rule_id      = "T1_duty_cycle",
        display_name = "Duty cycle thermal risk",
        severity     = sev,
        observed     = f"{dc_pct:.0f}%",
        threshold    = f"Warn >{_DC_WARN_PCT:.0f}%   Fail >{_DC_FAIL_PCT:.0f}%",
        hint         = "Reduce the duty cycle in the FPGA panel (Hardware group) to lower average power delivered to the DUT.",
    )


def rule_pixel_headroom(snap: dict) -> Optional[RuleResult]:
    """C3 — warn when camera pixels approach 12-bit saturation ceiling.

    max_pixel is the single highest pixel value in the latest frame.
    """
    cam = snap.get("camera", {})
    if not cam.get("connected"):
        return None
    mx = cam.get("max_pixel", 0)
    if mx >= _PIX_FAIL:
        sev = "fail"
        obs = "CLIPPED (4095)"
    elif mx >= _PIX_WARN:
        sev = "warn"
        obs = f"{mx} / {_PIX_FAIL}"
    else:
        sev = "ok"
        obs = f"{mx} / {_PIX_FAIL}"
    return RuleResult(
        rule_id      = "C3_pixel_headroom",
        display_name = "Pixel headroom",
        severity     = sev,
        observed     = obs,
        threshold    = f"Warn ≥{_PIX_WARN}   Fail ={_PIX_FAIL}",
        hint         = (
            "Reduce exposure in the Camera panel or lower illumination "
            "to keep pixel values below the 12-bit saturation limit (4095)."
        ),
    )


def rule_tec_temp_range(snap: dict) -> list[RuleResult]:
    """R5 — TEC setpoints must remain within hardware-safe operating range."""
    results: list[RuleResult] = []
    for tec in snap.get("tec", []):
        if not tec.get("enabled"):
            continue
        sp  = tec.get("target_c", 25.0)
        idx = tec.get("idx", 0)
        if sp < _TEMP_MIN_C or sp > _TEMP_MAX_C:
            sev = "fail"
        else:
            sev = "ok"
        results.append(RuleResult(
            rule_id      = f"R5_tec{idx}_range",
            display_name = f"TEC {idx + 1} temp range",
            severity     = sev,
            observed     = f"{sp:.1f} °C",
            threshold    = f"{_TEMP_MIN_C}–{_TEMP_MAX_C} °C",
            hint         = (
                f"Adjust TEC {idx + 1} setpoint in the Temperature panel "
                f"to be between {_TEMP_MIN_C:.0f} and {_TEMP_MAX_C:.0f} °C."
            ),
        ))
    return results


# ── Rule registry — order determines evaluation and display order ──────────

ALL_RULES: list = [
    # R-series — readiness gates (checked first)
    rule_camera_connected,
    rule_stage_homed,
    rule_tec_stable,
    rule_tec_temp_range,          # R5 — TEC setpoint within hardware limits
    # C-series — camera signal quality
    rule_saturation,
    rule_underexposure,
    rule_pixel_headroom,          # C3 — 12-bit pixel headroom
    # F-series — focus and motion
    rule_focus,
    rule_drift,
    rule_stage_not_moving,
    # L-series — modulation
    rule_fpga_running,
    rule_fpga_locked,
    # T-series — thermal safety
    rule_duty_cycle_thermal,      # T1 — duty cycle overheating risk
]
