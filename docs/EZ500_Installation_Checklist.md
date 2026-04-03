# EZ-500 Installation Checklist

**SanjINSIGHT Thermoreflectance Microscope System**
Microsanj, LLC | microsanj.com

---

## Pre-Installation Requirements

- [ ] Windows 11 (or Windows 10 build 17763+), 64-bit, fresh install complete
- [ ] Internet connection available (for Windows Update and chipset drivers)
- [ ] All EZ-500 hardware physically connected:
  - [ ] Basler camera (USB3 cable to USB 3.0 port)
  - [ ] Meerstetter TEC-1089 (USB cable — FTDI chip)
  - [ ] Meerstetter LDD-1121 (USB cable — FTDI chip)
  - [ ] Arduino Nano (USB cable — CH340 chip)
  - [ ] Thorlabs stage controller (USB cable)
  - [ ] Newport NPC3SG piezo controller (USB cable — FTDI chip)
  - [ ] NI sbRIO (built-in, Ethernet link-local 169.254.x.x)
  - [ ] Rigol DP832 power supply (USB or LAN)

---

## Step 1 — Windows Update & Chipset Drivers

**MUST be done BEFORE running the SanjINSIGHT installer.**

- [ ] Run Windows Update until no more updates available
  - Settings → Windows Update → Check for updates
  - Repeat until "You're up to date" with no pending updates
  - **Reboot** after updates complete
- [ ] Install motherboard/NUC chipset drivers (if not auto-detected)
  - Check Device Manager for any devices with yellow warning triangles
  - Download chipset drivers from the NUC/motherboard manufacturer's website
  - Intel NUC: https://www.intel.com/content/www/us/en/support.html
- [ ] Verify USB 3.0 controller appears in Device Manager
  - Device Manager → Universal Serial Bus controllers
  - Should show "USB 3.0" or "xHCI" host controller

---

## Step 2 — Run SanjINSIGHT Installer

- [ ] Run `SanjINSIGHT-Setup-{version}.exe` as Administrator
- [ ] Accept the license agreement
- [ ] Use default install location (`C:\Program Files\Microsanj\SanjINSIGHT`)
- [ ] On the Driver Selection page, verify all are checked:
  - [x] Visual C++ 2015-2022 Runtime (x64) — required by Qt5
  - [x] FTDI CDM driver — TEC-1089, LDD-1121, Newport NPC3SG, Thorlabs stage
  - [x] CH340/CH341 driver — Arduino Nano GPIO/LED selector
  - [x] Basler USB3 Vision camera driver — Basler acA1920-155um (TR camera)
  - [x] NI R Series RIO driver — sbRIO built-in FPGA (**requires internet**)
  - [ ] NI-VISA Runtime — check only if Keithley SMU / GPIB is connected (**requires internet**)
- [ ] Note: Basler pylon runtime is bundled inside pypylon (no separate install)
- [ ] Note: Rigol DP832 uses Windows built-in USB TMC driver (no install needed)
- [ ] **Reboot** after installation

---

## Step 3 — Verify Driver Installation

After reboot, open Device Manager and verify:

### USB-Serial Devices
- [ ] FTDI devices appear under "Ports (COM & LPT)" — not under "Other devices"
  - Should show: "USB Serial Port (COMx)" — one for TEC, one for LDD
- [ ] CH340 device appears under "Ports (COM & LPT)"
  - Should show: "USB-SERIAL CH340 (COMx)" — Arduino Nano
- [ ] Newport NPC3SG appears under "Ports (COM & LPT)"
  - Should show: "USB Serial Port (COMx)" — uses FTDI chip (same driver as TEC/LDD)
- [ ] Note the COM port numbers: TEC=COM___, LDD=COM___, Arduino=COM___, NPC3=COM___

### Camera
- [ ] Basler camera appears under "Basler Cameras" or "USB3 Vision Devices"
  - If it shows under "Other devices" with a yellow triangle, the USB3 drivers
    may not be installed — run Windows Update again
- [ ] Camera is on a USB 3.0 port (not USB 2.0)

