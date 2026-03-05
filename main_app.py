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
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
    QDockWidget)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt5.QtGui   import (QImage, QPixmap, QFont, QColor, QPainter,
                           QPen, QBrush, QPalette, QIcon)

import config
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
from acquisition.movie_tab       import MovieTab            # ← movie-mode burst
from acquisition.transient_tab   import TransientTab        # ← time-resolved transient
from ui.tabs.prober_tab          import ProberTab           # ← probe-station chuck
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
    font-size:13pt;
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
    font-size:13pt;
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
    font-size:13pt;
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
    font-size:26pt;
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

# ── Windows stylesheet font-size fix ─────────────────────────────────────────
# Qt converts stylesheet `pt` values to pixels using the screen's logical DPI.
# macOS uses 72 DPI as its pt baseline, so a "13pt" font renders as 13 logical
# pixels.  Windows uses 96 DPI, making the same rule render as ~17 px — 33%
# larger.  On Parallels at 200% scaling the compound effect can look ~2× bigger.
#
# The fix: scale every explicit pt value in the STYLE string down by 72/96 = ¾.
# This leaves the app stylesheet matching macOS visual size on Windows.
# NOTE: do NOT use QT_FONT_DPI — that env var overrides system/default fonts too
# (e.g. dialogs, Device Manager) which are already correctly DPI-aware.
if sys.platform == 'win32':
    STYLE = (STYLE
             .replace('font-size:13pt', 'font-size:10pt')
             .replace('font-size:12pt', 'font-size:9pt')
             .replace('font-size:26pt', 'font-size:20pt'))


