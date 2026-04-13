"""
acquisition/recipe_presets.py

Factory presets for common thermoreflectance measurement scenarios.

Presets provide sensible starting points for engineers working with
standard device categories.  Load a preset into the Recipe Builder,
adjust as needed, and save with your own lab-specific label.

Presets
-------
  Standard Silicon IC       General-purpose CMOS / BJT devices
  GaN / SiC Power Device    Wide-bandgap power FETs and HEMTs
  Metal Interconnects       Copper / aluminium traces — low dR/R
  LED / Laser Chip          Optical emitters — TEC-stabilised baseline
  High Sensitivity          Maximum SNR, long acquisition
  Quick Scan                Fast screening pass, 8 frames
"""

from __future__ import annotations

from typing import List

from acquisition.recipe import (
    Recipe,
    _build_standard_phases,
)


# ── Private factory helper ─────────────────────────────────────────────────

def _make(
    label:              str,
    description:        str,
    exposure_us:        float,
    gain_db:            float,
    n_frames:           int,
    delay_s:            float  = 0.1,
    threshold_k:        float  = 5.0,
    fail_peak_k:        float  = 20.0,
    fail_hotspot_count: int    = 3,
    tec_enabled:        bool   = False,
    tec_setpoint_c:     float  = 25.0,
    notes:              str    = "",
) -> Recipe:
    r = Recipe()
    r.label       = label
    r.description = description
    r.created_at  = ""          # not persisted — no timestamp until saved
    r.notes       = notes

    camera = {
        "exposure_us": exposure_us,
        "gain_db": gain_db,
        "n_frames": n_frames,
        "inter_phase_delay_s": delay_s,
    }
    tec = {
        "enabled": tec_enabled,
        "setpoint_c": tec_setpoint_c,
    }
    analysis = {
        "threshold_k": threshold_k,
        "fail_peak_k": fail_peak_k,
        "fail_hotspot_count": fail_hotspot_count,
    }
    r.phases = _build_standard_phases(
        camera=camera,
        tec=tec,
        analysis=analysis,
    )
    return r


# ── Public preset list ─────────────────────────────────────────────────────

PRESETS: List[Recipe] = [

    _make(
        label="Standard Silicon IC",
        description=(
            "General-purpose silicon transistors and CMOS devices. "
            "Good starting point for most silicon ICs."
        ),
        exposure_us=5000,
        gain_db=0,
        n_frames=32,
        delay_s=0.1,
        threshold_k=5.0,
        fail_peak_k=20.0,
        notes=(
            "Balanced settings for standard silicon. "
            "Increase n_frames to 64 or 128 for better SNR on low-power devices."
        ),
    ),

    _make(
        label="GaN / SiC Power Device",
        description=(
            "Wide-bandgap power devices (GaN HEMT, SiC MOSFET) with "
            "strong dR/R signal and high operating temperatures."
        ),
        exposure_us=8000,
        gain_db=3,
        n_frames=32,
        delay_s=0.2,
        threshold_k=5.0,
        fail_peak_k=30.0,
        notes=(
            "Extended exposure and inter-phase delay allow the device to "
            "reach thermal steady-state. Raise fail_peak_k further for "
            "high-power RF devices."
        ),
    ),

    _make(
        label="Metal Interconnects",
        description=(
            "Copper or aluminium traces with weak thermoreflectance signal. "
            "Short exposure prevents saturation on reflective surfaces."
        ),
        exposure_us=1500,
        gain_db=0,
        n_frames=64,
        delay_s=0.05,
        threshold_k=2.0,
        fail_peak_k=10.0,
        fail_hotspot_count=5,
        notes=(
            "High frame count compensates for lower dR/R coefficient on metals. "
            "Reduce exposure further if bright-field image saturates."
        ),
    ),

    _make(
        label="LED / Laser Chip",
        description=(
            "Optical emitters — TEC-stabilised baseline for repeatable ΔT mapping. "
            "Suitable for edge-emitting lasers and surface-mount LEDs."
        ),
        exposure_us=2000,
        gain_db=0,
        n_frames=64,
        delay_s=0.1,
        threshold_k=3.0,
        fail_peak_k=15.0,
        tec_enabled=True,
        tec_setpoint_c=25.0,
        notes=(
            "TEC holds substrate temperature for repeatable ΔR/R. "
            "Reduce exposure_us if the laser facet or bonding wires saturate."
        ),
    ),

    _make(
        label="High Sensitivity",
        description=(
            "Maximum SNR acquisition for research-grade imaging of faint signals. "
            "Expect 5–10 min total acquisition time."
        ),
        exposure_us=10000,
        gain_db=6,
        n_frames=128,
        delay_s=0.2,
        threshold_k=1.0,
        fail_peak_k=5.0,
        notes=(
            "Use for extremely low ΔR/R signals or sub-micron features. "
            "Ensure the sample is thermally stable before starting."
        ),
    ),

    _make(
        label="Quick Scan",
        description=(
            "Fast screening pass — 8 frames for rapid device survey or alignment check. "
            "Not suitable for final characterisation."
        ),
        exposure_us=5000,
        gain_db=0,
        n_frames=8,
        delay_s=0.05,
        threshold_k=10.0,
        fail_peak_k=50.0,
        notes=(
            "Low frame count gives coarse SNR (~6 dB less than 32-frame run). "
            "Useful for device sorting or verifying that the hot spot is visible."
        ),
    ),
]
