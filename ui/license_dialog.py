"""
ui/license_dialog.py — License activation dialog for SanjINSIGHT.

Opened via Help → License…

Shows the current license status and allows the user to activate or
remove a license key.  All cryptographic validation is handled by the
licensing package — this file is pure UI.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtGui     import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QTextEdit, QSizePolicy, QApplication,
)

from version import APP_NAME, APP_VENDOR, SUPPORT_EMAIL
from ui.icons import IC, make_icon_label
from ui.theme import FONT, scaled_qss

log = logging.getLogger(__name__)

# ── Style constants (shared with update_dialog.py) ───────────────────────────
_BG        = "#0e1120"
_BG2       = "#13172a"
_BORDER    = "#1e2337"
_TEXT      = "#c0c8e0"
_MUTED     = "#8892a4"
_ACCENT    = "#4e73df"
_GREEN     = "#00d4aa"
_AMBER     = "#f5a623"
_RED       = "#ff4444"

_BTN_PRIMARY = f"""
    QPushButton {{
        background:{_ACCENT}; color:#fff; border:none;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:#3a5fc8; }}
    QPushButton:pressed {{ background:#2e4fa8; }}
    QPushButton:disabled {{ background:#2a3050; color:#555; }}
"""
_BTN_SECONDARY = f"""
    QPushButton {{
        background:{_BG2}; color:{_MUTED}; border:1px solid {_BORDER};
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt;
    }}
    QPushButton:hover   {{ background:#1e2540; color:{_TEXT}; }}
    QPushButton:pressed {{ background:#1a1f33; }}
"""
_BTN_RED = f"""
    QPushButton {{
        background:{_RED}22; color:{_RED}; border:1px solid {_RED}55;
        border-radius:6px; padding:8px 22px; font-size:{FONT["body"]}pt; font-weight:600;
    }}
    QPushButton:hover   {{ background:{_RED}44; }}
    QPushButton:pressed {{ background:{_RED}66; }}
"""


class LicenseDialog(QDialog):
    """
    License activation / status dialog.

    Emits license_changed() when the user activates or removes a key so
    the main application can reload the license and update the UI.
    """

    license_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — License")
        self.setModal(True)
        self.resize(600, 520)
        self.setStyleSheet(
            f"QDialog {{ background:{_BG}; }} "
            f"QLabel  {{ background:transparent; }}"
        )

        self._build_ui()
        self._refresh_status()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_status_card(), 0)
        root.addWidget(self._build_activate_section(), 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setFixedHeight(72)
        hdr.setStyleSheet(f"background:{_BG2}; border-bottom:1px solid {_BORDER};")
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(12)

        icon = make_icon_label(IC.KEY, color="#ffffff", size=28)
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        t1 = QLabel(f"{APP_VENDOR} {APP_NAME} — License")
        t1.setStyleSheet(scaled_qss(f"font-size:15pt; font-weight:700; color:#fff;"))
        t2 = QLabel("Manage your software license key")
        t2.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        col.addWidget(t1)
        col.addWidget(t2)
        lay.addLayout(col, 1)
        return hdr

    def _build_status_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(f"background:{_BG};")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 20, 28, 8)
        lay.setSpacing(6)

        title = QLabel("Current License")
        title.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; font-weight:700; color:{_MUTED}; letter-spacing:1px;")
        lay.addWidget(title)

        # Status grid
        self._status_widget = QWidget()
        self._status_widget.setStyleSheet(
            f"background:{_BG2}; border:1px solid {_BORDER}; border-radius:6px;")
        grid_lay = QVBoxLayout(self._status_widget)
        grid_lay.setContentsMargins(20, 14, 20, 14)
        grid_lay.setSpacing(8)

        def _row(label: str) -> QLabel:
            row = QWidget()
            row.setStyleSheet("background:transparent; border:none;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED}; min-width:90px;")
            lbl.setFixedWidth(110)
            val = QLabel("—")
            val.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_TEXT};")
            rl.addWidget(lbl)
            rl.addWidget(val, 1)
            grid_lay.addWidget(row)
            return val

        self._lbl_status   = _row("Status")
        self._lbl_tier     = _row("Tier")
        self._lbl_customer = _row("Licensed to")
        self._lbl_email    = _row("Email")
        self._lbl_seats    = _row("Seats")
        self._lbl_expiry   = _row("Expires")

        lay.addWidget(self._status_widget)

        # Remove button (shown only when a license is active)
        self._remove_btn = QPushButton("Remove License Key")
        self._remove_btn.setStyleSheet(_BTN_RED)
        self._remove_btn.setFixedHeight(34)
        self._remove_btn.clicked.connect(self._on_remove)
        self._remove_btn.hide()
        lay.addWidget(self._remove_btn, 0, Qt.AlignRight)

        return card

    def _build_activate_section(self) -> QWidget:
        sect = QWidget()
        sect.setStyleSheet(f"background:{_BG};")
        lay = QVBoxLayout(sect)
        lay.setContentsMargins(28, 8, 28, 8)
        lay.setSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER};")
        lay.addWidget(sep)

        title = QLabel("Activate License")
        title.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; font-weight:700; color:{_MUTED}; letter-spacing:1px;")
        lay.addWidget(title)

        hint = QLabel(
            "Paste your license key below. "
            f"To purchase a license, contact {SUPPORT_EMAIL}."
        )
        hint.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._key_input = QTextEdit()
        self._key_input.setPlaceholderText(
            "Paste license key here…\n\n"
            "Example:  eyJjdXN0b21lciI6Ii4uLiJ9.AAAA…"
        )
        self._key_input.setStyleSheet(f"""
            QTextEdit {{
                background:{_BG2}; color:{_TEXT};
                border:1px solid {_BORDER}; border-radius:4px;
                font-size:{FONT["caption"]}pt; font-family:Menlo,Consolas,monospace;
                padding:8px;
            }}
            QTextEdit:focus {{ border-color:{_ACCENT}; }}
        """)
        self._key_input.setMaximumHeight(100)
        self._key_input.textChanged.connect(self._on_key_input_changed)
        lay.addWidget(self._key_input, 1)

        # Status message label (shown after activation attempt)
        self._msg_label = QLabel("")
        self._msg_label.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED};")
        self._msg_label.setWordWrap(True)
        self._msg_label.hide()
        lay.addWidget(self._msg_label)

        self._activate_btn = QPushButton("Activate License")
        self._activate_btn.setStyleSheet(_BTN_PRIMARY)
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate)
        lay.addWidget(self._activate_btn, 0, Qt.AlignRight)

        return sect

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(52)
        footer.setStyleSheet(f"background:{_BG2}; border-top:1px solid {_BORDER};")
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(28, 0, 28, 0)

        contact = QLabel(f"Questions? Contact {SUPPORT_EMAIL}")
        contact.setStyleSheet(f"font-size:{FONT['caption']}pt; color:{_MUTED};")
        lay.addWidget(contact, 1)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:6px 18px"))
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

        return footer

    # ── Refresh / update ──────────────────────────────────────────────────────

    def _refresh_status(self):
        """Re-read the current license from preferences and update the display."""
        import config as _cfg
        from licensing.license_validator import load_license
        from licensing.license_model import LicenseTier

        info = load_license(_cfg)

        if info.tier == LicenseTier.UNLICENSED:
            self._lbl_status.setText("⚠ Unlicensed — demo mode only")
            self._lbl_status.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_AMBER}; font-weight:600;")
            self._lbl_tier.setText("—")
            self._lbl_customer.setText("—")
            self._lbl_email.setText("—")
            self._lbl_seats.setText("—")
            self._lbl_expiry.setText("—")
            self._remove_btn.hide()
        else:
            # Active license
            if info.days_until_expiry is not None and info.days_until_expiry <= 30:
                status_color = _AMBER
                status_text  = f"⚠ Active — expiring soon"
            else:
                status_color = _GREEN
                status_text  = "✓ Active"

            self._lbl_status.setText(status_text)
            self._lbl_status.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{status_color}; font-weight:600;")
            self._lbl_tier.setText(info.tier_display)
            self._lbl_customer.setText(info.customer or "—")
            self._lbl_email.setText(info.email or "—")
            self._lbl_seats.setText(
                str(info.seats) if info.tier.value == "site" else "1 (single-seat)")
            self._lbl_expiry.setText(info.expiry_display)
            self._remove_btn.show()

    def _set_message(self, text: str, color: str = _MUTED):
        self._msg_label.setText(text)
        self._msg_label.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{color};")
        self._msg_label.show()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_key_input_changed(self):
        text = self._key_input.toPlainText().strip()
        self._activate_btn.setEnabled(bool(text))
        self._msg_label.hide()

    def _on_activate(self):
        key_string = self._key_input.toPlainText().strip()
        if not key_string:
            return

        import config as _cfg
        from licensing.license_validator import save_license_key

        info = save_license_key(_cfg, key_string)
        if info is None:
            self._set_message(
                "Invalid license key. Check the key and try again, "
                f"or contact {SUPPORT_EMAIL}.",
                _RED,
            )
        else:
            self._key_input.clear()
            self._set_message(
                f"✓ License activated for {info.customer}  ({info.tier_display})",
                _GREEN,
            )
            self._refresh_status()
            self.license_changed.emit()

    def _on_remove(self):
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Remove License Key",
            "Are you sure you want to remove the license key?\n\n"
            "The software will revert to demo mode (simulated hardware only) "
            "until a new license is activated.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply == QMessageBox.Yes:
            import config as _cfg
            from licensing.license_validator import remove_license
            remove_license(_cfg)
            self._refresh_status()
            self.license_changed.emit()
