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
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame,
    QSizePolicy, QLineEdit)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal

import config as cfg_mod
from ui.theme import FONT, PALETTE, scaled_qss, active_theme
from ui.icons import IC, set_btn_icon, make_icon, make_icon_label


# ── Device label lookup ───────────────────────────────────────────────────────
_DEVICE_LABELS: dict[str, str] = {
    "camera":          "Camera",
    "tr_camera":       "TR Camera",
    "ir_camera":       "IR Camera",
    "tec0":            "TEC 1",
    "tec1":            "TEC 2",
    "tec2":            "TEC 2",
    "tec_meerstetter": "TEC",
    "tec_atec":        "TEC",
    "fpga":            "FPGA",
    "bias":            "Bias Source",
    "stage":           "Stage",
}

# Camera keys are selectable — clicking one makes it the active scan camera
_CAMERA_KEYS: frozenset = frozenset({"camera", "tr_camera", "ir_camera"})


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
        """Position popup flush against the bottom of anchor and show."""
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.adjustSize()
        self.move(pos.x(), pos.y())
        self.show()
        self.raise_()

    # ── Data ─────────────────────────────────────────────────────────────

    def update_devices(self, devices: dict):
        """Rebuild device rows from devices dict: key → {name, ok, tooltip, is_active}."""
        # Clear old rows
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()

        for key, info in devices.items():
            row = self._make_row(
                key, info["name"], info["ok"],
                info.get("tooltip", ""), info.get("is_active", False))
            self._rows_lay.addWidget(row)
            self._row_widgets[key] = row

        has = bool(devices)
        self._empty_lbl.setVisible(not has)
        self._rows_w.setVisible(has)
        self._apply_styles()
        self.adjustSize()

    def _make_row(self, key: str, name: str, ok, tooltip: str,
                  is_active: bool = False) -> QWidget:
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setFixedHeight(34)
        row.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        dot      = QLabel("●")
        name_lbl = QLabel(name)

        if ok is True:
            dot_color  = "#00d4aa"
            status_txt = "Connected"
        elif ok is False:
            dot_color  = "#ff4444"
            status_txt = "Error"
        else:
            dot_color  = "#ff9900"
            status_txt = "Connecting…"

        # Camera rows show an "Active" pill instead of "Connected" when selected
        if key in _CAMERA_KEYS and is_active:
            active_lbl = QLabel("Active")
            active_lbl.setObjectName("camera_active_pill")
            lay.addWidget(dot)
            lay.addWidget(name_lbl, 1)
            lay.addWidget(active_lbl)
        else:
            status_lbl = QLabel(status_txt)
            lay.addWidget(dot)
            lay.addWidget(name_lbl, 1)
            lay.addWidget(status_lbl)
            row._status_lbl = status_lbl

        row._dot_lbl  = dot
        row._name_lbl = name_lbl
        row._dot_color = dot_color
        row._key       = key
        row._is_active = is_active

        if tooltip:
            row.setToolTip(tooltip)

        # Click: camera rows activate the camera; all rows close popup
        if key in _CAMERA_KEYS:
            row.mousePressEvent = lambda e, k=key: (
                self.device_clicked.emit(k), self.hide()
            ) if e.button() == Qt.LeftButton else None
        else:
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
            f"border-top:none; border-radius:0 0 8px 8px; }}")

        # Header
        self._hdr.setStyleSheet(
            f"background:{bg2}; border-radius:0;")
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
        acc = PALETTE.get("accent", "#00d4aa")
        row.setStyleSheet(
            f"QWidget {{ background:{bg}; }}"
            f"QWidget:hover {{ background:{bg2}; }}")
        row._dot_lbl.setStyleSheet(
            f"color:{row._dot_color}; font-size:{FONT['label']}pt; background:transparent;")
        row._name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{txt}; background:transparent;")
        if getattr(row, "_is_active", False):
            # Active camera pill — teal badge, no status label
            pill = row.findChild(QLabel, "camera_active_pill")
            if pill:
                pill.setStyleSheet(
                    f"color:{acc}; font-size:{FONT['caption']}pt; "
                    f"font-weight:700; background:transparent;")
        else:
            if hasattr(row, "_status_lbl"):
                row._status_lbl.setStyleSheet(
                    f"font-size:{FONT['caption']}pt; color:{sub}; background:transparent;")

    def _on_manage(self):
        self.hide()
        self.manage_requested.emit()


# ──────────────────────────────────────────────────────────────────────────────
#  _ProfilePopup   — floating dropdown for profile save/load
# ──────────────────────────────────────────────────────────────────────────────

