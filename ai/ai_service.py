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

Conversation history
--------------------
  A rolling window of _MAX_HISTORY_TURNS exchange pairs (user + assistant)
  is prepended to every request so the model can answer follow-up questions.
  History is cleared when disable() is called or clear_history() is invoked.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

import config as cfg_mod
from ai.model_runner import ModelRunner, llama_available
from ai.context_builder import ContextBuilder
from ai import prompt_templates as tmpl
from ai import manual_rag
from ai.personas import PERSONAS, DEFAULT_PERSONA_ID
from ai.model_catalog import MODEL_CATALOG

log = logging.getLogger(__name__)


def _n_ctx_for_model(model_path: str) -> int:
    """
    Look up the recommended n_ctx for a model by matching its filename
    against MODEL_CATALOG entries.  Falls back to DEFAULT_N_CTX for
    custom / unknown model files.
    """
    from pathlib import Path
    filename = Path(model_path).name
    for entry in MODEL_CATALOG.values():
        if entry["filename"] == filename:
            return entry.get("n_ctx", tmpl.DEFAULT_N_CTX)
    return tmpl.DEFAULT_N_CTX


class AIService(QObject):
    """
    High-level AI assistant service.

    Signals
    -------
    status_changed(str)               one of the 5 status strings above
    response_token(str)               streaming token
    response_complete(str, float)     full text + elapsed seconds
    ai_error(str)                     human-readable error
    history_cleared()                 conversation history was reset
    """

    status_changed    = pyqtSignal(str)
    response_token    = pyqtSignal(str)
    response_complete = pyqtSignal(str, float)
    ai_error          = pyqtSignal(str)
    history_cleared   = pyqtSignal()

    # Rolling window: keep the last N user+assistant exchange pairs
    _MAX_HISTORY_TURNS = 6

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._runner  = ModelRunner(parent=self)
        self._ctx     = ContextBuilder()
        self._status  = "off"
        self._history: list[dict] = []   # alternating user / assistant messages
        self._n_ctx:  int = tmpl.DEFAULT_N_CTX  # updated in enable() from catalog

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

    def set_diagnostics(self, engine) -> None:
        """Inject DiagnosticEngine so the context builder can include rule results."""
        self._ctx.set_diagnostics(engine)

    def set_active_tab(self, tab_name: str) -> None:
        """Track which tab is visible for context building."""
        self._ctx.set_active_tab(tab_name)

    def enable(self, model_path: str, n_gpu_layers: int = 0) -> None:
        """Load the model. Transitions to 'loading' then 'ready' or 'error'."""
        if self._status in ("loading", "thinking"):
            return
        self._n_ctx = _n_ctx_for_model(model_path)
        self._set_status("loading")
        self._runner.load(model_path, n_gpu_layers=n_gpu_layers,
                          n_ctx=self._n_ctx)

    def disable(self) -> None:
        """Unload the model and transition to 'off'."""
        self._runner.unload()
        self._history.clear()
        self._set_status("off")

    def clear_history(self) -> None:
        """Reset the conversation history without unloading the model."""
        self._history.clear()
        self.history_cleared.emit()
        log.debug("AIService: conversation history cleared")

    def explain_tab(self) -> None:
        """Ask the AI to explain the current active tab."""
        tab        = self._ctx._active_tab
        sp         = self._active_system_prompt()
        manual_ctx = manual_rag.retrieve(f"{tab} panel settings controls")
        self._run(tmpl.explain_tab(tab, self._ctx.build(), sp, manual_ctx))

    def diagnose(self) -> None:
        """Ask the AI to diagnose the current instrument state."""
        tab        = self._ctx._active_tab
        sp         = self._active_system_prompt()
        manual_ctx = manual_rag.retrieve(
            f"{tab} troubleshooting problems issues fixes")
        self._run(tmpl.diagnose(self._ctx.build(), sp, manual_ctx))

    def ask(self, question: str) -> None:
        """Send a free-form question with instrument context and manual RAG."""
        sp         = self._active_system_prompt()
        manual_ctx = manual_rag.retrieve(question)
        self._run(tmpl.free_ask(question, self._ctx.build(), sp, manual_ctx))

    def session_report(self, result_data: dict) -> None:
        """
        Generate a post-acquisition quality report.

        result_data is a dict of acquisition metrics plus pre-acquisition grade
        and issue snapshot — see prompt_templates.session_report() for keys.
        Silently skips if the model is not ready.
        """
        if self._status != "ready":
            return
        sp         = self._active_system_prompt()
        manual_ctx = manual_rag.retrieve(
            "acquisition quality SNR dark pixels exposure gain result analysis")
        self._run(tmpl.session_report(result_data, self._ctx.build(), sp, manual_ctx))

    # ------------------------------------------------------------------ #
    #  Persona helpers                                                     #
    # ------------------------------------------------------------------ #

    def _active_system_prompt(self) -> str:
        """
        Build the system prompt for the current persona and loaded model.

        The Quickstart Guide is only embedded when the model's n_ctx is
        large enough (>= 8 192); smaller models receive domain knowledge
        and UI nav only, preserving headroom for context and responses.
        """
        pid     = cfg_mod.get_pref("ai.persona", DEFAULT_PERSONA_ID)
        persona = PERSONAS.get(pid, PERSONAS[DEFAULT_PERSONA_ID])
        return tmpl.build_system_prompt(persona.system_prompt, self._n_ctx)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _run(self, messages: list[dict]) -> None:
        """
        Send a request to the runner, injecting conversation history.

        messages must be [system_msg, user_msg].  History is spliced between
        them so the model sees: system → past turns → new user message.
        """
        if self._status != "ready":
            self.ai_error.emit(
                f"AI assistant is not ready (status: {self._status})")
            return

        # Splice history between system prompt and new user message
        system_msg = messages[0]
        user_msg   = messages[-1]
        max_msgs   = self._MAX_HISTORY_TURNS * 2          # pairs → messages
        trimmed    = self._history[-max_msgs:] if self._history else []
        full_msgs  = [system_msg] + trimmed + [user_msg]

        # Record the user turn now (before inference, so cancel still records it)
        self._history.append(user_msg)
        # Keep only the messages that will ever be used in context; trimming here
        # prevents unbounded memory growth over long sessions.
        max_stored = self._MAX_HISTORY_TURNS * 2
        if len(self._history) > max_stored:
            del self._history[:-max_stored]

        self._set_status("thinking")
        self._runner.infer(full_msgs)

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
        # Record the assistant turn so follow-up questions have context
        if text.strip():
            self._history.append({"role": "assistant", "content": text})
            max_stored = self._MAX_HISTORY_TURNS * 2
            if len(self._history) > max_stored:
                del self._history[:-max_stored]
        self._set_status("ready")
        self.response_complete.emit(text, elapsed)

    def _on_error(self, msg: str) -> None:
        self._set_status("error")
        self.ai_error.emit(f"AI inference error:\n{msg}")
        log.error("AI inference error: %s", msg)
