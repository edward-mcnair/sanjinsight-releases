"""
acquisition/recipe.py  —  Phase-based Recipe data model (v2)

A Recipe is an ordered sequence of phases that define a complete
measurement workflow:

    Preparation → Hardware Setup → Stabilization → Acquisition →
    Validation → Analysis → Output

Each phase has preconditions, a typed config dict, validation checks,
and a retry policy.  Operator-adjustable variables are declared with
type/range constraints so locked recipes expose a safe, bounded
parameter surface.

Storage
-------
    ~/.microsanj/recipes/<uid>.json      (v2, UID-keyed)
    ~/.microsanj/recipes/<label>.json    (v1 legacy, label-keyed)

Migration
---------
    v1 (flat RecipeCamera/RecipeAcquisition/… dicts) is auto-upgraded
    to v2 phase structure on load.  The original file is NOT rewritten;
    migration is in-memory only until the user explicitly saves.
"""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_RECIPES_DIR = Path.home() / ".microsanj" / "recipes"

CURRENT_RECIPE_VERSION = 2


# ================================================================== #
#  Enums                                                              #
# ================================================================== #

class PhaseType(str, Enum):
    """Canonical recipe phase types."""
    PREPARATION    = "preparation"
    HARDWARE_SETUP = "hardware_setup"
    STABILIZATION  = "stabilization"
    ACQUISITION    = "acquisition"
    VALIDATION     = "validation"
    ANALYSIS       = "analysis"
    OUTPUT         = "output"


# ================================================================== #
#  Supporting dataclasses                                              #
# ================================================================== #

