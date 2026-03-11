"""
acquisition_panel.py

Thermoreflectance acquisition control panel.

Shows:
  - Live camera feed (left)
  - Cold average, Hot average, ΔR/R result (right)
  - Capture controls with progress bar
  - Export button

Run:  python acquisition_panel.py
"""

import logging
import sys
import time
import threading
import numpy as np

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QProgressBar, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QComboBox, QTextEdit, QSplitter,
    QFileDialog, QFrame, QSizePolicy)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui   import QImage, QPixmap, QFont, QColor

import config
from hardware.cameras   import create_camera
from ui.theme import FONT, scaled_qss
from acquisition        import (AcquisitionPipeline, AcquisitionResult,
                                AcquisitionProgress, AcqState,
                                to_display, apply_colormap, export_result)


# ------------------------------------------------------------------ #
#  Signals (bridge background threads → Qt main thread)             #
# ------------------------------------------------------------------ #

class AcqSignals(QObject):
    progress  = pyqtSignal(object)   # AcquisitionProgress
    complete  = pyqtSignal(object)   # AcquisitionResult
    new_frame = pyqtSignal(object)   # CameraFrame
    error     = pyqtSignal(str)


signals = AcqSignals()


# ------------------------------------------------------------------ #
#  Image display widget                                              #
# ------------------------------------------------------------------ #

