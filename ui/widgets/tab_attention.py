"""
ui/widgets/tab_attention.py  —  Section-tab attention badges

Provides a lightweight mixin for QTabWidget containers that draws
amber (review-suggested) or red (blocking-issue) pulsing dots on
individual tab labels.

Usage
-----
In any container tab class that has a ``self._tabs: QTabWidget``:

    from ui.widgets.tab_attention import TabAttentionMixin

    class StimulusTab(QWidget, TabAttentionMixin):
        def __init__(self):
            ...
            self._init_tab_attention(self._tabs)

    # Set amber (review suggested):
    self.set_tab_attention(0, "amber", "Prefilled from Measurement Setup")

    # Set red (blocking issue):
    self.set_tab_attention(1, "red", "Bias source disconnected")

    # Clear:
    self.set_tab_attention(0, None)

States
------
- None     — no badge (default)
- "amber"  — review suggested; slow subtle pulse (~2.5s cycle)
- "red"    — blocking issue;   faster pulse (~1.6s cycle)
"""
from __future__ import annotations

import math
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QEvent, QRect
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget, QTabWidget, QTabBar

from ui.theme import PALETTE

# ── Dot sizing ────────────────────────────────────────────────────────────
_DOT_SIZE = 10  # px diameter

# ── Pulse timing ──────────────────────────────────────────────────────────
_AMBER_PERIOD = 2.5   # seconds per full cycle
_RED_PERIOD   = 1.6   # seconds per full cycle
_OPACITY_MIN  = 0.40
_OPACITY_MAX  = 1.0

# ── Shared pulse timer ────────────────────────────────────────────────────
_tab_pulse_timer: Optional[QTimer] = None
_tab_pulse_overlays: list = []     # list of _AttentionOverlay instances


def _tab_pulse_tick() -> None:
    """Repaint all registered overlays that have active badges."""
    for overlay in _tab_pulse_overlays:
        if overlay.isVisible():
            overlay.update()


def _ensure_tab_pulse_timer() -> None:
    """Lazily create the shared 30fps pulse timer for tab badges."""
    global _tab_pulse_timer
    if _tab_pulse_timer is not None:
        return
    _tab_pulse_timer = QTimer()
    _tab_pulse_timer.setInterval(33)   # ~30 fps
    _tab_pulse_timer.timeout.connect(_tab_pulse_tick)
    _tab_pulse_timer.start()


def _pulse_opacity(period: float) -> float:
    """Compute current opacity for a given pulse period."""
    mid = (_OPACITY_MIN + _OPACITY_MAX) / 2
    amp = (_OPACITY_MAX - _OPACITY_MIN) / 2
    return mid + amp * math.sin(time.monotonic() * (2 * math.pi / period))


# ── Transparent overlay widget ────────────────────────────────────────────

class _AttentionOverlay(QWidget):
    """Transparent widget parented to a QTabBar that paints attention dots.

    Sits on top of the tab bar with ``WA_TransparentForMouseEvents`` so
    clicks pass straight through to the tabs underneath.  Resizes itself
    to match the tab bar whenever the tab bar changes geometry.
    """

    def __init__(self, tab_bar: QTabBar):
        super().__init__(tab_bar)
        self._tab_bar = tab_bar
        # tab_index → ("amber"|"red", tooltip_str)
        self._states: dict[int, tuple[str, str]] = {}

        # Transparent to mouse — clicks go to the tab bar
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # Match tab bar geometry now and on future resizes
        self._sync_geometry()
        tab_bar.installEventFilter(self)
        self.raise_()

    @property
    def has_active_badges(self) -> bool:
        return bool(self._states)

    def set_state(self, index: int, level: Optional[str],
                  tooltip: str = "") -> None:
        """Set or clear attention on a tab.

        level: None, "amber", or "red".
        """
        if level is None:
            self._states.pop(index, None)
        else:
            self._states[index] = (level, tooltip)

        # Manage pulse timer subscription
        if self.has_active_badges:
            _ensure_tab_pulse_timer()
            if self not in _tab_pulse_overlays:
                _tab_pulse_overlays.append(self)
        else:
            if self in _tab_pulse_overlays:
                _tab_pulse_overlays.remove(self)

        self.update()

    def _sync_geometry(self) -> None:
        """Resize overlay to match the tab bar."""
        self.setGeometry(self._tab_bar.rect())

    def eventFilter(self, obj, event) -> bool:
        """Track tab bar resize/move to keep overlay aligned."""
        if obj is self._tab_bar and event.type() in (
                QEvent.Resize, QEvent.Move, QEvent.LayoutRequest):
            self._sync_geometry()
            self.raise_()
        return False   # never consume events

    def paintEvent(self, event) -> None:
        if not self._states:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        for idx, (level, _tooltip) in self._states.items():
            if idx < 0 or idx >= self._tab_bar.count():
                continue

            rect: QRect = self._tab_bar.tabRect(idx)
            if rect.isEmpty():
                continue

            # Position: top-right corner of the tab, inset slightly
            dx = rect.right() - _DOT_SIZE - 4
            dy = rect.top() + 4

            # Choose colour and pulse rate
            if level == "red":
                color = QColor(PALETTE['danger'])
                opacity = _pulse_opacity(_RED_PERIOD)
            else:  # amber
                color = QColor(PALETTE['warning'])
                opacity = _pulse_opacity(_AMBER_PERIOD)

            p.setOpacity(opacity)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(dx, dy, _DOT_SIZE, _DOT_SIZE)

        p.setOpacity(1.0)
        p.end()


# ── Mixin ─────────────────────────────────────────────────────────────────

class TabAttentionMixin:
    """Mixin for container tabs that host a QTabWidget.

    Call ``_init_tab_attention(tabs)`` after creating the QTabWidget.
    Then use ``set_tab_attention(index, level, tooltip)`` to control badges.

    Clears on tab visit by default (amber only).
    """

    def _init_tab_attention(self, tabs: QTabWidget) -> None:
        """Install the attention overlay on *tabs*'s tab bar."""
        self._attn_overlay = _AttentionOverlay(tabs.tabBar())
        self._attn_tabs = tabs
        # Clear amber when user clicks to that tab
        tabs.currentChanged.connect(self._on_tab_visited)

    def set_tab_attention(
        self,
        tab_index: int,
        level: Optional[str],
        tooltip: str = "",
    ) -> None:
        """Set or clear an attention badge on a section tab.

        Parameters
        ----------
        tab_index : int
            Tab index in the QTabWidget.
        level : None | "amber" | "red"
            None clears the badge.
            "amber" = review suggested (clears on visit).
            "red" = blocking issue (clears only when resolved).
        tooltip : str
            Optional explanatory text.
        """
        if hasattr(self, "_attn_overlay"):
            self._attn_overlay.set_state(tab_index, level, tooltip)

    def _on_tab_visited(self, index: int) -> None:
        """Clear amber badge when user visits the tab.

        Red badges are NOT cleared on visit — they require the issue
        to actually be resolved.
        """
        if not hasattr(self, "_attn_overlay"):
            return
        state = self._attn_overlay._states.get(index)
        if state and state[0] == "amber":
            self._attn_overlay.set_state(index, None)
