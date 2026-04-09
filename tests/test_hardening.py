"""
tests/test_hardening.py

Targeted verification of the session-persistence and acquisition-pipeline
hardening pass.  Tests are grouped into four areas:

  1. Atomic JSON write failure behaviour
  2. Pipeline concurrency fencing
  3. DataTab stale-worker suppression
  4. Float32 downcast tolerance
"""

from __future__ import annotations

import json
import os
import sys
import glob
import time
import threading
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. Atomic JSON write failure behaviour                             #
# ================================================================== #

class TestAtomicWriteJson:
    """Verify atomic_write_json temp-file cleanup and original-file safety."""

    def test_successful_write_creates_file(self, tmp_path):
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        data = {"uid": "test123", "schema_version": 5}
        atomic_write_json(target, data)

        assert os.path.isfile(target)
        with open(target) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_successful_write_overwrites_existing(self, tmp_path):
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})

        with open(target) as f:
            assert json.load(f) == {"v": 2}

    def test_no_temp_files_left_on_success(self, tmp_path):
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        atomic_write_json(target, {"ok": True})

        leftovers = glob.glob(str(tmp_path / ".session_*"))
        assert leftovers == [], f"Temp files left behind: {leftovers}"

    def test_original_intact_when_json_dump_fails(self, tmp_path):
        """Unserializable data → json.dump raises → original file untouched."""
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        original = {"original": "data"}
        atomic_write_json(target, original)

        # object() is not JSON-serializable
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": object()})

        # Original content preserved
        with open(target) as f:
            assert json.load(f) == original

    def test_temp_cleaned_up_on_json_dump_failure(self, tmp_path):
        """After a failed write, no temp files remain."""
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": object()})

        leftovers = glob.glob(str(tmp_path / ".session_*"))
        assert leftovers == [], f"Temp files left behind: {leftovers}"

    def test_original_intact_when_fsync_fails(self, tmp_path):
        """Simulated fsync failure → original file untouched."""
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        original = {"key": "original_value"}
        atomic_write_json(target, original)

        with patch("utils.os.fsync",
                   side_effect=OSError("disk I/O error")):
            with pytest.raises(OSError, match="disk I/O error"):
                atomic_write_json(target, {"key": "new_value"})

        with open(target) as f:
            assert json.load(f) == original

    def test_temp_cleaned_up_on_fsync_failure(self, tmp_path):
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")

        with patch("utils.os.fsync",
                   side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                atomic_write_json(target, {"data": 1})

        leftovers = glob.glob(str(tmp_path / ".session_*"))
        assert leftovers == [], f"Temp files left behind: {leftovers}"

    def test_original_intact_when_replace_fails(self, tmp_path):
        """Simulated os.replace failure → original preserved, temp cleaned."""
        from acquisition.storage._atomic import atomic_write_json

        target = str(tmp_path / "session.json")
        original = {"version": "old"}
        atomic_write_json(target, original)

        with patch("utils.os.replace",
                   side_effect=OSError("permission denied")):
            with pytest.raises(OSError, match="permission denied"):
                atomic_write_json(target, {"version": "new"})

        with open(target) as f:
            assert json.load(f) == original

        leftovers = glob.glob(str(tmp_path / ".session_*"))
        assert leftovers == [], f"Temp files left behind: {leftovers}"


class TestUpdateFieldMemoryAfterDisk:
    """_update_field must not mutate in-memory index when disk write fails."""

    @pytest.fixture
    def populated_manager(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2
        session = mgr.save_result(result, label="persist_test",
                                  operator="tester")
        return mgr, session.meta.uid

    def test_memory_unchanged_on_disk_failure(self, populated_manager):
        mgr, uid = populated_manager

        meta_before = mgr.get_meta(uid)
        original_label = meta_before.label

        with patch("acquisition.storage.session_manager.atomic_write_json",
                   side_effect=OSError("disk full")):
            mgr.update_label(uid, "SHOULD_NOT_PERSIST")

        meta_after = mgr.get_meta(uid)
        assert meta_after.label == original_label, \
            "In-memory label was mutated despite disk write failure"

    def test_memory_updated_on_disk_success(self, populated_manager):
        mgr, uid = populated_manager
        mgr.update_label(uid, "new_label")
        assert mgr.get_meta(uid).label == "new_label"


class TestDeleteDiskBeforeIndex:
    """delete() must remove from index only after disk delete succeeds."""

    @pytest.fixture
    def populated_manager(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2
        session = mgr.save_result(result, label="delete_test",
                                  operator="tester")
        return mgr, session.meta.uid

    def test_index_preserved_when_rmtree_fails(self, populated_manager):
        mgr, uid = populated_manager

        with patch("acquisition.storage.session_manager.shutil.rmtree",
                   side_effect=OSError("permission denied")):
            ok = mgr.delete(uid)

        assert not ok, "delete() should return False on rmtree failure"
        assert mgr.get_meta(uid) is not None, \
            "Session vanished from index despite failed disk delete"

    def test_index_cleared_after_successful_delete(self, populated_manager):
        mgr, uid = populated_manager
        assert mgr.delete(uid) is True
        assert mgr.get_meta(uid) is None


class TestSessionSaveMemoryAfterDisk:
    """Session.save() must set meta.path only after JSON is committed."""

    def test_path_not_set_on_json_failure(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.session import Session

        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2
        session = Session.from_result(result, label="path_test")

        assert session.meta.path == "", "path should be empty before save"

        with patch("acquisition.storage.session.atomic_write_json",
                   side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                session.save(str(tmp_path))

        assert session.meta.path == "", \
            "meta.path was set despite JSON write failure"

    def test_path_set_on_success(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.session import Session

        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2
        session = Session.from_result(result, label="path_ok")
        folder = session.save(str(tmp_path))

        assert session.meta.path == folder
        assert os.path.isfile(os.path.join(folder, "session.json"))


class TestSaveAnalysisRollback:
    """save_analysis() must roll back meta on JSON failure."""

    def test_analysis_result_reverted_on_failure(self, tmp_path):
        from acquisition.pipeline import AcquisitionResult
        from acquisition.session import Session

        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2

        session = Session.from_result(result, label="rollback_test")
        session.save(str(tmp_path))

        assert session.meta.analysis_result is None

        # Create a mock AnalysisResult with the to_dict method
        mock_analysis = MagicMock()
        mock_analysis.to_dict.return_value = {"verdict": "pass", "hotspots": []}
        mock_analysis.overlay_rgb = None
        mock_analysis.binary_mask = None

        with patch("acquisition.storage.session.atomic_write_json",
                   side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                session.save_analysis(mock_analysis)

        assert session.meta.analysis_result is None, \
            "analysis_result was not rolled back after JSON write failure"


class TestMigrationBackup:
    """Schema migration must create a backup before modifying data."""

    def test_backup_created_on_migration(self, tmp_path):
        from acquisition.session import Session
        from acquisition.pipeline import AcquisitionResult

        # Create a session, then downgrade its schema to force migration
        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32) * 1.0
        result.cold_captured = result.hot_captured = 2
        session = Session.from_result(result, label="backup_test")
        folder = session.save(str(tmp_path))

        # Downgrade schema version
        json_path = os.path.join(folder, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        original_version = data["schema_version"]
        data["schema_version"] = 0
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Load triggers migration
        loaded = Session.load(folder)
        assert loaded is not None

        # Backup file should exist
        bak_path = f"{json_path}.v0.bak"
        assert os.path.isfile(bak_path), "Migration backup was not created"

        # Backup content should have the old schema version
        with open(bak_path) as f:
            bak_data = json.load(f)
        assert bak_data["schema_version"] == 0


# ================================================================== #
#  2. Pipeline concurrency fencing                                     #
# ================================================================== #

class TestPipelineConcurrency:
    """Verify lifecycle lock prevents overlapping acquisitions."""

    def _make_pipeline(self):
        """Create a pipeline with a mock camera that blocks on grab."""
        from acquisition.pipeline import AcquisitionPipeline

        cam = MagicMock()
        cam._cfg = {"exposure_us": 100, "gain": 0}

        pipeline = AcquisitionPipeline(cam)
        return pipeline, cam

    def test_double_start_raises(self):
        """Two concurrent start() calls: second must raise RuntimeError."""
        from acquisition.pipeline import AcqState

        pipeline, cam = self._make_pipeline()

        # Make camera.grab() block indefinitely
        block = threading.Event()
        frame = MagicMock()
        frame.data = np.ones((8, 8), dtype=np.uint16)

        def blocking_grab(timeout_ms=2000):
            block.wait()
            return frame
        cam.grab = blocking_grab

        pipeline.start(n_frames=1000)  # will block inside capture loop

        # Give thread time to enter CAPTURING state
        for _ in range(50):
            if pipeline.state == AcqState.CAPTURING:
                break
            time.sleep(0.02)

        with pytest.raises(RuntimeError, match="already in progress"):
            pipeline.start(n_frames=10)

        # Cleanup
        pipeline.abort()
        block.set()

    def test_start_abort_start_no_overlap(self):
        """start() → abort() → start() must not create overlapping threads."""
        from acquisition.pipeline import AcqState

        pipeline, cam = self._make_pipeline()

        frame = MagicMock()
        frame.data = np.ones((8, 8), dtype=np.uint16)

        call_count = 0
        abort_seen = threading.Event()

        original_grab = None

        def counting_grab(timeout_ms=2000):
            nonlocal call_count
            call_count += 1
            if call_count > 5:
                # Give time for abort to be processed
                time.sleep(0.01)
            return frame
        cam.grab = counting_grab

        # First acquisition
        pipeline.start(n_frames=100)
        time.sleep(0.05)  # let it start
        pipeline.abort()

        # Wait for first thread to finish
        if pipeline._thread is not None:
            pipeline._thread.join(timeout=3.0)

        # Pipeline should be in ABORTED state
        assert pipeline.state in (AcqState.ABORTED, AcqState.IDLE,
                                  AcqState.COMPLETE, AcqState.ERROR)

        # Second acquisition should start cleanly
        call_count = 0
        pipeline.start(n_frames=5)
        pipeline._thread.join(timeout=5.0)

        # Should have completed the second acquisition
        assert pipeline.state in (AcqState.COMPLETE, AcqState.ABORTED,
                                  AcqState.ERROR)

    def test_concurrent_start_calls_from_threads(self):
        """Multiple threads calling start() simultaneously: exactly one wins."""
        from acquisition.pipeline import AcqState

        pipeline, cam = self._make_pipeline()

        block = threading.Event()
        frame = MagicMock()
        frame.data = np.ones((8, 8), dtype=np.uint16)

        def blocking_grab(timeout_ms=2000):
            block.wait(timeout=0.5)
            return frame
        cam.grab = blocking_grab

        results = []
        barrier = threading.Barrier(3)

        def try_start():
            barrier.wait()  # synchronize thread launch
            try:
                pipeline.start(n_frames=1000)
                results.append("ok")
            except RuntimeError:
                results.append("rejected")

        threads = [threading.Thread(target=try_start) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        pipeline.abort()
        block.set()

        assert results.count("ok") == 1, \
            f"Expected exactly 1 successful start, got: {results}"
        assert results.count("rejected") == 2, \
            f"Expected exactly 2 rejected starts, got: {results}"


class TestCheckpointWriterIdempotent:
    """_CheckpointWriter.start()/stop() must be safe to call repeatedly."""

    def test_double_start_is_noop(self):
        from acquisition.pipeline import _CheckpointWriter

        writer = _CheckpointWriter()
        writer.start()
        thread1 = writer._thread

        writer.start()  # should be idempotent
        thread2 = writer._thread

        assert thread1 is thread2, "Double start created a new thread"
        writer.stop()

    def test_double_stop_is_noop(self):
        from acquisition.pipeline import _CheckpointWriter

        writer = _CheckpointWriter()
        writer.start()
        writer.stop()
        writer.stop()  # should not raise

    def test_stop_without_start_is_noop(self):
        from acquisition.pipeline import _CheckpointWriter

        writer = _CheckpointWriter()
        writer.stop()  # should not raise

    def test_start_after_stop_creates_new_thread(self):
        from acquisition.pipeline import _CheckpointWriter

        writer = _CheckpointWriter()
        writer.start()
        writer.stop()
        writer.start()

        assert writer._thread is not None
        assert writer._thread.is_alive()
        writer.stop()


# ================================================================== #
#  3. DataTab stale-worker suppression                                 #
# ================================================================== #

class TestSessionLoadWorkerCancellation:
    """Verify _SessionLoadWorker honours interruption and generation tokens."""

    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    def test_interrupted_before_load_emits_nothing(self, qapp):
        """If interrupted before load starts, no signal is emitted."""
        from acquisition.data_tab import _SessionLoadWorker

        mgr = MagicMock()
        # load should NOT be called
        mgr.load.return_value = MagicMock()

        worker = _SessionLoadWorker(mgr, "uid1")
        worker.requestInterruption()

        loaded_results = []
        error_results = []
        worker.loaded.connect(loaded_results.append)
        worker.error.connect(error_results.append)

        worker.start()
        worker.wait(3000)

        assert loaded_results == [], "loaded signal emitted despite interruption"
        assert error_results == [], "error signal emitted despite interruption"

    def test_interrupted_after_load_unloads_session(self, qapp):
        """If interrupted after load completes, session is unloaded and no
        signal is emitted."""
        from acquisition.data_tab import _SessionLoadWorker

        mock_session = MagicMock()
        mgr = MagicMock()

        interrupt_after_load = threading.Event()

        def slow_load(uid):
            result = mock_session
            # Simulate: by the time load returns, interruption was requested
            interrupt_after_load.wait(timeout=2.0)
            return result

        mgr.load = slow_load

        worker = _SessionLoadWorker(mgr, "uid1")

        loaded_results = []
        worker.loaded.connect(loaded_results.append)

        worker.start()
        time.sleep(0.05)  # let run() enter the load call

        worker.requestInterruption()
        interrupt_after_load.set()

        worker.wait(3000)

        assert loaded_results == [], "loaded signal emitted despite interruption"
        mock_session.unload.assert_called_once()

    def test_generation_counter_increments(self, qapp):
        """Each worker gets a unique, increasing generation token."""
        from acquisition.data_tab import _SessionLoadWorker

        mgr = MagicMock()
        w1 = _SessionLoadWorker(mgr, "a")
        w2 = _SessionLoadWorker(mgr, "b")
        w3 = _SessionLoadWorker(mgr, "c")

        assert w1.generation < w2.generation < w3.generation

    def test_error_suppressed_when_interrupted(self, qapp):
        """If load raises but worker was interrupted, error is not emitted."""
        from acquisition.data_tab import _SessionLoadWorker

        mgr = MagicMock()
        mgr.load.side_effect = RuntimeError("boom")

        worker = _SessionLoadWorker(mgr, "uid1")
        worker.requestInterruption()

        error_results = []
        worker.error.connect(error_results.append)

        worker.start()
        worker.wait(3000)

        assert error_results == [], "error emitted despite interruption"


class TestStaleResultRejection:
    """Verify that late results from a superseded worker do not pollute
    the display.  This tests the generation-token gating logic that lives
    in DataTab._load_and_display closures.

    Because DataTab requires a full Qt widget hierarchy we test the
    mechanism in isolation by simulating the closure logic directly.
    """

    def test_stale_loaded_signal_is_discarded(self):
        """Simulate: worker gen=1 finishes after worker gen=2 has started.
        The gen=1 result must be discarded."""

        # State that the closure captures
        active_generation = 2  # newer worker is generation 2
        display_calls = []

        def on_loaded(session, *, gen, active_gen_ref):
            """Mimics the _on_loaded closure in _load_and_display."""
            if gen != active_gen_ref[0]:
                if session is not None:
                    session.unload()
                return  # stale — discard
            display_calls.append(session)

        stale_session = MagicMock()
        active_gen_ref = [2]

        # Stale result from gen=1
        on_loaded(stale_session, gen=1, active_gen_ref=active_gen_ref)
        assert display_calls == [], "Stale gen=1 result was not discarded"
        stale_session.unload.assert_called_once()

        # Current result from gen=2
        current_session = MagicMock()
        on_loaded(current_session, gen=2, active_gen_ref=active_gen_ref)
        assert display_calls == [current_session], \
            "Current gen=2 result was not displayed"

    def test_stale_error_is_discarded(self):
        """Error from a superseded worker must be silently dropped."""
        error_displays = []
        active_gen_ref = [3]

        def on_error(msg, *, gen, active_gen_ref):
            if gen != active_gen_ref[0]:
                return  # stale
            error_displays.append(msg)

        on_error("stale error", gen=1, active_gen_ref=active_gen_ref)
        assert error_displays == []

        on_error("current error", gen=3, active_gen_ref=active_gen_ref)
        assert error_displays == ["current error"]


# ================================================================== #
#  4. Float32 downcast tolerance                                       #
# ================================================================== #

class TestFloat32Tolerance:
    """Verify that float32 storage introduces acceptable rounding error
    relative to the prior float64 regime.

    Thermoreflectance values are typically 1e-4 to 1e-2. Float32 has
    ~7 decimal digits of precision (23-bit mantissa), so for a value of
    1e-4 the absolute precision is ~1e-11 — far below measurement noise.
    """

    @pytest.fixture
    def synthetic_frames(self):
        """Camera-realistic uint16 frames with a known temperature signal."""
        rng = np.random.default_rng(42)
        H, W = 128, 128
        cold = rng.integers(2000, 50000, (H, W), dtype=np.uint16).astype(np.float64)
        # Inject known ΔR/R ≈ 5e-4 (typical for thermoreflectance)
        signal = 5e-4
        hot = cold * (1.0 + signal)
        # Add realistic photon noise
        hot += rng.normal(0, 2.0, (H, W))
        return cold, hot, signal

    def test_drr_float32_vs_float64_max_error(self, synthetic_frames):
        """Max absolute error from float32 storage is negligible."""
        cold, hot, expected_signal = synthetic_frames

        drr_f64 = ((hot - cold) / cold)
        drr_f32 = drr_f64.astype(np.float32)

        max_abs_err = float(np.max(np.abs(drr_f64 - drr_f32.astype(np.float64))))
        # Float32 relative error is ~1.2e-7; for ΔR/R ~5e-4 that's ~6e-11 absolute
        assert max_abs_err < 1e-8, \
            f"Max abs error {max_abs_err:.2e} exceeds 1e-8 tolerance"

    def test_drr_snr_preserved_in_float32(self, synthetic_frames):
        """SNR computed from float32 matches float64 to within 0.01 dB."""
        cold, hot, _ = synthetic_frames

        drr_f64 = ((hot - cold) / cold)
        drr_f32 = drr_f64.astype(np.float32)

        def snr_db(arr):
            sig = float(np.nanmean(np.abs(arr)))
            noise = float(np.nanstd(arr))
            if sig <= 0 or noise == 0:
                return float('inf')
            return float(20 * np.log10(sig / noise))

        snr64 = snr_db(drr_f64)
        snr32 = snr_db(drr_f32)

        assert abs(snr64 - snr32) < 0.01, \
            f"SNR diverged: f64={snr64:.4f} dB, f32={snr32:.4f} dB"

    def test_cold_hot_avg_roundtrip_through_float32(self, synthetic_frames):
        """Cold/hot averages survive float32 → save → load → float64 recast
        with negligible error."""
        cold_f64, hot_f64, _ = synthetic_frames

        cold_f32 = cold_f64.astype(np.float32)
        hot_f32 = hot_f64.astype(np.float32)

        # Recast back to float64 (as _compute does)
        cold_back = cold_f32.astype(np.float64)
        hot_back = hot_f32.astype(np.float64)

        # Relative error on cold (uint16-scale values: 2000–50000)
        rel_err_cold = np.max(np.abs(cold_f64 - cold_back) / cold_f64)
        rel_err_hot = np.max(np.abs(hot_f64 - hot_back) / hot_f64)

        # Float32 relative error bound: 2^-23 ≈ 1.19e-7
        assert rel_err_cold < 1e-6, \
            f"Cold avg relative error {rel_err_cold:.2e} exceeds 1e-6"
        assert rel_err_hot < 1e-6, \
            f"Hot avg relative error {rel_err_hot:.2e} exceeds 1e-6"

    def test_drr_computation_still_uses_float64_internally(self):
        """Verify that _compute() casts to float64 before division,
        regardless of input dtype."""
        from acquisition.pipeline import AcquisitionPipeline, AcquisitionResult

        cam = MagicMock()
        cam._cfg = {}
        pipeline = AcquisitionPipeline(cam)

        result = AcquisitionResult(n_frames=4)
        # Provide float32 inputs (as the pipeline now stores)
        rng = np.random.default_rng(99)
        result.cold_avg = (rng.integers(2000, 50000, (32, 32),
                           dtype=np.uint16)).astype(np.float32)
        result.hot_avg = (result.cold_avg * 1.0005).astype(np.float32)

        pipeline._compute(result)

        # Result should be float32 (downcast at end of _compute)
        assert result.delta_r_over_r.dtype == np.float32
        assert result.difference.dtype == np.float32

        # But values should be correct (computed in float64 internally)
        expected_drr = (result.hot_avg.astype(np.float64)
                        - result.cold_avg.astype(np.float64)) \
                       / result.cold_avg.astype(np.float64)
        max_err = float(np.nanmax(np.abs(
            expected_drr - result.delta_r_over_r.astype(np.float64))))
        assert max_err < 1e-7, \
            f"_compute output error {max_err:.2e} is too large"

    def test_nan_masking_preserved_in_float32(self):
        """Dark-pixel NaN masking survives float32 downcast."""
        from acquisition.pipeline import AcquisitionPipeline, AcquisitionResult

        cam = MagicMock()
        cam._cfg = {}
        pipeline = AcquisitionPipeline(cam)

        result = AcquisitionResult(n_frames=4)
        cold = np.full((32, 32), 30000.0, dtype=np.float32)
        cold[0:4, 0:4] = 1.0  # dark region
        hot = cold * 1.001

        result.cold_avg = cold
        result.hot_avg = hot

        pipeline._compute(result)

        # Dark pixels should be NaN in float32 result
        dark_region = result.delta_r_over_r[0:4, 0:4]
        assert np.all(np.isnan(dark_region)), \
            "NaN masking lost in float32 downcast"

        # Non-dark pixels should have valid values
        valid_region = result.delta_r_over_r[10:20, 10:20]
        assert np.all(np.isfinite(valid_region)), \
            "Valid pixels became NaN unexpectedly"


# ================================================================== #
#  5. Schema rejection and backup edge cases                           #
# ================================================================== #

class TestFutureSchemaRejection:
    """Verify hard rejection of sessions from newer builds."""

    def test_reject_future_schema_raises(self):
        from acquisition.schema_migrations import reject_future_schema, FutureSchemaError

        with pytest.raises(FutureSchemaError, match="v999"):
            reject_future_schema(999)

    def test_current_schema_accepted(self):
        from acquisition.schema_migrations import reject_future_schema, CURRENT_SCHEMA

        # Should not raise
        reject_future_schema(CURRENT_SCHEMA)

    def test_old_schema_accepted(self):
        from acquisition.schema_migrations import reject_future_schema

        reject_future_schema(0)
        reject_future_schema(3)

    def test_load_meta_returns_none_for_future_schema(self, tmp_path):
        """load_meta gracefully returns None instead of crashing."""
        from acquisition.pipeline import AcquisitionResult
        from acquisition.session import Session

        result = AcquisitionResult(
            n_frames=2, exposure_us=500.0, gain_db=0.0,
            timestamp=time.time())
        result.cold_avg = np.ones((8, 8), dtype=np.float32) * 1000
        result.hot_avg = result.cold_avg * 1.001
        result.delta_r_over_r = np.ones((8, 8), dtype=np.float32) * 0.001
        result.difference = np.ones((8, 8), dtype=np.float32)
        result.cold_captured = result.hot_captured = 2
        session = Session.from_result(result, label="future_test")
        folder = session.save(str(tmp_path))

        json_path = os.path.join(folder, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data["schema_version"] = 999
        with open(json_path, "w") as f:
            json.dump(data, f)

        assert Session.load_meta(folder) is None


# ================================================================== #
#  6. Config atomic writes (Item 4)                                    #
# ================================================================== #

class TestConfigAtomicPrefs:
    """Verify that config._save_prefs() uses atomic writes."""

    def test_prefs_survive_crash_mid_write(self, tmp_path, monkeypatch):
        """Simulated fsync failure leaves original prefs intact."""
        import config as cfg_mod

        prefs_path = tmp_path / "prefs.json"
        original = {"ui": {"theme": "dark"}}

        # Seed the file
        with open(prefs_path, "w") as f:
            json.dump(original, f)

        monkeypatch.setattr(cfg_mod, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(cfg_mod, "_prefs", {"ui": {"theme": "light"}})

        with patch("utils.os.fsync", side_effect=OSError("disk full")):
            cfg_mod._save_prefs()  # should log, not crash

        # Original must still be intact (atomic write rolled back)
        with open(prefs_path) as f:
            assert json.load(f) == original

    def test_prefs_written_on_success(self, tmp_path, monkeypatch):
        """Normal save writes the new data atomically."""
        import config as cfg_mod

        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr(cfg_mod, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(cfg_mod, "_prefs", {"key": "value"})

        cfg_mod._save_prefs()

        with open(prefs_path) as f:
            assert json.load(f) == {"key": "value"}

    def test_no_bak_file_created(self, tmp_path, monkeypatch):
        """The old shutil.copy2 .bak logic has been replaced by atomic write.
        No .bak file should be created."""
        import config as cfg_mod

        prefs_path = tmp_path / "prefs.json"
        with open(prefs_path, "w") as f:
            json.dump({"old": True}, f)

        monkeypatch.setattr(cfg_mod, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(cfg_mod, "_prefs", {"new": True})

        cfg_mod._save_prefs()

        bak = prefs_path.with_suffix(".json.bak")
        assert not bak.exists(), "Stale .bak logic still in place"


class TestUserPrefsAtomicWrite:
    """Verify auth.user_prefs.UserPrefs._save() uses atomic writes."""

    def test_user_prefs_survive_crash(self, tmp_path, monkeypatch):
        """Simulated fsync failure leaves original user prefs intact."""
        from auth.user_prefs import UserPrefs

        uid_dir = tmp_path / "users" / "test_user"
        uid_dir.mkdir(parents=True)
        prefs_file = uid_dir / "prefs.json"

        original = {"ui": {"theme": "dark"}}
        with open(prefs_file, "w") as f:
            json.dump(original, f)

        # Monkey-patch _USERS_DIR so UserPrefs finds this dir
        import auth.user_prefs as up_mod
        monkeypatch.setattr(up_mod, "_USERS_DIR", tmp_path / "users")

        prefs = UserPrefs("test_user")
        assert prefs.get("ui.theme") == "dark"

        with patch("utils.os.fsync", side_effect=OSError("disk full")):
            prefs.set("ui.theme", "light")  # should log, not crash

        # Original must still be intact
        with open(prefs_file) as f:
            data = json.load(f)
        assert data["ui"]["theme"] == "dark"

    def test_user_prefs_written_on_success(self, tmp_path, monkeypatch):
        import auth.user_prefs as up_mod
        monkeypatch.setattr(up_mod, "_USERS_DIR", tmp_path / "users")

        prefs = up_mod.UserPrefs("new_user")
        prefs.set("ui.theme", "light")

        prefs_file = tmp_path / "users" / "new_user" / "prefs.json"
        with open(prefs_file) as f:
            data = json.load(f)
        assert data["ui"]["theme"] == "light"


# ================================================================== #
#  7. ThermalGuard safety (Item 3)                                     #
# ================================================================== #

class TestThermalGuardNoneNaN:
    """ThermalGuard.check() must handle None and NaN actual_temp safely."""

    def _make_guard(self):
        from hardware.thermal_guard import ThermalGuard, AlarmState
        from hardware.tec.base import TecStatus

        tec = MagicMock()
        alarm_calls = []
        guard = ThermalGuard(
            index=0,
            tec=tec,
            cfg={"temp_min": -10.0, "temp_max": 85.0,
                 "temp_warning_margin": 5.0},
            on_alarm=lambda *a: alarm_calls.append(a),
        )
        return guard, tec, alarm_calls, AlarmState, TecStatus

    def test_none_actual_temp_skips_check(self):
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp=None, error=None)
        # Must not raise TypeError
        result = guard.check(status)
        assert result == AlarmState.NORMAL
        assert alarm_calls == []

    def test_nan_actual_temp_skips_check(self):
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp=float("nan"), error=None)
        result = guard.check(status)
        assert result == AlarmState.NORMAL
        assert alarm_calls == []

    def test_inf_actual_temp_skips_check(self):
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp=float("inf"), error=None)
        result = guard.check(status)
        assert result == AlarmState.NORMAL
        assert alarm_calls == []

    def test_negative_inf_actual_temp_skips_check(self):
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp=float("-inf"), error=None)
        result = guard.check(status)
        assert result == AlarmState.NORMAL
        assert alarm_calls == []

    def test_valid_temp_still_triggers_alarm(self):
        """Confirm valid over-limit temperature still triggers alarm."""
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp=90.0, error=None)
        result = guard.check(status)
        assert result == AlarmState.ALARM
        assert len(alarm_calls) == 1
        tec.disable.assert_called_once()

    def test_string_actual_temp_skips_check(self):
        """Non-numeric actual_temp must not raise or trigger alarm."""
        guard, tec, alarm_calls, AlarmState, TecStatus = self._make_guard()

        status = TecStatus(actual_temp="ERROR", error=None)
        result = guard.check(status)
        assert result == AlarmState.NORMAL
        assert alarm_calls == []


class TestThermalGuardDisableFailure:
    """When tec.disable() fails in ALARM, the message must escalate."""

    def test_disable_failure_escalates_in_message(self):
        from hardware.thermal_guard import ThermalGuard, AlarmState
        from hardware.tec.base import TecStatus

        tec = MagicMock()
        tec.disable.side_effect = RuntimeError("I2C bus error")

        alarm_msgs = []
        guard = ThermalGuard(
            index=0,
            tec=tec,
            cfg={"temp_min": -10.0, "temp_max": 85.0},
            on_alarm=lambda idx, msg, actual, limit: alarm_msgs.append(msg),
        )

        status = TecStatus(actual_temp=90.0, error=None)
        result = guard.check(status)

        assert result == AlarmState.ALARM
        assert len(alarm_msgs) == 1
        assert "CRITICAL" in alarm_msgs[0], \
            f"Alarm message should mention CRITICAL, got: {alarm_msgs[0]}"
        assert "FAILED" in alarm_msgs[0], \
            f"Alarm message should mention FAILED, got: {alarm_msgs[0]}"

    def test_disable_success_normal_message(self):
        from hardware.thermal_guard import ThermalGuard, AlarmState
        from hardware.tec.base import TecStatus

        tec = MagicMock()

        alarm_msgs = []
        guard = ThermalGuard(
            index=0,
            tec=tec,
            cfg={"temp_min": -10.0, "temp_max": 85.0},
            on_alarm=lambda idx, msg, actual, limit: alarm_msgs.append(msg),
        )

        status = TecStatus(actual_temp=90.0, error=None)
        guard.check(status)

        assert len(alarm_msgs) == 1
        assert "CRITICAL" not in alarm_msgs[0], \
            "Normal alarm should NOT contain CRITICAL"


# ================================================================== #
#  8. ThermalGuard lock refactor — callbacks outside lock (Item 1)     #
# ================================================================== #

class TestThermalGuardLockRefactor:
    """Verify callbacks and tec.disable() execute outside the guard lock."""

    def _make_guard(self, **cb_overrides):
        from hardware.thermal_guard import ThermalGuard, AlarmState
        from hardware.tec.base import TecStatus

        tec = MagicMock()
        events = []  # (event_type, lock_held)

        def _check_lock(guard, tag):
            """Record whether the guard lock is held when this callback fires."""
            held = not guard._lock.acquire(blocking=False)
            if not held:
                guard._lock.release()
            events.append((tag, held))

        guard = ThermalGuard(
            index=0,
            tec=tec,
            cfg={"temp_min": -10.0, "temp_max": 85.0,
                 "temp_warning_margin": 5.0},
        )

        # Patch callbacks to record lock state
        guard._on_alarm = cb_overrides.get(
            "on_alarm",
            lambda i, msg, a, l: _check_lock(guard, "alarm"))
        guard._on_warning = cb_overrides.get(
            "on_warning",
            lambda i, msg, a, l: _check_lock(guard, "warning"))
        guard._on_clear = cb_overrides.get(
            "on_clear",
            lambda i: _check_lock(guard, "clear"))

        # Also record lock state when tec.disable is called
        original_disable = tec.disable
        def _disable_with_check():
            _check_lock(guard, "disable")
            return original_disable()
        tec.disable = _disable_with_check

        return guard, tec, events, AlarmState, TecStatus

    def test_alarm_callback_runs_outside_lock(self):
        guard, tec, events, AlarmState, TecStatus = self._make_guard()

        guard.check(TecStatus(actual_temp=90.0, error=None))

        assert guard.state == AlarmState.ALARM
        # Both disable and alarm callback must have fired with lock NOT held
        tags = [tag for tag, held in events]
        assert "disable" in tags, "tec.disable() was not called"
        assert "alarm" in tags, "on_alarm was not called"
        for tag, held in events:
            assert not held, f"{tag} was called with lock HELD"

    def test_warning_callback_runs_outside_lock(self):
        guard, tec, events, AlarmState, TecStatus = self._make_guard()

        # Temperature in warning zone (80.5 > temp_max - margin = 85 - 5 = 80)
        guard.check(TecStatus(actual_temp=80.5, error=None))

        assert guard.state == AlarmState.WARNING
        assert len(events) == 1
        assert events[0] == ("warning", False), \
            "on_warning was called with lock held"

    def test_clear_callback_runs_outside_lock(self):
        guard, tec, events, AlarmState, TecStatus = self._make_guard()

        # Enter warning zone first
        guard.check(TecStatus(actual_temp=80.5, error=None))
        events.clear()

        # Return to comfortably within limits (needs to pass hysteresis)
        guard.check(TecStatus(actual_temp=40.0, error=None))

        assert guard.state == AlarmState.NORMAL
        assert len(events) == 1
        assert events[0] == ("clear", False), \
            "on_clear was called with lock held"

    def test_acknowledge_clear_runs_outside_lock(self):
        guard, tec, events, AlarmState, TecStatus = self._make_guard()

        # Trigger alarm
        guard.check(TecStatus(actual_temp=90.0, error=None))
        events.clear()

        # Acknowledge — on_clear should fire outside lock
        guard.acknowledge()

        assert guard.state == AlarmState.NORMAL
        assert len(events) == 1
        assert events[0] == ("clear", False), \
            "on_clear in acknowledge() was called with lock held"

    def test_callback_reentrance_does_not_deadlock(self):
        """If a callback re-enters check(), it must not deadlock."""
        from hardware.thermal_guard import ThermalGuard, AlarmState
        from hardware.tec.base import TecStatus

        tec = MagicMock()
        reentry_result = []

        guard = ThermalGuard(
            index=0, tec=tec,
            cfg={"temp_min": -10.0, "temp_max": 85.0,
                 "temp_warning_margin": 5.0},
        )

        def _reentrant_warning(i, msg, a, l):
            # Re-enter check() from inside the warning callback.
            # With old code (callback under lock) this would deadlock
            # on a non-reentrant Lock.
            result = guard.check(TecStatus(actual_temp=40.0, error=None))
            reentry_result.append(result)

        guard._on_warning = _reentrant_warning

        # This should not deadlock
        import signal
        def _timeout(signum, frame):
            raise TimeoutError("Deadlock detected — callback re-entry blocked")
        old_handler = signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(3)  # 3-second timeout
        try:
            guard.check(TecStatus(actual_temp=80.5, error=None))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        # The re-entrant check(40.0) sees WARNING state and 40°C is inside
        # hysteresis, so it clears back to NORMAL.  The key assertion is
        # that it didn't deadlock — the state value is a secondary check.
        assert guard.state == AlarmState.NORMAL
        assert len(reentry_result) == 1, "Re-entrant check() did not execute"


# ================================================================== #
#  9. Preference defaults registry & validation (Items 4-5)            #
# ================================================================== #

class TestPrefDefaultsRegistry:
    """Verify the centralized _PREF_DEFAULTS registry."""

    def test_registered_default_used_when_no_caller_default(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {})
        # "ui.theme" has a registered default of "auto"
        assert cfg_mod.get_pref("ui.theme") == "auto"

    def test_caller_default_overrides_registry(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {})
        # Caller explicitly supplies "dark" — overrides registry "auto"
        assert cfg_mod.get_pref("ui.theme", "dark") == "dark"

    def test_persisted_value_overrides_both_defaults(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {"ui": {"theme": "light"}})
        assert cfg_mod.get_pref("ui.theme") == "light"
        assert cfg_mod.get_pref("ui.theme", "dark") == "light"

    def test_unregistered_key_returns_none_without_default(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {})
        assert cfg_mod.get_pref("nonexistent.key") is None

    def test_pref_default_helper(self):
        import config as cfg_mod
        assert cfg_mod.pref_default("ui.theme") == "auto"
        assert cfg_mod.pref_default("nonexistent.key") is None


class TestPrefValidation:
    """Verify preference validation and coercion."""

    def test_valid_theme_accepted(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {"ui": {"theme": "dark"}})
        assert cfg_mod.get_pref("ui.theme") == "dark"

    def test_invalid_theme_falls_back_to_default(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {"ui": {"theme": "rainbow"}})
        # "rainbow" is not in {"auto", "dark", "light"} → fallback
        assert cfg_mod.get_pref("ui.theme") == "auto"

    def test_bool_coercion(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"auth": {"require_login": 1}})
        # int 1 should be coerced to True
        assert cfg_mod.get_pref("auth.require_login") is True

    def test_invalid_bool_falls_back(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"auth": {"require_login": "maybe"}})
        assert cfg_mod.get_pref("auth.require_login") is False

    def test_negative_timeout_falls_back(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"auth": {"lock_timeout_s": -100}})
        assert cfg_mod.get_pref("auth.lock_timeout_s") == 1800

    def test_string_timeout_coerced(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"auth": {"lock_timeout_s": "3600"}})
        assert cfg_mod.get_pref("auth.lock_timeout_s") == 3600

    def test_set_pref_validates(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {})
        monkeypatch.setattr(cfg_mod, "_PREFS_PATH",
                            Path("/tmp/_test_prefs_validate.json"))

        with pytest.raises(ValueError):
            cfg_mod.set_pref("ui.theme", "rainbow")

    def test_set_pref_coerces_valid_value(self, monkeypatch, tmp_path):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs", {})
        monkeypatch.setattr(cfg_mod, "_PREFS_PATH",
                            tmp_path / "test_prefs.json")

        cfg_mod.set_pref("auth.lock_timeout_s", "900")
        assert cfg_mod.get_pref("auth.lock_timeout_s") == 900

    def test_choice_validator_accepts_valid(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"updates": {"frequency": "daily"}})
        assert cfg_mod.get_pref("updates.frequency") == "daily"

    def test_choice_validator_rejects_invalid(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"updates": {"frequency": "hourly"}})
        assert cfg_mod.get_pref("updates.frequency") == "always"

    def test_float_validation(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"autofocus": {"coarse_step": -5.0}})
        # Negative is not positive → falls back to 50.0
        assert cfg_mod.get_pref("autofocus.coarse_step") == 50.0

    def test_list_validation(self, monkeypatch):
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_prefs",
                            {"lab": {"operators": "not_a_list"}})
        # String is not a list → falls back to []
        assert cfg_mod.get_pref("lab.operators") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
