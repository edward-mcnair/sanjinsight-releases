# SanjINSIGHT

**Microsanj Thermal Analysis Software**

SanjINSIGHT is the instrument control and data acquisition software for the Microsanj EZ-500 and related thermoreflectance imaging systems.

---

## For users — Installing or upgrading

See [**README_INSTALL.md**](README_INSTALL.md) for the full Windows installation guide.

To install the latest release, go to the [**Releases**](../../releases) page and download `SanjINSIGHT-Setup-{version}.exe`.

The application checks for updates automatically on startup and displays a notification when a new version is available.

---

## What's New in v1.5.0

- **AI capability tiers and Proactive Advisor** — AI features auto-scale with model size (BASIC → STANDARD → FULL). The new AI Advisor analyses profile vs instrument state after every profile selection, identifies conflicts, and suggests one-click fixes. Supports TR, IR, and future camera modalities.
- **Phase-aware sidebar and Guided mode** — Workspace modes (Auto / Manual) with progressive disclosure. Guided walkthrough banner walks users through the measurement workflow step by step.
- **Plugin architecture (API v1)** — Manifest-based plugin system for tool, camera, analysis, and export plugins. Requires Developer license tier.
- **Architecture restructure** — Device services, acquisition subpackages, MeasurementOrchestrator state machine, and Failure Analysis vs Metrology workflow profiles
- **Crash-resilient session logging** — Session log mirrored to disk; crash detection dialog on restart with previous session's log
- **Multi-channel (RGB) color camera support** — pypylon auto-detects and demosaics Bayer sensors; DirectShow cameras support `color_mode: true`
- **Pre-capture validation system** — checks exposure quality, frame stability, focus, and hardware readiness before each acquisition (enabled by default)
- **FPS throughput optimizer** — one-click auto-tuning of LED power, FPS, and exposure via the Camera panel
- **FFC button for thermal cameras** — triggers flat-field correction directly from the Camera panel toolbar
- **Float64 pipeline averaging** — all averaged data uses float64 precision; HDF5 exports preserve full accuracy
- **RGB thermoreflectance per-channel analysis** — per-channel ΔR/R computation for color sensors
- **Autofocus convenience features** — quick-action Autofocus button on the Camera panel; optional auto-focus before each capture in Settings
- **Pipeline processing hooks** — extensible hook points in the acquisition pipeline for custom pre/post-processing

---

## For developers — Getting started

### Prerequisites
- Python 3.10+ (64-bit)
- Git

### Clone and run

```bash
git clone https://github.com/microsanj/sanjinsight.git
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

1. Update `version.py` — change `__version__`, `PRERELEASE`, `VERSION_TUPLE`, and `BUILD_DATE`
2. Add a release entry to `CHANGELOG.md`
3. Commit and tag:
   ```bash
   git add version.py CHANGELOG.md
   git commit -m "Bump version to v1.5.0-beta.1"
   git tag -a v1.5.0-beta.1 -m "SanjINSIGHT v1.5.0-beta.1"
   git push origin main v1.5.0-beta.1
   ```
4. CI builds the installer automatically and creates a GitHub Release with the `.exe` attached
5. The in-app update checker notifies users on next startup

---

## License

Copyright © 2026 Microsanj, LLC. All Rights Reserved.  
See [LICENSE](LICENSE) for terms.
