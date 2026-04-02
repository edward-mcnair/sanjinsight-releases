"""
hardware/discovery_engine.py

Unified hardware discovery — combines passive VID/PID scanning with
active protocol probing to produce a complete, unambiguous device inventory.

Workflow
--------
1. Run ``DeviceScanner.scan()`` (passive: VID/PID + string matching)
2. Identify ambiguous ports (same VID/PID maps to multiple device types)
3. Run ``ProtocolProber`` on ambiguous ports (active: MeCom handshake)
4. Merge results into a ``DiscoveryReport``
5. Cache results to ``~/.microsanj/device_cache.json`` for fast startup

Usage
-----
    from hardware.discovery_engine import DiscoveryEngine

    engine = DiscoveryEngine()
    report = engine.discover(progress_cb=print)
    for dev in report.resolved:
        print(f"{dev.display_name} on {dev.port} ({dev.confidence})")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from hardware.protocol_prober import (
    ProbeResult,
    probe_mecom_port,
    probe_all_serial,
)

log = logging.getLogger(__name__)

# Cache file for remembered port → device mappings
_CACHE_DIR = Path.home() / ".microsanj"
_CACHE_FILE = _CACHE_DIR / "device_cache.json"


@dataclass
class ResolvedDevice:
    """A device that has been identified (passively or by protocol probe)."""
    device_uid: str              # registry UID
    display_name: str            # human-readable
    port: str                    # COM port / tty path / USB path
    connection_type: str         # "serial", "usb", "pcie", "network"
    confidence: str = "passive"  # "passive" | "cached" | "protocol_confirmed"
    serial_number: str = ""
    firmware_version: str = ""
    mecom_address: int = -1
    vid: Optional[int] = None
    pid: Optional[int] = None


@dataclass
class DiscoveryReport:
    """Complete result of a discovery run."""
    timestamp: float = field(default_factory=time.time)
    resolved: List[ResolvedDevice] = field(default_factory=list)
    unresolved_ports: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    scan_duration_s: float = 0.0

    def find(self, device_uid: str) -> Optional[ResolvedDevice]:
        """Find a resolved device by UID."""
        for dev in self.resolved:
            if dev.device_uid == device_uid:
                return dev
        return None

    def find_by_port(self, port: str) -> List[ResolvedDevice]:
        """Find all resolved devices on a given port (RS-485 bus sharing)."""
        return [d for d in self.resolved if d.port == port]


class DiscoveryEngine:
    """Orchestrates passive scanning + active protocol probing."""

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._load_cache()

    def discover(
        self,
        progress_cb: Optional[Callable[[str, int], None]] = None,
        use_cache: bool = True,
        probe_timeout: float = 1.5,
    ) -> DiscoveryReport:
        """Run a full discovery scan.

        Parameters
        ----------
        progress_cb : callable | None
            Called with (message: str, percent: int) during scanning.
        use_cache : bool
            If True, check cache before probing known USB serial numbers.
        probe_timeout : float
            Per-command timeout for protocol probes.

        Returns
        -------
        DiscoveryReport
        """
        t0 = time.monotonic()
        report = DiscoveryReport()

        def _progress(msg: str, pct: int = 0):
            if progress_cb:
                progress_cb(msg, pct)
            log.debug("Discovery: %s", msg)

        # ── Step 1: Passive serial port scan ─────────────────────────────
        _progress("Scanning serial ports…", 10)
        from hardware.device_scanner import SerialScanner, DiscoveredDevice
        scanner = SerialScanner()
        serial_devs, scan_err = scanner.scan()
        if scan_err:
            report.errors["serial_scan"] = scan_err

        # ── Step 2: Identify ambiguous ports ─────────────────────────────
        # Group by port → list of possible device UIDs
        port_candidates: Dict[str, List[DiscoveredDevice]] = {}
        for dev in serial_devs:
            port_candidates.setdefault(dev.address, []).append(dev)

        ambiguous_ports = {
            port: devs for port, devs in port_candidates.items()
            if len(devs) > 1  # multiple registry matches for same port
            or (devs and devs[0].vid == 0x0403 and devs[0].pid == 0x6001)
            # FTDI 0403:6001 is always ambiguous (TEC vs LDD)
        }

        # Non-ambiguous ports → resolve directly from passive scan
        for port, devs in port_candidates.items():
            if port not in ambiguous_ports:
                for dev in devs:
                    if dev.descriptor:
                        report.resolved.append(ResolvedDevice(
                            device_uid=dev.descriptor.uid,
                            display_name=dev.descriptor.display_name,
                            port=port,
                            connection_type=dev.connection_type,
                            confidence="passive",
                            serial_number=dev.serial_number,
                            vid=dev.vid,
                            pid=dev.pid,
                        ))

        # ── Step 3: Check cache for ambiguous ports ──────────────────────
        ports_to_probe = []
        if use_cache:
            for port, devs in ambiguous_ports.items():
                sn = devs[0].serial_number if devs else ""
                cached = self._cache.get(sn) if sn else None
                if cached and cached.get("port") == port:
                    _progress(f"Using cached ID for {port}", 30)
                    report.resolved.append(ResolvedDevice(
                        device_uid=cached["device_uid"],
                        display_name=cached.get("display_name", ""),
                        port=port,
                        connection_type="serial",
                        confidence="cached",
                        serial_number=sn,
                        mecom_address=cached.get("mecom_address", -1),
                        vid=devs[0].vid if devs else None,
                        pid=devs[0].pid if devs else None,
                    ))
                else:
                    ports_to_probe.append(port)
        else:
            ports_to_probe = list(ambiguous_ports.keys())

        # ── Step 4: Active protocol probing ──────────────────────────────
        total_probes = len(ports_to_probe)
        for i, port in enumerate(ports_to_probe):
            pct = 40 + int(50 * (i / max(total_probes, 1)))
            _progress(f"Probing {port} for Meerstetter devices… "
                      f"[{i+1}/{total_probes}]", pct)

            probe_results = probe_mecom_port(
                port, baudrate=57600, timeout=probe_timeout)

            found_any = False
            for pr in probe_results:
                if pr.is_identified:
                    found_any = True
                    report.resolved.append(ResolvedDevice(
                        device_uid=pr.device_uid,
                        display_name=pr.display_name,
                        port=port,
                        connection_type="serial",
                        confidence=pr.confidence,
                        serial_number=pr.serial_number,
                        firmware_version=pr.firmware_version,
                        mecom_address=pr.mecom_address,
                        vid=0x0403,
                        pid=0x6001,
                    ))
                    # Update cache
                    devs = ambiguous_ports.get(port, [])
                    sn = devs[0].serial_number if devs else ""
                    if sn:
                        self._cache[sn] = {
                            "device_uid": pr.device_uid,
                            "display_name": pr.display_name,
                            "port": port,
                            "mecom_address": pr.mecom_address,
                            "timestamp": time.time(),
                        }
                elif pr.error:
                    report.errors[f"probe_{port}"] = pr.error

            if not found_any:
                report.unresolved_ports.append(port)

        # ── Step 5: Camera discovery (non-serial) ────────────────────────
        _progress("Scanning for cameras…", 92)
        _discover_cameras(report, _progress)

        # ── Step 6: Save cache ───────────────────────────────────────────
        self._save_cache()

        report.scan_duration_s = time.monotonic() - t0
        _progress(f"Discovery complete: {len(report.resolved)} device(s) found "
                  f"in {report.scan_duration_s:.1f}s", 100)
        return report

    def invalidate_cache(self, port: Optional[str] = None):
        """Invalidate cached port mappings.

        Parameters
        ----------
        port : str | None
            Invalidate entries for this port only.  None = clear all.
        """
        if port is None:
            self._cache.clear()
        else:
            self._cache = {
                k: v for k, v in self._cache.items()
                if v.get("port") != port
            }
        self._save_cache()

    # ── Cache persistence ────────────────────────────────────────────────

    def _load_cache(self):
        try:
            if _CACHE_FILE.exists():
                with open(_CACHE_FILE) as f:
                    self._cache = json.load(f)
                # Expire entries older than 30 days
                cutoff = time.time() - (30 * 86400)
                self._cache = {
                    k: v for k, v in self._cache.items()
                    if v.get("timestamp", 0) > cutoff
                }
        except Exception:
            log.debug("DiscoveryEngine: cache load failed", exc_info=True)
            self._cache = {}

    def _save_cache(self):
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(_CACHE_FILE, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception:
            log.debug("DiscoveryEngine: cache save failed", exc_info=True)


# ---------------------------------------------------------------------------
# Camera discovery (Basler + FLIR)
# ---------------------------------------------------------------------------

def _discover_cameras(report: DiscoveryReport, progress_cb):
    """Detect connected cameras via pypylon and OpenCV."""
    # Basler cameras via pypylon
    try:
        from pypylon import pylon
        tlf = pylon.TlFactory.GetInstance()
        devices = tlf.EnumerateDevices()
        for dev in devices:
            report.resolved.append(ResolvedDevice(
                device_uid="basler_camera",
                display_name=f"Basler {dev.GetModelName()}",
                port=dev.GetSerialNumber(),
                connection_type="usb",
                confidence="protocol_confirmed",
                serial_number=dev.GetSerialNumber(),
                firmware_version=dev.GetDeviceVersion() if hasattr(dev, 'GetDeviceVersion') else "",
            ))
    except ImportError:
        log.debug("pypylon not available — skipping Basler camera discovery")
    except Exception as exc:
        report.errors["basler_camera"] = str(exc)
        log.debug("Basler camera discovery failed: %s", exc)

    # FLIR Boson is detected via UVC (OpenCV) at connect time — not
    # enumerable without opening a video capture, so we skip it here.
    # The Boson driver handles its own auto-detection via video index scanning.
