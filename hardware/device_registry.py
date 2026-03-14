"""
hardware/device_registry.py

Central catalog of every device the Microsanj system knows about.

Each entry maps hardware identifiers (VID/PID, port patterns,
NI resource name patterns, TCP ports) to a DeviceDescriptor that
carries display metadata and the driver module to load.

This file is the single place to update when Microsanj adds support
for a new piece of hardware. Field technicians never touch this —
updated registries are delivered automatically via the driver store.

Registry format
---------------
DEVICE_REGISTRY : dict[str, DeviceDescriptor]
  key  = stable UID  (e.g. "meerstetter_tec_1089")
  value= DeviceDescriptor

PortPattern matching (serial / network)
  - Serial:  matched against port description or hwid string (case-insensitive)
  - Network: matched against TCP banner or mDNS service name
  - NI/PCIe: matched against NI resource name (e.g. "RIO0", "Dev1")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing      import List, Optional


# ------------------------------------------------------------------ #
#  Device types                                                        #
# ------------------------------------------------------------------ #

DTYPE_CAMERA  = "camera"
DTYPE_TEC     = "tec"
DTYPE_FPGA    = "fpga"
DTYPE_STAGE   = "stage"
DTYPE_PROBER  = "prober"   # probe-station chuck stage
DTYPE_TURRET  = "turret"   # motorized objective turret
DTYPE_BIAS    = "bias"
DTYPE_LDD     = "ldd"      # laser diode driver / LED illumination controller
DTYPE_UNKNOWN = "unknown"

CONN_SERIAL   = "serial"
CONN_USB      = "usb"
CONN_ETHERNET = "ethernet"
CONN_PCIE     = "pcie"
CONN_CAMERA   = "camera"   # cameras enumerated via SDK (pypylon, NI IMAQdx)


# ------------------------------------------------------------------ #
#  Descriptor                                                          #
# ------------------------------------------------------------------ #

@dataclass
class DeviceDescriptor:
    uid:            str
    display_name:   str
    manufacturer:   str
    device_type:    str                  # DTYPE_*
    connection_type: str                 # CONN_*

    # Driver info
    driver_module:  str                  # e.g. "hardware.tec.meerstetter"
    driver_version: str  = "builtin"
    hot_loadable:   bool = False         # can driver be swapped without restart?

    # Identification — any truthy match → device recognised
    usb_vid:         Optional[int]  = None   # USB vendor ID (int)
    usb_pid:         Optional[int]  = None   # USB product ID (int)
    serial_patterns: List[str]      = field(default_factory=list)
    # Strings that appear in pyserial port description or hwid
    ni_patterns:     List[str]      = field(default_factory=list)
    # Substrings of NI resource name
    tcp_port:        Optional[int]  = None   # well-known TCP port
    tcp_banner:      Optional[str]  = None   # string in TCP banner

    # Default connection parameters (can be overridden per-installation)
    default_baud:    int   = 115200
    default_timeout: float = 2.0
    default_ip:      str   = ""

    # Camera-specific (device_type == DTYPE_CAMERA only)
    # Default camera modality for this hardware model.  Per-installation
    # overrides are stored in config.yaml (hardware.camera.camera_type or
    # hardware.cameras[n].camera_type).
    camera_type:    str   = "tr"   # "tr" | "ir" — default for this model

    # Human-readable
    description:    str   = ""
    datasheet_url:  str   = ""
    notes:          str   = ""


# ------------------------------------------------------------------ #
#  Registry                                                            #
# ------------------------------------------------------------------ #

DEVICE_REGISTRY: dict[str, DeviceDescriptor] = {

    # ---------------------------------------------------------------- #
    #  Cameras                                                         #
    # ---------------------------------------------------------------- #

    "basler_aca1920_155um": DeviceDescriptor(
        uid            = "basler_aca1920_155um",
        display_name   = "Basler acA1920-155um",
        manufacturer   = "Basler AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        driver_module  = "hardware.cameras.pypylon_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x2676,    # Basler USB3 Vision VID
        usb_pid        = 0xBA02,
        serial_patterns= ["Basler", "acA1920"],
        description    = "USB3 Vision monochrome camera, 1920×1200 @ 155 fps. "
                         "Primary imaging sensor for thermoreflectance measurements.",
        datasheet_url  = "https://www.baslerweb.com/en/products/cameras/area-scan-cameras/ace/aca1920-155um/",
    ),

    "basler_aca2040_90umnir": DeviceDescriptor(
        uid            = "basler_aca2040_90umnir",
        display_name   = "Basler acA2040-90umNIR",
        manufacturer   = "Basler AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        driver_module  = "hardware.cameras.pypylon_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x2676,    # Basler USB3 Vision VID (all models)
        usb_pid        = 0xBA02,    # USB3 Vision standard PID
        serial_patterns= ["Basler", "acA2040", "acA2040-90umNIR"],
        description    = "USB3 Vision near-infrared (NIR) camera, 2048×1536 @ 90 fps. "
                         "NIR-optimised sensor for thermoreflectance at 850–1000 nm.",
        datasheet_url  = "https://www.baslerweb.com/en/products/cameras/area-scan-cameras/ace/aca2040-90umnir/",
    ),

    "basler_aca640_750um": DeviceDescriptor(
        uid            = "basler_aca640_750um",
        display_name   = "Basler acA640-750um",
        manufacturer   = "Basler AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        driver_module  = "hardware.cameras.pypylon_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x2676,
        usb_pid        = 0xBA03,
        serial_patterns= ["Basler", "acA640"],
        description    = "USB3 Vision monochrome camera, 640×480 @ 750 fps. "
                         "High-speed variant for fast thermal transient capture.",
    ),

    "basler_gigE_generic": DeviceDescriptor(
        uid            = "basler_gigE_generic",
        display_name   = "Basler GigE Camera",
        manufacturer   = "Basler AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_ETHERNET,
        driver_module  = "hardware.cameras.pypylon_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        tcp_port       = 3956,     # GigE Vision control port
        tcp_banner     = "Basler",
        description    = "Basler GigE Vision camera (any model). "
                         "Requires GigE Vision compliant network interface.",
    ),

    "microsanj_ir_camera_v1a": DeviceDescriptor(
        uid            = "microsanj_ir_camera_v1a",
        display_name   = "Microsanj Infrared Camera v1a",
        manufacturer   = "Microsanj / FLIR Systems (dist. OEMCameras.com)",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        camera_type    = "ir",         # always an IR camera
        driver_module  = "hardware.cameras.flir_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x09CB,     # FLIR Boson USB VID
        usb_pid        = None,       # PID varies by Boson revision
        serial_patterns= ["Boson", "FLIR", "Microsanj IR"],
        description    = "FLIR Boson-based uncooled microbolometer thermal camera "
                         "mounted in a Microsanj nosepiece housing. "
                         "320×256 or 640×512, 16-bit radiometric, ~30 fps. "
                         "IR imaging channel for passive lock-in IR thermography "
                         "(no stimulus required).",
        datasheet_url  = "https://www.flir.com/products/boson/",
        notes          = "Driver uses flirpy (bundled). Connects via USB CDC "
                         "(serial control) + UVC (video stream). "
                         "Set config key hardware.camera.driver='flir' and "
                         "hardware.camera.modality='ir_lockin' to activate "
                         "the IR imaging path in AutoScan.",
    ),

    # ---------------------------------------------------------------- #
    #  TEC Controllers                                                  #
    # ---------------------------------------------------------------- #

    "meerstetter_tec_1089": DeviceDescriptor(
        uid            = "meerstetter_tec_1089",
        display_name   = "Meerstetter TEC-1089",
        manufacturer   = "Meerstetter Engineering",
        device_type    = DTYPE_TEC,
        connection_type= CONN_USB,
        driver_module  = "hardware.tec.meerstetter",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0403,   # FTDI
        usb_pid        = 0x6001,
        serial_patterns= ["Meerstetter", "TEC-1089", "0403:6001"],
        # Note: generic USB-serial adapters (Prolific, CH340, CP2102) are
        # intentionally NOT matched here — the same adapter chip is used by
        # hundreds of different devices and would cause false positives.
        # Users with non-FTDI cables must assign the COM port manually.
        default_baud   = 57600,
        description    = "Single-channel TEC controller with USB/serial interface. "
                         "Used for precise sample temperature control and calibration.",
        datasheet_url  = "https://www.meerstetter.ch/products/tec-controllers/tec-1089",
    ),

    "meerstetter_tec_1123": DeviceDescriptor(
        uid            = "meerstetter_tec_1123",
        display_name   = "Meerstetter TEC-1123",
        manufacturer   = "Meerstetter Engineering",
        device_type    = DTYPE_TEC,
        connection_type= CONN_USB,
        driver_module  = "hardware.tec.meerstetter",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0403,
        usb_pid        = 0x6010,
        serial_patterns= ["Meerstetter", "TEC-1123"],
        default_baud   = 57600,
        description    = "Dual-channel TEC controller. Supports independent control "
                         "of two thermoelectric modules simultaneously.",
    ),

    "atec_302": DeviceDescriptor(
        uid            = "atec_302",
        display_name   = "ATEC-302 TEC Controller",
        manufacturer   = "Arroyo Instruments",
        device_type    = DTYPE_TEC,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.tec.atec",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["ATEC", "Arroyo", "0403:6001"],
        # Note: generic adapters intentionally excluded — see Meerstetter note above.
        default_baud   = 38400,
        description    = "RS-232 TEC controller with Modbus-style protocol. "
                         "Used as secondary TEC in dual-channel configurations.",
    ),

    # ---------------------------------------------------------------- #
    #  FPGA / NI Hardware                                              #
    # ---------------------------------------------------------------- #

    "ni_9637": DeviceDescriptor(
        uid            = "ni_9637",
        display_name   = "NI 9637 FPGA Module",
        manufacturer   = "National Instruments",
        device_type    = DTYPE_FPGA,
        connection_type= CONN_PCIE,
        driver_module  = "hardware.fpga.ni9637",
        driver_version = "builtin",
        hot_loadable   = False,
        ni_patterns    = ["RIO", "9637", "cRIO"],
        description    = "NI CompactRIO FPGA module. Generates lock-in reference "
                         "signal for hot/cold modulation and frame synchronisation.",
        datasheet_url  = "https://www.ni.com/en/shop/model/ni-9637.html",
        notes          = "Requires NI-RIO drivers and compiled FPGA bitfile.",
    ),

    "ni_usb_6001": DeviceDescriptor(
        uid            = "ni_usb_6001",
        display_name   = "NI USB-6001 DAQ",
        manufacturer   = "National Instruments",
        device_type    = DTYPE_FPGA,
        connection_type= CONN_USB,
        driver_module  = "hardware.fpga.ni9637",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x3923,   # National Instruments
        usb_pid        = 0x7272,
        serial_patterns= ["NI USB", "USB-6001"],
        ni_patterns    = ["Dev", "USB"],
        description    = "USB multifunction DAQ (fallback / bench configuration). "
                         "Lower modulation bandwidth than CompactRIO.",
    ),

    # ---------------------------------------------------------------- #
    #  Stage Controllers                                                #
    # ---------------------------------------------------------------- #

    "thorlabs_bsc203": DeviceDescriptor(
        uid            = "thorlabs_bsc203",
        display_name   = "Thorlabs BSC203 Stage Controller",
        manufacturer   = "Thorlabs",
        device_type    = DTYPE_STAGE,
        connection_type= CONN_USB,
        driver_module  = "hardware.stage.thorlabs",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0699,   # Thorlabs
        usb_pid        = 0x0203,
        serial_patterns= ["Thorlabs", "BSC203", "APT"],
        default_baud   = 115200,
        description    = "3-axis Brushless DC servo controller. "
                         "Drives XYZ translation stage for scanning measurements.",
        datasheet_url  = "https://www.thorlabs.com/thorproduct.cfm?partnumber=BSC203",
    ),

    "thorlabs_mpc320": DeviceDescriptor(
        uid            = "thorlabs_mpc320",
        display_name   = "Thorlabs MPC320 Piezo Controller",
        manufacturer   = "Thorlabs",
        device_type    = DTYPE_STAGE,
        connection_type= CONN_USB,
        driver_module  = "hardware.stage.thorlabs",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0699,
        usb_pid        = 0x0320,
        serial_patterns= ["Thorlabs", "MPC320"],
        description    = "Piezo inertia stage controller. "
                         "Used for fine Z-axis focus adjustment.",
    ),

    "prior_proscan": DeviceDescriptor(
        uid            = "prior_proscan",
        display_name   = "Prior ProScan III Stage",
        manufacturer   = "Prior Scientific",
        device_type    = DTYPE_STAGE,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.stage.prior",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Prior", "ProScan"],
        default_baud   = 9600,
        description    = "RS-232 XY motorised stage controller.",
    ),

    # ---------------------------------------------------------------- #
    #  Bias Sources                                                     #
    # ---------------------------------------------------------------- #

    "keithley_2400": DeviceDescriptor(
        uid            = "keithley_2400",
        display_name   = "Keithley 2400 SourceMeter",
        manufacturer   = "Keithley Instruments",
        device_type    = DTYPE_BIAS,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.bias.keithley",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Keithley", "2400", "GPIB"],
        default_baud   = 9600,
        description    = "GPIB/RS-232 source measure unit. "
                         "Provides stable DC bias current or voltage to DUT.",
        datasheet_url  = "https://www.tek.com/en/products/keithley/source-measure-units/2400-standard-series-sourcemeter",
    ),

    "keithley_2450": DeviceDescriptor(
        uid            = "keithley_2450",
        display_name   = "Keithley 2450 TouchScreen SMU",
        manufacturer   = "Keithley Instruments",
        device_type    = DTYPE_BIAS,
        connection_type= CONN_USB,
        driver_module  = "hardware.bias.keithley",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x05E6,   # Keithley
        usb_pid        = 0x2450,
        serial_patterns= ["Keithley", "2450"],
        description    = "USB/Ethernet SMU with touchscreen. "
                         "Supports 4-wire Kelvin sensing for accurate resistance measurement.",
    ),

    "rigol_dp832": DeviceDescriptor(
        uid            = "rigol_dp832",
        display_name   = "Rigol DP832 Power Supply",
        manufacturer   = "Rigol Technologies",
        device_type    = DTYPE_BIAS,
        connection_type= CONN_ETHERNET,
        driver_module  = "hardware.bias.visa_generic",
        driver_version = "builtin",
        hot_loadable   = True,
        tcp_port       = 5555,
        serial_patterns= ["Rigol", "DP832"],
        description    = "Triple-output programmable DC power supply. "
                         "Used as lower-cost bias source for less demanding applications.",
    ),

    # ---------------------------------------------------------------- #
    #  Laser Diode Drivers                                             #
    # ---------------------------------------------------------------- #

    "meerstetter_ldd1121": DeviceDescriptor(
        uid            = "meerstetter_ldd1121",
        display_name   = "Meerstetter LDD-1121",
        manufacturer   = "Meerstetter Engineering",
        device_type    = DTYPE_LDD,
        connection_type= CONN_USB,
        driver_module  = "hardware.ldd.meerstetter_ldd1121",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0403,   # FTDI — same adapter as TEC-1089
        usb_pid        = 0x6001,
        serial_patterns= ["Meerstetter", "LDD-1121", "LDD1121"],
        default_baud   = 57600,
        description    = (
            "Meerstetter LDD-1121 laser diode / LED driver. "
            "Shares RS-485 bus with TEC-1089 (address 1 vs TEC address 2). "
            "Controls illumination amplitude; pulse timing driven by FPGA HW Pin. "
            "Max current: 2 A.  Factory serial: 4798."),
        datasheet_url  = "https://www.meerstetter.ch/products/laser-diode-drivers",
        notes          = (
            "Uses MeCom protocol (pyMeCom). "
            "Parameter IDs: 1000=temp, 1020=actual_I, 1021=actual_V, "
            "2010=enable, 3000=target_I."),
    ),

    # ---------------------------------------------------------------- #
    #  Probe Station (MPI / FormFactor)                                #
    # ---------------------------------------------------------------- #

    "mpi_prober_generic": DeviceDescriptor(
        uid            = "mpi_prober_generic",
        display_name   = "MPI Probe Station (Generic ASCII)",
        manufacturer   = "FormFactor / MPI",
        device_type    = DTYPE_PROBER,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.stage.mpi_prober",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["MPI", "FormFactor", "ProbeStation"],
        default_baud   = 115200,
        description    = "MPI/FormFactor wafer probe station chuck stage. "
                         "Controls XYZ chuck positioning and probe needle contact/lift. "
                         "Stored separately from the optical microscope scan stage.",
        notes          = "Command set may vary by firmware version. "
                         "See config key 'protocol' overrides if default commands fail.",
    ),

    # ---------------------------------------------------------------- #
    #  Thermal Chuck Controllers                                        #
    # ---------------------------------------------------------------- #

    "temptronic_ats_series": DeviceDescriptor(
        uid            = "temptronic_ats_series",
        display_name   = "Temptronic ATS Thermal Chuck",
        manufacturer   = "Temptronic (Spirent)",
        device_type    = DTYPE_TEC,       # integrates as TEC in temperature_tab
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.tec.thermal_chuck",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Temptronic", "ATS", "Thermostream"],
        default_baud   = 9600,
        description    = "Temptronic ATS-series thermal chuck controller. "
                         "Temperature range: –65°C to 250°C. "
                         "Appears as an additional TEC in the Temperature tab.",
        notes          = "Set protocol: 'temptronic' in config.",
    ),

    "cascade_thermal_chuck": DeviceDescriptor(
        uid            = "cascade_thermal_chuck",
        display_name   = "Cascade / FormFactor Thermal Chuck",
        manufacturer   = "FormFactor (Cascade Microtech)",
        device_type    = DTYPE_TEC,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.tec.thermal_chuck",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Cascade", "FormFactor", "Chuck"],
        default_baud   = 9600,
        description    = "Cascade/FormFactor thermal chuck controller. "
                         "Set protocol: 'cascade' in config.",
    ),

    "wentworth_thermal_chuck": DeviceDescriptor(
        uid            = "wentworth_thermal_chuck",
        display_name   = "Wentworth Labs Thermal Chuck",
        manufacturer   = "Wentworth Laboratories",
        device_type    = DTYPE_TEC,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.tec.thermal_chuck",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Wentworth"],
        default_baud   = 9600,
        description    = "Wentworth Labs thermal chuck controller. "
                         "Set protocol: 'wentworth' in config.",
    ),

    # ---------------------------------------------------------------- #
    #  Objective Turrets                                               #
    # ---------------------------------------------------------------- #

    "olympus_ix_turret": DeviceDescriptor(
        uid            = "olympus_ix_turret",
        display_name   = "Olympus IX Objective Turret (Arduino/LINX)",
        manufacturer   = "Olympus / custom Arduino interface",
        device_type    = DTYPE_TURRET,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.turret.olympus_linx",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["CH340", "CP210", "Turret", "LINX"],
        # Note: "Arduino" intentionally omitted — Arduino Mega 2560 boards are
        # also used as stage controllers on the NT220 (COM7/COM22) and would
        # cause false positive matches. Match only on the interface chip
        # (CH340/CP210) or custom turret firmware identifier (LINX).
        default_baud   = 115200,
        description    = "Olympus IX motorized objective turret controlled via "
                         "Arduino/LINX serial interface. "
                         "Rotating to a new objective updates FOV, pixel size, "
                         "and autofocus search range automatically.",
        notes          = "Arduino must have the LINX turret sketch loaded. "
                         "Changing objectives requires autofocus re-run.",
    ),
}


# ------------------------------------------------------------------ #
#  Lookup helpers                                                      #
# ------------------------------------------------------------------ #

def find_by_usb(vid: int, pid: int) -> Optional[DeviceDescriptor]:
    for d in DEVICE_REGISTRY.values():
        if d.usb_vid == vid and d.usb_pid == pid:
            return d
    return None


def find_by_serial_pattern(description: str,
                            hwid: str = "") -> Optional[DeviceDescriptor]:
    text = (description + " " + hwid).lower()
    for d in DEVICE_REGISTRY.values():
        for pat in d.serial_patterns:
            if pat.lower() in text:
                return d
    return None


def find_by_ni_pattern(resource_name: str) -> Optional[DeviceDescriptor]:
    for d in DEVICE_REGISTRY.values():
        for pat in d.ni_patterns:
            if pat.lower() in resource_name.lower():
                return d
    return None


def all_by_type(device_type: str) -> List[DeviceDescriptor]:
    return [d for d in DEVICE_REGISTRY.values()
            if d.device_type == device_type]
