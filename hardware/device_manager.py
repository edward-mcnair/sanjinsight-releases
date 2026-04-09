"""
hardware/device_manager.py

DeviceManager — tracks the state of every device in the system,
manages connect/disconnect lifecycle, and acts as the bridge between
the scanner's discovered ports and the hardware driver layer.

State machine per device
------------------------
    ABSENT       — not detected on any port
    DISCOVERED   — detected by scanner, not yet connected
    CONNECTING   — connection attempt in progress
    CONNECTED    — driver active, hardware responding
    ERROR        — driver active but reporting an error
    DISCONNECTING— graceful disconnect in progress

This module is hardware-layer agnostic — it calls create_camera(),
create_tec(), etc. from the existing hardware factory functions and
delegates the actual I/O to them.
"""

from __future__ import annotations
import concurrent.futures
import logging
import time, threading, importlib
from dataclasses   import dataclass
from enum          import Enum, auto
from typing        import List, Optional, Dict, Callable

log = logging.getLogger(__name__)

# Hard limit on a single driver.connect() call.  If the call does not return
# within this time it is treated as a timeout failure.
_CONNECT_TIMEOUT_S: float = 12.0

# Camera connect timeout is longer because the Boson auto-detect on Windows
# probes multiple DirectShow indices, reads test frames, and may run
# PowerShell PnP queries — easily exceeding 12 s on cold USB enumeration.
_CAMERA_CONNECT_TIMEOUT_S: float = 30.0

from .device_registry import (DeviceDescriptor, DEVICE_REGISTRY,
                                DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA,
                                DTYPE_STAGE, DTYPE_PROBER, DTYPE_TURRET,
                                DTYPE_BIAS, DTYPE_LDD, DTYPE_GPIO)
from .device_scanner  import ScanReport


# ------------------------------------------------------------------ #
#  Device state                                                        #
# ------------------------------------------------------------------ #

class DeviceState(Enum):
    ABSENT        = auto()
    DISCOVERED    = auto()
    CONNECTING    = auto()
    CONNECTED     = auto()
    ERROR         = auto()
    DISCONNECTING = auto()


_STATE_PALETTE_KEYS = {
    DeviceState.ABSENT:        "stateAbsent",
    DeviceState.DISCOVERED:    "stateDiscovered",
    DeviceState.CONNECTING:    "stateConnecting",
    DeviceState.CONNECTED:     "stateConnected",
    DeviceState.ERROR:         "stateError",
    DeviceState.DISCONNECTING: "stateConnecting",
}


def _get_state_color(state) -> str:
    """Return the theme-aware colour for a device state."""
    from ui.theme import PALETTE
    key = _STATE_PALETTE_KEYS.get(state, "textDim")
    return PALETTE.get(key, "#888888")


# Legacy dict kept for backward compat — refreshes from PALETTE on each access.
class _StateColorDict(dict):
    def _refresh(self):
        from ui.theme import PALETTE
        self.clear()
        for st, pk in _STATE_PALETTE_KEYS.items():
            self[st] = PALETTE.get(pk, "#888888")

    def __getitem__(self, key):
        self._refresh()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._refresh()
        return super().get(key, default)


STATE_COLORS = _StateColorDict()

STATE_LABELS = {
    DeviceState.ABSENT:        "Not found",
    DeviceState.DISCOVERED:    "Discovered",
    DeviceState.CONNECTING:    "Connecting…",
    DeviceState.CONNECTED:     "Connected",
    DeviceState.ERROR:         "Error",
    DeviceState.DISCONNECTING: "Disconnecting…",
}

# Formal state machine: maps each state to the set of valid next states.
# Any transition not listed here is illegal and will be logged + rejected.
#
# ABSENT → CONNECTING is intentionally allowed so that users can manually
# trigger a connection attempt on a device that was not auto-discovered by
# the scanner (e.g. a TEC controller on a Prolific USB-serial adapter that
# doesn't match any registry pattern).  The connect worker checks that an
# address has been configured before proceeding; if not, it emits a helpful
# error message rather than silently failing.
_VALID_TRANSITIONS: dict[DeviceState, set[DeviceState]] = {
    DeviceState.ABSENT:        {DeviceState.DISCOVERED, DeviceState.CONNECTING},
    DeviceState.DISCOVERED:    {DeviceState.CONNECTING, DeviceState.ABSENT},
    DeviceState.CONNECTING:    {DeviceState.CONNECTED,  DeviceState.ERROR, DeviceState.ABSENT},
    DeviceState.CONNECTED:     {DeviceState.DISCONNECTING, DeviceState.ERROR},
    DeviceState.ERROR:         {DeviceState.CONNECTING, DeviceState.ABSENT},
    DeviceState.DISCONNECTING: {DeviceState.DISCOVERED, DeviceState.ABSENT},
}


# ------------------------------------------------------------------ #
#  Device entry                                                        #
# ------------------------------------------------------------------ #

@dataclass
class DeviceEntry:
    """Live record for one device slot."""

    descriptor:     DeviceDescriptor
    state:          DeviceState     = DeviceState.ABSENT
    address:        str             = ""   # authoritative port (set by resolver or verified connection)
    serial_number:  str             = ""
    firmware_ver:   str             = ""
    driver_ver:     str             = ""
    error_msg:      str             = ""
    last_seen:      float           = 0.0
    last_connected: float           = 0.0
    driver_obj:     object          = None   # live driver instance

    # ── Identity pipeline fields ─────────────────────────────────────
    # observed_address: set by passive scan — advisory, not authoritative.
    # resolution_method: how the current address was determined.
    # port_ambiguous: True if scan found multiple candidates on same port.
    observed_address:  str  = ""    # scan-discovered port (not persisted)
    resolution_method: str  = ""    # "fingerprint", "com_hint", "scan", "user", ""
    port_ambiguous:    bool = False # True if port had multiple candidate devices

    # Connection params (may be overridden by user in settings)
    baud_rate:   int   = 0
    ip_address:  str   = ""
    timeout_s:   float = 2.0
    # Boson-specific: serial control port and UVC video device index
    video_index: int   = 0

    @property
    def uid(self) -> str:
        return self.descriptor.uid

    @property
    def display_name(self) -> str:
        return self.descriptor.display_name

    @property
    def is_connected(self) -> bool:
        return self.state == DeviceState.CONNECTED

    @property
    def status_color(self) -> str:
        return _get_state_color(self.state)

    @property
    def status_label(self) -> str:
        return STATE_LABELS.get(self.state, "Unknown")

    def to_dict(self) -> dict:
        return {
            "uid":            self.uid,
            "address":        self.address,
            "serial_number":  self.serial_number,
            "firmware_ver":   self.firmware_ver,
            "driver_ver":     self.driver_ver or self.descriptor.driver_version,
            "baud_rate":      self.baud_rate  or self.descriptor.default_baud,
            "ip_address":     self.ip_address or self.descriptor.default_ip,
            "timeout_s":      self.timeout_s,
            "video_index":    self.video_index,
        }


# ------------------------------------------------------------------ #
#  Device manager                                                      #
# ------------------------------------------------------------------ #

