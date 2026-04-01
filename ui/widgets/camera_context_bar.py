"""
ui/widgets/camera_context_bar.py

CameraContextBar — a persistent, full-width bar shown between the status
header and the main content area.

Visible whenever 2 or more cameras are configured (TR + IR hybrid system).
Hidden on single-camera setups so labs without a hybrid system are
unaffected.

The bar lets the user switch the active camera from any section of the app
— Live, Capture, Transient, Calibration, Analysis, AutoScan — without
having to navigate to a specific tab first.

Layout (left → right)
─────────────────────
  [Camera icon]  "Active Camera:"  [combo ▾]  |  [mode badge]  ...  [peripheral dots]

The combo lists all configured cameras (from camera_registry.get_cameras()).
Selecting one sets app_state.active_camera_type globally, persists the
choice, and emits camera_changed(str) so callers can respond if needed.

The mode badge shows the current imaging modality:
  •  "THERMOREFLECTANCE"  (teal)  when a TR camera is active
  •  "IR LOCK-IN"         (amber) when an IR camera is active

Peripheral dots (right-aligned) show connection status for non-camera
hardware: TEC, FPGA, Bias Source, Stage.  Each dot is a coloured circle
(green = connected, red = error, hidden = not configured).
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QFrame, QSizePolicy)
from PyQt5.QtCore import pyqtSignal

import config as _cfg
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT


# Peripheral key → display label (order = display order)
_PERIPHERAL_LABELS: list[tuple[str, str]] = [
    ("tec",   "TEC"),
    ("fpga",  "FPGA"),
    ("bias",  "Bias"),
    ("stage", "Stage"),
]


class CameraContextBar(QWidget):
    """
    Persistent app-wide camera selector bar.

    Auto-hides when fewer than 2 cameras are available so single-camera
    labs see no change to the UI.
    """

    camera_changed = pyqtSignal(str)   # emits the new camera_type ("tr" | "ir")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        # Icon + label
        self._icon_lbl = QLabel("⬚")   # camera glyph placeholder
        self._icon_lbl.setObjectName("sublabel")
        lay.addWidget(self._icon_lbl)

        self._title_lbl = QLabel("Active Camera:")
        self._title_lbl.setObjectName("sublabel")
        lay.addWidget(self._title_lbl)

        # Combo
        self._combo = QComboBox()
        self._combo.setObjectName("cam_selector_combo")
        self._combo.setMinimumWidth(280)
        self._combo.setMaximumWidth(400)
        self._combo.setFixedHeight(28)
        lay.addWidget(self._combo)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(22)
        lay.addWidget(sep)
        self._sep = sep

        # Mode badge
        self._mode_lbl = QLabel("")
        self._mode_lbl.setFixedHeight(22)
        self._mode_lbl.setObjectName("modeBadge")
        lay.addWidget(self._mode_lbl)

        lay.addStretch()

        # ── Peripheral status indicators (right-aligned) ─────────────
        self._periph_sep = QFrame()
        self._periph_sep.setFrameShape(QFrame.VLine)
        self._periph_sep.setFixedHeight(22)
        self._periph_sep.setVisible(False)
        lay.addWidget(self._periph_sep)

        self._periph_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in _PERIPHERAL_LABELS:
            dot = QLabel("●")
            dot.setFixedWidth(12)
            name = QLabel(label)
            dot.setVisible(False)
            name.setVisible(False)
            lay.addWidget(dot)
            lay.addWidget(name)
            self._periph_widgets[key] = (dot, name)

        self._combo.currentIndexChanged.connect(self._on_changed)

        self._apply_styles()
        self.refresh()

    # ── Public API ───────────────────────────────────────────────────────

    def refresh(self) -> None:
        """
        Rebuild the combo from camera_registry.

        Called at startup, on every hotplug event, and whenever
        active_camera_type changes so the combo always reflects reality.
        """
        from hardware.camera_registry import get_cameras
        from hardware.app_state import app_state

        self._combo.blockSignals(True)
        try:
            cameras     = get_cameras()
            active_type = getattr(app_state, "active_camera_type", "tr")

            if len(cameras) < 2:
                # Single-camera (or no camera) — hide the whole bar.
                self.setVisible(False)
                self._combo.clear()
                if cameras:
                    self._combo.addItem(cameras[0].display_label())
                    self._combo.setItemData(0, cameras[0].camera_type)
                self._update_mode_badge(active_type)
                return

            self.setVisible(True)
            self._combo.clear()
            self._combo.setEnabled(True)
            active_idx = 0
            for i, entry in enumerate(cameras):
                item_text = (f"{entry.display_label()}"
                             f"  — {entry.status_suffix()}")
                self._combo.addItem(item_text)
                self._combo.setItemData(i, entry.camera_type)
                if entry.camera_type == active_type:
                    active_idx = i

            self._combo.setCurrentIndex(active_idx)
            self._update_mode_badge(active_type)

        except Exception:
            self._combo.clear()
            self._combo.addItem("Camera unavailable")
            self._combo.setEnabled(False)
            self.setVisible(False)
        finally:
            self._combo.blockSignals(False)

    def set_peripheral(self, key: str, ok: bool | None, tooltip: str = "") -> None:
        """Update a peripheral device's status indicator.

        Parameters
        ----------
        key : str
            One of ``"tec"``, ``"fpga"``, ``"bias"``, ``"stage"``.
        ok : bool | None
            ``True`` = connected (green), ``False`` = error (red),
            ``None`` = connecting (amber).
        tooltip : str
            Tooltip text shown on hover.
        """
        entry = self._periph_widgets.get(key)
        if entry is None:
            return
        dot, name = entry

        if ok is True:
            color = PALETTE['stateConnected']
        elif ok is False:
            color = PALETTE['stateError']
        else:
            color = PALETTE['stateConnecting']   # amber = connecting

        dot.setStyleSheet(
            f"color:{color}; font-size:9pt; background:transparent;")
        dot.setVisible(True)
        name.setVisible(True)
        if tooltip:
            dot.setToolTip(tooltip)
            name.setToolTip(tooltip)

        # Show the separator if any peripheral is visible
        self._periph_sep.setVisible(True)
        self._apply_periph_name_style()

    def clear_peripheral(self, key: str) -> None:
        """Hide a peripheral indicator (device removed / not configured)."""
        entry = self._periph_widgets.get(key)
        if entry is None:
            return
        dot, name = entry
        dot.setVisible(False)
        name.setVisible(False)

        # Hide separator if no peripherals visible
        any_visible = any(d.isVisible() for d, _ in self._periph_widgets.values())
        self._periph_sep.setVisible(any_visible)

    # ── Private helpers ──────────────────────────────────────────────────

    def _on_changed(self, index: int) -> None:
        cam_type = self._combo.itemData(index)
        if cam_type not in ("tr", "ir"):
            return
        try:
            from hardware.app_state import app_state
            app_state.active_camera_type = cam_type
            _cfg.set_pref("autoscan.selected_camera_type", cam_type)
        except Exception:
            pass
        self._update_mode_badge(cam_type)
        self.camera_changed.emit(cam_type)

    def _update_mode_badge(self, cam_type: str) -> None:
        is_ir  = (cam_type == "ir")
        label  = "IR LOCK-IN" if is_ir else "THERMOREFLECTANCE"
        color  = PALETTE['warning'] if is_ir else PALETTE['accent']
        self._mode_lbl.setText(label)
        self._mode_lbl.setStyleSheet(
            f"color:{color}; font-family:{MONO_FONT}; "
            f"font-size:{FONT.get('caption', 8)}pt; font-weight:700; "
            f"letter-spacing:1px; background:transparent; padding:0 4px;")

    def _apply_periph_name_style(self) -> None:
        txt = PALETTE['textDim']
        for _, name in self._periph_widgets.values():
            name.setStyleSheet(
                f"color:{txt}; font-size:{FONT.get('caption', 8)}pt; "
                f"font-weight:600; background:transparent;")

    def _apply_styles(self) -> None:
        bg  = PALETTE['surface']
        bdr = PALETTE['border']
        txt = PALETTE['textDim']

        self.setStyleSheet(
            f"CameraContextBar {{ background:{bg}; "
            f"border-bottom:1px solid {bdr}; }}")

        self._icon_lbl.setStyleSheet(
            f"color:{txt}; font-size:{FONT.get('label', 10)}pt; "
            f"background:transparent;")
        self._title_lbl.setStyleSheet(
            f"color:{txt}; font-size:{FONT.get('label', 10)}pt; "
            f"background:transparent;")
        self._sep.setStyleSheet(f"color:{bdr};")
        self._periph_sep.setStyleSheet(f"color:{bdr};")
        self._apply_periph_name_style()
