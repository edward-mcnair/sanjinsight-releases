"""
hardware/os_checks.py

Platform-specific diagnostic checks for hardware connectivity issues.

Detects common OS-level problems that prevent device communication:
  - Windows: USB selective suspend, COM port locks
  - macOS: camera access permissions
  - Linux: dialout group membership
  - All: serial port existence vs busy vs accessible

Pure Python — no Qt dependency.

Usage
-----
    from hardware.os_checks import run_os_checks

    results = run_os_checks()
    for r in results:
        if not r.passed:
            print(f"WARNING: {r.display_name} — {r.fix_suggestion}")
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class OSCheckResult:
    """Result of a single OS-level diagnostic check."""

    check_id:       str
    display_name:   str
    passed:         bool
    message:        str
    fix_suggestion: str = ""   # empty if passed

    @property
    def is_warning(self) -> bool:
        return not self.passed and bool(self.fix_suggestion)


def run_os_checks() -> list[OSCheckResult]:
    """Run all applicable OS checks for the current platform.

    Returns a list of results; only failed checks carry fix suggestions.
    Safe to call from any thread.
    """
    checks: list[OSCheckResult] = []

    if sys.platform == "win32":
        checks.append(_check_usb_selective_suspend())
        checks.extend(_check_com_port_locks())
    elif sys.platform == "darwin":
        checks.append(_check_macos_camera_permission())
    else:
        checks.append(_check_linux_dialout_group())

    checks.extend(_check_serial_port_health())

    return [c for c in checks if c is not None]


# ── Windows checks ──────────────────────────────────────────────────────────

def _check_usb_selective_suspend() -> OSCheckResult:
    """Check if USB selective suspend is disabled (Windows only).

    USB selective suspend can cause FTDI serial adapters to disconnect
    after idle periods, leading to intermittent "port not found" errors.
    """
    try:
        import winreg
        key_path = r"SYSTEM\CurrentControlSet\Services\USB"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            val, _ = winreg.QueryValueEx(key, "DisableSelectiveSuspend")
            winreg.CloseKey(key)
            if val == 1:
                return OSCheckResult(
                    check_id="win_usb_suspend",
                    display_name="USB Selective Suspend",
                    passed=True,
                    message="USB selective suspend is disabled (good).",
                )
        except FileNotFoundError:
            pass  # Key doesn't exist — suspend is enabled (default)
        except Exception as exc:
            log.debug("USB suspend check error: %s", exc)

        return OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Selective Suspend",
            passed=False,
            message="USB selective suspend is enabled (Windows default). "
                    "This can cause serial devices to disconnect after idle periods.",
            fix_suggestion=(
                "Disable USB selective suspend:\n"
                "  1. Open Device Manager\n"
                "  2. Expand 'Universal Serial Bus controllers'\n"
                "  3. For each USB Root Hub: Properties → Power Management\n"
                "     → Uncheck 'Allow the computer to turn off this device'\n"
                "Or: Control Panel → Power Options → Change Plan Settings\n"
                "  → Change Advanced → USB → Selective Suspend → Disabled"
            ),
        )
    except ImportError:
        return OSCheckResult(
            check_id="win_usb_suspend",
            display_name="USB Selective Suspend",
            passed=True,
            message="Check skipped (not on Windows).",
        )


def _check_com_port_locks() -> list[OSCheckResult]:
    """Check if any configured COM ports are locked by another process."""
    results = []
    try:
        import serial.tools.list_ports
        for port_info in serial.tools.list_ports.comports():
            port = port_info.device
            # Only check FTDI ports (our main serial adapters)
            if port_info.vid != 0x0403:
                continue
            try:
                import serial
                s = serial.Serial(port, timeout=0.1)
                s.close()
                # Port is accessible — no issue
            except serial.SerialException as exc:
                exc_str = str(exc).lower()
                if "access is denied" in exc_str or "permissionerror" in exc_str:
                    results.append(OSCheckResult(
                        check_id=f"win_port_lock_{port}",
                        display_name=f"{port} Locked",
                        passed=False,
                        message=f"{port} ({port_info.description}) is locked by another application.",
                        fix_suggestion=(
                            f"Close any application using {port}:\n"
                            "  • PuTTY, TeraTerm, Arduino IDE, or other serial monitors\n"
                            "  • Meerstetter Service Tool\n"
                            "Then click Re-scan Hardware."
                        ),
                    ))
            except Exception:
                pass
    except ImportError:
        log.debug("pyserial not available — skipping COM port lock check")
    return results


# ── macOS checks ────────────────────────────────────────────────────────────

def _check_macos_camera_permission() -> OSCheckResult:
    """Guide users to grant camera access on macOS if needed."""
    # macOS TCC (Transparency, Consent, and Control) manages camera access.
    # We can't directly query TCC without private APIs, but we can detect
    # if a camera import would likely fail due to permissions.
    try:
        # Try importing pypylon — if it fails with a permissions-related
        # error, the user needs to grant access.
        import pypylon.pylon  # noqa: F401
        return OSCheckResult(
            check_id="macos_camera_perm",
            display_name="Camera Permission (macOS)",
            passed=True,
            message="Camera SDK accessible.",
        )
    except ImportError:
        return OSCheckResult(
            check_id="macos_camera_perm",
            display_name="Camera Permission (macOS)",
            passed=True,
            message="pypylon not installed — camera permission check skipped.",
        )
    except Exception as exc:
        if "access" in str(exc).lower() or "permission" in str(exc).lower():
            return OSCheckResult(
                check_id="macos_camera_perm",
                display_name="Camera Permission (macOS)",
                passed=False,
                message="Camera access may be blocked by macOS privacy settings.",
                fix_suggestion=(
                    "Grant camera access:\n"
                    "  System Settings → Privacy & Security → Camera\n"
                    "  → Enable access for SanjINSIGHT (or Python/Terminal)"
                ),
            )
        return OSCheckResult(
            check_id="macos_camera_perm",
            display_name="Camera Permission (macOS)",
            passed=True,
            message=f"Camera check inconclusive: {str(exc)[:60]}",
        )


# ── Linux checks ────────────────────────────────────────────────────────────

def _check_linux_dialout_group() -> OSCheckResult:
    """Check if the current user is in the 'dialout' group (serial access)."""
    try:
        import grp
        user = os.getlogin()
        try:
            dialout = grp.getgrnam("dialout")
            if user in dialout.gr_mem or os.getuid() == 0:
                return OSCheckResult(
                    check_id="linux_dialout",
                    display_name="Serial Port Access (dialout)",
                    passed=True,
                    message=f"User '{user}' is in the 'dialout' group.",
                )
            return OSCheckResult(
                check_id="linux_dialout",
                display_name="Serial Port Access (dialout)",
                passed=False,
                message=f"User '{user}' is not in the 'dialout' group. "
                        "Serial port access will fail with 'Permission denied'.",
                fix_suggestion=(
                    f"Add your user to the dialout group:\n"
                    f"  sudo usermod -aG dialout {user}\n"
                    "Then log out and back in for the change to take effect."
                ),
            )
        except KeyError:
            # No 'dialout' group — try 'uucp' (Arch Linux)
            try:
                uucp = grp.getgrnam("uucp")
                if user in uucp.gr_mem:
                    return OSCheckResult(
                        check_id="linux_dialout",
                        display_name="Serial Port Access (uucp)",
                        passed=True,
                        message=f"User '{user}' is in the 'uucp' group.",
                    )
            except KeyError:
                pass
            return OSCheckResult(
                check_id="linux_dialout",
                display_name="Serial Port Access",
                passed=True,
                message="Neither 'dialout' nor 'uucp' group found — check skipped.",
            )
    except Exception as exc:
        log.debug("dialout group check failed: %s", exc)
        return OSCheckResult(
            check_id="linux_dialout",
            display_name="Serial Port Access",
            passed=True,
            message=f"Check skipped: {str(exc)[:60]}",
        )


# ── Cross-platform checks ──────────────────────────────────────────────────

def _check_serial_port_health() -> list[OSCheckResult]:
    """Check configured serial ports for existence and accessibility."""
    results = []
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            results.append(OSCheckResult(
                check_id="serial_no_ports",
                display_name="Serial Ports",
                passed=False,
                message="No serial ports detected on this system.",
                fix_suggestion=(
                    "Check that USB-to-serial adapters are plugged in.\n"
                    "Install FTDI drivers if needed: https://ftdichip.com/drivers/"
                ),
            ))
    except ImportError:
        results.append(OSCheckResult(
            check_id="serial_pyserial",
            display_name="pyserial",
            passed=False,
            message="pyserial is not installed — serial port detection unavailable.",
            fix_suggestion="pip install pyserial",
        ))
    return results
