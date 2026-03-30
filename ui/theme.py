"""
ui/theme.py  —  Single source of truth for SanjINSIGHT visual design.

Two themes (dark / light) defined as raw colour dicts.  A single
``build_style(mode)`` call produces the complete application QSS —
no hardcoded hex values live anywhere outside this file.

Quick reference
---------------
    from ui.theme import PALETTE, FONT, build_style, set_theme
    from ui.theme import btn_primary_qss, btn_accent_qss, status_pill_qss

    # At startup (after apply_dpi_scale):
    app.setStyleSheet(build_style("dark"))

    # On theme switch:
    set_theme("light")
    app.setStyleSheet(build_style("light"))
    app.setPalette(build_qt_palette("light"))

Colour roles
------------
  accent / accentHover / accentDim
      Mint-teal — system health, status, active indicators, focus rings,
      checkboxes, progress bars.  "The instrument is healthy."

  cta / ctaHover / ctaDim
      Blue — primary user-action CTAs: Run, Save, Apply, Export.
      "You are doing something."  Used for QPushButton#primary and
      btn_primary_qss().  Distinct from accent so CTAs read immediately
      as interactive.

  success / warning / danger / info
      Semantic one-offs: verdicts, readiness states, alerts.
      Derived from Apple's precisely-calibrated system colors.

  systemPurple / systemIndigo / systemPink / systemMint
  systemYellow / systemCyan / systemBrown
      Extended Apple system colors for icons and indicators.
      Purple → AI / advanced features.  Indigo → classification / navigation.
      Pink → critical alert.  Mint → connection / sync.
      Yellow → caution / pending.  Cyan → data / streaming.
      Brown → materials / physical layer.
"""

from __future__ import annotations

import sys as _sys


# ══════════════════════════════════════════════════════════════════════════════
#  Raw colour palettes
# ══════════════════════════════════════════════════════════════════════════════
#
# Design language — informed by Apple Human Interface Guidelines
# -------------------------------------------------------------
# Both themes follow Apple's layered background model:
#   Dark:  near-black workspace canvas → elevated sidebar/panels → controls
#   Light: grouped-background grey base → pure-white panels → inset fields
#
# The key insight from Apple's macOS design system is that navigation and
# workspace must occupy clearly distinct depth levels.  In dark mode the
# workspace sits at near-black (#111113) and the sidebar is elevated to
# Apple's secondarySystemBackground (#1c1c1e) — a visible, decisive step.
# In light mode the workspace is the grouped background (#f2f2f7) and panels
# are pure white (#ffffff) — unambiguous contrast that reads immediately.
#
# Semantic colors use Apple's precisely-calibrated system-color values.
# They were tuned for contrast, cultural legibility, and colorblind safety.
# We extend the palette with seven Apple system colors for icons/indicators:
# purple, indigo, pink, mint, yellow, cyan, brown — giving each type of
# hardware, protocol, or state a distinct, instantly-recognizable hue.
#
# Accent roles:
#   accent  — mint-teal (#00c7be dark / #009e80 light): instrument health
#   cta     — blue      (#0a84ff dark / #007aff light): primary user actions

