"""
ui/auth/login_screen.py

LoginScreen — full-window login gate for SanjINSIGHT.

This is a QWidget (not a QDialog) intended to be shown *before* the main
window is displayed.  main_app.py creates it, shows it, and waits for
``login_success(AuthSession)`` before constructing MainWindow.

Layout
------
  Full dark background with a centred 400 px card:
    ● App logo / wordmark
    ● Username field
    ● Password field  (Enter / Return triggers login)
    ● Error / lockout label
    ● [Log In] button  (disabled + spinner while verifying)

Lockout
-------
  After 5 consecutive failures the button is disabled and a countdown
  label ("Locked — try again in 4:32") updates every second via QTimer.
  Resets automatically when the lockout expires.

Signals
-------
  login_success(AuthSession)   — emitted on successful authentication

Usage in main_app.py
--------------------
  from ui.auth.login_screen import LoginScreen

  screen = LoginScreen(auth=_auth)
  screen.login_success.connect(_on_login_success)
  screen.show()
  screen.focus_username()
"""

from __future__ import annotations

import logging

from PyQt5.QtCore    import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy,
)

from ui.theme import (
    btn_wizard_primary_qss, wizard_input_qss, FONT, PALETTE,
)

log = logging.getLogger(__name__)

_BG      = "#0b0e1a"
_CARD_BG = "#12172a"
_BORDER  = "#2a3249"
_TEXT    = "#e0e0e0"
_DIM     = "#777777"


