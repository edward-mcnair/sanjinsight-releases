"""
support — Support-bundle utilities.

Public exports
--------------
BundleBuilder   — builds a zip containing logs, config, device inventory,
                  timeline JSON, and system info.
collect_system_info — returns a dict of OS/Python/app metadata.
"""
from .system_info    import collect_system_info
from .bundle_builder import BundleBuilder, BundleWorker

__all__ = ["collect_system_info", "BundleBuilder", "BundleWorker"]
