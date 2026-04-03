"""
hardware/error_narration.py — Human-readable device error narration.

Converts a :class:`DeviceError` (from ``error_taxonomy.py``) into a single
natural-language paragraph that tells the user **what happened**, **why** it
likely happened, and **what to do next** — in plain English.

Pure Python — no Qt dependency — so CLI tools can use it too.

Usage
-----
    from hardware.error_narration import narrate, short_narrate

    paragraph = narrate(dev_err)       # "The TEC-1089 has lost its serial …"
    one_liner = short_narrate(dev_err) # "TEC-1089 disconnected — check USB cable"
"""

from __future__ import annotations

import re
from typing import Optional

# Avoid circular import — error_taxonomy types used only for annotation
from hardware.error_taxonomy import DeviceError, ErrorCategory

# ── Friendly device names ───────────────────────────────────────────────────
# Single source of truth; replaces the duplicated _DEVICE_DISPLAY dicts in
# main_app.py.  Keyed by the device_uid values that flow through the system.

DEVICE_FRIENDLY_NAMES: dict[str, str] = {
    # TEC controllers
    "tec0":               "TEC-1089 temperature controller",
    "tec1":               "ATEC-302 temperature controller",
    "tec2":               "TEC controller 3",
    "tec_meerstetter":    "TEC-1089 temperature controller",
    "meerstetter_tec_1089": "TEC-1089 temperature controller",

    # LDD
    "ldd":                "LDD-1121 laser diode driver",
    "ldd_meerstetter":    "LDD-1121 laser diode driver",
    "meerstetter_ldd_1121": "LDD-1121 laser diode driver",

    # Cameras
    "camera":             "camera",
    "tr_camera":          "TR camera",
    "ir_camera":          "IR thermal camera",
    "basler_ace2":        "Basler camera",

    # FPGA / Stimulus
    "fpga":               "FPGA stimulus generator",
    "ni_9637":            "NI 9637 FPGA",
    "ni_sbrio":           "NI sbRIO FPGA",

    # Bias source
    "bias":               "bias power supply",
    "rigol_dp832":        "Rigol DP832 power supply",
    "keithley_smu":       "Keithley SMU",

    # Stage / motion
    "stage":              "XYZ stage",
    "thorlabs_bsc203":    "Thorlabs BSC203 stage",
    "newport_npc3":       "Newport NPC3SG piezo stage",

    # Arduino
    "gpio":               "Arduino GPIO controller",
    "arduino":            "Arduino Nano",

    # Prober
    "prober":             "wafer prober",
}

# Short display names for status bar and banner titles (no "controller" suffix)
DEVICE_SHORT_NAMES: dict[str, str] = {
    "tec0": "TEC-1089",    "tec1": "ATEC-302",    "tec2": "TEC 3",
    "camera": "Camera",    "tr_camera": "TR Camera",  "ir_camera": "IR Camera",
    "fpga": "FPGA / sbRIO", "bias": "Bias Source", "stage": "Stage",
    "prober": "Prober",    "ldd": "LDD-1121",     "gpio": "Arduino",
}


def _device_name(uid: str) -> str:
    """Look up a friendly full name for a device UID."""
    if uid in DEVICE_FRIENDLY_NAMES:
        return DEVICE_FRIENDLY_NAMES[uid]
    # Fallback: humanise the UID
    return uid.replace("_", " ").replace("-", " ").title() or "device"


def _device_short(uid: str) -> str:
    """Look up a short display name for a device UID."""
    if uid in DEVICE_SHORT_NAMES:
        return DEVICE_SHORT_NAMES[uid]
    return _device_name(uid).split()[0] if uid else "Device"


# ── Narration templates ─────────────────────────────────────────────────────
# Each ErrorCategory maps to a template that produces a flowing paragraph.
# Placeholders:
#   {device}   — friendly device name ("TEC-1089 temperature controller")
#   {Device}   — capitalised device name
#   {reason}   — the classified message from DeviceError.message
#   {fix}      — the suggested fix from DeviceError.suggested_fix
#   {raw}      — first 80 chars of the raw exception (for technical users)

