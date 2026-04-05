# Changelog — SanjINSIGHT

All notable changes to SanjINSIGHT are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.50.33-beta] — 2026-04-04

### Improved
- **WCAG AA contrast** — Light mode palette adjusted for accessibility: `success`, `warning`, `danger`, `info`, `cta`, `systemYellow`, `systemMint`, `systemCyan` all now meet WCAG AA contrast ratios on white backgrounds
- **Device Manager style DRY** — Extracted 6 repeated style patterns into helper functions (`_section_title_qss`, `_header_bar_qss`, `_accent_btn_qss`, `_cancel_btn_qss`, `_progress_bar_qss`, `_scroll_area_qss`) for maintainability
- **Font system consistency** — Migrated 24 hardcoded `font-size` values across 11 files to use `FONT['heading']`, `FONT['title']`, `FONT['readout']`, `FONT['readoutSm']`, `FONT['body']` from the design system, ensuring DPI scaling works correctly everywhere

## [Unreleased]

### Added

- **Observable state store** — `ApplicationState` now supports `subscribe(key, callback)` / `unsubscribe()` for reactive state change notifications. Property setters fire listeners when values actually change (identity comparison). `StateSignalBridge` in `ui/app_signals.py` marshals notifications to the Qt GUI thread via queued signals. All 20 state properties (cam, fpga, bias, stage, etc.) emit change notifications.
- **AI capability tier system** — Automatic feature gating (NONE → BASIC → STANDARD → FULL) based on model size and backend. Tier badge in AI panel, info strip in Settings, upgrade nudge system for tier-gated features.
- **Proactive AI Advisor** — Modal dialog analyses the selected material profile against live instrument state after every profile selection. Identifies conflicts (e.g. exposure too high for lock-in frequency) and suggests corrective settings with one-click "Apply fixes". Supports all camera modalities (TR, IR, future plugins).
  - Modality-aware physics reasoning (thermoreflectance vs IR thermal imaging)
  - Cloud models (Claude, ChatGPT) provide physics explanations; local models return compact JSON
  - Auto-launches when AI model loads after a profile is already selected
  - Retry with stricter JSON nudge on parse failure
  - Advisor results logged to the session log panel (not toasts)
  - Deduplicates fixes by parameter before applying
- **Auto-diagnosis on hardware errors** — Hardware errors automatically trigger AI diagnosis routed to the log panel (uses `infer()` directly, no chat history pollution). Throttled to once per 30 seconds.
- **Crash-resilient session logging** — `LogTab` messages are mirrored to `~/.microsanj/logs/session.log` (line-buffered). On unclean exit, the next launch shows a crash dialog with the previous session's log for diagnostics. HTML tags stripped via regex for the plain-text log file.
- **Phase-aware sidebar** — Workspace modes (Auto / Manual), progressive disclosure, collapsible hardware section, phase tracker with hardware signal wiring, SanjINSIGHT branding in header bar
- **Guided mode walkthrough** — Step-by-step banner with progress indicators, auto-advance, skip button, contextual hints, sidebar step indicators, Ctrl+1–9 section shortcuts
- **Plugin architecture (API v1)** — Manifest-based plugin system with Developer license tier, settings UI, and documentation. Supports tool, camera, analysis, and export plugin types.
- **Architecture restructure**:
  - Device services (`hardware/services/`) — Proper QObject service classes replacing monolithic HardwareService
  - Acquisition subpackages (`acquisition/processing/`, `calibration/`, `storage/`, `reporting/`) with backward-compat shims
  - `MeasurementOrchestrator` state machine for formal measurement lifecycle management
  - Workflow profiles (Failure Analysis vs Metrology) with configurable preflight strictness