class _ProfilePopup(QWidget):
    """
    Floating dropdown listing saved profiles with one-click load.
    Footer actions: save current settings, manage profiles.
    """

    profile_selected = pyqtSignal(object)   # emits Recipe
    save_requested   = pyqtSignal()
    manage_requested = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QWidget()
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 10, 14, 10)
        hdr_lay.setSpacing(7)
        self._hdr_icon = QLabel("●")
        self._hdr_text = QLabel("Profiles")
        hdr_lay.addWidget(self._hdr_icon)
        hdr_lay.addWidget(self._hdr_text)
        hdr_lay.addStretch()
        self._hdr = hdr
        outer.addWidget(hdr)

        # ── Separator 1 ──────────────────────────────────────────────
        self._sep1 = QFrame()
        self._sep1.setFrameShape(QFrame.HLine)
        self._sep1.setFixedHeight(1)
        outer.addWidget(self._sep1)

        # ── Profile rows container ───────────────────────────────────
        self._rows_w = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_w)
        self._rows_lay.setContentsMargins(0, 4, 0, 4)
        self._rows_lay.setSpacing(0)
        outer.addWidget(self._rows_w)

        # Empty state
        self._empty_lbl = QLabel("No saved profiles")
        self._empty_lbl.setContentsMargins(14, 10, 14, 10)
        outer.addWidget(self._empty_lbl)

        # ── Separator 2 ──────────────────────────────────────────────
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.HLine)
        self._sep2.setFixedHeight(1)
        outer.addWidget(self._sep2)

        # ── Save button ──────────────────────────────────────────────
        self._save_btn = QPushButton("💾  Save current settings…")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setFixedHeight(36)
        self._save_btn.clicked.connect(self._on_save)
        outer.addWidget(self._save_btn)

        # ── Separator 3 ──────────────────────────────────────────────
        self._sep3 = QFrame()
        self._sep3.setFrameShape(QFrame.HLine)
        self._sep3.setFixedHeight(1)
        outer.addWidget(self._sep3)

        # ── Manage link ──────────────────────────────────────────────
        self._manage_btn = QPushButton("Manage profiles…")
        self._manage_btn.setCursor(Qt.PointingHandCursor)
        self._manage_btn.setFixedHeight(34)
        self._manage_btn.clicked.connect(self._on_manage)
        outer.addWidget(self._manage_btn)

        self._recipes = []     # list of Recipe objects
        self._active_label = ""
        self._apply_styles()

    def show_below(self, anchor: QWidget):
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.adjustSize()
        self.move(pos.x(), pos.y())
        self.show()
        self.raise_()

    def set_profiles(self, recipes: list, active_label: str = ""):
        """Rebuild rows from a list of Recipe objects."""
        self._recipes = recipes
        self._active_label = active_label

        # Clear old rows
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        for recipe in recipes:
            row = self._make_row(recipe)
            self._rows_lay.addWidget(row)

        has = bool(recipes)
        self._empty_lbl.setVisible(not has)
        self._rows_w.setVisible(has)
        self._apply_styles()
        self.adjustSize()

    def _make_row(self, recipe) -> QWidget:
        is_active = recipe.label == self._active_label
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setFixedHeight(40)
        row.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)

        name_lbl = QLabel(recipe.label)
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        row._name_lbl = name_lbl

        desc_lbl = QLabel(recipe.description[:40] if recipe.description else "")
        desc_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        row._desc_lbl = desc_lbl

        lay.addWidget(name_lbl, 1)
        lay.addWidget(desc_lbl)

        if is_active:
            pill = QLabel("Active")
            pill.setObjectName("profile_active_pill")
            pill.setAttribute(Qt.WA_TransparentForMouseEvents)
            row._active_pill = pill
            lay.addWidget(pill)
        else:
            row._active_pill = None

        row.mousePressEvent = lambda e, r=recipe: (
            self._on_select(r)
        ) if e.button() == Qt.LeftButton else None

        return row

    def _on_select(self, recipe):
        self.hide()
        self.profile_selected.emit(recipe)

    def _on_save(self):
        self.hide()
        self.save_requested.emit()

    def _on_manage(self):
        self.hide()
        self.manage_requested.emit()

    def _apply_styles(self):
        P   = PALETTE
        bg  = P.get("bg",           "#242424")
        bg2 = P.get("surface",      "#2d2d2d")
        bdr = P.get("border",       "#484848")
        dim = P.get("textDim",      "#999999")
        sub = P.get("textSub",      "#6a6a6a")
        txt = P.get("text",         "#ebebeb")
        acc = P.get("accent",       "#00d4aa")

        self.setStyleSheet(
            f"_ProfilePopup {{ background:{bg}; border:1px solid {bdr}; "
            f"border-top:none; border-radius:0 0 8px 8px; }}")

        self._hdr.setStyleSheet(f"background:{bg2}; border-radius:0;")
        self._hdr_text.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; "
            f"color:{txt}; background:transparent;")
        self._hdr_icon.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{acc}; background:transparent;")

        for sep in (self._sep1, self._sep2, self._sep3):
            sep.setStyleSheet(f"background:{bdr}; border:none;")

        self._empty_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{sub}; background:{bg};")

        for btn in (self._save_btn, self._manage_btn):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {bg};
                    color: {acc};
                    border: none;
                    font-size: {FONT['label']}pt;
                    font-weight: 600;
                    text-align: left;
                    padding-left: 14px;
                }}
                QPushButton:hover {{
                    background: {bg2};
                }}
            """)

        # Last button gets bottom radius
        self._manage_btn.setStyleSheet(
            self._manage_btn.styleSheet().replace(
                "border: none;",
                "border: none; border-radius: 0 0 7px 7px;"))

        # Style profile rows
        for i in range(self._rows_lay.count()):
            item = self._rows_lay.itemAt(i)
            if item and item.widget():
                row = item.widget()
                row.setStyleSheet(
                    f"QWidget {{ background:{bg}; }}"
                    f"QWidget:hover {{ background:{bg2}; }}")
                if hasattr(row, "_name_lbl"):
                    row._name_lbl.setStyleSheet(
                        f"font-size:{FONT['label']}pt; font-weight:600; "
                        f"color:{txt}; background:transparent;")
                if hasattr(row, "_desc_lbl"):
                    row._desc_lbl.setStyleSheet(
                        f"font-size:{FONT['caption']}pt; color:{sub}; "
                        f"background:transparent;")
                if hasattr(row, "_active_pill") and row._active_pill:
                    row._active_pill.setStyleSheet(
                        f"color:{acc}; font-size:{FONT['caption']}pt; "
                        f"font-weight:700; background:transparent;")


# ──────────────────────────────────────────────────────────────────────────────
#  ProfileButton — header button with profile name + dropdown
# ──────────────────────────────────────────────────────────────────────────────

class ProfileButton(QWidget):
    """
    Header widget: active profile indicator + '▾' dropdown arrow.
    Click to open _ProfilePopup listing saved profiles with save/load.
    """

    profile_selected = pyqtSignal(object)   # emits Recipe
    save_requested   = pyqtSignal()
    manage_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: _ProfilePopup | None = None
        self._open: bool = False
        self._profile = None       # current MaterialProfile
        self._recipes = []         # cached recipe list
        self._active_recipe_label = ""
        self._recipe_store = None  # set by caller

        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMaximumHeight(36)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(5)

        self._dot_lbl  = QLabel("●")
        self._name_lbl = QLabel("No profile")
        self._arrow_lbl = QLabel("▾")

        for lbl in (self._dot_lbl, self._name_lbl, self._arrow_lbl):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay.addWidget(self._dot_lbl)
        lay.addWidget(self._name_lbl)
        lay.addWidget(self._arrow_lbl)

        self._apply_styles()

    def set_recipe_store(self, store):
        """Inject the RecipeStore so the popup can list saved profiles."""
        self._recipe_store = store

    def set_profile(self, profile):
        """Update the displayed profile name and color."""
        from profiles.profiles import CATEGORY_ACCENTS
        self._profile = profile
        if profile is None:
            dim = PALETTE.get("textDim", "#999999")
            sub = PALETTE.get("textSub", "#6a6a6a")
            self._name_lbl.setText("No profile")
            self._name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; "
                f"letter-spacing:1px; background:transparent;")
            self._dot_lbl.setStyleSheet(
                f"color:{sub}; font-size:{FONT['label']}pt; background:transparent;")
            self.setToolTip("")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")
            name = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._name_lbl.setText(name)
            self._name_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{accent}; "
                f"letter-spacing:1px; background:transparent;")
            self._dot_lbl.setStyleSheet(
                f"color:{accent}; font-size:{FONT['label']}pt; background:transparent;")
            self.setToolTip(
                f"{profile.name}\n"
                f"C_T = {profile.ct_value:.3e} K⁻¹\n"
                f"{profile.category}  ·  {profile.wavelength_nm} nm")

    def set_active_recipe(self, label: str):
        """Track which recipe is currently active (shown as 'Active' pill)."""
        self._active_recipe_label = label

    # ── Popup ────────────────────────────────────────────────────────

    def _ensure_popup(self) -> _ProfilePopup:
        if self._popup is None:
            self._popup = _ProfilePopup()
            self._popup.profile_selected.connect(self.profile_selected)
            self._popup.save_requested.connect(self.save_requested)
            self._popup.manage_requested.connect(self.manage_requested)
        return self._popup

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p = self._ensure_popup()
            if p.isVisible():
                p.hide()
                self._set_open(False)
            else:
                # Refresh recipe list before showing
                if self._recipe_store:
                    try:
                        self._recipes = self._recipe_store.list()
                    except Exception:
                        self._recipes = []
                p.set_profiles(self._recipes, self._active_recipe_label)
                p._apply_styles()
                p.show_below(self)
                self._set_open(True)
                p.installEventFilter(self)
        super().mousePressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self._popup and event.type() == event.Hide:
            self._set_open(False)
        return False

    def _set_open(self, open_: bool):
        self._open = open_
        self._apply_styles()

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self):
        P     = PALETTE
        surf  = P.get("surface",      "#2d2d2d")
        bdr   = P.get("border",       "#484848")
        hover = P.get("surfaceHover", "#404040")
        txt   = P.get("text",         "#ebebeb")

        if self._open:
            radius   = "5px 5px 0 0"
            border_b = "none"
        else:
            radius   = "5px"
            border_b = f"1px solid {bdr}"

        self.setStyleSheet(f"""
            ProfileButton {{
                background: {surf};
                border: 1px solid {bdr};
                border-bottom: {border_b};
                border-radius: {radius};
            }}
            ProfileButton:hover {{
                background: {hover};
            }}
        """)
        self._arrow_lbl.setStyleSheet(
            f"font-size:{int(FONT['label'] * 2.4)}pt; color:{txt}; "
            f"background:transparent; padding-bottom:6px;")

        # Dot and name styles are set by set_profile(); only touch arrow here.
        if self._popup:
            self._popup._apply_styles()


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
        self._open: bool = False

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
                self._set_open(False)
            else:
                p.update_devices(self._devices)
                p._apply_styles()
                p.show_below(self)
                self._set_open(True)
                p.installEventFilter(self)   # detect popup close
        super().mousePressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self._popup and event.type() == event.Hide:
            self._set_open(False)
        return False

    def _set_open(self, open_: bool):
        self._open = open_
        self._apply_styles()

    # ── Device state ─────────────────────────────────────────────────────

    def set_device(self, key: str, name: str, ok, tooltip: str = ""):
        """Register or update a device's connection status."""
        existing = self._devices.get(key, {})
        self._devices[key] = {
            "name":      name,
            "ok":        ok,
            "tooltip":   tooltip,
            "is_active": existing.get("is_active", False),
        }
        self._refresh()
        if self._popup and self._popup.isVisible():
            self._popup.update_devices(self._devices)

    def clear_devices(self) -> None:
        """Remove all device entries (e.g. when exiting demo mode)."""
        self._devices.clear()
        self._refresh()
        if self._popup and self._popup.isVisible():
            self._popup.update_devices(self._devices)

    def set_active_device(self, key: str) -> None:
        """Mark *key* as the active camera; clear the flag on all other camera keys."""
        changed = False
        for k in list(self._devices):
            was = self._devices[k].get("is_active", False)
            should = (k == key) and (k in _CAMERA_KEYS)
            if was != should:
                self._devices[k]["is_active"] = should
                changed = True
        if changed:
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

        # When open: square bottom corners + no bottom border (merges with popup)
        if self._open:
            radius   = "5px 5px 0 0"
            border_b = "none"
        else:
            radius   = "5px"
            border_b = f"1px solid {bdr}"

        self.setStyleSheet(f"""
            ConnectedDevicesButton {{
                background: {surf};
                border: 1px solid {bdr};
                border-bottom: {border_b};
                border-radius: {radius};
            }}
            ConnectedDevicesButton:hover {{
                background: {hover};
            }}
        """)
        self._text_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{txt}; background:transparent;")
        self._arrow_lbl.setStyleSheet(
            f"font-size:{int(FONT['label'] * 2.4)}pt; color:{txt}; "
            f"background:transparent; padding-bottom:6px;")
        self._refresh()

        if self._popup:
            self._popup._apply_styles()


