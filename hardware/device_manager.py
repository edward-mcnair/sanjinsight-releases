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

from .device_registry import (DeviceDescriptor, DEVICE_REGISTRY,
                                DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA,
                                DTYPE_STAGE, DTYPE_PROBER, DTYPE_TURRET,
                                DTYPE_BIAS, DTYPE_LDD)
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


STATE_COLORS = {
    DeviceState.ABSENT:        "#333333",
    DeviceState.DISCOVERED:    "#4488ff",
    DeviceState.CONNECTING:    "#ffaa00",
    DeviceState.CONNECTED:     "#00d4aa",
    DeviceState.ERROR:         "#ff3b3b",
    DeviceState.DISCONNECTING: "#ffaa00",
}

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
    address:        str             = ""   # current port / IP / resource
    serial_number:  str             = ""
    firmware_ver:   str             = ""
    driver_ver:     str             = ""
    error_msg:      str             = ""
    last_seen:      float           = 0.0
    last_connected: float           = 0.0
    driver_obj:     object          = None   # live driver instance

    # Connection params (may be overridden by user in settings)
    baud_rate:  int   = 0
    ip_address: str   = ""
    timeout_s:  float = 2.0

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
        return STATE_COLORS.get(self.state, "#555")

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

        # Initialise an entry for every known device and restore any
        # connection parameters (port, baud, IP) saved in a previous session.
        for uid, desc in DEVICE_REGISTRY.items():
            entry = DeviceEntry(descriptor=desc)
            try:
                import config as _cfg
                saved = _cfg.get_pref(f"device_params.{uid}", {})
                if saved.get("address"):    entry.address    = saved["address"]
                if saved.get("baud_rate"):  entry.baud_rate  = saved["baud_rate"]
                if saved.get("ip_address"): entry.ip_address = saved["ip_address"]
                if saved.get("timeout_s"):  entry.timeout_s  = saved["timeout_s"]
            except Exception:
                pass   # config not yet initialised at import time — ignore
            self._entries[uid] = entry

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
    #  Scan integration                                                 #
    # ---------------------------------------------------------------- #

    def update_from_scan(self, report: ScanReport):
        """
        Update all device entries based on the latest scan report.
        Devices that were CONNECTED are not disturbed.
        """
        with self._lock:
            # Mark everything not currently connected as ABSENT first
            for entry in self._entries.values():
                if entry.state not in (DeviceState.CONNECTED,
                                       DeviceState.CONNECTING,
                                       DeviceState.DISCONNECTING):
                    entry.state = DeviceState.ABSENT

            # Update entries for discovered devices
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
                entry.state         = DeviceState.DISCOVERED
                entry.address       = dev.address
                entry.serial_number = dev.serial_number or ""
                entry.last_seen     = time.time()
                self._emit(uid, DeviceState.DISCOVERED, dev.address)

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
            needs_address = desc.connection_type in ("serial", "usb", "ethernet")
            if needs_address and not entry.address:
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

            # Enforce a hard timeout on connect() so the UI is never frozen.
            log.info("[%s] Connecting %s on %s …",
                     uid, desc.display_name, entry.address or "?")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(driver_obj.connect)
                try:
                    future.result(timeout=_CONNECT_TIMEOUT_S)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(
                        f"Connect timed out after {_CONNECT_TIMEOUT_S:.0f}s. "
                        f"Check that the device is powered and not held by "
                        f"another process (terminal, firmware updater, etc.)."
                    )

            log.info("[%s] Connected in %.2fs", uid, time.time() - t0)

            with self._lock:
                entry.driver_obj     = driver_obj
                entry.state          = DeviceState.CONNECTED
                entry.last_connected = time.time()
                entry.error_msg      = ""
                try:
                    st = driver_obj.get_status()
                    entry.firmware_ver  = getattr(st, "firmware_version", "") or ""
                    entry.serial_number = getattr(st, "serial_number",
                                                  entry.serial_number) or ""
                except Exception:
                    log.debug("[%s] get_status() for metadata failed — "
                              "firmware/serial will be blank", uid, exc_info=True)

            self._log(f"✓  Connected: {desc.display_name}  ({entry.address})")
            self._emit(uid, DeviceState.CONNECTED)
            self._inject_into_app(uid, driver_obj)

            if on_complete:
                on_complete(True, "Connected")

        except Exception as e:
            log.error("[%s] Connect failed after %.2fs: %s",
                      uid, time.time() - t0, e, exc_info=True)

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
        try:
            if entry.driver_obj and hasattr(entry.driver_obj, "disconnect"):
                entry.driver_obj.disconnect()
        except Exception as e:
            self._log(f"Disconnect warning ({entry.display_name}): {e}")
        finally:
            with self._lock:
                entry.driver_obj = None
                entry.state      = (DeviceState.DISCOVERED
                                    if entry.address
                                    else DeviceState.ABSENT)
            self._log(f"Disconnected: {entry.display_name}")
            self._emit(uid, entry.state)
            self._eject_from_app(uid)
            if on_complete:
                on_complete(True, "Disconnected")

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
            return create_camera(cfg)
        elif dtype == DTYPE_TEC:
            from hardware.tec import create_tec
            return create_tec(cfg)
        elif dtype == DTYPE_FPGA:
            from hardware.fpga import create_fpga
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
            return create_bias(cfg)
        elif dtype == DTYPE_LDD:
            from hardware.ldd.factory import create_ldd
            return create_ldd(cfg)
        else:
            # Unknown type — try a hot-loaded custom driver from
            # ~/.microsanj/drivers/<module>.py before giving up.
            return self._load_custom_driver(desc, cfg)

    def _driver_key(self, desc: DeviceDescriptor) -> str:
        """Map descriptor uid to the short driver key used by factories."""
        KEY_MAP = {
            "basler_aca1920_155um":     "pypylon",
            "basler_aca640_750um":      "pypylon",
            "basler_gigE_generic":      "pypylon",
            "meerstetter_tec_1089":     "meerstetter",
            "meerstetter_tec_1123":     "meerstetter",
            "atec_302":                 "atec",
            "temptronic_ats_series":    "thermal_chuck",
            "cascade_thermal_chuck":    "thermal_chuck",
            "wentworth_thermal_chuck":  "thermal_chuck",
            "ni_9637":                  "ni9637",
            "ni_usb_6001":              "ni9637",
            "thorlabs_bsc203":          "thorlabs",
            "thorlabs_mpc320":          "thorlabs",
            "prior_proscan":            "prior",
            "mpi_prober_generic":       "mpi_prober",
            "olympus_ix_turret":        "olympus_linx",
            "keithley_2400":            "keithley",
            "keithley_2450":            "keithley",
            "rigol_dp832":              "visa",
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
            }

            try:
                if   dtype == DTYPE_CAMERA:  app_state.cam    = driver_obj
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

    def _eject_from_app(self, uid: str):
        """Clear the app_state reference when a device disconnects."""
        try:
            from hardware.app_state import app_state
            desc  = self._entries[uid].descriptor
            dtype = desc.device_type
            driver_obj = self._entries[uid].driver_obj
            if   dtype == DTYPE_CAMERA:  app_state.cam    = None
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