- **Guided mode phases 1–5** — Complete reporting pipeline, export presets, batch reports, session packaging, export history
- **Profile picker** — Compact dropdown combo box filtered by camera modality, auto-exposure support, extended material profile library
- **System status dropdown** — Connected Devices button with diagnostic health details
- **MoreOptionsPanel** — Progressive disclosure in Analysis, Temperature, and Camera tabs
- **Time estimation** — Added to five long-running processes (acquisition, calibration, scan, batch, export)
- **TR vs IR control separation** — FFC controls gated on IR cameras, modality-appropriate controls across all panels
- **10 performance/UX improvements**:
  - Camera preview sleep reduced (50ms to 10ms) for snappier live feed
  - Colormap cache in comparison tab avoids repeated lookups
  - Memory-mapped array loading (`mmap_mode='r'`) for faster session opens
  - Undo/restore button for acquisition settings before each run
  - F5 global hotkey for Run Sequence (live stream moved to Ctrl+F5)
  - Post-capture sub-step labels ("Scoring...", "Saving...", "Writing manifest...")
  - Comparison tab auto-populates with 2 most recent sessions
  - Non-modal batch progress widget for background batch operations
  - Periodic mid-capture checkpoint (every 25% of frames) for crash recovery
  - Config `.json.bak` backup before every preferences write
- **Accessibility improvements**:
  - Sidebar navigation now keyboard-accessible (Tab, Enter/Space, focus indicator)
  - Accessible names and descriptions on all critical controls (E-stop, Run, Abort, spinboxes, combos)
  - WCAG AA contrast ratios verified and documented for dark mode palette
  - Shortcut overlay updated with current keybindings
- **CI/CD hardening**:
  - Expanded CI dependency list (qtawesome, Pillow, pyqtgraph, bcrypt, cryptography, etc.)
  - Feature branch CI triggers (`feature/**`)
  - Concurrency control to cancel stale CI runs
  - Test summary step for quick pass/fail visibility
- **Test coverage**: 31 new tests plus orchestrator, device services, and workflow test suites

### Changed

- **MainWindow decomposition** — Extracted EStopService, RecipeApplicationService, ProfileApplicationService into `ui/services/` (~410 lines removed from main_app.py)
- **Hardware discovery off GUI thread** — `_rescan_hardware()` now runs DiscoveryEngine in a QThread worker
- **TEC polling lock split** — `get_status()` split into two lock acquisitions (3+3 reads) to reduce contention
- AI Advisor feedback now routed to status bar + log panel instead of toast notifications
- `gain_db` available in advisor profile summary for all camera types (not just TR)
- `ContextBuilder` includes active camera type, driver type, and modality in instrument state JSON
- Sidebar navigation reduced from 23 to 12 items (Manual mode); reorganized into ACQUIRE / ANALYZE / HARDWARE / LIBRARY groups
- Full PALETTE conversion: eliminated all hardcoded hex colors across 40+ UI files for consistent theming

### Fixed

- **AI Advisor infinite loop** — `_on_ai_status("ready")` guarded with `_advisor_launched_for` to prevent re-launch after advisor completes
- **AI Advisor race condition** — Cancel + retry with max 15 attempts (3s cap) when pre-empting busy AI runner; advisor dialog properly closed on programmatic cancel
- **Auto-diagnosis `_diag_active` stuck True** — Handlers stored on `self` and disconnected on preemption by advisor
- **False crash dialog on every launch** — Fixed `open_session_log()` / `previous_crash_log()` call order (read crash log before truncating)
- **Session log HTML stripping** — Now strips all HTML tags via regex and decodes additional entities (`&nbsp;`, `&quot;`, `&#39;`)
- Theme switch crash: `_apply_styles()` on `AcquisitionSummaryOverlay` now accepts optional scorecard parameter
- HTTP connection leak in Ollama client (`ai/remote_runner.py`)
- 3 Windows 11 compatibility fixes (DPI scaling, font rendering, file path handling)
- TypeError in live probe when ΔR/R array is 3D (RGB)
- FFC button visibility on modality change across all panels
- Guided banner Next button loop with robust advance logic
- Signal Check SNR now uses temporal noise, not spatial variation
- Profile cleared when modality filter removes it; header pill updates accordingly
- Duty cycle auto-fix loop and download progress display
- Startup crash with module-level `hw_service` and deferred device manager wiring
- **Thread safety** — `config.py` globals and `Session` lazy-load properties guarded with locks; all 17 hardware signal connections use `Qt.QueuedConnection`; `QThread.wait()` calls capped at 3 s
- **Newport NPC3 port lock leak** — `PortLock.release()` now called on disconnect
- **Camera reconnect crash** — `cam.open()`/`cam.start()` wrapped in try/except
- **Device scanner silent failures** — Camera enumeration `except: pass` replaced with `log.debug()` for visibility

---

