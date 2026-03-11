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
  • TEC1089_Configuration file.ini (Meerstetter TEC controller — verified LabVIEW config)
  • LDD1121_Configuration file.ini (Meerstetter LDD driver  — verified LabVIEW config)
  • MAIN_AUTOMATION.py (SanjANALYZER LabVIEW automation script)
  • LabVIEW project review (EZ500_SV7.lvproj, LINX Olympus Turret.lvproj,
    IV_Curve_Tracer.lvproj, QUICKCAL.lvproj, EZIR_Imager.lvproj, et al.)

All numeric limits referenced in ui/tabs, acquisition, ai/diagnostic_rules, and
ai/prompt_templates are imported from here — never hardcoded elsewhere.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List

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

CTH_MIN: float        = 1e-5   # K⁻¹ — below this SNR is impractically low
CTH_MAX: float        = 1e-2   # K⁻¹ — above this value is anomalously high
CTH_FILTER_MIN: float = 3e-6   # K⁻¹ — minimum Cth to include pixel in ΔR/R map
                                #        (SanjANALYZER MAIN_AUTOMATION.py: Filter Magnitude Cth)


# ── Stage / Temperature Limits ───────────────────────────────────────────────

STAGE_TEMP_MIN_C    =  15.0   # minimum operating temperature (TEC1089 PAR_TOBJECT1_UNDER)
STAGE_TEMP_MAX_TC   = 130.0   # TC-100 / EZ-CAL50 maximum setpoint (TEC1089 PAR_TOBJECT1_OVER)
STAGE_TEMP_MAX_AF   = 150.0   # AF-200 maximum setpoint
STAGE_TEMP_MAX_C    = 150.0   # overall system maximum (used for validation)


# ── TEC Controller Hardware Limits (TEC1089_Configuration file.ini) ──────────
#
# Physical limits programmed into the Meerstetter TEC1089 firmware.
# Verified directly from the LabVIEW project configuration file.
#
# Note: STAGE_TEMP_MIN_C / STAGE_TEMP_MAX_TC above are kept as aliases so
# existing code that imports those names continues to work unchanged.

TEC_OBJECT_MIN_C       =  15.0   # PAR_TOBJECT1_UNDER  — object (DUT side) temp floor
TEC_OBJECT_MAX_C       = 130.0   # PAR_TOBJECT1_OVER   — object (DUT side) temp ceiling
TEC_SINK_MIN_C         =   5.0   # PAR_TSINK1_TEMP_UNDER — heatsink temp minimum
TEC_SINK_MAX_C         =  70.0   # PAR_TSINK1_TEMP_OVER  — heatsink temp maximum
TEC_STABILITY_WINDOW_C =   1.0   # PAR_STABILITY_IND_TEMP1 — stable band ±°C
TEC_STABILITY_TIME_S   =  10     # PAR_STABILITY_IND_TIME1 — seconds in-band for stable flag
TEC_MAX_CURRENT_A      =   9.25  # PAR_TEC1_LIMIT_I — TEC1 max continuous current (A)
TEC_MAX_VOLTAGE_V      =  15.5   # PAR_TEC1_LIMIT_U — TEC1 max voltage (V)
TEC_PUMP_ON_C          =  40.0   # PAR_PUMP_ON_THRESHOLD1  — coolant pump starts at this sink temp
TEC_PUMP_OFF_C         =  35.0   # PAR_PUMP_OFF_THRESHOLD1 — coolant pump stops at this sink temp
PELTIER_MAX_DT_C       =  68.0   # PAR_PELT1_MAXDT — maximum ΔT across Peltier element (K)


# ── TEC Controller PID Defaults (TEC1089_Configuration file.ini) ─────────────
#
# Factory PID tuning values for Channel 1 (temperature control mode).
# Channel 2 uses slower PID (Kp=10, Ti=300) for the auxiliary stage.
# All values verified directly from the LabVIEW configuration file (S/N 9376).

TEC_PID_KP:       float = 35.0   # PAR_TEMP1_REGUL_KP   — proportional gain
TEC_PID_TI:       float =  5.0   # PAR_TEMP1_REGUL_TI   — integral time (s)
TEC_PID_TD:       float =  0.5   # PAR_TEMP1_REGUL_TD   — derivative time (s)
TEC_PID_D_PT1:    float =  0.3   # PAR_TEMP1_REGUL_D_PT1 — derivative filter (PT1)
TEC_CONTROL_HZ:   int   =  10    # PAR_TCTRL_CYCLE1      — control loop rate (Hz)