class LoginScreen(QWidget):
    """
    Full-window login gate.

    Parameters
    ----------
    auth :  Authenticator
        The Phase A authenticator facade.  authenticate() is called here;
        lockout_remaining() drives the countdown timer.
    parent : QWidget, optional
    """

    login_success = pyqtSignal(object)   # AuthSession

    def __init__(self, auth, parent=None):
        super().__init__(parent)
        self._auth = auth
        self._lockout_timer: QTimer | None = None
        self._locked_username: str = ""

        self.setWindowTitle("SanjINSIGHT — Log In")
        self.setMinimumSize(480, 400)
        self.setStyleSheet(f"background:{_BG};")

        # ── Centre card ────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        card_row = QHBoxLayout()
        card_row.addStretch(1)

        card = QFrame()
        card.setFixedWidth(400)
        card.setStyleSheet(
            f"QFrame {{ background:{_CARD_BG}; border:1px solid {_BORDER}; "
            f"border-radius:12px; }}")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(40, 40, 40, 40)
        card_lay.setSpacing(14)

        # ── Logo / wordmark ────────────────────────────────────────────────
        logo = QLabel("SanjINSIGHT")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "font-size:22pt; font-weight:800; color:#ffffff; "
            "background:transparent; border:none;")
        card_lay.addWidget(logo)

        tagline = QLabel("Thermoreflectance Imaging Platform")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:#555555; "
            "background:transparent; border:none;")
        card_lay.addWidget(tagline)

        card_lay.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER}; border:none; border-top:1px solid {_BORDER};")
        card_lay.addWidget(sep)

        card_lay.addSpacing(6)

        input_ss = wizard_input_qss()

        # ── Username ───────────────────────────────────────────────────────
        user_lbl = QLabel("Username")
        user_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:{_DIM}; "
            "background:transparent; border:none;")
        card_lay.addWidget(user_lbl)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Enter your username")
        self._user_edit.setFixedHeight(36)
        self._user_edit.setStyleSheet(input_ss)
        card_lay.addWidget(self._user_edit)

        # ── Password ───────────────────────────────────────────────────────
        pw_lbl = QLabel("Password")
        pw_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:{_DIM}; "
            "background:transparent; border:none;")
        card_lay.addWidget(pw_lbl)

        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Enter your password")
        self._pw_edit.setFixedHeight(36)
        self._pw_edit.setStyleSheet(input_ss)
        card_lay.addWidget(self._pw_edit)

        # ── Error / lockout message ────────────────────────────────────────
        self._msg_lbl = QLabel("")
        self._msg_lbl.setAlignment(Qt.AlignCenter)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            "background:transparent; border:none;")
        self._msg_lbl.setFixedHeight(32)
        card_lay.addWidget(self._msg_lbl)

        # ── Log In button ──────────────────────────────────────────────────
        self._login_btn = QPushButton("Log In")
        self._login_btn.setFixedHeight(40)
        self._login_btn.setStyleSheet(btn_wizard_primary_qss())
        card_lay.addWidget(self._login_btn)

        card_row.addWidget(card)
        card_row.addStretch(1)
        outer.addLayout(card_row)
        outer.addStretch(1)

        # ── Version watermark ──────────────────────────────────────────────
        try:
            import version as _v
            ver_txt = f"v{_v.VERSION}"
        except Exception:
            ver_txt = ""
        if ver_txt:
            ver_lbl = QLabel(ver_txt)
            ver_lbl.setAlignment(Qt.AlignCenter)
            ver_lbl.setStyleSheet(
                f"font-size:{FONT.get('caption', 8)}pt; color:#333333; "
                "background:transparent;")
            outer.addWidget(ver_lbl)
            outer.addSpacing(8)

        # ── Wire signals ───────────────────────────────────────────────────
        self._login_btn.clicked.connect(self._do_login)
        self._user_edit.returnPressed.connect(self._do_login)
        self._pw_edit.returnPressed.connect(self._do_login)

    # ── Public API ─────────────────────────────────────────────────────────────

    def focus_username(self) -> None:
        """Set keyboard focus to the username field. Call after show()."""
        self._user_edit.setFocus()

    def _apply_styles(self) -> None:
        """No-op by design.

        LoginScreen uses a fixed dark-card aesthetic regardless of the app
        theme (consistent with AdminSetupWizard and OperatorShell).  It is
        shown before MainWindow exists, so the theme-swap loop never reaches it.
        """

    # ── Login flow ─────────────────────────────────────────────────────────────

    def _do_login(self) -> None:
        username = self._user_edit.text().strip()
        password = self._pw_edit.text()

        if not username or not password:
            self._set_error("Please enter both username and password.")
            return

        # Check if still locked out before starting the async verify
        remaining = self._auth.lockout_remaining(username)
        if remaining > 0:
            self._start_lockout_display(username, remaining)
            return

        self._set_busy(True)

        def _on_result(session):
            self._set_busy(False)
            if session is not None:
                self._msg_lbl.setText("")
                log.info("LoginScreen: login success for '%s'", username)
                self.login_success.emit(session)
            else:
                # Check if we just triggered a lockout
                remaining2 = self._auth.lockout_remaining(username)
                if remaining2 > 0:
                    self._start_lockout_display(username, remaining2)
                else:
                    self._set_error("Invalid username or password.")

        self._auth.authenticate(username, password, _on_result)

    def _set_busy(self, busy: bool) -> None:
        self._login_btn.setEnabled(not busy)
        self._login_btn.setText("Verifying…" if busy else "Log In")
        self._user_edit.setEnabled(not busy)
        self._pw_edit.setEnabled(not busy)

    def _set_error(self, msg: str) -> None:
        self._msg_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            "background:transparent; border:none;")
        self._msg_lbl.setText(msg)

    # ── Lockout countdown ──────────────────────────────────────────────────────

    def _start_lockout_display(self, username: str, remaining_s: int) -> None:
        self._locked_username = username
        self._login_btn.setEnabled(False)
        self._user_edit.setEnabled(False)
        self._pw_edit.setEnabled(False)
        self._tick_lockout()

        if self._lockout_timer is None:
            self._lockout_timer = QTimer(self)
            self._lockout_timer.setInterval(1000)
            self._lockout_timer.timeout.connect(self._tick_lockout)
        self._lockout_timer.start()

    def _tick_lockout(self) -> None:
        remaining = self._auth.lockout_remaining(self._locked_username)
        if remaining <= 0:
            # Lockout expired
            if self._lockout_timer:
                self._lockout_timer.stop()
            self._locked_username = ""
            self._login_btn.setEnabled(True)
            self._user_edit.setEnabled(True)
            self._pw_edit.setEnabled(True)
            self._msg_lbl.setText("")
            self._login_btn.setText("Log In")
            return

        mins = remaining // 60
        secs = remaining % 60
        self._msg_lbl.setStyleSheet(
            f"color:{PALETTE.get('warning', '#ffaa44')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            "background:transparent; border:none;")
        self._msg_lbl.setText(
            f"Account locked — try again in {mins}:{secs:02d}")
        self._login_btn.setText(f"Locked ({mins}:{secs:02d})")