_DARK_RAW: dict = {
    # ── Backgrounds — Apple macOS layering model ──────────────────────────────
    # Each level is noticeably darker/lighter than the one above it.
    # workspace canvas: near-black (like macOS systemBackground in dark mode)
    # sidebar/panels: Apple's secondarySystemBackground (#1c1c1e)
    # list rows / cards: tertiary (#242426)
    # input fields / inset: quaternary (#2c2c2e Apple tertiarySystemBackground)
    # header bar / popovers: most elevated (#3a3a3c Apple systemGray4 dark)
    "bg":           "#111113",   # workspace canvas — near black
    "surface":      "#1c1c1e",   # sidebar, panels  — Apple secondarySystemBg
    "surface2":     "#242426",   # list rows, cards
    "surface3":     "#2c2c2e",   # input fields     — Apple tertiarySystemBg
    "surface4":     "#3a3a3c",   # header bar, popovers, tooltips (most elevated)
    # ── Borders — Apple opaqueSeparator dark (#38383a) ────────────────────────
    "border":       "#38383a",   # standard panel borders
    "border2":      "#2e2e30",   # subtle / inner borders
    # ── Interactive states ───────────────────────────────────────────────────
    "surfaceHover": "#2e2e30",   # surface on mouse-over (between surface2/3)
    # ── Text — Apple label hierarchy (opacity-based, cool-white) ─────────────
    # label (#ebebf5 @85%): primary readable text
    # secondaryLabel (#ebebf5 @55%): supporting text
    # tertiaryLabel (#ebebf5 @30%): hints, placeholders
    #
    # WCAG AA contrast ratios (verified 2026-03-30):
    #   text    on bg:      15.93:1  PASS (normal+large)
    #   textDim on bg:       6.49:1  PASS (normal+large)
    #   textDim on surface:  5.85:1  PASS (normal+large)
    #   textSub on bg:       2.53:1  (decorative/tertiary only — not body text)
    "text":         "#ebebf5",   # primary label — Apple dark label
    "textDim":      "#9696a8",   # secondary label ~55% — cool tinted
    "textSub":      "#545462",   # tertiary label  ~30%
    # ── Brand accent — mint-teal (instrument health / status) ─────────────────
    # Closer to Apple's systemMint (#00d9d4) — reads as "all systems healthy"
    # WCAG AA: accent on bg = 8.90:1 PASS, accent on surface = 8.03:1 PASS
    "accent":       "#00c7be",   # Apple systemMint dark
    "accentDim":    "#00c7be26", # mint @ 15 % opacity
    "accentHover":  "#00d9d4",   # brighter mint for hover
    # ── CTA — Apple systemBlue dark (#0a84ff) ────────────────────────────────
    # WCAG AA: cta on bg = 5.17:1 PASS
    "cta":          "#0a84ff",   # Apple systemBlue dark
    "ctaHover":     "#409cff",   # lighter blue for hover
    "ctaDim":       "#0a84ff26", # blue @ 15 % opacity
    # ── Semantic — Apple system colors, precisely calibrated ──────────────────
    "success":      "#30d158",   # Apple systemGreen dark
    "warning":      "#ff9f0a",   # Apple systemOrange dark
    "danger":       "#ff453a",   # Apple systemRed dark
    "info":         "#64d5ff",   # Apple systemTeal dark (distinct from CTA blue)
    # ── Extended Apple system colors — icons and indicators ───────────────────
    # Use these to give each domain a distinct, instantly-recognizable hue.
    "systemPurple": "#bf5af2",   # AI features, advanced analysis, spectral data
    "systemIndigo": "#5e5ce6",   # classification, sessions, protocol layers
    "systemPink":   "#ff375f",   # critical alert, thermal runaway, emergency stop
    "systemMint":   "#63e6e2",   # connection status, sync, data flow (light mint)
    "systemYellow": "#ffd60a",   # caution, pending calibration, staged changes
    "systemCyan":   "#5ac8f5",   # data streaming, live acquisition, network
    "systemBrown":  "#ac8e68",   # physical hardware, materials, substrate layers
    # ── Readiness widget ─────────────────────────────────────────────────────
    "readyBg":       "#0a2918",  # deep green tint
    "readyBorder":   "#30d158",
    "warnBg":        "#2e1a00",  # deep orange tint
    "warnBorder":    "#ff9f0a",
    "errorBg":       "#2e0c08",  # deep red tint
    "errorBorder":   "#ff453a",
    "unknownBg":     "#1c1c1e",
    "unknownBorder": "#38383a",
}

