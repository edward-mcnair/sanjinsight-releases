"""
acquisition/batch_reprocessor.py

Batch session reprocessing for SanjINSIGHT.

When a new or corrected calibration is available, BatchReprocessor
re-applies it to a list of existing sessions without re-capturing data.
Each session's ΔT array and PASS/FAIL verdict are updated in-place.

Usage
-----
    from acquisition.batch_reprocessor import BatchReprocessor
    from acquisition.calibration_library import CalibrationLibrary

    lib = CalibrationLibrary()
    cal = lib.load("GaN Basler 25°C")

    sm  = SessionManager(root)
    rp  = BatchReprocessor(sm)

    for update in rp.reprocess(session_uids, cal):
        print(update)          # BatchUpdate namedtuple

Qt usage (in a background thread — see BatchReprocessWorker below):
    worker = BatchReprocessWorker(sm, session_uids, cal, parent=None)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_done)
    worker.start()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional

log = logging.getLogger(__name__)


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class BatchUpdate:
    """Progress/result for one session in a batch reprocess run."""
    uid:        str
    label:      str
    success:    bool
    error:      str  = ""
    new_status: str  = ""   # "pass" | "fail" | "warn" | "" if unchanged
    duration_s: float = 0.0


@dataclass
class BatchResult:
    """Summary of a completed batch reprocess run."""
    total:    int
    ok:       int
    failed:   int
    duration_s: float


# ── BatchReprocessor ─────────────────────────────────────────────────────────

class BatchReprocessor:
    """
    Re-applies a CalibrationResult to a list of sessions.

    Each session's ΔR/R array (already stored on disk) is loaded, the
    new calibration is applied to produce a fresh ΔT array, the verdict
    rules are re-evaluated, and the session JSON is updated in-place.

    No camera or hardware access is required.
    """

    def __init__(self, session_manager) -> None:
        """
        session_manager : SessionManager — provides load() and the root path.
        """
        self._sm = session_manager

    def reprocess(
        self,
        uids: List[str],
        calibration,
        analysis_cfg: Optional[dict] = None,
    ) -> Iterator[BatchUpdate]:
        """
        Re-apply *calibration* to each session uid in *uids*.

        Yields a BatchUpdate for each session as it completes.
        Safe to call from a background thread.

        Parameters
        ----------
        uids          : list of session UIDs to reprocess
        calibration   : CalibrationResult with valid=True
        analysis_cfg  : optional dict of threshold overrides
                        (keys: threshold_k, fail_hotspot_count, etc.)
        """
        if not calibration or not calibration.valid:
            for uid in uids:
                yield BatchUpdate(uid=uid, label=uid, success=False,
                                  error="Calibration is not valid")
            return

        for uid in uids:
            t0 = time.time()
            meta = self._sm.get_meta(uid)
            label = meta.label if meta else uid
            try:
                update = self._process_one(uid, label, calibration,
                                           analysis_cfg or {})
                update.duration_s = time.time() - t0
                yield update
            except Exception as exc:
                log.exception("BatchReprocessor: uid=%s failed", uid)
                yield BatchUpdate(uid=uid, label=label, success=False,
                                  error=str(exc),
                                  duration_s=time.time() - t0)

    def _process_one(
        self,
        uid:          str,
        label:        str,
        calibration,
        analysis_cfg: dict,
    ) -> BatchUpdate:
        """Load, reprocess, and save one session."""
        import json
        import os
        import numpy as np

        session = self._sm.load(uid)
        if session is None:
            return BatchUpdate(uid=uid, label=label, success=False,
                               error="Session not found or failed to load")

        drr = session.delta_r_over_r
        if drr is None:
            return BatchUpdate(uid=uid, label=label, success=False,
                               error="Session has no ΔR/R data")

        # ── Apply calibration ─────────────────────────────────────────
        try:
            delta_t = calibration.apply(drr)
        except Exception as exc:
            return BatchUpdate(uid=uid, label=label, success=False,
                               error=f"Calibration.apply() failed: {exc}")

        # ── Re-evaluate verdict ───────────────────────────────────────
        new_status = _evaluate_verdict(delta_t, analysis_cfg)

        # ── Persist updated arrays + metadata ────────────────────────
        session_path = session.meta.path if session.meta else None
        if session_path and os.path.isdir(session_path):
            # Save updated delta_t
            np.save(os.path.join(session_path, "delta_t.npy"),
                    delta_t.astype(np.float32))

            # Update session.json with new verdict + reprocess timestamp
            json_path = os.path.join(session_path, "session.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                d["status"]               = new_status or d.get("status", "")
                d["reprocessed_at"]       = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                          time.gmtime())
                d["reprocessed_cal_name"] = getattr(calibration, "notes", "")
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=2)

            # Update in-memory meta
            if session.meta:
                session.meta.status = new_status or session.meta.status

        return BatchUpdate(uid=uid, label=label, success=True,
                           new_status=new_status)


def _evaluate_verdict(
    delta_t,
    cfg: dict,
) -> str:
    """
    Apply simple threshold rules to a ΔT map and return a verdict string.

    cfg keys (all optional, fall back to defaults):
      fail_peak_k        : float = 20.0  — peak ΔT that triggers FAIL
      warn_peak_k        : float = 10.0  — peak ΔT that triggers WARN
      fail_area_fraction : float = 0.05  — fraction of pixels above fail_peak_k
      warn_area_fraction : float = 0.01  — fraction of pixels above warn_peak_k

    Returns "fail", "warn", "pass", or "" if data is insufficient.
    """
    import numpy as np

    if delta_t is None:
        return ""

    valid = delta_t[~np.isnan(delta_t)] if np.any(np.isnan(delta_t)) else delta_t.ravel()
    if valid.size == 0:
        return ""

    fail_peak = float(cfg.get("fail_peak_k", 20.0))
    warn_peak = float(cfg.get("warn_peak_k", 10.0))
    fail_frac = float(cfg.get("fail_area_fraction", 0.05))
    warn_frac = float(cfg.get("warn_area_fraction", 0.01))

    peak   = float(np.nanmax(np.abs(delta_t)))
    area_f = float((np.abs(valid) > fail_peak).mean())
    area_w = float((np.abs(valid) > warn_peak).mean())

    if peak >= fail_peak or area_f >= fail_frac:
        return "fail"
    if peak >= warn_peak or area_w >= warn_frac:
        return "warn"
    return "pass"


# ── Qt worker (optional — only used when PyQt5 is available) ─────────────────

try:
    from PyQt5.QtCore import QThread, pyqtSignal

    class BatchReprocessWorker(QThread):
        """
        Run BatchReprocessor in a QThread so the GUI stays responsive.

        Signals
        -------
        progress(BatchUpdate)  — emitted for each completed session
        finished(BatchResult)  — emitted once the entire batch is done
        """

        progress = pyqtSignal(object)   # BatchUpdate
        finished = pyqtSignal(object)   # BatchResult

        def __init__(
            self,
            session_manager,
            uids:        List[str],
            calibration,
            analysis_cfg: Optional[dict] = None,
            parent=None,
        ) -> None:
            super().__init__(parent)
            self._sm          = session_manager
            self._uids        = uids
            self._cal         = calibration
            self._cfg         = analysis_cfg or {}
            self._abort_flag  = False

        def abort(self) -> None:
            self._abort_flag = True

        def run(self) -> None:
            t0 = time.time()
            reprocessor = BatchReprocessor(self._sm)
            ok = failed = 0
            for update in reprocessor.reprocess(self._uids, self._cal, self._cfg):
                if self._abort_flag:
                    break
                self.progress.emit(update)
                if update.success:
                    ok += 1
                else:
                    failed += 1
            result = BatchResult(
                total     = len(self._uids),
                ok        = ok,
                failed    = failed,
                duration_s= time.time() - t0,
            )
            self.finished.emit(result)

except ImportError:
    pass   # PyQt5 not available — BatchReprocessWorker not defined
