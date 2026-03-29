"""
acquisition/scan_tab.py

ScanTab — large-area mapping UI.

Left panel  : Grid configuration (cols × rows, step size, acquire settings)
              + Run / Abort controls + progress log
Right panel : Live stitched map with tile grid overlay
              + completed result viewer (ΔR/R  |  ΔT  |  Cold  |  Hot)
              + export / save buttons
"""

from __future__ import annotations
import os, time
import numpy as np

from ui.button_utils import RunningButton, apply_hand_cursor
from ui.font_utils   import sans_font
from ui.theme import FONT, PALETTE, scaled_qss

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QProgressBar,
    QTextEdit, QFileDialog, QSplitter, QFrame, QTabWidget,
    QSizePolicy, QCheckBox, QComboBox, QScrollArea, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from ui.icons import set_btn_icon
from PyQt5.QtGui  import (QImage, QPixmap, QPainter, QPen, QColor,
                           QBrush, QFont)

from .scan       import ScanProgress, ScanResult
from .processing import to_display, apply_colormap, COLORMAP_OPTIONS, COLORMAP_TOOLTIPS, setup_cmap_combo
import config as cfg_mod
from ui.widgets.more_options import MoreOptionsPanel
from ui.widgets.time_estimate_label import TimeEstimateLabel


# ------------------------------------------------------------------ #
#  Map viewer with tile-grid overlay                                  #
# ------------------------------------------------------------------ #

