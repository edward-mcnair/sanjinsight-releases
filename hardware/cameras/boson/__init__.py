# hardware/cameras/boson/__init__.py
#
# FLIR Boson 3.0 Python SDK — embedded package.
#
# Source: FLIR SDK_USER_PERMISSIONS v3.0 (2021-02-03).
# Embedded for self-contained distribution; no separate FLIR SDK install needed.
#
# SanjINSIGHT imports directly from the sub-packages:
#   hardware.cameras.boson.ClientFiles_Python.Client_API   — pyClient
#   hardware.cameras.boson.CommunicationFiles.CommonFslp   — CommonFslp
#   hardware.cameras.boson.CommunicationFiles.PySerialFslp — PySerialFslp
#
# The original SDK __init__.py used `from .ClientFiles_Python import __dict__`
# which is not valid Python and raised ImportError on all modern CPython versions.
# That namespace-injection pattern is not needed for the SanjINSIGHT integration
# and is intentionally omitted.
