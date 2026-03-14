# Changelog — SanjINSIGHT

All notable changes to SanjINSIGHT are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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
