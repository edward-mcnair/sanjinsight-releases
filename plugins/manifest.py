"""
plugins/manifest.py

Dataclass for parsed plugin manifest.json files, with validation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from plugins.errors import PluginManifestError

log = logging.getLogger(__name__)

# Current plugin API version supported by the host.  Plugins declare the
# api_version they target; the loader rejects plugins whose api_version
# exceeds this value.
PLUGIN_API_VERSION = 1

# Valid plugin_type values.
VALID_PLUGIN_TYPES = frozenset({
    "hardware_panel",
    "analysis_view",
    "tool_panel",
    "drawer_tab",
    "hardware_driver",
    "analysis_pipeline",
})

# Plugin types that require a sidebar block in the manifest.
_SIDEBAR_REQUIRED_TYPES = frozenset({
    "hardware_panel",
    "analysis_view",
    "tool_panel",
})


# ── Sidebar / Drawer tab metadata ─────────────────────────────────────────

@dataclass
class SidebarMeta:
    """Sidebar entry metadata from manifest ``sidebar`` block."""
    section: str = "HARDWARE"
    label: str = ""
    icon: str = "mdi.puzzle"


@dataclass
class DrawerTabMeta:
    """Bottom-drawer tab metadata from manifest ``drawer_tab`` block."""
    label: str = ""
    icon: str = "mdi.text-box-outline"


# ── Main manifest dataclass ───────────────────────────────────────────────

@dataclass
class PluginManifest:
    """Parsed and validated representation of a plugin's manifest.json."""

    # Identity
    id: str = ""
    name: str = ""
    version: str = "0.0.0"
    api_version: int = 1
    author: str = ""
    description: str = ""

    # Classification
    plugin_type: str = ""

    # Entry point — "module_name:ClassName"
    entry_point: str = ""

    # Licensing
    min_license_tier: str = "developer"

    # UI metadata (optional depending on type)
    sidebar: Optional[SidebarMeta] = None
    drawer_tab: Optional[DrawerTabMeta] = None

    # Dependencies
    python_deps: List[str] = field(default_factory=list)
    plugin_deps: List[str] = field(default_factory=list)

    # Compatibility
    min_app_version: str = "1.0.0"
    platforms: List[str] = field(default_factory=lambda: ["win32", "darwin", "linux"])

    # Resolved path (set by loader, not from JSON)
    path: Path = field(default_factory=lambda: Path("."))

    # ── Parsing ────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, manifest_path: Path) -> "PluginManifest":
        """Parse *manifest_path* and return a validated :class:`PluginManifest`.

        Raises :class:`PluginManifestError` on any validation failure.
        """
        if not manifest_path.is_file():
            raise PluginManifestError(
                "", f"Manifest not found: {manifest_path}")

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise PluginManifestError(
                "", f"Cannot read manifest {manifest_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise PluginManifestError(
                "", f"Manifest must be a JSON object: {manifest_path}")

        m = cls()
        m.path = manifest_path.parent

        # Required scalar fields
        for key in ("id", "name", "version", "plugin_type", "entry_point"):
            val = raw.get(key)
            if not val or not isinstance(val, str):
                raise PluginManifestError(
                    raw.get("id", "?"),
                    f"Missing or invalid required field '{key}'")
            setattr(m, key, val.strip())

        # Optional scalar fields
        m.api_version = int(raw.get("api_version", 1))
        m.author = raw.get("author", "")
        m.description = raw.get("description", "")
        m.min_license_tier = raw.get("min_license_tier", "developer")
        m.min_app_version = raw.get("min_app_version", "1.0.0")
        m.platforms = raw.get("platforms",
                              ["win32", "darwin", "linux"])

        # Sidebar block
        sb = raw.get("sidebar")
        if isinstance(sb, dict):
            m.sidebar = SidebarMeta(
                section=sb.get("section", "HARDWARE"),
                label=sb.get("label", m.name),
                icon=sb.get("icon", "mdi.puzzle"),
            )

        # Drawer tab block
        dt = raw.get("drawer_tab")
        if isinstance(dt, dict):
            m.drawer_tab = DrawerTabMeta(
                label=dt.get("label", m.name),
                icon=dt.get("icon", "mdi.text-box-outline"),
            )

        # Dependencies
        deps = raw.get("dependencies", {})
        if isinstance(deps, dict):
            m.python_deps = deps.get("python", [])
            m.plugin_deps = deps.get("plugins", [])

        m.validate()
        return m

    # ── Validation ─────────────────────────────────────────────────────

    def validate(self) -> None:
        """Run all validation checks.  Raises :class:`PluginManifestError`."""
        if self.plugin_type not in VALID_PLUGIN_TYPES:
            raise PluginManifestError(
                self.id,
                f"Unknown plugin_type '{self.plugin_type}'. "
                f"Valid: {sorted(VALID_PLUGIN_TYPES)}")

        if ":" not in self.entry_point:
            raise PluginManifestError(
                self.id,
                "entry_point must be 'module:ClassName' format, "
                f"got '{self.entry_point}'")

        if self.api_version > PLUGIN_API_VERSION:
            from plugins.errors import PluginAPIVersionError
            raise PluginAPIVersionError(
                self.id,
                f"Requires plugin API v{self.api_version}, "
                f"host supports v{PLUGIN_API_VERSION}")

        if (self.plugin_type in _SIDEBAR_REQUIRED_TYPES
                and self.sidebar is None):
            raise PluginManifestError(
                self.id,
                f"plugin_type '{self.plugin_type}' requires a 'sidebar' block")
