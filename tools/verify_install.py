#!/usr/bin/env python3
"""
verify_install.py — Post-installation verification for SanjINSIGHT on Windows.

Run this on the target machine after installing SanjINSIGHT to verify that
all drivers, COM ports, and hardware dependencies are correctly set up.

Usage:
    python tools/verify_install.py          # Full check
    python tools/verify_install.py --quick  # Drivers only (no hardware probing)

Exit codes:
    0 — All checks passed
    1 — One or more checks failed (see output)
"""

import ctypes
import os
import platform
import subprocess
import sys
import winreg
from pathlib import Path


# ── ANSI helpers (Windows 10+ supports VT100) ──────────────────────────────
def _enable_ansi():
    """Enable ANSI escape codes on Windows 10+."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

failures = []
warnings = []


def check(label, ok, fail_msg="", warn_only=False):
    """Print a check result and track failures."""
    if ok:
        print(f"  {PASS}  {label}")
    elif warn_only:
        print(f"  {WARN}  {label} — {fail_msg}")
        warnings.append(f"{label}: {fail_msg}")
    else:
        print(f"  {FAIL}  {label} — {fail_msg}")
        failures.append(f"{label}: {fail_msg}")


def reg_key_exists(hive, subkey):
    """Check if a registry key exists."""
    try:
        winreg.OpenKey(hive, subkey)
        return True
    except FileNotFoundError:
        return False


def reg_read_str(hive, subkey, value_name):
    """Read a REG_SZ value, return None if not found."""
    try:
        key = winreg.OpenKey(hive, subkey)
        val, _ = winreg.QueryValueEx(key, value_name)
        return str(val)
    except (FileNotFoundError, OSError):
        return None


def list_com_ports():
    """List COM ports visible to Windows."""
    ports = []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DEVICEMAP\SERIALCOMM")
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
                ports.append((name, value))
                i += 1
            except OSError:
                break
    except FileNotFoundError:
        pass
    return ports


# ── Section: OS & Platform ──────────────────────────────────────────────────
def check_platform():
    print(f"\n{BOLD}Operating System{RESET}")
    ver = platform.version()
    release = platform.release()
    arch = platform.machine()
    print(f"  {INFO}  Windows {release} (build {ver}), {arch}")

    check("64-bit Windows", arch in ("AMD64", "x86_64"),
          f"Got {arch} — SanjINSIGHT requires 64-bit Windows")

    # Windows 10 minimum (build 17763)
    try:
        build = int(ver.split(".")[-1])
        check("Windows 10 1809+ (build 17763+)", build >= 17763,
              f"Build {build} is too old")
    except ValueError:
        check("Windows version parse", False, f"Could not parse build from '{ver}'")


# ── Section: SanjINSIGHT Installation ───────────────────────────────────────
def check_sanjinsight():
    print(f"\n{BOLD}SanjINSIGHT Installation{RESET}")

    version = reg_read_str(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsanj\SanjINSIGHT", "Version")
    install_path = reg_read_str(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsanj\SanjINSIGHT", "InstallPath")

    check("Registry version entry", version is not None,
          "Not found — was the installer run?")
    if version:
        print(f"  {INFO}  Installed version: {version}")

    check("Registry install path", install_path is not None,
          "Not found in registry")
    if install_path:
        exe = Path(install_path) / "SanjINSIGHT.exe"
        check("SanjINSIGHT.exe exists", exe.exists(),
              f"Not found at {exe}")


# ── Section: Visual C++ Runtime ─────────────────────────────────────────────
def check_vcredist():
    print(f"\n{BOLD}Visual C++ 2015-2022 Runtime (x64){RESET}")

    installed = False
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")
        val, _ = winreg.QueryValueEx(key, "Installed")
        installed = (val == 1)
    except (FileNotFoundError, OSError):
        pass

    check("VC++ 2015-2022 x64 runtime", installed,
          "Not installed — Qt5 and numpy will not load")


# ── Section: USB-Serial Drivers ─────────────────────────────────────────────
def check_usb_serial_drivers():
    print(f"\n{BOLD}USB-Serial Drivers{RESET}")

    # FTDI VCP (Meerstetter TEC-1089 / LDD-1121)
    ftdi = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                          r"SYSTEM\CurrentControlSet\Services\FTSER2K")
    check("FTDI VCP driver (Meerstetter TEC/LDD)", ftdi,
          "Not installed — TEC and LDD hardware will not connect",
          warn_only=True)

    # CH340/CH341 (Arduino Nano, many serial adapters)
    ch341_64 = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Services\CH341SER_A64")
    ch341_32 = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Services\CH341SER")
    ch340_ok = ch341_64 or ch341_32
    check("CH340/CH341 driver (Arduino Nano)", ch340_ok,
          "Not installed — Arduino GPIO will not connect",
          warn_only=True)

    # Basler USB3 Vision camera driver
    basler_svc = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Services\BvcUsbU3v")
    basler_old = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Services\pylonusb")
    basler_sdk = reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Basler\pylon")
    basler_ok = basler_svc or basler_old or basler_sdk
    check("Basler USB3 Vision camera driver", basler_ok,
          "Not installed — Basler cameras will not be detected.\n"
          "           Install via the SanjINSIGHT installer or download the pylon\n"
          "           Runtime from: https://www.baslerweb.com/en/downloads/software-downloads/")

    # NI R Series RIO driver (NI 9637 FPGA via PCIe)
    ni_rio = (reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\National Instruments\RIO") or
              reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\National Instruments\RIO"))
    check("NI R Series RIO driver (NI 9637 FPGA)", ni_rio,
          "Not installed — FPGA stimulus generation will not work.\n"
          "           The installer bundles the NI-RIO online installer (requires internet).\n"
          "           Manual download: https://www.ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html",
          warn_only=True)

    # Check for DLL conflict (full Pylon SDK + pypylon)
    if basler_sdk:
        pylon_root = reg_read_str(winreg.HKEY_LOCAL_MACHINE,
                                  r"SOFTWARE\Basler\pylon", "InstallDir")
        if pylon_root:
            print(f"  {WARN}  Full Basler Pylon SDK detected at: {pylon_root}")
            print(f"         SanjINSIGHT isolates its bundled pypylon DLLs from the")
            print(f"         system SDK to prevent version conflicts.")
            warnings.append("Full Basler Pylon SDK installed — DLL isolation active")


# ── Section: COM Ports ──────────────────────────────────────────────────────
def check_com_ports():
    print(f"\n{BOLD}COM Ports{RESET}")

    ports = list_com_ports()
    if not ports:
        print(f"  {WARN}  No COM ports detected (is hardware plugged in?)")
        warnings.append("No COM ports found")
        return

    for name, port in ports:
        driver_hint = ""
        name_lower = name.lower()
        if "ftdi" in name_lower or "vcp" in name_lower:
            driver_hint = " (FTDI — likely Meerstetter TEC or LDD)"
        elif "ch340" in name_lower or "ch341" in name_lower or "wch" in name_lower:
            driver_hint = " (CH340 — likely Arduino Nano)"
        elif "usbser" in name_lower:
            driver_hint = " (USB Serial)"
        print(f"  {INFO}  {port}: {name}{driver_hint}")


# ── Section: Optional SDKs ──────────────────────────────────────────────────
def check_optional_sdks():
    print(f"\n{BOLD}Optional Hardware SDKs{RESET}")

    # NI-VISA (Keithley SMU / GPIB instruments only)
    visa_key = r"SOFTWARE\National Instruments\NI-VISA\CurrentVersion"
    ni_visa = (reg_key_exists(winreg.HKEY_LOCAL_MACHINE, visa_key) or
               reg_key_exists(winreg.HKEY_LOCAL_MACHINE,
                              visa_key.replace("SOFTWARE", "SOFTWARE\\WOW6432Node")))
    check("NI-VISA (Keithley SMU / GPIB only)", ni_visa,
          "Not installed — only needed if you have Keithley or GPIB instruments",
          warn_only=True)

    # NI-RIO is now checked in check_usb_serial_drivers() as a bundled driver


# ── Section: Camera (quick probe) ───────────────────────────────────────────
def check_camera(quick=False):
    print(f"\n{BOLD}Camera (Basler){RESET}")

    if quick:
        print(f"  {INFO}  Skipped (--quick mode)")
        return

    # pypylon bundles pylon runtime — just check if we can import
    install_path = reg_read_str(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsanj\SanjINSIGHT", "InstallPath")
    if not install_path:
        print(f"  {WARN}  Cannot probe — SanjINSIGHT install path not found")
        return

    # Check if pypylon DLLs are present in the bundle
    pypylon_dir = Path(install_path) / "pypylon"
    if pypylon_dir.is_dir():
        dll_count = len(list(pypylon_dir.glob("*.dll"))) + len(list(pypylon_dir.glob("*.pyd")))
        check("pypylon bundled in install", dll_count > 0,
              "pypylon directory exists but no DLLs found")
        if dll_count > 0:
            print(f"  {INFO}  pypylon contains {dll_count} binary files (pylon runtime bundled)")
    else:
        check("pypylon bundled in install", False,
              "pypylon directory not found — camera will not work",
              warn_only=True)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    if platform.system() != "Windows":
        print("This script is designed for Windows. Exiting.")
        sys.exit(0)

    _enable_ansi()
    quick = "--quick" in sys.argv

    print(f"\n{'=' * 60}")
    print(f"  SanjINSIGHT Post-Installation Verification")
    print(f"{'=' * 60}")

    check_platform()
    check_sanjinsight()
    check_vcredist()
    check_usb_serial_drivers()
    check_com_ports()
    check_optional_sdks()
    check_camera(quick=quick)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    if not failures and not warnings:
        print(f"  {PASS}  All checks passed!")
    elif not failures:
        print(f"  {PASS}  All required checks passed ({len(warnings)} warning(s))")
    else:
        print(f"  {FAIL}  {len(failures)} check(s) FAILED, {len(warnings)} warning(s)")
        print(f"\n  Failures:")
        for f in failures:
            print(f"    - {f}")

    if warnings:
        print(f"\n  Warnings (optional components):")
        for w in warnings:
            print(f"    - {w}")

    print(f"{'=' * 60}\n")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
