"""
hardware/ldd/factory.py

Creates LDD driver instances from config.yaml entries.

Usage:
    from hardware.ldd.factory import create_ldd
    ldd = create_ldd(config["hardware"]["ldd_meerstetter"])
    ldd.connect()
"""

import importlib
from .base import LddDriver

_DRIVERS = {
    "meerstetter_ldd1121": (
        "hardware.ldd.meerstetter_ldd1121", "MeerstetterLdd1121"),
    "simulated": (
        "hardware.ldd.simulated", "SimulatedLdd"),
}

_INSTALL_HINTS: dict = {
    "meerstetter_ldd1121": "pip install pyMeCom",
}


def create_ldd(cfg: dict) -> LddDriver:
    """Instantiate an LDD driver from a config dict.

    The ``cfg`` dict must contain at minimum ``{"driver": "meerstetter_ldd1121"}``
    (or ``"simulated"``).  Additional keys (``port``, ``address``, ``timeout``)
    are passed through to the driver constructor.
    """
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown LDD driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name,
                                  "Check the hardware documentation.")
        raise ImportError(
            f"LDD driver '{driver_name}' dependencies are not installed.\n"
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
