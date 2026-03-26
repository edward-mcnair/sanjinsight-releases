"""
ui/tabs/signal_check_section.py  —  Signal check section

SNR readout, saturation check, histogram, signal verification.
Phase 2 · IMAGE ACQUISITION

TODO: Full implementation in Phase 4.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from ui.theme import PALETTE, FONT


class SignalCheckSection(QWidget):
    """Placeholder for the Signal Check section."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Signal Check")
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: {FONT['heading']}pt; "
            "font-weight: bold;")
        lay.addWidget(title)

        desc = QLabel(
            "Signal-to-noise readout, saturation check, and signal verification.\n\n"
            "This section is under construction.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['textDim']};")
        lay.addWidget(desc)
        lay.addStretch()

    def _apply_styles(self) -> None:
        self.update()