_TEMPLATES: dict[ErrorCategory, str] = {
    ErrorCategory.DEVICE_DISCONNECTED: (
        "The {device} is no longer responding. This usually means the USB "
        "cable was unplugged, the device lost power, or the serial port "
        "was reassigned. {fix_sentence}"
    ),
    ErrorCategory.TIMEOUT: (
        "The {device} did not respond within the expected time. This can "
        "happen if the device is initialising, the baud rate is incorrect, "
        "or the connection has degraded. {fix_sentence}"
    ),
    ErrorCategory.PERMISSION_DENIED: (
        "The operating system denied access to the {device}. {fix_sentence}"
    ),
    ErrorCategory.DEVICE_BUSY: (
        "The {device} appears to be in use by another application. Only one "
        "program can communicate with a serial device at a time. {fix_sentence}"
    ),
    ErrorCategory.MISSING_DRIVER: (
        "A required software component for the {device} is not installed on "
        "this computer. The application cannot communicate with the hardware "
        "until the driver is installed. {fix_sentence}"
    ),
    ErrorCategory.WRONG_DRIVER_VERSION: (
        "The installed driver for the {device} is not the expected version. "
        "This can cause communication failures or missing features. "
        "{fix_sentence}"
    ),
    ErrorCategory.BANDWIDTH_LIMIT: (
        "The {device} reports insufficient USB bandwidth. This typically "
        "occurs when too many high-speed devices share the same USB "
        "controller. {fix_sentence}"
    ),
    ErrorCategory.NETWORK_CONFIG: (
        "A network error occurred while communicating with the {device}. "
        "Verify that the device is on the same network, the IP address is "
        "correct, and LAN control is enabled on the instrument. {fix_sentence}"
    ),
    ErrorCategory.FIRMWARE_MISMATCH: (
        "The {device} reported a firmware or protocol version that does not "
        "match what this software expects. {fix_sentence}"
    ),
    ErrorCategory.UNKNOWN: (
        "An unexpected error occurred with the {device}: {reason}. "
        "{fix_sentence}"
    ),
}


def _fix_to_sentence(fix: str) -> str:
    """Convert bullet-point suggested_fix into a flowing sentence.

    Input like:
        "Check USB cable and device power.\nTry a different USB port."
    Becomes:
        "To resolve this, check USB cable and device power, and try a different USB port."
    """
    if not fix:
        return "Check the device connection and try again."
    # Split on newlines, strip bullets/numbers/whitespace
    lines = [
        re.sub(r"^\s*[-•*\d.)\]]+\s*", "", line).strip()
        for line in fix.splitlines()
        if line.strip()
    ]
    lines = [l for l in lines if l]
    if not lines:
        return "Check the device connection and try again."

    if len(lines) == 1:
        s = lines[0]
        # Lowercase the first letter if it starts with uppercase
        if s and s[0].isupper() and not s.startswith(("USB", "NI", "COM", "IP", "LAN")):
            s = s[0].lower() + s[1:]
        return f"To resolve this, {s}"

    # Join multiple lines with commas
    parts = []
    for l in lines:
        if l and l[0].isupper() and not l.startswith(("USB", "NI", "COM", "IP", "LAN")):
            l = l[0].lower() + l[1:]
        parts.append(l)
    joined = ", ".join(parts[:-1]) + ", and " + parts[-1]
    return f"To resolve this, {joined}"


# ── Public API ──────────────────────────────────────────────────────────────

def narrate(dev_err: DeviceError) -> str:
    """Convert a DeviceError into a single natural-language paragraph.

    Returns a human-readable string suitable for toasts, health panel
    error rows, and the startup dialog.
    """
    device = _device_name(dev_err.device_uid)
    reason = dev_err.message or str(dev_err.raw_exception)[:100]
    fix_sentence = _fix_to_sentence(dev_err.suggested_fix)

    template = _TEMPLATES.get(dev_err.category, _TEMPLATES[ErrorCategory.UNKNOWN])
    try:
        return template.format(
            device=device,
            Device=device.capitalize() if device else "Device",
            reason=reason,
            fix_sentence=fix_sentence,
            raw=dev_err.raw_exception[:80],
        )
    except (KeyError, IndexError):
        return f"Error with {device}: {reason}. {fix_sentence}"


def short_narrate(dev_err: DeviceError) -> str:
    """One-line summary (≤120 chars) for status bars and banner titles.

    Format: "TEC-1089 disconnected — check USB cable"
    """
    name = _device_short(dev_err.device_uid)

    _SHORT_VERBS: dict[ErrorCategory, str] = {
        ErrorCategory.DEVICE_DISCONNECTED: "disconnected",
        ErrorCategory.TIMEOUT:             "not responding",
        ErrorCategory.PERMISSION_DENIED:   "access denied",
        ErrorCategory.DEVICE_BUSY:         "in use by another app",
        ErrorCategory.MISSING_DRIVER:      "driver not installed",
        ErrorCategory.WRONG_DRIVER_VERSION: "driver version mismatch",
        ErrorCategory.BANDWIDTH_LIMIT:     "USB bandwidth exceeded",
        ErrorCategory.NETWORK_CONFIG:      "network error",
        ErrorCategory.FIRMWARE_MISMATCH:   "firmware mismatch",
        ErrorCategory.UNKNOWN:             "error",
    }
    verb = _SHORT_VERBS.get(dev_err.category, "error")

    # Extract a short actionable hint from suggested_fix
    hint = ""
    if dev_err.suggested_fix:
        first_line = dev_err.suggested_fix.split("\n")[0].strip()
        # Remove leading bullets
        first_line = re.sub(r"^\s*[-•*\d.)\]]+\s*", "", first_line)
        if len(first_line) > 60:
            first_line = first_line[:57] + "…"
        hint = f" — {first_line}"

    result = f"{name} {verb}{hint}"
    return result[:160]
