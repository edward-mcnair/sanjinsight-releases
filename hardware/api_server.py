"""
hardware/api_server.py

Minimal REST API for SanjINSIGHT lab automation.

Provides a subset of instrument control over HTTP so that external
automation scripts (prober handlers, wafer loaders, LIMS systems) can
trigger acquisitions and retrieve results without operating the GUI.

Design choices
--------------
* Uses Python's built-in ``http.server`` — no third-party web framework
  required.  The API surface is intentionally small.
* Runs in a dedicated daemon thread; the QApplication main thread is
  never touched from API handlers.
* Authentication: a single bearer token set in config.yaml
  (``api.token``).  If unset, the API is localhost-only and requires no
  token (suitable for single-user workstations).
* JSON in, JSON out.

Endpoints
---------
GET  /api/v1/status
    Returns instrument status: connected devices, demo_mode, pipeline state.

GET  /api/v1/session/{uid}
    Returns metadata for a session.  Arrays are NOT included.

GET  /api/v1/sessions?limit=20
    Returns list of the N most recent session metadata objects.

POST /api/v1/acquire
    Body: {"n_frames": 100, "inter_phase_delay": 0.0, "label": ""}
    Starts a non-blocking acquisition.  Returns {"accepted": true}.
    If an acquisition is already running, returns 409 Conflict.

GET  /api/v1/acquire/status
    Returns current pipeline state: {"state": "IDLE"|"CAPTURING"|...}

POST /api/v1/stop
    Aborts any running acquisition.

Usage
-----
    from hardware.api_server import ApiServer
    server = ApiServer(app_state, hw_service, session_manager)
    server.start(port=8765)     # starts daemon thread
    ...
    server.stop()
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlparse, parse_qs

import config

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8765


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _json_response(handler, code: int, payload: dict) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler) -> Optional[dict]:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except Exception:
        return None


# ── Request handler ───────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler.  _server_ref is set by ApiServer.start()."""

    _server_ref: "ApiServer" = None   # injected by ApiServer

    def log_message(self, fmt, *args):
        log.debug("api_server: " + fmt, *args)

    def _check_auth(self) -> bool:
        token = config.get_pref("api.token", "")
        if not token:
            return True   # no token configured — open access
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {token}"

    def _dispatch(self, method: str):
        if not self._check_auth():
            _json_response(self, 401, {"error": "Unauthorized"})
            return

        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        qs     = parse_qs(parsed.query)
        ref    = self._server_ref

        # ── Routes ────────────────────────────────────────────────────

        if method == "GET" and path == "/api/v1/status":
            _json_response(self, 200, ref._status())
            return

        if method == "GET" and path == "/api/v1/acquire/status":
            _json_response(self, 200, ref._acquire_status())
            return

        if method == "GET" and path.startswith("/api/v1/session/"):
            uid = path[len("/api/v1/session/"):]
            data = ref._get_session(uid)
            if data is None:
                _json_response(self, 404, {"error": "Session not found"})
            else:
                _json_response(self, 200, data)
            return

        if method == "GET" and path == "/api/v1/sessions":
            limit = int(qs.get("limit", ["20"])[0])
            _json_response(self, 200, {"sessions": ref._list_sessions(limit)})
            return

        if method == "POST" and path == "/api/v1/acquire":
            body = _read_body(self)
            if body is None:
                _json_response(self, 400, {"error": "Invalid JSON body"})
                return
            ok, msg = ref._start_acquire(body)
            code = 200 if ok else 409
            _json_response(self, code, {"accepted": ok, "message": msg})
            return

        if method == "POST" and path == "/api/v1/stop":
            ref._stop_acquire()
            _json_response(self, 200, {"stopped": True})
            return

        _json_response(self, 404, {"error": f"Unknown endpoint: {path}"})

    def do_GET(self):   self._dispatch("GET")
    def do_POST(self):  self._dispatch("POST")
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()


# ── ApiServer ─────────────────────────────────────────────────────────────────

