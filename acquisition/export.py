"""
acquisition/export.py

Scientific data export for Microsanj sessions and acquisition results.

Supported formats
-----------------
    TIFF       — 32-bit float TIFF compatible with ImageJ / FIJI / Olympus
    HDF5       — all arrays + all metadata in one portable .h5 file
    CSV        — tab-separated ΔT(x_μm, y_μm) with spatial coordinates
    MATLAB     — .mat file readable directly in MATLAB (scipy.io.savemat)
    NPY/NPZ    — NumPy native format (lossless, fastest)

Usage
-----
    from acquisition.export import SessionExporter, ExportFormat

    # Export a session to multiple formats in one call
    exporter = SessionExporter(session, output_dir="~/Desktop/my_export")
    result   = exporter.export([
        ExportFormat.TIFF,
        ExportFormat.HDF5,
        ExportFormat.CSV,
        ExportFormat.MATLAB,
    ])
    print(result.saved_paths)   # list of absolute paths

    # Export with spatial calibration (for μm coordinates in CSV)
    exporter = SessionExporter(session, output_dir="~/Desktop",
                                px_per_um=2.5)
    result = exporter.export([ExportFormat.CSV])
"""

from __future__ import annotations

import os
import time
import logging
import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Export format enum                                                  #
# ------------------------------------------------------------------ #

class ExportFormat(str, Enum):
    TIFF    = "tiff"     # 32-bit float TIFF (all arrays)
    HDF5    = "hdf5"     # Single .h5 file with all data + metadata
    CSV     = "csv"      # ΔT map as tab-separated values with x/y coords
    MATLAB  = "matlab"   # .mat file (scipy.io.savemat)
    NPY     = "npy"      # NumPy .npy per-array + metadata.json
    NPZ     = "npz"      # Single compressed .npz archive


@dataclass
class ExportResult:
    """Returned by SessionExporter.export()."""
    saved_paths: List[str] = field(default_factory=list)
    errors:      Dict[str, str] = field(default_factory=dict)
    output_dir:  str = ""
    duration_s:  float = 0.0

    @property
    def success(self) -> bool:
        return len(self.saved_paths) > 0

    @property
    def n_files(self) -> int:
        return len(self.saved_paths)


# ------------------------------------------------------------------ #
#  Main exporter                                                       #
# ------------------------------------------------------------------ #