_LIGHT_RAW: dict = {
    # ── Backgrounds — Apple grouped-background model ──────────────────────────
    # Light mode: grey grouped base → white panels → grey inset → strong inset
    # This is the exact pattern Apple uses in Finder, Mail, Notes, Settings.
    # The contrast is decisive: white cards on a clearly-grey field.
    "bg":           "#f2f2f7",   # Apple systemGroupedBackground light
    "surface":      "#ffffff",   # panels, sidebar — pure white on grey field
    "surface2":     "#f2f2f7",   # alternating rows — back to grouped bg
    "surface3":     "#e5e5ea",   # input fields    — Apple systemGray5 light
    "surface4":     "#d1d1d6",   # header bar, most elevated — Apple systemGray4
    # ── Borders — Apple separator light (#c6c6c8) ─────────────────────────────
    "border":       "#c6c6c8",   # Apple opaqueSeparator light
    "border2":      "#d1d1d6",   # subtle / inner borders
    # ── Interactive states ───────────────────────────────────────────────────
    "surfaceHover": "#ebebf0",   # surface on mouse-over
    # ── Text — Apple label hierarchy, cool-dark tint ──────────────────────────
    "text":         "#0a0a0f",   # primary label — near black, slight cool cast
    "textDim":      "#3c3c52",   # secondary label — cool dark grey
    "textSub":      "#8e8ea0",   # tertiary label  — Apple systemGray light
    # ── Brand accent — teal darkened for WCAG AA on white ────────────────────
    "accent":       "#009e80",   # darkened mint for sufficient contrast on white
    "accentDim":    "#009e8018",
    "accentHover":  "#007d68",
    # ── CTA — Apple systemBlue light (#007aff) ───────────────────────────────
    "cta":          "#007aff",   # Apple systemBlue light — WCAG AA on white ✓
    "ctaHover":     "#0071e3",   # Apple blue pressed state
    "ctaDim":       "#007aff18",
    # ── Semantic — Apple system colors, light mode ────────────────────────────
    "success":      "#34c759",   # Apple systemGreen light
    "warning":      "#ff9500",   # Apple systemOrange light
    "danger":       "#ff3b30",   # Apple systemRed light
    "info":         "#5ac8fa",   # Apple systemTeal light
    # ── Extended Apple system colors — icons and indicators ───────────────────
    "systemPurple": "#af52de",   # Apple systemPurple light
    "systemIndigo": "#5856d6",   # Apple systemIndigo light
    "systemPink":   "#ff2d55",   # Apple systemPink light
    "systemMint":   "#00c7be",   # Apple systemMint light
    "systemYellow": "#ffcc00",   # Apple systemYellow light
    "systemCyan":   "#50b5d5",   # Apple systemCyan light (darkened for contrast)
    "systemBrown":  "#a2845e",   # Apple systemBrown light
    # ── Readiness widget ─────────────────────────────────────────────────────
    "readyBg":       "#d4f5e2",
    "readyBorder":   "#34c759",
    "warnBg":        "#fff3d0",
    "warnBorder":    "#ff9500",
    "errorBg":       "#fde8e6",
    "errorBorder":   "#ff3b30",
    "unknownBg":     "#f2f2f7",
    "unknownBorder": "#c6c6c8",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Font scale
# ══════════════════════════════════════════════════════════════════════════════
#
# apply_dpi_scale() rescales these once QApplication + QScreen are available.
# build_style() reads FONT at call time, so any widget constructed after
# apply_dpi_scale() automatically gets the correctly-scaled sizes.
#
# Scale rationale
# ---------------
#   title (18) → heading (15): 3pt gap — clearly distinct section labels
#   heading (15) → body (13):  2pt gap — readable panel hierarchy
#   body (13) → label (12):    1pt gap — deliberate; form labels read
#                              slightly subordinate to their values
#   label (12) → sublabel/caption (11): 1pt — the smallest text in the app;
#                              Inter's tall x-height keeps 11pt legible
#
# caption was raised from 10 → 11 pt.  At 96 DPI, 10 pt is 13 CSS px —
# borderline readable even with Inter.  11 pt (15 CSS px) is safe on all
# screen types including ageing lab monitors.

_FONT_BASE: dict = {
    "title":     18,   # sidebar app name / wizard h1          (was 17)
    "heading":   15,   # panel section headings                 (was 14)
    "body":      13,   # general text, buttons, inputs
    "label":     12,   # form row labels
    "sublabel":  11,   # secondary / dim sub-labels, section caps
    "caption":   11,   # hints, badges, timestamps              (was 10)
    "readout":   24,   # big status readout values              (was 22)
    "readoutLg": 28,   # large readout (e.g. temperature actual)(was 26)
    "readoutSm": 17,   # compact readout (e.g. exposure/gain)  (was 16)
    "mono":      13,   # monospace (console, log, frame stats)
}

_DPI_SCALE: float = 1.0 if _sys.platform == "darwin" else 72.0 / 96.0


def apply_dpi_scale(scale: float) -> None:
    """Update FONT in-place and load bundled Inter fonts.

    Call once, right after QApplication is created::

        app = QApplication(sys.argv)
        from ui.theme import apply_dpi_scale
        apply_dpi_scale(72.0 / app.primaryScreen().logicalDotsPerInch())

    Also triggers Inter font loading (no-op if ``ui/fonts/`` is absent).
    """
    global _DPI_SCALE
    _DPI_SCALE = scale
    for k, v in _FONT_BASE.items():
        FONT[k] = max(8, int(round(v * scale)))
    _try_load_inter()


def _try_load_inter() -> None:
    """Load bundled Inter font files.  Silent no-op on any failure."""
    try:
        from ui.font_utils import load_inter as _load
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            _load(app)
    except Exception:
        pass


# Initialised with best-guess platform scale; apply_dpi_scale() refines it.
FONT: dict = {k: max(8, int(round(v * _DPI_SCALE))) for k, v in _FONT_BASE.items()}

# Cross-platform monospace font family string — use in inline QSS stylesheets.
# "Menlo" (macOS) → "Consolas" (Windows) → "Courier New" (fallback).
MONO_FONT = "'Menlo','Consolas','Courier New',monospace"


# ══════════════════════════════════════════════════════════════════════════════
#  Active palette
# ══════════════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════════════
#  OS theme detection
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  QPalette builder
# ══════════════════════════════════════════════════════════════════════════════

def build_qt_palette(mode: str = "dark"):
    """Return a QPalette matching the requested theme mode."""
    from PyQt5.QtGui import QPalette, QColor
    p = _DARK_RAW if mode == "dark" else _LIGHT_RAW
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(p["bg"]))
    pal.setColor(QPalette.WindowText,      QColor(p["text"]))
    pal.setColor(QPalette.Base,            QColor(p["surface3"]))
    pal.setColor(QPalette.AlternateBase,   QColor(p["surface2"]))
    pal.setColor(QPalette.ToolTipBase,     QColor(p["surface4"]))
    pal.setColor(QPalette.ToolTipText,     QColor(p["text"]))
    pal.setColor(QPalette.Text,            QColor(p["text"]))
    pal.setColor(QPalette.Button,          QColor(p["surface2"]))
    pal.setColor(QPalette.ButtonText,      QColor(p["text"]))
    pal.setColor(QPalette.BrightText,      QColor(p["accent"]))
    pal.setColor(QPalette.Link,            QColor(p["cta"]))
    pal.setColor(QPalette.Highlight,       QColor(p["cta"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["textSub"]))
    pal.setColor(QPalette.Disabled, QPalette.Text,       QColor(p["textSub"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["textSub"]))
    return pal


# ══════════════════════════════════════════════════════════════════════════════
#  Master QSS builder
# ══════════════════════════════════════════════════════════════════════════════

def build_style(mode: str = "dark") -> str:
    """Generate the complete application stylesheet for the given mode.

    Call once at startup and again on any theme switch.
    FONT must already be DPI-scaled — call apply_dpi_scale() first.

    Border-radius convention
    ------------------------
      6px  — all interactive controls: buttons, inputs, combos, checkboxes
      8px  — menus and floating popups
      10px — cards and panels (session cards, GroupBox alternative)
      4px  — compact elements: list/tree items, badges, pills
      3px  — progress bars (deliberately pill-shaped at thin height)
    """
    p = _DARK_RAW if mode == "dark" else _LIGHT_RAW
    f = FONT

    _acc  = p["accent"]
    _ahov = p["accentHover"]
    _cta  = p["cta"]
    _ctah = p["ctaHover"]
    _text = p["text"]
    _dim  = p["textDim"]
    _sub  = p["textSub"]
    _bg   = p["bg"]
    _s    = p["surface"]
    _s2   = p["surface2"]
    _s3   = p["surface3"]
    _s4   = p["surface4"]
    _bdr  = p["border"]
    _bdr2 = p["border2"]
    _hov  = p["surfaceHover"]
    _warn = p["warning"]
    _dng  = p["danger"]

    # Tooltips: use the most elevated surface level (surface4) for both modes
    # — avoids the old always-dark hack that looked wrong in light mode.
    _tt_bg  = p["surface4"]
    _tt_fg  = p["text"]
    _tt_bdr = p["border"]

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
    selection-background-color: {_cta};
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
    font-family: 'Menlo', 'Consolas', 'Courier New', monospace;
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
    border-radius: 6px;
    padding: 6px 14px;
    font-size: {f['body']}pt;
}}
QPushButton:hover {{
    background: {_hov};
    border-color: {_dim};
}}
QPushButton:pressed {{
    background: {_bg};
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton:focus {{
    border-color: {_cta};
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

/* Primary action — solid blue CTA */
QPushButton#primary {{
    background: {_cta};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {_ctah};
}}
QPushButton#primary:pressed {{
    background: {_dk('#0060d0', '#0060c0')};
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton#primary:focus   {{ outline: none; }}
QPushButton#primary:disabled {{
    background: {_dk('#1c2a3a', '#c0d8f8')};
    color: {_dk('#3a5878', '#6090c8')};
    border: none;
}}