# ──────────────────────────────────────────────────────────────────────────────
#  _OperatorPopup   — floating operator selector
# ──────────────────────────────────────────────────────────────────────────────

class _OperatorPopup(QWidget):
    """
    Floating dropdown for selecting the active operator.

    Shows saved operators as clickable rows, plus an inline entry field
    to add a new operator name.  Created with Qt.Popup so it dismisses
    automatically when the user clicks outside.
    """

    operator_selected = pyqtSignal(str)   # name selected; "" = clear

    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(240)
        self._row_widgets: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────
        self._hdr = QWidget()
        hdr_lay = QHBoxLayout(self._hdr)
        hdr_lay.setContentsMargins(14, 10, 14, 10)
        hdr_lbl = QLabel("Active Operator")
        hdr_lay.addWidget(hdr_lbl)
        hdr_lay.addStretch()
        outer.addWidget(self._hdr)

        # ── Separator ────────────────────────────────────────────────────
        self._sep1 = QFrame()
        self._sep1.setFrameShape(QFrame.HLine)
        self._sep1.setFixedHeight(1)
        outer.addWidget(self._sep1)

        # ── Operator rows container ───────────────────────────────────────
        self._rows_w = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_w)
        self._rows_lay.setContentsMargins(0, 4, 0, 4)
        self._rows_lay.setSpacing(0)
        outer.addWidget(self._rows_w)

        # ── Separator ────────────────────────────────────────────────────
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.HLine)
        self._sep2.setFixedHeight(1)
        outer.addWidget(self._sep2)

        # ── New operator entry ────────────────────────────────────────────
        entry_w = QWidget()
        entry_lay = QHBoxLayout(entry_w)
        entry_lay.setContentsMargins(10, 6, 10, 6)
        entry_lay.setSpacing(6)
        self._new_edit = QLineEdit()
        self._new_edit.setPlaceholderText("New operator name…")
        self._new_edit.setFixedHeight(28)
        self._new_edit.returnPressed.connect(self._on_add)
        self._add_btn = QPushButton("Add")
        self._add_btn.setFixedHeight(28)
        self._add_btn.setMinimumWidth(54)
        self._add_btn.clicked.connect(self._on_add)
        entry_lay.addWidget(self._new_edit, 1)
        entry_lay.addWidget(self._add_btn)
        outer.addWidget(entry_w)

        self._entry_w = entry_w
        self._apply_styles()

    # ── Popup lifecycle ───────────────────────────────────────────────

    def show_below(self, anchor: QWidget):
        # Right-align popup with anchor's right edge so it never falls off-screen
        anchor_bottom_right = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.adjustSize()
        x = anchor_bottom_right.x() - self.width()
        self.move(x, anchor_bottom_right.y())
        self.show()
        self.raise_()

    # ── Data ─────────────────────────────────────────────────────────

    def rebuild(self, operators: list, active: str):
        """Rebuild operator rows from saved list."""
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()

        # "No operator" / clear row
        self._add_row("(No operator)", "", active)
        for name in (operators or []):
            self._add_row(name, name, active)

        self.adjustSize()

    def _add_row(self, display: str, value: str, active: str):
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setFixedHeight(34)
        row.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)

        check_lbl = QLabel("✓" if value == active else " ")
        name_lbl  = QLabel(display)
        lay.addWidget(check_lbl)
        lay.addWidget(name_lbl, 1)

        row._value     = value
        row._check_lbl = check_lbl
        row._name_lbl  = name_lbl

        row.mousePressEvent = lambda e, v=value: (
            self.operator_selected.emit(v), self.hide()
        ) if e.button() == Qt.LeftButton else None

        self._rows_lay.addWidget(row)
        self._row_widgets.append(row)
        self._style_row(row, value == active)

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_add(self):
        name = self._new_edit.text().strip()
        if name:
            self.operator_selected.emit(name)
            self._new_edit.clear()
            self.hide()

    # ── Styling ───────────────────────────────────────────────────────

    def _apply_styles(self):
        P   = PALETTE
        bg  = P.get("bg",           "#242424")
        bg2 = P.get("surface",      "#2d2d2d")
        bdr = P.get("border",       "#484848")
        txt = P.get("text",         "#ebebeb")
        acc = P.get("accent",       "#00d4aa")
        hov = P.get("surfaceHover", "#404040")
        sub = P.get("textSub",      "#6a6a6a")
        dim = P.get("textDim",      "#999999")

        self.setStyleSheet(
            f"_OperatorPopup {{ background:{bg}; border:1px solid {bdr}; "
            f"border-top:none; border-radius:0 0 8px 8px; }}")
        self._hdr.setStyleSheet(f"background:{bg2}; border-radius:0;")
        self._hdr.findChild(QLabel).setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; "
            f"color:{txt}; background:transparent;")
        for sep in (self._sep1, self._sep2):
            sep.setStyleSheet(f"background:{bdr}; border:none;")
        self._new_edit.setStyleSheet(
            f"background:{bg2}; color:{txt}; border:1px solid {bdr}; "
            f"border-radius:3px; padding:2px 6px; font-size:{FONT['label']}pt;")
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background:{acc}22; color:{acc}; border:1px solid {acc}44; "
            f"border-radius:3px; font-size:{FONT['label']}pt; font-weight:600; }}"
            f"QPushButton:hover {{ background:{acc}44; }}")
        for row in self._row_widgets:
            self._style_row(row, row._value == cfg_mod.get_pref("lab.active_operator", ""))

    def _style_row(self, row, is_active: bool):
        P   = PALETTE
        bg  = P.get("bg",           "#242424")
        acc = P.get("accent",       "#00d4aa")
        txt = P.get("text",         "#ebebeb")
        dim = P.get("textDim",      "#999999")
        hov = P.get("surfaceHover", "#404040")
        row.setStyleSheet(
            f"QWidget {{ background:{bg}; }}"
            f"QWidget:hover {{ background:{hov}; }}")
        row._check_lbl.setStyleSheet(
            f"color:{acc if is_active else 'transparent'}; "
            f"font-size:{FONT['label']}pt; background:transparent;")
        row._name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; "
            f"color:{acc if is_active else txt}; background:transparent; "
            f"font-weight:{'600' if is_active else 'normal'};")


