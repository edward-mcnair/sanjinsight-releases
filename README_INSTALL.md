# SanjINSIGHT — Installation Guide (Windows)

**Version:** 1.4.1-beta.2
**Applies to:** Windows 10 / Windows 11 (64-bit)
**Support:** software-support@microsanj.com

---

## System Requirements

### Operating System

| Version | Support |
|---|---|
| **Windows 11 64-bit** | Fully supported — recommended |
| **Windows 10 64-bit, build 17763+** (October 2018 Update, version 1809) | Supported |
| Windows 10 builds below 17763 | Not supported |
| Windows 32-bit | Not supported |
| macOS / Linux | Simulation / development mode only |

To check your Windows build: press **Win+R**, type `winver`, press Enter.

### Hardware

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 4-core, 2.5 GHz | 8-core, 3.5 GHz or better |
| RAM | 8 GB | 32 GB (16 GB minimum if using AI Assistant) |
| Disk | 4 GB free | NVMe SSD with 50 GB free |
| USB | USB 3.0 × 2 | USB 3.0 × 4 or more |
| Network | 100 Mbps Ethernet | Gigabit Ethernet |
| GPU | Not required | NVIDIA RTX series, 8 GB VRAM+ (for fast AI inference) |
| Display | 1920×1080 | 2560×1440, dual monitors |

### NUC / Mini-PC

An Intel NUC or equivalent mini-PC can run SanjINSIGHT for bench evaluation and network-attached setups. Limitations:
- PCIe-connected NI hardware (NI 9637 via PCIe) is **not** supported — NUCs have no full-height PCIe slots
- NI 9637 connected via Ethernet/network and Basler USB3 cameras work normally
- AI Assistant runs on CPU only at reduced speed (~10–30 tokens/second)

For production instrument use with a locally connected NI chassis, a standard desktop tower or workstation is required.

---

## Quick Start (recommended)

The SanjINSIGHT installer bundles Python and all required Python packages — no separate Python installation is needed. A small number of items cannot be bundled and must be set up manually as described below.

### 1 — Run the installer

Double-click `SanjINSIGHT-Setup-{version}.exe` and follow the prompts (administrator rights required).

### 2 — Install NI hardware drivers

Most drivers are bundled with the SanjINSIGHT installer (including the FTDI VCP driver for USB-serial devices and camera SDKs). The only drivers that must be installed separately are National Instruments (NI) kernel-level drivers. Install these **before** launching SanjINSIGHT:

