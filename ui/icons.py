"""
ui/icons.py  —  Central icon registry for SanjINSIGHT.

All icon names are Material Design Icons (mdi.*) via qtawesome.
No other file hardcodes icon names.

Usage
-----
    from ui.icons import NAV_ICONS, GROUP_ICONS, set_btn_icon, make_icon

    icon_name = NAV_ICONS["Live"]          # → "mdi.circle-medium"
    set_btn_icon(self._run_btn, IC.PLAY)   # colour from active PALETTE
    icon = make_icon(IC.SAVE, color=PALETTE['accent'], size=20)

Migration note
--------------
Legacy ``fa5s.*`` names passed to ``set_btn_icon`` / ``make_icon`` are
automatically mapped to their MDI equivalents via ``_FA5_TO_MDI``.
No call-site changes are required immediately — update them over time.
"""
from __future__ import annotations


# ── Icon name constants ───────────────────────────────────────────────────────
# Use these in widget code instead of string literals so IDE completion works
# and renames are mechanical.

class IC:
    """MDI icon name constants."""
    # Acquisition / workflow
    LIVE          = "mdi.circle"
    CAPTURE       = "mdi.camera-plus-outline"
    SCAN_GRID     = "mdi.view-grid-outline"
    MOVIE         = "mdi.filmstrip"
    TRANSIENT     = "mdi.waveform"
    # Analysis
    CALIBRATION   = "mdi.scale-balance"
    ANALYSIS      = "mdi.chart-bar"
    SESSIONS      = "mdi.archive-outline"
    COMPARE       = "mdi.compare"
    SURFACE_3D    = "mdi.cube-outline"
    # Hardware
    CAMERA        = "mdi.camera"
    STIMULUS      = "mdi.sine-wave"
    TEMPERATURE   = "mdi.thermometer"
    FPGA          = "mdi.chip"
    BIAS          = "mdi.lightning-bolt"
    STAGE         = "mdi.arrow-all"
    PROBER        = "mdi.needle"
    ROI           = "mdi.crop"
    AUTOFOCUS     = "mdi.crosshairs-gps"
    # Setup / library
    LIBRARY       = "mdi.bookshelf"
    PROFILES      = "mdi.layers"
    RECIPES       = "mdi.clipboard-list-outline"
    # Tools
    DATA          = "mdi.database"
    CONSOLE       = "mdi.console"
    LOG           = "mdi.file-document-outline"
    SETTINGS      = "mdi.cog-outline"
    # Hardware group header
    HARDWARE      = "mdi.server"
    # AutoScan mode
    NEW_SCAN      = "mdi.magnify-scan"
    HISTORY       = "mdi.history"
    # Actions — playback / control
    PLAY          = "mdi.play"
    STOP          = "mdi.stop"
    PAUSE         = "mdi.pause"
    FREEZE        = "mdi.snowflake"
    ABORT         = "mdi.stop-circle-outline"
    # Actions — file / data
    SAVE          = "mdi.content-save"
    SAVE_AS       = "mdi.content-save-edit-outline"
    EXPORT        = "mdi.export"
    EXPORT_PDF    = "mdi.file-pdf-box"
    EXPORT_CSV    = "mdi.file-delimited-outline"
    EXPORT_IMG    = "mdi.image-outline"
    OPEN_FOLDER   = "mdi.folder-open-outline"
    FOLDER        = "mdi.folder-outline"
    FILE          = "mdi.file-outline"
    # Actions — edit
    ADD           = "mdi.plus"
    DELETE        = "mdi.trash-can-outline"
    EDIT          = "mdi.pencil"
    RENAME        = "mdi.pencil-outline"
    DUPLICATE     = "mdi.content-copy"
    UNDO          = "mdi.undo"
    REDO          = "mdi.redo"
    # Actions — navigation / view
    REFRESH       = "mdi.refresh"
    SYNC          = "mdi.sync"
    HOME          = "mdi.home"
    ARROW_UP      = "mdi.arrow-up"
    ARROW_DOWN    = "mdi.arrow-down"
    ARROW_LEFT    = "mdi.arrow-left"
    ARROW_RIGHT   = "mdi.arrow-right"
    # Semantic / status
    CHECK         = "mdi.check"
    CLOSE         = "mdi.close"
    WARNING       = "mdi.alert-outline"
    ERROR         = "mdi.close-circle-outline"
    INFO          = "mdi.information-outline"
    LINK_OFF      = "mdi.link-off"
    FIRE          = "mdi.fire"
    TIMER         = "mdi.timer-outline"
    # UI elements
    NOTE          = "mdi.note-text-outline"
    CHART_LINE    = "mdi.chart-line"
    CHART_BAR     = "mdi.chart-bar"
    DATABASE      = "mdi.database"
    EMAIL         = "mdi.email-outline"
    SEND          = "mdi.send"
    STETHOSCOPE   = "mdi.stethoscope"
    DEVICE_MGR    = "mdi.server"
    # Auth / account
    LOGIN         = "mdi.login"
    LOGOUT        = "mdi.logout"
    USER          = "mdi.account-outline"
    # Search / discovery
    SEARCH        = "mdi.magnify"
    # Keys / credentials
    KEY           = "mdi.key-outline"
    # Hardware connection
    CONNECT       = "mdi.power-plug-outline"
    # Wavelength / spectroscopy
    WAVELENGTH    = "mdi.waves"
    MONOCHROMATOR = "mdi.ray-vertex"
    SPECTRUM      = "mdi.chart-bell-curve-cumulative"
    # Emissivity / IR calibration
    EMISSIVITY    = "mdi.thermometer-lines"
    # IV Sweep / electrical
    IV_SWEEP      = "mdi.current-ac"
    # Timing diagram
    TIMING        = "mdi.timeline-clock-outline"


