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
  is trimmed by *estimated token count* (not turn count) via token_budget.py
  so that context usage scales to the model's actual capacity.
  History is cleared when disable() is called or clear_history() is invoked.
  A threading.Lock guards the list so accidental concurrent access (e.g. a
  queued Qt signal arriving during a direct call) cannot corrupt it.

Request lifecycle
-----------------
  Every AI request gets a unique ``request_id`` from ``RequestManager``.
  Tokens and completions from stale/cancelled requests are silently dropped
  before reaching the UI.  A new request of the same flow type (CHAT,
  REPORT, ADVISOR) auto-cancels the previous one.
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
from ai.token_budget import (
    TaskType, allocate_budget, trim_history, estimate_tokens,
    truncate_text,
)
from ai.request_lifecycle import RequestManager, FlowType
from ai.task_context import (
    DigestCache, build_task_context, compact_state_summary,
)
from ai.ai_metrics import AIMetricsCollector

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
    response_meta     = pyqtSignal(dict)  # grounding/source metadata per response
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

        # Request lifecycle manager — tracks request IDs for stale suppression
        self._requests = RequestManager()
        # Current request ID for the active inference (0 = no active request)
        self._active_rid: int = 0

        # Cached state digest — avoids redundant context rebuilds
        self._digest_cache = DigestCache()

        # Instrumentation counters — observable metrics for the AI subsystem
        self._ai_metrics = AIMetricsCollector()

        # Wire local runner signals
        self._runner.load_complete.connect(self._on_load_complete)
        self._runner.load_failed.connect(self._on_load_failed)
        self._runner.token_ready.connect(self._on_token)
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

    @property
    def ai_metrics(self) -> AIMetricsCollector:
        """Instrumentation counters for the AI subsystem."""
        return self._ai_metrics

    def set_metrics(self, metrics) -> None:
        """Inject MetricsService so the context builder can include quality data."""
        self._ctx.set_metrics(metrics)

    def set_diagnostics(self, engine) -> None:
        """Inject DiagnosticEngine so the context builder can include rule results."""
        self._ctx.set_diagnostics(engine)

    def set_active_tab(self, tab_name: str) -> None:
        """Track which tab is visible for context building."""
        self._ctx.set_active_tab(tab_name)
        self._digest_cache.invalidate()

    def set_workspace_mode(self, mode: str) -> None:
        """Adapt AI behaviour to the workspace mode.

        The mode prefix is prepended to the persona's system prompt
        at inference time, so it layers on top of the existing persona.
        """
        self._workspace_mode = mode

    def invalidate_context(self) -> None:
        """Signal that instrument state has changed materially.

        Call this on device connect/disconnect, TEC alarm, acquisition
        start/stop, etc. so the cached state digest is refreshed on
        the next AI request.
        """
        self._digest_cache.invalidate()

    # ── Public facade — replaces direct access to private internals ──

    def set_status(self, status: str) -> None:
        """Public status setter (delegates to internal _set_status)."""
        self._set_status(status)

    @property
    def active_backend(self) -> str:
        """Return 'local' or 'remote'."""
        return self._active_backend

    @property
    def remote_provider(self) -> str:
        """Return the remote runner's provider string, or '' if none."""
        rr = self._remote_runner
        return getattr(rr, "_provider", "") if rr else ""

    @property
    def diagnostics(self):
        """Return the diagnostic engine (or None) from the context builder."""
        return getattr(self._ctx, "_diagnostics", None)

    def system_prompt(self) -> str:
        """Return the active system prompt for the current persona/tier."""
        return self._active_system_prompt()

    def build_instrument_context(self) -> str:
        """Return the current instrument state as a JSON string."""
        return self._ctx.build()

    def infer_direct(self, messages: list, *,
                     max_tokens: int = 512,
                     temperature: float = 0.0) -> None:
        """Fire inference on the active runner, bypassing history.

        Routes to the remote runner when the active backend is remote,
        otherwise falls through to the local runner.
        """
        if (self._active_backend == "remote"
                and self._remote_runner is not None):
            self._remote_runner.infer(
                messages, max_tokens=max_tokens, temperature=temperature)
        else:
            self._runner.infer(
                messages, max_tokens=max_tokens, temperature=temperature)

    def is_runner_busy(self) -> bool:
        """True if the active inference runner is mid-request."""
        runner = (self._remote_runner
                  if (self._active_backend == "remote"
                      and self._remote_runner is not None)
                  else self._runner)
        return getattr(runner, "_busy", False)

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
        runner.token_ready.connect(self._on_token)
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
        self._requests.reset()
        self._ai_metrics.log_summary()
        self._ai_metrics.reset()
        self._active_rid = 0
        self._set_tier(AITier.NONE)
        self._set_status("off")

    def cancel(self) -> None:
        """
        Cancel the in-progress inference (if any).

        Safe to call when not generating — has no effect.
        For local inference the worker loop checks the cancel event and stops
        emitting tokens.  For remote inference the connection is closed.
        The request is immediately marked cancelled so any subsequent tokens
        or completion events are silently dropped.
        """
        # Mark the active request as cancelled FIRST so stale tokens are dropped
        self._requests.cancel(FlowType.CHAT)
        self._requests.cancel(FlowType.REPORT)
        self._requests.cancel(FlowType.ADVISOR)
        self._ai_metrics.on_request_cancelled()

        if self._active_backend == "remote" and self._remote_runner is not None:
            self._remote_runner.cancel()
        else:
            self._runner.cancel()
        log.debug("AIService: cancel requested (backend=%s, rid=%d)",
                  self._active_backend, self._active_rid)

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
        ctx_json   = self._build_context(TaskType.EXPLAIN_TAB)
        manual_ctx = self._rag_query(f"{tab} panel settings controls")
        self._run(
            tmpl.explain_tab(tab, ctx_json, sp, manual_ctx, tier=int(self._tier)),
            TaskType.EXPLAIN_TAB,
        )

    def diagnose(self) -> None:
        """Ask the AI to diagnose the current instrument state."""
        tab        = self._ctx._active_tab
        sp         = self._active_system_prompt()
        ctx_json   = self._build_context(TaskType.DIAGNOSE)
        manual_ctx = self._rag_query(
            f"{tab} troubleshooting problems issues fixes")
        self._run(
            tmpl.diagnose(ctx_json, sp, manual_ctx, tier=int(self._tier)),
            TaskType.DIAGNOSE,
        )

    def ask(self, question: str) -> None:
        """Send a free-form question with instrument context and manual RAG."""
        sp         = self._active_system_prompt()
        ctx_json   = self._build_context(TaskType.CHAT)
        manual_ctx = self._rag_query(question)
        self._run(
            tmpl.free_ask(question, ctx_json, sp, manual_ctx, tier=int(self._tier)),
            TaskType.CHAT,
        )

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
        ctx_json   = self._build_context(TaskType.SESSION_REPORT)
        manual_ctx = self._rag_query(
            "acquisition quality SNR dark pixels exposure gain result analysis")
        self._run(
            tmpl.session_report(result_data, ctx_json, sp, manual_ctx,
                                tier=int(self._tier)),
            TaskType.SESSION_REPORT,
            flow=FlowType.REPORT,
        )

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
    #  RAG retrieval (with metrics)                                        #
    # ------------------------------------------------------------------ #

    def _rag_query(self, query: str) -> str:
        """Retrieve manual RAG context and record metrics.

        Returns the retrieved snippet (or "") and sets ``_last_rag_used``
        so the UI can show a grounding badge.
        """
        if not self.can("manual_rag"):
            self._last_rag_used = False
            return ""
        snippet = manual_rag.retrieve(query)
        hit = bool(snippet)
        self._ai_metrics.on_rag_query(hit)
        self._last_rag_used = hit
        return snippet

    @property
    def last_rag_used(self) -> bool:
        """True if the most recent request included manual RAG context."""
        return getattr(self, "_last_rag_used", False)

    # ------------------------------------------------------------------ #
    #  Context building                                                    #
    # ------------------------------------------------------------------ #

    def _build_context(self, task_type: TaskType) -> str:
        """Build a task-specific instrument context string.

        Uses the cached state digest when available, then filters to
        include only the sections relevant to this task type.

        For BASIC tier, produces a compact natural-language summary
        instead of raw JSON, which small models handle better.
        """
        budget = allocate_budget(task_type, self._n_ctx, int(self._tier))

        # Get the full state (cached)
        digest = self._digest_cache.get(self._ctx)
        full_json = digest.json_str

        # BASIC tier: natural language summary instead of JSON
        if int(self._tier) <= 1:
            summary = compact_state_summary(full_json)
            return truncate_text(summary, budget.instrument_ctx)

        # STANDARD/FULL: task-specific JSON filtering
        return build_task_context(
            task_type, full_json,
            max_tokens=budget.instrument_ctx,
        )

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _run(self, messages: list[dict], task_type: TaskType,
             flow: FlowType = FlowType.CHAT) -> None:
        """
        Send a request to the runner, injecting conversation history.

        messages must be [system_msg, user_msg].  History is spliced between
        them so the model sees: system → past turns → new user message.

        History trimming is token-aware: the budget for history is computed
        from the task type and tier, then oldest messages are dropped until
        history fits its allocation.
        """
        if self._status != "ready":
            self.ai_error.emit(
                f"AI assistant is not ready (status: {self._status})")
            return

        # Register the request — auto-cancels any previous of the same flow
        rid = self._requests.new_request(flow, task_type.value)
        self._active_rid = rid
        self._ai_metrics.on_request_started()

        # Allocate token budget for this task
        budget = allocate_budget(task_type, self._n_ctx, int(self._tier))

        # Splice history between system prompt and new user message
        system_msg = messages[0]
        user_msg   = messages[-1]
        with self._history_lock:
            pre_trim_count = len(self._history)
            trimmed = trim_history(
                self._history,
                max_tokens=budget.history,
            )
        if len(trimmed) < pre_trim_count:
            self._ai_metrics.on_history_trimmed(pre_trim_count - len(trimmed))
        full_msgs  = [system_msg] + trimmed + [user_msg]

        # Record the user turn now (before inference, so cancel still records it)
        with self._history_lock:
            self._history.append(user_msg)
            # Token-aware trim of stored history: keep enough for future requests
            # but prevent unbounded memory growth.
            max_stored_tokens = budget.history * 2  # 2x budget = comfortable buffer
            while (len(self._history) > 2 and
                   estimate_tokens(
                       " ".join(m.get("content", "") for m in self._history)
                   ) > max_stored_tokens):
                self._history.pop(0)

        # Log budget usage
        actual_sys  = estimate_tokens(system_msg.get("content", ""))
        actual_user = estimate_tokens(user_msg.get("content", ""))
        actual_hist = estimate_tokens(
            " ".join(m.get("content", "") for m in trimmed))
        log.debug(
            "AIService._run[rid=%d %s]: budget sys=%d/%d user=%d/%d hist=%d/%d resp=%d",
            rid, task_type.value,
            actual_sys, budget.system_prompt,
            actual_user, budget.task_prompt + budget.instrument_ctx + budget.rag_snippets,
            actual_hist, budget.history,
            budget.response,
        )

        self._set_status("thinking")
        max_tok = budget.response
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

    def _on_token(self, token: str) -> None:
        """Handle a streamed token from the runner.

        Drops the token silently if the active request has been
        cancelled or superseded.
        """
        if not self._requests.is_current(self._active_rid):
            self._ai_metrics.on_stale_token()
            return  # stale token — drop silently
        self.response_token.emit(token)

    def _on_response_complete(self, text: str, elapsed: float) -> None:
        """Handle inference completion from the runner.

        Drops the completion silently if the request was cancelled or
        superseded.  Otherwise records the assistant turn in history
        and emits the public response_complete signal.
        """
        rid = self._active_rid
        is_current = self._requests.complete(rid)

        if not is_current:
            self._ai_metrics.on_stale_completion()
            log.debug(
                "AIService: response for rid=%d dropped (stale/cancelled, "
                "%.1fs elapsed, %d chars)",
                rid, elapsed, len(text),
            )
            # Still transition back to ready so the UI isn't stuck on "thinking"
            self._set_status("ready")
            return

        # Record the assistant turn so follow-up questions have context
        if text.strip():
            budget = allocate_budget(
                TaskType.CHAT, self._n_ctx, int(self._tier))
            with self._history_lock:
                self._history.append({"role": "assistant", "content": text})
                max_stored_tokens = budget.history * 2
                while (len(self._history) > 2 and
                       estimate_tokens(
                           " ".join(m.get("content", "") for m in self._history)
                       ) > max_stored_tokens):
                    self._history.pop(0)

        tok_count = len(text.split()) if text else 0
        self._ai_metrics.on_request_completed(elapsed, tok_count)

        self._set_status("ready")
        self.response_meta.emit({
            "rag_used":     getattr(self, "_last_rag_used", False),
            "tier":         int(self._tier),
            "elapsed_s":    round(elapsed, 2),
            "tokens":       tok_count,
        })
        self.response_complete.emit(text, elapsed)

    def _on_error(self, msg: str) -> None:
        """Handle an inference error from the runner.

        Still emits for stale requests because errors indicate problems
        that may need user attention (network, OOM, etc.).
        """
        rid = self._active_rid
        self._requests.complete(rid)  # mark finished regardless
        self._set_status("error")
        self.ai_error.emit(f"AI inference error:\n{msg}")
        log.error("AI inference error (rid=%d): %s", rid, msg)
