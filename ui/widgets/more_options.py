"""
ui/widgets/more_options.py  —  "More Options" disclosure panel

Extends CollapsiblePanel with per-section state persistence.

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


class MoreOptionsPanel(CollapsiblePanel):
    """CollapsiblePanel that remembers per-section toggle state.

    Parameters
    ----------
    title : str
        Header text (default ``"More Options"``).
    section_key : str
        Unique key for per-section state persistence.
        If empty, the panel won't remember its state.
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

        # Honour per-section saved state if available
        start_collapsed = True  # default: collapsed
        if section_key:
            saved = cfg_mod.get_pref(f"ui.more_options.{section_key}", None)
            if saved is not None:
                start_collapsed = not saved

        super().__init__(title, parent, start_collapsed=start_collapsed)

        # Persist toggle state
        self.btn.toggled.connect(self._on_user_toggle)

    # ── Internal ─────────────────────────────────────────────────────

    def _on_user_toggle(self, expanded: bool) -> None:
        """Save per-section expansion state."""
        if self._section_key:
            cfg_mod.set_pref(f"ui.more_options.{self._section_key}", expanded)
