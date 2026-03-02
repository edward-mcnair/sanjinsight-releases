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

    def test_unknown_fields_are_ignored(self, minimal_result, tmp_path):
        """
        Extra keys in session.json (from a newer version) must be silently
        ignored — forward-compatibility guard.
        """
        from acquisition.session import Session

        session = Session.from_result(minimal_result, label="fwd_compat")
        path    = session.save(str(tmp_path))

        # Inject a hypothetical future field
        json_path = os.path.join(path, "session.json")
        with open(json_path) as f:
            data = json.load(f)
        data["future_field_xyz"] = "some_value"
        data["schema_version"]   = 999   # far-future schema
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Must not raise — unknown keys are ignored by from_dict()
        loaded = Session.load(path)
        assert loaded.meta.label == "fwd_compat"


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
