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
import threading
from pathlib import Path
from typing import Any


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
        # hybrid | tr_only | ir_only  — governs which imaging modes appear in the UI
        "imaging_system":  "hybrid",
        "camera":          {"driver": "simulated"},
        "fpga":            {"driver": "simulated"},
        "arduino":         {"driver": "simulated", "port": ""},
        "tec_meerstetter": {"driver": "simulated", "port": ""},
        "tec_atec":        {"driver": "simulated", "port": ""},
        "stage":           {"driver": "simulated"},
        "bias":            {"driver": "simulated"},
        # Poll intervals — increase these on slow USB/VM setups (e.g. Parallels)
        # to reduce USB passthrough traffic.  Values in seconds.
        # Default: tec=0.5 s, fpga=0.25 s, bias=0.25 s, stage=0.10 s.
        # Recommended for Parallels: stage_interval_s: 0.5
        "polling": {
            "tec_interval_s":   0.50,
            "fpga_interval_s":  0.25,
            "bias_interval_s":  0.25,
            "stage_interval_s": 0.10,
        },
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


def setup_logging(cfg: dict) -> None:
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


# Load once at import time so all modules share the same instance.
# All access to _config and _prefs is guarded by their respective locks
# so background hardware threads can read while the UI thread writes.
_config = load_config()
_path   = str(CONFIG_PATH)   # exposed so first_run wizard knows where to write
_config_lock = threading.Lock()
setup_logging(_config)


def get(section: str, default=None) -> dict:
    """Get a top-level config section. e.g. get('hardware')['tec_meerstetter']

    Mirrors the dict.get(key, default) signature so callers can write:
        config.get('hardware', {})
    """
    with _config_lock:
        return _config.get(section, {} if default is None else default)


_cam_write_timer = None   # threading.Timer | None
_cam_write_lock = threading.Lock()


def _flush_camera_config_to_disk() -> None:
    """Write the current in-memory camera config to disk (called by debounce timer)."""
    with _config_lock:
        cam_section = dict(
            _config.get("hardware", {}).get("camera", {}))
    try:
        config_file = CONFIG_PATH
        if config_file.exists():
            with open(config_file, "r") as f:
                on_disk = yaml.safe_load(f) or {}
        else:
            on_disk = {}
        on_disk.setdefault("hardware", {}).setdefault("camera", {}).update(cam_section)
        from utils import atomic_write
        atomic_write(
            str(config_file),
            lambda f: yaml.dump(on_disk, f, default_flow_style=False, sort_keys=False),
        )
        logging.getLogger(__name__).debug(
            "Camera config flushed to disk (debounced)")
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Could not persist camera config to disk: %s", exc)


def update_camera_config(updates: dict) -> None:
    """
    Merge *updates* into the in-memory camera config section and schedule
    a debounced write to disk so the settings survive an app restart.

    The in-memory update is synchronous (callers see the change
    immediately).  The disk write is debounced by 500 ms so rapid slider
    adjustments don't block the GUI thread with repeated YAML I/O.

    Only the keys present in *updates* are changed — other hardware settings
    (TEC, FPGA, polling intervals, etc.) are left untouched.

    Example::
        config.update_camera_config({"width": 1280, "height": 720, "fps": 15})
    """
    global _config, _cam_write_timer
    with _config_lock:
        # Update in-memory config (instant — callers see it immediately)
        cam_section = _config.setdefault("hardware", {}).setdefault("camera", {})
        cam_section.update(updates)

    # Debounce the disk write — cancel any pending timer and start a new one.
    with _cam_write_lock:
        if _cam_write_timer is not None:
            _cam_write_timer.cancel()
        _cam_write_timer = threading.Timer(0.5, _flush_camera_config_to_disk)
        _cam_write_timer.daemon = True
        _cam_write_timer.start()


def reload(path: str = None) -> None:
    """
    Reload config.yaml from disk into the shared _config dict in-place.
    Called after the first-run wizard saves new values so background threads
    pick up the updated COM ports / driver names without a restart.
    """
    global _config, _path
    fresh = load_config(path)
    with _config_lock:
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

