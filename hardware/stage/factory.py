"""
hardware/stage/factory.py
"""

import importlib
from .base import StageDriver

_DRIVERS = {
    "thorlabs":     ("hardware.stage.thorlabs",     "ThorlabsDriver"),
    "serial_stage": ("hardware.stage.serial_stage", "SerialStageDriver"),
    "simulated":    ("hardware.stage.simulated",    "SimulatedStage"),
    "mpi_prober":   ("hardware.stage.mpi_prober",  "MpiProberDriver"),
}

_INSTALL_HINTS: dict = {
    "thorlabs": (
        "pip install thorlabs-apt-device\n"
        "Also install Thorlabs Kinesis software: "
        "https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control"
    ),
    "serial_stage": "pip install pyserial",
}


def create_stage(cfg: dict) -> StageDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown stage driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"Stage driver '{driver_name}' dependencies are not installed.\n"
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
