"""
hardware/error_taxonomy.py

Structured error classification for hardware device exceptions.

Maps vendor-specific exceptions (pyserial, pypylon, pyMeCom, pyvisa, etc.)
into a small set of actionable categories, each carrying a user-facing
message, a suggested fix, and machine-readable context for support bundles.

Pure Python — no Qt dependency — so CLI tools can use it too.

Usage
-----
    from hardware.error_taxonomy import classify_error, ErrorCategory

    try:
        tec.connect()
    except Exception as exc:
        dev_err = classify_error(exc, device_uid="meerstetter_tec_1089")
        print(dev_err.category, dev_err.suggested_fix)
"""

from __future__ import annotations

import enum
import errno
import logging
import re
import traceback
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ── Error categories ────────────────────────────────────────────────────────

class ErrorCategory(enum.Enum):
    """Coarse classification of hardware errors."""

    MISSING_DRIVER      = "missing_driver"
    WRONG_DRIVER_VERSION = "wrong_driver_version"
    PERMISSION_DENIED   = "permission_denied"
    DEVICE_BUSY         = "device_busy"
    DEVICE_DISCONNECTED = "device_disconnected"
    TIMEOUT             = "timeout"
    BANDWIDTH_LIMIT     = "bandwidth_limit"
    NETWORK_CONFIG      = "network_config"
    FIRMWARE_MISMATCH   = "firmware_mismatch"
    UNKNOWN             = "unknown"


# ── Structured error ────────────────────────────────────────────────────────

@dataclass
class DeviceError:
    """Structured, actionable description of a hardware error."""

    category:        ErrorCategory
    device_uid:      str   = ""
    message:         str   = ""       # user-facing summary
    suggested_fix:   str   = ""       # actionable steps
    raw_exception:   str   = ""       # original str(exc)
    exception_type:  str   = ""       # e.g. "serial.SerialException"
    support_context: dict  = field(default_factory=dict)

    @property
    def short_message(self) -> str:
        """First line, capped at 120 chars — for status bar / toast."""
        first = self.message.split("\n", 1)[0]
        return first[:120]


# ── Install hints (reused from factory modules) ────────────────────────────

_INSTALL_HINTS: dict[str, str] = {
    "mecom":                  "pip install pyMeCom",
    "pypylon":                "pip install pypylon  (also install Basler pylon SDK)",
    "pylon":                  "Install Basler pylon SDK from baslerweb.com",
    "PySpin":                 "Install FLIR Spinnaker SDK from flir.com",
    "spinnaker":              "Install FLIR Spinnaker SDK from flir.com",
    "pyvisa":                 "pip install pyvisa pyvisa-py",
    "nifpga":                 "pip install nifpga  (also install NI-RIO drivers)",
    "thorlabs_apt_device":    "pip install thorlabs-apt-device  (also install Thorlabs Kinesis)",
    "pydp832":                "pip install pydp832",
    "serial":                 "pip install pyserial",
    "cv2":                    "pip install opencv-python",
    "flirpy":                 "pip install flirpy",
}


# ── Classification engine ───────────────────────────────────────────────────

