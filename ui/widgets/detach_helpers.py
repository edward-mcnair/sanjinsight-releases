"""
ui/widgets/detach_helpers.py

Shared helpers for the app-wide detached-viewer pattern.

Provides:
  - ``DetachableFrame``       — overlay wrapper: places ⧉ on the image's upper-right
  - ``make_detach_button()``  — consistent 24×24 icon button (used by the frame)
  - ``open_detached_viewer()`` — lifecycle helper (create-or-raise, wire closed signal)
  - ``close_all_detached()``  — teardown all tracked viewers (used on quit)
  - ``list_open_viewers()``   — snapshot for session-state persistence
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from PyQt5.QtWidgets import (
    QPushButton, QWidget, QVBoxLayout, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.icons import set_btn_icon
from ui.theme import PALETTE

log = logging.getLogger(__name__)

# ── Global registry of open detached viewers (source_id → viewer) ──────────
_open_viewers: Dict[str, "DetachedViewer"] = {}  # noqa: F821

# ── Source holder registry (source_id → (holder_widget, attr_name)) ──────
# Populated the first time open_detached_viewer() is called for each source.
# Used by session restore to rebind restored viewers to their source tabs.
_source_holders: Dict[str, tuple] = {}

# ── Source-ID → sidebar label mapping for auto-navigate ──────────────────
# When a detached viewer opens, the main app sidebar auto-navigates to the
# corresponding settings tab so the user can adjust parameters.
_SOURCE_ID_TO_NAV: Dict[str, str] = {
    "capture.live":       "Capture",
    "capture.cold":       "Capture",
    "capture.hot":        "Capture",
    "capture.diff":       "Capture",
    "capture.drr":        "Capture",
    "capture.dt":         "Capture",
    "calibration.ct":     "Calibration",
    "calibration.r2":     "Calibration",
    "calibration.res":    "Calibration",
    "session.drr":        "Sessions",
    "session.dt":         "Sessions",
    "session.cold":       "Sessions",
    "session.hot":        "Sessions",
    "session.cmp":        "Sessions",
    "transient.playback": "Transient",
    "movie.playback":     "Movie",
    "analysis.result":    "Sessions",
    "autoscan.live":      "Live View",
    "scan.drr":           "Capture",
    "scan.dt":            "Capture",
    "comparison.a":       "Sessions",
    "comparison.b":       "Sessions",
    "comparison.diff":    "Sessions",
    "surface.3d":         "3D Surface",
    "live_preview.camera": "Live View",
    "operator.live":      "Live View",
    "camera.pane":        "Live View",
}

# Module-level callback set by main_app at startup: fn(nav_label: str) -> None
_navigate_callback: Optional[Callable[[str], None]] = None

# Reentrancy guard — prevents viewer↔sidebar infinite loop
_syncing: bool = False


def set_navigate_callback(cb: Callable[[str], None]) -> None:
    """Register a callback that navigates the sidebar when a viewer opens."""
    global _navigate_callback
    _navigate_callback = cb


def register_source(source_id: str, holder: QWidget, attr: str) -> None:
    """Pre-register a source so session restore can rebind viewers.

    Called by tabs during ``__init__`` for every source_id they own.
    This ensures that if the user quit with a viewer open and restarts,
    the restored viewer gets bound back to the correct tab attribute.
    """
    _source_holders[source_id] = (holder, attr)


def rebind_restored_viewers() -> None:
    """Bind any session-restored viewers to their source tab attributes.

    Called once by MainWindow after all tabs are built and registered.
    For each viewer in ``_open_viewers`` that has a matching entry in
    ``_source_holders``, sets ``holder.attr = viewer`` and wires the
    ``closed`` and ``activated`` signals.
    """
    for source_id, viewer in list(_open_viewers.items()):
        entry = _source_holders.get(source_id)
        if entry is None:
            log.debug("rebind_restored_viewers: no holder for %s", source_id)
            continue
        holder, attr = entry
        # Skip if the tab already owns this viewer (opened normally, not restored)
        if getattr(holder, attr, None) is viewer:
            continue
        # Bind the restored viewer to its source tab
        setattr(holder, attr, viewer)

        def _make_on_closed(h=holder, a=attr, sid=source_id):
            def _on_closed():
                setattr(h, a, None)
                _open_viewers.pop(sid, None)
            return _on_closed

        viewer.closed.connect(_make_on_closed())
        viewer.activated.connect(
            lambda sid=source_id: _auto_navigate(sid))
        log.info("rebind_restored_viewers: bound %s → %s.%s",
                 source_id, type(holder).__name__, attr)


# ── DetachableFrame ─────────────────────────────────────────────────────────

class DetachableFrame(QWidget):
    """Overlay wrapper that places a ⧉ detach button in the upper-right
    corner of any child image widget.

    The button is *always* visible (even when no image data is loaded),
    so the user can pop out a window and have it ready for when data arrives.

    Usage::

        self._live = ImagePane("Live", 500, 375, expanding=True)
        self._live_frame = DetachableFrame(self._live)
        # ... add self._live_frame to your layout instead of self._live
        self._live_frame.detach_requested.connect(self._on_detach_viewer)

    The inner widget is accessible as ``frame.widget``.

    Parameters
    ----------
    child : QWidget
        The image widget to wrap.
    parent : QWidget | None
        Optional parent widget for Qt ownership.
    """

    detach_requested = pyqtSignal()

    # Right + top margin so the button floats inside the image area
    _BTN_MARGIN_R = 4
    _BTN_MARGIN_T = 4

    def __init__(self, child: QWidget,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._child = child

        # Layout: the child fills us completely
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        child.setParent(self)
        lay.addWidget(child)

        # Mirror the child's size policy so layout behaviour is unchanged
        self.setSizePolicy(child.sizePolicy())
        if child.minimumSize().width() > 0:
            self.setMinimumSize(child.minimumSize())

        # The detach button — overlay on top of the child
        self._btn = QPushButton(self)
        set_btn_icon(self._btn, "mdi.open-in-new", PALETTE["textDim"])
        self._btn.setFixedSize(22, 22)
        self._btn.setToolTip(
            "Pop out to separate window  ·  F11 for full screen")
        self._btn.setFlat(True)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {PALETTE.get('surface', '#2a2a2a')};"
            f" border: 1px solid {PALETTE.get('border', '#3a3a3a')};"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {PALETTE.get('surfaceHover', '#3a3a3a')}; }}")
        self._btn.clicked.connect(self.detach_requested.emit)

        # Position the button (initial placement)
        self._reposition_btn()
        self._btn.raise_()

    @property
    def widget(self) -> QWidget:
        """The wrapped image widget."""
        return self._child

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_btn()

    def _reposition_btn(self) -> None:
        """Move the ⧉ button to the upper-right corner of our rect."""
        x = self.width() - self._btn.width() - self._BTN_MARGIN_R
        y = self._BTN_MARGIN_T
        self._btn.move(max(0, x), y)
        self._btn.raise_()

    def _apply_styles(self) -> None:
        """Refresh button styles from current PALETTE."""
        set_btn_icon(self._btn, "mdi.open-in-new", PALETTE["textDim"])
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {PALETTE.get('surface', '#2a2a2a')};"
            f" border: 1px solid {PALETTE.get('border', '#3a3a3a')};"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {PALETTE.get('surfaceHover', '#3a3a3a')}; }}")
        # Also propagate to child if it has _apply_styles
        if hasattr(self._child, '_apply_styles'):
            self._child._apply_styles()


# ── make_detach_button ──────────────────────────────────────────────────────

def make_detach_button(parent: QWidget | None = None) -> QPushButton:
    """Create a standard 24×24 detach button with the ``open-in-new`` icon.

    .. note:: Prefer ``DetachableFrame`` for new code.  This function
       is kept for backwards compatibility with toolbar-style layouts.
    """
    btn = QPushButton(parent)
    set_btn_icon(btn, "mdi.open-in-new", PALETTE["textDim"])
    btn.setFixedSize(24, 24)
    btn.setToolTip(
        "Pop out to separate window  ·  F11 for full screen")
    btn.setFlat(True)
    return btn


# ── Auto-navigate helper ──────────────────────────────────────────────────

def _auto_navigate(source_id: str) -> None:
    """Switch the main app sidebar to the tab owning *source_id*."""
    global _syncing
    if _syncing or _navigate_callback is None:
        return
    nav_label = _SOURCE_ID_TO_NAV.get(source_id)
    if nav_label is None:
        prefix = source_id.split(".")[0]
        for sid, label in _SOURCE_ID_TO_NAV.items():
            if sid.startswith(prefix + "."):
                nav_label = label
                break
    if nav_label is not None:
        _syncing = True
        try:
            _navigate_callback(nav_label)
        except Exception:
            log.debug("_auto_navigate(%s) failed", source_id, exc_info=True)
        finally:
            _syncing = False


def raise_viewers_for_label(nav_label: str) -> None:
    """Bring all open detached viewers associated with *nav_label* to front.

    Called by the main app when the user selects a sidebar item, so that
    the corresponding pop-out windows become visible alongside the settings.
    """
    global _syncing
    if _syncing:
        return
    _syncing = True
    try:
        for source_id, label in _SOURCE_ID_TO_NAV.items():
            if label == nav_label and source_id in _open_viewers:
                viewer = _open_viewers[source_id]
                try:
                    viewer.raise_()
                    viewer.activateWindow()
                except Exception:
                    log.debug("raise_viewers_for_label: %s failed",
                              source_id, exc_info=True)
    finally:
        _syncing = False


# ── open_detached_viewer ────────────────────────────────────────────────────

def open_detached_viewer(
    holder: QWidget,
    attr: str,
    source_id: str,
    title: str,
    *,
    initial_push: Callable[["DetachedViewer"], None] | None = None,  # noqa: F821
    static: bool = False,
) -> "DetachedViewer":  # noqa: F821
    """Open (or bring-to-front) a :class:`DetachedViewer` owned by *holder*.

    Parameters
    ----------
    holder : QWidget
        The tab/panel that owns this viewer.  The viewer reference is stored
        as ``holder.<attr>`` and cleaned up on close.
    attr : str
        Attribute name on *holder* for the viewer reference,
        e.g. ``"_detached_viewer"``.
    source_id : str
        Unique key like ``"capture.live"`` or ``"calibration.ct"``.
        Used for geometry persistence and session restore.
    title : str
        Window title suffix, e.g. ``"Capture — Live Feed"``.
    initial_push : callable, optional
        ``fn(viewer)`` — called once after creation to push the current
        image into the new viewer.
    static : bool
        If True, the viewer is put into static/snapshot mode (hides the
        "← Source" colormap option and shows a "Snapshot" badge).

    Returns
    -------
    DetachedViewer
        The (possibly pre-existing) viewer window.
    """
    # Always record the holder so session restore can rebind
    _source_holders[source_id] = (holder, attr)

    existing = getattr(holder, attr, None)
    if existing is not None:
        existing.raise_()
        existing.activateWindow()
        _auto_navigate(source_id)
        return existing

    from ui.widgets.detached_viewer import DetachedViewer

    viewer = DetachedViewer(title, source_id=source_id)

    if static:
        viewer.set_static_mode(True)

    def _on_closed():
        setattr(holder, attr, None)
        _open_viewers.pop(source_id, None)

    viewer.closed.connect(_on_closed)
    viewer.activated.connect(lambda: _auto_navigate(source_id))
    setattr(holder, attr, viewer)
    _open_viewers[source_id] = viewer
    viewer.show()
    _auto_navigate(source_id)

    if initial_push is not None:
        try:
            initial_push(viewer)
        except Exception:
            log.debug("initial_push failed for %s", source_id, exc_info=True)

    return viewer


# ── Utilities ───────────────────────────────────────────────────────────────

def close_all_detached() -> None:
    """Close every open detached viewer.  Called during app shutdown."""
    for sid in list(_open_viewers):
        viewer = _open_viewers.pop(sid, None)
        if viewer is not None:
            try:
                viewer.close()
            except Exception:
                log.debug("close_all_detached: %s failed", sid, exc_info=True)


def list_open_viewers() -> list[dict]:
    """Return a snapshot of all open viewers for session persistence.

    Each entry is ``{"source_id": str, "title": str, "geometry": str}``
    where *geometry* is hex-encoded ``QByteArray``.
    """
    result = []
    for sid, viewer in _open_viewers.items():
        try:
            geo_hex = viewer.saveGeometry().toHex().data().decode()
            result.append({
                "source_id": sid,
                "title": viewer.windowTitle().replace(
                    "SanjINSIGHT \u2014 ", ""),
                "geometry": geo_hex,
            })
        except Exception:
            log.debug("list_open_viewers: %s failed", sid, exc_info=True)
    return result
