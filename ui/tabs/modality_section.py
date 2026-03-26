"""
ui/tabs/modality_section.py  —  Modality configuration section

Camera type selection, objective/lens, FOV, measurement mode.
Phase 1 · CONFIGURATION
"""
from __future__ import annotations

import logging
import threading

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QGroupBox, QStackedWidget, QPushButton,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from hardware.app_state import app_state
from ui.theme import PALETTE, FONT
from ui.icons import IC, make_icon, make_icon_label, set_btn_icon

log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────

_MODALITY_INFO = {
    "tr": ("Thermoreflectance",
           "Measures relative reflectance change (ΔR/R) induced by "
           "thermal modulation.  Best for high-spatial-resolution "
           "hotspot detection."),
    "ir": ("IR Lock-in Thermography",
           "Measures thermal emission under periodic stimulus.  "
           "Suited for failure isolation and backside imaging."),
}


def _mono_style() -> str:
    return (f"font-family:'Menlo','Consolas','Courier New',monospace; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


class ModalitySection(QWidget):
    """Camera type, objective, FOV — Phase 1 CONFIGURATION."""

    open_device_manager = pyqtSignal()
    modality_changed = pyqtSignal(str)          # "tr" | "ir"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0 — empty state
        self._stack.addWidget(self._build_empty_state())

        # Page 1 — full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)
        self._stack.addWidget(controls)
        self._stack.setCurrentIndex(0)

        # ── Section title ─────────────────────────────────────────────
        title = QLabel("Modality")
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            "font-weight:bold;")
        root.addWidget(title)

        # ── Grid of controls ──────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(8)
        root.addLayout(grid)

        # Camera type
        grid.addWidget(QLabel("Camera Type"), 0, 0)
        self._cam_combo = QComboBox()
        self._cam_combo.setFixedWidth(200)
        self._cam_combo.currentIndexChanged.connect(self._on_camera_type_changed)
        grid.addWidget(self._cam_combo, 0, 1)

        # Modality description
        self._modality_desc = QLabel("")
        self._modality_desc.setWordWrap(True)
        self._modality_desc.setStyleSheet(_dim_style())
        grid.addWidget(self._modality_desc, 1, 1, 1, 2)

        # Objective selector (hidden when no turret)
        self._obj_label = QLabel("Objective")
        self._obj_combo = QComboBox()
        self._obj_combo.setFixedWidth(200)
        self._obj_combo.currentIndexChanged.connect(self._on_objective_changed)

        self._obj_fov_lbl = QLabel("")
        self._obj_fov_lbl.setStyleSheet(_dim_style())

        self._obj_label.setVisible(False)
        self._obj_combo.setVisible(False)
        self._obj_fov_lbl.setVisible(False)

        grid.addWidget(self._obj_label,   2, 0)
        grid.addWidget(self._obj_combo,   2, 1)
        grid.addWidget(self._obj_fov_lbl, 3, 1, 1, 2)

        # ── More Options ──────────────────────────────────────────────
        from ui.widgets.more_options import MoreOptionsPanel

        opts = MoreOptionsPanel(section_key="modality")
        opts_inner = QWidget()
        opts_grid = QGridLayout(opts_inner)
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setSpacing(8)

        opts_grid.addWidget(QLabel("Pixel Pitch (µm)"), 0, 0)
        self._px_spin = QDoubleSpinBox()
        self._px_spin.setRange(0.001, 100.0)
        self._px_spin.setDecimals(3)
        self._px_spin.setReadOnly(True)
        self._px_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._px_spin.setFixedWidth(100)
        opts_grid.addWidget(self._px_spin, 0, 1)

        opts_grid.addWidget(QLabel("Sensor Format"), 1, 0)
        self._sensor_lbl = QLabel("—")
        self._sensor_lbl.setStyleSheet(_mono_style())
        opts_grid.addWidget(self._sensor_lbl, 1, 1)

        opts_grid.addWidget(QLabel("Wavelength Filter"), 2, 0)
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["None", "470 nm", "530 nm", "550 nm",
                                      "590 nm", "625 nm", "650 nm", "850 nm"])
        self._filter_combo.setFixedWidth(120)
        opts_grid.addWidget(self._filter_combo, 2, 1)

        opts.addWidget(opts_inner)
        root.addWidget(opts)
        root.addStretch()

    # ── Public API ─────────────────────────────────────────────────────

    def set_hardware_available(self, available: bool) -> None:
        self._stack.setCurrentIndex(1 if available else 0)
        if available:
            self.refresh()

    def refresh(self) -> None:
        """Re-populate combos from current app_state."""
        self._refresh_camera_combo()
        self._refresh_turret()
        self._refresh_sensor_info()

    # ── Camera combo ───────────────────────────────────────────────────

    def _refresh_camera_combo(self) -> None:
        self._cam_combo.blockSignals(True)
        self._cam_combo.clear()

        active = app_state.active_camera_type   # "tr" or "ir"
        tr_drv = app_state.tr_cam               # primary slot
        ir_drv = app_state.ir_cam               # secondary slot (hybrid only)

        if ir_drv is not None:
            # Hybrid system — both cameras available
            tr_model = getattr(getattr(tr_drv, 'info', None), 'model', 'TR Camera')
            ir_model = getattr(getattr(ir_drv, 'info', None), 'model', 'IR Camera')
            self._cam_combo.addItem(
                f"Thermoreflectance — {tr_model}", "tr")
            self._cam_combo.addItem(
                f"IR Lock-in — {ir_model}", "ir")
        elif tr_drv is not None:
            # Single camera — may be TR or IR depending on active_camera_type
            model = getattr(getattr(tr_drv, 'info', None), 'model', 'Camera')
            if active == "ir":
                self._cam_combo.addItem(
                    f"IR Lock-in — {model}", "ir")
            else:
                self._cam_combo.addItem(
                    f"Thermoreflectance — {model}", "tr")

        # Select the currently active type
        for i in range(self._cam_combo.count()):
            if self._cam_combo.itemData(i) == active:
                self._cam_combo.setCurrentIndex(i)
                break

        self._update_modality_desc(active)
        self._cam_combo.blockSignals(False)

    def _on_camera_type_changed(self, index: int) -> None:
        if index < 0:
            return
        cam_type = self._cam_combo.itemData(index)
        if cam_type is None:
            return
        app_state.active_camera_type = cam_type
        self._update_modality_desc(cam_type)
        self._refresh_sensor_info()
        self.modality_changed.emit(cam_type)

    def _update_modality_desc(self, cam_type: str) -> None:
        name, desc = _MODALITY_INFO.get(cam_type, ("", ""))
        self._modality_desc.setText(desc)

    # ── Objective turret ───────────────────────────────────────────────

    def _refresh_turret(self) -> None:
        turret = app_state.turret
        has_turret = turret is not None
        self._obj_label.setVisible(has_turret)
        self._obj_combo.setVisible(has_turret)
        self._obj_fov_lbl.setVisible(has_turret)

        if not has_turret:
            return

        self._obj_combo.blockSignals(True)
        self._obj_combo.clear()
        try:
            objectives = turret.list_objectives()
            for obj in objectives:
                self._obj_combo.addItem(obj.label, userData=obj)

            cur_pos = turret.get_position()
            for i in range(self._obj_combo.count()):
                obj = self._obj_combo.itemData(i)
                if obj is not None and obj.position == cur_pos:
                    self._obj_combo.setCurrentIndex(i)
                    self._update_fov_label(obj)
                    break
        except Exception:
            pass
        self._obj_combo.blockSignals(False)

    def _on_objective_changed(self, index: int) -> None:
        if index < 0:
            return
        obj = self._obj_combo.itemData(index)
        if obj is None:
            return
        self._update_fov_label(obj)

        turret = app_state.turret
        if turret is None:
            return

        self._obj_combo.setEnabled(False)
        self._obj_fov_lbl.setText("Moving turret…")
        self._obj_fov_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['warning']}; padding-left:2px;")

        def _move():
            try:
                turret.move_to(obj.position)
                app_state.active_objective = obj
            except Exception as exc:
                log.warning("Turret move error: %s", exc)
            finally:
                QTimer.singleShot(0, lambda: self._obj_combo.setEnabled(True))
                QTimer.singleShot(0, lambda: self._update_fov_label(obj))
                QTimer.singleShot(0, self._refresh_pixel_pitch)

        threading.Thread(target=_move, daemon=True).start()

    def _update_fov_label(self, obj) -> None:
        try:
            fov = obj.fov_um()
            px = obj.px_size_um()
            self._obj_fov_lbl.setText(
                f"FOV ≈ {fov:.0f} µm wide   ·   pixel ≈ {px:.3f} µm")
            self._obj_fov_lbl.setStyleSheet(_dim_style())
        except Exception:
            self._obj_fov_lbl.setText("")

    # ── Advanced info ──────────────────────────────────────────────────

    def _refresh_sensor_info(self) -> None:
        cam = app_state.cam
        if cam is not None and hasattr(cam, 'info'):
            w = getattr(cam.info, 'width', 0)
            h = getattr(cam.info, 'height', 0)
            self._sensor_lbl.setText(f"{w} × {h}")
        else:
            self._sensor_lbl.setText("—")
        self._refresh_pixel_pitch()

    def _refresh_pixel_pitch(self) -> None:
        obj = app_state.active_objective
        if obj is not None:
            try:
                self._px_spin.setValue(obj.px_size_um())
                return
            except Exception:
                pass
        self._px_spin.setValue(0.0)

    # ── Empty state ────────────────────────────────────────────────────

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        self._es_icon = make_icon_label(
            IC.LINK_OFF, color=PALETTE.get("textDim", "#555555"), size=64)
        self._es_icon.setAlignment(Qt.AlignCenter)

        self._es_title = QLabel("Camera Not Connected")
        self._es_title.setAlignment(Qt.AlignCenter)

        self._es_tip = QLabel(
            "Connect a camera in Device Manager to configure "
            "measurement modality.")
        self._es_tip.setAlignment(Qt.AlignCenter)
        self._es_tip.setWordWrap(True)
        self._es_tip.setMaximumWidth(400)

        self._es_btn = QPushButton("Open Device Manager")
        self._es_btn.setFixedWidth(200)
        self._es_btn.setFixedHeight(36)
        self._es_btn.clicked.connect(self.open_device_manager)

        self._apply_empty_state_styles()

        lay.addStretch()
        lay.addWidget(self._es_icon)
        lay.addWidget(self._es_title)
        lay.addWidget(self._es_tip)
        lay.addSpacing(8)
        lay.addWidget(self._es_btn, 0, Qt.AlignCenter)
        lay.addStretch()
        return w

    def _apply_empty_state_styles(self) -> None:
        dim = PALETTE.get("textDim", "#888888")
        accent = PALETTE.get("accent", "#00d4aa")
        self._es_title.setStyleSheet(
            f"font-size:{FONT['readoutSm']}pt; font-weight:bold; color:{dim};")
        self._es_tip.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{dim};")
        self._es_btn.setStyleSheet(f"""
            QPushButton {{
                background:{PALETTE.get('surface','#2d2d2d')}; color:{accent};
                border:1px solid {accent}66; border-radius:5px;
                font-size:{FONT['label']}pt; font-weight:600;
            }}
            QPushButton:hover {{ background:{PALETTE.get('surface2','#3d3d3d')}; }}
        """)
        # Rebuild icon pixmap with current palette color
        icon = make_icon(IC.LINK_OFF, color=dim, size=64)
        if icon:
            self._es_icon.setPixmap(icon.pixmap(64, 64))

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._modality_desc.setStyleSheet(_dim_style())
        self._obj_fov_lbl.setStyleSheet(_dim_style())
        self._sensor_lbl.setStyleSheet(_mono_style())
        if hasattr(self, "_es_btn"):
            self._apply_empty_state_styles()
        self.update()