# ── Sidebar navigation icon registry ─────────────────────────────────────────
# Keys match NavItem label exactly (case-sensitive).

NAV_ICONS: dict[str, str] = {
    # ── Phase 1: CONFIGURATION ────────────────────────────────────────────────
    "Modality":              IC.CAMERA,
    "Stimulus":              IC.STIMULUS,
    "Timing":                IC.TIMING,
    "Temperature":           IC.TEMPERATURE,
    "Acquisition Settings":  "mdi.tune-variant",
    # ── Phase 2: IMAGE ACQUISITION ────────────────────────────────────────────
    "Live View":             IC.LIVE,
    "Focus & Stage":         IC.AUTOFOCUS,
    "Signal Check":          "mdi.signal-cellular-3",
    # ── Phase 3: MEASUREMENT & ANALYSIS ───────────────────────────────────────
    "Capture":               IC.CAPTURE,
    "Calibration":           IC.CALIBRATION,
    "Sessions":              IC.SESSIONS,
    "Emissivity":            IC.EMISSIVITY,
    # ── SYSTEM ────────────────────────────────────────────────────────────────
    "Settings":              IC.SETTINGS,
    # ── Legacy names kept for backward compat during migration ────────────────
    "AutoScan":    IC.NEW_SCAN,
    "Live":        IC.LIVE,
    "Transient":   IC.TRANSIENT,
    "Analysis":    IC.ANALYSIS,
    "Camera":      IC.CAMERA,
    "Wavelength":  IC.WAVELENGTH,
    "Stage":       IC.STAGE,
    "Prober":      IC.PROBER,
    "Library":     IC.LIBRARY,
    "Acquire":     IC.CAPTURE,
    "Scan":        IC.SCAN_GRID,
    "Movie":       IC.MOVIE,
    "Compare":     IC.COMPARE,
    "3D Surface":  IC.SURFACE_3D,
    "IV Sweep":    IC.IV_SWEEP,
    "FPGA":        IC.FPGA,
    "Bias Source": IC.BIAS,
    "ROI":         IC.ROI,
    "Autofocus":   IC.AUTOFOCUS,
    "Profiles":    IC.PROFILES,
    "Recipes":     IC.RECIPES,
    "Data":        IC.DATA,
    "Console":     IC.CONSOLE,
    "Log":         IC.LOG,
}

