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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        r = cls()
        r.uid          = d.get("uid",         r.uid)
        r.label        = d.get("label",        "")
        r.description  = d.get("description",  "")
        r.created_at   = d.get("created_at",   "")
        r.version      = d.get("version",       1)
        r.profile_name = d.get("profile_name", "")
        r.notes        = d.get("notes",         "")
        r.camera       = RecipeCamera(**d.get("camera",      {}))
        r.acquisition  = RecipeAcquisition(**d.get("acquisition", {}))
        r.analysis     = RecipeAnalysis(**d.get("analysis",   {}))
        r.bias         = RecipeBias(**d.get("bias",          {}))
        r.tec          = RecipeTec(**d.get("tec",            {}))
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
    QMessageBox, QFrame, QComboBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont


class RecipeTab(QWidget):
    """
    Recipe manager panel for the Microsanj Advanced mode tab bar.

    Signals
    -------
    recipe_run(recipe):  Emitted when the user clicks RUN for a recipe.
                         The main window should connect this to apply the
                         recipe to the hardware and start acquisition.
    """

    recipe_run = pyqtSignal(object)   # Recipe instance

    def __init__(self, app_state=None, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._store     = RecipeStore()
        self._current:  Optional[Recipe] = None
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

        list_hdr = QLabel("Saved Recipes")
        list_hdr.setStyleSheet("color:#ccc; font-size:14pt; font-weight:600;")
        left_lay.addWidget(list_hdr)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget { background:#141414; color:#ccc; border:1px solid #2a2a2a;
                          font-size:12pt; font-family:Menlo,monospace; }
            QListWidget::item:selected { background:#0d3a52; color:#fff; }
            QListWidget::item:hover    { background:#1a2a2a; }
        """)
        self._list.currentRowChanged.connect(self._on_select)
        left_lay.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._new_btn    = QPushButton("New")
        self._delete_btn = QPushButton("Delete")
        self._run_btn    = QPushButton("▶  RUN")
        self._run_btn.setStyleSheet(
            "background:#006b40; color:#fff; font-weight:600; border-radius:3px;")
        for b in [self._new_btn, self._delete_btn, self._run_btn]:
            b.setFixedHeight(28)
            btn_row.addWidget(b)
        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn.clicked.connect(self._on_delete)
        self._run_btn.clicked.connect(self._on_run)
        left_lay.addLayout(btn_row)

        splitter.addWidget(left)

        # ─ Right: recipe editor ─
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        right_hdr = QLabel("Recipe Editor")
        right_hdr.setStyleSheet("color:#ccc; font-size:14pt; font-weight:600;")
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
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(0, 48)
        self._gain_spin.setSuffix(" dB")
        self._frames_spin = QSpinBox()
        self._frames_spin.setRange(1, 1000)
        self._frames_spin.setValue(16)
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0, 60)
        self._delay_spin.setValue(0.1)
        self._delay_spin.setSuffix(" s")
        self._modality_combo = QComboBox()
        self._modality_combo.addItems(["thermoreflectance", "ir_lockin", "hybrid", "opp"])
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
        self._fail_hs_spin    = QSpinBox()
        self._fail_hs_spin.setRange(1, 10000)
        self._fail_hs_spin.setValue(3)
        self._fail_peak_spin  = QDoubleSpinBox()
        self._fail_peak_spin.setRange(0, 1000)
        self._fail_peak_spin.setValue(20.0)
        self._fail_peak_spin.setSuffix(" °C")
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
            "background:#111; color:#ccc; font-size:12pt; border:none;")
        notes_lay.addWidget(self._notes_edit)
        right_lay.addWidget(notes_box)

        # Save / Capture buttons
        footer = QHBoxLayout()
        right_lay.addLayout(footer)

        self._save_btn = QPushButton("Save Recipe")
        self._cap_btn  = QPushButton("Capture Current Settings")
        self._cap_btn.setToolTip(
            "Read current camera / analysis / profile settings from the app "
            "and populate this recipe automatically.")
        for b in [self._save_btn, self._cap_btn]:
            b.setFixedHeight(28)
            footer.addWidget(b)
        footer.addStretch(1)
        self._save_btn.clicked.connect(self._on_save)
        self._cap_btn.clicked.connect(self._on_capture)

        right_lay.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([280, 560])

        self._set_editor_enabled(False)

    @staticmethod
    def _box_style() -> str:
        return (
            "QGroupBox { color:#aaa; font-size:12pt; border:1px solid #2a2a2a; "
            "border-radius:4px; margin-top:6px; } "
            "QGroupBox::title { subcontrol-position:top left; padding:0 4px; } "
            "QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox { "
            "background:#111; color:#ddd; border:1px solid #333; font-size:12pt; }"
        )

    def _set_editor_enabled(self, enabled: bool):
        for w in [self._label_edit, self._desc_edit, self._prof_edit,
                  self._exposure_spin, self._gain_spin, self._frames_spin,
                  self._delay_spin, self._modality_combo,
                  self._thresh_spin, self._fail_hs_spin, self._fail_peak_spin,
                  self._notes_edit, self._save_btn, self._cap_btn,
                  self._run_btn, self._delete_btn]:
            w.setEnabled(enabled)

    # ── List operations ─────────────────────────────────────────────

    def _refresh_list(self):
        self._list.clear()
        for recipe in self._store.list():
            item = QListWidgetItem(recipe.label)
            item.setData(Qt.UserRole, recipe)
            item.setForeground(QColor("#ccc"))
            self._list.addItem(item)
        if self._list.count() == 0:
            placeholder = QListWidgetItem("No recipes yet — click New")
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
            QMessageBox.warning(self, "Save Recipe", "Please enter a label.")
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
            self, "Delete Recipe",
            f"Delete recipe '{self._current.label}'?",
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if ans == QMessageBox.Yes:
            self._store.delete(self._current)
            self._current = None
            self._set_editor_enabled(False)
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

    def _on_run(self):
        if self._current is None:
            return
        # Save any unsaved edits first
        self._current = self._editor_to_recipe()
        self.recipe_run.emit(self._current)
