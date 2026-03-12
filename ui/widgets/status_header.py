"""
ui/widgets/status_header.py

StatusHeader           — app header bar (logo · profile pill · devices · e-stop).
_DevicesPopup          — floating dropdown listing connected devices.
ConnectedDevicesButton — header button: colored status dot + dropdown on click.
StatusHeader           — top header bar with logo, mode toggle, devices button, and E-Stop.
"""

from __future__ import annotations

import os
import sys
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal

from ui.theme import FONT, PALETTE, scaled_qss, active_theme


# ── Device label lookup ───────────────────────────────────────────────────────
_DEVICE_LABELS: dict[str, str] = {
    "camera":          "Camera",
    "tec0":            "TEC 1",
    "tec1":            "TEC 2",
    "tec2":            "TEC 2",
    "tec_meerstetter": "TEC",
    "tec_atec":        "TEC",
    "fpga":            "FPGA",
    "bias":            "Bias Source",
    "stage":           "Stage",
}


# ──────────────────────────────────────────────────────────────────────────────
#  _DevicesPopup   — floating dropdown
# ──────────────────────────────────────────────────────────────────────────────

class _DevicesPopup(QWidget):
    """
    Floating dropdown listing connected devices with status dots.

    Created with Qt.Popup so it auto-dismisses when the user clicks outside.
    Emits manage_requested when the footer 'Manage devices…' is clicked.
    Emits device_clicked(key) when a device row is clicked.
    """

    manage_requested = pyqtSignal()
    device_clicked   = pyqtSignal(str)

    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(280)
        self._row_widgets: dict[str, QWidget] = {}   # key → row widget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────
        self._hdr = QWidget()
        hdr_lay = QHBoxLayout(self._hdr)
        hdr_lay.setContentsMargins(14, 10, 14, 10)
        hdr_lay.setSpacing(7)
        self._hdr_dot  = QLabel("●")
        self._hdr_text = QLabel("Connected Devices")
        hdr_lay.addWidget(self._hdr_dot)
        hdr_lay.addWidget(self._hdr_text)
        hdr_lay.addStretch()
        outer.addWidget(self._hdr)

        # ── Top separator ────────────────────────────────────────────────
        self._sep1 = QFrame()
        self._sep1.setFrameShape(QFrame.HLine)
        self._sep1.setFixedHeight(1)
        outer.addWidget(self._sep1)

        # ── Device rows container ────────────────────────────────────────
        self._rows_w = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_w)
        self._rows_lay.setContentsMargins(0, 4, 0, 4)
        self._rows_lay.setSpacing(0)
        outer.addWidget(self._rows_w)

        # Empty-state label
        self._empty_lbl = QLabel("No devices registered")
        self._empty_lbl.setContentsMargins(14, 10, 14, 10)
        outer.addWidget(self._empty_lbl)

        # ── Bottom separator ─────────────────────────────────────────────
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.HLine)
        self._sep2.setFixedHeight(1)
        outer.addWidget(self._sep2)

        # ── Footer: Manage devices ───────────────────────────────────────
        self._manage_btn = QPushButton("＋  Manage devices…")
        self._manage_btn.setCursor(Qt.PointingHandCursor)
        self._manage_btn.setFixedHeight(38)
        self._manage_btn.clicked.connect(self._on_manage)
        outer.addWidget(self._manage_btn)

        self._apply_styles()

    # ── Popup lifecycle ──────────────────────────────────────────────────

    def show_below(self, anchor: QWidget):
        """Position popup just below anchor and show."""
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.adjustSize()
        self.move(pos.x(), pos.y() + 4)
        self.show()
        self.raise_()

    # ── Data ─────────────────────────────────────────────────────────────

    def update_devices(self, devices: dict):
        """Rebuild device rows from devices dict: key → {name, ok, tooltip}."""
        # Clear old rows
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()

        for key, info in devices.items():
            row = self._make_row(key, info["name"], info["ok"], info.get("tooltip", ""))
            self._rows_lay.addWidget(row)
            self._row_widgets[key] = row

        has = bool(devices)
        self._empty_lbl.setVisible(not has)
        self._rows_w.setVisible(has)
        self._apply_styles()
        self.adjustSize()

    def _make_row(self, key: str, name: str, ok, tooltip: str) -> QWidget:
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setFixedHeight(34)
        row.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        dot  = QLabel("●")
        name_lbl   = QLabel(name)
        status_lbl = QLabel()

        if ok is True:
            dot_color  = "#00d4aa"
            status_txt = "Connected"
        elif ok is False:
            dot_color  = "#ff4444"
            status_txt = "Error"
        else:
            dot_color  = "#ff9900"
            status_txt = "Connecting…"

        status_lbl.setText(status_txt)

        lay.addWidget(dot)
        lay.addWidget(name_lbl, 1)
        lay.addWidget(status_lbl)

        row._dot_lbl    = dot
        row._name_lbl   = name_lbl
        row._status_lbl = status_lbl
        row._dot_color  = dot_color
        row._key        = key

        if tooltip:
            row.setToolTip(tooltip)

        # Click detection via mouse press
        row.mousePressEvent = lambda e, k=key: (
            self.device_clicked.emit(k), self.hide()
        ) if e.button() == Qt.LeftButton else None

        return row

    # ── Styling ──────────────────────────────────────────────────────────

    def _apply_styles(self):
        P   = PALETTE
        bg  = P.get("bg",           "#242424")
        bg2 = P.get("surface",      "#2d2d2d")
        bdr = P.get("border",       "#484848")
        dim = P.get("textDim",      "#999999")
        sub = P.get("textSub",      "#6a6a6a")
        txt = P.get("text",         "#ebebeb")
        acc = P.get("accent",       "#00d4aa")
        hov = P.get("surfaceHover", "#404040")

        self.setStyleSheet(
            f"_DevicesPopup {{ background:{bg}; border:1px solid {bdr}; "
            f"border-radius:8px; }}")

        # Header
        self._hdr.setStyleSheet(
            f"background:{bg2}; border-radius:7px 7px 0 0;")
        self._hdr_text.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; "
            f"color:{txt}; background:transparent;")

        # Separators
        for sep in (self._sep1, self._sep2):
            sep.setStyleSheet(f"background:{bdr}; border:none;")

        # Empty state
        self._empty_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{sub}; background:{bg};")

        # Manage button
        self._manage_btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {acc};
                border: none;
                border-radius: 0 0 7px 7px;
                font-size: {FONT['label']}pt;
                font-weight: 600;
                text-align: left;
                padding-left: 14px;
            }}
            QPushButton:hover {{
                background: {bg2};
            }}
        """)

        # Device rows
        for row in self._row_widgets.values():
            self._style_row(row, bg, bg2, hov, txt, sub)

        # Update header dot to match overall summary
        self._hdr_dot.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{acc}; background:transparent;")

    def _style_row(self, row, bg, bg2, hov, txt, sub):
        row.setStyleSheet(
            f"QWidget {{ background:{bg}; }}"
            f"QWidget:hover {{ background:{bg2}; }}")
        row._dot_lbl.setStyleSheet(
            f"color:{row._dot_color}; font-size:{FONT['label']}pt; background:transparent;")
        row._name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{txt}; background:transparent;")
        row._status_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{sub}; background:transparent;")

    def _on_manage(self):
        self.hide()
        self.manage_requested.emit()


# ──────────────────────────────────────────────────────────────────────────────
#  ConnectedDevicesButton
# ──────────────────────────────────────────────────────────────────────────────

class ConnectedDevicesButton(QWidget):
    """
    Header widget: coloured-dot summary + 'Connected Devices (ok/total) ▾'.
    Click to open _DevicesPopup.  Signals forward from popup.
    """

    manage_requested = pyqtSignal()
    device_clicked   = pyqtSignal(str)   # emits device key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: dict[str, dict] = {}
        self._popup: _DevicesPopup | None = None

        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(6)

        self._dot_lbl   = QLabel("●")
        self._text_lbl  = QLabel("Connected Devices")
        self._arrow_lbl = QLabel("▾")

        for lbl in (self._dot_lbl, self._text_lbl, self._arrow_lbl):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay.addWidget(self._dot_lbl)
        lay.addWidget(self._text_lbl)
        lay.addWidget(self._arrow_lbl)

        self._apply_styles()

    # ── Popup ────────────────────────────────────────────────────────────

    def _ensure_popup(self) -> _DevicesPopup:
        if self._popup is None:
            self._popup = _DevicesPopup()
            self._popup.manage_requested.connect(self.manage_requested)
            self._popup.device_clicked.connect(self.device_clicked)
        return self._popup

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p = self._ensure_popup()
            if p.isVisible():
                p.hide()
            else:
                p.update_devices(self._devices)
                p._apply_styles()
                p.show_below(self)
        super().mousePressEvent(e)

    # ── Device state ─────────────────────────────────────────────────────

    def set_device(self, key: str, name: str, ok, tooltip: str = ""):
        """Register or update a device's connection status."""
        self._devices[key] = {"name": name, "ok": ok, "tooltip": tooltip}
        self._refresh()
        if self._popup and self._popup.isVisible():
            self._popup.update_devices(self._devices)

    def _overall_status(self):
        defined = [d["ok"] for d in self._devices.values() if d["ok"] is not None]
        if not defined:
            return None           # all unknown / connecting
        if all(s is True  for s in defined):
            return True           # all green
        if all(s is False for s in defined):
            return False          # all red
        return "partial"          # orange

    # ── Rendering ────────────────────────────────────────────────────────

    def _refresh(self):
        status = self._overall_status()
        if status is True:
            dot_color = "#00d4aa"
        elif status == "partial":
            dot_color = "#ff9900"
        elif status is False:
            dot_color = "#ff4444"
        else:
            dot_color = PALETTE.get("textSub", "#6a6a6a")

        n_ok    = sum(1 for d in self._devices.values() if d["ok"] is True)
        n_total = len(self._devices)
        count   = f" ({n_ok}/{n_total})" if n_total else ""

        self._dot_lbl.setStyleSheet(
            f"color:{dot_color}; font-size:{FONT['label']}pt; background:transparent;")
        self._text_lbl.setText(f"Connected Devices{count}")

    def _apply_styles(self):
        P     = PALETTE
        surf  = P.get("surface",      "#2d2d2d")
        bdr   = P.get("border",       "#484848")
        hover = P.get("surfaceHover", "#404040")
        txt   = P.get("text",         "#ebebeb")
        sub   = P.get("textSub",      "#6a6a6a")

        self.setStyleSheet(f"""
            ConnectedDevicesButton {{
                background: {surf};
                border: 1px solid {bdr};
                border-radius: 5px;
            }}
            ConnectedDevicesButton:hover {{
                background: {hover};
            }}
        """)
        self._text_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{txt}; background:transparent;")
        self._arrow_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{sub}; background:transparent;")
        self._refresh()

        if self._popup:
            self._popup._apply_styles()


