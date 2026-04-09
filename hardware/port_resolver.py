"""
hardware/port_resolver.py

USB-fingerprint-based serial port resolver.

Identifies physical serial devices by stable USB attributes (serial number,
VID:PID, location, manufacturer/product strings) instead of volatile COM
port numbers that shift between reboots.

Usage
-----
    from hardware.port_resolver import PortResolver

    resolver = PortResolver()
    resolver.snapshot()                     # enumerate all ports
    port = resolver.resolve("meerstetter_tec_1089")  # → "COM4" (or whatever it is now)

The resolver stores USB fingerprints in ``device_params.{uid}.usb_fingerprint``
via the config module.  On subsequent launches it matches the saved fingerprint
against the current port enumeration to find the correct COM port, regardless
of whether the port number has changed.

Design
------
Match priority (highest first):
    1. USB serial number (unique per FTDI/CH340 chip — best identifier)
    2. VID:PID (ambiguous for FTDI 0403:6001 — used as a filter, not identity)
    3. Manufacturer / product / interface strings
    4. USB location (stable if the physical USB topology doesn't change)
    5. COM port name (last resort — volatile)

Two devices that score identically on the same port → ambiguous → error.
A device that matches no port → absent → skip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
#  Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class USBFingerprint:
    """Stable identity attributes for a USB-serial device."""
    vid: Optional[int] = None
    pid: Optional[int] = None
    serial_number: str = ""
    location: str = ""
    manufacturer: str = ""
    product: str = ""
    interface: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "USBFingerprint":
        return cls(
            vid=d.get("vid"),
            pid=d.get("pid"),
            serial_number=d.get("serial_number", ""),
            location=d.get("location", ""),
            manufacturer=d.get("manufacturer", ""),
            product=d.get("product", ""),
            interface=d.get("interface", ""),
        )

    @classmethod
    def from_port_info(cls, p) -> "USBFingerprint":
        """Build from a ``serial.tools.list_ports.ListPortInfo`` object."""
        return cls(
            vid=getattr(p, "vid", None),
            pid=getattr(p, "pid", None),
            serial_number=(getattr(p, "serial_number", None) or "").strip(),
            location=(getattr(p, "location", None) or "").strip(),
            manufacturer=(getattr(p, "manufacturer", None) or "").strip(),
            product=(getattr(p, "product", None) or "").strip(),
            interface=(getattr(p, "interface", None) or "").strip(),
        )

    def is_empty(self) -> bool:
        return (
            self.vid is None
            and self.pid is None
            and not self.serial_number
            and not self.location
        )


@dataclass
class PortInfo:
    """Snapshot of a physical serial port with its USB fingerprint."""
    device: str                         # COM port name (e.g. "COM4")
    description: str = ""
    hwid: str = ""
    fingerprint: USBFingerprint = field(default_factory=USBFingerprint)


# ──────────────────────────────────────────────────────────────────────────────
#  Scoring
# ──────────────────────────────────────────────────────────────────────────────

def _score(port_fp: USBFingerprint, saved_fp: USBFingerprint) -> int:
    """Score how well *port_fp* matches *saved_fp*.

    Returns -1 if a required field mismatches (hard reject).
    Returns 0+ for the match quality (higher = better).
    """
    score = 0

    # ── USB serial number (most specific) ────────────────────────────
    if saved_fp.serial_number:
        if not port_fp.serial_number:
            return -1  # saved expects a serial, port has none
        if port_fp.serial_number.lower() == saved_fp.serial_number.lower():
            score += 100
        else:
            return -1  # different serial → definitely not the same device

    # ── VID:PID ──────────────────────────────────────────────────────
    if saved_fp.vid is not None:
        if port_fp.vid != saved_fp.vid:
            return -1
        score += 20
    if saved_fp.pid is not None:
        if port_fp.pid != saved_fp.pid:
            return -1
        score += 20

    # ── Manufacturer string ──────────────────────────────────────────
    if saved_fp.manufacturer:
        if saved_fp.manufacturer.lower() in (port_fp.manufacturer or "").lower():
            score += 5
        # Not a hard reject — manufacturer strings can vary

    # ── Product string ───────────────────────────────────────────────
    if saved_fp.product:
        if saved_fp.product.lower() in (port_fp.product or "").lower():
            score += 5

    # ── USB location (topology) ──────────────────────────────────────
    if saved_fp.location:
        if port_fp.location and port_fp.location == saved_fp.location:
            score += 10

    return score


# ──────────────────────────────────────────────────────────────────────────────
#  Resolver
# ──────────────────────────────────────────────────────────────────────────────

class PortResolver:
    """Resolves logical device UIDs to physical COM ports via USB fingerprints.

    Typical usage::

        resolver = PortResolver()
        resolver.snapshot()                 # enumerate hardware
        port = resolver.resolve("meerstetter_tec_1089")
    """

    def __init__(self):
        self._ports: list[PortInfo] = []
        self._claimed: set[str] = set()    # ports already assigned

    # ── Enumeration ──────────────────────────────────────────────────

    def snapshot(self) -> list[PortInfo]:
        """Take a fresh snapshot of all serial ports on the system."""
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            log.warning("pyserial not available — port resolution disabled")
            self._ports = []
            return self._ports

        self._ports = []
        self._claimed = set()
        for p in sorted(comports(), key=lambda x: x.device):
            info = PortInfo(
                device=p.device,
                description=getattr(p, "description", "") or "",
                hwid=getattr(p, "hwid", "") or "",
                fingerprint=USBFingerprint.from_port_info(p),
            )
            self._ports.append(info)
            fp = info.fingerprint
            log.debug(
                "Port %s: VID=%s PID=%s serial=%r loc=%r mfr=%r prod=%r",
                info.device,
                f"0x{fp.vid:04X}" if fp.vid is not None else "None",
                f"0x{fp.pid:04X}" if fp.pid is not None else "None",
                fp.serial_number, fp.location,
                fp.manufacturer, fp.product,
            )

        log.info("PortResolver: enumerated %d serial port(s)", len(self._ports))
        return list(self._ports)

    @property
    def ports(self) -> list[PortInfo]:
        return list(self._ports)

    # ── Resolution ───────────────────────────────────────────────────

    def resolve(self, uid: str, saved_fp: USBFingerprint | None = None,
                saved_port: str = "") -> str | None:
        """Find the current COM port for *uid* using its saved fingerprint.

        Parameters
        ----------
        uid : str
            Logical device UID (e.g. ``"meerstetter_tec_1089"``).
        saved_fp : USBFingerprint | None
            The fingerprint saved from the last successful connection.
            If ``None`` or empty, falls back to *saved_port*.
        saved_port : str
            The last-known COM port (fallback if fingerprint is unavailable).

        Returns
        -------
        str | None
            The resolved COM port name, or ``None`` if the device was not
            found in the current port enumeration.
        """
        if saved_fp and not saved_fp.is_empty():
            # Fingerprint-based resolution
            candidates: list[tuple[int, PortInfo]] = []
            for pi in self._ports:
                if pi.device in self._claimed:
                    continue
                s = _score(pi.fingerprint, saved_fp)
                if s >= 0:
                    candidates.append((s, pi))

            candidates.sort(key=lambda x: x[0], reverse=True)

            if candidates:
                best_score, best = candidates[0]
                # Reject ambiguous matches
                if (len(candidates) > 1
                        and candidates[0][0] == candidates[1][0]
                        and candidates[0][0] < 100):
                    log.warning(
                        "PortResolver: ambiguous match for %s — %s and %s "
                        "both scored %d.  Falling back to saved port.",
                        uid, candidates[0][1].device,
                        candidates[1][1].device, best_score)
                else:
                    self._claimed.add(best.device)
                    if best.device != saved_port:
                        log.info(
                            "PortResolver: %s moved from %s to %s "
                            "(matched by USB fingerprint, score=%d)",
                            uid, saved_port or "(none)", best.device,
                            best_score)
                    else:
                        log.info(
                            "PortResolver: %s → %s (fingerprint match, "
                            "score=%d)", uid, best.device, best_score)
                    return best.device

        # Fallback: use saved COM port if it exists in the current snapshot
        if saved_port:
            for pi in self._ports:
                if pi.device == saved_port and pi.device not in self._claimed:
                    log.info(
                        "PortResolver: %s → %s (COM port fallback, "
                        "no fingerprint)", uid, saved_port)
                    self._claimed.add(saved_port)
                    return saved_port
            log.warning(
                "PortResolver: %s saved port %s not found in current "
                "enumeration", uid, saved_port)

        return None

    def resolve_all(self, device_map: dict[str, tuple[USBFingerprint | None, str]]
                    ) -> dict[str, str | None]:
        """Resolve multiple devices at once.

        Parameters
        ----------
        device_map : dict
            ``{uid: (saved_fingerprint, saved_port)}``

        Returns
        -------
        dict
            ``{uid: resolved_port_or_None}``
        """
        result: dict[str, str | None] = {}
        # Sort by fingerprint quality: devices with serial numbers first
        # (most specific), then by saved port.  This ensures the best
        # matches claim ports before ambiguous ones.
        def _sort_key(item):
            uid, (fp, port) = item
            has_serial = 1 if (fp and fp.serial_number) else 0
            return (-has_serial, uid)

        for uid, (fp, port) in sorted(device_map.items(), key=_sort_key):
            result[uid] = self.resolve(uid, fp, port)
        return result

    # ── Fingerprint capture ──────────────────────────────────────────

    def get_fingerprint(self, port_name: str) -> USBFingerprint | None:
        """Return the USB fingerprint for a specific port in the snapshot."""
        for pi in self._ports:
            if pi.device == port_name:
                return pi.fingerprint
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  Persistence helpers
# ──────────────────────────────────────────────────────────────────────────────

def save_fingerprint(uid: str, fp: USBFingerprint) -> None:
    """Persist a device's USB fingerprint to config preferences."""
    try:
        import config as _cfg
        _cfg.set_pref(f"device_params.{uid}.usb_fingerprint", fp.to_dict())
    except Exception:
        log.debug("Could not save fingerprint for %s", uid, exc_info=True)


def load_fingerprint(uid: str) -> USBFingerprint | None:
    """Load a device's saved USB fingerprint from config preferences."""
    try:
        import config as _cfg
        d = _cfg.get_pref(f"device_params.{uid}.usb_fingerprint", None)
        if d and isinstance(d, dict):
            return USBFingerprint.from_dict(d)
    except Exception:
        log.debug("Could not load fingerprint for %s", uid, exc_info=True)
    return None
