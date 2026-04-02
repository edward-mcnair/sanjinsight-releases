#!/usr/bin/env python3
"""
scan_hardware.py — Standalone hardware diagnostic scanner for SanjINSIGHT.

Scans all serial ports, identifies FTDI devices, probes for Meerstetter
MeCom controllers (TEC-1089 / LDD-1121), and enumerates Basler cameras.
Designed to run directly on the target machine (e.g., the NUC) without
requiring the full SanjINSIGHT installation.

Usage:
    python tools/scan_hardware.py

Exit codes:
    0 — At least one device was identified
    1 — No devices found (or all probes failed)
"""

from __future__ import annotations

import os
import platform
import struct
import sys
import time
from typing import Dict, List, Optional, Tuple


# ── ANSI helpers (Windows 10+ supports VT100) ────────────────────────────────
def _enable_ansi():
    """Enable ANSI escape codes on Windows 10+."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
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


# ── sys.path: allow importing from hardware/ when run from tools/ ─────────
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ── Shared state ──────────────────────────────────────────────────────────────
# Each entry: {port, device_name, method}
identified_devices: List[Dict[str, str]] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_vid_pid(hwid: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract VID and PID from a pyserial hwid string."""
    hwid = (hwid or "").upper()
    if "VID:PID=" not in hwid:
        return None, None
    try:
        vp = hwid.split("VID:PID=")[1].split()[0]
        v, p = vp.split(":")
        return int(v, 16), int(p, 16)
    except Exception:
        return None, None


def _vid_pid_str(vid: Optional[int], pid: Optional[int]) -> str:
    """Format VID/PID as hex string."""
    if vid is None:
        return "n/a"
    pid_str = f"{pid:04X}" if pid is not None else "????"
    return f"{vid:04X}:{pid_str}"


# ── MeCom address → device name mapping ──────────────────────────────────────
_MECOM_ADDRESS_MAP: Dict[int, str] = {
    2: "Meerstetter TEC-1089",
    1: "Meerstetter LDD-1121",
    0: "Meerstetter device (addr 0)",
}


# ══════════════════════════════════════════════════════════════════════════════
# Section 1: Serial Ports
# ══════════════════════════════════════════════════════════════════════════════

def scan_serial_ports():
    """List ALL serial ports with details."""
    print(f"\n{BOLD}Serial Ports{RESET}")

    try:
        import serial.tools.list_ports as lp
    except ImportError:
        print(f"  {FAIL}  pyserial not installed — cannot enumerate serial ports")
        print(f"         Install with: pip install pyserial")
        return []

    ports = list(lp.comports())
    if not ports:
        print(f"  {WARN}  No serial ports detected")
        return []

    print(f"  {INFO}  Found {len(ports)} serial port(s)\n")

    for port in sorted(ports, key=lambda p: p.device):
        vid, pid = _parse_vid_pid(port.hwid)
        vid_pid = _vid_pid_str(vid, pid)

        print(f"  {BOLD}{port.device}{RESET}")
        print(f"    Description  : {port.description or '(none)'}")
        print(f"    VID:PID      : {vid_pid}")
        print(f"    Serial #     : {port.serial_number or '(none)'}")
        print(f"    Manufacturer : {port.manufacturer or '(none)'}")
        print(f"    HWID         : {port.hwid or '(none)'}")
        print()

    return ports


# ══════════════════════════════════════════════════════════════════════════════
# Section 2: FTDI Ports
# ══════════════════════════════════════════════════════════════════════════════

def scan_ftdi_ports(all_ports) -> list:
    """Filter to FTDI ports and highlight Meerstetter candidates."""
    print(f"\n{BOLD}FTDI Ports (Meerstetter Candidates){RESET}")

    if not all_ports:
        print(f"  {WARN}  No serial ports to filter")
        return []

    ftdi_ports = []
    for port in all_ports:
        vid, pid = _parse_vid_pid(port.hwid)
        if vid == 0x0403:
            ftdi_ports.append(port)

    if not ftdi_ports:
        print(f"  {WARN}  No FTDI ports found (VID 0x0403)")
        print(f"         Meerstetter devices use FTDI USB-serial chips.")
        print(f"         Check that TEC/LDD hardware is connected and powered on.")
        return []

    print(f"  {PASS}  Found {len(ftdi_ports)} FTDI port(s)\n")

    for port in sorted(ftdi_ports, key=lambda p: p.device):
        vid, pid = _parse_vid_pid(port.hwid)
        print(f"  {INFO}  {port.device}  "
              f"VID:PID={_vid_pid_str(vid, pid)}  "
              f"SN={port.serial_number or '(none)'}  "
              f"— {port.description or '(no description)'}")

    return ftdi_ports


# ══════════════════════════════════════════════════════════════════════════════
# Section 3: MeCom Probe
# ══════════════════════════════════════════════════════════════════════════════

