"""
acquisition/phase_handlers.py  —  Phase execution handlers

Each handler knows how to execute one phase type from a Recipe.
Handlers are pure logic — they read the phase config, call hardware
APIs, and return a PhaseResult.  They do NOT own threads or UI;
the RecipeExecutor (commit 3) orchestrates sequencing and signals.

Handler protocol
----------------
    execute(config, ctx) -> PhaseResult
    validate(checks, config, ctx) -> list[CheckResult]

ExecutionContext bundles the live references a handler needs:
app_state, pipeline, progress callback, abort flag, etc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Protocol

log = logging.getLogger(__name__)


# ================================================================== #
#  Result types                                                        #
# ================================================================== #

class PhaseStatus(str, Enum):
    SUCCESS  = "success"
    WARNING  = "warning"
    FAILED   = "failed"
    SKIPPED  = "skipped"
    ABORTED  = "aborted"


@dataclass
class CheckResult:
    """Result of a single post-phase validation check."""
    check_id:  str
    passed:    bool
    message:   str = ""
    value:     Any = None          # observed metric value


@dataclass
class PhaseResult:
    """Outcome of executing one recipe phase."""
    phase_type: str
    status:     str = PhaseStatus.SUCCESS.value
    message:    str = ""
    duration_s: float = 0.0
    checks:     List[CheckResult] = field(default_factory=list)
    data:       Dict[str, Any] = field(default_factory=dict)


# ================================================================== #
#  Execution context                                                   #
# ================================================================== #

@dataclass
class ExecutionContext:
    """Shared state passed to every phase handler.

    Holds live hardware references and session-level state that
    accumulates as phases execute.
    """
    app_state:  Any = None         # ApplicationState
    pipeline:   Any = None         # AcquisitionPipeline (set by HardwareSetup)
    on_progress: Optional[Callable] = None   # (message: str) -> None
    abort_requested: bool = False

    # Accumulated during execution
    acquisition_result: Any = None         # AcquisitionResult (set by Acquisition)
    analysis_result:    Any = None         # AnalysisResult (set by Analysis)
    session:            Any = None         # Session (set by Output)

    def check_abort(self) -> None:
        """Raise AbortError if the user has requested cancellation."""
        if self.abort_requested:
            raise AbortError("Execution aborted by user")

    def report(self, message: str) -> None:
        """Send a progress message to the UI."""
        if self.on_progress:
            try:
                self.on_progress(message)
            except Exception:
                pass


class AbortError(Exception):
    """Raised when the user cancels a recipe execution."""
    pass


# ================================================================== #
#  Handler protocol                                                    #
# ================================================================== #

class PhaseHandler(Protocol):
    """Protocol for phase execution handlers."""

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult: ...


# ================================================================== #
#  Handler registry                                                    #
# ================================================================== #

_HANDLER_REGISTRY: Dict[str, PhaseHandler] = {}


def get_handler(phase_type: str) -> Optional[PhaseHandler]:
    """Look up the handler for a given phase type."""
    return _HANDLER_REGISTRY.get(phase_type)


# ================================================================== #
#  1. Preparation handler                                              #
# ================================================================== #

class PreparationHandler:
    """Verify that required hardware is connected and responsive.

    Config keys
    -----------
    checks : list[str]
        Check IDs to run: "camera_connected", "fpga_responsive",
        "stage_homed", "tec_connected", "bias_connected".
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        ctx.report("Checking hardware readiness...")
        checks = config.get("checks", [])
        results = []
        all_pass = True

        for check_id in checks:
            ctx.check_abort()
            passed, msg = self._run_check(check_id, ctx)
            results.append(CheckResult(
                check_id=check_id, passed=passed, message=msg))
            if not passed:
                all_pass = False

        status = PhaseStatus.SUCCESS if all_pass else PhaseStatus.FAILED
        return PhaseResult(
            phase_type="preparation",
            status=status.value,
            message="" if all_pass else "Hardware check failed",
            duration_s=time.monotonic() - t0,
            checks=results,
        )

    @staticmethod
    def _run_check(check_id: str, ctx: ExecutionContext) -> tuple:
        """Run a single preparation check. Returns (passed, message)."""
        state = ctx.app_state
        if state is None:
            return False, "No application state available"

        if check_id == "camera_connected":
            cam = getattr(state, "cam", None)
            if cam is None:
                return False, "Camera not connected"
            return True, "Camera OK"

        if check_id == "fpga_responsive":
            fpga = getattr(state, "fpga", None)
            if fpga is None:
                return False, "FPGA not connected"
            try:
                fpga.get_status()
                return True, "FPGA OK"
            except Exception as e:
                return False, f"FPGA error: {e}"

        if check_id == "stage_homed":
            stage = getattr(state, "stage", None)
            if stage is None:
                return False, "Stage not connected"
            try:
                status = stage.get_status()
                if getattr(status, "homed", False):
                    return True, "Stage homed"
                return False, "Stage not homed"
            except Exception as e:
                return False, f"Stage error: {e}"

        if check_id == "tec_connected":
            tecs = getattr(state, "tecs", [])
            if not tecs:
                return False, "TEC not connected"
            return True, "TEC OK"

        if check_id == "bias_connected":
            bias = getattr(state, "bias", None)
            if bias is None:
                return False, "Bias source not connected"
            return True, "Bias OK"

        return False, f"Unknown check: {check_id}"


