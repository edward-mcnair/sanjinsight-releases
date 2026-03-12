"""
ui/theme.py  —  Single source of truth for SanjINSIGHT visual design.

Two themes (dark / light) defined as raw colour dicts.  A single
``build_style(mode)`` call produces the complete application QSS —
no hardcoded hex values live anywhere outside this file.

Quick reference
---------------
    from ui.theme import PALETTE, FONT, build_style, set_theme
    from ui.theme import btn_primary_qss, status_pill_qss

    # At startup (after apply_dpi_scale):
    app.setStyleSheet(build_style("dark"))

    # On theme switch:
    set_theme("light")
    app.setStyleSheet(build_style("light"))
    app.setPalette(build_qt_palette("light"))
"""

from __future__ import annotations

import sys as _sys


# ── Raw colour palettes ──────────────────────────────────────────────────────
#
# These dicts are the ONLY place hex values live.  Every other part of the
# codebase reads from PALETTE (the live active dict) or calls build_style().
#
# Design language
# ---------------
# Both themes share a cool blue-gray tonal axis — the same colour temperature
# in dark and light.  This makes the transition between modes feel intentional
# rather than accidental.  Four surface depth levels (bg → surface → surface2
# → surface3) create visual hierarchy without shadows.

_DARK_RAW: dict = {
    # ── Backgrounds (neutral dark gray, #242424 base) ────────────────────────
    "bg":           "#242424",   # deepest: main window / page canvas
    "surface":      "#2d2d2d",   # panels, sidebar, cards
    "surface2":     "#333333",   # list rows, elevated cells
    "surface3":     "#3a3a3a",   # input fields, header bar, inset areas
    # ── Borders ─────────────────────────────────────────────────────────────
    "border":       "#484848",   # standard panel borders
    "border2":      "#3d3d3d",   # deep / wizard-style borders
    # ── Interactive states ───────────────────────────────────────────────────
    "surfaceHover": "#404040",   # any surface on mouse-over
    # ── Text (high-contrast neutrals) ────────────────────────────────────────
    "text":         "#ebebeb",   # primary   (~12:1 on surface  ✓)
    "textDim":      "#999999",   # secondary (~5.2:1 on surface ✓)
    "textSub":      "#6a6a6a",   # hint / caption
    # ── Brand accent — teal ─────────────────────────────────────────────────
    "accent":       "#00d4aa",
    "accentDim":    "#00d4aa2e", # teal @ 18 % opacity
    "accentHover":  "#00e8bb",   # lighter teal for hover
    # ── Semantic ────────────────────────────────────────────────────────────
    "success":      "#00d4aa",
    "warning":      "#ffaa44",
    "danger":       "#ff4466",
    "info":         "#5b8ff9",
    # ── Readiness widget ────────────────────────────────────────────────────
    "readyBg":       "#0a2e28",
    "readyBorder":   "#00d4aa",
    "warnBg":        "#2e1e08",
    "warnBorder":    "#ffaa44",
    "errorBg":       "#2e0e18",
    "errorBorder":   "#ff4466",
    "unknownBg":     "#2d2d2d",
    "unknownBorder": "#484848",
}

_LIGHT_RAW: dict = {
    # ── Backgrounds (neutral mid-gray, #d9d9d9 base) ─────────────────────────
    "bg":           "#d9d9d9",   # deepest: main window / page canvas
    "surface":      "#f4f4f4",   # panels, sidebar, cards  (~16:1 text contrast ✓)
    "surface2":     "#ebebeb",   # list rows, elevated cells
    "surface3":     "#e0e0e0",   # input fields, header bar, inset areas
    # ── Borders ─────────────────────────────────────────────────────────────
    "border":       "#c2c2c2",   # standard panel borders (visible on all surfaces)
    "border2":      "#b0b0b0",   # deep / emphasized borders
    # ── Interactive states ───────────────────────────────────────────────────
    "surfaceHover": "#e6e6e6",   # any surface on mouse-over
    # ── Text (neutral, high-contrast on all light surfaces) ──────────────────
    "text":         "#1a1a1a",   # primary   (~16:1 on surface  ✓)
    "textDim":      "#5a5a5a",   # secondary (~6.3:1 on surface ✓)
    "textSub":      "#888888",   # hint / caption
    # ── Brand accent — teal darkened for WCAG AA on light surfaces ───────────
    "accent":       "#009e80",
    "accentDim":    "#009e8020",
    "accentHover":  "#007d68",
    # ── Semantic ────────────────────────────────────────────────────────────
    "success":      "#009e80",
    "warning":      "#c47d00",
    "danger":       "#d42050",
    "info":         "#3a5fd4",
    # ── Readiness widget ────────────────────────────────────────────────────
    "readyBg":       "#ddf0eb",
    "readyBorder":   "#009e80",
    "warnBg":        "#f0e4c8",
    "warnBorder":    "#c47d00",
    "errorBg":       "#f0d8e0",
    "errorBorder":   "#d42050",
    "unknownBg":     "#ebebeb",
    "unknownBorder": "#c2c2c2",
}


