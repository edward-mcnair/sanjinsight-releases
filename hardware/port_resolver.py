"""
hardware/port_resolver.py

USB-fingerprint-based serial port resolver.

Identifies physical serial devices by stable USB attributes (serial number,
VID:PID, location, manufacturer/product strings) instead of volatile COM
port numbers that shift between reboots.

Design principles
-----------------
1. COM port numbers are NEVER treated as device identity — only as a
   last-resort hint when no fingerprint is available.
2. Duplicate port claims are a hard error — if two logical devices resolve
   to the same physical port, the resolver raises ``AmbiguousPortError``
   before any connection is attempted.
3. After opening a resolved port, callers MUST verify device identity via
   a protocol handshake (IDENT for Arduino, MeCom query for Meerstetter).
   The ``verify_handshake()`` helper provides this.
4. The resolver owns a port-ownership registry.  Once a port is claimed,
   no second code path can re-claim it without explicitly releasing it.

Match priority (highest → lowest):
    1. USB serial number  (100 pts — unique per FTDI/CH340 chip)
    2. USB location        (10 pts — stable if physical topology unchanged)
    3. VID:PID             (40 pts — filter, not identity for shared PIDs)
    4. Manufacturer/product strings  (5 pts each — fuzzy tiebreaker)
    5. Saved COM port      (0 pts — volatile fallback, NOT scored)

Persistence
-----------
Fingerprints (not COM ports) are the primary stored identity.  If a device
has no USB serial number, ``location`` is persisted as a fallback.  COM port
is stored alongside but only as a hint for the very first migration from
older config.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
#  Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class AmbiguousPortError(RuntimeError):
    """Raised when two logical devices resolve to the same physical port."""

    def __init__(self, port: str, uid_a: str, uid_b: str):
        self.port = port
        self.uid_a = uid_a
        self.uid_b = uid_b
        super().__init__(
            f"Port conflict: {uid_a} and {uid_b} both resolved to {port}. "
            f"Run tools/dump_serial_ports.py to inspect USB fingerprints."
        )


class HandshakeMismatchError(RuntimeError):
    """Raised when a post-connect protocol handshake fails."""

    def __init__(self, uid: str, port: str, detail: str):
        self.uid = uid
        self.port = port
        super().__init__(
            f"{uid} on {port}: handshake failed — {detail}"
        )


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

    @property
    def stable_id(self) -> str:
        """Best available stable identifier (serial_number > location)."""
        if self.serial_number:
            return f"sn:{self.serial_number}"
        if self.location:
            return f"loc:{self.location}"
        if self.vid is not None and self.pid is not None:
            return f"vid:{self.vid:04x}:pid:{self.pid:04x}"
        return ""


@dataclass
class PortInfo:
    """Snapshot of a physical serial port with its USB fingerprint."""
    device: str                         # COM port name (e.g. "COM4")
    description: str = ""
    hwid: str = ""
    fingerprint: USBFingerprint = field(default_factory=USBFingerprint)


@dataclass
class ResolveResult:
    """Result of resolving a single device to a port."""
    port: str | None = None             # resolved COM port (None = not found)
    method: str = ""                    # "fingerprint", "com_hint", "" (not found)
    score: int = 0                      # fingerprint match score
    stable_id: str = ""                 # fingerprint stable_id that matched


# ──────────────────────────────────────────────────────────────────────────────
#  Scoring
# ──────────────────────────────────────────────────────────────────────────────

def _score(port_fp: USBFingerprint, saved_fp: USBFingerprint) -> int:
    """Score how well *port_fp* matches *saved_fp*.

    Returns -1 if a required field mismatches (hard reject).
    Returns 0+ for the match quality (higher = better).
    """
    score = 0

    # ── USB serial number (most specific — hard reject on mismatch) ──
    if saved_fp.serial_number:
        if not port_fp.serial_number:
            return -1
        if port_fp.serial_number.lower() == saved_fp.serial_number.lower():
            score += 100
        else:
            return -1  # different serial → definitely not the same device

    # ── VID:PID (hard reject on mismatch) ────────────────────────────
    if saved_fp.vid is not None:
        if port_fp.vid != saved_fp.vid:
            return -1
        score += 20
    if saved_fp.pid is not None:
        if port_fp.pid != saved_fp.pid:
            return -1
        score += 20

    # ── USB location (topology — stable if wiring unchanged) ─────────
    if saved_fp.location:
        if port_fp.location and port_fp.location == saved_fp.location:
            score += 10

    # ── Manufacturer string (soft match — not a hard reject) ─────────
    if saved_fp.manufacturer and port_fp.manufacturer:
        if saved_fp.manufacturer.lower() in port_fp.manufacturer.lower():
            score += 5

    # ── Product string (soft match) ──────────────────────────────────
    if saved_fp.product and port_fp.product:
        if saved_fp.product.lower() in port_fp.product.lower():
            score += 5

    return score


# ──────────────────────────────────────────────────────────────────────────────
#  Port ownership registry (singleton)
# ──────────────────────────────────────────────────────────────────────────────

class _PortOwnership:
    """Thread-safe registry of which UID owns which COM port.

    Prevents any second code path from opening an already-claimed port.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._port_to_uid: dict[str, str] = {}    # "COM4" → "meerstetter_tec_1089"
        self._uid_to_port: dict[str, str] = {}     # reverse index

    def claim(self, port: str, uid: str) -> None:
        """Claim *port* for *uid*.  Raises if already claimed by another."""
        with self._lock:
            current_owner = self._port_to_uid.get(port)
            if current_owner and current_owner != uid:
                raise AmbiguousPortError(port, current_owner, uid)
            # Release any previous port this UID held
            old_port = self._uid_to_port.get(uid)
            if old_port and old_port != port:
                self._port_to_uid.pop(old_port, None)
            self._port_to_uid[port] = uid
            self._uid_to_port[uid] = port

    def release(self, uid: str) -> None:
        """Release the port held by *uid* (if any)."""
        with self._lock:
            port = self._uid_to_port.pop(uid, None)
            if port:
                self._port_to_uid.pop(port, None)

    def owner_of(self, port: str) -> str | None:
        """Return the UID that owns *port*, or None."""
        with self._lock:
            return self._port_to_uid.get(port)

    def port_of(self, uid: str) -> str | None:
        """Return the port owned by *uid*, or None."""
        with self._lock:
            return self._uid_to_port.get(uid)

    def is_claimed(self, port: str) -> bool:
        with self._lock:
            return port in self._port_to_uid

    def claimed_ports(self) -> dict[str, str]:
        """Return a snapshot of all claims: {port: uid}."""
        with self._lock:
            return dict(self._port_to_uid)

    def clear(self) -> None:
        with self._lock:
            self._port_to_uid.clear()
            self._uid_to_port.clear()


