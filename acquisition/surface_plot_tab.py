"""
acquisition/surface_plot_tab.py

3D Thermal Surface Plot for the Microsanj Thermal Analysis System.

Features
--------
  • Interactive 3D surface rendering of any loaded 2D numpy array
    (ΔR/R, ΔT, difference, calibration C_T map …)
  • Elevation and azimuth controls + "Auto-rotate" animation
  • Colormap selector (matches the 2D map panel)
  • Vertical scale (Z-stretch) slider to exaggerate small variations
  • Threshold plane — horizontal plane drawn at a user-set value so
    hot-spots above threshold are immediately obvious
  • Export to PNG / PDF

Integration
-----------
    from acquisition.surface_plot_tab import SurfacePlotTab

    # Anywhere you have a numpy array from a session:
    self._surface_tab.set_data(session.delta_r_over_r, title="ΔR/R surface")
"""

from __future__ import annotations

import logging
import numpy as np
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QComboBox, QGroupBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QSizePolicy, QSplitter, QFrame, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer
from ui.icons import set_btn_icon
from ui.widgets.detach_helpers import DetachableFrame, open_detached_viewer
from ui.theme import FONT, PALETTE, scaled_qss
from .processing import (COLORMAP_OPTIONS, COLORMAP_TOOLTIPS,
                         setup_cmap_combo, get_mpl_cmap_name)
import config as cfg_mod

