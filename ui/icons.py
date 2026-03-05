"""
ui/icons.py

Central icon name registry for SanjINSIGHT.
All qtawesome icon names are sourced here — no other file hardcodes them.

Usage:
    from ui.icons import NAV_ICONS, GROUP_ICONS, set_btn_icon
    icon_name = NAV_ICONS["Live"]       # → "fa5s.circle"
    set_btn_icon(self._run_btn, "fa5s.play")
"""
from __future__ import annotations

# ── Sidebar navigation items ──────────────────────────────────────────────────
# Keys match NavItem label exactly (case-sensitive).
NAV_ICONS: dict[str, str] = {
    # MEASURE
    "Live":        "fa5s.circle",
    "Acquire":     "fa5s.camera",
    "Scan":        "fa5s.th",
    "Movie":       "fa5s.film",
    "Transient":   "fa5s.chart-line",
    # ANALYSIS
    "Calibration": "fa5s.balance-scale",
    "Analysis":    "fa5s.chart-bar",
    "Compare":     "fa5s.exchange-alt",
    "3D Surface":  "fa5s.cube",
    # HARDWARE
    "Camera":      "fa5s.camera",
    "Temperature": "fa5s.thermometer-half",
    "FPGA":        "fa5s.microchip",
    "Bias Source": "fa5s.bolt",
    "Stage":       "fa5s.arrows-alt",
    "Prober":      "fa5s.plug",
    "ROI":         "fa5s.crop-alt",
    "Autofocus":   "fa5s.bullseye",
    # SETUP
    "Profiles":    "fa5s.layer-group",
    "Recipes":     "fa5s.clipboard-list",
    # TOOLS
    "Data":        "fa5s.database",
    "Console":     "fa5s.terminal",
    "Log":         "fa5s.scroll",
    "Settings":    "fa5s.cog",
}

# ── Collapsible group header icons ────────────────────────────────────────────
GROUP_ICONS: dict[str, str] = {
    "Hardware": "fa5s.server",
}

# ── Button icon helper ────────────────────────────────────────────────────────

def set_btn_icon(btn, icon_name: str, color: str = "#d0d0d0", size: int = 16) -> None:
    """
    Set a qtawesome vector icon on a QPushButton.

    Silently no-ops if qtawesome is not installed so the app still runs without it.

    Parameters
    ----------
    btn       : QPushButton
    icon_name : str    e.g. "fa5s.play"
    color     : str    hex color string; defaults to the standard text colour
    size      : int    icon pixel size (default 16)
    """
    try:
        import qtawesome as qta
        from PyQt5.QtCore import QSize
        btn.setIcon(qta.icon(icon_name, color=color))
        btn.setIconSize(QSize(size, size))
    except Exception:
        pass
