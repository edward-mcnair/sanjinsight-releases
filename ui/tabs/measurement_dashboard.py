"""
ui/tabs/measurement_dashboard.py  —  Measurement Dashboard (v1)

Lean informational home surface for the measurement workspace.
Reads from MeasurementContext, shows device status from app_state,
and lists recent sessions and scan profiles.

Responsibilities:
  - Context strip: camera, material profile, scan profile (live from mctx)
  - Device status: compact connected/disconnected summary
  - Recents: recent sessions + recent scan profiles
  - Contextual actions: navigate to existing surfaces

Does NOT own:
  - next-step guidance (GuidedBanner's job)
  - progress tracking (PhaseTracker's job)
  - hardware control (hardware panels' job)
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSizePolicy,
)

from ui.theme import FONT, PALETTE
from ui.icons import IC, set_btn_icon
from ui.display_terms import TERMS
from ui.nav_labels import NavLabel as NL
from measurement_context import measurement_context as mctx

log = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────

def _card_frame() -> QFrame:
    """Create a styled card container."""
    f = QFrame()
    f.setStyleSheet(
        f"QFrame {{ background: {PALETTE['surface']};"
        f" border: 1px solid {PALETTE['border']};"
        f" border-radius: 8px; }}")
    return f


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {PALETTE['textSub']}; font-size: {FONT['label']}pt;"
        f" font-weight: 600; padding: 0; border: none; background: transparent;")
    return lbl


def _dim_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {PALETTE['textDim']}; font-size: {FONT['sublabel']}pt;"
        f" border: none; background: transparent;")
    return lbl


# ── Context Card ────────────────────────────────────────────────────

class _ContextCard(QFrame):
    """Compact clickable card showing one context item."""

    clicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, parent=None):
        super().__init__(parent)
        self._title_text = title
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        # Icon
        self._icon_lbl = QLabel()
        set_btn_icon(self._icon_lbl, icon_name, PALETTE['accent'], size=20)
        self._icon_lbl.setFixedSize(24, 24)
        self._icon_lbl.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(self._icon_lbl)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"color: {PALETTE['textSub']}; font-size: {FONT['sublabel']}pt;"
            f" font-weight: 600; border: none; background: transparent;")
        text_col.addWidget(self._title_lbl)

        self._value_lbl = QLabel("Select\u2026")
        self._value_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['body']}pt;"
            f" border: none; background: transparent;")
        text_col.addWidget(self._value_lbl)

        lay.addLayout(text_col, 1)

        # Arrow
        arrow = QLabel("\u203A")
        arrow.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: 16pt;"
            f" border: none; background: transparent;")
        lay.addWidget(arrow)

        self._apply_card_style()

    def _apply_card_style(self):
        self.setStyleSheet(
            f"_ContextCard {{ background: {PALETTE['surface']};"
            f" border: 1px solid {PALETTE['border']}; border-radius: 6px; }}"
            f" _ContextCard:hover {{ border-color: {PALETTE['accent']}; }}")

    def set_value(self, text: str, is_set: bool = True):
        """Update the displayed value."""
        self._value_lbl.setText(text)
        if is_set:
            self._value_lbl.setStyleSheet(
                f"color: {PALETTE['text']}; font-size: {FONT['body']}pt;"
                f" border: none; background: transparent;")
        else:
            self._value_lbl.setStyleSheet(
                f"color: {PALETTE['textDim']}; font-size: {FONT['body']}pt;"
                f" font-style: italic; border: none; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _apply_styles(self):
        """Called on theme switch."""
        self._apply_card_style()
        self._title_lbl.setStyleSheet(
            f"color: {PALETTE['textSub']}; font-size: {FONT['sublabel']}pt;"
            f" font-weight: 600; border: none; background: transparent;")
        set_btn_icon(self._icon_lbl, "", PALETTE['accent'], size=20)


# ── Device Row ──────────────────────────────────────────────────────

class _DeviceRow(QWidget):
    """Single row in the device status section."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(8)

        self._dot = QLabel("\u2022")
        self._dot.setFixedWidth(12)
        self._dot.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: 14pt;"
            f" border: none; background: transparent;")
        lay.addWidget(self._dot)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['sublabel']}pt;"
            f" border: none; background: transparent;")
        lay.addWidget(self._label, 1)

        self._status = QLabel("---")
        self._status.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: {FONT['sublabel']}pt;"
            f" border: none; background: transparent;")
        lay.addWidget(self._status)

    def set_connected(self, connected: bool, detail: str = ""):
        if connected:
            self._dot.setStyleSheet(
                f"color: #00d479; font-size: 14pt;"
                f" border: none; background: transparent;")
            self._status.setText(detail or "Connected")
            self._status.setStyleSheet(
                f"color: {PALETTE['textSub']}; font-size: {FONT['sublabel']}pt;"
                f" border: none; background: transparent;")
        else:
            self._dot.setStyleSheet(
                f"color: {PALETTE['textDim']}; font-size: 14pt;"
                f" border: none; background: transparent;")
            self._status.setText("Not connected")
            self._status.setStyleSheet(
                f"color: {PALETTE['textDim']}; font-size: {FONT['sublabel']}pt;"
                f" border: none; background: transparent;")


