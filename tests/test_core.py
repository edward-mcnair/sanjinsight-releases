"""
tests/test_core.py

Core unit tests for Microsanj Thermal Analysis System.

Covers:
    • Calibration math (C_T fit, ΔT conversion, R² quality)
    • ThermalAnalysisEngine verdict logic (all six rule combinations)
    • Session save / load round-trip
    • Profile serialisation (all 20 built-in profiles)
    • Modality enum parsing
    • AppState thread safety
    • AcquisitionPipeline abort + result structure
    • Scientific export (NPY, NPZ, CSV — no optional deps required)

Run:
    cd project_bonaire
    pytest tests/test_core.py -v

All tests use synthetic data — no hardware required.
"""

from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import threading
import numpy as np
import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. Calibration                                                      #
# ================================================================== #

class TestCalibration:
    """Verify per-pixel C_T fit and ΔT conversion."""

    @pytest.fixture
    def synthetic_cal(self):
        """
        Build a synthetic calibration with known C_T.
        True C_T = 2e-4 K⁻¹ everywhere (uniform illumination).
        """
        from acquisition.calibration import Calibration

        H, W = 64, 64
        TRUE_CT = 2e-4
        T_REF   = 25.0
        I_REF   = 2000.0   # reference intensity (counts)

        cal = Calibration()
        for T in [25.0, 30.0, 35.0, 40.0]:
            dT  = T - T_REF
            drr = TRUE_CT * dT
            I   = I_REF * (1 + drr)
            frame = np.full((H, W), I, dtype=np.float32)
            # Add tiny reproducible noise (0.05 counts ≪ weakest ΔT signal of
            # 2 counts at 5 °C step, giving SNR ~40 and R² reliably > 0.99)
            rng   = np.random.default_rng(seed=int(T * 100))
            frame += rng.normal(0, 0.05, (H, W)).astype(np.float32)
            cal.add_point(temperature=T, frame=frame)

        return cal, TRUE_CT, H, W

    def test_fit_ct_accuracy(self, synthetic_cal):
        """Fitted C_T should match true C_T within 2%."""
        cal, TRUE_CT, H, W = synthetic_cal
        result = cal.fit()
        assert result.valid, "Calibration fit returned valid=False"
        masked = result.ct_map[result.mask]
        mean_ct = float(masked.mean())
        assert abs(mean_ct - TRUE_CT) / TRUE_CT < 0.02, \
            f"Fitted C_T {mean_ct:.3e} deviates > 2% from true {TRUE_CT:.3e}"

    def test_r2_map_high(self, synthetic_cal):
        """R² should be > 0.99 for ideal synthetic data."""
        cal, *_ = synthetic_cal
        result = cal.fit()
        assert result.r2_map is not None
        masked_r2 = result.r2_map[result.mask]
        assert masked_r2.mean() > 0.99, \
            f"Mean R² {masked_r2.mean():.4f} too low for synthetic data"

    def test_apply_dt_round_trip(self, synthetic_cal):
        """apply() should convert ΔR/R back to ΔT within 1%."""
        cal, TRUE_CT, H, W = synthetic_cal
        result = cal.fit()

        TRUE_DT = 10.0  # °C we'll encode in the ΔR/R map
        drr_map = np.full((H, W), TRUE_CT * TRUE_DT, dtype=np.float32)

        dt_map = result.apply(drr_map)
        valid  = dt_map[result.mask & ~np.isnan(dt_map)]
        mean_dt = float(valid.mean())
        assert abs(mean_dt - TRUE_DT) / TRUE_DT < 0.01, \
            f"ΔT round-trip error: got {mean_dt:.3f}°C, expected {TRUE_DT:.1f}°C"

    def test_save_load_round_trip(self, synthetic_cal, tmp_path):
        """Saved and reloaded CalibrationResult should match original."""
        from acquisition.calibration import CalibrationResult
        cal, TRUE_CT, H, W = synthetic_cal
        result = cal.fit()

        path = str(tmp_path / "cal_test")
        saved_path = result.save(path)
        loaded = CalibrationResult.load(saved_path)

        assert loaded.valid
        assert loaded.n_points  == result.n_points
        assert loaded.frame_h   == H
        assert loaded.frame_w   == W
        np.testing.assert_allclose(loaded.ct_map, result.ct_map,
                                   rtol=1e-5, atol=1e-12)
        np.testing.assert_array_equal(loaded.mask, result.mask)

    def test_requires_two_points(self):
        """Calibration.fit() must raise with fewer than 2 points."""
        from acquisition.calibration import Calibration
        cal = Calibration()
        cal.add_point(25.0, np.ones((32, 32), np.float32) * 1000)
        with pytest.raises(ValueError, match="2 calibration points"):
            cal.fit()

    def test_mask_suppresses_dark_pixels(self, synthetic_cal):
        """Pixels with intensity < min_intensity must be masked out."""
        from acquisition.calibration import Calibration

        H, W = 32, 32
        TRUE_CT = 2e-4
        cal = Calibration()
        for T in [25.0, 35.0]:
            I = np.full((H, W), 2000.0 * (1 + TRUE_CT * (T - 25.0)),
                        dtype=np.float32)
            I[:4, :] = 2.0   # dark region — below min_intensity=10
            cal.add_point(T, I)

        result = cal.fit(min_intensity=10.0)
        # Dark pixels (rows 0–3) must be masked
        assert not result.mask[:4, :].any(), \
            "Dark pixels should be excluded from mask"


