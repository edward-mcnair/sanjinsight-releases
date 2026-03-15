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

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGroupBox)
from PyQt5.QtCore    import Qt

from hardware.app_state    import app_state
from ui.widgets.temp_plot  import TempPlot
from ui.widgets.collapsible_panel import CollapsiblePanel
from ui.theme import FONT, PALETTE, scaled_qss

# Approximate TEC temperature ramp rate (°C per minute).
# Used for the stabilization time estimate shown in the UI.
_TEC_RAMP_RATE_C_PER_MIN = 0.5


class TemperatureTab(QWidget):
    def __init__(self, n_tecs: int, hw_service=None):
        super().__init__()
        self._hw = hw_service
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._panels = []
        labels = ["TEC 1 — Meerstetter TEC-1089", "TEC 2 — ATEC-302"]
        for i in range(n_tecs):
            p = self._build_tec(labels[i] if i < len(labels) else f"TEC {i+1}", i)
            root.addWidget(p)
            self._panels.append(p)

        root.addStretch()

    def _build_tec(self, title, tec_index):
        box = QGroupBox(title)
        main = QVBoxLayout(box)

        # ── Alarm banner (hidden by default) ─────────────────────────
        alarm_banner = QWidget()
        alarm_banner.setVisible(False)
        alarm_banner.setStyleSheet(
            "background:#330000; border:1px solid #ff4444; border-radius:3px;")
        ab_lay = QHBoxLayout(alarm_banner)
        ab_lay.setContentsMargins(10, 6, 10, 6)
        ab_icon = QLabel("⊗")
        ab_icon.setStyleSheet(f"color:#ff4444; font-size:{FONT['readoutSm']}pt;")
        ab_msg  = QLabel("Temperature alarm")
        ab_msg.setStyleSheet(f"color:#ff6666; font-size:{FONT['body']}pt;")
        ab_msg.setWordWrap(True)
        ab_ack  = QPushButton("Acknowledge")
        ab_ack.setFixedHeight(26)
        ab_ack.setStyleSheet(f"""
            QPushButton {{
                background:{PALETTE.get('surface','#2d2d2d')}; color:#ff9999;
                border:1px solid #ff444466; border-radius:3px;
                font-size:{FONT['label']}pt; padding: 0 10px;
            }}
            QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; color:#ffbbbb; }}
        """)
        ab_lay.addWidget(ab_icon)
        ab_lay.addWidget(ab_msg, 1)
        ab_lay.addWidget(ab_ack)
        box._alarm_banner  = alarm_banner
        box._alarm_msg_lbl = ab_msg
        box._alarm_ack_btn = ab_ack
        main.addWidget(alarm_banner)

        # ── Warning banner (hidden by default) ───────────────────────
        warn_banner = QWidget()
        warn_banner.setVisible(False)
        warn_banner.setStyleSheet(
            f"background:{PALETTE.get('surface','#2d2d2d')}; border:1px solid #ff990066; border-radius:3px;")
        wb_lay = QHBoxLayout(warn_banner)
        wb_lay.setContentsMargins(10, 4, 10, 4)
        wb_icon = QLabel("⚠")
        wb_icon.setStyleSheet(f"color:#ff9900; font-size:{FONT['heading']}pt;")
        wb_msg  = QLabel("Approaching limit")
        wb_msg.setStyleSheet(f"color:#ffaa44; font-size:{FONT['label']}pt;")
        wb_msg.setWordWrap(True)
        wb_lay.addWidget(wb_icon)
        wb_lay.addWidget(wb_msg, 1)
        box._warn_banner  = warn_banner
        box._warn_msg_lbl = wb_msg
        main.addWidget(warn_banner)

        # ── Readouts ─────────────────────────────────────────────────
        top = QHBoxLayout()
        actual_w = self._readout_widget("ACTUAL", "--", "#00d4aa")
        target_w = self._readout_widget("SETPOINT", "--", "#ffaa44")
        power_w  = self._readout_widget("OUTPUT", "--", "#6699ff")
        state_w  = self._readout_widget("STATUS", "UNKNOWN", "#555")
        ready_w  = self._readout_widget("ACQUISITION", "CHECKING", PALETTE["textDim"])

        box._actual_lbl = actual_w._val
        box._target_lbl = target_w._val
        box._power_lbl  = power_w._val
        box._state_lbl  = state_w._val
        box._ready_lbl  = ready_w._val

        for w in [actual_w, target_w, power_w, state_w, ready_w]:
            top.addWidget(w)
        main.addLayout(top)

        # ── Plot ──────────────────────────────────────────────────────
        plot = TempPlot(h=130)
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
        set_btn.setFixedWidth(50)
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
        en_btn.setFixedWidth(70)
        dis_btn.setFixedWidth(70)
        en_btn.setStyleSheet( "background:#003322; color:#00d4aa; border-color:#00d4aa;")
        dis_btn.setStyleSheet("background:#330000; color:#ff6666; border-color:#ff4444;")
        ctrl.addWidget(en_btn)
        ctrl.addWidget(dis_btn)
        main.addLayout(ctrl)

        # ── Safety limits (collapsible Advanced section) ──────────────
        lim_panel = CollapsiblePanel("Safety limits", start_collapsed=True)

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
        warn_spin.setFixedWidth(105)  # wide enough for "warn ±20.0 °C" on Windows
        warn_spin.setPrefix("warn ±")
        warn_spin.setSuffix(" °C")

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(55)

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

    def _apply_styles(self) -> None:
        P    = PALETTE
        acc  = P.get("accent",  "#00d4aa")
        dng  = P.get("danger",  "#ff5555")
        sur  = P.get("surface", "#1a1d28")
        for panel in getattr(self, "_panels", []):
            if hasattr(panel, "_en_btn"):
                panel._en_btn.setStyleSheet(
                    f"background:{acc}22; color:{acc}; border-color:{acc}55;")
            if hasattr(panel, "_dis_btn"):
                panel._dis_btn.setStyleSheet(
                    f"background:{dng}22; color:{dng}; border-color:{dng}55;")

    def _readout_widget(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def update_tec(self, index: int, status):
        if index >= len(self._panels):
            return
        p = self._panels[index]
        if status.error:
            p._actual_lbl.setText("ERR")
            p._state_lbl.setText(status.error[:20])
            p._state_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            p._ready_lbl.setText("ERROR ✗")
            p._ready_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['danger']};")
            return
        p._actual_lbl.setText(f"{status.actual_temp:.2f} °C")
        p._target_lbl.setText(f"{status.target_temp:.1f} °C")
        p._power_lbl.setText( f"{status.output_power:.2f} W")
        if not status.enabled:
            p._state_lbl.setText("DISABLED")
            p._state_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:#444;")
            p._ready_lbl.setText("○  Disabled")
            p._ready_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:#555;")
        elif status.stable:
            p._state_lbl.setText("STABLE ✓")
            p._state_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
            p._ready_lbl.setText("READY ✓")
            p._ready_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['accent']};")
        else:
            diff  = status.actual_temp - status.target_temp
            arrow = "▼" if diff > 0 else "▲"
            eta_min = abs(diff) / _TEC_RAMP_RATE_C_PER_MIN
            eta_s   = int(eta_min * 60)
            eta_str = f"~{eta_s // 60}:{eta_s % 60:02d}"
            p._state_lbl.setText(f"SETTLING {arrow}  {eta_str}")
            p._state_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
            p._ready_lbl.setText(f"{eta_str} remaining")
            p._ready_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readout']}pt; color:{PALETTE['warning']};")
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
            f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['danger']};")
        p.setStyleSheet("QGroupBox { border-color: #ff4444; }")

    def show_warning(self, index: int, message: str):
        """Show the warning banner for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._warn_msg_lbl.setText(message)
        p._warn_banner.setVisible(True)
        p._actual_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['warning']};")

    def clear_alarm(self, index: int):
        """Clear alarm/warning state for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._alarm_banner.setVisible(False)
        p._warn_banner.setVisible(False)
        p._actual_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['accent']};")
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
