"""
ui/settings_tab.py

Settings Tab
============
Provides user-configurable preferences for SanjINSIGHT.

Sections
--------
  • Software Updates   — auto-check on/off, frequency, channel, manual Check Now
  • Appearance         — (placeholder for future UI prefs)
  • Support            — About dialog shortcut, copy version info

This tab is added to the TOOLS section of the sidebar.
"""

from __future__ import annotations

import logging
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal, QUrl
from PyQt5.QtGui     import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QFrame, QSizePolicy,
    QScrollArea, QLineEdit,
    QSpinBox,
)

import config as cfg_mod
from version import (
    __version__, BUILD_DATE, APP_NAME, APP_VENDOR,
    RELEASES_PAGE_URL, SUPPORT_EMAIL, version_string,
)
from ui.theme import FONT, PALETTE, MONO_FONT, scaled_qss
from ui.settings.ai_section import AISettingsMixin
from ui.settings._helpers import (
    _BG, _BG2, _BORDER, _TEXT, _MUTED, _ACCENT, _ACCENT_H,
    _GREEN, _AMBER, _DANGER,
    BTN_PRIMARY  as _BTN_PRIMARY,
    BTN_SECONDARY as _BTN_SECONDARY,
    COMBO         as _COMBO,
    CHECK         as _CHECK,
    h2    as _h2,
    body  as _body,
    sep   as _sep,
    group as _group,
)

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  SettingsTab
# ══════════════════════════════════════════════════════════════════════════════

