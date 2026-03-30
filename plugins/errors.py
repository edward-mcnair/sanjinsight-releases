"""
plugins/errors.py

Custom exceptions for the SanjINSIGHT plugin system.
"""
from __future__ import annotations


class PluginError(Exception):
    """Base exception for all plugin-related errors."""

    def __init__(self, plugin_id: str = "", message: str = ""):
        self.plugin_id = plugin_id
        super().__init__(f"[{plugin_id}] {message}" if plugin_id else message)


class PluginManifestError(PluginError):
    """Raised when a manifest.json is missing, malformed, or invalid."""


class PluginLoadError(PluginError):
    """Raised when a plugin module cannot be imported or instantiated."""


class PluginLicenseError(PluginError):
    """Raised when the current license tier is insufficient for a plugin."""


class PluginDependencyError(PluginError):
    """Raised when a plugin's Python or plugin-to-plugin dependency is unmet."""


class PluginAPIVersionError(PluginError):
    """Raised when a plugin requires a newer plugin API version than the host."""
