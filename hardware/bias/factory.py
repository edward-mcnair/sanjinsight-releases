"""
hardware/bias/factory.py

Creates bias source driver instances from config.yaml.
"""

from .base import BiasDriver

_DRIVERS = {
    "keithley":     ("hardware.bias.keithley",     "KeithleyDriver"),
    "visa_generic": ("hardware.bias.visa_generic",  "VisaGenericDriver"),
    "simulated":    ("hardware.bias.simulated",     "SimulatedBias"),
}


def create_bias(cfg: dict) -> BiasDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown bias driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(cfg)
