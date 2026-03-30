"""
plugins/registry.py

Central registry of all loaded and activated plugins.
Provides lookup by ID, type, and enumeration of manifests.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from plugins.base import PluginBase
from plugins.manifest import PluginManifest

log = logging.getLogger(__name__)


class PluginRegistry:
    """In-memory store for activated plugin instances and their manifests."""

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginBase] = {}
        self._manifests: Dict[str, PluginManifest] = {}
        self._by_type: Dict[str, List[str]] = defaultdict(list)

    # ── Registration ───────────────────────────────────────────────────

    def register(
        self,
        plugin_id: str,
        instance: PluginBase,
        manifest: PluginManifest,
    ) -> None:
        """Add an activated plugin to the registry."""
        if plugin_id in self._plugins:
            log.warning("Plugin '%s' already registered — replacing.", plugin_id)
        self._plugins[plugin_id] = instance
        self._manifests[plugin_id] = manifest
        self._by_type[manifest.plugin_type].append(plugin_id)
        log.info(
            "Registered plugin '%s' v%s (%s)",
            manifest.name, manifest.version, manifest.plugin_type,
        )

    def unregister(self, plugin_id: str) -> None:
        """Remove a plugin from the registry (does *not* call deactivate)."""
        manifest = self._manifests.pop(plugin_id, None)
        self._plugins.pop(plugin_id, None)
        if manifest and plugin_id in self._by_type.get(manifest.plugin_type, []):
            self._by_type[manifest.plugin_type].remove(plugin_id)

    # ── Lookup ─────────────────────────────────────────────────────────

    def get(self, plugin_id: str) -> Optional[PluginBase]:
        """Return the plugin instance for *plugin_id*, or ``None``."""
        return self._plugins.get(plugin_id)

    def get_manifest(self, plugin_id: str) -> Optional[PluginManifest]:
        """Return the manifest for *plugin_id*, or ``None``."""
        return self._manifests.get(plugin_id)

    def get_by_type(self, plugin_type: str) -> List[PluginBase]:
        """Return all plugin instances of the given *plugin_type*."""
        return [
            self._plugins[pid]
            for pid in self._by_type.get(plugin_type, [])
            if pid in self._plugins
        ]

    def get_all_manifests(self) -> List[PluginManifest]:
        """Return manifests for every registered plugin."""
        return list(self._manifests.values())

    @property
    def plugin_ids(self) -> List[str]:
        """All registered plugin IDs."""
        return list(self._plugins.keys())

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    # ── Lifecycle ──────────────────────────────────────────────────────

    def deactivate_all(self) -> None:
        """Call ``deactivate()`` on every registered plugin, then clear."""
        for pid, plugin in list(self._plugins.items()):
            try:
                plugin.deactivate()
            except Exception:
                log.exception("Error deactivating plugin '%s'", pid)
        self._plugins.clear()
        self._manifests.clear()
        self._by_type.clear()
        log.info("All plugins deactivated and registry cleared.")

    def notify_theme_changed(self) -> None:
        """Broadcast theme change to all registered plugins."""
        for pid, plugin in self._plugins.items():
            try:
                plugin.on_theme_changed()
            except Exception:
                log.debug("Theme callback failed for plugin '%s'", pid,
                          exc_info=True)
