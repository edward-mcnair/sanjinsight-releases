"""
ui/tabs/stimulus_tab.py

StimulusTab — unified hardware tab for FPGA modulation + Bias Source.

Replaces two separate sidebar entries ("FPGA" and "Bias Source") with a
single "Stimulus" entry.  Each sub-tab preserves its full existing UI.
"""
from __future__ import annotations

import logging

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon
from ui.widgets.tab_helpers import inner_tab_qss

log = logging.getLogger(__name__)


class StimulusTab(QWidget):
    """Stimulus control: FPGA modulation + Bias source + IV Sweep as sub-tabs."""

    # Pass-through signals from inner tabs
    open_device_manager = pyqtSignal()

    def __init__(self, fpga_tab: QWidget, bias_tab: QWidget, parent=None):
        super().__init__(parent)
        self._fpga_tab = fpga_tab
        self._bias_tab = bias_tab

        from ui.tabs.iv_sweep_tab import IVSweepTab
        self._iv_sweep_tab = IVSweepTab()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_qss())
        self._tabs.addTab(fpga_tab,              "  Modulation")
        self._tabs.addTab(bias_tab,              "  Bias Source")
        self._tabs.addTab(self._iv_sweep_tab,    "  IV Sweep")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        # Wire inner open_device_manager signals upward
        for tab in (fpga_tab, bias_tab):
            if hasattr(tab, "open_device_manager"):
                tab.open_device_manager.connect(self.open_device_manager)

    # ── Public API passthrough ────────────────────────────────────────

    def update_status(self, status) -> None:
        """Delegate to whichever inner tab cares about this status object."""
        for tab in (self._fpga_tab, self._bias_tab, self._iv_sweep_tab):
            if hasattr(tab, "update_status"):
                try:
                    tab.update_status(status)
                except Exception:
                    log.warning(
                        "StimulusTab.update_status: %s.update_status() raised",
                        type(tab).__name__, exc_info=True)

    def set_hardware_available(self, available: bool) -> None:
        for tab in (self._fpga_tab, self._bias_tab):
            if hasattr(tab, "set_hardware_available"):
                tab.set_hardware_available(available)

    def set_bias_driver(self, bias_driver, camera_driver=None, pipeline=None) -> None:
        """Wire bias/camera drivers into the IV Sweep sub-tab."""
        self._iv_sweep_tab.set_drivers(bias_driver, camera_driver, pipeline)

    # ── Attention dots ─────────────────────────────────────────────

    _TAB_BASE = {0: "  Modulation", 1: "  Bias Source", 2: "  IV Sweep"}
    _TAB_ICONS = {0: IC.FPGA, 1: IC.BIAS, 2: IC.IV_SWEEP}
    _DOT = "\u2009\u25cf"

    def set_tab_attention(self, tab_index: int, needs_attention: bool) -> None:
        """Show/hide a red attention dot on a sub-tab."""
        if tab_index < 0 or tab_index >= self._tabs.count():
            return
        base = self._TAB_BASE.get(tab_index, "")
        if needs_attention:
            self._tabs.setTabText(tab_index, base + self._DOT)
            icon_name = self._TAB_ICONS.get(tab_index)
            if icon_name:
                icon = make_icon(icon_name, color=PALETTE["danger"], size=14)
                if icon:
                    self._tabs.setTabIcon(tab_index, icon)
        else:
            self._tabs.setTabText(tab_index, base)
            self._apply_tab_icons()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(self._tab_qss())
        self._apply_tab_icons()
        for sub in (self._fpga_tab, self._bias_tab, self._iv_sweep_tab):
            if hasattr(sub, "_apply_styles"):
                sub._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.FPGA,     color=PALETTE["textDim"], size=14),
            make_icon(IC.BIAS,     color=PALETTE["textDim"], size=14),
            make_icon(IC.IV_SWEEP, color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)

    def _tab_qss(self) -> str:
        return _inner_tab_qss()


def _inner_tab_qss() -> str:
    return inner_tab_qss()
