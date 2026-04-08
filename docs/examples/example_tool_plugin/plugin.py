"""
Example Tool Plugin for SanjINSIGHT
====================================

This minimal plugin demonstrates how to create a Tool Panel plugin
that appears in the TOOLS section of the sidebar.

To install:
    1. Copy this folder to ~/.microsanj/plugins/sample-viewer/
    2. Ensure your license is "developer" tier or above
    3. Restart SanjINSIGHT

The plugin adds a "Sample Viewer" panel to the sidebar with a text
area for entering sample metadata and a button to save it.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout,
)
from PyQt5.QtCore import Qt

from plugins.base import ToolPanelPlugin, PluginContext
from ui.theme import PALETTE, FONT


class SampleViewerPlugin(ToolPanelPlugin):
    """A simple tool panel that lets the user enter sample metadata."""

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.logger.info("Sample Viewer plugin activated.")

    def deactivate(self) -> None:
        self.log.info("Sample Viewer plugin deactivated.")

    def create_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Sample Metadata")
        title.setStyleSheet(f"""
            font-size: {FONT.get('heading', 16)}px;
            font-weight: bold;
            color: {PALETTE['text']};
        """)
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "Enter notes about the sample under test. "
            "Data is saved to the plugin's data directory."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['textDim']};")
        layout.addWidget(desc)

        # Text area
        self._editor = QTextEdit()
        self._editor.setPlaceholderText("Sample ID, material, thickness...")
        self._editor.setStyleSheet(f"""
            QTextEdit {{
                background: {PALETTE['surface']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self._editor, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("Save Notes")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['accent']};
                color: {PALETTE['textOnAccent']};
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {PALETTE['accentHover']};
            }}
        """)
        save_btn.clicked.connect(self._save_notes)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        return panel

    def get_nav_label(self) -> str:
        return "Sample Viewer"

    def get_nav_icon(self) -> str:
        return "mdi.microscope"

    def _save_notes(self) -> None:
        """Save the editor contents to the plugin's data directory."""
        text = self._editor.toPlainText()
        out_path = self.context.data_dir / "sample_notes.txt"
        out_path.write_text(text, encoding="utf-8")
        self.log.info("Sample notes saved to %s", out_path)
