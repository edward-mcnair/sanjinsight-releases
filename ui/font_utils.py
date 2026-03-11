"""
ui/font_utils.py

Cross-platform font helpers for SanjINSIGHT custom widgets.

Problem
-------
Qt looks up fonts by exact family name.  If the requested family is not
installed, Qt falls back to the application default (proportional UI font)
rather than a logical font class.  On Windows, "Menlo" does not exist, so
every ``QFont("Menlo", ...)`` call in a paintEvent produces misaligned
numbers because Qt silently substitutes Segoe UI.

On macOS, "Segoe UI" does not exist, so every ``QFont("Segoe UI", ...)``
call produces text rendered in whatever proportional fallback the OS picks —
typically Helvetica or Lucida Grande, with different metrics.

Solution
--------
Use a platform-aware name *and* set ``setStyleHint`` so Qt's font matcher
knows the desired logical class (monospace / sans-serif).  Both measures
together ensure the closest matching installed font is always selected.

Usage
-----
    from ui.font_utils import sans_font, mono_font, mono_family_css

    p.setFont(sans_font(11))                  # sans-serif, 11 pt
    p.setFont(mono_font(11))                  # monospace, 11 pt
    lbl.setStyleSheet(f"font-family: {mono_family_css()};")
"""
from __future__ import annotations

import sys
from PyQt5.QtGui import QFont


def sans_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return a cross-platform sans-serif QFont.

    * Windows → Segoe UI        (native Windows UI font since Vista)
    * macOS   → Helvetica Neue  (ships on every macOS since 10.9)
    * Linux   → DejaVu Sans     (present on virtually all Linux distros)

    The ``SansSerif`` style hint is always set so Qt's font matcher picks
    the best installed sans-serif family even if the named family is absent.

    Use for custom-painted labels and headers (``paintEvent``).
    For regular Qt widgets, prefer the stylesheet ``font-size`` property.
    """
    if sys.platform == "win32":
        name = "Segoe UI"
    elif sys.platform == "darwin":
        name = "Helvetica Neue"
    else:
        name = "DejaVu Sans"   # standard on Debian/Ubuntu/Fedora/Arch/etc.
    font = QFont(name, point_size)
    font.setStyleHint(QFont.SansSerif)
    if bold:
        font.setBold(True)
    return font


def mono_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return a cross-platform monospace QFont.

    * Windows → Consolas   (built-in since Vista, full Unicode coverage)
    * macOS   → Menlo      (default macOS terminal font)
    * Linux   → system monospace fallback via style hint

    The ``Monospace`` style hint is always set so Qt's font matcher finds
    the best monospace alternative on any platform even if the named family
    is not present.
    """
    name = "Consolas" if sys.platform == "win32" else "Menlo"
    font = QFont(name, point_size)
    font.setStyleHint(QFont.Monospace)
    if bold:
        font.setBold(True)
    return font


def mono_family_css() -> str:
    """CSS ``font-family`` string for QSS monospace rules (platform-aware).

    Windows gets Consolas first; macOS/Linux get Menlo first.
    Both chains include Courier New as a universal fallback.

    Example::

        lbl.setStyleSheet(f"font-family: {mono_family_css()}; font-size:13pt;")
    """
    if sys.platform == "win32":
        return "'Consolas', 'Menlo', 'Courier New', monospace"
    return "'Menlo', 'Consolas', 'Courier New', monospace"
