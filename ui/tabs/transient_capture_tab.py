"""
ui/tabs/transient_capture_tab.py

TransientCaptureTab — unified time-resolved acquisition tab.

Combines TransientTab (time-resolved pulsed capture) and MovieTab (burst/movie
capture) under a single "Transient" sidebar entry as sub-tabs.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore    import QSize

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon


class TransientCaptureTab(QWidget):
    """Transient capture: Time-Resolved + Burst/Movie as mode sub-tabs."""

    def __init__(self, transient_tab: QWidget, movie_tab: QWidget, parent=None):
        super().__init__(parent)
        self._transient_tab = transient_tab
        self._movie_tab     = movie_tab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._tabs.addTab(transient_tab, "  Time-Resolved")
        self._tabs.addTab(movie_tab,     "  Burst")
        self._apply_tab_icons()

        root.addWidget(self._tabs, 1)

    # ── Public API passthrough ────────────────────────────────────────

    def update_data(self, values, times_s, *args, **kwargs) -> None:
        if hasattr(self._transient_tab, "update_data"):
            self._transient_tab.update_data(values, times_s, *args, **kwargs)

    def _refresh_hw(self) -> None:
        if hasattr(self._transient_tab, "_refresh_hw"):
            self._transient_tab._refresh_hw()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.TRANSIENT, color=PALETTE.get("textDim", "#8892aa"), size=14),
            make_icon(IC.CAPTURE,   color=PALETTE.get("textDim", "#8892aa"), size=14),
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