@dataclass
class RetryPolicy:
    """What to do when a phase's validation fails."""
    max_retries: int = 0
    backoff_s:  float = 1.0
    on_exhaust:  str = "abort"          # "abort" | "warn_continue" | "skip"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RetryPolicy:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class HardwareRequirement:
    """A hardware device required (or recommended) to run this recipe.

    device_type values
    ------------------
    camera_tr, camera_ir    — thermoreflectance / IR camera
    fpga                    — modulation generator
    bias                    — bias/current source
    tec                     — TEC controller
    stage                   — motorised XY stage
    bilt                    — BILT pulse generator
    ldd                     — laser diode driver
    gpio                    — Arduino / LED selector
    prober                  — probe-station chuck
    turret                  — motorised objective turret
    """
    device_type: str              # canonical key (see above)
    label:       str = ""         # human-readable, e.g. "TR Camera (532 nm)"
    optional:    bool = False     # True = warn but allow run

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> HardwareRequirement:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class OperatorVariable:
    """A parameter the operator can adjust at run time.

    field_path points into a phase config, e.g.
    ``"hardware_setup.camera.exposure_us"`` means
    ``phases[hardware_setup].config["camera"]["exposure_us"]``.
    """
    field_path:    str              # e.g. "hardware_setup.camera.exposure_us"
    display_label: str = ""
    value_type:    str = "float"    # "float" | "int" | "bool" | "choice"
    unit:          str = ""
    default:       Any = None
    min_value:     Any = None       # constraint (float/int only)
    max_value:     Any = None       # constraint (float/int only)
    choices:       List[str] = field(default_factory=list)  # for "choice" type

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> OperatorVariable:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class RecipePhase:
    """One step in the recipe workflow."""
    phase_type:    str = ""         # PhaseType value string
    enabled:       bool = True
    config:        Dict[str, Any] = field(default_factory=dict)
    preconditions: List[str] = field(default_factory=list)
    validation:    List[str] = field(default_factory=list)
    retry:         RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s:     float = 0        # 0 = no timeout

    def to_dict(self) -> dict:
        d = {
            "phase_type":    self.phase_type,
            "enabled":       self.enabled,
            "config":        self.config,
            "preconditions": self.preconditions,
            "validation":    self.validation,
            "retry":         self.retry.to_dict(),
            "timeout_s":     self.timeout_s,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> RecipePhase:
        retry_raw = d.get("retry", {})
        retry = RetryPolicy.from_dict(retry_raw) if retry_raw else RetryPolicy()
        return cls(
            phase_type=d.get("phase_type", ""),
            enabled=d.get("enabled", True),
            config=d.get("config", {}),
            preconditions=list(d.get("preconditions", [])),
            validation=list(d.get("validation", [])),
            retry=retry,
            timeout_s=d.get("timeout_s", 0),
        )


# ================================================================== #
#  Recipe                                                              #
# ================================================================== #

@dataclass
class Recipe:
    """Phase-based measurement recipe (v2).

    A Recipe defines *how* to execute a measurement as an ordered
    sequence of phases.  Each phase has typed configuration, optional
    preconditions, post-phase validation, and retry policy.
    """

    # ── Identity ────────────────────────────────────────────────────
    uid:         str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label:       str = ""
    description: str = ""
    created_at:  str = ""
    version:     int = CURRENT_RECIPE_VERSION

    # ── Material reference ──────────────────────────────────────────
    profile_uid:  str = ""          # authoritative link (by UID)
    profile_name: str = ""          # cached display name (not authoritative)

    # ── Workflow ────────────────────────────────────────────────────
    phases:           List[RecipePhase]      = field(default_factory=list)
    acquisition_type: str = "single_point"   # "single_point"|"grid"|"transient"|"movie"

    # ── Hardware requirements ───────────────────────────────────────
    requirements: List[HardwareRequirement] = field(default_factory=list)

    # ── Operator interface ──────────────────────────────────────────
    variables: List[OperatorVariable] = field(default_factory=list)

    # ── Approval workflow ───────────────────────────────────────────
    locked:      bool = False
    approved_by: str  = ""
    approved_at: str  = ""

    # ── Metadata ────────────────────────────────────────────────────
    notes: str        = ""
    tags:  List[str]  = field(default_factory=list)

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "version":          self.version,
            "uid":              self.uid,
            "label":            self.label,
            "description":      self.description,
            "created_at":       self.created_at,
            "profile_uid":      self.profile_uid,
            "profile_name":     self.profile_name,
            "phases":           [p.to_dict() for p in self.phases],
            "acquisition_type": self.acquisition_type,
            "requirements":     [r.to_dict() for r in self.requirements],
            "variables":        [v.to_dict() for v in self.variables],
            "locked":           self.locked,
            "approved_by":      self.approved_by,
            "approved_at":      self.approved_at,
            "notes":            self.notes,
            "tags":             self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Recipe:
        """Deserialize a Recipe, auto-migrating v1 if necessary."""
        ver = d.get("version", 1)
        if ver < 2:
            d = _migrate_v1_to_v2(d)

        phases = [RecipePhase.from_dict(p) for p in d.get("phases", [])]
        requirements = [HardwareRequirement.from_dict(r)
                        for r in d.get("requirements", [])
                        if isinstance(r, dict)]
        variables = [OperatorVariable.from_dict(v)
                     for v in d.get("variables", [])
                     if isinstance(v, dict)]

        recipe = cls(
            uid=d.get("uid", str(uuid.uuid4())[:8]),
            label=d.get("label", ""),
            description=d.get("description", ""),
            created_at=d.get("created_at", ""),
            version=CURRENT_RECIPE_VERSION,
            profile_uid=d.get("profile_uid", ""),
            profile_name=d.get("profile_name", ""),
            phases=phases,
            acquisition_type=d.get("acquisition_type", "single_point"),
            requirements=requirements,
            variables=variables,
            locked=bool(d.get("locked", False)),
            approved_by=d.get("approved_by", ""),
            approved_at=d.get("approved_at", ""),
            notes=d.get("notes", ""),
            tags=list(d.get("tags", [])),
        )

        # Auto-infer requirements if not explicitly stored (v1 migration,
        # or v2 files saved before requirements were added)
        if not recipe.requirements:
            recipe.requirements = infer_requirements(recipe)

        return recipe

    # ── Phase access helpers ────────────────────────────────────────

    def get_phase(self, phase_type: str) -> Optional[RecipePhase]:
        """Return the first phase matching the given type, or None."""
        for p in self.phases:
            if p.phase_type == phase_type:
                return p
        return None

    def get_phase_config(self, phase_type: str) -> dict:
        """Return the config dict for a phase type, or empty dict."""
        p = self.get_phase(phase_type)
        return p.config if p else {}

    # ── Factory: from current hardware state ────────────────────────

    @classmethod
    def from_current_state(cls, app_state, label: str = "") -> Recipe:
        """Snapshot live hardware into a new Recipe with standard phases.

        Reads camera, FPGA, bias, TEC, and analysis state from
        ``app_state`` and builds a seven-phase recipe.
        """
        r = cls()
        r.label = label or f"recipe_{int(time.time())}"
        r.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Profile reference
        prof = getattr(app_state, "active_profile", None)
        if prof:
            r.profile_uid = getattr(prof, "uid", "")
            r.profile_name = getattr(prof, "name", "")

        # Gather hardware state
        cam_cfg = {}
        cam = getattr(app_state, "cam", None)
        if cam:
            try:
                cam_cfg["exposure_us"] = cam.get_exposure()
                cam_cfg["gain_db"] = cam.get_gain()
            except Exception:
                pass

        fpga_cfg = {}
        fpga = getattr(app_state, "fpga", None)
        if fpga:
            try:
                fpga_cfg["frequency_hz"] = fpga.get_frequency()
                fpga_cfg["duty_cycle"] = fpga.get_duty_cycle()
            except Exception:
                pass

        modality = getattr(app_state, "active_modality", "thermoreflectance")

        # Build phases
        r.phases = _build_standard_phases(
            camera=cam_cfg,
            fpga=fpga_cfg,
            modality=modality,
            acquisition_type="single_point",
        )
        r.requirements = infer_requirements(r)
        return r

    # ── Factory: from completed session ─────────────────────────────

    @classmethod
    def from_session(cls, session_meta, *, label: str = "") -> Recipe:
        """Reconstruct a Recipe from a completed session's metadata.

        Creates a new UID.  The resulting recipe captures the exact
        parameters that produced the session so the measurement can
        be reproduced.

        Parameters
        ----------
        session_meta
            A SessionMeta (or any object with the standard session
            metadata attributes).
        label : str, optional
            Override label.  Falls back to a timestamped default.
        """
        r = cls()
        r.uid = str(uuid.uuid4())[:8]
        r.label = label or f"from_session_{int(time.time())}"
        r.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        r.description = "Created from completed measurement session"

        # Profile reference
        r.profile_uid = getattr(session_meta, "profile_uid", "")
        r.profile_name = getattr(session_meta, "profile_name", "")

        # Map session result_type to acquisition_type
        result_type = getattr(session_meta, "result_type", "single_point")
        _RESULT_TO_ACQ = {
            "single_point": "single_point",
            "grid": "grid",
            "transient": "transient",
            "movie": "movie",
        }
        r.acquisition_type = _RESULT_TO_ACQ.get(result_type, "single_point")

        # Build phases from session metadata
        cam_cfg = {
            "exposure_us": getattr(session_meta, "exposure_us", 5000),
            "gain_db": getattr(session_meta, "gain_db", 0),
            "n_frames": getattr(session_meta, "n_frames", 16),
        }
        roi = getattr(session_meta, "roi", None)
        if roi:
            cam_cfg["roi"] = roi

        fpga_cfg = {
            "frequency_hz": getattr(session_meta, "fpga_frequency_hz", 1000),
            "duty_cycle": getattr(session_meta, "fpga_duty_cycle", 0.5),
        }

        bias_cfg = {
            "enabled": bool(getattr(session_meta, "bias_voltage", 0)),
            "voltage_v": getattr(session_meta, "bias_voltage", 0),
            "current_a": getattr(session_meta, "bias_current", 0),
        }

        tec_cfg = {
            "enabled": bool(getattr(session_meta, "tec_setpoint", 0)),
            "setpoint_c": getattr(session_meta, "tec_setpoint", 25.0),
        }

        modality = getattr(session_meta, "imaging_mode", "thermoreflectance")

        # Analysis thresholds — pull from quality scorecard if available
        analysis_cfg = {}
        qs = getattr(session_meta, "quality_scorecard", None)
        if isinstance(qs, dict):
            analysis_cfg["threshold_k"] = qs.get("threshold_k", 5.0)

        # Scan params for grid
        scan_cfg = {}
        sp = getattr(session_meta, "scan_params", None)
        if isinstance(sp, dict):
            scan_cfg = dict(sp)

        # Transient/movie params
        cube_cfg = {}
        cp = getattr(session_meta, "cube_params", None)
        if isinstance(cp, dict):
            cube_cfg = dict(cp)

        r.phases = _build_standard_phases(
            camera=cam_cfg,
            fpga=fpga_cfg,
            bias=bias_cfg,
            tec=tec_cfg,
            modality=modality,
            acquisition_type=r.acquisition_type,
            analysis=analysis_cfg,
            scan=scan_cfg,
            cube=cube_cfg,
        )
        r.requirements = infer_requirements(r)
        return r

    # ── Factory: from v1 run payload (backwards compat) ─────────────

    @classmethod
    def from_run_payload(cls, payload: dict, *,
                         label: str = "") -> Recipe:
        """Reconstruct a Recipe from a v1 RecipeRunPayload dict.

        Creates a new UID.  Only fields present in the payload are set;
        anything the payload did not capture stays at defaults.
        """
        r = cls()
        r.uid = str(uuid.uuid4())[:8]
        r.label = (label
                   or payload.get("recipe_label")
                   or f"from_run_{int(time.time())}")
        r.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        r.description = "Created from measurement run"
        r.profile_name = payload.get("profile_name", "")

        scan_type = payload.get("scan_type", "single")
        _SCAN_TO_ACQ = {"autoscan": "grid", "single": "single_point",
                        "transient": "transient"}
        r.acquisition_type = _SCAN_TO_ACQ.get(scan_type, "single_point")

        cam_cfg = {
            "exposure_us": payload.get("exposure_us", 5000),
            "gain_db": payload.get("gain_db", 0),
            "n_frames": payload.get("n_frames", 16),
        }
        fpga_cfg = {}
        bias_cfg = {
            "enabled": payload.get("bias_enabled", False),
            "voltage_v": payload.get("bias_voltage_v", 0),
            "current_a": payload.get("bias_current_a", 0),
        }
        tec_cfg = {
            "enabled": payload.get("tec_enabled", False),
            "setpoint_c": payload.get("tec_setpoint_c", 25.0),
        }
        modality = payload.get("modality", "thermoreflectance")
        analysis_cfg = {
            "threshold_k": payload.get("threshold_k", 5.0),
        }

        r.phases = _build_standard_phases(
            camera=cam_cfg,
            fpga=fpga_cfg,
            bias=bias_cfg,
            tec=tec_cfg,
            modality=modality,
            acquisition_type=r.acquisition_type,
            analysis=analysis_cfg,
        )
        r.requirements = infer_requirements(r)
        return r


# ================================================================== #
#  RecipeStore — persistence layer                                     #
# ================================================================== #

class RecipeStore:
    """Load / save recipes from ~/.microsanj/recipes/.

    Handles both v1 (label-keyed) and v2 (UID-keyed) files.
    All recipes are returned as v2 Recipe objects regardless of
    on-disk format.
    """

    def __init__(self, directory: Path = None):
        self._dir = Path(directory) if directory else _RECIPES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> List[Recipe]:
        """Return all saved recipes, sorted by label."""
        recipes = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                with open(p) as f:
                    recipes.append(Recipe.from_dict(json.load(f)))
            except Exception as e:
                log.warning("Skipping malformed recipe %s: %s", p.name, e)
        return sorted(recipes, key=lambda r: r.label.lower())

    def save(self, recipe: Recipe) -> Path:
        """Persist a recipe using its UID as filename."""
        recipe.version = CURRENT_RECIPE_VERSION
        path = self._dir / f"{recipe.uid}.json"
        with open(path, "w") as f:
            json.dump(recipe.to_dict(), f, indent=2)
        log.info("Recipe saved → %s", path)
        return path

    def save_as_new(self, recipe: Recipe) -> Path:
        """Persist with a fresh UID (collision-safe).

        Use for programmatic saves (post-run, import, duplication)
        where the caller has already assigned a fresh UID.
        """
        recipe.version = CURRENT_RECIPE_VERSION
        path = self._dir / f"{recipe.uid}.json"
        with open(path, "w") as f:
            json.dump(recipe.to_dict(), f, indent=2)
        log.info("Recipe saved (new) → %s", path)
        return path

    def delete(self, recipe: Recipe) -> None:
        """Delete a recipe file.  Tries UID-keyed first, then label-keyed."""
        # v2: UID-keyed
        path = self._dir / f"{recipe.uid}.json"
        if path.exists():
            path.unlink()
            log.info("Recipe deleted: %s", path)
            return
        # v1 fallback: label-keyed
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in recipe.label).strip("_")
        path = self._dir / f"{safe_label}.json"
        if path.exists():
            path.unlink()
            log.info("Recipe deleted (legacy): %s", path)

    def load(self, label: str) -> Optional[Recipe]:
        """Load a recipe by label string (v1 compat) or UID."""
        # Try UID first
        path = self._dir / f"{label}.json"
        if path.exists():
            with open(path) as f:
                return Recipe.from_dict(json.load(f))
        # Try label-keyed
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in label).strip("_")
        path = self._dir / f"{safe_label}.json"
        if path.exists():
            with open(path) as f:
                return Recipe.from_dict(json.load(f))
        return None


