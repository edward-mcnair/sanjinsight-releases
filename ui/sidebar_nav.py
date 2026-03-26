"""
ui/sidebar_nav.py  —  SanjINSIGHT sidebar navigation

Expanded : full-width panel with section headers + menu items
Collapsed: thin blue accent bar (22px) with a ▶ arrow — click to expand

Toggle lives in the logo header row (◀ arrow, right-aligned).
"""
from __future__ import annotations
from typing import List, Optional, NamedTuple, Dict

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolTip,
    QStackedWidget, QSizePolicy, QScrollArea, QFrame,
)
from PyQt5.QtCore  import Qt, pyqtSignal, QPoint, QEvent
from PyQt5.QtGui   import (
    QColor, QFont, QPainter, QPen, QCursor,
    QPainterPath, QFontMetrics, QPixmap,
)

# ── qtawesome (optional — degrades to unicode glyphs if not installed) ──────
try:
    import qtawesome as qta
    _QTA_AVAILABLE = True
except ImportError:
    qta = None
    _QTA_AVAILABLE = False

# Module-level pixmap cache: (icon_name, color_hex) → QPixmap
_pix_cache: dict = {}

# ── Palette helpers — read PALETTE at call time (survives theme switches) ───
from ui.theme      import PALETTE, FONT as _FONT
from ui.font_utils import sans_font as _sans_font

# These are read at PAINT TIME so they always reflect the current theme.
def _BG():         return PALETTE.get("surface",     "#1a1d28")
def _BG_HOVER():   return PALETTE.get("surfaceHover","#262a38")
def _BG_ACTIVE():  return PALETTE.get("accentDim",   "#00d4aa2e")
def _ACCENT():     return PALETTE.get("accent",      "#00d4aa")
def _TEXT_DIM():   return PALETTE.get("textDim",     "#8892aa")
def _TEXT_NORM():  return PALETTE.get("text",        "#dde3f2")
def _TEXT_WHITE(): return PALETTE.get("text",        "#dde3f2")
def _DIVIDER():    return PALETTE.get("border",      "#2e3245")
def _HDR_BG():     return PALETTE.get("surface4",    "#3a3a3c")

# ── Sizes ──────────────────────────────────────────────────────────
_ITEM_H    = 30    # menu row height
_ITEM_H_COMPACT = 28  # compact item height (Expert mode)
_SECTION_H = 24    # section label height
_COLL_H    = 32    # collapsible group header height
_PHASE_H   = 38    # phase group header height
_PHASE_HINT_H = 20 # guidance hint height (Guided mode)
_PHASE_SEP_H  = 8  # phase separator height
_LOGO_H    = 56    # logo/header area
_W_FULL    = 240   # expanded width
_W_MINI    = 22    # collapsed — thin blue bar

# ── Label aliases (old name → new name) for backward compatibility ─
_LABEL_ALIASES: Dict[str, str] = {
    "Live":       "Live View",
    "Stage":      "Focus & Stage",
    "Autofocus":  "Focus & Stage",
    "Analysis":   "Sessions",
    "Compare":    "Sessions",
    "3D Surface": "Sessions",
}

# ── Fonts ──────────────────────────────────────────────────────────
# Font point sizes are NOT cached here as module-level constants.
# Instead, paintEvent methods read _FONT["body"] etc. at call time so
# they always reflect the DPI-scaled values set by apply_dpi_scale()
# (which runs in main() after QApplication is created).


class NavItem(NamedTuple):
    label: str
    icon:  str
    panel: QWidget
    badge: str = ""


# ================================================================== #
#  _SidebarTooltip  — custom tooltip; bypasses macOS native rendering #
# ================================================================== #
class _SidebarTooltip(QLabel):
    """Singleton styled tooltip for sidebar items.

    Intercepts QEvent.ToolTip on _MenuItem/_CollapseHeader so the
    macOS native tooltip (which ignores QSS) is never shown.
    """
    _inst: Optional["_SidebarTooltip"] = None

    @classmethod
    def get(cls) -> "_SidebarTooltip":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._restyle()

    def _restyle(self):
        self.setStyleSheet(
            f"QLabel {{ background:{PALETTE.get('surface','#1a1d28')}; "
            f"color:{PALETTE.get('text','#dde3f2')}; "
            f"border:1px solid {PALETTE.get('border','#2e3245')}; "
            "border-radius:5px; padding:5px 10px; }}")
        self.setFont(_sans_font(_FONT["body"]))

    def show_tip(self, global_pos: QPoint, text: str):
        self._restyle()
        self.setText(text)
        self.adjustSize()
        self.move(global_pos + QPoint(16, 8))
        self.show()
        self.raise_()

    def hide_tip(self):
        self.hide()


