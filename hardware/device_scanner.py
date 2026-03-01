"""
hardware/device_scanner.py

Scans all four connection types and returns discovered ports/devices.
Each scanner is independent — a missing dependency silently skips
that transport rather than crashing the whole scan.

Returns a ScanReport containing all discovered items, each matched
against the device registry where possible.
"""

from __future__ import annotations
import time
import socket
import threading
from dataclasses  import dataclass, field
from typing       import List, Optional, Callable

from .device_registry import (
    DeviceDescriptor, DEVICE_REGISTRY,
    find_by_usb, find_by_serial_pattern, find_by_ni_pattern,
    CONN_SERIAL, CONN_USB, CONN_ETHERNET, CONN_PCIE,
    DTYPE_UNKNOWN)


# ------------------------------------------------------------------ #
#  Discovered item                                                     #
# ------------------------------------------------------------------ #

@dataclass
class DiscoveredDevice:
    """One discovered port or device — may or may not be in the registry."""

    # Transport
    connection_type: str        # CONN_*
    address:         str        # COM port, IP:port, NI resource, USB path

    # Raw OS/driver info
    description:     str = ""
    hwid:            str = ""
    manufacturer:    str = ""
    serial_number:   str = ""
    vid:             Optional[int] = None
    pid:             Optional[int] = None

    # Registry match (None = unknown device)
    descriptor:      Optional[DeviceDescriptor] = None

    # Convenience
    @property
    def display_name(self) -> str:
        if self.descriptor:
            return self.descriptor.display_name
        return self.description or self.address

    @property
    def device_type(self) -> str:
        return self.descriptor.device_type if self.descriptor else DTYPE_UNKNOWN

    @property
    def is_known(self) -> bool:
        return self.descriptor is not None


# ------------------------------------------------------------------ #
#  Scan report                                                         #
# ------------------------------------------------------------------ #

@dataclass
class ScanReport:
    timestamp:      float = field(default_factory=time.time)
    devices:        List[DiscoveredDevice] = field(default_factory=list)
    errors:         dict[str, str]         = field(default_factory=dict)
    # keys: "serial", "usb", "ethernet", "pcie"

    def by_type(self, connection_type: str) -> List[DiscoveredDevice]:
        return [d for d in self.devices
                if d.connection_type == connection_type]

    def known_only(self) -> List[DiscoveredDevice]:
        return [d for d in self.devices if d.is_known]


# ------------------------------------------------------------------ #
#  Serial / COM port scanner                                          #
# ------------------------------------------------------------------ #

class SerialScanner:
    """Uses pyserial's port enumeration — always available."""

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        try:
            import serial.tools.list_ports as lp
        except ImportError:
            return [], "pyserial not installed"

        results = []
        for port in lp.comports():
            desc = port.description or ""
            hwid = port.hwid or ""

            # Parse VID/PID from hwid string (e.g. "USB VID:PID=0403:6001")
            vid, pid = None, None
            if "VID:PID=" in hwid.upper():
                try:
                    vp = hwid.upper().split("VID:PID=")[1].split()[0]
                    v, p = vp.split(":")
                    vid, pid = int(v, 16), int(p, 16)
                except Exception:
                    pass

            descriptor = None
            if vid and pid:
                descriptor = find_by_usb(vid, pid)
            if descriptor is None:
                descriptor = find_by_serial_pattern(desc, hwid)

            results.append(DiscoveredDevice(
                connection_type = CONN_SERIAL,
                address         = port.device,
                description     = desc,
                hwid            = hwid,
                manufacturer    = getattr(port, "manufacturer", "") or "",
                serial_number   = getattr(port, "serial_number", "") or "",
                vid             = vid,
                pid             = pid,
                descriptor      = descriptor,
            ))
        return results, None


# ------------------------------------------------------------------ #
#  USB scanner (non-serial USB devices)                               #
# ------------------------------------------------------------------ #