# ================================================================== #
#  Standard phase builder                                              #
# ================================================================== #

def _build_standard_phases(
    *,
    camera:           dict = None,
    fpga:             dict = None,
    bias:             dict = None,
    tec:              dict = None,
    modality:         str = "thermoreflectance",
    acquisition_type: str = "single_point",
    analysis:         dict = None,
    scan:             dict = None,
    cube:             dict = None,
) -> List[RecipePhase]:
    """Build the canonical seven-phase sequence from hardware parameters.

    This is the shared builder used by all factory methods.  Each dict
    may be partial; missing keys get sensible defaults at execution time.
    """
    camera = camera or {}
    fpga = fpga or {}
    bias = bias or {}
    tec = tec or {}
    analysis = analysis or {}
    scan = scan or {}
    cube = cube or {}

    phases = []

    # 1. Preparation — verify hardware is ready
    phases.append(RecipePhase(
        phase_type=PhaseType.PREPARATION.value,
        preconditions=["camera_connected"],
        config={
            "checks": ["camera_connected", "fpga_responsive"],
        },
    ))

    # 2. Hardware Setup — configure all devices
    hw_config: Dict[str, Any] = {
        "camera": {
            "exposure_us": camera.get("exposure_us", 5000),
            "gain_db": camera.get("gain_db", 0),
            "n_frames": camera.get("n_frames", 16),
        },
        "modality": modality,
    }
    if camera.get("roi"):
        hw_config["camera"]["roi"] = camera["roi"]
    if fpga:
        hw_config["fpga"] = {
            "frequency_hz": fpga.get("frequency_hz", 1000),
            "duty_cycle": fpga.get("duty_cycle", 0.5),
        }
        if "waveform" in fpga:
            hw_config["fpga"]["waveform"] = fpga["waveform"]
        if "trigger_mode" in fpga:
            hw_config["fpga"]["trigger_mode"] = fpga["trigger_mode"]
    if bias:
        hw_config["bias"] = {
            "enabled": bias.get("enabled", False),
            "voltage_v": bias.get("voltage_v", 0),
        }
        if "current_a" in bias:
            hw_config["bias"]["current_a"] = bias["current_a"]
        if "compliance_ma" in bias:
            hw_config["bias"]["compliance_ma"] = bias["compliance_ma"]
    if tec:
        hw_config["tec"] = {
            "enabled": tec.get("enabled", False),
            "setpoint_c": tec.get("setpoint_c", 25.0),
        }

    phases.append(RecipePhase(
        phase_type=PhaseType.HARDWARE_SETUP.value,
        config=hw_config,
    ))

    # 3. Stabilization — wait for equilibrium
    stab_config: Dict[str, Any] = {}
    if tec.get("enabled"):
        stab_config["tec_settle"] = {
            "tolerance_c": tec.get("tolerance_c", 0.1),
            "duration_s": tec.get("settle_duration_s", 10),
            "timeout_s": tec.get("settle_timeout_s", 120),
        }
    if bias.get("enabled"):
        stab_config["bias_settle"] = {
            "delay_s": bias.get("settle_delay_s", 2.0),
        }

    phases.append(RecipePhase(
        phase_type=PhaseType.STABILIZATION.value,
        enabled=bool(stab_config),     # skip if nothing to stabilize
        config=stab_config,
    ))

    # 4. Acquisition — capture data
    acq_config: Dict[str, Any] = {
        "type": acquisition_type,
    }
    if acquisition_type == "grid" and scan:
        acq_config["grid"] = scan
    elif acquisition_type in ("transient", "movie") and cube:
        acq_config["cube"] = cube
    if camera.get("inter_phase_delay_s"):
        acq_config["inter_phase_delay_s"] = camera["inter_phase_delay_s"]

    phases.append(RecipePhase(
        phase_type=PhaseType.ACQUISITION.value,
        config=acq_config,
    ))

    # 5. Validation — verify data quality
    phases.append(RecipePhase(
        phase_type=PhaseType.VALIDATION.value,
        config={
            "checks": ["snr_minimum", "no_saturation"],
            "snr_minimum_db": 10,
        },
        retry=RetryPolicy(max_retries=1, on_exhaust="warn_continue"),
    ))

    # 6. Analysis — process captured data
    analysis_config: Dict[str, Any] = {
        "threshold_k": analysis.get("threshold_k", 5.0),
        "fail_hotspot_count": analysis.get("fail_hotspot_count", 3),
        "fail_peak_k": analysis.get("fail_peak_k", 20.0),
        "fail_area_fraction": analysis.get("fail_area_fraction", 0.05),
        "warn_hotspot_count": analysis.get("warn_hotspot_count", 1),
        "warn_peak_k": analysis.get("warn_peak_k", 10.0),
        "warn_area_fraction": analysis.get("warn_area_fraction", 0.01),
    }
    phases.append(RecipePhase(
        phase_type=PhaseType.ANALYSIS.value,
        config=analysis_config,
    ))

    # 7. Output — save, export, report
    phases.append(RecipePhase(
        phase_type=PhaseType.OUTPUT.value,
        config={
            "auto_save": True,
        },
    ))

    return phases


