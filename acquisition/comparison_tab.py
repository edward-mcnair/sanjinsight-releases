"""
acquisition/comparison_tab.py

Session Comparison View for the Microsanj Thermal Analysis System.

Features
--------
  • Load any two saved sessions from disk
  • Side-by-side ΔR/R (or ΔT) maps with shared colormap and synchronized
    zoom / pan
  • Difference map  (B − A) with diverging (blue-white-red) colormap
  • Statistical comparison table: peak, mean, RMS, hotspot count, etc.
  • "Blink" toggle that rapidly alternates between session A and B so
    changes become immediately visible
  • Export: save the three-panel figure as a PNG or PDF

Usage (Advanced tab)
--------------------
    from acquisition.comparison_tab import ComparisonTab
    tab = ComparisonTab(session_manager)
    self._tabs.addTab(tab, "Compare")
"""

from __future__ import annotations

import os
import logging
import numpy as np
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QGroupBox, QCheckBox, QSlider,
    QMessageBox, QComboBox, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap, QColor
from ui.icons import set_btn_icon

import matplotlib
if matplotlib.get_backend().lower() in ("", "agg"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize, TwoSlopeNorm
from io import BytesIO

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Tiny helper — numpy array → QPixmap via matplotlib colormap        #
# ------------------------------------------------------------------ #

def _array_to_pixmap(arr: np.ndarray,
                     cmap: str = "inferno",
                     vmin: float = None,
                     vmax: float = None,
                     width: int = 480,
                     height: int = 360) -> QPixmap:
    """Render a 2D float32 array as a colormapped QPixmap."""
    if arr is None or arr.ndim != 2:
        pm = QPixmap(width, height)
        pm.fill(QColor("#1a1a1a"))
        return pm

    v_lo = float(vmin if vmin is not None else np.nanmin(arr))
    v_hi = float(vmax if vmax is not None else np.nanmax(arr))
    if v_lo == v_hi:
        v_hi = v_lo + 1e-9

    colormap = cm.get_cmap(cmap)
    normed   = np.clip((arr - v_lo) / (v_hi - v_lo), 0.0, 1.0)
    rgba     = (colormap(normed) * 255).astype(np.uint8)   # H×W×4
    h, w     = rgba.shape[:2]
    qimg     = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888)
    pm       = QPixmap.fromImage(qimg)
    return pm.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ------------------------------------------------------------------ #
#  MapPanel — a single colormapped image pane with title + scale bar  #
# ------------------------------------------------------------------ #

