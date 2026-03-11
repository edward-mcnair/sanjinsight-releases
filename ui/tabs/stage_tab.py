"""
ui/tabs/stage_tab.py

StageTab — XYZ stage control with absolute move, relative jog, and home/stop buttons.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QComboBox, QStackedWidget)
from PyQt5.QtCore    import Qt, pyqtSignal

from hardware.app_state import app_state
from ui.theme import FONT, PALETTE
from ui.icons import set_btn_icon


class StageTab(QWidget):
    open_device_manager = pyqtSignal()

    def __init__(self, hw_service=None):
        super().__init__()
        self._hw = hw_service

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "Stage", "Zaber motion stage",
            "Connect the Zaber motion stage in Device Manager to enable controls."))

        # Page 1: full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self._stack.addWidget(controls)
        self._stack.setCurrentIndex(1)  # show controls by default

        # Position readouts
        pos_box = QGroupBox("Current Position")
        pl = QHBoxLayout(pos_box)
        self._x_w = self._readout("X",      "--", "#00d4aa")
        self._y_w = self._readout("Y",      "--", "#ffaa44")
        self._z_w = self._readout("Z",      "--", "#6699ff")
        self._st_w = self._readout("STATUS","UNKNOWN","#555")
        for w in [self._x_w, self._y_w, self._z_w, self._st_w]:
            pl.addWidget(w)
        root.addWidget(pos_box)

        # Absolute move
        abs_box = QGroupBox("Move To  (absolute μm)")
        al = QGridLayout(abs_box)
        al.setSpacing(8)

        self._ax = self._axis_spin("X", -50000, 50000)
        self._ay = self._axis_spin("Y", -50000, 50000)
        self._az = self._axis_spin("Z",      0, 25000)

        for col, (lbl, spin) in enumerate(
                [("X (μm)", self._ax), ("Y (μm)", self._ay),
                 ("Z (μm)", self._az)]):
            al.addWidget(QLabel(lbl), 0, col*2)
            al.addWidget(spin, 0, col*2+1)

        move_btn = QPushButton("Move To")
        move_btn.setObjectName("primary")
        move_btn.setFixedWidth(90)
        move_btn.clicked.connect(self._move_to)
        al.addWidget(move_btn, 0, 6)
        root.addWidget(abs_box)

        # Relative jog
        jog_box = QGroupBox("Jog  (relative μm)")
        jl = QGridLayout(jog_box)
        jl.setSpacing(6)

        # Step size selector
        jl.addWidget(QLabel("Step size:"), 0, 0)
        self._step_combo = QComboBox()
        for v in ["0.1", "1", "10", "100", "1000", "5000"]:
            self._step_combo.addItem(f"{v} μm", float(v))
        self._step_combo.setCurrentIndex(3)   # 100μm default
        self._step_combo.setFixedWidth(100)
        jl.addWidget(self._step_combo, 0, 1)

        # XY jog pad
        jl.addWidget(self._jog_pad(), 1, 0, 1, 3)

        # Z jog
        z_col = QVBoxLayout()
        z_col.setAlignment(Qt.AlignCenter)
        z_col.addWidget(QLabel("Z", alignment=Qt.AlignCenter))
        btn_zup  = QPushButton("▲")
        btn_zdn  = QPushButton("▼")
        for b in [btn_zup, btn_zdn]:
            b.setFixedSize(50, 36)
        btn_zup.clicked.connect(lambda: self._jog(z= self._step()))
        btn_zdn.clicked.connect(lambda: self._jog(z=-self._step()))
        z_col.addWidget(btn_zup)
        z_col.addWidget(btn_zdn)
        jl.addLayout(z_col, 1, 3)

        root.addWidget(jog_box)

        # Home + Stop row
        ctrl_row = QHBoxLayout()
        home_xyz = QPushButton("Home All")
        set_btn_icon(home_xyz, "fa5s.home")
        home_xy  = QPushButton("Home XY")
        set_btn_icon(home_xy, "fa5s.home")
        home_z   = QPushButton("Home Z")
        set_btn_icon(home_z, "fa5s.home")
        stop_btn = QPushButton("STOP")
        set_btn_icon(stop_btn, "fa5s.stop", "#ff6666")
        stop_btn.setObjectName("danger")
        for b in [home_xyz, home_xy, home_z]:
            b.setFixedWidth(110)
            ctrl_row.addWidget(b)
        ctrl_row.addStretch()
        stop_btn.setFixedWidth(110)
        ctrl_row.addWidget(stop_btn)

        home_xyz.clicked.connect(lambda: self._home("xyz"))
        home_xy.clicked.connect( lambda: self._home("xy"))
        home_z.clicked.connect(  lambda: self._home("z"))
        stop_btn.clicked.connect(self._stop)
        root.addLayout(ctrl_row)
        root.addStretch()

    # ── Empty state ───────────────────────────────────────────────────

    def _build_empty_state(self, title: str, device: str, tip: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        try:
            import qtawesome as qta
            icon_lbl = QLabel()
            icon_lbl.setPixmap(qta.icon("fa5s.unlink", color="#555").pixmap(64, 64))
        except Exception:
            icon_lbl = QLabel("⚡")
            icon_lbl.setStyleSheet("font-size: 48pt; color: #333;")
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(f"{title} Not Connected")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("font-size: 16pt; font-weight: bold; color: #888;")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("font-size: 12pt; color: #555;")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        btn.setStyleSheet("""
            QPushButton {
                background: #1a2a20; color: #00d4aa;
                border: 1px solid #00d4aa66; border-radius: 5px;
                font-size: 12pt; font-weight: 600;
            }
            QPushButton:hover { background: #1e3028; }
        """)
        btn.clicked.connect(self.open_device_manager)

        lay.addStretch()
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addWidget(tip_lbl)
        lay.addSpacing(8)
        lay.addWidget(btn, 0, Qt.AlignCenter)
        lay.addStretch()
        return w

    def set_hardware_available(self, available: bool) -> None:
        """Switch between empty state (page 0) and full controls (page 1)."""
        self._stack.setCurrentIndex(1 if available else 0)

    # ---------------------------------------------------------------- #

    def _readout(self, label, initial, color):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{color};")
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def _axis_spin(self, label, lo, hi):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(0.0)
        s.setDecimals(2)
        s.setSingleStep(1.0)
        s.setFixedWidth(110)
        return s

    def _jog_pad(self):
        """Build a directional XY jog pad."""
        pad = QWidget()
        g   = QGridLayout(pad)
        g.setSpacing(4)

        arrows = {
            (0, 1): ("▲",  lambda: self._jog(y= self._step())),
            (2, 1): ("▼",  lambda: self._jog(y=-self._step())),
            (1, 0): ("◀",  lambda: self._jog(x=-self._step())),
            (1, 2): ("▶",  lambda: self._jog(x= self._step())),
            (0, 0): ("↖",  lambda: self._jog(x=-self._step(), y= self._step())),
            (0, 2): ("↗",  lambda: self._jog(x= self._step(), y= self._step())),
            (2, 0): ("↙",  lambda: self._jog(x=-self._step(), y=-self._step())),
            (2, 2): ("↘",  lambda: self._jog(x= self._step(), y=-self._step())),
        }
        for (row, col), (symbol, fn) in arrows.items():
            b = QPushButton(symbol)
            b.setFixedSize(46, 40)
            b.setStyleSheet("font-size:22pt;")
            b.clicked.connect(fn)
            g.addWidget(b, row, col)

        return pad

    def _step(self) -> float:
        return self._step_combo.currentData()

    def _jog(self, x=0.0, y=0.0, z=0.0):
        if self._hw:
            self._hw.stage_move_by(x=x, y=y, z=z)
        else:
            stage = app_state.stage
            if stage:
                stage.move_by(x=x, y=y, z=z, wait=False)

    def _move_to(self):
        if self._hw:
            self._hw.stage_move_to(
                self._ax.value(), self._ay.value(), self._az.value())
        else:
            stage = app_state.stage
            if stage:
                stage.move_to(x=self._ax.value(), y=self._ay.value(),
                               z=self._az.value(), wait=False)

    def _home(self, axes: str):
        if self._hw:
            self._hw.stage_home(axes)
        else:
            stage = app_state.stage
            if stage:
                stage.home(axes)

    def _stop(self):
        if self._hw:
            self._hw.stage_stop()
        else:
            stage = app_state.stage
            if stage:
                stage.stop()

    def update_status(self, status):
        if status.error:
            self._st_w._val.setText("ERROR")
            self._st_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['danger']};")
            return

        p = status.position
        self._x_w._val.setText(f"{p.x:+.2f} μm")
        self._y_w._val.setText(f"{p.y:+.2f} μm")
        self._z_w._val.setText(f"{p.z:.2f} μm")

        # Update absolute move spinboxes to current position
        self._ax.setValue(p.x)
        self._ay.setValue(p.y)
        self._az.setValue(p.z)

        if status.moving:
            self._st_w._val.setText("MOVING ↔")
            self._st_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['warning']};")
        elif status.homed:
            self._st_w._val.setText("READY ✓")
            self._st_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['success']};")
        else:
            self._st_w._val.setText("NOT HOMED")
            self._st_w._val.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:{FONT['readoutLg']}pt; color:{PALETTE['textDim']};")
