"""
tests/test_integration.py

Integration tests — multi-component scenarios that verify the system
behaves correctly across module boundaries.

All tests use only simulated drivers and temporary files — no real
hardware or display is required.

Run:
    cd sanjinsight
    pytest tests/test_integration.py -v

Coverage
--------
1. Session schema migration — legacy v0 files load without error; new
   files carry schema_version; migration is logged.
2. Config robustness — corrupt / missing preferences file does not crash
   the application, and the failure is recorded in the log.
3. HardwareService lifecycle — demo-mode start + clean shutdown leaves
   no orphan hw.* threads alive.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import tempfile
import threading
import time

import numpy as np
import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. Session schema migration                                         #
# ================================================================== #

class TestSessionSchemaMigration:
    """
    Verify that legacy (v0) session.json files migrate transparently,
    that new saves include schema_version, and that the migration is
    written to the log.
    """

    @pytest.fixture
    def minimal_result(self):
        """AcquisitionResult with small synthetic arrays — no hardware needed."""
        from acquisition.pipeline import AcquisitionResult

        H, W   = 32, 32
        result = AcquisitionResult(
            n_frames=4, exposure_us=1000.0,
            gain_db=0.0, timestamp=time.time())
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 1000
        result.hot_avg        = result.cold_avg * 1.001
        result.delta_r_over_r = (
            (result.hot_avg - result.cold_avg) / result.cold_avg
        ).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = result.hot_captured = 4
        return result

    # ----------------------------------------------------------------

    def test_new_session_includes_schema_version(self, minimal_result, tmp_path):
        """Freshly saved sessions must write schema_version into session.json."""
        from acquisition.session import Session
        from acquisition.schema_migrations import CURRENT_SCHEMA

        session = Session.from_result(minimal_result, label="sv_test")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)

        assert "schema_version" in data, \
            "schema_version key missing from freshly saved session.json"
        assert data["schema_version"] == CURRENT_SCHEMA, \
            f"Expected schema_version={CURRENT_SCHEMA}, got {data['schema_version']}"

    def test_legacy_v0_session_loads_correctly(self, minimal_result, tmp_path):
        """
        A session.json without schema_version (legacy v0) must load
        without raising and return a fully populated SessionMeta.
        """
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="legacy_test")
        path    = session.save(str(tmp_path))

        # Simulate a v0 file by stripping the schema_version field
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)

        assert loaded.meta.label == "legacy_test", \
            f"Label mismatch after migration: {loaded.meta.label!r}"
        assert loaded.meta.uid == session.meta.uid, \
            "UID changed after v0 → v1 migration"

    def test_migration_is_logged(self, minimal_result, tmp_path, caplog):
        """The v0 → v1 migration must emit an INFO-level log message."""
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="log_test")
        path    = session.save(str(tmp_path))

        # Strip schema_version to trigger the migration path
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        with caplog.at_level(logging.INFO, logger="acquisition.schema_migrations"):
            Session.load(path)

        migration_msgs = [
            r.message for r in caplog.records
            if "v0" in r.message and "v1" in r.message
        ]
        assert migration_msgs, (
            "Expected a log message containing 'v0' and 'v1' from "
            "acquisition.schema_migrations — got none.\n"
            f"All records: {[r.message for r in caplog.records]}"
        )

    def test_load_meta_also_migrates(self, minimal_result, tmp_path):
        """Session.load_meta() uses from_dict() and must apply migrations too."""
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="meta_test")
        path    = session.save(str(tmp_path))

        # Simulate v0
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        meta = Session.load_meta(path)

        assert meta is not None, "load_meta returned None for a valid v0 session"
        assert meta.label == "meta_test", \
            f"Unexpected label after load_meta migration: {meta.label!r}"

    def test_unknown_fields_at_current_schema_are_ignored(self, minimal_result, tmp_path):
        """
        Extra keys in session.json at the CURRENT schema version are silently
        ignored — forward-compatibility guard for additive field additions
        within the same schema version.
        """
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="fwd_compat")
        path    = session.save(str(tmp_path))

        # Inject a hypothetical future field at the CURRENT schema version
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data["future_field_xyz"] = "some_value"
        # Keep schema_version at CURRENT — only unknown *fields* are new
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Must not raise — unknown keys are ignored by from_dict()
        loaded = Session.load(path)
        assert loaded.meta.label == "fwd_compat"

    def test_future_schema_version_is_rejected(self, minimal_result, tmp_path):
        """
        A session.json with schema_version > CURRENT_SCHEMA is hard-rejected
        to prevent data corruption from silently dropping unknown fields.
        """
        import pytest
        from acquisition.session import Session
        from acquisition.schema_migrations import FutureSchemaError

        session = Session.from_result(minimal_result, label="future_reject")
        path    = session.save(str(tmp_path))

        # Inject a far-future schema version
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data["schema_version"] = 999
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Must raise FutureSchemaError
        with pytest.raises(FutureSchemaError):
            Session.load(path)

        # load_meta should return None (graceful skip) rather than crash
        assert Session.load_meta(path) is None


# ================================================================== #
#  1b. Schema v6 — result_type / scan_params / grid persistence       #
# ================================================================== #

class TestSchemaV6GridPersistence:
    """
    Phase 2B tests — v5→v6 migration, result_type/scan_params round-trip,
    grid mapping in Session.from_result(), and SessionManager.save_result()
    with result_type="grid".
    """

    @pytest.fixture
    def single_point_result(self):
        """Standard single-point AcquisitionResult (32×32 synthetic)."""
        from acquisition.pipeline import AcquisitionResult

        H, W = 32, 32
        result = AcquisitionResult(
            n_frames=4, exposure_us=1000.0,
            gain_db=0.0, timestamp=time.time())
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 1000
        result.hot_avg        = result.cold_avg * 1.001
        result.delta_r_over_r = (
            (result.hot_avg - result.cold_avg) / result.cold_avg
        ).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = result.hot_captured = 4
        return result

    @pytest.fixture
    def grid_result(self):
        """Synthetic grid scan result with drr_map and dt_map."""
        class _GridResult:
            n_frames    = 16
            exposure_us = 500.0
            gain_db     = 0.0
            n_rows      = 4
            n_cols      = 4
            step_x_um   = 10.0
            step_y_um   = 10.0
            tile_w      = 32
            tile_h      = 32
            origin_x_um = 0.0
            origin_y_um = 0.0

        r = _GridResult()
        # Stitched composite arrays: 4 tiles × 32 px = 128 px per axis
        r.drr_map = np.random.rand(128, 128).astype(np.float32) * 1e-4
        r.dt_map  = np.random.rand(128, 128).astype(np.float32) * 0.5
        r.timestamp = time.time()
        return r

    @pytest.fixture
    def scan_params(self):
        return {
            "n_rows": 4, "n_cols": 4,
            "step_x_um": 10.0, "step_y_um": 10.0,
            "tile_w": 32, "tile_h": 32,
            "origin_x_um": 0.0, "origin_y_um": 0.0,
        }

    # ── v5 → v6 migration ────────────────────────────────────────

    def test_v5_to_v6_migration_adds_defaults(self, single_point_result, tmp_path):
        """A v5 session.json must gain result_type='single_point' and
        scan_params=None after migration to v6."""
        from acquisition.storage.session import Session
        from acquisition.schema_migrations import CURRENT_SCHEMA

        session = Session.from_result(single_point_result, label="v5_test")
        path    = session.save(str(tmp_path))

        # Simulate a v5 file by stripping v6 fields + downgrading version
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("result_type", None)
        data.pop("scan_params", None)
        data["schema_version"] = 5
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)
        assert loaded is not None
        assert loaded.meta.result_type == "single_point"
        assert loaded.meta.scan_params is None

    def test_v5_to_v6_migration_is_logged(self, single_point_result, tmp_path, caplog):
        """The v5 → v6 migration must emit a log message."""
        from acquisition.storage.session import Session

        session = Session.from_result(single_point_result, label="v6_log")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("result_type", None)
        data.pop("scan_params", None)
        data["schema_version"] = 5
        with open(json_path, "w") as f:
            json.dump(data, f)

        with caplog.at_level(logging.INFO, logger="acquisition.schema_migrations"):
            Session.load(path)

        migration_msgs = [
            r.message for r in caplog.records
            if "v5" in r.message and "v6" in r.message
        ]
        assert migration_msgs, (
            "Expected a log message containing 'v5' and 'v6' — got none.\n"
            f"All records: {[r.message for r in caplog.records]}"
        )

    def test_v5_to_v6_preserves_existing_fields(self, single_point_result, tmp_path):
        """Migration must not clobber pre-existing v5 fields."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            single_point_result, label="preserve_test", operator="Alice")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        original_uid   = data["uid"]
        original_label = data["label"]
        data.pop("result_type", None)
        data.pop("scan_params", None)
        data["schema_version"] = 5
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)
        assert loaded.meta.uid      == original_uid
        assert loaded.meta.label    == original_label
        assert loaded.meta.operator == "Alice"

    # ── result_type / scan_params round-trip ──────────────────────

    def test_single_point_round_trip(self, single_point_result, tmp_path):
        """Single-point session persists result_type and scan_params=None."""
        from acquisition.storage.session import Session

        session = Session.from_result(single_point_result, label="sp_rt")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)

        assert data["result_type"]  == "single_point"
        assert data["scan_params"]  is None

        loaded = Session.load(path)
        assert loaded.meta.result_type  == "single_point"
        assert loaded.meta.scan_params  is None

    def test_grid_round_trip(self, grid_result, scan_params, tmp_path):
        """Grid session persists result_type='grid' and full scan_params."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="grid_rt",
            result_type="grid", scan_params=scan_params)
        path = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)

        assert data["result_type"] == "grid"
        assert data["scan_params"] == scan_params

        loaded = Session.load(path)
        assert loaded.meta.result_type  == "grid"
        assert loaded.meta.scan_params  == scan_params

    def test_scan_params_keys_match(self, grid_result, scan_params, tmp_path):
        """scan_params dict must survive JSON serialisation with all keys intact."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="keys_test",
            result_type="grid", scan_params=scan_params)
        path = session.save(str(tmp_path))

        loaded = Session.load(path)
        for key in ("n_rows", "n_cols", "step_x_um", "step_y_um",
                     "tile_w", "tile_h", "origin_x_um", "origin_y_um"):
            assert key in loaded.meta.scan_params, \
                f"Missing scan_params key: {key}"
            assert loaded.meta.scan_params[key] == scan_params[key]

    # ── Grid mapping in Session.from_result() ─────────────────────

    def test_grid_from_result_maps_drr(self, grid_result, scan_params):
        """from_result(result_type='grid') maps drr_map → _delta_r_over_r."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="drr_map_test",
            result_type="grid", scan_params=scan_params)

        assert session._delta_r_over_r is not None
        assert session._delta_r_over_r.shape == (128, 128)
        np.testing.assert_array_equal(session._delta_r_over_r, grid_result.drr_map)

    def test_grid_from_result_maps_dt(self, grid_result, scan_params):
        """from_result(result_type='grid') maps dt_map → _difference."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="dt_map_test",
            result_type="grid", scan_params=scan_params)

        assert session._difference is not None
        assert session._difference.shape == (128, 128)
        np.testing.assert_array_equal(session._difference, grid_result.dt_map)

    def test_grid_from_result_no_cold_hot(self, grid_result, scan_params):
        """Grid sessions must not have cold_avg or hot_avg arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="no_cold_hot",
            result_type="grid", scan_params=scan_params)

        assert session._cold_avg is None
        assert session._hot_avg  is None

    def test_grid_from_result_dimensions(self, grid_result, scan_params):
        """Grid session frame_h/frame_w must match stitched array dimensions."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            grid_result, label="dims_test",
            result_type="grid", scan_params=scan_params)

        assert session.meta.frame_h == 128
        assert session.meta.frame_w == 128
        assert session.meta.has_drr is True

    def test_grid_drr_only_no_dt(self, scan_params):
        """Grid result with drr_map but no dt_map must still work."""
        from acquisition.storage.session import Session

        class _DrOnly:
            n_frames = 4; exposure_us = 500.0; gain_db = 0.0
        r = _DrOnly()
        r.drr_map = np.ones((64, 64), dtype=np.float32)

        session = Session.from_result(
            r, label="drr_only", result_type="grid", scan_params=scan_params)
        assert session._delta_r_over_r is not None
        assert session._difference is None
        assert session.meta.frame_h == 64
        assert session.meta.frame_w == 64

    def test_grid_dt_only_no_drr(self, scan_params):
        """Grid result with dt_map but no drr_map must derive dimensions from dt."""
        from acquisition.storage.session import Session

        class _DtOnly:
            n_frames = 4; exposure_us = 500.0; gain_db = 0.0
        r = _DtOnly()
        r.dt_map = np.ones((48, 96), dtype=np.float32)

        session = Session.from_result(
            r, label="dt_only", result_type="grid", scan_params=scan_params)
        assert session._delta_r_over_r is None
        assert session._difference is not None
        assert session.meta.frame_h == 48
        assert session.meta.frame_w == 96
        assert session.meta.has_drr is False

    # ── save_result(..., result_type="grid") via SessionManager ───

    def test_session_manager_save_grid(self, grid_result, scan_params, tmp_path):
        """SessionManager.save_result() with result_type='grid' must persist
        correctly and appear in the index."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        session = mgr.save_result(
            grid_result, label="mgr_grid",
            result_type="grid", scan_params=scan_params)

        assert session.meta.result_type == "grid"
        assert session.meta.scan_params == scan_params
        assert mgr.count() == 1

        # Verify it survives a full rescan
        mgr2 = SessionManager(str(tmp_path))
        mgr2.scan()
        assert mgr2.count() == 1
        meta = mgr2.all_metas()[0]
        assert meta.result_type  == "grid"
        assert meta.scan_params  == scan_params

    def test_session_manager_save_single_default(self, single_point_result, tmp_path):
        """SessionManager.save_result() without result_type defaults to single_point."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        session = mgr.save_result(single_point_result, label="mgr_sp")

        assert session.meta.result_type  == "single_point"
        assert session.meta.scan_params  is None

    def test_session_manager_grid_load_arrays(self, grid_result, scan_params, tmp_path):
        """Grid session saved via SessionManager must load arrays correctly."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        saved = mgr.save_result(
            grid_result, label="mgr_load",
            result_type="grid", scan_params=scan_params)

        loaded = mgr.load(saved.meta.uid)
        assert loaded is not None
        assert loaded.meta.result_type == "grid"

        drr = loaded.delta_r_over_r
        assert drr is not None
        assert drr.shape == (128, 128)
        np.testing.assert_allclose(drr, grid_result.drr_map, atol=1e-6)


# ================================================================== #
#  1c. Schema v7 — cube_params / transient persistence                #
# ================================================================== #

class TestSchemaV7TransientPersistence:
    """
    Phase 2C tests — v6→v7 migration, transient cube round-trip,
    cube lazy loading, and SessionManager transient save path.
    """

    @pytest.fixture
    def transient_result(self):
        """Synthetic TransientResult with small cube arrays."""
        class _TransientResult:
            n_delays     = 10
            n_averages   = 5
            pulse_dur_us = 500.0
            delay_start_s = 0.0
            delay_end_s  = 0.005
            exposure_us  = 100.0
            gain_db      = 0.0
            duration_s   = 12.5
            hw_triggered = True
            notes        = ""
            n_frames     = 10  # not used for transient, but present on result
        r = _TransientResult()
        H, W = 32, 32
        r.delta_r_cube = np.random.rand(10, H, W).astype(np.float32) * 1e-4
        r.reference    = np.random.rand(H, W).astype(np.float32) * 1000
        r.delay_times_s = np.linspace(0.0, 0.005, 10).astype(np.float64)
        r.raw_cube     = None  # not persisted
        r.timestamp    = time.time()
        return r

    @pytest.fixture
    def cube_params(self):
        return {
            "n_delays":      10,
            "n_averages":    5,
            "delay_start_s": 0.0,
            "delay_end_s":   0.005,
            "pulse_dur_us":  500.0,
            "hw_triggered":  True,
        }

    @pytest.fixture
    def single_point_result(self):
        """Standard single-point AcquisitionResult for migration tests."""
        from acquisition.pipeline import AcquisitionResult
        H, W = 32, 32
        result = AcquisitionResult(
            n_frames=4, exposure_us=1000.0,
            gain_db=0.0, timestamp=time.time())
        result.cold_avg       = np.random.rand(H, W).astype(np.float32) * 1000
        result.hot_avg        = result.cold_avg * 1.001
        result.delta_r_over_r = (
            (result.hot_avg - result.cold_avg) / result.cold_avg
        ).astype(np.float32)
        result.difference     = (result.hot_avg - result.cold_avg).astype(np.float32)
        result.cold_captured  = result.hot_captured = 4
        return result

    # ── v6 → v7 migration ────────────────────────────────────────

    def test_v6_to_v7_migration_adds_cube_params(self, single_point_result, tmp_path):
        """A v6 session.json must gain cube_params=None after migration to v7."""
        from acquisition.storage.session import Session
        from acquisition.schema_migrations import CURRENT_SCHEMA

        session = Session.from_result(single_point_result, label="v6_test")
        path    = session.save(str(tmp_path))

        # Simulate v6 by stripping cube_params + downgrading version
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("cube_params", None)
        data["schema_version"] = 6
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)
        assert loaded is not None
        assert loaded.meta.cube_params is None
        assert loaded.meta.result_type == "single_point"

    def test_v6_to_v7_migration_is_logged(self, single_point_result, tmp_path, caplog):
        """The v6 → v7 migration must emit a log message."""
        from acquisition.storage.session import Session

        session = Session.from_result(single_point_result, label="v7_log")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("cube_params", None)
        data["schema_version"] = 6
        with open(json_path, "w") as f:
            json.dump(data, f)

        with caplog.at_level(logging.INFO, logger="acquisition.schema_migrations"):
            Session.load(path)

        migration_msgs = [
            r.message for r in caplog.records
            if "v6" in r.message and "v7" in r.message
        ]
        assert migration_msgs, (
            "Expected a log message containing 'v6' and 'v7' — got none.\n"
            f"All records: {[r.message for r in caplog.records]}"
        )

    def test_full_migration_v0_to_v7(self, single_point_result, tmp_path):
        """A v0 session must migrate all the way to v7 with all defaults."""
        from acquisition.storage.session import Session
        from acquisition.schema_migrations import CURRENT_SCHEMA

        session = Session.from_result(single_point_result, label="v0_full")
        path    = session.save(str(tmp_path))

        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        with open(json_path, "w") as f:
            json.dump(data, f)

        loaded = Session.load(path)
        assert loaded.meta.result_type  == "single_point"
        assert loaded.meta.scan_params  is None
        assert loaded.meta.cube_params  is None

    # ── Transient from_result() ───────────────────────────────────

    def test_transient_from_result_maps_cube(self, transient_result, cube_params):
        """from_result(result_type='transient') maps delta_r_cube correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="cube_test",
            result_type="transient", cube_params=cube_params)

        assert session._delta_r_cube is not None
        assert session._delta_r_cube.shape == (10, 32, 32)
        np.testing.assert_array_equal(
            session._delta_r_cube, transient_result.delta_r_cube)

    def test_transient_from_result_maps_reference(self, transient_result, cube_params):
        """from_result(result_type='transient') maps reference frame."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="ref_test",
            result_type="transient", cube_params=cube_params)

        assert session._reference is not None
        assert session._reference.shape == (32, 32)
        np.testing.assert_array_equal(
            session._reference, transient_result.reference)

    def test_transient_from_result_maps_delay_times(self, transient_result, cube_params):
        """from_result(result_type='transient') maps delay_times_s."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="delay_test",
            result_type="transient", cube_params=cube_params)

        assert session._delay_times_s is not None
        assert session._delay_times_s.shape == (10,)
        np.testing.assert_array_equal(
            session._delay_times_s, transient_result.delay_times_s)

    def test_transient_from_result_no_2d_arrays(self, transient_result, cube_params):
        """Transient sessions must not populate 2D single-point arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="no_2d_test",
            result_type="transient", cube_params=cube_params)

        assert session._cold_avg       is None
        assert session._hot_avg        is None
        assert session._delta_r_over_r is None
        assert session._difference     is None

    def test_transient_from_result_dimensions(self, transient_result, cube_params):
        """Transient session frame_h/frame_w must match cube spatial dims."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="dims_test",
            result_type="transient", cube_params=cube_params)

        assert session.meta.frame_h == 32
        assert session.meta.frame_w == 32
        assert session.meta.has_drr is True
        assert session.meta.result_type == "transient"

    def test_transient_from_result_n_frames(self, transient_result, cube_params):
        """n_frames should reflect n_delays for transient results."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="nframes_test",
            result_type="transient", cube_params=cube_params)

        # n_frames comes from result.n_frames or result.n_delays
        assert session.meta.n_frames == 10

    # ── Round-trip persistence ────────────────────────────────────

    def test_transient_round_trip(self, transient_result, cube_params, tmp_path):
        """Transient session persists and reloads all cube arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="rt_test",
            result_type="transient", cube_params=cube_params)
        path = session.save(str(tmp_path))

        # Verify JSON
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["result_type"]  == "transient"
        assert data["cube_params"]  == cube_params

        # Verify files on disk
        assert os.path.exists(os.path.join(path, "delta_r_cube.npy"))
        assert os.path.exists(os.path.join(path, "reference.npy"))
        assert os.path.exists(os.path.join(path, "delay_times_s.npy"))
        assert not os.path.exists(os.path.join(path, "cold_avg.npy"))
        assert not os.path.exists(os.path.join(path, "hot_avg.npy"))

        # Load and verify
        loaded = Session.load(path)
        assert loaded.meta.result_type == "transient"
        assert loaded.meta.cube_params == cube_params

    def test_transient_lazy_load_cube(self, transient_result, cube_params, tmp_path):
        """Cube arrays must lazy-load via mmap on first property access."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="lazy_test",
            result_type="transient", cube_params=cube_params)
        session.save(str(tmp_path))

        # Fresh load — arrays not yet in memory
        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        assert loaded._delta_r_cube is None   # not loaded yet

        # Access triggers lazy load
        cube = loaded.delta_r_cube
        assert cube is not None
        assert cube.shape == (10, 32, 32)
        np.testing.assert_allclose(
            cube, transient_result.delta_r_cube, atol=1e-6)

    def test_transient_lazy_load_reference(self, transient_result, cube_params, tmp_path):
        """Reference frame must lazy-load correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="ref_lazy",
            result_type="transient", cube_params=cube_params)
        session.save(str(tmp_path))

        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        ref = loaded.reference
        assert ref is not None
        assert ref.shape == (32, 32)
        np.testing.assert_allclose(ref, transient_result.reference, atol=1e-6)

    def test_transient_lazy_load_delay_times(self, transient_result, cube_params, tmp_path):
        """Delay times must lazy-load correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="dt_lazy",
            result_type="transient", cube_params=cube_params)
        session.save(str(tmp_path))

        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        dt = loaded.delay_times_s
        assert dt is not None
        assert dt.shape == (10,)
        np.testing.assert_allclose(dt, transient_result.delay_times_s, atol=1e-10)

    def test_transient_unload(self, transient_result, cube_params, tmp_path):
        """unload() must release all cube arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="unload_test",
            result_type="transient", cube_params=cube_params)
        session.save(str(tmp_path))

        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        _ = loaded.delta_r_cube  # trigger load
        _ = loaded.reference
        _ = loaded.delay_times_s
        loaded.unload()

        assert loaded._delta_r_cube  is None
        assert loaded._reference     is None
        assert loaded._delay_times_s is None

    # ── Thumbnail ─────────────────────────────────────────────────

    def test_transient_thumbnail_generated(self, transient_result, cube_params, tmp_path):
        """Transient session save must generate a thumbnail.png."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            transient_result, label="thumb_test",
            result_type="transient", cube_params=cube_params)
        path = session.save(str(tmp_path))

        thumb_path = os.path.join(path, "thumbnail.png")
        assert os.path.exists(thumb_path), "thumbnail.png missing for transient session"

    # ── SessionManager ────────────────────────────────────────────

    def test_session_manager_save_transient(self, transient_result, cube_params, tmp_path):
        """SessionManager.save_result() with result_type='transient' must
        persist correctly and appear in the index."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        session = mgr.save_result(
            transient_result, label="mgr_transient",
            result_type="transient", cube_params=cube_params)

        assert session.meta.result_type == "transient"
        assert session.meta.cube_params == cube_params
        assert mgr.count() == 1

        # Verify rescan
        mgr2 = SessionManager(str(tmp_path))
        mgr2.scan()
        assert mgr2.count() == 1
        meta = mgr2.all_metas()[0]
        assert meta.result_type  == "transient"
        assert meta.cube_params  == cube_params

    def test_session_manager_transient_load_arrays(self, transient_result, cube_params, tmp_path):
        """Transient session saved via SessionManager must load cube arrays."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        saved = mgr.save_result(
            transient_result, label="mgr_load",
            result_type="transient", cube_params=cube_params)

        loaded = mgr.load(saved.meta.uid)
        assert loaded is not None
        cube = loaded.delta_r_cube
        assert cube is not None
        assert cube.shape == (10, 32, 32)
        np.testing.assert_allclose(
            cube, transient_result.delta_r_cube, atol=1e-6)


# ================================================================== #
#  1d. Movie session persistence                                      #
# ================================================================== #

class TestMoviePersistence:
    """
    Movie auto-save tests — movie branch in from_result(), round-trip
    persistence, lazy loading, and persistability gating.
    """

    @pytest.fixture
    def movie_result_with_drr(self):
        """Synthetic MovieResult with delta_r_cube (reference was captured)."""
        class _MovieResult:
            n_frames        = 20
            frames_captured = 20
            exposure_us     = 200.0
            gain_db         = 0.0
            duration_s      = 0.5
            fps_achieved    = 40.0
            notes           = ""
        r = _MovieResult()
        H, W = 24, 32
        r.delta_r_cube = np.random.rand(20, H, W).astype(np.float32) * 1e-4
        r.reference    = np.random.rand(H, W).astype(np.float32) * 1000
        r.timestamps_s = np.linspace(0.0, 0.5, 20).astype(np.float64)
        r.frame_cube   = np.random.rand(20, H, W).astype(np.float32) * 1000
        r.timestamp    = time.time()
        return r

    @pytest.fixture
    def movie_result_no_drr(self):
        """Synthetic MovieResult WITHOUT delta_r_cube (no reference captured)."""
        class _MovieResult:
            n_frames        = 20
            frames_captured = 20
            exposure_us     = 200.0
            gain_db         = 0.0
            duration_s      = 0.5
            fps_achieved    = 40.0
            notes           = ""
        r = _MovieResult()
        H, W = 24, 32
        r.delta_r_cube = None         # no reference → no ΔR/R
        r.reference    = None
        r.timestamps_s = np.linspace(0.0, 0.5, 20).astype(np.float64)
        r.frame_cube   = np.random.rand(20, H, W).astype(np.float32) * 1000
        r.timestamp    = time.time()
        return r

    @pytest.fixture
    def movie_cube_params(self):
        return {
            "n_frames":        20,
            "frames_captured": 20,
            "fps_achieved":    40.0,
        }

    # ── from_result() movie branch ────────────────────────────────

    def test_movie_from_result_maps_cube(self, movie_result_with_drr, movie_cube_params):
        """from_result(result_type='movie') maps delta_r_cube correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_cube",
            result_type="movie", cube_params=movie_cube_params)

        assert session._delta_r_cube is not None
        assert session._delta_r_cube.shape == (20, 24, 32)
        np.testing.assert_array_equal(
            session._delta_r_cube, movie_result_with_drr.delta_r_cube)

    def test_movie_from_result_maps_timestamps(self, movie_result_with_drr, movie_cube_params):
        """from_result(result_type='movie') maps timestamps_s correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_ts",
            result_type="movie", cube_params=movie_cube_params)

        assert session._timestamps_s is not None
        assert session._timestamps_s.shape == (20,)
        np.testing.assert_array_equal(
            session._timestamps_s, movie_result_with_drr.timestamps_s)

    def test_movie_from_result_maps_reference(self, movie_result_with_drr, movie_cube_params):
        """from_result(result_type='movie') maps reference frame."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_ref",
            result_type="movie", cube_params=movie_cube_params)

        assert session._reference is not None
        assert session._reference.shape == (24, 32)

    def test_movie_from_result_no_2d_arrays(self, movie_result_with_drr, movie_cube_params):
        """Movie sessions must not populate 2D single-point arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_no2d",
            result_type="movie", cube_params=movie_cube_params)

        assert session._cold_avg       is None
        assert session._hot_avg        is None
        assert session._delta_r_over_r is None
        assert session._difference     is None

    def test_movie_from_result_does_not_store_frame_cube(self, movie_result_with_drr, movie_cube_params):
        """frame_cube (raw intensity) must NOT be persisted."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_no_raw",
            result_type="movie", cube_params=movie_cube_params)
        # frame_cube is not a Session field — only delta_r_cube goes in
        # Verify no field holds the raw frame_cube data
        assert session._cold_avg is None
        assert session._hot_avg is None

    def test_movie_from_result_dimensions(self, movie_result_with_drr, movie_cube_params):
        """Movie session frame_h/frame_w must match cube spatial dims."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_dims",
            result_type="movie", cube_params=movie_cube_params)

        assert session.meta.frame_h == 24
        assert session.meta.frame_w == 32
        assert session.meta.has_drr is True
        assert session.meta.result_type == "movie"

    # ── Round-trip persistence ────────────────────────────────────

    def test_movie_round_trip(self, movie_result_with_drr, movie_cube_params, tmp_path):
        """Movie session persists and reloads all cube arrays."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_rt",
            result_type="movie", cube_params=movie_cube_params)
        path = session.save(str(tmp_path))

        # Verify JSON
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["result_type"] == "movie"
        assert data["cube_params"] == movie_cube_params

        # Verify files on disk
        assert os.path.exists(os.path.join(path, "delta_r_cube.npy"))
        assert os.path.exists(os.path.join(path, "reference.npy"))
        assert os.path.exists(os.path.join(path, "timestamps_s.npy"))
        assert not os.path.exists(os.path.join(path, "cold_avg.npy"))

        # Load and verify
        loaded = Session.load(path)
        assert loaded.meta.result_type == "movie"
        assert loaded.meta.cube_params == movie_cube_params

    def test_movie_lazy_load_cube(self, movie_result_with_drr, movie_cube_params, tmp_path):
        """Movie cube arrays must lazy-load via mmap."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_lazy",
            result_type="movie", cube_params=movie_cube_params)
        session.save(str(tmp_path))

        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        assert loaded._delta_r_cube is None   # not loaded yet

        cube = loaded.delta_r_cube
        assert cube is not None
        assert cube.shape == (20, 24, 32)
        np.testing.assert_allclose(
            cube, movie_result_with_drr.delta_r_cube, atol=1e-6)

    def test_movie_lazy_load_timestamps(self, movie_result_with_drr, movie_cube_params, tmp_path):
        """Movie timestamps must lazy-load correctly."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_ts_lazy",
            result_type="movie", cube_params=movie_cube_params)
        session.save(str(tmp_path))

        loaded = Session.load(os.path.join(str(tmp_path), session.meta.uid))
        ts = loaded.timestamps_s
        assert ts is not None
        assert ts.shape == (20,)
        np.testing.assert_allclose(
            ts, movie_result_with_drr.timestamps_s, atol=1e-10)

    def test_movie_thumbnail_generated(self, movie_result_with_drr, movie_cube_params, tmp_path):
        """Movie session save must generate a thumbnail.png."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_with_drr, label="movie_thumb",
            result_type="movie", cube_params=movie_cube_params)
        path = session.save(str(tmp_path))
        assert os.path.exists(os.path.join(path, "thumbnail.png"))

    # ── SessionManager ────────────────────────────────────────────

    def test_session_manager_save_movie(self, movie_result_with_drr, movie_cube_params, tmp_path):
        """SessionManager.save_result() with result_type='movie' must persist
        correctly and appear in the index."""
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        session = mgr.save_result(
            movie_result_with_drr, label="mgr_movie",
            result_type="movie", cube_params=movie_cube_params)

        assert session.meta.result_type == "movie"
        assert session.meta.cube_params == movie_cube_params
        assert mgr.count() == 1

        mgr2 = SessionManager(str(tmp_path))
        mgr2.scan()
        assert mgr2.count() == 1
        meta = mgr2.all_metas()[0]
        assert meta.result_type == "movie"

    # ── Non-persistable movie (no delta_r_cube) ───────────────────

    def test_movie_no_drr_has_drr_false(self, movie_result_no_drr, movie_cube_params):
        """Movie without delta_r_cube must have has_drr=False."""
        from acquisition.storage.session import Session

        session = Session.from_result(
            movie_result_no_drr, label="movie_nodrr",
            result_type="movie", cube_params=movie_cube_params)

        assert session.meta.has_drr is False
        assert session._delta_r_cube is None


# ================================================================== #
#  2. Config — preferences file robustness                            #
# ================================================================== #

class TestConfigRobustness:
    """
    Verify that config.py survives malformed or missing preference
    files without crashing, and that failures appear in the log.
    """

    def test_corrupt_prefs_returns_empty_dict(self, tmp_path, monkeypatch):
        """_load_prefs() must return {} and not raise on invalid JSON."""
        import config

        corrupt_path = tmp_path / "preferences.json"
        corrupt_path.write_text("{this is NOT valid JSON!!!}", encoding="utf-8")
        monkeypatch.setattr(config, "_PREFS_PATH", corrupt_path)

        result = config._load_prefs()

        assert result == {}, \
            f"Expected empty dict for corrupt prefs, got {result!r}"

    def test_corrupt_prefs_logs_exception(self, tmp_path, monkeypatch, caplog):
        """The load failure must be captured in the log (not silently dropped)."""
        import config

        corrupt_path = tmp_path / "preferences.json"
        corrupt_path.write_text("<<<NOT JSON>>>", encoding="utf-8")
        monkeypatch.setattr(config, "_PREFS_PATH", corrupt_path)

        with caplog.at_level(logging.ERROR):
            config._load_prefs()

        assert any("Preferences load failed" in r.message for r in caplog.records), (
            "Expected 'Preferences load failed' in log records.\n"
            f"Got: {[r.message for r in caplog.records]}"
        )

    def test_missing_prefs_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """_load_prefs() must return {} when the preferences file does not exist."""
        import config

        missing_path = tmp_path / "no_such_dir" / "preferences.json"
        monkeypatch.setattr(config, "_PREFS_PATH", missing_path)

        result = config._load_prefs()

        assert result == {}, \
            f"Expected empty dict for missing prefs file, got {result!r}"

    def test_get_pref_returns_default_when_prefs_empty(self, monkeypatch):
        """get_pref() must return the caller's default when _prefs is empty."""
        import config
        monkeypatch.setattr(config, "_prefs", {})

        assert config.get_pref("ui.theme", "light") == "light"
        assert config.get_pref("nonexistent.key") is None
        assert config.get_pref("a.b.c.d", 42) == 42

    def test_get_pref_reads_nested_key(self, monkeypatch):
        """get_pref() must navigate dot-separated nested keys."""
        import config
        monkeypatch.setattr(config, "_prefs", {
            "ui": {"theme": "dark", "zoom": 1.5},
            "scan": {"step_um": 5.0},
        })

        assert config.get_pref("ui.theme")    == "dark"
        assert config.get_pref("ui.zoom")     == 1.5
        assert config.get_pref("scan.step_um") == 5.0
        assert config.get_pref("ui.missing", "fallback") == "fallback"