/* Danger action (red) */
QPushButton#danger {{
    background: {_dk('#2a0810', '#fde8ee')};
    color: {_dng};
    border: 1px solid {_dng};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#danger:hover    {{ background: {_dk('#3a0c18', '#f8d0db')}; }}
QPushButton#danger:pressed  {{
    background: {_dk('#1a040c', '#f0bec8')};
    padding-top: 7px; padding-bottom: 5px;
}}
QPushButton#danger:focus    {{ border-color: {_dng}; outline: none; }}
QPushButton#danger:disabled {{
    color: {_sub}; background: {_s2}; border-color: {_bdr};
}}

/* Domain: cold frame capture */
QPushButton#cold_btn {{
    background: {_dk('#001830', '#e0eeff')};
    color: {_dk('#409cff', '#0060c0')};
    border: 1px solid {_dk('#0a84ff55', '#007aff66')};
    border-radius: 6px;
    font-weight: 600;
    padding: 6px 14px;
}}
QPushButton#cold_btn:hover {{
    background: {_dk('#002040', '#cce0ff')};
    border-color: {_dk('#409cff', '#0060c0')};
}}

/* Domain: hot frame capture */
QPushButton#hot_btn {{
    background: {_dk('#2e1800', '#fff0d8')};
    color: {_warn};
    border: 1px solid {_dk('#ff9f0a55', '#ff950066')};
    border-radius: 6px;
    font-weight: 600;
    padding: 6px 14px;
}}
QPushButton#hot_btn:hover {{
    background: {_dk('#3e2000', '#ffe4b8')};
    border-color: {_warn};
}}