class SessionExporter:
    """
    Exports a Session (or raw arrays) to one or more scientific formats.

    Parameters
    ----------
    session     : Session object (from session_manager.load) — provides
                  all arrays and metadata automatically.
    output_dir  : folder to write exported files to (created if needed).
    px_per_um   : pixels per micrometre — enables μm coordinates in CSV.
                  0 = unknown (outputs pixel-index coordinates instead).
    prefix      : filename prefix; defaults to session uid or timestamp.
    """

    def __init__(self, session=None, output_dir: str = ".",
                 px_per_um: float = 0.0, prefix: str = ""):
        self._session    = session
        self._output_dir = os.path.expanduser(output_dir)
        self._px_per_um  = px_per_um
        self._prefix     = prefix or (
            session.meta.uid if session and hasattr(session, "meta")
            else time.strftime("%Y%m%d_%H%M%S"))

    # ---------------------------------------------------------------- #
    #  Public                                                           #
    # ---------------------------------------------------------------- #

    def export(self, formats: List[ExportFormat]) -> ExportResult:
        """
        Export session data in all requested formats.

        Returns an ExportResult with paths to all written files.
        """
        os.makedirs(self._output_dir, exist_ok=True)
        result   = ExportResult(output_dir=self._output_dir)
        t_start  = time.time()

        arrays, meta = self._collect_data()

        for fmt in formats:
            try:
                paths = self._export_one(fmt, arrays, meta)
                result.saved_paths.extend(paths)
                log.info("Exported %s → %s (%d file(s))",
                         fmt.value, self._output_dir, len(paths))
            except Exception as e:
                msg = f"{fmt.value}: {e}"
                result.errors[fmt.value] = msg
                log.error("Export failed — %s", msg)

        result.duration_s = time.time() - t_start
        return result

    # ---------------------------------------------------------------- #
    #  Internal routing                                                 #
    # ---------------------------------------------------------------- #

    def _export_one(self, fmt: ExportFormat, arrays: dict,
                    meta: dict) -> List[str]:
        dispatch = {
            ExportFormat.TIFF:   self._to_tiff,
            ExportFormat.HDF5:   self._to_hdf5,
            ExportFormat.CSV:    self._to_csv,
            ExportFormat.MATLAB: self._to_matlab,
            ExportFormat.NPY:    self._to_npy,
            ExportFormat.NPZ:    self._to_npz,
        }
        fn = dispatch.get(fmt)
        if fn is None:
            raise ValueError(f"Unknown format: {fmt}")
        return fn(arrays, meta)

    def _p(self, suffix: str) -> str:
        """Build an absolute output path."""
        return os.path.join(self._output_dir, f"{self._prefix}{suffix}")

    def _collect_data(self) -> tuple[dict, dict]:
        """Extract arrays and metadata from the session."""
        arrays: Dict[str, np.ndarray] = {}
        meta:   Dict[str, Any]        = {}

        if self._session is not None:
            s = self._session
            m = s.meta if hasattr(s, "meta") else None

            # Arrays (load lazily — session only reads from disk on access)
            for name in ["cold_avg", "hot_avg", "delta_r_over_r", "difference"]:
                arr = getattr(s, name, None)
                if arr is not None:
                    arrays[name] = arr.astype(np.float32)

            # Optional ΔT (computed from calibration, may not be persisted)
            dt = getattr(s, "delta_t", None)
            if dt is not None:
                arrays["delta_t"] = dt.astype(np.float32)

            # Metadata
            if m is not None:
                meta = {k: v for k, v in vars(m).items()
                        if not k.startswith("_")}

        return arrays, meta

    # ---------------------------------------------------------------- #
    #  TIFF exporter — 32-bit float, ImageJ / FIJI compatible          #
    # ---------------------------------------------------------------- #

    def _to_tiff(self, arrays: dict, meta: dict) -> List[str]:
        """
        Write each array as an independent 32-bit float TIFF.
        Falls back to cv2.imwrite if tifffile is unavailable.
        """
        saved = []

        try:
            import tifffile
            use_tifffile = True
        except ImportError:
            import cv2
            use_tifffile = False
            log.warning("tifffile not installed — using cv2 for TIFF export "
                        "(limited metadata support). "
                        "Install: pip install tifffile")

        array_info = {
            "cold_avg":       ("cold_baseline_uint16.tiff",    "uint16"),
            "hot_avg":        ("hot_stimulus_uint16.tiff",     "uint16"),
            "delta_r_over_r": ("delta_R_over_R_float32.tiff",  "float32"),
            "difference":     ("hot_minus_cold_float32.tiff",  "float32"),
            "delta_t":        ("delta_T_degC_float32.tiff",    "float32"),
        }

        for key, (suffix, dtype) in array_info.items():
            arr = arrays.get(key)
            if arr is None:
                continue
            path = self._p(f"_{suffix}")
            data = arr.astype(np.uint16 if dtype == "uint16" else np.float32)

            if use_tifffile:
                metadata = {
                    "axes": "YX",
                    "array":   key,
                    "unit":    "°C" if key == "delta_t" else ("counts" if "avg" in key else ""),
                    **{str(k): str(v) for k, v in meta.items()
                       if isinstance(v, (str, int, float, bool))},
                }
                tifffile.imwrite(path, data,
                                 imagej=True,
                                 metadata=metadata)
            else:
                import cv2
                cv2.imwrite(path, data)

            saved.append(path)

        return saved

    # ---------------------------------------------------------------- #
    #  HDF5 exporter — all-in-one portable archive                     #
    # ---------------------------------------------------------------- #

    def _to_hdf5(self, arrays: dict, meta: dict) -> List[str]:
        """
        Write all arrays and all metadata into a single .h5 file.

        Structure:
            /arrays/cold_avg             float32 dataset
            /arrays/hot_avg              float32 dataset
            /arrays/delta_r_over_r       float32 dataset
            /arrays/difference           float32 dataset
            /arrays/delta_t              float32 dataset (if available)
            /meta/*                      scalar datasets from SessionMeta
        """
        try:
            import h5py
        except ImportError:
            raise ImportError(
                "h5py not installed. Run: pip install h5py")

        path = self._p("_session.h5")
        with h5py.File(path, "w") as f:
            # Arrays group
            arr_grp = f.create_group("arrays")
            for key, data in arrays.items():
                ds = arr_grp.create_dataset(key, data=data,
                                            compression="gzip",
                                            compression_opts=4)
                unit_map = {
                    "cold_avg": "counts",
                    "hot_avg":  "counts",
                    "delta_r_over_r": "dimensionless",
                    "difference": "counts",
                    "delta_t": "degC",
                }
                ds.attrs["unit"] = unit_map.get(key, "")
                ds.attrs["description"] = _ARRAY_DESCRIPTIONS.get(key, "")

            # Metadata group — write each field as a scalar dataset
            meta_grp = f.create_group("meta")
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    try:
                        meta_grp.create_dataset(k, data=v)
                    except Exception:
                        pass

            # Top-level attributes
            f.attrs["creator"]       = "Microsanj Thermal Analysis System"
            f.attrs["format_version"] = "1.0"
            f.attrs["created"]        = time.strftime("%Y-%m-%d %H:%M:%S")
            f.attrs["imaging_mode"]   = str(meta.get("imaging_mode", "unknown"))

        return [path]

    # ---------------------------------------------------------------- #
    #  CSV exporter — ΔT map with x/y spatial coordinates             #
    # ---------------------------------------------------------------- #

    def _to_csv(self, arrays: dict, meta: dict) -> List[str]:
        """
        Write the primary result (ΔT preferred, else ΔR/R) as a
        tab-separated CSV with spatial coordinates.

        If px_per_um > 0, coordinates are in μm.
        Otherwise coordinates are in pixels.
        """
        # Choose best available array
        data = arrays.get("delta_t") or arrays.get("delta_r_over_r")
        if data is None:
            raise ValueError(
                "No ΔT or ΔR/R array available for CSV export.")

        H, W = data.shape[:2]
        px_per_um = self._px_per_um

        saved = []

        # ── Primary map CSV ────────────────────────────────────────
        path = self._p("_delta_T_map.csv")
        key_name  = "delta_t" if "delta_t" in arrays else "delta_r_over_r"
        unit      = "°C" if key_name == "delta_t" else "dimensionless"
        coord_unit = "um" if px_per_um > 0 else "px"

        with open(path, "w", newline="") as fh:
            fh.write(f"# Microsanj session export — {key_name}\n")
            fh.write(f"# Imaging mode: {meta.get('imaging_mode','?')}\n")
            fh.write(f"# Timestamp: {meta.get('timestamp_str','?')}\n")
            fh.write(f"# Unit: {unit}\n")
            fh.write(f"# Spatial coordinates: {coord_unit}\n")
            if px_per_um > 0:
                fh.write(f"# px_per_um: {px_per_um:.4f}\n")
            fh.write(f"# Array shape: {H} rows × {W} cols\n")
            fh.write("#\n")

            # Header row: x coordinates
            x_coords = (np.arange(W) / px_per_um) if px_per_um > 0 \
                        else np.arange(W, dtype=float)
            y_coords = (np.arange(H) / px_per_um) if px_per_um > 0 \
                        else np.arange(H, dtype=float)

            header = f"y_{coord_unit}\t" + "\t".join(f"{x:.3f}" for x in x_coords)
            fh.write(header + "\n")

            # Data rows
            for row_idx in range(H):
                y = y_coords[row_idx]
                vals = "\t".join(f"{v:.6g}" for v in data[row_idx])
                fh.write(f"{y:.3f}\t{vals}\n")

        saved.append(path)

        # ── Hotspot summary CSV (if analysis result attached) ──────
        # (future: pass analysis_result to export for hotspot table)

        return saved

    # ---------------------------------------------------------------- #
    #  MATLAB exporter                                                  #
    # ---------------------------------------------------------------- #

    def _to_matlab(self, arrays: dict, meta: dict) -> List[str]:
        """
        Write all arrays and metadata as a MATLAB .mat file.
        Requires scipy (already a dependency of the calibration engine).
        """
        try:
            from scipy.io import savemat
        except ImportError:
            raise ImportError(
                "scipy not installed. Run: pip install scipy")

        # MATLAB variable names cannot contain hyphens or slashes
        mat_dict: Dict[str, Any] = {}
        rename = {
            "delta_r_over_r": "delta_R_over_R",
            "cold_avg":       "cold_baseline",
            "hot_avg":        "hot_stimulus",
            "difference":     "hot_minus_cold",
            "delta_t":        "delta_T_degC",
        }
        for key, data in arrays.items():
            mat_name = rename.get(key, key)
            mat_dict[mat_name] = data

        # Metadata struct — only scalar/string fields are safe in .mat
        meta_safe = {}
        for k, v in meta.items():
            if isinstance(v, (int, float, bool)):
                meta_safe[k] = float(v)
            elif isinstance(v, str):
                meta_safe[k] = v
        mat_dict["meta"] = meta_safe

        path = self._p("_session.mat")
        savemat(path, mat_dict, do_compression=True)
        return [path]

    # ---------------------------------------------------------------- #
    #  NumPy exporters                                                  #
    # ---------------------------------------------------------------- #

    def _to_npy(self, arrays: dict, meta: dict) -> List[str]:
        """Write each array as an individual .npy file + metadata JSON."""
        import json
        saved = []
        for key, data in arrays.items():
            path = self._p(f"_{key}.npy")
            np.save(path, data)
            saved.append(path)

        # Metadata JSON
        meta_path = self._p("_metadata.json")
        meta_safe = {k: v for k, v in meta.items()
                     if isinstance(v, (str, int, float, bool, type(None)))}
        with open(meta_path, "w") as f:
            json.dump(meta_safe, f, indent=2, default=str)
        saved.append(meta_path)
        return saved

    def _to_npz(self, arrays: dict, meta: dict) -> List[str]:
        """Write all arrays in a single compressed .npz archive."""
        path = self._p("_session.npz")
        np.savez_compressed(path, **arrays)
        return [path]