# ================================================================== #
#  v1 → v2 migration                                                  #
# ================================================================== #

def _migrate_v1_to_v2(d: dict) -> dict:
    """Convert a v1 flat recipe dict to v2 phase-based structure.

    The v1 format has top-level ``camera``, ``acquisition``, ``analysis``,
    ``bias``, ``tec`` dicts with hardware parameters.  We map these into
    the v2 phase sequence.
    """
    cam_raw = d.get("camera", {})
    acq_raw = d.get("acquisition", {})
    ana_raw = d.get("analysis", {})
    bias_raw = d.get("bias", {})
    tec_raw = d.get("tec", {})

    # Map v1 scan_type to v2 acquisition_type
    scan_type = d.get("scan_type", "single")
    acq_type_map = {"autoscan": "grid", "single": "single_point",
                    "transient": "transient"}
    acq_type = acq_type_map.get(scan_type, "single_point")

    camera = {
        "exposure_us": cam_raw.get("exposure_us", 5000),
        "gain_db": cam_raw.get("gain_db", 0),
        "n_frames": cam_raw.get("n_frames", 16),
    }
    if cam_raw.get("roi"):
        camera["roi"] = cam_raw["roi"]
    if acq_raw.get("inter_phase_delay_s"):
        camera["inter_phase_delay_s"] = acq_raw["inter_phase_delay_s"]

    modality = acq_raw.get("modality", "thermoreflectance")

    fpga = {}  # v1 didn't store FPGA params in recipe

    bias = {
        "enabled": bias_raw.get("enabled", False),
        "voltage_v": bias_raw.get("voltage_v", 0),
        "current_a": bias_raw.get("current_a", 0),
    }
    tec = {
        "enabled": tec_raw.get("enabled", False),
        "setpoint_c": tec_raw.get("setpoint_c", 25.0),
    }
    analysis = {
        "threshold_k": ana_raw.get("threshold_k", 5.0),
        "fail_hotspot_count": ana_raw.get("fail_hotspot_count", 3),
        "fail_peak_k": ana_raw.get("fail_peak_k", 20.0),
        "fail_area_fraction": ana_raw.get("fail_area_fraction", 0.05),
        "warn_hotspot_count": ana_raw.get("warn_hotspot_count", 1),
        "warn_peak_k": ana_raw.get("warn_peak_k", 10.0),
        "warn_area_fraction": ana_raw.get("warn_area_fraction", 0.01),
    }

    phases = _build_standard_phases(
        camera=camera,
        fpga=fpga,
        bias=bias,
        tec=tec,
        modality=modality,
        acquisition_type=acq_type,
        analysis=analysis,
    )

    # Migrate v1 variables (dotted field paths) to v2 OperatorVariable objects
    v1_vars = d.get("variables", [])
    variables = []
    if isinstance(v1_vars, list):
        for v in v1_vars:
            if isinstance(v, str):
                variables.append(_migrate_v1_variable(v))
            elif isinstance(v, dict):
                variables.append(v)  # already v2 format

    result = {
        "version":          CURRENT_RECIPE_VERSION,
        "uid":              d.get("uid", str(uuid.uuid4())[:8]),
        "label":            d.get("label", ""),
        "description":      d.get("description", ""),
        "created_at":       d.get("created_at", ""),
        "profile_uid":      d.get("profile_uid", ""),
        "profile_name":     d.get("profile_name", ""),
        "phases":           [p.to_dict() for p in phases],
        "acquisition_type": acq_type,
        "variables":        variables,
        "locked":           d.get("locked", False),
        "approved_by":      d.get("approved_by", ""),
        "approved_at":      d.get("approved_at", ""),
        "notes":            d.get("notes", ""),
        "tags":             d.get("tags", []),
    }
    return result