# ── Font scale (pt sizes, macOS 72-DPI baseline) ─────────────────────────────
#
# apply_dpi_scale() rescales these once QApplication + QScreen are available.
# build_style() reads FONT at call time, so any widget constructed after
# apply_dpi_scale() automatically gets the correctly-scaled sizes.

_FONT_BASE: dict = {
    "title":     17,   # sidebar app name / wizard h1
    "heading":   14,   # panel section headings
    "body":      13,   # general text, buttons, inputs
    "label":     12,   # form row labels
    "sublabel":  11,   # secondary / dim sub-labels
    "caption":   10,   # hints, badges, inline notes
    "readout":   22,   # big status readout values
    "readoutLg": 26,   # large readout (e.g. temperature actual)
    "readoutSm": 16,   # compact readout (e.g. exposure/gain labels)
    "mono":      13,   # monospace (console, log, frame stats)
}

_DPI_SCALE: float = 1.0 if _sys.platform == "darwin" else 72.0 / 96.0


def apply_dpi_scale(scale: float) -> None:
    """Update FONT in-place using the real screen DPI scale factor.

    Call once, right after QApplication is created::

        app = QApplication(sys.argv)
        from ui.theme import apply_dpi_scale
        apply_dpi_scale(72.0 / app.primaryScreen().logicalDotsPerInch())
    """
    global _DPI_SCALE
    _DPI_SCALE = scale
    for k, v in _FONT_BASE.items():
        FONT[k] = max(8, int(round(v * scale)))


# Initialised with best-guess platform scale; apply_dpi_scale() refines it.
FONT: dict = {k: max(8, int(round(v * _DPI_SCALE))) for k, v in _FONT_BASE.items()}


# ── Active palette ────────────────────────────────────────────────────────────
#
# PALETTE is the single live dict all widget code imports.  set_theme() clears
# and repopulates it so every PALETTE["key"] reference automatically reflects
# the current mode — no import changes needed anywhere.

_active_mode: str = "dark"
PALETTE: dict = dict(_DARK_RAW)


def set_theme(mode: str) -> None:
    """Switch the active theme to ``'dark'`` or ``'light'``.

    Updates PALETTE in-place — all existing ``PALETTE[key]`` references
    in widget code pick up the new values automatically.
    """
    global _active_mode
    _active_mode = mode
    raw = _DARK_RAW if mode == "dark" else _LIGHT_RAW
    PALETTE.clear()
    PALETTE.update(raw)


def active_theme() -> str:
    """Return the currently active theme name (``'dark'`` or ``'light'``)."""
    return _active_mode


# ── OS theme detection ────────────────────────────────────────────────────────

def detect_system_theme() -> str:
    """Query the OS for the current light/dark preference.

    Returns ``'dark'`` or ``'light'``.  Falls back to ``'dark'`` on any
    error or unsupported platform.
    """
    import subprocess
    if _sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1,
            )
            return "dark" if r.stdout.strip() == "Dark" else "light"
        except Exception:
            pass
    elif _sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if val else "dark"
        except Exception:
            pass
    else:  # Linux / freedesktop
        try:
            r = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=1,
            )
            return "dark" if "dark" in r.stdout.lower() else "light"
        except Exception:
            pass
    return "dark"


