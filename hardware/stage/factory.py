"""
hardware/stage/factory.py
"""

from .base import StageDriver

_DRIVERS = {
    "thorlabs":     ("hardware.stage.thorlabs",     "ThorlabsDriver"),
    "serial_stage": ("hardware.stage.serial_stage", "SerialStageDriver"),
    "simulated":    ("hardware.stage.simulated",    "SimulatedStage"),
}


def create_stage(cfg: dict) -> StageDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown stage driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(cfg)
