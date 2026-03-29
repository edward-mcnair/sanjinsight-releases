"""
acquisition/recipe.py  +  acquisition/recipe_tab.py  (combined module)

Measurement Recipe System for the Microsanj Thermal Analysis System.

A Recipe captures a complete measurement protocol:
  - Material profile selection
  - Camera settings (exposure, gain, ROI)
  - Acquisition parameters (n_frames, inter_phase_delay)
  - Analysis configuration (threshold, verdict rules)
  - Bias / TEC conditions
  - Optional descriptive notes

Engineers define recipes once; technicians select one from the list and
press RUN.  No manual parameter entry required.

Storage
-------
    ~/.microsanj/recipes/<name>.json

Usage
-----
    from acquisition.recipe import Recipe, RecipeStore
    from acquisition.recipe_tab import RecipeTab

    # Save a recipe
    recipe = Recipe.capture_current(app_state, label="GaN_100mA_25C")
    RecipeStore.save(recipe)

    # Run a recipe
    store   = RecipeStore()
    recipes = store.list()
    recipe  = store.load("GaN_100mA_25C")
    recipe.apply(app_state, main_window)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_RECIPES_DIR = Path.home() / ".microsanj" / "recipes"


# ================================================================== #
#  Recipe data model                                                   #
# ================================================================== #

@dataclass
class RecipeCamera:
    exposure_us: float = 5000.0
    gain_db:     float = 0.0
    n_frames:    int   = 16
    roi:         Optional[Dict[str, int]] = None   # {x, y, w, h} or None

@dataclass
class RecipeAcquisition:
    inter_phase_delay_s: float = 0.1
    modality:            str   = "thermoreflectance"
    wavelength_nm:       int   = 532

@dataclass
class RecipeAnalysis:
    threshold_k:          float = 5.0
    fail_hotspot_count:   int   = 3
    fail_peak_k:          float = 20.0
    fail_area_fraction:   float = 0.05
    warn_hotspot_count:   int   = 1
    warn_peak_k:          float = 10.0
    warn_area_fraction:   float = 0.01

@dataclass
class RecipeBias:
    enabled:    bool  = False
    voltage_v:  float = 0.0
    current_a:  float = 0.0

@dataclass
class RecipeTec:
    enabled:      bool  = False
    setpoint_c:   float = 25.0

@dataclass
class Recipe:
    uid:         str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label:       str = ""
    description: str = ""
    created_at:  str = ""
    version:     int = 1

    profile_name: str = ""          # Name of MaterialProfile to activate
    camera:       RecipeCamera      = field(default_factory=RecipeCamera)
    acquisition:  RecipeAcquisition = field(default_factory=RecipeAcquisition)
    analysis:     RecipeAnalysis    = field(default_factory=RecipeAnalysis)
    bias:         RecipeBias        = field(default_factory=RecipeBias)
    tec:          RecipeTec         = field(default_factory=RecipeTec)
    notes:        str = ""

    # ── Operator workflow (Phase D) ─────────────────────────────────────
    locked:      bool = False   # True = operator-executable, editing disabled
    approved_by: str  = ""      # display_name of approving engineer/admin
    approved_at: str  = ""      # ISO timestamp of lock action
    scan_type:   str  = "autoscan"  # "autoscan" | "single" | "transient"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        def _filter(dc_cls, raw: dict) -> dict:
            """Strip unknown keys to avoid TypeError on version mismatch."""
            known = {f for f in dc_cls.__dataclass_fields__}
            return {k: v for k, v in raw.items() if k in known}

        r = cls()
        r.uid          = d.get("uid",         r.uid)
        r.label        = d.get("label",        "")
        r.description  = d.get("description",  "")
        r.created_at   = d.get("created_at",   "")
        r.version      = d.get("version",       1)
        r.profile_name = d.get("profile_name", "")
        r.notes        = d.get("notes",         "")
        r.locked       = bool(d.get("locked",      False))
        r.approved_by  = d.get("approved_by",  "")
        r.approved_at  = d.get("approved_at",  "")
        r.scan_type    = d.get("scan_type",    "autoscan")
        r.camera       = RecipeCamera(**_filter(RecipeCamera,      d.get("camera",      {})))
        r.acquisition  = RecipeAcquisition(**_filter(RecipeAcquisition, d.get("acquisition", {})))
        r.analysis     = RecipeAnalysis(**_filter(RecipeAnalysis,  d.get("analysis",   {})))
        r.bias         = RecipeBias(**_filter(RecipeBias,          d.get("bias",        {})))
        r.tec          = RecipeTec(**_filter(RecipeTec,            d.get("tec",         {})))
        return r

    @classmethod
    def from_current_state(cls, app_state, label: str = "") -> "Recipe":
        """
        Snapshot the current app_state into a new Recipe.

        Parameters are read from app_state where available; sensible
        defaults are used for anything not yet connected.
        """
        r = cls()
        r.label      = label or f"recipe_{int(time.time())}"
        r.created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # Profile
        prof = getattr(app_state, "active_profile", None)
        if prof:
            r.profile_name = getattr(prof, "name", "")

        # Camera
        cam = getattr(app_state, "cam", None)
        if cam:
            try:
                r.camera.exposure_us = cam.get_exposure()
                r.camera.gain_db     = cam.get_gain()
            except Exception:
                pass

        # Modality
        modality = getattr(app_state, "active_modality", "thermoreflectance")
        r.acquisition.modality = modality

        # Analysis from active analysis config
        analysis = getattr(app_state, "active_analysis", None)
        if analysis:
            cfg = getattr(analysis, "config", None)
            if cfg:
                r.analysis.threshold_k        = getattr(cfg, "threshold_k",        5.0)
                r.analysis.fail_hotspot_count = getattr(cfg, "fail_hotspot_count",  3)
                r.analysis.fail_peak_k        = getattr(cfg, "fail_peak_k",        20.0)
                r.analysis.fail_area_fraction = getattr(cfg, "fail_area_fraction", 0.05)

        return r


# ================================================================== #
#  RecipeStore — persistence layer                                     #
# ================================================================== #

class RecipeStore:
    """Load / save recipes from ~/.microsanj/recipes/."""

    def __init__(self, directory: Path = None):
        self._dir = Path(directory) if directory else _RECIPES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> List[Recipe]:
        """Return all saved recipes, sorted by label."""
        recipes = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                with open(p) as f:
                    recipes.append(Recipe.from_dict(json.load(f)))
            except Exception as e:
                log.warning("Skipping malformed recipe %s: %s", p.name, e)
        return sorted(recipes, key=lambda r: r.label.lower())

    def save(self, recipe: Recipe) -> Path:
        """Persist a recipe.  Filename is derived from the label."""
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in recipe.label).strip("_") or recipe.uid
        path = self._dir / f"{safe_label}.json"
        with open(path, "w") as f:
            json.dump(recipe.to_dict(), f, indent=2)
        log.info("Recipe saved → %s", path)
        return path

    def delete(self, recipe: Recipe) -> None:
        """Delete a recipe file by label."""
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in recipe.label).strip("_") or recipe.uid
        path = self._dir / f"{safe_label}.json"
        if path.exists():
            path.unlink()
            log.info("Recipe deleted: %s", path)

    def load(self, label: str) -> Optional[Recipe]:
        """Load a recipe by label string."""
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in label).strip("_")
        path = self._dir / f"{safe_label}.json"
        if path.exists():
            with open(path) as f:
                return Recipe.from_dict(json.load(f))
        return None


# ================================================================== #
#  RecipeTab — UI panel                                               #
# ================================================================== #

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QLineEdit, QTextEdit,
    QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox,
    QMessageBox, QFrame, QComboBox, QDialog, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT


class RecipeTab(QWidget):
    """
    Recipe manager panel for the Microsanj Manual mode tab bar.

    Signals
    -------
    recipe_run(recipe):  Emitted when the user clicks RUN for a recipe.
                         The main window should connect this to apply the
                         recipe to the hardware and start acquisition.
    """

    recipe_run = pyqtSignal(object)   # Recipe instance

    def __init__(self, app_state=None, parent=None):
        super().__init__(parent)
        self._app_state    = app_state
        self._store        = RecipeStore()
        self._current:     Optional[Recipe] = None
        self._auth_session = None   # set by main_app after login
        self._build()
        self._refresh_list()

    # ── UI ──────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ─ Left: recipe list ─
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)

        self._list_hdr = QLabel("Saved Scan Profiles")
        list_hdr = self._list_hdr
        list_hdr.setStyleSheet(f"color:#ccc; font-size:{FONT['heading']}pt; font-weight:600;")
        left_lay.addWidget(list_hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{ background:#141414; color:#ccc; border:1px solid #2a2a2a;
                          font-size:{FONT['label']}pt; font-family:{MONO_FONT}; }}
            QListWidget::item:selected {{ background:#0d3a52; color:#fff; }}
            QListWidget::item:hover    {{ background:#1a2a2a; }}
        """)
        self._list.currentRowChanged.connect(self._on_select)
        left_lay.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._new_btn    = QPushButton("New")
        set_btn_icon(self._new_btn, "fa5s.plus")
        self._delete_btn = QPushButton("Delete")
        set_btn_icon(self._delete_btn, "fa5s.trash", "#ff6666")
        self._run_btn    = QPushButton("RUN")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setStyleSheet(
            "background:#006b40; color:#fff; font-weight:600; border-radius:3px;")
        self._compare_btn = QPushButton("Compare…")
        set_btn_icon(self._compare_btn, "fa5s.exchange-alt")
        self._compare_btn.setFixedHeight(28)
        for b in [self._new_btn, self._delete_btn, self._run_btn, self._compare_btn]:
            b.setFixedHeight(28)
            btn_row.addWidget(b)
        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn.clicked.connect(self._on_delete)
        self._run_btn.clicked.connect(self._on_run)
        self._compare_btn.clicked.connect(self._on_compare)
        left_lay.addLayout(btn_row)

        self._preset_btn = QPushButton("Load Preset…")
        set_btn_icon(self._preset_btn, "fa5s.folder-open")
        self._preset_btn.setFixedHeight(28)
        self._preset_btn.setToolTip(
            "Load a factory preset into the editor as a starting point.\n"
            "Rename and save it to create your own scan profile."
        )
        self._preset_btn.clicked.connect(self._on_load_preset)
        left_lay.addWidget(self._preset_btn)

        splitter.addWidget(left)

        # ─ Right: recipe editor ─
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        self._right_hdr = QLabel("Scan Profile Editor")
        right_hdr = self._right_hdr
        right_hdr.setStyleSheet(f"color:#ccc; font-size:{FONT['heading']}pt; font-weight:600;")
        right_lay.addWidget(right_hdr)

        # Identity
        id_box = QGroupBox("Identity")
        id_box.setStyleSheet(self._box_style())
        id_form = QFormLayout(id_box)
        self._label_edit = QLineEdit()
        self._desc_edit  = QLineEdit()
        self._prof_edit  = QLineEdit()
        self._prof_edit.setPlaceholderText("e.g. GaN on SiC")
        id_form.addRow("Label:", self._label_edit)
        id_form.addRow("Description:", self._desc_edit)
        id_form.addRow("Profile name:", self._prof_edit)
        right_lay.addWidget(id_box)

        # Camera / Acquisition
        cam_box = QGroupBox("Camera + Acquisition")
        cam_box.setStyleSheet(self._box_style())
        cam_form = QFormLayout(cam_box)
        self._exposure_spin = QDoubleSpinBox()
        self._exposure_spin.setRange(1, 1_000_000)
        self._exposure_spin.setValue(5000)
        self._exposure_spin.setSuffix(" µs")
        self._exposure_spin.setToolTip(
            "Camera exposure time per frame.\n"
            "Higher = more signal, more blur risk.\n"
            "Typical range: 1000–50000 µs."
        )
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(0, 48)
        self._gain_spin.setSuffix(" dB")
        self._gain_spin.setToolTip(
            "Camera analogue gain.\n"
            "Increase only if exposure cannot be raised further.\n"
            "0 dB = no gain amplification."
        )
        self._frames_spin = QSpinBox()
        self._frames_spin.setRange(1, 1000)
        self._frames_spin.setValue(16)
        self._frames_spin.setToolTip(
            "Number of hot+cold frame pairs to average.\n"
            "More frames = lower noise but longer acquisition.\n"
            "Typical: 16–64."
        )
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0, 60)
        self._delay_spin.setValue(0.1)
        self._delay_spin.setSuffix(" s")
        self._delay_spin.setToolTip(
            "Settling time between the cold and hot acquisition phases.\n"
            "Increase if the bias source takes time to stabilise.\n"
            "Typical: 0.05–0.5 s."
        )
        self._modality_combo = QComboBox()
        self._modality_combo.addItems(["thermoreflectance", "ir_lockin", "hybrid", "opp"])
        self._modality_combo.setToolTip(
            "Imaging modality.\n"
            "thermoreflectance: standard ΔR/R for thermal maps.\n"
            "ir_lockin: mid-wave IR lock-in mode.\n"
            "hybrid / opp: contact Microsanj for application notes."
        )
        cam_form.addRow("Exposure:", self._exposure_spin)
        cam_form.addRow("Gain:", self._gain_spin)
        cam_form.addRow("Frames:", self._frames_spin)
        cam_form.addRow("Inter-phase delay:", self._delay_spin)
        cam_form.addRow("Modality:", self._modality_combo)
        right_lay.addWidget(cam_box)

        # Analysis
        an_box = QGroupBox("Pass / Fail Analysis")
        an_box.setStyleSheet(self._box_style())
        an_form = QFormLayout(an_box)
        self._thresh_spin = QDoubleSpinBox()
        self._thresh_spin.setRange(0.001, 1000)
        self._thresh_spin.setValue(5.0)
        self._thresh_spin.setSuffix(" °C")
        self._thresh_spin.setToolTip(
            "Minimum ΔT to be counted as a hotspot.\n"
            "Pixels below this value are ignored in verdict logic.\n"
            "Typical: 2–10 °C."
        )
        self._fail_hs_spin    = QSpinBox()
        self._fail_hs_spin.setRange(1, 10000)
        self._fail_hs_spin.setValue(3)
        self._fail_hs_spin.setToolTip(
            "Maximum number of hotspot regions allowed before FAIL verdict.\n"
            "Set to 1 for zero-defect inspection; higher values allow benign hot spots."
        )
        self._fail_peak_spin  = QDoubleSpinBox()
        self._fail_peak_spin.setRange(0, 1000)
        self._fail_peak_spin.setValue(20.0)
        self._fail_peak_spin.setSuffix(" °C")
        self._fail_peak_spin.setToolTip(
            "Maximum allowable single-pixel peak temperature rise.\n"
            "Exceeding this threshold triggers an immediate FAIL verdict regardless of hotspot count."
        )
        an_form.addRow("Threshold:", self._thresh_spin)
        an_form.addRow("Fail: hotspot count ≥", self._fail_hs_spin)
        an_form.addRow("Fail: peak ΔT ≥", self._fail_peak_spin)
        right_lay.addWidget(an_box)

        # Notes
        notes_box = QGroupBox("Notes")
        notes_box.setStyleSheet(self._box_style())
        notes_lay = QVBoxLayout(notes_box)
        self._notes_edit = QTextEdit()
        self._notes_edit.setFixedHeight(70)
        self._notes_edit.setStyleSheet(
            f"background:#111; color:#ccc; font-size:{FONT['label']}pt; border:none;")
        notes_lay.addWidget(self._notes_edit)
        right_lay.addWidget(notes_box)

        # ── Lock banner (hidden until recipe is locked) ────────────────
        self._lock_banner = QLabel()
        self._lock_banner.setAlignment(Qt.AlignCenter)
        self._lock_banner.setFixedHeight(26)
        self._lock_banner.setStyleSheet(
            f"background:{PALETTE.get('accent','#00d4aa')}22; "
            f"color:{PALETTE.get('accent','#00d4aa')}; "
            "border:1px solid #00d4aa55; border-radius:4px; "
            f"font-size:{FONT.get('sublabel', 9)}pt; font-weight:600;")
        self._lock_banner.setVisible(False)
        right_lay.addWidget(self._lock_banner)

        # Save / Capture buttons
        footer = QHBoxLayout()
        right_lay.addLayout(footer)

        self._save_btn = QPushButton("Save Scan Profile")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._cap_btn  = QPushButton("Capture Current Settings")
        set_btn_icon(self._cap_btn, "fa5s.camera")
        self._cap_btn.setToolTip(
            "Read current camera / analysis / profile settings from the app "
            "and populate this scan profile automatically.")
        self._lock_btn = QPushButton("Approve && Lock")
        set_btn_icon(self._lock_btn, "fa5s.lock")
        self._lock_btn.setToolTip(
            "Lock this scan profile so operators can run it. "
            "Locked scan profiles cannot be edited without unlocking first.")
        for b in [self._save_btn, self._cap_btn]:
            b.setFixedHeight(28)
            footer.addWidget(b)
        footer.addStretch(1)
        self._lock_btn.setFixedHeight(28)
        footer.addWidget(self._lock_btn)
        self._save_btn.clicked.connect(self._on_save)
        self._cap_btn.clicked.connect(self._on_capture)
        self._lock_btn.clicked.connect(self._on_lock_toggle)

        right_lay.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([280, 560])

        self._set_editor_enabled(False)

    @staticmethod
    def _box_style() -> str:
        P = PALETTE
        sur = P.get("surface",  "#1a1d28")
        bdr = P.get("border",   "#2e3245")
        dim = P.get("textDim",  "#8892aa")
        txt = P.get("text",     "#dde3f2")
        su2 = P.get("surface2", "#20232e")
        return (
            f"QGroupBox {{ color:{dim}; font-size:{FONT['label']}pt; "
            f"border:1px solid {bdr}; border-radius:4px; margin-top:6px; }} "
            "QGroupBox::title { subcontrol-position:top left; padding:0 4px; } "
            f"QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{ "
            f"background:{sur}; color:{txt}; border:1px solid {bdr}; "
            f"font-size:{FONT['label']}pt; }}"
        )

    def _apply_styles(self) -> None:
        P   = PALETTE
        su2 = P.get("surface2", "#20232e")
        sur = P.get("surface",  "#1a1d28")
        bdr = P.get("border",   "#2e3245")
        txt = P.get("text",     "#dde3f2")
        dim = P.get("textDim",  "#8892aa")
        acc = P.get("accent",   "#00d4aa")
        hdr_qss = f"color:{txt}; font-size:{FONT['heading']}pt; font-weight:600;"
        if hasattr(self, "_list_hdr"):
            self._list_hdr.setStyleSheet(hdr_qss)
        if hasattr(self, "_right_hdr"):
            self._right_hdr.setStyleSheet(hdr_qss)
        if hasattr(self, "_list"):
            self._list.setStyleSheet(f"""
                QListWidget {{ background:{su2}; color:{txt}; border:1px solid {bdr};
                              font-size:{FONT['label']}pt; font-family:{MONO_FONT}; }}
                QListWidget::item:selected {{ background:{P.get('info','#0d3a52')}; color:{P.get('bg','#12151f')}; }}
                QListWidget::item:hover    {{ background:{P.get('surfaceHover','#262a38')}; }}
            """)
        box_qss = self._box_style()
        from PyQt5.QtWidgets import QGroupBox
        for box in self.findChildren(QGroupBox):
            box.setStyleSheet(box_qss)
        if hasattr(self, "_notes_edit"):
            self._notes_edit.setStyleSheet(
                f"background:{sur}; color:{txt}; "
                f"font-size:{FONT['label']}pt; border:none;")
        if hasattr(self, "_lock_banner") and self._lock_banner.isVisible():
            self._lock_banner.setStyleSheet(
                f"background:{acc}22; color:{acc}; "
                f"border:1px solid {acc}55; border-radius:4px; "
                f"font-size:{FONT.get('sublabel', 9)}pt; font-weight:600;")

    def _set_editor_enabled(self, enabled: bool):
        locked = bool(self._current and self._current.locked)
        can_edit = enabled and not locked
        for w in [self._label_edit, self._desc_edit, self._prof_edit,
                  self._exposure_spin, self._gain_spin, self._frames_spin,
                  self._delay_spin, self._modality_combo,
                  self._thresh_spin, self._fail_hs_spin, self._fail_peak_spin,
                  self._notes_edit, self._save_btn, self._cap_btn]:
            w.setEnabled(can_edit)
        # Delete and Run stay enabled (can still run or delete a locked recipe)
        for w in [self._run_btn, self._delete_btn]:
            w.setEnabled(enabled)
        # Lock button — enabled if a recipe is selected and user can edit recipes
        can_lock = enabled and self._can_edit_recipes()
        self._lock_btn.setEnabled(can_lock)
        if enabled:
            if locked:
                self._lock_btn.setText("Unlock Recipe")
                set_btn_icon(self._lock_btn, "fa5s.unlock")
            else:
                self._lock_btn.setText("Approve && Lock")
                set_btn_icon(self._lock_btn, "fa5s.lock")

    # ── List operations ─────────────────────────────────────────────

    def _refresh_list(self):
        self._list.clear()
        for recipe in self._store.list():
            item = QListWidgetItem(recipe.label)
            item.setData(Qt.UserRole, recipe)
            item.setForeground(QColor("#ccc"))
            self._list.addItem(item)
        if self._list.count() == 0:
            placeholder = QListWidgetItem("No scan profiles yet — click New")
            placeholder.setForeground(QColor("#555"))
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)

    def _on_select(self, row: int):
        item = self._list.item(row)
        if item is None:
            return
        recipe = item.data(Qt.UserRole)
        if recipe is None:
            self._set_editor_enabled(False)
            return
        self._current = recipe
        self._populate_editor(recipe)
        self._set_editor_enabled(True)

    # ── Editor helpers ──────────────────────────────────────────────

    def _populate_editor(self, r: Recipe):
        self._label_edit.setText(r.label)
        self._desc_edit.setText(r.description)
        self._prof_edit.setText(r.profile_name)
        self._exposure_spin.setValue(r.camera.exposure_us)
        self._gain_spin.setValue(r.camera.gain_db)
        self._frames_spin.setValue(r.camera.n_frames)
        self._delay_spin.setValue(r.acquisition.inter_phase_delay_s)
        idx = self._modality_combo.findText(r.acquisition.modality)
        self._modality_combo.setCurrentIndex(max(0, idx))
        self._thresh_spin.setValue(r.analysis.threshold_k)
        self._fail_hs_spin.setValue(r.analysis.fail_hotspot_count)
        self._fail_peak_spin.setValue(r.analysis.fail_peak_k)
        self._notes_edit.setPlainText(r.notes)
        # Lock banner
        if r.locked:
            by = r.approved_by or "unknown"
            self._lock_banner.setText(
                f"  Approved for Operators — Locked by {by}")
            self._lock_banner.setVisible(True)
        else:
            self._lock_banner.setVisible(False)

    def _editor_to_recipe(self) -> Recipe:
        r = self._current or Recipe()
        r.label        = self._label_edit.text().strip() or "unnamed"
        r.description  = self._desc_edit.text().strip()
        r.profile_name = self._prof_edit.text().strip()
        r.camera.exposure_us              = self._exposure_spin.value()
        r.camera.gain_db                  = self._gain_spin.value()
        r.camera.n_frames                 = self._frames_spin.value()
        r.acquisition.inter_phase_delay_s = self._delay_spin.value()
        r.acquisition.modality            = self._modality_combo.currentText()
        r.analysis.threshold_k            = self._thresh_spin.value()
        r.analysis.fail_hotspot_count     = self._fail_hs_spin.value()
        r.analysis.fail_peak_k            = self._fail_peak_spin.value()
        r.notes = self._notes_edit.toPlainText()
        return r

    # ── Auth helpers ─────────────────────────────────────────────────

    def set_auth_session(self, session) -> None:
        """Called by main_app on login / logout so the lock button is gated."""
        self._auth_session = session
        if self._current is not None:
            self._set_editor_enabled(True)

    def _can_edit_recipes(self) -> bool:
        """True when no auth is active (legacy mode) or user can edit recipes."""
        if self._auth_session is None:
            return True   # no-auth mode — everyone can edit
        return getattr(self._auth_session.user, "can_access_full_ui", True)

    # ── Buttons ─────────────────────────────────────────────────────

    def _on_new(self):
        r = Recipe()
        r.label      = f"recipe_{int(time.time())}"
        r.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._current = r
        self._populate_editor(r)
        self._set_editor_enabled(True)
        self._label_edit.selectAll()
        self._label_edit.setFocus()

    def _on_save(self):
        recipe = self._editor_to_recipe()
        if not recipe.label:
            QMessageBox.warning(self, "Save Scan Profile", "Please enter a label.")
            return
        self._store.save(recipe)
        self._current = recipe
        self._refresh_list()
        # Reselect the saved recipe
        for i in range(self._list.count()):
            item = self._list.item(i)
            r = item.data(Qt.UserRole)
            if r and r.uid == recipe.uid:
                self._list.setCurrentRow(i)
                break

    def _on_delete(self):
        if self._current is None:
            return
        ans = QMessageBox.question(
            self, "Delete Scan Profile",
            f"Delete scan profile '{self._current.label}'?",
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if ans == QMessageBox.Yes:
            self._store.delete(self._current)
            self._current = None
            self._set_editor_enabled(False)
            self._refresh_list()

    def _on_lock_toggle(self):
        """Approve & Lock / Unlock the current recipe."""
        if self._current is None:
            return
        recipe = self._current
        if recipe.locked:
            ans = QMessageBox.question(
                self, "Unlock Scan Profile",
                f"Unlock '{recipe.label}'?\n\n"
                "This will remove operator approval and allow editing.",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if ans != QMessageBox.Yes:
                return
            recipe.locked      = False
            recipe.approved_by = ""
            recipe.approved_at = ""
        else:
            # Require at least one save before locking
            if not recipe.uid:
                QMessageBox.warning(
                    self, "Approve & Lock",
                    "Please save this scan profile before locking it.")
                return
            approver = ""
            if self._auth_session is not None:
                approver = self._auth_session.user.display_name
            recipe.locked      = True
            recipe.approved_by = approver
            recipe.approved_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._store.save(recipe)
        self._populate_editor(recipe)
        self._set_editor_enabled(True)
        self._refresh_list()

    def _on_capture(self):
        """Read current app settings and populate the editor."""
        if self._app_state is None:
            QMessageBox.information(self, "Capture",
                "No app state available — fill in the fields manually.")
            return
        label = self._label_edit.text().strip() or f"recipe_{int(time.time())}"
        r = Recipe.from_current_state(self._app_state, label=label)
        if self._current:
            r.uid = self._current.uid
        self._current = r
        self._populate_editor(r)

    def _on_load_preset(self):
        """Open a preset picker dialog and load the chosen preset into the editor."""
        # Lazy import avoids a circular dependency (recipe_presets imports from here)
        from acquisition.recipe_presets import PRESETS
        import copy

        dlg = QDialog(self)
        dlg.setWindowTitle("Load Preset")
        dlg.setMinimumSize(500, 340)
        dlg.setStyleSheet("background:#1a1a1a; color:#ccc;")

        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        hdr = QLabel(
            "Choose a preset to load into the Recipe Editor.\n"
            "Rename and save it to create your own scan profile."
        )
        hdr.setStyleSheet(f"color:#aaa; font-size:{FONT['sublabel']}pt;")
        lay.addWidget(hdr)

        lst = QListWidget()
        lst.setStyleSheet(f"""
            QListWidget {{ background:#141414; color:#ccc; border:1px solid #2a2a2a;
                          font-size:{FONT['label']}pt; font-family:{MONO_FONT}; }}
            QListWidget::item:selected {{ background:#0d3a52; color:#fff; }}
            QListWidget::item:hover    {{ background:#1a2a2a; }}
        """)
        for preset in PRESETS:
            item = QListWidgetItem(preset.label)
            item.setData(Qt.UserRole, preset)
            lst.addItem(item)
        if PRESETS:
            lst.setCurrentRow(0)
        lay.addWidget(lst, 1)

        desc_lbl = QLabel(PRESETS[0].description if PRESETS else "")
        desc_lbl.setStyleSheet(
            f"color:#888; font-size:{FONT['sublabel']}pt; font-style:italic; padding:4px 0;")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)

        def _on_row_changed(row: int) -> None:
            item = lst.item(row)
            if item:
                preset = item.data(Qt.UserRole)
                if preset:
                    desc_lbl.setText(preset.description)

        lst.currentRowChanged.connect(_on_row_changed)
        lst.doubleClicked.connect(dlg.accept)

        btn_row = QHBoxLayout()
        load_btn   = QPushButton("Load")
        load_btn.setFixedHeight(28)
        load_btn.setStyleSheet(
            "background:#006b40; color:#fff; font-weight:600; border-radius:3px;")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(28)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(load_btn)
        lay.addLayout(btn_row)

        load_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return

        item = lst.currentItem()
        if item is None:
            return
        preset = item.data(Qt.UserRole)
        if preset is None:
            return

        # Deep-copy so the PRESETS list stays pristine; give it a fresh uid
        r            = copy.deepcopy(preset)
        r.uid        = str(uuid.uuid4())[:8]
        r.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._current = r
        self._populate_editor(r)
        self._set_editor_enabled(True)
        self._label_edit.selectAll()
        self._label_edit.setFocus()

    def _on_compare(self):
        dlg = _RecipeDiffDialog(self._store.list(), parent=self)
        dlg.exec_()

    def _on_run(self):
        if self._current is None:
            return
        # Save any unsaved edits first
        self._current = self._editor_to_recipe()
        self.recipe_run.emit(self._current)


# ================================================================== #
#  Helpers                                                             #
# ================================================================== #

def _flat_params(recipe: Recipe) -> "dict[str, str]":
    """Return all comparable Recipe fields as a flat dict of human-readable strings."""
    return {
        "Label":                   recipe.label,
        "Description":             recipe.description,
        "Profile":                 recipe.profile_name,
        "Exposure (\u00b5s)":      f"{recipe.camera.exposure_us:.0f}",
        "Gain (dB)":               f"{recipe.camera.gain_db:.1f}",
        "Frames":                  str(recipe.camera.n_frames),
        "Inter-phase delay (s)":   f"{recipe.acquisition.inter_phase_delay_s:.3f}",
        "Modality":                recipe.acquisition.modality,
        "Threshold (\u00b0C)":     f"{recipe.analysis.threshold_k:.1f}",
        "Fail: hotspot count":     str(recipe.analysis.fail_hotspot_count),
        "Fail: peak \u0394T (\u00b0C)": f"{recipe.analysis.fail_peak_k:.1f}",
        "Bias enabled":            str(recipe.bias.enabled),
        "Bias voltage (V)":        f"{recipe.bias.voltage_v:.2f}",
        "TEC enabled":             str(recipe.tec.enabled),
        "TEC setpoint (\u00b0C)":  f"{recipe.tec.setpoint_c:.1f}",
    }


# ================================================================== #
#  _RecipeDiffDialog                                                   #
# ================================================================== #

class _RecipeDiffDialog(QDialog):
    """
    Side-by-side diff viewer for two scan profiles.

    Opens via the "Compare…" button in RecipeTab.
    Highlights changed parameters: left value in amber, right in teal.
    """

    def __init__(self, recipes: List[Recipe], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare Scan Profiles")
        self.resize(700, 520)
        self.setStyleSheet(
            f"background:{PALETTE.get('bg', '#1a1a1a')}; "
            f"color:{PALETTE.get('text', '#cccccc')};"
        )

        self._recipes = recipes

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Selector row ──────────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)

        combo_style = (
            f"QComboBox {{ background:{PALETTE.get('surface', '#222')}; "
            f"color:{PALETTE.get('text', '#ccc')}; "
            f"border:1px solid {PALETTE.get('border', '#333')}; "
            f"border-radius:3px; padding:2px 6px; "
            f"font-size:{FONT.get('label', 10)}pt; }}"
            f"QComboBox::drop-down {{ border:none; }}"
            f"QComboBox QAbstractItemView {{ "
            f"background:{PALETTE.get('surface', '#222')}; "
            f"color:{PALETTE.get('text', '#ccc')}; "
            f"selection-background-color:{PALETTE.get('accent', '#00d4aa')}22; }}"
        )

        self._combo_left  = QComboBox()
        self._combo_right = QComboBox()
        for combo in (self._combo_left, self._combo_right):
            combo.setStyleSheet(combo_style)
            for r in recipes:
                combo.addItem(r.label, r)

        if len(recipes) >= 2:
            self._combo_left.setCurrentIndex(0)
            self._combo_right.setCurrentIndex(1)

        self._cmp_btn = QPushButton("Compare")
        set_btn_icon(self._cmp_btn, "fa5s.exchange-alt", "#00d4aa")
        self._cmp_btn.setFixedHeight(28)
        self._cmp_btn.setStyleSheet(
            "background:#006b40; color:#fff; font-weight:600; "
            "border-radius:3px; padding:0 10px;"
        )
        self._cmp_btn.clicked.connect(self._rebuild_diff)

        sel_row.addWidget(QLabel("Left:"))
        sel_row.addWidget(self._combo_left, 1)
        sel_row.addWidget(QLabel("Right:"))
        sel_row.addWidget(self._combo_right, 1)
        sel_row.addWidget(self._cmp_btn)
        root.addLayout(sel_row)

        # ── Scroll area for diff rows ─────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border:1px solid {PALETTE.get('border', '#2a2a2a')}; "
            f"border-radius:4px; background:{PALETTE.get('bg', '#1a1a1a')}; }}"
        )
        root.addWidget(self._scroll, 1)

        # Build immediately if we have enough recipes
        if len(recipes) >= 2:
            self._rebuild_diff()
        else:
            self._show_message("Need at least two scan profiles to compare.")

    # ── Diff rendering ───────────────────────────────────────────────

    def _rebuild_diff(self):
        left_recipe  = self._combo_left.currentData()
        right_recipe = self._combo_right.currentData()

        if left_recipe is None or right_recipe is None:
            self._show_message("Need at least two scan profiles to compare.")
            return

        if left_recipe.uid == right_recipe.uid:
            self._show_message("Select two different profiles to compare.")
            return

        left_params  = _flat_params(left_recipe)
        right_params = _flat_params(right_recipe)

        container = QWidget()
        container.setStyleSheet(
            f"background:{PALETTE.get('bg', '#1a1a1a')};"
        )
        form = QFormLayout(container)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        label_font_bold   = QFont()
        label_font_bold.setBold(True)
        label_font_bold.setPointSize(FONT.get("label", 10))

        label_font_normal = QFont()
        label_font_normal.setBold(False)
        label_font_normal.setPointSize(FONT.get("label", 10))

        for key in left_params:
            lv = left_params.get(key, "")
            rv = right_params.get(key, "")
            same = (lv == rv)

            # Row label
            row_lbl = QLabel(key)
            row_lbl.setFont(label_font_bold if not same else label_font_normal)
            row_lbl.setStyleSheet(
                f"color:{PALETTE.get('text', '#ccc') if same else '#ffffff'};"
            )

            # Value widget
            if same:
                val_lbl = QLabel(lv)
                val_lbl.setStyleSheet(
                    f"color:{PALETTE.get('textDim', '#777')}; "
                    f"font-size:{FONT.get('label', 10)}pt;"
                )
                form.addRow(row_lbl, val_lbl)
            else:
                pair_widget = QWidget()
                pair_widget.setStyleSheet("background:transparent;")
                pair_lay = QHBoxLayout(pair_widget)
                pair_lay.setContentsMargins(0, 0, 0, 0)
                pair_lay.setSpacing(12)

                left_lbl = QLabel(lv)
                left_lbl.setStyleSheet(
                    f"color:#ffb300; font-size:{FONT.get('label', 10)}pt; font-weight:600;"
                )
                arrow_lbl = QLabel("\u2192")
                arrow_lbl.setStyleSheet(
                    f"color:{PALETTE.get('textDim', '#555')}; "
                    f"font-size:{FONT.get('label', 10)}pt;"
                )
                right_lbl = QLabel(rv)
                right_lbl.setStyleSheet(
                    f"color:{PALETTE.get('accent', '#00d4aa')}; "
                    f"font-size:{FONT.get('label', 10)}pt; font-weight:600;"
                )

                pair_lay.addWidget(left_lbl)
                pair_lay.addWidget(arrow_lbl)
                pair_lay.addWidget(right_lbl)
                pair_lay.addStretch(1)

                form.addRow(row_lbl, pair_widget)

        self._scroll.setWidget(container)

    def _show_message(self, text: str):
        container = QWidget()
        container.setStyleSheet(
            f"background:{PALETTE.get('bg', '#1a1a1a')};"
        )
        lay = QVBoxLayout(container)
        lay.setAlignment(Qt.AlignCenter)
        msg = QLabel(text)
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet(
            f"color:{PALETTE.get('textDim', '#777')}; "
            f"font-size:{FONT.get('label', 10)}pt; font-style:italic;"
        )
        lay.addWidget(msg)
        self._scroll.setWidget(container)
