"""
ui/guidance/cards.py  —  GuidanceCard / WorkflowFooter compatibility shims

The guided-mode card system has been replaced by the Recipe execution
model.  These stub widgets are instantiable (callers add them to
layouts) but render as invisible zero-height widgets.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget
from PyQt5.QtCore import pyqtSignal


class GuidanceCard(QFrame):
    """Invisible stub — accepts the original constructor signature.

    A QVBoxLayout is created so that callers who access ``.layout()``
    (e.g. to tweak margins) do not get ``None``.
    """

    dismissed = pyqtSignal(str)

    def __init__(
        self,
        card_id: str = "",
        title: str = "",
        body: str = "",
        *,
        step_number: int | None = None,
        target_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.card_id = card_id
        self.step_id = card_id
        self.target_widget = target_widget
        QVBoxLayout(self)  # ensure .layout() is never None
        self.setVisible(False)
        self.setMaximumHeight(0)

    def _apply_styles(self) -> None:
        pass


class WorkflowFooter(QFrame):
    """Invisible stub — accepts a list of (nav_target, label, hint)."""

    navigate_requested = pyqtSignal(str, str)

    def __init__(self, steps=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        QVBoxLayout(self)  # ensure .layout() is never None
        self.setVisible(False)
        self.setMaximumHeight(0)

    def _apply_styles(self) -> None:
        pass
