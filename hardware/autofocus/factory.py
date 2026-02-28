"""
hardware/autofocus/factory.py

Creates autofocus driver instances from config.yaml.
Unlike other hardware factories, autofocus also needs references
to the camera and stage drivers — pass them as arguments.
"""

from .base import AutofocusDriver

_DRIVERS = {
    "sweep":      ("hardware.autofocus.sweep",      "SweepAutofocus"),
    "hill_climb": ("hardware.autofocus.hill_climb", "HillClimbAutofocus"),
    "simulated":  ("hardware.autofocus.simulated",  "SimulatedAutofocus"),
}


def create_autofocus(cfg: dict, camera, stage) -> AutofocusDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown autofocus driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(camera, stage, cfg)
