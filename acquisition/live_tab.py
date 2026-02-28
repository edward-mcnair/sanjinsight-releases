"""
acquisition/live_tab.py

LiveTab — real-time thermoreflectance display.

Layout
------
Top bar     : Run / Stop / Freeze / Capture controls + status indicators
Left panel  : Settings (trigger mode, accumulation, frames/half, display fps, ROI)
Centre      : Full live ΔR/R map (fills remaining space)
Right panel : Numerical readouts — SNR meter, pixel probe, histogram,
              min/max/mean updated every frame
"""

from __future__ import annotations
import time
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout,
    QComboBox, QCheckBox, QSplitter, QSizePolicy, QFrame,
    QFileDialog, QMessageBox, QSlider)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui  import (QImage, QPixmap, QPainter, QPen, QColor,
                           QBrush, QFont, QLinearGradient, QFontMetrics)

from .live       import LiveProcessor, LiveConfig, LiveFrame
from .processing import to_display


# ------------------------------------------------------------------ #
#  SNR bar widget                                                     #
# ------------------------------------------------------------------ #

class SnrBar(QWidget):
    """Vertical SNR bargraph with dB scale."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(44)
        self.setMinimumHeight(80)
        self._value = 0.0
        self._min   = -20.0
        self._max   =  40.0

    def set_value(self, v: float):
        self._value = float(v)
        self.update()

    def paintEvent(self, e):
        p  = QPainter(self)
        W, H = self.width(), self.height()
        pad_top, pad_bot, pad_l = 8, 24, 6

        bar_h   = H - pad_top - pad_bot
        bar_w   = 14
        bar_x   = pad_l

        # Background
        p.fillRect(0, 0, W, H, QColor(18, 18, 18))

        # Gradient fill (green → yellow → red from top = good)
        grad = QLinearGradient(0, pad_top, 0, pad_top + bar_h)
        grad.setColorAt(0.0,  QColor(0,   210, 120))
        grad.setColorAt(0.4,  QColor(80,  200, 40))
        grad.setColorAt(0.7,  QColor(220, 200, 0))
        grad.setColorAt(1.0,  QColor(200, 40,  20))

        # Track
        p.setBrush(QColor(30, 30, 30))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(bar_x, pad_top, bar_w, bar_h, 2, 2)

        # Fill
        frac = (self._value - self._min) / (self._max - self._min)
        frac = max(0.0, min(1.0, frac))
        fill_h = int(bar_h * frac)
        fill_y = pad_top + bar_h - fill_h

        # Clip gradient to filled portion
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(bar_x, fill_y, bar_w, fill_h, 2, 2)

        # Scale ticks
        p.setPen(QColor(60, 60, 60))
        p.setFont(QFont("Menlo", 10))
        for db in [40, 20, 0, -20]:
            tf = (db - self._min) / (self._max - self._min)
            ty = int(pad_top + bar_h * (1.0 - tf))
            p.drawLine(bar_x + bar_w + 1, ty, bar_x + bar_w + 4, ty)
            p.setPen(QColor(80, 80, 80))
            p.drawText(bar_x + bar_w + 5, ty + 4, str(db))
            p.setPen(QColor(60, 60, 60))

        # Value label
        p.setFont(QFont("Menlo", 11))
        p.setPen(QColor(0, 200, 130) if frac > 0.4 else QColor(200, 80, 40))
        p.drawText(0, H - 10, W, 12, Qt.AlignCenter,
                   f"{self._value:.1f}dB")
        p.end()


# ------------------------------------------------------------------ #
#  Histogram widget                                                   #
# ------------------------------------------------------------------ #

class Histogram(QWidget):
    """Compact ΔR/R histogram."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self._bins  = None
        self._edges = None

    def update_data(self, data: np.ndarray):
        try:
            flat = data.ravel()
            lo   = float(np.percentile(flat, 0.5))
            hi   = float(np.percentile(flat, 99.5))
            if hi == lo:
                hi = lo + 1e-9
            self._bins, edges = np.histogram(flat, bins=64, range=(lo, hi))
            self._edges = edges
        except Exception:
            self._bins = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(18, 18, 18))

        if self._bins is None:
            p.setPen(QColor(40, 40, 40))
            p.drawText(self.rect(), Qt.AlignCenter, "No data")
            p.end()
            return

        mx   = float(self._bins.max()) or 1.0
        nb   = len(self._bins)
        bw   = W / nb
        pad  = 4

        for i, v in enumerate(self._bins):
            bh  = int((v / mx) * (H - pad))
            bx  = int(i * bw)
            by  = H - bh

            # Colour by position: blue(negative) → black(zero) → red(positive)
            t   = i / nb          # 0..1
            if t < 0.5:
                r, g, b = 0, 0, int((1 - t * 2) * 160)
            else:
                r, g, b = int((t - 0.5) * 2 * 200), 0, 0

            p.fillRect(bx, by, max(1, int(bw) - 1), bh, QColor(r, g, b))

        # Zero line
        p.setPen(QPen(QColor(60, 60, 60), 1, Qt.DotLine))
        lo = self._edges[0]
        hi = self._edges[-1]
        if lo < 0 < hi:
            zx = int((-lo) / (hi - lo) * W)
            p.drawLine(zx, 0, zx, H)

        p.end()


