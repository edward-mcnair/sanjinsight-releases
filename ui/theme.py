"""
ui/theme.py  —  Single source of truth for SanjINSIGHT visual design.

Import this module anywhere you need colours, font sizes, or QSS strings.
Never hardcode hex colour values or font sizes outside this module.

Quick reference
---------------
    from ui.theme import PALETTE, FONT, btn_primary_qss, groupbox_qss

    lbl.setStyleSheet(f"color:{PALETTE['accent']}; font-size:{FONT['body']}pt;")
    btn.setStyleSheet(btn_primary_qss())
"""

from __future__ import annotations

import sys as _sys

# ── Colour palette ─────────────────────────────────────────────────────────────

PALETTE: dict = {
    # Backgrounds
    "bg":       "#0e1120",   # main window / deepest background
    "surface":  "#1a1a1a",   # panels, sidebar, cards
    "surface2": "#141414",   # list items, slightly darker
    "surface3": "#111111",   # header bar, input fields
    # Borders
    "border":   "#2a2a2a",   # standard panel borders
    "border2":  "#1e2337",   # wizard / first-run borders
    # Text
    "text":     "#c0c8e0",   # primary text
    "textDim":  "#888888",   # secondary / muted  (WCAG AA on #1a1a1a ✓)
    "textSub":  "#5a6480",   # hint / caption
    # Accents
    "accent":   "#00d4aa",   # teal primary
    "accentDim":"#00d4aa44", # teal @ 27 % opacity
    # Semantic
    "success":  "#00d4aa",
    "warning":  "#ffaa44",   # amber
    "danger":   "#ff5555",   # red
    "info":     "#6699ff",   # blue
    # Readiness widget
    "readyBg":      "#0d2b22",
    "readyBorder":  "#00d4aa",
    "warnBg":       "#2b1e0a",
    "warnBorder":   "#ffaa44",
    "errorBg":      "#2b0a0a",
    "errorBorder":  "#ff6666",
    "unknownBg":    "#181818",
    "unknownBorder":"#333333",
}


# ── Font scale (pt sizes) ──────────────────────────────────────────────────────
#
# All values are the macOS 72-DPI baseline.  apply_dpi_scale() rescales them
# to match the real screen DPI once QApplication has been created.
#
# Design rationale
# ----------------
# Qt converts stylesheet `pt` values to pixels using the screen logical DPI.
# macOS uses 72 DPI as its baseline, so "13pt" is 13 logical pixels.
# Windows/Linux use 96 DPI, making "13pt" render as ~17 px — 33 % larger.
# The fix: query the real logical DPI after QApplication is created and scale
# all FONT values by 72 / logical_dpi (clamped to [0.5, 1.0]).
# With AA_EnableHighDpiScaling active, logical DPI is always the *unscaled*
# DPI (e.g. 96 on a 200%-scaled 4K Windows display), so one scale factor
# handles both standard- and high-DPI cases correctly.

_FONT_BASE: dict = {
    "title":     17,   # sidebar app name / wizard h1
    "heading":   14,   # panel section headings
    "body":      13,   # general text, buttons, inputs
    "label":     12,   # form row labels
    "sublabel":  11,   # secondary / dim sub-labels
    "caption":   10,   # hints, badges, inline notes
    "readout":   22,   # big status readout values
    "readoutLg": 26,   # large readout (e.g. temperature actual)
    "readoutSm": 16,   # compact readout (e.g. exposure/gain value labels)
    "mono":      13,   # monospace values (SNR, frame stats)
}

# Pre-computed best-guess scale before QApplication / QScreen is available.
# apply_dpi_scale() is called from main() with the real screen DPI and
# overwrites both this variable and the FONT dict.
_DPI_SCALE: float = 1.0 if _sys.platform == "darwin" else 72.0 / 96.0