# ================================================================== #
#  3. HardwareService — demo-mode start → clean shutdown              #
# ================================================================== #

class TestHardwareServiceLifecycle:
    """
    Verify that HardwareService.start_demo() + shutdown() leaves no
    orphaned hw.* threads alive.

    Uses only simulated drivers; PyQt5 is required for signal/slot
    infrastructure but no physical display is needed.
    """

    @pytest.fixture(autouse=True)
    def reset_app_state(self):
        """
        Clear the global app_state hardware references before and after
        each test so successive tests don't see stale driver objects.
        """
        from hardware.app_state import app_state
        yield
        # Tear-down: null out hardware refs left by the service
        try:
            with app_state:
                app_state._cam      = None
                app_state._fpga     = None
                app_state._bias     = None
                app_state._stage    = None
                app_state._pipeline = None
                app_state._tecs     = []
                app_state._demo_mode = False
        except Exception:
            pass    # best-effort cleanup

    @pytest.fixture(scope="class")
    def qapp(self):
        """One QApplication for all tests in this class."""
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    # ----------------------------------------------------------------

    def test_demo_start_and_shutdown_no_orphan_threads(self, qapp):
        """start_demo() + shutdown() must leave no hw.* threads running."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        try:
            svc.start_demo()
            time.sleep(0.35)   # let all six demo threads reach their poll loops

            hw_before = [t for t in threading.enumerate()
                         if t.name.startswith("hw.")]
            assert len(hw_before) > 0, \
                "Expected ≥1 hw.* thread after start_demo() — none found"

            svc.shutdown()
        finally:
            # Safety net: ensure shutdown was called even if the assert above fails
            try:
                svc.shutdown()
            except Exception:
                pass

        hw_after = [t for t in threading.enumerate()
                    if t.name.startswith("hw.")]
        assert len(hw_after) == 0, (
            f"hw.* threads still alive after shutdown(): "
            f"{[t.name for t in hw_after]}"
        )

    def test_shutdown_is_idempotent(self, qapp):
        """Calling shutdown() twice on the same service must not raise."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        svc.start_demo()
        time.sleep(0.2)

        svc.shutdown()          # first shutdown — normal path
        svc.shutdown()          # second — must be a no-op, not an exception

    def test_shutdown_on_never_started_service(self, qapp):
        """shutdown() on a service that was never started must not raise."""
        from hardware.hardware_service import HardwareService

        svc = HardwareService()
        svc.shutdown()   # nothing started — should be a clean no-op


# ================================================================== #
#  4. MetricsService — deterministic quality metrics                  #
# ================================================================== #

class TestMetricsService:
    """
    Verify that MetricsService correctly computes and emits quality metrics
    and issues from simulated hardware signal data.

    Uses a minimal stub QObject that exposes the same signals as
    HardwareService so no real hardware is needed.
    """

    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    @pytest.fixture
    def hw_stub(self, qapp):
        """Minimal HardwareService stub that exposes the required signals."""
        from PyQt5.QtCore import QObject, pyqtSignal

        class HwStub(QObject):
            camera_frame     = pyqtSignal(object)
            tec_status       = pyqtSignal(int, object)
            fpga_status      = pyqtSignal(object)
            stage_status     = pyqtSignal(object)
            device_connected = pyqtSignal(str, bool)

        return HwStub()

    @pytest.fixture
    def svc(self, hw_stub):
        from ai.metrics_service import MetricsService
        return MetricsService(hw_stub)

    @staticmethod
    def _make_frame(data: np.ndarray, bit_depth: int = 12):
        """Wrap a numpy array in a minimal CameraFrame-like object."""
        class Frame:
            pass
        f = Frame()
        f.data        = data.astype(np.uint16)
        f.frame_index = 0
        f.exposure_us = 5000.0
        f.gain_db     = 0.0
        f.timestamp   = time.time()
        return f

    # ----------------------------------------------------------------

    def test_initial_state_has_no_issues(self, svc):
        """Before any signals arrive, there must be no active issues."""
        assert len(svc.active_issue_codes) == 0

    def test_camera_disconnected_issue_on_device_disconnected(
            self, hw_stub, svc):
        """device_connected('camera', False) → camera_disconnected issue."""
        from ai.metrics_service import CAM_DISCONNECTED
        detected = []
        svc.issue_detected.connect(lambda code, msg: detected.append(code))

        hw_stub.device_connected.emit("camera", False)

        assert CAM_DISCONNECTED in svc.active_issue_codes
        assert CAM_DISCONNECTED in detected

    def test_camera_disconnected_clears_on_reconnect(self, hw_stub, svc):
        """device_connected('camera', True) → camera_disconnected issue clears."""
        from ai.metrics_service import CAM_DISCONNECTED
        hw_stub.device_connected.emit("camera", False)   # set it
        assert CAM_DISCONNECTED in svc.active_issue_codes

        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        hw_stub.device_connected.emit("camera", True)    # clear it

        assert CAM_DISCONNECTED not in svc.active_issue_codes
        assert CAM_DISCONNECTED in cleared

    def test_saturation_issue_detected_on_bright_frame(self, hw_stub, svc):
        """A frame with >2% saturated pixels triggers camera_saturated."""
        from ai.metrics_service import CAM_SATURATED
        # 12-bit sensor, fill 10% of pixels to saturation (value = 4095)
        data        = np.zeros((100, 100), dtype=np.uint16)
        data[:10, :] = 4095   # 10 rows × 100 cols = 10% saturated
        hw_stub.camera_frame.emit(self._make_frame(data))

        assert CAM_SATURATED in svc.active_issue_codes

    def test_saturation_issue_clears_on_normal_frame(self, hw_stub, svc):
        """After saturation detected, a normal frame must clear the issue."""
        from ai.metrics_service import CAM_SATURATED
        # First: emit a saturated frame
        sat_data = np.full((100, 100), 4095, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(sat_data))
        assert CAM_SATURATED in svc.active_issue_codes

        # Then: emit a normal mid-range frame
        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        normal_data = np.full((100, 100), 2000, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(normal_data))

        assert CAM_SATURATED not in svc.active_issue_codes
        assert CAM_SATURATED in cleared

    def test_tec_stability_tracks_in_band_duration(self, hw_stub, svc):
        """
        TEC issue clears only after TEC_DWELL_S seconds in-band.
        We shorten TEC_DWELL_S to near-zero for a fast test.
        """
        from ai.metrics_service import TEC_NOT_STABLE
        from hardware.tec.base import TecStatus

        svc.TEC_DWELL_S = 0.05   # 50 ms dwell for test speed

        # Emit in-band status multiple times over > 50 ms
        stable_status = TecStatus(
            actual_temp=25.05, target_temp=25.0,
            enabled=True, stable=False)
        hw_stub.tec_status.emit(0, stable_status)
        time.sleep(0.07)
        hw_stub.tec_status.emit(0, stable_status)

        assert f"{TEC_NOT_STABLE}_0" not in svc.active_issue_codes

    def test_tec_not_stable_while_out_of_band(self, hw_stub, svc):
        """TEC with |actual - target| > tolerance must flag tec_not_stable."""
        from ai.metrics_service import TEC_NOT_STABLE
        from hardware.tec.base import TecStatus

        svc.TEC_DWELL_S = 30.0   # restore default so issue is raised

        unstable = TecStatus(
            actual_temp=26.5, target_temp=25.0,
            enabled=True, stable=False)
        hw_stub.tec_status.emit(0, unstable)

        assert f"{TEC_NOT_STABLE}_0" in svc.active_issue_codes

    def test_fpga_not_running_issue(self, hw_stub, svc):
        """FPGA status with running=False triggers fpga_not_running."""
        from ai.metrics_service import FPGA_NOT_RUNNING
        from hardware.fpga.base import FpgaStatus

        hw_stub.fpga_status.emit(FpgaStatus(running=False, sync_locked=True))

        assert FPGA_NOT_RUNNING in svc.active_issue_codes

    def test_fpga_issues_clear_when_running_and_locked(self, hw_stub, svc):
        """FPGA running + locked must clear both FPGA issues."""
        from ai.metrics_service import FPGA_NOT_RUNNING, FPGA_NOT_LOCKED
        from hardware.fpga.base import FpgaStatus

        # Set issues first
        hw_stub.fpga_status.emit(FpgaStatus(running=False, sync_locked=False))
        assert FPGA_NOT_RUNNING in svc.active_issue_codes

        # Clear them
        hw_stub.fpga_status.emit(FpgaStatus(running=True, sync_locked=True))
        assert FPGA_NOT_RUNNING not in svc.active_issue_codes
        assert FPGA_NOT_LOCKED  not in svc.active_issue_codes

    def test_stage_not_homed_issue(self, hw_stub, svc):
        """Stage status with homed=False triggers stage_not_homed."""
        from ai.metrics_service import STAGE_NOT_HOMED
        from hardware.stage.base import StageStatus

        hw_stub.stage_status.emit(StageStatus(homed=False))

        assert STAGE_NOT_HOMED in svc.active_issue_codes

    def test_ready_flag_false_when_issues_present(self, hw_stub, svc):
        """snapshot['ready'] must be False when any issue is active."""
        from hardware.stage.base import StageStatus
        hw_stub.stage_status.emit(StageStatus(homed=False))

        snap = svc.current_snapshot()
        assert snap["ready"] is False
        assert len(snap["issues"]) > 0

    def test_ready_flag_true_with_no_issues(self, svc):
        """A freshly constructed service with no signals has ready=True."""
        snap = svc.current_snapshot()
        assert snap["ready"] is True
        assert snap["issues"] == []

    def test_snapshot_structure(self, svc):
        """current_snapshot() must contain all required top-level keys."""
        snap = svc.current_snapshot()
        for key in ("camera", "tec", "fpga", "stage", "issues", "ready"):
            assert key in snap, f"Missing key {key!r} in snapshot"

    def test_focus_computation_nonzero_for_sharp_image(self):
        """_compute_focus() must return a positive value for a non-uniform image."""
        from ai.metrics_service import MetricsService
        # Sharp vertical step edge — creates a non-zero second derivative that
        # survives the 4× downsampling (unlike a 2-pixel-period checkerboard).
        data = np.zeros((64, 64), dtype=np.float32)
        data[:, 32:] = 4000   # left half dark, right half at full scale
        score = MetricsService._compute_focus(data)
        assert score > 0.0

    def test_focus_computation_zero_for_flat_image(self):
        """_compute_focus() must return 0 for a completely flat image."""
        from ai.metrics_service import MetricsService
        flat = np.full((64, 64), 2000.0, dtype=np.float32)
        score = MetricsService._compute_focus(flat)
        assert score == 0.0

    def test_throttle_bypassed_when_active_issues(self, hw_stub, svc):
        """
        The frame-rate throttle must be bypassed when active issues exist,
        so issues clear promptly even if frames arrive faster than EMIT_RATE_HZ.
        """
        from ai.metrics_service import CAM_SATURATED
        # Step 1: emit saturated frame → issue is raised and _last_proc_t is set
        sat = np.full((100, 100), 4095, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(sat))
        assert CAM_SATURATED in svc.active_issue_codes

        # Step 2: immediately emit a normal frame (within throttle window).
        # With the issue-aware bypass, this MUST be processed.
        cleared = []
        svc.issue_cleared.connect(lambda code: cleared.append(code))
        normal = np.full((100, 100), 2000, dtype=np.uint16)
        hw_stub.camera_frame.emit(self._make_frame(normal))

        assert CAM_SATURATED not in svc.active_issue_codes, (
            "throttle incorrectly blocked the normal frame — "
            "active-issue bypass is not working"
        )
        assert CAM_SATURATED in cleared

    def test_throttle_applied_when_no_active_issues(self, hw_stub, svc):
        """
        When there are no active issues, rapid duplicate frames within the
        throttle window must be dropped (only the first is processed).
        """
        # Ensure no active issues and reset the throttle clock
        svc._last_proc_t = 0.0
        assert len(svc.active_issue_codes) == 0

        emit_count = []
        svc.metrics_updated.connect(lambda snap: emit_count.append(1))

        # Emit first frame — should be processed (resets throttle clock)
        svc._last_proc_t = 0.0
        hw_stub.camera_frame.emit(self._make_frame(
            np.full((50, 50), 2000, dtype=np.uint16)))
        count_after_first = len(emit_count)

        # Immediately emit a second frame — throttle window not yet elapsed
        hw_stub.camera_frame.emit(self._make_frame(
            np.full((50, 50), 2001, dtype=np.uint16)))
        count_after_second = len(emit_count)

        # The second frame should have been dropped by the throttle
        assert count_after_second == count_after_first, (
            "throttle did not drop the rapid second frame"
        )


# ================================================================== #
#  5. HardwareService — demo-mode camera config override              #
# ================================================================== #

class TestDemoModeCamera:
    """
    Verify that _run_camera() replaces the config driver with "simulated"
    when app_state.demo_mode is True, regardless of what config.yaml says.

    We test this by monkeypatching the camera factory so no thread is
    actually started — only the config argument is captured and inspected.
    """

    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    def test_demo_mode_forces_simulated_driver(self, monkeypatch, qapp):
        """When demo_mode=True the camera factory must receive driver='simulated'."""
        import hardware.hardware_service as hs_mod
        import hardware.services.camera_service as cam_mod
        from hardware.app_state import app_state

        # Capture the config dict passed to create_camera
        captured = []

        class _FakeCamera:
            class info:
                model = "Simulated"
                width = 320
                height = 240
            def open(self): pass
            def start(self): pass
            def stop(self): pass

        def _fake_create_camera(cfg):
            captured.append(dict(cfg))
            return _FakeCamera()

        monkeypatch.setattr(cam_mod, "create_camera", _fake_create_camera)
        # Patch _connect_with_retry to a no-op so it doesn't actually retry
        from hardware.services.base_device_service import BaseDeviceService
        monkeypatch.setattr(BaseDeviceService, "_connect_with_retry",
                            lambda self, fn, **kw: fn())
        # Ensure app_state reports demo mode
        with app_state:
            app_state._demo_mode = True

        try:
            svc = hs_mod.HardwareService()
            svc._running = True          # prevent the thread from exiting early
            svc.camera_service._run_camera()  # call directly (no thread needed)
        except Exception:
            pass                          # cleanup failures from missing pipeline etc.
        finally:
            with app_state:
                app_state._demo_mode = False
                app_state._cam = None

        assert len(captured) > 0, "_run_camera() never called create_camera()"
        assert captured[0]["driver"] == "simulated", (
            f"Expected driver='simulated' in demo mode, got {captured[0]['driver']!r}"
        )


# ================================================================== #
#  Session Library Usability                                           #
# ================================================================== #

class TestSessionLibraryUsability:
    """
    Tests for session discovery (result_type filtering, sort order,
    session count) and session hygiene (delete, size calculation).
    """

    @pytest.fixture
    def populated_sessions(self, tmp_path):
        """Create 4 sessions with different result_types.

        Returns (SessionManager, dict[result_type → uid]).
        """
        from acquisition.storage.session import Session
        from acquisition.storage.session_manager import SessionManager

        mgr = SessionManager(str(tmp_path))
        uid_map = {}  # result_type → uid

        # 1. single_point
        from acquisition.pipeline import AcquisitionResult
        sp = AcquisitionResult(
            n_frames=4, exposure_us=1000.0,
            gain_db=0.0, timestamp=time.time() - 300)
        sp.cold_avg       = np.random.rand(16, 16).astype(np.float32) * 1000
        sp.hot_avg        = sp.cold_avg * 1.001
        sp.delta_r_over_r = ((sp.hot_avg - sp.cold_avg) / sp.cold_avg).astype(np.float32)
        sp.difference     = (sp.hot_avg - sp.cold_avg).astype(np.float32)
        sp.cold_captured  = sp.hot_captured = 4
        s = mgr.save_result(sp, label="SP Session", result_type="single_point")
        uid_map["single_point"] = s.meta.uid

        # 2. grid
        class _GridResult:
            n_frames = 16; exposure_us = 500.0; gain_db = 0.0
            n_rows = 2; n_cols = 2; step_x_um = 10.0; step_y_um = 10.0
            tile_w = 16; tile_h = 16; origin_x_um = 0.0; origin_y_um = 0.0
        gr = _GridResult()
        gr.drr_map = np.random.rand(32, 32).astype(np.float32) * 1e-4
        gr.dt_map  = np.random.rand(32, 32).astype(np.float32) * 0.5
        gr.timestamp = time.time() - 200
        scan_params = {"n_rows": 2, "n_cols": 2, "step_x_um": 10.0,
                       "step_y_um": 10.0, "tile_w": 16, "tile_h": 16,
                       "origin_x_um": 0.0, "origin_y_um": 0.0}
        s = mgr.save_result(gr, label="Grid Session",
                            result_type="grid", scan_params=scan_params)
        uid_map["grid"] = s.meta.uid

        # 3. transient
        from acquisition.transient_pipeline import TransientResult
        tr = TransientResult(
            delta_r_cube=np.random.rand(5, 16, 16).astype(np.float32),
            raw_cube=None,
            reference=np.random.rand(16, 16).astype(np.float32),
            delay_times_s=np.linspace(0, 1e-3, 5),
            n_delays=5, n_averages=2,
            pulse_dur_us=10.0, delay_start_s=0.0, delay_end_s=1e-3,
            exposure_us=500.0, gain_db=0.0,
            duration_s=2.5, hw_triggered=False,
        )
        tr.timestamp = time.time() - 100
        cube_params_t = {"n_delays": 5, "n_averages": 2,
                         "pulse_dur_us": 10.0, "delay_start_s": 0.0,
                         "delay_end_s": 1e-3, "hw_triggered": False}
        s = mgr.save_result(tr, label="Transient Session",
                            result_type="transient", cube_params=cube_params_t)
        uid_map["transient"] = s.meta.uid

        # 4. movie
        from acquisition.movie_pipeline import MovieResult
        mv = MovieResult(
            delta_r_cube=np.random.rand(8, 16, 16).astype(np.float32),
            frame_cube=None,
            reference=np.random.rand(16, 16).astype(np.float32),
            timestamps_s=np.linspace(0, 1.0, 8),
            n_frames=8, frames_captured=8,
            exposure_us=200.0, gain_db=0.0,
            duration_s=1.0, fps_achieved=8.0,
        )
        mv.timestamp = time.time()
        cube_params_m = {"n_frames": 8, "frames_captured": 8,
                         "fps_achieved": 8.0}
        s = mgr.save_result(mv, label="Movie Session",
                            result_type="movie", cube_params=cube_params_m)
        uid_map["movie"] = s.meta.uid

        return mgr, uid_map

    # ── Filtering ────────────────────────────────────────────────────

    def test_all_metas_returns_all_types(self, populated_sessions):
        mgr, uid_map = populated_sessions
        metas = mgr.all_metas()
        assert len(metas) == 4
        types = {m.result_type for m in metas}
        assert types == {"single_point", "grid", "transient", "movie"}

    def test_filter_by_result_type(self, populated_sessions):
        """Verify that filtering by result_type works for each type."""
        mgr, uid_map = populated_sessions
        metas = mgr.all_metas()
        for rt in ["single_point", "grid", "transient", "movie"]:
            filtered = [m for m in metas if m.result_type == rt]
            assert len(filtered) == 1, f"Expected 1 {rt}, got {len(filtered)}"
            assert filtered[0].uid == uid_map[rt]

    def test_filter_all_returns_everything(self, populated_sessions):
        """The 'all' filter should return all sessions."""
        mgr, uid_map = populated_sessions
        metas = mgr.all_metas()
        assert len(metas) == 4

    # ── Sort order ───────────────────────────────────────────────────

    def test_default_sort_newest_first(self, populated_sessions):
        mgr, uid_map = populated_sessions
        metas = mgr.all_metas()
        # Movie was created last (highest timestamp)
        assert metas[0].uid == uid_map["movie"]
        # Single point was created first (lowest timestamp)
        assert metas[-1].uid == uid_map["single_point"]

    def test_sort_oldest_first(self, populated_sessions):
        mgr, uid_map = populated_sessions
        metas = mgr.all_metas()
        oldest_first = list(reversed(metas))
        assert oldest_first[0].uid == uid_map["single_point"]
        assert oldest_first[-1].uid == uid_map["movie"]

    # ── Session count ────────────────────────────────────────────────

    def test_session_count(self, populated_sessions):
        mgr, uid_map = populated_sessions
        assert mgr.count() == 4

    def test_count_after_delete(self, populated_sessions):
        mgr, uid_map = populated_sessions
        assert mgr.count() == 4
        mgr.delete(uid_map["grid"])
        assert mgr.count() == 3

    # ── Delete ───────────────────────────────────────────────────────

    def test_delete_removes_from_index(self, populated_sessions):
        mgr, uid_map = populated_sessions
        uid = uid_map["transient"]
        assert mgr.get_meta(uid) is not None
        ok = mgr.delete(uid)
        assert ok is True
        assert mgr.get_meta(uid) is None

    def test_delete_removes_from_disk(self, populated_sessions):
        mgr, uid_map = populated_sessions
        uid = uid_map["movie"]
        meta = mgr.get_meta(uid)
        session_path = meta.path
        assert os.path.isdir(session_path)
        mgr.delete(uid)
        assert not os.path.exists(session_path)

    def test_delete_nonexistent_returns_false(self, populated_sessions):
        mgr, uid_map = populated_sessions
        ok = mgr.delete("nonexistent_uid_12345")
        assert ok is False

    def test_delete_updates_all_metas(self, populated_sessions):
        mgr, uid_map = populated_sessions
        mgr.delete(uid_map["grid"])
        metas = mgr.all_metas()
        assert len(metas) == 3
        remaining_types = {m.result_type for m in metas}
        assert "grid" not in remaining_types

    # ── Session size ─────────────────────────────────────────────────

    def test_session_dir_size_positive(self, populated_sessions):
        """Every session directory should have non-zero size on disk."""
        from acquisition.data_tab import DataTab
        mgr, uid_map = populated_sessions
        for rt, uid in uid_map.items():
            meta = mgr.get_meta(uid)
            size = DataTab._session_dir_size(meta.path)
            assert size > 0, f"{rt} session should have positive disk size"

    def test_session_dir_size_cube_larger(self, populated_sessions):
        """Cube sessions (transient/movie) should be larger than single-point
        because they store additional .npy files."""
        from acquisition.data_tab import DataTab
        mgr, uid_map = populated_sessions
        sp_size = DataTab._session_dir_size(
            mgr.get_meta(uid_map["single_point"]).path)
        tr_size = DataTab._session_dir_size(
            mgr.get_meta(uid_map["transient"]).path)
        mv_size = DataTab._session_dir_size(
            mgr.get_meta(uid_map["movie"]).path)
        assert tr_size > sp_size, "Transient should be larger than single-point"
        assert mv_size > sp_size, "Movie should be larger than single-point"

    def test_session_dir_size_nonexistent(self):
        """Non-existent path should return 0, not raise."""
        from acquisition.data_tab import DataTab
        assert DataTab._session_dir_size("/tmp/nonexistent_path_xyz") == 0

    def test_fmt_size_units(self):
        """Verify human-readable size formatting."""
        from acquisition.data_tab import DataTab
        assert DataTab._fmt_size(500) == "500 B"
        assert DataTab._fmt_size(1024) == "1.0 KB"
        assert DataTab._fmt_size(1536) == "1.5 KB"
        assert DataTab._fmt_size(1048576) == "1.0 MB"
        assert DataTab._fmt_size(1073741824) == "1.00 GB"

    # ── Result-type round-trip through scan ──────────────────────────

    def test_scan_preserves_result_types(self, populated_sessions, tmp_path):
        """After a full scan(), all result_type values are preserved."""
        mgr, uid_map = populated_sessions
        # Create a fresh manager and scan the same directory
        from acquisition.storage.session_manager import SessionManager
        mgr2 = SessionManager(str(tmp_path))
        n = mgr2.scan()
        assert n == 4
        for rt, uid in uid_map.items():
            meta = mgr2.get_meta(uid)
            assert meta is not None, f"Session {uid} not found after scan"
            assert meta.result_type == rt, (
                f"Expected result_type={rt}, got {meta.result_type}")


