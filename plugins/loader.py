"""
plugins/loader.py

Plugin discovery, validation, license checking, and loading.

Usage from MainWindow._build_ui()::

    from plugins.loader import PluginLoader
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()
    loader = PluginLoader(registry)
    loaded = loader.discover_and_load()
    # loaded is a list of PluginManifest for successfully activated plugins
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from plugins.base import (
    AnalysisPipelinePlugin,
    AnalysisViewPlugin,
    DrawerTabPlugin,
    HardwareDriverPlugin,
    HardwarePanelPlugin,
    PluginBase,
    PluginContext,
    ToolPanelPlugin,
)
from plugins.errors import (
    PluginDependencyError,
    PluginLicenseError,
    PluginLoadError,
    PluginManifestError,
)
from plugins.manifest import PluginManifest
from plugins.registry import PluginRegistry
from plugins.sandbox import import_plugin_class, unload_plugin

log = logging.getLogger(__name__)

# ── License tier ordering ──────────────────────────────────────────────────

_TIER_ORDER: Dict[str, int] = {
    "unlicensed": 0,
    "standard": 1,
    "developer": 2,
    "site": 3,
}

# Plugin-type → expected base class (for validation at load time).
_TYPE_BASE_MAP = {
    "hardware_panel": HardwarePanelPlugin,
    "analysis_view": AnalysisViewPlugin,
    "tool_panel": ToolPanelPlugin,
    "drawer_tab": DrawerTabPlugin,
    "hardware_driver": HardwareDriverPlugin,
    "analysis_pipeline": AnalysisPipelinePlugin,
}


class PluginLoader:
    """Discovers, validates, and activates plugins from the user's
    ``~/.microsanj/plugins/`` directory.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        *,
        hw_service: Any = None,
        app_state: Any = None,
        signals: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._registry = registry
        self._hw_service = hw_service
        self._app_state = app_state
        self._signals = signals
        self._event_bus = event_bus
        self._plugins_dir = self._resolve_plugins_dir()
        self._errors: List[str] = []

    # ── Directory resolution ───────────────────────────────────────────

    @staticmethod
    def _resolve_plugins_dir() -> Path:
        """Return the user-writable plugins directory, creating it if needed."""
        try:
            base = Path.home() / ".microsanj" / "plugins"
        except Exception:
            import os
            fallback = (
                os.environ.get("LOCALAPPDATA")
                or os.environ.get("APPDATA")
                or os.environ.get("TEMP")
                or "."
            )
            base = Path(fallback) / "Microsanj" / "plugins"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    @property
    def errors(self) -> List[str]:
        """Human-readable error messages from the last load cycle."""
        return list(self._errors)

    def discover_and_load(self) -> List[PluginManifest]:
        """Scan the plugins directory, load and activate each valid plugin.

        Returns the list of manifests for successfully activated plugins.
        Errors are accumulated in :attr:`errors` and logged, but never
        propagated — a bad plugin must not crash the host.
        """
        self._errors.clear()
        loaded: List[PluginManifest] = []

        if not self._plugins_dir.is_dir():
            log.debug("No plugins directory at %s", self._plugins_dir)
            return loaded

        candidates = sorted(self._plugins_dir.iterdir())
        log.info(
            "Scanning %d plugin candidate(s) in %s",
            len(candidates), self._plugins_dir,
        )

        for plugin_dir in candidates:
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.is_file():
                continue

            try:
                manifest = self._load_one(manifest_path)
                if manifest is not None:
                    loaded.append(manifest)
            except Exception as exc:
                msg = f"Plugin in '{plugin_dir.name}': {exc}"
                self._errors.append(msg)
                log.warning(msg, exc_info=True)

        log.info(
            "Plugin loading complete: %d activated, %d error(s)",
            len(loaded), len(self._errors),
        )
        return loaded

    # ── Internal pipeline ──────────────────────────────────────────────

    def _load_one(self, manifest_path: Path) -> Optional[PluginManifest]:
        """Parse, validate, license-check, import, and activate one plugin."""
        # 1. Parse manifest
        manifest = PluginManifest.from_file(manifest_path)
        log.debug("Parsed manifest for '%s' v%s", manifest.id, manifest.version)

        # 2. Platform check
        if sys.platform not in manifest.platforms:
            log.info(
                "Skipping plugin '%s': platform '%s' not in %s",
                manifest.id, sys.platform, manifest.platforms,
            )
            return None

        # 3. App version check
        if not self._check_app_version(manifest):
            return None

        # 4. License tier check
        if not self._check_license(manifest):
            return None

        # 5. Check enabled in preferences
        if not self._is_enabled(manifest.id):
            log.info("Plugin '%s' is disabled in preferences.", manifest.id)
            return None

        # 6. Python dependency check
        self._check_python_deps(manifest)

        # 7. Import plugin class
        cls, _module = import_plugin_class(
            manifest.id, manifest.path, manifest.entry_point)

        # 8. Validate base class
        expected_base = _TYPE_BASE_MAP.get(manifest.plugin_type)
        if expected_base and not issubclass(cls, expected_base):
            raise PluginLoadError(
                manifest.id,
                f"Class '{cls.__name__}' must subclass "
                f"'{expected_base.__name__}' for type '{manifest.plugin_type}'")

        # 9. Instantiate
        try:
            instance: PluginBase = cls()
        except Exception as exc:
            raise PluginLoadError(
                manifest.id,
                f"Instantiation failed: {exc}") from exc

        # 10. Build context and activate
        context = self._build_context(manifest)
        try:
            instance.activate(context)
            instance._context = context
            instance._active = True
        except Exception as exc:
            raise PluginLoadError(
                manifest.id,
                f"Activation failed: {exc}") from exc

        # Store sidebar/drawer metadata from manifest on the instance for
        # easy access during UI wiring.
        instance._manifest_name = manifest.name

        # 11. Register
        self._registry.register(manifest.id, instance, manifest)

        # 12. Emit event
        self._emit_event("plugin.activated", manifest.id, manifest.name)

        return manifest

    # ── Checks ─────────────────────────────────────────────────────────

    def _check_license(self, manifest: PluginManifest) -> bool:
        """Return True if the current license tier meets the plugin's minimum."""
        current_tier = self._get_current_tier()
        current_level = _TIER_ORDER.get(current_tier, 0)
        required_level = _TIER_ORDER.get(manifest.min_license_tier, 99)

        if current_level < required_level:
            msg = (
                f"Plugin '{manifest.id}' requires '{manifest.min_license_tier}' "
                f"license (current: '{current_tier}')"
            )
            self._errors.append(msg)
            log.info(msg)
            self._emit_event("plugin.license_denied", manifest.id, msg)
            return False
        return True

    def _get_current_tier(self) -> str:
        """Read the license tier from app_state, with safe fallbacks."""
        if self._app_state is None:
            return "developer"  # Assume developer during testing/development

        try:
            info = getattr(self._app_state, "license_info", None)
            if info is None:
                return "unlicensed"
            tier = getattr(info, "tier", None)
            if tier is None:
                return "unlicensed"
            # tier might be an enum — coerce to string
            return str(tier.value if hasattr(tier, "value") else tier).lower()
        except Exception:
            return "unlicensed"

    def _check_app_version(self, manifest: PluginManifest) -> bool:
        """Return True if the host app version meets the plugin's minimum."""
        try:
            from version import VERSION_TUPLE
            min_parts = [int(x) for x in manifest.min_app_version.split(".")]
            # Pad to 3 elements
            while len(min_parts) < 3:
                min_parts.append(0)
            if VERSION_TUPLE < tuple(min_parts):
                msg = (
                    f"Plugin '{manifest.id}' requires app v{manifest.min_app_version}, "
                    f"running v{'.'.join(str(x) for x in VERSION_TUPLE)}"
                )
                self._errors.append(msg)
                log.info(msg)
                return False
        except ImportError:
            log.debug("Cannot check app version — version module not found.")
        return True

    def _check_python_deps(self, manifest: PluginManifest) -> None:
        """Check that required Python packages are importable."""
        import importlib.metadata as ilm

        for dep_spec in manifest.python_deps:
            # dep_spec is like "pyserial>=3.5" — extract bare name
            name = dep_spec.split(">")[0].split("<")[0].split("=")[0].split("!")[0].strip()
            try:
                ilm.distribution(name)
            except ilm.PackageNotFoundError:
                raise PluginDependencyError(
                    manifest.id,
                    f"Python dependency not installed: {dep_spec}")

    def _is_enabled(self, plugin_id: str) -> bool:
        """Check the user preference for this plugin (default: enabled)."""
        try:
            from config import get_pref
            return get_pref(f"plugins.{plugin_id}.enabled", True)
        except ImportError:
            return True

    # ── Context building ───────────────────────────────────────────────

    def _build_context(self, manifest: PluginManifest) -> PluginContext:
        """Construct a :class:`PluginContext` for a specific plugin."""
        data_dir = manifest.path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Plugin-specific config from preferences
        plugin_config: Dict[str, Any] = {}
        try:
            from config import get_pref
            plugin_config = get_pref(f"plugins.{manifest.id}.config", {})
        except ImportError:
            pass

        return PluginContext(
            hw_service=self._hw_service,
            app_state=self._app_state,
            signals=self._signals,
            event_bus=self._event_bus,
            plugin_id=manifest.id,
            config=plugin_config,
            data_dir=data_dir,
            logger=logging.getLogger(f"plugins.{manifest.id}"),
        )

    # ── Events ─────────────────────────────────────────────────────────

    def _emit_event(self, event_type: str, plugin_id: str, detail: str = "") -> None:
        """Publish a plugin lifecycle event to the event bus (if available)."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(event_type, plugin_id=plugin_id, detail=detail)
        except Exception:
            log.debug("Failed to emit plugin event '%s'", event_type, exc_info=True)
