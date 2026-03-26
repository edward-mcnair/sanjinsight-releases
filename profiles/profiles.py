"""
profiles/profiles.py

MaterialProfile data model and category constants.

A MaterialProfile captures the thermoreflectance calibration parameters
for a specific material under specific imaging conditions:
    - C_T coefficient (K⁻¹): converts ΔR/R to ΔT
    - Recommended camera settings (exposure, gain, wavelength)
    - Material metadata (category, description, notes)

Profiles are stored as JSON files in ~/.microsanj/profiles/
and are managed by ProfileManager.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ------------------------------------------------------------------ #
#  Category constants                                                  #
# ------------------------------------------------------------------ #

CATEGORY_SEMICONDUCTOR = "Semiconductor"
CATEGORY_PCB           = "PCB"
CATEGORY_AUTOMOTIVE    = "Automotive"
CATEGORY_METAL         = "Metal"
CATEGORY_USER          = "User Defined"

ALL_CATEGORIES = [
    CATEGORY_SEMICONDUCTOR,
    CATEGORY_PCB,
    CATEGORY_AUTOMOTIVE,
    CATEGORY_METAL,
    CATEGORY_USER,
]

# Accent colours matching the application dark theme
CATEGORY_ACCENTS: dict = {
    CATEGORY_SEMICONDUCTOR: "#00d4aa",   # teal
    CATEGORY_PCB:           "#4488ff",   # blue
    CATEGORY_AUTOMOTIVE:    "#ffaa00",   # amber
    CATEGORY_METAL:         "#cc88ff",   # violet
    CATEGORY_USER:          "#ff6688",   # pink
}

# Subtle dark-tinted backgrounds for selected / hovered profile cards.
# Used by _ProfileCard / _ProfileRow._refresh_style() in wizard.py.
# Each value is a dark mix of the corresponding CATEGORY_ACCENTS colour
# blended against the #111 app background (~15 % tint).
CATEGORY_COLORS: dict = {
    CATEGORY_SEMICONDUCTOR: "#0d2a22",   # dark teal tint
    CATEGORY_PCB:           "#0d1a2a",   # dark blue tint
    CATEGORY_AUTOMOTIVE:    "#2a1e0d",   # dark amber tint
    CATEGORY_METAL:         "#1a0d2a",   # dark violet tint
    CATEGORY_USER:          "#2a0d18",   # dark pink tint
}


# ------------------------------------------------------------------ #
#  MaterialProfile                                                     #
# ------------------------------------------------------------------ #

@dataclass
class MaterialProfile:
    """
    Complete description of a material's thermoreflectance properties
    and preferred acquisition settings.
    """

    uid:            str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name:           str   = ""
    material:       str   = ""
    category:       str   = CATEGORY_USER
    description:    str   = ""
    notes:          str   = ""
    created_at:     str   = ""

    # ── Camera & modality ───────────────────────────────────────────
    modality:           str   = "tr"     # "tr" | "ir" | "any"
    auto_exposure:      bool  = True     # enable auto-exposure on profile load
    exposure_target_pct: float = 70.0    # histogram target (% of dynamic range)

    # Thermoreflectance coefficient (dR/R per kelvin)
    ct_value:       float = 1.5e-4   # K⁻¹ — typical GaAs at 532 nm
    wavelength_nm:  int   = 532      # illumination wavelength

    # Recommended acquisition settings
    exposure_us:    float = 5000.0
    gain_db:        float = 0.0
    n_frames:       int   = 16
    accumulation:   int   = 16

    # ── Stimulus ────────────────────────────────────────────────────
    stimulus_freq_hz:   float = 1000.0   # FPGA modulation frequency
    stimulus_duty:      float = 0.50     # FPGA duty cycle (0–1)
    stimulus_waveform:  str   = "square" # "square" | "sine"
    trigger_mode:       str   = "continuous"  # "continuous" | "single_shot"
    pulse_duration_us:  float = 100.0    # BNC 745 pulse width

    # ── Temperature / calibration ───────────────────────────────────
    tec_setpoint_c:     float = 25.0     # default TEC temperature
    tec_enabled:        bool  = True     # whether profile needs TEC
    cal_temps:          str   = ""       # comma-separated cal sequence, e.g. "25,30,35,40,45"
    cal_settle_s:       float = 60.0     # settle time per cal step (seconds)
    cal_n_avg:          int   = 100      # frames per calibration step
    cal_stability_tol_c: float = 0.2     # °C tolerance for "settled"
    cal_stability_dur_s: float = 5.0     # seconds at stable before capture
    cal_min_r2:         float = 0.80     # minimum R² fit quality

    # ── Bias source ─────────────────────────────────────────────────
    bias_voltage_v:     float = 0.0      # default bias voltage
    bias_compliance_ma: float = 100.0    # current compliance (mA)
    bias_enabled:       bool  = False    # whether device needs bias

    # ── BILT pulse configuration (power device testing) ─────────────
    bilt_gate_bias_v:   float = -5.0
    bilt_gate_pulse_v:  float = -2.2
    bilt_gate_width_us: float = 110.0
    bilt_gate_delay_us: float = 5.0
    bilt_drain_bias_v:  float = 0.0
    bilt_drain_pulse_v: float = 1.0
    bilt_drain_width_us: float = 100.0
    bilt_drain_delay_us: float = 10.0

    # ── Signal quality ──────────────────────────────────────────────
    snr_threshold_db:   float = 20.0     # minimum acceptable SNR
    roi_strategy:       str   = "center50"  # "full" | "center50" | "center25"

    # ── Autofocus defaults ──────────────────────────────────────────
    af_strategy:    str   = "sweep"      # "sweep" | "hill_climb"
    af_metric:      str   = "laplacian"  # "laplacian"|"tenengrad"|"normalized"|"fft"|"brenner"
    af_z_range_um:  float = 1000.0       # total Z sweep range
    af_coarse_um:   float = 50.0         # coarse step
    af_fine_um:     float = 5.0          # fine step
    af_n_avg:       int   = 2            # frames per Z position

    # ── Analysis thresholds ─────────────────────────────────────────
    analysis_threshold_k:    float = 5.0   # temperature threshold for hotspot detection
    analysis_fail_hotspot_n: int   = 0     # 0 = use recipe/tab default
    analysis_fail_peak_k:    float = 0.0
    analysis_warn_hotspot_n: int   = 0
    analysis_warn_peak_k:    float = 0.0

    # ── Scan / grid defaults ────────────────────────────────────────
    grid_step_um:       float = 50.0     # default grid step size (µm)
    grid_overlap_pct:   float = 10.0     # overlap percentage for stitching

    # ── Transient capture defaults ──────────────────────────────────
    transient_n_delays:     int   = 50
    transient_delay_end_ms: float = 1000.0
    transient_pulse_us:     float = 100.0
    transient_n_avg:        int   = 10

    # Display / analysis helpers
    dt_range_k:     float = 10.0   # expected ΔT range (for display scaling)
    expected_dr_r:  str   = ""     # expected ΔR/R range, e.g. "1e-4,5e-3"
    colormap:       str   = "Thermal Delta"  # preferred colormap

    # Optics guidance (informational, shown in Guided mode)
    recommended_objective: str = ""  # e.g. "10×" or "20×"
    illumination_note:     str = ""  # e.g. "LED at 70%"
    sample_prep_note:      str = ""  # e.g. "Clean surface with IPA"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialProfile":
        known = {k: v for k, v in d.items()
                 if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in self.name).strip("_") or self.uid
        path = directory / f"{safe}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, path: Path) -> "MaterialProfile":
        with open(path) as f:
            return cls.from_dict(json.load(f))


# ------------------------------------------------------------------ #
#  Built-in material profiles                                          #
# ------------------------------------------------------------------ #
# C_T values are representative literature / empirical values for each
# material + wavelength combination.  Users can override via ProfileManager.

BUILTIN_PROFILES: list = [
    # ── Semiconductors — 532 nm ────────────────────────────────────
    MaterialProfile(uid="si_532",   name="Silicon — 532 nm",
                    material="Silicon",       category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.5e-4,          wavelength_nm=532,
                    description="Crystalline silicon, green illumination",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,35,40,45",
                    cal_settle_s=60.0,        snr_threshold_db=20.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="5e-5,5e-3"),
    MaterialProfile(uid="gaas_532", name="GaAs — 532 nm",
                    material="GaAs",          category=CATEGORY_SEMICONDUCTOR,
                    ct_value=2.0e-4,          wavelength_nm=532,
                    description="Gallium arsenide, green illumination",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,35,40,45",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="1e-4,8e-3"),
    MaterialProfile(uid="gan_532",  name="GaN — 532 nm",
                    material="GaN",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.8e-4,          wavelength_nm=532,
                    description="Gallium nitride, green illumination",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,40,50,60,70,80",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="5e-5,5e-3"),
    MaterialProfile(uid="inp_532",  name="InP — 532 nm",
                    material="InP",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=2.5e-4,          wavelength_nm=532,
                    description="Indium phosphide, green illumination",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,35,40,45",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="1e-4,1e-2"),
    MaterialProfile(uid="sic_532",  name="SiC — 532 nm",
                    material="SiC",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.2e-4,          wavelength_nm=532,
                    description="Silicon carbide, green illumination",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55,65,75",
                    cal_settle_s=90.0,        snr_threshold_db=20.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="3e-5,3e-3"),
    # ── Semiconductors — 785 nm ────────────────────────────────────
    MaterialProfile(uid="si_785",   name="Silicon — 785 nm",
                    material="Silicon",       category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.0e-4,          wavelength_nm=785,
                    description="Crystalline silicon, NIR illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,35,40,45",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="3e-5,3e-3"),
    MaterialProfile(uid="gaas_785", name="GaAs — 785 nm",
                    material="GaAs",          category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.4e-4,          wavelength_nm=785,
                    description="Gallium arsenide, NIR illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,35,40,45",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="5e-5,5e-3"),
    MaterialProfile(uid="gan_785",  name="GaN — 785 nm",
                    material="GaN",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.3e-4,          wavelength_nm=785,
                    description="Gallium nitride, NIR illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,30,40,50,60,70,80",
                    cal_settle_s=60.0,        snr_threshold_db=18.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="3e-5,3e-3"),
    # ── Metals — 532 nm ───────────────────────────────────────────
    MaterialProfile(uid="cu_532",   name="Copper — 532 nm",
                    material="Copper",        category=CATEGORY_METAL,
                    ct_value=0.8e-4,          wavelength_nm=532,
                    description="Bulk copper, green illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55",
                    cal_settle_s=45.0,        snr_threshold_db=15.0,
                    roi_strategy="center25",  recommended_objective="10×",
                    illumination_note="Metals reflect strongly — start at low exposure",
                    expected_dr_r="2e-5,2e-3"),
    MaterialProfile(uid="au_532",   name="Gold — 532 nm",
                    material="Gold",          category=CATEGORY_METAL,
                    ct_value=1.2e-4,          wavelength_nm=532,
                    description="Gold film or bulk, green illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55",
                    cal_settle_s=45.0,        snr_threshold_db=15.0,
                    roi_strategy="center25",  recommended_objective="10×",
                    illumination_note="Metals reflect strongly — start at low exposure",
                    expected_dr_r="3e-5,4e-3"),
    MaterialProfile(uid="al_532",   name="Aluminum — 532 nm",
                    material="Aluminum",      category=CATEGORY_METAL,
                    ct_value=0.5e-4,          wavelength_nm=532,
                    description="Aluminum film or bulk, green illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55",
                    cal_settle_s=45.0,        snr_threshold_db=15.0,
                    roi_strategy="center25",  recommended_objective="10×",
                    illumination_note="Weak TR signal — use maximum averaging",
                    n_frames=32,              accumulation=32,
                    expected_dr_r="1e-5,1e-3"),
    # ── Metals — 785 nm ───────────────────────────────────────────
    MaterialProfile(uid="cu_785",   name="Copper — 785 nm",
                    material="Copper",        category=CATEGORY_METAL,
                    ct_value=0.6e-4,          wavelength_nm=785,
                    description="Bulk copper, NIR illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55",
                    cal_settle_s=45.0,        snr_threshold_db=15.0,
                    roi_strategy="center25",  recommended_objective="10×",
                    expected_dr_r="1e-5,1e-3"),
    # ── PCB / packaging ───────────────────────────────────────────
    MaterialProfile(uid="fr4_532",  name="FR4 — 532 nm",
                    material="FR4",           category=CATEGORY_PCB,
                    ct_value=0.3e-4,          wavelength_nm=532,
                    description="Standard PCB substrate, green illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=False,        bias_enabled=True,
                    bias_voltage_v=3.3,       bias_compliance_ma=500.0,
                    cal_temps="25,35,45",     cal_settle_s=45.0,
                    snr_threshold_db=12.0,    roi_strategy="full",
                    grid_step_um=200.0,       grid_overlap_pct=15.0,
                    n_frames=32,              accumulation=32,
                    recommended_objective="5×",
                    illumination_note="Large area — use low magnification and grid scan",
                    expected_dr_r="5e-6,5e-4"),
    MaterialProfile(uid="cuw_532",  name="Cu/W composite — 532 nm",
                    material="Cu/W",          category=CATEGORY_PCB,
                    ct_value=0.7e-4,          wavelength_nm=532,
                    description="Copper-tungsten heat spreader, green illumination",
                    stimulus_freq_hz=500.0,   stimulus_duty=0.50,
                    tec_enabled=True,         cal_temps="25,35,45,55",
                    cal_settle_s=45.0,        snr_threshold_db=15.0,
                    roi_strategy="center50",  recommended_objective="10×",
                    expected_dr_r="2e-5,2e-3"),
    # ── Automotive / EV ───────────────────────────────────────────
    MaterialProfile(uid="sic_ev",   name="SiC MOSFET — 532 nm",
                    material="SiC",           category=CATEGORY_AUTOMOTIVE,
                    ct_value=1.1e-4,          wavelength_nm=532,
                    description="SiC power device for EV / automotive",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         bias_enabled=True,
                    bias_voltage_v=12.0,      bias_compliance_ma=1000.0,
                    cal_temps="25,35,45,55,65,75",
                    cal_settle_s=90.0,        cal_n_avg=200,
                    cal_stability_tol_c=0.15, cal_min_r2=0.90,
                    snr_threshold_db=18.0,    roi_strategy="center50",
                    recommended_objective="10×",
                    af_z_range_um=1500.0,     af_coarse_um=75.0,
                    bilt_gate_bias_v=-8.0,    bilt_gate_pulse_v=-4.0,
                    bilt_drain_bias_v=0.0,    bilt_drain_pulse_v=12.0,
                    analysis_threshold_k=10.0,
                    analysis_fail_peak_k=50.0, analysis_warn_peak_k=25.0,
                    expected_dr_r="3e-5,3e-3",
                    sample_prep_note="Remove lid. Clean die surface with IPA."),
    MaterialProfile(uid="gan_ev",   name="GaN HEMT — 532 nm",
                    material="GaN",           category=CATEGORY_AUTOMOTIVE,
                    ct_value=1.7e-4,          wavelength_nm=532,
                    description="GaN-on-Si power device for EV / automotive",
                    stimulus_freq_hz=1000.0,  stimulus_duty=0.50,
                    tec_enabled=True,         bias_enabled=True,
                    bias_voltage_v=48.0,      bias_compliance_ma=500.0,
                    cal_temps="25,35,45,55,65,75,85",
                    cal_settle_s=90.0,        cal_n_avg=200,
                    cal_stability_tol_c=0.15, cal_min_r2=0.90,
                    snr_threshold_db=18.0,    roi_strategy="center50",
                    recommended_objective="10×",
                    af_z_range_um=1500.0,     af_coarse_um=75.0,
                    bilt_gate_bias_v=-5.0,    bilt_gate_pulse_v=-2.2,
                    bilt_gate_width_us=110.0, bilt_gate_delay_us=5.0,
                    bilt_drain_bias_v=0.0,    bilt_drain_pulse_v=48.0,
                    bilt_drain_width_us=100.0, bilt_drain_delay_us=10.0,
                    analysis_threshold_k=15.0,
                    analysis_fail_peak_k=80.0, analysis_warn_peak_k=40.0,
                    expected_dr_r="5e-5,5e-3",
                    sample_prep_note="Caution: high bias voltage. Verify compliance before powering."),
    # ── IR Camera Profiles ───────────────────────────────────────
    MaterialProfile(uid="si_ir",    name="Silicon IC — IR",
                    material="Silicon",       category=CATEGORY_SEMICONDUCTOR,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="Standard IC thermal imaging via IR camera",
                    stimulus_freq_hz=100.0,   stimulus_duty=0.50,
                    n_frames=32,              accumulation=32,
                    tec_enabled=True,         cal_temps="25,35,45",
                    snr_threshold_db=15.0,    roi_strategy="full",
                    exposure_target_pct=60.0,
                    af_z_range_um=500.0,      af_coarse_um=25.0,
                    dt_range_k=20.0,          recommended_objective="5×",
                    illumination_note="IR mode — no active illumination needed"),
    MaterialProfile(uid="gan_ir",   name="GaN Power — IR",
                    material="GaN",           category=CATEGORY_AUTOMOTIVE,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="GaN power device thermal mapping via IR camera",
                    stimulus_freq_hz=100.0,   stimulus_duty=0.50,
                    n_frames=64,              accumulation=64,
                    tec_enabled=True,         bias_enabled=True,
                    bias_voltage_v=48.0,      bias_compliance_ma=500.0,
                    cal_temps="25,45,65,85",  snr_threshold_db=12.0,
                    roi_strategy="full",      exposure_target_pct=60.0,
                    af_z_range_um=1500.0,     af_coarse_um=75.0,
                    dt_range_k=50.0,          recommended_objective="5×",
                    analysis_threshold_k=20.0, analysis_fail_peak_k=100.0),
    MaterialProfile(uid="sic_ir",   name="SiC Power — IR",
                    material="SiC",           category=CATEGORY_AUTOMOTIVE,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="SiC power device thermal mapping via IR camera",
                    stimulus_freq_hz=100.0,   stimulus_duty=0.50,
                    n_frames=64,              accumulation=64,
                    tec_enabled=True,         bias_enabled=True,
                    bias_voltage_v=12.0,      bias_compliance_ma=1000.0,
                    cal_temps="25,45,65",     snr_threshold_db=12.0,
                    roi_strategy="full",      exposure_target_pct=60.0,
                    dt_range_k=50.0,          recommended_objective="5×",
                    analysis_threshold_k=15.0, analysis_fail_peak_k=80.0),
    MaterialProfile(uid="pcb_ir",   name="PCB — IR",
                    material="FR4",           category=CATEGORY_PCB,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="Board-level thermal survey via IR camera",
                    stimulus_freq_hz=50.0,    stimulus_duty=0.50,
                    n_frames=64,              accumulation=64,
                    tec_enabled=False,        bias_enabled=True,
                    bias_voltage_v=3.3,       bias_compliance_ma=500.0,
                    snr_threshold_db=10.0,    roi_strategy="full",
                    grid_step_um=500.0,       grid_overlap_pct=15.0,
                    exposure_target_pct=60.0,
                    dt_range_k=30.0,          recommended_objective="2×",
                    illumination_note="IR mode — large area, use low magnification"),
    MaterialProfile(uid="led_ir",   name="LED/Laser — IR",
                    material="GaAs",          category=CATEGORY_SEMICONDUCTOR,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="Active LED/laser chip thermal imaging via IR camera",
                    stimulus_freq_hz=200.0,   stimulus_duty=0.50,
                    n_frames=32,              accumulation=32,
                    tec_enabled=True,         bias_enabled=True,
                    bias_voltage_v=3.0,       bias_compliance_ma=200.0,
                    cal_temps="25,35,45",     snr_threshold_db=15.0,
                    roi_strategy="center50",  exposure_target_pct=55.0,
                    dt_range_k=15.0,          recommended_objective="10×",
                    analysis_threshold_k=8.0),
    MaterialProfile(uid="general_ir", name="General — IR Steady State",
                    material="Any",           category=CATEGORY_USER,
                    modality="ir",            ct_value=0.0,
                    wavelength_nm=0,          exposure_us=8333.0,
                    description="General-purpose direct thermal imaging, no lock-in",
                    stimulus_freq_hz=0.0,     stimulus_duty=0.0,
                    n_frames=32,              accumulation=32,
                    tec_enabled=False,        snr_threshold_db=10.0,
                    roi_strategy="full",      exposure_target_pct=65.0,
                    dt_range_k=30.0,          recommended_objective="5×"),
]