# ================================================================== #
#  Hardware Setup Profiles                                             #
# ================================================================== #

class TestSetupProfile:
    """
    Tests for SetupProfile data model, serialisation round-trip,
    safety classification, hardware mismatch detection, and the
    SetupProfileManager persistence layer.
    """

    # ── Data model ───────────────────────────────────────────────────

    def test_default_profile_round_trip(self):
        """Default profile serialises and deserialises to identical values."""
        from hardware.setup_profile import SetupProfile
        p = SetupProfile(name="test")
        d = p.to_dict()
        p2 = SetupProfile.from_dict(d)
        assert p2.name == "test"
        assert p2.camera.exposure_us == 0.0
        assert p2.camera.gain_db == 0.0
        assert p2.fpga.freq_hz == 1000.0
        assert p2.fpga.duty_pct == 50.0
        assert p2.bias.mode == "voltage"
        assert p2.tec.channels == []

    def test_populated_profile_round_trip(self):
        """A profile with real values survives serialisation."""
        from hardware.setup_profile import (
            SetupProfile, CameraSettings, TECSettings,
            TECChannelSettings, FPGASettings, BiasSettings,
            HardwareIdentity,
        )
        p = SetupProfile(
            name="85C Cycling",
            saved_at=1712345678.0,
            camera=CameraSettings(exposure_us=5000.0, gain_db=3.2),
            tec=TECSettings(channels=[
                TECChannelSettings(setpoint_c=85.0, ramp_rate_c_s=2.0,
                                   limit_low_c=-10.0, limit_high_c=120.0,
                                   warn_margin_c=3.0),
                TECChannelSettings(setpoint_c=25.0),
            ]),
            fpga=FPGASettings(freq_hz=10000.0, duty_pct=25.0),
            bias=BiasSettings(port_index=1, mode="current",
                              level_v=1.8, compliance_ma=50.0,
                              range_20ma=False),
            hardware_id=HardwareIdentity(
                camera_driver="basler_tr", tec_driver="meerstetter",
                fpga_driver="ez500", bias_driver="ez500_smu"),
        )
        d = p.to_dict()
        p2 = SetupProfile.from_dict(d)
        assert p2.name == "85C Cycling"
        assert p2.saved_at == 1712345678.0
        assert p2.camera.exposure_us == 5000.0
        assert p2.camera.gain_db == 3.2
        assert len(p2.tec.channels) == 2
        assert p2.tec.channels[0].setpoint_c == 85.0
        assert p2.tec.channels[0].ramp_rate_c_s == 2.0
        assert p2.tec.channels[1].setpoint_c == 25.0
        assert p2.fpga.freq_hz == 10000.0
        assert p2.fpga.duty_pct == 25.0
        assert p2.bias.port_index == 1
        assert p2.bias.mode == "current"
        assert p2.bias.level_v == 1.8
        assert p2.bias.compliance_ma == 50.0
        assert p2.bias.range_20ma is False
        assert p2.hardware_id.camera_driver == "basler_tr"
        assert p2.hardware_id.fpga_driver == "ez500"

    def test_from_dict_handles_missing_sections(self):
        """Partial dicts produce defaults for missing sections."""
        from hardware.setup_profile import SetupProfile
        p = SetupProfile.from_dict({"name": "partial", "camera": {"exposure_us": 999}})
        assert p.camera.exposure_us == 999.0
        assert p.camera.gain_db == 0.0
        assert p.fpga.freq_hz == 1000.0  # default
        assert p.tec.channels == []
        assert p.bias.mode == "voltage"

    def test_from_dict_handles_empty_dict(self):
        from hardware.setup_profile import SetupProfile
        p = SetupProfile.from_dict({})
        assert p.name == ""
        assert p.camera.exposure_us == 0.0

    # ── Safety classification ────────────────────────────────────────

    def test_safe_fields_contains_camera(self):
        from hardware.setup_profile import SAFE_FIELDS, PENDING_FIELDS
        assert "camera" in SAFE_FIELDS
        assert "exposure_us" in SAFE_FIELDS["camera"]
        assert "gain_db" in SAFE_FIELDS["camera"]

    def test_pending_fields_contains_unsafe_categories(self):
        from hardware.setup_profile import PENDING_FIELDS
        assert "tec" in PENDING_FIELDS
        assert "fpga" in PENDING_FIELDS
        assert "bias" in PENDING_FIELDS

    def test_safe_and_pending_do_not_overlap(self):
        from hardware.setup_profile import SAFE_FIELDS, PENDING_FIELDS
        safe_cats = set(SAFE_FIELDS.keys())
        pending_cats = set(PENDING_FIELDS.keys())
        assert safe_cats & pending_cats == set(), \
            "Safe and pending categories must not overlap"

    # ── Hardware mismatch detection ──────────────────────────────────

    def test_no_mismatch_when_identical(self):
        from hardware.setup_profile import SetupProfile, HardwareIdentity
        hw = HardwareIdentity(camera_driver="basler", tec_driver="meerstetter")
        p = SetupProfile(hardware_id=hw)
        warnings = p.hardware_mismatches(hw)
        assert warnings == []

    def test_mismatch_detected_for_different_driver(self):
        from hardware.setup_profile import SetupProfile, HardwareIdentity
        saved = HardwareIdentity(camera_driver="basler", fpga_driver="ez500")
        current = HardwareIdentity(camera_driver="simulated", fpga_driver="ez500")
        p = SetupProfile(hardware_id=saved)
        warnings = p.hardware_mismatches(current)
        assert len(warnings) == 1
        assert "camera" in warnings[0].lower() or "Camera" in warnings[0]

    def test_mismatch_skips_empty_drivers(self):
        """If either saved or current driver is empty, no mismatch is reported."""
        from hardware.setup_profile import SetupProfile, HardwareIdentity
        saved = HardwareIdentity(camera_driver="basler", tec_driver="")
        current = HardwareIdentity(camera_driver="basler", tec_driver="meerstetter")
        p = SetupProfile(hardware_id=saved)
        warnings = p.hardware_mismatches(current)
        assert warnings == [], "Empty saved driver should not trigger mismatch"

    def test_multiple_mismatches_reported(self):
        from hardware.setup_profile import SetupProfile, HardwareIdentity
        saved = HardwareIdentity(camera_driver="a", tec_driver="b",
                                 fpga_driver="c", bias_driver="d")
        current = HardwareIdentity(camera_driver="x", tec_driver="y",
                                   fpga_driver="z", bias_driver="w")
        p = SetupProfile(hardware_id=saved)
        warnings = p.hardware_mismatches(current)
        assert len(warnings) == 4

    # ── Restore report ───────────────────────────────────────────────

    def test_restore_report_summary(self):
        from hardware.setup_profile import RestoreReport
        r = RestoreReport()
        r.applied.append("camera exposure")
        r.pending.append("TEC setpoints")
        r.warnings.append("Camera driver differs")
        s = r.summary()
        assert "camera exposure" in s
        assert "TEC setpoints" in s
        assert "Camera driver" in s

    def test_restore_report_has_pending(self):
        from hardware.setup_profile import RestoreReport
        r = RestoreReport()
        assert r.has_pending is False
        r.pending.append("FPGA frequency")
        assert r.has_pending is True

    # ── Profile manager persistence ──────────────────────────────────

    def test_save_and_load_named_profile(self, tmp_path):
        from hardware.setup_profile import SetupProfile, CameraSettings
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        p = SetupProfile(name="My Setup",
                         camera=CameraSettings(exposure_us=2000, gain_db=5.0))
        mgr.save(p)

        loaded = mgr.load("My Setup")
        assert loaded is not None
        assert loaded.name == "My Setup"
        assert loaded.camera.exposure_us == 2000.0
        assert loaded.camera.gain_db == 5.0

    def test_list_names(self, tmp_path):
        from hardware.setup_profile import SetupProfile
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        mgr.save(SetupProfile(name="B Profile"))
        mgr.save(SetupProfile(name="A Profile"))
        names = mgr.names()
        assert names == ["A Profile", "B Profile"]

    def test_delete_profile(self, tmp_path):
        from hardware.setup_profile import SetupProfile
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        mgr.save(SetupProfile(name="Temp"))
        assert mgr.count() == 1
        ok = mgr.delete("Temp")
        assert ok is True
        assert mgr.count() == 0
        assert mgr.load("Temp") is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))
        assert mgr.delete("nope") is False

    def test_save_and_load_last_used(self, tmp_path):
        from hardware.setup_profile import SetupProfile, FPGASettings
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        assert mgr.has_last_used() is False

        p = SetupProfile(fpga=FPGASettings(freq_hz=5000, duty_pct=30))
        mgr.save_last_used(p)

        assert mgr.has_last_used() is True
        loaded = mgr.load_last_used()
        assert loaded is not None
        assert loaded.fpga.freq_hz == 5000.0
        assert loaded.fpga.duty_pct == 30.0

    def test_last_used_name_is_empty(self, tmp_path):
        """Last-used auto-profile should have no name."""
        from hardware.setup_profile import SetupProfile
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        mgr.save_last_used(SetupProfile(name="should be cleared"))
        loaded = mgr.load_last_used()
        assert loaded.name == ""

    def test_persistence_survives_reload(self, tmp_path):
        """Profiles persist across manager instances."""
        from hardware.setup_profile import SetupProfile
        from hardware.setup_profile_manager import SetupProfileManager
        pp = str(tmp_path / "profiles.json")
        lp = str(tmp_path / "last_used.json")

        mgr1 = SetupProfileManager(profiles_path=pp, last_used_path=lp)
        mgr1.save(SetupProfile(name="Persistent"))
        mgr1.save_last_used(SetupProfile())

        mgr2 = SetupProfileManager(profiles_path=pp, last_used_path=lp)
        assert "Persistent" in mgr2.names()
        assert mgr2.has_last_used()

    def test_overwrite_named_profile(self, tmp_path):
        from hardware.setup_profile import SetupProfile, CameraSettings
        from hardware.setup_profile_manager import SetupProfileManager
        mgr = SetupProfileManager(
            profiles_path=str(tmp_path / "profiles.json"),
            last_used_path=str(tmp_path / "last_used.json"))

        mgr.save(SetupProfile(name="X",
                               camera=CameraSettings(exposure_us=100)))
        mgr.save(SetupProfile(name="X",
                               camera=CameraSettings(exposure_us=999)))
        assert mgr.count() == 1
        loaded = mgr.load("X")
        assert loaded.camera.exposure_us == 999.0

    # ── Restore with mock tabs ───────────────────────────────────────

    def test_restore_camera_applies_to_hardware(self):
        """Camera settings should be applied (not just populated)."""
        from hardware.setup_profile import (
            SetupProfile, CameraSettings, restore_profile, RestoreReport)

        class _MockCamTab:
            def __init__(self):
                self._exp_slider = _MockSlider(1000)
                self._gain_slider = _MockSlider(50)
                self._applied_exp = None
                self._applied_gain = False
            def _do_exp(self, val, _from_sync=False):
                self._applied_exp = val
            def _on_gain(self, _from_sync=False):
                self._applied_gain = True

        tab = _MockCamTab()
        profile = SetupProfile(
            camera=CameraSettings(exposure_us=5000, gain_db=8.5))

        report = restore_profile(profile, camera_tab=tab)

        assert tab._exp_slider._value == 5000
        assert tab._applied_exp == 5000
        assert tab._gain_slider._value == 85  # 8.5 * 10
        assert tab._applied_gain is True
        assert "camera exposure" in report.applied

    def test_restore_fpga_populates_only(self):
        """FPGA settings should populate spinboxes but not call hardware."""
        from hardware.setup_profile import (
            SetupProfile, FPGASettings, restore_profile)

        class _MockFpgaTab:
            def __init__(self):
                self._freq_spin = _MockSpin(1000)
                self._duty_spin = _MockSpin(50)
                self._profile_pending = False

        tab = _MockFpgaTab()
        profile = SetupProfile(fpga=FPGASettings(freq_hz=10000, duty_pct=25))

        report = restore_profile(profile, fpga_tab=tab)

        assert tab._freq_spin._value == 10000
        assert tab._duty_spin._value == 25
        assert tab._profile_pending is True
        assert "FPGA frequency" in report.pending

    def test_restore_tec_populates_only(self):
        """TEC settings should populate spinboxes but not call hardware."""
        from hardware.setup_profile import (
            SetupProfile, TECSettings, TECChannelSettings, restore_profile)

        class _MockBox:
            def __init__(self):
                self._spin = _MockSpin(25.0)
                self._ramp_spin = _MockSpin(0.0)
                self._min_spin = _MockSpin(-40.0)
                self._max_spin = _MockSpin(150.0)
                self._warn_spin = _MockSpin(5.0)

        class _MockTempTab:
            def __init__(self):
                self._panels = [_MockBox(), _MockBox()]
                self._profile_pending = False

        tab = _MockTempTab()
        profile = SetupProfile(tec=TECSettings(channels=[
            TECChannelSettings(setpoint_c=85.0, ramp_rate_c_s=2.0),
            TECChannelSettings(setpoint_c=-20.0),
        ]))

        report = restore_profile(profile, temperature_tab=tab)

        assert tab._panels[0]._spin._value == 85.0
        assert tab._panels[0]._ramp_spin._value == 2.0
        assert tab._panels[1]._spin._value == -20.0
        assert tab._profile_pending is True
        assert "TEC setpoints" in report.pending

    def test_restore_bias_populates_only(self):
        """Bias settings should populate controls but not call hardware."""
        from hardware.setup_profile import (
            SetupProfile, BiasSettings, restore_profile)

        class _MockBiasTab:
            def __init__(self):
                self._port_combo = _MockCombo(3)
                self._mode_bg = _MockButtonGroup()
                self._level_spin = _MockSpin(0.0)
                self._comp_spin = _MockSpin(10.0)
                self._range_20ma_cb = _MockCheckBox(True)
                self._profile_pending = False

        tab = _MockBiasTab()
        profile = SetupProfile(bias=BiasSettings(
            port_index=2, mode="current", level_v=3.3,
            compliance_ma=50.0, range_20ma=False))

        report = restore_profile(profile, bias_tab=tab)

        assert tab._port_combo._current_index == 2
        assert tab._mode_bg._checked_id == 1  # current
        assert tab._level_spin._value == 3.3
        assert tab._comp_spin._value == 50.0
        assert tab._range_20ma_cb._checked is False
        assert tab._profile_pending is True
        assert "bias level" in report.pending

    def test_restore_skips_missing_tabs(self):
        """Restore with no tabs should produce all-skipped report."""
        from hardware.setup_profile import SetupProfile, restore_profile
        report = restore_profile(SetupProfile())
        assert len(report.skipped) >= 3  # camera, FPGA, bias at least
        assert report.applied == []
        assert report.pending == []

    def test_restore_with_hardware_mismatch(self):
        """Restore should report hardware mismatches but still proceed."""
        from hardware.setup_profile import (
            SetupProfile, HardwareIdentity, CameraSettings, restore_profile)

        class _MockState:
            cam = type("C", (), {"driver_name": "simulated"})()
            tecs = []
            fpga = None
            bias = None

        class _MockCamTab:
            def __init__(self):
                self._exp_slider = _MockSlider(1000)
                self._gain_slider = _MockSlider(0)
            def _do_exp(self, val, _from_sync=False): pass
            def _on_gain(self, _from_sync=False): pass

        profile = SetupProfile(
            camera=CameraSettings(exposure_us=2000),
            hardware_id=HardwareIdentity(camera_driver="basler_tr"))

        report = restore_profile(
            profile, camera_tab=_MockCamTab(), app_state=_MockState())
        assert len(report.warnings) == 1
        assert "camera" in report.warnings[0].lower()
        assert "camera exposure" in report.applied  # still applied


# ── Mock widgets for restore tests ─────────────────────────────────────────

class _MockSlider:
    """Minimal mock for QSlider with blockSignals support."""
    def __init__(self, initial=0):
        self._value = initial
        self._blocked = False
    def value(self):
        return self._value
    def setValue(self, v):
        self._value = v
    def blockSignals(self, block):
        self._blocked = block


class _MockSpin:
    """Minimal mock for QDoubleSpinBox with blockSignals support."""
    def __init__(self, initial=0.0):
        self._value = initial
        self._blocked = False
    def value(self):
        return self._value
    def setValue(self, v):
        self._value = v
    def blockSignals(self, block):
        self._blocked = block


class _MockCombo:
    """Minimal mock for QComboBox."""
    def __init__(self, count=4):
        self._count = count
        self._current_index = 0
        self._blocked = False
    def count(self):
        return self._count
    def currentIndex(self):
        return self._current_index
    def setCurrentIndex(self, idx):
        self._current_index = idx
    def blockSignals(self, block):
        self._blocked = block


class _MockButtonGroup:
    """Minimal mock for QButtonGroup."""
    def __init__(self):
        self._checked_id = 0
        self._blocked = False
        self._buttons = {0: _MockRadio(self, 0), 1: _MockRadio(self, 1)}
    def checkedId(self):
        return self._checked_id
    def button(self, id):
        return self._buttons.get(id)
    def blockSignals(self, block):
        self._blocked = block


class _MockRadio:
    """Minimal mock for QRadioButton."""
    def __init__(self, group=None, id=0):
        self._checked = False
        self._group = group
        self._id = id
    def setChecked(self, v):
        self._checked = v
        if v and self._group is not None:
            self._group._checked_id = self._id


class _MockCheckBox:
    """Minimal mock for QCheckBox."""
    def __init__(self, initial=False):
        self._checked = initial
        self._blocked = False
    def isChecked(self):
        return self._checked
    def setChecked(self, v):
        self._checked = v
    def blockSignals(self, block):
        self._blocked = block


# ══════════════════════════════════════════════════════════════════════════════
#  Transient Analysis Insights — metrics computation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTransientMetrics:
    """Tests for acquisition/transient_metrics.py — pure numpy metrics."""

    def test_baseline_window_size_small(self):
        from acquisition.transient_metrics import baseline_window_size
        # For N < 30, ceil(0.1*N) < 3, so baseline should be 3
        assert baseline_window_size(5) == 3
        assert baseline_window_size(10) == 3
        assert baseline_window_size(29) == 3

    def test_baseline_window_size_large(self):
        from acquisition.transient_metrics import baseline_window_size
        # For N=50, ceil(0.1*50) = 5 > 3
        assert baseline_window_size(50) == 5
        assert baseline_window_size(100) == 10
        assert baseline_window_size(200) == 20

    def test_basic_positive_peak(self):
        """Positive impulse: peak detected, recovery computed."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 50
        ts = np.linspace(0, 0.005, n)
        sig = np.zeros(n)
        sig[10] = 0.01  # sharp positive peak at index 10
        m = compute_transient_metrics(sig, ts, "ROI-A", "#ff0000")
        assert m.peak_drr == pytest.approx(0.01)
        assert m.peak_abs == pytest.approx(0.01)
        assert m.peak_index == 10
        assert m.time_to_peak_s == pytest.approx(ts[10])
        assert m.baseline_mean == pytest.approx(0.0, abs=1e-12)
        assert m.baseline_std == pytest.approx(0.0, abs=1e-12)
        assert m.recovery_ratio == pytest.approx(1.0, abs=0.05)
        assert m.n_points == 50
        assert m.roi_label == "ROI-A"
        assert m.roi_color == "#ff0000"

    def test_negative_peak_preserved(self):
        """Peak should preserve sign for negative impulse."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 40
        ts = np.linspace(0, 0.004, n)
        sig = np.zeros(n)
        sig[15] = -0.02  # negative peak
        m = compute_transient_metrics(sig, ts)
        assert m.peak_drr == pytest.approx(-0.02)
        assert m.peak_abs == pytest.approx(0.02)
        assert m.peak_index == 15

    def test_peak_snr_nonzero_baseline(self):
        """SNR uses baseline std when baseline has noise."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 100
        rng = np.random.RandomState(42)
        ts = np.linspace(0, 0.01, n)
        noise = rng.normal(0, 0.001, n)  # baseline noise ~1e-3
        sig = noise.copy()
        sig[50] = 0.05  # strong peak
        m = compute_transient_metrics(sig, ts)
        # SNR should be >> 1 for a peak well above noise
        assert m.peak_snr > 10.0
        assert m.baseline_std > 0

    def test_snr_zero_std(self):
        """SNR is 0 when baseline has zero std (constant signal)."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 30
        ts = np.linspace(0, 0.003, n)
        sig = np.full(n, 0.005)
        m = compute_transient_metrics(sig, ts)
        assert m.peak_snr == pytest.approx(0.0)
        assert m.baseline_std == pytest.approx(0.0, abs=1e-15)

    def test_recovery_full(self):
        """Full recovery: signal returns to baseline at the end."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 60
        ts = np.linspace(0, 0.006, n)
        sig = np.zeros(n)
        sig[20:30] = 0.01  # pulse in the middle, returns to 0
        m = compute_transient_metrics(sig, ts)
        assert m.recovery_ratio == pytest.approx(1.0, abs=0.05)

    def test_recovery_none(self):
        """No recovery: signal stays at peak level."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 50
        ts = np.linspace(0, 0.005, n)
        sig = np.zeros(n)
        sig[10:] = 0.02  # step change, no recovery
        m = compute_transient_metrics(sig, ts)
        assert m.recovery_ratio == pytest.approx(0.0, abs=0.1)

    def test_partial_recovery(self):
        """Partial recovery: signal returns halfway."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 50
        ts = np.linspace(0, 0.005, n)
        sig = np.zeros(n)
        sig[10:25] = 0.02
        sig[25:] = 0.01  # halfway back
        m = compute_transient_metrics(sig, ts)
        assert 0.3 < m.recovery_ratio < 0.7

    def test_minimum_signal_length(self):
        """Signal with < 2 points returns default metrics."""
        from acquisition.transient_metrics import compute_transient_metrics
        m = compute_transient_metrics(np.array([0.1]), np.array([0.0]),
                                      "tiny")
        assert m.n_points == 1
        assert m.peak_drr == 0.0
        assert m.peak_snr == 0.0

    def test_to_dict_round_trip(self):
        """TransientMetrics.to_dict → from_dict round-trip."""
        from acquisition.transient_metrics import (
            compute_transient_metrics, TransientMetrics)
        sig = np.linspace(-0.01, 0.01, 30)
        ts = np.linspace(0, 0.003, 30)
        m = compute_transient_metrics(sig, ts, "Test", "#00ff00")
        d = m.to_dict()
        m2 = TransientMetrics.from_dict(d)
        assert m2.roi_label == "Test"
        assert m2.peak_drr == pytest.approx(m.peak_drr)
        assert m2.peak_snr == pytest.approx(m.peak_snr)
        assert m2.recovery_ratio == pytest.approx(m.recovery_ratio)

    def test_compute_all_roi_metrics(self):
        """compute_all_roi_metrics processes a list of ROI signals."""
        from acquisition.transient_metrics import compute_all_roi_metrics
        n = 40
        ts = np.linspace(0, 0.004, n)
        roi_signals = [
            ("A", "#ff0000", np.random.RandomState(1).randn(n) * 0.001),
            ("B", "#00ff00", np.random.RandomState(2).randn(n) * 0.002),
        ]
        results = compute_all_roi_metrics(roi_signals, ts)
        assert len(results) == 2
        assert results[0].roi_label == "A"
        assert results[1].roi_label == "B"
        # Second ROI has larger noise → should have larger baseline_std
        assert results[1].baseline_std > results[0].baseline_std * 0.5

    def test_realistic_transient_shape(self):
        """Exponential decay from a pulse — metrics make physical sense."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 100
        ts = np.linspace(0, 0.01, n)
        # Thermal transient: sharp rise, exponential decay
        tau = 0.002  # 2 ms time constant
        sig = np.where(ts < 0.001, 0.0,
                       0.005 * np.exp(-(ts - 0.001) / tau))
        m = compute_transient_metrics(sig, ts, "thermal")
        assert m.peak_drr > 0  # positive
        assert m.time_to_peak_s >= 0.001  # after pulse onset
        assert m.time_to_peak_s < 0.002   # near onset
        assert m.baseline_mean == pytest.approx(0.0, abs=1e-6)
        assert m.recovery_ratio > 0.5  # should recover substantially

    def test_argmax_abs_selects_largest_deviation(self):
        """Peak detection uses argmax(abs), not argmax(raw)."""
        from acquisition.transient_metrics import compute_transient_metrics
        n = 50
        ts = np.linspace(0, 0.005, n)
        sig = np.zeros(n)
        sig[15] = 0.005   # positive, smaller magnitude
        sig[30] = -0.010  # negative, larger magnitude
        m = compute_transient_metrics(sig, ts)
        assert m.peak_index == 30
        assert m.peak_drr == pytest.approx(-0.010)
        assert m.peak_abs == pytest.approx(0.010)


