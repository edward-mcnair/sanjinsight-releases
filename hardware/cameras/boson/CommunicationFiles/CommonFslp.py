# -*- coding: utf-8 -*-
"""
Common FSLP — common interface to select the correct FSLP transport.

Modified for SanjINSIGHT:
  - sys.path.append(None) guard added (C2: prevented TypeError on Python 3.11+)
  - print() calls replaced with logging (m1: frozen-app stdout crash prevention)
"""

import sys
import os
import logging
from os.path import dirname
from enum import IntEnum

log = logging.getLogger(__name__)


class FSLP_TYPE_E(IntEnum):
    FSLP_DLL_SERIAL = 0
    FSLP_PY_SERIAL  = 1
    FSLP_I2C        = 2


class CommonFslp(object):
    @staticmethod
    def getFslp(portName, baudrate=None, fslpType=FSLP_TYPE_E.FSLP_DLL_SERIAL, extPath=None):
        fslp = None

        # Guard: only append extPath to sys.path when it is an actual path string.
        # The original SDK code unconditionally appended extPath even when None,
        # which inserted None into sys.path and caused TypeError on Python 3.11+.
        if extPath is not None and extPath not in sys.path:
            sys.path.append(extPath)

        if FSLP_TYPE_E.FSLP_DLL_SERIAL == fslpType:
            from .CSerialFslp import CSerialFslp
            if extPath is None:
                extPath = os.path.join(dirname(dirname(__file__)), "FSLP_Files")
            fslp = CSerialFslp(portName, baudrate, extPath)
            log.debug("Boson SDK: C serial FSLP loaded")

        elif FSLP_TYPE_E.FSLP_PY_SERIAL == fslpType:
            from .PySerialFslp import PySerialFslp
            fslp = PySerialFslp(portName, baudrate)
            log.debug("Boson SDK: Python serial FSLP loaded")

        elif FSLP_TYPE_E.FSLP_I2C == fslpType:
            from .I2CFslp import I2CFslp
            fslp = I2CFslp(portName, baudrate)
            log.debug("Boson SDK: I2C FSLP loaded")

        else:
            raise ValueError(f"Unknown FSLP type: {fslpType}")

        return fslp
