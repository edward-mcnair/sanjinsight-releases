"""
hardware/services/stage_service.py

Stage device service — owns stage lifecycle, poll loop, and control surface.
"""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import pyqtSignal

from hardware.services.base_device_service import BaseDeviceService
from hardware.app_state import app_state

try:
    from hardware.stage.factory import create_stage
    _HAS_STAGE = True
except ImportError:
    _HAS_STAGE = False

log = logging.getLogger(__name__)


class StageService(BaseDeviceService):
    """Stage poll loops, demo init, and control-surface methods."""

    # -- Stage-specific signals --------------------------------------------
    status_update = pyqtSignal(object)

    # -- Poll interval -----------------------------------------------------
    _STAGE_POLL_S: float = 0.10

    def __init__(self, stop_event: threading.Event, parent=None):
        super().__init__(stop_event, parent)

        # Pull poll interval from config (class-level value is default).
        try:
            import config as config_module
            poll = (config_module.get("hardware") or {}).get("polling", {})
            self._STAGE_POLL_S = float(poll.get("stage_interval_s", self._STAGE_POLL_S))
        except Exception:
            log.debug("StageService: polling config parse failed -- using defaults",
                      exc_info=True)

    # ── Stage poll loop ───────────────────────────────────────────────

    def _run_stage(self, cfg: dict):
        try:
            stage = create_stage(cfg)
            self._connect_with_retry(stage.connect, label="stage")
            app_state.stage = stage
            self.log_message.emit(f"Stage: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("stage", True)
            self.startup_status.emit("stage", True, cfg.get('driver', 'connected'))
        except Exception as e:
            dev_err = self._classify_and_emit(e, "stage")
            self.device_connected.emit("stage", False)
            self.startup_status.emit("stage", False, dev_err.short_message)
            log.error(f"StageService stage init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = stage.get_status()
                    self.status_update.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.stage.base import StageStatus
                    self.status_update.emit(StageStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("stage", False)
                        self.error.emit(
                            f"Stage: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(stage=stage):
                            try:
                                stage.stop()
                                stage.disconnect()
                            except Exception:
                                log.debug("Stage: cleanup failed before reconnect",
                                          exc_info=True)
                            stage.connect()
                        if not self._reconnect_loop("stage", _do_reconnect, "stage"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._STAGE_POLL_S)
        except Exception as e:
            log.error("[stage] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"Stage: poll thread crashed — {e}")
            self.device_connected.emit("stage", False)

    # ── Demo ──────────────────────────────────────────────────────────

    def _run_demo_stage(self, cfg: dict):
        """Stage demo thread — uses simulated driver."""
        from hardware.stage.simulated import SimulatedStage
        try:
            stage = SimulatedStage(cfg)
            stage.connect()
            app_state.stage = stage
            self.log_message.emit("Stage: demo mode (simulated)")
            self.device_connected.emit("stage", True)
            self.startup_status.emit("stage", True, "Simulated")
        except Exception as e:
            dev_err = self._classify_and_emit(e, "stage")
            self.startup_status.emit("stage", False, dev_err.short_message)
            return
        while not self._stop_event.is_set():
            try:
                self.status_update.emit(stage.get_status())
            except Exception as e:
                from hardware.stage.base import StageStatus
                self.status_update.emit(StageStatus(error=str(e)))
            self._stop_event.wait(timeout=self._STAGE_POLL_S)

    # ── Control surface ───────────────────────────────────────────────

    def stage_move_by(self, x: float = 0.0, y: float = 0.0,
                      z: float = 0.0) -> None:
        """Move stage by relative distances in um."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.move_by, x=x, y=y, z=z, wait=False)

    def stage_move_to(self, x: float, y: float, z: float) -> None:
        """Move stage to absolute position in um."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.move_to, x=x, y=y, z=z, wait=False)

    def stage_home(self, axes: str = "xyz") -> None:
        """Home stage axes ('xyz', 'xy', or 'z')."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.home, axes)

    def stage_stop(self) -> None:
        """Stop all stage motion immediately."""
        stage = app_state.stage
        if stage:
            self._dispatch(stage.stop)

    def stage_move_z(self, distance_um: float) -> None:
        """Move Z stage by distance_um (positive = up, negative = down)."""
        stage = app_state.stage
        if stage:
            if hasattr(stage, 'move_z'):
                self._dispatch(stage.move_z, distance_um)
            else:
                self._dispatch(stage.move_by, z=distance_um, wait=False)
