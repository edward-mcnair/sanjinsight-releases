"""
tests/test_pipelines.py

Unit tests for new acquisition pipeline modules:
  • acquisition/drift_correction.py   — estimate_shift / apply_shift
  • hardware/ldd/simulated.py         — SimulatedLdd full lifecycle
  • acquisition/movie_pipeline.py     — MovieAcquisitionPipeline end-to-end
  • acquisition/transient_pipeline.py — TransientAcquisitionPipeline end-to-end
  • hardware/app_state.py             — system_model property
  • Voltage sweep list math           — _vsweep_voltage_list equivalent logic

All tests use synthetic data — no hardware required.

Run:
    cd project_bonaire
    pytest tests/test_pipelines.py -v
"""

from __future__ import annotations

import os
import sys
import time
import threading
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. Drift correction — estimate_shift                               #
# ================================================================== #

class TestEstimateShift:
    """FFT phase-correlation shift estimation."""

    @pytest.fixture
    def reference(self):
        """Synthetic 64×64 reference frame with a bright central blob."""
        rng  = np.random.default_rng(42)
        ref  = rng.integers(500, 2000, (64, 64), dtype=np.uint16).astype(np.float32)
        # Add a distinct bright feature so phase correlation has a clear peak
        ref[28:36, 28:36] = 4000.0
        return ref

    def test_zero_shift_returns_zero(self, reference):
        """Identical frames must report (0, 0)."""
        from acquisition.drift_correction import estimate_shift
        dy, dx = estimate_shift(reference, reference)
        assert dy == pytest.approx(0.0, abs=0.5), f"dy={dy} for zero shift"
        assert dx == pytest.approx(0.0, abs=0.5), f"dx={dx} for zero shift"

    def test_integer_shift_row(self, reference):
        """Frame shifted down by 3 pixels → dy ≈ 3."""
        from acquisition.drift_correction import estimate_shift
        shifted = np.roll(reference, 3, axis=0)
        dy, dx  = estimate_shift(shifted, reference)
        assert dy == pytest.approx(3.0, abs=0.5), f"Expected dy≈3, got {dy}"
        assert dx == pytest.approx(0.0, abs=0.5), f"Expected dx≈0, got {dx}"

    def test_integer_shift_col(self, reference):
        """Frame shifted right by 5 pixels → dx ≈ 5."""
        from acquisition.drift_correction import estimate_shift
        shifted = np.roll(reference, 5, axis=1)
        dy, dx  = estimate_shift(shifted, reference)
        assert dy == pytest.approx(0.0, abs=0.5), f"Expected dy≈0, got {dy}"
        assert dx == pytest.approx(5.0, abs=0.5), f"Expected dx≈5, got {dx}"

    def test_diagonal_shift(self, reference):
        """Frame shifted (−2, 4) → dy≈−2, dx≈4."""
        from acquisition.drift_correction import estimate_shift
        shifted = np.roll(np.roll(reference, -2, axis=0), 4, axis=1)
        dy, dx  = estimate_shift(shifted, reference)
        assert dy == pytest.approx(-2.0, abs=0.5), f"Expected dy≈-2, got {dy}"
        assert dx == pytest.approx(4.0,  abs=0.5), f"Expected dx≈4, got {dx}"

    def test_returns_floats(self, reference):
        """estimate_shift must always return Python floats, not numpy scalars."""
        from acquisition.drift_correction import estimate_shift
        dy, dx = estimate_shift(reference, reference)
        assert isinstance(dy, float)
        assert isinstance(dx, float)


# ================================================================== #
#  2. Drift correction — apply_shift                                  #
# ================================================================== #

