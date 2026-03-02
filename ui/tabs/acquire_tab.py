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
    QGroupBox, QComboBox, QTextEdit, QFileDialog)

from hardware.app_state import app_state
from acquisition        import AcquisitionProgress, AcqState
from acquisition        import export_result
from ui.widgets.image_pane import ImagePane


class AcquireTab(QWidget):
    def __init__(self):
        super().__init__()
        self._result = None
        root = QHBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # LEFT
        left = QVBoxLayout()
        left.setSpacing(8)
        root.addLayout(left, 2)
        self._left_layout = left   # exposed for ReadinessWidget injection

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

        from ui.help import help_label
        cl.addWidget(help_label("Frames / phase", "n_frames"), 0, 0)
        self._frames = QSpinBox()
        self._frames.setRange(1, 10000)
        self._frames.setValue(100)
        self._frames.setSuffix(" frames")
        self._frames.setFixedWidth(130)
        cl.addWidget(self._frames, 0, 1)

        cl.addWidget(self._sub("Phase delay (s)"), 1, 0)
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0, 60)
        self._delay.setValue(0)
        self._delay.setSingleStep(0.5)
        self._delay.setSuffix(" s")
        self._delay.setFixedWidth(90)
        self._delay.setToolTip(
            "Wait time between switching from cold to hot (or vice versa).\n"
            "Allows the device to reach thermal equilibrium after the stimulus changes.\n"
            "Set to 0 for rapid alternating measurements.")
        cl.addWidget(self._delay, 1, 1)

        cl.addWidget(self._sub("ΔR/R colormap"), 2, 0)
        self._cmap = QComboBox()
        for c in ["signed", "hot", "cool", "viridis", "gray"]:
            self._cmap.addItem(c)
        self._cmap.setFixedWidth(90)
        cl.addWidget(self._cmap, 2, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self._cold_btn = QPushButton("① COLD")
        self._cold_btn.setObjectName("cold_btn")
        self._cold_btn.setToolTip(
            "Capture cold (baseline) frames only.\n"
            "Use this when you want to set up the cold reference manually "
            "before applying the stimulus.")
        self._hot_btn  = QPushButton("② HOT")
        self._hot_btn.setObjectName("hot_btn")
        self._hot_btn.setToolTip(
            "Capture hot (stimulus) frames and compute ΔR/R immediately.\n"
            "Requires a cold reference to already be captured.")
        self._run_btn  = QPushButton("▶  RUN SEQUENCE")
        self._run_btn.setObjectName("primary")
        self._run_btn.setToolTip(
            "Run the full cold → hot acquisition sequence automatically.\n"
            "Captures cold baseline, applies stimulus, captures hot frames, "
            "then computes ΔR/R and ΔT.\n\n"
            "Keyboard shortcut: Ctrl+R")
        self._abort_btn = QPushButton("■  ABORT")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setToolTip(
            "Abort the current acquisition immediately.\n"
            "Any frames already captured will be discarded.\n\n"
            "Keyboard shortcut: Escape")
        self._abort_btn.setEnabled(False)
        for b in [self._cold_btn, self._hot_btn,
                  self._run_btn, self._abort_btn]:
            btn_row.addWidget(b)
        cl.addLayout(btn_row, 3, 0, 1, 2)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        cl.addWidget(self._progress, 4, 0, 1, 2)

        left.addWidget(ctrl_box)

        # Log
        log_box = QGroupBox("Log")
        logl = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(80)
        self._log.setMaximumHeight(140)
        logl.addWidget(self._log)
        left.addWidget(log_box)

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
            "background:#161616; color:#bbb; border:1px solid #2a2a2a; "
            "font-size:13pt; font-family:Menlo,monospace;")
        nl.addWidget(self._notes_edit)

        # Quick-insert chips for common tags
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        chips_lbl = QLabel("Quick tags:")
        chips_lbl.setObjectName("sublabel")
        chips_row.addWidget(chips_lbl)
        for chip_text in ["25°C", "dark room", "no bias", "after reflow",
                           "calibrated", "reference sample"]:
            btn = QPushButton(chip_text)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                "QPushButton { background:#1e2a28; color:#00d4aa; "
                "border:1px solid #00d4aa44; border-radius:10px; "
                "font-size:11pt; padding:0 8px; }"
                "QPushButton:hover { background:#254d42; }")
            btn.clicked.connect(
                lambda _, t=chip_text: self._insert_notes_chip(t))
            chips_row.addWidget(btn)
        chips_row.addStretch()
        nl.addLayout(chips_row)
        left.addWidget(notes_box)

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
            "font-family:Menlo,monospace; font-size:15pt; color:#555;")
        self._export_btn = QPushButton("💾  Export")
        self._export_btn.setEnabled(False)
        bot.addWidget(self._snr_lbl)
        bot.addStretch()
        bot.addWidget(self._export_btn)
        right.addLayout(bot)

        # Wire buttons
        self._cold_btn.clicked.connect(self._cap_cold)
        self._hot_btn.clicked.connect(self._cap_hot)
        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)
        self._export_btn.clicked.connect(self._export)

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
            mode = "signed" if cmap == "signed" else "percentile"
            self._drr_pane.show_array(result.delta_r_over_r, mode=mode, cmap=cmap)
        # Show ΔT map if calibration was applied
        dt = getattr(result, "delta_t", None)
        if dt is not None:
            self._dt_pane.show_array(dt, mode="signed", cmap="signed")
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
        self.log("Capturing cold frames...")
        def _run():
            pl = app_state.pipeline
            if pl is None:
                self.log("No acquisition pipeline — is hardware connected?")
                self._set_busy(False)
                return
            r = pl.capture_reference(self._frames.value())
            if r is not None:
                if self._result is None:
                    from acquisition.pipeline import AcquisitionResult
                    self._result = AcquisitionResult(n_frames=self._frames.value())
                self._result.cold_avg = r
                self._cold_pane.show_array(r)
                self.log(f"Cold: mean={r.mean():.1f}")
            self._set_busy(False)
        threading.Thread(target=_run, daemon=True).start()

    def _cap_hot(self):
        self._set_busy(True)
        self.log("Capturing hot frames...")
        def _run():
            pl = app_state.pipeline
            if pl is None:
                self.log("No acquisition pipeline — is hardware connected?")
                self._set_busy(False)
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
            self._set_busy(False)
        threading.Thread(target=_run, daemon=True).start()

    def _run(self):
        pl = app_state.pipeline
        if pl is None:
            self.log("No acquisition pipeline — is hardware connected?")
            return
        self._set_busy(True)
        self._progress.setValue(0)
        self.log("Starting acquisition sequence...")
        pl.start(n_frames=self._frames.value(),
                 inter_phase_delay=self._delay.value())

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
