"""
ui/tabs/acquire_tab.py

AcquireTab — the main acquisition tab for cold/hot capture and ΔR/R computation.
"""

from __future__ import annotations

import time
import threading
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QProgressBar, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QComboBox, QTextEdit, QFileDialog, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from ui.icons import set_btn_icon
from ui.theme import progress_bar_qss, FONT, PALETTE, scaled_qss
from ui.widgets.time_estimate_label import TimeEstimateLabel

from hardware.app_state import app_state
from acquisition        import AcquisitionProgress, AcqState
from acquisition        import export_result
from acquisition.processing import COLORMAP_OPTIONS, COLORMAP_TOOLTIPS, setup_cmap_combo
import config as cfg_mod
from ui.widgets.image_pane import ImagePane
from ui.widgets.more_options import MoreOptionsPanel


class AcquireTab(QWidget):
    # Emitted when the user clicks Run — MainWindow intercepts for readiness gate
    acquire_requested = pyqtSignal(int, float)   # (n_frames, inter_phase_delay)
    optimize_and_acquire_requested = pyqtSignal(int, float)  # same args
    workflow_changed = pyqtSignal(object)  # WorkflowProfile | None

    def __init__(self):
        super().__init__()
        self._result = None
        root = QHBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # LEFT — scrollable panel
        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setSpacing(8)
        left.setContentsMargins(0, 0, 0, 0)
        self._left_layout = left   # exposed for ReadinessWidget injection

        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_widget)
        root.addWidget(left_scroll, 2)

        # Live feed
        live_box = QGroupBox("Live Feed")
        ll = QVBoxLayout(live_box)
        self._live = ImagePane("", 500, 375)
        ll.addWidget(self._live)
        left.addWidget(live_box)

        # Controls
        ctrl_box = QGroupBox("Capture")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(8)
        cl.setColumnStretch(1, 1)

        # Workflow selector — Failure Analysis vs Metrology
        from ui.help import help_label
        cl.addWidget(help_label("Workflow", "workflow"), 0, 0)
        self._workflow_combo = QComboBox()
        self._workflow_combo.addItem("Default", "")
        try:
            from acquisition.workflows import WORKFLOWS
            for wf in WORKFLOWS.values():
                self._workflow_combo.addItem(wf.display_name, wf.name)
        except ImportError:
            pass
        self._workflow_combo.setToolTip(
            "Select a measurement workflow.\n\n"
            "Failure Analysis: Rapid imaging for defect localization "
            "(fewer frames, relaxed preflight).\n"
            "Metrology: Precision calibrated measurements "
            "(more frames, strict preflight, calibration required).")
        self._workflow_combo.currentIndexChanged.connect(
            self._on_workflow_changed)
        cl.addWidget(self._workflow_combo, 0, 1)

        cl.addWidget(help_label("Frames / phase", "n_frames"), 1, 0)
        self._frames = QSpinBox()
        self._frames.setRange(1, 10000)
        self._frames.setValue(100)
        self._frames.setSuffix(" frames")
        self._frames.setMinimumWidth(110)
        cl.addWidget(self._frames, 1, 1)

        self._delay_label = self._sub("Phase delay (s)")
        cl.addWidget(self._delay_label, 2, 0)
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0, 60)
        self._delay.setValue(0)
        self._delay.setSingleStep(0.5)
        self._delay.setSuffix(" s")
        self._delay.setMinimumWidth(90)
        self._delay.setToolTip(
            "Wait time between switching from cold to hot (or vice versa).\n"
            "Allows the device to reach thermal equilibrium after the stimulus changes.\n"
            "Set to 0 for rapid alternating measurements.")
        cl.addWidget(self._delay, 2, 1)

        self._time_est_lbl = TimeEstimateLabel()
        cl.addWidget(self._time_est_lbl, 3, 0, 1, 2)

        cl.addWidget(self._sub("ΔR/R colormap"), 4, 0)
        self._cmap = QComboBox()
        self._cmap.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap, saved_cmap)
        self._cmap.currentTextChanged.connect(self._on_cmap_changed)
        cl.addWidget(self._cmap, 4, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self._cold_btn = QPushButton("COLD")
        set_btn_icon(self._cold_btn, "fa5s.snowflake", "#66aaff")
        self._cold_btn.setObjectName("cold_btn")
        self._cold_btn.setToolTip(
            "Capture cold (baseline) frames only.\n"
            "Use this when you want to set up the cold reference manually "
            "before applying the stimulus.")
        self._hot_btn  = QPushButton("HOT")
        set_btn_icon(self._hot_btn, "fa5s.fire", "#ff8866")
        self._hot_btn.setObjectName("hot_btn")
        self._hot_btn.setToolTip(
            "Capture hot (stimulus) frames and compute ΔR/R immediately.\n"
            "Requires a cold reference to already be captured.")
        self._run_btn  = QPushButton("RUN SEQUENCE")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setObjectName("primary")
        self._run_btn.setToolTip(
            "Run the full cold → hot acquisition sequence automatically.\n"
            "Captures cold baseline, applies stimulus, captures hot frames, "
            "then computes ΔR/R and ΔT.\n\n"
            "Keyboard shortcut: Ctrl+R")
        self._opt_acq_btn = QPushButton("OPTIMIZE && ACQUIRE")
        set_btn_icon(self._opt_acq_btn, "fa5s.magic", PALETTE.get("accent", "#00bcd4"))
        self._opt_acq_btn.setToolTip(
            "Run auto-expose, auto-gain, TEC preconditioning, and preflight\n"
            "validation, then start acquisition automatically.\n\n"
            "Equivalent to manually optimising each parameter before clicking\n"
            "RUN SEQUENCE, but in one click.")
        self._abort_btn = QPushButton("ABORT")
        set_btn_icon(self._abort_btn, "fa5s.stop", "#ff6666")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setToolTip(
            "Abort the current acquisition immediately.\n"
            "Any frames already captured will be discarded.\n\n"
            "Keyboard shortcut: Escape")
        self._abort_btn.setEnabled(False)
        for b in [self._cold_btn, self._hot_btn,
                  self._run_btn, self._opt_acq_btn, self._abort_btn]:
            btn_row.addWidget(b)
        cl.addLayout(btn_row, 4, 0, 1, 2)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setStyleSheet(progress_bar_qss())
        cl.addWidget(self._progress, 5, 0, 1, 2)

        # Recipe quick-access row
        from PyQt5.QtWidgets import QFrame as _QFrame
        recipe_row = QHBoxLayout()
        recipe_lbl = QLabel("Recipe:")
        recipe_lbl.setStyleSheet(f"color:#555; font-size:{FONT['label']}pt;")
        recipe_row.addWidget(recipe_lbl)
        self._active_recipe_lbl = QLabel("(none)")
        self._active_recipe_lbl.setStyleSheet(
            f"color:#00d4aa; font-size:{FONT['label']}pt; font-style:italic;")
        recipe_row.addWidget(self._active_recipe_lbl, 1)
        self._load_recipe_btn = QPushButton("Load Recipe…")
        set_btn_icon(self._load_recipe_btn, "fa5s.clipboard-list")
        self._load_recipe_btn.setFixedHeight(26)
        self._load_recipe_btn.setToolTip(
            "Open the Recipe Manager to select and apply a hardware + "
            "acquisition configuration preset")
        self._load_recipe_btn.clicked.connect(self._open_recipe_manager)
        recipe_row.addWidget(self._load_recipe_btn)
        cl.addLayout(recipe_row, 6, 0, 1, 2)

        left.addWidget(ctrl_box)

        # Notes & Log — collapsed in Guided mode, expanded in Expert
        self._notes_more = MoreOptionsPanel(
            "Session Notes & Log", section_key="acquire_notes_log")
        notes_log_w = QWidget()
        notes_log_lay = QVBoxLayout(notes_log_w)
        notes_log_lay.setContentsMargins(0, 0, 0, 0)
        notes_log_lay.setSpacing(6)

        # Session notes — annotate before saving
        notes_box = QGroupBox("Session Notes")
        notes_box.setToolTip(
            "Notes are saved with the session. Describe sample, conditions, "
            "DUT ID, or anything relevant to reproduce this measurement.")
        nl = QVBoxLayout(notes_box)
        nl.setContentsMargins(8, 6, 8, 6)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText(
            "Sample ID, conditions, DUT info, temperature, bias settings…\n"
            "e.g.  Au on Si, 25°C ambient, Vbias=1.5 V, dark room")
        self._notes_edit.setMaximumHeight(70)
        self._notes_edit.setStyleSheet(
            f"background:{PALETTE.get('bg','#242424')}; color:{PALETTE.get('text','#ebebeb')}; border:1px solid {PALETTE.get('border','#484848')}; "
            f"font-size:{FONT['body']}pt; font-family:'Menlo','Consolas','Courier New',monospace;")
        nl.addWidget(self._notes_edit)

        # Quick-insert chips for common tags
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        chips_lbl = QLabel("Quick tags:")
        chips_lbl.setObjectName("sublabel")
        chips_row.addWidget(chips_lbl)
        self._chip_btns = []
        for chip_text in ["25°C", "dark room", "no bias", "after reflow",
                           "calibrated", "reference sample"]:
            btn = QPushButton(chip_text)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                f"QPushButton {{ background:{PALETTE.get('surface2','#3d3d3d')}; color:{PALETTE.get('accent','#00d4aa')}; "
                f"border:1px solid {PALETTE.get('accent','#00d4aa')}44; border-radius:10px; "
                f"font-size:{FONT['sublabel']}pt; padding:0 8px; }}"
                f"QPushButton:hover {{ background:{PALETTE.get('surface','#2d2d2d')}; }}")
            btn.clicked.connect(
                lambda _, t=chip_text: self._insert_notes_chip(t))
            chips_row.addWidget(btn)
            self._chip_btns.append(btn)
        chips_row.addStretch()
        nl.addLayout(chips_row)
        notes_log_lay.addWidget(notes_box)

        # Log
        log_box = QGroupBox("Log")
        logl = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(80)
        self._log.setMaximumHeight(140)
        logl.addWidget(self._log)
        notes_log_lay.addWidget(log_box)

        self._notes_more.addWidget(notes_log_w)
        left.addWidget(self._notes_more)

        # RIGHT — results
        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 2)

        res_box = QGroupBox("Results")
        rl = QGridLayout(res_box)
        rl.setSpacing(6)
        self._cold_pane = ImagePane("COLD  (baseline)", 310, 230)
        self._hot_pane  = ImagePane("HOT  (stimulus)",  310, 230)
        self._diff_pane = ImagePane("DIFFERENCE  hot − cold", 310, 230)
        self._drr_pane  = ImagePane("ΔR/R  thermoreflectance", 310, 230)
        self._dt_pane   = ImagePane("ΔT  temperature change  (°C)", 310, 230)
        rl.addWidget(self._cold_pane, 0, 0)
        rl.addWidget(self._hot_pane,  0, 1)
        rl.addWidget(self._diff_pane, 1, 0)
        rl.addWidget(self._drr_pane,  1, 1)
        rl.addWidget(self._dt_pane,   2, 0, 1, 2)
        right.addWidget(res_box)

        bot = QHBoxLayout()
        self._snr_lbl = QLabel("SNR  —")
        self._snr_lbl.setStyleSheet(
            scaled_qss("font-family:'Menlo','Consolas','Courier New',monospace; font-size:15pt; color:#555;"))
        self._export_btn = QPushButton("Export")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._export_btn.setToolTip("Export acquisition results to a folder")
        self._export_btn.setEnabled(False)
        bot.addWidget(self._snr_lbl)
        bot.addStretch()
        bot.addWidget(self._export_btn)
        right.addLayout(bot)

        # Wire buttons
        self._cold_btn.clicked.connect(self._cap_cold)
        self._hot_btn.clicked.connect(self._cap_hot)
        self._run_btn.clicked.connect(self._run)
        self._opt_acq_btn.clicked.connect(self._optimize_and_acquire)
        self._abort_btn.clicked.connect(self._abort)
        self._export_btn.clicked.connect(self._export)

        # Time estimation updates
        self._frames.valueChanged.connect(self._update_time_est)
        self._delay.valueChanged.connect(self._update_time_est)
        self._update_time_est()

    def _update_time_est(self) -> None:
        """Recalculate and display the estimated acquisition time."""
        try:
            cam_info = getattr(app_state.cam, "info", None)
            fps = getattr(cam_info, "max_fps", 30) if cam_info else 30
        except Exception:
            fps = 30
        fps = max(fps, 1)  # guard against zero/negative
        frames = self._frames.value()
        delay = self._delay.value()
        total = 2 * (frames / fps) + delay
        detail = (f"2 × ({frames} frames / {fps} fps)"
                  + (f" + {delay:.1f} s delay" if delay else ""))
        self._time_est_lbl.set_estimate(total, detail)

    def _apply_styles(self) -> None:
        P = PALETTE
        bg  = P.get("bg",      "#242424")
        txt = P.get("text",    "#ebebeb")
        bdr = P.get("border",  "#484848")
        if hasattr(self, "_notes_edit"):
            self._notes_edit.setStyleSheet(
                f"background:{bg}; color:{txt}; border:1px solid {bdr}; "
                f"font-size:{FONT['body']}pt; font-family:'Menlo','Consolas','Courier New',monospace;")
        acc = P.get("accent",   "#00d4aa")
        su2 = P.get("surface2", "#3d3d3d")
        sur = P.get("surface",  "#2d2d2d")
        if hasattr(self, "_time_est_lbl"):
            self._time_est_lbl.setStyleSheet(
                f"color:{P.get('textDim','#888')}; font-size:{FONT['caption']}pt;")
        for btn in getattr(self, "_chip_btns", []):
            btn.setStyleSheet(
                f"QPushButton {{ background:{su2}; color:{acc}; "
                f"border:1px solid {acc}44; border-radius:10px; "
                f"font-size:{FONT['sublabel']}pt; padding:0 8px; }}"
                f"QPushButton:hover {{ background:{sur}; }}")

    def set_active_recipe_name(self, name: str | None) -> None:
        """Called by MainWindow when a recipe is applied to reflect its name."""
        self._active_recipe_lbl.setText(name or "(none)")

    def _open_recipe_manager(self):
        """Navigate to the Recipe tab (makes it visible to the user)."""
        # Walk up to MainWindow and switch to the Recipe tab
        w = self.window()
        recipe_tab = getattr(w, '_recipe_tab', None)
        nav = getattr(w, '_nav', None)
        if recipe_tab is not None and nav is not None:
            nav.navigate_to(recipe_tab)

    def insert_readiness_widget(self, widget) -> None:
        """
        Insert *widget* at the top of the left column.
        Called by MainWindow after constructing MetricsService.
        """
        self._left_layout.insertWidget(0, widget)

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def get_notes(self) -> str:
        """Return the current session notes (called by MainWindow before saving)."""
        return self._notes_edit.toPlainText().strip()

    def _insert_notes_chip(self, text: str):
        """Insert a quick-tag chip at the cursor position."""
        cursor = self._notes_edit.textCursor()
        existing = self._notes_edit.toPlainText()
        if existing and not existing.endswith(", ") and not existing.endswith("\n"):
            cursor.insertText(", ")
        cursor.insertText(text)
        self._notes_edit.setFocus()

    def update_live(self, frame):
        self._live.show_array(frame.data, mode="auto")

    def update_progress(self, p: AcquisitionProgress):
        self.log(p.message)
        if p.phase == "cold":
            self._progress.setValue(int(p.fraction * 50))
        elif p.phase == "hot":
            self._progress.setValue(50 + int(p.fraction * 50))
        elif p.state in (AcqState.COMPLETE, AcqState.ABORTED, AcqState.ERROR):
            self._set_busy(False)
            if p.state == AcqState.COMPLETE:
                self._progress.setValue(100)

    def _on_workflow_changed(self, index: int):
        """Handle workflow combo selection change."""
        name = self._workflow_combo.currentData()
        if not name:
            # "Default" selected — no workflow profile
            self.workflow_changed.emit(None)
            return
        try:
            from acquisition.workflows import get_workflow
            wf = get_workflow(name)
            if wf:
                self._frames.setValue(wf.default_n_frames)
                self._frames.setMinimum(wf.min_n_frames)
                self.workflow_changed.emit(wf)
        except ImportError:
            pass

    def _on_cmap_changed(self, cmap: str):
        cfg_mod.set_pref("display.colormap", cmap)
        if self._result is not None and self._result.delta_r_over_r is not None:
            mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
            self._drr_pane.show_array(self._result.delta_r_over_r, mode=mode, cmap=cmap)

    def update_result(self, result):
        self._result = result
        cmap = self._cmap.currentText()
        if result.cold_avg is not None:
            self._cold_pane.show_array(result.cold_avg)
        if result.hot_avg is not None:
            self._hot_pane.show_array(result.hot_avg)
        if result.difference is not None:
            self._diff_pane.show_array(result.difference, mode="percentile")
        if result.delta_r_over_r is not None:
            mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
            self._drr_pane.show_array(result.delta_r_over_r, mode=mode, cmap=cmap)
        # Show ΔT map if calibration was applied
        dt = getattr(result, "delta_t", None)
        if dt is not None:
            self._dt_pane.show_array(dt, mode="signed", cmap="Thermal Delta")
            self._dt_pane._title.setText("ΔT  temperature change  (°C)  ✓ calibrated")
        else:
            self._dt_pane.clear()
            self._dt_pane._title.setText("ΔT  — no calibration active")
        if result.snr_db is not None:
            self._snr_lbl.setText(f"SNR  {result.snr_db:.1f} dB")
        self._export_btn.setEnabled(True)

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}]  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())

    def _set_busy(self, busy):
        self._cold_btn.setEnabled(not busy)
        self._hot_btn.setEnabled(not busy)
        self._run_btn.setEnabled(not busy)
        self._abort_btn.setEnabled(busy)

    def _cap_cold(self):
        self._set_busy(True)
        self._progress.setRange(0, 0)   # indeterminate spinner while capturing
        self.log("Capturing cold frames...")

        def _done():
            self._progress.setRange(0, 100)
            self._set_busy(False)

        def _run():
            pl = app_state.pipeline
            if pl is None:
                self.log("No acquisition pipeline — is hardware connected?")
                QTimer.singleShot(0, _done)
                return
            r = pl.capture_reference(self._frames.value())
            if r is not None:
                if self._result is None:
                    from acquisition.pipeline import AcquisitionResult
                    self._result = AcquisitionResult(n_frames=self._frames.value())
                self._result.cold_avg = r
                self._cold_pane.show_array(r)
                self.log(f"Cold: mean={r.mean():.1f}")
            QTimer.singleShot(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _cap_hot(self):
        self._set_busy(True)
        self._progress.setRange(0, 0)   # indeterminate spinner while capturing
        self.log("Capturing hot frames...")

        def _done():
            self._progress.setRange(0, 100)
            self._set_busy(False)

        def _run():
            pl = app_state.pipeline
            if pl is None:
                self.log("No acquisition pipeline — is hardware connected?")
                QTimer.singleShot(0, _done)
                return
            r = pl.capture_reference(self._frames.value())
            if r is not None:
                if self._result is None:
                    from acquisition.pipeline import AcquisitionResult
                    self._result = AcquisitionResult(n_frames=self._frames.value())
                self._result.hot_avg = r
                self._hot_pane.show_array(r)
                self.log(f"Hot: mean={r.mean():.1f}")
                if self._result.cold_avg is not None:
                    from acquisition.pipeline import AcquisitionPipeline
                    AcquisitionPipeline._compute(self._result)
                    self.update_result(self._result)
            QTimer.singleShot(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _run(self):
        """Called by the Run button. Emits acquire_requested for readiness gate."""
        if app_state.pipeline is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self.acquire_requested.emit(self._frames.value(), self._delay.value())

    def _optimize_and_acquire(self):
        """Called by Optimize & Acquire button."""
        if app_state.pipeline is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self.optimize_and_acquire_requested.emit(
            self._frames.value(), self._delay.value())

    def insert_suggestions_widget(self, widget):
        """Insert an optimization suggestions widget below readiness."""
        self._left_layout.insertWidget(1, widget)

    def start_acquisition(self, n_frames: int, inter_phase_delay: float = 0.0) -> None:
        """
        Actually start the acquisition pipeline.

        Called by MainWindow after the readiness gate is satisfied (or bypassed).
        Also used by the recipe system.
        """
        pl = app_state.pipeline
        if pl is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self._set_busy(True)
        self._progress.setValue(0)
        self.log("Starting acquisition sequence...")
        pl.start(n_frames=n_frames, inter_phase_delay=inter_phase_delay)

    def _abort(self):
        pl = app_state.pipeline
        if pl:
            pl.abort()

    def _export(self):
        if not self._result or not self._result.is_complete:
            return
        d = QFileDialog.getExistingDirectory(self, "Export folder", ".")
        if d:
            saved = export_result(self._result, d)
            self.log(f"Exported {len(saved)} files → {d}")

    def set_n_frames(self, n: int):
        """Update the frame count spinbox (called when a profile is applied)."""
        self._frames.setValue(int(n))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_camera_mode()

    def refresh_camera_mode(self) -> None:
        """Adapt UI controls for IR vs TR camera mode.

        IR cameras capture thermal frames directly — no cold/hot phase
        separation or stimulus is needed.  TR cameras use the full
        cold → stimulus → hot → ΔR/R pipeline.
        """
        is_ir = getattr(app_state, "active_camera_type", "tr") == "ir"
        # Phase buttons (TR only)
        self._cold_btn.setVisible(not is_ir)
        self._hot_btn.setVisible(not is_ir)
        # Phase delay and time estimate (TR only — IR has no stimulus switching)
        self._delay.setVisible(not is_ir)
        self._delay_label.setVisible(not is_ir)
        self._time_est_lbl.setVisible(not is_ir)
        # Update RUN button label
        if is_ir:
            self._run_btn.setText("CAPTURE")
            self._run_btn.setToolTip(
                "Capture thermal frames from the IR camera.\n\n"
                "Keyboard shortcut: Ctrl+R")
        else:
            self._run_btn.setText("RUN SEQUENCE")
            self._run_btn.setToolTip(
                "Run the full cold → hot acquisition sequence automatically.\n"
                "Captures cold baseline, applies stimulus, captures hot frames, "
                "then computes ΔR/R and ΔT.\n\n"
                "Keyboard shortcut: Ctrl+R")
