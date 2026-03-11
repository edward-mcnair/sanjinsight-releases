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

from ui.theme import FONT, PALETTE, scaled_qss


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

        # Note: the CSS `font:` shorthand cannot take a comma-separated
        # font-family list in Qt QSS, so we use separate properties instead.
        _base = (
            f"font-family:'Helvetica Neue',Arial;"
            f"font-size:{_fp}pt; font-weight:bold; "
            f"letter-spacing:1px; border:1px solid {PALETTE['border']}; padding:0 10px;")

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

    def _apply_styles(self) -> None:
        self._refresh_style()

    # ---------------------------------------------------------------- #
    #  Internal                                                         #
    # ---------------------------------------------------------------- #

    def _refresh_style(self):
        """Update button colours to reflect the current active mode."""
        std_active = not self._advanced
        adv_active = self._advanced

        std_bg  = self._COL_STD if std_active else PALETTE["surface"]
        std_col = "white"       if std_active else "rgba(255,255,255,100)"
        adv_bg  = self._COL_ADV if adv_active else PALETTE["surface"]
        adv_col = "white"       if adv_active else "rgba(255,255,255,100)"

        _fp = 8 if sys.platform == 'win32' else 10
        _base = (
            f"font-family:'Helvetica Neue',Arial;"
            f"font-size:{_fp}pt; font-weight:bold; "
            f"letter-spacing:1px; border:1px solid {PALETTE['border']}; padding:0 10px;")

        self._std_btn.setStyleSheet(
            f"QPushButton {{ {_base} background:{std_bg}; color:{std_col}; "
            "border-top-left-radius:6px; border-bottom-left-radius:6px; "
            "border-right:none; }}")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ {_base} background:{adv_bg}; color:{adv_col}; "
            "border-top-right-radius:6px; border-bottom-right-radius:6px; }}")