class ImagePane(QWidget):
    """Displays a numpy array with a title label underneath."""

    def __init__(self, title: str, w: int = 320, h: int = 240):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(w, h)
        self._img_lbl.setStyleSheet("background: #111; border: 1px solid #444;")
        self._img_lbl.setAlignment(Qt.AlignCenter)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(
            scaled_qss("font-size:9pt; color:#aaa; font-family:Consolas;"))

        self._stat_lbl = QLabel("--")
        self._stat_lbl.setAlignment(Qt.AlignCenter)
        self._stat_lbl.setStyleSheet(
            scaled_qss("font-size:8pt; color:#666; font-family:Consolas;"))

        layout.addWidget(self._img_lbl)
        layout.addWidget(self._title_lbl)
        layout.addWidget(self._stat_lbl)

    def show_frame(self, data: np.ndarray, mode: str = "auto",
                   cmap: str = "gray"):
        """Display a numpy array. data can be uint16 or float32."""
        if data is None:
            return

        disp = to_display(data, mode=mode)

        if cmap != "gray" and disp.ndim == 2:
            disp = apply_colormap(disp, cmap)

        if disp.ndim == 2:
            h, w  = disp.shape
            qimg  = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w  = disp.shape[:2]
            qimg  = QImage(disp.tobytes(), w, h, w * 3,
                           QImage.Format_RGB888)

        sz  = self._img_lbl.size()
        pix = QPixmap.fromImage(qimg).scaled(
            sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img_lbl.setPixmap(pix)

        # Stats
        self._stat_lbl.setText(
            f"min={data.min():.4g}  max={data.max():.4g}  "
            f"mean={data.mean():.4g}")

    def set_title(self, title: str):
        self._title_lbl.setText(title)

    def clear(self):
        self._img_lbl.clear()
        self._img_lbl.setStyleSheet("background: #111; border: 1px solid #444;")
        self._stat_lbl.setText("--")


# ------------------------------------------------------------------ #
#  Shared state                                                       #
# ------------------------------------------------------------------ #

cam      = None
pipeline = None
running  = True


def live_capture_loop():
    global cam, pipeline
    cfg = config.get("hardware").get("camera", {})
    try:
        cam = create_camera(cfg)
        cam.open()
        cam.start()
        pipeline = AcquisitionPipeline(cam)
        pipeline.on_progress = lambda p: signals.progress.emit(p)
        pipeline.on_complete = lambda r: signals.complete.emit(r)
        pipeline.on_error    = lambda e: signals.error.emit(e)
    except Exception as e:
        signals.error.emit(str(e))
        return

    log.info("Camera: %s | %s", cam.info.driver, cam.info.model)

    while running:
        if pipeline.state == AcqState.CAPTURING:
            time.sleep(0.05)
            continue
        frame = cam.grab(timeout_ms=500)
        if frame:
            signals.new_frame.emit(frame)


# ------------------------------------------------------------------ #
#  Main window                                                        #
# ------------------------------------------------------------------ #

class AcquisitionPanel(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Microsanj — Thermoreflectance Acquisition")
        self._result = None
        self._build_ui()
        signals.new_frame.connect(self._on_live_frame)
        signals.progress.connect(self._on_progress)
        signals.complete.connect(self._on_complete)
        signals.error.connect(self._on_error)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(8)

        # ---- LEFT: Live feed + controls ----
        left = QVBoxLayout()
        left.setSpacing(6)
        root.addLayout(left, stretch=1)

        # Live image
        live_box = QGroupBox("Live Camera Feed")
        live_layout = QVBoxLayout(live_box)
        self._live_pane = ImagePane("Live", 480, 360)
        live_layout.addWidget(self._live_pane)
        left.addWidget(live_box)

        # Acquisition controls
        ctrl_box = QGroupBox("Acquisition")
        ctrl_layout = QGridLayout(ctrl_box)

        ctrl_layout.addWidget(QLabel("Frames per phase:"), 0, 0)
        self._frames_spin = QSpinBox()
        self._frames_spin.setRange(1, 10000)
        self._frames_spin.setValue(100)
        self._frames_spin.setFixedWidth(100)
        ctrl_layout.addWidget(self._frames_spin, 0, 1)

        ctrl_layout.addWidget(QLabel("Delay between phases (s):"), 1, 0)
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0, 60)
        self._delay_spin.setValue(0.0)
        self._delay_spin.setSingleStep(0.5)
        self._delay_spin.setFixedWidth(100)
        ctrl_layout.addWidget(self._delay_spin, 1, 1)

        ctrl_layout.addWidget(QLabel("ΔR/R colormap:"), 2, 0)
        self._cmap_combo = QComboBox()
        for c in ["signed", "hot", "cool", "viridis", "gray"]:
            self._cmap_combo.addItem(c)
        self._cmap_combo.setFixedWidth(100)
        ctrl_layout.addWidget(self._cmap_combo, 2, 1)

        # Capture buttons
        btn_row = QHBoxLayout()
        self._cold_btn  = QPushButton("① Capture Cold")
        self._hot_btn   = QPushButton("② Capture Hot")
        self._run_btn   = QPushButton("▶  Run Full Sequence")
        self._abort_btn = QPushButton("■  Abort")
        self._abort_btn.setEnabled(False)

        self._cold_btn.setStyleSheet( "background:#004488; color:white; font-weight:bold;")
        self._hot_btn.setStyleSheet(  "background:#884400; color:white; font-weight:bold;")
        self._run_btn.setStyleSheet(  "background:#006600; color:white; font-weight:bold;")
        self._abort_btn.setStyleSheet("background:#660000; color:white;")

        self._cold_btn.clicked.connect(self._capture_cold)
        self._hot_btn.clicked.connect(self._capture_hot)
        self._run_btn.clicked.connect(self._run_sequence)
        self._abort_btn.clicked.connect(self._abort)

        btn_row.addWidget(self._cold_btn)
        btn_row.addWidget(self._hot_btn)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._abort_btn)
        ctrl_layout.addLayout(btn_row, 3, 0, 1, 2)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        ctrl_layout.addWidget(self._progress_bar, 4, 0, 1, 2)

        # Status log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        self._log.setStyleSheet(
            scaled_qss("background:#1a1a1a; color:#aaa; font-family:Consolas; font-size:9pt;"))
        ctrl_layout.addWidget(self._log, 5, 0, 1, 2)

        left.addWidget(ctrl_box)

        # ---- RIGHT: Result images ----
        right = QVBoxLayout()
        root.addLayout(right, stretch=1)

        results_box = QGroupBox("Results")
        results_layout = QGridLayout(results_box)

        self._cold_pane  = ImagePane("Cold Average (baseline)", 320, 240)
        self._hot_pane   = ImagePane("Hot Average (stimulus)",  320, 240)
        self._diff_pane  = ImagePane("Difference (hot − cold)", 320, 240)
        self._drr_pane   = ImagePane("ΔR/R (thermoreflectance)",320, 240)

        results_layout.addWidget(self._cold_pane, 0, 0)
        results_layout.addWidget(self._hot_pane,  0, 1)
        results_layout.addWidget(self._diff_pane, 1, 0)
        results_layout.addWidget(self._drr_pane,  1, 1)

        right.addWidget(results_box)

        # Export
        export_row = QHBoxLayout()
        self._export_btn = QPushButton("💾  Export Results")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export)
        self._snr_lbl = QLabel("SNR: --")
        self._snr_lbl.setStyleSheet(f"font-family:Consolas; font-size:{FONT['caption']}pt;")
        export_row.addWidget(self._snr_lbl)
        export_row.addStretch()
        export_row.addWidget(self._export_btn)
        right.addLayout(export_row)

    # ---------------------------------------------------------------- #
    #  Button handlers                                                  #
    # ---------------------------------------------------------------- #

    def _capture_cold(self):
        self._log_msg("Capturing cold frames...")
        self._set_capturing(True)
        def _run():
            result = pipeline.capture_reference(self._frames_spin.value())
            if result is not None:
                if self._result is None:
                    from acquisition.pipeline import AcquisitionResult
                    self._result = AcquisitionResult(
                        n_frames=self._frames_spin.value())
                self._result.cold_avg = result
                self._cold_pane.show_frame(result, mode="auto")
                self._log_msg(f"Cold captured: {result.shape}, "
                              f"mean={result.mean():.1f}")
            self._set_capturing(False)
        threading.Thread(target=_run, daemon=True).start()

    def _capture_hot(self):
        self._log_msg("Capturing hot frames...")
        self._set_capturing(True)
        def _run():
            result = pipeline.capture_reference(self._frames_spin.value())
            if result is not None:
                if self._result is None:
                    from acquisition.pipeline import AcquisitionResult
                    self._result = AcquisitionResult(
                        n_frames=self._frames_spin.value())
                self._result.hot_avg = result
                self._hot_pane.show_frame(result, mode="auto")
                self._log_msg(f"Hot captured: mean={result.mean():.1f}")
                # Compute if we have both
                if self._result.cold_avg is not None:
                    from acquisition.pipeline import AcquisitionPipeline
                    AcquisitionPipeline._compute(self._result)
                    self._show_results(self._result)
            self._set_capturing(False)
        threading.Thread(target=_run, daemon=True).start()

    def _run_sequence(self):
        self._log_msg("Starting full acquisition sequence...")
        self._set_capturing(True)
        pipeline.start(
            n_frames          = self._frames_spin.value(),
            inter_phase_delay = self._delay_spin.value())

    def _abort(self):
        if pipeline:
            pipeline.abort()
        self._log_msg("Aborting...")

    def _export(self):
        if not self._result or not self._result.is_complete:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Select Export Folder", ".")
        if directory:
            saved = export_result(self._result, directory)
            self._log_msg(f"Exported {len(saved)} files to {directory}")

    # ---------------------------------------------------------------- #
    #  Signal handlers                                                  #
    # ---------------------------------------------------------------- #

    def _on_live_frame(self, frame):
        self._live_pane.show_frame(frame.data, mode="auto")

    def _on_progress(self, p: AcquisitionProgress):
        self._log_msg(p.message)
        total = p.frames_total * 2 if p.phase in ("cold", "hot") else 0
        if p.phase == "cold":
            pct = int(p.fraction * 50)
        elif p.phase == "hot":
            pct = 50 + int(p.fraction * 50)
        elif p.state == AcqState.COMPLETE:
            pct = 100
        else:
            pct = self._progress_bar.value()
        self._progress_bar.setValue(pct)

        if p.state in (AcqState.COMPLETE, AcqState.ABORTED, AcqState.ERROR):
            self._set_capturing(False)

    def _on_complete(self, result: AcquisitionResult):
        self._result = result
        self._show_results(result)
        self._log_msg(
            f"✓ Complete in {result.duration_s:.1f}s  |  "
            f"SNR: {result.snr_db:.1f} dB" if result.snr_db else
            f"✓ Complete in {result.duration_s:.1f}s")
        self._export_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._log_msg(f"ERROR: {msg}")
        self._set_capturing(False)

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _show_results(self, result: AcquisitionResult):
        cmap = self._cmap_combo.currentText()
        if result.cold_avg is not None:
            self._cold_pane.show_frame(result.cold_avg, mode="auto")
        if result.hot_avg is not None:
            self._hot_pane.show_frame(result.hot_avg,  mode="auto")
        if result.difference is not None:
            self._diff_pane.show_frame(result.difference, mode="percentile")
        if result.delta_r_over_r is not None:
            mode = "signed" if cmap in ("Thermal Delta", "signed") else "percentile"
            self._drr_pane.show_frame(
                result.delta_r_over_r, mode=mode, cmap=cmap)
            if result.snr_db is not None:
                self._snr_lbl.setText(f"SNR: {result.snr_db:.1f} dB")

    def _log_msg(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}] {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())

    def _set_capturing(self, capturing: bool):
        self._cold_btn.setEnabled(not capturing)
        self._hot_btn.setEnabled(not capturing)
        self._run_btn.setEnabled(not capturing)
        self._abort_btn.setEnabled(capturing)

    def closeEvent(self, event):
        global running
        running = False
        if pipeline:
            pipeline.abort()
        if cam:
            cam.close()
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    threading.Thread(target=live_capture_loop, daemon=True).start()
    app    = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AcquisitionPanel()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
