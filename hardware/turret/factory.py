"""
hardware/turret/factory.py

Factory function for creating an ObjectiveTurretDriver from config.
"""

from __future__ import annotations
import importlib
import logging

log = logging.getLogger(__name__)

_DRIVERS: dict[str, tuple[str, str]] = {
    "olympus_linx": ("hardware.turret.olympus_linx", "OlympusLinxTurret"),
    "simulated":    ("hardware.turret.simulated",    "SimulatedTurret"),
}


def create_turret(cfg: dict):
    """
    Create and return an ObjectiveTurretDriver from config.

    cfg must contain a 'driver' key matching a registered driver name.
    All other keys are passed to the driver constructor.

    Returns:
        ObjectiveTurretDriver instance (not yet connected).
    Raises:
        ValueError  — unknown driver name
        ImportError — driver dependency not installed
    """
    driver_name = cfg.get("driver", "simulated").lower()
    if driver_name not in _DRIVERS:
        raise ValueError(
            f"Unknown turret driver '{driver_name}'.  "
            f"Available: {list(_DRIVERS.keys())}")

    module_path, class_name = _DRIVERS[driver_name]
    try:
        module = importlib.import_module(module_path)
        cls    = getattr(module, class_name)
    except ImportError as e:
        raise ImportError(
            f"Could not import turret driver '{driver_name}': {e}\n"
            f"Check that all required packages are installed.") from e

    log.debug("Creating turret driver: %s", class_name)
    return cls(cfg)