# ================================================================== #
#  _MenuItem                                                          #
# ================================================================== #
class _MenuItem(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, item: NavItem, indent: int = 0, parent=None):
        super().__init__(parent)
        self._item   = item
        self._indent = indent
        self._active = False
        self._hover  = False
        self.setFixedHeight(_ITEM_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip(item.label)

    @property
    def panel(self): return self._item.panel

    def set_active(self, v):
        if self._active != v:
            self._active = v
            self.update()

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            _SidebarTooltip.get().show_tip(e.globalPos(), self._item.label)
            return True          # suppress native tooltip
        return super().event(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        _SidebarTooltip.get().hide_tip()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._item.panel)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if self._active:
            p.fillRect(0, 0, w, h, QColor(_BG_ACTIVE()))
            p.fillRect(0, 0, 3, h, QColor(_ACCENT()))
        elif self._hover:
            p.fillRect(0, 0, w, h, QColor(_BG_HOVER()))
        else:
            p.fillRect(0, 0, w, h, QColor(_BG()))

        x = 18 + self._indent
        icon_col = QColor(_ACCENT() if self._active else
                         (_TEXT_NORM() if self._hover else _TEXT_DIM()))

        icon_name = self._item.icon
        # Remap icons that don't exist in the installed qtawesome version
        # (e.g. "water-opacity" renamed in newer MDI fonts).
        try:
            from ui.icons import _safe_icon
            icon_name = _safe_icon(icon_name)
        except Exception:
            pass
        if _QTA_AVAILABLE and "." in icon_name:
            cache_key = (icon_name, icon_col.name())
            px = _pix_cache.get(cache_key)
            if px is None:
                try:
                    px = qta.icon(icon_name, color=icon_col.name()).pixmap(18, 18)
                except Exception:
                    # Icon name not available in this qtawesome version —
                    # fall back to a safe generic icon.
                    try:
                        px = qta.icon("mdi.circle-medium",
                                      color=icon_col.name()).pixmap(18, 18)
                    except Exception:
                        px = None
                if px is not None:
                    _pix_cache[cache_key] = px
            if px is not None:
                p.drawPixmap(x + 1, (h - 18) // 2, px)
        else:
            p.setFont(_sans_font(_FONT["label"]))
            p.setPen(icon_col)
            p.drawText(x, 0, 26, h, Qt.AlignVCenter | Qt.AlignLeft, icon_name)

        lf = _sans_font(_FONT["body"])
        if self._active:
            lf.setWeight(QFont.DemiBold)
        p.setFont(lf)
        p.setPen(QColor(_TEXT_WHITE() if (self._active or self._hover) else _TEXT_NORM()))
        p.drawText(x + 30, 0, w - x - 38, h,
                   Qt.AlignVCenter | Qt.AlignLeft, self._item.label)

        if self._item.badge:
            bf = _sans_font(_FONT["caption"], bold=True)
            p.setFont(bf)
            fm = QFontMetrics(bf)
            bw = fm.horizontalAdvance(self._item.badge) + 10
            bh = 17
            bx = w - bw - 10
            by = (h - bh) // 2
            path = QPainterPath()
            path.addRoundedRect(bx, by, bw, bh, 8, 8)
            p.fillPath(path, QColor(_ACCENT()))
            p.setPen(QColor("#fff"))
            p.drawText(bx, by, bw, bh, Qt.AlignCenter, self._item.badge)

        p.end()


# ================================================================== #
#  _SectionLabel                                                      #
# ================================================================== #
class _SectionLabel(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self.setFixedHeight(_SECTION_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), self.height(), QColor(_BG()))
        # Thin top rule
        p.setPen(QPen(QColor(_DIVIDER()), 1))
        p.drawLine(16, 8, self.width() - 16, 8)
        # Label — bold, spaced caps, slightly larger than items
        f = _sans_font(_FONT["sublabel"])
        f.setWeight(QFont.Black)          # heaviest weight for visual dominance
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(QColor(_TEXT_NORM()))      # brighter than _TEXT_DIM()
        p.drawText(18, 8, self.width() - 22, _SECTION_H - 8,
                   Qt.AlignVCenter | Qt.AlignLeft, self._title.upper())
        p.end()


# ================================================================== #
#  _CollapseHeader  (Hardware group etc)                              #
# ================================================================== #
class _CollapseHeader(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, icon: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._title     = title
        self._icon      = icon
        self._collapsed = collapsed
        self._hover     = False
        self.setFixedHeight(_COLL_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip(title)

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            _SidebarTooltip.get().show_tip(e.globalPos(), self._title)
            return True          # suppress native tooltip
        return super().event(e)

    def enterEvent(self, e): self._hover = True;  self.update()
    def leaveEvent(self, e):
        self._hover = False
        _SidebarTooltip.get().hide_tip()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._collapsed = not self._collapsed
            self.toggled.emit(self._collapsed)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG_HOVER() if self._hover else _BG()))
        col = QColor(_TEXT_NORM() if self._hover else _TEXT_DIM())

        if _QTA_AVAILABLE and "." in self._icon:
            cache_key = (self._icon, col.name())
            px = _pix_cache.get(cache_key)
            if px is None:
                px = qta.icon(self._icon, color=col.name()).pixmap(18, 18)
                _pix_cache[cache_key] = px
            p.drawPixmap(19, (h - 18) // 2, px)
        else:
            p.setFont(_sans_font(_FONT["label"]))
            p.setPen(col)
            p.drawText(18, 0, 26, h, Qt.AlignVCenter | Qt.AlignLeft, self._icon)

        f = _sans_font(_FONT["body"])
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(col)
        p.drawText(48, 0, w - 70, h, Qt.AlignVCenter | Qt.AlignLeft, self._title)

        p.setFont(_sans_font(_FONT["body"]))
        p.setPen(QColor(_TEXT_NORM()))
        p.drawText(w - 26, 0, 20, h, Qt.AlignVCenter | Qt.AlignLeft,
                   "▾" if not self._collapsed else "▸")
        p.end()


# ================================================================== #
#  _LogoHeader  — app name + collapse arrow                          #
# ================================================================== #
class _LogoHeader(QWidget):
    """Sidebar header containing the workspace mode pill toggle and collapse arrow."""
    collapse_clicked = pyqtSignal()
    mode_clicked = pyqtSignal(str)

    _ARROW_W = 28   # width of the clickable arrow zone on the right

    def __init__(self, app_name: str, parent=None):
        super().__init__(parent)
        self._arrow_hover = False
        self.setFixedHeight(_LOGO_H)
        self.setStyleSheet(f"background:{_HDR_BG()};")
        self.setMouseTracking(True)

        # Layout: [pill toggle] [stretch] [collapse arrow]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 4, 0)
        lay.setSpacing(0)

        # Mode pill toggle (Guided / Standard / Expert)
        self._mode_pill = _ModePill()
        self._mode_pill.mode_clicked.connect(self.mode_clicked)
        lay.addWidget(self._mode_pill)

        lay.addStretch()

        # Collapse arrow
        self._arrow_lbl = QLabel("◀")
        self._arrow_lbl.setFixedWidth(self._ARROW_W)
        self._arrow_lbl.setAlignment(Qt.AlignCenter)
        self._arrow_lbl.setStyleSheet(
            f"color:{_TEXT_DIM()}; font-size:{_FONT['body']}pt; background:transparent;")
        self._arrow_lbl.setCursor(QCursor(Qt.PointingHandCursor))
        lay.addWidget(self._arrow_lbl)

    def mouseMoveEvent(self, e):
        in_arrow = e.x() >= self.width() - self._ARROW_W
        if in_arrow != self._arrow_hover:
            self._arrow_hover = in_arrow
            self._arrow_lbl.setStyleSheet(
                f"color:{_TEXT_WHITE() if in_arrow else _TEXT_DIM()}; "
                f"font-size:{_FONT['body']}pt; background:transparent;")

    def leaveEvent(self, e):
        if self._arrow_hover:
            self._arrow_hover = False
            self._arrow_lbl.setStyleSheet(
                f"color:{_TEXT_DIM()}; font-size:{_FONT['body']}pt; background:transparent;")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if e.x() >= self.width() - self._ARROW_W:
                self.collapse_clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_HDR_BG()))
        # Bottom border
        p.setPen(QPen(QColor(_DIVIDER()), 1))
        p.drawLine(0, h - 1, w, h - 1)
        p.end()

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"background:{_HDR_BG()};")
        self._arrow_lbl.setStyleSheet(
            f"color:{_TEXT_DIM()}; font-size:{_FONT['body']}pt; background:transparent;")
        self._mode_pill._apply_styles()