class SettingsTab(AISettingsMixin, QWidget):
    """
    Settings tab content.  Added to the TOOLS nav section.

    Signals
    -------
    check_for_updates_requested       — emitted when user clicks "Check Now"
    ai_enable_requested(str, int)     — (model_path, n_gpu_layers) when user enables AI
    ai_disable_requested              — emitted when user disables AI
    download_model_requested(str,str) — (url, dest_path) to start a model download
    download_cancel_requested         — emitted when user cancels a download
    """

    check_for_updates_requested   = pyqtSignal()
    theme_changed                 = pyqtSignal(str)   # emits "auto", "dark", or "light"
    colors_changed                = pyqtSignal(str)   # emits "standard" or "accessible"
    # workspace_changed removed — modes deprecated (recipe-mode branch)
    ai_enable_requested           = pyqtSignal(str, int)
    ai_disable_requested          = pyqtSignal()
    download_model_requested      = pyqtSignal(str, str)
    download_cancel_requested     = pyqtSignal()
    cloud_ai_connect_requested    = pyqtSignal(str, str, str)  # provider, api_key, model_id
    cloud_ai_disconnect_requested = pyqtSignal()
    ollama_connect_requested      = pyqtSignal(str)   # model_id
    ollama_disconnect_requested   = pyqtSignal()

    # Hardware setup profiles
    profile_save_requested        = pyqtSignal(str)   # profile name
    profile_load_requested        = pyqtSignal(str)   # profile name
    profile_delete_requested      = pyqtSignal(str)   # profile name

    def __init__(self, parent=None, auth=None, auth_session=None):
        super().__init__(parent)
        self._auth         = auth
        self._auth_session = auth_session
        self.setStyleSheet(f"background:{_BG()};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Search bar + status label (above the scroll area) ─────────
        self._search_bar_widget = QWidget()
        search_bar_widget = self._search_bar_widget
        search_bar_widget.setStyleSheet(f"background:{_BG()};")
        search_bar_lay = QVBoxLayout(search_bar_widget)
        search_bar_lay.setContentsMargins(30, 12, 30, 4)
        search_bar_lay.setSpacing(2)

        self._settings_search = QLineEdit()
        self._settings_search.setPlaceholderText("Filter settings\u2026")
        self._settings_search.setStyleSheet(f"""
            QLineEdit {{
                background: {_BG2()};
                border: 1px solid {_BORDER()};
                border-radius: 4px;
                color: {_TEXT()};
                padding: 4px 8px;
                font-size: {FONT["label"]}pt;
            }}
            QLineEdit:focus {{
                border-color: {_ACCENT()};
            }}
        """)
        self._settings_search.setFixedHeight(32)
        self._settings_search.textChanged.connect(self._filter_settings)
        search_bar_lay.addWidget(self._settings_search)

        self._settings_filter_status = QLabel("")
        self._settings_filter_status.setStyleSheet(f"font-size: {FONT['caption']}pt; color: {_MUTED()};")
        search_bar_lay.addWidget(self._settings_filter_status)

        outer.addWidget(search_bar_widget)

        # ── Outer scroll area so content works on small screens ───────
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        outer.addWidget(scroll)

        self._settings_content = QWidget()
        content = self._settings_content
        content.setStyleSheet(f"background:{_BG()};")
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(30, 24, 30, 30)
        lay.setSpacing(20)

        # ── Page title ────────────────────────────────────────────────
        self._pg_title = QLabel("Settings")
        pg_title = self._pg_title
        pg_title.setStyleSheet(scaled_qss(f"font-size:{FONT['titleLg']}pt; font-weight:700; color:{_TEXT()};"))
        lay.addWidget(pg_title)

        lay.addWidget(_sep())

        # ── Software version card ─────────────────────────────────────
        self._version_card = self._build_version_card()
        lay.addWidget(self._version_card)

        # ── Appearance ────────────────────────────────────────────────
        lay.addWidget(self._build_appearance_group())

        # ── Hardware Profiles ─────────────────────────────────────────
        lay.addWidget(self._build_hardware_profiles_group())

        # ── Lab / Operator ────────────────────────────────────────────
        lay.addWidget(self._build_lab_group())

        # ── Security + User Management (admin only — hidden until login) ─
        self._security_group = self._build_security_group()
        self._security_group.setVisible(False)
        lay.addWidget(self._security_group)

        self._users_group = self._build_users_group()
        self._users_group.setVisible(False)
        lay.addWidget(self._users_group)

        # Show immediately if already logged in as admin at construction time
        _is_admin_now = getattr(getattr(auth_session, "user", None), "is_admin", False)
        if _is_admin_now:
            self._security_group.setVisible(True)
            self._users_group.setVisible(True)

        # ── Software updates ──────────────────────────────────────────
        lay.addWidget(self._build_updates_group())

        # Apply initial admin gate (both lab and updates widgets now exist)
        self._apply_admin_gate(_is_admin_now)

        # ── AI Assistant (local) ──────────────────────────────────────
        lay.addWidget(self._build_ai_group())

        # ── Alternative AI Sources (collapsible) ──────────────────────
        lay.addWidget(self._build_alt_ai_container())

        # ── License ───────────────────────────────────────────────────
        lay.addWidget(self._build_license_group())

        # ── Plugins ──────────────────────────────────────────────────
        self._plugins_group = self._build_plugins_group()
        lay.addWidget(self._plugins_group)

        # ── Diagnostics ───────────────────────────────────────────────
        lay.addWidget(self._build_diagnostics_group())

        # ── Support ───────────────────────────────────────────────────
        lay.addWidget(self._build_support_group())

        lay.addStretch(1)

        # ── Collect all top-level QGroupBox sections for filtering ─────
        self._setting_groups: list[QGroupBox] = content.findChildren(
            QGroupBox, options=Qt.FindDirectChildrenOnly
        )
        # Update the status label with the total count
        self._settings_filter_status.setText(
            f"Showing {len(self._setting_groups)} of {len(self._setting_groups)} sections"
        )

    # ── Section builders ──────────────────────────────────────────────

    def _build_appearance_group(self) -> QGroupBox:
        grp = _group("Appearance")
        lay = QVBoxLayout(grp)
        lay.setSpacing(14)

        from ui.widgets.segmented_control import SegmentedControl

        row = QHBoxLayout()
        theme_lbl = QLabel("Theme")
        theme_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; color:{PALETTE['text']};")
        row.addWidget(theme_lbl)
        row.addStretch()

        self._theme_seg = SegmentedControl(["Auto", "Dark", "Light"])
        current_pref = cfg_mod.get_pref("ui.theme", "auto")
        self._theme_seg.set_index(
            {"auto": 0, "dark": 1, "light": 2}.get(current_pref, 0))
        self._theme_seg.selection_changed.connect(
            lambda i: self.theme_changed.emit(
                ("auto", "dark", "light")[i]))
        row.addWidget(self._theme_seg)
        lay.addLayout(row)

        # ── Colors palette selector (Standard / Accessible) ─────────
        colors_row = QHBoxLayout()
        colors_lbl = QLabel("Colors")
        colors_lbl.setStyleSheet(
            f"font-size:{FONT['body']}pt; color:{PALETTE['text']};")
        colors_row.addWidget(colors_lbl)
        colors_row.addStretch()

        self._colors_seg = SegmentedControl(
            ["Standard", "Accessible"], seg_width=90)
        current_colors = cfg_mod.get_pref("ui.colors", "standard")
        self._colors_seg.set_index(0 if current_colors == "standard" else 1)
        self._colors_seg.selection_changed.connect(self._on_colors_btn)
        colors_row.addWidget(self._colors_seg)
        lay.addLayout(colors_row)

        # Description for the colors selector
        self._colors_desc_lbl = QLabel(
            "Accessible: optimized for color vision differences"
            if current_colors == "accessible"
            else "")
        self._colors_desc_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            "font-style: italic;")
        self._colors_desc_lbl.setWordWrap(True)
        colors_desc_row = QHBoxLayout()
        colors_desc_row.addStretch()
        colors_desc_row.addWidget(self._colors_desc_lbl)
        lay.addLayout(colors_desc_row)

        return grp

    def _on_colors_btn(self, idx: int) -> None:
        mode = "standard" if idx == 0 else "accessible"
        self._colors_desc_lbl.setText(
            "Accessible: optimized for color vision differences"
            if mode == "accessible" else "")
        self.colors_changed.emit(mode)

    def _on_workspace_btn(self, idx: int) -> None:
        """No-op — workspace modes are deprecated (recipe-mode branch)."""
        pass

    # ── Hardware Profiles section ────────────────────────────────────────

    def _build_hardware_profiles_group(self) -> QGroupBox:
        """Hardware Setup Profiles: save/load/delete named profiles, auto-restore toggle."""
        grp = _group("Hardware Profiles")
        lay = QVBoxLayout(grp)
        lay.setSpacing(10)

        lay.addWidget(_h2("Setup Profiles"))
        lay.addWidget(_body(
            "Save and restore complete hardware configurations. "
            "Camera settings are applied automatically; TEC, FPGA, and Bias "
            "settings are loaded as pending values — use each tab's "
            "Apply / Set button to activate."))

        # Auto-restore toggle
        self._profile_auto_restore_cb = QCheckBox(
            "Restore last-used settings on startup")
        self._profile_auto_restore_cb.setStyleSheet(_CHECK())
        self._profile_auto_restore_cb.setChecked(
            cfg_mod.get_pref("hardware.auto_restore_profile", True))
        self._profile_auto_restore_cb.toggled.connect(
            lambda v: cfg_mod.set_pref("hardware.auto_restore_profile", v))
        lay.addWidget(self._profile_auto_restore_cb)

        lay.addWidget(_sep())

        # Profile selector row
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)

        sel_lbl = QLabel("Profile:")
        sel_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        sel_row.addWidget(sel_lbl)

        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        self._profile_combo.setStyleSheet(_COMBO())
        self._profile_combo.setFixedHeight(30)
        sel_row.addWidget(self._profile_combo, 1)

        lay.addLayout(sel_row)

        # Action buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._profile_load_btn = QPushButton("Load")
        self._profile_load_btn.setStyleSheet(_BTN_PRIMARY())
        self._profile_load_btn.setFixedHeight(32)
        self._profile_load_btn.setToolTip(
            "Load the selected profile into hardware tabs")
        self._profile_load_btn.clicked.connect(self._on_profile_load)
        btn_row.addWidget(self._profile_load_btn)

        self._profile_save_btn = QPushButton("Save Current…")
        self._profile_save_btn.setStyleSheet(_BTN_SECONDARY())
        self._profile_save_btn.setFixedHeight(32)
        self._profile_save_btn.setToolTip(
            "Save the current hardware settings as a named profile")
        self._profile_save_btn.clicked.connect(self._on_profile_save)
        btn_row.addWidget(self._profile_save_btn)

        self._profile_delete_btn = QPushButton("Delete")
        self._profile_delete_btn.setStyleSheet(_BTN_SECONDARY())
        self._profile_delete_btn.setFixedHeight(32)
        self._profile_delete_btn.setToolTip("Delete the selected profile")
        self._profile_delete_btn.clicked.connect(self._on_profile_delete)
        btn_row.addWidget(self._profile_delete_btn)

        lay.addLayout(btn_row)

        # Status label — shows last restore summary
        self._profile_status_lbl = QLabel("")
        self._profile_status_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._profile_status_lbl.setWordWrap(True)
        lay.addWidget(self._profile_status_lbl)

        return grp

    def refresh_profile_list(self, names: list):
        """Update the profile combo with current profile names."""
        combo = self._profile_combo
        combo.blockSignals(True)
        current = combo.currentText()
        combo.clear()
        for n in names:
            combo.addItem(n)
        # Restore previous selection if still present
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._profile_delete_btn.setEnabled(combo.count() > 0)
        self._profile_load_btn.setEnabled(combo.count() > 0)

    def set_profile_status(self, text: str):
        """Update the profile status label (e.g. after restore)."""
        self._profile_status_lbl.setText(text)

    def _on_profile_save(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Save Hardware Profile",
            "Profile name:")
        if ok and name.strip():
            self.profile_save_requested.emit(name.strip())

    def _on_profile_load(self):
        name = self._profile_combo.currentText()
        if name:
            self.profile_load_requested.emit(name)

    def _on_profile_delete(self):
        name = self._profile_combo.currentText()
        if not name:
            return
        from PyQt5.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, "Delete Profile",
            f"Delete hardware profile \"{name}\"?\n\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.profile_delete_requested.emit(name)

    def _build_lab_group(self) -> QGroupBox:
        """Lab / Operator settings: active operator, saved list, scan preferences."""
        grp = _group("Lab / Operator")
        lay = QVBoxLayout(grp)
        lay.setSpacing(14)

        # ── Active operator selector ──────────────────────────────────
        active_row = QHBoxLayout()
        active_lbl = QLabel("Active operator:")
        active_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        active_row.addWidget(active_lbl)

        self._lab_op_combo = QComboBox()
        self._lab_op_combo.setEditable(True)
        self._lab_op_combo.setInsertPolicy(QComboBox.NoInsert)
        self._lab_op_combo.setMinimumWidth(200)
        self._lab_op_combo.setMaximumWidth(300)
        self._lab_op_combo.setStyleSheet(_COMBO())
        self._lab_op_combo.lineEdit().setPlaceholderText("Type or select name…")
        self._lab_reload_op_combo()

        self._lab_op_combo.currentTextChanged.connect(self._on_lab_op_text_changed)
        active_row.addWidget(self._lab_op_combo)

        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(64)
        set_btn.setStyleSheet(_BTN_PRIMARY())
        set_btn.clicked.connect(self._on_lab_set_operator)
        active_row.addWidget(set_btn)
        active_row.addStretch()
        lay.addLayout(active_row)

        lay.addWidget(_body(
            "The active operator name is stamped onto every new session and "
            "exported with TIFF metadata so it travels with the image file."))

        lay.addWidget(_sep())

        # ── Saved operator list management ────────────────────────────
        saved_lbl = QLabel("Saved operators")
        saved_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; color:{_TEXT()};")
        lay.addWidget(saved_lbl)

        self._lab_op_list_w = QWidget()
        self._lab_op_list_lay = QVBoxLayout(self._lab_op_list_w)
        self._lab_op_list_lay.setContentsMargins(0, 0, 0, 0)
        self._lab_op_list_lay.setSpacing(4)
        self._lab_rebuild_list()
        lay.addWidget(self._lab_op_list_w)

        # Add operator inline
        add_row = QHBoxLayout()
        self._lab_new_edit = QLineEdit()
        self._lab_new_edit.setPlaceholderText("Add new operator name…")
        self._lab_new_edit.setFixedHeight(30)
        self._lab_new_edit.setStyleSheet(f"""
            QLineEdit {{
                background:{_BG2()}; color:{_TEXT()}; border:1px solid {_BORDER()};
                border-radius:4px; padding:4px 8px; font-size:{FONT["label"]}pt;
            }}
        """)
        self._lab_new_edit.returnPressed.connect(self._on_lab_add_operator)
        add_row.addWidget(self._lab_new_edit, 1)
        self._lab_add_btn = QPushButton("Add")
        self._lab_add_btn.setFixedWidth(64)
        self._lab_add_btn.setStyleSheet(_BTN_SECONDARY())
        self._lab_add_btn.clicked.connect(self._on_lab_add_operator)
        add_row.addWidget(self._lab_add_btn)
        lay.addLayout(add_row)

        lay.addWidget(_sep())

        # ── Scan behaviour preferences ────────────────────────────────
        self._lab_require_chk = QCheckBox(
            "Require operator selection before each scan")
        self._lab_require_chk.setStyleSheet(_CHECK())
        self._lab_require_chk.setChecked(
            cfg_mod.get_pref("lab.require_operator", False))
        self._lab_require_chk.toggled.connect(
            lambda v: cfg_mod.set_pref("lab.require_operator", v))
        lay.addWidget(self._lab_require_chk)

        self._lab_confirm_chk = QCheckBox(
            "Show operator confirmation banner before scanning")
        self._lab_confirm_chk.setStyleSheet(_CHECK())
        self._lab_confirm_chk.setChecked(
            cfg_mod.get_pref("lab.confirm_at_scan", False))
        self._lab_confirm_chk.toggled.connect(
            lambda v: cfg_mod.set_pref("lab.confirm_at_scan", v))
        lay.addWidget(self._lab_confirm_chk)

        lay.addWidget(_sep())

        # ── Pre-Capture Validation ────────────────────────────────────
        pf_lbl = QLabel("Pre-Capture Validation")
        pf_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; color:{_TEXT()};")
        lay.addWidget(pf_lbl)

        self._preflight_chk = QCheckBox(
            "Run pre-capture validation checks (exposure, stability, focus)")
        self._preflight_chk.setStyleSheet(_CHECK())
        self._preflight_chk.setChecked(
            cfg_mod.get_pref("acquisition.preflight_enabled", True))
        self._preflight_chk.toggled.connect(
            lambda v: cfg_mod.set_pref("acquisition.preflight_enabled", v))
        lay.addWidget(self._preflight_chk)

        pf_desc = QLabel(
            "When enabled, the system checks exposure quality, frame "
            "stability, focus, and hardware readiness before each "
            "acquisition.  You can always override warnings and proceed.")
        pf_desc.setWordWrap(True)
        pf_desc.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_MUTED()}; "
            f"padding-left:22px;")
        lay.addWidget(pf_desc)

        lay.addWidget(_sep())

        # ── Autofocus ─────────────────────────────────────────────────
        af_lbl = QLabel("Autofocus")
        af_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:700; color:{_TEXT()};")
        lay.addWidget(af_lbl)

        self._af_before_chk = QCheckBox(
            "Auto-focus before each capture (requires motorized stage)")
        self._af_before_chk.setStyleSheet(_CHECK())
        self._af_before_chk.setChecked(
            cfg_mod.get_pref("autofocus.before_capture", False))
        self._af_before_chk.toggled.connect(
            lambda v: cfg_mod.set_pref("autofocus.before_capture", v))
        lay.addWidget(self._af_before_chk)

        # Collect admin-gated widgets (Active operator selector is NOT gated)
        self._lab_admin_widgets = [
            self._lab_op_list_w,
            self._lab_new_edit,
            self._lab_add_btn,
            self._lab_require_chk,
            self._lab_confirm_chk,
        ]

        return grp

    # ── Lab helpers ────────────────────────────────────────────────────

    def _lab_reload_op_combo(self):
        """Populate the active-operator combo from saved preferences."""
        operators = list(cfg_mod.get_pref("lab.operators", []) or [])
        active    = cfg_mod.get_pref("lab.active_operator", "") or ""
        self._lab_op_combo.blockSignals(True)
        self._lab_op_combo.clear()
        self._lab_op_combo.addItems([""] + operators)
        if active:
            idx = self._lab_op_combo.findText(active)
            if idx >= 0:
                self._lab_op_combo.setCurrentIndex(idx)
            else:
                self._lab_op_combo.setCurrentText(active)
        self._lab_op_combo.blockSignals(False)

    def _lab_rebuild_list(self):
        """Rebuild the saved-operators list widget."""
        for i in reversed(range(self._lab_op_list_lay.count())):
            item = self._lab_op_list_lay.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        operators = list(cfg_mod.get_pref("lab.operators", []) or [])
        active    = cfg_mod.get_pref("lab.active_operator", "") or ""

        if not operators:
            empty = QLabel("No saved operators yet.")
            empty.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
            self._lab_op_list_lay.addWidget(empty)
            return

        for name in operators:
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(6)
            is_active = (name == active)
            dot = QLabel("●" if is_active else "○")
            dot.setStyleSheet(
                f"color:{_GREEN() if is_active else _MUTED()}; "
                f"font-size:{FONT['sublabel']}pt;")
            dot.setFixedWidth(14)
            lbl = QLabel(name)
            lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; "
                f"color:{_TEXT() if is_active else _MUTED()}; "
                f"font-weight:{'600' if is_active else 'normal'};")
            rm_btn = QPushButton("✕")
            rm_btn.setFixedSize(22, 22)
            rm_btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{_MUTED()}; border:none; "
                f"font-size:{FONT['label']}pt; }}"
                f"QPushButton:hover {{ color:{PALETTE['danger']}; }}")
            rm_btn.clicked.connect(lambda _, n=name: self._on_lab_remove_operator(n))
            row_lay.addWidget(dot)
            row_lay.addWidget(lbl, 1)
            row_lay.addWidget(rm_btn)
            self._lab_op_list_lay.addWidget(row)

    def _on_lab_set_operator(self):
        """Set the current combo text as the active operator."""
        name = self._lab_op_combo.currentText().strip()
        cfg_mod.set_pref("lab.active_operator", name)
        if name:
            operators = list(cfg_mod.get_pref("lab.operators", []) or [])
            if name not in operators:
                operators.append(name)
                cfg_mod.set_pref("lab.operators", operators)
        self._lab_reload_op_combo()
        self._lab_rebuild_list()

    def _on_lab_op_text_changed(self, text: str):
        """Live-update active operator as user types in editable combo."""
        # Only auto-set if it matches a saved name (avoid saving partial input)
        operators = list(cfg_mod.get_pref("lab.operators", []) or [])
        if text in operators or text == "":
            cfg_mod.set_pref("lab.active_operator", text)

    def _on_lab_add_operator(self):
        name = self._lab_new_edit.text().strip()
        if not name:
            return
        operators = list(cfg_mod.get_pref("lab.operators", []) or [])
        if name not in operators:
            operators.append(name)
            cfg_mod.set_pref("lab.operators", operators)
        cfg_mod.set_pref("lab.active_operator", name)
        self._lab_new_edit.clear()
        self._lab_reload_op_combo()
        self._lab_rebuild_list()

    def _on_lab_remove_operator(self, name: str):
        operators = list(cfg_mod.get_pref("lab.operators", []) or [])
        if name in operators:
            operators.remove(name)
            cfg_mod.set_pref("lab.operators", operators)
        active = cfg_mod.get_pref("lab.active_operator", "") or ""
        if active == name:
            cfg_mod.set_pref("lab.active_operator", "")
        self._lab_reload_op_combo()
        self._lab_rebuild_list()

    def _apply_styles(self) -> None:
        """Called by MainWindow._swap_visual_theme() after a theme switch."""
        # Top-level background
        self.setStyleSheet(f"background:{_BG()};")

        # Content + search bar backgrounds (stored in __init__)
        if hasattr(self, "_settings_content"):
            self._settings_content.setStyleSheet(f"background:{_BG()};")
        if hasattr(self, "_search_bar_widget"):
            self._search_bar_widget.setStyleSheet(f"background:{_BG()};")

        # Page title
        if hasattr(self, "_pg_title"):
            self._pg_title.setStyleSheet(
                scaled_qss(f"font-size:{FONT['titleLg']}pt; font-weight:700; color:{_TEXT()};"))

        # Version card
        if hasattr(self, "_version_card"):
            self._version_card.setStyleSheet(
                f"background:{_BG2()}; border:1px solid {_BORDER()}; border-radius:6px;")
        if hasattr(self, "_version_name_lbl"):
            self._version_name_lbl.setStyleSheet(
                scaled_qss(f"font-size:{FONT['heading']}pt; font-weight:700; color:{_TEXT()};"))

        # Update status label
        if hasattr(self, "_update_status_lbl"):
            self._update_status_lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")

        # All top-level QGroupBox sections
        _grp_qss = f"""
            QGroupBox {{
                color:{_TEXT()}; font-size:{FONT["sublabel"]}pt; font-weight:600;
                border:1px solid {_BORDER()}; border-radius:5px;
                margin-top:10px; padding:14px 14px 14px 14px;
            }}
            QGroupBox::title {{
                subcontrol-origin:margin; left:12px; padding:0 6px;
                background:{_BG()};
            }}
        """
        for grp in getattr(self, "_setting_groups", []):
            grp.setStyleSheet(_grp_qss)

        # Search bar
        if hasattr(self, "_settings_search"):
            self._settings_search.setStyleSheet(f"""
                QLineEdit {{
                    background: {_BG2()};
                    border: 1px solid {_BORDER()};
                    border-radius: 4px;
                    color: {_TEXT()};
                    padding: 4px 8px;
                    font-size: {FONT["label"]}pt;
                }}
                QLineEdit:focus {{
                    border-color: {_ACCENT()};
                }}
            """)
        if hasattr(self, "_settings_filter_status"):
            self._settings_filter_status.setStyleSheet(
                f"font-size: {FONT['caption']}pt; color: {_MUTED()};")

        # Segmented controls (pill-style, repaint with current palette)
        for attr in ("_theme_seg", "_colors_seg", "_ws_seg"):
            seg = getattr(self, attr, None)
            if seg is not None:
                seg._apply_styles()

        # AI persona selector buttons
        for btn in getattr(self, "_ai_persona_btns", {}).values():
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{_BG2()}; color:{_MUTED()};
                    border:1px solid {_BORDER()}; border-radius:5px;
                    padding:6px 14px; font-size:{FONT["sublabel"]}pt;
                }}
                QPushButton:checked {{
                    background:{_ACCENT()}22; color:{_TEXT()};
                    border:1px solid {_ACCENT()};
                }}
                QPushButton:hover:!checked {{ background:{_BG()}; color:{_TEXT()}; }}
            """)

        # Lab / Operator form widgets
        if hasattr(self, "_lab_op_combo"):
            self._lab_op_combo.setStyleSheet(_COMBO())
        if hasattr(self, "_lab_new_edit"):
            self._lab_new_edit.setStyleSheet(f"""
                QLineEdit {{
                    background:{_BG2()}; color:{_TEXT()}; border:1px solid {_BORDER()};
                    border-radius:4px; padding:4px 8px; font-size:{FONT["label"]}pt;
                }}
            """)
        if hasattr(self, "_lab_add_btn"):
            self._lab_add_btn.setStyleSheet(_BTN_SECONDARY())
        if hasattr(self, "_lab_require_chk"):
            self._lab_require_chk.setStyleSheet(_CHECK())
        if hasattr(self, "_lab_confirm_chk"):
            self._lab_confirm_chk.setStyleSheet(_CHECK())
        # Rebuild the operator list rows (they use _TEXT()/_MUTED() lambdas)
        if hasattr(self, "_lab_op_list_lay"):
            self._lab_rebuild_list()

        # Software Updates form widgets
        if hasattr(self, "_auto_check"):
            self._auto_check.setStyleSheet(_CHECK())
        if hasattr(self, "_freq_combo"):
            self._freq_combo.setStyleSheet(_COMBO())
        if hasattr(self, "_channel_combo"):
            self._channel_combo.setStyleSheet(_COMBO())
        if hasattr(self, "_check_btn"):
            self._check_btn.setStyleSheet(_BTN_PRIMARY())
        if hasattr(self, "_check_result"):
            self._check_result.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{_MUTED()};")

        # Security group widgets
        if hasattr(self, "_sec_require_login_chk"):
            self._sec_require_login_chk.setStyleSheet(_CHECK())
        if hasattr(self, "_sec_timeout_spin"):
            self._sec_timeout_spin.setStyleSheet(_COMBO())

        # AI Assistant group widgets
        if hasattr(self, "_ai_privacy_frame"):
            self._ai_privacy_frame.setStyleSheet(
                f"QFrame {{ background:{_BG2()}; border:1px solid {_GREEN()}55; "
                f"border-radius:5px; }}")
        if hasattr(self, "_ai_no_llama_frame"):
            self._ai_no_llama_frame.setStyleSheet(
                f"QFrame {{ background:{_BG2()}; border:1px solid {_AMBER()}55; "
                f"border-radius:5px; }}")
        if hasattr(self, "_ai_hw_frame"):
            self._ai_hw_frame.setStyleSheet(
                f"QFrame {{ background:{_BG2()}; border:1px solid {_BORDER()}; "
                f"border-radius:4px; }}")
        if hasattr(self, "_ai_enable_chk"):
            self._ai_enable_chk.setStyleSheet(_CHECK())
        if hasattr(self, "_ai_model_combo"):
            self._ai_model_combo.setStyleSheet(_COMBO())
        if hasattr(self, "_ai_download_btn"):
            self._ai_download_btn.setStyleSheet(_BTN_PRIMARY())
        if hasattr(self, "_ai_cancel_btn"):
            self._ai_cancel_btn.setStyleSheet(_BTN_SECONDARY())
        if hasattr(self, "_ai_progress_bar"):
            self._ai_progress_bar.setStyleSheet(
                f"QProgressBar {{ background:{_BG2()}; border:1px solid {_BORDER()}; "
                f"border-radius:4px; font-size:{FONT['caption']}pt; color:{_TEXT()}; }}"
                f"QProgressBar::chunk {{ background:{_GREEN()}; border-radius:3px; }}")
        if hasattr(self, "_ai_path_edit"):
            self._ai_path_edit.setStyleSheet(
                f"QLineEdit {{ background:{_BG2()}; color:{_TEXT()}; "
                f"border:1px solid {_BORDER()}; border-radius:4px; "
                f"font-size:{FONT['label']}pt; padding:5px 8px; }}")
        if hasattr(self, "_ai_browse_btn"):
            self._ai_browse_btn.setStyleSheet(_BTN_SECONDARY())
        if hasattr(self, "_ai_gpu_slider"):
            self._ai_gpu_slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    background:{_BG2()}; border:1px solid {_BORDER()};
                    height:6px; border-radius:3px;
                }}
                QSlider::handle:horizontal {{
                    background:{_ACCENT()}; border:none;
                    width:16px; height:16px; margin:-5px 0; border-radius:8px;
                }}
                QSlider::sub-page:horizontal {{
                    background:{_ACCENT()}55; border-radius:3px;
                }}
                QSlider:disabled::handle:horizontal {{ background:{_BORDER()}; }}
                QSlider:disabled::sub-page:horizontal {{ background:{_BG2()}; }}
            """)
        if hasattr(self, "_ai_apply_btn"):
            self._ai_apply_btn.setStyleSheet(_BTN_PRIMARY())

        # Software Updates — View All Releases button
        if hasattr(self, "_releases_btn"):
            self._releases_btn.setStyleSheet(_BTN_SECONDARY())

        # Support group — About button
        if hasattr(self, "_about_btn"):
            self._about_btn.setStyleSheet(_BTN_SECONDARY())

        # License group — Manage button
        if hasattr(self, "_manage_license_btn"):
            self._manage_license_btn.setStyleSheet(_BTN_PRIMARY())

    def _build_version_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{_BG2()}; border:1px solid {_BORDER()}; border-radius:6px;")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(0)

        col = QVBoxLayout()
        self._version_name_lbl = QLabel(f"{APP_VENDOR}  {APP_NAME}")
        self._version_name_lbl.setStyleSheet(scaled_qss(f"font-size:{FONT['heading']}pt; font-weight:700; color:{_TEXT()};"))
        col.addWidget(self._version_name_lbl)

        ver_lbl = QLabel(f"Version {version_string()}  ·  Built {BUILD_DATE}")
        ver_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_GREEN()};")
        col.addWidget(ver_lbl)

        lay.addLayout(col, 1)

        self._update_status_lbl = QLabel("")
        self._update_status_lbl.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._update_status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._update_status_lbl)

        return card

    def _build_security_group(self) -> QGroupBox:
        """Security settings — shown only to admins."""
        grp = _group("Security  (Admin)")
        lay = QVBoxLayout(grp)
        lay.setSpacing(14)

        lay.addWidget(_body(
            "Configure authentication requirements for all users on this instrument."))

        # ── Require Login toggle ──────────────────────────────────────
        self._sec_require_login_chk = QCheckBox("Require login at startup")
        self._sec_require_login_chk.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_TEXT()};")
        current = cfg_mod.get_pref("auth.require_login", False)
        self._sec_require_login_chk.setChecked(bool(current))
        self._sec_require_login_chk.stateChanged.connect(
            lambda s: cfg_mod.set_pref(
                "auth.require_login", bool(s)))
        lay.addWidget(self._sec_require_login_chk)

        lay.addWidget(_sep())

        # ── Lock timeout ──────────────────────────────────────────────
        timeout_row = QHBoxLayout()
        timeout_lbl = QLabel("Inactivity lock timeout:")
        timeout_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        timeout_row.addWidget(timeout_lbl)

        self._sec_timeout_spin = QSpinBox()
        self._sec_timeout_spin.setRange(60, 14400)    # 1 min – 4 hrs
        self._sec_timeout_spin.setSingleStep(60)
        self._sec_timeout_spin.setSuffix(" s")
        self._sec_timeout_spin.setFixedWidth(90)
        self._sec_timeout_spin.setStyleSheet(_COMBO())
        self._sec_timeout_spin.setValue(
            int(cfg_mod.get_pref("auth.lock_timeout_s", 1800)))
        self._sec_timeout_spin.valueChanged.connect(
            lambda v: cfg_mod.set_pref("auth.lock_timeout_s", v))
        timeout_row.addWidget(self._sec_timeout_spin)
        timeout_row.addStretch(1)
        lay.addLayout(timeout_row)

        return grp

    def _build_users_group(self) -> QGroupBox:
        """User management — shown only to admins."""
        grp = _group("User Management  (Admin)")
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        try:
            from ui.auth.user_management_widget import UserManagementWidget
            store = getattr(
                getattr(self, "_auth", None), "_store", None)
            audit = getattr(
                getattr(self, "_auth", None), "_audit", None)
            if store is not None and audit is not None:
                widget = UserManagementWidget(
                    store, audit,
                    current_session=self._auth_session,
                    parent=self,
                )
            else:
                widget = UserManagementWidget(parent=self)
            lay.addWidget(widget)
        except Exception as exc:
            lay.addWidget(_body(f"User management unavailable: {exc}"))

        return grp

    def _build_updates_group(self) -> QGroupBox:
        g = _group("Software Updates")
        lay = QVBoxLayout(g)
        lay.setSpacing(14)

        # Auto-check toggle
        self._auto_check = QCheckBox("Automatically check for updates on startup")
        self._auto_check.setStyleSheet(_CHECK())
        self._auto_check.setChecked(cfg_mod.get_pref("updates.auto_check", True))
        self._auto_check.toggled.connect(self._on_auto_check_changed)
        lay.addWidget(self._auto_check)

        # Frequency
        freq_row = QHBoxLayout()
        freq_row.setSpacing(10)
        freq_lbl = QLabel("Check frequency:")
        freq_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        freq_row.addWidget(freq_lbl)

        self._freq_combo = QComboBox()
        self._freq_combo.addItems(["Every launch", "Daily", "Weekly"])
        freq_map = {"always": 0, "daily": 1, "weekly": 2}
        saved_freq = cfg_mod.get_pref("updates.frequency", "always")
        self._freq_combo.setCurrentIndex(freq_map.get(saved_freq, 0))
        self._freq_combo.setStyleSheet(_COMBO())
        self._freq_combo.setFixedWidth(160)
        self._freq_combo.currentIndexChanged.connect(self._on_freq_changed)
        freq_row.addWidget(self._freq_combo)
        freq_row.addStretch(1)
        lay.addLayout(freq_row)

        # Channel
        ch_row = QHBoxLayout()
        ch_row.setSpacing(10)
        ch_lbl = QLabel("Release channel:")
        ch_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        ch_row.addWidget(ch_lbl)

        self._channel_combo = QComboBox()
        self._channel_combo.addItems(["Stable releases only", "Include pre-releases (beta)"])
        include_pre = cfg_mod.get_pref("updates.include_prerelease", False)
        self._channel_combo.setCurrentIndex(1 if include_pre else 0)
        self._channel_combo.setStyleSheet(_COMBO())
        self._channel_combo.setFixedWidth(260)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._channel_combo)
        ch_row.addStretch(1)
        lay.addLayout(ch_row)

        lay.addWidget(_sep())

        # Manual check row
        check_row = QHBoxLayout()
        self._check_btn = QPushButton("Check Now")
        self._check_btn.setStyleSheet(_BTN_PRIMARY())
        self._check_btn.setFixedWidth(130)
        self._check_btn.clicked.connect(self._on_check_now)
        check_row.addWidget(self._check_btn)

        self._check_result = QLabel("")
        self._check_result.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        check_row.addWidget(self._check_result, 1)
        lay.addLayout(check_row)

        note = _body(
            "When an update is available, an indicator will appear in the application "
            "header. You can also view all releases on the Microsanj GitHub page.")
        lay.addWidget(note)

        self._releases_btn = QPushButton("View All Releases on GitHub ↗")
        releases_btn = self._releases_btn
        releases_btn.setStyleSheet(_BTN_SECONDARY())
        releases_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL)))
        lay.addWidget(releases_btn)

        self._update_freq_enabled()

        # Collect admin-gated widgets.
        # NOTE: _check_btn is intentionally NOT gated — any user should be
        # able to check for updates.  Only the auto-check preferences
        # (frequency, channel) are admin-restricted.
        self._upd_admin_widgets = [
            self._auto_check,
            self._freq_combo,
            self._channel_combo,
        ]

        return g

    def _build_license_group(self) -> QGroupBox:
        """License status card with a shortcut to the License dialog."""
        g = _group("License")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # Status row
        status_row = QWidget()
        status_row.setStyleSheet("background:transparent;")
        sr_lay = QHBoxLayout(status_row)
        sr_lay.setContentsMargins(0, 0, 0, 0)
        sr_lay.setSpacing(10)

        self._lic_status_icon  = QLabel("○")
        self._lic_status_icon.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{_AMBER()};")
        self._lic_status_label = QLabel("Loading…")
        self._lic_status_label.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_TEXT()};")

        sr_lay.addWidget(self._lic_status_icon)
        sr_lay.addWidget(self._lic_status_label, 1)

        self._manage_license_btn = QPushButton("Manage License…")
        self._manage_license_btn.setStyleSheet(_BTN_PRIMARY())
        self._manage_license_btn.setFixedHeight(30)
        self._manage_license_btn.setToolTip("View license details or activate a new key")
        self._manage_license_btn.clicked.connect(self._on_manage_license)
        sr_lay.addWidget(self._manage_license_btn)

        lay.addWidget(status_row)

        # Detail line (customer name / expiry)
        self._lic_detail_label = QLabel("")
        self._lic_detail_label.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{_MUTED()};")
        self._lic_detail_label.setWordWrap(True)
        lay.addWidget(self._lic_detail_label)

        # Populate immediately
        self.refresh_license_status()

        return g

    def refresh_license_status(self):
        """Re-read the current license from app_state and update the card."""
        from hardware.app_state import app_state
        from licensing.license_model import LicenseTier

        info = app_state.license_info

        if info is None or info.tier == LicenseTier.UNLICENSED:
            self._lic_status_icon.setText("○")
            self._lic_status_icon.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{_AMBER()};")
            self._lic_status_label.setText("Unlicensed — demo mode only")
            self._lic_status_label.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_AMBER()};")
            self._lic_detail_label.setText(
                "Activate a license key to enable full hardware access.")
        else:
            days = info.days_until_expiry
            if days is not None and days <= 30:
                icon_color = _AMBER()
                status_text = f"Active — expires in {days} day{'s' if days != 1 else ''}"
            else:
                icon_color = _GREEN()
                status_text = "Active"

            self._lic_status_icon.setText("●")
            self._lic_status_icon.setStyleSheet(f"font-size:{FONT['heading']}pt; color:{icon_color};")
            self._lic_status_label.setText(status_text)
            self._lic_status_label.setStyleSheet(f"font-size:{FONT['label']}pt; color:{icon_color};")

            detail_parts = [f"{info.tier_display}  ·  {info.customer}"]
            if info.email:
                detail_parts.append(info.email)
            if not info.is_perpetual:
                detail_parts.append(f"Expires {info.expires}")
            self._lic_detail_label.setText("  ·  ".join(detail_parts))

    def _on_manage_license(self):
        """Open the License dialog from the Settings tab."""
        from ui.license_dialog import LicenseDialog
        from PyQt5.QtWidgets import QApplication
        parent = QApplication.activeWindow()
        dlg = LicenseDialog(parent=parent)
        dlg.license_changed.connect(self.refresh_license_status)
        dlg.exec_()

    def _build_plugins_group(self) -> QGroupBox:
        g = _group("Plugins")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        desc = _body(
            "Plugins extend SanjINSIGHT with custom hardware drivers, analysis "
            "algorithms, and tool panels. Plugins are loaded from "
            "~/.microsanj/plugins/ on startup.")
        lay.addWidget(desc)

        # Plugin directory and status
        self._plugin_status = QLabel("No plugins loaded.")
        self._plugin_status.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        lay.addWidget(self._plugin_status)

        # Plugin list container
        self._plugin_list_widget = QWidget()
        self._plugin_list_layout = QVBoxLayout(self._plugin_list_widget)
        self._plugin_list_layout.setContentsMargins(0, 0, 0, 0)
        self._plugin_list_layout.setSpacing(6)
        lay.addWidget(self._plugin_list_widget)

        # Open plugins folder button
        open_btn = QPushButton("Open Plugins Folder")
        open_btn.setStyleSheet(_BTN_SECONDARY())
        open_btn.clicked.connect(self._open_plugins_folder)
        lay.addWidget(open_btn)

        return g

    def refresh_plugins_list(self, registry=None) -> None:
        """Populate the plugins list from the registry (called after load)."""
        # Clear existing rows
        while self._plugin_list_layout.count():
            item = self._plugin_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if registry is None or len(registry) == 0:
            self._plugin_status.setText("No plugins loaded.")
            return

        manifests = registry.get_all_manifests()
        self._plugin_status.setText(
            f"{len(manifests)} plugin(s) loaded")

        for m in manifests:
            row = QWidget()
            row.setStyleSheet(f"""
                QWidget {{
                    background: {_BG2()};
                    border: 1px solid {_BORDER()};
                    border-radius: 4px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 8, 12, 8)
            rl.setSpacing(8)

            # Icon
            icon_lbl = QLabel("\U0001F9E9")  # puzzle piece emoji
            icon_lbl.setStyleSheet("border:none;")
            rl.addWidget(icon_lbl)

            # Name + version
            name_lbl = QLabel(f"<b>{m.name}</b>  "
                              f"<span style='color:{_MUTED()}'>"
                              f"v{m.version}</span>")
            name_lbl.setStyleSheet(
                f"color:{_TEXT()}; font-size:{FONT['label']}pt; border:none;")
            rl.addWidget(name_lbl, 1)

            # Type badge
            _type_colors = {
                "hardware_panel": _ACCENT(),
                "analysis_view": PALETTE['systemIndigo'],
                "tool_panel": _AMBER(),
                "drawer_tab": _MUTED(),
                "hardware_driver": _ACCENT(),
                "analysis_pipeline": PALETTE['systemIndigo'],
            }
            badge_color = _type_colors.get(m.plugin_type, _MUTED())
            type_label = m.plugin_type.replace("_", " ").title()
            badge = QLabel(type_label)
            badge.setStyleSheet(f"""
                QLabel {{
                    color: {badge_color};
                    font-size: {FONT['caption']}pt;
                    border: 1px solid {badge_color};
                    border-radius: 3px;
                    padding: 1px 6px;
                }}
            """)
            rl.addWidget(badge)

            # Enable/disable toggle
            toggle = QCheckBox()
            toggle.setChecked(
                cfg_mod.get_pref(f"plugins.{m.id}.enabled", True))
            toggle.setToolTip("Enable or disable this plugin (restart required)")
            toggle.setStyleSheet("border:none;")
            toggle.toggled.connect(
                lambda checked, pid=m.id: self._on_plugin_toggled(pid, checked))
            rl.addWidget(toggle)

            self._plugin_list_layout.addWidget(row)

    def _on_plugin_toggled(self, plugin_id: str, enabled: bool) -> None:
        cfg_mod.set_pref(f"plugins.{plugin_id}.enabled", enabled)
        log.info("Plugin '%s' %s (restart required)",
                 plugin_id, "enabled" if enabled else "disabled")

    def _open_plugins_folder(self) -> None:
        from pathlib import Path
        plugins_dir = Path.home() / ".microsanj" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(plugins_dir)))

    # ── Diagnostics section ──────────────────────────────────────────

    def _build_diagnostics_group(self) -> QGroupBox:
        """Diagnostics: hardware debug logging and log file access."""
        from pathlib import Path
        grp = _group("Diagnostics")
        lay = QVBoxLayout(grp)
        lay.setSpacing(14)

        lay.addWidget(_body(
            "Enable hardware debug logging to capture wire-level serial "
            "TX/RX traffic, command timing, and detailed connection "
            "diagnostics in the log file.  Useful when troubleshooting "
            "device connectivity.  Disable when not needed — debug "
            "logging increases file I/O."))

        # ── Hardware debug checkbox ──────────────────────────────────
        self._hw_debug_chk = QCheckBox("Enable hardware debug logging")
        self._hw_debug_chk.setStyleSheet(_CHECK())
        self._hw_debug_chk.setChecked(
            cfg_mod.get_pref("logging.hardware_debug", False))
        self._hw_debug_chk.toggled.connect(self._on_hw_debug_toggled)
        lay.addWidget(self._hw_debug_chk)

        lay.addWidget(_sep())

        # ── Open log file / folder ───────────────────────────────────
        log_row = QHBoxLayout()
        log_lbl = QLabel("Log file location")
        log_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        log_row.addWidget(log_lbl)
        log_row.addStretch()

        import logging_config as _lc
        _log_path = str(_lc.log_path())

        open_log_btn = QPushButton("Open Log File")
        open_log_btn.setFixedWidth(130)
        open_log_btn.setStyleSheet(_BTN_SECONDARY())
        open_log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(_log_path)))
        log_row.addWidget(open_log_btn)

        open_folder_btn = QPushButton("Open Folder")
        open_folder_btn.setFixedWidth(110)
        open_folder_btn.setStyleSheet(_BTN_SECONDARY())
        _log_folder = str(Path(_log_path).parent)
        open_folder_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(_log_folder)))
        log_row.addWidget(open_folder_btn)
        lay.addLayout(log_row)

        path_lbl = QLabel(_log_path)
        path_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{_MUTED()}; "
            f"font-family:{MONO_FONT};")
        path_lbl.setWordWrap(True)
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(path_lbl)

        return grp

    def _on_hw_debug_toggled(self, enabled: bool) -> None:
        """Handle the hardware debug logging checkbox."""
        cfg_mod.set_pref("logging.hardware_debug", enabled)
        try:
            import logging_config as _lc
            _lc.set_hardware_debug(enabled)
        except Exception:
            pass
        log.info("Hardware debug logging %s by user",
                 "ENABLED" if enabled else "disabled")

    def _build_support_group(self) -> QGroupBox:
        g = _group("Support & About")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        info = _body(
            "When contacting Microsanj support, please include your version number "
            "and system information. Use the button below to copy it to your clipboard.")
        lay.addWidget(info)

        self._about_btn = QPushButton("About SanjINSIGHT…")
        about_btn = self._about_btn
        about_btn.setStyleSheet(_BTN_SECONDARY())
        about_btn.clicked.connect(self._open_about)
        lay.addWidget(about_btn)

        contact_row = QHBoxLayout()
        contact_lbl = QLabel(f"Support email:  {SUPPORT_EMAIL}")
        contact_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        contact_row.addWidget(contact_lbl)
        contact_row.addStretch(1)
        lay.addLayout(contact_row)

        return g

    # ── Event handlers ────────────────────────────────────────────────

    def _on_auto_check_changed(self, checked: bool):
        cfg_mod.set_pref("updates.auto_check", checked)
        self._update_freq_enabled()

    def _on_freq_changed(self, idx: int):
        mapping = {0: "always", 1: "daily", 2: "weekly"}
        cfg_mod.set_pref("updates.frequency", mapping[idx])

    def _on_channel_changed(self, idx: int):
        cfg_mod.set_pref("updates.include_prerelease", idx == 1)

    def _update_freq_enabled(self):
        enabled = self._auto_check.isChecked()
        self._freq_combo.setEnabled(enabled)
        self._channel_combo.setEnabled(enabled)

    def _on_check_now(self):
        self._check_btn.setEnabled(False)
        self._check_result.setText("Checking…")
        self._check_result.setStyleSheet(f"font-size:{FONT['label']}pt; color:{_MUTED()};")
        self.check_for_updates_requested.emit()

    def set_check_result(self, message: str, color: str = None):
        """Called by MainWindow after a manual check completes."""
        self._check_result.setText(message)
        self._check_result.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{color or _MUTED()};")
        self._check_btn.setEnabled(True)

    def set_update_status(self, message: str, color: str = None):
        """Update the version card status label."""
        self._update_status_lbl.setText(message)
        if color:
            self._update_status_lbl.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{color};")

    def _open_about(self):
        from ui.update_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec_()

    # ── Settings search / filter ───────────────────────────────────────

    def set_auth_session(self, session) -> None:
        """Update the active auth session — shows/hides and enables/disables admin controls."""
        self._auth_session = session
        is_admin = getattr(
            getattr(session, "user", None), "is_admin", False
        ) if session else False
        if hasattr(self, "_security_group"):
            self._security_group.setVisible(is_admin)
        if hasattr(self, "_users_group"):
            self._users_group.setVisible(is_admin)
        self._apply_admin_gate(is_admin)

    def _apply_admin_gate(self, is_admin: bool) -> None:
        """Enable or disable admin-only settings widgets; show tooltip when locked."""
        _tip = "" if is_admin else "Administrator login required"
        gated = (
            getattr(self, "_lab_admin_widgets", [])
            + getattr(self, "_upd_admin_widgets", [])
        )
        for w in gated:
            w.setEnabled(is_admin)
            w.setToolTip(_tip)

    def _filter_settings(self, text: str) -> None:
        """Show/hide QGroupBox sections based on search text."""
        groups = getattr(self, "_setting_groups", [])
        if not groups:
            return

        needle = text.strip().lower()

        visible_count = 0
        for group in groups:
            if not needle:
                group.setVisible(True)
                visible_count += 1
                continue

            # Match on group box title
            if needle in group.title().lower():
                group.setVisible(True)
                visible_count += 1
                continue

            # Match on any QLabel text within the group
            matched = any(
                needle in lbl.text().lower()
                for lbl in group.findChildren(QLabel)
                if lbl.text()
            )
            group.setVisible(matched)
            if matched:
                visible_count += 1

        total = len(groups)
        if hasattr(self, "_settings_filter_status"):
            self._settings_filter_status.setText(
                f"Showing {visible_count} of {total} sections"
            )

    def keyPressEvent(self, event) -> None:
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            self._settings_search.setFocus()
            self._settings_search.selectAll()
        super().keyPressEvent(event)
