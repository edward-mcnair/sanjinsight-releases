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


# Module-level singleton — import this object, do not instantiate your own.
signals = AppSignals()
