"""
ui/auth/admin_setup_wizard.py

AdminSetupWizard — one-time administrator account creation dialog.

Shown automatically on first launch (when UserStore.has_users() is False).
Cannot be dismissed without creating an account — closing the window exits
the application.

Pages
-----
  Page 1  Welcome + role system overview
  Page 2  Create first admin account
          (display name, username, password × 2, strength meter, admin note)

On completion
-------------
  user_store.create_user() is called with is_admin=True.
  AuditLogger logs FIRST_ADMIN.
  exec_() returns QDialog.Accepted.

If the user closes the dialog on page 1 or 2, exec_() returns QDialog.Rejected
and the caller (main_app.py) should call sys.exit(0).
"""

from __future__ import annotations

import logging
import re

from PyQt5.QtCore    import Qt, QSize
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QWidget, QFrame, QSizePolicy,
    QProgressBar,
)

from ui.theme import (
    btn_wizard_primary_qss, btn_wizard_secondary_qss, wizard_input_qss,
    FONT, PALETTE,
)
from auth.models import UserType

log = logging.getLogger(__name__)


# ── Password strength ──────────────────────────────────────────────────────────

def _pw_strength(password: str) -> tuple[int, str]:
    """
    Returns (score 0-4, label).
    score: 0=empty, 1=weak, 2=fair, 3=good, 4=strong
    """
    if not password:
        return 0, ""
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[A-Z]", password) and re.search(r"[a-z]", password):
        score += 1
    if re.search(r"\d", password) and re.search(r"[^A-Za-z0-9]", password):
        score += 1
    labels = {0: "", 1: "Weak", 2: "Fair", 3: "Good", 4: "Strong"}
    return score, labels[score]


_STRENGTH_COLORS = {
    1: "#ff4466",
    2: "#ffaa44",
    3: "#4e73df",
    4: "#00d4aa",
}


# ── Shared visual helpers ──────────────────────────────────────────────────────

_H1_SS    = "font-size:22pt; font-weight:700; color:#ffffff;"
_H2_SS    = f"font-size:{FONT.get('body', 11)}pt; color:#aaaaaa; line-height:1.6;"
_BODY_SS  = f"font-size:{FONT.get('body', 11)}pt; color:#cccccc;"
_LABEL_SS = f"font-size:{FONT.get('label', 10)}pt; color:#888888;"
_BG       = "#0f1120"
_SURFACE  = "#181b2e"
_BORDER   = "#2a3249"


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{_BORDER};")
    return f


# ── Page 1: Welcome ────────────────────────────────────────────────────────────

