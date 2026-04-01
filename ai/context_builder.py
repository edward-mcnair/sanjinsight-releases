"""
ai/context_builder.py

ContextBuilder — assembles a compact JSON instrument snapshot for the LLM.

Keeps token count < 800 by choosing flat keys and omitting nulls.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from hardware.app_state import app_state

if TYPE_CHECKING:
    from ai.metrics_service import MetricsService
    from ai.diagnostic_engine import DiagnosticEngine

log = logging.getLogger(__name__)


class ContextBuilder:
    """
    Assembles a compact JSON snapshot of the current instrument state.
    Safe to call from any thread.
    """

    def __init__(self, metrics: "MetricsService | None" = None):
        self._metrics      = metrics
        self._diagnostics: "DiagnosticEngine | None" = None
        self._active_tab: str = ""

    def set_active_tab(self, tab: str) -> None:
        self._active_tab = tab

    def set_metrics(self, metrics: "MetricsService") -> None:
        self._metrics = metrics

    def set_diagnostics(self, engine: "DiagnosticEngine") -> None:
        self._diagnostics = engine

    def build(self) -> str:
        """Return a compact JSON string describing current instrument state."""
        from ui.workspace import get_manager
        data: dict = {
            "tab": self._active_tab,
            "workspace_mode": get_manager().mode.value,
        }
        # Tracks which sections raised an exception; written into the JSON so
        # the LLM knows the context may be incomplete.
        _incomplete: list = []

        # Camera — adapts to active camera type (TR, IR, or future plugins)
        try:
            cam_type = getattr(app_state, "active_camera_type", "tr")
            cam = app_state.cam
            if cam is not None:
                cam_data: dict = {
                    "connected": True,
                    "type": cam_type,
                }
                # Include driver-reported camera_type if available
                driver_type = getattr(cam, "camera_type", None)
                if driver_type:
                    cam_data["driver_type"] = driver_type
                # Common attributes (present on most camera drivers)
                for attr in ("exposure_us", "gain_db", "fps"):
                    val = getattr(cam, attr, None)
                    if val is not None:
                        cam_data[attr] = val
                # Camera info (resolution, bit depth, model)
                info = getattr(cam, "info", None)
                if info is not None:
                    for attr in ("width", "height", "bit_depth", "model"):
                        val = getattr(info, attr, None)
                        if val is not None:
                            cam_data[attr] = val
                data["cam"] = cam_data
            else:
                data["cam"] = {"connected": False, "type": cam_type}
        except Exception:
            log.debug("ContextBuilder.build: camera section failed", exc_info=True)
            data["cam"] = {"connected": False}
            _incomplete.append("cam")

        # FPGA
        try:
            fpga = app_state.fpga
            if fpga is not None:
                data["fpga"] = {
                    "connected": True,
                    "running": getattr(fpga, "running", None),
                    "locked": getattr(fpga, "locked", None),
                    "freq_hz": getattr(fpga, "frequency", None),
                    "duty_pct": getattr(fpga, "duty_cycle", None),
                }
            else:
                data["fpga"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: FPGA section failed", exc_info=True)
            data["fpga"] = {"connected": False}
            _incomplete.append("fpga")

        # Stage
        try:
            stage = app_state.stage
            if stage is not None:
                pos = getattr(stage, "position", None)
                pos_dict = {k: v for k, v in vars(pos).items()} if pos is not None else None
                data["stage"] = {
                    "connected": True,
                    "homed": getattr(stage, "homed", None),
                    "pos_um": pos_dict,
                }
            else:
                data["stage"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: stage section failed", exc_info=True)
            data["stage"] = {"connected": False}
            _incomplete.append("stage")

        # Bias
        try:
            bias = app_state.bias
            if bias is not None:
                data["bias"] = {
                    "connected": True,
                    "enabled": getattr(bias, "enabled", None),
                    "mode": getattr(bias, "mode", None),
                    "level": getattr(bias, "level", None),
                }
            else:
                data["bias"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: bias section failed", exc_info=True)
            data["bias"] = {"connected": False}
            _incomplete.append("bias")

        # LDD (Laser Diode Driver — illumination source)
        try:
            ldd = app_state.ldd
            if ldd is not None:
                st = ldd.get_status()
                data["ldd"] = {
                    "connected":   True,
                    "enabled":     st.enabled,
                    "current_a":   round(st.actual_current_a, 3),
                    "voltage_v":   round(st.actual_voltage_v, 3),
                    "diode_temp_c": round(st.diode_temp_c, 1),
                    "mode":        st.mode,
                }
                if st.error:
                    data["ldd"]["error"] = st.error
            else:
                data["ldd"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: LDD section failed", exc_info=True)
            data["ldd"] = {"connected": False}
            _incomplete.append("ldd")

        # System model (EZ500 / NT220 / PT410A) — from config or auto-detected
        try:
            from ai.instrument_knowledge import SYSTEM_SPECS, system_spec
            model_key = getattr(app_state, "system_model", None)
            spec = system_spec(model_key) if model_key else None
            if spec is not None:
                data["system_model"] = {
                    "model":           spec.model,
                    "min_time_res_ns": spec.min_time_res_ns,
                    "sensor":          spec.sensor,
                    "illumination_nm": spec.illumination_nm,
                    "objectives":      spec.objectives,
                }
        except Exception:
            log.debug("ContextBuilder.build: system_model section failed", exc_info=True)
            _incomplete.append("system_model")

        # Active measurement profile (material + wavelength + C_T)
        try:
            prof = app_state.active_profile
            if prof is not None:
                data["profile"] = {
                    "material":      prof.material,
                    "wavelength_nm": prof.wavelength_nm,
                    "ct_value":      prof.ct_value,
                    "category":      prof.category,
                }
        except Exception:
            log.debug("ContextBuilder.build: profile section failed", exc_info=True)
            _incomplete.append("profile")

        # TECs
        try:
            tecs = app_state.tecs or []
            tec_data = []
            for i, tec in enumerate(tecs):
                if tec is not None:
                    tec_data.append({
                        "idx": i,
                        "enabled": getattr(tec, "enabled", None),
                        "setpoint_c": getattr(tec, "setpoint", None),
                        "actual_c": getattr(tec, "temperature", None),
                    })
            if tec_data:
                data["tecs"] = tec_data
        except Exception:
            log.debug("ContextBuilder.build: TECs section failed", exc_info=True)
            _incomplete.append("tecs")

        # Arduino GPIO / LED wavelength selector
        try:
            gpio = app_state.gpio
            if gpio is not None:
                gpio_data: dict = {"connected": True}
                st = gpio.get_status()
                gpio_data["active_led"] = st.active_led
                gpio_data["firmware"] = st.firmware_version
                channels = gpio.channels
                if channels:
                    gpio_data["led_channels"] = [
                        {"nm": ch.wavelength_nm, "label": ch.label}
                        for ch in channels
                    ]
                data["gpio"] = gpio_data
            else:
                data["gpio"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: GPIO section failed", exc_info=True)
            data["gpio"] = {"connected": False}
            _incomplete.append("gpio")

        # Active acquisition modality — always include so the AI adapts to
        # the measurement technique (TR, IR, or future modalities)
        try:
            modality = app_state.active_modality
            if modality:
                data["modality"] = modality
        except Exception:
            log.debug("ContextBuilder.build: modality section failed", exc_info=True)
            _incomplete.append("modality")

        # Prober (probe-station chuck — distinct from microscope scan stage)
        try:
            prober = app_state.prober
            if prober is not None:
                _pos = getattr(prober, '_pos', None)
                pos_dict = None
                if _pos is not None:
                    pos_dict = {
                        "x": round(getattr(_pos, 'x', 0.0), 1),
                        "y": round(getattr(_pos, 'y', 0.0), 1),
                        "z": round(getattr(_pos, 'z', 0.0), 1),
                    }
                _map = getattr(prober, '_map_size', (0, 0))
                data["prober"] = {
                    "connected": True,
                    "homed":    getattr(prober, '_homed', None),
                    "pos_um":   pos_dict,
                    "map_size": (f"{_map[0]}×{_map[1]}"
                                 if _map and _map[0] and _map[1] else None),
                }
            else:
                data["prober"] = {"connected": False}
        except Exception:
            log.debug("ContextBuilder.build: prober section failed", exc_info=True)
            data["prober"] = {"connected": False}
            _incomplete.append("prober")

        # Active objective (from motorized turret — drives FOV, pixel size, autofocus range)
        try:
            obj = app_state.active_objective
            if obj is not None:
                obj_data: dict = {
                    "mag":   obj.magnification,
                    "na":    obj.numerical_aperture,
                    "label": obj.label,
                }
                try:
                    obj_data["fov_um"] = round(obj.fov_um(), 1)
                    obj_data["px_um"]  = round(obj.px_size_um(), 4)
                except Exception:
                    log.debug("ContextBuilder.build: objective fov/px_size failed",
                              exc_info=True)
                data["objective"] = obj_data
            elif app_state.turret is not None:
                data["objective"] = {"connected": True}
        except Exception:
            log.debug("ContextBuilder.build: objective section failed", exc_info=True)
            _incomplete.append("objective")

        # Metrics snapshot
        if self._metrics is not None:
            try:
                snap = self._metrics.current_snapshot()
                data["metrics"] = {
                    "ready": snap.get("ready", False),
                    "issues": snap.get("issues", {}),
                }
                cam_metrics = snap.get("camera", {})
                if cam_metrics:
                    data["metrics"]["focus"] = cam_metrics.get("focus_score", None)
                    data["metrics"]["saturation_pct"] = cam_metrics.get("saturation_pct", None)
            except Exception:
                log.debug("ContextBuilder.build: metrics section failed", exc_info=True)
                _incomplete.append("metrics")

        # Diagnostic rule results — warn/fail only, compact format for token budget
        if self._diagnostics is not None:
            try:
                issues = self._diagnostics.active_issues()
                if issues:
                    data["rules"] = [
                        {
                            "id":   r.rule_id,
                            "sev":  r.severity,
                            "obs":  r.observed,
                            "hint": r.hint,
                        }
                        for r in issues
                    ]
            except Exception:
                log.debug("ContextBuilder.build: diagnostics section failed",
                          exc_info=True)
                _incomplete.append("diagnostics")

        # Inject fallback flag so the LLM knows some device state may be missing
        if _incomplete:
            data["context_incomplete"] = True
            log.debug("ContextBuilder.build: incomplete sections — %s",
                      ", ".join(_incomplete))

        return json.dumps(_strip_none(data), separators=(",", ":"))


def _strip_none(obj):
    """Recursively remove None-valued keys from dicts."""
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj
