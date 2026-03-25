# SanjINSIGHT User Manual

**Microsanj SanjINSIGHT v1.5.0-beta.1**
**Document revision: 2026-03-25**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation](#2-installation)
3. [Hardware Setup Wizard](#3-hardware-setup-wizard)
4. [Application Overview](#4-application-overview)
5. [Device Status & Emergency Stop](#5-device-status--emergency-stop)
6. [AutoScan](#6-autoscan)
7. [Live View](#7-live-view)
8. [Capture — Single Acquisition](#8-capture--single-acquisition)
9. [Capture — Grid Scan](#9-capture--grid-scan)
10. [Transient Capture](#10-transient-capture)
11. [Calibration](#11-calibration)
12. [Analysis Panel](#12-analysis-panel)
13. [Sessions Panel](#13-sessions-panel)
14. [Hardware Panels](#14-hardware-panels)
15. [AI Assistant](#15-ai-assistant)
16. [Compare Sessions](#16-compare-sessions)
17. [3D Surface](#17-3d-surface)
18. [Saving and Exporting Data](#18-saving-and-exporting-data)
19. [Device Manager](#19-device-manager)
20. [Settings](#20-settings)
21. [User Accounts & Roles](#21-user-accounts--roles)
22. [Operator Mode](#22-operator-mode)
23. [Supported Hardware](#23-supported-hardware)
24. [Configuration File Reference](#24-configuration-file-reference)
25. [Keyboard Shortcuts](#25-keyboard-shortcuts)
26. [Troubleshooting](#26-troubleshooting)
27. [Technical Reference](#27-technical-reference)

---

## 1. Introduction

### 1.1 What is SanjINSIGHT?

SanjINSIGHT is the instrument control and data-acquisition software for the **Microsanj EZ-Therm** and **Nano-THERM** thermoreflectance imaging systems. It provides a complete workflow for:

- **Real-time thermoreflectance streaming** — continuous live ΔR/R display with EMA smoothing
- **Single-shot acquisition** — averaged hot/cold frame capture with instant ΔR/R computation
- **Large-area grid scanning** — automated stage-driven multi-tile mapping stitched into a single composite image
- **Thermoreflectance calibration** — TEC-stepped measurement of the C_T coefficient map, enabling conversion of ΔR/R into temperature change (ΔT)
- **AI-assisted diagnostics** — a local language model monitors all instrument parameters in real time, grades readiness (A–D), and answers instrument questions in plain language

### 1.2 Underlying Physics

Thermoreflectance imaging exploits the fact that a material's optical reflectance changes slightly with temperature. The relationship is approximately linear over small temperature ranges:

```
ΔR/R = C_T × ΔT
```

| Symbol | Meaning | Typical units |
|---|---|---|
| ΔR/R | Fractional change in reflectance (the measured signal) | dimensionless (×10⁻⁴ to ×10⁻³) |
| C_T | Thermoreflectance coefficient (material and wavelength specific) | K⁻¹ |
| ΔT | Temperature change | °C or K |

The application measures ΔR/R by alternating the device under test (DUT) between two bias states ("cold" and "hot") synchronised with the camera via an FPGA lock-in reference signal. C_T is determined by the Calibration workflow (Section 11). Once C_T is known, ΔT = ΔR/R ÷ C_T.

**Thermoreflectance coefficient reference values (C_T [K⁻¹]):**

| Material | Optimal LED | C_T |
|---|---|---|
| Silicon | 470 nm Blue | 1.5 × 10⁻⁴ |
| GaAs | 470 nm Blue | 2.0 × 10⁻⁴ |
| GaN | 365 / 470 / 530 nm | 1.8 × 10⁻⁴ |
| InP | 470 nm Blue | 2.5 × 10⁻⁴ |
| Gold (pulsed) | 470 / 530 nm | 1.6–2.5 × 10⁻⁴ |
| Aluminum | **780 nm NIR only** | 0.8 × 10⁻⁴ |
| Nickel | 585 / 660 nm | 0.9–1.0 × 10⁻⁴ |
| Titanium | 585 / 660 nm | 0.7–0.8 × 10⁻⁴ |

> **Aluminum note:** C_T at 532 nm and 470 nm is negligibly small for aluminum. Always use the 780 nm NIR LED when measuring aluminum surfaces. Changing LED wavelength requires recalibration.

> **Flip-chip / thru-substrate:** Silicon is transparent at wavelengths ≥ 1100 nm. Use 1050–1500 nm NIR illumination (InGaAs sensor) for backside or flip-chip thermal imaging.

### 1.3 Modes of Operation

| Mode | Access | Best for |
|---|---|---|
| **AutoScan** | ACQUIRE → AutoScan in sidebar | Guided one-screen workflow; new users and automated QA |
| **Manual** | Individual panels in ACQUIRE, ANALYZE, Hardware | Full independent control of all acquisition and analysis parameters |

AutoScan and Manual mode are not exclusive — users freely switch between them by navigating the sidebar. AutoScan is simply a single-panel guided workflow that drives the same underlying acquisition engine as the manual panels.

---

## 2. Installation

### 2.1 System Requirements

#### Operating System

| Version | Support |
|---|---|
| **Windows 11 64-bit** | Fully supported — recommended |
| **Windows 10 64-bit, build 17763+** (October 2018 Update, version 1809) | Supported |
| Windows 10 64-bit, builds before 17763 | Not supported |
| Windows 32-bit (any version) | Not supported |
| macOS / Linux | Development and simulation mode only — NI drivers not available |

> **Minimum Windows 10 build:** 17763. To check your build, press **Win+R**, type `winver`, press Enter. If the build number shown is below 17763, update Windows before installing SanjINSIGHT.

#### Hardware

| Component | Minimum | Recommended | Notes |
|---|---|---|---|
| CPU | 4-core, 2.5 GHz | 8-core, 3.5 GHz or better | More cores improve AI inference speed on CPU |
| RAM | 8 GB | 32 GB | 16 GB minimum if using the AI Assistant; 32 GB for smooth simultaneous acquisition + AI |
| Disk | 4 GB free | NVMe SSD with 50 GB free | SSD strongly recommended; AI model alone is 2–5 GB; large scan sessions can exceed 10 GB |
| USB | USB 3.0 × 2 | USB 3.0 × 4 or more | One port per USB camera + additional ports for serial adapters (TEC, stage, turret) |
| Network | 100 Mbps Ethernet | Gigabit Ethernet | Required if the FPGA chassis or camera connects over a network rather than USB |
| GPU | Not required | NVIDIA RTX 4070 (12 GB VRAM) minimum; RTX 4090 or RTX A6000 for large models | A dedicated NVIDIA GPU dramatically accelerates the AI Assistant (see note below) |
| Display | 1920×1080 | 2560×1440, dual monitors | Dual monitors allow the live thermal map and analysis panels to be visible simultaneously |

> **GPU and AI inference:** Without a dedicated GPU, the AI Assistant runs on the CPU at approximately 15–50 tokens/second (model dependent). An NVIDIA GPU with CUDA support raises this to 200–500+ tokens/second and enables larger, more capable models (7B–13B parameter range). The application runs fully without a GPU — only AI response speed is affected. The RTX 4070 (12 GB VRAM) is the practical minimum for running larger models at useful speeds; the RTX 4090 or RTX A6000 are recommended for 70B-class models. GPU detection is automatic — no additional configuration is required.

#### Will it run on an Intel NUC or mini-PC?

Yes, with limitations:

| Capability | NUC / Mini-PC |
|---|---|
| SanjINSIGHT application | ✓ Fully supported |
| Basler USB3 camera | ✓ Works via USB 3.0 |
| NI 9637 FPGA via Ethernet/network | ✓ Works |
| NI 9637 FPGA via PCIe | ✗ NUCs have no full-height PCIe slots |
| Meerstetter / ATEC TEC (via USB-serial adapter) | ✓ Works |
| Stage and turret (USB-serial) | ✓ Works |
| AI Assistant (CPU inference, small model) | ✓ Works; expect 10–30 tok/s |
| AI Assistant (GPU-accelerated, large model) | ✗ No dedicated GPU slot |

A NUC is suitable for bench evaluation, software demonstrations, and systems where the FPGA connects over the network. For production instrument control with a locally connected NI chassis, a standard desktop tower or workstation is required.

### 2.2 What the Installer Includes

The SanjINSIGHT `.exe` installer is a self-contained bundle built with PyInstaller. It includes:

- Python runtime
- All required Python packages (PyQt5, NumPy, OpenCV, Matplotlib, SciPy, HDF5, and all hardware driver libraries)
- The complete SanjINSIGHT application and assets

**No separate Python installation is required.**

### 2.3 Installing SanjINSIGHT

#### Step 1 — Run the installer

1. Download `SanjINSIGHT-Setup-{version}.exe` from the [Releases page](https://github.com/edward-mcnair/sanjinsight/releases).
2. Double-click the installer and follow the prompts (administrator rights required).
3. The installer places shortcuts on the Desktop and in the Start Menu.

#### Step 2 — Install NI hardware drivers

The installer cannot bundle Windows kernel-level hardware drivers. Install these **before** launching SanjINSIGHT for the first time.

> **Restart tip:** NI-RIO and NI Vision Acquisition Software both require a restart. You can install all three NI packages first and then restart once — you do not need to restart between each NI install. NI-VISA does not require a restart.

| Driver | Required for | Restart | Download |
|---|---|---|---|
| **NI-RIO** | FPGA — NI 9637 | Yes | [ni.com → NI-RIO](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html) |
| **NI Vision Acquisition Software** | Camera — NI IMAQdx | Yes | [ni.com → NI-VAS](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html) |
| **NI-VISA** | Bias source — Keithley (GPIB / USB / LAN) | No | [ni.com → NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |
| **Basler camera** | Basler TR / SWIR camera | No | **No SDK required** — pypylon bundles the pylon runtime in its wheel. Install SanjINSIGHT and connect the camera. |
| **FLIR Boson** | FLIR Boson 320 / 640 IR camera | No | **No SDK required** — the Boson 3.0 Python SDK is bundled in the installer. After install, configure `serial_port` and `video_index` in Device Manager. |

After installing the NI drivers, open **NI MAX** (Measurement & Automation Explorer) and verify:
- The camera appears under **Devices and Interfaces** with the correct name (e.g. `cam4`).
- The FPGA chassis appears under **Remote Systems** with its resource string (e.g. `rio://169.254.x.x/RIO0`).

> **USB-to-serial adapters** (Meerstetter TEC, LDD, ATEC, stage, turret): The FTDI VCP driver is bundled with the SanjINSIGHT installer and installs silently during setup. The TEC-1089, LDD-1121, and other FTDI-based devices should appear as COM ports in Windows Device Manager immediately after installation. If a COM port still does not appear, download the latest FTDI VCP driver from [ftdichip.com/drivers/vcp-drivers](https://ftdichip.com/drivers/vcp-drivers/).

#### Step 3 — Copy the FPGA bitfile

The compiled FPGA firmware (`.lvbitx`) is supplied on the Microsanj USB key. Copy it to a permanent location:

```
C:\Microsanj\firmware\ez500firmware.lvbitx
```

Create the folder if it does not exist. The Hardware Setup Wizard will prompt for this path.

#### Step 4 — Launch, complete the Hardware Setup Wizard, and activate your license

Launch **SanjINSIGHT** from the Start Menu or Desktop shortcut. The first launch proceeds through three automatic steps:

1. **Admin Setup** — create the administrator account (one-time only).
2. **Hardware Setup Wizard** — configure TEC, camera, FPGA, bias source, stage, and optionally the AI model (see Section 3 for full details).
3. **License Activation prompt** — after the wizard closes, a dialog appears asking you to activate your license key or continue in demo mode:
   - **Activate License** — paste the key supplied by Microsanj and click **Activate License**. The key is validated immediately; the application unlocks full hardware access on success.
   - **Continue in Demo Mode** — dismiss the prompt and run with simulated hardware. You can activate a license at any time via **Help → License…** or **Settings → License**.

> The license prompt appears only once. If you skip it, the application runs in demo mode until a key is entered manually.

#### Step 5 — Download the AI model (optional)

The AI Assistant requires a local language model file (~2–5 GB, downloaded once). Go to **Settings → AI Assistant** and click **Download Model**. A progress bar is shown in Settings. All non-AI features work immediately without the model.

#### Complete installation checklist

```
□ Run SanjINSIGHT-Setup.exe
□ Install NI-RIO                               ← do NOT restart yet
□ Install NI Vision Acquisition Software       ← do NOT restart yet
□ Install NI-VISA                              ← no restart needed
□ Restart PC once (satisfies NI-RIO + NI-VAS restart requirements)
□ (Basler camera: no SDK install needed — pypylon is self-contained)
□ (FLIR Boson: no SDK install needed — SDK is bundled)
□   → After install: configure serial_port + video_index in Device Manager
□ Confirm camera + FPGA visible in NI MAX
□ Copy FPGA bitfile → C:\Microsanj\firmware\ez500firmware.lvbitx
□ Launch SanjINSIGHT → complete Admin Setup    (first launch only)
□ Complete Hardware Setup Wizard
□ Activate license key (or choose Continue in Demo Mode)
□ Settings → AI Assistant → Download Model     (optional, ~2–5 GB)
```

### 2.4 Updates

SanjINSIGHT checks for updates on startup. When a newer release is available, a badge appears in the top bar. Click the badge or go to **Help → Check for Updates…** to download and install the latest version.

---

## 3. Hardware Setup Wizard

The Hardware Setup Wizard runs automatically the first time SanjINSIGHT is launched. You can also open it at any time from **Help → Hardware Setup…** (Ctrl+Shift+H).

### 3.1 Auto-Detection

When the wizard opens it immediately starts a background device scan that checks:

- USB ports (VID/PID matching)
- Serial ports (description and hardware-ID matching)
- Network/Ethernet devices
- NI instrument resources (NI MAX)
- Camera SDKs (Pylon TlFactory, NI IMAQdx)

Detected devices are shown with a **green ✓** badge and have their fields pre-filled. Missing devices show an **amber ⚠** badge.

### 3.2 Admin Setup Wizard (first launch only)

On the very first launch, before the Hardware Setup Wizard, the **Admin Setup** screen appears. This creates the first administrator account and only needs to be completed once per installation.

The welcome page explains the three user roles and the privileges each one carries:

| Role | UI Surface | Can do | Cannot do |
|---|---|---|---|
| **Technician** | Operator Mode | Run approved scan profiles, view PASS/FAIL verdicts | Create/edit profiles, change hardware settings, manage users |
| **Failure Analyst** | Full UI | Full UI access, create scan profiles, AI assistance | Manage users, change security settings |
| **Researcher** | Full UI | Full UI access, create scan profiles, AI assistance | Manage users, change security settings |

Any user of any type can be granted **Administrator** privileges as an overlay. Administrators can manage users, change system settings, and approve scan profiles for operator use.

**To complete Admin Setup:**

1. Enter a **Display Name** (shown in the header, e.g. "Jane Smith").
2. Enter a **Username** (used to log in, case-insensitive).
3. Enter a **Password** and confirm it. A strength indicator is shown.
4. Click **Create Account**. The account is created and you are logged in automatically.
5. The Hardware Setup Wizard opens immediately after.

> You cannot dismiss this screen without creating an account. All fields are required.

### 3.3 Page 1 — Welcome

Displays a brief overview of the system. No camera SDK installation is required before clicking Next — pypylon bundles the pylon runtime, and the FLIR Boson SDK is bundled in the installer.

The scan status label updates as each hardware class is checked. Wait for "Scan complete — N devices found" before clicking **Next**, or click through immediately if you prefer to configure manually.

### 3.4 Page 2 — TEC Controllers

Two TEC controllers are supported independently.

**Meerstetter TEC-1089 / TEC-1123 (Hot-side controller)**

| Field | Options | Notes |
|---|---|---|
| Driver | `meerstetter` / `simulated` | Use simulated if no hardware connected |
| COM Port | Editable combo (refresh ↺) | Auto-filled if detected |
| Address | 2 (fixed) | Default Meerstetter device address |
| Baud rate | 57600 (fixed) | Fixed by Meerstetter protocol |

**ATEC-302 (Cold-side / secondary controller)**

| Field | Options | Notes |
|---|---|---|
| Driver | `atec` / `simulated` | |
| COM Port | Editable combo (refresh ↺) | |
| Address | 1 (fixed) | |
| Baud rate | 9600 (fixed) | |

### 3.5 Page 3 — Camera

| Field | Options | Notes |
|---|---|---|
| Driver | `pypylon` / `Microsanj IR Camera` / `ni_imaqdx` / `directshow` / `simulated` | |
| Camera Serial # | Text field | Leave blank for first found camera |
| NI Camera Name | Text field | NI IMAQdx only — e.g. `cam4` |

> **pypylon** — Self-contained; no separate Basler SDK install required. Supports all Basler USB3 Vision and GigE Vision cameras including the TR and SWIR models.
> **boson** — FLIR Boson 320 / 640 IR camera. SDK is bundled in the installer. Set `serial_port` and `video_index` in Device Manager after connecting.
> **Microsanj IR Camera** — Uses the `flir` driver via `flirpy` (bundled). No external SDK required.
> **ni_imaqdx** — Requires NI Vision Acquisition Software. Camera name is shown in NI MAX.
> **simulated** — Generates synthetic frames; no hardware needed.

The background device scan auto-selects the correct driver and pre-fills the serial number for both Basler and Microsanj IR cameras when detected.

### 3.6 Page 4 — FPGA

| Field | Options | Notes |
|---|---|---|
| Driver | `ni9637` / `simulated` | |
| Bitfile | File path (Browse…) | Path to compiled `.lvbitx` firmware |
| Resource | Text field | NI resource string, e.g. `RIO0` or `rio://hostname/RIO0` |

The resource string is visible in **NI MAX → Devices and Interfaces**. Common values:

- `RIO0` — Locally connected CompactRIO
- `rio://192.168.1.1/RIO0` — Network CompactRIO
- `Dev1` — USB-6001 DAQ fallback

### 3.7 Page 5 — Bias Source

| Field | Options | Notes |
|---|---|---|
| Driver | `keithley` / `visa_generic` / `simulated` | |
| VISA address | Text field | e.g. `GPIB0::24::INSTR` or `USB0::...` |
| Instrument type | Combo | Keithley 24xx / 26xx, Rigol DP832, generic SCPI |

Use **simulated** if no bias source is connected or for software-only use.

### 3.8 Page 6 — Stage

| Field | Options | Notes |
|---|---|---|
| Driver | `thorlabs` / `prior` / `serial_stage` / `simulated` | |
| COM Port | Editable combo | Auto-filled if detected |
| Dialect | `prior` / `ludl` / `asi` / `marzhauser` | For `serial_stage` only |

Use **simulated** if no motorised stage is present.

### 3.9 Page 7 — AI Assistant

This page configures the local language model used by the AI Assistant.

- **Ollama** — The recommended backend. If Ollama is not detected, an install link is shown.
- **Pull model** — Select a model from the combo and click **Pull** to download it into Ollama.
- **Model list** — After pulling, the downloaded model appears in the list. Select it and click **Connect**.

The AI Assistant works without a model — it falls back to rule-based diagnostics only. The model can also be set up later via **Settings → AI Assistant**.

### 3.10 Page 8 — Done

Review a summary of all configured devices. Click **Finish** to write `config.yaml` and launch the application. Click **Back** to revise any earlier page.

The wizard can be re-opened at any time via **Help → Hardware Setup…** (Ctrl+Shift+H).

> **Skip Setup:** A **Skip Setup** button at the bottom-left of each wizard page closes the wizard without saving changes, using the existing `config.yaml` (or defaults on a fresh install).

> **License Activation:** Immediately after the wizard closes on a fresh install, the **License Activation** prompt appears (see Section 20.7). You can activate your key there or choose **Continue in Demo Mode** and activate later.

---

## 4. Application Overview

### 4.1 Top Bar

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [Microsanj logo]  SanjINSIGHT   [ ● Connected Devices ▾ ]  [User] [■ STOP] │
└──────────────────────────────────────────────────────────────────────────┘
```

| Element | Description |
|---|---|
| **Logo / App name** | Microsanj branding |
| **Connected Devices button** | A single dropdown button showing the overall connection state. Click it to open a popup listing every configured device with its individual status dot (● cyan = connected, ● red = error/disconnected). The popup footer has a **Manage devices…** link that opens the Device Manager. |
| **User display** | Shows the logged-in user's display name and type badge (e.g. "Jane Smith  [OP]"). Includes a **Log in** button when no session is active (visible only when an admin account exists) and a **Log out** button when a session is active. Hidden in no-auth mode. |
| **■ STOP** | Emergency stop button — see Section 5 |

> **Update badge:** When a newer release is available, a badge appears in the **Connected Devices** dropdown or the application title. Click it to go to **Help → Check for Updates…**.

### 4.2 Left Sidebar

The sidebar organises all panels into functional groups. Click any item to open it in the main area. The sidebar collapses to a narrow accent bar — click it to re-expand.

**ACQUIRE section**

| Panel | Shortcut | Sub-tabs | Purpose |
|---|---|---|---|
| **AutoScan** ★ | — | — | Guided one-screen measurement workflow |
| **Live** ★ | Ctrl+L | — | Real-time ΔR/R streaming with EMA smoothing |
| **Capture** ★ | Ctrl+1 | Single · Grid | Single-shot acquisition and automated grid scan |
| **Transient** | — | Time-Resolved · Burst | Time-resolved pulsed and burst (movie) capture |

**ANALYZE section**

| Panel | Shortcut | Purpose |
|---|---|---|
| **Calibration** | — | TEC-stepped C_T coefficient measurement |
| **Analysis** ★ | Ctrl+5 | Post-acquisition ΔR/R and ΔT analysis tools |
| **Sessions** | — | Browse and re-open saved sessions |
| **Compare** | — | Side-by-side session comparison |
| **3D Surface** | — | Interactive 3D rendering of ΔR/R or ΔT map |

**Hardware group** *(collapsible — click the group header to expand/collapse)*

| Panel | Shortcut | Sub-tabs | Purpose |
|---|---|---|---|
| **Camera** | Ctrl+2 | Camera · ROI · Autofocus | Exposure, gain, live preview, ROI, autofocus |
| **Stimulus** | — | Modulation · Bias Source | FPGA lock-in controls and bias source output |
| **Temperature** | Ctrl+3 | — | TEC setpoints, enable/disable, temperature history |
| **Stage** | Ctrl+4 | — | XYZ position, absolute move, jog pad, Home buttons |
| **Prober** | — | — | Semi-automatic prober station controls |

> Hardware items whose device is disabled in `config.yaml` are hidden by default.

**LIBRARY section**

| Panel | Sub-tabs | Purpose |
|---|---|---|
| **Profiles** | Material Profiles · Scan Profiles | C_T material profiles and locked scan recipes |

**Settings** | Ctrl+, | Application preferences, AI model, user management |

> ★ items are recommended starting points for new users.

#### Bottom Drawer — Console & Log

A **Bottom Drawer** runs along the bottom edge of the window. It is collapsed by default (a thin toggle strip is always visible). Press **Ctrl+`** or click the grip handle to expand it.

| Tab | Purpose |
|---|---|
| **Console** | Interactive Python REPL for scripting and automation |
| **Log** | Live application event log with severity filtering |

### 4.3 Menu Bar

**File**
- **Quit** (Ctrl+Q / Cmd+Q) — Exit the application

**Acquisition**
- **▶ Run Sequence** (Ctrl+R) — Capture cold and hot frames and compute ΔR/R
- **■ Abort** (Esc) — Stop the active acquisition or scan
- **Live Mode** (Ctrl+L) — Navigate to the Live panel
- **Scan Mode** (Ctrl+Shift+S) — Navigate to the Capture → Grid panel
- **▶ Start Live Stream** (F5) — Start live streaming
- **■ Stop Live Stream** (F6) — Stop live streaming
- **❄ Freeze / Resume** (F7) — Freeze or resume the live display
- **◈ Run Analysis** (F8) — Run the Analysis pipeline on the current result
- **⊞ Start / Stop Scan** (F9) — Toggle the grid scan

**View**
- **Acquire** (Ctrl+1) — Navigate to Capture panel
- **Camera** (Ctrl+2), **Temperature** (Ctrl+3), **Stage** (Ctrl+4), **Analysis** (Ctrl+5)
- **Device Manager…** (Ctrl+D)

**Help**
- **About SanjINSIGHT…** — Version, build date, licence
- **Check for Updates…** — Compare against latest release on GitHub
- **Hardware Setup…** (Ctrl+Shift+H) — Re-run the hardware wizard
- **Settings** (Ctrl+,) — Application preferences
- **License…** — View or activate licence key
- **Get Support…** — Pre-filled support email with diagnostic data
- **Create Support Bundle…** — Save a `.zip` of logs, config, and device inventory for support

### 4.4 Bottom Drawer Toggle Bar

A 34 px strip runs along the very bottom of the window at all times. It provides quick access to the Console and Log without opening the full sidebar:

| Element | Description |
|---|---|
| **Console / Log buttons** (left) | Checkable — click to jump to that tab in the drawer; auto-opens the drawer if it is collapsed |
| **Grip handle** (centre) | iOS-style pill — click or drag to expand/collapse the drawer |
| **Panel ∧ / ∨** (right) | Chevron button — toggles the drawer open or closed |

Press **Ctrl+`** anywhere in the application to toggle the drawer.

---

## 5. Device Status & Emergency Stop

### 5.1 Status Indicators

Device status is shown in the **Connected Devices** dropdown button in the top bar. Click the button to open the popup, which lists every configured device with a coloured dot:

| Colour | Meaning |
|---|---|
| **Cyan** | Connected and communicating normally |
| **Red** | Not found, disconnected, or driver error |
| **Amber** | Connected but in a warning state (e.g. TEC temperature out of range) |

The button's own appearance reflects the worst-case state across all devices. Click **Manage devices…** in the popup footer to open the full Device Manager (Ctrl+D).

### 5.2 Emergency Stop

The **■ STOP** button in the top bar triggers an immediate hardware stop.

1. **Click ■ STOP** (or press **Ctrl+.**) — All active hardware output is disabled immediately: TEC setpoints are cleared, bias output is switched off, and any running acquisition or scan is aborted. The button label changes to **⚠  STOPPED — Click to Clear**.
2. **Click ⚠ STOPPED — Click to Clear** — Clears the latched stop state and re-arms the button, ready for the next operation.

After clearing the stop, reconnect any dropped devices via **Manage devices…** in the Connected Devices popup (or Ctrl+D).

---

## 6. AutoScan

### 6.1 Overview

AutoScan is the guided measurement panel. It presents a single-screen workflow — configure, preview, scan, review — without requiring knowledge of individual hardware panels. It drives the same acquisition and analysis engine as the manual panels.

Open AutoScan from the sidebar (ACQUIRE → **AutoScan**).

### 6.2 Left Panel — Configuration

The left panel is divided into collapsible setting groups:

| Group | Key controls |
|---|---|
| **Imaging Mode** | Objective magnification, camera driver, illumination wavelength |
| **Goal** | Measurement objective (Hotspot detection / Calibration / Custom) |
| **Stimulus** | FPGA frequency, duty cycle, bias voltage/current |
| **Scan Area** | Single point or grid; columns, rows, step size |
| **Speed** | Frames/half, settle time |
| **Advanced** | Trigger mode, inter-phase delay, averaging options |

Click **Preview** to capture a single live frame and verify field-of-view alignment before committing to a full scan.

### 6.3 Right Panel — Live View and Results

The right panel shows a live thermal preview while scanning, then displays the result.

| State | Display |
|---|---|
| **Idle** | Live camera feed |
| **Scanning** | Progress bar + live ΔR/R image updating as tiles complete |
| **Complete** | Final ΔR/R (or ΔT) map + MetadataStrip (Tags + Notes) + action bar |

**Post-scan actions:**

| Button | Action |
|---|---|
| **New Scan** | Clears the result and returns to Idle state |
| **Send to Analysis** | Loads the result into the Analysis panel for detailed review |

### 6.4 Readiness Check

A readiness indicator at the top of the configuration panel runs the same diagnostic rules as the manual panels. If any check fails, an amber banner shows the issue with a **Fix it →** link to the relevant hardware panel.

---

## 7. Live View

### 7.1 Overview

The Live tab provides continuous real-time thermoreflectance display. Frames alternate between a cold phase and a hot phase; the difference is computed on-the-fly and smoothed with an exponential moving average (EMA).

### 7.2 Toolbar

| Button | Action |
|---|---|
| **▶ Start** | Begin streaming. Button animates (⠙ Streaming…) while active. |
| **■ Stop** | End streaming and release camera. |
| **❄ Freeze** | Pause display update without stopping capture. Button changes to ▶ Resume. |
| **📷 Capture** | Save the currently displayed frame to disk. |
| **↺ Reset EMA** | Restart the exponential moving average accumulator (clears the smoothed image). |

### 7.3 Left Panel — Live Settings

#### Trigger (Group Box)

| Control | Range | Description |
|---|---|---|
| **Mode** | `fpga` / `software` | `fpga` uses the FPGA lock-in signal for precise phase lock; `software` uses a CPU timer |
| **Trigger delay** | 0–100 ms | Wait time after the trigger edge before grabbing frames |

#### Acquisition (Group Box)

| Control | Range | Default | Description |
|---|---|---|---|
| **Frames/half** | 1–64 | 4 | Number of camera frames grabbed per cold/hot phase per cycle |
| **EMA depth** | 1–256 | 16 | Exponential moving average depth. Higher = smoother image, slower response to transients |
| **Display fps** | 1–30 Hz | 10 | Maximum UI refresh rate |

#### Apply Settings

Changes to live settings take effect when **Apply Settings** is clicked. This updates the running `LiveProcessor` without restarting the stream.

### 7.4 Centre Panel — Live Canvas

The canvas displays the live ΔR/R map scaled to fill the available space. Colour mapping is controlled by the selector at the bottom of the canvas:

| Colormap | Usage |
|---|---|
| `signed` | Blue (negative ΔR/R) through black (zero) to red (positive). Default; shows both heating and cooling. |
| `hot` | Black–red–yellow–white. Suitable for predominantly positive ΔR/R signals. |
| `cool` | White–cyan–blue. Suitable for predominantly negative signals. |
| `viridis` | Perceptually uniform; good for publication. |
| `gray` | Greyscale. |

Move the mouse cursor over the canvas to inspect individual pixels. The position and ΔR/R value are reported in the right panel.

A **FROZEN** badge overlays the canvas when Freeze is active.

### 7.5 Right Panel — Readouts

**SNR Bar** — Vertical dB bargraph (−20 to +40 dB). Colour transitions from green (high SNR, good signal) through yellow to red (low SNR, dominated by noise).

**Frame Stats**

| Readout | Description |
|---|---|
| Min ΔR/R | Minimum value in the current frame |
| Max ΔR/R | Maximum value |
| Mean ΔR/R | Spatial mean |
| Std Dev | Spatial standard deviation |
| SNR | Signal-to-noise ratio (dB) |
| Cycles | Total completed cycles since Start |
| Live fps | Actual display update rate |

**Pixel Probe**

| Readout | Description |
|---|---|
| Position | Pixel coordinates under the cursor |
| ΔR/R | Fractional reflectance change at that pixel |
| ΔT | Temperature change (°C) — only shown if a calibration is applied |

**ΔR/R Histogram** — 64-bin histogram of all pixel values in the current frame. Blue bins = negative values, red bins = positive values.

---

## 8. Capture — Single Acquisition

### 8.1 Overview

The **Capture — Single** tab captures a complete measurement: N cold frames and N hot frames are averaged, ΔR/R is computed, and the result is displayed. This is the standard workflow for a single measurement point.

### 8.2 Readiness Banner

A compact readiness banner appears at the very top of the Acquire tab. It runs all diagnostic rules continuously and summarises the result:

| State | Appearance | Meaning |
|---|---|---|
| **READY TO ACQUIRE** | Green ● | All checks passed; safe to acquire |
| **NOT READY — N issues** | Amber ⚠ | One or more problems require attention |
| **Checking…** | Grey ○ | MetricsService still initialising |

When issues are shown, each one has a **Fix it →** button that navigates directly to the hardware panel responsible. For example, a "Stage not homed" issue links to the Stage panel, where you can click **⌂ Home All**.

### 8.3 Controls

**Trigger & Modulation**

| Control | Options | Description |
|---|---|---|
| **Trigger mode** | `fpga` / `software` | Source for the cold/hot phase switching signal |
| **FPGA frequency** | 50–500 kHz | Lock-in reference frequency (FPGA mode only) |
| **Duty cycle** | 0–100 % | Fraction of cycle in "hot" state |

**Frames**

| Control | Range | Default | Description |
|---|---|---|---|
| **Frames/half** | 1–200 | 20 | Frames averaged per cold and hot phase |
| **Exposure** | 100 µs–100 ms | (from config) | Camera shutter time per frame |
| **Gain** | 0–30 dB | 0 | Camera analogue gain |

> **More frames = lower noise.** Noise is reduced by approximately √N for N averaged frames.

**Processing**

| Control | Default | Description |
|---|---|---|
| **Averaging** | Enabled | Activates frame-to-frame averaging |
| **SNR threshold** | 0 dB | Frames with SNR below this threshold are discarded |

### 8.4 Running an Acquisition

1. Check the readiness banner. Resolve any "NOT READY" issues before proceeding.
2. Configure exposure, gain, and frames/half in the left panel.
3. Click **▶ Run Sequence** or press **Ctrl+R**.
4. The status bar shows progress (frame N of M).
5. When complete, the ΔR/R map appears in the right panel.
6. If a calibration is applied, the ΔT map tab is also populated.

Press **Esc** or click **■ Abort** to cancel a running acquisition.

#### Pre-Capture Validation *(v1.5.0)*

Before each acquisition begins, a preflight validation dialog runs five automated checks:

| Check | Ideal range | Fail condition | What it detects |
|---|---|---|---|
| **Exposure quality** | Mean intensity 30–80 % of dynamic range | Mean < 15 % or peak > 90 % | Under/overexposure |
| **Frame stability** | Coefficient of variation (CV) low | CV > 0.02 | Vibration, flicker, or drift |
| **Focus quality** | Laplacian variance high | Variance < 40 | Out-of-focus image |
| **Hardware readiness** | All devices connected | Any device disconnected or faulted | Missing hardware |
| **TEC stability** | Temperature settled | TEC not at setpoint | Thermal drift |

If all checks pass, acquisition proceeds automatically. If any check fails, a dismissable dialog lists the issues. You can fix them and re-check, or dismiss the dialog to proceed anyway.

Disable preflight checks in **Settings → Pre-Capture Validation** (config key: `acquisition.preflight_enabled`, default: on).

### 8.5 Result Display

| Tab | Content |
|---|---|
| **ΔR/R Map** | Computed thermoreflectance signal map |
| **ΔT Map** | Temperature change map (requires calibration) |
| **Stats** | Min, max, mean, std, SNR, duration, frame count |

---

## 9. Capture — Grid Scan

### 9.1 Overview

The Scan panel automates a stage-driven grid acquisition, stepping the sample through a rectangular array of positions, capturing a tile at each point, and stitching all tiles into a single large-area map.

### 9.2 Left Panel — Scan Configuration

#### Scan Grid (Group Box)

| Control | Range | Default | Description |
|---|---|---|---|
| **Columns (X)** | 1–20 | 3 | Number of tile columns |
| **Rows (Y)** | 1–20 | 3 | Number of tile rows |
| **Step X** | 1–10 000 µm | 100 µm | Horizontal distance between tile centres |
| **Step Y** | 1–10 000 µm | 100 µm | Vertical distance between tile centres |
| **Settle time** | 0.1–30 s | 0.5 s | Wait time after each stage move before capturing |
| **Frames/tile** | 5–200 | 20 | Acquisitions averaged at each tile position |
| **Snake scan** | Checkbox | Enabled | Boustrophedon (alternating) row travel to minimise stage travel |

**Summary label** — Updates in real time to show:
- Calculated map dimensions (pixels)
- Total field of view (µm × µm)
- Estimated scan duration

#### Run Controls (Group Box)

| Control | Description |
|---|---|
| **▶ Start Scan** | Begin the grid scan. Button animates (⠙ Scanning…) while running. |
| **■ Abort** | Stop the scan after the current tile completes. |
| **Progress bar** | 0–100 % completion |
| **Tile label** | "Tile N / M — [state]" showing current progress state |

#### Log

A scrolling text log records all state transitions, errors, and timestamps during the scan.

### 9.3 Right Panel — Map Viewer & Statistics

**Statistics Bar**

| Field | Description |
|---|---|
| **Tiles** | Current / total tiles |
| **Map size** | Stitched map dimensions in pixels |
| **Field of view** | Total area covered in µm × µm |
| **Elapsed** | Time since scan start (seconds) |
| **State** | Current stage: Moving / Settling / Capturing / Stitching / Complete / Error |

**Result Tabs**

| Tab | Content |
|---|---|
| **ΔR/R Map** | Stitched thermoreflectance map with colormap selector. Toggle tile grid overlay with the checkbox. |
| **ΔT Map** | Stitched temperature change map. Available only if a calibration has been applied. |

### 9.4 Scan Workflow (Internal)

For each tile (row-major, or snake-order if enabled):

1. **Move** — Stage positions to tile (x, y) coordinates.
2. **Settle** — Wait the configured settle time for mechanical vibrations to damp out.
3. **Acquire** — Capture N cold and N hot frames.
4. **Stitch** — Composite the tile result into the running ΔR/R map preview.
5. Update progress bar and log.

After all tiles complete: final stitching pass, enable export buttons.

### 9.5 Export

| Button | Output format | Description |
|---|---|---|
| **💾 Save Map** | `.npy` | NumPy float64 array for Python post-processing |
| **🖼 Save Image** | `.png` | Raster image of the stitched ΔR/R map |
| **📄 PDF Report** | `.pdf` | Multi-page PDF: maps, statistics, scan metadata |
| **◈ Save as Profile** | (profile store) | Save the ΔR/R map as a material profile for future reference |

> **Example CSV:** See `docs/samples/example_test.csv` for a 20-row sample export with columns `x_um, y_um, delta_t_c, delta_r_over_r, verdict, hotspot_count, peak_k, scan_duration_s`. Use this as a template for automated post-processing workflows or data import validation.

---

## 10. Transient Capture

### 10.1 Overview

The **Transient** panel (ACQUIRE → Transient) provides two specialised capture modes for time-domain thermoreflectance measurements. It is intended for devices driven by pulsed stimuli where the thermal response must be resolved in time.

### 10.2 Time-Resolved Sub-tab

Captures a sequence of ΔR/R frames phase-locked to a repeating stimulus pulse, building a time-resolved thermal map at each delay offset.

| Control | Description |
|---|---|
| **Trigger source** | FPGA trigger (locked to stimulus) or external TTL |
| **Delay steps** | Number of time delay points |
| **Delay start / end** | Start and end delay relative to pulse rising edge (ns–µs) |
| **Frames/step** | Frames averaged at each delay point |
| **Run** | Starts the delay sweep; progress shown per step |

The result is a 3D array (time × height × width) that can be exported as a NumPy `.npy` or HDF5 file, or animated as a time-series map.

### 10.3 Burst (Movie) Sub-tab

Captures a rapid burst of ΔR/R frames to record a thermal transient as it evolves, without phase-locking to a specific delay.

| Control | Description |
|---|---|
| **Frame count** | Total burst frames to capture |
| **Frame rate** | Requested capture rate (camera-limited) |
| **Trigger** | Free-run or single external trigger pulse |
| **Run** | Starts the burst; progress shown as frame N/M |

The output is a sequence of ΔR/R frames exportable as an image stack (TIFF) or NumPy array.

> **20 mA Range Mode:** For IR camera FA and Movie mode, the bias source 20 mA limit must be unchecked (see §14.2 Stimulus → Bias Source sub-tab). Verify the DUT thermal budget before exceeding 20 mA.

---

## 11. Calibration

### 11.1 Overview

Calibration measures the thermoreflectance coefficient **C_T** (units: K⁻¹) on a pixel-by-pixel basis. The TEC steps the sample through a range of temperatures; at each step, the app captures a ΔR/R map. A linear regression of ΔR/R vs. ΔT at each pixel yields C_T and R² (fit quality).

Once applied, C_T is used by all other panels (Live, Acquire, Scan) to display ΔT = ΔR/R ÷ C_T.

### 11.2 Left Panel — Calibration Setup

#### Temperature Sequence

Click a preset to populate the list quickly:

| Preset | Points | Range (°C) | Notes |
|---|---|---|---|
| **3-pt** | 3 | 25, 35, 45 | Quick check for known samples |
| **5-pt** | 5 | 25, 30, 35, 40, 45 | Standard starting point |
| **7-pt** | 7 | 25–43 (equal spacing) | Higher accuracy for variable-C_T samples |
| **TR Std** | 6 | 20, 40, 60, 80, 100, 120 | Microsanj standard TR protocol (~12 min total) |
| **IR Std** | 7 | 85, 90, 95, 100, 105, 110, 115 | Standard for IR camera calibration |

Or build a custom sequence:
- Adjust the value in any row's spinbox (−20 to +150 °C).
- Click **+ Add** to append a new point.
- Click **✕** on any row to delete it.
- Temperatures are automatically sorted before the run begins.

> **Minimum 2 temperature points required.** For best accuracy, use at least 5 points spanning ≥ 15 °C.

**Estimated time label** — Displayed below the preset buttons. Updates live as you add or remove temperature steps and adjust **Avg frames/step** and **Max settle time**, giving a projected run time before you start.

#### Capture Settings (Group Box)

| Control | Range | Default | Description |
|---|---|---|---|
| **Avg frames/step** | 5–200 | 20 | Frames averaged at each temperature point |
| **Max settle time** | 1–300 s | 30 s | Maximum time to wait for temperature stabilisation before aborting |
| **Stable tolerance** | 0.01–2.0 °C | 0.2 °C | Temperature is considered stable when it remains within ±tolerance |
| **Stable duration** | 1–60 s | 5 s | Minimum time the temperature must remain stable |
| **Min R²** | 0.1–1.0 | 0.80 | Pixels with R² below this threshold are excluded from the calibration mask |

#### Run Controls

| Control | Description |
|---|---|
| **▶ Run Calibration** | Start the temperature sequence. Button animates (⠙ Calibrating…) while running. |
| **■ Abort** | Stop after the current temperature step. If valid results already exist, a confirmation dialog appears: "Valid calibration results exist but have not been saved. Abort anyway?" |
| **Progress bar** | 0–100 % across all steps |
| **Step label** | "Step N / M — [state]" |

### 11.3 Right Panel — Calibration Results

**Statistics Bar**

| Field | Description |
|---|---|
| **State** | Current phase: Settling / Capturing / Fitting / Complete |
| **T Range** | Min – Max °C from the sequence |
| **Points** | Number of temperature steps captured |
| **Valid pixels** | % of pixels with R² ≥ min R² threshold |
| **Mean C_T** | Spatial mean of the C_T map (K⁻¹) |
| **Saved** | Path to last saved calibration file |

**Result Map Tabs**

| Tab | Content |
|---|---|
| **C_T Map** | Thermoreflectance coefficient per pixel. Diverging blue–red colormap. |
| **R² Map** | Coefficient of determination per pixel (0–1). White = perfect linear fit; black = poor fit. |
| **Residual Map** | RMS residual of the linear fit per pixel. Lower = better fit quality. |
| **Quality ✦** | Interactive chart panel — see §11.5 below. |

**Calibration File (Group Box)**

| Button | Action |
|---|---|
| **💾 Save .cal** | Save the full calibration result to a `.npz` file |
| **📂 Load .cal** | Load a previously saved calibration |
| **✓ Apply to Acquisitions** | Mark this calibration as active — enables ΔT display in Live, Acquire, and Scan panels |

### 11.4 Calibration Workflow

```
Set temperature sequence
        │
        ▼
Click ▶ Run Calibration
        │
        ▼
  For each temperature
  ┌─────────────────────────────────────┐
  │  TEC → setpoint                     │
  │  Wait: temperature stable?          │
  │  No → wait (up to max settle time)  │
  │  Yes → acquire N frames             │
  │  Compute ΔR/R for this step         │
  └─────────────────────────────────────┘
        │
        ▼
  Fit ΔR/R = C_T × ΔT per pixel
  Compute R² and residual maps
        │
        ▼
  Review C_T / R² maps
  Save .cal file
  ✓ Apply to Acquisitions
```

### 11.5 Calibration Quality Chart (Quality ✦ tab)

The **Quality ✦** tab provides three interactive charts for assessing calibration reliability at a glance:

**R² Histogram**

Bars show the distribution of R² values across all valid pixels, coloured by quality:

| Bar colour | R² range | Meaning |
|---|---|---|
| Green | ≥ 0.95 | Excellent fit — reliable ΔT data |
| Amber | 0.80 – 0.95 | Acceptable; minor noise |
| Red | < 0.80 | Poor fit — consider masking these pixels or recalibrating |

A good calibration shows the majority of bars in the green region.

**C_T Histogram**

Shows the spread of thermoreflectance coefficient values across the imaged area (displayed in units of ×10⁻⁴ K⁻¹). A narrow, symmetric peak centred on the expected material value indicates uniform optical contact and consistent heating. A wide or bimodal distribution may indicate contamination, shadowing, or mixed materials in the field of view.

**Calibration Curve**

Scatter plot of mean ΔR/R (spatial average across all pixels, per temperature step) versus set temperature. The fitted linear trendline is overlaid. A tight linear scatter with low residuals confirms the assumed ΔR/R = C_T × ΔT model is valid for this sample. Significant nonlinearity or step-to-step scatter suggests: TEC not fully settled, sample drift, or illumination instability.

> **Tip:** All three charts update automatically when a calibration finishes or a `.cal` file is loaded.

---

## 12. Analysis Panel

### 12.1 Overview

The **Analysis** panel (ANALYZE → Analysis, shortcut **Ctrl+5**) provides post-acquisition hotspot detection and statistical analysis. It receives data automatically after every acquisition (AutoScan, Capture, or Grid Scan) or can be loaded manually via the **Send to Analysis** button on any result panel.

### 12.2 Controls

| Control | Description |
|---|---|
| **Threshold (K)** | Temperature rise above which a pixel is classified as a hotspot. Only meaningful when a calibration is applied and a ΔT map is available. |
| **▶ Run Analysis** (F8) | Executes the hotspot detection pipeline on the current result map. |
| **■ Clear** | Clears the current analysis result. |

### 12.3 Verdict Banner

After analysis completes, a colour-coded verdict banner appears at the top of the panel:

| Colour | Verdict | Meaning |
|---|---|---|
| Green | **PASS** | No pixels exceed the hotspot threshold |
| Red | **FAIL** | One or more pixels exceed the threshold |
| Amber | **REVIEW** | Analysis incomplete or threshold not set |

### 12.4 Summary Statistics

| Statistic | Description |
|---|---|
| **Max ΔT** | Peak temperature rise (°C) in the analysed region |
| **Hotspot count** | Number of spatially connected hotspot regions above threshold |
| **Mean ΔT** | Area-weighted mean temperature rise |
| **SNR** | Signal-to-noise ratio of the ΔR/R map (dB) |
| **Dark pixel fraction** | Fraction of pixels excluded due to insufficient illumination |

### 12.5 ΔT Histogram Chart

An interactive histogram chart is embedded below the summary statistics. It shows the distribution of temperature rise values across all pixels in the analysed area:

- **Bars** — binned pixel count at each ΔT value
- **Threshold line** — vertical red dashed line at the configured threshold temperature
- **Verdict annotation** — PASS or FAIL label in the chart area

The histogram makes it easy to see whether hotspot pixels represent a narrow spike above background or a broad elevated tail, which informs whether the threshold is set appropriately.

> **Tip:** A FAIL result with only a tiny number of pixels above the threshold line may indicate a noisy pixel rather than a true device hotspot. Inspect the spatial map before concluding.

### 12.6 Hotspot Table

Below the histogram, a table lists each detected hotspot region with its peak ΔT, area (pixels), and centroid coordinates (x, y). Click any row to highlight the corresponding region on the map.

### 12.7 RGB Analysis *(v1.5.0)*

When the source acquisition was captured with a color (RGB) camera, the analysis engine operates on 3-channel data:

- **Per-channel ΔR/R:** The signal map is computed as (H, W, 3) with independent ΔR/R values for each color channel (red, green, blue).
- **Luminance reduction:** For threshold-based hotspot detection and morphological operations, the engine reduces the 3-channel map to a single luminance channel using Rec. 709 weights (0.2126 R + 0.7152 G + 0.0722 B). This ensures consistent pass/fail verdicts regardless of color content.
- **Per-channel statistics:** The `rgb_analysis` module provides per-channel min, max, mean, and standard deviation. These are available in the Stats tab when viewing an RGB acquisition result.

Monochrome acquisitions are unaffected — the analysis engine detects the channel count automatically.

---

## 13. Sessions Panel

### 13.1 Overview

The **Sessions** panel (ANALYZE → Sessions) provides a searchable, card-based browser for all saved acquisition sessions stored in `~/.microsanj/sessions/`. Each session appears as a card showing its label, timestamp, thumbnail, PASS/FAIL badge, and key metrics.

### 13.2 Session Cards

Each card shows:
- **Thumbnail** — false-colour preview of the ΔR/R map (or blank if no data was saved)
- **Label** — editable name, shown in bold
- **Timestamp** — date and time the session was saved
- **Verdict badge** — PASS / FAIL / — colour chip
- **SNR** and **ΔT peak** metrics if available

Click a card to select it; double-click to open it in the Analysis panel.

### 13.3 Session Trend Chart

A **Session Trend** chart in the right column plots measurement metrics across all sessions in chronological order:

- **Top panel** — SNR (dB) per session as a scatter plot. Green points = high quality; amber = moderate; red = low SNR.
- **Bottom panel** — TEC temperature (°C) at acquisition time, where available.

Both panels share a linked x-axis, so panning or zooming one panel moves the other in sync. The trend chart updates automatically whenever sessions are added, removed, or refreshed.

**Reading the trend chart:**
- A gradual downward trend in SNR over many sessions can indicate drift in illumination power, alignment, or camera noise floor.
- A sudden SNR drop on a specific session suggests a one-off event (vibration, illumination interruption, sample movement).
- TEC temperature variation visible in the bottom panel that correlates with SNR variation in the top panel suggests the calibration may need to be updated.

### 13.4 Session Actions

| Button | Action |
|---|---|
| **Open** | Load the session's ΔR/R and ΔT arrays into the Analysis panel |
| **Set A / Set B** | Mark this session as comparison input A or B |
| **Compare A vs B** | Open the Compare panel with sessions A and B loaded |
| **Export** | Export session data in TIFF, HDF5, NumPy, or PDF format |
| **Delete** | Permanently remove the session folder from disk *(confirmation required)* |

### 13.5 Session Schema *(v1.5.0 — Schema v3)*

The `session.json` metadata file uses schema version 3. New fields added in v3:

| Field | Type | Description |
|---|---|---|
| `frame_channels` | int | 1 = mono, 3 = RGB |
| `frame_bit_depth` | int | Native sensor bit depth (12, 14, or 16) |
| `pixel_format` | string | `"mono"`, `"bayer_rggb"`, or `"rgb"` |
| `preflight` | dict or null | Pre-capture validation results (pass/fail per check, timestamps) |

**Auto-migration:** Sessions saved by older versions (schema v1 or v2) are automatically migrated to v3 when loaded. Migrated sessions default to `frame_channels: 1`, `frame_bit_depth: 16`, `pixel_format: "mono"`, and `preflight: null`.

---

## 14. Hardware Panels

All hardware panels are located in the collapsible **Hardware** group in the left sidebar. Each entry may contain multiple sub-tabs.

### 12.1 Camera Panel (Ctrl+2)

The **Camera** sidebar entry opens a panel with three sub-tabs: **Camera**, **ROI**, and **Autofocus**.

**Camera sub-tab** — Controls camera exposure and gain; displays a live frame statistics readout.

| Readout | Description |
|---|---|
| **MIN** | Minimum pixel value in the latest frame |
| **MAX** | Maximum pixel value (12-bit sensor: 0–4095) |
| **MEAN** | Mean pixel value |
| **FRAME** | Frame counter |
| **SATURATION** | Percentage of pixels at or near the 12-bit ceiling |

**Saturation Guard:**
- **OK** (green) — Maximum pixel value < 3900; full dynamic range available
- **N.NN%** (amber) — Maximum pixel value ≥ 3900; some pixels near saturation
- **CLIPPED ✗** (red) — One or more pixels at 4095 (hard saturation); ΔR/R measurements in those pixels are invalid

> **What to do when clipped:** Reduce exposure in the Camera sub-tab or lower the illumination intensity until the SATURATION readout returns to "OK".

**ROI sub-tab** — Defines a region of interest (rectangle, in pixels) that restricts the active sensor area. Reducing the ROI increases frame rate and reduces data volume per acquisition.

**Autofocus sub-tab** — Drives the Z-axis stage to find the sharpest focus position. Select the focus metric (variance, Laplacian, or gradient) and click **Run Autofocus** to execute a Z-sweep.

#### Camera Sub-Tab Quick-Action Buttons *(v1.5.0)*

| Button | Visibility | Description |
|---|---|---|
| **Optimize Throughput** | All TR cameras (hidden for IR) | Runs the FPS Optimizer: (1) maximizes LED duty cycle, (2) sets camera to maximum frame rate, (3) binary-searches exposure to achieve 70 % of dynamic range. The result is the highest achievable frame rate at a usable exposure level. |
| **Run FFC** | Cameras that support flat-field correction (Boson, FLIR IR) | Triggers a flat-field correction cycle on the sensor. Run before calibration or whenever the ambient temperature changes significantly. Hidden when the camera does not support FFC. |
| **Autofocus** | When a motorized stage is connected | Runs autofocus using the last-used settings (metric and range). Executes in a background thread. Disabled when no stage is connected. |

### 12.2 Stimulus Panel

The **Stimulus** sidebar entry opens a panel with two sub-tabs: **Modulation** and **Bias Source**.

**Modulation sub-tab** — Controls FPGA lock-in modulation frequency, duty cycle, and Start/Stop.

**Duty Cycle Warning:**

When the duty cycle is set to ≥ 50 %, a warning label appears below the duty cycle controls:

> ⚠ Duty cycle ≥ 50 % increases average power delivered to the DUT. Monitor device temperature closely — risk of overheating.

The label color escalates based on severity:

| Duty Cycle | Label color | Risk |
|---|---|---|
| < 50 % | Hidden | Normal |
| 50–79 % | Amber | Elevated thermal risk |
| ≥ 80 % | Red | High overheating risk — reduce immediately |

> **Transient imaging:** For time-resolved thermoreflectance measurements, keep the DUT duty cycle between 25 % and 35 % to allow adequate cool-down between pulses while still reaching maximum operating temperature.

**Quick-action buttons** — Preset duty cycles: 10 %, 25 %, 50 %, 75 %, 90 %.

**Start / Stop** — Begin or halt FPGA modulation. Modulation must be running (L1 check) for lock-in acquisition.

#### BNC 745 Trigger Mode

When a **BNC Model 745** digital delay generator is connected, a **Trigger Mode** panel appears below the Quick Controls. This panel is hidden when using the NI-9637.

| Control | Description |
|---|---|
| **Continuous** | T0 free-runs at the configured frequency — standard lock-in operation |
| **Single-shot** | T0 fires once per **▶ Arm Trigger** click — for pulsed IV / transient measurements |
| **Pulse Duration (µs)** | Directly sets the camera-channel (Ch 1) pulse width, overriding the duty-cycle derived width |
| **▶ Arm Trigger** | Fire one single-shot pulse. Enabled only in Single-shot mode |

A **TRIGGER** readout appears in the status bar alongside FREQUENCY and SYNC:

| Status | Meaning |
|---|---|
| **CONT** | Continuous (free-running) mode |
| **SINGLE** | Single-shot mode, idle |
| **SINGLE ✦** | Single-shot mode, pulse armed/firing |

> **Workflow for pulsed IV measurements:** set Mode → Single-shot, configure Pulse Duration to match the AMCAD BILT Drain channel width, then click **▶ Arm Trigger** once per measurement point. Use Continuous mode for standard lock-in thermoreflectance.

---

**Bias Source sub-tab** — Controls the electrical output to the device under test (DUT).

**Output Port Selector:**

| Port | Type | Range | Notes |
|---|---|---|---|
| **VO INT — pulsed ±10 V** | Pulsed (bipolar) | ±10 V | Internal DAC; synchronised with FPGA modulation |
| **AUX INT — DC ±10 V** | DC (bipolar) | ±10 V | Secondary DC output; independent of modulation |
| **VO EXT — pulsed ≤+60 V** | Pulsed (unipolar) | 0–+60 V | Passthrough from external supply |

When **VO EXT** is selected, a safety warning appears:

> ⚠ VO EXT routes the external supply directly to the DUT. Confirm external supply current limit before enabling output.

**20 mA Range Mode checkbox:**
- **Checked** (default) — Current is limited to ≤ 20 mA. Appropriate for most device types.
- **Unchecked** — Removes the 20 mA limit. Required for IR camera FA (Fault Analysis) and Movie mode, which needs > 20 mA. Always verify the device thermal budget before unchecking.

> **Compliance limit:** Always set the Compliance Limit to the maximum safe current (or voltage) for your DUT before enabling output.

#### AMCAD BILT Pulsed I-V System

When an **AMCAD BILT** is connected, the Bias Source sub-tab gains two additional elements:

**Gate channel readout row** — A second row appears in the Measured Output status header showing Gate (Ch 1) measurements alongside the standard Drain (Ch 2) readouts.

| Readout | Description |
|---|---|
| **GATE Vg** | Gate channel measured voltage |
| **GATE Ig** | Gate channel measured current |

**AMCAD BILT Pulse Configuration panel** (collapsible) — Configures independent bias and pulse parameters for Gate (Ch 1) and Drain (Ch 2).

| Parameter | Description |
|---|---|
| **Bias (V)** | DC bias voltage applied outside the pulse window |
| **Pulse (V)** | Voltage during the pulse window |
| **Width (µs)** | Pulse duration in microseconds |
| **Delay (µs)** | Delay from trigger rising edge to pulse start |

Default values (from PIV1.txt):

| Parameter | Gate (Ch 1) | Drain (Ch 2) |
|---|---|---|
| Bias | −5.0 V | 0.0 V |
| Pulse | −2.2 V | +1.0 V |
| Width | 110 µs | 100 µs |
| Delay | 5 µs | 10 µs |

Click **Apply Pulse Config** to push the settings to the BILT hardware. This does not enable output — click **Output ON** afterwards to begin pulsing.

> **pivserver64.exe** must be running on the Windows instrument PC before connecting the BILT. Launch it from the AMCAD installation directory:
> ```
> pivserver64.exe -p 5035
> ```
> If the connection is refused, add a Windows Firewall inbound rule for TCP port 5035 on the instrument PC (Control Panel → Windows Defender Firewall → Advanced Settings → Inbound Rules → New Rule).

### 12.3 Temperature Panel (Ctrl+3)

Controls TEC setpoints and displays real-time temperature history for all connected TEC channels.

**TEC Setpoint Range:** 10 °C to 150 °C (hardware limit from EZ-Therm / Nano-THERM specs).

### 12.4 Stage Panel (Ctrl+4)

Controls the XYZ motorised stage with absolute move, relative jogging, and home/stop operations.

**Position Readouts** — Shows current X, Y, Z position in µm and a STATUS indicator:
- **READY ✓** (green) — Stage is homed and stationary
- **MOVING ↔** (amber) — Stage is currently moving
- **NOT HOMED** (dim) — Stage has not been homed; automated moves may be inaccurate

**Home buttons** (at the bottom of the Stage panel):

| Button | Action |
|---|---|
| **⌂ Home All** | Home all three axes (X, Y, and Z) to their reference positions |
| **⌂ Home XY** | Home X and Y axes only |
| **⌂ Home Z** | Home Z axis only |

> **Always home the stage before running automated scans or recipes.** The "Stage homed" diagnostic rule (R3) will show a warning in the AI Assistant and Readiness Banner until homing is complete.

**Jog Pad** — Directional arrows (N/S/E/W and diagonals) for manual XY positioning. Step size: 0.1 / 1 / 10 / 100 / 1000 / 5000 µm.

**■ STOP** — Immediately halts all stage motion.

### 12.5 Prober Panel

The **Prober** panel appears in the Hardware group when a supported probe station is configured. It provides manual probe positioning (X/Y/Z in µm) and contact detection. Configure the prober connection in the Hardware Setup Wizard or Device Manager.

---

## 15. AI Assistant

### 13.1 Overview

The AI Assistant is a dockable panel that provides real-time instrument intelligence powered by a local language model running entirely on your PC (no internet connection required after setup).

Key capabilities:
- **Readiness grading** — Evaluates all diagnostic rules every few seconds and assigns a letter grade (A–D)
- **Issue navigation** — Lists active problems with one-click "Fix it →" links to the relevant hardware panel
- **Tab explanation** — Explains what the currently visible panel does and what to check given live instrument state
- **Free-form chat** — Answers questions about instrument settings, measurement technique, and troubleshooting

### 13.2 Grade System

The AI panel shows a large letter grade based on the current diagnostic rule results:

| Grade | Condition | Colour | Meaning |
|---|---|---|---|
| **A** | No issues | Green | All checks passed; instrument is ready |
| **B** | 1–2 warnings | Light green | Minor warnings; review but can proceed |
| **C** | 1 fail, or ≥ 3 warnings | Amber | Significant issue; address before acquiring |
| **D** | ≥ 2 fails | Red | Critical failures detected; results will be unreliable |

The grade badge (36 pt, bold) is accompanied by a brief summary such as "Instrument ready" or "1 fail · 2 warn".

### 13.3 Issue Rows

Up to 5 active issues are listed below the grade badge. Each row shows:
- **⊗** (red) for a fail, **⚠** (amber) for a warning
- The rule's display name and observed value (e.g. "TEC 1 stable · Δ0.18°C")
- Clicking the row navigates to the hint text for that rule

### 13.4 Quick Actions

| Button | Action |
|---|---|
| **Explain this tab** | Asks the AI to describe the currently visible panel and what to check given the live instrument state. Enabled only when a model is loaded. |
| **Diagnose** | Asks the AI to review all active issues and suggest a concrete fix for each. |

### 13.5 Free-Form Chat

Type any question in the chat box and press **Ask** (or Enter). Example questions:
- "What LED wavelength should I use for GaAs?"
- "Why is my ΔR/R signal noisy?"
- "Where is the Home All button?"
- "Is a duty cycle of 75% safe?"
- "What does the R² map tell me?"

The AI grounds every answer in the live JSON instrument state, so it can reference your current exposure, TEC temperature, focus score, and so on.

**Token rate** — Displayed below the response as "N tok/s · X.Xs". On a typical desktop CPU this is 15–50 tokens/second depending on model size.

### 13.6 AI Model Setup

The AI Assistant requires a local language model (~2–5 GB). On first use, the response area shows installation instructions.

To download the model:
1. Open **Settings** (Ctrl+,) → **AI Assistant** tab.
2. Click **Download Model**. Progress is shown in the Settings panel.
3. Once complete, the AI Assistant panel activates automatically.

The model is stored locally and never sends data to any external server.

### 13.7 Readiness Widget (Acquire Tab)

A compact readiness banner appears at the top of the Acquire tab independently of the AI Assistant panel. It provides the same pass/fail assessment as the AI grade system in a minimal form factor optimised for the acquisition workflow:

- **● READY TO ACQUIRE** (green) — All checks passed
- **⚠ NOT READY — N issues** (amber) — Shows each issue with a **Fix it →** navigation button

---

## 16. Compare Sessions

### 14.1 Overview

The **Compare** panel (ANALYZE → Compare) places two sessions side-by-side so differences in thermal distribution can be assessed visually and quantitatively. Open it from the sidebar after completing two acquisitions, or load sessions from the Sessions browser.

### 14.2 Loading Sessions

- **Left / Right dropdowns** — Select any saved session from the session manager, or drag a `.h5` file directly onto the panel.
- **Sync zoom** — When enabled, panning or zooming one map mirrors the action on the other.
- **Difference map** — A third map shows (Left − Right) with a diverging colormap; hot-spots visible only in one session are immediately apparent.

### 14.3 Statistics Comparison

A statistics bar below the maps shows Min, Max, Mean, Std, and SNR for each session side-by-side, plus the absolute difference in each metric.

---

## 17. 3D Surface

### 15.1 Overview

The **3D Surface** panel (ANALYZE → 3D Surface) renders any 2D ΔR/R or ΔT array as an interactive 3D terrain map using Matplotlib's 3D projection. It updates automatically after each acquisition.

### 15.2 Controls

| Control | Description |
|---|---|
| **Colormap** | Matches the 2D map panel — Emberline, viridis, hot, etc. |
| **Z-stretch** | Vertical exaggeration (1–200×). Increase to reveal small ΔT variations that appear flat at 1×. |
| **Show threshold plane** | Draws a semi-transparent red horizontal plane at the set value. Hotspots above the threshold protrude above the plane, making them immediately visible. |
| **Elevation / Azimuth sliders** | Adjust the 3D viewing angle continuously. |
| **Auto-rotate** | Slowly rotates the azimuth at 20 fps for presentation use. |
| **Export…** | Save the current view to PNG or PDF (200 dpi). |

### 15.3 Data Source

The panel receives data automatically after every Capture, AutoScan, or Grid Scan result. If a calibration is applied, the ΔT surface is shown; otherwise ΔR/R is shown.

To manually load a different dataset, use **Send to Analysis** from the AutoScan or Capture result area, then navigate to 3D Surface — the panel retains the last data pushed to it.

---

## 18. Saving and Exporting Data

### 16.1 Session Storage

When you save a session, a folder is created under `~\.microsanj_sessions\` containing:

```
20260302_143022_device_A/
  session.json      — Human-readable metadata (exposure, gain, TEC temp, etc.)
  cold_avg.npy      — Averaged cold frames (float64)
  hot_avg.npy       — Averaged hot frames (float64)
  delta_r_over_r.npy — ΔR/R signal map (float64)
  difference.npy    — Raw (hot − cold) difference (float64)
  thumbnail.png     — Small PNG preview
```

> **Float64 averaging (v1.5.0):** Pipeline averaging and all NPY files now use float64 precision (previously float32). HDF5 exports also store float64. TIFF exports remain float32 for file-size compatibility with ImageJ/FIJI.

### 16.2 Export Formats

| Format | Extension | Description | Compatible with |
|---|---|---|---|
| **HDF5** | `.h5` | All arrays and metadata in a single hierarchical file (float64) | Python (h5py), MATLAB, HDFView |
| **NumPy** | `.npy` / `.npz` | Native NumPy format (float64) | Python (numpy.load) |
| **TIFF** | `.tiff` | 32-bit floating-point, ImageJ/FIJI compatible (float32 for file size) | ImageJ, FIJI, Olympus, any TIFF reader |
| **CSV** | `.csv` | Tab-separated X (µm), Y (µm), ΔT (°C) | Excel, MATLAB, any spreadsheet |
| **MATLAB** | `.mat` | MATLAB binary format | MATLAB R2006b+ |
| **PNG** | `.png` | 8-bit colormapped raster image | Any image viewer |
| **PDF** | `.pdf` | Multi-page report with maps and statistics | Adobe Reader, any PDF viewer |

### 16.3 Calibration Files

Calibration files (`.npz`) contain:

- `ct_map` — C_T coefficient map (float32, pixels × K⁻¹)
- `r2_map` — R² quality map (float32, 0–1)
- `residual_map` — RMS residual map (float32)
- `mask` — Boolean reliability mask
- Metadata: temperature range, reference temperature, timestamp, frame dimensions

Load a calibration with **📂 Load .cal** in the Calibration panel, then click **✓ Apply to Acquisitions**.

---

## 19. Device Manager

Open with **⚙** (top bar) or **Ctrl+D**.

The Device Manager shows the current connection state and driver details for each hardware class:

| Column | Description |
|---|---|
| **Device** | Hardware class (Camera, TEC, FPGA, Bias, Stage) |
| **Driver** | Active driver module name |
| **Status** | Connected / Disconnected / Error |
| **Info** | Model, port, resource string, or firmware version |

**Reconnect** — Attempts to re-initialise the selected device using the current `config.yaml` settings.

**Disconnect** — Safely closes the driver connection.

> **FLIR Boson cameras:** When a Boson 320 or Boson 640 entry is selected, the Connection Parameters area shows two additional fields: **Serial Port** (the CDC serial interface for SDK/FFC commands) and **Video Device Index** (the `cv2.VideoCapture` index for the UVC video device). Leave Serial Port blank to use video-only mode. Click **Run FFC** to trigger a Flat Field Correction cycle.

> **Note:** Changes to driver type or port require re-running the Hardware Setup wizard (Ctrl+Shift+H) and restarting the application.

---

## 20. Settings

Open with **Help → Settings** or **Ctrl+,**. The Settings panel is organised into collapsible sections.

### 18.1 Appearance

| Setting | Description |
|---|---|
| **Theme** | Three-button segmented control: **Auto** (follows OS dark/light mode), **Dark**, **Light** |

### 18.2 Lab

| Setting | Description |
|---|---|
| **Active operator** | Display name stamped on saved sessions when no login is active |
| **Saved operators** | Manage the list of operator names available in the dropdown |

### 18.3 Security *(admin-only)*

| Setting | Description |
|---|---|
| **Require login on startup** | When enabled, the login screen appears on every launch and after inactivity timeout |
| **Lock timeout** | Inactivity period before the session auto-locks (minutes; 0 = never) |

### 18.4 Users *(admin-only)*

Embeds the full user management table. See Section 21.4 for details.

### 18.4a Pre-Capture Validation *(v1.5.0)*

| Setting | Description |
|---|---|
| **Enable preflight checks** | Checkbox. When enabled, automated validation runs before each acquisition. When disabled, acquisitions start immediately without checks. Config key: `acquisition.preflight_enabled` (default: on). |

### 18.4b Autofocus *(v1.5.0)*

| Setting | Description |
|---|---|
| **Auto-focus before each capture** | Checkbox. When enabled and a motorized stage is connected, autofocus runs automatically before every acquisition. Disabled by default. Requires a connected Z-axis stage. |

### 18.5 Updates

| Setting | Description |
|---|---|
| **Auto-check on startup** | Enable/disable automatic update checks |
| **Check frequency** | Daily / Weekly / Monthly |
| **Channel** | Stable / Beta / Dev |
| **Check Now** | Manually trigger an update check |
| **Release Notes** | Open the changelog for the latest release |

### 18.6 AI Assistant

**Local model (Ollama / bundled)**

| Setting | Description |
|---|---|
| **AI enabled** | Enable or disable the AI Assistant globally |
| **Model** | Select which locally installed model to use |
| **Download Model** | Download the selected model (~2–5 GB). Progress shown inline. |
| **Model path** | Override the default model directory |
| **GPU allocation** | Slider: percentage of GPU VRAM allocated to inference |
| **Persona** | Auto (from user type) / Technician / Failure Analyst / Researcher |
| **Scope** | Always / Session / RAG — controls how much instrument context is included in each prompt |

**Cloud AI**

| Setting | Description |
|---|---|
| **Provider** | OpenAI / Anthropic / Azure / Custom |
| **Model** | Model identifier (e.g. `gpt-4o`, `claude-3-5-sonnet`) |
| **API key** | Paste your API key (stored in OS keychain, never in `config.yaml`) |

**Ollama**

| Setting | Description |
|---|---|
| **Pull model** | Download a new model into Ollama from the Ollama model registry |
| **Model list** | Select from models already installed in Ollama |
| **Connect** | Test the Ollama connection and activate the selected model |

### 18.7 License

#### First-run License Activation prompt

On a fresh installation (or whenever no valid license key is stored), SanjINSIGHT shows the **License Activation** prompt automatically after the Hardware Setup Wizard closes. The prompt appears only once; subsequent launches skip it entirely.

| Button | Action |
|---|---|
| **Activate License** | Paste your Microsanj license key and click to validate. The key is checked immediately — on success the application unlocks full hardware access and the dialog closes. |
| **Continue in Demo Mode** | Dismiss the prompt permanently. The application runs in demo mode (simulated hardware) until a key is entered manually. |

> If activation fails, an inline error message is shown. Double-check the key or contact support@microsanj.com. You can try again without closing the dialog.

#### License settings

| Element | Description |
|---|---|
| **Status** | Shows the current license tier, licensed name, and expiry date if applicable. Amber if expiring within 30 days. |
| **Manage license** | Open the full License dialog to enter a new key or remove the current one. Removing a key reverts the application to demo mode. |

### 18.8 Support

| Button | Action |
|---|---|
| **About** | Version, build date, licence summary |
| **Get Support…** | Opens a pre-filled support email with diagnostic data attached |

---

## 21. User Accounts & Roles

### 19.1 Overview

SanjINSIGHT includes a role-based access control (RBAC) system that lets administrators control who can use the instrument and what they can change. The auth system is **opt-in** — research labs that don't need user management can leave the default setting (`require_login: false`) and the application behaves exactly as before v1.2.0.

### 19.2 User Types

Three user types map the natural roles in a lab or production environment. Each type determines the UI surface the user sees and the default AI Assistant persona they get.

| User Type | UI Surface | Default AI Persona | Can Edit Scan Profiles? | Can Manage Users? |
|---|---|---|---|---|
| **Technician** | Operator Shell | Lab Technician | No | No |
| **Failure Analyst** | Full UI | Failure Analyst | Yes | No |
| **Researcher** | Full UI | Researcher | Yes | No |
| *(any)* **+ Admin** | Full UI + User Management | *(unchanged)* | Yes | Yes |

**Administrator** is a privilege overlay — any user type can be granted admin rights. Admin does not change how the instrument AI talks to the user; it adds access to user management and global settings.

> **Technician users** always land in the Operator Shell after login — a simplified interface designed for repeatably running approved scan profiles. See Section 22 for details.

> **AI persona:** The AI Assistant automatically switches context to match the logged-in user. Failure Analysts get evidence-first diagnostic guidance; Researchers get exploratory explanations. Technicians always get the simplified Lab Technician persona.

### 19.3 Admin Setup (First Launch)

The very first time SanjINSIGHT starts on a new installation, the **Admin Setup Wizard** appears. This one-time screen creates the administrator account that controls who can use the system.

1. Enter a display name, username, and password (confirmed twice). A strength indicator shows password quality.
2. Click **Create Account**. The account is created and you are logged in automatically.
3. The Hardware Setup Wizard opens immediately after.

> You only see this screen once, on a fresh installation. After the admin account exists, subsequent launches proceed directly.

### 19.4 Creating and Managing Users

Open **Settings → Users** (admin login required). The Users panel shows a table of all accounts with columns for display name, username, user type, admin flag, last login, and active status.

**Adding a user**

1. Click **+ Add User**.
2. Select the user type by clicking one of the three profile cards:
   - 🔧 **Technician** — Runs QA scans per SOP; guided Operator Shell UI
   - 🔬 **Failure Analyst** — Diagnoses device failures; full UI access
   - 📚 **Researcher** — Explores and publishes results; full UI access
3. Optionally check **Grant administrator privileges** (adds user management and global settings access).
4. Enter a display name, username, and initial password.
5. Click **Create**. The new user can log in immediately.

**Editing a user:** Select the row and click **Edit** to change display name, user type, or admin flag.

**Deactivating a user:** Click **Deactivate** to disable the account without deleting it. Deactivated accounts cannot log in but their history is preserved.

**Resetting a password:** Click **Reset Password** to set a new temporary password.

### 19.5 Login Gate

By default, SanjINSIGHT does not require login (`auth.require_login = false`). To require login:

1. Open **Settings → Security** (admin login required).
2. Toggle **Require login on startup** to On.
3. Set **Lock timeout** (default 30 minutes; 0 = never auto-lock).

Once enabled, the login screen appears on every launch and after the inactivity timeout.

**Session lock:** When a session is locked (timeout or manual lock), the login screen reappears. The user logs back in to resume where they left off.

**No-login mode:** When `require_login` is off, the application still records a "no-login session" in the audit log so that measurement history can be attributed to the system even without named users.

### 19.6 Per-User Preferences

When login is active, each user has their own preference file (`~/.microsanj/users/{uid}/prefs.json`). User preferences override the global defaults but cannot change hardware or security settings.

| Preference | Description |
|---|---|
| `ui.theme` | Dark, Light, or Auto (follows OS) |
| `lab.default_recipe` | Default scan profile loaded at startup |
| `autoscan.last_objective_mag` | Last-used objective magnification |
| `ui.sidebar_collapsed` | Whether the Hardware sidebar group is collapsed |

Global settings (hardware config, auth settings, lock timeout) are admin-only and stored in `config.yaml`.

### 19.7 Audit Log

All authentication events are appended to `~/.microsanj/audit.log` as JSON Lines. The log is human-readable and can be grepped or imported into a spreadsheet.

```
{"ts": 1741872000.0, "ts_str": "2026-03-13 09:00:00", "event": "login",
 "actor": "jsmith", "user_type": "failure_analyst", "detail": "success", "success": true}
```

| Event | Description |
|---|---|
| `first_admin_created` | Initial admin account created during first-launch wizard |
| `login` | Successful or failed login attempt |
| `logout` | User logged out |
| `locked` | Session locked due to inactivity timeout |
| `supervisor_override` | Temporary engineer access granted at operator station |
| `user_created` | New user account created by admin |
| `user_deactivated` | Account deactivated by admin |
| `password_reset` | Password reset by admin |

The log rotates at 5 MB and keeps 3 backups.

---

## 22. Operator Mode

### 20.1 Overview

Operator Mode is a simplified interface for technicians who run repeatably against approved scan profiles. It launches automatically when a **Technician** user logs in.

```
┌─────────────────────────────────────────────────────────────────┐
│  Logo  │  Operator Mode  │  Jane Smith [OP]  │  12 scans · 91% │
├──────────────┬──────────────────────────┬───────────────────────┤
│ Scan Profile │    Live Camera View      │  Shift Log            │
│ (approved    │                          │  ✓ SN-001  09:14 PASS │
│  profiles    │  [Part ID / Serial #]    │  ✗ SN-002  09:22 FAIL │
│  only)       │                          │  ✓ SN-003  09:31 PASS │
│              │  [  ▶  START SCAN  ]     │                       │
└──────────────┴──────────────────────────┴───────────────────────┘
```

**The Operator Shell has three zones:**
- **Left — Scan Profile Selector:** Lists only scan profiles that have been approved and locked by an engineer.
- **Centre — Scan Work Area:** Live camera view, Part ID / Serial Number field, and the START SCAN button.
- **Right — Shift Log:** Running log of today's results with PASS/FAIL badges and running totals.

### 20.2 Running a Scan

1. Log in as a Technician user.
2. Select a scan profile from the left panel. Only profiles with the "Approved for Operators" badge appear.
3. Scan or type the part serial number in the **Part ID** field. If a USB barcode scanner is connected, scanning the barcode and pressing Enter auto-starts the scan.
4. Click **▶ START SCAN** (or press Enter if the Part ID field is focused).
5. A full-screen verdict screen appears after each scan (see Section 22.3).
6. Results are logged automatically to the Shift Log and exported as a PDF report.

> **START SCAN is disabled** until both a scan profile is selected and a non-empty Part ID is entered.

### 20.3 Verdict Screen

After each scan, a full-screen overlay shows the result:

```
Background colour: green (PASS) / red (FAIL) / amber (REVIEW)

         ✓  PASS
         Part: SN-A12346
         ─────────────────────────────
         Max hotspot:   4.2 °C   (limit: 20 °C)
         Hotspots:      0          Scan time: 8.3 s
         ─────────────────────────────
   [ Flag for Review ]      [ ▶ Next Part ]
              [ View Details ]
```

| Button | Action |
|---|---|
| **▶ Next Part** | Dismisses the verdict screen; returns to the Scan Work Area for the next part |
| **Flag for Review** | Marks the result as "needs engineering review"; adds a flag to the Shift Log entry |
| **View Details** | Opens the full result viewer (read-only) so the operator can see the thermal map |

**Verdict logic** is defined in the scan profile by the engineer who approved it:
- **PASS** — No hotspot exceeds the profile's temperature limit
- **FAIL** — One or more hotspots exceed the limit
- **REVIEW** — Result is within the limit but above a warning threshold (if configured)

### 20.4 Shift Log

The Shift Log panel on the right side records every scan in the current session. Each entry shows:
- PASS / FAIL / REVIEW badge
- Part serial number
- Time of scan
- Scan profile name

Running totals ("12 scans · 91% pass") are shown at the top.

Click **Export CSV** to save the shift log as a comma-separated file for quality system reporting.

### 20.5 Approving Scan Profiles for Operator Use

Only engineers and admins can approve scan profiles. In the full UI:

1. Open **Scan Profiles** (Setup section of the sidebar).
2. Select the profile you want to make available to operators.
3. Configure and test the profile until it is ready.
4. Click **Approve & Lock** in the profile editor footer.

Once locked:
- The profile appears in the Operator Shell's scan profile list.
- All edit fields in the profile editor are disabled (a teal badge shows "Approved for Operators — Locked by {name}").
- To modify the profile, click **Unlock** (engineer/admin only), make changes, re-test, and re-approve.

> **If the Scan Profile list is empty in Operator Mode:** No profiles have been approved yet. An engineer must open a Scan Profile in the full UI, configure it, and click **Approve & Lock**.

### 20.6 Supervisor Override

If an engineer needs temporary access at an operator station without logging the technician out:

1. Click the **Supervisor Override** button (accessible from the operator station header).
2. Enter engineer or admin credentials in the overlay dialog.
3. If credentials are valid, temporary access is granted.
4. Access auto-reverts to the logged-in technician after **15 minutes**, or when the engineer clicks **End Override**.

All supervisor override events are logged to the audit log (Section 21.7).

---

## 23. Supported Hardware

### 21.1 Cameras

| Model | Sensor | Connection | Driver | Required SDK |
|---|---|---|---|---|
| Basler acA1920-155um | 1920×1200, mono | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Basler acA640-750um | 640×480, mono | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Basler acA2040-90um | 2040×1088, mono | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Basler acA1300-200um | 1280×1024, mono | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Any Basler USB3 Vision (mono or color) | varies | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Any Basler GigE Vision (mono or color) | varies | Gigabit Ethernet | `pypylon` | None (self-contained wheel) |
| Basler a2A1280-125umSWIR | 1280×1024, SWIR mono | USB 3.0 | `pypylon` | None (self-contained wheel) |
| Allied Vision Goldeye G-032 Cool | 636×508, SWIR/IR | GigE | `ni_imaqdx` | NI Vision Acquisition Software 2019+ (ICD bundled) |
| Photonfocus MV4-D1280U-H01-GT | 1280×1024, mono | GigE | `ni_imaqdx` | NI Vision Acquisition Software 2019+ (ICD bundled) |
| FLIR Boson 320 | 320×256, 14-bit IR | USB | `boson` | None (SDK bundled) |
| FLIR Boson 640 | 640×512, 14-bit IR | USB | `boson` | None (SDK bundled) |
| NI IMAQdx cameras | varies | USB / GigE / Camera Link | `ni_imaqdx` | NI Vision Acquisition Software 2019+ |
| DirectShow-compatible | varies | USB | `directshow` | None (Windows API) |
| Simulated | 512×512, synthetic (mono or color) | — | `simulated` | None |

> **pypylon:** The pypylon wheel bundles the pylon runtime internally — no separate Basler SDK install is required.
> **NI Vision Acquisition download:** [ni.com/downloads](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html)

#### RGB Color Camera Support *(v1.5.0)*

SanjINSIGHT supports RGB color cameras alongside traditional monochrome sensors. Enable color mode by setting `color_mode: true` in the camera section of `config.yaml`.

**Driver-specific behavior:**

| Driver | Color behavior |
|---|---|
| `pypylon` | Bayer demosaic is performed automatically by the pylon SDK for color Basler sensors. Frames arrive as (H, W, 3) RGB. |
| `directshow` | The driver converts BGR to RGB when `color_mode: true`. |
| `simulated` | Generates synthetic 3-channel RGB frames when `color_mode: true`. |
| `boson` / FLIR IR | Always monochrome. The `color_mode` setting is ignored. |

**Frame format:** `CameraFrame.data` is `(H, W)` for mono or `(H, W, 3)` for RGB. The `CameraFrame.channels` field reports 1 (mono) or 3 (RGB). `CameraInfo.pixel_format` is one of `"mono"`, `"bayer_rggb"`, `"rgb"`, or `"bgr"`.

> **Note:** Thermal (IR) cameras — Boson 320, Boson 640, and other microbolometers — are always monochrome regardless of `color_mode`. The setting applies only to visible-light cameras.

### 21.2 FLIR Boson Camera Setup

The FLIR Boson 320 and Boson 640 are USB-connected uncooled IR microbolometer cameras. They enumerate as two separate USB interfaces: a serial CDC control port (for SDK/FFC commands) and a UVC video device (for frame capture).

**Connection**

Plug the Boson into a USB 2.0 or USB 3.0 port using the supplied cable. Both interfaces appear automatically — no additional driver install is needed on Windows 10/11 or macOS.

**`serial_port` — serial control port**

The `serial_port` key selects the CDC serial interface used for SDK commands (FFC, gain mode, telemetry, etc.).

- **macOS:** Run `ls /dev/cu.usb*` in Terminal. The Boson CDC port typically appears as `/dev/cu.usbmodem*` or `/dev/cu.usbserial*`.
- **Windows:** Open **Device Manager → Ports (COM & LPT)**. Look for "FLIR Boson" or "CDC Serial Device". Note the `COM` number (e.g. `COM5`).

Set `serial_port` to this value in the Device Manager Connection Parameters or in `config.yaml`. If left blank, the driver operates in **video-only mode** — FFC and all SDK commands are unavailable, but frame capture works normally.

**`video_index` — UVC device index**

The `video_index` key is the integer index passed to `cv2.VideoCapture(index)` to select the Boson's UVC video device. The default is `0`. If multiple USB cameras are connected, enumerate them to find the correct index:

```python
import cv2
for i in range(10):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        print(i, cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
```

Set `video_index` to the index that matches the Boson's resolution (320 or 640 pixels wide).

**Video-only mode**

Leave `serial_port` blank to use the Boson without SDK control. The driver captures Y16 radiometric frames normally. FFC and telemetry features are disabled; no error is shown during connection.

**FFC (Flat Field Correction)**

FFC corrects non-uniformity across the sensor and should be run before measurements, especially after the camera has warmed up or the scene temperature has changed significantly. Trigger FFC via:

- **Camera panel** — click the **Run FFC** button in the Camera sub-tab (visible only when the connected camera supports FFC).
- **Device Manager** — select the Boson entry and click **Run FFC** in the action bar.
- **SDK** — call `driver.send_ffc()` from the scripting console or Python API.

**`config.yaml`**

```yaml
hardware:
  camera:
    driver: boson
    serial_port: ""          # CDC serial port; blank = video-only mode
    video_index: 0           # cv2.VideoCapture index for the UVC video device
    width: 320               # 320 (Boson 320) or 640 (Boson 640)
    height: 256              # 256 (Boson 320) or 512 (Boson 640)
    camera_type: ir          # must be "ir" for Boson cameras
```

### 21.3 Camera ICD Files (NI IMAQdx)

NI IMAQdx uses **camera interface descriptor** (`.icd`) and **instrument interface descriptor** (`.iid`) files to configure acquisition parameters for specific camera models. Without the correct ICD file, NI MAX may not recognise the camera or may not expose the full resolution and pixel format.

**Bundled cameras**

The following ICD/IID files are included in `assets/camera_icd/` in the SanjINSIGHT installation:

| Camera | File(s) |
|---|---|
| Basler a2A1280-125umSWIR | `basler_a2a1280_125um_swir.icd` |
| Allied Vision Goldeye G-032 Cool | `allied_vision_goldeye_g032.icd`, `allied_vision_goldeye_g032.iid` |
| Photonfocus MV4-D1280U-H01-GT | `photonfocus_mv4_d1280u.icd` |

**Windows installation**

1. Locate the ICD directory — typically `C:\Program Files\National Instruments\Vision\ICD\` (exact path depends on NI Vision Acquisition Software version; check NI MAX → Tools → NI-IMAQdx → Camera Files).
2. Copy the `.icd` and `.iid` files for your camera from `assets/camera_icd/` into that directory.
3. Restart **NI MAX**. The camera should now appear with its full model name and correct resolution options under **Devices and Interfaces**.

### 21.4 TEC Controllers

| Model | Manufacturer | Connection | Driver | Baud | Required Package |
|---|---|---|---|---|---|
| TEC-1089 | Meerstetter Engineering | USB (FTDI VCP) / RS-232 | `meerstetter` | 57 600 | `pyMeCom` |
| TEC-1123 | Meerstetter Engineering | USB (FTDI VCP) / RS-232 | `meerstetter` | 57 600 | `pyMeCom` |
| ATEC-302 | ATEC | RS-232 | `atec` | 9 600 | `pyserial` |
| Simulated | — | — | `simulated` | — | None |

> The Meerstetter protocol requires the FTDI VCP driver for USB connections. This driver is bundled with the SanjINSIGHT installer and installs silently during setup. If COM ports do not appear, download manually from [ftdichip.com/drivers/vcp-drivers](https://ftdichip.com/drivers/vcp-drivers/).

### 21.5 FPGA / Signal Generation

| Model | Manufacturer | Connection | Driver | Required Software |
|---|---|---|---|---|
| NI 9637 | National Instruments | PCIe / cRIO / Ethernet | `ni9637` | NI-RIO 19.0+; compiled `.lvbitx` bitfile |
| NI USB-6001 | National Instruments | USB | `ni9637` | NI-RIO 19.0+; compiled `.lvbitx` bitfile |
| BNC Model 745 | Berkeley Nucleonics | GPIB / USB / Serial | `bnc745` | PyVISA + NI-VISA (GPIB) or `pyvisa-py` (USB/Serial) |
| Simulated | — | — | `simulated` | None |

> **NI-RIO download:** [ni.com → NI-RIO](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html)
> The compiled bitfile (`.lvbitx`) is provided by Microsanj on the instrument USB key. The bitfile must match the NI-RIO version installed on the PC — if you upgrade NI-RIO, request a recompiled bitfile from Microsanj support.

> **BNC 745:** Replaces the NI-9637 in PT-100B transient test setups. Communicates via PyVISA — install with `pip install pyvisa pyvisa-py`. For GPIB connections, NI-VISA and a NI-GPIB-USB-HS adapter are recommended. Configure the VISA resource string in Device Manager (e.g. `GPIB::12` or `USB0::0x0A33::0x0021::...`). Supports continuous lock-in mode and single-shot transient mode.

### 21.6 Bias Sources

#### AMCAD BILT Pulsed I-V System

| Model | Manufacturer | Connection | Driver | Required Software |
|---|---|---|---|---|
| BILT (any module) | AMCAD Engineering | TCP/IP (Ethernet) | `amcad_bilt` | `pivserver64.exe` running on instrument PC |

The AMCAD BILT is a two-channel (Gate + Drain) pulsed voltage/current source for transistor characterisation. SanjINSIGHT communicates with it via TCP/SCPI to the companion `pivserver64.exe` Windows process (included with the AMCAD software package).

**Setup:** Start `pivserver64.exe -p 5035` on the instrument PC, then configure the IP address in Device Manager. If connection is blocked, add a Windows Firewall inbound rule for TCP port 5035. Default pulse parameters match the PIV1.txt configuration shipped with the Microsanj PT-100B kit.

#### Keithley SourceMeters (SCPI command set)

| Model | Connection | Driver |
|---|---|---|
| Keithley 2400 | GPIB / RS-232 | `keithley` |
| Keithley 2410 | GPIB | `keithley` |
| Keithley 2420 | GPIB | `keithley` |
| Keithley 2425 | GPIB | `keithley` |
| Keithley 2430 | GPIB | `keithley` |
| Keithley 2450 | USB / Ethernet / GPIB | `keithley` |

#### Keithley SourceMeters (TSP / Lua command set)

| Model | Connection | Driver |
|---|---|---|
| Keithley 2601 / 2602 | GPIB / Ethernet | `keithley` |
| Keithley 2611 / 2612 | GPIB / Ethernet | `keithley` |
| Keithley 2635 / 2636 | GPIB / Ethernet | `keithley` |

#### Generic VISA instruments

| Instrument | Connection | Driver | Notes |
|---|---|---|---|
| Rigol DP832 / DP831 | Ethernet / USB | `visa_generic` | Programmable DC supply |
| Agilent / Keysight B2900 series | GPIB / USB / Ethernet | `visa_generic` | SMU series |
| Rohde & Schwarz NGM / HMP series | Ethernet | `visa_generic` | Programmable supplies |
| Any IEEE 488.2 / SCPI instrument | GPIB / USB / Ethernet | `visa_generic` | Command overrides configurable in `config.yaml` |

> **VISA GPIB connections** require either NI-VISA + NI-GPIB-USB-HS adapter, or Keysight IO Libraries Suite + Keysight GPIB adapter. USB and Ethernet VISA instruments work with `pyvisa-py` only (no NI-VISA required).

### 21.7 Motorised Stages

#### Thorlabs (USB, via thorlabs-apt-device)

| Model | Axes | Driver | Notes |
|---|---|---|---|
| BBD302 | 3-axis (XYZ) | `thorlabs` | Brushless DC benchtop controller |
| KST101 | 1-axis | `thorlabs` | Stepper motor controller |
| KDC101 | 1-axis | `thorlabs` | DC servo motor controller |
| TDC001 | 1-axis | `thorlabs` | DC servo motor controller |
| MPC320 | 1-axis | `thorlabs` | Motorised polariser controller |

#### Serial stages (RS-232 / USB-CDC, multi-dialect)

| Model | Manufacturer | Dialect | Baud | Driver |
|---|---|---|---|---|
| ProScan III | Prior Scientific | `prior` | 9 600 | `serial_stage` |
| ES111 / H128 | Prior Scientific | `prior` | 9 600 | `serial_stage` |
| MAC5000 | Ludl Electronic Products | `ludl` | 9 600 | `serial_stage` |
| BioPrecision2 | Ludl Electronic Products | `ludl` | 9 600 | `serial_stage` |
| MS-2000 | Applied Scientific Instrumentation (ASI) | `asi` | 9 600 | `serial_stage` |
| Tiger controller | Applied Scientific Instrumentation (ASI) | `asi` | 115 200 | `serial_stage` |
| TANGO | Marzhauser Wetzlar | `marzhauser` | 57 600 | `serial_stage` |

#### Prober stations

| Model | Manufacturer | Connection | Driver |
|---|---|---|---|
| Semi-automatic prober | MPI Corporation | RS-232 (115 200 baud) | `mpi_prober` |

### 21.8 Objective Turret

| Controller | Manufacturer | Connection | Driver | Baud |
|---|---|---|---|---|
| LINX (Arduino-based) | Olympus / custom | USB-CDC | `olympus_linx` | 115 200 |

### 21.9 SDK and Driver Version Reference

| Software | Minimum Version | Recommended | Notes |
|---|---|---|---|
| Windows | 10 build 17763 (Oct 2018) | Windows 11 | — |
| NI-RIO | 19.0 (2019) | Latest | Bitfile must match installed version |
| NI Vision Acquisition Software | 2019 | Latest | Includes NI-IMAQdx |
| NI-VISA | 19.0 | Latest | Required for GPIB instruments |
| Basler Pylon SDK | — | — | **Not required** — pypylon bundles the pylon runtime in its wheel. No OS-level Basler SDK install needed. |
| FLIR Boson SDK | — | — | **Not required** — the Boson 3.0 Python SDK is bundled in the installer (`hardware/cameras/boson/`). No separate download needed. |
| Thorlabs Kinesis | 1.14 | Latest | Required for Thorlabs USB stages |
| FTDI VCP Driver | 2.12 | Latest | Bundled with the SanjINSIGHT installer; installs silently during setup |
| PyVISA | 1.13 | **Latest** | Required for BNC 745 (GPIB/USB/Serial). Install: `pip install pyvisa pyvisa-py` |
| AMCAD PIV software | 2019+ | Latest | Includes `pivserver64.exe` required for AMCAD BILT |

---

## 24. Configuration File Reference

`config.yaml` is located in the application installation directory. Edit it with a plain-text editor if you need to make changes outside the wizard.

```yaml
hardware:

  camera:
    driver: pypylon          # pypylon | boson | ni_imaqdx | directshow | simulated
    serial: ""               # Basler serial number (blank = first found)
    camera_name: ""          # NI IMAQdx camera name (e.g. "cam4")
    color_mode: false        # true = enable RGB color output (pypylon, directshow, simulated)

    # boson driver keys (used when driver: boson)
    serial_port: ""          # CDC serial port for SDK/FFC commands (blank = video-only mode)
    video_index: 0           # cv2.VideoCapture index for UVC video device
    width: 320               # 320 (Boson 320) or 640 (Boson 640)
    height: 256              # 256 (Boson 320) or 512 (Boson 640)
    camera_type: tr          # "tr" (thermoreflectance) or "ir" (infrared); set "ir" for Boson

  fpga:
    driver: ni9637           # ni9637 | simulated
    bitfile: ""              # Absolute path to .lvbitx firmware file
    resource: RIO0           # NI resource string (e.g. RIO0, rio://host/RIO0)

  tec_meerstetter:
    driver: meerstetter       # meerstetter | simulated
    port: COM3                # Serial port
    address: 2                # Meerstetter device address
    baudrate: 57600

  tec_atec:
    driver: atec              # atec | simulated
    port: COM4
    address: 1
    baudrate: 9600

  stage:
    driver: simulated         # thorlabs | prior | serial | simulated

  bias:
    driver: simulated         # keithley | visa_generic | simulated

acquisition:
  default_n_frames: 16        # Frames/half for new acquisitions
  default_exposure_us: 5000   # Default exposure (microseconds)
  default_gain_db: 0          # Default camera gain
  inter_phase_delay_s: 0.1    # Delay between cold and hot phases
  preflight_enabled: true     # Run pre-capture validation before each acquisition

logging:
  level: INFO                 # INFO | DEBUG
  log_to_file: false          # Write to logs/microsanj.log
  log_file: logs/microsanj.log
```

---

## 25. Keyboard Shortcuts

**Acquisition**

| Shortcut | Action |
|---|---|
| **Ctrl+R** | Run acquisition (Capture — Single) |
| **Esc** | Abort current acquisition or scan |
| **F5** | Start live ΔR/R preview |
| **F6** | Stop live preview |
| **F7** | Freeze / resume live display |
| **F8** | Run hotspot analysis on current result |
| **F9** | Start or abort grid scan |

**Navigation**

| Shortcut | Action |
|---|---|
| **Ctrl+L** | Switch to Live View |
| **Ctrl+Shift+S** | Switch to Capture — Grid Scan |
| **Ctrl+1** | Capture panel (single acquisition) |
| **Ctrl+2** | Camera panel (Hardware group) |
| **Ctrl+3** | Temperature panel (Hardware group) |
| **Ctrl+4** | Stage panel (Hardware group) |
| **Ctrl+5** | Analysis panel |
| **Ctrl+K** | Command Palette (search all panels) |

**Application**

| Shortcut | Action |
|---|---|
| **Ctrl+D** | Device Manager |
| **Ctrl+Shift+H** | Hardware Setup Wizard |
| **Ctrl+,** | Settings |
| **Ctrl+.** | Emergency stop (immediate) |
| **Ctrl+`** | Toggle Bottom Drawer (Console / Log) |
| **Ctrl+?** | Keyboard Shortcut overlay |

---

## 26. Troubleshooting

### Connected Devices button shows a red indicator after startup

1. Click the **Connected Devices** button in the top-right of the header to open the device status popup. Individual devices with a red dot (● red) are disconnected or faulted.
2. Open **Device Manager** (Ctrl+D), select the affected device, and click **Reconnect**.
3. If it fails, open **Hardware Setup** (Ctrl+Shift+H) and verify the driver selection, port, and resource string.
4. Confirm the hardware SDK is installed (see §2.2).

### Camera not detected

- Verify the camera appears in Basler Pylon Viewer (pypylon) or NI MAX (IMAQdx).
- On USB cameras, try a different USB 3.0 port or cable.
- Ensure no other application (e.g. Pylon Viewer) has exclusive access to the camera.

### Camera shows SATURATION warning or CLIPPED

- The **SATURATION** readout in the Camera panel is amber (near saturation, > 3900 / 4095) or red "CLIPPED ✗" (at full 12-bit saturation, 4095).
- Reduce **Exposure** in the Camera panel, or lower the illumination intensity.
- Pixel values at 4095 are clipped; ΔR/R data in those pixels is invalid.

### TEC not stabilising during calibration

- Increase **Max settle time** (up to 300 s for slow thermals).
- Loosen **Stable tolerance** (e.g. 0.5 °C if the TEC is noisy).
- Check physical connections: TEC power leads, thermistor wiring.
- Verify the COM port is not in use by another application.
- The TEC-1089 requires external DC power (12–36 V) to respond to serial commands. USB only powers the FTDI serial chip — the TEC processor does not boot without DC input.
- The FTDI VCP driver is bundled with the SanjINSIGHT installer (v1.5.0-beta.1+). If the TEC does not appear as a COM port, reinstall SanjINSIGHT or download the FTDI driver from [ftdichip.com](https://ftdichip.com/drivers/vcp-drivers/).

### FPGA not found / bitfile error

- Confirm NI-RIO drivers are installed and the cRIO/DAQ is visible in NI MAX.
- Match the **resource string** exactly to NI MAX (right-click the device → Properties).
- Ensure the `.lvbitx` bitfile was compiled for the correct FPGA model and NI-RIO version.

### Stage shows "NOT HOMED"

- Open the **Stage** panel (Hardware group in the left sidebar).
- Click **⌂ Home All** at the bottom of the Stage panel to set the reference position on all axes.
- Use **⌂ Home XY** or **⌂ Home Z** if you only need to home specific axes.
- The Readiness Banner in the Acquire tab will show a "Stage homed" warning until homing is complete; click its **Fix it →** button to jump directly to the Stage panel.

### FPGA duty cycle warning appears

- The duty cycle warning (amber label) appears when duty cycle ≥ 50 %.
- It turns red when duty cycle ≥ 80 % — reduce the duty cycle immediately to prevent DUT overheating.
- For time-resolved measurements, the recommended range is 25–35 %.

### ΔT shows "—" or is absent

- No calibration is applied. Go to **Calibration → 📂 Load .cal → ✓ Apply to Acquisitions**.

### Image appears noisy

- Increase **Frames/half** for more averaging.
- Increase **EMA depth** in Live view.
- Check for vibration (reduce stage settle time if overshooting, or increase settle time if under-damped).
- Verify illumination stability — laser power fluctuations add noise.

### AI Assistant shows no response / no model

- Go to **Settings** (Ctrl+,) → **AI Assistant** tab and click **Download Model**.
- The download is ~2–5 GB and runs in the background. Progress is displayed in the Settings panel.
- Once complete, the AI Assistant activates automatically.

### PDF report fails to generate

- Ensure `reportlab` is installed: `pip install reportlab`.

### Application shows update badge on every launch

- Check network connectivity; the updater contacts the GitHub API.
- Verify the system clock is set correctly (TLS certificate validation).

### Basler TR camera not found

- Ensure Basler Pylon 8 SDK is installed and the camera appears in Pylon Viewer.
- Verify `pypylon` is installed: `pip install pypylon`.
- Check USB 3.0 connection; try a different port.

### Microsanj IR camera not found

- Ensure the **FLIR Spinnaker SDK** is installed: [flir.com/spinnaker-sdk](https://www.flir.com/products/spinnaker-sdk/). After installing the SDK, run `pip install spinnaker_python` (the wheel file ships inside the SDK package).
- If the Device Manager shows "spinnaker_python not found", the `pip install` step was skipped — run it from a command prompt and then restart SanjINSIGHT.
- Check the USB 3.0 connection; try a different port. The camera requires USB 3.0 (not USB 2.0) for reliable operation.
- Ensure no other application (e.g. a video conference app) has exclusive access to the camera.
- Run **Test Camera** in the Hardware Setup Wizard (Ctrl+Shift+H → Camera page) to confirm the camera is detected by the Spinnaker driver.

### NI IMAQdx camera not found

- Ensure **NI Vision Acquisition Software** is installed: [ni.com → NI-VAS](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html).
- Open **NI MAX** and verify the camera appears under **Devices and Interfaces** with the expected name (e.g. `cam4`).
- The device name in `config.yaml` (`hardware.camera.camera_name`) must match the NI MAX name exactly.
- If the Device Manager error says "niimaqdx.dll not found", NI Vision Acquisition Software is not installed or has been partially uninstalled.

### Device Manager shows an error with a bullet-point message

Starting from v1.2.8, SanjINSIGHT validates all required software dependencies before attempting to connect any device. The error dialog shows an actionable message explaining exactly what is missing (e.g. "nifpga not found — install NI-RIO") along with installation instructions. Follow the instructions in the error dialog, then click **Reconnect** in the Device Manager to retry.

### Login screen appears even though require_login is off

- This happens only on first launch when no admin account exists yet. Complete the Admin Setup Wizard to create the admin account; subsequent launches will not require login until `require_login` is enabled in Settings → Security.

### Scan Profile list is empty in Operator Mode

- No scan profiles have been approved yet. An engineer must open a Scan Profile in the full UI (Scan Profiles panel in the sidebar), configure and test it, then click **Approve & Lock**. Only locked profiles appear in Operator Mode.

### "Administrator login required" tooltip on a setting

- The setting is admin-only. Click **Log in** in the top-right header, enter admin credentials, and the control will unlock.

### Login locked out for 5 minutes

- After 5 consecutive failed login attempts the account is locked for 5 minutes. Wait for the countdown to expire, then try again with the correct credentials.

---

## 27. Technical Reference

### 25.1 Acquisition Data Structures

**AcquisitionResult**

| Field | Type | Description |
|---|---|---|
| `cold_avg` | float64 ndarray (H×W or H×W×3) | Averaged cold-phase frame |
| `hot_avg` | float64 ndarray (H×W or H×W×3) | Averaged hot-phase frame |
| `delta_r_over_r` | float64 ndarray (H×W or H×W×3) | ΔR/R = (hot − cold) / cold |
| `difference` | float64 ndarray | Hot − cold difference image |
| `snr_db` | float | Estimated SNR in dB |
| `exposure_us` | float | Exposure time (µs) |
| `gain_db` | float | Camera gain (dB) |
| `n_frames` | int | Total frames averaged |
| `duration_s` | float | Acquisition wall time (s) |
| `timestamp` | float | Unix timestamp |
| `dark_pixel_count` | int | Pixels masked as dark/noise |
| `dark_pixel_fraction` | float | Fraction of dark pixels (0.0–1.0) |

> **v1.5.0 change:** All averaged arrays are now float64 (previously float32). The H×W×3 shape applies when the source camera is RGB.

**ScanResult**

| Field | Type | Description |
|---|---|---|
| `drr_map` | float32 ndarray | Stitched ΔR/R map |
| `dt_map` | float32 ndarray or None | Stitched ΔT map (if calibration applied) |
| `tile_results` | list | `AcquisitionResult` per tile |
| `positions` | list of (x, y) | Stage positions in µm, scan order |
| `n_cols, n_rows` | int | Grid dimensions |
| `tile_w, tile_h` | int | Pixels per tile |
| `step_x_um, step_y_um` | float | Grid spacing (µm) |
| `duration_s` | float | Total scan time (s) |
| `valid` | bool | True if scan completed successfully |

**CalibrationResult**

| Field | Type | Description |
|---|---|---|
| `ct_map` | float32 ndarray | C_T coefficient per pixel (K⁻¹) |
| `r2_map` | float32 ndarray | R² goodness-of-fit per pixel (0–1) |
| `residual_map` | float32 ndarray | RMS residual of linear fit |
| `mask` | bool ndarray | True where C_T is reliable (R² ≥ threshold) |
| `n_points` | int | Temperature steps used |
| `t_min, t_max` | float | Temperature range (°C) |
| `t_ref` | float | Reference temperature (°C) |
| `frame_h, frame_w` | int | Image dimensions |
| `timestamp` | float | Unix timestamp |
| `valid` | bool | True if fit succeeded |

### 25.2 Diagnostic Rules

The diagnostic engine evaluates the following rules on every `MetricsService` snapshot. Rules are organised in evaluation order.

**R-series — Readiness gates**

| Rule ID | Name | Trigger |
|---|---|---|
| R1 | Camera connected | Camera not connected |
| R3 | Stage homed | Stage present but not homed |
| R4 | TEC N stable | Enabled TEC Δ > 0.10 °C (warn) or Δ > 0.20 °C (fail) |
| R5 | TEC N temp range | TEC setpoint outside 10–150 °C |

**C-series — Camera signal quality**

| Rule ID | Name | Trigger |
|---|---|---|
| C1 | Pixel saturation | Clipped pixels > 0.2 % (warn) or > 1.0 % (fail) |
| C2 | Underexposure | Near-black pixels > 5 % (warn) or > 15 % (fail) |
| C3 | Pixel headroom | Max pixel ≥ 3900 (warn) or = 4095 (fail) |

**F-series — Focus and motion**

| Rule ID | Name | Trigger |
|---|---|---|
| F1 | Focus quality | Laplacian variance < 100 (warn) or < 40 (fail) |
| F2 | Frame drift | Normalised inter-frame drift > 0.02 (warn) or > 0.05 (fail) |
| M1 | Stage stationary | Stage is moving during acquisition |

**L-series — FPGA / modulation**

| Rule ID | Name | Trigger |
|---|---|---|
| L1 | Modulation running | FPGA not running |
| L2 | Sync locked | FPGA running but sync not locked |

**T-series — Thermal safety**

| Rule ID | Name | Trigger |
|---|---|---|
| T1 | Duty cycle thermal risk | FPGA duty cycle ≥ 50 % (warn) or ≥ 80 % (fail) |

### 25.3 LiveConfig Parameters

| Parameter | Range | Default | Description |
|---|---|---|---|
| `frames_per_half` | 1–64 | 4 | Frames per cold/hot half-cycle |
| `accumulation` | 1–256 | 16 | EMA smoothing depth |
| `trigger_mode` | `fpga` / `software` | `fpga` | Phase-lock signal source |
| `trigger_delay_ms` | 0–100 | 5 | Delay from trigger edge to first frame (ms) |
| `display_fps` | 1–30 | 10 | Maximum UI refresh rate |
| `roi_x, roi_y` | 0–(W−1), 0–(H−1) | 0, 0 | ROI top-left origin |
| `roi_w, roi_h` | 0–W, 0–H | 0, 0 | ROI size (0 = full frame) |

### 25.4 File Locations

| Item | Location |
|---|---|
| Configuration | `config.yaml` (application directory) |
| Sessions | `%USERPROFILE%\.microsanj_sessions\` |
| Material profiles | `%USERPROFILE%\.microsanj\profiles\` |
| Application log | `logs\microsanj.log` (if enabled in Settings) |
| AI model | `%USERPROFILE%\.microsanj\models\` |
| First-run sentinel | `.first_run_complete` (application directory) |
| User database | `%USERPROFILE%\.microsanj\users.db` (SQLite) |
| Audit log | `%USERPROFILE%\.microsanj\audit.log` (JSON Lines, 5 MB rotation) |
| Per-user preferences | `%USERPROFILE%\.microsanj\users\{uid}\prefs.json` |

### 25.5 Thread Architecture

| Thread | Purpose | Poll rate |
|---|---|---|
| GUI thread | All UI rendering and user interaction | — |
| Camera thread | Continuous frame grab | Camera frame rate |
| TEC threads (×2) | Temperature setpoint and readback | 0.5 Hz |
| FPGA thread | Lock-in status and frequency readback | 0.25 Hz |
| Bias thread | Output voltage/current readback | 0.25 Hz |
| Stage thread | Position readback and move command queue | 10 Hz |
| **MetricsService thread** | Aggregates all hardware state into a unified snapshot for diagnostic rules and AI context | 2 Hz |
| Acquisition thread | Hot/cold frame capture (daemon) | Per acquisition |
| Scan thread | Multi-tile scan loop (daemon) | Per tile |
| Calibration thread | TEC stepping and capture loop (daemon) | Per temperature step |
| AI inference thread | Language model token generation (daemon) | Per query |

All cross-thread communication uses Qt signals (queued connections) or `app_state` context managers. Hardware drivers are never called from the GUI thread directly.

---

*Copyright © 2026 Microsanj, LLC. All Rights Reserved.*
*For support, use **Help → Get Support…** in the application, or contact [software-support@microsanj.com](mailto:software-support@microsanj.com)*
