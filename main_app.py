"""
main_app.py

Microsanj Thermoreflectance System — Main Application Window.

Combines camera, TEC, and acquisition into a single unified interface.
Tabs: Acquire | Camera | Temperature | Log

Run:  python3 main_app.py
"""

from __future__ import annotations

# ── Pre-boot crash guard ──────────────────────────────────────────────────────
# MUST stay at the top of this file — before every other import.
#
# On Windows with console=False (the production installer build), any exception
# that occurs before the Qt window appears is completely invisible: the process
# simply vanishes with no window, no log, and no error dialog.
#
# This block installs a sys.excepthook using ONLY stdlib (so it works even if
# PyQt5, numpy, or any bundled package fails to import).  On a crash it:
#   1. Writes a timestamped crash report to ~/.microsanj/logs/startup_crash.txt
#   2. Shows a native Windows MessageBox via ctypes (no Qt required)
#   3. Exits with code 1
#
# The handler is later superseded by the richer Qt-aware hook installed inside
# main(), so this is purely the "before Qt exists" safety net.
# ─────────────────────────────────────────────────────────────────────────────
import sys    as _sys_boot
import os     as _os_boot
import time   as _time_boot
import traceback as _tb_boot

# On macOS, OpenCV's AVFoundation backend tries to request Camera permission
# from whichever thread calls cv2.VideoCapture() — but macOS only allows the
# authorization dialog on the main thread.  Setting this env var tells OpenCV
# to skip the in-process auth request and just fail fast if permission has not
# already been granted via System Settings → Privacy & Security → Camera.
# The user grants permission once; after that VideoCapture opens normally.
if _sys_boot.platform == "darwin":
    _os_boot.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

_BOOT_LOG_DIR  = _os_boot.path.join(_os_boot.path.expanduser("~"), ".microsanj", "logs")
_BOOT_CRASH    = _os_boot.path.join(_BOOT_LOG_DIR, "startup_crash.txt")


def _write_crash_report(msg: str) -> None:
    """Write crash details to the crash file and, if available, the log.

    Uses only stdlib for the file write so it works even when PyQt5 and
    the rotating log handler have not yet been set up.  Never raises.
    """
    # Route through the logging system when it is already configured
    # (i.e. after logging_config.setup() has run inside __main__).
    try:
        import logging as _logging_boot
        _root_log = _logging_boot.getLogger()
        if _root_log.handlers:
            _root_log.critical("STARTUP CRASH: %s", msg)
            for _lh in _root_log.handlers:
                try:
                    _lh.flush()
                except Exception:
                    pass
    except Exception:
        pass

    # Always write to the dedicated crash file — works before any logging setup
    try:
        _os_boot.makedirs(_BOOT_LOG_DIR, exist_ok=True)
        with open(_BOOT_CRASH, "a", encoding="utf-8") as _fh:
            _fh.write(
                f"\n{'='*60}\n"
                f"SanjINSIGHT startup crash\n"
                f"Time    : {_time_boot.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Python  : {_sys_boot.version}\n"
                f"Platform: {_sys_boot.platform}\n"
                f"Exe     : {getattr(_sys_boot, 'executable', '?')}\n"
                f"{'='*60}\n"
                f"{msg}\n"
            )
    except Exception:
        pass  # If we can't write the file there's nothing more we can do


