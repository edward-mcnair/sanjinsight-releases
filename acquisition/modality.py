"""
acquisition/modality.py

ImagingModality — defines the distinct measurement techniques supported
by Microsanj instruments, each with its own signal chain, calibration
model, and output data shape.

Modality         Instrument       Signal chain           Output shape
---------------- ---------------- ---------------------- ---------------
THERMOREFLECT.   SanjSCOPE/NT220  ΔR/R = C_T × ΔT       2D (H × W)
IR_LOCKIN        irSCOPE          Radiance → Planck → T  2D (H × W)
HYBRID           SanjSCOPE dual   TR + IR co-registered  2D × 2 channels
OPP              OPP system       TR at N delay steps     3D (H × W × N)

Usage
-----
    from acquisition.modality import ImagingModality, MODALITY_INFO

    session.meta.imaging_mode = ImagingModality.THERMOREFLECTANCE.value
    info = MODALITY_INFO[ImagingModality.THERMOREFLECTANCE]
    print(info.display_name)          # "Thermoreflectance (TR)"
    print(info.calibration_model)     # "ΔR/R = C_T × ΔT"
    print(info.requires_ct_map)       # True
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass


class ImagingModality(str, Enum):
    """Measurement modality tag stored in every SessionMeta."""
    THERMOREFLECTANCE = "thermoreflectance"
    IR_LOCKIN         = "ir_lockin"
    HYBRID            = "hybrid"
    OPP               = "opp"
    UNKNOWN           = "unknown"

    @classmethod
    def from_str(cls, s: str) -> "ImagingModality":
        """Parse a string, defaulting to UNKNOWN for unrecognised values."""
        try:
            return cls(s.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


@dataclass(frozen=True)
class ModalityInfo:
    """Human-readable metadata about a modality."""
    display_name:        str
    short_name:          str       # Used in UI badges / tab labels
    calibration_model:   str       # Equation or description
    requires_ct_map:     bool      # True → needs per-pixel C_T calibration
    requires_emissivity: bool      # True → needs IR emissivity calibration
    output_dimensions:   int       # 2 for 2D maps, 3 for time-resolved cubes
    output_description:  str
    instrument_examples: str
    accent_color:        str       # Hex colour used in UI


MODALITY_INFO: dict[ImagingModality, ModalityInfo] = {
    ImagingModality.THERMOREFLECTANCE: ModalityInfo(
        display_name        = "Thermoreflectance (TR)",
        short_name          = "TR",
        calibration_model   = "ΔR/R = C_T × ΔT  (per-pixel linear fit)",
        requires_ct_map     = True,
        requires_emissivity = False,
        output_dimensions   = 2,
        output_description  = "2D ΔT map  (H × W, float32, °C)",
        instrument_examples = "SanjSCOPE, NT220, EZ-THERM",
        accent_color        = "#00d4aa",
    ),
    ImagingModality.IR_LOCKIN: ModalityInfo(
        display_name        = "Infrared Lock-In (IR)",
        short_name          = "IR",
        calibration_model   = "Radiance → Temperature via Planck's law + emissivity",
        requires_ct_map     = False,
        requires_emissivity = True,
        output_dimensions   = 2,
        output_description  = "2D ΔT map  (H × W, float32, °C)",
        instrument_examples = "irSCOPE",
        accent_color        = "#ff8844",
    ),
    ImagingModality.HYBRID: ModalityInfo(
        display_name        = "Hybrid TR + IR (Dual-Mode)",
        short_name          = "HYBRID",
        calibration_model   = "TR channel: C_T map;  IR channel: Planck + emissivity",
        requires_ct_map     = True,
        requires_emissivity = True,
        output_dimensions   = 2,
        output_description  = "2D ΔT maps × 2 co-registered channels",
        instrument_examples = "SanjSCOPE (dual-mode)",
        accent_color        = "#aa55ff",
    ),
    ImagingModality.OPP: ModalityInfo(
        display_name        = "Optical Pump-Probe (OPP)",
        short_name          = "OPP",
        calibration_model   = "ΔR/R = C_T × ΔT  at each pump-probe delay step",
        requires_ct_map     = True,
        requires_emissivity = False,
        output_dimensions   = 3,
        output_description  = "3D ΔT cube  (H × W × N_delays, float32, °C)",
        instrument_examples = "OPP system, PS700",
        accent_color        = "#4488ff",
    ),
    ImagingModality.UNKNOWN: ModalityInfo(
        display_name        = "Unknown",
        short_name          = "?",
        calibration_model   = "Not specified",
        requires_ct_map     = False,
        requires_emissivity = False,
        output_dimensions   = 2,
        output_description  = "Unspecified",
        instrument_examples = "",
        accent_color        = "#666666",
    ),
}


def get_info(modality: ImagingModality | str) -> ModalityInfo:
    """Return ModalityInfo for a modality (accepts enum or string)."""
    if isinstance(modality, str):
        modality = ImagingModality.from_str(modality)
    return MODALITY_INFO.get(modality, MODALITY_INFO[ImagingModality.UNKNOWN])


def all_modalities() -> list[ImagingModality]:
    """Return all modalities except UNKNOWN, in display order."""
    return [
        ImagingModality.THERMOREFLECTANCE,
        ImagingModality.IR_LOCKIN,
        ImagingModality.HYBRID,
        ImagingModality.OPP,
    ]
