"""
tests/test_working_copy.py  —  WorkingCopy model tests

Covers the six core operations (load, edit, save, save-as, revert, deselect)
plus the guardrails (equality-based modified, locked protection, rebase
after save-as, generated profile restrictions).

Uses the v2 phase-based Recipe model.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from acquisition.recipe import (
    Recipe, RecipeStore, _build_standard_phases, infer_requirements,
)
from acquisition.working_copy import (
    WorkingCopy, Origin,
    load_working_copy, generated_working_copy,
)


@pytest.fixture
def tmp_store(tmp_path):
    """A RecipeStore backed by a temp directory."""
    return RecipeStore(directory=tmp_path)


def _make_recipe(**overrides) -> Recipe:
    """Helper to create a v2 Recipe with standard phases."""
    r = Recipe()
    r.label = overrides.pop("label", "Test Profile")
    r.notes = overrides.pop("notes", "")
    r.locked = overrides.pop("locked", False)
    r.approved_by = overrides.pop("approved_by", "")
    r.approved_at = overrides.pop("approved_at", "")
    r.phases = _build_standard_phases(
        camera={"exposure_us": overrides.pop("exposure_us", 1000),
                "gain_db": overrides.pop("gain_db", 6.0)},
        bias={"enabled": overrides.pop("bias_enabled", True),
              "voltage_v": overrides.pop("bias_voltage_v", 3.3)},
    )
    r.variables = overrides.pop("variables", [])
    r.requirements = infer_requirements(r)
    return r


@pytest.fixture
def saved_recipe(tmp_store):
    """A recipe saved to disk via the store."""
    r = _make_recipe()
    tmp_store.save(r)
    return r


@pytest.fixture
def locked_recipe(tmp_store):
    """A locked/approved recipe saved to disk."""
    r = _make_recipe(
        label="Locked Baseline",
        locked=True,
        approved_by="admin",
        approved_at="2026-01-01T00:00:00",
        exposure_us=2000,
    )
    tmp_store.save(r)
    return r


def _get_hw_config(recipe: Recipe) -> dict:
    """Get the hardware_setup phase config from a recipe."""
    return recipe.get_phase_config("hardware_setup")


def _set_exposure(recipe: Recipe, val: float) -> None:
    """Set exposure_us in the hardware_setup phase."""
    hw = recipe.get_phase("hardware_setup")
    hw.config["camera"]["exposure_us"] = val


def _get_exposure(recipe: Recipe) -> float:
    """Get exposure_us from the hardware_setup phase."""
    return _get_hw_config(recipe)["camera"]["exposure_us"]


def _set_bias_voltage(recipe: Recipe, val: float) -> None:
    """Set bias voltage in the hardware_setup phase."""
    hw = recipe.get_phase("hardware_setup")
    hw.config["bias"]["voltage_v"] = val


def _get_bias_voltage(recipe: Recipe) -> float:
    """Get bias voltage from the hardware_setup phase."""
    return _get_hw_config(recipe)["bias"]["voltage_v"]


# ── Baseline behavior ──────────────────────────────────────────────


class TestLoadAndModified:
    def test_not_modified_after_load(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert not wc.modified

    def test_modified_after_edit(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        assert wc.modified

    def test_modified_returns_false_when_reverted_by_hand(self, saved_recipe, tmp_store):
        """Equality-based: change a value, change it back → not modified."""
        wc = load_working_copy(saved_recipe, tmp_store)
        original = _get_exposure(wc.recipe)
        _set_exposure(wc.recipe, 9999.0)
        assert wc.modified
        _set_exposure(wc.recipe, original)
        assert not wc.modified

    def test_origin_is_loaded(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert wc.origin == Origin.LOADED

    def test_origin_is_generated(self, saved_recipe, tmp_store):
        wc = generated_working_copy(saved_recipe, store=tmp_store)
        assert wc.origin == Origin.GENERATED

    def test_deep_copy_isolation(self, saved_recipe, tmp_store):
        """Edits to working copy do not mutate the original Recipe object."""
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        assert _get_exposure(saved_recipe) == 1000.0


# ── Save ────────────────────────────────────────────────────────────


class TestSave:
    def test_can_save_loaded_unlocked(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert wc.can_save

    def test_cannot_save_generated(self, saved_recipe, tmp_store):
        wc = generated_working_copy(saved_recipe, store=tmp_store)
        assert not wc.can_save

    def test_cannot_save_locked(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        assert not wc.can_save

    def test_save_updates_disk(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 7777.0)
        wc.save()

        # Reload from disk and check
        reloaded = tmp_store.load(saved_recipe.uid)
        assert reloaded is not None
        assert _get_exposure(reloaded) == 7777.0

    def test_save_resets_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 7777.0)
        assert wc.modified
        wc.save()
        assert not wc.modified

    def test_save_raises_for_generated(self, saved_recipe, tmp_store):
        wc = generated_working_copy(saved_recipe, store=tmp_store)
        with pytest.raises(ValueError, match="generated"):
            wc.save()

    def test_save_raises_for_locked(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        with pytest.raises(ValueError, match="locked"):
            wc.save()

    def test_save_raises_without_store(self, saved_recipe):
        wc = WorkingCopy(saved_recipe, Origin.LOADED)
        with pytest.raises(RuntimeError, match="No RecipeStore"):
            wc.save()


# ── Save As ─────────────────────────────────────────────────────────


class TestSaveAs:
    def test_save_as_creates_new_uid(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        old_uid = wc.recipe.uid
        result = wc.save_as("Cloned Profile")
        assert result.uid != old_uid

    def test_save_as_rebases(self, saved_recipe, tmp_store):
        """After save-as, origin becomes LOADED, modified is False."""
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 5555.0)
        assert wc.modified
        wc.save_as("Cloned Profile")
        assert not wc.modified
        assert wc.origin == Origin.LOADED
        assert wc.source_uid == wc.recipe.uid

    def test_save_as_persists_to_disk(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 5555.0)
        result = wc.save_as("Cloned Profile")

        # UID-keyed file should exist
        uid_file = tmp_store._dir / f"{result.uid}.json"
        assert uid_file.exists()
        with open(uid_file) as f:
            data = json.load(f)
        assert data["label"] == "Cloned Profile"
        # Verify exposure in hardware_setup phase
        hw_phase = [p for p in data["phases"]
                    if p["phase_type"] == "hardware_setup"][0]
        assert hw_phase["config"]["camera"]["exposure_us"] == 5555.0

    def test_save_as_clears_lock_state(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        result = wc.save_as("Unlocked Clone")
        assert not result.locked
        assert result.approved_by == ""

    def test_save_as_allowed_for_generated(self, saved_recipe, tmp_store):
        wc = generated_working_copy(saved_recipe, store=tmp_store)
        result = wc.save_as("New Profile")
        assert result.uid != saved_recipe.uid
        assert wc.origin == Origin.LOADED

    def test_save_as_raises_without_store(self, saved_recipe):
        wc = WorkingCopy(saved_recipe, Origin.LOADED)
        with pytest.raises(RuntimeError, match="No RecipeStore"):
            wc.save_as("Test")

    def test_subsequent_save_after_save_as(self, saved_recipe, tmp_store):
        """After save-as, Save should work (now loaded, not locked)."""
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.save_as("Cloned Profile")
        _set_exposure(wc.recipe, 3333.0)
        assert wc.can_save
        wc.save()  # should not raise
        assert not wc.modified


# ── Revert ──────────────────────────────────────────────────────────


class TestRevert:
    def test_revert_restores_all_fields(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        _set_bias_voltage(wc.recipe, 99.0)
        wc.recipe.label = "Changed Name"
        wc.revert()
        assert _get_exposure(wc.recipe) == 1000.0
        assert _get_bias_voltage(wc.recipe) == 3.3
        assert wc.recipe.label == "Test Profile"

    def test_revert_clears_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        assert wc.modified
        wc.revert()
        assert not wc.modified

    def test_revert_preserves_locked_state(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        _set_bias_voltage(wc.recipe, 99.0)
        wc.revert()
        assert wc.recipe.locked
        assert wc.recipe.approved_by == "admin"


# ── Locked profile behavior ────────────────────────────────────────


class TestLockedProfile:
    def test_is_locked_from_baseline(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        assert wc.is_locked

    def test_not_locked_for_regular(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert not wc.is_locked

    def test_can_save_as_locked(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        assert wc.can_save_as

    def test_variable_edit_marks_modified(self, locked_recipe, tmp_store):
        """Editing an allowed variable field still sets modified."""
        wc = load_working_copy(locked_recipe, tmp_store)
        _set_bias_voltage(wc.recipe, 5.0)
        assert wc.modified


# ── Display label ───────────────────────────────────────────────────


class TestDisplayLabel:
    def test_clean_label(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert wc.display_label == "Test Profile"

    def test_modified_label(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        assert wc.display_label == "Test Profile (modified)"

    def test_locked_label(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        assert wc.display_label == "Locked: Locked Baseline"

    def test_generated_label(self, saved_recipe, tmp_store):
        wc = generated_working_copy(saved_recipe, store=tmp_store)
        assert wc.display_label == "Unsaved: Test Profile"

    def test_untitled_fallback(self, tmp_store):
        r = Recipe()
        r.label = ""
        wc = load_working_copy(r, tmp_store)
        assert wc.display_label == "Untitled"


# ── Deselect guard ──────────────────────────────────────────────────


class TestDeselectGuard:
    def test_safe_to_deselect_when_not_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert not wc.modified  # safe to discard

    def test_prompt_needed_when_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        _set_exposure(wc.recipe, 9999.0)
        assert wc.modified  # caller should prompt before discarding
