"""
ai/auto_fix.py

Auto-fix registry for diagnostic rules.

Maps rule_id → FixAction describing whether the system can automatically
resolve the issue, and the function to call when the user clicks "Fix".

Usage
-----
    from ai.auto_fix import get_fix, can_auto_fix, apply_fix

    result: RuleResult = ...
    fix = get_fix(result.rule_id)
    if fix and fix.auto:
        apply_fix(result.rule_id, hw_service, app_state)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FixAction:
    """Describes how a diagnostic rule issue can be resolved."""
    rule_id:     str
    label:       str        # button label, e.g. "Auto-Fix" or "Home XY"
    auto:        bool       # True = system can fix without user input
    description: str        # tooltip / explanation of what the fix does
    navigate_to: str = ""   # sidebar label to navigate to (manual fixes)


# ── Fix functions ────────────────────────────────────────────────────────────
# Each takes (hw_service, app_state) and returns (success: bool, message: str).
# They run on a background thread — must not touch Qt widgets directly.

def _fix_underexposure(hw, app_state):
    """C2: Increase exposure in steps until underexposure drops below threshold."""
    cam = app_state.cam
    if cam is None:
        return False, "No camera connected"
    try:
        current = cam.get_exposure()
        # Increase by 50% up to 3 iterations, capped at 50ms
        for _ in range(3):
            new_exp = min(current * 1.5, 50000.0)
            hw.cam_set_exposure(new_exp)
            current = new_exp
            import time; time.sleep(0.3)  # wait for a frame
        return True, f"Exposure increased to {current:.0f} μs"
    except Exception as e:
        return False, str(e)


def _fix_saturation(hw, app_state):
    """C1/C3: Reduce exposure in steps until saturation drops below threshold."""
    cam = app_state.cam
    if cam is None:
        return False, "No camera connected"
    try:
        current = cam.get_exposure()
        # Reduce by 30% up to 3 iterations, floor at 100μs
        for _ in range(3):
            new_exp = max(current * 0.7, 100.0)
            hw.cam_set_exposure(new_exp)
            current = new_exp
            import time; time.sleep(0.3)
        return True, f"Exposure reduced to {current:.0f} μs"
    except Exception as e:
        return False, str(e)


def _fix_stage_home(hw, app_state):
    """R3: Home the stage XY axes."""
    if app_state.stage is None:
        return False, "No stage connected"
    try:
        hw.stage_home("xy")
        return True, "Stage homing started"
    except Exception as e:
        return False, str(e)


def _fix_stage_stop(hw, app_state):
    """M1: Stop stage motion."""
    if app_state.stage is None:
        return False, "No stage connected"
    try:
        hw.stage_stop()
        return True, "Stage stopped"
    except Exception as e:
        return False, str(e)


def _fix_fpga_start(hw, app_state):
    """L1: Start FPGA modulation."""
    if app_state.fpga is None:
        return False, "No FPGA connected"
    try:
        hw.fpga_start()
        return True, "Modulation started"
    except Exception as e:
        return False, str(e)


def _fix_duty_cycle(hw, app_state):
    """T1: Reduce duty cycle to safe level (45%, below the 50% warn threshold)."""
    if app_state.fpga is None:
        return False, "No FPGA connected"
    try:
        hw.fpga_set_duty_cycle(0.45)
        return True, "Duty cycle set to 45%"
    except Exception as e:
        return False, str(e)


def _fix_tec_range(hw, app_state):
    """R5: Clamp TEC setpoint to valid range."""
    _MIN, _MAX = 15.0, 130.0
    tecs = app_state.tecs or []
    if not tecs:
        return False, "No TEC connected"
    fixed = []
    for idx, tec in enumerate(tecs):
        try:
            st = tec.get_status()
            sp = st.target_temp
            if sp < _MIN:
                hw.tec_set_target(idx, _MIN)
                fixed.append(f"TEC {idx+1} → {_MIN}°C")
            elif sp > _MAX:
                hw.tec_set_target(idx, _MAX)
                fixed.append(f"TEC {idx+1} → {_MAX}°C")
        except Exception:
            pass
    if fixed:
        return True, "Clamped: " + ", ".join(fixed)
    return True, "All TEC setpoints already in range"


# ── Fix function registry ────────────────────────────────────────────────────

_FIX_FUNCTIONS: Dict[str, Callable] = {
    "C1_saturation":      _fix_saturation,
    "C2_underexposure":   _fix_underexposure,
    "C3_pixel_headroom":  _fix_saturation,       # same remedy
    "R3_stage_homed":     _fix_stage_home,
    "M1_stage_stationary": _fix_stage_stop,
    "L1_fpga_running":    _fix_fpga_start,
    "T1_duty_cycle":      _fix_duty_cycle,
}

# TEC range fixes are per-channel — match by prefix
_TEC_RANGE_PREFIX = "R5_tec"


# ── Fix action registry ─────────────────────────────────────────────────────

_FIXES: Dict[str, FixAction] = {
    "C1_saturation": FixAction(
        rule_id="C1_saturation", label="Auto-Fix",
        auto=True, description="Reduce camera exposure to eliminate clipped pixels"),
    "C2_underexposure": FixAction(
        rule_id="C2_underexposure", label="Auto-Fix",
        auto=True, description="Increase camera exposure to improve signal"),
    "C3_pixel_headroom": FixAction(
        rule_id="C3_pixel_headroom", label="Auto-Fix",
        auto=True, description="Reduce exposure to stay below 12-bit limit"),
    "R3_stage_homed": FixAction(
        rule_id="R3_stage_homed", label="Home XY",
        auto=True, description="Home the stage XY axes"),
    "M1_stage_stationary": FixAction(
        rule_id="M1_stage_stationary", label="Stop",
        auto=True, description="Stop stage motion immediately"),
    "L1_fpga_running": FixAction(
        rule_id="L1_fpga_running", label="Start",
        auto=True, description="Start FPGA modulation"),
    "T1_duty_cycle": FixAction(
        rule_id="T1_duty_cycle", label="Auto-Fix",
        auto=True, description="Reduce duty cycle to 45%"),
    # Manual-only fixes (navigate to the relevant panel)
    "R1_cam_connected": FixAction(
        rule_id="R1_cam_connected", label="Open Device Manager",
        auto=False, description="Check USB cable and reconnect camera",
        navigate_to="Device Manager"),
    "F1_focus": FixAction(
        rule_id="F1_focus", label="Adjust Focus",
        auto=False, description="Adjust the focus knob or run Auto-Focus",
        navigate_to="Camera"),
    "F2_drift": FixAction(
        rule_id="F2_drift", label="View Camera",
        auto=False, description="Wait for thermal stabilisation; check vibration",
        navigate_to="Camera"),
    "L2_fpga_locked": FixAction(
        rule_id="L2_fpga_locked", label="View FPGA",
        auto=False, description="Check sync source and reference cable",
        navigate_to="Stimulus"),
}


def get_fix(rule_id: str) -> Optional[FixAction]:
    """Return the FixAction for a rule_id, or None if no fix is registered."""
    fix = _FIXES.get(rule_id)
    if fix:
        return fix
    # Check TEC range prefix (R5_tec0_range, R5_tec1_range, ...)
    if rule_id.startswith(_TEC_RANGE_PREFIX):
        return FixAction(
            rule_id=rule_id, label="Auto-Fix",
            auto=True, description="Clamp TEC setpoint to valid range (15-130°C)")
    # Check TEC stable prefix (R4_tec0_stable, ...)
    if rule_id.startswith("R4_tec"):
        return FixAction(
            rule_id=rule_id, label="View TEC",
            auto=False, description="Wait for temperature to stabilise",
            navigate_to="Temperature")
    return None


def can_auto_fix(rule_id: str) -> bool:
    """True if the rule has a registered automatic fix."""
    fix = get_fix(rule_id)
    return fix is not None and fix.auto


def apply_fix(rule_id: str, hw_service, app_state,
              on_complete: Optional[Callable] = None) -> None:
    """Run the fix for rule_id on a background thread.

    on_complete(success: bool, message: str) is called when done.
    """
    fix_fn = _FIX_FUNCTIONS.get(rule_id)
    if fix_fn is None and rule_id.startswith(_TEC_RANGE_PREFIX):
        fix_fn = _fix_tec_range

    if fix_fn is None:
        if on_complete:
            on_complete(False, f"No auto-fix available for {rule_id}")
        return

    def _worker():
        try:
            success, msg = fix_fn(hw_service, app_state)
            log.info("Auto-fix %s: %s — %s", rule_id,
                     "OK" if success else "FAILED", msg)
            if on_complete:
                on_complete(success, msg)
        except Exception as e:
            log.warning("Auto-fix %s failed: %s", rule_id, e, exc_info=True)
            if on_complete:
                on_complete(False, str(e))

    threading.Thread(target=_worker, daemon=True,
                     name=f"autofix.{rule_id}").start()
