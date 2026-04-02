"""
hardware/services/bias_service.py

Bias source device service — owns bias lifecycle, poll loop, and control surface.
"""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import pyqtSignal

from hardware.services.base_device_service import BaseDeviceService
from hardware.app_state import app_state

try:
    from hardware.bias.factory import create_bias
    _HAS_BIAS = True
except ImportError:
    _HAS_BIAS = False

try:
    from acquisition.pipeline import AcquisitionPipeline, AcqState
    _HAS_PIPELINE = True
except ImportError:
    _HAS_PIPELINE = False

log = logging.getLogger(__name__)


class BiasService(BaseDeviceService):
    """Bias source poll loops, demo init, and control-surface methods."""

    # -- Bias-specific signals ---------------------------------------------
    status_update = pyqtSignal(object)

    # -- Poll interval -----------------------------------------------------
    _BIAS_POLL_S: float = 0.25

    def __init__(self, stop_event: threading.Event, parent=None):
        super().__init__(stop_event, parent)

        # Pull poll interval from config (class-level value is default).
        try:
            import config as config_module
            poll = (config_module.get("hardware") or {}).get("polling", {})
            self._BIAS_POLL_S = float(poll.get("bias_interval_s", self._BIAS_POLL_S))
        except Exception:
            log.debug("BiasService: polling config parse failed -- using defaults",
                      exc_info=True)

    # ── Bias poll loop ────────────────────────────────────────────────

    def _run_bias(self, cfg: dict):
        try:
            bias = create_bias(cfg)
            self._connect_with_retry(bias.connect, label="bias")
            app_state.bias = bias
            if app_state.pipeline and _HAS_PIPELINE and app_state.fpga is None:
                app_state.pipeline.update_hardware(fpga=None, bias=bias)
            self.log_message.emit(f"Bias: connected ({cfg.get('driver','?')})")
            self.device_connected.emit("bias", True)
            self.startup_status.emit("bias", True, cfg.get('driver', 'connected'))
        except Exception as e:
            dev_err = self._classify_and_emit(e, "bias")
            self.device_connected.emit("bias", False)
            self.startup_status.emit("bias", False, dev_err.short_message)
            log.error(f"BiasService bias init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = bias.get_status()
                    self.status_update.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.bias.base import BiasStatus
                    self.status_update.emit(BiasStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("bias", False)
                        self.error.emit(
                            f"Bias: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(bias=bias):
                            try:
                                bias.disconnect()
                            except Exception:
                                log.debug("Bias: cleanup failed before reconnect",
                                          exc_info=True)
                            bias.connect()
                        if not self._reconnect_loop("bias", _do_reconnect, "bias"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._BIAS_POLL_S)
        except Exception as e:
            log.error("[bias] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"Bias: poll thread crashed — {e}")
            self.device_connected.emit("bias", False)

    # ── Demo ──────────────────────────────────────────────────────────

    def _run_demo_bias(self, cfg: dict):
        """Bias source demo thread — uses simulated driver."""
        from hardware.bias.simulated import SimulatedBias
        try:
            bias = SimulatedBias(cfg)
            bias.connect()
            app_state.bias = bias
            self.log_message.emit("Bias: demo mode (simulated)")
            self.device_connected.emit("bias", True)
            self.startup_status.emit("bias", True, "Simulated")
        except Exception as e:
            dev_err = self._classify_and_emit(e, "bias")
            self.startup_status.emit("bias", False, dev_err.short_message)
            return
        while not self._stop_event.is_set():
            try:
                self.status_update.emit(bias.get_status())
            except Exception as e:
                from hardware.bias.base import BiasStatus
                self.status_update.emit(BiasStatus(error=str(e)))
            self._stop_event.wait(timeout=self._BIAS_POLL_S)

    # ── Control surface ───────────────────────────────────────────────

    def bias_set_mode(self, mode: str) -> None:
        """Set bias source mode ('voltage' or 'current')."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_mode, mode)

    def bias_set_level(self, value: float) -> None:
        """Set bias source output level (V or A depending on mode)."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_level, value)

    def bias_set_compliance(self, value: float) -> None:
        """Set bias source compliance limit."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.set_compliance, value)

    def bias_enable(self) -> None:
        """Enable bias source output."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.enable)

    def bias_disable(self) -> None:
        """Disable bias source output."""
        bias = app_state.bias
        if bias:
            self._dispatch(bias.disable)
