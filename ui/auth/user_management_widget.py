"""
ui/auth/user_management_widget.py

UserManagementWidget — admin-only user CRUD panel embedded in SettingsTab.

Visible only when the active session has is_admin == True.

Layout
------
  Toolbar:  [+ Add User]  [Edit]  [Deactivate]  [Reset Password]
  ─────────────────────────────────────────────────────────────
  QTableWidget:
    Display Name | Username | Type | Admin | Last Login | Active

Sub-dialogs (private)
---------------------
  _AddUserDialog      Three profile cards + admin checkbox + credentials
  _EditUserDialog     Same cards (pre-selected) + display name + admin toggle
  _ResetPasswordDialog  New password × 2 + strength indicator

Usage
-----
  from ui.auth.user_management_widget import UserManagementWidget

  self._users_widget = UserManagementWidget(
      store=user_store,
      auditor=audit_logger,
      auth=authenticator,
      parent=self,
  )
  settings_layout.addWidget(self._users_widget)
  # Refresh whenever auth session changes:
  self._users_widget.refresh(auth_session)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtGui     import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QFrame, QCheckBox, QProgressBar, QSizePolicy,
    QMessageBox, QAbstractItemView,
)

from ui.theme import (
    btn_primary_qss, btn_secondary_qss, btn_danger_qss,
    btn_wizard_primary_qss, btn_wizard_secondary_qss, wizard_input_qss,
    input_qss, FONT, PALETTE,
)
from auth.models import UserType

log = logging.getLogger(__name__)

# ── Password-strength helper (shared with AdminSetupWizard) ───────────────────

def _pw_strength(password: str) -> tuple[int, str]:
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


_STRENGTH_COLORS = {1: "#ff4466", 2: "#ffaa44", 3: "#4e73df", 4: "#00d4aa"}

_DLG_BG     = "#0f1120"
_DLG_SURF   = "#181b2e"
_DLG_BORDER = "#2a3249"


# ── Profile-card widget ────────────────────────────────────────────────────────

_CARD_INFO = {
    UserType.TECHNICIAN: {
        "icon": "Technician",
        "color": "#5b8ff9",
        "desc":  "Runs QA scans per SOP.\nGuided UI with PASS/FAIL verdict.",
    },
    UserType.FAILURE_ANALYST: {
        "icon": "Failure Analyst",
        "color": "#00d4aa",
        "desc":  "Diagnoses device failures.\nEvidence-first AI. Full UI.",
    },
    UserType.RESEARCHER: {
        "icon": "Researcher",
        "color": "#ffaa44",
        "desc":  "Explores, learns, and publishes.\nExplanatory AI. Full UI.",
    },
}


class _ProfileCardSet(QWidget):
    """
    Three horizontally-arranged profile cards.  Clicking one selects it.
    Emits ``selection_changed(UserType)`` when the selection changes.
    """

    selection_changed = pyqtSignal(object)   # UserType

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected: Optional[UserType] = None
        self._cards: dict[UserType, QFrame] = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        for ut in (UserType.TECHNICIAN, UserType.FAILURE_ANALYST, UserType.RESEARCHER):
            info  = _CARD_INFO[ut]
            card  = QFrame()
            card.setFixedSize(160, 110)
            card.setStyleSheet(self._card_qss(info["color"], selected=False))
            card.setCursor(Qt.PointingHandCursor)

            inner = QVBoxLayout(card)
            inner.setContentsMargins(10, 10, 10, 10)
            inner.setSpacing(4)

            title = QLabel(info["icon"])
            title.setStyleSheet(
                f"font-size:{FONT.get('body', 11)}pt; font-weight:700; "
                f"color:{info['color']}; background:transparent;")
            inner.addWidget(title)

            desc = QLabel(info["desc"])
            desc.setWordWrap(True)
            desc.setStyleSheet(
                f"font-size:{FONT.get('caption', 8)}pt; color:#777777; "
                "background:transparent;")
            inner.addWidget(desc)
            inner.addStretch(1)

            self._cards[ut] = card
            row.addWidget(card)

            # Install click filter
            card.mousePressEvent = lambda _ev, u=ut: self._select(u)

        row.addStretch(1)

    @staticmethod
    def _card_qss(color: str, selected: bool) -> str:
        bg     = _DLG_SURF if not selected else f"{color}18"
        border = color if selected else _DLG_BORDER
        width  = 2 if selected else 1
        return (
            f"QFrame {{ background:{bg}; border:{width}px solid {border}; "
            "border-radius:8px; }}"
        )

    def _select(self, user_type: UserType) -> None:
        self._selected = user_type
        for ut, card in self._cards.items():
            info = _CARD_INFO[ut]
            card.setStyleSheet(self._card_qss(info["color"], selected=(ut == user_type)))
        self.selection_changed.emit(user_type)

    def selected(self) -> Optional[UserType]:
        return self._selected

    def set_selected(self, user_type: UserType) -> None:
        self._select(user_type)


# ── Add User dialog ────────────────────────────────────────────────────────────

class _AddUserDialog(QDialog):
    """Create a new user account."""

    def __init__(self, store, auditor, creating_uid: str, parent=None):
        super().__init__(parent)
        self._store       = store
        self._auditor     = auditor
        self._creating_uid = creating_uid
        self._created_user = None

        self.setWindowTitle("Add User")
        self.setFixedSize(560, 560)
        self.setStyleSheet(f"QDialog {{ background:{_DLG_BG}; }}")
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)

        # Title
        title = QLabel("Who is this user?")
        title.setStyleSheet(
            "font-size:16pt; font-weight:700; color:#ffffff; background:transparent;")
        lay.addWidget(title)

        # Profile cards
        self._cards = _ProfileCardSet()
        lay.addWidget(self._cards)

        # Admin checkbox
        self._admin_chk = QCheckBox(
            "Grant administrator privileges  "
            "(user management, global settings, recipe approval)")
        self._admin_chk.setStyleSheet(
            f"color:{PALETTE.get('textDim', '#999999')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
        lay.addWidget(self._admin_chk)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_DLG_BORDER};")
        lay.addWidget(sep)

        input_ss = wizard_input_qss()

        # Display name
        lay.addWidget(self._lbl("Display name"))
        self._display_edit = QLineEdit()
        self._display_edit.setPlaceholderText("e.g. Jane Smith")
        self._display_edit.setFixedHeight(34)
        self._display_edit.setStyleSheet(input_ss)
        lay.addWidget(self._display_edit)

        # Username
        lay.addWidget(self._lbl("Username  (used to log in)"))
        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("e.g. jsmith")
        self._user_edit.setFixedHeight(34)
        self._user_edit.setStyleSheet(input_ss)
        lay.addWidget(self._user_edit)

        # Password
        lay.addWidget(self._lbl("Password"))
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Minimum 8 characters")
        self._pw_edit.setFixedHeight(34)
        self._pw_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw_edit)

        # Strength bar
        srow = QHBoxLayout()
        self._strength_bar = QProgressBar()
        self._strength_bar.setRange(0, 4)
        self._strength_bar.setValue(0)
        self._strength_bar.setFixedHeight(5)
        self._strength_bar.setTextVisible(False)
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            "QProgressBar::chunk { background:#ff4466; border-radius:2px; }")
        self._strength_lbl = QLabel("")
        self._strength_lbl.setFixedWidth(55)
        self._strength_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:#888; background:transparent;")
        srow.addWidget(self._strength_bar)
        srow.addSpacing(8)
        srow.addWidget(self._strength_lbl)
        lay.addLayout(srow)

        # Confirm password
        lay.addWidget(self._lbl("Confirm password"))
        self._pw2_edit = QLineEdit()
        self._pw2_edit.setEchoMode(QLineEdit.Password)
        self._pw2_edit.setPlaceholderText("Repeat password")
        self._pw2_edit.setFixedHeight(34)
        self._pw2_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw2_edit)

        # Error label
        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
        lay.addWidget(self._err_lbl)

        lay.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setStyleSheet(btn_wizard_secondary_qss())
        self._create_btn = QPushButton("Create User")
        self._create_btn.setFixedHeight(36)
        self._create_btn.setStyleSheet(btn_wizard_primary_qss())
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._create_btn)
        lay.addLayout(btn_row)

        self._pw_edit.textChanged.connect(self._update_strength)
        self._cancel_btn.clicked.connect(self.reject)
        self._create_btn.clicked.connect(self._create)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:#777777; background:transparent;")
        return l

    def _update_strength(self, text: str) -> None:
        score, label = _pw_strength(text)
        self._strength_bar.setValue(score)
        color = _STRENGTH_COLORS.get(score, "#ff4466")
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}")
        self._strength_lbl.setText(label)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:{color}; background:transparent;")

    def _create(self) -> None:
        user_type = self._cards.selected()
        if user_type is None:
            self._err_lbl.setText("Please select a user type.")
            return

        display  = self._display_edit.text().strip()
        username = self._user_edit.text().strip()
        pw       = self._pw_edit.text()
        pw2      = self._pw2_edit.text()

        if not display:
            self._err_lbl.setText("Display name is required.")
            return
        if not username:
            self._err_lbl.setText("Username is required.")
            return
        if " " in username:
            self._err_lbl.setText("Username cannot contain spaces.")
            return
        if len(pw) < 8:
            self._err_lbl.setText("Password must be at least 8 characters.")
            return
        if pw != pw2:
            self._err_lbl.setText("Passwords do not match.")
            return

        self._create_btn.setEnabled(False)
        self._create_btn.setText("Creating…")

        try:
            from auth.authenticator import Authenticator
            pw_hash = Authenticator.hash_password(pw)
        except ImportError as exc:
            self._err_lbl.setText(str(exc))
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create User")
            return

        try:
            user = self._store.create_user(
                username     = username,
                display_name = display,
                user_type    = user_type,
                pw_hash      = pw_hash,
                is_admin     = self._admin_chk.isChecked(),
                created_by   = self._creating_uid,
            )
            self._auditor.log(
                "user_created",
                actor  = username,
                uid    = user.uid,
                role   = user_type.value,
                detail = f"admin={self._admin_chk.isChecked()}, "
                         f"created_by={self._creating_uid}",
            )
            self._created_user = user
            self.accept()
        except Exception as exc:
            self._err_lbl.setText(f"Error: {exc}")
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create User")

    def created_user(self):
        """Return the created User, or None if dialog was rejected."""
        return self._created_user


# ── Edit User dialog ───────────────────────────────────────────────────────────

class _EditUserDialog(QDialog):
    """Edit an existing user's display name, type, and admin flag."""

    def __init__(self, user, store, auditor, acting_uid: str, parent=None):
        super().__init__(parent)
        self._user      = user
        self._store     = store
        self._auditor   = auditor
        self._acting_uid = acting_uid

        self.setWindowTitle(f"Edit User — {user.display_name}")
        self.setFixedSize(560, 380)
        self.setStyleSheet(f"QDialog {{ background:{_DLG_BG}; }}")
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)

        title = QLabel(f"Edit: {user.display_name}")
        title.setStyleSheet(
            "font-size:15pt; font-weight:700; color:#ffffff; background:transparent;")
        lay.addWidget(title)

        input_ss = wizard_input_qss()

        # Display name
        lay.addWidget(self._lbl("Display name"))
        self._display_edit = QLineEdit(user.display_name)
        self._display_edit.setFixedHeight(34)
        self._display_edit.setStyleSheet(input_ss)
        lay.addWidget(self._display_edit)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_DLG_BORDER};")
        lay.addWidget(sep)

        user_type_lbl = QLabel("User type")
        user_type_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:#777777; background:transparent;")
        lay.addWidget(user_type_lbl)

        self._cards = _ProfileCardSet()
        self._cards.set_selected(user.user_type)
        lay.addWidget(self._cards)

        self._admin_chk = QCheckBox(
            "Grant administrator privileges  "
            "(user management, global settings, recipe approval)")
        self._admin_chk.setChecked(user.is_admin)
        self._admin_chk.setStyleSheet(
            f"color:{PALETTE.get('textDim', '#999999')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
        lay.addWidget(self._admin_chk)

        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
        lay.addWidget(self._err_lbl)

        lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setStyleSheet(btn_wizard_secondary_qss())
        self._save_btn = QPushButton("Save Changes")
        self._save_btn.setFixedHeight(36)
        self._save_btn.setStyleSheet(btn_wizard_primary_qss())
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._save_btn)
        lay.addLayout(btn_row)

        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn.clicked.connect(self._save)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:#777777; background:transparent;")
        return l

    def _save(self) -> None:
        new_display  = self._display_edit.text().strip()
        new_type     = self._cards.selected() or self._user.user_type
        new_is_admin = self._admin_chk.isChecked()

        if not new_display:
            self._err_lbl.setText("Display name is required.")
            return

        try:
            if new_display != self._user.display_name:
                self._store.update_display_name(self._user.uid, new_display)
            if new_type != self._user.user_type:
                self._store.update_user_type(self._user.uid, new_type)
            if new_is_admin != self._user.is_admin:
                self._store.set_admin(self._user.uid, new_is_admin)

            self._auditor.log(
                "user_modified",
                actor  = self._user.username,
                uid    = self._user.uid,
                role   = new_type.value,
                detail = f"by={self._acting_uid}",
            )
            self.accept()
        except Exception as exc:
            self._err_lbl.setText(f"Error: {exc}")