# v1 dotted field paths → v2 OperatorVariable dicts
_V1_VARIABLE_MAP: Dict[str, dict] = {
    "camera.exposure_us": {
        "field_path": "hardware_setup.camera.exposure_us",
        "display_label": "Exposure",
        "value_type": "float",
        "unit": "us",
        "min_value": 1,
        "max_value": 1000000,
    },
    "camera.gain_db": {
        "field_path": "hardware_setup.camera.gain_db",
        "display_label": "Gain",
        "value_type": "float",
        "unit": "dB",
        "min_value": 0,
        "max_value": 48,
    },
    "camera.n_frames": {
        "field_path": "hardware_setup.camera.n_frames",
        "display_label": "Frames",
        "value_type": "int",
        "unit": "",
        "min_value": 1,
        "max_value": 1000,
    },
    "acquisition.inter_phase_delay_s": {
        "field_path": "acquisition.inter_phase_delay_s",
        "display_label": "Inter-phase delay",
        "value_type": "float",
        "unit": "s",
        "min_value": 0,
        "max_value": 60,
    },
    "analysis.threshold_k": {
        "field_path": "analysis.threshold_k",
        "display_label": "Threshold",
        "value_type": "float",
        "unit": "°C",
        "min_value": 0.001,
        "max_value": 1000,
    },
    "analysis.fail_peak_k": {
        "field_path": "analysis.fail_peak_k",
        "display_label": "Fail: peak ΔT",
        "value_type": "float",
        "unit": "°C",
        "min_value": 0,
        "max_value": 1000,
    },
    "bias.voltage_v": {
        "field_path": "hardware_setup.bias.voltage_v",
        "display_label": "Voltage",
        "value_type": "float",
        "unit": "V",
    },
    "bias.current_a": {
        "field_path": "hardware_setup.bias.current_a",
        "display_label": "Current",
        "value_type": "float",
        "unit": "A",
    },
    "tec.setpoint_c": {
        "field_path": "hardware_setup.tec.setpoint_c",
        "display_label": "Temperature setpoint",
        "value_type": "float",
        "unit": "°C",
    },
}


