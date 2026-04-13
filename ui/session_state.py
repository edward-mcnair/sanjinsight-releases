"""
ui/session_state.py

Window arrangement persistence — save and restore the user's window layout
across application restarts.

Saved state includes:
  - Main window geometry
  - Active sidebar tab label
  - Content splitter sizes
  - Bottom drawer visibility + height
  - List of open detached viewers (source_id, title, geometry)

The user is prompted on quit (unless they chose "Always Save") and on
startup (unless they chose "Always Restore").

Preferences used:
  ``ui.save_arrangement``   — "ask" (default) | "always" | "never"
  ``ui.restore_arrangement`` — "ask" (default) | "always" | "never"
  ``ui.window_arrangement``  — dict with full saved state
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class ViewerSnapshot:
    """One open detached viewer."""
    source_id: str
    title: str
    geometry: str       # hex-encoded QByteArray


@dataclass
class WindowArrangement:
    """Full window layout snapshot."""
    main_geometry: str = ""             # hex-encoded
    sidebar_tab: str = ""               # label of the active sidebar entry
    content_splitter: List[int] = field(default_factory=list)
    drawer_visible: bool = False
    drawer_height: int = 200
    detached_viewers: List[dict] = field(default_factory=list)


# ── Save ──────────────────────────────────────────────────────────────────

def save_window_arrangement(main_window) -> None:
    """Capture the current window arrangement and persist to prefs.

    Called from ``MainWindow.closeEvent`` (after checking user preference).
    """
    import config as _cfg
    from ui.widgets.detach_helpers import list_open_viewers

    arr = WindowArrangement()

    # Main window geometry
    try:
        arr.main_geometry = (
            main_window.saveGeometry().toHex().data().decode())
    except Exception:
        log.debug("save_window_arrangement: geometry failed", exc_info=True)

    # Active sidebar tab
    try:
        nav = main_window._nav
        sel = getattr(nav, "current_label", None)
        if callable(sel):
            arr.sidebar_tab = sel() or ""
        else:
            arr.sidebar_tab = str(sel) if sel else ""
    except Exception:
        log.debug("save_window_arrangement: sidebar_tab failed", exc_info=True)

    # Content splitter (main area vs bottom drawer)
    try:
        splitter = main_window._content_splitter
        arr.content_splitter = list(splitter.sizes())
    except Exception:
        log.debug("save_window_arrangement: splitter failed", exc_info=True)

    # Bottom drawer
    try:
        drawer = main_window._bottom_drawer
        arr.drawer_visible = drawer.isVisible()
        arr.drawer_height = drawer.height() if drawer.isVisible() else 200
    except Exception:
        log.debug("save_window_arrangement: drawer failed", exc_info=True)

    # Detached viewers
    arr.detached_viewers = list_open_viewers()

    _cfg.set_pref("ui.window_arrangement", asdict(arr))
    log.info("Window arrangement saved (%d detached viewers)",
             len(arr.detached_viewers))


def restore_window_arrangement(main_window) -> bool:
    """Restore a previously saved window arrangement.

    Returns True if arrangement was restored, False if nothing to restore.
    Called from ``MainWindow`` during startup (after UI is built).
    """
    import config as _cfg
    from PyQt5.QtCore import QByteArray

    raw = _cfg.get_pref("ui.window_arrangement", None)
    if not raw or not isinstance(raw, dict):
        return False

    arr = WindowArrangement(**{
        k: raw[k] for k in WindowArrangement.__dataclass_fields__
        if k in raw
    })

    restored_any = False

    # Main window geometry
    if arr.main_geometry:
        try:
            main_window.restoreGeometry(
                QByteArray.fromHex(arr.main_geometry.encode()))
            restored_any = True
        except Exception:
            log.debug("restore: geometry failed", exc_info=True)

    # Sidebar tab
    if arr.sidebar_tab:
        try:
            main_window._nav.select_by_label(arr.sidebar_tab)
            restored_any = True
        except Exception:
            log.debug("restore: sidebar_tab failed", exc_info=True)

    # Content splitter
    if arr.content_splitter:
        try:
            main_window._content_splitter.setSizes(arr.content_splitter)
            restored_any = True
        except Exception:
            log.debug("restore: splitter failed", exc_info=True)

    # Detached viewers — reopen at saved positions
    # They'll show "No image" until their source tab pushes data.
    if arr.detached_viewers:
        try:
            from ui.widgets.detached_viewer import DetachedViewer
            from ui.widgets.detach_helpers import _open_viewers
            for vs in arr.detached_viewers:
                sid = vs.get("source_id", "")
                title = vs.get("title", "Viewer")
                geo = vs.get("geometry", "")
                if not sid:
                    continue
                viewer = DetachedViewer(title, source_id=sid)
                if geo:
                    viewer.restoreGeometry(
                        QByteArray.fromHex(geo.encode()))
                _open_viewers[sid] = viewer
                viewer.show()
                restored_any = True
            log.info("Restored %d detached viewers",
                     len(arr.detached_viewers))
        except Exception:
            log.debug("restore: detached viewers failed", exc_info=True)

    return restored_any


# ── User prompts ──────────────────────────────────────────────────────────

def should_save_arrangement() -> bool:
    """Check preference and optionally prompt the user.

    Returns True if the arrangement should be saved.
    """
    import config as _cfg
    pref = _cfg.get_pref("ui.save_arrangement", "ask")

    if pref == "always":
        return True
    if pref == "never":
        return False

    # "ask" — show dialog
    try:
        from PyQt5.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setWindowTitle("Save Window Arrangement")
        msg.setText("Save your current window arrangement for next time?")
        msg.setInformativeText(
            "This includes window positions, open detached viewers, "
            "and sidebar state.")
        btn_save = msg.addButton("Save", QMessageBox.AcceptRole)
        btn_always = msg.addButton("Always Save", QMessageBox.AcceptRole)
        btn_no = msg.addButton("Don't Save", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_save)
        msg.exec_()

        clicked = msg.clickedButton()
        if clicked is btn_always:
            _cfg.set_pref("ui.save_arrangement", "always")
            return True
        if clicked is btn_save:
            return True
        return False
    except Exception:
        log.debug("should_save_arrangement: dialog failed", exc_info=True)
        return False


def should_restore_arrangement() -> bool:
    """Check preference and optionally prompt the user.

    Returns True if the arrangement should be restored.
    """
    import config as _cfg

    # Nothing to restore?
    raw = _cfg.get_pref("ui.window_arrangement", None)
    if not raw or not isinstance(raw, dict):
        return False

    pref = _cfg.get_pref("ui.restore_arrangement", "ask")

    if pref == "always":
        return True
    if pref == "never":
        return False

    # "ask" — show dialog
    try:
        from PyQt5.QtWidgets import QMessageBox
        n_viewers = len(raw.get("detached_viewers", []))
        detail = ""
        if n_viewers:
            detail = f"\n\nIncludes {n_viewers} detached viewer window(s)."

        msg = QMessageBox()
        msg.setWindowTitle("Restore Window Arrangement")
        msg.setText(
            "A saved window arrangement was found.\n"
            "Restore it?" + detail)
        btn_yes = msg.addButton("Restore", QMessageBox.AcceptRole)
        btn_always = msg.addButton("Always Restore", QMessageBox.AcceptRole)
        btn_no = msg.addButton("Skip", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_yes)
        msg.exec_()

        clicked = msg.clickedButton()
        if clicked is btn_always:
            _cfg.set_pref("ui.restore_arrangement", "always")
            return True
        if clicked is btn_yes:
            return True
        return False
    except Exception:
        log.debug("should_restore_arrangement: dialog failed", exc_info=True)
        return False
