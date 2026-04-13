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

Segfault protection
-------------------
llama-cpp-python wraps native C++ code (llama.cpp) that can segfault
during model loading — particularly when Metal/GPU initialisation
fails on macOS.  A Python try/except cannot catch a segfault because
it is an OS-level signal (SIGSEGV) that terminates the process.

To guard against this, ``_load_worker`` runs a **subprocess preflight**
before loading in-process.  The preflight attempts to instantiate the
Llama model in an isolated child process with a timeout.  If the child
segfaults (exit code < 0) or times out, the load is aborted and
``load_failed`` is emitted with a diagnostic message — the main app
stays alive.

Cancellation
------------
Call cancel() to set a threading.Event that the inference worker checks
between tokens.  The worker stops emitting tokens and emits
response_complete() with whatever text was generated so far.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
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


# ---------------------------------------------------------------------- #
#  Subprocess preflight — catches segfaults during model load             #
# ---------------------------------------------------------------------- #

# Timeout for the preflight subprocess (seconds).  The child only needs
# to instantiate Llama() and exit — it doesn't run inference.  If Metal
# shader compilation is slow this may take a while, but 90 s is generous.
_PREFLIGHT_TIMEOUT = 90

# Inline script executed in the child process.  It imports llama_cpp,
# instantiates Llama with the given arguments, and exits 0 on success.
# Any Python exception exits 1; a segfault exits with a negative signal.
_PREFLIGHT_SCRIPT = """\
import sys, os
# Suppress llama.cpp verbose output in the child
os.environ.setdefault("LLAMA_LOG_LEVEL", "0")
try:
    from llama_cpp import Llama
    model = Llama(
        model_path=sys.argv[1],
        n_gpu_layers=int(sys.argv[2]),
        n_ctx=int(sys.argv[3]),
        verbose=False,
    )
    del model
    sys.exit(0)
except SystemExit:
    raise
except BaseException as exc:
    print(f"PREFLIGHT_ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
"""


def _run_preflight(model_path: str, n_gpu_layers: int,
                   n_ctx: int) -> tuple[bool, str]:
    """Run model load in a subprocess to detect segfaults.

    Returns
    -------
    (ok, message)
        ok is True if the child loaded the model without crashing.
        message describes the failure if ok is False.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PREFLIGHT_SCRIPT,
             model_path, str(n_gpu_layers), str(n_ctx)],
            capture_output=True, text=True,
            timeout=_PREFLIGHT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"Model preflight timed out after {_PREFLIGHT_TIMEOUT}s. "
            f"The model file may be too large or GPU initialisation is "
            f"hanging. Try setting GPU layers to 0 (CPU-only) in "
            f"Settings → AI."
        )
    except Exception as exc:
        return False, f"Preflight subprocess error: {exc}"

    if result.returncode == 0:
        return True, ""

    # Negative return code → killed by signal (e.g. -11 = SIGSEGV)
    if result.returncode < 0:
        sig_num = -result.returncode
        sig_name = _signal_name(sig_num)
        stderr_tail = (result.stderr or "").strip()[-500:]
        return False, (
            f"Model loading crashed ({sig_name}) in the native "
            f"llama.cpp library. This usually means the GPU/Metal "
            f"backend is incompatible with this model format.\n\n"
            f"Suggestions:\n"
            f"  • Set GPU layers to 0 (CPU-only) in Settings → AI\n"
            f"  • Try a smaller quantisation (Q4_K_S instead of Q4_K_M)\n"
            f"  • Update llama-cpp-python: pip install -U llama-cpp-python\n"
            + (f"\nNative error output:\n{stderr_tail}" if stderr_tail else "")
        )

    # Positive return code → Python exception in child
    stderr_tail = (result.stderr or "").strip()[-500:]
    return False, (
        f"Model preflight failed (exit code {result.returncode}).\n"
        + (stderr_tail if stderr_tail else "Unknown error")
    )


def _signal_name(sig_num: int) -> str:
    """Human-readable signal name, e.g. 'SIGSEGV (signal 11)'."""
    try:
        name = signal.Signals(sig_num).name
        return f"{name} (signal {sig_num})"
    except (ValueError, AttributeError):
        return f"signal {sig_num}"


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
        self._model        = None
        self._lock         = threading.Lock()
        self._busy         = False
        self._cancel_event = threading.Event()

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
        if not Path(model_path).is_file():
            self.load_failed.emit(f"Model file not found: {model_path}")
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
        self._cancel_event.clear()
        threading.Thread(
            target=self._infer_worker,
            args=(messages, max_tokens, temperature),
            daemon=True,
            name="ai-infer",
        ).start()

    def cancel(self) -> None:
        """
        Request cancellation of the current inference.

        The worker thread checks the cancel event between tokens and will
        stop after the next token completes.  response_complete() is still
        emitted with the partial text generated so far.
        """
        self._cancel_event.set()
        log.debug("ModelRunner: cancel requested")

    def unload(self) -> None:
        """Release the model from memory."""
        self.cancel()   # stop any in-progress inference first
        with self._lock:
            self._model = None
        log.info("AI model unloaded")

    # ------------------------------------------------------------------ #
    #  Worker threads                                                      #
    # ------------------------------------------------------------------ #

    def _load_worker(self, model_path: str, n_gpu_layers: int, n_ctx: int):
        # ── Step 1: subprocess preflight ──────────────────────────────
        # Catches segfaults in native llama.cpp / Metal code that would
        # otherwise kill the entire application.
        log.info("AI model preflight check: %s (n_gpu_layers=%d)",
                 model_path, n_gpu_layers)
        ok, msg = _run_preflight(model_path, n_gpu_layers, n_ctx)
        if not ok:
            log.error("AI model preflight FAILED: %s", msg)
            self.load_failed.emit(msg)
            return
        log.info("AI model preflight passed — loading in-process")

        # ── Step 2: load in-process ───────────────────────────────────
        # The preflight succeeded, so the same load should work here.
        # We still wrap in try/except for non-fatal errors (OOM, etc.).
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
            log.exception("AI model load failed (in-process)")
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
                if self._cancel_event.is_set():
                    log.debug("ModelRunner: inference cancelled after %d tokens",
                               len(full_text))
                    break
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
