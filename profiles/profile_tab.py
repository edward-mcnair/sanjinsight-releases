"""
profiles/profile_tab.py

ProfileTab — QWidget panel for browsing, applying, and managing
MaterialProfile objects stored via ProfileManager.

Layout
------
  ┌─────────────────────────────────────────────────────┐
  │  Category filter combo  │  [New]  [Delete]  [Apply] │
  ├─────────────────────────────────────────────────────┤
  │  Profile list (name, material, C_T, category)       │
  ├─────────────────────────────────────────────────────┤
  │  Detail pane: all fields read-only                  │
  └─────────────────────────────────────────────────────┘

Public API
----------
    ProfileTab(manager: ProfileManager) → QWidget
    tab.save_from_settings(**kwargs)     # create & persist a profile
    tab.active_profile → MaterialProfile | None
"""

from __future__ import annotations

import logging
import time

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QFormLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QMessageBox, QDialog, QDialogButtonBox, QSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import QColor

from profiles.profiles import (
    MaterialProfile,
    ALL_CATEGORIES, CATEGORY_USER, CATEGORY_ACCENTS,
)
from profiles.profile_manager import ProfileManager
from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)

_ALL_LABEL = "All Categories"


class ProfileTab(QWidget):
    """Displays and manages the MaterialProfile library."""

    profile_applied = pyqtSignal(object)   # MaterialProfile

    def __init__(self, manager: ProfileManager, parent=None):
        super().__init__(parent)
        self._mgr = manager
        self._profiles: list[MaterialProfile] = []
        self._selected: MaterialProfile | None = None

        self._build_ui()
        self._refresh()

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    @property
    def active_profile(self) -> MaterialProfile | None:
        return self._selected

    def save_from_settings(
        self,
        *,
        name: str        = "New Profile",
        material: str    = "",
        category: str    = CATEGORY_USER,
        ct_value: float  = 1.5e-4,
        exposure_us: float = 5000.0,
        gain_db: float   = 0.0,
        n_frames: int    = 16,
        accumulation: int = 16,
        dt_range_k: float = 10.0,
        description: str = "",
        notes: str       = "",
        wavelength_nm: int = 532,
    ) -> MaterialProfile:
        """Create a new profile from acquisition settings and persist it."""
        p = MaterialProfile(
            name          = name,
            material      = material,
            category      = category,
            ct_value      = ct_value,
            exposure_us   = exposure_us,
            gain_db       = gain_db,
            n_frames      = n_frames,
            accumulation  = accumulation,
            dt_range_k    = dt_range_k,
            description   = description,
            notes         = notes,
            wavelength_nm = wavelength_nm,
            created_at    = time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._mgr.save(p)
        self._refresh()
        log.info("Profile saved: %s", p.name)
        return p

    # ---------------------------------------------------------------- #
    #  UI construction                                                  #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Toolbar ────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._cat_cb = QComboBox()
        self._cat_cb.addItem(_ALL_LABEL)
        for cat in ALL_CATEGORIES:
            self._cat_cb.addItem(cat)
        self._cat_cb.currentTextChanged.connect(self._refresh)
        bar.addWidget(self._cat_cb, 1)

        self._new_btn    = QPushButton("New")
        self._delete_btn = QPushButton("Delete")
        self._apply_btn  = QPushButton("Apply")
        self._apply_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        for btn in (self._new_btn, self._delete_btn, self._apply_btn):
            bar.addWidget(btn)

        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn.clicked.connect(self._on_delete)
        self._apply_btn.clicked.connect(self._on_apply)

        root.addLayout(bar)

        # ── Profile table ──────────────────────────────────────────
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Material", "C_T (K⁻¹)", "Category"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {PALETTE['surface2']};
                alternate-background-color: {PALETTE['surface']};
                color: {PALETTE['text']};
                gridline-color: {PALETTE['border']};
                border: 1px solid {PALETTE['border']};
                border-radius: 3px;
            }}
            QTableWidget::item {{
                padding: 3px 6px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background: {PALETTE['info']};
                color: {PALETTE['bg']};
            }}
            QHeaderView::section {{
                background: {PALETTE['surface3']};
                color: {PALETTE['textDim']};
                font-size: {FONT['caption']}pt;
                border: none;
                border-bottom: 1px solid {PALETTE['border']};
                border-right: 1px solid {PALETTE['border']};
                padding: 4px 8px;
            }}
            QHeaderView::section:last {{
                border-right: none;
            }}
            QScrollBar:vertical {{
                background: {PALETTE['surface3']};
                width: 8px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {PALETTE['border']};
                border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)
        root.addWidget(self._table, 3)

        # ── Detail pane ────────────────────────────────────────────
        self._detail_box = QGroupBox("Profile Details")
        detail_box = self._detail_box
        detail_box.setStyleSheet(f"""
            QGroupBox {{
                background: {PALETTE['surface']};
                color: {PALETTE['textDim']};
                font-size: {FONT['label']}pt;
                border: 1px solid {PALETTE['border']};
                border-radius: 4px;
                margin-top: 6px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                left: 8px;
            }}
            QLabel {{
                background: transparent;
                color: {PALETTE['textDim']};
                font-size: {FONT['label']}pt;
            }}
        """)
        fl = QFormLayout(detail_box)
        fl.setContentsMargins(8, 8, 8, 8)

        def _ro_label() -> QLabel:
            lbl = QLabel("-")
            lbl.setStyleSheet(
                f"color: {PALETTE['text']}; font-size: {FONT['label']}pt;")
            return lbl

        self._d_name     = _ro_label()
        self._d_material = _ro_label()
        self._d_category = _ro_label()
        self._d_ct       = _ro_label()
        self._d_wl       = _ro_label()
        self._d_exp      = _ro_label()
        self._d_gain     = _ro_label()
        self._d_frames   = _ro_label()
        self._d_accum    = _ro_label()
        self._d_dt       = _ro_label()
        self._d_desc     = _ro_label()
        self._d_notes    = _ro_label()

        fl.addRow("Name:",          self._d_name)
        fl.addRow("Material:",      self._d_material)
        fl.addRow("Category:",      self._d_category)
        fl.addRow("C_T (K⁻¹):",    self._d_ct)
        fl.addRow("Wavelength:",    self._d_wl)
        fl.addRow("Exposure (µs):", self._d_exp)
        fl.addRow("Gain (dB):",     self._d_gain)
        fl.addRow("Frames:",        self._d_frames)
        fl.addRow("Accumulation:",  self._d_accum)
        fl.addRow("ΔT range (K):",  self._d_dt)
        fl.addRow("Description:",   self._d_desc)
        fl.addRow("Notes:",         self._d_notes)

        root.addWidget(detail_box, 2)

    # ---------------------------------------------------------------- #
    #  Theme                                                            #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        P = PALETTE
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {P['surface2']};
                alternate-background-color: {P['surface']};
                color: {P['text']};
                gridline-color: {P['border']};
                border: 1px solid {P['border']};
                border-radius: 3px;
            }}
            QTableWidget::item {{
                padding: 3px 6px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background: {P['info']};
                color: {P['bg']};
            }}
            QHeaderView::section {{
                background: {P['surface3']};
                color: {P['textDim']};
                font-size: {FONT['caption']}pt;
                border: none;
                border-bottom: 1px solid {P['border']};
                border-right: 1px solid {P['border']};
                padding: 4px 8px;
            }}
            QHeaderView::section:last {{
                border-right: none;
            }}
            QScrollBar:vertical {{
                background: {P['surface3']};
                width: 8px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {P['border']};
                border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self._detail_box.setStyleSheet(f"""
            QGroupBox {{
                background: {P['surface']};
                color: {P['textDim']};
                font-size: {FONT['label']}pt;
                border: 1px solid {P['border']};
                border-radius: 4px;
                margin-top: 6px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                left: 8px;
            }}
            QLabel {{
                background: transparent;
                color: {P['textDim']};
                font-size: {FONT['label']}pt;
            }}
        """)
        _ro_qss = f"color: {P['text']}; font-size: {FONT['label']}pt;"
        for lbl in (self._d_name, self._d_material, self._d_category,
                    self._d_ct, self._d_wl, self._d_exp, self._d_gain,
                    self._d_frames, self._d_accum, self._d_dt,
                    self._d_desc, self._d_notes):
            lbl.setStyleSheet(_ro_qss)

    # ---------------------------------------------------------------- #
    #  Data helpers                                                     #
    # ---------------------------------------------------------------- #

    def _refresh(self):
        cat = self._cat_cb.currentText()
        if cat == _ALL_LABEL:
            self._profiles = self._mgr.all()
        else:
            self._profiles = self._mgr.by_category(cat)

        self._table.setRowCount(0)
        for p in self._profiles:
            row = self._table.rowCount()
            self._table.insertRow(row)
            items = [
                QTableWidgetItem(p.name),
                QTableWidgetItem(p.material),
                QTableWidgetItem(f"{p.ct_value:.3e}"),
                QTableWidgetItem(p.category),
            ]
            accent = CATEGORY_ACCENTS.get(p.category, "#aaaaaa")
            for item in items:
                item.setForeground(QColor(accent))
            for col, item in enumerate(items):
                self._table.setItem(row, col, item)

        self._selected = None
        self._update_detail(None)
        self._apply_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

    def _update_detail(self, p: MaterialProfile | None):
        if p is None:
            for lbl in (self._d_name, self._d_material, self._d_category,
                        self._d_ct, self._d_wl, self._d_exp, self._d_gain,
                        self._d_frames, self._d_accum, self._d_dt,
                        self._d_desc, self._d_notes):
                lbl.setText("-")
            return

        self._d_name.setText(p.name)
        self._d_material.setText(p.material or "-")
        self._d_category.setText(p.category)
        self._d_ct.setText(f"{p.ct_value:.4e}")
        self._d_wl.setText(f"{p.wavelength_nm} nm")
        self._d_exp.setText(f"{p.exposure_us:.0f}")
        self._d_gain.setText(f"{p.gain_db:.1f}")
        self._d_frames.setText(str(p.n_frames))
        self._d_accum.setText(str(p.accumulation))
        self._d_dt.setText(f"{p.dt_range_k:.1f}")
        self._d_desc.setText(p.description or "-")
        self._d_notes.setText(p.notes or "-")

    # ---------------------------------------------------------------- #
    #  Slot handlers                                                    #
    # ---------------------------------------------------------------- #

    def _on_selection(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._selected = None
            self._update_detail(None)
            self._apply_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            return

        idx = rows[0].row()
        if 0 <= idx < len(self._profiles):
            self._selected = self._profiles[idx]
            self._update_detail(self._selected)
            self._apply_btn.setEnabled(True)
            self._delete_btn.setEnabled(
                self._selected.category == CATEGORY_USER)

    def _on_apply(self):
        if self._selected is None:
            return
        from hardware.app_state import app_state
        app_state.active_profile = self._selected
        self.profile_applied.emit(self._selected)
        log.info("Active profile set: %s", self._selected.name)

    def _on_delete(self):
        if self._selected is None or self._selected.category != CATEGORY_USER:
            return
        ans = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{self._selected.name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._mgr.delete(self._selected)
            self._selected = None
            self._refresh()

    def _on_new(self):
        """Show a dialog to create a new user profile from scratch."""
        dlg = QDialog(self)
        dlg.setWindowTitle("New Material Profile")
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {PALETTE['surface']};
            }}
            QLabel {{
                background: transparent;
                color: {PALETTE['textDim']};
                font-size: {FONT['label']}pt;
            }}
            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
                background: {PALETTE['surface3']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: {FONT['label']}pt;
            }}
            QLineEdit:focus, QDoubleSpinBox:focus,
            QSpinBox:focus, QComboBox:focus {{
                border-color: {PALETTE['accent']};
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {PALETTE['surface3']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
            }}
            QPushButton {{
                background: {PALETTE['surface']};
                color: {PALETTE['textDim']};
                border: 1px solid {PALETTE['border']};
                border-radius: 3px;
                padding: 5px 14px;
                font-size: {FONT['label']}pt;
            }}
            QPushButton:hover  {{ background: #252525; color: {PALETTE['text']}; }}
            QPushButton:pressed {{ background: #111; }}
        """)
        fl = QFormLayout(dlg)
        fl.setContentsMargins(12, 12, 12, 12)
        fl.setSpacing(8)

        name_ed  = QLineEdit("My Material")
        mat_ed   = QLineEdit()
        cat_cb   = QComboBox()
        for cat in ALL_CATEGORIES:
            cat_cb.addItem(cat)
        cat_cb.setCurrentText(CATEGORY_USER)

        ct_spin  = QDoubleSpinBox()
        ct_spin.setDecimals(6)
        ct_spin.setRange(1e-7, 1e-2)
        ct_spin.setValue(1.5e-4)
        ct_spin.setSingleStep(1e-5)

        wl_spin  = QSpinBox()
        wl_spin.setRange(400, 1100)
        wl_spin.setValue(532)
        wl_spin.setSuffix(" nm")

        exp_spin = QDoubleSpinBox()
        exp_spin.setRange(100, 1_000_000)
        exp_spin.setValue(5000)
        exp_spin.setSuffix(" µs")

        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(0, 48)
        gain_spin.setValue(0)
        gain_spin.setSuffix(" dB")

        desc_ed  = QLineEdit()
        notes_ed = QLineEdit()

        fl.addRow("Name:",          name_ed)
        fl.addRow("Material:",      mat_ed)
        fl.addRow("Category:",      cat_cb)
        fl.addRow("C_T (K⁻¹):",    ct_spin)
        fl.addRow("Wavelength:",    wl_spin)
        fl.addRow("Exposure:",      exp_spin)
        fl.addRow("Gain:",          gain_spin)
        fl.addRow("Description:",   desc_ed)
        fl.addRow("Notes:",         notes_ed)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        self.save_from_settings(
            name          = name_ed.text().strip() or "New Profile",
            material      = mat_ed.text().strip(),
            category      = cat_cb.currentText(),
            ct_value      = ct_spin.value(),
            wavelength_nm = wl_spin.value(),
            exposure_us   = exp_spin.value(),
            gain_db       = gain_spin.value(),
            description   = desc_ed.text().strip(),
            notes         = notes_ed.text().strip(),
        )
