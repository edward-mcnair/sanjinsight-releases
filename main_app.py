"""
main_app.py

Microsanj Thermoreflectance System — Main Application Window.

Combines camera, TEC, and acquisition into a single unified interface.
Tabs: Acquire | Camera | Temperature | Log

Run:  python3 main_app.py
"""

from __future__ import annotations

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
                           QPen, QBrush, QPalette, QIcon)

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
QPushButton:hover   { background: #383838; color: #fff; border-color: #666; }
QPushButton:pressed { background: #1a1a1a; border-color: #888; padding-top: 6px; padding-bottom: 4px; }
QPushButton:focus   { border-color: #00d4aa88; outline: none; }
QPushButton:disabled { color: #444; border-color: #2a2a2a; background: #1e1e1e; }

QPushButton#primary {
    background: #003d2e;
    color: #00d4aa;
    border-color: #00d4aa;
    font-weight: bold;
}
QPushButton#primary:hover   { background: #005040; border-color: #00e8bb; color: #00e8bb; }
QPushButton#primary:pressed { background: #002a1e; border-color: #00b090; padding-top: 6px; padding-bottom: 4px; }
QPushButton#primary:focus   { border-color: #00d4aa; outline: none; }
QPushButton#primary:disabled { background: #1a1a1a; color: #2a5040; border-color: #1e3030; }

QPushButton#danger {
    background: #3d0000;
    color: #ff6666;
    border-color: #ff4444;
}
QPushButton#danger:hover   { background: #550000; border-color: #ff6666; color: #ff8888; }
QPushButton#danger:pressed { background: #280000; border-color: #cc2222; padding-top: 6px; padding-bottom: 4px; }
QPushButton#danger:focus   { border-color: #ff4444; outline: none; }
QPushButton#danger:disabled { background: #1a1a1a; color: #442222; border-color: #2a1a1a; }

QPushButton#cold_btn {
    background: #001a33;
    color: #66aaff;
    border-color: #3377cc;
    font-weight: bold;
}
QPushButton#cold_btn:hover   { background: #002244; border-color: #4488dd; color: #88bbff; }
QPushButton#cold_btn:pressed { background: #001122; border-color: #2266bb; padding-top: 6px; padding-bottom: 4px; }

QPushButton#hot_btn {
    background: #331a00;
    color: #ffaa44;
    border-color: #cc6600;
    font-weight: bold;
}
QPushButton#hot_btn:hover   { background: #442200; border-color: #dd7700; color: #ffbb66; }
QPushButton#hot_btn:pressed { background: #221100; border-color: #aa5500; padding-top: 6px; padding-bottom: 4px; }

/* Running / in-progress state — applied via setProperty("running", True) */
QPushButton[running="true"] {
    background: #2a1e00;
    color: #f5a623;
    border: 2px solid #f5a62388;
    font-weight: bold;
    padding: 4px 11px;
}
QPushButton[running="true"]#primary {
    background: #002820;
    color: #00d4aa;
    border: 2px solid #00d4aa88;
    padding: 4px 11px;
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

# AppSignals and its singleton live in ui/app_signals.py so that any module
# can import `signals` without depending on this file.
from ui.app_signals import AppSignals, signals

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


# ── UI widgets and tabs (extracted to their own modules) ──────────────
from ui.widgets.image_pane    import ImagePane
from ui.widgets.temp_plot     import TempPlot
from ui.widgets.status_header import StatusHeader, _ModeToggle
from ui.tabs.acquire_tab      import AcquireTab
from ui.tabs.camera_tab       import CameraTab
from ui.tabs.temperature_tab  import TemperatureTab
from ui.tabs.fpga_tab         import FpgaTab
from ui.tabs.bias_tab         import BiasTab
from ui.tabs.stage_tab        import StageTab
from ui.tabs.roi_tab          import RoiTab
from ui.tabs.autofocus_tab    import AutofocusTab, FocusPlot
from ui.tabs.log_tab          import LogTab


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

        act_hw_setup = help_menu.addAction("Hardware Setup…")
        act_hw_setup.setShortcut(QKeySequence("Ctrl+Shift+H"))
        act_hw_setup.setToolTip(
            "Re-run the hardware setup wizard to detect or reconfigure devices")
        act_hw_setup.triggered.connect(self._open_hardware_setup)

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

    def _open_hardware_setup(self):
        """Open the hardware setup wizard at any time (no sentinel check)."""
        from ui.first_run import FirstRunWizard
        import config as _cfg
        config_path = (
            _cfg._path if hasattr(_cfg, "_path")
            else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "config.yaml"))
        dlg = FirstRunWizard(config_path, parent=self)
        if dlg.exec_() == dlg.Accepted:
            # Reload config so values are fresh if the app re-connects hardware
            try:
                _cfg.reload()
            except Exception:
                log.warning("Config reload after hardware setup failed", exc_info=True)
            QMessageBox.information(
                self, "Hardware Setup",
                "Configuration saved.\n\n"
                "Restart the application (or reconnect hardware from the "
                "Device Manager) to apply the new driver settings.")

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
            except Exception as _e:
                log.debug("Wizard step1 refresh: %s", _e)

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
        except Exception as _e:
            log.warning("Profile apply — camera settings: %s", _e)

        # 3. Push acquisition frame count to acquire tab
        try:
            self._acquire_tab.set_n_frames(profile.n_frames)
        except Exception as _e:
            log.debug("Profile apply — acquire n_frames: %s", _e)

        # 4. Push live tab accumulation depth + frames per half
        try:
            self._live_tab._frames_per_half.setValue(
                max(2, profile.n_frames // 4))
            self._live_tab._accum.setValue(profile.accumulation)
        except Exception as _e:
            log.debug("Profile apply — live tab settings: %s", _e)

        # 5. Push scan frames per tile
        try:
            self._scan_tab._n_frames.setValue(profile.n_frames)
        except Exception as _e:
            log.debug("Profile apply — scan n_frames: %s", _e)

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
            except Exception as _e:
                log.debug("Calibration apply to acquisition result failed: %s", _e)
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

    # ── Configure rotating log file before anything else ──────────────
    # This must run before config is reloaded or QApplication is created
    # so that every log message (including hardware init) is captured.
    import logging_config as _lc
    import config as _cfg_boot
    _lc.setup(level=_cfg_boot.get("logging.level", "INFO"))

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

    _icon_path = os.path.join(os.path.dirname(__file__), "assets", "app-icon.png")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # Register QTextCursor with Qt's meta-type system so it can be safely
    # queued across threads (suppresses the "Cannot queue arguments of type
    # 'QTextCursor'" warning that appears when QTextEdit is used near threads).
    try:
        from PyQt5.QtGui  import QTextCursor
        from PyQt5.QtCore import QMetaType
        QMetaType.type("QTextCursor")   # ensures the type is registered
    except Exception as _e:
        log.debug("QMetaType QTextCursor registration skipped: %s", _e)

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
    if os.path.exists(_icon_path):
        window.setWindowIcon(QIcon(_icon_path))

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
