"""
ui/tabs/temperature_tab.py

TemperatureTab — TEC temperature control with live readouts, plots, and safety limits.

Architecture
------------
Each TEC controller gets its own ``TecPanel`` widget, displayed as a
separate tab inside a ``QTabWidget``.  Shared infrastructure (Chuck
temperature, error banner, empty-state) lives in the outer
``TemperatureTab`` wrapper.

TecPanel layout
~~~~~~~~~~~~~~~
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
    QHBoxLayout, QGroupBox, QFrame, QStackedWidget, QScrollArea,
    QTabWidget)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal

from hardware.app_state    import app_state
from ui.widgets.temp_plot  import TempPlot
from ui.widgets.more_options import MoreOptionsPanel
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.widgets.tab_helpers import inner_tab_qss
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after

# Approximate TEC temperature ramp rate (°C per minute).
# Used for the stabilization time estimate shown in the UI.
_TEC_RAMP_RATE_C_PER_MIN = 0.5

# Chuck stability criteria matching config default
_CHUCK_STAB_TOLERANCE_C  = 0.5   # °C band
_CHUCK_STAB_DURATION_S   = 5.0   # seconds within band


# ═══════════════════════════════════════════════════════════════════════
# TecPanel — self-contained control surface for one TEC controller
# ═══════════════════════════════════════════════════════════════════════

class TecPanel(QWidget):
    """Full control panel for a single TEC device.

    Contains readouts, temperature history plot, setpoint controls,
    ramp speed, and safety limits.  Previously built inline by
    ``TemperatureTab._build_tec()``.
    """

    def __init__(
        self,
        tec_index: int,
        display_name: str = "",
        hw_service=None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tec_index = tec_index
        self._hw = hw_service

        if not display_name:
            display_name = f"TEC {tec_index + 1}"

        main = QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(10)

        # ── Alarm banner (hidden by default) ─────────────────────────
        alarm_banner = QWidget()
        alarm_banner.setVisible(False)
        _dng  = PALETTE['danger']
        _warn = PALETTE['warning']
        _surf = PALETTE['surface']
        _sur2 = PALETTE['surface2']
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
        self._alarm_banner   = alarm_banner
        self._alarm_msg_lbl  = ab_msg
        self._alarm_icon_lbl = ab_icon
        self._alarm_ack_btn  = ab_ack
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
        self._warn_banner   = warn_banner
        self._warn_msg_lbl  = wb_msg
        self._warn_icon_lbl = wb_icon
        main.addWidget(warn_banner)

        # ── Readouts ─────────────────────────────────────────────────
        top = QHBoxLayout()
        actual_w = self._readout_widget("ACTUAL",      "--",       "accent")
        target_w = self._readout_widget("SETPOINT",    "--",       "warning")
        power_w  = self._readout_widget("OUTPUT",      "--",       "cta")
        state_w  = self._readout_widget("STATUS",      "UNKNOWN",  "textSub")
        ready_w  = self._readout_widget("ACQUISITION", "CHECKING", "textDim")

        self._actual_lbl = actual_w._val
        self._target_lbl = target_w._val
        self._power_lbl  = power_w._val
        self._state_lbl  = state_w._val
        self._ready_lbl  = ready_w._val

        for w in [actual_w, target_w, power_w, state_w, ready_w]:
            top.addWidget(w)
        main.addLayout(top)

        # ── Plot ──────────────────────────────────────────────────────
        self._plot = TempPlot(h=166)
        main.addWidget(self._plot)

        # ── Setpoint controls ─────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Target (°C)"))
        spin = QDoubleSpinBox()
        spin.setRange(-40, 150)
        spin.setValue(25.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setFixedWidth(80)
        self._spin = spin
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
                lambda _, v=val, s=spin: (
                    s.setValue(v), self._set_target(v)))

        ctrl.addStretch()
        en_btn  = QPushButton("Enable")
        dis_btn = QPushButton("Disable")
        self._en_btn  = en_btn
        self._dis_btn = dis_btn
        en_btn.setMinimumWidth(85)
        dis_btn.setMinimumWidth(85)
        _acc2 = PALETTE['accent']
        _dng2 = PALETTE['danger']
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

        # ── Ramp speed (protects DUT from thermal shock) ──────────────
        ramp_row = QHBoxLayout()
        ramp_row.addWidget(QLabel("Ramp (°C/s)"))
        ramp_spin = QDoubleSpinBox()
        ramp_spin.setRange(0.0, 50.0)
        ramp_spin.setValue(0.0)
        ramp_spin.setSingleStep(0.5)
        ramp_spin.setDecimals(1)
        ramp_spin.setFixedWidth(80)
        ramp_spin.setToolTip(
            "Temperature ramp rate in °C per second.\n"
            "0 = disabled (instant setpoint change).\n"
            "Non-zero values slew to the target gradually,\n"
            "protecting the DUT from thermal shock.\n"
            "Supported on Meerstetter TEC-1089 only.")
        self._ramp_spin = ramp_spin
        ramp_row.addWidget(ramp_spin)

        ramp_set_btn = QPushButton("Set Ramp")
        ramp_set_btn.setFixedWidth(80)
        ramp_set_btn.clicked.connect(
            lambda _: self._set_ramp_speed(self._ramp_spin.value()))
        ramp_row.addWidget(ramp_set_btn)

        ramp_hint = QLabel("0 = disabled (Meerstetter only)")
        ramp_hint.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['caption']}pt;")
        ramp_row.addWidget(ramp_hint)
        ramp_row.addStretch()
        main.addLayout(ramp_row)

        # ── Safety limits (collapsible Advanced section) ──────────────
        lim_panel = MoreOptionsPanel("Safety Limits", section_key="temperature_safety")

        lim_row = QHBoxLayout()

        min_spin = QDoubleSpinBox()
        min_spin.setRange(-40, 148)
        min_spin.setValue(-20.0)
        min_spin.setSingleStep(1.0)
        min_spin.setDecimals(1)
        min_spin.setFixedWidth(105)
        min_spin.setPrefix("min ")
        min_spin.setSuffix(" °C")

        max_spin = QDoubleSpinBox()
        max_spin.setRange(-38, 150)
        max_spin.setValue(85.0)
        max_spin.setSingleStep(1.0)
        max_spin.setDecimals(1)
        max_spin.setFixedWidth(105)
        max_spin.setPrefix("max ")
        max_spin.setSuffix(" °C")

        warn_spin = QDoubleSpinBox()
        warn_spin.setRange(0.5, 20.0)
        warn_spin.setValue(5.0)
        warn_spin.setSingleStep(0.5)
        warn_spin.setDecimals(1)
        warn_spin.setMinimumWidth(120)
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

        self._min_spin  = min_spin
        self._max_spin  = max_spin
        self._warn_spin = warn_spin

        # Update plot limits immediately with defaults
        self._plot.set_limits(-20.0, 85.0, 5.0)

        main.addStretch()

        # ── Wire ──────────────────────────────────────────────────────
        set_btn.clicked.connect(
            lambda _: self._set_target(spin.value()))
        en_btn.clicked.connect( lambda _: self._enable())
        dis_btn.clicked.connect(lambda _: self._disable())
        apply_btn.clicked.connect(lambda _: self._apply_limits())
        ab_ack.clicked.connect(lambda _: self._acknowledge_alarm())

    # ── Readout factory ──────────────────────────────────────────────

    @staticmethod
    def _readout_widget(label: str, initial: str, pal_key: str) -> QWidget:
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
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val     = val
        w._pal_key = pal_key
        return w

    # ── Live data update ─────────────────────────────────────────────

    def update_status(self, status) -> None:
        """Push a new TEC status snapshot to this panel."""
        if status.error:
            self._actual_lbl.setText("ERR")
            self._state_lbl.setText(status.error[:20])
            self._state_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            self._ready_lbl.setText("ERROR ✗")
            self._ready_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            return
        self._actual_lbl.setText(f"{status.actual_temp:.2f} °C")
        self._target_lbl.setText(f"{status.target_temp:.1f} °C")
        self._power_lbl.setText( f"{status.output_power:.2f} W")
        if not status.enabled:
            _sub = PALETTE['textSub']
            _dim = PALETTE['textDim']
            self._state_lbl.setText("DISABLED")
            self._state_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{_sub};")
            self._ready_lbl.setText("○  Disabled")
            self._ready_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{_dim};")
        elif status.stable:
            self._state_lbl.setText("STABLE ✓")
            self._state_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
            self._ready_lbl.setText("READY ✓")
            self._ready_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
        else:
            diff  = status.actual_temp - status.target_temp
            arrow = "▼" if diff > 0 else "▲"
            eta_min = abs(diff) / _TEC_RAMP_RATE_C_PER_MIN
            eta_s   = int(eta_min * 60)
            eta_str = f"~{eta_s // 60}:{eta_s % 60:02d}"
            self._state_lbl.setText(f"SETTLING {arrow}  {eta_str}")
            self._state_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
            self._ready_lbl.setText(f"{eta_str} remaining")
            self._ready_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
        self._plot.push(status.actual_temp, status.target_temp)

    # ── Alarm / warning ──────────────────────────────────────────────

    def show_alarm(self, message: str) -> None:
        self._alarm_msg_lbl.setText(message)
        self._alarm_banner.setVisible(True)
        self._warn_banner.setVisible(False)
        self._actual_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; color:{PALETTE['danger']};")

    def show_warning(self, message: str) -> None:
        self._warn_msg_lbl.setText(message)
        self._warn_banner.setVisible(True)
        self._actual_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; color:{PALETTE['warning']};")

    def clear_alarm(self) -> None:
        self._alarm_banner.setVisible(False)
        self._warn_banner.setVisible(False)
        self._actual_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; color:{PALETTE['accent']};")

    # ── Hardware actions ─────────────────────────────────────────────

    def _set_target(self, val: float, _from_sync: bool = False) -> None:
        idx = self._tec_index
        if self._hw:
            self._hw.tec_set_target(idx, val)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].set_target(val)
        if not _from_sync:
            from ui.app_signals import signals
            signals.tec_setpoint_changed.emit(idx, float(val), "temperature_tab")

    def _enable(self) -> None:
        idx   = self._tec_index
        guard = app_state.get_tec_guard(idx)
        if guard and guard.is_alarmed:
            return
        if self._hw:
            self._hw.tec_enable(idx)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].enable()

    def _disable(self) -> None:
        idx = self._tec_index
        if self._hw:
            self._hw.tec_disable(idx)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs):
                _tecs[idx].disable()

    def _set_ramp_speed(self, degrees_per_second: float) -> None:
        idx = self._tec_index
        if self._hw:
            self._hw.tec_set_ramp_speed(idx, degrees_per_second)
        else:
            _tecs = app_state.tecs
            if _tecs and idx < len(_tecs) and hasattr(_tecs[idx], 'set_ramp_speed'):
                _tecs[idx].set_ramp_speed(degrees_per_second)

    def _apply_limits(self) -> None:
        idx         = self._tec_index
        temp_min    = self._min_spin.value()
        temp_max    = self._max_spin.value()
        warn_margin = self._warn_spin.value()
        self._plot.set_limits(temp_min, temp_max, warn_margin)
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.update_limits(temp_min, temp_max, warn_margin)

    def _acknowledge_alarm(self) -> None:
        idx   = self._tec_index
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.acknowledge()
        self.clear_alarm()

    # ── Theme ────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P    = PALETTE
        acc  = P['accent']
        dng  = P['danger']
        warn = P['warning']
        surf = P['surface']
        sur2 = P['surface2']

        def _rgb(h):
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        ar, ag, ab = _rgb(acc)
        dr, dg, db = _rgb(dng)

        self._en_btn.setStyleSheet(
            f"QPushButton {{ background:rgba({ar},{ag},{ab},0.13); color:{acc}; "
            f"border:1px solid rgba({ar},{ag},{ab},0.35); border-radius:4px; padding:0 8px; }}"
            f"QPushButton:hover {{ background:rgba({ar},{ag},{ab},0.22); }}")
        self._dis_btn.setStyleSheet(
            f"QPushButton {{ background:rgba({dr},{dg},{db},0.13); color:{dng}; "
            f"border:1px solid rgba({dr},{dg},{db},0.35); border-radius:4px; padding:0 8px; }}"
            f"QPushButton:hover {{ background:rgba({dr},{dg},{db},0.22); }}")
        self._alarm_banner.setStyleSheet(
            f"background:{dng}22; border:1px solid {dng}; border-radius:3px;")
        self._alarm_icon_lbl.setStyleSheet(
            f"color:{dng}; font-size:{FONT['readoutSm']}pt;")
        self._alarm_msg_lbl.setStyleSheet(
            f"color:{dng}; font-size:{FONT['body']}pt;")
        self._alarm_ack_btn.setStyleSheet(
            f"QPushButton {{ background:{surf}; color:{dng}; "
            f"border:1px solid {dng}66; border-radius:3px; "
            f"font-size:{FONT['label']}pt; padding: 0 10px; }}"
            f"QPushButton:hover {{ background:{sur2}; }}")
        self._warn_banner.setStyleSheet(
            f"background:{warn}22; border:1px solid {warn}66; border-radius:3px;")
        self._warn_icon_lbl.setStyleSheet(
            f"color:{warn}; font-size:{FONT['heading']}pt;")
        self._warn_msg_lbl.setStyleSheet(
            f"color:{warn}; font-size:{FONT['label']}pt;")
        for attr, pal_key in [
            ("_actual_lbl", "accent"),
            ("_target_lbl", "warning"),
            ("_power_lbl",  "cta"),
            ("_state_lbl",  "textSub"),
            ("_ready_lbl",  "textDim"),
        ]:
            lbl = getattr(self, attr, None)
            if lbl:
                lbl.setStyleSheet(
                    f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; "
                    f"color:{P[pal_key]};")


# ═══════════════════════════════════════════════════════════════════════
# TemperatureTab — outer routing surface (unchanged public API)
# ═══════════════════════════════════════════════════════════════════════

class TemperatureTab(QWidget):

    open_device_manager = pyqtSignal()
    navigate_requested = pyqtSignal(str)

    def __init__(self, n_tecs: int, hw_service=None, has_chuck: bool = False):
        super().__init__()
        self._hw        = hw_service
        self._has_chuck = has_chuck

        # Chuck stability tracking (software-side, no HW flag from chuck driver)
        self._chuck_in_band_since: float | None = None

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Guidance cards (Guided mode) — scrollable area ────────
        _cards = get_section_cards("temperature")
        def _body(cid):
            for c in _cards:
                if c["card_id"] == cid:
                    return c["body"]
            return ""

        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "temperature.overview",
            "Getting Started with Temperature",
            _body("temperature.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "temperature.setup",
            "Set a Stable Baseline",
            _body("temperature.setup"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setMaximumHeight(200)
        self._cards_scroll.setWidget(self._cards_widget)
        self._cards_scroll.setVisible(False)
        outer.addWidget(self._cards_scroll)

        for c in (self._overview_card, self._guide_card1):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Temperature", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "Temperature Controller", "TEC",
            "Connect a TEC controller in Device Manager to enable "
            "temperature control and monitoring."))

        # Page 1: full controls (tab widget + chuck section)
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Error banner (hidden until a device error occurs)
        from ui.widgets.device_error_banner import DeviceErrorBanner
        self._error_banner = DeviceErrorBanner()
        self._error_banner.device_manager_clicked.connect(
            self.open_device_manager.emit)
        root.addWidget(self._error_banner)

        # ── Per-TEC tab widget ───────────────────────────────────────
        self._tec_tabs = QTabWidget()
        self._tec_tabs.setDocumentMode(True)
        self._tec_tabs.setStyleSheet(inner_tab_qss())

        self._panels: list[TecPanel] = []
        _default_info = [
            ("TEC-1089", "Meerstetter TEC-1089"),
            ("ATEC-302", "ATEC-302"),
        ]
        for i in range(n_tecs):
            if i < len(_default_info):
                tab_label, full_name = _default_info[i]
            else:
                tab_label, full_name = f"TEC {i + 1}", f"TEC {i + 1}"
            panel = TecPanel(i, display_name=full_name, hw_service=hw_service)
            self._panels.append(panel)
            self._tec_tabs.addTab(panel, tab_label)

        root.addWidget(self._tec_tabs, 1)

        # ── Chuck Temperature (TCAT) section (shared, outside tabs) ──
        self._chuck_box = self._build_chuck()
        root.addWidget(self._chuck_box)
        self._chuck_box.setVisible(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)  # empty state until device connects

        outer.addWidget(self._workflow_footer)

    def _build_empty_state(self, title: str, device: str, tip: str) -> QWidget:
        from ui.widgets.empty_state import build_empty_state
        return build_empty_state(
            title=f"{title} Not Connected",
            description=tip,
            on_action=self.open_device_manager,
        )

    def set_hardware_available(self, available: bool) -> None:
        """Switch between empty state (page 0) and full controls (page 1)."""
        self._stack.setCurrentIndex(1 if available else 0)

    # ── Public routing API (unchanged signatures) ────────────────────

    def update_tec(self, index: int, status) -> None:
        """Route a TEC status update to the correct panel."""
        if index < len(self._panels):
            self._panels[index].update_status(status)

    def show_alarm(self, index: int, message: str) -> None:
        if index < len(self._panels):
            self._panels[index].show_alarm(message)

    def show_warning(self, index: int, message: str) -> None:
        if index < len(self._panels):
            self._panels[index].show_warning(message)

    def clear_alarm(self, index: int) -> None:
        if index < len(self._panels):
            self._panels[index].clear_alarm()

    # ── Device error banner ──────────────────────────────────────────

    def show_device_error(self, key: str, name: str, message: str) -> None:
        self._error_banner.show_error(key, name, message)

    def clear_device_error(self) -> None:
        self._error_banner.clear()

    # ── Tab label management ─────────────────────────────────────────

    def set_tab_label(self, index: int, label: str) -> None:
        """Update the tab label for a TEC panel (e.g. with device identity)."""
        if 0 <= index < self._tec_tabs.count():
            self._tec_tabs.setTabText(index, label)

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
        _dim = PALETTE['textDim']
        nc_lbl = QLabel("Not configured")
        nc_lbl.setAlignment(Qt.AlignCenter)
        nc_lbl.setStyleSheet(
            f"color:{_dim}; font-size:{FONT['body']}pt; padding:8px;")
        box._not_configured_lbl = nc_lbl
        main.addWidget(nc_lbl)

        # ── Live readout row ──────────────────────────────────────────
        readout_row = QHBoxLayout()
        readout_row.setSpacing(16)

        cur_w  = TecPanel._readout_widget("CHUCK TEMP", "--", "accent")
        box._chuck_actual_lbl = cur_w._val
        readout_row.addWidget(cur_w)

        tgt_w  = TecPanel._readout_widget("TARGET", "--", "warning")
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
        _dim2 = PALETTE['textDim']
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
        _bdr = PALETTE['border']
        sep.setStyleSheet(f"color:{_bdr};")
        box._chuck_sep = sep

        # ── Assemble: separator first, then the row ───────────────────
        main.addWidget(sep)
        main.addLayout(readout_row)

        # Store references for show/hide
        box._readout_row_w = readout_row
        box._tgt_ctrl_w    = tgt_ctrl_w

        # Initial state: hide live content, show "not configured"
        sep.setVisible(False)
        tgt_ctrl_w.setVisible(False)
        cur_w.setVisible(False)
        tgt_w.setVisible(False)
        stab_w.setVisible(False)

        box._cur_readout_w  = cur_w
        box._tgt_readout_w  = tgt_w
        box._stab_readout_w = stab_w

        return box

    def _chuck_set_target(self, val: float) -> None:
        try:
            chuck = getattr(app_state, "chuck", None)
            if chuck is not None:
                chuck.set_target(val)
        except Exception:
            log.debug("TemperatureTab._chuck_set_target: could not set chuck target",
                      exc_info=True)

    def update_chuck(self, temp_c: float | None, stable: bool = False) -> None:
        """Update the Chuck Temperature (TCAT) display."""
        box = self._chuck_box

        if temp_c is None:
            box._not_configured_lbl.setVisible(True)
            box._chuck_sep.setVisible(False)
            box._cur_readout_w.setVisible(False)
            box._tgt_readout_w.setVisible(False)
            box._stab_readout_w.setVisible(False)
            box._tgt_ctrl_w.setVisible(False)
            self._chuck_in_band_since = None
            return

        box._not_configured_lbl.setVisible(False)
        box._chuck_sep.setVisible(True)
        box._cur_readout_w.setVisible(True)
        box._tgt_readout_w.setVisible(True)
        box._stab_readout_w.setVisible(True)
        box._tgt_ctrl_w.setVisible(True)

        box._chuck_actual_lbl.setText(f"{temp_c:.2f} °C")
        box._chuck_target_lbl.setText(f"{box._chuck_spin.value():.1f} °C")

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

        is_stable = stable or sw_stable

        if is_stable:
            _grn = PALETTE['success']
            box._chuck_stab_dot.setText("●")
            box._chuck_stab_dot.setStyleSheet(
                f"font-size:{FONT['readoutLg']}pt; color:{_grn};")
            box._chuck_stab_dot.setToolTip(
                f"Chuck stable: within ±{_CHUCK_STAB_TOLERANCE_C}°C "
                f"for ≥{_CHUCK_STAB_DURATION_S:.0f}s")
        else:
            _dim = PALETTE['textDim']
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

    # ── Workspace mode ────────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        is_guided = (mode == "guided")
        self._guide_card1.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._overview_card.setVisible(not is_guided)
        self._update_cards_scroll_visibility()

    def _update_cards_scroll_visibility(self) -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1))
        self._cards_scroll.setVisible(any_visible)

    # ── Theme ────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P = PALETTE
        # Refresh sub-tab styling
        self._tec_tabs.setStyleSheet(inner_tab_qss())
        # Guidance cards
        for c in (self._overview_card, self._guide_card1):
            if hasattr(c, "_apply_styles"):
                c._apply_styles()
        self._workflow_footer._apply_styles()
        # Delegate to each TEC panel
        for panel in self._panels:
            panel._apply_styles()

        # ── Chuck box ─────────────────────────────────────────────────
        chuck = getattr(self, "_chuck_box", None)
        if chuck:
            nc = getattr(chuck, "_not_configured_lbl", None)
            if nc:
                nc.setStyleSheet(
                    f"color:{P['textDim']}; "
                    f"font-size:{FONT['body']}pt; padding:8px;")
            sep = getattr(chuck, "_chuck_sep", None)
            if sep:
                sep.setStyleSheet(f"color:{P['border']};")
            for attr, pal_key in [
                ("_chuck_actual_lbl", "accent"),
                ("_chuck_target_lbl", "warning"),
            ]:
                lbl = getattr(chuck, attr, None)
                if lbl:
                    lbl.setStyleSheet(
                        f"font-family:{MONO_FONT}; font-size:{FONT['readoutLg']}pt; "
                        f"color:{P[pal_key]};")
            dot = getattr(chuck, "_chuck_stab_dot", None)
            if dot:
                _dim3 = P['textDim']
                dot.setStyleSheet(
                    f"font-size:{FONT['readoutLg']}pt; color:{_dim3};")

    def _readout_widget(self, label, initial, pal_key):
        """Backward-compatible readout factory (delegates to TecPanel)."""
        return TecPanel._readout_widget(label, initial, pal_key)