## [1.50.32-beta] — 2026-04-03

### Added

- **NI sbRIO FPGA support** — New `ni_sbrio` device registry entry for the Single-Board RIO built into the EZ-500 chassis. Connects via Ethernet (link-local 169.254.x.x) using the existing `Ni9637Driver` and `nifpga` library. Device Manager shows IP address, NI Resource string, and FPGA Bitfile (with Browse) fields for sbRIO and NI 9637 devices.
- **NI-VISA Runtime** bundled in installer — Optional online installer for GPIB/SMU instruments (Keithley 2400/2450). Unchecked by default since USB and LAN instruments work without it via `pyvisa-py`.
- **Newport NPC3SG in first-run wizard** — Stage driver selector now includes `newport_npc3` with auto-selected 19200 baud; hardware discovery auto-fills NPC3 when detected.
- **NI 9637 FPGA driver rewrite** (`hardware/fpga/ni9637.py`) — Complete rewrite to match actual `FPGA_CODE.vi` firmware registers (38+ controls/indicators). Adds `session.reset()` + `session.run()` FPGA initialization sequence. All register names now match the bitfile exactly.
- **EZ-500 FPGA extended controls** — 16 new service-layer methods for voltage DAC (±16V FXP20), LED illumination timing (CW + pulsed), device phase offsets, exposure timing, external sync, sample rate, trigger I/O direction, high-range mode, IR frame trigger, event trigger system, and analog input readback.
- **FPGA tab EZ-500 panels** — 5 new collapsible UI sections (auto-hidden until NI9637 connects): Voltage Output, LED Timing, Phase & Timing, Sync & Trigger I/O, Event Trigger. All wired through service layer to firmware registers.
- **TEC ramp speed control** — Temperature tab gains ramp speed spinbox (0–50 °C/s) for Meerstetter TEC-1089 temperature ramping (parameter 3003).
- **TEC temperature safety limits** — Service-layer method for ATEC-302 hardware limit registers.
- **Camera trigger mode** — `set_trigger_mode()` added to pypylon driver using GenICam IEnumeration API ("Off" = free-running, "On" = external trigger).
- **FPGA bitfile bundling** — Installer (Inno Setup) and PyInstaller spec both include `firmware/ez500_fpga.lvbitx` for deployment.

### Changed

- **FPGA config** — `initial_freq_hz` replaced with `initial_period_us: 1000.0` to match firmware register convention.

- **Connected Devices dropdown now shows ALL device types** — TEC, stage, FPGA, bias, LDD, GPIO, and prober now appear in the status header dropdown, not just cameras. Previously only camera devices called `set_connected()`.
- **FTDI driver description** updated across installer, build script, and verification to list all covered devices: TEC-1089, LDD-1121, Newport NPC3SG, and Thorlabs stage controllers.
- **Installer driver page** — All checkbox captions now specify which EZ-500 devices each driver covers. Post-install summary includes "built-in" section for Rigol DP832 (Windows USB TMC / LAN — no install needed). NI-RIO label updated to mention sbRIO.
- **First-run wizard FPGA page** renamed from "NI 9637" to "NI sbRIO / NI 9637".
- **Status header label** "FPGA" → "FPGA / sbRIO".

### Fixed

- **Newport NPC3 "Write timeout"** — Three root causes: (1) missing `write_timeout` on serial port, (2) `\r\n` terminator changed to `\r` per NPC3 protocol, (3) write-only commands (`set`, `setall`, `setk`, `cloop`) no longer block waiting for a nonexistent response.
- **Missing PyInstaller hidden imports** — Added `hardware.ldd.meerstetter_ldd1121`, `hardware.ldd.simulated`, `hardware.arduino.nano_driver`, `hardware.arduino.simulated`, `hardware.fpga.bnc745`, `hardware.bias.amcad_bilt`, and `hardware.bias.rigol_dp832` to both Windows and macOS `.spec` files. Without these, LDD, Arduino GPIO, BNC 745, and AMCAD BILT devices would fail with `ImportError` in production builds.

### Fixed (Hardware Drivers)

