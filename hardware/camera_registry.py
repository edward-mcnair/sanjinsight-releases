"""
hardware/camera_registry.py

CameraRegistry — builds the list of configured cameras for the camera
selector QComboBox in AutoScanTab (and any place that needs it).

Supports two config.yaml formats
----------------------------------
Multi-camera (new format):
  hardware:
    cameras:
      - label: "Basler acA1920-155um"
        camera_type: "tr"           # "tr" | "ir"
        driver: "ni_imaqdx"
        camera_name: "cam4"
        exposure_us: 5000
      - label: "Microsanj IR Camera"
        camera_type: "ir"
        driver: "flir"

Legacy single-camera (backward-compatible):
  hardware:
    camera:
      driver: "ni_imaqdx"
      camera_type: "tr"             # optional — defaults to "tr"
      label: "Basler acA1920-155um" # optional — falls back to live model string
      ...

Live-state merge
-----------------
  CameraEntry.is_connected   True when the corresponding app_state slot is non-None
  CameraEntry.driver_model   Model string from the live CameraInfo

Demo mode
---------
  In demo mode, entries are synthesised from the running simulated drivers
  even when config.yaml has no cameras section (hybrid-demo shows both TR + IR).

No PyQt5 imports — safe in tests and background threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import logging

log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CameraEntry:
    """
    One configured camera slot.

    config_key   -- "tr" or "ir" — identifies which app_state slot this
                    entry maps to (_cam for "tr", _ir_cam for "ir").
                    On single-camera systems always "tr".
    label        -- display label used in the QComboBox header
    camera_type  -- "tr" (thermoreflectance) | "ir" (infrared)
    is_connected -- True when the driver slot in app_state is non-None
    driver_model -- model string from the live driver's CameraInfo
    cfg          -- raw config dict for this entry (for hardware_service)
    """
    config_key:   str
    label:        str
    camera_type:  str                     # "tr" | "ir"
    is_connected: bool       = False
    driver_model: str        = ""
    cfg:          dict       = field(default_factory=dict)

    def display_label(self) -> str:
        """'Basler acA1920-155um  [TR]' — the text shown in the dropdown."""
        tag  = "[TR]" if self.camera_type == "tr" else "[IR]"
        base = (self.driver_model
                if (self.is_connected and self.driver_model)
                else self.label)
        return f"{base}  {tag}"

    def status_suffix(self) -> str:
        """Short text appended to dropdown items."""
        return "connected" if self.is_connected else "not connected"


# ── Public API ────────────────────────────────────────────────────────────────

def _default_camera_type_from_registry(cam_cfg: dict) -> str:
    """
    Look up the default camera_type for a given camera config dict.

    Priority:
      1. Explicit camera_type in the config dict
      2. Match by driver name against DEVICE_REGISTRY camera_type fields
      3. "tr" (safe default — thermoreflectance is more common)
    """
    # 1. Explicit override in config
    explicit = cam_cfg.get("camera_type", "").strip().lower()
    if explicit in ("tr", "ir"):
        return explicit

    # 2. Look up by driver name (e.g. "flir" → "ir")
    from hardware.device_registry import DEVICE_REGISTRY, DTYPE_CAMERA
    driver = cam_cfg.get("driver", "").lower()
    model  = cam_cfg.get("model",  "").lower()
    for desc in DEVICE_REGISTRY.values():
        if desc.device_type != DTYPE_CAMERA:
            continue
        # Match by driver module suffix or model substring
        if driver and driver in desc.driver_module.lower():
            return desc.camera_type
        if model and any(model in p.lower() for p in (desc.serial_patterns or [])
                         if p):
            return desc.camera_type

    return "tr"


def get_cameras() -> List[CameraEntry]:
    """
    Return all configured camera slots with live connection state merged in.

    Lookup order:
      1. hardware.cameras list (multi-camera format)
      2. hardware.camera dict  (legacy single-camera format)
      3. Demo-mode synthesised from running drivers (fallback when config is empty)

    For camera_type, the priority is:
      a. Explicit camera_type in the config dict
      b. Default from DEVICE_REGISTRY (e.g. flir driver → "ir")
      c. "tr" fallback

    Always returns a list; empty only if config has no camera section and
    no cameras are running in demo mode.
    """
    import config as _cfg_mod
    from hardware.app_state import app_state

    hw: dict = _cfg_mod.get("hardware") or {}
    entries: List[CameraEntry] = []

    # ── New multi-camera format ──────────────────────────────────────────
    cameras_list = hw.get("cameras")
    if cameras_list and isinstance(cameras_list, list):
        seen_types: set = set()
        for i, cam_cfg in enumerate(cameras_list):
            if not isinstance(cam_cfg, dict):
                continue
            cam_type = _default_camera_type_from_registry(cam_cfg)
            label = (cam_cfg.get("label")
                     or cam_cfg.get("model", f"Camera {i + 1}"))
            # Use first occurrence per type as the active slot for that type.
            config_key = cam_type
            if cam_type in seen_types:
                config_key = f"{cam_type}_{i}"
            seen_types.add(cam_type)
            entries.append(CameraEntry(
                config_key=config_key,
                label=label,
                camera_type=cam_type,
                cfg=cam_cfg,
            ))

    # ── Legacy single-camera format ──────────────────────────────────────
    elif "camera" in hw:
        cam_cfg = hw["camera"]
        if isinstance(cam_cfg, dict):
            cam_type = _default_camera_type_from_registry(cam_cfg)
            label    = (cam_cfg.get("label")
                        or cam_cfg.get("model", "Camera"))
            entries.append(CameraEntry(
                config_key=cam_type,
                label=label,
                camera_type=cam_type,
                cfg=cam_cfg,
            ))

    # ── Merge with live app_state ────────────────────────────────────────
    tr_drv = getattr(app_state, "_cam",    None)
    ir_drv = getattr(app_state, "_ir_cam", None)

    for entry in entries:
        live_drv = tr_drv if entry.camera_type == "tr" else ir_drv
        if live_drv is not None:
            entry.is_connected = True
            try:
                entry.driver_model = live_drv.info.model or ""
            except Exception:
                pass
        # Refine label from live model when no explicit label/model in config
        if (not entry.cfg.get("label") and not entry.cfg.get("model")
                and entry.driver_model):
            entry.label = entry.driver_model

    # ── Supplement: add running cameras not covered by config ────────────
    # Cameras connected via Device Manager may not have a config entry.
    # In demo mode both TR and IR cameras are always started.  In either
    # case, add an entry for any camera type that is running but not
    # already represented so the CameraContextBar and selectors see it.
    seen_types = {e.camera_type for e in entries}
    for drv, cam_type in ((tr_drv, "tr"), (ir_drv, "ir")):
        if drv is None or cam_type in seen_types:
            continue
        model = ""
        try:
            model = drv.info.model or ""
        except Exception:
            pass
        entries.append(CameraEntry(
            config_key=cam_type,
            label=model or f"{cam_type.upper()} Camera",
            camera_type=cam_type,
            is_connected=True,
            driver_model=model,
        ))

    return entries


def get_active_entry() -> Optional[CameraEntry]:
    """Return the CameraEntry matching app_state.active_camera_type, or first entry."""
    from hardware.app_state import app_state
    active_type = getattr(app_state, "active_camera_type", "tr")
    cameras = get_cameras()
    for entry in cameras:
        if entry.camera_type == active_type:
            return entry
    return cameras[0] if cameras else None
