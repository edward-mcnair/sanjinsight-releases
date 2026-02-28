"""
config.py
Loads and provides access to system configuration from config.yaml.
All hardware modules pull their settings from here — no hardcoded values anywhere.
"""

import yaml
import logging
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"


_DEFAULT_CONFIG: dict = {
    "hardware": {
        "camera":          {"driver": "simulated"},
        "fpga":            {"driver": "simulated"},
        "tec_meerstetter": {"driver": "simulated", "port": "COM3"},
        "tec_atec":        {"driver": "simulated", "port": "COM4"},
        "stage":           {"driver": "simulated"},
        "bias":            {"driver": "simulated"},
    },
    "acquisition": {
        "default_n_frames":       16,
        "default_exposure_us":  5000,
        "default_gain_db":         0,
        "inter_phase_delay_s":   0.1,
    },
    "logging": {
        "level":       "INFO",
        "log_to_file": False,
        "log_file":    "logs/microsanj.log",
    },
}


def _write_default_config(path: Path) -> None:
    """Write the bundled default config.yaml so the user has something to edit."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(_DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        logging.getLogger(__name__).info(
            "Generated default config.yaml at %s — edit to match your hardware.", path
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not write default config: %s", exc)


def load_config(path: str = None) -> dict:
    """Load configuration from YAML file.

    Graceful fallback strategy:
      1. Try to load the requested / default config.yaml.
      2. If the file is missing, write a default one and return its contents.
      3. If the file is malformed, log a warning and return the built-in defaults.
    """
    config_file = Path(path) if path else CONFIG_PATH

    if not config_file.exists():
        logging.getLogger(__name__).warning(
            "config.yaml not found at %s — using built-in defaults "
            "and writing a starter file for you to customise.", config_file
        )
        _write_default_config(config_file)
        return _DEFAULT_CONFIG.copy()

    try:
        with open(config_file, "r") as f:
            loaded = yaml.safe_load(f)
        if not isinstance(loaded, dict):
            raise ValueError("YAML root must be a mapping.")
        return loaded
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Failed to parse %s (%s) — falling back to built-in defaults.",
            config_file, exc
        )
        return _DEFAULT_CONFIG.copy()


def setup_logging(cfg: dict):
    """Configure logging based on config settings."""
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    handlers = [logging.StreamHandler()]

    if log_cfg.get("log_to_file"):
        log_file = Path(log_cfg.get("log_file", "logs/microsanj.log"))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# Load once at import time so all modules share the same instance
_config = load_config()
_path   = str(CONFIG_PATH)   # exposed so first_run wizard knows where to write
setup_logging(_config)


def get(section: str) -> dict:
    """Get a top-level config section. e.g. get('hardware')['tec_meerstetter']"""
    return _config.get(section, {})


def reload(path: str = None) -> None:
    """
    Reload config.yaml from disk into the shared _config dict in-place.
    Called after the first-run wizard saves new values so background threads
    pick up the updated COM ports / driver names without a restart.
    """
    global _config, _path
    fresh = load_config(path)
    _config.clear()
    _config.update(fresh)
    if path:
        _path = path
    logging.getLogger(__name__).info("Config reloaded from %s", _path)


# ------------------------------------------------------------------ #
#  User preferences  (separate from hardware config)                  #
#  Stored in ~/.microsanj/preferences.json so they survive           #
#  config.yaml updates and can be written back at runtime.            #
# ------------------------------------------------------------------ #

import json
from pathlib import Path as _Path

_PREFS_PATH = _Path.home() / ".microsanj" / "preferences.json"
_prefs: dict = {}


def _load_prefs() -> dict:
    try:
        if _PREFS_PATH.exists():
            with open(_PREFS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_prefs():
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PREFS_PATH, "w") as f:
            json.dump(_prefs, f, indent=2)
    except Exception:
        pass


_prefs = _load_prefs()


def get_pref(key: str, default=None):
    """Read a user preference.  e.g. get_pref('ui.mode', 'standard')"""
    keys = key.split(".")
    val  = _prefs
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, None)
        if val is None:
            return default
    return val


def set_pref(key: str, value):
    """Write and immediately persist a user preference."""
    keys = key.split(".")
    node = _prefs
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    _save_prefs()

