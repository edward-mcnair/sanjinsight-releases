"""
acquisition/session.py

A Session is one complete measurement acquisition saved to disk.
Supports all Microsanj imaging modalities: thermoreflectance, IR lock-in,
hybrid, and optical pump-probe (OPP).

Each session lives in a self-contained folder:

    sessions/
        20250315_143022_device_A/
            session.json           ← metadata (human-readable)
            cold_avg.npy           ← float32 baseline frame
            hot_avg.npy            ← float32 stimulus frame
            delta_r_over_r.npy     ← float32 ΔR/R signal
            difference.npy         ← float32 hot − cold
            thumbnail.png          ← small ΔR/R preview for browser

Usage:
    session = Session.from_result(result, label="device_A_25C")
    path    = session.save("/path/to/sessions")

    session = Session.load("/path/to/sessions/20250315_143022_device_A")
    drr     = session.delta_r_over_r   # float32 numpy array
"""

from __future__ import annotations
import logging
import os, json, time
import threading
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from acquisition.schema_migrations import (
    CURRENT_SCHEMA, migrate, reject_future_schema, FutureSchemaError,
)
from acquisition.storage._atomic import atomic_write_json

log = logging.getLogger(__name__)


@dataclass
class SessionMeta:
    """
    Lightweight metadata — loadable without reading numpy files.

    All fields needed to fully reproduce a measurement and trace it in
    a quality management system are stored here.
    """
    # Identity
    uid:           str            = ""
    label:         str            = ""
    timestamp:     float          = 0.0
    timestamp_str: str            = ""

    # ── Imaging modality ───────────────────────────────────────────
    imaging_mode:  str  = "thermoreflectance"  # ImagingModality value
    wavelength_nm: int  = 532                  # illumination wavelength

    # ── Camera / acquisition ───────────────────────────────────────
    n_frames:      int            = 0
    exposure_us:   float          = 0.0
    gain_db:       float          = 0.0
    duration_s:    float          = 0.0
    snr_db:        Optional[float]= None
    frame_h:       int            = 0
    frame_w:       int            = 0

    # ── FPGA modulation ────────────────────────────────────────────
    fpga_frequency_hz: float = 0.0    # modulation frequency used
    fpga_duty_cycle:   float = 0.5    # duty cycle (0–1)

    # ── TEC / temperature ──────────────────────────────────────────
    tec_temperature:   float = 0.0   # sample temperature at acquisition (°C)
    tec_setpoint:      float = 0.0   # TEC setpoint at acquisition (°C)

    # ── Bias / DUT drive conditions ────────────────────────────────
    bias_voltage:   float = 0.0      # V  (0 if not applicable)
    bias_current:   float = 0.0      # A  (0 if not applicable)

    # ── Material profile ───────────────────────────────────────────
    profile_uid:    str   = ""       # uid of the MaterialProfile used
    profile_name:   str   = ""       # human-readable copy for traceability
    ct_value:       float = 0.0      # C_T coefficient used (0 if uncalibrated)

    # ── Geometry ───────────────────────────────────────────────────
    notes:          str            = ""
    roi:            Optional[dict] = None
    has_drr:        bool           = False
    path:           str            = ""

    # ── Provenance / Lab context ─────────────────────────────────────
    operator:   str       = ""       # name of the person who ran the scan
    device_id:  str       = ""       # DUT / device-under-test identifier
    project:    str       = ""       # project or lot name
    status:     str       = ""       # "pending" | "reviewed" | "flagged" | "archived"
    tags:       List[str] = field(default_factory=list)   # user-defined tag strings

    # ── Hardware identity (v2) ────────────────────────────────────────
    camera_id:  str        = ""    # e.g. "TR-Andor-iStar-SN12345"
    notes_log:  List[dict] = field(default_factory=list)  # NoteEntry dicts

    # ── Multi-channel / bit-depth metadata (v3) ────────────────────
    frame_channels:  int = 1       # 1 = mono, 3 = RGB
    frame_bit_depth: int = 16      # native sensor bit depth
    pixel_format:    str = "mono"  # "mono" | "bayer_rggb" | "rgb"

    # ── Pre-capture validation (v3) ──────────────────────────────────
    preflight:       Optional[dict] = None  # PreflightResult.to_dict()

    # ── Post-acquisition quality scoring (v4) ──────────────────────
    quality_scorecard: Optional[dict] = None  # QualityScorecard.to_dict()

    # ── Analysis result persistence (v5) ─────────────────────────
    analysis_result: Optional[dict] = None  # AnalysisResult.to_dict()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("path", None)
        d["schema_version"] = CURRENT_SCHEMA
        return d

    @staticmethod
    def from_dict(d: dict, path: str = "") -> "SessionMeta":
        """Deserialise a metadata dict, migrating old schemas on the fly.

        Raises ``FutureSchemaError`` if the file was written by a newer
        SanjINSIGHT build (schema_version > CURRENT_SCHEMA).  This is a
        hard reject — silently ignoring unknown fields could corrupt data
        if the session is later re-saved with the missing fields dropped.
        """
        version = d.get("schema_version", 0)

        # Hard-reject sessions from the future
        reject_future_schema(version, path)

        if version < CURRENT_SCHEMA:
            json_path = os.path.join(path, "session.json") if path else ""
            d = migrate(d, from_version=version,
                        session_json_path=json_path)
        m = SessionMeta(path=path)
        for k, v in d.items():
            if hasattr(m, k):
                setattr(m, k, v)
        return m


