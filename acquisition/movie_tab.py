"""
acquisition/movie_tab.py

MovieTab — UI for high-speed burst (movie-mode) thermoreflectance acquisition.

Movie mode captures N frames as fast as possible after bias power turns ON,
producing a 3D frame cube (N × H × W) that reveals the thermal transient
video of the DUT heating up.  Unlike live lock-in mode (which requires
FPGA synchronisation), movie mode works with any camera and bias source.

Layout
------
Toolbar     : Run / Abort / Save buttons + status badge
Left panel  : Capture settings + hardware readiness + run controls
Right panel : Progress bar + status log + result image (max ΔR/R projection)
"""

from __future__ import annotations

import os
import time
import numpy as np
from typing import Optional

from ui.button_utils import RunningButton, apply_hand_cursor
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QCheckBox, QComboBox, QSplitter, QSizePolicy, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui  import QImage, QPixmap, QColor, QFont

from .movie_pipeline import (
    MovieAcquisitionPipeline, MovieAcqState, MovieProgress, MovieResult)
from .processing import to_display, apply_colormap, COLORMAP_OPTIONS, COLORMAP_TOOLTIPS, setup_cmap_combo
from ai.instrument_knowledge import (
    MOVIE_DEFAULT_N_FRAMES, MOVIE_DEFAULT_SETTLE_MS,
    MOVIE_MIN_N_FRAMES, MOVIE_MAX_N_FRAMES)
import config as cfg_mod


# ------------------------------------------------------------------ #
#  Image rendering helper                                             #
# ------------------------------------------------------------------ #

