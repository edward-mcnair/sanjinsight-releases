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
from ui.widgets.tab_helpers import inner_tab_qss
from ui.widgets.tab_attention import TabAttentionMixin


class CameraControlTab(QWidget, TabAttentionMixin):
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
        self._tabs.setStyleSheet(inner_tab_qss())
        self._tabs.addTab(camera_tab,    "Camera")
        self._tabs.addTab(roi_tab,       "ROI")
        self._tabs.addTab(autofocus_tab, "Autofocus")
        self._apply_tab_icons()
        self._init_tab_attention(self._tabs)

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

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(inner_tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.CAMERA,    color=PALETTE["textDim"], size=14),
            make_icon(IC.ROI,       color=PALETTE["textDim"], size=14),
            make_icon(IC.AUTOFOCUS, color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)
