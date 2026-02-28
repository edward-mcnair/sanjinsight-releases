"""
ui/wizard.py

StandardWizard — the 4-step guided measurement interface for technicians.

Steps
-----
    1. Profile   — pick a material profile (filtered by industry)
    2. Focus     — live camera feed, autofocus, nothing else
    3. Acquire   — one button, progress bar, estimated time
    4. Results   — verdict banner, annotated overlay, export

The wizard is a QStackedWidget. The header shows a step progress bar.
All heavy work delegates to the same backend objects used in Advanced mode
(AcquisitionPipeline, LiveProcessor, ThermalAnalysisEngine) — there is
no duplication of logic.
"""

from __future__ import annotations
import time
from typing import Optional

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QSizePolicy, QScrollArea, QFrame, QComboBox,
    QProgressBar, QFileDialog, QMessageBox, QGridLayout,
    QGroupBox, QSpacerItem)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui  import (QColor, QPainter, QPen, QFont,
                           QImage, QPixmap, QLinearGradient)


# ------------------------------------------------------------------ #
#  Step progress bar                                                   #
# ------------------------------------------------------------------ #

class WizardStepBar(QWidget):
    """Horizontal step indicator: ① Profile → ② Focus → ③ Acquire → ④ Results"""

    STEPS = ["Profile", "Focus", "Acquire", "Results"]

    def __init__(self):
        super().__init__()
        self.setFixedHeight(44)
        self._current = 0

    def set_step(self, index: int):
        self._current = index
        self.update()

    def paintEvent(self, e):
        p   = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(15, 15, 15))

        n     = len(self.STEPS)
        step_w = W / n

        for i, label in enumerate(self.STEPS):
            cx  = int(step_w * i + step_w / 2)
            cy  = H // 2 - 4

            done    = i < self._current
            active  = i == self._current
            pending = i > self._current

            # Connector line (before each step except first)
            if i > 0:
                prev_cx = int(step_w * (i - 1) + step_w / 2)
                line_color = QColor(0, 180, 110) if done else QColor(40, 40, 40)
                p.setPen(QPen(line_color, 2))
                p.drawLine(prev_cx + 14, cy + 1, cx - 14, cy + 1)

            # Circle
            r = 12
            if active:
                p.setBrush(QColor(0, 210, 130))
                p.setPen(QPen(QColor(0, 210, 130), 2))
            elif done:
                p.setBrush(QColor(0, 130, 80))
                p.setPen(QPen(QColor(0, 180, 110), 1))
            else:
                p.setBrush(QColor(30, 30, 30))
                p.setPen(QPen(QColor(50, 50, 50), 1))

            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            # Number / checkmark
            p.setPen(QColor(255, 255, 255) if (active or done)
                     else QColor(60, 60, 60))
            p.setFont(QFont("Helvetica", 12, QFont.Bold))
            text = "✓" if done else str(i + 1)
            p.drawText(cx - r, cy - r, r * 2, r * 2,
                       Qt.AlignCenter, text)

            # Label
            p.setPen(QColor(180, 180, 180) if active
                     else QColor(100, 100, 100) if done
                     else QColor(50, 50, 50))
            p.setFont(QFont("Helvetica", 12,
                            QFont.Bold if active else QFont.Normal))
            p.drawText(cx - 50, cy + r + 4, 100, 16,
                       Qt.AlignCenter, label)

        p.end()


# ------------------------------------------------------------------ #
#  Step 1 — Profile picker                                            #
# ------------------------------------------------------------------ #

class _ProfileCard(QFrame):
    """3-column grid tile: name, description, category, wavelength, C_T."""
    clicked = pyqtSignal(str)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.uid       = profile.uid
        self._profile  = profile
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self._refresh_style()

        from profiles.profiles import CATEGORY_ACCENTS
        accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # Name row with accent stripe
        top = QHBoxLayout()
        top.setSpacing(8)
        stripe = QFrame()
        stripe.setFixedSize(3, 20)
        stripe.setStyleSheet(f"background:{accent}; border-radius:1px;")
        top.addWidget(stripe, 0, Qt.AlignTop)
        name_lbl = QLabel(profile.name)
        name_lbl.setStyleSheet("font-size:14pt; font-weight:bold; color:#ddd;")
        name_lbl.setWordWrap(True)
        top.addWidget(name_lbl, 1)
        root.addLayout(top)

        # Description
        desc = (profile.description[:90] + "…"
                if len(profile.description) > 90 else profile.description)
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("font-size:12pt; color:#585858;")
        desc_lbl.setWordWrap(True)
        root.addWidget(desc_lbl)

        root.addStretch(1)

        # Bottom: category · wavelength · C_T
        bot = QHBoxLayout()
        bot.setSpacing(8)
        cat_lbl = QLabel(profile.category)
        cat_lbl.setStyleSheet(
            f"font-size:10pt; font-weight:bold; color:{accent}99;")
        wl_lbl = QLabel(f"{profile.wavelength_nm} nm")
        wl_lbl.setStyleSheet("font-size:10pt; color:#404040;")
        ct_lbl = QLabel(f"C_T  {profile.ct_value:.2e}")
        ct_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:11pt; color:{accent};")
        bot.addWidget(cat_lbl)
        bot.addWidget(wl_lbl)
        bot.addStretch(1)
        bot.addWidget(ct_lbl)
        root.addLayout(bot)

    def _refresh_style(self):
        from profiles.profiles import CATEGORY_ACCENTS, CATEGORY_COLORS
        accent = CATEGORY_ACCENTS.get(self._profile.category, "#00d4aa")
        bg     = CATEGORY_COLORS.get(self._profile.category, "#1a1a1a")
        if self._selected:
            self.setStyleSheet(
                f"_ProfileCard{{background:{bg}; "
                f"border:2px solid {accent}; border-radius:7px;}}")
        else:
            self.setStyleSheet(
                "_ProfileCard{background:#181818; border:1px solid #242424;"
                " border-radius:7px;}"
                f"_ProfileCard:hover{{background:{bg}22; border-color:#333;}}")

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)


