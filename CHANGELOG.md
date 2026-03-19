# Changelog — SanjINSIGHT

All notable changes to SanjINSIGHT are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.4.0-beta.1] — 2026-03-19

### Added

- **AMCAD BILT pulsed I-V system driver** (`hardware/bias/amcad_bilt.py`) — TCP/SCPI driver communicating with `pivserver64.exe` on the instrument PC. Implements the full `BiasDriver` interface; `configure_pulse()` method sets per-channel bias, pulse voltage, width, and delay for Gate (Ch 1) and Drain (Ch 2).
- **BNC Model 745 digital delay generator driver** (`hardware/fpga/bnc745.py`) — PyVISA driver implementing `FpgaDriver` with continuous and single-shot trigger modes. Replaces the NI-9637 as the precision timing source in PT-100B test setups.
- **AMCAD BILT Pulse Configuration panel** in Stimulus → Bias Source tab — collapsible panel with Gate and Drain channel spinboxes (bias V, pulse V, width µs, delay µs) and an **Apply Pulse Config** button; appears only when an AMCAD BILT is connected.
- **Gate channel readout row** (Vg / Ig) in the Bias Source status header; shown only when AMCAD BILT is connected.
- **Trigger Mode panel** in Stimulus → Modulation tab — Continuous/Single-shot radio buttons, Pulse Duration spinbox (µs), and **▶ Arm Trigger** button for BNC 745; hidden for NI-9637.
- **TRIGGER readout** in the FPGA status bar (CONT / SINGLE / SINGLE ✦); hidden for NI-9637.
- `BiasTab.set_bias_driver(driver)` — called by `main_app` on hotplug events; reveals BILT-specific UI for `AmcadBiltDriver` instances.
- `FpgaTab.set_fpga_driver(driver)` — called by `main_app` on hotplug events; reveals trigger-mode UI for drivers that return `supports_trigger_mode() = True`.
- `hardware/device_manager.py` KEY_MAP entries: `amcad_bilt` → `"amcad_bilt"`, `bnc_745` → `"bnc745"`.
- Device Manager dialog: TCP port display for CONN_ETHERNET devices with `desc.tcp_port`; VISA address text field for BNC 745 (replaces NI-DAQmx note).
- `MONO_FONT` constant in `ui/theme.py` — cross-platform monospace CSS family string `'Menlo','Consolas','Courier New',monospace`.

### Changed

- **Versioning scheme switched to beta** — releases now use `MAJOR.MINOR.PATCH-beta.N` pre-release identifiers. `version.py` gains `PRERELEASE`, `is_prerelease()`, and an updated `is_newer()` that treats a GA release as newer than an equivalent beta.
- AMCAD BILT TCP connection error message now explicitly lists Windows Firewall (port 5035) as a diagnostic step.
- BNC 745 VISA address placeholder updated to include Windows serial format `ASRL1::INSTR` alongside the Linux `/dev/ttyUSB0` example.

### Fixed

- **Monospace font fallback on Windows** (146 replacements across 29 files) — all inline stylesheets now use `'Menlo','Consolas','Courier New',monospace` so Windows users get Consolas rather than bare Courier New.

---

## [1.4.0] — 2026-03-19

### Added

- **Interactive chart suite** (`ui/charts.py` — new module) — five PyQtGraph-based chart widgets with full PALETTE theming and graceful fallback to placeholder labels when PyQtGraph is not installed:
  - **`CalibrationQualityChart`** — three-panel chart in a new "Quality ✦" tab on the Calibration screen: R² histogram (green / amber / red bars by value), C_T coefficient histogram (×10⁻⁴ scale), and calibration curve scatter + linear fit. Wired to `CalibrationResult` via `update_data()`.
  - **`AnalysisHistogramChart`** — dT pixel-distribution histogram with a vertical threshold line and a pass/fail verdict annotation; embedded in the Analysis tab between the summary stats and the hotspot table.
  - **`TransientTraceChart`** — replaces the old QPainter-based `TransientCurve`; renders time-resolved waveforms with a draggable cursor line and zero-baseline rule. API-compatible (`update_data(values, times_s, cursor_idx)`) — no call-site changes required.
  - **`SessionTrendChart`** — linked-axis scatter chart showing SNR (dB) and TEC temperature per saved session over time; embedded in the Sessions panel right column. Updates on every `_refresh()`.
  - **`dTSparklineWidget`** — rolling 2-minute dT stability strip using a `collections.deque` buffer; time axis is "seconds ago" so the window always shows relative recency. Auto-appears in the main window the first time TEC data arrives.
- **`CalibrationResult` curve data fields** — `temps_c: Optional[np.ndarray]` and `mean_signals: Optional[np.ndarray]` added to the `CalibrationResult` dataclass. Both are `Optional` so existing `.cal` files load without migration. `Calibration.fit()` now computes per-step spatial-mean ΔR/R and populates these fields for use by `CalibrationQualityChart`.
- **`pyqtgraph>=0.13.3`** added to `requirements.txt` and both PyInstaller specs (`installer/sanjinsight.spec`, `installer/sanjinsight_mac.spec`).

