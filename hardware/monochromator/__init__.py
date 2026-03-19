"""
hardware/monochromator

Newport / Oriel Cornerstone monochromator driver package.

Drivers
-------
simulated   — software-only stand-in for development and testing
cornerstone — real Newport Cornerstone via serial (ASCII command protocol)

Usage
-----
    from hardware.monochromator.factory import build_monochromator
    driver = build_monochromator(cfg)   # cfg from config.yaml → hardware.monochromator
    if driver:
        driver.connect()
        driver.set_wavelength(532.0)
        driver.set_shutter(True)
        status = driver.get_status()
        driver.disconnect()
"""
