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
import time, threading, importlib
from dataclasses   import dataclass, field
from enum          import Enum, auto
from typing        import List, Optional, Dict, Callable

from .device_registry import (DeviceDescriptor, DEVICE_REGISTRY,
                                DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA,
                                DTYPE_STAGE, DTYPE_BIAS)
from .device_scanner  import DiscoveredDevice, ScanReport


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

        # Initialise an entry for every known device
        for uid, desc in DEVICE_REGISTRY.items():
            self._entries[uid] = DeviceEntry(descriptor=desc)

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
                pass

    def _log(self, msg: str):
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:
                pass

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
        if entry.state == DeviceState.CONNECTED:
            if on_complete:
                on_complete(True, "Already connected")
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

        try:
            driver_obj = self._instantiate_driver(entry)
            driver_obj.connect()

            with self._lock:
                entry.driver_obj     = driver_obj
                entry.state          = DeviceState.CONNECTED
                entry.last_connected = time.time()
                entry.error_msg      = ""
                # Try to read firmware/serial from driver
                try:
                    st = driver_obj.get_status()
                    entry.firmware_ver = getattr(st, "firmware_version", "") or ""
                    entry.serial_number = getattr(st, "serial_number",
                                                   entry.serial_number) or ""
                except Exception:
                    pass

            self._log(f"✓  Connected: {desc.display_name}  ({entry.address})")
            self._emit(uid, DeviceState.CONNECTED)

            # Inject into main_app globals
            self._inject_into_app(uid, driver_obj)

            if on_complete:
                on_complete(True, "Connected")

        except Exception as e:
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

        try:
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
            elif dtype == DTYPE_BIAS:
                from hardware.bias import create_bias
                return create_bias(cfg)
            else:
                raise ValueError(f"No factory for device type: {dtype}")
        except Exception:
            # Try hot-loading a custom driver module if present
            return self._load_custom_driver(desc, cfg)

    def _driver_key(self, desc: DeviceDescriptor) -> str:
        """Map descriptor uid to the short driver key used by factories."""
        KEY_MAP = {
            "basler_aca1920_155um": "pypylon",
            "basler_aca640_750um":  "pypylon",
            "basler_gigE_generic":  "pypylon",
            "meerstetter_tec_1089": "meerstetter",
            "meerstetter_tec_1123": "meerstetter",
            "atec_302":             "atec",
            "ni_9637":              "ni9637",
            "ni_usb_6001":          "ni9637",
            "thorlabs_bsc203":      "thorlabs",
            "thorlabs_mpc320":      "thorlabs",
            "prior_proscan":        "prior",
            "keithley_2400":        "keithley",
            "keithley_2450":        "keithley",
            "rigol_dp832":          "visa",
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
        """Write connected driver into the main_app global namespace."""
        try:
            import main_app as _ma
            desc = self._entries[uid].descriptor
            dtype = desc.device_type
            if   dtype == DTYPE_CAMERA: _ma.cam     = driver_obj
            elif dtype == DTYPE_FPGA:   _ma.fpga    = driver_obj
            elif dtype == DTYPE_STAGE:  _ma.stage   = driver_obj
            elif dtype == DTYPE_BIAS:   _ma.bias    = driver_obj
            elif dtype == DTYPE_TEC:
                # Assign to first empty TEC slot
                if not getattr(_ma, "tec1", None):  _ma.tec1 = driver_obj
                elif not getattr(_ma, "tec2", None): _ma.tec2 = driver_obj
        except Exception:
            pass

    def _eject_from_app(self, uid: str):
        """Clear the main_app global when a device disconnects."""
        try:
            import main_app as _ma
            desc  = self._entries[uid].descriptor
            dtype = desc.device_type
            if   dtype == DTYPE_CAMERA: _ma.cam  = None
            elif dtype == DTYPE_FPGA:   _ma.fpga = None
            elif dtype == DTYPE_STAGE:  _ma.stage= None
            elif dtype == DTYPE_BIAS:   _ma.bias = None
            elif dtype == DTYPE_TEC:
                if getattr(_ma, "tec1", None) is self._entries[uid].driver_obj:
                    _ma.tec1 = None
                elif getattr(_ma, "tec2", None) is self._entries[uid].driver_obj:
                    _ma.tec2 = None
        except Exception:
            pass

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