_HANDLER_REGISTRY["preparation"] = PreparationHandler()


# ================================================================== #
#  2. Hardware Setup handler                                           #
# ================================================================== #

class HardwareSetupHandler:
    """Configure all hardware devices from the recipe's phase config.

    Config keys
    -----------
    camera : dict
        exposure_us, gain_db, n_frames, roi
    fpga : dict
        frequency_hz, duty_cycle, waveform, trigger_mode
    bias : dict
        enabled, voltage_v, current_a, compliance_ma
    tec : dict
        enabled, setpoint_c
    modality : str
        "thermoreflectance" | "ir_lockin" | etc.
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        ctx.report("Configuring hardware...")
        state = ctx.app_state
        errors = []

        # Camera
        cam_cfg = config.get("camera", {})
        if cam_cfg:
            ctx.check_abort()
            errors.extend(self._setup_camera(cam_cfg, state, ctx))

        # FPGA
        fpga_cfg = config.get("fpga", {})
        if fpga_cfg:
            ctx.check_abort()
            errors.extend(self._setup_fpga(fpga_cfg, state, ctx))

        # Bias
        bias_cfg = config.get("bias", {})
        if bias_cfg and bias_cfg.get("enabled"):
            ctx.check_abort()
            errors.extend(self._setup_bias(bias_cfg, state, ctx))

        # TEC
        tec_cfg = config.get("tec", {})
        if tec_cfg and tec_cfg.get("enabled"):
            ctx.check_abort()
            errors.extend(self._setup_tec(tec_cfg, state, ctx))

        # Modality
        modality = config.get("modality")
        if modality:
            try:
                state.active_modality = modality
            except Exception as e:
                errors.append(f"Modality: {e}")

        if errors:
            return PhaseResult(
                phase_type="hardware_setup",
                status=PhaseStatus.WARNING.value,
                message="; ".join(errors),
                duration_s=time.monotonic() - t0,
            )

        ctx.report("Hardware configured")
        return PhaseResult(
            phase_type="hardware_setup",
            status=PhaseStatus.SUCCESS.value,
            duration_s=time.monotonic() - t0,
        )

    @staticmethod
    def _setup_camera(cfg: dict, state, ctx) -> List[str]:
        errors = []
        cam = getattr(state, "cam", None)
        if cam is None:
            return ["Camera not available"]

        ctx.report("Setting camera parameters...")
        if "exposure_us" in cfg:
            try:
                cam.set_exposure(cfg["exposure_us"])
            except Exception as e:
                errors.append(f"Exposure: {e}")
        if "gain_db" in cfg:
            try:
                cam.set_gain(cfg["gain_db"])
            except Exception as e:
                errors.append(f"Gain: {e}")
        return errors

    @staticmethod
    def _setup_fpga(cfg: dict, state, ctx) -> List[str]:
        errors = []
        fpga = getattr(state, "fpga", None)
        if fpga is None:
            return ["FPGA not available"]

        ctx.report("Setting FPGA parameters...")
        if "frequency_hz" in cfg:
            try:
                fpga.set_frequency(cfg["frequency_hz"])
            except Exception as e:
                errors.append(f"Frequency: {e}")
        if "duty_cycle" in cfg:
            try:
                fpga.set_duty_cycle(cfg["duty_cycle"])
            except Exception as e:
                errors.append(f"Duty cycle: {e}")
        if "trigger_mode" in cfg:
            try:
                fpga.set_trigger_mode(cfg["trigger_mode"])
            except Exception as e:
                errors.append(f"Trigger mode: {e}")
        return errors

    @staticmethod
    def _setup_bias(cfg: dict, state, ctx) -> List[str]:
        errors = []
        bias = getattr(state, "bias", None)
        if bias is None:
            return ["Bias source not available"]

        ctx.report("Configuring bias source...")
        try:
            if "voltage_v" in cfg:
                bias.set_mode("voltage")
                bias.set_level(cfg["voltage_v"])
            if "compliance_ma" in cfg:
                bias.set_compliance(cfg["compliance_ma"] / 1000.0)
            elif "current_a" in cfg:
                bias.set_compliance(cfg["current_a"])
        except Exception as e:
            errors.append(f"Bias: {e}")
        return errors

    @staticmethod
    def _setup_tec(cfg: dict, state, ctx) -> List[str]:
        errors = []
        tecs = getattr(state, "tecs", [])
        if not tecs:
            return ["TEC not available"]

        ctx.report("Setting TEC target...")
        try:
            tecs[0].enable()
            if "setpoint_c" in cfg:
                tecs[0].set_target(cfg["setpoint_c"])
        except Exception as e:
            errors.append(f"TEC: {e}")
        return errors


_HANDLER_REGISTRY["hardware_setup"] = HardwareSetupHandler()


# ================================================================== #
#  3. Stabilization handler                                            #
# ================================================================== #

class StabilizationHandler:
    """Wait for thermal and electrical equilibrium.

    Config keys
    -----------
    tec_settle : dict
        tolerance_c, duration_s, timeout_s
    bias_settle : dict
        delay_s
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        state = ctx.app_state

        # TEC stabilization
        tec_settle = config.get("tec_settle")
        if tec_settle:
            ctx.report("Waiting for TEC to stabilize...")
            ok, msg = self._wait_tec(tec_settle, state, ctx)
            if not ok:
                return PhaseResult(
                    phase_type="stabilization",
                    status=PhaseStatus.FAILED.value,
                    message=msg,
                    duration_s=time.monotonic() - t0,
                )

        # Bias settling delay
        bias_settle = config.get("bias_settle")
        if bias_settle:
            delay = bias_settle.get("delay_s", 2.0)
            ctx.report(f"Bias settling ({delay:.1f}s)...")
            self._interruptible_sleep(delay, ctx)

        ctx.report("System stabilized")
        return PhaseResult(
            phase_type="stabilization",
            status=PhaseStatus.SUCCESS.value,
            duration_s=time.monotonic() - t0,
        )

    @staticmethod
    def _wait_tec(cfg: dict, state, ctx) -> tuple:
        """Poll TEC until stable or timeout. Returns (success, message)."""
        tolerance = cfg.get("tolerance_c", 0.1)
        stable_duration = cfg.get("duration_s", 10)
        timeout = cfg.get("timeout_s", 120)

        tecs = getattr(state, "tecs", [])
        if not tecs:
            return False, "TEC not connected"

        start = time.monotonic()
        stable_since = None

        while (time.monotonic() - start) < timeout:
            ctx.check_abort()
            try:
                status = tecs[0].get_status()
                actual = getattr(status, "actual_temp", None)
                target = getattr(status, "target_temp", None)
                if actual is not None and target is not None:
                    if abs(actual - target) <= tolerance:
                        if stable_since is None:
                            stable_since = time.monotonic()
                        elif (time.monotonic() - stable_since) >= stable_duration:
                            return True, f"TEC stable at {actual:.1f}°C"
                    else:
                        stable_since = None
                        elapsed = time.monotonic() - start
                        ctx.report(
                            f"TEC: {actual:.1f}°C → {target:.1f}°C "
                            f"({elapsed:.0f}s / {timeout:.0f}s)")
            except Exception as e:
                log.debug("TEC poll error: %s", e)

            time.sleep(1.0)

        return False, f"TEC did not stabilize within {timeout}s"

    @staticmethod
    def _interruptible_sleep(seconds: float, ctx: ExecutionContext) -> None:
        """Sleep in small increments, checking for abort."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ctx.check_abort()
            remaining = end - time.monotonic()
            time.sleep(min(0.5, remaining))


_HANDLER_REGISTRY["stabilization"] = StabilizationHandler()


# ================================================================== #
#  4. Acquisition handler                                              #
# ================================================================== #

class AcquisitionHandler:
    """Execute the data capture.

    Config keys
    -----------
    type : str
        "single_point" | "grid" | "transient" | "movie"
    inter_phase_delay_s : float
        Settling time between cold/hot phases.
    grid : dict
        Grid scan parameters (for type="grid").
    cube : dict
        Transient/movie parameters (for type="transient"|"movie").
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        acq_type = config.get("type", "single_point")
        ctx.report(f"Starting {acq_type} acquisition...")

        state = ctx.app_state
        cam = getattr(state, "cam", None)
        fpga = getattr(state, "fpga", None)
        bias = getattr(state, "bias", None)

        if cam is None:
            return PhaseResult(
                phase_type="acquisition",
                status=PhaseStatus.FAILED.value,
                message="Camera not available",
                duration_s=time.monotonic() - t0,
            )

        # Get n_frames from hardware_setup phase config via context
        # (the pipeline reads it from its own params)
        hw_config = {}
        # The recipe is not directly available here; n_frames comes
        # from the pipeline configuration set during hardware_setup
        n_frames = config.get("n_frames", 16)
        delay = config.get("inter_phase_delay_s", 0.1)

        try:
            if acq_type == "single_point":
                result = self._acquire_single(cam, fpga, bias, n_frames, delay, ctx)
            elif acq_type == "grid":
                result = self._acquire_grid(config.get("grid", {}), state, ctx)
            elif acq_type in ("transient", "movie"):
                result = self._acquire_cube(config.get("cube", {}), state, ctx)
            else:
                return PhaseResult(
                    phase_type="acquisition",
                    status=PhaseStatus.FAILED.value,
                    message=f"Unknown acquisition type: {acq_type}",
                    duration_s=time.monotonic() - t0,
                )
        except AbortError:
            raise
        except Exception as e:
            log.exception("Acquisition failed")
            return PhaseResult(
                phase_type="acquisition",
                status=PhaseStatus.FAILED.value,
                message=str(e),
                duration_s=time.monotonic() - t0,
            )

        ctx.acquisition_result = result
        ctx.report("Acquisition complete")
        return PhaseResult(
            phase_type="acquisition",
            status=PhaseStatus.SUCCESS.value,
            duration_s=time.monotonic() - t0,
            data={"n_frames": getattr(result, "n_frames", 0),
                  "snr_db": getattr(result, "snr_db", None)},
        )

    @staticmethod
    def _acquire_single(cam, fpga, bias, n_frames, delay, ctx):
        """Run a single-point acquisition via the pipeline."""
        from acquisition.pipeline import AcquisitionPipeline
        pipeline = AcquisitionPipeline(cam, fpga=fpga, bias=bias)
        ctx.pipeline = pipeline

        def _on_progress(progress):
            ctx.check_abort()
            ctx.report(
                f"Acquiring: {progress.phase} "
                f"{progress.frames_done}/{progress.frames_total}")

        pipeline.on_progress = _on_progress
        result = pipeline.run(n_frames=n_frames,
                              inter_phase_delay=delay)
        return result

    @staticmethod
    def _acquire_grid(grid_cfg, state, ctx):
        """Run a grid scan. Delegates to the scan module."""
        ctx.report("Grid scan in progress...")
        # Grid scan is orchestrated by scan.py which manages
        # stage movement + repeated single-point acquisitions.
        # Full integration deferred to UI wiring.
        raise NotImplementedError(
            "Grid scan execution requires scan module integration")

    @staticmethod
    def _acquire_cube(cube_cfg, state, ctx):
        """Run a transient or movie acquisition."""
        ctx.report("Transient/movie capture in progress...")
        # Cube acquisitions are orchestrated by transient_pipeline.py
        # or movie_pipeline.py. Full integration deferred.
        raise NotImplementedError(
            "Cube acquisition requires transient/movie pipeline integration")


