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
    QGroupBox, QComboBox, QTextEdit, QFileDialog, QScrollArea,
    QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from ui.icons import set_btn_icon
from ui.theme import progress_bar_qss, FONT, PALETTE, scaled_qss, MONO_FONT
from ui.widgets.time_estimate_label import TimeEstimateLabel
from ui.widgets.tab_helpers import make_sub

from hardware.app_state import app_state
from acquisition        import AcquisitionProgress, AcqState
from acquisition        import export_result
from acquisition.processing import COLORMAP_OPTIONS, COLORMAP_TOOLTIPS, setup_cmap_combo
import config as cfg_mod
from ui.widgets.image_pane import ImagePane
from ui.widgets.more_options import MoreOptionsPanel
from ui.widgets.compact_controls import QuickControlsBar


class AcquireTab(QWidget):
    # Emitted when the user clicks Run — MainWindow intercepts for readiness gate
    acquire_requested = pyqtSignal(int, float)   # (n_frames, inter_phase_delay)
    optimize_and_acquire_requested = pyqtSignal(int, float)  # same args
    workflow_changed = pyqtSignal(object)  # WorkflowProfile | None

    def __init__(self):
        super().__init__()
        self._result = None
        self._prev_settings: dict | None = None   # for undo
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

        # Quick hardware controls bar
        self._quick_controls = QuickControlsBar()
        left.addWidget(self._quick_controls)

        # Hardware summary strip (timing + bias)
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        self._hw_strip = HwSummaryStrip()
        left.addWidget(self._hw_strip)

        # Live feed
        live_box = QGroupBox("Live Feed")
        ll = QVBoxLayout(live_box)
        self._live = ImagePane("", 500, 375, expanding=True)
        ll.addWidget(self._live)

        # Camera context strip (identity + modality confirmation + detach)
        ctx_row = QHBoxLayout()
        ctx_row.setContentsMargins(0, 0, 0, 0)
        ctx_row.setSpacing(8)

        self._cam_ctx_lbl = QLabel("")
        self._cam_ctx_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
        ctx_row.addWidget(self._cam_ctx_lbl)

        ctx_row.addStretch()

        self._mode_badge = QLabel("")
        self._mode_badge.setAlignment(Qt.AlignCenter)
        self._mode_badge.setFixedHeight(20)
        self._mode_badge.setVisible(False)
        ctx_row.addWidget(self._mode_badge)

        # Detach button — open large viewer window
        self._detach_btn = QPushButton()
        set_btn_icon(self._detach_btn, "mdi.open-in-new", PALETTE['textDim'])
        self._detach_btn.setFixedSize(24, 24)
        self._detach_btn.setToolTip(
            "Open a detached large viewer window.\n"
            "Can be moved to a second monitor or made full-screen (F11).")
        self._detach_btn.setFlat(True)
        self._detach_btn.clicked.connect(self._on_detach_viewer)
        ctx_row.addWidget(self._detach_btn)

        ll.addLayout(ctx_row)
        left.addWidget(live_box)

        # ROI status bar
        from acquisition.roi_model import roi_model
        roi_row = QHBoxLayout()
        roi_row.setSpacing(6)
        self._roi_status = QLabel("No ROIs defined")
        self._roi_status.setStyleSheet(scaled_qss(
            f"font-family:{MONO_FONT}; font-size:8pt; "
            f"color:{PALETTE['textDim']};"))
        roi_row.addWidget(self._roi_status)
        roi_row.addStretch()
        self._roi_manage_btn = QPushButton("Manage ROIs")
        self._roi_manage_btn.setFixedHeight(22)
        self._roi_manage_btn.clicked.connect(self._open_roi_tab)
        roi_row.addWidget(self._roi_manage_btn)
        left.addLayout(roi_row)

        # Subscribe to ROI model changes
        self._roi_model = roi_model
        roi_model.rois_changed.connect(self._update_roi_status)

        # Controls
        ctrl_box = QGroupBox("Capture")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(8)
        cl.setColumnStretch(1, 1)

        # Workflow selector — Failure Analysis vs Metrology
        from ui.help import help_label
        cl.addWidget(help_label("Workflow", "workflow"), 0, 0)
        self._workflow_combo = QComboBox()
        self._workflow_combo.setAccessibleName("Measurement workflow")
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
        self._frames.setAccessibleName("Frames per phase")
        self._frames.setAccessibleDescription(
            "Number of frames to capture in each cold and hot phase")
        cl.addWidget(self._frames, 1, 1)

        self._delay_label = self._sub("Phase delay (s)")
        cl.addWidget(self._delay_label, 2, 0)
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0, 60)
        self._delay.setValue(0)
        self._delay.setSingleStep(0.5)
        self._delay.setSuffix(" s")
        self._delay.setMinimumWidth(90)
        self._delay.setAccessibleName("Phase delay")
        self._delay.setAccessibleDescription(
            "Wait time in seconds between cold and hot phases")
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
        self._cmap.setAccessibleName("Delta R over R colormap")
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap, saved_cmap)
        self._cmap.currentTextChanged.connect(self._on_cmap_changed)
        cl.addWidget(self._cmap, 4, 1)

        # Sync colormap from other tabs
        from ui.app_signals import signals as _sig
        _sig.colormap_changed.connect(self._on_cmap_remote)

        # Buttons
        btn_row = QHBoxLayout()
        self._cold_btn = QPushButton("COLD")
        set_btn_icon(self._cold_btn, "fa5s.snowflake", PALETTE['info'])
        self._cold_btn.setObjectName("cold_btn")
        self._cold_btn.setAccessibleName("Capture cold frames")
        self._cold_btn.setToolTip(
            "Capture cold (baseline) frames only.\n"
            "Use this when you want to set up the cold reference manually "
            "before applying the stimulus.")
        self._hot_btn  = QPushButton("HOT")
        set_btn_icon(self._hot_btn, "fa5s.fire", PALETTE['danger'])
        self._hot_btn.setObjectName("hot_btn")
        self._hot_btn.setAccessibleName("Capture hot frames")
        self._hot_btn.setToolTip(
            "Capture hot (stimulus) frames and compute ΔR/R immediately.\n"
            "Requires a cold reference to already be captured.")
        self._run_btn  = QPushButton("RUN SEQUENCE")
        set_btn_icon(self._run_btn, "fa5s.play", PALETTE['accent'])
        self._run_btn.setObjectName("primary")
        self._run_btn.setAccessibleName("Run acquisition sequence")
        self._run_btn.setAccessibleDescription(
            "Run full cold-hot acquisition sequence. Shortcut: F5")
        self._run_btn.setToolTip(
            "Run the full cold → hot acquisition sequence automatically.\n"
            "Captures cold baseline, applies stimulus, captures hot frames, "
            "then computes ΔR/R and ΔT.\n\n"
            "Keyboard shortcut: F5")
        self._opt_acq_btn = QPushButton("OPTIMIZE && ACQUIRE")
        set_btn_icon(self._opt_acq_btn, "fa5s.magic", PALETTE['accent'])
        self._opt_acq_btn.setToolTip(
            "Run auto-expose, auto-gain, TEC preconditioning, and preflight\n"
            "validation, then start acquisition automatically.\n\n"
            "Equivalent to manually optimising each parameter before clicking\n"
            "RUN SEQUENCE, but in one click.")
        self._abort_btn = QPushButton("ABORT")
        set_btn_icon(self._abort_btn, "fa5s.stop", PALETTE['danger'])
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setAccessibleName("Abort acquisition")
        self._abort_btn.setAccessibleDescription(
            "Abort current acquisition and discard frames. Shortcut: Escape")
        self._abort_btn.setToolTip(
            "Abort the current acquisition immediately.\n"
            "Any frames already captured will be discarded.\n\n"
            "Keyboard shortcut: Escape")
        self._abort_btn.setEnabled(False)
        self._restore_btn = QPushButton("Restore")
        set_btn_icon(self._restore_btn, "fa5s.undo")
        self._restore_btn.setAccessibleName("Restore previous settings")
        self._restore_btn.setToolTip(
            "Restore acquisition settings from before the last run.")
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._restore_settings)
        for b in [self._cold_btn, self._hot_btn,
                  self._run_btn, self._opt_acq_btn, self._abort_btn,
                  self._restore_btn]:
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
        recipe_lbl.setStyleSheet(f"color:{PALETTE['textSub']}; font-size:{FONT['label']}pt;")
        recipe_row.addWidget(recipe_lbl)
        self._active_recipe_lbl = QLabel("(none)")
        self._active_recipe_lbl.setStyleSheet(
            f"color:{PALETTE['accent']}; font-size:{FONT['label']}pt; font-style:italic;")
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
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; "
            f"font-size:{FONT['body']}pt; font-family:{MONO_FONT};")
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
                f"QPushButton {{ background:{PALETTE['surface2']}; color:{PALETTE['accent']}; "
                f"border:1px solid {PALETTE['accent']}44; border-radius:10px; "
                f"font-size:{FONT['sublabel']}pt; padding:0 8px; }}"
                f"QPushButton:hover {{ background:{PALETTE['surface']}; }}")
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

        # RIGHT — results (hidden until acquisition starts)
        self._results_container = QWidget()
        right = QVBoxLayout(self._results_container)
        right.setSpacing(8)
        right.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._results_container, 2)

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
            scaled_qss(f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{PALETTE['textSub']};"))
        self._export_btn = QPushButton("Export")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._export_btn.setToolTip("Export acquisition results to a folder")
        self._export_btn.setEnabled(False)
        bot.addWidget(self._snr_lbl)
        bot.addStretch()
        bot.addWidget(self._export_btn)
        right.addLayout(bot)

        # Hide results panel until acquisition starts
        self._results_container.setVisible(False)

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
        bg  = P['bg']
        txt = P['text']
        bdr = P['border']
        if hasattr(self, "_notes_edit"):
            self._notes_edit.setStyleSheet(
                f"background:{bg}; color:{txt}; border:1px solid {bdr}; "
                f"font-size:{FONT['body']}pt; font-family:{MONO_FONT};")
        acc = P['accent']
        su2 = P['surface2']
        sur = P['surface']
        if hasattr(self, "_time_est_lbl"):
            self._time_est_lbl.setStyleSheet(
                f"color:{P['textDim']}; font-size:{FONT['caption']}pt;")
        for btn in getattr(self, "_chip_btns", []):
            btn.setStyleSheet(
                f"QPushButton {{ background:{su2}; color:{acc}; "
                f"border:1px solid {acc}44; border-radius:10px; "
                f"font-size:{FONT['sublabel']}pt; padding:0 8px; }}"
                f"QPushButton:hover {{ background:{sur}; }}")
        if hasattr(self, "_quick_controls"):
            self._quick_controls._apply_styles()
        if hasattr(self, "_hw_strip"):
            self._hw_strip._apply_styles()

    def set_workspace_mode(self, mode: str) -> None:
        """Control component visibility based on workspace mode."""
        if hasattr(self, "_hw_strip"):
            self._hw_strip.set_workspace_mode(mode)

    def set_active_recipe_name(self, name: str | None) -> None:
        """Called by MainWindow when a recipe is applied to reflect its name."""
        self._active_recipe_lbl.setText(name or "(none)")

    def _update_roi_status(self):
        count = self._roi_model.count
        if count == 0:
            self._roi_status.setText("No ROIs defined \u2014 full frame")
            self._roi_status.setStyleSheet(scaled_qss(
                f"font-family:{MONO_FONT}; font-size:8pt; "
                f"color:{PALETTE['textDim']};"))
        else:
            active = self._roi_model.active_roi
            lbl = active.label if active else ""
            self._roi_status.setText(
                f"{count} ROI(s) \u2022 Active: {lbl}")
            self._roi_status.setStyleSheet(scaled_qss(
                f"font-family:{MONO_FONT}; font-size:8pt; "
                f"color:{PALETTE['warning']};"))

    def _open_roi_tab(self):
        """Navigate to the ROI tab."""
        w = self.window()
        roi_tab = getattr(w, '_roi_tab', None)
        nav = getattr(w, '_nav', None)
        if roi_tab is not None and nav is not None:
            nav.navigate_to(roi_tab)

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
        return make_sub(text)

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
        # Push to detached viewer if open
        if hasattr(self, '_detached_viewer') and self._detached_viewer is not None:
            pix = self._live._lbl.pixmap()
            if pix is not None and not pix.isNull():
                cam = app_state.cam
                info = ""
                if cam is not None and hasattr(cam, "info"):
                    model = getattr(cam.info, "model", "") or "Camera"
                    w = getattr(cam.info, "width", 0)
                    h = getattr(cam.info, "height", 0)
                    info = f"{model}  ·  {w}×{h}  ·  Live"
                self._detached_viewer.update_image(
                    pix, info, data=frame.data)

    # ── Detached viewer ─────────────────────────────────────────────

    _detached_viewer = None

    def _on_detach_viewer(self) -> None:
        """Open (or bring to front) a detached large viewer window."""
        if self._detached_viewer is not None:
            self._detached_viewer.raise_()
            self._detached_viewer.activateWindow()
            return
        from ui.widgets.detached_viewer import DetachedViewer
        self._detached_viewer = DetachedViewer("Capture — Live Feed")
        self._detached_viewer.closed.connect(self._on_viewer_closed)
        self._detached_viewer.show()

        # Push current frame immediately if available
        pix = self._live._lbl.pixmap()
        if pix is not None and not pix.isNull():
            self._detached_viewer.update_image(pix, "")

    def _on_viewer_closed(self) -> None:
        """Clean up reference when the detached viewer is closed."""
        self._detached_viewer = None

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

    def _on_cmap_remote(self, cmap_name: str):
        """Another tab changed the colormap — sync our combo."""
        if self._cmap.currentText() != cmap_name:
            self._cmap.blockSignals(True)
            idx = self._cmap.findText(cmap_name)
            if idx >= 0:
                self._cmap.setCurrentIndex(idx)
                if self._result and self._result.delta_r_over_r is not None:
                    mode = "signed" if cmap_name in ("Thermal Delta", "signed") else "percentile"
                    self._drr_pane.show_array(self._result.delta_r_over_r, mode=mode, cmap=cmap_name)
            self._cmap.blockSignals(False)

    def _on_cmap_changed(self, cmap: str):
        cfg_mod.set_pref("display.colormap", cmap)
        from ui.app_signals import signals as _sig
        _sig.colormap_changed.emit(cmap)
        if self._result is not None and self._result.delta_r_over_r is not None:
            mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
            self._drr_pane.show_array(self._result.delta_r_over_r, mode=mode, cmap=cmap)

    def update_result(self, result):
        self._result = result
        self._results_container.setVisible(True)
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
        if busy:
            self._results_container.setVisible(True)

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

    def _snapshot_settings(self):
        """Save current settings before acquisition for undo."""
        self._prev_settings = {
            "frames": self._frames.value(),
            "delay": self._delay.value(),
        }
        self._restore_btn.setEnabled(True)

    def _restore_settings(self):
        """Restore settings from before the last acquisition."""
        if self._prev_settings is None:
            return
        self._frames.setValue(self._prev_settings["frames"])
        self._delay.setValue(self._prev_settings["delay"])
        self.log("Settings restored from previous run.")

    def _run(self):
        """Called by the Run button. Emits acquire_requested for readiness gate."""
        if app_state.pipeline is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self._snapshot_settings()
        self.acquire_requested.emit(self._frames.value(), self._delay.value())

    def _optimize_and_acquire(self):
        """Called by Optimize & Acquire button."""
        if app_state.pipeline is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self._snapshot_settings()
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
        self._refresh_camera_context()

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
        self._refresh_camera_context()

    def _refresh_camera_context(self) -> None:
        """Update the camera context strip below the live feed."""
        cam = app_state.cam
        cam_type = getattr(app_state, "active_camera_type", "tr")

        # Camera identity + resolution
        if cam is not None and hasattr(cam, "info"):
            model = getattr(cam.info, "model", "") or "Camera"
            w = getattr(cam.info, "width", 0)
            h = getattr(cam.info, "height", 0)
            parts = [model]
            if w and h:
                parts.append(f"{w} × {h}")
            self._cam_ctx_lbl.setText("  ·  ".join(parts))
        else:
            self._cam_ctx_lbl.setText("No camera connected")

        # Modality badge
        if cam_type == "ir":
            badge_text = "IR Lock-in"
            bg = PALETTE.get("warning", "#ff9f0a")
        else:
            badge_text = "TR"
            bg = PALETTE.get("accent", "#00d4aa")
        self._mode_badge.setText(badge_text)
        self._mode_badge.setStyleSheet(
            f"background: {bg}22; color: {bg}; "
            f"border: 1px solid {bg}44; border-radius: 9px; "
            f"font-size: {FONT['sublabel']}pt; font-weight: 600; "
            f"padding: 1px 8px;")
        self._mode_badge.setVisible(cam is not None)
