"""
plugins/sandbox.py

Isolated import mechanism for plugins.

Each plugin is imported under a synthetic namespace
``_sanjinsight_plugins.<plugin_id>`` so that plugins cannot
accidentally shadow each other's modules or collide with the
host application's internal modules.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Tuple, Type

from plugins.errors import PluginLoadError

log = logging.getLogger(__name__)

_NAMESPACE_ROOT = "_sanjinsight_plugins"


def _ensure_namespace_root() -> None:
    """Create the synthetic top-level namespace package if absent."""
    if _NAMESPACE_ROOT not in sys.modules:
        ns = ModuleType(_NAMESPACE_ROOT)
        ns.__path__ = []
        ns.__package__ = _NAMESPACE_ROOT
        sys.modules[_NAMESPACE_ROOT] = ns


def import_plugin_class(
    plugin_id: str,
    plugin_dir: Path,
    entry_point: str,
) -> Tuple[Type[Any], ModuleType]:
    """Import a plugin class from *plugin_dir* using *entry_point*.

    Parameters
    ----------
    plugin_id:
        Unique plugin identifier (e.g. ``"com.microsanj.posh-tdtr"``).
    plugin_dir:
        Absolute path to the plugin's root directory (contains the
        module file referenced by *entry_point*).
    entry_point:
        ``"module_name:ClassName"`` string from the manifest.

    Returns
    -------
    (cls, module):
        The plugin class and the module it was loaded from.

    Raises
    ------
    PluginLoadError
        If the module or class cannot be resolved.
    """
    _ensure_namespace_root()

    try:
        module_name, class_name = entry_point.split(":", 1)
    except ValueError:
        raise PluginLoadError(
            plugin_id,
            f"entry_point must be 'module:Class', got '{entry_point}'")

    # Build a dotted module path under the namespace root.
    safe_id = plugin_id.replace(".", "_").replace("-", "_")
    fq_module = f"{_NAMESPACE_ROOT}.{safe_id}.{module_name}"

    # Resolve the .py file on disk.
    module_file = plugin_dir / f"{module_name}.py"
    if not module_file.is_file():
        # Try as a package (directory with __init__.py).
        package_init = plugin_dir / module_name / "__init__.py"
        if package_init.is_file():
            module_file = package_init
        else:
            raise PluginLoadError(
                plugin_id,
                f"Cannot find '{module_name}.py' or "
                f"'{module_name}/__init__.py' in {plugin_dir}")

    # Create an intermediate namespace for this plugin's ID.
    ns_id = f"{_NAMESPACE_ROOT}.{safe_id}"
    if ns_id not in sys.modules:
        ns = ModuleType(ns_id)
        ns.__path__ = [str(plugin_dir)]
        ns.__package__ = ns_id
        sys.modules[ns_id] = ns

    # Import the module via importlib spec.
    try:
        spec = importlib.util.spec_from_file_location(
            fq_module,
            str(module_file),
            submodule_search_locations=(
                [str(module_file.parent)] if module_file.name == "__init__.py"
                else None
            ),
        )
        if spec is None or spec.loader is None:
            raise PluginLoadError(
                plugin_id,
                f"importlib could not create a spec for {module_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[fq_module] = module

        # Temporarily prepend the plugin directory to sys.path so that
        # relative imports within the plugin resolve correctly.
        plugin_dir_str = str(plugin_dir)
        inserted = False
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
            inserted = True

        try:
            spec.loader.exec_module(module)
        finally:
            if inserted:
                try:
                    sys.path.remove(plugin_dir_str)
                except ValueError:
                    pass

    except PluginLoadError:
        raise
    except Exception as exc:
        raise PluginLoadError(
            plugin_id,
            f"Failed to import {module_file}: {exc}") from exc

    # Extract the class.
    cls = getattr(module, class_name, None)
    if cls is None:
        raise PluginLoadError(
            plugin_id,
            f"Class '{class_name}' not found in module '{module_name}'")

    return cls, module


def unload_plugin(plugin_id: str) -> None:
    """Remove all sys.modules entries for *plugin_id*'s namespace.

    This is best-effort — Python's import system does not guarantee
    complete cleanup, but removing the entries allows re-import.
    """
    safe_id = plugin_id.replace(".", "_").replace("-", "_")
    prefix = f"{_NAMESPACE_ROOT}.{safe_id}"
    to_remove = [k for k in sys.modules if k == prefix or k.startswith(prefix + ".")]
    for k in to_remove:
        del sys.modules[k]
    log.debug("Unloaded %d module(s) for plugin '%s'", len(to_remove), plugin_id)
