"""
hardware/services/fpga_service.py

FPGA device service — owns FPGA lifecycle, poll loop, and control surface.
"""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import pyqtSignal

from hardware.services.base_device_service import BaseDeviceService
from hardware.app_state import app_state
from hardware.fpga.factory import create_fpga

try:
    from acquisition.pipeline import AcquisitionPipeline, AcqState
    _HAS_PIPELINE = True
except ImportError:
    _HAS_PIPELINE = False

log = logging.getLogger(__name__)


class FpgaService(BaseDeviceService):
    """FPGA poll loops, demo init, and control-surface methods."""

    # -- FPGA-specific signals ---------------------------------------------
    status_update = pyqtSignal(object)

    # -- Poll interval -----------------------------------------------------
    _FPGA_POLL_S: float = 0.25

    def __init__(self, stop_event: threading.Event, parent=None):
        super().__init__(stop_event, parent)

        # Pull poll interval from config (class-level value is default).
        try:
            import config as config_module
            poll = (config_module.get("hardware") or {}).get("polling", {})
            self._FPGA_POLL_S = float(poll.get("fpga_interval_s", self._FPGA_POLL_S))
        except Exception:
            log.debug("FpgaService: polling config parse failed -- using defaults",
                      exc_info=True)

    # ── FPGA poll loop ────────────────────────────────────────────────

    def _run_fpga(self, cfg: dict):
        try:
            fpga = create_fpga(cfg)
            self._connect_with_retry(fpga.open, label="fpga")
            app_state.fpga = fpga
            # Wire existing pipeline to FPGA if camera already up
            if app_state.pipeline and _HAS_PIPELINE:
                app_state.pipeline.update_hardware(fpga=fpga, bias=app_state.bias)
            self.log_message.emit(f"FPGA: open ({cfg.get('driver','?')})")
            self.device_connected.emit("fpga", True)
            self.startup_status.emit("fpga", True, cfg.get('driver', 'connected'))
        except Exception as e:
            dev_err = self._classify_and_emit(e, "fpga")
            self.device_connected.emit("fpga", False)
            self.startup_status.emit("fpga", False, dev_err.short_message)
            log.error(f"FpgaService FPGA init: {e}")
            return

        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                try:
                    status = fpga.get_status()
                    self.status_update.emit(status)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    from hardware.fpga.base import FpgaStatus
                    self.status_update.emit(FpgaStatus(error=str(e)))
                    if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                        self.device_connected.emit("fpga", False)
                        self.error.emit(
                            f"FPGA: device went offline after "
                            f"{consecutive_errors} errors"
                            " — reconnecting automatically…")
                        def _do_reconnect(fpga=fpga):
                            try:
                                fpga.stop()
                                fpga.close()
                            except Exception:
                                log.debug("FPGA: cleanup failed before reconnect",
                                          exc_info=True)
                            fpga.open()
                            fpga.start()
                        if not self._reconnect_loop("fpga", _do_reconnect, "fpga"):
                            return
                        consecutive_errors = 0
                self._stop_event.wait(timeout=self._FPGA_POLL_S)
        except Exception as e:
            log.error("[fpga] Poll thread died unexpectedly: %s", e, exc_info=True)
            self.error.emit(f"FPGA: poll thread crashed — {e}")
            self.device_connected.emit("fpga", False)

    # ── Demo ──────────────────────────────────────────────────────────

    def _run_demo_fpga(self, cfg: dict):
        """FPGA demo thread — uses simulated driver, overrides config."""
        from hardware.fpga.simulated import SimulatedFpga
        try:
            fpga = SimulatedFpga(cfg)
            fpga.open()
            fpga.start()
            app_state.fpga = fpga
            if app_state.pipeline and _HAS_PIPELINE:
                app_state.pipeline.update_hardware(fpga=fpga, bias=app_state.bias)
            self.log_message.emit("FPGA: demo mode (simulated)")
            self.device_connected.emit("fpga", True)
            self.startup_status.emit("fpga", True, "Simulated")
        except Exception as e:
            dev_err = self._classify_and_emit(e, "fpga")
            self.startup_status.emit("fpga", False, dev_err.short_message)
            return
        while not self._stop_event.is_set():
            try:
                from hardware.fpga.base import FpgaStatus
                self.status_update.emit(fpga.get_status())
            except Exception as e:
                from hardware.fpga.base import FpgaStatus
                self.status_update.emit(FpgaStatus(error=str(e)))
            self._stop_event.wait(timeout=self._FPGA_POLL_S)

    # ── Control surface ───────────────────────────────────────────────

    def fpga_set_frequency(self, hz: float) -> None:
        """Set FPGA modulation frequency in Hz."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_frequency, hz)

    def fpga_set_duty_cycle(self, fraction: float) -> None:
        """Set FPGA duty cycle (0.0–1.0)."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_duty_cycle, fraction)

    def fpga_start(self) -> None:
        """Start FPGA modulation output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.start)

    def fpga_stop(self) -> None:
        """Stop FPGA modulation output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.stop)

    def fpga_set_stimulus(self, on: bool) -> None:
        """Enable or disable FPGA stimulus output."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_stimulus, on)
