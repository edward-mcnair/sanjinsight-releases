"""
ui/tabs/temperature_tab.py

TemperatureTab — TEC temperature control with live readouts, plots, and safety limits.

Layout per TEC
--------------
Basic (always visible)
  • Alarm / warning banners
  • ACTUAL / SETPOINT / OUTPUT / STATUS readouts
  • Temperature history plot
  • Setpoint spinbox + quick temperature buttons + Enable / Disable

Advanced — Safety limits (collapsible, hidden by default)
  • Min / max temperature limits, warning margin, Apply button
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGroupBox, QFrame, QStackedWidget, QScrollArea)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal

from hardware.app_state    import app_state
from ui.widgets.temp_plot  import TempPlot
from ui.widgets.more_options import MoreOptionsPanel
from ui.theme import FONT, PALETTE, scaled_qss
from ui.icons import make_icon_label, IC

# Approximate TEC temperature ramp rate (°C per minute).
# Used for the stabilization time estimate shown in the UI.
_TEC_RAMP_RATE_C_PER_MIN = 0.5

# Chuck stability criteria matching config default
_CHUCK_STAB_TOLERANCE_C  = 0.5   # °C band
_CHUCK_STAB_DURATION_S   = 5.0   # seconds within band


class TemperatureTab(QWidget):

    open_device_manager = pyqtSignal()

    def __init__(self, n_tecs: int, hw_service=None, has_chuck: bool = False):
        super().__init__()
        self._hw        = hw_service
        self._has_chuck = has_chuck

        # Chuck stability tracking (software-side, no HW flag from chuck driver)
        self._chuck_in_band_since: float | None = None

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "Temperature Controller", "TEC",
            "Connect a TEC controller in Device Manager to enable "
            "temperature control and monitoring."))

        # Page 1: full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._panels = []
        labels = ["TEC 1 — Meerstetter TEC-1089", "TEC 2 — ATEC-302"]
        for i in range(n_tecs):
            p = self._build_tec(labels[i] if i < len(labels) else f"TEC {i+1}", i)
            root.addWidget(p)
            self._panels.append(p)

        # ── Chuck Temperature (TCAT) section ─────────────────────────
        self._chuck_box = self._build_chuck()
        root.addWidget(self._chuck_box)
        # Show/hide based on whether chuck controller is configured
        self._chuck_box.setVisible(True)   # always render; update_chuck hides content if N/A

        root.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)  # empty state until device connects

    def _build_empty_state(self, title: str, device: str, tip: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon_lbl = make_icon_label(IC.LINK_OFF, color="#555555", size=64)
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(f"{title} Not Connected")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; font-weight: bold; color: #888;")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: #555;")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE.get('surface','#2d2d2d')}; color: #00d4aa;
                border: 1px solid #00d4aa66; border-radius: 5px;
                font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: {PALETTE.get('surface2','#3d3d3d')}; }}
        """)
        btn.clicked.connect(self.open_device_manager)

        lay.addStretch()
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addWidget(tip_lbl)
        lay.addSpacing(8)
        lay.addWidget(btn, 0, Qt.AlignCenter)
        lay.addStretch()
        return w

    def set_hardware_available(self, available: bool) -> None:
        """Switch between empty state (page 0) and full controls (page 1)."""
        self._stack.setCurrentIndex(1 if available else 0)

    def _build_tec(self, title, tec_index):
        box = QGroupBox(title)
        main = QVBoxLayout(box)

        # ── Alarm banner (hidden by default) ─────────────────────────
        alarm_banner = QWidget()
        alarm_banner.setVisible(False)
        _dng  = PALETTE.get("danger",   "#ff453a")
        _warn = PALETTE.get("warning",  "#ff9f0a")
        _surf = PALETTE.get("surface",  "#2d2d2d")
        _sur2 = PALETTE.get("surface2", "#3d3d3d")
        alarm_banner.setStyleSheet(
            f"background:{_dng}22; border:1px solid {_dng}; border-radius:3px;")
        ab_lay = QHBoxLayout(alarm_banner)
        ab_lay.setContentsMargins(10, 6, 10, 6)
        ab_icon = QLabel("⊗")
        ab_icon.setStyleSheet(f"color:{_dng}; font-size:{FONT['readoutSm']}pt;")
        ab_msg  = QLabel("Temperature alarm")
        ab_msg.setStyleSheet(f"color:{_dng}; font-size:{FONT['body']}pt;")
        ab_msg.setWordWrap(True)
        ab_ack  = QPushButton("Acknowledge")
        ab_ack.setFixedHeight(26)
        ab_ack.setStyleSheet(f"""
            QPushButton {{
                background:{_surf}; color:{_dng};
                border:1px solid {_dng}66; border-radius:3px;
                font-size:{FONT['label']}pt; padding: 0 10px;
            }}
            QPushButton:hover {{ background:{_sur2}; }}
        """)
        ab_lay.addWidget(ab_icon)
        ab_lay.addWidget(ab_msg, 1)
        ab_lay.addWidget(ab_ack)
        box._alarm_banner   = alarm_banner
        box._alarm_msg_lbl  = ab_msg
        box._alarm_icon_lbl = ab_icon
        box._alarm_ack_btn  = ab_ack
        main.addWidget(alarm_banner)

        # ── Warning banner (hidden by default) ───────────────────────
        warn_banner = QWidget()
        warn_banner.setVisible(False)
        warn_banner.setStyleSheet(
            f"background:{_warn}22; border:1px solid {_warn}66; border-radius:3px;")
        wb_lay = QHBoxLayout(warn_banner)
        wb_lay.setContentsMargins(10, 4, 10, 4)
        wb_icon = QLabel("⚠")
        wb_icon.setStyleSheet(f"color:{_warn}; font-size:{FONT['heading']}pt;")
        wb_msg  = QLabel("Approaching limit")
        wb_msg.setStyleSheet(f"color:{_warn}; font-size:{FONT['label']}pt;")
        wb_msg.setWordWrap(True)
        wb_lay.addWidget(wb_icon)
        wb_lay.addWidget(wb_msg, 1)
        box._warn_banner   = warn_banner
        box._warn_msg_lbl  = wb_msg
        box._warn_icon_lbl = wb_icon
        main.addWidget(warn_banner)

        # ── Readouts ─────────────────────────────────────────────────
        top = QHBoxLayout()
        actual_w = self._readout_widget("ACTUAL",      "--",       "accent")
        target_w = self._readout_widget("SETPOINT",    "--",       "warning")
        power_w  = self._readout_widget("OUTPUT",      "--",       "cta")
        state_w  = self._readout_widget("STATUS",      "UNKNOWN",  "textSub")
        ready_w  = self._readout_widget("ACQUISITION", "CHECKING", "textDim")

        box._actual_lbl = actual_w._val
        box._target_lbl = target_w._val
        box._power_lbl  = power_w._val
        box._state_lbl  = state_w._val
        box._ready_lbl  = ready_w._val

        for w in [actual_w, target_w, power_w, state_w, ready_w]:
            top.addWidget(w)
        main.addLayout(top)

        # ── Plot ──────────────────────────────────────────────────────
        plot = TempPlot(h=166)
        box._plot = plot
        main.addWidget(plot)

        # ── Setpoint controls ─────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Target (°C)"))
        spin = QDoubleSpinBox()
        spin.setRange(-40, 150)
        spin.setValue(25.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setFixedWidth(80)
        box._spin = spin
        ctrl.addWidget(spin)

        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(60)
        ctrl.addWidget(set_btn)

        ctrl.addSpacing(12)
        for lbl, val in [("-20°C",-20),("0°C",0),("25°C",25),
                          ("50°C",50),("85°C",85)]:
            b = QPushButton(lbl)
            b.setMinimumWidth(66)
            ctrl.addWidget(b)
            b.clicked.connect(
                lambda _, v=val, s=spin, box=box: (
                    s.setValue(v), self._set_target(box, v)))

        ctrl.addStretch()
        en_btn  = QPushButton("Enable")
        dis_btn = QPushButton("Disable")
        box._en_btn  = en_btn
        box._dis_btn = dis_btn
        en_btn.setMinimumWidth(85)
        dis_btn.setMinimumWidth(85)
        _acc2 = PALETTE.get("accent", "#00d4aa")
        _dng2 = PALETTE.get("danger", "#ff453a")
        _ar, _ag, _ab = int(_acc2[1:3],16), int(_acc2[3:5],16), int(_acc2[5:7],16)
        _dr, _dg, _db = int(_dng2[1:3],16), int(_dng2[3:5],16), int(_dng2[5:7],16)
        en_btn.setStyleSheet(
            f"QPushButton {{ background:rgba({_ar},{_ag},{_ab},0.13); color:{_acc2}; "
            f"border:1px solid rgba({_ar},{_ag},{_ab},0.35); border-radius:4px; padding:0 8px; }}"
            f"QPushButton:hover {{ background:rgba({_ar},{_ag},{_ab},0.22); }}")
        dis_btn.setStyleSheet(
            f"QPushButton {{ background:rgba({_dr},{_dg},{_db},0.13); color:{_dng2}; "
            f"border:1px solid rgba({_dr},{_dg},{_db},0.35); border-radius:4px; padding:0 8px; }}"
            f"QPushButton:hover {{ background:rgba({_dr},{_dg},{_db},0.22); }}")
        ctrl.addWidget(en_btn)
        ctrl.addWidget(dis_btn)
        main.addLayout(ctrl)

        # ── Safety limits (collapsible Advanced section) ──────────────
        lim_panel = MoreOptionsPanel("Safety Limits", section_key="temperature_safety")

        lim_row = QHBoxLayout()

        min_spin = QDoubleSpinBox()
        min_spin.setRange(-40, 148)
        min_spin.setValue(-20.0)
        min_spin.setSingleStep(1.0)
        min_spin.setDecimals(1)
        min_spin.setFixedWidth(105)  # wide enough for "min -20.0 °C" on Windows
        min_spin.setPrefix("min ")
        min_spin.setSuffix(" °C")

        max_spin = QDoubleSpinBox()
        max_spin.setRange(-38, 150)
        max_spin.setValue(85.0)
        max_spin.setSingleStep(1.0)
        max_spin.setDecimals(1)
        max_spin.setFixedWidth(105)  # wide enough for "max 150.0 °C" on Windows
        max_spin.setPrefix("max ")
        max_spin.setSuffix(" °C")

        warn_spin = QDoubleSpinBox()
        warn_spin.setRange(0.5, 20.0)
        warn_spin.setValue(5.0)
        warn_spin.setSingleStep(0.5)
        warn_spin.setDecimals(1)
        warn_spin.setMinimumWidth(120)  # wide enough for "warn ±20.0 °C" on Windows
        warn_spin.setPrefix("warn ±")
        warn_spin.setSuffix(" °C")

        apply_btn = QPushButton("Apply")
        apply_btn.setMinimumWidth(65)

        for w in [min_spin, max_spin, warn_spin]:
            w.setStyleSheet(f"font-size:{FONT['label']}pt;")

        lim_row.addWidget(min_spin)
        lim_row.addWidget(max_spin)
        lim_row.addWidget(warn_spin)
        lim_row.addWidget(apply_btn)
        lim_row.addStretch()
        lim_panel.addLayout(lim_row)
        main.addWidget(lim_panel)

        box._min_spin  = min_spin
        box._max_spin  = max_spin
        box._warn_spin = warn_spin
        box._tec_index = tec_index

        # Update plot limits immediately with defaults
        plot.set_limits(-20.0, 85.0, 5.0)

        # ── Wire ──────────────────────────────────────────────────────
        set_btn.clicked.connect(
            lambda _, s=spin, b=box: self._set_target(b, s.value()))
        en_btn.clicked.connect( lambda _, b=box: self._enable(b))
        dis_btn.clicked.connect(lambda _, b=box: self._disable(b))
        apply_btn.clicked.connect(lambda _, b=box: self._apply_limits(b))
        ab_ack.clicked.connect(lambda _, b=box: self._acknowledge_alarm(b))

        return box

    # ---------------------------------------------------------------- #
    #  Chuck Temperature (TCAT) section                                #
    # ---------------------------------------------------------------- #

    def _build_chuck(self) -> QGroupBox:
        """Build the Chuck Temperature (TCAT) display group."""
        box = QGroupBox("Chuck Temperature (TCAT)")
        main = QVBoxLayout(box)
        main.setContentsMargins(10, 8, 10, 10)
        main.setSpacing(8)

        # ── "Not configured" placeholder (shown when no chuck controller) ─
        _dim = PALETTE.get("textDim", "#999999")
        nc_lbl = QLabel("Not configured")
        nc_lbl.setAlignment(Qt.AlignCenter)
        nc_lbl.setStyleSheet(
            f"color:{_dim}; font-size:{FONT['body']}pt; padding:8px;")
        box._not_configured_lbl = nc_lbl
        main.addWidget(nc_lbl)

        # ── Live readout row ──────────────────────────────────────────
        readout_row = QHBoxLayout()
        readout_row.setSpacing(16)

        # Current temperature display
        cur_w  = self._readout_widget("CHUCK TEMP", "--", "accent")
        box._chuck_actual_lbl = cur_w._val
        readout_row.addWidget(cur_w)

        # Target temperature display (only meaningful when ATEC302 connected)
        tgt_w  = self._readout_widget("TARGET", "--", "warning")
        box._chuck_target_lbl = tgt_w._val
        readout_row.addWidget(tgt_w)

        # Stabilized indicator
        stab_w = QWidget()
        stab_v = QVBoxLayout(stab_w)
        stab_v.setAlignment(Qt.AlignCenter)
        stab_sub = QLabel("STABLE")
        stab_sub.setObjectName("sublabel")
        stab_sub.setAlignment(Qt.AlignCenter)
        stab_dot = QLabel("○")
        stab_dot.setAlignment(Qt.AlignCenter)
        _dim2 = PALETTE.get("textDim", "#999999")
        stab_dot.setStyleSheet(
            f"font-size:{FONT['readoutLg']}pt; color:{_dim2};")
        stab_v.addWidget(stab_sub)
        stab_v.addWidget(stab_dot)
        box._chuck_stab_dot = stab_dot
        readout_row.addWidget(stab_w)

        readout_row.addStretch()

        # ── Target spinbox (only shown when chuck controller active) ──
        tgt_ctrl_w = QWidget()
        tgt_ctrl_h = QHBoxLayout(tgt_ctrl_w)
        tgt_ctrl_h.setContentsMargins(0, 0, 0, 0)
        tgt_ctrl_h.setSpacing(6)
        tgt_ctrl_h.addWidget(QLabel("Target (°C)"))
        chuck_spin = QDoubleSpinBox()
        chuck_spin.setRange(-65, 250)
        chuck_spin.setValue(25.0)
        chuck_spin.setSingleStep(1.0)
        chuck_spin.setDecimals(1)
        chuck_spin.setFixedWidth(80)
        box._chuck_spin = chuck_spin
        tgt_ctrl_h.addWidget(chuck_spin)
        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(60)
        tgt_ctrl_h.addWidget(set_btn)
        set_btn.clicked.connect(lambda _: self._chuck_set_target(chuck_spin.value()))
        box._chuck_set_btn = set_btn
        readout_row.addWidget(tgt_ctrl_w)

        # ── Horizontal separator ──────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        _bdr = PALETTE.get("border", "#3a3a3a")
        sep.setStyleSheet(f"color:{_bdr};")
        box._chuck_sep = sep

        # ── Assemble: separator first, then the row ───────────────────
        main.addWidget(sep)
        main.addLayout(readout_row)

        # Store references for show/hide
        box._readout_row_w = readout_row   # layout — toggle via widgets visibility
        box._tgt_ctrl_w    = tgt_ctrl_w

        # Initial state: hide live content, show "not configured"
        sep.setVisible(False)
        tgt_ctrl_w.setVisible(False)
        cur_w.setVisible(False)
        tgt_w.setVisible(False)
        stab_w.setVisible(False)

        # Keep references
        box._cur_readout_w  = cur_w
        box._tgt_readout_w  = tgt_w
        box._stab_readout_w = stab_w

        return box

    def _chuck_set_target(self, val: float) -> None:
        """Send new target temperature to the chuck controller."""
        try:
            chuck = getattr(app_state, "chuck", None)
            if chuck is not None:
                chuck.set_target(val)
        except Exception:
            log.debug("TemperatureTab._chuck_set_target: could not set chuck target",
                      exc_info=True)

    def update_chuck(self, temp_c: float | None, stable: bool = False) -> None:
        """
        Update the Chuck Temperature (TCAT) display.

        Parameters
        ----------
        temp_c : float or None
            Current chuck temperature in °C.  Pass None to show "not configured".
        stable : bool
            True when the chuck reports it is within tolerance.
            If the chuck driver does not report a stable flag, callers may pass
            the result of the software-side stability check instead.
        """
        box = self._chuck_box

        if temp_c is None:
            # No chuck controller available — show placeholder
            box._not_configured_lbl.setVisible(True)
            box._chuck_sep.setVisible(False)
            box._cur_readout_w.setVisible(False)
            box._tgt_readout_w.setVisible(False)
            box._stab_readout_w.setVisible(False)
            box._tgt_ctrl_w.setVisible(False)
            self._chuck_in_band_since = None
            return

        # Chuck is available — hide placeholder, show live content
        box._not_configured_lbl.setVisible(False)
        box._chuck_sep.setVisible(True)
        box._cur_readout_w.setVisible(True)
        box._tgt_readout_w.setVisible(True)
        box._stab_readout_w.setVisible(True)

        # Show target spinbox only when a chuck controller is configured
        box._tgt_ctrl_w.setVisible(True)

        # ── Temperature readout ───────────────────────────────────────
        box._chuck_actual_lbl.setText(f"{temp_c:.2f} °C")

        # Update target label from spinbox value
        box._chuck_target_lbl.setText(f"{box._chuck_spin.value():.1f} °C")

        # ── Software-side stability check ─────────────────────────────
        # If the caller already resolved stability (e.g. from HW flag), use it.
        # Otherwise compute from tolerance + duration window.
        target = box._chuck_spin.value()
        within_band = abs(temp_c - target) <= _CHUCK_STAB_TOLERANCE_C
        if within_band:
            if self._chuck_in_band_since is None:
                self._chuck_in_band_since = time.monotonic()
            elapsed = time.monotonic() - self._chuck_in_band_since
            sw_stable = elapsed >= _CHUCK_STAB_DURATION_S
        else:
            self._chuck_in_band_since = None
            sw_stable = False

        # Hardware flag takes precedence if True; SW check is the fallback
        is_stable = stable or sw_stable

        # ── Stability indicator dot ───────────────────────────────────
        if is_stable:
            _grn = PALETTE.get("success", "#32d74b")
            box._chuck_stab_dot.setText("●")
            box._chuck_stab_dot.setStyleSheet(
                f"font-size:{FONT['readoutLg']}pt; color:{_grn};")
            box._chuck_stab_dot.setToolTip(
                f"Chuck stable: within ±{_CHUCK_STAB_TOLERANCE_C}°C "
                f"for ≥{_CHUCK_STAB_DURATION_S:.0f}s")
        else:
            _dim = PALETTE.get("textDim", "#999999")
            box._chuck_stab_dot.setText("○")
            box._chuck_stab_dot.setStyleSheet(
                f"font-size:{FONT['readoutLg']}pt; color:{_dim};")
            if within_band and self._chuck_in_band_since is not None:
                remaining = _CHUCK_STAB_DURATION_S - (
                    time.monotonic() - self._chuck_in_band_since)
                box._chuck_stab_dot.setToolTip(
                    f"Settling — {remaining:.0f}s until stable")
            else:
                diff = temp_c - target
                box._chuck_stab_dot.setToolTip(
                    f"Settling — Δ{diff:+.2f}°C from target")

    def _apply_styles(self) -> None:
        P    = PALETTE
        acc  = P.get("accent",  "#00d4aa")
        dng  = P.get("danger",  "#ff453a")
        warn = P.get("warning", "#ff9f0a")
        surf = P.get("surface", "#2d2d2d")
        sur2 = P.get("surface2","#3d3d3d")

        def _rgb(h):
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        ar, ag, ab = _rgb(acc)
        dr, dg, db = _rgb(dng)

        for panel in getattr(self, "_panels", []):
            # ── Enable / Disable buttons ──────────────────────────────
            if hasattr(panel, "_en_btn"):
                panel._en_btn.setStyleSheet(
                    f"QPushButton {{ background:rgba({ar},{ag},{ab},0.13); color:{acc}; "
                    f"border:1px solid rgba({ar},{ag},{ab},0.35); border-radius:4px; padding:0 8px; }}"
                    f"QPushButton:hover {{ background:rgba({ar},{ag},{ab},0.22); }}")
            if hasattr(panel, "_dis_btn"):
                panel._dis_btn.setStyleSheet(
                    f"QPushButton {{ background:rgba({dr},{dg},{db},0.13); color:{dng}; "
                    f"border:1px solid rgba({dr},{dg},{db},0.35); border-radius:4px; padding:0 8px; }}"
                    f"QPushButton:hover {{ background:rgba({dr},{dg},{db},0.22); }}")
            # ── Alarm banner ──────────────────────────────────────────
            if hasattr(panel, "_alarm_banner"):
                panel._alarm_banner.setStyleSheet(
                    f"background:{dng}22; border:1px solid {dng}; border-radius:3px;")
            if hasattr(panel, "_alarm_icon_lbl"):
                panel._alarm_icon_lbl.setStyleSheet(
                    f"color:{dng}; font-size:{FONT['readoutSm']}pt;")
            if hasattr(panel, "_alarm_msg_lbl"):
                panel._alarm_msg_lbl.setStyleSheet(
                    f"color:{dng}; font-size:{FONT['body']}pt;")
            if hasattr(panel, "_alarm_ack_btn"):
                panel._alarm_ack_btn.setStyleSheet(
                    f"QPushButton {{ background:{surf}; color:{dng}; "
                    f"border:1px solid {dng}66; border-radius:3px; "
                    f"font-size:{FONT['label']}pt; padding: 0 10px; }}"
                    f"QPushButton:hover {{ background:{sur2}; }}")
            # ── Warning banner ────────────────────────────────────────
            if hasattr(panel, "_warn_banner"):
                panel._warn_banner.setStyleSheet(
                    f"background:{warn}22; border:1px solid {warn}66; border-radius:3px;")
            if hasattr(panel, "_warn_icon_lbl"):
                panel._warn_icon_lbl.setStyleSheet(
                    f"color:{warn}; font-size:{FONT['heading']}pt;")
            if hasattr(panel, "_warn_msg_lbl"):
                panel._warn_msg_lbl.setStyleSheet(
                    f"color:{warn}; font-size:{FONT['label']}pt;")
            # ── Readout value labels (default/idle colours only) ──────
            for attr, pal_key in [
                ("_actual_lbl", "accent"),
                ("_target_lbl", "warning"),
                ("_power_lbl",  "cta"),
                ("_state_lbl",  "textSub"),
                ("_ready_lbl",  "textDim"),
            ]:
                lbl = getattr(panel, attr, None)
                if lbl:
                    lbl.setStyleSheet(
                        f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; "
                        f"color:{P.get(pal_key,'#00d4aa')};")

        # ── Chuck box ─────────────────────────────────────────────────
        chuck = getattr(self, "_chuck_box", None)
        if chuck:
            # "Not configured" label
            nc = getattr(chuck, "_not_configured_lbl", None)
            if nc:
                nc.setStyleSheet(
                    f"color:{P.get('textDim','#999999')}; "
                    f"font-size:{FONT['body']}pt; padding:8px;")
            # Separator colour
            sep = getattr(chuck, "_chuck_sep", None)
            if sep:
                sep.setStyleSheet(f"color:{P.get('border','#3a3a3a')};")
            # Readout labels
            for attr, pal_key in [
                ("_chuck_actual_lbl", "accent"),
                ("_chuck_target_lbl", "warning"),
            ]:
                lbl = getattr(chuck, attr, None)
                if lbl:
                    lbl.setStyleSheet(
                        f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; "
                        f"color:{P.get(pal_key,'#00d4aa')};")
            # Stability dot — colour preserved by update_chuck; just reset font
            dot = getattr(chuck, "_chuck_stab_dot", None)
            if dot:
                _dim3 = P.get("textDim", "#999999")
                dot.setStyleSheet(
                    f"font-size:{FONT['readoutLg']}pt; color:{_dim3};")

    def _readout_widget(self, label, initial, pal_key):
        """Create a readout widget.  pal_key is a PALETTE key (e.g. "accent")."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        color = PALETTE.get(pal_key, "#00d4aa")
        val.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val     = val
        w._pal_key = pal_key
        return w

    def update_tec(self, index: int, status):
        if index >= len(self._panels):
            return
        p = self._panels[index]
        if status.error:
            p._actual_lbl.setText("ERR")
            p._state_lbl.setText(status.error[:20])
            p._state_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            p._ready_lbl.setText("ERROR ✗")
            p._ready_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            return
        p._actual_lbl.setText(f"{status.actual_temp:.2f} °C")
        p._target_lbl.setText(f"{status.target_temp:.1f} °C")
        p._power_lbl.setText( f"{status.output_power:.2f} W")
        if not status.enabled:
            _sub = PALETTE.get("textSub", "#6a6a6a")
            _dim = PALETTE.get("textDim", "#999999")
            p._state_lbl.setText("DISABLED")
            p._state_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{_sub};")
            p._ready_lbl.setText("○  Disabled")
            p._ready_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{_dim};")
        elif status.stable:
            p._state_lbl.setText("STABLE ✓")
            p._state_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
            p._ready_lbl.setText("READY ✓")
            p._ready_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
        else:
            diff  = status.actual_temp - status.target_temp
            arrow = "▼" if diff > 0 else "▲"
            eta_min = abs(diff) / _TEC_RAMP_RATE_C_PER_MIN
            eta_s   = int(eta_min * 60)
            eta_str = f"~{eta_s // 60}:{eta_s % 60:02d}"
            p._state_lbl.setText(f"SETTLING {arrow}  {eta_str}")
            p._state_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
            p._ready_lbl.setText(f"{eta_str} remaining")
            p._ready_lbl.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
        p._plot.push(status.actual_temp, status.target_temp)

    def show_alarm(self, index: int, message: str):
        """Show the alarm banner for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._alarm_msg_lbl.setText(message)
        p._alarm_banner.setVisible(True)
        p._warn_banner.setVisible(False)
        p._actual_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['danger']};")
        p.setStyleSheet(f"QGroupBox {{ border-color: {PALETTE.get('danger','#ff453a')}; }}")

    def show_warning(self, index: int, message: str):
        """Show the warning banner for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._warn_msg_lbl.setText(message)
        p._warn_banner.setVisible(True)
        p._actual_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['warning']};")

    def clear_alarm(self, index: int):
        """Clear alarm/warning state for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._alarm_banner.setVisible(False)
        p._warn_banner.setVisible(False)
        p._actual_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['accent']};")
        p.setStyleSheet("")

    def _apply_limits(self, box):
        """Push updated limits to the ThermalGuard and TempPlot."""
        idx        = self._panels.index(box)
        temp_min   = box._min_spin.value()
        temp_max   = box._max_spin.value()
        warn_margin = box._warn_spin.value()

        # Update the chart
        box._plot.set_limits(temp_min, temp_max, warn_margin)

        # Update the guard
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.update_limits(temp_min, temp_max, warn_margin)

    def _acknowledge_alarm(self, box):
        """Acknowledge the alarm — clears latch, hides banner."""
        idx   = self._panels.index(box)
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.acknowledge()
        self.clear_alarm(idx)

    def _set_target(self, box, val):
        idx = self._panels.index(box)
        if self._hw:
            self._hw.tec_set_target(idx, val)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].set_target(val)

    def _enable(self, box):
        idx   = self._panels.index(box)
        guard = app_state.get_tec_guard(idx)
        if guard and guard.is_alarmed:
            return
        if self._hw:
            self._hw.tec_enable(idx)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].enable()

    def _disable(self, box):
        idx = self._panels.index(box)
        if self._hw:
            self._hw.tec_disable(idx)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].disable()