class UsbScanner:
    """
    Uses pyusb for non-serial USB device enumeration.
    Falls back gracefully if pyusb or libusb is not installed.
    """

    # VIDs already covered by serial scanner — skip duplicates
    SERIAL_VIDS = {0x0403, 0x2341, 0x1A86}

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        try:
            import usb.core
            import usb.util
        except ImportError:
            return [], "pyusb not installed (pip install pyusb)"

        results = []
        try:
            devices = usb.core.find(find_all=True)
        except Exception as e:
            return [], f"USB scan failed: {e}"

        for dev in devices:
            vid = dev.idVendor
            pid = dev.idProduct

            if vid in self.SERIAL_VIDS:
                continue   # already handled by serial scanner

            try:
                mfr = usb.util.get_string(dev, dev.iManufacturer) or ""
            except Exception:
                mfr = ""
            try:
                prod = usb.util.get_string(dev, dev.iProduct) or ""
            except Exception:
                prod = ""
            try:
                sn = usb.util.get_string(dev, dev.iSerialNumber) or ""
            except Exception:
                sn = ""

            descriptor = find_by_usb(vid, pid)
            if descriptor is None:
                descriptor = find_by_serial_pattern(f"{mfr} {prod}")

            addr = f"USB {vid:04X}:{pid:04X}"
            if dev.bus and dev.address:
                addr = f"USB bus{dev.bus} dev{dev.address} ({vid:04X}:{pid:04X})"

            results.append(DiscoveredDevice(
                connection_type = CONN_USB,
                address         = addr,
                description     = f"{mfr} {prod}".strip() or addr,
                manufacturer    = mfr,
                serial_number   = sn,
                vid             = vid,
                pid             = pid,
                descriptor      = descriptor,
            ))
        return results, None


# ------------------------------------------------------------------ #
#  Network / Ethernet scanner                                         #
# ------------------------------------------------------------------ #

_NETWORK_TARGETS = [
    # (tcp_port, banner_hint, timeout_s)
    (3956,  "GigE Vision",   0.3),   # Basler / GigE cameras
    (5555,  "VISA",          0.3),   # Rigol, Keysight LXI
    (5025,  "SCPI",          0.3),   # Generic SCPI instruments
    (23,    "telnet",        0.3),   # Some TEC controllers
]

_SCAN_SUBNET_LAST_OCTET = range(1, 255)