- **ATEC-302 wrong register map** — Registers 0x0002/0x0003 were incorrectly labelled as output current/voltage; they are actually high/low temperature safety limits per the ATEC protocol spec. `get_status()` no longer reads wrong registers.
- **ATEC-302 wrong stop bits** — Changed from `STOPBITS_ONE` to `STOPBITS_TWO` (N-8-2 framing required by ATEC-302 spec).
- **ATEC-302 missing input buffer reset** — Added `reset_input_buffer()` before all serial writes to clear stale bytes, matching the original reference implementation.
- **ATEC-302 missing control methods** — Added `set_temperature_limits()`, `get_alarm_status()`, and `set_control_mode()` from the reference protocol spec.
- **ATEC-302 baud rate mismatch** — Device registry listed 38400 baud but the ATEC-302 protocol defaults to 9600. Registry corrected.
- **Meerstetter missing ramp control** — Added `set_ramp_speed()` method using parameter 3003 with thread-safe `_api_lock` protection.
- **Boson+ models not handled in Device Manager** — Video-only mode guard and geometry injection (width/height) now include Boson+ 320 and Boson+ 640.
- **Newport NPC3SG missing driver mapping** — `newport_npc3` was in the device registry but had no entry in Device Manager's driver key map.
- **Removed duplicate Microsanj IR Camera** — Eliminated confusing duplicate of FLIR Boson 320; users select FLIR Boson / Boson+ instead.
- **First-run wizard camera driver** — Default IR camera driver changed from `flir` (requires Spinnaker SDK) to `boson` (bundled, no extra install). Added Boson test button.

---

## [1.5.0-beta.3] — 2026-04-02

### Added

- **Single-instance guard** — Prevents multiple app launches fighting over COM ports and cameras. Uses QLocalServer/QLocalSocket (cross-platform); second launch activates the existing window and exits.
- **Camera type auto-detection** — TR/IR type is now detected from the device registry based on camera model. Shows detected type prominently with model context; collapsible "Override" toggle for manual selection with "Reset to detected" to clear saved overrides.
- **Error taxonomy** (`hardware/error_taxonomy.py`) — 10-category `DeviceError` classification (missing driver, permission denied, device busy, timeout, etc.) with actionable suggested fixes, replacing truncated `str(e)[:60]` error strings across all 5 device services.
- **Support bundle auto-trigger** (`hardware/support_bundle.py`) — `SupportBundleTrigger` fires a toast notification after 3 consecutive failures for the same device, offering to generate a diagnostic zip bundle.
- **OS-level diagnostics** (`hardware/os_checks.py`) — Platform-specific checks run during device discovery: USB selective suspend (Windows), COM port locks (Windows), camera permissions (macOS), dialout group membership (Linux), serial port health (all).
- **Device state machine** (`hardware/device_state.py`) — Formal `DeviceState` enum with validated lifecycle transitions (DISCONNECTED → CONNECTING → CONNECTED → ERROR, etc.).
- **Driver health contract** (`hardware/driver_contract.py`) — Runtime-checkable `DriverHealthCheck` protocol for driver detection, install guidance, and self-test.
- 4 new MDI icon constants: `IC.DISCONNECT`, `IC.GLOBE`, `IC.CLIPBOARD`, `IC.DOWNLOAD`

### Changed

- **Device Manager font sizes** — All panels bumped for comfortable reading: labels/inputs/buttons 8.5→10pt, group box titles 9.5→11pt, section headers 9.5→11pt, left panel tree 10→11pt, row height 34→36px. Smallest remaining font is 8.5pt (log filter combo).
- **Device Manager UX improvements** — Tinted category headers with letter spacing, persistent port test status indicator, prominent red-bordered error banner with copy button and show more/less toggle, "Connecting…"/"Disconnecting…" loading indicators, address column tooltips, expandable driver changelog cards, log level filter combo (All/Info+/Warning+/Error+), all emoji icons replaced with MDI equivalents.

### Fixed

- **Override button crash** — `clicked(bool)` signal passed a bool as the first positional argument, overriding the closure's `btn` default parameter. Fixed with lambda wrapper.
- **Show More button crash** — Same `clicked(bool)` signal issue on error banner expand toggle.
- **`os.getlogin()` OSError** — Fixed crash in non-interactive Linux sessions (Docker, SSH without PTY, systemd) with fallback to `$USER`/`$LOGNAME` environment variables.
- **Camera type reverting after connection** — `device_manager.py` was unconditionally overwriting `camera_type` from device registry, ignoring user preferences saved in `device_params`. Now checks `config.get_pref()` first.