class ApiServer:
    """
    Lifecycle manager for the SanjINSIGHT REST API.

    Parameters
    ----------
    app_state       : ApplicationState singleton
    hw_service      : HardwareService singleton
    session_manager : SessionManager singleton (optional)
    """

    def __init__(self, app_state, hw_service, session_manager=None) -> None:
        self._state   = app_state
        self._hw      = hw_service
        self._sm      = session_manager
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port    = _DEFAULT_PORT

    def start(self, port: int = _DEFAULT_PORT) -> None:
        """Start the API server in a daemon thread."""
        if self._httpd is not None:
            return   # already running

        self._port = port
        _Handler._server_ref = self   # inject reference before server starts

        try:
            self._httpd = HTTPServer(("127.0.0.1", port), _Handler)
        except OSError as exc:
            log.error("ApiServer: cannot bind to port %d: %s", port, exc)
            return

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="api-server",
            daemon=True,
        )
        self._thread.start()
        log.info("ApiServer: listening on http://127.0.0.1:%d/api/v1/", port)

    def stop(self) -> None:
        """Shut down the HTTP server gracefully."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        log.info("ApiServer: stopped")

    @property
    def port(self) -> int:
        return self._port

    @property
    def running(self) -> bool:
        return self._httpd is not None

    # ── Internal route implementations ───────────────────────────────

    def _status(self) -> dict:
        state = self._state
        pipeline = getattr(state, "pipeline", None)
        return {
            "version":     _version(),
            "demo_mode":   getattr(state, "demo_mode", False),
            "pipeline":    str(getattr(pipeline, "state", "N/A")).split(".")[-1],
            "devices": {
                "camera":  _driver_name(getattr(state, "cam",    None)),
                "fpga":    _driver_name(getattr(state, "fpga",   None)),
                "bias":    _driver_name(getattr(state, "bias",   None)),
                "stage":   _driver_name(getattr(state, "stage",  None)),
                "turret":  _driver_name(getattr(state, "turret", None)),
                "tecs":    [_driver_name(t)
                            for t in getattr(state, "tecs", [])],
            },
        }

    def _acquire_status(self) -> dict:
        pipeline = getattr(self._state, "pipeline", None)
        state_str = str(getattr(pipeline, "state", "N/A")).split(".")[-1]
        return {"state": state_str}

    def _get_session(self, uid: str) -> Optional[dict]:
        if self._sm is None:
            return None
        meta = self._sm.get_meta(uid)
        if meta is None:
            return None
        return {
            "uid":        meta.uid,
            "label":      getattr(meta, "label", ""),
            "timestamp":  getattr(meta, "timestamp", 0),
            "operator":   getattr(meta, "operator", ""),
            "status":     getattr(meta, "status", ""),
            "tags":       getattr(meta, "tags", []),
        }

    def _list_sessions(self, limit: int = 20) -> list:
        if self._sm is None:
            return []
        metas = self._sm.all_metas()[:limit]
        return [
            {
                "uid":       m.uid,
                "label":     getattr(m, "label", ""),
                "timestamp": getattr(m, "timestamp", 0),
                "status":    getattr(m, "status", ""),
            }
            for m in metas
        ]

    def _start_acquire(self, body: dict) -> tuple[bool, str]:
        pipeline = getattr(self._state, "pipeline", None)
        if pipeline is None:
            return False, "No acquisition pipeline available"
        try:
            from acquisition.pipeline import AcqState
            if pipeline.state == AcqState.CAPTURING:
                return False, "Acquisition already in progress"
        except ImportError:
            pass
        try:
            n_frames = int(body.get("n_frames", 100))
            delay    = float(body.get("inter_phase_delay", 0.0))
            pipeline.start(n_frames=n_frames, inter_phase_delay=delay)
            return True, "Acquisition started"
        except Exception as exc:
            return False, str(exc)

    def _stop_acquire(self) -> None:
        pipeline = getattr(self._state, "pipeline", None)
        if pipeline is not None:
            try:
                pipeline.abort()
            except Exception:
                pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _driver_name(driver) -> str:
    return type(driver).__name__ if driver is not None else "none"


def _version() -> str:
    try:
        from version import __version__
        return __version__
    except ImportError:
        return "unknown"
