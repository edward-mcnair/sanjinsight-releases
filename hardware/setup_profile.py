"""
hardware/setup_profile.py

SetupProfile — a serialisable snapshot of hardware settings that can be
saved, loaded, and selectively restored.

Settings are split into two safety tiers:

    SAFE    — read-before-write sensor/display settings that can be applied
              automatically without physical consequence (camera exposure, gain).

    PENDING — settings that control hardware outputs, heating/cooling, or
              stimulus generation.  These are *populated* into the UI controls
              on restore but NOT sent to hardware until the user clicks the
              existing Apply / Set / Enable button.  A small visual indicator
              flags sections that have pending values.

Stage settings are excluded entirely in v1.
Enable/disable states are never stored or restored.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

log = logging.getLogger(__name__)


# ── Safety classification ─────────────────────────────────────────────────────

SAFE_FIELDS = {
    "camera": {"exposure_us", "gain_db"},
}

PENDING_FIELDS = {
    "tec":  {"channels"},          # list of per-channel dicts
    "fpga": {"freq_hz", "duty_pct"},
    "bias": {"port_index", "mode", "level_v", "compliance_ma", "range_20ma"},
}

# Fields stored for identity matching, not for restore
IDENTITY_FIELDS = {"hardware_id"}


# ── Section dataclasses ───────────────────────────────────────────────────────

@dataclass
class CameraSettings:
    exposure_us: float = 0.0
    gain_db:     float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CameraSettings":
        return cls(
            exposure_us=d.get("exposure_us", 0.0),
            gain_db=d.get("gain_db", 0.0),
        )


@dataclass
class TECChannelSettings:
    setpoint_c:    float = 25.0
    ramp_rate_c_s: float = 0.0
    limit_low_c:   float = -40.0
    limit_high_c:  float = 150.0
    warn_margin_c: float = 5.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TECChannelSettings":
        return cls(
            setpoint_c=d.get("setpoint_c", 25.0),
            ramp_rate_c_s=d.get("ramp_rate_c_s", 0.0),
            limit_low_c=d.get("limit_low_c", -40.0),
            limit_high_c=d.get("limit_high_c", 150.0),
            warn_margin_c=d.get("warn_margin_c", 5.0),
        )


@dataclass
class TECSettings:
    channels: List[TECChannelSettings] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"channels": [ch.to_dict() for ch in self.channels]}

    @classmethod
    def from_dict(cls, d: dict) -> "TECSettings":
        chs = [TECChannelSettings.from_dict(c)
               for c in d.get("channels", [])]
        return cls(channels=chs)


@dataclass
class FPGASettings:
    freq_hz:  float = 1000.0
    duty_pct: float = 50.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FPGASettings":
        return cls(
            freq_hz=d.get("freq_hz", 1000.0),
            duty_pct=d.get("duty_pct", 50.0),
        )


@dataclass
class BiasSettings:
    port_index:    int   = 0
    mode:          str   = "voltage"   # "voltage" | "current"
    level_v:       float = 0.0
    compliance_ma: float = 10.0
    range_20ma:    bool  = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BiasSettings":
        return cls(
            port_index=d.get("port_index", 0),
            mode=d.get("mode", "voltage"),
            level_v=d.get("level_v", 0.0),
            compliance_ma=d.get("compliance_ma", 10.0),
            range_20ma=d.get("range_20ma", True),
        )


@dataclass
class HardwareIdentity:
    """Lightweight record of what hardware was connected when the profile
    was saved.  Used for mismatch warnings, not for gating restore."""
    camera_driver: str = ""
    camera_model:  str = ""
    tec_driver:    str = ""
    fpga_driver:   str = ""
    bias_driver:   str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HardwareIdentity":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


# ── Top-level profile ─────────────────────────────────────────────────────────

@dataclass
class SetupProfile:
    """Complete hardware setup profile.

    Attributes
    ----------
    name         : User-visible profile name ("" for last-used auto-profile).
    saved_at     : Unix timestamp of when the profile was captured.
    camera       : Camera exposure + gain.
    tec          : Per-channel TEC setpoints and limits.
    fpga         : Modulation frequency + duty cycle.
    bias         : Bias source mode, level, compliance, port.
    hardware_id  : Identity of connected hardware at save time.
    """
    name:        str               = ""
    saved_at:    float             = 0.0
    camera:      CameraSettings    = field(default_factory=CameraSettings)
    tec:         TECSettings       = field(default_factory=TECSettings)
    fpga:        FPGASettings      = field(default_factory=FPGASettings)
    bias:        BiasSettings      = field(default_factory=BiasSettings)
    hardware_id: HardwareIdentity  = field(default_factory=HardwareIdentity)

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "saved_at":    self.saved_at,
            "camera":      self.camera.to_dict(),
            "tec":         self.tec.to_dict(),
            "fpga":        self.fpga.to_dict(),
            "bias":        self.bias.to_dict(),
            "hardware_id": self.hardware_id.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SetupProfile":
        return cls(
            name=d.get("name", ""),
            saved_at=d.get("saved_at", 0.0),
            camera=CameraSettings.from_dict(d.get("camera", {})),
            tec=TECSettings.from_dict(d.get("tec", {})),
            fpga=FPGASettings.from_dict(d.get("fpga", {})),
            bias=BiasSettings.from_dict(d.get("bias", {})),
            hardware_id=HardwareIdentity.from_dict(d.get("hardware_id", {})),
        )

    def hardware_mismatches(self, current_id: HardwareIdentity) -> List[str]:
        """Return a list of human-readable mismatch descriptions.

        Compares the saved hardware identity against the currently connected
        hardware.  Empty list means no mismatches.
        """
        warnings: list[str] = []
        saved = self.hardware_id
        if saved.camera_driver and current_id.camera_driver:
            if saved.camera_driver != current_id.camera_driver:
                warnings.append(
                    f"Camera driver differs: profile={saved.camera_driver}, "
                    f"current={current_id.camera_driver}")
        if saved.tec_driver and current_id.tec_driver:
            if saved.tec_driver != current_id.tec_driver:
                warnings.append(
                    f"TEC driver differs: profile={saved.tec_driver}, "
                    f"current={current_id.tec_driver}")
        if saved.fpga_driver and current_id.fpga_driver:
            if saved.fpga_driver != current_id.fpga_driver:
                warnings.append(
                    f"FPGA driver differs: profile={saved.fpga_driver}, "
                    f"current={current_id.fpga_driver}")
        if saved.bias_driver and current_id.bias_driver:
            if saved.bias_driver != current_id.bias_driver:
                warnings.append(
                    f"Bias driver differs: profile={saved.bias_driver}, "
                    f"current={current_id.bias_driver}")
        return warnings


# ── Capture helper ────────────────────────────────────────────────────────────

def capture_current_settings(
    camera_tab=None,
    temperature_tab=None,
    fpga_tab=None,
    bias_tab=None,
    app_state=None,
    name: str = "",
) -> SetupProfile:
    """Read current settings from the live tab widgets and return a profile.

    Each tab argument is optional — missing tabs produce default sections.
    This function reads UI widget values only; it does NOT query hardware.
    """
    profile = SetupProfile(name=name, saved_at=time.time())

    # ── Camera ────────────────────────────────────────────────────────
    if camera_tab is not None:
        try:
            exp = camera_tab._exp_slider.value()
            gain = camera_tab._gain_slider.value() / 10.0
            profile.camera = CameraSettings(exposure_us=float(exp),
                                            gain_db=float(gain))
        except Exception as exc:
            log.debug("capture_current_settings: camera read failed: %s", exc)

    # ── TEC ───────────────────────────────────────────────────────────
    if temperature_tab is not None:
        try:
            channels = []
            for box in getattr(temperature_tab, "_panels", []):
                ch = TECChannelSettings(
                    setpoint_c=box._spin.value(),
                    ramp_rate_c_s=getattr(box, "_ramp_spin", None)
                                  and box._ramp_spin.value() or 0.0,
                    limit_low_c=getattr(box, "_min_spin", None)
                                and box._min_spin.value() or -40.0,
                    limit_high_c=getattr(box, "_max_spin", None)
                                 and box._max_spin.value() or 150.0,
                    warn_margin_c=getattr(box, "_warn_spin", None)
                                  and box._warn_spin.value() or 5.0,
                )
                channels.append(ch)
            profile.tec = TECSettings(channels=channels)
        except Exception as exc:
            log.debug("capture_current_settings: TEC read failed: %s", exc)

    # ── FPGA ──────────────────────────────────────────────────────────
    if fpga_tab is not None:
        try:
            profile.fpga = FPGASettings(
                freq_hz=fpga_tab._freq_spin.value(),
                duty_pct=fpga_tab._duty_spin.value(),
            )
        except Exception as exc:
            log.debug("capture_current_settings: FPGA read failed: %s", exc)

    # ── Bias ──────────────────────────────────────────────────────────
    if bias_tab is not None:
        try:
            mode = "voltage" if bias_tab._mode_bg.checkedId() == 0 else "current"
            profile.bias = BiasSettings(
                port_index=bias_tab._port_combo.currentIndex(),
                mode=mode,
                level_v=bias_tab._level_spin.value(),
                compliance_ma=bias_tab._comp_spin.value(),
                range_20ma=getattr(bias_tab, "_range_20ma_cb", None)
                           is not None and bias_tab._range_20ma_cb.isChecked(),
            )
        except Exception as exc:
            log.debug("capture_current_settings: bias read failed: %s", exc)

    # ── Hardware identity ─────────────────────────────────────────────
    if app_state is not None:
        try:
            hw_id = HardwareIdentity()
            cam = getattr(app_state, "cam", None)
            if cam is not None:
                hw_id.camera_driver = getattr(cam, "driver_name", "") or ""
                hw_id.camera_model = getattr(cam, "model_name", "") or ""
            # TEC — take driver name from first tec if available
            tecs = getattr(app_state, "tecs", None) or []
            if tecs:
                hw_id.tec_driver = getattr(tecs[0], "driver_name", "") or ""
            fpga = getattr(app_state, "fpga", None)
            if fpga is not None:
                hw_id.fpga_driver = getattr(fpga, "driver_name", "") or ""
            bias = getattr(app_state, "bias", None)
            if bias is not None:
                hw_id.bias_driver = getattr(bias, "driver_name", "") or ""
            profile.hardware_id = hw_id
        except Exception as exc:
            log.debug("capture_current_settings: hw identity read failed: %s", exc)

    return profile


# ── Restore helpers ───────────────────────────────────────────────────────────

class RestoreReport:
    """Tracks what was applied vs. populated during a profile restore."""

    def __init__(self):
        self.applied: list[str]  = []   # settings sent to hardware
        self.pending: list[str]  = []   # settings populated in UI only
        self.skipped: list[str]  = []   # sections skipped (no tab/hardware)
        self.warnings: list[str] = []   # hardware mismatch warnings

    @property
    def has_pending(self) -> bool:
        return len(self.pending) > 0

    def summary(self) -> str:
        parts = []
        if self.applied:
            parts.append(f"Applied: {', '.join(self.applied)}")
        if self.pending:
            parts.append(f"Pending (use Apply/Set buttons): {', '.join(self.pending)}")
        if self.skipped:
            parts.append(f"Skipped: {', '.join(self.skipped)}")
        if self.warnings:
            parts.append(f"Warnings: {'; '.join(self.warnings)}")
        return "\n".join(parts) if parts else "No settings restored."


def restore_profile(
    profile: SetupProfile,
    camera_tab=None,
    temperature_tab=None,
    fpga_tab=None,
    bias_tab=None,
    app_state=None,
) -> RestoreReport:
    """Restore a profile into the live tab widgets.

    SAFE settings (camera exposure/gain) are applied to hardware immediately.
    PENDING settings (TEC, FPGA, Bias) populate the UI controls but do NOT
    call hardware — the user must click the existing Apply/Set/Enable buttons.

    Signal blocking is used on all controls to prevent accidental hardware
    calls from valueChanged/sliderReleased signals during populate.

    Returns a RestoreReport describing what was applied, what is pending,
    and any mismatches detected.
    """
    report = RestoreReport()

    # ── Hardware mismatch check ───────────────────────────────────────
    if app_state is not None:
        current_id = HardwareIdentity()
        cam = getattr(app_state, "cam", None)
        if cam is not None:
            current_id.camera_driver = getattr(cam, "driver_name", "") or ""
        tecs = getattr(app_state, "tecs", None) or []
        if tecs:
            current_id.tec_driver = getattr(tecs[0], "driver_name", "") or ""
        fpga = getattr(app_state, "fpga", None)
        if fpga is not None:
            current_id.fpga_driver = getattr(fpga, "driver_name", "") or ""
        bias = getattr(app_state, "bias", None)
        if bias is not None:
            current_id.bias_driver = getattr(bias, "driver_name", "") or ""
        report.warnings = profile.hardware_mismatches(current_id)

    # ── Camera (SAFE — apply immediately) ─────────────────────────────
    if camera_tab is not None:
        try:
            _restore_camera(profile.camera, camera_tab)
            report.applied.append("camera exposure")
            report.applied.append("camera gain")
        except Exception as exc:
            log.warning("restore_profile: camera failed: %s", exc)
            report.skipped.append("camera")
    else:
        report.skipped.append("camera")

    # ── TEC (PENDING — populate only) ─────────────────────────────────
    if temperature_tab is not None and profile.tec.channels:
        try:
            _restore_tec(profile.tec, temperature_tab)
            report.pending.append("TEC setpoints")
            report.pending.append("TEC ramp rates")
            report.pending.append("TEC limits")
        except Exception as exc:
            log.warning("restore_profile: TEC failed: %s", exc)
            report.skipped.append("TEC")
    elif not profile.tec.channels:
        report.skipped.append("TEC (no channels in profile)")
    else:
        report.skipped.append("TEC")

    # ── FPGA (PENDING — populate only) ────────────────────────────────
    if fpga_tab is not None:
        try:
            _restore_fpga(profile.fpga, fpga_tab)
            report.pending.append("FPGA frequency")
            report.pending.append("FPGA duty cycle")
        except Exception as exc:
            log.warning("restore_profile: FPGA failed: %s", exc)
            report.skipped.append("FPGA")
    else:
        report.skipped.append("FPGA")

    # ── Bias (PENDING — populate only) ────────────────────────────────
    if bias_tab is not None:
        try:
            _restore_bias(profile.bias, bias_tab)
            report.pending.append("bias port")
            report.pending.append("bias level")
            report.pending.append("bias compliance")
        except Exception as exc:
            log.warning("restore_profile: bias failed: %s", exc)
            report.skipped.append("bias")
    else:
        report.skipped.append("bias")

    return report


# ── Per-section restore (private) ─────────────────────────────────────────────

def _restore_camera(settings: CameraSettings, tab) -> None:
    """Apply camera exposure and gain directly to hardware.

    Blocks slider signals to prevent the sliderReleased handler from
    double-applying, then calls the hardware setter explicitly.
    """
    # Exposure
    slider = tab._exp_slider
    slider.blockSignals(True)
    try:
        slider.setValue(int(settings.exposure_us))
    finally:
        slider.blockSignals(False)
    # Explicitly apply to hardware (the safe path)
    tab._do_exp(int(settings.exposure_us), _from_sync=True)

    # Gain
    gain_slider = tab._gain_slider
    gain_slider.blockSignals(True)
    try:
        gain_slider.setValue(int(settings.gain_db * 10))
    finally:
        gain_slider.blockSignals(False)
    tab._on_gain(_from_sync=True)


def _restore_tec(settings: TECSettings, tab) -> None:
    """Populate TEC spinboxes WITHOUT calling hardware.

    Signal blocking prevents any accidental side-effects.
    The user must click the existing 'Set' button to apply.
    """
    panels = getattr(tab, "_panels", [])
    for i, ch in enumerate(settings.channels):
        if i >= len(panels):
            break
        box = panels[i]

        # Setpoint
        if hasattr(box, "_spin"):
            box._spin.blockSignals(True)
            try:
                box._spin.setValue(ch.setpoint_c)
            finally:
                box._spin.blockSignals(False)

        # Ramp rate
        if hasattr(box, "_ramp_spin") and box._ramp_spin is not None:
            box._ramp_spin.blockSignals(True)
            try:
                box._ramp_spin.setValue(ch.ramp_rate_c_s)
            finally:
                box._ramp_spin.blockSignals(False)

        # Safety limits
        for attr, val in [("_min_spin", ch.limit_low_c),
                          ("_max_spin", ch.limit_high_c),
                          ("_warn_spin", ch.warn_margin_c)]:
            spin = getattr(box, attr, None)
            if spin is not None:
                spin.blockSignals(True)
                try:
                    spin.setValue(val)
                finally:
                    spin.blockSignals(False)

    # Mark the tab as having pending profile values
    tab._profile_pending = True


def _restore_fpga(settings: FPGASettings, tab) -> None:
    """Populate FPGA spinboxes WITHOUT calling hardware.

    Signal blocking prevents valueChanged side-effects.
    The user must click 'Apply Only' or 'Start Modulation' to apply.
    """
    tab._freq_spin.blockSignals(True)
    try:
        tab._freq_spin.setValue(settings.freq_hz)
    finally:
        tab._freq_spin.blockSignals(False)

    tab._duty_spin.blockSignals(True)
    try:
        tab._duty_spin.setValue(settings.duty_pct)
    finally:
        tab._duty_spin.blockSignals(False)

    # Mark the tab as having pending profile values
    tab._profile_pending = True


def _restore_bias(settings: BiasSettings, tab) -> None:
    """Populate bias controls WITHOUT calling hardware.

    Signal blocking prevents port/mode change side-effects from
    triggering validation-only handlers. The user must click
    'Apply Settings' or 'Output ON' to apply.
    """
    # Port
    tab._port_combo.blockSignals(True)
    try:
        if settings.port_index < tab._port_combo.count():
            tab._port_combo.setCurrentIndex(settings.port_index)
    finally:
        tab._port_combo.blockSignals(False)

    # Mode (voltage=0, current=1)
    mode_id = 0 if settings.mode == "voltage" else 1
    mode_btn = tab._mode_bg.button(mode_id)
    if mode_btn is not None:
        tab._mode_bg.blockSignals(True)
        try:
            mode_btn.setChecked(True)
        finally:
            tab._mode_bg.blockSignals(False)

    # Level
    tab._level_spin.blockSignals(True)
    try:
        tab._level_spin.setValue(settings.level_v)
    finally:
        tab._level_spin.blockSignals(False)

    # Compliance
    tab._comp_spin.blockSignals(True)
    try:
        tab._comp_spin.setValue(settings.compliance_ma)
    finally:
        tab._comp_spin.blockSignals(False)

    # 20 mA range checkbox
    range_cb = getattr(tab, "_range_20ma_cb", None)
    if range_cb is not None:
        range_cb.blockSignals(True)
        try:
            range_cb.setChecked(settings.range_20ma)
        finally:
            range_cb.blockSignals(False)

    # Mark the tab as having pending profile values
    tab._profile_pending = True