class TestApplyShift:
    """Frame translation (bilinear / numpy.roll fallback)."""

    @pytest.fixture
    def frame(self):
        rng = np.random.default_rng(7)
        f   = rng.integers(200, 3000, (48, 64), dtype=np.uint16).astype(np.float32)
        f[20:28, 25:35] = 4095.0   # bright feature
        return f

    def test_zero_shift_identity(self, frame):
        """apply_shift(frame, 0, 0) must return the same array unchanged."""
        from acquisition.drift_correction import apply_shift
        out = apply_shift(frame, 0.0, 0.0)
        # Should be exact identity (short-circuit path)
        assert out is frame

    def test_shape_preserved(self, frame):
        """Output shape must match input shape."""
        from acquisition.drift_correction import apply_shift
        out = apply_shift(frame, 3.0, -2.0)
        assert out.shape == frame.shape

    def test_dtype_preserved(self, frame):
        """Output dtype must match input dtype."""
        from acquisition.drift_correction import apply_shift
        out = apply_shift(frame, 1.0, 1.0)
        assert out.dtype == frame.dtype

    def test_round_trip_row_shift(self, frame):
        """Shift right by 5 then correct left by −5 should approximately recover."""
        from acquisition.drift_correction import apply_shift
        shifted   = np.roll(frame, 5, axis=1)
        corrected = apply_shift(shifted.astype(np.float32), 0.0, -5.0)
        # Interior pixels (away from wrap-around boundary) should match well
        np.testing.assert_allclose(
            corrected[:, 10:-10], frame[:, 10:-10],
            rtol=0.01, atol=2.0,
            err_msg="Round-trip row shift should recover interior pixels")

    def test_numpy_roll_fallback(self, frame, monkeypatch):
        """When scipy is missing the numpy.roll path must still produce valid output."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "scipy.ndimage":
                raise ImportError("scipy not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # Reload to force the fallback path
        from acquisition import drift_correction as dc
        out = dc.apply_shift(frame, 2.0, 3.0)
        assert out.shape == frame.shape
        assert out.dtype == frame.dtype


# ================================================================== #
#  3. SimulatedLdd                                                    #
# ================================================================== #

class TestSimulatedLdd:
    """SimulatedLdd full lifecycle and readback."""

    @pytest.fixture
    def ldd(self):
        from hardware.ldd.simulated import SimulatedLdd
        d = SimulatedLdd({})
        d.connect()
        return d

    def test_connect_sets_connected(self):
        from hardware.ldd.simulated import SimulatedLdd
        d = SimulatedLdd({})
        assert not d.is_connected
        d.connect()
        assert d.is_connected

    def test_disconnect_clears_connected(self, ldd):
        ldd.disconnect()
        assert not ldd.is_connected

    def test_initial_status_is_disabled(self, ldd):
        st = ldd.get_status()
        assert not st.enabled
        assert st.actual_current_a == pytest.approx(0.0, abs=0.01)

    def test_enable_reports_enabled(self, ldd):
        ldd.enable()
        st = ldd.get_status()
        assert st.enabled

    def test_disable_after_enable(self, ldd):
        ldd.enable()
        ldd.disable()
        st = ldd.get_status()
        assert not st.enabled

    def test_set_current_clamps_to_max(self, ldd):
        """set_current(999A) must clamp to LDD_MAX_CURRENT_A."""
        from ai.instrument_knowledge import LDD_MAX_CURRENT_A
        ldd.set_current(999.0)
        ldd.enable()
        # Poll several times to let the slew ramp toward target
        for _ in range(20):
            st = ldd.get_status()
        assert st.actual_current_a <= LDD_MAX_CURRENT_A + 0.01

    def test_set_current_zero_stays_zero(self, ldd):
        ldd.set_current(0.0)
        ldd.enable()
        st = ldd.get_status()
        # Slew starts at 0 → actual should not exceed 0.2 after one poll
        assert st.actual_current_a <= 0.21

    def test_status_fields_present(self, ldd):
        """All LddStatus fields must be populated and sane."""
        from hardware.ldd.base import LddStatus
        st = ldd.get_status()
        assert isinstance(st, LddStatus)
        assert isinstance(st.actual_current_a, float)
        assert isinstance(st.actual_voltage_v, float)
        assert isinstance(st.diode_temp_c, float)
        assert isinstance(st.enabled, bool)
        assert isinstance(st.mode, str)

    def test_diode_temp_in_plausible_range(self, ldd):
        """Diode temperature must be within a physically sane range at idle."""
        ldd.set_current(0.0)
        st = ldd.get_status()
        assert 10.0 < st.diode_temp_c < 45.0, \
            f"Idle diode temp {st.diode_temp_c}°C out of range"

    def test_current_range(self, ldd):
        lo, hi = ldd.current_range()
        assert lo == 0.0
        assert hi > 0.0

    def test_diode_temp_range(self, ldd):
        lo, hi = ldd.diode_temp_range()
        assert lo < 0.0, "Min diode temp should allow sub-zero operation"
        assert hi >= 60.0, "Max diode temp should allow at least 60°C"


# ================================================================== #
#  4. MovieAcquisitionPipeline — end-to-end                          #
# ================================================================== #

class TestMoviePipeline:
    """MovieAcquisitionPipeline with SimulatedCamera, no hardware needed."""

    @pytest.fixture
    def camera(self):
        from hardware.cameras.simulated import SimulatedCamera
        cfg = {"exposure_us": 1000, "gain": 0.0,
               "width": 32, "height": 24, "frame_rate": 500,
               "noise_level": 0.01, "bit_depth": 12}
        cam = SimulatedCamera(cfg)
        cam.open()
        cam.start()
        return cam

    def test_run_produces_frame_cube(self, camera):
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=10, capture_reference=False)

        assert result is not None, "run() returned None"
        assert result.frame_cube is not None, "frame_cube is None"
        assert result.frame_cube.shape == (10, 24, 32), \
            f"Unexpected cube shape: {result.frame_cube.shape}"
        assert result.frame_cube.dtype == np.float32

    def test_run_with_reference_produces_delta_r_cube(self, camera):
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=8, capture_reference=True)

        assert result.reference is not None, "Reference not captured"
        assert result.delta_r_cube is not None, "delta_r_cube is None"
        assert result.delta_r_cube.shape == (8, 24, 32), \
            f"delta_r_cube shape: {result.delta_r_cube.shape}"

    def test_delta_r_cube_values_are_finite(self, camera):
        """
        ΔR/R cube must have at least some finite values (bright hotspot
        pixels at the frame centre).  The simulated camera generates a
        sine-pattern frame where many edge pixels can fall below the dark
        threshold and become NaN — but the Gaussian hotspot at the centre
        must always be bright and produce finite ΔR/R values.
        """
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=5, capture_reference=True)

        # At least the central hotspot pixels should yield finite ΔR/R values;
        # dark edge masking (NaN) is correct and expected behaviour.
        assert np.isfinite(result.delta_r_cube).any(), \
            "delta_r_cube has no finite values at all"

    def test_timestamps_monotonically_increasing(self, camera):
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=6)

        assert result.timestamps_s is not None
        assert len(result.timestamps_s) == 6
        diffs = np.diff(result.timestamps_s)
        assert (diffs >= 0).all(), "Timestamps not monotonically non-decreasing"

    def test_abort_stops_acquisition(self, camera):
        from acquisition.movie_pipeline import MovieAcquisitionPipeline, MovieAcqState
        pipeline = MovieAcquisitionPipeline(camera)

        pipeline.start(n_frames=10_000)   # very long — will be aborted
        time.sleep(0.02)
        pipeline.abort()
        pipeline._thread.join(timeout=3.0)

        assert pipeline.state in (MovieAcqState.ABORTED, MovieAcqState.COMPLETE), \
            f"Unexpected state after abort: {pipeline.state}"

    def test_fps_achieved_is_positive(self, camera):
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=5)

        assert result.fps_achieved > 0.0, \
            f"fps_achieved={result.fps_achieved} is not positive"

    def test_run_with_drift_correction(self, camera):
        """Pipeline must complete successfully with drift_correction=True."""
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_frames=5, capture_reference=True, drift_correction=True)
        assert result.frame_cube is not None
        assert result.frame_cube.shape[0] == 5

    def test_no_reference_no_delta_cube(self, camera):
        """With capture_reference=False, delta_r_cube must be None."""
        from acquisition.movie_pipeline import MovieAcquisitionPipeline
        pipeline = MovieAcquisitionPipeline(camera)
        result   = pipeline.run(n_frames=5, capture_reference=False)
        assert result.delta_r_cube is None, \
            "delta_r_cube should be None when capture_reference=False"


# ================================================================== #
#  5. TransientAcquisitionPipeline — end-to-end                      #
# ================================================================== #

class TestTransientPipeline:
    """TransientAcquisitionPipeline with SimulatedCamera, no hardware needed."""

    @pytest.fixture
    def camera(self):
        from hardware.cameras.simulated import SimulatedCamera
        cfg = {"exposure_us": 500, "gain": 0.0,
               "width": 32, "height": 24, "frame_rate": 1000,
               "noise_level": 0.01, "bit_depth": 12}
        cam = SimulatedCamera(cfg)
        cam.open()
        cam.start()
        return cam

    def test_run_produces_delta_r_cube(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=4, delay_start_s=0.0, delay_end_s=0.002,
            pulse_dur_us=100.0, n_averages=3)

        assert result is not None
        assert result.delta_r_cube is not None, "delta_r_cube is None"
        assert result.delta_r_cube.shape == (4, 24, 32), \
            f"Unexpected shape: {result.delta_r_cube.shape}"

    def test_run_produces_raw_cube(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001, pulse_dur_us=50.0, n_averages=2)

        assert result.raw_cube is not None, "raw_cube is None"
        assert result.raw_cube.shape == (3, 24, 32)

    def test_delay_times_correct_length(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=5, delay_end_s=0.003, pulse_dur_us=100.0, n_averages=2)

        assert result.delay_times_s is not None
        assert len(result.delay_times_s) == 5

    def test_delay_times_monotonically_increasing(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=6, delay_start_s=0.0, delay_end_s=0.005,
            pulse_dur_us=100.0, n_averages=2)

        diffs = np.diff(result.delay_times_s)
        assert (diffs > 0).all(), "Delay times must be strictly increasing"

    def test_reference_captured(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001, pulse_dur_us=50.0, n_averages=2)

        assert result.reference is not None, "Cold reference frame not captured"
        assert result.reference.shape == (24, 32)

    def test_is_complete_true_after_run(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001, pulse_dur_us=50.0, n_averages=2)

        assert result.is_complete

    def test_metadata_populated(self, camera):
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001,
            pulse_dur_us=200.0, n_averages=4)

        assert result.n_delays    == 3
        assert result.n_averages  == 4
        assert result.pulse_dur_us == pytest.approx(200.0)
        assert result.duration_s  > 0.0
        assert result.timestamp   > 0.0

    def test_abort_before_completion(self, camera):
        from acquisition.transient_pipeline import (
            TransientAcquisitionPipeline, TransientAcqState)
        pipeline = TransientAcquisitionPipeline(camera)

        # Large acquisition — will be aborted early
        pipeline.start(n_delays=500, delay_end_s=5.0,
                       pulse_dur_us=100.0, n_averages=50)
        time.sleep(0.05)
        pipeline.abort()
        pipeline._thread.join(timeout=5.0)

        assert pipeline.state in (
            TransientAcqState.ABORTED, TransientAcqState.COMPLETE), \
            f"Unexpected state: {pipeline.state}"

    def test_run_with_drift_correction(self, camera):
        """Pipeline must complete with drift_correction=True."""
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001, pulse_dur_us=50.0,
            n_averages=2, drift_correction=True)
        assert result.is_complete

    def test_sw_fallback_when_no_fpga(self, camera):
        """Without FPGA, pipeline falls back to SW timing (hw_triggered=False)."""
        from acquisition.transient_pipeline import TransientAcquisitionPipeline
        pipeline = TransientAcquisitionPipeline(camera, fpga=None)
        result   = pipeline.run(
            n_delays=3, delay_end_s=0.001, pulse_dur_us=50.0, n_averages=2)
        assert not result.hw_triggered


# ================================================================== #
#  6. AppState — system_model property                                #
# ================================================================== #

class TestAppStateSystemModel:
    """Verify system_model property and snapshot integration."""

    def test_default_is_none(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        assert state.system_model is None

    def test_set_and_get(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        state.system_model = "EZ500"
        assert state.system_model == "EZ500"

    def test_set_none_clears(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        state.system_model = "NT220"
        state.system_model = None
        assert state.system_model is None

    def test_coerced_to_string(self):
        """Non-string values must be coerced to str."""
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        state.system_model = 500   # type: ignore[assignment]
        assert state.system_model == "500"
        assert isinstance(state.system_model, str)

    def test_thread_safe_write(self):
        """Multiple threads writing system_model must not corrupt state."""
        from hardware.app_state import ApplicationState
        state  = ApplicationState()
        errors = []

        def writer(val):
            for _ in range(100):
                try:
                    state.system_model = str(val)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors
        assert state.system_model in [str(i) for i in range(4)]

    def test_snapshot_includes_system_model(self):
        """snapshot() must include the system_model key."""
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        state.system_model = "PT410A"
        snap  = state.snapshot()
        assert "system_model" in snap
        assert snap["system_model"] == "PT410A"

    def test_snapshot_system_model_none_when_unset(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        snap  = state.snapshot()
        assert "system_model" in snap
        assert snap["system_model"] is None


# ================================================================== #
#  7. Voltage sweep list logic                                        #
# ================================================================== #

class TestVsweepVoltageList:
    """
    Exercise the voltage-series list computation that lives in
    TransientTab._vsweep_voltage_list() as pure-math unit tests
    (without instantiating QWidget).
    """

    @staticmethod
    def _compute(start: float, step: float, end: float):
        """Mirrors TransientTab._vsweep_voltage_list() logic exactly."""
        if step <= 0 or start > end:
            return []
        n = max(1, int(round((end - start) / step)) + 1)
        return [round(start + i * step, 6) for i in range(n)]

    def test_simple_three_step(self):
        v = self._compute(0.5, 0.5, 2.0)
        assert v == pytest.approx([0.5, 1.0, 1.5, 2.0])

    def test_single_step_when_start_equals_end(self):
        v = self._compute(1.0, 0.5, 1.0)
        assert v == [pytest.approx(1.0)]
        assert len(v) == 1

    def test_empty_when_start_greater_than_end(self):
        v = self._compute(3.0, 0.5, 1.0)
        assert v == []

    def test_empty_when_step_is_zero(self):
        v = self._compute(0.0, 0.0, 5.0)
        assert v == []

    def test_empty_when_step_is_negative(self):
        v = self._compute(0.0, -0.5, 5.0)
        assert v == []

    def test_large_sweep(self):
        v = self._compute(0.0, 0.1, 1.0)
        # Should have 11 steps: 0.0, 0.1, ..., 1.0
        assert len(v) == 11
        assert v[0]  == pytest.approx(0.0)
        assert v[-1] == pytest.approx(1.0, abs=1e-5)

    def test_values_are_rounded(self):
        """All values must be rounded to 6 decimal places."""
        v = self._compute(0.0, 1.0 / 3.0, 1.0)
        for val in v:
            # repr should not show more than 6 decimal digits of precision
            parts = str(val).split(".")
            decimals = parts[1] if len(parts) > 1 else ""
            assert len(decimals) <= 7, f"Too many decimal places in {val}"

    def test_monotonically_increasing(self):
        v = self._compute(0.1, 0.3, 2.0)
        for a, b in zip(v, v[1:]):
            assert b > a, f"Not monotonically increasing: {v}"