class StatusHeader(QWidget):
    exit_demo_requested = pyqtSignal()   # emitted when user clicks Exit in the demo banner

    def __init__(self):
        super().__init__()
        self.setMaximumHeight(64)
        self.setMinimumHeight(44)
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
            self._logo_fallback = QLabel("MICROSANJ")
            logo_col_lay.addWidget(self._logo_fallback)
        else:
            self._logo_fallback = None

        lay.addWidget(logo_col)

        # ---- Divider ----
        self._div = QFrame()
        self._div.setFrameShape(QFrame.VLine)
        self._div.setFixedHeight(28)
        lay.addWidget(self._div)

        # ---- Title removed ----

        # ---- Mode toggle (right next to the title) ----
        lay.addSpacing(10)
        self._mode_toggle = _ModeToggle()
        lay.addWidget(self._mode_toggle)
        lay.addSpacing(4)

        lay.addStretch()

        # ---- Active profile indicator — styled to match the hardware dots ----
        self._profile_pill = QWidget()
        self._profile_pill.setMaximumHeight(36)
        self._profile_pill.setMinimumWidth(60)
        self._profile_pill.setObjectName("profilePill")
        pp_lay = QHBoxLayout(self._profile_pill)
        pp_lay.setContentsMargins(8, 0, 8, 0)
        pp_lay.setSpacing(5)
        pp_icon = QLabel("●")
        self._profile_name_lbl = QLabel("No profile")
        pp_lay.addWidget(pp_icon)
        pp_lay.addWidget(self._profile_name_lbl)
        self._profile_pill_icon = pp_icon
        lay.addWidget(self._profile_pill)

        # ---- Divider ----
        self._div2 = QFrame()
        self._div2.setFrameShape(QFrame.VLine)
        self._div2.setFixedHeight(28)
        lay.addWidget(self._div2)

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
        db_lay = QHBoxLayout(self._demo_banner)
        db_lay.setContentsMargins(10, 0, 6, 0)
        db_lay.setSpacing(6)
        self._db_icon = QLabel("▶")
        self._db_text = QLabel("DEMO MODE")
        self._db_text.setStyleSheet(
            f"font-family:Menlo,monospace; letter-spacing:2px; font-weight:bold;")
        self._db_exit = QPushButton("✕ Exit")
        self._db_exit.setToolTip("Exit demo mode and scan for real hardware")
        self._db_exit.clicked.connect(self.exit_demo_requested)
        db_lay.addWidget(self._db_icon)
        db_lay.addWidget(self._db_text)
        db_lay.addSpacing(4)
        db_lay.addWidget(self._db_exit)
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
        self._estop_btn.setProperty("armed", "true")
        self._estop_armed = True
        lay.addWidget(self._estop_btn)

        self._apply_styles()

    # ---------------------------------------------------------------- #
    #  Theme support                                                    #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        """Re-apply all per-widget stylesheets using the current PALETTE."""
        warn = PALETTE["warning"]
        surf = PALETTE["surface"]
        surf3 = PALETTE["surface3"]
        bdr = PALETTE["border"]
        text = PALETTE["text"]
        dim = PALETTE["textDim"]

        # Header bar itself
        self.setStyleSheet(
            f"background:{surf3}; border-bottom:1px solid {bdr};")

        # Logo text fallback
        if self._logo_fallback is not None:
            self._logo_fallback.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['body']}pt; "
                f"color:{text}; letter-spacing:3px; background:transparent;")

        # Dividers
        self._div.setStyleSheet(f"color:{bdr};")
        self._div2.setStyleSheet(f"color:{bdr};")

        # Profile pill
        self._profile_pill_icon.setStyleSheet(
            f"color:{dim}; font-size:{FONT['label']}pt;")
        self._profile_name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

        # Demo banner
        self._demo_banner.setStyleSheet(
            f"background:{warn}22; border:1px solid {warn}66; border-radius:4px;")
        self._db_icon.setStyleSheet(
            f"color:{warn}; font-size:{FONT['body']}pt;")
        self._db_text.setStyleSheet(
            f"color:{warn}; font-size:{FONT['label']}pt; "
            f"font-family:Menlo,monospace; letter-spacing:2px; font-weight:bold;")
        self._db_exit.setStyleSheet(scaled_qss(
            f"QPushButton {{"
            f"    background:{warn}33; color:{warn};"
            f"    border:1px solid {warn}66; border-radius:3px;"
            f"    font-size:11pt; font-weight:600; padding:2px 8px;"
            f"}}"
            f"QPushButton:hover   {{ background:{warn}66; }}"
            f"QPushButton:pressed {{ background:{warn}99; }}"
        ))

        # E-Stop button — safety-critical reds stay hardcoded; only the
        # disarmed/idle state uses PALETTE refs for theme correctness.
        self._estop_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{"
            "    background: #5a0000;"
            "    color: #ff4444;"
            "    border: 2px solid #aa0000;"
            "    border-radius: 5px;"
            "    font-size: 13pt;"
            "    font-weight: bold;"
            "    letter-spacing: 1px;"
            "    padding: 0 12px;"
            "}"
            "QPushButton:hover {"
            "    background: #7a0000;"
            "    color: #ff6666;"
            "    border-color: #cc2222;"
            "}"
            "QPushButton:pressed {"
            "    background: #3a0000;"
            "}"
            f"QPushButton[armed=\"false\"] {{"
            f"    background:{surf3}; color:{dim}; border:1px solid {bdr};"
            f"}}"
            f"QPushButton[armed=\"false\"]:hover {{"
            f"    background:{surf}; color:{text}; border-color:{bdr};"
            f"}}"
        ))

        # Mode toggle
        self._mode_toggle._apply_styles()

        # Device manager button (if added)
        if hasattr(self, "_hw_btn"):
            self._hw_btn.setStyleSheet(
                f"QPushButton {{"
                f"    background:{surf3}; border:1px solid {bdr}; border-radius:4px;"
                f"}}"
                f"QPushButton:hover {{ background:{surf}; }}"
            )

        # AI button (if added) — re-apply with current status colour preserved
        if hasattr(self, "_ai_btn"):
            self.set_ai_status(getattr(self, "_ai_status", "off"))

        # Default dot styles (connected state overrides these at runtime)
        for dot_widget in [self._cam_dot, self._tec1_dot, self._tec2_dot,
                           self._fpga_dot, self._bias_dot, self._stage_dot]:
            lbl = dot_widget.layout().itemAt(1).widget()
            lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

        # Readiness dot (if added)
        if hasattr(self, "_readiness_dot"):
            rd_lbl = self._readiness_dot.layout().itemAt(1).widget()
            rd_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

    def _dot(self, label):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']}; letter-spacing:1px;")
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
                f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']}; letter-spacing:1px;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
            self._profile_pill.setToolTip("")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, PALETTE["success"])
            # Truncate long names
            name = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._profile_name_lbl.setText(name)
            self._profile_name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{accent}; letter-spacing:1px;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{accent}; font-size:{FONT['label']}pt;")
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
        """Add a Device Manager button with a hardware status colour indicator.

        The button icon starts red (no hardware detected) and transitions to
        green once DeviceManagerDialog reports at least one connected device.
        Call set_hw_btn_status(True/False) to update it at any time.
        """
        btn = QPushButton()
        btn.setFixedSize(44, 30)
        btn.setToolTip(
            "Device Manager — manage hardware connections and drivers\n"
            "● Red: no hardware connected\n"
            "● Green: hardware connected")
        btn.setStyleSheet(
            f"QPushButton {{"
            f"    background:{PALETTE['surface3']};"
            f"    border:1px solid {PALETTE['border']}; border-radius:4px;"
            f"}}"
            f"QPushButton:hover {{ background:{PALETTE['surface']}; }}"
        )

        # Start red — updated to green by set_hw_btn_status() once a device
        # is detected.  Uses qtawesome so the icon renders on all platforms
        # (the old SVG path silently failed on Windows, showing "HW" text).
        from ui.icons import set_btn_icon
        set_btn_icon(btn, "fa5s.server", color="#cc3333", size=18)

        self._hw_btn = btn
        btn.clicked.connect(callback)
        self.layout().addWidget(btn)

    def set_hw_btn_status(self, connected: bool):
        """Update the Device Manager button colour to reflect hardware state.

        connected=True  → green icon  (at least one device actively connected)
        connected=False → red icon    (no devices connected)
        """
        if not hasattr(self, "_hw_btn"):
            return
        from ui.icons import set_btn_icon
        color = PALETTE["success"] if connected else "#cc3333"
        set_btn_icon(self._hw_btn, "fa5s.server", color=color, size=18)
        tip_state = "connected" if connected else "no hardware connected"
        self._hw_btn.setToolTip(
            f"Device Manager ({tip_state})\n"
            "Click to manage hardware connections and drivers")

    def add_update_badge(self) -> "UpdateBadge":
        """Add the update-available badge to the header and return it."""
        from ui.update_dialog import UpdateBadge
        self._update_badge = UpdateBadge()
        self.layout().addWidget(self._update_badge)
        return self._update_badge

    def add_ai_button(self, callback) -> QPushButton:
        """Add the AI assistant toggle button and return it."""
        btn = QPushButton("AI")
        btn.setFixedSize(44, 30)
        btn.setCheckable(True)
        btn.setToolTip(
            "AI Assistant — toggle the on-device AI assistant panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions.\n"
            "Requires a GGUF model file (configured in Settings → AI Assistant).")
        btn.clicked.connect(callback)
        self.layout().addWidget(btn)
        self._ai_btn = btn
        self._ai_status = "off"
        self.set_ai_status("off")
        return btn

    def set_ai_status(self, status: str) -> None:
        """Update the AI button appearance to reflect the current AI status."""
        if not hasattr(self, "_ai_btn"):
            return
        self._ai_status = status
        _colors = {
            "off":      PALETTE["textDim"],
            "loading":  PALETTE["warning"],
            "ready":    PALETTE["success"],
            "thinking": PALETTE["info"],
            "error":    PALETTE["danger"],
        }
        color = _colors.get(status, PALETTE["textDim"])
        surf3 = PALETTE["surface3"]
        surf = PALETTE["surface"]
        bdr = PALETTE["border"]
        dim = PALETTE["textDim"]
        self._ai_btn.setToolTip(
            f"AI Assistant ({status}) — click to toggle panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions."
        )
        self._ai_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{"
            f"    background:{surf3}; color:{dim};"
            f"    border:1px solid {bdr}; border-radius:4px;"
            f"    font-size:12pt; font-weight:600; letter-spacing:1px;"
            f"}}"
            f"QPushButton:hover   {{ color:{PALETTE['text']}; background:{surf}; }}"
            f"QPushButton:checked {{"
            f"    background:{surf3}; color:{color};"
            f"    border:1px solid {color}66;"
            f"}}"
            f"QPushButton:checked:hover {{ background:{surf}; }}"
        ))

    def set_connected(self, which: str, ok: bool, tooltip: str = ""):
        color  = PALETTE["success"] if ok else PALETTE["danger"]
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
            target._dot.setStyleSheet(
                f"color:{PALETTE['warning']}; font-size:{FONT['label']}pt;")
            target.setToolTip("Connecting…")

    def add_readiness_dot(self):
        """Add a persistent system-readiness dot to the header bar.

        The dot is placed between the profile pill and the device status dots.
        Call set_readiness_grade() to update its colour and tooltip.

        This method inserts the widget into the layout at the correct position
        (immediately after the divider that follows the profile pill) and must
        be called from outside, like add_device_manager_button(), so that
        existing callers are unaffected.
        """
        # Build the dot widget using the same pattern as _dot()
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        lbl = QLabel("System")
        lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']}; letter-spacing:1px;")
        h.addWidget(dot)
        h.addWidget(lbl)
        w._dot = dot

        # Insert after the divider that follows the profile pill (div2).
        # The layout order is: …profile_pill, div2, cam_dot, …
        # We find div2's index and insert one position after it.
        lay = self.layout()
        div2_idx = lay.indexOf(self._cam_dot) - 1   # div2 sits just before cam_dot
        insert_idx = div2_idx + 1                    # right after div2, before cam_dot
        lay.insertWidget(insert_idx, w)

        self._readiness_dot = w
        w.setToolTip("System readiness: unknown")

    def set_readiness_grade(self, grade: str, issues: list = None):
        """Update the readiness dot colour and tooltip to reflect *grade*.

        Parameters
        ----------
        grade:
            One of "A", "B", "C", or "D".
        issues:
            Optional list of issue description strings shown in the tooltip.
        """
        if not hasattr(self, "_readiness_dot"):
            return

        _colors = {
            "A": PALETTE["success"],  # green  — all clear
            "B": PALETTE["info"],     # blue   — minor issues
            "C": PALETTE["warning"],  # amber  — warnings present
            "D": PALETTE["danger"],   # red    — critical failures
        }
        color = _colors.get(grade, PALETTE["textDim"])
        self._readiness_dot._dot.setStyleSheet(
            f"color:{color}; font-size:{FONT['label']}pt;")

        tip = f"System readiness: Grade {grade}"
        if issues:
            tip += "\n" + "\n".join(f"  • {i}" for i in issues[:8])
        self._readiness_dot.setToolTip(tip)