def _migrate_v1_variable(dotted_path: str) -> dict:
    """Convert a v1 dotted field path to a v2 OperatorVariable dict."""
    if dotted_path in _V1_VARIABLE_MAP:
        return dict(_V1_VARIABLE_MAP[dotted_path])
    # Unknown variable — preserve as-is with minimal metadata
    return {
        "field_path": dotted_path,
        "display_label": dotted_path.split(".")[-1].replace("_", " ").title(),
        "value_type": "float",
        "unit": "",
    }


# ================================================================== #
#  Hardware requirements inference                                     #
# ================================================================== #

def infer_requirements(recipe: Recipe) -> List[HardwareRequirement]:
    """Infer hardware requirements from a recipe's phase configs.

    Examines the hardware_setup phase to determine which devices
    are needed.  Returns a list of HardwareRequirement objects.
    This is called automatically by factory methods; the result
    can also be edited manually in the Recipe Builder.
    """
    reqs: List[HardwareRequirement] = []
    hw = recipe.get_phase_config(PhaseType.HARDWARE_SETUP.value)
    if not hw:
        return reqs

    # Camera — infer type from modality
    modality = hw.get("modality", "thermoreflectance")
    if modality in ("thermoreflectance", "hybrid", "opp"):
        reqs.append(HardwareRequirement(
            device_type="camera_tr",
            label="TR Camera",
        ))
    if modality in ("ir_lockin", "hybrid"):
        reqs.append(HardwareRequirement(
            device_type="camera_ir",
            label="IR Camera",
        ))

    # FPGA — always required for modulated measurements
    if hw.get("fpga") or modality in ("thermoreflectance", "ir_lockin", "hybrid"):
        reqs.append(HardwareRequirement(
            device_type="fpga",
            label="FPGA Modulation Controller",
        ))

    # Bias source
    bias = hw.get("bias", {})
    if bias.get("enabled"):
        reqs.append(HardwareRequirement(
            device_type="bias",
            label="Bias / Current Source",
        ))

    # TEC
    tec = hw.get("tec", {})
    if tec.get("enabled"):
        reqs.append(HardwareRequirement(
            device_type="tec",
            label="TEC Controller",
        ))

    # BILT pulse generator
    bilt = hw.get("bilt", {})
    if bilt:
        reqs.append(HardwareRequirement(
            device_type="bilt",
            label="BILT Pulse Generator",
        ))

    # Stage — required for grid scans
    acq = recipe.get_phase_config(PhaseType.ACQUISITION.value)
    if acq.get("type") == "grid":
        reqs.append(HardwareRequirement(
            device_type="stage",
            label="Motorised XY Stage",
        ))

    return reqs


