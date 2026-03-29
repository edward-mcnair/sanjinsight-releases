"""
ui/tabs/camera_control_tab.py

CameraControlTab — unified Camera hardware tab.

Combines Camera (live view + controls), ROI, and Autofocus into a single
sidebar entry, each as a sub-tab.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class CameraControlTab(QWidget):
    """Camera controls: Camera view, ROI selection, Autofocus — sub-tabs."""

    open_device_manager = pyqtSignal()

    def __init__(self, camera_tab: QWidget, roi_tab: QWidget,
                 autofocus_tab: QWidget, parent=None):
        super().__init__(parent)
        self._camera_tab   = camera_tab
        self._roi_tab      = roi_tab
        self._autofocus_tab = autofocus_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._tabs.addTab(camera_tab,    "  Camera")
        self._tabs.addTab(roi_tab,       "  ROI")
        self._tabs.addTab(autofocus_tab, "  Autofocus")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        if hasattr(camera_tab, "open_device_manager"):
            camera_tab.open_device_manager.connect(self.open_device_manager)

    # ── Public API passthrough ────────────────────────────────────────

    def update_frame(self, frame) -> None:
        """Feed live frame to Camera and ROI sub-tabs."""
        if hasattr(self._camera_tab, "update_frame"):
            self._camera_tab.update_frame(frame)
        if hasattr(self._roi_tab, "update_frame"):
            self._roi_tab.update_frame(frame.data if hasattr(frame, "data") else frame)

    def set_exposure(self, us: float) -> None:
        if hasattr(self._camera_tab, "set_exposure"):
            self._camera_tab.set_exposure(us)

    def set_gain(self, db: float) -> None:
        if hasattr(self._camera_tab, "set_gain"):
            self._camera_tab.set_gain(db)

    # ── Attention dots ─────────────────────────────────────────────

    _TAB_BASE = {0: "  Camera", 1: "  ROI", 2: "  Autofocus"}
    _TAB_ICONS = {0: IC.CAMERA, 1: IC.ROI, 2: IC.AUTOFOCUS}
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
                icon = make_icon(icon_name, color=PALETTE.get("error", "#ff453a"), size=14)
                if icon:
                    self._tabs.setTabIcon(tab_index, icon)
        else:
            self._tabs.setTabText(tab_index, base)
            self._apply_tab_icons()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.CAMERA,    color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.ROI,       color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.AUTOFOCUS, color=PALETTE.get("textDim", "#8892aa"), size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)


def _inner_tab_qss() -> str:
    P = PALETTE
    return f"""
        QTabWidget::pane {{ border:none; background:{P.get('bg','#12151f')}; }}
        QTabBar::tab {{
            background:{P.get('surface2','#20232e')}; color:{P.get('textDim','#8892aa')};
            border:none; border-right:1px solid {P.get('border','#2e3245')};
            padding:6px 20px; font-size:{FONT['label']}pt;
        }}
        QTabBar::tab:selected {{
            background:{P.get('surface','#1a1d28')}; color:{P.get('text','#dde3f2')};
            border-bottom:2px solid {P.get('accent','#00d4aa')};
        }}
        QTabBar::tab:hover:!selected {{
            background:{P.get('surfaceHover','#262a38')}; color:{P.get('text','#dde3f2')};
        }}
    """