class NetworkScanner:
    """
    Probes the local subnet for devices on well-known instrument TCP ports.
    Runs probes in parallel threads to keep scan time under 3 seconds.
    """

    def scan(self,
             subnet: str = "",
             progress_cb: Optional[Callable[[int, int], None]] = None
             ) -> tuple[List[DiscoveredDevice], Optional[str]]:

        if not subnet:
            subnet = self._detect_subnet()
        if not subnet:
            return [], "Could not detect local subnet"

        results = []
        lock    = threading.Lock()
        tasks   = []

        for last in _SCAN_SUBNET_LAST_OCTET:
            ip = f"{subnet}.{last}"
            for port, hint, timeout in _NETWORK_TARGETS:
                tasks.append((ip, port, hint, timeout))

        completed = [0]
        total     = len(tasks)

        def probe(ip, port, hint, timeout):
            try:
                with socket.create_connection((ip, port), timeout=timeout) as s:
                    # Try to read a banner
                    s.settimeout(timeout)
                    banner = ""
                    try:
                        banner = s.recv(256).decode("ascii", errors="replace")
                    except Exception:
                        pass

                    desc = banner.strip()[:80] or hint
                    descriptor = None
                    for d in DEVICE_REGISTRY.values():
                        if d.tcp_port == port:
                            if (d.tcp_banner is None
                                    or d.tcp_banner.lower() in desc.lower()
                                    or d.tcp_banner.lower() in banner.lower()):
                                descriptor = d
                                break

                    with lock:
                        results.append(DiscoveredDevice(
                            connection_type = CONN_ETHERNET,
                            address         = f"{ip}:{port}",
                            description     = desc,
                            descriptor      = descriptor,
                        ))
            except (ConnectionRefusedError, OSError, TimeoutError):
                pass
            finally:
                with lock:
                    completed[0] += 1
                    if progress_cb:
                        progress_cb(completed[0], total)

        threads = [threading.Thread(target=probe, args=t, daemon=True)
                   for t in tasks]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        return results, None

    def _detect_subnet(self) -> str:
        """Return the local subnet prefix (e.g. '192.168.1')."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ".".join(ip.split(".")[:3])
        except Exception:
            return ""


# ------------------------------------------------------------------ #
#  NI / PCIe scanner                                                  #
# ------------------------------------------------------------------ #

class NiScanner:
    """
    Enumerates NI hardware via nifpga system resource list.
    Falls back to pyvisa / NI-VISA resource manager for DAQ devices.
    """

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        results = []
        error   = None

        # ---- NI-FPGA / CompactRIO ----
        try:
            import nifpga
            # nifpga doesn't have a native list — parse common resource names
            for resource in self._probe_ni_resources():
                descriptor = find_by_ni_pattern(resource)
                results.append(DiscoveredDevice(
                    connection_type = CONN_PCIE,
                    address         = resource,
                    description     = descriptor.display_name if descriptor
                                      else f"NI Device ({resource})",
                    descriptor      = descriptor,
                ))
        except ImportError:
            error = "nifpga not installed"
        except Exception as e:
            error = f"NI-FPGA scan error: {e}"

        # ---- NI-VISA (DAQmx, USB-based NI devices) ----
        try:
            import pyvisa
            rm = pyvisa.ResourceManager()
            for rname in rm.list_resources():
                if any(rname.upper().startswith(p)
                       for p in ["USB", "GPIB", "ASRL", "TCPIP"]):
                    continue   # handled by other scanners
                descriptor = find_by_ni_pattern(rname)
                if descriptor:
                    results.append(DiscoveredDevice(
                        connection_type = CONN_PCIE,
                        address         = rname,
                        description     = descriptor.display_name,
                        descriptor      = descriptor,
                    ))
        except ImportError:
            pass
        except Exception:
            pass

        return results, error

    def _probe_ni_resources(self) -> List[str]:
        """
        List NI resource names using VISA or NI-DAQmx enumeration.
        Returns only resources that physically exist.
        """
        # Prefer PyVISA resource enumeration — zero false positives
        try:
            import pyvisa
            rm    = pyvisa.ResourceManager()
            found = []
            for rname in rm.list_resources():
                upper = rname.upper()
                if any(k in upper for k in ("RIO", "CRIO", "FPGA", "DEV")):
                    found.append(rname)
            return found
        except Exception:
            pass

        # Fallback: NI-DAQmx device list
        try:
            import nidaqmx
            system = nidaqmx.system.System.local()
            return [d.name for d in system.devices]
        except Exception:
            pass

        return []


# ------------------------------------------------------------------ #
#  Main scanner                                                        #
# ------------------------------------------------------------------ #

class DeviceScanner:
    """
    Runs all four sub-scanners and returns a consolidated ScanReport.
    Each sub-scanner runs in its own thread; total scan time is
    bounded by the network timeout (≈3 seconds).

    Network scanning notes
    ----------------------
    The Ethernet scanner probes 254 × 4 port combinations on the local
    subnet in parallel, which may trigger intrusion-detection alerts on
    corporate or lab networks. For this reason, network scanning is
    **opt-in** and disabled by default.

    To enable: call scan(include_network=True) or toggle the checkbox
    in the Device Manager dialog.
    """

    def scan(self,
             include_network: bool = False,   # opt-in — see class docstring
             progress_cb: Optional[Callable[[str], None]] = None
             ) -> ScanReport:

        report  = ScanReport()
        lock    = threading.Lock()

        def run(name: str, fn):
            if progress_cb:
                progress_cb(f"Scanning {name}…")
            try:
                devs, err = fn()
                with lock:
                    report.devices.extend(devs)
                    if err:
                        report.errors[name] = err
            except Exception as e:
                with lock:
                    report.errors[name] = str(e)
            if progress_cb:
                progress_cb(f"{name} scan complete.")

        serial_t = threading.Thread(
            target=run, args=("serial", SerialScanner().scan), daemon=True)
        usb_t    = threading.Thread(
            target=run, args=("usb",    UsbScanner().scan), daemon=True)
        ni_t     = threading.Thread(
            target=run, args=("pcie",   NiScanner().scan), daemon=True)

        threads = [serial_t, usb_t, ni_t]

        if include_network:
            net_t = threading.Thread(
                target=run, args=("ethernet", NetworkScanner().scan),
                daemon=True)
            threads.append(net_t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=8.0)

        # Deduplicate by address
        seen    = set()
        unique  = []
        for d in report.devices:
            if d.address not in seen:
                seen.add(d.address)
                unique.append(d)
        report.devices = unique
        report.timestamp = time.time()

        return report
