"""
hardware/cameras/factory.py

Creates the correct camera driver from config.yaml.
The rest of the application imports only this — never a specific driver.

Usage:
    from hardware.cameras.factory import create_camera
    cam = create_camera(config.get("hardware")["camera"])
    cam.open()
    cam.start()

Adding a new camera driver:
    1. Create hardware/cameras/my_driver.py, subclass CameraDriver
    2. Add it to the _DRIVERS dict below
    3. Set  driver: "my_driver"  in config.yaml
    No other files need to change.
"""

import sys
import logging

from .base import CameraDriver

log = logging.getLogger(__name__)

# Registry: config name → (module path, class name)
_DRIVERS = {
    "ni_imaqdx":  ("hardware.cameras.ni_imaqdx",       "NiImaqdxDriver"),
    "pypylon":     ("hardware.cameras.pypylon_driver",   "PylonDriver"),
    "directshow":  ("hardware.cameras.directshow",       "DirectShowDriver"),
    "simulated":   ("hardware.cameras.simulated",        "SimulatedDriver"),
}

# Drivers that only work on Windows
_WINDOWS_ONLY = {"ni_imaqdx", "directshow"}


def create_camera(cfg: dict) -> CameraDriver:
    """
    Instantiate and return a camera driver based on config.

    cfg is the hardware.camera dict from config.yaml, e.g.:
        driver:      "ni_imaqdx"
        camera_name: "cam4"
        exposure_us: 5000
        gain:        0.0

    Raises:
        ValueError  if driver name is not recognised
        ImportError if the driver's dependencies are not installed
    """
    driver_name = cfg.get("driver", "ni_imaqdx")

    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown camera driver '{driver_name}'. "
            f"Available: {available}\n"
            f"Set  driver: <name>  under hardware.camera in config.yaml")


    # Platform guard — Windows-only drivers fall back to simulated on Mac/Linux
    if driver_name in _WINDOWS_ONLY and sys.platform != 'win32':
        log.warning(
            f"Camera driver '{driver_name}' is Windows-only "
            f"(platform: {sys.platform}). Falling back to 'simulated'. "
            "Set  driver: simulated  in config.yaml to suppress this.")
        driver_name = 'simulated'

    module_path, class_name = _DRIVERS[driver_name]

    # Lazy import so missing dependencies only fail for the driver being used
    import importlib
    module = importlib.import_module(module_path)
    cls    = getattr(module, class_name)

    driver = cls(cfg)
    return driver


def list_drivers() -> list:
    """Return the names of all registered drivers."""
    return list(_DRIVERS.keys())
