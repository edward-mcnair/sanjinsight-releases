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

Two layers of protection:

1. **CPU-only subprocess preflight** — Before loading in-process, a
   child process instantiates the model with ``n_gpu_layers=0`` (CPU
   only) to validate the GGUF file without touching Metal/GPU.  If the
   child crashes or times out, the load is aborted with a diagnostic
   message.  The preflight runs CPU-only to avoid GPU resource
   conflicts with Qt's Metal rendering in the parent process.

2. **Watchdog timer** — After preflight passes, the in-process load
   runs in a daemon thread with a watchdog.  If the thread dies without
   emitting ``load_complete`` or ``load_failed`` (i.e. a silent
   segfault killed the thread but not the process), the watchdog fires
   after a timeout and emits ``load_failed``.

Cancellation
------------
Call cancel() to set a threading.Event that the inference worker checks
between tokens.  The worker stops emitting tokens and emits
response_complete() with whatever text was generated so far.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

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

# Timeout for the preflight subprocess (seconds).  CPU-only loading is
# slower than GPU but avoids Metal resource conflicts with Qt.
_PREFLIGHT_TIMEOUT = 120

# Inline script executed in the child process.  It imports llama_cpp,
# instantiates Llama **CPU-only** to validate the file, and exits 0.
# Any Python exception exits 1; a segfault exits with a negative signal.
_PREFLIGHT_SCRIPT = """\
import sys, os
os.environ["LLAMA_LOG_LEVEL"] = "0"
try:
    from llama_cpp import Llama
    model = Llama(
        model_path=sys.argv[1],
        n_gpu_layers=0,
        n_ctx=int(sys.argv[2]),
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


def _run_preflight(model_path: str, n_ctx: int) -> tuple[bool, str]:
    """Run model load CPU-only in a subprocess to validate the GGUF file.

    The preflight always uses ``n_gpu_layers=0`` to avoid Metal/GPU
    resource conflicts with Qt's rendering in the parent process.

    Returns
    -------
    (ok, message)
        ok is True if the child loaded the model without crashing.
        message describes the failure if ok is False.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PREFLIGHT_SCRIPT,
             model_path, str(n_ctx)],
            capture_output=True, text=True,
            timeout=_PREFLIGHT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"Model preflight timed out after {_PREFLIGHT_TIMEOUT}s. "
            f"The model file may be corrupt or too large for available "
            f"memory. Try a smaller model."
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
            f"llama.cpp library. This model file may be corrupt or "
            f"incompatible with the installed llama-cpp-python.\n\n"
            f"Suggestions:\n"
            f"  • Re-download the model file (possible corruption)\n"
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


# ---------------------------------------------------------------------- #
#  Watchdog — detects silent thread death from in-process segfaults        #
# ---------------------------------------------------------------------- #

_WATCHDOG_INTERVAL_MS = 2000   # check every 2 seconds


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

        # Watchdog state — tracks whether the load thread is alive
        self._load_thread: Optional[threading.Thread] = None
        self._load_settled = threading.Event()  # set when load emits a signal
        self._watchdog_timer: Optional[QTimer] = None

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
        self._load_settled.clear()
        t = threading.Thread(
            target=self._load_worker,
            args=(model_path, n_gpu_layers, n_ctx),
            daemon=True,
            name="ai-model-load",
        )
        self._load_thread = t
        t.start()
        self._start_watchdog()

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
    #  Watchdog                                                            #
    # ------------------------------------------------------------------ #

    def _start_watchdog(self) -> None:
        """Start a QTimer that checks if the load thread is still alive."""
        self._stop_watchdog()
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._watchdog_check)
        self._watchdog_timer.start(_WATCHDOG_INTERVAL_MS)

    def _stop_watchdog(self) -> None:
        if self._watchdog_timer is not None:
            self._watchdog_timer.stop()
            self._watchdog_timer.deleteLater()
            self._watchdog_timer = None

    def _watchdog_check(self) -> None:
        """Called periodically to detect silent thread death."""
        # If the load already emitted a signal, nothing to do
        if self._load_settled.is_set():
            self._stop_watchdog()
            return

        t = self._load_thread
        if t is None:
            self._stop_watchdog()
            return

        # Thread still alive → keep watching
        if t.is_alive():
            return

        # Thread is dead but never emitted load_complete/load_failed.
        # This means it was killed by a signal (segfault) or an
        # unhandled error in native code that bypassed Python's
        # exception handling.
        self._stop_watchdog()
        self._load_thread = None
        log.error(
            "AI model load thread died without signalling completion. "
            "This usually means a segfault in native llama.cpp / Metal "
            "code.  The model will not be available."
        )
        self.load_failed.emit(
            "Model loading crashed silently (likely a segfault in the "
            "native GPU/Metal backend).\n\n"
            "Suggestions:\n"
            "  • Set GPU layers to 0 (CPU-only) in Settings → AI\n"
            "  • Try a smaller quantisation (Q4_K_S instead of Q4_K_M)\n"
            "  • Update llama-cpp-python: pip install -U llama-cpp-python"
        )

    # ------------------------------------------------------------------ #
    #  Worker threads                                                      #
    # ------------------------------------------------------------------ #

    def _load_worker(self, model_path: str, n_gpu_layers: int, n_ctx: int):
        # Enable faulthandler so segfaults dump a Python traceback to
        # stderr before the thread dies — helps with post-mortem debugging.
        try:
            faulthandler.enable()
        except Exception:
            pass

        # ── Step 1: CPU-only subprocess preflight ─────────────────────
        # Validates the GGUF file can be parsed by llama.cpp without
        # touching Metal/GPU.  This avoids GPU resource conflicts with
        # Qt's Metal rendering in the parent process.
        log.info("AI model preflight (CPU-only): %s", model_path)
        ok, msg = _run_preflight(model_path, n_ctx)
        if not ok:
            log.error("AI model preflight FAILED: %s", msg)
            self.load_failed.emit(msg)
            self._load_settled.set()
            return
        log.info("AI model preflight passed — loading in-process "
                 "(n_gpu_layers=%d)", n_gpu_layers)

        # ── Step 2: load in-process (with GPU if configured) ──────────
        # The preflight validated the file is parseable.  The in-process
        # load may still fail (OOM, Metal crash, etc.).  The watchdog
        # detects silent death from a segfault.
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
        finally:
            self._load_settled.set()

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