# ──────────────────────────────────────────────────────────────────────────────
#  OperatorButton
# ──────────────────────────────────────────────────────────────────────────────

class OperatorButton(QWidget):
    """
    Header button: 👤 icon + active operator name + dropdown arrow.

    Click opens _OperatorPopup.  Saves and restores selection via
    config.get_pref / config.set_pref("lab.*").

    Signals
    -------
    operator_changed(str)   Emitted when the active operator changes.
                            Empty string means "no operator set".
    """

    operator_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: _OperatorPopup | None = None
        self._open: bool = False

        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(5)

        self._icon_lbl  = make_icon_label(IC.USER, color=PALETTE.get("textDim", "#8892aa"), size=18)
        self._name_lbl  = QLabel("Operator")
        self._arrow_lbl = QLabel("▾")

        for lbl in (self._icon_lbl, self._name_lbl, self._arrow_lbl):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay.addWidget(self._icon_lbl)
        lay.addWidget(self._name_lbl)
        lay.addWidget(self._arrow_lbl)

        self._apply_styles()

    # ── Popup ────────────────────────────────────────────────────────

    def _ensure_popup(self) -> _OperatorPopup:
        if self._popup is None:
            self._popup = _OperatorPopup()
            self._popup.operator_selected.connect(self._on_operator_selected)
        return self._popup

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p = self._ensure_popup()
            if p.isVisible():
                p.hide()
                self._set_open(False)
            else:
                operators = cfg_mod.get_pref("lab.operators", []) or []
                active    = cfg_mod.get_pref("lab.active_operator", "") or ""
                p.rebuild(operators, active)
                p._apply_styles()
                p.show_below(self)
                self._set_open(True)
                p.installEventFilter(self)
        super().mousePressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self._popup and event.type() == event.Hide:
            self._set_open(False)
        return False

    def _set_open(self, open_: bool):
        self._open = open_
        self._apply_styles()


    # ── State ─────────────────────────────────────────────────────────

    def _on_operator_selected(self, name: str):
        """Persist selection and add new names to the saved list."""
        cfg_mod.set_pref("lab.active_operator", name)
        if name:
            operators = list(cfg_mod.get_pref("lab.operators", []) or [])
            if name not in operators:
                operators.append(name)
                cfg_mod.set_pref("lab.operators", operators)
        self._refresh()
        self.operator_changed.emit(name)

    def _refresh(self):
        active = cfg_mod.get_pref("lab.active_operator", "") or ""
        self._name_lbl.setText(active if active else "Operator")

    def get_active_operator(self) -> str:
        """Return the currently active operator name (or empty string)."""
        return cfg_mod.get_pref("lab.active_operator", "") or ""

    def update_from_session(self, session) -> None:
        """Show the logged-in user name + role badge, or fall back to pref.

        Displays e.g. "Jane Smith  [TECH]" / "R. Wilson  [ANALYST]" /
        "Admin  [ADMIN]".  When *session* is None the widget reverts to
        the legacy pref-based operator name.
        """
        if session is None:
            self._refresh()
            return
        user = getattr(session, "user", None)
        if user is None:
            self._refresh()
            return
        name    = getattr(user, "display_name", "") or ""
        is_admin = getattr(user, "is_admin", False)
        user_type = getattr(user, "user_type", None)
        ut_val  = getattr(user_type, "value", "") if user_type else ""
        badge   = {
            "technician":      "[TECH]",
            "failure_analyst": "[ANALYST]",
            "researcher":      "[RES]",
        }.get(ut_val, "[USER]")
        if is_admin:
            badge = "[ADMIN]"
        self._name_lbl.setText(f"{name}  {badge}" if name else badge)

    # ── Styling ───────────────────────────────────────────────────────

    def _apply_styles(self):
        P     = PALETTE
        surf  = P.get("surface",      "#2d2d2d")
        bdr   = P.get("border",       "#484848")
        hover = P.get("surfaceHover", "#404040")
        txt   = P.get("text",         "#ebebeb")
        dim   = P.get("textDim",      "#999999")

        if self._open:
            radius   = "5px 5px 0 0"
            border_b = "none"
        else:
            radius   = "5px"
            border_b = f"1px solid {bdr}"

        self.setStyleSheet(f"""
            OperatorButton {{
                background: {surf};
                border: 1px solid {bdr};
                border-bottom: {border_b};
                border-radius: {radius};
            }}
            OperatorButton:hover {{
                background: {hover};
            }}
        """)
        _user_icon = make_icon(IC.USER, color=dim, size=18)
        if _user_icon:
            self._icon_lbl.setPixmap(_user_icon.pixmap(18, 18))
        self._icon_lbl.setStyleSheet("background:transparent;")
        self._name_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{txt}; background:transparent;")
        self._arrow_lbl.setStyleSheet(
            f"font-size:{int(FONT['label'] * 2.4)}pt; color:{dim}; "
            f"background:transparent; padding-bottom:6px;")
        self._refresh()
        if self._popup:
            self._popup._apply_styles()