---

## [1.5.0-beta.2] — 2026-04-01

### Added

- **Arduino Nano driver** — Full driver stack for ATmega328P as a general-purpose I/O controller: LED wavelength selector (4 channels: 470/530/590/625 nm), digital GPIO (D6–D13), and 10-bit ADC (A0–A7). Includes base ABC, serial driver (CH340/FTDI auto-detect), simulated driver for demo mode, factory, device registry entries (`DTYPE_GPIO`), app_state slot, device manager wiring, and AI context builder integration.
- **Arduino UI tab** — New sidebar entry under HARDWARE with LED radio selector, GPIO toggle buttons, ADC readout with voltage conversion, controller status polling, and empty-state placeholder with Device Manager link.
- **Arduino firmware sketch** (`firmware/arduino_nano/sanjinsight_io.ino`) — Line-based ASCII serial protocol: `LED`, `PIN`, `READ`, `ADC`, `STATUS`, `IDENT` commands. Ready to flash via Arduino IDE.

### Fixed

- **IC.CHIP AttributeError** — Arduino nav icon referenced non-existent `IC.CHIP`; changed to `mdi.integrated-circuit-chip`.
- **IC.COG AttributeError** — Arduino tab empty-state button referenced non-existent `IC.COG`; changed to `IC.SETTINGS`.
- **PALETTE key errors** — Arduino tab used non-existent `hover` and `pass` keys; corrected to `surfaceHover` and `success`.

---

## [1.5.0-beta.1] — 2026-03-25

### Added

- **Multi-channel (RGB) camera support** — Color cameras now flow (H,W,3) data through the entire pipeline: capture, averaging, ΔR/R computation, display, analysis, and export. Supported drivers: pypylon (Bayer demosaic), DirectShow, and simulated camera. Thermal IR cameras (Boson, FLIR) remain mono.
- **`CameraFrame` generalized** — New `channels` (1=mono, 3=RGB) and `bit_depth` fields on CameraFrame; `pixel_format` field on CameraInfo. All drivers now report explicit channel/bit-depth metadata.
- **Float64 pipeline averaging** — All pipeline averaging upgraded from float32 to float64 for >15 significant digits of precision when averaging many frames.
- **Pipeline processing hooks** — `pre_capture_hooks` and `post_average_hooks` on `AcquisitionPipeline` enable extensibility without modifying `_run()`.
- **Session schema v3** — Adds `frame_channels`, `frame_bit_depth`, `pixel_format`, and `preflight` fields. Automatic cumulative migration from v1/v2.
- **FFC (Flat-Field Correction) UI button** — Visible on Camera tab when camera supports FFC (Boson, FLIR). Wires to existing `send_ffc()` / `do_ffc()` driver methods.
- **FPS Optimizer** (`acquisition/fps_optimizer.py`) — Three-step auto-optimization: maximize LED duty cycle, maximize frame rate, binary-search exposure for 70% of dynamic range.
- **RGB thermoreflectance analysis** (`acquisition/rgb_analysis.py`) — Per-channel split, Rec. 709 luminance, per-channel statistics, and per-channel analysis engine dispatch.
- **Pre-capture validation system** — Read-only preflight checks (exposure quality, frame stability, focus, hardware readiness, TEC stability) run before each acquisition. Dismissable dialog with traffic-light results. Toggle in Settings.
- **Shared image metrics** (`acquisition/image_metrics.py`) — `compute_focus()`, `compute_intensity_stats()`, `compute_frame_stability()` used by both MetricsService and PreflightValidator.
- **Autofocus quick-button** on Camera tab — Runs AF with last-used settings from a background thread. Disabled when no stage connected.
- **"Optimize Throughput" button** on Camera tab — Runs FPS optimizer in background thread.
- **"Auto-focus before each capture" checkbox** in Settings.
- **Autofocus settings persistence** — Last-used AF config saved to preferences.
- **Example test CSV** (`docs/samples/example_test.csv`) — 20 rows of representative thermoreflectance data with PASS/WARN/FAIL examples.

### Fixed

