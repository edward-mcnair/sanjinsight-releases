"""
tests/test_os_checks.py — OS-level diagnostic check tests.

Verifies that:
- OSCheckResult correctly maps to taxonomy categories and severities
- to_device_error() converts failed checks to structured DeviceError
- to_dict() serialization includes taxonomy fields for failed checks
- Passing checks return None from to_device_error()
- is_blocking correctly reflects severity threshold
- The taxonomy mapping covers all known check_ids
- run_os_checks() runs without error on any platform
"""

import pytest

from hardware.os_checks import (
    OSCheckResult,
    run_os_checks,
    _CHECK_TAXONOMY,
)
from hardware.error_taxonomy import (
    ErrorCategory,
    ErrorDomain,
    Severity,
    Transience,
)


# ── OSCheckResult taxonomy integration ─────────────────────────────────────


class TestOSCheckTaxonomy:
    """Tests for taxonomy mapping on OSCheckResult."""

    def test_passing_check_not_blocking(self):
        r = OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Suspend",
            passed=True,
            message="OK",
        )
        assert not r.is_blocking
        assert r.is_informational

    def test_failing_warning_not_blocking(self):
        r = OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Suspend",
            passed=False,
            message="Enabled",
            fix_suggestion="Disable it",
        )
        assert not r.is_blocking  # WARNING severity
        assert r.is_warning

    def test_failing_error_is_blocking(self):
        r = OSCheckResult(
            check_id="linux_dialout",
            display_name="dialout group",
            passed=False,
            message="Not in group",
            fix_suggestion="sudo usermod -aG dialout user",
        )
        assert r.is_blocking  # ERROR severity

    def test_explicit_severity_overrides_mapping(self):
        r = OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Suspend",
            passed=False,
            message="Problem",
            severity=Severity.CRITICAL,
        )
        assert r.is_blocking

    def test_explicit_category(self):
        r = OSCheckResult(
            check_id="custom_check",
            display_name="Custom",
            passed=False,
            message="Failed",
            category=ErrorCategory.LOW_RESOURCES,
            severity=Severity.DEGRADED,
        )
        err = r.to_device_error()
        assert err.category == ErrorCategory.LOW_RESOURCES


class TestToDeviceError:
    """Tests for to_device_error() conversion."""

    def test_passing_returns_none(self):
        r = OSCheckResult(
            check_id="linux_dialout",
            display_name="dialout",
            passed=True,
            message="OK",
        )
        assert r.to_device_error() is None

    def test_failed_usb_suspend(self):
        r = OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Suspend",
            passed=False,
            message="USB selective suspend is enabled.",
            fix_suggestion="Disable it.",
        )
        err = r.to_device_error()
        assert err is not None
        assert err.category == ErrorCategory.BLOCKED_PERMISSION
        assert err.resolved_severity == Severity.WARNING
        assert err.resolved_transience == Transience.PERSISTENT
        assert err.is_user_correctable
        assert err.error_code == "OS_WIN_USB_SUSPEND"
        assert not err.is_blocking

    def test_failed_port_lock(self):
        r = OSCheckResult(
            check_id="win_port_lock_COM3",
            display_name="COM3 Locked",
            passed=False,
            message="COM3 is locked.",
            fix_suggestion="Close other apps.",
            category=ErrorCategory.DEVICE_BUSY,
            severity=Severity.ERROR,
        )
        err = r.to_device_error()
        assert err is not None
        assert err.category == ErrorCategory.DEVICE_BUSY
        assert err.resolved_severity == Severity.ERROR
        assert err.is_blocking
        assert err.error_code == "OS_WIN_PORT_LOCK_COM3"

    def test_failed_dialout(self):
        r = OSCheckResult(
            check_id="linux_dialout",
            display_name="dialout",
            passed=False,
            message="Not in dialout group.",
            fix_suggestion="sudo usermod -aG dialout user",
        )
        err = r.to_device_error()
        assert err.category == ErrorCategory.PERMISSION_DENIED
        assert err.resolved_severity == Severity.ERROR
        assert err.is_blocking

    def test_failed_no_serial_ports(self):
        r = OSCheckResult(
            check_id="serial_no_ports",
            display_name="Serial Ports",
            passed=False,
            message="No serial ports.",
            fix_suggestion="Plug in adapters.",
        )
        err = r.to_device_error()
        assert err.category == ErrorCategory.DEVICE_DISCONNECTED
        assert err.resolved_severity == Severity.WARNING
        assert not err.is_blocking

    def test_failed_pyserial_missing(self):
        r = OSCheckResult(
            check_id="serial_pyserial",
            display_name="pyserial",
            passed=False,
            message="pyserial not installed.",
            fix_suggestion="pip install pyserial",
        )
        err = r.to_device_error()
        assert err.category == ErrorCategory.MISSING_DEPENDENCY
        assert err.resolved_severity == Severity.ERROR


class TestToDict:
    """Tests for to_dict() serialization."""

    def test_passing_check_dict(self):
        r = OSCheckResult(
            check_id="linux_dialout",
            display_name="dialout",
            passed=True,
            message="OK",
        )
        d = r.to_dict()
        assert d["passed"] is True
        assert d["is_blocking"] is False
        assert "fix_suggestion" not in d
        assert "category" not in d

    def test_failing_check_dict(self):
        r = OSCheckResult(
            check_id="serial_no_ports",
            display_name="Serial Ports",
            passed=False,
            message="None found.",
            fix_suggestion="Check adapters.",
        )
        d = r.to_dict()
        assert d["passed"] is False
        assert d["is_blocking"] is False  # WARNING
        assert d["category"] == "device_disconnected"
        assert d["severity"] == "WARNING"
        assert d["fix_suggestion"] == "Check adapters."


class TestTaxonomyMapping:
    """Verify the _CHECK_TAXONOMY mapping is complete and consistent."""

    def test_all_entries_are_valid(self):
        for check_id, (cat, sev) in _CHECK_TAXONOMY.items():
            assert isinstance(cat, ErrorCategory), f"{check_id} bad category"
            assert isinstance(sev, Severity), f"{check_id} bad severity"

    def test_known_ids_covered(self):
        expected = {
            "win_usb_suspend", "win_port_lock", "macos_camera_perm",
            "linux_dialout", "serial_no_ports", "serial_pyserial",
        }
        assert expected == set(_CHECK_TAXONOMY.keys())


class TestRunOSChecks:
    """Integration: run_os_checks() completes on any platform."""

    def test_returns_list(self):
        results = run_os_checks()
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, OSCheckResult)

    def test_all_results_have_check_id(self):
        results = run_os_checks()
        for r in results:
            assert r.check_id
            assert r.display_name

    def test_to_dict_works_for_all(self):
        results = run_os_checks()
        for r in results:
            d = r.to_dict()
            assert isinstance(d, dict)
            assert "check_id" in d
