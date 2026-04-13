"""
ui/tabs/modality_section.py  —  Measurement Setup section

Camera → Measurement Goal → Profile → Begin.
Phase 1 · CONFIGURATION

Layout: two-card architecture
  LEFT  — Configuration card: camera, goal, profile, objective, advanced, begin
  RIGHT — Preview card: live feed, camera identity, modality badge

Two presentation modes controlled by workspace mode:

  GUIDED  — numbered guidance cards above the two-card body
  COMPACT — compact help card above the two-card body

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
from ui.icons import IC, make_icon, set_btn_icon
from ui.widgets.profile_picker import ProfilePicker
from ui.guidance.cards import GuidanceCard, WorkflowFooter
from ui.guidance.content import (
    MODALITY_INFO as _MODALITY_INFO,
    get_section_cards,
    get_modality_info,
)
from ui.guidance.steps import next_steps_after
from ui.display_terms import TERMS

log = logging.getLogger(__name__)

# ── Measurement Goal definitions ──────────────────────────────────────
# Each goal: (id, title, subtitle, icon, navigate_to)
# Goals are filtered by camera type at runtime.

_GOALS_TR = [
    ("measurement",      "Measurement",         "Acquire thermal image",           "mdi.thermometer",       "Live View"),
    ("calibration",      "Calibration",          "Create or verify C_T map",        "mdi.chart-line",        "Calibration"),
    ("hotspot_detection","Hotspot Detection",    "Capture and analyse for defects", "mdi.target",            "Capture"),
    ("transient_series", "Transient Series",     "Time-resolved thermal response",  "mdi.chart-timeline",    "Transient"),
    ("dataset_analysis", "Data Set Analysis",    "Analyse saved sessions",          "mdi.folder-search",     "Sessions"),
]
_GOALS_IR = [
    ("measurement",      "Measurement",         "Acquire thermal image",           "mdi.thermometer",       "Live View"),
    ("calibration",      "Calibration",          "Create or verify emissivity map", "mdi.chart-line",        "Calibration"),
    ("hotspot_detection","Hotspot Detection",    "Capture and analyse for defects", "mdi.target",            "Capture"),
    ("dataset_analysis", "Data Set Analysis",    "Analyse saved sessions",          "mdi.folder-search",     "Sessions"),
]

def _goals_for(cam_type: str) -> list:
    """Return goal tuples appropriate for the camera type."""
    return _GOALS_IR if cam_type == "ir" else _GOALS_TR

# ── Preview constants ──────────────────────────────────────────────────
_PREVIEW_MIN_W  = 320       # preview minimum width
_PREVIEW_MIN_H  = 240       # preview minimum height (4:3 ratio)
_PREVIEW_DECIM  = 15        # update every Nth frame (~2 fps at 30 fps)

# Legacy aliases for external callers (if any)
_PREVIEW_W = _PREVIEW_MIN_W
_PREVIEW_H = _PREVIEW_MIN_H

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
    for s in next_steps_after("Measurement Setup", count=3)
]


# ── Helpers ────────────────────────────────────────────────────────────

def _mono_style() -> str:
    return (f"font-family:{MONO_FONT}; "
            f"font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")


def _dim_style() -> str:
    return f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;"


def _card_frame_qss() -> str:
    """Bordered card container QSS (reusable for left/right cards)."""
    return (
        f"QFrame#CardFrame {{"
        f"  background: {PALETTE['surface']};"
        f"  border: 1px solid {PALETTE['border']};"
        f"  border-radius: 8px;"
        f"}}")


def _separator() -> QFrame:
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {PALETTE['border']}; border: none;")
    return line


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
    scan_profile_selected = pyqtSignal(str, str)  # (uid, label) — ("", "") on clear

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

    # ── Controls page (two-card layout) ────────────────────────────────

    def _build_controls_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 8, 16, 12)
        root.setSpacing(0)

        # ── Compact help card (Standard/Expert) ────────────────────────
        # No standalone heading — sidebar already provides "Modality" context
        self._compact_card = GuidanceCard(
            card_id="modality.overview",
            title="Measurement Setup",
            body=_card_body("modality.overview"),
        )
        # Tighter padding for compact card — reduce visual weight
        self._compact_card.layout().setContentsMargins(12, 8, 12, 8)
        self._compact_card.layout().setSpacing(4)
        root.addWidget(self._compact_card)
        root.addSpacing(6)

        # ── Guided step cards (Guided mode only) ───────────────────────
        self._guide_card1 = GuidanceCard(
            card_id="modality.technique",
            title="Choose Your Measurement Technique",
            body=_card_body("modality.technique"),
            step_number=1,
        )
        root.addWidget(self._guide_card1)

        self._guide_card2 = GuidanceCard(
            card_id="modality.profile",
            title="Select a Measurement Profile",
            body=_card_body("modality.profile"),
            step_number=2,
        )
        root.addWidget(self._guide_card2)

        self._guide_card3 = GuidanceCard(
            card_id="modality.finetune",
            title="Fine-Tune (Optional)",
            body=_card_body("modality.finetune"),
            step_number=3,
        )
        root.addWidget(self._guide_card3)
        root.addSpacing(6)

        # ══════════════════════════════════════════════════════════════
        # Two-card body: LEFT = configuration, RIGHT = preview
        # ══════════════════════════════════════════════════════════════
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # ── LEFT CARD: Configuration ─────────────────────────────────
        left_card = QFrame()
        left_card.setObjectName("CardFrame")
        left_card.setStyleSheet(_card_frame_qss())
        # Content-hugging: Preferred height, not Expanding
        left_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        left_card.setMinimumWidth(340)

        lc = QVBoxLayout(left_card)
        lc.setContentsMargins(14, 12, 14, 12)
        lc.setSpacing(0)

        # ── Camera section ────────────────────────────────────────────
        cam_lbl = QLabel("Camera")
        cam_lbl.setStyleSheet(self._section_label_qss())
        lc.addWidget(cam_lbl)
        lc.addSpacing(2)

        # Multi-camera: combo selector
        self._cam_combo = QComboBox()
        self._cam_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cam_combo.currentIndexChanged.connect(self._on_camera_type_changed)
        lc.addWidget(self._cam_combo)

        # Single-camera: read-only identity row (hidden when multi)
        self._single_cam_row = QFrame()
        self._single_cam_row.setStyleSheet(
            f"QFrame {{ background:{PALETTE['surface']}; "
            f"border:1px solid {PALETTE['border']}; border-radius:4px; }}")
        scr_lay = QHBoxLayout(self._single_cam_row)
        scr_lay.setContentsMargins(8, 4, 8, 4)
        scr_lay.setSpacing(6)
        self._single_cam_label = QLabel("")
        self._single_cam_label.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE['text']}; "
            f"font-weight:500; border:none; background:transparent;")
        scr_lay.addWidget(self._single_cam_label, 1)
        self._single_cam_badge = QLabel("")
        self._single_cam_badge.setAlignment(Qt.AlignCenter)
        self._single_cam_badge.setFixedHeight(18)
        self._single_cam_badge.setMinimumWidth(32)
        self._single_cam_badge.setStyleSheet(
            f"font-size:{FONT.get('small', 8)}pt; font-weight:600; "
            f"border-radius:9px; padding:1px 6px; "
            f"background:{PALETTE['accent']}22; color:{PALETTE['accent']}; "
            f"border:none;")
        scr_lay.addWidget(self._single_cam_badge)
        self._single_cam_row.setVisible(False)
        lc.addWidget(self._single_cam_row)

        lc.addSpacing(2)

        self._modality_desc = QLabel("")
        self._modality_desc.setWordWrap(True)
        self._modality_desc.setStyleSheet(_dim_style())
        lc.addWidget(self._modality_desc)

        # ── Separator ─────────────────────────────────────────────────
        lc.addSpacing(4)
        self._sep1 = _separator()
        lc.addWidget(self._sep1)
        lc.addSpacing(4)

        # ── Measurement Goal section ──────────────────────────────────
        goal_lbl = QLabel("Measurement Goal")
        goal_lbl.setStyleSheet(self._section_label_qss())
        lc.addWidget(goal_lbl)
        lc.addSpacing(2)

        self._goal_combo = QComboBox()
        self._goal_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._goal_combo.currentIndexChanged.connect(self._on_goal_changed)
        lc.addWidget(self._goal_combo)

        self._goal_desc = QLabel("")
        self._goal_desc.setWordWrap(True)
        self._goal_desc.setStyleSheet(_dim_style())
        lc.addWidget(self._goal_desc)

        # ── Separator ─────────────────────────────────────────────────
        lc.addSpacing(4)
        self._sep_goal = _separator()
        lc.addWidget(self._sep_goal)
        lc.addSpacing(4)

        # ── Scan Profile section (camera-filtered) ────────────────────
        scan_lbl = QLabel(TERMS["recipe"])
        scan_lbl.setStyleSheet(self._section_label_qss())
        lc.addWidget(scan_lbl)
        lc.addSpacing(2)

        self._scan_combo = QComboBox()
        self._scan_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._scan_combo.setPlaceholderText(f"Select a {TERMS['recipe'].lower()}\u2026")
        self._scan_combo.currentIndexChanged.connect(self._on_scan_profile_changed)
        lc.addWidget(self._scan_combo)

        self._scan_desc = QLabel("")
        self._scan_desc.setWordWrap(True)
        self._scan_desc.setStyleSheet(_dim_style())
        lc.addWidget(self._scan_desc)

        lc.addSpacing(4)
        self._sep_scan = _separator()
        lc.addWidget(self._sep_scan)
        lc.addSpacing(4)

        # ── Material Profile section ──────────────────────────────────
        prof_lbl = QLabel("Material Profile")
        prof_lbl.setStyleSheet(self._section_label_qss())
        lc.addWidget(prof_lbl)
        lc.addSpacing(2)

        self._profile_picker = ProfilePicker()
        self._profile_picker.profile_selected.connect(self._on_profile_picked)
        self._profile_picker.custom_selected.connect(self.custom_selected)
        lc.addWidget(self._profile_picker)

        # ── Separator (hidden when no turret) ─────────────────────────
        lc.addSpacing(4)
        self._sep2 = _separator()
        lc.addWidget(self._sep2)
        lc.addSpacing(4)

        # ── Objective selector (hidden when no turret) ────────────────
        obj_grid = QGridLayout()
        obj_grid.setSpacing(4)
        obj_grid.setContentsMargins(0, 0, 0, 0)
        lc.addLayout(obj_grid)

        self._obj_label = QLabel("Objective")
        self._obj_label.setStyleSheet(self._section_label_qss())
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

        # ── More Options (directly in left card — not orphaned) ───────
        from ui.widgets.more_options import MoreOptionsPanel
        self._opts_panel = MoreOptionsPanel(section_key="modality")
        opts_inner = QWidget()
        opts_grid = QGridLayout(opts_inner)
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setSpacing(6)

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

        self._filter_label = QLabel("Wavelength Filter")
        opts_grid.addWidget(self._filter_label, 2, 0)
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["None", "470 nm", "530 nm", "550 nm",
                                      "590 nm", "625 nm", "650 nm", "850 nm"])
        self._filter_combo.setFixedWidth(120)
        opts_grid.addWidget(self._filter_combo, 2, 1)

        # FFC row — visible only when IR camera supports FFC
        self._ffc_label = QLabel("Flat-Field Correction")
        self._ffc_status = QLabel("—")
        self._ffc_status.setStyleSheet(_mono_style())
        self._ffc_run_btn = QPushButton("Run FFC")
        set_btn_icon(self._ffc_run_btn, "mdi.grid-off", PALETTE['warning'])
        self._ffc_run_btn.setFixedWidth(100)
        self._ffc_run_btn.setFixedHeight(28)
        self._ffc_run_btn.setToolTip(
            "Run Flat-Field Correction to recalibrate pixel offsets.\n"
            "Recommended before acquisition and after ambient temperature changes.")
        self._ffc_run_btn.clicked.connect(self._on_ffc)

        ffc_right = QHBoxLayout()
        ffc_right.setSpacing(8)
        ffc_right.addWidget(self._ffc_status)
        ffc_right.addWidget(self._ffc_run_btn)
        ffc_right.addStretch()
        opts_grid.addWidget(self._ffc_label, 3, 0)
        opts_grid.addLayout(ffc_right, 3, 1)

        # Initially hidden — shown by _refresh_ffc_row()
        self._ffc_label.setVisible(False)
        self._ffc_status.setVisible(False)
        self._ffc_run_btn.setVisible(False)

        self._opts_panel.addWidget(opts_inner)
        lc.addWidget(self._opts_panel)

        # ── Begin button ──────────────────────────────────────────────
        lc.addSpacing(8)
        self._begin_btn = QPushButton("  Begin Measurement")
        set_btn_icon(self._begin_btn, IC.PLAY,
                     color=PALETTE.get("ctaText", "#fff"))
        self._begin_btn.setMinimumHeight(36)
        self._begin_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._begin_btn.setCursor(Qt.PointingHandCursor)
        self._begin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['cta']}; "
            f"  color: {PALETTE.get('ctaText', '#fff')}; "
            f"  border: none; border-radius: 6px; "
            f"  font-size: {FONT['body']}pt; font-weight: 600; "
            f"  padding: 4px 16px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE.get('ctaHover', PALETTE['cta'])};"
            f"}}")
        self._begin_btn.clicked.connect(self._on_begin)
        lc.addWidget(self._begin_btn)

        body.addWidget(left_card, 3)

        # ── RIGHT CARD: Preview / Confirmation ───────────────────────
        right_card = QFrame()
        right_card.setObjectName("CardFrame")
        right_card.setStyleSheet(_card_frame_qss())
        right_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_card.setMinimumWidth(300)
        self._right_card = right_card

        rc = QVBoxLayout(right_card)
        rc.setContentsMargins(12, 12, 12, 12)
        rc.setSpacing(8)

        # Live preview (expanding)
        self._preview_lbl = QLabel()
        self._preview_lbl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_lbl.setMinimumSize(_PREVIEW_MIN_W, _PREVIEW_MIN_H)
        self._preview_lbl.setAlignment(Qt.AlignCenter)
        self._preview_lbl.setStyleSheet(self._preview_frame_qss())
        rc.addWidget(self._preview_lbl, 1)

        # ── Info footer (confirmation panel) ──────────────────────────
        self._preview_sep = _separator()
        rc.addWidget(self._preview_sep)
        rc.addSpacing(4)

        # Footer label — anchors the confirmation panel
        self._footer_label = QLabel("Active Camera")
        self._footer_label.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            f"font-weight:500; text-transform:uppercase; letter-spacing:0.5px;")
        rc.addWidget(self._footer_label)
        rc.addSpacing(2)

        # Camera identity (bold, prominent — primary anchor)
        self._cam_identity_lbl = QLabel("")
        self._cam_identity_lbl.setAlignment(Qt.AlignLeft)
        self._cam_identity_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; color:{PALETTE['text']}; "
            f"font-weight:600;")
        rc.addWidget(self._cam_identity_lbl)

        # Camera detail line (resolution, pixel format — mono)
        self._cam_detail_lbl = QLabel("")
        self._cam_detail_lbl.setAlignment(Qt.AlignLeft)
        self._cam_detail_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; "
            f"color:{PALETTE['textDim']};")
        rc.addWidget(self._cam_detail_lbl)
        rc.addSpacing(4)

        # Modality badge + status caption row
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)

        self._modality_badge = QLabel("TR")
        self._modality_badge.setAlignment(Qt.AlignCenter)
        self._modality_badge.setFixedHeight(22)
        self._modality_badge.setMinimumWidth(80)
        self._modality_badge.setMaximumWidth(160)
        self._apply_badge_style("tr")
        badge_row.addWidget(self._modality_badge)
        badge_row.addStretch()

        self._preview_caption = QLabel("No Preview")
        self._preview_caption.setAlignment(Qt.AlignRight)
        self._preview_caption.setStyleSheet(_dim_style())
        badge_row.addWidget(self._preview_caption)

        rc.addLayout(badge_row)

        body.addWidget(right_card, 3)

        root.addSpacing(10)

        # ── Workflow footer (Guided only) ───────────────────────────
        self._workflow_footer = WorkflowFooter(_NEXT_STEPS)
        self._workflow_footer.navigate_requested.connect(
            self.navigate_requested)
        root.addWidget(self._workflow_footer)

        return page

    # ── Auto-config info banner ────────────────────────────────────

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

        # Compact-only element
        self._compact_card.setVisible(not is_guided)

    # ── Modality badge ─────────────────────────────────────────────────

    def _apply_badge_style(self, cam_type: str) -> None:
        """Apply colored pill style to the modality badge."""
        if cam_type == "ir":
            bg = PALETTE.get("warning", "#ff9f0a")
            text = "IR Lock-in"
        else:
            bg = PALETTE.get("accent", "#00d4aa")
            text = "Thermoreflectance"
        self._modality_badge.setText(text)
        self._modality_badge.setStyleSheet(
            f"background: {bg}22; color: {bg}; "
            f"border: 1px solid {bg}44; border-radius: 10px; "
            f"font-size: {FONT['sublabel']}pt; font-weight: 600; "
            f"padding: 2px 10px;")

    def _refresh_preview_card_info(self) -> None:
        """Update camera identity + detail in the preview card."""
        cam = app_state.cam
        cam_type = getattr(app_state, "active_camera_type", "tr")
        if cam is not None and hasattr(cam, "info"):
            model = getattr(cam.info, "model", "") or "Camera"
            w = getattr(cam.info, "width", 0)
            h = getattr(cam.info, "height", 0)
            self._cam_identity_lbl.setText(model)
            if w and h:
                fmt = getattr(cam.info, "pixel_format", "")
                detail = f"{w} × {h}"
                if fmt:
                    detail += f"  ·  {fmt}"
                self._cam_detail_lbl.setText(detail)
            else:
                self._cam_detail_lbl.setText("")
        else:
            self._cam_identity_lbl.setText("No camera")
            self._cam_detail_lbl.setText("")
        self._apply_badge_style(cam_type)

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

        # Get the actual display size of the preview label
        pw = self._preview_lbl.width()
        ph = self._preview_lbl.height()
        # Fallback to minimums if not yet laid out
        if pw < 10:
            pw = _PREVIEW_MIN_W
        if ph < 10:
            ph = _PREVIEW_MIN_H

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
                pw, ph,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview_lbl.setPixmap(pix)
        except Exception:
            log.debug("Modality preview render failed", exc_info=True)
            return

        # Update caption
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

        pw = self._preview_lbl.width()
        ph = self._preview_lbl.height()
        if pw < 10:
            pw = _PREVIEW_MIN_W
        if ph < 10:
            ph = _PREVIEW_MIN_H

        bg_col = QColor(PALETTE['bg'])
        dim_col = QColor(PALETTE['textDim'])

        canvas = QPixmap(pw, ph)
        canvas.fill(bg_col)

        icon = make_icon("mdi.microscope", color=dim_col.name(), size=80)
        if icon is None:
            icon = make_icon(IC.CAMERA, color=dim_col.name(), size=80)
        if icon is not None:
            icon_px = icon.pixmap(80, 80)
            p = QPainter(canvas)
            p.drawPixmap((pw - 80) // 2, (ph - 80) // 2, icon_px)
            p.end()

        self._preview_lbl.setPixmap(canvas)
        self._preview_caption.setText("No Preview")

    @staticmethod
    def _preview_frame_qss() -> str:
        return (
            f"QLabel {{"
            f"  background:{PALETTE['bg']};"
            f"  border:1px solid {PALETTE['border']};"
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
        self._refresh_camera_combo()   # also calls _refresh_goals()
        self._refresh_turret()
        self._refresh_sensor_info()
        self._refresh_modality_controls()
        self._refresh_ffc_row()
        self._refresh_preview_card_info()
        self._profile_picker.filter_by_modality(app_state.active_camera_type)

    # ── Camera combo ───────────────────────────────────────────────────

    def _refresh_camera_combo(self) -> None:
        self._cam_combo.blockSignals(True)
        self._cam_combo.clear()

        active = app_state.active_camera_type
        tr_drv = app_state.tr_cam
        ir_drv = app_state.ir_cam

        multi_camera = ir_drv is not None and tr_drv is not None

        if multi_camera:
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

        # Single-camera: show read-only identity row instead of combo
        if not multi_camera and (tr_drv is not None or ir_drv is not None):
            drv = tr_drv or ir_drv
            model = getattr(getattr(drv, 'info', None), 'model', 'Camera')
            badge_text = "IR" if active == "ir" else "TR"
            self._single_cam_label.setText(model)
            self._single_cam_badge.setText(badge_text)
            # Badge color
            if active == "ir":
                bc = PALETTE.get("warning", "#ff9f0a")
            else:
                bc = PALETTE.get("accent", "#00d4aa")
            self._single_cam_badge.setStyleSheet(
                f"font-size:{FONT.get('small', 8)}pt; font-weight:600; "
                f"border-radius:9px; padding:1px 6px; "
                f"background:{bc}22; color:{bc}; border:none;")
            self._cam_combo.setVisible(False)
            self._single_cam_row.setVisible(True)
        else:
            self._cam_combo.setVisible(True)
            self._single_cam_row.setVisible(False)

        self._update_modality_desc(active)
        self._cam_combo.blockSignals(False)
        # Refresh goals and scan profiles for current camera type
        self._refresh_goals(active)
        self._refresh_scan_profiles(active)

    def _on_camera_type_changed(self, index: int) -> None:
        if index < 0:
            return
        cam_type = self._cam_combo.itemData(index)
        if cam_type is None:
            return
        app_state.active_camera_type = cam_type
        self._update_modality_desc(cam_type)
        self._refresh_goals(cam_type)
        self._refresh_sensor_info()
        self._refresh_modality_controls()
        self._refresh_ffc_row()
        self._refresh_preview_card_info()
        self._profile_picker.filter_by_modality(cam_type)
        self._refresh_scan_profiles(cam_type)
        self.modality_changed.emit(cam_type)

    # ── Measurement Goal ──────────────────────────────────────────────

    def _refresh_goals(self, cam_type: str) -> None:
        """Populate the goal combo for the active camera type."""
        self._goal_combo.blockSignals(True)
        self._goal_combo.clear()
        for gid, title, subtitle, icon, nav in _goals_for(cam_type):
            self._goal_combo.addItem(title, userData=(gid, subtitle, icon, nav))
        self._goal_combo.setCurrentIndex(0)
        self._goal_combo.blockSignals(False)
        self._on_goal_changed(0)

    def _on_goal_changed(self, index: int) -> None:
        """Handle goal selection change — update subtitle + begin button."""
        if index < 0:
            return
        data = self._goal_combo.itemData(index)
        if data is None:
            return
        gid, subtitle, icon, nav = data
        self._goal_desc.setText(subtitle)
        # Update Begin button text
        goal_title = self._goal_combo.currentText()
        self._begin_btn.setText(f"  Begin {goal_title}")
        set_btn_icon(self._begin_btn, icon,
                     color=PALETTE.get("ctaText", "#fff"))

    def _on_begin(self) -> None:
        """Handle Begin button click — navigate to the goal's target panel."""
        index = self._goal_combo.currentIndex()
        if index < 0:
            return
        data = self._goal_combo.itemData(index)
        if data is None:
            return
        gid, subtitle, icon, nav = data
        self.navigate_requested.emit(nav)

    # ── Scan Profile (camera-filtered) ────────────────────────────────

    _CAM_TO_MODALITY = {"tr": "thermoreflectance", "ir": "ir_lockin"}

    def _refresh_scan_profiles(self, cam_type: str) -> None:
        """Populate the scan profile combo filtered by camera modality."""
        from acquisition.recipe_tab import RecipeStore
        self._scan_combo.blockSignals(True)
        self._scan_combo.clear()

        modality = self._CAM_TO_MODALITY.get(cam_type, "thermoreflectance")
        try:
            recipes = RecipeStore().list()
        except Exception:
            recipes = []

        matching = [r for r in recipes
                    if r.acquisition.modality == modality]

        for recipe in matching:
            suffix = " \U0001f512" if recipe.locked else ""
            self._scan_combo.addItem(
                f"{recipe.label}{suffix}",
                userData=(recipe.uid, recipe.label))

        if not matching:
            self._scan_desc.setText(
                f"No {TERMS['recipe_plural'].lower()} for this camera.")
        else:
            self._scan_desc.setText("")

        self._scan_combo.setCurrentIndex(-1)  # no selection
        self._scan_combo.blockSignals(False)
        self.scan_profile_selected.emit("", "")  # clear on camera change

    def _on_scan_profile_changed(self, index: int) -> None:
        """Handle scan profile selection change."""
        if index < 0:
            self._scan_desc.setText("")
            self.scan_profile_selected.emit("", "")
            return
        data = self._scan_combo.itemData(index)
        if data is None:
            self.scan_profile_selected.emit("", "")
            return
        uid, label = data
        self.scan_profile_selected.emit(uid, label)
        # Show key parameters
        from acquisition.recipe_tab import RecipeStore
        try:
            store = RecipeStore()
            for r in store.list():
                if r.uid == uid:
                    parts = []
                    parts.append(f"{r.camera.n_frames} frames")
                    parts.append(f"{r.camera.exposure_us:.0f} \u00b5s")
                    if r.tec.enabled:
                        parts.append(f"TEC {r.tec.setpoint_c:.0f}\u00b0C")
                    if r.bias.enabled:
                        parts.append(f"Bias {r.bias.voltage_v:.1f}V")
                    self._scan_desc.setText("  \u00b7  ".join(parts))
                    break
        except Exception:
            pass

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

        # Show/hide the separator above objectives
        self._sep2.setVisible(has_turret)

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

    # ── FFC controls (IR cameras only) ───────────────────────────────

    def _ffc_camera(self):
        """Return the FFC-capable camera, only when IR modality is active."""
        if getattr(app_state, "active_camera_type", "tr") != "ir":
            return None
        for c in (app_state.cam, getattr(app_state, "ir_cam", None)):
            if c is not None and getattr(c, "supports_ffc", lambda: False)():
                return c
        return None

    def _refresh_modality_controls(self) -> None:
        """Show/hide controls based on active camera type (TR vs IR)."""
        is_ir = getattr(app_state, "active_camera_type", "tr") == "ir"
        # Wavelength filter — TR only (IR cameras use fixed thermal band)
        self._filter_label.setVisible(not is_ir)
        self._filter_combo.setVisible(not is_ir)

    def _refresh_ffc_row(self) -> None:
        """Show/hide FFC row and update status text."""
        import time as _t
        cam = self._ffc_camera()
        visible = cam is not None
        self._ffc_label.setVisible(visible)
        self._ffc_status.setVisible(visible)
        self._ffc_run_btn.setVisible(visible)
        if not visible:
            return

        last = getattr(cam, "last_ffc_time", None)
        if last is None:
            self._ffc_status.setText("Not run this session")
            self._ffc_status.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; "
                f"color:{PALETTE['warning']};")
        else:
            age_min = (_t.time() - last) / 60.0
            if age_min < 60:
                self._ffc_status.setText(f"Current ({age_min:.0f} min ago)")
                self._ffc_status.setStyleSheet(_mono_style())
            else:
                self._ffc_status.setText(f"Stale ({age_min:.0f} min ago)")
                self._ffc_status.setStyleSheet(
                    f"font-family:{MONO_FONT}; font-size:{FONT['readoutSm']}pt; "
                    f"color:{PALETTE['warning']};")

    def _on_ffc(self) -> None:
        """Run FFC on a background thread."""
        cam = self._ffc_camera()
        if cam is None:
            return

        self._ffc_run_btn.setEnabled(False)
        self._ffc_run_btn.setText("Running…")

        def _run():
            try:
                ok = cam.do_ffc()
            except Exception:
                ok = False
            QTimer.singleShot(0, lambda: self._on_ffc_done(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _on_ffc_done(self, success: bool) -> None:
        self._ffc_run_btn.setEnabled(True)
        self._ffc_run_btn.setText("Run FFC")
        self._refresh_ffc_row()

    # ── Empty state ────────────────────────────────────────────────────

    def _build_empty_state(self) -> QWidget:
        from ui.widgets.empty_state import build_empty_state
        return build_empty_state(
            title="Camera Not Connected",
            description="Connect a camera in Device Manager to begin "
                        "measurement setup.",
            on_action=self.open_device_manager.emit,
        )

    # ── Theme ──────────────────────────────────────────────────────────

    @staticmethod
    def _section_label_qss() -> str:
        """Consistent section label style for left-card headings."""
        return (f"font-size:{FONT['label']}pt; font-weight:600; "
                f"color:{PALETTE['text']};")

    def _apply_styles(self) -> None:
        self._modality_desc.setStyleSheet(_dim_style())
        self._goal_desc.setStyleSheet(_dim_style())
        self._obj_fov_lbl.setStyleSheet(_dim_style())
        self._sensor_lbl.setStyleSheet(_mono_style())
        # Begin button
        self._begin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['cta']}; "
            f"  color: {PALETTE.get('ctaText', '#fff')}; "
            f"  border: none; border-radius: 6px; "
            f"  font-size: {FONT['body']}pt; font-weight: 600; "
            f"  padding: 4px 16px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE.get('ctaHover', PALETTE['cta'])};"
            f"}}")
        # Section labels in left card
        for child in self.findChildren(QLabel):
            if child.text() in ("Camera", "Measurement Goal", "Profile", "Objective"):
                child.setStyleSheet(self._section_label_qss())
        if hasattr(self, "_profile_picker"):
            self._profile_picker._apply_styles()
        # Card frames
        card_qss = _card_frame_qss()
        for attr in ("_right_card",):
            card = getattr(self, attr, None)
            if card is not None:
                card.setStyleSheet(card_qss)
        # Find left card by walking children
        for child in self.findChildren(QFrame, "CardFrame"):
            child.setStyleSheet(card_qss)
        # Separators
        for sep in (self._sep1, self._sep_goal, self._sep2, self._preview_sep):
            sep.setStyleSheet(
                f"background: {PALETTE['border']}; border: none;")
        # Preview panel
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setStyleSheet(self._preview_frame_qss())
            self._preview_caption.setStyleSheet(_dim_style())
            if not self._preview_live:
                self._show_placeholder()
        # Preview card info
        if hasattr(self, "_footer_label"):
            self._footer_label.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
                f"font-weight:500; text-transform:uppercase; letter-spacing:0.5px;")
        if hasattr(self, "_cam_identity_lbl"):
            self._cam_identity_lbl.setStyleSheet(
                f"font-size:{FONT['body']}pt; color:{PALETTE['text']}; "
                f"font-weight:600;")
            self._cam_detail_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; "
                f"color:{PALETTE['textDim']};")
        # Badge
        if hasattr(self, "_modality_badge"):
            cam_type = getattr(app_state, "active_camera_type", "tr")
            self._apply_badge_style(cam_type)
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
