"""
hardware/tec/factory.py

Creates TEC driver instances from config.yaml entries.

Usage:
    from hardware.tec.factory import create_tec
    tec = create_tec(config.get("hardware")["tec_meerstetter"])
    tec.connect()
"""

from .base import TecDriver

_DRIVERS = {
    "meerstetter": ("hardware.tec.meerstetter", "MeerstetterDriver"),
    "atec":        ("hardware.tec.atec",         "AtecDriver"),
    "simulated":   ("hardware.tec.simulated",     "SimulatedTec"),
}


def create_tec(cfg: dict) -> TecDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown TEC driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(cfg)