# ── TEC-1089 Per-Unit ADC Calibration Trim (documentation only) ──────────────
#
# The TEC-1089 firmware applies a linear correction to raw ADC counts before
# computing temperature and before reporting via MeCom Parameter 1000.
# Consequently the Python driver always receives a fully corrected temperature
# in °C — these constants document the values programmed into unit S/N 9376
# and are NOT applied again in software.
#
# Formula (firmware-internal):  T_out = A0 + A1 × T_raw
#
# ⚠  UNIT SWAP WARNING ─────────────────────────────────────────────────────────
# When replacing the TEC-1089, read back PAR_TO1_ADCADJ_A0/A1 and
# PAR_TS1_ADCADJ_A0/A1 from the replacement unit via TEC Service Software.
# A 1 % A1 slope mismatch causes a sustained 0.5–1.5 °C temperature error
# that is invisible without comparing against an independent reference.
# Verify that the new unit's trim values match the ones below before use.
# ─────────────────────────────────────────────────────────────────────────────
#
# Source: TEC1089_Configuration file.ini, unit S/N 9376.

TEC_UNIT_SN:        int   = 9376         # serial number these trim values apply to
TEC_OBJ_ADC_A0:     float = -130.2993    # PAR_TO1_ADCADJ_A0 — object ADC zero offset
TEC_OBJ_ADC_A1:     float =    0.9993604 # PAR_TO1_ADCADJ_A1 — object ADC slope (0.07 % err)
TEC_SINK_ADC_A0:    float =  -12.2633    # PAR_TS1_ADCADJ_A0 — sink ADC zero offset
TEC_SINK_ADC_A1:    float =    1.016483  # PAR_TS1_ADCADJ_A1 — sink ADC slope (1.6 % err)


# ── NTC Thermistor Calibration Points (both TEC1089 and LDD1121) ──────────────
#
# Both Meerstetter devices (TEC-1089 and LDD-1121) use the same 3-point NTC
# calibration.  Values verified from both configuration files.
# NTC type: 10 kΩ @ 25 °C standard thermistor (R25 = 10 000 Ω)

MEERSTETTER_NTC_T1_C:   float =  0.0    # PAR_TOBJ_NTC_T11  — calibration point 1 temp
MEERSTETTER_NTC_R1_OHM: int   = 32650   # PAR_TOBJ_NTC_R11  — NTC resistance at T1
MEERSTETTER_NTC_T2_C:   float = 25.0    # PAR_TOBJ_NTC_T21  — calibration point 2 temp
MEERSTETTER_NTC_R2_OHM: int   = 10000   # PAR_TOBJ_NTC_R21  — NTC resistance at T2 (R25)
MEERSTETTER_NTC_T3_C:   float = 60.0    # PAR_TOBJ_NTC_T31  — calibration point 3 temp
MEERSTETTER_NTC_R3_OHM: int   =  2488   # PAR_TOBJ_NTC_R31  — NTC resistance at T3


# ── Laser Diode Driver Limits (LDD1121_Configuration file.ini) ───────────────
#
# Physical limits from the Meerstetter LDD1121 firmware.
# Verified directly from the LabVIEW project configuration file (S/N 4798).

LDD_MAX_CURRENT_A    =  2.0    # CURRENT_LIMIT    — maximum LED / laser diode current (A)
LDD_START_CURRENT_A  =  1.5    # LimitStartCurrent — ramp-up starting limit (A)
LDD_DIODE_MIN_C      = -20.0   # PAR_TLD_TEMP_UNDER — diode temperature minimum (°C)
LDD_DIODE_MAX_C      =  60.0   # PAR_TLD_TEMP_OVER  — diode temperature maximum (°C)

# LDD signal-generator timing constants (internal mode; not used in HW-trigger mode)
# In hardware-trigger mode (Pulse_Source = HW Pin), the FPGA drives pulse timing.
LDD_TIMEBASE_NS:      int   = 100    # label_TimeBase=100  — internal timer resolution (ns)
LDD_PULSE_HIGH_NS:    int   = 100    # PulseHigh=1 × 100 ns  — internal high duration
LDD_PULSE_LOW_NS:     int   = 90000  # PulseLow=900 × 100 ns — internal low duration (90 µs)
LDD_SLOPE_LIMIT_A_US: float = 0.2    # SlopeLimit — maximum current ramp rate (A/µs)
LDD_RS485_BAUD:       int   = 57600  # RS485_CH1_BaudRate — serial baud rate
LDD_RS485_ADDRESS:    int   = 1      # PAR_RS485_1_ADDR — default LDD device address


