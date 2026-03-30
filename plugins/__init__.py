"""
plugins — SanjINSIGHT Plugin Architecture  (API v1)
====================================================

Public API for plugin authors and host integration.

Plugin authors subclass one of the base classes from :mod:`plugins.base`
and provide a ``manifest.json`` in their plugin directory.  The host
application uses :class:`PluginLoader` and :class:`PluginRegistry` to
discover, validate, and activate plugins at startup.

Quick reference
---------------
- :mod:`plugins.base`      — ``PluginBase`` and all six type-specific ABCs
- :mod:`plugins.manifest`  — ``PluginManifest`` dataclass + ``PLUGIN_API_VERSION``
- :mod:`plugins.loader`    — ``PluginLoader`` — discovery, import, activation
- :mod:`plugins.registry`  — ``PluginRegistry`` — in-memory store + lookup
- :mod:`plugins.sandbox`   — isolated import mechanism
- :mod:`plugins.errors`    — custom exceptions
"""
from __future__ import annotations

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
    PluginAPIVersionError,
    PluginDependencyError,
    PluginError,
    PluginLicenseError,
    PluginLoadError,
    PluginManifestError,
)
from plugins.loader import PluginLoader
from plugins.manifest import PLUGIN_API_VERSION, PluginManifest
from plugins.registry import PluginRegistry

__all__ = [
    # Core
    "PluginLoader",
    "PluginRegistry",
    "PluginManifest",
    "PluginContext",
    "PLUGIN_API_VERSION",
    # Base classes
    "PluginBase",
    "HardwarePanelPlugin",
    "AnalysisViewPlugin",
    "ToolPanelPlugin",
    "DrawerTabPlugin",
    "HardwareDriverPlugin",
    "AnalysisPipelinePlugin",
    # Errors
    "PluginError",
    "PluginManifestError",
    "PluginLoadError",
    "PluginLicenseError",
    "PluginDependencyError",
    "PluginAPIVersionError",
]
