"""
auth/store.py

Persistent storage for the SanjINSIGHT authentication system.

Classes
-------
UserStore       SQLite-backed user CRUD (thread-safe).
AuditLogger     Append-only JSON Lines audit trail with automatic rotation.

Storage paths
-------------
User DB   : ~/.microsanj/users.db
Audit log : ~/.microsanj/audit.log

No PyQt5 imports — safe in tests and background threads.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

from auth.models import User, UserType

# ── Paths ─────────────────────────────────────────────────────────────────────

_MICROSANJ_DIR = Path.home() / ".microsanj"
_DB_PATH       = _MICROSANJ_DIR / "users.db"
_AUDIT_PATH    = _MICROSANJ_DIR / "audit.log"

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_VERSION = 1

_DDL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    uid          TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    user_type    TEXT NOT NULL,
    is_admin     INTEGER NOT NULL DEFAULT 0,
    pw_hash      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_login   TEXT NOT NULL DEFAULT '',
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_by   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username COLLATE NOCASE);
"""

log = logging.getLogger(__name__)


# ── UserStore ─────────────────────────────────────────────────────────────────

class UserStore:
    """
    SQLite-backed user CRUD for SanjINSIGHT.

    All public methods are thread-safe — each acquires a reentrant lock
    before touching the connection.  Connections are opened lazily and
    closed automatically.

    Schema versioning
    -----------------
    ``PRAGMA user_version`` is set to _SCHEMA_VERSION on creation.
    Future migrations increment the version and apply ALTER TABLE statements.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._lock    = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Open (or return cached) the SQLite connection."""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,   # autocommit; we manage transactions manually
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_db(self) -> None:
        """Create schema if it does not exist; run migrations if needed."""
        with self._lock:
            conn = self._connect()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.executescript(_DDL)
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                log.info("UserStore: created schema v%d at %s",
                         _SCHEMA_VERSION, self._db_path)
            elif version < _SCHEMA_VERSION:
                self._migrate(conn, version)

    def _migrate(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Apply incremental migrations from *from_version* to _SCHEMA_VERSION."""
        # Placeholder — no migrations exist beyond v1 yet.
        # Pattern for v2: if from_version < 2: conn.execute("ALTER TABLE ...")
        log.warning("UserStore: no migration path from v%d to v%d",
                    from_version, _SCHEMA_VERSION)

    def _row_to_user(self, row) -> User:
        return User(
            uid          = row["uid"],
            username     = row["username"],
            display_name = row["display_name"],
            user_type    = UserType(row["user_type"]),
            is_admin     = bool(row["is_admin"]),
            pw_hash      = row["pw_hash"],
            created_at   = row["created_at"],
            last_login   = row["last_login"] or "",
            is_active    = bool(row["is_active"]),
            created_by   = row["created_by"] or "",
        )

    # ── Queries ───────────────────────────────────────────────────────────

    def has_users(self) -> bool:
        """True if any user record exists (used to detect first launch)."""
        with self._lock:
            row = self._connect().execute(
                "SELECT 1 FROM users LIMIT 1"
            ).fetchone()
            return row is not None

    def get_by_username(self, username: str) -> Optional[User]:
        """Return the User with the given username (case-insensitive), or None."""
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            return self._row_to_user(row) if row else None

    def get_by_uid(self, uid: str) -> Optional[User]:
        """Return the User with the given uid, or None."""
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM users WHERE uid = ?", (uid,)
            ).fetchone()
            return self._row_to_user(row) if row else None

    def list_users(self, include_inactive: bool = False) -> List[User]:
        """Return all users, ordered by display_name.

        Args:
            include_inactive: when False (default) only active accounts are returned.
        """
        with self._lock:
            if include_inactive:
                rows = self._connect().execute(
                    "SELECT * FROM users ORDER BY display_name COLLATE NOCASE"
                ).fetchall()
            else:
                rows = self._connect().execute(
                    "SELECT * FROM users WHERE is_active = 1 "
                    "ORDER BY display_name COLLATE NOCASE"
                ).fetchall()
            return [self._row_to_user(r) for r in rows]

    # ── Mutations ─────────────────────────────────────────────────────────

    def create_user(
        self,
        username:     str,
        display_name: str,
        user_type:    UserType,
        pw_hash:      str,
        is_admin:     bool = False,
        created_by:   str  = "",
    ) -> User:
        """Insert a new user record and return the created User.

        Raises sqlite3.IntegrityError if the username already exists.
        """
        from datetime import datetime, timezone
        uid        = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._connect().execute(
                """INSERT INTO users
                   (uid, username, display_name, user_type, is_admin,
                    pw_hash, created_at, last_login, is_active, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '', 1, ?)""",
                (uid, username, display_name, user_type.value,
                 int(is_admin), pw_hash, created_at, created_by),
            )
            log.info("UserStore: created user '%s' (uid=%s, type=%s, admin=%s)",
                     username, uid, user_type.value, is_admin)
        return User(
            uid=uid, username=username, display_name=display_name,
            user_type=user_type, is_admin=is_admin, pw_hash=pw_hash,
            created_at=created_at, last_login="", is_active=True,
            created_by=created_by,
        )

    def update_user_type(self, uid: str, user_type: UserType) -> None:
        """Change the user type for an existing account."""
        with self._lock:
            self._connect().execute(
                "UPDATE users SET user_type = ? WHERE uid = ?",
                (user_type.value, uid),
            )

    def set_admin(self, uid: str, is_admin: bool) -> None:
        """Grant or revoke administrator privileges."""
        with self._lock:
            self._connect().execute(
                "UPDATE users SET is_admin = ? WHERE uid = ?",
                (int(is_admin), uid),
            )

    def set_active(self, uid: str, is_active: bool) -> None:
        """Activate or deactivate an account (soft delete)."""
        with self._lock:
            self._connect().execute(
                "UPDATE users SET is_active = ? WHERE uid = ?",
                (int(is_active), uid),
            )

    def update_password(self, uid: str, pw_hash: str) -> None:
        """Replace the stored password hash (bcrypt, work factor 12)."""
        with self._lock:
            self._connect().execute(
                "UPDATE users SET pw_hash = ? WHERE uid = ?",
                (pw_hash, uid),
            )

    def update_display_name(self, uid: str, display_name: str) -> None:
        """Update the user's display name."""
        with self._lock:
            self._connect().execute(
                "UPDATE users SET display_name = ? WHERE uid = ?",
                (display_name, uid),
            )

    def update_last_login(self, uid: str) -> None:
        """Stamp last_login with the current UTC time."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._connect().execute(
                "UPDATE users SET last_login = ? WHERE uid = ?",
                (ts, uid),
            )

    def close(self) -> None:
        """Close the SQLite connection (optional — called on app exit)."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ── AuditLogger ───────────────────────────────────────────────────────────────

class AuditLogger:
    """
    Append-only JSON Lines audit trail for authentication events.

    Each line is a self-contained JSON object:
    {
      "ts":      1741872000.0,          # Unix timestamp (float)
      "ts_str":  "2025-03-13T12:00:00Z",
      "event":   "login",               # see _EVENT_TYPES below
      "actor":   "jane.smith",          # username (empty for system events)
      "uid":     "abc123",              # user uid  (empty for system events)
      "role":    "technician",          # user_type.value or "unknown"
      "detail":  "success",
      "success": true
    }

    Rotation
    --------
    5 MB per file, 3 backups — matches the logging_config.py pattern.
    File: ~/.microsanj/audit.log
    """

    # Recognised event type strings (informational only — no enforcement)
    LOGIN           = "login"
    LOGIN_FAILED    = "login_failed"
    LOGOUT          = "logout"
    LOCKED          = "locked"
    UNLOCKED        = "unlocked"
    LOCKOUT_START   = "lockout_start"
    LOCKOUT_END     = "lockout_end"
    SV_OVERRIDE     = "supervisor_override"
    SV_OVERRIDE_END = "supervisor_override_end"
    USER_CREATED    = "user_created"
    USER_MODIFIED   = "user_modified"
    USER_DEACTIVATED= "user_deactivated"
    PW_RESET        = "password_reset"
    FIRST_ADMIN     = "first_admin_created"

    def __init__(self, log_path: Path = _AUDIT_PATH) -> None:
        self._path = log_path
        self._lock = threading.Lock()
        self._handler: Optional[logging.handlers.RotatingFileHandler] = None
        self._logger  = logging.getLogger("sanjinsight.audit")
        self._setup_handler()

    def _setup_handler(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                str(self._path),
                maxBytes    = 5 * 1024 * 1024,   # 5 MB per file
                backupCount = 3,
                encoding    = "utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False          # don't echo to root logger
            self._handler = handler
        except OSError as exc:
            log.warning("AuditLogger: could not create %s: %s", self._path, exc)

    def log(
        self,
        event:   str,
        actor:   str  = "",
        uid:     str  = "",
        role:    str  = "unknown",
        detail:  str  = "",
        success: bool = True,
    ) -> None:
        """Append one JSON event line to the audit log."""
        from datetime import datetime, timezone
        now = time.time()
        record = {
            "ts":      now,
            "ts_str":  datetime.fromtimestamp(now, tz=timezone.utc)
                               .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event":   event,
            "actor":   actor,
            "uid":     uid,
            "role":    role,
            "detail":  detail,
            "success": success,
        }
        with self._lock:
            self._logger.info(json.dumps(record, separators=(",", ":")))

    def close(self) -> None:
        """Flush and close the audit log handler."""
        if self._handler:
            self._handler.flush()
            self._handler.close()
            self._logger.removeHandler(self._handler)
            self._handler = None
