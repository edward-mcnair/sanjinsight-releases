"""
hardware/mixins/tec_mixin.py

TEC-related methods extracted from HardwareService.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from hardware.app_state import app_state
from hardware.tec.factory import create_tec

log = logging.getLogger(__name__)


class TecMixin:
    """TEC poll loops, demo init, and control-surface methods."""

    # ── TEC poll loop ─────────────────────────────────────────────────

    def _run_tec(self, key: str, cfg: dict):
        tec_key = "tec0" if "meerstetter" in key else "tec1"
        try:
            tec = create_tec(cfg)
            self._connect_with_retry(tec.connect, label=key)
            idx = app_state.add_tec(tec)
            self.log_message.emit(f"{key}: connected ({cfg.get('driver','?')})")
            self.device_connected.emit(tec_key, True)
            self.startup_status.emit(tec_key, True, cfg.get('driver', 'connected'))
        except Exception as e:
            self.error.emit(f"{key}: {e}")
            self.device_connected.emit(tec_key, False)
            self.startup_status.emit(tec_key, False, str(e)[:60])
            log.error(f"HardwareService TEC init ({key}): {e}")
            return

        # Attach a ThermalGuard to this TEC channel
        from hardware.thermal_guard import ThermalGuard
        guard = ThermalGuard(
            index      = idx,
            tec        = tec,
            cfg        = cfg,
            on_alarm   = lambda i, msg, a, l: self.tec_alarm.emit(i, msg, a, l),
            on_warning = lambda i, msg, a, l: self.tec_warning.emit(i, msg, a, l),
            on_clear   = lambda i: self.tec_alarm_clear.emit(i),
        )
        # Expose guard so UI can call acknowledge() and update_limits()
        app_state.set_tec_guard(idx, guard)

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = tec.get_status()
                    guard.check(status)          # safety check every poll
                    self.tec_status.emit(idx, status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.tec.base import TecStatus
                    self.tec_status.emit(idx, TecStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit(tec_key, False)
                        self.error.emit(
                            f"{key}: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(tec=tec):
                            try:
                                tec.disconnect()
                            except Exception:
                                log.debug("TEC: cleanup failed before reconnect",
                                          exc_info=True)
                            tec.connect()
                        if not self._reconnect_loop(tec_key, _do_reconnect, key):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._TEC_POLL_S)
        except Exception as e:
            log.error("[%s] Poll thread died unexpectedly: %s", key, e, exc_info=True)
            self.error.emit(f"{key}: poll thread crashed — {e}")
            self.device_connected.emit(tec_key, False)

    # ── Demo ──────────────────────────────────────────────────────────

    def _run_demo_tec(self, cfg: dict, tec_key: str):
        """TEC demo thread — uses simulated driver."""
        from hardware.tec.simulated import SimulatedTec
        try:
            tec = SimulatedTec(cfg)
            tec.connect()
            tec.enable()
            idx = app_state.add_tec(tec)
            self.log_message.emit(f"TEC {idx+1}: demo mode (simulated)")
            self.device_connected.emit(tec_key, True)
            self.startup_status.emit(tec_key, True, "Simulated")
        except Exception as e:
            self.startup_status.emit(tec_key, False, str(e)[:60])
            return

        from hardware.thermal_guard import ThermalGuard
        guard = ThermalGuard(
            index      = idx,
            tec        = tec,
            cfg        = cfg,
            on_alarm   = lambda i, msg, a, l: self.tec_alarm.emit(i, msg, a, l),
            on_warning = lambda i, msg, a, l: self.tec_warning.emit(i, msg, a, l),
            on_clear   = lambda i: self.tec_alarm_clear.emit(i),
        )
        app_state.set_tec_guard(idx, guard)

        while not self._stop_event.is_set():
            try:
                status = tec.get_status()
                guard.check(status)
                self.tec_status.emit(idx, status)
            except Exception as e:
                from hardware.tec.base import TecStatus
                self.tec_status.emit(idx, TecStatus(error=str(e)))
            self._stop_event.wait(timeout=self._TEC_POLL_S)

    # ── Control surface ───────────────────────────────────────────────

    def tec_enable(self, idx: int) -> None:
        """Enable TEC channel idx."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].enable)

    def tec_disable(self, idx: int) -> None:
        """Disable TEC channel idx."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].disable)

    def tec_set_target(self, idx: int, temp_c: float) -> None:
        """Set TEC channel idx target temperature in °C."""
        tecs = app_state.tecs
        if idx < len(tecs):
            self._dispatch(tecs[idx].set_target, temp_c)