class _PageWelcome(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_BG};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 36, 48, 24)
        lay.setSpacing(12)

        # Header
        h1 = QLabel("First Launch — Administrator Setup")
        h1.setStyleSheet(_H1_SS)
        lay.addWidget(h1)

        h2 = QLabel(
            "No user accounts exist yet. On the next page you will create the "
            "<b>administrator account</b> — the person responsible for managing users, "
            "approving scan profiles, and configuring system security.")
        h2.setStyleSheet(_H2_SS)
        h2.setWordWrap(True)
        lay.addWidget(h2)

        lay.addWidget(_hline())
        lay.addSpacing(4)

        # What the admin can do
        what_lbl = QLabel("As administrator you can:")
        what_lbl.setStyleSheet(_BODY_SS)
        lay.addWidget(what_lbl)

        for item in [
            "Add, edit, and deactivate user accounts",
            "Approve and lock scan profiles for operator use",
            "Configure login and security settings",
            "Access all instrument features",
        ]:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("✓")
            dot.setStyleSheet(
                f"color:{PALETTE.get('accent','#00d4aa')}; "
                f"font-size:{FONT.get('body', 11)}pt;")
            dot.setFixedWidth(18)
            row.addWidget(dot)
            lbl = QLabel(item)
            lbl.setStyleSheet(
                f"font-size:{FONT.get('body', 11)}pt; color:#cccccc;")
            row.addWidget(lbl, 1)
            lay.addLayout(row)

        lay.addSpacing(8)
        lay.addWidget(_hline())
        lay.addSpacing(4)

        # Role overview
        intro = QLabel("Three user types are built in:")
        intro.setStyleSheet(_BODY_SS)
        lay.addWidget(intro)

        lay.addLayout(self._role_row(
            "Technician",
            "Runs QA scans from approved scan profiles. Simple guided interface "
            "with PASS/FAIL verdict. Cannot create or edit profiles.",
            "#5b8ff9",
        ))
        lay.addLayout(self._role_row(
            "Failure Analyst",
            "Diagnoses device failures. Full instrument access. "
            "Evidence-first AI guidance.",
            "#00d4aa",
        ))
        lay.addLayout(self._role_row(
            "Researcher",
            "Explores, learns, and publishes results. Full instrument access. "
            "Explanatory AI mode.",
            "#ffaa44",
        ))

        lay.addSpacing(8)
        next_steps = QLabel(
            "After setup: open Settings to add user accounts and, optionally, "
            "enable login enforcement.")
        next_steps.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:#777777; "
            f"background:{_SURFACE}; border:1px solid {_BORDER}; border-radius:5px; "
            "padding:10px;")
        next_steps.setWordWrap(True)
        lay.addWidget(next_steps)

        lay.addStretch(1)

    @staticmethod
    def _role_row(title: str, desc: str, color: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(12)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:10pt;")
        dot.setFixedWidth(16)
        dot.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        h.addWidget(dot)
        body = QVBoxLayout()
        body.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet(f"font-size:{FONT.get('body', 11)}pt; font-weight:700; color:#dddddd;")
        body.addWidget(t)
        d = QLabel(desc)
        d.setStyleSheet(f"font-size:{FONT.get('sublabel', 9)}pt; color:#888888;")
        d.setWordWrap(True)
        body.addWidget(d)
        h.addLayout(body)
        return h


# ── Page 2: Create first admin ─────────────────────────────────────────────────

class _PageCreateAdmin(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_BG};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 36, 48, 24)
        lay.setSpacing(10)

        h1 = QLabel("Create Administrator Account")
        h1.setStyleSheet(_H1_SS)
        lay.addWidget(h1)

        h2 = QLabel(
            "This account will have full access to all settings and user management. "
            "You can add more users from Settings after setup.")
        h2.setStyleSheet(_H2_SS)
        h2.setWordWrap(True)
        lay.addWidget(h2)

        lay.addWidget(_hline())
        lay.addSpacing(6)

        input_ss = wizard_input_qss()

        # Display name
        lay.addWidget(self._field_label("Display name"))
        self._display_edit = QLineEdit()
        self._display_edit.setPlaceholderText("e.g. Jane Smith")
        self._display_edit.setFixedHeight(34)
        self._display_edit.setStyleSheet(input_ss)
        lay.addWidget(self._display_edit)

        lay.addSpacing(4)

        # Username
        lay.addWidget(self._field_label("Username  (used to log in)"))
        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("e.g. jsmith")
        self._user_edit.setFixedHeight(34)
        self._user_edit.setStyleSheet(input_ss)
        lay.addWidget(self._user_edit)

        lay.addSpacing(4)

        # Password
        lay.addWidget(self._field_label("Password"))
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Minimum 8 characters")
        self._pw_edit.setFixedHeight(34)
        self._pw_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw_edit)

        # Strength bar
        strength_row = QHBoxLayout()
        self._strength_bar = QProgressBar()
        self._strength_bar.setRange(0, 4)
        self._strength_bar.setValue(0)
        self._strength_bar.setFixedHeight(5)
        self._strength_bar.setTextVisible(False)
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            "QProgressBar::chunk { background:#ff4466; border-radius:2px; }")
        self._strength_lbl = QLabel("")
        self._strength_lbl.setFixedWidth(60)
        self._strength_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:#888888;")
        strength_row.addWidget(self._strength_bar)
        strength_row.addSpacing(8)
        strength_row.addWidget(self._strength_lbl)
        lay.addLayout(strength_row)

        lay.addSpacing(4)

        # Confirm password
        lay.addWidget(self._field_label("Confirm password"))
        self._pw2_edit = QLineEdit()
        self._pw2_edit.setEchoMode(QLineEdit.Password)
        self._pw2_edit.setPlaceholderText("Repeat password")
        self._pw2_edit.setFixedHeight(34)
        self._pw2_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw2_edit)

        # Error message
        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt;")
        lay.addWidget(self._error_lbl)

        lay.addStretch(1)

        # Wire signals
        self._pw_edit.textChanged.connect(self._update_strength)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_SS)
        return lbl

    def _update_strength(self, text: str) -> None:
        score, label = _pw_strength(text)
        self._strength_bar.setValue(score)
        color = _STRENGTH_COLORS.get(score, "#ff4466")
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}")
        self._strength_lbl.setText(label)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:{color};")

    def validate(self) -> tuple[bool, str]:
        """Return (ok, error_message). Clears error label on success."""
        display = self._display_edit.text().strip()
        username = self._user_edit.text().strip()
        pw  = self._pw_edit.text()
        pw2 = self._pw2_edit.text()

        if not display:
            self._error_lbl.setText("Display name is required.")
            return False, "Display name is required."
        if not username:
            self._error_lbl.setText("Username is required.")
            return False, "Username is required."
        if " " in username:
            self._error_lbl.setText("Username cannot contain spaces.")
            return False, "Username cannot contain spaces."
        if len(pw) < 8:
            self._error_lbl.setText("Password must be at least 8 characters.")
            return False, "Password must be at least 8 characters."
        if pw != pw2:
            self._error_lbl.setText("Passwords do not match.")
            return False, "Passwords do not match."

        self._error_lbl.setText("")
        return True, ""

    def values(self) -> dict:
        return {
            "display_name": self._display_edit.text().strip(),
            "username":     self._user_edit.text().strip(),
            "password":     self._pw_edit.text(),
        }

    def focus_display(self) -> None:
        self._display_edit.setFocus()


