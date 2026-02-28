"""
hardware/driver_store.py

DriverStore — fetches the Microsanj driver index, downloads driver
packages, and installs or hot-loads them.

Driver package types
--------------------
  "module"   — a single .py file; can be hot-loaded immediately for
               devices that support it (hot_loadable = True)
  "zip"      — a zip archive containing one or more .py files and an
               optional requires.txt; requires app restart

Install location
----------------
  ~/.microsanj/drivers/
    <module_name>.py          ← installed module files
    <driver_uid>.meta.json    ← version/timestamp metadata

Index format (hosted at MICROSANJ_DRIVER_INDEX_URL)
----------------------------------------------------
{
  "version": 1,
  "updated": "2025-06-01",
  "drivers": [
    {
      "uid":              "tec_meerstetter_v2",
      "display_name":     "Meerstetter TEC Driver v2.1",
      "device_uids":      ["meerstetter_tec_1089", "meerstetter_tec_1123"],
      "driver_module":    "meerstetter",
      "package_type":     "module",
      "version":          "2.1.0",
      "min_app_version":  "1.0.0",
      "hot_loadable":     true,
      "changelog":        "Improved error recovery, added TEC-1123 support.",
      "download_url":     "https://drivers.microsanj.com/meerstetter_v2.py",
      "checksum_sha256":  "abc123..."
    }
  ]
}
"""

from __future__ import annotations
import os, json, time, hashlib, zipfile, importlib.util, threading
from dataclasses import dataclass, field
from typing      import List, Optional, Callable
from urllib      import request, error as url_error

MICROSANJ_DRIVER_INDEX_URL = (
    "https://raw.githubusercontent.com/microsanj/drivers/main/index.json"
)
INDEX_URL      = os.environ.get("MICROSANJ_DRIVER_REPO",
                                 MICROSANJ_DRIVER_INDEX_URL)
DRIVERS_DIR    = os.path.join(os.path.expanduser("~"),
                               ".microsanj", "drivers")
REQUEST_TIMEOUT = 12


# ------------------------------------------------------------------ #
#  Data models                                                         #
# ------------------------------------------------------------------ #

@dataclass
class RemoteDriverEntry:
    uid:             str
    display_name:    str
    device_uids:     List[str]
    driver_module:   str
    package_type:    str          # "module" | "zip"
    version:         str
    min_app_version: str
    hot_loadable:    bool
    changelog:       str
    download_url:    str
    checksum_sha256: str = ""
    installed_version: str = ""   # filled in by DriverStore.check()
    already_current: bool  = False


@dataclass
class InstallResult:
    uid:         str
    success:     bool
    version:     str     = ""
    hot_loaded:  bool    = False
    needs_restart: bool  = False
    path:        str     = ""
    error:       str     = ""


# ------------------------------------------------------------------ #
#  Driver store                                                        #
# ------------------------------------------------------------------ #

