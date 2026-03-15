"""
ui/font_utils.py

Cross-platform font helpers for SanjINSIGHT custom widgets.

Inter (preferred)
-----------------
Run ``python scripts/fetch_inter.py`` once to download Inter into
``ui/fonts/``.  On the next launch, ``load_inter()`` detects the files,
registers them with Qt's font database, and sets Inter as the application
default font.  Every QSS rule that specifies only ``font-size`` then
inherits Inter automatically.  Custom-painted widgets (sidebar, headers)
call ``sans_font()`` which returns ``QFont("Inter", …)`` when available.

Platform fallback (no Inter files)
-----------------------------------
If ``ui/fonts/`` is absent or empty the app falls back gracefully:
  * Windows → Segoe UI
  * macOS   → Helvetica Neue
  * Linux   → DejaVu Sans (standard on Debian/Ubuntu/Fedora/Arch)

Monospace
---------
``mono_font()`` always uses the platform monospace font (Consolas /
Menlo); Inter is a proportional typeface and is never used for code or
numeric readout contexts that require a fixed character grid.

Usage
-----
    # Called automatically by theme.apply_dpi_scale():
    from ui.font_utils import load_inter
    load_inter(app)

    # In custom paintEvent:
    from ui.font_utils import sans_font, mono_font
    painter.setFont(sans_font(12))
    painter.setFont(mono_font(13, bold=True))

    # In QSS strings:
    from ui.font_utils import mono_family_css
    label.setStyleSheet(f"font-family: {mono_family_css()}; font-size: 13pt;")
"""
from __future__ import annotations

import os
import sys

from PyQt5.QtGui import QFont, QFontDatabase


# ── Inter state ───────────────────────────────────────────────────────────────

_INTER_AVAILABLE: bool = False


def load_inter(app) -> bool:
    """Load bundled Inter TTF files and set as the application default font.

    Expects files in ``ui/fonts/`` relative to this module.  Call after
    ``QApplication`` is created — ``theme.apply_dpi_scale()`` does this
    automatically, so no manual call is required.

    Returns ``True`` if at least one Inter file loaded; the application
    silently uses the platform fallback font if the directory is absent.
    """
    global _INTER_AVAILABLE
    if _INTER_AVAILABLE:
        return True

    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    if not os.path.isdir(fonts_dir):
        return False

    db = QFontDatabase()
    loaded = 0
    for fname in (
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
        "Inter-Bold.ttf",
    ):
        path = os.path.join(fonts_dir, fname)
        if os.path.exists(path):
            if db.addApplicationFont(path) != -1:
                loaded += 1

    if loaded > 0:
        _INTER_AVAILABLE = True
        # Set Inter as the application default so all Qt widgets that don't
        # explicitly specify a family inherit it from the app font.
        # Import FONT here to avoid a circular import (font_utils ← theme).
        try:
            from ui.theme import FONT
            body_size = FONT.get("body", 13)
        except ImportError:
            body_size = 13
        app.setFont(QFont("Inter", body_size))

    return _INTER_AVAILABLE


def inter_available() -> bool:
    """Return ``True`` if Inter was successfully loaded via ``load_inter()``."""
    return _INTER_AVAILABLE


# ── Sans-serif font helper ────────────────────────────────────────────────────

def sans_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return the UI sans-serif QFont for custom-painted widgets.

    Uses Inter when available (see ``load_inter()``), otherwise returns
    the platform native UI font.  Always sets ``SansSerif`` style-hint so
    Qt's font matcher selects the best available sans-serif family even if
    the named family is absent.

    Use for ``QPainter`` calls inside ``paintEvent`` overrides.  For
    regular Qt widgets styled via QSS, the application default font
    (set by ``load_inter()``) propagates automatically — no explicit call
    is needed there.
    """
    if _INTER_AVAILABLE:
        font = QFont("Inter", point_size)
    elif sys.platform == "win32":
        font = QFont("Segoe UI", point_size)
    elif sys.platform == "darwin":
        font = QFont("Helvetica Neue", point_size)
    else:
        font = QFont("DejaVu Sans", point_size)

    font.setStyleHint(QFont.SansSerif)
    if bold:
        font.setBold(True)
    return font


# ── Monospace font helper ─────────────────────────────────────────────────────

def mono_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return a cross-platform monospace QFont.

    * Windows → Consolas   (built-in since Vista, full Unicode coverage)
    * macOS   → Menlo      (default macOS terminal font since 10.6)
    * Linux   → system monospace via style hint

    The ``Monospace`` style hint ensures Qt picks the best installed
    monospace family even when the named family is absent.
    """
    name = "Consolas" if sys.platform == "win32" else "Menlo"
    font = QFont(name, point_size)
    font.setStyleHint(QFont.Monospace)
    if bold:
        font.setBold(True)
    return font


def mono_family_css() -> str:
    """CSS ``font-family`` string for QSS monospace rules (platform-aware).

    Puts the platform-preferred monospace font first; both chains include
    ``Courier New`` as a universal fallback.

    Example::

        label.setStyleSheet(f"font-family: {mono_family_css()}; font-size: 13pt;")
    """
    if sys.platform == "win32":
        return "'Consolas', 'Menlo', 'Courier New', monospace"
    return "'Menlo', 'Consolas', 'Courier New', monospace"
