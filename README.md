# SanjINSIGHT

**Microsanj Thermal Analysis Software**

SanjINSIGHT is the instrument control and data acquisition software for the Microsanj EZ-500 and related thermoreflectance imaging systems.

---

## For users — Installing or upgrading

See [**README_INSTALL.md**](README_INSTALL.md) for the full Windows installation guide.

To install the latest release, go to the [**Releases**](https://github.com/edward-mcnair/sanjinsight-releases/releases) page and download `SanjINSIGHT-Setup-{version}.exe`.

The application checks for updates automatically on startup and displays a notification when a new version is available.

---

## What's New in v0.44.0

- **Measurement Setup** — Replaces the old Quick Start launcher. Single entry surface: Camera → Measurement Goal → Material Profile → Begin. Camera type (TR/IR) determines available goals automatically.
- **Hardware category panels** — Sidebar HARDWARE section restructured from individual tabs to 6 dynamic category panels: Cameras, Stages, Thermal Control, Stimulus & Timing, Probes, Sensors. Device tabs appear/disappear on connect/disconnect.
- **Recipe system** — Recipe Builder with variable designation (mark fields as operator-adjustable), workspace mode gating (Standard = view-only, Expert = full edit), and run-time preview. Recipe Run Panel for operator execution with Experiment Log integration.
- **Experiment Log** — Tracks all recipe runs with verdict, hotspots, peak ΔT, duration. Guided mode shows simplified 7-column view; Standard/Expert shows full 12-column detail. CSV export, row-to-session drill-down, auto-refresh.
- **Guided walkthrough** — 15 steps across 5 phases (Configuration → Image Acquisition → Analysis → Hardware Automation → Data & Reporting). Phase-aware sidebar with progress dots.
- **Workspace modes** — Guided / Standard / Expert with progressive disclosure across all surfaces.
- **Error taxonomy and support bundles** — 30-category error classification with actionable suggested fixes. Auto-triggered diagnostic bundle after repeated failures.
- **Hardened release pipeline** — CI cross-publishes to public releases repo with post-publish verification. Fail-fast if installer asset is missing.
- **AI capability tiers** — BASIC / STANDARD / FULL auto-scaling with Proactive Advisor.
- **Plugin architecture (API v1)** — Manifest-based plugin system. Requires Developer license tier.
- **Pre-capture validation** — exposure quality, frame stability, focus, and hardware readiness checks before each acquisition.

---

## For developers — Getting started

### Prerequisites
- Python 3.10+ (64-bit)
- Git

### Clone and run

```bash
git clone https://github.com/edward-mcnair/sanjinsight.git
cd sanjinsight
pip install -r requirements.txt
python main_app.py
```

The app starts in simulated mode — no hardware required for development.

### Project structure

```
sanjinsight/
├── main_app.py              # Application entry point; MainWindow class
├── version.py               # Single source of truth for version number
├── config.py                # Configuration loader
├── config.yaml              # Hardware configuration (edit per installation)
├── logging_config.py        # Rotating log file, session log, crash detection
├── CHANGELOG.md             # Release history
├── requirements.txt         # Python dependencies
│
├── hardware/                # Device drivers and services
│   ├── cameras/             # Basler, NI IMAQdx, FLIR Boson, DirectShow, simulated
│   ├── tec/                 # Meerstetter TEC-1089, ATEC-302, simulated
│   ├── fpga/                # NI 9637 via nifpga, simulated
│   ├── bias/                # Keithley, VISA-generic, simulated
│   ├── stage/               # Thorlabs, serial, simulated
│   ├── services/            # Per-device QObject service classes
│   ├── hardware_service.py  # Coordinator with signal forwarding
│   ├── readiness_orchestrator.py  # Multi-step hardware prep sequencer
│   ├── error_taxonomy.py    # 30-category error classification with suggested fixes
│   ├── support_bundle.py    # Diagnostic zip generator (14 sections)
│   ├── os_checks.py         # Platform-specific diagnostics (USB, permissions)
│   └── app_state.py         # Thread-safe shared application state
│
├── acquisition/             # Measurement pipeline and data management
│   ├── pipeline.py          # Hot/cold frame capture, ΔR/R computation
│   ├── measurement_orchestrator.py  # Formal measurement lifecycle state machine
│   ├── workflows/           # Failure Analysis / Metrology workflow profiles
│   ├── processing/          # Image filters, drift correction, quality scoring
│   ├── calibration/         # Calibration runner and library
│   ├── storage/             # Sessions, autosave, export, export presets
│   └── reporting/           # HTML reports, batch reports, report presets
│
├── ai/                      # AI assistant and diagnostics
│   ├── ai_service.py        # Multi-backend AI service (local + cloud)
│   ├── advisor.py           # Proactive AI Advisor (profile vs instrument)
│   ├── tier.py              # AITier enum and feature gating
│   ├── context_builder.py   # Live instrument state JSON for prompts
│   ├── diagnostic_engine.py # Rule-based readiness grading (A–D)
│   └── instrument_knowledge.py  # Domain knowledge for AI prompts
│
├── ui/                      # UI components
│   ├── sidebar_nav.py       # Phase-aware collapsible sidebar
│   ├── theme.py             # Design system: palettes, QSS builder
│   ├── icons.py             # MDI icon registry
│   ├── tabs/                # Merged tab widgets (Capture, Stimulus, Library, etc.)
│   ├── widgets/             # Shared widgets (advisor dialog, readiness, toasts, etc.)
│   └── guidance/            # Guided walkthrough steps and content
│
├── plugins/                 # Plugin API v1 (manifest-based)
├── profiles/                # Measurement profiles (C_T values)
├── docs/                    # User manual, developer guide, quickstart
└── tests/                   # Unit and integration tests
```

### Running tests

```bash
pytest tests/
```

---

## Releasing a new version

1. Update `version.py` — change `__version__`, `PRERELEASE`, and `BUILD_DATE`
2. Add a release entry to `CHANGELOG.md`
3. Commit and tag:
   ```bash
   git add version.py CHANGELOG.md
   git commit -m "Bump version to v0.44.0-beta.1"
   git tag -a v0.44.0-beta.1 -m "SanjINSIGHT v0.44.0-beta.1"
   git push origin main v0.44.0-beta.1
   ```
4. CI builds the Windows installer and cross-publishes to the public `sanjinsight-releases` repo
5. A post-publish verification step confirms the release and installer asset are live
6. The in-app update checker notifies users on next startup

> **Repos:** Source code lives in the private `edward-mcnair/sanjinsight` repo. Packaged installers are published to the public `edward-mcnair/sanjinsight-releases` repo. The in-app updater only checks the public repo — no authentication required.

---

## License

Copyright © 2026 Microsanj, LLC. All Rights Reserved.  
See [LICENSE](LICENSE) for terms.
