"""
ai/ollama.py

Ollama local-server discovery and management utilities.

Ollama runs a local HTTP API on localhost:11434 that is OpenAI-compatible.
No API key is required.  These helpers detect whether Ollama is installed
and running, list available models, and locate the executable for pull/run
operations.

Separated from remote_runner.py because Ollama straddles the local/remote
boundary — it is a *local* runtime accessed via HTTP — and several UI
modules need these discovery functions without importing the full
RemoteRunner class.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import shutil
import sys

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

OLLAMA_HOST = "localhost"
OLLAMA_PORT = 11434


# ── Discovery ────────────────────────────────────────────────────────────────

def get_ollama_models(timeout: float = 3.0) -> list[dict]:
    """
    Query the running Ollama server for installed models.

    Returns a list of dicts with keys  "id"  and  "name", e.g.::

        [{"id": "llama3:8b", "name": "llama3:8b  (4.7 GB)"},
         {"id": "mistral",   "name": "mistral  (4.1 GB)"}]

    Returns an empty list if Ollama is not running or reachable.
    """
    conn = None
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT,
                                          timeout=timeout)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        if resp.status != 200:
            return []
        data = json.loads(resp.read())
        models = []
        for m in data.get("models", []):
            mid = m.get("name", "")
            size = m.get("size", 0)
            size_str = f"  ({size / 1e9:.1f} GB)" if size else ""
            models.append({"id": mid, "name": f"{mid}{size_str}"})
        return models
    except Exception:
        return []
    finally:
        if conn is not None:
            conn.close()


def is_ollama_running(timeout: float = 2.0) -> bool:
    """Return True if an Ollama server is reachable on localhost:11434."""
    conn = None
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT,
                                          timeout=timeout)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        return resp.status == 200
    except Exception:
        return False
    finally:
        if conn is not None:
            conn.close()


def is_ollama_installed() -> bool:
    """
    Return True if the Ollama binary exists on this machine.

    Does NOT require the Ollama server to be running — just checks whether
    the executable is present.  Checks the system PATH first, then
    platform-specific default install locations.
    """
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
    if sys.platform == "win32":
        return "https://ollama.com/download/OllamaSetup.exe"
    if sys.platform == "darwin":
        return "https://ollama.com/download/Ollama-darwin.zip"
    return "https://ollama.com/install.sh"