def _try_probe_with_protocol_prober(ftdi_ports) -> bool:
    """Attempt to use hardware.protocol_prober for MeCom probing.

    Returns True if the prober was available and ran, False otherwise.
    """
    try:
        from hardware.protocol_prober import probe_mecom_port
    except ImportError:
        return False

    print(f"  {INFO}  Using hardware.protocol_prober module\n")

    for port in sorted(ftdi_ports, key=lambda p: p.device):
        print(f"  Probing {port.device} ...")
        results = probe_mecom_port(
            port.device, baudrate=57600, timeout=1.5,
            addresses=[2, 1, 0], skip_locked=False,
        )
        found_any = False
        for r in results:
            if r.is_identified:
                found_any = True
                name = r.display_name or f"MeCom device @{r.mecom_address}"
                print(f"    {PASS}  {name}  "
                      f"(addr={r.mecom_address}, SN={r.serial_number or 'n/a'}, "
                      f"confidence={r.confidence})")
                identified_devices.append({
                    "port": port.device,
                    "device": name,
                    "method": "protocol_prober",
                })
            elif r.error:
                print(f"    {WARN}  {r.error}")

        if not found_any and not any(r.error for r in results):
            print(f"    {INFO}  No MeCom response")

    return True


def _try_probe_with_pymecom(ftdi_ports) -> bool:
    """Attempt to use pyMeCom (mecom package) directly.

    Returns True if pyMeCom was available and ran, False otherwise.
    """
    try:
        from mecom import MeCom
    except ImportError:
        return False

    print(f"  {INFO}  Using pyMeCom (mecom) package directly\n")

    for port in sorted(ftdi_ports, key=lambda p: p.device):
        print(f"  Probing {port.device} ...")
        mcom = None
        found_any = False
        try:
            mcom = MeCom(serialport=port.device, baudrate=57600,
                         timeout=1.5, metype='TEC')

            for addr in [2, 1, 0]:
                try:
                    dev_info = mcom.identify(address=addr)
                    name = _MECOM_ADDRESS_MAP.get(addr, f"MeCom device @{addr}")
                    sn = str(dev_info) if dev_info else "n/a"
                    print(f"    {PASS}  {name}  (addr={addr}, SN={sn})")
                    identified_devices.append({
                        "port": port.device,
                        "device": name,
                        "method": "pyMeCom",
                    })
                    found_any = True
                except Exception:
                    pass

        except Exception as exc:
            print(f"    {WARN}  Could not open port: {exc}")
        finally:
            if mcom is not None:
                try:
                    mcom.stop()
                except Exception:
                    pass

        if not found_any:
            print(f"    {INFO}  No MeCom response")

    return True


def _build_mecom_frame(address: int, sequence: int = 1) -> bytes:
    """Build a minimal MeCom query frame (get device type, parameter 100).

    MeCom frame structure (binary):
        [1B start] [1B address] [2B sequence] [2B param_id] [1B instance]
        [2B CRC16] — simplified; real protocol is more complex.

    In practice MeCom uses an ASCII protocol with CRC.  We send a
    ?IF (identify) query:  #<addr><seq>?IF<crc>\\r

    Format: #{address:02d}{sequence:04d}?IF{crc}\\r
    CRC is a custom CRC-CCITT over the payload between # and CRC.
    """
    # Build ASCII payload (no # prefix, no CRC, no \r)
    payload = f"{address:02d}{sequence:04d}?IF"
    # MeCom CRC-CCITT (poly 0x1021, init 0x0000)
    crc = _mecom_crc(payload.encode("ascii"))
    frame = f"#{payload}{crc:04X}\r"
    return frame.encode("ascii")


def _mecom_crc(data: bytes) -> int:
    """Compute MeCom CRC-CCITT (polynomial 0x1021, initial value 0x0000)."""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def _try_probe_with_raw_serial(ftdi_ports) -> bool:
    """Last-resort MeCom probe using raw pyserial.

    Sends a MeCom ?IF (identify) query and checks for any response.
    This cannot parse the response fully but can confirm a device is present.

    Returns True if pyserial was available and ran, False otherwise.
    """
    try:
        import serial
    except ImportError:
        return False

    print(f"  {INFO}  Using raw pyserial (limited — install pyMeCom for full info)\n")

    for port in sorted(ftdi_ports, key=lambda p: p.device):
        print(f"  Probing {port.device} ...")
        found_any = False

        for addr in [2, 1, 0]:
            ser = None
            try:
                ser = serial.Serial(
                    port=port.device,
                    baudrate=57600,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=1.5,
                )
                # Flush any stale data
                ser.reset_input_buffer()

                frame = _build_mecom_frame(addr)
                ser.write(frame)
                ser.flush()

                # Read response — MeCom replies start with '!' and end with '\r'
                response = ser.read(128)
                if response and b"!" in response:
                    name = _MECOM_ADDRESS_MAP.get(addr, f"MeCom device @{addr}")
                    print(f"    {PASS}  {name}  (addr={addr}, raw response detected)")
                    identified_devices.append({
                        "port": port.device,
                        "device": name,
                        "method": "raw_serial",
                    })
                    found_any = True

            except Exception as exc:
                if addr == 2:  # Only warn once per port
                    print(f"    {WARN}  Could not open port: {exc}")
                break  # Port-level failure — skip remaining addresses
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

        if not found_any:
            print(f"    {INFO}  No MeCom response")

    return True


