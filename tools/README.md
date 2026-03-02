# tools/

Standalone development and diagnostic utilities.

These scripts are **not part of the main SanjINSIGHT application**. They create
their own hardware driver instances directly and are intended for low-level
debugging and testing outside the main UI.

| Script | Purpose |
|--------|---------|
| `acquisition_panel.py` | Minimal standalone acquisition panel (no main-app dependency) |
| `tec_panel.py` | TEC controller diagnostic panel |
| `viewer.py` | Raw camera frame viewer |

> **Warning:** These scripts bypass `HardwareService` and create drivers directly.
> Do not run them while the main application is connected to the same hardware.

## Running

```bash
cd /path/to/sanjinsight
python tools/acquisition_panel.py
python tools/tec_panel.py
python tools/viewer.py
```
