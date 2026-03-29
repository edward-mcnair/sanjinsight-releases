"""
acquisition/report_presets.py  —  Named report template presets

Save and load report content selections so users can quickly
regenerate reports with consistent settings.

Stored in user preferences via ``config.get_pref / set_pref`` under
the key ``report.presets``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import config as cfg_mod


@dataclass
class ReportPreset:
    """A named report content configuration."""
    name: str
    thermal_map: bool = True
    hotspot_table: bool = True
    measurement_params: bool = True
    device_info: bool = True
    raw_data_summary: bool = False
    verdict_and_recommendations: bool = True
    calibration_details: bool = False
    quality_scorecard: bool = True
    format: str = "pdf"


def _all_presets() -> dict:
    """Return the full presets dict from preferences."""
    return cfg_mod.get_pref("report.presets", {}) or {}


def save_report_preset(preset: ReportPreset) -> None:
    """Persist a preset (overwrites if name exists)."""
    presets = _all_presets()
    presets[preset.name] = asdict(preset)
    cfg_mod.set_pref("report.presets", presets)


def load_report_preset(name: str) -> Optional[ReportPreset]:
    """Load a preset by name, or None if not found."""
    d = _all_presets().get(name)
    if d is None:
        return None
    return ReportPreset(
        name=d.get("name", name),
        thermal_map=d.get("thermal_map", True),
        hotspot_table=d.get("hotspot_table", True),
        measurement_params=d.get("measurement_params", True),
        device_info=d.get("device_info", True),
        raw_data_summary=d.get("raw_data_summary", False),
        verdict_and_recommendations=d.get("verdict_and_recommendations", True),
        calibration_details=d.get("calibration_details", False),
        quality_scorecard=d.get("quality_scorecard", True),
        format=d.get("format", "pdf"),
    )


def list_report_presets() -> List[str]:
    """Return sorted preset names."""
    return sorted(_all_presets().keys())


def delete_report_preset(name: str) -> None:
    """Remove a preset by name."""
    presets = _all_presets()
    presets.pop(name, None)
    cfg_mod.set_pref("report.presets", presets)
