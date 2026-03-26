"""
ui/widgets/more_options.py  —  Workspace-aware "More Options" disclosure panel

Extends CollapsiblePanel to respect the active workspace mode:

    Guided   → always starts collapsed
    Standard → remembers user's per-section toggle state
    Expert   → always starts expanded

Usage
-----
    from ui.widgets.more_options import MoreOptionsPanel

    opts = MoreOptionsPanel(section_key="stimulus")
    opts.addWidget(voltage_limit_spinbox)
    opts.addWidget(waveform_selector)
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget

import config as cfg_mod
from ui.widgets.collapsible_panel import CollapsiblePanel
from ui.workspace import get_manager, WorkspaceMode


class MoreOptionsPanel(CollapsiblePanel):
    """CollapsiblePanel whose default state adapts to the workspace mode.

    Parameters
    ----------
    title : str
        Header text (default ``"More Options"``).
    section_key : str
        Unique key for per-section state persistence in Standard mode.
        If empty, the panel won't remember its state across mode switches.
    parent : QWidget | None
        Parent widget.
    """

    def __init__(
        self,
        title: str = "More Options",
        section_key: str = "",
        parent: QWidget | None = None,
    ) -> None:
        self._section_key = section_key
        manager = get_manager()

        # Determine initial collapsed state based on workspace mode
        start_collapsed = not manager.more_options_default_expanded()

        # In Standard mode, honour per-section saved state if available
        if manager.mode == WorkspaceMode.STANDARD and section_key:
            saved = cfg_mod.get_pref(f"ui.more_options.{section_key}", None)
            if saved is not None:
                start_collapsed = not saved

        super().__init__(title, parent, start_collapsed=start_collapsed)

        # Persist toggle state in Standard mode
        self.btn.toggled.connect(self._on_user_toggle)

        # React to workspace mode changes
        manager.mode_changed.connect(self._on_mode_changed)

    # ── Internal ─────────────────────────────────────────────────────

    def _on_user_toggle(self, expanded: bool) -> None:
        """Save per-section expansion state for Standard mode recall."""
        if self._section_key and get_manager().mode == WorkspaceMode.STANDARD:
            cfg_mod.set_pref(f"ui.more_options.{self._section_key}", expanded)

    def _on_mode_changed(self, mode: str) -> None:
        """Adjust expansion state when the workspace mode switches."""
        if mode == WorkspaceMode.EXPERT:
            # Expert: force expand
            if not self.btn.isChecked():
                self.btn.setChecked(True)
        elif mode == WorkspaceMode.GUIDED:
            # Guided: force collapse
            if self.btn.isChecked():
                self.btn.setChecked(False)
        else:
            # Standard: restore saved state or leave as-is
            if self._section_key:
                saved = cfg_mod.get_pref(
                    f"ui.more_options.{self._section_key}", None)
                if saved is not None:
                    self.btn.setChecked(saved)
