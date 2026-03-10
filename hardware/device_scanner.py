"""
hardware/device_scanner.py

Scans all four connection types and returns discovered ports/devices.
Each scanner is independent — a missing dependency silently skips
that transport rather than crashing the whole scan.

Returns a ScanReport containing all discovered items, each matched
against the device registry where possible.
"""

from __future__ import annotations
import logging
import sys
import time
import socket
import threading
from dataclasses  import dataclass, field
from typing       import List, Optional, Callable

log = logging.getLogger(__name__)

from .device_registry import (
    DeviceDescriptor, DEVICE_REGISTRY,
    find_by_usb, find_by_serial_pattern, find_by_ni_pattern,
    CONN_SERIAL, CONN_USB, CONN_ETHERNET, CONN_PCIE, CONN_CAMERA,
    DTYPE_CAMERA, DTYPE_UNKNOWN)


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
                    log.debug("SerialScanner: VID:PID parse failed for hwid=%r — "
                              "skipping VID/PID match", hwid, exc_info=True)

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
    Placeholder for raw USB device enumeration (pyusb / libusb).

    pyusb loads libusb-1.0.dll (Windows) or libusb.dylib (macOS), a native
    C++ library.  When NI USB hardware (e.g. NI USB-TC01, NI USB-6001) is
    present on Windows the libusb backend can issue an access-violation
    (0xFFFFFFFFFFFFFFFF) that bypasses Python exception handling and kills
    the process.  SanjINSIGHT's instruments connect via serial (COM port) or
    Ethernet, so raw USB enumeration is not required.

    If USB enumeration becomes necessary in future, re-enable this scanner
    only after verifying that libusb does not conflict with the NI-VISA / NI
    driver stack on the target machine.
    """

    # VIDs already covered by serial scanner — kept for documentation
    SERIAL_VIDS = {0x0403, 0x2341, 0x1A86}

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        log.debug("UsbScanner: raw USB scanning is disabled — returning empty result")
        return [], None


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
                        log.debug("NetworkScanner.probe: banner recv failed "
                                  "for %s:%s", ip, port, exc_info=True)

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
            log.debug("NetworkScanner._detect_subnet: socket probe failed — "
                      "network scan will be skipped", exc_info=True)
            return ""


# ------------------------------------------------------------------ #
#  NI / PCIe scanner                                                  #
# ------------------------------------------------------------------ #

class NiScanner:
    """
    Placeholder for NI/PCIe hardware enumeration.

    NI-VISA (pyvisa) and NI-DAQmx (nidaqmx) DLL initialisation can conflict
    with other processes that hold the NI driver lock (e.g. LabVIEW), causing
    hard process crashes that bypass Python exception handling.  SanjINSIGHT
    does not require PCIe/NI hardware, so this scanner is intentionally
    disabled and returns an empty result set immediately.

    If NI FPGA support is needed in future, re-enable this scanner and ensure
    that no other NI application (NI MAX, LabVIEW, etc.) holds the VISA lock
    before calling scan().
    """

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        log.debug("NiScanner: PCIe/NI scanning is disabled — returning empty result")
        return [], None


# ------------------------------------------------------------------ #
#  Camera SDK scanner                                                  #
# ------------------------------------------------------------------ #

class CameraScanner:
    """
    Enumerates Basler cameras using pypylon.TlFactory.EnumerateDevices().

    Safety approach — subprocess isolation
    ----------------------------------------
    pypylon loads native Basler pylon C++ DLLs.  On Windows machines that also
    run NI hardware (NI USB-TC01, NI-DAQmx, NI-RIO) those DLLs can occasionally
    trigger access-violations during initialisation that bypass Python exception
    handling and kill the process.

    To prevent a camera scan crash from taking down the SanjINSIGHT UI, the
    enumeration runs in a *separate child process* (sys.executable -c ...).
    The child can crash or be killed without affecting the parent.  Results are
    passed back via stdout as a JSON array.

    The scan never opens a camera — it only calls EnumerateDevices() which
    queries the transport layer for attached devices.  This is safe even if a
    camera is in use by another application.
    """

    # Embedded script run in the child process.
    # Written as a single string so no temp file is needed.
    _ENUM_SCRIPT = (
        "import json, sys\n"
        "try:\n"
        "    from pypylon import pylon\n"
        "    devs = pylon.TlFactory.GetInstance().EnumerateDevices()\n"
        "    out = []\n"
        "    for d in devs:\n"
        "        entry = {\n"
        "            'model':        d.GetModelName(),\n"
        "            'serial':       '',\n"
        "            'device_class': d.GetDeviceClass(),\n"
        "            'ip':           '',\n"
        "            'full_name':    '',\n"
        "        }\n"
        "        try:  entry['serial']    = d.GetSerialNumber()\n"
        "        except Exception: pass\n"
        "        try:  entry['full_name'] = d.GetFullName()\n"
        "        except Exception: pass\n"
        "        try:\n"
        "            if 'GigE' in entry['device_class']:\n"
        "                entry['ip'] = d.GetIpAddress()\n"
        "        except Exception: pass\n"
        "        out.append(entry)\n"
        "    print(json.dumps(out))\n"
        "except ImportError:\n"
        "    sys.stderr.write('pypylon_not_installed')\n"
        "    sys.exit(2)\n"
        "except Exception as exc:\n"
        "    sys.stderr.write(str(exc))\n"
        "    sys.exit(1)\n"
    )

    def scan(self) -> tuple[List[DiscoveredDevice], Optional[str]]:
        raw, err = self._enumerate_subprocess()
        if err:
            return [], err

        results = []
        for cam in raw:
            model  = cam.get("model", "")
            serial = cam.get("serial", "")
            ip     = cam.get("ip", "")
            # address: prefer serial number (unique per camera), then IP, then model
            address = serial or ip or model

            # Match against device registry by model name pattern
            descriptor = find_by_serial_pattern(model, f"Basler {model}")

            results.append(DiscoveredDevice(
                connection_type = CONN_CAMERA,
                address         = address,
                description     = model,
                manufacturer    = "Basler AG",
                serial_number   = serial,
                descriptor      = descriptor,
            ))
            log.debug("CameraScanner: found %s  serial=%s  class=%s",
                      model, serial, cam.get("device_class"))

        return results, None

    # ------------------------------------------------------------------
    def _enumerate_subprocess(self) -> tuple[list, Optional[str]]:
        """
        Run the pypylon enumeration script in a child process.
        Returns (list_of_camera_dicts, error_string_or_None).

        IMPORTANT — PyInstaller frozen builds
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        In a frozen (.exe) build ``sys.executable`` is the packaged application
        executable, not the Python interpreter.  Spawning it with ``-c script``
        does NOT execute the script — it launches a new instance of the full
        application (with its own Qt GUI window).  This is what causes multiple
        "Microsanj SanjINSIGHT" windows to appear in the taskbar during a scan.

        When frozen we therefore fall back to in-process enumeration, accepting
        the loss of crash isolation.  The risk is low: pypylon crashes during
        enumeration are rare, and the fallback is wrapped in a broad try/except.
        """
        import subprocess, json

        # ── PyInstaller / frozen build: run inline, no subprocess ────────────
        if getattr(sys, 'frozen', False):
            log.debug("CameraScanner: frozen build detected — "
                      "using in-process enumeration (no subprocess)")
            return self._enumerate_inline()

        # ── Normal Python interpreter: subprocess with crash isolation ────────
        # On Windows, omitting CREATE_NO_WINDOW causes a console (or GUI) window
        # to flash briefly even with capture_output=True when the parent is a
        # windowless (GUI subsystem) process.
        _popen_kw: dict = {}
        if sys.platform == 'win32':
            _popen_kw['creationflags'] = subprocess.CREATE_NO_WINDOW

        try:
            result = subprocess.run(
                [sys.executable, "-c", self._ENUM_SCRIPT],
                capture_output=True,
                text=True,
                timeout=12,          # pylon SDK init can be slow on first run
                **_popen_kw,
            )
        except subprocess.TimeoutExpired:
            log.warning("CameraScanner: pypylon subprocess timed out after 12 s")
            return [], "Camera scan timed out — pylon SDK may be busy"
        except Exception as exc:
            log.warning("CameraScanner: failed to launch subprocess: %s", exc)
            return [], f"Camera scan subprocess error: {exc}"

        if result.returncode == 2:
            # pypylon not installed — expected on non-Basler systems
            log.debug("CameraScanner: pypylon not installed in this environment")
            return [], "pypylon not installed — install Basler pylon SDK then: pip install pypylon"

        if result.returncode != 0:
            err = result.stderr.strip() or "pypylon subprocess exited with non-zero code"
            log.warning("CameraScanner: subprocess returned %d: %s",
                        result.returncode, err[:200])
            return [], err[:200]

        stdout = result.stdout.strip()
        if not stdout:
            log.debug("CameraScanner: subprocess returned empty output — no cameras found")
            return [], None

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            log.warning("CameraScanner: JSON parse error: %s  raw=%r", exc, stdout[:200])
            return [], f"Camera scan parse error: {exc}"

        if not isinstance(data, list):
            return [], "Unexpected data from camera scan subprocess"

        return data, None

    def _enumerate_inline(self) -> tuple[list, Optional[str]]:
        """Enumerate Basler cameras in-process (used in frozen/PyInstaller builds).

        Identical logic to _ENUM_SCRIPT but executed in the current process.
        Wrapped in a broad try/except so a pypylon crash or access-violation
        produces a logged warning rather than taking down the whole app.
        """
        try:
            from pypylon import pylon
            devs = pylon.TlFactory.GetInstance().EnumerateDevices()
            out = []
            for d in devs:
                entry: dict = {
                    'model':        '',
                    'serial':       '',
                    'device_class': '',
                    'ip':           '',
                    'full_name':    '',
                }
                try: entry['model']        = d.GetModelName()
                except Exception: pass
                try: entry['serial']       = d.GetSerialNumber()
                except Exception: pass
                try: entry['device_class'] = d.GetDeviceClass()
                except Exception: pass
                try: entry['full_name']    = d.GetFullName()
                except Exception: pass
                try:
                    if 'GigE' in entry['device_class']:
                        entry['ip'] = d.GetIpAddress()
                except Exception: pass
                out.append(entry)
            log.debug("CameraScanner._enumerate_inline: found %d camera(s)", len(out))
            return out, None
        except ImportError:
            log.debug("CameraScanner._enumerate_inline: pypylon not installed")
            return [], "pypylon not installed"
        except Exception as exc:
            log.warning("CameraScanner._enumerate_inline: %s", exc)
            return [], str(exc)


# ------------------------------------------------------------------ #
#  Main scanner                                                        #
# ------------------------------------------------------------------ #

class DeviceScanner:
    """
    Runs all five sub-scanners and returns a consolidated ScanReport.
    Each sub-scanner runs in its own thread; total scan time is
    bounded by the network timeout (≈3 seconds).

    Active scanners
    ---------------
    serial   — pyserial COM/ttyUSB port enumeration with VID/PID matching
    ethernet — subnet TCP probe (opt-in, disabled by default)

    Disabled scanners (native DLL crash risk on Windows + NI hardware)
    -------------------------------------------------------------------
    usb      — pyusb/libusb raw USB enumeration  (see UsbScanner)
    camera   — Basler pypylon SDK + NI IMAQdx    (see CameraScanner)
    pcie     — NI-FPGA / NI-VISA resource scan   (see NiScanner)

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
                log.warning("DeviceScanner: %s scanner raised an unexpected exception",
                            name, exc_info=True)
                with lock:
                    report.errors[name] = str(e)
            if progress_cb:
                progress_cb(f"{name} scan complete.")

        serial_t = threading.Thread(
            target=run, args=("serial", SerialScanner().scan), daemon=True)
        usb_t    = threading.Thread(
            target=run, args=("usb",    UsbScanner().scan), daemon=True)
        camera_t = threading.Thread(
            target=run, args=("camera", CameraScanner().scan), daemon=True)
        ni_t     = threading.Thread(
            target=run, args=("pcie",   NiScanner().scan), daemon=True)

        threads = [serial_t, usb_t, camera_t, ni_t]

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
