"""
config.py
Loads and provides access to system configuration from config.yaml.
All hardware modules pull their settings from here — no hardcoded values anywhere.

User-writable paths
-------------------
When running as a frozen PyInstaller bundle (installed via the Windows installer)
the app cannot write to Program Files.  All mutable files are redirected:

  Windows  : %LOCALAPPDATA%\\Microsanj\\SanjINSIGHT\\
  macOS    : ~/Library/Application Support/Microsanj/SanjINSIGHT/
  Linux    : ~/.local/share/Microsanj/SanjINSIGHT/

When running from source (development) all paths remain next to config.py.
"""

import sys
import yaml
import logging
import logging.handlers
import os
from pathlib import Path


def _user_data_dir() -> Path:
    """
    Returns the per-user writable directory for SanjINSIGHT data (logs, config).

    Frozen (installed app):
      Windows : %LOCALAPPDATA%\\Microsanj\\SanjINSIGHT
      macOS   : ~/Library/Application Support/Microsanj/SanjINSIGHT
      Linux   : ~/.local/share/Microsanj/SanjINSIGHT
    Development (running from source):
      Always  : the project root directory (next to config.py)
    """
    if getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
        elif sys.platform == 'darwin':
            base = Path.home() / 'Library' / 'Application Support'
        else:
            base = Path(os.environ.get(
                'XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        return base / 'Microsanj' / 'SanjINSIGHT'
    return Path(__file__).parent


def _resolve_config_path() -> Path:
    """
    When frozen, config.yaml lives in the user data dir so it is editable
    without admin rights.  On first run the bundled default is copied there
    automatically so the user starts with real hardware settings rather than
    the minimal built-in defaults.
    """
    if getattr(sys, 'frozen', False):
        user_cfg = _user_data_dir() / 'config.yaml'
        if not user_cfg.exists():
            # First run: seed from the bundled config shipped with the installer
            bundled = Path(sys.executable).parent / 'config.yaml'
            try:
                user_cfg.parent.mkdir(parents=True, exist_ok=True)
                if bundled.exists():
                    import shutil
                    shutil.copy2(bundled, user_cfg)
            except Exception:
                pass  # _write_default_config() will handle it if still missing
        return user_cfg
    return Path(__file__).parent / 'config.yaml'


CONFIG_PATH = _resolve_config_path()


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
        # Relative paths are resolved against the user-writable data directory
        # so the app never tries to write logs into read-only Program Files.
        if not log_file.is_absolute():
            log_file = _user_data_dir() / log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # Use RotatingFileHandler so logs never grow without bound.
        # 2 MB per file, 5 rotated backups = 10 MB maximum on disk.
        handlers.append(logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2 * 1024 * 1024, backupCount=5))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# Load once at import time so all modules share the same instance
_config = load_config()
_path   = str(CONFIG_PATH)   # exposed so first_run wizard knows where to write
setup_logging(_config)


def get(section: str, default=None) -> dict:
    """Get a top-level config section. e.g. get('hardware')['tec_meerstetter']

    Mirrors the dict.get(key, default) signature so callers can write:
        config.get('hardware', {})
    """
    return _config.get(section, {} if default is None else default)


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
_prefs_log = logging.getLogger(__name__ + ".prefs")


def _load_prefs() -> dict:
    try:
        if _PREFS_PATH.exists():
            with open(_PREFS_PATH) as f:
                return json.load(f)
    except Exception:
        _prefs_log.exception(
            "Preferences load failed (%s) — using defaults", _PREFS_PATH
        )
    return {}


def _save_prefs():
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PREFS_PATH, "w") as f:
            json.dump(_prefs, f, indent=2)
    except Exception:
        _prefs_log.exception("Preferences save failed (%s)", _PREFS_PATH)


_prefs = _load_prefs()


# ── Preference migration ───────────────────────────────────────────────────────
# Keys removed in v1.1.0 — delete them from persisted preferences so stale
# data does not confuse future code that might reuse the same key names.
_STALE_PREF_KEYS: dict[str, list[str]] = {
    "ai": ["include_quickstart", "include_manual"],
}


def _migrate_prefs() -> None:
    changed = False
    for section, keys in _STALE_PREF_KEYS.items():
        node = _prefs.get(section)
        if not isinstance(node, dict):
            continue
        for k in keys:
            if k in node:
                del node[k]
                _prefs_log.info("Removed stale preference: %s.%s", section, k)
                changed = True
    if changed:
        _save_prefs()


_migrate_prefs()


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

