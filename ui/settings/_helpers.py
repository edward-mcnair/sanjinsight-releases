"""
ui/settings/_helpers.py

Shared style constants and widget factories for settings sections.

All settings section modules import these helpers rather than
duplicating inline QSS templates.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QFrame, QGroupBox

from ui.theme import FONT, PALETTE


# ── Palette accessor lambdas (read live PALETTE on each call) ─────────────
_BG       = lambda: PALETTE['bg']
_BG2      = lambda: PALETTE['surface']
_BORDER   = lambda: PALETTE['border']
_TEXT     = lambda: PALETTE['text']
_MUTED    = lambda: PALETTE['textSub']
_ACCENT   = lambda: PALETTE['accent']
_ACCENT_H = lambda: PALETTE['accentHover']
_GREEN    = lambda: PALETTE['accent']
_AMBER    = lambda: PALETTE['warning']
_DANGER   = lambda: PALETTE['danger']


# ── Reusable QSS snippets ────────────────────────────────────────────────

def BTN_PRIMARY() -> str:
    return f"""
    QPushButton {{
        background:{_ACCENT()}; color:{PALETTE['textOnAccent']}; border:none;
        border-radius:5px; padding:7px 18px; font-size:{FONT["label"]}pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:{_ACCENT_H()}; }}
    QPushButton:pressed {{ background:{_ACCENT()}; }}
    QPushButton:disabled{{ background:{_BG2()}; color:{_MUTED()}; }}
"""


def BTN_SECONDARY() -> str:
    return f"""
    QPushButton {{
        background:{_BG2()}; color:{_MUTED()}; border:1px solid {_BORDER()};
        border-radius:5px; padding:7px 18px; font-size:{FONT["label"]}pt;
    }}
    QPushButton:hover   {{ background:{_BG2()}; color:{_TEXT()}; border-color:{_BORDER()}; }}
    QPushButton:pressed {{ background:{_BG()}; }}
"""


def COMBO() -> str:
    return f"""
    QComboBox {{
        background:{_BG2()}; color:{_TEXT()}; border:1px solid {_BORDER()};
        border-radius:4px; padding:5px 10px; font-size:{FONT["label"]}pt;
    }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{ background:{_BG2()}; color:{_TEXT()}; border:1px solid {_BORDER()}; }}
"""


def CHECK() -> str:
    return f"""
    QCheckBox {{ color:{_TEXT()}; font-size:{FONT["label"]}pt; spacing:8px; }}
    QCheckBox::indicator {{
        width:18px; height:18px; border-radius:3px;
        border:1px solid {_BORDER()}; background:{_BG2()};
    }}
    QCheckBox::indicator:checked {{
        background:{_ACCENT()}; border-color:{_ACCENT()};
    }}
"""


# ── Widget factories ─────────────────────────────────────────────────────

def h2(text: str) -> QLabel:
    """Section sub-heading (bold, body-size)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size:{FONT['body']}pt; font-weight:700; color:{_TEXT()};")
    return lbl


def body(text: str) -> QLabel:
    """Secondary body text (muted, word-wrapped)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
    lbl.setWordWrap(True)
    return lbl


def sep() -> QFrame:
    """Horizontal separator line."""
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{_BORDER()};")
    return f


def group(title: str) -> QGroupBox:
    """Create a QGroupBox — styling applied by parent _apply_styles()."""
    return QGroupBox(title)


def segmented_base_qss() -> str:
    """Base QSS for Auto/Dark/Light and similar segmented controls."""
    return (
        f"QPushButton {{"
        f" background:{PALETTE['surface2']};"
        f" color:{PALETTE['textDim']};"
        f" border:1px solid {PALETTE['border']};"
        f" padding:5px 0; font-size:{FONT['label']}pt;"
        f"}}"
        f"QPushButton:checked {{"
        f" background:{_ACCENT()}; color:{PALETTE['textOnAccent']}; border-color:{_ACCENT()};"
        f"}}"
    )