def apply_dpi_scale(scale: float) -> None:
    """Update FONT in-place using the real screen DPI scale factor.

    Call once, right after ``QApplication`` is created:

        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)
        from ui.theme import apply_dpi_scale
        apply_dpi_scale(72.0 / app.primaryScreen().logicalDotsPerInch())

    All QSS helpers (btn_primary_qss, etc.) read from FONT at call time, so
    any widget constructed *after* this call automatically gets the right sizes.
    """
    global _DPI_SCALE
    _DPI_SCALE = scale
    for k, v in _FONT_BASE.items():
        FONT[k] = max(8, int(round(v * scale)))


# FONT is initialised with the best-guess platform scale; apply_dpi_scale()
# will refine it once the real screen DPI is known.
FONT: dict = {k: max(8, int(round(v * _DPI_SCALE))) for k, v in _FONT_BASE.items()}


def scaled_qss(qss: str) -> str:
    """Scale every ``font-size: Npt`` token in a QSS string by the current DPI scale.

    Use this when a widget builds its own stylesheet with hardcoded pt values
    so the sizes stay consistent with the DPI-scaled global STYLE applied in
    ``main()``.  On macOS (scale = 1.0) the string is returned unchanged with
    zero regex overhead.

    Example::

        self.setStyleSheet(scaled_qss(\"\"\"
            QLabel { font-size: 13pt; color: #ccc; }
            QPushButton { font-size: 12pt; }
        \"\"\"))

    The base pt values should always be the macOS 72-DPI baseline (i.e. the
    same values stored in ``_FONT_BASE``).
    """
    if _DPI_SCALE == 1.0:
        return qss
    import re as _re
    return _re.sub(
        r'font-size:\s*(\d+)pt',
        lambda m: f"font-size:{max(8, int(round(int(m.group(1)) * _DPI_SCALE)))}pt",
        qss,
    )


# ── QPalette builder ───────────────────────────────────────────────────────────

def build_qt_palette():
    """Return a QPalette for the dark Fusion theme (call once at app startup)."""
    from PyQt5.QtGui import QPalette, QColor
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(PALETTE["bg"]))
    p.setColor(QPalette.WindowText,      QColor(PALETTE["text"]))
    p.setColor(QPalette.Base,            QColor(PALETTE["surface3"]))
    p.setColor(QPalette.AlternateBase,   QColor(PALETTE["surface"]))
    p.setColor(QPalette.ToolTipBase,     QColor(PALETTE["accent"]))
    p.setColor(QPalette.ToolTipText,     QColor(PALETTE["bg"]))
    p.setColor(QPalette.Text,            QColor(PALETTE["text"]))
    p.setColor(QPalette.Button,          QColor(PALETTE["surface"]))
    p.setColor(QPalette.ButtonText,      QColor(PALETTE["text"]))
    p.setColor(QPalette.BrightText,      QColor(PALETTE["accent"]))
    p.setColor(QPalette.Link,            QColor(PALETTE["info"]))
    p.setColor(QPalette.Highlight,       QColor(PALETTE["info"]))
    p.setColor(QPalette.HighlightedText, QColor(PALETTE["bg"]))
    return p


# ── QSS helpers ────────────────────────────────────────────────────────────────

def btn_primary_qss() -> str:
    """Teal primary action button (Save, Run, Apply…)."""
    b = FONT["body"]
    return f"""
    QPushButton {{
        background:#006b40; color:#fff; border:none; border-radius:4px;
        padding:5px 16px; font-size:{b}pt; font-weight:600;
    }}
    QPushButton:hover    {{ background:#008050; }}
    QPushButton:pressed  {{ background:#005030; }}
    QPushButton:disabled {{ background:#1e2e2a; color:#444; }}
    """


def btn_wizard_primary_qss() -> str:
    """Blue primary button used in the first-run wizard."""
    b = FONT["body"]
    return f"""
    QPushButton {{
        background:#4e73df; color:#fff; border:none; border-radius:6px;
        padding:8px 22px; font-size:{b}pt; font-weight:600;
    }}
    QPushButton:hover    {{ background:#3a5fc8; }}
    QPushButton:pressed  {{ background:#2e4fa8; }}
    QPushButton:disabled {{ background:#333;    color:#666; }}
    """


