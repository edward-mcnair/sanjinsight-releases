"""
acquisition/working_copy.py  —  Working-copy model for scan profiles

Implements the edit-in-memory / save-explicitly pattern:

  Load   → creates a mutable working copy; original on disk is untouched
  Edit   → mutates only the working copy
  Save   → overwrites the original (only if loaded from an existing profile)
  Save As → creates a new profile with a fresh UID, rebases working copy
  Revert → restores from the original snapshot
  Deselect → caller checks ``modified`` and prompts if True

Design rules:
  - ``modified`` is equality-based: working_copy.to_dict() != baseline snapshot.
    If a user changes a value back, modified returns to False.
  - Locked profiles: only variable fields are editable; Save back to
    the locked original is blocked; Save As is always allowed.
  - Save As rebases: after save-as, the new profile becomes the baseline
    and modified resets to False.
"""
from __future__ import annotations

import copy
import logging
import uuid
from enum import Enum, auto
from typing import Optional

from .recipe_tab import Recipe, RecipeStore

log = logging.getLogger(__name__)


class Origin(Enum):
    """How the working copy was created."""
    LOADED    = auto()   # loaded from an existing saved profile
    GENERATED = auto()   # created from a run payload or snapshot (never saved)


class WorkingCopy:
    """In-memory editable copy of a scan profile (Recipe).

    Parameters
    ----------
    recipe : Recipe
        The recipe to edit.  A deep copy is made internally.
    origin : Origin
        How this working copy was created.
    store : RecipeStore, optional
        Store used for save/revert operations.  Required for save/revert
        but not for read-only inspection.
    """

    def __init__(self, recipe: Recipe, origin: Origin, *,
                 store: Optional[RecipeStore] = None) -> None:
        self._recipe = copy.deepcopy(recipe)
        self._baseline = recipe.to_dict()     # snapshot for modified check
        self._origin = origin
        self._store = store
        self._source_uid: str = recipe.uid    # UID of the profile we loaded from

    # ── Read access ─────────────────────────────────────────────────

    @property
    def recipe(self) -> Recipe:
        """The mutable working copy.  Edit this directly."""
        return self._recipe

    @property
    def origin(self) -> Origin:
        return self._origin

    @property
    def source_uid(self) -> str:
        """UID of the profile this was loaded from (may differ after Save As)."""
        return self._source_uid

    @property
    def is_locked(self) -> bool:
        """True if the *original* was a locked/approved profile."""
        return self._baseline.get("locked", False)

    # ── Modified state (equality-based) ─────────────────────────────

    @property
    def modified(self) -> bool:
        """True when the working copy differs from the loaded baseline.

        This is an equality check, not an event flag.  If a user changes
        a value and then changes it back, modified returns to False.
        """
        return self._recipe.to_dict() != self._baseline

    # ── Capability checks ───────────────────────────────────────────

    @property
    def can_save(self) -> bool:
        """True when Save (overwrite original) is allowed.

        Requires: loaded from an existing profile AND not locked.
        """
        return (self._origin == Origin.LOADED
                and not self.is_locked)

    @property
    def can_save_as(self) -> bool:
        """True when Save As New is allowed (always)."""
        return True

    @property
    def can_revert(self) -> bool:
        """True when revert has meaning (there is a baseline to revert to)."""
        return True

    # ── Operations ──────────────────────────────────────────────────

    def save(self) -> None:
        """Overwrite the original profile on disk.

        Raises
        ------
        ValueError
            If the working copy cannot be saved (generated or locked).
        RuntimeError
            If no store was provided.
        """
        if not self.can_save:
            if self.is_locked:
                raise ValueError(
                    "Cannot overwrite a locked profile.  Use save_as().")
            raise ValueError(
                "Cannot save a generated profile.  Use save_as().")
        if self._store is None:
            raise RuntimeError("No RecipeStore provided")

        self._store.save(self._recipe)
        self._baseline = self._recipe.to_dict()
        log.info("WorkingCopy saved → %s", self._recipe.uid)

    def save_as(self, label: str) -> Recipe:
        """Save as a new profile with a fresh UID.

        After save-as, the working copy rebases to the new profile:
        new UID becomes the source, origin becomes LOADED, modified
        resets to False.

        Parameters
        ----------
        label : str
            Display label for the new profile.

        Returns
        -------
        Recipe
            The newly saved recipe (with its new UID).

        Raises
        ------
        RuntimeError
            If no store was provided.
        """
        if self._store is None:
            raise RuntimeError("No RecipeStore provided")

        # Assign new identity
        self._recipe.uid = str(uuid.uuid4())[:8]
        self._recipe.label = label
        self._recipe.locked = False
        self._recipe.approved_by = ""
        self._recipe.approved_at = ""

        self._store.save_as_new(self._recipe)

        # Rebase: new profile is now the baseline
        self._baseline = self._recipe.to_dict()
        self._source_uid = self._recipe.uid
        self._origin = Origin.LOADED
        log.info("WorkingCopy save-as → %s (%s)", self._recipe.uid, label)

        return copy.deepcopy(self._recipe)

    def revert(self) -> None:
        """Restore the working copy from the baseline snapshot.

        Complete revert: all fields, including locked/read-only values,
        are restored to the originally loaded state.
        """
        self._recipe = Recipe.from_dict(self._baseline)
        log.info("WorkingCopy reverted → %s", self._recipe.uid)

    # ── Display helpers ─────────────────────────────────────────────

    @property
    def display_label(self) -> str:
        """Label suitable for UI display, including modification state."""
        base = self._recipe.label or "Untitled"
        if self.is_locked:
            return f"Locked: {base}"
        if self._origin == Origin.GENERATED:
            return f"Unsaved: {base}"
        if self.modified:
            return f"{base} (modified)"
        return base


# ── Factory helpers ─────────────────────────────────────────────────

def load_working_copy(recipe: Recipe, store: RecipeStore) -> WorkingCopy:
    """Create a working copy from an existing saved profile."""
    return WorkingCopy(recipe, Origin.LOADED, store=store)


def generated_working_copy(recipe: Recipe, *,
                           store: Optional[RecipeStore] = None) -> WorkingCopy:
    """Create a working copy from a generated/ad-hoc recipe (e.g. post-run)."""
    return WorkingCopy(recipe, Origin.GENERATED, store=store)
