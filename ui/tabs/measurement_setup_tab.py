"""
ui/tabs/measurement_setup_tab.py  —  Measurement Setup surface

The primary setup surface that combines:
  - ReadinessPanel: live shrinking checklist of pending actions
  - ProfilePicker: material profile selection
  - RecipeBuilder: recipe creation, editing, and management

This tab replaces the modality_section as the Measurement Setup
sidebar entry.  It drives sidebar readiness indicators by computing
severity-per-tab from the pending actions list.

Signals
-------
    recipe_run(Recipe)
        Forwarded from RecipeBuilder when user clicks Run.
    navigate_requested(str, str)
        Forwarded from ReadinessPanel — (nav_target, tab_hint).
    readiness_changed(dict)
        Emitted when pending actions change.  Carries a severity_map
        ``{nav_label: severity_str}`` for sidebar indicator updates.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSplitter,
    QVBoxLayout, QWidget,
)

from ui.theme import FONT, PALETTE
from ui.widgets.readiness_panel import ReadinessPanel
from ui.widgets.recipe_builder import RecipeBuilder

from acquisition.recipe import Recipe, RecipeStore
from acquisition.readiness import evaluate_pending_actions, Severity

log = logging.getLogger(__name__)


def _compute_severity_map(actions: list) -> dict:
    """Compute highest severity per nav_target from pending actions.

    Returns a dict mapping nav_target label → highest severity string.
    Priority: blocking > review > info.
    """
    _ORDER = {"blocking": 0, "review": 1, "info": 2}
    result: Dict[str, str] = {}
    for a in actions:
        if not a.nav_target:
            continue
        existing = result.get(a.nav_target)
        if existing is None:
            result[a.nav_target] = a.severity
        elif _ORDER.get(a.severity, 9) < _ORDER.get(existing, 9):
            result[a.nav_target] = a.severity
    return result


class MeasurementSetupTab(QWidget):
    """Combined setup surface: readiness + profile + recipe editor."""

    recipe_run          = pyqtSignal(object)    # Recipe
    navigate_requested  = pyqtSignal(str, str)  # nav_target, tab_hint
    readiness_changed   = pyqtSignal(dict)      # severity_map

    def __init__(
        self,
        app_state: Any = None,
        store: Optional[RecipeStore] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._app_state = app_state
        self._store = store or RecipeStore()
        self._readiness_context: dict = {}
        self._current_recipe: Optional[Recipe] = None
        self._build()
        self._wire_signals()

        # Periodic readiness refresh (every 3 seconds)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_readiness)
        self._refresh_timer.start(3000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main horizontal split: readiness panel | recipe builder
        splitter = QSplitter(Qt.Horizontal)

        # ─── Left: Readiness panel ───
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8)
        left_lay.setSpacing(8)

        # Profile picker (compact)
        self._profile_section = QWidget()
        prof_lay = QVBoxLayout(self._profile_section)
        prof_lay.setContentsMargins(0, 0, 0, 0)
        prof_lay.setSpacing(4)

        prof_hdr = QLabel("Material Profile")
        prof_hdr.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['label']}pt; "
            f"font-weight:600;")
        prof_lay.addWidget(prof_hdr)

        try:
            from ui.widgets.profile_picker import ProfilePicker
            self._profile_picker = ProfilePicker()
            self._profile_picker.profile_selected.connect(
                self._on_profile_selected)
            prof_lay.addWidget(self._profile_picker)
        except Exception:
            # Fallback if ProfilePicker not available
            self._profile_picker = None
            fallback = QLabel("Profile selection unavailable")
            fallback.setStyleSheet(
                f"color:{PALETTE['textDim']}; font-size:{FONT['caption']}pt;")
            prof_lay.addWidget(fallback)

        left_lay.addWidget(self._profile_section)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{PALETTE['border']};")
        left_lay.addWidget(sep)

        # Readiness panel
        self._readiness_panel = ReadinessPanel()
        left_lay.addWidget(self._readiness_panel, 1)

        # Run button (prominent)
        self._run_btn = _RunButton()
        self._run_btn.clicked.connect(self._on_run)
        left_lay.addWidget(self._run_btn)

        splitter.addWidget(left)

        # ─── Right: Recipe builder ───
        self._recipe_builder = RecipeBuilder(store=self._store)
        splitter.addWidget(self._recipe_builder)

        splitter.setSizes([280, 600])
        root.addWidget(splitter)

    def _wire_signals(self):
        # Forward signals
        self._recipe_builder.recipe_run.connect(self.recipe_run)
        self._readiness_panel.navigate_requested.connect(
            self.navigate_requested)
        self._readiness_panel.action_dismissed.connect(
            self._on_action_dismissed)

    # ── Profile integration ────────────────────────────────────────

    def _on_profile_selected(self, profile):
        """Apply selected profile to the current recipe."""
        wc = self._recipe_builder._wc
        if wc is None:
            # Create a quick recipe from the profile
            from acquisition.profile_bridge import quick_recipe_from_profile
            wc = quick_recipe_from_profile(profile, self._store)
            self._recipe_builder.load_working_copy(wc)
        else:
            from acquisition.profile_bridge import apply_profile_to_recipe
            apply_profile_to_recipe(wc.recipe, profile)
            self._recipe_builder._populate_editor()

        self._current_recipe = wc.recipe
        self._refresh_readiness()

    # ── Readiness evaluation ───────────────────────────────────────

    def set_readiness_context(self, key: str, value: Any) -> None:
        """Update a readiness context value (e.g. focus_confirmed)."""
        self._readiness_context[key] = value
        self._refresh_readiness()

    def _refresh_readiness(self):
        """Re-evaluate pending actions and update the panel + indicators."""
        recipe = self._get_active_recipe()
        if recipe is None:
            self._readiness_panel.update_actions([])
            self.readiness_changed.emit({})
            self._run_btn.set_ready(True)
            return

        actions = evaluate_pending_actions(
            recipe, self._app_state, self._readiness_context)
        self._readiness_panel.update_actions(actions)

        severity_map = _compute_severity_map(actions)
        self.readiness_changed.emit(severity_map)

        has_blocking = any(a.severity == "blocking" for a in actions)
        self._run_btn.set_ready(not has_blocking)

    def _get_active_recipe(self) -> Optional[Recipe]:
        """Get the recipe currently loaded in the builder."""
        if self._current_recipe is not None:
            return self._current_recipe
        wc = self._recipe_builder._wc
        return wc.recipe if wc else None

    def _on_action_dismissed(self, action_id: str):
        """Handle dismissal of an informational action."""
        dismissed = self._readiness_context.get("dismissed_checks", set())
        dismissed.add(action_id)
        self._readiness_context["dismissed_checks"] = dismissed
        self._refresh_readiness()

    def _on_run(self):
        """Handle the Run button click."""
        recipe = self._get_active_recipe()
        if recipe:
            self.recipe_run.emit(recipe)

    # ── External API ───────────────────────────────────────────────

    def load_recipe(self, recipe: Recipe):
        """Load a recipe into the builder (e.g. from Library)."""
        from acquisition.working_copy import load_working_copy
        wc = load_working_copy(recipe, self._store)
        self._recipe_builder.load_working_copy(wc)
        self._current_recipe = recipe
        self._refresh_readiness()

    def load_working_copy(self, wc):
        """Load an external WorkingCopy (e.g. from Quick Recipe)."""
        self._recipe_builder.load_working_copy(wc)
        self._current_recipe = wc.recipe
        self._refresh_readiness()

    # ── Theme ─────────────────────────────────────────────────────

    def _apply_styles(self):
        self._readiness_panel._apply_styles()
        if hasattr(self._recipe_builder, '_apply_styles'):
            self._recipe_builder._apply_styles()
        if self._profile_picker and hasattr(self._profile_picker, '_apply_styles'):
            self._profile_picker._apply_styles()


# ── Run button ─────────────────────────────────────────────────────


class _RunButton(QWidget):
    """Prominent run button with ready/blocked state."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        self._btn = _StyledRunBtn("RUN")
        self._btn.clicked.connect(self.clicked)
        lay.addWidget(self._btn)
        self._ready = True

    def set_ready(self, ready: bool):
        self._ready = ready
        if ready:
            self._btn.setText("\u25b6  RUN")
            self._btn.setEnabled(True)
            self._btn.setStyleSheet(
                f"QPushButton {{ background:{PALETTE['accent']}; "
                f"color:{PALETTE['textOnAccent']}; font-weight:700; "
                f"font-size:{FONT['label']}pt; border-radius:4px; "
                f"padding:10px; }}"
                f"QPushButton:hover {{ background:{PALETTE['accentHover']}; }}")
        else:
            self._btn.setText("\u26d4  Not Ready")
            self._btn.setEnabled(False)
            self._btn.setStyleSheet(
                f"QPushButton {{ background:{PALETTE['surface2']}; "
                f"color:{PALETTE['textDim']}; font-weight:600; "
                f"font-size:{FONT['label']}pt; border-radius:4px; "
                f"padding:10px; border:1px solid {PALETTE['border']}; }}")


class _StyledRunBtn(QPushButton):
    """QPushButton subclass to avoid import issues."""
    pass


# Need QPushButton import for _StyledRunBtn
from PyQt5.QtWidgets import QPushButton  # noqa: E402
