"""
hardware/driver_contract.py

Lightweight driver health-check protocol.

Defines a runtime-checkable Protocol that any hardware driver family can
implement to report SDK/driver installation status, provide install help,
and run a self-test.

This is NOT a base class — it's a protocol that existing factory modules
can adopt incrementally.  The ConnectionHealthPanel can query any object
implementing this interface.

Usage
-----
    from hardware.driver_contract import DriverHealthCheck, check_driver

    status = check_driver("pypylon")
    print(status.installed, status.version, status.install_command)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass
class DriverStatus:
    """Status of a driver/SDK installation."""

    name:            str
    installed:       bool
    version:         str  = ""           # empty if not installed
    install_command: str  = ""           # "pip install pypylon"
    install_url:     str  = ""           # vendor download page
    notes:           str  = ""           # "Windows only", etc.
    platform_ok:     bool = True         # False if wrong OS

    @property
    def summary(self) -> str:
        if not self.platform_ok:
            return f"{self.name}: not supported on this platform"
        if self.installed:
            return f"{self.name}: v{self.version}" if self.version else f"{self.name}: installed"
        return f"{self.name}: NOT INSTALLED"


@dataclass
class SelfTestResult:
    """Result of a driver self-test."""

    passed:  bool
    message: str
    details: dict = field(default_factory=dict)


@runtime_checkable
class DriverHealthCheck(Protocol):
    """Protocol for driver health checks."""

    def detect_driver(self) -> DriverStatus: ...
    def install_help(self) -> str: ...
    def self_test(self, cfg: dict) -> SelfTestResult: ...


# ── Built-in driver checks ─────────────────────────────────────────────────

_DRIVER_CHECKS: dict[str, callable] = {}


def check_driver(driver_key: str) -> DriverStatus:
    """Check installation status for a known driver key.

    Supported keys: ``"pypylon"``, ``"mecom"``, ``"pyvisa"``, ``"nifpga"``,
    ``"thorlabs"``, ``"flir"``, ``"pydp832"``, ``"pyserial"``.
    """
    fn = _DRIVER_CHECKS.get(driver_key)
    if fn:
        return fn()
    return DriverStatus(name=driver_key, installed=False,
                        notes="Unknown driver key")


def check_all_drivers() -> list[DriverStatus]:
    """Check all known driver families. Returns a list of DriverStatus."""
    return [fn() for fn in _DRIVER_CHECKS.values()]


def _register(key: str):
    def decorator(fn):
        _DRIVER_CHECKS[key] = fn
        return fn
    return decorator


@_register("pypylon")
def _check_pypylon() -> DriverStatus:
    try:
        from pypylon import pylon
        ver = ""
        try:
            ver = pylon.GetPylonVersionString() if hasattr(pylon, "GetPylonVersionString") else ""
        except Exception:
            pass
        return DriverStatus(
            name="Basler pylon (pypylon)",
            installed=True, version=ver,
            install_command="pip install pypylon",
            install_url="https://www.baslerweb.com/en-us/downloads/software/",
        )
    except ImportError:
        return DriverStatus(
            name="Basler pylon (pypylon)",
            installed=False,
            install_command="pip install pypylon",
            install_url="https://www.baslerweb.com/en-us/downloads/software/",
            notes="Also install Basler pylon SDK for USB3 Vision driver",
        )


@_register("mecom")
def _check_mecom() -> DriverStatus:
    try:
        import mecom
        ver = getattr(mecom, "__version__", "")
        return DriverStatus(
            name="pyMeCom (Meerstetter)",
            installed=True, version=ver,
            install_command="pip install pyMeCom",
            install_url="https://github.com/meerstetter/pyMeCom",
        )
    except ImportError:
        return DriverStatus(
            name="pyMeCom (Meerstetter)",
            installed=False,
            install_command="pip install pyMeCom",
            install_url="https://github.com/meerstetter/pyMeCom",
        )


@_register("pyvisa")
def _check_pyvisa() -> DriverStatus:
    try:
        import pyvisa
        ver = getattr(pyvisa, "__version__", "")
        return DriverStatus(
            name="pyvisa",
            installed=True, version=ver,
            install_command="pip install pyvisa pyvisa-py",
            install_url="https://pyvisa.readthedocs.io/",
        )
    except ImportError:
        return DriverStatus(
            name="pyvisa",
            installed=False,
            install_command="pip install pyvisa pyvisa-py",
            install_url="https://pyvisa.readthedocs.io/",
            notes="Required for Keithley and VISA Generic instruments",
        )


@_register("nifpga")
def _check_nifpga() -> DriverStatus:
    try:
        import nifpga
        ver = getattr(nifpga, "__version__", "")
        return DriverStatus(
            name="nifpga",
            installed=True, version=ver,
            install_command="pip install nifpga",
            install_url="https://www.ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html",
            notes="Also requires NI-RIO drivers",
        )
    except ImportError:
        return DriverStatus(
            name="nifpga",
            installed=False,
            install_command="pip install nifpga",
            install_url="https://www.ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html",
            notes="Also requires NI-RIO drivers",
        )


@_register("thorlabs")
def _check_thorlabs() -> DriverStatus:
    try:
        import thorlabs_apt_device
        ver = getattr(thorlabs_apt_device, "__version__", "")
        return DriverStatus(
            name="thorlabs-apt-device",
            installed=True, version=ver,
            install_command="pip install thorlabs-apt-device",
            install_url="https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control",
            notes="Also install Thorlabs Kinesis software",
        )
    except ImportError:
        return DriverStatus(
            name="thorlabs-apt-device",
            installed=False,
            install_command="pip install thorlabs-apt-device",
            install_url="https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control",
            notes="Also install Thorlabs Kinesis software for USB drivers",
        )


@_register("flir")
def _check_flir() -> DriverStatus:
    try:
        import PySpin
        ver = ""
        try:
            system = PySpin.System.GetInstance()
            ver = system.GetLibraryVersion()
            system.ReleaseInstance()
            ver = f"{ver.major}.{ver.minor}.{ver.type}.{ver.build}"
        except Exception:
            pass
        return DriverStatus(
            name="FLIR Spinnaker (PySpin)",
            installed=True, version=ver,
            install_command="pip install spinnaker_python",
            install_url="https://www.flir.com/products/spinnaker-sdk/",
        )
    except ImportError:
        return DriverStatus(
            name="FLIR Spinnaker (PySpin)",
            installed=False,
            install_command="pip install spinnaker_python",
            install_url="https://www.flir.com/products/spinnaker-sdk/",
            notes="Wheel ships inside the SDK package",
        )


@_register("pydp832")
def _check_pydp832() -> DriverStatus:
    for mod_name in ("pydp832", "dp832"):
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "")
            return DriverStatus(
                name="pydp832 (Rigol DP832)",
                installed=True, version=ver,
                install_command="pip install pydp832",
                install_url="https://github.com/tspspi/pydp832",
            )
        except ImportError:
            continue
    return DriverStatus(
        name="pydp832 (Rigol DP832)",
        installed=False,
        install_command="pip install pydp832",
        install_url="https://github.com/tspspi/pydp832",
    )


@_register("pyserial")
def _check_pyserial() -> DriverStatus:
    try:
        import serial
        ver = getattr(serial, "VERSION", getattr(serial, "__version__", ""))
        return DriverStatus(
            name="pyserial",
            installed=True, version=ver,
            install_command="pip install pyserial",
        )
    except ImportError:
        return DriverStatus(
            name="pyserial",
            installed=False,
            install_command="pip install pyserial",
            notes="Required for all serial device communication",
        )
