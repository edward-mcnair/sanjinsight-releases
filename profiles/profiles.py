"""
profiles/profiles.py

MaterialProfile — encodes everything needed to configure the system
for a specific material without running a manual calibration.

A profile is the commercial answer to the calibration problem:
Microsanj engineers characterise a material once; technicians select
it from a list and start measuring immediately.

C_T reference values (thermoreflectance coefficient, 1/K) are
wavelength-dependent. All built-in profiles are at 532 nm (green)
unless noted — the most common illumination wavelength for
thermoreflectance systems.

Sources:
  Burzo et al., Int. J. Heat Mass Transfer, 2003
  Rosencwaig et al., J. Appl. Phys., 1985
  Microsanj internal calibration database
"""

from __future__ import annotations
import os, json, time
from dataclasses import dataclass, field, asdict
from typing      import List, Optional, Dict


# ------------------------------------------------------------------ #
#  Industry / category tags                                           #
# ------------------------------------------------------------------ #

CATEGORY_SEMICONDUCTOR  = "Semiconductor / IC"
CATEGORY_PCB            = "Electronics / PCB"
CATEGORY_AUTOMOTIVE     = "Automotive / EV"
CATEGORY_METAL          = "Metal / Thin Film"
CATEGORY_USER           = "User Defined"

# Accent colour per category (used by UI cards, badges, header pills)
CATEGORY_ACCENTS = {
    CATEGORY_SEMICONDUCTOR: "#00d4aa",   # teal
    CATEGORY_PCB:           "#4488ff",   # blue
    CATEGORY_AUTOMOTIVE:    "#cc66ff",   # purple
    CATEGORY_METAL:         "#ffcc44",   # gold
    CATEGORY_USER:          "#ff8844",   # orange
}

# Subtle background tint per category (for selected cards)
CATEGORY_COLORS = {
    CATEGORY_SEMICONDUCTOR: "#0d2a22",
    CATEGORY_PCB:           "#0d1a2a",
    CATEGORY_AUTOMOTIVE:    "#1e0d2a",
    CATEGORY_METAL:         "#2a220d",
    CATEGORY_USER:          "#2a1a0d",
}


@dataclass
class MaterialProfile:
    """
    Complete measurement profile for one material class.

    Selecting a profile does three things automatically:
      1. Sets active_calibration to a uniform C_T map
      2. Suggests camera settings (user can override)
      3. Suggests acquisition settings (user can override)
    """

    # Identity
    uid:          str   = ""
    name:         str   = ""            # e.g. "Silicon — 532 nm"
    material:     str   = ""            # e.g. "Silicon"
    category:     str   = ""            # one of CATEGORY_* above
    industry_tags: List[str] = field(default_factory=list)
    wavelength_nm: int  = 532

    # Thermoreflectance coefficient
    ct_value:     float = 1e-4          # [1/K]  nominal C_T
    ct_min:       float = 0.0           # [1/K]  lower bound (surface variation)
    ct_max:       float = 0.0           # [1/K]  upper bound
    ct_notes:     str   = ""            # e.g. "Varies with doping level"

    # Recommended camera settings
    exposure_us:  float = 5000.0        # µs
    gain_db:      float = 0.0           # dB

    # Recommended acquisition settings
    n_frames:     int   = 32            # frames per cold/hot half
    accumulation: int   = 24            # EMA depth for live mode
    bias_voltage: float = 0.0           # V  (0 = not applicable)

    # Display hints
    dt_range_k:   float = 5.0           # expected ΔT range for colorscale
    description:  str   = ""
    notes:        str   = ""

    # Metadata
    source:       str   = "builtin"     # "builtin" | "user" | "imported"
    created:      float = 0.0
    modified:     float = 0.0

    # ---------------------------------------------------------------- #

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "MaterialProfile":
        p = MaterialProfile()
        for k, v in d.items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> "MaterialProfile":
        with open(path) as f:
            return MaterialProfile.from_dict(json.load(f))

    def make_calibration(self, frame_h: int = 256,
                         frame_w: int = 320):
        """
        Create a uniform CalibrationResult from this profile's C_T value.
        Every pixel gets the same coefficient — no calibration run needed.
        Returns a CalibrationResult ready to assign to active_calibration.
        """
        import numpy as np
        from acquisition.calibration import CalibrationResult

        ct_map = (np.ones((frame_h, frame_w), dtype=np.float32)
                  * self.ct_value)
        mask   = ct_map > 0

        return CalibrationResult(
            ct_map        = ct_map,
            r2_map        = None,
            residual_map  = None,
            mask          = mask,
            n_points      = 0,
            t_min         = 20.0,
            t_max         = 20.0 + self.dt_range_k,
            t_ref         = 20.0,
            frame_h       = frame_h,
            frame_w       = frame_w,
            timestamp     = time.time(),
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S"),
            notes         = f"Profile: {self.name}  C_T={self.ct_value:.3e} K⁻¹",
            valid         = True,
        )

    def __repr__(self):
        return (f"<MaterialProfile {self.name!r}  "
                f"C_T={self.ct_value:.3e}  {self.category}>")