class ScanMapView(QWidget):
    """
    Renders the stitched ΔR/R map with an overlaid tile grid.
    Supports zoom-to-fit and optional physical scale annotation.
    """

    context_save_image = pyqtSignal()   # user requested "Save Map Image…"

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#0d0d0d;")
        self.setMouseTracking(True)

        self._data      = None   # float32 map
        self._n_cols    = 1
        self._n_rows    = 1
        self._step_x_um = 100.0
        self._step_y_um = 100.0
        self._show_grid = True
        self._cmap      = "Thermal Delta"
        self._pixmap    = None
        self._title     = ""

        # ── Zoom & pan ────────────────────────────────────────────────
        self._zoom           = 1.0
        self._pan_x          = 0.0
        self._pan_y          = 0.0
        self._drag_start     = None
        self._drag_pan_start = (0.0, 0.0)

    def update_map(self, data: np.ndarray,
                   n_cols: int, n_rows: int,
                   step_x_um: float, step_y_um: float,
                   cmap: str = "Thermal Delta"):
        self._data      = data
        self._n_cols    = n_cols
        self._n_rows    = n_rows
        self._step_x_um = step_x_um
        self._step_y_um = step_y_um
        self._cmap      = cmap
        self._rebuild_pixmap()
        self.update()

    def set_grid_visible(self, v: bool):
        self._show_grid = v
        self.update()

    def set_title(self, t: str):
        self._title = t
        self.update()

    def _rebuild_pixmap(self):
        if self._data is None:
            self._pixmap = None
            return

        if self._cmap in ("Thermal Delta", "signed"):
            d      = self._data.astype(np.float32)
            limit  = float(np.percentile(np.abs(d), 99.5)) or 1e-9
            normed = np.clip(d / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            rgb = np.stack([r, g, b], axis=-1)
        else:
            disp = to_display(self._data, mode="percentile")
            rgb  = apply_colormap(disp, self._cmap)

        h, w = rgb.shape[:2]
        buf = rgb.tobytes()   # keep ref alive for QImage
        qi = QImage(buf, w, h, w*3, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qi)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(13, 13, 13))

        if self._pixmap is None:
            p.setPen(QColor(60, 60, 60))
            p.setFont(sans_font(15))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No scan data\n\nConfigure grid and run scan")
            p.end()
            return

        # Scale pixmap to fit widget (honouring zoom/pan)
        W, H = self.width(), self.height()
        PAD  = 8
        ox, oy, dw, dh = self._draw_rect()
        scaled = self._pixmap.scaled(dw, dh, Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
        p.drawPixmap(ox, oy, scaled)

        # Tile grid overlay
        if self._show_grid and self._n_cols > 0 and self._n_rows > 0:
            p.setPen(QPen(QColor(0, 180, 130, 80), 1, Qt.DotLine))
            tw = dw / self._n_cols
            th = dh / self._n_rows
            for c in range(1, self._n_cols):
                x = ox + int(c * tw)
                p.drawLine(x, oy, x, oy + dh)
            for r in range(1, self._n_rows):
                y = oy + int(r * th)
                p.drawLine(ox, y, ox + dw, y)

        # Scale bar (100 μm)
        px_per_um = (dw / self._n_cols) / self._step_x_um \
                    if self._step_x_um > 0 else 0
        if px_per_um > 0:
            bar_um  = 100.0
            bar_px  = int(bar_um * px_per_um)
            bar_x   = ox + 12
            bar_y   = oy + dh - 14
            p.setPen(QPen(QColor(255, 255, 255, 180), 2))
            p.drawLine(bar_x, bar_y, bar_x + bar_px, bar_y)
            p.setFont(sans_font(11))
            p.setPen(QColor(220, 220, 220))
            p.drawText(bar_x, bar_y - 2, f"{bar_um:.0f} μm")

        # Title
        if self._title:
            p.setPen(QColor(100, 100, 100))
            p.setFont(sans_font(12))
            p.drawText(self.rect().adjusted(8, 4, -8, -4),
                       Qt.AlignTop | Qt.AlignRight, self._title)

        # Zoom indicator
        if abs(self._zoom - 1.0) > 0.05:
            p.setPen(QColor(180, 180, 180, 200))
            p.setFont(sans_font(11))
            p.drawText(8, self.height() - 8, f"×{self._zoom:.2f}")

        p.end()

    # ── Zoom & pan helpers ────────────────────────────────────────────

    def _draw_rect(self):
        """(ox, oy, dw, dh) for the pixmap given current zoom/pan."""
        if self._pixmap is None:
            return 0, 0, self.width(), self.height()
        W, H = self.width(), self.height()
        PAD  = 8
        pw, ph = self._pixmap.width(), max(self._pixmap.height(), 1)
        fit_scale = min((W - 2*PAD) / max(pw, 1), (H - 2*PAD) / max(ph, 1))
        dw = max(1, int(pw * fit_scale * self._zoom))
        dh = max(1, int(ph * fit_scale * self._zoom))
        ox = (W - dw) // 2 + int(self._pan_x)
        oy = (H - dh) // 2 + int(self._pan_y)
        return ox, oy, dw, dh

    def wheelEvent(self, e):
        if self._pixmap is None:
            return
        delta   = e.angleDelta().y()
        factor  = 1.15 if delta > 0 else 1.0 / 1.15
        new_zoom = max(0.25, min(16.0, self._zoom * factor))
        r = self._draw_rect()
        if r and new_zoom != self._zoom:
            ox, oy, dw, dh = r
            cx, cy = e.x(), e.y()
            new_ox = cx - int((cx - ox) * new_zoom / max(self._zoom, 1e-9))
            new_oy = cy - int((cy - oy) * new_zoom / max(self._zoom, 1e-9))
            new_dw = max(1, int(dw * new_zoom / max(self._zoom, 1e-9)))
            new_dh = max(1, int(dh * new_zoom / max(self._zoom, 1e-9)))
            W, H = self.width(), self.height()
            self._pan_x = new_ox - (W - new_dw) // 2
            self._pan_y = new_oy - (H - new_dh) // 2
        self._zoom = new_zoom
        self.update()
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._drag_start     = e.pos()
            self._drag_pan_start = (self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MiddleButton and self._drag_start is not None:
            dx = e.x() - self._drag_start.x()
            dy = e.y() - self._drag_start.y()
            self._pan_x = self._drag_pan_start[0] + dx
            self._pan_y = self._drag_pan_start[1] + dy
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._drag_start = None
            self.setCursor(Qt.ArrowCursor)
        else:
            super().mouseReleaseEvent(e)

    def reset_zoom(self):
        self._zoom  = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def save_image(self, path: str):
        if self._pixmap:
            self._pixmap.save(path)

    def contextMenuEvent(self, e):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{PALETTE.get('surface','#2d2d2d')}; color:{PALETTE.get('text','#ebebeb')}; border:1px solid {PALETTE.get('border','#484848')}; }}"
            f"QMenu::item:selected {{ background:{PALETTE.get('surface2','#3d3d3d')}; }}"
            f"QMenu::separator {{ height:1px; background:{PALETTE.get('border','#484848')}; margin:3px 8px; }}")
        menu.addAction("🔍  Reset Zoom (fit)", self.reset_zoom)
        menu.addSeparator()
        act_save = menu.addAction("💾  Save Map Image…")
        act_save.setEnabled(self._pixmap is not None)
        act_save.triggered.connect(self.context_save_image)
        menu.exec_(e.globalPos())