- **Thread safety: `_on_quick_af()` UI updates** — Moved `setEnabled`/`setText` calls from worker thread to main thread via `QTimer.singleShot(0, ...)`.
- **UI blocking: `_on_optimize()`** — Moved FPS optimizer execution to a background thread.
- **Stale closure: AF pre-capture hook** — Hook now resolves `app_state.cam`/`app_state.stage` at execution time, not closure creation time.
- **Missing CameraFrame fields** — Boson driver now sets `channels=1, bit_depth=14`; FLIR driver sets `channels=1, bit_depth=16`.
- **FPS optimizer streaming assumption** — Now detects if camera isn't streaming, starts it, and cleans up afterward.
- **`to_display()` luminance calculation** — Signed mode now uses Rec. 709 weights instead of `mean(axis=2)`.
- **Simulated camera `set_resolution()`/`set_fps()`** — Now preserve `camera_type` and `pixel_format` when rebuilding CameraInfo.
- **8-bit to 12-bit scaling** — pypylon and DirectShow RGB conversion changed from `<< 4` (0-4080) to `* 4095 // 255` (correct 0-4095).
- **Drift correction with RGB frames** — `estimate_shift()` now receives luminance; `apply_shift()` builds correct shift tuple for 3D arrays.
- **Transient pipeline multi-channel** — Accumulator shape matches frame dimensionality; dark-mask computed on luminance and broadcast correctly.
- **Movie pipeline multi-channel** — Same drift correction and dark-mask fixes as transient pipeline.
- **Export float64 preservation** — `_collect_data()` no longer casts to float32; HDF5 stores native float64; TIFF keeps float32 for file size.
- **Export multi-channel** — TIFF axes metadata set to "YXC" for 3-channel; CSV reduces to luminance for 2D output.
- **Analysis multi-channel** — `ThermalAnalysisEngine.run()` and overlay renderer reduce RGB input to luminance for threshold/morphology.
- **Session difference precision** — `session_manager.py` comparison now returns float64 instead of float32.

### Changed

- **MetricsService focus computation** — Delegates to shared `acquisition.image_metrics.compute_focus()`.
- **Schema migration v2→v3 docstring** — Clarifies why `frame_bit_depth=16` is the correct conservative default for legacy sessions.

---

## [1.4.1-beta.2] — 2026-03-24

### Added

- **FTDI VCP driver bundled in installer** — the FTDI CDM (Combined Driver Model) driver is now automatically downloaded and included in the Windows installer. It installs silently during setup if not already present, so the Meerstetter TEC-1089 and LDD-1121 appear as COM ports immediately after installation.
- **pyMeCom auto-installed in local builds** — `build_installer.bat` now installs pyMeCom (and pydp832) from GitHub before running PyInstaller, matching the CI workflow behavior.
- **`find_all_by_usb()` in device registry** — returns all registry entries matching a given VID:PID, fixing FTDI VID:PID sharing between Meerstetter TEC, ATEC, and LDD devices.

### Fixed

- **Camera "exclusively opened" race condition** — `hw_service.start()` and Device Manager auto-reconnect were both trying to open the same USB camera. Added `skip_cameras=True` parameter so only one code path owns camera connections.
- **Boson "could not open video device" on Windows** — auto-detect used `cap.get()` which returns stale values on Windows DirectShow until a frame is read. Replaced with frame-verify pass. Also fixed PnP enumeration order being incorrectly used as DirectShow index.
- **Camera selection not persisting across tabs** — three separate force-resets were overriding the user's IR/TR choice: (1) `_inject_into_app` force-switching to TR on TR connect, (2) `_switch_to_real` always defaulting to TR, (3) `AcquireTab` missing `showEvent`. All three fixed; saved preference now restored on tab switch and camera reconnect.
- **Undefined `dtype` in `_connect_worker`** — `dtype` was referenced for camera timeout check but never assigned in that scope.
- **TEC-1089 port conflict** — scanner deduplication used address-only keys, dropping the second device on the same COM port. Changed to `(address, uid)` composite key.
- **pyMeCom wrong GitHub URL** — CI workflow referenced `marcwimmer/pyMeCom` instead of the correct `meerstetter/pyMeCom`.
- **pyMeCom not available on PyPI for Python 3.10** — reverted to optional dependency installed from GitHub in CI and build scripts.
- **qtawesome missing from Windows installer** — added to hidden_imports and `collect_data_files()` in the Windows PyInstaller spec.
- **Inno Setup compile errors** — CI-generated ISS script had invalid `[Run]` flags (`waitprogress`, `skipifdoesntexist`). Replaced with valid flags and moved file-existence checks into Pascal Script functions.