class DriverStore:

    def __init__(self, device_manager=None):
        self._mgr = device_manager
        os.makedirs(DRIVERS_DIR, exist_ok=True)

    # ---------------------------------------------------------------- #
    #  Index                                                            #
    # ---------------------------------------------------------------- #

    def fetch_index(self,
                    progress_cb: Optional[Callable[[str], None]] = None
                    ) -> List[RemoteDriverEntry]:
        if progress_cb:
            progress_cb("Connecting to Microsanj driver repository…")
        try:
            req = request.Request(
                INDEX_URL,
                headers={"User-Agent": "MicrosanjThermalAnalysis/1.0"})
            with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
        except url_error.URLError as e:
            raise RuntimeError(
                f"Cannot reach driver server:\n{e}\n\n"
                f"Check your internet connection or contact "
                f"support@microsanj.com") from e

        data = json.loads(raw)
        entries = []
        installed = self._load_installed_meta()

        for item in data.get("drivers", []):
            try:
                uid  = item["uid"]
                inst = installed.get(item.get("driver_module", ""), {})
                inst_ver = inst.get("version", "")
                entry = RemoteDriverEntry(
                    uid             = uid,
                    display_name    = item["display_name"],
                    device_uids     = item.get("device_uids", []),
                    driver_module   = item.get("driver_module", ""),
                    package_type    = item.get("package_type", "module"),
                    version         = item["version"],
                    min_app_version = item.get("min_app_version", "1.0.0"),
                    hot_loadable    = item.get("hot_loadable", False),
                    changelog       = item.get("changelog", ""),
                    download_url    = item["download_url"],
                    checksum_sha256 = item.get("checksum_sha256", ""),
                    installed_version = inst_ver,
                    already_current = (inst_ver == item["version"]),
                )
                entries.append(entry)
            except KeyError:
                continue

        if progress_cb:
            n_new = sum(1 for e in entries if not e.already_current)
            progress_cb(
                f"{len(entries)} drivers available  ·  "
                f"{n_new} update(s) available")
        return entries

    # ---------------------------------------------------------------- #
    #  Download & install                                               #
    # ---------------------------------------------------------------- #

    def install(self,
                entry: RemoteDriverEntry,
                progress_cb: Optional[Callable[[str], None]] = None
                ) -> InstallResult:

        if progress_cb:
            progress_cb(f"Downloading {entry.display_name}…")

        # Download
        try:
            req = request.Request(
                entry.download_url,
                headers={"User-Agent": "MicrosanjThermalAnalysis/1.0"})
            with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read()
        except Exception as e:
            return InstallResult(uid=entry.uid, success=False,
                                  error=f"Download failed: {e}")

        # Require checksum — reject unsigned packages
        if not entry.checksum_sha256:
            raise ValueError(
                f"Driver '{entry.uid}' has no SHA-256 checksum. "
                "Unsigned driver packages are not installed for security. "
                "Contact Microsanj support to obtain a signed driver.")

        # Verify checksum
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry.checksum_sha256:
                return InstallResult(
                    uid=entry.uid, success=False,
                    error=f"Checksum mismatch — download may be corrupted.\n"
                          f"Expected: {entry.checksum_sha256}\n"
                          f"Got:      {actual}")

        os.makedirs(DRIVERS_DIR, exist_ok=True)

        # Install
        try:
            if entry.package_type == "module":
                path = self._install_module(entry, data)
            else:
                path = self._install_zip(entry, data, progress_cb)
        except Exception as e:
            return InstallResult(uid=entry.uid, success=False,
                                  error=f"Install failed: {e}")

        # Save metadata
        self._save_meta(entry)

        # Hot-load if possible
        hot_loaded    = False
        needs_restart = False

        if entry.hot_loadable and entry.package_type == "module":
            ok = self._hot_load(entry, path)
            if ok:
                hot_loaded = True
                if progress_cb:
                    progress_cb(f"✓  Hot-loaded: {entry.display_name}")
            else:
                needs_restart = True
                if progress_cb:
                    progress_cb(
                        f"✓  Installed: {entry.display_name}  "
                        f"(restart required)")
        else:
            needs_restart = True
            if progress_cb:
                progress_cb(
                    f"✓  Installed: {entry.display_name}  "
                    f"(restart required)")

        return InstallResult(
            uid          = entry.uid,
            success      = True,
            version      = entry.version,
            hot_loaded   = hot_loaded,
            needs_restart= needs_restart,
            path         = path,
        )

    def install_many(self,
                     entries: List[RemoteDriverEntry],
                     progress_cb: Optional[Callable[[str], None]] = None
                     ) -> List[InstallResult]:
        results = []
        for i, e in enumerate(entries):
            if progress_cb:
                progress_cb(f"[{i+1}/{len(entries)}]  {e.display_name}…")
            results.append(self.install(e, progress_cb))
        return results

    # ---------------------------------------------------------------- #
    #  Package handling                                                 #
    # ---------------------------------------------------------------- #

    def _install_module(self, entry: RemoteDriverEntry,
                         data: bytes) -> str:
        path = os.path.join(DRIVERS_DIR, f"{entry.driver_module}.py")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _install_zip(self, entry: RemoteDriverEntry,
                      data: bytes,
                      progress_cb: Optional[Callable] = None) -> str:
        zip_path = os.path.join(DRIVERS_DIR, f"{entry.uid}.zip")
        with open(zip_path, "wb") as f:
            f.write(data)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".py"):
                    zf.extract(name, DRIVERS_DIR)
                elif name == "requires.txt":
                    # Install Python dependencies
                    reqs = zf.read(name).decode().splitlines()
                    reqs = [r.strip() for r in reqs if r.strip()
                            and not r.startswith("#")]
                    if reqs and progress_cb:
                        progress_cb(
                            f"Installing dependencies: {', '.join(reqs)}…")
                    for req in reqs:
                        os.system(
                            f"pip install {req} --quiet "
                            f"--break-system-packages 2>/dev/null")

        os.unlink(zip_path)
        return os.path.join(DRIVERS_DIR, f"{entry.driver_module}.py")

    # ---------------------------------------------------------------- #
    #  Hot-loading                                                      #
    # ---------------------------------------------------------------- #

    def _hot_load(self, entry: RemoteDriverEntry, path: str) -> bool:
        """
        Reload the driver module in-place and notify DeviceManager.
        Returns True if hot-load succeeded.
        """
        try:
            mod_name = f"microsanj_driver_{entry.driver_module}"
            spec     = importlib.util.spec_from_file_location(mod_name, path)
            mod      = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # If DeviceManager is available, reconnect affected devices
            if self._mgr:
                for uid in entry.device_uids:
                    entry_dev = self._mgr.get(uid)
                    if entry_dev and entry_dev.is_connected:
                        # Reconnect using the new driver
                        self._mgr.disconnect(uid)
                        time.sleep(0.5)
                        self._mgr.connect(uid)
                    if entry_dev:
                        self._mgr.apply_driver_update(uid, entry.version)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- #
    #  Metadata persistence                                             #
    # ---------------------------------------------------------------- #

    def _meta_path(self, module_name: str) -> str:
        return os.path.join(DRIVERS_DIR, f"{module_name}.meta.json")

    def _load_installed_meta(self) -> dict:
        result = {}
        if not os.path.isdir(DRIVERS_DIR):
            return result
        for fname in os.listdir(DRIVERS_DIR):
            if not fname.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(DRIVERS_DIR, fname)) as f:
                    d = json.load(f)
                module = fname.replace(".meta.json", "")
                result[module] = d
            except Exception:
                pass
        return result

    def _save_meta(self, entry: RemoteDriverEntry):
        meta = {
            "uid":          entry.uid,
            "version":      entry.version,
            "installed_at": time.time(),
            "download_url": entry.download_url,
            "hot_loadable": entry.hot_loadable,
        }
        with open(self._meta_path(entry.driver_module), "w") as f:
            json.dump(meta, f, indent=2)

    def get_installed_version(self, driver_module: str) -> str:
        meta = self._load_installed_meta()
        return meta.get(driver_module, {}).get("version", "")