# ── Recent Item ─────────────────────────────────────────────────────

class _RecentItem(QFrame):
    """Compact clickable row for a recent session or scan profile."""

    clicked = pyqtSignal(str)  # uid

    def __init__(self, uid: str, title: str, subtitle: str,
                 icon_name: str, parent=None):
        super().__init__(parent)
        self._uid = uid
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        icon_lbl = QLabel()
        set_btn_icon(icon_lbl, icon_name, PALETTE['textSub'], size=14)
        icon_lbl.setFixedSize(18, 18)
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['sublabel']}pt;"
            f" border: none; background: transparent;")
        lay.addWidget(title_lbl, 1)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(
            f"color: {PALETTE['textDim']}; font-size: {FONT['sublabel']}pt;"
            f" border: none; background: transparent;")
        lay.addWidget(sub_lbl)

        self.setStyleSheet(
            f"_RecentItem {{ background: transparent;"
            f" border-radius: 4px; border: none; }}"
            f" _RecentItem:hover {{ background: {PALETTE['hover']}; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._uid)
        super().mousePressEvent(event)


# ════════════════════════════════════════════════════════════════════
#  MeasurementDashboard
# ════════════════════════════════════════════════════════════════════

class MeasurementDashboard(QWidget):
    """Lean v1 Measurement Dashboard.

    Signals
    -------
    navigate_requested(str)
        Nav label to select in the sidebar.
    open_session_requested(str)
        Session UID to open in the Sessions tab.
    """

    navigate_requested = pyqtSignal(str)
    open_session_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._subscribe_to_context()
        self._refresh_context()

        # Periodic refresh for device status + recents (every 5s)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_device_status)
        self._refresh_timer.timeout.connect(self._refresh_recents)
        self._refresh_timer.start(5000)

        # Initial population
        QTimer.singleShot(100, self._refresh_device_status)
        QTimer.singleShot(200, self._refresh_recents)

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {PALETTE['bg']}; border: none; }}")

        container = QWidget()
        container.setStyleSheet(f"background: {PALETTE['bg']};")
        self._main_lay = QVBoxLayout(container)
        self._main_lay.setContentsMargins(24, 20, 24, 20)
        self._main_lay.setSpacing(20)

        # Title
        title = QLabel("Measurement Setup")
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['title']}pt;"
            f" font-weight: 700; background: transparent;")
        self._main_lay.addWidget(title)

        # ── Context Strip ───────────────────────────────────────────
        self._main_lay.addWidget(_section_label("Current Setup"))
        self._build_context_strip()

        # ── Device Status ───────────────────────────────────────────
        self._main_lay.addWidget(_section_label("Hardware"))
        self._build_device_status()

        # ── Recents ─────────────────────────────────────────────────
        self._main_lay.addWidget(_section_label("Recent"))
        self._build_recents()

        self._main_lay.addStretch(1)

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_context_strip(self):
        row = QHBoxLayout()
        row.setSpacing(12)

        self._camera_card = _ContextCard(IC.CAMERA, "Camera")
        self._camera_card.clicked.connect(
            lambda: self.navigate_requested.emit(NL.CAMERAS))
        row.addWidget(self._camera_card)

        self._profile_card = _ContextCard(IC.PROFILES, "Material Profile")
        self._profile_card.clicked.connect(
            lambda: self.navigate_requested.emit(NL.LIBRARY))
        row.addWidget(self._profile_card)

        self._scan_card = _ContextCard(
            IC.RECIPES, TERMS["recipe"])
        self._scan_card.clicked.connect(
            lambda: self.navigate_requested.emit(NL.RUN_SCAN))
        row.addWidget(self._scan_card)

        self._main_lay.addLayout(row)

    def _build_device_status(self):
        card = _card_frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        self._dev_camera = _DeviceRow("Camera")
        self._dev_tec = _DeviceRow("TEC")
        self._dev_fpga = _DeviceRow("FPGA")
        self._dev_bias = _DeviceRow("Bias Source")
        self._dev_stage = _DeviceRow("Stage")

        lay.addWidget(self._dev_camera)
        lay.addWidget(self._dev_tec)
        lay.addWidget(self._dev_fpga)
        lay.addWidget(self._dev_bias)
        lay.addWidget(self._dev_stage)

        self._device_card = card
        self._main_lay.addWidget(card)

    def _build_recents(self):
        cols = QHBoxLayout()
        cols.setSpacing(16)

        # Recent Sessions
        sessions_col = QVBoxLayout()
        sessions_col.setSpacing(4)
        sessions_col.addWidget(_dim_label("Sessions"))
        self._sessions_container = QVBoxLayout()
        self._sessions_container.setSpacing(2)
        sessions_col.addLayout(self._sessions_container)
        self._no_sessions_lbl = _dim_label("No recent sessions")
        self._sessions_container.addWidget(self._no_sessions_lbl)
        cols.addLayout(sessions_col, 1)

        # Recent Scan Profiles
        profiles_col = QVBoxLayout()
        profiles_col.setSpacing(4)
        profiles_col.addWidget(_dim_label(TERMS["recipe_plural"]))
        self._profiles_container = QVBoxLayout()
        self._profiles_container.setSpacing(2)
        profiles_col.addLayout(self._profiles_container)
        self._no_profiles_lbl = _dim_label(f"No {TERMS['recipe_plural'].lower()}")
        self._profiles_container.addWidget(self._no_profiles_lbl)
        cols.addLayout(profiles_col, 1)

        self._main_lay.addLayout(cols)

    # ── Context subscription ────────────────────────────────────────

    def _subscribe_to_context(self):
        """Subscribe to MeasurementContext changes."""
        mctx.subscribe("camera_key", self._on_ctx_change)
        mctx.subscribe("material_profile_id", self._on_ctx_change)
        mctx.subscribe("material_profile_name", self._on_ctx_change)
        mctx.subscribe("scan_profile_uid", self._on_ctx_change)
        mctx.subscribe("scan_profile_label", self._on_ctx_change)
        mctx.subscribe("scan_profile_modified", self._on_ctx_change)

    def _on_ctx_change(self, key: str, old, new):
        """Handle any MeasurementContext field change."""
        # Schedule refresh on Qt thread (mctx callbacks may be under lock)
        QTimer.singleShot(0, self._refresh_context)

    def _refresh_context(self):
        """Update context cards from MeasurementContext."""
        # Camera
        cam = mctx.camera_key
        cam_display = {"tr": "Thermoreflectance", "ir": "Infrared"}.get(
            cam, cam.upper())
        self._camera_card.set_value(cam_display, is_set=True)

        # Material profile
        prof_name = mctx.material_profile_name
        if prof_name:
            self._profile_card.set_value(prof_name, is_set=True)
        else:
            self._profile_card.set_value("Select\u2026", is_set=False)

        # Scan profile
        sp_label = mctx.scan_profile_label
        if sp_label:
            suffix = " (modified)" if mctx.scan_profile_modified else ""
            self._scan_card.set_value(f"{sp_label}{suffix}", is_set=True)
        else:
            self._scan_card.set_value("Select\u2026", is_set=False)

    # ── Device status ───────────────────────────────────────────────

    def _refresh_device_status(self):
        """Read device presence from app_state."""
        from hardware.app_state import app_state

        cam = app_state.cam
        if cam:
            name = getattr(cam, "display_name", None) or "Connected"
            self._dev_camera.set_connected(True, name)
        else:
            self._dev_camera.set_connected(False)

        tecs = app_state.tecs
        if tecs:
            names = []
            for t in tecs:
                n = getattr(t, "display_name", None)
                if n:
                    names.append(n)
            self._dev_tec.set_connected(True,
                                        ", ".join(names) if names else "Connected")
        else:
            self._dev_tec.set_connected(False)

        fpga = app_state.fpga
        self._dev_fpga.set_connected(fpga is not None)

        bias = app_state.bias
        self._dev_bias.set_connected(bias is not None)

        stage = app_state.stage
        self._dev_stage.set_connected(stage is not None)

    # ── Recents ─────────────────────────────────────────────────────

    def _refresh_recents(self):
        """Populate recent sessions and scan profiles from data sources."""
        self._refresh_recent_sessions()
        self._refresh_recent_profiles()

    def _refresh_recent_sessions(self):
        """Load recent sessions from SessionManager."""
        try:
            from main_app import session_mgr
            metas = session_mgr.all_metas()[:5]
        except Exception:
            metas = []

        # Clear existing items
        self._clear_layout(self._sessions_container)

        if not metas:
            self._no_sessions_lbl = _dim_label("No recent sessions")
            self._sessions_container.addWidget(self._no_sessions_lbl)
            return

        for meta in metas:
            title = meta.label or meta.uid[:8]
            ts = getattr(meta, "timestamp", "") or ""
            if ts and len(ts) > 10:
                ts = ts[:16]  # trim to date + HH:MM
            item = _RecentItem(
                uid=meta.uid,
                title=title,
                subtitle=ts,
                icon_name=IC.SESSIONS,
            )
            item.clicked.connect(self._on_session_clicked)
            self._sessions_container.addWidget(item)

    def _refresh_recent_profiles(self):
        """Load recent scan profiles from RecipeStore."""
        try:
            from acquisition.recipe_tab import RecipeStore
            store = RecipeStore()
            recipes = store.list()
            # Sort by created_at descending for recency (list() sorts by label)
            recipes_with_ts = [
                r for r in recipes if r.created_at
            ]
            recipes_with_ts.sort(key=lambda r: r.created_at, reverse=True)
            recent = (recipes_with_ts or recipes)[:5]
        except Exception:
            recent = []

        self._clear_layout(self._profiles_container)

        if not recent:
            self._no_profiles_lbl = _dim_label(
                f"No {TERMS['recipe_plural'].lower()}")
            self._profiles_container.addWidget(self._no_profiles_lbl)
            return

        for recipe in recent:
            lock_suffix = " \U0001f512" if recipe.locked else ""
            item = _RecentItem(
                uid=recipe.uid,
                title=f"{recipe.label}{lock_suffix}",
                subtitle=recipe.scan_type or "",
                icon_name=IC.RECIPES,
            )
            item.clicked.connect(self._on_profile_clicked)
            self._profiles_container.addWidget(item)

    def _on_session_clicked(self, uid: str):
        """Navigate to Sessions tab and select the session."""
        self.open_session_requested.emit(uid)

    def _on_profile_clicked(self, uid: str):
        """Navigate to Run Scan panel."""
        self.navigate_requested.emit(NL.RUN_SCAN)

    @staticmethod
    def _clear_layout(layout):
        """Remove all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ── Theme support ───────────────────────────────────────────────

    def _apply_styles(self):
        """Called by MainWindow._swap_visual_theme()."""
        # Re-apply card styles
        self._device_card.setStyleSheet(
            f"QFrame {{ background: {PALETTE['surface']};"
            f" border: 1px solid {PALETTE['border']};"
            f" border-radius: 8px; }}")
        self._refresh_context()
        self._refresh_device_status()
        self._refresh_recents()
