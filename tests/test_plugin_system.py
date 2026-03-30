"""
tests/test_plugin_system.py

Tests for the SanjINSIGHT plugin architecture:
  - Manifest parsing and validation
  - Sandbox import isolation
  - Plugin registry operations
  - Plugin loader discovery, license checks, and lifecycle
  - Theme listener integration
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ══════════════════════════════════════════════════════════════════════════════
#  Manifest Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginManifest(unittest.TestCase):
    """Test manifest.json parsing and validation."""

    def _write_manifest(self, tmpdir: str, data: dict) -> Path:
        p = Path(tmpdir) / "manifest.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def _valid_data(self, **overrides) -> dict:
        base = {
            "id": "com.test.sample",
            "name": "Test Plugin",
            "version": "1.0.0",
            "api_version": 1,
            "plugin_type": "tool_panel",
            "entry_point": "plugin:TestPlugin",
            "min_license_tier": "developer",
            "sidebar": {"section": "TOOLS", "label": "Test", "icon": "mdi.test"},
        }
        base.update(overrides)
        return base

    def test_valid_manifest_parses(self):
        from plugins.manifest import PluginManifest
        with tempfile.TemporaryDirectory() as td:
            p = self._write_manifest(td, self._valid_data())
            m = PluginManifest.from_file(p)
            self.assertEqual(m.id, "com.test.sample")
            self.assertEqual(m.name, "Test Plugin")
            self.assertEqual(m.plugin_type, "tool_panel")
            self.assertIsNotNone(m.sidebar)
            self.assertEqual(m.sidebar.label, "Test")

    def test_missing_required_field_raises(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginManifestError
        with tempfile.TemporaryDirectory() as td:
            data = self._valid_data()
            del data["id"]
            p = self._write_manifest(td, data)
            with self.assertRaises(PluginManifestError):
                PluginManifest.from_file(p)

    def test_invalid_plugin_type_raises(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginManifestError
        with tempfile.TemporaryDirectory() as td:
            p = self._write_manifest(td, self._valid_data(plugin_type="invalid"))
            with self.assertRaises(PluginManifestError):
                PluginManifest.from_file(p)

    def test_bad_entry_point_format_raises(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginManifestError
        with tempfile.TemporaryDirectory() as td:
            p = self._write_manifest(td, self._valid_data(entry_point="no_colon"))
            with self.assertRaises(PluginManifestError):
                PluginManifest.from_file(p)

    def test_api_version_too_high_raises(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginAPIVersionError
        with tempfile.TemporaryDirectory() as td:
            p = self._write_manifest(td, self._valid_data(api_version=999))
            with self.assertRaises(PluginAPIVersionError):
                PluginManifest.from_file(p)

    def test_sidebar_required_for_panel_types(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginManifestError
        with tempfile.TemporaryDirectory() as td:
            data = self._valid_data()
            del data["sidebar"]
            p = self._write_manifest(td, data)
            with self.assertRaises(PluginManifestError):
                PluginManifest.from_file(p)

    def test_drawer_tab_type_no_sidebar_ok(self):
        from plugins.manifest import PluginManifest
        with tempfile.TemporaryDirectory() as td:
            data = self._valid_data(plugin_type="drawer_tab")
            del data["sidebar"]
            data["drawer_tab"] = {"label": "Log", "icon": "mdi.text"}
            p = self._write_manifest(td, data)
            m = PluginManifest.from_file(p)
            self.assertEqual(m.plugin_type, "drawer_tab")

    def test_missing_file_raises(self):
        from plugins.manifest import PluginManifest
        from plugins.errors import PluginManifestError
        with self.assertRaises(PluginManifestError):
            PluginManifest.from_file(Path("/nonexistent/manifest.json"))

    def test_dependencies_parsed(self):
        from plugins.manifest import PluginManifest
        with tempfile.TemporaryDirectory() as td:
            data = self._valid_data()
            data["dependencies"] = {
                "python": ["numpy>=1.20", "scipy"],
                "plugins": ["com.other.plugin"],
            }
            p = self._write_manifest(td, data)
            m = PluginManifest.from_file(p)
            self.assertEqual(m.python_deps, ["numpy>=1.20", "scipy"])
            self.assertEqual(m.plugin_deps, ["com.other.plugin"])

    def test_platforms_default(self):
        from plugins.manifest import PluginManifest
        with tempfile.TemporaryDirectory() as td:
            p = self._write_manifest(td, self._valid_data())
            m = PluginManifest.from_file(p)
            self.assertIn("win32", m.platforms)
            self.assertIn("darwin", m.platforms)
            self.assertIn("linux", m.platforms)


# ══════════════════════════════════════════════════════════════════════════════
#  Sandbox Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSandbox(unittest.TestCase):
    """Test isolated plugin import via sandbox.py."""

    def test_import_plugin_class(self):
        from plugins.sandbox import import_plugin_class
        with tempfile.TemporaryDirectory() as td:
            # Write a minimal plugin module
            Path(td, "myplugin.py").write_text(textwrap.dedent("""\
                class MyClass:
                    name = "hello"
            """))
            cls, mod = import_plugin_class(
                "com.test.sandbox", Path(td), "myplugin:MyClass")
            self.assertEqual(cls.name, "hello")
            self.assertIn("_sanjinsight_plugins", mod.__name__)

    def test_missing_module_raises(self):
        from plugins.sandbox import import_plugin_class
        from plugins.errors import PluginLoadError
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(PluginLoadError):
                import_plugin_class(
                    "com.test.missing", Path(td), "nonexistent:Cls")

    def test_missing_class_raises(self):
        from plugins.sandbox import import_plugin_class
        from plugins.errors import PluginLoadError
        with tempfile.TemporaryDirectory() as td:
            Path(td, "mod.py").write_text("class Foo: pass\n")
            with self.assertRaises(PluginLoadError):
                import_plugin_class(
                    "com.test.badclass", Path(td), "mod:Bar")

    def test_unload_removes_modules(self):
        from plugins.sandbox import import_plugin_class, unload_plugin
        with tempfile.TemporaryDirectory() as td:
            Path(td, "tmp.py").write_text("X = 1\n")
            import_plugin_class("com.test.unload", Path(td), "tmp:X")
            # Verify module exists
            matches = [k for k in sys.modules
                       if "com_test_unload" in k]
            self.assertTrue(len(matches) > 0)
            # Unload
            unload_plugin("com.test.unload")
            matches = [k for k in sys.modules
                       if "com_test_unload" in k]
            self.assertEqual(len(matches), 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Registry Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginRegistry(unittest.TestCase):
    """Test PluginRegistry operations."""

    def _make_manifest(self, pid="com.test.a", ptype="tool_panel"):
        from plugins.manifest import PluginManifest
        m = PluginManifest()
        m.id = pid
        m.name = pid
        m.plugin_type = ptype
        return m

    def test_register_and_get(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        plugin = MagicMock()
        manifest = self._make_manifest()
        r.register("com.test.a", plugin, manifest)
        self.assertIn("com.test.a", r)
        self.assertIs(r.get("com.test.a"), plugin)

    def test_get_by_type(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        p1, p2, p3 = MagicMock(), MagicMock(), MagicMock()
        r.register("a", p1, self._make_manifest("a", "tool_panel"))
        r.register("b", p2, self._make_manifest("b", "hardware_panel"))
        r.register("c", p3, self._make_manifest("c", "tool_panel"))
        tools = r.get_by_type("tool_panel")
        self.assertEqual(len(tools), 2)
        self.assertIn(p1, tools)
        self.assertIn(p3, tools)

    def test_deactivate_all(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        p1, p2 = MagicMock(), MagicMock()
        r.register("a", p1, self._make_manifest("a"))
        r.register("b", p2, self._make_manifest("b"))
        r.deactivate_all()
        p1.deactivate.assert_called_once()
        p2.deactivate.assert_called_once()
        self.assertEqual(len(r), 0)

    def test_notify_theme_changed(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        p = MagicMock()
        r.register("a", p, self._make_manifest())
        r.notify_theme_changed()
        p.on_theme_changed.assert_called_once()

    def test_unregister(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        r.register("x", MagicMock(), self._make_manifest("x"))
        self.assertIn("x", r)
        r.unregister("x")
        self.assertNotIn("x", r)

    def test_get_all_manifests(self):
        from plugins.registry import PluginRegistry
        r = PluginRegistry()
        m1 = self._make_manifest("a")
        m2 = self._make_manifest("b")
        r.register("a", MagicMock(), m1)
        r.register("b", MagicMock(), m2)
        all_m = r.get_all_manifests()
        self.assertEqual(len(all_m), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  Loader Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginLoader(unittest.TestCase):
    """Test PluginLoader discovery and loading."""

    def _make_plugin_dir(self, base: str, plugin_id: str, plugin_code: str,
                         manifest_overrides: dict = None) -> Path:
        """Create a plugin directory with manifest + plugin.py."""
        pdir = Path(base) / plugin_id.replace(".", "-")
        pdir.mkdir(parents=True)

        manifest = {
            "id": plugin_id,
            "name": f"Test {plugin_id}",
            "version": "1.0.0",
            "api_version": 1,
            "plugin_type": "drawer_tab",
            "entry_point": "plugin:TestDrawerPlugin",
            "min_license_tier": "developer",
            "drawer_tab": {"label": "Test", "icon": "mdi.test"},
        }
        if manifest_overrides:
            manifest.update(manifest_overrides)

        (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pdir / "plugin.py").write_text(plugin_code, encoding="utf-8")
        return pdir

    def _minimal_plugin_code(self) -> str:
        return textwrap.dedent("""\
            from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
            from plugins.base import DrawerTabPlugin, PluginContext

            class TestDrawerPlugin(DrawerTabPlugin):
                def activate(self, context):
                    self._context = context
                def create_tab(self):
                    w = QWidget()
                    QVBoxLayout(w).addWidget(QLabel("Test"))
                    return w
                def get_tab_label(self):
                    return "Test Tab"
                def get_tab_icon(self):
                    return "mdi.test"
        """)

    def test_discover_and_load_empty_dir(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        with tempfile.TemporaryDirectory() as td:
            loader._plugins_dir = Path(td)
            loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 0)

    def test_discover_and_load_valid_plugin(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        with tempfile.TemporaryDirectory() as td:
            self._make_plugin_dir(td, "com.test.valid", self._minimal_plugin_code())
            loader._plugins_dir = Path(td)
            loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, "com.test.valid")
            self.assertIn("com.test.valid", registry)

    def test_license_tier_blocks_loading(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()

        # Mock app_state with standard tier (below developer)
        mock_state = MagicMock()
        mock_state.license_info.tier.value = "standard"

        loader = PluginLoader(registry, app_state=mock_state)
        with tempfile.TemporaryDirectory() as td:
            self._make_plugin_dir(
                td, "com.test.licensed", self._minimal_plugin_code(),
                manifest_overrides={"min_license_tier": "site"})
            loader._plugins_dir = Path(td)
            loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 0)
            self.assertNotIn("com.test.licensed", registry)

    def test_bad_manifest_does_not_crash(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        with tempfile.TemporaryDirectory() as td:
            # Create a plugin dir with invalid JSON
            bad_dir = Path(td) / "bad-plugin"
            bad_dir.mkdir()
            (bad_dir / "manifest.json").write_text("{invalid json", encoding="utf-8")
            loader._plugins_dir = Path(td)
            loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 0)
            self.assertTrue(len(loader.errors) > 0)

    def test_platform_filter(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        with tempfile.TemporaryDirectory() as td:
            # Plugin only for a platform that isn't the current one
            fake_platform = "win32" if sys.platform != "win32" else "linux"
            self._make_plugin_dir(
                td, "com.test.wrongos", self._minimal_plugin_code(),
                manifest_overrides={"platforms": [fake_platform]})
            loader._plugins_dir = Path(td)
            loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 0)

    def test_disabled_plugin_skipped(self):
        from plugins.loader import PluginLoader
        from plugins.registry import PluginRegistry
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        with tempfile.TemporaryDirectory() as td:
            self._make_plugin_dir(td, "com.test.disabled", self._minimal_plugin_code())
            loader._plugins_dir = Path(td)
            # Mock config to disable
            with patch("plugins.loader.PluginLoader._is_enabled", return_value=False):
                loaded = loader.discover_and_load()
            self.assertEqual(len(loaded), 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Theme Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestThemeListeners(unittest.TestCase):
    """Test that theme listeners are called on set_theme()."""

    def test_listener_called_on_theme_change(self):
        from ui.theme import register_theme_listener, set_theme, _theme_listeners
        called = []

        def _on_change():
            called.append(True)

        register_theme_listener(_on_change)
        try:
            set_theme("light")
            self.assertTrue(len(called) > 0)
        finally:
            _theme_listeners.remove(_on_change)
            set_theme("dark")


# ══════════════════════════════════════════════════════════════════════════════
#  Device Registry External Registration
# ══════════════════════════════════════════════════════════════════════════════

class TestDeviceRegistryExternal(unittest.TestCase):
    """Test register_external() for plugin-provided devices."""

    def test_register_and_find(self):
        from hardware.device_registry import (
            DeviceDescriptor, DEVICE_REGISTRY, register_external,
        )
        desc = DeviceDescriptor(
            uid="test.plugin.device",
            display_name="Test Device",
            manufacturer="Test Corp",
            device_type="tec",
            connection_type="serial",
            driver_module="test.driver",
        )
        try:
            register_external(desc)
            self.assertIn("test.plugin.device", DEVICE_REGISTRY)
        finally:
            DEVICE_REGISTRY.pop("test.plugin.device", None)

    def test_duplicate_uid_raises(self):
        from hardware.device_registry import (
            DeviceDescriptor, DEVICE_REGISTRY, register_external,
        )
        desc = DeviceDescriptor(
            uid="test.plugin.dup",
            display_name="Dup Device",
            manufacturer="Test Corp",
            device_type="tec",
            connection_type="serial",
            driver_module="test.driver",
        )
        try:
            register_external(desc)
            with self.assertRaises(ValueError):
                register_external(desc)
        finally:
            DEVICE_REGISTRY.pop("test.plugin.dup", None)


if __name__ == "__main__":
    unittest.main()
