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
