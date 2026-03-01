"""
main_app.py

Microsanj Thermoreflectance System — Main Application Window.

Combines camera, TEC, and acquisition into a single unified interface.
Tabs: Acquire | Camera | Temperature | Log

Run:  python3 main_app.py
"""

import sys
import os
import time
import threading
import collections
import logging

log = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, Future
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QProgressBar, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QComboBox, QTextEdit, QTabWidget,
    QFileDialog, QFrame, QSizePolicy, QSlider, QButtonGroup,
    QRadioButton, QSplitter, QStatusBar, QAction, QMenuBar,
    QMessageBox, QStackedWidget, QCheckBox, QScrollArea,
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt5.QtGui   import (QImage, QPixmap, QFont, QColor, QPainter,
                           QPen, QBrush, QPalette)

import config
from hardware.cameras    import create_camera
from hardware.tec        import create_tec
from hardware.fpga       import create_fpga
from hardware.bias       import create_bias
from hardware.stage      import create_stage
from hardware.autofocus  import create_autofocus, AfState
from hardware.app_state  import app_state                   # ← thread-safe state
from acquisition         import (AcquisitionPipeline, AcquisitionResult,
                                AcquisitionProgress, AcqState,
                                to_display, apply_colormap, export_result)
from acquisition.roi        import Roi
from acquisition.roi_widget import RoiSelector
from acquisition.session         import Session
from acquisition.session_manager import SessionManager
from acquisition.data_tab        import DataTab
from acquisition.calibration     import CalibrationResult
from acquisition.calibration_tab import CalibrationTab
from acquisition.scan_tab        import ScanTab
from acquisition.live_tab        import LiveTab
from acquisition.analysis        import AnalysisResult
from acquisition.analysis_tab    import AnalysisTab
from acquisition.modality        import ImagingModality     # ← modality enum
from acquisition.comparison_tab  import ComparisonTab       # ← session comparison
from acquisition.surface_plot_tab import SurfacePlotTab     # ← 3D surface plot
from acquisition.recipe_tab      import RecipeTab           # ← measurement recipes
from ui.wizard                   import StandardWizard
from ui.scripting_console        import ScriptingConsoleTab # ← Python console
from ui.sidebar_nav              import SidebarNav          # ← grouped sidebar nav
from hardware.device_manager     import DeviceManager
from ui.device_manager_dialog    import DeviceManagerDialog
from ui.notifications            import (StartupProgressDialog,   # ← notifications
                                          ToastManager, get_guidance)
from profiles.profiles        import MaterialProfile
from profiles.profile_manager import ProfileManager
from profiles.profile_tab     import ProfileTab
from ui.settings_tab          import SettingsTab

# ------------------------------------------------------------------ #
#  App-wide style                                                     #
# ------------------------------------------------------------------ #

STYLE = """
QMainWindow, QWidget {
    background-color: #1a1a1a;
    color: #d0d0d0;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size:15pt;
}
QTabWidget::pane {
    border: 1px solid #333;
    background: #1e1e1e;
}
QTabBar::tab {
    background: #252525;
    color: #888;
    padding: 8px 20px;
    border: 1px solid #333;
    border-bottom: none;
    font-size:15pt;
    letter-spacing: 1px;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    color: #00d4aa;
    border-top: 2px solid #00d4aa;
}
QTabBar::tab:hover { color: #bbb; }
QGroupBox {
    border: 1px solid #333;
    border-radius: 3px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    font-size:13pt;
    color: #999;
    letter-spacing: 1px;
    text-transform: uppercase;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 8px;
}
QPushButton {
    background: #2a2a2a;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 2px;
    padding: 5px 12px;
    font-size:14pt;
}
QPushButton:hover   { background: #333; color: #fff; border-color: #555; }
QPushButton:pressed { background: #222; }
QPushButton:disabled { color: #444; border-color: #333; }
QPushButton#primary {
    background: #003d2e;
    color: #00d4aa;
    border-color: #00d4aa;
    font-weight: bold;
}
QPushButton#primary:hover { background: #005040; }
QPushButton#danger {
    background: #3d0000;
    color: #ff6666;
    border-color: #ff4444;
}
QPushButton#cold_btn {
    background: #001a33;
    color: #66aaff;
    border-color: #3377cc;
    font-weight: bold;
}
QPushButton#hot_btn {
    background: #331a00;
    color: #ffaa44;
    border-color: #cc6600;
    font-weight: bold;
}
QSlider::groove:horizontal {
    height: 3px;
    background: #333;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #00d4aa;
    width: 12px; height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::sub-page:horizontal { background: #00d4aa; border-radius: 2px; }
QProgressBar {
    border: 1px solid #333;
    border-radius: 2px;
    background: #222;
    height: 6px;
    text-align: center;
    font-size:12pt;
    color: #666;
}
QProgressBar::chunk { background: #00d4aa; border-radius: 2px; }
QSpinBox, QDoubleSpinBox, QComboBox {
    background: #222;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 2px;
    padding: 3px 6px;
}
QComboBox::drop-down { border: none; }
QTextEdit {
    background: #111;
    color: #888;
    border: 1px solid #2a2a2a;
    font-family: 'Menlo', 'Courier New', monospace;
    font-size:12pt;
}
QLabel#readout {
    font-family: 'Menlo', 'Courier New', monospace;
    font-size:35pt;
    color: #00d4aa;
}
QLabel#readout_warn { color: #ffaa44; }
QLabel#readout_error { color: #ff6666; }
QLabel#sublabel {
    font-size:12pt;
    color: #888;
    letter-spacing: 1px;
    text-transform: uppercase;
}
QStatusBar { background: #111; color: #888; font-size:12pt; }
QMenuBar { background: #111; color: #888; border-bottom: 1px solid #222; font-size:13pt; }
QMenuBar::item:selected { background: #222; color: #ddd; }
QMenu { background: #1a1a1a; color: #ccc; border: 1px solid #333; font-size:13pt; }
QMenu::item:selected { background: #252525; color: #fff; }
QMenu::separator { height: 1px; background: #333; margin: 4px 0; }
"""

# ------------------------------------------------------------------ #
#  Signals                                                           #
# ------------------------------------------------------------------ #

class AppSignals(QObject):
    new_live_frame = pyqtSignal(object)
    tec_status     = pyqtSignal(int, object)    # index, TecStatus
    fpga_status    = pyqtSignal(object)         # FpgaStatus
    bias_status    = pyqtSignal(object)         # BiasStatus
    stage_status   = pyqtSignal(object)         # StageStatus
    af_progress    = pyqtSignal(object)         # AfResult (mid-run)
    af_complete    = pyqtSignal(object)         # AfResult (final)
    cal_progress   = pyqtSignal(object)         # CalibrationProgress
    cal_complete   = pyqtSignal(object)         # CalibrationResult
    scan_progress  = pyqtSignal(object)         # ScanProgress
    scan_complete  = pyqtSignal(object)         # ScanResult
    profile_applied = pyqtSignal(object)        # MaterialProfile
    acq_progress   = pyqtSignal(object)
    acq_complete   = pyqtSignal(object)
    acq_saved      = pyqtSignal(object)         # Session (just saved)
    log_message    = pyqtSignal(str)
    error          = pyqtSignal(str)

signals = AppSignals()

# ------------------------------------------------------------------ #
#  Shared state — all hardware refs live in the thread-safe AppState  #
# ------------------------------------------------------------------ #
#
# IMPORTANT: Always read/write hardware via app_state.xxx, never as
# bare module-level variables.  The shims below exist only for the
# handful of places in this file that reference them by old names
# before the full migration is complete.
#
# New code should use:
#     from hardware.app_state       import app_state
from hardware.hardware_service import HardwareService
from version import __version__, APP_NAME, APP_VENDOR, version_string
#     cam = app_state.cam
#

# Hardware state accessed via app_state (see __getattr__ below)

running = True   # kept for any legacy code; service uses its own Event

# Central hardware service — owns all device threads and state
hw_service = HardwareService()

# Session manager — persists acquisitions to disk
_default_sessions_dir = os.path.join(
    os.path.expanduser("~"), "microsanj_sessions")
session_mgr = SessionManager(_default_sessions_dir)

