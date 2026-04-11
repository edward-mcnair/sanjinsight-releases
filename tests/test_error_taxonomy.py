"""
tests/test_error_taxonomy.py — Error taxonomy classification tests.

Verifies that:
- Hardware exceptions are classified correctly
- Severity, domain, and transience resolve properly
- The make_error factory works for non-hardware domains
- to_dict serialization is stable
- Backward compatibility: existing DeviceError fields work unchanged
"""

import pytest

from hardware.error_taxonomy import (
    ErrorCategory,
    ErrorDomain,
    Severity,
    Transience,
    DeviceError,
    classify_error,
    make_error,
    domain_of,
    default_severity,
    default_transience,
)


# ── Hardware classification tests ────────────────────────────────────────────


class TestClassifyError:
    """Tests for classify_error() with vendor exception patterns."""

    def test_import_error_missing_driver(self):
        err = classify_error(ImportError("No module named 'pypylon'"))
        assert err.category == ErrorCategory.MISSING_DRIVER
        assert err.resolved_domain == ErrorDomain.HARDWARE
        assert err.resolved_severity == Severity.ERROR
        assert err.is_blocking
        assert "pypylon" in err.suggested_fix

    def test_permission_error(self):
        err = classify_error(PermissionError("Access denied: /dev/ttyUSB0"))
        assert err.category == ErrorCategory.PERMISSION_DENIED
        assert err.is_blocking
        assert err.is_user_correctable

    def test_timeout_error(self):
        err = classify_error(TimeoutError("read timed out"), device_uid="tec0")
        assert err.category == ErrorCategory.TIMEOUT
        assert err.resolved_severity == Severity.WARNING
        assert err.resolved_transience == Transience.TRANSIENT
        assert not err.is_blocking
        assert err.device_uid == "tec0"

    def test_connection_refused(self):
        err = classify_error(ConnectionRefusedError("Connection refused"))
        assert err.category == ErrorCategory.NETWORK_CONFIG
        assert err.resolved_domain == ErrorDomain.HARDWARE

    def test_oserror_eacces(self):
        import errno
        exc = OSError(errno.EACCES, "Permission denied", "/dev/ttyUSB0")
        err = classify_error(exc)
        assert err.category == ErrorCategory.PERMISSION_DENIED

    def test_oserror_enoent(self):
        import errno
        exc = OSError(errno.ENOENT, "No such file", "/dev/ttyUSB0")
        err = classify_error(exc)
        assert err.category == ErrorCategory.DEVICE_DISCONNECTED

    def test_oserror_ebusy(self):
        import errno
        exc = OSError(errno.EBUSY, "Device busy")
        err = classify_error(exc)
        assert err.category == ErrorCategory.DEVICE_BUSY

    def test_runtime_error_not_found(self):
        err = classify_error(RuntimeError("device not found"))
        assert err.category == ErrorCategory.DEVICE_DISCONNECTED

    def test_runtime_error_version_mismatch(self):
        err = classify_error(RuntimeError("version mismatch detected"))
        assert err.category == ErrorCategory.WRONG_DRIVER_VERSION

    def test_unknown_exception_fallback(self):
        err = classify_error(ValueError("unexpected value"))
        assert err.category == ErrorCategory.UNKNOWN
        assert err.resolved_severity == Severity.WARNING

    def test_device_uid_preserved(self):
        err = classify_error(TimeoutError("timeout"), device_uid="fpga")
        assert err.device_uid == "fpga"


# ── Severity / domain / transience tests ─────────────────────────────────────


class TestSeverityModel:
    """Tests for the severity model and category metadata."""

    def test_severity_ordering(self):
        assert Severity.INFO < Severity.WARNING < Severity.DEGRADED
        assert Severity.DEGRADED < Severity.ERROR < Severity.CRITICAL

    def test_is_blocking_threshold(self):
        """ERROR and CRITICAL are blocking; WARNING and below are not."""
        err_warning = make_error(ErrorCategory.TIMEOUT, "timeout")
        err_error = make_error(ErrorCategory.MISSING_DRIVER, "missing")
        assert not err_warning.is_blocking  # WARNING
        assert err_error.is_blocking  # ERROR

    def test_severity_override(self):
        """Explicit severity overrides the category default."""
        err = make_error(
            ErrorCategory.TIMEOUT, "critical timeout",
            severity=Severity.CRITICAL,
        )
        assert err.resolved_severity == Severity.CRITICAL
        assert err.is_blocking

    def test_domain_mapping(self):
        assert domain_of(ErrorCategory.MISSING_DRIVER) == ErrorDomain.HARDWARE
        assert domain_of(ErrorCategory.SAVE_FAILED) == ErrorDomain.PERSISTENCE
        assert domain_of(ErrorCategory.AI_TIMEOUT) == ErrorDomain.AI
        assert domain_of(ErrorCategory.PRECONDITION_FAILED) == ErrorDomain.ACQUISITION
        assert domain_of(ErrorCategory.INVALID_SETTING) == ErrorDomain.CONFIG
        assert domain_of(ErrorCategory.LOW_RESOURCES) == ErrorDomain.ENVIRONMENT

    def test_transience_defaults(self):
        assert default_transience(ErrorCategory.TIMEOUT) == Transience.TRANSIENT
        assert default_transience(ErrorCategory.MISSING_DRIVER) == Transience.PERSISTENT
        assert default_transience(ErrorCategory.DEVICE_DISCONNECTED) == Transience.UNKNOWN

    def test_all_categories_have_meta(self):
        """Every ErrorCategory must have a domain/severity/transience entry."""
        for cat in ErrorCategory:
            d = domain_of(cat)
            s = default_severity(cat)
            t = default_transience(cat)
            assert isinstance(d, ErrorDomain), f"{cat} missing domain"
            assert isinstance(s, Severity), f"{cat} missing severity"
            assert isinstance(t, Transience), f"{cat} missing transience"


