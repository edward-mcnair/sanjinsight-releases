"""
ai/ai_service.py

AIService — high-level AI assistant service for SanjINSIGHT.

Architecture mirrors HardwareService:
  • Singleton-like QObject owned by MainWindow
  • Signals: status_changed, response_token, response_complete, ai_error
  • enable() / disable() control model lifecycle

Status states
-------------
  "off"      — model not loaded (feature disabled)
  "loading"  — model loading from disk
  "ready"    — model loaded, waiting for query
  "thinking" — inference in progress
  "error"    — last load or infer failed
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from ai.model_runner import ModelRunner, llama_available
from ai.context_builder import ContextBuilder
from ai import prompt_templates as tmpl

log = logging.getLogger(__name__)


class AIService(QObject):
    """
    High-level AI assistant service.

    Signals
    -------
    status_changed(str)               one of the 5 status strings above
    response_token(str)               streaming token
    response_complete(str, float)     full text + elapsed seconds
    ai_error(str)                     human-readable error
    """

    status_changed    = pyqtSignal(str)
    response_token    = pyqtSignal(str)
    response_complete = pyqtSignal(str, float)
    ai_error          = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._runner = ModelRunner(parent=self)
        self._ctx    = ContextBuilder()
        self._status = "off"

        # Wire runner signals
        self._runner.load_complete.connect(self._on_load_complete)
        self._runner.load_failed.connect(self._on_load_failed)
        self._runner.token_ready.connect(self.response_token)
        self._runner.response_complete.connect(self._on_response_complete)
        self._runner.error.connect(self._on_error)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def status(self) -> str:
        return self._status

    @property
    def llama_available(self) -> bool:
        return llama_available()

    def set_metrics(self, metrics) -> None:
        """Inject MetricsService so the context builder can include quality data."""
        self._ctx.set_metrics(metrics)

    def set_active_tab(self, tab_name: str) -> None:
        """Track which tab is visible for context building."""
        self._ctx.set_active_tab(tab_name)

    def enable(self, model_path: str, n_gpu_layers: int = 0) -> None:
        """Load the model. Transitions to 'loading' then 'ready' or 'error'."""
        if self._status in ("loading", "thinking"):
            return
        self._set_status("loading")
        self._runner.load(model_path, n_gpu_layers=n_gpu_layers)

    def disable(self) -> None:
        """Unload the model and transition to 'off'."""
        self._runner.unload()
        self._set_status("off")

    def explain_tab(self) -> None:
        """Ask the AI to explain the current active tab."""
        self._run(tmpl.explain_tab(self._ctx._active_tab, self._ctx.build()))

    def diagnose(self) -> None:
        """Ask the AI to diagnose the current instrument state."""
        self._run(tmpl.diagnose(self._ctx.build()))

    def ask(self, question: str) -> None:
        """Send a free-form question with instrument context."""
        self._run(tmpl.free_ask(question, self._ctx.build()))

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _run(self, messages: list[dict]) -> None:
        if self._status != "ready":
            self.ai_error.emit(
                f"AI assistant is not ready (status: {self._status})")
            return
        self._set_status("thinking")
        self._runner.infer(messages)

    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.status_changed.emit(status)
            log.debug("AIService status → %s", status)

    # ------------------------------------------------------------------ #
    #  Runner signal handlers                                              #
    # ------------------------------------------------------------------ #

    def _on_load_complete(self) -> None:
        self._set_status("ready")

    def _on_load_failed(self, msg: str) -> None:
        self._set_status("error")
        self.ai_error.emit(f"AI model failed to load:\n{msg}")
        log.error("AI model load failed: %s", msg)

    def _on_response_complete(self, text: str, elapsed: float) -> None:
        self._set_status("ready")
        self.response_complete.emit(text, elapsed)

    def _on_error(self, msg: str) -> None:
        self._set_status("error")
        self.ai_error.emit(f"AI inference error:\n{msg}")
        log.error("AI inference error: %s", msg)