# ── Collapsible group header icons ────────────────────────────────────────────

GROUP_ICONS: dict[str, str] = {
    "Hardware": IC.HARDWARE,
}

# ── Legacy fa5s → MDI migration map ──────────────────────────────────────────
# set_btn_icon() and make_icon() silently upgrade old names so no call-site
# changes are required immediately.

_FA5_TO_MDI: dict[str, str] = {
    "fa5s.circle":        "mdi.circle-medium",
    "fa5s.camera":        "mdi.camera",
    "fa5s.th":            "mdi.view-grid-outline",
    "fa5s.film":          "mdi.filmstrip",
    "fa5s.chart-line":    "mdi.chart-line",
    "fa5s.balance-scale": "mdi.scale-balance",
    "fa5s.chart-bar":     "mdi.chart-bar",
    "fa5s.exchange-alt":  "mdi.compare",
    "fa5s.cube":          "mdi.cube-outline",
    "fa5s.thermometer-half": "mdi.thermometer",
    "fa5s.microchip":     "mdi.chip",
    "fa5s.bolt":          "mdi.lightning-bolt",
    "fa5s.arrows-alt":    "mdi.arrow-all",
    "fa5s.plug":          "mdi.needle",
    "fa5s.crop-alt":      "mdi.crop",
    "fa5s.bullseye":      "mdi.crosshairs-gps",
    "fa5s.layer-group":   "mdi.layers",
    "fa5s.clipboard-list":"mdi.clipboard-list-outline",
    "fa5s.database":      "mdi.database",
    "fa5s.terminal":      "mdi.console",
    "fa5s.scroll":        "mdi.file-document-outline",
    "fa5s.cog":           "mdi.cog-outline",
    "fa5s.server":        "mdi.server",
    "fa5s.play":          "mdi.play",
    "fa5s.stop":          "mdi.stop",
    "fa5s.snowflake":     "mdi.snowflake",
    "fa5s.undo":          "mdi.undo",
    "fa5s.sync-alt":      "mdi.refresh",
    "fa5s.sync":          "mdi.sync",
    "fa5s.save":          "mdi.content-save",
    "fa5s.file-export":   "mdi.export",
    "fa5s.file-pdf":      "mdi.file-pdf-box",
    "fa5s.unlink":        "mdi.link-off",
    "fa5s.arrow-down":    "mdi.arrow-down",
    "fa5s.arrow-up":      "mdi.arrow-up",
    "fa5s.home":          "mdi.home",
    "fa5s.fire":          "mdi.fire",
    "fa5s.check":         "mdi.check",
    "fa5s.times":         "mdi.close",
    "fa5s.trash":         "mdi.trash-can-outline",
    "fa5s.envelope":      "mdi.email-outline",
    "fa5s.stethoscope":   "mdi.stethoscope",
    "fa5s.info-circle":   "mdi.information-outline",
    "fa5s.paper-plane":   "mdi.send",
    "fa5s.stop-circle":   "mdi.stop-circle-outline",
    "fa5s.folder":        "mdi.folder-outline",
    "fa5s.folder-open":   "mdi.folder-open-outline",
    "fa5s.pencil-alt":    "mdi.pencil",
    "fa5s.sticky-note":   "mdi.note-text-outline",
    "fa5s.image":         "mdi.image-outline",
    "fa5s.plus":          "mdi.plus",
    "fa5s.crosshairs":    "mdi.crosshairs-gps",
    "fa5s.file-alt":      "mdi.file-outline",
}