# ── make_error factory tests ─────────────────────────────────────────────────


class TestMakeError:
    """Tests for the make_error() convenience factory."""

    def test_persistence_error(self):
        err = make_error(
            ErrorCategory.SAVE_FAILED,
            "Could not save session to disk",
            suggested_fix="Check available disk space.",
        )
        assert err.resolved_domain == ErrorDomain.PERSISTENCE
        assert err.resolved_severity == Severity.ERROR
        assert err.is_blocking

    def test_ai_error(self):
        err = make_error(
            ErrorCategory.AI_PARSE_FAILED,
            "Failed to parse AI response",
        )
        assert err.resolved_domain == ErrorDomain.AI
        assert err.resolved_severity == Severity.WARNING
        assert err.resolved_transience == Transience.TRANSIENT

    def test_config_error(self):
        err = make_error(
            ErrorCategory.INVALID_SETTING,
            "Exposure must be > 0",
            user_correctable=True,
        )
        assert err.is_user_correctable

    def test_environment_error(self):
        err = make_error(
            ErrorCategory.MISSING_DEPENDENCY,
            "numpy is not installed",
            exc=ImportError("No module named 'numpy'"),
        )
        assert err.raw_exception == "No module named 'numpy'"
        assert err.exception_type == "ImportError"

    def test_error_code(self):
        err = make_error(
            ErrorCategory.TIMEOUT,
            "Device timeout",
            error_code="HW_TIMEOUT",
        )
        assert err.error_code == "HW_TIMEOUT"


# ── Serialization tests ─────────────────────────────────────────────────────


class TestSerialization:
    """Tests for to_dict serialization."""

    def test_to_dict_fields(self):
        err = classify_error(TimeoutError("timeout"), device_uid="tec0")
        d = err.to_dict()
        assert d["category"] == "timeout"
        assert d["domain"] == "hardware"
        assert d["severity"] == "WARNING"
        assert d["transience"] == "transient"
        assert d["device_uid"] == "tec0"
        assert isinstance(d["is_blocking"], bool)
        assert isinstance(d["user_correctable"], bool)

    def test_to_dict_with_overrides(self):
        err = make_error(
            ErrorCategory.SAVE_FAILED,
            "write failed",
            severity=Severity.CRITICAL,
            transience=Transience.PERSISTENT,
            user_correctable=False,
        )
        d = err.to_dict()
        assert d["severity"] == "CRITICAL"
        assert d["transience"] == "persistent"
        assert d["user_correctable"] is False
        assert d["is_blocking"] is True


# ── Backward compatibility tests ─────────────────────────────────────────────


class TestBackwardCompat:
    """Verify existing DeviceError fields and properties still work."""

    def test_short_message(self):
        err = DeviceError(
            category=ErrorCategory.TIMEOUT,
            message="Line one\nLine two",
        )
        assert err.short_message == "Line one"

    def test_narration_property(self):
        err = classify_error(TimeoutError("timed out"), device_uid="tec0")
        narr = err.narration
        assert isinstance(narr, str)
        assert len(narr) > 20  # should produce a meaningful paragraph

    def test_short_narration_property(self):
        err = classify_error(TimeoutError("timed out"), device_uid="tec0")
        short = err.short_narration
        assert isinstance(short, str)
        assert len(short) <= 160

    def test_support_context_preserved(self):
        err = classify_error(ImportError("no module"))
        assert "exception_type" in err.support_context
        assert "traceback" in err.support_context

    def test_new_fields_default_to_none(self):
        """Existing code that creates DeviceError without new fields still works."""
        err = DeviceError(
            category=ErrorCategory.TIMEOUT,
            device_uid="cam",
            message="timeout",
        )
        assert err.severity is None
        assert err.domain is None
        assert err.transience is None
        # But resolved accessors still return values
        assert err.resolved_severity == Severity.WARNING
        assert err.resolved_domain == ErrorDomain.HARDWARE
