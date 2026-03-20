# -*- coding: utf-8 -*-
"""
Serial port supported by Python serial library.

Modified for SanjINSIGHT:
  - serial.Serial.isOpen() (removed in pyserial 3.5) replaced with .is_open (m3)
  - print() calls replaced with logging (m1: frozen-app stdout crash prevention)
  - PortBase.setPortBaudrate() missing-self bug noted but method is unused here
"""

import logging

import serial
try:
    import serial.tools.list_ports as portList
    HAS_SERIAL_LIST = True
except ImportError:
    HAS_SERIAL_LIST = False

from .PortBase import PortBase

log = logging.getLogger(__name__)


class PySerialPort(PortBase):
    def __init__(self, portID, baudrate=None, port=None):
        if baudrate is None:
            baudrate = 921600
        super().__init__(str(portID), int(baudrate))
        self.port = port if port else serial.Serial()

    def open(self):
        self.port.port     = self.portID
        self.port.baudrate = self.baudrate
        self.port.parity   = 'N'
        self.port.stopbits = 1
        self.port.bytesize = 8
        self.port.timeout  = 10
        self.port.open()
        if self.port.is_open:
            log.debug("Boson SDK: serial port %s open", self.portID)
        else:
            raise IOError(f"Failed to open serial port {self.portID!r}")

    def close(self):
        if self.port.is_open:
            self.port.close()
        log.debug("Boson SDK: serial port %s closed", self.portID)

    def isOpen(self):
        return self.port.is_open

    def isAvailable(self):
        if HAS_SERIAL_LIST:
            return self.portID in [p[0] for p in portList.comports()]
        return None

    def write(self, data):
        self.port.write(data)

    def read(self, numberOfBytes):
        return self.port.read(numberOfBytes)
