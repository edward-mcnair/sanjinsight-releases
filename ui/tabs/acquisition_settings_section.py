"""
ui/tabs/acquisition_settings_section.py  —  Acquisition settings section

Frame count, exposure, gain, averaging mode, quality gating.
Phase 1 · CONFIGURATION

TODO: Full implementation in Phase 4.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


class AcquisitionSettingsSection(QWidget):
    """Placeholder for the Acquisition Settings section."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Acquisition Settings")
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['heading']}pt; "
            "font-weight: bold;")
        lay.addWidget(title)

        desc = QLabel(
            "Frame count, exposure, gain, averaging mode, and quality gating.\n\n"
            "This section is under construction.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['textDim']};")
        lay.addWidget(desc)
        lay.addStretch()

    def _apply_styles(self) -> None:
        self.update()
