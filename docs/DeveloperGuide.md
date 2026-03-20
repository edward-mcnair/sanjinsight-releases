# SanjINSIGHT — Developer Guide

**Version**: 1.4.0-beta.1
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
9. [Auth & RBAC System](#9-auth--rbac-system)
10. [Operator Shell](#10-operator-shell)
11. [Configuration & Preferences](#11-configuration--preferences)
12. [Session Management](#12-session-management)
13. [Update System](#13-update-system)
14. [Event Bus & Logging](#14-event-bus--logging)
15. [Thread Safety Model](#15-thread-safety-model)
16. [Data Flow Diagrams](#16-data-flow-diagrams)
17. [Build & Release Pipeline](#17-build--release-pipeline)
18. [Testing](#18-testing)
19. [Adding a New Hardware Driver](#19-adding-a-new-hardware-driver)
20. [Adding a New UI Tab](#20-adding-a-new-ui-tab)
21. [Key Design Decisions](#21-key-design-decisions)
22. [Dependency Reference](#22-dependency-reference)

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
├── auth/                      ← RBAC, user management, session auth (pure Python)
│   ├── __init__.py            ← Exports UserStore, AuditLogger, Authenticator, AuthSession
│   ├── models.py              ← UserType, User, AuthSession dataclasses
│   ├── store.py               ← UserStore (SQLite) + AuditLogger (JSON Lines)
│   ├── authenticator.py       ← Authenticator(QObject) — bcrypt in QThread, lockout, override
│   └── user_prefs.py          ← Per-user preference layer (extends config dot-notation API)
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
│   ├── cameras/               ← CameraDriver implementations (pypylon, ni_imaqdx, flir_driver, simulated)
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
│   ├── charts.py              ← PyQtGraph chart widgets (calibration, analysis, transient, sessions)
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
│   ├── auth/                  ← Auth UI screens
│   │   ├── admin_setup_wizard.py  ← One-time admin account creation wizard
│   │   ├── login_screen.py        ← Full-window login (replaces content before MainWindow)
│   │   ├── supervisor_override_dialog.py ← Temporary engineer access at operator station
│   │   └── user_management_widget.py     ← Admin-only user CRUD, embedded in SettingsTab
│   ├── operator/              ← Operator Shell (Technician users only; never imports MainWindow)
│   │   ├── operator_shell.py      ← OperatorShell(QMainWindow) — top-level operator window
│   │   ├── recipe_selector_panel.py ← Lists only approved/locked scan profiles
│   │   ├── scan_work_area.py      ← Live camera view + Part ID field + START SCAN button
│   │   ├── shift_log_panel.py     ← Today's results log with PASS/FAIL badges
│   │   └── verdict_overlay.py     ← Full-screen PASS/FAIL/REVIEW result after each scan
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
                    main_app.py  (startup routing)
                          │
              ┌───────────┼────────────────────┐
              │           │                    │
              ▼           ▼                    ▼
     No users?       require_login?      user_type?
   AdminSetupWizard   LoginScreen     TECHNICIAN → OperatorShell
                           │          FA/RESEARCHER → MainWindow
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
- **Auth is opt-in.** When `auth.require_login` is `false` (default), the startup flow is identical to pre-v1.3.0 — no login screen, no user management visible.
- **OperatorShell is a complete separate window.** It never imports MainWindow; Technician users cannot reach the full UI even by accident.

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
- Optional hardware SDKs (pypylon, nifpga, pyMeCom, …) cannot be bundled into the installer for every target system. Rather than a bare `ImportError` traceback, the user sees "pypylon not found — try reinstalling SanjINSIGHT" with a direct action.
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

`CameraFrame` contains:
- `data: np.ndarray` — uint16, shape `(H, W)`
- `timestamp: float` — `time.monotonic()` at capture
- `index: int` — frame counter

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

## 9. Auth & RBAC System

The auth system is in the `auth/` package. It is pure Python (no PyQt5 imports) so it can be tested without a display.

### 9.1 User Types (`auth/models.py`)

```python
class UserType(enum.Enum):
    TECHNICIAN       = "technician"       # OperatorShell + lab_tech AI
    FAILURE_ANALYST  = "failure_analyst"  # Full UI + failure_analyst AI
    RESEARCHER       = "researcher"       # Full UI + new_grad AI

    @property
    def default_ai_persona(self) -> str: ...
    @property
    def uses_operator_shell(self) -> bool: ...  # True only for TECHNICIAN
    @property
    def can_edit_recipes(self) -> bool: ...     # False only for TECHNICIAN

@dataclass
class User:
    uid:           str
    username:      str         # COLLATE NOCASE
    display_name:  str
    user_type:     UserType
    is_admin:      bool        # privilege overlay — any type can be admin
    pw_hash:       str         # bcrypt, work factor 12
    created_at:    str
    last_login:    str = ""
    is_active:     bool = True
    created_by:    str = ""

@dataclass
class AuthSession:
    user:          User
    login_time:    float
    last_activity: float
    session_id:    str
    supervisor_override_active: bool = False

    def touch(self) -> None: ...
    def is_expired(self, timeout_s: int) -> bool: ...
```

**Admin is a privilege overlay, not a separate user type.** Any `UserType` can have `is_admin=True`. The `is_admin` flag adds access to user management and global settings — it does not change the AI persona or UI surface.

### 9.2 UserStore (`auth/store.py`)

SQLite database at `~/.microsanj/users.db`. Schema version tracked via `PRAGMA user_version` for future migration support.

```python
store = UserStore()

# One-time check at startup
store.has_users()             # → False on fresh install

# User CRUD
store.create_user(username="jsmith", display_name="Jane Smith",
                  user_type=UserType.FAILURE_ANALYST, is_admin=False,
                  password="secret")
store.get_by_username("jsmith")  # → User | None
store.list_users()               # → List[User]
store.set_admin(uid, True)
store.set_active(uid, False)     # deactivate (doesn't delete)
store.update_password(uid, "new_secret")
store.update_last_login(uid)
```

### 9.3 AuditLogger (`auth/store.py`)

Appends JSON Lines to `~/.microsanj/audit.log`. 5 MB rotation, 3 backups.

```python
audit = AuditLogger()
audit.log(event="login", actor="jsmith", user_type="failure_analyst",
          detail="success", success=True)
```

### 9.4 Authenticator (`auth/authenticator.py`)

`Authenticator(QObject)` is the central facade. It owns the current `AuthSession`.

```python
auth = Authenticator(store, audit)

# Login — bcrypt check runs in QThread; never blocks GUI
session = auth.authenticate("jsmith", "password")  # → AuthSession | None

# Signals
auth.session_started.connect(on_login)    # (AuthSession)
auth.session_ended.connect(on_logout)
auth.locked.connect(on_lock)

# Supervisor override at operator station
auth.supervisor_override("rjones", "pw", minimum_role=...)  # → bool

# Inactivity management (call from 30-second QTimer)
auth.touch()                              # reset inactivity clock
auth.check_lock_timeout(timeout_s=1800)  # True if session expired
```

**Lockout:** 5 consecutive failures → 5-minute lockout, countdown shown in LoginScreen.

**LDAP stub:** `_verify_credentials()` is an overridable method; the default implementation uses bcrypt + SQLite. An LDAP implementation drops in without changing any callers.

### 9.5 UserPrefs (`auth/user_prefs.py`)

Per-user preference file: `~/.microsanj/users/{uid}/prefs.json`.

```python
prefs = UserPrefs.for_session(session)

prefs.get("ui.theme", "auto")         # user file → falls back to config.get_pref()
prefs.set("ui.theme", "dark")         # writes to user file only

# Users cannot modify hardware.* or auth.* keys (admin-only; raises PermissionError)
```

### 9.6 Startup Routing (`main_app.py`)

```python
# ① Create auth objects
_user_store = UserStore()
_audit      = AuditLogger()
_auth       = Authenticator(_user_store, _audit)

# ② First launch: no users → admin setup wizard (one-time)
if not _user_store.has_users():
    if AdminSetupWizard(_user_store, _audit).exec_() != QDialog.Accepted:
        sys.exit(0)

# ③ Login gate (only when require_login is on)
_auth_session = None
if config.get_pref("auth.require_login", False):
    _auth_session = _run_login(_auth, app)
    if _auth_session is None:
        sys.exit(0)

# ④ Route by user type
if _auth_session and _auth_session.user.user_type.uses_operator_shell:
    _launch_operator_shell(_auth, _auth_session, session_mgr)
else:
    window = MainWindow(auth=_auth, auth_session=_auth_session)
    # ... existing flow unchanged ...
```

When `auth.require_login` is `false` (the default), steps ③ and ④ are skipped entirely and the application behaves identically to v1.1.x.

### 9.7 Auth-Related Config Keys

Three new keys in `~/.microsanj/preferences.json` (admin-only; not in `config.yaml`):

```python
config.get_pref("auth.require_login",                False)  # bool
config.get_pref("auth.lock_timeout_s",               1800)   # int (30 min)
config.get_pref("auth.supervisor_override_timeout_s", 900)   # int (15 min)
```

---

## 10. Operator Shell

`OperatorShell(QMainWindow)` in `ui/operator/operator_shell.py` is the complete UI for Technician users. It shares the same `HardwareService` and `ApplicationState` as `MainWindow` but has no code dependencies on it.

### 10.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Logo │ Operator Mode │ Jane Smith [OP] │ 12 scans · 91%    │
├─────────────────┬────────────────────┬────────────────────  ┤
│ RecipeSelectorPanel │  ScanWorkArea  │   ShiftLogPanel       │
│ (320 px fixed)  │  (flexible)        │  (280 px fixed)       │
└─────────────────┴────────────────────┴───────────────────── ┘
```

### 10.2 Panels

**`RecipeSelectorPanel`** — Shows only `recipe.locked == True` scan profiles. Emits `recipe_selected(Recipe)`. Empty state message guides operators to ask an engineer to approve profiles.

**`ScanWorkArea`** — Live camera view (same QImage→QPixmap pipeline as MainWindow) + `Part ID` QLineEdit + START SCAN button (56 px tall, green). `returnPressed` on the line edit auto-starts the scan (barcode scanner support). START SCAN is disabled until a recipe is selected AND a non-empty Part ID is entered.

**`ShiftLogPanel`** — Scrollable card list of today's results. Running totals in the header. `Export CSV` button → `QFileDialog`.

**`VerdictOverlay(QDialog)`** — Full-screen modal after each scan. Background color: green (PASS), red (FAIL), amber (REVIEW). Center card shows verdict text (72 pt), part ID, max hotspot temperature vs. limit, and action buttons (Next Part, Flag for Review, View Details).

### 10.3 Verdict Logic

`VerdictOverlay` reads from `AnalysisResult.verdict` and `Recipe.analysis.fail_peak_k`. No new verdict logic is introduced — the overlay is purely a display wrapper over the existing analysis pipeline.

### 10.4 PDF Auto-generation

On `_on_scan_complete(result)`, `OperatorShell` calls the existing `generate_report()` from `acquisition/report.py`. The report is saved to the session directory automatically. Operators never need to click "Export PDF".

### 10.5 Supervisor Override

`SupervisorOverrideDialog` (340 × 280 px) takes engineer credentials and calls `auth.supervisor_override()`. On success, `session.supervisor_override_active = True`. A 15-minute `QTimer` calls `auth.revert_override()` automatically.

---

## 11. Configuration & Preferences

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

## 12. Session Management

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
| `schema_version` | int | For migrations |

### 12.3 Loading Sessions

Arrays are lazy-loaded — only read from disk when accessed:

```python
session = Session.load("/path/to/session_dir")
drr = session.delta_r_over_r    # Loads delta_r_over_r.npy on first access
session.unload()                 # Frees memory
```

### 12.4 Schema Migrations (`acquisition/schema_migrations.py`)

When a new field is added to `SessionMeta`, a migration function bumps `schema_version` and fills in the default value for old sessions. Migrations run automatically on `Session.load()`.

---

## 13. Update System

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
checker = UpdateChecker(current_version="1.3.0", on_update=my_callback)
checker.check_async()    # Non-blocking background thread
result = checker.check_sync()   # Blocking (used for "Check Now" button)
```

`on_update(UpdateInfo)` is called on the background thread if a newer version is found.
`UpdateInfo` has: `latest_version`, `release_notes`, `download_url`, `release_page_url`.

---

## 14. Event Bus & Logging

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

## 15. Thread Safety Model

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

## 16. Data Flow Diagrams

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

## 17. Build & Release Pipeline

### 17.1 GitHub Actions (`.github/workflows/build-installer.yml`)

**Triggers:**
- `git push origin v1.4.0-beta.1` — builds + creates GitHub Release on `sanjinsight-releases`
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

### 17.2 Release Procedure

```bash
# 1. Update version
# Edit version.py: __version__, PRERELEASE, VERSION_TUPLE, BUILD_DATE
# Beta example:  __version__ = "1.4.0-beta.2",  PRERELEASE = "beta.2"
# GA example:    __version__ = "1.4.0",          PRERELEASE = ""

# 2. Update CHANGELOG.md: add ## [1.4.0-beta.2] — YYYY-MM-DD section

# 3. Commit
git add version.py CHANGELOG.md
git commit -m "chore: bump to v1.4.0-beta.2"

# 4. Tag and push — this triggers CI
git tag v1.4.0-beta.2
git push origin main
git push origin v1.4.0-beta.2

# 5. CI builds installer and publishes release automatically
# 6. Verify at https://github.com/edward-mcnair/sanjinsight-releases/releases
```

### 17.3 Local Windows Build (manual)

```bash
pip install pyinstaller pillow cairosvg
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

## 18. Testing

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

## 19. Adding a New Hardware Driver

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

## 20. Adding a New UI Tab

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

---

## 21. Key Design Decisions

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
| **PyQtGraph for interactive charts** | Native QWidget, no web engine, OpenGL-accelerated, real-time capable; degrades gracefully to a `QLabel` placeholder when not installed. Chosen over matplotlib (slow redraws in Qt), Qt Charts (GPL, separate install), and Plotly/Bokeh (require Chromium). |
| **`_PG_OK` flag + conditional base class** | `_PlotBase = pg.PlotWidget if _PG_OK else QWidget` evaluated once at import; all chart classes inherit from it. `pg.PlotWidget` is only referenced when PyQtGraph is available, so `import ui.charts` never crashes on a system without it. |
| **`_CmdSignals.finished` + `_active_cmd_signals` set** | `setAutoDelete(False)` on `_CmdRunnable` + a strong Python reference held in the parent widget's `_active_cmd_signals` set until `finished` fires. Prevents the common PyQt5 pitfall where a `QObject` signal carrier is garbage-collected before its queued cross-thread delivery reaches the main thread. |

---

## 22. Dependency Reference

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
pyMeCom                Meerstetter TEC serial protocol
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

*This document was last updated for SanjINSIGHT v1.4.0-beta.1 (2026-03-19).
Update it whenever significant architectural changes are made.*
