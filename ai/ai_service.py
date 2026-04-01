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
  A rolling window of exchange pairs (user + assistant) is prepended to
  every request so the model can answer follow-up questions.  The window
  depth is controlled by the active tier's token budget (see capability_tier.py).
  History is cleared when disable() is called or clear_history() is invoked.
  A threading.Lock guards the list so accidental concurrent access (e.g. a
  queued Qt signal arriving during a direct call) cannot corrupt it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from PyQt5.QtCore import QObject, pyqtSignal

import config as cfg_mod
from ai.model_runner import ModelRunner, llama_available
from ai.remote_runner import RemoteRunner
from ai.context_builder import ContextBuilder
from ai import prompt_templates as tmpl
from ai import manual_rag
from ai.personas import PERSONAS, DEFAULT_PERSONA_ID
from ai.model_catalog import MODEL_CATALOG
from ai.capability_tier import (
    AITier, tier_for_catalog_model, tier_for_ollama_model,
    budget_for, can,
)

log = logging.getLogger(__name__)


# ── Runner signal contract ───────────────────────────────────────────────────
#
# Both ModelRunner (GGUF/llama-cpp) and RemoteRunner (cloud providers) follow
# this contract by emitting identical Qt signals.  AIService connects to
# whichever runner is active and does not need to know the backend type.
#
# Any future runner (e.g. a PyTorch backend) must emit these same signals.