def _prefs_path() -> _Path:
    """Return the preferences file path, checking multiple locations.

    On Windows the preferred location is ``~/.microsanj/preferences.json``
    (``C:\\Users\\<name>\\.microsanj\\preferences.json``).  If ``Path.home()``
    raises (network homes, enterprise lockdown), we fall back to
    ``%LOCALAPPDATA%\\Microsanj\\preferences.json``.

    To survive reinstalls, if the primary path doesn't exist but the
    fallback does (or vice-versa), we use whichever already has a file.
    This prevents "lost" preferences when the resolution order changes
    between sessions (e.g., running elevated vs normal).
    """
    import os as _os

    candidates: list[_Path] = []

    # Primary: user home directory
    try:
        candidates.append(_Path.home() / ".microsanj" / "preferences.json")
    except Exception:
        pass

    # Fallback: %LOCALAPPDATA% (always available on Windows)
    fallback_base = (
        _os.environ.get("LOCALAPPDATA")
        or _os.environ.get("APPDATA")
        or _os.environ.get("TEMP")
    )
    if fallback_base:
        candidates.append(_Path(fallback_base) / "Microsanj" / "preferences.json")

    # Return the first candidate that already has a file on disk.
    # This ensures we find prefs saved by a previous session that may
    # have resolved to a different path (e.g., elevated vs normal).
    for p in candidates:
        if p.exists():
            return p

    # No existing file — return the first candidate (preferred location).
    return candidates[0] if candidates else _Path(".microsanj") / "preferences.json"


_PREFS_PATH = _prefs_path()
_prefs: dict = {}
_prefs_lock = threading.Lock()
_prefs_log = logging.getLogger(__name__ + ".prefs")
_prefs_log.info("Preferences path: %s (exists: %s)", _PREFS_PATH, _PREFS_PATH.exists())


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


def _save_prefs(snapshot=None):
    """Persist preferences to disk.

    Parameters
    ----------
    snapshot : dict or None
        A frozen copy of ``_prefs`` taken under ``_prefs_lock``.
        If None, falls back to reading ``_prefs`` directly (only safe
        when called at import time before threads exist).
    """
    data = snapshot if snapshot is not None else _prefs
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        from utils import atomic_write_json
        atomic_write_json(str(_PREFS_PATH), data)
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


# ── Auth preference key defaults (Phase D) ──────────────────────────────────
# These keys are written by AdminSetupWizard / Settings → Security (admin only).
# get_pref() returns the default if the key has never been set — no explicit
# registration needed; callers always supply a default.
#
#   auth.require_login                bool  False    Login gate at startup
#   auth.lock_timeout_s               int   1800     Inactivity lock (30 min)
#   auth.supervisor_override_timeout_s int  900      Override revert (15 min)

AUTH_PREF_REQUIRE_LOGIN              = "auth.require_login"
AUTH_PREF_LOCK_TIMEOUT_S             = "auth.lock_timeout_s"
AUTH_PREF_SUPERVISOR_OVERRIDE_TIMEOUT_S = "auth.supervisor_override_timeout_s"

AUTH_DEFAULT_REQUIRE_LOGIN           = False
AUTH_DEFAULT_LOCK_TIMEOUT_S          = 1800
AUTH_DEFAULT_SUPERVISOR_OVERRIDE_S   = 900


# ── Centralised preference defaults & validation ────────────────────────────
#
# One source of truth for default values and type constraints.
#
# get_pref() checks this registry as the *first* fallback before using the
# caller-supplied default.  This means existing call sites that pass their
# own default continue to work unchanged — but if a key is registered here,
# the registry value takes precedence over an omitted (None) default.
#
# Callers are migrated incrementally: once a key is registered, call sites
# can drop their explicit default.
#
# _PREF_VALIDATORS maps keys to a callable(value) → validated_value.
# If validation fails it should raise (ValueError / TypeError); get_pref()
# catches and falls back to the registered default.