# ── Icon validation ───────────────────────────────────────────────────────────
# Some MDI icon names were renamed or removed between qtawesome releases.
# Validate all IC.* names at first use and remap any that don't exist in
# the installed qtawesome to a safe fallback.  This prevents crashes inside
# Qt paint events where exceptions may propagate to the global handler.

_VALIDATED = False
_ICON_REMAP: dict[str, str] = {}   # bad_name → fallback_name

def _validate_icons() -> None:
    """One-time check: test every IC.* constant and build remap table."""
    global _VALIDATED
    if _VALIDATED:
        return
    _VALIDATED = True
    try:
        import qtawesome as qta
    except ImportError:
        return
    _SAFE = "mdi.circle-medium"
    for attr in dir(IC):
        if attr.startswith("_"):
            continue
        name = getattr(IC, attr)
        if not isinstance(name, str) or "." not in name:
            continue
        try:
            qta.icon(name, color=PALETTE['text']).pixmap(16, 16)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Icon %r not available in installed qtawesome — "
                "remapping to fallback", name)
            _ICON_REMAP[name] = _SAFE


def _safe_icon(name: str) -> str:
    """Return *name* if valid, or its fallback from the remap table."""
    if not _VALIDATED:
        _validate_icons()
    return _ICON_REMAP.get(name, name)


# ── Icon helpers ──────────────────────────────────────────────────────────────

def make_icon(icon_name: str, color: str | None = None, size: int = 16):
    """Return a QIcon for the given MDI icon name.

    Parameters
    ----------
    icon_name : str
        MDI name (e.g. ``IC.PLAY``) or legacy ``fa5s.*`` name (auto-upgraded).
    color : str | None
        Hex colour string.  Defaults to ``PALETTE['textDim']``.
    size : int
        Pixel size for the icon.

    Returns ``None`` if qtawesome is not installed.
    """
    icon_name = _FA5_TO_MDI.get(icon_name, icon_name)
    icon_name = _safe_icon(icon_name)
    if color is None:
        try:
            from ui.theme import PALETTE
            color = PALETTE['textDim']
        except Exception:
            color = PALETTE['textDim']
    try:
        import qtawesome as qta
        return qta.icon(icon_name, color=color, scale_factor=size / 16)
    except Exception:
        return None


def make_icon_label(
    icon_name: str,
    color: str | None = None,
    size: int = 16,
):
    """Return a QLabel showing the given MDI icon as a flat vector pixmap.

    Use this anywhere you need an icon in a non-button context (dialog headers,
    status badges, inline indicators) instead of a Unicode/emoji character.
    Returns a plain QLabel with no text if qtawesome is unavailable.
    """
    try:
        from PyQt5.QtWidgets import QLabel
        from PyQt5.QtCore import Qt
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        icon = make_icon(icon_name, color=color, size=size)
        if icon:
            lbl.setPixmap(icon.pixmap(size, size))
        return lbl
    except Exception:
        from PyQt5.QtWidgets import QLabel
        return QLabel()


def set_btn_icon(
    btn,
    icon_name: str,
    color: str | None = None,
    size: int = 16,
) -> None:
    """Set a qtawesome MDI vector icon on a QPushButton.

    Silently no-ops if qtawesome is not installed.

    Parameters
    ----------
    btn       : QPushButton
    icon_name : str    MDI name (e.g. ``IC.PLAY``) or legacy ``fa5s.*``
    color     : str | None    hex colour; defaults to ``PALETTE['textDim']``
    size      : int    icon pixel size (default 16)
    """
    icon_name = _FA5_TO_MDI.get(icon_name, icon_name)
    icon_name = _safe_icon(icon_name)
    if color is None:
        try:
            from ui.theme import PALETTE
            color = PALETTE['textDim']
        except Exception:
            color = PALETTE['textDim']
    try:
        import qtawesome as qta
        from PyQt5.QtCore import QSize
        btn.setIcon(qta.icon(icon_name, color=color))
        btn.setIconSize(QSize(size, size))
    except Exception:
        pass
