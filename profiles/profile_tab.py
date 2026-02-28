"""
profiles/profile_tab.py

ProfileTab — material profile browser, selector, and manager.
"""

from __future__ import annotations
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGroupBox, QGridLayout, QTextEdit,
    QLineEdit, QSplitter, QComboBox, QDoubleSpinBox, QSpinBox,
    QSizePolicy, QMessageBox, QFileDialog,
    QDialog, QDialogButtonBox, QFormLayout, QTabWidget)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui  import QColor, QPainter, QFont, QLinearGradient, QBrush

from .profiles        import (MaterialProfile,
                               CATEGORY_SEMICONDUCTOR, CATEGORY_PCB,
                               CATEGORY_AUTOMOTIVE, CATEGORY_METAL,
                               CATEGORY_USER)
from .profiles        import CATEGORY_ACCENTS, CATEGORY_COLORS
from .profile_manager import ProfileManager, is_protected, SOURCE_BUILTIN, SOURCE_DOWNLOADED


# ------------------------------------------------------------------ #
#  C_T confidence bar widget                                          #
# ------------------------------------------------------------------ #

class CtBar(QWidget):
    """Horizontal bar showing nominal C_T with min/max confidence range."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(36)
        self._value = 1.5e-4
        self._lo    = 1.0e-4
        self._hi    = 2.0e-4

    def set_values(self, value, lo, hi):
        self._value = float(value)
        self._lo    = float(lo or value * 0.7)
        self._hi    = float(hi or value * 1.3)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(18, 18, 18))

        lo   = self._lo * 0.5
        hi   = self._hi * 1.5
        span = hi - lo if hi != lo else 1e-30

        def xof(v):
            return int((v - lo) / span * (W - 24) + 12)

        # Confidence band
        x1 = xof(self._lo)
        x2 = xof(self._hi)
        p.setBrush(QColor(0, 80, 60))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(x1, 11, max(x2 - x1, 4), 11, 3, 3)

        # Nominal tick
        xv = xof(self._value)
        p.setBrush(QColor(0, 210, 140))
        p.drawRect(xv - 2, 7, 4, 19)

        # Labels
        p.setFont(QFont("Menlo", 11))
        p.setPen(QColor(80, 80, 80))
        p.drawText(x1,      32, f"{self._lo:.2e}")
        p.drawText(x2 - 38, 32, f"{self._hi:.2e}")
        p.setPen(QColor(0, 200, 130))
        p.drawText(xv - 20, 8, f"{self._value:.2e} K\u207b\u00b9")
        p.end()


# ------------------------------------------------------------------ #
#  Profile card                                                       #
# ------------------------------------------------------------------ #

class ProfileCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, profile: MaterialProfile, parent=None):
        super().__init__(parent)
        self.uid = profile.uid
        self.setFixedHeight(72)
        self.setCursor(Qt.PointingHandCursor)
        self._set_style(False, profile.category)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(10)

        accent = CATEGORY_ACCENTS.get(profile.category, "#555")
        stripe = QFrame()
        stripe.setFixedWidth(4)
        stripe.setStyleSheet(f"background:{accent}; border-radius:2px;")
        lay.addWidget(stripe)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(profile.name)
        name_lbl.setStyleSheet("font-size:14pt; color:#ccc; font-weight:bold;")
        cat_lbl  = QLabel(
            f"{profile.category}  \u00b7  "
            f"C\u209c {profile.ct_value:.2e} K\u207b\u00b9  \u00b7  "
            f"{profile.wavelength_nm} nm")
        cat_lbl.setStyleSheet("font-size:13pt; color:#555;")
        src_map = {"builtin":    "🔒 built-in",
                   "downloaded": "🔒 ☁ official",
                   "user":       "✎ user",
                   "imported":   "⬆ imported"}
        src_color = ("#444" if profile.source in ("builtin", "downloaded")
                     else accent)
        src_lbl  = QLabel(src_map.get(profile.source, ""))
        src_lbl.setStyleSheet(
            f"font-size:16.5pt; color:{src_color}; font-family:Menlo,monospace;")
        info.addWidget(name_lbl)
        info.addWidget(cat_lbl)
        lay.addLayout(info, 1)
        lay.addWidget(src_lbl)

    def _set_style(self, selected, category=""):
        accent = CATEGORY_ACCENTS.get(category, "#333")
        bg     = CATEGORY_COLORS.get(category, "#1e1e1e")
        if selected:
            self.setStyleSheet(
                f"ProfileCard{{background:{bg}; "
                f"border:1px solid {accent}; border-radius:3px;}}")
        else:
            self.setStyleSheet(
                "ProfileCard{background:#1a1a1a; border:1px solid #242424; "
                "border-radius:3px;}"
                f"ProfileCard:hover{{background:{bg}; border-color:#333;}}")

    def set_selected(self, sel, category=""):
        self._set_style(sel, category)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)


# ------------------------------------------------------------------ #
#  Profile editor dialog                                              #
# ------------------------------------------------------------------ #

class ProfileEditorDialog(QDialog):

    def __init__(self, profile: MaterialProfile = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile else "New Profile")
        self.setMinimumWidth(460)
        self._profile = profile or MaterialProfile(source="user")

        lay  = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self._name     = QLineEdit(self._profile.name)
        self._material = QLineEdit(self._profile.material)

        self._category = QComboBox()
        for c in [CATEGORY_SEMICONDUCTOR, CATEGORY_PCB,
                  CATEGORY_AUTOMOTIVE, CATEGORY_METAL, CATEGORY_USER]:
            self._category.addItem(c)
        idx = self._category.findText(self._profile.category)
        if idx >= 0:
            self._category.setCurrentIndex(idx)

        self._wl = QSpinBox()
        self._wl.setRange(400, 1100); self._wl.setSuffix(" nm")
        self._wl.setValue(self._profile.wavelength_nm)

        def dbl(val, lo=1e-6, hi=1e-2, step=1e-5, dec=3):
            s = QDoubleSpinBox()
            s.setDecimals(dec); s.setRange(lo, hi)
            s.setSingleStep(step); s.setValue(val)
            return s

        self._ct     = dbl(self._profile.ct_value)
        self._ct_min = dbl(self._profile.ct_min or self._profile.ct_value * 0.7)
        self._ct_max = dbl(self._profile.ct_max or self._profile.ct_value * 1.3)

        self._exposure = QDoubleSpinBox()
        self._exposure.setRange(100, 100000)
        self._exposure.setSuffix(" us"); self._exposure.setValue(self._profile.exposure_us)

        self._gain = QDoubleSpinBox()
        self._gain.setRange(0, 24); self._gain.setSuffix(" dB")
        self._gain.setValue(self._profile.gain_db)

        self._n_frames = QSpinBox()
        self._n_frames.setRange(4, 256); self._n_frames.setValue(self._profile.n_frames)

        self._accum = QSpinBox()
        self._accum.setRange(1, 256); self._accum.setValue(self._profile.accumulation)

        self._dt_range = QDoubleSpinBox()
        self._dt_range.setRange(0.1, 200); self._dt_range.setSuffix(" K")
        self._dt_range.setValue(self._profile.dt_range_k)

        self._description = QTextEdit(self._profile.description)
        self._description.setFixedHeight(70)
        self._notes = QTextEdit(self._profile.notes)
        self._notes.setFixedHeight(70)
        self._ct_notes = QLineEdit(self._profile.ct_notes)

        for label, widget in [
            ("Name",          self._name),
            ("Material",      self._material),
            ("Category",      self._category),
            ("Wavelength",    self._wl),
            ("C_T nominal",   self._ct),
            ("C_T min",       self._ct_min),
            ("C_T max",       self._ct_max),
            ("C_T notes",     self._ct_notes),
            ("Exposure",      self._exposure),
            ("Gain",          self._gain),
            ("Frames / half", self._n_frames),
            ("EMA depth",     self._accum),
            ("dT range",      self._dt_range),
            ("Description",   self._description),
            ("Notes",         self._notes),
        ]:
            form.addRow(label, widget)

        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _save(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Required", "Name cannot be empty.")
            return
        p = self._profile
        p.name          = self._name.text().strip()
        p.material      = self._material.text().strip()
        p.category      = self._category.currentText()
        p.wavelength_nm = self._wl.value()
        p.ct_value      = self._ct.value()
        p.ct_min        = self._ct_min.value()
        p.ct_max        = self._ct_max.value()
        p.ct_notes      = self._ct_notes.text()
        p.exposure_us   = self._exposure.value()
        p.gain_db       = self._gain.value()
        p.n_frames      = self._n_frames.value()
        p.accumulation  = self._accum.value()
        p.dt_range_k    = self._dt_range.value()
        p.description   = self._description.toPlainText()
        p.notes         = self._notes.toPlainText()
        self.accept()

    def get_profile(self) -> MaterialProfile:
        return self._profile


# ------------------------------------------------------------------ #
#  Main profile tab                                                   #
# ------------------------------------------------------------------ #

class ProfileTab(QWidget):

    profile_applied = pyqtSignal(object)   # MaterialProfile

    def __init__(self, manager: ProfileManager):
        super().__init__()
        self._mgr      = manager
        self._cards    = {}      # uid -> ProfileCard
        self._selected = None    # uid

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_detail())
        splitter.setSizes([340, 860])

        self._populate()

    # ---- list panel ----

    def _build_list(self) -> QWidget:
        w   = QWidget(); w.setMinimumWidth(290); w.setMaximumWidth(400)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8); lay.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel("MATERIAL PROFILES")
        title.setStyleSheet("font-size:14pt; color:#555; letter-spacing:2px;")
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#333;")
        hdr.addWidget(title); hdr.addStretch(); hdr.addWidget(self._count_lbl)
        lay.addLayout(hdr)

        self._cat_filter = QComboBox()
        self._cat_filter.addItem("All Categories")
        for c in [CATEGORY_SEMICONDUCTOR, CATEGORY_PCB,
                  CATEGORY_AUTOMOTIVE, CATEGORY_METAL, CATEGORY_USER]:
            self._cat_filter.addItem(c)
        self._cat_filter.currentTextChanged.connect(self._filter)
        lay.addWidget(self._cat_filter)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search profiles...")
        self._search.textChanged.connect(self._filter)
        lay.addWidget(self._search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:#141414;}")
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(3)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        lay.addWidget(scroll)

        btn_row = QHBoxLayout()
        self._new_btn      = QPushButton("+ New Profile")
        self._import_btn   = QPushButton("Import…")
        self._download_btn = QPushButton("🌐  Get Online Profiles")
        self._download_btn.setObjectName("primary")
        for b in [self._new_btn, self._import_btn]:
            b.setFixedHeight(28); btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._download_btn.setFixedHeight(30)
        lay.addWidget(self._download_btn)

        self._new_btn.clicked.connect(self._new_profile)
        self._import_btn.clicked.connect(self._import_profile)
        self._download_btn.clicked.connect(self._open_downloader)
        return w

    # ---- detail panel ----

    def _build_detail(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8); lay.setSpacing(8)

        # Apply banner
        banner = QWidget()
        banner.setFixedHeight(54)
        banner.setStyleSheet(
            "background:#0d1f19; border:1px solid #1a3a2a; border-radius:4px;")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 0, 16, 0)
        self._apply_name = QLabel("Select a profile")
        self._apply_name.setStyleSheet(
            "font-size:19pt; color:#ccc; font-weight:bold;")
        self._apply_btn = QPushButton("  Apply Profile  ")
        self._apply_btn.setObjectName("primary")
        self._apply_btn.setFixedHeight(36)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply)
        bl.addWidget(self._apply_name, 1)
        bl.addWidget(self._apply_btn)
        lay.addWidget(banner)

        # Spec tabs
        tabs = QTabWidget(); tabs.setDocumentMode(True)

        # --- Overview ---
        ov = QWidget()
        ol = QVBoxLayout(ov); ol.setSpacing(8)

        from ui.help import help_label, HelpButton
        ct_row = QHBoxLayout()
        ct_row.setContentsMargins(0, 0, 0, 0)
        ct_row.setSpacing(4)
        ct_row.addWidget(self._sub(
            "Thermoreflectance Coefficient  C_T  [1/K]"))
        ct_row.addWidget(HelpButton("ct_value"))
        ct_row.addStretch()
        ol.addLayout(ct_row)
        self._ct_bar = CtBar()
        ol.addWidget(self._ct_bar)
        self._ct_notes_lbl = QLabel("")
        self._ct_notes_lbl.setStyleSheet(
            "font-size:12pt; color:#555; font-style:italic;")
        self._ct_notes_lbl.setWordWrap(True)
        ol.addWidget(self._ct_notes_lbl)

        params_box = QGroupBox("Recommended Settings")
        pg = QGridLayout(params_box); pg.setSpacing(6)
        self._pvals = {}
        entries = [("Exposure", "exp"), ("Gain", "gain"),
                   ("Frames/half", "nf"), ("EMA depth", "acc"),
                   ("dT range", "dtr"), ("Wavelength", "wl")]
        for i, (lbl, key) in enumerate(entries):
            r, c = divmod(i, 2)
            pg.addWidget(self._sub(lbl), r, c * 2)
            v = QLabel("--")
            v.setStyleSheet(
                "font-family:Menlo,monospace; font-size:14pt; color:#aaa;")
            pg.addWidget(v, r, c * 2 + 1)
            self._pvals[key] = v
        ol.addWidget(params_box)

        ol.addWidget(self._sub("Description"))
        self._desc_lbl = QLabel("")
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet("font-size:14pt; color:#888;")
        ol.addWidget(self._desc_lbl)

        ol.addWidget(self._sub("Application Notes"))
        self._notes_lbl = QLabel("")
        self._notes_lbl.setWordWrap(True)
        self._notes_lbl.setStyleSheet(
            "font-size:13pt; color:#666; font-style:italic;")
        ol.addWidget(self._notes_lbl)
        ol.addStretch()
        tabs.addTab(ov, " Overview ")

        # --- Applications ---
        apps_w = QWidget()
        al = QVBoxLayout(apps_w)
        self._tags_lbl = QLabel("--")
        self._tags_lbl.setWordWrap(True)
        self._tags_lbl.setStyleSheet("font-size:14pt; color:#888;")
        al.addWidget(self._sub("Target Industries"))
        al.addWidget(self._tags_lbl)
        al.addStretch()
        tabs.addTab(apps_w, " Applications ")

        lay.addWidget(tabs, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        self._edit_btn  = QPushButton("Edit")
        self._dup_btn   = QPushButton("Duplicate")
        self._exp_btn   = QPushButton("Export")
        self._del_btn   = QPushButton("Delete")
        self._del_btn.setObjectName("danger")
        for b in [self._edit_btn, self._dup_btn,
                  self._exp_btn, self._del_btn]:
            b.setFixedHeight(28); b.setEnabled(False); btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._edit_btn.clicked.connect(self._edit_profile)
        self._dup_btn.clicked.connect(self._dup_profile)
        self._exp_btn.clicked.connect(self._export_profile)
        self._del_btn.clicked.connect(self._del_profile)
        return w

    # ---- populate + filter ----

    def _populate(self):
        for card in list(self._cards.values()):
            self._list_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        for p in self._mgr.all():
            card = ProfileCard(p)
            card.clicked.connect(self._on_card_clicked)
            idx = self._list_layout.count() - 1
            self._list_layout.insertWidget(idx, card)
            self._cards[p.uid] = card

        self._count_lbl.setText(str(self._mgr.count()))
        self._filter()

    def _filter(self):
        cat  = self._cat_filter.currentText()
        text = self._search.text().lower()
        for uid, card in self._cards.items():
            p = self._mgr.get(uid)
            if p is None:
                card.setVisible(False); continue
            cat_ok  = cat == "All Categories" or p.category == cat
            text_ok = (not text or
                       text in p.name.lower() or
                       text in p.material.lower() or
                       text in p.description.lower() or
                       any(text in t.lower() for t in p.industry_tags))
            card.setVisible(cat_ok and text_ok)

    # ---- selection ----

    def _on_card_clicked(self, uid: str):
        if self._selected and self._selected in self._cards:
            p_old = self._mgr.get(self._selected)
            self._cards[self._selected].set_selected(
                False, p_old.category if p_old else "")
        self._selected = uid
        p = self._mgr.get(uid)
        if uid in self._cards:
            self._cards[uid].set_selected(True, p.category if p else "")
        self._show_detail(uid)

    def _show_detail(self, uid: str):
        p = self._mgr.get(uid)
        if p is None:
            return
        self._apply_name.setText(p.name)
        self._apply_btn.setEnabled(True)
        self._ct_bar.set_values(p.ct_value, p.ct_min, p.ct_max)
        self._ct_notes_lbl.setText(p.ct_notes or "")
        self._pvals["exp"].setText(f"{p.exposure_us:.0f} us")
        self._pvals["gain"].setText(f"{p.gain_db:.1f} dB")
        self._pvals["nf"].setText(str(p.n_frames))
        self._pvals["acc"].setText(str(p.accumulation))
        self._pvals["dtr"].setText(f"+-{p.dt_range_k:.0f} K")
        self._pvals["wl"].setText(f"{p.wavelength_nm} nm")
        self._desc_lbl.setText(p.description or "--")
        self._notes_lbl.setText(p.notes or "")
        self._tags_lbl.setText(
            "\n".join(f"  - {t}" for t in p.industry_tags)
            if p.industry_tags else "--")
        protected = is_protected(p)
        self._edit_btn.setEnabled(not protected)
        self._del_btn.setEnabled(not protected)
        self._dup_btn.setEnabled(True)
        self._exp_btn.setEnabled(True)

    # ---- apply ----

    def _apply(self):
        if not self._selected:
            return
        p = self._mgr.get(self._selected)
        if p is None:
            return
        try:
            import main_app
            h, w = 256, 320
            if main_app.cam:
                try:
                    st = main_app.cam.get_status()
                    h, w = st.height or 256, st.width or 320
                except Exception:
                    pass
            main_app.active_calibration = p.make_calibration(h, w)
            main_app.signals.profile_applied.emit(p)
            main_app.signals.log_message.emit(
                f"Profile applied: {p.name}  "
                f"C_T={p.ct_value:.3e} K-1  "
                f"exposure={p.exposure_us:.0f}us  gain={p.gain_db:.1f}dB")
        except Exception as ex:
            QMessageBox.warning(self, "Apply Failed", str(ex))
            return
        self.profile_applied.emit(p)
        self._apply_btn.setText("  Applied  ")
        QTimer.singleShot(2000,
            lambda: self._apply_btn.setText("  Apply Profile  "))

    # ---- CRUD ----

    def _new_profile(self):
        dlg = ProfileEditorDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            p = dlg.get_profile()
            self._mgr.save_user(p)
            self._populate()
            self._on_card_clicked(p.uid)

    def _edit_profile(self):
        if not self._selected:
            return
        p = self._mgr.get(self._selected)
        if p is None or is_protected(p):
            return
        dlg = ProfileEditorDialog(p, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._mgr.save_user(p)
            self._populate()
            self._on_card_clicked(p.uid)

    def _dup_profile(self):
        if not self._selected:
            return
        p = self._mgr.duplicate_as_user(self._selected)
        if p:
            self._populate()
            self._on_card_clicked(p.uid)

    def _export_profile(self):
        if not self._selected:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile",
            f"{self._selected}.json",
            "Profile files (*.json);;All files (*)")
        if path:
            ok = self._mgr.export_profile(self._selected, path)
            if ok:
                QMessageBox.information(self, "Exported",
                                        f"Profile saved to:\n{path}")

    def _import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "",
            "Profile files (*.json);;All files (*)")
        if not path:
            return
        p = self._mgr.import_profile(path)
        if p:
            self._populate()
            self._on_card_clicked(p.uid)
        else:
            QMessageBox.warning(self, "Import Failed",
                                "Could not read profile file.")

    def _del_profile(self):
        if not self._selected:
            return
        p = self._mgr.get(self._selected)
        if p is None or is_protected(p):
            return
        r = QMessageBox.question(
            self, "Delete Profile",
            f"Delete '{p.name}'?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self._mgr.delete_user(self._selected)
            self._selected = None
            self._populate()

    def _open_downloader(self):
        """Open the online profile browser / downloader."""
        from .download_dialog import ProfileDownloadDialog
        dlg = ProfileDownloadDialog(self._mgr, parent=self)
        dlg.profiles_installed.connect(self._on_profiles_installed)
        dlg.exec_()

    def _on_profiles_installed(self, uids: list):
        """Called after new profiles are downloaded — refresh the list."""
        self._mgr.scan()
        self._populate()
        if uids:
            self._on_card_clicked(uids[-1])

    def save_from_settings(self, name: str, material: str,
                           category: str, ct_value: float,
                           exposure_us: float, gain_db: float,
                           n_frames: int, accumulation: int,
                           dt_range_k: float,
                           description: str = "",
                           notes: str = "") -> MaterialProfile:
        """
        Create a user profile from externally-supplied settings
        (called by Scan tab and Acquire tab 'Save as Profile' buttons).
        Saves, refreshes the list, and returns the new profile.
        """
        p = MaterialProfile(
            name         = name,
            material     = material,
            category     = category,
            ct_value     = ct_value,
            ct_min       = ct_value * 0.8,
            ct_max       = ct_value * 1.2,
            exposure_us  = exposure_us,
            gain_db      = gain_db,
            n_frames     = n_frames,
            accumulation = accumulation,
            dt_range_k   = dt_range_k,
            description  = description,
            notes        = notes,
            source       = "user",
        )
        self._mgr.save_user(p)
        self._populate()
        self._on_card_clicked(p.uid)
        return p

    # ---- helper ----

    def _sub(self, text):
        l = QLabel(text); l.setObjectName("sublabel"); return l