_PREF_DEFAULTS: dict[str, Any] = {
    # ── UI ──────────────────────────────────────────────────────────────
    "ui.theme":               "auto",
    "ui.colors":              "standard",
    "ui.workspace":           "standard",
    "ui.license_prompted":    False,
    "ui.save_arrangement":    "ask",       # "ask" | "always" | "never"
    "ui.restore_arrangement": "ask",       # "ask" | "always" | "never"
    "ui.window_arrangement":  None,        # dict — see ui/session_state.py

    # ── Display ─────────────────────────────────────────────────────────
    "display.colormap":       "Thermal Delta",

    # ── Auth ────────────────────────────────────────────────────────────
    "auth.require_login":     AUTH_DEFAULT_REQUIRE_LOGIN,
    "auth.lock_timeout_s":    AUTH_DEFAULT_LOCK_TIMEOUT_S,
    "auth.supervisor_override_timeout_s": AUTH_DEFAULT_SUPERVISOR_OVERRIDE_S,

    # ── Acquisition ─────────────────────────────────────────────────────
    "acquisition.preflight_enabled": True,

    # ── Autofocus ───────────────────────────────────────────────────────
    "autofocus.strategy":     "sweep",
    "autofocus.metric":       "laplacian",
    "autofocus.z_start":      -500.0,
    "autofocus.z_end":        500.0,
    "autofocus.coarse_step":  50.0,
    "autofocus.fine_step":    5.0,
    "autofocus.n_avg":        2,
    "autofocus.settle_ms":    50,
    "autofocus.before_capture": False,

    # ── AutoScan ────────────────────────────────────────────────────────
    "autoscan.last_objective_mag": 10,

    # ── Lab ─────────────────────────────────────────────────────────────
    "lab.require_operator":   False,
    "lab.confirm_at_scan":    False,
    "lab.active_operator":    "",
    "lab.operators":          [],

    # ── AI ──────────────────────────────────────────────────────────────
    "ai.enabled":             False,
    "ai.model_path":          "",
    "ai.n_gpu_layers":        0,
    "ai.persona":             "default",
    "ai.cloud.provider":      "claude",
    "ai.cloud.api_key":       "",
    "ai.cloud.model":         "",
    "ai.ollama.model":        "",

    # ── Updates ─────────────────────────────────────────────────────────
    "updates.auto_check":     True,
    "updates.frequency":      "always",
    "updates.include_prerelease": False,

    # ── Logging ─────────────────────────────────────────────────────────
    "logging.hardware_debug": False,

    # ── Plugins ─────────────────────────────────────────────────────────
    # plugin-specific keys use "plugins.<id>.enabled" / "plugins.<id>.config"
    # — no defaults needed here; get_pref() call sites supply their own.
}