def _array_to_pixmap(data: np.ndarray, cmap: str = "Thermal Delta") -> Optional[QPixmap]:
    """Convert float32 2D array to a QPixmap using the given colourmap."""
    try:
        d = data.astype(np.float32)
        if cmap in ("Thermal Delta", "signed"):
            finite = d[np.isfinite(d)]
            limit  = float(np.percentile(np.abs(finite), 99.5)) if finite.size else 1e-9
            limit  = limit or 1e-9
            normed = np.clip(d / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            rgb = np.stack([r, g, b], axis=-1)
        else:
            gray = to_display(d, mode="percentile")
            rgb  = apply_colormap(gray, cmap)
        h, w = rgb.shape[:2]
        buf = rgb.tobytes()
        qi = QImage(buf, w, h, w * 3, QImage.Format_RGB888)
        return QPixmap.fromImage(qi)
    except Exception:
        return None


# ------------------------------------------------------------------ #
#  MovieTab                                                           #
# ------------------------------------------------------------------ #

class MovieTab(QWidget):
    """
    UI tab for movie-mode burst acquisition.

    Wires up MovieAcquisitionPipeline, shows live progress, and displays
    the max-ΔR/R projection after the run completes.
    """

    def __init__(self):
        super().__init__()
        self._pipeline: Optional[MovieAcquisitionPipeline] = None
        self._result:   Optional[MovieResult] = None
        self._last_progress: Optional[MovieProgress] = None

        # Poll timer — reads last progress and refreshes UI (20 Hz)
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([260, 700])
        root.addWidget(splitter, 1)

    # ---------------------------------------------------------------- #
    #  Left panel — settings + controls                                #
    # ---------------------------------------------------------------- #

    def _build_left(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(230)
        w.setMaximumWidth(290)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        # ── Capture settings ──────────────────────────────────────────
        cap_box = QGroupBox("Capture Settings")
        cl = QGridLayout(cap_box)
        cl.setSpacing(6)

        self._n_frames = QSpinBox()
        self._n_frames.setRange(MOVIE_MIN_N_FRAMES, MOVIE_MAX_N_FRAMES)
        self._n_frames.setValue(MOVIE_DEFAULT_N_FRAMES)
        self._n_frames.setSuffix(" frames")
        self._n_frames.setFixedWidth(110)
        self._n_frames.setToolTip(
            f"Number of frames to capture in burst.\n"
            f"Range: {MOVIE_MIN_N_FRAMES}–{MOVIE_MAX_N_FRAMES} frames.")

        self._settle_ms = QDoubleSpinBox()
        self._settle_ms.setRange(0.0, 2000.0)
        self._settle_ms.setValue(MOVIE_DEFAULT_SETTLE_MS)
        self._settle_ms.setSuffix(" ms")
        self._settle_ms.setFixedWidth(110)
        self._settle_ms.setToolTip(
            "Wait time after bias power ON before burst capture begins.\n"
            "Allows the DUT to reach a representative initial temperature.")

        self._capture_ref = QCheckBox("Capture cold reference")
        self._capture_ref.setChecked(True)
        self._capture_ref.setToolTip(
            "Capture a bias-off reference frame before the burst.\n"
            "Required to compute ΔR/R = (frame − ref) / ref.")

        self._drift_cb = QCheckBox("Use drift correction (image shift)")
        self._drift_cb.setChecked(False)
        self._drift_cb.setToolTip(
            "Apply FFT phase-correlation drift correction to each burst frame\n"
            "before accumulating.  Compensates for slow sample drift between\n"
            "the reference and hot captures.\n"
            "Equivalent to 'Use Image Shift' in the LabVIEW interface.\n"
            "Note: adds ~1 ms per frame; disable for maximum throughput.")

        cl.addWidget(self._sub("N frames"),  0, 0)
        cl.addWidget(self._n_frames,         0, 1)
        cl.addWidget(self._sub("Settle"),    1, 0)
        cl.addWidget(self._settle_ms,        1, 1)
        cl.addWidget(self._capture_ref,      2, 0, 1, 2)
        cl.addWidget(self._drift_cb,         3, 0, 1, 2)
        lay.addWidget(cap_box)

        # ── Hardware status ───────────────────────────────────────────
        hw_box = QGroupBox("Hardware")
        hl = QGridLayout(hw_box)
        hl.setSpacing(4)
        self._hw_cam_lbl  = QLabel("—")
        self._hw_bias_lbl = QLabel("—")
        self._hw_fpga_lbl = QLabel("—")
        for l in [self._hw_cam_lbl, self._hw_bias_lbl, self._hw_fpga_lbl]:
            l.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['textDim']};")
        hl.addWidget(self._sub("Camera"),  0, 0)
        hl.addWidget(self._hw_cam_lbl,     0, 1)
        hl.addWidget(self._sub("Bias"),    1, 0)
        hl.addWidget(self._hw_bias_lbl,    1, 1)
        hl.addWidget(self._sub("FPGA"),    2, 0)
        hl.addWidget(self._hw_fpga_lbl,    2, 1)
        lay.addWidget(hw_box)

        # ── Run controls ──────────────────────────────────────────────
        run_box = QGroupBox("Run")
        rl = QVBoxLayout(run_box)

        self._run_btn   = QPushButton("Run Movie")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(34)
        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", "#ff6666")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setFixedHeight(32)
        self._abort_btn.setEnabled(False)

        self._btn_runner = RunningButton(self._run_btn, idle_text="▶  Run Movie")
        apply_hand_cursor(self._abort_btn)
        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']};")
        self._status_lbl.setWordWrap(True)

        rl.addWidget(self._run_btn)
        rl.addWidget(self._abort_btn)
        rl.addWidget(self._progress)
        rl.addWidget(self._status_lbl)
        lay.addWidget(run_box)

        # ── Save ──────────────────────────────────────────────────────
        self._save_btn = QPushButton("Save Cube…")
        set_btn_icon(self._save_btn, "fa5s.save")
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedHeight(30)
        self._save_btn.clicked.connect(self._save)
        lay.addWidget(self._save_btn)

        lay.addStretch()
        self._refresh_hw()
        return w

    # ---------------------------------------------------------------- #
    #  Right panel — result display                                    #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # ── Result stats ──────────────────────────────────────────────
        stats_box = QGroupBox("Result")
        sl = QHBoxLayout(stats_box)
        self._stats: dict = {}
        for key, label in [
            ("frames", "Frames"),
            ("fps",    "fps"),
            ("dur",    "Duration"),
            ("min_drr","Min ΔR/R"),
            ("max_drr","Max ΔR/R"),
        ]:
            w2 = QWidget()
            v  = QVBoxLayout(w2)
            v.setAlignment(Qt.AlignCenter)
            sub = QLabel(label)
            sub.setObjectName("sublabel")
            sub.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt; "
                f"color:{PALETTE['accent']};")
            v.addWidget(sub)
            v.addWidget(val)
            sl.addWidget(w2)
            self._stats[key] = val
        lay.addWidget(stats_box)

        # ── Image display (max ΔR/R projection) ───────────────────────
        img_box = QGroupBox("Max ΔR/R Projection  (max over time axis)")
        il = QVBoxLayout(img_box)

        # Colormap selector row
        cmap_row = QHBoxLayout()
        cmap_row.addWidget(QLabel("Colourmap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setFixedWidth(130)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        self._cmap_combo.currentTextChanged.connect(self._redisplay)
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        cmap_row.addWidget(self._cmap_combo)
        cmap_row.addStretch()
        il.addLayout(cmap_row)

        self._img_lbl = QLabel()
        self._img_lbl.setMinimumSize(400, 300)
        self._img_lbl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img_lbl.setStyleSheet(
            f"background:#0d0d0d; border:1px solid {PALETTE['border']};")
        self._img_lbl.setAlignment(Qt.AlignCenter)
        _dim  = PALETTE['textDim']
        _body = FONT['body']
        self._img_lbl.setText(
            f"<span style='color:{_dim};font-size:{_body}pt'>"
            f"Run Movie to capture</span>")
        il.addWidget(self._img_lbl)
        lay.addWidget(img_box, 1)

        return w

    # ---------------------------------------------------------------- #
    #  Run / Abort                                                      #
    # ---------------------------------------------------------------- #

    def _run(self):
        from hardware.app_state import app_state
        cam  = app_state.cam
        fpga = app_state.fpga
        bias = app_state.bias

        if cam is None:
            QMessageBox.warning(self, "Movie", "Camera not connected.")
            return

        self._pipeline = MovieAcquisitionPipeline(cam, fpga=fpga, bias=bias)

        # Route callbacks through app_signals to stay on GUI thread
        try:
            from ui.app_signals import signals
            self._pipeline.on_progress = lambda p: signals.movie_progress.emit(p)
            self._pipeline.on_complete = lambda r: signals.movie_complete.emit(r)
            self._pipeline.on_error    = lambda e: signals.error.emit(e)
            # Disconnect any stale connections from a previous run to prevent
            # the slot firing N times on the Nth successive run call.
            try:
                signals.movie_progress.disconnect(self._on_progress)
                signals.movie_complete.disconnect(self._on_complete)
            except Exception:
                pass
            signals.movie_progress.connect(self._on_progress)
            signals.movie_complete.connect(self._on_complete)
        except Exception:
            # Fallback: store and poll
            self._pipeline.on_progress = lambda p: setattr(self, '_last_progress', p)
            self._pipeline.on_complete = self._on_complete

        self._pipeline.start(
            n_frames         = self._n_frames.value(),
            capture_reference= self._capture_ref.isChecked(),
            settle_s         = self._settle_ms.value() / 1000.0,
            drift_correction = self._drift_cb.isChecked(),
        )

        self._timer.start()
        self._btn_runner.set_running(True, "Recording")
        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._save_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status_lbl.setText("Starting…")

        # Update app_state modality
        try:
            from hardware.app_state import app_state
            app_state.active_modality = "movie"
        except Exception:
            pass

    def _abort(self):
        if self._pipeline:
            self._pipeline.abort()
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._status_lbl.setText("Aborted")
        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Poll + callbacks                                                 #
    # ---------------------------------------------------------------- #

    def _poll(self):
        """Called by QTimer; checks pipeline state and updates status."""
        if self._pipeline is None:
            return
        state = self._pipeline.state

        # If the pipeline is no longer running, stop polling
        if state in (MovieAcqState.COMPLETE,
                     MovieAcqState.ABORTED,
                     MovieAcqState.ERROR):
            self._timer.stop()

        # Update status from stored progress if signals not connected
        p = self._last_progress
        if p is not None:
            self._last_progress = None
            self._on_progress(p)

    def _on_progress(self, p: MovieProgress):
        """Update progress bar and status label (called on GUI thread)."""
        pct = int(p.fraction * 100)
        self._progress.setValue(pct)
        self._status_lbl.setText(p.message)

    def _on_complete(self, result: MovieResult):
        """Called on GUI thread when acquisition finishes."""
        self._result = result
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setValue(100)
        self._save_btn.setEnabled(True)

        self._status_lbl.setText(
            f"Complete — {result.n_frames} frames @ {result.fps_achieved:.1f} fps")

        # Update stats
        self._stats["frames"].setText(str(result.n_frames))
        self._stats["fps"].setText(f"{result.fps_achieved:.1f}")
        dur = getattr(result, 'duration_s', 0.0) or 0.0
        self._stats["dur"].setText(f"{dur:.2f} s")

        # Display max ΔR/R projection
        if result.delta_r_cube is not None:
            cube = result.delta_r_cube
            valid = cube[np.isfinite(cube)]
            if valid.size > 0:
                self._stats["min_drr"].setText(f"{float(valid.min()):.3e}")
                self._stats["max_drr"].setText(f"{float(valid.max()):.3e}")
            self._redisplay()
        elif result.frame_cube is not None:
            # No reference → show last raw frame
            last = result.frame_cube[-1].astype(np.float32)
            pct_lo = float(np.percentile(last, 1))
            pct_hi = float(np.percentile(last, 99))
            if pct_hi > pct_lo:
                norm = ((last - pct_lo) / (pct_hi - pct_lo) * 255).clip(0, 255).astype(np.uint8)
                qi = QImage(norm.tobytes(), norm.shape[1], norm.shape[0],
                            norm.shape[1], QImage.Format_Grayscale8)
                self._img_lbl.setPixmap(
                    QPixmap.fromImage(qi).scaled(
                        self._img_lbl.size(),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation))

        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            pass

    def _redisplay(self):
        """Re-render the max-projection with the currently selected colormap."""
        if self._result is None or self._result.delta_r_cube is None:
            return
        max_proj = np.nanmax(self._result.delta_r_cube, axis=0)
        px = _array_to_pixmap(max_proj, self._cmap_combo.currentText())
        if px is not None:
            self._img_lbl.setPixmap(
                px.scaled(self._img_lbl.size(),
                          Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---------------------------------------------------------------- #
    #  Save                                                             #
    # ---------------------------------------------------------------- #

    def _save(self):
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Movie Cube",
            f"movie_{int(time.time())}.npz",
            "NumPy archives (*.npz);;All files (*)")
        if not path:
            return
        try:
            save_kw: dict = {}
            if self._result.frame_cube is not None:
                save_kw["frame_cube"] = self._result.frame_cube
            if self._result.delta_r_cube is not None:
                save_kw["delta_r_cube"] = self._result.delta_r_cube
            if self._result.timestamps_s is not None:
                save_kw["timestamps_s"] = self._result.timestamps_s
            if self._result.reference is not None:
                save_kw["reference"] = self._result.reference
            np.savez_compressed(path, **save_kw)
            QMessageBox.information(self, "Saved",
                                    f"Movie cube saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    # ---------------------------------------------------------------- #
    #  Hardware readiness refresh                                      #
    # ---------------------------------------------------------------- #

    def _refresh_hw(self):
        try:
            from hardware.app_state import app_state
            ok  = f"color:{PALETTE['success']};"
            dim = f"color:{PALETTE['textDim']};"
            self._hw_cam_lbl.setText("Connected" if app_state.cam  else "—")
            self._hw_cam_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
                + (ok if app_state.cam else dim))
            self._hw_bias_lbl.setText("Connected" if app_state.bias else "—")
            self._hw_bias_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
                + (ok if app_state.bias else dim))
            self._hw_fpga_lbl.setText("Connected" if app_state.fpga else "—")
            self._hw_fpga_lbl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['caption']}pt; "
                + (ok if app_state.fpga else dim))
        except Exception:
            pass

    def showEvent(self, e):
        self._refresh_hw()
        super().showEvent(e)

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
