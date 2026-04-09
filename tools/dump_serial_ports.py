#!/usr/bin/env python3
"""
tools/dump_serial_ports.py

Diagnostic utility — prints the full USB fingerprint for every serial port.

Run with all devices connected:
    python tools/dump_serial_ports.py

Then run with each device unplugged one at a time to identify which
fingerprint belongs to which physical device.

The output is used to build the USB-serial-number-based device identity
map so SanjINSIGHT can reliably distinguish devices that share the same
FTDI VID:PID (0x0403:0x6001), such as Arduino Nano and Meerstetter TEC.
"""

from serial.tools import list_ports


def dump_ports():
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    if not ports:
        print("No serial ports found.")
        return

    print(f"Found {len(ports)} serial port(s):\n")

    for p in ports:
        print("=" * 72)
        print(f"  device        : {p.device}")
        print(f"  description   : {getattr(p, 'description', None)}")
        print(f"  hwid          : {getattr(p, 'hwid', None)}")
        print(f"  vid           : {f'0x{p.vid:04X}' if p.vid is not None else None}")
        print(f"  pid           : {f'0x{p.pid:04X}' if p.pid is not None else None}")
        print(f"  serial_number : {getattr(p, 'serial_number', None)}")
        print(f"  location      : {getattr(p, 'location', None)}")
        print(f"  manufacturer  : {getattr(p, 'manufacturer', None)}")
        print(f"  product       : {getattr(p, 'product', None)}")
        print(f"  interface     : {getattr(p, 'interface', None)}")
    print("=" * 72)


if __name__ == "__main__":
    dump_ports()
