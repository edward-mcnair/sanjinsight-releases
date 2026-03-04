"""
hardware/hardware_preset_manager.py

Simple named-preset manager for hardware configuration.

Presets are dicts saved to  ~/.microsanj/hw_presets_<scope>.json
where <scope> is e.g.  "fpga"  or  "bias".

Built-in factory presets are merged with saved user presets; user presets
take precedence when names collide.

Usage
-----
    from hardware.hardware_preset_manager import HardwarePresetManager

    mgr = HardwarePresetManager("fpga", factory_presets={...})
    names = mgr.names()          # all preset names (factory + user)
    cfg   = mgr.load("TR Std")   # dict of settings
    mgr.save("My Preset", cfg)   # persist a new preset
    mgr.delete("My Preset")      # remove a saved preset
"""

from __future__ import annotations

import json
import os
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Preset storage directory ──────────────────────────────────────────────────
_PREFS_DIR = os.path.join(os.path.expanduser("~"), ".microsanj")


class HardwarePresetManager:
    """
    Manages named hardware configuration presets.

    Parameters
    ----------
    scope            : identifier string, e.g. "fpga" or "bias"
    factory_presets  : dict of {name: config_dict} built into the app
    """

    def __init__(self, scope: str, factory_presets: dict | None = None):
        self._scope    = scope
        self._factory  = dict(factory_presets or {})
        self._user: dict = {}
        self._path = os.path.join(_PREFS_DIR, f"hw_presets_{scope}.json")
        self._load_user_presets()

    # ── Public API ─────────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        """Return all preset names — factory first, then user-saved."""
        seen: set = set()
        result: list[str] = []
        for name in list(self._factory.keys()) + list(self._user.keys()):
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def get(self, name: str) -> Optional[dict]:
        """Return the preset dict for *name*, or None if not found."""
        return dict(self._user.get(name) or self._factory.get(name) or {}) or None

    def save(self, name: str, config: dict) -> None:
        """Persist a user preset."""
        self._user[name] = dict(config)
        self._write_user_presets()
        log.debug("HardwarePresetManager[%s]: saved preset '%s'", self._scope, name)

    def delete(self, name: str) -> bool:
        """Remove a user preset.  Returns True if it existed."""
        if name in self._user:
            del self._user[name]
            self._write_user_presets()
            log.debug("HardwarePresetManager[%s]: deleted preset '%s'",
                      self._scope, name)
            return True
        return False

    def is_user_preset(self, name: str) -> bool:
        """Return True if *name* was saved by the user (not a factory preset)."""
        return name in self._user

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_user_presets(self):
        try:
            if os.path.isfile(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._user = {k: v for k, v in data.items() if isinstance(v, dict)}
        except Exception as exc:
            log.warning("HardwarePresetManager[%s]: could not load %s — %s",
                        self._scope, self._path, exc)
            self._user = {}

    def _write_user_presets(self):
        try:
            os.makedirs(_PREFS_DIR, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._user, f, indent=2)
        except Exception as exc:
            log.warning("HardwarePresetManager[%s]: could not save %s — %s",
                        self._scope, self._path, exc)


# ── Factory presets ───────────────────────────────────────────────────────────

FPGA_FACTORY_PRESETS = {
    "TR Standard  (1 kHz / 50%)":   {"freq_hz": 1000.0,  "duty_pct": 50.0},
    "High-Speed  (10 kHz / 50%)":   {"freq_hz": 10000.0, "duty_pct": 50.0},
    "Low-Power  (100 Hz / 25%)":    {"freq_hz": 100.0,   "duty_pct": 25.0},
    "Slow Modulation  (10 Hz / 50%)": {"freq_hz": 10.0,  "duty_pct": 50.0},
    "Fast Low-Duty  (10 kHz / 25%)": {"freq_hz": 10000.0, "duty_pct": 25.0},
}

BIAS_FACTORY_PRESETS = {
    "Typical DUT  (1.8 V, 10 mA)":  {"level_v": 1.8,  "compliance_ma": 10.0},
    "Logic  (3.3 V, 50 mA)":        {"level_v": 3.3,  "compliance_ma": 50.0},
    "5V Logic  (5.0 V, 100 mA)":    {"level_v": 5.0,  "compliance_ma": 100.0},
    "LED Test  (2.0 V, 20 mA)":     {"level_v": 2.0,  "compliance_ma": 20.0},
    "Safe Zero  (0.0 V, 1 mA)":     {"level_v": 0.0,  "compliance_ma": 1.0},
}
