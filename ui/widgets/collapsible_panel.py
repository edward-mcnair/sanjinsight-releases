"""
ui/widgets/collapsible_panel.py

CollapsiblePanel  —  a titled container the user can expand or collapse.

Usage
-----
    from ui.widgets.collapsible_panel import CollapsiblePanel

    panel = CollapsiblePanel("Advanced settings", start_collapsed=True)
    panel.addWidget(some_widget)
    panel.addLayout(some_layout)
    some_layout.addWidget(panel)
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


class CollapsiblePanel(QWidget):
    """
    A titled container that the user can expand or collapse by clicking
    the header row.

    start_collapsed=True  (default) means content is hidden on creation.
    """

    def __init__(
        self,
        title: str = "Advanced settings",
        parent: QWidget = None,
        start_collapsed: bool = True,
    ):
        super().__init__(parent)

        # ── Toggle button (acts as the header row) ────────────────────
        self.btn = QToolButton(text=f"  {title}")
        self.btn.setCheckable(True)
        self.btn.setChecked(not start_collapsed)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(
            Qt.DownArrow if not start_collapsed else Qt.RightArrow)
        self.btn.setStyleSheet(f"""
            QToolButton {{
                color: {PALETTE["textDim"]};
                border: none;
                font-size: {FONT["sublabel"]}pt;
                padding: 4px 0;
                background: transparent;
            }}
            QToolButton:hover   {{ color: {PALETTE["text"]}; }}
            QToolButton:checked {{ color: {PALETTE["text"]}; }}
        """)

        # ── Content frame ─────────────────────────────────────────────
        self.content = QFrame()
        self.content.setFrameShape(QFrame.NoFrame)
        # QSizePolicy.Preferred (not Fixed) so the frame grows with its children
        self.content.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 4, 0, 0)
        self.content_layout.setSpacing(6)

        # ── Outer layout ──────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.btn)
        root.addWidget(self.content)

        self.btn.toggled.connect(self._on_toggle)
        self._on_toggle(self.btn.isChecked())

    # ── Public API ────────────────────────────────────────────────────

    def addWidget(self, widget: QWidget) -> None:
        """Add a widget to the collapsible content area."""
        self.content_layout.addWidget(widget)

    def addLayout(self, layout) -> None:
        """Add a layout to the collapsible content area."""
        self.content_layout.addLayout(layout)

    # ── Internal ──────────────────────────────────────────────────────

    def _on_toggle(self, expanded: bool) -> None:
        self.btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)