class _MapPanel(QFrame):
    """Displays one colormapped 2D array with a title and value range label."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("background:#111; border:1px solid #2a2a2a; border-radius:4px;")
        self._title_str = title
        self._arr: Optional[np.ndarray] = None
        self._cmap = "inferno"
        self._vmin = None
        self._vmax = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._title_lbl = QLabel(self._title_str)
        self._title_lbl.setStyleSheet(
            "color:#ddd; font-size:14pt; font-weight:600; font-family:Menlo,monospace;")
        self._title_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._title_lbl)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignCenter)
        self._img_lbl.setMinimumSize(320, 240)
        self._img_lbl.setStyleSheet("background:#1a1a1a;")
        lay.addWidget(self._img_lbl, 1)

        self._range_lbl = QLabel("—")
        self._range_lbl.setAlignment(Qt.AlignCenter)
        self._range_lbl.setStyleSheet("color:#888; font-size:12pt; font-family:Menlo,monospace;")
        lay.addWidget(self._range_lbl)

    def set_data(self, arr: Optional[np.ndarray],
                 cmap: str = "inferno",
                 vmin: float = None,
                 vmax: float = None,
                 title: str = None):
        self._arr  = arr
        self._cmap = cmap
        self._vmin = vmin
        self._vmax = vmax
        if title:
            self._title_lbl.setText(title)
            self._title_str = title
        self._refresh()

    def _refresh(self):
        sz   = self._img_lbl.size()
        w, h = max(sz.width(), 320), max(sz.height(), 240)
        pm   = _array_to_pixmap(self._arr, self._cmap, self._vmin, self._vmax, w, h)
        self._img_lbl.setPixmap(pm)

        if self._arr is not None:
            lo = np.nanmin(self._arr)
            hi = np.nanmax(self._arr)
            self._range_lbl.setText(f"min {lo:.4g}  ·  max {hi:.4g}")
        else:
            self._range_lbl.setText("—")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def clear(self):
        self._arr = None
        self._refresh()
        self._range_lbl.setText("—")


# ------------------------------------------------------------------ #
#  Stats comparison table                                              #
# ------------------------------------------------------------------ #

class _StatsTable(QTableWidget):
    _METRICS = [
        ("Peak value",     lambda a: f"{np.nanmax(a):.5g}"),
        ("Mean value",     lambda a: f"{np.nanmean(a):.5g}"),
        ("RMS value",      lambda a: f"{np.sqrt(np.nanmean(a**2)):.5g}"),
        ("Std deviation",  lambda a: f"{np.nanstd(a):.5g}"),
        ("Median",         lambda a: f"{np.nanmedian(a):.5g}"),
        ("Negative pixels",lambda a: f"{int(np.sum(a < 0)):,}"),
        ("Positive pixels",lambda a: f"{int(np.sum(a > 0)):,}"),
        ("Shape",          lambda a: f"{a.shape[0]} × {a.shape[1]}"),
    ]

    def __init__(self, parent=None):
        super().__init__(len(self._METRICS), 3, parent)
        self.setHorizontalHeaderLabels(["Metric", "Session A", "Session B"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.verticalHeader().hide()
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QTableWidget { background:#141414; color:#ccc; font-size:12pt;
                           font-family:Menlo,monospace; gridline-color:#222; }
            QHeaderView::section { background:#1e1e1e; color:#aaa; font-size:12pt;
                                   padding: 4px 16px 4px 8px; }
            QTableWidget::item:alternate { background:#191919; }
        """)
        for r, (name, _) in enumerate(self._METRICS):
            item = QTableWidgetItem(name)
            item.setForeground(QColor("#aaa"))
            self.setItem(r, 0, item)
        self._clear_col(1)
        self._clear_col(2)

    def _clear_col(self, col: int):
        for r in range(self.rowCount()):
            self.setItem(r, col, QTableWidgetItem("—"))

    def update_session(self, col: int, arr: Optional[np.ndarray]):
        if arr is None or arr.ndim != 2:
            self._clear_col(col)
            return
        for r, (_, fn) in enumerate(self._METRICS):
            try:
                val = fn(arr)
            except Exception:
                val = "err"
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            self.setItem(r, col, item)


# ------------------------------------------------------------------ #
#  ComparisonTab — main widget                                         #
# ------------------------------------------------------------------ #

