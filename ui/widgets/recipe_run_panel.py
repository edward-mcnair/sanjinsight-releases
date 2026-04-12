"""
ui/widgets/recipe_run_panel.py  —  Compact recipe execution surface

A focused "select → configure variables → run → log" panel.
This is a RUN surface, not a recipe editor.

Layout (Standard/Expert):
  ┌──────────────────────────────────────┐
  │ ▶ Recipe Run                         │  section title
  ├──────────────────────────────────────┤
  │ Recipe: [▼ dropdown          ]       │  recipe selector
  │                                      │
  │  Modality · Frames · Exposure        │  compact summary strip
  │  Profile · Threshold · Verdict rules │
  ├──────────────────────────────────────┤
  │ Test Variables  (if any)             │  auto-generated inputs
  │  Voltage (V)   [____]               │
  │  Current (mA)  [____]               │
  ├──────────────────────────────────────┤
  │ Operator  [____]  Device ID  [____] │  context fields
  │ Project   [____]  Notes      [____] │
  ├──────────────────────────────────────┤
  │ ☐ Bypass Analyzer                   │  checkbox
  │                                      │
  │ [ ▶ RUN RECIPE ]  (or progress bar) │  action
  ├──────────────────────────────────────┤
  │ ✓ Complete · 12.3s · Pass · 2 spots │  result strip (after run)
  └──────────────────────────────────────┘

Guided mode: hides context fields (auto-filled from lab prefs).
Expert mode: adds "Edit Recipe ▸" link to open RecipeTab.

Signals
-------
run_requested(dict)
    Emitted when the user presses RUN.  Payload is a dict with all
    information needed to execute the acquisition and log the result.
    The parent (main_app) is responsible for actually running the pipeline.

run_completed()
    Emitted after the panel receives a completion callback and has
    appended to the experiment log.

Usage
-----
    panel = RecipeRunPanel()
    panel.run_requested.connect(main_app._on_recipe_run)

    # After acquisition + analysis complete, call:
    panel.on_run_complete(acq_result, analysis_result, duration_s)

    # Or on error:
    panel.on_run_error("Camera disconnected")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QCheckBox, QPushButton, QProgressBar,
    QFrame, QSizePolicy, QFormLayout, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, set_btn_icon
from ui.workspace import get_manager

log = logging.getLogger(__name__)


# ── Run payload ──────────────────────────────────────────────────────

@dataclass
class RecipeRunPayload:
    """Everything needed to execute a recipe run.

    Emitted by the panel as a dict (via ``to_dict()``).
    The parent orchestrates hardware + pipeline from this payload.
    """
    recipe_uid: str = ""
    recipe_label: str = ""
    scan_type: str = "single"           # "single" | "autoscan" | "transient"

    # Acquisition params (from recipe)
    modality: str = ""
    n_frames: int = 16
    exposure_us: float = 5000.0
    gain_db: float = 0.0
    inter_phase_delay_s: float = 0.1

    # Analysis config (from recipe)
    threshold_k: float = 5.0
    bypass_analyzer: bool = False

    # Hardware presets (from recipe)
    bias_enabled: bool = False
    bias_voltage_v: float = 0.0
    bias_current_a: float = 0.0
    tec_enabled: bool = False
    tec_setpoint_c: float = 25.0
    profile_name: str = ""

    # Operator context (from panel inputs)
    operator: str = ""
    device_id: str = ""
    project: str = ""
    notes: str = ""

    # Test variables (operator-filled at run time)
    test_variables: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


# ── RecipeRunPanel ───────────────────────────────────────────────────

class RecipeRunPanel(QWidget):
    """Compact recipe execution panel.

    Signals
    -------
    run_requested(dict)
        Payload dict from RecipeRunPayload.  Parent handles execution.
    run_completed()
        After on_run_complete() finishes and experiment log is appended.
    edit_recipe_requested(str)
        Recipe UID — emitted in Expert mode when "Edit Recipe ▸" is clicked.
    """

    run_requested = pyqtSignal(dict)
    run_completed = pyqtSignal()
    edit_recipe_requested = pyqtSignal(str)
    navigate_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recipes: list = []        # cached Recipe objects
        self._active_recipe = None      # currently selected Recipe
        self._running = False
        self._variable_inputs: Dict[str, QLineEdit] = {}

        self._build_ui()
        self._apply_styles()
        self._connect_signals()

        # Initial mode
        self.set_workspace_mode(get_manager().mode)
        get_manager().mode_changed.connect(self.set_workspace_mode)

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Guidance cards (Guided mode) ─────────────────────────────
        from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
        from ui.guidance.steps import next_steps_after

        cards_widget = QWidget()
        cards_lay = QVBoxLayout(cards_widget)
        cards_lay.setContentsMargins(12, 8, 12, 4)
        cards_lay.setSpacing(6)
        self._guidance_cards: list[GuidanceCard] = []
        for cdef in get_section_cards("recipe_run"):
            card = GuidanceCard(
                card_id=cdef["card_id"],
                title=cdef["title"],
                body=cdef["body"],
                step_number=cdef.get("step_number"),
            )
            cards_lay.addWidget(card)
            self._guidance_cards.append(card)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setWidget(cards_widget)
        self._cards_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cards_scroll.setMaximumHeight(180)
        self._cards_scroll.setVisible(False)
        root.addWidget(self._cards_scroll)

        # ── Recipe selector ──────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.setContentsMargins(12, 10, 12, 6)
        sel_row.setSpacing(8)

        sel_lbl = QLabel("Scan Profile:")
        sel_lbl.setStyleSheet(
            f"font-size: {FONT['label']}pt; color: {PALETTE['text']};")
        sel_row.addWidget(sel_lbl)

        self._recipe_combo = QComboBox()
        self._recipe_combo.setMinimumWidth(200)
        self._recipe_combo.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._recipe_combo.setPlaceholderText("Select a scan profile…")
        sel_row.addWidget(self._recipe_combo, 1)

        root.addLayout(sel_row)

        # ── Empty-state hint (visible when no recipes loaded) ────────
        self._empty_hint = QLabel(
            "No scan profiles available.\n"
            "Create one in the Library tab, or ask your engineer to set up a scan profile.")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setStyleSheet(
            f"font-size: {FONT['label']}pt; "
            f"color: {PALETTE['textDim']}; "
            f"padding: 24px 16px;")
        self._empty_hint.setVisible(False)
        root.addWidget(self._empty_hint)

        # ── Summary strip ────────────────────────────────────────────
        self._summary_frame = QFrame()
        self._summary_frame.setObjectName("recipeSummary")
        summary_lay = QHBoxLayout(self._summary_frame)
        summary_lay.setContentsMargins(12, 6, 12, 6)
        summary_lay.setSpacing(16)

        self._summary_labels: Dict[str, QLabel] = {}
        for key, label_text in [
            ("modality", "Type"),
            ("frames", "Frames"),
            ("exposure", "Exposure"),
            ("profile", "Profile"),
            ("threshold", "Threshold"),
            ("scan_type", "Type"),
        ]:
            pair = QHBoxLayout()
            pair.setSpacing(4)
            sub = QLabel(f"{label_text}:")
            sub.setStyleSheet(
                f"font-size: {FONT['caption']}pt; "
                f"color: {PALETTE['textDim']};")
            val = QLabel("—")
            val.setStyleSheet(
                f"font-family: {MONO_FONT}; "
                f"font-size: {FONT['caption']}pt; "
                f"color: {PALETTE['text']};")
            pair.addWidget(sub)
            pair.addWidget(val)
            summary_lay.addLayout(pair)
            self._summary_labels[key] = val

        summary_lay.addStretch()
        self._summary_frame.setVisible(False)
        root.addWidget(self._summary_frame)

        # ── Test variables (dynamic) ─────────────────────────────────
        self._vars_container = QWidget()
        self._vars_container.setObjectName("testVarsContainer")
        self._vars_layout = QFormLayout(self._vars_container)
        self._vars_layout.setContentsMargins(12, 6, 12, 6)
        self._vars_layout.setSpacing(6)
        self._vars_layout.setLabelAlignment(Qt.AlignRight)
        self._vars_container.setVisible(False)
        root.addWidget(self._vars_container)

        # ── Context fields (operator, device, project, notes) ────────
        self._context_frame = QFrame()
        self._context_frame.setObjectName("runContext")
        ctx_lay = QVBoxLayout(self._context_frame)
        ctx_lay.setContentsMargins(12, 6, 12, 6)
        ctx_lay.setSpacing(6)

        # Row 1: operator + device
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        op_lbl = QLabel("Operator:")
        op_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        self._operator_input = QLineEdit()
        self._operator_input.setPlaceholderText("Name")
        self._operator_input.setMaximumWidth(160)
        row1.addWidget(op_lbl)
        row1.addWidget(self._operator_input)

        dev_lbl = QLabel("Device ID:")
        dev_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        self._device_input = QLineEdit()
        self._device_input.setPlaceholderText("DUT identifier")
        self._device_input.setMaximumWidth(160)
        row1.addWidget(dev_lbl)
        row1.addWidget(self._device_input)
        row1.addStretch()
        ctx_lay.addLayout(row1)

        # Row 2: project + notes
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        proj_lbl = QLabel("Project:")
        proj_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("Project / lot")
        self._project_input.setMaximumWidth(160)
        row2.addWidget(proj_lbl)
        row2.addWidget(self._project_input)

        notes_lbl = QLabel("Notes:")
        notes_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        self._notes_input = QLineEdit()
        self._notes_input.setPlaceholderText("Optional run notes")
        row2.addWidget(notes_lbl)
        row2.addWidget(self._notes_input, 1)
        ctx_lay.addLayout(row2)

        root.addWidget(self._context_frame)

        # ── Bypass + action row ──────────────────────────────────────
        action_frame = QFrame()
        action_lay = QVBoxLayout(action_frame)
        action_lay.setContentsMargins(12, 8, 12, 10)
        action_lay.setSpacing(8)

        bypass_row = QHBoxLayout()
        bypass_row.setSpacing(8)
        self._bypass_cb = QCheckBox("Bypass Analyzer")
        self._bypass_cb.setToolTip(
            "Skip image analysis after acquisition.\n"
            "Raw data is still saved and can be analysed later.")
        self._bypass_cb.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        bypass_row.addWidget(self._bypass_cb)
        bypass_row.addStretch()

        # Expert: "Edit Recipe ▸" link
        self._edit_link = QPushButton("Edit Scan Profile ▸")
        self._edit_link.setFlat(True)
        self._edit_link.setCursor(Qt.PointingHandCursor)
        self._edit_link.setStyleSheet(
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['accent']}; "
            f"border: none; padding: 0;")
        self._edit_link.setVisible(False)
        bypass_row.addWidget(self._edit_link)

        action_lay.addLayout(bypass_row)

        # Run button
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._run_btn = QPushButton("  RUN SCAN")
        set_btn_icon(self._run_btn, IC.PLAY, color=PALETTE.get("ctaText", "#fff"))
        self._run_btn.setEnabled(False)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_row.addWidget(self._run_btn)

        self._abort_btn = QPushButton()
        set_btn_icon(self._abort_btn, IC.STOP, color=PALETTE['danger'])
        self._abort_btn.setFixedSize(36, 36)
        self._abort_btn.setToolTip("Abort acquisition")
        self._abort_btn.setVisible(False)
        btn_row.addWidget(self._abort_btn)

        action_lay.addLayout(btn_row)

        # Progress bar (hidden until running)
        self._progress = QProgressBar()
        self._progress.setFixedHeight(18)
        self._progress.setTextVisible(True)
        self._progress.setVisible(False)
        action_lay.addWidget(self._progress)

        root.addWidget(action_frame)

        # ── Result strip (hidden until complete) ─────────────────────
        self._result_strip = QFrame()
        self._result_strip.setObjectName("runResult")
        result_lay = QHBoxLayout(self._result_strip)
        result_lay.setContentsMargins(12, 6, 12, 6)
        result_lay.setSpacing(12)

        self._result_icon = QLabel()
        self._result_icon.setFixedSize(18, 18)
        result_lay.addWidget(self._result_icon)

        self._result_text = QLabel("")
        self._result_text.setStyleSheet(
            f"font-family: {MONO_FONT}; "
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['text']};")
        result_lay.addWidget(self._result_text, 1)

        self._result_strip.setVisible(False)
        root.addWidget(self._result_strip)

        # ── Workflow footer (Guided mode) ────────────────────────────
        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Run Scan", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.navigate_requested.connect(self.navigate_requested)
        self._workflow_footer.setVisible(False)
        root.addWidget(self._workflow_footer)

    # ── Signal wiring ────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._recipe_combo.currentIndexChanged.connect(self._on_recipe_selected)
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._edit_link.clicked.connect(self._on_edit_clicked)

    # ── Public API ───────────────────────────────────────────────────

    def load_recipes(self, recipes: list) -> None:
        """Populate the recipe selector from a list of Recipe objects.

        Called by main_app after loading RecipeStore.
        """
        self._recipes = list(recipes)
        self._recipe_combo.blockSignals(True)
        self._recipe_combo.clear()
        for r in self._recipes:
            icon_suffix = " 🔒" if getattr(r, "locked", False) else ""
            self._recipe_combo.addItem(f"{r.label}{icon_suffix}", r.uid)
        self._recipe_combo.setCurrentIndex(-1)
        self._recipe_combo.blockSignals(False)
        self._active_recipe = None
        self._run_btn.setEnabled(False)
        self._summary_frame.setVisible(False)
        # Show/hide empty-state hint
        has_recipes = len(self._recipes) > 0
        self._empty_hint.setVisible(not has_recipes)

    def set_operator(self, name: str) -> None:
        """Pre-fill operator from lab preferences or auth session."""
        self._operator_input.setText(name)

    def set_project(self, project: str) -> None:
        """Pre-fill project from last-used or lab preferences."""
        self._project_input.setText(project)

    def on_run_progress(self, frames_done: int, frames_total: int,
                        phase: str = "") -> None:
        """Update progress bar during acquisition.

        Called by the parent from the pipeline's on_progress callback.
        """
        if not self._running:
            return
        self._progress.setMaximum(frames_total * 2 if frames_total > 0 else 100)

        if phase == "cold":
            self._progress.setValue(frames_done)
            self._progress.setFormat(f"Cold: {frames_done}/{frames_total}")
        elif phase == "delay":
            self._progress.setValue(frames_total)
            self._progress.setFormat("Inter-phase delay…")
        elif phase == "hot":
            self._progress.setValue(frames_total + frames_done)
            self._progress.setFormat(f"Hot: {frames_done}/{frames_total}")
        elif phase == "processing":
            self._progress.setMaximum(0)  # indeterminate
            self._progress.setFormat("Processing…")
        else:
            total = max(frames_total, 1)
            self._progress.setMaximum(total)
            self._progress.setValue(frames_done)

    def on_run_complete(
        self,
        acq_result,
        analysis_result=None,
        duration_s: float = 0.0,
        session_uid: str = "",
        session_label: str = "",
    ) -> None:
        """Called by the parent after acquisition (and optional analysis).

        Appends to the experiment log and updates the result strip.

        Parameters
        ----------
        acq_result
            AcquisitionResult from the pipeline.
        analysis_result
            AnalysisResult or None (if analysis was skipped/bypassed).
        duration_s
            Wall-clock time of the acquisition.
        session_uid, session_label
            Session identifiers for experiment log linkage.
        """
        self._running = False
        self._run_btn.setVisible(True)
        self._abort_btn.setVisible(False)
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)
        self._run_btn.setText("  RUN SCAN")
        set_btn_icon(self._run_btn, IC.PLAY,
                     color=PALETTE.get("ctaText", "#fff"))

        # Build experiment log entry
        recipe = self._active_recipe
        payload = self._build_payload()

        from acquisition.storage.experiment_log import make_entry
        entry = make_entry(
            source="recipe" if recipe else "manual",
            recipe_uid=payload.get("recipe_uid", ""),
            recipe_label=payload.get("recipe_label", ""),
            test_variables=payload.get("test_variables", {}),
            modality=payload.get("modality", ""),
            session_uid=session_uid,
            session_label=session_label,
            operator=payload.get("operator", ""),
            device_id=payload.get("device_id", ""),
            project=payload.get("project", ""),
            n_frames=getattr(acq_result, "n_frames", 0),
            exposure_us=getattr(acq_result, "exposure_us", 0.0),
            gain_db=getattr(acq_result, "gain_db", 0.0),
            outcome="complete",
            duration_s=duration_s,
            analysis_skipped=payload.get("bypass_analyzer", False),
            notes=payload.get("notes", ""),
            analysis_result=analysis_result,
        )

        # Append to experiment log (non-blocking, best-effort)
        try:
            from acquisition.storage.experiment_log import ExperimentLog
            log_dir = str(Path.home() / ".microsanj")
            elog = ExperimentLog(log_dir)
            elog.append(entry)
            log.info("Experiment log: appended entry %s (recipe=%s, verdict=%s)",
                     entry.entry_uid, entry.recipe_label, entry.verdict)
        except Exception:
            log.warning("Failed to append experiment log entry", exc_info=True)

        # Update result strip
        self._show_result(entry)
        self.run_completed.emit()

    def on_run_error(self, error_msg: str) -> None:
        """Called by the parent if the acquisition fails."""
        self._running = False
        self._run_btn.setVisible(True)
        self._abort_btn.setVisible(False)
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)
        self._run_btn.setText("  RUN SCAN")
        set_btn_icon(self._run_btn, IC.PLAY,
                     color=PALETTE.get("ctaText", "#fff"))

        # Log as error entry
        payload = self._build_payload()
        try:
            from acquisition.storage.experiment_log import make_entry, ExperimentLog
            entry = make_entry(
                source="recipe" if self._active_recipe else "manual",
                recipe_uid=payload.get("recipe_uid", ""),
                recipe_label=payload.get("recipe_label", ""),
                test_variables=payload.get("test_variables", {}),
                modality=payload.get("modality", ""),
                operator=payload.get("operator", ""),
                device_id=payload.get("device_id", ""),
                project=payload.get("project", ""),
                outcome="error",
                notes=error_msg[:200],
            )
            elog = ExperimentLog(str(Path.home() / ".microsanj"))
            elog.append(entry)
        except Exception:
            log.debug("Failed to log error entry", exc_info=True)

        # Show error in result strip
        self._result_icon.setStyleSheet(
            f"color: {PALETTE['danger']}; font-size: 14pt;")
        self._result_icon.setText("✕")
        self._result_text.setText(f"Error: {error_msg[:100]}")
        self._result_text.setStyleSheet(
            f"font-family: {MONO_FONT}; "
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['danger']};")
        self._result_strip.setVisible(True)

    def set_workspace_mode(self, mode: str) -> None:
        """Adjust visibility and density for the current workspace mode."""
        is_guided = (mode == "guided")
        is_expert = (mode == "expert")

        # Guided: hide context fields (auto-filled from lab prefs)
        self._context_frame.setVisible(not is_guided)

        # Expert: show "Edit Recipe ▸" link
        self._edit_link.setVisible(is_expert)

        # Guidance cards + footer (Guided mode only)
        self._cards_scroll.setVisible(is_guided and len(self._guidance_cards) > 0)
        self._workflow_footer.setVisible(is_guided)

        # Pre-fill operator from lab prefs in guided mode
        if is_guided:
            try:
                import config as cfg_mod
                op = cfg_mod.get_pref("lab.active_operator", "")
                if op:
                    self._operator_input.setText(op)
            except Exception:
                pass

    # ── Internal handlers ────────────────────────────────────────────

    def _on_recipe_selected(self, index: int) -> None:
        """Handle recipe combo selection change."""
        if index < 0 or index >= len(self._recipes):
            self._active_recipe = None
            self._run_btn.setEnabled(False)
            self._summary_frame.setVisible(False)
            self._vars_container.setVisible(False)
            return

        recipe = self._recipes[index]
        self._active_recipe = recipe
        self._run_btn.setEnabled(True)
        self._result_strip.setVisible(False)

        # Update summary strip
        self._update_summary(recipe)

        # Generate test variable inputs
        self._generate_variable_inputs(recipe)

    def _update_summary(self, recipe) -> None:
        """Populate the summary strip from recipe fields."""
        acq = recipe.acquisition
        cam = recipe.camera
        ana = recipe.analysis

        # Modality display name
        modality_map = {
            "thermoreflectance": "TR",
            "ir_lockin": "IR",
            "hybrid_tr_ir": "Hybrid",
            "opp": "OPP",
        }
        self._summary_labels["modality"].setText(
            modality_map.get(acq.modality, acq.modality[:8]))
        self._summary_labels["frames"].setText(str(cam.n_frames))
        self._summary_labels["exposure"].setText(f"{cam.exposure_us:.0f} μs")
        self._summary_labels["profile"].setText(
            recipe.profile_name or "—")
        self._summary_labels["threshold"].setText(f"{ana.threshold_k:.1f} K")

        scan_map = {"single": "Single", "autoscan": "Grid",
                     "transient": "Transient"}
        self._summary_labels["scan_type"].setText(
            scan_map.get(recipe.scan_type, recipe.scan_type))

        self._summary_frame.setVisible(True)

    def _generate_variable_inputs(self, recipe) -> None:
        """Create input fields for recipe test variables.

        If the recipe has an explicit ``variables`` list (set by the
        Recipe Builder in Expert mode), those fields are shown.
        Otherwise falls back to v1 auto-generation (bias/TEC fields
        when their respective subsystems are enabled).
        """
        # Clear old inputs
        self._variable_inputs = {}
        while self._vars_layout.rowCount() > 0:
            self._vars_layout.removeRow(0)

        variables_found = False

        # ── v2: explicit variable designation from Recipe Builder ─────
        designated = getattr(recipe, "variables", None) or []
        if designated:
            from acquisition.recipe_tab import VARIABLE_FIELDS
            for field_path in designated:
                info = VARIABLE_FIELDS.get(field_path)
                if info is None:
                    continue
                label_text, vtype, suffix = info
                # Resolve current value from the recipe
                val = self._resolve_field(recipe, field_path)
                display_label = f"{label_text}{suffix.strip()}" if suffix.strip() else label_text
                key = field_path.replace(".", "_")
                self._add_variable_input(key, display_label, str(val))
                variables_found = True

        # ── v1 fallback: auto-generate from bias/TEC enabled state ────
        if not variables_found:
            if recipe.bias.enabled:
                self._add_variable_input(
                    "bias_voltage_v", "Voltage (V)",
                    str(recipe.bias.voltage_v))
                self._add_variable_input(
                    "bias_current_a", "Current (A)",
                    str(recipe.bias.current_a))
                variables_found = True
            if recipe.tec.enabled:
                self._add_variable_input(
                    "tec_setpoint_c", "Temperature (°C)",
                    str(recipe.tec.setpoint_c))
                variables_found = True

        self._vars_container.setVisible(variables_found)

    @staticmethod
    def _resolve_field(recipe, dotted_path: str):
        """Resolve a dotted field path like 'bias.voltage_v' on a Recipe."""
        parts = dotted_path.split(".", 1)
        obj = recipe
        for part in parts:
            obj = getattr(obj, part, None)
            if obj is None:
                return ""
        return obj

    def _add_variable_input(self, key: str, label: str,
                            default: str = "") -> None:
        """Add a single test variable input to the form."""
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['textDim']};")
        inp = QLineEdit()
        inp.setText(default)
        inp.setMaximumWidth(120)
        inp.setStyleSheet(
            f"font-family: {MONO_FONT}; "
            f"font-size: {FONT['caption']}pt;")
        self._vars_layout.addRow(lbl, inp)
        self._variable_inputs[key] = inp

    def _build_payload(self) -> dict:
        """Assemble the run payload from current UI state."""
        recipe = self._active_recipe
        if recipe is None:
            return {}

        payload = RecipeRunPayload(
            recipe_uid=recipe.uid,
            recipe_label=recipe.label,
            scan_type=recipe.scan_type,
            modality=recipe.acquisition.modality,
            n_frames=recipe.camera.n_frames,
            exposure_us=recipe.camera.exposure_us,
            gain_db=recipe.camera.gain_db,
            inter_phase_delay_s=recipe.acquisition.inter_phase_delay_s,
            threshold_k=recipe.analysis.threshold_k,
            bypass_analyzer=self._bypass_cb.isChecked(),
            bias_enabled=recipe.bias.enabled,
            bias_voltage_v=recipe.bias.voltage_v,
            bias_current_a=recipe.bias.current_a,
            tec_enabled=recipe.tec.enabled,
            tec_setpoint_c=recipe.tec.setpoint_c,
            profile_name=recipe.profile_name,
            operator=self._operator_input.text().strip(),
            device_id=self._device_input.text().strip(),
            project=self._project_input.text().strip(),
            notes=self._notes_input.text().strip(),
        )

        # Collect test variables from dynamic inputs
        test_vars = {}
        for key, inp in self._variable_inputs.items():
            val = inp.text().strip()
            # Try numeric conversion
            try:
                test_vars[key] = float(val)
            except ValueError:
                test_vars[key] = val
        payload.test_variables = test_vars

        # Override bias/tec from variable inputs if present
        if "bias_voltage_v" in test_vars:
            try:
                payload.bias_voltage_v = float(test_vars["bias_voltage_v"])
            except (ValueError, TypeError):
                pass
        if "bias_current_a" in test_vars:
            try:
                payload.bias_current_a = float(test_vars["bias_current_a"])
            except (ValueError, TypeError):
                pass
        if "tec_setpoint_c" in test_vars:
            try:
                payload.tec_setpoint_c = float(test_vars["tec_setpoint_c"])
            except (ValueError, TypeError):
                pass

        return payload.to_dict()

    def _on_run_clicked(self) -> None:
        """Handle RUN button click."""
        if self._active_recipe is None:
            return
        if self._running:
            return

        self._running = True
        self._result_strip.setVisible(False)
        self._run_btn.setText("  Running…")
        self._run_btn.setEnabled(False)
        self._abort_btn.setVisible(True)
        self._progress.setValue(0)
        self._progress.setMaximum(100)
        self._progress.setFormat("Starting…")
        self._progress.setVisible(True)

        payload = self._build_payload()
        self.run_requested.emit(payload)

    def _on_edit_clicked(self) -> None:
        """Handle "Edit Recipe ▸" link (Expert mode)."""
        if self._active_recipe:
            self.edit_recipe_requested.emit(self._active_recipe.uid)

    def _show_result(self, entry) -> None:
        """Update the result strip after a completed run."""
        verdict = entry.verdict or "—"
        outcome = entry.outcome

        if outcome == "complete" and verdict == "pass":
            icon_text, icon_color = "✓", PALETTE['success']
        elif outcome == "complete" and verdict == "warning":
            icon_text, icon_color = "⚠", PALETTE['warning']
        elif outcome == "complete" and verdict == "fail":
            icon_text, icon_color = "✕", PALETTE['danger']
        elif outcome == "error":
            icon_text, icon_color = "✕", PALETTE['danger']
        else:
            icon_text, icon_color = "●", PALETTE['textDim']

        self._result_icon.setText(icon_text)
        self._result_icon.setStyleSheet(
            f"color: {icon_color}; font-size: 14pt; font-weight: bold;")

        parts = [outcome.title()]
        if entry.duration_s > 0:
            parts.append(f"{entry.duration_s:.1f}s")
        if verdict and verdict != "—":
            parts.append(verdict.title())
        if entry.hotspot_count > 0:
            spots = entry.hotspot_count
            parts.append(f"{spots} hotspot{'s' if spots != 1 else ''}")
        if entry.analysis_skipped:
            parts.append("(analysis skipped)")

        self._result_text.setText("  ·  ".join(parts))
        self._result_text.setStyleSheet(
            f"font-family: {MONO_FONT}; "
            f"font-size: {FONT['caption']}pt; "
            f"color: {PALETTE['text']};")
        self._result_strip.setVisible(True)

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Apply palette-aware styles."""
        self._run_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['cta']}; "
            f"  color: {PALETTE.get('ctaText', '#fff')}; "
            f"  border: none; border-radius: 6px; "
            f"  font-size: {FONT['body']}pt; font-weight: 600; "
            f"  padding: 4px 16px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE.get('ctaHover', PALETTE['cta'])};"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background: {PALETTE['surface2']}; "
            f"  color: {PALETTE['textDim']};"
            f"}}")

        self._abort_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; border: 1px solid {PALETTE['danger']}; "
            f"  border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['danger']}20;"
            f"}}")

        self._summary_frame.setStyleSheet(
            f"#recipeSummary {{"
            f"  background: {PALETTE['surface']}; "
            f"  border-top: 1px solid {PALETTE['border']}; "
            f"  border-bottom: 1px solid {PALETTE['border']};"
            f"}}")

        self._result_strip.setStyleSheet(
            f"#runResult {{"
            f"  background: {PALETTE['surface']}; "
            f"  border-top: 1px solid {PALETTE['border']};"
            f"}}")

        self._progress.setStyleSheet(
            f"QProgressBar {{"
            f"  background: {PALETTE['surface2']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 4px; "
            f"  text-align: center; "
            f"  font-size: {FONT['small']}pt; "
            f"  color: {PALETTE['text']};"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background: {PALETTE['accent']}; "
            f"  border-radius: 3px;"
            f"}}")

        combo_qss = (
            f"QComboBox {{"
            f"  background: {PALETTE['surface']}; "
            f"  color: {PALETTE['text']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 4px; "
            f"  padding: 4px 8px; "
            f"  font-size: {FONT['body']}pt;"
            f"}}"
            f"QComboBox:hover {{ border-color: {PALETTE['accent']}; }}"
            f"QComboBox::drop-down {{"
            f"  border: none; width: 20px;"
            f"}}"
        )
        self._recipe_combo.setStyleSheet(combo_qss)

        line_qss = (
            f"QLineEdit {{"
            f"  background: {PALETTE['surface']}; "
            f"  color: {PALETTE['text']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 3px; "
            f"  padding: 3px 6px; "
            f"  font-size: {FONT['caption']}pt;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {PALETTE['accent']}; }}"
        )
        self._operator_input.setStyleSheet(line_qss)
        self._device_input.setStyleSheet(line_qss)
        self._project_input.setStyleSheet(line_qss)
        self._notes_input.setStyleSheet(line_qss)
