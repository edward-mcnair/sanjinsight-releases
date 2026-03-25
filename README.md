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
├── main_app.py              # Application entry point
├── version.py               # Single source of truth for version number
├── updater.py               # GitHub Releases update checker
├── config.py                # Configuration loader
├── config.yaml              # Hardware configuration (edit per installation)
├── CHANGELOG.md             # Release history
├── requirements.txt         # Python dependencies
├── README_INSTALL.md        # Windows installation guide for end users
│
├── hardware/                # Device drivers (camera, TEC, FPGA, bias, stage)
│   ├── cameras/             # Basler, NI IMAQdx, FLIR Boson, DirectShow, simulated
│   ├── tec/                 # Meerstetter TEC-1089, ATEC-302, simulated
│   ├── fpga/                # NI 9637 via nifpga, simulated
│   ├── bias/                # Keithley, VISA-generic, simulated
│   ├── stage/               # Thorlabs, serial, simulated
│   ├── hardware_service.py  # Owns all device threads and lifecycle
│   └── app_state.py         # Thread-safe shared application state
│
├── acquisition/             # Measurement pipeline and data management
│   ├── pipeline.py          # Hot/cold frame capture, ΔR/R computation
│   ├── session.py           # Session data model
│   ├── session_manager.py   # Session storage and retrieval
│   └── export.py            # TIFF, HDF5, NumPy, CSV, MATLAB export
│
├── ui/                      # UI components
│   ├── charts.py            # PyQtGraph chart widgets (calibration, analysis, transient, sessions)
│   ├── sidebar_nav.py       # Bootstrap-style collapsible sidebar
│   ├── wizard.py            # Standard mode guided wizard
│   ├── settings_tab.py      # Update preferences, about, support
│   ├── update_dialog.py     # Update badge, update dialog, about dialog
│   ├── first_run.py         # First-run hardware setup wizard
│   └── device_manager_dialog.py
│
├── profiles/                # Measurement profiles (C_T values)
└── tests/                   # Unit tests
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