def scan_mecom_devices(ftdi_ports):
    """Probe FTDI ports for Meerstetter MeCom devices."""
    print(f"\n{BOLD}MeCom Probe (Meerstetter TEC / LDD){RESET}")

    if not ftdi_ports:
        print(f"  {WARN}  No FTDI ports to probe — skipping")
        return

    # Try approaches in order of capability
    if _try_probe_with_protocol_prober(ftdi_ports):
        return

    if _try_probe_with_pymecom(ftdi_ports):
        return

    if _try_probe_with_raw_serial(ftdi_ports):
        return

    # Nothing worked
    print(f"  {FAIL}  Cannot probe MeCom devices — no suitable library available")
    print(f"         Install pyserial:  pip install pyserial")
    print(f"         (Optional) Install pyMeCom for full device identification")


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: Basler Camera
# ══════════════════════════════════════════════════════════════════════════════

def scan_basler_cameras():
    """Enumerate Basler cameras using pypylon."""
    print(f"\n{BOLD}Basler Camera{RESET}")

    try:
        from pypylon import pylon
    except ImportError:
        print(f"  {WARN}  pypylon not installed — skipping camera enumeration")
        print(f"         Install with: pip install pypylon")
        return

    try:
        tlf = pylon.TlFactory.GetInstance()
        devices = tlf.EnumerateDevices()
    except Exception as exc:
        print(f"  {FAIL}  Camera enumeration failed: {exc}")
        return

    if not devices:
        print(f"  {WARN}  No Basler cameras detected")
        print(f"         Check that the camera is connected via USB3 and powered on.")
        return

    print(f"  {PASS}  Found {len(devices)} Basler camera(s)\n")

    for dev in devices:
        model = dev.GetModelName()
        serial = dev.GetSerialNumber()
        friendly = dev.GetFriendlyName()
        print(f"  {INFO}  {model}  SN={serial}")
        print(f"           {friendly}")
        identified_devices.append({
            "port": "USB3",
            "device": f"Basler {model} (SN: {serial})",
            "method": "pypylon",
        })


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Summary
# ══════════════════════════════════════════════════════════════════════════════

def print_summary():
    """Print a summary table of all identified devices."""
    print(f"\n{'=' * 64}")
    print(f"  {BOLD}Device Summary{RESET}")
    print(f"{'=' * 64}")

    if not identified_devices:
        print(f"\n  {FAIL}  No devices identified")
        print(f"         Check that hardware is connected and powered on.")
        print(f"{'=' * 64}\n")
        return False

    # Column widths
    max_dev = max(len(d["device"]) for d in identified_devices)
    max_port = max(len(d["port"]) for d in identified_devices)
    max_method = max(len(d["method"]) for d in identified_devices)
    col_dev = max(max_dev, 6)  # "Device"
    col_port = max(max_port, 4)  # "Port"
    col_method = max(max_method, 6)  # "Method"

    header = f"  {'Device':<{col_dev}}  {'Port':<{col_port}}  {'Method':<{col_method}}"
    sep = f"  {'-' * col_dev}  {'-' * col_port}  {'-' * col_method}"

    print(f"\n{header}")
    print(sep)

    for d in identified_devices:
        print(f"  {d['device']:<{col_dev}}  {d['port']:<{col_port}}  {d['method']:<{col_method}}")

    print(f"\n  {PASS}  {len(identified_devices)} device(s) identified")
    print(f"{'=' * 64}\n")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    _enable_ansi()

    print(f"\n{'=' * 64}")
    print(f"  SanjINSIGHT Hardware Scanner")
    print(f"  {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  Python {sys.version.split()[0]}")
    print(f"{'=' * 64}")

    # Section 1: All serial ports
    all_ports = scan_serial_ports()

    # Section 2: FTDI ports
    ftdi_ports = scan_ftdi_ports(all_ports)

    # Section 3: MeCom probe
    scan_mecom_devices(ftdi_ports)

    # Section 4: Basler cameras
    scan_basler_cameras()

    # Section 5: Summary
    found = print_summary()
    sys.exit(0 if found else 1)


if __name__ == "__main__":
    main()