def _validate_bool(v: Any) -> bool:
    """Coerce to bool; reject non-boolean-ish values."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.lower() in ("true", "false", "1", "0"):
        return v.lower() in ("true", "1")
    raise TypeError(f"expected bool, got {type(v).__name__}: {v!r}")


def _validate_positive_int(v: Any) -> int:
    """Coerce to int ≥ 0."""
    v = int(v)
    if v < 0:
        raise ValueError(f"expected non-negative int, got {v}")
    return v


def _validate_positive_float(v: Any) -> float:
    """Coerce to float > 0."""
    v = float(v)
    if v <= 0:
        raise ValueError(f"expected positive float, got {v}")
    return v


def _validate_float(v: Any) -> float:
    """Coerce to float (any sign)."""
    return float(v)


def _validate_str(v: Any) -> str:
    """Coerce to str."""
    if not isinstance(v, str):
        raise TypeError(f"expected str, got {type(v).__name__}: {v!r}")
    return v


def _validate_str_list(v: Any) -> list:
    """Validate a list of strings."""
    if not isinstance(v, list):
        raise TypeError(f"expected list, got {type(v).__name__}")
    return [str(item) for item in v]


def _make_choice_validator(*choices):
    """Return a validator that accepts only the given string values."""
    valid = set(choices)
    def _validate(v: Any) -> str:
        s = str(v)
        if s not in valid:
            raise ValueError(f"expected one of {sorted(valid)}, got {s!r}")
        return s
    return _validate


_PREF_VALIDATORS: dict[str, Any] = {
    # ── UI ──────────────────────────────────────────────────────────────
    "ui.theme":             _make_choice_validator("auto", "dark", "light"),
    "ui.colors":            _make_choice_validator("standard", "deuteranopia",
                                                   "protanopia", "tritanopia"),
    "ui.workspace":         _make_choice_validator("guided", "standard", "expert"),
    "ui.license_prompted":  _validate_bool,
    "ui.save_arrangement":  _make_choice_validator("ask", "always", "never"),
    "ui.restore_arrangement": _make_choice_validator("ask", "always", "never"),
    # ui.window_arrangement is a free-form dict — no validator needed.

    # ── Auth ────────────────────────────────────────────────────────────
    "auth.require_login":   _validate_bool,
    "auth.lock_timeout_s":  _validate_positive_int,
    "auth.supervisor_override_timeout_s": _validate_positive_int,

    # ── Acquisition ─────────────────────────────────────────────────────
    "acquisition.preflight_enabled": _validate_bool,

    # ── Autofocus ───────────────────────────────────────────────────────
    "autofocus.strategy":   _make_choice_validator("sweep", "hillclimb",
                                                    "binary_search"),
    "autofocus.metric":     _make_choice_validator("laplacian", "variance",
                                                    "gradient", "tenengrad"),
    "autofocus.z_start":    _validate_float,
    "autofocus.z_end":      _validate_float,
    "autofocus.coarse_step": _validate_positive_float,
    "autofocus.fine_step":   _validate_positive_float,
    "autofocus.n_avg":       _validate_positive_int,
    "autofocus.settle_ms":   _validate_positive_int,
    "autofocus.before_capture": _validate_bool,

    # ── Lab ─────────────────────────────────────────────────────────────
    "lab.require_operator":  _validate_bool,
    "lab.confirm_at_scan":   _validate_bool,
    "lab.active_operator":   _validate_str,
    "lab.operators":         _validate_str_list,

    # ── AI ──────────────────────────────────────────────────────────────
    "ai.enabled":            _validate_bool,
    "ai.n_gpu_layers":       _validate_positive_int,

    # ── Updates ─────────────────────────────────────────────────────────
    "updates.auto_check":    _validate_bool,
    "updates.frequency":     _make_choice_validator("always", "daily",
                                                     "weekly", "never"),
    "updates.include_prerelease": _validate_bool,

    # ── Logging ─────────────────────────────────────────────────────────
    "logging.hardware_debug": _validate_bool,
}


def get_pref(key: str, default: Any = None) -> Any:
    """Read a user preference.  e.g. get_pref('ui.mode', 'standard')

    Lookup order:
      1. Persisted value in preferences.json (with validation)
      2. Caller-supplied *default*
      3. ``_PREF_DEFAULTS`` registry

    If a persisted value fails validation, a warning is logged and the
    value is treated as absent (falls through to default / registry).
    """
    # Resolve the effective default: caller-supplied wins, then registry.
    effective_default = default if default is not None else _PREF_DEFAULTS.get(key)

    keys = key.split(".")
    with _prefs_lock:
        val = _prefs
        for k in keys:
            if not isinstance(val, dict):
                return effective_default
            val = val.get(k, None)
            if val is None:
                return effective_default

    # Validate if a validator is registered
    validator = _PREF_VALIDATORS.get(key)
    if validator is not None:
        try:
            val = validator(val)
        except (TypeError, ValueError) as exc:
            _prefs_log.warning(
                "Preference %r has invalid persisted value %r: %s — "
                "using default %r", key, val, exc, effective_default)
            return effective_default

    return val


def pref_default(key: str) -> Any:
    """Return the registered default for *key*, or None if not registered.

    Useful for UI widgets that need to show "default" without hardcoding
    the value in the widget itself.
    """
    return _PREF_DEFAULTS.get(key)


def set_pref(key: str, value: Any) -> None:
    """Write and immediately persist a user preference.

    If a validator is registered for *key*, the value is validated before
    writing.  Invalid values raise ValueError / TypeError to the caller
    so UI code can catch and reject the input.
    """
    validator = _PREF_VALIDATORS.get(key)
    if validator is not None:
        value = validator(value)   # raises on invalid — caller should handle

    keys = key.split(".")
    with _prefs_lock:
        node = _prefs
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        import copy
        snapshot = copy.deepcopy(_prefs)
    # Serialize outside the lock — the snapshot is an independent copy,
    # so concurrent set_pref() calls can proceed without blocking on I/O.
    _save_prefs(snapshot)

