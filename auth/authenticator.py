"""
auth/authenticator.py

Central authentication facade for SanjINSIGHT.

The Authenticator is a QObject so it can emit Qt signals when session state
changes.  All bcrypt operations run in a worker QThread to avoid blocking the
UI event loop.

Public API
----------
authenticate(username, password, callback)
    Kick off async credential check.  *callback(session_or_none)* is called on
    the main thread when the check completes.

logout()            Destroy the current session; emit session_ended.
lock()              Preserve session but lock the screen; emit locked.
unlock(username, password, callback)
    Re-authenticate and unlock; callback receives bool success.

supervisor_override(username, password, callback)
    Grant temporary engineer access at an operator station.
    callback(bool) called with True on success.
end_supervisor_override()
    Revoke the override manually (also auto-reverts after timeout).

touch()             Reset inactivity clock (call from mouseMoveEvent).
check_lock_timeout(timeout_s) -> bool
    Returns True (and emits locked) if the session has been idle too long.
    Call from a 30-second QTimer.

current_session() -> Optional[AuthSession]
current_user()    -> Optional[User]

Signals
-------
session_started(AuthSession)
session_ended()
locked()
unlocked()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from PyQt5.QtCore import QObject, pyqtSignal, QThread, pyqtSlot

from auth.models import AuthSession, User, UserType
from auth.store  import AuditLogger, UserStore

log = logging.getLogger(__name__)

# Lockout constants — hard-coded (not user-configurable)
_MAX_FAILURES    = 5       # consecutive bad passwords before lockout
_LOCKOUT_SECS    = 5 * 60  # 5-minute lockout window
_OVERRIDE_SECS   = 15 * 60 # 15-minute supervisor override window


# ── bcrypt worker ─────────────────────────────────────────────────────────────

class _AuthWorker(QThread):
    """Runs bcrypt.checkpw in a background thread.

    Emits result(bool, user_or_none) when done.
    """

    result = pyqtSignal(bool, object)   # (success: bool, user: User | None)

    def __init__(
        self,
        username:  str,
        password:  str,
        store:     UserStore,
        parent:    QObject = None,
    ) -> None:
        super().__init__(parent)
        self._username = username
        self._password = password
        self._store    = store

    @pyqtSlot()
    def run(self) -> None:
        try:
            import bcrypt
        except ImportError:
            log.error("bcrypt not installed — run: pip install bcrypt>=4.0")
            self.result.emit(False, None)
            return

        user = self._store.get_by_username(self._username)
        if user is None or not user.is_active:
            # Perform a dummy check to avoid timing oracle
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            self.result.emit(False, None)
            return

        try:
            ok = bcrypt.checkpw(
                self._password.encode("utf-8"),
                user.pw_hash.encode("utf-8"),
            )
        except Exception as exc:
            log.error("bcrypt.checkpw failed: %s", exc)
            ok = False

        self.result.emit(ok, user if ok else None)


# ── Authenticator ─────────────────────────────────────────────────────────────

class Authenticator(QObject):
    """
    Central facade for all authentication operations.

    Maintains a single active AuthSession.  Thread-safe for the session state
    fields; bcrypt checks are always dispatched to _AuthWorker.

    LDAP stub
    ---------
    Override _verify_credentials(username, password, callback) to plug in
    LDAP/AD without changing any callers.
    """

    # Qt signals
    session_started = pyqtSignal(object)   # AuthSession
    session_ended   = pyqtSignal()
    locked          = pyqtSignal()
    unlocked        = pyqtSignal()

    def __init__(
        self,
        store:   UserStore,
        auditor: AuditLogger,
        parent:  QObject = None,
    ) -> None:
        super().__init__(parent)
        self._store   = store
        self._auditor = auditor
        self._session: Optional[AuthSession] = None
        self._locked  = False

        # Failure tracking: username → (count, first_failure_time)
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

        # Active worker thread reference (kept alive until done)
        self._worker: Optional[_AuthWorker] = None

        # Supervisor override auto-revert timer
        self._override_timer: Optional[object] = None  # QTimer set lazily

    # ── Lockout helpers ───────────────────────────────────────────────────

    def _is_locked_out(self, username: str) -> bool:
        with self._lock:
            entry = self._failures.get(username.lower())
            if entry is None:
                return False
            count, first_time = entry
            if count < _MAX_FAILURES:
                return False
            if (time.time() - first_time) >= _LOCKOUT_SECS:
                # Lockout expired
                del self._failures[username.lower()]
                self._auditor.log(AuditLogger.LOCKOUT_END, actor=username)
                return False
            return True

    def _record_failure(self, username: str) -> None:
        with self._lock:
            key  = username.lower()
            now  = time.time()
            prev = self._failures.get(key, (0, now))
            count = prev[0] + 1
            self._failures[key] = (count, prev[1])
            if count == _MAX_FAILURES:
                self._auditor.log(AuditLogger.LOCKOUT_START, actor=username,
                                  detail=f"locked for {_LOCKOUT_SECS}s")
                log.warning("Account '%s' locked out after %d failures",
                            username, count)

    def _clear_failures(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username.lower(), None)

    def lockout_remaining(self, username: str) -> int:
        """Seconds remaining in lockout, or 0 if not locked out."""
        with self._lock:
            entry = self._failures.get(username.lower())
            if entry is None:
                return 0
            count, first_time = entry
            if count < _MAX_FAILURES:
                return 0
            remaining = int(_LOCKOUT_SECS - (time.time() - first_time))
            return max(0, remaining)

    # ── Core credential verification (override for LDAP) ──────────────────

    def _verify_credentials(
        self,
        username: str,
        password: str,
        callback: Callable[[bool, Optional[User]], None],
    ) -> None:
        """
        Default implementation: bcrypt check against UserStore in a QThread.

        To add LDAP/AD: subclass Authenticator and override this method.
        The callback signature is (success: bool, user: User | None).
        callback is always called on the main thread.
        """
        worker = _AuthWorker(username, password, self._store, parent=self)
        worker.result.connect(lambda ok, u: callback(ok, u))
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    # ── Public: authenticate ──────────────────────────────────────────────

    def authenticate(
        self,
        username: str,
        password: str,
        callback: Callable[[Optional[AuthSession]], None],
    ) -> None:
        """
        Start an asynchronous credential check.

        *callback(session_or_none)* is invoked on the main thread.
        On success: session is stored, session_started emitted.
        On failure: lockout counter incremented; callback(None).
        """
        if self._is_locked_out(username):
            remaining = self.lockout_remaining(username)
            log.info("Login blocked — '%s' is locked out (%ds remaining)",
                     username, remaining)
            callback(None)
            return

        def _on_result(ok: bool, user: Optional[User]) -> None:
            if ok and user is not None:
                self._clear_failures(username)
                session = self._create_session(user)
                self._store.update_last_login(user.uid)
                self._locked = False
                self._auditor.log(
                    AuditLogger.LOGIN, actor=user.username,
                    uid=user.uid, role=user.user_type.value, success=True,
                )
                self.session_started.emit(session)
                log.info("Login success: %s (%s)", user.username, user.user_type.value)
                callback(session)
            else:
                self._record_failure(username)
                self._auditor.log(
                    AuditLogger.LOGIN_FAILED, actor=username, success=False,
                    detail=f"attempt {self._failures.get(username.lower(), (0,))[0]}",
                )
                log.info("Login failed for '%s'", username)
                callback(None)

        self._verify_credentials(username, password, _on_result)

    def _create_session(self, user: User) -> AuthSession:
        from auth.models import AuthSession as _AS
        session = _AS(user=user)
        self._session = session
        return session

    def authenticate_user(self, user: User) -> AuthSession:
        """Create a session directly from a User object (no password check).

        Used after AdminSetupWizard to auto-login the newly-created admin
        without requiring them to re-enter their credentials.
        """
        session = self._create_session(user)
        self._store.update_last_login(user.uid)
        self._auditor.log(
            "login",
            actor   = user.username,
            uid     = user.uid,
            role    = user.user_type.value,
            detail  = "auto-login after account creation",
            success = True,
        )
        self.session_started.emit(session)
        log.info("authenticate_user: auto-session for %s", user.username)
        return session

    # ── Public: lock / unlock / logout ────────────────────────────────────

    def lock(self) -> None:
        """Lock the screen — session is preserved; user must re-authenticate."""
        if self._session and not self._locked:
            self._locked = True
            self._auditor.log(
                AuditLogger.LOCKED,
                actor=self._session.user.username,
                uid=self._session.user.uid,
                role=self._session.user.user_type.value,
            )
            self.locked.emit()
            log.info("Session locked for %s", self._session.user.username)

    def unlock(
        self,
        username: str,
        password: str,
        callback: Callable[[bool], None],
    ) -> None:
        """Re-authenticate to unlock.  callback(True) on success."""
        if self._session is None:
            callback(False)
            return
        # Must be the same user who locked the session
        if self._session.user.username.lower() != username.lower():
            callback(False)
            return

        def _on_result(ok: bool, _user: Optional[User]) -> None:
            if ok:
                self._locked = False
                self._session.touch()
                self._auditor.log(
                    AuditLogger.UNLOCKED,
                    actor=self._session.user.username,
                    uid=self._session.user.uid,
                    role=self._session.user.user_type.value,
                )
                self.unlocked.emit()
            callback(ok)

        self._verify_credentials(username, password, _on_result)

    def logout(self) -> None:
        """Destroy the current session entirely."""
        if self._session:
            self._auditor.log(
                AuditLogger.LOGOUT,
                actor=self._session.user.username,
                uid=self._session.user.uid,
                role=self._session.user.user_type.value,
            )
            log.info("Logout: %s", self._session.user.username)
        self._session = None
        self._locked  = False
        self._end_supervisor_override_internal()
        self.session_ended.emit()

    # ── Public: supervisor override ───────────────────────────────────────

    def supervisor_override(
        self,
        username: str,
        password: str,
        callback: Callable[[bool], None],
        minimum_user_type: UserType = UserType.FAILURE_ANALYST,
    ) -> None:
        """
        Temporarily grant engineer access at an operator station.

        The overriding user must have `can_access_full_ui == True` (any
        non-Technician, or any admin).  On success:
          - session.supervisor_override_active = True
          - session._override_user set to the engineer's User
          - Auto-reverts after _OVERRIDE_SECS seconds
          - callback(True) on success, callback(False) on failure
        """
        def _on_result(ok: bool, user: Optional[User]) -> None:
            if not ok or user is None:
                callback(False)
                return
            if not user.can_access_full_ui:
                log.info("Supervisor override denied: %s lacks permission",
                         user.username)
                callback(False)
                return
            if self._session is None:
                callback(False)
                return

            self._session.supervisor_override_active = True
            self._session._override_user = user
            self._auditor.log(
                AuditLogger.SV_OVERRIDE,
                actor=user.username, uid=user.uid,
                role=user.user_type.value,
                detail=f"at_station={self._session.user.username}",
            )
            log.info("Supervisor override granted: %s at %s station",
                     user.username, self._session.user.username)
            self._start_override_timer()
            callback(True)

        self._verify_credentials(username, password, _on_result)

    def end_supervisor_override(self) -> None:
        """Manually revoke the supervisor override."""
        self._end_supervisor_override_internal()

    def _start_override_timer(self) -> None:
        """Set a QTimer to auto-revert the override after _OVERRIDE_SECS."""
        from PyQt5.QtCore import QTimer
        if self._override_timer is not None:
            try:
                self._override_timer.stop()
            except Exception:
                pass
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._end_supervisor_override_internal)
        timer.start(_OVERRIDE_SECS * 1000)
        self._override_timer = timer

    def _end_supervisor_override_internal(self) -> None:
        if self._override_timer is not None:
            try:
                self._override_timer.stop()
            except Exception:
                pass
            self._override_timer = None
        if self._session and self._session.supervisor_override_active:
            override_user = self._session._override_user
            self._session.supervisor_override_active = False
            self._session._override_user = None
            if override_user:
                self._auditor.log(
                    AuditLogger.SV_OVERRIDE_END,
                    actor=override_user.username,
                    uid=override_user.uid,
                    role=override_user.user_type.value,
                )
                log.info("Supervisor override ended: %s", override_user.username)

    # ── Public: inactivity management ─────────────────────────────────────

    def touch(self) -> None:
        """Reset the inactivity clock. Wire to mouseMoveEvent / keyPressEvent."""
        if self._session:
            self._session.touch()

    def check_lock_timeout(self, timeout_s: int) -> bool:
        """
        Call from a 30-second QTimer.

        Returns True and emits locked() if the session has been idle longer
        than *timeout_s* seconds.  Returns False otherwise.
        """
        if self._session and not self._locked:
            if self._session.is_expired(timeout_s):
                self.lock()
                return True
        return False

    # ── Public: accessors ─────────────────────────────────────────────────

    def current_session(self) -> Optional[AuthSession]:
        return self._session

    def current_user(self) -> Optional[User]:
        return self._session.user if self._session else None

    def is_locked(self) -> bool:
        return self._locked

    # ── Utility: password hashing ──────────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a plaintext password with bcrypt (work factor 12).

        Import-safe: raises ImportError with a helpful message if bcrypt
        is not installed.
        """
        try:
            import bcrypt
        except ImportError:
            raise ImportError(
                "bcrypt is required for password hashing. "
                "Install with: pip install bcrypt>=4.0"
            ) from None
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
