"""
hardware/fpga/factory.py

Creates FPGA driver instances from config.yaml.
"""

from .base import FpgaDriver

_DRIVERS = {
    "ni9637":    ("hardware.fpga.ni9637",    "Ni9637Driver"),
    "simulated": ("hardware.fpga.simulated", "SimulatedFpga"),
}


def create_fpga(cfg: dict) -> FpgaDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown FPGA driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(cfg)