def btn_secondary_qss() -> str:
    """Muted secondary button."""
    b = FONT["body"]
    s, d, t = PALETTE["surface"], PALETTE["border"], PALETTE["textDim"]
    return f"""
    QPushButton {{
        background:{s}; color:{t}; border:1px solid {d}; border-radius:4px;
        padding:5px 16px; font-size:{b}pt;
    }}
    QPushButton:hover    {{ background:#252525; color:{PALETTE["text"]}; }}
    QPushButton:pressed  {{ background:#111; }}
    """


def btn_wizard_secondary_qss() -> str:
    b = FONT["body"]
    return f"""
    QPushButton {{
        background:#1e2337; color:#aaa; border:1px solid #333;
        border-radius:6px; padding:8px 22px; font-size:{b}pt;
    }}
    QPushButton:hover    {{ background:#2a3249; color:#ccc; }}
    QPushButton:pressed  {{ background:#1a1f33; }}
    """


def btn_danger_qss() -> str:
    b = FONT["body"]
    return f"""
    QPushButton {{
        background:#330a0a; color:{PALETTE["danger"]};
        border:1px solid #aa2222; border-radius:4px;
        padding:5px 16px; font-size:{b}pt; font-weight:600;
    }}
    QPushButton:hover    {{ background:#440e0e; }}
    QPushButton:pressed  {{ background:#220808; }}
    """


def input_qss() -> str:
    """Standard spinbox / line-edit / combo stylesheet."""
    s3, bdr, txt, b = PALETTE["surface3"], PALETTE["border"], PALETTE["text"], FONT["body"]
    return f"""
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background:{s3}; color:{txt}; border:1px solid {bdr}; border-radius:3px;
        padding:3px 6px; font-size:{b}pt;
        selection-background-color:{PALETTE["info"]};
    }}
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
        border-color:{PALETTE["accent"]};
    }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{
        background:{s3}; color:{txt}; border:1px solid {bdr};
    }}
    """


def wizard_input_qss() -> str:
    """Input style for the first-run wizard (blue focus accent)."""
    b = FONT["body"]
    return f"""
    QLineEdit, QComboBox {{
        background:#13172a; color:#ddd; border:1px solid #2a3249;
        border-radius:4px; padding:5px 10px; font-size:{b}pt;
        selection-background-color:#4e73df;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color:#4e73df; }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{
        background:#13172a; color:#ddd; border:1px solid #2a3249;
    }}
    """


def groupbox_qss() -> str:
    """Standard GroupBox border + title style."""
    d, td, b = PALETTE["border"], PALETTE["textDim"], FONT["label"]
    return f"""
    QGroupBox {{
        color:{td}; font-size:{b}pt;
        border:1px solid {d}; border-radius:4px; margin-top:6px;
    }}
    QGroupBox::title {{
        subcontrol-origin:margin; subcontrol-position:top left;
        padding:0 4px; left:8px;
    }}
    """


def progress_bar_qss() -> str:
    """Teal QProgressBar with dark background (used across all tabs)."""
    s3, bdr, acc = PALETTE["surface3"], PALETTE["border"], PALETTE["accent"]
    return (
        f"QProgressBar {{ background:{s3}; border:1px solid {bdr}; "
        f"border-radius:4px; }}"
        f"QProgressBar::chunk {{ background:{acc}; border-radius:3px; }}"
    )


# ── Microcopy helpers ──────────────────────────────────────────────────────────

def dual_label(primary: str, secondary: str) -> "QLabel":
    """
    Return a QLabel showing a primary label with a smaller muted secondary line.
    Use in QFormLayout / QGridLayout label columns to add plain-language
    context alongside technical terms.

        cl.addWidget(dual_label("Exposure", "µs · image brightness"), 0, 0)
    """
    from PyQt5.QtWidgets import QLabel
    from PyQt5.QtCore import Qt
    td, cap = PALETTE["textDim"], FONT["caption"]
    lbl = QLabel(
        f'{primary}'
        f'<br><span style="font-size:{cap}pt; color:{td};">{secondary}</span>'
    )
    lbl.setTextFormat(Qt.RichText)
    return lbl
