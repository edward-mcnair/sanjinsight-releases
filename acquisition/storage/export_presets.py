"""
acquisition/export_presets.py  —  Named export configuration presets

Save and load export format selections + spatial calibration so users
don't have to re-configure every time.

Stored in user preferences via ``config.get_pref / set_pref`` under
the key ``export.presets``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import config as cfg_mod


@dataclass
class ExportPreset:
    """A named export configuration."""
    name: str
    formats: List[str]       # ExportFormat .value strings, e.g. ["tiff","csv"]
    px_per_um: float = 0.0


def _all_presets() -> dict:
    """Return the full presets dict from preferences."""
    return cfg_mod.get_pref("export.presets", {}) or {}


def save_preset(preset: ExportPreset) -> None:
    """Persist a preset (overwrites if name exists)."""
    presets = _all_presets()
    presets[preset.name] = asdict(preset)
    cfg_mod.set_pref("export.presets", presets)


def load_preset(name: str) -> Optional[ExportPreset]:
    """Load a preset by name, or None if not found."""
    d = _all_presets().get(name)
    if d is None:
        return None
    return ExportPreset(
        name=d.get("name", name),
        formats=d.get("formats", []),
        px_per_um=d.get("px_per_um", 0.0),
    )


def list_presets() -> List[str]:
    """Return sorted preset names."""
    return sorted(_all_presets().keys())


def delete_preset(name: str) -> None:
    """Remove a preset by name."""
    presets = _all_presets()
    presets.pop(name, None)
    cfg_mod.set_pref("export.presets", presets)
