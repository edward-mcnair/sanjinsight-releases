"""
hardware/protocol_prober.py

Protocol-level device identification for ambiguous serial ports.

The passive VID/PID scan cannot distinguish devices that share the same
USB vendor/product IDs (e.g. Meerstetter TEC-1089 and LDD-1121 both use
FTDI 0x0403:0x6001).  This module opens candidate ports and performs
protocol handshakes to resolve ambiguous matches.

Usage
-----
    from hardware.protocol_prober import probe_mecom_port, probe_all_serial

    # Probe a single port
    results = probe_mecom_port("COM3")

    # Probe all FTDI serial ports for any Meerstetter device
    results = probe_all_serial(progress_cb=print)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

# Known MeCom device address → device UID mapping.
# Factory defaults: TEC-1089 = address 2, LDD-1121 = address 1.
_MECOM_ADDRESS_MAP: dict[int, str] = {
    2: "meerstetter_tec_1089",
    1: "meerstetter_ldd1121",
}


@dataclass
class ProbeResult:
    """Result of a protocol-level identification on a single port."""
    port: str                                # COM port / tty path
    device_uid: str = ""                     # registry UID (empty = unknown)
    display_name: str = ""                   # human-readable name
    mecom_address: int = -1                  # MeCom address that responded
    serial_number: str = ""                  # device serial (if available)
    firmware_version: str = ""               # firmware version string
    confidence: str = "protocol_confirmed"   # "protocol_confirmed" | "address_inferred"
    error: str = ""                          # non-empty if probe failed

    @property
    def is_identified(self) -> bool:
        return bool(self.device_uid) and not self.error


# ---------------------------------------------------------------------------
# MeCom probing
# ---------------------------------------------------------------------------

def probe_mecom_port(
    port: str,
    baudrate: int = 57600,
    timeout: float = 1.5,
    addresses: Optional[List[int]] = None,
    skip_locked: bool = True,
) -> List[ProbeResult]:
    """Probe a single serial port for Meerstetter MeCom devices.

    Tries ``identify()`` at each address in *addresses* (default: [2, 1, 0]).
    Two passes with a 0.5 s pause between to handle USB hub latency.

    Parameters
    ----------
    port : str
        Serial port path (e.g. "COM3" or "/dev/cu.usbserial-A50285BI").
    baudrate : int
        Baud rate (MeCom default: 57600).
    timeout : float
        Per-command serial timeout in seconds.
    addresses : list[int] | None
        MeCom addresses to try.  ``None`` = [2, 1, 0].
    skip_locked : bool
        If True, skip ports that are locked by another process.

    Returns
    -------
    list[ProbeResult]
        One entry per address that responded.  Empty list if nothing found.
    """
    if addresses is None:
        addresses = [2, 1, 0]

    # Check if port is locked by another SanjINSIGHT process
    if skip_locked and _is_port_locked(port):
        log.debug("probe_mecom_port: %s is locked — skipping", port)
        return [ProbeResult(port=port, error="port locked by another process")]

    # Check if port is claimed by the port ownership registry
    # (i.e. a live connection or another probe is using it).
    _probe_tag = f"__probe__{port}"
    try:
        from hardware.port_resolver import port_ownership, AmbiguousPortError
        owner = port_ownership.owner_of(port)
        if owner:
            log.debug("probe_mecom_port: %s is owned by %s — skipping", port, owner)
            return [ProbeResult(port=port, error=f"port claimed by {owner}")]
        # Claim the port for the duration of the probe so no concurrent
        # connect or second probe can open it while we're probing.
        port_ownership.claim(port, _probe_tag)
        log.debug("probe_mecom_port: claimed %s for probing", port)
    except AmbiguousPortError as clash:
        log.debug("probe_mecom_port: %s claimed by %s — skipping",
                  port, clash.uid_a)
        return [ProbeResult(port=port, error=f"port claimed by {clash.uid_a}")]
    except Exception:
        pass

    try:
        from mecom import MeCom
    except ImportError:
        # Release probe claim before returning
        try:
            port_ownership.release(_probe_tag)
        except Exception:
            pass
        return [ProbeResult(port=port, error="pyMeCom not installed")]

    results: List[ProbeResult] = []
    mcom = None
    try:
        mcom = MeCom(serialport=port, baudrate=baudrate,
                      timeout=timeout, metype='TEC')

        for pass_num in range(2):
            for addr in addresses:
                # Skip addresses we already found
                if any(r.mecom_address == addr for r in results):
                    continue
                try:
                    dev_info = mcom.identify(address=addr)
                    uid = _MECOM_ADDRESS_MAP.get(addr, "")
                    display = _uid_to_display(uid) if uid else f"MeCom device @{addr}"
                    log.info("MeCom probe: %s → %s at address %d (pass %d)",
                             port, display, addr, pass_num + 1)
                    results.append(ProbeResult(
                        port=port,
                        device_uid=uid,
                        display_name=display,
                        mecom_address=addr,
                        serial_number=str(dev_info) if dev_info else "",
                        confidence="protocol_confirmed" if uid else "address_inferred",
                    ))
                except Exception as exc:
                    log.debug("MeCom probe: %s addr=%d pass=%d failed: %s",
                              port, addr, pass_num + 1, exc)

            if pass_num == 0 and not results:
                # Pause before second pass — USB hub latency mitigation
                time.sleep(0.5)
            else:
                break  # found something or second pass done

    except Exception as exc:
        log.debug("probe_mecom_port: failed to open %s: %s", port, exc)
        results.append(ProbeResult(port=port, error=str(exc)))
    finally:
        if mcom is not None:
            try:
                mcom.stop()
            except Exception:
                pass
        # Release probe claim so the port is available for connect
        try:
            from hardware.port_resolver import port_ownership as _po
            _po.release(_probe_tag)
            log.debug("probe_mecom_port: released %s", port)
        except Exception:
            pass

    # ── Phantom-echo deduplication ────────────────────────────────
    # When only one Meerstetter device is on the bus, it may respond to
    # ANY MeCom address — so address 2 (TEC) and address 1 (LDD) both
    # get a hit with the *same* serial/identity string.  This creates a
    # ghost device.
    #
    # Strategy:
    #   1. If two results share the same non-empty serial → phantom echo.
    #   2. If ALL results have empty serials → can't distinguish, so keep
    #      only the FIRST identified result (the one at the highest-
    #      confidence factory-default address).
    #   3. Error-only results are always kept.
    identified = [r for r in results if r.is_identified]
    errors     = [r for r in results if r.error]

    if len(identified) > 1:
        # Check serials — if any pair matches or all are empty, deduplicate.
        serials = [r.serial_number.strip() for r in identified]
        all_empty = all(not s for s in serials)
        has_dupe  = (len(set(s for s in serials if s)) <
                     len([s for s in serials if s]))

        if all_empty or has_dupe:
            kept = identified[0]
            for dropped in identified[1:]:
                log.info(
                    "MeCom phantom echo: %s addr=%d %s — dropping "
                    "(keeping addr=%d %s)",
                    port, dropped.mecom_address, dropped.device_uid,
                    kept.mecom_address, kept.device_uid)
            identified = [kept]

    results = identified + errors
    return results


def probe_all_serial(
    target_vid: int = 0x0403,
    target_pid: Optional[int] = None,
    baudrate: int = 57600,
    timeout: float = 1.5,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> List[ProbeResult]:
    """Scan all serial ports matching VID (optionally PID) for MeCom devices.

    Parameters
    ----------
    target_vid : int
        USB vendor ID to filter (default: FTDI 0x0403).
    target_pid : int | None
        USB product ID to filter.  None = match any PID from *target_vid*.
    baudrate : int
        MeCom baud rate.
    timeout : float
        Per-command serial timeout.
    progress_cb : callable | None
        Called with status messages during scanning.

    Returns
    -------
    list[ProbeResult]
        All identified devices across all ports.
    """
    ports = _enumerate_serial_ports(target_vid, target_pid)
    if not ports:
        if progress_cb:
            progress_cb("No FTDI serial ports found.")
        return []

    all_results: List[ProbeResult] = []
    for i, (port_path, desc) in enumerate(ports):
        if progress_cb:
            progress_cb(f"Probing {port_path} ({desc}) [{i+1}/{len(ports)}]…")
        results = probe_mecom_port(port_path, baudrate=baudrate, timeout=timeout)
        all_results.extend(r for r in results if r.is_identified)

    return all_results


def find_device_port(
    device_uid: str,
    baudrate: int = 57600,
    timeout: float = 1.5,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Find the COM port for a specific device by UID.

    Scans all FTDI serial ports and returns the port where the device
    with *device_uid* responds.  Returns None if not found.
    """
    target_address = None
    for addr, uid in _MECOM_ADDRESS_MAP.items():
        if uid == device_uid:
            target_address = addr
            break

    if target_address is None:
        log.warning("find_device_port: unknown device_uid %r", device_uid)
        return None

    ports = _enumerate_serial_ports(0x0403, None)
    for port_path, desc in ports:
        if progress_cb:
            progress_cb(f"Scanning {port_path} for {device_uid}…")
        results = probe_mecom_port(
            port_path, baudrate=baudrate, timeout=timeout,
            addresses=[target_address],
        )
        for r in results:
            if r.is_identified and r.device_uid == device_uid:
                return port_path

    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enumerate_serial_ports(
    vid: Optional[int] = None,
    pid: Optional[int] = None,
) -> List[tuple[str, str]]:
    """Return [(port_path, description)] for serial ports matching VID/PID."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        log.warning("pyserial not installed — cannot enumerate serial ports")
        return []

    results = []
    for port in lp.comports():
        hwid = (port.hwid or "").upper()
        port_vid, port_pid = _parse_vid_pid(hwid)

        if vid is not None and port_vid != vid:
            continue
        if pid is not None and port_pid != pid:
            continue

        desc = port.description or port.device
        results.append((port.device, desc))

    return results


def _parse_vid_pid(hwid: str) -> tuple[Optional[int], Optional[int]]:
    """Extract VID and PID from a pyserial hwid string."""
    if "VID:PID=" not in hwid:
        return None, None
    try:
        vp = hwid.split("VID:PID=")[1].split()[0]
        v, p = vp.split(":")
        return int(v, 16), int(p, 16)
    except Exception:
        return None, None


def _is_port_locked(port: str) -> bool:
    """Check if a port has an active SanjINSIGHT lock (Unix only).

    On Windows, we can't check without attempting to open the port,
    so we always return False and let the probe handle the error.
    """
    if sys.platform == "win32":
        return False

    import tempfile
    safe = port.replace("/", "_").replace("\\", "_").replace(":", "_")
    lock_path = os.path.join(tempfile.gettempdir(),
                             f"sanjinsight_port{safe}.lock")
    if not os.path.exists(lock_path):
        return False

    # Check if the lock holder is still alive
    try:
        with open(lock_path) as f:
            pid_str = f.read().strip()
        if pid_str:
            pid = int(pid_str)
            # os.kill(pid, 0) checks existence without sending a signal
            os.kill(pid, 0)
            return True  # process is alive → port is locked
    except (ValueError, ProcessLookupError, PermissionError):
        pass
    except OSError:
        return True  # can't check — assume locked

    return False


def _uid_to_display(uid: str) -> str:
    """Convert a device UID to a display name."""
    _names = {
        "meerstetter_tec_1089": "Meerstetter TEC-1089",
        "meerstetter_tec_1123": "Meerstetter TEC-1123",
        "meerstetter_ldd1121":  "Meerstetter LDD-1121",
    }
    return _names.get(uid, uid)