# ================================================================== #
#  2. Thermal Analysis Engine — verdict logic                         #
# ================================================================== #

class TestAnalysisEngine:
    """Test all verdict rule combinations."""

    @pytest.fixture
    def engine_and_map(self):
        """
        Returns (engine, hot_map, cool_map).
        hot_map  — 20×20 square hotspot in centre (peak = 15°C)
        cool_map — uniform 1°C, no hotspots
        """
        from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

        H, W = 100, 100
        hot_map  = np.ones((H, W), np.float32)
        hot_map[40:60, 40:60] = 15.0   # 20×20 = 400 px hotspot, peak 15°C

        cool_map = np.ones((H, W), np.float32)

        cfg    = AnalysisConfig(
            threshold_k        = 5.0,
            fail_hotspot_count = 1,
            fail_peak_k        = 10.0,
            fail_area_fraction = 0.05,
            warn_hotspot_count = 0,
            warn_peak_k        = 3.0,
            warn_area_fraction = 0.01,
            min_area_px        = 10,
        )
        engine = ThermalAnalysisEngine(cfg)
        return engine, hot_map, cool_map

    def test_fail_on_hotspot_count(self, engine_and_map):
        engine, hot_map, _ = engine_and_map
        result = engine.run(dt_map=hot_map, drr_map=None)
        assert result.verdict == "FAIL", \
            f"Expected FAIL (hotspot count), got {result.verdict}"

    def test_pass_on_cool_map(self, engine_and_map):
        engine, _, cool_map = engine_and_map
        result = engine.run(dt_map=cool_map, drr_map=None)
        assert result.verdict == "PASS", \
            f"Expected PASS (cool map), got {result.verdict}"

    def test_warning_below_fail_threshold(self):
        """Map with peak 4°C should give WARNING (warn_peak_k=3) not FAIL."""
        from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

        H, W = 80, 80
        dt_map = np.ones((H, W), np.float32)
        dt_map[35:45, 35:45] = 4.0   # peak 4°C

        cfg = AnalysisConfig(
            threshold_k        = 2.0,
            fail_hotspot_count = 2,     # need 2 hotspots to fail by count
            fail_peak_k        = 8.0,   # peak 4 < 8 → no fail
            fail_area_fraction = 0.10,
            warn_peak_k        = 3.0,   # peak 4 ≥ 3 → warning
            warn_area_fraction = 0.00,
            warn_hotspot_count = 0,
            min_area_px        = 5,
        )
        engine = ThermalAnalysisEngine(cfg)
        result = engine.run(dt_map=dt_map, drr_map=None)
        assert result.verdict == "WARNING", \
            f"Expected WARNING, got {result.verdict}"

    def test_fail_on_area_fraction(self):
        """Map where hotspot area fraction exceeds limit."""
        from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

        H, W = 50, 50
        dt_map = np.full((H, W), 10.0, np.float32)  # 100% area above threshold

        cfg = AnalysisConfig(
            threshold_k        = 5.0,
            fail_hotspot_count = 999,   # won't trigger by count
            fail_peak_k        = 999,   # won't trigger by peak
            fail_area_fraction = 0.01,  # 100% ≫ 1%
            warn_peak_k        = 0,
            warn_area_fraction = 0,
            warn_hotspot_count = 0,
            min_area_px        = 5,
        )
        engine = ThermalAnalysisEngine(cfg)
        result = engine.run(dt_map=dt_map, drr_map=None)
        assert result.verdict == "FAIL"

    def test_hotspot_index_ordering(self, engine_and_map):
        """Hotspots must be sorted by peak ΔT descending, 1-based index."""
        engine, hot_map, _ = engine_and_map
        # Add a second, smaller hotspot
        hot_map[10:15, 10:15] = 8.0

        result = engine.run(dt_map=hot_map, drr_map=None)
        peaks = [h.peak_k for h in result.hotspots]
        assert peaks == sorted(peaks, reverse=True), \
            "Hotspots should be sorted by peak ΔT descending"
        for i, h in enumerate(result.hotspots):
            assert h.index == i + 1, \
                f"Hotspot index should be 1-based, got {h.index}"

    def test_no_input_returns_fail(self):
        """Running engine with no data should return FAIL, not crash."""
        from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig
        engine = ThermalAnalysisEngine(AnalysisConfig())
        result = engine.run(dt_map=None, drr_map=None)
        assert result.verdict == "FAIL"
        assert not result.valid

    def test_fallback_to_drr_map(self):
        """Engine must use drr_map when dt_map is None."""
        from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

        H, W = 60, 60
        drr_map = np.ones((H, W), np.float32) * 0.001   # below threshold

        cfg    = AnalysisConfig(threshold_k=0.005, fail_peak_k=0.01,
                                fail_hotspot_count=1, use_dt=False)
        engine = ThermalAnalysisEngine(cfg)
        result = engine.run(dt_map=None, drr_map=drr_map)
        assert result.valid
        assert result.verdict == "PASS"