@dataclass
class Session:
    """Full session — metadata + lazily-loaded numpy arrays.

    Thread safety: all mutable state is guarded by ``_lock``.  Concurrent
    reads (e.g. autosave thread + analysis thread) are serialised to avoid
    TOCTOU races on the lazy-loaded numpy arrays and the JSON save path.
    """
    meta:             SessionMeta          = field(default_factory=SessionMeta)
    _cold_avg:        Optional[np.ndarray] = field(default=None, repr=False)
    _hot_avg:         Optional[np.ndarray] = field(default=None, repr=False)
    _delta_r_over_r:  Optional[np.ndarray] = field(default=None, repr=False)
    _difference:      Optional[np.ndarray] = field(default=None, repr=False)

    def __post_init__(self):
        self._lock = threading.RLock()

    @property
    def cold_avg(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._cold_avg is None:
                self._cold_avg = self._load("cold_avg.npy")
            return self._cold_avg

    @property
    def hot_avg(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._hot_avg is None:
                self._hot_avg = self._load("hot_avg.npy")
            return self._hot_avg

    @property
    def delta_r_over_r(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._delta_r_over_r is None:
                self._delta_r_over_r = self._load("delta_r_over_r.npy")
            return self._delta_r_over_r

    @property
    def difference(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._difference is None:
                self._difference = self._load("difference.npy")
            return self._difference

    def _load(self, filename: str) -> Optional[np.ndarray]:
        p = os.path.join(self.meta.path, filename)
        return np.load(p, mmap_mode="r") if os.path.exists(p) else None

    def unload(self):
        with self._lock:
            for attr in ("_cold_avg", "_hot_avg", "_delta_r_over_r", "_difference"):
                arr = getattr(self, attr, None)
                if isinstance(arr, np.memmap):
                    del arr
                setattr(self, attr, None)

    @staticmethod
    def from_result(result, label: str = "",
                    imaging_mode: str = "thermoreflectance",
                    wavelength_nm: int = 532,
                    fpga_frequency_hz: float = 0.0,
                    fpga_duty_cycle: float = 0.5,
                    tec_temperature: float = 0.0,
                    tec_setpoint: float = 0.0,
                    bias_voltage: float = 0.0,
                    bias_current: float = 0.0,
                    profile_uid: str = "",
                    profile_name: str = "",
                    ct_value: float = 0.0,
                    operator: str = "",
                    device_id: str = "",
                    project: str = "",
                    status: str = "",
                    tags: Optional[List[str]] = None,
                    camera_id: str = "",
                    notes_log: Optional[List[dict]] = None) -> "Session":
        ts     = time.time()
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        slug   = label.replace(" ", "_").replace("/", "-") if label else "unnamed"
        uid    = f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}"

        h, w = 0, 0
        for arr in [result.cold_avg, result.hot_avg, result.delta_r_over_r]:
            if arr is not None:
                h, w = arr.shape[:2]; break

        roi_dict = None
        if hasattr(result, "roi") and result.roi is not None:
            roi_dict = result.roi.to_dict()

        meta = SessionMeta(
            uid           = uid,
            label         = label or uid,
            timestamp     = ts,
            timestamp_str = ts_str,
            imaging_mode  = imaging_mode,
            wavelength_nm = wavelength_nm,
            n_frames      = getattr(result, "n_frames",    0),
            exposure_us   = getattr(result, "exposure_us", 0.0),
            gain_db       = getattr(result, "gain_db",     0.0),
            duration_s    = getattr(result, "duration_s",  0.0),
            snr_db        = getattr(result, "snr_db",      None),
            frame_h       = h,
            frame_w       = w,
            fpga_frequency_hz = fpga_frequency_hz,
            fpga_duty_cycle   = fpga_duty_cycle,
            tec_temperature   = tec_temperature,
            tec_setpoint      = tec_setpoint,
            bias_voltage      = bias_voltage,
            bias_current      = bias_current,
            profile_uid       = profile_uid,
            profile_name      = profile_name,
            ct_value          = ct_value,
            notes         = getattr(result, "notes",       ""),
            roi           = roi_dict,
            has_drr       = result.delta_r_over_r is not None,
            operator      = operator,
            device_id     = device_id,
            project       = project,
            status        = status,
            tags          = list(tags) if tags else [],
            camera_id     = camera_id,
            notes_log     = list(notes_log) if notes_log else [],
        )

        return Session(
            meta            = meta,
            _cold_avg       = result.cold_avg,
            _hot_avg        = result.hot_avg,
            _delta_r_over_r = result.delta_r_over_r,
            _difference     = result.difference,
        )

    def save(self, sessions_root: str) -> str:
        """Persist session to *sessions_root*/<uid>/.

        Write ordering: arrays first (idempotent — can be rewritten safely),
        then metadata JSON via atomic write.  ``meta.path`` is only set after
        the JSON is durably committed, so in-memory state never disagrees
        with disk on a crash.
        """
        with self._lock:
            folder = os.path.join(sessions_root, self.meta.uid)
            os.makedirs(folder, exist_ok=True)

            # 1. Arrays (order doesn't matter; each is self-contained)
            for name, arr in [
                ("cold_avg",       self._cold_avg),
                ("hot_avg",        self._hot_avg),
                ("delta_r_over_r", self._delta_r_over_r),
                ("difference",     self._difference),
            ]:
                if arr is not None:
                    np.save(os.path.join(folder, f"{name}.npy"), arr)

            # 2. Thumbnail (best-effort, non-critical)
            if self._delta_r_over_r is not None:
                self._save_thumbnail(folder)

            # 3. Metadata — atomic write (temp + flush + fsync + rename)
            #    Build the dict with the target path so ``from_dict`` can
            #    reconstruct later, but don't mutate self.meta.path yet.
            meta_snapshot = self.meta.to_dict()
            json_path = os.path.join(folder, "session.json")
            atomic_write_json(json_path, meta_snapshot)

            # 4. Commit in-memory path only after disk write succeeds
            self.meta.path = folder
            return folder

    def _save_thumbnail(self, folder: str):
        try:
            drr    = self._delta_r_over_r.astype(np.float32)
            limit  = float(np.percentile(np.abs(drr), 99.5)) or 1e-9
            normed = np.clip(drr / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            import cv2
            thumb = cv2.resize(np.stack([r, g, b], axis=-1), (160, 120))
            cv2.imwrite(os.path.join(folder, "thumbnail.png"), thumb)
        except Exception:
            log.debug("Thumbnail save failed for %s", folder, exc_info=True)

    @staticmethod
    def load(folder: str) -> "Session":
        """Load a session from *folder*.

        Raises ``FileNotFoundError`` if session.json is missing and
        ``FutureSchemaError`` if the file was written by a newer build.
        """
        p = os.path.join(folder, "session.json")
        if not os.path.exists(p):
            raise FileNotFoundError(f"No session.json in {folder}")
        with open(p) as f:
            d = json.load(f)
        return Session(meta=SessionMeta.from_dict(d, path=folder))

    @staticmethod
    def load_meta(folder: str) -> Optional[SessionMeta]:
        p = os.path.join(folder, "session.json")
        if not os.path.exists(p):
            return None
        try:
            with open(p) as f:
                return SessionMeta.from_dict(json.load(f), path=folder)
        except json.JSONDecodeError as exc:
            log.error("Session at '%s' has corrupt JSON: %s — skipping.", folder, exc)
            return None
        except FutureSchemaError as exc:
            log.warning("Skipping session: %s", exc)
            return None
        except Exception:
            log.debug("Could not load session meta from '%s'", folder, exc_info=True)
            return None

    # ---------------------------------------------------------------- #
    #  Analysis persistence                                              #
    # ---------------------------------------------------------------- #

    def save_analysis(self, result) -> None:
        """Persist an AnalysisResult alongside the session on disk.

        Write ordering: arrays first, then metadata JSON via atomic write.
        ``self.meta.analysis_result`` is updated only after the JSON is
        durably committed so memory and disk stay consistent on failure.
        """
        with self._lock:
            folder = self.meta.path
            if not folder or not os.path.isdir(folder):
                log.warning("Cannot save analysis — session has no path on disk")
                return

            # 1. Arrays (idempotent)
            if result.overlay_rgb is not None:
                np.save(os.path.join(folder, "analysis_overlay.npy"),
                        result.overlay_rgb)
            if result.binary_mask is not None:
                np.save(os.path.join(folder, "analysis_mask.npy"),
                        result.binary_mask)

            # 2. Build JSON with the new analysis attached, but don't
            #    mutate self.meta yet — write disk first.
            analysis_dict = result.to_dict()
            old_analysis = self.meta.analysis_result
            self.meta.analysis_result = analysis_dict
            try:
                json_path = os.path.join(folder, "session.json")
                atomic_write_json(json_path, self.meta.to_dict())
            except Exception:
                # Disk write failed — roll back in-memory change
                self.meta.analysis_result = old_analysis
                raise

    def load_analysis(self):
        """Reconstruct an AnalysisResult from disk, or return None."""
        d = self.meta.analysis_result
        if not d:
            return None
        folder = self.meta.path
        overlay = self._load("analysis_overlay.npy")
        mask = self._load("analysis_mask.npy")
        from acquisition.analysis import AnalysisResult
        return AnalysisResult.from_dict(d, overlay_rgb=overlay,
                                        binary_mask=mask)

    def __repr__(self):
        return f"<Session {self.meta.uid!r} snr={self.meta.snr_db}>"