def _pre_boot_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Global exception handler active from the very first import onward."""
    msg = "".join(_tb_boot.format_exception(exc_type, exc_value, exc_tb))
    _write_crash_report(msg)

    # Native Windows message box — works with no Qt, no console
    if _sys_boot.platform == "win32":
        try:
            import ctypes as _ctypes
            _ctypes.windll.user32.MessageBoxW(
                0,
                (
                    f"SanjINSIGHT could not start.\n\n"
                    f"Error: {exc_type.__name__}: {exc_value}\n\n"
                    f"A full crash report has been saved to:\n"
                    f"{_BOOT_CRASH}\n\n"
                    f"Please send this file to Microsanj support."
                ),
                "SanjINSIGHT — Startup Error",
                0x10,   # MB_ICONERROR
            )
        except Exception:
            pass

    _sys_boot.exit(1)


_sys_boot.excepthook = _pre_boot_excepthook

# Write a startup-attempt marker so support knows the app was launched.
# This line is overwritten / appended on each launch; a crash report
# appearing after a "=== STARTED ===" line confirms the app did reach
# Python startup (as opposed to a missing DLL caught by Windows before
# Python runs at all).
_write_crash_report(
    f"=== STARTED === {_time_boot.strftime('%Y-%m-%d %H:%M:%S')}  "
    f"argv={_sys_boot.argv}"
)
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os
import re
import time
import threading
import collections
import logging

log = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, Future
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QComboBox, QTextEdit, QTabWidget, QFileDialog, QFrame,
    QSizePolicy, QButtonGroup, QSplitter, QStatusBar,
    QAction, QMenuBar, QMessageBox, QStackedWidget,
    QCheckBox, QScrollArea, QDockWidget, QDialog)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt5.QtGui   import (QImage, QPixmap, QFont, QColor, QPainter,
                           QPen, QBrush, QPalette, QIcon)

import config
from hardware.app_state  import app_state                   # ← thread-safe state
from acquisition         import (AcquisitionPipeline, AcquisitionResult,
                                AcquisitionProgress, AcqState,
                                to_display, apply_colormap, export_result)
from acquisition.roi             import Roi
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
from acquisition.measurement_orchestrator import (           # ← lifecycle state machine
    MeasurementOrchestrator, MeasurementPhase, MeasurementResult)
from acquisition.workflows import (                          # ← workflow profiles
    WorkflowProfile, FAILURE_ANALYSIS, METROLOGY, WORKFLOWS, get_workflow)
from ui.tabs.prober_tab          import ProberTab           # ← probe-station chuck
from ui.tabs.autoscan_tab        import AutoScanTab
from ui.scripting_console        import ScriptingConsoleTab # ← Python console
from ui.sidebar_nav              import SidebarNav          # ← grouped sidebar nav
from hardware.device_manager     import DeviceManager
from ui.device_manager_dialog    import DeviceManagerDialog
from ui.notifications            import (ToastManager, get_guidance)  # ← notifications
from profiles.profiles        import MaterialProfile
from profiles.profile_manager import ProfileManager
from profiles.profile_tab     import ProfileTab
from ui.settings_tab          import SettingsTab
from ui.widgets.safe_mode_banner import SafeModeBanner
from ui.widgets.shortcut_overlay import show_shortcut_overlay
from ui.widgets.command_palette import CommandPalette, PaletteItem
from hardware.requirements_resolver import (
    check_readiness, OP_ACQUIRE, OP_SCAN,
)
from utils import safe_call

# ------------------------------------------------------------------ #
#  App-wide style                                                     #
# ------------------------------------------------------------------ #
# The application stylesheet is generated by ui.theme.build_style()
# at startup (after DPI scaling) and on every theme switch.
# See the main() function below for the call site.

# ── Font-size scaling note ────────────────────────────────────────────────────
# The STYLE constant above is NOT scaled at module load time — scaling depends
# on the real screen DPI which is only available after QApplication is created.
# The scaling is applied inside main() immediately after app = QApplication()
# using a regex that catches all "font-size: Npt" patterns regardless of
# spacing, then stored in a local `_scaled_style` that is passed to
# app.setStyleSheet().  See the DPI-aware block in main() below.


def _style_pt(macos_pt: int) -> str:
    """Return a CSS font-size declaration scaled for the actual screen DPI.

    Reads ``ui.theme._DPI_SCALE`` which is set by ``apply_dpi_scale()`` in
    main() once the real screen DPI is known.  Falls back to a platform guess
    if called before app startup (e.g. during import-time widget construction).

    Example::
        f"QMenuBar {{ font-size: {_style_pt(12)}; }}"
    """
    from ui.theme import _DPI_SCALE
    return f"{max(8, int(round(macos_pt * _DPI_SCALE)))}pt"


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
from version import __version__, APP_NAME, APP_VENDOR, version_string, SUPPORT_EMAIL
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
    from ui.theme import PALETTE
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


# ── UI widgets and tabs (extracted to their own modules) ──────────────
from ui.widgets.status_header       import StatusHeader
from ui.widgets.camera_context_bar  import CameraContextBar
from ui.tabs.acquire_tab      import AcquireTab
from ui.tabs.camera_tab       import CameraTab
from ui.tabs.temperature_tab  import TemperatureTab
from ui.tabs.fpga_tab         import FpgaTab
from ui.tabs.bias_tab         import BiasTab
from ui.tabs.stage_tab        import StageTab
from ui.tabs.roi_tab          import RoiTab
from ui.tabs.autofocus_tab    import AutofocusTab, FocusPlot
from ui.tabs.log_tab          import LogTab
from ui.tabs.capture_tab           import CaptureTab
from ui.tabs.transient_capture_tab import TransientCaptureTab
from ui.tabs.camera_control_tab    import CameraControlTab
from ui.tabs.stimulus_tab          import StimulusTab
from ui.tabs.library_tab           import LibraryTab
from ui.tabs.wavelength_tab        import WavelengthTab
from ui.tabs.emissivity_cal_tab    import EmissivityCalTab
from ui.tabs.timing_diagram_tab    import TimingDiagramTab
from ui.tabs.focus_stage_tab       import FocusStageTab
from ui.tabs.modality_section      import ModalitySection
from ui.tabs.acquisition_settings_section import AcquisitionSettingsSection
from ui.tabs.signal_check_section  import SignalCheckSection
from ui.workspace                  import get_manager as _get_ws_manager
from ui.phase_tracker              import PhaseTracker
from ui.widgets.bottom_drawer      import BottomDrawer, DrawerToggleBar
from ui.widgets.measurement_strip  import MeasurementReadoutStrip
from ui.charts                     import dTSparklineWidget
from ai.metrics_service          import MetricsService
from ai.diagnostic_engine        import DiagnosticEngine
from ui.widgets.readiness_widget import ReadinessWidget
from ui.widgets.acquisition_summary_overlay import AcquisitionSummaryOverlay
from ui.widgets.optimization_suggestions import OptimizationSuggestionsWidget
from ui.widgets.batch_progress_widget import BatchProgressWidget
from ai.ai_service               import AIService
from ai.model_runner             import llama_available
from ai.model_downloader         import ModelDownloader, RECOMMENDED_MODEL, DEFAULT_MODELS_DIR
from ui.widgets.ai_panel_widget  import AIPanelWidget


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

class _FlexStack(QStackedWidget):
    """QStackedWidget that reports a zero minimum-size hint.

    When placed in a QSplitter the splitter uses minimumSizeHint() to
    determine how much space each child must keep.  Returning (0,0) lets
    the splitter freely shrink the mode-stack so the bottom drawer can
    always open to its target height regardless of the current tab's
    preferred size.
    """
    def minimumSizeHint(self):          # noqa: N802
        return QSize(0, 0)


class _SplitterTop(QWidget):
    """Container for the top pane of the content splitter.

    No QLayout is installed on this widget — the single child (SidebarNav)
    is positioned manually in resizeEvent.  This is deliberate:

    Qt's QSplitter internally calls qSmartMinSize() during setSizes().
    When a widget *has a layout*, qSmartMinSize() uses
    ``widget.layout().minimumSize()`` as a hard floor — completely
    bypassing any minimumSizeHint() override.  The SidebarNav and its
    12 tabs have a layout minimum of several hundred pixels, which
    prevents setSizes([total-240, 240]) from ever giving the bottom
    drawer its full target height.

    By installing *no layout* here, qSmartMinSize() falls back to
    ``minimumSizeHint()`` (which we override to (0, 0)), giving the
    splitter complete freedom to allocate space to the drawer.
    """

    def __init__(self, child: QWidget, parent=None) -> None:
        super().__init__(parent)
        child.setParent(self)
        # Qt's setParent() marks the child as hidden.  Call show() here so the
        # child's "explicitly shown" flag is set — it will become visible when
        # this container widget is shown by the splitter.
        child.show()
        self._child = child

    def minimumSizeHint(self) -> QSize:   # noqa: N802
        return QSize(0, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._child.setGeometry(self.rect())


# ------------------------------------------------------------------ #
#  Main Window                                                        #
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    # Emitted (from any thread) when a real device connects while in demo mode
    # — the connected slot runs on the GUI thread to clean up the demo UI.
    _demo_auto_exited = pyqtSignal()

    def __init__(self, auth=None, auth_session=None):
        super().__init__()
        self._auth         = auth
        self._auth_session = auth_session
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
        # Show logged-in user name in the operator slot when auth is active
        if self._auth_session is not None:
            self._header.update_from_session(self._auth_session)

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

        # Safe-mode banner — shown when a required device is absent.
        # Sits between the header and content area; hidden by default.
        self._safe_banner = SafeModeBanner()
        self._safe_banner.device_manager_requested.connect(
            self._open_device_manager)
        root.addWidget(self._safe_banner)

        # Global camera context bar — shows active camera selector across all tabs.
        # Auto-hides itself when only one camera is configured.
        self._cam_bar = CameraContextBar()
        self._cam_bar.camera_changed.connect(self._on_camera_bar_changed)
        root.addWidget(self._cam_bar)

        # Live BT/dT/CT measurement readout strip — sits between camera bar and content.
        # Receives TEC status via _on_tec(); always visible when TECs are present.
        self._measurement_strip = MeasurementReadoutStrip()
        root.addWidget(self._measurement_strip)

        # dT rolling sparkline — hidden by default; shown when TEC data arrives.
        # Displays a 2-minute scrolling history of ΔT so the user can see
        # thermal drift and stability at a glance without opening a separate tab.
        self._dt_sparkline = dTSparklineWidget()
        self._dt_sparkline.setVisible(False)
        root.addWidget(self._dt_sparkline)

        # Content splitter: nav widget above, BottomDrawer (Console+Log) below.
        # BottomDrawer is collapsed to 0 by default; Ctrl+` toggles it.
        self._content_splitter = QSplitter(Qt.Vertical)
        self._content_splitter.setHandleWidth(5)
        self._content_splitter.setOpaqueResize(True)
        # nav widget added below after adv_widget is built
        self._content_splitter.setCollapsible(0, False)
        root.addWidget(self._content_splitter, 1)

        # Always-visible toggle bar below the splitter.
        # Provides Console / Log buttons + open/close chevron even when drawer == 0 px.
        self._batch_progress = BatchProgressWidget()
        root.addWidget(self._batch_progress)
        self._drawer_toggle_bar = DrawerToggleBar()
        root.addWidget(self._drawer_toggle_bar)

        # ---- Auto mode ----
        # (built after profile manager; added to stack below)

        # ---- Manual mode: sidebar navigation ----
        # _SplitterTop has no layout — see class docstring for why this matters.
        self._nav = SidebarNav(app_name="SanjINSIGHT")
        adv_widget = _SplitterTop(self._nav)

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

        # Stage "Open Device Manager" — standalone, wire here
        self._stage_tab.open_device_manager.connect(self._open_device_manager)

        self._roi_tab      = RoiTab()
        self._af_tab       = AutofocusTab()
        self._cal_tab      = CalibrationTab()
        self._scan_tab     = ScanTab()
        self._profile_tab  = ProfileTab(self._profile_mgr)
        self._data_tab     = DataTab(session_mgr)
        self._log_tab      = LogTab()
        self._settings_tab = SettingsTab(
            auth=self._auth, auth_session=self._auth_session)

        # ── Metrics service + readiness banner ───────────────────
        self._metrics = MetricsService(hw_service, parent=self)
        self._readiness_widget = ReadinessWidget()
        self._metrics.metrics_updated.connect(
            self._readiness_widget.update_metrics)
        self._metrics.metrics_updated.connect(self._update_tab_attention)
        self._acquire_tab.insert_readiness_widget(self._readiness_widget)

        # ── Post-acquisition summary overlay ──────────────────────
        self._acq_summary_overlay = AcquisitionSummaryOverlay()
        self._acquire_tab.insert_readiness_widget(self._acq_summary_overlay)

        # ── Live optimisation suggestions ─────────────────────────
        self._suggestions = OptimizationSuggestionsWidget()
        self._metrics.metrics_updated.connect(self._suggestions.update_metrics)
        self._acquire_tab.insert_suggestions_widget(self._suggestions)
        self._suggestions.action_requested.connect(
            self._on_suggestion_action)

        # ── AI service + model downloader + dockable panel ────────
        self._last_grade: str = ""         # tracks grade for change notifications
        self._acq_start_grade: str = "A"  # grade snapshot at acquisition start
        self._acq_start_issues: list = [] # issue snapshot at acquisition start
        self._acq_start_ts:  float = 0.0  # wall-clock time at acquisition start
        self._scan_start_ts: float = 0.0  # wall-clock time at scan start
        self._diagnostic_engine = DiagnosticEngine(self._metrics)

        # ── Measurement orchestrator (lifecycle state machine) ────
        self._measurement_orch = MeasurementOrchestrator(
            hw_service=hw_service,
            app_state=app_state,
            parent=self,
        )
        # Give the orchestrator access to metrics (device_mgr wired later)
        self._measurement_orch._metrics = self._metrics
        self._measurement_orch.phase_changed.connect(
            self._on_measurement_phase)
        self._measurement_orch.user_decision_needed.connect(
            self._on_measurement_decision)
        self._measurement_orch.measurement_complete.connect(
            self._on_measurement_complete)
        # Default workflow — can be changed via the workflow selector
        self._active_workflow = None  # WorkflowProfile | None
        # Feature flag: set to True once orchestrator is validated
        self._use_orchestrator = config.get_pref(
            "acquisition.use_orchestrator", True)

        self._ai_service = AIService(parent=self)
        self._ai_service.set_metrics(self._metrics)
        self._ai_service.set_diagnostics(self._diagnostic_engine)
        self._ai_service.set_workspace_mode(
            config.get_pref("ui.workspace", "standard"))
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
        self._prober_tab.open_device_manager.connect(self._open_device_manager)
        self._temp_tab.open_device_manager.connect(self._open_device_manager)
        self._wavelength_tab   = WavelengthTab()               # ← monochromator control
        self._emissivity_tab   = EmissivityCalTab()             # ← IR emissivity cal
        self._timing_tab       = TimingDiagramTab()             # ← timing waveform viewer

        # ── Merged tabs ──────────────────────────────────────────────────
        # Each merged tab wraps multiple individual tabs into one sidebar entry.
        self._capture_tab           = CaptureTab(self._acquire_tab, self._scan_tab)
        self._transient_capture_tab = TransientCaptureTab(self._transient_tab, self._movie_tab)
        self._camera_ctrl_tab       = CameraControlTab(self._camera_tab, self._roi_tab, self._af_tab)
        self._stimulus_tab          = StimulusTab(self._fpga_tab, self._bias_tab)
        self._library_tab           = LibraryTab(self._profile_tab, self._recipe_tab)
        self._autoscan_tab          = AutoScanTab()

        # ── Phase-aware sections (new) ─────────────────────────────────
        self._modality_section      = ModalitySection()
        self._modality_section.open_device_manager.connect(
            self._open_device_manager)
        self._modality_section.modality_changed.connect(
            self._on_modality_changed)
        self._modality_section.profile_selected.connect(
            self._on_profile_applied)
        self._modality_section.navigate_requested.connect(
            self._nav.select_by_label)
        self._acq_settings_section  = AcquisitionSettingsSection()
        self._signal_check_section  = SignalCheckSection()
        self._focus_stage_tab       = FocusStageTab(
            self._af_tab, self._stage_tab, self._prober_tab)
        self._focus_stage_tab.open_device_manager.connect(
            self._open_device_manager)

        # ── Bottom drawer (Console + Log) ────────────────────────────────
        self._bottom_drawer = BottomDrawer(self._console_tab, self._log_tab)
        self._content_splitter.addWidget(adv_widget)          # index 0 — nav
        self._content_splitter.addWidget(self._bottom_drawer)
        self._content_splitter.setCollapsible(1, False)  # drag stops at minimum; use toggle bar to close
        self._bottom_drawer.hide()   # start hidden — splitter reclaims the space

        # Wire DrawerToggleBar ↔ bottom drawer
        self._drawer_toggle_bar.console_requested.connect(
            lambda: (self._bottom_drawer.show_console(),
                     self._drawer_toggle_bar.set_active_tab(0)))
        self._drawer_toggle_bar.log_requested.connect(
            lambda: (self._bottom_drawer.show_log(),
                     self._drawer_toggle_bar.set_active_tab(1)))
        self._drawer_toggle_bar.toggle_requested.connect(self._toggle_bottom_drawer)

        # Wire "Open Device Manager" from merged hardware tabs → MainWindow
        self._camera_ctrl_tab.open_device_manager.connect(self._open_device_manager)
        self._stimulus_tab.open_device_manager.connect(self._open_device_manager)

        # Wire "Go to Acquire" from the analysis empty-state button
        self._analysis_tab.navigate_to_acquire.connect(
            lambda: self._nav.navigate_to(self._capture_tab))

        # Wire recipe RUN signal → apply recipe to hardware
        self._recipe_tab.recipe_run.connect(self._apply_recipe)

        # Wire Library tab "Apply" → propagate profile to header + hardware
        self._library_tab.profile_applied.connect(self._on_profile_applied)

        # Wire header Profile button → save / load / manage
        from acquisition.recipe_tab import RecipeStore
        self._recipe_store = RecipeStore()
        self._header._profile_btn.set_recipe_store(self._recipe_store)
        self._header._profile_btn.save_requested.connect(self._save_profile_dialog)
        self._header._profile_btn.profile_selected.connect(self._load_profile)
        self._header._profile_btn.manage_requested.connect(self._navigate_to_profiles)

        # Wire Settings tab → theme toggle (Auto / Dark / Light)
        self._settings_tab.theme_changed.connect(self.apply_theme)

        # Wire Settings tab → workspace mode (Guided / Standard / Expert)
        self._settings_tab.workspace_changed.connect(self._on_workspace_changed)

        # Wire Settings tab → manual update check
        self._settings_tab.check_for_updates_requested.connect(
            self._on_manual_update_check)

        # NOTE: AI service + downloader signals are connected below (after
        # AI panel signals) in the "AI service signals" block near line 920+.
        # Cloud and Ollama signals are connected here because they don't
        # appear in that block.

        # Wire Settings tab → AI service (cloud)
        self._settings_tab.cloud_ai_connect_requested.connect(
            self._on_cloud_ai_connect)
        self._settings_tab.cloud_ai_disconnect_requested.connect(
            self._on_cloud_ai_disconnect)

        # Wire Settings tab → AI service (Ollama)
        self._settings_tab.ollama_connect_requested.connect(
            self._on_ollama_connect)
        self._settings_tab.ollama_disconnect_requested.connect(
            self._on_ollama_disconnect)

        # ── Register all panels with the sidebar nav ──────────────────
        from ui.sidebar_nav import NavItem as NI
        from ui.icons import NAV_ICONS as _I

        # Phase 1: CONFIGURATION
        self._nav.add_phase(1, "CONFIGURATION",
            "Set up your hardware and measurement parameters", [
            NI("Modality",             _I["Modality"],             self._modality_section),
            NI("Stimulus",             _I["Stimulus"],             self._stimulus_tab),
            NI("Timing",               _I["Timing"],               self._timing_tab),
            NI("Temperature",          _I["Temperature"],          self._temp_tab),
            NI("Acquisition Settings", _I["Acquisition Settings"], self._acq_settings_section),
        ])

        # Phase 2: IMAGE ACQUISITION
        self._nav.add_phase(2, "IMAGE ACQUISITION",
            "Preview, focus, and verify your signal", [
            NI("Live View",     _I["Live View"],     self._live_tab),
            NI("Focus & Stage", _I["Focus & Stage"], self._focus_stage_tab),
            NI("Signal Check",  _I["Signal Check"],  self._signal_check_section),
        ])

        # Phase 3: ANALYSIS
        self._nav.add_phase(3, "ANALYSIS",
            "Capture data and analyze results", [
            NI("Capture",     _I["Capture"],     self._capture_tab),
            NI("Calibration", _I["Calibration"], self._cal_tab),
            NI("Sessions",    _I["Sessions"],    self._data_tab),
            NI("Emissivity",  _I["Emissivity"],  self._emissivity_tab),
        ])

        # ─── separator ───
        self._nav.add_separator()

        # HARDWARE (collapsible — Camera, Stage, Prober controls)
        self._nav.add_collapsible("HARDWARE", "mdi.chip", [
            NI("Camera",  _I["Camera"],  self._camera_ctrl_tab),
            NI("Stage",   _I["Stage"],   self._stage_tab),
            NI("Prober",  _I["Prober"],  self._prober_tab),
        ])

        # SYSTEM
        self._nav.add_section("SYSTEM", [
            NI("Library",     _I["Library"],    self._library_tab),
            NI("Settings",    _I["Settings"],    self._settings_tab),
        ])

        # ─── Plugin system ────────────────────────────────────────────
        self._wire_plugins(NI, _I)

        self._nav.finish()

        # Apply initial workspace mode
        ws_mgr = _get_ws_manager()
        self._nav.set_workspace_mode(ws_mgr.mode.value)
        self._modality_section.set_workspace_mode(ws_mgr.mode.value)
        for w in (self._live_tab, self._focus_stage_tab,
                  self._signal_check_section, self._capture_tab,
                  self._cal_tab):
            if hasattr(w, "set_workspace_mode"):
                w.set_workspace_mode(ws_mgr.mode.value)
        ws_mgr.mode_changed.connect(self._nav.set_workspace_mode)
        # Mode indicator in sidebar header cycles through modes
        self._nav.mode_cycle_requested.connect(self._on_workspace_changed)

        # Phase completion tracker
        self._phase_tracker = PhaseTracker(parent=self)
        self._phase_tracker.phase_updated.connect(self._nav.set_phase_badge)
        self._phase_tracker.phase_updated.connect(
            lambda *_: self._nav.update_guided_banner(self._phase_tracker))
        self._phase_tracker.phase_updated.connect(
            lambda *_: self._nav.update_guided_states(
                self._phase_tracker, _get_ws_manager().mode.value))
        # Initial banner + sidebar step indicators
        self._nav.update_guided_banner(self._phase_tracker)
        self._nav.update_guided_states(
            self._phase_tracker, _get_ws_manager().mode.value)
        # Skip button in guided banner → force-mark the step as done
        self._nav.guided_skip_requested.connect(
            lambda phase, key: self._phase_tracker.mark(phase, key, True))
        self._live_viewed_marked = False
        self._tec_target_marked = False

        # ── Auto-hide unconfigured items ──────────────────────────────────
        _hw_cfg = config.get("hardware", {})
        # Temperature: shown if at least one TEC is enabled
        if n_tecs == 0:
            self._nav.set_item_visible("Temperature", False)
        # Stimulus (FPGA+Bias): shown if FPGA is enabled
        if not _hw_cfg.get("fpga", {}).get("enabled", True):
            self._nav.set_item_visible("Stimulus", False)
        # Emissivity: always shown (applies to both real + simulated IR cameras)

        # Wire monochromator driver into WavelengthTab if available
        try:
            from hardware.monochromator.factory import build_monochromator
            _mono_driver = build_monochromator(_hw_cfg.get("monochromator", {}))
            if _mono_driver is not None:
                self._wavelength_tab.set_driver(_mono_driver)
        except Exception:
            pass

        # Wire hardware sources into Timing Diagram tab for Sync buttons
        self._timing_tab.set_fpga_source(self._fpga_tab)
        self._timing_tab.set_transient_source(self._transient_tab)
        self._timing_tab.set_bias_source(self._bias_tab)

        self._nav.select_first()

        # Connect demo mode exit button
        self._header.exit_demo_requested.connect(self._deactivate_demo_mode)

        # Admin "Log in" / "Log out" buttons
        self._header.admin_login_requested.connect(self._on_admin_login)
        self._header.admin_logout_requested.connect(self._on_admin_logout)
        if self._auth is not None:
            try:
                self._header.set_auth_users_exist(
                    self._auth._store.has_users())
            except Exception:
                pass

        # AutoScanTab signal wiring
        self._autoscan_tab.scan_requested.connect(self._on_autoscan_scan_requested)
        self._autoscan_tab.send_to_analysis.connect(self._on_autoscan_send_to_analysis)
        self._autoscan_tab.abort_requested.connect(self._on_autoscan_abort_requested)

        # Device manager — dialog created eagerly (hidden) so hw_status_changed
        # is wired from app start.  The auto-scan now fires on first open (not
        # at __init__ time) so it never competes with the startup hw-init threads.
        self._device_mgr     = DeviceManager()
        self._device_mgr_dlg = DeviceManagerDialog(
            self._device_mgr, parent=self,
            # Suppress auto-scan in demo mode — user must click Scan explicitly.
            # The getter is evaluated lazily on each showEvent so it tracks the
            # current mode correctly throughout the session.
            demo_mode_getter=lambda: app_state.demo_mode,
        )
        self._header.add_device_manager_button(self._open_device_manager)
        # Now that device_mgr exists, wire it into the orchestrator
        self._measurement_orch._device_mgr = self._device_mgr
        self._device_mgr_dlg.hw_status_changed.connect(
            self._header.set_hw_btn_status)
        # Allow the Device Manager's "Demo Mode" button to activate demo mode.
        self._device_mgr_dlg.demo_requested.connect(self._activate_demo_mode)
        # Allow the Device Manager's "Setup Wizard" button to open the wizard.
        self._device_mgr_dlg.setup_wizard_requested.connect(self._open_hardware_setup)

        # Wire Device Manager → hw_service so the main window hears about
        # cameras / devices connected through the Device Manager dialog.
        # This fires hw_service.device_connected which triggers _on_device_hotplug
        # → camera selectors refresh, safe-mode re-evaluated, status header updated.
        self._device_mgr.set_post_inject_callback(self._on_device_mgr_injected)
        self._demo_auto_exited.connect(self._finish_auto_demo_exit)

        # Emergency stop — wire header button to hw_service
        self._header.connect_estop(
            on_stop  = self._trigger_estop,
            on_clear = self._clear_estop,
        )
        hw_service.emergency_stop_complete.connect(self._on_estop_complete)

        # Persistent system-health dropdown button
        self._header.add_readiness_dot()
        if self._header.system_btn is not None:
            self._header.system_btn.diagnostics_requested.connect(
                self._toggle_ai_panel)

        # Update badge in header
        self._update_badge = self._header.add_update_badge()
        self._update_badge.clicked_with_info.connect(self._show_update_dialog)

        # AI toggle button in header
        self._ai_btn = self._header.add_ai_button(self._toggle_ai_panel)
        # Restore AI enabled state from preferences
        import config as _cfg_ai
        # AI model loading is deferred to _on_startup_done() (~10 s after
        # first show) so that the heavy Metal/GPU init in llama-cpp doesn't
        # starve the main thread during widget construction.
        self._deferred_ai_enabled = _cfg_ai.get_pref("ai.enabled", False)
        self._deferred_ai_model_path = _cfg_ai.get_pref("ai.model_path", "")
        self._deferred_ai_n_gpu = _cfg_ai.get_pref("ai.n_gpu_layers", 0)

        # Help menu
        self._build_menu_bar()

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(f"SanjINSIGHT {version_string()}  —  Ready")

        # Toast notification manager — bottom-right corner of the window
        self._toasts = ToastManager(self)
        # Guard: suppress device-connection toasts during the startup window.
        # Set to True by _on_startup_done() (fired ~10 s after first show) so
        # post-startup hotplug reconnections still surface as toasts.
        self._startup_done = False

        # ── Command Palette ───────────────────────────────────────────
        self._cmd_palette = CommandPalette(self)
        self._cmd_palette.set_items(self._build_palette_items())

    def _build_palette_items(self) -> list:
        """Return all PaletteItems for the command palette (Ctrl+K)."""
        return [
            # ── CONFIGURATION ─────────────────────────────────────────
            PaletteItem("Modality",             "Configuration",
                        lambda: self._nav.navigate_to(self._modality_section),
                        keywords=["modality", "camera", "objective", "fov", "lens"]),
            PaletteItem("Stimulus",             "Configuration",
                        lambda: self._nav.navigate_to(self._stimulus_tab),
                        keywords=["stimulus", "fpga", "modulation", "bias", "voltage", "iv", "sweep"]),
            PaletteItem("Timing",               "Configuration",
                        lambda: self._nav.navigate_to(self._timing_tab),
                        keywords=["timing", "diagram", "waveform", "pulse", "trigger"]),
            PaletteItem("Temperature",          "Configuration",
                        lambda: self._nav.navigate_to(self._temp_tab),
                        keywords=["temperature", "tec", "thermoelectric", "heat"]),
            PaletteItem("Acquisition Settings", "Configuration",
                        lambda: self._nav.navigate_to(self._acq_settings_section),
                        keywords=["acquisition", "frames", "exposure", "gain", "averaging"]),
            # ── IMAGE ACQUISITION ─────────────────────────────────────
            PaletteItem("Live View",            "Image Acquisition",
                        lambda: self._nav.navigate_to(self._live_tab),
                        keywords=["live", "stream", "preview", "camera"]),
            PaletteItem("Focus & Stage",        "Image Acquisition",
                        lambda: self._nav.navigate_to(self._focus_stage_tab),
                        keywords=["focus", "autofocus", "stage", "motion", "position", "prober"]),
            PaletteItem("Signal Check",         "Image Acquisition",
                        lambda: self._nav.navigate_to(self._signal_check_section),
                        keywords=["signal", "snr", "noise", "check", "verify"]),
            # ── ANALYSIS ──────────────────────────────────────────────
            PaletteItem("Capture",              "Measurement",
                        lambda: self._nav.navigate_to(self._capture_tab),
                        keywords=["capture", "acquire", "scan", "sweep", "map", "run", "start"]),
            PaletteItem("Calibration",          "Measurement",
                        lambda: self._nav.navigate_to(self._cal_tab),
                        keywords=["calibration", "cal", "reference"]),
            PaletteItem("Sessions",             "Measurement",
                        lambda: self._nav.navigate_to(self._data_tab),
                        keywords=["sessions", "data", "history", "export", "compare", "analysis"]),
            PaletteItem("Emissivity",           "Measurement",
                        lambda: self._nav.navigate_to(self._emissivity_tab),
                        keywords=["emissivity", "ir", "infrared", "thermal", "blackbody"]),
            # ── SYSTEM ────────────────────────────────────────────────
            PaletteItem("Settings",             "System",
                        lambda: self._nav.navigate_to(self._settings_tab),
                        keywords=["settings", "preferences", "config", "theme", "workspace"]),
        ]

    def _connect_signals(self):
        self._last_ir_frame = None      # most recent frame for emissivity capture
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
        # AutoScan live + result feeds
        signals.new_live_frame.connect(self._autoscan_tab.on_live_frame)
        signals.acq_progress.connect(self._autoscan_tab.on_acq_progress)
        signals.acq_complete.connect(self._autoscan_tab.on_acq_complete)
        signals.scan_progress.connect(self._autoscan_tab.on_scan_progress)
        signals.scan_complete.connect(self._autoscan_tab.on_scan_complete)
        signals.log_message.connect(self._on_log)
        signals.error.connect(self._on_error)
        # TEC alarm signals
        hw_service.tec_alarm.connect(self._on_tec_alarm)
        hw_service.tec_warning.connect(self._on_tec_warning)
        hw_service.tec_alarm_clear.connect(self._on_tec_alarm_clear)

        # Device hotplug → refresh HW indicators in acquisition tabs
        hw_service.device_connected.connect(self._on_device_hotplug)

        # Signal check section → phase tracker
        self._signal_check_section.signal_check_passed.connect(
            lambda: self._phase_tracker.mark(2, "signal_checked"))

        # Camera selection from Connected Devices dropdown
        self._header.connect_camera_selection(self._on_camera_selected)

        # ── AI service signals ────────────────────────────────────
        self._ai_service.status_changed.connect(self._on_ai_status)
        self._ai_service.tier_changed.connect(self._ai_panel.on_tier_changed)
        self._ai_service.tier_changed.connect(self._settings_tab.set_ai_tier)
        self._ai_service.response_token.connect(self._on_ai_token)
        self._ai_service.response_complete.connect(self._on_ai_response_complete)
        self._ai_service.ai_error.connect(self._on_ai_error)

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
        self._ai_panel.cancel_requested.connect(self._ai_service.cancel)
        self._ai_panel.export_requested.connect(self._ai_service.export_history)
        self._ai_panel.support_requested.connect(self._open_support_dialog)
        self._ai_panel.upgrade_nudge.connect(
            lambda msg: self._toasts.show_info(msg, auto_dismiss_ms=8000))
        self._ai_service.history_exported.connect(self._on_history_exported)

        # Auto-fix: wire the AI panel's fix button callback
        self._ai_panel.set_fix_callback(self._on_autofix_requested)

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
        self._nav.panel_changed.connect(self._on_panel_changed)

        # ReadinessWidget "Fix it →" buttons → auto-fix or sidebar navigation
        self._readiness_widget.navigate_requested.connect(
            self._nav.select_by_label)
        self._readiness_widget.fix_requested.connect(
            self._on_readiness_fix_requested)

        # Section "navigate" signals → sidebar navigation
        for w in (self._data_tab, self._focus_stage_tab,
                  self._signal_check_section, self._capture_tab):
            if hasattr(w, "navigate_requested"):
                w.navigate_requested.connect(self._nav.select_by_label)

        # Phase 5 tracking: data/export/reporting milestones
        self._data_tab.status_changed.connect(
            lambda uid, s: (self._phase_tracker.mark(5, "session_reviewed")
                            if s == "reviewed" else None))
        self._data_tab.export_completed.connect(
            lambda uid: self._phase_tracker.mark(5, "data_exported"))
        self._data_tab.report_completed.connect(
            lambda uid: self._phase_tracker.mark(5, "report_generated"))

        # Acquisition readiness gate
        self._acquire_tab.acquire_requested.connect(self._on_acquire_requested)
        self._acquire_tab.optimize_and_acquire_requested.connect(
            self._on_optimize_and_acquire)
        self._acquire_tab.workflow_changed.connect(self._on_workflow_selected)

        # Evidence panel — refresh every 3 s while the app is running
        self._evidence_timer = QTimer(self)
        self._evidence_timer.setInterval(3000)
        self._evidence_timer.timeout.connect(self._refresh_evidence_panel)
        self._evidence_timer.start()

        # Auto OS-theme polling — polls every 5 s while pref == "auto"
        from ui.theme import detect_system_theme as _dst, active_theme as _at
        self._last_system_theme = _at()
        self._auto_theme_timer = QTimer(self)
        self._auto_theme_timer.setInterval(5000)
        self._auto_theme_timer.timeout.connect(self._poll_system_theme)
        if config.get_pref("ui.theme", "auto") == "auto":
            self._auto_theme_timer.start()

    # ── Theme switching ───────────────────────────────────────────────────────

    def _restyle_menu_bar(self) -> None:
        """Apply PALETTE-aware colours to the native menu bar and drop-down menus."""
        from ui.theme import PALETTE
        mb = getattr(self, "_menu_bar", self.menuBar())
        bg   = PALETTE['bg']
        surf = PALETTE['surface']
        txt  = PALETTE['text']
        sub  = PALETTE['textSub']
        bdr  = PALETTE['border']
        sel  = PALETTE['accent']
        mb.setStyleSheet(
            f"QMenuBar {{ background:{bg}; color:{sub}; font-size:{_style_pt(12)}; }}"
            f"QMenuBar::item:selected {{ background:{surf}; color:{txt}; }}"
            f"QMenu {{ background:{surf}; color:{txt}; border:1px solid {bdr}; }}"
            f"QMenu::item:selected {{ background:{sel}22; color:{txt}; }}"
        )

    # ── Action-button restyling ───────────────────────────────────────
    # Widget-level setStyleSheet("background:…") on parent containers
    # (toolbars, panels) cascades to child QPushButtons and overrides
    # the app-level QPushButton#primary / #danger rules.  Qt5 has no
    # reliable !important for app-level stylesheets, so we must apply
    # widget-level QSS directly on every named action button.  This is
    # called once after first show and again on every theme switch.

    def _restyle_action_buttons(self) -> None:
        from ui.theme import (btn_primary_qss, btn_danger_qss,
                              btn_cold_qss, btn_hot_qss)
        _qss = {
            "primary": btn_primary_qss(),
            "danger":  btn_danger_qss(),
            "cold_btn": btn_cold_qss(),
            "hot_btn":  btn_hot_qss(),
        }
        for btn in self.findChildren(QPushButton):
            qss = _qss.get(btn.objectName())
            if qss:
                btn.setStyleSheet(qss)

    def _swap_visual_theme(self, effective: str) -> None:
        """Core visual swap — applies 'dark' or 'light' with no flicker.

        Does NOT touch pref storage or the auto-polling timer.
        """
        from ui.theme import set_theme, build_qt_palette, build_style as _bs
        from ui.charts import refresh_pyqtgraph_globals
        app = QApplication.instance()
        self.setUpdatesEnabled(False)
        try:
            set_theme(effective)
            refresh_pyqtgraph_globals()
            app.setStyleSheet(_bs(effective))
            app.setPalette(build_qt_palette(effective))
            style = app.style()
            for w in app.allWidgets():
                style.unpolish(w)
                style.polish(w)
                if hasattr(w, "_apply_styles"):
                    w._apply_styles()
                w.update()
            self._restyle_action_buttons()
            self._restyle_menu_bar()
        finally:
            self.setUpdatesEnabled(True)
        app.processEvents()

    def apply_theme(self, mode: str) -> None:
        """Switch theme preference to 'auto', 'dark', or 'light'."""
        from ui.theme import detect_system_theme
        if mode == "auto":
            effective = detect_system_theme()
            self._last_system_theme = effective
            self._auto_theme_timer.start()
        else:
            self._auto_theme_timer.stop()
            effective = mode
        config.set_pref("ui.theme", mode)
        self._swap_visual_theme(effective)

    def _on_panel_changed(self, panel: QWidget) -> None:
        """Track which section the user visits for phase completion."""
        # AI context
        self._ai_service.set_active_tab(type(panel).__name__)
        # Phase 1: visiting Modality with a camera connected → camera_selected
        if panel is self._modality_section and app_state.cam is not None:
            self._phase_tracker.mark(1, "camera_selected")
        # Sessions: auto-select latest session if nothing is selected
        if panel is self._data_tab and self._data_tab._selected is None:
            self._data_tab.select_latest()

    def _update_tab_attention(self, snapshot: dict) -> None:
        """Update sub-tab attention dots from MetricsService snapshot."""
        issues = {i.get("code", "") for i in snapshot.get("issues", [])}

        # Focus & Stage: stage_not_homed → Stage sub-tab (index 1)
        if hasattr(self, "_focus_stage_tab"):
            self._focus_stage_tab.set_tab_attention(
                1, "stage_not_homed" in issues)

        # Stimulus: fpga issues → Modulation sub-tab (0), bias → won't map yet
        if hasattr(self, "_stimulus_tab"):
            self._stimulus_tab.set_tab_attention(
                0, bool(issues & {"fpga_not_running", "fpga_not_locked"}))

        # Camera controls: camera issues → Camera sub-tab (0)
        if hasattr(self, "_camera_ctrl_tab"):
            self._camera_ctrl_tab.set_tab_attention(
                0, bool(issues & {"camera_saturated", "camera_underexposed",
                                  "camera_disconnected"}))

    # ── Plugin system ────────────────────────────────────────────────────

    def _wire_plugins(self, NI, _I) -> None:
        """Discover, load, and wire plugins into the UI.

        Called from _build_ui() after all built-in nav sections are
        registered but *before* ``self._nav.finish()``.
        """
        try:
            from plugins.loader import PluginLoader
            from plugins.registry import PluginRegistry
            from plugins.base import (
                HardwarePanelPlugin, AnalysisViewPlugin,
                ToolPanelPlugin, DrawerTabPlugin,
                HardwareDriverPlugin,
            )
            from ui.theme import register_theme_listener

            self._plugin_registry = PluginRegistry()
            self._plugin_loader = PluginLoader(
                self._plugin_registry,
                hw_service=getattr(self, "_hw_service", None),
                app_state=None,
                signals=None,
                event_bus=None,
            )

            loaded = self._plugin_loader.discover_and_load()
            if not loaded:
                log.debug("No plugins loaded.")
                return

            # Wire hardware panels into a PLUGINS collapsible section
            hw_plugins = self._plugin_registry.get_by_type("hardware_panel")
            if hw_plugins:
                hw_items = []
                for p in hw_plugins:
                    panel = p.create_panel()
                    hw_items.append(NI(p.get_nav_label(), p.get_nav_icon(), panel))
                self._nav.add_collapsible("PLUGINS · HARDWARE", "mdi.puzzle", hw_items)

            # Wire tool panels into a TOOLS section
            tool_plugins = self._plugin_registry.get_by_type("tool_panel")
            if tool_plugins:
                tool_items = []
                for p in tool_plugins:
                    panel = p.create_panel()
                    tool_items.append(NI(p.get_nav_label(), p.get_nav_icon(), panel))
                self._nav.add_section("TOOLS", tool_items)

            # Wire analysis views
            analysis_plugins = self._plugin_registry.get_by_type("analysis_view")
            if analysis_plugins:
                analysis_items = []
                for p in analysis_plugins:
                    panel = p.create_panel()
                    analysis_items.append(NI(p.get_nav_label(), p.get_nav_icon(), panel))
                self._nav.add_section("ANALYSIS · PLUGINS", analysis_items)

            # Wire drawer tabs
            drawer_plugins = self._plugin_registry.get_by_type("drawer_tab")
            for p in drawer_plugins:
                tab_widget = p.create_tab()
                self._bottom_drawer.add_tab(
                    tab_widget, p.get_tab_label(), p.get_tab_icon())

            # Wire hardware drivers into device registry
            driver_plugins = self._plugin_registry.get_by_type("hardware_driver")
            for p in driver_plugins:
                try:
                    from hardware.device_registry import register_external
                    register_external(p.get_device_descriptor())
                except Exception:
                    log.warning("Failed to register driver plugin '%s'",
                                type(p).__name__, exc_info=True)

            # Register theme listener so plugins get notified on switch
            register_theme_listener(self._plugin_registry.notify_theme_changed)

            log.info("Loaded %d plugin(s): %s", len(loaded),
                     ", ".join(m.name for m in loaded))

            # Update settings tab plugin list
            if hasattr(self, "_settings_tab"):
                self._settings_tab.refresh_plugins_list(self._plugin_registry)

        except Exception:
            log.debug("Plugin system unavailable or failed to load.",
                      exc_info=True)

    def _on_workspace_changed(self, mode: str) -> None:
        """Handle workspace mode switch from Settings or sidebar indicator."""
        mgr = _get_ws_manager()
        mgr.set_mode(mode)
        # Adjust bottom drawer visibility based on mode
        if mode == "expert" and not self._bottom_drawer.isVisible():
            self._toggle_bottom_drawer()
        elif mode == "guided" and self._bottom_drawer.isVisible():
            self._toggle_bottom_drawer()
        # Update log verbosity
        if hasattr(self._log_tab, "set_verbosity"):
            self._log_tab.set_verbosity(mgr.console_verbosity())
        # Update AI agent behaviour
        if hasattr(self, "_ai_service"):
            self._ai_service.set_workspace_mode(mode)
        # Refresh sidebar step indicators for the new mode
        if hasattr(self, "_phase_tracker"):
            self._nav.update_guided_states(self._phase_tracker, mode)
        # Switch section layouts (Guided vs compact)
        for w in (getattr(self, "_modality_section", None),
                  getattr(self, "_live_tab", None),
                  getattr(self, "_focus_stage_tab", None),
                  getattr(self, "_signal_check_section", None),
                  getattr(self, "_capture_tab", None),
                  getattr(self, "_cal_tab", None)):
            if w is not None and hasattr(w, "set_workspace_mode"):
                w.set_workspace_mode(mode)
        # Sync settings tab buttons if change came from sidebar indicator
        if hasattr(self, "_settings_tab"):
            idx = {"guided": 0, "standard": 1, "expert": 2}.get(mode, 1)
            if hasattr(self._settings_tab, "_ws_btn_grp"):
                btn = self._settings_tab._ws_btn_grp.button(idx)
                if btn and not btn.isChecked():
                    btn.setChecked(True)
                    # Update descriptor label too
                    self._settings_tab._on_workspace_btn(idx)

    def _poll_system_theme(self) -> None:
        """Called every 5 s while auto mode is active; swaps if OS theme changed."""
        from ui.theme import detect_system_theme
        current = detect_system_theme()
        if current != getattr(self, "_last_system_theme", None):
            self._last_system_theme = current
            self._swap_visual_theme(current)

    # ── Camera frames ─────────────────────────────────────────────────────────

    def _on_frame(self, frame):
        # Ack immediately so the camera thread can queue the next frame while
        # we process this one.  This keeps Qt's event queue bounded to ≤1
        # pending frame regardless of camera fps or VM event-loop latency.
        hw_service.ack_camera_frame()
        self._last_ir_frame = frame     # keep latest for emissivity capture
        self._camera_tab.update_frame(frame)
        self._acquire_tab.update_live(frame)
        self._roi_tab.update_frame(frame.data)
        self._modality_section.update_preview(frame)
        # Use the typed camera key so the right row lights up in the device list
        cam = app_state.cam
        if cam is not None:
            cam_key = ("tr_camera" if getattr(cam.info, "camera_type", "tr") == "tr"
                       and app_state.ir_cam is not None else "camera")
            if getattr(cam.info, "camera_type", "tr") == "ir":
                cam_key = "ir_camera"
            self._header.set_connected(cam_key, True)
        self._status.showMessage(
            f"Camera: {cam.info.model if cam else ''}  |  "
            f"Frame {frame.frame_index}  |  "
            f"Exp {frame.exposure_us:.0f}μs")

        # Phase tracker: mark live view as visited (one-shot)
        if not self._live_viewed_marked:
            self._live_viewed_marked = True
            self._phase_tracker.mark(2, "live_viewed")

        # Feed signal check section
        self._signal_check_section.update_frame(frame)

    def _read_ir_camera_temp(self) -> float:
        """Return the mean pixel value of the latest IR frame (°C-equivalent).

        Used by the emissivity tab's "Capture from camera" button.
        On macOS the Boson runs in 8-bit AGC mode (uint8 scaled to uint16),
        so the value is an uncalibrated mean — the user enters the true
        blackbody temperature manually.
        """
        f = self._last_ir_frame
        if f is None or f.data is None:
            raise RuntimeError("No IR frame available — is the camera running?")
        import numpy as np
        return float(np.mean(f.data))

    def _on_tec(self, index, status):
        # Ignore stale status updates from simulated TEC drivers that
        # were queued before demo-mode shutdown completed.
        if not app_state.demo_mode:
            tec_list = getattr(app_state, 'tecs', None) or []
            if index >= len(tec_list) or tec_list[index] is None:
                return
        self._temp_tab.update_tec(index, status)
        key = f"tec{index}"
        ok  = status.error is None
        tip = (f"TEC {index+1}: {status.actual_temp:.1f}°C → {status.target_temp:.1f}°C"
               if ok else f"TEC {index+1} error: {status.error}")
        self._header.set_connected(key, ok, tip)
        self._cam_bar.set_peripheral("tec", ok, tip)

        # Phase tracker: mark temperature_set once a non-zero setpoint is active
        if ok and not self._tec_target_marked:
            sp = getattr(status, "target_temp", None)
            if sp is not None and sp != 0:
                self._tec_target_marked = True
                self._phase_tracker.mark(1, "temperature_set")

        # Update live BT/dT readout strip from primary TEC (index 0)
        if index == 0 and ok:
            bt = getattr(status, "actual_temp", None)
            sp = getattr(status, "target_temp", None)
            dt = (bt - sp) if (bt is not None and sp is not None) else None
            self._measurement_strip.set_values(bt_c=bt, dt_c=dt)
            self._dt_sparkline.push_dt(dt)
            if not self._dt_sparkline.isVisible():
                self._dt_sparkline.setVisible(True)

    def _on_fpga(self, status):
        if app_state.fpga is None and not app_state.demo_mode:
            return
        self._fpga_tab.update_status(status)
        if app_state.fpga is None:
            return
        ok  = status.error is None and status.running
        tip = ("FPGA: running" if ok else
               f"FPGA error: {status.error}" if status.error else "FPGA: stopped")
        self._header.set_connected("fpga", ok, tip)
        self._cam_bar.set_peripheral("fpga", ok, tip)

    def _on_bias(self, status):
        if app_state.bias is None and not app_state.demo_mode:
            return
        self._bias_tab.update_status(status)
        if app_state.bias is None:
            return
        ok  = status.error is None and status.output_on
        tip = (f"Bias: {status.actual_voltage:.3f}V / {status.actual_current*1000:.2f}mA"
               if ok else
               f"Bias error: {status.error}" if status.error else "Bias: output off")
        self._header.set_connected("bias", ok, tip)
        self._cam_bar.set_peripheral("bias", ok, tip)

    def _on_stage(self, status):
        # Ignore stale status updates from simulated stage drivers that
        # were queued before the demo-mode shutdown completed.
        if app_state.stage is None and not app_state.demo_mode:
            return
        self._stage_tab.update_status(status)
        ok  = status.error is None
        pos = status.position
        tip = (f"Stage: {pos.x:.0f} / {pos.y:.0f} / {pos.z:.0f} μm" if ok
               else f"Stage error: {status.error}")
        self._header.set_connected("stage", ok, tip)
        self._cam_bar.set_peripheral("stage", ok, tip)

    def _on_cal_progress(self, prog):
        self._cal_tab.update_progress(prog)
        self._log_tab.append(prog.message)

    def _on_cal_complete(self, result):
        self._cal_tab.update_complete(result)
        self._phase_tracker.mark(3, "calibrated", result.valid)
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
                log.debug("_on_scan_complete: winsound.MessageBeep failed",
                          exc_info=True)
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

        # ── Run manifest (scan) ───────────────────────────────────────
        # Scans are not yet saved through SessionManager, so there is no
        # session directory to write the manifest into.  A scan-specific
        # session save path is tracked for a future enhancement; for now
        # we emit the run event to the timeline bus only.
        try:
            from events import emit_info, EVT_SCAN_COMPLETE
            _rdns = check_readiness(OP_SCAN, app_state)
            emit_info("acquisition.scan", EVT_SCAN_COMPLETE,
                      f"Scan complete — {result.n_cols}×{result.n_rows} tiles  "
                      f"{result.duration_s:.0f}s",
                      n_cols=result.n_cols, n_rows=result.n_rows,
                      duration_s=result.duration_s,
                      degraded_mode=_rdns.degraded,
                      optional_devices_missing=_rdns.optional_missing)
        except Exception as _me:
            log.debug("Manifest event (scan) failed: %s", _me)

    # ── Centralized camera-mode refresh ──────────────────────────────

    def _refresh_camera_dependent_ui(self, cam_type: str, source: str = "") -> None:
        """Refresh ALL camera-mode-dependent UI after any camera switch.

        Called from every code path that changes the active camera:
        header dropdown, camera bar combo, and modality section combo.
        Ensures no panel is left showing stale controls (e.g. FFC on TR).
        """
        key = "tr_camera" if cam_type == "tr" else "ir_camera"
        self._header.set_active_device(key)
        self._refresh_all_camera_selectors()

        # Restart Live feed so it picks up the new camera immediately
        try:
            self._live_tab.restart_if_running()
        except Exception:
            log.debug("Live tab restart failed on camera switch", exc_info=True)

        # Refresh every tab/section that has mode-dependent controls
        _refresh_targets = [
            ("modality_section",    lambda: self._modality_section.refresh()),
            ("acq_settings",        lambda: self._acq_settings_section.refresh_camera_mode()),
            ("cal_tab",             lambda: self._cal_tab.refresh_camera_mode()),
            ("acquire_tab",         lambda: self._acquire_tab.refresh_camera_mode()),
            ("live_tab",            lambda: self._live_tab.refresh_camera_mode()),
            ("camera_tab",          lambda: self._camera_tab.refresh_camera_mode()),
        ]
        for name, fn in _refresh_targets:
            try:
                fn()
            except Exception:
                log.debug("%s camera refresh failed", name, exc_info=True)

        # Update profile filters to match camera modality
        try:
            self._profile_tab.set_modality_filter(cam_type)
        except Exception:
            log.debug("Profile modality filter update failed", exc_info=True)
        try:
            self._modality_section._profile_picker.filter_by_modality(cam_type)
        except Exception:
            log.debug("Profile picker modality filter failed", exc_info=True)

        # If the active profile doesn't match the new modality, clear it
        # from the header and app_state so the user isn't misled.
        active = getattr(app_state, "active_profile", None)
        if active is not None:
            profile_modality = getattr(active, "modality", "tr")
            if profile_modality not in (cam_type, "any"):
                app_state.active_profile = None
                try:
                    self._header.set_profile(None)
                except Exception:
                    log.debug("Header profile clear failed", exc_info=True)

        log.info("Camera mode refresh (%s): active camera → %s", source, cam_type)

    # ── Individual camera-switch entry points ─────────────────────────

    def _on_camera_selected(self, key: str) -> None:
        """
        Called when the user clicks a camera row in the Connected Devices dropdown.
        """
        if key in ("tr_camera", "camera"):
            cam_type = "tr"
        elif key == "ir_camera":
            cam_type = "ir"
        else:
            return

        # Guard: only switch if the target camera is actually connected
        target = app_state.cam if cam_type == "tr" else app_state.ir_cam
        if target is None:
            log.warning("Camera selection: %s not connected", key)
            return

        app_state.active_camera_type = cam_type
        self._refresh_camera_dependent_ui(cam_type, source="header_dropdown")

    def _on_camera_bar_changed(self, cam_type: str) -> None:
        """
        Called when the user picks a camera from the global CameraContextBar.
        The bar has already updated app_state.active_camera_type.
        """
        self._refresh_camera_dependent_ui(cam_type, source="camera_bar")

    def _on_modality_changed(self, cam_type: str) -> None:
        """Handle camera type change from ModalitySection's combo."""
        # Sync the camera context bar (it checks for redundant updates internally)
        try:
            self._cam_bar.set_camera_type(cam_type)
        except Exception:
            app_state.active_camera_type = cam_type
        self._refresh_camera_dependent_ui(cam_type, source="modality_section")

    def _refresh_all_camera_selectors(self) -> None:
        """
        Rebuild every camera selector in the app from the current registry.

        Called after any camera change (hotplug, device-popup click, bar
        combo change) to keep all controls in sync with app_state.
        """
        # Global bar
        try:
            self._cam_bar.refresh()
        except Exception:
            log.debug("camera bar refresh failed", exc_info=True)

        # AutoScan has its own per-tab combo with additional modality logic
        # (shows/hides objective controls, stimulus section, IR note).
        try:
            self._autoscan_tab.refresh_active_camera()
        except Exception:
            log.debug("autoscan camera refresh failed", exc_info=True)

    def _on_device_hotplug(self, key: str, ok: bool):
        """
        Called on the GUI thread whenever hw_service detects a device
        connect or disconnect event.

        Refreshes hardware-readiness labels in the acquisition tabs that
        display a static HW status panel (populated at showEvent but not
        otherwise updated while the tab is already visible).

        Also toggles Tier-1 tab empty-state placeholders so controls are
        hidden when the owning device is absent (unless demo mode is active).
        """
        try:
            self._movie_tab._refresh_hw()
            self._transient_tab._refresh_hw()
            self._prober_tab._refresh_hw()
        except Exception:
            log.debug("hotplug refresh failed", exc_info=True)

        # Camera connect/disconnect → rebuild all camera selectors (global bar
        # + per-tab combos) so the IR entry appears as soon as the IR driver
        # finishes initialising on its background thread.
        # Phase tracker: camera hardware is available but not yet "selected"
        # until the user visits the Modality section (see panel_changed handler).
        # Stimulus is marked when FPGA connects (less ambiguous).
        if "fpga" in key:
            self._phase_tracker.mark(1, "stimulus_configured", ok)

        if "camera" in key:
            # Set header entry for this camera so Connected Devices count is correct.
            # Live-frame handler only sets the *active* camera; this ensures
            # both TR and IR cameras appear when connected.
            if ok:
                if "ir" in key:
                    ir = app_state.ir_cam
                    model = getattr(getattr(ir, 'info', None), 'model', '') if ir else ''
                    self._header.set_connected("ir_camera", True,
                                               f"IR Camera: {model or 'connected'}")
                else:
                    tr = app_state.tr_cam
                    model = getattr(getattr(tr, 'info', None), 'model', '') if tr else ''
                    cam_key = "tr_camera" if app_state.ir_cam is not None else "camera"
                    self._header.set_connected(cam_key, True,
                                               f"TR Camera: {model or 'connected'}")
            self._refresh_all_camera_selectors()
            # Refresh AutoScan TR/IR section visibility
            try:
                self._autoscan_tab.refresh_active_camera()
            except Exception:
                log.debug("AutoScan camera refresh failed", exc_info=True)
            # Refresh all camera-mode-dependent controls (FFC, etc.)
            _cam_refresh_targets = [
                ("acq_settings", lambda: self._acq_settings_section.refresh_camera_mode()),
                ("acquire_tab",  lambda: self._acquire_tab.refresh_camera_mode()),
                ("cal_tab",      lambda: self._cal_tab.refresh_camera_mode()),
                ("live_tab",     lambda: self._live_tab.refresh_camera_mode()),
                ("camera_tab",   lambda: self._camera_tab.refresh_camera_mode()),
            ]
            for name, fn in _cam_refresh_targets:
                try:
                    fn()
                except Exception:
                    log.debug("%s camera refresh failed on hotplug", name, exc_info=True)

        # Wire the emissivity tab's "Capture from camera" button to the
        # live IR camera when an IR camera connects (or disconnect it).
        if "ir" in key or "camera" in key:
            ir = app_state.ir_cam if ok else None
            if ir is not None:
                self._emissivity_tab.set_camera_temp_source(
                    self._read_ir_camera_temp)
            else:
                self._emissivity_tab.set_camera_temp_source(None)

        # Reveal driver-specific UI panels for BNC 745 / AMCAD BILT
        if "fpga" in key:
            self._fpga_tab.set_fpga_driver(app_state.fpga if ok else None)
        elif "bias" in key:
            self._bias_tab.set_bias_driver(app_state.bias if ok else None)

        # Refresh Modality section immediately when any camera connects
        # (regardless of demo mode) so the combo populates without waiting
        # for the 10-second _on_startup_done timer.
        if "camera" in key:
            try:
                self._modality_section.set_hardware_available(ok)
            except Exception:
                log.debug("Modality hotplug refresh failed", exc_info=True)

        # Toggle Tier-1 tab empty-state placeholders.
        # In demo mode all tabs stay fully visible.
        if not app_state.demo_mode:
            self._refresh_tab_availability(key, ok)

        # Re-evaluate required-device readiness after every hotplug event
        self._update_safe_mode()

        # Only show a toast for hotplug events that happen AFTER startup.
        # During startup every device fires device_connected in quick succession
        # and the startup dialog already communicates that status clearly.
        if getattr(self, '_startup_done', False):
            label = key.upper()
            if ok:
                self._toasts.show_success(f"{label} reconnected",
                                          auto_dismiss_ms=4000)
            else:
                self._toasts.show_warning(f"{label} disconnected",
                                          auto_dismiss_ms=0)

    def _refresh_tab_availability(self, key: str = "", ok: bool = True):
        """Toggle Tier-1 tab empty-state placeholders based on device presence.

        Called from _on_device_hotplug and during startup.  If *key* is empty
        every tab is re-evaluated; otherwise only the tab matching *key*.
        """
        _cam_test = lambda: app_state.cam is not None
        _any_cam  = lambda: app_state.cam is not None or app_state.ir_cam is not None
        _map = [
            ("stage",     self._stage_tab,              lambda: app_state.stage is not None),
            ("prober",    self._prober_tab,             lambda: app_state.prober is not None),
            ("camera",    self._camera_tab,             _any_cam),
            ("ir_camera", self._camera_tab,             _any_cam),
            ("fpga",      self._fpga_tab,               lambda: app_state.fpga is not None),
            ("bias",      self._bias_tab,               lambda: app_state.bias is not None),
            ("tec",       self._temp_tab,               lambda: len(app_state.tecs) > 0),
            # New phase-aware sections (camera-dependent)
            ("camera",    self._modality_section,       _cam_test),
            ("camera",    self._acq_settings_section,   _cam_test),
            ("camera",    self._signal_check_section,   _cam_test),
        ]
        if key:
            # Refresh only the matching tab(s)
            for k, tab, test in _map:
                if k in key:
                    if hasattr(tab, 'set_hardware_available'):
                        tab.set_hardware_available(test())
        else:
            # Full refresh (startup)
            for _k, tab, test in _map:
                if hasattr(tab, 'set_hardware_available'):
                    tab.set_hardware_available(test())

    def _show_all_tabs(self) -> None:
        """Show full controls on every Tier-1 tab (for demo mode)."""
        for tab in (self._stage_tab, self._prober_tab, self._camera_tab,
                    self._fpga_tab, self._bias_tab, self._temp_tab,
                    self._modality_section, self._acq_settings_section,
                    self._signal_check_section):
            if hasattr(tab, 'set_hardware_available'):
                tab.set_hardware_available(True)
        # Refresh camera-mode-dependent controls (FFC button visibility)
        try:
            self._live_tab.refresh_camera_mode()
        except Exception:
            pass

    def _update_safe_mode(self) -> None:
        """
        Re-evaluate operation readiness and update the safe-mode banner.

        Uses OP_ACQUIRE as the "most demanding single-shot operation" to
        determine whether the required camera is present.  OP_SCAN
        additionally requires a stage; if the scan is the only blocked
        operation we show a degraded-mode warning instead of full safe mode.

        Called:
          • on every device hotplug / disconnect event
          • once at startup (first showEvent)
        """
        try:
            acq_rdy  = check_readiness(OP_ACQUIRE, app_state)
            scan_rdy = check_readiness(OP_SCAN,    app_state)

            if not acq_rdy.ready:
                # Required device absent → activate safe mode / block start
                self._device_mgr.set_safe_mode(acq_rdy.blocked_reason)
                self._safe_banner.activate(acq_rdy.blocked_reason)
            else:
                self._device_mgr.clear_safe_mode()
                self._safe_banner.deactivate()

                # Scan additionally requires a stage — show a softer warning
                # in the scan tab title if the stage is missing.
                if not scan_rdy.ready:
                    log.debug("Scan blocked (stage absent): %s",
                              scan_rdy.blocked_reason)
        except Exception:
            log.debug("_update_safe_mode failed", exc_info=True)

    def _on_device_mgr_injected(self, uid: str, driver_obj) -> None:
        """Called from DeviceManager after a successful driver injection.

        Runs on the connect-worker thread — uses Qt signals for all GUI work.
        Emits hw_service.device_connected so _on_device_hotplug fires on the
        GUI thread, refreshing camera selectors, safe-mode state, and the
        status header.

        If the app is still in demo mode when a real device connects, this
        automatically exits demo mode before activating the real driver.
        """
        try:
            from hardware.device_registry import DTYPE_CAMERA, DTYPE_FPGA, DTYPE_BIAS
            from hardware.app_state import app_state as _as
            entry = self._device_mgr.get(uid)
            if entry is None:
                return
            dtype = entry.descriptor.device_type

            # Auto-exit demo mode when any real device connects via Device Manager.
            if _as.demo_mode:
                self._handle_real_device_in_demo(uid, driver_obj, dtype)
                return

            if dtype == DTYPE_CAMERA:
                cam_type = getattr(
                    getattr(driver_obj, "info", None), "camera_type", "tr"
                ) or "tr"
                if str(cam_type).lower() == "ir":
                    key = "ir_camera"
                else:
                    # Use "tr_camera" on hybrid systems so the header shows
                    # both TR and IR dots (consistent with _on_device_hotplug).
                    key = "tr_camera" if app_state.ir_cam is not None else "camera"
            elif dtype == DTYPE_FPGA:
                key = "fpga"
            elif dtype == DTYPE_BIAS:
                key = "bias"
            else:
                key = uid
            hw_service.device_connected.emit(key, True)
        except Exception:
            log.debug("_on_device_mgr_injected failed for %s", uid, exc_info=True)

    def _handle_real_device_in_demo(self, uid: str, driver_obj,
                                     dtype) -> None:
        """Schedule an auto-exit from demo mode when a real device connects.

        Runs on the connect-worker thread.  The heavy shutdown/restart work is
        deferred to _deactivate_demo_mode (called on the GUI thread) so that
        the connect-worker thread is not blocked by hw_service.shutdown().

        _inject_into_app has already set app_state.ir_cam = driver_obj and
        set active_camera_type = "ir" (since the simulated TR camera is not
        treated as a real TR camera), so live frames from the real device
        are already visible — this signal just cleans up the demo UI.
        """
        log.info("Device Manager: real device connected while in demo mode — "
                 "scheduling auto-exit of demo mode.")
        self._demo_auto_exited.emit()

    def _finish_auto_demo_exit(self) -> None:
        """GUI-thread: called when a real device connects while in demo mode.

        Delegates to _deactivate_demo_mode with auto_mode=True so that:
        - The demo banner is hidden
        - Simulated drivers are shut down (background thread)
        - Any real drivers already injected are preserved
        - Device Manager dialog is NOT re-opened (it's already showing)
        """
        self._deactivate_demo_mode(auto_mode=True)

    def _purge_stale_demo_devices(self) -> None:
        """Delayed cleanup: clear stale demo device entries from the header.

        Called 500ms after demo exit to catch any TEC/FPGA status signals
        that were already queued in the Qt event loop before shutdown.
        Re-adds only genuinely connected real devices.
        """
        if app_state.demo_mode:
            return  # re-entered demo mode — don't interfere
        self._header.clear_devices()
        # Re-add only genuinely connected real devices (cameras)
        ir = app_state.ir_cam
        tr = app_state.tr_cam
        if ir is not None:
            model = getattr(getattr(ir, 'info', None), 'model', '') or 'connected'
            self._header.set_connected("ir_camera", True, f"IR Camera: {model}")
        if tr is not None:
            model = getattr(getattr(tr, 'info', None), 'model', '') or 'connected'
            cam_key = "tr_camera" if ir is not None else "camera"
            self._header.set_connected(cam_key, True, f"TR Camera: {model}")
        # Re-add real peripheral devices (stage, FPGA, bias, TEC are
        # only re-added when their status handler fires next — clearing
        # stale entries here is sufficient).
        # Clear any stale TEC/stage/FPGA metrics that snuck in after reset().
        self._metrics.reset()
        # Reset tab empty-state placeholders now that demo devices are gone.
        # Tabs for unconnected hardware revert to their empty state.
        self._refresh_tab_availability()

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
        self._menu_bar = mb           # kept for _restyle_menu_bar()
        self._restyle_menu_bar()

        # ── File menu ────────────────────────────────────────────
        # "Quit" on macOS (Cmd+Q, auto-merged into the application menu by Qt);
        # "Exit" on Windows / Linux (Ctrl+Q, plus the standard Alt+F4 still works).
        # Both routes call self.close() so the full closeEvent() shutdown
        # sequence runs in every case.
        file_menu = mb.addMenu("File")

        _is_mac   = sys.platform == "darwin"
        _quit_lbl = f"Quit {APP_NAME}" if _is_mac else "Exit"
        act_quit  = file_menu.addAction(_quit_lbl)
        act_quit.setShortcut(QKeySequence.Quit)          # Cmd+Q / Ctrl+Q
        act_quit.setMenuRole(QAction.QuitRole)           # macOS: move to app menu
        act_quit.triggered.connect(self.close)

        # ── Profile menu ─────────────────────────────────────────
        profile_menu = mb.addMenu("Profile")

        act_save_profile = profile_menu.addAction("Save Current Settings…")
        act_save_profile.setShortcut(QKeySequence("Ctrl+S"))
        act_save_profile.setToolTip("Snapshot all current hardware settings as a named profile")
        act_save_profile.triggered.connect(self._save_profile_dialog)

        act_open_profile = profile_menu.addAction("Open Profile…")
        act_open_profile.setShortcut(QKeySequence("Ctrl+O"))
        act_open_profile.setToolTip("Load a previously saved profile")
        act_open_profile.triggered.connect(self._open_profile_dialog)

        profile_menu.addSeparator()

        act_manage_profiles = profile_menu.addAction("Manage Profiles…")
        act_manage_profiles.triggered.connect(self._navigate_to_profiles)

        # ── Acquisition menu ─────────────────────────────────────
        acq_menu = mb.addMenu("Acquisition")

        act_run = acq_menu.addAction("▶  Run Sequence")
        act_run.setShortcut(QKeySequence("F5"))
        act_run.setToolTip(
            "Capture cold and hot frames then compute ΔR/R (F5)")
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
            lambda: self._nav.navigate_to(self._capture_tab))

        acq_menu.addSeparator()

        act_start_live = acq_menu.addAction("▶  Start Live Stream")
        act_start_live.setShortcut(QKeySequence("Ctrl+F5"))
        act_start_live.setToolTip("Start the live ΔR/R preview (Ctrl+F5)")
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
        # Ctrl+1–9 map to sections in workflow order (phase 1→2→3),
        # Ctrl+0 goes to Settings.  All modes get these; Expert users
        # benefit most from muscle memory.
        view_menu = mb.addMenu("View")

        # Phase 1: Configuration
        act_modality = view_menu.addAction("Modality")
        act_modality.setShortcut(QKeySequence("Ctrl+1"))
        act_modality.triggered.connect(
            lambda: self._nav.navigate_to(self._modality_section))

        act_stimulus = view_menu.addAction("Stimulus")
        act_stimulus.setShortcut(QKeySequence("Ctrl+2"))
        act_stimulus.triggered.connect(
            lambda: self._nav.navigate_to(self._stimulus_tab))

        act_timing = view_menu.addAction("Timing")
        act_timing.setShortcut(QKeySequence("Ctrl+3"))
        act_timing.triggered.connect(
            lambda: self._nav.navigate_to(self._timing_tab))

        view_menu.addSeparator()

        # Phase 2: Image Acquisition
        act_live_view = view_menu.addAction("Live View")
        act_live_view.setShortcut(QKeySequence("Ctrl+4"))
        act_live_view.triggered.connect(
            lambda: self._nav.navigate_to(self._live_tab))

        act_focus_view = view_menu.addAction("Focus && Stage")
        act_focus_view.setShortcut(QKeySequence("Ctrl+5"))
        act_focus_view.triggered.connect(
            lambda: self._nav.navigate_to(self._focus_stage_tab))

        act_signal = view_menu.addAction("Signal Check")
        act_signal.setShortcut(QKeySequence("Ctrl+6"))
        act_signal.triggered.connect(
            lambda: self._nav.navigate_to(self._signal_check_section))

        view_menu.addSeparator()

        # Phase 3: Analysis
        act_capture_view = view_menu.addAction("Capture")
        act_capture_view.setShortcut(QKeySequence("Ctrl+7"))
        act_capture_view.triggered.connect(
            lambda: self._nav.navigate_to(self._capture_tab))

        act_cal_view = view_menu.addAction("Calibration")
        act_cal_view.setShortcut(QKeySequence("Ctrl+8"))
        act_cal_view.triggered.connect(
            lambda: self._nav.navigate_to(self._cal_tab))

        act_sessions_view = view_menu.addAction("Sessions")
        act_sessions_view.setShortcut(QKeySequence("Ctrl+9"))
        act_sessions_view.triggered.connect(
            lambda: self._nav.navigate_to(self._data_tab))

        view_menu.addSeparator()

        # System
        act_settings_view = view_menu.addAction("Settings")
        act_settings_view.setShortcut(QKeySequence("Ctrl+0"))
        act_settings_view.triggered.connect(
            lambda: self._nav.navigate_to(self._settings_tab))

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

        act_license = help_menu.addAction("License…")
        act_license.setToolTip("View or activate your SanjINSIGHT license key")
        act_license.triggered.connect(self._show_license_dialog)

        act_support = help_menu.addAction("Get Support…")
        act_support.setToolTip(
            "Open a pre-filled support email with system info and recent log")
        act_support.triggered.connect(self._open_support_dialog)

        act_bundle = help_menu.addAction("Create Support Bundle…")
        act_bundle.setToolTip(
            "Save a .zip file with logs, config, device inventory, and event "
            "timeline — attach it to a support email for faster diagnosis")
        act_bundle.triggered.connect(self._create_support_bundle)

        # ── Emergency stop shortcut (keyboard) ───────────────────
        estop_sc = QShortcut(QKeySequence("Ctrl+."), self)
        estop_sc.activated.connect(self._trigger_estop)

        # ── Shortcut reference overlay ────────────────────────────
        shortcuts_sc = QShortcut(QKeySequence("Ctrl+?"), self)
        shortcuts_sc.activated.connect(lambda: show_shortcut_overlay(self))

        # ── Command palette (quick navigation) ────────────────────
        palette_sc = QShortcut(QKeySequence("Ctrl+K"), self)
        palette_sc.activated.connect(lambda: self._cmd_palette.show_palette())

        # ── Bottom drawer toggle (Ctrl+`) ─────────────────────────
        drawer_sc = QShortcut(QKeySequence("Ctrl+`"), self)
        drawer_sc.activated.connect(self._toggle_bottom_drawer)

    # ── Keyboard shortcut helpers ──────────────────────────────────

    def _toggle_scan(self):
        """F9 — start scan if idle, abort if running."""
        try:
            if self._scan_tab._btn_runner.is_running:
                self._scan_tab._abort_btn.click()
                return
            # Gate on required devices (camera + stage) before starting
            rdns = check_readiness(OP_SCAN, app_state)
            if not rdns.ready:
                box = QMessageBox(self)
                box.setWindowTitle("Cannot Start Scan")
                box.setIcon(QMessageBox.Critical)
                box.setText(
                    f"Scan is blocked because a required device is missing.\n\n"
                    f"{rdns.blocked_reason}\n\n"
                    f"Connect the device in Device Manager to proceed."
                )
                open_btn  = box.addButton("Open Device Manager", QMessageBox.AcceptRole)
                box.addButton("Close", QMessageBox.RejectRole)
                box.exec_()
                if box.clickedButton() is open_btn:
                    self._open_device_manager()
                return
            self._scan_start_ts = time.time()
            try:
                from events import emit_info, EVT_SCAN_START
                safe_call(emit_info,
                          "acquisition.scan", EVT_SCAN_START,
                          "Scan start requested",
                          label="EVT_SCAN_START", level=logging.DEBUG)
            except ImportError:
                log.debug("_toggle_scan: events module not available — "
                          "EVT_SCAN_START not emitted")
            safe_call(self._scan_tab._run_btn.click,
                      label="_toggle_scan._run_btn.click")
        except Exception:
            log.warning("_toggle_scan: unexpected exception in scan gate",
                        exc_info=True)

    def _toggle_bottom_drawer(self) -> None:
        """Ctrl+` or toggle bar chevron — hide/show the Console+Log panel."""
        if self._bottom_drawer.isVisible():
            self._bottom_drawer.hide()
            self._drawer_toggle_bar.set_open(False)
        else:
            self._bottom_drawer.show()
            self._drawer_toggle_bar.set_open(True)
            self._drawer_toggle_bar.set_active_tab(self._bottom_drawer.current_tab_index())
            # Defer setSizes by one event-loop tick so the splitter has fully
            # processed the show() before we set proportions.
            QTimer.singleShot(0, self._apply_drawer_open_size)

    def _apply_drawer_open_size(self) -> None:
        """Set the drawer to HEIGHT_OPEN after the splitter has settled."""
        total = self._content_splitter.height()
        target = BottomDrawer.HEIGHT_OPEN
        if total >= target + 100:
            self._content_splitter.setSizes([total - target, target])

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
            log.debug("_show_support_dialog: context build failed — "
                      "sending empty context", exc_info=True)
        dlg = SupportDialog(context_json=context_json, parent=self)
        dlg.exec_()

    def _create_support_bundle(self):
        """Open the Support Bundle dialog (Help → Create Support Bundle…)."""
        from ui.dialogs.bundle_dialog import BundleDialog
        dlg = BundleDialog(device_manager=self._device_mgr, parent=self)
        dlg.exec_()

    # ── Update checker ─────────────────────────────────────────────

    # ── License ────────────────────────────────────────────────────────

    def _load_license(self):
        """Load and validate the stored license key; update app_state."""
        import config as _cfg
        from licensing.license_validator import load_license
        from licensing.license_model import LicenseTier
        from hardware.app_state import app_state as _app_state

        info = load_license(_cfg)
        _app_state.license_info = info

        if info.tier == LicenseTier.UNLICENSED:
            log.info("No valid license key — running in demo/unlicensed mode")
        else:
            log.info(
                f"License: {info.tier_display} / {info.customer!r} "
                f"(expires: {info.expires or 'never'})"
            )
            # Warn if expiry is within 30 days
            days = info.days_until_expiry
            if days is not None and 0 < days <= 30:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(
                    3000,   # wait 3 s after startup before showing dialog
                    lambda: self._show_license_expiry_warning(info)
                )

    def _show_license_dialog(self):
        """Open Help → License… dialog."""
        from ui.license_dialog import LicenseDialog
        dlg = LicenseDialog(parent=self)
        dlg.license_changed.connect(self._load_license)
        dlg.license_changed.connect(self._settings_tab.refresh_license_status)
        dlg.exec_()

    def _maybe_show_license_prompt(self):
        """Show the first-run license activation prompt if appropriate.

        Conditions that must ALL be true to show the prompt:
          - Software is not in forced demo mode (--demo flag / app_state.demo_mode).
          - License tier is UNLICENSED (no valid key stored).
          - The user has never previously dismissed this prompt
            (``ui.license_prompted`` pref is False / absent).

        After the dialog closes — regardless of whether the user activated a
        key or chose demo mode — the pref is set to True so the prompt never
        reappears.  Users can always reach the full license dialog via
        Help → License… or Settings → License.
        """
        import config as _cfg
        from hardware.app_state import app_state as _app_state
        from licensing.license_model import LicenseTier

        # Skip if already running in deliberate demo mode
        if _app_state.demo_mode:
            return

        # Skip if a valid license is already active
        if _app_state.license_info.tier != LicenseTier.UNLICENSED:
            return

        # Skip if the user has already seen and dismissed this prompt
        if _cfg.get_pref("ui.license_prompted", False):
            return

        from ui.license_prompt import LicenseActivationPrompt
        dlg = LicenseActivationPrompt(parent=self)
        dlg.license_activated.connect(self._load_license)
        dlg.license_activated.connect(self._settings_tab.refresh_license_status)
        dlg.exec_()   # blocks; accept() on success, reject() on demo choice

        # Mark as shown regardless of outcome so it never fires again
        _cfg.set_pref("ui.license_prompted", True)

    def _show_license_expiry_warning(self, info):
        """Show a one-time amber warning when the license expires within 30 days."""
        from PyQt5.QtWidgets import QMessageBox
        days = info.days_until_expiry
        if days is None or days > 30:
            return
        QMessageBox.warning(
            self,
            "License Expiring Soon",
            f"Your SanjINSIGHT license for {info.customer!r} expires in "
            f"{days} day{'s' if days != 1 else ''}.\n\n"
            f"Contact {SUPPORT_EMAIL} to renew.",
        )

    # ── Update checker ─────────────────────────────────────────────

    def _start_update_checker(self):
        """Start the background update check if enabled in preferences.

        Runs in all modes (including demo) — the user should always know
        when a newer version is available, regardless of hardware state.
        """
        from updater import UpdateChecker, should_check_now, record_check_date
        import config as _cfg
        if not should_check_now(_cfg):
            return
        record_check_date(_cfg)
        include_pre = _cfg.get_pref("updates.include_prerelease", False)
        checker = UpdateChecker(
            on_update=self._on_update_available,
            on_error=lambda e: log.debug(f"Update check: {e}"),
            include_prerelease=include_pre,
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
            f"v{info.version} available", color=PALETTE['warning'])

    def _show_update_dialog(self, info):
        from ui.update_dialog import UpdateDialog
        dlg = UpdateDialog(info, parent=self)
        dlg.exec_()

    def _on_manual_update_check(self):
        """Triggered by Settings tab "Check Now" or Help → Check for Updates."""
        from updater import UpdateChecker
        import config as _cfg
        import threading

        include_pre = _cfg.get_pref("updates.include_prerelease", False)

        def _check():
            checker = UpdateChecker(
                on_update=self._on_update_available,
                on_no_update=lambda: _post_result("✓ You are up to date", PALETTE['accent']),
                on_error=lambda e: _post_result(f"Could not check: {e}", PALETTE['danger']),
                include_prerelease=include_pre,
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
        safe_call(self._acquire_tab.set_active_recipe_name, recipe.label,
                  label="acquire_tab.set_active_recipe_name", level=logging.DEBUG)

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

        # ── Switch to Capture tab and start ───────────────────────
        self._nav.navigate_to(self._capture_tab)
        # Trigger acquisition using recipe frame count and delay
        try:
            self._acquire_tab.start_acquisition(
                n_frames            = recipe.camera.n_frames,
                inter_phase_delay_s = recipe.acquisition.inter_phase_delay_s,
            )
        except Exception as e:
            log.warning("Recipe: could not auto-start acquisition: %s", e)

    # ── Profile save / load ────────────────────────────────────────────

    def _navigate_to_profiles(self):
        """Navigate to the Library tab and switch to the Scan Profiles sub-tab."""
        self._nav.navigate_to(self._library_tab)
        self._library_tab._tabs.setCurrentIndex(1)  # Scan Profiles

    def _save_profile_dialog(self):
        """Show a dialog to name and save the current settings as a profile."""
        from PyQt5.QtWidgets import QInputDialog
        from acquisition.recipe_tab import Recipe

        label, ok = QInputDialog.getText(
            self, "Save Profile",
            "Profile name:",
            text=f"Profile {time.strftime('%Y-%m-%d %H:%M')}")
        if not ok or not label.strip():
            return

        label = label.strip()
        recipe = Recipe.from_current_state(app_state, label=label)

        # Also capture TEC and bias state
        if app_state.tecs:
            try:
                tec = app_state.tecs[0]
                st = tec.get_status()
                recipe.tec.enabled = True
                recipe.tec.setpoint_c = st.target_temp
            except Exception:
                pass
        if app_state.bias is not None:
            try:
                st = app_state.bias.get_status()
                recipe.bias.enabled = True
                recipe.bias.voltage_v = st.actual_voltage
                recipe.bias.current_a = st.actual_current
            except Exception:
                pass

        # Capture FPGA settings
        if app_state.fpga is not None:
            try:
                st = app_state.fpga.get_status()
                recipe.acquisition.modality = getattr(
                    app_state, "active_modality", "thermoreflectance")
            except Exception:
                pass

        self._recipe_store.save(recipe)
        self._header._profile_btn.set_active_recipe(label)
        self._toasts.show_success(f"Profile saved: {label}")
        log.info("Profile saved: %s", label)

    def _open_profile_dialog(self):
        """Show a dialog listing saved profiles for the user to open."""
        from PyQt5.QtWidgets import QInputDialog

        recipes = self._recipe_store.list()
        if not recipes:
            self._toasts.show_warning("No saved profiles found.")
            return

        labels = [r.label for r in recipes]
        chosen, ok = QInputDialog.getItem(
            self, "Open Profile", "Select a profile:", labels, 0, False)
        if not ok:
            return

        recipe = self._recipe_store.load(chosen)
        if recipe:
            self._load_profile(recipe)

    def _load_profile(self, recipe):
        """Apply a saved profile (recipe) to the current hardware state.

        Unlike _apply_recipe, this does NOT start an acquisition — it only
        configures the hardware parameters so the user can review before running.
        """
        from acquisition.recipe_tab import Recipe
        log.info("Loading profile: %s", recipe.label)

        # Camera
        try:
            hw_service.cam_set_exposure(recipe.camera.exposure_us)
            hw_service.cam_set_gain(recipe.camera.gain_db)
            self._camera_tab.set_exposure(recipe.camera.exposure_us)
            self._camera_tab.set_gain(recipe.camera.gain_db)
        except Exception as e:
            log.debug("Profile load — camera: %s", e)

        # Modality
        app_state.active_modality = recipe.acquisition.modality

        # Material profile
        if recipe.profile_name:
            try:
                _find = getattr(self._profile_mgr, 'find_by_name',
                                self._profile_mgr.find)
                profile = _find(recipe.profile_name)
                if profile:
                    self._on_profile_applied(profile)
            except Exception as e:
                log.debug("Profile load — material profile: %s", e)

        # TEC
        if recipe.tec.enabled:
            for idx in range(len(app_state.tecs)):
                try:
                    hw_service.tec_set_target(idx, recipe.tec.setpoint_c)
                except Exception:
                    pass

        # Analysis
        try:
            from acquisition.analysis import AnalysisConfig
            cfg = AnalysisConfig(
                threshold_k        = recipe.analysis.threshold_k,
                fail_hotspot_count = recipe.analysis.fail_hotspot_count,
                fail_peak_k        = recipe.analysis.fail_peak_k,
                fail_area_fraction = recipe.analysis.fail_area_fraction,
                warn_hotspot_count = recipe.analysis.warn_hotspot_count,
                warn_peak_k        = recipe.analysis.warn_peak_k,
                warn_area_fraction = recipe.analysis.warn_area_fraction,
            )
            self._analysis_tab.set_config(cfg)
        except Exception as e:
            log.debug("Profile load — analysis: %s", e)

        # Track active recipe in header button
        self._header._profile_btn.set_active_recipe(recipe.label)
        self._toasts.show_success(
            f"Profile loaded: {recipe.label}")

    def _on_autoscan_scan_requested(self, cfg: dict) -> None:
        """Route an AutoScan scan/preview config to the appropriate engine."""
        if cfg.get("preview") or cfg.get("scan_area") == "single":
            # Brief acquisition (preview pass or single-frame mode)
            n_frames = int(cfg.get("n_frames", 10))
            self._on_acquire_requested(n_frames, 0.0)
        else:
            # Multi-tile grid scan
            self._scan_tab.apply_config(cfg)
            self._scan_tab._run()

    def _on_autoscan_abort_requested(self) -> None:
        """Abort whichever engine AutoScan currently has running."""
        op = self._autoscan_tab._current_op
        if op == "preview":
            self._acquire_tab._abort()
        elif op == "scan":
            if getattr(self._scan_tab, "_runner", None):
                self._scan_tab._runner.abort()

    def _on_autoscan_send_to_analysis(self, result) -> None:
        """Push AutoScan result to Analysis tab, then switch to Manual mode."""
        dt_map  = getattr(result, "delta_t",        None) \
                  or getattr(result, "dt_map",       None)
        drr_map = getattr(result, "delta_r_over_r",  None) \
                  or getattr(result, "drr_map",       None)
        self._analysis_tab.push_result(
            dt_map=dt_map, drr_map=drr_map,
            base_image=None, source_label="AutoScan")
        self._nav.select_by_label("Analysis")

    def _on_profile_applied(self, profile):
        """
        A material profile has been selected and applied.
        Propagate all recommended settings to the relevant subsystems.
        """
        app_state.active_profile = profile
        # Reset the auto-launch guard so _on_ai_status can fire for this profile
        self._advisor_launched_for = None

        # 1. Update header indicator
        self._header.set_profile(profile)

        # 1b. Sync the modality section's profile picker (no re-emit)
        try:
            self._modality_section._profile_picker.set_profile(profile)
        except Exception as _e:
            log.debug("Profile apply — modality picker sync: %s", _e)

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

        # 6. Push stimulus settings to FPGA tab
        try:
            freq = getattr(profile, "stimulus_freq_hz", 0)
            duty = getattr(profile, "stimulus_duty", 0)
            if freq > 0:
                hw_service.fpga_set_frequency(freq)
                self._fpga_tab._freq_spin.setValue(freq)
            if duty > 0:
                hw_service.fpga_set_duty_cycle(duty)
                self._fpga_tab._duty_spin.setValue(duty * 100)
        except Exception as _e:
            log.debug("Profile apply — stimulus settings: %s", _e)

        # 7. Push TEC setpoint
        try:
            if getattr(profile, "tec_enabled", False):
                sp = getattr(profile, "tec_setpoint_c", 25.0)
                hw_service.tec_set_target(0, sp)
        except Exception as _e:
            log.debug("Profile apply — TEC settings: %s", _e)

        # 8. Push bias source settings
        try:
            if getattr(profile, "bias_enabled", False):
                self._bias_tab._level_spin.setValue(
                    getattr(profile, "bias_voltage_v", 0))
                comp_ma = getattr(profile, "bias_compliance_ma", 100)
                self._bias_tab._comp_spin.setValue(comp_ma / 1000.0)
        except Exception as _e:
            log.debug("Profile apply — bias settings: %s", _e)

        # 9. Push calibration temperature sequence + quality settings
        try:
            cal_temps = getattr(profile, "cal_temps", "")
            settle = getattr(profile, "cal_settle_s", 60.0)
            if cal_temps:
                self._cal_tab.set_temp_sequence(cal_temps)
            if settle > 0:
                self._cal_tab._settle.setValue(settle)
            cal_n_avg = getattr(profile, "cal_n_avg", 0)
            if cal_n_avg > 0:
                self._cal_tab._n_avg.setValue(cal_n_avg)
            cal_tol = getattr(profile, "cal_stability_tol_c", 0)
            if cal_tol > 0:
                self._cal_tab._stable_tol.setValue(cal_tol)
            cal_dur = getattr(profile, "cal_stability_dur_s", 0)
            if cal_dur > 0:
                self._cal_tab._stable_dur.setValue(cal_dur)
            cal_r2 = getattr(profile, "cal_min_r2", 0)
            if cal_r2 > 0:
                self._cal_tab._min_r2.setValue(cal_r2)
        except Exception as _e:
            log.debug("Profile apply — calibration settings: %s", _e)

        # 10. Push signal check SNR threshold + ROI strategy
        try:
            snr_thr = getattr(profile, "snr_threshold_db", 20.0)
            self._signal_check_section.set_snr_threshold(snr_thr)
            roi = getattr(profile, "roi_strategy", "")
            if roi:
                self._signal_check_section.set_roi_strategy(roi)
        except Exception as _e:
            log.debug("Profile apply — signal check settings: %s", _e)

        # 11. Push grid scan defaults
        try:
            step = getattr(profile, "grid_step_um", 0)
            if step > 0:
                self._scan_tab.set_grid_from_profile(step,
                    getattr(profile, "grid_overlap_pct", 10.0))
        except Exception as _e:
            log.debug("Profile apply — grid scan settings: %s", _e)

        # 12. Push autofocus defaults
        try:
            af_strat = getattr(profile, "af_strategy", "")
            if af_strat:
                idx = self._af_tab._strategy.findText(
                    af_strat, Qt.MatchFixedString)
                if idx >= 0:
                    self._af_tab._strategy.setCurrentIndex(idx)
            af_metric = getattr(profile, "af_metric", "")
            if af_metric:
                idx = self._af_tab._metric.findText(
                    af_metric, Qt.MatchFixedString)
                if idx >= 0:
                    self._af_tab._metric.setCurrentIndex(idx)
            af_z = getattr(profile, "af_z_range_um", 0)
            if af_z > 0:
                self._af_tab._z_start.setValue(-af_z / 2)
                self._af_tab._z_end.setValue(af_z / 2)
            af_c = getattr(profile, "af_coarse_um", 0)
            if af_c > 0:
                self._af_tab._coarse.setValue(af_c)
            af_f = getattr(profile, "af_fine_um", 0)
            if af_f > 0:
                self._af_tab._fine.setValue(af_f)
            af_n = getattr(profile, "af_n_avg", 0)
            if af_n > 0:
                self._af_tab._n_avg.setValue(af_n)
        except Exception as _e:
            log.debug("Profile apply — autofocus settings: %s", _e)

        # 13. Push FPGA trigger mode
        try:
            trig = getattr(profile, "trigger_mode", "continuous")
            if trig == "single_shot":
                self._fpga_tab._trig_single_rb.setChecked(True)
            else:
                self._fpga_tab._trig_cont_rb.setChecked(True)
        except Exception as _e:
            log.debug("Profile apply — trigger mode: %s", _e)

        # 14. Push BILT pulse settings (only if BILT tab has pulse widgets)
        try:
            if getattr(profile, "bias_enabled", False) and \
               hasattr(self._bias_tab, "_g_bias_sp"):
                self._bias_tab._g_bias_sp.setValue(
                    getattr(profile, "bilt_gate_bias_v", -5.0))
                self._bias_tab._g_pulse_sp.setValue(
                    getattr(profile, "bilt_gate_pulse_v", -2.2))
                self._bias_tab._g_width_sp.setValue(
                    getattr(profile, "bilt_gate_width_us", 110.0))
                self._bias_tab._g_delay_sp.setValue(
                    getattr(profile, "bilt_gate_delay_us", 5.0))
                self._bias_tab._d_bias_sp.setValue(
                    getattr(profile, "bilt_drain_bias_v", 0.0))
                self._bias_tab._d_pulse_sp.setValue(
                    getattr(profile, "bilt_drain_pulse_v", 1.0))
                self._bias_tab._d_width_sp.setValue(
                    getattr(profile, "bilt_drain_width_us", 100.0))
                self._bias_tab._d_delay_sp.setValue(
                    getattr(profile, "bilt_drain_delay_us", 10.0))
        except Exception as _e:
            log.debug("Profile apply — BILT pulse settings: %s", _e)

        # 15. Push analysis thresholds
        try:
            at = getattr(profile, "analysis_threshold_k", 0)
            if at > 0:
                self._analysis_tab.set_thresholds_from_profile(
                    threshold_k=at,
                    fail_hotspot_n=getattr(profile, "analysis_fail_hotspot_n", 0),
                    fail_peak_k=getattr(profile, "analysis_fail_peak_k", 0),
                    warn_hotspot_n=getattr(profile, "analysis_warn_hotspot_n", 0),
                    warn_peak_k=getattr(profile, "analysis_warn_peak_k", 0))
        except Exception as _e:
            log.debug("Profile apply — analysis thresholds: %s", _e)

        # 16. Mark phase tracker checks (for guided walkthrough)
        try:
            tracker = self._phase_tracker
            tracker.mark(1, "camera_selected", True)
            tracker.mark(1, "profile_selected", True)
            tracker.mark(1, "stimulus_configured", True)
            if getattr(profile, "tec_enabled", False):
                tracker.mark(1, "temperature_set", True)
        except Exception as _e:
            log.debug("Profile apply — phase tracker: %s", _e)

        # 17. Log
        self._log_tab.append(
            f"Profile applied: {profile.name}  ·  "
            f"C_T = {profile.ct_value:.3e} K⁻¹  ·  "
            f"exposure = {profile.exposure_us:.0f} µs  ·  "
            f"gain = {profile.gain_db:.1f} dB  ·  "
            f"frames = {profile.n_frames}  ·  "
            f"EMA = {profile.accumulation}")

        # 18. Status bar
        self._status.showMessage(
            f"Profile active: {profile.name}   "
            f"C_T = {profile.ct_value:.3e} K⁻¹",
            8000)

        # 19. Proactive AI Advisor
        self._maybe_launch_advisor(profile)

        # 20. Auto-exposure (runs on background thread, updates UI on complete)
        if getattr(profile, "auto_exposure", False) and app_state.cam is not None:
            target = getattr(profile, "exposure_target_pct", 70.0)
            roi = getattr(profile, "roi_strategy", "center50")

            import threading

            def _run_ae():
                from hardware.cameras.auto_exposure import auto_expose
                result = auto_expose(
                    hw_service, target_pct=target, roi=roi, max_iters=6)
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._on_auto_expose_done(result))

            threading.Thread(target=_run_ae, daemon=True,
                             name="auto-exposure").start()
            self._toasts.show_info("Auto-exposure running…")

    def _on_auto_expose_done(self, result) -> None:
        """Handle auto-exposure completion (called on GUI thread)."""
        try:
            self._camera_tab.set_exposure(result.exposure_us)
            hw_service.cam_set_exposure(result.exposure_us)
        except Exception as _e:
            log.debug("Auto-expose UI update failed: %s", _e)
        if result.converged:
            self._toasts.show_success(result.message)
        else:
            self._toasts.show_warning(result.message)
        self._log_tab.append(result.message)

    def _on_af_progress(self, result):
        self._af_tab.update_progress(result)
        self._log_tab.append(result.message)

    def _on_af_complete(self, result):
        self._af_tab.update_complete(result)
        self._log_tab.append(result.message)
        # Phase tracker: mark focused if autofocus succeeded
        if getattr(result, 'best_z', None) is not None:
            self._phase_tracker.mark(2, "focused")

    def _on_acq_progress(self, p):
        self._acquire_tab.update_progress(p)
        self._log_tab.append(p.message)

    def _on_acq_complete(self, r):
        # Phase tracker: mark captured if result has data
        if getattr(r, 'delta_r_over_r', None) is not None:
            self._phase_tracker.mark(3, "captured")
            self._toasts.show_success(
                "Acquisition complete — data saved to Sessions",
                auto_dismiss_ms=5000)
        # Attach current calibration if available — enables ΔT display
        cal = app_state.active_calibration
        if cal and cal.valid:
            try:
                r.delta_t = cal.apply(r.delta_r_over_r)
            except Exception as _e:
                log.debug("Calibration apply to acquisition result failed: %s", _e)
                r.delta_t = None
        self._acquire_tab.update_result(r)

        # ── Post-acquisition quality scoring ────────────────────────
        scorecard = None
        try:
            from acquisition.quality_scorecard import QualityScoringEngine
            from acquisition.image_metrics import compute_intensity_stats, compute_frame_stability

            cold = getattr(r, "cold_avg", None)
            bit_depth = 12
            if cold is not None:
                cam = app_state.cam
                if cam and cam.info:
                    bit_depth = cam.info.bit_depth
                stats = compute_intensity_stats(cold, bit_depth)
                mean_f, max_f = stats["mean_frac"], stats["max_frac"]
            else:
                mean_f, max_f = 0.5, 0.7

            drr = getattr(r, "delta_r_over_r", None)
            peak_drr = float(abs(drr).max()) if drr is not None else None

            scorecard = QualityScoringEngine.compute(
                snr_db=r.snr_db,
                mean_frac=mean_f,
                max_frac=max_f,
                peak_drr=peak_drr,
                frame_cv=None,
                n_frames=r.n_frames,
                duration_s=r.duration_s,
            )
            r._quality_scorecard = scorecard.to_dict()

            self._acq_summary_overlay.show_summary(
                scorecard, duration_s=r.duration_s, n_frames=r.n_frames)
        except Exception:
            log.debug("Quality scorecard computation failed", exc_info=True)

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

        # ── Backend pipeline: session save, manifest, autosave ─────
        # When the orchestrator is active, it handles post-capture
        # persistence (save, manifest, events) in its own background thread.
        if (self._use_orchestrator
                and self._measurement_orch.phase == MeasurementPhase.CAPTURING):
            self._measurement_orch.on_acquisition_complete(r)
        else:
            # Legacy save path
            self._acq_complete_save_legacy(r, drr_map, dt_map)

        # AI session quality report — silently skips if model not loaded
        if self._ai_service.status == "ready":
            snr = getattr(r, "snr_db", None)
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

    def _acq_complete_save_legacy(self, r, drr_map, dt_map):
        """Legacy session save + manifest + autosave (used when orchestrator is off)."""
        profile = app_state.active_profile
        fpga    = app_state.fpga
        notes   = self._acquire_tab.get_notes()

        _acq_start_ts_snap   = self._acq_start_ts
        _device_mgr_snap     = self._device_mgr
        _rdns_snap           = check_readiness(OP_ACQUIRE, app_state)

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
                        getattr(fpga.get_status(), "frequency_hz", 0.0)
                        if fpga and hasattr(fpga, "get_status") else 0.0),
                    notes          = notes,
                )
                _sc_dict = getattr(r, '_quality_scorecard', None)
                if _sc_dict and session.meta and session.meta.path:
                    session.meta.quality_scorecard = _sc_dict
                    try:
                        import json as _json
                        _meta_path = os.path.join(session.meta.path,
                                                  "session.json")
                        with open(_meta_path, "w") as _fp:
                            _json.dump(session.meta.to_dict(), _fp, indent=2)
                    except Exception:
                        log.debug("Failed to save scorecard to session",
                                  exc_info=True)

                try:
                    ar = self._analysis_tab.get_result()
                    if ar and ar.valid and session.meta.path:
                        session.save_analysis(ar)
                except Exception:
                    log.debug("Failed to save analysis to session",
                              exc_info=True)

                signals.acq_saved.emit(session)
                signals.log_message.emit(
                    f"Session saved: {session.meta.uid}  "
                    f"({session_mgr.root})")

                try:
                    from session.manifest import (RunRecord, ManifestWriter,
                                                  build_device_inventory,
                                                  build_settings_snapshot)
                    from events import timeline as _tl

                    _now = time.time()
                    _cal = app_state.active_calibration
                    _cal_status = ("ok" if (_cal and _cal.valid)
                                   else "missing")
                    _cal_uid    = (getattr(_cal, "uid", "")
                                   if (_cal and _cal.valid) else "")
                    record = RunRecord(
                        operation    = "acquire",
                        started_at   = time.strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            time.localtime(_acq_start_ts_snap)),
                        completed_at = time.strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            time.localtime(_now)),
                        duration_s   = getattr(r, "duration_s", 0.0),
                        outcome      = ("complete" if r.is_complete
                                        else "abort"),
                        session_uid  = session.meta.uid,
                        device_inventory = build_device_inventory(
                            _device_mgr_snap),
                        settings_snapshot = build_settings_snapshot(
                            app_state),
                        calibration_uid    = _cal_uid,
                        calibration_status = _cal_status,
                        degraded_mode      = _rdns_snap.degraded,
                        optional_devices_missing = _rdns_snap.optional_missing,
                        snr_db   = getattr(r, "snr_db", None),
                        n_frames = getattr(r, "n_frames", 0),
                        event_trace = _tl.export_for_run(
                            _acq_start_ts_snap, _now),
                    )
                    ManifestWriter(session.meta.path).append_run(record)
                    try:
                        from events import emit_info, EVT_ACQ_COMPLETE
                        safe_call(emit_info,
                                  "acquisition", EVT_ACQ_COMPLETE,
                                  f"Acquisition complete — snr={record.snr_db} dB  "
                                  f"outcome={record.outcome}",
                                  session_uid=session.meta.uid,
                                  outcome=record.outcome,
                                  snr_db=record.snr_db,
                                  label="EVT_ACQ_COMPLETE", level=logging.DEBUG)
                    except ImportError:
                        pass
                except Exception as _me:
                    log.debug("Manifest write (acquire) failed: %s", _me)

            except Exception as e:
                signals.log_message.emit(f"Session save failed: {e}")
        t = threading.Thread(target=_save, daemon=False, name="session-save")
        t.start()

        # Autosave checkpoint
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

    def _on_log(self, msg: str):
        self._log_tab.append(msg)
        self._status.showMessage(msg, 4000)
        # Surface success confirmations as green toasts.
        # "connected" is intentionally excluded: device-connection messages
        # fire for every device during startup and are already shown in the
        # startup dialog, header status dots, and log tab.  Post-startup
        # hotplug reconnections are toasted by _on_device_hotplug instead.
        if any(k in msg.lower() for k in ("saved", "calibration complete", "loaded")):
            self._toasts.show_success(msg, auto_dismiss_ms=4000)

    def _on_error(self, msg: str):
        self._log_tab.append(f"ERROR: {msg}")
        self._status.showMessage(f"Error: {msg}", 8000)
        self._toasts.show_error(msg)
        self._maybe_auto_diagnose(msg)

    def _maybe_auto_diagnose(self, error_msg: str) -> None:
        """Auto-trigger AI diagnosis when a hardware error occurs.

        The request is queued rather than fired immediately so that:
        - The advisor (higher priority) is never blocked by auto-diagnosis.
        - Rapid-fire errors during profile apply or camera switch don't
          flood the AI with requests.
        - The queue is drained after a short delay, giving transient
          operations time to settle.
        """
        if not hasattr(self, "_diag_queue"):
            self._diag_queue: list[str] = []
        self._diag_queue.append(error_msg)
        # Drain after 3 s — long enough for profile-apply + advisor launch
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, self._drain_auto_diagnose)

    def _drain_auto_diagnose(self) -> None:
        """Process queued auto-diagnosis if the AI is free."""
        queue = getattr(self, "_diag_queue", [])
        if not queue:
            return
        # Take the most recent error only (earlier ones are likely related)
        error_msg = queue[-1]
        queue.clear()

        # Yield to advisor — never interrupt it
        if getattr(self, "_advisor_active", False):
            return
        if self._ai_service.status != "ready":
            return
        if not self._ai_service.can("diagnose"):
            return
        # Throttle: max once per 30 seconds
        import time
        now = time.monotonic()
        if now - getattr(self, "_last_auto_diagnose", 0.0) < 30.0:
            return
        self._last_auto_diagnose = now

        # Route auto-diagnosis to the log panel only — no AI dock pop-up.
        # Uses infer() directly (not ask()) to avoid polluting chat history.
        self._log_tab.append(f"AI diagnosing error: {error_msg}")
        self._diag_active = True  # separate flag from advisor

        # Disconnect any stale diagnosis handlers from a previous run
        self._disconnect_diag_handlers()

        # Store handlers on self so they can be disconnected on preemption
        def _on_diag_token(tok: str) -> None:
            pass  # accumulate silently — full text arrives in complete

        def _on_diag_done(text: str, _elapsed: float) -> None:
            self._diag_active = False
            self._disconnect_diag_handlers()
            self._ai_service._set_status("ready")
            summary = text.strip()[:300]
            if summary:
                self._log_tab.append(f"AI diagnosis: {summary}")

        def _on_diag_err(msg: str) -> None:
            self._diag_active = False
            self._disconnect_diag_handlers()
            self._ai_service._set_status("ready")

        self._diag_token_handler = _on_diag_token
        self._diag_done_handler = _on_diag_done
        self._diag_err_handler = _on_diag_err

        self._ai_service.response_token.connect(_on_diag_token)
        self._ai_service.response_complete.connect(_on_diag_done)
        self._ai_service.ai_error.connect(_on_diag_err)

        # Build a standalone diagnosis prompt (no history injection)
        from ai import prompt_templates as tmpl
        sp = self._ai_service._active_system_prompt()
        ctx_json = self._ai_service._ctx.build()
        messages = tmpl.diagnose(ctx_json, sp, "")
        # Replace the user message with the specific error
        messages[-1] = {"role": "user", "content":
            f"A hardware error just occurred: \"{error_msg}\". "
            f"Briefly: likely cause and fix?"}

        # Fire inference directly — bypasses _run() so no history pollution
        if (self._ai_service._active_backend == "remote"
                and self._ai_service._remote_runner is not None):
            self._ai_service._remote_runner.infer(
                messages, max_tokens=256, temperature=0.3)
        else:
            self._ai_service._runner.infer(
                messages, max_tokens=256, temperature=0.3)
        self._ai_service._set_status("thinking")

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

    # ── Demo mode activation ───────────────────────────────────────────

    def _activate_demo_mode(self):
        """Switch to demo mode from any in-app trigger (Device Manager, etc.).

        Safe to call at any point after MainWindow is constructed.  Updates the
        UI immediately, then shuts down any partially-initialised real hardware
        and starts all simulated drivers on a background thread so the GUI stays
        responsive during the handover (hw_service.shutdown() joins threads, which
        can block for up to 4 s each on Windows if hardware is still initialising).
        """
        import threading as _threading
        from hardware.app_state import app_state as _app_state
        if _app_state.demo_mode:
            return  # already in demo mode — nothing to do

        # Update state and UI immediately so the user sees the mode change
        # even before the hardware handover thread finishes.
        _app_state.demo_mode = True
        _app_state.tecs      = []
        self._header.set_demo_mode(True)
        # Ensure all Tier-1 tabs show full controls in demo mode
        self._show_all_tabs()
        self._status.showMessage(
            f"SanjINSIGHT {version_string()}  \u2014  DEMO MODE  "
            f"(simulated hardware)", 0)
        signals.log_message.emit(
            "Demo mode activated \u2014 switching hardware to simulated drivers…")

        # Shutdown real hardware and start demo drivers off the GUI thread.
        # hw_service.shutdown() calls t.join(timeout=4 s) for every thread, so
        # running it on the GUI thread makes the window go "Not Responding" on
        # Windows for the full join duration.
        def _switch_to_demo():
            hw_service.shutdown()
            hw_service.start_demo()

        _threading.Thread(
            target=_switch_to_demo, daemon=True, name="hw.demo_switch"
        ).start()

    def _on_admin_login(self) -> None:
        """Open the LoginScreen so an admin can authenticate in no-login mode."""
        if self._auth is None:
            return
        from ui.auth.login_screen import LoginScreen
        from PyQt5.QtCore import QEventLoop as _QEL

        ls = LoginScreen(self._auth, parent=self)
        ls.setWindowTitle("SanjINSIGHT — Log In")
        ls.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        ls.resize(460, 520)

        _el = _QEL()
        ls.login_success.connect(
            lambda sess: (
                setattr(ls, "_sess", sess),
                _el.quit(),
            ) and None
        )
        ls.show()
        _el.exec_()
        session = getattr(ls, "_sess", None)
        ls.hide()

        if session is not None:
            self._auth_session = session
            self._header.update_from_session(session)
            self._settings_tab.set_auth_session(session)
            log.info("Admin login: %s", session.user.username)

    def _on_admin_logout(self) -> None:
        """Clear the active auth session and revert the header to unauthenticated state."""
        if self._auth_session is not None and self._auth is not None:
            try:
                self._auth.logout()
            except Exception:
                pass
        self._auth_session = None
        self._header.update_from_session(None)
        # Re-show the Log-in button so the admin can re-authenticate
        if self._auth is not None:
            try:
                self._header.set_auth_users_exist(self._auth._store.has_users())
            except Exception:
                pass
        self._settings_tab.set_auth_session(None)
        log.info("Admin logged out")

    def _deactivate_demo_mode(self, *, auto_mode: bool = False):
        """Exit demo mode and (optionally) open the Device Manager.

        Called when the user clicks the '✕ Exit' button in the demo banner, or
        automatically via _finish_auto_demo_exit when a real device connects
        while demo mode is still active.

        Shuts down simulated drivers on a background thread while preserving
        any real drivers that were already injected via the Device Manager.

        Args:
            auto_mode: When True the Device Manager dialog is NOT shown after
                       the switch (it's already open) and the status message
                       reflects the automated exit.
        """
        import threading as _threading
        from hardware.app_state import app_state as _app_state
        if not _app_state.demo_mode:
            return  # not in demo mode — nothing to do

        _app_state.demo_mode = False
        self._header.set_demo_mode(False)
        self._header.clear_devices()          # flush simulated device entries
        self._metrics.reset()                 # clear stale TEC/stage/FPGA metrics

        # Stale TEC/FPGA status signals may already be queued in the Qt event
        # loop from demo polling threads.  Schedule clears after short delays
        # to catch any that re-add stale demo devices (TEC poll = 0.5s).
        QTimer.singleShot(500, self._purge_stale_demo_devices)
        QTimer.singleShot(1500, self._purge_stale_demo_devices)

        if auto_mode:
            self._status.showMessage(
                "Real hardware connected — exited demo mode automatically.", 5000)
        else:
            self._status.showMessage(
                f"SanjINSIGHT {version_string()}  —  exiting demo mode…", 4000)
            signals.log_message.emit(
                "Exiting demo mode — shutting down simulated drivers…")

        def _switch_to_real():
            from hardware.app_state import app_state as _as
            # Preserve any real (non-simulated) drivers already connected via
            # Device Manager before shutdown clears app_state slots.
            _real_ir  = None
            _real_cam = None
            try:
                from hardware.cameras.simulated import SimulatedDriver
                from hardware.device_registry import (DTYPE_CAMERA, DTYPE_FPGA,
                                                      DTYPE_STAGE, DTYPE_BIAS)
                if _as.ir_cam is not None and not isinstance(_as.ir_cam, SimulatedDriver):
                    _real_ir = _as.ir_cam
                # Use tr_cam (raw _cam slot) — not the .cam property which
                # returns ir_cam when active_camera_type=="ir", causing the
                # same driver to appear in both slots.
                if _as.tr_cam is not None and not isinstance(_as.tr_cam, SimulatedDriver):
                    _real_cam = _as.tr_cam
            except Exception:
                pass

            hw_service.shutdown()          # stop simulated drivers

            # Clear ALL stale demo device references.  shutdown() closes
            # drivers but does NOT null out app_state slots — the closed
            # simulated objects linger, making guards like
            # "app_state.stage is None" ineffective.
            _as.cam    = None
            _as.ir_cam = None
            _as.pipeline = None
            _as.active_camera_type = "tr"  # reset to default
            _as.stage  = None
            _as.fpga   = None
            _as.bias   = None
            _as.prober = None
            _as.tecs = []  # clear simulated TECs

            # Restore real drivers saved above.
            if _real_ir is not None:
                _as.ir_cam = _real_ir
                if _real_cam is None:
                    _as.active_camera_type = "ir"
            if _real_cam is not None:
                _as.cam = _real_cam

            # Re-inject any devices that connected via auto-reconnect
            # while hw_service.shutdown() was running.  The shutdown may
            # have closed them and the slot-clear above wiped them from
            # app_state, so we need to re-instantiate from the Device
            # Manager's still-CONNECTED entries.
            try:
                from hardware.device_manager import DeviceState
                for uid, entry in self._device_mgr._entries.items():
                    if entry.state != DeviceState.CONNECTED:
                        continue
                    if entry.driver_obj is None:
                        continue
                    drv = entry.driver_obj
                    dtype = entry.descriptor.device_type
                    if dtype == DTYPE_CAMERA:
                        ct = getattr(getattr(drv, 'info', None),
                                     'camera_type', 'tr') or 'tr'
                        if str(ct).lower() == 'ir':
                            if _as.ir_cam is None or isinstance(
                                    _as.ir_cam, SimulatedDriver):
                                # Re-open if shutdown closed it
                                if not getattr(drv, '_open', True):
                                    try: drv.open(); drv.start()
                                    except Exception: continue
                                _as.ir_cam = drv
                                _real_ir = drv
                        else:
                            if _as.tr_cam is None or isinstance(
                                    _as.tr_cam, SimulatedDriver):
                                if not getattr(drv, '_open', True):
                                    try: drv.open(); drv.start()
                                    except Exception: continue
                                _as.cam = drv
                                _real_cam = drv
                    elif dtype == DTYPE_FPGA and _as.fpga is None:
                        _as.fpga = drv
                    elif dtype == DTYPE_STAGE and _as.stage is None:
                        _as.stage = drv
                    elif dtype == DTYPE_BIAS and _as.bias is None:
                        _as.bias = drv
                log.info("_switch_to_real: re-injected DM-connected devices "
                         "(ir=%s, tr=%s)", _real_ir is not None,
                         _real_cam is not None)
            except Exception:
                log.debug("_switch_to_real: DM re-inject failed",
                          exc_info=True)

            # Set active camera type based on what's available.
            # Respect saved user preference when both cameras exist.
            if _real_cam is not None and _real_ir is not None:
                _saved = config.get_pref("autoscan.selected_camera_type", "tr")
                _as.active_camera_type = _saved if _saved in ("tr", "ir") else "tr"
            elif _real_cam is not None:
                _as.active_camera_type = "tr"
            elif _real_ir is not None:
                _as.active_camera_type = "ir"

            # Create a new acquisition pipeline for the real camera so
            # COLD/HOT capture uses the actual device, not the stale
            # demo pipeline.
            _active = _real_cam or _real_ir
            if _active is not None:
                try:
                    pipeline = AcquisitionPipeline(
                        _active,
                        fpga=_as.fpga,
                        bias=_as.bias)
                    pipeline.on_progress = lambda p: hw_service.acq_progress.emit(p)
                    pipeline.on_complete = lambda r: hw_service.acq_complete.emit(r)
                    pipeline.on_error    = lambda e: hw_service.error.emit(e)

                    # Register auto-focus pre-capture hook if enabled.
                    # Resolve cam/stage from app_state at execution time,
                    # not at closure creation time, so hardware swaps are
                    # picked up correctly.
                    if config.get_pref("autofocus.before_capture", False):
                        def _af_hook():
                            _cam = app_state.cam
                            _stage = app_state.stage
                            if _stage is None or _cam is None:
                                return
                            try:
                                from hardware.autofocus import create_autofocus
                                af_cfg = {
                                    "driver":   config.get_pref("autofocus.strategy", "sweep"),
                                    "strategy": config.get_pref("autofocus.strategy", "sweep"),
                                    "metric":   config.get_pref("autofocus.metric", "laplacian"),
                                    "z_start":  config.get_pref("autofocus.z_start", -500.0),
                                    "z_end":    config.get_pref("autofocus.z_end", 500.0),
                                    "coarse_step": config.get_pref("autofocus.coarse_step", 50.0),
                                    "fine_step":   config.get_pref("autofocus.fine_step", 5.0),
                                    "n_avg":    config.get_pref("autofocus.n_avg", 2),
                                    "settle_ms": config.get_pref("autofocus.settle_ms", 50),
                                    "move_to_best": True,
                                }
                                af = create_autofocus(af_cfg, _cam, _stage)
                                af.run()
                                log.info("Pre-capture autofocus complete")
                            except Exception as exc:
                                log.warning("Pre-capture autofocus failed: %s", exc)
                        pipeline.pre_capture_hooks.append(_af_hook)

                    _as.pipeline = pipeline
                except Exception:
                    log.debug("Failed to create pipeline for real camera",
                              exc_info=True)

            hw_service.start_idle()        # restart grab loop with real camera

            # Notify the main window so camera selectors, header, and
            # tab availability are refreshed for the real hardware state.
            if _real_ir:
                hw_service.device_connected.emit("ir_camera", True)
            if _real_cam:
                hw_service.device_connected.emit("camera", True)
            if not (_real_ir or _real_cam) and not auto_mode:
                # No real device yet → open Device Manager so user can scan.
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._device_mgr_dlg.show)

            # Schedule a final full refresh after shutdown has cleared all
            # simulated device references.  This catches any tab/header state
            # that the timed purges at 500/1500ms missed because shutdown
            # was still in progress when they ran.
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self._purge_stale_demo_devices)

        _threading.Thread(
            target=_switch_to_real, daemon=True, name="hw.exit_demo"
        ).start()

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

    # Metrics issue code → diagnostic rule ID mapping for auto-fix
    _METRICS_TO_RULE: dict[str, str] = {
        "stage_not_homed":      "R3_stage_homed",
        "camera_saturated":     "C1_saturation",
        "camera_underexposed":  "C2_underexposure",
        "fpga_not_running":     "L1_fpga_running",
        "fpga_not_locked":      "L2_fpga_locked",
    }

    def _on_readiness_fix_requested(self, issue_code: str) -> None:
        """Handle a 'Fix it' click from the ReadinessWidget.

        Maps the metrics issue code to a diagnostic rule ID and delegates
        to the auto-fix system.  Falls back to sidebar navigation if no
        auto-fix is available.
        """
        from ui.widgets.readiness_widget import _nav_target_for

        rule_id = self._METRICS_TO_RULE.get(issue_code)
        if rule_id:
            self._on_autofix_requested(rule_id)
        else:
            # No auto-fix mapping — fall back to navigation
            nav = _nav_target_for(issue_code)
            if nav:
                self._nav.select_by_label(nav)

    def _on_autofix_requested(self, rule_id: str) -> None:
        """Handle a fix button click from the AI panel evidence section."""
        from ai.auto_fix import get_fix, can_auto_fix, apply_fix

        fix = get_fix(rule_id)
        if fix is None:
            return

        if fix.auto:
            # Run the automatic fix
            self._toasts.show_info(f"Fixing: {fix.description}…")

            def _on_complete(success, msg):
                # Called from background thread — use QTimer to get to GUI thread
                from PyQt5.QtCore import QTimer
                if success:
                    QTimer.singleShot(0, lambda: self._toasts.show_success(
                        f"Fixed: {msg}"))
                else:
                    QTimer.singleShot(0, lambda: self._toasts.show_warning(
                        f"Fix failed: {msg}"))

            apply_fix(rule_id, hw_service, app_state, on_complete=_on_complete)
        elif fix.navigate_to:
            # Manual fix — navigate to the relevant panel
            if fix.navigate_to == "Device Manager":
                self._open_device_manager()
            else:
                self._nav.select_by_label(fix.navigate_to)

    def _refresh_evidence_panel(self) -> None:
        """Push latest diagnostic results to the AI panel evidence section."""
        try:
            results = self._diagnostic_engine.evaluate()
            self._ai_panel.refresh_evidence(results)

            grade = self._compute_grade(results)
            self._header.set_readiness_grade(grade, results)

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
            log.debug("_refresh_evidence_panel: diagnostic evaluation failed",
                      exc_info=True)

    def _on_acquire_requested(self, n_frames: int, delay: float) -> None:
        """
        Readiness gate: intercept acquisition start, warn or block on C/D grades.

        When ``acquisition.use_orchestrator`` is enabled (default), delegates
        to the ``MeasurementOrchestrator`` state machine.  Otherwise falls
        back to the legacy inline implementation.
        """
        if self._use_orchestrator:
            return self._on_acquire_via_orchestrator(n_frames, delay)
        return self._on_acquire_legacy(n_frames, delay)

    # ── Orchestrator path ──────────────────────────────────────────

    def _on_acquire_via_orchestrator(self, n_frames: int, delay: float) -> None:
        """Pre-capture chain via MeasurementOrchestrator."""
        # Snapshot for AI session report / legacy code that reads these
        self._acq_start_ts = time.time()

        # Emit ACQ_START to the event bus timeline
        try:
            from events import emit_info, EVT_ACQ_START
            safe_call(emit_info,
                      "acquisition", EVT_ACQ_START,
                      f"Acquisition start — {n_frames} frames/phase",
                      n_frames=n_frames,
                      label="EVT_ACQ_START", level=logging.DEBUG)
        except ImportError:
            pass

        self._measurement_orch.start_measurement(
            n_frames, delay, workflow=self._active_workflow)

        # If the orchestrator reached CAPTURING synchronously, start pipeline
        if self._measurement_orch.phase == MeasurementPhase.CAPTURING:
            # Sync snapshots for legacy consumers
            ctx = self._measurement_orch.context
            self._acq_start_grade = ctx.grade
            self._acq_start_issues = ctx.issues
            self._acquire_tab.start_acquisition(n_frames, delay)

    def _on_measurement_phase(self, phase, label: str) -> None:
        """React to orchestrator phase transitions."""
        log.debug("Measurement phase: %s — %s", phase.value, label)

    def _on_measurement_decision(self, decision_type: str, message: str,
                                  context: object) -> None:
        """Show a UI dialog for the orchestrator's user_decision_needed signal."""
        ctx = context if isinstance(context, dict) else {}

        if decision_type == "safe_mode_block":
            # Safe-mode blocks are non-overridable — orchestrator already
            # transitioned to ABORTED.  Show informational dialog.
            box = QMessageBox(self)
            box.setWindowTitle("Cannot Start Acquisition")
            box.setIcon(QMessageBox.Critical)
            box.setText(message)
            open_btn = box.addButton("Open Device Manager",
                                     QMessageBox.AcceptRole)
            box.addButton("Close", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is open_btn:
                self._open_device_manager()
            return

        if decision_type == "preflight_issues":
            # Show the preflight dialog with auto-fix buttons
            preflight = ctx.get("preflight")
            if preflight is not None:
                try:
                    from ui.widgets.preflight_dialog import PreflightDialog
                    from acquisition.preflight_remediation import (
                        PreflightRemediator)
                    remediator = PreflightRemediator(app_state)
                    remediations = remediator.get_remediations(
                        preflight.checks)
                    dlg = PreflightDialog(preflight,
                                          remediations=remediations,
                                          parent=self)
                    if dlg.exec_() == QDialog.Accepted:
                        self._measurement_orch.provide_decision("proceed")
                        if self._measurement_orch.phase == MeasurementPhase.CAPTURING:
                            n = self._measurement_orch.context.n_frames
                            d = self._measurement_orch.context.delay
                            self._acq_start_grade = self._measurement_orch.context.grade
                            self._acq_start_issues = self._measurement_orch.context.issues
                            self._acquire_tab.start_acquisition(n, d)
                    else:
                        self._measurement_orch.provide_decision("abort")
                    return
                except Exception:
                    log.debug("PreflightDialog failed", exc_info=True)
            # Fall through to generic grade dialog
            decision_type = "grade_warning"

        if decision_type in ("grade_warning", "grade_critical"):
            grade = ctx.get("grade", "C")
            is_critical = decision_type == "grade_critical"
            msg = QMessageBox(self)
            msg.setWindowTitle(
                f"Readiness {'Failure' if is_critical else 'Warning'}"
                f" — Grade {grade}")
            msg.setIcon(
                QMessageBox.Critical if is_critical else QMessageBox.Warning)
            msg.setText(message)
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            msg.button(QMessageBox.Ok).setText(
                "Start Despite Failures" if is_critical
                else "Start Acquisition Anyway")
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec_() == QMessageBox.Ok:
                self._measurement_orch.provide_decision("proceed")
                if self._measurement_orch.phase == MeasurementPhase.CAPTURING:
                    n = self._measurement_orch.context.n_frames
                    d = self._measurement_orch.context.delay
                    self._acq_start_grade = self._measurement_orch.context.grade
                    self._acq_start_issues = self._measurement_orch.context.issues
                    self._acquire_tab.start_acquisition(n, d)
            else:
                self._measurement_orch.provide_decision("abort")

    def _on_measurement_complete(self, result) -> None:
        """Handle orchestrator measurement_complete signal.

        The orchestrator fires this after post-processing and saving
        complete (in the background thread).  Update UI accordingly.
        """
        if result.phase == MeasurementPhase.ABORTED:
            log.info("Measurement aborted")
        elif result.phase == MeasurementPhase.ERROR:
            log.warning("Measurement ended with error")
        elif result.phase == MeasurementPhase.COMPLETE:
            log.info("Measurement lifecycle complete (orchestrator) — "
                     "duration=%.1fs", result.duration_s)

    # ── Legacy path (fallback) ─────────────────────────────────────

    def _on_acquire_legacy(self, n_frames: int, delay: float) -> None:
        """Legacy inline readiness gate (used when orchestrator is disabled)."""
        # ── Required-device gate (safe mode) ─────────────────────────────
        if self._device_mgr.safe_mode:
            rdns = check_readiness(OP_ACQUIRE, app_state)
            msg  = rdns.blocked_reason or self._device_mgr.safe_mode_reason
            box  = QMessageBox(self)
            box.setWindowTitle("Cannot Start Acquisition")
            box.setIcon(QMessageBox.Critical)
            box.setText(
                f"Acquisition is blocked because a required device is missing.\n\n"
                f"{msg}\n\n"
                f"Connect the device in Device Manager to proceed."
            )
            open_btn  = box.addButton("Open Device Manager", QMessageBox.AcceptRole)
            box.addButton("Close", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is open_btn:
                self._open_device_manager()
            return

        try:
            results = self._diagnostic_engine.evaluate()
            grade   = self._compute_grade(results)
        except Exception:
            results = []
            grade   = "A"

        self._acq_start_ts     = time.time()
        self._acq_start_grade  = grade
        self._acq_start_issues = [r for r in results if r.severity in ("fail", "warn")]

        preflight = None
        if config.get_pref("acquisition.preflight_enabled", True):
            try:
                from acquisition.preflight import PreflightValidator
                metrics_snap = (self._metrics.latest_snapshot()
                                if hasattr(self._metrics, 'latest_snapshot')
                                else {})
                validator = PreflightValidator(app_state, metrics_snap)
                preflight = validator.run(operation="acquire")
                self._acq_start_preflight = preflight
            except Exception:
                log.debug("Preflight validation failed — proceeding",
                          exc_info=True)

        try:
            from events import emit_info, EVT_ACQ_START
            safe_call(emit_info,
                      "acquisition", EVT_ACQ_START,
                      f"Acquisition start — {n_frames} frames/phase",
                      n_frames=n_frames, grade=grade,
                      label="EVT_ACQ_START", level=logging.DEBUG)
        except ImportError:
            pass

        preflight_ok = (preflight is None or preflight.all_clear)
        if grade in ("A", "B") and preflight_ok:
            self._acquire_tab.start_acquisition(n_frames, delay)
            return

        if preflight is not None and not preflight.all_clear:
            try:
                from ui.widgets.preflight_dialog import PreflightDialog
                from acquisition.preflight_remediation import PreflightRemediator
                remediator = PreflightRemediator(app_state)
                remediations = remediator.get_remediations(preflight.checks)
                dlg = PreflightDialog(preflight, remediations=remediations,
                                      parent=self)
                if dlg.exec_() != QDialog.Accepted:
                    return
                self._acquire_tab.start_acquisition(n_frames, delay)
                return
            except Exception:
                log.debug("PreflightDialog failed — falling back to "
                          "grade-based gate", exc_info=True)

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
            msg.button(QMessageBox.Ok).setText("Start Acquisition Anyway")
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
            msg.button(QMessageBox.Ok).setText("Start Despite Failures")
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec_() == QMessageBox.Ok:
                self._acquire_tab.start_acquisition(n_frames, delay)

    # ── Optimize & Acquire ──────────────────────────────────────────

    def _on_workflow_selected(self, workflow) -> None:
        """Handle workflow selection from the acquire tab."""
        self._active_workflow = workflow
        if workflow:
            log.info("Workflow selected: %s", workflow.display_name)
        else:
            log.info("Workflow selection cleared (default)")

    def _on_optimize_and_acquire(self, n_frames: int, delay: float) -> None:
        """Launch the multi-step preparation orchestrator, then acquire."""
        from hardware.readiness_orchestrator import ReadinessOrchestrator, Step
        from ui.widgets.orchestrator_dialog import OrchestratorDialog

        orch = ReadinessOrchestrator(
            self._hw_service, self._metrics, parent=self)

        # Choose steps based on connected hardware
        steps = [Step.AUTO_EXPOSE, Step.AUTO_GAIN]
        tecs = getattr(app_state, 'tecs', [])
        if tecs:
            steps.append(Step.TEC_PRECONDITION)
        steps.append(Step.PREFLIGHT)
        orch.configure(steps=steps, operation="acquire")

        dlg = OrchestratorDialog(orch, parent=self)
        orch.start()

        if dlg.exec_() == QDialog.Accepted:
            self._acquire_tab.start_acquisition(n_frames, delay)

    def _on_suggestion_action(self, code: str) -> None:
        """Handle an action request from the optimisation suggestions strip."""
        if code == "auto_expose":
            self._camera_tab._run_auto_expose()
        elif code == "auto_gain":
            self._camera_tab._run_auto_gain()
        elif code == "autofocus":
            # Navigate to autofocus tab
            try:
                self._nav.select_by_label("Camera")
            except Exception:
                pass
        elif code == "tec_wait":
            try:
                self._nav.select_by_label("Temperature")
            except Exception:
                pass

    def _on_history_exported(self, path: str) -> None:
        """Show a transient status-bar message when a conversation is exported."""
        self._status.showMessage(f"Conversation saved → {path}", 6000)

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
        # Also update cloud / Ollama status labels when the remote backend is active
        if self._ai_service._active_backend == "remote":
            provider = getattr(self._ai_service, "_runner", None)
            # Determine which remote backend is active
            remote = self._ai_service._remote_runner
            remote_provider = getattr(remote, "_provider", "") if remote else ""
            if remote_provider == "ollama":
                self._settings_tab.set_ollama_status(status)
            else:
                self._settings_tab.set_cloud_ai_status(status)
        if status == "ready":
            self._status.showMessage("AI Assistant ready", 3000)
            # If a profile is already active and advisor hasn't run for it,
            # auto-launch now (covers "model loaded after profile selected").
            # Guard prevents infinite loop: advisor completes → status="ready"
            # → _on_ai_status → must NOT re-launch.
            active_prof = getattr(app_state, "active_profile", None)
            if (active_prof is not None
                    and not getattr(self, "_advisor_active", False)
                    and getattr(self, "_advisor_launched_for", None)
                    is not active_prof):
                self._advisor_launched_for = active_prof
                self._maybe_launch_advisor(active_prof)
        elif status == "error":
            self._status.showMessage("AI Assistant error — see AI panel", 5000)

    def _ai_panel_suppressed(self) -> bool:
        """True when AI output should NOT go to the chat panel."""
        return (getattr(self, "_advisor_active", False)
                or getattr(self, "_diag_active", False))

    def _disconnect_diag_handlers(self) -> None:
        """Safely disconnect auto-diagnosis signal handlers."""
        for attr, signal in (
            ("_diag_token_handler", self._ai_service.response_token),
            ("_diag_done_handler",  self._ai_service.response_complete),
            ("_diag_err_handler",   self._ai_service.ai_error),
        ):
            handler = getattr(self, attr, None)
            if handler is not None:
                try:
                    signal.disconnect(handler)
                except TypeError:
                    pass
                setattr(self, attr, None)

    def _on_ai_token(self, token: str) -> None:
        """Guard: suppress chat panel tokens while advisor/diagnosis active."""
        if not self._ai_panel_suppressed():
            self._ai_panel.on_token(token)

    def _on_ai_response_complete(self, text: str, elapsed: float) -> None:
        """Guard: suppress chat panel response while advisor/diagnosis active."""
        if not self._ai_panel_suppressed():
            self._ai_panel.on_response_complete(text, elapsed)

    def _on_ai_error(self, msg: str) -> None:
        """Guard: suppress chat panel error while advisor/diagnosis active."""
        if not self._ai_panel_suppressed():
            self._ai_panel.on_error(msg)

    # ── Proactive AI Advisor ─────────────────────────────────────────────

    def _maybe_launch_advisor(self, profile) -> None:
        """Launch the AI advisor after profile selection.

        Works for any camera type (TR, IR, future plugins) by passing
        the active modality to the prompt builder so the AI adapts its
        physics reasoning to the measurement technique.
        """
        _prof_name = getattr(profile, "name", "?")

        # ── Pre-flight guards ──
        if getattr(self, "_advisor_active", False):
            # Previous advisor still running — cancel it so the new
            # profile's advisor can take over
            log.info("Advisor: cancelling previous advisor for new profile")
            self._on_advisor_cancelled()

        ai_status = self._ai_service.status
        if ai_status == "thinking":
            # AI is busy (auto-diagnosis, chat, etc.) — the advisor
            # takes priority: cancel and retry after the runner is free
            log.info("Advisor: pre-empting AI (was %r) for profile advisor",
                     ai_status)
            # Clean up any running auto-diagnosis so _diag_active doesn't stick
            if getattr(self, "_diag_active", False):
                self._diag_active = False
                self._disconnect_diag_handlers()
            self._ai_service.cancel()
            self._ai_service._set_status("ready")
            # Defer launch to let the cancelled worker thread finish
            self._pending_advisor_profile = profile
            self._advisor_retry_count = 0
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(200, self._retry_launch_advisor)
            return
        elif ai_status not in ("ready",):
            # AI is off, loading, or in error — can't launch now.
            # When AI becomes ready, _on_ai_status will auto-launch.
            if ai_status == "off":
                log.debug("Advisor deferred: AI not loaded yet — will "
                          "auto-launch when AI becomes ready")
            return

        if not self._ai_service.can("proactive_advisor"):
            return

        try:
            self._launch_advisor(profile)
        except Exception as exc:
            log.error("AI Advisor failed to launch: %s", exc, exc_info=True)
            self._log_tab.append(f"AI Advisor error: {exc}", level="error")
            self._status.showMessage("AI Advisor error — see log", 5000)
            # Ensure flag is reset so next attempt isn't blocked
            self._advisor_active = False

    def _retry_launch_advisor(self) -> None:
        """Retry advisor launch after a cancelled inference has drained."""
        profile = getattr(self, "_pending_advisor_profile", None)
        if profile is None:
            return

        # Max 15 retries (3 seconds) — give up if runner is hung
        retry_count = getattr(self, "_advisor_retry_count", 0)
        if retry_count >= 15:
            log.warning("Advisor: gave up waiting for runner to drain after %d retries",
                        retry_count)
            self._pending_advisor_profile = None
            self._advisor_active = False
            return

        # Check if the runner is still busy (cancel not yet drained)
        runner = (self._ai_service._remote_runner
                  if (self._ai_service._active_backend == "remote"
                      and self._ai_service._remote_runner is not None)
                  else self._ai_service._runner)
        if getattr(runner, "_busy", False):
            # Still draining — retry again shortly
            from PyQt5.QtCore import QTimer
            self._advisor_retry_count = retry_count + 1
            QTimer.singleShot(200, self._retry_launch_advisor)
            return

        self._pending_advisor_profile = None

        self._ai_service._set_status("ready")
        if not self._ai_service.can("proactive_advisor"):
            return
        try:
            self._launch_advisor(profile)
        except Exception as exc:
            log.error("AI Advisor failed to launch: %s", exc, exc_info=True)
            self._log_tab.append(f"AI Advisor error: {exc}", level="error")
            self._status.showMessage("AI Advisor error — see log", 5000)
            self._advisor_active = False

    def _launch_advisor(self, profile) -> None:
        """Internal: build prompt, create dialog, fire inference."""
        from ai.advisor import (build_advisor_prompt, profile_to_summary,
                                ADVISOR_MAX_TOKENS_LOCAL, ADVISOR_MAX_TOKENS_CLOUD)
        from ui.widgets.advisor_dialog import AdvisorDialog

        # Determine camera type and modality for prompt adaptation
        camera_type = getattr(app_state, "active_camera_type", "tr")
        modality    = getattr(app_state, "active_modality", "thermoreflectance")

        # Build the analysis prompt
        ctx_json    = self._ai_service._ctx.build()
        profile_sum = profile_to_summary(profile, camera_type=camera_type)

        # Gather diagnostic issues (if engine is available)
        diag_text = ""
        try:
            engine = self._ai_service._ctx._diagnostics
            if engine is not None:
                results = engine.evaluate()
                issues  = [r for r in results if r.severity in ("fail", "warn")]
                if issues:
                    diag_text = "\n".join(
                        f"  {r.severity.upper()}: {r.display_name} — {r.observed}"
                        for r in issues)
        except Exception:
            pass

        is_cloud = (self._ai_service._active_backend == "remote"
                    and getattr(self._ai_service._remote_runner, "_provider", "")
                    != "ollama")
        messages = build_advisor_prompt(
            profile_sum, ctx_json, diag_text,
            cloud=is_cloud, modality=modality)

        # Create and show the dialog
        dlg = AdvisorDialog(parent=self)
        dlg.proceed_clicked.connect(self._on_advisor_proceed)
        dlg.cancel_requested.connect(self._on_advisor_cancelled)
        dlg.show_thinking()
        dlg.show()

        # Determine token budget before storing state
        max_tok = ADVISOR_MAX_TOKENS_CLOUD if is_cloud else ADVISOR_MAX_TOKENS_LOCAL

        # Store ref so streaming callbacks can reach the dialog
        self._advisor_dlg = dlg
        self._advisor_text = []
        self._advisor_active = True  # suppress normal chat panel tokens
        self._advisor_retried = False  # track whether we already retried
        self._advisor_messages = messages  # keep for retry
        self._advisor_max_tok = max_tok
        self._advisor_is_cloud = is_cloud

        # Connect to streaming signals temporarily
        self._ai_service.response_token.connect(self._on_advisor_token)
        self._ai_service.response_complete.connect(self._on_advisor_complete)
        self._ai_service.ai_error.connect(self._on_advisor_error)

        # Fire the inference (bypasses the normal _run to avoid history injection)
        if (self._ai_service._active_backend == "remote"
                and self._ai_service._remote_runner is not None):
            self._ai_service._remote_runner.infer(
                messages, max_tokens=max_tok, temperature=0.0)
        else:
            self._ai_service._runner.infer(
                messages, max_tokens=max_tok, temperature=0.0)

        self._ai_service._set_status("thinking")
        self._log_tab.append(
            f"AI Advisor analysing profile: {getattr(profile, 'name', '?')}")
        log.info("AI Advisor launched for %s profile %r (camera=%s, modality=%s)",
                 camera_type.upper(), getattr(profile, "name", "?"),
                 camera_type, modality)

    def _on_advisor_token(self, token: str) -> None:
        """Accumulate tokens during advisor analysis."""
        if hasattr(self, "_advisor_text"):
            self._advisor_text.append(token)

    def _on_advisor_complete(self, text: str, elapsed: float) -> None:
        """Parse advisor response and show results in the dialog."""
        from ai.advisor import parse_advice

        result = parse_advice(text)

        # Retry once with a stricter nudge if JSON parsing failed
        if (not result.parse_ok
                and not getattr(self, "_advisor_retried", True)):
            self._advisor_retried = True
            self._advisor_text = []
            log.info("AI Advisor: JSON parse failed — retrying with nudge")

            # Append a correction message and re-fire
            msgs = list(getattr(self, "_advisor_messages", []))
            msgs.append({"role": "assistant", "content": text})
            msgs.append({"role": "user", "content":
                         "That was not valid JSON. Respond with ONLY a JSON "
                         "object — no prose, no markdown. Start with {"})
            max_tok = getattr(self, "_advisor_max_tok", 512)
            if (self._ai_service._active_backend == "remote"
                    and self._ai_service._remote_runner is not None):
                self._ai_service._remote_runner.infer(
                    msgs, max_tokens=max_tok, temperature=0.0)
            else:
                self._ai_service._runner.infer(
                    msgs, max_tokens=max_tok, temperature=0.0)
            return

        self._advisor_active = False
        # Disconnect temporary signal connections
        try:
            self._ai_service.response_token.disconnect(self._on_advisor_token)
            self._ai_service.response_complete.disconnect(self._on_advisor_complete)
            self._ai_service.ai_error.disconnect(self._on_advisor_error)
        except TypeError:
            pass

        self._ai_service._set_status("ready")

        dlg = getattr(self, "_advisor_dlg", None)
        if dlg is None:
            return

        dlg.show_result(result)
        log.info("AI Advisor: %d conflicts, %d suggestions (%.1fs, parse_ok=%s)",
                 len(result.conflicts), len(result.suggestions),
                 elapsed, result.parse_ok)

        # Log advisor findings to the session log tab
        if result.parse_ok:
            parts = []
            for c in result.conflicts:
                parts.append(f"  ⚠ {c.issue}")
            for s in result.suggestions:
                reason = s.reason or f"set {s.param} to {s.value} {s.unit}"
                parts.append(f"  → {reason}")
            if parts:
                self._log_tab.append(
                    f"AI Advisor: {len(result.conflicts)} conflicts, "
                    f"{len(result.suggestions)} suggestions")
                for p in parts:
                    self._log_tab.append(p)
            else:
                self._log_tab.append("AI Advisor: no issues found")
        else:
            self._log_tab.append("AI Advisor: returned text (JSON parse failed)")

    def _on_advisor_cancelled(self) -> None:
        """Cancel advisor — called by user Cancel button or programmatic preemption."""
        self._advisor_active = False
        try:
            self._ai_service.response_token.disconnect(self._on_advisor_token)
            self._ai_service.response_complete.disconnect(self._on_advisor_complete)
            self._ai_service.ai_error.disconnect(self._on_advisor_error)
        except TypeError:
            pass
        self._ai_service.cancel()
        # Close the dialog widget if still visible (programmatic cancel)
        dlg = getattr(self, "_advisor_dlg", None)
        if dlg is not None:
            dlg.close()
        self._advisor_dlg = None
        log.info("AI Advisor cancelled")

    def _on_advisor_error(self, msg: str) -> None:
        """Handle advisor inference error."""
        self._advisor_active = False
        try:
            self._ai_service.response_token.disconnect(self._on_advisor_token)
            self._ai_service.response_complete.disconnect(self._on_advisor_complete)
            self._ai_service.ai_error.disconnect(self._on_advisor_error)
        except TypeError:
            pass

        self._ai_service._set_status("ready")

        dlg = getattr(self, "_advisor_dlg", None)
        if dlg is not None:
            dlg.show_error(msg)

    def _on_advisor_proceed(self, fixes: list) -> None:
        """Apply the AI advisor's suggested fixes."""
        if not fixes:
            return

        # Deduplicate by param — last value wins (suggestion overrides conflict)
        seen: dict = {}
        for fix in fixes:
            p = fix.get("param", "")
            if p:
                seen[p] = fix
        fixes = list(seen.values())

        applied = []
        for fix in fixes:
            param = fix.get("param", "")
            value = fix.get("value")
            if value is None:
                continue
            try:
                if param == "exposure" or param == "exposure_us":
                    hw_service.cam_set_exposure(float(value))
                    self._camera_tab.set_exposure(float(value))
                    applied.append(f"Exposure → {value} µs")
                elif param == "gain" or param == "gain_db":
                    hw_service.cam_set_gain(float(value))
                    self._camera_tab.set_gain(float(value))
                    applied.append(f"Gain → {value} dB")
                elif param == "stimulus_freq" or param == "stimulus_freq_hz":
                    hw_service.fpga_set_frequency(float(value))
                    applied.append(f"Stimulus freq → {value} Hz")
                elif param == "stimulus_duty":
                    hw_service.fpga_set_duty_cycle(float(value))
                    applied.append(f"Stimulus duty → {value}%")
                elif param == "tec_setpoint" or param == "tec_setpoint_c":
                    hw_service.tec_set_target(0, float(value))
                    applied.append(f"TEC setpoint → {value} °C")
                elif param == "n_frames":
                    self._acquire_tab.set_n_frames(int(value))
                    applied.append(f"Frames → {value}")
                else:
                    log.info("AI Advisor: unknown param %r — skipped", param)
            except Exception as exc:
                log.warning("AI Advisor: failed to apply %s=%s: %s",
                            param, value, exc)

        if applied:
            n = len(applied)
            brief = f"AI Advisor applied {n} {'change' if n == 1 else 'changes'}"
            self._status.showMessage(brief, 5000)
            self._log_tab.append(
                f"{brief}: {', '.join(applied)}")
        else:
            self._status.showMessage("AI Advisor: no changes applied", 3000)

    # ── AI enable/disable ─────────────────────────────────────────────

    def _on_ai_enable(self, model_path: str, n_gpu_layers: int):
        """Called when Settings tab emits ai_enable_requested."""
        self._ai_panel.clear_display()
        self._ai_service.enable(model_path, n_gpu_layers)
        # Show the panel automatically when loading starts
        self._ai_dock.show()

    def _on_cloud_ai_connect(self, provider: str, api_key: str, model_id: str) -> None:
        """Called when Settings tab emits cloud_ai_connect_requested."""
        self._ai_panel.clear_display()
        self._ai_service.enable_remote(provider, api_key, model_id)
        self._ai_dock.show()

    def _on_cloud_ai_disconnect(self) -> None:
        """Called when Settings tab emits cloud_ai_disconnect_requested."""
        self._ai_service.disable()
        self._settings_tab.set_cloud_ai_status("off")

    def _on_ollama_connect(self, model_id: str) -> None:
        """Called when Settings tab emits ollama_connect_requested."""
        self._ai_panel.clear_display()
        # Ollama uses the OpenAI-compatible endpoint — no API key needed
        self._ai_service.enable_remote("ollama", "", model_id)
        self._ai_dock.show()

    def _on_ollama_disconnect(self) -> None:
        """Called when Settings tab emits ollama_disconnect_requested."""
        self._ai_service.disable()
        self._settings_tab.set_ollama_status("off")

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
            # Evaluate device readiness at startup so the safe-mode banner
            # appears immediately if hardware is not connected.
            self._update_safe_mode()
            # Force widget-level QSS on #primary/#danger buttons so parent
            # container backgrounds don't cascade over them.
            QTimer.singleShot(0, self._restyle_action_buttons)
            # Allow enough time for the hardware init sequence to finish before
            # surfacing device-connection toasts.  10 s covers the slowest real
            # hardware (FPGA firmware load) on both macOS demo and Windows.
            QTimer.singleShot(10_000, self._on_startup_done)

    def _on_startup_done(self):
        """Mark the startup window as complete; enable hotplug toasts."""
        self._startup_done = True
        # Deferred AI model load — kicked off here so the Metal/GPU init
        # in llama-cpp doesn't starve the main thread during widget
        # construction (it was blocking _build_ui for ~50 s).
        if getattr(self, "_deferred_ai_enabled", False):
            model_path = getattr(self, "_deferred_ai_model_path", "")
            if model_path:
                n_gpu = getattr(self, "_deferred_ai_n_gpu", 0)
                log.info("Starting deferred AI model load: %s", model_path)
                self._ai_service.enable(model_path, n_gpu)
        # Ensure tab empty-state placeholders reflect actual hardware.
        # In demo mode all tabs are already shown; in normal mode this
        # hides controls for unconnected devices (stage, TEC, etc.).
        if not app_state.demo_mode:
            self._refresh_tab_availability()
        # Always refresh the modality section so the camera combo is populated
        # even in demo mode (where _refresh_tab_availability is skipped).
        try:
            self._modality_section.refresh()
        except Exception:
            log.debug("Modality startup refresh failed", exc_info=True)

    def _restore_layout(self):
        """Restore persisted window geometry and tab splitter sizes."""
        import config as _cfg
        from PyQt5.QtCore import QByteArray
        geo = _cfg.get_pref("ui.geometry", "")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
            except Exception:
                log.debug("_restore_layout: restoreGeometry failed", exc_info=True)
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
                    log.debug("_restore_layout: setSizes failed for %s", key,
                              exc_info=True)

    def _save_layout(self):
        """Persist window geometry and tab splitter sizes."""
        import config as _cfg
        try:
            _cfg.set_pref("ui.geometry",
                          self.saveGeometry().toHex().data().decode())
        except Exception:
            log.debug("_save_layout: saveGeometry failed", exc_info=True)
        for attr, key in [
            ("_live_tab",     "ui.splitter.live"),
            ("_scan_tab",     "ui.splitter.scan"),
            ("_analysis_tab", "ui.splitter.analysis"),
        ]:
            try:
                _cfg.set_pref(key, list(getattr(self, attr)._body_splitter.sizes()))
            except Exception:
                log.debug("_save_layout: set_pref failed for %s", key,
                          exc_info=True)

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
            log.debug("closeEvent: autosave clear failed (non-fatal)", exc_info=True)
        # ── Deactivate plugins ────────────────────────────────────
        if hasattr(self, "_plugin_registry") and self._plugin_registry:
            try:
                self._plugin_registry.deactivate_all()
            except Exception:
                log.debug("Plugin deactivation failed (non-fatal)", exc_info=True)

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

        # Mark clean exit so next launch knows we didn't crash
        try:
            from logging_config import mark_clean_exit
            mark_clean_exit()
        except Exception:
            pass

        event.accept()
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Auth helper — OperatorShell launch                                 #
# ------------------------------------------------------------------ #

def _launch_operator_shell(auth, auth_session, session_mgr, app):
    """
    Instantiate and run the OperatorShell for Technician users.

    Called from the startup routing block when the logged-in user is a
    Technician.  Blocks until the operator shell exits, then returns so
    the caller can sys.exit(0).

    Parameters
    ----------
    auth         : Authenticator
    auth_session : AuthSession
    session_mgr  : SessionManager
    app          : QApplication
    """
    from ui.operator.operator_shell import OperatorShell

    shell = OperatorShell(
        auth=auth,
        auth_session=auth_session,
        session_mgr=session_mgr,
    )
    shell.show()

    # 30-second inactivity lock timer
    _lock_timer = QTimer()
    _lock_timer.setInterval(30_000)

    def _check_lock():
        if auth is None:
            return
        timeout = int(config.get_pref("auth.lock_timeout_s", 1800))
        if auth.check_lock_timeout(timeout):
            log.info("OperatorShell: inactivity lock triggered")
            shell.hide()
            # Re-show login screen
            from ui.auth.login_screen import LoginScreen
            from PyQt5.QtCore import QEventLoop as _QEL
            ls = LoginScreen(auth)
            ls.resize(app.primaryScreen().availableSize())
            _el = _QEL()
            ls.login_success.connect(
                lambda sess: (
                    setattr(ls, "_sess", sess),
                    _el.quit(),
                ) and None
            )
            ls.show()
            _el.exec_()
            new_sess = getattr(ls, "_sess", None)
            ls.hide()
            if new_sess is not None:
                shell.set_auth_session(new_sess)
                shell.show()
            else:
                shell.close()

    _lock_timer.timeout.connect(_check_lock)
    _lock_timer.start()

    app.exec_()
    _lock_timer.stop()


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import sys as _sys

    # ── Configure rotating log file before anything else ──────────────
    # This must run before config is reloaded or QApplication is created
    # so that every log message (including hardware init) is captured.
    # Pass --debug on the command line to enable DEBUG-level logging for
    # troubleshooting crashes and hardware initialisation issues.
    import logging_config as _lc
    import config as _cfg_boot
    _debug_mode = "--debug" in _sys.argv or "--verbose" in _sys.argv
    _log_level  = "DEBUG" if _debug_mode else _cfg_boot.get("logging").get("level", "INFO")
    _lc.setup(level=_log_level)

    # ── Check for previous crash BEFORE opening new session log ──────
    # open_session_log() truncates session.log, so we must read first.
    _prev_crash_log = _lc.previous_crash_log()
    _lc.open_session_log()

    # ── Global exception hook — prevents PyQt5 abort() on slot errors ──
    # PyQt5 ≥ 5.15 calls qFatal() → abort() when a Python exception
    # escapes a signal/slot boundary without being caught.  Installing a
    # custom sys.excepthook intercepts this: PyQt5 calls our hook first
    # so we can log the full traceback to the rotating log file and
    # show a non-fatal error dialog, rather than silently crashing.
    import traceback as _tb

    _crash_log = logging.getLogger("crash_handler")

    def _qt_exception_hook(exc_type, exc_value, exc_tb):
        msg = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        _crash_log.critical(
            "Unhandled exception in PyQt5 slot (process saved from abort):\n%s",
            msg)
        # Flush so it reaches disk before any further crash
        for _h in logging.getLogger().handlers:
            try:
                _h.flush()
            except Exception:
                pass
        # Show a non-modal error dialog if QApplication already exists
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication as _QA
            if _QA.instance():
                _dlg = QMessageBox()
                _dlg.setWindowTitle("Unexpected Error")
                _dlg.setIcon(QMessageBox.Critical)
                _dlg.setText(
                    "An unexpected error occurred in the application.\n\n"
                    "The full traceback has been written to the log file.\n"
                    f"Log: {_lc.log_path()}")
                _dlg.setDetailedText(msg)
                _dlg.exec_()
        except Exception:
            pass

    _sys.excepthook = _qt_exception_hook

    # ── Background-thread exception hook ──────────────────────────────
    # threading.excepthook (Python 3.8+) is called when a daemon or worker
    # thread raises an unhandled exception.  Without this, every crash in
    # HardwareService threads, scan workers, or autosave threads is silently
    # swallowed — not even the pre-boot hook sees them, because the pre-boot
    # hook only covers the main thread.
    import threading as _threading

    def _thread_excepthook(args: "_threading.ExceptHookArgs") -> None:
        if args.exc_type is SystemExit:
            return  # normal thread shutdown — not an error
        msg = "".join(_tb.format_exception(
            args.exc_type, args.exc_value, args.exc_tb))
        full = f"Unhandled exception in thread '{args.thread.name}':\n{msg}"
        _crash_log.critical(full)
        for _h in logging.getLogger().handlers:
            try:
                _h.flush()
            except Exception:
                pass
        # Also write to the pre-boot crash file so field support finds it
        # even if the rotating log hasn't been retrieved yet.
        _write_crash_report(
            f"THREAD CRASH [{args.thread.name}]\n{msg}"
        )

    _threading.excepthook = _thread_excepthook

    # ── Unraisable exception hook ──────────────────────────────────────
    # sys.unraisablehook (Python 3.8+) catches exceptions that Python cannot
    # raise normally — typically thrown by __del__ destructors and C-extension
    # finalizers during garbage collection.  PyQt5 triggers these on shutdown
    # when signal/slot connections are cleaned up after the Qt event loop ends.
    # Without this hook they are printed to stderr (invisible on Windows with
    # console=False) or dropped entirely.
    def _unraisable_hook(unraisable) -> None:
        msg = (
            f"Unraisable exception in {unraisable.object!r}:\n"
            + "".join(_tb.format_exception(
                unraisable.exc_type,
                unraisable.exc_value,
                unraisable.exc_traceback,
            ))
        )
        _crash_log.error("sys.unraisablehook: %s", msg)
        for _h in logging.getLogger().handlers:
            try:
                _h.flush()
            except Exception:
                pass

    _sys.unraisablehook = _unraisable_hook

    # ── Determine launch mode ─────────────────────────────────────────
    # Demo mode activates when:
    #   1.  --demo flag is passed on the command line
    #   2.  Running on macOS — real hardware drivers are Windows-only
    _FORCE_DEMO = ("--demo" in _sys.argv or _sys.platform == "darwin")

    log.info(f"{'='*60}")
    log.info(f"  {APP_VENDOR} {APP_NAME}  {version_string()}")
    log.info(f"  Build date: {__import__('version').BUILD_DATE}")
    log.info(f"  Platform: {_sys.platform}  |  Demo mode: {_FORCE_DEMO}")
    if _debug_mode:
        log.info("  *** DEBUG / VERBOSE MODE ACTIVE (--debug) ***")
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

    # ── DPI-aware font scaling ────────────────────────────────────────────────
    # Must run AFTER QApplication so we can query the real screen logical DPI.
    # With AA_EnableHighDpiScaling, logicalDotsPerInch() returns the *logical*
    # DPI (e.g. 96 on a 200 %-scaled 4K Windows display; 72 on macOS Retina).
    # scale = 72 / logical_dpi normalises all pt values to the macOS baseline.
    # NOTE: do NOT use QT_FONT_DPI — that env var affects system dialogs too.
    _screen_dpi = app.primaryScreen().logicalDotsPerInch()
    _dpi_scale  = max(0.5, min(1.0, 72.0 / _screen_dpi))
    log.debug("Screen logical DPI=%.1f  →  font scale=%.3f", _screen_dpi, _dpi_scale)

    from ui.theme import (
        apply_dpi_scale as _apply_dpi_scale,
        FONT as _FONT_LIVE,
        build_style as _build_style,
        build_qt_palette as _build_qt_palette,
        set_theme as _set_theme,
        detect_system_theme as _detect_system_theme,
    )
    from ui.font_utils import sans_font as _sans_font
    _apply_dpi_scale(_dpi_scale)

    # Resolve the initial effective theme ("auto" defers to OS).
    _initial_pref      = config.get_pref("ui.theme", "auto")
    _initial_effective = _detect_system_theme() if _initial_pref == "auto" else _initial_pref
    _set_theme(_initial_effective)

    # Set base application font so all Qt widgets that don't have an explicit
    # QSS font rule inherit the platform-appropriate family (Segoe UI on
    # Windows, Helvetica Neue on macOS) at the correctly-scaled body size.
    app.setFont(_sans_font(_FONT_LIVE["body"]))
    app.setStyleSheet(_build_style(_initial_effective))
    app.setPalette(_build_qt_palette(_initial_effective))

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

    # ── Auth startup (Phase D) ────────────────────────────────────────
    _auth         = None
    _auth_session = None
    try:
        from auth.store         import UserStore, AuditLogger
        from auth.authenticator import Authenticator
        _user_store = UserStore()
        _audit_log  = AuditLogger()
        _auth       = Authenticator(_user_store, _audit_log)

        # ① One-time admin setup if no users exist
        if not _user_store.has_users():
            from ui.auth.admin_setup_wizard import AdminSetupWizard
            from PyQt5.QtWidgets import QDialog as _QDialog
            wiz = AdminSetupWizard(_user_store, _audit_log)
            if wiz.exec_() != _QDialog.Accepted:
                _sys.exit(0)
            # Auto-login the newly created admin so their name appears in the
            # header immediately and the Security group is visible in Settings.
            _created_user = wiz.created_user()   # AdminSetupWizard exposes this
            if _created_user is not None:
                _auth_session = _auth.authenticate_user(_created_user)

        # ② Login gate (only when admin has enabled require_login)
        if config.get_pref("auth.require_login", False):
            from ui.auth.login_screen import LoginScreen
            from PyQt5.QtCore import QEventLoop as _QEventLoop

            _login_screen = LoginScreen(_auth)
            _login_screen.resize(app.primaryScreen().availableSize())

            _loop = _QEventLoop()
            _login_screen.login_success.connect(
                lambda sess: (
                    setattr(_login_screen, "_accepted_session", sess),
                    _loop.quit(),
                ) and None
            )
            _login_screen.show()
            _loop.exec_()
            _auth_session = getattr(_login_screen, "_accepted_session", None)
            _login_screen.hide()
            if _auth_session is None:
                _sys.exit(0)

        # ③ Route Technicians to OperatorShell
        if (_auth_session is not None
                and _auth_session.user.user_type.uses_operator_shell):
            _launch_operator_shell(_auth, _auth_session, session_mgr, app)
            _sys.exit(0)

    except Exception as _auth_err:
        log.warning("Auth startup skipped (non-fatal): %s", _auth_err)
        _auth         = None
        _auth_session = None

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

    window = MainWindow(auth=_auth, auth_session=_auth_session)
    if _icon_path:
        window.setWindowIcon(_app_icon)   # title-bar / taskbar icon

    # ── Demo mode: activate immediately, skip the startup dialog ──────
    # If devices were previously connected, try to auto-connect them after
    # demo mode starts — the _handle_real_device_in_demo path will
    # automatically exit demo mode once the first connection succeeds.
    _remembered_uids = config.get_pref("hw.last_connected_devices", [])
    # Backward compat: migrate single-device key to list
    if not _remembered_uids:
        _single = config.get_pref("hw.last_connected_device", None)
        if _single:
            _remembered_uids = [_single]

    if _FORCE_DEMO:
        app_state.demo_mode = True
        window._header.set_demo_mode(True)
        window._status.showMessage(
            f"SanjINSIGHT {version_string()}  \u2014  DEMO MODE  (simulated hardware)", 0)
        signals.log_message.emit("Running in demo mode \u2014 all hardware is simulated")
        hw_service.start_demo()
        window._show_all_tabs()  # demo mode: all tabs show full controls
        # Register demo devices in the header so they appear immediately
        # (tec_status callbacks will update the actual status later).
        window._header.set_connecting("tec0")
        window._header.set_connecting("tec1")
        window._header.set_connecting("fpga")
        window._header.set_connecting("bias")
        window._header.set_connecting("stage")

        # Auto-connect all previously-used devices in the background.
        if _remembered_uids:
            def _auto_reconnect():
                import time as _t
                from hardware.device_manager import DeviceState
                _t.sleep(1.5)   # let demo mode finish initialising
                dm = window._device_mgr
                for uid in _remembered_uids:
                    entry = dm.get(uid)
                    if entry is None:
                        log.info("Auto-reconnect: device %s not in registry", uid)
                        continue
                    if entry.state == DeviceState.CONNECTED:
                        log.info("Auto-reconnect: %s already connected — skipping",
                                 entry.descriptor.display_name)
                        continue
                    # Camera-type devices (Basler pypylon) connect via SDK
                    # enumeration and don't require a serial address.
                    from hardware.device_registry import CONN_CAMERA
                    _conn = entry.descriptor.connection_type
                    if entry.address or _conn == CONN_CAMERA:
                        log.info("Auto-reconnect: attempting %s on %s …",
                                 entry.descriptor.display_name,
                                 entry.address or f"({_conn} enumeration)")
                        dm.connect(uid)
                        # Small delay between connections to let each device
                        # initialise before the next one starts.
                        _t.sleep(1.0)
                    else:
                        log.info("Auto-reconnect: no saved address for %s — skipping",
                                 uid)

            threading.Thread(
                target=_auto_reconnect, daemon=True,
                name="hw.auto_reconnect"
            ).start()

    # ── Normal startup: Device Manager as the startup gate ───────────
    else:
        hw_cfg = config.get("hardware", {})

        # Set amber connecting dots in the header for all enabled devices so
        # the user has immediate visual feedback while hardware initialises.
        if hw_cfg.get("camera", {}).get("enabled", True):
            window._header.set_connecting("camera")
        for _tec_key, _dot_key in [("tec_meerstetter", "tec0"), ("tec_atec", "tec1")]:
            if hw_cfg.get(_tec_key, {}).get("enabled", False):
                window._header.set_connecting(_dot_key)
                window._cam_bar.set_peripheral("tec", None, "Connecting…")
        if hw_cfg.get("fpga",  {}).get("enabled", False):
            window._header.set_connecting("fpga")
            window._cam_bar.set_peripheral("fpga", None, "Connecting…")
        if hw_cfg.get("bias",  {}).get("enabled", False):
            window._header.set_connecting("bias")
            window._cam_bar.set_peripheral("bias", None, "Connecting…")
        if hw_cfg.get("stage", {}).get("enabled", False):
            window._header.set_connecting("stage")
            window._cam_bar.set_peripheral("stage", None, "Connecting…")

        # Show a status-bar advisory when any device falls back to simulation
        # (so the user can distinguish "real HW connected" from "simulated").
        _simulated_keys: list = []
        def _on_startup_status_sim(key: str, ok: bool, detail: str):
            if ok and "simulated" in detail.lower():
                _simulated_keys.append(key)
                if not app_state.demo_mode:
                    keys_str = ", ".join(_simulated_keys)
                    window._status.showMessage(
                        f"SanjINSIGHT {version_string()}  \u2014  "
                        f"Simulated hardware  ({keys_str} \u2014 no real hardware connected)",
                        0)
        hw_service.startup_status.connect(_on_startup_status_sim)

        # Start hardware after the Qt event loop begins (see COM STA
        # message-pump explanation in the QTimer.singleShot comment above).
        # When auto-reconnect will handle cameras, skip camera init in
        # hw_service.start() to prevent both paths from opening the same
        # USB camera (causes "exclusively opened" errors on Windows).
        _has_remembered_cameras = any(
            (window._device_mgr.get(u) and
             window._device_mgr.get(u).descriptor.device_type == "camera")
            for u in _remembered_uids
        ) if _remembered_uids else False
        if _has_remembered_cameras:
            QTimer.singleShot(0, lambda: hw_service.start(skip_cameras=True))
        else:
            QTimer.singleShot(0, hw_service.start)

        # Show Device Manager modally so the user sees scan results before
        # the main interface is accessible.  Modality is removed once the
        # user closes the DM so subsequent deliberate opens are non-blocking.
        #
        # suppress_next_scan() prevents the DM's auto-scan from firing at
        # startup.  hw_service.start() (posted to the same first idle tick)
        # is already spawning NI/pyvisa init threads; a concurrent DM scan
        # would race on pyvisa.ResourceManager() initialisation inside the
        # NI VISA DLL and cause 10–30 s freezes on Windows / Parallels.
        # Subsequent DM opens (user-initiated) scan normally — only this
        # first programmatic show() is suppressed.
        def _show_startup_dm():
            dm = window._device_mgr_dlg
            dm.suppress_next_scan()
            dm.setWindowModality(Qt.ApplicationModal)
            dm.show()
            dm.finished.connect(lambda _: dm.setWindowModality(Qt.NonModal))
        QTimer.singleShot(0, _show_startup_dm)

        # Auto-reconnect all previously-used Device Manager devices.
        # Camera init is skipped in hw_service.start() when remembered
        # camera UIDs exist (skip_cameras=True), so Device Manager is the
        # sole owner of camera connections — no double-open race.
        # Non-camera devices may still be opened by hw_service.start()
        # from config, so we check app_state for those.
        if _remembered_uids:
            def _auto_reconnect_normal():
                import time as _t
                from hardware.device_manager import DeviceState
                from hardware.device_registry import (
                    CONN_CAMERA, DTYPE_CAMERA, DTYPE_FPGA,
                    DTYPE_STAGE, DTYPE_TEC, DTYPE_BIAS)
                # Brief pause to let Qt event loop start and hw_service
                # threads to begin.  Cameras are handled exclusively by
                # Device Manager (no race), so this only needs to be long
                # enough for non-camera hw_service init.
                _t.sleep(2.0)
                dm = window._device_mgr
                for uid in _remembered_uids:
                    entry = dm.get(uid)
                    if entry is None:
                        log.info("Auto-reconnect: device %s not in registry", uid)
                        continue
                    # Skip if Device Manager already has it connected.
                    if entry.state == DeviceState.CONNECTED:
                        log.info("Auto-reconnect: %s already connected — skipping",
                                 entry.descriptor.display_name)
                        continue
                    # For non-camera devices, check if hw_service.start()
                    # already opened this device type from config.
                    dtype = entry.descriptor.device_type
                    _already_open = False
                    if dtype == DTYPE_FPGA and app_state.fpga is not None:
                        _already_open = True
                    elif dtype == DTYPE_STAGE and app_state.stage is not None:
                        _already_open = True
                    elif dtype == DTYPE_TEC and len(app_state.tecs) > 0:
                        _already_open = True
                    elif dtype == DTYPE_BIAS and app_state.bias is not None:
                        _already_open = True
                    if _already_open:
                        log.info("Auto-reconnect: %s — device type already "
                                 "open in app_state, skipping",
                                 entry.descriptor.display_name)
                        continue

                    _conn = entry.descriptor.connection_type
                    if entry.address or _conn == CONN_CAMERA:
                        log.info("Auto-reconnect: attempting %s on %s …",
                                 entry.descriptor.display_name,
                                 entry.address or f"({_conn} enumeration)")
                        dm.connect(uid)
                        _t.sleep(1.0)
                    else:
                        log.info("Auto-reconnect: no saved address for %s — skipping",
                                 uid)

            threading.Thread(
                target=_auto_reconnect_normal, daemon=True,
                name="hw.auto_reconnect"
            ).start()

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
    window._load_license()           # validate stored license key
    window._start_update_checker()   # background check, non-blocking

    # ── Show crash recovery dialog if previous session didn't exit cleanly ──
    if _prev_crash_log:
        def _show_crash_dialog():
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, \
                QPushButton, QHBoxLayout, QSizePolicy
            from ui.theme import PALETTE, MONO_FONT, FONT

            dlg = QDialog(window)
            dlg.setWindowTitle("SanjINSIGHT — Previous Session")
            dlg.setMinimumSize(600, 400)
            lay = QVBoxLayout(dlg)

            lbl = QLabel("The previous session did not shut down cleanly.\n"
                         "The session log may help diagnose what happened:")
            lbl.setStyleSheet(f"color: {PALETTE['warning']}; "
                              f"font-size: {FONT['heading']}pt; "
                              f"font-weight: bold;")
            lay.addWidget(lbl)

            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setPlainText(_prev_crash_log)
            txt.setStyleSheet(
                f"background: {PALETTE['bg']}; color: {PALETTE['textDim']}; "
                f"font-family: {MONO_FONT}; font-size: {FONT['body']}pt; "
                f"border: 1px solid {PALETTE['border']};")
            lay.addWidget(txt)

            btn_row = QHBoxLayout()
            btn_row.addStretch()

            copy_btn = QPushButton("Copy to Clipboard")
            copy_btn.clicked.connect(
                lambda: QApplication.clipboard().setText(_prev_crash_log))
            btn_row.addWidget(copy_btn)

            ok_btn = QPushButton("OK")
            ok_btn.setDefault(True)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)
            lay.addLayout(btn_row)

            dlg.exec_()

        QTimer.singleShot(800, _show_crash_dialog)

    # Show the first-run license prompt after the window has settled.
    # QTimer.singleShot ensures the event loop is running and all startup
    # dialogs (Device Manager, autosave recovery) have had a chance to appear
    # first.  The prompt is a no-op on subsequent launches (pref guard inside).
    QTimer.singleShot(600, window._maybe_show_license_prompt)

    # Mark startup as complete in the crash-report file so support knows
    # the app reached the event loop successfully.
    _write_crash_report(
        f"=== STARTUP COMPLETE === {_time_boot.strftime('%Y-%m-%d %H:%M:%S')}  "
        f"demo={_FORCE_DEMO}"
    )

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
                    _dlg = _QMB(window)
                    _dlg.setWindowTitle("Restore Unsaved Result")
                    _dlg.setIcon(_QMB.Question)
                    _dlg.setText(
                        f"An unsaved {_label} result from {saved_at} was found.\n\n"
                        "Restore it now?")
                    _restore_btn = _dlg.addButton("Restore",  _QMB.AcceptRole)
                    _dlg.addButton("Discard", _QMB.RejectRole)
                    _dlg.setDefaultButton(_restore_btn)
                    _dlg.exec_()
                    if _dlg.clickedButton() is _restore_btn:
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
                                    window._nav.navigate_to(window._capture_tab)
                        except Exception as _re:
                            log.debug("Autosave restore: failed to push result to UI — %s",
                                      _re, exc_info=True)
                    _as.clear()
    except Exception as _ce:
        log.debug("Autosave recovery: unexpected error (startup continues) — %s",
                  _ce, exc_info=True)

    # ── Inactivity lock timer (auth mode only) ────────────────────────
    if _auth is not None and _auth_session is not None:
        _mw_lock_timer = QTimer()
        _mw_lock_timer.setInterval(30_000)

        def _mw_check_lock():
            timeout = int(config.get_pref("auth.lock_timeout_s", 1800))
            if _auth.check_lock_timeout(timeout):
                log.info("MainWindow: inactivity lock triggered")
                window.hide()
                from ui.auth.login_screen import LoginScreen
                from PyQt5.QtCore import QEventLoop as _QEL2
                ls2 = LoginScreen(_auth)
                ls2.resize(app.primaryScreen().availableSize())
                _el2 = _QEL2()
                ls2.login_success.connect(
                    lambda sess: (
                        setattr(ls2, "_sess", sess),
                        _el2.quit(),
                    ) and None
                )
                ls2.show()
                _el2.exec_()
                new_sess2 = getattr(ls2, "_sess", None)
                ls2.hide()
                if new_sess2 is not None:
                    window._auth_session = new_sess2
                    window.show()
                else:
                    window.close()

        _mw_lock_timer.timeout.connect(_mw_check_lock)
        _mw_lock_timer.start()

    _sys.exit(app.exec_())