# ------------------------------------------------------------------ #
#  Built-in profile library                                           #
# ------------------------------------------------------------------ #

def _p(**kw) -> MaterialProfile:
    """Shorthand constructor."""
    p = MaterialProfile(**kw)
    if not p.uid:
        p.uid = p.name.lower().replace(" ", "_").replace("/", "_")
    if p.ct_min == 0:
        p.ct_min = p.ct_value * 0.7
    if p.ct_max == 0:
        p.ct_max = p.ct_value * 1.3
    return p


BUILTIN_PROFILES: List[MaterialProfile] = [

    # ================================================================ #
    #  Semiconductor / IC                                               #
    # ================================================================ #

    _p(uid="si_532", name="Silicon — 532 nm",
       material="Silicon", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC", "Electronics / PCB"],
       wavelength_nm=532,
       ct_value=1.5e-4, ct_min=1.2e-4, ct_max=2.0e-4,
       ct_notes="Varies with doping; n-type slightly higher than p-type",
       exposure_us=8000, gain_db=0, n_frames=32, accumulation=24,
       dt_range_k=10,
       description="Crystalline silicon — the most common semiconductor substrate.",
       notes="Use for bare die, flip-chip, and CMOS ICs. "
             "Oxide layers may reduce effective C_T slightly."),

    _p(uid="si_785", name="Silicon — 785 nm",
       material="Silicon", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC"],
       wavelength_nm=785,
       ct_value=3.0e-4, ct_min=2.5e-4, ct_max=3.8e-4,
       ct_notes="Higher C_T at near-IR due to bandgap proximity",
       exposure_us=5000, gain_db=2, n_frames=32, accumulation=24,
       dt_range_k=5,
       description="Silicon at 785 nm — higher sensitivity, preferred for "
                   "fine-pitch or lightly doped devices."),

    _p(uid="gaas_532", name="GaAs — 532 nm",
       material="Gallium Arsenide", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC", "Automotive / EV"],
       wavelength_nm=532,
       ct_value=2.0e-4, ct_min=1.6e-4, ct_max=2.5e-4,
       ct_notes="Sensitive to surface passivation layer",
       exposure_us=6000, gain_db=0, n_frames=28, accumulation=20,
       dt_range_k=8,
       description="Gallium arsenide — III-V RF and power devices.",
       notes="Common in RF power amplifiers, LNAs, and HEMT devices."),

    _p(uid="gan_sic_532", name="GaN-on-SiC — 532 nm",
       material="GaN on SiC", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC", "Automotive / EV"],
       wavelength_nm=532,
       ct_value=1.8e-4, ct_min=1.4e-4, ct_max=2.3e-4,
       ct_notes="C_T dominated by GaN epilayer; SiC substrate contributes at depths",
       exposure_us=7000, gain_db=0, n_frames=40, accumulation=32,
       dt_range_k=20,
       description="GaN HEMT on SiC — high-power RF and power electronics.",
       notes="Used in 5G power amplifiers and EV inverter gate drivers. "
             "High thermal conductivity of SiC substrate aids heat spreading."),

    _p(uid="sic_532", name="Silicon Carbide — 532 nm",
       material="Silicon Carbide (SiC)", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC", "Automotive / EV"],
       wavelength_nm=532,
       ct_value=8.0e-5, ct_min=6.0e-5, ct_max=1.1e-4,
       ct_notes="Lower C_T than Si; requires higher accumulation for good SNR",
       exposure_us=10000, gain_db=4, n_frames=48, accumulation=40,
       dt_range_k=15,
       description="Silicon carbide — wide-bandgap power semiconductor.",
       notes="Core material for EV inverters, charging systems, and industrial "
             "motor drives. High operating temperatures — wider ΔT range expected."),

    _p(uid="ge_532", name="Germanium — 532 nm",
       material="Germanium", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=4.5e-4, ct_min=3.5e-4, ct_max=5.5e-4,
       exposure_us=4000, gain_db=0, n_frames=24, accumulation=20,
       dt_range_k=5,
       description="Germanium — infrared photodetectors, HBT transistors.",
       notes="High C_T makes Ge relatively easy to measure. "
             "Used in SiGe BiCMOS and some photovoltaic applications."),

    _p(uid="inp_532", name="Indium Phosphide — 532 nm",
       material="Indium Phosphide", category=CATEGORY_SEMICONDUCTOR,
       industry_tags=["Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=1.7e-4, ct_min=1.3e-4, ct_max=2.2e-4,
       exposure_us=6000, gain_db=2, n_frames=32, accumulation=24,
       dt_range_k=8,
       description="InP — high-frequency telecom and photonic integrated circuits.",
       notes="Common in 100G+ optical transceivers and laser drivers."),

    # ================================================================ #
    #  Electronics / PCB                                                #
    # ================================================================ #

    _p(uid="cu_trace_532", name="Copper Trace — 532 nm",
       material="Copper", category=CATEGORY_PCB,
       industry_tags=["Electronics / PCB", "Automotive / EV"],
       wavelength_nm=532,
       ct_value=9.0e-5, ct_min=7.0e-5, ct_max=1.2e-4,
       ct_notes="C_T varies with surface finish (bare, OSP, ENIG)",
       exposure_us=4000, gain_db=0, n_frames=24, accumulation=20,
       dt_range_k=10,
       description="PCB copper conductor — trace heating and current crowding.",
       notes="Useful for tracing current paths, identifying resistance hotspots, "
             "and validating copper pour design. ENIG finish gives more stable C_T."),

    _p(uid="fr4_532", name="FR4 Substrate — 532 nm",
       material="FR4 Glass-Epoxy", category=CATEGORY_PCB,
       industry_tags=["Electronics / PCB"],
       wavelength_nm=532,
       ct_value=3.0e-5, ct_min=2.0e-5, ct_max=5.0e-5,
       ct_notes="Low C_T and heterogeneous — higher uncertainty",
       exposure_us=12000, gain_db=6, n_frames=48, accumulation=40,
       dt_range_k=15,
       description="FR4 PCB laminate substrate.",
       notes="Low thermoreflectance signal. Use high accumulation for SNR. "
             "Primarily useful for identifying large thermal gradients."),

    _p(uid="sac305_532", name="SAC305 Solder — 532 nm",
       material="SAC305 Sn-Ag-Cu Solder", category=CATEGORY_PCB,
       industry_tags=["Electronics / PCB", "Automotive / EV"],
       wavelength_nm=532,
       ct_value=7.0e-5, ct_min=5.0e-5, ct_max=9.0e-5,
       ct_notes="Affected by grain structure and surface oxidation",
       exposure_us=5000, gain_db=2, n_frames=32, accumulation=28,
       dt_range_k=20,
       description="SAC305 lead-free solder — BGA joints, QFN pads, reflow.",
       notes="Used for solder joint quality assessment and electromigration "
             "studies. High ΔT range reflects potential for thermal fatigue sites."),

    _p(uid="au_wire_532", name="Gold Bond Wire — 532 nm",
       material="Gold", category=CATEGORY_PCB,
       industry_tags=["Electronics / PCB", "Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=1.2e-4, ct_min=9.0e-5, ct_max=1.6e-4,
       ct_notes="Very stable C_T — gold is an excellent thermoreflectance material",
       exposure_us=3000, gain_db=0, n_frames=20, accumulation=16,
       dt_range_k=5,
       description="Gold bond wire and bond pad metalization.",
       notes="One of the most reliable thermoreflectance materials. "
             "Wire bonding resistance and current distribution studies."),

    _p(uid="ni_532", name="Nickel — 532 nm",
       material="Nickel", category=CATEGORY_PCB,
       industry_tags=["Electronics / PCB"],
       wavelength_nm=532,
       ct_value=6.0e-5, ct_min=4.5e-5, ct_max=8.0e-5,
       exposure_us=5000, gain_db=2, n_frames=28, accumulation=24,
       dt_range_k=8,
       description="Nickel — ENIG surface finish barrier layer, connectors.",
       notes="Thin nickel barrier in ENIG finishes. "
             "C_T is lower than gold; copper underneath contributes at thin layers."),

    # ================================================================ #
    #  Automotive / EV                                                  #
    # ================================================================ #

    _p(uid="al_heatsink_532", name="Aluminum Heatsink — 532 nm",
       material="Aluminum (6061)", category=CATEGORY_AUTOMOTIVE,
       industry_tags=["Automotive / EV", "Electronics / PCB"],
       wavelength_nm=532,
       ct_value=5.0e-5, ct_min=3.5e-5, ct_max=7.0e-5,
       ct_notes="Strongly affected by surface finish — anodized vs bare",
       exposure_us=6000, gain_db=3, n_frames=36, accumulation=32,
       dt_range_k=20,
       description="Aluminum heatsink and cold plate — power module packaging.",
       notes="Used for thermal resistance validation of EV motor controller "
             "and inverter heatsinks. Anodized surfaces give better repeatability."),

    _p(uid="cu_busbar_532", name="Copper Busbar — 532 nm",
       material="Copper Busbar", category=CATEGORY_AUTOMOTIVE,
       industry_tags=["Automotive / EV"],
       wavelength_nm=532,
       ct_value=9.5e-5, ct_min=7.5e-5, ct_max=1.25e-4,
       ct_notes="Bare copper — oxidation will reduce C_T over time",
       exposure_us=4000, gain_db=0, n_frames=24, accumulation=20,
       dt_range_k=15,
       description="Copper busbar — battery packs, inverters, junction boxes.",
       notes="EV battery current distribution validation. "
             "Identify connection resistance hotspots and current crowding "
             "at bolted joints and busbars."),

    _p(uid="sic_power_module_532", name="SiC Power Module — 532 nm",
       material="SiC (power module, packaged)", category=CATEGORY_AUTOMOTIVE,
       industry_tags=["Automotive / EV", "Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=8.5e-5, ct_min=6.5e-5, ct_max=1.1e-4,
       ct_notes="Packaged module — effective C_T includes die attach and substrate",
       exposure_us=9000, gain_db=4, n_frames=48, accumulation=40,
       dt_range_k=30,
       description="SiC MOSFET/diode power module — EV traction inverters.",
       notes="For full EV inverter module characterisation. "
             "High ΔT range — inverter die can reach 150°C+. "
             "Use calibration run if die attach condition is uncertain."),

    _p(uid="tim_532", name="Thermal Interface Material — 532 nm",
       material="TIM (generic)", category=CATEGORY_AUTOMOTIVE,
       industry_tags=["Automotive / EV", "Electronics / PCB"],
       wavelength_nm=532,
       ct_value=2.5e-5, ct_min=1.5e-5, ct_max=4.0e-5,
       ct_notes="Highly variable — strongly recommend per-batch calibration",
       exposure_us=14000, gain_db=6, n_frames=56, accumulation=48,
       dt_range_k=10,
       description="Thermal interface materials — pads, greases, phase-change.",
       notes="Very low thermoreflectance signal. This profile gives approximate "
             "results only. A calibration run is strongly recommended for TIM "
             "characterisation work."),

    # ================================================================ #
    #  Metals / Thin Film                                               #
    # ================================================================ #

    _p(uid="au_film_532", name="Gold Film — 532 nm",
       material="Gold", category=CATEGORY_METAL,
       industry_tags=["Semiconductor / IC", "Electronics / PCB"],
       wavelength_nm=532,
       ct_value=1.1e-4, ct_min=9.0e-5, ct_max=1.4e-4,
       ct_notes="Stable and repeatable — recommended for system validation",
       exposure_us=3000, gain_db=0, n_frames=20, accumulation=16,
       dt_range_k=5,
       description="Gold thin film — MEMS, sensors, RF substrates.",
       notes="Excellent thermoreflectance material. Ideal for system "
             "verification and SNR benchmarking."),

    _p(uid="ag_532", name="Silver — 532 nm",
       material="Silver", category=CATEGORY_METAL,
       industry_tags=["Electronics / PCB"],
       wavelength_nm=532,
       ct_value=1.0e-4, ct_min=8.0e-5, ct_max=1.3e-4,
       ct_notes="Tarnishing degrades C_T over time — measure fresh surfaces",
       exposure_us=3500, gain_db=0, n_frames=24, accumulation=20,
       dt_range_k=5,
       description="Silver — conductive epoxy, silver-sintered die attach."),

    _p(uid="w_532", name="Tungsten — 532 nm",
       material="Tungsten", category=CATEGORY_METAL,
       industry_tags=["Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=3.5e-5, ct_min=2.5e-5, ct_max=5.0e-5,
       ct_notes="Low C_T — high accumulation required",
       exposure_us=8000, gain_db=4, n_frames=48, accumulation=40,
       dt_range_k=10,
       description="Tungsten — VLSI vias, contact plugs, TaN barrier layers.",
       notes="Common in BEOL metallisation. Low signal — ensure good focusing."),

    _p(uid="pt_532", name="Platinum — 532 nm",
       material="Platinum", category=CATEGORY_METAL,
       industry_tags=["Semiconductor / IC"],
       wavelength_nm=532,
       ct_value=4.5e-5, ct_min=3.5e-5, ct_max=6.0e-5,
       exposure_us=7000, gain_db=3, n_frames=40, accumulation=32,
       dt_range_k=8,
       description="Platinum — RTD sensors, MEMS heaters, catalytic devices."),
]

# Build a lookup dict
PROFILE_REGISTRY: Dict[str, MaterialProfile] = {
    p.uid: p for p in BUILTIN_PROFILES
}
