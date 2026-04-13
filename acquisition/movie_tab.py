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
from ui.theme import FONT, PALETTE, MONO_FONT

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QCheckBox, QComboBox, QSplitter, QSizePolicy, QFileDialog, QMessageBox,
    QScrollArea, QSlider,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui  import (QImage, QPixmap, QColor, QFont, QPen, QPainter,
                          QPolygonF, QPainterPath)

from .movie_pipeline import (
    MovieAcquisitionPipeline, MovieAcqState, MovieProgress, MovieResult)
from .movie_metrics import (
    compute_movie_metrics, compute_all_movie_roi_metrics, MovieMetrics)
from .roi_extraction import extract_roi_signals as _extract_roi_signals_shared
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
        self._loaded_session_label: str                   = ""
        self._last_progress: Optional[MovieProgress] = None

        # Poll timer — reads last progress and refreshes UI (20 Hz)
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setWidget(self._build_left())
        splitter.addWidget(left_scroll)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setWidget(self._build_right())
        splitter.addWidget(right_scroll)
        splitter.setSizes([260, 700])
        root.addWidget(splitter, 1)

        # Re-extract ROI curves when ROIs change
        try:
            from acquisition.roi_model import roi_model
            roi_model.rois_changed.connect(self._invalidate_roi_mask_cache)
            roi_model.rois_changed.connect(self._update_roi_curves)
        except Exception:
            pass

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
        cl.setColumnStretch(1, 1)

        self._n_frames = QSpinBox()
        self._n_frames.setRange(MOVIE_MIN_N_FRAMES, MOVIE_MAX_N_FRAMES)
        self._n_frames.setValue(MOVIE_DEFAULT_N_FRAMES)
        self._n_frames.setSuffix(" frames")
        self._n_frames.setMinimumWidth(80)
        self._n_frames.setToolTip(
            f"Number of frames to capture in burst.\n"
            f"Range: {MOVIE_MIN_N_FRAMES}–{MOVIE_MAX_N_FRAMES} frames.")

        self._settle_ms = QDoubleSpinBox()
        self._settle_ms.setRange(0.0, 2000.0)
        self._settle_ms.setValue(MOVIE_DEFAULT_SETTLE_MS)
        self._settle_ms.setSuffix(" ms")
        self._settle_ms.setMinimumWidth(80)
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
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
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
        set_btn_icon(self._run_btn, "fa5s.play", PALETTE['accent'])
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(34)
        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", PALETTE['danger'])
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
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
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

        self._export_video_btn = QPushButton("Export Video…")
        set_btn_icon(self._export_video_btn, "mdi.filmstrip")
        self._export_video_btn.setEnabled(False)
        self._export_video_btn.setFixedHeight(30)
        self._export_video_btn.clicked.connect(self._export_video)
        lay.addWidget(self._export_video_btn)

        lay.addStretch()
        self._refresh_hw()
        return w

    # ---------------------------------------------------------------- #
    #  Right panel — result display                                    #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        """Right panel — viewer-first layout.

        Hierarchy (top to bottom):
          1. Compact result strip (single line)
          2. View mode + colormap controls
          3. Frame viewer (stretch=3, dominates)
          4. Frame slider (directly below viewer)
          5. Signal chart (stretch=1, capped height)
          6. ROI Metrics (collapsed by default)
          7. Save Analysis button
        """
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 6, 8, 8)
        lay.setSpacing(4)

        # ── Compact result strip (single line) ────────────────────────
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(12)
        self._stats: dict = {}
        for key, label in [
            ("frames", "Frames"),
            ("fps",    "fps"),
            ("dur",    "Duration"),
            ("min_drr", "Min ΔR/R"),
            ("max_drr", "Max ΔR/R"),
        ]:
            sub = QLabel(f"{label}:")
            sub.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")
            val = QLabel("—")
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['accent']};")
            strip.addWidget(sub)
            strip.addWidget(val)
            self._stats[key] = val
        strip.addStretch()
        lay.addLayout(strip)
        lay.addSpacing(2)

        # ── View mode + colormap row ──────────────────────────────────
        view_row = QHBoxLayout()
        from ui.widgets.segmented_control import SegmentedControl
        self._view_seg = SegmentedControl(["Thermal", "Merge"], seg_width=72, height=24)
        self._view_seg.selection_changed.connect(self._on_view_mode)
        view_row.addWidget(self._view_seg)
        view_row.addSpacing(12)

        view_row.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        self._cmap_combo.currentTextChanged.connect(
            lambda _: self._show_frame(self._frame_slider.value()))
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        view_row.addWidget(self._cmap_combo)
        view_row.addStretch()

        lay.addLayout(view_row)

        # ── Frame viewer (dominant — stretch=3) ───────────────────────
        from ui.widgets.overlay_compositor import OverlayCompositor
        from ui.widgets.detach_helpers import DetachableFrame
        self._compositor = OverlayCompositor()
        self._compositor.setMinimumSize(400, 300)
        self._compositor.add_overlay("rois", self._paint_rois, label="ROIs")
        self._compositor_frame = DetachableFrame(self._compositor)
        self._compositor_frame.detach_requested.connect(self._on_detach_viewer)
        lay.addWidget(self._compositor_frame, 3)

        # ── Frame slider (directly below viewer) ─────────────────────
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Frame:"))
        self._frame_slider = QSlider(Qt.Horizontal)
        self._frame_slider.setRange(0, 0)
        self._frame_slider.setValue(0)
        self._frame_slider.setEnabled(False)
        self._frame_slider.valueChanged.connect(self._on_slider_changed)
        self._frame_time_lbl = QLabel("—")
        self._frame_time_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']}; min-width:70px;")
        slider_row.addWidget(self._frame_slider, 1)
        slider_row.addWidget(self._frame_time_lbl)
        lay.addLayout(slider_row)

        # ── Signal chart (secondary — stretch=1, capped) ──────────────
        curve_box = QGroupBox("Signal vs Time")
        curve_box.setMaximumHeight(200)
        cl = QVBoxLayout(curve_box)
        from ui.charts import TransientTraceChart
        self._curve = TransientTraceChart()
        self._curve.cursor_moved.connect(self._on_chart_cursor)
        cl.addWidget(self._curve)
        lay.addWidget(curve_box, 1)

        # ── ROI Metrics (collapsed by default) ────────────────────────
        from ui.widgets.collapsible_panel import CollapsiblePanel
        self._metrics_panel = CollapsiblePanel(
            "ROI Metrics", start_collapsed=True)

        self._metrics_table = QTableWidget(0, 7)
        self._metrics_table.setHorizontalHeaderLabels([
            "ROI", "Peak ΔR/R", "Peak |ΔR/R|", "Peak time",
            "Peak frame", "Mean ΔR/R", "Temporal σ",
        ])
        self._metrics_table.horizontalHeader().setStretchLastSection(True)
        self._metrics_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self._metrics_table.verticalHeader().setVisible(False)
        self._metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._metrics_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._metrics_table.setMaximumHeight(160)
        self._metrics_table.setStyleSheet(
            f"QTableWidget {{ font-family:{MONO_FONT}; "
            f"font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['bg']}; color:{PALETTE['text']}; }}"
            f"QHeaderView::section {{ font-size:{FONT['caption']}pt; "
            f"background:{PALETTE['surface']}; color:{PALETTE['textSub']}; "
            f"padding:2px 4px; }}")
        self._metrics_panel.addWidget(self._metrics_table)
        lay.addWidget(self._metrics_panel)

        # Cache for computed metrics
        self._current_metrics: list[MovieMetrics] = []
        self._ff_metrics: Optional[MovieMetrics] = None

        # ── Save Analysis ─────────────────────────────────────────────
        save_row = QHBoxLayout()
        self._save_analysis_btn = QPushButton("Save Analysis…")
        set_btn_icon(self._save_analysis_btn, "fa5s.file-export")
        self._save_analysis_btn.setEnabled(False)
        self._save_analysis_btn.setFixedHeight(28)
        self._save_analysis_btn.clicked.connect(self._save_analysis)
        save_row.addWidget(self._save_analysis_btn)
        save_row.addStretch()
        lay.addLayout(save_row)

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
        self._export_video_btn.setEnabled(False)
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
        self._loaded_session_label = ""   # clear any "loaded from" indicator
        self._timer.stop()
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setValue(100)
        self._save_btn.setEnabled(True)
        self._export_video_btn.setEnabled(True)

        self._status_lbl.setText(
            f"Complete — {result.n_frames} frames @ {result.fps_achieved:.1f} fps")

        self._display_result(result)

        try:
            from hardware.app_state import app_state
            app_state.active_modality = "thermoreflectance"
        except Exception:
            pass

    def _display_result(self, result: MovieResult):
        """Populate all display widgets from a MovieResult.

        Shared by live acquisition (_on_complete) and session reload
        (load_session).  Does NOT touch run/abort button state —
        callers handle those concerns separately.
        """
        # Stats
        self._stats["frames"].setText(str(result.n_frames))
        self._stats["fps"].setText(f"{result.fps_achieved:.1f}")
        dur = getattr(result, 'duration_s', 0.0) or 0.0
        self._stats["dur"].setText(f"{dur:.2f} s")

        # Determine display cube (prefer ΔR/R, fall back to raw frames)
        cube = result.delta_r_cube
        if cube is None:
            cube = result.frame_cube
        if cube is not None:
            if result.delta_r_cube is not None:
                valid = result.delta_r_cube[np.isfinite(result.delta_r_cube)]
                if valid.size > 0:
                    self._stats["min_drr"].setText(f"{float(valid.min()):.3e}")
                    self._stats["max_drr"].setText(f"{float(valid.max()):.3e}")

            n = cube.shape[0]
            self._frame_slider.setRange(0, max(n - 1, 0))
            self._frame_slider.setValue(0)
            self._frame_slider.setEnabled(True)

            # Build time axis and mean signal curve
            times = result.timestamps_s
            if times is None:
                times = np.arange(n, dtype=np.float64)
            means = np.nanmean(cube.reshape(n, -1), axis=1)
            self._curve.update_data(means, times, 0)
            self._update_roi_curves(full_frame_signal=means)
            self._show_frame(0)

    def load_session(self, session) -> None:
        """Populate the tab from a stored movie Session.

        Reconstructs a MovieResult from the session's lazy-loaded arrays
        and cube_params metadata, then displays it.  The tab shows a
        "Loaded from: <label>" indicator to distinguish reloaded data
        from a live acquisition.

        Parameters
        ----------
        session
            A ``Session`` object with ``result_type == "movie"``
            and cube arrays available via lazy-load properties.
        """
        cp = getattr(session.meta, "cube_params", None) or {}
        result = MovieResult(
            delta_r_cube    = session.delta_r_cube,
            frame_cube      = None,   # raw frames not persisted
            reference       = session.reference,
            timestamps_s    = session.timestamps_s,
            n_frames        = cp.get("n_frames", 0),
            frames_captured = cp.get("frames_captured", 0),
            exposure_us     = session.meta.exposure_us,
            gain_db         = session.meta.gain_db,
            duration_s      = session.meta.duration_s,
            fps_achieved    = cp.get("fps_achieved", 0.0),
        )
        self._result = result
        label = getattr(session.meta, "label", session.meta.uid) or session.meta.uid
        self._loaded_session_label = label

        # UI state for a loaded session (not a live acquisition)
        self._save_btn.setEnabled(True)
        self._export_video_btn.setEnabled(result.delta_r_cube is not None)
        self._status_lbl.setText(
            f"Loaded from session: {label}  —  "
            f"{result.n_frames} frames @ {result.fps_achieved:.1f} fps")

        self._display_result(result)

    # ---------------------------------------------------------------- #
    #  Frame navigation                                                 #
    # ---------------------------------------------------------------- #

    def _on_slider_changed(self, idx: int):
        if self._result is None:
            return
        cube = self._result.delta_r_cube
        if cube is None:
            cube = self._result.frame_cube
        if cube is None:
            return

        times = self._result.timestamps_s
        if times is not None and idx < len(times):
            t_ms = times[idx] * 1e3
            self._frame_time_lbl.setText(f"{t_ms:.1f} ms")
        else:
            self._frame_time_lbl.setText(f"#{idx}")

        n = cube.shape[0]
        means = np.nanmean(cube.reshape(n, -1), axis=1)
        ts = times if times is not None else np.arange(n, dtype=np.float64)
        self._curve.update_data(means, ts, idx)
        self._show_frame(idx)

    def _on_chart_cursor(self, idx: int):
        """Handle interactive cursor click/drag on the chart."""
        if self._result is None:
            return
        cube = self._result.delta_r_cube or self._result.frame_cube
        if cube is None:
            return
        idx = max(0, min(idx, cube.shape[0] - 1))
        self._frame_slider.setValue(idx)

    def _render_thermal_rgb(self, frame: np.ndarray,
                            use_delta: bool) -> Optional[np.ndarray]:
        """Render a frame to RGB using the active colormap."""
        cmap = self._cmap_combo.currentText()
        if use_delta and cmap in ("Thermal Delta", "signed"):
            finite = frame[np.isfinite(frame)]
            if finite.size == 0:
                return None
            limit = float(np.percentile(np.abs(finite), 99.5)) or 1e-9
            normed = np.clip(frame / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            return np.stack([r, g, b], axis=-1)
        disp = to_display(frame, mode="percentile")
        return apply_colormap(disp, cmap)

    def _show_frame(self, idx: int):
        """Render the frame at *idx* into the compositor."""
        if self._result is None:
            return
        cube = self._result.delta_r_cube
        use_delta = cube is not None
        if cube is None:
            cube = self._result.frame_cube
        if cube is None or idx < 0 or idx >= cube.shape[0]:
            return

        frame = cube[idx].astype(np.float32)
        merge = self._view_seg.index() == 1  # Merge mode

        if merge and self._result.reference is not None:
            ref = self._result.reference.astype(np.float32)
            self._compositor.set_base_frame(ref, cmap="gray")
            rgb = self._render_thermal_rgb(frame, use_delta)
            if rgb is not None:
                self._compositor.add_overlay(
                    "thermal", self._make_thermal_paint(rgb),
                    label="Thermal")
        else:
            rgb = self._render_thermal_rgb(frame, use_delta)
            if rgb is None:
                return
            self._compositor.set_base_frame(rgb)
            self._compositor.remove_overlay("thermal")

        # Push to detached viewer if open
        self._push_to_detached(idx)

    def _on_view_mode(self, idx: int):
        """Handle Thermal / Merge toggle."""
        self._show_frame(self._frame_slider.value())

    @staticmethod
    def _make_thermal_paint(rgb: np.ndarray):
        """Return a paint function that draws the thermal RGB as an overlay."""
        h, w = rgb.shape[:2]
        qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qi)
        def _paint(painter, img_size, frame_hw):
            scaled = pix.scaled(img_size, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled)
        return _paint

    def _paint_rois(self, painter, img_size, frame_hw):
        """Overlay paint function for ROI shapes (rect, ellipse, freeform)."""
        try:
            from acquisition.roi_model import roi_model
        except ImportError:
            return
        fh, fw = frame_hw
        iw, ih = img_size.width(), img_size.height()
        if fw <= 0 or fh <= 0:
            return
        sx, sy = iw / fw, ih / fh
        painter.setRenderHint(QPainter.Antialiasing, True)
        for roi in roi_model.rois:
            if roi.is_empty:
                continue
            color = QColor(roi.color or "#ffffff")
            color.setAlpha(200)
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            if roi.is_freeform and roi.vertices:
                poly = QPolygonF()
                for vx, vy in roi.vertices:
                    poly.append(QPointF(vx * sx, vy * sy))
                painter.drawPolygon(poly)
            elif roi.is_ellipse:
                painter.drawEllipse(int(roi.x * sx), int(roi.y * sy),
                                    int(roi.w * sx), int(roi.h * sy))
            else:
                painter.drawRect(int(roi.x * sx), int(roi.y * sy),
                                 int(roi.w * sx), int(roi.h * sy))
            if roi.label:
                painter.setFont(QFont(MONO_FONT, 8))
                painter.drawText(int(roi.x * sx) + 3, int(roi.y * sy) - 4,
                                 roi.label)

    def _update_roi_curves(self, full_frame_signal: Optional[np.ndarray] = None):
        """Extract per-ROI mean signal from the cube and push to chart + metrics."""
        if self._result is None:
            self._curve.set_roi_curves([])
            self._curve.clear_annotations()
            return
        cube = self._result.delta_r_cube
        if cube is None:
            cube = self._result.frame_cube
        if cube is None:
            self._curve.set_roi_curves([])
            self._curve.clear_annotations()
            return

        roi_signals = self._extract_roi_signals(cube)
        self._curve.set_roi_curves(roi_signals)

        # Compute full-frame signal if not provided
        if full_frame_signal is None:
            n = cube.shape[0]
            full_frame_signal = np.nanmean(cube.reshape(n, -1), axis=1)

        self._compute_and_display_metrics(roi_signals, full_frame_signal)

    def _extract_roi_signals(self, cube: np.ndarray
                             ) -> list[tuple[str, str, np.ndarray]]:
        """Extract current ROI signals from the cube via shared helper."""
        try:
            from acquisition.roi_model import roi_model
        except ImportError:
            return []
        if not hasattr(self, '_roi_mask_cache'):
            self._roi_mask_cache: dict = {}
        return _extract_roi_signals_shared(
            cube, roi_model.rois, self._roi_mask_cache)

    def _invalidate_roi_mask_cache(self):
        """Clear cached ROI masks when ROIs change geometry."""
        if hasattr(self, '_roi_mask_cache'):
            self._roi_mask_cache.clear()

    # ---------------------------------------------------------------- #
    #  Metrics computation + display                                    #
    # ---------------------------------------------------------------- #

    def _compute_and_display_metrics(
        self,
        roi_signals: list[tuple[str, str, np.ndarray]],
        full_frame_signal: Optional[np.ndarray] = None,
    ) -> None:
        """Compute per-ROI + full-frame metrics and populate the table."""
        ts = self._get_time_axis()
        if ts is None:
            return

        # Full-frame metrics
        if full_frame_signal is not None and len(full_frame_signal) == len(ts):
            self._ff_metrics = compute_movie_metrics(
                full_frame_signal, ts, roi_label="Full frame",
                roi_color=PALETTE['accent'])
        else:
            self._ff_metrics = None

        # Per-ROI metrics
        self._current_metrics = compute_all_movie_roi_metrics(roi_signals, ts)

        # Populate table
        self._populate_metrics_table()

        # Chart annotation — peak marker for full-frame (or first ROI)
        ref = self._ff_metrics
        if ref is None and self._current_metrics:
            ref = self._current_metrics[0]
        if ref is not None and ref.n_frames >= 1:
            self._curve.set_peak_marker(ref.peak_time_s, ref.peak_drr)
        else:
            self._curve.clear_annotations()

        # Enable export button
        self._save_analysis_btn.setEnabled(
            bool(self._current_metrics or self._ff_metrics))

    def _populate_metrics_table(self) -> None:
        """Fill the ROI metrics table from cached metrics."""
        table = self._metrics_table
        all_m: list[MovieMetrics] = []
        if self._ff_metrics is not None:
            all_m.append(self._ff_metrics)
        all_m.extend(self._current_metrics)

        table.setRowCount(len(all_m))
        for row, m in enumerate(all_m):
            def _item(text: str, color: str = "") -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if color:
                    it.setForeground(QColor(color))
                return it

            table.setItem(row, 0, _item(m.roi_label, m.roi_color))
            table.setItem(row, 1, _item(f"{m.peak_drr:+.4e}"))
            table.setItem(row, 2, _item(f"{m.peak_abs:.4e}"))
            table.setItem(row, 3, _item(f"{m.peak_time_s * 1e3:.1f} ms"))
            table.setItem(row, 4, _item(str(m.peak_index)))
            table.setItem(row, 5, _item(f"{m.mean_drr:+.4e}"))
            table.setItem(row, 6, _item(f"{m.temporal_std:.4e}"))

    def _get_time_axis(self) -> Optional[np.ndarray]:
        """Return the time axis for the current result."""
        if self._result is None:
            return None
        ts = self._result.timestamps_s
        if ts is not None:
            return ts
        cube = self._result.delta_r_cube or self._result.frame_cube
        if cube is not None:
            return np.arange(cube.shape[0], dtype=np.float64)
        return None

    # ---------------------------------------------------------------- #
    #  Save Analysis                                                    #
    # ---------------------------------------------------------------- #

    def _save_analysis(self) -> None:
        """Export ROI traces + summary metrics + acquisition metadata."""
        if self._result is None:
            return
        default_name = f"movie_analysis_{int(time.time())}"
        if self._loaded_session_label:
            slug = self._loaded_session_label.replace(" ", "_")
            default_name = f"{slug}_analysis"

        path, filt = QFileDialog.getSaveFileName(
            self, "Save Movie Analysis",
            default_name + ".csv",
            "CSV (*.csv);;JSON (*.json);;All files (*)")
        if not path:
            return

        try:
            ts = self._get_time_axis()
            if ts is None:
                return

            cube = self._result.delta_r_cube or self._result.frame_cube
            roi_signals = self._extract_roi_signals(cube) if cube is not None else []
            ff_signal = None
            if cube is not None:
                n = cube.shape[0]
                ff_signal = np.nanmean(cube.reshape(n, -1), axis=1)

            if path.lower().endswith(".json"):
                self._save_analysis_json(path, ts, ff_signal, roi_signals)
            else:
                self._save_analysis_csv(path, ts, ff_signal, roi_signals)

            QMessageBox.information(
                self, "Saved",
                f"Movie analysis saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _save_analysis_csv(self, path: str, ts: np.ndarray,
                           ff_signal: Optional[np.ndarray],
                           roi_signals: list) -> None:
        """Write traces + metrics to CSV."""
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)

            # Header: metadata
            w.writerow(["# Movie Analysis Export"])
            w.writerow(["# n_frames", self._result.n_frames])
            w.writerow(["# fps_achieved", self._result.fps_achieved])
            w.writerow(["# duration_s", self._result.duration_s])
            w.writerow(["# exposure_us", self._result.exposure_us])
            w.writerow([])

            # Traces section
            headers = ["time_s", "time_ms", "frame"]
            columns = [ts, ts * 1e3,
                       np.arange(len(ts), dtype=np.float64)]
            if ff_signal is not None:
                headers.append("full_frame")
                columns.append(ff_signal)
            for label, _color, sig in roi_signals:
                headers.append(label)
                columns.append(sig)
            w.writerow(headers)
            for i in range(len(ts)):
                w.writerow([f"{col[i]:.8e}" if i < len(col) else ""
                            for col in columns])
            w.writerow([])

            # Metrics section
            w.writerow(["# Metrics"])
            w.writerow(["roi", "peak_drr", "peak_abs", "peak_time_s",
                        "peak_index", "mean_drr", "temporal_std"])
            all_m: list[MovieMetrics] = []
            if self._ff_metrics is not None:
                all_m.append(self._ff_metrics)
            all_m.extend(self._current_metrics)
            for m in all_m:
                w.writerow([m.roi_label, f"{m.peak_drr:.6e}",
                           f"{m.peak_abs:.6e}", f"{m.peak_time_s:.6f}",
                           str(m.peak_index),
                           f"{m.mean_drr:.6e}", f"{m.temporal_std:.6e}"])

    def _save_analysis_json(self, path: str, ts: np.ndarray,
                            ff_signal: Optional[np.ndarray],
                            roi_signals: list) -> None:
        """Write traces + metrics to JSON."""
        import json as _json

        doc = {
            "format": "sanjinsight_movie_analysis_v1",
            "metadata": {
                "n_frames": self._result.n_frames,
                "frames_captured": self._result.frames_captured,
                "fps_achieved": self._result.fps_achieved,
                "exposure_us": self._result.exposure_us,
                "gain_db": self._result.gain_db,
                "duration_s": self._result.duration_s,
            },
            "timestamps_s": ts.tolist(),
            "traces": {},
            "metrics": [],
        }
        if ff_signal is not None:
            doc["traces"]["full_frame"] = ff_signal.tolist()
        for label, color, sig in roi_signals:
            doc["traces"][label] = sig.tolist()

        all_m: list[MovieMetrics] = []
        if self._ff_metrics is not None:
            all_m.append(self._ff_metrics)
        all_m.extend(self._current_metrics)
        doc["metrics"] = [m.to_dict() for m in all_m]

        with open(path, "w", encoding="utf-8") as f:
            _json.dump(doc, f, indent=2)

    # ---------------------------------------------------------------- #
    #  Save                                                             #
    # ---------------------------------------------------------------- #

    def _save(self):
        if self._result is None:
            return
        default_name = f"movie_{int(time.time())}.npz"
        if self._loaded_session_label:
            slug = self._loaded_session_label.replace(" ", "_")
            default_name = f"{slug}.npz"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Movie Cube",
            default_name,
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
            # Inform user about what was included
            contents = list(save_kw.keys())
            note = ""
            if self._loaded_session_label and "frame_cube" not in save_kw:
                note = "\n\nNote: frame_cube (raw intensity) is not available for reloaded sessions."
            QMessageBox.information(
                self, "Saved",
                f"Movie cube saved to:\n{path}\n\n"
                f"Contents: {', '.join(contents)}{note}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _export_video(self):
        """Export the frame cube or ΔR/R cube as an MP4/AVI video."""
        if self._result is None:
            return
        cube = self._result.delta_r_cube
        if cube is None:
            cube = self._result.frame_cube
        if cube is None:
            QMessageBox.warning(self, "No Data", "No frame data to export.")
            return

        from acquisition.video_export import available_formats
        exts = available_formats()
        filt = ";;".join([f"{e.upper()[1:]} video (*{e})" for e in exts])
        filt += ";;All files (*)"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Video",
            f"movie_{int(time.time())}.mp4",
            filt)
        if not path:
            return
        try:
            from acquisition.video_export import export_video
            fps = self._result.fps_achieved if self._result.fps_achieved > 0 else 10.0
            export_video(cube, path, fps=fps)
            QMessageBox.information(self, "Exported",
                                    f"Video exported to:\n{path}")
        except ImportError as e:
            QMessageBox.critical(self, "Missing Dependency", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

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
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                + (ok if app_state.cam else dim))
            self._hw_bias_lbl.setText("Connected" if app_state.bias else "—")
            self._hw_bias_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                + (ok if app_state.bias else dim))
            self._hw_fpga_lbl.setText("Connected" if app_state.fpga else "—")
            self._hw_fpga_lbl.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                + (ok if app_state.fpga else dim))
        except Exception:
            pass

    def showEvent(self, e):
        self._refresh_hw()
        super().showEvent(e)

    # ---------------------------------------------------------------- #
    #  Helpers                                                          #
    # ---------------------------------------------------------------- #

    # ── Detached viewer ──────────────────────────────────────────

    _detached_viewer = None

    def _on_detach_viewer(self) -> None:
        """Open (or bring to front) a detached large viewer window."""
        from ui.widgets.detach_helpers import open_detached_viewer
        open_detached_viewer(
            self, "_detached_viewer",
            source_id="movie.playback",
            title="Movie — Playback",
            initial_push=lambda v: self._push_to_detached(
                self._frame_slider.value()))

    def _push_to_detached(self, idx: int) -> None:
        """Send the current compositor pixmap to the detached viewer."""
        if self._detached_viewer is None:
            return
        try:
            pix = self._compositor.grab()
            n = self._frame_slider.maximum() + 1
            info = f"Frame {idx + 1}/{n}"
            # Provide raw data for cursor readout + colormap
            data = None
            rois = None
            cmap = ""
            if self._result is not None:
                cube = self._result.delta_r_cube
                if cube is not None and 0 <= idx < cube.shape[0]:
                    data = cube[idx].astype("float32")
                cmap = self._cmap_combo.currentText()
            self._detached_viewer.update_image(
                pix, info, data=data, rois=rois, cmap=cmap)
        except Exception:
            pass

    def _apply_styles(self):
        """Refresh inline stylesheets from the current PALETTE values."""
        mono_base = (f"font-family:{MONO_FONT}; "
                     f"font-size:{FONT['caption']}pt; ")
        for lbl in [self._hw_cam_lbl, self._hw_bias_lbl, self._hw_fpga_lbl]:
            lbl.setStyleSheet(mono_base + f"color:{PALETTE['textDim']};")
        self._status_lbl.setStyleSheet(
            mono_base + f"color:{PALETTE['textDim']};")
        if hasattr(self, '_compositor'):
            self._compositor._apply_styles()
        # Compact result strip values
        for val in self._stats.values():
            val.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
                f"color:{PALETTE['accent']};")
        self._frame_time_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['textDim']}; min-width:70px;")
        if hasattr(self, '_curve'):
            self._curve._apply_styles()
        if hasattr(self, '_metrics_table'):
            self._metrics_table.setStyleSheet(
                f"QTableWidget {{ font-family:{MONO_FONT}; "
                f"font-size:{FONT['caption']}pt; "
                f"background:{PALETTE['bg']}; color:{PALETTE['text']}; }}"
                f"QHeaderView::section {{ font-size:{FONT['caption']}pt; "
                f"background:{PALETTE['surface']}; color:{PALETTE['textSub']}; "
                f"padding:2px 4px; }}")
        if hasattr(self, '_metrics_panel'):
            self._metrics_panel._apply_styles()
        self._refresh_hw()

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
