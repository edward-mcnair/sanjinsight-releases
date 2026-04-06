# SanjINSIGHT — Developer Guide

**Version**: 1.50.34-beta
**Platform**: Windows 10/11 (64-bit); macOS/Linux supported for development
**Stack**: Python 3.10 · PyQt5 · NumPy · PyInstaller · Inno Setup
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
9. [Plugin Architecture](#9-plugin-architecture)
10. [Auth & RBAC System *(Planned)*](#10-auth--rbac-system-planned-for-v150)
11. [Operator Shell *(Planned)*](#11-operator-shell-planned-for-v150)
12. [Configuration & Preferences](#12-configuration--preferences)
13. [Session Management](#13-session-management)
14. [Update System](#14-update-system)
15. [Event Bus & Logging](#15-event-bus--logging)
16. [Thread Safety Model](#16-thread-safety-model)
17. [Data Flow Diagrams](#17-data-flow-diagrams)
18. [Build & Release Pipeline](#18-build--release-pipeline)
19. [Testing](#19-testing)
20. [Adding a New Hardware Driver](#20-adding-a-new-hardware-driver)
21. [Adding a New UI Tab](#21-adding-a-new-ui-tab)
22. [Key Design Decisions](#22-key-design-decisions)
23. [Dependency Reference](#23-dependency-reference)

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
│   ├── cameras/               ← CameraDriver implementations (pypylon, ni_imaqdx, boson_driver, flir_driver, directshow, simulated)
│   ├── tec/                   ← TecDriver implementations
│   ├── fpga/                  ← FpgaDriver implementations
│   ├── bias/                  ← BiasDriver implementations
│   ├── stage/                 ← StageDriver implementations
│   ├── autofocus/             ← AutofocusDriver implementations
│   ├── turret/                ← ObjectiveTurretDriver implementations
│   └── ldd/                   ← LddDriver (laser diode) implementations
│
├── plugins/                   ← Plugin system (API v1)
│   ├── __init__.py            ← Public API exports
│   ├── base.py                ← Abstract base classes for 6 plugin types + PluginContext
│   ├── manifest.py            ← PluginManifest dataclass, validation
│   ├── loader.py              ← Discovery, license check, sandboxed import, activation
│   ├── registry.py            ← In-memory plugin store
│   ├── sandbox.py             ← Isolated module import
│   └── errors.py              ← PluginError exception hierarchy
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
│   ├── movie_pipeline.py      ← Burst-mode high-speed capture
│   ├── fps_optimizer.py       ← Auto-optimize acquisition throughput (LED → FPS → exposure)
│   ├── image_metrics.py       ← Shared stateless image-quality metrics (focus, intensity, stability)
│   ├── preflight.py           ← Pre-capture validation system (PreflightValidator, PreflightCheck, PreflightResult)
│   ├── rgb_analysis.py        ← Per-channel RGB thermoreflectance analysis utilities
│   ├── export_worker.py       ← QThread worker for background export
│   ├── report_worker.py       ← QThread worker for background report generation
│   ├── processing/
│   │   ├── image_rendering.py ← Shared render_array(), render_to_tmpfile(), render_to_b64()
│
├── ui/                        ← Qt5 UI components
│   ├── charts.py              ← PyQtGraph chart widgets (calibration, analysis, transient, sessions)
│   ├── app_signals.py         ← AppSignals singleton (application-wide Qt signals)
│   ├── sidebar_nav.py         ← Collapsible sidebar navigation (Manual mode)
│   ├── wizard.py              ← Guided workflow wizard (Auto mode)
│   ├── settings_tab.py        ← Preferences / AI setup / license / about
│   ├── settings/              ← Settings subsystem
│   │   ├── _helpers.py        ← Shared QSS/palette helper functions for settings UI
│   │   └── ai_section.py     ← AISettingsMixin (extracted from settings_tab.py)
│   ├── first_run.py           ← First-run hardware setup wizard
│   ├── device_manager_dialog.py ← Device discovery and management dialog
│   ├── update_dialog.py       ← Update badge and about dialog
│   ├── theme.py               ← Dual-mode (dark/light) theme system: palettes, QSS, QPalette
│   ├── icons.py               ← MDI icon registry (via qtawesome), IC class, set_btn_icon()
│   ├── font_utils.py          ← DPI-aware font scaling
│   ├── button_utils.py        ← Button state/style helpers
│   ├── notifications.py       ← Toast notification system
│   ├── license_dialog.py      ← License key entry / display dialog
│   ├── help.py                ← Help viewer
│   ├── scripting_console.py   ← Python REPL for power users
│   │
│   ├── tabs/                  ← Merged tabs (capture, transient_capture, camera_control, stimulus, library)
│   ├── dialogs/               ← Specialized dialogs (support bundle, etc.)
│   └── widgets/               ← Reusable widgets (image pane, temp plot, status header …)
│       ├── preflight_dialog.py ← Pre-capture validation dialog (modal, traffic-light results)
│       ├── segmented_control.py ← Shared pill-style SegmentedControl widget
│       ├── tab_helpers.py      ← Shared make_readout(), make_sub(), inner_tab_qss()
│       └── empty_state.py      ← Empty-state placeholder widget
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
│   ├── DeveloperGuide.md      ← This file
│   └── samples/
│       └── example_test.csv   ← Example thermoreflectance test data (20 rows, 8 columns)
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
                    main_app.py  (startup routing)
                          │
                          ▼
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
│  (Basler/FLIR/  (Meerstetter/ (NI 9637/    (Thorlabs/     │
│   NI/simulated)  simulated)   simulated)    simulated)     │
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
- **Auth is planned for v1.5.0.** The `auth/` package and `ui/operator/` shell do not exist yet. When implemented, auth will be opt-in — `auth.require_login` defaults to `false`.

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

#### Pre-flight Validation (all driver types)

Every base class declares a `preflight()` classmethod that each concrete driver overrides to verify its own dependencies *before* `DeviceManager` attempts to open hardware:

```python
@classmethod
def preflight(cls) -> tuple[bool, list[str]]:
    """
    Check that all runtime dependencies for this driver are available.

    Returns
    -------
    ok : bool
        True if the driver can be used; False if a hard dependency is missing.
    issues : list[str]
        Actionable human-readable strings shown to the user in the Device
        Manager dialog.  May be non-empty even when ok=True (warnings).
    """
    return (True, [])   # base-class default — always passes
```

`DeviceManager._connect_worker()` calls `preflight()` immediately after driver instantiation, before calling `connect()` or `open()`. Hard failures (`ok=False`) are surfaced as a formatted bullet list in the Device Manager error dialog. Non-blocking issues (`ok=True` with a non-empty list) are logged at `WARNING` level.

**Why `preflight()` exists:**
- Optional hardware SDKs (pypylon, nifpga, …) cannot always be bundled into the installer for every target system. Rather than a bare `ImportError` traceback, the user sees "pypylon not found — try reinstalling SanjINSIGHT" with a direct action. Note: pyMeCom is now bundled in the installer (installed from GitHub in the CI pipeline).
- All imports of optional packages are deferred to `open()` / `connect()` or to `preflight()` itself — never at module level — so the driver module can be safely imported even when its SDK is absent.

**Pre-flight coverage by driver:**

| Driver | Hard failure trigger | Warning trigger |
|---|---|---|
| `PylonDriver` | `pypylon.pylon` not importable | — |
| `BosonDriver` | — (SDK is bundled; always passes) | — |
| `FlirDriver` | `flirpy` not importable | — |
| `NiImaqdxDriver` | not Windows, or `niimaqdx.dll` not found | `ImaqdxAttr.exe` missing (exposure/gain unavailable) |
| `DirectShowDriver` | not Windows, or `cv2` not importable | — |
| `MeerstetterDriver` | `mecom` not importable | — |
| `MeerstetterLdd1121` | `mecom` not importable | — |
| `KeithleyDriver` | `pyvisa` not importable | — |
| `VisaGenericDriver` | `pyvisa` not importable | — |
| `RigolDP832Driver` | `pydp832` / `dp832` not importable | — |
| `Ni9637Driver` | `nifpga` not importable | — |
| `ThorlabsDriver` | `thorlabs_apt_device` not importable | — |
| `MpiProberDriver` | `serial` (pyserial) not importable | — |
| `OlympusLinxTurret` | `serial` (pyserial) not importable | — |
| All simulated drivers | — (always pass) | — |

#### Camera (`hardware/cameras/base.py — CameraDriver`)

```python
class CameraDriver(ABC):
    @classmethod
    def preflight(cls) -> tuple[bool, list[str]]: ...  # see Pre-flight Validation above

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

`CameraFrame` fields:

| Field | Type | Description |
|---|---|---|
| `data` | `np.ndarray` | Shape `(H, W)` for mono or `(H, W, 3)` for RGB |
| `frame_index` | `int` | Frame counter |
| `exposure_us` | `float` | Exposure time at capture |
| `gain_db` | `float` | Gain at capture |
| `timestamp` | `float` | `time.time()` at grab |
| `channels` | `int` | `1` = mono, `3` = RGB |
| `bit_depth` | `int` | Native sensor bit depth (e.g. 12, 14, 16) |

`CameraInfo` fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `driver` | `str` | `""` | Driver module name |
| `model` | `str` | `""` | Camera model string |
| `serial` | `str` | `""` | Serial number |
| `width` | `int` | `0` | Sensor width (px) |
| `height` | `int` | `0` | Sensor height (px) |
| `bit_depth` | `int` | `12` | Native sensor bit depth |
| `max_fps` | `float` | `0.0` | Maximum frame rate |
| `camera_type` | `str` | `"tr"` | `"tr"` (thermoreflectance) or `"ir"` (infrared) |
| `pixel_format` | `str` | `"mono"` | `"mono"`, `"bayer_rggb"`, `"rgb"`, or `"bgr"` |

**Flat-Field Correction (FFC):**

IR cameras (e.g. Boson) support FFC — a shutter-based non-uniformity correction. The base class provides two optional methods:

```python
def supports_ffc(self) -> bool:
    """Return True if this camera supports Flat-Field Correction."""
    return False

def do_ffc(self) -> bool:
    """Trigger a Flat-Field Correction. Returns True on success."""
    return False
```

Drivers that support FFC override both methods. `BosonDriver.do_ffc()` sends the FFC command via the FSLP serial SDK.

**Implementations**: `pypylon_driver.py` (Basler TR), `boson_driver.py` (FLIR Boson 320/640 via bundled Boson SDK (serial FSLP) + OpenCV UVC), `flir_driver.py` (Microsanj IR Camera via flirpy), `ni_imaqdx.py` (NI IMAQdx), `directshow.py` (OpenCV/DirectShow), `simulated.py`.

#### FLIR Boson Driver (`hardware/cameras/boson_driver.py`)

The Boson driver uses a two-channel architecture:

**Control channel** — `hardware/cameras/boson/` contains the FLIR Boson 3.0 Python SDK (pure-Python, no DLL). The package uses the FSLP serial protocol (`FSLP_PY_SERIAL` path). Structure:
- `ClientFiles_Python/` — FSLP client; SDK entry point is `BosonAPI`
- `CommunicationFiles/` — serial framing and packet layer

The control channel is optional. When `serial_port` is blank, `BosonDriver` skips SDK initialisation and operates in video-only mode.

**Video channel** — `cv2.VideoCapture(video_index)` with `cv2.VideoWriter_fourcc(*'Y16 ')` FOURCC to capture 14-bit radiometric data. `open()` validates that Y16 is actually negotiated and raises `RuntimeError` if a lower-bit-depth format is returned instead.

**Key public API:**

```python
driver.send_ffc()          # triggers Flat Field Correction (SDK control channel only)
driver.sdk_client          # property: BosonAPI instance, or None in video-only mode
```

**`BosonDriver.preflight()`** — always returns `(True, [])` since the SDK is bundled; no external install to check.

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

**Implementations**:

| Module | Driver key | Hardware | Protocol |
|---|---|---|---|
| `ni9637.py` | `ni9637` | NI 9637 / USB-6001 | NI-RIO / NI-DAQmx |
| `bnc745.py` | `bnc745` | BNC Model 745 | VISA (GPIB / USB / Serial) |
| `simulated.py` | `simulated` | — | — |

**BNC 745 extended interface** — implements `supports_trigger_mode() → True` and:
```python
def set_trigger_mode(self, mode: FpgaTriggerMode) -> None: ...  # CONTINUOUS | SINGLE_SHOT
def arm_trigger(self) -> None: ...         # fires one pulse (*TRG)
def set_pulse_duration(self, us: float) -> None: ...  # Ch1 width override
```
`FpgaTab.set_fpga_driver(driver)` reveals the Trigger Mode panel for any driver where `supports_trigger_mode()` is `True`.

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

**Implementations**:

| Module | Driver key | Hardware | Protocol |
|---|---|---|---|
| `keithley.py` | `keithley` | Keithley 24xx / 26xx | VISA (GPIB / USB / Ethernet) |
| `visa_generic.py` | `visa_generic` | Any SCPI instrument | VISA |
| `rigol_dp832.py` | `rigol_dp832` | Rigol DP832 / DP831 | VISA |
| `amcad_bilt.py` | `amcad_bilt` | AMCAD BILT pulsed I-V | TCP/SCPI → pivserver64.exe |
| `simulated.py` | `simulated` | — | — |

**AMCAD BILT extended interface** — adds beyond the base `BiasDriver`:
```python
def configure_pulse(self, *, channel: int, bias_v: float,
                    pulse_v: float, width_s: float, delay_s: float) -> None: ...
def apply_defaults(self) -> None:  # push PIV1.txt defaults to hardware
```
`BiasTab.set_bias_driver(driver)` reveals the BILT Pulse Configuration panel for `AmcadBiltDriver` instances. Gate (Ch 1) and Drain (Ch 2) are configured independently. `connect()` calls `apply_defaults()` automatically on first connection.

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

**Deduplication** uses `(address, uid)` composite keys — not address alone. This is required because multiple devices can share the same USB VID:PID (e.g. Meerstetter TEC-1089, ATEC, and LDD-1121 all use FTDI VID `0403` PID `6001`). The registry function `find_all_by_usb(vid, pid)` returns all matching entries for a given VID:PID pair.

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

**Connection sequence inside `_connect_worker()`:**

```
1. Instantiate driver class (no I/O yet)
2. Call driver.preflight()
   → ok=False  → raise RuntimeError with formatted issue list → ERROR state
   → ok=True, issues non-empty → log.warning() each issue, continue
3. Call driver.connect() / driver.open()
4. Start poll loop → CONNECTED
```

The pre-flight step ensures optional SDK dependencies are checked and reported as actionable user messages *before* any hardware I/O is attempted. See section 4.3 for the full driver coverage table.

**`_driver_key()` KEY_MAP** — maps device registry UID to the short factory key:

| Registry UID | Factory key | Factory |
|---|---|---|
| `ni_9637` / `ni_usb_6001` | `ni9637` | `create_fpga()` |
| `bnc_745` | `bnc745` | `create_fpga()` |
| `keithley_2400` / `keithley_2450` | `keithley` | `create_bias()` |
| `rigol_dp832` | `visa` | `create_bias()` |
| `amcad_bilt` | `amcad_bilt` | `create_bias()` |

**Special cfg remapping** — devices that need non-standard config keys before reaching their factory:
- **BNC 745**: `cfg["address"] = entry.address` (VISA resource string stored in `DeviceEntry.address`)
- **AMCAD BILT**: `cfg["host"] = entry.ip_address`, `cfg["port"] = desc.tcp_port` (TCP port 5035 from `DeviceDescriptor.tcp_port`; distinct from serial COM port in `cfg["port"]`)
- **FLIR Boson 320 / 640**: `cfg["serial_port"] = entry.address` (CDC serial port for FSLP control), `cfg["video_index"] = entry.video_index` (UVC device index). Width/height are injected from the registry (320×256 for `flir_boson_320`, 640×512 for `flir_boson_640`). `DeviceEntry.video_index` is a new `int` field (default `0`) persisted in device-params prefs.

**UI driver wiring** — after every hotplug event `main_app._on_device_hotplug()` calls:
```python
self._fpga_tab.set_fpga_driver(app_state.fpga if ok else None)
self._bias_tab.set_bias_driver(app_state.bias if ok else None)
```
This is what reveals the BNC 745 Trigger Mode panel and the AMCAD BILT Pulse Configuration panel at runtime.

---

## 5. Acquisition Pipeline

### 5.1 AcquisitionPipeline (`acquisition/pipeline.py`)

The core measurement loop. Given a camera (+ optional FPGA/bias for stimulus control), it captures alternating cold and hot image stacks, averages them, and computes ΔR/R.

**Full measurement sequence:**

```
 1. Run pre_capture_hooks (before cold phase)
 2. Set stimulus OFF  (FPGA.set_stimulus(False) or Bias.disable())
 3. Emit AcquisitionProgress(state=CAPTURING, phase="cold")
 4. Capture n_frames frames → accumulate as float64
 5. Average → cold_avg (float64); run post_average_hooks
 6. Wait inter_phase_delay seconds
 7. Run pre_capture_hooks (before hot phase)
 8. Set stimulus ON  (FPGA.set_stimulus(True) or Bias.enable())
 9. Emit AcquisitionProgress(phase="hot")
10. Capture n_frames frames → accumulate as float64
11. Average → hot_avg (float64); run post_average_hooks
12. Compute:  ΔR/R = (hot_avg - cold_avg) / cold_safe  (float64)
13. Mask dark pixels (cold intensity < 0.5% full scale) as NaN
14. Compute SNR_dB = 20·log10(mean|ΔR/R| / std(ΔR/R))
15. Emit AcquisitionResult
16. finally: _stimulus_safe_off() — guarantee DUT is unpowered
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
    cold_avg: np.ndarray           # float64, shape (H, W) or (H, W, 3) for RGB
    hot_avg: np.ndarray            # float64, shape (H, W) or (H, W, 3) for RGB
    delta_r_over_r: np.ndarray     # float64, shape (H, W) or (H, W, 3); NaN where dark
    difference: np.ndarray         # float64, shape (H, W) or (H, W, 3); hot − cold

    n_frames: int
    cold_captured: int
    hot_captured: int
    dark_pixel_count: int          # number of pixels masked as dark/noise
    dark_pixel_fraction: float     # fraction of NaN pixels in result (0.0–1.0)
    exposure_us: float
    gain_db: float
    timestamp: float               # time.time()
    duration_s: float
    snr_db: float                  # computed from ΔR/R excluding NaN pixels
    notes: str
```

### 5.3 ΔR/R Computation

```python
# Inputs: float64 arrays, shape (H, W) or (H, W, 3)
cold_safe = np.where(dark_mask, 1.0, cold)   # clamp dark pixels to avoid /0
drr = (hot - cold) / cold_safe

# Typical value range: ±1e-4 to ±1e-2
# (0.01% to 1% reflectance change per degree)

# Dark-pixel masking: pixels where cold intensity < 0.5% of full scale
# are set to NaN. For RGB data, the mask is computed on luminance
# (cold.mean(axis=2)) and broadcast to (H, W, 1) via np.newaxis.
drr[dark_mask] = np.nan
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

### 5.6 Pipeline Processing Hooks

The pipeline exposes two hook lists for extensibility without subclassing:

- **`pre_capture_hooks`** (`List[Callable[[], None]]`) — Run before each capture phase (cold and hot). Use cases include triggering external instruments, logging, or inserting settling delays.
- **`post_average_hooks`** (`List[Callable[[ndarray], ndarray]]`) — Transform the averaged frame after each phase completes. Each hook receives the float64 averaged array and must return a float64 array of the same shape.

Hooks are invoked in list order. A failing hook is logged at WARNING level but does not abort the acquisition.

```python
pipeline.pre_capture_hooks.append(lambda: fpga.arm_trigger())
pipeline.post_average_hooks.append(my_shading_correction)
```

### 5.7 Float64 Averaging

All pipeline averaging now uses **float64** (was float32 in earlier versions). Each frame is cast to `float64` before accumulation, and the averaged result remains float64 throughout the ΔR/R computation. This provides >15 significant digits of precision, eliminating rounding artefacts that were visible in low-signal (ΔR/R < 10⁻⁴) measurements when using float32.

### 5.8 Multi-Channel ΔR/R (RGB Cameras)

When cold and hot averages are `(H, W, 3)` (i.e. from a color camera), the pipeline handles them natively:

1. **Dark-pixel mask** — computed on the luminance channel (`cold.mean(axis=2)`) to produce a single 2D boolean mask.
2. **Mask broadcast** — the 2D mask is expanded to `(H, W, 1)` via `np.newaxis` and broadcast across all three channels for safe division and NaN insertion.
3. **ΔR/R result** — shape `(H, W, 3)`, where each channel contains an independent thermoreflectance signal at that wavelength.

Downstream code can use `rgb_analysis.split_channels()` to separate R/G/B maps, or `rgb_analysis.to_luminance()` to reduce to a single-channel Rec. 709 weighted map.

### 5.9 Pre-Capture Validation (`acquisition/preflight.py`)

`PreflightValidator` runs five read-only checks immediately before acquisition starts. It never modifies hardware state. Total runtime target: < 1.5 seconds.

**Checks performed:**

| Rule ID | Check | Pass | Warn | Fail |
|---|---|---|---|---|
| `PF_CAMERA` | Camera connected | Connected | — | Not connected |
| `PF_FPGA` | FPGA / stimulus connected | — | Not connected | — |
| `PF_STAGE` | Stage connected (scan only) | — | — | Not connected |
| `PF_EXPOSURE` | Exposure quality | Mean 30–80% DR | Outside ideal range | Mean < 15% or peak > 90% |
| `PF_STABILITY` | Frame-to-frame CV | CV < 0.005 | CV 0.005–0.02 | CV > 0.02 |
| `PF_FOCUS` | Laplacian variance | Score > 100 | Score 40–100 | Score < 40 |
| `PF_TEC_*` | TEC channel stability | Stable | Not at setpoint | — |

**Usage:**

```python
from acquisition.preflight import PreflightValidator
validator = PreflightValidator(app_state, metrics_snapshot=latest_metrics)
result = validator.run(operation="acquire")  # "acquire" | "scan" | "transient" | "movie"
if not result.passed:
    # show PreflightDialog, let user override or cancel
```

When all checks pass, acquisition starts immediately (no dialog). When any check is warn or fail, `PreflightDialog` (`ui/widgets/preflight_dialog.py`) displays a modal traffic-light summary. The user can proceed despite warnings or even failures.

`PreflightResult.to_dict()` is stored in the session metadata (`SessionMeta.preflight`) for post-hoc traceability.

### 5.10 Export Formats (`acquisition/export.py`)

| Format | Precision | Multi-channel handling | Notes |
|---|---|---|---|
| HDF5 | float64 (native) | Full `(H,W,3)` arrays preserved | Stored under `/arrays/*` |
| TIFF | float32 | Full `(H,W,3)` with `axes="YXC"` metadata; mono uses `axes="YX"` | float32 for file-size compatibility |
| CSV | text | Reduced to Rec. 709 luminance (`0.2126·R + 0.7152·G + 0.0722·B`) | Inherently 2D |
| NumPy (`.npy`) | float64 (native) | Full array preserved | Direct `np.save` |
| MATLAB (`.mat`) | float64 | Full array preserved | Via `scipy.io.savemat` |

### 5.11 New Module APIs (v1.5.0)

#### FpsOptimizer (`acquisition/fps_optimizer.py`)

Auto-optimizes acquisition throughput using a three-step priority: maximize LED duty cycle, maximize frame rate, then binary-search exposure to hit a target intensity fraction.

```python
from acquisition.fps_optimizer import FpsOptimizer

optimizer = FpsOptimizer(camera, fpga=fpga_driver, target_intensity=0.0)
# target_intensity=0.0 → uses default 0.70 (70% of dynamic range)

summary = optimizer.optimize()
# Returns dict:
#   duty_cycle:      float  — final FPGA duty cycle (0–1)
#   fps:             float  — camera max_fps after optimization
#   exposure_us:     float  — final camera exposure (μs)
#   mean_intensity:  float  — measured image mean (fraction of full scale)
#   skipped:         bool   — True if camera is IR (no optimization possible)
```

IR cameras (e.g. Boson) have no user-controllable FPS or exposure; `optimize()` returns immediately with `skipped=True`.

#### PreflightValidator (`acquisition/preflight.py`)

Read-only pre-capture validation. See section 5.9 for check details.

```python
from acquisition.preflight import PreflightValidator, PreflightResult

validator = PreflightValidator(app_state, metrics_snapshot=latest_metrics)
result = validator.run(operation="acquire")
# operation: "acquire" | "scan" | "transient" | "movie"

result.passed        # bool — True if no checks failed
result.has_warnings  # bool — True if any check is "warn"
result.all_clear     # bool — True if every check is "pass"
result.duration_ms   # float — wall-clock time for all checks
result.to_dict()     # dict — serializable for session metadata
```

#### Image Metrics (`acquisition/image_metrics.py`)

Stateless, pure-NumPy image-quality functions. No Qt, no hardware, no side-effects.

```python
from acquisition.image_metrics import (
    compute_focus, compute_intensity_stats, compute_frame_stability,
)

# Focus score: variance of discrete Laplacian on 4x downsampled frame.
# Higher = sharper. Multi-channel input is reduced to luminance.
score = compute_focus(data)  # -> float

# Exposure statistics as fractions of dynamic range.
stats = compute_intensity_stats(data, bit_depth=12)
# Returns dict: mean_frac, max_frac, sat_pct, under_pct

# Frame-to-frame stability: coefficient of variation across per-frame means.
# Returns 0.0 if fewer than 2 values or mean is zero.
cv = compute_frame_stability(means_list)  # -> float
```

#### RGB Analysis (`acquisition/rgb_analysis.py`)

Per-channel RGB thermoreflectance utilities for color-camera data.

```python
from acquisition.rgb_analysis import (
    split_channels, to_luminance, per_channel_stats, per_channel_analysis,
)

# Split (H,W,3) ΔR/R into individual channel maps.
# Returns {"red": (H,W), "green": (H,W), "blue": (H,W)} for RGB,
# or {"mono": (H,W)} for single-channel input.
channels = split_channels(drr_rgb)

# Convert (H,W,3) to (H,W) using Rec. 709 weights.
# Y = 0.2126·R + 0.7152·G + 0.0722·B. Returns input unchanged if 2D.
lum = to_luminance(drr_rgb)

# Per-channel statistics: mean, std, min, max, peak_abs for each channel.
stats = per_channel_stats(drr_rgb)

# Run the analysis engine on each channel independently.
# Returns {channel_name: AnalysisResult} for each channel.
results = per_channel_analysis(drr_rgb, analysis_engine, calibration=cal)
```

---

## 6. User Interface

### 6.1 MainWindow (`main_app.py`)

`MainWindow(QMainWindow)` is the top-level window. It:

- Instantiates `HardwareService`, `SessionManager`, `ApplicationState`, `AppSignals`
- Builds two navigation modes: **Auto** (wizard) and **Manual** (sidebar)
- Connects all Qt signals from `HardwareService` to slot methods
- Manages the central stack widget (switches between Auto and Manual views)

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

**Auto Mode** (`ui/wizard.py`):
- `StandardWizard` — guided step-by-step measurement workflow
- Steps: Select Profile → Configure Camera → Set Temperature → Acquire → View Result
- Suitable for new users and routine measurements

**Manual Mode** (`ui/sidebar_nav.py`):
- Collapsible sidebar with 12 items grouped by category:
  - **ACQUIRE**: Live, Capture (Single/Grid), Transient (Transient/Movie)
  - **ANALYZE**: Calibration, Analysis, Sessions
  - **HARDWARE** (collapsible): Camera (Camera/ROI/Autofocus), Stimulus (Modulation/Bias Source), Temperature, Stage, Prober
  - **LIBRARY**: Library (Profiles/Recipes)
  - Settings

### 6.3 AppSignals (`ui/app_signals.py`)

A singleton `QObject` that holds application-wide signals. Tabs emit and connect to signals here rather than passing references between widgets:

```python
signals = AppSignals()
signals.session_saved.emit(session_uid)     # Any tab can emit
signals.session_saved.connect(callback)     # Any tab can connect
```

Key signals: `session_saved`, `profile_changed`, `hardware_ready`, `demo_mode_changed`, `license_changed`.

### 6.4 StatusHeader (`ui/widgets/status_header.py`)

The PALETTE-themed header bar at the top of the window. Shows:
- Logo and profile pill
- `ConnectedDevicesButton` — dropdown showing hardware connection status
- E-Stop button
- Mode indicator (Auto / Manual)
- Demo Mode banner (blue, `_DEMO_BLUE = "#3d8bef"`) when in demo mode

**Signals:**
- `exit_demo_requested` — emitted when user clicks the demo banner
- `admin_login_requested` — emitted when "Log in" button is clicked
- `admin_logout_requested` — emitted when "Log out" button is clicked

### 6.5 Notifications (`ui/notifications.py`)

Toast-style notifications appearing in the bottom-right corner:

```python
from ui.notifications import show_toast
show_toast(parent_widget, "Acquisition complete", level="success", duration_ms=3000)
# Levels: "info", "success", "warning", "error"
```

### 6.6 Theme (`ui/theme.py`)

Dual-mode theme system supporting Auto (OS-adaptive), Dark, and Light modes. The module provides:

- **`_DARK_RAW` / `_LIGHT_RAW`** — raw palette dictionaries for each mode
- **`PALETTE`** — a live mutable dict updated in-place by `set_theme(mode)`. All widgets reference `PALETTE["key"]` and get the current theme's values without re-importing
- **`build_style(mode)`** — generates a master QSS string (~670 lines) for all widget classes
- **`build_qt_palette(mode)`** — generates a `QPalette` for native Qt widgets
- **`detect_system_theme()`** — OS detection (macOS/Windows/Linux), fallback `"dark"`
- **17 QSS helper functions** — `btn_primary_qss()`, `btn_danger_qss()`, `input_qss()`, `status_pill_qss()`, `groupbox_qss()`, etc. for consistent widget styling

Theme preference is stored as `config.get_pref("ui.theme", "auto")` with three options controlled by a `SegmentedControl` in Settings → Appearance. When set to `"auto"`, a 5-second polling timer (`MainWindow._poll_system_theme()`) detects OS theme changes.

**Theme switching (`_swap_visual_theme()`):**

The method uses a colour-rewrite strategy to update inline stylesheets without losing font/layout properties:

1. Snapshots all PALETTE hex values before `set_theme()` updates them
2. Builds an old→new colour remap (only entries that changed)
3. For each widget: rewrites stale hex values in its inline stylesheet, then calls `unpolish()` / `polish()` / `_apply_styles()` / `update()`

This preserves `font-size`, `font-weight`, `padding`, and all non-colour CSS properties while updating every colour to the new theme. Widgets with `_apply_styles()` re-apply any specialised styling with current PALETTE values.

**Widget theme contract:**

Persistent widgets that set inline stylesheets should implement `_apply_styles(self)` and re-apply all construction-time styling with current `PALETTE`/`FONT` values. This method is called automatically by `_swap_visual_theme()`. Sidebar palette helpers (`_BG()`, `_ACCENT()`, etc.) are functions, not snapshots, ensuring live updates.

### 6.7 Charts (`ui/charts.py`)

All interactive data charts are in the `ui/charts` module backed by **PyQtGraph** (`pyqtgraph>=0.13.3`). The module is designed for graceful degradation: if PyQtGraph is not installed, every widget falls back to a plain `QLabel` placeholder without crashing.

**Availability guard:**

```python
try:
    import pyqtgraph as pg
    pg.setConfigOption("antialias", True)
    _PG_OK = True
except ImportError:
    pg = None
    _PG_OK = False

_PlotBase = pg.PlotWidget if _PG_OK else QWidget
```

**Available widgets:**

| Class | Location | Description |
|---|---|---|
| `CalibrationQualityChart` | Calibration tab → Quality ✦ | R² histogram + C_T histogram + curve scatter |
| `AnalysisHistogramChart` | Analysis panel | ΔT pixel distribution with threshold line |
| `TransientTraceChart` | Transient tab | Time-resolved waveform with cursor line |
| `SessionTrendChart` | Sessions panel | SNR and TEC temperature over saved sessions |
| `dTSparklineWidget` | Main window (below content) | Rolling 2-minute dT stability strip |

**PALETTE integration:**

Each chart calls `_configure_plot(pw)` in `_apply_styles()`, which sets `pw.setBackground(PALETTE["bg"])`, axis pen colours, and grid alpha from the live `PALETTE` dict. Call `_apply_styles()` on each chart widget from `MainWindow._swap_visual_theme()` to re-theme on dark/light switch.

**Adding a new chart:**

1. Subclass `QWidget` (not `_PlotBase`); create internal `StyledPlotWidget` or `pg.PlotWidget` instances as children.
2. Implement `update_data(result)` with a duck-typed `result` argument.
3. Implement `_apply_styles()` that re-calls `_configure_plot()` on every internal plot.
4. Guard all `pg.*` usage with `if not _PG_OK: return`.
5. Add a `clear()` method that resets all plot items to empty datasets.

---

## 7. AI Assistant & Diagnostics

### 7.1 AI Service (`ai/ai_service.py`)

Multi-backend AI service. The active backend is selected in Settings:

| Backend | Module | Requirements |
|---|---|---|
| Local LLM | `model_runner.py` (llama-cpp-python) | Downloaded model file |
| Ollama | `remote_runner.py` (provider="ollama") | Ollama installed locally |
| Claude API | `remote_runner.py` (provider="anthropic") | User's Anthropic API key |
| ChatGPT API | `remote_runner.py` (provider="openai") | User's OpenAI API key |

**Context injected with every prompt:**
1. Quickstart Guide (always, ~2,500 tokens — STANDARD/FULL tier only)
2. User Manual sections matched to the active tab (RAG, up to ~8,000 tokens — FULL tier only)
3. Instrument knowledge (`ai/instrument_knowledge.py` — hardware limits, CTR table, system specs, ~80 tokens)
4. Live metrics snapshot (SNR, saturation, temperature)
5. Active material profile (C_T, wavelength)
6. Active modality and camera type

### 7.2 AI Capability Tiers (`ai/tier.py`)

Features are gated by `AITier`, an IntEnum determined by model size and backend:

| Tier | Value | Trigger |
|---|---|---|
| `NONE` | 0 | No model loaded |
| `BASIC` | 1 | Small local model (< 4B parameters) |
| `STANDARD` | 2 | Medium local model, or Ollama backend |
| `FULL` | 3 | Cloud providers (Claude, ChatGPT) |

**Feature gating** via `AIService.can(feature_name)`:

| Feature | Required tier | Description |
|---|---|---|
| `chat` | BASIC | Free-form chat |
| `explain_tab` | BASIC | Tab explanation |
| `diagnose` | STANDARD | Manual diagnose |
| `proactive_advisor` | STANDARD | Profile conflict advisor |
| `session_report` | FULL | Post-acquisition quality report |
| `manual_rag` | FULL | User Manual retrieval |

Each tier has a token budget (`budget_for(tier)`) controlling history depth, context inclusion, and max tokens per response.

### 7.3 Proactive AI Advisor (`ai/advisor.py`)

The advisor fires automatically after every profile selection. It bypasses the normal `_run()` pipeline (no history injection) and calls `infer()` directly on the active runner.

**Key components:**
- `_MODALITY_CONTEXT` — Registry mapping modality strings to physics context. Add an entry here to support a new camera/modality plugin.
- `_build_advisor_system(cloud, modality)` — Adapts the system prompt to the measurement technique.
- `build_advisor_prompt(...)` — Builds the `[system, user]` message list with profile, instrument state, and diagnostic issues.
- `profile_to_summary(profile, camera_type)` — Extracts key profile fields; gates C_T and wavelength to TR-only, but includes `gain_db` for all camera types.
- `parse_advice(raw_text)` — Extracts JSON from the response (handles ```` ```json ``` ```` fences and bare JSON). Returns `AdvisorResult` with `parse_ok=False` for fallback display.

**Retry on parse failure:** If JSON parsing fails, the advisor appends a correction message and re-fires once with `temperature=0.0`.

**Race condition handling:** If the AI is already busy (e.g. auto-diagnosis), `_maybe_launch_advisor()` cancels the current inference, disconnects handlers, and retries with exponential polling (200ms, max 15 retries / 3s).

### 7.4 Auto-Diagnosis

Hardware errors (via `hw_service.log_message`) are queued and drained every 3 seconds by `_drain_auto_diagnose()`. The diagnosis:
- Uses `infer()` directly (not `ask()`) to avoid polluting chat history
- Stores signal handlers on `self` so they can be cleanly disconnected if the advisor preempts
- Routes output to the log panel only (no chat panel, no toasts)
- Is throttled to once per 30 seconds and yields to the advisor

### 7.5 Diagnostic Engine (`ai/diagnostic_engine.py`)

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

### 7.6 Context Builder (`ai/context_builder.py`)

Assembles a compact JSON snapshot of all instrument state (< 800 tokens). Includes:
- Camera (type, driver type, exposure, gain, fps, resolution)
- FPGA, Stage, Bias, LDD, TECs, Prober
- Active modality and objective
- System model specs (EZ500, NT220, PT410A)
- Active material profile
- Metrics snapshot and diagnostic rule results
- Fallback `context_incomplete` flag if any section throws

### 7.7 Manual RAG (`ai/manual_rag.py`)

Loads `docs/UserManual.md`, splits it into sections, and retrieves relevant sections based on keyword overlap with the user's query and the active tab name. This keeps context token usage bounded while ensuring the AI has relevant documentation. Available at FULL tier only.

### 7.8 Session Logging & Crash Recovery (`logging_config.py`)

- `open_session_log()` — Truncates `~/.microsanj/logs/session.log` and deletes `.clean_exit` marker
- `write_session(line)` — Appends to session log (line-buffered for crash resilience)
- `mark_clean_exit()` — Called from `MainWindow.closeEvent()`; writes `.clean_exit` marker
- `previous_crash_log()` — Returns session log contents if `.clean_exit` marker is absent

**Startup order:** `previous_crash_log()` must be called *before* `open_session_log()` (which truncates the file). The crash dialog is shown via `QTimer.singleShot(800ms)` after the main window is visible.

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
    DEVELOPER  = "developer"    # Plugin SDK access
    SITE       = "site"
```

Tier hierarchy: `UNLICENSED < STANDARD < DEVELOPER < SITE`. The Developer tier gates plugin loading and was added for internal Microsanj add-on products and third-party plugin developers.

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

## 9. Plugin Architecture

### 9.1 Overview

SanjINSIGHT supports a plugin system that allows extending the application with custom hardware panels, analysis views, tool panels, bottom-drawer tabs, hardware drivers, and analysis pipelines. Plugins are discovered at startup from the user-writable directory `~/.microsanj/plugins/`.

The plugin system is designed primarily for internal Microsanj development of add-on products (e.g. POSH-TDTR, NOSH-TDTR) that share SanjINSIGHT's infrastructure but have fundamentally different measurement modalities. Third-party plugins are also supported for customers with a **Developer** or **Site** license tier.

### 9.2 Package Structure

```
plugins/
    __init__.py           Public API exports
    base.py               Abstract base classes for all 6 plugin types + PluginContext
    manifest.py           PluginManifest dataclass, validation, API version
    loader.py             Discovery, license check, sandboxed import, activation
    registry.py           In-memory store: register / unregister / get / get_by_type
    sandbox.py            Isolated module import under _sanjinsight_plugins namespace
    errors.py             PluginError hierarchy (manifest, load, license, dependency, API)
```

### 9.3 Plugin Types

| Type | Base Class | UI Slot | Use Case |
|------|-----------|---------|----------|
| `hardware_panel` | `HardwarePanelPlugin` | Sidebar HARDWARE section | Custom device control panel |
| `analysis_view` | `AnalysisViewPlugin` | Sidebar ANALYZE section | Custom analysis / results view |
| `tool_panel` | `ToolPanelPlugin` | Sidebar TOOLS section | General-purpose utility |
| `drawer_tab` | `DrawerTabPlugin` | Bottom drawer (Console/Log area) | Diagnostics, live data feeds |
| `hardware_driver` | `HardwareDriverPlugin` | None (device registry) | Device driver without UI |
| `analysis_pipeline` | `AnalysisPipelinePlugin` | None (pipeline registry) | Data processing pipeline |

### 9.4 Plugin Lifecycle

```
Startup
  1. PluginLoader.discover_and_load() scans ~/.microsanj/plugins/*/manifest.json
  2. Each manifest is parsed and validated (PluginManifest.validate())
  3. License tier check: manifest.min_license_tier vs app_state.license_info.tier
  4. Platform filter: manifest.platforms checked against sys.platform
  5. Disabled check: config preference plugins.<id>.enabled
  6. Module imported under sandboxed namespace: _sanjinsight_plugins.<safe_id>.<module>
  7. Plugin class instantiated and validated against expected base class
  8. PluginContext built (hw_service, app_state, signals, event_bus, config, data_dir, logger)
  9. plugin.activate(context) called
 10. Plugin registered in PluginRegistry

Shutdown
  1. PluginRegistry.deactivate_all() iterates all registered plugins
  2. plugin.deactivate() called on each
  3. Sandboxed sys.modules entries cleaned up
```

### 9.5 Integration with MainWindow

Plugin wiring happens in `MainWindow._wire_plugins()`:

```python
def _wire_plugins(self):
    loader = PluginLoader(app_state, hw_service, signals, event_bus, config)
    self._plugin_registry = loader.discover_and_load()

    for plugin in self._plugin_registry.get_by_type("hardware_panel"):
        panel = plugin.create_panel()
        self._nav.add_item("HARDWARE", plugin.nav_label, plugin.nav_icon, panel)

    for plugin in self._plugin_registry.get_by_type("tool_panel"):
        panel = plugin.create_panel()
        self._nav.add_item("TOOLS", plugin.nav_label, plugin.nav_icon, panel)

    for plugin in self._plugin_registry.get_by_type("drawer_tab"):
        tab = plugin.create_tab()
        self._drawer.add_tab(tab, plugin.tab_label, plugin.tab_icon)

    for plugin in self._plugin_registry.get_by_type("hardware_driver"):
        descriptor = plugin.get_device_descriptor()
        register_external(descriptor)
```

### 9.6 PluginContext

Every plugin receives a `PluginContext` dataclass on activation, providing sandboxed access to application services:

| Field | Type | Description |
|-------|------|-------------|
| `hw_service` | `HardwareService` | Device control (set_exposure, start_fpga, etc.) |
| `app_state` | `ApplicationState` | Thread-safe global state (cam, tecs, stage, etc.) |
| `signals` | `AppSignals` | Application-wide Qt signals |
| `event_bus` | `EventBus` | Publish/subscribe event bus |
| `config` | module | Configuration and preferences |
| `data_dir` | `Path` | Plugin-specific data directory (`~/.microsanj/plugins/<id>/data/`) |
| `logger` | `Logger` | Pre-configured logger (`sanjinsight.plugin.<id>`) |

### 9.7 Theme Integration

Plugins receive theme change notifications through the `register_theme_listener()` API in `ui/theme.py`. When the user switches between Dark/Light/Auto themes:

1. `set_theme(mode)` updates the global `PALETTE` dict
2. All registered theme listeners are called with the new mode
3. Plugin base class provides `on_theme_changed(mode)` for override

### 9.8 Manifest Schema

Each plugin directory must contain a `manifest.json`:

```json
{
  "id": "com.microsanj.posh-tdtr",
  "name": "POSH-TDTR Module",
  "version": "1.0.0",
  "api_version": 1,
  "plugin_type": "hardware_panel",
  "entry_point": "plugin.py",
  "class_name": "PoshTdtrPlugin",
  "min_license_tier": "developer",
  "author": "Microsanj",
  "description": "Picosecond optical sampling heating for thermal property extraction",
  "platforms": ["win32", "darwin", "linux"],
  "min_app_version": "1.5.0"
}
```

### 9.9 License Gating

Plugin loading is gated by the `min_license_tier` field in the manifest. The tier hierarchy is:

```
UNLICENSED < STANDARD < DEVELOPER < SITE
```

- **Standard** tier: can use plugins with `min_license_tier: "standard"` (none currently)
- **Developer** tier: can use internal Microsanj plugins and custom extensions
- **Site** tier: full access to all plugins

The `DEVELOPER` tier was added specifically for plugin SDK access and sits between Standard and Site.

### 9.10 External Driver Registration

Hardware driver plugins register with the device registry via `register_external(descriptor)`. This allows plugin-provided cameras, stages, or other devices to appear in Device Manager alongside built-in drivers.

### 9.11 Settings UI

The Settings panel includes a **Plugins** group (visible when plugins are installed) showing:
- Plugin name, version, type badge, and enable/disable toggle
- "Open Plugins Folder" button to open `~/.microsanj/plugins/` in the file manager
- Enable/disable state persisted to user preferences

### 9.12 Testing

Plugin system tests are in `tests/test_plugin_system.py` (29 tests covering manifest validation, sandboxed import, registry operations, loader lifecycle, theme listeners, and external driver registration).

For the complete plugin developer API, see `docs/PluginDevelopmentGuide.md`.

---

## 10. Auth & RBAC System *(Planned for v1.5.0)*

> **Note:** This section describes the planned authentication and role-based access control system. It is not yet implemented — the `auth/` package does not exist in the current codebase. The design is documented here for forward reference.

Key planned features:
- **User types**: Technician (Operator Shell), Failure Analyst (full UI), Researcher (full UI)
- **Admin privilege overlay** — any user type can have `is_admin=True`
- **SQLite user store** at `~/.microsanj/users.db` with bcrypt password hashing
- **Audit logging** — JSON Lines to `~/.microsanj/audit.log` (5 MB rotation)
- **Inactivity lock** — configurable timeout (default 30 min)
- **Per-user preferences** — `~/.microsanj/users/{uid}/prefs.json`
- **LDAP stub** — overridable `_verify_credentials()` for future LDAP integration

When `auth.require_login` is `false` (the default), the auth system is bypassed entirely and the application behaves identically to pre-auth versions.

---

## 11. Operator Shell *(Planned for v1.5.0)*

> **Note:** This section describes the planned Operator Shell UI for Technician users. It is not yet implemented — `ui/operator/` does not exist in the current codebase.

Key planned features:
- **`OperatorShell(QMainWindow)`** — simplified three-panel layout (Recipe Selector, Scan Work Area, Shift Log)
- **Locked recipe profiles** — operators can only run approved scan profiles
- **Barcode scanner support** — `returnPressed` on Part ID field auto-starts scan
- **Verdict overlay** — full-screen PASS/FAIL/REVIEW modal after each scan
- **Auto PDF generation** — report saved to session directory automatically
- **Supervisor override** — engineer credentials grant temporary elevated access (15-min timeout)

---

## 12. Configuration & Preferences

### 11.1 System Configuration (`config.yaml`)

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

### 11.2 User Preferences (`~/.microsanj/preferences.json`)

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

## 13. Session Management

### 12.1 Session Structure on Disk

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

### 12.2 SessionMeta Fields

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
| `camera_id` | str | Hardware identity (e.g. `"TR-Andor-iStar-SN12345"`) *(v2)* |
| `notes_log` | List[dict] | Structured append-only notes (NoteEntry dicts) *(v2)* |
| `frame_channels` | int | `1` (mono) or `3` (RGB) *(v3)* |
| `frame_bit_depth` | int | Native sensor bit depth (12, 14, 16) *(v3)* |
| `pixel_format` | str | `"mono"`, `"bayer_rggb"`, or `"rgb"` *(v3)* |
| `preflight` | Optional[dict] | PreflightResult snapshot, or None *(v3)* |
| `schema_version` | int | For migrations (currently 5) |

### 12.3 Loading Sessions

Arrays are lazy-loaded — only read from disk when accessed:

```python
session = Session.load("/path/to/session_dir")
drr = session.delta_r_over_r    # Loads delta_r_over_r.npy on first access
session.unload()                 # Frees memory
```

### 12.4 Schema Migrations (`acquisition/schema_migrations.py`)

When a new field is added to `SessionMeta`, a migration function bumps `schema_version` and fills in the default value for old sessions. Migrations run automatically on `Session.load()`.

**Current schema version: 3** (`CURRENT_SCHEMA = 3`).

| Migration | Fields Added | Defaults |
|---|---|---|
| v0 → v1 | `schema_version` | `1` |
| v1 → v2 | `camera_id`, `notes_log` | `""`, `[]` |
| v2 → v3 | `frame_channels`, `frame_bit_depth`, `pixel_format`, `preflight` | `1`, `16`, `"mono"`, `None` |

**v3 fields detail:**

| Field | Type | Description |
|---|---|---|
| `frame_channels` | `int` | `1` (mono) or `3` (RGB) — matches `CameraFrame.channels` |
| `frame_bit_depth` | `int` | Native sensor bit depth (12, 14, or 16). Defaults to `16` for migrated sessions (conservative upper bound since the original depth cannot be inferred). |
| `pixel_format` | `str` | `"mono"`, `"bayer_rggb"`, or `"rgb"` — matches `CameraInfo.pixel_format` |
| `preflight` | `Optional[dict]` | `PreflightResult.to_dict()` snapshot captured before acquisition, or `None` if preflight was not run. Contains the full list of checks, pass/warn/fail status, and timing. |

When loading a session written by a *newer* version of the software (schema > CURRENT_SCHEMA), unknown fields are silently ignored and a warning is logged.

---

## 14. Update System

### 13.1 UpdateChecker (`updater.py`)

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
checker = UpdateChecker(current_version="1.4.1", on_update=my_callback)
checker.check_async()    # Non-blocking background thread
result = checker.check_sync()   # Blocking (used for "Check Now" button)
```

`on_update(UpdateInfo)` is called on the background thread if a newer version is found.
`UpdateInfo` has: `latest_version`, `release_notes`, `download_url`, `release_page_url`.

---

## 15. Event Bus & Logging

### 14.1 EventBus (`events/event_bus.py`)

Central dispatcher for application-wide events:

```python
from events.event_bus import emit_info, emit_warning, emit_error

emit_info("acquisition", "acq_complete", "Acquisition finished", snr_db=34.2)
emit_warning("tec", "temp_unstable", "TEC not stable", actual=25.3, target=25.0)
emit_error("camera", "grab_timeout", "Camera frame grab timed out")
```

Events are stored in `TimelineStore` (`~/.microsanj/timeline.jsonl`) as newline-delimited JSON for audit trails and debugging.

### 14.2 Python Logging

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

## 16. Thread Safety Model

| Mechanism | Used for |
|---|---|
| `ApplicationState` (RLock) | Protecting hardware driver references |
| `threading.Event` (`_stop_event`) | Signaling background threads to exit |
| `threading.Event` (`_cam_preview_free`) | Camera frame back-pressure |
| `DeviceManager._lock` | Device state machine transitions |
| `SessionManager._lock` (RLock) | Protecting session index and atomic metadata writes |
| Qt signals (auto-queued) | Cross-thread GUI updates |

**Rule**: Background threads (hardware poll loops, acquisition pipeline) **never** call any Qt widget methods directly. They emit signals, which Qt queues to the GUI thread automatically.

**Rule**: All reads/writes of hardware driver references use `with app_state:` to avoid races during hotplug.

**Rule**: `AcquisitionPipeline.run()` (blocking) must be called from a non-GUI thread. `AcquisitionPipeline.start()` (non-blocking) spawns its own thread internally.

**Rule**: `SessionManager._update_field()` holds its RLock through the entire read-modify-write cycle (in-memory update + JSON file write). File writes use atomic operations (write to `.tmp`, then `os.replace()`) to prevent corruption on process crash.

---

## 17. Data Flow Diagrams

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

## 18. Build & Release Pipeline

### 17.1 GitHub Actions (`.github/workflows/build-installer.yml`)

**Triggers:**
- `git push origin v1.5.0-beta.1` — builds + creates GitHub Release on `sanjinsight`
- Manual **Run workflow** in Actions UI — builds only (artifact available for 1 day)

**Steps:**
1. Checkout on `windows-latest` runner
2. Python 3.10 + pip dependencies (3.10 required for FLIR PySpin wheel compatibility)
3. Install optional GitHub-only drivers (pyMeCom, pydp832) — failures are non-fatal
4. Download redistributable drivers (VC++ Redist, FTDI CDM) to `installer/redist/`
5. Convert `assets/microsanj-logo.svg` → `installer/assets/sanjinsight.ico`
6. Generate `installer/version_info.txt` (Windows VERSIONINFO)
7. **PyInstaller** → `dist/SanjINSIGHT/` (self-contained bundle)
8. **Inno Setup** → `installer_output/SanjINSIGHT-Setup-X.Y.Z.exe` (bundles VC++ Redist + FTDI CDM driver)
9. Extract release notes from `CHANGELOG.md`
10. **Create GitHub Release** on `edward-mcnair/sanjinsight` with `.exe` attached

### 17.2 Release Procedure

```bash
# 1. Update version
# Edit version.py: __version__, PRERELEASE, VERSION_TUPLE, BUILD_DATE
# Beta example:  __version__ = "1.5.0-beta.1",  PRERELEASE = "beta.2"
# GA example:    __version__ = "1.4.1",          PRERELEASE = ""

# 2. Update CHANGELOG.md: add ## [1.5.0-beta.1] — YYYY-MM-DD section

# 3. Commit
git add version.py CHANGELOG.md
git commit -m "chore: bump to v1.5.0-beta.1"

# 4. Tag and push — this triggers CI
git tag v1.5.0-beta.1
git push origin main
git push origin v1.5.0-beta.1

# 5. CI builds installer and publishes release automatically
# 6. Verify at https://github.com/edward-mcnair/sanjinsight-releases/releases
```

### 17.3 Local Windows Build (manual)

Use `build_installer.bat` which handles all steps automatically:

```bash
cd installer
build_installer.bat 1.4.1
```

The script:
1. Verifies the Python interpreter
2. Installs dependencies from `requirements.txt`
3. Installs optional GitHub-only drivers (pyMeCom, pydp832)
4. Downloads VC++ Redistributable and FTDI CDM driver to `redist/`
5. Runs PyInstaller with the spec file
6. Runs Inno Setup to produce the final installer

For manual builds without the batch script:
```bash
pip install pyinstaller pillow cairosvg
pip install git+https://github.com/meerstetter/pyMeCom
pyinstaller installer/sanjinsight.spec --noconfirm --clean
python installer/gen_version_info.py
# Then open Inno Setup and compile installer/setup.iss
```

### 17.4 CI Test Runner (`.github/workflows/ci.yml`)

Runs on every push and PR:

```bash
pytest tests/
```

CI requires `CHANGELOG.md` to have an entry for the current version in `version.py`.

---

## 19. Testing

```bash
# Run all tests
pytest tests/

# Run a specific file
pytest tests/test_pipelines.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

**Test files:**

| File | Tests | Covers |
|---|---|---|
| `test_core.py` | ~80 | Config, calibration, session save/load, profiles, modality |
| `test_ai.py` | ~40 | AI service, diagnostic rules, metrics engine |
| `test_pipelines.py` | ~60 | Acquisition pipeline, abort, result structure |
| `test_widgets.py` | ~30 | Qt widget initialization, signals, saturation guard |
| `test_integration.py` | ~50 | End-to-end workflows with simulated hardware |
| `test_hardware.py` | ~30 | Camera drivers, preflight interface, hardware service |
| `test_measurement_orchestrator.py` | 36 | Orchestrator state machine, grade gate, post-capture |
| `test_device_services.py` | 30 | BaseDeviceService, retry, reconnect, HardwareService |
| `test_workflows.py` | 38 | Workflow profiles, registry, backward-compat shims |
| `test_improvements.py` | 31 | UX improvements: undo, checkpoint, batch widget, config backup |

**Total: ~490 tests** (16 skipped for optional dependencies like `reportlab`).

All hardware tests use simulated drivers — no real hardware required to run the suite.

**CI:** GitHub Actions runs syntax checks and the full test suite on every push to `main`, `develop`, and `feature/**` branches. See `.github/workflows/ci.yml`.

---

## 20. Adding a New Hardware Driver

Example: adding a new camera driver `acme_cam.py`.

**Step 1 — Implement the driver:**

```python
# hardware/cameras/acme_cam.py
from hardware.cameras.base import CameraDriver, CameraFrame
import time, numpy as np

class AcmeCameraDriver(CameraDriver):

    # ── Pre-flight (REQUIRED) ──────────────────────────────────────────────
    @classmethod
    def preflight(cls) -> tuple:
        """Check runtime dependencies before DeviceManager attempts to open hardware."""
        issues = []
        try:
            import acme_sdk   # noqa: F401
        except ImportError:
            issues.append(
                "acme_sdk not found — ACME camera support is unavailable.\n"
                "Download and install the ACME SDK from acme.example.com."
            )
        return (len(issues) == 0, issues)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def __init__(self, serial: str):
        self._serial = serial
        self._sdk = None

    def open(self):
        import acme_sdk        # deferred import — never at module level
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

> **Important:** Never `import acme_sdk` at module level. Deferred imports inside `open()` and `preflight()` ensure the module can be safely imported on systems where the SDK is absent. `preflight()` catches the missing package with a clear message; `open()` only runs after preflight has passed.

**Step 2 — Register in the factory:**

The camera factory uses a `_DRIVERS` registry dict rather than `if/elif` chains:

```python
# hardware/cameras/factory.py — add to _DRIVERS dict:
_DRIVERS = {
    ...
    "acme": ("hardware.cameras.acme_cam", "AcmeCameraDriver"),
}
```

Add an install hint to `_INSTALL_HINTS` if the driver has external SDK dependencies:

```python
_INSTALL_HINTS["acme"] = "pip install acme_sdk\nDownload SDK from acme.example.com"
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

**Updating the Hardware Setup Wizard (`ui/first_run.py`):** If you want the new driver to appear in the Camera page dropdown, add a `(display_label, "acme")` tuple to the `_PageCamera` combo loop in `_PageCamera.__init__`, and add an `_update_hints` branch for the key `"acme"`. If the driver has SDK prerequisites, add a notice label following the `_pylon_notice` / `_flir_notice` pattern.

---

## 21. Adding a New UI Tab

Example: adding a new "Polarization" tab in Manual mode.

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
    icon="mdi6.polarization",  # MDI icon name (fa5s.* auto-upgraded)
    widget_factory=lambda: PolarizationTab(self._hw, self._state),
)
```

**Step 3 — Connect hardware signals (if needed):**

```python
# In PolarizationTab.__init__() or in MainWindow._connect_signals():
hw_service.some_signal.connect(self._polarization_tab.on_some_event)
```

No changes to `MainWindow` are required if the tab is self-contained and uses `app_state` for hardware references.

**Auth considerations:** If your tab should only be visible to certain user types or requires admin access:

```python
# In __init__, check the auth session if provided
def __init__(self, hw_service, app_state, auth_session=None, parent=None):
    ...
    if auth_session and not auth_session.user.is_admin:
        self._some_admin_button.setVisible(False)
        self._some_admin_button.setToolTip("Administrator login required")
```

Tabs should **never block** the user from viewing data — they should hide or disable controls they can't use, not hide the entire tab.

**Step 4 — Implement `_apply_styles()` for theme switching:**

Every tab that sets inline stylesheets at construction time must implement `_apply_styles()` to re-apply them with current PALETTE values:

```python
def _apply_styles(self):
    from ui.theme import PALETTE as P, FONT as F
    self._readout.setStyleSheet(
        f"font-family: 'Menlo'; font-size: {F['readoutLg']}pt; color: {P['accent']};")
    self._sublabel.setStyleSheet(
        f"font-size: {F['caption']}pt; color: {P['textDim']};")
```

This method is called automatically by `MainWindow._swap_visual_theme()` during theme switches. Use `ui/widgets/tab_helpers.py` helpers (`make_readout()`, `make_sub()`) for common readout patterns.

---

## 22. Key Design Decisions

| Decision | Rationale |
|---|---|
| **PyQt5 (not PySide6)** | Mature, stable on Windows; PySide6 migration is straightforward when needed |
| **Factory pattern for all drivers** | Registry dict in `factory.py`; no `if/elif` chains in business logic; adding a driver requires only two lines |
| **Simulated driver for every device** | CI tests with no hardware; demo mode for sales/training |
| **`preflight()` classmethod on every driver** | SDK availability is checked and reported as an actionable message *before* any hardware I/O; deferred imports keep module loading safe on systems without optional SDKs |
| **ApplicationState RLock instead of per-driver locks** | Prevents compound-operation races (e.g., replacing camera + pipeline atomically) |
| **Camera frame back-pressure semaphore** | Prevents Qt event queue overflow at high frame rates |
| **Ed25519 for license keys (not HMAC)** | Asymmetric: private key never in app; public key cannot forge keys |
| **Two repos (source private, releases public)** | Update checker works without GitHub auth token; source is protected |
| **Lazy-loaded NumPy arrays in sessions** | Browsing 100s of sessions without loading all data into RAM |
| **Schema migrations on session load** | Old sessions remain valid after adding new metadata fields |
| **`version.py` as single source of truth** | All version strings, URLs, and repo names derived from one file; CI reads it |
| **Manual RAG over embedding-based RAG** | No embedding model required; keyword matching is fast and sufficient for a bounded domain |
| **Auth opt-in via `auth.require_login`** | Backwards-compatible; research labs get zero disruption; corporate ops enable it |
| **Admin is `is_admin: bool`, not a separate user type** | Any user type can be admin; AI persona and UI surface are unchanged by the admin flag |
| **UserType → uses_operator_shell** | Single boolean property routes Technicians to OperatorShell; no scattered `if role == "technician"` checks |
| **OperatorShell is a separate QMainWindow** | Complete hard separation; Technicians never accidentally reach engineer UI |
| **bcrypt work factor 12 for passwords** | Industry standard; air-gap friendly (no server) |
| **SQLite for user DB** | Zero server dependency; stdlib `sqlite3`; works air-gapped |
| **JSON Lines for audit log** | Human-readable, grep-able, append-only; matches existing `timeline.jsonl` pattern |
| **FLIR driver key stays `"flir"` internally** | User-facing label is "Microsanj IR Camera" via QComboBox userData; `config.yaml` key unchanged for backwards compatibility |
| **Colour-rewrite theme switching** | Inline stylesheets are rewritten in-place (old hex → new hex) instead of cleared-and-rebuilt, preserving font/layout properties that would be lost by clearing |
| **SegmentedControl as shared widget** | One custom-painted pill-style widget replaces 7+ QPushButton-based segment implementations across the app |
| **Atomic session metadata writes** | `.tmp` + `os.replace()` prevents corrupt JSON if the process crashes mid-write |
| **PyQtGraph for interactive charts** | Native QWidget, no web engine, OpenGL-accelerated, real-time capable; degrades gracefully to a `QLabel` placeholder when not installed. Chosen over matplotlib (slow redraws in Qt), Qt Charts (GPL, separate install), and Plotly/Bokeh (require Chromium). |
| **`_PG_OK` flag + conditional base class** | `_PlotBase = pg.PlotWidget if _PG_OK else QWidget` evaluated once at import; all chart classes inherit from it. `pg.PlotWidget` is only referenced when PyQtGraph is available, so `import ui.charts` never crashes on a system without it. |
| **`_CmdSignals.finished` + `_active_cmd_signals` set** | `setAutoDelete(False)` on `_CmdRunnable` + a strong Python reference held in the parent widget's `_active_cmd_signals` set until `finished` fires. Prevents the common PyQt5 pitfall where a `QObject` signal carrier is garbage-collected before its queued cross-thread delivery reaches the main thread. |

---

## 23. Dependency Reference

```
PyQt5>=5.15.9          Qt5 GUI framework
PyQt5-sip>=12.12       PyQt5 C extension
numpy>=1.24            Numerical arrays (all image data)
scipy>=1.10            Signal processing, linear regression
matplotlib>=3.7        Plots (temperature, focus, histograms)
pyqtgraph>=0.13.3      Interactive real-time charts (calibration, analysis, transient, sessions)
Pillow>=10.0           Image processing, thumbnail generation
pyyaml>=6.0            config.yaml parsing
pyserial>=3.5          Serial port enumeration and communication
pyusb>=1.2             USB device enumeration
cryptography>=42.0     Ed25519 license key validation
qtawesome>=1.3.0       FontAwesome 5 / Material Design Icons for PyQt5
requests>=2.31         HTTP (update checker, cloud AI)
bcrypt>=4.0            Password hashing for user accounts (work factor 12)

# Optional — hardware SDKs (Windows-only unless otherwise noted, not in PyPI)
pypylon                Basler camera SDK — self-contained wheel (bundles pylon runtime; no OS SDK install needed)
flirpy                 FLIR camera SDK Python wrapper — used by flir_driver.py (Microsanj IR Camera v1a); bundled in installer
pyMeCom                Meerstetter TEC serial protocol (installed from GitHub: meerstetter/pyMeCom)
nifpga                 NI-FPGA Python interface
pyvisa                 NI-VISA / GPIB / SCPI instrument control
thorlabs_apt_device    Thorlabs APT/Kinesis stage control
pydp832 / dp832        Rigol DP832 programmable power supply

# Dev / build only
pyinstaller>=6.0       Standalone bundle builder
cairosvg               SVG → PNG conversion (for .ico generation in CI)
pytest>=7.4            Test runner
```

---

*This document was last updated for SanjINSIGHT v1.5.0-beta.1 (2026-03-25).
Update it whenever significant architectural changes are made.*