_HANDLER_REGISTRY["acquisition"] = AcquisitionHandler()


# ================================================================== #
#  5. Validation handler                                               #
# ================================================================== #

class ValidationHandler:
    """Verify data quality after acquisition.

    Config keys
    -----------
    checks : list[str]
        Check IDs: "snr_minimum", "no_saturation", "frame_count".
    snr_minimum_db : float
        Minimum acceptable SNR (default 10).
    saturation_threshold : float
        Max fraction of saturated pixels (default 0.05).
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        ctx.report("Validating acquisition quality...")

        result = ctx.acquisition_result
        if result is None:
            return PhaseResult(
                phase_type="validation",
                status=PhaseStatus.SKIPPED.value,
                message="No acquisition result to validate",
                duration_s=time.monotonic() - t0,
            )

        checks_to_run = config.get("checks", [])
        check_results = []

        for check_id in checks_to_run:
            ctx.check_abort()
            cr = self._run_check(check_id, config, result)
            check_results.append(cr)

        all_pass = all(cr.passed for cr in check_results)
        status = PhaseStatus.SUCCESS if all_pass else PhaseStatus.WARNING
        return PhaseResult(
            phase_type="validation",
            status=status.value,
            message="" if all_pass else "Some quality checks did not pass",
            duration_s=time.monotonic() - t0,
            checks=check_results,
        )

    @staticmethod
    def _run_check(check_id: str, config: dict, result) -> CheckResult:
        if check_id == "snr_minimum":
            threshold = config.get("snr_minimum_db", 10)
            snr = getattr(result, "snr_db", None)
            if snr is None:
                return CheckResult(
                    check_id=check_id, passed=False,
                    message="SNR not available", value=None)
            passed = snr >= threshold
            return CheckResult(
                check_id=check_id, passed=passed,
                message=f"SNR {snr:.1f} dB (min {threshold})",
                value=snr)

        if check_id == "no_saturation":
            threshold = config.get("saturation_threshold", 0.05)
            frac = getattr(result, "dark_pixel_fraction", 0)
            # dark_pixel_fraction is actually saturated fraction in context
            passed = frac < threshold
            return CheckResult(
                check_id=check_id, passed=passed,
                message=f"Saturation {frac:.1%} (max {threshold:.0%})",
                value=frac)

        if check_id == "frame_count":
            expected = getattr(result, "n_frames", 0)
            cold = getattr(result, "cold_captured", 0)
            hot = getattr(result, "hot_captured", 0)
            passed = cold >= expected and hot >= expected
            return CheckResult(
                check_id=check_id, passed=passed,
                message=f"Frames: {cold}+{hot} (expected {expected}+{expected})",
                value={"cold": cold, "hot": hot, "expected": expected})

        return CheckResult(
            check_id=check_id, passed=False,
            message=f"Unknown check: {check_id}")


_HANDLER_REGISTRY["validation"] = ValidationHandler()


# ================================================================== #
#  6. Analysis handler                                                 #
# ================================================================== #

class AnalysisHandler:
    """Run hotspot detection and pass/fail verdict.

    Config keys
    -----------
    threshold_k : float
    fail_hotspot_count : int
    fail_peak_k : float
    fail_area_fraction : float
    warn_hotspot_count : int
    warn_peak_k : float
    warn_area_fraction : float
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        ctx.report("Running analysis...")

        acq_result = ctx.acquisition_result
        if acq_result is None:
            return PhaseResult(
                phase_type="analysis",
                status=PhaseStatus.SKIPPED.value,
                message="No acquisition result to analyse",
                duration_s=time.monotonic() - t0,
            )

        drr = getattr(acq_result, "delta_r_over_r", None)
        if drr is None:
            return PhaseResult(
                phase_type="analysis",
                status=PhaseStatus.FAILED.value,
                message="No ΔR/R data available",
                duration_s=time.monotonic() - t0,
            )

        try:
            from acquisition.analysis import Analysis
            analysis = Analysis(config)
            result = analysis.run(drr, calibration=getattr(
                ctx.app_state, "active_calibration", None))
            ctx.analysis_result = result

            verdict = getattr(result, "verdict", "unknown")
            ctx.report(f"Analysis complete — verdict: {verdict}")
            return PhaseResult(
                phase_type="analysis",
                status=PhaseStatus.SUCCESS.value,
                duration_s=time.monotonic() - t0,
                data={"verdict": verdict},
            )
        except Exception as e:
            log.exception("Analysis failed")
            return PhaseResult(
                phase_type="analysis",
                status=PhaseStatus.FAILED.value,
                message=str(e),
                duration_s=time.monotonic() - t0,
            )


