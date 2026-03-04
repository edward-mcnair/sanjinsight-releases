# SanjINSIGHT — Installation Guide (Windows)

**Version:** 1.0.0  
**Applies to:** Windows 10 / Windows 11 (64-bit)  
**Support:** support@microsanj.com

---

## Quick Start (recommended)

The SanjINSIGHT installer bundles Python and all required Python packages — no separate Python installation is needed. A small number of items cannot be bundled and must be set up manually as described below.

### 1 — Run the installer

Double-click `SanjINSIGHT-Setup-{version}.exe` and follow the prompts (administrator rights required).

### 2 — Install NI hardware drivers

These are Windows kernel-level drivers that cannot be embedded in the application installer. Install them **before** launching SanjINSIGHT:

| Driver | Required for | Download |
|---|---|---|
| **NI-RIO** | FPGA — NI 9637 | [ni.com → NI-RIO](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html) |
| **NI Vision Acquisition Software** | Camera — NI IMAQdx | [ni.com → NI-VAS](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html) |
| **NI-VISA** | Bias source — Keithley via GPIB | [ni.com → NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |

Each installer requires a restart. After all three are installed, open **NI MAX** (Measurement & Automation Explorer) and confirm that your camera and FPGA chassis appear under **Devices and Interfaces** / **Remote Systems**.

> **USB-to-serial adapters** (Meerstetter TEC, ATEC, stage, turret): Windows 11 usually detects FTDI and Prolific adapters automatically. If a COM port does not appear in Device Manager after plugging in the cable, download and install the FTDI VCP driver from [ftdichip.com/drivers/vcp-drivers](https://ftdichip.com/drivers/vcp-drivers/).

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
□ Run SanjINSIGHT-Setup.exe
□ Install NI-RIO + restart
□ Install NI Vision Acquisition Software + restart
□ Install NI-VISA
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

> **Alternative camera driver (Basler pypylon):**  
> If your site uses the Basler pypylon driver instead of NI IMAQdx:
> 1. Download and install the **Basler Pylon SDK** from [baslerweb.com](https://www.baslerweb.com/en/downloads/software-downloads/).
> 2. Run: `pip install pypylon`

---

### Step 4 — Install hardware-specific Python packages

Install only the packages for hardware you have:

| Hardware | Command |
|---|---|
| NI FPGA (NI 9637) | `pip install nifpga` |
| Basler camera (pypylon) | `pip install pypylon` |
| Meerstetter TEC-1089 | `pip install pyMeCom` |
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
Go to **Help → About** in the application and click **"Copy Info to Clipboard"**, then paste into your support email to support@microsanj.com. This gives us your exact version, OS, and driver configuration.

---

## File locations

| Item | Location |
|---|---|
| Application | `C:\Program Files\Microsanj\SanjINSIGHT\` (installer) or your source folder |
| Configuration | `config.yaml` in the application folder |
| Measurement sessions | `%USERPROFILE%\microsanj_sessions\` |
| User preferences | `%USERPROFILE%\.microsanj\preferences.json` |
| Log file | `logs\microsanj.log` in the application folder |