@runtime_checkable
class RunnerProtocol(Protocol):
    """Structural type for AI inference runners.

    Signals
    -------
    load_complete()                 Backend is loaded / connected and ready.
    load_failed(str)                Load or connection failed (human message).
    token_ready(str)                One streamed token during inference.
    response_complete(str, float)   Full response text + elapsed seconds.
    error(str)                      Inference-time error (human message).

    Methods
    -------
    infer(messages, max_tokens, temperature)
        Start streaming inference in a daemon thread.
    cancel()
        Request cancellation; worker emits response_complete with partial text.
    """

    # -- signals (pyqtSignal instances on the class) --
    load_complete:     pyqtSignal
    load_failed:       pyqtSignal
    token_ready:       pyqtSignal
    response_complete: pyqtSignal
    error:             pyqtSignal

    # -- required methods --
    def infer(self, messages: list[dict],
              max_tokens: int = ...,
              temperature: float = ...) -> None: ...
    def cancel(self) -> None: ...


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
    history_exported(str)             path of the exported conversation file
    """

    status_changed    = pyqtSignal(str)
    tier_changed      = pyqtSignal(int)   # emits AITier value
    response_token    = pyqtSignal(str)
    response_complete = pyqtSignal(str, float)
    ai_error          = pyqtSignal(str)
    history_cleared   = pyqtSignal()
    history_exported  = pyqtSignal(str)   # emitted with the export file path

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._runner         = ModelRunner(parent=self)
        self._remote_runner: Optional[RemoteRunner] = None
        self._active_backend = "local"   # "local" | "remote"
        self._ctx            = ContextBuilder()
        self._status         = "off"
        self._tier           = AITier.NONE
        self._history: list[dict] = []   # alternating user / assistant messages
        self._history_lock   = threading.Lock()
        self._n_ctx:  int = tmpl.DEFAULT_N_CTX  # updated in enable() from catalog

        # Wire local runner signals
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

    @property
    def tier(self) -> AITier:
        """Current AI capability tier (NONE when disabled)."""
        if self._status == "off":
            return AITier.NONE
        return self._tier

    def can(self, feature: str) -> bool:
        """Check whether the current tier supports *feature*."""
        return can(self._tier, feature)

    def set_metrics(self, metrics) -> None:
        """Inject MetricsService so the context builder can include quality data."""
        self._ctx.set_metrics(metrics)

    def set_diagnostics(self, engine) -> None:
        """Inject DiagnosticEngine so the context builder can include rule results."""
        self._ctx.set_diagnostics(engine)

    def set_active_tab(self, tab_name: str) -> None:
        """Track which tab is visible for context building."""
        self._ctx.set_active_tab(tab_name)

    def set_workspace_mode(self, mode: str) -> None:
        """Adapt AI behaviour to the workspace mode.

        The mode prefix is prepended to the persona's system prompt
        at inference time, so it layers on top of the existing persona.
        """
        self._workspace_mode = mode

    def enable(self, model_path: str, n_gpu_layers: int = 0) -> None:
        """Load the model. Transitions to 'loading' then 'ready' or 'error'."""
        if self._status in ("loading", "thinking"):
            return
        self._n_ctx = _n_ctx_for_model(model_path)
        self._set_tier(tier_for_catalog_model(model_path))
        self._set_status("loading")
        self._runner.load(model_path, n_gpu_layers=n_gpu_layers,
                          n_ctx=self._n_ctx)

    def enable_remote(self, provider: str, api_key: str, model_id: str) -> None:
        """
        Connect to a cloud AI provider.

        Validates credentials asynchronously, then transitions to 'ready'.
        Unloads any active local model first.
        """
        if self._status in ("loading", "thinking"):
            return
        # Unload local model if loaded
        self._runner.unload()
        # Disconnect previous remote runner if any
        if self._remote_runner is not None:
            self._remote_runner.disconnect()

        runner = RemoteRunner(parent=self)
        runner.load_complete.connect(self._on_load_complete)
        runner.load_failed.connect(self._on_load_failed)
        runner.token_ready.connect(self.response_token)
        runner.response_complete.connect(self._on_response_complete)
        runner.error.connect(self._on_error)
        self._remote_runner  = runner
        self._active_backend = "remote"

        # Cloud models have large context — always include full system prompt
        self._n_ctx = 100_000

        # Ollama models are classified by parameter count; cloud is always FULL
        if provider == "ollama":
            self._set_tier(tier_for_ollama_model(model_id))
        else:
            self._set_tier(AITier.FULL)

        self._set_status("loading")
        runner.connect(provider, api_key, model_id)

    def disable(self) -> None:
        """Unload the local model (or disconnect cloud) and transition to 'off'."""
        self._runner.unload()
        if self._remote_runner is not None:
            self._remote_runner.disconnect()
            self._remote_runner  = None
        self._active_backend = "local"
        with self._history_lock:
            self._history.clear()
        self._set_tier(AITier.NONE)
        self._set_status("off")

    def cancel(self) -> None:
        """
        Cancel the in-progress inference (if any).

        Safe to call when not generating — has no effect.
        For local inference the worker loop checks the cancel event and stops
        emitting tokens.  For remote inference the connection is closed.
        """
        if self._active_backend == "remote" and self._remote_runner is not None:
            self._remote_runner.cancel()
        else:
            self._runner.cancel()
        log.debug("AIService: cancel requested (backend=%s)", self._active_backend)

    def clear_history(self) -> None:
        """Reset the conversation history without unloading the model."""
        with self._history_lock:
            self._history.clear()
        self.history_cleared.emit()
        log.debug("AIService: conversation history cleared")

    def export_history(self, dest_path: str = "") -> None:
        """
        Export the current conversation history to a plain-text file.

        Parameters
        ----------
        dest_path : str
            Full path for the output file.  If empty, writes to
            ~/Documents/sanjinsight_conversation_<timestamp>.txt.

        Emits history_exported(path) on success, ai_error(msg) on failure.
        """
        if not dest_path:
            ts = time.strftime("%Y%m%d_%H%M%S")
            docs = Path.home() / "Documents"
            docs.mkdir(parents=True, exist_ok=True)
            dest_path = str(docs / f"sanjinsight_conversation_{ts}.txt")

        with self._history_lock:
            history_snapshot = list(self._history)

        if not history_snapshot:
            self.ai_error.emit("No conversation to export.")
            return

        try:
            lines = [
                "SanjINSIGHT AI Conversation Export",
                f"Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 60,
                "",
            ]
            for msg in history_snapshot:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if role == "user":
                    lines.append(f"▷ You")
                    lines.append(f"  {content}")
                else:
                    lines.append(f"◉ AI")
                    lines.append(f"  {content}")
                lines.append("")
                lines.append("─" * 60)
                lines.append("")

            Path(dest_path).write_text("\n".join(lines), encoding="utf-8")
            log.info("AIService: conversation exported to %s", dest_path)
            self.history_exported.emit(dest_path)
        except OSError as exc:
            msg = f"Failed to export conversation:\n{exc}"
            log.error("AIService: %s", msg)
            self.ai_error.emit(msg)

    def explain_tab(self) -> None:
        """Ask the AI to explain the current active tab."""
        tab        = self._ctx._active_tab
        sp         = self._active_system_prompt()
        manual_ctx = (manual_rag.retrieve(f"{tab} panel settings controls")
                      if self.can("manual_rag") else "")
        self._run(tmpl.explain_tab(tab, self._ctx.build(), sp, manual_ctx))

    def diagnose(self) -> None:
        """Ask the AI to diagnose the current instrument state."""
        tab        = self._ctx._active_tab
        sp         = self._active_system_prompt()
        manual_ctx = (manual_rag.retrieve(
            f"{tab} troubleshooting problems issues fixes")
            if self.can("manual_rag") else "")
        self._run(tmpl.diagnose(self._ctx.build(), sp, manual_ctx))

    def ask(self, question: str) -> None:
        """Send a free-form question with instrument context and manual RAG."""
        sp         = self._active_system_prompt()
        manual_ctx = (manual_rag.retrieve(question)
                      if self.can("manual_rag") else "")
        self._run(tmpl.free_ask(question, self._ctx.build(), sp, manual_ctx))

    def session_report(self, result_data: dict) -> None:
        """
        Generate a post-acquisition quality report.

        result_data is a dict of acquisition metrics plus pre-acquisition grade
        and issue snapshot — see prompt_templates.session_report() for keys.
        Silently skips if the model is not ready or tier is too low.
        """
        if self._status != "ready":
            log.debug(
                "AIService.session_report skipped — not ready (status=%s)",
                self._status)
            return
        if not self.can("session_report"):
            log.debug("AIService.session_report skipped — tier %s too low",
                      self._tier.name)
            return
        sp         = self._active_system_prompt()
        manual_ctx = manual_rag.retrieve(
            "acquisition quality SNR dark pixels exposure gain result analysis")
        self._run(tmpl.session_report(result_data, self._ctx.build(), sp, manual_ctx))

    # ------------------------------------------------------------------ #
    #  Persona helpers                                                     #
    # ------------------------------------------------------------------ #

    _MODE_PROMPT_PREFIX = {
        "guided":   ("Be explanatory and proactive. Suggest next steps. "
                     "Use simple language. Offer to help the user."),
        "standard": ("Be concise and action-oriented. Alert on anomalies. "
                     "Skip explanations unless asked."),
        "expert":   ("Be terse and technical. Assume deep domain knowledge. "
                     "Only speak when asked. Skip pleasantries."),
    }

    def _active_system_prompt(self) -> str:
        """
        Build the system prompt for the current persona and loaded model.

        The workspace mode prefix is prepended so the AI adapts its tone
        and proactivity to the user's experience level.

        The Quickstart Guide is included based on the tier's token budget
        (STANDARD and FULL include it; BASIC does not).  The n_ctx value
        is still passed to build_system_prompt for the underlying size check.
        """
        pid     = cfg_mod.get_pref("ai.persona", DEFAULT_PERSONA_ID)
        persona = PERSONAS.get(pid, PERSONAS[DEFAULT_PERSONA_ID])
        bud     = budget_for(self._tier)
        # If the tier budget says no guide, pass a small n_ctx to suppress it
        effective_n_ctx = self._n_ctx if bud["include_guide"] else 0
        base    = tmpl.build_system_prompt(persona.system_prompt, effective_n_ctx)

        mode = getattr(self, "_workspace_mode", "standard")
        prefix = self._MODE_PROMPT_PREFIX.get(mode, "")
        if prefix:
            return f"{prefix}\n\n{base}"
        return base

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _run(self, messages: list[dict]) -> None:
        """
        Send a request to the runner, injecting conversation history.

        messages must be [system_msg, user_msg].  History is spliced between
        them so the model sees: system → past turns → new user message.
        The number of history turns is controlled by the current tier's
        token budget.
        """
        if self._status != "ready":
            self.ai_error.emit(
                f"AI assistant is not ready (status: {self._status})")
            return

        # Use tier-based history depth
        bud = budget_for(self._tier)
        max_turns = bud["max_history_turns"]

        # Splice history between system prompt and new user message
        system_msg = messages[0]
        user_msg   = messages[-1]
        max_msgs   = max_turns * 2                        # pairs → messages
        with self._history_lock:
            trimmed = self._history[-max_msgs:] if self._history else []
        full_msgs  = [system_msg] + trimmed + [user_msg]

        # Record the user turn now (before inference, so cancel still records it)
        with self._history_lock:
            self._history.append(user_msg)
            # Keep only the messages that will ever be used in context; trimming here
            # prevents unbounded memory growth over long sessions.
            max_stored = max_turns * 2
            if len(self._history) > max_stored:
                del self._history[:-max_stored]

        self._set_status("thinking")
        max_tok = bud["max_tokens_reply"]
        if self._active_backend == "remote" and self._remote_runner is not None:
            self._remote_runner.infer(full_msgs, max_tokens=max_tok)
        else:
            self._runner.infer(full_msgs, max_tokens=max_tok)

    def _set_tier(self, tier: AITier) -> None:
        if tier != self._tier:
            self._tier = tier
            self.tier_changed.emit(int(tier))
            log.info("AIService tier → %s (%s)", tier.name, tier.value)

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
            max_turns = budget_for(self._tier)["max_history_turns"]
            with self._history_lock:
                self._history.append({"role": "assistant", "content": text})
                max_stored = max_turns * 2
                if len(self._history) > max_stored:
                    del self._history[:-max_stored]
        self._set_status("ready")
        self.response_complete.emit(text, elapsed)

    def _on_error(self, msg: str) -> None:
        self._set_status("error")
        self.ai_error.emit(f"AI inference error:\n{msg}")
        log.error("AI inference error: %s", msg)