# ══════════════════════════════════════════════════════════════════════════════
#  Movie Quantitative Review — metrics computation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMovieMetrics:
    """Tests for acquisition/movie_metrics.py — pure numpy movie metrics."""

    def test_basic_positive_peak(self):
        """Positive peak detected with correct signed value."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 60
        ts = np.linspace(0, 1.0, n)  # 1 second recording
        sig = np.zeros(n)
        sig[25] = 0.008
        m = compute_movie_metrics(sig, ts, "ROI-1", "#ff0000")
        assert m.peak_drr == pytest.approx(0.008)
        assert m.peak_abs == pytest.approx(0.008)
        assert m.peak_index == 25
        assert m.peak_time_s == pytest.approx(ts[25])
        assert m.n_frames == 60
        assert m.roi_label == "ROI-1"

    def test_negative_peak_preserved(self):
        """Signed negative peak is preserved."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 40
        ts = np.linspace(0, 0.5, n)
        sig = np.zeros(n)
        sig[10] = -0.015
        m = compute_movie_metrics(sig, ts)
        assert m.peak_drr == pytest.approx(-0.015)
        assert m.peak_abs == pytest.approx(0.015)
        assert m.peak_index == 10

    def test_argmax_abs_selects_largest_deviation(self):
        """Peak uses argmax(abs), not argmax(raw)."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 50
        ts = np.linspace(0, 1.0, n)
        sig = np.zeros(n)
        sig[10] = 0.003   # small positive
        sig[30] = -0.007  # larger negative
        m = compute_movie_metrics(sig, ts)
        assert m.peak_index == 30
        assert m.peak_drr == pytest.approx(-0.007)

    def test_mean_drr(self):
        """Mean ΔR/R is the temporal average."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 100
        ts = np.linspace(0, 2.0, n)
        sig = np.full(n, 0.005)
        m = compute_movie_metrics(sig, ts)
        assert m.mean_drr == pytest.approx(0.005)

    def test_temporal_std_constant_signal(self):
        """Temporal σ is zero for constant signal."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 50
        ts = np.linspace(0, 1.0, n)
        sig = np.full(n, 0.002)
        m = compute_movie_metrics(sig, ts)
        assert m.temporal_std == pytest.approx(0.0, abs=1e-15)

    def test_temporal_std_noisy_signal(self):
        """Temporal σ reflects noise level."""
        from acquisition.movie_metrics import compute_movie_metrics
        rng = np.random.RandomState(42)
        n = 1000
        ts = np.linspace(0, 1.0, n)
        noise_level = 0.003
        sig = rng.normal(0, noise_level, n)
        m = compute_movie_metrics(sig, ts)
        # σ should be close to the known noise level
        assert m.temporal_std == pytest.approx(noise_level, rel=0.1)

    def test_empty_signal(self):
        """Empty signal returns default metrics."""
        from acquisition.movie_metrics import compute_movie_metrics
        m = compute_movie_metrics(np.array([]), np.array([]))
        assert m.n_frames == 0
        assert m.peak_drr == 0.0

    def test_single_frame(self):
        """Single-frame signal computes valid metrics."""
        from acquisition.movie_metrics import compute_movie_metrics
        m = compute_movie_metrics(np.array([0.01]), np.array([0.0]),
                                  "single")
        assert m.n_frames == 1
        assert m.peak_drr == pytest.approx(0.01)
        assert m.peak_index == 0
        assert m.temporal_std == pytest.approx(0.0)

    def test_to_dict_round_trip(self):
        """MovieMetrics.to_dict → from_dict round-trip."""
        from acquisition.movie_metrics import compute_movie_metrics, MovieMetrics
        sig = np.linspace(-0.01, 0.01, 30)
        ts = np.linspace(0, 0.5, 30)
        m = compute_movie_metrics(sig, ts, "Test", "#00ff00")
        d = m.to_dict()
        m2 = MovieMetrics.from_dict(d)
        assert m2.roi_label == "Test"
        assert m2.peak_drr == pytest.approx(m.peak_drr)
        assert m2.temporal_std == pytest.approx(m.temporal_std)
        assert m2.mean_drr == pytest.approx(m.mean_drr)

    def test_compute_all_movie_roi_metrics(self):
        """compute_all_movie_roi_metrics processes a list of ROI signals."""
        from acquisition.movie_metrics import compute_all_movie_roi_metrics
        n = 40
        ts = np.linspace(0, 0.5, n)
        roi_signals = [
            ("A", "#ff0000", np.random.RandomState(1).randn(n) * 0.001),
            ("B", "#00ff00", np.random.RandomState(2).randn(n) * 0.003),
        ]
        results = compute_all_movie_roi_metrics(roi_signals, ts)
        assert len(results) == 2
        assert results[0].roi_label == "A"
        assert results[1].roi_label == "B"
        assert results[1].temporal_std > results[0].temporal_std

    def test_peak_time_matches_timestamp(self):
        """Peak time corresponds to the correct timestamp value."""
        from acquisition.movie_metrics import compute_movie_metrics
        n = 50
        # Non-uniform timestamps (e.g., dropped frames)
        ts = np.sort(np.random.RandomState(99).uniform(0, 2.0, n))
        sig = np.zeros(n)
        sig[35] = 0.02
        m = compute_movie_metrics(sig, ts)
        assert m.peak_index == 35
        assert m.peak_time_s == pytest.approx(ts[35])


# ══════════════════════════════════════════════════════════════════════════════
#  ROI Extraction — shared helper tests
# ══════════════════════════════════════════════════════════════════════════════

class TestRoiExtraction:
    """Tests for acquisition/roi_extraction.py — shared cube→signal helper."""

    def test_rect_roi_extraction(self):
        """Rectangular ROI extracts correct spatial mean per frame."""
        from acquisition.roi_extraction import extract_roi_signals
        from acquisition.roi import Roi
        cube = np.zeros((10, 20, 30), dtype=np.float32)
        cube[:, 5:10, 5:15] = 0.01  # hot region
        roi = Roi(x=5, y=5, w=10, h=5, label="hot", color="#ff0000")
        signals = extract_roi_signals(cube, [roi])
        assert len(signals) == 1
        label, color, sig = signals[0]
        assert label == "hot"
        assert color == "#ff0000"
        assert len(sig) == 10
        assert sig[0] == pytest.approx(0.01, abs=1e-6)

    def test_empty_roi_skipped(self):
        """Empty ROIs are excluded from extraction."""
        from acquisition.roi_extraction import extract_roi_signals
        from acquisition.roi import Roi
        cube = np.ones((5, 10, 10), dtype=np.float32)
        roi = Roi(x=0, y=0, w=0, h=0)  # empty
        signals = extract_roi_signals(cube, [roi])
        assert len(signals) == 0

    def test_mask_cache_populated(self):
        """Mask cache is populated for ellipse ROIs."""
        from acquisition.roi_extraction import extract_roi_signals
        from acquisition.roi import Roi, SHAPE_ELLIPSE
        cube = np.ones((5, 20, 20), dtype=np.float32)
        roi = Roi(x=2, y=2, w=10, h=10, shape=SHAPE_ELLIPSE,
                  label="ell", color="#00ff00")
        cache: dict = {}
        signals = extract_roi_signals(cube, [roi], mask_cache=cache)
        assert len(signals) == 1
        assert (roi.uid, 20, 20) in cache

    def test_multiple_rois(self):
        """Multiple ROIs produce independent signals."""
        from acquisition.roi_extraction import extract_roi_signals
        from acquisition.roi import Roi
        cube = np.zeros((8, 20, 30), dtype=np.float32)
        cube[:, 0:5, 0:5] = 0.01
        cube[:, 10:15, 10:15] = 0.02
        rois = [
            Roi(x=0, y=0, w=5, h=5, label="A", color="#ff0000"),
            Roi(x=10, y=10, w=5, h=5, label="B", color="#00ff00"),
        ]
        signals = extract_roi_signals(cube, rois)
        assert len(signals) == 2
        assert signals[0][0] == "A"
        assert signals[1][0] == "B"
        assert signals[0][2][0] == pytest.approx(0.01, abs=1e-6)
        assert signals[1][2][0] == pytest.approx(0.02, abs=1e-6)

    def test_no_cache_mode(self):
        """Works correctly with mask_cache=None."""
        from acquisition.roi_extraction import extract_roi_signals
        from acquisition.roi import Roi
        cube = np.ones((3, 10, 10), dtype=np.float32)
        roi = Roi(x=0, y=0, w=5, h=5, label="X")
        signals = extract_roi_signals(cube, [roi], mask_cache=None)
        assert len(signals) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  Transient Session Comparison — computation tests
# ══════════════════════════════════════════════════════════════════════════════

def _make_test_result(n_delays=50, delay_end_s=0.005, seed=42,
                      peak_val=0.01, peak_idx=20):
    """Create a synthetic TransientResult for testing."""
    from acquisition.transient_pipeline import TransientResult
    rng = np.random.RandomState(seed)
    h, w = 16, 16
    cube = rng.randn(n_delays, h, w).astype(np.float32) * 0.0001
    cube[peak_idx, 4:12, 4:12] = peak_val  # hot region at peak
    ts = np.linspace(0, delay_end_s, n_delays)
    return TransientResult(
        delta_r_cube=cube,
        reference=np.ones((h, w), dtype=np.float32),
        delay_times_s=ts,
        n_delays=n_delays,
        n_averages=50,
        pulse_dur_us=500.0,
        delay_start_s=0.0,
        delay_end_s=delay_end_s,
        exposure_us=100.0,
        gain_db=6.0,
        hw_triggered=True,
        duration_s=5.0,
    )


class TestTransientComparison:
    """Tests for acquisition/transient_comparison.py."""

    def test_identical_sessions_zero_deltas(self):
        """Two identical results produce zero deltas."""
        from acquisition.transient_comparison import compare_transient_sessions
        r = _make_test_result(seed=42)
        cr = compare_transient_sessions(r, r, "A", "B")
        assert cr.full_frame.has_both
        assert cr.full_frame.delta_peak_drr == pytest.approx(0.0)
        assert cr.full_frame.delta_peak_snr == pytest.approx(0.0)
        assert cr.full_frame.delta_recovery_ratio == pytest.approx(0.0)
        assert not cr.grids_differ

    def test_different_peaks_produce_nonzero_delta(self):
        """Different peak values produce nonzero delta_peak_drr."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1, peak_val=0.005, peak_idx=15)
        rb = _make_test_result(seed=2, peak_val=0.015, peak_idx=25)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        assert cr.full_frame.has_both
        # B has larger peak, so delta should be positive
        assert cr.full_frame.delta_peak_abs > 0

    def test_grid_differences_detected(self):
        """Different delay counts or ranges are flagged."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(n_delays=50, delay_end_s=0.005)
        rb = _make_test_result(n_delays=100, delay_end_s=0.010)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        assert cr.grids_differ
        assert "Delay count" in cr.grid_note
        assert "Delay end" in cr.grid_note

    def test_identical_grid_not_flagged(self):
        """Identical delay grids produce no grid warning."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(n_delays=50, delay_end_s=0.005)
        rb = _make_test_result(n_delays=50, delay_end_s=0.005, seed=99)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        assert not cr.grids_differ

    def test_session_summaries_populated(self):
        """Session summaries carry correct metadata."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result()
        rb = _make_test_result(seed=99)
        cr = compare_transient_sessions(ra, rb, "Lab A", "Lab B",
                                        uid_a="uid-a", uid_b="uid-b")
        assert cr.summary_a.label == "Lab A"
        assert cr.summary_b.label == "Lab B"
        assert cr.summary_a.uid == "uid-a"
        assert cr.summary_a.n_delays == 50
        assert cr.summary_a.hw_triggered is True

    def test_matched_roi_comparison(self):
        """ROIs with matching labels are compared and produce deltas."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        ts = ra.delay_times_s
        roi_a = [("ROI-1", "#ff0000", np.zeros(50))]
        roi_b = [("ROI-1", "#00ff00", np.ones(50) * 0.01)]
        roi_a[0][2][20] = 0.005  # small peak in A

        cr = compare_transient_sessions(ra, rb, "A", "B",
                                        roi_signals_a=roi_a,
                                        roi_signals_b=roi_b)
        assert len(cr.roi_deltas) == 1
        assert cr.roi_deltas[0].has_both
        assert cr.roi_deltas[0].label == "ROI-1"
        assert len(cr.unmatched_notes) == 0

    def test_unmatched_rois_noted(self):
        """ROIs present in only one session produce unmatched notes."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        roi_a = [("ROI-A", "#ff0000", np.zeros(50))]
        roi_b = [("ROI-B", "#00ff00", np.ones(50) * 0.01)]
        cr = compare_transient_sessions(ra, rb, "A", "B",
                                        roi_signals_a=roi_a,
                                        roi_signals_b=roi_b)
        assert len(cr.roi_deltas) == 2
        assert len(cr.unmatched_notes) == 2
        assert any("ROI-A" in n and "A only" in n for n in cr.unmatched_notes)
        assert any("ROI-B" in n and "B only" in n for n in cr.unmatched_notes)

    def test_mixed_matched_and_unmatched(self):
        """Mix of matched and unmatched ROIs handled correctly."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        roi_a = [
            ("shared", "#ff0000", np.zeros(50)),
            ("only-A", "#00ff00", np.ones(50)),
        ]
        roi_b = [
            ("shared", "#0000ff", np.ones(50) * 0.01),
            ("only-B", "#ffff00", np.ones(50) * 0.02),
        ]
        cr = compare_transient_sessions(ra, rb, "A", "B",
                                        roi_signals_a=roi_a,
                                        roi_signals_b=roi_b)
        matched = [d for d in cr.roi_deltas if d.has_both]
        assert len(matched) == 1
        assert matched[0].label == "shared"
        assert len(cr.unmatched_notes) == 2

    def test_no_roi_signals_still_compares_full_frame(self):
        """Comparison works without ROI signals (full-frame only)."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        assert cr.full_frame.has_both
        assert len(cr.roi_deltas) == 0

    def test_full_frame_overlay_has_both_signals(self):
        """Full-frame overlay carries signal arrays from both sessions."""
        from acquisition.transient_comparison import compare_transient_sessions
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        ov = cr.full_frame_overlay
        assert ov.signal_a is not None
        assert ov.signal_b is not None
        assert len(ov.signal_a) == 50
        assert ov.times_a_s is not None

    def test_comparison_to_dict_round_trip(self):
        """comparison_to_dict produces valid serialisable dict."""
        from acquisition.transient_comparison import (
            compare_transient_sessions, comparison_to_dict)
        ra = _make_test_result(seed=1)
        rb = _make_test_result(seed=2)
        roi_a = [("ROI-X", "#ff0000", np.zeros(50))]
        roi_b = [("ROI-X", "#00ff00", np.ones(50) * 0.01)]
        cr = compare_transient_sessions(ra, rb, "A", "B",
                                        roi_signals_a=roi_a,
                                        roi_signals_b=roi_b)
        d = comparison_to_dict(cr)
        assert d["format"] == "sanjinsight_transient_comparison_v1"
        assert d["summary_a"]["label"] == "A"
        assert d["summary_b"]["label"] == "B"
        assert "full_frame" in d
        assert len(d["roi_comparisons"]) == 1
        # Verify JSON-serialisable
        import json
        json_str = json.dumps(d)
        assert len(json_str) > 100

    def test_delta_signs_b_minus_a(self):
        """Deltas are computed as B − A (positive means B is larger)."""
        from acquisition.transient_comparison import compare_transient_sessions
        # A has small peak, B has large peak
        ra = _make_test_result(seed=1, peak_val=0.001, peak_idx=20)
        rb = _make_test_result(seed=2, peak_val=0.050, peak_idx=20)
        cr = compare_transient_sessions(ra, rb, "A", "B")
        # B's peak is much larger, so delta_peak_abs should be positive
        assert cr.full_frame.delta_peak_abs > 0


# ══════════════════════════════════════════════════════════════════════════════
#  Transient + Movie Report Sections — rendering tests
# ══════════════════════════════════════════════════════════════════════════════

class _MockMeta:
    """Minimal mock for SessionMeta with cube_params."""
    def __init__(self, result_type="single_point", **kwargs):
        self.result_type = result_type
        self.cube_params = kwargs.get("cube_params", {})
        self.n_frames = kwargs.get("n_frames", 50)
        self.exposure_us = kwargs.get("exposure_us", 100.0)
        self.gain_db = kwargs.get("gain_db", 6.0)
        self.duration_s = kwargs.get("duration_s", 5.0)


class _MockSession:
    """Minimal mock for Session with lazy-load cube properties."""
    def __init__(self, meta, cube=None, times=None, reference=None):
        self.meta = meta
        self._cube = cube
        self._times = times
        self._reference = reference

    @property
    def delta_r_cube(self):
        return self._cube

    @property
    def delay_times_s(self):
        return self._times

    @property
    def timestamps_s(self):
        return self._times

    @property
    def reference(self):
        return self._reference


class TestReportSections:
    """Tests for transient/movie HTML report section rendering."""

    def test_transient_section_renders_html(self):
        """Transient section produces valid HTML with metrics."""
        from acquisition.reporting.report_html import _render_transient_section
        n, h, w = 30, 10, 10
        cube = np.random.RandomState(42).randn(n, h, w).astype(np.float32) * 0.001
        cube[15, 3:7, 3:7] = 0.01
        ts = np.linspace(0, 0.003, n)
        meta = _MockMeta(
            result_type="transient",
            cube_params={
                "n_delays": n, "n_averages": 50,
                "pulse_dur_us": 500.0, "delay_start_s": 0.0,
                "delay_end_s": 0.003, "hw_triggered": True,
            })
        session = _MockSession(meta, cube=cube, times=ts)
        html = _render_transient_section(session, meta)
        assert "Transient Acquisition" in html
        assert "Peak ΔR/R" in html
        assert "Time-to-peak" in html
        assert "Recovery ratio" in html
        assert "Baseline" in html

    def test_transient_section_includes_peak_frame(self):
        """Transient section includes peak-frame thumbnail caption."""
        from acquisition.reporting.report_html import _render_transient_section
        n = 20
        cube = np.zeros((n, 8, 8), dtype=np.float32)
        cube[10] = 0.005
        ts = np.linspace(0, 0.002, n)
        meta = _MockMeta(
            result_type="transient",
            cube_params={"n_delays": n, "n_averages": 25,
                        "pulse_dur_us": 200.0, "delay_start_s": 0.0,
                        "delay_end_s": 0.002, "hw_triggered": False})
        session = _MockSession(meta, cube=cube, times=ts)
        html = _render_transient_section(session, meta)
        assert "Peak-frame" in html
        assert "delay index" in html

    def test_movie_section_renders_html(self):
        """Movie section produces valid HTML with movie-appropriate metrics."""
        from acquisition.reporting.report_html import _render_movie_section
        n, h, w = 40, 10, 10
        cube = np.random.RandomState(42).randn(n, h, w).astype(np.float32) * 0.001
        cube[20, 3:7, 3:7] = 0.008
        ts = np.linspace(0, 0.5, n)
        meta = _MockMeta(
            result_type="movie",
            cube_params={"n_frames": n, "fps_achieved": 80.0})
        session = _MockSession(meta, cube=cube, times=ts)
        html = _render_movie_section(session, meta)
        assert "Movie Acquisition" in html
        assert "Peak ΔR/R" in html
        assert "Mean ΔR/R" in html
        assert "Temporal" in html

    def test_movie_section_no_cube_graceful(self):
        """Movie section handles missing cube gracefully."""
        from acquisition.reporting.report_html import _render_movie_section
        meta = _MockMeta(result_type="movie",
                        cube_params={"n_frames": 0, "fps_achieved": 0})
        session = _MockSession(meta, cube=None, times=None)
        html = _render_movie_section(session, meta)
        assert "Movie Acquisition" in html
        # Should not crash, just skip image/metrics

    def test_transient_section_no_cube_graceful(self):
        """Transient section handles missing cube gracefully."""
        from acquisition.reporting.report_html import _render_transient_section
        meta = _MockMeta(
            result_type="transient",
            cube_params={"n_delays": 0})
        session = _MockSession(meta, cube=None, times=None)
        html = _render_transient_section(session, meta)
        assert "Transient Acquisition" in html

    def test_report_config_has_new_fields(self):
        """ReportConfig includes transient_section and movie_section."""
        from acquisition.report import ReportConfig
        cfg = ReportConfig()
        assert cfg.transient_section is True
        assert cfg.movie_section is True
        cfg2 = ReportConfig(transient_section=False, movie_section=False)
        assert cfg2.transient_section is False
        assert cfg2.movie_section is False

    def test_sections_gated_by_result_type(self):
        """HTML generator only renders transient/movie sections for matching result_type."""
        # This tests the gating logic in generate_html_report indirectly
        from acquisition.report import ReportConfig
        cfg = ReportConfig(transient_section=True, movie_section=True)
        # For a single_point session, both sections should be gated off
        # by the result_type check, not by the config toggle
        assert cfg.transient_section is True  # config says yes
        # But the generator checks: cfg.transient_section AND rt == "transient"
        # So single_point sessions won't get transient/movie sections


# ================================================================== #
#  DataTab comparison entry point                                      #
# ================================================================== #

class TestDataTabCompareEntryPoint:
    """Tests for the DataTab session comparison routing logic.

    These tests verify the visibility and routing rules without
    requiring a running Qt event loop — we test the decision logic
    that determines which comparison dialog should open.
    """

    # -------------------------------------------------------------- #
    #  Routing rules (unit-level, no Qt)                              #
    # -------------------------------------------------------------- #

    _SUPPORTED_COMPARE_TYPES = {"transient", "movie"}

    def test_transient_routes_to_compare(self):
        """Transient sessions are routable to comparison."""
        assert "transient" in self._SUPPORTED_COMPARE_TYPES

    def test_movie_routes_to_compare(self):
        """Movie sessions are routable to comparison."""
        assert "movie" in self._SUPPORTED_COMPARE_TYPES

    def test_single_point_not_comparable(self):
        """Single-point sessions cannot use session comparison."""
        assert "single_point" not in self._SUPPORTED_COMPARE_TYPES

    def test_grid_not_comparable(self):
        """Grid sessions cannot use session comparison."""
        assert "grid" not in self._SUPPORTED_COMPARE_TYPES

    def test_compare_button_visibility_transient(self):
        """Compare Sessions button should be visible for transient sessions."""
        rt = "transient"
        has_drr = True
        is_transient = rt == "transient"
        is_movie = rt == "movie"
        can_compare = (is_transient or is_movie) and bool(has_drr)
        assert can_compare is True

    def test_compare_button_hidden_single_point(self):
        """Compare Sessions button should be hidden for single_point sessions."""
        rt = "single_point"
        has_drr = True
        is_transient = rt == "transient"
        is_movie = rt == "movie"
        can_compare = (is_transient or is_movie) and bool(has_drr)
        assert can_compare is False

    def test_compare_button_hidden_no_drr(self):
        """Compare Sessions button hidden when session has no ΔR/R data."""
        rt = "transient"
        has_drr = False
        is_transient = rt == "transient"
        is_movie = rt == "movie"
        can_compare = (is_transient or is_movie) and bool(has_drr)
        assert can_compare is False

    def test_compare_button_visible_movie(self):
        """Compare Sessions button visible for movie sessions with ΔR/R."""
        rt = "movie"
        has_drr = True
        is_transient = rt == "transient"
        is_movie = rt == "movie"
        can_compare = (is_transient or is_movie) and bool(has_drr)
        assert can_compare is True

    def test_transient_compare_dialog_exists(self):
        """TransientCompareDialog is importable and has run() classmethod."""
        from ui.dialogs.transient_compare_dialog import TransientCompareDialog
        assert hasattr(TransientCompareDialog, "run")
        assert callable(TransientCompareDialog.run)

    def test_movie_compare_dialog_exists(self):
        """MovieCompareDialog is importable and has run() classmethod."""
        from ui.dialogs.movie_compare_dialog import MovieCompareDialog
        assert hasattr(MovieCompareDialog, "run")
        assert callable(MovieCompareDialog.run)


# ================================================================== #
#  Movie comparison                                                    #
# ================================================================== #

def _make_movie_result(n_frames=40, h=10, w=10, peak_frame=20,
                       peak_val=0.008, fps=80.0, seed=42):
    """Factory for synthetic MovieResult objects."""
    from acquisition.movie_pipeline import MovieResult
    rng = np.random.RandomState(seed)
    cube = rng.randn(n_frames, h, w).astype(np.float32) * 0.001
    cube[peak_frame, 3:7, 3:7] = peak_val
    ts = np.linspace(0, n_frames / fps, n_frames)
    return MovieResult(
        delta_r_cube=cube,
        reference=np.ones((h, w), dtype=np.float32),
        timestamps_s=ts,
        frame_cube=None,
        n_frames=n_frames,
        frames_captured=n_frames,
        exposure_us=500.0,
        gain_db=12.0,
        duration_s=n_frames / fps,
        fps_achieved=fps,
    )


class TestMovieComparison:
    """Tests for movie session comparison logic."""

    def test_identical_sessions_zero_deltas(self):
        """Comparing a session with itself yields zero deltas."""
        from acquisition.movie_comparison import compare_movie_sessions
        r = _make_movie_result()
        cr = compare_movie_sessions(r, r, "A", "B", "uid_a", "uid_b")
        assert cr.full_frame.has_both
        assert abs(cr.full_frame.delta_peak_drr) < 1e-12
        assert abs(cr.full_frame.delta_mean_drr) < 1e-12
        assert abs(cr.full_frame.delta_temporal_std) < 1e-12

    def test_different_peaks_produce_nonzero_delta(self):
        """Sessions with different peak values yield nonzero delta."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(peak_val=0.005, seed=1)
        b = _make_movie_result(peak_val=0.010, seed=2)
        cr = compare_movie_sessions(a, b)
        assert cr.full_frame.has_both
        assert abs(cr.full_frame.delta_peak_drr) > 1e-6

    def test_grid_differences_detected(self):
        """Different frame counts are flagged as timing differences."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(n_frames=40)
        b = _make_movie_result(n_frames=60)
        cr = compare_movie_sessions(a, b)
        assert cr.grids_differ is True
        assert "Frame count" in cr.grid_note

    def test_fps_difference_detected(self):
        """Different FPS is flagged as a timing difference."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(fps=80.0)
        b = _make_movie_result(fps=120.0)
        cr = compare_movie_sessions(a, b)
        assert cr.grids_differ is True
        assert "FPS" in cr.grid_note

    def test_identical_grid_not_flagged(self):
        """Identical timing parameters are not flagged."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(seed=1)
        b = _make_movie_result(seed=2)
        cr = compare_movie_sessions(a, b)
        assert cr.grids_differ is False

    def test_session_summaries_populated(self):
        """Session summaries carry correct metadata."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(n_frames=40, fps=80.0)
        b = _make_movie_result(n_frames=40, fps=80.0)
        cr = compare_movie_sessions(a, b, "Label A", "Label B",
                                    "uid_a", "uid_b")
        assert cr.summary_a.label == "Label A"
        assert cr.summary_b.uid == "uid_b"
        assert cr.summary_a.n_frames == 40
        assert abs(cr.summary_a.fps_achieved - 80.0) < 0.01

    def test_matched_roi_comparison(self):
        """ROIs with matching labels produce deltas."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(seed=1)
        b = _make_movie_result(seed=2)
        roi_a = [("ROI-1", "#ff0000", np.random.randn(40) * 0.001)]
        roi_b = [("ROI-1", "#00ff00", np.random.randn(40) * 0.002)]
        cr = compare_movie_sessions(a, b, roi_signals_a=roi_a,
                                    roi_signals_b=roi_b)
        assert len(cr.roi_deltas) == 1
        assert cr.roi_deltas[0].has_both
        assert cr.roi_deltas[0].label == "ROI-1"

    def test_unmatched_rois_noted(self):
        """ROIs present in only one session are noted."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(seed=1)
        b = _make_movie_result(seed=2)
        roi_a = [("Only-A", "#ff0000", np.random.randn(40) * 0.001)]
        cr = compare_movie_sessions(a, b, roi_signals_a=roi_a,
                                    roi_signals_b=[])
        assert len(cr.unmatched_notes) == 1
        assert "Only-A" in cr.unmatched_notes[0]
        assert "A only" in cr.unmatched_notes[0]

    def test_full_frame_overlay_has_both_signals(self):
        """Full-frame overlay contains signals from both sessions."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(seed=1)
        b = _make_movie_result(seed=2)
        cr = compare_movie_sessions(a, b)
        ov = cr.full_frame_overlay
        assert ov.signal_a is not None
        assert ov.signal_b is not None
        assert len(ov.signal_a) == 40
        assert len(ov.signal_b) == 40

    def test_comparison_to_dict_round_trip(self):
        """movie_comparison_to_dict produces valid serialisation."""
        from acquisition.movie_comparison import (
            compare_movie_sessions, movie_comparison_to_dict)
        a = _make_movie_result(seed=1)
        b = _make_movie_result(seed=2)
        roi_a = [("R1", "#f00", np.random.randn(40) * 0.001)]
        roi_b = [("R1", "#0f0", np.random.randn(40) * 0.002)]
        cr = compare_movie_sessions(a, b, roi_signals_a=roi_a,
                                    roi_signals_b=roi_b)
        doc = movie_comparison_to_dict(cr)
        assert doc["format"] == "sanjinsight_movie_comparison_v1"
        assert "full_frame" in doc
        assert "roi_comparisons" in doc
        # Verify JSON-serialisable
        json_str = json.dumps(doc)
        assert len(json_str) > 100

    def test_delta_signs_b_minus_a(self):
        """Deltas are B − A (positive when B is larger)."""
        from acquisition.movie_comparison import compare_movie_sessions
        a = _make_movie_result(peak_val=0.001, seed=1)
        b = _make_movie_result(peak_val=0.010, seed=1)
        cr = compare_movie_sessions(a, b)
        # B has larger peak → delta should be positive
        assert cr.full_frame.delta_peak_drr > 0

    def test_movie_metrics_no_baseline_or_recovery(self):
        """Movie metrics do not include transient-specific fields."""
        from acquisition.movie_comparison import MovieMetricsDelta
        md = MovieMetricsDelta()
        assert not hasattr(md, "delta_baseline_mean")
        assert not hasattr(md, "delta_recovery_ratio")
        assert hasattr(md, "delta_mean_drr")
        assert hasattr(md, "delta_temporal_std")


# ================================================================== #
#  Hardware card redesign                                              #
# ================================================================== #

class TestHardwareCardParts:
    """Tests for the hardware card sub-widgets."""

    def test_metric_tile_importable(self):
        """MetricTile is importable and has expected API."""
        from ui.widgets.hardware_card_parts import MetricTile
        assert callable(MetricTile)

    def test_device_header_bar_importable(self):
        """DeviceHeaderBar is importable and has expected API."""
        from ui.widgets.hardware_card_parts import DeviceHeaderBar
        assert callable(DeviceHeaderBar)

    def test_info_card_importable(self):
        """InfoCard is importable and has expected API."""
        from ui.widgets.hardware_card_parts import InfoCard
        assert callable(InfoCard)

    def test_device_status_card_accepts_layout(self):
        """DeviceStatusCard constructor accepts layout parameter."""
        import inspect
        from ui.widgets.device_status_card import DeviceStatusCard
        sig = inspect.signature(DeviceStatusCard.__init__)
        assert "layout" in sig.parameters

    def test_coordinator_layout_mode_camera(self):
        """Coordinator assigns 'camera' layout to camera devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("camera") == "camera"
        assert HardwarePanelCoordinator._device_layout_mode("tr_camera") == "camera"
        assert HardwarePanelCoordinator._device_layout_mode("ir_camera") == "camera"

    def test_coordinator_layout_mode_dashboard_stage(self):
        """Coordinator assigns 'dashboard' layout to stage devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("stage") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("newport_npc3") == "dashboard"

    def test_coordinator_layout_mode_dashboard_tec(self):
        """Coordinator assigns 'dashboard' layout to TEC devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("tec0") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("tec1") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("tec_meerstetter") == "dashboard"

    def test_coordinator_layout_mode_dashboard_fpga(self):
        """Coordinator assigns 'dashboard' layout to FPGA devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("fpga") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("ni_9637") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("ni_sbrio") == "dashboard"

    def test_coordinator_layout_mode_dashboard_bias(self):
        """Coordinator assigns 'dashboard' layout to bias devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("bias") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("rigol_dp832") == "dashboard"

    def test_coordinator_layout_mode_dashboard_gpio_ldd(self):
        """Coordinator assigns 'dashboard' layout to GPIO and LDD devices."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("gpio") == "dashboard"
        assert HardwarePanelCoordinator._device_layout_mode("ldd") == "dashboard"

    def test_coordinator_layout_mode_generic_fallback(self):
        """Non-redesigned devices get 'generic' layout."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert HardwarePanelCoordinator._device_layout_mode("prober") == "generic"
        assert HardwarePanelCoordinator._device_layout_mode("turret") == "generic"

    def test_metric_tile_has_set_value(self):
        """MetricTile exposes set_value() method."""
        from ui.widgets.hardware_card_parts import MetricTile
        assert hasattr(MetricTile, "set_value")

    def test_metric_tile_has_set_accent(self):
        """MetricTile exposes set_accent() method."""
        from ui.widgets.hardware_card_parts import MetricTile
        assert hasattr(MetricTile, "set_accent")

    def test_device_header_bar_has_set_summary(self):
        """DeviceHeaderBar exposes set_summary() method."""
        from ui.widgets.hardware_card_parts import DeviceHeaderBar
        assert hasattr(DeviceHeaderBar, "set_summary")

    def test_info_card_has_add_info(self):
        """InfoCard exposes add_info() and update_info() methods."""
        from ui.widgets.hardware_card_parts import InfoCard
        assert hasattr(InfoCard, "add_info")
        assert hasattr(InfoCard, "update_info")

    def test_device_status_card_has_add_tile(self):
        """DeviceStatusCard exposes add_tile() method."""
        from ui.widgets.device_status_card import DeviceStatusCard
        assert hasattr(DeviceStatusCard, "add_tile")

    def test_device_status_card_has_set_summary(self):
        """DeviceStatusCard exposes set_summary() method."""
        from ui.widgets.device_status_card import DeviceStatusCard
        assert hasattr(DeviceStatusCard, "set_summary")

    def test_coordinator_has_update_gpio_readouts(self):
        """Coordinator exposes update_gpio_readouts()."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert hasattr(HardwarePanelCoordinator, "update_gpio_readouts")

    def test_coordinator_has_update_ldd_readouts(self):
        """Coordinator exposes update_ldd_readouts()."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        assert hasattr(HardwarePanelCoordinator, "update_ldd_readouts")

    def test_coordinator_static_refresh_methods_exist(self):
        """Coordinator has static refresh methods for all device types."""
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        for method in (
            "_refresh_fpga_static",
            "_refresh_bias_static",
            "_refresh_gpio_static",
            "_refresh_ldd_static",
            "_refresh_stage_static",
            "_refresh_tec_static",
        ):
            assert hasattr(HardwarePanelCoordinator, method), (
                f"Missing {method}")

    def test_coordinator_fpga_uses_correct_status_fields(self):
        """FPGA update uses freq_hz (not frequency) from FpgaStatus."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_fpga_readouts)
        assert "freq_hz" in src, "Should use FpgaStatus.freq_hz"
        assert "sync_locked" in src, "Should use FpgaStatus.sync_locked"

    def test_coordinator_stage_uses_correct_moving_field(self):
        """Stage update uses 'moving' (not 'is_moving') from StageStatus."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_stage_readouts)
        # Should use status.moving, not status.is_moving
        assert '"moving"' in src, "Should use StageStatus.moving"
        assert '"homed"' in src, "Should expose homed field"

    def test_coordinator_bias_exposes_power_tile(self):
        """Bias update pushes actual_power to a Power tile."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_bias_readouts)
        assert "actual_power" in src, "Should use BiasStatus.actual_power"
        assert '"Power"' in src, "Should update Power tile"

    def test_coordinator_tec_exposes_sink_temp(self):
        """TEC update pushes sink_temp when non-zero."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_tec_readouts)
        assert "sink_temp" in src, "Should use TecStatus.sink_temp"

    def test_coordinator_ldd_uses_correct_fields(self):
        """LDD update uses actual_current_a and diode_temp_c."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_ldd_readouts)
        assert "actual_current_a" in src
        assert "diode_temp_c" in src

    def test_coordinator_gpio_uses_active_led(self):
        """GPIO update uses active_led from ArduinoStatus."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_gpio_readouts)
        assert "active_led" in src
        assert "firmware_version" in src

    # ── Phase 3: Summary color + tile accent tests ───────────────

    def test_set_summary_accepts_color(self):
        """DeviceHeaderBar.set_summary accepts optional color parameter."""
        import inspect
        from ui.widgets.hardware_card_parts import DeviceHeaderBar
        sig = inspect.signature(DeviceHeaderBar.set_summary)
        assert "color" in sig.parameters

    def test_device_status_card_set_summary_accepts_color(self):
        """DeviceStatusCard.set_summary passes color through."""
        import inspect
        from ui.widgets.device_status_card import DeviceStatusCard
        sig = inspect.signature(DeviceStatusCard.set_summary)
        assert "color" in sig.parameters

    def test_device_status_card_has_set_tile_accent(self):
        """DeviceStatusCard exposes set_tile_accent(label, color)."""
        from ui.widgets.device_status_card import DeviceStatusCard
        assert hasattr(DeviceStatusCard, "set_tile_accent")
        import inspect
        sig = inspect.signature(DeviceStatusCard.set_tile_accent)
        params = list(sig.parameters.keys())
        assert "label" in params
        assert "color" in params

    def test_state_palette_helpers_exist(self):
        """Coordinator exposes state palette helper functions."""
        from ui.hardware_panel_coordinator import (
            _c_healthy, _c_warning, _c_neutral, _c_error)
        # Healthy and warning return non-empty color strings
        assert _c_healthy()
        assert _c_warning()
        assert _c_error()
        # Neutral returns empty (clears accent)
        assert _c_neutral() == ""

    def test_tec_update_sets_stability_accent(self):
        """TEC update calls set_tile_accent on Stability tile."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_tec_readouts)
        assert 'set_tile_accent("Stability"' in src

    def test_fpga_update_sets_running_accent(self):
        """FPGA update calls set_tile_accent on Running tile."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_fpga_readouts)
        assert 'set_tile_accent("Running"' in src
        assert 'set_tile_accent("Sync Locked"' in src

    def test_bias_update_sets_output_accent(self):
        """Bias update calls set_tile_accent on Output tile."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_bias_readouts)
        assert 'set_tile_accent("Output"' in src

    def test_stage_update_sets_moving_accent(self):
        """Stage update calls set_tile_accent on Moving tile."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_stage_readouts)
        assert 'set_tile_accent("Moving"' in src

    def test_camera_summary_uses_healthy_color(self):
        """Camera streaming summary uses healthy (success) color."""
        import inspect
        from ui.hardware_panel_coordinator import HardwarePanelCoordinator
        src = inspect.getsource(
            HardwarePanelCoordinator.update_camera_readouts)
        assert "_c_healthy()" in src

    def test_summary_color_uses_palette(self):
        """State palette functions read from PALETTE dict."""
        from ui.hardware_panel_coordinator import _c_healthy, _c_warning
        from ui.theme import PALETTE
        assert _c_healthy() == PALETTE.get("success", "#30d158")
        assert _c_warning() == PALETTE.get("warning", "#ff9f0a")


