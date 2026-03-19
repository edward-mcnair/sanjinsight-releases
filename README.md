# SanjINSIGHT

**Microsanj Thermal Analysis Software**

SanjINSIGHT is the instrument control and data acquisition software for the Microsanj EZ-500 and related thermoreflectance imaging systems.

---

## For users — Installing or upgrading

See [**README_INSTALL.md**](README_INSTALL.md) for the full Windows installation guide.

To install the latest release, go to the [**Releases**](../../releases) page and download `SanjINSIGHT-Setup-{version}.exe`.

The application checks for updates automatically on startup and displays a notification when a new version is available.

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
│   ├── cameras/             # Basler, NI IMAQdx, DirectShow, simulated
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

1. Update `version.py` — change `__version__` and `BUILD_DATE`
2. Add a release entry to `CHANGELOG.md`
3. Commit and tag:
   ```bash
   git add -A
   git commit -m "Release v1.0.1"
   git tag -a v1.0.1 -m "Release v1.0.1"
   git push origin main --tags
   ```
4. On GitHub: **Releases → Draft a new release → Choose tag v1.0.1**
5. Paste the CHANGELOG section as release notes
6. Attach the Windows installer `.exe` as a release asset
7. Publish — the in-app update checker will notify users automatically

---

## License

Copyright © 2026 Microsanj, LLC. All Rights Reserved.  
See [LICENSE](LICENSE) for terms.