# ------------------------------------------------------------------ #
#  Live map canvas                                                    #
# ------------------------------------------------------------------ #

class LiveCanvas(QWidget):
    """Displays the live ΔR/R map. Optionally shows a crosshair probe."""

    probe_moved = pyqtSignal(int, int)   # pixel x, y under cursor

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#0d0d0d;")
        self.setMouseTracking(True)

        self._pixmap    = None
        self._frozen    = False
        self._cmap      = "signed"
        self._data      = None
        self._probe_pos = None   # (px, py) in widget coords

    def set_cmap(self, cmap: str):
        self._cmap = cmap

    def update_frame(self, frame: LiveFrame):
        if self._frozen or frame.drr is None:
            return
        self._data = frame.drr
        self._rebuild(frame.drr)
        self.update()

    def freeze(self, yes: bool):
        self._frozen = yes

    def _rebuild(self, data: np.ndarray):
        d = data.astype(np.float32)
        if self._cmap == "signed":
            limit  = float(np.percentile(np.abs(d), 99.5)) or 1e-9
            normed = np.clip(d / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            rgb = np.stack([r, g, b], axis=-1)
        else:
            disp = to_display(d, mode="percentile")
            try:
                import cv2
                cv_maps = {"hot":     cv2.COLORMAP_HOT,
                           "cool":    cv2.COLORMAP_COOL,
                           "viridis": cv2.COLORMAP_VIRIDIS}
                rgb = cv2.applyColorMap(
                    disp, cv_maps.get(self._cmap, cv2.COLORMAP_HOT))
            except ImportError:
                rgb = np.stack([disp]*3, axis=-1)

        h, w = rgb.shape[:2]
        qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qi)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(13, 13, 13))

        if self._pixmap is None:
            p.setPen(QColor(45, 45, 45))
            p.setFont(QFont("Helvetica", 18))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Live ΔR/R\n\nPress  ▶  Start  to begin")
            if self._frozen:
                self._draw_frozen_badge(p)
            p.end()
            return

        W, H   = self.width(), self.height()
        PAD    = 6
        scaled = self._pixmap.scaled(
            W - 2*PAD, H - 2*PAD,
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ox = (W - scaled.width())  // 2
        oy = (H - scaled.height()) // 2
        p.drawPixmap(ox, oy, scaled)

        # Crosshair probe
        if self._probe_pos:
            px, py = self._probe_pos
            pen = QPen(QColor(0, 220, 150, 160), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(px, oy, px, oy + scaled.height())
            p.drawLine(ox, py, ox + scaled.width(), py)

        if self._frozen:
            self._draw_frozen_badge(p)
        p.end()

    def _draw_frozen_badge(self, p: QPainter):
        p.setBrush(QColor(0, 180, 130, 200))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(8, 8, 70, 22, 4, 4)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Helvetica-Bold", 14))
        p.drawText(8, 8, 70, 22, Qt.AlignCenter, "FROZEN")

    def mouseMoveEvent(self, e):
        self._probe_pos = (e.x(), e.y())
        if self._pixmap and self._data is not None:
            # Map widget coords back to data coords
            W, H   = self.width(), self.height()
            PAD    = 6
            sw     = min(W - 2*PAD, int((H - 2*PAD) *
                         self._pixmap.width() / max(self._pixmap.height(), 1)))
            sh     = min(H - 2*PAD, int((W - 2*PAD) *
                         self._pixmap.height() / max(self._pixmap.width(), 1)))
            ox     = (W - sw) // 2
            oy     = (H - sh) // 2
            dx     = int((e.x() - ox) / sw * self._data.shape[1])
            dy     = int((e.y() - oy) / sh * self._data.shape[0])
            dx     = max(0, min(dx, self._data.shape[1] - 1))
            dy     = max(0, min(dy, self._data.shape[0] - 1))
            self.probe_moved.emit(dx, dy)
        self.update()

    def leaveEvent(self, e):
        self._probe_pos = None
        self.update()

    def save_snapshot(self, path: str):
        if self._pixmap:
            self._pixmap.save(path)


# ------------------------------------------------------------------ #
#  Live tab                                                           #
# ------------------------------------------------------------------ #

class LiveTab(QWidget):

    def __init__(self):
        super().__init__()
        self._proc    = None
        self._frozen  = False
        self._last_frame: LiveFrame = None

        # Poll timer — reads queue and updates UI
        self._timer = QTimer()
        self._timer.setInterval(50)   # 20 Hz max UI update
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._build_settings())
        body.addWidget(self._build_canvas())
        body.addWidget(self._build_readouts())
        body.setSizes([220, 900, 200])
        root.addWidget(body, 1)

    # ---------------------------------------------------------------- #
    #  Toolbar                                                          #
    # ---------------------------------------------------------------- #

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            "background:#151515; border-bottom:1px solid #1e1e1e;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self._start_btn  = QPushButton("▶  Start")
        self._stop_btn   = QPushButton("■  Stop")
        self._freeze_btn = QPushButton("❄  Freeze")
        self._capture_btn= QPushButton("📷  Capture")
        self._reset_btn  = QPushButton("↺  Reset EMA")

        self._start_btn.setObjectName("primary")
        self._stop_btn.setObjectName("danger")
        self._stop_btn.setEnabled(False)

        for b in [self._start_btn, self._stop_btn, self._freeze_btn,
                  self._capture_btn, self._reset_btn]:
            b.setFixedHeight(30)
            lay.addWidget(b)

        lay.addSpacing(20)

        # Status indicators
        self._fps_lbl    = self._badge("— fps",   "#333")
        self._cycle_lbl  = self._badge("cycle —", "#333")
        self._state_lbl  = self._badge("IDLE",    "#333")

        for l in [self._fps_lbl, self._cycle_lbl, self._state_lbl]:
            lay.addWidget(l)

        lay.addStretch()

        # Colourmap selector in toolbar
        lay.addWidget(QLabel("Cmap:"))
        self._cmap_combo = QComboBox()
        for c in ["signed", "hot", "cool", "viridis"]:
            self._cmap_combo.addItem(c)
        self._cmap_combo.setFixedWidth(80)
        self._cmap_combo.setFixedHeight(28)
        self._cmap_combo.currentTextChanged.connect(
            lambda c: self._canvas.set_cmap(c))
        lay.addWidget(self._cmap_combo)

        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        self._freeze_btn.clicked.connect(self._toggle_freeze)
        self._capture_btn.clicked.connect(self._capture)
        self._reset_btn.clicked.connect(self._reset_ema)

        return bar

    def _badge(self, text, color) -> QLabel:
        l = QLabel(text)
        l.setFixedHeight(24)
        l.setStyleSheet(
            f"background:{color}; color:#888; padding:0 8px; "
            f"border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")
        return l

    # ---------------------------------------------------------------- #
    #  Settings panel                                                   #
    # ---------------------------------------------------------------- #

    def _build_settings(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(200)
        w.setMaximumWidth(260)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        # Trigger
        trig_box = QGroupBox("Trigger")
        tl = QGridLayout(trig_box)
        tl.setSpacing(5)

        self._trig_mode = QComboBox()
        self._trig_mode.addItems(["fpga", "software"])
        self._trig_delay = QDoubleSpinBox()
        self._trig_delay.setRange(0, 100)
        self._trig_delay.setValue(5.0)
        self._trig_delay.setSuffix(" ms")
        self._trig_delay.setFixedWidth(90)

        tl.addWidget(self._sub("Mode"),  0, 0)
        tl.addWidget(self._trig_mode,    0, 1)
        tl.addWidget(self._sub("Delay"), 1, 0)
        tl.addWidget(self._trig_delay,   1, 1)
        lay.addWidget(trig_box)

        # Acquisition
        acq_box = QGroupBox("Acquisition")
        al = QGridLayout(acq_box)
        al.setSpacing(5)

        self._frames_per_half = QSpinBox()
        self._frames_per_half.setRange(1, 64)
        self._frames_per_half.setValue(4)
        self._frames_per_half.setFixedWidth(70)

        self._accum = QSpinBox()
        self._accum.setRange(1, 256)
        self._accum.setValue(16)
        self._accum.setFixedWidth(70)
        self._accum.setToolTip(
            "EMA depth — higher = smoother signal, slower transient response")

        self._disp_fps = QDoubleSpinBox()
        self._disp_fps.setRange(1, 30)
        self._disp_fps.setValue(10)
        self._disp_fps.setSuffix(" fps")
        self._disp_fps.setFixedWidth(90)

        from ui.help import help_label
        al.addWidget(help_label("Frames/half", "n_frames"),  0, 0)
        al.addWidget(self._frames_per_half,                   0, 1)
        al.addWidget(help_label("EMA depth", "accumulation"), 1, 0)
        al.addWidget(self._accum,                             1, 1)
        al.addWidget(self._sub("Display fps"),                2, 0)
        al.addWidget(self._disp_fps,                          2, 1)
        lay.addWidget(acq_box)

        # EMA depth slider (visual)
        depth_box = QGroupBox("Accumulation depth")
        dl = QVBoxLayout(depth_box)
        self._accum_slider = QSlider(Qt.Horizontal)
        self._accum_slider.setRange(1, 128)
        self._accum_slider.setValue(16)
        self._accum_slider.setTickPosition(QSlider.TicksBelow)
        self._accum_slider.setTickInterval(16)
        self._accum_slider.valueChanged.connect(self._accum.setValue)
        self._accum.valueChanged.connect(self._accum_slider.setValue)
        self._accum_lbl = QLabel("16 frames")
        self._accum_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        self._accum.valueChanged.connect(
            lambda v: self._accum_lbl.setText(f"{v} frames"))
        dl.addWidget(self._accum_slider)
        dl.addWidget(self._accum_lbl)
        lay.addWidget(depth_box)

        # Apply button
        self._apply_btn = QPushButton("↻  Apply Settings")
        self._apply_btn.setFixedHeight(30)
        self._apply_btn.clicked.connect(self._apply_config)
        lay.addWidget(self._apply_btn)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Canvas (centre)                                                  #
    # ---------------------------------------------------------------- #

    def _build_canvas(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        self._canvas = LiveCanvas()
        self._canvas.probe_moved.connect(self._on_probe)
        lay.addWidget(self._canvas)
        return w

    # ---------------------------------------------------------------- #
    #  Readouts panel (right)                                           #
    # ---------------------------------------------------------------- #

    def _build_readouts(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(180)
        w.setMaximumWidth(220)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        lay.addWidget(self._sub("SNR"))
        self._snr_bar = SnrBar()
        lay.addWidget(self._snr_bar)

        # Numerical stats
        stats_box = QGroupBox("Frame Stats")
        sl = QGridLayout(stats_box)
        sl.setSpacing(4)
        self._stat_vals = {}
        for r, (key, lbl) in enumerate([
            ("min",   "Min ΔR/R"),
            ("max",   "Max ΔR/R"),
            ("mean",  "Mean ΔR/R"),
            ("std",   "Std Dev"),
            ("snr",   "SNR (dB)"),
            ("cycle", "Cycles"),
            ("fps",   "Live fps"),
        ]):
            sl.addWidget(self._sub(lbl), r, 0)
            v = QLabel("—")
            v.setStyleSheet(
                "font-family:Menlo,monospace; font-size:14pt; color:#aaa;")
            v.setAlignment(Qt.AlignRight)
            sl.addWidget(v, r, 1)
            self._stat_vals[key] = v
        lay.addWidget(stats_box)

        # Probe readout
        probe_box = QGroupBox("Pixel Probe")
        pl = QGridLayout(probe_box)
        pl.setSpacing(4)
        self._probe_xy  = QLabel("—")
        self._probe_drr = QLabel("—")
        self._probe_dt  = QLabel("—")
        for l in [self._probe_xy, self._probe_drr, self._probe_dt]:
            l.setStyleSheet(
                "font-family:Menlo,monospace; font-size:14pt; color:#aaa;")
        pl.addWidget(self._sub("Position"), 0, 0)
        pl.addWidget(self._probe_xy,         0, 1)
        pl.addWidget(self._sub("ΔR/R"),     1, 0)
        pl.addWidget(self._probe_drr,        1, 1)
        pl.addWidget(self._sub("ΔT (°C)"),  2, 0)
        pl.addWidget(self._probe_dt,         2, 1)
        lay.addWidget(probe_box)

        # Histogram
        lay.addWidget(self._sub("ΔR/R Histogram"))
        self._histogram = Histogram()
        lay.addWidget(self._histogram)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def set_calibration(self, cal):
        """Update calibration for live ΔT display."""
        if self._proc:
            self._proc._cal = cal

    # ---------------------------------------------------------------- #
    #  Controls                                                         #
    # ---------------------------------------------------------------- #

    def _build_config(self) -> LiveConfig:
        return LiveConfig(
            frames_per_half  = self._frames_per_half.value(),
            accumulation     = self._accum.value(),
            trigger_mode     = self._trig_mode.currentText(),
            trigger_delay_ms = self._trig_delay.value(),
            display_fps      = self._disp_fps.value(),
        )

    def _start(self):
        try:
            import main_app
            _cam   = main_app.cam
            _fpga  = main_app.fpga
            _cal   = getattr(main_app, "active_calibration", None)
        except Exception:
            _cam = _fpga = _cal = None

        cfg = self._build_config()
        self._proc = LiveProcessor(_cam, _fpga, cfg, calibration=_cal)
        self._proc.start()

        self._timer.start()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._frozen = False
        self._canvas.freeze(False)
        self._set_state("RUNNING", "#00d4aa")

    def _stop(self):
        self._timer.stop()
        if self._proc:
            self._proc.stop()
            self._proc = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_state("STOPPED", "#555")

    def _toggle_freeze(self):
        self._frozen = not self._frozen
        self._canvas.freeze(self._frozen)
        self._freeze_btn.setText("▶  Resume" if self._frozen else "❄  Freeze")
        self._set_state("FROZEN" if self._frozen else "RUNNING",
                        "#ffaa44" if self._frozen else "#00d4aa")

    def _capture(self):
        """Save the current frozen/live frame to disk."""
        if self._last_frame is None or self._last_frame.drr is None:
            QMessageBox.warning(self, "No Frame", "No live frame to capture.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Live Frame", "live_frame.npy",
            "NumPy files (*.npy);;PNG images (*.png);;All files (*)")
        if not path:
            return
        import numpy as np
        if path.endswith(".png"):
            self._canvas.save_snapshot(path)
        else:
            np.save(path, self._last_frame.drr)
            if self._last_frame.dt_map is not None:
                np.save(path.replace(".npy", "_dt.npy"),
                        self._last_frame.dt_map)
        QMessageBox.information(self, "Saved", f"Frame saved to:\n{path}")

    def _reset_ema(self):
        if self._proc:
            self._proc.reset_ema()

    def _apply_config(self):
        if self._proc:
            self._proc.update_config(self._build_config())

    # ---------------------------------------------------------------- #
    #  Poll timer — reads queue and refreshes UI                       #
    # ---------------------------------------------------------------- #

    def _poll(self):
        if self._proc is None:
            return

        frame = self._proc.get_frame(timeout=0.0)
        if frame is None:
            return

        self._last_frame = frame
        self._canvas.update_frame(frame)
        self._histogram.update_data(frame.drr)
        self._snr_bar.set_value(frame.snr_db)

        # Stats
        drr = frame.drr
        if drr is not None:
            flat = drr.ravel()
            self._stat_vals["min"].setText(f"{float(flat.min()):.4e}")
            self._stat_vals["max"].setText(f"{float(flat.max()):.4e}")
            self._stat_vals["mean"].setText(f"{float(flat.mean()):.4e}")
            self._stat_vals["std"].setText(f"{float(flat.std()):.4e}")
        self._stat_vals["snr"].setText(f"{frame.snr_db:.1f}")
        self._stat_vals["cycle"].setText(str(frame.cycle))
        self._stat_vals["fps"].setText(f"{frame.fps:.1f}")

        # Toolbar badges
        self._fps_lbl.setText(f"{frame.fps:.1f} fps")
        self._fps_lbl.setStyleSheet(
            "background:#1a2a1a; color:#00d4aa; padding:0 8px; "
            "border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")
        self._cycle_lbl.setText(f"cycle {frame.cycle}")
        self._cycle_lbl.setStyleSheet(
            "background:#1a1a2a; color:#6688cc; padding:0 8px; "
            "border-radius:3px; font-family:Menlo,monospace; font-size:12pt;")

    def _on_probe(self, dx: int, dy: int):
        """Update pixel probe readout from mouse position."""
        if self._last_frame is None:
            return
        drr = self._last_frame.drr
        if drr is None:
            return
        dy = max(0, min(dy, drr.shape[0] - 1))
        dx = max(0, min(dx, drr.shape[1] - 1))
        self._probe_xy.setText(f"({dx}, {dy})")
        self._probe_drr.setText(f"{drr[dy, dx]:.5e}")

        dt = self._last_frame.dt_map
        if dt is not None and 0 <= dy < dt.shape[0] and 0 <= dx < dt.shape[1]:
            v = dt[dy, dx]
            self._probe_dt.setText(
                "masked" if not np.isfinite(v) else f"{v:.3f} °C")
        else:
            self._probe_dt.setText("—")

    # ---------------------------------------------------------------- #
    #  State badge helper                                               #
    # ---------------------------------------------------------------- #

    def _set_state(self, text: str, color: str):
        self._state_lbl.setText(text)
        self._state_lbl.setStyleSheet(
            f"background:#111; color:{color}; padding:0 8px; "
            f"border-radius:3px; font-family:Menlo,monospace; font-size:12pt; "
            f"border:1px solid {color};")

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