# Module-level singleton — shared across DeviceManager, hw_service, drivers.
port_ownership = _PortOwnership()


# ──────────────────────────────────────────────────────────────────────────────
#  Resolver
# ──────────────────────────────────────────────────────────────────────────────

class PortResolver:
    """Resolves logical device UIDs to physical COM ports via USB fingerprints.

    Typical usage::

        resolver = PortResolver()
        resolver.snapshot()                 # enumerate hardware
        assignments = resolver.resolve_all(device_map)
        # assignments is validated: no duplicate ports.
    """

    def __init__(self):
        self._ports: list[PortInfo] = []

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

    # ── Single-device resolution (internal) ──────────────────────────

    def _resolve_one(self, uid: str, saved_fp: USBFingerprint | None,
                     saved_port: str, claimed: set[str]) -> ResolveResult:
        """Find the current COM port for *uid*.

        Parameters
        ----------
        claimed : set[str]
            Ports already assigned to other devices in this resolution
            pass.  This device will not be matched to a claimed port.
        """
        if saved_fp and not saved_fp.is_empty():
            candidates: list[tuple[int, PortInfo]] = []
            for pi in self._ports:
                if pi.device in claimed:
                    continue
                s = _score(pi.fingerprint, saved_fp)
                if s >= 0:
                    candidates.append((s, pi))

            candidates.sort(key=lambda x: x[0], reverse=True)

            if candidates:
                best_score, best = candidates[0]
                # Reject ambiguous same-score matches below serial-number
                # confidence (score < 100).
                if (len(candidates) > 1
                        and candidates[0][0] == candidates[1][0]
                        and best_score < 100):
                    log.warning(
                        "PortResolver: ambiguous match for %s — %s and %s "
                        "both scored %d.  Skipping (will not guess).",
                        uid, candidates[0][1].device,
                        candidates[1][1].device, best_score)
                    return ResolveResult()
                if best.device != saved_port:
                    log.info(
                        "PortResolver: %s moved %s → %s "
                        "(fingerprint score=%d, id=%s)",
                        uid, saved_port or "(none)", best.device,
                        best_score, saved_fp.stable_id)
                else:
                    log.info(
                        "PortResolver: %s → %s (fingerprint match, "
                        "score=%d)", uid, best.device, best_score)
                return ResolveResult(
                    port=best.device, method="fingerprint",
                    score=best_score, stable_id=saved_fp.stable_id)

        # ── COM port fallback (hint only, no fingerprint) ────────────
        # This path is ONLY used during migration from older configs
        # that don't have saved fingerprints yet.  The port is treated
        # as a hint — the caller MUST verify via handshake.
        if saved_port:
            for pi in self._ports:
                if pi.device == saved_port and pi.device not in claimed:
                    log.info(
                        "PortResolver: %s → %s (COM hint fallback — "
                        "HANDSHAKE REQUIRED)", uid, saved_port)
                    return ResolveResult(port=saved_port, method="com_hint")
            log.warning(
                "PortResolver: %s hint port %s not in current enumeration",
                uid, saved_port)

        return ResolveResult()

    # ── Batch resolution ─────────────────────────────────────────────

    def resolve_all(self, device_map: dict[str, tuple[USBFingerprint | None, str]]
                    ) -> dict[str, ResolveResult]:
        """Resolve multiple devices at once.

        Parameters
        ----------
        device_map : dict
            ``{uid: (saved_fingerprint, saved_port)}``

        Returns
        -------
        dict
            ``{uid: ResolveResult}``

        Raises
        ------
        AmbiguousPortError
            If two devices resolve to the same physical port.
        """
        result: dict[str, ResolveResult] = {}
        claimed: set[str] = set()

        # Resolve in priority order: devices with USB serial numbers first
        # (highest confidence), then by location, then bare VID:PID.
        def _priority(item):
            uid, (fp, port) = item
            if fp and fp.serial_number:
                return (0, uid)      # best: has serial number
            if fp and fp.location:
                return (1, uid)      # good: has USB location
            if fp and not fp.is_empty():
                return (2, uid)      # ok: has VID:PID at least
            return (3, uid)          # worst: no fingerprint, COM hint only

        for uid, (fp, port) in sorted(device_map.items(), key=_priority):
            rr = self._resolve_one(uid, fp, port, claimed)
            if rr.port:
                # ── Duplicate claim check (hard fail) ────────────────
                if rr.port in claimed:
                    other = next(
                        (u for u, r in result.items() if r.port == rr.port), "?")
                    raise AmbiguousPortError(rr.port, other, uid)
                claimed.add(rr.port)
            result[uid] = rr

        # Log final assignments
        for uid, rr in result.items():
            if rr.port:
                log.info("PortResolver assignment: %s → %s (method=%s, "
                         "score=%d)", uid, rr.port, rr.method, rr.score)
            else:
                log.info("PortResolver assignment: %s → NOT FOUND", uid)

        return result

    # ── Fingerprint lookup ───────────────────────────────────────────

    def get_fingerprint(self, port_name: str) -> USBFingerprint | None:
        """Return the USB fingerprint for a specific port in the snapshot."""
        for pi in self._ports:
            if pi.device == port_name:
                return pi.fingerprint
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  Post-connect handshake verification
# ──────────────────────────────────────────────────────────────────────────────

