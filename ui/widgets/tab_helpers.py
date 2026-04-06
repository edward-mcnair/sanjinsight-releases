"""
ui/widgets/tab_helpers.py

Shared helper functions for hardware / container tabs, eliminating
duplicated _readout(), _sub(), and _inner_tab_qss() across the codebase.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.theme import FONT, MONO_FONT, PALETTE


# ── Readout widget ────────────────────────────────────────────────────

def make_readout(
    label: str,
    value: str = "---",
    color: str | None = None,
    *,
    pal_key: str | None = None,
    font_key: str = "readout",
) -> QWidget:
    """Create a labelled readout widget (label over value).

    Parameters
    ----------
    label:
        Dimmed subscript text shown above the value.
    value:
        Initial display text (e.g. ``"---"``).
    color:
        Explicit CSS colour string.  Mutually exclusive with *pal_key*.
    pal_key:
        Key into ``PALETTE`` — resolved at call-time so ``_apply_styles``
        can refresh it later.  Stored on ``w._pal_key``.
    font_key:
        Key into ``FONT`` for the value size (default ``"readout"``).
        Pass ``"readoutLg"`` or ``"readoutSm"`` as needed.
    """
    if pal_key is not None:
        resolved_color = PALETTE.get(pal_key, "#00d4aa")
    elif color is not None:
        resolved_color = color
    else:
        resolved_color = PALETTE.get("accent", "#00d4aa")

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignCenter)

    sub = QLabel(label)
    sub.setObjectName("sublabel")
    sub.setAlignment(Qt.AlignCenter)

    val = QLabel(value)
    val.setAlignment(Qt.AlignCenter)
    val.setStyleSheet(
        f"font-family:{MONO_FONT}; font-size:{FONT[font_key]}pt; "
        f"color:{resolved_color};")

    lay.addWidget(sub)
    lay.addWidget(val)

    w._val = val                          # noqa: SLF001  (tab convention)
    if pal_key is not None:
        w._pal_key = pal_key              # noqa: SLF001
    return w


# ── Sub-label widget ─────────────────────────────────────────────────

def make_sub(text: str) -> QLabel:
    """Return a dimmed subscript / field-label consistent across tabs."""
    lbl = QLabel(text)
    lbl.setObjectName("sublabel")
    return lbl


# ── Inner-tab QSS (container tabs) ──────────────────────────────────

def inner_tab_qss() -> str:
    """QSS for a ``QTabWidget`` embedded inside a container tab.

    Used by CaptureTab, TransientCaptureTab, CameraControlTab,
    StimulusTab, LibraryTab, FocusStageTab, etc.
    """
    P = PALETTE
    return f"""
        QTabWidget::pane {{ border:none; background:{P['bg']}; }}
        QTabBar::tab {{
            background:{P['surface2']}; color:{P['textDim']};
            border:none; border-right:1px solid {P['border']};
            padding:6px 20px; font-size:{FONT['label']}pt;
        }}
        QTabBar::tab:selected {{
            background:{P['surface']}; color:{P['text']};
            border-bottom:2px solid {P['accent']};
        }}
        QTabBar::tab:hover:!selected {{
            background:{P['surfaceHover']}; color:{P['text']};
        }}
    """