# ------------------------------------------------------------------ #
#  Descriptions for HDF5 dataset attributes                          #
# ------------------------------------------------------------------ #

_ARRAY_DESCRIPTIONS = {
    "cold_avg":       "Averaged baseline frame (device OFF) in detector counts",
    "hot_avg":        "Averaged stimulus frame (device ON) in detector counts",
    "delta_r_over_r": "Thermoreflectance signal ΔR/R = (hot - cold) / cold",
    "difference":     "Difference image: hot_avg minus cold_avg",
    "delta_t":        "Temperature change ΔT in °C (ΔR/R converted via C_T calibration)",
}


# ------------------------------------------------------------------ #
#  Convenience wrapper compatible with the legacy export_result()     #
# ------------------------------------------------------------------ #

def export_session(session, output_dir: str,
                   formats: Optional[List[ExportFormat]] = None,
                   px_per_um: float = 0.0) -> ExportResult:
    """
    Convenience function to export a session to all default formats.

    Default formats: TIFF, HDF5, CSV, MATLAB, NPY.
    """
    if formats is None:
        formats = [
            ExportFormat.TIFF,
            ExportFormat.HDF5,
            ExportFormat.CSV,
            ExportFormat.MATLAB,
            ExportFormat.NPY,
        ]
    return SessionExporter(session, output_dir=output_dir,
                           px_per_um=px_per_um).export(formats)
