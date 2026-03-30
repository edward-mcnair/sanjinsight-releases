"""
plugins/base.py

Abstract base classes for all SanjINSIGHT plugin types and the
PluginContext object that provides sandboxed access to app services.

Plugin API v1
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from PyQt5.QtWidgets import QWidget

if TYPE_CHECKING:
    from hardware.hardware_service import HardwareService
    from hardware.device_registry import DeviceDescriptor


# ── Plugin context ─────────────────────────────────────────────────────────

@dataclass
class PluginContext:
    """Sandboxed access to app-level services, provided to every plugin
    at activation time.

    Plugins should store this reference and use it throughout their
    lifetime rather than importing singletons directly.
    """
    # Core services
    hw_service: Any = None          # HardwareService singleton
    app_state: Any = None           # hardware.app_state module
    signals: Any = None             # ui.app_signals.signals (AppSignals)
    event_bus: Any = None           # events.event_bus (EventBus)

    # Plugin-specific
    plugin_id: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    data_dir: Path = field(default_factory=lambda: Path("."))
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("plugins"))


# ── Base class ─────────────────────────────────────────────────────────────

class PluginBase(ABC):
    """Common interface shared by all plugin types.

    Subclasses must implement :meth:`activate`.  All other lifecycle
    methods have safe default implementations.
    """

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._active: bool = False

    @property
    def context(self) -> PluginContext:
        """Access the :class:`PluginContext` set during activation."""
        if self._context is None:
            raise RuntimeError("Plugin has not been activated yet.")
        return self._context

    @property
    def log(self) -> logging.Logger:
        """Convenience accessor for the plugin's logger."""
        return self.context.logger if self._context else logging.getLogger("plugins")

    # ── Lifecycle ──────────────────────────────────────────────────────

    @abstractmethod
    def activate(self, context: PluginContext) -> None:
        """Called once after the plugin is loaded and license-verified.

        Store *context* and perform any one-time setup here.
        """

    def deactivate(self) -> None:
        """Called on app shutdown or when the plugin is explicitly unloaded.

        Override to release resources, close connections, etc.
        """
        self._active = False

    def on_theme_changed(self) -> None:
        """Called after ``set_theme()`` updates ``PALETTE`` and ``FONT``.

        Override to refresh any cached colors or stylesheets.
        Plugins that use ``PALETTE[...]`` in ``paintEvent`` or
        ``_apply_styles()`` typically do not need to override this —
        the QSS cascade handles it.  Override only for custom paint
        logic or cached pixmaps.
        """


# ── Tier 1: Hardware Panel ─────────────────────────────────────────────────

class HardwarePanelPlugin(PluginBase):
    """Plugin that contributes a control panel widget to the HARDWARE
    sidebar section.

    The host calls :meth:`create_panel` once during UI wiring and
    places the returned widget in the main stacked layout.
    """

    @abstractmethod
    def create_panel(self) -> QWidget:
        """Return the QWidget to be hosted in the HARDWARE sidebar section."""

    def get_nav_label(self) -> str:
        """Sidebar label.  Defaults to manifest *name*; override to customise."""
        return getattr(self, "_manifest_name", "Hardware Plugin")

    def get_nav_icon(self) -> str:
        """MDI icon name for the sidebar entry (e.g. ``'mdi.chip'``)."""
        return "mdi.puzzle"


# ── Tier 2: Analysis View ──────────────────────────────────────────────────

class AnalysisViewPlugin(PluginBase):
    """Plugin that contributes an analysis sub-tab widget."""

    @abstractmethod
    def create_panel(self) -> QWidget:
        """Return the QWidget for the ANALYZE sidebar section."""

    def get_nav_label(self) -> str:
        return getattr(self, "_manifest_name", "Analysis Plugin")

    def get_nav_icon(self) -> str:
        return "mdi.chart-line"


# ── Tier 3: Tool Panel ────────────────────────────────────────────────────

class ToolPanelPlugin(PluginBase):
    """Plugin that contributes a panel to the TOOLS sidebar section."""

    @abstractmethod
    def create_panel(self) -> QWidget:
        """Return the QWidget for the TOOLS sidebar section."""

    def get_nav_label(self) -> str:
        return getattr(self, "_manifest_name", "Tool Plugin")

    def get_nav_icon(self) -> str:
        return "mdi.wrench"


# ── Tier 4: Bottom Drawer Tab ─────────────────────────────────────────────

class DrawerTabPlugin(PluginBase):
    """Plugin that adds a tab to the bottom drawer ``QTabWidget``."""

    @abstractmethod
    def create_tab(self) -> QWidget:
        """Return the QWidget to be added as a drawer tab."""

    def get_tab_label(self) -> str:
        return getattr(self, "_manifest_name", "Plugin")

    def get_tab_icon(self) -> str:
        return "mdi.text-box-outline"


# ── Non-UI: Hardware Driver ────────────────────────────────────────────────

class HardwareDriverPlugin(PluginBase):
    """Non-UI plugin that registers a device driver with the
    :mod:`hardware.device_registry`.

    The host calls :meth:`get_device_descriptor` during activation to
    register the device, and :meth:`create_driver` when the user
    connects to it.
    """

    @abstractmethod
    def get_device_descriptor(self) -> "DeviceDescriptor":
        """Return a :class:`DeviceDescriptor` for the global registry."""

    @abstractmethod
    def create_driver(self, address: str, config: dict) -> Any:
        """Factory: return a connected driver instance for *address*."""


# ── Non-UI: Analysis Pipeline ──────────────────────────────────────────────

class AnalysisPipelinePlugin(PluginBase):
    """Non-UI plugin that registers a data-processing pipeline."""

    @abstractmethod
    def get_pipeline_name(self) -> str:
        """Human-readable name for this pipeline (shown in UI selectors)."""

    @abstractmethod
    def process(self, data: Any, **kwargs: Any) -> Any:
        """Process acquisition data.

        *data* is typically a :class:`numpy.ndarray` or an
        ``AcquisitionResult`` dict.  Return the processed result in the
        same format, or as a dict with ``{"result": ..., "metadata": ...}``.
        """