# ================================================================== #
#  Hardware requirement validation                                     #
# ================================================================== #

# Maps device_type → (app_state attribute, human label for messages)
_DEVICE_TYPE_CHECKS: Dict[str, tuple] = {
    "camera_tr": ("cam",    "TR Camera"),
    "camera_ir": ("ir_cam", "IR Camera"),
    "fpga":      ("fpga",   "FPGA Modulation Controller"),
    "bias":      ("bias",   "Bias / Current Source"),
    "tec":       ("tecs",   "TEC Controller"),          # list — check len > 0
    "stage":     ("stage",  "Motorised XY Stage"),
    "bilt":      ("bias",   "BILT Pulse Generator"),    # BILT uses bias driver
    "ldd":       ("ldd",    "Laser Diode Driver"),
    "gpio":      ("gpio",   "Arduino / LED Selector"),
    "prober":    ("prober", "Probe Station Chuck"),
    "turret":    ("turret", "Motorised Objective Turret"),
}


def validate_requirements(
    recipe: Recipe,
    app_state,
) -> List[tuple]:
    """Check recipe hardware requirements against live hardware.

    Parameters
    ----------
    recipe : Recipe
        The recipe to validate.
    app_state
        The ApplicationState singleton (or any object with the
        standard hardware driver attributes).

    Returns
    -------
    list of (HardwareRequirement, bool)
        Each tuple is (requirement, is_satisfied).  The UI can use
        this to show ready/missing badges and block the Run button.
    """
    results = []
    for req in recipe.requirements:
        check = _DEVICE_TYPE_CHECKS.get(req.device_type)
        if check is None:
            # Unknown device type — can't validate, assume missing
            results.append((req, False))
            continue

        attr_name, _label = check
        driver = getattr(app_state, attr_name, None)

        # Special case: tecs is a list
        if req.device_type == "tec":
            satisfied = isinstance(driver, list) and len(driver) > 0
        else:
            satisfied = driver is not None

        results.append((req, satisfied))
    return results


