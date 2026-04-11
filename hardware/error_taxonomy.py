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


# ── Error domain (broad classification) ─────────────────────────────────────

class ErrorDomain(enum.Enum):
    """Which subsystem produced the error."""

    HARDWARE     = "hardware"        # connection, communication, driver
    CONFIG       = "config"          # validation, incompatible settings
    ACQUISITION  = "acquisition"     # pipeline state, workflow preconditions
    PERSISTENCE  = "persistence"     # save/load, filesystem, schema
    AI           = "ai"              # model/provider, parse, auth
    ENVIRONMENT  = "environment"     # OS, deps, permissions, resources


# ── Error categories ────────────────────────────────────────────────────────

class ErrorCategory(enum.Enum):
    """Specific classification of the error within its domain."""

    # Hardware (domain=HARDWARE)
    MISSING_DRIVER      = "missing_driver"
    WRONG_DRIVER_VERSION = "wrong_driver_version"
    PERMISSION_DENIED   = "permission_denied"
    DEVICE_BUSY         = "device_busy"
    DEVICE_DISCONNECTED = "device_disconnected"
    TIMEOUT             = "timeout"
    BANDWIDTH_LIMIT     = "bandwidth_limit"
    NETWORK_CONFIG      = "network_config"
    FIRMWARE_MISMATCH   = "firmware_mismatch"
    DEVICE_COMM_ERROR   = "device_comm_error"       # transient read/write failure

    # Config / validation (domain=CONFIG)
    INVALID_SETTING     = "invalid_setting"
    INCOMPATIBLE_CONFIG = "incompatible_config"
    MISSING_PARAMETER   = "missing_parameter"

    # Acquisition / workflow (domain=ACQUISITION)
    PRECONDITION_FAILED = "precondition_failed"
    PIPELINE_CONFLICT   = "pipeline_conflict"
    OPERATION_CANCELED  = "operation_canceled"

    # Persistence / filesystem (domain=PERSISTENCE)
    SAVE_FAILED         = "save_failed"
    LOAD_FAILED         = "load_failed"
    FILE_PERMISSION     = "file_permission"
    CORRUPT_FILE        = "corrupt_file"
    SCHEMA_REJECTED     = "schema_rejected"

    # AI / provider (domain=AI)
    AI_PROVIDER_UNAVAILABLE = "ai_provider_unavailable"
    AI_TIMEOUT          = "ai_timeout"
    AI_PARSE_FAILED     = "ai_parse_failed"
    AI_AUTH_FAILED      = "ai_auth_failed"
    AI_RATE_LIMITED     = "ai_rate_limited"

    # Environment / OS (domain=ENVIRONMENT)
    MISSING_DEPENDENCY  = "missing_dependency"
    UNSUPPORTED_OS      = "unsupported_os"
    BLOCKED_PERMISSION  = "blocked_permission"
    LOW_RESOURCES       = "low_resources"

    # Catch-all
    UNKNOWN             = "unknown"


# ── Severity ────────────────────────────────────────────────────────────────

class Severity(enum.IntEnum):
    """How urgently the issue needs attention.

    IntEnum so comparisons work naturally: ``if sev >= Severity.ERROR``.
    """

    INFO     = 0   # informational, no user action needed
    WARNING  = 1   # degraded but system usable, user should be aware
    DEGRADED = 2   # feature impaired, workaround possible
    ERROR    = 3   # blocking — feature unavailable until resolved
    CRITICAL = 4   # safety-critical — immediate user action required


# ── Transience ──────────────────────────────────────────────────────────────

class Transience(enum.Enum):
    """Whether the issue is expected to resolve on its own."""

    TRANSIENT  = "transient"    # retry may succeed (timeout, brief disconnect)
    PERSISTENT = "persistent"   # will not resolve without user/admin action
    UNKNOWN    = "unknown"      # cannot determine automatically


# ── Category → domain / default severity mapping ───────────────────────────

