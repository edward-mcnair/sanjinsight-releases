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

Solution
--------
Use a platform-aware name *and* set ``setStyleHint`` so Qt's font matcher
knows the desired logical class (monospace / sans-serif).  Both measures
together ensure the closest matching installed font is always selected.

Usage
-----
    from ui.font_utils import mono_font

    p.setFont(mono_font(11))        # monospace, 11 pt
    p.setFont(mono_font(9))         # smaller
    fmt.setFont(mono_font(11, bold=True))
"""
from __future__ import annotations

import sys
from PyQt5.QtGui import QFont


def sans_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return a cross-platform sans-serif QFont.

    * Windows  → Segoe UI   (Windows default UI font since Vista)
    * macOS    → Helvetica  (macOS default sans-serif)
    * Linux    → system sans-serif via style hint

    Use for large status/placeholder labels drawn in paintEvent.
    For regular widget labels, prefer the Qt stylesheet ``font-size`` property.
    """
    name = "Segoe UI" if sys.platform == "win32" else "Helvetica"
    font = QFont(name, point_size)
    font.setStyleHint(QFont.SansSerif)
    if bold:
        font.setBold(True)
    return font


def mono_font(point_size: int = 11, bold: bool = False) -> QFont:
    """Return a cross-platform monospace QFont.

    * Windows  → Consolas   (built-in since Vista, full Unicode coverage)
    * macOS    → Menlo      (default macOS terminal font)
    * Linux    → system monospace fallback via style hint

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