# Module-level __getattr__ resolves bare names like 'cam', 'fpga', etc.
# at access time via app_state.  This is the correct way to do module-level
# "properties" — the @property decorator does NOT work at module scope.
def __getattr__(name: str):
    _aliases = {
        "cam":      lambda: app_state.cam,
        "fpga":     lambda: app_state.fpga,
        "bias":     lambda: app_state.bias,
        "stage":    lambda: app_state.stage,
        "pipeline": lambda: app_state.pipeline,
        "tecs":     lambda: app_state.tecs,
    }
    if name in _aliases:
        return _aliases[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ------------------------------------------------------------------ #
#  Background threads                                                 #
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
#  Background threads                                                 #
# ------------------------------------------------------------------ #

def camera_thread():
    cfg = config.get("hardware").get("camera", {})
    try:
        cam = create_camera(cfg)
        cam.open()
        cam.start()
        pipeline = AcquisitionPipeline(cam,
                                        fpga=app_state.fpga,
                                        bias=app_state.bias)
        pipeline.on_progress = lambda p: signals.acq_progress.emit(p)
        pipeline.on_complete = lambda r: signals.acq_complete.emit(r)
        pipeline.on_error    = lambda e: signals.error.emit(e)
        with app_state:
            app_state.cam      = cam
            app_state.pipeline = pipeline
        signals.log_message.emit(
            f"Camera: {cam.info.driver} | {cam.info.model} "
            f"| {cam.info.width}×{cam.info.height}")
    except Exception as e:
        signals.error.emit(f"Camera: {e}")
        return

    while running:
        if app_state.pipeline and app_state.pipeline.state == AcqState.CAPTURING:
            time.sleep(0.05)
            continue
        cam = app_state.cam
        if cam is None:
            time.sleep(0.1)
            continue
        frame = cam.grab(timeout_ms=500)
        if frame:
            signals.new_live_frame.emit(frame)


def tec_thread(index: int, tec):
    while running:
        try:
            status = tec.get_status()
            signals.tec_status.emit(index, status)
        except Exception as e:
            from hardware.tec import TecStatus
            signals.tec_status.emit(index, TecStatus(error=str(e)))
        time.sleep(0.5)


def fpga_thread(fpga_driver):
    while running:
        try:
            status = fpga_driver.get_status()
            signals.fpga_status.emit(status)
        except Exception as e:
            from hardware.fpga import FpgaStatus
            signals.fpga_status.emit(FpgaStatus(error=str(e)))
        time.sleep(0.25)


def bias_thread(bias_driver):
    while running:
        try:
            status = bias_driver.get_status()
            signals.bias_status.emit(status)
        except Exception as e:
            from hardware.bias import BiasStatus
            signals.bias_status.emit(BiasStatus(error=str(e)))
        time.sleep(0.25)


def stage_thread(stage_driver):
    while running:
        try:
            status = stage_driver.get_status()
            signals.stage_status.emit(status)
        except Exception as e:
            from hardware.stage import StageStatus
            signals.stage_status.emit(StageStatus(error=str(e)))
        time.sleep(0.1)


# ------------------------------------------------------------------ #
#  Reusable widgets                                                   #
# ------------------------------------------------------------------ #

def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #2a2a2a;")
    return f


class ImagePane(QWidget):
    def __init__(self, title: str = "", w: int = 400, h: int = 300):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._lbl = QLabel()
        self._lbl.setFixedSize(w, h)
        self._lbl.setStyleSheet("background:#0d0d0d; border:1px solid #2a2a2a;")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet("font-size:13pt; color:#666; letter-spacing:1px;")
        self._stats = QLabel("")
        self._stats.setAlignment(Qt.AlignCenter)
        self._stats.setStyleSheet("font-family:Menlo,monospace; font-size:13pt; color:#666;")
        layout.addWidget(self._lbl)
        layout.addWidget(self._title)
        layout.addWidget(self._stats)

    def show_array(self, data, mode="auto", cmap="gray"):
        if data is None:
            return
        disp = to_display(data, mode=mode)
        if cmap != "gray" and disp.ndim == 2:
            disp = apply_colormap(disp, cmap)
        if disp.ndim == 2:
            h, w = disp.shape
            qi = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w = disp.shape[:2]
            qi = QImage(disp.tobytes(), w, h, w*3, QImage.Format_RGB888)
        sz  = self._lbl.size()
        pix = QPixmap.fromImage(qi).scaled(sz, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation)
        self._lbl.setPixmap(pix)
        self._stats.setText(
            f"min {data.min():.3g}   max {data.max():.3g}   "
            f"μ {data.mean():.3g}")

    def set_title(self, t):
        self._title.setText(t)

    def clear(self):
        """Reset the pane to a blank state (no image, no stats)."""
        self._lbl.setPixmap(QPixmap())
        self._lbl.setText("")
        self._stats.setText("")


class TempPlot(QWidget):
    HISTORY = 120

    def __init__(self, h=140):
        super().__init__()
        self.setMinimumSize(100, 80)
        self.setMaximumHeight(h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._actual = collections.deque([None]*self.HISTORY, maxlen=self.HISTORY)
        self._target = collections.deque([None]*self.HISTORY, maxlen=self.HISTORY)
        self._temp_min:    float | None = None
        self._temp_max:    float | None = None
        self._warn_margin: float        = 5.0

    def push(self, actual, target):
        self._actual.append(actual)
        self._target.append(target)
        self.update()

    def set_limits(self, temp_min: float, temp_max: float,
                   warn_margin: float = 5.0):
        self._temp_min    = temp_min
        self._temp_max    = temp_max
        self._warn_margin = warn_margin
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        pad  = 36
        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        vals = [v for v in list(self._actual)+list(self._target) if v is not None]

        # Include limits in the Y-range calculation so lines are always visible
        if self._temp_min is not None: vals.append(self._temp_min)
        if self._temp_max is not None: vals.append(self._temp_max)

        if not vals:
            return
        lo   = min(vals) - 2
        hi   = max(vals) + 2
        span = max(hi - lo, 0.5)

        def tx(i): return int(pad + i/(self.HISTORY-1)*(W-2*pad))
        def ty(v): return int(H-pad-(v-lo)/span*(H-2*pad))

        # Grid
        p.setPen(QPen(QColor(35,35,35), 1))
        step = max(1, int(span/4))
        t = (int(lo/step)-1)*step
        p.setFont(QFont("Menlo", 11))
        while t <= hi+step:
            y = ty(t)
            if pad <= y <= H-pad:
                p.drawLine(pad, y, W-pad, y)
                p.setPen(QPen(QColor(80,80,80), 1))
                p.drawText(2, y+4, f"{t:.0f}°")
                p.setPen(QPen(QColor(35,35,35), 1))
            t += step

        # ── Alarm limit lines ─────────────────────────────────────────
        if self._temp_min is not None or self._temp_max is not None:
            dash = [6, 4]
            for limit, color, warn_offset in [
                (self._temp_min, QColor(255,68,68),   +self._warn_margin),
                (self._temp_max, QColor(255,68,68),   -self._warn_margin),
            ]:
                if limit is None:
                    continue
                # Hard limit — dashed red
                pen = QPen(QColor(255, 68, 68), 1, Qt.DashLine)
                p.setPen(pen)
                y = ty(limit)
                if 0 <= y <= H:
                    p.drawLine(pad, y, W-pad, y)
                    p.setFont(QFont("Menlo", 10))
                    p.setPen(QPen(QColor(255, 100, 100), 1))
                    label = f"{'min' if warn_offset > 0 else 'max'} {limit:.0f}°"
                    p.drawText(pad+2, y-2, label)

                # Warning zone — dashed amber
                warn_limit = limit + warn_offset
                pen_w = QPen(QColor(255, 153, 0), 1, Qt.DotLine)
                p.setPen(pen_w)
                yw = ty(warn_limit)
                if 0 <= yw <= H:
                    p.drawLine(pad, yw, W-pad, yw)

        # ── Temperature traces ────────────────────────────────────────
        for series, col in [(self._actual, QColor(0,212,170)),
                             (self._target, QColor(255,170,68))]:
            p.setPen(QPen(col, 1))
            prev = None
            for i, v in enumerate(series):
                if v is None: prev = None; continue
                x, y = tx(i), ty(v)
                if prev: p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # Legend
        p.setPen(QPen(QColor(0,212,170), 1))
        p.drawLine(W-110, 10, W-95, 10)
        p.setPen(QPen(QColor(100,100,100), 1))
        p.drawText(W-90, 14, "actual")
        p.setPen(QPen(QColor(255,170,68), 1))
        p.drawLine(W-110, 22, W-95, 22)
        p.setPen(QPen(QColor(100,100,100), 1))
        p.drawText(W-90, 26, "target")
        p.end()


# ------------------------------------------------------------------ #
#  Tab 1: Acquire                                                     #
# ------------------------------------------------------------------ #

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

    def update_result(self, result: AcquisitionResult):
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


# ------------------------------------------------------------------ #
#  Tab 2: Camera                                                      #
# ------------------------------------------------------------------ #

class CameraTab(QWidget):
    def __init__(self, cam_info=None):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        root.addLayout(top)

        # Image
        img_box = QGroupBox("Frame")
        il = QVBoxLayout(img_box)
        self._pane = ImagePane("", 640, 480)
        il.addWidget(self._pane)
        top.addWidget(img_box, 3)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        from ui.help import help_label
        cl.addWidget(help_label("Exposure (μs)", "exposure_us"), 0, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(50, 200000)
        self._exp_slider.setValue(5000)
        self._exp_lbl = QLabel("5000")
        self._exp_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        self._exp_slider.valueChanged.connect(
            lambda v: self._exp_lbl.setText(str(v)))
        self._exp_slider.sliderReleased.connect(self._on_exp)
        cl.addWidget(self._exp_slider, 0, 1)
        cl.addWidget(self._exp_lbl, 0, 2)

        # Presets
        pr = QHBoxLayout()
        for lbl, v in [("50μs",50),("1ms",1000),("5ms",5000),
                       ("20ms",20000),("100ms",100000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(55)
            b.clicked.connect(lambda _, val=v: self._set_exp(val))
            pr.addWidget(b)
        pr.addStretch()
        cl.addLayout(pr, 1, 1)

        cl.addWidget(help_label("Gain (dB)", "gain_db"), 2, 0)
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 239)
        self._gain_slider.setValue(0)
        self._gain_lbl = QLabel("0.0")
        self._gain_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        self._gain_slider.valueChanged.connect(
            lambda v: self._gain_lbl.setText(f"{v/10:.1f}"))
        self._gain_slider.sliderReleased.connect(self._on_gain)
        cl.addWidget(self._gain_slider, 2, 1)
        cl.addWidget(self._gain_lbl, 2, 2)

        cl.addWidget(hline(), 3, 0, 1, 3)

        cl.addWidget(QLabel("Display"), 4, 0)
        self._bg = QButtonGroup()
        dr = QHBoxLayout()
        for i, m in enumerate(["Auto contrast", "12-bit fixed"]):
            rb = QRadioButton(m)
            self._bg.addButton(rb, i)
            dr.addWidget(rb)
        self._bg.button(0).setChecked(True)
        dr.addStretch()
        cl.addLayout(dr, 4, 1)

        save_btn = QPushButton("Save Frame (16-bit PNG)")
        save_btn.clicked.connect(self._save)
        cl.addWidget(save_btn, 5, 1)

        top.addWidget(ctrl_box, 1)

        # Stats
        stats_box = QGroupBox("Frame Statistics")
        sl = QHBoxLayout(stats_box)
        self._stat_min  = self._stat_widget("MIN")
        self._stat_max  = self._stat_widget("MAX")
        self._stat_mean = self._stat_widget("MEAN")
        self._stat_idx  = self._stat_widget("FRAME")
        for w in [self._stat_min, self._stat_max,
                  self._stat_mean, self._stat_idx]:
            sl.addWidget(w)
        root.addWidget(stats_box)

    def _stat_widget(self, label):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel("--")
        val.setObjectName("readout")
        val.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def update_frame(self, frame):
        d = frame.data
        mode = "auto" if self._bg.checkedId() == 0 else "fixed"
        self._pane.show_array(d, mode=mode)
        self._stat_min._val.setText(str(int(d.min())))
        self._stat_max._val.setText(str(int(d.max())))
        self._stat_mean._val.setText(f"{d.mean():.1f}")
        self._stat_idx._val.setText(str(frame.frame_index))

    def _set_exp(self, val):
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def _on_exp(self):
        self._do_exp(self._exp_slider.value())

    def _do_exp(self, val):
        cam = app_state.cam
        if cam:
            threading.Thread(
                target=cam.set_exposure, args=(float(val),),
                daemon=True).start()

    def _on_gain(self):
        cam = app_state.cam
        if cam:
            val = self._gain_slider.value() / 10.0
            threading.Thread(
                target=cam.set_gain, args=(val,),
                daemon=True).start()

    def _save(self):
        import cv2
        cam = app_state.cam
        if cam:
            f = cam.grab()
            if f:
                name = f"frame_{int(time.time())}.png"
                cv2.imwrite(name, f.data)
                signals.log_message.emit(f"Saved: {name}")

    def set_exposure(self, us: float):
        """Push a new exposure value from an external source (e.g. profile)."""
        val = int(max(50, min(200000, us)))
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def set_gain(self, db: float):
        """Push a new gain value from an external source (e.g. profile)."""
        val = int(max(0, min(239, db * 10)))
        self._gain_slider.setValue(val)
        cam = app_state.cam
        if cam:
            threading.Thread(
                target=cam.set_gain, args=(db,), daemon=True).start()


# ------------------------------------------------------------------ #
#  Tab 3: Temperature                                                  #
# ------------------------------------------------------------------ #

class TemperatureTab(QWidget):
    def __init__(self, n_tecs: int):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._panels = []
        labels = ["TEC 1 — Meerstetter TEC-1089", "TEC 2 — ATEC-302"]
        for i in range(n_tecs):
            p = self._build_tec(labels[i] if i < len(labels) else f"TEC {i+1}", i)
            root.addWidget(p)
            self._panels.append(p)

        root.addStretch()

    def _build_tec(self, title, tec_index):
        box = QGroupBox(title)
        main = QVBoxLayout(box)

        # ── Alarm banner (hidden by default) ─────────────────────────
        alarm_banner = QWidget()
        alarm_banner.setVisible(False)
        alarm_banner.setStyleSheet(
            "background:#330000; border:1px solid #ff4444; border-radius:3px;")
        ab_lay = QHBoxLayout(alarm_banner)
        ab_lay.setContentsMargins(10, 6, 10, 6)
        ab_icon = QLabel("⊗")
        ab_icon.setStyleSheet("color:#ff4444; font-size:16pt;")
        ab_msg  = QLabel("Temperature alarm")
        ab_msg.setStyleSheet("color:#ff6666; font-size:13pt;")
        ab_msg.setWordWrap(True)
        ab_ack  = QPushButton("Acknowledge")
        ab_ack.setFixedHeight(26)
        ab_ack.setStyleSheet("""
            QPushButton {
                background:#550000; color:#ff9999;
                border:1px solid #ff444466; border-radius:3px;
                font-size:12pt; padding: 0 10px;
            }
            QPushButton:hover { background:#660000; color:#ffbbbb; }
        """)
        ab_lay.addWidget(ab_icon)
        ab_lay.addWidget(ab_msg, 1)
        ab_lay.addWidget(ab_ack)
        box._alarm_banner  = alarm_banner
        box._alarm_msg_lbl = ab_msg
        box._alarm_ack_btn = ab_ack
        main.addWidget(alarm_banner)

        # ── Warning banner (hidden by default) ───────────────────────
        warn_banner = QWidget()
        warn_banner.setVisible(False)
        warn_banner.setStyleSheet(
            "background:#332200; border:1px solid #ff9900; border-radius:3px;")
        wb_lay = QHBoxLayout(warn_banner)
        wb_lay.setContentsMargins(10, 4, 10, 4)
        wb_icon = QLabel("⚠")
        wb_icon.setStyleSheet("color:#ff9900; font-size:14pt;")
        wb_msg  = QLabel("Approaching limit")
        wb_msg.setStyleSheet("color:#ffaa44; font-size:12pt;")
        wb_msg.setWordWrap(True)
        wb_lay.addWidget(wb_icon)
        wb_lay.addWidget(wb_msg, 1)
        box._warn_banner  = warn_banner
        box._warn_msg_lbl = wb_msg
        main.addWidget(warn_banner)

        # ── Readouts ─────────────────────────────────────────────────
        top = QHBoxLayout()
        actual_w = self._readout_widget("ACTUAL", "--", "#00d4aa")
        target_w = self._readout_widget("SETPOINT", "--", "#ffaa44")
        power_w  = self._readout_widget("OUTPUT", "--", "#6699ff")
        state_w  = self._readout_widget("STATUS", "UNKNOWN", "#555")

        box._actual_lbl = actual_w._val
        box._target_lbl = target_w._val
        box._power_lbl  = power_w._val
        box._state_lbl  = state_w._val

        for w in [actual_w, target_w, power_w, state_w]:
            top.addWidget(w)
        main.addLayout(top)

        # ── Plot ──────────────────────────────────────────────────────
        plot = TempPlot(h=130)
        box._plot = plot
        main.addWidget(plot)

        # ── Setpoint controls ─────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Target (°C)"))
        spin = QDoubleSpinBox()
        spin.setRange(-40, 150)
        spin.setValue(25.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setFixedWidth(80)
        box._spin = spin
        ctrl.addWidget(spin)

        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(50)
        ctrl.addWidget(set_btn)

        ctrl.addSpacing(12)
        for lbl, val in [("-20°C",-20),("0°C",0),("25°C",25),
                          ("50°C",50),("85°C",85)]:
            b = QPushButton(lbl)
            b.setFixedWidth(52)
            ctrl.addWidget(b)
            b.clicked.connect(
                lambda _, v=val, s=spin, box=box: (
                    s.setValue(v), self._set_target(box, v)))

        ctrl.addStretch()
        en_btn  = QPushButton("Enable")
        dis_btn = QPushButton("Disable")
        en_btn.setFixedWidth(70)
        dis_btn.setFixedWidth(70)
        en_btn.setStyleSheet( "background:#003322; color:#00d4aa; border-color:#00d4aa;")
        dis_btn.setStyleSheet("background:#330000; color:#ff6666; border-color:#ff4444;")
        ctrl.addWidget(en_btn)
        ctrl.addWidget(dis_btn)
        main.addLayout(ctrl)

        # ── Safety limits row ─────────────────────────────────────────
        lim_row = QHBoxLayout()
        lim_row.addWidget(QLabel("Safety limits:"))

        min_spin = QDoubleSpinBox()
        min_spin.setRange(-40, 148)
        min_spin.setValue(-20.0)
        min_spin.setSingleStep(1.0)
        min_spin.setDecimals(1)
        min_spin.setFixedWidth(70)
        min_spin.setPrefix("min ")
        min_spin.setSuffix(" °C")

        max_spin = QDoubleSpinBox()
        max_spin.setRange(-38, 150)
        max_spin.setValue(85.0)
        max_spin.setSingleStep(1.0)
        max_spin.setDecimals(1)
        max_spin.setFixedWidth(70)
        max_spin.setPrefix("max ")
        max_spin.setSuffix(" °C")

        warn_spin = QDoubleSpinBox()
        warn_spin.setRange(0.5, 20.0)
        warn_spin.setValue(5.0)
        warn_spin.setSingleStep(0.5)
        warn_spin.setDecimals(1)
        warn_spin.setFixedWidth(70)
        warn_spin.setPrefix("warn ±")
        warn_spin.setSuffix(" °C")

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(55)

        for w in [min_spin, max_spin, warn_spin]:
            w.setStyleSheet("font-size:12pt;")

        lim_row.addWidget(min_spin)
        lim_row.addWidget(max_spin)
        lim_row.addWidget(warn_spin)
        lim_row.addWidget(apply_btn)
        lim_row.addStretch()
        main.addLayout(lim_row)

        box._min_spin  = min_spin
        box._max_spin  = max_spin
        box._warn_spin = warn_spin
        box._tec_index = tec_index

        # Update plot limits immediately with defaults
        plot.set_limits(-20.0, 85.0, 5.0)

        # ── Wire ──────────────────────────────────────────────────────
        set_btn.clicked.connect(
            lambda _, s=spin, b=box: self._set_target(b, s.value()))
        en_btn.clicked.connect( lambda _, b=box: self._enable(b))
        dis_btn.clicked.connect(lambda _, b=box: self._disable(b))
        apply_btn.clicked.connect(lambda _, b=box: self._apply_limits(b))
        ab_ack.clicked.connect(lambda _, b=box: self._acknowledge_alarm(b))

        return box

    def _readout_widget(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:31pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def update_tec(self, index: int, status):
        if index >= len(self._panels):
            return
        p = self._panels[index]
        if status.error:
            p._actual_lbl.setText("ERR")
            p._state_lbl.setText(status.error[:20])
            p._state_lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:22pt; color:#ff6666;")
            return
        p._actual_lbl.setText(f"{status.actual_temp:.2f} °C")
        p._target_lbl.setText(f"{status.target_temp:.1f} °C")
        p._power_lbl.setText( f"{status.output_power:.2f} W")
        if not status.enabled:
            p._state_lbl.setText("DISABLED")
            p._state_lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:22pt; color:#444;")
        elif status.stable:
            p._state_lbl.setText("STABLE ✓")
            p._state_lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:22pt; color:#00d4aa;")
        else:
            diff  = status.actual_temp - status.target_temp
            arrow = "▼" if diff > 0 else "▲"
            p._state_lbl.setText(f"SETTLING {arrow}")
            p._state_lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:22pt; color:#ffaa44;")
        p._plot.push(status.actual_temp, status.target_temp)

    def show_alarm(self, index: int, message: str):
        """Show the alarm banner for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._alarm_msg_lbl.setText(message)
        p._alarm_banner.setVisible(True)
        p._warn_banner.setVisible(False)
        p._actual_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:31pt; color:#ff4444;")
        p.setStyleSheet("QGroupBox { border-color: #ff4444; }")

    def show_warning(self, index: int, message: str):
        """Show the warning banner for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._warn_msg_lbl.setText(message)
        p._warn_banner.setVisible(True)
        p._actual_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:31pt; color:#ff9900;")

    def clear_alarm(self, index: int):
        """Clear alarm/warning state for the given TEC panel."""
        if index >= len(self._panels):
            return
        p = self._panels[index]
        p._alarm_banner.setVisible(False)
        p._warn_banner.setVisible(False)
        p._actual_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:31pt; color:#00d4aa;")
        p.setStyleSheet("")

    def _apply_limits(self, box):
        """Push updated limits to the ThermalGuard and TempPlot."""
        idx        = self._panels.index(box)
        temp_min   = box._min_spin.value()
        temp_max   = box._max_spin.value()
        warn_margin = box._warn_spin.value()

        # Update the chart
        box._plot.set_limits(temp_min, temp_max, warn_margin)

        # Update the guard
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.update_limits(temp_min, temp_max, warn_margin)

    def _acknowledge_alarm(self, box):
        """Acknowledge the alarm — clears latch, hides banner."""
        idx   = self._panels.index(box)
        guard = app_state.get_tec_guard(idx)
        if guard:
            guard.acknowledge()
        self.clear_alarm(idx)

    def _set_target(self, box, val):
        idx = self._panels.index(box)
        _tecs = app_state.tecs
        if _tecs and idx < len(_tecs):
            threading.Thread(
                target=_tecs[idx].set_target, args=(val,),
                daemon=True).start()

    def _enable(self, box):
        idx   = self._panels.index(box)
        guard = app_state.get_tec_guard(idx)
        if guard and guard.is_alarmed:
            # Don't allow re-enable while alarm is active
            return
        _tecs = app_state.tecs
        if _tecs and idx < len(_tecs):
            threading.Thread(target=_tecs[idx].enable, daemon=True).start()

    def _disable(self, box):
        idx = self._panels.index(box)
        _tecs = app_state.tecs
        if _tecs and idx < len(_tecs):
            threading.Thread(target=_tecs[idx].disable, daemon=True).start()


# ------------------------------------------------------------------ #
#  Tab 4: FPGA                                                        #
# ------------------------------------------------------------------ #

class FpgaTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Status readouts
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._freq_w    = self._readout("FREQUENCY",   "--",    "#00d4aa")
        self._duty_w    = self._readout("DUTY CYCLE",  "--",    "#ffaa44")
        self._frames_w  = self._readout("FRAME COUNT", "--",    "#6699ff")
        self._sync_w    = self._readout("SYNC",        "UNKNOWN","#555")
        self._stim_w    = self._readout("STIMULUS",    "OFF",   "#555")
        for w in [self._freq_w, self._duty_w, self._frames_w,
                  self._sync_w, self._stim_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        cl.addWidget(self._sub("Frequency (Hz)"), 0, 0)
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(0.1, 100000)
        self._freq_spin.setValue(1000)
        self._freq_spin.setDecimals(1)
        self._freq_spin.setFixedWidth(110)
        cl.addWidget(self._freq_spin, 0, 1)

        # Frequency presets
        freq_row = QHBoxLayout()
        for lbl, val in [("1 Hz",1),("10 Hz",10),("100 Hz",100),
                         ("1 kHz",1000),("10 kHz",10000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(62)
            b.clicked.connect(
                lambda _, v=val: (self._freq_spin.setValue(v),
                                  self._set_freq(v)))
            freq_row.addWidget(b)
        freq_row.addStretch()
        cl.addLayout(freq_row, 1, 1)

        cl.addWidget(self._sub("Duty Cycle (%)"), 2, 0)
        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(1, 99)
        self._duty_spin.setValue(50)
        self._duty_spin.setDecimals(0)
        self._duty_spin.setFixedWidth(110)
        cl.addWidget(self._duty_spin, 2, 1)

        duty_row = QHBoxLayout()
        for lbl, val in [("10%",10),("25%",25),("50%",50),
                         ("75%",75),("90%",90)]:
            b = QPushButton(lbl)
            b.setFixedWidth(52)
            b.clicked.connect(
                lambda _, v=val: (self._duty_spin.setValue(v),
                                  self._set_duty(v/100.0)))
            duty_row.addWidget(b)
        duty_row.addStretch()
        cl.addLayout(duty_row, 3, 1)

        cl.addWidget(hline(), 4, 0, 1, 3)

        # Apply + run buttons
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Settings")
        apply_btn.clicked.connect(self._apply)
        start_btn = QPushButton("▶  Start")
        start_btn.setObjectName("primary")
        stop_btn  = QPushButton("■  Stop")
        stop_btn.setObjectName("danger")
        stim_on   = QPushButton("Stimulus ON")
        stim_off  = QPushButton("Stimulus OFF")
        stim_on.setStyleSheet(
            "background:#331a00; color:#ffaa44; border-color:#cc6600;")
        stim_off.setStyleSheet(
            "background:#1a1a2e; color:#6699ff; border-color:#3355aa;")

        for b in [apply_btn, start_btn, stop_btn, stim_on, stim_off]:
            b.setFixedWidth(110)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row, 5, 0, 1, 3)

        start_btn.clicked.connect(self._start)
        stop_btn.clicked.connect(self._stop)
        stim_on.clicked.connect(lambda: self._set_stimulus(True))
        stim_off.clicked.connect(lambda: self._set_stimulus(False))

        root.addWidget(ctrl_box)
        root.addStretch()

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:28pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def update_status(self, status):
        if status.error:
            self._sync_w._val.setText("ERROR")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ff6666;")
            return

        self._freq_w._val.setText(f"{status.freq_hz:,.0f} Hz")
        self._duty_w._val.setText(f"{status.duty_cycle*100:.0f}%")
        self._frames_w._val.setText(f"{status.frame_count:,}")

        if status.sync_locked:
            self._sync_w._val.setText("LOCKED ✓")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#00d4aa;")
        else:
            self._sync_w._val.setText("UNLOCKED")
            self._sync_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#555;")

        if status.stimulus_on:
            self._stim_w._val.setText("ON ●")
            self._stim_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ffaa44;")
        else:
            self._stim_w._val.setText("OFF ○")
            self._stim_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#444;")

    def _apply(self):
        self._set_freq(self._freq_spin.value())
        self._set_duty(self._duty_spin.value() / 100.0)

    def _set_freq(self, val):
        fpga = app_state.fpga
        if fpga:
            threading.Thread(
                target=fpga.set_frequency, args=(val,),
                daemon=True).start()

    def _set_duty(self, val):
        fpga = app_state.fpga
        if fpga:
            threading.Thread(
                target=fpga.set_duty_cycle, args=(val,),
                daemon=True).start()

    def _start(self):
        fpga = app_state.fpga
        if fpga:
            self._apply()
            threading.Thread(target=fpga.start, daemon=True).start()

    def _stop(self):
        fpga = app_state.fpga
        if fpga:
            threading.Thread(target=fpga.stop, daemon=True).start()

    def _set_stimulus(self, on: bool):
        fpga = app_state.fpga
        if fpga:
            threading.Thread(
                target=fpga.set_stimulus, args=(on,),
                daemon=True).start()


# ------------------------------------------------------------------ #
#  Tab 5: Bias                                                        #
# ------------------------------------------------------------------ #

class BiasTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Status readouts
        status_box = QGroupBox("Measured Output")
        sl = QHBoxLayout(status_box)
        self._v_w      = self._readout("VOLTAGE",    "--",    "#00d4aa")
        self._i_w      = self._readout("CURRENT",    "--",    "#ffaa44")
        self._p_w      = self._readout("POWER",      "--",    "#6699ff")
        self._comp_w   = self._readout("COMPLIANCE", "--",    "#888")
        self._state_w  = self._readout("OUTPUT",     "OFF",   "#555")
        for w in [self._v_w, self._i_w, self._p_w,
                  self._comp_w, self._state_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        # Mode selector
        cl.addWidget(self._sub("Source Mode"), 0, 0)
        mode_row = QHBoxLayout()
        self._mode_bg = QButtonGroup()
        for i, m in enumerate(["Voltage", "Current"]):
            rb = QRadioButton(m)
            self._mode_bg.addButton(rb, i)
            mode_row.addWidget(rb)
        self._mode_bg.button(0).setChecked(True)
        self._mode_bg.buttonClicked.connect(self._on_mode_change)
        mode_row.addStretch()
        cl.addLayout(mode_row, 0, 1)

        # Level
        cl.addWidget(self._sub("Output Level"), 1, 0)
        level_row = QHBoxLayout()
        self._level_spin = QDoubleSpinBox()
        self._level_spin.setRange(-200, 200)
        self._level_spin.setValue(0.0)
        self._level_spin.setDecimals(4)
        self._level_spin.setSingleStep(0.1)
        self._level_spin.setFixedWidth(120)
        self._level_unit = QLabel("V")
        self._level_unit.setStyleSheet("color:#666; font-size:15pt;")
        level_row.addWidget(self._level_spin)
        level_row.addWidget(self._level_unit)
        level_row.addStretch()
        cl.addLayout(level_row, 1, 1)

        # Voltage presets
        self._v_presets = QHBoxLayout()
        for lbl, val in [("0V",0),("0.5V",0.5),("1V",1),
                          ("1.8V",1.8),("3.3V",3.3),("5V",5)]:
            b = QPushButton(lbl)
            b.setFixedWidth(52)
            b.clicked.connect(
                lambda _, v=val: (self._level_spin.setValue(v),
                                  self._set_level(v)))
            self._v_presets.addWidget(b)
        self._v_presets.addStretch()
        cl.addLayout(self._v_presets, 2, 1)

        # Current presets
        self._i_presets = QHBoxLayout()
        for lbl, val in [("0A",0),("1mA",0.001),("10mA",0.01),
                          ("100mA",0.1),("500mA",0.5),("1A",1.0)]:
            b = QPushButton(lbl)
            b.setFixedWidth(56)
            b.clicked.connect(
                lambda _, v=val: (self._level_spin.setValue(v),
                                  self._set_level(v)))
            self._i_presets.addWidget(b)
        self._i_presets.addStretch()
        cl.addLayout(self._i_presets, 3, 1)

        # Compliance
        cl.addWidget(self._sub("Compliance Limit"), 4, 0)
        comp_row = QHBoxLayout()
        self._comp_spin = QDoubleSpinBox()
        self._comp_spin.setRange(0.000001, 1.0)
        self._comp_spin.setValue(0.1)
        self._comp_spin.setDecimals(4)
        self._comp_spin.setSingleStep(0.01)
        self._comp_spin.setFixedWidth(120)
        self._comp_unit = QLabel("A limit")
        self._comp_unit.setStyleSheet("color:#666; font-size:15pt;")
        comp_row.addWidget(self._comp_spin)
        comp_row.addWidget(self._comp_unit)
        comp_row.addStretch()
        cl.addLayout(comp_row, 4, 1)

        cl.addWidget(hline(), 5, 0, 1, 3)

        # Action buttons
        btn_row = QHBoxLayout()
        apply_btn  = QPushButton("Apply Settings")
        self._on_btn  = QPushButton("⬤  Output ON")
        self._off_btn = QPushButton("⬤  Output OFF")
        self._on_btn.setStyleSheet(
            "background:#003322; color:#00d4aa; border-color:#00d4aa; font-weight:bold;")
        self._off_btn.setStyleSheet(
            "background:#330000; color:#ff6666; border-color:#ff4444; font-weight:bold;")
        for b in [apply_btn, self._on_btn, self._off_btn]:
            b.setFixedWidth(130)
            btn_row.addWidget(b)
        btn_row.addStretch()
        cl.addLayout(btn_row, 6, 0, 1, 3)

        apply_btn.clicked.connect(self._apply)
        self._on_btn.clicked.connect(self._enable)
        self._off_btn.clicked.connect(self._disable)

        root.addWidget(ctrl_box)
        root.addStretch()

        # Show voltage presets by default
        self._show_presets("voltage")

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:28pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _show_presets(self, mode):
        """Show voltage or current preset buttons."""
        for i in range(self._v_presets.count()):
            item = self._v_presets.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(mode == "voltage")
        for i in range(self._i_presets.count()):
            item = self._i_presets.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(mode == "current")

    def _on_mode_change(self):
        mode = "voltage" if self._mode_bg.checkedId() == 0 else "current"
        self._level_unit.setText("V" if mode == "voltage" else "A")
        self._comp_unit.setText(
            "A limit" if mode == "voltage" else "V limit")
        self._level_spin.setRange(
            *( (-200, 200) if mode == "voltage" else (-1, 1) ))
        self._comp_spin.setRange(
            *( (0.000001, 1.0) if mode == "voltage" else (0.001, 200) ))
        self._show_presets(mode)
        bias = app_state.bias
        if bias:
            threading.Thread(
                target=bias.set_mode, args=(mode,),
                daemon=True).start()

    def _apply(self):
        self._set_level(self._level_spin.value())
        self._set_compliance(self._comp_spin.value())

    def _set_level(self, val):
        bias = app_state.bias
        if bias:
            threading.Thread(
                target=bias.set_level, args=(val,),
                daemon=True).start()

    def _set_compliance(self, val):
        bias = app_state.bias
        if bias:
            threading.Thread(
                target=bias.set_compliance, args=(val,),
                daemon=True).start()

    def _enable(self):
        self._apply()
        bias = app_state.bias
        if bias:
            threading.Thread(target=bias.enable, daemon=True).start()

    def _disable(self):
        bias = app_state.bias
        if bias:
            threading.Thread(target=bias.disable, daemon=True).start()

    def update_status(self, status):
        if status.error:
            self._state_w._val.setText("ERROR")
            self._state_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ff6666;")
            return

        self._v_w._val.setText(f"{status.actual_voltage:.4f} V")
        self._i_w._val.setText(f"{status.actual_current*1000:.3f} mA")
        self._p_w._val.setText(f"{status.actual_power*1000:.2f} mW")
        self._comp_w._val.setText(
            f"{status.compliance*1000:.1f} mA"
            if status.mode == "voltage"
            else f"{status.compliance:.2f} V")

        if status.output_on:
            self._state_w._val.setText("ON ●")
            self._state_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#00d4aa;")
        else:
            self._state_w._val.setText("OFF ○")
            self._state_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#444;")


# ------------------------------------------------------------------ #
#  Tab 6: Stage                                                       #
# ------------------------------------------------------------------ #

class StageTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Position readouts
        pos_box = QGroupBox("Current Position")
        pl = QHBoxLayout(pos_box)
        self._x_w = self._readout("X",      "--", "#00d4aa")
        self._y_w = self._readout("Y",      "--", "#ffaa44")
        self._z_w = self._readout("Z",      "--", "#6699ff")
        self._st_w = self._readout("STATUS","UNKNOWN","#555")
        for w in [self._x_w, self._y_w, self._z_w, self._st_w]:
            pl.addWidget(w)
        root.addWidget(pos_box)

        # Absolute move
        abs_box = QGroupBox("Move To  (absolute μm)")
        al = QGridLayout(abs_box)
        al.setSpacing(8)

        self._ax = self._axis_spin("X", -50000, 50000)
        self._ay = self._axis_spin("Y", -50000, 50000)
        self._az = self._axis_spin("Z",      0, 25000)

        for col, (lbl, spin) in enumerate(
                [("X (μm)", self._ax), ("Y (μm)", self._ay),
                 ("Z (μm)", self._az)]):
            al.addWidget(QLabel(lbl), 0, col*2)
            al.addWidget(spin, 0, col*2+1)

        move_btn = QPushButton("Move To")
        move_btn.setObjectName("primary")
        move_btn.setFixedWidth(90)
        move_btn.clicked.connect(self._move_to)
        al.addWidget(move_btn, 0, 6)
        root.addWidget(abs_box)

        # Relative jog
        jog_box = QGroupBox("Jog  (relative μm)")
        jl = QGridLayout(jog_box)
        jl.setSpacing(6)

        # Step size selector
        jl.addWidget(QLabel("Step size:"), 0, 0)
        self._step_combo = QComboBox()
        for v in ["0.1", "1", "10", "100", "1000", "5000"]:
            self._step_combo.addItem(f"{v} μm", float(v))
        self._step_combo.setCurrentIndex(3)   # 100μm default
        self._step_combo.setFixedWidth(100)
        jl.addWidget(self._step_combo, 0, 1)

        # XY jog pad
        jl.addWidget(self._jog_pad(), 1, 0, 1, 3)

        # Z jog
        z_col = QVBoxLayout()
        z_col.setAlignment(Qt.AlignCenter)
        z_col.addWidget(QLabel("Z", alignment=Qt.AlignCenter))
        btn_zup  = QPushButton("▲")
        btn_zdn  = QPushButton("▼")
        for b in [btn_zup, btn_zdn]:
            b.setFixedSize(50, 36)
        btn_zup.clicked.connect(lambda: self._jog(z= self._step()))
        btn_zdn.clicked.connect(lambda: self._jog(z=-self._step()))
        z_col.addWidget(btn_zup)
        z_col.addWidget(btn_zdn)
        jl.addLayout(z_col, 1, 3)

        root.addWidget(jog_box)

        # Home + Stop row
        ctrl_row = QHBoxLayout()
        home_xyz = QPushButton("⌂  Home All")
        home_xy  = QPushButton("⌂  Home XY")
        home_z   = QPushButton("⌂  Home Z")
        stop_btn = QPushButton("■  STOP")
        stop_btn.setObjectName("danger")
        for b in [home_xyz, home_xy, home_z]:
            b.setFixedWidth(110)
            ctrl_row.addWidget(b)
        ctrl_row.addStretch()
        stop_btn.setFixedWidth(110)
        ctrl_row.addWidget(stop_btn)

        home_xyz.clicked.connect(lambda: self._home("xyz"))
        home_xy.clicked.connect( lambda: self._home("xy"))
        home_z.clicked.connect(  lambda: self._home("z"))
        stop_btn.clicked.connect(self._stop)
        root.addLayout(ctrl_row)
        root.addStretch()

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:31pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _axis_spin(self, label, lo, hi):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(0.0)
        s.setDecimals(2)
        s.setSingleStep(1.0)
        s.setFixedWidth(110)
        return s

    def _jog_pad(self):
        """Build a directional XY jog pad."""
        pad = QWidget()
        g   = QGridLayout(pad)
        g.setSpacing(4)

        arrows = {
            (0, 1): ("▲",  lambda: self._jog(y= self._step())),
            (2, 1): ("▼",  lambda: self._jog(y=-self._step())),
            (1, 0): ("◀",  lambda: self._jog(x=-self._step())),
            (1, 2): ("▶",  lambda: self._jog(x= self._step())),
            (0, 0): ("↖",  lambda: self._jog(x=-self._step(), y= self._step())),
            (0, 2): ("↗",  lambda: self._jog(x= self._step(), y= self._step())),
            (2, 0): ("↙",  lambda: self._jog(x=-self._step(), y=-self._step())),
            (2, 2): ("↘",  lambda: self._jog(x= self._step(), y=-self._step())),
        }
        for (row, col), (symbol, fn) in arrows.items():
            b = QPushButton(symbol)
            b.setFixedSize(46, 40)
            b.setStyleSheet("font-size:22pt;")
            b.clicked.connect(fn)
            g.addWidget(b, row, col)

        return pad

    def _step(self) -> float:
        return self._step_combo.currentData()

    def _jog(self, x=0.0, y=0.0, z=0.0):
        stage = app_state.stage
        if stage:
            threading.Thread(
                target=stage.move_by,
                kwargs={"x": x, "y": y, "z": z, "wait": False},
                daemon=True).start()

    def _move_to(self):
        stage = app_state.stage
        if stage:
            threading.Thread(
                target=stage.move_to,
                kwargs={"x": self._ax.value(),
                        "y": self._ay.value(),
                        "z": self._az.value(),
                        "wait": False},
                daemon=True).start()

    def _home(self, axes: str):
        stage = app_state.stage
        if stage:
            threading.Thread(
                target=stage.home, args=(axes,),
                daemon=True).start()

    def _stop(self):
        stage = app_state.stage
        if stage:
            threading.Thread(target=stage.stop, daemon=True).start()

    def update_status(self, status):
        if status.error:
            self._st_w._val.setText("ERROR")
            self._st_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:31pt; color:#ff6666;")
            return

        p = status.position
        self._x_w._val.setText(f"{p.x:+.2f} μm")
        self._y_w._val.setText(f"{p.y:+.2f} μm")
        self._z_w._val.setText(f"{p.z:.2f} μm")

        # Update absolute move spinboxes to current position
        self._ax.setValue(p.x)
        self._ay.setValue(p.y)
        self._az.setValue(p.z)

        if status.moving:
            self._st_w._val.setText("MOVING ↔")
            self._st_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:31pt; color:#ffaa44;")
        elif status.homed:
            self._st_w._val.setText("READY ✓")
            self._st_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:31pt; color:#00d4aa;")
        else:
            self._st_w._val.setText("NOT HOMED")
            self._st_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:31pt; color:#888;")


# ------------------------------------------------------------------ #
#  Tab 7: ROI                                                         #
# ------------------------------------------------------------------ #

class RoiTab(QWidget):
    """
    ROI selection tab.

    Left  — interactive RoiSelector (draw box on live image)
    Right — ROI info, presets, apply/clear controls
    """

    def __init__(self):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- Left: selector canvas ----
        left = QVBoxLayout()
        sel_box = QGroupBox("Draw ROI  (click and drag on image)")
        sl = QVBoxLayout(sel_box)
        self._selector = RoiSelector()
        self._selector.roi_changed.connect(self._on_roi_changed)
        sl.addWidget(self._selector)
        left.addWidget(sel_box)
        root.addLayout(left, 3)

        # ---- Right: controls ----
        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 1)

        # Current ROI readout
        info_box = QGroupBox("Current ROI")
        il = QGridLayout(info_box)

        self._roi_labels = {}
        for r, (key, label) in enumerate([
                ("x",  "X origin"), ("y", "Y origin"),
                ("w",  "Width"),    ("h", "Height"),
                ("area", "Area"),   ("status", "Status")]):
            il.addWidget(self._sub(label), r, 0)
            lbl = QLabel("--")
            lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#00d4aa;")
            il.addWidget(lbl, r, 1)
            self._roi_labels[key] = lbl

        right.addWidget(info_box)

        # Preset ROIs
        preset_box = QGroupBox("Presets")
        pl = QVBoxLayout(preset_box)
        self._frame_hw = (1200, 1920)   # updated when frames arrive

        presets = [
            ("Centre  25%",  0.375, 0.375, 0.25,  0.25),
            ("Centre  50%",  0.25,  0.25,  0.50,  0.50),
            ("Top-left  25%",0.0,   0.0,   0.25,  0.25),
            ("Full frame",   0.0,   0.0,   1.0,   1.0),
        ]
        for label, rx, ry, rw, rh in presets:
            b = QPushButton(label)
            b.clicked.connect(
                lambda _, rx=rx, ry=ry, rw=rw, rh=rh:
                    self._apply_preset(rx, ry, rw, rh))
            pl.addWidget(b)
        right.addWidget(preset_box)

        # Manual entry
        manual_box = QGroupBox("Manual Entry  (pixels)")
        ml = QGridLayout(manual_box)
        self._mx = self._ispin(0, 9999, 0)
        self._my = self._ispin(0, 9999, 0)
        self._mw = self._ispin(1, 9999, 400)
        self._mh = self._ispin(1, 9999, 300)
        for r, (lbl, sp) in enumerate([
                ("X", self._mx), ("Y", self._my),
                ("W", self._mw), ("H", self._mh)]):
            ml.addWidget(QLabel(lbl), r, 0)
            ml.addWidget(sp, r, 1)
        apply_btn = QPushButton("Apply Manual ROI")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply_manual)
        ml.addWidget(apply_btn, 4, 0, 1, 2)
        right.addWidget(manual_box)

        # Apply to acquisition / clear
        ctrl_box = QGroupBox("Acquisition")
        ctl = QVBoxLayout(ctrl_box)
        self._apply_acq_btn = QPushButton("✓  Apply ROI to Acquisition")
        self._apply_acq_btn.setObjectName("primary")
        self._clear_acq_btn = QPushButton("✕  Clear  (use full frame)")
        self._apply_acq_btn.clicked.connect(self._apply_to_acq)
        self._clear_acq_btn.clicked.connect(self._clear_acq)
        self._acq_status = QLabel("No ROI active")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        ctl.addWidget(self._apply_acq_btn)
        ctl.addWidget(self._clear_acq_btn)
        ctl.addWidget(self._acq_status)
        right.addWidget(ctrl_box)
        right.addStretch()

    # ---------------------------------------------------------------- #

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _ispin(self, lo, hi, val):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setFixedWidth(90)
        return s

    def update_frame(self, frame_data):
        """Feed latest live frame into the selector canvas."""
        self._frame_hw = frame_data.shape[:2]
        self._selector.set_frame(frame_data)

    def _on_roi_changed(self, roi: Roi):
        """Update info labels when ROI changes."""
        if roi.is_empty:
            for k, l in self._roi_labels.items():
                l.setText("--")
            self._roi_labels["status"].setText("Full frame")
            self._roi_labels["status"].setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#555;")
        else:
            self._roi_labels["x"].setText(str(roi.x))
            self._roi_labels["y"].setText(str(roi.y))
            self._roi_labels["w"].setText(str(roi.w))
            self._roi_labels["h"].setText(str(roi.h))
            self._roi_labels["area"].setText(f"{roi.area:,} px")
            self._roi_labels["status"].setText("ROI defined")
            self._roi_labels["status"].setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#ffaa44;")

    def _apply_preset(self, rx, ry, rw, rh):
        fh, fw = self._frame_hw
        x = int(rx * fw)
        y = int(ry * fh)
        w = int(rw * fw)
        h = int(rh * fh)
        if w >= fw and h >= fh:
            self._selector._canvas.clear_roi()
        else:
            self._selector._canvas.set_roi(Roi(x=x, y=y, w=w, h=h))

    def _apply_manual(self):
        roi = Roi(x=self._mx.value(), y=self._my.value(),
                  w=self._mw.value(), h=self._mh.value())
        self._selector._canvas.set_roi(roi)

    def _apply_to_acq(self):
        roi = self._selector.roi
        pl = app_state.pipeline
        if pl:
            pl.roi = roi if not roi.is_empty else None
        msg = str(roi) if not roi.is_empty else "Full frame (no ROI)"
        self._acq_status.setText(f"Active: {msg}")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#00d4aa;")
        signals.log_message.emit(f"ROI applied to acquisition: {msg}")

    def _clear_acq(self):
        self._selector._canvas.clear_roi()
        pl = app_state.pipeline
        if pl:
            pl.roi = None
        self._acq_status.setText("No ROI active (full frame)")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        signals.log_message.emit("ROI cleared — acquisition using full frame")


# ------------------------------------------------------------------ #
#  Tab 8: Autofocus                                                   #
# ------------------------------------------------------------------ #

class AutofocusTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- Status row ----
        status_box = QGroupBox("Status")
        sl = QHBoxLayout(status_box)
        self._state_w  = self._readout("STATE",     "IDLE",  "#555")
        self._best_z_w = self._readout("BEST Z",    "--",    "#00d4aa")
        self._score_w  = self._readout("SCORE",     "--",    "#ffaa44")
        self._time_w   = self._readout("TIME",      "--",    "#6699ff")
        for w in [self._state_w, self._best_z_w,
                  self._score_w, self._time_w]:
            sl.addWidget(w)
        root.addWidget(status_box)

        # ---- Settings + Plot side by side ----
        mid = QHBoxLayout()
        root.addLayout(mid)

        # Settings
        cfg_box = QGroupBox("Settings")
        cl = QGridLayout(cfg_box)
        cl.setSpacing(8)

        from ui.help import help_label

        def row(label, widget, r, topic=None):
            lbl_widget = help_label(label, topic) if topic else self._sub(label)
            cl.addWidget(lbl_widget, r, 0)
            cl.addWidget(widget,     r, 1)

        self._strategy = QComboBox()
        for s in ["sweep", "hill_climb"]:
            self._strategy.addItem(s)
        row("Strategy", self._strategy, 0, "autofocus")

        self._metric = QComboBox()
        for m in ["laplacian","tenengrad","normalized","fft","brenner"]:
            self._metric.addItem(m)
        row("Focus metric", self._metric, 1)

        self._z_start = self._dspin(-2000, 0,     -500, "μm")
        self._z_end   = self._dspin(0,     2000,   500, "μm")
        row("Z start (rel)", self._z_start, 2, "af_sweep_range")
        row("Z end (rel)",   self._z_end,   3)

        self._coarse = self._dspin(1, 500,  50, "μm")
        self._fine   = self._dspin(0.1, 50,  5, "μm")
        row("Coarse step", self._coarse, 4)
        row("Fine step",   self._fine,   5)

        self._n_avg    = QSpinBox()
        self._n_avg.setRange(1, 20)
        self._n_avg.setValue(2)
        self._n_avg.setFixedWidth(80)
        row("Avg frames", self._n_avg, 6)

        self._settle = QSpinBox()
        self._settle.setRange(0, 2000)
        self._settle.setValue(50)
        self._settle.setSuffix(" ms")
        self._settle.setFixedWidth(80)
        row("Settle delay", self._settle, 7)

        mid.addWidget(cfg_box, 1)

        # Focus curve plot
        plot_box = QGroupBox("Focus Curve")
        pl = QVBoxLayout(plot_box)
        self._plot = FocusPlot()
        pl.addWidget(self._plot)
        mid.addWidget(plot_box, 2)

        # ---- Run controls ----
        ctrl = QHBoxLayout()
        self._run_btn   = QPushButton("▶  Run Autofocus")
        self._run_btn.setObjectName("primary")
        self._abort_btn = QPushButton("■  Abort")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setEnabled(False)
        self._run_btn.setFixedWidth(150)
        self._abort_btn.setFixedWidth(100)
        ctrl.addWidget(self._run_btn)
        ctrl.addWidget(self._abort_btn)
        ctrl.addStretch()
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setFixedWidth(300)
        ctrl.addWidget(self._prog)
        root.addLayout(ctrl)

        # ---- Log ----
        log_box = QGroupBox("Log")
        ll = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(80)
        self._log.setMaximumHeight(140)
        ll.addWidget(self._log)
        root.addWidget(log_box)

        self._run_btn.clicked.connect(self._run)
        self._abort_btn.clicked.connect(self._abort)

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:28pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _dspin(self, lo, hi, val, suffix=""):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setDecimals(1)
        s.setSingleStep(10)
        s.setFixedWidth(100)
        if suffix:
            s.setSuffix(f" {suffix}")
        return s

    def _build_cfg(self) -> dict:
        """Read current UI settings into a config dict."""
        return {
            "driver":       "sweep" if self._strategy.currentText() == "sweep"
                            else "hill_climb",
            "strategy":     self._strategy.currentText(),
            "metric":       self._metric.currentText(),
            "z_start":      self._z_start.value(),
            "z_end":        self._z_end.value(),
            "coarse_step":  self._coarse.value(),
            "fine_step":    self._fine.value(),
            "n_avg":        self._n_avg.value(),
            "settle_ms":    self._settle.value(),
            "move_to_best": True,
        }

    def _run(self):
        global af_driver
        cam   = app_state.cam
        stage = app_state.stage
        if cam is None:
            self.log("No camera connected")
            return

        cfg = self._build_cfg()
        af_driver = create_autofocus(cfg, cam, stage)
        af_driver.on_progress = lambda r: signals.af_progress.emit(r)
        af_driver.on_complete = lambda r: signals.af_complete.emit(r)

        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._prog.setValue(0)
        self._plot.clear()
        self.log(f"Starting {cfg['strategy']} autofocus "
                 f"(metric: {cfg['metric']})...")

        import threading
        threading.Thread(target=af_driver.run, daemon=True).start()

    def _abort(self):
        if af_driver:
            af_driver.abort()

    def _set_busy(self, busy):
        self._run_btn.setEnabled(not busy)
        self._abort_btn.setEnabled(busy)

    def update_progress(self, result):
        self._plot.update(result.z_positions, result.scores)
        self.log(result.message)

        # Estimate progress as fraction of z range covered
        if result.z_positions:
            z_arr  = result.z_positions
            z_span = abs(self._z_end.value() - self._z_start.value()) * 2
            covered = abs(max(z_arr) - min(z_arr))
            pct = min(int(covered / max(z_span, 1) * 100), 95)
            self._prog.setValue(pct)

        self._state_w._val.setText("RUNNING")
        self._state_w._val.setStyleSheet(
            "font-family:Menlo,monospace; font-size:28pt; color:#ffaa44;")

    def update_complete(self, result):
        self._set_busy(False)
        self._prog.setValue(100)
        self._plot.update(result.z_positions, result.scores,
                          best_z=result.best_z)
        self.log(result.message)

        if result.state == AfState.COMPLETE:
            self._state_w._val.setText("COMPLETE ✓")
            self._state_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#00d4aa;")
            self._best_z_w._val.setText(f"{result.best_z:.2f} μm")
            self._score_w._val.setText(f"{result.best_score:.4f}")
            self._time_w._val.setText(f"{result.duration_s:.1f} s")
        else:
            self._state_w._val.setText(result.state.name)
            self._state_w._val.setStyleSheet(
                "font-family:Menlo,monospace; font-size:28pt; color:#ff6666;")

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}]  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())


class FocusPlot(QWidget):
    """Live focus score vs Z plot with best-focus marker."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._z      = []
        self._scores = []
        self._best_z = None

    def clear(self):
        self._z      = []
        self._scores = []
        self._best_z = None
        self.update()

    def update(self, z, scores, best_z=None):
        self._z      = list(z)
        self._scores = list(scores)
        self._best_z = best_z
        self.repaint()

    def paintEvent(self, e):
        p   = QPainter(self)
        W   = self.width()
        H   = self.height()
        pad = 40

        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        if len(self._z) < 2:
            p.setPen(QPen(QColor(60, 60, 60)))
            p.setFont(QFont("Menlo", 14))
            p.drawText(W//2 - 80, H//2, "No data yet")
            p.end()
            return

        z_min, z_max = min(self._z), max(self._z)
        s_min, s_max = min(self._scores), max(self._scores)
        z_span = max(z_max - z_min, 1e-6)
        s_span = max(s_max - s_min, 1e-6)

        def tx(z): return int(pad + (z - z_min) / z_span * (W - 2*pad))
        def ty(s): return int(H - pad - (s - s_min) / s_span * (H - 2*pad))

        # Grid
        p.setFont(QFont("Menlo", 11))
        for i in range(5):
            frac = i / 4
            y    = int(pad + frac * (H - 2*pad))
            sv   = s_max - frac * s_span
            p.setPen(QPen(QColor(35, 35, 35)))
            p.drawLine(pad, y, W - pad, y)
            p.setPen(QPen(QColor(70, 70, 70)))
            p.drawText(2, y + 4, f"{sv:.3f}")

        for i in range(5):
            frac = i / 4
            x    = int(pad + frac * (W - 2*pad))
            zv   = z_min + frac * z_span
            p.setPen(QPen(QColor(35, 35, 35)))
            p.drawLine(x, pad, x, H - pad)
            p.setPen(QPen(QColor(70, 70, 70)))
            p.drawText(x - 15, H - 5, f"{zv:.0f}")

        # Score curve
        p.setPen(QPen(QColor(0, 212, 170), 2))
        pts = [(tx(z), ty(s)) for z, s in zip(self._z, self._scores)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

        # Data points
        p.setBrush(QBrush(QColor(0, 212, 170)))
        for x, y in pts:
            p.drawEllipse(x-3, y-3, 6, 6)

        # Best-focus marker
        if self._best_z is not None:
            bx = tx(self._best_z)
            p.setPen(QPen(QColor(255, 170, 68), 1, Qt.DashLine))
            p.drawLine(bx, pad, bx, H - pad)
            p.setPen(QPen(QColor(255, 170, 68)))
            p.setFont(QFont("Menlo", 12))
            p.drawText(bx + 4, pad + 14,
                       f"best: {self._best_z:.1f}μm")

        # Axis labels
        p.setPen(QPen(QColor(80, 80, 80)))
        p.setFont(QFont("Menlo", 12))
        p.drawText(W//2 - 20, H - 1, "Z position (μm)")

        p.end()


# ------------------------------------------------------------------ #
#  Tab 8: Log                                                         #
# ------------------------------------------------------------------ #

class LogTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background:#0d0d0d; color:#666; "
            "font-family:Menlo,monospace; font-size:14pt; "
            "border:none;")
        root.addWidget(self._log)
        clr = QPushButton("Clear")
        clr.setFixedWidth(80)
        clr.clicked.connect(self._log.clear)
        root.addWidget(clr)

    def append(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"<span style='color:#444'>[{ts}]</span>  {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())


# ------------------------------------------------------------------ #
#  Header status bar                                                  #
# ------------------------------------------------------------------ #

class _ModeToggle(QWidget):
    """
    Compact iOS-style toggle switch with STANDARD / ADVANCED labels.

    Left  (unchecked) = Standard   teal pill
    Right (checked)   = Advanced   blue pill

    Emits toggled(bool) — True means Advanced.
    """

    toggled = pyqtSignal(bool)

    _W, _H   = 160, 26          # total widget size
    _PAD     = 2                 # padding around pill
    _RADIUS  = 11                # pill corner radius

    _COL_STANDARD = QColor(0,  212, 170)   # teal
    _COL_ADVANCED = QColor(80, 120, 220)   # blue
    _COL_TRACK    = QColor(30,  30,  30)
    _COL_BORDER   = QColor(50,  50,  50)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._advanced  = False
        self._anim_pos  = 0.0      # 0.0 = standard, 1.0 = advanced
        self._timer     = QTimer(self)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Standard: guided 4-step wizard\n"
            "Advanced: full expert tab interface")

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def is_advanced(self) -> bool:
        return self._advanced

    def set_checked(self, advanced: bool, emit: bool = True):
        if advanced == self._advanced:
            return
        self._advanced = advanced
        self._timer.start()
        if emit:
            self.toggled.emit(advanced)

    # ---------------------------------------------------------------- #
    #  Animation                                                        #
    # ---------------------------------------------------------------- #

    def _tick(self):
        target = 1.0 if self._advanced else 0.0
        step   = 0.12
        if abs(self._anim_pos - target) < step:
            self._anim_pos = target
            self._timer.stop()
        else:
            self._anim_pos += step if target > self._anim_pos else -step
        self.update()

    # ---------------------------------------------------------------- #
    #  Painting                                                         #
    # ---------------------------------------------------------------- #

    def paintEvent(self, _):
        p  = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H   = self._W, self._H
        pad    = self._PAD
        r      = self._RADIUS

        # Track
        p.setPen(QPen(self._COL_BORDER, 1))
        p.setBrush(self._COL_TRACK)
        p.drawRoundedRect(0, 0, W, H, r + pad, r + pad)

        # Interpolate pill colour
        t   = self._anim_pos
        sc  = self._COL_STANDARD
        ac  = self._COL_ADVANCED
        col = QColor(
            int(sc.red()   + (ac.red()   - sc.red())   * t),
            int(sc.green() + (ac.green() - sc.green()) * t),
            int(sc.blue()  + (ac.blue()  - sc.blue())  * t))

        # Pill position — travels from left half to right half
        half      = W // 2
        pill_x    = pad + int((half - pad) * t)
        pill_w    = half - pad
        pill_rect = (pill_x, pad, pill_w, H - pad * 2)

        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(*pill_rect, r, r)

        # Labels
        p.setPen(Qt.NoPen)   # reset
        font = QFont("Helvetica", 11, QFont.Bold)
        p.setFont(font)

        # STANDARD label (left half)
        std_active = t < 0.5
        p.setPen(QColor(255, 255, 255, 220 if std_active else 60))
        p.drawText(0, 0, half, H, Qt.AlignCenter, "STANDARD")

        # ADVANCED label (right half)
        adv_active = t >= 0.5
        p.setPen(QColor(255, 255, 255, 220 if adv_active else 60))
        p.drawText(half, 0, half, H, Qt.AlignCenter, "ADVANCED")

        p.end()

    # ---------------------------------------------------------------- #
    #  Interaction                                                      #
    # ---------------------------------------------------------------- #

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_checked(not self._advanced)


# ------------------------------------------------------------------ #
#  Status header                                                       #
# ------------------------------------------------------------------ #

class StatusHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setMaximumHeight(64)
        self.setMinimumHeight(44)
        self.setStyleSheet("background:#111; border-bottom:1px solid #252525;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(14)

        # ---- Logo + SanjINSIGHT name stacked vertically ----
        logo_col = QWidget()
        logo_col.setStyleSheet("background:transparent;")
        logo_col_lay = QVBoxLayout(logo_col)
        logo_col_lay.setContentsMargins(0, 4, 0, 4)
        logo_col_lay.setSpacing(1)

        logo_path = os.path.join(
            os.path.dirname(__file__), "assets", "microsanj-logo.svg")
        logo_loaded = False
        if os.path.exists(logo_path):
            try:
                from PyQt5.QtSvg import QSvgWidget
                svg = QSvgWidget(logo_path)
                svg.setFixedSize(130, 26)
                svg.setStyleSheet("background:transparent;")
                logo_col_lay.addWidget(svg)
                logo_loaded = True
            except Exception:
                pass

        if not logo_loaded:
            fallback = QLabel("MICROSANJ")
            fallback.setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; "
                "color:#fff; letter-spacing:3px; background:transparent;")
            logo_col_lay.addWidget(fallback)



        lay.addWidget(logo_col)

        # ---- Divider ----
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet("color:#2a2a2a;")
        div.setFixedHeight(28)
        lay.addWidget(div)

        # ---- Title removed ----

        # ---- Mode toggle (right next to the title) ----
        lay.addSpacing(10)
        self._mode_toggle = _ModeToggle()
        lay.addWidget(self._mode_toggle)
        lay.addSpacing(4)

        lay.addStretch()

        # ---- Active profile indicator ----
        self._profile_pill = QWidget()
        self._profile_pill.setMaximumHeight(36)
        self._profile_pill.setMinimumWidth(60)
        self._profile_pill.setStyleSheet(
            "background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;")
        pp_lay = QHBoxLayout(self._profile_pill)
        pp_lay.setContentsMargins(10, 0, 10, 0)
        pp_lay.setSpacing(6)
        pp_icon = QLabel("◈")
        pp_icon.setStyleSheet("color:#333; font-size:14pt;")
        self._profile_name_lbl = QLabel("No profile")
        self._profile_name_lbl.setStyleSheet(
            "font-size:14pt; color:#666; font-family:Menlo,monospace;")
        pp_lay.addWidget(pp_icon)
        pp_lay.addWidget(self._profile_name_lbl)
        self._profile_pill_icon = pp_icon
        lay.addWidget(self._profile_pill)

        # ---- Divider ----
        div2 = QFrame()
        div2.setFrameShape(QFrame.VLine)
        div2.setStyleSheet("color:#2a2a2a;")
        div2.setFixedHeight(28)
        lay.addWidget(div2)

        # ---- Status dots ----
        self._cam_dot   = self._dot("Camera")
        self._tec1_dot  = self._dot("TEC 1")
        self._tec2_dot  = self._dot("TEC 2")
        self._fpga_dot  = self._dot("FPGA")
        self._bias_dot  = self._dot("Bias")
        self._stage_dot = self._dot("Stage")
        for d in [self._cam_dot, self._tec1_dot, self._tec2_dot,
                  self._fpga_dot, self._bias_dot, self._stage_dot]:
            lay.addWidget(d)

        # ---- Demo mode banner (hidden until activated) ----
        self._demo_banner = QWidget()
        self._demo_banner.setVisible(False)
        self._demo_banner.setStyleSheet(
            "background:#ff990022; border:1px solid #ff990066; border-radius:4px;")
        db_lay = QHBoxLayout(self._demo_banner)
        db_lay.setContentsMargins(10, 0, 10, 0)
        db_lay.setSpacing(6)
        db_icon = QLabel("▶")
        db_icon.setStyleSheet("color:#ff9900; font-size:13pt;")
        db_text = QLabel("DEMO MODE")
        db_text.setStyleSheet(
            "color:#ff9900; font-size:12pt; font-family:Menlo,monospace; "
            "letter-spacing:2px; font-weight:bold;")
        db_lay.addWidget(db_icon)
        db_lay.addWidget(db_text)
        self._demo_banner.setToolTip(
            "Running with simulated hardware — no instrument connected.\n"
            "All measurements use synthetic data.")
        lay.addWidget(self._demo_banner)

        # ---- Emergency Stop button (always visible, right edge) ------
        lay.addSpacing(8)
        self._estop_btn = QPushButton("■  STOP")
        self._estop_btn.setFixedHeight(36)
        self._estop_btn.setMinimumWidth(90)
        self._estop_btn.setToolTip(
            "Emergency Stop — immediately disables bias output, "
            "all TECs, stage motion, and aborts any active acquisition.\n"
            "Hardware stays connected. Click 'Clear' to re-arm.")
        self._estop_btn.setStyleSheet("""
            QPushButton {
                background: #5a0000;
                color: #ff4444;
                border: 2px solid #aa0000;
                border-radius: 5px;
                font-size: 13pt;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #7a0000;
                color: #ff6666;
                border-color: #cc2222;
            }
            QPushButton:pressed {
                background: #3a0000;
            }
            QPushButton[armed="false"] {
                background: #1a1a1a;
                color: #555;
                border: 1px solid #2a2a2a;
            }
            QPushButton[armed="false"]:hover {
                background: #222;
                color: #888;
                border-color: #444;
            }
        """)
        self._estop_btn.setProperty("armed", "true")
        self._estop_armed = True
        lay.addWidget(self._estop_btn)

    def _dot(self, label):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet("color:#555; font-size:14pt;")
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size:14pt; color:#888; letter-spacing:1px;")
        h.addWidget(dot)
        h.addWidget(lbl)
        w._dot = dot
        return w

    def set_profile(self, profile):
        """Update the active profile indicator in the header."""
        from profiles.profiles import CATEGORY_ACCENTS
        if profile is None:
            self._profile_name_lbl.setText("No profile")
            self._profile_name_lbl.setStyleSheet(
                "font-size:14pt; color:#666; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet("color:#333; font-size:14pt;")
            self._profile_pill.setStyleSheet(
                "background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;")
        else:
            accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")
            # Truncate long names
            name = profile.name if len(profile.name) <= 28 else profile.name[:26] + "…"
            self._profile_name_lbl.setText(name)
            self._profile_name_lbl.setStyleSheet(
                f"font-size:14pt; color:{accent}; font-family:Menlo,monospace;")
            self._profile_pill_icon.setStyleSheet(
                f"color:{accent}; font-size:14pt;")
            self._profile_pill.setStyleSheet(
                f"background:#111; border:1px solid {accent}44; border-radius:4px;")
            self._profile_pill.setToolTip(
                f"{profile.name}\n"
                f"C_T = {profile.ct_value:.3e} K⁻¹\n"
                f"{profile.category}  ·  {profile.wavelength_nm} nm")

    def connect_mode_toggle(self, callback):
        """Wire the mode toggle to a callback(advanced: bool)."""
        self._mode_toggle.toggled.connect(callback)

    def set_demo_mode(self, active: bool):
        """Show or hide the DEMO MODE banner in the header."""
        self._demo_banner.setVisible(active)

    def set_mode(self, advanced: bool):
        """Set the toggle position programmatically (no callback fired)."""
        self._mode_toggle.set_checked(advanced, emit=False)

    def connect_estop(self, on_stop, on_clear):
        """Wire E-Stop button: on_stop fires when armed & clicked, on_clear when latched & clicked."""
        def _clicked():
            if self._estop_armed:
                on_stop()
            else:
                on_clear()
        self._estop_btn.clicked.connect(_clicked)

    def set_estop_triggered(self):
        """Visually latch the button into STOPPED state."""
        self._estop_armed = False
        self._estop_btn.setText("⚠  STOPPED — Click to Clear")
        self._estop_btn.setProperty("armed", "false")
        self._estop_btn.setMinimumWidth(200)
        # Force Qt to re-evaluate the stylesheet property
        self._estop_btn.style().unpolish(self._estop_btn)
        self._estop_btn.style().polish(self._estop_btn)

    def set_estop_armed(self):
        """Reset button back to armed/ready state."""
        self._estop_armed = True
        self._estop_btn.setText("■  STOP")
        self._estop_btn.setProperty("armed", "true")
        self._estop_btn.setMinimumWidth(90)
        self._estop_btn.style().unpolish(self._estop_btn)
        self._estop_btn.style().polish(self._estop_btn)

    def add_device_manager_button(self, callback):
        """Add a ⚙ gear button that opens the Device Manager."""
        gear = QPushButton("⚙")
        gear.setFixedSize(30, 30)
        gear.setToolTip("Device Manager — manage hardware connections and drivers")
        gear.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#444;
                border:1px solid #2a2a2a; border-radius:4px;
                font-size:19pt;
            }
            QPushButton:hover { color:#888; background:#222; }
        """)
        gear.clicked.connect(callback)
        self.layout().addWidget(gear)

    def add_update_badge(self) -> "UpdateBadge":
        """Add the update-available badge to the header and return it."""
        from ui.update_dialog import UpdateBadge
        self._update_badge = UpdateBadge()
        self.layout().addWidget(self._update_badge)
        return self._update_badge

    def set_connected(self, which: str, ok: bool, tooltip: str = ""):
        color  = "#00d4aa" if ok else "#ff4444"
        target = {"camera": self._cam_dot,
                  "tec0":   self._tec1_dot,
                  "tec1":   self._tec2_dot,
                  "tec2":   self._tec2_dot,
                  "tec_meerstetter": self._tec1_dot,
                  "tec_atec":        self._tec2_dot,
                  "fpga":   self._fpga_dot,
                  "bias":   self._bias_dot,
                  "stage":  self._stage_dot}.get(which)
        if target:
            target._dot.setStyleSheet(f"color:{color}; font-size:14pt;")
            if tooltip:
                target.setToolTip(tooltip)

    def set_connecting(self, which: str):
        """Show amber 'connecting' state while device initializes."""
        target = {"camera": self._cam_dot,
                  "tec0":   self._tec1_dot,
                  "tec1":   self._tec2_dot,
                  "fpga":   self._fpga_dot,
                  "bias":   self._bias_dot,
                  "stage":  self._stage_dot}.get(which)
        if target:
            target._dot.setStyleSheet("color:#ff9900; font-size:14pt;")
            target.setToolTip("Connecting…")


# ------------------------------------------------------------------ #
#  Main Window                                                        #
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_VENDOR} {APP_NAME}  {version_string()}")

        # Fit the window within the available screen (respects macOS menu bar + dock)
        screen  = QApplication.primaryScreen().availableGeometry()
        win_w   = min(1400, int(screen.width()  * 0.92))
        win_h   = min(800,  int(screen.height() * 0.88))
        self.resize(win_w, win_h)
        self.setMinimumSize(480, 280)
        self.move(screen.x() + (screen.width()  - win_w) // 2,
                  screen.y() + (screen.height() - win_h) // 2)
        # Bounded thread pool — prevents unbounded thread spawning from rapid button clicks
        self._thread_pool = ThreadPoolExecutor(max_workers=4,
                                               thread_name_prefix="msanj_worker")
        self._build_ui()
        self._connect_signals()

    def _submit(self, fn, *args, done_cb=None, **kwargs) -> Future:
        """Submit work to the bounded thread pool.

        Args:
            fn:      Callable to run on the pool.
            done_cb: Optional callable(future) invoked on completion.
        Returns:
            concurrent.futures.Future
        """
        fut = self._thread_pool.submit(fn, *args, **kwargs)
        if done_cb:
            fut.add_done_callback(done_cb)
        return fut

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = StatusHeader()
        root.addWidget(self._header)

        # Tabs
        # Mode stack — index 0 = Standard (wizard), index 1 = Advanced (tabs)
        self._mode_stack = QStackedWidget()
        root.addWidget(self._mode_stack)

        # ---- Standard mode ----
        # (built after profile manager; added to stack below)

        # ---- Advanced mode: sidebar navigation ----
        adv_widget = QWidget()
        adv_layout = QVBoxLayout(adv_widget)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(0)

        self._nav = SidebarNav(app_name="SanjINSIGHT")
        adv_layout.addWidget(self._nav)

        hw = config.get("hardware")
        n_tecs = sum(1 for k in ["tec_meerstetter","tec_atec"]
                     if hw.get(k,{}).get("enabled", False))

        # Profile manager — scans user profiles from ~/.microsanj/profiles/
        self._profile_mgr = ProfileManager()
        self._profile_mgr.scan()

        self._acquire_tab  = AcquireTab()
        self._live_tab     = LiveTab()
        self._analysis_tab = AnalysisTab()
        self._camera_tab   = CameraTab()
        self._temp_tab     = TemperatureTab(max(n_tecs, 1))
        self._fpga_tab     = FpgaTab()
        self._bias_tab     = BiasTab()
        self._stage_tab    = StageTab()
        self._roi_tab      = RoiTab()
        self._af_tab       = AutofocusTab()
        self._cal_tab      = CalibrationTab()
        self._scan_tab     = ScanTab()
        self._profile_tab  = ProfileTab(self._profile_mgr)
        self._data_tab     = DataTab(session_mgr)
        self._log_tab      = LogTab()
        self._settings_tab = SettingsTab()

        # ── New enhancement tabs ──────────────────────────────────
        self._compare_tab  = ComparisonTab(session_manager=session_mgr)
        self._surface_tab  = SurfacePlotTab()
        self._recipe_tab   = RecipeTab(app_state=app_state)
        self._console_tab  = ScriptingConsoleTab(app_state=app_state)

        # Wire recipe RUN signal → apply recipe to hardware
        self._recipe_tab.recipe_run.connect(self._apply_recipe)

        # Wire Settings tab → manual update check
        self._settings_tab.check_for_updates_requested.connect(
            self._on_manual_update_check)

        # ── Register panels with the Bootstrap-style sidebar ─────
        from ui.sidebar_nav import NavItem as NI

        self._nav.add_section("MEASURE", [
            NI("Live",        "●",  self._live_tab),
            NI("Acquire",     "⊙",  self._acquire_tab),
            NI("Scan",        "⊞",  self._scan_tab),
        ])
        self._nav.add_section("ANALYSIS", [
            NI("Calibration", "⚖",  self._cal_tab),
            NI("Analysis",    "◈",  self._analysis_tab),
            NI("Compare",     "⇌",  self._compare_tab),
            NI("3D Surface",  "△",  self._surface_tab),
        ])
        self._nav.add_collapsible("Hardware", "⚙", [
            NI("Camera",      "▣",  self._camera_tab),
            NI("Temperature", "⊡",  self._temp_tab),
            NI("FPGA",        "⬡",  self._fpga_tab),
            NI("Bias Source", "⚡",  self._bias_tab),
            NI("Stage",       "✛",  self._stage_tab),
            NI("ROI",         "⬚",  self._roi_tab),
            NI("Autofocus",   "◉",  self._af_tab),
        ], collapsed=False)
        self._nav.add_section("SETUP", [
            NI("Profiles",    "◧",  self._profile_tab),
            NI("Recipes",     "≡",  self._recipe_tab),
        ])
        self._nav.add_section("TOOLS", [
            NI("Data",        "⊟",  self._data_tab),
            NI("Console",     "›_", self._console_tab),
            NI("Log",         "☰",  self._log_tab),
            NI("Settings",    "⚙",  self._settings_tab),
        ])
        self._nav.finish()
        self._nav.select_first()

        # Build wizard (Standard mode)
        self._wizard = StandardWizard(self._profile_mgr)

        # Add both to mode stack — Standard first (index 0)
        self._mode_stack.addWidget(self._wizard)
        self._mode_stack.addWidget(adv_widget)
        self._mode_stack.setCurrentIndex(0)   # default: Standard

        # Connect mode toggle button
        self._header.connect_mode_toggle(self._on_mode_change)

        # Restore last-used mode from preferences
        import config as _cfg
        saved_mode = _cfg.get_pref("ui.mode", "standard")
        if saved_mode == "advanced":
            # Set toggle position without firing the callback yet
            self._header.set_mode(True)
            self._mode_stack.setCurrentIndex(1)

        # Device manager
        self._device_mgr    = DeviceManager()
        self._device_mgr_dlg: DeviceManagerDialog = None
        self._header.add_device_manager_button(self._open_device_manager)

        # Emergency stop — wire header button to hw_service
        self._header.connect_estop(
            on_stop  = self._trigger_estop,
            on_clear = self._clear_estop,
        )
        hw_service.emergency_stop_complete.connect(self._on_estop_complete)

        # Update badge in header
        self._update_badge = self._header.add_update_badge()
        self._update_badge.clicked_with_info.connect(self._show_update_dialog)

        # Help menu
        self._build_menu_bar()

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(f"SanjINSIGHT {version_string()}  —  Ready")

        # Toast notification manager — bottom-right corner of the window
        self._toasts = ToastManager(self)

    def _connect_signals(self):
        signals.new_live_frame.connect(self._on_frame)
        signals.tec_status.connect(self._on_tec)
        signals.fpga_status.connect(self._on_fpga)
        signals.bias_status.connect(self._on_bias)
        signals.stage_status.connect(self._on_stage)
        signals.af_progress.connect(self._on_af_progress)
        signals.af_complete.connect(self._on_af_complete)
        signals.cal_progress.connect(self._on_cal_progress)
        signals.cal_complete.connect(self._on_cal_complete)
        signals.scan_progress.connect(self._on_scan_progress)
        signals.scan_complete.connect(self._on_scan_complete)
        signals.profile_applied.connect(self._on_profile_applied)
        signals.acq_progress.connect(self._on_acq_progress)
        signals.acq_complete.connect(self._on_acq_complete)
        signals.acq_saved.connect(self._on_acq_saved)
        signals.log_message.connect(self._on_log)
        signals.error.connect(self._on_error)
        # TEC alarm signals
        hw_service.tec_alarm.connect(self._on_tec_alarm)
        hw_service.tec_warning.connect(self._on_tec_warning)
        hw_service.tec_alarm_clear.connect(self._on_tec_alarm_clear)

    def _on_frame(self, frame):
        self._camera_tab.update_frame(frame)
        self._acquire_tab.update_live(frame)
        self._roi_tab.update_frame(frame.data)
        self._header.set_connected("camera", True)
        self._status.showMessage(
            f"Camera: {app_state.cam.info.model if app_state.cam else ''}  |  "
            f"Frame {frame.frame_index}  |  "
            f"Exp {frame.exposure_us:.0f}μs")

    def _on_tec(self, index, status):
        self._temp_tab.update_tec(index, status)
        key = f"tec{index}"
        ok  = status.error is None
        tip = (f"TEC {index+1}: {status.actual_temp:.1f}°C → {status.target_temp:.1f}°C"
               if ok else f"TEC {index+1} error: {status.error}")
        self._header.set_connected(key, ok, tip)

    def _on_fpga(self, status):
        self._fpga_tab.update_status(status)
        ok  = status.error is None and status.running
        tip = ("FPGA: running" if ok else
               f"FPGA error: {status.error}" if status.error else "FPGA: stopped")
        self._header.set_connected("fpga", ok, tip)

    def _on_bias(self, status):
        self._bias_tab.update_status(status)
        ok  = status.error is None and status.output_on
        tip = (f"Bias: {status.actual_voltage:.3f}V / {status.actual_current*1000:.2f}mA"
               if ok else
               f"Bias error: {status.error}" if status.error else "Bias: output off")
        self._header.set_connected("bias", ok, tip)

    def _on_stage(self, status):
        self._stage_tab.update_status(status)
        ok  = status.error is None
        pos = status.position
        tip = (f"Stage: {pos.x:.0f} / {pos.y:.0f} / {pos.z:.0f} μm" if ok
               else f"Stage error: {status.error}")
        self._header.set_connected("stage", ok, tip)

    def _on_cal_progress(self, prog):
        self._cal_tab.update_progress(prog)
        self._log_tab.append(prog.message)

    def _on_cal_complete(self, result):
        self._cal_tab.update_complete(result)
        if result.valid:
            self._live_tab.set_calibration(result)
            self._log_tab.append(
                f"Calibration complete — {result.n_points} points, "
                f"T {result.t_min:.1f}–{result.t_max:.1f}°C")
        else:
            self._log_tab.append("Calibration failed or aborted")

    def _on_scan_progress(self, prog):
        self._scan_tab.update_progress(prog)

    def _on_scan_complete(self, result):
        self._scan_tab.update_complete(result)
        if result.valid:
            H, W = result.drr_map.shape[:2]
            self._log_tab.append(
                f"Scan complete — {result.n_cols}×{result.n_rows} tiles  "
                f"{W}×{H} px  FOV "
                f"{result.n_cols*result.step_x_um:.0f}×"
                f"{result.n_rows*result.step_y_um:.0f} μm  "
                f"{result.duration_s:.0f}s")
        else:
            self._log_tab.append("Scan failed or aborted")

    def _open_device_manager(self):
        if self._device_mgr_dlg is None:
            self._device_mgr_dlg = DeviceManagerDialog(
                self._device_mgr, parent=self)
        self._device_mgr_dlg.show()
        self._device_mgr_dlg.raise_()
        self._device_mgr_dlg.activateWindow()

    # ── Menu bar ──────────────────────────────────────────────────

    def _build_menu_bar(self):
        """Build menus and keyboard shortcuts for the main window."""
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence

        mb = self.menuBar()
        mb.setStyleSheet(
            "QMenuBar { background:#111; color:#888; font-size:12pt; }"
            "QMenuBar::item:selected { background:#222; color:#fff; }"
            "QMenu { background:#1a1a1a; color:#ccc; border:1px solid #333; }"
            "QMenu::item:selected { background:#222; }")

        # ── Acquisition menu ─────────────────────────────────────
        acq_menu = mb.addMenu("Acquisition")

        act_run = acq_menu.addAction("▶  Run Sequence")
        act_run.setShortcut(QKeySequence("Ctrl+R"))
        act_run.setToolTip(
            "Capture cold and hot frames then compute ΔR/R (Ctrl+R)")
        act_run.triggered.connect(self._acquire_tab._run)

        act_abort = acq_menu.addAction("■  Abort")
        act_abort.setShortcut(QKeySequence("Escape"))
        act_abort.triggered.connect(self._acquire_tab._abort)

        acq_menu.addSeparator()

        act_live = acq_menu.addAction("Live Mode")
        act_live.setShortcut(QKeySequence("Ctrl+L"))
        act_live.triggered.connect(
            lambda: self._nav.navigate_to(self._live_tab))

        act_scan = acq_menu.addAction("Scan Mode")
        act_scan.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_scan.triggered.connect(
            lambda: self._nav.navigate_to(self._scan_tab))

        # ── View menu ────────────────────────────────────────────
        view_menu = mb.addMenu("View")

        act_acquire_view = view_menu.addAction("Acquire")
        act_acquire_view.setShortcut(QKeySequence("Ctrl+1"))
        act_acquire_view.triggered.connect(
            lambda: self._nav.navigate_to(self._acquire_tab))

        act_camera_view = view_menu.addAction("Camera")
        act_camera_view.setShortcut(QKeySequence("Ctrl+2"))
        act_camera_view.triggered.connect(
            lambda: self._nav.navigate_to(self._camera_tab))

        act_temp_view = view_menu.addAction("Temperature")
        act_temp_view.setShortcut(QKeySequence("Ctrl+3"))
        act_temp_view.triggered.connect(
            lambda: self._nav.navigate_to(self._temp_tab))

        act_stage_view = view_menu.addAction("Stage")
        act_stage_view.setShortcut(QKeySequence("Ctrl+4"))
        act_stage_view.triggered.connect(
            lambda: self._nav.navigate_to(self._stage_tab))

        act_analysis_view = view_menu.addAction("Analysis")
        act_analysis_view.setShortcut(QKeySequence("Ctrl+5"))
        act_analysis_view.triggered.connect(
            lambda: self._nav.navigate_to(self._analysis_tab))

        view_menu.addSeparator()

        act_device_mgr = view_menu.addAction("Device Manager…")
        act_device_mgr.setShortcut(QKeySequence("Ctrl+D"))
        act_device_mgr.triggered.connect(self._open_device_manager)

        # ── Help menu ────────────────────────────────────────────
        help_menu = mb.addMenu("Help")

        act_about = help_menu.addAction(f"About {APP_NAME}…")
        act_about.triggered.connect(self._show_about)

        act_updates = help_menu.addAction("Check for Updates…")
        act_updates.triggered.connect(self._on_manual_update_check)

        help_menu.addSeparator()

        act_settings = help_menu.addAction("Settings")
        act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(
            lambda: self._nav.select_by_label("Settings"))

        # ── Emergency stop shortcut (keyboard) ───────────────────
        estop_sc = QShortcut(QKeySequence("Ctrl+."), self)
        estop_sc.activated.connect(self._trigger_estop)

    # ── About ──────────────────────────────────────────────────────

    def _show_about(self):
        from ui.update_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec_()

    # ── Update checker ─────────────────────────────────────────────

    def _start_update_checker(self):
        """Start the background update check if enabled in preferences."""
        from updater import UpdateChecker, should_check_now, record_check_date
        import config as _cfg
        if not should_check_now(_cfg):
            return
        record_check_date(_cfg)
        checker = UpdateChecker(
            on_update=self._on_update_available,
            on_error=lambda e: log.debug(f"Update check: {e}"),
        )
        checker.check_async(delay_s=8)

    def _on_update_available(self, info):
        """Called on the background thread — must post to UI thread via Qt signal."""
        # Use a single-shot timer to safely update UI from a background thread
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._apply_update_info(info))

    def _apply_update_info(self, info):
        """Apply update notification to all UI elements (runs on UI thread)."""
        self._update_badge.show_update(info)
        self._settings_tab.set_update_status(
            f"v{info.version} available", color="#f5a623")

    def _show_update_dialog(self, info):
        from ui.update_dialog import UpdateDialog
        dlg = UpdateDialog(info, parent=self)
        dlg.exec_()

    def _on_manual_update_check(self):
        """Triggered by Settings tab "Check Now" or Help → Check for Updates."""
        from updater import UpdateChecker
        import threading

        def _check():
            checker = UpdateChecker(
                on_update=self._on_update_available,
                on_no_update=lambda: _post_result("✓ You are up to date", "#00d4aa"),
                on_error=lambda e: _post_result(f"Could not check: {e}", "#ff4444"),
            )
            checker.check_sync()

        def _post_result(msg, color):
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._settings_tab.set_check_result(msg, color))

        threading.Thread(target=_check, daemon=True).start()

    def _apply_recipe(self, recipe) -> None:
        """
        Apply a Recipe to the live hardware and, optionally, start acquisition.

        Called when the user clicks RUN in the Recipes tab.  Applies all recipe
        parameters that have connected hardware; silently skips anything that isn't.
        """
        from acquisition.recipe_tab import Recipe   # local import avoids circular

        log = logging.getLogger(__name__)
        log.info("Applying recipe: %s", recipe.label)

        # ── Camera settings ───────────────────────────────────────
        cam = app_state.cam
        if cam:
            try:
                cam.set_exposure(recipe.camera.exposure_us)
                cam.set_gain(recipe.camera.gain_db)
            except Exception as e:
                log.warning("Recipe: failed to set camera params: %s", e)

        # ── Modality ──────────────────────────────────────────────
        app_state.active_modality = recipe.acquisition.modality

        # ── Material profile ──────────────────────────────────────
        if recipe.profile_name:
            try:
                profile = self._profile_mgr.find_by_name(recipe.profile_name)
                if profile:
                    app_state.active_profile = profile
                    self._profile_tab.select_profile(profile)
            except Exception as e:
                log.warning("Recipe: could not activate profile '%s': %s",
                            recipe.profile_name, e)

        # ── TEC setpoint ──────────────────────────────────────────
        if recipe.tec.enabled:
            for tec in app_state.tecs:
                try:
                    tec.set_setpoint(recipe.tec.setpoint_c)
                except Exception as e:
                    log.warning("Recipe: TEC setpoint failed: %s", e)

        # ── Analysis config ───────────────────────────────────────
        try:
            from acquisition.analysis import AnalysisConfig
            cfg = AnalysisConfig(
                threshold_k          = recipe.analysis.threshold_k,
                fail_hotspot_count   = recipe.analysis.fail_hotspot_count,
                fail_peak_k          = recipe.analysis.fail_peak_k,
                fail_area_fraction   = recipe.analysis.fail_area_fraction,
                warn_hotspot_count   = recipe.analysis.warn_hotspot_count,
                warn_peak_k          = recipe.analysis.warn_peak_k,
                warn_area_fraction   = recipe.analysis.warn_area_fraction,
            )
            self._analysis_tab.set_config(cfg)
        except Exception as e:
            log.warning("Recipe: analysis config not applied: %s", e)

        # ── Switch to Acquire tab and start ───────────────────────
        self._nav.navigate_to(self._acquire_tab)
        # Trigger acquisition using recipe frame count and delay
        try:
            self._acquire_tab.start_acquisition(
                n_frames            = recipe.camera.n_frames,
                inter_phase_delay_s = recipe.acquisition.inter_phase_delay_s,
            )
        except Exception as e:
            log.warning("Recipe: could not auto-start acquisition: %s", e)

    def _on_mode_change(self, advanced: bool):
        """Switch between Standard (wizard) and Advanced (tabs) mode."""
        self._mode_stack.setCurrentIndex(1 if advanced else 0)
        # Persist the choice
        import config as _cfg
        _cfg.set_pref("ui.mode", "advanced" if advanced else "standard")
        if not advanced:
            try:
                self._wizard._step1.refresh()
            except Exception:
                pass

    def _on_profile_applied(self, profile):
        """
        A material profile has been selected and applied.
        Propagate all recommended settings to the relevant subsystems.
        """
        app_state.active_profile = profile

        # 1. Update header indicator
        self._header.set_profile(profile)

        # 2. Push camera settings
        try:
            cam = app_state.cam
            if cam:
                cam.set_exposure(profile.exposure_us)
                cam.set_gain(profile.gain_db)
            self._camera_tab.set_exposure(profile.exposure_us)
            self._camera_tab.set_gain(profile.gain_db)
        except Exception:
            pass

        # 3. Push acquisition frame count to acquire tab
        try:
            self._acquire_tab.set_n_frames(profile.n_frames)
        except Exception:
            pass

        # 4. Push live tab accumulation depth + frames per half
        try:
            self._live_tab._frames_per_half.setValue(
                max(2, profile.n_frames // 4))
            self._live_tab._accum.setValue(profile.accumulation)
        except Exception:
            pass

        # 5. Push scan frames per tile
        try:
            self._scan_tab._n_frames.setValue(profile.n_frames)
        except Exception:
            pass

        # 6. Log
        self._log_tab.append(
            f"Profile applied: {profile.name}  ·  "
            f"C_T = {profile.ct_value:.3e} K⁻¹  ·  "
            f"exposure = {profile.exposure_us:.0f} µs  ·  "
            f"gain = {profile.gain_db:.1f} dB  ·  "
            f"frames = {profile.n_frames}  ·  "
            f"EMA = {profile.accumulation}")

        # 7. Status bar
        self._status.showMessage(
            f"Profile active: {profile.name}   "
            f"C_T = {profile.ct_value:.3e} K⁻¹",
            8000)

    def _on_af_progress(self, result):
        self._af_tab.update_progress(result)
        self._log_tab.append(result.message)

    def _on_af_complete(self, result):
        self._af_tab.update_complete(result)
        self._log_tab.append(result.message)

    def _on_acq_progress(self, p):
        self._acquire_tab.update_progress(p)
        self._log_tab.append(p.message)

    def _on_acq_complete(self, r):
        # Attach current calibration if available — enables ΔT display
        cal = app_state.active_calibration
        if cal and cal.valid:
            try:
                r.delta_t = cal.apply(r.delta_r_over_r)
            except Exception:
                r.delta_t = None
        self._acquire_tab.update_result(r)

        # Push to analysis tab — auto-runs if auto-run checkbox is on
        dt_map  = getattr(r, "delta_t",       None)
        drr_map = getattr(r, "delta_r_over_r", None)
        self._analysis_tab.push_result(
            dt_map    = dt_map,
            drr_map   = drr_map,
            base_image= None,
            source_label = "Acquisition")

        # Update 3D surface plot with the latest ΔR/R (or ΔT if calibrated)
        surface_arr = dt_map if dt_map is not None else drr_map
        if surface_arr is not None:
            label = "ΔT surface  (°C)" if dt_map is not None else "ΔR/R surface"
            self._surface_tab.set_data(surface_arr, title=label)

        # Auto-save to session manager in background — capture full context
        profile = app_state.active_profile
        fpga    = app_state.fpga
        notes   = self._acquire_tab.get_notes()   # capture now, before UI changes

        def _save():
            try:
                label   = time.strftime("acq_%Y%m%d_%H%M%S")
                session = session_mgr.save_result(
                    r, label=label,
                    imaging_mode   = app_state.active_modality,
                    profile_uid    = profile.uid  if profile else "",
                    profile_name   = profile.name if profile else "",
                    ct_value       = profile.ct_value if profile else 0.0,
                    fpga_frequency_hz = (
                        fpga.get_status().frequency_hz
                        if fpga and hasattr(fpga, "get_status") else 0.0),
                    notes          = notes,
                )
                signals.acq_saved.emit(session)
                signals.log_message.emit(
                    f"Session saved: {session.meta.uid}  "
                    f"({session_mgr.root})")
            except Exception as e:
                signals.log_message.emit(f"Session save failed: {e}")
        threading.Thread(target=_save, daemon=True).start()

    def _on_acq_saved(self, session):
        """New session was saved — refresh data tab immediately."""
        self._data_tab.add_session(session)

    def _on_log(self, msg: str):
        self._log_tab.append(msg)
        self._status.showMessage(msg, 4000)
        # Surface success confirmations as green toasts
        if any(k in msg.lower() for k in ("saved", "calibration complete",
                                           "connected", "loaded")):
            self._toasts.show_success(msg, auto_dismiss_ms=4000)

    def _on_error(self, msg: str):
        self._log_tab.append(f"ERROR: {msg}")
        self._status.showMessage(f"Error: {msg}", 8000)
        self._toasts.show_error(msg)

    # ── TEC alarm handlers ────────────────────────────────────────────

    def _on_tec_alarm(self, index: int, message: str,
                      actual: float, limit: float):
        """Hard temperature limit exceeded — TEC already disabled by guard."""
        self._log_tab.append(f"⊗ ALARM: {message}")
        self._status.showMessage(f"TEC {index+1} ALARM — {actual:.2f}°C", 0)

        # Show alarm state in the temperature panel
        self._temp_tab.show_alarm(index, message)

        # Persistent toast — no auto-dismiss for safety alarms
        self._toasts._show(
            title=f"TEC {index+1} Temperature Alarm",
            message=message,
            level="error",
            guidance=[
                "TEC output has been disabled automatically",
                "Check the temperature on the instrument before proceeding",
                "Go to the Temperature tab and click Acknowledge when safe to do so",
                "Do NOT re-enable the TEC until you understand why the limit was reached",
            ],
            auto_dismiss_ms=0)

    def _on_tec_warning(self, index: int, message: str,
                        actual: float, limit: float):
        """Temperature approaching a limit — TEC still running."""
        self._log_tab.append(f"⚠ WARNING: {message}")
        self._temp_tab.show_warning(index, message)
        self._toasts.show_warning(message, auto_dismiss_ms=0)

    def _on_tec_alarm_clear(self, index: int):
        """Alarm or warning cleared — temperature back in safe range."""
        self._log_tab.append(f"✓ TEC {index+1}: temperature alarm cleared")
        self._temp_tab.clear_alarm(index)
        self._status.showMessage(f"TEC {index+1} alarm cleared", 4000)

    # ── Emergency Stop ────────────────────────────────────────────────

    def _trigger_estop(self):
        """User pressed E-Stop — latch the UI then fire the stop sequence."""
        self._header.set_estop_triggered()
        self._status.showMessage("⚠  EMERGENCY STOP — stopping all hardware outputs…", 0)
        self._log_tab.append("⊗ EMERGENCY STOP triggered by user")
        hw_service.emergency_stop()

    def _on_estop_complete(self, summary: str):
        """Called on UI thread when all outputs are confirmed stopped."""
        self._log_tab.append(f"⊗ E-STOP complete — {summary}")
        self._status.showMessage(f"⚠  STOPPED — {summary}", 0)
        self._toasts._show(
            title="Emergency Stop — Hardware Outputs Disabled",
            message=summary,
            level="error",
            guidance=[
                "Bias output, all TECs, and stage motion have been stopped",
                "Acquisition has been aborted",
                "Inspect the instrument before proceeding",
                "Click '⚠ STOPPED — Click to Clear' in the header when safe to re-arm",
            ],
            auto_dismiss_ms=0)

    def _clear_estop(self):
        """User clicked the latched STOPPED button to re-arm."""
        self._header.set_estop_armed()
        self._status.showMessage("Emergency stop cleared — hardware ready", 4000)
        self._log_tab.append("✓ Emergency stop cleared — outputs can be re-enabled")

    def closeEvent(self, event):
        """
        Deterministic shutdown sequence:
          1. Signal all background loops to stop (running = False)
          2. Abort any in-progress acquisition
          3. Stop the live tab processor
          4. Close every driver in a defined order (camera last so frames stop)
          5. Shutdown the thread pool (wait=True up to 3 s, then cancel)
          6. Accept the event — window closes cleanly
        """
        import sys
        global running

        log.info("Shutdown requested")
        global running
        running = False   # legacy flag for any code that still checks it

        # ── Stop live preview processor ───────────────────────────
        try:
            self._live_tab._stop()
        except Exception as e:
            log.warning(f"Live tab stop: {e}")

        # ── Delegate all hardware shutdown to HardwareService ─────
        # This stops all poll loops, joins threads, and closes every
        # driver in the correct order.
        hw_service.shutdown()

        # ── Shutdown the Qt worker thread pool ────────────────────
        try:
            self._thread_pool.shutdown(wait=True, cancel_futures=True)
        except TypeError:
            self._thread_pool.shutdown(wait=False)
        except Exception as e:
            log.warning(f"Thread pool shutdown: {e}")

        log.info("Shutdown complete")
        event.accept()
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import sys as _sys

    # ── Determine launch mode ─────────────────────────────────────────
    # Demo mode activates when:
    #   1.  --demo flag is passed on the command line
    #   2.  Running on macOS — real hardware drivers are Windows-only
    _FORCE_DEMO = ("--demo" in _sys.argv or _sys.platform == "darwin")

    log.info(f"{'='*60}")
    log.info(f"  {APP_VENDOR} {APP_NAME}  {version_string()}")
    log.info(f"  Build date: {__import__('version').BUILD_DATE}")
    log.info(f"  Platform: {_sys.platform}  |  Demo mode: {_FORCE_DEMO}")
    log.info(f"{'='*60}")

    # ── Connect HardwareService signals → app signals ─────────────────
    hw_service.camera_frame.connect(signals.new_live_frame)
    hw_service.tec_status.connect(signals.tec_status)
    hw_service.fpga_status.connect(signals.fpga_status)
    hw_service.bias_status.connect(signals.bias_status)
    hw_service.stage_status.connect(signals.stage_status)
    hw_service.acq_progress.connect(signals.acq_progress)
    hw_service.acq_complete.connect(signals.acq_complete)
    hw_service.error.connect(signals.error)
    hw_service.log_message.connect(signals.log_message)
    hw_service.device_connected.connect(
        lambda key, ok: signals.log_message.emit(
            f"{{'✓' if ok else '✗'}} {key}: {{'connected' if ok else 'connection failed'}}"))

    if not _FORCE_DEMO:
        # Normal startup — attempt real hardware on background threads
        hw_service.start()

    app = QApplication(_sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    # ── First-run wizard (Windows + real hardware only) ───────────────
    if not _FORCE_DEMO:
        _config_path = config._path if hasattr(config, "_path") else os.path.join(
            os.path.dirname(__file__), "config.yaml")
        try:
            from ui.first_run import should_show_first_run, FirstRunWizard
            if should_show_first_run(_config_path):
                dlg = FirstRunWizard(_config_path)
                dlg.exec_()
                config.reload()
        except Exception as _fre:
            log.warning(f"First-run wizard error (non-fatal): {_fre}")

    window = MainWindow()

    # ── Demo mode: activate immediately, skip the startup dialog ──────
    if _FORCE_DEMO:
        app_state.demo_mode = True
        window._header.set_demo_mode(True)
        window._status.showMessage(
            f"SanjINSIGHT {version_string()}  \u2014  DEMO MODE  (simulated hardware)", 0)
        signals.log_message.emit("Running in demo mode \u2014 all hardware is simulated")
        hw_service.start_demo()

    # ── Normal startup: amber dots + startup progress dialog ──────────
    else:
        hw_cfg = config.get("hardware", {})
        _configured_devices = []
        if hw_cfg.get("camera", {}).get("enabled", True):
            _configured_devices.append("camera")
            window._header.set_connecting("camera")
        for _tec_key, _dot_key in [("tec_meerstetter", "tec0"), ("tec_atec", "tec1")]:
            if hw_cfg.get(_tec_key, {}).get("enabled", False):
                _configured_devices.append(_dot_key)
                window._header.set_connecting(_dot_key)
        if hw_cfg.get("fpga", {}).get("enabled", False):
            _configured_devices.append("fpga")
            window._header.set_connecting("fpga")
        if hw_cfg.get("bias", {}).get("enabled", False):
            _configured_devices.append("bias")
            window._header.set_connecting("bias")
        if hw_cfg.get("stage", {}).get("enabled", False):
            _configured_devices.append("stage")
            window._header.set_connecting("stage")

        if _configured_devices:
            _startup_dlg = StartupProgressDialog(
                expected_devices=_configured_devices,
                parent=window)
            hw_service.startup_status.connect(_startup_dlg.on_device_status)

            def _on_demo_requested():
                hw_service.shutdown()
                app_state.demo_mode = True
                app_state.tecs      = []
                window._header.set_demo_mode(True)
                window._status.showMessage(
                    f"SanjINSIGHT {version_string()}  \u2014  DEMO MODE", 0)
                signals.log_message.emit(
                    "Demo mode activated \u2014 all hardware replaced with simulated drivers")
                hw_service.start_demo()

            _startup_dlg.demo_requested.connect(_on_demo_requested)
            _startup_dlg.show()
        else:
            def _offer_demo():
                window._toasts._show(
                    title="No Hardware Configured",
                    message="All devices are disabled in config.yaml.",
                    level="warning",
                    guidance=[
                        "Open config.yaml and set enabled: true for your devices",
                        "Or run with --demo to explore with simulated hardware",
                    ],
                    auto_dismiss_ms=0)
            QTimer.singleShot(800, _offer_demo)

    # Scan existing sessions on startup
    try:
        n = session_mgr.scan()
        if n:
            window._data_tab.refresh()
            signals.log_message.emit(
                f"Sessions: loaded {n} existing sessions from {session_mgr.root}")
    except Exception as e:
        signals.log_message.emit(f"Sessions: could not scan {session_mgr.root}: {e}")

    window.show()
    window._start_update_checker()   # background check, non-blocking
    _sys.exit(app.exec_())