# ──────────────────────────────────────────────────────────────────────────────
#  StatusHeader
# ──────────────────────────────────────────────────────────────────────────────

class StatusHeader(QWidget):
    exit_demo_requested = pyqtSignal()

    # Paths to the two logo variants (resolved relative to this file)
    _ASSETS = os.path.join(os.path.dirname(__file__), "..", "..", "assets")
    _LOGO_LIGHT = os.path.join(_ASSETS, "microsanj-logo.svg")        # white  → for dark bg
    _LOGO_DARK  = os.path.join(_ASSETS, "microsanj-logo-black.svg")  # black  → for light bg

    def __init__(self):
        super().__init__()
        self.setMaximumHeight(64)
        self.setMinimumHeight(44)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(14)

        # ── Logo column ──────────────────────────────────────────────
        logo_col = QWidget()
        logo_col.setStyleSheet("background:transparent;")
        logo_col_lay = QVBoxLayout(logo_col)
        logo_col_lay.setContentsMargins(0, 4, 0, 4)
        logo_col_lay.setSpacing(1)

        self._svg_white = None   # shown in dark mode
        self._svg_black = None   # shown in light mode

        # Try to load both SVG variants
        try:
            from PyQt5.QtSvg import QSvgWidget
            if os.path.exists(self._LOGO_LIGHT):
                self._svg_white = QSvgWidget(self._LOGO_LIGHT)
                self._svg_white.setFixedSize(130, 26)
                self._svg_white.setStyleSheet("background:transparent;")
                logo_col_lay.addWidget(self._svg_white)
            if os.path.exists(self._LOGO_DARK):
                self._svg_black = QSvgWidget(self._LOGO_DARK)
                self._svg_black.setFixedSize(130, 26)
                self._svg_black.setStyleSheet("background:transparent;")
                logo_col_lay.addWidget(self._svg_black)
        except Exception as _e:
            log.debug("SVG logo load failed — using text fallback: %s", _e)

        # Text fallback if no SVGs loaded
        if self._svg_white is None and self._svg_black is None:
            fallback = QLabel("MICROSANJ")
            fallback.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['body']}pt; "
                "letter-spacing:3px; background:transparent;")
            logo_col_lay.addWidget(fallback)
            self._logo_fallback = fallback
        else:
            self._logo_fallback = None

        lay.addWidget(logo_col)

        # ── Divider ──────────────────────────────────────────────────
        self._div1 = QFrame()
        self._div1.setFrameShape(QFrame.VLine)
        self._div1.setFixedHeight(28)
        lay.addWidget(self._div1)

        lay.addStretch()

        # ── Active profile pill ───────────────────────────────────────
        self._profile_pill = QWidget()
        self._profile_pill.setMaximumHeight(36)
        self._profile_pill.setMinimumWidth(60)
        self._profile_pill.setObjectName("profilePill")
        pp_lay = QHBoxLayout(self._profile_pill)
        pp_lay.setContentsMargins(8, 0, 8, 0)
        pp_lay.setSpacing(5)
        self._profile_pill_icon = QLabel("●")
        self._profile_name_lbl  = QLabel("No profile")
        pp_lay.addWidget(self._profile_pill_icon)
        pp_lay.addWidget(self._profile_name_lbl)
        lay.addWidget(self._profile_pill)

        # ── Divider 2 ─────────────────────────────────────────────────
        self._div2 = QFrame()
        self._div2.setFrameShape(QFrame.VLine)
        self._div2.setFixedHeight(28)
        lay.addWidget(self._div2)

        # ── Connected Devices dropdown button ─────────────────────────
        self._devices_btn = ConnectedDevicesButton()
        lay.addWidget(self._devices_btn)

        # ── Demo banner (hidden until activated) ─────────────────────
        # Two-part segmented widget: [  Demo Mode  |✕]
        # Outer container owns the blue bg + border-radius (avoids Qt
        # transparency bleed on QLabel).  Exit button sits on the right
        # with a red bg and shared-edge border.
        self._demo_banner = QWidget()
        self._demo_banner.setObjectName("demoBanner")
        self._demo_banner.setVisible(False)
        self._demo_banner.setFixedHeight(36)
        self._demo_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._demo_banner.setAttribute(Qt.WA_StyledBackground, True)
        self._demo_banner.setToolTip(
            "Running with simulated hardware — no instrument connected.\n"
            "All measurements use synthetic data.")
        db_lay = QHBoxLayout(self._demo_banner)
        db_lay.setContentsMargins(0, 0, 0, 0)
        db_lay.setSpacing(0)
        self._db_mode_lbl = QLabel("  Demo Mode  ")
        self._db_mode_lbl.setObjectName("dbModeLabel")
        self._db_mode_lbl.setAlignment(Qt.AlignCenter)
        self._db_mode_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._db_exit = QPushButton("  ✕  ")
        self._db_exit.setObjectName("dbExitBtn")
        self._db_exit.setFixedWidth(44)
        self._db_exit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._db_exit.setToolTip("Exit demo mode and scan for real hardware")
        self._db_exit.clicked.connect(self.exit_demo_requested)
        db_lay.addWidget(self._db_mode_lbl, 0)
        db_lay.addWidget(self._db_exit, 0)
        self._refresh_demo_banner_style()
        lay.addWidget(self._demo_banner)

        # ── Emergency Stop (always red — intentionally semantic) ──────
        lay.addSpacing(8)
        self._estop_btn = QPushButton("■  STOP")
        self._estop_btn.setFixedHeight(36)
        self._estop_btn.setMinimumWidth(90)
        self._estop_btn.setToolTip(
            "Emergency Stop — immediately disables bias output, "
            "all TECs, stage motion, and aborts any active acquisition.\n"
            "Hardware stays connected. Click 'Clear' to re-arm.")
        self._estop_btn.setStyleSheet(scaled_qss("""
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
        """))
        self._estop_btn.setProperty("armed", "true")
        self._estop_armed = True
        lay.addWidget(self._estop_btn)

        # Apply initial theme
        self._apply_styles()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Re-apply all PALETTE-driven styles.  Called on theme change."""
        P     = PALETTE
        bg    = P.get("surface",  "#2d2d2d")
        bdr   = P.get("border",   "#484848")
        dim   = P.get("textDim",  "#999999")
        sub   = P.get("textSub",  "#6a6a6a")
        text  = P.get("text",     "#ebebeb")

        # Header background
        self.setStyleSheet(
            f"StatusHeader {{ background:{bg}; border-bottom:1px solid {bdr}; }}")

        # Dividers
        for div in (self._div1, self._div2):
            div.setStyleSheet(f"color:{bdr};")

        # Profile pill default state (overridden by set_profile when a profile is active)
        self._profile_pill_icon.setStyleSheet(
            f"color:{sub}; font-size:{FONT['label']}pt;")
        self._profile_name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

        # Logo: show white svg in dark mode, black svg in light mode
        dark = active_theme() == "dark"
        if self._svg_white is not None:
            self._svg_white.setVisible(dark)
        if self._svg_black is not None:
            self._svg_black.setVisible(not dark)
        if self._logo_fallback is not None:
            self._logo_fallback.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['body']}pt; "
                f"color:{text}; letter-spacing:3px; background:transparent;")

        # Connected Devices button
        self._devices_btn._apply_styles()

        # Readiness dot (if added)
        if hasattr(self, "_readiness_dot"):
            rd = self._readiness_dot
            rd._lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

        # Demo banner
        if hasattr(self, "_db_mode_lbl"):
            self._refresh_demo_banner_style()

        # AI button (added later via add_ai_button) — re-apply base appearance
        if hasattr(self, "_ai_btn"):
            self._restyle_ai_btn()

        # E-stop button: re-apply armed=false structural colours so they
        # read correctly in both dark and light modes.
        if hasattr(self, "_estop_btn"):
            surf2 = P.get("surface2", "#3d3d3d")
            self._estop_btn.setStyleSheet(scaled_qss(f"""
                QPushButton {{
                    background: #5a0000;
                    color: #ff4444;
                    border: 2px solid #aa0000;
                    border-radius: 5px;
                    font-size: 13pt;
                    font-weight: bold;
                    letter-spacing: 1px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background: #7a0000;
                    color: #ff6666;
                    border-color: #cc2222;
                }}
                QPushButton:pressed {{
                    background: #3a0000;
                }}
                QPushButton[armed="false"] {{
                    background: {surf2};
                    color: {dim};
                    border: 1px solid {bdr};
                }}
                QPushButton[armed="false"]:hover {{
                    background: {bg};
                    color: {sub};
                    border-color: {bdr};
                }}
            """))

    # ── Helpers ───────────────────────────────────────────────────────

    def _refresh_demo_banner_style(self) -> None:
        """Apply PALETTE info/danger colors to the two-part demo banner.

        The outer container owns the blue background so Qt's child-widget
        transparency doesn't bleed through.  CSS is scoped by object name
        to prevent rules from leaking into nested children.
        """
        _info   = PALETTE.get("info",   "#5b8ff9")
        _danger = PALETTE.get("danger", "#ff4466")
        _bg     = PALETTE.get("bg",     "#242424")

        def _blend(fg: str, bg: str, a: float) -> str:
            """Blend fg over bg at alpha a → opaque '#rrggbb'."""
            fr, fg2, fb = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
            br, bg2, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            return (f"#{int(fr*a + br*(1-a)):02x}"
                    f"{int(fg2*a + bg2*(1-a)):02x}"
                    f"{int(fb*a + bb*(1-a)):02x}")

        _ib  = _blend(_info,   _bg, 0.28)   # muted blue bg
        _db  = _blend(_danger, _bg, 0.28)   # muted red bg
        _dh  = _blend(_danger, _bg, 0.42)   # red hover
        _dp  = _blend(_danger, _bg, 0.58)   # red pressed
        _div = _blend(_info,   _bg, 0.45)   # divider between sections

        # Outer container: blue bg + full border + rounded corners
        self._demo_banner.setStyleSheet(
            f"#demoBanner {{ background:{_ib}; border:1px solid {_div}; border-radius:5px; }}")

        # Label: transparent so outer container's blue shows through
        self._db_mode_lbl.setStyleSheet(
            f"QLabel#dbModeLabel {{"
            f" background:transparent; color:{_info}; border:none;"
            f" font-size:{FONT['label']}pt; font-weight:600; letter-spacing:1px;"
            f"}}")

        # Exit button: red bg, right-rounded, shares left border with outer
        self._db_exit.setStyleSheet(scaled_qss(
            f"QPushButton#dbExitBtn {{"
            f" background:{_db}; color:{_danger};"
            f" border:none; border-left:1px solid {_div};"
            f" border-radius:0 4px 4px 0; font-size:13pt; font-weight:bold;"
            f"}}"
            f"QPushButton#dbExitBtn:hover   {{ background:{_dh}; }}"
            f"QPushButton#dbExitBtn:pressed {{ background:{_dp}; }}"
        ))

    def _restyle_ai_btn(self) -> None:
        """Re-apply the AI button's base stylesheet with current PALETTE."""
        if not hasattr(self, "_ai_btn"):
            return
        P     = PALETTE
        surf  = P.get("surface",      "#2d2d2d")
        bdr2  = P.get("border2",      "#3d3d3d")
        hover = P.get("surfaceHover", "#404040")
        sub   = P.get("textSub",      "#6a6a6a")
        # Keep accent from ai_status if set, else default sub colour
        accent = getattr(self._ai_btn, "_ai_accent", sub)
        self._ai_btn.setStyleSheet(f"""
            QPushButton {{
                background:{surf}; color:{sub};
                border:1px solid {bdr2}; border-radius:4px;
                font-size:{FONT['label']}pt; font-weight:600; letter-spacing:1px;
            }}
            QPushButton:hover   {{ color:{P.get('textDim','#999')}; background:{hover}; }}
            QPushButton:checked {{
                background:{surf}; color:{accent};
                border:1px solid {accent}66;
            }}
            QPushButton:checked:hover {{ background:{hover}; }}
        """)

    # ── Public API ─────────────────────────────────────────────────────

    def set_profile(self, profile):
        """Update the active profile indicator in the header."""
        from profiles.profiles import CATEGORY_ACCENTS
        if profile is None:
            dim = PALETTE.get("textDim", "#999999")
            sub = PALETTE.get("textSub", "#6a6a6a")
            self._profile_name_lbl.setText("No profile")
            self._profile_name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{sub}; font-size:{FONT['label']}pt;")
            self._profile_pill.setToolTip("")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")
            name   = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._profile_name_lbl.setText(name)
            self._profile_name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{accent}; letter-spacing:1px;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{accent}; font-size:{FONT['label']}pt;")
            self._profile_pill.setToolTip(
                f"{profile.name}\n"
                f"C_T = {profile.ct_value:.3e} K⁻¹\n"
                f"{profile.category}  ·  {profile.wavelength_nm} nm")

    def set_demo_mode(self, active: bool):
        """Show or hide the DEMO MODE banner in the header."""
        self._demo_banner.setVisible(active)

    def connect_estop(self, on_stop, on_clear):
        """Wire E-Stop button."""
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
        """Wire the 'Manage devices…' dropdown footer to the Device Manager."""
        self._devices_btn.manage_requested.connect(callback)

    def set_hw_btn_status(self, connected: bool):
        """Legacy API — overall status is now derived from individual device states."""
        # No-op: the ConnectedDevicesButton computes overall status
        # from the individual set_connected() calls.
        pass

    def set_connected(self, which: str, ok: bool, tooltip: str = ""):
        """Update a device's connection state in the dropdown."""
        name = _DEVICE_LABELS.get(which, which.replace("_", " ").title())
        self._devices_btn.set_device(which, name, ok, tooltip)

    def set_connecting(self, which: str):
        """Show amber 'connecting' state while device initializes."""
        name = _DEVICE_LABELS.get(which, which.replace("_", " ").title())
        self._devices_btn.set_device(which, name, None, "Connecting…")

    def add_update_badge(self) -> "UpdateBadge":
        """Add the update-available badge to the header."""
        from ui.update_dialog import UpdateBadge
        self._update_badge = UpdateBadge()
        self.layout().addWidget(self._update_badge)
        return self._update_badge

    def add_ai_button(self, callback) -> QPushButton:
        """Add the AI assistant toggle button."""
        btn = QPushButton("AI")
        btn.setFixedSize(44, 30)
        btn.setCheckable(True)
        btn.setToolTip(
            "AI Assistant — toggle the on-device AI assistant panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions.\n"
            "Requires a GGUF model file (configured in Settings → AI Assistant).")
        self._ai_btn = btn
        self._restyle_ai_btn()
        btn.clicked.connect(callback)
        self.layout().addWidget(btn)
        return btn

    def set_ai_status(self, status: str) -> None:
        """Update the AI button appearance to reflect the current AI status."""
        if not hasattr(self, "_ai_btn"):
            return
        _colors = {
            "off":      PALETTE.get("textSub", "#6a6a6a"),
            "loading":  "#ffaa44",
            "ready":    "#00d4aa",
            "thinking": "#8888ff",
            "error":    "#ff5555",
        }
        self._ai_btn._ai_accent = _colors.get(status, PALETTE.get("textSub", "#6a6a6a"))
        self._ai_btn.setToolTip(
            f"AI Assistant ({status}) — click to toggle panel.\n"
            "Explains tabs, diagnoses instrument state, answers questions.")
        self._restyle_ai_btn()

    def add_readiness_dot(self):
        """Add a persistent system-readiness dot to the header bar."""
        dim = PALETTE.get("textDim", "#999999")
        sub = PALETTE.get("textSub", "#6a6a6a")
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{sub}; font-size:{FONT['label']}pt;")
        lbl = QLabel("System")
        lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")
        h.addWidget(dot)
        h.addWidget(lbl)
        w._dot = dot
        w._lbl = lbl

        lay = self.layout()
        dev_idx = lay.indexOf(self._devices_btn)
        lay.insertWidget(dev_idx, w)

        self._readiness_dot = w
        w.setToolTip("System readiness: unknown")

    def set_readiness_grade(self, grade: str, issues: list = None):
        """Update the readiness dot colour and tooltip."""
        if not hasattr(self, "_readiness_dot"):
            return
        _colors = {
            "A": "#00d4aa",
            "B": "#4499ff",
            "C": "#ffaa44",
            "D": "#ff4444",
        }
        color = _colors.get(grade, PALETTE.get("textSub", "#6a6a6a"))
        self._readiness_dot._dot.setStyleSheet(
            f"color:{color}; font-size:{FONT['label']}pt;")
        tip = f"System readiness: Grade {grade}"
        if issues:
            tip += "\n" + "\n".join(f"  • {i}" for i in issues[:8])
        self._readiness_dot.setToolTip(tip)