### Changed

- **`TransientCurve` replaced by `TransientTraceChart`** — `acquisition/transient_tab.py` now imports `TransientTraceChart` from `ui/charts`. The public API is identical so no external callers are affected.

### Fixed

- **Monochromator command lifetime hazard** (`ui/tabs/wavelength_tab.py`) — `_CmdRunnable` previously used `setAutoDelete(True)` with a `_CmdSignals` QObject stored as a member. If the Python wrapper was garbage-collected before a queued cross-thread signal reached the main thread, the slot was silently dropped. Fixed by: (1) switching to `setAutoDelete(False)` with Python ref-counting managing lifetime; (2) adding a `finished = pyqtSignal()` to `_CmdSignals` that fires unconditionally at the end of `run()`; (3) storing a strong reference to the `signals` object in `WavelengthTab._active_cmd_signals` until `finished` fires.
- **`_restore()` closure crash on widget close** (`ui/tabs/wavelength_tab.py`) — the 3-second timer that restores normal styles after a command error captured `self` strongly. If the `WavelengthTab` was destroyed before the timer fired, `self._apply_styles()` on the deleted C++ object crashed. Fixed by passing `self` as the context argument to `QTimer.singleShot(3000, self, _restore)` — PyQt5 auto-cancels the callback if the context object is deleted.
- **Compare A vs B `AttributeError`** (`acquisition/data_tab.py`) — `_run_compare()` accessed `ma.label` and `mb.label` without checking that both `get_meta()` calls returned non-`None`. If a session was deleted between setting the compare slot and clicking Compare, the access crashed. Added `if ma is not None and mb is not None:` guard.
- **DPI scaling in measurement strip** (`ui/widgets/measurement_strip.py`) — all QPainter layout constants (`_STRIP_HEIGHT`, `_MARGIN`, `_SUB_GAP`, `_CELL_GAP`, `_DIV_H_INSET`) now pass through a new `_s(px)` helper that multiplies by `_DPI_SCALE` from `ui.theme`, ensuring correct proportions on HiDPI / Retina displays.
- **Tag registry corruption recovery** (`acquisition/metadata.py`) — `get_registry()` previously propagated a `json.JSONDecodeError` from a corrupt or truncated `tag_registry.json`. Now wraps the load in `try/except`; on failure the corrupt file is renamed to `tag_registry.json.bak` and a fresh empty registry is written, preventing a startup crash.
- **Session schema forward-version warning** (`acquisition/session.py`) — loading a session written by a newer build of SanjINSIGHT now emits a `WARNING`-level log message naming the file path and the schema version mismatch instead of silently ignoring unknown fields.

---

## [1.3.0] — 2026-03-14

### Added