def verify_handshake(uid: str, port: str, driver_obj) -> bool:
    """Verify that the connected device actually matches the expected UID.

    This MUST be called after every successful ``driver_obj.connect()``.
    If the handshake fails, the caller should close the port immediately.

    Returns True if the device identity is confirmed.
    Raises HandshakeMismatchError if the device is wrong.
    """
    from hardware.device_registry import DEVICE_REGISTRY

    desc = DEVICE_REGISTRY.get(uid)
    if desc is None:
        return True  # unknown device type, can't verify

    dtype = desc.device_type

    # ── Arduino / ESP32 (GPIO devices) ───────────────────────────────
    # The driver's connect() already validates IDENT response.
    # If connect() succeeded, the handshake passed.
    if dtype == "gpio":
        return True

    # ── Meerstetter TEC / LDD ────────────────────────────────────────
    if desc.protocol_prober == "mecom":
        try:
            st = driver_obj.get_status()
        except Exception as exc:
            raise HandshakeMismatchError(
                uid, port,
                f"MeCom status query failed: {exc}"
            ) from exc

        # Verify MeCom address matches the registry expectation.
        # The driver stores the actual address used to communicate.
        expected_addr = getattr(desc, "mecom_address", None)
        actual_addr = getattr(driver_obj, "_address", None)
        if (expected_addr is not None and actual_addr is not None
                and expected_addr != actual_addr):
            raise HandshakeMismatchError(
                uid, port,
                f"MeCom address mismatch: expected {expected_addr}, "
                f"got {actual_addr} — this may be a different Meerstetter "
                f"device (TEC vs LDD)"
            )

        # Verify device family: TEC drivers should have temperature
        # fields, LDD drivers should have current fields.
        _is_tec_driver = hasattr(st, "actual_temp") or hasattr(st, "sink_temp")
        _is_ldd_driver = hasattr(st, "actual_current_a") and not _is_tec_driver
        if dtype == "tec" and _is_ldd_driver:
            raise HandshakeMismatchError(
                uid, port,
                "Expected TEC but got LDD-type status response"
            )
        if dtype == "ldd" and _is_tec_driver:
            raise HandshakeMismatchError(
                uid, port,
                "Expected LDD but got TEC-type status response"
            )

        log.info("[%s] MeCom handshake OK on %s (address=%s)",
                 uid, port, actual_addr)
        return True

    # ── Other device types ───────────────────────────────────────────
    # For devices we can't protocol-verify, trust the fingerprint match.
    return True


