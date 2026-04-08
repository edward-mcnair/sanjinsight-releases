"""
hardware/arduino/factory.py

Creates Arduino driver instances from config.yaml.
"""

import importlib
from .base import ArduinoDriver

_DRIVERS = {
    "nano":      ("hardware.arduino.nano_driver",   "ArduinoNanoDriver"),
    "esp32":     ("hardware.arduino.esp32_driver",   "Esp32Driver"),
    "uno":       ("hardware.arduino.nano_driver",   "ArduinoNanoDriver"),
    "simulated": ("hardware.arduino.simulated",      "SimulatedArduino"),
}

_INSTALL_HINTS: dict = {
    "nano": (
        "pip install pyserial\n"
        "Ensure the CH340 USB-serial driver is installed:\n"
        "  Windows: usually auto-installed via Windows Update\n"
        "  macOS:   brew install ch340g-ch34g-ch34x-mac-os-x-driver\n"
        "  Linux:   included in kernel (ch341 module)"
    ),
    "esp32": (
        "pip install pyserial\n"
        "CP2102 driver is usually included with the OS.\n"
        "  If not detected, install from:\n"
        "  https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers"
    ),
    "uno": (
        "pip install pyserial\n"
        "Arduino UNO uses the ATmega16U2 USB-serial bridge.\n"
        "  Driver is included with the Arduino IDE and most OS installs."
    ),
}


def create_arduino(cfg: dict) -> ArduinoDriver:
    """Create and return an ArduinoDriver from the given config dict."""
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown Arduino driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"Arduino driver '{driver_name}' dependencies are not installed.\n"
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
