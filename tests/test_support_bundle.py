"""
tests/test_support_bundle.py — Support bundle generator tests.

Verifies that:
- Bundle generation produces a valid zip with expected sections
- App info section includes version/build metadata
- Hardware summary captures device state from app_state
- Error context uses taxonomy to_dict() when available
- AI state snapshot captures provider/tier/status
- Preferences are sanitized (sensitive keys redacted)
- Graceful degradation: missing app_state/ai_service → sections skipped
- Backward compatibility: old call signature still works
"""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from hardware.support_bundle import generate_support_bundle, _sanitize_dict


@pytest.fixture
def tmp_bundle_dir(tmp_path):
    """Provide a temporary output directory for bundles."""
    return tmp_path / "bundles"


# ── Core generation tests ──────────────────────────────────────────────────


class TestBundleGeneration:
    """Tests for generate_support_bundle() output structure."""

    def test_generates_zip(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        assert path.exists()
        assert path.suffix == ".zip"
        assert zipfile.is_zipfile(path)

    def test_contains_core_sections(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            assert "app_info.json" in names
            assert "system_info.json" in names
            assert "python_packages.json" in names

    def test_backward_compat_no_new_params(self, tmp_bundle_dir):
        """Old call signature (no app_state/ai_service) still works."""
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        assert path.exists()
        with zipfile.ZipFile(path, "r") as zf:
            # hardware_summary.json should NOT be present without app_state
            assert "hardware_summary.json" not in zf.namelist()
            # ai_state.json should NOT be present without ai_service
            assert "ai_state.json" not in zf.namelist()


# ── App info section ───────────────────────────────────────────────────────


class TestAppInfo:
    """Tests for the app_info.json section."""

    def test_app_info_contains_version(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            info = json.loads(zf.read("app_info.json"))
            assert "version" in info
            assert "app_name" in info
            assert info["app_name"] == "SanjINSIGHT"
            assert "build_date" in info
            assert "is_prerelease" in info
            assert "timestamp" in info

    def test_demo_mode_none_without_app_state(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            info = json.loads(zf.read("app_info.json"))
            assert info["demo_mode"] is None

    def test_demo_mode_from_app_state(self, tmp_bundle_dir):
        state = SimpleNamespace(demo_mode=True)
        path = generate_support_bundle(
            output_dir=tmp_bundle_dir, app_state=state)
        with zipfile.ZipFile(path, "r") as zf:
            info = json.loads(zf.read("app_info.json"))
            assert info["demo_mode"] is True


# ── Hardware summary section ───────────────────────────────────────────────


class TestHardwareSummary:
    """Tests for the hardware_summary.json section."""

    def _make_app_state(self, **kwargs):
        defaults = dict(
            cam=None, ir_cam=None, active_camera_type="TR",
            fpga=None, bias=None, stage=None, prober=None,
            gpio=None, ldd=None, tecs=[], demo_mode=False,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_skipped_without_app_state(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            assert "hardware_summary.json" not in zf.namelist()

    def test_captures_device_types(self, tmp_bundle_dir):
        fake_cam = SimpleNamespace(connected=True)
        state = self._make_app_state(cam=fake_cam)
        path = generate_support_bundle(
            output_dir=tmp_bundle_dir, app_state=state)
        with zipfile.ZipFile(path, "r") as zf:
            summary = json.loads(zf.read("hardware_summary.json"))
            assert summary["cam"]["type"] == "SimpleNamespace"
            assert summary["cam"]["connected"] is True
            assert summary["ir_cam"] is None

    def test_captures_tec_list(self, tmp_bundle_dir):
        tecs = [
            SimpleNamespace(connected=True),
            SimpleNamespace(connected=False),
        ]
        state = self._make_app_state(tecs=tecs)
        path = generate_support_bundle(
            output_dir=tmp_bundle_dir, app_state=state)
        with zipfile.ZipFile(path, "r") as zf:
            summary = json.loads(zf.read("hardware_summary.json"))
            assert len(summary["tecs"]) == 2
            assert summary["tecs"][0]["connected"] is True
            assert summary["tecs"][1]["connected"] is False


# ── Error context section ──────────────────────────────────────────────────


class TestErrorContext:
    """Tests for error_context.json — taxonomy-aware serialization."""

    def test_uses_to_dict_when_available(self, tmp_bundle_dir):
        from hardware.error_taxonomy import classify_error
        err = classify_error(TimeoutError("timeout"), device_uid="tec0")
        path = generate_support_bundle(
            error_context=[err], output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            errors = json.loads(zf.read("error_context.json"))
            assert len(errors) == 1
            e = errors[0]
            # to_dict() fields from taxonomy
            assert e["category"] == "timeout"
            assert e["domain"] == "hardware"
            assert e["severity"] == "WARNING"
            assert e["transience"] == "transient"
            assert e["device_uid"] == "tec0"
            assert "is_blocking" in e

    def test_legacy_fallback_without_to_dict(self, tmp_bundle_dir):
        """Objects with .category but no .to_dict() use manual extraction."""
        legacy = SimpleNamespace(
            category=SimpleNamespace(value="timeout"),
            device_uid="cam0",
            message="timed out",
            suggested_fix="retry",
            raw_exception="TimeoutError",
            exception_type="TimeoutError",
        )
        path = generate_support_bundle(
            error_context=[legacy], output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            errors = json.loads(zf.read("error_context.json"))
            assert errors[0]["category"] == "timeout"
            assert errors[0]["device_uid"] == "cam0"

    def test_raw_string_fallback(self, tmp_bundle_dir):
        """Plain strings/objects are included as raw."""
        path = generate_support_bundle(
            error_context=["something went wrong"], output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            errors = json.loads(zf.read("error_context.json"))
            assert errors[0]["raw"] == "something went wrong"


# ── AI state section ───────────────────────────────────────────────────────


class TestAIState:
    """Tests for ai_state.json section."""

    def test_skipped_without_ai_service(self, tmp_bundle_dir):
        path = generate_support_bundle(output_dir=tmp_bundle_dir)
        with zipfile.ZipFile(path, "r") as zf:
            assert "ai_state.json" not in zf.namelist()

    def test_captures_provider_and_tier(self, tmp_bundle_dir):
        ai = SimpleNamespace(
            status="ready",
            tier=SimpleNamespace(name="STANDARD", value=2),
            active_backend="remote",
            remote_provider="ollama",
        )
        path = generate_support_bundle(
            output_dir=tmp_bundle_dir, ai_service=ai)
        with zipfile.ZipFile(path, "r") as zf:
            state = json.loads(zf.read("ai_state.json"))
            assert state["status"] == "ready"
            assert state["tier"] == "STANDARD"
            assert state["tier_value"] == 2
            assert state["active_backend"] == "remote"
            assert state["remote_provider"] == "ollama"

    def test_no_sensitive_fields(self, tmp_bundle_dir):
        """API keys and model paths must never appear in ai_state."""
        ai = SimpleNamespace(
            status="ready",
            tier=SimpleNamespace(name="BASIC", value=1),
            active_backend="remote",
            remote_provider="openai",
            api_key="sk-supersecret",
            model_path="/home/user/.models/llama.gguf",
        )
        path = generate_support_bundle(
            output_dir=tmp_bundle_dir, ai_service=ai)
        with zipfile.ZipFile(path, "r") as zf:
            state = json.loads(zf.read("ai_state.json"))
            assert "api_key" not in state
            assert "model_path" not in state
            raw = zf.read("ai_state.json").decode()
            assert "supersecret" not in raw
            assert "llama.gguf" not in raw


# ── Sanitization tests ────────────────────────────────────────────────────


class TestSanitization:
    """Tests for _sanitize_dict redaction."""

    def test_redacts_password(self):
        assert _sanitize_dict({"password": "s3cret"}) == {
            "password": "***REDACTED***"}

    def test_redacts_api_key(self):
        assert _sanitize_dict({"api_key": "abc123"}) == {
            "api_key": "***REDACTED***"}

    def test_preserves_safe_keys(self):
        d = {"hostname": "lab-pc", "port": 5000}
        assert _sanitize_dict(d) == d

    def test_recursive_redaction(self):
        d = {"server": {"host": "10.0.0.1", "token": "xyz"}}
        result = _sanitize_dict(d)
        assert result["server"]["host"] == "10.0.0.1"
        assert result["server"]["token"] == "***REDACTED***"