| Driver | Required for | Download |
|---|---|---|
| **NI-RIO** | FPGA — NI 9637 | [ni.com → NI-RIO](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html) |
| **NI Vision Acquisition Software** | Camera — NI IMAQdx | [ni.com → NI-VAS](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html) |
| **NI-VISA** | Bias source — Keithley via GPIB | [ni.com → NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |

NI-RIO and NI Vision Acquisition Software both require a restart; NI-VISA does not. You can install all three and then restart once. After all three are installed, open **NI MAX** (Measurement & Automation Explorer) and confirm that your camera and FPGA chassis appear under **Devices and Interfaces** / **Remote Systems**.

> **USB-to-serial adapters** (Meerstetter TEC, LDD, ATEC, stage, turret): The FTDI VCP driver is bundled with the SanjINSIGHT installer and installs silently during setup. USB-serial devices should appear as COM ports in Windows Device Manager immediately after installation. If a COM port still does not appear, download the latest FTDI VCP driver from [ftdichip.com/drivers/vcp-drivers](https://ftdichip.com/drivers/vcp-drivers/).

### 3 — Copy the FPGA bitfile

Copy the FPGA firmware file from the Microsanj USB key to a permanent location on this PC:

```
C:\Microsanj\firmware\ez500firmware.lvbitx
```

Create the folder if it does not exist. The Hardware Setup Wizard will ask for this path on first launch.

### 4 — Launch and complete the Hardware Setup Wizard

Launch **SanjINSIGHT** from the Start menu or desktop shortcut. The **Hardware Setup Wizard** opens automatically on the first run and guides you through selecting COM ports, the camera driver, the FPGA resource string, and the bitfile path.

### 5 — Download the AI model (optional)

The AI Assistant requires a local language model (~2–5 GB). Go to **Settings → AI Assistant** and click **Download Model**. The application runs normally without it — only the AI panel is unavailable until the model is downloaded.

### Quick checklist

```
□ Run SanjINSIGHT-Setup.exe (FTDI driver installs automatically)
□ Install NI-RIO                               ← do NOT restart yet
□ Install NI Vision Acquisition Software       ← do NOT restart yet
□ Install NI-VISA                              ← no restart needed
□ Restart PC once (satisfies NI-RIO + NI-VAS restart requirements)
□ Copy FPGA bitfile → C:\Microsanj\firmware\ez500firmware.lvbitx
□ Open NI MAX — confirm camera and FPGA appear
□ Launch SanjINSIGHT → complete Hardware Setup Wizard
□ Settings → AI Assistant → Download Model  (optional)
```

> **To update:** when a new version is released, a notification badge appears in the application header. Click it to download and run the new installer. Your settings, profiles, and measurement data are preserved.

---

## Manual Installation (Python source)

Use this method if you are a developer or if the installer is not yet available for your version.

### Step 1 — Install Python

Download and install **Python 3.10 or later** (64-bit) from [python.org](https://www.python.org/downloads/).

During installation, check **"Add Python to PATH"**.

Verify in a Command Prompt:
```
python --version
```
Expected output: `Python 3.10.x` or higher.

---

### Step 2 — Install Python packages

Open a Command Prompt in the SanjINSIGHT folder and run:

```
pip install -r requirements.txt
```

This installs the GUI framework, NumPy, OpenCV, matplotlib, HDF5, and YAML support.

---

### Step 3 — Install NI drivers (required for real hardware)

#### NI-RIO (for the FPGA — NI 9637)
1. Download **NI-RIO** from [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html).
2. Run the installer and restart when prompted.
3. Open **NI MAX** (Measurement & Automation Explorer) and verify your CompactRIO target appears under **Remote Systems**.
4. Note the resource string shown (e.g. `rio://169.254.x.x/RIO0`) — you will need it in the setup wizard.

#### NI Vision Acquisition Software (for the camera via NI IMAQdx)
1. Download from [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html).
2. Install and restart.
3. Open **NI MAX** and verify the camera appears under **Devices and Interfaces**.
4. Note the camera name (e.g. `cam4`) — you will need it in the setup wizard.

> **Basler pypylon camera driver:**
> If your site uses the Basler pypylon driver instead of NI IMAQdx:
> Run: `pip install pypylon`
> No separate Basler SDK install is needed — pypylon bundles the pylon runtime in its wheel.

---

### Step 4 — Install hardware-specific Python packages

Install only the packages for hardware you have:

| Hardware | Command |
|---|---|
| NI FPGA (NI 9637) | `pip install nifpga` |
| Basler camera (pypylon) | `pip install pypylon` |
| Meerstetter TEC-1089 | `pip install git+https://github.com/meerstetter/pyMeCom` |
| Keithley bias source | `pip install pyvisa pyvisa-py` |

---

### Step 5 — Copy the FPGA bitfile

Copy the compiled FPGA bitfile (`*.lvbitx`) to a permanent location on this PC, for example:

```
C:\Microsanj\firmware\ez500firmware.lvbitx
```

You will enter this path in the Hardware Setup Wizard.

---

### Step 6 — Launch SanjINSIGHT

```
cd path\to\sanjinsight
python main_app.py
```

The **Hardware Setup Wizard** will appear on first launch and guide you through configuring COM ports, camera driver, and FPGA bitfile path.

---

## Upgrading

### From the application (recommended)
When a new version is available, an **amber notification badge** will appear in the top-right of the header bar. Click it to see release notes and download the new installer.

### Manual upgrade
1. Download the new release from [github.com/microsanj/sanjinsight/releases](https://github.com/microsanj/sanjinsight/releases).
2. Run the installer. It will detect the existing installation and upgrade in place.
3. Your `config.yaml`, measurement sessions, and preferences are preserved.

> **Note:** if the upgrade includes a new FPGA bitfile (listed in the release notes), deploy the new `.lvbitx` to your instrument PC and update the path in `config.yaml` or via **Hardware Setup** in Settings.

---

## Uninstalling

If installed via the `.exe` installer: use **Windows Settings → Apps** and find **SanjINSIGHT**.

If installed from source: simply delete the folder. Your measurement sessions are in `~/microsanj_sessions` and preferences in `~/.microsanj/` — delete those folders too if you want a full clean uninstall.

---

## Troubleshooting

### "Camera driver 'ni_imaqdx' is Windows-only" warning
This is normal when running on macOS or a development PC. The app runs with simulated hardware. On the instrument PC the NI camera driver will be used automatically.

### "FPGA bitfile not found" error
The path in `config.yaml` (or set during the setup wizard) does not point to a real file. Open **Settings → Hardware Setup** and browse for the `.lvbitx` file.

### "nifpga not installed" error
Run `pip install nifpga` and ensure NI-RIO drivers are installed.

### App starts but no live image appears
Check:
1. Camera is powered and connected via USB or GigE.
2. Camera name in NI MAX matches `hardware.camera.camera_name` in `config.yaml`.
3. No other application (e.g. NI MAX, Pylon Viewer) has the camera open.

### Contacting support
Use **Help → Get Support…** in the application to open a pre-filled support email with your system info and recent log included automatically. Alternatively, go to **Help → About** and click **"Copy Info to Clipboard"**, then paste into an email to software-support@microsanj.com.

---

## File locations

| Item | Location |
|---|---|
| Application | `C:\Program Files\Microsanj\SanjINSIGHT\` (installer) or your source folder |
| Configuration | `config.yaml` in the application folder |
| Measurement sessions | `%USERPROFILE%\microsanj_sessions\` |
| User preferences | `%USERPROFILE%\.microsanj\preferences.json` |
| Log file | `logs\microsanj.log` in the application folder |
