"""
hardware/services/fpga_service.py

FPGA device service — owns FPGA lifecycle, poll loop, and control surface.
"""

from __future__ import annotations

import logging
import threading
import time

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
                    _t0 = time.time()
                    status = fpga.get_status()
                    self._emit_heartbeat("fpga", time.time() - _t0)
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

    def fpga_set_trigger_mode(self, mode: str) -> None:
        """Set FPGA trigger mode (continuous / single-shot)."""
        fpga = app_state.fpga
        if fpga:
            self._dispatch(fpga.set_trigger_mode, mode)

    # ── EZ-500 extended FPGA controls ─────────────────────────────────
    # These wrap NI sbRIO-9637 firmware registers.  Each method uses
    # hasattr() so that the simulated driver (which lacks these
    # methods) is a safe no-op.

    def fpga_set_period_us(self, period_us: float) -> None:
        """Set stimulus period directly in microseconds."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_period_us'):
            self._dispatch(fpga.set_period_us, period_us)

    def fpga_set_voltage(self, volts: float) -> None:
        """Set main voltage output (−16 V to +16 V)."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_voltage'):
            self._dispatch(fpga.set_voltage, volts)

    def fpga_set_aux_voltage(self, volts: float) -> None:
        """Set auxiliary voltage output (−16 V to +16 V)."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_aux_voltage'):
            self._dispatch(fpga.set_aux_voltage, volts)

    def fpga_disable_voltage(self) -> None:
        """Disable both voltage outputs."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'disable_voltage'):
            self._dispatch(fpga.disable_voltage)

    def fpga_set_voltage_limits(self, vo_lim: float, va_lim: float) -> None:
        """Set voltage output limits for main and aux channels."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_voltage_limits'):
            self._dispatch(fpga.set_voltage_limits, vo_lim, va_lim)

    def fpga_set_led_timing(self, phase: int, time_on: int) -> None:
        """Set LED illumination CW timing (phase offset, on-duration)."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_led_timing'):
            self._dispatch(fpga.set_led_timing, phase, time_on)

    def fpga_set_led_pulsed(self, phase: int, pulse_time: int) -> None:
        """Set LED pulsed illumination timing."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_led_pulsed'):
            self._dispatch(fpga.set_led_pulsed, phase, pulse_time)

    def fpga_set_device_phase(self, phase: int, phase2: int = 0,
                               use_phase2: bool = False) -> None:
        """Set device stimulus phase offset(s)."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_device_phase'):
            self._dispatch(fpga.set_device_phase, phase, phase2, use_phase2)

    def fpga_set_exposure_time(self, ticks: int) -> None:
        """Set camera exposure timing register on the FPGA."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_exposure_time'):
            self._dispatch(fpga.set_exposure_time, ticks)

    def fpga_set_synch(self, enabled: bool, phase: int = 0) -> None:
        """Enable/disable external clock synchronisation."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_synch'):
            self._dispatch(fpga.set_synch, enabled, phase)

    def fpga_set_sample_rate(self, rate: int) -> None:
        """Set analog input sample rate divisor."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_sample_rate'):
            self._dispatch(fpga.set_sample_rate, rate)

    def fpga_set_trigger_direction(self, output: bool) -> None:
        """Set trigger BNC direction (True = output)."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_trigger_direction'):
            self._dispatch(fpga.set_trigger_direction, output)

    def fpga_set_high_range(self, enabled: bool) -> None:
        """Enable high voltage range on analog outputs."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_high_range'):
            self._dispatch(fpga.set_high_range, enabled)

    def fpga_set_ir_frame_trigger(self, enabled: bool) -> None:
        """Enable/disable IR camera frame trigger output."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_ir_frame_trigger'):
            self._dispatch(fpga.set_ir_frame_trigger, enabled)

    def fpga_set_event_source(self, source: int) -> None:
        """Set event trigger source."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_event_source'):
            self._dispatch(fpga.set_event_source, source)

    def fpga_set_event_phase(self, phase_us: int) -> None:
        """Set event trigger phase delay in microseconds."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'set_event_phase'):
            self._dispatch(fpga.set_event_phase, phase_us)

    def fpga_read_analog_inputs(self) -> dict:
        """Read all four analog input channels (blocking).

        Returns dict with keys 'ai0'–'ai3', or empty dict if unavailable.
        """
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'read_analog_inputs'):
            try:
                return fpga.read_analog_inputs()
            except Exception as exc:
                log.warning("fpga_read_analog_inputs failed: %s", exc)
        return {}

    def fpga_trigger_voltage_readback(self) -> None:
        """Pulse GetV to trigger analog voltage readback on FPGA."""
        fpga = app_state.fpga
        if fpga and hasattr(fpga, 'trigger_voltage_readback'):
            self._dispatch(fpga.trigger_voltage_readback)
