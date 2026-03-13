"""
auth/

Role-based access control for SanjINSIGHT.

Three user types (Technician, Failure Analyst, Researcher) drive both the
UI surface (OperatorShell vs full MainWindow) and the default AI persona.
Admin is a privilege overlay — any user type can be granted admin access.

Public exports
--------------
UserType        Enum: TECHNICIAN | FAILURE_ANALYST | RESEARCHER
User            Persistent user record (dataclass)
AuthSession     In-memory active login session (dataclass)
UserStore       SQLite-backed user CRUD
AuditLogger     Append-only JSON Lines audit trail
Authenticator   Central facade: authenticate, lock, logout, supervisor override
UserPrefs       Per-user preference layer (layered on global config.get_pref)
"""

from auth.models        import UserType, User, AuthSession
from auth.store         import UserStore, AuditLogger
from auth.authenticator import Authenticator
from auth.user_prefs    import UserPrefs

__all__ = [
    "UserType", "User", "AuthSession",
    "UserStore", "AuditLogger",
    "Authenticator",
    "UserPrefs",
]
