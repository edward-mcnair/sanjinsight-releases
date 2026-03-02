"""
ai/model_runner.py

ModelRunner — thin QObject wrapper around llama-cpp-python.

Ownership
---------
Lives on the main thread; spawns a daemon thread for blocking
load / inference calls so the UI never freezes.

Graceful degradation
--------------------
If llama-cpp-python is not installed the ModelRunner still loads and emits
load_failed() so the rest of the code can respond appropriately.
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

try:
    from llama_cpp import Llama
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False
    log.debug("llama-cpp-python not installed — AI inference unavailable")


def llama_available() -> bool:
    """Return True if llama-cpp-python is installed."""
    return _LLAMA_AVAILABLE


class ModelRunner(QObject):
    """
    Manages a single GGUF model: loading and streaming inference.

    Signals
    -------
    load_complete                      model is loaded and ready
    load_failed(str)                   model failed to load (message)
    token_ready(str)                   one streamed token from inference
    response_complete(str, float)      full text + elapsed seconds
    error(str)                         inference error
    """

    load_complete     = pyqtSignal()
    load_failed       = pyqtSignal(str)
    token_ready       = pyqtSignal(str)
    response_complete = pyqtSignal(str, float)
    error             = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._model = None
        self._lock  = threading.Lock()
        self._busy  = False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, model_path: str, n_gpu_layers: int = 0,
             n_ctx: int = 4096) -> None:
        """Start loading the model in a daemon thread. Emits load_complete or load_failed."""
        if not _LLAMA_AVAILABLE:
            self.load_failed.emit(
                "llama-cpp-python is not installed.\n"
                "Install it with:  pip install llama-cpp-python"
            )
            return
        threading.Thread(
            target=self._load_worker,
            args=(model_path, n_gpu_layers, n_ctx),
            daemon=True,
            name="ai-model-load",
        ).start()

    def infer(self, messages: list[dict],
              max_tokens: int = 512,
              temperature: float = 0.3) -> None:
        """
        Run streaming inference in a daemon thread.
        Emits token_ready() for each chunk, then response_complete().
        """
        if self._model is None:
            self.error.emit("Model not loaded")
            return
        if self._busy:
            self.error.emit("Already generating — please wait")
            return
        threading.Thread(
            target=self._infer_worker,
            args=(messages, max_tokens, temperature),
            daemon=True,
            name="ai-infer",
        ).start()

    def unload(self) -> None:
        """Release the model from memory."""
        with self._lock:
            self._model = None
        log.info("AI model unloaded")

    # ------------------------------------------------------------------ #
    #  Worker threads                                                      #
    # ------------------------------------------------------------------ #

    def _load_worker(self, model_path: str, n_gpu_layers: int, n_ctx: int):
        log.info("Loading AI model from %s (n_gpu_layers=%d)", model_path, n_gpu_layers)
        try:
            model = Llama(
                model_path=model_path,
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                verbose=False,
            )
            with self._lock:
                self._model = model
            log.info("AI model loaded successfully")
            self.load_complete.emit()
        except Exception as exc:
            log.exception("AI model load failed")
            self.load_failed.emit(str(exc))

    def _infer_worker(self, messages: list[dict],
                      max_tokens: int, temperature: float):
        self._busy = True
        t0 = time.monotonic()
        full_text: list[str] = []
        try:
            with self._lock:
                model = self._model
            if model is None:
                self.error.emit("Model was unloaded")
                return
            stream = model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    full_text.append(token)
                    self.token_ready.emit(token)
            elapsed = time.monotonic() - t0
            self.response_complete.emit("".join(full_text), elapsed)
        except Exception as exc:
            log.exception("AI inference error")
            self.error.emit(str(exc))
        finally:
            self._busy = False