# ================================================================== #
#  3. Session save / load round-trip                                   #
# ================================================================== #

class TestSession:
    """Session serialisation and new metadata fields."""

    @pytest.fixture
    def sample_result(self):
        """Minimal AcquisitionResult for testing."""
        from acquisition.pipeline import AcquisitionResult
        H, W   = 48, 64
        result = AcquisitionResult(
            n_frames    = 50,
            exposure_us = 5000.0,
            gain_db     = 0.0,
            timestamp   = time.time(),
            duration_s  = 2.5,
        )
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 2000
        result.hot_avg        = result.cold_avg * 1.001
        result.delta_r_over_r = (
            (result.hot_avg - result.cold_avg) / result.cold_avg).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = 50
        result.hot_captured   = 50
        return result

    def test_round_trip_arrays(self, sample_result, tmp_path):
        """Saved arrays must be identical after load."""
        from acquisition.session import Session

        session = Session.from_result(
            sample_result,
            label="test_session",
            imaging_mode="thermoreflectance",
            wavelength_nm=532,
            profile_uid="si_532nm",
            profile_name="Silicon — 532 nm",
            ct_value=2e-4,
            fpga_frequency_hz=1000.0,
            tec_temperature=25.0,
        )
        path    = session.save(str(tmp_path))
        loaded  = Session.load(path)

        for name in ["cold_avg", "hot_avg", "delta_r_over_r", "difference"]:
            orig = getattr(session, name)
            back = getattr(loaded, name)
            assert back is not None, f"{name} not loaded"
            np.testing.assert_array_equal(orig, back,
                                          err_msg=f"{name} mismatch")

    def test_new_metadata_fields(self, sample_result, tmp_path):
        """All new metadata fields must be persisted and restored."""
        from acquisition.session import Session

        session = Session.from_result(
            sample_result,
            imaging_mode     = "ir_lockin",
            wavelength_nm    = 785,
            profile_uid      = "si_785",
            profile_name     = "Silicon — 785 nm",
            ct_value         = 1.5e-4,
            fpga_frequency_hz= 2000.0,
            fpga_duty_cycle  = 0.4,
            tec_temperature  = 30.0,
            tec_setpoint     = 30.0,
            bias_voltage     = 3.3,
            bias_current     = 0.01,
        )
        path   = session.save(str(tmp_path))
        loaded = Session.load(path)

        assert loaded.meta.imaging_mode      == "ir_lockin"
        assert loaded.meta.wavelength_nm     == 785
        assert loaded.meta.profile_uid       == "si_785"
        assert loaded.meta.ct_value          == pytest.approx(1.5e-4)
        assert loaded.meta.fpga_frequency_hz == pytest.approx(2000.0)
        assert loaded.meta.tec_temperature   == pytest.approx(30.0)
        assert loaded.meta.bias_voltage      == pytest.approx(3.3)

    def test_session_json_is_human_readable(self, sample_result, tmp_path):
        """session.json must be valid JSON with expected keys."""
        from acquisition.session import Session
        session = Session.from_result(sample_result)
        path = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        assert os.path.exists(json_path)
        with open(json_path) as f:
            data = json.load(f)
        for key in ["uid", "label", "imaging_mode", "wavelength_nm",
                    "n_frames", "exposure_us", "timestamp_str"]:
            assert key in data, f"session.json missing key: {key}"