### Stage (Thorlabs)
- [ ] Thorlabs controller appears under "Ports (COM & LPT)" or "USB devices"

### No Yellow Triangles
- [ ] No devices with yellow warning icons in Device Manager

---

## Step 4 — Run Verification Script

- [ ] Open Command Prompt (as Administrator)
- [ ] Navigate to the install directory:
  ```
  cd "C:\Program Files\Microsanj\SanjINSIGHT"
  ```
- [ ] Run the verification script:
  ```
  SanjINSIGHT.exe --verify-install
  ```
  Or from the tools directory:
  ```
  python tools\verify_install.py
  ```
- [ ] All required checks show [PASS]
- [ ] Note any [WARN] items — these are optional components

---

## Step 5 — Launch and Configure SanjINSIGHT

- [ ] Launch SanjINSIGHT from the desktop shortcut or Start Menu
- [ ] First-run wizard appears — follow the prompts
- [ ] Open Settings → Hardware Setup (Device Manager)
- [ ] Connect each device:
  - [ ] Camera: should auto-detect Basler camera
  - [ ] TEC: select the correct COM port
  - [ ] LDD: select the correct COM port
  - [ ] Arduino: select the correct COM port (CH340)
  - [ ] Stage: select the correct COM port
  - [ ] Newport NPC3SG: select the correct COM port
- [ ] Verify all devices show "Connected" in the status bar

---

## Step 6 — Functional Verification

- [ ] Camera: Live view shows thermal image
- [ ] TEC: Can set target temperature, readback shows actual temp
- [ ] Arduino: Can toggle LED channels (470/530/590/625 nm)
- [ ] Stage: Can home and move to known positions
- [ ] Acquire a test capture (10 frames) — completes without errors
- [ ] Save the test capture to verify file I/O

---

## Optional: NI-VISA

NI-VISA is **optionally bundled** in the installer (unchecked by default).
Check the NI-VISA checkbox during installation ONLY if the system has
Keithley SMU or GPIB instruments. USB and LAN instruments work without it.

If NI-VISA was not installed during setup:
- [ ] Download from: https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html
- [ ] Install with default options
- [ ] Reboot

> **Note:** NI-RIO (for the sbRIO / NI 9637 FPGA) is bundled in the
> installer and checked by default. It installs automatically but requires
> an internet connection (downloads ~200 MB from NI's servers).
> If installation fails due to no internet, download manually from:
> https://www.ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html

---

## Troubleshooting

### "USB Serial Port" shows yellow triangle
→ FTDI driver not installed. Re-run the SanjINSIGHT installer, or manually
  install from: https://ftdichip.com/drivers/vcp-drivers/

### "USB-SERIAL CH340" not appearing
→ CH340 driver not installed. Re-run the SanjINSIGHT installer, or manually
  install from: https://www.wch-ic.com/downloads/CH341SER_EXE.html

### Camera not detected
→ Ensure it's on a **direct USB 3.0 port** (blue connector) — NOT through a hub.
→ USB 2.0 ports and bus-powered USB hubs will not work.
→ Run Windows Update — USB3 host controller drivers may be pending.
→ Try a different USB 3.0 port on the NUC.
→ If the Basler Pylon Viewer was installed separately and SanjINSIGHT crashes,
  uninstall the full Pylon SDK (keep drivers when prompted) — pypylon bundles
  its own runtime and a version mismatch causes a silent crash.

### "Python was not found" error
→ This is a Windows App Execution Alias conflict. Go to:
  Settings → Apps → Advanced app settings → App execution aliases
  → Disable both "python.exe" and "python3.exe" aliases.
  SanjINSIGHT bundles its own Python — the system Python is not needed.

### Device Manager shows "Unknown Device"
→ Run Windows Update. Most unknown devices are resolved by chipset drivers
  delivered through Windows Update.

---

## Sign-Off

| Item | Initials | Date |
|------|----------|------|
| Installation complete | ________ | ________ |
| All devices connected | ________ | ________ |
| Test capture successful | ________ | ________ |
| Customer walkthrough done | ________ | ________ |

**Installer version**: _______________
**System serial number**: _______________
**Notes**: _______________________________________________________________
