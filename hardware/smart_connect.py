"""
hardware/smart_connect.py

Smart connection with automatic port fallback.

When a driver's configured port fails, SmartConnect scans all available
ports for the target device using protocol-level identification, then
updates the configuration with the correct port.

Usage
-----
    from hardware.smart_connect import smart_connect_tec

    # Returns (port, mecom_address) or raises RuntimeError
    port, addr = smart_connect_tec(cfg, progress_cb=log.info)
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

log = logging.getLogger(__name__)


def smart_connect_tec(
    cfg: dict,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[str, int]:
    """Find and connect to a Meerstetter TEC, with automatic port fallback.

    Tries the configured port first.  If that fails (or no port is configured),
    scans all FTDI serial ports for a device responding at the TEC's MeCom
    address.

    Parameters
    ----------
    cfg : dict
        TEC configuration dict (from config.yaml ``hardware.tec_meerstetter``).
        Keys used: ``port``, ``address``, ``baudrate``.
    progress_cb : callable | None
        Called with human-readable status messages.

    Returns
    -------
    (port, mecom_address) : tuple[str, int]
        The port and address where the TEC was found.
        The ``cfg`` dict is updated in-place with the working port.

    Raises
    ------
    RuntimeError
        If the TEC cannot be found on any port.
    """
    configured_port = cfg.get("port", "")
    address = cfg.get("address", 2)
    baudrate = int(cfg.get("baudrate", 57600))

    def _msg(text: str):
        if progress_cb:
            progress_cb(text)
        log.info("SmartConnect: %s", text)

    # ── Fast path: try configured port first ─────────────────────────────
    if configured_port:
        _msg(f"Trying configured port {configured_port}…")
        if _try_mecom_identify(configured_port, address, baudrate):
            _msg(f"TEC found on configured port {configured_port}")
            return configured_port, address

        _msg(f"TEC not responding on {configured_port} — scanning all ports…")

    # ── Fallback: scan all FTDI ports ────────────────────────────────────
    from hardware.protocol_prober import find_device_port

    device_uid = _address_to_uid(address)
    found_port = find_device_port(
        device_uid=device_uid,
        baudrate=baudrate,
        progress_cb=lambda s: _msg(s),
    )

    if found_port:
        _msg(f"TEC found on {found_port} (was configured as "
             f"{configured_port or '<empty>'})")

        # Update config in-place so the driver gets the right port
        cfg["port"] = found_port

        # Persist the port change to config file
        _persist_port_change(device_uid, found_port)

        return found_port, address

    # ── Also try other addresses (device might have been re-addressed) ───
    other_addresses = [a for a in (2, 1, 0) if a != address]
    for try_addr in other_addresses:
        try_uid = _address_to_uid(try_addr)
        if not try_uid:
            continue
        found = find_device_port(
            device_uid=try_uid,
            baudrate=baudrate,
            progress_cb=lambda s: _msg(s),
        )
        if found:
            _msg(f"Found MeCom device at address {try_addr} on {found} "
                 f"(expected address {address})")
            cfg["port"] = found
            cfg["address"] = try_addr
            _persist_port_change(device_uid, found)
            return found, try_addr

    # ── Nothing found ────────────────────────────────────────────────────
    raise RuntimeError(
        "Meerstetter TEC not found on any serial port.\n\n"
        "Troubleshooting:\n"
        "  1. Is the TEC-1089 powered on? (check front-panel LED)\n"
        "     The TEC needs its own DC power supply — USB alone is not sufficient.\n"
        "  2. Is the USB cable connected? Check Device Manager → Ports (COM & LPT)\n"
        "     for an FTDI USB Serial Port.\n"
        "  3. Is the FTDI driver installed? The SanjINSIGHT installer includes it,\n"
        "     but you can also download from ftdichip.com.\n"
        "  4. If using a USB hub, try connecting directly to the computer.\n"
        "  5. Try unplugging and re-plugging the USB cable."
    )


def smart_connect_ldd(
    cfg: dict,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[str, int]:
    """Find and connect to a Meerstetter LDD, with automatic port fallback.

    Same logic as smart_connect_tec but targets MeCom address 1 (LDD default).
    """
    # LDD default address is 1
    if "address" not in cfg:
        cfg["address"] = 1

    configured_port = cfg.get("port", "")
    address = cfg.get("address", 1)
    baudrate = int(cfg.get("baudrate", 57600))

    def _msg(text: str):
        if progress_cb:
            progress_cb(text)
        log.info("SmartConnect: %s", text)

    if configured_port:
        _msg(f"Trying configured port {configured_port}…")
        if _try_mecom_identify(configured_port, address, baudrate):
            _msg(f"LDD found on configured port {configured_port}")
            return configured_port, address
        _msg(f"LDD not responding on {configured_port} — scanning all ports…")

    from hardware.protocol_prober import find_device_port

    found_port = find_device_port(
        device_uid="meerstetter_ldd1121",
        baudrate=baudrate,
        progress_cb=lambda s: _msg(s),
    )

    if found_port:
        _msg(f"LDD found on {found_port}")
        cfg["port"] = found_port
        _persist_port_change("meerstetter_ldd1121", found_port)
        return found_port, address

    raise RuntimeError(
        "Meerstetter LDD not found on any serial port.\n\n"
        "Troubleshooting:\n"
        "  1. Is the LDD-1121 powered on?\n"
        "  2. Is the USB cable connected?\n"
        "  3. Check Device Manager → Ports for an FTDI USB Serial Port.\n"
        "  4. If TEC and LDD share an RS-485 bus, ensure the TEC is also powered."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_mecom_identify(port: str, address: int, baudrate: int) -> bool:
    """Quick check: does a MeCom device respond at this port+address?"""
    from hardware.protocol_prober import probe_mecom_port
    results = probe_mecom_port(
        port, baudrate=baudrate, timeout=1.5,
        addresses=[address], skip_locked=True,
    )
    return any(r.is_identified for r in results)


def _address_to_uid(address: int) -> str:
    """Map MeCom address to device UID."""
    from hardware.protocol_prober import _MECOM_ADDRESS_MAP
    return _MECOM_ADDRESS_MAP.get(address, "")


def _persist_port_change(device_uid: str, new_port: str):
    """Save the discovered port to config so it persists across restarts."""
    try:
        import config
        # Map device UIDs to their config key paths
        _config_keys = {
            "meerstetter_tec_1089": "hardware.tec_meerstetter.port",
            "meerstetter_tec_1123": "hardware.tec_meerstetter.port",
            "meerstetter_ldd1121": "hardware.ldd_meerstetter.port",
        }
        key = _config_keys.get(device_uid)
        if key:
            config.set_pref(key, new_port)
            log.info("SmartConnect: saved port %s for %s to config (%s)",
                     new_port, device_uid, key)
    except Exception:
        log.debug("SmartConnect: failed to persist port change for %s",
                  device_uid, exc_info=True)