# ── Reset Password dialog ──────────────────────────────────────────────────────

class _ResetPasswordDialog(QDialog):
    """Admin-initiated password reset for any user."""

    def __init__(self, user, store, auditor, acting_uid: str, parent=None):
        super().__init__(parent)
        self._user       = user
        self._store      = store
        self._auditor    = auditor
        self._acting_uid = acting_uid

        self.setWindowTitle(f"Reset Password — {user.display_name}")
        self.setFixedSize(400, 300)
        self.setStyleSheet(f"QDialog {{ background:{_DLG_BG}; }}")
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)

        title = QLabel(f"Reset password for {user.display_name}")
        title.setWordWrap(True)
        title.setStyleSheet(
            "font-size:14pt; font-weight:700; color:#ffffff; background:transparent;")
        lay.addWidget(title)

        input_ss = wizard_input_qss()

        lay.addWidget(self._lbl("New password"))
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Minimum 8 characters")
        self._pw_edit.setFixedHeight(34)
        self._pw_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw_edit)

        # Strength bar
        srow = QHBoxLayout()
        self._strength_bar = QProgressBar()
        self._strength_bar.setRange(0, 4)
        self._strength_bar.setValue(0)
        self._strength_bar.setFixedHeight(5)
        self._strength_bar.setTextVisible(False)
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            "QProgressBar::chunk { background:#ff4466; border-radius:2px; }")
        self._strength_lbl = QLabel("")
        self._strength_lbl.setFixedWidth(55)
        self._strength_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:#888; background:transparent;")
        srow.addWidget(self._strength_bar)
        srow.addSpacing(8)
        srow.addWidget(self._strength_lbl)
        lay.addLayout(srow)

        lay.addWidget(self._lbl("Confirm new password"))
        self._pw2_edit = QLineEdit()
        self._pw2_edit.setEchoMode(QLineEdit.Password)
        self._pw2_edit.setPlaceholderText("Repeat password")
        self._pw2_edit.setFixedHeight(34)
        self._pw2_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw2_edit)

        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; background:transparent;")
        lay.addWidget(self._err_lbl)

        lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setStyleSheet(btn_wizard_secondary_qss())
        self._reset_btn = QPushButton("Reset Password")
        self._reset_btn.setFixedHeight(36)
        self._reset_btn.setStyleSheet(btn_wizard_primary_qss())
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._reset_btn)
        lay.addLayout(btn_row)

        self._pw_edit.textChanged.connect(self._update_strength)
        self._cancel_btn.clicked.connect(self.reject)
        self._reset_btn.clicked.connect(self._reset)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:#777777; background:transparent;")
        return l

    def _update_strength(self, text: str) -> None:
        score, label = _pw_strength(text)
        self._strength_bar.setValue(score)
        color = _STRENGTH_COLORS.get(score, "#ff4466")
        self._strength_bar.setStyleSheet(
            "QProgressBar { background:#1a1e30; border:none; border-radius:2px; }"
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}")
        self._strength_lbl.setText(label)
        self._strength_lbl.setStyleSheet(
            f"font-size:{FONT.get('caption', 8)}pt; color:{color}; background:transparent;")

    def _reset(self) -> None:
        pw  = self._pw_edit.text()
        pw2 = self._pw2_edit.text()

        if len(pw) < 8:
            self._err_lbl.setText("Password must be at least 8 characters.")
            return
        if pw != pw2:
            self._err_lbl.setText("Passwords do not match.")
            return

        try:
            from auth.authenticator import Authenticator
            pw_hash = Authenticator.hash_password(pw)
        except ImportError as exc:
            self._err_lbl.setText(str(exc))
            return

        try:
            self._store.update_password(self._user.uid, pw_hash)
            self._auditor.log(
                "password_reset",
                actor  = self._user.username,
                uid    = self._user.uid,
                role   = self._user.user_type.value,
                detail = f"by={self._acting_uid}",
            )
            self.accept()
        except Exception as exc:
            self._err_lbl.setText(f"Error: {exc}")


