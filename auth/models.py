"""
auth/models.py

Core data models for the SanjINSIGHT authentication and access-control system.

No PyQt5 imports — this module is pure Python and safe to import in tests,
CLI scripts, and background threads without a running QApplication.

Classes
-------
UserType        Enum: TECHNICIAN | FAILURE_ANALYST | RESEARCHER
                Maps 1:1 to AI personas in ai/personas.py.

User            Persistent user record stored in ~/.microsanj/users.db.
                user_type drives UI surface and default AI persona.
                is_admin is an orthogonal privilege overlay.

AuthSession     In-memory representation of an active login session.
                Created by Authenticator.authenticate(); destroyed on
                logout or application exit.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ── UserType ─────────────────────────────────────────────────────────────────

class UserType(enum.Enum):
    """
    The three natural user categories for SanjINSIGHT operators.

    Each value maps directly to an AI persona ID in ai/personas.py and
    determines which UI shell the user sees after login:

        TECHNICIAN       →  OperatorShell  +  lab_tech AI
        FAILURE_ANALYST  →  Full UI        +  failure_analyst AI
        RESEARCHER       →  Full UI        +  new_grad AI
    """

    TECHNICIAN      = "technician"
    FAILURE_ANALYST = "failure_analyst"
    RESEARCHER      = "researcher"

    # ── Display ───────────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        return {
            "technician":      "Technician",
            "failure_analyst": "Failure Analyst",
            "researcher":      "Researcher",
        }[self.value]

    @property
    def description(self) -> str:
        return {
            "technician":
                "Runs QA scans per SOP. Guided UI with PASS/FAIL verdict.",
            "failure_analyst":
                "Diagnoses device failures. Evidence-first AI guidance. Full UI.",
            "researcher":
                "Explores, learns, and publishes results. Explanatory AI. Full UI.",
        }[self.value]

    # ── UI routing ────────────────────────────────────────────────────────

    @property
    def uses_operator_shell(self) -> bool:
        """Technicians get OperatorShell; all other types get the full engineer UI."""
        return self is UserType.TECHNICIAN

    @property
    def can_edit_recipes(self) -> bool:
        """Technicians run approved locked recipes only; other types can create/edit."""
        return self is not UserType.TECHNICIAN

    # ── AI persona ────────────────────────────────────────────────────────

    @property
    def default_ai_persona(self) -> str:
        """
        AI persona ID from ai/personas.py that best matches this user type.
        Seeded into UserPrefs["ai.persona"] on first login; user can override.
        """
        return {
            "technician":      "lab_tech",
            "failure_analyst": "failure_analyst",   # persona ID matches directly
            "researcher":      "new_grad",
        }[self.value]


# ── User ─────────────────────────────────────────────────────────────────────

@dataclass
class User:
    """
    Persistent user record stored in ~/.microsanj/users.db.

    Fields
    ------
    user_type       Drives both the UI shell and the default AI persona.
    is_admin        Privilege overlay — any user type can be admin.
                    Grants: User Management tab, global settings, recipe approval.
    pw_hash         bcrypt hash at work factor 12. Never stored in plaintext.
    created_by      uid of the admin who created this account ("" = first bootstrap).
    """

    uid:          str
    username:     str           # Login name; stored with COLLATE NOCASE in DB
    display_name: str           # Full name shown in UI, e.g. "Jane Smith"
    user_type:    UserType
    is_admin:     bool          # Privilege overlay — orthogonal to user_type
    pw_hash:      str           # bcrypt hash
    created_at:   str           # ISO-8601 UTC string
    last_login:   str  = ""     # ISO-8601 UTC string, empty if never logged in
    is_active:    bool = True
    created_by:   str  = ""     # uid of creating admin; "" for the bootstrap admin

    # ── Derived access properties ─────────────────────────────────────────

    @property
    def can_manage_users(self) -> bool:
        return self.is_admin

    @property
    def can_access_full_ui(self) -> bool:
        """
        True for anyone who should see the full engineer interface.
        This includes Technicians who have been granted admin (unusual but valid).
        """
        return self.user_type.can_edit_recipes or self.is_admin

    @property
    def default_ai_persona(self) -> str:
        return self.user_type.default_ai_persona

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "uid":          self.uid,
            "username":     self.username,
            "display_name": self.display_name,
            "user_type":    self.user_type.value,
            "is_admin":     int(self.is_admin),
            "pw_hash":      self.pw_hash,
            "created_at":   self.created_at,
            "last_login":   self.last_login,
            "is_active":    int(self.is_active),
            "created_by":   self.created_by,
        }

    @staticmethod
    def from_row(row: tuple) -> "User":
        """
        Reconstruct from a SQLite row.
        Expected column order: uid, username, display_name, user_type,
        is_admin, pw_hash, created_at, last_login, is_active, created_by.
        """
        (uid, username, display_name, user_type_val,
         is_admin, pw_hash, created_at, last_login,
         is_active, created_by) = row
        return User(
            uid=uid,
            username=username,
            display_name=display_name,
            user_type=UserType(user_type_val),
            is_admin=bool(is_admin),
            pw_hash=pw_hash,
            created_at=created_at,
            last_login=last_login or "",
            is_active=bool(is_active),
            created_by=created_by or "",
        )


# ── AuthSession ───────────────────────────────────────────────────────────────

@dataclass
class AuthSession:
    """
    In-memory representation of an active login session.

    Created by Authenticator.authenticate(); destroyed on logout or application exit.
    The session is not persisted — the user must log in again after a restart.

    Inactivity management
    ---------------------
    Call touch() on any user interaction.
    Poll is_expired(timeout_s) from a QTimer every 30 seconds.

    Supervisor override
    -------------------
    When an engineer authenticates at an operator station:
      supervisor_override_active = True
      _override_user = the overriding engineer's User object

    Convenience properties (can_edit_recipes, is_admin) check the override
    first, so the rest of the app never needs to know about the override mechanism.
    """

    user:                       User
    login_time:                 float = field(default_factory=time.time)
    last_activity:              float = field(default_factory=time.time)
    session_id:                 str   = field(
                                    default_factory=lambda: str(uuid.uuid4())[:16])
    supervisor_override_active: bool  = False
    _override_user:             Optional[User] = field(
                                    default=None, compare=False, repr=False)

    # ── Inactivity ────────────────────────────────────────────────────────

    def touch(self) -> None:
        """Reset the inactivity clock. Call on any user mouse or key event."""
        self.last_activity = time.time()

    def is_expired(self, timeout_s: int) -> bool:
        """True if no activity has occurred for longer than timeout_s seconds."""
        return (time.time() - self.last_activity) > timeout_s

    # ── Convenience delegates ─────────────────────────────────────────────

    @property
    def can_edit_recipes(self) -> bool:
        if self.supervisor_override_active and self._override_user:
            return self._override_user.can_access_full_ui
        return self.user.can_access_full_ui

    @property
    def is_admin(self) -> bool:
        if self.supervisor_override_active and self._override_user:
            return self._override_user.is_admin
        return self.user.is_admin

    @property
    def effective_display_name(self) -> str:
        """Name shown in the UI header; notes the override engineer when active."""
        if self.supervisor_override_active and self._override_user:
            return f"{self._override_user.display_name}  (supervisor)"
        return self.user.display_name

    @property
    def effective_user_type(self) -> UserType:
        """Active user type — override user's type when override is active."""
        if self.supervisor_override_active and self._override_user:
            return self._override_user.user_type
        return self.user.user_type