- **Acquisition safety net** (`acquisition/pipeline.py`) — `_run()` now wraps the hot-phase in `try/except/finally`; the new `_stimulus_safe_off()` method unconditionally disables FPGA modulation and bias on every exit path (normal completion, early abort, and exception). Eliminates the pre-existing bug where an abort during hot-frame collection left the DUT powered.
- **Structured crash reporter** (`ui/crash_reporter.py`) — `install_crash_reporter(app_state)` hooks `sys.excepthook` to write a timestamped crash report (`~/.microsanj/crashes/crash_<ts>.txt`) containing version info, OS/Python environment, connected hardware driver names, the last 50 log lines (via `_BufferHandler`), and the full traceback. A `QMessageBox` is shown if the UI is alive.
- **UserStore integrity check and hot backup** (`auth/store.py`) — `_ensure_db()` runs `PRAGMA integrity_check` at every startup and logs `CRITICAL` if the database is corrupt. `backup()` uses the SQLite native `connection.backup()` API for a consistent hot copy to `~/.microsanj/users.db.bak`. `close()` automatically triggers a backup before releasing the connection.
- **Acquisition pipeline integration tests** (`tests/test_pipelines.py`) — `TestAcquisitionPipelineIntegration` adds 9 test cases: normal ΔR/R production, stimulus OFF on normal/abort/exception exit paths, finite SNR, both averages present, correct `n_frames`, `dark_pixel_fraction` in [0,1], and `finally`-block coverage with a faulting FPGA driver.
- **Readiness banner full Fix-it coverage** (`ui/widgets/readiness_widget.py`) — corrected two wrong nav-target mappings (`fpga_not_running` and `fpga_not_locked` now map to `"Stimulus"`, not the non-existent `"FPGA"` label), and added the missing `stage_not_homed` → `"Stage"` entry. Every issue code produced by `MetricsService` now has a working "Fix it →" button.
- **Contextual per-widget help tooltips** — multi-line tooltips added to the most commonly confused controls: all camera/acquisition/analysis spinboxes in `RecipeTab`; status label and Clear button in `HealthTab`; readiness title label in `ReadinessWidget`. Tooltips explain what the parameter does and what values to use.
- **Session home screen** (`ui/tabs/home_tab.py`) — new `HomeTab` landing dashboard shows the 5 most recent acquisition sessions as cards (thumbnail, label, timestamp, PASS/FAIL chip, Open button). Registered as the first item in the ACQUIRE nav section. Emits `open_session_requested(path)` and `new_acquisition_requested()`. Automatically refreshes after each session save.
- **Scan profile diff viewer** (`acquisition/recipe_tab.py`) — "Compare…" button opens `_RecipeDiffDialog`: a 700 × 520 px dialog with two combo dropdowns (select any two profiles) and a scrollable diff view. Equal parameters are shown in dim grey; changed parameters highlight both values (left = amber, right = teal). Uses `_flat_params()` to flatten all 15 comparable Recipe fields.
- **Calibration library** (`acquisition/calibration_library.py`) — slug-keyed named store for `CalibrationResult` objects. Saves `.npz` files + `index.json` in `~/.microsanj/calibrations/`. `best_match(device_id, temperature_c)` scores candidates by device match and temperature proximity.
- **Batch session reprocessor** (`acquisition/batch_reprocessor.py`) — `BatchReprocessor.reprocess(uids, calibration)` re-applies a `CalibrationResult` to a list of session UIDs without re-capturing data; updates `delta_t.npy` and `session.json` in-place. `BatchReprocessWorker(QThread)` provides a Qt-friendly async wrapper.
- **Remote control REST API** (`hardware/api_server.py`) — `ApiServer` binds to `127.0.0.1` only; no third-party dependencies (`http.server` stdlib only). Endpoints: `GET /api/v1/status`, `GET /api/v1/acquire/status`, `GET/POST /api/v1/acquire`, `POST /api/v1/stop`, `GET /api/v1/session/{uid}`, `GET /api/v1/sessions`. Optional bearer-token auth via `config.get_pref("api.token", "")`.
- **Hardware health dashboard** (`ui/tabs/health_tab.py`) — `HealthTab` shows 60-minute rolling trends for TEC channel temperatures, FPGA duty cycle, and camera frame rate using a 3-subplot matplotlib figure (QLabel fallback if matplotlib unavailable). `_RollingBuffer` trims entries older than 3600 s. Updates via 5-second QTimer.

### Changed

- **DeveloperGuide.md updated for v1.2.x** — Section 4.3 documents the pre-flight validation system with full driver coverage table; Sections 4.5, 19, 21, and 22 updated accordingly. Footer updated to v1.2.9.
- **UserManual.md updated for v1.2.x** — FLIR Spinnaker SDK references replaced with `flirpy` throughout; troubleshooting entries added for NI IMAQdx cameras and the pre-flight error dialog. Header updated to v1.2.9.

### Dependencies

- `bcrypt>=4.0` added to `requirements.txt` (only new runtime dependency).

---

## [1.2.9] — 2026-03-14

### Added

