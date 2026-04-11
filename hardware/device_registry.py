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
DTYPE_GPIO    = "gpio"     # Arduino Nano GPIO / LED wavelength selector
DTYPE_UNKNOWN = "unknown"

CONN_SERIAL   = "serial"
CONN_USB      = "usb"
CONN_ETHERNET = "ethernet"
CONN_PCIE     = "pcie"
CONN_CAMERA   = "camera"   # cameras enumerated via SDK (pypylon, NI IMAQdx)


# ------------------------------------------------------------------ #
#  Hardware categories                                                 #
# ------------------------------------------------------------------ #
#  Six user-facing categories shared by the sidebar Hardware panel
#  and the Device Manager.  Each maps one or more device types.
#  Categorized by what the hardware does for the user, not board type.

CAT_CAMERAS         = "cameras"
CAT_STAGES          = "stages"
CAT_THERMAL_CONTROL = "thermal_control"
CAT_STIMULUS        = "stimulus_timing"
CAT_PROBES          = "probes"
CAT_SENSORS         = "sensors"

# Backward compat aliases — old code may reference the previous names.
CAT_ILLUMINATION    = CAT_STIMULUS
CAT_STIMULUS_TIMING = CAT_STIMULUS  # canonical alias (same value)

CATEGORY_ORDER = [
    CAT_CAMERAS,
    CAT_STAGES,
    CAT_THERMAL_CONTROL,
    CAT_STIMULUS,
    CAT_PROBES,
    CAT_SENSORS,
]

CATEGORY_LABELS = {
    CAT_CAMERAS:         "Cameras",
    CAT_STAGES:          "Stages",
    CAT_THERMAL_CONTROL: "Thermal Control",
    CAT_STIMULUS:        "Stimulus & Timing",
    CAT_PROBES:          "Probes",
    CAT_SENSORS:         "Sensors",
}

# Map every device type to its parent category.
# Internal sub-labels distinguish roles within Stimulus & Timing:
#   FPGA      → Timing / FPGA
#   Bias      → Bias Source
#   LDD       → Optical Source / Illumination
#   GPIO      → GPIO / LED Selector
DTYPE_TO_CATEGORY = {
    DTYPE_CAMERA:  CAT_CAMERAS,
    DTYPE_STAGE:   CAT_STAGES,
    DTYPE_TEC:     CAT_THERMAL_CONTROL,  # active temperature control
    DTYPE_FPGA:    CAT_STIMULUS,         # timing / modulation controller
    DTYPE_GPIO:    CAT_STIMULUS,         # Arduino LED / laser selector
    DTYPE_LDD:     CAT_STIMULUS,         # laser diode driver (optical source)
    DTYPE_BIAS:    CAT_STIMULUS,         # bias source (electrical excitation)
    DTYPE_PROBER:  CAT_PROBES,
    DTYPE_TURRET:  CAT_PROBES,           # objective turret on probe station
    DTYPE_UNKNOWN: CAT_SENSORS,          # default bucket for unrecognised devices
}


def category_for(device_type: str) -> str:
    """Return the hardware category for a given DTYPE_* constant."""
    return DTYPE_TO_CATEGORY.get(device_type, CAT_SENSORS)