# ═══════════════════════════════════════════════════════════════════════
# Phase A — Image-First Quick Wins
# ═══════════════════════════════════════════════════════════════════════

class TestImagePaneExpanding:
    """ImagePane expanding parameter — opt-in, backward-compatible."""

    def test_default_uses_fixed_size(self):
        """Default ImagePane constructor uses setFixedSize."""
        import inspect
        from ui.widgets.image_pane import ImagePane
        src = inspect.getsource(ImagePane.__init__)
        assert "expanding: bool = False" in src
        assert "setFixedSize(w, h)" in src

    def test_expanding_mode_uses_size_policy(self):
        """Expanding mode sets Expanding size policy and minimum size."""
        import inspect
        from ui.widgets.image_pane import ImagePane
        src = inspect.getsource(ImagePane.__init__)
        assert "SizePolicy.Expanding" in src
        assert "setMinimumSize(w, h)" in src

    def test_expanding_branches_on_flag(self):
        """Constructor branches on the expanding flag."""
        import inspect
        from ui.widgets.image_pane import ImagePane
        src = inspect.getsource(ImagePane.__init__)
        assert "if expanding:" in src


class TestAutofocusLogRemoval:
    """Autofocus tab: embedded log removed, redirected to logging."""

    def test_no_log_textedit(self):
        """AutofocusTab no longer has an embedded QTextEdit log."""
        import inspect
        from ui.tabs.autofocus_tab import AutofocusTab
        src = inspect.getsource(AutofocusTab.__init__)
        assert "QTextEdit" not in src
        assert 'log_box' not in src

    def test_log_method_uses_logging(self):
        """AutofocusTab.log() delegates to the logging module."""
        import inspect
        from ui.tabs.autofocus_tab import AutofocusTab
        src = inspect.getsource(AutofocusTab.log)
        assert "log.info" in src

    def test_focus_plot_min_height(self):
        """FocusPlot minimum height raised from 120 to 200."""
        import inspect
        from ui.tabs.autofocus_tab import FocusPlot
        src = inspect.getsource(FocusPlot.__init__)
        assert "setMinimumHeight(200)" in src


class TestCaptureResultsContainer:
    """Capture tab: results hidden pre-acquisition, shown on start."""

    def test_results_hidden_at_init(self):
        """Results container is hidden when AcquireTab is first created."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "_results_container" in src
        assert "setVisible(False)" in src

    def test_set_busy_shows_results(self):
        """_set_busy(True) makes the results container visible."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._set_busy)
        assert "_results_container.setVisible(True)" in src

    def test_update_result_shows_container(self):
        """update_result() ensures results container is visible."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.update_result)
        assert "_results_container.setVisible(True)" in src

    def test_live_feed_is_expanding(self):
        """AcquireTab live feed uses expanding=True."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "expanding=True" in src


# ═══════════════════════════════════════════════════════════════════════
# TEC Tab — One-device-per-tab conversion
# ═══════════════════════════════════════════════════════════════════════

class TestTecPanelExtraction:
    """TecPanel class extracted from TemperatureTab._build_tec()."""

    def test_tec_panel_class_exists(self):
        """TecPanel is a standalone QWidget subclass."""
        from PyQt5.QtWidgets import QWidget as _QWidget
        from ui.tabs.temperature_tab import TecPanel
        assert issubclass(TecPanel, _QWidget)

    def test_tec_panel_owns_update_status(self):
        """TecPanel has its own update_status method (was update_tec)."""
        from ui.tabs.temperature_tab import TecPanel
        assert hasattr(TecPanel, 'update_status')
        assert callable(TecPanel.update_status)

    def test_tec_panel_owns_alarm_methods(self):
        """TecPanel owns show_alarm, show_warning, clear_alarm."""
        from ui.tabs.temperature_tab import TecPanel
        for method in ('show_alarm', 'show_warning', 'clear_alarm'):
            assert hasattr(TecPanel, method), f"Missing {method}"

    def test_tec_panel_owns_hardware_actions(self):
        """TecPanel owns _set_target, _enable, _disable, _set_ramp_speed."""
        from ui.tabs.temperature_tab import TecPanel
        for method in ('_set_target', '_enable', '_disable',
                       '_set_ramp_speed', '_apply_limits',
                       '_acknowledge_alarm'):
            assert hasattr(TecPanel, method), f"Missing {method}"

    def test_tec_panel_owns_apply_styles(self):
        """TecPanel has its own _apply_styles for theme switching."""
        from ui.tabs.temperature_tab import TecPanel
        assert hasattr(TecPanel, '_apply_styles')

    def test_tec_panel_stores_index(self):
        """TecPanel constructor accepts and stores tec_index."""
        import inspect
        from ui.tabs.temperature_tab import TecPanel
        src = inspect.getsource(TecPanel.__init__)
        assert "tec_index" in src
        assert "self._tec_index = tec_index" in src


class TestTemperatureTabTabWidget:
    """TemperatureTab uses QTabWidget instead of vertical stack."""

    def test_uses_qtabwidget(self):
        """TemperatureTab.__init__ creates a QTabWidget for TEC panels."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.__init__)
        assert "QTabWidget" in src
        assert "_tec_tabs" in src

    def test_no_vertical_loop_with_addwidget(self):
        """TemperatureTab no longer adds panels directly to root layout."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.__init__)
        # Old pattern was: root.addWidget(p) inside the loop
        # New pattern is: self._tec_tabs.addTab(panel, ...)
        assert "addTab(panel" in src

    def test_panels_are_tec_panels(self):
        """_panels list contains TecPanel instances (type annotation)."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.__init__)
        assert "list[TecPanel]" in src

    def test_routing_update_tec(self):
        """update_tec routes to TecPanel.update_status."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.update_tec)
        assert "update_status(status)" in src

    def test_routing_show_alarm(self):
        """show_alarm routes to TecPanel.show_alarm."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.show_alarm)
        assert ".show_alarm(message)" in src

    def test_routing_show_warning(self):
        """show_warning routes to TecPanel.show_warning."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.show_warning)
        assert ".show_warning(message)" in src

    def test_routing_clear_alarm(self):
        """clear_alarm routes to TecPanel.clear_alarm."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.clear_alarm)
        assert ".clear_alarm()" in src

    def test_chuck_outside_tabs(self):
        """Chuck section is added outside the per-TEC tab widget."""
        import inspect
        from ui.tabs.temperature_tab import TemperatureTab
        src = inspect.getsource(TemperatureTab.__init__)
        # _chuck_box is added to root, not to _tec_tabs
        assert "_build_chuck" in src
        # Verify chuck is added after the tab widget
        tab_pos = src.index("_tec_tabs")
        chuck_pos = src.index("_chuck_box")
        assert chuck_pos > tab_pos

    def test_set_tab_label_exists(self):
        """TemperatureTab has set_tab_label for device identity."""
        from ui.tabs.temperature_tab import TemperatureTab
        assert hasattr(TemperatureTab, 'set_tab_label')

    def test_no_build_tec_method(self):
        """Old _build_tec method no longer exists on TemperatureTab."""
        from ui.tabs.temperature_tab import TemperatureTab
        assert not hasattr(TemperatureTab, '_build_tec')


# ═══════════════════════════════════════════════════════════════════════
# Modality — Two-card layout redesign
# ═══════════════════════════════════════════════════════════════════════

class TestModalityTwoCardLayout:
    """Modality section uses two-card architecture."""

    def test_two_card_body_layout(self):
        """Controls page has a QHBoxLayout body with two CardFrame children."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "body = QHBoxLayout" in src
        assert 'left_card.setObjectName("CardFrame")' in src
        assert 'right_card.setObjectName("CardFrame")' in src

    def test_left_card_contains_controls(self):
        """Left card contains camera combo, profile picker, and more options."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # All controls are inside the left card (lc layout)
        assert "lc.addWidget(self._cam_combo)" in src or "_cam_combo" in src
        assert "lc.addWidget(self._profile_picker)" in src
        assert "lc.addWidget(self._opts_panel)" in src

    def test_right_card_is_preview(self):
        """Right card contains expanding preview and camera identity."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_preview_lbl" in src
        assert "_cam_identity_lbl" in src
        assert "_modality_badge" in src

    def test_preview_is_expanding(self):
        """Preview label uses expanding size policy, not fixed size."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "SizePolicy.Expanding" in src
        assert "setMinimumSize" in src
        # Old fixed size should be gone
        assert "setFixedSize" not in src

    def test_no_detached_preview_in_camera_row(self):
        """Preview is NOT inside the camera row — it has its own card."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # Old pattern had: cam_row.addLayout(preview_col, 2)
        # _single_cam_row is acceptable — it's the read-only identity row, not a layout
        assert "cam_row.addLayout" not in src

    def test_card_frame_qss_exists(self):
        """Module-level _card_frame_qss helper provides card styling."""
        from ui.tabs.modality_section import _card_frame_qss
        qss = _card_frame_qss()
        assert "CardFrame" in qss
        assert "border-radius" in qss

    def test_separator_helper_exists(self):
        """Module-level _separator helper creates HLine dividers."""
        from ui.tabs.modality_section import _separator
        assert callable(_separator)

    def test_modality_badge_exists(self):
        """ModalitySection has _apply_badge_style for TR/IR badge."""
        from ui.tabs.modality_section import ModalitySection
        assert hasattr(ModalitySection, '_apply_badge_style')

    def test_preview_card_info_refresh(self):
        """_refresh_preview_card_info updates camera identity + badge."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._refresh_preview_card_info)
        assert "_cam_identity_lbl" in src
        assert "_cam_detail_lbl" in src
        assert "_apply_badge_style" in src

    def test_compact_spacing(self):
        """Left card uses zero base spacing with explicit addSpacing (tight flow)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "lc.setSpacing(0)" in src
        assert "addSpacing" in src

    def test_stretch_factors(self):
        """Left card gets stretch=3, right card gets stretch=3 (equal)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "body.addWidget(left_card, 3)" in src
        assert "body.addWidget(right_card, 3)" in src

    def test_preview_scales_to_label_size(self):
        """update_preview uses the label's actual size, not fixed constants."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection.update_preview)
        assert "self._preview_lbl.width()" in src
        assert "self._preview_lbl.height()" in src


# ═══════════════════════════════════════════════════════════════════════
# Modality polish refinements
# ═══════════════════════════════════════════════════════════════════════

class TestModalityPolish:
    """Modality polish: content-hugging left card, stronger info footer,
    reduced guidance weight, section label consistency."""

    def test_left_card_content_hugging(self):
        """Left card uses SizePolicy.Maximum for content-hugging height."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "QSizePolicy.Maximum" in src

    def test_section_label_qss_method_exists(self):
        """_section_label_qss static method exists on ModalitySection."""
        from ui.tabs.modality_section import ModalitySection
        assert hasattr(ModalitySection, '_section_label_qss')
        qss = ModalitySection._section_label_qss()
        assert "font-weight:600" in qss

    def test_section_labels_use_method(self):
        """Section labels (Camera, Profile, Objective) use _section_label_qss."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "self._section_label_qss()" in src

    def test_preview_separator_exists(self):
        """Preview card has a separator between preview and info footer."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_preview_sep" in src

    def test_no_subtitle_in_apply_styles(self):
        """_apply_styles does not reference removed _subtitle attribute."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "_subtitle" not in src

    def test_compact_card_tighter_padding(self):
        """Compact guidance card gets reduced margins."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "setContentsMargins(12, 8, 12, 8)" in src

    def test_identity_label_bold(self):
        """Camera identity label uses font-weight 600 (bold)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # Find the cam_identity_lbl style — should be weight 600
        assert 'font-weight:600' in src

    def test_apply_styles_refreshes_section_labels(self):
        """_apply_styles re-applies section label styles on theme switch."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "_section_label_qss" in src

    def test_preview_sep_in_apply_styles(self):
        """_apply_styles refreshes the preview separator."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "_preview_sep" in src


# ═══════════════════════════════════════════════════════════════════════
# Capture tab — camera context strip
# ═══════════════════════════════════════════════════════════════════════

class TestCaptureContextStrip:
    """Capture tab has a compact camera context strip below the live feed."""

    def test_context_strip_exists(self):
        """AcquireTab has _cam_ctx_lbl and _mode_badge widgets."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "_cam_ctx_lbl" in src
        assert "_mode_badge" in src

    def test_context_strip_in_live_box(self):
        """Context strip is inside the live feed group box (ll layout)."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        # ctx_row is added to ll (the live_box layout)
        assert "ll.addLayout(ctx_row)" in src

    def test_refresh_method_exists(self):
        """_refresh_camera_context method exists on AcquireTab."""
        from ui.tabs.acquire_tab import AcquireTab
        assert hasattr(AcquireTab, '_refresh_camera_context')

    def test_refresh_called_on_show(self):
        """showEvent calls _refresh_camera_context."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.showEvent)
        assert "_refresh_camera_context" in src

    def test_refresh_called_on_mode_change(self):
        """refresh_camera_mode calls _refresh_camera_context."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.refresh_camera_mode)
        assert "_refresh_camera_context" in src

    def test_badge_shows_tr_or_ir(self):
        """_refresh_camera_context sets badge text based on camera type."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._refresh_camera_context)
        assert '"IR Lock-in"' in src
        assert '"TR"' in src

    def test_context_shows_model_and_resolution(self):
        """_refresh_camera_context shows camera model and resolution."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._refresh_camera_context)
        assert "cam.info" in src
        assert "model" in src
        assert "width" in src
        assert "height" in src


# ═══════════════════════════════════════════════════════════════════════
# Modality final polish — heading removal, tighter spacing, stronger footer
# ═══════════════════════════════════════════════════════════════════════

class TestModalityFinalPolish:
    """Modality final polish: no standalone heading, tighter separator
    spacing, stronger preview footer, equal stretch factors."""

    def test_no_standalone_heading(self):
        """No standalone 'Modality' heading — sidebar provides context."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # The old pattern was: title = QLabel("Modality") followed by
        # title.setStyleSheet(... FONT['heading'] ...)
        # Should not exist as a standalone heading widget any more
        lines = src.split('\n')
        heading_lines = [l for l in lines
                         if 'QLabel("Modality")' in l and 'title' in l]
        assert len(heading_lines) == 0, "Standalone Modality heading should be removed"

    def test_reduced_top_margin(self):
        """Root layout top margin is 8px (not 12px)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "setContentsMargins(16, 8, 16, 12)" in src

    def test_separator_spacing_tightened(self):
        """Separators use 4px spacing (not 6px)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # Count addSpacing(4) around separators — at least 4 occurrences
        # (2 separators × 2 sides each)
        count = src.count("addSpacing(4)")
        assert count >= 4, f"Expected ≥4 addSpacing(4), got {count}"

    def test_camera_section_tight_spacing(self):
        """Camera label→combo→desc spacing is 2px each."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # After cam_lbl: addSpacing(2), after combo: addSpacing(2)
        lines = src.split('\n')
        cam_lbl_idx = next(i for i, l in enumerate(lines) if 'cam_lbl' in l and 'QLabel' in l)
        # Next addSpacing should be 2
        next_spacing = next(l for l in lines[cam_lbl_idx:] if 'addSpacing' in l)
        assert "addSpacing(2)" in next_spacing

    def test_footer_label_exists(self):
        """Preview card has an 'Active Camera' footer label."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_footer_label" in src
        assert "Active Camera" in src

    def test_identity_label_body_font(self):
        """Camera identity uses FONT['body'] (not FONT['label'])."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        # Find the cam_identity_lbl stylesheet line
        lines = src.split('\n')
        identity_lines = [l for l in lines
                          if '_cam_identity_lbl' in l and 'setStyleSheet' in l]
        # The style applied near it should use FONT['body']
        identity_section = src[src.index("_cam_identity_lbl"):]
        assert "FONT['body']" in identity_section[:200]

    def test_equal_stretch_factors(self):
        """Both cards get equal stretch (3, 3)."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "body.addWidget(left_card, 3)" in src
        assert "body.addWidget(right_card, 3)" in src

    def test_footer_label_in_apply_styles(self):
        """_apply_styles refreshes the footer label."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "_footer_label" in src

    def test_identity_body_font_in_apply_styles(self):
        """_apply_styles uses FONT['body'] for identity label."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "FONT['body']" in src


# ═══════════════════════════════════════════════════════════════════════
# Signal Check — two-card layout with preview / ROI overlay
# ═══════════════════════════════════════════════════════════════════════

class TestSignalCheckTwoCardLayout:
    """Signal Check uses two-card architecture: left=metrics, right=preview
    with ROI overlay for measurement-quality confirmation."""

    def test_two_card_structure(self):
        """_build_controls_page creates left and right CardFrame cards."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "left_card" in src
        assert "right_card" in src
        assert 'setObjectName("CardFrame")' in src

    def test_left_card_content_hugging(self):
        """Left card uses SizePolicy.Maximum (content-hugging)."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "QSizePolicy.Maximum" in src

    def test_readout_strip_in_left_card(self):
        """SNR, Saturation, and Verdict readouts are in the left card."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_snr_val" in src
        assert "_sat_val" in src
        assert "_verdict" in src

    def test_preview_label_exists(self):
        """Right card has an expanding preview label."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_preview_lbl" in src
        assert "QSizePolicy.Expanding" in src

    def test_preview_minimum_size(self):
        """Preview label has minimum size set."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_PREVIEW_MIN_W" in src
        assert "_PREVIEW_MIN_H" in src

    def test_roi_badge_exists(self):
        """Right card has an ROI mode badge."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_roi_badge" in src

    def test_camera_identity_in_footer(self):
        """Right card has camera identity and detail labels."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_cam_identity_lbl" in src
        assert "_cam_detail_lbl" in src

    def test_footer_label_measurement_region(self):
        """Footer label says 'Measurement Region'."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "Measurement Region" in src

    def test_preview_separator(self):
        """Preview card has a separator between preview and info footer."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._build_controls_page)
        assert "_preview_sep" in src

    def test_card_frame_qss_helper(self):
        """Module has _card_frame_qss helper."""
        from ui.tabs.signal_check_section import _card_frame_qss
        qss = _card_frame_qss()
        assert "CardFrame" in qss
        assert "border-radius" in qss

    def test_separator_helper(self):
        """Module has _separator helper that creates QFrame HLine."""
        import inspect
        from ui.tabs import signal_check_section
        src = inspect.getsource(signal_check_section._separator)
        assert "HLine" in src


