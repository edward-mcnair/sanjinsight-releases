"""
hardware/bias/factory.py

Creates bias source driver instances from config.yaml.
"""

import importlib
from .base import BiasDriver

_DRIVERS = {
    "keithley":     ("hardware.bias.keithley",     "KeithleyDriver"),
    "visa_generic": ("hardware.bias.visa_generic",  "VisaGenericDriver"),
    "rigol_dp832":  ("hardware.bias.rigol_dp832",   "RigolDP832Driver"),
    "simulated":    ("hardware.bias.simulated",     "SimulatedBias"),
}

_INSTALL_HINTS: dict = {
    "keithley": (
        "pip install pyvisa pyvisa-py\n"
        "Or use the dcps library (wraps pyvisa with Keithley-specific commands):\n"
        "  pip install dcps  —  https://github.com/sgoadhouse/dcps"
    ),
    "visa_generic": (
        "pip install pyvisa pyvisa-py\n"
        "Or install NI-VISA: "
        "https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html\n"
        "Tip: for Rigol DP832 without NI-VISA, use driver: 'rigol_dp832' instead."
    ),
    "rigol_dp832": (
        "pip install pydp832\n"
        "GitHub: https://github.com/tspspi/pydp832\n"
        "Or use driver: 'visa_generic' with pyvisa if NI-VISA is already installed."
    ),
}


def create_bias(cfg: dict) -> BiasDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown bias driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"Bias driver '{driver_name}' dependencies are not installed.\n"
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
