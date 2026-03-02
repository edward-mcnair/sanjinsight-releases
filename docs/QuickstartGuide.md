# SanjINSIGHT — Quick Start Guide

**Microsanj SanjINSIGHT v1.0.0**
*Get from first launch to your first thermoreflectance measurement in minutes.*

---

## 1. Install

1. Download `SanjINSIGHT-Setup-{version}.exe` from the [Releases page](https://github.com/edward-mcnair/sanjinsight/releases).
2. Run the installer and follow the on-screen prompts.
3. Install the required hardware SDK drivers **before** launching the app:
   - **Basler camera:** [Pylon SDK](https://www.baslerweb.com/en/downloads/software-downloads/) (USB3 or GigE)
   - **NI FPGA / DAQ:** [NI-RIO drivers](https://www.ni.com/downloads/) (NI 9637 / USB-6001)
   - **NI IMAQdx camera:** Included with NI Vision Acquisition Software

---

## 2. First Launch — Hardware Setup Wizard

On first launch, the **Hardware Setup Wizard** opens automatically and walks you through connecting each piece of hardware. It runs a background device scan and pre-fills fields where hardware is detected.

> **Tip:** You can re-open this wizard at any time via **Help → Hardware Setup…** (Ctrl+Shift+H).

### Step-by-step

| Page | What to do |
|---|---|
| **Welcome** | Wait a few seconds for the auto-scan to complete. A status message shows how many devices were found. |
| **TEC Controllers** | Confirm or select the COM port for each TEC (Meerstetter and/or ATEC). The dropdown shows detected ports with a green ✓ badge. Use "simulated" if no TEC is connected. |
| **Camera** | Choose the driver: **pypylon** (Basler USB3/GigE), **ni_imaqdx** (NI camera), or **simulated**. If auto-scan found a camera, the serial number or camera name is pre-filled. |
| **FPGA** | Choose **ni9637** and browse to the FPGA bitfile (`.lvbitx`). Enter the resource string (e.g. `RIO0`). Use **simulated** for software-only use. |
| **Finish** | Review your settings and click **Finish**. The configuration is saved to `config.yaml`. |

---

## 3. Application Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Logo  │  ● Cam  ● TEC1  ● TEC2  ● FPGA  ● Bias  ● Stage  │ ■ STOP │
├──────────────────────────────────────────────────────────────────────┤
│ Sidebar │                   Main Panel                               │
│         │  (Live / Scan / Calibration / Acquire / Camera / Temp …)  │
└──────────────────────────────────────────────────────────────────────┘
```

- **Status dots** (top bar) — Cyan = connected, Red = disconnected.
- **■ STOP** — Emergency stop for all hardware. Click once to arm (turns amber), click again to trigger, or press **Ctrl+.** to trigger immediately.
- **Sidebar** — Click any section to open the corresponding panel.
- **Mode toggle** — Switch between **Standard** (guided wizard) and **Advanced** (full controls) in the top bar.

---

## 4. Core Workflows

### A — Live View (real-time ΔR/R streaming)

1. Open **Live** from the sidebar (or press **Ctrl+L**).
2. In the left panel, set **Frames/half** (4 is a good starting point) and **EMA depth** (16 for smooth display).
3. Click **▶ Start**. The centre canvas shows a live ΔR/R map updating at the rate set by **Display fps**.
4. Move your mouse over the image to read the ΔR/R value and ΔT (if a calibration is loaded) in the right panel.
5. Click **❄ Freeze** to pause the display, **📷 Capture** to save the current frame, **■ Stop** to end streaming.

### B — Single Acquisition

1. Open **Acquire** from the sidebar (or press **Ctrl+R** to run immediately).
2. Set **Exposure**, **Gain**, and **Frames/half** in the left panel.
3. Click **▶ Run Sequence** (or **Ctrl+R**). The pipeline captures cold and hot frames, computes ΔR/R, and displays the result.
4. Click **💾 Save Session** to save to HDF5, or **🖼 Save Image** to export a PNG.

### C — Grid Scan (large-area map)

1. Open **Scan** from the sidebar (or press **Ctrl+Shift+S**).
2. Set the grid: **Columns**, **Rows**, and **Step X / Step Y** (µm).
   The summary label shows the estimated FOV and scan duration before you start.
3. Enable **Snake scan** (default) for efficient boustrophedon travel.
4. Click **▶ Start Scan**. The button animates (⠙ Scanning…) while running.
   The right panel shows the live stitched map as each tile is acquired.
5. When complete, export using **💾 Save Map**, **🖼 Save Image**, or **📄 PDF Report**.

### D — Calibration (measure C_T)

> *Calibration converts ΔR/R into temperature (ΔT). Run this once per sample type / illumination wavelength.*

1. Open **Calibration** from the sidebar.
2. Click a preset (**5-pt** is recommended) or add your own temperatures with **+ Add**.
3. Set **Avg frames/step** (20) and **Max settle time** (30 s).
4. Click **▶ Run Calibration**. The TEC steps through each temperature; the app waits for stability before capturing.
5. Review the **C_T Map** and **R² Map**. High R² (close to 1.0, white) = reliable pixels.
6. Click **💾 Save .cal** then **✓ Apply to Acquisitions** to enable ΔT display across all tabs.

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

| Shortcut | Action |
|---|---|
| **Ctrl+R** | Run acquisition sequence |
| **Esc** | Abort current acquisition |
| **Ctrl+L** | Switch to Live view |
| **Ctrl+Shift+S** | Switch to Scan view |
| **Ctrl+1–5** | Switch sidebar panel |
| **Ctrl+D** | Open Device Manager |
| **Ctrl+Shift+H** | Open Hardware Setup wizard |
| **Ctrl+,** | Open Settings |
| **Ctrl+.** | Emergency stop (immediate) |

---

## 7. Troubleshooting

| Problem | Check |
|---|---|
| Status dot stays red | Open **Device Manager** (⚙ icon or Ctrl+D) and click **Reconnect**. Verify driver and port in **Hardware Setup** (Ctrl+Shift+H). |
| Camera not found | Ensure Pylon or NI Vision is installed and the camera appears in its own companion software. |
| TEC not stabilising | Increase **Max settle time** in Calibration settings. Check physical TEC connections. |
| FPGA not found | Confirm NI-RIO drivers are installed and the resource string matches NI MAX (e.g. `RIO0`). |
| ΔT always shows "—" | Load and apply a calibration file: **Calibration → 📂 Load .cal → ✓ Apply**. |
| Update badge appears | Click the badge or go to **Help → Check for Updates…** to download the latest installer. |

---

## 8. Getting Help

- **Documentation:** [docs.microsanj.com/sanjinsight](https://docs.microsanj.com/sanjinsight)
- **Support:** [support@microsanj.com](mailto:support@microsanj.com)
- **Releases:** [github.com/edward-mcnair/sanjinsight/releases](https://github.com/edward-mcnair/sanjinsight/releases)

---

*Copyright © 2026 Microsanj, LLC. All Rights Reserved.*
