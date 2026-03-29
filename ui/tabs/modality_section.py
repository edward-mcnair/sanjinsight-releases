"""
ui/tabs/modality_section.py  —  Modality configuration section

Camera type selection, objective/lens, FOV, measurement mode.
Phase 1 · CONFIGURATION

Two presentation modes controlled by workspace mode:

  GUIDED  — Option C: numbered guidance cards with explanations
  COMPACT — Option A: two-column with dismissable help card

Both modes share the same widgets and controls page.  Mode switching
toggles visibility of guidance elements (cards, footer, step badges)
rather than moving widgets between layouts.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QGroupBox, QStackedWidget, QPushButton,
    QDoubleSpinBox, QFrame, QSizePolicy, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor

from hardware.app_state import app_state
from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, make_icon, make_icon_label, set_btn_icon
from ui.widgets.profile_picker import ProfilePicker
from ui.guidance.cards import GuidanceCard, WorkflowFooter
from ui.guidance.content import (
    MODALITY_INFO as _MODALITY_INFO,
    get_section_cards,
    get_modality_info,
)
from ui.guidance.steps import next_steps_after

log = logging.getLogger(__name__)

# ── Preview constants ──────────────────────────────────────────────────
_PREVIEW_W      = 280       # preview thumbnail width
_PREVIEW_H      = 210       # preview thumbnail height  (4:3 ratio)
_PREVIEW_DECIM  = 15        # update every Nth frame (~2 fps at 30 fps)

# ── Guidance content (pulled from centralized database) ────────────────

_CARDS = get_section_cards("modality")

def _card_body(card_id: str) -> str:
    """Look up card body text by card_id."""
    for c in _CARDS:
        if c["card_id"] == card_id:
            return c["body"]
    return ""

# Build next-steps tuples for the WorkflowFooter
_NEXT_STEPS = [
    (s.nav_target, s.label, s.hint)
    for s in next_steps_after("Modality", count=3)
]


# ── Helpers ────────────────────────────────────────────────────────────

def _mono_style() -> str:
    return (f"font-family:{MONO_FONT}; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


class ModalitySection(QWidget):
    """Camera type, objective, FOV — Phase 1 CONFIGURATION.

    Builds a single controls page with guidance cards that are shown/hidden
    based on workspace mode.  ``set_workspace_mode(mode)`` controls which
    guidance elements are visible.
    """

    open_device_manager = pyqtSignal()
    navigate_requested  = pyqtSignal(str)        # nav label
    modality_changed    = pyqtSignal(str)         # "tr" | "ir"
    profile_selected    = pyqtSignal(object)      # MaterialProfile
    custom_selected     = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview_frame_n = 0
        self._preview_live    = False
        self._current_mode    = "standard"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0 — empty state (no hardware)
        self._stack.addWidget(self._build_empty_state())

        # Page 1 — controls (both modes use this, guidance toggles visibility)
        controls_page = self._build_controls_page()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(controls_page)
        self._stack.addWidget(scroll)
        self._stack.setCurrentIndex(0)

        # Show the placeholder icon
        self._show_placeholder()

    # ── Controls page (single page, dual-mode) ─────────────────────

    def _build_controls_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(0)

        # ── Section header ──────────────────────────────────────────
        title = QLabel("Modality")
        title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            "font-weight:bold;")
        root.addWidget(title)

        self._subtitle = QLabel(
            "Configure your imaging technique and measurement settings")
        self._subtitle.setStyleSheet(_dim_style())
        root.addWidget(self._subtitle)
        root.addSpacing(12)

        # ── Compact help card (Standard/Expert) — sits above controls ──
        self._compact_card = GuidanceCard(
            card_id="modality.overview",
            title="Getting Started with Modality",
            body=_card_body("modality.overview"),
        )
        root.addWidget(self._compact_card)
        root.addSpacing(8)

        # ── Step 1: Camera technique ────────────────────────────────
        self._guide_card1 = GuidanceCard(
            card_id="modality.technique",
            title="Choose Your Measurement Technique",
            body=_card_body("modality.technique"),
            step_number=1,
        )
        root.addWidget(self._guide_card1)
        root.addSpacing(4)

        # Camera row: combo + description + preview
        cam_row = QHBoxLayout()
        cam_row.setSpacing(24)
        root.addLayout(cam_row)

        cam_left = QVBoxLayout()
        cam_left.setSpacing(6)
        cam_row.addLayout(cam_left, 3)

        cam_lbl = QLabel("Camera")
        cam_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; "
            f"color:{PALETTE['text']}; padding-left:2px;")
        cam_left.addWidget(cam_lbl)

        self._cam_combo = QComboBox()
        self._cam_combo.setMaximumWidth(700)
        self._cam_combo.currentIndexChanged.connect(self._on_camera_type_changed)
        cam_left.addWidget(self._cam_combo)

        self._modality_desc = QLabel("")
        self._modality_desc.setWordWrap(True)
        self._modality_desc.setStyleSheet(_dim_style())
        cam_left.addWidget(self._modality_desc)

        # Preview (right side of camera row)
        preview_col = QVBoxLayout()
        preview_col.setSpacing(4)
        preview_col.setContentsMargins(0, 0, 0, 0)
        cam_row.addLayout(preview_col, 2)

        self._preview_lbl = QLabel()
        self._preview_lbl.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        self._preview_lbl.setAlignment(Qt.AlignCenter)
        self._preview_lbl.setStyleSheet(self._preview_frame_qss())
        preview_col.addWidget(self._preview_lbl, 0, Qt.AlignTop)

        self._preview_caption = QLabel("No Preview")
        self._preview_caption.setAlignment(Qt.AlignCenter)
        self._preview_caption.setStyleSheet(_dim_style())
        self._preview_caption.setFixedWidth(_PREVIEW_W)
        preview_col.addWidget(self._preview_caption)

        root.addSpacing(12)

        # ── Step 2: Profile ─────────────────────────────────────────
        self._guide_card2 = GuidanceCard(
            card_id="modality.profile",
            title="Select a Measurement Profile",
            body=_card_body("modality.profile"),
            step_number=2,
        )
        root.addWidget(self._guide_card2)
        root.addSpacing(4)

        self._profile_picker = ProfilePicker()
        self._profile_picker.profile_selected.connect(self._on_profile_picked)
        self._profile_picker.custom_selected.connect(self.custom_selected)
        root.addWidget(self._profile_picker)
        root.addSpacing(12)

        # ── Step 3: Fine-tune ───────────────────────────────────────
        self._guide_card3 = GuidanceCard(
            card_id="modality.finetune",
            title="Fine-Tune (Optional)",
            body=_card_body("modality.finetune"),
            step_number=3,
        )
        root.addWidget(self._guide_card3)
        root.addSpacing(4)

        # Objective selector (hidden when no turret)
        obj_grid = QGridLayout()
        obj_grid.setSpacing(8)
        root.addLayout(obj_grid)

        self._obj_label = QLabel("Objective")
        self._obj_combo = QComboBox()
        self._obj_combo.setFixedWidth(200)
        self._obj_combo.currentIndexChanged.connect(self._on_objective_changed)
        self._obj_fov_lbl = QLabel("")
        self._obj_fov_lbl.setStyleSheet(_dim_style())

        self._obj_label.setVisible(False)
        self._obj_combo.setVisible(False)
        self._obj_fov_lbl.setVisible(False)

        obj_grid.addWidget(self._obj_label,   0, 0)
        obj_grid.addWidget(self._obj_combo,   0, 1)
        obj_grid.addWidget(self._obj_fov_lbl, 1, 1, 1, 2)

        # More Options
        from ui.widgets.more_options import MoreOptionsPanel
        self._opts_panel = MoreOptionsPanel(section_key="modality")
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
        self._opts_panel.addWidget(opts_inner)
        root.addWidget(self._opts_panel)
        root.addSpacing(16)

        # ── Workflow footer (Guided only) ───────────────────────────
        self._workflow_footer = WorkflowFooter(_NEXT_STEPS)
        self._workflow_footer.navigate_requested.connect(
            self.navigate_requested)
        root.addWidget(self._workflow_footer)

        root.addStretch()
        return page

    # ── Mode switching ──────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        """Toggle visibility of guidance elements based on mode.

        Guided:  show numbered step cards + workflow footer, hide compact card
        Compact: show compact card, hide step cards + footer
        """
        self._current_mode = mode
        is_guided = (mode == "guided")

        # Guided-only elements
        self._guide_card1.setVisible(is_guided)
        self._guide_card2.setVisible(is_guided)
        self._guide_card3.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._subtitle.setVisible(is_guided)

        # Compact-only element
        self._compact_card.setVisible(not is_guided)

    # ── Live preview ──────────────────────────────────────────────────

    def update_preview(self, frame) -> None:
        """Feed a camera frame into the preview thumbnail.

        Called from MainWindow._on_frame() on every frame.  Only every
        Nth frame (``_PREVIEW_DECIM``) is actually rendered to keep CPU
        usage negligible.
        """
        self._preview_frame_n += 1
        if self._preview_frame_n % _PREVIEW_DECIM != 0:
            return

        data = frame.data
        if data is None:
            return

        try:
            from acquisition.processing import to_display
            disp = to_display(data, mode="auto")

            if disp.ndim == 2:
                h, w = disp.shape
                disp = np.ascontiguousarray(disp)
                qi = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
            else:
                h, w = disp.shape[:2]
                qi = QImage(disp.tobytes(), w, h, w * 3, QImage.Format_RGB888)

            pix = QPixmap.fromImage(qi).scaled(
                _PREVIEW_W, _PREVIEW_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview_lbl.setPixmap(pix)
        except Exception:
            log.debug("Modality preview render failed", exc_info=True)
            return

        # Update caption with camera model
        self._preview_live = True
        cam = app_state.cam
        if cam is not None and hasattr(cam, "info"):
            model = getattr(cam.info, "model", "") or "Camera"
            self._preview_caption.setText(f"{model} Preview")
        else:
            self._preview_caption.setText("Live Preview")

    def _show_placeholder(self) -> None:
        """Render a generic microscope icon as the preview placeholder."""
        self._preview_live = False
        bg_col = QColor(PALETTE.get("bg", "#242424"))
        dim_col = QColor(PALETTE.get("textDim", "#888888"))

        canvas = QPixmap(_PREVIEW_W, _PREVIEW_H)
        canvas.fill(bg_col)

        icon = make_icon("mdi.microscope", color=dim_col.name(), size=80)
        if icon is None:
            icon = make_icon(IC.CAMERA, color=dim_col.name(), size=80)
        if icon is not None:
            icon_px = icon.pixmap(80, 80)
            p = QPainter(canvas)
            p.drawPixmap((_PREVIEW_W - 80) // 2, (_PREVIEW_H - 80) // 2, icon_px)
            p.end()

        self._preview_lbl.setPixmap(canvas)
        self._preview_caption.setText("No Preview")

    @staticmethod
    def _preview_frame_qss() -> str:
        return (
            f"QLabel {{"
            f"  background:{PALETTE.get('bg', '#242424')};"
            f"  border:1px solid {PALETTE.get('border', '#484848')};"
            f"  border-radius:6px;"
            f"}}")

    # ── Public API ─────────────────────────────────────────────────────

    def showEvent(self, event):
        """Refresh combos every time the section becomes visible."""
        super().showEvent(event)
        if app_state.cam is not None:
            self.refresh()

    def set_hardware_available(self, available: bool) -> None:
        self._stack.setCurrentIndex(1 if available else 0)
        if available:
            self.refresh()
        else:
            self._show_placeholder()

    def refresh(self) -> None:
        """Re-populate combos from current app_state."""
        self._refresh_camera_combo()
        self._refresh_turret()
        self._refresh_sensor_info()
        self._profile_picker.filter_by_modality(app_state.active_camera_type)

    # ── Camera combo ───────────────────────────────────────────────────

    def _refresh_camera_combo(self) -> None:
        self._cam_combo.blockSignals(True)
        self._cam_combo.clear()

        active = app_state.active_camera_type
        tr_drv = app_state.tr_cam
        ir_drv = app_state.ir_cam

        if ir_drv is not None:
            tr_model = getattr(getattr(tr_drv, 'info', None), 'model', 'TR Camera')
            ir_model = getattr(getattr(ir_drv, 'info', None), 'model', 'IR Camera')
            self._cam_combo.addItem(
                f"Thermoreflectance — {tr_model}", "tr")
            self._cam_combo.addItem(
                f"IR Lock-in — {ir_model}", "ir")
        elif tr_drv is not None:
            model = getattr(getattr(tr_drv, 'info', None), 'model', 'Camera')
            if active == "ir":
                self._cam_combo.addItem(
                    f"IR Lock-in — {model}", "ir")
            else:
                self._cam_combo.addItem(
                    f"Thermoreflectance — {model}", "tr")

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
        self._profile_picker.filter_by_modality(cam_type)
        self.modality_changed.emit(cam_type)

    def _on_profile_picked(self, profile) -> None:
        self.profile_selected.emit(profile)

    def _update_modality_desc(self, cam_type: str) -> None:
        name, desc = get_modality_info(cam_type)
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
        icon = make_icon(IC.LINK_OFF, color=dim, size=64)
        if icon:
            self._es_icon.setPixmap(icon.pixmap(64, 64))

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._modality_desc.setStyleSheet(_dim_style())
        self._obj_fov_lbl.setStyleSheet(_dim_style())
        self._sensor_lbl.setStyleSheet(_mono_style())
        self._subtitle.setStyleSheet(_dim_style())
        if hasattr(self, "_profile_picker"):
            self._profile_picker._apply_styles()
        if hasattr(self, "_es_btn"):
            self._apply_empty_state_styles()
        # Preview panel
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setStyleSheet(self._preview_frame_qss())
            self._preview_caption.setStyleSheet(_dim_style())
            if not self._preview_live:
                self._show_placeholder()
        # Guidance cards
        for card in self._all_guidance_cards():
            card._apply_styles()
        if hasattr(self, "_workflow_footer"):
            self._workflow_footer._apply_styles()
        self.update()

    def _all_guidance_cards(self) -> list[GuidanceCard]:
        """Return all guidance cards for bulk operations."""
        cards = []
        for attr in ("_guide_card1", "_guide_card2", "_guide_card3",
                      "_compact_card"):
            card = getattr(self, attr, None)
            if card is not None:
                cards.append(card)
        return cards