class _ProfileRow(QFrame):
    """Compact list row for list-view mode."""
    clicked = pyqtSignal(str)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.uid      = profile.uid
        self._profile = profile
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(52)
        self._refresh_style()

        from profiles.profiles import CATEGORY_ACCENTS
        accent = CATEGORY_ACCENTS.get(profile.category, "#00d4aa")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 14, 0)
        lay.setSpacing(10)

        stripe = QFrame()
        stripe.setFixedWidth(3)
        stripe.setStyleSheet(f"background:{accent}; border-radius:1px;")
        lay.addWidget(stripe)

        name_lbl = QLabel(profile.name)
        name_lbl.setStyleSheet("font-size:14pt; font-weight:bold; color:#ddd;")
        name_lbl.setMinimumWidth(160)
        lay.addWidget(name_lbl)

        cat_lbl = QLabel(profile.category)
        cat_lbl.setStyleSheet(f"font-size:12pt; color:{accent}88;")
        cat_lbl.setFixedWidth(160)
        lay.addWidget(cat_lbl)

        wl_lbl = QLabel(f"{profile.wavelength_nm} nm")
        wl_lbl.setStyleSheet("font-size:12pt; color:#505050;")
        wl_lbl.setFixedWidth(60)
        lay.addWidget(wl_lbl)

        desc = (profile.description[:70] + "…"
                if len(profile.description) > 70 else profile.description)
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("font-size:12pt; color:#484848;")
        lay.addWidget(desc_lbl, 1)

        ct_lbl = QLabel(f"C_T  {profile.ct_value:.2e}")
        ct_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:12pt; color:{accent};")
        ct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(ct_lbl)

    def _refresh_style(self):
        from profiles.profiles import CATEGORY_ACCENTS, CATEGORY_COLORS
        accent = CATEGORY_ACCENTS.get(self._profile.category, "#00d4aa")
        bg     = CATEGORY_COLORS.get(self._profile.category, "#1a1a1a")
        if self._selected:
            self.setStyleSheet(
                f"_ProfileRow{{background:{bg}; "
                f"border:2px solid {accent}; border-radius:4px;}}")
        else:
            self.setStyleSheet(
                "_ProfileRow{background:#181818; border:1px solid #242424;"
                " border-radius:4px;}"
                f"_ProfileRow:hover{{background:{bg}22; border-color:#333;}}")

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)


