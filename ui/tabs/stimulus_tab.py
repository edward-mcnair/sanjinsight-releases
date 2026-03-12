"""
ui/tabs/stimulus_tab.py

StimulusTab — unified hardware tab for FPGA modulation + Bias Source.

Replaces two separate sidebar entries ("FPGA" and "Bias Source") with a
single "Stimulus" entry.  Each sub-tab preserves its full existing UI.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QSizePolicy
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class StimulusTab(QWidget):
    """Stimulus control: FPGA modulation + Bias source as sub-tabs."""

    # Pass-through signals from inner tabs
    open_device_manager = pyqtSignal()

    def __init__(self, fpga_tab: QWidget, bias_tab: QWidget, parent=None):
        super().__init__(parent)
        self._fpga_tab = fpga_tab
        self._bias_tab = bias_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_qss())
        self._tabs.addTab(fpga_tab, "  Modulation")
        self._tabs.addTab(bias_tab, "  Bias Source")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        # Wire inner open_device_manager signals upward
        for tab in (fpga_tab, bias_tab):
            if hasattr(tab, "open_device_manager"):
                tab.open_device_manager.connect(self.open_device_manager)

    # ── Public API passthrough ────────────────────────────────────────

    def update_status(self, status) -> None:
        """Delegate to whichever inner tab cares about this status object."""
        if hasattr(self._fpga_tab, "update_status"):
            try:
                self._fpga_tab.update_status(status)
            except Exception:
                pass
        if hasattr(self._bias_tab, "update_status"):
            try:
                self._bias_tab.update_status(status)
            except Exception:
                pass

    def set_hardware_available(self, available: bool) -> None:
        for tab in (self._fpga_tab, self._bias_tab):
            if hasattr(tab, "set_hardware_available"):
                tab.set_hardware_available(available)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(self._tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.FPGA,  color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.BIAS,  color=PALETTE.get("textDim", "#8892aa"), size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)

    def _tab_qss(self) -> str:
        return _inner_tab_qss()


def _inner_tab_qss() -> str:
    P = PALETTE
    return f"""
        QTabWidget::pane {{
            border: none;
            background: {P.get('bg', '#12151f')};
        }}
        QTabBar::tab {{
            background: {P.get('surface2', '#20232e')};
            color: {P.get('textDim', '#8892aa')};
            border: none;
            border-right: 1px solid {P.get('border', '#2e3245')};
            padding: 6px 20px;
            font-size: {FONT['label']}pt;
        }}
        QTabBar::tab:selected {{
            background: {P.get('surface', '#1a1d28')};
            color: {P.get('text', '#dde3f2')};
            border-bottom: 2px solid {P.get('accent', '#00d4aa')};
        }}
        QTabBar::tab:hover:!selected {{
            background: {P.get('surfaceHover', '#262a38')};
            color: {P.get('text', '#dde3f2')};
        }}
    """