/* Running / in-progress dynamic state */
QPushButton[running="true"] {{
    background: {_dk('#2a1e00', '#fff4d0')};
    color: {_dk('#ff9f0a', '#8b5200')};
    border: 2px solid {_warn}55;
    border-radius: 6px;
    font-weight: 600;
    padding: 5px 13px;
}}
QPushButton[running="true"]#primary {{
    background: {_dk('#001830', '#d0e8ff')};
    color: {_cta};
    border: 2px solid {_cta}66;
    padding: 5px 15px;
}}

/* ════════════════════════════════════════════════════════════════════════════
   LINE EDIT
════════════════════════════════════════════════════════════════════════════ */
QLineEdit {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: {f['body']}pt;
    selection-background-color: {_cta};
    selection-color: #ffffff;
}}
QLineEdit:focus    {{ border-color: {_cta}; }}
QLineEdit:disabled {{ color: {_sub}; background: {_s2}; }}

/* ════════════════════════════════════════════════════════════════════════════
   TEXT EDIT / PLAIN TEXT EDIT
════════════════════════════════════════════════════════════════════════════ */
QTextEdit, QPlainTextEdit {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 6px;
    padding: 4px;
    font-size: {f['body']}pt;
    selection-background-color: {_cta};
    selection-color: #ffffff;
}}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {_cta}; }}
QTextEdit#console, QPlainTextEdit#console {{
    font-family: 'Menlo', 'Consolas', 'Courier New', monospace;
    font-size: {f['mono']}pt;
    background: {_dk('#0a0a0c', '#f5f5f7')};
    color: {_dk('#30d158', '#1a4a20')};
    border-color: {_bdr};
}}