# ------------------------------------------------------------------ #
#  Scan tab                                                           #
# ------------------------------------------------------------------ #

class ScanTab(QWidget):

    def __init__(self):
        super().__init__()
        self._runner  = None
        self._result  = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._body_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self._body_splitter)

        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(290)
        left_scroll.setMaximumWidth(360)
        left_scroll.setWidget(self._build_left())

        self._body_splitter.addWidget(left_scroll)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setWidget(self._build_right())
        self._body_splitter.addWidget(right_scroll)
        self._body_splitter.setSizes([320, 900])

    # ---------------------------------------------------------------- #
    #  Left panel — config + controls                                  #
    # ---------------------------------------------------------------- #

    def _build_left(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 6, 10)
        lay.setSpacing(10)

        # ---- Grid config ----
        grid_box = QGroupBox("Scan Grid")
        gl = QGridLayout(grid_box)
        gl.setSpacing(6)
        gl.setColumnStretch(1, 1)

        def row(lbl, widget, r):
            gl.addWidget(self._sub(lbl), r, 0)
            gl.addWidget(widget, r, 1)

        self._n_cols    = QSpinBox();       self._n_cols.setRange(1, 20)
        self._n_cols.setValue(3);           self._n_cols.setMinimumWidth(70)

        self._n_rows    = QSpinBox();       self._n_rows.setRange(1, 20)
        self._n_rows.setValue(3);           self._n_rows.setMinimumWidth(70)

        self._step_x    = QDoubleSpinBox(); self._step_x.setRange(1, 10000)
        self._step_x.setValue(100.0);       self._step_x.setSuffix(" μm")
        self._step_x.setMinimumWidth(80)

        self._step_y    = QDoubleSpinBox(); self._step_y.setRange(1, 10000)
        self._step_y.setValue(100.0);       self._step_y.setSuffix(" μm")
        self._step_y.setMinimumWidth(80)

        self._settle    = QDoubleSpinBox(); self._settle.setRange(0.1, 30)
        self._settle.setValue(0.5);         self._settle.setSuffix(" s")
        self._settle.setMinimumWidth(70)

        self._n_frames  = QSpinBox();       self._n_frames.setRange(5, 200)
        self._n_frames.setValue(20);        self._n_frames.setMinimumWidth(70)

        self._snake     = QCheckBox("Snake scan (boustrophedon)")
        self._snake.setChecked(True)

        row("Columns (X)",  self._n_cols,   0)
        row("Rows (Y)",     self._n_rows,   1)
        row("Step X",       self._step_x,   2)
        row("Step Y",       self._step_y,   3)
        row("Settle time",  self._settle,   4)
        row("Frames/tile",  self._n_frames, 5)
        gl.addWidget(self._snake, 6, 0, 1, 2)
        lay.addWidget(grid_box)

        # ---- Tile size summary ----
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['label']}pt; color:#666;")
        self._summary_lbl.setWordWrap(True)
        lay.addWidget(self._summary_lbl)

        self._time_est_lbl = TimeEstimateLabel()
        lay.addWidget(self._time_est_lbl)

        self._update_summary()
        for spin in [self._n_cols, self._n_rows, self._step_x, self._step_y,
                     self._n_frames, self._settle]:
            spin.valueChanged.connect(self._update_summary)

        # ---- Run controls ----
        run_box = QGroupBox("Run")
        rl = QVBoxLayout(run_box)
        rl.setSpacing(6)

        self._run_btn   = QPushButton("Start Scan")
        set_btn_icon(self._run_btn, "fa5s.play", "#00d4aa")
        self._run_btn.setObjectName("primary")
        self._run_btn.setFixedHeight(42)   # was 34 — taller so spinner text is
        self._run_btn.setStyleSheet(       # clearly readable while scanning
            scaled_qss("font-size:15pt; font-weight:600;"))

        self._abort_btn = QPushButton("Abort")
        set_btn_icon(self._abort_btn, "fa5s.stop", "#ff6666")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setFixedHeight(30)
        self._abort_btn.setEnabled(False)

        self._btn_runner = RunningButton(self._run_btn, idle_text="▶  Start Scan")
        apply_hand_cursor(self._abort_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(20)  # doubled from default ~10 px

        self._tile_lbl = QLabel("Ready")
        self._tile_lbl.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['heading']}pt; color:#555;")
        self._tile_lbl.setWordWrap(True)

        rl.addWidget(self._run_btn)
        rl.addWidget(self._abort_btn)
        rl.addWidget(self._progress)
        rl.addWidget(self._tile_lbl)
        lay.addWidget(run_box)

        # ---- Log (collapsed in Guided, expanded in Expert) ----
        self._scan_log_more = MoreOptionsPanel(
            "Scan Log", section_key="scan_log")
        log_box = QGroupBox("Log")
        ll = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        self._log.setStyleSheet(
            f"background:{PALETTE.get('bg','#242424')}; color:{PALETTE.get('textDim','#888')}; "
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['sublabel']}pt;")
        ll.addWidget(self._log)
        self._scan_log_more.addWidget(log_box)
        lay.addWidget(self._scan_log_more)
        lay.addStretch()

        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)
        return w

    # ---------------------------------------------------------------- #
    #  Right panel — map viewer + result tabs                          #
    # ---------------------------------------------------------------- #

    def _build_right(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        # ---- Stats row ----
        stats_box = QGroupBox("Scan Status")
        sl = QHBoxLayout(stats_box)
        self._stat_fields = {}
        for key, label in [("tiles",   "Tiles"),
                            ("size",    "Map Size"),
                            ("fov",     "Field of View"),
                            ("elapsed", "Elapsed"),
                            ("state",   "State")]:
            w2 = QWidget()
            v  = QVBoxLayout(w2)
            v.setAlignment(Qt.AlignCenter)
            sub = QLabel(label)
            sub.setObjectName("sublabel")
            sub.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(
                scaled_qss("font-family:'Menlo','Consolas','Courier New',monospace; font-size:15pt; color:#aaa;"))
            v.addWidget(sub)
            v.addWidget(val)
            w2._val = val
            sl.addWidget(w2)
            self._stat_fields[key] = w2
        lay.addWidget(stats_box)

        # ---- Map tabs ----
        result_tabs = QTabWidget()
        # documentMode(True) strips the frame that visually connects the tab
        # bar to the content area; without it, the inactive tab looks like it
        # is floating in the wrong position.  Use explicit styling instead.
        result_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {PALETTE.get('border','#484848')};
                border-top: none;
                background: {PALETTE.get('bg','#242424')};
            }}
            QTabBar::tab {{
                background: {PALETTE.get('surface2','#3d3d3d')};
                color: {PALETTE.get('textDim','#999999')};
                border: 1px solid {PALETTE.get('border','#484848')};
                border-bottom: none;
                border-radius: 3px 3px 0 0;
                padding: 4px 20px;
                min-width: 110px;
                font-size: {FONT['label']}pt;
            }}
            QTabBar::tab:selected {{
                background: {PALETTE.get('bg','#242424')};
                color: {PALETTE.get('accent','#00d4aa')};
                border-bottom-color: {PALETTE.get('bg','#242424')};
            }}
            QTabBar::tab:hover:!selected {{ color: {PALETTE.get('textSub','#6a6a6a')}; background: {PALETTE.get('surface','#2d2d2d')}; }}
        """)

        # Live / final ΔR/R
        drr_wrapper = QWidget()
        dw = QVBoxLayout(drr_wrapper)
        dw.setContentsMargins(4, 4, 4, 4)

        cmap_row = QHBoxLayout()
        cmap_row.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        self._cmap_combo.currentTextChanged.connect(self._redisplay)
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        self._grid_chk = QCheckBox("Show tile grid")
        self._grid_chk.setChecked(True)
        self._grid_chk.stateChanged.connect(
            lambda s: self._map_drr.set_grid_visible(s == Qt.Checked))
        cmap_row.addWidget(self._cmap_combo)
        cmap_row.addSpacing(12)
        cmap_row.addWidget(self._grid_chk)
        cmap_row.addStretch()
        dw.addLayout(cmap_row)

        self._map_drr = ScanMapView()
        self._map_drr.context_save_image.connect(
            lambda: self._save_map_ctx(self._map_drr))
        dw.addWidget(self._map_drr)

        self._map_dt  = ScanMapView()
        self._map_dt.set_title("ΔT (°C)  — requires calibration")
        self._map_dt.context_save_image.connect(
            lambda: self._save_map_ctx(self._map_dt))

        result_tabs.addTab(drr_wrapper,  " ΔR/R Map ")
        result_tabs.addTab(self._map_dt, " ΔT Map ")
        lay.addWidget(result_tabs, 1)

        # ---- Export buttons ----
        btn_row = QHBoxLayout()
        self._save_map_btn  = QPushButton("Save Map (.npy)")
        set_btn_icon(self._save_map_btn, "fa5s.save")
        self._save_img_btn  = QPushButton("Save Image (.png)")
        set_btn_icon(self._save_img_btn, "fa5s.image")
        self._report_btn    = QPushButton("PDF Report")
        set_btn_icon(self._report_btn, "fa5s.file-pdf")
        self._save_prof_btn = QPushButton("Save as Profile")
        set_btn_icon(self._save_prof_btn, "fa5s.layer-group")
        self._report_btn.setObjectName("primary")
        for b in [self._save_map_btn, self._save_img_btn,
                  self._report_btn, self._save_prof_btn]:
            b.setFixedHeight(30)
            b.setEnabled(False)
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._save_map_btn.clicked.connect(self._save_map)
        self._save_img_btn.clicked.connect(self._save_img)
        self._report_btn.clicked.connect(self._gen_report)
        self._save_prof_btn.clicked.connect(self._save_as_profile)

        return w

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def set_grid_from_profile(self, step_um: float, overlap_pct: float) -> None:
        """Apply grid scan defaults from a material profile."""
        if step_um > 0:
            self._step_x.setValue(step_um)
            self._step_y.setValue(step_um)

    def update_progress(self, prog: ScanProgress):
        n   = prog.total_tiles or 1
        pct = int(prog.tile / n * 100)
        self._progress.setValue(pct)

        state_labels = {
            "moving":   "→ Moving",  "settling": "⏳ Settling",
            "acquiring":"📷 Capturing","stitching":"⚙ Stitching",
            "complete": "✓ Complete", "error":    "✗ Error",
            "aborted":  "■ Aborted",
        }
        state_str = state_labels.get(prog.state, prog.state.capitalize())
        self._tile_lbl.setText(prog.message)
        self._stat_fields["tiles"]._val.setText(
            f"{prog.tile}/{prog.total_tiles}")
        self._stat_fields["state"]._val.setText(state_str)
        color = ("#00d4aa" if prog.state == "complete" else
                 "#ff6666" if prog.state in ("error", "aborted") else "#ffaa44")
        self._stat_fields["state"]._val.setStyleSheet(
            scaled_qss(f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:15pt; color:{color};"))

        self._log.append(
            f"<span style='color:#444'>"
            f"[{time.strftime('%H:%M:%S')}]</span>  {prog.message}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())

        if prog.partial_map is not None:
            cfg  = self._build_cfg()
            cmap = self._cmap_combo.currentText()
            self._map_drr.update_map(
                prog.partial_map,
                cfg["n_cols"], cfg["n_rows"],
                cfg["step_x_um"], cfg["step_y_um"],
                cmap=cmap)

    def update_complete(self, result: ScanResult):
        self._result = result
        self._btn_runner.set_running(False)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)

        if not result.valid:
            return

        cfg  = self._build_cfg()
        cmap = self._cmap_combo.currentText()
        self._map_drr.update_map(
            result.drr_map,
            result.n_cols, result.n_rows,
            result.step_x_um, result.step_y_um,
            cmap=cmap)

        if result.dt_map is not None:
            self._map_dt.update_map(
                result.dt_map,
                result.n_cols, result.n_rows,
                result.step_x_um, result.step_y_um,
                cmap="Thermal Delta")

        H, W = result.drr_map.shape[:2]
        fov_x = result.n_cols * result.step_x_um
        fov_y = result.n_rows * result.step_y_um
        self._stat_fields["size"]._val.setText(f"{W}×{H} px")
        self._stat_fields["fov"]._val.setText(
            f"{fov_x:.0f}×{fov_y:.0f} μm")
        self._stat_fields["elapsed"]._val.setText(
            f"{result.duration_s:.0f} s")
        self._progress.setValue(100)

        for b in [self._save_map_btn, self._save_img_btn, self._report_btn, self._save_prof_btn]:
            b.setEnabled(True)

    def apply_config(self, cfg: dict) -> None:
        """Pre-fill grid config from an AutoScan config dict."""
        if "n_cols"    in cfg: self._n_cols.setValue(int(cfg["n_cols"]))
        if "n_rows"    in cfg: self._n_rows.setValue(int(cfg["n_rows"]))
        if "step_x_um" in cfg: self._step_x.setValue(float(cfg["step_x_um"]))
        if "step_y_um" in cfg: self._step_y.setValue(float(cfg["step_y_um"]))
        if "settle_s"  in cfg: self._settle.setValue(float(cfg["settle_s"]))
        if "n_frames"  in cfg: self._n_frames.setValue(int(cfg["n_frames"]))

    # ---------------------------------------------------------------- #
    #  Run / Abort                                                     #
    # ---------------------------------------------------------------- #

    def _run(self):
        from .scan import ScanEngine
        import threading

        try:
            from hardware.app_state import app_state
            _stage    = app_state.stage
            _tecs     = app_state.tecs
            _cal      = app_state.active_calibration
            if app_state.demo_mode:
                # Use synthetic tiles so the demo map shows visible signal
                _cam      = None
                _pipeline = None
            else:
                _cam      = app_state.cam
                _pipeline = app_state.pipeline
        except Exception:
            _stage = _cam = _pipeline = None
            _tecs  = []
            _cal   = None

        cfg = self._build_cfg()
        self._runner = ScanEngine(_stage, _cam, _tecs, _pipeline, cfg, _cal)

        try:
            from ui.app_signals import signals
            self._runner.on_progress = \
                lambda p: signals.scan_progress.emit(p)
            self._runner.on_complete = \
                lambda r: signals.scan_complete.emit(r)
        except Exception:
            pass

        # Update stats preview
        n = cfg["n_cols"] * cfg["n_rows"]
        self._stat_fields["tiles"]._val.setText(f"0/{n}")
        self._stat_fields["state"]._val.setText("Running…")
        fov_x = cfg["n_cols"] * cfg["step_x_um"]
        fov_y = cfg["n_rows"] * cfg["step_y_um"]
        self._stat_fields["fov"]._val.setText(
            f"{fov_x:.0f}×{fov_y:.0f} μm")

        self._btn_runner.set_running(True, "Scanning")
        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._progress.setValue(0)
        self._log.clear()
        for b in [self._save_map_btn, self._save_img_btn, self._report_btn, self._save_prof_btn]:
            b.setEnabled(False)

        threading.Thread(target=self._runner.run, daemon=True).start()

    def _abort(self):
        if self._runner:
            self._runner.abort()

    # ---------------------------------------------------------------- #
    #  Export                                                          #
    # ---------------------------------------------------------------- #

    def _save_map(self):
        if not (self._result and self._result.valid):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ΔR/R Map", "scan_drr.npy",
            "NumPy files (*.npy);;All files (*)")
        if path:
            np.save(path, self._result.drr_map)
            if self._result.dt_map is not None:
                dt_path = path.replace(".npy", "_dt.npy")
                np.save(dt_path, self._result.dt_map)
            QMessageBox.information(self, "Saved", f"Map saved to:\n{path}")

    def _save_img(self):
        if not (self._result and self._result.valid):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Map Image", "scan_map.png",
            "PNG images (*.png);;All files (*)")
        if path:
            self._map_drr.save_image(path)
            QMessageBox.information(self, "Saved", f"Image saved to:\n{path}")

    def _save_map_ctx(self, view: ScanMapView):
        """Context-menu 'Save Map Image…' — save whichever map view was right-clicked."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Map Image", "scan_map.png",
            "PNG images (*.png);;All files (*)")
        if path:
            view.save_image(path)

    def _gen_report(self):
        if not (self._result and self._result.valid):
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Save Scan Report To", ".")
        if not out_dir:
            return
        try:
            from .report       import generate_report
            from .session      import Session, SessionMeta
            from hardware.app_state import app_state
            cal = app_state.active_calibration

            # Wrap ScanResult in a minimal Session for the report engine
            class _FakeResult:
                cold_avg       = None
                hot_avg        = None
                difference     = None
                delta_r_over_r = self._result.drr_map
                snr_db         = None
                n_frames       = self._build_cfg()["n_frames"]
                exposure_us    = 0.0
                gain_db        = 0.0
                duration_s     = self._result.duration_s
                notes          = (f"Scan: {self._result.n_cols}×"
                                  f"{self._result.n_rows} tiles  "
                                  f"step {self._result.step_x_um:.0f}×"
                                  f"{self._result.step_y_um:.0f} μm")
                roi            = None

            session = Session.from_result(_FakeResult(), label="scan_map")
            session._delta_r_over_r = self._result.drr_map
            session._delta_t        = self._result.dt_map

            assets = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "assets", "microsanj-logo.svg")
            pdf = generate_report(session, out_dir, cal, assets)
            QMessageBox.information(
                self, "Report Generated", f"Saved to:\n{pdf}")
        except Exception as e:
            QMessageBox.critical(self, "Report Failed", str(e))

    # ---------------------------------------------------------------- #
    #  Helpers                                                         #
    # ---------------------------------------------------------------- #

    def _save_as_profile(self):
        """Capture current scan + camera settings into a new user profile."""
        from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
        from PyQt5.QtWidgets import QDoubleSpinBox as _DSB, QComboBox as _CB
        from profiles.profiles import (CATEGORY_SEMICONDUCTOR, CATEGORY_PCB,
                                        CATEGORY_AUTOMOTIVE, CATEGORY_METAL,
                                        CATEGORY_USER)

        # Gather current settings
        cfg = self._build_cfg()
        try:
            from hardware.app_state import app_state
            exp  = app_state.cam.get_status().exposure_us if app_state.cam else 5000.0
            gain = app_state.cam.get_status().gain_db     if app_state.cam else 0.0
            cal  = app_state.active_calibration
            ct   = float(cal.ct_map.mean()) if (cal and cal.valid) else 1.5e-4
        except Exception:
            exp, gain, ct = 5000.0, 0.0, 1.5e-4

        # Quick-entry dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Save as Profile")
        dlg.setMinimumWidth(380)
        fl = QFormLayout(dlg)
        fl.setSpacing(8)

        name_edit = QLineEdit("My Scan Profile")
        mat_edit  = QLineEdit("")
        cat_cb    = _CB()
        for c in [CATEGORY_SEMICONDUCTOR, CATEGORY_PCB,
                  CATEGORY_AUTOMOTIVE, CATEGORY_METAL, CATEGORY_USER]:
            cat_cb.addItem(c)
        ct_spin = _DSB()
        ct_spin.setDecimals(3); ct_spin.setRange(1e-6, 1e-2)
        ct_spin.setValue(ct);   ct_spin.setSingleStep(1e-5)
        desc_edit = QLineEdit("")
        notes_edit = QLineEdit(
            f"Scan: {cfg['n_cols']}×{cfg['n_rows']} tiles  "
            f"step {cfg['step_x_um']:.0f}×{cfg['step_y_um']:.0f} μm")

        fl.addRow("Profile name", name_edit)
        fl.addRow("Material",     mat_edit)
        fl.addRow("Category",     cat_cb)
        fl.addRow("C_T value",    ct_spin)
        fl.addRow("Description",  desc_edit)
        fl.addRow("Notes",        notes_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        try:
            from hardware.app_state import app_state
            app_state._window._profile_tab.save_from_settings(
                name         = name_edit.text().strip() or "Scan Profile",
                material     = mat_edit.text().strip(),
                category     = cat_cb.currentText(),
                ct_value     = ct_spin.value(),
                exposure_us  = exp,
                gain_db      = gain,
                n_frames     = cfg["n_frames"],
                accumulation = 20,
                dt_range_k   = 10.0,
                description  = desc_edit.text().strip(),
                notes        = notes_edit.text().strip(),
            )
            QMessageBox.information(self, "Profile Saved",
                "Profile saved to your library.\n"
                "Find it in the PROFILES tab under 'User Defined'.")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def _build_cfg(self) -> dict:
        return {
            "n_cols":    self._n_cols.value(),
            "n_rows":    self._n_rows.value(),
            "step_x_um": self._step_x.value(),
            "step_y_um": self._step_y.value(),
            "settle_s":  self._settle.value(),
            "n_frames":  self._n_frames.value(),
            "snake":     self._snake.isChecked(),
        }

    def _update_summary(self):
        nc = self._n_cols.value()
        nr = self._n_rows.value()
        sx = self._step_x.value()
        sy = self._step_y.value()
        nf = self._n_frames.value()
        self._summary_lbl.setText(
            f"{nc}×{nr} = {nc*nr} tiles  ·  "
            f"FOV {nc*sx:.0f}×{nr*sy:.0f} μm  ·  "
            f"{nf} frames/tile")
        self._update_time_estimate()

    def _update_time_estimate(self):
        _STAGE_OVERHEAD_S = 0.3
        n_tiles    = self._n_cols.value() * self._n_rows.value()
        settle_s   = self._settle.value()
        n_frames   = self._n_frames.value()

        try:
            from hardware.app_state import app_state
            fps = getattr(getattr(app_state.cam, 'info', None),
                          'max_fps', 30)
        except Exception:
            fps = 30

        fps = max(fps, 1)
        est = n_tiles * (settle_s + n_frames / fps + _STAGE_OVERHEAD_S)
        detail = (f"{n_tiles} tiles × ({settle_s:.1f} s settle"
                  f" + {n_frames} frames @ {fps} fps + 0.3 s move)")
        self._time_est_lbl.set_estimate(est, detail)

    def _redisplay(self):
        if self._result and self._result.valid:
            cfg  = self._build_cfg()
            cmap = self._cmap_combo.currentText()
            self._map_drr.update_map(
                self._result.drr_map,
                self._result.n_cols, self._result.n_rows,
                self._result.step_x_um, self._result.step_y_um,
                cmap=cmap)

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