class ComparisonTab(QWidget):
    """
    Side-by-side session comparison panel.

    session_manager: SessionManager instance (used for folder discovery)
    """

    def __init__(self, session_manager=None, parent=None):
        super().__init__(parent)
        self._sm   = session_manager
        self._arrA: Optional[np.ndarray] = None
        self._arrB: Optional[np.ndarray] = None
        self._pathA: Optional[str] = None
        self._pathB: Optional[str] = None
        self._blink_state = False
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._build()

    # ── UI construction ─────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ─ Toolbar (always visible) ─
        toolbar = QHBoxLayout()
        root.addLayout(toolbar)

        self._load_a_btn = QPushButton("Load Session A…")
        self._load_b_btn = QPushButton("Load Session B…")
        self._load_a_btn.setFixedHeight(28)
        self._load_b_btn.setFixedHeight(28)
        self._load_a_btn.clicked.connect(lambda: self._load_session("A"))
        self._load_b_btn.clicked.connect(lambda: self._load_session("B"))

        self._array_combo = QComboBox()
        self._array_combo.addItems(["ΔR/R (raw signal)", "Difference (hot−cold)", "Cold avg", "Hot avg"])
        self._array_combo.currentIndexChanged.connect(self._refresh_maps)
        self._array_combo.setFixedHeight(28)

        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(["inferno", "hot", "plasma", "viridis", "RdBu_r", "bwr"])
        self._cmap_combo.currentIndexChanged.connect(self._refresh_maps)
        self._cmap_combo.setFixedHeight(28)

        self._blink_btn = QPushButton("Blink")
        set_btn_icon(self._blink_btn, "fa5s.eye")
        self._blink_btn.setFixedHeight(28)
        self._blink_btn.setCheckable(True)
        self._blink_btn.toggled.connect(self._toggle_blink)

        self._export_btn = QPushButton("Export Figure…")
        set_btn_icon(self._export_btn, "fa5s.file-export")
        self._export_btn.setFixedHeight(28)
        self._export_btn.clicked.connect(self._export_figure)

        for w in [self._load_a_btn, self._load_b_btn,
                  QLabel("Array:"), self._array_combo,
                  QLabel("Colormap:"), self._cmap_combo,
                  self._blink_btn, self._export_btn]:
            if isinstance(w, QLabel):
                w.setStyleSheet("color:#aaa; font-size:12pt;")
            toolbar.addWidget(w)
        toolbar.addStretch(1)

        # ─ Stacked widget: page 0 = empty state, page 1 = content ─
        self._data_stack = QStackedWidget()
        self._data_stack.addWidget(self._build_empty_state(
            icon="⇔",
            title="No Sessions to Compare",
            desc="Load two saved acquisition sessions from disk to compare them "
                 "side-by-side. Save sessions from the Analysis tab after running "
                 "an acquisition.",
            btn_text="Load Session A",
            btn_callback=lambda: self._load_session("A"),
        ))
        self._data_stack.addWidget(self._build_content_widget())
        self._data_stack.setCurrentIndex(0)
        root.addWidget(self._data_stack, 1)

        # ─ Status bar ─
        self._status_lbl = QLabel("Load two sessions to compare.")
        self._status_lbl.setStyleSheet("color:#888; font-size:12pt; padding:2px 4px;")
        root.addWidget(self._status_lbl)

    def _build_empty_state(self, icon, title, desc, btn_text="", btn_callback=None):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 52pt; color: #2a2a2a;")

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("font-size: 16pt; font-weight: bold; color: #555;")

        desc_lbl = QLabel(desc)
        desc_lbl.setAlignment(Qt.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12pt; color: #444;")
        desc_lbl.setMaximumWidth(450)

        lay.addStretch()
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addWidget(desc_lbl)

        if btn_text and btn_callback:
            btn = QPushButton(btn_text)
            btn.setFixedWidth(200)
            btn.setFixedHeight(36)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1a2a20; color: #00d4aa;
                    border: 1px solid #00d4aa55; border-radius: 5px;
                    font-size: 12pt; font-weight: 600;
                }
                QPushButton:hover { background: #1e3028; }
            """)
            btn.clicked.connect(btn_callback)
            lay.addSpacing(4)
            lay.addWidget(btn, 0, Qt.AlignCenter)

        lay.addStretch()
        return w

    def _build_content_widget(self) -> QWidget:
        """Build the main comparison content (maps + stats table)."""
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ─ Three map panels ─
        maps_split = QSplitter(Qt.Horizontal)

        self._panel_a    = _MapPanel("Session A")
        self._panel_b    = _MapPanel("Session B")
        self._panel_diff = _MapPanel("Difference  (B − A)")

        maps_split.addWidget(self._panel_a)
        maps_split.addWidget(self._panel_b)
        maps_split.addWidget(self._panel_diff)
        maps_split.setSizes([400, 400, 400])
        lay.addWidget(maps_split, 3)

        # ─ Stats table ─
        stats_box = QGroupBox("Comparison Statistics")
        stats_box.setStyleSheet("""
            QGroupBox { color:#aaa; font-size:12pt; border:1px solid #2a2a2a;
                        border-radius:4px; margin-top:6px; }
            QGroupBox::title { subcontrol-position:top left; padding:0 4px; }
        """)
        stats_lay = QVBoxLayout(stats_box)
        stats_lay.setContentsMargins(4, 12, 4, 4)
        self._stats_table = _StatsTable()
        stats_lay.addWidget(self._stats_table)
        lay.addWidget(stats_box, 1)

        return content

    def _check_empty_state(self):
        """Show empty state (page 0) or content (page 1) based on loaded data."""
        if self._arrA is not None or self._arrB is not None:
            self._data_stack.setCurrentIndex(1)
        else:
            self._data_stack.setCurrentIndex(0)

    # ── Session loading ─────────────────────────────────────────────

    def _load_session(self, slot: str):
        """Open a folder-picker and load the chosen session into slot A or B."""
        folder = QFileDialog.getExistingDirectory(
            self, f"Select Session {slot} folder",
            str(Path.home() / "sessions")
        )
        if not folder:
            return

        arr = self._load_array_from_folder(folder)
        if arr is None:
            QMessageBox.warning(self, "Load Error",
                f"Could not find a recognisable data array in:\n{folder}\n\n"
                "Expected delta_r_over_r.npy or difference.npy.")
            return

        if slot == "A":
            self._arrA  = arr
            self._pathA = folder
        else:
            self._arrB  = arr
            self._pathB = folder

        self._check_empty_state()
        self._refresh_maps()
        self._status_lbl.setText(
            f"A: {Path(self._pathA).name if self._pathA else '—'}   "
            f"B: {Path(self._pathB).name if self._pathB else '—'}"
        )

    def _load_array_from_folder(self, folder: str) -> Optional[np.ndarray]:
        """Try to load a 2D numpy array from a session folder."""
        candidates = [
            "delta_r_over_r.npy",
            "difference.npy",
            "hot_avg.npy",
            "cold_avg.npy",
        ]
        for name in candidates:
            p = os.path.join(folder, name)
            if os.path.exists(p):
                try:
                    arr = np.load(p)
                    if arr.ndim == 2:
                        return arr.astype(np.float32)
                except Exception as e:
                    log.warning("Failed to load %s: %s", p, e)
        return None

    def _get_selected_array(self, folder: Optional[str]) -> Optional[np.ndarray]:
        """Return the array selected in the combo for the given session folder."""
        if not folder:
            return None
        combo_map = {
            0: "delta_r_over_r.npy",
            1: "difference.npy",
            2: "cold_avg.npy",
            3: "hot_avg.npy",
        }
        fname = combo_map.get(self._array_combo.currentIndex(), "delta_r_over_r.npy")
        p = os.path.join(folder, fname)
        if os.path.exists(p):
            try:
                arr = np.load(p)
                if arr.ndim == 2:
                    return arr.astype(np.float32)
            except Exception as e:
                log.warning("Could not load %s: %s", p, e)
        # Fallback: use whichever array was loaded initially
        if folder == self._pathA:
            return self._arrA
        return self._arrB

    # ── Map rendering ───────────────────────────────────────────────

    def _refresh_maps(self):
        cmap = self._cmap_combo.currentText()
        arrA = self._get_selected_array(self._pathA) if self._pathA else None
        arrB = self._get_selected_array(self._pathB) if self._pathB else None

        # Shared color range across A and B so they're visually comparable
        if arrA is not None and arrB is not None:
            vmin = float(min(np.nanmin(arrA), np.nanmin(arrB)))
            vmax = float(max(np.nanmax(arrA), np.nanmax(arrB)))
        elif arrA is not None:
            vmin, vmax = float(np.nanmin(arrA)), float(np.nanmax(arrA))
        elif arrB is not None:
            vmin, vmax = float(np.nanmin(arrB)), float(np.nanmax(arrB))
        else:
            vmin, vmax = 0.0, 1.0

        label_a = f"Session A — {Path(self._pathA).name}" if self._pathA else "Session A"
        label_b = f"Session B — {Path(self._pathB).name}" if self._pathB else "Session B"

        self._panel_a.set_data(arrA, cmap=cmap, vmin=vmin, vmax=vmax, title=label_a)
        self._panel_b.set_data(arrB, cmap=cmap, vmin=vmin, vmax=vmax, title=label_b)

        # Difference map
        if arrA is not None and arrB is not None:
            if arrA.shape == arrB.shape:
                diff = arrB.astype(np.float32) - arrA.astype(np.float32)
                abs_max = float(max(abs(np.nanmin(diff)), abs(np.nanmax(diff)), 1e-9))
                self._panel_diff.set_data(diff, cmap="RdBu_r",
                                          vmin=-abs_max, vmax=abs_max,
                                          title="Difference  (B − A)")
            else:
                self._panel_diff.clear()
                self._panel_diff.set_data(None, title="Difference — shape mismatch")
        else:
            self._panel_diff.clear()

        # Stats
        self._stats_table.update_session(1, arrA)
        self._stats_table.update_session(2, arrB)

    # ── Blink ───────────────────────────────────────────────────────

    def _toggle_blink(self, checked: bool):
        if checked:
            self._blink_btn.setText("Blink")
            self._blink_timer.start(500)   # 2 Hz blink
        else:
            self._blink_btn.setText("Blink")
            self._blink_timer.stop()
            self._refresh_maps()           # restore normal view

    def _do_blink(self):
        """Alternate panel_a between arrA and arrB."""
        self._blink_state = not self._blink_state
        if self._arrA is None or self._arrB is None:
            return
        cmap = self._cmap_combo.currentText()
        vmin = float(min(np.nanmin(self._arrA), np.nanmin(self._arrB)))
        vmax = float(max(np.nanmax(self._arrA), np.nanmax(self._arrB)))

        if self._blink_state:
            arr   = self._get_selected_array(self._pathB) if self._pathB else self._arrB
            label = f"[B] {Path(self._pathB).name if self._pathB else 'Session B'}"
        else:
            arr   = self._get_selected_array(self._pathA) if self._pathA else self._arrA
            label = f"[A] {Path(self._pathA).name if self._pathA else 'Session A'}"

        self._panel_a.set_data(arr, cmap=cmap, vmin=vmin, vmax=vmax, title=label)

    # ── Export ─────────────────────────────────────────────────────

    def _export_figure(self):
        if self._arrA is None and self._arrB is None:
            QMessageBox.information(self, "Nothing to export",
                "Load at least one session before exporting.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Comparison Figure",
            str(Path.home() / "comparison.png"),
            "PNG Image (*.png);;PDF Document (*.pdf)"
        )
        if not path:
            return

        cmap = self._cmap_combo.currentText()
        arrA = self._get_selected_array(self._pathA) if self._pathA else None
        arrB = self._get_selected_array(self._pathB) if self._pathB else None
        n_panels = 2 + (1 if arrA is not None and arrB is not None
                             and arrA.shape == arrB.shape else 0)

        fig, axes = plt.subplots(1, n_panels, figsize=(6 * n_panels, 5),
                                 facecolor="#0d0d0d")
        fig.suptitle("Microsanj Session Comparison", color="white", fontsize=13)

        for ax, arr, title in [
            (axes[0], arrA, f"Session A\n{Path(self._pathA).name if self._pathA else ''}"),
            (axes[1], arrB, f"Session B\n{Path(self._pathB).name if self._pathB else ''}"),
        ]:
            ax.set_facecolor("#1a1a1a")
            ax.set_title(title, color="#ccc", fontsize=9)
            ax.axis("off")
            if arr is not None:
                im = ax.imshow(arr, cmap=cmap, aspect="equal")
                plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        if n_panels == 3 and arrA is not None and arrB is not None:
            diff = arrB - arrA
            abs_max = float(max(abs(np.nanmin(diff)), abs(np.nanmax(diff)), 1e-9))
            axes[2].set_facecolor("#1a1a1a")
            axes[2].set_title("Difference (B − A)", color="#ccc", fontsize=9)
            axes[2].axis("off")
            im = axes[2].imshow(diff, cmap="RdBu_r",
                                vmin=-abs_max, vmax=abs_max, aspect="equal")
            plt.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04)

        plt.tight_layout()
        try:
            plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
            self._status_lbl.setText(f"Exported → {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))
        finally:
            plt.close(fig)