_HANDLER_REGISTRY["analysis"] = AnalysisHandler()


# ================================================================== #
#  7. Output handler                                                   #
# ================================================================== #

class OutputHandler:
    """Save session, export data, generate reports.

    Config keys
    -----------
    auto_save : bool
        Automatically save the session (default True).
    export_format : str, optional
        Export format (deferred to UI integration).
    generate_report : bool, optional
        Auto-generate report (deferred to UI integration).
    """

    def execute(self, config: dict, ctx: ExecutionContext) -> PhaseResult:
        t0 = time.monotonic()
        auto_save = config.get("auto_save", True)

        if not auto_save:
            return PhaseResult(
                phase_type="output",
                status=PhaseStatus.SKIPPED.value,
                message="Auto-save disabled",
                duration_s=time.monotonic() - t0,
            )

        acq_result = ctx.acquisition_result
        if acq_result is None:
            return PhaseResult(
                phase_type="output",
                status=PhaseStatus.SKIPPED.value,
                message="No acquisition result to save",
                duration_s=time.monotonic() - t0,
            )

        ctx.report("Saving session...")
        try:
            from acquisition.session import Session
            session = Session.from_result(
                acq_result,
                imaging_mode=getattr(
                    ctx.app_state, "active_modality", "thermoreflectance"),
            )

            # Attach analysis if available
            if ctx.analysis_result is not None:
                session.meta.analysis_result = ctx.analysis_result.to_dict()

            # Save to default sessions directory
            import config as cfg_mod
            sessions_dir = cfg_mod.get_pref(
                "paths.sessions_dir",
                str(cfg_mod.DEFAULT_SESSIONS_DIR))
            path = session.save(sessions_dir)

            ctx.session = session
            ctx.report(f"Session saved: {path}")
            return PhaseResult(
                phase_type="output",
                status=PhaseStatus.SUCCESS.value,
                message=f"Saved to {path}",
                duration_s=time.monotonic() - t0,
                data={"path": path},
            )
        except Exception as e:
            log.exception("Session save failed")
            return PhaseResult(
                phase_type="output",
                status=PhaseStatus.FAILED.value,
                message=str(e),
                duration_s=time.monotonic() - t0,
            )


_HANDLER_REGISTRY["output"] = OutputHandler()
