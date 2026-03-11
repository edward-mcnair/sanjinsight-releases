"""
ai/model_downloader.py

ModelDownloader — background download of GGUF model files.

Downloads to ~/.microsanj/models/ using urllib.request (stdlib only).
Emits Qt signals for progress, completion, and failure so the UI can
display a progress bar without any threading on the UI side.

Usage
-----
    dl = ModelDownloader(parent=self)
    dl.progress.connect(settings_tab.set_download_progress)
    dl.complete.connect(on_download_complete)
    dl.failed.connect(settings_tab.set_download_failed)
    dl.download(RECOMMENDED_MODEL["url"],
                str(DEFAULT_MODELS_DIR / RECOMMENDED_MODEL["filename"]))
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# ── Recommended model ──────────────────────────────────────────────────────────
RECOMMENDED_MODEL = {
    "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
    "url": (
        "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF"
        "/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
    ),
    "size_gb": 2.4,
}

DEFAULT_MODELS_DIR: Path = Path.home() / ".microsanj" / "models"

# Minimum file size (bytes) to be considered a valid model
_MIN_MODEL_BYTES = 100 * 1024 * 1024   # 100 MB
_CHUNK_SIZE      = 64 * 1024            # 64 KB per read


def find_existing_model(models_dir: Path = DEFAULT_MODELS_DIR) -> Optional[str]:
    """
    Return the path to the first .gguf file larger than 100 MB found in
    *models_dir*, or None if no such file exists.
    """
    if not models_dir.is_dir():
        return None
    for entry in sorted(models_dir.iterdir()):
        if entry.suffix.lower() == ".gguf" and entry.stat().st_size >= _MIN_MODEL_BYTES:
            return str(entry)
    return None


class ModelDownloader(QObject):
    """
    Downloads a GGUF model file in a daemon thread.

    Signals
    -------
    progress(int, int, float)   bytes_downloaded, total_bytes, speed_mbps
    complete(str)               path to the downloaded file
    failed(str)                 human-readable error / "Cancelled"
    """

    progress = pyqtSignal(int, int, float)  # done, total, MB/s
    complete = pyqtSignal(str)              # dest_path
    failed   = pyqtSignal(str)              # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_flag = threading.Event()
        self._busy = False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def download(self, url: str, dest_path: str,
                 expected_sha256: str = "") -> None:
        """
        Start downloading *url* to *dest_path* in a background daemon thread.
        The destination directory is created if it does not exist.
        A call while already busy is silently ignored.

        Parameters
        ----------
        url : str
            Remote GGUF file URL.
        dest_path : str
            Absolute local path for the downloaded file.
        expected_sha256 : str
            Lowercase hex SHA-256 digest to verify after download.
            Pass an empty string (default) to skip verification.
        """
        if self._busy:
            log.warning("ModelDownloader: already busy, ignoring download request")
            return
        self._cancel_flag.clear()
        threading.Thread(
            target=self._worker,
            args=(url, dest_path, expected_sha256),
            daemon=True,
            name="ai-download",
        ).start()

    def cancel(self) -> None:
        """Request cancellation of the in-progress download."""
        self._cancel_flag.set()
        log.info("ModelDownloader: cancel requested")

    # ------------------------------------------------------------------ #
    #  Worker thread                                                       #
    # ------------------------------------------------------------------ #

    def _worker(self, url: str, dest_path: str,
                expected_sha256: str = "") -> None:
        self._busy = True
        part_path = dest_path + ".part"
        try:
            # Ensure destination directory exists
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

            log.info("ModelDownloader: starting download %s → %s", url, dest_path)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SanjINSIGHT/1.0 (GGUF model downloader)"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                done  = 0
                t0    = time.monotonic()

                with open(part_path, "wb") as f:
                    while True:
                        if self._cancel_flag.is_set():
                            log.info("ModelDownloader: cancelled")
                            f.close()
                            self._cleanup_part(part_path)
                            self.failed.emit("Cancelled")
                            return

                        chunk = resp.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)

                        elapsed = time.monotonic() - t0
                        speed   = (done / 1024 / 1024) / elapsed if elapsed > 0 else 0.0
                        self.progress.emit(done, total, speed)

            # ── Integrity check ────────────────────────────────────────────
            if expected_sha256:
                self.progress.emit(done, total, 0.0)   # final progress update
                log.info("ModelDownloader: verifying SHA-256…")
                actual = self._sha256_file(part_path)
                if actual.lower() != expected_sha256.lower():
                    self._cleanup_part(part_path)
                    msg = (
                        f"SHA-256 mismatch — file may be corrupt or tampered.\n"
                        f"Expected: {expected_sha256}\n"
                        f"Actual:   {actual}"
                    )
                    log.error("ModelDownloader: %s", msg)
                    self.failed.emit(msg)
                    return
                log.info("ModelDownloader: SHA-256 verified OK")

            # Rename .part → final path
            os.replace(part_path, dest_path)
            log.info("ModelDownloader: complete → %s", dest_path)
            self.complete.emit(dest_path)

        except Exception as exc:
            log.exception("ModelDownloader: download failed")
            self._cleanup_part(part_path)
            self.failed.emit(str(exc))
        finally:
            self._busy = False

    @staticmethod
    def _cleanup_part(part_path: str) -> None:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass

    @staticmethod
    def _sha256_file(path: str) -> str:
        """Compute the lowercase hex SHA-256 digest of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()