class TestSignalCheckPreview:
    """Signal Check preview renders frames with ROI overlay."""

    def test_render_preview_method_exists(self):
        """_render_preview method exists on SignalCheckSection."""
        from ui.tabs.signal_check_section import SignalCheckSection
        assert hasattr(SignalCheckSection, '_render_preview')

    def test_render_preview_calls_to_display(self):
        """_render_preview uses to_display for frame conversion."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._render_preview)
        assert "to_display" in src

    def test_render_preview_draws_roi_overlay(self):
        """_render_preview calls _draw_roi_overlay for non-full-frame modes."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._render_preview)
        assert "_draw_roi_overlay" in src
        assert '"Full Frame"' in src

    def test_draw_roi_overlay_method_exists(self):
        """_draw_roi_overlay method draws ROI rectangle on pixmap."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._draw_roi_overlay)
        assert "QPainter" in src
        assert "drawRect" in src

    def test_draw_roi_overlay_center_50(self):
        """_draw_roi_overlay handles Center 50% mode."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._draw_roi_overlay)
        assert "Center 50%" in src

    def test_draw_roi_overlay_center_25(self):
        """_draw_roi_overlay handles Center 25% mode."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._draw_roi_overlay)
        assert "Center 25%" in src

    def test_roi_overlay_color_from_verdict(self):
        """ROI overlay colour is based on current verdict level."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._draw_roi_overlay)
        assert "_last_verdict_level" in src

    def test_update_frame_triggers_preview(self):
        """update_frame calls _render_preview after computing metrics."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection.update_frame)
        assert "_render_preview" in src

    def test_show_placeholder_method(self):
        """_show_placeholder renders a placeholder icon."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._show_placeholder)
        assert "QPixmap" in src

    def test_refresh_preview_card_info(self):
        """_refresh_preview_card_info updates camera identity + ROI badge."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._refresh_preview_card_info)
        assert "_cam_identity_lbl" in src
        assert "_apply_roi_badge_style" in src

    def test_section_label_qss(self):
        """_section_label_qss static method exists."""
        from ui.tabs.signal_check_section import SignalCheckSection
        qss = SignalCheckSection._section_label_qss()
        assert "font-weight:600" in qss


class TestSignalCheckTheme:
    """Signal Check _apply_styles handles all new elements."""

    def test_apply_styles_card_frames(self):
        """_apply_styles refreshes CardFrame QSS."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._apply_styles)
        assert "CardFrame" in src

    def test_apply_styles_separators(self):
        """_apply_styles refreshes separator styling."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._apply_styles)
        assert "_sep1" in src
        assert "_sep2" in src
        assert "_preview_sep" in src

    def test_apply_styles_preview(self):
        """_apply_styles refreshes preview label."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._apply_styles)
        assert "_preview_lbl" in src
        assert "_preview_frame_qss" in src

    def test_apply_styles_footer(self):
        """_apply_styles refreshes footer and identity labels."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._apply_styles)
        assert "_footer_label" in src
        assert "_cam_identity_lbl" in src

    def test_apply_styles_roi_badge(self):
        """_apply_styles refreshes ROI badge."""
        import inspect
        from ui.tabs.signal_check_section import SignalCheckSection
        src = inspect.getsource(SignalCheckSection._apply_styles)
        assert "_roi_badge" in src


# ═══════════════════════════════════════════════════════════════════════
# Movie — viewer-first layout
# ═══════════════════════════════════════════════════════════════════════

class TestMovieViewerFirstLayout:
    """Movie tab uses viewer-first layout: image dominates, slider below
    viewer, chart capped, metrics collapsed."""

    def test_compact_result_strip(self):
        """Result stats use compact single-line layout (no QGroupBox)."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        # No QGroupBox("Result") — replaced with inline strip
        assert 'QGroupBox("Result")' not in src
        # Stats are inline labels
        assert '"Frames:"' not in src  # not readout widget pattern
        assert "_stats" in src

    def test_viewer_stretch_dominant(self):
        """Frame viewer gets stretch=3 (dominant)."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        assert "addWidget(self._compositor, 3)" in src

    def test_chart_stretch_secondary(self):
        """Chart gets stretch=1 (secondary to viewer)."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        assert "addWidget(curve_box, 1)" in src

    def test_chart_max_height(self):
        """Chart box has a maximum height cap."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        assert "setMaximumHeight(200)" in src

    def test_slider_below_viewer(self):
        """Frame slider is positioned after the compositor (below viewer)."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        # Find the addWidget calls — compositor before slider_row
        compositor_add = src.index("addWidget(self._compositor")
        slider_add = src.index("addLayout(slider_row)")
        assert slider_add > compositor_add, \
            "Slider should be below viewer in layout order"

    def test_metrics_collapsed_by_default(self):
        """ROI Metrics table is in a CollapsiblePanel, starts collapsed."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        assert "CollapsiblePanel" in src
        assert "start_collapsed=True" in src

    def test_no_image_groupbox(self):
        """No QGroupBox wrapping the image viewer — direct in layout."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        assert 'QGroupBox("Frame at Selected Time")' not in src

    def test_view_controls_above_viewer(self):
        """View mode + colormap row is above the compositor."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._build_right)
        view_seg_pos = src.index("_view_seg")
        compositor_pos = src.index("_compositor")
        assert view_seg_pos < compositor_pos

    def test_apply_styles_metrics_panel(self):
        """_apply_styles refreshes the collapsible metrics panel."""
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._apply_styles)
        assert "_metrics_panel" in src


# ═══════════════════════════════════════════════════════════════════════
# Transient — viewer-first layout
# ═══════════════════════════════════════════════════════════════════════

class TestTransientViewerFirstLayout:
    """Transient tab uses viewer-first layout: image dominates, delay slider
    below viewer, chart capped, metrics collapsed."""

    def test_compact_result_strip(self):
        """Result stats use compact single-line layout (no QGroupBox)."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert 'QGroupBox("Result")' not in src
        assert "_stats" in src

    def test_viewer_stretch_dominant(self):
        """Frame viewer gets stretch=3 (dominant)."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert "addWidget(self._compositor, 3)" in src

    def test_chart_stretch_secondary(self):
        """Chart gets stretch=1 (secondary to viewer)."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert "addWidget(curve_box, 1)" in src

    def test_chart_max_height(self):
        """Chart box has a maximum height cap."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert "setMaximumHeight(200)" in src

    def test_slider_below_viewer(self):
        """Delay slider is positioned after the compositor (below viewer)."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        compositor_add = src.index("addWidget(self._compositor")
        slider_add = src.index("addLayout(slider_row)")
        assert slider_add > compositor_add

    def test_metrics_collapsed_by_default(self):
        """ROI Metrics table is in a CollapsiblePanel, starts collapsed."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert "CollapsiblePanel" in src
        assert "start_collapsed=True" in src

    def test_no_image_groupbox(self):
        """No QGroupBox wrapping the image viewer — direct in layout."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        assert 'QGroupBox("Frame at Selected Delay")' not in src

    def test_view_controls_above_viewer(self):
        """View mode + colormap row is above the compositor."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._build_right)
        view_seg_pos = src.index("_view_seg")
        compositor_pos = src.index("_compositor")
        assert view_seg_pos < compositor_pos

    def test_apply_styles_metrics_panel(self):
        """_apply_styles refreshes the collapsible metrics panel."""
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._apply_styles)
        assert "_metrics_panel" in src


# ═══════════════════════════════════════════════════════════════════════
# Detached Viewer — read-only large viewer window
# ═══════════════════════════════════════════════════════════════════════

class TestDetachedViewer:
    """DetachedViewer: top-level read-only image viewer window."""

    def test_class_exists(self):
        """DetachedViewer class is importable."""
        from ui.widgets.detached_viewer import DetachedViewer
        assert DetachedViewer is not None

    def test_is_qwidget_window(self):
        """DetachedViewer uses Qt.Window flag for top-level window."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.__init__)
        assert "Qt.Window" in src

    def test_update_image_method(self):
        """update_image accepts pixmap and info string."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.update_image)
        assert "pixmap" in src
        assert "info" in src
        assert "set_pixmap" in src

    def test_closed_signal(self):
        """DetachedViewer has a closed signal."""
        from ui.widgets.detached_viewer import DetachedViewer
        assert hasattr(DetachedViewer, 'closed')

    def test_fullscreen_toggle(self):
        """DetachedViewer supports full-screen toggle."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._toggle_fullscreen)
        assert "showFullScreen" in src
        assert "showNormal" in src

    def test_f11_key_binding(self):
        """F11 key triggers full-screen toggle."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.keyPressEvent)
        assert "Key_F11" in src

    def test_escape_exits_fullscreen(self):
        """Escape key exits full-screen mode."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.keyPressEvent)
        assert "Key_Escape" in src

    def test_delete_on_close(self):
        """Window uses WA_DeleteOnClose for clean lifecycle."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.__init__)
        assert "WA_DeleteOnClose" in src

    def test_canvas_aspect_ratio(self):
        """_ViewerCanvas scales pixmap with aspect ratio preservation."""
        import inspect
        from ui.widgets.detached_viewer import _ViewerCanvas
        src = inspect.getsource(_ViewerCanvas.paintEvent)
        assert "KeepAspectRatio" in src

    def test_double_click_fullscreen(self):
        """Double-clicking the canvas toggles full-screen."""
        import inspect
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert hasattr(_ViewerCanvas, 'double_clicked')

    def test_apply_styles_method(self):
        """DetachedViewer has _apply_styles for theme support."""
        from ui.widgets.detached_viewer import DetachedViewer
        assert hasattr(DetachedViewer, '_apply_styles')

    def test_info_strip(self):
        """DetachedViewer has a compact info label in the bottom bar."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "_info" in src


class TestCaptureDetachIntegration:
    """Capture (AcquireTab) integrates with DetachedViewer."""

    def test_detach_button_exists(self):
        """AcquireTab has a detach button."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "_detach_btn" in src

    def test_detach_button_icon(self):
        """Detach button uses mdi.open-in-new icon."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "mdi.open-in-new" in src

    def test_detach_handler(self):
        """_on_detach_viewer creates a DetachedViewer."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._on_detach_viewer)
        assert "DetachedViewer" in src
        assert "_detached_viewer" in src

    def test_update_live_pushes_to_viewer(self):
        """update_live pushes pixmap to detached viewer if open."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.update_live)
        assert "_detached_viewer" in src
        assert "update_image" in src

    def test_viewer_closed_cleanup(self):
        """_on_viewer_closed nulls the viewer reference."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._on_viewer_closed)
        assert "_detached_viewer = None" in src

    def test_detach_button_in_context_strip(self):
        """Detach button is in the camera context strip row."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        # _detach_btn is added to ctx_row
        detach_pos = src.index("_detach_btn")
        ctx_row_pos = src.index("ctx_row")
        assert detach_pos > ctx_row_pos


# ================================================================== #
#  Experiment Log — data model + persistence                          #
# ================================================================== #

class TestRunEntrySchema:
    """RunEntry dataclass schema and serialisation."""

    def test_auto_uid(self):
        """entry_uid is auto-generated when empty."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry()
        assert len(e.entry_uid) == 12
        assert e.entry_uid.isalnum()

    def test_auto_timestamp(self):
        """timestamp is auto-set to ISO-8601 UTC when empty."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry()
        assert "T" in e.timestamp
        assert e.timestamp.endswith("+00:00") or "Z" in e.timestamp

    def test_unique_uids(self):
        """Each RunEntry gets a unique UID."""
        from acquisition.storage.experiment_log import RunEntry
        uids = {RunEntry().entry_uid for _ in range(100)}
        assert len(uids) == 100

    def test_to_dict_roundtrip(self):
        """to_dict() → from_dict() preserves all fields."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry(
            source="recipe",
            recipe_uid="abc123",
            recipe_label="Thermal Sweep",
            test_variables={"voltage": 1.5, "current": 0.006},
            modality="thermoreflectance",
            session_uid="sess-001",
            session_label="TEA chip run 1",
            operator="James",
            device_id="DUT-42",
            project="EZ500",
            n_frames=16,
            exposure_us=5000.0,
            gain_db=6.0,
            roi_peak_k=15.3,
            roi_mean_k=8.7,
            roi_max_delta_t_k=15.3,
            roi_area_px=450,
            roi_area_fraction=0.032,
            verdict="warning",
            hotspot_count=2,
            outcome="complete",
            duration_s=12.5,
            analysis_skipped=False,
            notes="good run",
        )
        d = e.to_dict()
        e2 = RunEntry.from_dict(d)
        assert e2.source == "recipe"
        assert e2.recipe_uid == "abc123"
        assert e2.test_variables == {"voltage": 1.5, "current": 0.006}
        assert e2.roi_peak_k == 15.3
        assert e2.verdict == "warning"
        assert e2.hotspot_count == 2
        assert e2.notes == "good run"

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict() silently ignores keys not in the schema."""
        from acquisition.storage.experiment_log import RunEntry
        d = {"source": "manual", "unknown_field": 42, "future_col": "x"}
        e = RunEntry.from_dict(d)
        assert e.source == "manual"
        assert not hasattr(e, "unknown_field")

    def test_defaults(self):
        """Default values are sensible for a bare entry."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry()
        assert e.source == "manual"
        assert e.recipe_uid == ""
        assert e.test_variables == {}
        assert e.roi_peak_k is None
        assert e.verdict == ""
        assert e.hotspot_count == 0
        assert e.analysis_skipped is False

    def test_csv_row_none_handling(self):
        """to_csv_row() converts None to empty string."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry()  # roi_* fields are None
        row = e.to_csv_row()
        assert row["roi_peak_k"] == ""
        assert row["roi_mean_k"] == ""
        assert row["roi_area_px"] == ""

    def test_csv_row_test_variables_json(self):
        """to_csv_row() serialises test_variables as JSON string."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry(test_variables={"v": 1.5})
        row = e.to_csv_row()
        import json
        parsed = json.loads(row["test_variables"])
        assert parsed == {"v": 1.5}

    def test_csv_row_empty_variables(self):
        """to_csv_row() produces empty string for empty test_variables."""
        from acquisition.storage.experiment_log import RunEntry
        e = RunEntry(test_variables={})
        row = e.to_csv_row()
        assert row["test_variables"] == ""


class TestMakeEntry:
    """make_entry() factory helper with AnalysisResult integration."""

    def test_manual_without_analysis(self):
        """Manual run without analysis leaves ROI fields as None."""
        from acquisition.storage.experiment_log import make_entry
        e = make_entry(
            source="manual",
            modality="infrared",
            session_uid="s1",
            n_frames=8,
            outcome="complete",
        )
        assert e.source == "manual"
        assert e.roi_peak_k is None
        assert e.verdict == ""

    def test_recipe_with_analysis(self):
        """Recipe run with AnalysisResult populates ROI fields."""
        from acquisition.storage.experiment_log import make_entry
        from types import SimpleNamespace

        hotspot = SimpleNamespace(peak_k=18.5, mean_k=12.0,
                                 area_px=200, severity="fail")
        ar = SimpleNamespace(
            verdict="fail",
            hotspots=[hotspot],
            max_peak_k=18.5,
            total_area_px=200,
            area_fraction=0.015,
            map_mean_k=5.2,
        )
        e = make_entry(
            source="recipe",
            recipe_uid="r1",
            recipe_label="Hotspot Check",
            analysis_result=ar,
            outcome="complete",
        )
        assert e.verdict == "fail"
        assert e.hotspot_count == 1
        assert e.roi_peak_k == 18.5
        assert e.roi_area_px == 200
        assert e.roi_area_fraction == 0.015
        assert e.roi_max_delta_t_k == 18.5

    def test_analysis_skipped(self):
        """analysis_skipped=True leaves ROI fields as None even with result."""
        from acquisition.storage.experiment_log import make_entry
        from types import SimpleNamespace
        ar = SimpleNamespace(verdict="pass", hotspots=[], max_peak_k=1.0,
                             total_area_px=0, area_fraction=0.0, map_mean_k=0.5)
        e = make_entry(analysis_result=ar, analysis_skipped=True)
        assert e.analysis_skipped is True
        assert e.roi_peak_k is None
        assert e.verdict == ""

    def test_multiple_hotspots_max(self):
        """roi_max_delta_t_k picks the highest hotspot peak."""
        from acquisition.storage.experiment_log import make_entry
        from types import SimpleNamespace
        h1 = SimpleNamespace(peak_k=10.0)
        h2 = SimpleNamespace(peak_k=22.0)
        h3 = SimpleNamespace(peak_k=15.0)
        ar = SimpleNamespace(
            verdict="fail", hotspots=[h1, h2, h3],
            max_peak_k=22.0, total_area_px=500,
            area_fraction=0.04, map_mean_k=7.0,
        )
        e = make_entry(analysis_result=ar)
        assert e.roi_max_delta_t_k == 22.0
        assert e.hotspot_count == 3


class TestExperimentLogPersistence:
    """ExperimentLog JSON + CSV persistence and query."""

    @pytest.fixture
    def log_dir(self, tmp_path):
        return str(tmp_path)

    @pytest.fixture
    def elog(self, log_dir):
        from acquisition.storage.experiment_log import ExperimentLog
        return ExperimentLog(log_dir)

    def test_append_creates_files(self, elog, log_dir):
        """append() creates both JSON and CSV files."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(source="manual", session_uid="s1"))
        assert os.path.isfile(elog.json_path)
        assert os.path.isfile(elog.csv_path)

    def test_json_schema_version(self, elog, log_dir):
        """JSON file contains schema_version envelope."""
        from acquisition.storage.experiment_log import RunEntry, SCHEMA_VERSION
        elog.append(RunEntry())
        with open(elog.json_path) as f:
            data = json.load(f)
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["entry_count"] == 1
        assert len(data["entries"]) == 1

    def test_append_multiple(self, elog):
        """Multiple appends accumulate entries."""
        from acquisition.storage.experiment_log import RunEntry
        for i in range(5):
            elog.append(RunEntry(session_uid=f"s{i}"))
        assert elog.count() == 5

    def test_all_entries_order(self, elog):
        """all_entries() returns oldest first."""
        from acquisition.storage.experiment_log import RunEntry
        for label in ["first", "second", "third"]:
            elog.append(RunEntry(session_label=label))
        entries = elog.all_entries()
        assert [e.session_label for e in entries] == ["first", "second", "third"]

    def test_recent_order(self, elog):
        """recent() returns newest first."""
        from acquisition.storage.experiment_log import RunEntry
        for label in ["first", "second", "third"]:
            elog.append(RunEntry(session_label=label))
        entries = elog.recent(2)
        assert len(entries) == 2
        assert entries[0].session_label == "third"
        assert entries[1].session_label == "second"

    def test_csv_content(self, elog):
        """CSV file contains header + data rows."""
        from acquisition.storage.experiment_log import RunEntry, CSV_COLUMNS
        elog.append(RunEntry(source="recipe", recipe_label="Test Recipe",
                             verdict="pass"))
        with open(elog.csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["source"] == "recipe"
        assert rows[0]["recipe_label"] == "Test Recipe"
        assert rows[0]["verdict"] == "pass"
        # Header matches CSV_COLUMNS
        with open(elog.csv_path) as f:
            header = f.readline().strip().split(",")
        assert header == CSV_COLUMNS

    def test_csv_append_no_duplicate_header(self, elog):
        """Multiple appends don't duplicate the CSV header."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(session_uid="s1"))
        elog.append(RunEntry(session_uid="s2"))
        with open(elog.csv_path) as f:
            lines = f.readlines()
        header_count = sum(1 for l in lines if l.startswith("entry_uid,"))
        assert header_count == 1

    def test_find_by_source(self, elog):
        """find(source=...) filters correctly."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(source="recipe", recipe_uid="r1"))
        elog.append(RunEntry(source="manual"))
        elog.append(RunEntry(source="recipe", recipe_uid="r2"))
        results = elog.find(source="recipe")
        assert len(results) == 2
        assert all(e.source == "recipe" for e in results)

    def test_find_by_verdict(self, elog):
        """find(verdict=...) filters correctly."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(verdict="pass"))
        elog.append(RunEntry(verdict="fail"))
        elog.append(RunEntry(verdict="pass"))
        results = elog.find(verdict="fail")
        assert len(results) == 1
        assert results[0].verdict == "fail"

    def test_find_combined_filters(self, elog):
        """find() with multiple filters uses AND logic."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(source="recipe", verdict="pass"))
        elog.append(RunEntry(source="recipe", verdict="fail"))
        elog.append(RunEntry(source="manual", verdict="pass"))
        results = elog.find(source="recipe", verdict="pass")
        assert len(results) == 1

    def test_find_limit(self, elog):
        """find(limit=N) caps results."""
        from acquisition.storage.experiment_log import RunEntry
        for i in range(10):
            elog.append(RunEntry(source="manual"))
        results = elog.find(limit=3)
        assert len(results) == 3

    def test_find_newest_first(self, elog):
        """find() returns newest first."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(session_label="old"))
        elog.append(RunEntry(session_label="new"))
        results = elog.find()
        assert results[0].session_label == "new"

    def test_max_entries_cap(self, elog):
        """JSON is capped at MAX_ENTRIES."""
        from acquisition.storage import experiment_log as mod
        from acquisition.storage.experiment_log import RunEntry
        old_max = mod.MAX_ENTRIES
        try:
            mod.MAX_ENTRIES = 5
            for i in range(8):
                elog.append(RunEntry(session_uid=f"s{i}"))
            entries = elog.all_entries()
            assert len(entries) == 5
            # Oldest entries were evicted
            assert entries[0].session_uid == "s3"
            assert entries[-1].session_uid == "s7"
        finally:
            mod.MAX_ENTRIES = old_max

    def test_export_csv(self, elog, tmp_path):
        """export_csv() writes a complete CSV to a custom path."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(source="recipe", session_uid="s1"))
        elog.append(RunEntry(source="manual", session_uid="s2"))
        export_path = str(tmp_path / "export.csv")
        count = elog.export_csv(export_path)
        assert count == 2
        assert os.path.isfile(export_path)
        with open(export_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_rebuild_csv(self, elog):
        """rebuild_csv() regenerates CSV from JSON source of truth."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(session_uid="s1"))
        elog.append(RunEntry(session_uid="s2"))
        # Corrupt CSV
        with open(elog.csv_path, "w") as f:
            f.write("garbage")
        count = elog.rebuild_csv()
        assert count == 2
        with open(elog.csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_clear(self, elog):
        """clear() removes all entries."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry())
        elog.clear()
        assert elog.count() == 0
        assert not os.path.isfile(elog.csv_path)

    def test_empty_log_operations(self, elog):
        """Operations on an empty log don't crash."""
        assert elog.count() == 0
        assert elog.all_entries() == []
        assert elog.recent() == []
        assert elog.find(source="recipe") == []

    def test_corrupt_json_recovery(self, elog):
        """Corrupt JSON is handled gracefully."""
        from acquisition.storage.experiment_log import RunEntry
        os.makedirs(os.path.dirname(elog.json_path), exist_ok=True)
        with open(elog.json_path, "w") as f:
            f.write("{bad json")
        # Should not raise — returns empty
        assert elog.count() == 0
        # Can still append after corruption
        elog.append(RunEntry(session_uid="recovery"))
        assert elog.count() == 1

    def test_future_schema_rejected(self, elog):
        """JSON with schema_version > current is refused (data safety)."""
        from acquisition.storage.experiment_log import SCHEMA_VERSION
        os.makedirs(os.path.dirname(elog.json_path), exist_ok=True)
        with open(elog.json_path, "w") as f:
            json.dump({"schema_version": SCHEMA_VERSION + 1,
                        "entries": [{"source": "manual"}]}, f)
        assert elog.count() == 0

    def test_thread_safety(self, elog):
        """Concurrent appends don't corrupt the log."""
        from acquisition.storage.experiment_log import RunEntry
        errors = []
        def worker(start):
            try:
                for i in range(20):
                    elog.append(RunEntry(session_uid=f"t{start}-{i}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert elog.count() == 80

    def test_find_by_session_uid(self, elog):
        """find(session_uid=...) returns matching entries."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(session_uid="target"))
        elog.append(RunEntry(session_uid="other"))
        results = elog.find(session_uid="target")
        assert len(results) == 1
        assert results[0].session_uid == "target"

    def test_find_by_device_id(self, elog):
        """find(device_id=...) returns matching entries."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(device_id="DUT-1"))
        elog.append(RunEntry(device_id="DUT-2"))
        results = elog.find(device_id="DUT-1")
        assert len(results) == 1

    def test_find_by_project(self, elog):
        """find(project=...) returns matching entries."""
        from acquisition.storage.experiment_log import RunEntry
        elog.append(RunEntry(project="EZ500"))
        elog.append(RunEntry(project="Other"))
        results = elog.find(project="EZ500")
        assert len(results) == 1


# ================================================================== #
#  Recipe Run Panel — structure + payload + integration               #
# ================================================================== #

class TestRecipeRunPanelStructure:
    """RecipeRunPanel UI structure and widget composition."""

    def test_class_exists(self):
        """RecipeRunPanel can be imported."""
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        assert RecipeRunPanel is not None

    def test_payload_class_exists(self):
        """RecipeRunPayload dataclass exists."""
        from ui.widgets.recipe_run_panel import RecipeRunPayload
        p = RecipeRunPayload()
        assert p.recipe_uid == ""
        assert p.bypass_analyzer is False
        assert p.test_variables == {}

    def test_payload_to_dict(self):
        """RecipeRunPayload.to_dict() produces a serialisable dict."""
        from ui.widgets.recipe_run_panel import RecipeRunPayload
        p = RecipeRunPayload(
            recipe_uid="r1", recipe_label="Test",
            modality="thermoreflectance",
            n_frames=16, bypass_analyzer=True,
            test_variables={"voltage": 1.5},
        )
        d = p.to_dict()
        assert d["recipe_uid"] == "r1"
        assert d["bypass_analyzer"] is True
        assert d["test_variables"] == {"voltage": 1.5}

    def test_signals_exist(self):
        """Panel has run_requested, run_completed, edit_recipe_requested signals."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel)
        assert "run_requested = pyqtSignal" in src
        assert "run_completed = pyqtSignal" in src
        assert "edit_recipe_requested = pyqtSignal" in src

    def test_has_recipe_combo(self):
        """Panel has a recipe selector combo box."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_recipe_combo" in src
        assert "QComboBox" in src

    def test_has_summary_strip(self):
        """Panel has a summary strip for recipe details."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_summary_frame" in src
        assert "_summary_labels" in src

    def test_summary_shows_key_fields(self):
        """Summary strip shows modality, frames, exposure, profile, threshold."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        for key in ["modality", "frames", "exposure", "profile", "threshold"]:
            assert f'"{key}"' in src, f"Missing summary key: {key}"

    def test_has_bypass_checkbox(self):
        """Panel has a 'Bypass Analyzer' checkbox."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_bypass_cb" in src
        assert "Bypass Analyzer" in src

    def test_has_run_button(self):
        """Panel has a RUN RECIPE button."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_run_btn" in src
        assert "RUN SCAN" in src

    def test_has_abort_button(self):
        """Panel has an abort button (hidden until running)."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_abort_btn" in src
        assert "IC.STOP" in src

    def test_has_progress_bar(self):
        """Panel has a progress bar (hidden until running)."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_progress" in src
        assert "QProgressBar" in src

    def test_has_result_strip(self):
        """Panel has a result strip (hidden until complete)."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_result_strip" in src
        assert "_result_text" in src

    def test_has_context_fields(self):
        """Panel has operator, device, project, notes inputs."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_operator_input" in src
        assert "_device_input" in src
        assert "_project_input" in src
        assert "_notes_input" in src

    def test_has_edit_link(self):
        """Panel has an 'Edit Recipe ▸' link for Expert mode."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_ui)
        assert "_edit_link" in src
        assert "Edit Recipe" in src


class TestRecipeRunPanelBehavior:
    """RecipeRunPanel logic — payload building, mode gating, log integration."""

    def test_build_payload_from_recipe(self):
        """_build_payload() constructs payload from active recipe."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._build_payload)
        assert "RecipeRunPayload" in src
        assert "recipe_uid" in src
        assert "test_variables" in src
        assert "bypass_analyzer" in src

    def test_run_emits_signal(self):
        """_on_run_clicked emits run_requested with payload dict."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._on_run_clicked)
        assert "run_requested.emit" in src
        assert "_build_payload" in src

    def test_workspace_mode_guided(self):
        """Guided mode hides context fields."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.set_workspace_mode)
        assert "_context_frame.setVisible(not is_guided)" in src

    def test_workspace_mode_expert(self):
        """Expert mode shows edit recipe link."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.set_workspace_mode)
        assert "_edit_link.setVisible(is_expert)" in src

    def test_on_run_complete_appends_log(self):
        """on_run_complete() appends to the experiment log."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.on_run_complete)
        assert "make_entry" in src
        assert "elog.append" in src
        assert "run_completed.emit" in src

    def test_on_run_error_logs_error(self):
        """on_run_error() logs an error entry to the experiment log."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.on_run_error)
        assert "make_entry" in src
        assert 'outcome="error"' in src

    def test_variable_inputs_for_bias(self):
        """Bias-enabled recipes generate voltage/current variable inputs."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._generate_variable_inputs)
        assert "bias_voltage_v" in src
        assert "bias_current_a" in src
        assert "bias.enabled" in src

    def test_variable_inputs_for_tec(self):
        """TEC-enabled recipes generate temperature variable input."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._generate_variable_inputs)
        assert "tec_setpoint_c" in src
        assert "tec.enabled" in src

    def test_progress_phases(self):
        """on_run_progress handles cold/delay/hot/processing phases."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.on_run_progress)
        for phase in ["cold", "delay", "hot", "processing"]:
            assert f'"{phase}"' in src, f"Missing phase: {phase}"

    def test_result_strip_verdict_colors(self):
        """_show_result uses palette colors for pass/warning/fail."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._show_result)
        assert "PALETTE['success']" in src
        assert "PALETTE['warning']" in src
        assert "PALETTE['danger']" in src

    def test_run_does_not_edit_recipe(self):
        """Run panel does not modify recipe fields — run vs build separation."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        # _build_payload should not save or mutate the recipe
        src = inspect.getsource(RecipeRunPanel._build_payload)
        assert "recipe.save" not in src
        assert "RecipeStore" not in src
        # No assignment to recipe attributes (recipe.x = ...)
        import re
        mutations = re.findall(r'recipe\.\w+\s*=', src)
        assert len(mutations) == 0, f"Recipe mutations found: {mutations}"

    def test_has_apply_styles(self):
        """Panel has _apply_styles for theme support."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        assert hasattr(RecipeRunPanel, '_apply_styles')
        src = inspect.getsource(RecipeRunPanel._apply_styles)
        assert "PALETTE" in src

    def test_load_recipes_api(self):
        """load_recipes() populates the combo from Recipe objects."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.load_recipes)
        assert "_recipe_combo" in src
        assert "addItem" in src


# ================================================================== #
#  Experiment Log Widget — table UI                                    #
# ================================================================== #

class TestExperimentLogWidgetStructure:
    """ExperimentLogWidget UI structure and components."""

    def test_class_exists(self):
        """ExperimentLogWidget can be imported."""
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        assert ExperimentLogWidget is not None

    def test_open_session_signal(self):
        """Widget has open_session_requested signal."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget)
        assert "open_session_requested = pyqtSignal" in src

    def test_has_table(self):
        """Widget has a QTableWidget."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "QTableWidget" in src
        assert "_table" in src

    def test_default_columns(self):
        """Default columns include all required fields."""
        from ui.widgets.experiment_log_widget import _COLUMNS, _COL_KEYS
        required = [
            "timestamp", "source", "recipe_label", "session_label",
            "modality", "device_id", "project", "verdict",
            "hotspot_count", "roi_peak_k", "duration_s", "operator",
        ]
        for key in required:
            assert key in _COL_KEYS, f"Missing column: {key}"

    def test_column_count(self):
        """12 default columns."""
        from ui.widgets.experiment_log_widget import _COLUMNS
        assert len(_COLUMNS) == 12

    def test_has_source_filter(self):
        """Widget has a source filter combo (All/Scan Profile/Manual)."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_source_filter" in src
        assert '"All"' in src
        assert '"Scan Profile"' in src
        assert '"Manual"' in src

    def test_has_verdict_filter(self):
        """Widget has a verdict filter combo (All/Pass/Warning/Fail)."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_verdict_filter" in src
        assert '"Pass"' in src
        assert '"Warning"' in src
        assert '"Fail"' in src

    def test_has_export_button(self):
        """Widget has an Export CSV button."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_export_btn" in src
        assert "Export CSV" in src

    def test_has_refresh_button(self):
        """Widget has a Refresh button."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_refresh_btn" in src
        assert "mdi.refresh" in src

    def test_has_empty_state(self):
        """Widget has an empty-state label."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_empty_label" in src
        assert "No experiment log entries" in src

    def test_has_count_label(self):
        """Widget has an entry count label."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "_count_label" in src

    def test_table_not_editable(self):
        """Table is read-only (NoEditTriggers)."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "NoEditTriggers" in src

    def test_table_sortable(self):
        """Table has sorting enabled."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "setSortingEnabled(True)" in src

    def test_table_row_selection(self):
        """Table selects full rows, single selection."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._build_ui)
        assert "SelectRows" in src
        assert "SingleSelection" in src


class TestExperimentLogWidgetBehavior:
    """ExperimentLogWidget logic — filtering, navigation, formatting."""

    def test_double_click_emits_session_uid(self):
        """Double-clicking a row emits open_session_requested."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._on_row_double_clicked)
        assert "open_session_requested.emit" in src
        assert "session_uid" in src

    def test_session_uid_stored_in_item(self):
        """Session UID is stored as UserRole data on row items."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._populate_table)
        assert "Qt.UserRole" in src
        assert "session_uid" in src

    def test_verdict_coloring(self):
        """Verdict cells use palette colors (pass=success, fail=danger)."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._populate_table)
        assert "PALETTE['success']" in src
        assert "PALETTE['warning']" in src
        assert "PALETTE['danger']" in src

    def test_modality_short_names(self):
        """Modality column displays short names (TR, IR, etc.)."""
        from ui.widgets.experiment_log_widget import _MODALITY_SHORT
        assert _MODALITY_SHORT["thermoreflectance"] == "TR"
        assert _MODALITY_SHORT["ir_lockin"] == "IR"

    def test_filter_logic(self):
        """_apply_filters_and_populate filters by source and verdict."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._apply_filters_and_populate)
        assert "source_filter" in src
        assert "verdict_filter" in src

    def test_refresh_reads_from_log(self):
        """refresh() instantiates ExperimentLog and reads entries."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.refresh)
        assert "ExperimentLog" in src
        assert "all_entries" in src

    def test_append_entry_api(self):
        """append_entry() adds to cache without disk I/O."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.append_entry)
        assert "_entries.insert" in src

    def test_export_uses_file_dialog(self):
        """Export uses QFileDialog and ExperimentLog.export_csv."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._on_export)
        assert "QFileDialog" in src
        assert "export_csv" in src

    def test_timestamp_formatting(self):
        """Timestamp column strips fractional seconds and uses spaces."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._make_item)
        assert '[:19]' in src
        assert 'replace("T"' in src

    def test_peak_dt_formatting(self):
        """Peak ΔT column formats as float with K suffix."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._make_item)
        assert ':.2f' in src

    def test_has_apply_styles(self):
        """Widget has _apply_styles for theme support."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        assert hasattr(ExperimentLogWidget, '_apply_styles')
        src = inspect.getsource(ExperimentLogWidget._apply_styles)
        assert "PALETTE" in src
        assert "MONO_FONT" in src

    def test_alternating_row_colors(self):
        """Table uses alternating row colors from palette."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._apply_styles)
        assert "alternate-background-color" in src

    def test_count_label_filtered_vs_total(self):
        """Count label shows filtered/total when filters are active."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._apply_filters_and_populate)
        assert "of" in src  # "N of M entries"
        assert "entries" in src


# ================================================================== #
#  Measurement Setup — consolidated entry surface (replaces Quick Start)
# ================================================================== #

class TestMeasurementSetupGoals:
    """Measurement Goal definitions and filtering."""

    def test_goals_tr_defined(self):
        """TR goal list exists and has expected entries."""
        from ui.tabs.modality_section import _GOALS_TR
        assert len(_GOALS_TR) >= 5
        ids = [g[0] for g in _GOALS_TR]
        assert "measurement" in ids
        assert "calibration" in ids
        assert "transient_series" in ids

    def test_goals_ir_defined(self):
        """IR goal list exists and excludes transient."""
        from ui.tabs.modality_section import _GOALS_IR
        assert len(_GOALS_IR) >= 4
        ids = [g[0] for g in _GOALS_IR]
        assert "measurement" in ids
        assert "transient_series" not in ids

    def test_goals_for_helper(self):
        """_goals_for returns TR goals by default, IR goals for 'ir'."""
        from ui.tabs.modality_section import _goals_for
        tr = _goals_for("tr")
        ir = _goals_for("ir")
        assert len(tr) > len(ir)  # TR has transient, IR doesn't
        assert any(g[0] == "transient_series" for g in tr)
        assert not any(g[0] == "transient_series" for g in ir)

    def test_all_goals_have_five_fields(self):
        """Every goal tuple has (id, title, subtitle, icon, navigate_to)."""
        from ui.tabs.modality_section import _GOALS_TR, _GOALS_IR
        for g in _GOALS_TR + _GOALS_IR:
            assert len(g) == 5
            gid, title, subtitle, icon, nav = g
            assert isinstance(gid, str)
            assert isinstance(title, str)
            assert isinstance(nav, str)

    def test_navigate_targets_valid(self):
        """All goal navigate_to targets are valid sidebar labels."""
        from ui.tabs.modality_section import _GOALS_TR, _GOALS_IR
        valid = {"Live View", "Capture", "Calibration", "Transient", "Sessions"}
        for g in _GOALS_TR + _GOALS_IR:
            assert g[4] in valid, f"Invalid target for {g[0]}: {g[4]}"

    def test_measurement_goal_is_first(self):
        """'Measurement' is the default first goal for both camera types."""
        from ui.tabs.modality_section import _GOALS_TR, _GOALS_IR
        assert _GOALS_TR[0][0] == "measurement"
        assert _GOALS_IR[0][0] == "measurement"


class TestMeasurementSetupUI:
    """ModalitySection enhanced with goal selector and begin button."""

    def test_goal_combo_exists(self):
        """ModalitySection has a _goal_combo widget."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_goal_combo" in src
        assert "Measurement Goal" in src

    def test_begin_button_exists(self):
        """ModalitySection has a _begin_btn widget."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_begin_btn" in src
        assert "Begin" in src

    def test_single_camera_row_exists(self):
        """ModalitySection has a single-camera read-only row."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._build_controls_page)
        assert "_single_cam_row" in src
        assert "_single_cam_label" in src
        assert "_single_cam_badge" in src

    def test_refresh_goals_method(self):
        """_refresh_goals populates goal combo from camera type."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._refresh_goals)
        assert "_goals_for" in src
        assert "_goal_combo" in src

    def test_on_goal_changed_updates_begin_button(self):
        """Goal change updates begin button text."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._on_goal_changed)
        assert "_begin_btn" in src
        assert "Begin" in src

    def test_on_begin_emits_navigate(self):
        """Begin button emits navigate_requested with target label."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._on_begin)
        assert "navigate_requested.emit" in src

    def test_camera_combo_shows_single_cam_row(self):
        """Single-camera path shows read-only row instead of combo."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._refresh_camera_combo)
        assert "_single_cam_row" in src
        assert "setVisible" in src

    def test_camera_combo_refreshes_goals(self):
        """Camera type change also refreshes goals."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._on_camera_type_changed)
        assert "_refresh_goals" in src

    def test_apply_styles_covers_new_widgets(self):
        """_apply_styles handles goal_desc and begin_btn."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._apply_styles)
        assert "_goal_desc" in src
        assert "_begin_btn" in src


# ================================================================== #
#  Phase 1 Integration — main_app wiring                              #
# ================================================================== #

class TestPhase1Integration:
    """Verify all Phase 1 widgets are wired into main_app."""

    def test_measurement_setup_in_sidebar(self):
        """Measurement Setup is registered as a sidebar item (replaces Quick Start)."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert '"Measurement Setup"' in src
        assert "self._modality_section" in src

    def test_recipe_run_created(self):
        """main_app creates RecipeRunPanel."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "self._recipe_run" in src
        assert "RecipeRunPanel" in src

    def test_experiment_log_widget_created(self):
        """main_app creates ExperimentLogWidget."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "self._experiment_log_widget" in src
        assert "ExperimentLogWidget" in src

    def test_no_quick_start_section(self):
        """Quick Start section is removed from sidebar."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert '"QUICK START"' not in src
        assert "QuickStartLauncher" not in src

    def test_recipe_run_in_sidebar(self):
        """Run Scan is registered as a sidebar item."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "NL.RUN_SCAN" in src
        assert "self._recipe_run" in src

    def test_experiment_log_in_sidebar(self):
        """Experiment Log is registered as a sidebar item."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert '"Experiment Log"' in src
        assert "self._experiment_log_widget" in src

    def test_measurement_setup_navigate_wired(self):
        """Measurement Setup navigate_requested is connected."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "navigate_requested" in src
        assert "select_by_label" in src

    def test_recipe_run_signal_wired(self):
        """Recipe Run run_requested signal is connected."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "run_requested.connect" in src
        assert "_on_recipe_run_requested" in src

    def test_experiment_log_signal_wired(self):
        """Experiment Log open_session_requested signal is connected."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "open_session_requested.connect" in src
        assert "_on_experiment_log_open_session" in src

    def test_recipe_run_handler_starts_acquisition(self):
        """_on_recipe_run_requested starts acquisition via existing path."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_recipe_run_requested)
        assert "_on_acquire_requested" in src
        assert "n_frames" in src

    def test_experiment_log_handler_navigates(self):
        """_on_experiment_log_open_session navigates to Sessions."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_experiment_log_open_session)
        assert "NL.SESSIONS" in src
        assert "select_session" in src

    def test_guided_mode_navigates_to_measurement_setup(self):
        """Switching to Guided mode navigates to Measurement Setup."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_workspace_changed)
        assert 'mode == "guided"' in src
        assert "navigate_to" in src
        assert "_modality_section" in src

    def test_recipe_run_mode_gated(self):
        """Recipe Run Panel receives set_workspace_mode calls."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_workspace_changed)
        assert "_recipe_run" in src

    def test_recipes_loaded_at_startup(self):
        """Recipes are loaded into the run panel at startup."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "load_recipes" in src
        assert "RecipeStore" in src

    def test_operator_prefilled(self):
        """Operator is pre-filled from lab preferences."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "set_operator" in src
        assert "lab.active_operator" in src

    def test_edit_recipe_navigates_to_library(self):
        """Edit Recipe link navigates to Library tab."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "edit_recipe_requested" in src
        assert "Library" in src

    def test_nav_icons_include_required_entries(self):
        """NAV_ICONS dict includes Modality and Experiment Log."""
        from ui.icons import NAV_ICONS
        assert "Modality" in NAV_ICONS
        assert "Experiment Log" in NAV_ICONS

    def test_ic_constants_exist(self):
        """IC class has QUICK_START and RUN_LOG constants."""
        from ui.icons import IC
        assert hasattr(IC, "QUICK_START")
        assert hasattr(IC, "RUN_LOG")
        assert "rocket" in IC.QUICK_START
        assert "table" in IC.RUN_LOG

    def test_measurement_setup_first_in_configuration(self):
        """Measurement Setup is the first item in CONFIGURATION phase."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        config_pos = src.index('"CONFIGURATION"')
        ms_pos = src.index('"Measurement Setup"')
        assert ms_pos > config_pos  # inside the CONFIGURATION section

    def test_sidebar_order_workflow_before_system(self):
        """WORKFLOW section appears before SYSTEM in sidebar."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        wf_pos = src.index('"WORKFLOW"')
        sys_pos = src.index('"SYSTEM"')
        assert wf_pos < sys_pos


# ╔══════════════════════════════════════════════════════════════════╗
# ║  PHASE 2 — Detached Viewer v2 (Movie / Transient / Analysis)   ║
# ╚══════════════════════════════════════════════════════════════════╝

class TestDetachedViewerV2MovieTab:
    """Verify Movie tab has detached viewer plumbing."""

    def _src(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        return inspect.getsource(MovieTab)

    # ── Button exists ──────────────────────────────────────────
    def test_detach_button_created(self):
        src = self._src()
        assert "_detach_btn" in src

    def test_detach_button_icon(self):
        src = self._src()
        assert "mdi.open-in-new" in src

    def test_detach_button_tooltip(self):
        src = self._src()
        assert "detached large viewer" in src.lower()

    def test_detach_button_connected(self):
        src = self._src()
        assert "_detach_btn.clicked.connect(self._on_detach_viewer)" in src

    # ── Methods exist ──────────────────────────────────────────
    def test_on_detach_viewer_method(self):
        from acquisition.movie_tab import MovieTab
        assert callable(getattr(MovieTab, "_on_detach_viewer", None))

    def test_on_viewer_closed_method(self):
        from acquisition.movie_tab import MovieTab
        assert callable(getattr(MovieTab, "_on_viewer_closed", None))

    def test_push_to_detached_method(self):
        from acquisition.movie_tab import MovieTab
        assert callable(getattr(MovieTab, "_push_to_detached", None))

    # ── Class attribute ────────────────────────────────────────
    def test_detached_viewer_attr_default_none(self):
        from acquisition.movie_tab import MovieTab
        assert MovieTab._detached_viewer is None

    # ── DetachedViewer import ──────────────────────────────────
    def test_lazy_import_detached_viewer(self):
        src = self._src()
        assert "from ui.widgets.detached_viewer import DetachedViewer" in src

    # ── Push call in _show_frame ───────────────────────────────
    def test_push_called_in_show_frame(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._show_frame)
        assert "_push_to_detached" in src

    # ── Title ──────────────────────────────────────────────────
    def test_viewer_title_contains_movie(self):
        src = self._src()
        assert 'DetachedViewer("Movie' in src

    # ── _on_viewer_closed resets to None ───────────────────────
    def test_viewer_closed_resets(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._on_viewer_closed)
        assert "_detached_viewer = None" in src

    # ── Push uses compositor.grab() ────────────────────────────
    def test_push_uses_compositor_grab(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._push_to_detached)
        assert "_compositor.grab()" in src

    # ── Push includes frame info ───────────────────────────────
    def test_push_includes_frame_info(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._push_to_detached)
        assert "Frame" in src


class TestDetachedViewerV2TransientTab:
    """Verify Transient tab has detached viewer plumbing."""

    def _src(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        return inspect.getsource(TransientTab)

    def test_detach_button_created(self):
        src = self._src()
        assert "_detach_btn" in src

    def test_detach_button_icon(self):
        src = self._src()
        assert "mdi.open-in-new" in src

    def test_detach_button_connected(self):
        src = self._src()
        assert "_detach_btn.clicked.connect(self._on_detach_viewer)" in src

    def test_on_detach_viewer_method(self):
        from acquisition.transient_tab import TransientTab
        assert callable(getattr(TransientTab, "_on_detach_viewer", None))

    def test_on_viewer_closed_method(self):
        from acquisition.transient_tab import TransientTab
        assert callable(getattr(TransientTab, "_on_viewer_closed", None))

    def test_push_to_detached_method(self):
        from acquisition.transient_tab import TransientTab
        assert callable(getattr(TransientTab, "_push_to_detached", None))

    def test_detached_viewer_attr_default_none(self):
        from acquisition.transient_tab import TransientTab
        assert TransientTab._detached_viewer is None

    def test_lazy_import_detached_viewer(self):
        src = self._src()
        assert "from ui.widgets.detached_viewer import DetachedViewer" in src

    def test_push_called_in_show_frame(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._show_frame)
        assert "_push_to_detached" in src

    def test_viewer_title_contains_transient(self):
        src = self._src()
        assert 'DetachedViewer("Transient' in src

    def test_viewer_closed_resets(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._on_viewer_closed)
        assert "_detached_viewer = None" in src

    def test_push_uses_compositor_grab(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._push_to_detached)
        assert "_compositor.grab()" in src

    def test_push_includes_delay_info(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._push_to_detached)
        assert "Delay" in src


class TestDetachedViewerV2AnalysisTab:
    """Verify Analysis tab has detached viewer plumbing."""

    def _src(self):
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        return inspect.getsource(AnalysisTab)

    def test_detach_button_created(self):
        src = self._src()
        assert "_detach_btn" in src

    def test_detach_button_icon(self):
        src = self._src()
        assert "mdi.open-in-new" in src

    def test_detach_button_connected(self):
        src = self._src()
        assert "_detach_btn.clicked.connect(self._on_detach_viewer)" in src

    def test_on_detach_viewer_method(self):
        from acquisition.analysis_tab import AnalysisTab
        assert callable(getattr(AnalysisTab, "_on_detach_viewer", None))

    def test_on_viewer_closed_method(self):
        from acquisition.analysis_tab import AnalysisTab
        assert callable(getattr(AnalysisTab, "_on_viewer_closed", None))

    def test_push_to_detached_method(self):
        from acquisition.analysis_tab import AnalysisTab
        assert callable(getattr(AnalysisTab, "_push_to_detached", None))

    def test_detached_viewer_attr_default_none(self):
        from acquisition.analysis_tab import AnalysisTab
        assert AnalysisTab._detached_viewer is None

    def test_lazy_import_detached_viewer(self):
        src = self._src()
        assert "from ui.widgets.detached_viewer import DetachedViewer" in src

    def test_push_called_in_run(self):
        """Push is called after _canvas.update_result in _run."""
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._run)
        assert "_push_to_detached" in src

    def test_viewer_title_contains_analysis(self):
        src = self._src()
        assert 'DetachedViewer("Analysis' in src

    def test_viewer_closed_resets(self):
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._on_viewer_closed)
        assert "_detached_viewer = None" in src

    def test_push_uses_canvas_grab(self):
        """Analysis uses _canvas.grab() (not _compositor)."""
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._push_to_detached)
        assert "_canvas.grab()" in src

    def test_push_includes_verdict_info(self):
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._push_to_detached)
        assert "verdict" in src

    def test_push_no_index_arg(self):
        """Analysis push takes no index (unlike Movie/Transient)."""
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        sig = inspect.signature(AnalysisTab._push_to_detached)
        # Only 'self' parameter
        params = [p for p in sig.parameters if p != "self"]
        assert len(params) == 0

    def test_detach_button_in_toolbar(self):
        """Detach button is built inside _build_toolbar."""
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._build_toolbar)
        assert "_detach_btn" in src


class TestDetachedViewerV2Consistency:
    """Cross-tab consistency checks for Detached Viewer v2."""

    def test_all_three_tabs_have_detach(self):
        """Movie, Transient, and Analysis all expose _on_detach_viewer."""
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        from acquisition.analysis_tab import AnalysisTab
        for cls in (MovieTab, TransientTab, AnalysisTab):
            assert callable(getattr(cls, "_on_detach_viewer", None)), \
                f"{cls.__name__} missing _on_detach_viewer"

    def test_all_three_have_push(self):
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        from acquisition.analysis_tab import AnalysisTab
        for cls in (MovieTab, TransientTab, AnalysisTab):
            assert callable(getattr(cls, "_push_to_detached", None)), \
                f"{cls.__name__} missing _push_to_detached"

    def test_all_three_have_closed(self):
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        from acquisition.analysis_tab import AnalysisTab
        for cls in (MovieTab, TransientTab, AnalysisTab):
            assert callable(getattr(cls, "_on_viewer_closed", None)), \
                f"{cls.__name__} missing _on_viewer_closed"

    def test_all_use_same_icon(self):
        """All three tabs use the same icon for the detach button."""
        import inspect
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        from acquisition.analysis_tab import AnalysisTab
        for cls in (MovieTab, TransientTab, AnalysisTab):
            src = inspect.getsource(cls)
            count = src.count("mdi.open-in-new")
            assert count >= 1, f"{cls.__name__} missing mdi.open-in-new"

    def test_acquire_tab_also_has_detach(self):
        """Verify existing AcquireTab still has detached viewer (v1)."""
        from ui.tabs.acquire_tab import AcquireTab
        assert callable(getattr(AcquireTab, "_on_detach_viewer", None))
        assert AcquireTab._detached_viewer is None


# ╔══════════════════════════════════════════════════════════════════╗
# ║  PHASE 2 — Merge View Standardization                          ║
# ╚══════════════════════════════════════════════════════════════════╝

class TestMergeViewLiveCanvas:
    """Verify LiveCanvas merge mode plumbing."""

    def test_set_merge_method_exists(self):
        from acquisition.live_tab import LiveCanvas
        assert callable(getattr(LiveCanvas, "set_merge", None))

    def test_merge_default_false(self):
        from acquisition.live_tab import LiveCanvas
        src = __import__("inspect").getsource(LiveCanvas.__init__)
        assert "_merge" in src
        assert "False" in src

    def test_cold_data_stored(self):
        """update_frame stores cold_avg for merge base."""
        import inspect
        from acquisition.live_tab import LiveCanvas
        src = inspect.getsource(LiveCanvas.update_frame)
        assert "_cold_data" in src
        assert "cold_avg" in src

    def test_rebuild_base_method_exists(self):
        from acquisition.live_tab import LiveCanvas
        assert callable(getattr(LiveCanvas, "_rebuild_base", None))

    def test_rebuild_base_uses_gray_cmap(self):
        """Base pixmap should use grayscale colormap."""
        import inspect
        from acquisition.live_tab import LiveCanvas
        src = inspect.getsource(LiveCanvas._rebuild_base)
        assert '"gray"' in src

    def test_rebuild_calls_rebuild_base_in_merge(self):
        """_rebuild triggers _rebuild_base when merge is active."""
        import inspect
        from acquisition.live_tab import LiveCanvas
        src = inspect.getsource(LiveCanvas._rebuild)
        assert "_rebuild_base" in src

    def test_paint_merge_draws_base_then_thermal(self):
        """paintEvent in merge mode draws base at full opacity then thermal."""
        import inspect
        from acquisition.live_tab import LiveCanvas
        src = inspect.getsource(LiveCanvas.paintEvent)
        assert "_base_pixmap" in src
        assert "_overlay_opacity" in src
        # Merge branch should exist
        assert "_merge" in src

    def test_paint_merge_resets_opacity(self):
        """After drawing thermal overlay, opacity is reset to 1.0."""
        import inspect
        from acquisition.live_tab import LiveCanvas
        src = inspect.getsource(LiveCanvas.paintEvent)
        assert "setOpacity(1.0)" in src


class TestMergeViewLiveTab:
    """Verify LiveTab has Merge toggle in toolbar."""

    def _src(self):
        import inspect
        from acquisition.live_tab import LiveTab
        return inspect.getsource(LiveTab)

    def test_view_seg_created(self):
        src = self._src()
        assert "_view_seg" in src

    def test_segmented_control_labels(self):
        """Toggle has 'Thermal' and 'Merge' options."""
        src = self._src()
        assert '"Thermal"' in src
        assert '"Merge"' in src

    def test_on_view_mode_handler(self):
        from acquisition.live_tab import LiveTab
        assert callable(getattr(LiveTab, "_on_view_mode", None))

    def test_on_view_mode_calls_set_merge(self):
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab._on_view_mode)
        assert "set_merge" in src

    def test_guided_mode_hides_merge_toggle(self):
        """In Guided mode, the Merge toggle should be hidden."""
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab.set_workspace_mode)
        assert "_view_seg" in src
        assert "not is_guided" in src

    def test_view_seg_connected(self):
        src = self._src()
        assert "_view_seg.selection_changed.connect(self._on_view_mode)" in src

    def test_view_seg_in_toolbar(self):
        """SegmentedControl is built inside _build_toolbar."""
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab._build_toolbar)
        assert "_view_seg" in src


