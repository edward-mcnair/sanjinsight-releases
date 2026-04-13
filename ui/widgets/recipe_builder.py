"""
ui/widgets/recipe_builder.py  —  Recipe Builder / Editor widget

Two-panel interface for creating, editing, and managing v2 Recipes:

  Left panel:  saved recipe list + action buttons
  Right panel: phase-based editor with inline config sections

This replaces the v1 RecipeTab for the recipe-mode branch.
The widget manages a WorkingCopy internally and emits signals
for recipe execution, navigation, and save operations.

Signals
-------
    recipe_run(Recipe)
        User clicked Run — caller should execute via RecipeExecutor.
    navigate_requested(str, str)
        From the readiness panel — (nav_target, tab_hint).
    recipe_saved(Recipe)
        After successful Save or Save As.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget, QFrame, QCheckBox,
)

from ui.theme import FONT, MONO_FONT, PALETTE
from ui.icons import set_btn_icon

from acquisition.recipe import (
    Recipe, RecipeStore, PhaseType, _build_standard_phases, infer_requirements,
)
from acquisition.working_copy import (
    WorkingCopy, Origin, load_working_copy, generated_working_copy,
)

log = logging.getLogger(__name__)


class RecipeBuilder(QWidget):
    """Two-panel recipe editor with readiness integration."""

    recipe_run          = pyqtSignal(object)   # Recipe
    navigate_requested  = pyqtSignal(str, str) # nav_target, tab_hint
    recipe_saved        = pyqtSignal(object)   # Recipe

    def __init__(self, store: Optional[RecipeStore] = None, parent=None):
        super().__init__(parent)
        self._store = store or RecipeStore()
        self._wc: Optional[WorkingCopy] = None
        self._var_toggles: Dict[str, QCheckBox] = {}
        self._build()
        self._refresh_list()

    # ── Build ──────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ─── Left: recipe list ───
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)

        hdr = QLabel("Recipes")
        hdr.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            f"font-weight:600;")
        left_lay.addWidget(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{ background:{PALETTE['bg']}; color:{PALETTE['text']};
                          border:1px solid {PALETTE['border']};
                          font-size:{FONT['label']}pt; font-family:{MONO_FONT}; }}
            QListWidget::item:selected {{ background:{PALETTE['accentDim']};
                          color:{PALETTE['textOnAccent']}; }}
            QListWidget::item:hover {{ background:{PALETTE['surfaceHover']}; }}
        """)
        self._list.currentRowChanged.connect(self._on_select)
        left_lay.addWidget(self._list, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("New")
        set_btn_icon(self._new_btn, "fa5s.plus")
        self._delete_btn = QPushButton("Delete")
        set_btn_icon(self._delete_btn, "fa5s.trash", PALETTE['danger'])
        self._run_btn = QPushButton("RUN")
        set_btn_icon(self._run_btn, "fa5s.play", PALETTE['accent'])
        self._run_btn.setStyleSheet(
            f"background:{PALETTE['accent']}; color:{PALETTE['textOnAccent']}; "
            f"font-weight:600; border-radius:3px;")
        for b in (self._new_btn, self._delete_btn, self._run_btn):
            b.setFixedHeight(28)
            btn_row.addWidget(b)
        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn.clicked.connect(self._on_delete)
        self._run_btn.clicked.connect(self._on_run)
        left_lay.addLayout(btn_row)

        self._preset_btn = QPushButton("Load Preset\u2026")
        set_btn_icon(self._preset_btn, "fa5s.folder-open")
        self._preset_btn.setFixedHeight(28)
        self._preset_btn.clicked.connect(self._on_load_preset)
        left_lay.addWidget(self._preset_btn)

        splitter.addWidget(left)

        # ─── Right: editor ───
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 8, 0)
        right_lay.setSpacing(6)

        self._editor_hdr = QLabel("Recipe Editor")
        self._editor_hdr.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt; "
            f"font-weight:600;")
        right_lay.addWidget(self._editor_hdr)

        # Modified indicator
        self._modified_lbl = QLabel()
        self._modified_lbl.setStyleSheet(
            f"color:{PALETTE['warning']}; font-size:{FONT['caption']}pt;")
        right_lay.addWidget(self._modified_lbl)

        # Identity group
        id_box = QGroupBox("Identity")
        id_box.setStyleSheet(self._box_qss())
        id_form = QFormLayout(id_box)
        self._label_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        self._profile_lbl = QLabel("None")
        self._profile_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        id_form.addRow("Label:", self._label_edit)
        id_form.addRow("Description:", self._desc_edit)
        id_form.addRow("Material Profile:", self._profile_lbl)
        right_lay.addWidget(id_box)

        # Camera + Acquisition
        cam_box = QGroupBox("Camera + Acquisition")
        cam_box.setStyleSheet(self._box_qss())
        cam_form = QFormLayout(cam_box)
        self._exposure_spin = QDoubleSpinBox()
        self._exposure_spin.setRange(1, 1_000_000)
        self._exposure_spin.setValue(5000)
        self._exposure_spin.setSuffix(" \u00b5s")
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
        self._modality_combo.addItems([
            "thermoreflectance", "ir_lockin", "hybrid", "opp"])
        cam_form.addRow("Exposure:", self._make_var_row(
            self._exposure_spin, "hardware_setup.camera.exposure_us"))
        cam_form.addRow("Gain:", self._make_var_row(
            self._gain_spin, "hardware_setup.camera.gain_db"))
        cam_form.addRow("Frames:", self._make_var_row(
            self._frames_spin, "hardware_setup.camera.n_frames"))
        cam_form.addRow("Inter-phase delay:", self._delay_spin)
        cam_form.addRow("Modality:", self._modality_combo)
        right_lay.addWidget(cam_box)

        # Stimulus (FPGA)
        stim_box = QGroupBox("Stimulus")
        stim_box.setStyleSheet(self._box_qss())
        stim_form = QFormLayout(stim_box)
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(1, 100_000)
        self._freq_spin.setValue(1000)
        self._freq_spin.setSuffix(" Hz")
        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(0.01, 0.99)
        self._duty_spin.setValue(0.5)
        self._duty_spin.setSingleStep(0.05)
        stim_form.addRow("Frequency:", self._freq_spin)
        stim_form.addRow("Duty cycle:", self._duty_spin)
        right_lay.addWidget(stim_box)

        # Bias source
        bias_box = QGroupBox("Bias Source")
        bias_box.setStyleSheet(self._box_qss())
        bias_form = QFormLayout(bias_box)
        self._bias_enabled = QCheckBox("Enable bias")
        self._bias_voltage_spin = QDoubleSpinBox()
        self._bias_voltage_spin.setRange(0, 100)
        self._bias_voltage_spin.setSuffix(" V")
        bias_form.addRow(self._bias_enabled)
        bias_form.addRow("Voltage:", self._bias_voltage_spin)
        right_lay.addWidget(bias_box)

        # TEC
        tec_box = QGroupBox("Temperature Control")
        tec_box.setStyleSheet(self._box_qss())
        tec_form = QFormLayout(tec_box)
        self._tec_enabled = QCheckBox("Enable TEC")
        self._tec_setpoint_spin = QDoubleSpinBox()
        self._tec_setpoint_spin.setRange(-40, 200)
        self._tec_setpoint_spin.setValue(25.0)
        self._tec_setpoint_spin.setSuffix(" \u00b0C")
        tec_form.addRow(self._tec_enabled)
        tec_form.addRow("Setpoint:", self._tec_setpoint_spin)
        right_lay.addWidget(tec_box)

        # Analysis
        an_box = QGroupBox("Pass / Fail Analysis")
        an_box.setStyleSheet(self._box_qss())
        an_form = QFormLayout(an_box)
        self._thresh_spin = QDoubleSpinBox()
        self._thresh_spin.setRange(0.001, 1000)
        self._thresh_spin.setValue(5.0)
        self._thresh_spin.setSuffix(" \u00b0C")
        self._fail_hs_spin = QSpinBox()
        self._fail_hs_spin.setRange(1, 10000)
        self._fail_hs_spin.setValue(3)
        self._fail_peak_spin = QDoubleSpinBox()
        self._fail_peak_spin.setRange(0, 1000)
        self._fail_peak_spin.setValue(20.0)
        self._fail_peak_spin.setSuffix(" \u00b0C")
        an_form.addRow("Threshold:", self._thresh_spin)
        an_form.addRow("Fail hotspot count:", self._fail_hs_spin)
        an_form.addRow("Fail peak \u0394T:", self._fail_peak_spin)
        right_lay.addWidget(an_box)

        # Notes
        notes_box = QGroupBox("Notes")
        notes_box.setStyleSheet(self._box_qss())
        notes_lay = QVBoxLayout(notes_box)
        self._notes_edit = QTextEdit()
        self._notes_edit.setMaximumHeight(70)
        notes_lay.addWidget(self._notes_edit)
        right_lay.addWidget(notes_box)

        # Lock banner
        self._lock_banner = QLabel()
        self._lock_banner.setWordWrap(True)
        self._lock_banner.setStyleSheet(
            f"background:{PALETTE['accentDim']}; color:{PALETTE['text']}; "
            f"border:1px solid {PALETTE['accent']}; border-radius:4px; "
            f"padding:8px; font-size:{FONT['label']}pt;")
        self._lock_banner.hide()
        right_lay.addWidget(self._lock_banner)

        right_lay.addStretch()

        # Footer buttons
        footer = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._save_btn.setFixedHeight(28)
        self._save_btn.clicked.connect(self._on_save)
        self._save_as_btn = QPushButton("Save As\u2026")
        set_btn_icon(self._save_as_btn, "fa5s.copy")
        self._save_as_btn.setFixedHeight(28)
        self._save_as_btn.clicked.connect(self._on_save_as)
        self._revert_btn = QPushButton("Revert")
        set_btn_icon(self._revert_btn, "fa5s.undo")
        self._revert_btn.setFixedHeight(28)
        self._revert_btn.clicked.connect(self._on_revert)
        footer.addWidget(self._save_btn)
        footer.addWidget(self._save_as_btn)
        footer.addWidget(self._revert_btn)
        footer.addStretch()
        right_lay.addLayout(footer)

        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setSizes([280, 560])

    # ── Group box styling ──────────────────────────────────────────

    @staticmethod
    def _box_qss() -> str:
        return (
            f"QGroupBox {{ border:1px solid {PALETTE['border']}; "
            f"border-radius:4px; margin-top:8px; padding-top:14px; "
            f"font-size:{FONT['label']}pt; color:{PALETTE['textDim']}; }}"
            f"QGroupBox::title {{ subcontrol-origin:margin; left:8px; "
            f"padding:0 4px; }}")

    # ── VAR toggle helper ──────────────────────────────────────────

    def _make_var_row(self, spin_widget, field_path: str) -> QWidget:
        """Wrap a spin widget with a VAR checkbox for operator variables."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(spin_widget, 1)

        cb = QCheckBox("VAR")
        cb.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT['caption']}pt;")
        cb.setToolTip(
            "Mark as operator-adjustable.\n"
            "Checked fields can be tweaked at run time\n"
            "even on locked recipes.")
        lay.addWidget(cb)
        self._var_toggles[field_path] = cb
        return row

    # ── List management ────────────────────────────────────────────

    def _refresh_list(self):
        self._list.blockSignals(True)
        self._list.clear()
        for recipe in self._store.list_all():
            item = QListWidgetItem(recipe.label or "Untitled")
            item.setData(Qt.UserRole, recipe.uid)
            if recipe.locked:
                item.setText(f"\U0001f512 {recipe.label}")
            self._list.addItem(item)
        self._list.blockSignals(False)

    def _on_select(self, row: int):
        if row < 0:
            return
        item = self._list.item(row)
        if not item:
            return
        uid = item.data(Qt.UserRole)
        recipe = self._store.load(uid)
        if recipe is None:
            return
        self._load_recipe(recipe, Origin.LOADED)

    # ── Load recipe into editor ────────────────────────────────────

    def _load_recipe(self, recipe: Recipe, origin: Origin):
        if origin == Origin.LOADED:
            self._wc = load_working_copy(recipe, self._store)
        else:
            self._wc = generated_working_copy(recipe, store=self._store)
        self._populate_editor()

    def load_working_copy(self, wc: WorkingCopy):
        """Load an external WorkingCopy (e.g. from Quick Recipe)."""
        self._wc = wc
        self._populate_editor()

    def _populate_editor(self):
        """Fill editor widgets from the current working copy."""
        if self._wc is None:
            return
        r = self._wc.recipe

        self._label_edit.setText(r.label)
        self._desc_edit.setText(r.description)
        self._notes_edit.setPlainText(r.notes)

        # Profile reference
        if r.profile_name:
            self._profile_lbl.setText(
                f"{r.profile_name} ({r.profile_uid[:8]})")
        else:
            self._profile_lbl.setText("None")

        # Camera
        hw = r.get_phase_config("hardware_setup")
        cam = hw.get("camera", {})
        self._exposure_spin.setValue(cam.get("exposure_us", 5000))
        self._gain_spin.setValue(cam.get("gain_db", 0))
        self._frames_spin.setValue(cam.get("n_frames", 16))

        # FPGA
        fpga = hw.get("fpga", {})
        self._freq_spin.setValue(fpga.get("frequency_hz", 1000))
        self._duty_spin.setValue(fpga.get("duty_cycle", 0.5))

        # Bias
        bias = hw.get("bias", {})
        self._bias_enabled.setChecked(bias.get("enabled", False))
        self._bias_voltage_spin.setValue(bias.get("voltage_v", 0))

        # TEC
        tec = hw.get("tec", {})
        self._tec_enabled.setChecked(tec.get("enabled", False))
        self._tec_setpoint_spin.setValue(tec.get("setpoint_c", 25.0))

        # Acquisition
        acq = r.get_phase_config("acquisition")
        self._delay_spin.setValue(acq.get("inter_phase_delay_s", 0.1))

        # Modality
        mod = hw.get("modality", "thermoreflectance")
        idx = self._modality_combo.findText(mod)
        if idx >= 0:
            self._modality_combo.setCurrentIndex(idx)

        # Analysis
        analysis = r.get_phase_config("analysis")
        self._thresh_spin.setValue(analysis.get("threshold_k", 5.0))
        self._fail_hs_spin.setValue(analysis.get("fail_hotspot_count", 3))
        self._fail_peak_spin.setValue(analysis.get("fail_peak_k", 20.0))

        # Lock state
        if self._wc.is_locked:
            self._lock_banner.setText(
                f"\U0001f512 Locked — approved by "
                f"{r.approved_by or 'unknown'} "
                f"({r.approved_at or 'date unknown'})")
            self._lock_banner.show()
            self._save_btn.setEnabled(False)
        else:
            self._lock_banner.hide()
            self._save_btn.setEnabled(self._wc.can_save)

        self._update_modified_label()

    def _apply_editor_to_recipe(self):
        """Write editor widget values back into the working copy's recipe."""
        if self._wc is None:
            return
        r = self._wc.recipe

        r.label = self._label_edit.text().strip()
        r.description = self._desc_edit.text().strip()
        r.notes = self._notes_edit.toPlainText().strip()

        # Camera
        hw = r.get_phase("hardware_setup")
        if hw:
            hw.config.setdefault("camera", {}).update({
                "exposure_us": self._exposure_spin.value(),
                "gain_db": self._gain_spin.value(),
                "n_frames": self._frames_spin.value(),
            })
            hw.config.setdefault("fpga", {}).update({
                "frequency_hz": self._freq_spin.value(),
                "duty_cycle": self._duty_spin.value(),
            })
            hw.config["bias"] = {
                "enabled": self._bias_enabled.isChecked(),
                "voltage_v": self._bias_voltage_spin.value(),
            }
            hw.config["tec"] = {
                "enabled": self._tec_enabled.isChecked(),
                "setpoint_c": self._tec_setpoint_spin.value(),
            }
            hw.config["modality"] = self._modality_combo.currentText()

        # Acquisition
        acq = r.get_phase("acquisition")
        if acq:
            acq.config["inter_phase_delay_s"] = self._delay_spin.value()

        # Analysis
        analysis = r.get_phase("analysis")
        if analysis:
            analysis.config["threshold_k"] = self._thresh_spin.value()
            analysis.config["fail_hotspot_count"] = self._fail_hs_spin.value()
            analysis.config["fail_peak_k"] = self._fail_peak_spin.value()

        # Stabilization enable/disable
        stab = r.get_phase("stabilization")
        if stab:
            stab.enabled = (
                self._tec_enabled.isChecked()
                or self._bias_enabled.isChecked())
            if self._tec_enabled.isChecked():
                stab.config["tec_settle"] = {
                    "tolerance_c": 0.1, "duration_s": 10, "timeout_s": 120}
            elif "tec_settle" in stab.config:
                del stab.config["tec_settle"]
            if self._bias_enabled.isChecked():
                stab.config["bias_settle"] = {"delay_s": 2.0}
            elif "bias_settle" in stab.config:
                del stab.config["bias_settle"]

        # Re-infer requirements
        r.requirements = infer_requirements(r)

    def _update_modified_label(self):
        if self._wc and self._wc.modified:
            self._modified_lbl.setText("\u25cf Unsaved changes")
        else:
            self._modified_lbl.setText("")

    # ── Actions ────────────────────────────────────────────────────

    def _on_new(self):
        r = Recipe()
        r.label = "New Recipe"
        r.phases = _build_standard_phases()
        r.requirements = infer_requirements(r)
        self._store.save(r)
        self._refresh_list()
        # Select the new recipe
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == r.uid:
                self._list.setCurrentRow(i)
                break

    def _on_delete(self):
        if self._wc is None:
            return
        uid = self._wc.recipe.uid
        label = self._wc.recipe.label
        reply = QMessageBox.question(
            self, "Delete Recipe",
            f"Delete \"{label}\"?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._store.delete(uid)
            self._wc = None
            self._refresh_list()

    def _on_run(self):
        if self._wc is None:
            return
        self._apply_editor_to_recipe()
        self.recipe_run.emit(self._wc.recipe)

    def _on_save(self):
        if self._wc is None or not self._wc.can_save:
            return
        self._apply_editor_to_recipe()
        try:
            self._wc.save()
            self._refresh_list()
            self._update_modified_label()
            self.recipe_saved.emit(self._wc.recipe)
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", str(e))

    def _on_save_as(self):
        if self._wc is None:
            return
        self._apply_editor_to_recipe()
        label = self._label_edit.text().strip() or "Untitled Copy"
        try:
            result = self._wc.save_as(label)
            self._refresh_list()
            self._update_modified_label()
            self.recipe_saved.emit(result)
        except Exception as e:
            QMessageBox.warning(self, "Save As Failed", str(e))

    def _on_revert(self):
        if self._wc is None:
            return
        self._wc.revert()
        self._populate_editor()

    def _on_load_preset(self):
        from acquisition.recipe_presets import PRESETS
        if not PRESETS:
            return
        # Simple selection — pick the first preset for now.
        # Full preset picker deferred to UI polish pass.
        from PyQt5.QtWidgets import QInputDialog
        labels = [p.label for p in PRESETS]
        label, ok = QInputDialog.getItem(
            self, "Load Preset", "Select a preset:", labels, 0, False)
        if ok and label:
            preset = next((p for p in PRESETS if p.label == label), None)
            if preset:
                self._load_recipe(preset, Origin.GENERATED)

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self):
        """Refresh all styles from current PALETTE (called on theme switch)."""
        self._rebuild_list_style()
        # GroupBoxes and other children will pick up new PALETTE
        # values on next _populate_editor call.

    def _rebuild_list_style(self):
        self._list.setStyleSheet(f"""
            QListWidget {{ background:{PALETTE['bg']}; color:{PALETTE['text']};
                          border:1px solid {PALETTE['border']};
                          font-size:{FONT['label']}pt; font-family:{MONO_FONT}; }}
            QListWidget::item:selected {{ background:{PALETTE['accentDim']};
                          color:{PALETTE['textOnAccent']}; }}
            QListWidget::item:hover {{ background:{PALETTE['surfaceHover']}; }}
        """)
