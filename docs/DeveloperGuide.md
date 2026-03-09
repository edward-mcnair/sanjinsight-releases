# SanjINSIGHT — Developer Guide

**Version**: 1.1.2
**Platform**: Windows 10/11 (64-bit); macOS/Linux supported for development
**Stack**: Python 3.11 · PyQt5 · NumPy · PyInstaller · Inno Setup
**Repository**: Private source (`edward-mcnair/sanjinsight`) · Public releases (`edward-mcnair/sanjinsight-releases`)

---

## Table of Contents

1. [What the Software Does](#1-what-the-software-does)
2. [Repository Layout](#2-repository-layout)
3. [Architecture Overview](#3-architecture-overview)
4. [Hardware Layer](#4-hardware-layer)
5. [Acquisition Pipeline](#5-acquisition-pipeline)
6. [User Interface](#6-user-interface)
7. [AI Assistant & Diagnostics](#7-ai-assistant--diagnostics)
8. [License System](#8-license-system)
9. [Configuration & Preferences](#9-configuration--preferences)
10. [Session Management](#10-session-management)
11. [Update System](#11-update-system)
12. [Event Bus & Logging](#12-event-bus--logging)
13. [Thread Safety Model](#13-thread-safety-model)
14. [Data Flow Diagrams](#14-data-flow-diagrams)
15. [Build & Release Pipeline](#15-build--release-pipeline)
16. [Testing](#16-testing)
17. [Adding a New Hardware Driver](#17-adding-a-new-hardware-driver)
18. [Adding a New UI Tab](#18-adding-a-new-ui-tab)
19. [Key Design Decisions](#19-key-design-decisions)
20. [Dependency Reference](#20-dependency-reference)

---

## 1. What the Software Does

SanjINSIGHT is the instrument control and data-acquisition application for the **Microsanj EZ-500** thermoreflectance imaging system. Thermoreflectance is a technique that maps surface temperature by measuring tiny changes in optical reflectance (ΔR/R ≈ 10⁻⁴ to 10⁻²) caused by heating.

The software:

- **Controls hardware** — cameras, TEC temperature controllers, FPGA modulation sources, bias/SMU supplies, motorized stages, objective turrets, and laser-diode drivers
- **Acquires thermoreflectance data** — captures hot-phase and cold-phase image stacks, averages them, and computes ΔR/R images
- **Manages sessions** — saves every measurement as a structured directory of JSON metadata and NumPy arrays
- **Provides analysis tools** — colormap display, ROI selection, hotspot detection, calibration, tiling scans, multi-session comparison
- **Exports results** — TIFF, HDF5, NumPy, CSV, MATLAB, and PDF
- **Runs an AI assistant** — powered by a local LLM or cloud providers (Claude, ChatGPT), with real-time diagnostic grading

---

## 2. Repository Layout

```
sanjinsight/
│
├── main_app.py                ← Application entry point; MainWindow class
├── version.py                 ← Single source of truth for version, URLs, repo names
├── updater.py                 ← GitHub Releases update checker
├── config.py                  ← YAML system config + JSON user preferences
├── utils.py                   ← Shared helpers (safe_call, etc.)
├── logging_config.py          ← Rotating file + console logging setup
├── requirements.txt           ← pip dependencies
│
├── hardware/                  ← All device drivers
│   ├── app_state.py           ← Thread-safe ApplicationState singleton
│   ├── hardware_service.py    ← Owns all devices; runs background poll threads
│   ├── device_manager.py      ← State machine (ABSENT → DISCOVERING → CONNECTED)
│   ├── device_scanner.py      ← Parallel hardware discovery (serial/USB/camera/NI/network)
│   ├── device_registry.py     ← Known-device metadata (VID/PID, display name, etc.)
│   ├── requirements_resolver.py ← Pre-flight readiness checks (OP_ACQUIRE, OP_SCAN)
│   ├── thermal_guard.py       ← TEC safety monitor (alarm thresholds)
│   ├── port_lock.py           ← Serial port mutual exclusion
│   ├── driver_store.py        ← Driver instance cache
│   ├── hardware_preset_manager.py ← Named hardware config profiles
│   │
│   ├── cameras/               ← CameraDriver implementations
│   ├── tec/                   ← TecDriver implementations
│   ├── fpga/                  ← FpgaDriver implementations
│   ├── bias/                  ← BiasDriver implementations
│   ├── stage/                 ← StageDriver implementations
│   ├── autofocus/             ← AutofocusDriver implementations
│   ├── turret/                ← ObjectiveTurretDriver implementations
│   └── ldd/                   ← LddDriver (laser diode) implementations
│
├── acquisition/               ← Measurement pipeline and data model
│   ├── pipeline.py            ← Hot/cold capture + ΔR/R computation
│   ├── session.py             ← Session data model + lazy-load NumPy arrays
│   ├── session_manager.py     ← Session CRUD on disk
│   ├── live.py                ← Continuous live preview
│   ├── scan.py                ← Raster tile scan with autofocus
│   ├── calibration.py         ← Thermal calibration (C_T sweep)
│   ├── calibration_runner.py  ← Calibration execution logic
│   ├── analysis.py            ← Post-acquisition hotspot detection & SNR
│   ├── export.py              ← Multi-format export (TIFF, HDF5, CSV, PDF …)
│   ├── processing.py          ← Colormap, normalization, ROI masking
│   ├── drift_correction.py    ← Long-acquisition drift compensation
│   ├── roi.py                 ← ROI data model
│   ├── roi_widget.py          ← ROI editor widget
│   ├── modality.py            ← Imaging modalities enum
│   ├── recipe_presets.py      ← Pre-built measurement recipes
│   ├── autosave.py            ← Checkpoint saving
│   ├── schema_migrations.py   ← Session metadata version migrations
│   └── movie_pipeline.py      ← Burst-mode high-speed capture
│
├── ui/                        ← Qt5 UI components
│   ├── app_signals.py         ← AppSignals singleton (application-wide Qt signals)
│   ├── sidebar_nav.py         ← Collapsible sidebar navigation (Advanced mode)
│   ├── wizard.py              ← Guided workflow wizard (Standard mode)
│   ├── settings_tab.py        ← Preferences / AI setup / license / about
│   ├── first_run.py           ← First-run hardware setup wizard
│   ├── device_manager_dialog.py ← Device discovery and management dialog
│   ├── update_dialog.py       ← Update badge and about dialog
│   ├── theme.py               ← Dark theme stylesheet
│   ├── icons.py               ← FontAwesome icon name constants
│   ├── font_utils.py          ← DPI-aware font scaling
│   ├── button_utils.py        ← Button state/style helpers
│   ├── notifications.py       ← Toast notification system
│   ├── license_dialog.py      ← License key entry / display dialog
│   ├── help.py                ← Help viewer
│   ├── scripting_console.py   ← Python REPL for power users
│   │
│   ├── tabs/                  ← Hardware control tabs (camera, tec, fpga, bias, stage …)
│   ├── dialogs/               ← Specialized dialogs (support bundle, etc.)
│   └── widgets/               ← Reusable widgets (image pane, temp plot, status header …)
│
├── ai/                        ← AI assistant
│   ├── ai_service.py          ← Multi-backend AI service (local + cloud)
│   ├── model_runner.py        ← llama-cpp-python inference wrapper
│   ├── model_downloader.py    ← Model download/cache
│   ├── model_catalog.py       ← Available model list
│   ├── diagnostic_engine.py   ← Real-time grade A–D assessment
│   ├── diagnostic_rules.py    ← Individual diagnostic rules
│   ├── metrics_service.py     ← Live metric collection (SNR, saturation, temp)
│   ├── context_builder.py     ← System-state context for AI prompts
│   ├── prompt_templates.py    ← System prompts
│   ├── instrument_knowledge.py ← Hardware limits, CTR table, calibration constants
│   ├── manual_rag.py          ← User Manual RAG (keyword-matched sections)
│   ├── personas.py            ← AI personality definitions
│   ├── hardware_probe.py      ← Hardware capability queries for AI
│   └── remote_runner.py       ← Cloud provider integration (Claude / ChatGPT)
│
├── licensing/                 ← License key validation
│   ├── __init__.py
│   ├── license_model.py       ← LicenseTier enum, LicenseInfo dataclass
│   └── license_validator.py   ← Ed25519 offline signature verification
│
├── profiles/                  ← Material measurement profiles
│   ├── profiles.py            ← MaterialProfile (C_T, wavelength, metadata)
│   ├── profile_manager.py     ← Load profiles from disk
│   └── profile_tab.py         ← Profile selection UI
│
├── events/                    ← Application event bus
│   ├── event_bus.py           ← Central dispatcher
│   ├── models.py              ← Event data structures
│   └── timeline_store.py      ← Persistent event log (JSONL)
│
├── support/                   ← Support bundle generation
│   ├── bundle_builder.py      ← Zip logs, configs, hardware info
│   └── system_info.py         ← Platform information collector
│
├── tools/                     ← Developer / operator tools (not shipped in installer)
│   ├── gen_license.py         ← Offline license key generator (holds private key)
│   ├── tec_panel.py           ← Standalone TEC control panel
│   ├── viewer.py              ← Saved session image viewer
│   └── acquisition_panel.py   ← Standalone acquisition panel
│
├── tests/                     ← Pytest suite (~94 tests)
│   ├── test_core.py
│   ├── test_ai.py
│   ├── test_pipelines.py
│   ├── test_widgets.py
│   └── test_integration.py
│
├── docs/                      ← Documentation
│   ├── QuickstartGuide.md
│   ├── UserManual.md
│   ├── LicenseKeySystem.md
│   └── DeveloperGuide.md      ← This file
│
├── installer/                 ← Windows packaging
│   ├── sanjinsight.spec       ← PyInstaller spec
│   ├── setup.iss              ← Inno Setup script
│   ├── gen_version_info.py    ← Windows VERSIONINFO resource generator
│   └── assets/                ← Icons / branding
│
├── .github/workflows/
│   ├── build-installer.yml    ← CI/CD: build + publish GitHub Release
│   └── ci.yml                 ← Test suite runner
│
├── config.yaml                ← Hardware configuration
├── CHANGELOG.md               ← Release history
└── LICENSE                    ← Proprietary license text
```

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                      main_app.py                         │
│                    MainWindow (QMainWindow)               │
│  ┌─────────────┐  ┌────────────────┐  ┌───────────────┐  │
│  │  Sidebar /  │  │  Acquisition   │  │  AI Panel     │  │
│  │  Wizard     │  │  Tabs & Panes  │  │  Widget       │  │
│  └──────┬──────┘  └───────┬────────┘  └──────┬────────┘  │
│         │                 │                  │            │
└─────────┼─────────────────┼──────────────────┼────────────┘
          │    Qt Signals   │                  │
          ▼                 ▼                  ▼
┌───────────────────────────────────────────────────────────┐
│                   HardwareService                         │
│  (Background threads — never touches Qt directly)         │
│                                                           │
│  _run_camera()   _run_tec()   _run_fpga()   _run_stage()  │
│      │               │             │              │        │
│      ▼               ▼             ▼              ▼        │
│  CameraDriver   TecDriver    FpgaDriver    StageDriver     │
│  (Basler/NI/    (Meerstetter/ (NI 9637/    (Thorlabs/     │
│   simulated)     simulated)   simulated)    simulated)     │
└───────────────────────────────────────────────────────────┘
          │                 │
          ▼                 ▼
┌──────────────┐   ┌────────────────────────────────────────┐
│ ApplicationState│  │         Acquisition Pipeline          │
│ (RLock-based   │  │  cold frames → average → ΔR/R → SNR   │
│  shared state) │  └────────────────────────────────────────┘
└──────────────┘             │
                             ▼
                  ┌─────────────────────┐
                  │   SessionManager    │
                  │  (disk persistence) │
                  └─────────────────────┘
```

**Design principles**:

- **Hardware threads are separate from the GUI thread.** All cross-thread communication is via Qt signals (auto-marshaled to the GUI thread) or via `ApplicationState` (RLock-protected).
- **No global module-level state.** Hardware references live in `ApplicationState`; preferences live in `config`; signals live in `AppSignals`.
- **Factory pattern for all drivers.** Each device type has an abstract base class and a `factory.py` that reads `config.yaml` and instantiates the correct implementation.
- **Simulated drivers for every device.** Demo mode or development without hardware is always possible.

---

## 4. Hardware Layer

### 4.1 ApplicationState (`hardware/app_state.py`)

The single shared-state object. All hardware references are properties here, protected by an `RLock`.

```python
from hardware.app_state import ApplicationState
app_state = ApplicationState()    # singleton — call once at startup

# Reading state (any thread)
cam = app_state.cam               # CameraDriver | None

# Atomic compound update (any thread)
with app_state:
    app_state.cam = new_driver
    app_state.pipeline = AcquisitionPipeline(new_driver)

# Other key properties
app_state.fpga          # FpgaDriver | None
app_state.bias          # BiasDriver | None
app_state.stage         # StageDriver | None
app_state.tecs          # List[TecDriver]
app_state.turret        # ObjectiveTurretDriver | None
app_state.af            # AutofocusDriver | None
app_state.pipeline      # AcquisitionPipeline | None
app_state.demo_mode     # bool
app_state.license_info  # LicenseInfo | None
app_state.is_licensed   # bool (computed from license_info)
```

### 4.2 HardwareService (`hardware/hardware_service.py`)

Owns all device lifecycles and background poll threads.

**Startup sequence:**
1. `HardwareService.start()` is called from `MainWindow.__init__`
2. Runs `DeviceScanner.scan()` (parallel threads — serial, USB, camera, NI, network)
3. Passes `ScanReport` to `DeviceManager`
4. Starts one daemon thread per device type

**Key signals (emitted from background threads, queued to GUI):**

| Signal | Payload | Description |
|---|---|---|
| `camera_frame` | `CameraFrame` | New live frame from camera |
| `tec_status` | `(int, TecStatus)` | Temperature poll result |
| `fpga_status` | `FpgaStatus` | FPGA state |
| `bias_status` | `BiasStatus` | Bias source state |
| `stage_status` | `StageStatus` | Stage position |
| `acq_progress` | `AcquisitionProgress` | Acquisition step completion |
| `acq_complete` | `AcquisitionResult` | Full acquisition result |
| `device_connected` | `(str, bool)` | Device hotplug event |
| `tec_alarm` | `(int, str, float, float)` | TEC safety alert |

**Back-pressure for camera frames:**

The camera thread uses a `threading.Event` semaphore (`_cam_preview_free`) to prevent flooding the Qt event queue when the camera frame rate exceeds the GUI render rate:

```python
# In _run_camera() background thread:
self._cam_preview_free.wait()          # Block until GUI has consumed last frame
self.camera_frame.emit(frame)
self._cam_preview_free.clear()         # Mark as consumed

# In MainWindow._on_frame() GUI thread:
self.hw_service.ack_camera_frame()     # Unblocks next frame
```

**Auto-reconnect:**
If a device poll loop raises an exception, the thread waits with exponential backoff (2 s → 4 s → 8 s → … capped at 30 s) and retries the connection.

### 4.3 Driver Abstraction Pattern

Every device type follows the same pattern:

```
hardware/<type>/
    base.py       ← Abstract base class (interface)
    factory.py    ← create_<type>(config) → <Type>Driver
    <impl1>.py    ← Real hardware implementation
    <impl2>.py    ← Alternative implementation
    simulated.py  ← Simulated implementation (always present)
```

**To add a new implementation of an existing device type**, follow section 17.

#### Camera (`hardware/cameras/base.py — CameraDriver`)

```python
class CameraDriver(ABC):
    def open(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
    def grab(self, timeout_ms: int = 500) -> CameraFrame: ...
    def set_exposure(self, microseconds: float) -> None: ...
    def set_gain(self, db: float) -> None: ...

    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...
    @property
    def bit_depth(self) -> int: ...    # 8, 10, 12, or 16
```

`CameraFrame` contains:
- `data: np.ndarray` — uint16, shape `(H, W)`
- `timestamp: float` — `time.monotonic()` at capture
- `index: int` — frame counter

**Implementations**: `pypylon_driver.py` (Basler), `ni_imaqdx.py` (NI), `directshow.py` (webcam), `simulated.py`.

#### TEC (`hardware/tec/base.py — TecDriver`)

```python
class TecDriver(ABC):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def enable(self) -> None: ...
    def disable(self) -> None: ...
    def set_target(self, temperature_c: float) -> None: ...
    def get_status(self) -> TecStatus: ...
```

`TecStatus` fields: `actual_temp`, `target_temp`, `sink_temp`, `output_current`, `output_voltage`, `output_power`, `enabled`, `stable`, `error`.

**Implementations**: `meerstetter.py` (TEC-1089 via pyMeCom), `atec.py`, `thermal_chuck.py`, `simulated.py`.

#### FPGA (`hardware/fpga/base.py — FpgaDriver`)

The FPGA generates the modulation waveform that switches the stimulus (bias, laser) between hot and cold states.

```python
class FpgaDriver(ABC):
    def open(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
    def set_output(self, state: bool) -> None: ...  # True=hot, False=cold
    def set_frequency(self, hz: float) -> None: ...
    def set_duty_cycle(self, fraction: float) -> None: ...  # 0.0 – 1.0
    def get_status(self) -> FpgaStatus: ...
```

**Implementations**: `ni9637.py` (NI CompactRIO via nifpga), `simulated.py`.

#### Bias Source (`hardware/bias/base.py — BiasDriver`)

```python
class BiasDriver(ABC):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def enable(self) -> None: ...
    def disable(self) -> None: ...
    def set_voltage(self, volts: float) -> None: ...
    def set_current_limit(self, amps: float) -> None: ...
    def get_status(self) -> BiasStatus: ...
```

**Implementations**: `keithley.py` (VISA), `visa_generic.py` (SCPI), `simulated.py`.

#### Stage (`hardware/stage/base.py — StageDriver`)

```python
class StageDriver(ABC):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def move_xy(self, x_um: float, y_um: float, z_um: float = None) -> None: ...
    def move_relative(self, dx_um: float, dy_um: float, dz_um: float = 0) -> None: ...
    def home(self) -> None: ...
    def stop(self) -> None: ...
    def get_position(self) -> StagePosition: ...
    def get_status(self) -> StageStatus: ...
    def disconnect(self) -> None: ...
```

**Implementations**: `thorlabs.py`, `serial_stage.py`, `mpi_prober.py`, `simulated.py`.

#### Other Device Types

| Type | Base Class | Implementations |
|---|---|---|
| Autofocus | `AutofocusDriver` | `hill_climb.py`, `sweep.py`, `simulated.py` |
| Objective turret | `ObjectiveTurretDriver` | `olympus_linx.py`, `simulated.py` |
| Laser diode driver | `LddDriver` | `meerstetter_ldd1121.py`, `simulated.py` |

### 4.4 Device Scanner (`hardware/device_scanner.py`)

Runs five sub-scanners in parallel threads on startup:

| Scanner | Discovers |
|---|---|
| `SerialScanner` | pyserial COM/ttyUSB ports; matches VID/PID against registry |
| `UsbScanner` | pyusb raw USB devices (excludes known serial VIDs) |
| `CameraScanner` | Basler Pylon SDK + NI IMAQdx SDK |
| `NiScanner` | NI-FPGA (CompactRIO) + NI-VISA resource manager |
| `NetworkScanner` | Subnet TCP probe for GigE/SCPI instruments (opt-in, off by default) |

Returns a `ScanReport` containing `List[DiscoveredDevice]`, each with a device key, display name, connection string, and whether it matched a known registry entry.

### 4.5 DeviceManager (`hardware/device_manager.py`)

State machine per device:

```
ABSENT → DISCOVERED → CONNECTING → CONNECTED
                          │              │
                          ↓              ↓
                        ERROR  ←  [poll loop failure]
                          │
                    DISCONNECTING → ABSENT
```

Connection timeout: 12 seconds (configurable in `config.yaml`).

---

## 5. Acquisition Pipeline

### 5.1 AcquisitionPipeline (`acquisition/pipeline.py`)

The core measurement loop. Given a camera (+ optional FPGA/bias for stimulus control), it captures alternating cold and hot image stacks, averages them, and computes ΔR/R.

**Full measurement sequence:**

```
1. Safety check: ensure required hardware is ready
2. Emit AcquisitionProgress(state=CAPTURING, phase="cold")
3. Set stimulus OFF  (FPGA.set_output(False)  or  Bias.disable())
4. Capture n_frames frames → stack[0..N-1] (uint16)
5. Average stack → cold_avg (float64)
6. Wait inter_phase_delay seconds
7. Emit AcquisitionProgress(phase="hot")
8. Set stimulus ON   (FPGA.set_output(True)   or  Bias.enable())
9. Capture n_frames frames → average → hot_avg (float64)
10. Set stimulus OFF (restore safe state)
11. Compute:  ΔR/R = (hot_avg - cold_avg) / cold_avg
12. Mask dark pixels (cold_avg < 5th percentile) as NaN
13. Compute SNR_dB = 20·log10(mean|ΔR/R| / std(ΔR/R))
14. Emit AcquisitionResult
```

**Usage:**

```python
pipeline = AcquisitionPipeline(
    camera=app_state.cam,
    fpga=app_state.fpga,
    bias=app_state.bias,
)
pipeline.on_progress = lambda p: print(p.message)
pipeline.on_complete = lambda r: save_and_display(r)

# Non-blocking (background thread)
pipeline.start(n_frames=100, inter_phase_delay=0.1)
pipeline.abort()    # cancel at any time

# Blocking (current thread — only use outside GUI thread)
result = pipeline.run(n_frames=100)
```

### 5.2 AcquisitionResult

```python
@dataclass
class AcquisitionResult:
    cold_avg: np.ndarray           # float64, shape (H, W)
    hot_avg: np.ndarray            # float64, shape (H, W)
    delta_r_over_r: np.ndarray     # float32, shape (H, W); NaN where dark
    difference: np.ndarray         # float32, shape (H, W); hot − cold

    n_frames: int
    exposure_us: float
    gain_db: float
    timestamp: float               # time.time()
    duration_s: float
    snr_db: float                  # computed from ΔR/R excluding NaN pixels
    dark_pixel_fraction: float     # fraction of NaN pixels in result
    notes: str
```

### 5.3 ΔR/R Computation

```python
# Inputs: float64 arrays, shape (H, W)
drr = (hot_avg - cold_avg) / cold_avg

# Typical value range: ±1e-4 to ±1e-2
# (0.01% to 1% reflectance change per degree)

# Mask low-signal pixels (their noise dominates)
dark_threshold = np.percentile(cold_avg, 5)
drr[cold_avg < dark_threshold] = np.nan
```

### 5.4 Calibration (`acquisition/calibration.py`)

Determines the thermoreflectance calibration coefficient **C_T** (units: ΔR/R per °C) for the material under test.

**Procedure:**
1. Set TEC to temperature T₁; wait for stability
2. Acquire ΔR/R image; record mean signal
3. Repeat for T₂, T₃, … (typically 6–10 points)
4. Linear regression: ΔR/R vs. ΔT → slope = C_T

**Typical values**: C_T = 1–5 × 10⁻⁴ / °C (material dependent).

Once calibrated, temperature maps are computed as:

```python
temperature_map = delta_r_over_r / C_T    # °C above baseline
```

### 5.5 Scan (`acquisition/scan.py`)

Raster tiling acquisition — moves the stage in a grid, acquires at each position.

```
For row in range(n_rows):
    For col in range(n_cols):
        stage.move_xy(col * step_x_um, row * step_y_um)
        autofocus.run()                    # optional
        result = pipeline.run(n_frames)
        stitch_tile(result.delta_r_over_r, row, col)
```

Output: a stitched ΔR/R image of size `(n_rows × H, n_cols × W)`.

---

## 6. User Interface

### 6.1 MainWindow (`main_app.py`)

`MainWindow(QMainWindow)` is the top-level window. It:

- Instantiates `HardwareService`, `SessionManager`, `ApplicationState`, `AppSignals`
- Builds two navigation modes: **Standard** (wizard) and **Advanced** (sidebar)
- Connects all Qt signals from `HardwareService` to slot methods
- Manages the central stack widget (switches between Standard and Advanced views)

**Key slot methods:**

| Method | Connected to |
|---|---|
| `_on_frame(frame)` | `hw_service.camera_frame` |
| `_on_tec_status(idx, status)` | `hw_service.tec_status` |
| `_on_acq_progress(progress)` | `hw_service.acq_progress` |
| `_on_acq_complete(result)` | `hw_service.acq_complete` |
| `_on_device_connected(key, ok)` | `hw_service.device_connected` |
| `_on_tec_alarm(idx, msg, val, lim)` | `hw_service.tec_alarm` |
| `_on_manual_update_check()` | Help menu "Check for Updates" |
| `_show_license_dialog()` | Help menu "License…" |
| `_deactivate_demo_mode()` | `StatusHeader.exit_demo_requested` |

### 6.2 Navigation Modes

**Standard Mode** (`ui/wizard.py`):
- `StandardWizard` — guided step-by-step measurement workflow
- Steps: Select Profile → Configure Camera → Set Temperature → Acquire → View Result
- Suitable for new users and routine measurements

**Advanced Mode** (`ui/sidebar_nav.py`):
- Collapsible sidebar with 20+ tabs grouped by category:
  - **Hardware**: Camera, TEC, FPGA, Bias, Stage, Autofocus, ROI
  - **Acquire**: Live, Acquire, Scan, Calibration, Movie, Transient
  - **Analysis**: Analysis, Comparison, Surface Plot, Data
  - **System**: Settings, Log, Scripting Console

### 6.3 AppSignals (`ui/app_signals.py`)

A singleton `QObject` that holds application-wide signals. Tabs emit and connect to signals here rather than passing references between widgets:

```python
signals = AppSignals()
signals.session_saved.emit(session_uid)     # Any tab can emit
signals.session_saved.connect(callback)     # Any tab can connect
```

Key signals: `session_saved`, `profile_changed`, `hardware_ready`, `demo_mode_changed`, `license_changed`.

### 6.4 StatusHeader (`ui/widgets/status_header.py`)

The orange header bar at the top of the window. Shows:
- Hardware connection status for each device (colored dots)
- Mode indicator (Standard / Advanced)
- DEMO MODE banner (when in demo mode) with `✕ Exit` button

**Signals:**
- `exit_demo_requested` — emitted when user clicks `✕ Exit` in demo banner

### 6.5 Notifications (`ui/notifications.py`)

Toast-style notifications appearing in the bottom-right corner:

```python
from ui.notifications import show_toast
show_toast(parent_widget, "Acquisition complete", level="success", duration_ms=3000)
# Levels: "info", "success", "warning", "error"
```

### 6.6 Theme (`ui/theme.py`)

A single dark stylesheet applied globally via `QApplication.setStyleSheet()`. Colors are defined as module-level constants:

```python
_DARK_BG    = "#1e1e1e"
_PANEL_BG   = "#2d2d2d"
_ACCENT     = "#00d4aa"    # Microsanj teal
_TEXT       = "#e0e0e0"
_AMBER      = "#f0a500"
_RED        = "#e05252"
_GREEN      = "#4caf50"
```

---

## 7. AI Assistant & Diagnostics

### 7.1 AI Service (`ai/ai_service.py`)

Multi-backend AI service. The active backend is selected in Settings:

| Backend | Module | Requirements |
|---|---|---|
| Local LLM | `model_runner.py` (llama-cpp-python) | Downloaded model file |
| Claude API | `remote_runner.py` | User's Anthropic API key |
| ChatGPT API | `remote_runner.py` | User's OpenAI API key |

**Context injected with every prompt:**
1. Quickstart Guide (always, ~2,500 tokens)
2. User Manual sections matched to the active tab (RAG, up to ~8,000 tokens)
3. Instrument knowledge (hardware limits, CTR table, ~80 tokens)
4. Live metrics snapshot (SNR, saturation, temperature)
5. Active material profile (C_T, wavelength)

### 7.2 Diagnostic Engine (`ai/diagnostic_engine.py`)

Runs continuously and grades the system A–D:

| Grade | Meaning |
|---|---|
| A | All systems optimal |
| B | Amber warnings present |
| C | Red failures — degraded operation |
| D | Critical failure — operation blocked |

**Rules (in `ai/diagnostic_rules.py`):**

| Rule | Condition | Level |
|---|---|---|
| T1 | FPGA duty cycle ≥ 50% | Amber |
| T1 | FPGA duty cycle ≥ 80% | Red |
| C3 | Camera saturation ≥ 3900 ADU (12-bit) | Amber |
| C3 | Camera pixels clipped | Red |
| R5 | TEC setpoint < 10°C or > 150°C | Red |

To add a new rule, add a function to `diagnostic_rules.py` following the existing pattern and register it in `diagnostic_engine.py`.

### 7.3 Manual RAG (`ai/manual_rag.py`)

Loads `docs/UserManual.md`, splits it into sections, and retrieves relevant sections based on keyword overlap with the user's query and the active tab name. This keeps context token usage bounded while ensuring the AI has relevant documentation.

---

## 8. License System

### 8.1 Overview

Licenses use **Ed25519 asymmetric cryptography**. The private key (held by Microsanj) signs license payloads; the public key (baked into the app) verifies them. Validation is fully offline — no server call ever occurs.

### 8.2 Key Format

```
<base64url(json_payload)>.<base64url(ed25519_signature)>
```

**Payload JSON fields:**

```json
{
  "tier": "standard",
  "customer": "Acme Corp",
  "email": "admin@acme.com",
  "seats": 3,
  "issued": "2026-01-15",
  "expires": "2027-01-15",
  "serial": "SJ-2026-001"
}
```

`"expires": null` means perpetual (never expires).

### 8.3 Validation Flow (`licensing/license_validator.py`)

```python
def validate_key(key_string: str) -> Optional[LicenseInfo]:
    payload_b64, sig_b64 = key_string.split(".")
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
    sig_bytes     = base64.urlsafe_b64decode(sig_b64 + "==")

    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(_PUBLIC_KEY_B64)
    )
    public_key.verify(sig_bytes, payload_bytes)  # raises InvalidSignature if forged

    data = json.loads(payload_bytes)
    # Build and return LicenseInfo; return None if expired
```

### 8.4 Generating License Keys

```bash
# Run on Microsanj's machine only (requires the private key file)
python tools/gen_license.py \
  --key-file microsanj_license_private.key \
  --customer "Acme Corp" \
  --email admin@acme.com \
  --tier standard \
  --seats 3 \
  --days 365 \
  --serial SJ-2026-001
```

See `docs/LicenseKeySystem.md` for the full operations manual.

### 8.5 License Tiers (`licensing/license_model.py`)

```python
class LicenseTier(str, Enum):
    UNLICENSED = "unlicensed"
    STANDARD   = "standard"
    SITE       = "site"
```

`LicenseInfo` computed properties: `is_active`, `is_expired`, `days_until_expiry`, `expiry_display`, `tier_display`.

### 8.6 Runtime Access

```python
# Set at startup in main_app._load_license()
app_state.license_info = load_license(config)

# Check anywhere
if app_state.is_licensed:
    enable_premium_feature()
```

---

## 9. Configuration & Preferences

### 9.1 System Configuration (`config.yaml`)

YAML file at the repository root. Defines hardware drivers, polling intervals, and logging:

```yaml
camera:
  driver: pypylon          # pypylon | ni_imaqdx | directshow | simulated
  serial: "12345678"       # Device serial number (leave blank for first-found)

tec:
  - driver: meerstetter
    port: COM3
    address: 2

fpga:
  driver: ni9637
  resource: RIO0

bias:
  driver: keithley
  visa_address: "GPIB0::24::INSTR"

stage:
  driver: thorlabs
  serial_x: "12345678"
  serial_y: "87654321"

logging:
  level: INFO              # DEBUG | INFO | WARNING | ERROR

polling:
  tec_interval:   0.50     # seconds
  fpga_interval:  0.25
  bias_interval:  0.25
  stage_interval: 0.10
```

Missing `config.yaml` → app writes a default and runs in simulated mode.

### 9.2 User Preferences (`~/.microsanj/preferences.json`)

Read/written via `config.get_pref()` / `config.set_pref()`:

```python
config.get_pref("ui.mode", "standard")           # "standard" | "advanced"
config.get_pref("updates.auto_check", True)
config.get_pref("updates.frequency", "always")   # "always" | "daily" | "weekly"
config.get_pref("ai.enabled", False)
config.get_pref("ai.backend", "local")           # "local" | "claude" | "openai"
config.get_pref("ai.model_path", "")
config.get_pref("license.key", "")
```

---

## 10. Session Management

### 10.1 Session Structure on Disk

```
~/microsanj_sessions/
    20260307_143022_gold_pad_A/
        session.json           ← Metadata (human-readable)
        cold_avg.npy           ← float64 baseline frame
        hot_avg.npy            ← float64 stimulus frame
        delta_r_over_r.npy     ← float32 ΔR/R signal (NaN where dark)
        difference.npy         ← float32 hot − cold
        thumbnail.png          ← Small PNG preview for browser
```

### 10.2 SessionMeta Fields

| Field | Type | Description |
|---|---|---|
| `uid` | str | Unique ID (timestamp-based) |
| `label` | str | User-facing name |
| `timestamp` | float | `time.time()` at acquisition |
| `imaging_mode` | str | `"thermoreflectance"`, `"ir_lockin"`, `"hybrid"`, `"opp"` |
| `wavelength_nm` | int | Illumination wavelength |
| `n_frames` | int | Frames averaged per phase |
| `exposure_us` | float | Camera exposure |
| `gain_db` | float | Camera gain |
| `fpga_frequency_hz` | float | Modulation frequency |
| `fpga_duty_cycle` | float | Duty cycle |
| `tec_temperature` | float | Actual TEC temp at acquisition |
| `tec_setpoint` | float | TEC setpoint |
| `bias_voltage` | float | Applied bias voltage |
| `bias_current` | float | Applied bias current |
| `profile_uid` | str | Material profile ID |
| `ct_value` | float | C_T coefficient used |
| `snr_db` | float | Computed SNR |
| `schema_version` | int | For migrations |

### 10.3 Loading Sessions

Arrays are lazy-loaded — only read from disk when accessed:

```python
session = Session.load("/path/to/session_dir")
drr = session.delta_r_over_r    # Loads delta_r_over_r.npy on first access
session.unload()                 # Frees memory
```

### 10.4 Schema Migrations (`acquisition/schema_migrations.py`)

When a new field is added to `SessionMeta`, a migration function bumps `schema_version` and fills in the default value for old sessions. Migrations run automatically on `Session.load()`.

---

## 11. Update System

### 11.1 UpdateChecker (`updater.py`)

Checks GitHub Releases for a newer version. Source repo is private; the public `sanjinsight-releases` repo is used for update checking (no auth required).

**Check URL:** `https://api.github.com/repos/edward-mcnair/sanjinsight-releases/releases/latest`

**Frequency control (via user preferences):**

| Value | Behavior |
|---|---|
| `"always"` | Check every launch |
| `"daily"` | Once per calendar day |
| `"weekly"` | Once per 7 days |

**Skip conditions:**
- Demo mode (`app_state.demo_mode == True`) — skips auto-check on startup; manual "Check Now" always works

**Callback:**

```python
checker = UpdateChecker(current_version="1.1.2", on_update=my_callback)
checker.check_async()    # Non-blocking background thread
result = checker.check_sync()   # Blocking (used for "Check Now" button)
```

`on_update(UpdateInfo)` is called on the background thread if a newer version is found.
`UpdateInfo` has: `latest_version`, `release_notes`, `download_url`, `release_page_url`.

---

## 12. Event Bus & Logging

### 12.1 EventBus (`events/event_bus.py`)

Central dispatcher for application-wide events:

```python
from events.event_bus import emit_info, emit_warning, emit_error

emit_info("acquisition", "acq_complete", "Acquisition finished", snr_db=34.2)
emit_warning("tec", "temp_unstable", "TEC not stable", actual=25.3, target=25.0)
emit_error("camera", "grab_timeout", "Camera frame grab timed out")
```

Events are stored in `TimelineStore` (`~/.microsanj/timeline.jsonl`) as newline-delimited JSON for audit trails and debugging.

### 12.2 Python Logging

Configured in `logging_config.py`. Output goes to:
- **Console** (INFO and above)
- **Rotating file** (`~/.microsanj/logs/microsanj.log`, 2 MB per file, 5 backups)

Use standard Python logging in all modules:

```python
import logging
log = logging.getLogger(__name__)
log.debug("Frame grabbed: index=%d", frame.index)
log.warning("TEC not stable after 30s")
log.error("Camera grab failed: %s", exc)
```

---

## 13. Thread Safety Model

| Mechanism | Used for |
|---|---|
| `ApplicationState` (RLock) | Protecting hardware driver references |
| `threading.Event` (`_stop_event`) | Signaling background threads to exit |
| `threading.Event` (`_cam_preview_free`) | Camera frame back-pressure |
| `DeviceManager._lock` | Device state machine transitions |
| Qt signals (auto-queued) | Cross-thread GUI updates |

**Rule**: Background threads (hardware poll loops, acquisition pipeline) **never** call any Qt widget methods directly. They emit signals, which Qt queues to the GUI thread automatically.

**Rule**: All reads/writes of hardware driver references use `with app_state:` to avoid races during hotplug.

**Rule**: `AcquisitionPipeline.run()` (blocking) must be called from a non-GUI thread. `AcquisitionPipeline.start()` (non-blocking) spawns its own thread internally.

---

## 14. Data Flow Diagrams

### Hardware Discovery & Startup

```
main_app.MainWindow.__init__()
    │
    ├─ HardwareService.start()
    │   ├─ DeviceScanner.scan()  [5 parallel threads]
    │   │   → ScanReport
    │   ├─ DeviceManager.update_from_scan(report)
    │   ├─ Thread: _run_camera()  ──► camera.grab()  ──► camera_frame.emit()
    │   ├─ Thread: _run_tec(0)   ──► tec.get_status() ──► tec_status.emit()
    │   ├─ Thread: _run_tec(1)   ──► tec.get_status() ──► tec_status.emit()
    │   ├─ Thread: _run_fpga()   ──► fpga.get_status() ──► fpga_status.emit()
    │   ├─ Thread: _run_bias()   ──► bias.get_status() ──► bias_status.emit()
    │   └─ Thread: _run_stage()  ──► stage.get_status() ──► stage_status.emit()
    │
    ├─ MainWindow._load_license()
    └─ MainWindow._start_update_checker()
```

### Acquisition (live frame → display)

```
[Camera thread]                [GUI thread]
    │
    ├─ camera.grab()
    ├─ _cam_preview_free.wait()
    ├─ camera_frame.emit(frame) ──────────────────► _on_frame(frame)
    ├─ _cam_preview_free.clear()                         │
    │                                               ack_camera_frame()
    │                                               ├─ CameraTab.update_frame()
    │                                               ├─ AcquireTab.update_live()
    │                                               └─ RoiTab.update_frame()
    │  [blocks here until ack]
    ├─ _cam_preview_free.wait()  ◄────────────────── _cam_preview_free.set()
    └─ (loop)
```

### Acquisition (hot/cold → result → session)

```
[User: clicks Acquire]
    │
    [GUI thread]
    ├─ AcquireTab._start_acquisition()
    ├─ AcquisitionPipeline.start(n_frames=100)
    │
    [Pipeline thread]
    ├─ Stimulus OFF → capture cold frames → average
    ├─ Stimulus ON  → capture hot  frames → average
    ├─ Compute ΔR/R, SNR
    ├─ acq_progress.emit(progress)  ──► GUI: progress bar update
    └─ acq_complete.emit(result)    ──►
                                        [GUI thread]
                                        _on_acq_complete(result)
                                        ├─ session_mgr.save(session)
                                        ├─ Display result
                                        └─ show_toast("Acquisition complete")
```

---

## 15. Build & Release Pipeline

### 15.1 GitHub Actions (`.github/workflows/build-installer.yml`)

**Triggers:**
- `git push origin v1.2.0` — builds + creates GitHub Release on `sanjinsight-releases`
- Manual **Run workflow** in Actions UI — builds only (artifact available for 1 day)

**Steps:**
1. Checkout on `windows-latest` runner
2. Python 3.11 + pip dependencies
3. Convert `assets/microsanj-logo.svg` → `installer/assets/sanjinsight.ico`
4. Generate `installer/version_info.txt` (Windows VERSIONINFO)
5. **PyInstaller** → `dist/SanjINSIGHT/` (self-contained bundle)
6. **Inno Setup** → `installer_output/SanjINSIGHT-Setup-X.Y.Z.exe`
7. Extract release notes from `CHANGELOG.md`
8. **Create GitHub Release** on `edward-mcnair/sanjinsight-releases` with `.exe` attached

### 15.2 Release Procedure

```bash
# 1. Update version
# Edit version.py: __version__ = "1.2.0", BUILD_DATE = "2026-03-15"

# 2. Update CHANGELOG.md: add ## [1.2.0] — 2026-03-15 section

# 3. Commit
git add version.py CHANGELOG.md
git commit -m "chore: bump to v1.2.0"

# 4. Tag and push — this triggers CI
git tag v1.2.0
git push origin main
git push origin v1.2.0

# 5. CI builds installer and publishes release automatically
# 6. Verify at https://github.com/edward-mcnair/sanjinsight-releases/releases
```

### 15.3 Local Windows Build (manual)

```bash
pip install pyinstaller pillow cairosvg
pyinstaller installer/sanjinsight.spec --noconfirm --clean
python installer/gen_version_info.py
# Then open Inno Setup and compile installer/setup.iss
```

### 15.4 CI Test Runner (`.github/workflows/ci.yml`)

Runs on every push and PR:

```bash
pytest tests/
```

CI requires `CHANGELOG.md` to have an entry for the current version in `version.py`.

---

## 16. Testing

```bash
# Run all tests
pytest tests/

# Run a specific file
pytest tests/test_pipelines.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

**Test files:**

| File | Covers |
|---|---|
| `test_core.py` | Config loading, version parsing, utilities |
| `test_ai.py` | AI service, diagnostic rules, metrics |
| `test_pipelines.py` | Acquisition pipeline, session save/load |
| `test_widgets.py` | Qt widget initialization & signal connections |
| `test_integration.py` | End-to-end workflows with simulated hardware |

All hardware tests use simulated drivers — no real hardware required to run the suite.

---

## 17. Adding a New Hardware Driver

Example: adding a new camera driver `acme_cam.py`.

**Step 1 — Implement the driver:**

```python
# hardware/cameras/acme_cam.py
from hardware.cameras.base import CameraDriver, CameraFrame
import time, numpy as np

class AcmeCameraDriver(CameraDriver):
    def __init__(self, serial: str):
        self._serial = serial
        self._sdk = None

    def open(self):
        import acme_sdk
        self._sdk = acme_sdk.open(self._serial)

    def start(self):
        self._sdk.start_stream()

    def stop(self):
        self._sdk.stop_stream()

    def close(self):
        self._sdk.close()

    def grab(self, timeout_ms: int = 500) -> CameraFrame:
        raw = self._sdk.get_frame(timeout_ms=timeout_ms)
        return CameraFrame(
            data=raw.astype(np.uint16),
            timestamp=time.monotonic(),
            index=raw.index,
        )

    def set_exposure(self, microseconds: float):
        self._sdk.set_exposure(microseconds)

    def set_gain(self, db: float):
        self._sdk.set_gain(db)

    @property
    def width(self) -> int: return self._sdk.width
    @property
    def height(self) -> int: return self._sdk.height
    @property
    def bit_depth(self) -> int: return 12
```

**Step 2 — Register in the factory:**

```python
# hardware/cameras/factory.py — add to create_camera():
elif driver_name == "acme":
    from hardware.cameras.acme_cam import AcmeCameraDriver
    return AcmeCameraDriver(serial=cfg.get("serial", ""))
```

**Step 3 — Add a simulated version (required for CI):**

```python
# hardware/cameras/simulated.py — extend or add an acme-compatible mode
```

**Step 4 — Update `config.yaml`:**

```yaml
camera:
  driver: acme
  serial: "ACME123"
```

**Step 5 — Add a device registry entry (optional):**

```python
# hardware/device_registry.py
KNOWN_DEVICES["acme_cam"] = DeviceDescriptor(
    display_name="ACME Camera XR-200",
    vendor_id=0x1234,
    product_id=0x5678,
    category="camera",
)
```

No other changes are needed. The `HardwareService` reads the factory and the rest of the system sees a `CameraDriver` — it doesn't know or care which implementation is active.

---

## 18. Adding a New UI Tab

Example: adding a new "Polarization" tab in Advanced mode.

**Step 1 — Create the tab widget:**

```python
# ui/tabs/polarization_tab.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

class PolarizationTab(QWidget):
    def __init__(self, hw_service, app_state, parent=None):
        super().__init__(parent)
        self._hw = hw_service
        self._state = app_state
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Polarization Controls"))
        # ... add your controls

    def refresh(self):
        # Called when the tab becomes visible
        pass
```

**Step 2 — Register in the sidebar:**

```python
# ui/sidebar_nav.py — in _build_nav():
self._add_nav_item(
    group="Hardware",
    label="Polarization",
    icon="fa5s.adjust",       # FontAwesome 5 icon name
    widget_factory=lambda: PolarizationTab(self._hw, self._state),
)
```

**Step 3 — Connect hardware signals (if needed):**

```python
# In PolarizationTab.__init__() or in MainWindow._connect_signals():
hw_service.some_signal.connect(self._polarization_tab.on_some_event)
```

No changes to `MainWindow` are required if the tab is self-contained and uses `app_state` for hardware references.

---

## 19. Key Design Decisions

| Decision | Rationale |
|---|---|
| **PyQt5 (not PySide6)** | Mature, stable on Windows; PySide6 migration is straightforward when needed |
| **Factory pattern for all drivers** | Config-driven instantiation without `if/elif` chains in business logic |
| **Simulated driver for every device** | CI tests with no hardware; demo mode for sales/training |
| **ApplicationState RLock instead of per-driver locks** | Prevents compound-operation races (e.g., replacing camera + pipeline atomically) |
| **Camera frame back-pressure semaphore** | Prevents Qt event queue overflow at high frame rates |
| **Ed25519 for license keys (not HMAC)** | Asymmetric: private key never in app; public key cannot forge keys |
| **Two repos (source private, releases public)** | Update checker works without GitHub auth token; source is protected |
| **Lazy-loaded NumPy arrays in sessions** | Browsing 100s of sessions without loading all data into RAM |
| **Schema migrations on session load** | Old sessions remain valid after adding new metadata fields |
| **`version.py` as single source of truth** | All version strings, URLs, and repo names derived from one file; CI reads it |
| **Manual RAG over embedding-based RAG** | No embedding model required; keyword matching is fast and sufficient for a bounded domain |

---

## 20. Dependency Reference

```
PyQt5>=5.15.9          Qt5 GUI framework
PyQt5-sip>=12.12       PyQt5 C extension
numpy>=1.24            Numerical arrays (all image data)
scipy>=1.10            Signal processing, linear regression
matplotlib>=3.7        Plots (temperature, focus, histograms)
Pillow>=10.0           Image processing, thumbnail generation
pyyaml>=6.0            config.yaml parsing
pyserial>=3.5          Serial port enumeration and communication
pyusb>=1.2             USB device enumeration
cryptography>=42.0     Ed25519 license key validation
qtawesome>=1.3.0       FontAwesome 5 vector icons for PyQt5
requests>=2.31         HTTP (update checker, cloud AI)

# Optional — hardware SDKs (Windows-only, not in PyPI)
pypylon                Basler Pylon camera SDK Python wrapper
pyMeCom                Meerstetter TEC serial protocol
nifpga                 NI-FPGA Python interface
pyvisa                 NI-VISA / GPIB / SCPI instrument control

# Dev / build only
pyinstaller>=6.0       Standalone bundle builder
cairosvg               SVG → PNG conversion (for .ico generation in CI)
pytest>=7.4            Test runner
```

---

*This document was written against SanjINSIGHT v1.1.2 (2026-03-07).
Update it whenever significant architectural changes are made.*
