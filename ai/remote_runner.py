"""
ai/remote_runner.py

RemoteRunner — QObject wrapper for cloud AI providers (Anthropic Claude, OpenAI ChatGPT).

Same signal interface as ModelRunner so AIService can swap backends transparently.

Providers
---------
  "claude"   Anthropic Messages API   (https://api.anthropic.com)
  "openai"   OpenAI Chat Completions  (https://api.openai.com)

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

# ── Cloud model catalogue ─────────────────────────────────────────────────────

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
}

_ANTHROPIC_HOST = "api.anthropic.com"
_OPENAI_HOST    = "api.openai.com"
_ANTHROPIC_VER  = "2023-06-01"


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
        self._provider:  str = ""
        self._api_key:   str = ""
        self._model_id:  str = ""
        self._busy:      bool = False

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
        threading.Thread(
            target=self._infer_worker,
            args=(messages, max_tokens, temperature),
            daemon=True,
            name="ai-cloud-infer",
        ).start()

    def disconnect(self) -> None:
        """Clear credentials."""
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
            else:
                self.load_failed.emit(f"Unknown provider: {self._provider!r}")
                return
            log.info("Cloud AI connected: provider=%s model=%s",
                     self._provider, self._model_id)
            self.load_complete.emit()
        except _AuthError as exc:
            log.warning("Cloud AI auth failed: %s", exc)
            self.load_failed.emit(str(exc))
        except Exception as exc:
            log.exception("Cloud AI connection error")
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
            else:
                self.error.emit(f"Unknown provider: {self._provider!r}")
                return
            elapsed = time.monotonic() - t0
            self.response_complete.emit(text, elapsed)
        except Exception as exc:
            log.exception("Cloud AI inference error")
            self.error.emit(f"Cloud AI error: {exc}")
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
            raise RuntimeError(f"Anthropic API HTTP {status}")

        full_text: list[str] = []
        for line in resp_obj:
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
            raise RuntimeError(f"OpenAI API HTTP {status}")

        full_text: list[str] = []
        for line in resp_obj:
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
        return "".join(full_text)

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
            return resp.status, resp   # caller iterates response lines
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