class DeviceManager:
    """
    Central device lifecycle manager.

    Usage:
        mgr = DeviceManager()
        mgr.set_status_callback(lambda uid, state, msg: ...)
        report = scanner.scan()
        mgr.update_from_scan(report)
        mgr.connect("meerstetter_tec_1089")
        entry = mgr.get("meerstetter_tec_1089")
    """

    def __init__(self):
        self._entries:  Dict[str, DeviceEntry] = {}
        self._lock      = threading.Lock()
        self._status_cb: Optional[Callable[[str, DeviceState, str], None]] = None
        self._log_cb:    Optional[Callable[[str], None]] = None

        # Safe-mode state — set when a required device is absent
        self._safe_mode:        bool = False
        self._safe_mode_reason: str  = ""

        # Optional callback fired after every successful _inject_into_app.
        # Used by main_app.py to emit hw_service.device_connected so the
        # main window refreshes camera selectors / safe-mode status.
        self._post_inject_cb: Optional[Callable[[str, object], None]] = None

        # Cached port resolver (set by resolve_ports(), read by
        # _connect_worker for fingerprint saves).
        self._port_resolver = None

        # Initialise an entry for every known device and restore any
        # connection parameters (port, baud, IP) saved in a previous session.
        for uid, desc in DEVICE_REGISTRY.items():
            entry = DeviceEntry(descriptor=desc)
            try:
                import config as _cfg
                saved = _cfg.get_pref(f"device_params.{uid}", {})
                if saved.get("address"):          entry.address        = saved["address"]
                if saved.get("baud_rate"):        entry.baud_rate      = saved["baud_rate"]
                if saved.get("ip_address"):       entry.ip_address     = saved["ip_address"]
                if saved.get("timeout_s"):        entry.timeout_s      = saved["timeout_s"]
                if "video_index" in saved:        entry.video_index    = saved["video_index"]
                if saved.get("last_connected"):   entry.last_connected = saved["last_connected"]
            except Exception:
                pass   # config not yet initialised at import time — ignore
            self._entries[uid] = entry

        # ── Stale port-conflict cleanup ──────────────────────────────
        # Saved preferences can contain phantom port assignments from
        # previous buggy scans (e.g. MeCom echo created a ghost
        # LDD-1121 on the TEC's port, or the Arduino's port was saved
        # for two devices).  Detect conflicts among restored addresses
        # and clear the losers so auto-reconnect doesn't fight over
        # the same port.
        self._dedup_restored_addresses()

    def _dedup_restored_addresses(self) -> None:
        """Clear duplicate port assignments from saved preferences.

        When two (or more) serial devices were saved with the same COM
        port, keep the one most likely to be the real occupant and blank
        the others.  Uses the ``hw.last_connected_devices`` list (most
        recent first) to rank; falls back to ``protocol_prober`` presence
        (devices requiring active probing are more likely phantoms).
        Also persists the cleanup back to preferences so it sticks.
        """
        # Build a recency rank from the saved last_connected_devices list
        # (most recent first → lower index = higher priority).
        try:
            import config as _cfg
            _last_list = _cfg.get_pref("hw.last_connected_devices", [])
        except Exception:
            _last_list = []
        _recency: dict[str, int] = {}
        for _i, _uid in enumerate(_last_list):
            if _uid not in _recency:          # first occurrence = latest
                _recency[_uid] = _i

        port_owners: dict[str, list[str]] = {}   # port → [uid, ...]
        for uid, entry in self._entries.items():
            if entry.address and not entry.ip_address:
                # Serial port address (not IP-based devices)
                port_owners.setdefault(entry.address, []).append(uid)

        for port, uids in port_owners.items():
            if len(uids) <= 1:
                continue
            # Multiple devices claim the same port — resolve conflict.
            # Prefer the device that appears earliest in
            # last_connected_devices (most recently connected).  Devices
            # NOT in the list are ranked last (index = 9999).
            # Among ties, prefer devices without protocol_prober (they
            # can't create phantom echoes).
            best_uid = min(
                uids,
                key=lambda u: (
                    _recency.get(u, 9999),
                    1 if getattr(self._entries[u].descriptor,
                                 'protocol_prober', None) else 0,
                ),
            )
            for uid in uids:
                if uid == best_uid:
                    continue
                entry = self._entries[uid]
                log.warning(
                    "Stale port conflict: %s and %s both saved with "
                    "port %s — clearing %s (keeping %s)",
                    best_uid, uid, port, uid, best_uid,
                )
                entry.address = ""
                # Persist the cleanup so the phantom doesn't return
                try:
                    import config as _cfg
                    saved = _cfg.get_pref(f"device_params.{uid}", {})
                    if saved.get("address"):
                        saved["address"] = ""
                        _cfg.set_pref(f"device_params.{uid}", saved)
                    # Also remove from last_connected_devices list so
                    # auto-reconnect doesn't try to reconnect the phantom
                    lc = _cfg.get_pref("hw.last_connected_devices", [])
                    if uid in lc:
                        lc = [u for u in lc if u != uid]
                        _cfg.set_pref("hw.last_connected_devices", lc)
                except Exception:
                    pass

    # ---------------------------------------------------------------- #
    #  Callbacks                                                        #
    # ---------------------------------------------------------------- #

    def set_status_callback(self,
                             cb: Callable[[str, DeviceState, str], None]):
        """Called whenever a device changes state: cb(uid, new_state, message)."""
        self._status_cb = cb

    def set_log_callback(self, cb: Callable[[str], None]):
        """Called with human-readable log messages."""
        self._log_cb = cb

    def set_post_inject_callback(self,
                                  cb: Callable[[str, object], None]) -> None:
        """Register a callback fired after every successful driver injection.

        cb(uid: str, driver_obj) — called from the connect worker thread
        immediately after _inject_into_app completes successfully.  Use this
        to emit hw_service.device_connected so the main window refreshes its
        camera selectors and safe-mode state without a circular import.
        """
        self._post_inject_cb = cb

    def _emit(self, uid: str, state: DeviceState, msg: str = ""):
        if self._status_cb:
            try:
                self._status_cb(uid, state, msg)
            except Exception:
                log.warning("DeviceManager: status callback failed for %s",
                            uid, exc_info=True)

    def _log(self, msg: str):
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:
                log.debug("DeviceManager: log callback failed", exc_info=True)

    # ---------------------------------------------------------------- #
    #  USB fingerprint port resolution                                  #
    # ---------------------------------------------------------------- #

    def resolve_ports(self) -> dict[str, str | None]:
        """Re-resolve all device addresses using USB fingerprints.

        Enumerates all serial ports, matches each remembered device to
        its physical port by USB serial number / VID:PID / location
        (not volatile COM port number), and updates entry.address
        to the current COM port.

        Call this BEFORE auto-reconnect to ensure devices are connected
        on their correct (current) ports, even if Windows reassigned
        COM numbers since the last session.

        Returns a dict of ``{uid: resolved_port_or_None}``.
        """
        from hardware.port_resolver import (
            PortResolver, ResolveResult, load_fingerprint, USBFingerprint
        )

        resolver = PortResolver()
        resolver.snapshot()

        # Build the map: uid → (saved_fingerprint, saved_port)
        device_map: dict[str, tuple[USBFingerprint | None, str]] = {}
        try:
            import config as _cfg
            remembered = _cfg.get_pref("hw.last_connected_devices", [])
        except Exception:
            remembered = []

        for uid in remembered:
            entry = self._entries.get(uid)
            if entry is None:
                continue
            if entry.state in (DeviceState.CONNECTED, DeviceState.CONNECTING):
                continue  # don't disturb live connections
            # Skip non-serial devices (cameras, Ethernet, etc.)
            conn = entry.descriptor.connection_type
            if conn not in ("serial", "usb"):
                continue

            fp = load_fingerprint(uid)
            device_map[uid] = (fp, entry.address)

        if not device_map:
            log.debug("resolve_ports: no serial devices to resolve")
            return {}

        from hardware.port_resolver import AmbiguousPortError
        try:
            results = resolver.resolve_all(device_map)
        except AmbiguousPortError as clash:
            log.error("resolve_ports: PORT CONFLICT — %s", clash)
            self._log(
                f"⚠  Port conflict: {clash.uid_a} and {clash.uid_b} both "
                f"resolved to {clash.port}.  Check USB connections and run "
                f"Tools → Dump Serial Ports for diagnostics."
            )
            # Return empty — don't update any addresses with bad data
            self._port_resolver = resolver
            return {}

        # Update entry addresses with resolved ports (under lock to
        # avoid races with concurrent connect workers).
        port_map: dict[str, str | None] = {}
        with self._lock:
            for uid, rr in results.items():
                entry = self._entries.get(uid)
                if entry is None:
                    continue
                old_addr = entry.address
                port_map[uid] = rr.port
                if rr.port:
                    entry.address           = rr.port
                    entry.resolution_method = rr.method
                    entry.port_ambiguous    = False
                    if rr.port != old_addr:
                        log.info("resolve_ports: %s port changed %s → %s "
                                 "(method=%s, score=%d)",
                                 uid, old_addr, rr.port, rr.method, rr.score)
                        self._log(
                            f"Port update: {entry.descriptor.display_name} "
                            f"moved from {old_addr} to {rr.port}"
                            f" ({rr.method})")
                else:
                    if old_addr:
                        log.info("resolve_ports: %s (was %s) not found in "
                                 "current port enumeration", uid, old_addr)

        # Store resolver for later use (e.g. saving fingerprints)
        self._port_resolver = resolver

        # ── Watchdog: warn about stale probe claims ──────────────────
        from hardware.port_resolver import port_ownership
        port_ownership.check_stale_claims()

        # ── Audit log: trace every identity decision ─────────────────
        self._log_identity_audit(resolver, results, device_map)

        return port_map

    def _log_identity_audit(self, resolver, results, device_map) -> None:
        """Log a per-device identity trace for debugging port conflicts.

        This produces one block per serial device showing:
        - raw port fingerprint from hardware
        - whether a saved fingerprint existed
        - resolver score and match method
        - whether the port was ambiguous
        - port ownership claim/release events
        """
        from hardware.port_resolver import load_fingerprint
        log.info("=" * 60)
        log.info("IDENTITY AUDIT — %d serial device(s)", len(results))
        log.info("=" * 60)

        for uid, rr in results.items():
            saved_fp_data = device_map.get(uid, (None, ""))
            saved_fp, saved_port = saved_fp_data if saved_fp_data else (None, "")
            entry = self._entries.get(uid)
            display = entry.descriptor.display_name if entry else uid

            log.info("── %s (%s) ──", display, uid)
            log.info("  Saved fingerprint:  %s",
                     f"serial={saved_fp.serial_number!r} "
                     f"vid=0x{saved_fp.vid or 0:04X} "
                     f"pid=0x{saved_fp.pid or 0:04X} "
                     f"loc={saved_fp.location!r}"
                     if saved_fp and not saved_fp.is_empty()
                     else "(none)")
            log.info("  Saved COM port:     %s", saved_port or "(none)")
            log.info("  Resolved port:      %s", rr.port or "NOT FOUND")
            log.info("  Resolution method:  %s", rr.method or "—")
            log.info("  Fingerprint score:  %d", rr.score)
            log.info("  Stable ID match:    %s", rr.stable_id or "—")

            # Show the hardware fingerprint at the resolved port
            if rr.port and resolver:
                hw_fp = resolver.get_fingerprint(rr.port)
                if hw_fp:
                    log.info("  Hardware at %s:     serial=%r "
                             "vid=0x%04X pid=0x%04X loc=%r mfr=%r",
                             rr.port, hw_fp.serial_number,
                             hw_fp.vid or 0, hw_fp.pid or 0,
                             hw_fp.location, hw_fp.manufacturer)

            if entry:
                log.info("  Ambiguous:          %s", entry.port_ambiguous)

        log.info("=" * 60)

    # ---------------------------------------------------------------- #
    #  Startup diagnostic report                                        #
    # ---------------------------------------------------------------- #

    def generate_identity_report(self) -> list[dict]:
        """Generate a per-device identity summary for diagnostics.

        Returns a list of dicts, one per serial device, containing:
          uid, display_name, saved_fingerprint, observed_address,
          resolved_address, resolution_method, ambiguous, state,
          connected_port, handshake_identity

        Call AFTER auto-reconnect completes for the fullest picture.
        Also logs the report at INFO level.
        """
        from hardware.port_resolver import load_fingerprint
        report: list[dict] = []

        for uid, entry in sorted(self._entries.items()):
            conn = entry.descriptor.connection_type
            if conn not in ("serial", "usb"):
                continue

            # Saved fingerprint
            fp = load_fingerprint(uid)
            fp_summary = ""
            if fp and not fp.is_empty():
                parts = []
                if fp.serial_number:
                    parts.append(f"sn={fp.serial_number}")
                if fp.vid is not None:
                    parts.append(f"vid:pid={fp.vid:04X}:{(fp.pid or 0):04X}")
                if fp.location:
                    parts.append(f"loc={fp.location}")
                fp_summary = ", ".join(parts)

            # Handshake identity
            identity_str = ""
            if entry.driver_obj and hasattr(entry.driver_obj, "get_identity"):
                try:
                    ident = entry.driver_obj.get_identity()
                    identity_str = (
                        f"{ident.protocol}/{ident.device_family} "
                        f"model={ident.model} addr={ident.node_address}"
                    )
                    if ident.firmware_version:
                        identity_str += f" fw={ident.firmware_version}"
                except Exception:
                    identity_str = "(get_identity failed)"

            row = {
                "uid":                uid,
                "display_name":       entry.display_name,
                "saved_fingerprint":  fp_summary or "(none)",
                "observed_address":   entry.observed_address or "",
                "resolved_address":   entry.address or "",
                "resolution_method":  entry.resolution_method or "",
                "ambiguous":          entry.port_ambiguous,
                "state":              entry.status_label,
                "connected_port":     entry.address if entry.is_connected else "",
                "handshake_identity": identity_str or "",
            }
            report.append(row)

        # ── Watchdog: check for stale probe claims ────────────────────
        from hardware.port_resolver import port_ownership
        stale = port_ownership.check_stale_claims()
        if stale:
            port_ownership.release_stale_probes()

        # Log the report
        log.info("=" * 70)
        log.info("DEVICE IDENTITY REPORT — %d serial device(s)", len(report))
        log.info("=" * 70)
        for r in report:
            log.info("── %s (%s) ──", r["display_name"], r["uid"])
            log.info("  State:              %s", r["state"])
            log.info("  Saved fingerprint:  %s", r["saved_fingerprint"])
            log.info("  Observed address:   %s", r["observed_address"] or "—")
            log.info("  Resolved address:   %s", r["resolved_address"] or "—")
            log.info("  Resolution method:  %s", r["resolution_method"] or "—")
            log.info("  Ambiguous:          %s", r["ambiguous"])
            log.info("  Connected port:     %s", r["connected_port"] or "—")
            log.info("  Handshake identity: %s", r["handshake_identity"] or "—")
        log.info("=" * 70)

        return report

    # ---------------------------------------------------------------- #
    #  Scan integration                                                 #
    # ---------------------------------------------------------------- #

    def update_from_scan(self, report: ScanReport):
        """
        Update all device entries based on the latest scan report.
        Devices that were CONNECTED are not disturbed.

        Port exclusivity: if two discovered devices resolve to the same
        serial port, only the first is accepted; the duplicate is logged
        and left as ABSENT so we don't attempt a double-open at startup.
        """
        with self._lock:
            # Mark everything not currently connected as ABSENT first
            for entry in self._entries.values():
                if entry.state not in (DeviceState.CONNECTED,
                                       DeviceState.CONNECTING,
                                       DeviceState.DISCONNECTING):
                    entry.state = DeviceState.ABSENT

            # Track ports already claimed by this scan pass.
            # Includes ports held by already-connected devices.
            claimed_ports: dict[str, str] = {}   # port → uid
            for uid, entry in self._entries.items():
                if (entry.state in (DeviceState.CONNECTED,
                                    DeviceState.CONNECTING)
                        and entry.address):
                    claimed_ports[entry.address] = uid

            # ── Phase 1: Collect scan evidence per port ────────────
            # Group discovered devices by address to detect ambiguity
            # (multiple candidates for the same physical port).
            port_candidates: dict[str, list] = {}   # port → [dev, ...]
            for dev in report.devices:
                if dev.descriptor is None:
                    continue
                addr = dev.address or ""
                if addr:
                    port_candidates.setdefault(addr, []).append(dev)

            # Identify ambiguous ports (multiple candidates)
            ambiguous_ports: set[str] = {
                port for port, devs in port_candidates.items()
                if len(devs) > 1
            }
            if ambiguous_ports:
                log.info("Scan: ambiguous ports (multiple candidates): %s",
                         ambiguous_ports)

            # ── Phase 2: Update entries from scan ─────────────────
            # Scan results are ADVISORY — they update observed_address
            # and state, but do NOT overwrite the authoritative address
            # (which is set only by the resolver or verified connection).
            for dev in report.devices:
                if dev.descriptor is None:
                    continue
                uid   = dev.descriptor.uid
                entry = self._entries.get(uid)
                if entry is None:
                    continue
                if entry.state in (DeviceState.CONNECTED,
                                   DeviceState.CONNECTING):
                    continue   # don't disturb live connections

                addr = dev.address or ""

                # Track port collisions with live connections
                if addr and addr in claimed_ports:
                    owner = claimed_ports[addr]
                    log.warning(
                        "Port collision: %s claims %s but it is held by "
                        "connected device %s — marking ambiguous",
                        uid, addr, owner)
                    entry.port_ambiguous = True
                    continue

                entry.state            = DeviceState.DISCOVERED
                entry.observed_address = addr
                entry.serial_number    = dev.serial_number or ""
                entry.last_seen        = time.time()
                entry.port_ambiguous   = addr in ambiguous_ports

                # Scan NEVER writes entry.address — that field is set only
                # by the resolver (fingerprint/com_hint) or a verified
                # successful connection.  The UI reads observed_address
                # for display when address is empty.

                if addr:
                    claimed_ports[addr] = uid
                self._emit(uid, DeviceState.DISCOVERED, addr)

    # ---------------------------------------------------------------- #
    #  Connect                                                          #
    # ---------------------------------------------------------------- #

    def connect(self, uid: str,
                on_complete: Optional[Callable[[bool, str], None]] = None):
        """
        Connect a device asynchronously.
        on_complete(success: bool, message: str) called when done.
        """
        entry = self._entries.get(uid)
        if entry is None:
            if on_complete:
                on_complete(False, f"Unknown device: {uid}")
            return

        with self._lock:
            if entry.state == DeviceState.CONNECTED:
                if on_complete:
                    on_complete(True, "Already connected")
                return
            if entry.state == DeviceState.CONNECTING:
                if on_complete:
                    on_complete(False, "Already connecting")
                return

            # Guard: if hw_service.start() already opened this specific
            # device type from config (it bypasses Device Manager), detect
            # that here and adopt the existing driver instead of trying to
            # open the hardware a second time (which causes "exclusively
            # opened" errors for cameras and similar conflicts for other
            # device types).
            _adopted = self._try_adopt_existing(entry)
            if _adopted:
                log.info("[%s] Adopted existing driver from hw_service — "
                         "marking as CONNECTED", uid)
                entry.state          = DeviceState.CONNECTED
                entry.last_connected = time.time()
                entry.error_msg      = ""
                self._emit(uid, DeviceState.CONNECTED)
                # Fire post_inject_cb so the main window updates
                # header, camera bar, tab availability, etc.
                if self._post_inject_cb:
                    try:
                        self._post_inject_cb(uid, entry.driver_obj)
                    except Exception:
                        log.debug("[%s] post_inject_cb (adopted) failed",
                                  uid, exc_info=True)
                if on_complete:
                    on_complete(True, "Already open (adopted from hw_service)")
                return

            allowed = _VALID_TRANSITIONS.get(entry.state, set())
            if DeviceState.CONNECTING not in allowed:
                msg = (f"Cannot connect from state {entry.state.name}. "
                       f"Try disconnecting first.")
                log.warning("[%s] %s", uid, msg)
                if on_complete:
                    on_complete(False, msg)
                return
            entry.state     = DeviceState.CONNECTING
            entry.error_msg = ""

        self._emit(uid, DeviceState.CONNECTING)
        threading.Thread(
            target=self._connect_worker,
            args=(uid, on_complete),
            daemon=True).start()

    def _connect_worker(self, uid: str,
                        on_complete: Optional[Callable]):
        entry = self._entries[uid]
        desc  = entry.descriptor
        t0    = time.time()
        driver_obj = None

        try:
            # Guard: if the device was never auto-discovered and has no address
            # configured, give the user a clear action rather than a cryptic
            # driver error. Serial/USB/Ethernet devices all need an address.
            # Boson cameras support video-only mode with an empty serial_port —
            # skip the address guard so the driver can open in that mode.
            _boson_video_only = (
                desc.uid in ("flir_boson_320", "flir_boson_640",
                             "flir_boson_plus_320", "flir_boson_plus_640")
                and not entry.address
            )
            # Ethernet devices (sbRIO) use ip_address, not address (port)
            _has_address = (
                entry.ip_address if desc.connection_type == "ethernet"
                else entry.address
            )
            needs_address = (
                desc.connection_type in ("serial", "usb", "ethernet")
                and not _boson_video_only
            )
            if needs_address and not _has_address:
                raise ValueError(
                    f"No port or address configured for {desc.display_name}.\n\n"
                    "In the Device Manager, select this device → set the Port "
                    "in Connection Parameters → click Apply Parameters, then "
                    "try Connect again.\n\n"
                    "Or open Settings → Hardware Setup to configure all ports "
                    "at once using the step-by-step wizard."
                )

            # Pre-flight: check driver dependencies before touching hardware.
            # This surfaces "pypylon not bundled" style issues with a clear
            # user message instead of a raw ImportError traceback.
            driver_obj = self._instantiate_driver(entry)
            if hasattr(driver_obj, "preflight"):
                pf_ok, pf_issues = driver_obj.__class__.preflight()
                if not pf_ok:
                    bullet_list = "\n".join(f"  • {i}" for i in pf_issues)
                    raise RuntimeError(
                        f"Cannot connect to {desc.display_name} — "
                        f"driver pre-flight failed:\n\n{bullet_list}"
                    )
                if pf_issues:
                    for issue in pf_issues:
                        log.warning("[%s] pre-flight warning: %s", uid, issue)

            # ── Claim port ownership BEFORE connecting ────────────────
            # This prevents any second code path (hw_service, hotplug,
            # another connect click) from opening the same port.
            _port_to_claim = entry.address
            if _port_to_claim:
                from hardware.port_resolver import port_ownership, AmbiguousPortError
                try:
                    port_ownership.claim(_port_to_claim, uid)
                    log.info("[%s] Claimed port %s", uid, _port_to_claim)
                except AmbiguousPortError as clash:
                    raise RuntimeError(
                        f"Cannot connect {desc.display_name}: port "
                        f"{clash.port} is already claimed by "
                        f"{clash.uid_a}.\n\n"
                        f"Disconnect {clash.uid_a} first, or check that "
                        f"devices have distinct USB serial numbers."
                    ) from clash

            # Enforce a hard timeout on connect() so the UI is never frozen.
            # NOTE: do NOT use `with ThreadPoolExecutor` here — the context
            # manager calls shutdown(wait=True) on exit, which blocks until the
            # driver thread returns even after a TimeoutError.  For drivers like
            # Boson whose cv2.VideoCapture() can hang for minutes (wrong index,
            # macOS camera permission pending), that deadlocks _connect_worker.
            # We use shutdown(wait=False) so the stuck thread is abandoned and
            # _connect_worker can report failure immediately.
            addr_str = entry.address or entry.ip_address or "(video-only)"
            _method_tag = (f" [{entry.resolution_method}]"
                           if entry.resolution_method else "")
            self._log(f"Connecting {desc.display_name} on "
                      f"{addr_str}{_method_tag} …")
            log.info("[%s] Connecting %s on %s (resolution=%s) …",
                     uid, desc.display_name, addr_str,
                     entry.resolution_method or "none")
            import sys as _sys
            # Cameras (especially FLIR Boson) need a longer timeout because
            # auto-detect probes multiple video device indices on Windows.
            dtype = desc.device_type
            _timeout = (_CAMERA_CONNECT_TIMEOUT_S if dtype == DTYPE_CAMERA
                        else _CONNECT_TIMEOUT_S)
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(driver_obj.connect)
            try:
                future.result(timeout=_timeout)
                pool.shutdown(wait=False)
            except concurrent.futures.TimeoutError:
                pool.shutdown(wait=False)   # abandon stuck driver thread
                _macos_hint = (
                    "\n\nOn macOS, also check:\n"
                    "  • System Settings → Privacy & Security → Camera\n"
                    "    → enable SanjINSIGHT (or Terminal if running from source).\n"
                    "  • For the FLIR Boson, confirm the Video Device Index in\n"
                    "    Device Manager matches the UVC camera (try 0, 1, 2…)."
                ) if _sys.platform == "darwin" else ""
                raise TimeoutError(
                    f"Connect timed out after {_timeout:.0f}s. "
                    f"Check that the device is powered and not held by "
                    f"another process (terminal, firmware updater, etc.)."
                    + _macos_hint
                )

            log.info("[%s] Connected in %.2fs", uid, time.time() - t0)

            with self._lock:
                entry.driver_obj     = driver_obj
                entry.state          = DeviceState.CONNECTED
                entry.last_connected = time.time()
                entry.error_msg      = ""

                # ── Verify driver didn't wander to a different port ────
                # Now that drivers are prevented from fallback scanning
                # when a resolver-provided port is set, this should be
                # a no-op.  Log a warning if it ever happens — it means
                # a driver bypassed the resolver.
                actual_port = getattr(driver_obj, "connected_port", None)
                if actual_port and actual_port != entry.address:
                    log.warning("[%s] Driver connected on %s but resolver "
                                "assigned %s — possible resolver bypass!",
                                uid, actual_port, entry.address)
                    entry.address = actual_port

                try:
                    st = driver_obj.get_status()
                    entry.firmware_ver  = getattr(st, "firmware_version", "") or ""
                    entry.serial_number = getattr(st, "serial_number",
                                                  entry.serial_number) or ""
                except Exception:
                    log.debug("[%s] get_status() for metadata failed — "
                              "firmware/serial will be blank", uid, exc_info=True)

            # ── Post-connect handshake verification ──────────────────
            # Confirm the device on the wire actually matches the UID.
            # For Arduino/ESP32 this is already validated by connect()
            # (IDENT check), for Meerstetter it verifies MeCom protocol.
            if entry.address:
                try:
                    from hardware.port_resolver import (
                        verify_handshake, HandshakeMismatchError
                    )
                    verify_handshake(uid, entry.address, driver_obj)
                except HandshakeMismatchError as hmm:
                    # Wrong device on this port — disconnect immediately
                    log.error("[%s] Handshake FAILED: %s", uid, hmm)
                    try:
                        driver_obj.disconnect()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"{desc.display_name}: wrong device on "
                        f"{entry.address} — {hmm}"
                    )
                except Exception:
                    # Non-fatal: if we can't verify, log and proceed
                    log.debug("[%s] Handshake check unavailable",
                              uid, exc_info=True)

            _conn_method = (f", {entry.resolution_method}"
                            if entry.resolution_method else "")
            self._log(f"✓  Connected: {desc.display_name}  "
                      f"({entry.address}{_conn_method})")
            self._emit(uid, DeviceState.CONNECTED)
            self._inject_into_app(uid, driver_obj)

            # Remember all connected devices so the app can auto-connect on
            # next launch.  Maintains a list of UIDs (order = connect order).
            try:
                import config as _cfg
                saved = _cfg.get_pref("hw.last_connected_devices", [])
                if not isinstance(saved, list):
                    saved = [saved] if saved else []
                if uid not in saved:
                    saved.append(uid)
                _cfg.set_pref("hw.last_connected_devices", saved)
                # Keep legacy key for backward compat with older installs
                _cfg.set_pref("hw.last_connected_device", uid)
                # Persist connection parameters (address, baud, video_index,
                # etc.) so the device can be auto-reconnected with the same
                # settings on next launch.  MERGE into existing dict so we
                # don't destroy the usb_fingerprint saved below.
                _existing = _cfg.get_pref(f"device_params.{uid}", {})
                if not isinstance(_existing, dict):
                    _existing = {}
                _existing.update({
                    "address":        entry.address,
                    "baud_rate":      entry.baud_rate,
                    "ip_address":     entry.ip_address,
                    "timeout_s":      entry.timeout_s,
                    "video_index":    entry.video_index,
                    "last_connected": entry.last_connected,
                })
                _cfg.set_pref(f"device_params.{uid}", _existing)
            except Exception:
                log.debug("[%s] Could not save device_params", uid,
                          exc_info=True)

            # ── Save USB fingerprint for the port we connected on ────
            # This is the KEY to reliable reconnection: next launch we
            # match by USB serial number / VID:PID / location instead
            # of volatile COM port number.
            if entry.address:
                try:
                    from hardware.port_resolver import (
                        save_fingerprint, USBFingerprint
                    )
                    resolver = getattr(self, '_port_resolver', None)
                    if resolver:
                        fp = resolver.get_fingerprint(entry.address)
                    else:
                        # No resolver cached — do a quick lookup
                        from serial.tools.list_ports import comports
                        fp = None
                        for p in comports():
                            if p.device == entry.address:
                                fp = USBFingerprint.from_port_info(p)
                                break
                    if fp and not fp.is_empty():
                        save_fingerprint(uid, fp)
                        log.info("[%s] Saved USB fingerprint: serial=%r "
                                 "vid=0x%04X pid=0x%04X loc=%r",
                                 uid, fp.serial_number,
                                 fp.vid or 0, fp.pid or 0, fp.location)
                except Exception:
                    log.debug("[%s] Could not save USB fingerprint",
                              uid, exc_info=True)

            if self._post_inject_cb:
                try:
                    self._post_inject_cb(uid, driver_obj)
                except Exception:
                    log.debug("[%s] post_inject_cb failed", uid, exc_info=True)

            if on_complete:
                on_complete(True, "Connected")

        except Exception as e:
            log.error("[%s] Connect failed after %.2fs: %s",
                      uid, time.time() - t0, e, exc_info=True)

            # Release port ownership on failure
            try:
                from hardware.port_resolver import port_ownership
                port_ownership.release(uid)
            except Exception:
                pass

            # Release any resources the driver may have partially acquired
            # (serial port locks, USB handles, NI sessions, etc.).
            if driver_obj is not None:
                try:
                    driver_obj.disconnect()
                except Exception as cleanup_exc:
                    log.debug("[%s] Cleanup after failed connect: %s",
                              uid, cleanup_exc)

            with self._lock:
                entry.state     = DeviceState.ERROR
                entry.error_msg = str(e)
            self._log(f"✗  {desc.display_name}: {e}")
            self._emit(uid, DeviceState.ERROR, str(e))
            if on_complete:
                on_complete(False, str(e))

    # ---------------------------------------------------------------- #
    #  Disconnect                                                       #
    # ---------------------------------------------------------------- #

    def disconnect(self, uid: str,
                   on_complete: Optional[Callable[[bool, str], None]] = None):
        entry = self._entries.get(uid)
        if entry is None or entry.state != DeviceState.CONNECTED:
            if on_complete:
                on_complete(False, "Not connected")
            return

        entry.state = DeviceState.DISCONNECTING
        self._emit(uid, DeviceState.DISCONNECTING)

        threading.Thread(
            target=self._disconnect_worker,
            args=(uid, on_complete),
            daemon=True).start()

    def _disconnect_worker(self, uid: str,
                           on_complete: Optional[Callable]):
        entry = self._entries[uid]
        # Save the driver reference BEFORE disconnect clears it — needed
        # by _eject_from_app to identify which app_state slot to clear
        # (e.g. ir_cam vs cam for cameras).
        driver_ref = entry.driver_obj
        try:
            if entry.driver_obj and hasattr(entry.driver_obj, "disconnect"):
                entry.driver_obj.disconnect()
        except Exception as e:
            self._log(f"Disconnect warning ({entry.display_name}): {e}")
        finally:
            # ── Release port ownership ──────────────────────────────
            try:
                from hardware.port_resolver import port_ownership
                port_ownership.release(uid)
                log.info("[%s] Released port ownership", uid)
            except Exception:
                pass

            with self._lock:
                entry.driver_obj = None
                entry.state      = (DeviceState.DISCOVERED
                                    if entry.address
                                    else DeviceState.ABSENT)
            self._log(f"Disconnected: {entry.display_name}")
            self._emit(uid, entry.state)
            self._eject_from_app(uid, driver_ref=driver_ref)
            # Remove from saved auto-reconnect list
            try:
                import config as _cfg
                saved = _cfg.get_pref("hw.last_connected_devices", [])
                if isinstance(saved, list) and uid in saved:
                    saved.remove(uid)
                    _cfg.set_pref("hw.last_connected_devices", saved)
            except Exception:
                pass
            if on_complete:
                on_complete(True, "Disconnected")

    # ---------------------------------------------------------------- #
    #  Adopt existing driver from hw_service                            #
    # ---------------------------------------------------------------- #

    def _try_adopt_existing(self, entry: DeviceEntry) -> bool:
        """Check if hw_service.start() already opened this device type.

        hw_service.start() opens devices from config.yaml directly into
        app_state WITHOUT going through Device Manager.  If the user then
        clicks Connect (or auto-reconnect fires), we'd try to open the
        same USB/serial resource a second time — causing "exclusively
        opened" errors for cameras and similar conflicts elsewhere.

        This method checks the SPECIFIC app_state slot for the entry's
        device type.  For cameras it distinguishes TR vs IR so that
        connecting a Boson (IR) is not blocked by an already-open Basler
        (TR) and vice versa.

        Returns True (and sets entry.driver_obj) if an existing driver
        was adopted, False otherwise.
        """
        try:
            from hardware.app_state import app_state
            desc  = entry.descriptor
            dtype = desc.device_type

            if dtype == DTYPE_CAMERA:
                # Determine whether this specific entry is IR or TR
                # using the registry's camera_type field (not hardcoded UIDs)
                _is_ir = getattr(desc, "camera_type", "tr") == "ir"
                if _is_ir:
                    existing = app_state.ir_cam
                else:
                    existing = app_state.tr_cam
                if existing is not None:
                    # Verify it's a real driver, not a simulated one
                    try:
                        from hardware.cameras.simulated import SimulatedDriver
                        if isinstance(existing, SimulatedDriver):
                            return False   # demo driver — don't adopt
                    except ImportError:
                        pass
                    entry.driver_obj = existing
                    return True
            elif dtype == DTYPE_FPGA:
                if app_state.fpga is not None:
                    entry.driver_obj = app_state.fpga
                    return True
            elif dtype == DTYPE_STAGE:
                if app_state.stage is not None:
                    entry.driver_obj = app_state.stage
                    return True
            elif dtype == DTYPE_TEC:
                if len(app_state.tecs) > 0:
                    # Can't definitively map which TEC — adopt first match
                    entry.driver_obj = app_state.tecs[0]
                    return True
            elif dtype == DTYPE_BIAS:
                if app_state.bias is not None:
                    entry.driver_obj = app_state.bias
                    return True
        except Exception:
            log.debug("_try_adopt_existing failed for %s", entry.uid,
                      exc_info=True)
        return False

    # ---------------------------------------------------------------- #
    #  Driver instantiation                                             #
    # ---------------------------------------------------------------- #

    def _instantiate_driver(self, entry: DeviceEntry):
        """
        Build the config dict for this device and call the appropriate
        hardware factory function.
        """
        desc   = entry.descriptor
        dtype  = desc.device_type
        addr   = entry.address
        baud   = entry.baud_rate or desc.default_baud
        timeout= entry.timeout_s

        # Build config in the same format the existing hardware factories expect
        cfg = {
            "enabled": True,
            "driver":  self._driver_key(desc),
            "port":    addr,
            "baud":    baud,
            "timeout": timeout,
            "ip":      entry.ip_address or desc.default_ip,
        }

        # Known device types use their dedicated factory functions.
        # Exceptions from these factories are real errors — propagate them
        # directly so the caller sees the actual cause (e.g. "pypylon SDK
        # mismatch") rather than a confusing "driver module not found" message
        # from _load_custom_driver.
        if dtype == DTYPE_CAMERA:
            from hardware.cameras import create_camera
            # Camera modality (tr/ir): user preference > registry default.
            # The device registry knows the correct type for each model
            # (Basler → "tr", FLIR Boson → "ir"), but a user override
            # saved in device_params takes priority.
            _registry_type = getattr(desc, "camera_type", "tr")
            try:
                import config as _cfg
                _user_type = _cfg.get_pref(
                    f"device_params.{entry.uid}.camera_type", "")
                cfg["camera_type"] = _user_type if _user_type else _registry_type
            except Exception:
                cfg["camera_type"] = _registry_type
            # Boson: serial control port = entry.address (set in Device Manager),
            # UVC video device index = entry.video_index.
            # Width/height injected from registry so Boson 640 gets correct geometry.
            if desc.uid in ("flir_boson_320", "flir_boson_640",
                            "flir_boson_plus_320", "flir_boson_plus_640"):
                cfg["serial_port"] = addr  # address field stores serial port path
                cfg["video_index"] = entry.video_index
                if desc.uid in ("flir_boson_640", "flir_boson_plus_640"):
                    cfg.setdefault("width",  640)
                    cfg.setdefault("height", 512)
                else:
                    cfg.setdefault("width",  320)
                    cfg.setdefault("height", 256)
            return create_camera(cfg)
        elif dtype == DTYPE_TEC:
            from hardware.tec import create_tec
            return create_tec(cfg)
        elif dtype == DTYPE_FPGA:
            from hardware.fpga import create_fpga
            # BNC 745 uses a VISA resource string stored in entry.address
            if desc.uid == "bnc_745":
                cfg["address"] = addr or "GPIB::12"
            # TDG-VII / PT-100 uses a serial port
            if desc.uid == "tdg7":
                cfg["port"] = addr or ""
            # NI RIO devices (sbRIO, 9637): construct resource string from IP
            # and pull bitfile from device_params or config.yaml fallback.
            if desc.uid in ("ni_sbrio", "ni_9637", "ni_usb_6001"):
                ip = entry.ip_address or desc.default_ip
                # Resource string: "RIO0" (local) or "rio://IP/RIO0" (Ethernet)
                try:
                    import config as _cfg
                    saved_resource = _cfg.get_pref(
                        f"device_params.{entry.uid}.resource", "")
                    saved_bitfile = _cfg.get_pref(
                        f"device_params.{entry.uid}.bitfile", "")
                except Exception:
                    saved_resource = ""
                    saved_bitfile = ""
                if not saved_resource:
                    # Fall back to config.yaml global fpga section
                    try:
                        import config as _cfg
                        saved_resource = _cfg.get("hardware.fpga.resource", "")
                    except Exception:
                        saved_resource = ""
                if not saved_resource and ip:
                    saved_resource = f"rio://{ip}/RIO0"
                cfg["resource"] = saved_resource
                if not saved_bitfile:
                    try:
                        import config as _cfg
                        saved_bitfile = _cfg.get("hardware.fpga.bitfile", "")
                    except Exception:
                        saved_bitfile = ""
                cfg["bitfile"] = saved_bitfile
            return create_fpga(cfg)
        elif dtype == DTYPE_STAGE:
            from hardware.stage import create_stage
            return create_stage(cfg)
        elif dtype == DTYPE_PROBER:
            # Prober uses the stage factory with the mpi_prober driver key
            from hardware.stage import create_stage
            cfg_prober = dict(cfg, driver="mpi_prober")
            return create_stage(cfg_prober)
        elif dtype == DTYPE_TURRET:
            from hardware.turret.factory import create_turret
            return create_turret(cfg)
        elif dtype == DTYPE_BIAS:
            from hardware.bias import create_bias
            # AMCAD BILT uses TCP/SCPI: remap ip → host, use desc.tcp_port
            if desc.uid == "amcad_bilt":
                cfg["host"] = entry.ip_address or desc.default_ip
                cfg["port"] = desc.tcp_port or 5035
            return create_bias(cfg)
        elif dtype == DTYPE_LDD:
            from hardware.ldd.factory import create_ldd
            return create_ldd(cfg)
        elif dtype == DTYPE_GPIO:
            # Tell Arduino/ESP32 drivers which ports are already claimed
            # by other devices so their fallback scan never tries to open
            # a Meerstetter (or any other) device's port.
            claimed: list[str] = []
            for _uid, _ent in self._entries.items():
                if _uid == entry.uid:
                    continue   # skip self
                if (_ent.address
                        and _ent.state in (DeviceState.CONNECTED,
                                           DeviceState.CONNECTING,
                                           DeviceState.DISCOVERED)):
                    claimed.append(_ent.address)
            cfg["_excluded_ports"] = claimed
            from hardware.arduino.factory import create_arduino
            return create_arduino(cfg)
        else:
            # Unknown type — try a hot-loaded custom driver from
            # ~/.microsanj/drivers/<module>.py before giving up.
            return self._load_custom_driver(desc, cfg)

    def _driver_key(self, desc: DeviceDescriptor) -> str:
        """Map descriptor uid to the short driver key used by factories."""
        KEY_MAP = {
            # Cameras
            "basler_aca1920_155um":     "pypylon",
            "basler_aca2040_90umnir":   "pypylon",
            "basler_aca640_750um":      "pypylon",
            "basler_gigE_generic":      "pypylon",
            "basler_a2a1280_125um_swir": "pypylon",
            "allied_vision_goldeye_g032": "ni_imaqdx",
            "photonfocus_mv4_d1280u":   "ni_imaqdx",
            "flir_boson_320":           "boson",
            "flir_boson_640":           "boson",
            "flir_boson_plus_320":      "boson",
            "flir_boson_plus_640":      "boson",
            # TECs / thermal chucks
            "meerstetter_tec_1089":     "meerstetter",
            "meerstetter_tec_1123":     "meerstetter",
            "atec_302":                 "atec",
            "temptronic_ats_series":    "thermal_chuck",
            "cascade_thermal_chuck":    "thermal_chuck",
            "wentworth_thermal_chuck":  "thermal_chuck",
            # FPGA / timing
            "ni_9637":                  "ni9637",
            "ni_sbrio":                 "ni9637",
            "ni_usb_6001":              "ni9637",
            "bnc_745":                  "bnc745",
            "tdg7":                     "tdg7",
            # Stages / prober
            "thorlabs_bsc203":          "thorlabs",
            "thorlabs_mpc320":          "thorlabs",
            "prior_proscan":            "prior",
            "newport_npc3":             "newport_npc3",
            "mpi_prober_generic":       "mpi_prober",
            # Turret
            "olympus_ix_turret":        "olympus_linx",
            # Bias sources
            "keithley_2400":            "keithley",
            "keithley_2450":            "keithley",
            "rigol_dp832":              "visa",
            "amcad_bilt":               "amcad_bilt",
            # Laser diode driver
            "meerstetter_ldd1121":      "meerstetter_ldd1121",
            # Arduino GPIO / LED selector
            "arduino_nano_ch340":       "nano",
            "arduino_nano_ftdi":        "nano",
            "arduino_uno":              "uno",
            "arduino_uno_r4":           "uno",
            "arduino_uno_r4_wifi":      "uno",
            "arduino_uno_q":            "nano",
            # ESP32 GPIO / LED selector
            "arduino_nano_esp32":       "esp32",
            "esp32_cp2102":             "esp32",
            "esp32_native_usb":         "esp32",
        }
        return KEY_MAP.get(desc.uid, desc.uid)

    def _load_custom_driver(self, desc: DeviceDescriptor, cfg: dict):
        """
        Attempt to load a hot-loaded driver from
        ~/.microsanj/drivers/<module_name>.py
        """
        import os, importlib.util
        drivers_dir = os.path.join(
            os.path.expanduser("~"), ".microsanj", "drivers")
        mod_name = desc.driver_module.split(".")[-1]
        path     = os.path.join(drivers_dir, f"{mod_name}.py")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Driver module not found: {path}\n"
                f"Try downloading the driver from Device Manager → Driver Store.")
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.create(cfg)

    # ---------------------------------------------------------------- #
    #  App integration                                                  #
    # ---------------------------------------------------------------- #

    def _inject_into_app(self, uid: str, driver_obj):
        """Write connected driver into the app_state singleton."""
        try:
            from hardware.app_state import app_state
            desc  = self._entries[uid].descriptor
            dtype = desc.device_type

            # Snapshot current state so we can roll back on failure
            _snap = {
                "cam":    app_state.cam,
                "fpga":   app_state.fpga,
                "stage":  app_state.stage,
                "prober": app_state.prober,
                "bias":   app_state.bias,
                "turret": app_state.turret,
                "active_objective": app_state.active_objective,
                "ldd":    app_state.ldd,
                "gpio":   app_state.gpio,
            }

            try:
                if dtype == DTYPE_CAMERA:
                    # Route IR cameras (Boson etc.) to the ir_cam slot;
                    # TR/visible cameras go to the primary cam slot.
                    _cam_type = getattr(
                        getattr(driver_obj, "info", None), "camera_type", "tr"
                    ) or "tr"
                    if str(_cam_type).lower() == "ir":
                        app_state.ir_cam = driver_obj
                        # Auto-select IR ONLY if no real TR camera exists
                        # and the user hasn't already made a deliberate
                        # selection.  Check whether a real TR camera is
                        # present — if so, leave the user's choice alone.
                        _tr = app_state.tr_cam
                        _tr_is_real = False
                        if _tr is not None:
                            try:
                                from hardware.cameras.simulated import SimulatedDriver
                                _tr_is_real = not isinstance(_tr, SimulatedDriver)
                            except Exception:
                                _tr_is_real = True   # can't determine — assume real
                        if not _tr_is_real:
                            app_state.active_camera_type = "ir"
                    else:
                        app_state.cam = driver_obj
                        # Only auto-switch to TR if there was NO real TR
                        # camera before (i.e. this is the first TR camera
                        # connecting).  If the user has deliberately selected
                        # IR via the camera bar, respect that choice — don't
                        # force-switch back to TR on every reconnect.
                    # Start the frame-grab thread inside the driver.
                    try:
                        driver_obj.start()
                    except Exception:
                        log.debug("[%s] driver.start() failed or not needed",
                                  uid, exc_info=True)
                elif dtype == DTYPE_FPGA:    app_state.fpga   = driver_obj
                elif dtype == DTYPE_STAGE:   app_state.stage  = driver_obj
                elif dtype == DTYPE_PROBER:  app_state.prober = driver_obj
                elif dtype == DTYPE_BIAS:    app_state.bias   = driver_obj
                elif dtype == DTYPE_TURRET:
                    app_state.turret = driver_obj
                    # Prime active_objective from current turret position
                    try:
                        spec = driver_obj.get_objective()
                        if spec is not None:
                            app_state.active_objective = spec
                    except Exception:
                        log.debug("[%s] get_objective() failed — "
                                  "active_objective unchanged", uid, exc_info=True)
                elif dtype == DTYPE_TEC:
                    app_state.add_tec(driver_obj)
                elif dtype == DTYPE_LDD:
                    app_state.ldd = driver_obj
                elif dtype == DTYPE_GPIO:
                    app_state.gpio = driver_obj
            except Exception:
                # Restore snapshot to avoid partial app_state mutation
                log.warning("[%s] _inject_into_app failed — rolling back app_state",
                            uid, exc_info=True)
                for attr, val in _snap.items():
                    try:
                        setattr(app_state, attr, val)
                    except Exception:
                        log.debug("[%s] rollback setattr(%r) failed",
                                  uid, attr, exc_info=True)
                with self._lock:
                    entry = self._entries.get(uid)
                    if entry:
                        entry.state = DeviceState.ERROR
                        entry.error_msg = "app_state injection failed"
                self._emit(uid, DeviceState.ERROR, "app_state injection failed")

        except Exception:
            log.warning("[%s] _inject_into_app: unexpected error", uid, exc_info=True)

    def _eject_from_app(self, uid: str, driver_ref=None):
        """Clear the app_state reference when a device disconnects.

        ``driver_ref`` is the driver object saved **before** disconnect
        cleared ``entry.driver_obj``.  Without it the identity check
        (e.g. ``driver_ref is app_state.ir_cam``) would always fail and
        IR cameras would never be properly ejected.
        """
        try:
            from hardware.app_state import app_state
            desc  = self._entries[uid].descriptor
            dtype = desc.device_type
            # Use the pre-disconnect reference if provided, otherwise
            # fall back to the entry (may already be None).
            driver_obj = driver_ref or self._entries[uid].driver_obj
            if dtype == DTYPE_CAMERA:
                # Clear the correct slot — IR cameras go to ir_cam, TR to cam.
                if driver_obj is not None and driver_obj is app_state.ir_cam:
                    app_state.ir_cam = None
                else:
                    app_state.cam = None
            elif dtype == DTYPE_FPGA:    app_state.fpga   = None
            elif dtype == DTYPE_STAGE:   app_state.stage  = None
            elif dtype == DTYPE_PROBER:  app_state.prober = None
            elif dtype == DTYPE_BIAS:    app_state.bias   = None
            elif dtype == DTYPE_TURRET:
                app_state.turret           = None
                app_state.active_objective = None
            elif dtype == DTYPE_TEC:
                # Remove this TEC from the list; preserve order of others
                with app_state:
                    app_state.tecs = [t for t in app_state.tecs
                                      if t is not driver_obj]
            elif dtype == DTYPE_LDD:
                app_state.ldd = None
            elif dtype == DTYPE_GPIO:
                app_state.gpio = None
        except Exception:
            log.warning("[%s] _eject_from_app failed — app_state may still "
                        "hold a stale reference", uid, exc_info=True)

    # ---------------------------------------------------------------- #
    #  Query                                                            #
    # ---------------------------------------------------------------- #

    def get(self, uid: str) -> Optional[DeviceEntry]:
        return self._entries.get(uid)

    def all(self) -> List[DeviceEntry]:
        with self._lock:
            return list(self._entries.values())

    def connected(self) -> List[DeviceEntry]:
        return [e for e in self.all() if e.is_connected]

    def apply_driver_update(self, uid: str, new_version: str) -> bool:
        """Mark an entry as using an updated driver version."""
        entry = self._entries.get(uid)
        if entry:
            entry.driver_ver = new_version
            return True
        return False

    # ---------------------------------------------------------------- #
    #  Safe-mode state machine                                          #
    # ---------------------------------------------------------------- #

    @property
    def safe_mode(self) -> bool:
        """True when a required device is absent and operations must be blocked."""
        return self._safe_mode

    @property
    def safe_mode_reason(self) -> str:
        """Human-readable explanation of why safe mode is active."""
        return self._safe_mode_reason

    def set_safe_mode(self, reason: str) -> None:
        """
        Activate safe mode.

        Safe mode is set by the application when ``check_readiness()``
        finds that one or more *required* devices are missing.  The
        reason string is displayed in the UI banner and recorded in the
        event timeline.

        Calling this when safe mode is already active with the same
        reason is a no-op (avoids spurious event-bus traffic).
        """
        if self._safe_mode and self._safe_mode_reason == reason:
            return
        self._safe_mode        = True
        self._safe_mode_reason = reason
        log.warning("Safe mode ACTIVE: %s", reason)
        try:
            from events import emit_warning, EVT_SAFE_MODE_ACTIVE
            emit_warning("hardware.device_manager", EVT_SAFE_MODE_ACTIVE,
                         f"Safe mode active: {reason}", reason=reason)
        except Exception:
            log.debug("DeviceManager.set_safe_mode: event bus emit failed",
                      exc_info=True)

    def clear_safe_mode(self) -> None:
        """
        Deactivate safe mode.

        Called when ``check_readiness()`` confirms that all required
        devices for the most demanding operation are present.
        """
        if not self._safe_mode:
            return
        self._safe_mode        = False
        self._safe_mode_reason = ""
        log.info("Safe mode CLEARED — all required devices present")
        try:
            from events import emit_info, EVT_SAFE_MODE_CLEARED
            emit_info("hardware.device_manager", EVT_SAFE_MODE_CLEARED,
                      "Safe mode cleared — all required devices present")
        except Exception:
            log.debug("DeviceManager.clear_safe_mode: event bus emit failed",
                      exc_info=True)