# ================================================================== #
#  _ModePill  — three-way pill toggle: Guided / Standard / Expert     #
# ================================================================== #
class _ModePill(QWidget):
    """Three-segment pill toggle for workspace mode selection.

    Renders as a rounded-rect track containing three labelled segments.
    The active segment is accent-coloured; inactive ones are dim.
    """
    mode_clicked = pyqtSignal(str)

    _MODES  = ("guided", "standard", "expert")
    _LABELS = ("Guided", "Standard", "Expert")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode_idx = 1  # standard
        self._hover_idx = -1
        self.setFixedSize(198, 28)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip("Workspace mode — click to switch")

    def set_mode(self, mode: str) -> None:
        try:
            self._mode_idx = self._MODES.index(mode)
        except ValueError:
            self._mode_idx = 1
        self.update()

    def _idx_at(self, x: int) -> int:
        seg_w = self.width() / 3
        idx = int(x / seg_w)
        return max(0, min(2, idx))

    def mouseMoveEvent(self, e):
        idx = self._idx_at(e.x())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def leaveEvent(self, e):
        self._hover_idx = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self._idx_at(e.x())
            if idx != self._mode_idx:
                self._mode_idx = idx
                self.mode_clicked.emit(self._MODES[idx])
                self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        seg_w = w / 3

        # Track background
        track = QPainterPath()
        track.addRoundedRect(0.5, 0.5, w - 1, h - 1, h / 2, h / 2)
        p.fillPath(track, QColor(_BG()))
        p.setPen(QPen(QColor(_DIVIDER()), 1))
        p.drawPath(track)

        # Active segment highlight
        ax = self._mode_idx * seg_w + 2
        aw = seg_w - 4
        ah = h - 4
        ay = 2
        pill = QPainterPath()
        pill.addRoundedRect(ax, ay, aw, ah, ah / 2, ah / 2)
        p.fillPath(pill, QColor(_ACCENT()))

        # Labels
        font = _sans_font(_FONT.get("caption", 8), bold=False)
        p.setFont(font)

        for i, label in enumerate(self._LABELS):
            sx = i * seg_w
            if i == self._mode_idx:
                # Active: dark text on accent background
                p.setPen(QColor("#000000"))
                f = _sans_font(_FONT.get("caption", 8), bold=True)
                p.setFont(f)
            elif i == self._hover_idx:
                p.setPen(QColor(_TEXT_NORM()))
                p.setFont(font)
            else:
                p.setPen(QColor(_TEXT_DIM()))
                p.setFont(font)
            p.drawText(int(sx), 0, int(seg_w), h,
                       Qt.AlignCenter, label)

        p.end()

    def _apply_styles(self) -> None:
        self.update()


