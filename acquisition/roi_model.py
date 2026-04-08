"""
acquisition/roi_model.py

Central, shared ROI model — single source of truth for all ROIs across
the application.  Any tab or widget that needs to read/draw/modify ROIs
subscribes to signals on this model.

Usage:
    from acquisition.roi_model import roi_model

    roi_model.add(Roi(100, 80, 400, 300, label="Hotspot A"))
    roi_model.rois          # list of all Roi objects
    roi_model.active_roi    # the currently selected Roi (or None)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from acquisition.roi import Roi, ROI_COLORS

log = logging.getLogger(__name__)

_MAX_ROIS = 16


class RoiModel(QObject):
    """Observable list of ROIs shared across the entire application.

    Signals
    -------
    rois_changed()
        Emitted whenever the ROI list is modified (add/remove/update/clear).
    roi_added(object)
        Emitted with the new ``Roi`` after it is appended.
    roi_removed(str)
        Emitted with the ``uid`` of the removed ROI.
    roi_updated(object)
        Emitted with the modified ``Roi`` after an in-place update.
    active_changed(object)
        Emitted with the newly active ``Roi`` (or ``None``).
    """

    rois_changed   = pyqtSignal()
    roi_added      = pyqtSignal(object)
    roi_removed    = pyqtSignal(str)
    roi_updated    = pyqtSignal(object)
    active_changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rois: List[Roi] = []
        self._active_uid: str = ""

    # ── read access ──────────────────────────────────────────────────

    @property
    def rois(self) -> List[Roi]:
        """Snapshot of the current ROI list (shallow copy)."""
        return list(self._rois)

    @property
    def count(self) -> int:
        return len(self._rois)

    @property
    def active_roi(self) -> Optional[Roi]:
        """The currently selected ROI, or None."""
        if not self._active_uid:
            return None
        for r in self._rois:
            if r.uid == self._active_uid:
                return r
        return None

    @property
    def active_uid(self) -> str:
        return self._active_uid

    def by_uid(self, uid: str) -> Optional[Roi]:
        for r in self._rois:
            if r.uid == uid:
                return r
        return None

    def index_of(self, uid: str) -> int:
        for i, r in enumerate(self._rois):
            if r.uid == uid:
                return i
        return -1

    # ── write access ─────────────────────────────────────────────────

    def add(self, roi: Roi) -> bool:
        """Append an ROI.  Returns False if at capacity or uid duplicated."""
        if len(self._rois) >= _MAX_ROIS:
            log.warning("ROI limit reached (%d)", _MAX_ROIS)
            return False
        if any(r.uid == roi.uid for r in self._rois):
            log.warning("Duplicate ROI uid %s", roi.uid)
            return False
        # Auto-assign colour if blank
        if not roi.color:
            roi.color = ROI_COLORS[len(self._rois) % len(ROI_COLORS)]
        # Auto-assign label if blank
        if not roi.label:
            roi.label = f"ROI {len(self._rois) + 1}"
        self._rois.append(roi)
        if not self._active_uid:
            self._active_uid = roi.uid
            self.active_changed.emit(roi)
        self.roi_added.emit(roi)
        self.rois_changed.emit()
        log.debug("ROI added: %s", roi)
        return True

    def remove(self, uid: str) -> bool:
        """Remove an ROI by uid.  Returns False if not found."""
        idx = self.index_of(uid)
        if idx < 0:
            return False
        removed = self._rois.pop(idx)
        self.roi_removed.emit(uid)
        if self._active_uid == uid:
            self._active_uid = self._rois[0].uid if self._rois else ""
            self.active_changed.emit(self.active_roi)
        self.rois_changed.emit()
        log.debug("ROI removed: %s", removed)
        return True

    def update(self, uid: str, **fields) -> bool:
        """Update fields of an existing ROI in-place.  Returns False if not found.

        Example: ``roi_model.update(uid, x=120, w=500, label="Hotspot B")``
        """
        roi = self.by_uid(uid)
        if roi is None:
            return False
        for k, v in fields.items():
            if hasattr(roi, k) and k != "uid":
                setattr(roi, k, v)
        self.roi_updated.emit(roi)
        self.rois_changed.emit()
        return True

    def replace(self, uid: str, roi: Roi) -> bool:
        """Replace an ROI entirely (preserving list position)."""
        idx = self.index_of(uid)
        if idx < 0:
            return False
        roi.uid = uid  # keep original uid
        if not roi.color:
            roi.color = self._rois[idx].color
        if not roi.label:
            roi.label = self._rois[idx].label
        self._rois[idx] = roi
        self.roi_updated.emit(roi)
        self.rois_changed.emit()
        return True

    def set_active(self, uid: str) -> None:
        """Change which ROI is the 'active' (selected) one."""
        if uid == self._active_uid:
            return
        if uid and not any(r.uid == uid for r in self._rois):
            return
        self._active_uid = uid
        self.active_changed.emit(self.active_roi)

    def clear(self) -> None:
        """Remove all ROIs."""
        if not self._rois:
            return
        self._rois.clear()
        self._active_uid = ""
        self.active_changed.emit(None)
        self.rois_changed.emit()
        log.debug("All ROIs cleared")

    # ── bulk helpers ─────────────────────────────────────────────────

    def set_rois(self, rois: List[Roi]) -> None:
        """Replace the entire ROI list at once."""
        self._rois = list(rois)
        for i, r in enumerate(self._rois):
            if not r.color:
                r.color = ROI_COLORS[i % len(ROI_COLORS)]
            if not r.label:
                r.label = f"ROI {i + 1}"
        if self._rois and self._active_uid not in [r.uid for r in self._rois]:
            self._active_uid = self._rois[0].uid
        elif not self._rois:
            self._active_uid = ""
        self.active_changed.emit(self.active_roi)
        self.rois_changed.emit()

    def to_list(self) -> list:
        """Serialize all ROIs to a list of dicts."""
        return [r.to_dict() for r in self._rois]

    def from_list(self, data: list) -> None:
        """Deserialize and replace from a list of dicts."""
        self.set_rois([Roi.from_dict(d) for d in data])


# ── module-level singleton ───────────────────────────────────────────
roi_model = RoiModel()
