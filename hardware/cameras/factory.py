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
    "flir":        ("hardware.cameras.flir_driver",      "FlirDriver"),
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
    cls = _load_driver(driver_name, module_path, class_name)
    return cls(cfg)


def list_drivers() -> list:
    """Return the names of all registered drivers."""
    return list(_DRIVERS.keys())


# ---------------------------------------------------------------------------
# Install hints shown when a driver's dependencies are missing.
# ---------------------------------------------------------------------------
_INSTALL_HINTS: dict[str, str] = {
    "pypylon": (
        "pip install pypylon\n"
        "Also install the Basler Pylon SDK: "
        "https://www.baslerweb.com/en/downloads/software-downloads/"
    ),
    "ni_imaqdx": (
        "Install NI Vision Acquisition Software (Windows only).\n"
        "Download from: https://www.ni.com/en/support/downloads/drivers/"
        "download.ni-vision-acquisition-software.html"
    ),
    "directshow": (
        "DirectShow is built into Windows — no extra install required.\n"
        "Make sure you are running on Windows and your camera has a WDM driver."
    ),
    "flir": (
        "pip install spinnaker_python\n"
        "Also install the FLIR Spinnaker SDK (cross-platform):\n"
        "  https://www.flir.com/products/spinnaker-sdk/\n"
        "The spinnaker_python wheel is distributed alongside the SDK installer."
    ),
}


def _load_driver(driver_name: str, module_path: str, class_name: str):
    """Import *module_path* and return *class_name*, with actionable errors."""
    import importlib
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"Camera driver '{driver_name}' dependencies are not installed.\n"
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