def all_by_category(category: str) -> "List[DeviceDescriptor]":
    """Return all registered devices belonging to *category*."""
    return [d for d in DEVICE_REGISTRY.values()
            if DTYPE_TO_CATEGORY.get(d.device_type) == category]


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

    # Protocol-level identification (for resolving ambiguous VID/PID matches)
    protocol_prober: Optional[str] = None   # prober key: "mecom", None = passive only
    mecom_address:   Optional[int] = None   # expected MeCom address (2=TEC, 1=LDD)

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

    # ── FLIR Boson (direct — bundled Boson SDK) ──────────────────────────────

    "flir_boson_320": DeviceDescriptor(
        uid            = "flir_boson_320",
        display_name   = "FLIR Boson 320",
        manufacturer   = "FLIR Systems",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,  # UVC + serial; no address required for video-only
        camera_type    = "ir",
        driver_module  = "hardware.cameras.boson_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x09CB,    # FLIR Boson USB VID
        usb_pid        = 0x4007,    # Boson 320 PID
        serial_patterns= ["Boson", "FLIR Boson", "09CB:4007"],
        description    = "FLIR Boson 320×256 uncooled LWIR microbolometer. "
                         "Controlled via bundled FLIR Python SDK over serial (FSLP), "
                         "video via UVC (USB Video Class). 14-bit radiometric output.",
        datasheet_url  = "https://www.flir.com/products/boson/",
        notes          = "Set serial_port (e.g. /dev/cu.usbmodemXXX on macOS, "
                         "COM3 on Windows) and video_index in config.yaml. "
                         "Driver: boson",
    ),

    "flir_boson_640": DeviceDescriptor(
        uid            = "flir_boson_640",
        display_name   = "FLIR Boson 640",
        manufacturer   = "FLIR Systems",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,  # UVC + serial; no address required for video-only
        camera_type    = "ir",
        driver_module  = "hardware.cameras.boson_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x09CB,
        usb_pid        = 0x4009,    # Boson 640 PID
        serial_patterns= ["Boson 640", "FLIR Boson 640", "09CB:4009"],
        description    = "FLIR Boson 640×512 uncooled LWIR microbolometer. "
                         "Higher resolution variant of the Boson 320. "
                         "14-bit radiometric output at up to 60 fps.",
        datasheet_url  = "https://www.flir.com/products/boson/",
        notes          = "Set serial_port and video_index in config.yaml. "
                         "Driver: boson",
    ),

    # ── FLIR Boson+ (enhanced sensitivity, <6 ms latency) ───────────────────

    # Boson+ entries have NO usb_vid/usb_pid — they share PIDs with the
    # original Boson and cannot be distinguished by USB enumeration alone.
    # The scanner will match the physical device to flir_boson_320 or _640;
    # the driver reports the actual model (Boson vs Boson+) after connecting
    # via the camera part number.  These entries exist so users with a known
    # Boson+ can manually select it in Device Manager if desired.

    "flir_boson_plus_320": DeviceDescriptor(
        uid            = "flir_boson_plus_320",
        display_name   = "FLIR Boson+ 320",
        manufacturer   = "Teledyne FLIR",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        camera_type    = "ir",
        driver_module  = "hardware.cameras.boson_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Boson+", "Boson Plus", "22320", "23320"],
        description    = "FLIR Boson+ 320×256 uncooled LWIR microbolometer. "
                         "Enhanced sensitivity (≤20 mK NEdT Industrial, ≤30 mK Professional), "
                         "<6 ms video latency. 14-bit radiometric, 60 fps. "
                         "Pin-compatible upgrade from Boson 320.",
        datasheet_url  = "https://oem.flir.com/products/boson-plus/",
        notes          = "Same driver as Boson 320. Differentiated by part number "
                         "prefix (22xxx shutter / 23xxx shutterless). "
                         "Adds MIPI interface option (not used over USB). "
                         "Driver: boson",
    ),

    "flir_boson_plus_640": DeviceDescriptor(
        uid            = "flir_boson_plus_640",
        display_name   = "FLIR Boson+ 640",
        manufacturer   = "Teledyne FLIR",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,
        camera_type    = "ir",
        driver_module  = "hardware.cameras.boson_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        serial_patterns= ["Boson+ 640", "Boson Plus 640", "22640", "23640"],
        description    = "FLIR Boson+ 640×512 uncooled LWIR microbolometer. "
                         "Enhanced sensitivity (≤20 mK NEdT Industrial, ≤30 mK Professional), "
                         "<6 ms video latency. 14-bit radiometric, 60 fps. "
                         "Pin-compatible upgrade from Boson 640.",
        datasheet_url  = "https://oem.flir.com/products/boson-plus/",
        notes          = "Same driver as Boson 640. Differentiated by part number "
                         "prefix (22xxx shutter / 23xxx shutterless). "
                         "Adds MIPI interface option (not used over USB). "
                         "Driver: boson",
    ),

    # ── Basler SWIR (ICD-registered, NI IMAQdx / pypylon) ────────────────────

    "basler_a2a1280_125um_swir": DeviceDescriptor(
        uid            = "basler_a2a1280_125um_swir",
        display_name   = "Basler a2A1280-125umSWIR",
        manufacturer   = "Basler AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_CAMERA,  # pypylon USB3 Vision enumeration
        camera_type    = "tr",
        driver_module  = "hardware.cameras.pypylon_driver",
        driver_version = "builtin",
        hot_loadable   = False,
        usb_vid        = 0x2676,
        usb_pid        = 0xBA02,
        serial_patterns= ["Basler", "a2A1280", "0000267601CA9A1F"],
        description    = "Basler a2A1280-125umSWIR USB3 Vision short-wave infrared "
                         "camera, 1280×1024 @ 125 fps. "
                         "ICD file: assets/camera_icd/Basler a2A1280-125umSWIR.icd.",
        datasheet_url  = "https://www.baslerweb.com/",
    ),

    # ── Allied Vision Goldeye (ICD-registered, NI IMAQdx) ────────────────────

    "allied_vision_goldeye_g032": DeviceDescriptor(
        uid            = "allied_vision_goldeye_g032",
        display_name   = "Allied Vision Goldeye G-032 Cool",
        manufacturer   = "Allied Vision Technologies",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_ETHERNET,
        camera_type    = "ir",
        driver_module  = "hardware.cameras.ni_imaqdx",
        driver_version = "builtin",
        hot_loadable   = False,
        tcp_port       = 3956,      # GigE Vision control port
        tcp_banner     = "Allied Vision",
        serial_patterns= ["Allied Vision", "Goldeye", "0000000F31F4"],
        description    = "Allied Vision Goldeye G-032 Cool InGaAs SWIR camera. "
                         "GigE Vision, 636×508, cooled InGaAs sensor. "
                         "ICD file: assets/camera_icd/Allied Vision Goldeye.icd.",
        datasheet_url  = "https://www.alliedvision.com/en/products/cameras/detail/Goldeye/G-032.html",
        notes          = "NI IMAQdx required (Windows). interface_name: cam3 or DUV.",
    ),

    # ── Photonfocus MV4 (ICD-registered, NI IMAQdx) ──────────────────────────

    "photonfocus_mv4_d1280u": DeviceDescriptor(
        uid            = "photonfocus_mv4_d1280u",
        display_name   = "Photonfocus MV4-D1280U-H01-GT",
        manufacturer   = "Photonfocus AG",
        device_type    = DTYPE_CAMERA,
        connection_type= CONN_ETHERNET,
        camera_type    = "tr",
        driver_module  = "hardware.cameras.ni_imaqdx",
        driver_version = "builtin",
        hot_loadable   = False,
        tcp_port       = 3956,      # GigE Vision
        tcp_banner     = "Photonfocus",
        serial_patterns= ["Photonfocus", "MV4", "000070F8E7B0"],
        description    = "Photonfocus MV4-D1280U-H01-GT GigE Vision camera. "
                         "1280×1024, high-dynamic-range CMOS. "
                         "ICD file: assets/camera_icd/Photonfocus MV4-D1280U.icd.",
        datasheet_url  = "https://www.photonfocus.com/",
        notes          = "NI IMAQdx required (Windows). interface_name: DUV.",
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
        protocol_prober= "mecom",
        mecom_address  = 2,        # factory default for TEC-1089
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
        protocol_prober= "mecom",
        mecom_address  = 2,        # factory default for TEC-1123
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
        default_baud   = 9600,
        description    = "RS-232 TEC controller with Modbus RTU protocol (N-8-2). "
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
        ni_patterns    = ["9637"],
        description    = "NI CompactRIO FPGA module. Generates lock-in reference "
                         "signal for hot/cold modulation and frame synchronisation.",
        datasheet_url  = "https://www.ni.com/en/shop/model/ni-9637.html",
        notes          = "Requires NI-RIO drivers and compiled FPGA bitfile.",
    ),

    "ni_sbrio": DeviceDescriptor(
        uid            = "ni_sbrio",
        display_name   = "NI sbRIO FPGA",
        manufacturer   = "National Instruments",
        device_type    = DTYPE_FPGA,
        connection_type= CONN_ETHERNET,
        driver_module  = "hardware.fpga.ni9637",
        driver_version = "builtin",
        hot_loadable   = False,
        ni_patterns    = ["RIO", "sbRIO", "cRIO"],
        default_ip     = "169.254.252.165",
        description    = (
            "NI Single-Board RIO embedded controller with user-programmable "
            "FPGA. Built into the Microsanj EZ-500 chassis. Generates the "
            "lock-in reference signal for hot/cold modulation and camera "
            "frame synchronisation. Connects via Ethernet (link-local "
            "169.254.x.x) using the nifpga library."),
        datasheet_url  = "https://www.ni.com/en/shop/compactrio/single-board-rio.html",
        notes          = (
            "Requires NI-RIO drivers and compiled LabVIEW FPGA bitfile (.lvbitx). "
            "Resource string format: rio://169.254.x.x/RIO0 — find the correct "
            "IP in NI MAX → Remote Systems. The sbRIO uses a link-local Ethernet "
            "address; ensure the host NIC is configured for DHCP or has a "
            "169.254.x.x address on the same subnet."),
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

    "bnc_745": DeviceDescriptor(
        uid            = "bnc_745",
        display_name   = "BNC Model 745 Digital Delay Generator",
        manufacturer   = "Berkeley Nucleonics Corporation",
        device_type    = DTYPE_FPGA,
        connection_type= CONN_USB,
        driver_module  = "hardware.fpga.bnc745",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0A33,   # BNC USB vendor ID
        usb_pid        = 0x0021,   # BNC 745 OEM
        serial_patterns= ["BNC", "745", "Berkeley Nucleonics", "MOD745"],
        default_timeout= 5.0,
        description    = (
            "BNC Model 745 multi-channel digital delay/pulse generator. "
            "Used in PT-100B transient test setups as the precision timing "
            "source for camera and bias synchronisation. Replaces the NI-9637 "
            "FPGA in setups without CompactRIO hardware.  "
            "Communicates via GPIB, USB, or Serial using PyVISA. "
            "Supports continuous lock-in mode and single-shot transient mode."),
        datasheet_url  = "https://www.berkeleynucleonics.com/model-745",
        notes          = (
            "Requires pyvisa + VISA backend (NI-VISA recommended on Windows). "
            "LabVIEW heritage: MOD745.lvlib driver (BNC_745_OEM). "
            "Channel 1 = camera trigger, Channel 2 = auxiliary gate. "
            "Single-shot transient mode: set_trigger_mode(SINGLE_SHOT) + arm_trigger()."),
    ),

    "tdg7": DeviceDescriptor(
        uid            = "tdg7",
        display_name   = "TDG-VII Picosecond Delay Generator",
        manufacturer   = "Fastlaser Tech",
        device_type    = DTYPE_FPGA,
        connection_type= CONN_USB,
        driver_module  = "hardware.fpga.tdg7",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0483,   # STM32 VCP vendor ID
        usb_pid        = 0x5740,   # STM32 VCP product ID
        serial_patterns= ["STM32", "STMicroelectronics", "TDG", "PT-100",
                          "Fastlaser"],
        default_timeout= 2.0,
        description    = (
            "Fastlaser Tech TDG-VII 7-channel picosecond delay/pulse generator "
            "(also sold as the Microsanj PT-100 timing module). "
            "Replaces the NI sbRIO FPGA as the precision timing source. "
            "Channels 1–4: 0–999,999.99 ns (0.01 ns resolution). "
            "Channels 5–7: 0–9,999,999.9 ns (0.1 ns resolution). "
            "Communicates via USB-serial (STM32 Virtual COM Port)."),
        notes          = (
            "Requires pyserial. USB VID:PID = 0483:5740 (STM32 VCP). "
            "On Windows install the STM32 Virtual COM Port driver if "
            "the device is not auto-detected. "
            "Commands are sent twice for firmware reliability. "
            "Channel 1 = camera trigger, Channel 2 = bias gate."),
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

    "newport_npc3": DeviceDescriptor(
        uid            = "newport_npc3",
        display_name   = "Newport NPC3SG Piezo Controller",
        manufacturer   = "Newport / MKS Instruments",
        device_type    = DTYPE_STAGE,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.stage.newport_npc3",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0403,   # FTDI USB-to-serial chip
        serial_patterns= ["Newport", "NPC3", "NPC3SG", "Piezo Stack"],
        default_baud   = 19200,
        default_timeout= 1.0,
        description    = "3-channel closed-loop piezo stack amplifier controller. "
                         "Drives NPA-series actuators for nanometer-precision positioning.",
        datasheet_url  = "https://www.newport.com/p/NPC3SG",
        notes          = "Uses FTDI virtual COM port. XON/XOFF flow control. "
                         "Closed-loop requires SG model with strain-gauge feedback.",
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

    "amcad_bilt": DeviceDescriptor(
        uid            = "amcad_bilt",
        display_name   = "AMCAD BILT Pulsed I-V System",
        manufacturer   = "AMCAD Engineering",
        device_type    = DTYPE_BIAS,
        connection_type= CONN_ETHERNET,
        driver_module  = "hardware.bias.amcad_bilt",
        driver_version = "builtin",
        hot_loadable   = False,
        tcp_port       = 5035,          # pivserver64.exe default port
        tcp_banner     = "PIV",         # AMCAD pivserver banner
        default_ip     = "127.0.0.1",
        default_timeout= 5.0,
        description    = (
            "AMCAD BILT pulsed I-V system — two-channel (Gate + Drain) "
            "pulsed voltage/current source for transistor characterisation. "
            "Communicates via TCP/SCPI to pivserver64.exe running on the "
            "instrument PC.  Typical use: pulsed thermoreflectance measurements "
            "with µs-scale gate and drain pulses.  "
            "Default port: 5035 (set via pivserver64.exe -p <port>)."),
        datasheet_url  = "https://www.amcad-engineering.com/products/bilt/",
        notes          = (
            "Requires pivserver64.exe (Windows) running on instrument PC. "
            "Default pulse parameters loaded from PIV1.txt via amcad_bilt.py. "
            "Gate ch1: bias=-5 V, pulse=-2.2 V, width=110 µs, delay=5 µs. "
            "Drain ch2: bias=0 V, pulse=+1 V, width=100 µs, delay=10 µs."),
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
        protocol_prober= "mecom",
        mecom_address  = 1,        # factory default for LDD-1121
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

    # ---------------------------------------------------------------- #
    #  Arduino GPIO / LED Controllers                                  #
    # ---------------------------------------------------------------- #

    "arduino_nano_ch340": DeviceDescriptor(
        uid            = "arduino_nano_ch340",
        display_name   = "Arduino Nano (CH340)",
        manufacturer   = "Generic / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x1A86,   # QinHeng Electronics (CH340)
        usb_pid        = 0x7523,   # CH340 USB-serial
        serial_patterns= ["CH340", "ch340", "Arduino Nano"],
        default_baud   = 115200,
        description    = "Arduino Nano (ATmega328P) with CH340 USB-serial chip. "
                         "Used as LED wavelength selector and general-purpose I/O "
                         "controller for Microsanj thermoreflectance systems.",
        notes          = "Flash firmware/arduino_nano/sanjinsight_io.ino via Arduino IDE. "
                         "Pins D2–D5: LED channel select. D6–D13: general GPIO. "
                         "A0–A7: analog inputs (10-bit ADC).",
    ),

    "arduino_nano_ftdi": DeviceDescriptor(
        uid            = "arduino_nano_ftdi",
        display_name   = "Arduino Nano (FTDI)",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x0403,   # FTDI
        usb_pid        = 0x6001,   # FT232R
        serial_patterns= ["Arduino Nano", "FT232"],
        default_baud   = 115200,
        description    = "Arduino Nano (ATmega328P) with FTDI FT232R USB-serial. "
                         "Original Arduino Nano revision; same firmware as CH340 variant.",
    ),

    # ---------------------------------------------------------------- #
    #  Arduino UNO                                                      #
    # ---------------------------------------------------------------- #

    "arduino_uno": DeviceDescriptor(
        uid            = "arduino_uno",
        display_name   = "Arduino UNO",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x2341,   # Arduino SA
        usb_pid        = 0x0043,   # UNO R3 (ATmega16U2 bridge)
        serial_patterns= ["Arduino Uno", "Arduino UNO", "ttyACM"],
        default_baud   = 115200,
        description    = "Arduino UNO (ATmega328P) with ATmega16U2 USB-serial bridge. "
                         "Same firmware and serial protocol as the Nano variant. "
                         "Pin mapping: D2–D5 LED select, D6–D13 GPIO, A0–A5 ADC.",
        notes          = "Flash firmware/arduino_nano/sanjinsight_io.ino via Arduino IDE. "
                         "The UNO resets on serial open (2 s bootloader wait). "
                         "A0–A5 only (no A6/A7 — those are analog-only on Nano but "
                         "absent on UNO headers).",
    ),

    "arduino_uno_r4": DeviceDescriptor(
        uid            = "arduino_uno_r4",
        display_name   = "Arduino UNO R4",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x2341,   # Arduino SA
        usb_pid        = 0x0069,   # UNO R4 Minima
        serial_patterns= ["Arduino UNO R4", "UNO R4", "Renesas"],
        default_baud   = 115200,
        description    = "Arduino UNO R4 Minima/WiFi (Renesas RA4M1). "
                         "Native USB — no external USB-serial chip. "
                         "Same serial protocol as the Nano firmware.",
        notes          = "The R4 has a 14-bit ADC (0–16383) but firmware should "
                         "scale output to 10-bit for protocol compatibility. "
                         "No bootloader reset delay on native USB variants.",
    ),

    "arduino_uno_q": DeviceDescriptor(
        uid            = "arduino_uno_q",
        display_name   = "Arduino UNO Q",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x2341,   # Arduino SA
        usb_pid        = 0x0078,   # UNO Q (Qualcomm QRB2210 + STM32U585)
        serial_patterns= ["Arduino UNO Q", "UNO Q", "UNO-Q"],
        default_baud   = 115200,
        description    = "Arduino UNO Q (Qualcomm QRB2210 + STM32U585 MCU). "
                         "Dual-brain SBC: Linux on QRB2210, Arduino sketches "
                         "on STM32U585 Cortex-M33. USB-CDC serial to STM32. "
                         "Same serial protocol as the Nano firmware.",
        notes          = "SanjINSIGHT communicates with the STM32U585 MCU "
                         "side via USB-CDC serial (same ASCII protocol). "
                         "The Qualcomm Linux side is not used. "
                         "EDL mode uses VID 05C6:PID 9008 — do not match.",
    ),

    "arduino_uno_r4_wifi": DeviceDescriptor(
        uid            = "arduino_uno_r4_wifi",
        display_name   = "Arduino UNO R4 WiFi",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.nano_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x2341,   # Arduino SA
        usb_pid        = 0x1002,   # UNO R4 WiFi
        serial_patterns= ["Arduino UNO R4 WiFi", "UNO R4 WiFi"],
        default_baud   = 115200,
        description    = "Arduino UNO R4 WiFi (Renesas RA4M1 + ESP32-S3). "
                         "Native USB — no external USB-serial chip. "
                         "Same serial protocol as the Nano firmware.",
        notes          = "The R4 WiFi has a 14-bit ADC but firmware should "
                         "scale output to 10-bit for protocol compatibility. "
                         "WiFi/BLE module is not used by SanjINSIGHT.",
    ),

    "arduino_nano_esp32": DeviceDescriptor(
        uid            = "arduino_nano_esp32",
        display_name   = "Arduino Nano ESP32",
        manufacturer   = "Arduino / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.esp32_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x2341,   # Arduino SA
        usb_pid        = 0x0070,   # Nano ESP32 (u-blox NORA-W106)
        serial_patterns= ["Arduino Nano ESP32", "Nano ESP32", "NORA-W106"],
        default_baud   = 115200,
        description    = "Arduino Nano ESP32 (u-blox NORA-W106 / ESP32-S3). "
                         "Native USB-CDC. Same serial protocol and pin "
                         "mapping as the ESP32 firmware variant.",
        notes          = "Flash firmware/esp32/sanjinsight_io.ino via Arduino IDE. "
                         "No bootloader reset delay on native USB. "
                         "WiFi/BT disabled at boot by firmware.",
    ),

    # ---------------------------------------------------------------- #
    #  ESP32 GPIO / LED Controllers                                     #
    # ---------------------------------------------------------------- #

    "esp32_cp2102": DeviceDescriptor(
        uid            = "esp32_cp2102",
        display_name   = "ESP32 (CP2102)",
        manufacturer   = "Espressif / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.esp32_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x10C4,   # Silicon Labs
        usb_pid        = 0xEA60,   # CP210x USB-UART
        serial_patterns= ["CP210", "cp210", "ESP32", "esp32"],
        default_baud   = 115200,
        description    = "ESP32 dev board with Silicon Labs CP2102/CP2104 USB-UART bridge. "
                         "Common on ESP32-DevKitC, NodeMCU-32S, and most third-party boards. "
                         "Same serial protocol as the Arduino Nano firmware.",
        notes          = "Flash firmware/esp32/sanjinsight_io.ino via Arduino IDE or "
                         "PlatformIO. GPIO16–19: LED select. GPIO21–33: general GPIO. "
                         "ADC1 channels (GPIO32–39): 12-bit analog input.",
    ),

    "esp32_native_usb": DeviceDescriptor(
        uid            = "esp32_native_usb",
        display_name   = "ESP32-S3/C3 (Native USB)",
        manufacturer   = "Espressif / Microsanj",
        device_type    = DTYPE_GPIO,
        connection_type= CONN_SERIAL,
        driver_module  = "hardware.arduino.esp32_driver",
        driver_version = "builtin",
        hot_loadable   = True,
        usb_vid        = 0x303A,   # Espressif Inc.
        usb_pid        = 0x1001,   # ESP32-S2/S3/C3 native USB-CDC
        serial_patterns= ["Espressif", "ESP32-S", "ESP32-C"],
        default_baud   = 115200,
        description    = "ESP32-S2, ESP32-S3, or ESP32-C3 with built-in USB (no external "
                         "USB-serial chip). Driver-free on all platforms. "
                         "Same serial protocol as the Arduino Nano firmware.",
        notes          = "No bootloader reset delay — USB-CDC is always ready. "
                         "Flash via Arduino IDE (ESP32 board package) or PlatformIO.",
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


def find_all_by_usb(vid: int, pid: int) -> list:
    """Return ALL device descriptors matching a VID:PID pair.

    Common USB-serial chips (FTDI 0403:6001, Prolific 067B:2303) are
    shared by multiple device types.  Returning all matches lets the
    scanner create a discovered-device entry for each, so the user can
    pick the correct one in Device Manager.
    """
    return [d for d in DEVICE_REGISTRY.values()
            if d.usb_vid == vid and d.usb_pid == pid]


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


def register_external(descriptor: DeviceDescriptor) -> None:
    """Register a plugin-provided device descriptor into the global registry.

    Raises :class:`ValueError` if the UID is already in use.
    """
    if descriptor.uid in DEVICE_REGISTRY:
        raise ValueError(
            f"Device UID '{descriptor.uid}' already registered "
            f"(existing: {DEVICE_REGISTRY[descriptor.uid].display_name})")
    DEVICE_REGISTRY[descriptor.uid] = descriptor
