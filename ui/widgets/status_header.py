"""
ui/widgets/status_header.py

_ModeToggle  — animated iOS-style Standard/Advanced toggle switch.
StatusHeader — top header bar with logo, mode toggle, device status dots, and E-Stop.
"""

from __future__ import annotations

import os
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal
from PyQt5.QtGui     import QPainter, QColor, QPen, QFont, QBrush


class _ModeToggle(QWidget):
    """
    Compact iOS-style toggle switch with STANDARD / ADVANCED labels.

    Left  (unchecked) = Standard   teal pill
    Right (checked)   = Advanced   blue pill

    Emits toggled(bool) — True means Advanced.
    """

    toggled = pyqtSignal(bool)

    _W, _H   = 160, 26          # total widget size
    _PAD     = 2                 # padding around pill
    _RADIUS  = 11                # pill corner radius

    _COL_STANDARD = QColor(0,  212, 170)   # teal
    _COL_ADVANCED = QColor(80, 120, 220)   # blue
    _COL_TRACK    = QColor(30,  30,  30)
    _COL_BORDER   = QColor(50,  50,  50)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._advanced  = False
        self._anim_pos  = 0.0      # 0.0 = standard, 1.0 = advanced
        self._timer     = QTimer(self)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Standard: guided 4-step wizard\n"
            "Advanced: full expert tab interface")

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def is_advanced(self) -> bool:
        return self._advanced

    def set_checked(self, advanced: bool, emit: bool = True):
        if advanced == self._advanced:
            return
        self._advanced = advanced
        self._timer.start()
        if emit:
            self.toggled.emit(advanced)

    # ---------------------------------------------------------------- #
    #  Animation                                                        #
    # ---------------------------------------------------------------- #

    def _tick(self):
        target = 1.0 if self._advanced else 0.0
        step   = 0.12
        if abs(self._anim_pos - target) < step:
            self._anim_pos = target
            self._timer.stop()
        else:
            self._anim_pos += step if target > self._anim_pos else -step
        self.update()

    # ---------------------------------------------------------------- #
    #  Painting                                                         #
    # ---------------------------------------------------------------- #

    def paintEvent(self, _):
        p  = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H   = self._W, self._H
        pad    = self._PAD
        r      = self._RADIUS

        # Track
        p.setPen(QPen(self._COL_BORDER, 1))
        p.setBrush(self._COL_TRACK)
        p.drawRoundedRect(0, 0, W, H, r + pad, r + pad)

        # Interpolate pill colour
        t   = self._anim_pos
        sc  = self._COL_STANDARD
        ac  = self._COL_ADVANCED
        col = QColor(
            int(sc.red()   + (ac.red()   - sc.red())   * t),
            int(sc.green() + (ac.green() - sc.green()) * t),
            int(sc.blue()  + (ac.blue()  - sc.blue())  * t))

        # Pill position — travels from left half to right half
        half      = W // 2
        pill_x    = pad + int((half - pad) * t)
        pill_w    = half - pad
        pill_rect = (pill_x, pad, pill_w, H - pad * 2)

        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(*pill_rect, r, r)

        # Labels
        p.setPen(Qt.NoPen)   # reset
        font = QFont("Helvetica", 11, QFont.Bold)
        p.setFont(font)

        # STANDARD label (left half)
        std_active = t < 0.5
        p.setPen(QColor(255, 255, 255, 220 if std_active else 60))
        p.drawText(0, 0, half, H, Qt.AlignCenter, "STANDARD")

        # ADVANCED label (right half)
        adv_active = t >= 0.5
        p.setPen(QColor(255, 255, 255, 220 if adv_active else 60))
        p.drawText(half, 0, half, H, Qt.AlignCenter, "ADVANCED")

        p.end()

    # ---------------------------------------------------------------- #
    #  Interaction                                                      #
    # ---------------------------------------------------------------- #

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_checked(not self._advanced)


class StatusHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setMaximumHeight(64)
        self.setMinimumHeight(44)
        self.setStyleSheet("background:#111; border-bottom:1px solid #252525;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(14)

        # ---- Logo + SanjINSIGHT name stacked vertically ----
        logo_col = QWidget()
        logo_col.setStyleSheet("background:transparent;")
        logo_col_lay = QVBoxLayout(logo_col)
        logo_col_lay.setContentsMargins(0, 4, 0, 4)
        logo_col_lay.setSpacing(1)

        logo_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "microsanj-logo.svg")
        logo_loaded = False
        if os.path.exists(logo_path):
            try:
                from PyQt5.QtSvg import QSvgWidget
                svg = QSvgWidget(logo_path)
                svg.setFixedSize(130, 26)
                svg.setStyleSheet("background:transparent;")
                logo_col_lay.addWidget(svg)
                logo_loaded = True
            except Exception as _e:
                log.debug("Logo SVG load failed — using text fallback: %s", _e)

        if not logo_loaded:
            fallback = QLabel("MICROSANJ")
            fallback.setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; "
                "color:#fff; letter-spacing:3px; background:transparent;")
            logo_col_lay.addWidget(fallback)



        lay.addWidget(logo_col)

        # ---- Divider ----
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet("color:#2a2a2a;")
        div.setFixedHeight(28)
        lay.addWidget(div)

        # ---- Title removed ----

        # ---- Mode toggle (right next to the title) ----
        lay.addSpacing(10)
        self._mode_toggle = _ModeToggle()
        lay.addWidget(self._mode_toggle)
        lay.addSpacing(4)

        lay.addStretch()

        # ---- Active profile indicator ----
        self._profile_pill = QWidget()
        self._profile_pill.setMaximumHeight(36)
        self._profile_pill.setMinimumWidth(60)
        self._profile_pill.setStyleSheet(
            "background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;")
        pp_lay = QHBoxLayout(self._profile_pill)
        pp_lay.setContentsMargins(10, 0, 10, 0)
        pp_lay.setSpacing(6)
        pp_icon = QLabel("◈")
        pp_icon.setStyleSheet("color:#333; font-size:14pt;")
        self._profile_name_lbl = QLabel("No profile")
        self._profile_name_lbl.setStyleSheet(
            "font-size:14pt; color:#666; font-family:Menlo,monospace;")
        pp_lay.addWidget(pp_icon)
        pp_lay.addWidget(self._profile_name_lbl)
        self._profile_pill_icon = pp_icon
        lay.addWidget(self._profile_pill)

        # ---- Divider ----
        div2 = QFrame()
        div2.setFrameShape(QFrame.VLine)
        div2.setStyleSheet("color:#2a2a2a;")
        div2.setFixedHeight(28)
        lay.addWidget(div2)

        # ---- Status dots ----
        self._cam_dot   = self._dot("Camera")
        self._tec1_dot  = self._dot("TEC 1")
        self._tec2_dot  = self._dot("TEC 2")
        self._fpga_dot  = self._dot("FPGA")
        self._bias_dot  = self._dot("Bias")
        self._stage_dot = self._dot("Stage")
        for d in [self._cam_dot, self._tec1_dot, self._tec2_dot,
                  self._fpga_dot, self._bias_dot, self._stage_dot]:
            lay.addWidget(d)

        # ---- Demo mode banner (hidden until activated) ----
        self._demo_banner = QWidget()
        self._demo_banner.setVisible(False)
        self._demo_banner.setStyleSheet(
            "background:#ff990022; border:1px solid #ff990066; border-radius:4px;")
        db_lay = QHBoxLayout(self._demo_banner)
        db_lay.setContentsMargins(10, 0, 10, 0)
        db_lay.setSpacing(6)
        db_icon = QLabel("▶")
        db_icon.setStyleSheet("color:#ff9900; font-size:13pt;")
        db_text = QLabel("DEMO MODE")
        db_text.setStyleSheet(
            "color:#ff9900; font-size:12pt; font-family:Menlo,monospace; "
            "letter-spacing:2px; font-weight:bold;")
        db_lay.addWidget(db_icon)
        db_lay.addWidget(db_text)
        self._demo_banner.setToolTip(
            "Running with simulated hardware — no instrument connected.\n"
            "All measurements use synthetic data.")
        lay.addWidget(self._demo_banner)

        # ---- Emergency Stop button (always visible, right edge) ------
        lay.addSpacing(8)
        self._estop_btn = QPushButton("■  STOP")
        self._estop_btn.setFixedHeight(36)
        self._estop_btn.setMinimumWidth(90)
        self._estop_btn.setToolTip(
            "Emergency Stop — immediately disables bias output, "
            "all TECs, stage motion, and aborts any active acquisition.\n"
            "Hardware stays connected. Click 'Clear' to re-arm.")
        self._estop_btn.setStyleSheet("""
            QPushButton {
                background: #5a0000;
                color: #ff4444;
                border: 2px solid #aa0000;
                border-radius: 5px;
                font-size: 13pt;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #7a0000;
                color: #ff6666;
                border-color: #cc2222;
            }
            QPushButton:pressed {
                background: #3a0000;
            }
            QPushButton[armed="false"] {
                background: #1a1a1a;
                color: #555;
                border: 1px solid #2a2a2a;
            }
            QPushButton[armed="false"]:hover {
                background: #222;
                color: #888;
                border-color: #444;
            }
        """)
        self._estop_btn.setProperty("armed", "true")
        self._estop_armed = True
        lay.addWidget(self._estop_btn)

    def _dot(self, label):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet("color:#555; font-size:14pt;")
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size:14pt; color:#888; letter-spacing:1px;")
        h.addWidget(dot)
        h.addWidget(lbl)
        w._dot = dot
        return w

    def set_profile(self, profile):
        """Update the active profile indicator in the header."""
        from profiles.profiles import CATEGORY_ACCENTS
        if profile is None:
            self._profile_name_lbl.setText("No profile")
            self._profile_name_lbl.setStyleSheet(
                "font-size:14pt; color:#666; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet("color:#333; font-size:14pt;")
            self._profile_pill.setStyleSheet(
                "background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")
            # Truncate long names
            name = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._profile_name_lbl.setText(name)
            self._profile_name_lbl.setStyleSheet(
                f"font-size:14pt; color:{accent}; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{accent}; font-size:14pt;")
            self._profile_pill.setStyleSheet(
                f"background:#111; border:1px solid {accent}44; border-radius:4px;")
            self._profile_pill.setToolTip(
                f"{profile.name}\n"
                f"C_T = {profile.ct_value:.3e} K⁻¹\n"
                f"{profile.category}  ·  {profile.wavelength_nm} nm")

    def connect_mode_toggle(self, callback):
        """Wire the mode toggle to a callback(advanced: bool)."""
        self._mode_toggle.toggled.connect(callback)

    def set_demo_mode(self, active: bool):
        """Show or hide the DEMO MODE banner in the header."""
        self._demo_banner.setVisible(active)

    def set_mode(self, advanced: bool):
        """Set the toggle position programmatically (no callback fired)."""
        self._mode_toggle.set_checked(advanced, emit=False)

    def connect_estop(self, on_stop, on_clear):
        """Wire E-Stop button: on_stop fires when armed & clicked, on_clear when latched & clicked."""
        def _clicked():
            if self._estop_armed:
                on_stop()
            else:
                on_clear()
        self._estop_btn.clicked.connect(_clicked)

    def set_estop_triggered(self):
        """Visually latch the button into STOPPED state."""
        self._estop_armed = False
        self._estop_btn.setText("⚠  STOPPED — Click to Clear")
        self._estop_btn.setProperty("armed", "false")
        self._estop_btn.setMinimumWidth(200)
        # Force Qt to re-evaluate the stylesheet property
        self._estop_btn.style().unpolish(self._estop_btn)
        self._estop_btn.style().polish(self._estop_btn)

    def set_estop_armed(self):
        """Reset button back to armed/ready state."""
        self._estop_armed = True
        self._estop_btn.setText("■  STOP")
        self._estop_btn.setProperty("armed", "true")
        self._estop_btn.setMinimumWidth(90)
        self._estop_btn.style().unpolish(self._estop_btn)
        self._estop_btn.style().polish(self._estop_btn)

    def add_device_manager_button(self, callback):
        """Add a ⚙ gear button that opens the Device Manager."""
        gear = QPushButton("⚙")
        gear.setFixedSize(30, 30)
        gear.setToolTip("Device Manager — manage hardware connections and drivers")
        gear.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#444;
                border:1px solid #2a2a2a; border-radius:4px;
                font-size:19pt;
            }
            QPushButton:hover { color:#888; background:#222; }
        """)
        gear.clicked.connect(callback)
        self.layout().addWidget(gear)

    def add_update_badge(self) -> "UpdateBadge":
        """Add the update-available badge to the header and return it."""
        from ui.update_dialog import UpdateBadge
        self._update_badge = UpdateBadge()
        self.layout().addWidget(self._update_badge)
        return self._update_badge

    def set_connected(self, which: str, ok: bool, tooltip: str = ""):
        color  = "#00d4aa" if ok else "#ff4444"
        target = {"camera": self._cam_dot,
                  "tec0":   self._tec1_dot,
                  "tec1":   self._tec2_dot,
                  "tec2":   self._tec2_dot,
                  "tec_meerstetter": self._tec1_dot,
                  "tec_atec":        self._tec2_dot,
                  "fpga":   self._fpga_dot,
                  "bias":   self._bias_dot,
                  "stage":  self._stage_dot}.get(which)
        if target:
            target._dot.setStyleSheet(f"color:{color}; font-size:14pt;")
            if tooltip:
                target.setToolTip(tooltip)

    def set_connecting(self, which: str):
        """Show amber 'connecting' state while device initializes."""
        target = {"camera": self._cam_dot,
                  "tec0":   self._tec1_dot,
                  "tec1":   self._tec2_dot,
                  "fpga":   self._fpga_dot,
                  "bias":   self._bias_dot,
                  "stage":  self._stage_dot}.get(which)
        if target:
            target._dot.setStyleSheet("color:#ff9900; font-size:14pt;")
            target.setToolTip("Connecting…")
