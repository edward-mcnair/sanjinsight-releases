"""
ai/remote_runner.py

RemoteRunner — QObject wrapper for remote AI providers.

Same signal interface as ModelRunner (see RunnerProtocol in ai_service.py)
so AIService can swap backends transparently.

Providers
---------
  "claude"   Anthropic Messages API   (https://api.anthropic.com)
  "openai"   OpenAI Chat Completions  (https://api.openai.com)
  "ollama"   Ollama local server      (http://localhost:11434)
             No API key required. Install from https://ollama.com, then
             run  ollama pull <model>  to download a model.

No external SDK required — raw HTTP via stdlib http.client.
Streaming implemented via Server-Sent Events (SSE).

API key is never logged.
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
from typing import Callable, Optional

from PyQt5.QtCore import QObject, pyqtSignal

# Re-export Ollama utilities so existing  from ai.remote_runner import …
# statements continue to work without changes.
from ai.ollama import (                                     # noqa: F401
    OLLAMA_HOST, OLLAMA_PORT,
    get_ollama_models, is_ollama_running,
    is_ollama_installed, ollama_exe_path, ollama_download_url,
)

log = logging.getLogger(__name__)

# ── Provider catalogue ────────────────────────────────────────────────────────

CLOUD_PROVIDERS: dict[str, dict] = {
    "claude": {
        "name": "Claude (Anthropic)",
        "api_key_url": "https://console.anthropic.com/account/keys",
        "models": [
            {"id": "claude-opus-4-6",          "name": "Claude Opus 4.6  — Most Capable"},
            {"id": "claude-sonnet-4-6",         "name": "Claude Sonnet 4.6  — Recommended"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5  — Fast & Economical"},
        ],
    },
    "openai": {
        "name": "ChatGPT (OpenAI)",
        "api_key_url": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4o",      "name": "GPT-4o  — Most Capable"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini  — Fast & Economical"},
        ],
    },
    # Ollama is handled separately from cloud — no API key, local HTTP.
    # Its model list is fetched live from the running Ollama server.
}

_ANTHROPIC_HOST = "api.anthropic.com"
_OPENAI_HOST    = "api.openai.com"
_ANTHROPIC_VER  = "2023-06-01"

_CONNECT_TIMEOUT = 30   # seconds — connection + validation timeout
_STREAM_TIMEOUT  = 120  # seconds — long timeout for streaming responses


def _ssl_ctx() -> ssl.SSLContext:
    try:
        ctx = ssl.create_default_context()
    except ssl.SSLError:
        # Fallback for Windows machines with restricted/corporate CA stores
        log.warning("ssl.create_default_context() failed; using permissive context")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except (ImportError, OSError):
            # Last resort: use system default store (may be empty on some Windows)
            ctx.load_default_certs()
    return ctx


# ── SSE token extraction helpers ─────────────────────────────────────────────
# Each provider returns SSE with different JSON shapes.  These callables
# extract the text token from one parsed SSE data object, returning "" if
# the object contains no content token.

def _extract_anthropic(obj: dict) -> str:
    """Anthropic: ``content_block_delta`` events carry text in ``delta.text``."""
    if obj.get("type") == "content_block_delta":
        return obj.get("delta", {}).get("text", "")
    return ""


def _extract_openai(obj: dict) -> str:
    """OpenAI / Ollama: ``choices[0].delta.content``."""
    return (obj.get("choices", [{}])[0]
               .get("delta", {})
               .get("content", ""))


# ── RemoteRunner ──────────────────────────────────────────────────────────────

class RemoteRunner(QObject):
    """
    Validates and uses a cloud AI provider API key.

    Signals (identical to ModelRunner — see RunnerProtocol)
    -------------------------------------------------------
    load_complete              connection verified, ready for inference
    load_failed(str)           bad key / network error
    token_ready(str)           one streaming token
    response_complete(str, float)  full text + elapsed seconds
    error(str)                 inference error
    """

    load_complete     = pyqtSignal()
    load_failed       = pyqtSignal(str)
    token_ready       = pyqtSignal(str)
    response_complete = pyqtSignal(str, float)
    error             = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._provider:    str = ""
        self._api_key:     str = ""
        self._model_id:    str = ""
        self._busy:        bool = False
        self._cancel_event = threading.Event()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        return bool(self._api_key)

    def connect(self, provider: str, api_key: str, model_id: str) -> None:
        """Validate credentials in a daemon thread; emits load_complete or load_failed."""
        self._provider = provider
        self._api_key  = api_key
        self._model_id = model_id
        threading.Thread(
            target=self._validate_worker,
            daemon=True,
            name="ai-cloud-connect",
        ).start()

    def infer(self, messages: list[dict],
              max_tokens: int = 1024,
              temperature: float = 0.3) -> None:
        """Stream a response in a daemon thread."""
        if not self._api_key:
            self.error.emit("Cloud AI not connected")
            return
        if self._busy:
            self.error.emit("Already generating — please wait")
            return
        self._cancel_event.clear()
        threading.Thread(
            target=self._infer_worker,
            args=(messages, max_tokens, temperature),
            daemon=True,
            name="ai-cloud-infer",
        ).start()

    def cancel(self) -> None:
        """
        Request cancellation of the current streaming inference.

        Sets a threading.Event checked between SSE lines by all streaming
        methods.  The worker emits response_complete() with partial text.
        """
        self._cancel_event.set()
        log.debug("RemoteRunner: cancel requested (provider=%s)", self._provider)

    def disconnect(self) -> None:
        """Clear credentials and cancel any in-progress inference."""
        self.cancel()
        self._provider = ""
        self._api_key  = ""
        self._model_id = ""

    # ------------------------------------------------------------------ #
    #  Validation                                                          #
    # ------------------------------------------------------------------ #

    def _validate_worker(self) -> None:
        try:
            if self._provider == "claude":
                self._validate_anthropic()
            elif self._provider == "openai":
                self._validate_openai()
            elif self._provider == "ollama":
                self._validate_ollama()
            else:
                self.load_failed.emit(f"Unknown provider: {self._provider!r}")
                return
            log.info("AI backend connected: provider=%s model=%s",
                     self._provider, self._model_id)
            self.load_complete.emit()
        except _AuthError as exc:
            log.warning("AI backend auth/connection failed: %s", exc)
            self.load_failed.emit(str(exc))
        except Exception as exc:
            log.exception("AI backend connection error")
            self.load_failed.emit(f"Connection error: {exc}")

    def _validate_anthropic(self) -> None:
        """Send a 1-token request to verify the key."""
        payload = {
            "model":      self._model_id,
            "max_tokens": 1,
            "messages":   [{"role": "user", "content": "hi"}],
        }
        status, _ = self._post_anthropic("/v1/messages", payload, stream=False)
        if status == 401:
            raise _AuthError("Invalid Anthropic API key")
        if status == 403:
            raise _AuthError("Anthropic API key lacks permission")
        if status not in (200, 201, 400):
            raise _AuthError(f"Anthropic API returned HTTP {status}")

    def _validate_openai(self) -> None:
        """Hit /v1/models to check the key."""
        status, _ = self._get_openai("/v1/models")
        if status == 401:
            raise _AuthError("Invalid OpenAI API key")
        if status == 403:
            raise _AuthError("OpenAI API key lacks permission")
        if status not in (200,):
            raise _AuthError(f"OpenAI API returned HTTP {status}")

    def _validate_ollama(self) -> None:
        """Check that the local Ollama server is running and has the selected model."""
        try:
            conn = http.client.HTTPConnection(
                OLLAMA_HOST, OLLAMA_PORT, timeout=5)
            conn.request("GET", "/api/tags")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
        except OSError as exc:
            raise _AuthError(
                f"Cannot reach Ollama at localhost:{OLLAMA_PORT}.\n"
                "Make sure Ollama is installed and running.\n"
                f"Details: {exc}") from exc

        if resp.status != 200:
            raise _AuthError(f"Ollama server returned HTTP {resp.status}")

        if self._model_id:
            try:
                data = json.loads(body)
                installed = [m.get("name", "")
                             for m in data.get("models", [])]
                if self._model_id not in installed:
                    raise _AuthError(
                        f"Ollama model '{self._model_id}' is not installed.\n"
                        f"Pull it first:  ollama pull {self._model_id}\n"
                        f"Installed models: {', '.join(installed) or '(none)'}"
                    )
            except _AuthError:
                raise
            except Exception:
                pass   # can't parse tag list — server is alive, continue

    # ------------------------------------------------------------------ #
    #  Inference                                                           #
    # ------------------------------------------------------------------ #

    def _infer_worker(self, messages: list[dict],
                      max_tokens: int, temperature: float) -> None:
        self._busy = True
        t0 = time.monotonic()
        try:
            if self._provider == "claude":
                text = self._stream_anthropic(messages, max_tokens, temperature)
            elif self._provider == "openai":
                text = self._stream_openai(messages, max_tokens, temperature)
            elif self._provider == "ollama":
                text = self._stream_ollama(messages, max_tokens, temperature)
            else:
                self.error.emit(f"Unknown provider: {self._provider!r}")
                return
            elapsed = time.monotonic() - t0
            self.response_complete.emit(text, elapsed)
        except Exception as exc:
            log.exception("AI inference error (provider=%s)", self._provider)
            self.error.emit(f"AI error: {exc}")
        finally:
            self._busy = False

    # ── Shared SSE reader ───────────────────────────────────────────────

    def _read_sse(self, resp, extract_token: Callable[[dict], str],
                  label: str) -> str:
        """
        Read an SSE stream, emitting tokens via ``token_ready``.

        Parameters
        ----------
        resp            Iterable HTTP response (line-by-line).
        extract_token   Callable that pulls the text token from one parsed
                        SSE JSON object.  Return ``""`` to skip the event.
        label           Provider name for debug logging on cancel.

        Returns the full concatenated response text.
        """
        full_text: list[str] = []
        for raw_line in resp:
            if self._cancel_event.is_set():
                log.debug("RemoteRunner: %s stream cancelled", label)
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            token = extract_token(obj)
            if token:
                full_text.append(token)
                self.token_ready.emit(token)
        return "".join(full_text)

    # ── Per-provider streaming ──────────────────────────────────────────

    def _stream_anthropic(self, messages: list[dict],
                          max_tokens: int, temperature: float) -> str:
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_messages.append(m)

        payload: dict = {
            "model":       self._model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    chat_messages,
            "stream":      True,
        }
        if system:
            payload["system"] = system

        status, resp = self._post_anthropic("/v1/messages", payload, stream=True)
        if status != 200:
            self._close_stream(resp)
            raise RuntimeError(f"Anthropic API HTTP {status}")
        try:
            return self._read_sse(resp, _extract_anthropic, "Anthropic")
        finally:
            self._close_stream(resp)

    def _stream_openai(self, messages: list[dict],
                       max_tokens: int, temperature: float) -> str:
        payload = {
            "model":       self._model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    messages,
            "stream":      True,
        }
        status, resp = self._post_openai(
            "/v1/chat/completions", payload, stream=True)
        if status != 200:
            self._close_stream(resp)
            raise RuntimeError(f"OpenAI API HTTP {status}")
        try:
            return self._read_sse(resp, _extract_openai, "OpenAI")
        finally:
            self._close_stream(resp)

    def _stream_ollama(self, messages: list[dict],
                       max_tokens: int, temperature: float) -> str:
        """Stream from a local Ollama server (OpenAI-compatible endpoint)."""
        payload = {
            "model":       self._model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    messages,
            "stream":      True,
        }
        body = json.dumps(payload).encode()
        headers = {"content-type": "application/json"}
        try:
            conn = http.client.HTTPConnection(
                OLLAMA_HOST, OLLAMA_PORT, timeout=_STREAM_TIMEOUT)
            conn.request("POST", "/v1/chat/completions",
                         body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at localhost:{OLLAMA_PORT}: {exc}"
            ) from exc

        if resp.status != 200:
            conn.close()
            raise RuntimeError(f"Ollama HTTP {resp.status}")
        try:
            return self._read_sse(resp, _extract_openai, "Ollama")
        finally:
            conn.close()

    # ── HTTP helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _close_stream(resp_obj) -> None:
        """Close the HTTP connection attached to a streaming response."""
        try:
            try:
                resp_obj.read()
            except Exception:
                pass
            conn = getattr(resp_obj, "_conn_ref", None)
            if conn is not None:
                conn.close()
        except Exception:
            pass

    def _post_anthropic(self, path: str, payload: dict,
                        stream: bool) -> tuple[int, object]:
        headers = {
            "x-api-key":         self._api_key,
            "anthropic-version": _ANTHROPIC_VER,
            "content-type":      "application/json",
        }
        body = json.dumps(payload).encode()
        timeout = _STREAM_TIMEOUT if stream else _CONNECT_TIMEOUT
        conn = http.client.HTTPSConnection(
            _ANTHROPIC_HOST, context=_ssl_ctx(), timeout=timeout)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        if stream:
            resp._conn_ref = conn
            return resp.status, resp
        data = resp.read()
        conn.close()
        return resp.status, data

    def _post_openai(self, path: str, payload: dict,
                     stream: bool) -> tuple[int, object]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "content-type":  "application/json",
        }
        body = json.dumps(payload).encode()
        timeout = _STREAM_TIMEOUT if stream else _CONNECT_TIMEOUT
        conn = http.client.HTTPSConnection(
            _OPENAI_HOST, context=_ssl_ctx(), timeout=timeout)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        if stream:
            resp._conn_ref = conn
            return resp.status, resp
        data = resp.read()
        conn.close()
        return resp.status, data

    def _get_openai(self, path: str) -> tuple[int, bytes]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        conn = http.client.HTTPSConnection(
            _OPENAI_HOST, context=_ssl_ctx(), timeout=_CONNECT_TIMEOUT)
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data


class _AuthError(Exception):
    """Raised when an API key is rejected."""