import matplotlib
if matplotlib.get_backend().lower() in ("", "agg"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from mpl_toolkits.mplot3d import Axes3D   # noqa: F401 — registers 3D projection

log = logging.getLogger(__name__)


class SurfacePlotTab(QWidget):
    """
    3D thermal surface plot panel.

    Call ``set_data(array, title='...')`` to update the surface.
    The panel can also be embedded stand-alone inside any QWidget layout.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arr:       Optional[np.ndarray] = None
        self._title:     str  = "ΔR/R Surface"
        self._azimuth:   float = 225.0
        self._elevation: float = 35.0
        self._rotate_timer = QTimer(self)
        self._rotate_timer.setInterval(50)   # 20 fps
        self._rotate_timer.timeout.connect(self._auto_rotate_step)
        self._build()

    # ── UI ──────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ─ Toolbar (always visible) ─
        toolbar = QHBoxLayout()
        root.addLayout(toolbar)

        # Colormap
        toolbar.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setFixedHeight(28)
        self._cmap_combo.setMinimumWidth(160)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Emberline")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        self._cmap_combo.currentTextChanged.connect(self._replot)
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        toolbar.addWidget(self._cmap_combo)

        toolbar.addWidget(QLabel("  Z-stretch:"))
        self._z_spin = QDoubleSpinBox()
        self._z_spin.setRange(1.0, 200.0)
        self._z_spin.setValue(10.0)
        self._z_spin.setSingleStep(1.0)
        self._z_spin.setFixedHeight(28)
        self._z_spin.setToolTip("Vertical exaggeration — increase to see small ΔT variations")
        self._z_spin.valueChanged.connect(self._replot)
        toolbar.addWidget(self._z_spin)

        # Threshold plane
        self._thresh_cb = QCheckBox("Show threshold plane")
        self._thresh_cb.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        self._thresh_cb.stateChanged.connect(self._replot)
        toolbar.addWidget(self._thresh_cb)

        self._thresh_spin = QDoubleSpinBox()
        self._thresh_spin.setRange(-1e6, 1e6)
        self._thresh_spin.setValue(0.01)
        self._thresh_spin.setDecimals(5)
        self._thresh_spin.setSingleStep(0.001)
        self._thresh_spin.setFixedHeight(28)
        self._thresh_spin.setFixedWidth(100)
        self._thresh_spin.valueChanged.connect(self._replot)
        toolbar.addWidget(self._thresh_spin)

        toolbar.addStretch(1)

        self._rotate_btn = QPushButton("Auto-rotate")
        set_btn_icon(self._rotate_btn, "fa5s.sync-alt")
        self._rotate_btn.setFixedHeight(28)
        self._rotate_btn.setCheckable(True)
        self._rotate_btn.toggled.connect(self._toggle_rotate)
        toolbar.addWidget(self._rotate_btn)

        self._export_btn = QPushButton("Export…")
        self._export_btn.setFixedHeight(28)
        self._export_btn.clicked.connect(self._export)
        toolbar.addWidget(self._export_btn)

        # ─ Stacked widget: page 0 = empty state, page 1 = content ─
        self._data_stack = QStackedWidget()
        self._data_stack.addWidget(self._build_empty_state(
            icon="⛰",
            title="No Surface Data",
            desc="Run an acquisition and the 3D thermal surface will appear here "
                 "automatically. You can also load data from the Analysis tab.",
        ))
        self._data_stack.addWidget(self._build_content_widget())
        self._data_stack.setCurrentIndex(0)
        root.addWidget(self._data_stack, 1)

        # ─ Status ─
        self._status_lbl = QLabel("No data loaded — call set_data() to display a surface.")
        self._status_lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt; padding:2px 4px;")
        root.addWidget(self._status_lbl)

        # Apply label styling to toolbar labels
        for lbl in toolbar.parentWidget().findChildren(QLabel) if toolbar.parentWidget() else []:
            if not lbl.styleSheet():
                lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")

    def _build_empty_state(self, icon, title, desc, btn_text="", btn_callback=None):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(scaled_qss(f"font-size: 52pt; color: {PALETTE['border']};"))

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(f"font-size: {FONT['readoutSm']}pt; font-weight: bold; color: {PALETTE['textSub']};")

        desc_lbl = QLabel(desc)
        desc_lbl.setAlignment(Qt.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: {PALETTE['textSub']};")
        desc_lbl.setMaximumWidth(450)

        lay.addStretch()
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addWidget(desc_lbl)

        if btn_text and btn_callback:
            btn = QPushButton(btn_text)
            btn.setFixedWidth(200)
            btn.setFixedHeight(36)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {PALETTE['accentDim']}; color: {PALETTE['accent']};
                    border: 1px solid {PALETTE['accent']}55; border-radius: 5px;
                    font-size: {FONT['label']}pt; font-weight: 600;
                }}
                QPushButton:hover {{ background: {PALETTE['accentDim']}; }}
            """)
            btn.clicked.connect(btn_callback)
            lay.addSpacing(4)
            lay.addWidget(btn, 0, Qt.AlignCenter)

        lay.addStretch()
        return w

    def _build_content_widget(self) -> QWidget:
        """Build the matplotlib canvas + view-angle sliders content widget."""
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ─ Matplotlib canvas ─
        self._fig  = Figure(figsize=(8, 5), facecolor=PALETTE['canvas'], tight_layout=True)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas_frame = DetachableFrame(self._canvas)
        self._canvas_frame.detach_requested.connect(self._on_detach_canvas)
        lay.addWidget(self._canvas_frame, 1)

        # ─ View-angle sliders ─
        angle_row = QHBoxLayout()
        lay.addLayout(angle_row)

        el_lbl = QLabel("Elevation:")
        el_lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        angle_row.addWidget(el_lbl)
        self._el_slider = QSlider(Qt.Horizontal)
        self._el_slider.setRange(-90, 90)
        self._el_slider.setValue(35)
        self._el_slider.valueChanged.connect(self._on_elevation)
        angle_row.addWidget(self._el_slider)

        az_lbl = QLabel("  Azimuth:")
        az_lbl.setStyleSheet(f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        angle_row.addWidget(az_lbl)
        self._az_slider = QSlider(Qt.Horizontal)
        self._az_slider.setRange(0, 359)
        self._az_slider.setValue(225)
        self._az_slider.valueChanged.connect(self._on_azimuth)
        angle_row.addWidget(self._az_slider)

        self._replot()
        return content

    # ── Detached viewer ────────────────────────────────────────────

    _detached_surface = None

    def _on_detach_canvas(self) -> None:
        """Open a detached viewer for the 3D surface plot."""
        def _push(viewer):
            pix = self._canvas.grab()
            if pix is not None and not pix.isNull():
                viewer.update_image(pix, self._title)

        open_detached_viewer(
            self, "_detached_surface",
            source_id="surface.3d",
            title="3D Surface",
            initial_push=_push,
            static=True)

    # ── Public API ──────────────────────────────────────────────────

    def set_data(self, arr: Optional[np.ndarray], title: str = ""):
        """Update the surface with a new 2D float array.

        Args:
            arr:   2D numpy array (H × W).  Pass None to clear.
            title: Plot title string.
        """
        if arr is not None and arr.ndim != 2:
            log.warning("SurfacePlotTab.set_data: expected 2D array, got shape %s", arr.shape)
            return
        self._arr   = None if arr is None else arr.astype(np.float32)
        self._title = title or self._title
        self._status_lbl.setText(
            f"Array: {arr.shape[0]}×{arr.shape[1]}  "
            f"min={np.nanmin(arr):.5g}  max={np.nanmax(arr):.5g}"
            if arr is not None else "No data loaded."
        )
        if arr is not None:
            self._data_stack.setCurrentIndex(1)
        self._replot()

    # ── Plotting ────────────────────────────────────────────────────

    def _replot(self):
        self._fig.clear()
        ax = self._fig.add_subplot(111, projection="3d")
        ax.set_facecolor(PALETTE['bg'])
        self._fig.patch.set_facecolor(PALETTE['canvas'])

        # Label styling
        for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
            pane.fill = False
            pane.set_edgecolor(PALETTE['border'])
        ax.tick_params(colors=PALETTE['textDim'], labelsize=7)
        ax.xaxis.label.set_color(PALETTE['textDim'])
        ax.yaxis.label.set_color(PALETTE['textDim'])
        ax.zaxis.label.set_color(PALETTE['textDim'])
        ax.set_xlabel("X  (pixels)", labelpad=2)
        ax.set_ylabel("Y  (pixels)", labelpad=2)
        ax.set_zlabel("ΔR/R", labelpad=2)
        ax.set_title(self._title, color=PALETTE['text'], fontsize=9, pad=6)
        ax.view_init(elev=self._elevation, azim=self._azimuth)

        if self._arr is not None:
            arr = self._arr
            H, W = arr.shape

            # Downsample for performance if the array is large
            step = max(1, max(H, W) // 128)
            arr_ds = arr[::step, ::step]
            H2, W2 = arr_ds.shape

            X = np.linspace(0, W - 1, W2)
            Y = np.linspace(0, H - 1, H2)
            X, Y = np.meshgrid(X, Y)

            z_stretch  = self._z_spin.value()
            cmap_name  = get_mpl_cmap_name(self._cmap_combo.currentText())

            # Apply Z-stretch (vertical exaggeration around centre)
            z_min = float(np.nanmin(arr_ds))
            z_max = float(np.nanmax(arr_ds))
            z_range = max(z_max - z_min, 1e-12)
            z_center  = (z_min + z_max) * 0.5
            arr_plot  = z_center + (arr_ds - z_center) * z_stretch

            surf = ax.plot_surface(
                X, Y, arr_plot,
                cmap=cmap_name,
                linewidth=0,
                antialiased=True,
                alpha=0.92,
            )
            self._fig.colorbar(surf, ax=ax, shrink=0.5, aspect=12, pad=0.1)

            # Threshold plane (draw in stretched Z space)
            if self._thresh_cb.isChecked():
                t = float(self._thresh_spin.value())
                if z_min <= t <= z_max:
                    t_stretched = z_center + (t - z_center) * z_stretch
                    xx = np.array([[0, W - 1], [0, W - 1]])
                    yy = np.array([[0, 0], [H - 1, H - 1]])
                    zz = np.full_like(xx, t_stretched, dtype=float)
                    ax.plot_surface(xx, yy, zz, alpha=0.25, color=PALETTE['danger'])
                    ax.text(W * 0.05, H * 0.05, t_stretched,
                            f"threshold={t:.4g}", color=PALETTE['danger'], fontsize=7)

        self._canvas.draw()

    # ── Controls ────────────────────────────────────────────────────

    def _on_elevation(self, val: int):
        self._elevation = float(val)
        self._replot()

    def _on_azimuth(self, val: int):
        self._azimuth = float(val)
        self._replot()

    def _toggle_rotate(self, checked: bool):
        if checked:
            self._rotate_btn.setText("Auto-rotate")
            self._rotate_timer.start()
        else:
            self._rotate_btn.setText("Auto-rotate")
            self._rotate_timer.stop()

    def _auto_rotate_step(self):
        self._azimuth = (self._azimuth + 1.5) % 360
        self._az_slider.blockSignals(True)
        self._az_slider.setValue(int(self._azimuth))
        self._az_slider.blockSignals(False)
        self._replot()

    # ── Export ──────────────────────────────────────────────────────

    def _apply_styles(self):
        """Refresh inline stylesheets from the current PALETTE values."""
        self._status_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt; padding:2px 4px;")
        self._thresh_cb.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt;")
        # Re-set matplotlib figure background colors and re-render
        self._fig.patch.set_facecolor(PALETTE['canvas'])
        self._replot()

    def _export(self):
        if self._arr is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export 3D Surface Plot",
            str(Path.home() / "surface_plot.png"),
            "PNG Image (*.png);;PDF Document (*.pdf)"
        )
        if not path:
            return
        try:
            self._fig.savefig(path, dpi=200, bbox_inches="tight",
                              facecolor=self._fig.get_facecolor())
            self._status_lbl.setText(f"Exported → {path}")
        except Exception as e:
            log.error("Surface export failed: %s", e)