# ──────────────────────────────────────────────────────────────────────────────
#  StatusHeader
# ──────────────────────────────────────────────────────────────────────────────

class StatusHeader(QWidget):
    exit_demo_requested  = pyqtSignal()
    admin_login_requested  = pyqtSignal()   # emitted when "Log in" btn clicked
    admin_logout_requested = pyqtSignal()   # emitted when "Log out" btn clicked

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
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['body']}pt; "
                "letter-spacing:3px; background:transparent;")
            logo_col_lay.addWidget(fallback)
            self._logo_fallback = fallback
        else:
            self._logo_fallback = None

        lay.addWidget(logo_col)

        # ── App name ─────────────────────────────────────────────────
        self._app_name_lbl = QLabel("SanjINSIGHT")
        self._app_name_lbl.setStyleSheet(
            f"font-size:{FONT.get('heading', 14)}pt; font-weight:bold; "
            f"color:{PALETTE.get('text', '#ebebeb')}; background:transparent; "
            "letter-spacing:0.5px;")
        lay.addWidget(self._app_name_lbl)

        # ── Divider ──────────────────────────────────────────────────
        self._div1 = QFrame()
        self._div1.setFrameShape(QFrame.VLine)
        self._div1.setFixedHeight(28)
        lay.addWidget(self._div1)

        lay.addStretch()

        # ── Active profile button (dropdown) ──────────────────────────
        self._profile_btn = ProfileButton()
        lay.addWidget(self._profile_btn)

        # ── Divider 2 ─────────────────────────────────────────────────
        self._div2 = QFrame()
        self._div2.setFrameShape(QFrame.VLine)
        self._div2.setFixedHeight(28)
        lay.addWidget(self._div2)

        # ── Connected Devices dropdown button ─────────────────────────
        self._devices_btn = ConnectedDevicesButton()
        lay.addWidget(self._devices_btn)

        # ── Divider 3 ─────────────────────────────────────────────────
        self._div3 = QFrame()
        self._div3.setFrameShape(QFrame.VLine)
        self._div3.setFixedHeight(28)
        lay.addWidget(self._div3)

        # ── Operator selector button ───────────────────────────────────
        self._operator_btn = OperatorButton()
        lay.addWidget(self._operator_btn)

        # ── Admin "Log in" button (visible only when auth users exist + no session)
        self._login_btn = QPushButton("Log in")
        set_btn_icon(self._login_btn, IC.LOGIN)
        self._login_btn.setFixedHeight(28)
        self._login_btn.setToolTip(
            "Log in to access administrator features\n"
            "(User Management, Security settings, Scan Profile approval)")
        self._login_btn.setVisible(False)
        self._login_btn.clicked.connect(self.admin_login_requested)
        lay.addWidget(self._login_btn)

        # ── Admin "Log out" button (visible only when a session is active)
        self._logout_btn = QPushButton("Log out")
        set_btn_icon(self._logout_btn, IC.LOGOUT)
        self._logout_btn.setFixedHeight(28)
        self._logout_btn.setToolTip("Log out and return to unauthenticated mode")
        self._logout_btn.setVisible(False)
        self._logout_btn.clicked.connect(self.admin_logout_requested)
        lay.addWidget(self._logout_btn)

        # ── Demo banner (hidden until activated) ─────────────────────
        # Single unified button: [  Demo Mode  ✕  ]
        self._demo_banner = QPushButton("  Demo Mode  ✕  ")
        self._demo_banner.setObjectName("demoBanner")
        self._demo_banner.setVisible(False)
        self._demo_banner.setFixedHeight(30)
        self._demo_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._demo_banner.setToolTip(
            "Running with simulated hardware — no instrument connected.\n"
            "Click to exit demo mode.")
        self._demo_banner.clicked.connect(self.exit_demo_requested)
        self._refresh_demo_banner_style()
        lay.addWidget(self._demo_banner)

        # ── Emergency Stop (always red — intentionally semantic) ──────
        lay.addSpacing(8)
        self._estop_btn = QPushButton("■  STOP")
        self._estop_btn.setFixedHeight(30)
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
        # Header bar is the most elevated surface — use surface4 so it sits
        # visually above both the sidebar (surface) and the workspace (bg).
        bg    = P.get("surface4", "#3a3a3c")
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
        if hasattr(self, "_div3"):
            self._div3.setStyleSheet(f"color:{bdr};")

        # Profile button
        self._profile_btn._apply_styles()
        self._profile_btn.set_profile(self._profile_btn._profile)

        # Logo: show white svg in dark mode, black svg in light mode
        dark = active_theme() == "dark"
        if self._svg_white is not None:
            self._svg_white.setVisible(dark)
        if self._svg_black is not None:
            self._svg_black.setVisible(not dark)
        if self._logo_fallback is not None:
            self._logo_fallback.setStyleSheet(
                f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['body']}pt; "
                f"color:{text}; letter-spacing:3px; background:transparent;")

        # App name label
        if hasattr(self, "_app_name_lbl"):
            self._app_name_lbl.setStyleSheet(
                f"font-size:{FONT.get('heading', 14)}pt; font-weight:bold; "
                f"color:{text}; background:transparent; letter-spacing:0.5px;")

        # Connected Devices button
        self._devices_btn._apply_styles()

        # Operator button
        if hasattr(self, "_operator_btn"):
            self._operator_btn._apply_styles()

        # Log-in / Log-out buttons
        acc = P.get("accent", "#00d4aa")
        _btn_qss = (
            f"QPushButton {{ background:{acc}18; color:{acc}; "
            f"border:1px solid {acc}55; border-radius:4px; "
            f"font-size:{FONT.get('label', 10)}pt; padding:0 10px; }}"
            f"QPushButton:hover {{ background:{acc}33; }}"
        )
        if hasattr(self, "_login_btn"):
            self._login_btn.setStyleSheet(_btn_qss)
        if hasattr(self, "_logout_btn"):
            self._logout_btn.setStyleSheet(_btn_qss)

        # Readiness dot (if added)
        if hasattr(self, "_readiness_dot"):
            rd = self._readiness_dot
            rd._lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{dim}; letter-spacing:1px;")

        # Demo banner
        if hasattr(self, "_demo_banner"):
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
        """Apply PALETTE info color to the unified demo banner button."""
        _info = PALETTE.get("info", "#5b8ff9")
        _bg   = PALETTE.get("bg",   "#242424")

        def _blend(fg: str, bg: str, a: float) -> str:
            fr, fg2, fb = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
            br, bg2, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            return (f"#{int(fr*a + br*(1-a)):02x}"
                    f"{int(fg2*a + bg2*(1-a)):02x}"
                    f"{int(fb*a + bb*(1-a)):02x}")

        _ih = _blend(_info, _bg, 0.85)   # slightly darker on hover
        _ip = _blend(_info, _bg, 0.70)   # pressed

        self._demo_banner.setStyleSheet(scaled_qss(
            f"QPushButton#demoBanner {{"
            f" background:{_info}; color:#ffffff; border:none;"
            f" border-radius:5px; padding:0 14px;"
            f" font-size:{FONT['label']}pt; font-weight:600; letter-spacing:1px;"
            f"}}"
            f"QPushButton#demoBanner:hover   {{ background:{_ih}; }}"
            f"QPushButton#demoBanner:pressed {{ background:{_ip}; }}"
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
        self._profile_btn.set_profile(profile)

    def set_demo_mode(self, active: bool):
        """Show or hide the DEMO MODE banner in the header."""
        self._demo_active = active
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

    def connect_camera_selection(self, callback) -> None:
        """Wire camera-row clicks in the dropdown to *callback(key: str)*."""
        self._devices_btn.device_clicked.connect(
            lambda k: callback(k) if k in _CAMERA_KEYS else None)

    def set_active_device(self, key: str) -> None:
        """Mark *key* as the active camera in the dropdown (shows 'Active' pill)."""
        self._devices_btn.set_active_device(key)

    def clear_devices(self) -> None:
        """Clear all device entries from the dropdown (e.g. when exiting demo mode)."""
        self._devices_btn.clear_devices()

    def set_hw_btn_status(self, connected: bool):
        """Legacy API — overall status is now derived from individual device states."""
        # No-op: the ConnectedDevicesButton computes overall status
        # from the individual set_connected() calls.
        pass

    def set_connected(self, which: str, ok: bool, tooltip: str = ""):
        """Update a device's connection state in the dropdown."""
        name = _DEVICE_LABELS.get(which, which.replace("_", " ").title())
        self._devices_btn.set_device(which, name, ok, tooltip)
        # Auto-hide the demo banner once any real (non-demo) device connects
        if ok and not getattr(self, "_demo_active", False) \
                and hasattr(self, "_demo_banner") and self._demo_banner.isVisible():
            self._demo_banner.setVisible(False)

    def set_connecting(self, which: str):
        """Show amber 'connecting' state while device initializes."""
        name = _DEVICE_LABELS.get(which, which.replace("_", " ").title())
        self._devices_btn.set_device(which, name, None, "Connecting…")

    def get_active_operator(self) -> str:
        """Return the currently active operator name (empty string if none)."""
        if hasattr(self, "_operator_btn"):
            return self._operator_btn.get_active_operator()
        return ""

    def update_from_session(self, session) -> None:
        """Show the logged-in user's name + role badge; swap Log in ↔ Log out."""
        if hasattr(self, "_operator_btn"):
            self._operator_btn.update_from_session(session)
        logged_in = session is not None
        if hasattr(self, "_login_btn"):
            self._login_btn.setVisible(not logged_in)
        if hasattr(self, "_logout_btn"):
            self._logout_btn.setVisible(logged_in)

    def set_auth_users_exist(self, exists: bool) -> None:
        """Show the Log-in button when auth users exist and no session is active."""
        if hasattr(self, "_login_btn"):
            self._login_btn.setVisible(exists)
        # Log-out button only appears after an actual session is established

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