# ── QPalette builder ──────────────────────────────────────────────────────────

def build_qt_palette(mode: str = "dark"):
    """Return a QPalette matching the requested theme mode."""
    from PyQt5.QtGui import QPalette, QColor
    p = _DARK_RAW if mode == "dark" else _LIGHT_RAW
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(p["bg"]))
    pal.setColor(QPalette.WindowText,      QColor(p["text"]))
    pal.setColor(QPalette.Base,            QColor(p["surface3"]))
    pal.setColor(QPalette.AlternateBase,   QColor(p["surface2"]))
    pal.setColor(QPalette.ToolTipBase,     QColor(p["surface2"]))
    pal.setColor(QPalette.ToolTipText,     QColor(p["text"]))
    pal.setColor(QPalette.Text,            QColor(p["text"]))
    pal.setColor(QPalette.Button,          QColor(p["surface2"]))
    pal.setColor(QPalette.ButtonText,      QColor(p["text"]))
    pal.setColor(QPalette.BrightText,      QColor(p["accent"]))
    pal.setColor(QPalette.Link,            QColor(p["info"]))
    pal.setColor(QPalette.Highlight,       QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["textSub"]))
    pal.setColor(QPalette.Disabled, QPalette.Text,       QColor(p["textSub"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["textSub"]))
    return pal


# ── Master QSS builder ────────────────────────────────────────────────────────

def build_style(mode: str = "dark") -> str:
    """Generate the complete application stylesheet for the given mode.

    Replaces the hardcoded STYLE constant previously defined in main_app.py.
    Call once at startup and again on any theme switch.

    FONT must already be DPI-scaled — call apply_dpi_scale() first.
    """
    p = _DARK_RAW if mode == "dark" else _LIGHT_RAW
    f = FONT

    _acc  = p["accent"]
    _ahov = p["accentHover"]
    _text = p["text"]
    _dim  = p["textDim"]
    _sub  = p["textSub"]
    _bg   = p["bg"]
    _s    = p["surface"]
    _s2   = p["surface2"]
    _s3   = p["surface3"]
    _bdr  = p["border"]
    _hov  = p["surfaceHover"]
    _warn = p["warning"]
    _dng  = p["danger"]

    # Tooltips always dark for maximum readability in both modes
    _tt_bg  = "#1a1d28"
    _tt_fg  = "#dde3f2"
    _tt_bdr = "#2e3245"

    _dark = mode == "dark"

    def _dk(d: str, l: str) -> str:
        return d if _dark else l

    return f"""
/* ════════════════════════════════════════════════════════════════════════════
   BASE
════════════════════════════════════════════════════════════════════════════ */
QWidget {{
    background: {_bg};
    color: {_text};
    font-size: {f['body']}pt;
    selection-background-color: {_acc};
    selection-color: #ffffff;
}}
QMainWindow, QDialog {{
    background: {_bg};
}}
QFrame {{
    background: transparent;
    border: none;
}}

/* ════════════════════════════════════════════════════════════════════════════
   LABELS
════════════════════════════════════════════════════════════════════════════ */
QLabel {{
    background: transparent;
    color: {_text};
}}
QLabel#readout {{
    font-family: 'Menlo', 'Courier New', monospace;
    font-size: {f['readoutLg']}pt;
    color: {_acc};
}}
QLabel#readout_warn  {{ color: {_warn}; }}
QLabel#readout_error {{ color: {_dng};  }}
QLabel#sublabel {{
    font-size: {f['caption']}pt;
    color: {_sub};
    letter-spacing: 1px;
    text-transform: uppercase;
}}

/* ════════════════════════════════════════════════════════════════════════════
   BUTTONS — base
════════════════════════════════════════════════════════════════════════════ */
QPushButton {{
    background: {_s2};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: {f['body']}pt;
}}
QPushButton:hover {{
    background: {_hov};
    border-color: {_dim};
}}
QPushButton:pressed {{
    background: {_bg};
    padding-top: 6px;
    padding-bottom: 4px;
}}
QPushButton:focus {{
    border-color: {_acc};
    outline: none;
}}
QPushButton:disabled {{
    color: {_sub};
    background: {_s2};
    border-color: {_bdr};
}}
QPushButton:checked {{
    background: {_acc};
    color: #ffffff;
    border-color: {_acc};
}}

/* Primary action (teal) */
QPushButton#primary {{
    background: {_dk('#003d2e', '#d4f3ed')};
    color: {_acc};
    border-color: {_acc};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {_dk('#004d3a', '#c0ede4')};
    color: {_ahov};
    border-color: {_ahov};
}}
QPushButton#primary:pressed {{
    background: {_dk('#002820', '#a8e4d8')};
    padding-top: 6px; padding-bottom: 4px;
}}
QPushButton#primary:focus   {{ border-color: {_acc}; outline: none; }}
QPushButton#primary:disabled {{
    background: {_dk('#1a2e28', '#e8f5f2')};
    color: {_dk('#2a5040', '#80b8ae')};
    border-color: {_dk('#1e3030', '#c0ddd8')};
}}

/* Danger action (red) */
QPushButton#danger {{
    background: {_dk('#2a0810', '#fde8ee')};
    color: {_dng};
    border-color: {_dng};
    font-weight: 600;
}}
QPushButton#danger:hover    {{ background: {_dk('#3a0c18', '#f8d0db')}; }}
QPushButton#danger:pressed  {{
    background: {_dk('#1a040c', '#f0bec8')};
    padding-top: 6px; padding-bottom: 4px;
}}
QPushButton#danger:focus    {{ border-color: {_dng}; outline: none; }}
QPushButton#danger:disabled {{
    color: {_sub}; background: {_s2}; border-color: {_bdr};
}}

/* Domain: cold frame capture */
QPushButton#cold_btn {{
    background: {_dk('#001a33', '#e8f0ff')};
    color: {_dk('#66aaff', '#2255bb')};
    border-color: {_dk('#3377cc', '#6688dd')};
    font-weight: 600;
}}
QPushButton#cold_btn:hover {{
    background: {_dk('#002244', '#d8e8ff')};
    border-color: {_dk('#4488dd', '#4477cc')};
}}

/* Domain: hot frame capture */
QPushButton#hot_btn {{
    background: {_dk('#331a00', '#fff4e0')};
    color: {_warn};
    border-color: {_dk('#cc6600', '#c47d00')};
    font-weight: 600;
}}
QPushButton#hot_btn:hover {{
    background: {_dk('#442200', '#ffe8c0')};
    border-color: {_dk('#dd7700', '#a86800')};
}}

/* Running / in-progress dynamic state */
QPushButton[running="true"] {{
    background: {_dk('#2a1e00', '#fff4d0')};
    color: {_dk('#f5a623', '#8b5a00')};
    border: 2px solid {_dk('#f5a62366', '#c47d0066')};
    font-weight: 600;
    padding: 4px 13px;
}}
QPushButton[running="true"]#primary {{
    background: {_dk('#002820', '#d4f3ed')};
    color: {_acc};
    border: 2px solid {_acc}66;
    padding: 4px 13px;
}}

/* ════════════════════════════════════════════════════════════════════════════
   LINE EDIT
════════════════════════════════════════════════════════════════════════════ */
QLineEdit {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {f['body']}pt;
    selection-background-color: {_acc};
    selection-color: #ffffff;
}}
QLineEdit:focus    {{ border-color: {_acc}; }}
QLineEdit:disabled {{ color: {_sub}; background: {_s2}; }}

/* ════════════════════════════════════════════════════════════════════════════
   TEXT EDIT / PLAIN TEXT EDIT
════════════════════════════════════════════════════════════════════════════ */
QTextEdit, QPlainTextEdit {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 4px;
    font-size: {f['body']}pt;
    selection-background-color: {_acc};
    selection-color: #ffffff;
}}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {_acc}; }}
QTextEdit#console, QPlainTextEdit#console {{
    font-family: 'Menlo', 'Courier New', monospace;
    font-size: {f['mono']}pt;
    background: {_dk('#0d1018', '#f8f9fc')};
    color: {_dk('#a8d8b0', '#1a4a20')};
    border-color: {_dk('#1e2338', '#c0c6d8')};
}}

/* ════════════════════════════════════════════════════════════════════════════
   SPINBOXES
════════════════════════════════════════════════════════════════════════════ */
QSpinBox, QDoubleSpinBox {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 4px 6px;
    font-size: {f['body']}pt;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {_acc}; }}
QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {_sub}; background: {_s2}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {_bdr};
    border-bottom: 1px solid {_bdr};
    border-radius: 0 4px 0 0;
    background: {_s2};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid {_bdr};
    border-radius: 0 0 4px 0;
    background: {_s2};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {_hov};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {_dim};
    width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_dim};
    width: 0; height: 0;
}}

/* ════════════════════════════════════════════════════════════════════════════
   COMBOBOX
════════════════════════════════════════════════════════════════════════════ */
QComboBox {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {f['body']}pt;
}}
QComboBox:focus    {{ border-color: {_acc}; }}
QComboBox:disabled {{ color: {_sub}; background: {_s2}; }}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    border-left: 1px solid {_bdr};
    border-radius: 0 4px 4px 0;
}}
QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_dim};
    width: 0; height: 0;
}}
QComboBox QAbstractItemView {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    padding: 2px;
    selection-background-color: {_acc};
    selection-color: #ffffff;
    outline: none;
}}

/* ════════════════════════════════════════════════════════════════════════════
   CHECKBOX & RADIOBUTTON
════════════════════════════════════════════════════════════════════════════ */
QCheckBox {{
    color: {_text};
    spacing: 8px;
    font-size: {f['body']}pt;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {_bdr};
    border-radius: 3px;
    background: {_s3};
}}
QCheckBox::indicator:hover   {{ border-color: {_acc}; }}
QCheckBox::indicator:checked {{
    background: {_acc};
    border-color: {_acc};
}}
QCheckBox::indicator:checked:disabled {{ background: {_sub}; border-color: {_sub}; }}
QCheckBox:disabled {{ color: {_sub}; }}

QRadioButton {{
    color: {_text};
    spacing: 8px;
    font-size: {f['body']}pt;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {_bdr};
    border-radius: 8px;
    background: {_s3};
}}
QRadioButton::indicator:hover   {{ border-color: {_acc}; }}
QRadioButton::indicator:checked {{
    background: {_acc};
    border-color: {_acc};
}}
QRadioButton:disabled {{ color: {_sub}; }}

/* ════════════════════════════════════════════════════════════════════════════
   GROUPBOX
════════════════════════════════════════════════════════════════════════════ */
QGroupBox {{
    color: {_dim};
    font-size: {f['label']}pt;
    font-weight: 600;
    border: 1px solid {_bdr};
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 6px;
    background: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    background: {_bg};
}}

/* ════════════════════════════════════════════════════════════════════════════
   TAB WIDGET
════════════════════════════════════════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {_bdr};
    border-radius: 0 4px 4px 4px;
    background: {_s};
}}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {_s2};
    color: {_dim};
    border: 1px solid {_bdr};
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 6px 18px;
    font-size: {f['body']}pt;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {_s};
    color: {_text};
    border-bottom: 2px solid {_acc};
}}
QTabBar::tab:hover:!selected {{
    background: {_hov};
    color: {_text};
}}

/* ════════════════════════════════════════════════════════════════════════════
   SCROLLBARS  (thin, modern)
════════════════════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_bdr};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {_sub}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {_bdr};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {_sub}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ════════════════════════════════════════════════════════════════════════════
   SLIDER
════════════════════════════════════════════════════════════════════════════ */
QSlider::groove:horizontal {{
    background: {_s3};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {_acc};
    border: none;
    width: 14px; height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{ background: {_ahov}; }}
QSlider::sub-page:horizontal {{ background: {_acc}; border-radius: 2px; }}

QSlider::groove:vertical {{
    background: {_s3};
    width: 4px;
    border-radius: 2px;
}}
QSlider::handle:vertical {{
    background: {_acc};
    border: none;
    width: 14px; height: 14px;
    border-radius: 7px;
    margin: 0 -5px;
}}
QSlider::handle:vertical:hover {{ background: {_ahov}; }}
QSlider::sub-page:vertical {{ background: {_acc}; border-radius: 2px; }}

/* ════════════════════════════════════════════════════════════════════════════
   PROGRESS BAR
════════════════════════════════════════════════════════════════════════════ */
QProgressBar {{
    background: {_s3};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
    font-size: {f['caption']}pt;
}}
QProgressBar::chunk {{ background: {_acc}; border-radius: 3px; }}

/* ════════════════════════════════════════════════════════════════════════════
   LISTS, TREES & TABLES
════════════════════════════════════════════════════════════════════════════ */
QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    outline: none;
    font-size: {f['body']}pt;
    alternate-background-color: {_s2};
}}
QListWidget::item, QListView::item,
QTreeWidget::item, QTreeView::item {{
    padding: 4px 8px;
    border-radius: 3px;
}}
QListWidget::item:hover, QListView::item:hover,
QTreeWidget::item:hover, QTreeView::item:hover {{ background: {_hov}; }}
QListWidget::item:selected, QListView::item:selected,
QTreeWidget::item:selected, QTreeView::item:selected {{
    background: {_acc};
    color: #ffffff;
}}
QTreeView::branch {{ background: {_s}; }}

QTableWidget, QTableView {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 4px;
    gridline-color: {_bdr};
    outline: none;
    font-size: {f['body']}pt;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {_acc};
    color: #ffffff;
}}
QHeaderView::section {{
    background: {_s2};
    color: {_dim};
    border: none;
    border-right: 1px solid {_bdr};
    border-bottom: 1px solid {_bdr};
    padding: 6px 10px;
    font-size: {f['label']}pt;
    font-weight: 600;
}}
QHeaderView::section:first {{ border-left: none; }}

/* ════════════════════════════════════════════════════════════════════════════
   SCROLL AREA & SPLITTER
════════════════════════════════════════════════════════════════════════════ */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QSplitter::handle            {{ background: {_bdr}; }}
QSplitter::handle:horizontal {{ width:  5px; }}
QSplitter::handle:vertical   {{ height: 5px; }}

/* ════════════════════════════════════════════════════════════════════════════
   STATUS BAR & MENU BAR
════════════════════════════════════════════════════════════════════════════ */
QStatusBar {{
    background: {_s3};
    color: {_dim};
    font-size: {f['caption']}pt;
    border-top: 1px solid {_bdr};
}}
QMenuBar {{
    background: {_s3};
    color: {_dim};
    border-bottom: 1px solid {_bdr};
    font-size: {f['body']}pt;
}}
QMenuBar::item:selected {{ background: {_hov}; color: {_text}; }}
QMenu {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 6px;
    padding: 4px;
    font-size: {f['body']}pt;
}}
QMenu::item {{
    padding: 6px 20px 6px 14px;
    border-radius: 3px;
}}
QMenu::item:selected {{ background: {_hov}; color: {_text}; }}
QMenu::separator {{ height: 1px; background: {_bdr}; margin: 4px 8px; }}

/* ════════════════════════════════════════════════════════════════════════════
   TOOLTIP  (always dark regardless of app mode — best readability)
════════════════════════════════════════════════════════════════════════════ */
QToolTip {{
    background: {_tt_bg};
    color: {_tt_fg};
    border: 1px solid {_tt_bdr};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: {f['label']}pt;
    opacity: 230;
}}

/* ════════════════════════════════════════════════════════════════════════════
   DOCK WIDGET
════════════════════════════════════════════════════════════════════════════ */
QDockWidget {{
    background: {_bg};
    color: {_text};
}}
QDockWidget::title {{
    background: {_s2};
    color: {_dim};
    padding: 6px 10px;
    border-bottom: 1px solid {_bdr};
    font-size: {f['label']}pt;
    font-weight: 600;
}}
"""


# ── scaled_qss (backward compatibility) ──────────────────────────────────────

def scaled_qss(qss: str) -> str:
    """Scale every ``font-size: Npt`` token in a QSS string by _DPI_SCALE.

    On macOS (scale = 1.0) the string is returned unchanged with zero overhead.
    Use only for legacy inline stylesheets that contain hardcoded pt values.
    """
    if _DPI_SCALE == 1.0:
        return qss
    import re as _re
    return _re.sub(
        r'font-size:\s*(\d+)pt',
        lambda m: f"font-size:{max(8, int(round(int(m.group(1)) * _DPI_SCALE)))}pt",
        qss,
    )


# ── Component helpers ─────────────────────────────────────────────────────────
#
# These return focused QSS snippets for widgets that need styling beyond the
# base application stylesheet.  All read from PALETTE (the live dict) so they
# automatically reflect the active theme when called inside _apply_styles().


def btn_primary_qss() -> str:
    """Teal primary action button (Save, Run, Apply…)."""
    p, f = PALETTE, FONT
    acc  = p["accent"]
    ahov = p["accentHover"]
    dark = active_theme() == "dark"
    return f"""
    QPushButton {{
        background: {'#003d2e' if dark else '#d4f3ed'};
        color: {acc}; border: 1px solid {acc};
        border-radius: 4px; padding: 5px 16px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover   {{ background: {'#004d3a' if dark else '#c0ede4'};
                           color: {ahov}; border-color: {ahov}; }}
    QPushButton:pressed {{ background: {'#002820' if dark else '#a8e4d8'};
                           padding-top: 6px; padding-bottom: 4px; }}
    QPushButton:disabled {{ background: {'#1a2e28' if dark else '#e8f5f2'};
                            color: {'#2a5040' if dark else '#80b8ae'};
                            border-color: {'#1e3030' if dark else '#c0ddd8'}; }}
    """


def btn_secondary_qss() -> str:
    """Muted secondary button."""
    p, f = PALETTE, FONT
    return f"""
    QPushButton {{
        background: {p['surface2']}; color: {p['textDim']};
        border: 1px solid {p['border']}; border-radius: 4px;
        padding: 5px 16px; font-size: {f['body']}pt;
    }}
    QPushButton:hover   {{ background: {p['surfaceHover']}; color: {p['text']}; }}
    QPushButton:pressed {{ background: {p['bg']}; padding-top: 6px; padding-bottom: 4px; }}
    QPushButton:disabled {{ color: {p['textSub']}; border-color: {p['border']}; }}
    """


def btn_danger_qss() -> str:
    """Destructive / danger action button."""
    p, f = PALETTE, FONT
    dark = active_theme() == "dark"
    dng  = p["danger"]
    return f"""
    QPushButton {{
        background: {'#2a0810' if dark else '#fde8ee'};
        color: {dng}; border: 1px solid {dng};
        border-radius: 4px; padding: 5px 16px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover   {{ background: {'#3a0c18' if dark else '#f8d0db'}; }}
    QPushButton:pressed {{ background: {'#1a040c' if dark else '#f0bec8'};
                           padding-top: 6px; padding-bottom: 4px; }}
    QPushButton:disabled {{ color: {p['textSub']}; background: {p['surface2']};
                            border-color: {p['border']}; }}
    """


def btn_wizard_primary_qss() -> str:
    """Blue primary button for the first-run wizard."""
    f = FONT
    return f"""
    QPushButton {{
        background: #4e73df; color: #fff; border: none;
        border-radius: 6px; padding: 8px 22px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover    {{ background: #3a5fc8; }}
    QPushButton:pressed  {{ background: #2e4fa8; padding-top: 9px; padding-bottom: 7px; }}
    QPushButton:disabled {{ background: #333; color: #666; }}
    """


def btn_wizard_secondary_qss() -> str:
    """Muted secondary button for the first-run wizard."""
    f = FONT
    return f"""
    QPushButton {{
        background: #1e2337; color: #aaa;
        border: 1px solid #333; border-radius: 6px;
        padding: 8px 22px; font-size: {f['body']}pt;
    }}
    QPushButton:hover   {{ background: #2a3249; color: #ccc; }}
    QPushButton:pressed {{ background: #1a1f33; }}
    """


def input_qss() -> str:
    """Standard spinbox / line-edit / combo stylesheet (for manual override)."""
    p, f = PALETTE, FONT
    return f"""
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background: {p['surface3']}; color: {p['text']};
        border: 1px solid {p['border']}; border-radius: 4px;
        padding: 4px 8px; font-size: {f['body']}pt;
        selection-background-color: {p['accent']};
    }}
    QLineEdit:focus, QDoubleSpinBox:focus,
    QSpinBox:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{
        background: {p['surface']}; color: {p['text']};
        border: 1px solid {p['border']};
    }}
    """


def wizard_input_qss() -> str:
    """Input style for the first-run wizard (blue focus accent)."""
    f = FONT
    return f"""
    QLineEdit, QComboBox {{
        background: #13172a; color: #ddd;
        border: 1px solid #2a3249; border-radius: 4px;
        padding: 5px 10px; font-size: {f['body']}pt;
        selection-background-color: #4e73df;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: #4e73df; }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{
        background: #13172a; color: #ddd; border: 1px solid #2a3249;
    }}
    """


def groupbox_qss() -> str:
    """Standard GroupBox border + title style."""
    p, f = PALETTE, FONT
    return f"""
    QGroupBox {{
        color: {p['textDim']}; font-size: {f['label']}pt; font-weight: 600;
        border: 1px solid {p['border']}; border-radius: 6px;
        margin-top: 8px; padding-top: 6px; background: transparent;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; subcontrol-position: top left;
        padding: 0 6px; left: 10px; background: {p['bg']};
    }}
    """


def progress_bar_qss() -> str:
    """Teal progress bar (for manual override)."""
    p = PALETTE
    return (
        f"QProgressBar {{ background:{p['surface3']}; border:none; "
        f"border-radius:3px; height:6px; color:transparent; }}"
        f"QProgressBar::chunk {{ background:{p['accent']}; border-radius:3px; }}"
    )


def status_pill_qss(semantic: str) -> str:
    """Soft status pill — 18 % opacity background, solid colour text.

    Parameters
    ----------
    semantic : ``'success'`` | ``'warning'`` | ``'danger'`` | ``'info'``
    """
    color = PALETTE.get(semantic, PALETTE["info"])
    f = FONT
    return f"""
    QLabel {{
        background: {color}2e;
        color: {color};
        border-radius: 3px;
        padding: 1px 7px;
        font-size: {f['caption']}pt;
        font-weight: 600;
    }}
    """


def segmented_control_qss() -> str:
    """Base style for Auto/Dark/Light and similar segmented controls.

    Apply per-button border-radius overrides on top::

        base = segmented_control_qss()
        first_btn.setStyleSheet(base + "QPushButton { border-radius: 4px 0 0 4px; }")
        mid_btn.setStyleSheet(  base + "QPushButton { border-radius: 0; border-left: none; }")
        last_btn.setStyleSheet( base + "QPushButton { border-radius: 0 4px 4px 0; border-left: none; }")
    """
    p, f = PALETTE, FONT
    acc = p["accent"]
    return f"""
    QPushButton {{
        background: {p['surface2']}; color: {p['textDim']};
        border: 1px solid {p['border']}; padding: 5px 0;
        font-size: {f['label']}pt;
    }}
    QPushButton:checked {{
        background: {acc}; color: #ffffff; border-color: {acc};
    }}
    QPushButton:hover:!checked {{
        background: {p['surfaceHover']}; color: {p['text']};
    }}
    """


def badge_qss(semantic: str) -> str:
    """Compact solid-fill badge for counts and result grades.

    Parameters
    ----------
    semantic : ``'success'`` | ``'warning'`` | ``'danger'`` | ``'info'``
    """
    color = PALETTE.get(semantic, PALETTE["info"])
    f = FONT
    return f"""
    QLabel {{
        background: {color};
        color: #ffffff;
        border-radius: 3px;
        padding: 1px 5px;
        font-size: {f['caption']}pt;
        font-weight: 700;
    }}
    """


# ── Microcopy helper ──────────────────────────────────────────────────────────

def dual_label(primary: str, secondary: str) -> "QLabel":
    """Return a QLabel with a primary label and a smaller muted secondary line.

    Use in QFormLayout / QGridLayout label columns::

        layout.addWidget(dual_label("Exposure", "µs · image brightness"), 0, 0)
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