def classify_error(
    exc: Exception,
    device_uid: str = "",
) -> DeviceError:
    """Classify a hardware exception into an actionable :class:`DeviceError`.

    Parameters
    ----------
    exc : Exception
        The raw vendor exception.
    device_uid : str
        Registry UID of the device (e.g. ``"meerstetter_tec_1089"``).

    Returns
    -------
    DeviceError
    """
    exc_type = type(exc).__qualname__
    exc_mod  = type(exc).__module__ or ""
    exc_str  = str(exc)
    exc_lower = exc_str.lower()

    ctx: dict = {
        "exception_type": f"{exc_mod}.{exc_type}",
        "exception_str":  exc_str[:500],
        "traceback":      traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:],
    }

    # ── ImportError → MISSING_DRIVER ────────────────────────────────────
    if isinstance(exc, ImportError):
        module_name = getattr(exc, "name", "") or ""
        hint = _find_install_hint(module_name, exc_str)
        return DeviceError(
            category=ErrorCategory.MISSING_DRIVER,
            device_uid=device_uid,
            message=f"Required library not installed: {module_name or exc_str}",
            suggested_fix=f"Install the missing package:\n  {hint}" if hint
                          else f"Install the missing dependency and restart.",
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── PermissionError → PERMISSION_DENIED ─────────────────────────────
    if isinstance(exc, PermissionError):
        return DeviceError(
            category=ErrorCategory.PERMISSION_DENIED,
            device_uid=device_uid,
            message=f"Permission denied: {exc_str[:100]}",
            suggested_fix=_permission_fix_hint(exc_str),
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── TimeoutError / socket.timeout → TIMEOUT ────────────────────────
    if isinstance(exc, (TimeoutError,)):
        return DeviceError(
            category=ErrorCategory.TIMEOUT,
            device_uid=device_uid,
            message=f"Communication timeout: {exc_str[:100]}",
            suggested_fix="Check that the device is powered on and connected.\n"
                          "Verify the port/address is correct in Settings.",
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── ConnectionRefusedError → NETWORK_CONFIG ────────────────────────
    if isinstance(exc, ConnectionRefusedError):
        return DeviceError(
            category=ErrorCategory.NETWORK_CONFIG,
            device_uid=device_uid,
            message=f"Connection refused: {exc_str[:100]}",
            suggested_fix="Check IP address and port settings.\n"
                          "Verify the device is on the same network and LAN control is enabled.",
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── OSError with errno → context-dependent ─────────────────────────
    if isinstance(exc, OSError) and exc.errno:
        return _classify_oserror(exc, device_uid, ctx)

    # ── pyserial SerialException ───────────────────────────────────────
    if "SerialException" in exc_type or "serialutil" in exc_mod:
        return _classify_serial(exc, device_uid, exc_str, exc_lower, ctx)

    # ── pypylon GenericException ───────────────────────────────────────
    if "GenericException" in exc_type or "pypylon" in exc_mod or "_genicam" in exc_mod:
        return _classify_pypylon(exc, device_uid, exc_str, exc_lower, ctx)

    # ── pyvisa VisaIOError ─────────────────────────────────────────────
    if "VisaIOError" in exc_type or "pyvisa" in exc_mod:
        return _classify_visa(exc, device_uid, exc_str, exc_lower, ctx)

    # ── MeCom exceptions ───────────────────────────────────────────────
    if "mecom" in exc_mod.lower() or "MeComError" in exc_type:
        return _classify_mecom(exc, device_uid, exc_str, exc_lower, ctx)

    # ── socket errors ──────────────────────────────────────────────────
    if isinstance(exc, (ConnectionError, OSError)) and _is_network_error(exc_lower):
        return DeviceError(
            category=ErrorCategory.NETWORK_CONFIG,
            device_uid=device_uid,
            message=f"Network error: {exc_str[:100]}",
            suggested_fix="Check network cable and IP configuration.\n"
                          "Verify firewall is not blocking the connection.",
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── Version / mismatch keywords ────────────────────────────────────
    if _has_version_mismatch(exc_lower):
        return DeviceError(
            category=ErrorCategory.WRONG_DRIVER_VERSION,
            device_uid=device_uid,
            message=f"Version mismatch: {exc_str[:100]}",
            suggested_fix="Update the driver or SDK to the version required by this application.\n"
                          "Check the installation guide for compatible versions.",
            raw_exception=exc_str,
            exception_type=exc_type,
            support_context=ctx,
        )

    # ── RuntimeError with diagnostic text ──────────────────────────────
    if isinstance(exc, RuntimeError):
        return _classify_runtime(exc, device_uid, exc_str, exc_lower, ctx)

    # ── Fallback → UNKNOWN ─────────────────────────────────────────────
    return DeviceError(
        category=ErrorCategory.UNKNOWN,
        device_uid=device_uid,
        message=f"Unexpected error: {exc_str[:120]}",
        suggested_fix="Check the log for details. If this persists, generate a support bundle\n"
                       "from Help → Generate Support Bundle.",
        raw_exception=exc_str,
        exception_type=exc_type,
        support_context=ctx,
    )


# ── Specialized classifiers ─────────────────────────────────────────────────

def _classify_serial(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify pyserial SerialException variants."""
    if "could not open port" in sl or "filenotfounderror" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED,
            device_uid=uid,
            message=f"Serial port not found: {s[:80]}",
            suggested_fix="Check that the USB cable is connected and the device is powered on.\n"
                          "Use View → Re-scan Hardware to detect the current port.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "access is denied" in sl or "permissionerror" in sl or "eacces" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_BUSY,
            device_uid=uid,
            message=f"Serial port in use: {s[:80]}",
            suggested_fix="Another application may have the port open.\n"
                          "Close other serial terminals (PuTTY, Arduino IDE, etc.) and retry.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "timeout" in sl or "timed out" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT,
            device_uid=uid,
            message=f"Serial timeout: {s[:80]}",
            suggested_fix="Device did not respond. Check power and baud rate settings.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.DEVICE_DISCONNECTED,
        device_uid=uid,
        message=f"Serial error: {s[:100]}",
        suggested_fix="Check USB connection and device power.\n"
                      "Try a different USB port or cable.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


def _classify_pypylon(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify Basler pypylon exceptions."""
    if "timeout" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT,
            device_uid=uid,
            message=f"Camera timeout: {s[:80]}",
            suggested_fix="Camera did not deliver a frame in time.\n"
                          "Check USB cable quality and try a different USB3 port.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "bandwidth" in sl or "insufficient" in sl:
        return DeviceError(
            category=ErrorCategory.BANDWIDTH_LIMIT,
            device_uid=uid,
            message=f"Insufficient USB bandwidth: {s[:80]}",
            suggested_fix="Too many USB devices sharing the same controller.\n"
                          "Move the camera to a dedicated USB3 port (not a hub).\n"
                          "Disconnect other high-bandwidth USB devices.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "access" in sl or "locked" in sl or "exclusively" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_BUSY,
            device_uid=uid,
            message=f"Camera locked by another application: {s[:80]}",
            suggested_fix="Close Basler Pylon Viewer or any other camera application, then retry.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "not found" in sl or "no camera" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED,
            device_uid=uid,
            message=f"Camera not found: {s[:80]}",
            suggested_fix="Check USB cable and power supply.\n"
                          "Verify Basler pylon SDK is installed (pylon Viewer should list the camera).",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN,
        device_uid=uid,
        message=f"Camera error: {s[:100]}",
        suggested_fix="Check the camera connection and pylon SDK installation.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


def _classify_visa(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify pyvisa VisaIOError variants."""
    if "timeout" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT, device_uid=uid,
            message=f"VISA timeout: {s[:80]}",
            suggested_fix="Instrument did not respond. Check power and GPIB/USB/LAN connection.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "not found" in sl or "resource" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
            message=f"VISA resource not found: {s[:80]}",
            suggested_fix="Check the VISA address and verify the instrument is visible in NI MAX.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN, device_uid=uid,
        message=f"VISA error: {s[:100]}",
        suggested_fix="Check instrument connection and pyvisa installation.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


def _classify_mecom(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify Meerstetter MeCom exceptions."""
    if "timeout" in sl or "no response" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT, device_uid=uid,
            message=f"TEC controller timeout: {s[:80]}",
            suggested_fix="Check power to the TEC controller and USB cable.\n"
                          "Verify the COM port and MeCom address in Settings.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "address" in sl:
        return DeviceError(
            category=ErrorCategory.FIRMWARE_MISMATCH, device_uid=uid,
            message=f"MeCom address error: {s[:80]}",
            suggested_fix="The device is responding at a different MeCom address than expected.\n"
                          "Use tools/scan_hardware.py to detect the actual address.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
        message=f"TEC communication error: {s[:100]}",
        suggested_fix="Check USB cable and device power.\n"
                      "Run View → Re-scan Hardware to detect the device.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


def _classify_oserror(
    exc: OSError, uid: str, ctx: dict,
) -> DeviceError:
    """Classify OSError by errno."""
    s = str(exc)
    if exc.errno == errno.EACCES:
        return DeviceError(
            category=ErrorCategory.PERMISSION_DENIED, device_uid=uid,
            message=f"Access denied: {s[:80]}",
            suggested_fix=_permission_fix_hint(s),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if exc.errno == errno.ENOENT:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
            message=f"Device path not found: {s[:80]}",
            suggested_fix="The device port no longer exists. Check USB connection.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if exc.errno == errno.EBUSY:
        return DeviceError(
            category=ErrorCategory.DEVICE_BUSY, device_uid=uid,
            message=f"Device busy: {s[:80]}",
            suggested_fix="Another process has this device open.\n"
                          "Close other applications using the device and retry.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN, device_uid=uid,
        message=f"OS error ({exc.errno}): {s[:80]}",
        suggested_fix="Check the log for details.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


def _classify_runtime(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify RuntimeError by message content."""
    if "not found" in sl or "no device" in sl or "not connected" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
            message=f"{s[:120]}",
            suggested_fix="Verify the device is connected and powered on.\n"
                          "Use View → Re-scan Hardware to detect available devices.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "timeout" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT, device_uid=uid,
            message=f"{s[:120]}",
            suggested_fix="Device communication timed out. Check connection and power.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "version" in sl or "mismatch" in sl:
        return DeviceError(
            category=ErrorCategory.WRONG_DRIVER_VERSION, device_uid=uid,
            message=f"{s[:120]}",
            suggested_fix="Update the driver or SDK to a compatible version.",
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN, device_uid=uid,
        message=f"{s[:120]}",
        suggested_fix="Check the log for details.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_install_hint(module_name: str, exc_str: str) -> str:
    """Look up an install hint for a missing module."""
    for key, hint in _INSTALL_HINTS.items():
        if key in module_name or key in exc_str:
            return hint
    return ""


def _permission_fix_hint(exc_str: str) -> str:
    """Platform-aware permission fix suggestion."""
    import sys
    if sys.platform == "win32":
        return ("Run SanjINSIGHT as Administrator, or check that no other\n"
                "application has the device open.")
    elif sys.platform == "darwin":
        return ("Grant camera/USB access in System Settings → Privacy & Security.\n"
                "If using a serial device, check /dev/tty permissions.")
    else:
        return ("Add your user to the 'dialout' group for serial access:\n"
                "  sudo usermod -aG dialout $USER\n"
                "Then log out and back in.")


def _is_network_error(s: str) -> bool:
    """Heuristic: does the error string look network-related?"""
    return any(kw in s for kw in (
        "connection refused", "network unreachable", "host unreachable",
        "no route to host", "connection reset", "broken pipe",
        "name or service not known", "getaddrinfo failed",
    ))


def _has_version_mismatch(s: str) -> bool:
    """Heuristic: does the error mention version incompatibility?"""
    return bool(re.search(
        r"version\s*(mismatch|incompatib|conflict|not supported)", s
    ))
