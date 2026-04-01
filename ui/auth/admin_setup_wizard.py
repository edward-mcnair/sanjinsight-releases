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
    QProgressBar, QScrollArea,
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


def _strength_color(score: int) -> str:
    """Return PALETTE-driven color for password strength score."""
    return {
        1: PALETTE['danger'],
        2: PALETTE['warning'],
        3: PALETTE['cta'],
        4: PALETTE['accent'],
    }.get(score, PALETTE['danger'])


# ── Shared visual helpers ──────────────────────────────────────────────────────

def _H1_SS():   return f"font-size:22pt; font-weight:700; color:{PALETTE['text']};"
def _H2_SS():   return f"font-size:{FONT.get('bodyf', 11)}pt; color:{PALETTE['textDim']}; line-height:1.6;"
def _BODY_SS(): return f"font-size:{FONT.get('bodyf', 11)}pt; color:{PALETTE['text']};"
def _LABEL_SS(): return f"font-size:{FONT.get('labelf', 10)}pt; color:{PALETTE['textDim']};"


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{PALETTE['border']};")
    return f


# ── Page 1: Welcome ────────────────────────────────────────────────────────────

class _PageWelcome(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        P = PALETTE
        self.setStyleSheet(f"background:{P['bg']};")

        # Outer layout wraps a scroll area so the page works at any dialog height
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{P['bg']}; border:none; }}"
            f"QScrollBar:vertical {{ width:6px; background:{P['bg']}; }}"
            f"QScrollBar::handle:vertical {{ background:{P['border']}; border-radius:3px; }}")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background:{P['bg']};")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(48, 36, 48, 28)
        lay.setSpacing(10)
        scroll.setWidget(content)

        # ── Headline ─────────────────────────────────────────────────────────
        h1 = QLabel("First Launch — Administrator Setup")
        h1.setStyleSheet(_H1_SS())
        lay.addWidget(h1)

        h2 = QLabel(
            "No user accounts exist yet.  You are about to create the "
            "<b>administrator account</b> — the top-level account that controls "
            "user management, scan profile approvals, and system security.")
        h2.setStyleSheet(_H2_SS())
        h2.setWordWrap(True)
        lay.addWidget(h2)

        lay.addWidget(_hline())

        # ── Admin account card ────────────────────────────────────────────────
        acc = P["accent"]
        admin_card = QFrame()
        admin_card.setStyleSheet(
            f"QFrame {{ background:{P['readyBg']}; border:1px solid {acc}44; "
            f"border-left:3px solid {acc}; border-radius:6px; }}")
        ac_lay = QVBoxLayout(admin_card)
        ac_lay.setContentsMargins(14, 12, 14, 12)
        ac_lay.setSpacing(8)

        admin_title = QLabel("Your account: Administrator")
        admin_title.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{acc}; background:transparent;")
        ac_lay.addWidget(admin_title)

        admin_desc = QLabel(
            "The administrator account is unique — it is not assigned to a single "
            "user type but has access to everything.  There is only one admin account "
            "per installation.")
        admin_desc.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textDim']}; background:transparent;")
        admin_desc.setWordWrap(True)
        ac_lay.addWidget(admin_desc)

        for item in [
            "Add, edit, and deactivate user accounts",
            "Assign roles (Technician, Failure Analyst, Researcher) to each user",
            "Approve and lock scan profiles so Technicians can run them",
            "Enable or disable login enforcement and set session timeouts",
            "Access every tab and instrument feature",
        ]:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            chk = QLabel("✓")
            chk.setStyleSheet(
                f"color:{acc}; font-size:{FONT.get('body', 11)}pt; background:transparent;")
            chk.setFixedWidth(16)
            row.addWidget(chk)
            lbl = QLabel(item)
            lbl.setStyleSheet(
                f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['text']}; background:transparent;")
            row.addWidget(lbl, 1)
            ac_lay.addLayout(row)

        lay.addWidget(admin_card)
        lay.addWidget(_hline())

        # ── User role overview ────────────────────────────────────────────────
        roles_hdr = QLabel("User roles you will create")
        roles_hdr.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; color:{P['text']};")
        lay.addWidget(roles_hdr)

        roles_sub = QLabel(
            "After creating your admin account you can add users from Settings.  "
            "Each user is assigned one of these three roles:")
        roles_sub.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textDim']};")
        roles_sub.setWordWrap(True)
        lay.addWidget(roles_sub)

        lay.addWidget(self._role_card(
            "Technician",
            "Runs approved QA scans and views PASS / FAIL verdicts.",
            P["cta"],
            can=[
                "Run scan profiles approved by the admin",
                "View scan results and PASS/FAIL verdict",
            ],
            cannot=[
                "Create or edit scan profiles",
                "Access full instrument settings",
                "Manage users or security settings",
            ],
            interface="Guided operator interface",
        ))
        lay.addWidget(self._role_card(
            "Failure Analyst",
            "Diagnoses device failures using the full instrument interface.",
            P["accent"],
            can=[
                "Full access to all acquisition and analysis tabs",
                "Create and edit scan profiles (requires admin approval to deploy)",
                "Evidence-guided AI assistance",
            ],
            cannot=[
                "Manage user accounts",
                "Change security / login settings",
            ],
            interface="Full instrument interface",
        ))
        lay.addWidget(self._role_card(
            "Researcher",
            "Explores experimental parameters and publishes results.",
            P["warning"],
            can=[
                "Full access to all acquisition and analysis tabs",
                "Create and edit scan profiles (requires admin approval to deploy)",
                "Explanatory AI mode for learning and documentation",
            ],
            cannot=[
                "Manage user accounts",
                "Change security / login settings",
            ],
            interface="Full instrument interface",
        ))

        # ── Next steps hint ───────────────────────────────────────────────────
        lay.addSpacing(4)
        next_steps = QLabel(
            "▶  After setup: open Settings → Security to add users and, optionally, "
            "enable login enforcement so users must authenticate on each launch.")
        next_steps.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textDim']}; "
            f"background:{P['surface']}; border:1px solid {P['border']}; border-radius:5px; "
            "padding:10px;")
        next_steps.setWordWrap(True)
        lay.addWidget(next_steps)

        lay.addStretch(1)

    @staticmethod
    def _role_card(title: str, desc: str, color: str,
                   can: list, cannot: list, interface: str) -> QFrame:
        P = PALETTE
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{P['surface']}; border:1px solid {P['border']}; "
            f"border-left:3px solid {color}; border-radius:6px; }}")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(14, 10, 14, 10)
        c_lay.setSpacing(6)

        # Title row + interface badge
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
            f"color:{color}; background:transparent;")
        title_row.addWidget(t)

        badge = QLabel(interface)
        badge.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:{color}; "
            f"background:{color}18; border:1px solid {color}44; border-radius:3px; "
            "padding:1px 6px;")
        title_row.addWidget(badge)
        title_row.addStretch()
        c_lay.addLayout(title_row)

        d = QLabel(desc)
        d.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textDim']}; background:transparent;")
        d.setWordWrap(True)
        c_lay.addWidget(d)

        # Can / Cannot columns
        cols = QHBoxLayout()
        cols.setSpacing(12)

        can_col = QVBoxLayout()
        can_col.setSpacing(3)
        for item in can:
            row = QHBoxLayout()
            row.setSpacing(6)
            chk = QLabel("✓")
            chk.setStyleSheet(
                f"color:{P['accent']}; font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
            chk.setFixedWidth(14)
            lbl = QLabel(item)
            lbl.setStyleSheet(
                f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textDim']}; background:transparent;")
            lbl.setWordWrap(True)
            row.addWidget(chk)
            row.addWidget(lbl, 1)
            can_col.addLayout(row)
        can_col.addStretch()

        cannot_col = QVBoxLayout()
        cannot_col.setSpacing(3)
        for item in cannot:
            row = QHBoxLayout()
            row.setSpacing(6)
            chk = QLabel("✗")
            chk.setStyleSheet(
                f"color:{P['danger']}; font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
            chk.setFixedWidth(14)
            lbl = QLabel(item)
            lbl.setStyleSheet(
                f"font-size:{FONT.get('sublabel', 9)}pt; color:{P['textSub']}; background:transparent;")
            lbl.setWordWrap(True)
            row.addWidget(chk)
            row.addWidget(lbl, 1)
            cannot_col.addLayout(row)
        cannot_col.addStretch()

        cols.addLayout(can_col, 1)
        cols.addLayout(cannot_col, 1)
        c_lay.addLayout(cols)

        return card


# ── Page 2: Create first admin ─────────────────────────────────────────────────

class _PageCreateAdmin(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{PALETTE['bg']};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 36, 48, 24)
        lay.setSpacing(10)

        h1 = QLabel("Create Administrator Account")
        h1.setStyleSheet(_H1_SS())
        lay.addWidget(h1)

        h2 = QLabel(
            "This account will have full access to all settings and user management. "
            "You can add more users from Settings after setup.")
        h2.setStyleSheet(_H2_SS())
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
            f"QProgressBar {{ background:{PALETTE['surface']}; border:none; border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['danger']}; border-radius:2px; }}")
        self._strength_lbl = QLabel("")
        self._strength_lbl.setFixedWidth(60)
        self._strength_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('captionf', 8)}pt; color:{PALETTE['textDim']};")
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
            f"color:{PALETTE['danger']}; "
            f"font-size:{FONT.get('sublabel', 9)}pt;")
        lay.addWidget(self._error_lbl)

        lay.addStretch(1)

        # Wire signals
        self._pw_edit.textChanged.connect(self._update_strength)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_SS())
        return lbl

    def _update_strength(self, text: str) -> None:
        score, label = _pw_strength(text)
        self._strength_bar.setValue(score)
        color = _strength_color(score)
        self._strength_bar.setStyleSheet(
            f"QProgressBar {{ background:{PALETTE['surface']}; border:none; border-radius:2px; }}"
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
        self.setMinimumSize(640, 580)
        self.resize(680, 680)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background:{PALETTE['bg']}; }}")

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
            f"background:{PALETTE['surface']}; border-top:1px solid {PALETTE['border']};")
        footer_lay = QHBoxLayout(footer_frame)
        footer_lay.setContentsMargins(40, 12, 40, 12)

        # Step indicator (1 / 2)
        self._step_lbl = QLabel("Step 1 of 2")
        self._step_lbl.setStyleSheet(
            f"font-size:{FONT.get('sublabelf', 9)}pt; color:{PALETTE['textSub']};")
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