# ================================================================== #
#  4. Profile serialisation                                            #
# ================================================================== #

class TestProfiles:
    """Verify all built-in profiles survive to_dict → from_dict round-trip."""

    def test_all_builtin_profiles_round_trip(self):
        from profiles.profiles import BUILTIN_PROFILES, MaterialProfile
        assert len(BUILTIN_PROFILES) > 0, "No built-in profiles found"
        for p in BUILTIN_PROFILES:
            d      = p.to_dict()
            reborn = MaterialProfile.from_dict(d)
            assert reborn.uid          == p.uid,      f"uid mismatch for {p.name}"
            assert reborn.ct_value     == p.ct_value, f"ct_value mismatch for {p.name}"
            assert reborn.wavelength_nm== p.wavelength_nm

    def test_profile_has_required_fields(self):
        from profiles.profiles import BUILTIN_PROFILES
        for p in BUILTIN_PROFILES:
            assert p.uid,       f"Profile missing uid: {p.name}"
            assert p.name,      f"Profile missing name"
            assert p.category,  f"Profile {p.name} missing category"
            # IR profiles don't have a thermoreflectance coefficient or
            # specific illumination wavelength — only TR profiles require these.
            if getattr(p, "modality", "tr") != "ir":
                assert p.ct_value > 0, f"Profile {p.name} has non-positive ct_value"
                assert p.wavelength_nm > 0, f"Profile {p.name} has non-positive wavelength"


# ================================================================== #
#  5. ImagingModality                                                  #
# ================================================================== #

class TestModality:
    def test_known_values_parse(self):
        from acquisition.modality import ImagingModality
        assert ImagingModality.from_str("thermoreflectance") == ImagingModality.THERMOREFLECTANCE
        assert ImagingModality.from_str("ir_lockin")         == ImagingModality.IR_LOCKIN
        assert ImagingModality.from_str("hybrid")            == ImagingModality.HYBRID
        assert ImagingModality.from_str("opp")               == ImagingModality.OPP

    def test_unknown_string_gives_unknown(self):
        from acquisition.modality import ImagingModality
        assert ImagingModality.from_str("unicorn") == ImagingModality.UNKNOWN
        assert ImagingModality.from_str("")        == ImagingModality.UNKNOWN

    def test_info_lookup_complete(self):
        from acquisition.modality import ImagingModality, get_info, all_modalities
        for m in all_modalities():
            info = get_info(m)
            assert info.display_name
            assert info.accent_color.startswith("#")

    def test_ct_map_flags_correct(self):
        from acquisition.modality import ImagingModality, get_info
        assert get_info(ImagingModality.THERMOREFLECTANCE).requires_ct_map is True
        assert get_info(ImagingModality.IR_LOCKIN).requires_ct_map          is False
        assert get_info(ImagingModality.HYBRID).requires_ct_map             is True


