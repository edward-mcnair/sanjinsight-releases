"""
ui/auth/supervisor_override_dialog.py

SupervisorOverrideDialog — compact overlay that lets an engineer temporarily
grant elevated access at an operator (Technician) station.

Layout  (340 × 280 px)
-----------------------
  Title: "Supervisor Override"
  Subtitle: "An engineer must authenticate to continue."
  Username field
  Password field
  Error label
  [Cancel]  [Authenticate]

Signals
-------
  override_granted(User)   — emitted on success with the engineer's User object

Usage
-----
  dlg = SupervisorOverrideDialog(auth=_auth, parent=operator_shell)
  dlg.override_granted.connect(_on_override_granted)
  dlg.exec_()

The dialog calls Authenticator.supervisor_override() internally; the audit
log entry is written by the Authenticator.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame,
)

from ui.theme import (
    btn_wizard_primary_qss, btn_wizard_secondary_qss, wizard_input_qss,
    FONT, PALETTE,
)

log = logging.getLogger(__name__)

_BG     = "#0f1120"
_BORDER = "#2a3249"
_DIM    = "#777777"


class SupervisorOverrideDialog(QDialog):
    """
    Modal dialog for temporary engineer access at an operator station.

    Parameters
    ----------
    auth :  Authenticator
        The central auth facade.
    parent : QWidget, optional
    """

    override_granted = pyqtSignal(object)   # User (the overriding engineer)

    def __init__(self, auth, parent=None):
        super().__init__(parent)
        self._auth = auth

        self.setWindowTitle("Supervisor Override")
        self.setFixedSize(360, 310)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)

        # ── Header ─────────────────────────────────────────────────────────
        title = QLabel("Supervisor Override")
        title.setStyleSheet(
            "font-size:16pt; font-weight:700; color:#ffffff; "
            "background:transparent;")
        lay.addWidget(title)

        subtitle = QLabel(
            "An engineer or administrator must authenticate "
            "to grant temporary access at this station.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:{_DIM}; "
            "background:transparent;")
        lay.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER};")
        lay.addWidget(sep)

        input_ss = wizard_input_qss()

        # ── Username ───────────────────────────────────────────────────────
        user_lbl = QLabel("Engineer username")
        user_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:{_DIM}; "
            "background:transparent;")
        lay.addWidget(user_lbl)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Username")
        self._user_edit.setFixedHeight(34)
        self._user_edit.setStyleSheet(input_ss)
        lay.addWidget(self._user_edit)

        # ── Password ───────────────────────────────────────────────────────
        pw_lbl = QLabel("Password")
        pw_lbl.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; color:{_DIM}; "
            "background:transparent;")
        lay.addWidget(pw_lbl)

        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Password")
        self._pw_edit.setFixedHeight(34)
        self._pw_edit.setStyleSheet(input_ss)
        lay.addWidget(self._pw_edit)

        # ── Error label ────────────────────────────────────────────────────
        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet(
            f"color:{PALETTE.get('danger', '#ff4466')}; "
            f"font-size:{FONT.get('sublabel', 9)}pt; "
            "background:transparent;")
        lay.addWidget(self._err_lbl)

        lay.addStretch(1)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setStyleSheet(btn_wizard_secondary_qss())

        self._auth_btn = QPushButton("Authenticate")
        self._auth_btn.setFixedHeight(36)
        self._auth_btn.setStyleSheet(btn_wizard_primary_qss())

        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._auth_btn)
        lay.addLayout(btn_row)

        # ── Wire signals ───────────────────────────────────────────────────
        self._cancel_btn.clicked.connect(self.reject)
        self._auth_btn.clicked.connect(self._do_authenticate)
        self._pw_edit.returnPressed.connect(self._do_authenticate)
        self._user_edit.returnPressed.connect(self._pw_edit.setFocus)

    # ── Authentication ─────────────────────────────────────────────────────────

    def _do_authenticate(self) -> None:
        username = self._user_edit.text().strip()
        password = self._pw_edit.text()

        if not username or not password:
            self._err_lbl.setText("Please enter username and password.")
            return

        self._set_busy(True)

        def _on_result(granted: bool) -> None:
            self._set_busy(False)
            if granted:
                # Retrieve the override engineer from the live session
                session = self._auth.current_session()
                engineer = (
                    session._override_user
                    if session and session.supervisor_override_active
                    else None
                )
                log.info("SupervisorOverrideDialog: override granted by '%s'",
                         username)
                self.override_granted.emit(engineer)
                self.accept()
            else:
                self._err_lbl.setText(
                    "Authentication failed. "
                    "Only engineers or administrators can override.")

        self._auth.supervisor_override(username, password, _on_result)

    def _set_busy(self, busy: bool) -> None:
        self._auth_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(not busy)
        self._user_edit.setEnabled(not busy)
        self._pw_edit.setEnabled(not busy)
        self._auth_btn.setText("Verifying…" if busy else "Authenticate")
