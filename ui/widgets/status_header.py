"""
ui/widgets/status_header.py

_ModeToggle  — animated iOS-style Standard/Advanced toggle switch.
StatusHeader — top header bar with logo, mode toggle, device status dots, and E-Stop.
"""

from __future__ import annotations

import os
import sys
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal

from ui.theme import FONT, PALETTE


class _ModeToggle(QWidget):
    """
    Simple two-button segmented control — Standard / Advanced mode selector.

    Clicking STANDARD always activates Standard mode; clicking ADVANCED
    always activates Advanced mode (not a raw XOR toggle).

    Emits toggled(bool) — True means Advanced.
    """

    toggled = pyqtSignal(bool)

    _COL_STD = "#00d4aa"   # teal  — Standard active
    _COL_ADV = "#5078dc"   # blue  — Advanced active

    def __init__(self, parent=None):
        super().__init__(parent)
        self._advanced = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._std_btn = QPushButton("STANDARD")
        self._adv_btn = QPushButton("ADVANCED")

        # Font size: Windows renders pt at 96 DPI vs macOS 72 DPI, so
        # use a slightly smaller point value to keep the buttons compact.
        _fp = 8 if sys.platform == 'win32' else 10

        _base = (
            f"font: bold {_fp}pt 'Helvetica Neue', Arial; "
            "letter-spacing:1px; border:1px solid #333; padding:0 10px;")

        self._std_btn.setStyleSheet(
            f"QPushButton {{ {_base} border-top-left-radius:6px; "
            "border-bottom-left-radius:6px; border-right:none; }}")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ {_base} border-top-right-radius:6px; "
            "border-bottom-right-radius:6px; }}")

        for b in (self._std_btn, self._adv_btn):
            b.setFixedHeight(26)
            b.setMinimumWidth(70)
            b.setCursor(Qt.PointingHandCursor)

        lay.addWidget(self._std_btn)
        lay.addWidget(self._adv_btn)

        self._std_btn.clicked.connect(lambda: self.set_checked(False))
        self._adv_btn.clicked.connect(lambda: self.set_checked(True))

        self.setFixedHeight(26)
        self.setToolTip(
            "Standard: guided 4-step wizard\n"
            "Advanced: full expert tab interface")

        self._refresh_style()

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def is_advanced(self) -> bool:
        return self._advanced

    def set_checked(self, advanced: bool, emit: bool = True):
        if advanced == self._advanced:
            return
        self._advanced = advanced
        self._refresh_style()
        if emit:
            self.toggled.emit(advanced)

    # ---------------------------------------------------------------- #
    #  Internal                                                         #
    # ---------------------------------------------------------------- #

    def _refresh_style(self):
        """Update button colours to reflect the current active mode."""
        std_active = not self._advanced
        adv_active = self._advanced

        std_bg  = self._COL_STD if std_active else "#1e1e1e"
        std_col = "white"       if std_active else "rgba(255,255,255,100)"
        adv_bg  = self._COL_ADV if adv_active else "#1e1e1e"
        adv_col = "white"       if adv_active else "rgba(255,255,255,100)"

        _fp = 8 if sys.platform == 'win32' else 10
        _base = (
            f"font: bold {_fp}pt 'Helvetica Neue', Arial; "
            "letter-spacing:1px; border:1px solid #333; padding:0 10px;")

        self._std_btn.setStyleSheet(
            f"QPushButton {{ {_base} background:{std_bg}; color:{std_col}; "
            "border-top-left-radius:6px; border-bottom-left-radius:6px; "
            "border-right:none; }}")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ {_base} background:{adv_bg}; color:{adv_col}; "
            "border-top-right-radius:6px; border-bottom-right-radius:6px; }}")


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
                f"font-family:Menlo,monospace; font-size:{FONT['body']}pt; "
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
        pp_icon.setStyleSheet(f"color:#333; font-size:{FONT['label']}pt;")
        self._profile_name_lbl = QLabel("No profile")
        self._profile_name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:#666; font-family:Menlo,monospace;")
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
        dot.setStyleSheet(f"color:#555; font-size:{FONT['label']}pt;")
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:#888; letter-spacing:1px;")
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
                f"font-size:{FONT['label']}pt; color:#666; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet(f"color:#333; font-size:{FONT['label']}pt;")
            self._profile_pill.setStyleSheet(
                "background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")
            # Truncate long names
            name = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._profile_name_lbl.setText(name)
            self._profile_name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{accent}; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{accent}; font-size:{FONT['label']}pt;")
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

    def add_ai_button(self, callback) -> QPushButton:
        """Add the AI assistant toggle button and return it."""
        btn = QPushButton("AI")
        btn.setFixedSize(36, 30)
        btn.setCheckable(True)
        btn.setToolTip(
            "AI Assistant — toggle the on-device AI assistant panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions.\n"
            "Requires a GGUF model file (configured in Settings → AI Assistant).")
        btn.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#444;
                border:1px solid #2a2a2a; border-radius:4px;
                font-size:12pt; font-weight:600; letter-spacing:1px;
            }
            QPushButton:hover   { color:#888; background:#222; }
            QPushButton:checked {
                background:#1e2a28; color:#00d4aa;
                border:1px solid #00d4aa66;
            }
            QPushButton:checked:hover { background:#254d42; }
        """)
        btn.clicked.connect(callback)
        self.layout().addWidget(btn)
        self._ai_btn = btn
        return btn

    def set_ai_status(self, status: str) -> None:
        """Update the AI button appearance to reflect the current AI status."""
        if not hasattr(self, "_ai_btn"):
            return
        _colors = {
            "off":      "#444",
            "loading":  "#ffaa44",
            "ready":    "#00d4aa",
            "thinking": "#8888ff",
            "error":    "#ff5555",
        }
        color = _colors.get(status, "#444")
        checked = self._ai_btn.isChecked()
        self._ai_btn.setToolTip(
            f"AI Assistant ({status}) — click to toggle panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions."
        )
        # Re-apply style with status colour
        self._ai_btn.setStyleSheet(f"""
            QPushButton {{
                background:#1a1a1a; color:#444;
                border:1px solid #2a2a2a; border-radius:4px;
                font-size:12pt; font-weight:600; letter-spacing:1px;
            }}
            QPushButton:hover   {{ color:#888; background:#222; }}
            QPushButton:checked {{
                background:#1e2a28; color:{color};
                border:1px solid {color}66;
            }}
            QPushButton:checked:hover {{ background:#254d42; }}
        """)

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
            target._dot.setStyleSheet(f"color:{color}; font-size:{FONT['label']}pt;")
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
            target._dot.setStyleSheet(f"color:#ff9900; font-size:{FONT['label']}pt;")
            target.setToolTip("Connecting…")