# ── AdminSetupWizard ───────────────────────────────────────────────────────────

class AdminSetupWizard(QDialog):
    """
    One-time administrator account creation wizard.

    Usage::

        wizard = AdminSetupWizard(user_store, audit_logger, parent=app_window)
        if wizard.exec_() != QDialog.Accepted:
            sys.exit(0)

    The dialog is modal and cannot be escaped without creating an account.
    """

    def __init__(self, user_store, audit_logger, parent=None):
        super().__init__(parent)
        self._store        = user_store
        self._auditor      = audit_logger
        self._created_user = None   # set after successful creation

        self.setWindowTitle("SanjINSIGHT — First Launch Setup")
        self.setMinimumSize(620, 540)
        self.resize(660, 580)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Pages ────────────────────────────────────────────────────────────
        self._pages = QStackedWidget()
        self._page_welcome      = _PageWelcome()
        self._page_create_admin = _PageCreateAdmin()
        self._pages.addWidget(self._page_welcome)       # index 0
        self._pages.addWidget(self._page_create_admin)  # index 1
        root.addWidget(self._pages, 1)

        # ── Footer ───────────────────────────────────────────────────────────
        footer_frame = QFrame()
        footer_frame.setFixedHeight(68)
        footer_frame.setStyleSheet(
            f"background:{_SURFACE}; border-top:1px solid {_BORDER};")
        footer_lay = QHBoxLayout(footer_frame)
        footer_lay.setContentsMargins(40, 12, 40, 12)

        # Step indicator (1 / 2)
        self._step_lbl = QLabel("Step 1 of 2")
        self._step_lbl.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:#555555;")
        footer_lay.addWidget(self._step_lbl)
        footer_lay.addStretch(1)

        # Back / Next / Finish
        btn_ss_sec = btn_wizard_secondary_qss()
        btn_ss_pri = btn_wizard_primary_qss()

        self._back_btn = QPushButton("Back")
        self._back_btn.setFixedSize(QSize(90, 36))
        self._back_btn.setStyleSheet(btn_ss_sec)
        self._back_btn.setVisible(False)

        self._next_btn = QPushButton("Next  →")
        self._next_btn.setFixedSize(QSize(110, 36))
        self._next_btn.setStyleSheet(btn_ss_pri)

        footer_lay.addWidget(self._back_btn)
        footer_lay.addSpacing(8)
        footer_lay.addWidget(self._next_btn)

        root.addWidget(footer_frame)

        # ── Signals ──────────────────────────────────────────────────────────
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_next(self) -> None:
        idx = self._pages.currentIndex()
        if idx == 0:
            self._pages.setCurrentIndex(1)
            self._page_create_admin.focus_display()
            self._back_btn.setVisible(True)
            self._next_btn.setText("Create Account")
            self._step_lbl.setText("Step 2 of 2")
        elif idx == 1:
            self._finish()

    def _go_back(self) -> None:
        self._pages.setCurrentIndex(0)
        self._back_btn.setVisible(False)
        self._next_btn.setText("Next  →")
        self._step_lbl.setText("Step 1 of 2")

    # ── Account creation ──────────────────────────────────────────────────────

    def _finish(self) -> None:
        ok, _ = self._page_create_admin.validate()
        if not ok:
            return

        vals = self._page_create_admin.values()
        self._next_btn.setEnabled(False)
        self._next_btn.setText("Creating…")

        try:
            from auth.authenticator import Authenticator
            pw_hash = Authenticator.hash_password(vals["password"])
        except ImportError as exc:
            self._page_create_admin._error_lbl.setText(str(exc))
            self._next_btn.setEnabled(True)
            self._next_btn.setText("Create Account")
            return

        try:
            self._store.create_user(
                username     = vals["username"],
                display_name = vals["display_name"],
                user_type    = UserType.RESEARCHER,   # admin type doesn't matter
                pw_hash      = pw_hash,
                is_admin     = True,
                created_by   = "",
            )
            self._auditor.log(
                "first_admin_created",
                actor = vals["username"],
                role  = "researcher",
            )
            self._created_user = self._store.get_by_username(vals["username"])
            log.info("AdminSetupWizard: first admin '%s' created", vals["username"])
        except Exception as exc:
            self._page_create_admin._error_lbl.setText(f"Error: {exc}")
            self._next_btn.setEnabled(True)
            self._next_btn.setText("Create Account")
            return

        self.accept()

    def created_user(self):
        """Return the User that was just created, or None."""
        return self._created_user

    # ── Close guard — cannot dismiss without creating an account ──────────────

    def closeEvent(self, event):
        event.accept()
        self.reject()
