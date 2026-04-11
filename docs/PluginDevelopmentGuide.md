# SanjINSIGHT Plugin Development Guide

**Plugin API v1** | SanjINSIGHT v0.44.0+

---

## Overview

The SanjINSIGHT plugin system allows authorized developers to extend the
application with custom hardware drivers, analysis algorithms, UI panels,
and tool integrations. Plugins are discovered at startup from the user's
`~/.microsanj/plugins/` directory.

**License requirement:** Plugin loading requires a **Developer** or **Site**
license tier. Standard licenses do not load plugins.

---

## Quick Start

1. Create a folder: `~/.microsanj/plugins/my-plugin/`
2. Add a `manifest.json` (see [Manifest Schema](#manifest-schema))
3. Add your Python module (e.g., `plugin.py`)
4. Restart SanjINSIGHT

Your plugin appears in **Settings > Plugins** with an enable/disable toggle.

---

## Plugin Types

| Type | Base Class | UI Slot | Use Case |
|------|-----------|---------|----------|
| `hardware_panel` | `HardwarePanelPlugin` | Sidebar > HARDWARE section | Custom device control panel |
| `analysis_view` | `AnalysisViewPlugin` | Sidebar > ANALYSIS section | Custom analysis/results view |
| `tool_panel` | `ToolPanelPlugin` | Sidebar > TOOLS section | General-purpose utility |
| `drawer_tab` | `DrawerTabPlugin` | Bottom drawer tab | Diagnostics, live data feeds |
| `hardware_driver` | `HardwareDriverPlugin` | None (registers with device manager) | Device driver without UI |
| `analysis_pipeline` | `AnalysisPipelinePlugin` | None (registers processing function) | Data processing pipeline |

---

## Manifest Schema

Every plugin must include a `manifest.json` in its root directory:

```json
{
    "id": "com.yourcompany.plugin-name",
    "name": "Human-Readable Name",
    "version": "1.0.0",
    "api_version": 1,
    "author": "Your Name or Organization",
    "description": "Brief description of what the plugin does.",

    "plugin_type": "tool_panel",

    "entry_point": "plugin:MyPluginClass",

    "min_license_tier": "developer",

    "sidebar": {
        "section": "TOOLS",
        "label": "My Tool",
        "icon": "mdi.wrench"
    },

    "drawer_tab": {
        "label": "My Log",
        "icon": "mdi.text-box-outline"
    },

    "dependencies": {
        "python": ["numpy>=1.20"],
        "plugins": []
    },

    "min_app_version": "0.44.0",
    "platforms": ["win32", "darwin", "linux"]
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `id` | Unique reverse-domain identifier (e.g., `com.university.cryo-stage`) |
| `name` | Display name shown in sidebar and settings |
| `version` | Semantic version of the plugin |
| `plugin_type` | One of the six types listed above |
| `entry_point` | `"module_name:ClassName"` — the Python file and class to load |

### Optional Fields

| Field | Default | Description |
|-------|---------|-------------|
| `api_version` | `1` | Plugin API version targeted (must not exceed host's version) |
| `min_license_tier` | `"developer"` | Minimum license tier: `standard`, `developer`, or `site` |
| `sidebar` | — | **Required** for `hardware_panel`, `analysis_view`, `tool_panel` |
| `drawer_tab` | — | **Required** for `drawer_tab` type; optional for others |
| `dependencies.python` | `[]` | pip package specifiers checked at load time |
| `dependencies.plugins` | `[]` | Plugin IDs that must load before this one |
| `min_app_version` | `"1.0.0"` | Minimum SanjINSIGHT version |
| `platforms` | `["win32","darwin","linux"]` | Supported platforms |

### Icons

Icons use Material Design Icons via `qtawesome`. Browse available icons at
https://pictogrammers.com/library/mdi/. Use the `mdi.` prefix (e.g.,
`mdi.microscope`, `mdi.thermometer`, `mdi.chart-line`).

---

## Writing a Plugin

### Minimal Example (Tool Panel)

```python
# plugin.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from plugins.base import ToolPanelPlugin, PluginContext
from ui.theme import PALETTE, FONT

class MyToolPlugin(ToolPanelPlugin):

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.logger.info("MyTool activated!")

    def deactivate(self) -> None:
        self.log.info("MyTool deactivated.")

    def create_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        label = QLabel("Hello from my plugin!")
        label.setStyleSheet(f"color: {PALETTE['text']};")
        layout.addWidget(label)
        return panel

    def get_nav_label(self) -> str:
        return "My Tool"

    def get_nav_icon(self) -> str:
        return "mdi.wrench"
```

### Hardware Panel Example

```python
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from plugins.base import HardwarePanelPlugin, PluginContext
from ui.theme import PALETTE

class CryoStagePlugin(HardwarePanelPlugin):

    def activate(self, context: PluginContext) -> None:
        self._context = context
        self._driver = None

    def create_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self._status = QLabel("Disconnected")
        self._status.setStyleSheet(f"color: {PALETTE['textDim']};")
        layout.addWidget(self._status)

        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._connect)
        layout.addWidget(connect_btn)

        layout.addStretch()
        return panel

    def _connect(self):
        # Your hardware connection logic here
        self._status.setText("Connected")
        self._status.setStyleSheet(f"color: {PALETTE['pass']};")

    def get_nav_label(self) -> str:
        return "Cryo Stage"

    def get_nav_icon(self) -> str:
        return "mdi.snowflake"
```

### Hardware Driver (Non-UI)

```python
from plugins.base import HardwareDriverPlugin, PluginContext
from hardware.device_registry import DeviceDescriptor

class MyDriverPlugin(HardwareDriverPlugin):

    def activate(self, context: PluginContext) -> None:
        self._context = context

    def get_device_descriptor(self) -> DeviceDescriptor:
        return DeviceDescriptor(
            uid="com.example.my-device",
            display_name="My Custom Device",
            manufacturer="Example Corp",
            device_type="stage",
            connection_type="serial",
            driver_module="my_driver",
            serial_patterns=["MY_DEVICE"],
            default_baud=9600,
        )

    def create_driver(self, address: str, config: dict):
        from my_driver import MyDeviceDriver
        return MyDeviceDriver(address, **config)
```

---

## Plugin Lifecycle

1. **Discovery** — SanjINSIGHT scans `~/.microsanj/plugins/*/manifest.json`
2. **Validation** — Manifest is parsed; `api_version`, `min_app_version`, and
   `platforms` are checked
3. **License check** — The user's license tier must meet `min_license_tier`
4. **Dependency check** — Python packages verified via `importlib.metadata`
5. **Import** — Plugin module is loaded in an isolated namespace
   (`_sanjinsight_plugins.<id>.*`) to prevent collisions
6. **Instantiation** — Plugin class is constructed (no arguments)
7. **Activation** — `activate(context)` is called with a `PluginContext`
8. **UI wiring** — `create_panel()` / `create_tab()` is called; widgets are
   placed in the appropriate sidebar section or drawer
9. **Runtime** — Plugin receives `on_theme_changed()` callbacks when the user
   switches themes
10. **Shutdown** — `deactivate()` is called during application close

If any step fails, the error is logged and the plugin is skipped. A failing
plugin never crashes the host application.

---

## PluginContext

Every plugin receives a `PluginContext` at activation, providing sandboxed
access to application services:

| Attribute | Type | Description |
|-----------|------|-------------|
| `hw_service` | `HardwareService` | Hardware management singleton |
| `app_state` | module | `hardware.app_state` — device references, calibration |
| `signals` | `AppSignals` | Qt signal hub for cross-component communication |
| `event_bus` | `EventBus` | Publish/subscribe event system |
| `plugin_id` | `str` | This plugin's manifest ID |
| `config` | `dict` | Plugin-specific config from user preferences |
| `data_dir` | `Path` | Writable directory for plugin data (`plugins/<id>/data/`) |
| `logger` | `Logger` | Pre-configured logger (`plugins.<id>`) |

Access via `self.context` after activation, or `self.log` for the logger.

---

## Theming

Plugins automatically receive the application's QSS stylesheet, so standard
Qt widgets (buttons, labels, inputs) are themed without effort.

For custom styling, use `PALETTE` and `FONT` from `ui.theme`:

```python
from ui.theme import PALETTE, FONT

# In your widget code:
label.setStyleSheet(f"color: {PALETTE['text']}; font-size: {FONT['body']}pt;")
```

### Key PALETTE Colors

| Key | Usage |
|-----|-------|
| `bg` | Main background |
| `surface` | Card/panel background |
| `text` | Primary text |
| `textDim` | Secondary text |
| `textSub` | Tertiary/decorative text |
| `accent` | Interactive elements, links |
| `border` | Borders and dividers |
| `pass` | Success (green) |
| `fail` | Error (red) |

### Theme Change Notification

Override `on_theme_changed()` if you cache colors or pixmaps:

```python
def on_theme_changed(self) -> None:
    # Re-read PALETTE values
    self._status.setStyleSheet(f"color: {PALETTE['text']};")
```

For widgets that use `PALETTE[key]` in their stylesheet strings, the global
QSS cascade handles updates automatically — you only need to override this
for custom paint logic or cached values.

---

## Plugin Data and Preferences

### Data Directory

Each plugin gets a writable directory at `~/.microsanj/plugins/<id>/data/`:

```python
path = self.context.data_dir / "results.json"
path.write_text(json.dumps(data))
```

### Plugin Preferences

Plugin-specific preferences are stored under `plugins.<id>.config` in the
user's preference file:

```python
# Reading (via context.config at activation)
threshold = self.context.config.get("threshold", 0.5)

# Writing
from config import set_pref
set_pref(f"plugins.{self.context.plugin_id}.config.threshold", 0.75)
```

---

## Restrictions

Plugins **can**:
- Create any QWidget for their designated UI slot
- Import `PALETTE`, `FONT`, and `build_style` from `ui.theme`
- Use `app_state`, `signals`, and `event_bus` via the context
- Register device descriptors with the device registry
- Read and write to their own data directory
- Use any Python package available on the system

Plugins **cannot**:
- Modify existing tabs or panels
- Change sidebar structure, ordering, or icons of built-in items
- Override theme colors or fonts globally
- Intercept signals between core components
- Access other plugins' data directories
- Import `main_app` or modify the `MainWindow` directly

---

## Testing Your Plugin

### Local Testing

1. Place your plugin in `~/.microsanj/plugins/your-plugin/`
2. Start SanjINSIGHT — check the log for activation messages
3. Open **Settings > Plugins** to verify it appears and is enabled

### Unit Testing

```python
import unittest
from plugins.manifest import PluginManifest
from pathlib import Path

class TestMyPlugin(unittest.TestCase):
    def test_manifest_valid(self):
        m = PluginManifest.from_file(
            Path("path/to/your/manifest.json"))
        self.assertEqual(m.plugin_type, "tool_panel")

    def test_plugin_activates(self):
        from your_plugin import MyPluginClass
        from plugins.base import PluginContext
        ctx = PluginContext(plugin_id="test", data_dir=Path("/tmp/test"))
        p = MyPluginClass()
        p.activate(ctx)
        # Assert plugin state
```

---

## Directory Structure

```
~/.microsanj/plugins/
    my-plugin/
        manifest.json          # Required: plugin metadata
        plugin.py              # Entry point module
        helpers.py             # Additional modules (optional)
        data/                  # Auto-created writable data directory
            results.json
    another-plugin/
        manifest.json
        driver.py
        panel.py
```

---

## Version Compatibility

| Plugin API Version | SanjINSIGHT Version | Notes |
|--------------------|---------------------|-------|
| 1 | 0.44.0+ | Initial release |

When the plugin API evolves, the `api_version` field ensures backward
compatibility. Plugins targeting API v1 will continue to load on hosts
that support API v1, even if newer API versions are available.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Plugin not listed in Settings | Missing or invalid `manifest.json` | Check JSON syntax and required fields |
| "License denied" in log | Insufficient license tier | Upgrade to Developer or Site license |
| Plugin loads but panel is blank | `create_panel()` returns empty widget | Ensure layout and widgets are added |
| Theme colors wrong after switch | Cached PALETTE values | Override `on_theme_changed()` |
| Import errors | Missing Python dependency | Install packages listed in `dependencies.python` |
| Plugin breaks after app update | API incompatibility | Check `min_app_version` in manifest |

---

## Support

Plugin developers can reach Microsanj engineering support at
support@microsanj.com. Include your plugin's `manifest.json` and
the SanjINSIGHT log file (`~/.microsanj/logs/sanjinsight.log`).
