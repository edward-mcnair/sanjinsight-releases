"""
ui/tabs/capture_tab.py

CaptureTab — unified acquisition tab: Single Capture + Grid Scan.

Combines AcquireTab (single-point acquisition) and ScanTab (spatial scan)
under one sidebar entry with "Single" / "Grid" mode tabs.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import pyqtSignal, QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class CaptureTab(QWidget):
    """Capture: Single-point (Acquire) and Grid Scan as mode tabs."""

    # Pass-through from AcquireTab
    acquire_requested = pyqtSignal(int, float)   # n_frames, inter_phase_delay

    def __init__(self, acquire_tab: QWidget, scan_tab: QWidget, parent=None):
        super().__init__(parent)
        self._acquire_tab = acquire_tab
        self._scan_tab    = scan_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._tabs.addTab(acquire_tab, "  Single")
        self._tabs.addTab(scan_tab,    "  Grid")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

        if hasattr(acquire_tab, "acquire_requested"):
            acquire_tab.acquire_requested.connect(self.acquire_requested)

    # ── Public API passthrough ────────────────────────────────────────

    def update_live(self, frame) -> None:
        if hasattr(self._acquire_tab, "update_live"):
            self._acquire_tab.update_live(frame)

    def update_progress(self, p) -> None:
        if hasattr(self._acquire_tab, "update_progress"):
            self._acquire_tab.update_progress(p)

    def update_result(self, result) -> None:
        if hasattr(self._acquire_tab, "update_result"):
            self._acquire_tab.update_result(result)

    def set_active_recipe_name(self, name: str) -> None:
        if hasattr(self._acquire_tab, "set_active_recipe_name"):
            self._acquire_tab.set_active_recipe_name(name)

    def set_n_frames(self, n: int) -> None:
        if hasattr(self._acquire_tab, "set_n_frames"):
            self._acquire_tab.set_n_frames(n)

    def get_notes(self) -> str:
        if hasattr(self._acquire_tab, "get_notes"):
            return self._acquire_tab.get_notes()
        return ""

    def insert_readiness_widget(self, widget: QWidget) -> None:
        if hasattr(self._acquire_tab, "insert_readiness_widget"):
            self._acquire_tab.insert_readiness_widget(widget)

    def start_acquisition(self, *args, **kwargs) -> None:
        if hasattr(self._acquire_tab, "start_acquisition"):
            self._acquire_tab.start_acquisition(*args, **kwargs)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()
        for sub in (self._acquire_tab, self._scan_tab):
            if hasattr(sub, "_apply_styles"):
                sub._apply_styles()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.CAPTURE,   color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.SCAN_GRID, color=PALETTE.get("textDim", "#8892aa"), size=14),
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
