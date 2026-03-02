"""
ai/instrument_knowledge.py

Single source of truth for Microsanj hardware constants extracted from user manuals.

Sources
-------
  • EZ-Therm User Manual (Microsanj EZ-Therm thermoreflectance system)
  • Nano-THERM User Manual Rev.A (Microsanj Nano-THERM system)
  • AN-002: Preparing Device Samples for Thermal Analysis
  • AN-003: Understanding the Thermoreflectance Coefficient
  • AN-004: Comparing TTI, IR, EMMI, and OBIRCH Imaging Techniques
  • AN-005: Detecting Hot-Spots and Other Thermal Defects on a Sub-Micron Scale
  • AN-006: Analysis of Time-Dependent Thermal Events in High Speed Logic ICs
  • AN-007: Through-the-Substrate Imaging Enables Flip Chip Thermal Analysis

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
    # AN-003: optimal LED for Si is 470 nm (Blue); 532 nm also usable.
    "silicon":    {470: 1.5e-4, 532: 1.5e-4, 785: 1.0e-4},
    # AN-003: optimal LED for GaAs is 470 nm (Blue); 532 nm also usable.
    "gaas":       {470: 2.0e-4, 532: 2.0e-4, 785: 1.4e-4},
    # AN-003: GaN works well at 365/470/530 nm.
    "gan":        {365: 1.8e-4, 470: 1.8e-4, 532: 1.8e-4, 785: 1.3e-4},
    "inp":        {470: 2.5e-4, 532: 2.5e-4},
    "sic":        {532: 1.2e-4},
    "gold":       {530: 2.5e-4, 470: 1.6e-4},   # pulsed TR, EZ-Therm Table 3
    "gold_ss":    {530: -2.7e-4},                 # steady-state (negative)
    "copper":     {470: 1.8e-4, 532: 1.8e-4, 785: 1.3e-4},
    "aluminum":   {780: 0.8e-4},                  # 532/470 nm Cth too small — use 780 nm only
    # AN-003: Ni and Ti optimal at 585 nm (Yellow) or 660 nm (Red)
    "nickel":     {585: 1.0e-4, 660: 0.9e-4},
    "titanium":   {585: 0.8e-4, 660: 0.7e-4},
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


# ── Optimal LED Wavelength Recommendations (from AN-003) ─────────────────────
#
# LED_WAVELENGTH_TABLE[material] → list of recommended wavelengths in nm.
# The first entry is the optimal (highest Cth) wavelength for that material.
#
# Key rules from AN-003:
#  • Al: 780 nm N-IR ONLY — Cth is negligibly small at 532/470 nm.
#  • Si, GaAs, InP: 470 nm Blue is optimal (also works at 532 nm).
#  • GaN: flexible — 365 nm UV, 470 nm Blue, or 530 nm Green all work.
#  • Ni, Ti: Yellow (585 nm) or Red (660 nm).
#  • Au: Blue (470 nm) or Green (530 nm).
#  • Flip-chip / thru-substrate: NIR (1050–1500 nm) only.

LED_WAVELENGTH_TABLE: dict[str, list[int]] = {
    "silicon":        [470, 532],               # Blue optimal; Green also usable
    "gaas":           [470, 532],               # Blue optimal; Green also usable
    "gan":            [365, 470, 530],          # UV, Blue, or Green — all work well
    "inp":            [470, 532],               # Blue optimal
    "sic":            [532, 470],               # Green; Blue also tested
    "gold":           [470, 530],               # Blue or Green
    "copper":         [470, 532],               # Blue or Green
    "aluminum":       [780],                    # N-IR ONLY — no other wavelength works
    "nickel":         [585, 660],               # Yellow or Red
    "titanium":       [585, 660],               # Yellow or Red
    "thru_substrate": [1050, 1200, 1300, 1500], # NIR for backside / flip-chip imaging
}

# Convenience function: recommended LED wavelength(s) for a material.
def led_wavelengths(material: str) -> list[int]:
    """Return recommended LED wavelengths in nm for *material* (first = optimal)."""
    return LED_WAVELENGTH_TABLE.get(material.lower(), [])


# ── Thermoreflectance Coefficient Validity Range (from AN-003) ────────────────
#
# Cth values outside this range likely indicate measurement error or
# an inappropriate wavelength / surface condition.

CTH_MIN: float = 1e-5   # K⁻¹ — below this SNR is impractically low
CTH_MAX: float = 1e-2   # K⁻¹ — above this value is anomalously high


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


# ── Objective Field-of-View Reference (from AN-002) ──────────────────────────
#
# Approximate camera FOV at each standard objective magnification.
# Values assume a typical 2/3" sensor format; actual FOV depends on sensor size.
# Use these to set scan step sizes and to estimate tile overlap.

OBJECTIVE_FOV_UM: dict[int, int] = {
    5:   2500,   # 5×   → ~2.5 mm FOV
    20:   600,   # 20×  → ~0.6 mm FOV
    50:   250,   # 50×  → ~250 µm FOV
    100:  120,   # 100× → ~120 µm FOV
}


# ── Diffraction-Limited Spatial Resolution (from AN-003 / AN-005) ────────────
#
# Spatial resolution ≈ λ / (2 × NA) at diffraction limit.
# Reference values: (NA, wavelength_nm) → resolution_nm
# Above NA = 0.5, the thermoreflectance coefficient Cth becomes NA-dependent —
# measurements at high NA require Cth recalibration or two-step correction.

SPATIAL_RES_NM: dict[tuple[float, int], int] = {
    (0.9, 365):   200,   # UV, high NA — best top-side resolution
    (0.9, 470):   260,   # Blue, high NA — standard for Si/GaAs hot-spot detection
    (0.5, 470):   470,   # Blue, medium NA
    (0.9, 532):   295,   # Green, high NA
    (0.5, 532):   530,   # Green, medium NA
    (0.9, 1100):  610,   # NIR thru-substrate, high NA
    (0.5, 1100): 1100,   # NIR thru-substrate, medium NA
}

NA_CTH_THRESHOLD: float = 0.5   # Above this NA, Cth becomes NA-dependent (AN-003)

# Silicon is virtually transparent at ≥1100 nm — enables backside / flip-chip imaging.
SI_TRANSPARENT_NM: int       = 1100
THRU_SUBSTRATE_NM: list[int] = [1050, 1200, 1300, 1500]  # Available NIR wavelengths


# ── TTI System Performance Reference (from AN-004) ───────────────────────────
#
# Key TTI performance numbers for AI context and user guidance.

TTI_TEMP_RES_2MIN_C:   float = 0.4    # Typical temperature resolution at 2 min avg
TTI_TEMP_RES_BEST_C:   float = 0.008  # Best achievable (6–10 mK, long averaging)
TTI_SPATIAL_RES_NM:    int   = 250    # Best top-side visible spatial resolution
TTI_SPATIAL_RES_NIR_UM: float = 1.5  # Thru-substrate NIR spatial resolution
TTI_TIME_RES_NS:       int   = 50    # Typical (50 ns in a megapixel image)
TTI_TIME_RES_BEST_PS:  int   = 800   # Best demonstrated (800 ps, NT410A system)
TTI_MIN_POWER_UW:      int   = 500   # Minimum detectable power (1 hr averaging)
TTI_MIN_POWER_OPT_UW:  int   = 50    # Detectable under optimal conditions


# ── Transient Imaging Parameters (from AN-006) ────────────────────────────────
#
# Recommended operating parameters for time-resolved thermoreflectance.
# Delayed thermal response relative to bias onset indicates sub-surface heating.

TRANSIENT_DUTY_MIN_PCT:  float = 25.0   # Min DUT pulse duty cycle (allows cool-down)
TRANSIENT_DUTY_MAX_PCT:  float = 35.0   # Max DUT pulse duty cycle (reaches max temp)
TRANSIENT_LED_PULSE_US:  int   = 100    # Typical LED illumination pulse width (µs)
SI_THERMAL_DIFFUSIVITY:  float = 8.8    # Silicon thermal diffusivity m²/s at 300 K
# Time resolution formula: Δt [s] = (0.02 / alpha) × x²  where x in mm, alpha in m²/s


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

# ── SanjINSIGHT UI Navigation Map ────────────────────────────────────────────
#
# Compact sidebar structure injected into the system prompt so the AI can
# answer "where is X?" questions with the correct panel and section names.
# Update this whenever the sidebar structure changes.

UI_NAV_MAP: str = (
    "SanjINSIGHT left sidebar layout — "
    "MEASURE section: Live, Acquire, Scan. "
    "ANALYSIS section: Calibration, Analysis, Compare, 3D Surface. "
    "Hardware group (collapsible): Camera, Temperature, FPGA, Bias Source, Stage, ROI, Autofocus. "
    "SETUP section: Profiles, Recipes. "
    "TOOLS section: Data, Console, Log, Settings. "
    "Key buttons by panel: "
    "Stage→Home All / Home XY / Home Z at the bottom of the Stage panel; "
    "FPGA→Start, Stop, frequency presets, duty-cycle presets; "
    "Camera→exposure, gain, saturation readout; "
    "Temperature→TEC setpoints and enable; "
    "Bias Source→output port, level, compliance, Output ON/OFF; "
    "Profiles→material, wavelength, C_T selection and calibration."
)


# ── Compact AI Knowledge String ───────────────────────────────────────────────
#
# Injected verbatim into the LLM system prompt alongside UI_NAV_MAP.

AI_DOMAIN_KNOWLEDGE: str = (
    "Hardware limits: pixel sat=4095 (12-bit); stage temp 10–150 °C; "
    "VO INT ±10 V pulsed, VO EXT ≤60 V, AUX INT ±10 V DC; "
    "duty >50 % risks DUT overheating. "
    "Optimal LED: Si/GaAs/InP→470 nm Blue; GaN→365/470/530 nm; "
    "Au→470/530 nm; Al→780 nm ONLY; Ni/Ti→585/660 nm; "
    "flip-chip/backside→1050–1500 nm NIR (Si transparent ≥1100 nm). "
    "Typical CTR [K⁻¹]: Si/470 nm 1.5e-4, GaAs/470 nm 2.0e-4, "
    "Au/530 nm 2.5e-4; valid 1e-5 to 1e-2 K⁻¹. "
    "TTI temp res: 0.25–0.5 °C at 2 min; 6 mK best (long avg). "
    "Transient: duty 25–35 %; delayed heat = sub-surface source. "
    "TR cal: Base=20 °C High=120 °C ~12 min. "
    "IR cal: Base=85 °C High=115 °C. "
    "Convergence: ROI mean variance <5 %."
)