- **Full hardware-stack pre-flight coverage** — the `preflight()` classmethod introduced in v1.2.8 now covers every driver in the system, not just cameras. All six non-camera subsystem base classes (`TecDriver`, `BiasDriver`, `FpgaDriver`, `StageDriver`, `LddDriver`, `ObjectiveTurretDriver`) expose a default `preflight()` that always passes; each concrete driver overrides it with the correct dependency check.
- **`NiImaqdxDriver.preflight()`** — checks Windows platform, then scans the two canonical DLL paths for `niimaqdx.dll` (NI Vision Acquisition Software). A missing DLL is a hard failure. Missing `ImaqdxAttr.exe` (the C# attribute helper) is a non-blocking warning; exposure/gain control will be unavailable but camera acquisition still works.
- **`DirectShowDriver.preflight()`** — checks Windows platform, then verifies `opencv-python` (`cv2`) is importable. Fails with a clear reinstall instruction if the package is missing.
- **`MeerstetterDriver.preflight()`** (TEC) — checks `mecom` (pyMeCom) importable.
- **`MeerstetterLdd1121Driver.preflight()`** (LDD) — checks `mecom` (pyMeCom) importable.
- **`KeithleyDriver.preflight()`** (bias) — checks `pyvisa` importable.
- **`VisaGenericDriver.preflight()`** (bias) — checks `pyvisa` importable.
- **`RigolDP832Driver.preflight()`** (bias) — tries three import paths (`pydp832`, `pydp832.dp832lan`, `dp832`) to account for the evolving package structure; fails with install instructions if none is found.
- **`Ni9637Driver.preflight()`** (FPGA) — checks `nifpga` importable.
- **`ThorlabsDriver.preflight()`** (stage) — checks `thorlabs_apt_device` importable.
- **`MpiProberDriver.preflight()`** (stage) — checks `serial` (pyserial) importable.
- **`OlympusLinxTurret.preflight()`** (turret) — checks `serial` (pyserial) importable.
- **Expanded `tests/test_hardware.py`** — test suite grows from 29 to 114 tests:
  - `TestSubsystemDriverPreflight` — parametrized across all 20 non-camera driver modules; 4 checks per module (method present, return type correct, issues are strings, simulated driver always passes) = 80 test cases.
  - `TestSubsystemFactories` — smoke tests all 6 subsystem factories for simulated-driver creation and unknown-driver rejection (10 test cases).

### Fixed

- **`DirectShowDriver` module-level `import cv2`** — the module previously imported `cv2` at the top level, causing an `ImportError` before `preflight()` could run on systems without `opencv-python`. All `cv2` imports moved inside the methods that use them (matching the deferred-import pattern used by `PylonDriver` and `FlirDriver`).
- **`cv2.VideoWriter.fourcc` → `cv2.VideoWriter_fourcc`** — corrected OpenCV API call in `DirectShowDriver`; the class-method form `cv2.VideoWriter.fourcc` does not exist in modern OpenCV builds.

---

## [1.2.8] — 2026-03-14

### Added

- **Driver pre-flight validation system** — `CameraDriver` base class now declares a `preflight()` classmethod that each driver overrides to check its own dependencies before `DeviceManager` attempts to open hardware. Returns `(ok: bool, issues: list[str])`. Actionable error messages ("flirpy not found — try reinstalling SanjINSIGHT") are shown to the user instead of raw Python tracebacks.
- **`PylonDriver.preflight()`** — checks `pypylon.pylon` is importable; fails with a clear reinstall instruction if the wheel is missing from the bundle.
- **`FlirDriver.preflight()`** — checks `flirpy` is importable; fails with a clear reinstall instruction if the wheel is missing from the bundle.
- **Pre-flight called in `DeviceManager._connect_worker()`** — runs before driver instantiation; any failed pre-flight is surfaced as a `RuntimeError` with a formatted bullet list of issues. Warnings (non-blocking issues) are logged at `WARNING` level.
- **`tests/test_hardware.py`** — new CI test suite with four classes:
  - `TestDeviceRegistry` — validates registry consistency: no UID mismatches, all `DTYPE_CAMERA` entries use `CONN_CAMERA`/`CONN_ETHERNET`, required fields non-empty, all `driver_module` paths importable (or skipped for optional deps), `camera_type` values in `{"tr", "ir"}`.
  - `TestCameraDriverInterface` — parametrized across all driver modules; verifies required method presence (`open`, `start`, `stop`, `close`, `grab`, `set_exposure`, `set_gain`, `connect`, `disconnect`, `preflight`), `preflight()` return type `(bool, list)`, all issues are strings, and `SimulatedDriver.preflight()` always passes with an empty issues list.
  - `TestCameraFactory` — smoke tests `create_camera({"driver": "simulated"})` always succeeds, unknown driver key raises `ValueError`/`RuntimeError`, `list_drivers()` contains `"simulated"`, `"pypylon"`, `"flir"`.
  - `TestSimulatedDriverEndToEnd` — full lifecycle test: `preflight()` passes, `connect()` / `start()` / `grab()` / `stop()` / `disconnect()` succeeds, frame is `uint16` 2-D array, exposure and gain ranges valid.
- **Post-build camera SDK bundle smoke test in CI** — new step 9b in `build-installer.yml` walks the PyInstaller output directory after each build and reports which camera SDK packages (`pypylon`, `flirpy`) are present. Emits `[OK]` or `[WARN]` per package so a silently missing SDK is caught before the installer ships.

### Changed

- `build-installer.yml` step 9b inserted between PyInstaller output verification and Inno Setup; warnings are non-fatal (optional deps may be absent on some runners) but hard-fail if the bundle directory itself is missing.

---

## [1.2.7] — 2026-03-13

### Changed

- **Microsanj IR Camera driver rewritten for FLIR Boson** — previous driver used Spinnaker/PySpin which targets FLIR machine-vision cameras, not the Boson microbolometer. Driver now uses `flirpy` (bundled in installer, no manual install needed). Connects via Boson USB CDC control channel + UVC video stream. USB VID updated to `0x09CB`.

### Fixed

- Spinnaker SDK install instructions removed — users no longer need to download PySpin manually.

---

## [1.2.6] — 2026-03-13

### Fixed

- **IR and TR cameras fail to connect with "No port or address configured"** — SDK-enumerated cameras (pypylon, PySpin) were registered with `CONN_USB` instead of `CONN_CAMERA`, causing the device manager's address guard to incorrectly reject them. All four Basler models and the Microsanj IR Camera now use `CONN_CAMERA` so they bypass the port check and enumerate automatically via their SDK.

---

## [1.2.5b] — 2026-03-14

### Fixed

- **Microsanj IR Camera not found on installed builds** — PySpin (FLIR Spinnaker SDK Python bindings) cannot be distributed via PyPI and therefore cannot be bundled in the installer. Added runtime path discovery in `FlirDriver`: on Windows the driver now searches the Spinnaker SDK's standard installation directories (`C:\Program Files\Teledyne\Spinnaker\python`, `C:\Program Files\FLIR Systems\Spinnaker\python`, and version-specific sub-folders) and adds the first matching path to `sys.path` automatically. Users only need to install the Spinnaker SDK with the "Install Python bindings" option checked — no manual `pip install` step required.

---

## [1.2.4] — 2026-03-13

### Changed

- **Bundled Python downgraded 3.11 → 3.10** — FLIR PySpin (required for the Microsanj IR camera) only distributes Windows wheels up to `cp310`. Downgrading ensures users can install PySpin manually after installing the Spinnaker SDK. Do not upgrade the bundled Python past 3.10 without first confirming a newer PySpin wheel is available on the FLIR download page.

---

## [1.2.3] — 2026-03-13

### Fixed

- **Camera connect crash** — `DeviceManager` calls `driver.connect()` on all devices but `CameraBase` only defined `open()`. Added concrete `connect()` → `open()` and `disconnect()` → `close()` aliases to `CameraBase` so all camera drivers satisfy the interface without individual changes.

---

## [1.2.2] — 2026-03-13

### Fixed

- **Basler camera not detected** — `pypylon` was missing from the CI build step so the installer never bundled the Basler Python bindings. Added a dedicated CI step that installs `pypylon` (which ships with the pylon runtime in its wheel — no system SDK required on the runner) before PyInstaller runs. Basler TR cameras now enumerate correctly on first launch.

---

## [1.2.1] — 2026-03-13

### Fixed

- **Hardware Setup Wizard crash** — Opening the wizard (Ctrl+Shift+H) raised `TypeError: widget(self): too many arguments` in `_PageAI.__init__` due to an invalid `QLayout.widget(0)` call. The wizard now opens correctly.

### Added
- (next feature here)

### Fixed
- (next bug fix here)

### Changed
- (next change here)

---

## [1.2.0] — 2026-03-13

### Added

#### Role-Based Access Control (RBAC)
- **Auth foundation** — `auth/` package: `UserStore` (SQLite, `~/.microsanj/users.db`),
  `AuditLogger` (JSON Lines, `~/.microsanj/audit.log`, 5 MB rotation), `Authenticator`
  (QObject facade, bcrypt work-factor 12, 5-failure lockout), and `UserPrefs`
  (per-user `prefs.json` layered over global config).
- **Three-user taxonomy** — `UserType` enum maps 1:1 to existing AI personas:
  Technician (→ OperatorShell + `lab_tech` AI), Failure Analyst (→ full UI +
  `failure_analyst` AI), Researcher (→ full UI + `new_grad` AI). Admin is a
  boolean privilege overlay on any user type, not a fourth type.
- **Admin Setup Wizard** (`ui/auth/admin_setup_wizard.py`) — two-page first-launch
  wizard that creates the first admin account. Welcome page explains the role system
  with privilege cards (Can ✓ / Cannot ✗ columns) for each user type. Cannot be
  dismissed without completing setup.
- **Login Screen** (`ui/auth/login_screen.py`) — full-window login card (logo,
  username, password, bcrypt in QThread, 5-failure lockout countdown). Activated
  when admin enables `auth.require_login` in Settings.
- **Supervisor Override Dialog** (`ui/auth/supervisor_override_dialog.py`) — compact
  340 × 280 px overlay for temporary engineer access at an operator station; logs
  `supervisor_override` event; auto-reverts after 15 minutes.
- **User Management widget** (`ui/auth/user_management_widget.py`) — embedded in
  Settings tab (admin-only). Table of users with Add / Edit / Deactivate / Reset
  Password actions. Add User dialog shows three profile cards + admin checkbox
  — no role dropdowns. AI persona and UI surface derived automatically.

#### Operator Shell
- **OperatorShell** (`ui/operator/operator_shell.py`) — dedicated `QMainWindow` for
  Technician users; never imports MainWindow code. Top bar shows shift summary and
  Lock button. QSplitter body: RecipeSelectorPanel | ScanWorkArea | ShiftLogPanel.
- **RecipeSelectorPanel** (`ui/operator/recipe_selector_panel.py`) — shows only
  `locked=True` scan profiles. Search/filter bar. Empty state guides user to ask an
  engineer to approve a profile.
- **ScanWorkArea** (`ui/operator/scan_work_area.py`) — Part ID / serial number field
  with barcode-scanner support (Enter auto-starts scan), live camera view, START SCAN
  button (56 px, green). Disabled until a profile is selected and a part ID is entered.
- **ShiftLogPanel** (`ui/operator/shift_log_panel.py`) — scrollable today's result
  cards (PASS/FAIL badge, part ID, time, profile label), running totals, Export CSV.
- **VerdictOverlay** (`ui/operator/verdict_overlay.py`) — full-screen modal after
  each scan: PASS / FAIL / REVIEW at 72 pt with key metrics, Flag for Review,
  Next Part, and View Details actions. Background colour reflects verdict.

#### Hybrid TR / IR Camera System
- **System-level camera selection** — `hardware/cameras/` now manages two concurrent
  camera slots (TR and IR). Camera identity locked at hardware selection; stamped on
  every session and exported to TIFF XMP metadata.
- **Global CameraContextBar** — replaces per-tab camera selectors. Shows active
  camera type (TR / IR), model, and status across the full UI.
- **Demo mode cameras** — demo mode always presents both a Basler TR and a
  Microsanj IR camera so the full camera-switching workflow is testable without
  hardware.
- **Microsanj IR Camera v1a** — FLIR-based uncooled microbolometer fully integrated:
  driver (`hardware/cameras/flir_driver.py`), device registry entry, device scanner
  detection, and first-run wizard support.

#### AutoScan improvements
- **Camera & Optics selector** — replaces the TR/IR mode toggle buttons with a
  unified camera and objective selector.
- **Objective magnification persistence** — last-used objective magnification is saved
  per-user and restored on next launch (useful for manual nosepiece systems).
- **Turret auto-sync** — objective buttons auto-update when a motorised turret
  reports a position change.

#### Settings / UX
- **Admin Log-in button** — appears in the status header when an admin account exists
  but no session is active. Clicking opens the Login Screen.
- **Admin Log-out button** — replaces the Log-in button while a session is active;
  clears the session and returns the header to its unauthenticated state.
- **Admin-gated settings** — Lab and Software Update controls are disabled (not
  hidden) with a tooltip "Administrator login required" when no admin session is
  active; all controls re-enable on login.
- **Scan Profile** — "Recipe" renamed to "Scan Profile" throughout the UI
  (menu, tabs, tooltip, wizard, operator shell). Config key unchanged.

### Changed

- **AI persona display names** — renamed from the previous internal labels to
  Technician, Failure Analyst, and Researcher to match the RBAC user taxonomy.
- **Admin Setup Wizard welcome page** — now explains what the admin account controls
  and what privileges each user type will have, with role cards showing Can ✓ and
  Cannot ✗ lists side-by-side.

### Fixed

#### Windows 11 / Cross-Platform
- **Console font on Windows** — `ui/scripting_console.py` hard-coded `Menlo` (macOS
  only); replaced with a platform-aware `_MONO_CSS_FAMILY` constant (`Consolas` on
  Windows, `Menlo` on macOS) so box-drawing glyphs in the banner render correctly.
- **Microsanj IR Camera branding** — first-run wizard and all user-facing strings now
  say "Microsanj IR Camera" instead of "FLIR"; internal config key (`driver: flir`)
  and factory lookup are unchanged.
- **First-run wizard — SDK prerequisites callout** — welcome page now shows a
  highlighted callout listing Basler pylon 8 (Basler TR camera) and FLIR Spinnaker
  SDK (Microsanj IR camera) with direct download links before the user reaches the
  Camera configuration page.
- **First-run wizard — Microsanj IR Camera driver** — camera page now includes
  "Microsanj IR Camera" in the driver dropdown; selecting it immediately checks
  whether the Spinnaker SDK (`PySpin`) is importable and shows an install notice with
  download link and `pip install spinnaker_python` command if it is not. Test Camera
  button enumerates PySpin cameras and reports the count.
- **First-run wizard — auto-detection** — background device scan now auto-selects
  "Microsanj IR Camera" in the driver combo when a Spinnaker-enumerable device is
  detected, the same as it does for Basler cameras.

---

## [1.1.2] — 2026-03-07

### Fixed

- "No Devices Found" dialog: `<i>` HTML tags now render correctly instead of
  appearing as literal text on Windows. Button names shown in quotes instead.
- Update checker: `on_update` callback now fires correctly from `check_sync()`
  so the "Check Now" button in Settings properly shows the update dialog.
- Update checker now points to the public releases repo
  (`edward-mcnair/sanjinsight-releases`) instead of the private source repo,
  so the GitHub API is reachable without authentication.
- Update checks are skipped in demo mode to avoid network errors on offline
  demo machines.

---

## [1.1.1] — 2026-03-06

### Added

- **Cloud AI providers (Claude & ChatGPT)** — optional third-party AI backends
  alongside the existing local LLM. Connect to Anthropic Claude (Opus 4.6,
  Sonnet 4.6, Haiku 4.5) or OpenAI ChatGPT (GPT-4o, GPT-4o Mini) using your
  own API key. Cloud models receive the full system prompt and Quickstart Guide
  in every request. Implemented via stdlib `http.client` — no new dependencies.
  Privacy warning displayed prominently in Settings.
- **Image-based demo mode** — simulated camera now loads real IC chip images
  (`assets/demo_background.png`, `assets/demo_signal.png`) instead of using
  only a parametric mathematical model; falls back to the parametric model if
  the assets are absent.

### Fixed

- Startup demo offer dialog now always appears correctly on first launch.
- Device Manager closes automatically when demo mode is confirmed.
- Device Manager always triggers a fresh scan when opened.
- Deferred startup scan visibility guard prevents race on slow systems.
- Dark tooltip styling corrected on Windows.

---

## [1.1.0] — 2026-03-02

### Added

- **AI: Quickstart Guide always in context** — the complete Quickstart Guide
  (~2,500 tokens) is embedded in every AI system prompt at model load time,
  so every response is grounded in current workflows and navigation without
  any extra setup.
- **AI: User Manual RAG** — a new keyword-based retrieval layer
  (`ai/manual_rag.py`) parses the User Manual into sections and injects the
  most relevant ones into every AI action (Ask, Explain this tab, Diagnose,
  Session Report). Uses Jaccard similarity; no external dependencies.
- **AI: context-aware Explain / Diagnose** — both quick-action buttons now
  retrieve manual sections keyed on the active panel name, so advice about
  the Camera tab draws from the Camera section of the manual, etc.
- **AI: Session Report RAG** — post-acquisition quality reports now include
  relevant manual sections on acquisition quality, SNR, and dark pixels.
- **Diagnostic rule T1 — Duty cycle thermal risk** — warns when FPGA duty
  cycle ≥ 50 % (amber) and fails at ≥ 80 % (red); prevents DUT overheating.
- **Diagnostic rule C3 — Pixel headroom** — warns when the brightest camera
  pixel approaches 12-bit saturation (≥ 3900 ADU), fails when clipped
  (= 4095); prompts the user to reduce exposure or illumination.
- **Diagnostic rule R5 — TEC temperature range** — fails when a TEC setpoint
  falls outside the hardware-safe 10–150 °C operating range.
- **Camera tab: saturation guard** — new SATURATION readout alongside
  MIN / MAX / MEAN / FRAME showing "OK", a clipping percentage (amber), or
  "CLIPPED ✗" (red) in real time during live streaming.
- **Bias Source tab: output port selector** — combo box chooses between
  VO INT (±10 V pulsed), AUX INT (±10 V DC), and VO EXT (≤ +60 V
  passthrough); voltage spinbox limits update automatically on port change;
  VO EXT selection shows a safety warning.
- **Bias Source tab: 20 mA range mode checkbox** — limits current to ≤ 20 mA
  by default (safe mode); uncheck for IR camera FA / Movie mode.
- **FPGA tab: duty cycle warning label** — inline amber/red label mirrors the
  T1 diagnostic rule directly in the hardware panel.
- **Calibration: TR Std and IR Std presets** — one-click standard temperature
  sequences: TR Std (20–120 °C, 6 points, ~12 min) and IR Std
  (85–115 °C, 7 points).
- **Calibration: live time estimate** — shows estimated run time below the
  preset buttons; updates live as steps or averaging settings change.
- **Calibration: save-before-abort dialog** — aborting with valid unsaved
  results now prompts for confirmation rather than silently discarding data.
- **Calibration: extended temperature range** — spinbox range extended to
  −20–150 °C to cover the full AF-200 stage operating range.
- **Help: C_T Coefficient Reference** — new topic with material/wavelength
  table (Si, GaAs, GaN, Au, Al, …) and LED selection guidance including the
  aluminum 780 nm caveat.
- **Help: System Power-Up Sequence** — new topic with required hardware
  startup order and safety notes (cooling pump dry-run warning, etc.).
- **Domain knowledge in AI context** — `ai/instrument_knowledge.py` provides
  a single source of truth for hardware limits, CTR table, and calibration
  constants; a compact ~80-token summary is injected into every system prompt.
- **Active profile in AI context** — when a measurement profile is loaded,
  the material, wavelength, and C_T value appear in the live instrument
  state JSON so the AI can give material-specific advice.
- **Settings: AI knowledge scope indicator** — shows a live count of indexed
  User Manual sections ("✓ User Manual — N sections indexed") and confirms
  the Quickstart Guide is always active.

### Changed

- **Out-of-scope AI response** — updated canned response now says
  "selected sections of the documentation" instead of "only the Quickstart
  Guide", accurately reflecting that manual RAG sections may also be present.
- **`build_system_prompt(base)`** — now the single function that assembles
  every system prompt; static `SYSTEM_PROMPT_COMPACT` dead-code constant
  removed; `SYSTEM_PROMPT` is now computed rather than hardcoded.
- **`USER_MANUAL_URL`** — imported from `version.DOCS_URL`; no more
  hardcoded URL strings in `prompt_templates.py` or `settings_tab.py`.
- **Documentation** — both the Quickstart Guide and User Manual were
  comprehensively updated to cover all v1.1.0 hardware panels (Camera
  saturation, FPGA duty cycle, Bias Source ports), the AI assistant (grade
  system A–D, RAG, model setup), correct keyboard shortcuts (Ctrl+1–5),
  stage homing, diagnostic rules reference, and calibration presets.

### Fixed

- Removed dead `_update_manual_checkbox_state()` and
  `_on_manual_chk_changed()` methods from Settings tab (leftover from a
  removed full-manual embedding feature that caused a performance regression).
- Stale preference keys `ai.include_quickstart` and `ai.include_manual` are
  now silently removed from `preferences.json` on first startup after upgrade.
- Added `pytest.ini` with `--import-mode=importlib` and `norecursedirs = .claude`
  to prevent stale git worktrees from interfering with test collection.

### Tests

- Test suite expanded from 67 → 94 tests.
- New `tests/test_ai.py`: 27 tests covering `build_system_prompt()`,
  `manual_rag` section parsing and retrieval, and RAG injection for all four
  AI query templates (ask, explain_tab, diagnose, session_report).

---

## [1.0.0] — 2026-02-28

### First public release

#### Added
- **Multi-modality imaging framework** — thermoreflectance, IR lock-in, and hybrid measurement modes selectable from the wizard; no hardcoded thermoreflectance assumptions.
- **Standard and Advanced UI modes** — Standard mode uses a guided 4-step wizard (Profile → Acquire → Review → Export); Advanced mode exposes all controls in a full sidebar.
- **Bootstrap-style collapsible sidebar** — 5 logical sections (Measure, Analysis, Hardware, Setup, Tools) replace the previous 19-tab horizontal bar.
- **Profile system** — built-in material profiles (thermoreflectance coefficients C_T); downloadable profile packs from Microsanj servers; user-defined profiles.
- **Measurement recipe system** — save and re-run complete measurement configurations (camera, FPGA, ROI, acquisition settings) in one click.
- **Session manager** — every acquisition is saved to a timestamped session folder; browse, compare, and export from the Data tab.
- **Session comparison view** — overlay two sessions side-by-side for A/B analysis.
- **3D surface plot** — ΔR/R maps rendered as interactive 3D surfaces via matplotlib.
- **Python scripting console** — built-in REPL with full access to app_state, signals, and hardware objects.
- **Scientific data export** — TIFF (32-bit), HDF5, NumPy .npy, CSV, and MATLAB .mat formats with complete metadata (profile, ROI, modality, software version, timestamp).
- **Dark-pixel masking for ΔR/R** — pixels below 0.5 % of sensor full-scale are masked to NaN rather than producing noise-amplified false signal.
- **HardwareService** — all device lifecycle (camera, TEC × 2, FPGA, bias source, stage) owned by a single service with deterministic startup and shutdown.
- **First-run hardware setup wizard** — guides new installations through COM port selection, camera driver choice, and FPGA bitfile path; saves directly to config.yaml.
- **Software update system** — background check against GitHub Releases; amber badge in header when update is available; full release-notes dialog; configurable frequency and channel in Settings.
- **About dialog** — version, build date, OS/Python/Qt versions; one-click copy for support tickets.
- **Settings tab** — update preferences (auto-check, frequency, stable/beta channel); support links.
- **Help menu** — About, Check for Updates, Settings.
- **Version in window title and status bar** — always visible without opening any dialog.
- **Version logged on every startup** — first log lines identify software version and build date.
- **Camera platform guard** — Windows-only drivers (ni_imaqdx, directshow) fall back to simulated on macOS/Linux with a clear warning rather than crashing.
- **FPGA bitfile validation** — open() checks for missing file, missing resource string, and bad nifpga install before attempting to connect; targeted error messages for common NI error codes.

#### Architecture
- Single `version.py` as the only source of truth for the version number.
- `HardwareService` replaces module-level thread functions; all signal bridging centralised.
- `ApplicationState` class replaces module-level globals; thread-safe via context manager.
- Module-level `__getattr__` resolves legacy bare device names (`cam`, `fpga`, etc.) via `app_state`.
- `config.reload()` allows runtime config refresh after first-run wizard writes new values.

---

## How to add a new release entry

> **Repo layout**
> - **Source** (private): `github.com/edward-mcnair/sanjinsight` — code lives here
> - **Releases** (public): `github.com/edward-mcnair/sanjinsight-releases` — installers + release notes only

1. Duplicate the `[Unreleased]` section above, set the version and today's date.
2. Move items from Unreleased into the new section.
3. Update `version.py` — change `__version__`, `VERSION_TUPLE`, and `BUILD_DATE`.
4. Commit, tag, and push the **source** repo:
   ```
   git add CHANGELOG.md version.py
   git commit -m "Release v1.x.x"
   git tag -a v1.x.x -m "Release v1.x.x"
   git push origin main --tags
   ```
5. Build the Windows installer (PyInstaller).
6. Create a GitHub Release on the **public releases repo**
   (`github.com/edward-mcnair/sanjinsight-releases/releases/new`):
   - Tag: `v1.x.x`
   - Title: `SanjINSIGHT v1.x.x`
   - Body: paste the CHANGELOG section for this version
   - Attach: `SanjINSIGHT-Setup-1.x.x.exe`
