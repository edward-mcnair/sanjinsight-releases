"""
ai/remote_runner.py

RemoteRunner — QObject wrapper for remote AI providers.

Same signal interface as ModelRunner so AIService can swap backends transparently.

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
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

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

# ── Ollama constants ──────────────────────────────────────────────────────────

_OLLAMA_HOST = "localhost"
_OLLAMA_PORT = 11434


def get_ollama_models(timeout: float = 3.0) -> list[dict]:
    """
    Query the running Ollama server for installed models.

    Returns a list of dicts with keys  "id"  and  "name", e.g.::

        [{"id": "llama3:8b", "name": "llama3:8b  (4.7 GB)"},
         {"id": "mistral",   "name": "mistral  (4.1 GB)"}]

    Returns an empty list if Ollama is not running or reachable.
    """
    try:
        conn = http.client.HTTPConnection(_OLLAMA_HOST, _OLLAMA_PORT, timeout=timeout)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        if resp.status != 200:
            return []
        data = json.loads(resp.read())
        conn.close()
        models = []
        for m in data.get("models", []):
            mid  = m.get("name", "")
            size = m.get("size", 0)
            size_str = f"  ({size / 1e9:.1f} GB)" if size else ""
            models.append({"id": mid, "name": f"{mid}{size_str}"})
        return models
    except Exception:
        return []


def is_ollama_running(timeout: float = 2.0) -> bool:
    """Return True if an Ollama server is reachable on localhost:11434."""
    try:
        conn = http.client.HTTPConnection(_OLLAMA_HOST, _OLLAMA_PORT, timeout=timeout)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        conn.close()
        return resp.status == 200
    except Exception:
        return False


def is_ollama_installed() -> bool:
    """
    Return True if the Ollama binary exists on this machine.

    Does NOT require the Ollama server to be running — just checks whether
    the executable is present.  Checks the system PATH first, then
    platform-specific default install locations.
    """
    import os
    import sys
    import shutil
    if shutil.which("ollama"):
        return True
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return os.path.isfile(
            os.path.join(local, "Programs", "Ollama", "ollama.exe"))
    if sys.platform == "darwin":
        return os.path.exists("/Applications/Ollama.app")
    return False


def ollama_exe_path() -> str:
    """
    Return the absolute path to the Ollama executable, or ``""`` if not found.

    Used by pull/run operations so they work even when Ollama's install
    directory is not on the system PATH (common on Windows right after install).
    """
    import os
    import sys
    import shutil
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidate = os.path.join(local, "Programs", "Ollama", "ollama.exe")
        if os.path.isfile(candidate):
            return candidate
    if sys.platform == "darwin":
        candidate = "/usr/local/bin/ollama"
        if os.path.isfile(candidate):
            return candidate
    return ""


def ollama_download_url() -> str:
    """Return the direct installer/download URL for Ollama on the current OS."""
    import sys
    if sys.platform == "win32":
        return "https://ollama.com/download/OllamaSetup.exe"
    if sys.platform == "darwin":
        return "https://ollama.com/download/Ollama-darwin.zip"
    return "https://ollama.com/install.sh"


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


# ── RemoteRunner ──────────────────────────────────────────────────────────────

class RemoteRunner(QObject):
    """
    Validates and uses a cloud AI provider API key.

    Signals (identical to ModelRunner)
    -----------------------------------
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

        Sets a threading.Event that all three streaming methods (_stream_anthropic,
        _stream_openai, _stream_ollama) check between SSE lines.  The worker
        stops reading and emits response_complete() with partial text.
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
    #  Internal validation                                                 #
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
            # 400 = validation error (e.g. model not found), still means key is valid
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
            conn = http.client.HTTPConnection(_OLLAMA_HOST, _OLLAMA_PORT, timeout=5)
            conn.request("GET", "/api/tags")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
        except OSError as exc:
            raise _AuthError(
                f"Cannot reach Ollama at localhost:{_OLLAMA_PORT}.\n"
                "Make sure Ollama is installed and running.\n"
                f"Details: {exc}") from exc

        if resp.status != 200:
            raise _AuthError(f"Ollama server returned HTTP {resp.status}")

        if self._model_id:
            try:
                data = json.loads(body)
                installed = [m.get("name", "") for m in data.get("models", [])]
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
    #  Internal inference                                                  #
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

    # ── Anthropic streaming ──────────────────────────────────────────────

    def _stream_anthropic(self, messages: list[dict],
                          max_tokens: int, temperature: float) -> str:
        # Extract system prompt (first message if role==system)
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_messages.append(m)

        payload: dict = {
            "model":      self._model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages":   chat_messages,
            "stream":     True,
        }
        if system:
            payload["system"] = system

        status, resp_obj = self._post_anthropic("/v1/messages", payload, stream=True)
        if status != 200:
            self._close_stream(resp_obj)
            raise RuntimeError(f"Anthropic API HTTP {status}")

        full_text: list[str] = []
        try:
            for line in resp_obj:
                if self._cancel_event.is_set():
                    log.debug("RemoteRunner: Anthropic stream cancelled")
                    break
                line = line.decode("utf-8", errors="replace").rstrip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "content_block_delta":
                    token = obj.get("delta", {}).get("text", "")
                    if token:
                        full_text.append(token)
                        self.token_ready.emit(token)
        finally:
            self._close_stream(resp_obj)
        return "".join(full_text)

    # ── OpenAI streaming ─────────────────────────────────────────────────

    def _stream_openai(self, messages: list[dict],
                       max_tokens: int, temperature: float) -> str:
        payload = {
            "model":       self._model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    messages,
            "stream":      True,
        }
        status, resp_obj = self._post_openai(
            "/v1/chat/completions", payload, stream=True)
        if status != 200:
            self._close_stream(resp_obj)
            raise RuntimeError(f"OpenAI API HTTP {status}")

        full_text: list[str] = []
        try:
            for line in resp_obj:
                if self._cancel_event.is_set():
                    log.debug("RemoteRunner: OpenAI stream cancelled")
                    break
                line = line.decode("utf-8", errors="replace").rstrip()
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                token = (obj.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", ""))
                if token:
                    full_text.append(token)
                    self.token_ready.emit(token)
        finally:
            self._close_stream(resp_obj)
        return "".join(full_text)

    # ── Ollama streaming (OpenAI-compatible, plain HTTP, localhost) ───────

    def _stream_ollama(self, messages: list[dict],
                       max_tokens: int, temperature: float) -> str:
        """
        Stream a response from a local Ollama server.

        Ollama exposes an OpenAI-compatible endpoint at
        http://localhost:11434/v1/chat/completions  — no API key required.
        """
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
                _OLLAMA_HOST, _OLLAMA_PORT, timeout=120)
            conn.request("POST", "/v1/chat/completions",
                         body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at localhost:{_OLLAMA_PORT}: {exc}") from exc

        if resp.status != 200:
            conn.close()
            raise RuntimeError(f"Ollama HTTP {resp.status}")

        full_text: list[str] = []
        try:
            for line in resp:
                if self._cancel_event.is_set():
                    log.debug("RemoteRunner: Ollama stream cancelled")
                    break
                line = line.decode("utf-8", errors="replace").rstrip()
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                token = (obj.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", ""))
                if token:
                    full_text.append(token)
                    self.token_ready.emit(token)
        finally:
            conn.close()
        return "".join(full_text)

    @staticmethod
    def _close_stream(resp_obj) -> None:
        """Close the HTTP connection attached to a streaming response."""
        try:
            conn = getattr(resp_obj, "_conn_ref", None)
            if conn is not None:
                conn.close()
        except Exception:
            pass

    # ── HTTP helpers ─────────────────────────────────────────────────────

    def _post_anthropic(self, path: str, payload: dict,
                        stream: bool) -> tuple[int, object]:
        headers = {
            "x-api-key":         self._api_key,
            "anthropic-version": _ANTHROPIC_VER,
            "content-type":      "application/json",
        }
        body = json.dumps(payload).encode()
        conn = http.client.HTTPSConnection(_ANTHROPIC_HOST, context=_ssl_ctx())
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        if stream:
            resp._conn_ref = conn  # attach so caller can close via _close_stream
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
        conn = http.client.HTTPSConnection(_OPENAI_HOST, context=_ssl_ctx())
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
        conn = http.client.HTTPSConnection(_OPENAI_HOST, context=_ssl_ctx())
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data


class _AuthError(Exception):
    """Raised when an API key is rejected."""
