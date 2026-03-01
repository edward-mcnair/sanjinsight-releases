"""
hardware/tec/factory.py

Creates TEC driver instances from config.yaml entries.

Usage:
    from hardware.tec.factory import create_tec
    tec = create_tec(config.get("hardware")["tec_meerstetter"])
    tec.connect()
"""

import importlib
from .base import TecDriver

_DRIVERS = {
    "meerstetter": ("hardware.tec.meerstetter", "MeerstetterDriver"),
    "atec":        ("hardware.tec.atec",         "AtecDriver"),
    "simulated":   ("hardware.tec.simulated",     "SimulatedTec"),
}

_INSTALL_HINTS: dict = {
    "meerstetter": "pip install pyMeCom",
    "atec":        "pip install pyserial",
}


def create_tec(cfg: dict) -> TecDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown TEC driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"TEC driver '{driver_name}' dependencies are not installed.\n"
            f"Error: {exc}\n"
            f"Fix:   {hint}"
        ) from exc
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise RuntimeError(
            f"Driver module '{module_path}' does not export '{class_name}'. "
            f"The driver file may be corrupted or the wrong version."
        ) from exc