# ── LDD-1121 Per-Unit Temperature Offset (documentation only) ────────────────
#
# The LDD-1121 firmware applies a linear correction to the raw NTC reading
# before reporting the diode temperature via MeCom.  The Python driver reads
# the already-corrected value — this constant is NOT applied again in software.
#
# Formula (firmware-internal):  T_out = TLD_TEMP_Offset + TLD_TEMP_Gain × T_ntc
#
# ⚠  UNIT SWAP WARNING ─────────────────────────────────────────────────────────
# A replacement LDD-1121 may have a different TLD_TEMP_Offset programmed in its
# flash.  The diode protection limits (LDD_DIODE_MIN_C / LDD_DIODE_MAX_C) are
# evaluated on the corrected reading, so safety bounds remain valid — but logged
# temperatures will differ from legacy data if the offset changes.
# Verify via Meerstetter Service Software after installing a new unit.
# ─────────────────────────────────────────────────────────────────────────────
#
# Source: LDD1121_Configuration file.ini, unit S/N 4798.

LDD_UNIT_SN:              int   = 4798  # serial number these trim values apply to
LDD_DIODE_TEMP_OFFSET_C:  float = -0.8  # TLD_TEMP_Offset — firmware correction offset (°C)
LDD_DIODE_TEMP_GAIN:      float =  1.0  # TLD_TEMP_Gain   — firmware correction gain (unity)


# ── Bias / Electrical Output Limits ─────────────────────────────────────────
#
# VO INT  — pulsed output via internal DAC, ±10 V maximum
# AUX INT — secondary DC output, ±10 V maximum
# VO EXT  — passthrough from external supply, ≤+60 V (unipolar)

BIAS_VO_INT_MAX_V   =  10.0   # VO INT pulsed (bipolar ±10 V)
BIAS_AUX_INT_MAX_V  =  10.0   # AUX INT DC (bipolar ±10 V)
BIAS_VO_EXT_MAX_V   =  60.0   # VO EXT passthrough (unipolar 0–60 V)


# ── EZ500 PCB Shunt / Current-Limit Resistors (SYSTEM_CONFIG) ────────────────
#
# These resistors are on the EZ500 PCB and define the current-sense scale for
# SanjVIEW7 internal analogue measurements (via DAQ inputs).
#
# When Python bias drivers use an external instrument (Keithley, Rigol, etc.)
# that instrument handles V/I sensing internally — SHUNT_VA_OHM / SHUNT_VO_OHM
# are NOT applied by the Python drivers.
#
# SHUNT_20MA_OHM is relevant to the UI "20 mA Range" checkbox: with that mode
# active the 500 Ω series resistor limits device current to:
#       I_max = V_set / SHUNT_20MA_OHM    (e.g. 10 V / 500 Ω = 20 mA)
#
# Source: SYSTEM_CONFIG in LabVIEW SV7 project root.

SHUNT_VA_OHM:    float = 0.100   # VA CURR RESISTOR — aux output current shunt (Ω)
SHUNT_VO_OHM:    float = 0.100   # VO CURR RESISTOR — main output current shunt (Ω)
SHUNT_20MA_OHM:  float = 500.0   # 20MA RESISTOR    — series resistor in 20 mA limit mode (Ω)


# ── Camera Pixel Limits (12-bit sensor) ──────────────────────────────────────

CAMERA_SAT_LIMIT    = 4095    # full saturation (12-bit maximum)
CAMERA_SAT_WARN     = 3900    # warn when within ~5 % of saturation


# ── Objective Specifications (Olympus IX — from LINX Olympus Turret.lvproj) ──
#
# Full optical specifications for each objective slot on the Olympus IX turret.
# Pixel sizes assume:
#   acA1920-155um: 5.86 µm pixel pitch, 1920 × 1200 sensor
#   acA640-750um : 4.80 µm pixel pitch,  640 × 480  sensor
# Formula: px_size_um = pixel_pitch_um / magnification
# FOV width: fov_um = n_pixels × px_size_um