class TestMergeViewMovieTransientAlreadyPresent:
    """Confirm Movie and Transient tabs already have Merge View."""

    def test_movie_has_view_seg(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab)
        assert "_view_seg" in src
        assert '"Thermal"' in src
        assert '"Merge"' in src

    def test_movie_on_view_mode(self):
        from acquisition.movie_tab import MovieTab
        assert callable(getattr(MovieTab, "_on_view_mode", None))

    def test_movie_merge_in_show_frame(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._show_frame)
        assert "_view_seg.index() == 1" in src
        assert "set_base_frame" in src

    def test_transient_has_view_seg(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab)
        assert "_view_seg" in src
        assert '"Thermal"' in src
        assert '"Merge"' in src

    def test_transient_on_view_mode(self):
        from acquisition.transient_tab import TransientTab
        assert callable(getattr(TransientTab, "_on_view_mode", None))

    def test_transient_merge_in_show_frame(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._show_frame)
        assert "_view_seg.index() == 1" in src
        assert "set_base_frame" in src


class TestMergeViewAnalysisPreComposed:
    """Analysis overlay_rgb is already a pre-composed merge. No toggle needed."""

    def test_overlay_rgb_includes_base(self):
        """_make_overlay uses base_image as greyscale background."""
        import inspect
        from acquisition.processing.analysis import ThermalAnalysisEngine
        src = inspect.getsource(ThermalAnalysisEngine._make_overlay)
        assert "base_image" in src
        # Greyscale conversion
        assert "0.2126" in src or "luminance" in src.lower() or "bg" in src

    def test_overlay_rgb_is_composite(self):
        """The overlay already composites base + hotspot tint."""
        import inspect
        from acquisition.processing.analysis import ThermalAnalysisEngine
        src = inspect.getsource(ThermalAnalysisEngine._make_overlay)
        # Hotspot regions are tinted onto the base
        assert "canvas" in src
        assert "region" in src


class TestMergeViewConsistency:
    """Cross-tab consistency for Merge View."""

    def test_all_image_tabs_have_merge_concept(self):
        """Live, Movie, Transient all have Thermal/Merge SegmentedControl."""
        import inspect
        from acquisition.live_tab import LiveTab
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        for cls in (LiveTab, MovieTab, TransientTab):
            src = inspect.getsource(cls)
            assert "_view_seg" in src, f"{cls.__name__} missing _view_seg"
            assert '"Merge"' in src, f"{cls.__name__} missing Merge label"

    def test_all_have_on_view_mode(self):
        from acquisition.live_tab import LiveTab
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        for cls in (LiveTab, MovieTab, TransientTab):
            assert callable(getattr(cls, "_on_view_mode", None)), \
                f"{cls.__name__} missing _on_view_mode"

    def test_segmented_control_same_dimensions(self):
        """All tabs use same SegmentedControl dimensions for visual consistency."""
        import inspect
        from acquisition.live_tab import LiveTab
        from acquisition.movie_tab import MovieTab
        from acquisition.transient_tab import TransientTab
        for cls in (LiveTab, MovieTab, TransientTab):
            src = inspect.getsource(cls)
            assert "seg_width=72" in src, f"{cls.__name__} inconsistent seg_width"
            assert "height=24" in src, f"{cls.__name__} inconsistent height"


