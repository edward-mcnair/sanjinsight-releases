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

    # Thermoreflectance coefficient (dR/R per kelvin)
    ct_value:       float = 1.5e-4   # K⁻¹ — typical GaAs at 532 nm
    wavelength_nm:  int   = 532      # illumination wavelength

    # Recommended acquisition settings
    exposure_us:    float = 5000.0
    gain_db:        float = 0.0
    n_frames:       int   = 16
    accumulation:   int   = 16

    # Display / analysis helpers
    dt_range_k:     float = 10.0   # expected ΔT range (for display scaling)

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
                    description="Crystalline silicon, green illumination"),
    MaterialProfile(uid="gaas_532", name="GaAs — 532 nm",
                    material="GaAs",          category=CATEGORY_SEMICONDUCTOR,
                    ct_value=2.0e-4,          wavelength_nm=532,
                    description="Gallium arsenide, green illumination"),
    MaterialProfile(uid="gan_532",  name="GaN — 532 nm",
                    material="GaN",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.8e-4,          wavelength_nm=532,
                    description="Gallium nitride, green illumination"),
    MaterialProfile(uid="inp_532",  name="InP — 532 nm",
                    material="InP",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=2.5e-4,          wavelength_nm=532,
                    description="Indium phosphide, green illumination"),
    MaterialProfile(uid="sic_532",  name="SiC — 532 nm",
                    material="SiC",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.2e-4,          wavelength_nm=532,
                    description="Silicon carbide, green illumination"),
    # ── Semiconductors — 785 nm ────────────────────────────────────
    MaterialProfile(uid="si_785",   name="Silicon — 785 nm",
                    material="Silicon",       category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.0e-4,          wavelength_nm=785,
                    description="Crystalline silicon, NIR illumination"),
    MaterialProfile(uid="gaas_785", name="GaAs — 785 nm",
                    material="GaAs",          category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.4e-4,          wavelength_nm=785,
                    description="Gallium arsenide, NIR illumination"),
    MaterialProfile(uid="gan_785",  name="GaN — 785 nm",
                    material="GaN",           category=CATEGORY_SEMICONDUCTOR,
                    ct_value=1.3e-4,          wavelength_nm=785,
                    description="Gallium nitride, NIR illumination"),
    # ── Metals — 532 nm ───────────────────────────────────────────
    MaterialProfile(uid="cu_532",   name="Copper — 532 nm",
                    material="Copper",        category=CATEGORY_METAL,
                    ct_value=0.8e-4,          wavelength_nm=532,
                    description="Bulk copper, green illumination"),
    MaterialProfile(uid="au_532",   name="Gold — 532 nm",
                    material="Gold",          category=CATEGORY_METAL,
                    ct_value=1.2e-4,          wavelength_nm=532,
                    description="Gold film or bulk, green illumination"),
    MaterialProfile(uid="al_532",   name="Aluminum — 532 nm",
                    material="Aluminum",      category=CATEGORY_METAL,
                    ct_value=0.5e-4,          wavelength_nm=532,
                    description="Aluminum film or bulk, green illumination"),
    # ── Metals — 785 nm ───────────────────────────────────────────
    MaterialProfile(uid="cu_785",   name="Copper — 785 nm",
                    material="Copper",        category=CATEGORY_METAL,
                    ct_value=0.6e-4,          wavelength_nm=785,
                    description="Bulk copper, NIR illumination"),
    # ── PCB / packaging ───────────────────────────────────────────
    MaterialProfile(uid="fr4_532",  name="FR4 — 532 nm",
                    material="FR4",           category=CATEGORY_PCB,
                    ct_value=0.3e-4,          wavelength_nm=532,
                    description="Standard PCB substrate, green illumination"),
    MaterialProfile(uid="cuw_532",  name="Cu/W composite — 532 nm",
                    material="Cu/W",          category=CATEGORY_PCB,
                    ct_value=0.7e-4,          wavelength_nm=532,
                    description="Copper-tungsten heat spreader, green illumination"),
    # ── Automotive / EV ───────────────────────────────────────────
    MaterialProfile(uid="sic_ev",   name="SiC MOSFET — 532 nm",
                    material="SiC",           category=CATEGORY_AUTOMOTIVE,
                    ct_value=1.1e-4,          wavelength_nm=532,
                    description="SiC power device for EV / automotive"),
    MaterialProfile(uid="gan_ev",   name="GaN HEMT — 532 nm",
                    material="GaN",           category=CATEGORY_AUTOMOTIVE,
                    ct_value=1.7e-4,          wavelength_nm=532,
                    description="GaN-on-Si power device for EV / automotive"),
]