def get_missing_requirements(
    recipe: Recipe,
    app_state,
    *,
    include_optional: bool = False,
) -> List[HardwareRequirement]:
    """Return only the unsatisfied requirements.

    Parameters
    ----------
    include_optional : bool
        If False (default), only mandatory missing requirements are
        returned.  If True, optional missing requirements are included.
    """
    missing = []
    for req, satisfied in validate_requirements(recipe, app_state):
        if not satisfied:
            if req.optional and not include_optional:
                continue
            missing.append(req)
    return missing


def can_run(recipe: Recipe, app_state) -> bool:
    """Return True if all mandatory requirements are satisfied."""
    return len(get_missing_requirements(recipe, app_state)) == 0


def format_missing_message(missing: List[HardwareRequirement]) -> str:
    """Build a user-facing message listing missing hardware.

    Example output::

        This recipe requires hardware that is not detected:

          - TR Camera — not connected
          - TEC Controller — not connected

        If you have this hardware, check that devices are
        attached and powered on.
    """
    if not missing:
        return ""
    lines = ["This recipe requires hardware that is not detected:\n"]
    for req in missing:
        label = req.label or req.device_type
        lines.append(f"  \u2022 {label} \u2014 not connected")
    lines.append("")
    lines.append(
        "If you have this hardware, check that devices are "
        "attached and powered on.")
    return "\n".join(lines)
