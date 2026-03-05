"""
hardware/requirements_resolver.py

Capability-based operation readiness resolver.

Maps each acqusition operation to the set of devices it requires (hard
requirement) and the set it benefits from (optional / degraded mode
allowed without them).  Given the current app_state, returns an
:class:`OperationReadiness` that the UI can use to:

  • Block the start button (required device missing → not ready)
  • Show a degraded-mode warning (optional device missing → degraded)
  • Log and record into the run manifest (degraded_mode, optional_devices_missing)

Canonical operation names are exported as module-level constants so
callers never use bare strings.

Usage::

    from hardware.requirements_resolver import check_readiness, OP_SCAN
    from hardware.app_state import app_state

    rdns = check_readiness(OP_SCAN, app_state)
    if not rdns.ready:
        show_error(rdns.blocked_reason)
    elif rdns.degraded:
        show_warning(rdns.degraded_reason)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ── Canonical operation identifiers ──────────────────────────────────────────

OP_LIVE      = "live"
OP_ACQUIRE   = "acquire"
OP_SCAN      = "scan"
OP_MOVIE     = "movie"
OP_TRANSIENT = "transient"
OP_CALIBRATE = "calibrate"

_ALL_OPS = (OP_LIVE, OP_ACQUIRE, OP_SCAN, OP_MOVIE, OP_TRANSIENT, OP_CALIBRATE)


# ── Requirements table ───────────────────────────────────────────────────────
# (required_device_types, optional_device_types)
# Device types must match the attribute names used in _state_map below.

_REQUIREMENTS: Dict[str, Tuple[List[str], List[str]]] = {
    OP_LIVE:      (["camera"],           ["fpga", "bias"]),
    OP_ACQUIRE:   (["camera"],           ["fpga", "bias", "tec"]),
    OP_SCAN:      (["camera", "stage"],  ["fpga", "bias", "tec"]),
    OP_MOVIE:     (["camera"],           ["fpga", "bias"]),
    OP_TRANSIENT: (["camera"],           ["fpga", "bias", "tec"]),
    OP_CALIBRATE: (["camera"],           ["tec"]),
}

# Human-readable device labels for error messages.
_DEVICE_LABELS: Dict[str, str] = {
    "camera": "Camera",
    "fpga":   "FPGA",
    "bias":   "Bias Source",
    "stage":  "Stage",
    "tec":    "TEC Controller",
    "prober": "Prober",
}


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class OperationReadiness:
    """
    Result of :func:`check_readiness`.

    Attributes
    ----------
    operation       : str      — operation that was checked
    ready           : bool     — False → start must be blocked
    degraded        : bool     — True → ready but running without optional devices
    blocked_reason  : str      — human-readable, non-empty only when ready=False
    degraded_reason : str      — human-readable, non-empty only when degraded=True
    required_missing  : list   — device types that are required but absent
    optional_missing  : list   — device types that are optional but absent
    """
    operation:        str
    ready:            bool
    degraded:         bool = False
    blocked_reason:   str  = ""
    degraded_reason:  str  = ""
    required_missing: List[str] = field(default_factory=list)
    optional_missing: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialisable snapshot for run manifests."""
        return {
            "operation":        self.operation,
            "ready":            self.ready,
            "degraded":         self.degraded,
            "blocked_reason":   self.blocked_reason,
            "degraded_reason":  self.degraded_reason,
            "required_missing": self.required_missing,
            "optional_missing": self.optional_missing,
        }


# ── Resolver ─────────────────────────────────────────────────────────────────

def check_readiness(operation: str, app_state) -> OperationReadiness:
    """
    Derive operation readiness from the current *app_state*.

    Returns :class:`OperationReadiness` with:

    * ``ready=True,  degraded=False`` — all required + optional devices present
    * ``ready=True,  degraded=True``  — required present, some optional absent
    * ``ready=False``                 — required device(s) missing → must block

    Parameters
    ----------
    operation : str
        One of the ``OP_*`` constants defined in this module.
    app_state : ApplicationState
        The global app_state singleton from ``hardware.app_state``.
    """
    if operation not in _REQUIREMENTS:
        # Unknown operation — fail safe: block with explanation.
        return OperationReadiness(
            operation=operation,
            ready=False,
            blocked_reason=f"Unknown operation '{operation}'"
        )

    required, optional = _REQUIREMENTS[operation]

    # Build a mapping of device_type → driver_object (None if absent).
    tec_present = bool(getattr(app_state, "tecs", None))  # list may be empty
    _state_map: Dict[str, object] = {
        "camera": getattr(app_state, "cam",    None),
        "fpga":   getattr(app_state, "fpga",   None),
        "bias":   getattr(app_state, "bias",   None),
        "stage":  getattr(app_state, "stage",  None),
        "tec":    tec_present or None,
        "prober": getattr(app_state, "prober", None),
    }

    required_missing = [d for d in required if not _state_map.get(d)]
    optional_missing = [d for d in optional if not _state_map.get(d)]

    if required_missing:
        labels = [_DEVICE_LABELS.get(d, d) for d in required_missing]
        return OperationReadiness(
            operation=operation,
            ready=False,
            blocked_reason=(
                f"Missing required device(s) for {operation}: "
                f"{', '.join(labels)}.  Connect via Device Manager."
            ),
            required_missing=required_missing,
            optional_missing=optional_missing,
        )

    degraded_reason = ""
    if optional_missing:
        labels = [_DEVICE_LABELS.get(d, d) for d in optional_missing]
        degraded_reason = (
            f"Running without optional device(s): {', '.join(labels)}.  "
            f"Some features may be unavailable."
        )

    return OperationReadiness(
        operation=operation,
        ready=True,
        degraded=bool(optional_missing),
        degraded_reason=degraded_reason,
        optional_missing=optional_missing,
    )
