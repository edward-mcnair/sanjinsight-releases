"""
acquisition/autosave.py

AutosaveManager — lightweight crash-recovery checkpointing.

Each time an acquisition or scan completes the app writes a small checkpoint
to  ~/.microsanj/autosave/.  On the next startup MainWindow detects the
checkpoint and shows a "Restore unsaved result?" dialog.

The checkpoint consists of:
  autosave_<kind>.npz   — compressed NumPy archive (arrays)
  autosave_<kind>.json  — metadata (timestamps, labels, scalar values)

Checkpoint lifecycle
--------------------
1. acquire/scan completes  → `save()`
2. user explicitly saves   → `clear()`  (clean exit also clears)
3. crash                   → checkpoint survives
4. next startup            → `has_checkpoint()` → True → ask user
5. user accepts restore    → `load()` returns dict → push to UI
6. user declines           → `clear()`
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import numpy as np

from events import (emit_info, emit_warning,
                    EVT_AUTOSAVE_SAVE, EVT_AUTOSAVE_LOAD, EVT_AUTOSAVE_CLEAR)

log = logging.getLogger(__name__)

_AUTOSAVE_DIR = os.path.join(os.path.expanduser("~"), ".microsanj", "autosave")


class AutosaveManager:
    """
    Saves and restores the last acquisition or scan result.

    Parameters
    ----------
    kind : "acquire" | "scan"
        Determines the checkpoint filename prefix so acquire and scan
        checkpoints are stored independently.
    """

    def __init__(self, kind: str = "acquire"):
        self._kind   = kind
        self._npz    = os.path.join(_AUTOSAVE_DIR, f"autosave_{kind}.npz")
        self._meta   = os.path.join(_AUTOSAVE_DIR, f"autosave_{kind}.json")

    # ── Public API ────────────────────────────────────────────────────────────

    def has_checkpoint(self) -> bool:
        """
        Return True if a complete checkpoint (both files) exists on disk.

        If only one file exists the pair is incomplete (crash mid-write);
        the orphan is removed and False is returned.
        """
        npz_ok  = os.path.isfile(self._npz)
        meta_ok = os.path.isfile(self._meta)
        if npz_ok and meta_ok:
            return True
        if npz_ok or meta_ok:
            # Partial write survived a crash — clean up the orphan.
            for path in (self._npz, self._meta):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                        log.warning("AutosaveManager[%s]: removed orphan %s "
                                    "(incomplete checkpoint from previous crash)",
                                    self._kind, os.path.basename(path))
                except Exception as exc:
                    log.warning("AutosaveManager[%s]: could not remove orphan — %s",
                                self._kind, exc)
        return False

    def save(self, arrays: dict, metadata: dict) -> None:
        """
        Persist a checkpoint atomically.

        Both files are written to ``.tmp`` siblings first, then renamed
        with :func:`os.replace` so a crash between the two writes never
        produces a partial checkpoint.

        Parameters
        ----------
        arrays   : dict of {name: np.ndarray}
        metadata : dict of JSON-serialisable scalars/strings
        """
        # Strip the trailing ".npz" so numpy re-adds it to the .tmp stem,
        # giving us "autosave_<kind>.tmp.npz" as the staging file.
        npz_tmp  = self._npz[:-4] + ".tmp"   # numpy will append .npz → .tmp.npz
        meta_tmp = self._meta + ".tmp"
        try:
            os.makedirs(_AUTOSAVE_DIR, exist_ok=True)

            # Write to temporaries
            np.savez_compressed(npz_tmp, **arrays)          # → <npz_tmp>.npz
            with open(meta_tmp, "w", encoding="utf-8") as f:
                json.dump({"_saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           **metadata}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename — on POSIX replaces the target in one syscall;
            # on Windows os.replace() is atomic at the file-system level.
            os.replace(npz_tmp + ".npz", self._npz)
            os.replace(meta_tmp, self._meta)

            log.debug("AutosaveManager[%s]: checkpoint saved", self._kind)
            emit_info("acquisition.autosave", EVT_AUTOSAVE_SAVE,
                      f"Autosave checkpoint saved [{self._kind}]", kind=self._kind)
        except Exception as exc:
            log.warning("AutosaveManager[%s]: save failed — %s", self._kind, exc)
            # Clean up any leftover temporaries
            for path in (npz_tmp + ".npz", meta_tmp):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except Exception:
                    pass

    def load(self) -> Optional[dict]:
        """
        Load a checkpoint.

        Returns
        -------
        dict with keys:
          "arrays"   : dict of {name: np.ndarray}
          "metadata" : dict of scalar/string metadata
          "saved_at" : ISO-8601 timestamp string
        or None if checkpoint cannot be loaded.
        """
        try:
            with np.load(self._npz, allow_pickle=False) as nf:
                arrays = {k: nf[k] for k in nf.files}
            with open(self._meta, "r", encoding="utf-8") as f:
                meta = json.load(f)
            saved_at = meta.pop("_saved_at", "?")
            return {"arrays": arrays, "metadata": meta, "saved_at": saved_at}
        except Exception as exc:
            log.warning("AutosaveManager[%s]: load failed — %s", self._kind, exc)
            return None

    def clear(self) -> None:
        """Delete the checkpoint files."""
        for path in (self._npz, self._meta):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception as exc:
                log.warning("AutosaveManager[%s]: clear failed — %s",
                            self._kind, exc)
        log.debug("AutosaveManager[%s]: checkpoint cleared", self._kind)
        emit_info("acquisition.autosave", EVT_AUTOSAVE_CLEAR,
                  f"Autosave checkpoint cleared [{self._kind}]", kind=self._kind)


# ── Module-level singletons ───────────────────────────────────────────────────
acquire_autosave = AutosaveManager("acquire")
scan_autosave    = AutosaveManager("scan")