---

## [1.4.1-beta.1] — 2026-03-19

### Added

- **FLIR Boson camera driver** (`hardware/cameras/boson_driver.py`) — `BosonDriver` class supporting the FLIR Boson 320 and Boson 640 uncooled microbolometer cameras. Uses a two-channel architecture: serial FSLP control via the bundled FLIR Boson 3.0 Python SDK (`hardware/cameras/boson/`) and UVC video capture via `cv2.VideoCapture` with Y16 FOURCC for 14-bit radiometric data. `send_ffc()` triggers a Flat Field Correction cycle via the SDK. Video-only mode is activated automatically when `serial_port` is blank — FFC and SDK commands are unavailable but frame capture works normally.
- **Bundled FLIR Boson 3.0 Python SDK** (`hardware/cameras/boson/`) — pure-Python, no DLL required. Package structure: `ClientFiles_Python/` (FSLP client) + `CommunicationFiles/` (serial framing). No manual SDK download or install needed.
- **New camera registry entries**: `flir_boson_320` (320×256, 14-bit, USB, IR), `flir_boson_640` (640×512, 14-bit, USB, IR), `basler_a2a1280_125um_swir` (1280×1024, USB3, TR/NIR), `allied_vision_goldeye_g032` (640×480, GigE, IR/SWIR), `photonfocus_mv4_d1280u` (1280×1024, GigE, TR).
- **Camera ICD/IID files** bundled in `assets/camera_icd/` — NI IMAQdx camera interface descriptors for Basler a2A1280-125umSWIR, Allied Vision Goldeye G-032 Cool, and Photonfocus MV4-D1280U-H01-GT. Install by copying `.icd`/`.iid` files to the NI IMAQdx camera directory and restarting NI MAX.
- **`DeviceEntry.video_index`** — new integer field (default 0) on `DeviceEntry` for selecting the UVC device index passed to `cv2.VideoCapture`. Persisted in device-params prefs so the setting survives restarts.
- **Device Manager** — FLIR Boson camera entries now show **Serial Port** and **Video Device Index** fields in the Connection Parameters area.
- **Windows spec** (`installer/sanjinsight.spec`) — Boson SDK hidden imports and data tree added so the bundled pure-Python SDK is included in the PyInstaller output.

### Changed

- **pypylon wheel is self-contained** — the pypylon wheel bundles the pylon runtime internally; no separate Basler SDK install is required. Updated all documentation references accordingly.

### Fixed

- **Invalid `__init__.py`** in `hardware/cameras/boson/` — file contained only a pass-through comment and prevented the package from being imported. Replaced with a proper empty `__init__.py`.
- **`sys.path.append(None)`** — `BosonDriver.__init__` could append `None` to `sys.path` when `serial_port` was unset, polluting the path and causing unrelated import failures.
- **Serial port leak** — `BosonDriver.close()` did not call `sdk_client.close()` when serial was open, leaving the port held after disconnect.
- **Address guard blocking video-only mode** — `DeviceManager` address guard raised "No port or address configured" for Boson cameras registered with a blank `serial_port`. Guard now exempts Boson entries when `serial_port` is blank and `video_index` is set.
- **`isOpen()` deprecated call** — replaced `serial.Serial.isOpen()` (deprecated since pyserial 3.0) with the `serial.Serial.is_open` property in `BosonDriver`.
- **Missing `self` in `PortBase`** — `PortBase.__init__` in the Boson SDK `CommunicationFiles/` was missing `self` as the first parameter, causing `TypeError` on instantiation.
- **`print()` calls in frozen bundle** — debug `print()` statements in the Boson SDK client files replaced with `logging.getLogger(__name__).debug()` to avoid console output in PyInstaller frozen builds.
- **Y16 FOURCC validation** — `cv2.VideoCapture` silently accepted non-Y16 streams on some UVC devices, returning 8-bit frames that appeared valid but had incorrect radiometric scaling. `BosonDriver.open()` now validates the negotiated FOURCC and raises `RuntimeError` if Y16 is not obtained.

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
