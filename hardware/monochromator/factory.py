"""
hardware/monochromator/factory.py

Creates monochromator driver instances from config.yaml entries.

Expected config shape (under hardware.monochromator)
-----------------------------------------------------
    enabled:  true
    driver:   "simulated"    # "simulated" | "cornerstone"
    port:     "COM5"         # serial port for cornerstone driver
    baudrate: 9600           # optional; defaults to 9600

Usage
-----
    from hardware.monochromator.factory import build_monochromator
    driver = build_monochromator(cfg.get("hardware", {}).get("monochromator", {}))
    if driver:
        driver.connect()
"""

import importlib
import logging

from .base import MonochromatorDriver

log = logging.getLogger(__name__)

# Registry: driver key → (module path, class name)
_DRIVERS: dict[str, tuple[str, str]] = {
    "simulated":   ("hardware.monochromator.simulated",   "SimulatedMonochromator"),
    "cornerstone": ("hardware.monochromator.cornerstone",  "CornerstoneMonochromator"),
}

_INSTALL_HINTS: dict[str, str] = {
    "cornerstone": (
        "pip install pyserial\n"
        "Newport Cornerstone communicates over RS-232.  pyserial provides the "
        "serial port interface.\n"
        "After installing, restart the application."
    ),
}


def build_monochromator(cfg: dict) -> MonochromatorDriver | None:
    """
    Instantiate and return a monochromator driver from the given config dict.

    Parameters
    ----------
    cfg:
        Dictionary corresponding to the ``hardware.monochromator`` section of
        config.yaml.

    Returns
    -------
    MonochromatorDriver
        A ready-to-``connect()`` driver instance.
    None
        If ``cfg["enabled"]`` is falsy or ``cfg`` is empty / ``None``.

    Raises
    ------
    ValueError
        If ``cfg["driver"]`` names an unknown driver.
    ImportError
        If the driver's required dependencies are not installed.
    RuntimeError
        If the driver module cannot be loaded for reasons other than a missing
        dependency.
    """
    if not cfg:
        return None
    if not cfg.get("enabled", True):
        log.debug("Monochromator disabled in config — skipping")
        return None

    driver_name = cfg.get("driver", "simulated")
    if driver_name not in _DRIVERS:
        available = ", ".join(f'"{k}"' for k in _DRIVERS)
        raise ValueError(
            f"Unknown monochromator driver {driver_name!r}. "
            f"Available: {available}"
        )

    module_path, class_name = _DRIVERS[driver_name]
    driver_cls = _load_driver(driver_name, module_path, class_name)

    # Build constructor kwargs from the relevant config keys
    if driver_name == "simulated":
        instance = driver_cls(cfg)
    elif driver_name == "cornerstone":
        instance = driver_cls(
            port=cfg.get("port", "COM5"),
            baudrate=int(cfg.get("baudrate", 9600)),
            timeout=float(cfg.get("timeout", 10.0)),
        )
    else:
        # Fallback: pass the full cfg dict and let the driver sort it out
        instance = driver_cls(cfg)

    log.debug(
        "Monochromator driver instantiated: %s", instance.__class__.__name__)
    return instance


def _load_driver(driver_name: str, module_path: str, class_name: str):
    """Import the driver module and return its class, with helpful errors."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(
            driver_name,
            "Check the hardware documentation or contact Microsanj support.",
        )
        raise ImportError(
            f"Monochromator driver {driver_name!r} dependencies are not installed.\n"
            f"Error:  {exc}\n"
            f"Fix:    {hint}"
        ) from exc

    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise RuntimeError(
            f"Driver module {module_path!r} does not export {class_name!r}. "
            f"The driver file may be corrupted or the wrong version."
        ) from exc