/* ════════════════════════════════════════════════════════════════════════════
   SPINBOXES
════════════════════════════════════════════════════════════════════════════ */
QSpinBox, QDoubleSpinBox {{
    background: {_s3};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 6px;
    padding: 4px 6px;
    font-size: {f['body']}pt;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {_cta}; }}
QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {_sub}; background: {_s2}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {_bdr};
    border-bottom: 1px solid {_bdr};
    border-radius: 0 6px 0 0;
    background: {_s2};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid {_bdr};
    border-radius: 0 0 6px 0;
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
    border-radius: 6px;
    padding: 4px 8px;
    font-size: {f['body']}pt;
}}
QComboBox:focus    {{ border-color: {_cta}; }}
QComboBox:disabled {{ color: {_sub}; background: {_s2}; }}
QComboBox::drop-down {{
    border: none;
    width: 26px;
    border-left: 1px solid {_bdr};
    border-radius: 0 6px 6px 0;
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
    border-radius: 6px;
    padding: 2px;
    selection-background-color: {_cta};
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
    border-radius: 4px;
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
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
    background: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    background: transparent;
}}

/* ════════════════════════════════════════════════════════════════════════════
   TAB WIDGET
════════════════════════════════════════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {_bdr};
    border-radius: 0 6px 6px 6px;
    background: {_s};
}}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {_s2};
    color: {_dim};
    border: 1px solid {_bdr};
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 7px 20px;
    font-size: {f['body']}pt;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {_s};
    color: {_text};
    border-bottom: 2px solid {_cta};
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

/* ── Left-panel scroll areas — wider, visible track ─────────────────────── */
QScrollArea#LeftPanelScroll QScrollBar:vertical {{
    background: {_dk('#1a1a1c', '#e8e8ea')};
    width: 10px;
    margin: 2px 0;
    border-radius: 5px;
}}
QScrollArea#LeftPanelScroll QScrollBar::handle:vertical {{
    background: {_dk('#555558', '#b0b0b4')};
    border-radius: 5px;
    min-height: 36px;
}}
QScrollArea#LeftPanelScroll QScrollBar::handle:vertical:hover {{
    background: {_dk('#6e6e72', '#9a9a9e')};
}}
QScrollArea#LeftPanelScroll QScrollBar::add-line:vertical,
QScrollArea#LeftPanelScroll QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
QScrollArea#LeftPanelScroll QScrollBar::add-page:vertical,
QScrollArea#LeftPanelScroll QScrollBar::sub-page:vertical {{ background: none; }}

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
    border-radius: 6px;
    outline: none;
    font-size: {f['body']}pt;
    alternate-background-color: {_s2};
}}
QListWidget::item, QListView::item,
QTreeWidget::item, QTreeView::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
QListWidget::item:hover, QListView::item:hover,
QTreeWidget::item:hover, QTreeView::item:hover {{ background: {_hov}; }}
QListWidget::item:selected, QListView::item:selected,
QTreeWidget::item:selected, QTreeView::item:selected {{
    background: {_cta};
    color: #ffffff;
}}
QTreeView::branch {{ background: {_s}; }}

