"""
tests/test_working_copy.py  —  WorkingCopy model tests

Covers the six core operations (load, edit, save, save-as, revert, deselect)
plus the guardrails (equality-based modified, locked protection, rebase
after save-as, generated profile restrictions).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from acquisition.recipe_tab import Recipe, RecipeStore
from acquisition.working_copy import (
    WorkingCopy, Origin,
    load_working_copy, generated_working_copy,
)


@pytest.fixture
def tmp_store(tmp_path):
    """A RecipeStore backed by a temp directory."""
    return RecipeStore(directory=tmp_path)


@pytest.fixture
def saved_recipe(tmp_store):
    """A recipe saved to disk via the store."""
    r = Recipe()
    r.label = "Test Profile"
    r.camera.exposure_us = 1000.0
    r.camera.gain_db = 6.0
    r.acquisition.modality = "thermoreflectance"
    r.analysis.threshold_k = 5.0
    r.bias.enabled = True
    r.bias.voltage_v = 3.3
    tmp_store.save(r)
    return r


@pytest.fixture
def locked_recipe(tmp_store):
    """A locked/approved recipe saved to disk."""
    r = Recipe()
    r.label = "Locked Baseline"
    r.locked = True
    r.approved_by = "admin"
    r.approved_at = "2026-01-01T00:00:00"
    r.variables = ["bias.voltage_v", "tec.setpoint_c"]
    r.camera.exposure_us = 2000.0
    tmp_store.save(r)
    return r


# ── Baseline behavior ──────────────────────────────────────────────


class TestLoadAndModified:
    def test_not_modified_after_load(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert not wc.modified

    def test_modified_after_edit(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 9999.0
        assert wc.modified

    def test_modified_returns_false_when_reverted_by_hand(self, saved_recipe, tmp_store):
        """Equality-based: change a value, change it back → not modified."""
        wc = load_working_copy(saved_recipe, tmp_store)
        original_exposure = wc.recipe.camera.exposure_us
        wc.recipe.camera.exposure_us = 9999.0
        assert wc.modified
        wc.recipe.camera.exposure_us = original_exposure
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
        wc.recipe.camera.exposure_us = 9999.0
        assert saved_recipe.camera.exposure_us == 1000.0


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
        wc.recipe.camera.exposure_us = 7777.0
        wc.save()

        # Reload from disk and check
        reloaded = tmp_store.load(saved_recipe.label)
        assert reloaded is not None
        assert reloaded.camera.exposure_us == 7777.0

    def test_save_resets_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 7777.0
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
        wc.recipe.camera.exposure_us = 5555.0
        assert wc.modified
        wc.save_as("Cloned Profile")
        assert not wc.modified
        assert wc.origin == Origin.LOADED
        assert wc.source_uid == wc.recipe.uid

    def test_save_as_persists_to_disk(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 5555.0
        result = wc.save_as("Cloned Profile")

        # UID-keyed file should exist
        uid_file = tmp_store._dir / f"{result.uid}.json"
        assert uid_file.exists()
        with open(uid_file) as f:
            data = json.load(f)
        assert data["camera"]["exposure_us"] == 5555.0
        assert data["label"] == "Cloned Profile"

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
        wc.recipe.camera.exposure_us = 3333.0
        assert wc.can_save
        wc.save()  # should not raise
        assert not wc.modified


# ── Revert ──────────────────────────────────────────────────────────


class TestRevert:
    def test_revert_restores_all_fields(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 9999.0
        wc.recipe.bias.voltage_v = 99.0
        wc.recipe.label = "Changed Name"
        wc.revert()
        assert wc.recipe.camera.exposure_us == 1000.0
        assert wc.recipe.bias.voltage_v == 3.3
        assert wc.recipe.label == "Test Profile"

    def test_revert_clears_modified(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 9999.0
        assert wc.modified
        wc.revert()
        assert not wc.modified

    def test_revert_preserves_locked_state(self, locked_recipe, tmp_store):
        wc = load_working_copy(locked_recipe, tmp_store)
        wc.recipe.bias.voltage_v = 99.0
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
        wc.recipe.bias.voltage_v = 5.0
        assert wc.modified


# ── Display label ───────────────────────────────────────────────────


class TestDisplayLabel:
    def test_clean_label(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        assert wc.display_label == "Test Profile"

    def test_modified_label(self, saved_recipe, tmp_store):
        wc = load_working_copy(saved_recipe, tmp_store)
        wc.recipe.camera.exposure_us = 9999.0
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
        wc.recipe.camera.exposure_us = 9999.0
        assert wc.modified  # caller should prompt before discarding