# ================================================================== #
#  _CollapseBar  — the thin blue bar shown when sidebar is collapsed  #
# ================================================================== #
class _CollapseBar(QWidget):
    expand_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setFixedWidth(_W_MINI)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self.setToolTip("Expand sidebar")

    def enterEvent(self, e): self._hover = True;  self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.expand_clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Blue accent bar fill
        bar_color = QColor(_ACCENT()).lighter(115) if self._hover else QColor(_ACCENT())
        p.fillRect(0, 0, w, h, bar_color)

        # Centred ▶ arrow, vertically centred
        p.setFont(_sans_font(_FONT["caption"], bold=True))
        p.setPen(QColor("#ffffff"))
        p.drawText(0, h // 2 - 40, w, 80, Qt.AlignCenter, "▶")

        p.end()


# ================================================================== #
#  _PhaseHeader  — numbered phase group header                       #
# ================================================================== #
class _PhaseHeader(QWidget):
    """Phase group header: ① CONFIGURATION, ② IMAGE ACQUISITION, etc.

    Shows a numbered circle, uppercase title, and optional completion badge.
    Clickable — toggles visibility of the phase's nav items.
    Hidden entirely in Expert mode.
    """
    toggled = pyqtSignal(bool)   # emits collapsed state

    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        self._number    = number
        self._title     = title
        self._badge     = ""      # e.g. "3/5" or "✓"
        self._collapsed = False
        self._hover     = False
        self.setFixedHeight(_PHASE_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMouseTracking(True)

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed != collapsed:
            self._collapsed = collapsed
            self.toggled.emit(collapsed)
            self.update()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_collapsed(not self._collapsed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(_BG_HOVER() if self._hover else _BG()))

        # Thin top divider (skip for first phase)
        if self._number > 1:
            p.setPen(QPen(QColor(_DIVIDER()), 1))
            p.drawLine(16, 4, w - 16, 4)

        # ── Numbered circle (20×20) ─────────────────────────────
        cx, cy, cr = 18, (h - 20) // 2 + 2, 10
        circle_path = QPainterPath()
        circle_path.addEllipse(cx, cy, cr * 2, cr * 2)

        if self._badge == "✓":
            # Completed: filled accent circle with checkmark
            p.fillPath(circle_path, QColor(_ACCENT()))
            p.setFont(_sans_font(_FONT["caption"], bold=True))
            p.setPen(QColor("#ffffff"))
            p.drawText(cx, cy, cr * 2, cr * 2, Qt.AlignCenter, "✓")
        else:
            # Numbered: outlined circle
            p.setPen(QPen(QColor(_ACCENT()), 1.5))
            p.drawPath(circle_path)
            p.setFont(_sans_font(_FONT["caption"], bold=True))
            p.setPen(QColor(_ACCENT()))
            p.drawText(cx, cy, cr * 2, cr * 2, Qt.AlignCenter, str(self._number))

        # ── Title — bold small caps ──────────────────────────────
        tx = cx + cr * 2 + 10
        f = _sans_font(_FONT["sublabel"])
        f.setWeight(QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
        p.setFont(f)
        p.setPen(QColor(_TEXT_NORM()))
        p.drawText(tx, 0, w - tx - 40, h,
                   Qt.AlignVCenter | Qt.AlignLeft, self._title.upper())

        # ── Badge pill (right side, e.g. "3/5") ─────────────────
        if self._badge and self._badge != "✓":
            bf = _sans_font(_FONT["caption"])
            p.setFont(bf)
            fm = QFontMetrics(bf)
            bw = fm.horizontalAdvance(self._badge) + 10
            bh = 16
            bx = w - bw - 30
            by = (h - bh) // 2
            badge_path = QPainterPath()
            badge_path.addRoundedRect(bx, by, bw, bh, 8, 8)
            p.fillPath(badge_path, QColor(PALETTE.get("surface2", "#2a2d3a")))
            p.setPen(QColor(_TEXT_DIM()))
            p.drawText(bx, by, bw, bh, Qt.AlignCenter, self._badge)

        # ── Collapse chevron ─────────────────────────────────────
        p.setFont(_sans_font(_FONT["body"]))
        p.setPen(QColor(_TEXT_DIM()))
        p.drawText(w - 24, 0, 20, h, Qt.AlignVCenter | Qt.AlignLeft,
                   "▸" if self._collapsed else "▾")

        p.end()


# ================================================================== #
#  _PhaseHint  — guidance text below phase header (Guided mode only)  #
# ================================================================== #
class _PhaseHint(QWidget):
    """Small text hint shown below a phase header in Guided mode."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(_PHASE_HINT_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG()))
        f = _sans_font(_FONT["caption"])
        f.setItalic(True)
        p.setFont(f)
        p.setPen(QColor(_TEXT_DIM()))
        p.drawText(50, 0, w - 60, h,
                   Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()


# ================================================================== #
#  _PhaseSeparator  — thin divider between phase groups               #
# ================================================================== #
class _PhaseSeparator(QWidget):
    """Thin horizontal line separating phase groups from SYSTEM."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_PHASE_SEP_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG()))
        p.setPen(QPen(QColor(_DIVIDER()), 1))
        p.drawLine(16, h // 2, w - 16, h // 2)
        p.end()


# ================================================================== #
#  _Sidebar  — the full expandable panel                             #
# ================================================================== #
class _Sidebar(QWidget):
    item_selected    = pyqtSignal(object)
    collapse_clicked = pyqtSignal()
    mode_changed     = pyqtSignal(str)

    def __init__(self, app_name: str = "SanjINSIGHT", parent=None):
        super().__init__(parent)
        self._items:       List[_MenuItem]       = []
        self._sections:    List[_SectionLabel]   = []
        self._cheaders:    List[_CollapseHeader] = []
        self._containers:  List[QWidget]         = []
        self._coll_states: List[bool]            = []
        self._active:      Optional[_MenuItem]   = None

        # Phase-aware state
        self._phase_headers:    List[_PhaseHeader]  = []
        self._phase_hints:      List[_PhaseHint]    = []
        self._phase_containers: List[QWidget]       = []
        self._phase_separators: List[_PhaseSeparator] = []
        self._workspace_mode:   str = "standard"

        self.setFixedWidth(_W_FULL)
        self.setStyleSheet(f"background:{_BG()};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Logo header with built-in collapse arrow + mode indicator
        self._logo_hdr = _LogoHeader(app_name)
        self._logo_hdr.collapse_clicked.connect(self.collapse_clicked)
        self._logo_hdr.mode_clicked.connect(
            lambda mode: self.mode_changed.emit(mode))
        root.addWidget(self._logo_hdr)

        # Scrollable menu
        self._scroll = QScrollArea()
        scroll = self._scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        self._restyle_scroll()
        self._menu_w = QWidget()
        self._menu_w.setStyleSheet(f"background:{_BG()};")
        self._lay = QVBoxLayout(self._menu_w)
        self._lay.setContentsMargins(0, 4, 0, 4)
        self._lay.setSpacing(0)
        scroll.setWidget(self._menu_w)
        root.addWidget(scroll, 1)

    def _restyle_scroll(self) -> None:
        """Re-apply PALETTE-aware stylesheet to the scroll area and its bar."""
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background:{_BG()}; border:none; }}"
            f"QScrollBar:vertical {{ background:{_BG()}; width:5px; margin:0; }}"
            f"QScrollBar::handle:vertical {{ background:{PALETTE.get('border2','#3d3d3d')};"
            " border-radius:2px; min-height:20px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
        )

    # ── Phase-aware group builders ───────────────────────────────────

    def add_phase(self, number: int, title: str, hint: str,
                  items: List[NavItem]) -> None:
        """Add a phase group with numbered header, hint, and nav items."""
        header = _PhaseHeader(number, title)
        self._phase_headers.append(header)
        self._lay.addWidget(header)

        hint_w = _PhaseHint(hint)
        hint_w.setVisible(self._workspace_mode == "guided")
        self._phase_hints.append(hint_w)
        self._lay.addWidget(hint_w)

        # Container for the phase's nav items
        container = QWidget()
        container.setStyleSheet(f"background:{_BG()};")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        for item in items:
            mi = _MenuItem(item)
            mi.clicked.connect(self._on_click)
            self._items.append(mi)
            cl.addWidget(mi)
        self._phase_containers.append(container)
        self._lay.addWidget(container)

        # Wire header collapse to container visibility
        header.toggled.connect(lambda col, _c=container: _c.setVisible(not col))

    def add_separator(self) -> None:
        """Add a thin horizontal separator (used before SYSTEM group)."""
        sep = _PhaseSeparator()
        self._phase_separators.append(sep)
        self._lay.addWidget(sep)

    def set_workspace_mode(self, mode: str) -> None:
        """Reconfigure sidebar presentation for the given workspace mode."""
        self._workspace_mode = mode
        self._logo_hdr._mode_pill.set_mode(mode)

        for header in self._phase_headers:
            if mode == "expert":
                header.setVisible(False)
            else:
                header.setVisible(True)
                # In Guided mode, collapse non-active phases
                if mode == "guided" and self._active:
                    active_in_phase = False
                    idx = self._phase_headers.index(header)
                    if idx < len(self._phase_containers):
                        container = self._phase_containers[idx]
                        for mi in self._items:
                            if mi.parent() is container and mi._active:
                                active_in_phase = True
                                break
                    if not active_in_phase:
                        header.set_collapsed(True)
                    else:
                        header.set_collapsed(False)
                elif mode == "standard":
                    header.set_collapsed(False)

        for hint in self._phase_hints:
            hint.setVisible(mode == "guided")

        for sep in self._phase_separators:
            sep.setVisible(mode != "expert")

        # Adjust item height for Expert compact mode
        compact_h = _ITEM_H_COMPACT if mode == "expert" else _ITEM_H
        for mi in self._items:
            mi.setFixedHeight(compact_h)

    def set_phase_badge(self, phase_number: int, text: str) -> None:
        """Update the completion badge on a phase header."""
        for header in self._phase_headers:
            if header._number == phase_number:
                header.set_badge(text)
                break

    # ── Legacy group builders (still used for SYSTEM section) ────

    def add_section(self, title: str, items: List[NavItem]):
        lbl = _SectionLabel(title)
        self._sections.append(lbl)
        self._lay.addWidget(lbl)
        for item in items:
            mi = _MenuItem(item)
            mi.clicked.connect(self._on_click)
            self._items.append(mi)
            self._lay.addWidget(mi)

    def add_collapsible(self, title: str, icon: str,
                        items: List[NavItem], collapsed: bool = False):
        hdr = _CollapseHeader(title, icon, collapsed=collapsed)
        self._cheaders.append(hdr)
        self._coll_states.append(collapsed)

        c = QWidget()
        c.setStyleSheet(f"background:{_BG()};")
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        for item in items:
            mi = _MenuItem(item, indent=14)
            mi.clicked.connect(self._on_click)
            self._items.append(mi)
            cl.addWidget(mi)
        c.setVisible(not collapsed)
        self._containers.append(c)

        idx = len(self._containers) - 1
        hdr.toggled.connect(lambda col, _c=c, _i=idx: (
            self._coll_states.__setitem__(_i, col) or _c.setVisible(not col)
        ))
        self._lay.addWidget(hdr)
        self._lay.addWidget(c)

    def set_item_visible(self, label: str, visible: bool) -> None:
        """Show or hide a specific sidebar item by its label.

        Supports legacy label aliases (e.g. "Live" → "Live View").
        """
        resolved = _LABEL_ALIASES.get(label, label)
        for mi in self._items:
            if mi._item.label == resolved or mi._item.label == label:
                mi.setVisible(visible)
                break

    def finish(self):
        self._lay.addStretch(1)

    # ── Selection ────────────────────────────────────────────────────

    def _on_click(self, panel):
        for mi in self._items:
            mi.set_active(mi.panel is panel)
            if mi.panel is panel:
                self._active = mi
        self.item_selected.emit(panel)

    def select_panel(self, panel):
        for mi in self._items:
            mi.set_active(mi.panel is panel)
            if mi.panel is panel:
                self._active = mi

    def select_first(self):
        if self._items:
            self._on_click(self._items[0].panel)


# ================================================================== #
#  SidebarNav  — public composite widget                             #
# ================================================================== #
class SidebarNav(QWidget):
    """
    Bootstrap-style sidebar that collapses to a thin blue accent bar.

    Expanded : full panel with logo, section headers, menu items.
    Collapsed: 22px blue bar with ▶ — click anywhere to expand.
    Collapse : click the ◀ arrow in the logo header area.
    """
    panel_changed = pyqtSignal(object)
    mode_cycle_requested = pyqtSignal(str)  # from mode indicator in header

    def __init__(self, app_name: str = "SanjINSIGHT", parent=None):
        super().__init__(parent)
        self._mini = False

        self._sidebar = _Sidebar(app_name)
        self._bar     = _CollapseBar()
        self._stack   = QStackedWidget()
        self._stack.setStyleSheet(f"background:{_BG()};")

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.VLine)
        self._sep.setStyleSheet(f"color:{_DIVIDER()}; max-width:1px;")

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._lay.addWidget(self._sidebar)
        self._lay.addWidget(self._sep)
        self._lay.addWidget(self._stack, 1)

        # Collapse bar is hidden by default
        self._bar.setParent(self)
        self._bar.hide()

        self._sidebar.item_selected.connect(self._on_select)
        self._sidebar.collapse_clicked.connect(self._collapse)
        self._sidebar.mode_changed.connect(self.mode_cycle_requested)
        self._bar.expand_clicked.connect(self._expand)

    # ── Public API ──────────────────────────────────────────────────

    def add_section(self, title: str, items: List[NavItem]):
        for item in items:
            if self._stack.indexOf(item.panel) == -1:
                self._stack.addWidget(item.panel)
        self._sidebar.add_section(title, items)

    def add_phase(self, number: int, title: str, hint: str,
                  items: List[NavItem]) -> None:
        """Add a phase group with numbered header and nav items."""
        for item in items:
            if self._stack.indexOf(item.panel) == -1:
                self._stack.addWidget(item.panel)
        self._sidebar.add_phase(number, title, hint, items)

    def add_separator(self) -> None:
        """Add a thin horizontal separator."""
        self._sidebar.add_separator()

    def add_collapsible(self, title: str, icon: str,
                        items: List[NavItem], collapsed: bool = False):
        for item in items:
            if self._stack.indexOf(item.panel) == -1:
                self._stack.addWidget(item.panel)
        self._sidebar.add_collapsible(title, icon, items, collapsed=collapsed)

    def set_workspace_mode(self, mode: str) -> None:
        """Reconfigure sidebar presentation for the given workspace mode."""
        self._sidebar.set_workspace_mode(mode)

    def set_phase_badge(self, phase_number: int, text: str) -> None:
        """Update completion badge on a phase header."""
        self._sidebar.set_phase_badge(phase_number, text)

    def finish(self):       self._sidebar.finish()
    def select_first(self): self._sidebar.select_first()

    def set_item_visible(self, label: str, visible: bool) -> None:
        """Show or hide a specific sidebar item by its label.

        Hidden items appear under the 'Show all…' toggle in their group.
        Call after ``add_collapsible()`` / ``finish()`` with the hardware
        config to suppress unconfigured device entries by default.
        """
        self._sidebar.set_item_visible(label, visible)

    def navigate_to(self, panel: QWidget):
        idx = self._stack.indexOf(panel)
        if idx >= 0:
            self._stack.setCurrentIndex(idx)
            self._sidebar.select_panel(panel)
            self.panel_changed.emit(panel)

    def select_by_label(self, label: str):
        """Navigate to the sidebar item whose label matches (case-insensitive).

        Supports legacy label aliases (e.g. ``"Live"`` → ``"Live View"``).
        """
        resolved = _LABEL_ALIASES.get(label, label)
        for item in self._sidebar._items:
            lbl = item._item.label.lower()
            if lbl == resolved.lower() or lbl == label.lower():
                self.navigate_to(item.panel)
                return

    # ── Theme support ────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Re-apply palette-derived styles after a theme switch."""
        # Clear the pixmap cache so repainted icons use the new accent colour
        _pix_cache.clear()

        # Re-apply stylesheet constants for non-paintEvent elements
        s = self._sidebar
        s.setStyleSheet(f"background:{_BG()};")
        s._menu_w.setStyleSheet(f"background:{_BG()};")
        s._logo_hdr._apply_styles()
        s._restyle_scroll()

        for c in s._containers:
            c.setStyleSheet(f"background:{_BG()};")

        self._stack.setStyleSheet(f"background:{_BG()};")
        self._sep.setStyleSheet(f"color:{_DIVIDER()}; max-width:1px;")

        for c in s._phase_containers:
            c.setStyleSheet(f"background:{_BG()};")

        # Trigger a repaint on all custom-drawn sidebar widgets
        for w in ([s, s._logo_hdr] + s._sections + s._cheaders + s._items
                  + s._phase_headers + s._phase_hints + s._phase_separators):
            w.update()

    # ── Collapse / expand ────────────────────────────────────────────

    def _collapse(self):
        """Hide sidebar, show thin blue bar."""
        self._mini = True
        self._sidebar.hide()
        self._sep.hide()

        # Insert bar at position 0 in the layout
        self._lay.insertWidget(0, self._bar)
        self._bar.show()

    def _expand(self):
        """Restore sidebar, hide bar."""
        self._mini = False
        self._bar.hide()
        self._lay.removeWidget(self._bar)

        self._sidebar.show()
        self._sep.show()

    # ── Internal ────────────────────────────────────────────────────

    def _on_select(self, panel: QWidget):
        idx = self._stack.indexOf(panel)
        if idx >= 0:
            self._stack.setCurrentIndex(idx)
        self.panel_changed.emit(panel)