# ── UserManagementWidget ───────────────────────────────────────────────────────

class UserManagementWidget(QWidget):
    """
    Admin-only user CRUD panel embedded in SettingsTab.

    Parameters
    ----------
    store   : UserStore
    auditor : AuditLogger
    auth    : Authenticator
    parent  : QWidget, optional

    Call refresh(auth_session) whenever the session changes or after any
    CRUD operation to reload the table.
    """

    def __init__(self, store, auditor, auth, parent=None):
        super().__init__(parent)
        self._store   = store
        self._auditor = auditor
        self._auth    = auth
        self._session = None   # current AuthSession

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ── Section header ─────────────────────────────────────────────────
        hdr = QLabel("User Accounts")
        hdr.setStyleSheet(
            f"font-size:{FONT.get('h3', 13)}pt; font-weight:700; "
            f"color:{PALETTE.get('text', '#ebebeb')}; background:transparent;")
        root.addWidget(hdr)

        sub = QLabel("Manage who can access SanjINSIGHT and their permissions.")
        sub.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            f"color:{PALETTE.get('textDim', '#999999')}; background:transparent;")
        root.addWidget(sub)

        # ── Toolbar ────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._add_btn    = self._toolbar_btn("+ Add User",      primary=True)
        self._edit_btn   = self._toolbar_btn("Edit",            primary=False)
        self._deact_btn  = self._toolbar_btn("Deactivate",      primary=False, danger=True)
        self._reset_btn  = self._toolbar_btn("Reset Password",  primary=False)

        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._edit_btn)
        toolbar.addWidget(self._reset_btn)
        toolbar.addWidget(self._deact_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # ── Table ──────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Display Name", "Username", "Type", "Admin", "Last Login", "Active"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._apply_table_style()
        root.addWidget(self._table, 1)

        # ── Wire signals ───────────────────────────────────────────────────
        self._add_btn.clicked.connect(self._add_user)
        self._edit_btn.clicked.connect(self._edit_user)
        self._deact_btn.clicked.connect(self._deactivate_user)
        self._reset_btn.clicked.connect(self._reset_password)
        self._table.itemSelectionChanged.connect(self._on_selection)

        self._update_toolbar_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self, auth_session=None) -> None:
        """
        Reload the table from UserStore.

        Pass the current AuthSession so the widget knows who the actor is
        and can hide itself when the user is not an admin.
        """
        self._session = auth_session
        is_admin = (
            auth_session is not None and auth_session.is_admin
        ) if auth_session else True   # show when no auth (dev mode)
        self.setVisible(is_admin)

        if not is_admin:
            return

        try:
            users = self._store.list_users(include_inactive=True)
        except Exception as exc:
            log.warning("UserManagementWidget.refresh: %s", exc)
            return

        self._table.setRowCount(0)
        for user in users:
            row = self._table.rowCount()
            self._table.insertRow(row)

            items = [
                QTableWidgetItem(user.display_name),
                QTableWidgetItem(user.username),
                QTableWidgetItem(user.user_type.display_name),
                QTableWidgetItem("Yes" if user.is_admin   else ""),
                QTableWidgetItem(user.last_login[:10] if user.last_login else "Never"),
                QTableWidgetItem("Active" if user.is_active else "Inactive"),
            ]
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, user)
                if col in (3, 5):   # Admin, Active — centre-align
                    item.setTextAlignment(Qt.AlignCenter)
                if not user.is_active:
                    item.setForeground(
                        QColor(PALETTE.get("textSub", "#6a6a6a")))
                self._table.setItem(row, col, item)

        self._update_toolbar_state()

    def _apply_styles(self) -> None:
        """Re-apply theme when app theme changes."""
        self._apply_table_style()

    # ── Private helpers ────────────────────────────────────────────────────────

    def _toolbar_btn(
        self, label: str, primary: bool, danger: bool = False
    ) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(30)
        if primary:
            btn.setStyleSheet(btn_primary_qss())
        elif danger:
            btn.setStyleSheet(btn_danger_qss())
        else:
            btn.setStyleSheet(btn_secondary_qss())
        return btn

    def _apply_table_style(self) -> None:
        P = PALETTE
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background:{P.get('surface','#2d2d2d')};
                alternate-background-color:{P.get('surface2','#333333')};
                color:{P.get('text','#ebebeb')};
                border:1px solid {P.get('border','#484848')};
                border-radius:4px;
                gridline-color:transparent;
                font-size:{FONT.get('body', 11)}pt;
            }}
            QHeaderView::section {{
                background:{P.get('surface2','#333333')};
                color:{P.get('textDim','#999999')};
                border:none; border-bottom:1px solid {P.get('border','#484848')};
                padding:5px 8px;
                font-size:{FONT.get('label', 10)}pt; font-weight:600;
            }}
            QTableWidget::item:selected {{
                background:{P.get('accentDim','#00d4aa2e')};
                color:{P.get('text','#ebebeb')};
            }}
        """)

    def _selected_user(self):
        """Return the User stored in the selected row, or None."""
        rows = self._table.selectedItems()
        if not rows:
            return None
        return rows[0].data(Qt.UserRole)

    def _acting_uid(self) -> str:
        if self._session:
            return self._session.user.uid
        return ""

    def _on_selection(self) -> None:
        self._update_toolbar_state()

    def _update_toolbar_state(self) -> None:
        user = self._selected_user()
        has_sel = user is not None
        self._edit_btn.setEnabled(has_sel)
        self._reset_btn.setEnabled(has_sel)
        self._deact_btn.setEnabled(has_sel and user.is_active)

    # ── CRUD actions ───────────────────────────────────────────────────────────

    def _add_user(self) -> None:
        dlg = _AddUserDialog(
            store        = self._store,
            auditor      = self._auditor,
            creating_uid = self._acting_uid(),
            parent       = self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.refresh(self._session)

    def _edit_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        dlg = _EditUserDialog(
            user       = user,
            store      = self._store,
            auditor    = self._auditor,
            acting_uid = self._acting_uid(),
            parent     = self,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.refresh(self._session)

    def _deactivate_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return

        # Guard: prevent self-deactivation
        if self._session and user.uid == self._session.user.uid:
            QMessageBox.warning(
                self, "Cannot Deactivate",
                "You cannot deactivate your own account while logged in.")
            return

        reply = QMessageBox.question(
            self,
            "Deactivate Account",
            f"Deactivate {user.display_name} ({user.username})?\n\n"
            "The account will be disabled immediately. "
            "This does not delete any data and can be reversed later.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._store.set_active(user.uid, False)
            self._auditor.log(
                "user_deactivated",
                actor  = user.username,
                uid    = user.uid,
                role   = user.user_type.value,
                detail = f"by={self._acting_uid()}",
            )
            self.refresh(self._session)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _reset_password(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        dlg = _ResetPasswordDialog(
            user       = user,
            store      = self._store,
            auditor    = self._auditor,
            acting_uid = self._acting_uid(),
            parent     = self,
        )
        dlg.exec_()