QTableWidget, QTableView {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 6px;
    gridline-color: {_bdr};
    outline: none;
    font-size: {f['body']}pt;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {_cta};
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
    background: {_s4};
    color: {_dim};
    font-size: {f['caption']}pt;
    border-top: 1px solid {_bdr};
}}
QMenuBar {{
    background: {_s4};
    color: {_dim};
    border-bottom: 1px solid {_bdr};
    font-size: {f['body']}pt;
}}
QMenuBar::item:selected {{ background: {_hov}; color: {_text}; }}
QMenu {{
    background: {_s};
    color: {_text};
    border: 1px solid {_bdr};
    border-radius: 8px;
    padding: 4px;
    font-size: {f['body']}pt;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 4px;
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
    border-radius: 6px;
    padding: 6px 10px;
    font-size: {f['label']}pt;
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


# ══════════════════════════════════════════════════════════════════════════════
#  scaled_qss (backward compatibility)
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  Component helpers
# ══════════════════════════════════════════════════════════════════════════════
#
# These return focused QSS snippets for widgets that need styling beyond the
# base application stylesheet.  All read from PALETTE (the live dict) so they
# automatically reflect the active theme when called inside _apply_styles().


def btn_primary_qss() -> str:
    """Solid blue primary action button (Run, Save, Apply, Export…).

    Uses the CTA blue role — Apple systemBlue — visually distinct from the
    mint-teal accent so user-action buttons read immediately as interactive.
    """
    p, f = PALETTE, FONT
    cta  = p["cta"]
    ctah = p["ctaHover"]
    dark = active_theme() == "dark"
    return f"""
    QPushButton {{
        background: {cta}; color: #ffffff; border: none;
        border-radius: 6px; padding: 6px 16px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover   {{ background: {ctah}; }}
    QPushButton:pressed {{ background: {'#0060d0' if dark else '#0060c0'};
                           padding-top: 7px; padding-bottom: 5px; }}
    QPushButton:disabled {{ background: {'#1c2a3a' if dark else '#c0d8f8'};
                            color: {'#3a5878' if dark else '#6090c8'};
                            border: none; }}
    """


def btn_accent_qss() -> str:
    """Ghost mint-teal accent button — for device/system confirmations.

    Use for actions that confirm a system state (Connect, Apply Calibration,
    Start TEC) where the mint health-colour reinforces the action's meaning.
    Use ``btn_primary_qss()`` for the main user-action CTA instead.
    """
    p, f = PALETTE, FONT
    acc  = p["accent"]
    ahov = p["accentHover"]
    dark = active_theme() == "dark"
    return f"""
    QPushButton {{
        background: {'#00332e' if dark else '#d0f5f0'};
        color: {acc}; border: 1px solid {acc};
        border-radius: 6px; padding: 6px 14px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover   {{ background: {'#004038' if dark else '#b8ede6'};
                           color: {ahov}; border-color: {ahov}; }}
    QPushButton:pressed {{ background: {'#002018' if dark else '#98e0d8'};
                           padding-top: 7px; padding-bottom: 5px; }}
    QPushButton:disabled {{ background: {'#1a2820' if dark else '#e8f5f2'};
                            color: {'#2a4838' if dark else '#7ab8b0'};
                            border-color: {'#1e2e28' if dark else '#b8d8d4'}; }}
    """


def btn_secondary_qss() -> str:
    """Muted secondary button."""
    p, f = PALETTE, FONT
    return f"""
    QPushButton {{
        background: {p['surface2']}; color: {p['textDim']};
        border: 1px solid {p['border']}; border-radius: 6px;
        padding: 6px 14px; font-size: {f['body']}pt;
    }}
    QPushButton:hover   {{ background: {p['surfaceHover']}; color: {p['text']}; }}
    QPushButton:pressed {{ background: {p['bg']}; padding-top: 7px; padding-bottom: 5px; }}
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
        border-radius: 6px; padding: 6px 14px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover   {{ background: {'#3a0c18' if dark else '#f8d0db'}; }}
    QPushButton:pressed {{ background: {'#1a040c' if dark else '#f0bec8'};
                           padding-top: 7px; padding-bottom: 5px; }}
    QPushButton:disabled {{ color: {p['textSub']}; background: {p['surface2']};
                            border-color: {p['border']}; }}
    """


def btn_wizard_primary_qss() -> str:
    """Blue primary button for the first-run wizard."""
    f = FONT
    return f"""
    QPushButton {{
        background: #4188f5; color: #fff; border: none;
        border-radius: 6px; padding: 8px 22px;
        font-size: {f['body']}pt; font-weight: 600;
    }}
    QPushButton:hover    {{ background: #5c9ef7; }}
    QPushButton:pressed  {{ background: #2e68d8; padding-top: 9px; padding-bottom: 7px; }}
    QPushButton:disabled {{ background: #2a3050; color: #5070a0; }}
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
        border: 1px solid {p['border']}; border-radius: 6px;
        padding: 4px 8px; font-size: {f['body']}pt;
        selection-background-color: {p['cta']};
    }}
    QLineEdit:focus, QDoubleSpinBox:focus,
    QSpinBox:focus, QComboBox:focus {{ border-color: {p['cta']}; }}
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
        border: 1px solid #2a3249; border-radius: 6px;
        padding: 6px 10px; font-size: {f['body']}pt;
        selection-background-color: #4188f5;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: #4188f5; }}
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
        border: 1px solid {p['border']}; border-radius: 8px;
        margin-top: 10px; padding-top: 8px; background: transparent;
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
        border-radius: 4px;
        padding: 1px 8px;
        font-size: {f['caption']}pt;
        font-weight: 600;
    }}
    """


def time_estimate_pill_qss() -> str:
    """Solid indigo pill for pre-action time estimates.

    Reverse-text design: solid ``systemIndigo`` background with page-
    coloured (bg) lettering so the pill is impossible to miss.
    Scoped to ``QWidget#TimeEstimatePill`` so it won't leak.
    """
    color = PALETTE.get("systemIndigo", "#5e5ce6")
    bg    = PALETTE.get("bg", "#111113")
    f = FONT
    return f"""
    QWidget#TimeEstimatePill {{
        background: {color};
        border: none;
        border-radius: 14px;
        padding: 4px 16px;
    }}
    QWidget#TimeEstimatePill QLabel {{
        background: transparent;
        border: none;
        color: {bg};
        font-size: {f['body']}pt;
        font-weight: 700;
    }}
    """


def segmented_control_qss() -> str:
    """Base style for Auto/Dark/Light and similar segmented controls.

    Uses the accent teal for the checked state — these are mode selectors,
    not action buttons, so the system-health colour is semantically correct.

    Apply per-button border-radius overrides on top::

        base = segmented_control_qss()
        first_btn.setStyleSheet(base + "QPushButton { border-radius: 6px 0 0 6px; }")
        mid_btn.setStyleSheet(  base + "QPushButton { border-radius: 0; border-left: none; }")
        last_btn.setStyleSheet( base + "QPushButton { border-radius: 0 6px 6px 0; border-left: none; }")
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
        border-radius: 4px;
        padding: 1px 6px;
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