_CATEGORY_META: dict[ErrorCategory, tuple[ErrorDomain, Severity, Transience]] = {
    # Hardware
    ErrorCategory.MISSING_DRIVER:      (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.WRONG_DRIVER_VERSION:(ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.PERMISSION_DENIED:   (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.DEVICE_BUSY:         (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.TRANSIENT),
    ErrorCategory.DEVICE_DISCONNECTED: (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.UNKNOWN),
    ErrorCategory.TIMEOUT:             (ErrorDomain.HARDWARE,     Severity.WARNING,  Transience.TRANSIENT),
    ErrorCategory.BANDWIDTH_LIMIT:     (ErrorDomain.HARDWARE,     Severity.DEGRADED, Transience.PERSISTENT),
    ErrorCategory.NETWORK_CONFIG:      (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.FIRMWARE_MISMATCH:   (ErrorDomain.HARDWARE,     Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.DEVICE_COMM_ERROR:   (ErrorDomain.HARDWARE,     Severity.WARNING,  Transience.TRANSIENT),
    # Config
    ErrorCategory.INVALID_SETTING:     (ErrorDomain.CONFIG,       Severity.WARNING,  Transience.PERSISTENT),
    ErrorCategory.INCOMPATIBLE_CONFIG: (ErrorDomain.CONFIG,       Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.MISSING_PARAMETER:   (ErrorDomain.CONFIG,       Severity.ERROR,    Transience.PERSISTENT),
    # Acquisition
    ErrorCategory.PRECONDITION_FAILED: (ErrorDomain.ACQUISITION,  Severity.ERROR,    Transience.TRANSIENT),
    ErrorCategory.PIPELINE_CONFLICT:   (ErrorDomain.ACQUISITION,  Severity.ERROR,    Transience.TRANSIENT),
    ErrorCategory.OPERATION_CANCELED:  (ErrorDomain.ACQUISITION,  Severity.INFO,     Transience.TRANSIENT),
    # Persistence
    ErrorCategory.SAVE_FAILED:         (ErrorDomain.PERSISTENCE,  Severity.ERROR,    Transience.UNKNOWN),
    ErrorCategory.LOAD_FAILED:         (ErrorDomain.PERSISTENCE,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.FILE_PERMISSION:     (ErrorDomain.PERSISTENCE,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.CORRUPT_FILE:        (ErrorDomain.PERSISTENCE,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.SCHEMA_REJECTED:     (ErrorDomain.PERSISTENCE,  Severity.ERROR,    Transience.PERSISTENT),
    # AI
    ErrorCategory.AI_PROVIDER_UNAVAILABLE: (ErrorDomain.AI,       Severity.DEGRADED, Transience.TRANSIENT),
    ErrorCategory.AI_TIMEOUT:          (ErrorDomain.AI,           Severity.WARNING,  Transience.TRANSIENT),
    ErrorCategory.AI_PARSE_FAILED:     (ErrorDomain.AI,           Severity.WARNING,  Transience.TRANSIENT),
    ErrorCategory.AI_AUTH_FAILED:      (ErrorDomain.AI,           Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.AI_RATE_LIMITED:     (ErrorDomain.AI,           Severity.WARNING,  Transience.TRANSIENT),
    # Environment
    ErrorCategory.MISSING_DEPENDENCY:  (ErrorDomain.ENVIRONMENT,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.UNSUPPORTED_OS:      (ErrorDomain.ENVIRONMENT,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.BLOCKED_PERMISSION:  (ErrorDomain.ENVIRONMENT,  Severity.ERROR,    Transience.PERSISTENT),
    ErrorCategory.LOW_RESOURCES:       (ErrorDomain.ENVIRONMENT,  Severity.WARNING,  Transience.TRANSIENT),
    # Catch-all
    ErrorCategory.UNKNOWN:             (ErrorDomain.HARDWARE,     Severity.WARNING,  Transience.UNKNOWN),
}


def domain_of(cat: ErrorCategory) -> ErrorDomain:
    """Return the domain for a category."""
    return _CATEGORY_META.get(cat, (ErrorDomain.HARDWARE, Severity.WARNING, Transience.UNKNOWN))[0]


def default_severity(cat: ErrorCategory) -> Severity:
    """Return the default severity for a category."""
    return _CATEGORY_META.get(cat, (ErrorDomain.HARDWARE, Severity.WARNING, Transience.UNKNOWN))[1]


def default_transience(cat: ErrorCategory) -> Transience:
    """Return the default transience for a category."""
    return _CATEGORY_META.get(cat, (ErrorDomain.HARDWARE, Severity.WARNING, Transience.UNKNOWN))[2]


# ── Structured error ────────────────────────────────────────────────────────

@dataclass
class DeviceError:
    """Structured, actionable description of an application error.

    Despite the name (kept for backward compatibility), this class is used
    for errors across all domains, not just hardware devices.
    """

    category:        ErrorCategory
    device_uid:      str   = ""
    message:         str   = ""       # user-facing summary
    suggested_fix:   str   = ""       # actionable steps
    raw_exception:   str   = ""       # original str(exc)
    exception_type:  str   = ""       # e.g. "serial.SerialException"
    support_context: dict  = field(default_factory=dict)

    # ── Extended fields (added Phase 1 taxonomy expansion) ────────────
    severity:        Optional[Severity]    = None   # None → use default_severity(category)
    domain:          Optional[ErrorDomain]  = None   # None → use domain_of(category)
    transience:      Optional[Transience]   = None   # None → use default_transience(category)
    user_correctable: Optional[bool]       = None   # True = user can fix; False = needs support
    error_code:      str   = ""       # stable machine-readable code, e.g. "HW_TIMEOUT"

    # ── Resolved accessors (fall back to category defaults) ────────
    @property
    def resolved_severity(self) -> Severity:
        return self.severity if self.severity is not None else default_severity(self.category)

    @property
    def resolved_domain(self) -> ErrorDomain:
        return self.domain if self.domain is not None else domain_of(self.category)

    @property
    def resolved_transience(self) -> Transience:
        return self.transience if self.transience is not None else default_transience(self.category)

    @property
    def is_blocking(self) -> bool:
        """True if this error prevents the affected feature from working."""
        return self.resolved_severity >= Severity.ERROR

    @property
    def is_user_correctable(self) -> bool:
        """True if the user can fix this without developer/support help."""
        if self.user_correctable is not None:
            return self.user_correctable
        # Heuristic: most hardware and config issues are user-correctable;
        # persistence corruption and unknown errors are not.
        return self.category not in (
            ErrorCategory.CORRUPT_FILE,
            ErrorCategory.SCHEMA_REJECTED,
            ErrorCategory.UNKNOWN,
        )

    @property
    def short_message(self) -> str:
        """First line, capped at 120 chars — for status bar / toast."""
        first = self.message.split("\n", 1)[0]
        return first[:120]

    @property
    def narration(self) -> str:
        """Full natural-language paragraph (lazy import to avoid circular deps)."""
        from hardware.error_narration import narrate
        return narrate(self)

    @property
    def short_narration(self) -> str:
        """One-line plain-English summary (≤120 chars)."""
        from hardware.error_narration import short_narrate
        return short_narrate(self)

    def to_dict(self) -> dict:
        """Serialize for support bundle / JSON logging."""
        return {
            "category": self.category.value,
            "domain": self.resolved_domain.value,
            "severity": self.resolved_severity.name,
            "transience": self.resolved_transience.value,
            "device_uid": self.device_uid,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "raw_exception": self.raw_exception,
            "exception_type": self.exception_type,
            "error_code": self.error_code,
            "user_correctable": self.is_user_correctable,
            "is_blocking": self.is_blocking,
        }


# ── Convenience factory for non-hardware errors ─────────────────────────────

def make_error(
    category: ErrorCategory,
    message: str,
    *,
    suggested_fix: str = "",
    device_uid: str = "",
    severity: Optional[Severity] = None,
    transience: Optional[Transience] = None,
    user_correctable: Optional[bool] = None,
    exc: Optional[Exception] = None,
    error_code: str = "",
    context: Optional[dict] = None,
) -> DeviceError:
    """Create a DeviceError for any domain — not just hardware.

    This is the preferred factory for config, acquisition, persistence,
    AI, and environment errors where ``classify_error()`` (which
    pattern-matches vendor exceptions) is not applicable.
    """
    return DeviceError(
        category=category,
        device_uid=device_uid,
        message=message,
        suggested_fix=suggested_fix,
        raw_exception=str(exc) if exc else "",
        exception_type=type(exc).__qualname__ if exc else "",
        support_context=context or {},
        severity=severity,
        transience=transience,
        user_correctable=user_correctable,
        error_code=error_code,
    )


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

    # ── TDG-VII / PT-100 / STM32 errors ─────────────────────────────
    if _is_tdg7_error(exc_lower, device_uid):
        return _classify_tdg7(exc, device_uid, exc_str, exc_lower, ctx)

    # ── Arduino / ESP32 microcontroller errors ────────────────────────
    if _is_arduino_error(exc_lower, device_uid):
        return _classify_arduino(exc, device_uid, exc_str, exc_lower, ctx)

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


# ── TDG-VII / PT-100 classifier ─────────────────────────────────────────────

_TDG7_UIDS = {"tdg7", "pt-100", "pt100", "tdg_vii"}
_TDG7_KEYWORDS = ("tdg", "pt-100", "stm32", "fastlaser", "0483:5740",
                   "delay generator", "stm virtual")


def _is_tdg7_error(exc_lower: str, uid: str) -> bool:
    """Heuristic: is this error related to a TDG-VII / PT-100?"""
    if uid.lower() in _TDG7_UIDS:
        return True
    return any(kw in exc_lower for kw in _TDG7_KEYWORDS)


def _classify_tdg7(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify TDG-VII / PT-100 delay generator errors."""
    if "not found" in sl or "no device" in sl or "not connected" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
            message=f"TDG-VII / PT-100 not found: {s[:80]}",
            suggested_fix=(
                "Check that the delay generator is connected via USB and powered on.\n"
                "The TDG-VII uses an STM32 Virtual COM Port (VID 0483:5740).\n"
                "On Windows, install the STM32 VCP driver if the device does not\n"
                "appear as a COM port in Device Manager."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "access" in sl or "denied" in sl or "busy" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_BUSY, device_uid=uid,
            message=f"TDG-VII port in use: {s[:80]}",
            suggested_fix=(
                "Another application has the TDG-VII serial port open.\n"
                "Close the Fastlaser Tech TDG software or any serial terminal, then retry."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "timeout" in sl:
        return DeviceError(
            category=ErrorCategory.TIMEOUT, device_uid=uid,
            message=f"TDG-VII timeout: {s[:80]}",
            suggested_fix=(
                "The delay generator did not respond.\n"
                "Check that the correct COM port is selected (should show as STM32 VCP).\n"
                "Verify baud rate is 115200 (default)."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "stm32" in sl or "vcp" in sl:
        return DeviceError(
            category=ErrorCategory.MISSING_DRIVER, device_uid=uid,
            message=f"STM32 VCP driver issue: {s[:80]}",
            suggested_fix=(
                "Install the STM32 Virtual COM Port driver:\n"
                "  https://www.st.com/en/development-tools/stsw-stm32102.html\n"
                "After installation, unplug and replug the TDG-VII."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN, device_uid=uid,
        message=f"TDG-VII error: {s[:100]}",
        suggested_fix="Check the TDG-VII USB connection and power.\n"
                      "Run View → Re-scan Hardware to detect the device.",
        raw_exception=s, exception_type=type(exc).__qualname__,
        support_context=ctx,
    )


# ── Arduino / ESP32 classifier ──────────────────────────────────────────────

_ARDUINO_UIDS = {"arduino_nano", "arduino_uno", "arduino_uno_r4",
                  "esp32_cp2102", "esp32_native_usb"}
_ARDUINO_KEYWORDS = ("arduino", "esp32", "ch340", "ch341", "cp210",
                     "nano", "uno r4", "sanjio", "led channel")


def _is_arduino_error(exc_lower: str, uid: str) -> bool:
    """Heuristic: is this error related to an Arduino or ESP32 board?"""
    if uid.lower() in _ARDUINO_UIDS:
        return True
    return any(kw in exc_lower for kw in _ARDUINO_KEYWORDS)


def _classify_arduino(
    exc: Exception, uid: str, s: str, sl: str, ctx: dict,
) -> DeviceError:
    """Classify Arduino / ESP32 microcontroller errors."""
    is_esp32 = "esp32" in uid.lower() or "esp32" in sl or "cp210" in sl

    if "not found" in sl or "no device" in sl:
        board = "ESP32" if is_esp32 else "Arduino"
        return DeviceError(
            category=ErrorCategory.DEVICE_DISCONNECTED, device_uid=uid,
            message=f"{board} not found: {s[:80]}",
            suggested_fix=(
                f"Check that the {board} board is connected via USB.\n"
                f"Verify the correct driver is installed:\n"
                + ("  ESP32 (CP2102): Silicon Labs CP210x driver\n"
                   "  ESP32 (native): no driver needed" if is_esp32
                   else "  Arduino Nano: CH340 driver (usually auto-installed)\n"
                        "  Arduino UNO: ATmega16U2 driver (included with Arduino IDE)")
            ),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "access" in sl or "denied" in sl or "busy" in sl:
        return DeviceError(
            category=ErrorCategory.DEVICE_BUSY, device_uid=uid,
            message=f"Serial port in use: {s[:80]}",
            suggested_fix=(
                "Another application has the serial port open.\n"
                "Close the Arduino IDE Serial Monitor or any other serial terminal, then retry."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "timeout" in sl or "no response" in sl:
        board = "ESP32" if is_esp32 else "Arduino"
        return DeviceError(
            category=ErrorCategory.TIMEOUT, device_uid=uid,
            message=f"{board} timeout: {s[:80]}",
            suggested_fix=(
                f"The {board} did not respond to the IDENT command.\n"
                "Verify the SanjINSIGHT I/O firmware is flashed on the board.\n"
                "Check baud rate is 115200 and the correct COM port is selected."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    if "firmware" in sl or "ident" in sl:
        return DeviceError(
            category=ErrorCategory.FIRMWARE_MISMATCH, device_uid=uid,
            message=f"Firmware issue: {s[:80]}",
            suggested_fix=(
                "The board responded but the firmware may not be the SanjINSIGHT I/O firmware.\n"
                "Flash the correct firmware from firmware/arduino_nano/ or firmware/esp32/."),
            raw_exception=s, exception_type=type(exc).__qualname__,
            support_context=ctx,
        )
    return DeviceError(
        category=ErrorCategory.UNKNOWN, device_uid=uid,
        message=f"Microcontroller error: {s[:100]}",
        suggested_fix="Check the USB connection and verify the SanjINSIGHT I/O firmware is flashed.",
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