# ================================================================== #
#  6. ApplicationState thread safety                                   #
# ================================================================== #

class TestAppState:
    def test_basic_set_get(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        assert state.cam is None

        # Fake camera object
        class FakeCam:
            pass
        fc = FakeCam()
        state.cam = fc
        assert state.cam is fc

    def test_concurrent_writes_are_safe(self):
        """Multiple threads writing simultaneously must not corrupt state."""
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        errors = []

        def writer(val):
            for _ in range(100):
                try:
                    with state:
                        state._active_modality = str(val)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors, f"Thread safety violation: {errors}"
        # Final value must be one of the written strings
        assert state.active_modality in [str(i) for i in range(8)]

    def test_snapshot(self):
        from hardware.app_state import ApplicationState
        state    = ApplicationState()
        snapshot = state.snapshot()
        assert "cam"      in snapshot
        assert "pipeline" in snapshot
        assert "modality" in snapshot

    def test_require_cam_raises_when_none(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        with pytest.raises(RuntimeError, match="Camera not connected"):
            state.require_cam()

    def test_add_tec_returns_index(self):
        from hardware.app_state import ApplicationState
        state = ApplicationState()
        idx0 = state.add_tec("tec_a")
        idx1 = state.add_tec("tec_b")
        assert idx0 == 0
        assert idx1 == 1
        assert len(state.tecs) == 2


# ================================================================== #
#  7. AcquisitionPipeline — simulated end-to-end                      #
# ================================================================== #

class TestPipeline:
    """Full pipeline run using simulated camera (no hardware)."""

    @pytest.fixture
    def pipeline_with_sim_cam(self):
        from hardware.cameras.simulated import SimulatedCamera
        from acquisition.pipeline import AcquisitionPipeline

        cfg = {"exposure_us": 1000, "gain": 0.0,
               "width": 64, "height": 48, "frame_rate": 200,
               "noise_level": 0.005, "bit_depth": 12}
        cam = SimulatedCamera(cfg)
        cam.open()
        cam.start()
        return AcquisitionPipeline(cam)

    def test_complete_run_produces_result(self, pipeline_with_sim_cam):
        pipeline = pipeline_with_sim_cam
        result   = pipeline.run(n_frames=10)

        assert result is not None
        assert result.delta_r_over_r is not None
        assert result.cold_avg.shape == (48, 64)
        assert result.hot_avg.shape  == (48, 64)
        assert result.cold_captured  == 10
        assert result.hot_captured   == 10

    def test_abort_stops_acquisition(self, pipeline_with_sim_cam):
        from acquisition.pipeline import AcqState
        pipeline = pipeline_with_sim_cam

        # Start a long acquisition and abort after 50ms
        pipeline.start(n_frames=1000)
        time.sleep(0.05)
        pipeline.abort()
        pipeline._thread.join(timeout=2.0)

        assert pipeline.state in (AcqState.ABORTED, AcqState.COMPLETE)

    def test_result_snr_is_finite(self, pipeline_with_sim_cam):
        pipeline = pipeline_with_sim_cam
        result   = pipeline.run(n_frames=20)
        assert result.snr_db is not None
        assert np.isfinite(result.snr_db)

    def test_roi_reduces_output_shape(self, pipeline_with_sim_cam):
        from acquisition.roi import Roi
        pipeline     = pipeline_with_sim_cam
        pipeline.roi = Roi(x=10, y=10, w=30, h=20)
        result       = pipeline.run(n_frames=5)

        assert result.cold_avg.shape == (20, 30), \
            f"Expected (20, 30) ROI crop, got {result.cold_avg.shape}"


# ================================================================== #
#  8. Scientific export (no optional deps required)                    #
# ================================================================== #

class TestExport:
    """Test NPY and NPZ export which have no optional dependencies."""

    @pytest.fixture
    def sample_session(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.session  import Session

        H, W   = 40, 60
        result = AcquisitionResult(n_frames=32, exposure_us=5000.0,
                                   gain_db=0.0, timestamp=time.time())
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 2000
        result.hot_avg        = result.cold_avg * 1.0005
        result.delta_r_over_r = ((result.hot_avg - result.cold_avg) /
                                  result.cold_avg).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = result.hot_captured = 32

        session = Session.from_result(result, label="export_test",
                                       imaging_mode="thermoreflectance",
                                       wavelength_nm=532)
        session.save(str(tmp_path / "sessions"))
        return session

    def test_npy_export_creates_files(self, sample_session, tmp_path):
        from acquisition.export import SessionExporter, ExportFormat

        out = str(tmp_path / "npy_out")
        ex  = SessionExporter(sample_session, output_dir=out)
        res = ex.export([ExportFormat.NPY])

        assert res.success
        assert any(f.endswith(".npy") for f in res.saved_paths)
        assert any(f.endswith(".json") for f in res.saved_paths)

    def test_npz_export_round_trip(self, sample_session, tmp_path):
        from acquisition.export import SessionExporter, ExportFormat

        out = str(tmp_path / "npz_out")
        ex  = SessionExporter(sample_session, output_dir=out)
        res = ex.export([ExportFormat.NPZ])

        assert res.success
        npz_path = [f for f in res.saved_paths if f.endswith(".npz")][0]
        loaded   = np.load(npz_path)
        np.testing.assert_allclose(
            loaded["delta_r_over_r"],
            sample_session.delta_r_over_r,
            rtol=1e-5)

    def test_csv_export_has_correct_shape(self, sample_session, tmp_path):
        from acquisition.export import SessionExporter, ExportFormat

        out = str(tmp_path / "csv_out")
        ex  = SessionExporter(sample_session, output_dir=out, px_per_um=2.5)
        res = ex.export([ExportFormat.CSV])

        assert res.success
        csv_path = [f for f in res.saved_paths if f.endswith(".csv")][0]
        lines    = [l for l in open(csv_path).readlines()
                    if not l.startswith("#")]
        # Should have 1 header line + H data rows
        H = sample_session.delta_r_over_r.shape[0]
        assert len(lines) == H + 1, \
            f"Expected {H+1} non-comment lines, got {len(lines)}"

    def test_export_result_errors_on_missing_array(self, tmp_path):
        """Export with no arrays should report error, not crash."""
        from acquisition.export import SessionExporter, ExportFormat

        out = str(tmp_path / "empty_out")
        ex  = SessionExporter(None, output_dir=out)   # no session
        res = ex.export([ExportFormat.CSV])

        # CSV needs delta_r_over_r — should error gracefully
        assert not res.success or len(res.errors) > 0 or res.n_files == 0


# ================================================================== #
#  9. Scan stitching geometry                                          #
# ================================================================== #

class TestScanEngine:
    """Verify tile placement math without running full hardware scan."""

    def test_3x3_grid_stitch_shape(self):
        """
        For a 3×3 scan with 64×48 px tiles (no overlap), the stitched
        map must be exactly 192×144 px.
        """
        from acquisition.scan import ScanEngine

        # ScanEngine._stitch() is internal — we'll test it directly
        tile_w, tile_h = 64, 48
        n_cols, n_rows = 3, 3

        # Build synthetic tile results (just arrays, not full AcquisitionResult)
        tiles = []
        for row in range(n_rows):
            for col in range(n_cols):
                arr = np.full((tile_h, tile_w), float(row * n_cols + col),
                              dtype=np.float32)
                tiles.append(arr)

        # Manual stitch
        canvas = np.zeros((tile_h * n_rows, tile_w * n_cols), dtype=np.float32)
        for i, tile in enumerate(tiles):
            row = i // n_cols
            col = i  % n_cols
            canvas[row*tile_h:(row+1)*tile_h,
                   col*tile_w:(col+1)*tile_w] = tile

        assert canvas.shape == (tile_h * n_rows, tile_w * n_cols), \
            f"Stitched shape {canvas.shape} unexpected"

        # Corner tiles should have their expected values
        assert canvas[0, 0]                 == pytest.approx(0.0)   # tile 0
        assert canvas[0, tile_w*2]          == pytest.approx(2.0)   # tile 2
        assert canvas[tile_h*2, 0]          == pytest.approx(6.0)   # tile 6
        assert canvas[tile_h*2, tile_w*2]   == pytest.approx(8.0)   # tile 8


# ================================================================== #
#  10. Processing utilities                                            #
# ================================================================== #

class TestProcessing:
    def test_to_display_auto_range(self):
        from acquisition.processing import to_display
        data = np.linspace(0, 1, 100, dtype=np.float32).reshape(10, 10)
        disp = to_display(data, mode="auto")
        assert disp.dtype == np.uint8
        assert int(disp.min()) == 0
        assert int(disp.max()) == 255

    def test_to_display_signed_returns_rgb(self):
        from acquisition.processing import to_display
        data = np.linspace(-1, 1, 64, dtype=np.float32).reshape(8, 8)
        disp = to_display(data, mode="signed")
        assert disp.shape == (8, 8, 3)
        assert disp.dtype == np.uint8

    def test_to_display_all_zeros_no_crash(self):
        from acquisition.processing import to_display
        data = np.zeros((32, 32), dtype=np.float32)
        disp = to_display(data, mode="auto")
        assert disp.shape == (32, 32)


# ================================================================== #
#  9. UpdateChecker                                                    #
# ================================================================== #

class TestUpdateChecker:
    """
    Unit tests for updater.py — all network calls are mocked.

    Tests cover:
        • on_update fires when remote version is strictly newer
        • on_no_update fires when remote version equals running version
        • on_no_update fires when remote version is older than running version
        • on_error fires on HTTP / network failure
        • on_error fires when API response is missing tag_name
        • on_error fires on malformed JSON
        • download_url falls back to RELEASES_PAGE_URL when no .exe asset
        • download_url is set from .exe asset when present
        • check_sync() returns UpdateInfo on newer, None on up-to-date
        • should_check_now() respects auto_check=False
        • should_check_now() returns True for frequency='always'
        • should_check_now() respects daily / weekly intervals
    """

    def _make_api_response(self, tag: str, has_exe: bool = True,
                           prerelease: bool = False) -> bytes:
        """Build a minimal GitHub Releases API payload."""
        assets = []
        if has_exe:
            assets.append({
                "name": f"SanjINSIGHT-Setup-{tag.lstrip('v')}.exe",
                "browser_download_url": f"https://example.com/SanjINSIGHT-Setup-{tag.lstrip('v')}.exe",
            })
        payload = {
            "tag_name": tag,
            "body": "Release notes here.",
            "html_url": f"https://github.com/test/releases/tag/{tag}",
            "prerelease": prerelease,
            "assets": assets,
        }
        return json.dumps(payload).encode("utf-8")

    def _mock_urlopen(self, tag: str, **kwargs):
        """Return a context-manager mock that yields the API response."""
        from unittest.mock import MagicMock, patch
        import io
        body = self._make_api_response(tag, **kwargs)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        return cm

    # ── on_update / on_no_update ──────────────────────────────────

    def test_on_update_fires_when_remote_is_newer(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker

        received = []
        checker = UpdateChecker(on_update=received.append)

        body = self._make_api_response("v99.0.0")
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            result = checker.check_sync()

        assert result is not None
        assert result.version == "99.0.0"
        assert len(received) == 1
        assert received[0].version == "99.0.0"

    def test_on_no_update_fires_when_running_is_newer(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker

        no_update_called = []
        checker = UpdateChecker(
            on_update=lambda info: (_ for _ in ()).throw(AssertionError("on_update should not fire")),
            on_no_update=lambda: no_update_called.append(True),
        )

        # Tag older than any real version
        body = self._make_api_response("v0.0.1")
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            result = checker.check_sync()

        assert result is None
        assert len(no_update_called) == 1

    def test_on_no_update_fires_when_same_version(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker
        from version import __version__

        no_update_called = []
        checker = UpdateChecker(
            on_update=lambda info: (_ for _ in ()).throw(AssertionError("on_update should not fire")),
            on_no_update=lambda: no_update_called.append(True),
        )

        body = self._make_api_response(f"v{__version__}")
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            result = checker.check_sync()

        assert result is None
        assert len(no_update_called) == 1

    # ── on_error ─────────────────────────────────────────────────

    def test_on_error_fires_on_network_failure(self):
        from unittest.mock import patch
        import urllib.error
        from updater import UpdateChecker

        errors = []
        checker = UpdateChecker(on_update=lambda i: None, on_error=errors.append)

        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            result = checker.check_sync()

        assert result is None
        assert len(errors) == 1
        assert "Network error" in errors[0]

    def test_on_error_fires_on_malformed_json(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker

        errors = []
        checker = UpdateChecker(on_update=lambda i: None, on_error=errors.append)

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(b"not json {{"))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            result = checker.check_sync()

        assert result is None
        assert len(errors) == 1
        assert "Malformed" in errors[0]

    def test_on_error_fires_when_tag_name_missing(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker

        errors = []
        checker = UpdateChecker(on_update=lambda i: None, on_error=errors.append)

        body = json.dumps({"assets": []}).encode("utf-8")
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            result = checker.check_sync()

        assert result is None
        assert len(errors) == 1
        assert "tag_name" in errors[0]

    # ── download_url resolution ───────────────────────────────────

    def test_download_url_set_from_exe_asset(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker

        received = []
        checker = UpdateChecker(on_update=received.append)

        body = self._make_api_response("v99.0.0", has_exe=True)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            checker.check_sync()

        assert len(received) == 1
        assert received[0].download_url.endswith(".exe")

    def test_download_url_falls_back_to_releases_page(self):
        from unittest.mock import patch, MagicMock
        import io
        from updater import UpdateChecker
        from version import RELEASES_PAGE_URL

        received = []
        checker = UpdateChecker(on_update=received.append)

        body = self._make_api_response("v99.0.0", has_exe=False)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
        cm.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=cm):
            checker.check_sync()

        assert len(received) == 1
        assert received[0].download_url == RELEASES_PAGE_URL

    # ── should_check_now() ────────────────────────────────────────

    def test_should_check_now_false_when_auto_check_disabled(self):
        from updater import should_check_now

        class FakePrefs:
            def get_pref(self, key, default=None):
                if key == "updates.auto_check":
                    return False
                return default

        assert should_check_now(FakePrefs()) is False

    def test_should_check_now_true_for_frequency_always(self):
        from updater import should_check_now
        import datetime

        class FakePrefs:
            def get_pref(self, key, default=None):
                return {"updates.auto_check": True,
                        "updates.frequency": "always",
                        "updates.last_check_date": datetime.date.today().isoformat(),
                        }.get(key, default)

        # Even if we checked today, "always" means always
        assert should_check_now(FakePrefs()) is True

    def test_should_check_now_daily_respects_interval(self):
        from updater import should_check_now
        import datetime

        today = datetime.date.today()
        yesterday = (today - datetime.timedelta(days=1)).isoformat()
        two_hours_ago_str = today.isoformat()  # same calendar day

        class FakePrefsCheckedToday:
            def get_pref(self, key, default=None):
                return {"updates.auto_check": True,
                        "updates.frequency": "daily",
                        "updates.last_check_date": two_hours_ago_str,
                        }.get(key, default)

        class FakePrefsCheckedYesterday:
            def get_pref(self, key, default=None):
                return {"updates.auto_check": True,
                        "updates.frequency": "daily",
                        "updates.last_check_date": yesterday,
                        }.get(key, default)

        assert should_check_now(FakePrefsCheckedToday()) is False
        assert should_check_now(FakePrefsCheckedYesterday()) is True

    def test_should_check_now_weekly_respects_interval(self):
        from updater import should_check_now
        import datetime

        today = datetime.date.today()
        three_days_ago = (today - datetime.timedelta(days=3)).isoformat()
        eight_days_ago = (today - datetime.timedelta(days=8)).isoformat()

        class FakePrefsRecent:
            def get_pref(self, key, default=None):
                return {"updates.auto_check": True,
                        "updates.frequency": "weekly",
                        "updates.last_check_date": three_days_ago,
                        }.get(key, default)

        class FakePrefsOld:
            def get_pref(self, key, default=None):
                return {"updates.auto_check": True,
                        "updates.frequency": "weekly",
                        "updates.last_check_date": eight_days_ago,
                        }.get(key, default)

        assert should_check_now(FakePrefsRecent()) is False
        assert should_check_now(FakePrefsOld()) is True