class Step1Profile(QWidget):
    """Step 1 — Material profile picker with card/list view toggle."""

    profile_selected = pyqtSignal(object)
    _VIEW_CARD = "card"
    _VIEW_LIST = "list"

    def __init__(self, profile_manager):
        super().__init__()
        self._mgr      = profile_manager
        self._widgets  = {}   # uid → card or row widget
        self._selected = None
        self._view     = self._VIEW_CARD
        self._cols     = 3
        self._active_filter = "All"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        # Title row  +  view-toggle buttons
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("Select a Material Profile")
        title.setStyleSheet("font-size:22pt; font-weight:bold; color:#ccc;")
        title_row.addWidget(title, 1)

        _btn_ss = """
            QPushButton {
                background:#1a1a1a; color:#555;
                border:1px solid #2a2a2a; border-radius:5px;
                font-size:16pt; padding:0 8px;
            }
            QPushButton:checked { background:#162030; color:#4e73df; border-color:#4e73df66; }
            QPushButton:hover   { border-color:#444; color:#888; }
        """
        self._card_btn = QPushButton("⊞")
        self._list_btn = QPushButton("≡")
        for b in (self._card_btn, self._list_btn):
            b.setCheckable(True)
            b.setFixedSize(36, 30)
            b.setStyleSheet(_btn_ss)
        self._card_btn.setChecked(True)
        self._card_btn.setToolTip("Card view")
        self._list_btn.setToolTip("List view")
        self._card_btn.clicked.connect(lambda: self._set_view(self._VIEW_CARD))
        self._list_btn.clicked.connect(lambda: self._set_view(self._VIEW_LIST))
        title_row.addWidget(self._card_btn)
        title_row.addWidget(self._list_btn)
        lay.addLayout(title_row)

        sub = QLabel("Choose the profile that matches the material on your sample.")
        sub.setStyleSheet("font-size:13pt; color:#555;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Filter chips
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        self._filter_btns = {}
        for f in ["All", "Semiconductor / IC", "Electronics / PCB", "Automotive / EV"]:
            b = QPushButton(f)
            b.setCheckable(True)
            b.setChecked(f == "All")
            b.setFixedHeight(28)
            b.setStyleSheet("""
                QPushButton {
                    background:#1a1a1a; color:#555;
                    border:1px solid #2a2a2a; border-radius:4px;
                    padding:0 12px; font-size:12pt;
                }
                QPushButton:checked { background:#0d2a1a; color:#00d4aa; border-color:#00d4aa44; }
                QPushButton:hover   { border-color:#333; color:#888; }
            """)
            b.clicked.connect(lambda _, fv=f: self._filter(fv))
            chip_row.addWidget(b)
            self._filter_btns[f] = b
        chip_row.addStretch()
        lay.addLayout(chip_row)

        # Scrollable content area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea{border:none; background:#111;}"
            "QScrollBar:vertical{background:#111; width:6px;}"
            "QScrollBar::handle:vertical{background:#2a2a2a; border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        lay.addWidget(self._scroll, 1)

        self._populate()

    # ── View switching ──────────────────────────────────────────────

    def _set_view(self, view: str):
        self._view = view
        self._card_btn.setChecked(view == self._VIEW_CARD)
        self._list_btn.setChecked(view == self._VIEW_LIST)
        self._populate()

    def _cols_for_width(self) -> int:
        """Responsive: 1 col <480, 2 col <760, 3 col <1100, 4+ col wider."""
        w = self._scroll.width()
        if w < 480:  return 1
        if w < 760:  return 2
        if w < 1100: return 3
        return 4

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view == self._VIEW_CARD:
            new_cols = self._cols_for_width()
            if new_cols != self._cols:
                self._cols = new_cols
                self._populate()

    # ── Population ──────────────────────────────────────────────────

    def _populate(self):
        # Destroy old container
        old = self._scroll.takeWidget()
        if old:
            old.deleteLater()
        self._widgets.clear()

        profiles = list(self._mgr.all())

        if self._view == self._VIEW_CARD:
            self._cols = self._cols_for_width()
            container = QWidget()
            container.setStyleSheet("background:#111;")
            grid = QGridLayout(container)
            grid.setSpacing(10)
            grid.setContentsMargins(4, 6, 4, 6)
            for i, p in enumerate(profiles):
                card = _ProfileCard(p)
                card.setMinimumHeight(120)
                card.clicked.connect(self._on_select)
                grid.addWidget(card, i // self._cols, i % self._cols)
                self._widgets[p.uid] = card
                if p.uid == self._selected:
                    card.set_selected(True)
            total_rows = (len(profiles) + self._cols - 1) // self._cols
            grid.setRowStretch(total_rows, 1)
            for col in range(self._cols):
                grid.setColumnStretch(col, 1)
        else:
            container = QWidget()
            container.setStyleSheet("background:#111;")
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(4, 4, 4, 4)
            vbox.setSpacing(3)
            for p in profiles:
                row = _ProfileRow(p)
                row.clicked.connect(self._on_select)
                vbox.addWidget(row)
                self._widgets[p.uid] = row
                if p.uid == self._selected:
                    row.set_selected(True)
            vbox.addStretch(1)

        self._scroll.setWidget(container)
        self._apply_filter()

    def _apply_filter(self):
        f = self._active_filter
        for uid, w in self._widgets.items():
            p = self._mgr.get(uid)
            show = (p is not None) and (
                f == "All" or f in (p.industry_tags or [p.category]))
            w.setVisible(show)

    def _filter(self, f: str):
        self._active_filter = f
        for k, b in self._filter_btns.items():
            b.setChecked(k == f)
        self._apply_filter()

    def _on_select(self, uid: str):
        # Deselect previous
        if self._selected and self._selected in self._widgets:
            self._widgets[self._selected].set_selected(False)
        self._selected = uid
        self._widgets[uid].set_selected(True)
        p = self._mgr.get(uid)
        if p:
            self.profile_selected.emit(p)

    def refresh(self):
        self._populate()

# ------------------------------------------------------------------ #
#  Step 2 — Focus                                                     #
# ------------------------------------------------------------------ #

class Step2Focus(QWidget):
    """Step 2 — live camera preview, autofocus, and manual Z control."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(14)

        title = QLabel("Focus on Your Sample")
        title.setStyleSheet("font-size:24pt; font-weight:bold; color:#ccc;")
        sub = QLabel(
            "Use the camera preview to position and focus on your device. "
            "Auto-Focus works best on samples with visible surface features. "
            "Use the manual controls for uniform or low-contrast surfaces.")
        sub.setStyleSheet("font-size:14pt; color:#555;")
        sub.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(sub)

        # ---- Main content: feed + right-side controls ----
        content = QHBoxLayout()
        content.setSpacing(12)

        # Live feed
        self._feed = QLabel()
        self._feed.setMinimumHeight(100)
        self._feed.setAlignment(Qt.AlignCenter)
        self._feed.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._feed.setStyleSheet(
            "background:#0d0d0d; border:1px solid #222; border-radius:4px;"
            "color:#333; font-size:18pt;")
        self._feed.setText("Camera initialising…")
        content.addWidget(self._feed, 1)

        # Right panel — focus controls
        right = QWidget()
        right.setFixedWidth(200)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        # Auto-Focus section
        af_box = QFrame()
        af_box.setStyleSheet(
            "QFrame{background:#141414; border:1px solid #222;"
            " border-radius:5px; padding:4px;}")
        afl = QVBoxLayout(af_box)
        afl.setSpacing(6)
        af_title = QLabel("AUTO-FOCUS")
        af_title.setStyleSheet(
            "font-size:12pt; letter-spacing:1.5px; color:#444;")
        self._af_btn = QPushButton("⚡  Auto-Focus")
        self._af_btn.setObjectName("primary")
        self._af_btn.setFixedHeight(34)
        self._af_btn.clicked.connect(self._run_autofocus)
        self._focus_metric = QLabel("Score: —")
        self._focus_metric.setStyleSheet(
            "font-family:Menlo,monospace; font-size:12pt; color:#555;"
            " padding-left:2px;")
        afl.addWidget(af_title)
        afl.addWidget(self._af_btn)
        afl.addWidget(self._focus_metric)
        rl.addWidget(af_box)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#222;")
        rl.addWidget(sep)

        # Manual Z section
        man_box = QFrame()
        man_box.setStyleSheet(
            "QFrame{background:#141414; border:1px solid #222;"
            " border-radius:5px; padding:4px;}")
        manl = QVBoxLayout(man_box)
        manl.setSpacing(6)

        man_title = QLabel("MANUAL FOCUS")
        man_title.setStyleSheet(
            "font-size:12pt; letter-spacing:1.5px; color:#444;")
        manl.addWidget(man_title)

        # Step size selector
        step_row = QHBoxLayout()
        step_lbl = QLabel("Step")
        step_lbl.setStyleSheet("font-size:14pt; color:#555;")
        self._step_combo = QComboBox()
        for label in ["0.5 µm", "1 µm", "2 µm", "5 µm",
                      "10 µm", "25 µm", "50 µm", "100 µm"]:
            self._step_combo.addItem(label)
        self._step_combo.setCurrentIndex(2)   # default: 2 µm
        self._step_combo.setFixedHeight(26)
        self._step_values = [0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0]
        step_row.addWidget(step_lbl)
        step_row.addWidget(self._step_combo, 1)
        manl.addLayout(step_row)

        # Up / Down buttons
        ud_row = QHBoxLayout()
        ud_row.setSpacing(6)
        self._z_up_btn   = QPushButton("▲  Up")
        self._z_down_btn = QPushButton("▼  Down")
        for b in [self._z_up_btn, self._z_down_btn]:
            b.setFixedHeight(34)
            ud_row.addWidget(b)
        self._z_up_btn.clicked.connect(lambda: self._move_z(+1))
        self._z_down_btn.clicked.connect(lambda: self._move_z(-1))
        manl.addLayout(ud_row)

        # Fine nudge row (single-step tap buttons)
        nudge_row = QHBoxLayout()
        nudge_row.setSpacing(4)
        self._z_up_fine   = QPushButton("↑")
        self._z_down_fine = QPushButton("↓")
        for b, sign in [(self._z_up_fine, +1), (self._z_down_fine, -1)]:
            b.setFixedSize(30, 24)
            b.setStyleSheet(
                "QPushButton{background:#1a1a1a; color:#555; border:1px solid #2a2a2a;"
                " border-radius:3px; font-size:14pt;}"
                "QPushButton:hover{color:#aaa; border-color:#444;}")
            _sign = sign
            b.clicked.connect(lambda _, s=_sign: self._move_z(s, fine=True))
        nudge_lbl = QLabel("0.1 µm nudge")
        nudge_lbl.setStyleSheet("font-size:14pt; color:#333;")
        nudge_row.addWidget(self._z_up_fine)
        nudge_row.addWidget(nudge_lbl, 1)
        nudge_row.addWidget(self._z_down_fine)
        manl.addLayout(nudge_row)

        # Current Z readout
        self._z_pos_lbl = QLabel("Z: —")
        self._z_pos_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:12pt; color:#555;"
            " padding-left:2px;")
        manl.addWidget(self._z_pos_lbl)

        rl.addWidget(man_box)
        rl.addStretch()
        content.addWidget(right, 0)
        lay.addLayout(content, 1)

        # Poll timer for live frames + Z position
        self._timer = QTimer()
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._poll_frame)

    def start_preview(self):
        self._timer.start()
        self._update_z_readout()

    def stop_preview(self):
        self._timer.stop()

    # ---------------------------------------------------------------- #
    #  Live feed                                                        #
    # ---------------------------------------------------------------- #

    def _poll_frame(self):
        try:
            import main_app as _ma
            if _ma.cam is None:
                return
            frame = _ma.cam.grab(timeout_ms=50)
            if frame is None:
                return
            d = frame.data
            normed = ((d.astype(np.float32) - d.min()) /
                      (d.max() - d.min() + 1e-9) * 255).astype(np.uint8)
            h, w = normed.shape
            qi = QImage(normed.tobytes(), w, h, w, QImage.Format_Grayscale8)
            pix = QPixmap.fromImage(qi).scaled(
                self._feed.width() - 4,
                self._feed.height() - 4,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
            self._feed.setPixmap(pix)
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Auto-focus                                                       #
    # ---------------------------------------------------------------- #

    def _run_autofocus(self):
        self._af_btn.setEnabled(False)
        self._af_btn.setText("Focusing…")
        try:
            import main_app as _ma
            if _ma.autofocus:
                _ma.autofocus.run_async(
                    cam=_ma.cam,
                    on_complete=self._on_af_done)
                return
        except Exception:
            pass
        self._af_btn.setEnabled(True)
        self._af_btn.setText("⚡  Auto-Focus")

    def _on_af_done(self, result):
        self._af_btn.setEnabled(True)
        self._af_btn.setText("⚡  Auto-Focus")
        if result and hasattr(result, "focus_score"):
            score = result.focus_score
            ok    = getattr(result, "converged", True)
            self._focus_metric.setText(f"Score: {score:.1f}")
            self._focus_metric.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:12pt;"
                f" color:{'#00d4aa' if ok else '#ff8800'};"
                f" padding-left:2px;")
        self._update_z_readout()

    # ---------------------------------------------------------------- #
    #  Manual Z                                                         #
    # ---------------------------------------------------------------- #

    def _step_um(self) -> float:
        idx = self._step_combo.currentIndex()
        return self._step_values[idx] if idx < len(self._step_values) else 2.0

    def _move_z(self, direction: int, fine: bool = False):
        """
        Move the Z stage by ±step_um (or ±0.1 µm for fine nudge).
        direction: +1 = up (away from sample), -1 = down (toward sample).
        """
        dist = 0.1 if fine else self._step_um()
        try:
            import main_app as _ma
            if _ma.stage is None:
                return
            import threading
            def _run():
                try:
                    _ma.stage.move_z(dist * direction)
                    QTimer.singleShot(120, self._update_z_readout)
                except Exception:
                    pass
            threading.Thread(target=_run, daemon=True).start()
        except Exception:
            pass

    def _update_z_readout(self):
        try:
            import main_app as _ma
            if _ma.stage is None:
                return
            pos = _ma.stage.get_position()
            z   = getattr(pos, "z_um", None)
            if z is not None:
                self._z_pos_lbl.setText(f"Z: {z:.2f} µm")
        except Exception:
            pass

# ------------------------------------------------------------------ #
#  Step 3 — Acquire                                                   #
# ------------------------------------------------------------------ #

class Step3Acquire(QWidget):
    """Step 3 — single-button acquisition with progress."""

    acquire_requested = pyqtSignal()
    acquire_complete  = pyqtSignal(object)   # AcquisitionResult

    def __init__(self):
        super().__init__()
        self._running = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(16)

        title = QLabel("Acquire Measurement")
        title.setStyleSheet("font-size:24pt; font-weight:bold; color:#ccc;")
        sub = QLabel(
            "Everything is configured. Press Acquire to capture the "
            "thermoreflectance measurement. This will take a few seconds.")
        sub.setStyleSheet("font-size:14pt; color:#555;")
        sub.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(sub)

        lay.addStretch()

        # Big acquire button
        self._acq_btn = QPushButton("▶  Acquire")
        self._acq_btn.setFixedHeight(64)
        self._acq_btn.setStyleSheet("""
            QPushButton {
                background:#0d2a1a; color:#00d4aa;
                border:2px solid #00d4aa44;
                border-radius:6px;
                font-size:25pt; font-weight:bold;
                letter-spacing:2px;
            }
            QPushButton:hover {
                background:#0d3a22; border-color:#00d4aa88;
            }
            QPushButton:disabled {
                background:#111; color:#333; border-color:#222;
            }
        """)
        lay.addWidget(self._acq_btn)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        lay.addWidget(self._status)

        # Profile info summary
        self._profile_info = QLabel("")
        self._profile_info.setAlignment(Qt.AlignCenter)
        self._profile_info.setStyleSheet(
            "font-size:14pt; color:#444; font-style:italic;")
        self._profile_info.setWordWrap(True)
        lay.addWidget(self._profile_info)

        lay.addStretch()

        self._acq_btn.clicked.connect(self._start_acquire)

    def set_profile(self, profile):
        if profile:
            self._profile_info.setText(
                f"{profile.name}  ·  "
                f"{profile.n_frames} frames  ·  "
                f"exposure {profile.exposure_us:.0f} µs  ·  "
                f"gain {profile.gain_db:.1f} dB")

    def _start_acquire(self):
        self._acq_btn.setEnabled(False)
        self._acq_btn.setText("Acquiring…")
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status.setText("Starting acquisition…")
        self._running = True
        self.acquire_requested.emit()

    def update_progress(self, pct: int, msg: str = ""):
        self._progress.setValue(pct)
        if msg:
            self._status.setText(msg)

    def on_complete(self, result):
        self._running = False
        self._acq_btn.setEnabled(True)
        self._acq_btn.setText("▶  Acquire")
        self._progress.setValue(100)
        self._status.setText("Complete.")
        self.acquire_complete.emit(result)

    def on_error(self, msg: str):
        self._running = False
        self._acq_btn.setEnabled(True)
        self._acq_btn.setText("▶  Acquire")
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._status.setText(f"Error: {msg}")
        self._status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#ff4444;")


# ------------------------------------------------------------------ #
#  Step 4 — Results                                                   #
# ------------------------------------------------------------------ #

class _VerdictBig(QWidget):
    """Large colour-coded verdict block for the results step."""

    _STYLES = {
        "PASS":    ("#00d479", "#0a2018", "No thermal anomalies detected."),
        "WARNING": ("#ffb300", "#221800", "Thermal anomalies within warning range."),
        "FAIL":    ("#ff3b3b", "#200808", "Thermal anomalies exceed fail threshold."),
        "NONE":    ("#333333", "#111111", ""),
    }

    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._outer = QWidget()
        ol = QVBoxLayout(self._outer)
        ol.setContentsMargins(24, 0, 24, 0)
        ol.setAlignment(Qt.AlignVCenter)
        self._verdict_lbl = QLabel("—")
        self._verdict_lbl.setStyleSheet(
            "font-size:50pt; font-weight:bold; font-family:Menlo,monospace;")
        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet("font-size:15pt;")
        ol.addWidget(self._verdict_lbl)
        ol.addWidget(self._sub_lbl)
        lay.addWidget(self._outer)

    def set_verdict(self, verdict: str, hotspots: int = 0, peak: float = 0.0):
        fg, bg, default_sub = self._STYLES.get(verdict, self._STYLES["NONE"])
        self._outer.setStyleSheet(
            f"background:{bg}; border-radius:6px;")
        self._verdict_lbl.setText(verdict)
        self._verdict_lbl.setStyleSheet(
            f"font-size:50pt; font-weight:bold; "
            f"font-family:Menlo,monospace; color:{fg};")
        if verdict in ("WARNING", "FAIL") and hotspots > 0:
            hs = "hotspot" if hotspots == 1 else "hotspots"
            sub = f"{hotspots} {hs} detected  ·  peak {peak:.1f} °C"
        else:
            sub = default_sub
        self._sub_lbl.setText(sub)
        self._sub_lbl.setStyleSheet(f"font-size:15pt; color:{fg}99;")


class Step4Results(QWidget):
    """Step 4 — verdict, overlay, export."""

    new_measurement = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._result   = None
        self._overlay  = None   # QPixmap

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(12)

        title = QLabel("Measurement Results")
        title.setStyleSheet(
            "font-size:24pt; font-weight:bold; color:#ccc;")
        lay.addWidget(title)

        # Verdict
        self._verdict_block = _VerdictBig()
        lay.addWidget(self._verdict_block)

        # Content: overlay + stats side by side
        content = QHBoxLayout()
        content.setSpacing(16)

        # Overlay image
        self._overlay_lbl = QLabel()
        self._overlay_lbl.setMinimumSize(200, 140)
        self._overlay_lbl.setAlignment(Qt.AlignCenter)
        self._overlay_lbl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._overlay_lbl.setStyleSheet(
            "background:#0d0d0d; border:1px solid #222; border-radius:4px;")
        content.addWidget(self._overlay_lbl, 2)

        # Stats
        stats_w = QWidget()
        stats_w.setFixedWidth(220)
        sl = QVBoxLayout(stats_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)

        stats_box = QGroupBox("Summary")
        sg = QGridLayout(stats_box)
        sg.setSpacing(5)
        self._stat_v = {}
        for r, (key, lbl) in enumerate([
            ("hotspots",  "Hotspots"),
            ("peak",      "Peak ΔT"),
            ("area",      "Hotspot area"),
            ("threshold", "Threshold"),
        ]):
            sg.addWidget(self._sub(lbl), r, 0)
            v = QLabel("—")
            v.setAlignment(Qt.AlignRight)
            v.setStyleSheet(
                "font-family:Menlo,monospace; font-size:14pt; color:#aaa;")
            sg.addWidget(v, r, 1)
            self._stat_v[key] = v
        sl.addWidget(stats_box)
        sl.addStretch()
        content.addWidget(stats_w, 0)

        lay.addLayout(content, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._new_btn     = QPushButton("↩  New Measurement")
        self._export_btn  = QPushButton("📄  Export Report")
        self._save_btn    = QPushButton("💾  Save PNG")
        self._new_btn.setObjectName("primary")
        for b in [self._new_btn, self._export_btn, self._save_btn]:
            b.setFixedHeight(34)
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._new_btn.clicked.connect(self.new_measurement.emit)
        self._export_btn.clicked.connect(self._export_report)
        self._save_btn.clicked.connect(self._save_png)

    def update_result(self, analysis_result, acq_result=None):
        self._result   = analysis_result
        self._acq_result = acq_result

        self._verdict_block.set_verdict(
            analysis_result.verdict,
            analysis_result.n_hotspots,
            analysis_result.max_peak_k)

        # Overlay
        if analysis_result.overlay_rgb is not None:
            rgb = analysis_result.overlay_rgb
            h, w = rgb.shape[:2]
            qi = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
            self._overlay = QPixmap.fromImage(qi)
            self._resize_overlay()

        # Stats
        r = analysis_result
        self._stat_v["hotspots"].setText(str(r.n_hotspots))
        self._stat_v["peak"].setText(
            f"{r.max_peak_k:.2f} °C" if r.n_hotspots else "—")
        self._stat_v["area"].setText(f"{r.area_fraction*100:.2f} %")
        self._stat_v["threshold"].setText(f"{r.threshold_k:.1f} °C")

        colors = {"PASS": "#00d479", "WARNING": "#ffb300", "FAIL": "#ff3b3b"}
        c = colors.get(r.verdict, "#aaa")
        for k in ["hotspots", "peak", "area"]:
            self._stat_v[k].setStyleSheet(
                f"font-family:Menlo,monospace; font-size:14pt; color:{c};")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_overlay()

    def _resize_overlay(self):
        if self._overlay:
            scaled = self._overlay.scaled(
                self._overlay_lbl.width()  - 4,
                self._overlay_lbl.height() - 4,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._overlay_lbl.setPixmap(scaled)

    def _export_report(self):
        try:
            import main_app as _ma
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Report", "report.pdf",
                "PDF files (*.pdf)")
            if not path:
                return
            out_dir  = str(path.rsplit("/", 1)[0])
            from acquisition.report import generate_report
            session  = getattr(_ma, "_last_session", None)
            cal      = getattr(_ma, "active_calibration", None)
            if session is None:
                QMessageBox.warning(
                    self, "No Session",
                    "No session available. Complete an acquisition first.")
                return
            pdf = generate_report(
                session, out_dir, cal,
                analysis=self._result)
            QMessageBox.information(
                self, "Report Saved", f"Saved to:\n{pdf}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _save_png(self):
        if not self._overlay:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", "result.png",
            "PNG images (*.png)")
        if path:
            self._overlay.save(path)

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l


# ------------------------------------------------------------------ #
#  Main wizard widget                                                  #
# ------------------------------------------------------------------ #

class StandardWizard(QWidget):
    """
    The full Standard mode wizard.
    Embeds all four steps and the step-progress bar.
    Communicates with the rest of the app through main_app globals.
    """

    switch_to_advanced = pyqtSignal()

    def __init__(self, profile_manager):
        super().__init__()
        self._mgr            = profile_manager
        self._current_step   = 0
        self._active_profile = None
        self._acq_result     = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Step bar
        self._step_bar = WizardStepBar()
        root.addWidget(self._step_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1e1e1e;")
        root.addWidget(sep)

        # Body: sidebar panel + main content side by side
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ── Left panel — matches Advanced sidebar style ──────────────
        side = QWidget()
        side.setFixedWidth(200)
        side.setStyleSheet("background:#1e2337; border-right:1px solid #2a3249;")
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(0)

        # App name header (mirrors sidebar logo header)
        hdr = QWidget()
        hdr.setStyleSheet("background:#1a1f33; border-bottom:1px solid #2a3249;")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(18, 14, 18, 14)
        hdr_lay.setSpacing(2)
        app_lbl = QLabel("SanjINSIGHT")
        app_lbl.setStyleSheet(
            "color:#ffffff; font-size:17pt; font-weight:700; "
            "font-family:'Segoe UI',Arial,sans-serif; background:transparent; border:none;")
        hdr_lay.addWidget(app_lbl)
        side_lay.addWidget(hdr)

        # Step indicators in the sidebar
        _ACCENT  = "#4e73df"
        _BG_ACT  = "#2a3551"
        _TXT_DIM = "#8892a4"
        _TXT_NRM = "#c8d0e0"
        steps_data = [
            ("①", "Profile",  "Select material"),
            ("②", "Focus",    "Set focus & ROI"),
            ("③", "Acquire",  "Run measurement"),
            ("④", "Results",  "Review & export"),
        ]
        self._side_steps = []
        for idx, (icon, label, hint) in enumerate(steps_data):
            btn = QWidget()
            btn.setFixedHeight(58)
            btn.setStyleSheet("background:transparent;")
            bl = QHBoxLayout(btn)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(0)

            # Accent bar (shown when active)
            bar = QFrame()
            bar.setFixedWidth(3)
            bar.setStyleSheet(f"background:transparent;")
            bl.addWidget(bar)

            inner = QVBoxLayout()
            inner.setContentsMargins(14, 6, 12, 6)
            inner.setSpacing(1)
            name_l = QLabel(f"{icon}  {label}")
            name_l.setStyleSheet(
                f"font-size:13pt; font-weight:600; color:{_TXT_DIM}; background:transparent;")
            hint_l = QLabel(hint)
            hint_l.setStyleSheet(
                f"font-size:10pt; color:#4a5568; background:transparent;")
            inner.addWidget(name_l)
            inner.addWidget(hint_l)
            bl.addLayout(inner)

            btn._bar   = bar
            btn._name  = name_l
            btn._hint  = hint_l
            side_lay.addWidget(btn)
            self._side_steps.append(btn)

        side_lay.addStretch(1)
        body.addWidget(side)

        # ── Main content (stack) ────────────────────────────────────
        # Pages — each step is wrapped in a QScrollArea so the wizard
        # fits on small screens (e.g. 14" MacBook) without clipping
        self._stack = QStackedWidget()
        self._step1 = Step1Profile(profile_manager)
        self._step2 = Step2Focus()
        self._step3 = Step3Acquire()
        self._step4 = Step4Results()

        def _wrap(w):
            sa = QScrollArea()
            sa.setWidget(w)
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sa.setStyleSheet("QScrollArea{background:#111; border:none;}"
                             "QScrollBar:vertical{background:#111; width:6px; margin:0;}"
                             "QScrollBar::handle:vertical{background:#2a2a2a; border-radius:3px;}"
                             "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
            return sa

        self._stack.addWidget(_wrap(self._step1))
        self._stack.addWidget(_wrap(self._step2))
        self._stack.addWidget(_wrap(self._step3))
        self._stack.addWidget(_wrap(self._step4))
        body.addWidget(self._stack, 1)

        root.addLayout(body, 1)

        # Navigation bar
        nav = QWidget()
        nav.setMinimumHeight(40)
        nav.setMaximumHeight(52)
        nav.setStyleSheet(
            "background:#111; border-top:1px solid #1e1e1e;")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(16, 0, 16, 0)
        nl.setSpacing(10)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedSize(100, 34)
        self._back_btn.setEnabled(False)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("primary")
        self._next_btn.setFixedSize(120, 34)

        self._step_hint = QLabel("")
        self._step_hint.setStyleSheet(
            "font-size:14pt; color:#444; font-style:italic;")

        nl.addWidget(self._back_btn)
        nl.addWidget(self._step_hint, 1)
        nl.addWidget(self._next_btn)
        root.addWidget(nav)

        # Signals
        self._step1.profile_selected.connect(self._on_profile_selected)
        self._step3.acquire_requested.connect(self._start_acquisition)
        self._step3.acquire_complete.connect(self._on_acq_complete)
        self._step4.new_measurement.connect(self._restart)

        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)

        self._go_to(0)

    # ---------------------------------------------------------------- #
    #  Navigation                                                       #
    # ---------------------------------------------------------------- #

    def _update_side_steps(self, active: int):
        """Highlight the active step in the left sidebar panel."""
        _ACCENT  = "#4e73df"
        _BG_ACT  = "#2a3551"
        _TXT_WH  = "#ffffff"
        _TXT_DIM = "#8892a4"
        for i, btn in enumerate(self._side_steps):
            is_active = (i == active)
            is_done   = (i < active)
            btn._bar.setStyleSheet(
                f"background:{'#4e73df' if is_active else 'transparent'};")
            btn.setStyleSheet(
                f"background:{'#2a3551' if is_active else 'transparent'};")
            if is_active:
                btn._name.setStyleSheet(
                    "font-size:13pt; font-weight:700; color:#ffffff; background:transparent;")
                btn._hint.setStyleSheet(
                    "font-size:10pt; color:#8892a4; background:transparent;")
            elif is_done:
                btn._name.setStyleSheet(
                    "font-size:13pt; font-weight:600; color:#00d4aa; background:transparent;")
                btn._hint.setStyleSheet(
                    "font-size:10pt; color:#4a5568; background:transparent;")
            else:
                btn._name.setStyleSheet(
                    "font-size:13pt; font-weight:600; color:#8892a4; background:transparent;")
                btn._hint.setStyleSheet(
                    "font-size:10pt; color:#4a5568; background:transparent;")

    def _go_to(self, step: int):
        # Stop focus preview if leaving step 2
        if self._current_step == 1:
            self._step2.stop_preview()

        self._current_step = step
        self._stack.setCurrentIndex(step)
        self._step_bar.set_step(step)
        self._update_side_steps(step)
        self._back_btn.setEnabled(step > 0)

        hints = [
            "Select a profile to continue.",
            "Position and focus your sample, then click Next.",
            "Press Acquire when ready.",
            "Review your results.",
        ]
        self._step_hint.setText(hints[step])

        # Step-specific setup
        if step == 0:
            self._next_btn.setText("Next →")
            self._next_btn.setEnabled(self._active_profile is not None)
        elif step == 1:
            self._next_btn.setText("Next →")
            self._next_btn.setEnabled(True)
            self._step2.start_preview()
        elif step == 2:
            self._next_btn.setVisible(False)
            self._step3.set_profile(self._active_profile)
        elif step == 3:
            self._next_btn.setVisible(False)

    def _go_next(self):
        if self._current_step < 3:
            self._go_to(self._current_step + 1)

    def _go_back(self):
        if self._current_step > 0:
            self._next_btn.setVisible(True)
            self._go_to(self._current_step - 1)

    def _restart(self):
        self._acq_result = None
        self._next_btn.setVisible(True)
        self._go_to(0)

    # ---------------------------------------------------------------- #
    #  Profile selection                                                #
    # ---------------------------------------------------------------- #

    def _on_profile_selected(self, profile):
        self._active_profile = profile
        self._next_btn.setEnabled(True)

        # Apply profile to the system immediately
        try:
            import main_app as _ma
            h, w = 256, 320
            if _ma.cam:
                try:
                    st = _ma.cam.get_status()
                    h, w = st.height or 256, st.width or 320
                except Exception:
                    pass
            _ma.active_calibration = profile.make_calibration(h, w)
            _ma.active_profile     = profile
            _ma.signals.profile_applied.emit(profile)
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Acquisition                                                      #
    # ---------------------------------------------------------------- #

    def _start_acquisition(self):
        try:
            import main_app as _ma
            n_frames = (self._active_profile.n_frames
                        if self._active_profile else 64)

            def _progress_cb(prog):
                pct = int(prog.frame_index / max(prog.total_frames, 1) * 100)
                _ma.signals.acq_progress.emit(prog)
                # Update step 3 directly on main thread via timer
                QTimer.singleShot(0, lambda: self._step3.update_progress(
                    pct, f"Frame {prog.frame_index} / {prog.total_frames}"))

            def _complete_cb(result):
                _ma.signals.acq_complete.emit(result)
                QTimer.singleShot(0, lambda: self._step3.on_complete(result))

            import threading
            def _run():
                try:
                    _ma.app_state.pipeline.start(
                        n_frames      = n_frames,
                        on_progress   = _progress_cb,
                        on_complete   = _complete_cb)
                except Exception as e:
                    QTimer.singleShot(
                        0, lambda: self._step3.on_error(str(e)))

            threading.Thread(target=_run, daemon=True).start()

        except Exception as e:
            self._step3.on_error(str(e))

    def _on_acq_complete(self, result):
        self._acq_result = result

        # Run analysis — use profile's expected ΔT range as threshold
        try:
            import main_app as _ma
            from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

            # Inherit threshold from the active profile's expected ΔT range
            profile = self._active_profile
            threshold_k = (profile.dt_range_k * 0.5
                           if profile and profile.dt_range_k > 0
                           else 5.0)

            cfg    = AnalysisConfig(threshold_k=threshold_k)
            engine = ThermalAnalysisEngine(cfg)
            dt_map  = getattr(result, "delta_t",        None)
            drr_map = getattr(result, "delta_r_over_r", None)
            analysis = engine.run(dt_map=dt_map, drr_map=drr_map)
            _ma.app_state.active_analysis = analysis
            self._step4.update_result(analysis, result)
            self._go_to(3)
        except Exception as e:
            self._step3.on_error(f"Analysis failed: {e}")