@dataclass
class ObjectiveSpec:
    """Optical properties of one objective lens position on the turret."""
    position:               int    # Turret slot (1-based)
    magnification:          int    # Nominal magnification
    numerical_aperture:     float  # NA
    working_dist_mm:        float  # Working distance (mm)
    label:                  str    # Display string
    px_size_acA1920_um:     float  # µm/px for Basler acA1920-155um
    px_size_acA640_um:      float  # µm/px for Basler acA640-750um
    fov_w_acA1920_um:       float  # FOV width (µm) for acA1920-155um  (1920 px × px_size)
    fov_w_acA640_um:        float  # FOV width (µm) for acA640-750um   ( 640 px × px_size)

    def fov_um(self, camera_model: str = "acA1920") -> float:
        """Return FOV width in µm for the named camera model."""
        if "640" in camera_model:
            return self.fov_w_acA640_um
        return self.fov_w_acA1920_um

    def px_size_um(self, camera_model: str = "acA1920") -> float:
        """Return pixel size in µm/px for the named camera model."""
        if "640" in camera_model:
            return self.px_size_acA640_um
        return self.px_size_acA1920_um


OBJECTIVE_SPECS: list[ObjectiveSpec] = [
    # Olympus IX — standard objective set
    ObjectiveSpec(
        position=1, magnification=4,   numerical_aperture=0.10,
        working_dist_mm=18.5, label=" 4× / 0.10 NA",
        px_size_acA1920_um =1.465,  px_size_acA640_um=1.200,
        fov_w_acA1920_um   =2813.0, fov_w_acA640_um  =768.0),
    ObjectiveSpec(
        position=2, magnification=10,  numerical_aperture=0.25,
        working_dist_mm=10.6, label="10× / 0.25 NA",
        px_size_acA1920_um =0.586,  px_size_acA640_um=0.480,
        fov_w_acA1920_um   =1125.1, fov_w_acA640_um  =307.2),
    ObjectiveSpec(
        position=3, magnification=20,  numerical_aperture=0.45,
        working_dist_mm= 8.2, label="20× / 0.45 NA",
        px_size_acA1920_um =0.293,  px_size_acA640_um=0.240,
        fov_w_acA1920_um   = 562.6, fov_w_acA640_um  =153.6),
    ObjectiveSpec(
        position=4, magnification=50,  numerical_aperture=0.80,
        working_dist_mm= 0.37,label="50× / 0.80 NA",
        px_size_acA1920_um =0.117,  px_size_acA640_um=0.096,
        fov_w_acA1920_um   = 225.0, fov_w_acA640_um  = 61.4),
    ObjectiveSpec(
        position=5, magnification=100, numerical_aperture=0.95,
        working_dist_mm= 0.21,label="100× / 0.95 NA",
        px_size_acA1920_um =0.059,  px_size_acA640_um=0.048,
        fov_w_acA1920_um   = 112.3, fov_w_acA640_um  = 30.7),
]

# Quick lookup by magnification
_OBJ_BY_MAG = {s.magnification: s for s in OBJECTIVE_SPECS}

def objective_by_mag(magnification: int) -> Optional[ObjectiveSpec]:
    """Return ObjectiveSpec for a given magnification, or None."""
    return _OBJ_BY_MAG.get(magnification)


# ── Objective Field-of-View Reference (legacy dict — kept for compatibility) ─
#
# FOV width in µm for acA1920-155um camera at each magnification.

