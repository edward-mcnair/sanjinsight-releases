# SanjINSIGHT User Manual

**Microsanj SanjINSIGHT v1.0.0**
**Document revision: 2026-03-01**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation](#2-installation)
3. [Hardware Setup Wizard](#3-hardware-setup-wizard)
4. [Application Overview](#4-application-overview)
5. [Device Status & Emergency Stop](#5-device-status--emergency-stop)
6. [Live View](#6-live-view)
7. [Acquisition](#7-acquisition)
8. [Grid Scan](#8-grid-scan)
9. [Calibration](#9-calibration)
10. [Saving and Exporting Data](#10-saving-and-exporting-data)
11. [Device Manager](#11-device-manager)
12. [Settings](#12-settings)
13. [Supported Hardware](#13-supported-hardware)
14. [Configuration File Reference](#14-configuration-file-reference)
15. [Keyboard Shortcuts](#15-keyboard-shortcuts)
16. [Troubleshooting](#16-troubleshooting)
17. [Technical Reference](#17-technical-reference)

---

## 1. Introduction

### 1.1 What is SanjINSIGHT?

SanjINSIGHT is the instrument control and data-acquisition software for the **Microsanj EZ-500** and related thermoreflectance imaging systems. It provides a complete workflow for:

- **Real-time thermoreflectance streaming** — continuous live ΔR/R display with EMA smoothing
- **Single-shot acquisition** — averaged hot/cold frame capture with instant ΔR/R computation
- **Large-area grid scanning** — automated stage-driven multi-tile mapping stitched into a single composite image
- **Thermoreflectance calibration** — TEC-stepped measurement of the C_T coefficient map, enabling conversion of ΔR/R into temperature change (ΔT)

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

The application measures ΔR/R by alternating the device under test (DUT) between two bias states ("cold" and "hot") synchronised with the camera via an FPGA lock-in reference signal. C_T is determined by the Calibration workflow (Section 9). Once C_T is known, ΔT = ΔR/R ÷ C_T.

### 1.3 Modes of Operation

| Mode | Access | Best for |
|---|---|---|
| **Standard** | Toggle in top bar | Step-by-step guided measurement; new users |
| **Advanced** | Toggle in top bar | Full independent control of all panels and parameters |

---

## 2. Installation

### 2.1 System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 (64-bit) | Windows 11 (64-bit) |
| CPU | 4-core, 2.5 GHz | 8-core, 3.5 GHz |
| RAM | 8 GB | 32 GB |
| Disk | 2 GB free | SSD with 50 GB free |
| USB | USB 3.0 | USB 3.1 Gen 1 |
| Display | 1920×1080 | 2560×1440 |

### 2.2 Software Prerequisites

Install these before running SanjINSIGHT:

| Driver | Required for | Download |
|---|---|---|
| **Basler Pylon SDK** | Basler USB3 or GigE cameras | [baslerweb.com/downloads](https://www.baslerweb.com/en/downloads/software-downloads/) |
| **NI-RIO Drivers** | NI 9637 FPGA / USB-6001 DAQ | [ni.com/downloads](https://www.ni.com/downloads/) |
| **NI Vision Acquisition Software** | NI IMAQdx cameras | Included with NI Vision |
| **FTDI CDM Drivers** | Meerstetter TEC via USB | Usually auto-installed by Windows |

### 2.3 Installing SanjINSIGHT

1. Download `SanjINSIGHT-Setup-{version}.exe` from the [Releases page](https://github.com/edward-mcnair/sanjinsight/releases).
2. Double-click the installer and follow the prompts (administrator rights required).
3. The installer places a shortcut on the Desktop and in the Start Menu.
4. Launch **SanjINSIGHT** — the Hardware Setup Wizard opens automatically on the first run.

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

### 3.2 Page 1 — Welcome

Displays a brief overview of the system. The scan status label updates as each hardware class is checked. Wait for "Scan complete — N devices found" before clicking **Next**, or click through immediately if you prefer to configure manually.

### 3.3 Page 2 — TEC Controllers

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

### 3.4 Page 3 — Camera

| Field | Options | Notes |
|---|---|---|
| Driver | `pypylon` / `ni_imaqdx` / `directshow` / `simulated` | |
| Serial number | Text field | Basler pypylon only — leave blank for first found |
| Camera name | Text field | NI IMAQdx only — e.g. `cam4` |

> **pypylon** — Requires Basler Pylon SDK. Supports acA1920-155um and acA640-750um.
> **ni_imaqdx** — Requires NI Vision Acquisition Software. Camera name is shown in NI MAX.
> **simulated** — Generates synthetic frames; no hardware needed.

### 3.5 Page 4 — FPGA

| Field | Options | Notes |
|---|---|---|
| Driver | `ni9637` / `simulated` | |
| Bitfile | File path (Browse…) | Path to compiled `.lvbitx` firmware |
| Resource | Text field | NI resource string, e.g. `RIO0` or `rio://hostname/RIO0` |

The resource string is visible in **NI MAX → Devices and Interfaces**. Common values:

- `RIO0` — Locally connected CompactRIO
- `rio://192.168.1.1/RIO0` — Network CompactRIO
- `Dev1` — USB-6001 DAQ fallback

### 3.6 Page 5 — Summary & Finish

Review all settings. Click **Finish** to write `config.yaml` and close the wizard. Click **Back** to revise any page. Click **Cancel** to leave the existing `config.yaml` unchanged.

After finishing, hardware drivers are initialised. Status dots in the top bar reflect the connection result.

---

## 4. Application Overview

### 4.1 Top Bar

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [Microsanj logo]  SanjINSIGHT       Standard ◉ Advanced               │
│  ● Cam  ● TEC1  ● TEC2  ● FPGA  ● Bias  ● Stage      ⚙   ■ STOP  [v] │
└──────────────────────────────────────────────────────────────────────────┘
```

| Element | Description |
|---|---|
| **Logo** | Microsanj branding |
| **Standard / Advanced toggle** | Switch the main view mode |
| **Status dots (●)** | Cyan = connected and responding; Red = disconnected or error |
| **⚙ (Device Manager)** | Open Device Manager dialog |
| **■ STOP** | Emergency stop button — see Section 5 |
| **[v] badge** | Version update available — click to download |

### 4.2 Sidebar (Advanced Mode)

The sidebar on the left lists all available panels. Click a panel name to open it:

| Panel | Shortcut | Purpose |
|---|---|---|
| **Acquire** | Ctrl+1 | Single-shot acquisition and result display |
| **Live** | Ctrl+2 (or Ctrl+L) | Real-time ΔR/R streaming |
| **Scan** | Ctrl+3 (or Ctrl+Shift+S) | Automated grid scan mapping |
| **Calibration** | Ctrl+4 | C_T coefficient measurement |
| **Camera** | Ctrl+2 | Camera settings and raw preview |
| **Temperature** | Ctrl+3 | TEC setpoints and temperature history |
| **Stage** | Ctrl+4 | Manual stage jogging and position readout |
| **Analysis** | Ctrl+5 | Post-acquisition analysis tools |
| **Device Manager** | Ctrl+D | Hardware connection management |

### 4.3 Menu Bar

**Acquisition**
- **▶ Run Sequence** (Ctrl+R) — Capture cold and hot frames and compute ΔR/R
- **■ Abort** (Esc) — Stop the active acquisition or scan
- **Live Mode** (Ctrl+L) — Switch to the Live panel
- **Scan Mode** (Ctrl+Shift+S) — Switch to the Scan panel

**View**
- Panels Ctrl+1 through Ctrl+5 (see sidebar list above)
- **Device Manager** (Ctrl+D)

**Help**
- **About SanjINSIGHT…** — Version, build date, licence
- **Check for Updates…** — Compare against latest release on GitHub
- **Hardware Setup…** (Ctrl+Shift+H) — Re-run the hardware wizard
- **Settings** (Ctrl+,) — Application preferences

### 4.4 Status Bar

The status bar at the bottom of the window shows:
- Application version
- Connection summary (e.g. "3/6 devices connected")
- Active camera model
- Frame counter and exposure time during acquisition

---

## 5. Device Status & Emergency Stop

### 5.1 Status Indicators

Each hardware class has a coloured status dot in the top bar:

| Colour | Meaning |
|---|---|
| **Cyan** | Connected and communicating normally |
| **Red** | Not found, disconnected, or driver error |
| **Amber** | Connected but in a warning state (e.g. TEC temperature out of range) |

Hover over a dot to see the detailed status tooltip.

### 5.2 Emergency Stop

The **■ STOP** button is a two-step hardware safety mechanism.

1. **Click once** — Button turns amber; the system is "armed". A confirmation message is displayed.
2. **Click again** — Emergency stop is triggered. All active hardware output is disabled immediately: TEC setpoints are cleared, bias output is switched off, and any running acquisition or scan is aborted.

**Keyboard shortcut:** Press **Ctrl+.** at any time to trigger the emergency stop in a single step, bypassing the arm stage.

To resume after an emergency stop, reconnect devices via the Device Manager (⚙).

---

## 6. Live View

### 6.1 Overview

The Live tab provides continuous real-time thermoreflectance display. Frames alternate between a cold phase and a hot phase; the difference is computed on-the-fly and smoothed with an exponential moving average (EMA).

### 6.2 Toolbar

| Button | Action |
|---|---|
| **▶ Start** | Begin streaming. Button animates (⠙ Streaming…) while active. |
| **■ Stop** | End streaming and release camera. |
| **❄ Freeze** | Pause display update without stopping capture. Button changes to ▶ Resume. |
| **📷 Capture** | Save the currently displayed frame to disk. |
| **↺ Reset EMA** | Restart the exponential moving average accumulator (clears the smoothed image). |

### 6.3 Left Panel — Live Settings

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

### 6.4 Centre Panel — Live Canvas

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

### 6.5 Right Panel — Readouts

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

## 7. Acquisition

### 7.1 Overview

The Acquire panel captures a complete measurement: N cold frames and N hot frames are averaged, ΔR/R is computed, and the result is displayed. This is the standard workflow for a single measurement point.

### 7.2 Controls

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

### 7.3 Running an Acquisition

1. Configure exposure, gain, and frames/half in the left panel.
2. Click **▶ Run Sequence** or press **Ctrl+R**.
3. The status bar shows progress (frame N of M).
4. When complete, the ΔR/R map appears in the right panel.
5. If a calibration is applied, the ΔT map tab is also populated.

Press **Esc** or click **■ Abort** to cancel a running acquisition.

### 7.4 Result Display

| Tab | Content |
|---|---|
| **ΔR/R Map** | Computed thermoreflectance signal map |
| **ΔT Map** | Temperature change map (requires calibration) |
| **Stats** | Min, max, mean, std, SNR, duration, frame count |

---

## 8. Grid Scan

### 8.1 Overview

The Scan panel automates a stage-driven grid acquisition, stepping the sample through a rectangular array of positions, capturing a tile at each point, and stitching all tiles into a single large-area map.

### 8.2 Left Panel — Scan Configuration

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

### 8.3 Right Panel — Map Viewer & Statistics

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

### 8.4 Scan Workflow (Internal)

For each tile (row-major, or snake-order if enabled):

1. **Move** — Stage positions to tile (x, y) coordinates.
2. **Settle** — Wait the configured settle time for mechanical vibrations to damp out.
3. **Acquire** — Capture N cold and N hot frames.
4. **Stitch** — Composite the tile result into the running ΔR/R map preview.
5. Update progress bar and log.

After all tiles complete: final stitching pass, enable export buttons.

### 8.5 Export

| Button | Output format | Description |
|---|---|---|
| **💾 Save Map** | `.npy` | NumPy float32 array for Python post-processing |
| **🖼 Save Image** | `.png` | Raster image of the stitched ΔR/R map |
| **📄 PDF Report** | `.pdf` | Multi-page PDF: maps, statistics, scan metadata |
| **◈ Save as Profile** | (profile store) | Save the ΔR/R map as a material profile for future reference |

---

## 9. Calibration

### 9.1 Overview

Calibration measures the thermoreflectance coefficient **C_T** (units: K⁻¹) on a pixel-by-pixel basis. The TEC steps the sample through a range of temperatures; at each step, the app captures a ΔR/R map. A linear regression of ΔR/R vs. ΔT at each pixel yields C_T and R² (fit quality).

Once applied, C_T is used by all other panels (Live, Acquire, Scan) to display ΔT = ΔR/R ÷ C_T.

### 9.2 Left Panel — Calibration Setup

#### Temperature Sequence

Click a preset to populate the list quickly:

| Preset | Points | Range (°C) |
|---|---|---|
| **3-pt** | 3 | 25, 35, 45 |
| **5-pt** | 5 | 25, 30, 35, 40, 45 |
| **7-pt** | 7 | 25, 28, 31, 34, 37, 40, 43 |

Or build a custom sequence:
- Adjust the value in any row's spinbox (−20 to +100 °C).
- Click **+ Add** to append a new point.
- Click **✕** on any row to delete it.
- Temperatures are automatically sorted before the run begins.

> **Minimum 2 temperature points required.** For best accuracy, use at least 5 points spanning ≥ 15 °C.

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
| **■ Abort** | Stop after the current temperature step. |
| **Progress bar** | 0–100 % across all steps |
| **Step label** | "Step N / M — [state]" |

### 9.3 Right Panel — Calibration Results

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

**Calibration File (Group Box)**

| Button | Action |
|---|---|
| **💾 Save .cal** | Save the full calibration result to a `.npz` file |
| **📂 Load .cal** | Load a previously saved calibration |
| **✓ Apply to Acquisitions** | Mark this calibration as active — enables ΔT display in Live, Acquire, and Scan panels |

### 9.4 Calibration Workflow

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

---

## 10. Saving and Exporting Data

### 10.1 Session Storage

When you save a session, a folder is created under `~\.microsanj_sessions\` containing:

```
20260301_143022_device_A/
  session.json      — Human-readable metadata (exposure, gain, TEC temp, etc.)
  cold_avg.npy      — Averaged cold frames (float32)
  hot_avg.npy       — Averaged hot frames (float32)
  delta_r_over_r.npy — ΔR/R signal map (float32)
  difference.npy    — Raw (hot − cold) difference (float32)
  thumbnail.png     — Small PNG preview
```

### 10.2 Export Formats

| Format | Extension | Description | Compatible with |
|---|---|---|---|
| **HDF5** | `.h5` | All arrays and metadata in a single hierarchical file | Python (h5py), MATLAB, HDFView |
| **NumPy** | `.npy` / `.npz` | Native NumPy format | Python (numpy.load) |
| **TIFF** | `.tiff` | 32-bit floating-point, ImageJ/FIJI compatible | ImageJ, FIJI, Olympus, any TIFF reader |
| **CSV** | `.csv` | Tab-separated X (µm), Y (µm), ΔT (°C) | Excel, MATLAB, any spreadsheet |
| **MATLAB** | `.mat` | MATLAB binary format | MATLAB R2006b+ |
| **PNG** | `.png` | 8-bit colormapped raster image | Any image viewer |
| **PDF** | `.pdf` | Multi-page report with maps and statistics | Adobe Reader, any PDF viewer |

### 10.3 Calibration Files

Calibration files (`.npz`) contain:

- `ct_map` — C_T coefficient map (float32, pixels × K⁻¹)
- `r2_map` — R² quality map (float32, 0–1)
- `residual_map` — RMS residual map (float32)
- `mask` — Boolean reliability mask
- Metadata: temperature range, reference temperature, timestamp, frame dimensions

Load a calibration with **📂 Load .cal** in the Calibration panel, then click **✓ Apply to Acquisitions**.

---

## 11. Device Manager

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

> **Note:** Changes to driver type or port require re-running the Hardware Setup wizard (Ctrl+Shift+H) and restarting the application.

---

## 12. Settings

Open with **Help → Settings** or **Ctrl+,**.

| Setting | Description |
|---|---|
| **Update check** | Enable/disable automatic update checks on startup |
| **Log to file** | Enable writing the application log to `logs/microsanj.log` |
| **Log level** | `INFO` (default) or `DEBUG` (verbose; for troubleshooting) |
| **Mode on startup** | Standard or Advanced |

---

## 13. Supported Hardware

### Cameras

| Model | Connection | Driver | Notes |
|---|---|---|---|
| Basler acA1920-155um | USB 3.0 | `pypylon` | 1920×1200 @ 155 fps; primary imaging sensor |
| Basler acA640-750um | USB 3.0 | `pypylon` | 640×480 @ 750 fps; high-speed transient capture |
| Basler GigE (any) | Ethernet | `pypylon` | GigE Vision; requires compatible NIC |
| NI IMAQdx cameras | Various | `ni_imaqdx` | Requires NI Vision Acquisition Software |
| Simulated | — | `simulated` | Generates synthetic test frames |

### TEC Controllers

| Model | Manufacturer | Connection | Driver | Baud |
|---|---|---|---|---|
| TEC-1089 | Meerstetter | USB (FTDI) / RS-232 | `meerstetter` | 57 600 |
| TEC-1123 | Meerstetter | USB (FTDI) / RS-232 | `meerstetter` | 57 600 |
| ATEC-302 | Arroyo Instruments | RS-232 | `atec` | 9 600 |

### FPGA / DAQ

| Model | Manufacturer | Connection | Driver | Notes |
|---|---|---|---|---|
| NI 9637 | National Instruments | PCIe / cRIO | `ni9637` | Requires NI-RIO drivers and compiled `.lvbitx` bitfile |
| NI USB-6001 | National Instruments | USB | `ni9637` | Lower bandwidth; bench/fallback configuration |

### Stage Controllers

| Model | Manufacturer | Connection | Driver |
|---|---|---|---|
| BSC203 | Thorlabs | USB | `thorlabs` |
| MPC320 | Thorlabs | USB | `thorlabs` |
| ProScan III | Prior Scientific | RS-232 | `prior` |

### Bias Sources

| Model | Manufacturer | Connection | Driver |
|---|---|---|---|
| Keithley 2400 | Keithley | GPIB / RS-232 | `keithley` |
| Keithley 2450 | Keithley | USB | `keithley` |
| Rigol DP832 | Rigol | Ethernet | `visa_generic` |
| Any VISA instrument | — | GPIB / USB / Ethernet | `visa_generic` |

---

## 14. Configuration File Reference

`config.yaml` is located in the application installation directory. Edit it with a plain-text editor if you need to make changes outside the wizard.

```yaml
hardware:

  camera:
    driver: pypylon          # pypylon | ni_imaqdx | directshow | simulated
    serial: ""               # Basler serial number (blank = first found)
    camera_name: ""          # NI IMAQdx camera name (e.g. "cam4")

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

logging:
  level: INFO                 # INFO | DEBUG
  log_to_file: false          # Write to logs/microsanj.log
  log_file: logs/microsanj.log
```

---

## 15. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **Ctrl+R** | Run acquisition sequence |
| **Esc** | Abort current acquisition or scan |
| **Ctrl+L** | Switch to Live view |
| **Ctrl+Shift+S** | Switch to Scan view |
| **Ctrl+1** | Acquire panel |
| **Ctrl+2** | Camera panel |
| **Ctrl+3** | Temperature panel |
| **Ctrl+4** | Stage panel |
| **Ctrl+5** | Analysis panel |
| **Ctrl+D** | Device Manager |
| **Ctrl+Shift+H** | Hardware Setup wizard |
| **Ctrl+,** | Settings |
| **Ctrl+.** | Emergency stop (immediate, bypasses arm stage) |

---

## 16. Troubleshooting

### Status dot stays red after startup

1. Open **Device Manager** (⚙ or Ctrl+D).
2. Select the affected device and click **Reconnect**.
3. If it fails, open **Hardware Setup** (Ctrl+Shift+H) and verify the driver selection, port, and resource string.
4. Confirm the hardware SDK is installed (see Section 2.2).

### Camera not detected

- Verify the camera appears in Basler Pylon Viewer (pypylon) or NI MAX (IMAQdx).
- On USB cameras, try a different USB 3.0 port or cable.
- Ensure no other application (e.g. Pylon Viewer) has exclusive access to the camera.

### TEC not stabilising during calibration

- Increase **Max settle time** (up to 300 s for slow thermals).
- Loosen **Stable tolerance** (e.g. 0.5 °C if the TEC is noisy).
- Check physical connections: TEC power leads, thermistor wiring.
- Verify the COM port is not in use by another application.

### FPGA not found / bitfile error

- Confirm NI-RIO drivers are installed and the cRIO/DAQ is visible in NI MAX.
- Match the **resource string** exactly to NI MAX (right-click the device → Properties).
- Ensure the `.lvbitx` bitfile was compiled for the correct FPGA model and NI-RIO version.

### ΔT shows "—" or is absent

- No calibration is applied. Go to **Calibration → 📂 Load .cal → ✓ Apply to Acquisitions**.

### Image appears noisy

- Increase **Frames/half** for more averaging.
- Increase **EMA depth** in Live view.
- Check for vibration (reduce stage settle time if overshooting, or increase settle time if under-damped).
- Verify illumination stability — laser power fluctuations add noise.

### PDF report fails to generate

- Ensure `reportlab` is installed: `pip install reportlab`.

### Application shows update badge on every launch

- Check network connectivity; the updater contacts the GitHub API.
- Verify the system clock is set correctly (TLS certificate validation).

---

## 17. Technical Reference

### 17.1 Acquisition Data Structures

**AcquisitionResult**

| Field | Type | Description |
|---|---|---|
| `cold_avg` | float32 ndarray | Averaged cold-phase frame |
| `hot_avg` | float32 ndarray | Averaged hot-phase frame |
| `delta_r_over_r` | float32 ndarray | ΔR/R = (hot − cold) / cold |
| `snr_db` | float | Estimated SNR in dB |
| `exposure_us` | float | Exposure time (µs) |
| `gain_db` | float | Camera gain (dB) |
| `n_frames` | int | Total frames averaged |
| `duration_s` | float | Acquisition wall time (s) |
| `timestamp` | float | Unix timestamp |
| `valid` | bool | True if acquisition succeeded |

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

### 17.2 LiveConfig Parameters

| Parameter | Range | Default | Description |
|---|---|---|---|
| `frames_per_half` | 1–64 | 4 | Frames per cold/hot half-cycle |
| `accumulation` | 1–256 | 16 | EMA smoothing depth |
| `trigger_mode` | `fpga` / `software` | `fpga` | Phase-lock signal source |
| `trigger_delay_ms` | 0–100 | 5 | Delay from trigger edge to first frame (ms) |
| `display_fps` | 1–30 | 10 | Maximum UI refresh rate |
| `roi_x, roi_y` | 0–(W−1), 0–(H−1) | 0, 0 | ROI top-left origin |
| `roi_w, roi_h` | 0–W, 0–H | 0, 0 | ROI size (0 = full frame) |

### 17.3 File Locations

| Item | Location |
|---|---|
| Configuration | `config.yaml` (application directory) |
| Sessions | `%USERPROFILE%\.microsanj_sessions\` |
| Material profiles | `%USERPROFILE%\.microsanj\profiles\` |
| Application log | `logs\microsanj.log` (if enabled in Settings) |
| First-run sentinel | `.first_run_complete` (application directory) |

### 17.4 Thread Architecture

| Thread | Purpose | Poll rate |
|---|---|---|
| GUI thread | All UI rendering and user interaction | — |
| Camera thread | Continuous frame grab | Camera frame rate |
| TEC threads (×2) | Temperature setpoint and readback | 0.5 Hz |
| FPGA thread | Lock-in status and frequency readback | 0.25 Hz |
| Bias thread | Output voltage/current readback | 0.25 Hz |
| Stage thread | Position readback and move command queue | 10 Hz |
| Acquisition thread | Hot/cold frame capture (daemon) | Per acquisition |
| Scan thread | Multi-tile scan loop (daemon) | Per tile |
| Calibration thread | TEC stepping and capture loop (daemon) | Per temperature step |

All cross-thread communication uses Qt signals (queued connections) or `app_state` context managers. Hardware drivers are never called from the GUI thread directly.

---

*Copyright © 2026 Microsanj, LLC. All Rights Reserved.*
*For support, contact [support@microsanj.com](mailto:support@microsanj.com)*
