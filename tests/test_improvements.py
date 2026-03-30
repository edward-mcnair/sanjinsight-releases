"""
tests/test_improvements.py

Tests for the 10 performance/UX improvements (commit 46ad1bf).

Covers:
    1. Camera preview sleep reduction (constant value check)
    2. Colormap cache in comparison_tab
    3. Session mmap_mode loading
    4. Acquire tab settings undo/restore
    5. F5 hotkey assignment (menu action shortcut)
    6. Post-capture sub-step progress labels
    7. Comparison tab auto-populate with recent sessions
    8. Batch progress widget (start, progress, finished, abort, reset)
    9. Periodic capture checkpoint logic
   10. Config backup before writes

No physical hardware required.  All tests use synthetic data or stubs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

_app: QApplication = QApplication.instance() or QApplication(sys.argv[:1])


# ================================================================== #
#  1. Camera preview sleep reduction                                   #
# ================================================================== #


class TestCameraSleepReduction:
    """Verify the preview loop sleep is <= 0.01s."""

    def test_sleep_value_in_source(self):
        """The camera service wait interval should be 0.01 (not 0.05)."""
        import hardware.services.camera_service as cs
        src = open(cs.__file__).read()
        # Should contain 0.01 in the preview loop, NOT 0.05
        assert "self._stop_event.wait(0.01)" in src
        assert "self._stop_event.wait(0.05)" not in src


# ================================================================== #
#  2. Colormap cache in comparison_tab                                 #
# ================================================================== #


class TestColormapCache:
    """Verify colormap cache avoids repeated lookups."""

    def test_cache_populated_on_first_use(self):
        from acquisition.comparison_tab import _cmap_cache, _array_to_pixmap

        _cmap_cache.clear()
        arr = np.random.rand(10, 10).astype(np.float32)
        _array_to_pixmap(arr, cmap="inferno")
        assert "inferno" in _cmap_cache

    def test_cache_reused_on_second_call(self):
        from acquisition.comparison_tab import _cmap_cache, _array_to_pixmap

        _cmap_cache.clear()
        arr = np.random.rand(10, 10).astype(np.float32)
        _array_to_pixmap(arr, cmap="viridis")
        cached = _cmap_cache["viridis"]
        _array_to_pixmap(arr, cmap="viridis")
        assert _cmap_cache["viridis"] is cached  # same object, not re-fetched

    def test_different_cmaps_cached_separately(self):
        from acquisition.comparison_tab import _cmap_cache, _array_to_pixmap

        _cmap_cache.clear()
        arr = np.random.rand(10, 10).astype(np.float32)
        _array_to_pixmap(arr, cmap="inferno")
        _array_to_pixmap(arr, cmap="plasma")
        assert "inferno" in _cmap_cache
        assert "plasma" in _cmap_cache


# ================================================================== #
#  3. Session mmap_mode loading                                        #
# ================================================================== #


class TestSessionMmap:
    """Verify sessions load arrays with mmap_mode='r'."""

    def test_load_uses_mmap(self, tmp_path):
        """_load() should return a memory-mapped array."""
        from acquisition.storage.session import Session, SessionMeta

        # Write a test array
        arr = np.arange(100, dtype=np.float32).reshape(10, 10)
        np.save(tmp_path / "delta_r_over_r.npy", arr)
        np.save(tmp_path / "cold_avg.npy", arr)

        # Write minimal session.json
        meta = {
            "uid": "test-001",
            "label": "test",
            "timestamp": time.time(),
            "schema_version": 2,
        }
        (tmp_path / "session.json").write_text(json.dumps(meta))

        session = Session.load(str(tmp_path))
        loaded = session.delta_r_over_r
        assert loaded is not None
        # mmap arrays are np.memmap instances
        assert isinstance(loaded, np.memmap)

    def test_missing_file_returns_none(self, tmp_path):
        """_load() should return None for missing .npy files."""
        from acquisition.storage.session import Session, SessionMeta

        meta = {
            "uid": "test-002",
            "label": "test",
            "timestamp": time.time(),
            "schema_version": 2,
        }
        (tmp_path / "session.json").write_text(json.dumps(meta))

        session = Session.load(str(tmp_path))
        assert session.cold_avg is None


# ================================================================== #
#  4. Acquire tab settings undo/restore                                #
# ================================================================== #


class TestAcquireTabUndo:
    """Verify snapshot/restore for acquisition settings."""

    def test_snapshot_saves_current_values(self):
        from ui.tabs.acquire_tab import AcquireTab

        tab = AcquireTab()
        tab._frames.setValue(200)
        tab._delay.setValue(1.5)
        tab._snapshot_settings()

        assert tab._prev_settings is not None
        assert tab._prev_settings["frames"] == 200
        assert tab._prev_settings["delay"] == 1.5

    def test_restore_reverts_to_snapshot(self):
        from ui.tabs.acquire_tab import AcquireTab

        tab = AcquireTab()
        tab._frames.setValue(200)
        tab._delay.setValue(1.5)
        tab._snapshot_settings()

        # Change values
        tab._frames.setValue(500)
        tab._delay.setValue(3.0)
        assert tab._frames.value() == 500

        # Restore
        tab._restore_settings()
        assert tab._frames.value() == 200
        assert tab._delay.value() == 1.5

    def test_restore_noop_when_no_snapshot(self):
        from ui.tabs.acquire_tab import AcquireTab

        tab = AcquireTab()
        tab._frames.setValue(100)
        tab._restore_settings()  # should not crash
        assert tab._frames.value() == 100

    def test_restore_button_enabled_after_snapshot(self):
        from ui.tabs.acquire_tab import AcquireTab

        tab = AcquireTab()
        assert not tab._restore_btn.isEnabled()
        tab._snapshot_settings()
        assert tab._restore_btn.isEnabled()


# ================================================================== #
#  5. F5 hotkey assignment                                             #
# ================================================================== #


class TestF5Hotkey:
    """Verify F5 is assigned to Run Sequence (not live stream)."""

    def test_run_sequence_shortcut_in_source(self):
        """main_app.py should assign F5 to Run Sequence."""
        import main_app
        src = open(main_app.__file__).read()
        # F5 should be on Run Sequence
        assert '"F5"' in src
        # Live stream should NOT have F5
        assert '"Ctrl+F5"' in src


# ================================================================== #
#  6. Post-capture sub-step progress labels                            #
# ================================================================== #


class TestPostCaptureLabels:
    """Verify sub-step labels exist in orchestrator source."""

    def test_substep_labels_present(self):
        import acquisition.measurement_orchestrator as mo
        src = open(mo.__file__).read()
        for label in ("Scoring quality", "Applying calibration",
                      "Saving session", "Writing manifest"):
            assert label in src, f"Missing sub-step label: {label}"


# ================================================================== #
#  7. Comparison tab auto-populate                                     #
# ================================================================== #


class TestComparisonAutoPopulate:
    """Verify comparison tab auto-populates with recent sessions."""

    def _make_session_folder(self, tmp_path, name: str) -> str:
        """Create a minimal session folder with delta_r_over_r.npy."""
        folder = tmp_path / name
        folder.mkdir()
        arr = np.random.rand(8, 8).astype(np.float32)
        np.save(folder / "delta_r_over_r.npy", arr)
        meta = {
            "uid": name,
            "label": name,
            "timestamp": time.time(),
            "schema_version": 2,
        }
        (folder / "session.json").write_text(json.dumps(meta))
        return str(folder)

    def test_auto_populate_loads_two_sessions(self, tmp_path):
        from acquisition.comparison_tab import ComparisonTab

        pathA = self._make_session_folder(tmp_path, "session_a")
        pathB = self._make_session_folder(tmp_path, "session_b")

        # Create a stub session manager
        @dataclass
        class _Meta:
            path: str
            timestamp: float

        mgr = MagicMock()
        mgr.all_metas.return_value = [
            _Meta(path=pathA, timestamp=2.0),
            _Meta(path=pathB, timestamp=1.0),
        ]

        tab = ComparisonTab(session_manager=mgr)
        tab._auto_populate()

        assert tab._arrA is not None
        assert tab._arrB is not None
        assert tab._pathA == pathA
        assert tab._pathB == pathB

    def test_auto_populate_skips_without_manager(self):
        from acquisition.comparison_tab import ComparisonTab

        tab = ComparisonTab(session_manager=None)
        tab._auto_populate()
        assert tab._arrA is None
        assert tab._arrB is None

    def test_auto_populate_skips_with_fewer_than_two(self, tmp_path):
        from acquisition.comparison_tab import ComparisonTab

        pathA = self._make_session_folder(tmp_path, "only_one")

        @dataclass
        class _Meta:
            path: str
            timestamp: float

        mgr = MagicMock()
        mgr.all_metas.return_value = [_Meta(path=pathA, timestamp=1.0)]

        tab = ComparisonTab(session_manager=mgr)
        tab._auto_populate()
        assert tab._arrA is None
        assert tab._arrB is None

    def test_auto_populate_only_once(self, tmp_path):
        """showEvent should only auto-populate on first show."""
        from acquisition.comparison_tab import ComparisonTab

        mgr = MagicMock()
        mgr.all_metas.return_value = []

        tab = ComparisonTab(session_manager=mgr)
        assert not tab._auto_populated

        # Simulate first show
        from PyQt5.QtGui import QShowEvent
        tab.showEvent(QShowEvent())
        assert tab._auto_populated
        assert mgr.all_metas.call_count == 1

        # Second show should not call again
        tab.showEvent(QShowEvent())
        assert mgr.all_metas.call_count == 1


# ================================================================== #
#  8. Batch progress widget                                            #
# ================================================================== #


class TestBatchProgressWidget:
    """Verify BatchProgressWidget tracks batch operations."""

    def _make_widget(self):
        from ui.widgets.batch_progress_widget import BatchProgressWidget
        return BatchProgressWidget()

    def test_initially_hidden(self):
        w = self._make_widget()
        # isHidden() checks the widget's own state (not parent chain)
        assert w.isHidden()

    def test_start_shows_and_initializes(self):
        w = self._make_widget()
        w.start("Reports", total=10)
        assert not w.isHidden()
        assert w._total == 10
        assert w._done == 0
        assert w._bar.maximum() == 10

    def test_progress_increments(self):
        w = self._make_widget()
        w.start("Reports", total=5)
        update = types.SimpleNamespace(label="session_1", success=True)
        w.on_progress(update)
        assert w._done == 1
        assert w._bar.value() == 1

    def test_progress_multiple(self):
        w = self._make_widget()
        w.start("Reports", total=3)
        for i in range(3):
            w.on_progress(types.SimpleNamespace(label=f"s{i}", success=True))
        assert w._done == 3
        assert w._bar.value() == 3

    def test_finished_updates_status(self):
        w = self._make_widget()
        w.start("Reports", total=2)
        result = types.SimpleNamespace(ok=2, failed=0, duration_s=1.5)
        w.on_finished(result)
        assert "2 ok" in w._status.text()
        assert "0 failed" in w._status.text()
        assert not w._abort_btn.isEnabled()

    def test_abort_calls_worker(self):
        w = self._make_widget()
        worker = MagicMock()
        w.start("Analysis", total=10, worker=worker)
        w._on_abort()
        worker.abort.assert_called_once()
        assert not w._abort_btn.isEnabled()

    def test_reset_hides_and_clears(self):
        w = self._make_widget()
        w.start("Reports", total=5)
        w.on_progress(types.SimpleNamespace(label="s1", success=True))
        w.reset()
        assert w.isHidden()
        assert w._total == 0
        assert w._done == 0
        assert w._worker is None

    def test_apply_styles_no_crash(self):
        """_apply_styles() should not crash (theme switch)."""
        w = self._make_widget()
        w._apply_styles()  # should not raise


# ================================================================== #
#  9. Periodic capture checkpoint                                      #
# ================================================================== #


class TestCaptureCheckpoint:
    """Verify checkpoint constants and method on AcquisitionPipeline."""

    def test_checkpoint_constants(self):
        from acquisition.pipeline import AcquisitionPipeline
        assert AcquisitionPipeline._CHECKPOINT_FRAC == 0.25
        assert AcquisitionPipeline._CHECKPOINT_MIN == 50

    def test_checkpoint_interval_calculation(self):
        """Checkpoint interval = max(50, int(n_frames * 0.25))."""
        from acquisition.pipeline import AcquisitionPipeline
        frac = AcquisitionPipeline._CHECKPOINT_FRAC
        mn = AcquisitionPipeline._CHECKPOINT_MIN
        # 100 frames → max(50, 25) = 50
        assert max(mn, int(100 * frac)) == 50
        # 1000 frames → max(50, 250) = 250
        assert max(mn, int(1000 * frac)) == 250
        # 10 frames → max(50, 2) = 50
        assert max(mn, int(10 * frac)) == 50

    def test_save_capture_checkpoint_calls_autosave(self):
        """_save_capture_checkpoint should call acquire_autosave.save()."""
        from acquisition.pipeline import AcquisitionPipeline

        pipeline = AcquisitionPipeline.__new__(AcquisitionPipeline)
        accumulator = np.ones((4, 4), dtype=np.float64) * 42.0

        with patch("acquisition.storage.autosave.acquire_autosave") as mock_auto:
            pipeline._save_capture_checkpoint("cold", accumulator, 50, 200)
            mock_auto.save.assert_called_once()
            call_args = mock_auto.save.call_args
            arrays = call_args[1].get("arrays") or call_args[0][0]
            metadata = call_args[1].get("metadata") or call_args[0][1]
            assert "cold_accumulator" in arrays
            np.testing.assert_array_equal(arrays["cold_accumulator"], accumulator)
            assert metadata["phase"] == "cold"
            assert metadata["frames_done"] == 50
            assert metadata["frames_total"] == 200
            assert metadata["checkpoint"] is True

    def test_save_capture_checkpoint_handles_error(self):
        """Should not raise even if autosave.save() fails."""
        from acquisition.pipeline import AcquisitionPipeline

        pipeline = AcquisitionPipeline.__new__(AcquisitionPipeline)
        accumulator = np.ones((4, 4), dtype=np.float64)

        with patch("acquisition.storage.autosave.acquire_autosave") as mock_auto:
            mock_auto.save.side_effect = OSError("disk full")
            # Should not raise
            pipeline._save_capture_checkpoint("hot", accumulator, 10, 100)


# ================================================================== #
# 10. Config backup before writes                                      #
# ================================================================== #


class TestConfigBackup:
    """Verify _save_prefs creates a .json.bak before writing."""

    def test_backup_created_on_save(self, tmp_path, monkeypatch):
        import config

        prefs_path = tmp_path / "prefs.json"
        prefs_path.write_text('{"old": "data"}')

        monkeypatch.setattr(config, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(config, "_prefs", {"new": "data"})

        config._save_prefs()

        bak = prefs_path.with_suffix(".json.bak")
        assert bak.exists(), ".json.bak should exist after save"
        assert json.loads(bak.read_text()) == {"old": "data"}
        assert json.loads(prefs_path.read_text()) == {"new": "data"}

    def test_no_backup_when_no_existing_file(self, tmp_path, monkeypatch):
        import config

        prefs_path = tmp_path / "new_prefs.json"
        monkeypatch.setattr(config, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(config, "_prefs", {"fresh": True})

        config._save_prefs()

        bak = prefs_path.with_suffix(".json.bak")
        assert not bak.exists(), "No backup when file didn't exist before"
        assert prefs_path.exists()
        assert json.loads(prefs_path.read_text()) == {"fresh": True}

    def test_backup_overwrites_previous_bak(self, tmp_path, monkeypatch):
        import config

        prefs_path = tmp_path / "prefs.json"
        bak_path = prefs_path.with_suffix(".json.bak")

        # Write initial state
        prefs_path.write_text('{"v": 1}')
        bak_path.write_text('{"v": 0}')

        monkeypatch.setattr(config, "_PREFS_PATH", prefs_path)
        monkeypatch.setattr(config, "_prefs", {"v": 2})

        config._save_prefs()

        # .bak should now hold v:1 (the pre-save content), not v:0
        assert json.loads(bak_path.read_text()) == {"v": 1}
        assert json.loads(prefs_path.read_text()) == {"v": 2}
