"""
ui/tabs/modality_section.py  —  Modality configuration section

Camera selection, objective, FOV, measurement mode.
Phase 1 · CONFIGURATION

TODO: Full implementation in Phase 4.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


class ModalitySection(QWidget):
    """Placeholder for the Modality configuration section."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Modality")
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['heading']}pt; "
            "font-weight: bold;")
        lay.addWidget(title)

        desc = QLabel(
            "Camera selection, objective, field of view, and measurement mode.\n\n"
            "This section is under construction.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['textDim']};")
        lay.addWidget(desc)
        lay.addStretch()

    def _apply_styles(self) -> None:
        self.update()
