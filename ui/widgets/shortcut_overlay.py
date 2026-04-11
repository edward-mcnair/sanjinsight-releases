"""
ui/widgets/shortcut_overlay.py  —  Keyboard shortcut reference overlay.

Shows a floating, semi-transparent card listing every keyboard shortcut
grouped by category.  The overlay is frameless and modal-less; it closes
when the user presses Escape or clicks outside the card.

Usage
-----
    from ui.widgets.shortcut_overlay import show_shortcut_overlay
    show_shortcut_overlay(parent_window)
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame,
)

from ui.theme import PALETTE, FONT
from ui.font_utils import mono_family_css


# ── Shortcut data ──────────────────────────────────────────────────────────────

# Each group is (header_label, [(key_string, description), ...])
_SHORTCUT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Sections  (Ctrl + number)", [
        ("Ctrl+1", "Measurement Setup"),
        ("Ctrl+2", "Stimulus"),
        ("Ctrl+3", "Timing"),
        ("Ctrl+4", "Live View"),
        ("Ctrl+5", "Focus & Stage"),
        ("Ctrl+6", "Signal Check"),
        ("Ctrl+7", "Capture"),
        ("Ctrl+8", "Calibration"),
        ("Ctrl+9", "Sessions"),
        ("Ctrl+0", "Settings"),
    ]),
    ("Acquisition", [
        ("F5",           "Run Acquisition Sequence"),
        ("Ctrl+F5",     "Start Live Stream"),
        ("F6",           "Stop Live Stream"),
        ("F7",           "Freeze / Resume"),
        ("F8",           "Run Analysis"),
        ("F9",           "Start / Stop Scan"),
        ("Ctrl+.",       "Emergency Stop"),
    ]),
    ("Navigation", [
        ("Ctrl+K",  "Command Palette"),
        ("Ctrl+`",  "Toggle Console"),
        ("Ctrl+D",  "Device Manager"),
        ("Ctrl+,",  "Settings (alt)"),
    ]),
    ("Profiles & Data", [
        ("Ctrl+S",       "Save Profile"),
        ("Ctrl+O",       "Open Profile"),
        ("Ctrl+Shift+H", "Hardware Setup"),
    ]),
    ("Help", [
        ("Ctrl+?",  "Show Shortcuts (this overlay)"),
        ("Escape",  "Close / Cancel"),
    ]),
]

# Split the groups into two columns for the layout
_LEFT_GROUPS  = _SHORTCUT_GROUPS[:2]   # Sections, Acquisition
_RIGHT_GROUPS = _SHORTCUT_GROUPS[2:]   # Navigation, Profiles, Help


# ── Internal helpers ───────────────────────────────────────────────────────────

def _make_group_widget(groups: list[tuple[str, list[tuple[str, str]]]]) -> QWidget:
    """Build a vertical column containing several shortcut groups."""
    col = QWidget()
    col.setObjectName("shortcutColumn")
    col.setStyleSheet("background:transparent;")
    layout = QVBoxLayout(col)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    accent   = PALETTE['accent']
    text_col = PALETTE['text']
    dim_col  = PALETTE['textDim']
    cap_pt   = FONT["caption"]
    body_pt  = FONT["body"]
    lbl_pt   = FONT["label"]
    mono_css = mono_family_css()

    for header, shortcuts in groups:
        grp = QWidget()
        grp.setStyleSheet("background:transparent;")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setContentsMargins(0, 0, 0, 0)
        grp_layout.setSpacing(4)

        # Section header
        hdr = QLabel(header.upper())
        hdr.setStyleSheet(
            f"color:{accent}; font-size:{lbl_pt}pt; font-weight:700;"
            f" letter-spacing:1px; background:transparent;"
        )
        grp_layout.addWidget(hdr)

        # Divider line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{PALETTE['border']}; background:{PALETTE['border']}; max-height:1px;")
        grp_layout.addWidget(line)
        grp_layout.addSpacing(2)

        # Shortcut rows
        for key_str, description in shortcuts:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 0, 4, 0)
            row_layout.setSpacing(8)

            key_lbl = QLabel(key_str)
            key_lbl.setStyleSheet(
                f"color:{text_col}; font-size:{cap_pt}pt; font-weight:600;"
                f" font-family:{mono_css}; background:{PALETTE['surface']};"
                f" border:1px solid {PALETTE['border']}; border-radius:3px;"
                f" padding:1px 5px;"
            )
            key_lbl.setFixedWidth(120)
            key_lbl.setAlignment(Qt.AlignCenter)

            arrow_lbl = QLabel("→")
            arrow_lbl.setStyleSheet(
                f"color:{dim_col}; font-size:{cap_pt}pt; background:transparent;"
            )
            arrow_lbl.setFixedWidth(14)

            desc_lbl = QLabel(description)
            desc_lbl.setStyleSheet(
                f"color:{text_col}; font-size:{body_pt}pt; background:transparent;"
            )

            row_layout.addWidget(key_lbl)
            row_layout.addWidget(arrow_lbl)
            row_layout.addWidget(desc_lbl, 1)

            grp_layout.addWidget(row)

        layout.addWidget(grp)

    layout.addStretch()
    return col


# ── Main dialog ────────────────────────────────────────────────────────────────

class ShortcutOverlay(QDialog):
    """Frameless, semi-transparent overlay that lists all keyboard shortcuts.

    Closes when Escape is pressed or when the user clicks outside the card.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent;")
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Outer layout fills the entire dialog (transparent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Dark card container
        self._card = QWidget(self)
        self._card.setObjectName("shortcutCard")
        self._card.setStyleSheet(
            "#shortcutCard {"
            f"  background: rgba({self._card_rgba()});"
            f"  border: 1px solid {PALETTE['border']};"
            "  border-radius: 10px;"
            "}"
        )

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(24, 18, 24, 22)
        card_layout.setSpacing(16)

        # Title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)

        title_lbl = QLabel("Keyboard Shortcuts")
        title_lbl.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt;"
            f" font-weight:700; background:transparent;"
        )

        close_btn = QPushButton("×")
        close_btn.setFlat(True)
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  color:{PALETTE['textDim']}; font-size:{FONT['heading']}pt;"
            f"  background:transparent; border:none;"
            f"}}"
            f"QPushButton:hover {{ color:{PALETTE['text']}; }}"
        )
        close_btn.clicked.connect(self.close)

        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        card_layout.addLayout(title_row)

        # Horizontal divider below title
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{PALETTE['border']}; background:{PALETTE['border']}; max-height:1px;")
        card_layout.addWidget(sep)

        # Two-column grid of shortcut groups
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(32)
        columns_layout.setContentsMargins(0, 0, 0, 0)

        columns_layout.addWidget(_make_group_widget(_LEFT_GROUPS),  1)
        columns_layout.addWidget(_make_group_widget(_RIGHT_GROUPS), 1)

        card_layout.addLayout(columns_layout)
        outer.addWidget(self._card)

    # ── Sizing and positioning ─────────────────────────────────────────────────

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._centre_on_parent()

    def _centre_on_parent(self) -> None:
        """Centre the overlay card over the parent window (or screen)."""
        self._card.adjustSize()
        # Add padding so the transparent dialog is large enough to detect
        # clicks outside the card
        pad = 200
        card_size = self._card.sizeHint()
        dialog_w = card_size.width()  + pad * 2
        dialog_h = card_size.height() + pad * 2

        # Position card inside the padded dialog
        self._card.setGeometry(pad, pad, card_size.width(), card_size.height())
        self.resize(dialog_w, dialog_h)

        parent = self.parent()
        if parent is not None:
            pg = parent.frameGeometry()
            cx = pg.left() + (pg.width()  - dialog_w) // 2
            cy = pg.top()  + (pg.height() - dialog_h) // 2
            self.move(cx, cy)

    # ── Event handlers ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _apply_styles(self):
        """Refresh the card's inline stylesheets from the current PALETTE."""
        self._card.setStyleSheet(
            "#shortcutCard {"
            f"  background: rgba({self._card_rgba()});"
            f"  border: 1px solid {PALETTE['border']};"
            "  border-radius: 10px;"
            "}"
        )

    @staticmethod
    def _card_rgba() -> str:
        """Return an rgba() string for the card background matching the theme."""
        # Dark theme: near-black card; light theme: white card
        bg = PALETTE['bg']
        # Parse hex to r,g,b
        bg = bg.lstrip('#')
        r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
        return f"{r}, {g}, {b}, 0.96"

    def mousePressEvent(self, event):  # noqa: N802
        """Close the overlay when the user clicks on the transparent backdrop."""
        if not self._card.geometry().contains(event.pos()):
            self.close()
        else:
            super().mousePressEvent(event)


# ── Factory function ───────────────────────────────────────────────────────────

def show_shortcut_overlay(parent: QWidget | None = None) -> ShortcutOverlay:
    """Create and show the shortcut overlay in a non-blocking (modal-less) way.

    Returns the overlay instance so the caller can connect signals if needed.
    """
    overlay = ShortcutOverlay(parent)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    return overlay