OBJECTIVE_FOV_UM: dict[int, int] = {
    s.magnification: int(s.fov_w_acA1920_um)
    for s in OBJECTIVE_SPECS
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
TTI_TIME_RES_NS:       int   = 50    # EZ-Therm / NT220 temporal resolution (ns)
TTI_TIME_RES_BEST_PS:  int   = 800   # PT410A PicoTherm best (800 ps)
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


# ── Thermal Chuck Controller Limits ──────────────────────────────────────────
#
# Thermal chucks (Temptronic, Cascade, Wentworth) have significantly wider
# temperature ranges than Meerstetter TEC1089 controllers.
# Used in thermal_chuck.py and for calibration_tab.py range validation.

CHUCK_TEMP_MIN_C:   float = -65.0   # typical ATS-series minimum setpoint
CHUCK_TEMP_MAX_C:   float = 250.0   # typical ATS-series maximum setpoint
CHUCK_STAB_TOL_C:   float =   2.0   # stability tolerance (chucks are less precise than TEC)
CHUCK_RAMP_RATE_MAX_C_MIN: float = 300.0  # typical maximum ramp rate


# ── Movie Mode Defaults ───────────────────────────────────────────────────────
#
# Default operating parameters for the movie-mode burst acquisition pipeline.
# Frame rates are per-camera-model maximums at reduced ROI.

MOVIE_DEFAULT_N_FRAMES:    int   = 200     # default burst length (frames)
MOVIE_DEFAULT_SETTLE_MS:   float =  50.0  # settle time after power-on before burst
MOVIE_MIN_N_FRAMES:        int   =  10    # minimum useful burst
MOVIE_MAX_N_FRAMES:        int   = 2000   # practical RAM limit for full-frame sequences

# Per-camera achievable frame rates (approximate; depends on ROI and host PC speed)
MOVIE_FPS_ACA1920:  float = 155.0   # Basler acA1920-155um at full frame
MOVIE_FPS_ACA640:   float = 750.0   # Basler acA640-750um at full frame (movie camera)


# ── Transient Acquisition Defaults ───────────────────────────────────────────

TRANSIENT_DEFAULT_N_DELAYS:    int   =  50     # time-delay steps in the output cube
TRANSIENT_DEFAULT_N_AVERAGES:  int   =  50     # trigger cycles averaged per delay
TRANSIENT_DEFAULT_PULSE_US:    float = 500.0   # default power pulse width (µs)
TRANSIENT_DEFAULT_DELAY_END_S: float =   0.005 # default transient window (5 ms)
TRANSIENT_MIN_AVERAGES:        int   =  10     # below this, SNR is poor


# ── Calibration Temperature Presets ──────────────────────────────────────────
#
# TR Standard: 6-point sweep from base=20°C to high=120°C (~12 min total)
# IR Standard: 7-point sweep in the mid-range used for IR camera calibration

CAL_TR_TEMPS_C: list[float] = [20.0, 40.0, 60.0, 80.0, 100.0, 120.0]
CAL_IR_TEMPS_C: list[float] = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0]


# ── Calibration Workflow Parameters (from MAIN_AUTOMATION.py) ─────────────────
#
# Timing parameters verified from the SanjANALYZER LabVIEW automation script.
# Used to compute accurate time estimates and to set sensible UI defaults.

CAL_N_AVERAGES:       int   = 100    # standard frame averaging count per temperature step
TEC_RAMP_TIME_S:      int   =  35    # typical heating ramp time to reach each setpoint (s)
CAL_SETTLE_TIMEOUT_S: int   = 200    # maximum wait time per setpoint for stability (s)
TEC_MAX_RAMP_RATE_C_MIN: float = 200.0  # maximum TEC ramp rate (5216E config, °C/min)


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
    "Profiles→material, wavelength, C_T selection and calibration. "
    "Support: use Help menu → Get Support to open a pre-filled support email "
    "(includes system info and recent log) addressed to software-support@microsanj.com. "
    "Users can also click 'Get Support' in the AI Assistant panel. "
    "Suggest this whenever a user has an unresolved hardware or software problem."
)


# ── Compact AI Knowledge String ───────────────────────────────────────────────
#
# Injected verbatim into the LLM system prompt alongside UI_NAV_MAP.

AI_DOMAIN_KNOWLEDGE: str = (
    "Hardware limits: pixel sat=4095 (12-bit); TEC object 15–130 °C, sink 5–70 °C; "
    "VO INT ±10 V pulsed, VO EXT ≤60 V, AUX INT ±10 V DC; "
    "duty >50 % risks DUT overheating; TEC stable = ±1 °C for 10 s. "
    "LED driver (LDD-1121): max 2 A, diode –20 to 60 °C, HW-trigger via FPGA pin. "
    "Optimal LED: Si/GaAs/InP→470 nm Blue; GaN→365/470/530 nm; "
    "Au→470/530 nm; Al→780 nm ONLY; Ni/Ti→585/660 nm; "
    "flip-chip/backside→1050–1500 nm NIR (Si transparent ≥1100 nm). "
    "Typical CTR [K⁻¹]: Si/470 nm 1.5e-4, GaAs/470 nm 2.0e-4, "
    "Au/530 nm 2.5e-4; valid 1e-5 to 1e-2 K⁻¹. "
    "TTI temp res: 0.25–0.5 °C at 2 min; 6 mK best (long avg). "
    "Transient: duty 25–35 %; delayed heat = sub-surface source. "
    "TR cal: Base=20 °C High=120 °C ~12 min. "
    "IR cal: Base=85 °C High=115 °C. "
    "Convergence: ROI mean variance <5 %. "
    "Systems: EZ500 (50 ns TR, acA1920 CMOS); NT220 (50 ns, acA640, MPI prober); "
    "PT410A (800 ps, 1024×1024 EMCCD, 532/1060 nm pulsed laser)."
)