# ──────────────────────────────────────────────────────────────────────────────
#  Persistence helpers
# ──────────────────────────────────────────────────────────────────────────────

def save_fingerprint(uid: str, fp: USBFingerprint) -> None:
    """Persist a device's USB fingerprint to config preferences.

    The fingerprint is the PRIMARY stored identity.  The COM port is saved
    alongside as a migration hint, but fingerprint takes precedence.
    """
    try:
        import config as _cfg
        existing = _cfg.get_pref(f"device_params.{uid}", {})
        if not isinstance(existing, dict):
            existing = {}
        existing["usb_fingerprint"] = fp.to_dict()
        _cfg.set_pref(f"device_params.{uid}", existing)
    except Exception:
        log.debug("Could not save fingerprint for %s", uid, exc_info=True)


def load_fingerprint(uid: str) -> USBFingerprint | None:
    """Load a device's saved USB fingerprint from config preferences."""
    try:
        import config as _cfg
        saved = _cfg.get_pref(f"device_params.{uid}", {})
        if isinstance(saved, dict):
            d = saved.get("usb_fingerprint")
            if d and isinstance(d, dict):
                return USBFingerprint.from_dict(d)
    except Exception:
        log.debug("Could not load fingerprint for %s", uid, exc_info=True)
    return None
