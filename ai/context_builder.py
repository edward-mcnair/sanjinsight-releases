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
        data: dict = {"tab": self._active_tab}

        # Camera
        try:
            cam = app_state.cam
            if cam is not None:
                data["cam"] = {
                    "connected": True,
                    "exposure_us": getattr(cam, "exposure_us", None),
                    "gain_db": getattr(cam, "gain_db", None),
                }
            else:
                data["cam"] = {"connected": False}
        except Exception:
            data["cam"] = {"connected": False}

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
            data["fpga"] = {"connected": False}

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
            data["stage"] = {"connected": False}

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
            data["bias"] = {"connected": False}

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
            pass

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
                pass

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
                pass

        return json.dumps(_strip_none(data), separators=(",", ":"))


def _strip_none(obj):
    """Recursively remove None-valued keys from dicts."""
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj
