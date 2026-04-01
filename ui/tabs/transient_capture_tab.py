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

    # ── Attention dots ─────────────────────────────────────────────

    _TAB_BASE = {0: "  Time-Resolved", 1: "  Burst"}
    _TAB_ICONS = {0: IC.TRANSIENT, 1: IC.CAPTURE}
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
        self._tabs.setStyleSheet(_inner_tab_qss())
        self._apply_tab_icons()

    def _apply_tab_icons(self) -> None:
        icons = [
            make_icon(IC.TRANSIENT, color=PALETTE["textDim"], size=14),
            make_icon(IC.CAPTURE,   color=PALETTE["textDim"], size=14),
        ]
        self._tabs.setIconSize(QSize(14, 14))
        for i, icon in enumerate(icons):
            if icon:
                self._tabs.setTabIcon(i, icon)


def _inner_tab_qss() -> str:
    P = PALETTE
    return f"""
        QTabWidget::pane {{ border:none; background:{P['bg']}; }}
        QTabBar::tab {{
            background:{P['surface2']}; color:{P['textDim']};
            border:none; border-right:1px solid {P['border']};
            padding:6px 20px; font-size:{FONT['label']}pt;
        }}
        QTabBar::tab:selected {{
            background:{P['surface']}; color:{P['text']};
            border-bottom:2px solid {P['accent']};
        }}
        QTabBar::tab:hover:!selected {{
            background:{P['surfaceHover']}; color:{P['text']};
        }}
    """