# ── System Model Specifications ───────────────────────────────────────────────
#
# Full product specifications for each Microsanj system family.
# Sources:
#   EZ500  : EZ-Therm User Manual / product datasheet
#   NT220  : Microsanj website (sitemap NT220 product pages, IMS 2024 showcase)
#   PT410A : Microsanj PicoTherm product page (picotherm-1.html, S/N PT410A)

@dataclass
class SystemModelSpec:
    """Complete specification for one Microsanj system model."""
    model:            str         # Model identifier: "EZ500", "NT220", "PT410A"
    display_name:     str         # Human-readable full name
    min_time_res_ns:  float       # Best temporal resolution (ns)
    sensor:           str         # Sensor description
    sensor_pixels:    tuple       # (width, height) in pixels
    pixel_size_um:    float       # Sensor pixel pitch (µm)
    illumination_nm:  List[int]   # Supported illumination wavelengths (nm)
    objectives:       List[int]   # Supported objective magnifications
    notes:            str = ""    # Additional notes


SYSTEM_SPECS: dict[str, SystemModelSpec] = {

    # EZ-Therm EZ500 — standard thermoreflectance, CW lock-in + transient
    "EZ500": SystemModelSpec(
        model        = "EZ500",
        display_name = "Microsanj EZ-Therm EZ500",
        min_time_res_ns = 50.0,
        sensor          = "Basler acA1920-155um CMOS (monochrome, 12-bit)",
        sensor_pixels   = (1920, 1200),
        pixel_size_um   = 5.86,
        illumination_nm = [365, 470, 532, 785, 1060],
        objectives      = [4, 10, 20, 50, 100],
        notes = (
            "Lock-in thermoreflectance and transient thermal imaging. "
            "Pulse timing via NI FPGA (50 ns resolution). "
            "Optional Basler acA640-750um for high-speed movie mode."
        ),
    ),

    # NanoTHERM NT220 — 50 ns transient, MPI probe station integration, AMCAD
    "NT220": SystemModelSpec(
        model        = "NT220",
        display_name = "Microsanj NanoTHERM NT220",
        min_time_res_ns = 50.0,
        sensor          = "Basler acA640-750um CMOS (monochrome, 12-bit, 750 fps)",
        sensor_pixels   = (640, 480),
        pixel_size_um   = 4.80,
        illumination_nm = [470, 532, 785],
        objectives      = [10, 20, 50, 100],
        notes = (
            "50 ns submicron transient thermal imaging. "
            "Integrated with MPI/FormFactor probe station and AMCAD Pulse IV. "
            "High-speed CMOS for sub-100 ns delay steps. "
            "Uses LDD-1121 laser diode driver with FPGA hardware trigger."
        ),
    ),

    # PicoTherm PT410A — 800 ps transient, EMCCD, pulsed diode laser
    "PT410A": SystemModelSpec(
        model        = "PT410A",
        display_name = "Microsanj PicoTherm PT410A",
        min_time_res_ns = 0.8,      # 800 ps = 0.8 ns
        sensor          = "1024×1024 EMCCD, 13 µm pixel pitch (480–1060 nm)",
        sensor_pixels   = (1024, 1024),
        pixel_size_um   = 13.0,
        illumination_nm = [532, 1060],
        objectives      = [5, 20, 100],
        notes = (
            "Picosecond transient thermal imager. "
            "Pulse duration: 800 ps FWHM. "
            "Spatial resolution: 380 nm @ 100×/0.7 NA/532 nm. "
            "Temperature sensitivity: 1 000 mK (EMCCD). "
            "Spectral range: 480–1060 nm (topside and backside capable). "
            "Software: SanjCONTROLLER with SanjVIEW v6.0."
        ),
    ),
}


def system_spec(model: str) -> Optional[SystemModelSpec]:
    """Return SystemModelSpec for *model* (case-insensitive key), or None."""
    return SYSTEM_SPECS.get(model.upper()) or SYSTEM_SPECS.get(model)
