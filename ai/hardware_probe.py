"""
ai/hardware_probe.py

probe_hardware() — fast (<300 ms) machine scan for AI model selection.

Detects available RAM and GPU using only the Python standard library
(subprocess, platform, ctypes).  Never raises — returns safe defaults
on any detection failure.

Supported configurations
------------------------
  • NVIDIA GPU    — via nvidia-smi (Windows/Linux/macOS)
  • Apple Silicon — arm64 + Metal (macOS)
  • AMD / Intel   — WMIC on Windows (VRAM estimate)
  • CPU-only      — fallback for everything else
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

from ai.model_catalog import MODEL_CATALOG, MODEL_ORDER

log = logging.getLogger(__name__)

# Headroom to leave free after loading the model (GB)
_HEADROOM_GB = 1.5


@dataclass
class HardwareProfile:
    """Result of probe_hardware()."""
    ram_gb:                   float
    gpu_name:                 Optional[str]   = None
    gpu_vram_gb:              Optional[float] = None
    has_cuda:                 bool            = False
    has_metal:                bool            = False
    # ── Recommendation ──────────────────────────────────────────────
    recommended_model_id:     str             = "phi35_mini_q4"
    recommended_n_gpu_layers: int             = 0
    hw_summary:               str             = ""   # one-line display
    rec_reason:               str             = ""   # why this model


def probe_hardware() -> HardwareProfile:
    """
    Probe the machine and return a HardwareProfile with a model recommendation.
    Safe to call from the UI thread — completes in < 300 ms on all platforms.
    """
    ram_gb                              = _get_ram_gb()
    gpu_name, gpu_vram_gb, has_cuda, has_metal = _get_gpu_info()

    profile = HardwareProfile(
        ram_gb      = ram_gb,
        gpu_name    = gpu_name,
        gpu_vram_gb = gpu_vram_gb,
        has_cuda    = has_cuda,
        has_metal   = has_metal,
    )

    # ── One-line hardware summary ────────────────────────────────────
    parts = [f"{ram_gb:.0f} GB RAM"]
    if gpu_name:
        gpu_str = gpu_name
        if gpu_vram_gb:
            gpu_str += f"  ({gpu_vram_gb:.0f} GB VRAM)"
        if has_cuda:
            gpu_str += "  · CUDA"
        elif has_metal:
            gpu_str += "  · Metal"
        parts.append(gpu_str)
    profile.hw_summary = "  ·  ".join(parts)

    # ── Effective memory available for inference ─────────────────────
    if has_cuda and gpu_vram_gb:
        eff_gb    = gpu_vram_gb
        gpu_layers = 999
        accel     = "CUDA GPU"
    elif has_metal:
        # Apple unified memory — reserve ~35% for OS + other apps
        eff_gb    = ram_gb * 0.65
        gpu_layers = 999
        accel     = "Metal GPU"
    else:
        # CPU — reserve 3 GB for OS, app, and acquisition pipeline
        eff_gb    = max(0.0, ram_gb - 3.0)
        gpu_layers = 0
        accel     = "CPU"

    # ── Pick the largest model that fits in effective memory ─────────
    rec_id = MODEL_ORDER[0]          # start with smallest as safe default
    for model_id in MODEL_ORDER:
        m = MODEL_CATALOG[model_id]
        if eff_gb >= m["size_gb"] + _HEADROOM_GB:
            rec_id = model_id        # keep upgrading while it fits

    profile.recommended_model_id      = rec_id
    profile.recommended_n_gpu_layers  = gpu_layers

    m = MODEL_CATALOG[rec_id]
    profile.rec_reason = (
        f"{m['name']} recommended for {accel}  "
        f"({eff_gb:.1f} GB available)."
    )

    log.debug("HardwareProfile: %s", profile)
    return profile


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_ram_gb() -> float:
    """Return total physical RAM in GB. Falls back to 8.0 on failure."""
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True, timeout=3, stderr=subprocess.DEVNULL,
            )
            return int(out.strip()) / 1024 ** 3

        if sys.platform == "win32":
            import ctypes
            class _MEMSTATEX(ctypes.Structure):           # noqa: E306
                _fields_ = [
                    ("dwLength",                 ctypes.c_ulong),
                    ("dwMemoryLoad",             ctypes.c_ulong),
                    ("ullTotalPhys",             ctypes.c_ulonglong),
                    ("ullAvailPhys",             ctypes.c_ulonglong),
                    ("ullTotalPageFile",         ctypes.c_ulonglong),
                    ("ullAvailPageFile",         ctypes.c_ulonglong),
                    ("ullTotalVirtual",          ctypes.c_ulonglong),
                    ("ullAvailVirtual",          ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            s = _MEMSTATEX()
            s.dwLength = ctypes.sizeof(s)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return s.ullTotalPhys / 1024 ** 3

        # Linux
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024 / 1024 ** 3

    except Exception:
        log.debug("RAM detection failed", exc_info=True)

    return 8.0  # safe fallback


def _get_gpu_info() -> tuple[Optional[str], Optional[float], bool, bool]:
    """
    Returns (gpu_name, vram_gb, has_cuda, has_metal).
    All values may be None/False on failure.
    """

    # ── 1. NVIDIA via nvidia-smi (Windows / Linux / macOS) ──────────
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        ).strip().splitlines()[0]
        name, vram_mib = out.split(",", 1)
        return name.strip(), float(vram_mib.strip()) / 1024, True, False
    except Exception:
        pass

    # ── 2. Apple Silicon (arm64 + Metal) ────────────────────────────
    if sys.platform == "darwin" and platform.machine() == "arm64":
        chip = _apple_chip_name()
        ram  = _get_ram_gb()
        return chip, ram, False, True   # unified memory → VRAM = RAM

    # ── 3. Windows AMD / Intel via WMIC ─────────────────────────────
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController",
                 "get", "Name,AdapterRAM", "/format:csv"],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                # csv columns: Node, AdapterRAM, Name
                if len(parts) >= 3 and parts[2]:
                    try:
                        vram_bytes = int(parts[1])
                        name       = parts[2]
                        vram_gb    = vram_bytes / 1024 ** 3
                        return name, (vram_gb if vram_gb > 0.5 else None), False, False
                    except (ValueError, IndexError):
                        continue
        except Exception:
            pass

    return None, None, False, False


def _apple_chip_name() -> str:
    """Return the Apple chip label, e.g. 'Apple M2 Pro'."""
    # sysctl is fastest
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    # Fallback: system_profiler (slower but reliable)
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPHardwareDataType"],
            text=True, timeout=6, stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "Chip" in line or "Processor Name" in line:
                return line.split(":", 1)[-1].strip()
    except Exception:
        pass
    return "Apple Silicon"
