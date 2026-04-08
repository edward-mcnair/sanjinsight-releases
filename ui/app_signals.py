"""
ui/app_signals.py

Application-wide Qt signals — the single source of truth for cross-module
signal routing.

Usage
-----
Any module that needs to emit or connect to an application signal should
import the singleton directly::

    from ui.app_signals import signals

    # emit (from a background thread — Qt queues it to the GUI thread)
    signals.scan_complete.emit(result)

    # connect (in MainWindow or a tab)
    signals.scan_complete.connect(self._on_scan_complete)

Why a separate module?
----------------------
Previously ``AppSignals`` lived in ``main_app.py``, which caused all tabs
and acquisition modules to do ``import main_app`` at runtime just to get
access to the ``signals`` object.  That circular dependency made tabs
impossible to unit-test in isolation and slowed cold-import time.

Moving the singleton here breaks the coupling: tabs import from
``ui.app_signals``; ``main_app`` imports from here too.  The singleton
is created at module-import time so all callers share the same instance.
"""

from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class AppSignals(QObject):
    """Application-wide signals broadcast by hardware threads and services."""

    new_live_frame  = pyqtSignal(object)          # LiveFrame from camera thread
    tec_status      = pyqtSignal(int, object)      # (index, TecStatus)
    fpga_status     = pyqtSignal(object)           # FpgaStatus
    bias_status     = pyqtSignal(object)           # BiasStatus
    stage_status    = pyqtSignal(object)           # StageStatus
    af_progress     = pyqtSignal(object)           # AfResult  (mid-run)
    af_complete     = pyqtSignal(object)           # AfResult  (final)
    cal_progress    = pyqtSignal(object)           # CalibrationProgress
    cal_complete    = pyqtSignal(object)           # CalibrationResult
    scan_progress   = pyqtSignal(object)           # ScanProgress
    scan_complete   = pyqtSignal(object)           # ScanResult
    movie_progress  = pyqtSignal(object)           # MovieProgress
    movie_complete  = pyqtSignal(object)           # MovieResult
    transient_progress = pyqtSignal(object)        # TransientProgress
    transient_complete = pyqtSignal(object)        # TransientResult
    profile_applied = pyqtSignal(object)           # MaterialProfile
    acq_progress    = pyqtSignal(object)           # AcquisitionProgress
    acq_complete    = pyqtSignal(object)           # AcquisitionResult
    acq_saved       = pyqtSignal(object)           # Session (just persisted)
    log_message     = pyqtSignal(str)              # Informational log line
    error           = pyqtSignal(str)              # Error message → toast
    colormap_changed = pyqtSignal(str)             # Colormap name changed by any tab


class StateSignalBridge(QObject):
    """Bridges app_state change notifications to a Qt queued signal.

    ``app_state`` fires listener callbacks **inside** its RLock (from any
    thread).  Those callbacks must not touch Qt widgets.  This bridge
    re-emits each notification as a Qt signal, which Qt automatically
    queues to the GUI event loop for safe processing.

    Usage
    -----
    After creating the bridge, connect to ``state_changed``::

        bridge = StateSignalBridge.install()
        bridge.state_changed.connect(my_handler, Qt.QueuedConnection)

    The handler receives ``(key: str, old_value: object, new_value: object)``.
    """

    # (key, old_value, new_value)
    state_changed = pyqtSignal(str, object, object)

    _instance: "StateSignalBridge | None" = None

    @classmethod
    def install(cls) -> "StateSignalBridge":
        """Create the singleton bridge and subscribe to app_state."""
        if cls._instance is not None:
            return cls._instance
        from hardware.app_state import app_state
        bridge = cls()
        # Subscribe to ALL state changes (wildcard key "")
        app_state.subscribe("", bridge._on_state_change)
        cls._instance = bridge
        return bridge

    def _on_state_change(self, key: str, old, new) -> None:
        """Called under app_state's lock — just emit the Qt signal."""
        self.state_changed.emit(key, old, new)


# Module-level singleton — import this object, do not instantiate your own.
signals = AppSignals()