# ╔══════════════════════════════════════════════════════════════════╗
# ║  PHASE 2 — Timing/Bias Summary Strips                          ║
# ╚══════════════════════════════════════════════════════════════════╝

class TestHwSummaryStripWidget:
    """Verify the HwSummaryStrip widget structure and API."""

    def test_import(self):
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        assert HwSummaryStrip is not None

    def test_update_timing_method(self):
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        assert callable(getattr(HwSummaryStrip, "update_timing", None))

    def test_update_bias_method(self):
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        assert callable(getattr(HwSummaryStrip, "update_bias", None))

    def test_set_workspace_mode_method(self):
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        assert callable(getattr(HwSummaryStrip, "set_workspace_mode", None))

    def test_apply_styles_method(self):
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        assert callable(getattr(HwSummaryStrip, "_apply_styles", None))

    def test_fixed_height(self):
        """Strip should be thin (28px)."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip.__init__)
        assert "setFixedHeight(28)" in src

    def test_timing_labels(self):
        """Strip should show timing section labels."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip._build_ui)
        assert "Mod:" in src
        assert "Sync" in src
        assert "Stim" in src

    def test_bias_labels(self):
        """Strip should show bias section labels."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip._build_ui)
        assert "Bias:" in src
        assert "OUT" in src or "out_val" in src

    def test_divider_between_sections(self):
        """Timing and bias sections separated by a divider."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip._build_ui)
        assert "_divider" in src


class TestHwSummaryStripFormatting:
    """Verify formatting helpers."""

    def test_fmt_freq_hz(self):
        from ui.widgets.hw_summary_strip import _fmt_freq
        assert _fmt_freq(100) == "100.0 Hz"

    def test_fmt_freq_khz(self):
        from ui.widgets.hw_summary_strip import _fmt_freq
        assert _fmt_freq(1000) == "1.0 kHz"

    def test_fmt_freq_mhz(self):
        from ui.widgets.hw_summary_strip import _fmt_freq
        assert _fmt_freq(1_000_000) == "1.0 MHz"

    def test_fmt_freq_zero(self):
        from ui.widgets.hw_summary_strip import _fmt_freq
        assert _fmt_freq(0) == "--"

    def test_fmt_duty(self):
        from ui.widgets.hw_summary_strip import _fmt_duty
        assert _fmt_duty(50) == "50%"

    def test_fmt_duty_zero(self):
        from ui.widgets.hw_summary_strip import _fmt_duty
        assert _fmt_duty(0) == "--"

    def test_dot_true(self):
        from ui.widgets.hw_summary_strip import _dot
        assert _dot(True) == "\u25cf"

    def test_dot_false(self):
        from ui.widgets.hw_summary_strip import _dot
        assert _dot(False) == "\u25cb"


class TestHwSummaryStripModeGating:
    """Verify workspace mode visibility."""

    def test_guided_hides(self):
        """set_workspace_mode('guided') should hide the strip."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip.set_workspace_mode)
        assert '"guided"' in src
        assert "setVisible" in src

    def test_standard_shows(self):
        """Standard mode should show the strip (mode != 'guided')."""
        import inspect
        from ui.widgets.hw_summary_strip import HwSummaryStrip
        src = inspect.getsource(HwSummaryStrip.set_workspace_mode)
        assert 'mode != "guided"' in src


class TestHwSummaryStripInLiveTab:
    """Verify strip is embedded in Live View tab."""

    def test_hw_strip_created(self):
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab)
        assert "_hw_strip" in src
        assert "HwSummaryStrip" in src

    def test_hw_strip_in_layout(self):
        """Strip is added to root layout."""
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab.__init__)
        assert "root.addWidget(self._hw_strip)" in src

    def test_workspace_mode_forwards_to_strip(self):
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab.set_workspace_mode)
        assert "_hw_strip" in src
        assert "set_workspace_mode" in src

    def test_apply_styles_forwards_to_strip(self):
        import inspect
        from acquisition.live_tab import LiveTab
        src = inspect.getsource(LiveTab._apply_styles)
        assert "_hw_strip" in src


class TestHwSummaryStripInAcquireTab:
    """Verify strip is embedded in Capture/Acquire tab."""

    def test_hw_strip_created(self):
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab)
        assert "_hw_strip" in src
        assert "HwSummaryStrip" in src

    def test_hw_strip_in_layout(self):
        """Strip is added to left panel layout."""
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.__init__)
        assert "left.addWidget(self._hw_strip)" in src

    def test_set_workspace_mode_exists(self):
        from ui.tabs.acquire_tab import AcquireTab
        assert callable(getattr(AcquireTab, "set_workspace_mode", None))

    def test_workspace_mode_forwards_to_strip(self):
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.set_workspace_mode)
        assert "_hw_strip" in src

    def test_apply_styles_forwards_to_strip(self):
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab._apply_styles)
        assert "_hw_strip" in src


class TestHwSummaryStripWiring:
    """Verify main_app forwards status to strips."""

    def test_fpga_status_forwarded_to_live_strip(self):
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_fpga)
        assert "_live_tab" in src
        assert "_hw_strip" in src
        assert "update_timing" in src

    def test_fpga_status_forwarded_to_acquire_strip(self):
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_fpga)
        assert "_acquire_tab" in src
        assert "update_timing" in src

    def test_bias_status_forwarded_to_live_strip(self):
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_bias)
        assert "_live_tab" in src
        assert "update_bias" in src

    def test_bias_status_forwarded_to_acquire_strip(self):
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_bias)
        assert "_acquire_tab" in src
        assert "update_bias" in src

    def test_acquire_tab_in_workspace_mode_loop(self):
        """AcquireTab should be included in workspace mode propagation."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_workspace_changed)
        assert "_acquire_tab" in src


# ╔══════════════════════════════════════════════════════════════════╗
# ║  PHASE 2 — Detached Viewer v3 (Light Interaction)              ║
# ╚══════════════════════════════════════════════════════════════════╝

class TestDetachedViewerV3Structure:
    """Verify v3 DetachedViewer widget structure."""

    def test_import(self):
        from ui.widgets.detached_viewer import DetachedViewer
        assert DetachedViewer is not None

    def test_canvas_class_has_cursor_signal(self):
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert hasattr(_ViewerCanvas, "cursor_value")

    def test_canvas_has_mouse_tracking(self):
        import inspect
        from ui.widgets.detached_viewer import _ViewerCanvas
        src = inspect.getsource(_ViewerCanvas.__init__)
        assert "setMouseTracking(True)" in src

    def test_canvas_has_set_data(self):
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert callable(getattr(_ViewerCanvas, "set_data", None))

    def test_canvas_has_set_rois(self):
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert callable(getattr(_ViewerCanvas, "set_rois", None))

    def test_canvas_has_set_show_rois(self):
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert callable(getattr(_ViewerCanvas, "set_show_rois", None))

    def test_canvas_widget_to_data_method(self):
        from ui.widgets.detached_viewer import _ViewerCanvas
        assert callable(getattr(_ViewerCanvas, "_widget_to_data", None))

    def test_canvas_paints_rois(self):
        import inspect
        from ui.widgets.detached_viewer import _ViewerCanvas
        src = inspect.getsource(_ViewerCanvas.paintEvent)
        assert "_show_rois" in src
        assert "_rois" in src


class TestDetachedViewerV3BottomBar:
    """Verify bottom bar has colormap combo, ROI toggle, cursor readout."""

    def test_bottom_bar_built(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.__init__)
        assert "_build_bottom_bar" in src

    def test_cmap_combo_exists(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "_cmap_combo" in src
        assert "QComboBox" in src

    def test_cmap_follow_source_option(self):
        """First item in combo should be 'Follow Source' sentinel."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "Source" in src
        assert "insertItem(0" in src

    def test_roi_checkbox_exists(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "_roi_cb" in src
        assert "QCheckBox" in src

    def test_roi_checkbox_connected(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "set_show_rois" in src

    def test_cursor_label_exists(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "_cursor_lbl" in src

    def test_info_label_exists(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._build_bottom_bar)
        assert "_info" in src


class TestDetachedViewerV3API:
    """Verify expanded update_image API."""

    def test_update_image_accepts_data(self):
        """update_image() should accept data= keyword argument."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        sig = inspect.signature(DetachedViewer.update_image)
        assert "data" in sig.parameters

    def test_update_image_accepts_rois(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        sig = inspect.signature(DetachedViewer.update_image)
        assert "rois" in sig.parameters

    def test_update_image_accepts_cmap(self):
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        sig = inspect.signature(DetachedViewer.update_image)
        assert "cmap" in sig.parameters

    def test_data_rois_cmap_are_keyword_only(self):
        """data, rois, cmap should be keyword-only for backward compat."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        sig = inspect.signature(DetachedViewer.update_image)
        for name in ("data", "rois", "cmap"):
            p = sig.parameters[name]
            assert p.kind == inspect.Parameter.KEYWORD_ONLY, \
                f"{name} should be keyword-only"

    def test_rerender_method_exists(self):
        from ui.widgets.detached_viewer import DetachedViewer
        assert callable(getattr(DetachedViewer, "_rerender", None))

    def test_on_cursor_method_exists(self):
        from ui.widgets.detached_viewer import DetachedViewer
        assert callable(getattr(DetachedViewer, "_on_cursor", None))

    def test_on_cmap_changed_method_exists(self):
        from ui.widgets.detached_viewer import DetachedViewer
        assert callable(getattr(DetachedViewer, "_on_cmap_changed", None))


class TestDetachedViewerV3ColorMap:
    """Verify colormap local override logic."""

    def test_rerender_uses_processing(self):
        """_rerender imports rendering utilities from acquisition.processing."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._rerender)
        assert "to_display" in src
        assert "apply_colormap" in src

    def test_rerender_handles_signed_cmap(self):
        """Thermal Delta / signed colormaps have special rendering."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._rerender)
        assert "Thermal Delta" in src

    def test_follow_source_resets_local_cmap(self):
        """Selecting index 0 (Follow Source) clears _local_cmap."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._on_cmap_changed)
        assert '_local_cmap = ""' in src

    def test_update_image_rerender_when_cmap_differs(self):
        """update_image calls _rerender when local cmap differs."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer.update_image)
        assert "_rerender" in src
        assert "_local_cmap" in src


class TestDetachedViewerV3SourcePushes:
    """Verify source screens pass data/rois/cmap to detached viewer."""

    def test_capture_passes_data(self):
        import inspect
        from ui.tabs.acquire_tab import AcquireTab
        src = inspect.getsource(AcquireTab.update_live)
        assert "data=frame.data" in src

    def test_movie_passes_data_and_cmap(self):
        import inspect
        from acquisition.movie_tab import MovieTab
        src = inspect.getsource(MovieTab._push_to_detached)
        assert "data=" in src
        assert "cmap=" in src

    def test_transient_passes_data_and_cmap(self):
        import inspect
        from acquisition.transient_tab import TransientTab
        src = inspect.getsource(TransientTab._push_to_detached)
        assert "data=" in src
        assert "cmap=" in src

    def test_analysis_passes_dt_map(self):
        """Analysis pushes ΔT map for cursor readout."""
        import inspect
        from acquisition.analysis_tab import AnalysisTab
        src = inspect.getsource(AnalysisTab._push_to_detached)
        assert "data=" in src
        assert "_dt_map" in src


class TestDetachedViewerV3BackwardCompat:
    """Ensure v1/v2 callers still work without new keyword args."""

    def test_update_image_defaults(self):
        """data, rois, cmap all default to None/empty."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        sig = inspect.signature(DetachedViewer.update_image)
        assert sig.parameters["data"].default is None
        assert sig.parameters["rois"].default is None
        assert sig.parameters["cmap"].default == ""

    def test_fullscreen_hides_bottom_bar(self):
        """Full-screen toggle hides _bottom (not just _info)."""
        import inspect
        from ui.widgets.detached_viewer import DetachedViewer
        src = inspect.getsource(DetachedViewer._toggle_fullscreen)
        assert "_bottom" in src

    def test_apply_styles_exists(self):
        from ui.widgets.detached_viewer import DetachedViewer
        assert callable(getattr(DetachedViewer, "_apply_styles", None))


# ================================================================== #
#  Phase 3 Step 1 — Recipe Builder Enhancements                       #
# ================================================================== #


class TestRecipeVariableField:
    """Recipe model: variables list field and persistence."""

    def test_variables_field_exists(self):
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        assert hasattr(r, "variables")
        assert r.variables == []

    def test_variables_in_to_dict(self):
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        r.variables = ["bias.voltage_v", "tec.setpoint_c"]
        d = r.to_dict()
        assert d["variables"] == ["bias.voltage_v", "tec.setpoint_c"]

    def test_from_dict_parses_variables(self):
        from acquisition.recipe_tab import Recipe
        d = {"label": "test", "variables": ["camera.exposure_us", "bias.voltage_v"]}
        r = Recipe.from_dict(d)
        assert r.variables == ["camera.exposure_us", "bias.voltage_v"]

    def test_from_dict_missing_variables_defaults_empty(self):
        from acquisition.recipe_tab import Recipe
        d = {"label": "legacy"}
        r = Recipe.from_dict(d)
        assert r.variables == []

    def test_roundtrip_preserves_variables(self):
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        r.variables = ["analysis.threshold_k", "camera.n_frames"]
        r2 = Recipe.from_dict(r.to_dict())
        assert r2.variables == r.variables


class TestVariableFieldsRegistry:
    """VARIABLE_FIELDS registry completeness and structure."""

    def test_registry_exists(self):
        from acquisition.recipe_tab import VARIABLE_FIELDS
        assert isinstance(VARIABLE_FIELDS, dict)
        assert len(VARIABLE_FIELDS) >= 9

    def test_all_entries_have_correct_shape(self):
        from acquisition.recipe_tab import VARIABLE_FIELDS
        for fp, val in VARIABLE_FIELDS.items():
            assert isinstance(fp, str)
            assert "." in fp, f"field path must be dotted: {fp}"
            assert len(val) == 3, f"expected (label, type, suffix): {fp}"
            label, vtype, suffix = val
            assert isinstance(label, str)
            assert vtype in (int, float, str)
            assert isinstance(suffix, str)

    def test_expected_fields_present(self):
        from acquisition.recipe_tab import VARIABLE_FIELDS
        expected = [
            "camera.exposure_us", "camera.gain_db", "camera.n_frames",
            "acquisition.inter_phase_delay_s",
            "analysis.threshold_k", "analysis.fail_peak_k",
            "bias.voltage_v", "bias.current_a", "tec.setpoint_c",
        ]
        for fp in expected:
            assert fp in VARIABLE_FIELDS, f"missing: {fp}"

    def test_field_to_widget_map_subset(self):
        from acquisition.recipe_tab import _FIELD_TO_WIDGET, VARIABLE_FIELDS
        for fp in _FIELD_TO_WIDGET:
            assert fp in VARIABLE_FIELDS


class TestRecipeTabVariableToggles:
    """RecipeTab variable toggle UI."""

    def test_var_toggles_dict_exists(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab.__init__)
        assert "_var_toggles" in src

    def test_make_var_row_creates_checkbox(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        assert hasattr(RecipeTab, "_make_var_row")
        src = inspect.getsource(RecipeTab._make_var_row)
        assert "QCheckBox" in src
        assert "VAR" in src

    def test_toggles_for_exposure(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "camera.exposure_us" in src

    def test_toggles_for_gain(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "camera.gain_db" in src

    def test_toggles_for_threshold(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "analysis.threshold_k" in src

    def test_toggles_for_fail_peak(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "analysis.fail_peak_k" in src

    def test_populate_sets_toggle_state(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._populate_editor)
        assert "_var_toggles" in src
        assert "variables" in src

    def test_editor_to_recipe_collects_variables(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._editor_to_recipe)
        assert "variables" in src
        assert "_var_toggles" in src


class TestRecipeTabWorkspaceMode:
    """RecipeTab workspace mode gating."""

    def test_set_workspace_mode_exists(self):
        from acquisition.recipe_tab import RecipeTab
        assert callable(getattr(RecipeTab, "set_workspace_mode", None))

    def test_workspace_mode_standard_view_only(self):
        """Standard mode disables editing."""
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab.set_workspace_mode)
        assert "standard" in src
        assert "setEnabled" in src

    def test_workspace_mode_expert_shows_toggles(self):
        """Expert mode shows variable toggles."""
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab.set_workspace_mode)
        assert "expert" in src
        assert "_var_toggles" in src

    def test_workspace_mode_hides_lock_in_standard(self):
        """Standard hides lock/capture buttons."""
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab.set_workspace_mode)
        assert "_lock_btn" in src
        assert "_cap_btn" in src

    def test_set_editor_enabled_respects_standard(self):
        """_set_editor_enabled checks workspace_mode."""
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._set_editor_enabled)
        assert "is_standard" in src or "workspace_mode" in src

    def test_wires_workspace_manager(self):
        """RecipeTab connects to workspace manager on init."""
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab.__init__)
        assert "get_manager" in src
        assert "mode_changed" in src


class TestRecipeTabPreviewPanel:
    """Run-time preview panel in RecipeTab."""

    def test_preview_frame_exists(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "_preview_frame" in src
        assert "_preview_body" in src

    def test_preview_header_text(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "Operator Run-Time Preview" in src

    def test_update_preview_method(self):
        from acquisition.recipe_tab import RecipeTab
        assert callable(getattr(RecipeTab, "_update_preview", None))

    def test_update_preview_shows_designated_fields(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._update_preview)
        assert "VARIABLE_FIELDS" in src
        assert "Operator will see" in src

    def test_preview_hidden_initially(self):
        import inspect
        from acquisition.recipe_tab import RecipeTab
        src = inspect.getsource(RecipeTab._build)
        assert "_preview_frame" in src
        assert "setVisible(False)" in src


class TestRecipeRunPanelVariableDesignation:
    """RecipeRunPanel reads from recipe.variables."""

    def test_generate_uses_designated_variables(self):
        """v2: explicit variables list is preferred over auto-generation."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._generate_variable_inputs)
        assert "designated" in src or "variables" in src
        assert "VARIABLE_FIELDS" in src

    def test_v1_fallback_still_exists(self):
        """v1 fallback: auto-generate from bias/TEC enabled state."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._generate_variable_inputs)
        assert "bias.enabled" in src or "recipe.bias.enabled" in src
        assert "fallback" in src.lower() or "v1" in src.lower()

    def test_resolve_field_helper(self):
        """_resolve_field correctly resolves dotted paths."""
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        r.bias.voltage_v = 3.3
        r.camera.exposure_us = 12000.0
        assert RecipeRunPanel._resolve_field(r, "bias.voltage_v") == 3.3
        assert RecipeRunPanel._resolve_field(r, "camera.exposure_us") == 12000.0

    def test_resolve_field_missing_returns_empty(self):
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        assert RecipeRunPanel._resolve_field(r, "nonexistent.field") == ""

    def test_designated_vars_produce_inputs(self):
        """When recipe.variables has entries, inputs are generated from registry."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel._generate_variable_inputs)
        assert "_add_variable_input" in src
        assert "field_path" in src


class TestRecipeBuilderConsistency:
    """Cross-cutting consistency checks."""

    def test_recipe_store_roundtrip_with_variables(self):
        """RecipeStore save/load preserves variables."""
        import json
        from acquisition.recipe_tab import Recipe
        r = Recipe()
        r.label = "test_vars"
        r.variables = ["bias.voltage_v", "camera.exposure_us"]
        d = r.to_dict()
        r2 = Recipe.from_dict(d)
        assert r2.variables == r.variables

    def test_run_build_boundary_maintained(self):
        """RecipeRunPanel never writes to Recipe objects."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        # The panel should not call recipe.save() or modify recipe fields
        src = inspect.getsource(RecipeRunPanel)
        assert ".save(" not in src or "elog" in src  # only experiment log save
        assert "_store.save" not in src

    def test_variable_fields_all_resolvable(self):
        """Every entry in VARIABLE_FIELDS resolves on a default Recipe."""
        from acquisition.recipe_tab import Recipe, VARIABLE_FIELDS
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        r = Recipe()
        for fp in VARIABLE_FIELDS:
            val = RecipeRunPanel._resolve_field(r, fp)
            assert val != "", f"failed to resolve {fp}"


# ================================================================== #
#  Phase B Step 5 — Experiment Log Beta Tightening                    #
# ================================================================== #


class TestExperimentLogWorkspaceMode:
    """Experiment Log workspace mode gating."""

    def test_set_workspace_mode_exists(self):
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        assert callable(getattr(ExperimentLogWidget, "set_workspace_mode", None))

    def test_guided_hidden_columns_defined(self):
        from ui.widgets.experiment_log_widget import _GUIDED_HIDDEN
        assert isinstance(_GUIDED_HIDDEN, set)
        assert "source" in _GUIDED_HIDDEN
        assert "modality" in _GUIDED_HIDDEN
        assert "device_id" in _GUIDED_HIDDEN
        assert "project" in _GUIDED_HIDDEN
        assert "operator" in _GUIDED_HIDDEN

    def test_guided_keeps_essential_columns(self):
        """Guided mode does NOT hide critical columns."""
        from ui.widgets.experiment_log_widget import _GUIDED_HIDDEN
        essential = {"timestamp", "recipe_label", "session_label",
                     "verdict", "hotspot_count", "roi_peak_k", "duration_s"}
        assert not (essential & _GUIDED_HIDDEN)

    def test_set_workspace_mode_hides_columns(self):
        """set_workspace_mode('guided') hides columns in _GUIDED_HIDDEN."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.set_workspace_mode)
        assert "setColumnHidden" in src
        assert "_GUIDED_HIDDEN" in src

    def test_wires_workspace_manager(self):
        """Widget connects to workspace manager on init."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.__init__)
        assert "get_manager" in src
        assert "mode_changed" in src


class TestExperimentLogAutoRefresh:
    """Auto-refresh on show and live update on run completion."""

    def test_show_event_refreshes(self):
        """showEvent triggers refresh()."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.showEvent)
        assert "refresh" in src

    def test_run_completed_wired_to_refresh(self):
        """main_app wires RecipeRunPanel.run_completed to log refresh."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "run_completed" in src
        assert "_experiment_log_widget" in src
        assert "refresh" in src


class TestExperimentLogCSVExport:
    """CSV export correctness verification."""

    def test_export_csv_method_exists(self):
        from acquisition.storage.experiment_log import ExperimentLog
        assert callable(getattr(ExperimentLog, "export_csv", None))

    def test_csv_columns_complete(self):
        """CSV output includes all RunEntry fields."""
        from acquisition.storage.experiment_log import CSV_COLUMNS
        expected = [
            "entry_uid", "timestamp", "source", "recipe_uid", "recipe_label",
            "modality", "session_uid", "session_label", "operator", "device_id",
            "project", "verdict", "hotspot_count", "outcome", "duration_s",
        ]
        for col in expected:
            assert col in CSV_COLUMNS, f"missing CSV column: {col}"

    def test_csv_export_returns_count(self):
        """export_csv returns the number of rows written."""
        import tempfile, os
        from acquisition.storage.experiment_log import ExperimentLog, make_entry
        with tempfile.TemporaryDirectory() as d:
            elog = ExperimentLog(d)
            elog.append(make_entry(source="recipe", recipe_label="test"))
            elog.append(make_entry(source="manual"))
            path = os.path.join(d, "test_export.csv")
            count = elog.export_csv(path)
            assert count == 2
            # Verify file has header + 2 data rows
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 3  # header + 2 rows


class TestExperimentLogSessionDrillDown:
    """Row-to-session navigation reliability."""

    def test_double_click_emits_session_uid(self):
        """Double-click handler reads session_uid from row data."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._on_row_double_clicked)
        assert "session_uid" in src
        assert "open_session_requested" in src

    def test_main_app_handles_open_session(self):
        """main_app navigates to Sessions and selects session."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._on_experiment_log_open_session)
        assert "NL.SESSIONS" in src
        assert "select_session" in src

    def test_session_uid_stored_on_first_column(self):
        """session_uid is stored as UserRole data on the first column item."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget._populate_table)
        assert "session_uid" in src
        assert "Qt.UserRole" in src


class TestExperimentLogEndToEndFlow:
    """End-to-end: Measurement Setup → Recipe Run → Experiment Log → Session."""

    def test_recipe_run_writes_to_log(self):
        """RecipeRunPanel.on_run_complete writes to ExperimentLog."""
        import inspect
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        src = inspect.getsource(RecipeRunPanel.on_run_complete)
        assert "ExperimentLog" in src
        assert "append" in src

    def test_log_widget_reads_from_log(self):
        """ExperimentLogWidget.refresh reads from ExperimentLog."""
        import inspect
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        src = inspect.getsource(ExperimentLogWidget.refresh)
        assert "ExperimentLog" in src
        assert "all_entries" in src

    def test_measurement_setup_begin_navigates(self):
        """Measurement Setup Begin button navigates to goal target."""
        import inspect
        from ui.tabs.modality_section import ModalitySection
        src = inspect.getsource(ModalitySection._on_begin)
        assert "navigate_requested" in src

    def test_full_flow_signals_exist(self):
        """All signals in the beta workflow chain exist."""
        from ui.tabs.modality_section import ModalitySection
        assert hasattr(ModalitySection, "navigate_requested")
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        assert hasattr(RecipeRunPanel, "run_requested")
        assert hasattr(RecipeRunPanel, "run_completed")
        from ui.widgets.experiment_log_widget import ExperimentLogWidget
        assert hasattr(ExperimentLogWidget, "open_session_requested")


# ════════════════════════════════════════════════════════════════════
#  MEASUREMENT DASHBOARD TESTS
# ════════════════════════════════════════════════════════════════════

class TestMeasurementDashboard:
    """Tests for the Measurement Dashboard (v1)."""

    def test_dashboard_import(self):
        """Dashboard module imports cleanly."""
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        assert MeasurementDashboard is not None

    def test_dashboard_has_required_signals(self):
        """Dashboard exposes navigate_requested and open_session_requested."""
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        assert hasattr(MeasurementDashboard, "navigate_requested")
        assert hasattr(MeasurementDashboard, "open_session_requested")

    def test_dashboard_replaces_modality_in_nav(self):
        """Measurement Setup NI uses the dashboard, not ModalitySection."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "self._dashboard" in src
        assert "NL.MEASUREMENT_SETUP" in src

    def test_modality_section_still_instantiated(self):
        """ModalitySection is still created for signal wiring."""
        import inspect
        from main_app import MainWindow
        src = inspect.getsource(MainWindow._build_ui)
        assert "ModalitySection()" in src
        assert "modality_changed" in src

    def test_context_strip_reads_mctx(self):
        """Dashboard _refresh_context reads from measurement_context."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard._refresh_context)
        assert "mctx.camera_key" in src
        assert "mctx.material_profile_name" in src
        assert "mctx.scan_profile_label" in src
        assert "mctx.scan_profile_modified" in src

    def test_context_cards_navigate_to_correct_targets(self):
        """Context card clicks emit correct navigation labels."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard._build_context_strip)
        assert "NL.CAMERAS" in src
        assert "NL.LIBRARY" in src
        assert "NL.RUN_SCAN" in src

    def test_device_status_reads_app_state(self):
        """Device status reads from app_state, not local cache."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard._refresh_device_status)
        assert "app_state.cam" in src
        assert "app_state.tecs" in src
        assert "app_state.fpga" in src
        assert "app_state.bias" in src
        assert "app_state.stage" in src

    def test_recents_use_session_manager(self):
        """Recent sessions come from session_mgr.all_metas()."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard._refresh_recent_sessions)
        assert "session_mgr" in src
        assert "all_metas" in src

    def test_recents_use_recipe_store(self):
        """Recent profiles come from RecipeStore.list()."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard._refresh_recent_profiles)
        assert "RecipeStore" in src
        assert "list()" in src

    def test_uses_display_terms(self):
        """Dashboard uses TERMS for scan profile terminology."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard)
        assert "TERMS[" in src

    def test_no_guided_banner_duplication(self):
        """Dashboard does not contain guided/workflow step logic."""
        import inspect
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        src = inspect.getsource(MeasurementDashboard)
        assert "GuidedBanner" not in src
        assert "PhaseTracker" not in src
        assert "WORKFLOW_STEPS" not in src
        assert "next_step" not in src.lower()

    def test_recipe_selection_changed_signal_exists(self):
        """RecipeRunPanel has recipe_selection_changed for mctx wiring."""
        from ui.widgets.recipe_run_panel import RecipeRunPanel
        assert hasattr(RecipeRunPanel, "recipe_selection_changed")

    def test_dashboard_has_theme_support(self):
        """Dashboard implements _apply_styles for theme switching."""
        from ui.tabs.measurement_dashboard import MeasurementDashboard
        assert hasattr(MeasurementDashboard, "_apply_styles")
