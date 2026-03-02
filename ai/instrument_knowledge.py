"""
ai/instrument_knowledge.py

Single source of truth for Microsanj hardware constants extracted from user manuals.

Sources
-------
  • EZ-Therm User Manual (Microsanj EZ-Therm thermoreflectance system)
  • Nano-THERM User Manual Rev.A (Microsanj Nano-THERM system)

All numeric limits referenced in ui/tabs, acquisition, ai/diagnostic_rules, and
ai/prompt_templates are imported from here — never hardcoded elsewhere.
"""

from __future__ import annotations

# ── Thermoreflectance Coefficients (CTR / C_T / Cth) [K⁻¹] ─────────────────
#
# CTR_TABLE[material][wavelength_nm] → C_T in K⁻¹
# Values taken from EZ-Therm User Manual §C_T Coefficients and
# NanoTherm Rev.A §Calibration.
#
# Notes:
#  • Aluminium: Cth at 532/470 nm is too small to be useful — always use 780 nm.
#  • gold_ss: steady-state (DC) measurement; negative coefficient is expected.
#  • GaN / InP values are typical; device-specific calibration is recommended.

CTR_TABLE: dict[str, dict[int, float]] = {
    "silicon":    {532: 1.5e-4, 785: 1.0e-4},
    "gaas":       {532: 2.0e-4, 785: 1.4e-4},
    "gan":        {532: 1.8e-4, 785: 1.3e-4},
    "inp":        {532: 2.5e-4},
    "sic":        {532: 1.2e-4},
    "gold":       {530: 2.5e-4, 470: 1.6e-4},   # pulsed TR, EZ-Therm Table 3
    "gold_ss":    {530: -2.7e-4},                 # steady-state (negative)
    "copper":     {532: 1.8e-4, 785: 1.3e-4},
    "aluminum":   {780: 0.8e-4},                  # 532/470 nm Cth too small
}

# Convenience lookup: return C_T for a material/wavelength pair, or None.
def ctr_lookup(material: str, wavelength_nm: int) -> float | None:
    """Return C_T [K⁻¹] for *material* (case-insensitive) at *wavelength_nm*, or None."""
    row = CTR_TABLE.get(material.lower())
    if row is None:
        return None
    # Try exact match first, then nearest within ±10 nm.
    if wavelength_nm in row:
        return row[wavelength_nm]
    for wl, val in row.items():
        if abs(wl - wavelength_nm) <= 10:
            return val
    return None


# ── Stage / Temperature Limits ───────────────────────────────────────────────

STAGE_TEMP_MIN_C    =  10.0   # minimum operating temperature (all stage types)
STAGE_TEMP_MAX_TC   = 120.0   # TC-100 / EZ-CAL50 maximum setpoint
STAGE_TEMP_MAX_AF   = 150.0   # AF-200 maximum setpoint
STAGE_TEMP_MAX_C    = 150.0   # overall system maximum (used for validation)


# ── Bias / Electrical Output Limits ─────────────────────────────────────────
#
# VO INT  — pulsed output via internal DAC, ±10 V maximum
# AUX INT — secondary DC output, ±10 V maximum
# VO EXT  — passthrough from external supply, ≤+60 V (unipolar)

BIAS_VO_INT_MAX_V   =  10.0   # VO INT pulsed (bipolar ±10 V)
BIAS_AUX_INT_MAX_V  =  10.0   # AUX INT DC (bipolar ±10 V)
BIAS_VO_EXT_MAX_V   =  60.0   # VO EXT passthrough (unipolar 0–60 V)


# ── Camera Pixel Limits (12-bit sensor) ──────────────────────────────────────

CAMERA_SAT_LIMIT    = 4095    # full saturation (12-bit maximum)
CAMERA_SAT_WARN     = 3900    # warn when within ~5 % of saturation


# ── FPGA Duty Cycle Safety Thresholds ────────────────────────────────────────

DUTY_CYCLE_WARN_PCT = 50.0    # above this → risk of DUT overheating
DUTY_CYCLE_FAIL_PCT = 80.0    # above this → high overheating risk


# ── Calibration Temperature Presets ──────────────────────────────────────────
#
# TR Standard: 6-point sweep from base=20°C to high=120°C (~12 min total)
# IR Standard: 7-point sweep in the mid-range used for IR camera calibration

CAL_TR_TEMPS_C: list[float] = [20.0, 40.0, 60.0, 80.0, 100.0, 120.0]
CAL_IR_TEMPS_C: list[float] = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0]


# ── Compact AI Knowledge String ───────────────────────────────────────────────
#
# Injected verbatim into the LLM system prompt.  Keep under ~80 tokens so the
# combined SYSTEM_PROMPT stays within the 200-token budget for 3 B models.

AI_DOMAIN_KNOWLEDGE: str = (
    "Hardware limits: pixel sat=4095 (12-bit); stage temp 10–150 °C; "
    "VO INT ±10 V pulsed, VO EXT ≤60 V, AUX INT ±10 V DC; "
    "duty >50% risks DUT overheating. "
    "Typical CTR [K⁻¹]: Si/532 nm 1.5e-4, GaAs/532 nm 2.0e-4, "
    "Au/530 nm 2.5e-4, Al: use 780 nm LED (532/470 nm Cth too small). "
    "TR cal: Base=20 °C High=120 °C ~12 min. "
    "IR cal: Base=85 °C High=115 °C. "
    "Convergence: ROI mean variance <5%."
)
