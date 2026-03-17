# SanjINSIGHT — Quick Start Guide

**Microsanj SanjINSIGHT v1.3.0**
*Get from first launch to your first thermoreflectance measurement in minutes.*

---

## Before You Begin — Requirements

| | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10 64-bit (build 17763+) | Windows 11 64-bit |
| **CPU** | 4-core, 2.5 GHz | 8-core, 3.5 GHz |
| **RAM** | 8 GB (16 GB with AI) | 32 GB |
| **Disk** | 4 GB free | SSD, 50 GB free |
| **USB** | USB 3.0 × 2 | USB 3.0 × 4 |
| **GPU** | Not required | NVIDIA RTX 4070+ (12 GB VRAM) |

> **Windows version:** Press **Win+R** → type `winver` → press Enter. Build number must be **17763 or higher**.

> **NUC / mini-PC:** Supported for USB cameras and network-attached FPGA. Not suitable for PCIe-connected NI hardware. See the User Manual §2.1 for details.

---

## 1. Install

### Step 1 — Run the SanjINSIGHT installer

Download `SanjINSIGHT-Setup-{version}.exe` from the [Releases page](https://github.com/edward-mcnair/sanjinsight-releases/releases) and run it.

The installer bundles everything SanjINSIGHT needs to run — Python, all Python packages, and the application itself. No separate Python installation is required.

### Step 2 — Install camera and hardware drivers

The installer cannot bundle OS-level hardware drivers. Install these **before** launching SanjINSIGHT for the first time:

| Driver | Required for | Where to get it |
|---|---|---|
| **NI-RIO** | FPGA (NI 9637) | [ni.com → Drivers → NI-RIO](https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html) |
| **NI Vision Acquisition Software** | Camera (NI IMAQdx) | [ni.com → Drivers → NI-VAS](https://www.ni.com/en/support/downloads/drivers/download.ni-vision-acquisition-software.html) |
| **NI-VISA** | Keithley bias source | [ni.com → Drivers → NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |
| **Basler Pylon 8 SDK** | Basler TR camera | [baslerweb.com/downloads](https://www.baslerweb.com/en-us/downloads/software/) |
| **FLIR Spinnaker SDK** | Microsanj IR camera | [flir.com/spinnaker-sdk](https://www.flir.com/products/spinnaker-sdk/) — then `pip install spinnaker_python` (wheel ships inside the SDK package) |

> **NI drivers:** NI-RIO and NI Vision Acquisition Software both require a restart after installation; NI-VISA does not. You can install all three NI packages first and then restart once — you do not need to restart between each NI install.

> **Camera SDKs** do not require a restart. Install both if you have both cameras. If you only have one camera type, install only the relevant SDK.

> **USB-to-serial adapters (TEC, stage, turret):** Windows 11 usually installs FTDI and Prolific drivers automatically. If a COM port does not appear in Device Manager after plugging in the cable, download the driver manually from [ftdichip.com](https://ftdichip.com/drivers/vcp-drivers/).

### Step 3 — Copy the FPGA bitfile

Copy the FPGA firmware file (supplied on the Microsanj USB key) to a permanent location:

```
C:\Microsanj\firmware\ez500firmware.lvbitx
```

Create the folder if it does not exist. The Hardware Setup Wizard will ask for this path on first launch.

### Step 4 — Download the AI model (optional)

The AI Assistant requires a language model file (~2–5 GB). Go to **Settings → AI Assistant** and click **Download Model**. The download runs in the background and a progress bar is shown. The assistant is disabled until this is complete, but all other functions work without it.

### Installation checklist

```
□ Run SanjINSIGHT-Setup.exe
□ Install NI-RIO                               ← do NOT restart yet
□ Install NI Vision Acquisition Software       ← do NOT restart yet
□ Install NI-VISA                              ← no restart needed
□ Restart PC once (satisfies NI-RIO + NI-VAS restart requirements)
□ Install Basler Pylon 8 SDK         (Basler TR camera systems only)
□ Install FLIR Spinnaker SDK +
    pip install spinnaker_python      (Microsanj IR camera systems only)
□ Copy FPGA bitfile → C:\Microsanj\firmware\ez500firmware.lvbitx
□ Launch SanjINSIGHT → complete Admin Setup (first time only)
□ Complete Hardware Setup Wizard
□ Settings → AI Assistant → Download Model  (optional)
```

---

## 2. First Launch

### Admin account setup (one-time)

The very first time SanjINSIGHT starts, the **Admin Setup** screen appears. This creates the administrator account that controls who can use the system and what they can change.

1. Enter a display name, username, and password (confirmed twice).
2. Click **Create Account**. The account is created and you are logged in automatically.
3. The **Hardware Setup Wizard** opens immediately after.
4. When the wizard closes, the **License Activation** prompt appears:
   - **Activate License** — paste the key supplied by Microsanj and click **Activate License**. The application unlocks full hardware access on success.
   - **Continue in Demo Mode** — skip activation and run with simulated hardware. You can enter a key at any time via **Help → License…**

> You only see the Admin Setup screen once. You only see the License Activation prompt once — on the first launch without a stored key.

### Hardware Setup Wizard

After admin setup, the **Hardware Setup Wizard** opens and walks you through connecting each piece of hardware. It runs a background device scan and pre-fills fields where hardware is detected. The wizard has 8 pages:

| Page | What to do |
|---|---|
| **1 — Welcome** | Wait a few seconds for the auto-scan to complete. A status message shows how many devices were found. |
| **2 — TEC Controllers** | Confirm or select the COM port for each TEC (Meerstetter and/or ATEC). Use "simulated" if no TEC is connected. |
| **3 — Camera** | Choose the driver: **pypylon** (Basler TR camera), **Microsanj IR Camera** (IR thermography camera), **ni_imaqdx** (NI camera), or **simulated**. If auto-scan found a camera, the serial number is pre-filled. |
| **4 — FPGA** | Choose **ni9637** and browse to the FPGA bitfile (`.lvbitx`). Enter the resource string (e.g. `RIO0`). Use **simulated** for software-only use. |
| **5 — Bias Source** | Select the bias source type and connection port. Use **simulated** if no bias source is connected. |
| **6 — Stage** | Select the motorised stage type and serial port. Use **simulated** if no stage is connected. |
| **7 — AI Assistant** | Optionally start the AI model download. This can also be done later via Settings. |
| **8 — Done** | Review your settings and click **Finish**. The configuration is saved to `config.yaml`. |

> **Microsanj IR Camera:** If you select this driver and the Spinnaker SDK is not yet installed, an amber install notice appears with a direct download link. Install the SDK, then click **Test Camera** to verify.

> **Tip:** You can re-open this wizard at any time via **Help → Hardware Setup…** (Ctrl+Shift+H).

---

## 3. Application Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Logo  │                                │ [● Devices ▼] │ [User] │ ■ STOP│
├───────────────────────────────────────────────────────────────────────────┤
│ Sidebar │                    Main Panel                                    │
│         │  (AutoScan / Live / Capture / Transient / …)                    │
├───────────────────────────────────────────────────────────────────────────┤
│ [▶ Console / Log]                                                          │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Connected Devices button** (top right) — Shows the overall hardware connection state. Click it to expand a popup listing every configured device with its individual status dot (● cyan = connected, ● red = error/disconnected). Click **Manage devices…** in the popup footer to open the Device Manager.
- **■ STOP** — Emergency stop for all hardware. Press **Ctrl+.** to trigger immediately.
- **User display** — Shows the logged-in user name and a Log out button when a session is active.
- **Sidebar** — Groups panels by function. Click any item to open it. The **Hardware** group is collapsible.
- **Bottom Drawer** — A toggle bar at the very bottom of the window. Click it (or press **Ctrl+`**) to reveal the Console and Log tabs for debugging output.

### Left Sidebar Structure

| Section | Panels |
|---|---|
| **ACQUIRE** | AutoScan★, Live★, Capture★ (Single / Grid sub-tabs), Transient (Time-Resolved / Burst sub-tabs) |
| **ANALYZE** | Calibration, Analysis★, Sessions, Compare, 3D Surface |
| **Hardware** *(collapsible ▸)* | Camera (Camera / ROI / Autofocus sub-tabs), Stimulus (Modulation / Bias Source sub-tabs), Temperature, Stage, Prober |
| **LIBRARY** | Profiles (Material Profiles / Scan Profiles sub-tabs) |
| **Settings** | |

★ = most commonly used panels

> **Tip:** Press **Ctrl+K** to open the Command Palette and search for any panel by name.

### AI Assistant Panel

The **AI Assistant** is accessible from the ANALYZE section. It shows:
- A **readiness grade** (A–D) based on all live diagnostic checks
- Up to 5 active issues with one-click **"Fix it →"** navigation to the relevant hardware panel
- **Explain this tab** and **Diagnose** quick-action buttons
- A free-form chat interface for instrument questions

---

## 4. Core Workflows

### A — AutoScan (recommended starting point)

AutoScan is the guided, single-screen workflow for new users and routine measurements.

1. Open **AutoScan** from the sidebar (ACQUIRE section, marked ★).
2. In the left panel, configure the scan objective, sample type, and measurement parameters.
3. The right panel shows a live camera view with a readiness indicator. When "● READY", proceed.
4. Click **▶ Start AutoScan**. The system captures, computes ΔR/R, and shows the result inline.
5. Add tags or notes in the metadata strip, then export or save the session.

### B — Live View (real-time ΔR/R streaming)

1. Open **Live** from the sidebar (or press **Ctrl+L**).
2. In the left panel, set **Frames/half** (4 is a good starting point) and **EMA depth** (16 for smooth display).
3. Click **▶ Start** (or press **F5**). The centre canvas shows a live ΔR/R map updating in real time.
4. Move your mouse over the image to read the ΔR/R value and ΔT (if a calibration is loaded) in the right panel.
5. Press **F7** to freeze the display, **F6** to stop streaming.

### C — Single Acquisition (Capture)

1. Open **Capture** from the sidebar (or press **Ctrl+1**) and select the **Single** sub-tab.
2. Check the **readiness banner** at the top. A green "● READY TO ACQUIRE" means all checks pass. If it shows amber "NOT READY — N issues", click any **Fix it →** link to jump to the relevant panel.
3. Set **Exposure**, **Gain**, and **Frames/half** in the left panel.
4. Click **▶ Run Sequence** (or **Ctrl+R**). The pipeline captures cold and hot frames, computes ΔR/R, and displays the result.
5. Click **💾 Save Session** to save to HDF5, or **🖼 Save Image** to export a PNG.

### D — Grid Scan (large-area map)

1. Open **Capture** from the sidebar and select the **Grid** sub-tab (or press **Ctrl+Shift+S**).
2. Set the grid: **Columns**, **Rows**, and **Step X / Step Y** (µm).
   The summary label shows the estimated FOV and scan duration before you start.
3. Enable **Snake scan** (default) for efficient boustrophedon travel.
4. Click **▶ Start Scan** (or press **F9**). The right panel shows the live stitched map as each tile is acquired.
5. When complete, export using **💾 Save Map**, **🖼 Save Image**, or **📄 PDF Report**.

### E — Transient Capture

1. Open **Transient** from the sidebar (ACQUIRE section).
2. For **time-resolved** measurements (phase-locked): select the **Time-Resolved** sub-tab, set delay range and steps, then click **Run**.
3. For **burst/movie** measurements: select the **Burst** sub-tab, set frame count and rate, then click **Run**.
4. Export results as a NumPy array (`.npy`), HDF5, or TIFF image stack.

### F — Calibration (measure C_T)

> *Calibration converts ΔR/R into temperature (ΔT). Run this once per sample type / illumination wavelength.*

1. Open **Calibration** from the sidebar (ANALYZE section).
2. Click a preset to populate the temperature sequence:
   - **5-pt** (25–45 °C) — quick check for known samples
   - **TR Std** (20, 40, 60, 80, 100, 120 °C) — standard 6-point sweep per Microsanj protocol (~12 min)
   - **IR Std** (85–115 °C) — 7-point sweep for IR camera calibration
3. Set **Avg frames/step** (20) and **Max settle time** (30 s). The estimated run time updates live below the preset buttons.
4. Click **▶ Run Calibration**. The TEC steps through each temperature; the app waits for stability before capturing.
5. Review the **C_T Map** and **R² Map**. High R² (close to 1.0, white) = reliable pixels.
6. Click **💾 Save .cal** then **✓ Apply to Acquisitions** to enable ΔT display across all tabs.

### G — Compare Sessions

1. Open **Compare** from the sidebar (ANALYZE section).
2. Use the two session pickers to load a **Baseline** session and a **Test** session.
3. The panel shows both ΔR/R maps side-by-side with a synchronised cursor and a statistics comparison table.
4. Use the **Difference map** toggle to highlight areas that changed between sessions.

### H — 3D Surface

1. Open **3D Surface** from the sidebar (ANALYZE section).
2. Data is loaded automatically after any acquisition. To load a different session, use the session picker.
3. Adjust **Z-stretch** (1–200×) to exaggerate small thermal variations.
4. Use the **Elevation** and **Azimuth** sliders to rotate the view, or click **Auto-rotate** for continuous animation.
5. Enable **Show threshold plane** and set a threshold value to highlight hotspots above a specific ΔR/R level.
6. Click **Export…** to save a PNG or PDF of the current view.

### I — AI-Assisted Diagnostics

1. Open the **AI Assistant** panel from the sidebar (ANALYZE section).
2. The **grade badge** (A–D) reflects the current instrument state:
   - **A** (green) — All checks passed
   - **B** (light green) — Minor warnings; review but can proceed
   - **C** (amber) — Significant issue; address before acquiring
   - **D** (red) — Critical failure; acquisition will be unreliable
3. Click any listed issue to jump to the affected hardware panel.
4. Click **Diagnose** for a plain-language summary of all active problems and how to fix each.
5. Click **Explain this tab** to get context-aware guidance for whichever panel is currently open.
6. Type any question in the chat box and press **Ask** (e.g. "What LED wavelength should I use for GaAs?").

> **First use:** The AI requires a local language model. Go to **Settings → AI Assistant** and click **Download Model** to fetch the model (~2–5 GB). The download runs in the background and shows progress in Settings.

### J — Operator Mode (Technician users)

Operator Mode is a simplified interface for technicians who run repeatably against approved scan profiles. It is presented automatically when a **Technician** account logs in.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Logo  │  Operator Mode  │  Jane Smith [OP]  │  12 scans · 91% pass   │
├──────────────┬─────────────────────────────┬───────────────────────────┤
│ Scan Profile │      Live Camera View       │  Shift Log                │
│ (approved    │                             │  ✓ SN-001  09:14  PASS    │
│  profiles    │  [Part ID / Serial #]       │  ✗ SN-002  09:22  FAIL    │
│  only)       │                             │  ✓ SN-003  09:31  PASS    │
│              │  [  ▶  START SCAN  ]        │                           │
└──────────────┴─────────────────────────────┴───────────────────────────┘
```

1. Log in as a Technician user (or have the admin create one).
2. Select a scan profile from the left panel (only profiles approved by an engineer appear).
3. Scan or type the part serial number in the **Part ID** field.
4. Click **▶ START SCAN** (or press Enter if a barcode scanner is connected).
5. A full-screen **PASS / FAIL / REVIEW** result is shown after each scan.
6. Results are logged automatically to the Shift Log and exported as a PDF report.

> **Supervisors:** If an engineer needs temporary access at an operator station, click the **Supervisor Override** button to enter engineer credentials. Access auto-reverts after 15 minutes.

---

## 5. Saving & Exporting Results

| Button | Output | Use for |
|---|---|---|
| 💾 Save Session | `.h5` (HDF5) | Full dataset + metadata in one file |
| 🖼 Save Image | `.png` | Quick visual record |
| 📄 PDF Report | `.pdf` | Formal report with stats and maps |
| 💾 Save Map | `.npy` | NumPy array for Python post-processing |
| 💾 Save .cal | `.npz` | Calibration file (C_T map + R² map) |

---

## 6. Keyboard Shortcuts

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
| **Ctrl+D** | Open Device Manager |
| **Ctrl+Shift+H** | Open Hardware Setup Wizard |
| **Ctrl+,** | Open Settings |
| **Ctrl+.** | Emergency stop (immediate) |
| **Ctrl+`** | Toggle Bottom Drawer (Console / Log) |
| **Ctrl+?** | Keyboard Shortcut overlay |

---

## 7. Troubleshooting

| Problem | Check |
|---|---|
| Connected Devices button shows red | Click the button to see which device is red. Open **Device Manager** (Ctrl+D) and click **Reconnect**. Verify driver and port in **Hardware Setup** (Ctrl+Shift+H). |
| Basler TR camera not found | Ensure Basler Pylon 8 SDK is installed and the camera appears in the Pylon Viewer. |
| Microsanj IR camera not found | Ensure the FLIR Spinnaker SDK is installed and run `pip install spinnaker_python`. Check USB connection. Run **Test Camera** in the Hardware Setup Wizard. |
| TEC not stabilising | Increase **Max settle time** in Calibration settings. Check physical TEC connections. |
| FPGA not found | Confirm NI-RIO drivers are installed and the resource string matches NI MAX (e.g. `RIO0`). |
| ΔT always shows "—" | Load and apply a calibration file: **Calibration → 📂 Load .cal → ✓ Apply**. |
| Stage shows "NOT HOMED" | Open the **Stage** panel (Hardware group) and click **⌂ Home All** to set the reference position. |
| FPGA duty cycle warning | Duty cycle ≥ 50 % risks DUT overheating (amber). Reduce in the **Stimulus → Modulation** sub-tab. ≥ 80 % turns red — reduce immediately. |
| AI Assistant shows no model | Go to **Settings → AI Assistant** and click **Download Model** (~2–5 GB). |
| Scan Profile list is empty (Operator Mode) | No profiles have been approved yet. An engineer must open a Scan Profile in the full UI and click **Approve & Lock**. |
| "Administrator login required" tooltip | Log in as an admin user to unlock those settings. |
| Update badge appears on every launch | Click the badge or go to **Help → Check for Updates…** to download the latest installer. |

---

## 8. Getting Help

- **Documentation:** [docs.microsanj.com/sanjinsight](https://docs.microsanj.com/sanjinsight)
- **Support:** [software-support@microsanj.com](mailto:software-support@microsanj.com) — or use **Help → Get Support…** in the application for a pre-filled email with diagnostic data attached
- **Releases:** [github.com/edward-mcnair/sanjinsight-releases/releases](https://github.com/edward-mcnair/sanjinsight-releases/releases)

---

*Copyright © 2026 Microsanj, LLC. All Rights Reserved.*
