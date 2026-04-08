"""
hardware/fpga/factory.py

Creates FPGA driver instances from config.yaml.
"""

import importlib
from .base import FpgaDriver

_DRIVERS = {
    "ni9637":    ("hardware.fpga.ni9637",    "Ni9637Driver"),
    "bnc745":    ("hardware.fpga.bnc745",    "Bnc745Driver"),
    "tdg7":      ("hardware.fpga.tdg7",      "Tdg7Driver"),
    "simulated": ("hardware.fpga.simulated", "SimulatedFpga"),
}

_INSTALL_HINTS: dict = {
    "ni9637": (
        "pip install nifpga\n"
        "Also install NI-RIO drivers: "
        "https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html"
    ),
    "bnc745": (
        "pip install pyvisa pyvisa-py\n"
        "For GPIB on Windows also install NI-VISA from ni.com.\n"
        "For USB without NI-VISA:  pip install pyvisa-py pyserial\n"
        "BNC 745 USB VID=0x0A33 — check VISA address with NI MAX or "
        "python -c \"import pyvisa; print(pyvisa.ResourceManager().list_resources())\""
    ),
    "tdg7": (
        "pip install pyserial\n"
        "TDG-VII / PT-100 uses STM32 VCP (VID 0483:5740).\n"
        "On Windows install the STM32 Virtual COM Port driver if not "
        "auto-detected."
    ),
}


def create_fpga(cfg: dict) -> FpgaDriver:
    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown FPGA driver '{driver_name}'. Available: {available}")
    module_path, class_name = _DRIVERS[driver_name]
    return _load_driver(driver_name, module_path, class_name)(cfg)


def _load_driver(driver_name: str, module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(driver_name, "Check the hardware documentation.")
        raise ImportError(
            f"FPGA driver '{driver_name}' dependencies are not installed.\n"
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