def _style_pt(macos_pt: int) -> str:
    """Return a CSS font-size declaration scaled for the current platform.

    Use this for any stylesheet string that is built dynamically (not part
    of the top-level STYLE constant which is already scaled at module load).

    Example:
        f"QMenuBar {{ font-size: {_style_pt(12)}; }}"
    """
    if sys.platform == 'win32':
        return f"{int(round(macos_pt * 0.75))}pt"
    return f"{macos_pt}pt"


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
from ai.metrics_service          import MetricsService
from ai.diagnostic_engine        import DiagnosticEngine
from ui.widgets.readiness_widget import ReadinessWidget
from ai.ai_service               import AIService
from ai.model_runner             import llama_available
from ai.model_downloader         import ModelDownloader, RECOMMENDED_MODEL, DEFAULT_MODELS_DIR
from ui.widgets.ai_panel_widget  import AIPanelWidget


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
        self._camera_tab   = CameraTab(hw_service=hw_service)
        self._temp_tab     = TemperatureTab(max(n_tecs, 1), hw_service=hw_service)
        self._fpga_tab     = FpgaTab(hw_service=hw_service)
        self._bias_tab     = BiasTab(hw_service=hw_service)
        self._stage_tab    = StageTab(hw_service=hw_service)
        self._roi_tab      = RoiTab()
        self._af_tab       = AutofocusTab()
        self._cal_tab      = CalibrationTab()
        self._scan_tab     = ScanTab()
        self._profile_tab  = ProfileTab(self._profile_mgr)
        self._data_tab     = DataTab(session_mgr)
        self._log_tab      = LogTab()
        self._settings_tab = SettingsTab()

        # ── Metrics service + readiness banner ───────────────────
        self._metrics = MetricsService(hw_service, parent=self)
        self._readiness_widget = ReadinessWidget()
        self._metrics.metrics_updated.connect(
            self._readiness_widget.update_metrics)
        self._acquire_tab.insert_readiness_widget(self._readiness_widget)

        # ── AI service + model downloader + dockable panel ────────
        self._last_grade: str = ""         # tracks grade for change notifications
        self._acq_start_grade: str = "A"  # grade snapshot at acquisition start
        self._acq_start_issues: list = [] # issue snapshot at acquisition start
        self._diagnostic_engine = DiagnosticEngine(self._metrics)
        self._ai_service = AIService(parent=self)
        self._ai_service.set_metrics(self._metrics)
        self._ai_service.set_diagnostics(self._diagnostic_engine)
        self._model_downloader = ModelDownloader(parent=self)

        self._ai_panel = AIPanelWidget(llama_installed=llama_available())
        self._ai_dock = QDockWidget("AI Assistant", self)
        self._ai_dock.setWidget(self._ai_panel)
        self._ai_dock.setMinimumWidth(300)
        self._ai_dock.setFeatures(
            QDockWidget.DockWidgetClosable |
            QDockWidget.DockWidgetMovable  |
            QDockWidget.DockWidgetFloatable)
        self._ai_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self._ai_dock)
        self._ai_dock.hide()
        self._ai_dock.visibilityChanged.connect(self._on_ai_dock_visibility)

        # ── New enhancement tabs ──────────────────────────────────
        self._compare_tab  = ComparisonTab(session_manager=session_mgr)
        self._surface_tab  = SurfacePlotTab()
        self._recipe_tab   = RecipeTab(app_state=app_state)
        self._console_tab  = ScriptingConsoleTab(app_state=app_state)
        self._movie_tab    = MovieTab()                          # ← burst capture
        self._transient_tab = TransientTab()                    # ← time-resolved
        self._prober_tab   = ProberTab()                        # ← probe chuck

        # Wire recipe RUN signal → apply recipe to hardware
        self._recipe_tab.recipe_run.connect(self._apply_recipe)

        # Wire Settings tab → manual update check
        self._settings_tab.check_for_updates_requested.connect(
            self._on_manual_update_check)

        # Wire Settings tab → AI service
        self._settings_tab.ai_enable_requested.connect(self._on_ai_enable)
        self._settings_tab.ai_disable_requested.connect(self._ai_service.disable)

        # Wire Settings tab ↔ ModelDownloader
        self._settings_tab.download_model_requested.connect(
            self._on_download_model_requested)
        self._settings_tab.download_cancel_requested.connect(
            self._model_downloader.cancel)
        self._model_downloader.progress.connect(
            self._settings_tab.set_download_progress)
        self._model_downloader.complete.connect(self._on_download_complete)
        self._model_downloader.failed.connect(
            self._settings_tab.set_download_failed)

        # ── Register panels with the Bootstrap-style sidebar ─────
        from ui.sidebar_nav import NavItem as NI
        from ui.icons import NAV_ICONS as _I, GROUP_ICONS as _G

        self._nav.add_section("MEASURE", [
            NI("Live",        _I["Live"],        self._live_tab,     badge="★"),
            NI("Acquire",     _I["Acquire"],     self._acquire_tab,  badge="★"),
            NI("Scan",        _I["Scan"],        self._scan_tab),
            NI("Movie",       _I["Movie"],       self._movie_tab),
            NI("Transient",   _I["Transient"],   self._transient_tab),
        ])
        self._nav.add_section("ANALYSIS", [
            NI("Calibration", _I["Calibration"], self._cal_tab),
            NI("Analysis",    _I["Analysis"],    self._analysis_tab, badge="★"),
            NI("Compare",     _I["Compare"],     self._compare_tab),
            NI("3D Surface",  _I["3D Surface"],  self._surface_tab),
        ])
        self._nav.add_collapsible("Hardware", _G["Hardware"], [
            NI("Camera",      _I["Camera"],      self._camera_tab),
            NI("Temperature", _I["Temperature"], self._temp_tab),
            NI("FPGA",        _I["FPGA"],        self._fpga_tab),
            NI("Bias Source", _I["Bias Source"], self._bias_tab),
            NI("Stage",       _I["Stage"],       self._stage_tab),
            NI("Prober",      _I["Prober"],      self._prober_tab),
            NI("ROI",         _I["ROI"],         self._roi_tab),
            NI("Autofocus",   _I["Autofocus"],   self._af_tab),
        ], collapsed=False)
        self._nav.add_section("SETUP", [
            NI("Profiles",    _I["Profiles"],    self._profile_tab),
            NI("Recipes",     _I["Recipes"],     self._recipe_tab),
        ])
        self._nav.add_section("TOOLS", [
            NI("Data",        _I["Data"],        self._data_tab),
            NI("Console",     _I["Console"],     self._console_tab),
            NI("Log",         _I["Log"],         self._log_tab),
            NI("Settings",    _I["Settings"],    self._settings_tab),
        ])
        self._nav.finish()
        self._nav.select_first()

        # Build wizard (Standard mode)
        self._wizard = StandardWizard(self._profile_mgr, hw_service=hw_service)

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

        # Device manager — dialog created eagerly (hidden) so hw_status_changed
        # is wired from app start.  The 200 ms initial scan fires automatically;
        # the header button turns green once hardware is detected.
        self._device_mgr     = DeviceManager()
        self._device_mgr_dlg = DeviceManagerDialog(self._device_mgr, parent=self)
        self._header.add_device_manager_button(self._open_device_manager)
        self._device_mgr_dlg.hw_status_changed.connect(
            self._header.set_hw_btn_status)

        # Emergency stop — wire header button to hw_service
        self._header.connect_estop(
            on_stop  = self._trigger_estop,
            on_clear = self._clear_estop,
        )
        hw_service.emergency_stop_complete.connect(self._on_estop_complete)

        # Update badge in header
        self._update_badge = self._header.add_update_badge()
        self._update_badge.clicked_with_info.connect(self._show_update_dialog)

        # AI toggle button in header
        self._ai_btn = self._header.add_ai_button(self._toggle_ai_panel)
        # Restore AI enabled state from preferences
        import config as _cfg_ai
        if _cfg_ai.get_pref("ai.enabled", False):
            model_path = _cfg_ai.get_pref("ai.model_path", "")
            if model_path:
                n_gpu = _cfg_ai.get_pref("ai.n_gpu_layers", 0)
                self._ai_service.enable(model_path, n_gpu)

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

        # Device hotplug → refresh HW indicators in acquisition tabs
        hw_service.device_connected.connect(self._on_device_hotplug)

        # ── AI service signals ────────────────────────────────────
        self._ai_service.status_changed.connect(self._on_ai_status)
        self._ai_service.response_token.connect(self._ai_panel.on_token)
        self._ai_service.response_complete.connect(self._ai_panel.on_response_complete)
        self._ai_service.ai_error.connect(self._ai_panel.on_error)

        # AI panel → service
        # start_user_turn must be connected FIRST so the user bubble appears
        # in the chat log before the AI service starts streaming tokens.
        self._ai_panel.explain_requested.connect(
            lambda: self._ai_panel.start_user_turn("Explain this tab"))
        self._ai_panel.explain_requested.connect(self._ai_service.explain_tab)
        self._ai_panel.diagnose_requested.connect(
            lambda: self._ai_panel.start_user_turn("Diagnose instrument state"))
        self._ai_panel.diagnose_requested.connect(self._ai_service.diagnose)
        self._ai_panel.ask_requested.connect(self._ai_service.ask)
        self._ai_panel.close_requested.connect(self._toggle_ai_panel)
        self._ai_panel.clear_requested.connect(self._ai_service.clear_history)
        self._ai_panel.support_requested.connect(self._open_support_dialog)

        # Settings tab → AI service (enable / disable)
        self._settings_tab.ai_enable_requested.connect(self._on_ai_enable)
        self._settings_tab.ai_disable_requested.connect(
            self._ai_service.disable)

        # Settings tab ↔ model downloader (download, cancel, progress)
        self._settings_tab.download_model_requested.connect(
            self._on_download_model_requested)
        self._settings_tab.download_cancel_requested.connect(
            self._model_downloader.cancel)
        self._model_downloader.progress.connect(
            self._settings_tab.set_download_progress)
        self._model_downloader.complete.connect(self._on_download_complete)
        self._model_downloader.failed.connect(
            self._settings_tab.set_download_failed)

        # Sidebar tab changes → AI context
        self._nav.panel_changed.connect(
            lambda p: self._ai_service.set_active_tab(type(p).__name__))

        # ReadinessWidget "Fix it →" buttons → sidebar navigation
        self._readiness_widget.navigate_requested.connect(
            self._nav.select_by_label)

        # Acquisition readiness gate
        self._acquire_tab.acquire_requested.connect(self._on_acquire_requested)

        # Evidence panel — refresh every 3 s while the app is running
        self._evidence_timer = QTimer(self)
        self._evidence_timer.setInterval(3000)
        self._evidence_timer.timeout.connect(self._refresh_evidence_panel)
        self._evidence_timer.start()

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
            summary = (
                f"Scan complete — {result.n_cols}×{result.n_rows} tiles  "
                f"{W}×{H} px  FOV "
                f"{result.n_cols*result.step_x_um:.0f}×"
                f"{result.n_rows*result.step_y_um:.0f} μm  "
                f"{result.duration_s:.0f}s")
            self._log_tab.append(summary)
            # ── Completion notification ──────────────────────────
            self._toasts.show_success(
                f"Scan complete  ({result.n_cols}×{result.n_rows} tiles, "
                f"{result.duration_s:.0f}s)",
                auto_dismiss_ms=6000)
            try:                          # Windows system beep (silent on other OS)
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        else:
            self._log_tab.append("Scan failed or aborted")
            self._toasts.show_warning("Scan failed or was aborted",
                                      auto_dismiss_ms=5000)
            return
        # ── Autosave checkpoint (scan) ────────────────────────────────
        try:
            from acquisition.autosave import scan_autosave
            _sarr = {"drr_map": result.drr_map}
            if hasattr(result, "dt_map") and result.dt_map is not None:
                _sarr["dt_map"] = result.dt_map
            scan_autosave.save(
                _sarr,
                {"n_cols": result.n_cols, "n_rows": result.n_rows,
                 "step_x_um": result.step_x_um, "step_y_um": result.step_y_um,
                 "label": time.strftime("scan_%Y%m%d_%H%M%S")})
        except Exception as _se:
            log.debug("Autosave (scan) failed: %s", _se)

    def _on_device_hotplug(self, key: str, ok: bool):
        """
        Called on the GUI thread whenever hw_service detects a device
        connect or disconnect event.

        Refreshes hardware-readiness labels in the acquisition tabs that
        display a static HW status panel (populated at showEvent but not
        otherwise updated while the tab is already visible).
        """
        try:
            self._movie_tab._refresh_hw()
            self._transient_tab._refresh_hw()
            self._prober_tab._refresh_hw()
        except Exception:
            log.debug("hotplug refresh failed", exc_info=True)

    def _open_device_manager(self):
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
            f"QMenuBar {{ background:#111; color:#888; font-size:{_style_pt(12)}; }}"
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

        acq_menu.addSeparator()

        act_start_live = acq_menu.addAction("▶  Start Live Stream")
        act_start_live.setShortcut(QKeySequence("F5"))
        act_start_live.setToolTip("Start the live ΔR/R preview (F5)")
        act_start_live.triggered.connect(
            lambda: self._live_tab._start_btn.click()
            if self._live_tab._start_btn.isEnabled() else None)

        act_stop_live = acq_menu.addAction("■  Stop Live Stream")
        act_stop_live.setShortcut(QKeySequence("F6"))
        act_stop_live.setToolTip("Stop the live preview (F6)")
        act_stop_live.triggered.connect(
            lambda: self._live_tab._stop_btn.click()
            if self._live_tab._stop_btn.isEnabled() else None)

        act_freeze = acq_menu.addAction("❄  Freeze / Resume")
        act_freeze.setShortcut(QKeySequence("F7"))
        act_freeze.setToolTip("Freeze or resume the live display (F7)")
        act_freeze.triggered.connect(self._live_tab._toggle_freeze)

        acq_menu.addSeparator()

        act_run_analysis = acq_menu.addAction("◈  Run Analysis")
        act_run_analysis.setShortcut(QKeySequence("F8"))
        act_run_analysis.setToolTip("Run hotspot analysis on the current result (F8)")
        act_run_analysis.triggered.connect(
            lambda: self._analysis_tab._run_btn.click()
            if self._analysis_tab._run_btn.isEnabled() else None)

        act_start_scan = acq_menu.addAction("⊞  Start / Stop Scan")
        act_start_scan.setShortcut(QKeySequence("F9"))
        act_start_scan.setToolTip("Start or abort the large-area scan (F9)")
        act_start_scan.triggered.connect(self._toggle_scan)

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

        help_menu.addSeparator()

        act_support = help_menu.addAction("Get Support…")
        act_support.setToolTip(
            "Open a pre-filled support email with system info and recent log")
        act_support.triggered.connect(self._open_support_dialog)

        # ── Emergency stop shortcut (keyboard) ───────────────────
        estop_sc = QShortcut(QKeySequence("Ctrl+."), self)
        estop_sc.activated.connect(self._trigger_estop)

    # ── Keyboard shortcut helpers ──────────────────────────────────

    def _toggle_scan(self):
        """F9 — start scan if idle, abort if running."""
        try:
            if self._scan_tab._btn_runner.is_running:
                self._scan_tab._abort_btn.click()
            else:
                self._scan_tab._run_btn.click()
        except Exception:
            pass

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

    def _open_support_dialog(self):
        """Open the Get Support dialog with current instrument state included."""
        from ui.dialogs.support_dialog import SupportDialog
        context_json = ""
        try:
            context_json = self._ai_service._ctx.build()
        except Exception:
            pass
        dlg = SupportDialog(context_json=context_json, parent=self)
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

        # Reflect active recipe name in the Acquire tab
        try:
            self._acquire_tab.set_active_recipe_name(recipe.label)
        except Exception:
            pass

        # ── Camera settings ───────────────────────────────────────
        try:
            hw_service.cam_set_exposure(recipe.camera.exposure_us)
            hw_service.cam_set_gain(recipe.camera.gain_db)
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
            for idx in range(len(app_state.tecs)):
                try:
                    hw_service.tec_set_target(idx, recipe.tec.setpoint_c)
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
            hw_service.cam_set_exposure(profile.exposure_us)
            hw_service.cam_set_gain(profile.gain_db)
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

        # ── Autosave checkpoint (acquire) ─────────────────────────
        try:
            from acquisition.autosave import acquire_autosave
            _arrays = {}
            if drr_map is not None:
                _arrays["drr"] = drr_map
            if dt_map is not None:
                _arrays["dt"] = dt_map
            acquire_autosave.save(
                _arrays,
                {"label": time.strftime("acq_%Y%m%d_%H%M%S"),
                 "snr_db": float(getattr(r, "snr_db", 0))})
        except Exception as _ae:
            log.debug("Autosave (acquire) failed: %s", _ae)

        # AI session quality report — silently skips if model not loaded
        if self._ai_service.status == "ready":
            snr = None
            try:
                snr = r.snr_db
            except Exception:
                pass
            result_data = {
                "grade":         self._acq_start_grade,
                "issues":        [
                    {"name": i.display_name, "sev": i.severity, "obs": i.observed}
                    for i in self._acq_start_issues
                ],
                "n_frames":      r.n_frames,
                "cold_captured": r.cold_captured,
                "hot_captured":  r.hot_captured,
                "duration_s":    r.duration_s,
                "exposure_us":   r.exposure_us,
                "gain_db":       r.gain_db,
                "snr_db":        snr,
                "dark_pixel_pct": round(r.dark_pixel_fraction * 100, 1),
                "complete":      r.is_complete,
            }
            self._ai_service.session_report(result_data)
            if not self._ai_dock.isVisible():
                self._status.showMessage(
                    "AI quality report ready — click ◉ to view", 6000)

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

    # ── AI assistant handlers ──────────────────────────────────────────

    @staticmethod
    def _compute_grade(results: list) -> str:
        """Derive A/B/C/D grade string from a list of RuleResult objects."""
        fails = sum(1 for r in results if r.severity == "fail")
        warns = sum(1 for r in results if r.severity == "warn")
        if fails >= 2:  return "D"
        if fails >= 1:  return "C"
        if warns >= 3:  return "C"
        if warns >= 1:  return "B"
        return "A"

    def _refresh_evidence_panel(self) -> None:
        """Push latest diagnostic results to the AI panel evidence section."""
        try:
            results = self._diagnostic_engine.evaluate()
            self._ai_panel.refresh_evidence(results)

            grade = self._compute_grade(results)
            if grade != self._last_grade:
                prev, self._last_grade = self._last_grade, grade
                if grade in ("C", "D") and prev not in ("C", "D"):
                    self._status.showMessage(
                        f"⚠  Instrument grade dropped to {grade} — "
                        f"review AI panel before acquiring", 8000)
                elif grade == "A" and prev in ("C", "D"):
                    self._status.showMessage(
                        "✓  Instrument grade restored to A — ready for acquisition", 5000)
        except Exception:
            pass

    def _on_acquire_requested(self, n_frames: int, delay: float) -> None:
        """
        Readiness gate: intercept acquisition start, warn or block on C/D grades.

        Grade A/B → proceed immediately.
        Grade C   → warning dialog, user can override.
        Grade D   → critical dialog, user can still override but is strongly warned.

        Always captures the pre-acquisition grade and issue snapshot so the
        post-acquisition session report can reference conditions at start time.
        """
        try:
            results = self._diagnostic_engine.evaluate()
            grade   = self._compute_grade(results)
        except Exception:
            results = []
            grade   = "A"   # if engine fails, don't block acquisition

        # Snapshot for session report regardless of whether we proceed
        self._acq_start_grade  = grade
        self._acq_start_issues = [r for r in results if r.severity in ("fail", "warn")]

        if grade in ("A", "B"):
            self._acquire_tab.start_acquisition(n_frames, delay)
            return

        issue_lines = "\n".join(
            f"  {'⊗' if r.severity == 'fail' else '⚠'}  {r.display_name}: {r.observed}"
            for r in self._acq_start_issues[:6]
        )

        if grade == "C":
            msg = QMessageBox(self)
            msg.setWindowTitle("Readiness Warning — Grade C")
            msg.setIcon(QMessageBox.Warning)
            msg.setText(
                f"The instrument has active warnings (Grade C).\n\n"
                f"{issue_lines}\n\n"
                f"Proceeding may affect data quality."
            )
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            msg.button(QMessageBox.Ok).setText("Proceed anyway")
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec_() == QMessageBox.Ok:
                self._acquire_tab.start_acquisition(n_frames, delay)

        else:   # grade == "D"
            msg = QMessageBox(self)
            msg.setWindowTitle("Readiness Failure — Grade D")
            msg.setIcon(QMessageBox.Critical)
            msg.setText(
                f"The instrument has critical failures (Grade D).\n\n"
                f"{issue_lines}\n\n"
                f"Acquisition results will likely be unreliable.\n"
                f"Resolve failures before proceeding if possible."
            )
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            msg.button(QMessageBox.Ok).setText("Proceed despite failures")
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec_() == QMessageBox.Ok:
                self._acquire_tab.start_acquisition(n_frames, delay)

    def _toggle_ai_panel(self):
        """Show or hide the AI assistant dock widget."""
        if self._ai_dock.isVisible():
            self._ai_dock.hide()
        else:
            self._ai_dock.show()
            self._refresh_evidence_panel()  # immediate refresh on open

    def _on_ai_dock_visibility(self, visible: bool):
        """Keep the header AI button checked state in sync with dock visibility."""
        if hasattr(self, "_ai_btn"):
            self._ai_btn.setChecked(visible)

    def _on_ai_status(self, status: str):
        """Propagate AIService status to header and settings."""
        self._ai_panel.on_status_changed(status)
        self._header.set_ai_status(status)
        self._settings_tab.set_ai_status(status)
        if status == "ready":
            self._status.showMessage("AI Assistant ready", 3000)
        elif status == "error":
            self._status.showMessage("AI Assistant error — see AI panel", 5000)

    def _on_ai_enable(self, model_path: str, n_gpu_layers: int):
        """Called when Settings tab emits ai_enable_requested."""
        self._ai_panel.clear_display()
        self._ai_service.enable(model_path, n_gpu_layers)
        # Show the panel automatically when loading starts
        self._ai_dock.show()

    def _on_download_model_requested(self, url: str, dest_path: str) -> None:
        """Start a background model download requested by the Settings tab."""
        self._model_downloader.download(url, dest_path)

    def _on_download_complete(self, path: str) -> None:
        """Model download finished — update prefs and auto-load if AI is enabled."""
        import config as cfg_mod
        self._settings_tab.set_download_complete(path)
        cfg_mod.set_pref("ai.model_path", path)
        if cfg_mod.get_pref("ai.enabled", False):
            n_gpu = cfg_mod.get_pref("ai.n_gpu_layers", 0)
            self._on_ai_enable(path, n_gpu)

    def showEvent(self, event):
        """Restore window geometry and splitter positions once on first show."""
        super().showEvent(event)
        if not getattr(self, '_layout_restored', False):
            self._layout_restored = True
            self._restore_layout()

    def _restore_layout(self):
        """Restore persisted window geometry and tab splitter sizes."""
        import config as _cfg
        from PyQt5.QtCore import QByteArray
        geo = _cfg.get_pref("ui.geometry", "")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
            except Exception:
                pass
        for attr, key, n in [
            ("_live_tab",     "ui.splitter.live",     3),
            ("_scan_tab",     "ui.splitter.scan",     2),
            ("_analysis_tab", "ui.splitter.analysis", 3),
        ]:
            sizes = _cfg.get_pref(key, [])
            if sizes and len(sizes) == n:
                try:
                    getattr(self, attr)._body_splitter.setSizes(sizes)
                except Exception:
                    pass

    def _save_layout(self):
        """Persist window geometry and tab splitter sizes."""
        import config as _cfg
        try:
            _cfg.set_pref("ui.geometry",
                          self.saveGeometry().toHex().data().decode())
        except Exception:
            pass
        for attr, key in [
            ("_live_tab",     "ui.splitter.live"),
            ("_scan_tab",     "ui.splitter.scan"),
            ("_analysis_tab", "ui.splitter.analysis"),
        ]:
            try:
                _cfg.set_pref(key, list(getattr(self, attr)._body_splitter.sizes()))
            except Exception:
                pass

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
        self._save_layout()
        # Clear autosave checkpoints on clean exit (not a crash)
        try:
            from acquisition.autosave import acquire_autosave, scan_autosave
            acquire_autosave.clear()
            scan_autosave.clear()
        except Exception:
            pass
        global running
        log.info("Shutdown requested")
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
    _lc.setup(level=_cfg_boot.get("logging").get("level", "INFO"))

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
            f"{'✓' if ok else '✗'} {key}: {'connected' if ok else 'connection failed'}"))

    # ── High-DPI support ──────────────────────────────────────────────
    # MUST be set before QApplication() is created.
    # Without these, Windows DPI scaling (e.g. 150 % / 200 % on high-DPI
    # displays such as Parallels on a Retina Mac) is applied on top of Qt's
    # own rendering, making fonts and UI elements appear 1.5–2× too large.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,    True)

    app = QApplication(_sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    # ── Windows: set stable AppUserModelID before any window is created ──
    # Without this, Windows assigns a generic AUMID based on the exe path,
    # which means the taskbar icon can be blank (especially when pinned) and
    # jump-lists / grouped taskbar buttons may not behave correctly.
    if _sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Microsanj.SanjINSIGHT")
        except Exception as _auid_err:
            log.debug("AppUserModelID not set: %s", _auid_err)

    # ── Application icon ──────────────────────────────────────────────
    # _resource_base resolves correctly both when running from source and
    # inside a PyInstaller-bundled executable (where __file__ points into the
    # frozen archive but sys._MEIPASS is the temp extraction directory).
    _resource_base = getattr(_sys, "_MEIPASS", os.path.dirname(
        os.path.abspath(__file__)))
    _assets = os.path.join(_resource_base, "assets")

    # Pick the best icon format for each platform.
    # PyQt5 on Windows cannot render .icns (macOS-only format) — it silently
    # returns an empty icon, which Qt then fills with the Fusion style's
    # highlight colour (a solid green square).  Prefer .ico on Windows and
    # .icns on macOS; fall back to .png on any platform if the preferred file
    # is missing.
    if _sys.platform == "win32":
        _candidates = ["app-icon.ico", "app-icon.png"]
    elif _sys.platform == "darwin":
        # .png is preferred: Qt reliably loads it via the native macOS image
        # loader and correctly propagates the icon to the Dock.  .icns is kept
        # as a fallback because PyQt5 cannot always parse the multi-resolution
        # ICNS container, which silently produces a null icon (green square).
        _candidates = ["app-icon.png", "app-icon.icns"]
    else:
        _candidates = ["app-icon.png"]
    _icon_path = None
    for _c in _candidates:
        _p = os.path.join(_assets, _c)
        if os.path.exists(_p):
            _icon_path = _p
            break
    if _icon_path:
        _app_icon = QIcon(_icon_path)
        if not _app_icon.isNull():
            app.setWindowIcon(_app_icon)
        else:
            log.warning("Icon file found but QIcon returned null: %s", _icon_path)
            _icon_path = None
    else:
        log.debug("No application icon found in: %s", _assets)

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
    if _icon_path:
        window.setWindowIcon(_app_icon)   # title-bar / taskbar icon

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

            # Track whether any device connects as simulated so we can
            # show an advisory in the status bar when no real hardware
            # is present (but the user didn't explicitly request demo mode).
            _simulated_keys: list = []
            def _on_startup_status_sim(key: str, ok: bool, detail: str):
                if ok and 'simulated' in detail.lower():
                    _simulated_keys.append(key)
            hw_service.startup_status.connect(_on_startup_status_sim)

            def _on_startup_finished():
                if _simulated_keys and not app_state.demo_mode:
                    keys_str = ', '.join(_simulated_keys)
                    window._status.showMessage(
                        f"SanjINSIGHT {version_string()}  \u2014  "
                        f"Simulated hardware  ({keys_str} — no real hardware connected)",
                        0)
            _startup_dlg.finished.connect(_on_startup_finished)

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

            # Start hardware AFTER the dialog is fully connected.
            # If start() were called earlier (before the signal connection above),
            # fast-connecting devices — especially the simulated camera — emit
            # startup_status before the slot exists and the dialog never receives
            # the notification, leaving it open indefinitely.
            hw_service.start()

            # Safety net: close after 30 s even if a device never reports back
            # (e.g. auto-reconnect loop keeps a device perpetually "connecting").
            QTimer.singleShot(
                30_000,
                lambda: _startup_dlg.accept() if _startup_dlg.isVisible() else None)

        else:
            # No devices configured — start camera thread anyway (simulated
            # fallback) and show the "no hardware" advisory toast.
            hw_service.start()
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

    # ── Autosave recovery check ──────────────────────────────────────
    try:
        from acquisition.autosave import acquire_autosave, scan_autosave
        from PyQt5.QtWidgets import QMessageBox as _QMB
        for _as, _label, _tab in [
            (acquire_autosave, "acquisition", window._analysis_tab),
            (scan_autosave,    "scan",        window._scan_tab),
        ]:
            if _as.has_checkpoint():
                cp = _as.load()
                if cp:
                    saved_at = cp.get("saved_at", "?")
                    r = _QMB.question(
                        window,
                        "Restore Unsaved Result",
                        f"An unsaved {_label} result from {saved_at} was found.\n\n"
                        "Restore it now?",
                        _QMB.Yes | _QMB.No, _QMB.Yes)
                    if r == _QMB.Yes:
                        try:
                            _arrays = cp.get("arrays", {})
                            if _label == "acquisition":
                                drr = _arrays.get("drr")
                                dtt = _arrays.get("dt")
                                if drr is not None:
                                    window._analysis_tab.push_result(
                                        dt_map=dtt, drr_map=drr,
                                        base_image=None,
                                        source_label="Restored")
                                    window._nav.navigate_to(window._analysis_tab)
                            else:
                                import numpy as _np
                                drr = _arrays.get("drr_map")
                                dtt = _arrays.get("dt_map")
                                if drr is not None:
                                    meta = cp.get("metadata", {})
                                    from acquisition.scan import ScanResult
                                    sr = ScanResult(
                                        drr_map=drr, dt_map=dtt,
                                        n_cols=int(meta.get("n_cols", 1)),
                                        n_rows=int(meta.get("n_rows", 1)),
                                        step_x_um=float(meta.get("step_x_um", 100)),
                                        step_y_um=float(meta.get("step_y_um", 100)),
                                        duration_s=0.0, valid=True)
                                    window._scan_tab.update_complete(sr)
                                    window._nav.navigate_to(window._scan_tab)
                        except Exception as _re:
                            pass
                    _as.clear()
    except Exception as _ce:
        pass   # autosave recovery is best-effort; never block startup

    _sys.exit(app.exec_())
