"""
ui/tabs/prober_tab.py

ProberTab — MPI probe station chuck control panel.

Provides:
  • Live XYZ position readout (chuck in probe-station coordinates)
  • Wafer-map die grid — visual overview of the configured die array
    with the current die highlighted; click a die to step to it
  • Die stepping (col/row spinboxes + Step button)
  • Needle Contact / Lift controls
  • Absolute XYZ move and Home

The prober driver lives in app_state.prober (distinct from app_state.stage
which holds the microscope scan stage).  If no prober is connected, the
tab shows a "Not connected" placeholder.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QProgressBar, QSizePolicy, QMessageBox, QStackedWidget)
from PyQt5.QtCore import Qt, QTimer, QRect, QPoint, pyqtSignal
from PyQt5.QtGui  import (QPainter, QColor, QPen, QFont,
                           QBrush, QFontMetrics)

from hardware.app_state import app_state
from ui.theme      import FONT, PALETTE
from ui.font_utils import mono_font
from ui.icons import set_btn_icon, make_icon_label, IC


# ------------------------------------------------------------------ #
#  Wafer-map die grid widget                                          #
# ------------------------------------------------------------------ #

class DieGrid(QWidget):
    """
    Draws a rectangular grid of die cells (n_cols × n_rows).

    The current die is highlighted in accent colour.  Clicking a cell
    emits nothing — the parent calls step_to(col, row) via a callback
    stored in `on_die_clicked`.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumSize(180, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._n_cols:    int   = 0
        self._n_rows:    int   = 0
        self._cur_col:   int   = -1
        self._cur_row:   int   = -1
        self._hover_col: int   = -1
        self._hover_row: int   = -1

        self.on_die_clicked = None   # callable(col, row) | None

    def set_map(self, n_cols: int, n_rows: int):
        self._n_cols = n_cols
        self._n_rows = n_rows
        self.update()

    def set_current(self, col: int, row: int):
        self._cur_col = col
        self._cur_row = row
        self.update()

    def _cell_rect(self, col: int, row: int) -> QRect:
        """Return the pixel QRect for a die cell."""
        W, H    = self.width(), self.height()
        PAD     = 4
        nc, nr  = max(self._n_cols, 1), max(self._n_rows, 1)
        cw      = max(4, (W - 2 * PAD) // nc)
        ch      = max(4, (H - 2 * PAD) // nr)
        x       = PAD + col * cw
        y       = PAD + row * ch
        return QRect(x, y, cw - 1, ch - 1)

    def _cell_at(self, px: int, py: int):
        """Return (col, row) for pixel coordinates, or (-1, -1)."""
        if self._n_cols < 1 or self._n_rows < 1:
            return -1, -1
        W, H  = self.width(), self.height()
        PAD   = 4
        nc, nr = self._n_cols, self._n_rows
        cw    = max(4, (W - 2 * PAD) // nc)
        ch    = max(4, (H - 2 * PAD) // nr)
        col   = (px - PAD) // cw
        row   = (py - PAD) // ch
        if 0 <= col < nc and 0 <= row < nr:
            return col, row
        return -1, -1

    def paintEvent(self, e):
        p  = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(13, 13, 13))

        if self._n_cols < 1 or self._n_rows < 1:
            p.setPen(QColor(60, 60, 60))
            p.setFont(mono_font(11))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No wafer map\n(MAPSIZE? returned 0)")
            p.end()
            return

        for col in range(self._n_cols):
            for row in range(self._n_rows):
                r = self._cell_rect(col, row)
                is_cur   = (col == self._cur_col   and row == self._cur_row)
                is_hover = (col == self._hover_col and row == self._hover_row)

                if is_cur:
                    p.fillRect(r, QColor(0, 180, 140))
                elif is_hover:
                    p.fillRect(r, QColor(40, 60, 55))
                else:
                    p.fillRect(r, QColor(22, 22, 22))

                p.setPen(QPen(QColor(40, 40, 40), 1))
                p.drawRect(r)

                # Show (col,row) label only if cells are large enough
                if r.width() >= 22 and r.height() >= 14:
                    p.setPen(QColor(80, 80, 80) if not is_cur
                             else QColor(0, 0, 0))
                    p.setFont(mono_font(7))
                    p.drawText(r, Qt.AlignCenter, f"{col},{row}")

        p.end()

    def mouseMoveEvent(self, e):
        col, row = self._cell_at(e.x(), e.y())
        if col != self._hover_col or row != self._hover_row:
            self._hover_col = col
            self._hover_row = row
            self.update()
        self.setCursor(
            Qt.PointingHandCursor if col >= 0 else Qt.ArrowCursor)

    def leaveEvent(self, e):
        self._hover_col = -1
        self._hover_row = -1
        self.update()
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            col, row = self._cell_at(e.x(), e.y())
            if col >= 0 and self.on_die_clicked is not None:
                self.on_die_clicked(col, row)


# ------------------------------------------------------------------ #
#  ProberTab                                                          #
# ------------------------------------------------------------------ #

class ProberTab(QWidget):
    """
    Probe-station chuck control panel.

    Reads app_state.prober and delegates all hardware calls through it.
    A QTimer polls position every second to keep readouts current.
    """

    open_device_manager = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._prober = None   # refreshed on each timer tick / showEvent

        # Outer layout holds the stacked widget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: not-connected empty state
        self._stack.addWidget(self._build_empty_state(
            "Probe Station", "Prober",
            "Connect a probe station in Device Manager to enable "
            "wafer navigation and die stepping."))

        # Page 1: full controls
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── Connection status ─────────────────────────────────────────
        self._conn_lbl = QLabel("Prober not connected")
        self._conn_lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt; "
            f"padding:4px;")
        self._conn_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._conn_lbl)

        # ── Motion busy indicator (shown only while a command is running) ─
        self._prog = QProgressBar()
        self._prog.setRange(0, 0)          # indeterminate / animated
        self._prog.setFixedHeight(3)
        self._prog.setTextVisible(False)
        self._prog.setVisible(False)
        self._prog.setStyleSheet(
            "QProgressBar { background:#1a1a1a; border:none; margin:0; }"
            "QProgressBar::chunk { background:#00d4aa; }")
        root.addWidget(self._prog)

        # ── Position readouts ─────────────────────────────────────────
        pos_box = QGroupBox("Chuck Position")
        pl = QHBoxLayout(pos_box)
        self._x_w  = self._readout("X (µm)", "—", PALETTE["accent"])
        self._y_w  = self._readout("Y (µm)", "—", PALETTE["warning"])
        self._z_w  = self._readout("Z (µm)", "—", PALETTE["info"])
        self._st_w = self._readout("Status",  "—", "#555")
        for w in [self._x_w, self._y_w, self._z_w, self._st_w]:
            pl.addWidget(w)
        root.addWidget(pos_box)

        # ── Bottom section (splitter-free: left + right columns) ──────
        body = QHBoxLayout()
        root.addLayout(body, 1)

        # Left column: die grid + stepping + contact/lift
        left = QVBoxLayout()
        body.addLayout(left, 2)

        # Wafer map die grid
        map_box = QGroupBox("Wafer Die Map  (click to step)")
        ml = QVBoxLayout(map_box)
        self._die_grid = DieGrid()
        self._die_grid.on_die_clicked = self._step_to_die_click
        ml.addWidget(self._die_grid, 1)
        left.addWidget(map_box, 1)

        # Die stepping
        die_box = QGroupBox("Die Step")
        dl = QGridLayout(die_box)
        dl.setSpacing(6)

        self._col_spin = QSpinBox()
        self._col_spin.setRange(0, 999)
        self._col_spin.setFixedWidth(80)
        self._col_spin.setToolTip("Wafer map column (0-based)")

        self._row_spin = QSpinBox()
        self._row_spin.setRange(0, 999)
        self._row_spin.setFixedWidth(80)
        self._row_spin.setToolTip("Wafer map row (0-based)")

        self._step_btn = QPushButton("Step →")
        self._step_btn.setObjectName("primary")
        self._step_btn.setFixedWidth(80)
        self._step_btn.setFixedHeight(30)
        self._step_btn.setToolTip("Move stage to the selected wafer die (row/column)")
        self._step_btn.clicked.connect(self._step_to_die)

        dl.addWidget(QLabel("Col:"),       0, 0)
        dl.addWidget(self._col_spin,       0, 1)
        dl.addWidget(QLabel("Row:"),       0, 2)
        dl.addWidget(self._row_spin,       0, 3)
        dl.addWidget(self._step_btn,       0, 4)
        left.addWidget(die_box)

        # Contact / Lift
        needle_box = QGroupBox("Probe Needles")
        nl = QHBoxLayout(needle_box)

        self._contact_btn = QPushButton("Contact")
        set_btn_icon(self._contact_btn, "fa5s.arrow-down", "#00d4aa")
        self._contact_btn.setObjectName("primary")
        self._contact_btn.setFixedHeight(34)
        self._contact_btn.setToolTip(
            "Lower probe needles to make electrical contact with the DUT.")
        self._contact_btn.clicked.connect(self._contact)

        self._lift_btn = QPushButton("Lift")
        set_btn_icon(self._lift_btn, "fa5s.arrow-up")
        self._lift_btn.setFixedHeight(34)
        self._lift_btn.setToolTip(
            "Raise probe needles to safe travel height before moving.")
        self._lift_btn.clicked.connect(self._lift)

        nl.addWidget(self._contact_btn)
        nl.addWidget(self._lift_btn)
        left.addWidget(needle_box)

        # Right column: absolute move + home/stop
        right = QVBoxLayout()
        body.addLayout(right, 1)

        # Absolute XYZ move
        abs_box = QGroupBox("Move To  (absolute µm)")
        al = QGridLayout(abs_box)
        al.setSpacing(8)

        self._ax = self._axis_spin(-100_000, 100_000, 0.0)
        self._ay = self._axis_spin(-100_000, 100_000, 0.0)
        self._az = self._axis_spin(0,          50_000, 0.0)

        al.addWidget(QLabel("X (µm):"),  0, 0)
        al.addWidget(self._ax,           0, 1)
        al.addWidget(QLabel("Y (µm):"),  1, 0)
        al.addWidget(self._ay,           1, 1)
        al.addWidget(QLabel("Z (µm):"),  2, 0)
        al.addWidget(self._az,           2, 1)

        move_btn = QPushButton("Move To")
        move_btn.setObjectName("primary")
        move_btn.setFixedHeight(30)
        move_btn.setToolTip("Move stage to the specified absolute X/Y/Z coordinates")
        move_btn.clicked.connect(self._move_to)
        al.addWidget(move_btn, 3, 0, 1, 2)
        right.addWidget(abs_box)

        # Home / Stop
        ctrl_box = QGroupBox("Controls")
        cl = QVBoxLayout(ctrl_box)
        self._home_btn = QPushButton("Home All")
        set_btn_icon(self._home_btn, "fa5s.home")
        self._home_btn.setFixedHeight(32)
        self._home_btn.clicked.connect(self._home)
        self._stop_btn = QPushButton("Stop")
        set_btn_icon(self._stop_btn, "fa5s.stop", "#ff6666")
        self._stop_btn.setObjectName("danger")
        self._stop_btn.setFixedHeight(32)
        self._stop_btn.clicked.connect(self._stop)
        cl.addWidget(self._home_btn)
        cl.addWidget(self._stop_btn)
        right.addWidget(ctrl_box)
        right.addStretch()

        # ── Poll timer ────────────────────────────────────────────────
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(1000)   # 1 Hz position refresh
        self._poll_timer.timeout.connect(self._refresh_position)

        self._stack.addWidget(controls)
        self._stack.setCurrentIndex(0)  # empty state until device connects

    # ---------------------------------------------------------------- #
    #  Visibility / refresh                                            #
    # ---------------------------------------------------------------- #

    def showEvent(self, e):
        self._refresh_all()
        self._poll_timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._poll_timer.stop()
        super().hideEvent(e)

    def _build_empty_state(self, title: str, device: str, tip: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon_lbl = make_icon_label(IC.LINK_OFF, color="#555555", size=64)
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(f"{title} Not Connected")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; font-weight: bold; color: #888;")

        tip_lbl = QLabel(tip)
        tip_lbl.setAlignment(Qt.AlignCenter)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet(f"font-size: {FONT['label']}pt; color: #555;")
        tip_lbl.setMaximumWidth(400)

        btn = QPushButton("Open Device Manager")
        btn.setFixedWidth(200)
        btn.setFixedHeight(36)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE.get('surface','#2d2d2d')}; color: #00d4aa;
                border: 1px solid #00d4aa66; border-radius: 5px;
                font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: {PALETTE.get('surface2','#3d3d3d')}; }}
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

    def _refresh_all(self):
        """Reload prober reference and update all UI elements."""
        self._prober = app_state.prober
        connected    = self._prober is not None

        self._conn_lbl.setText(
            ("MPI Prober connected" if connected else "Prober not connected")
        )
        self._conn_lbl.setStyleSheet(
            f"color:{PALETTE['success'] if connected else PALETTE['textDim']}; "
            f"font-size:{FONT['label']}pt; padding:4px;")

        # Enable/disable interactive controls
        for w in [self._ax, self._ay, self._az,
                  self._col_spin, self._row_spin,
                  self._step_btn, self._contact_btn, self._lift_btn,
                  self._home_btn, self._stop_btn]:
            w.setEnabled(connected)

        if connected:
            # Update wafer map size
            map_size = getattr(self._prober, '_map_size', (0, 0))
            self._die_grid.set_map(map_size[0], map_size[1])
            if map_size[0] > 0:
                self._col_spin.setRange(0, map_size[0] - 1)
            if map_size[1] > 0:
                self._row_spin.setRange(0, map_size[1] - 1)
            self._refresh_position()

    def _refresh_position(self):
        """Update position readout labels from cached driver state."""
        prober = self._prober or app_state.prober
        if prober is None:
            return
        pos = getattr(prober, '_pos', None)
        if pos is not None:
            self._x_w._val.setText(f"{getattr(pos, 'x', 0.0):+.1f}")
            self._y_w._val.setText(f"{getattr(pos, 'y', 0.0):+.1f}")
            self._z_w._val.setText(f"{getattr(pos, 'z', 0.0):.1f}")
        moving = getattr(prober, '_moving', False)
        homed  = getattr(prober, '_homed', False)
        status = "MOVING" if moving else ("HOMED" if homed else "IDLE")
        color  = (PALETTE["warning"] if moving
                  else PALETTE["success"] if homed
                  else PALETTE["textDim"])
        self._st_w._val.setText(status)
        self._st_w._val.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutSm']}pt; "
            f"color:{color};")

    # ---------------------------------------------------------------- #
    #  Hardware actions                                                 #
    # ---------------------------------------------------------------- #

    def _require_prober(self) -> bool:
        """Check prober is available; show warning if not. Returns True if ok."""
        p = self._prober or app_state.prober
        if p is None:
            QMessageBox.warning(self, "Prober", "Prober not connected.")
            return False
        self._prober = p
        return True

    def _step_to_die(self):
        if not self._require_prober():
            return
        col = self._col_spin.value()
        row = self._row_spin.value()
        self._execute_async(lambda: self._prober.step_to_die(col, row),
                            on_done=lambda: self._die_grid.set_current(col, row))

    def _step_to_die_click(self, col: int, row: int):
        """Called when user clicks a die cell in the grid."""
        if not self._require_prober():
            return
        self._col_spin.setValue(col)
        self._row_spin.setValue(row)
        self._step_to_die()

    def _contact(self):
        if self._require_prober():
            self._execute_async(self._prober.probe_contact)

    def _lift(self):
        if self._require_prober():
            self._execute_async(self._prober.probe_lift)

    def _move_to(self):
        if not self._require_prober():
            return
        x = self._ax.value()
        y = self._ay.value()
        z = self._az.value()
        self._execute_async(
            lambda: self._prober.move_to(x=x, y=y, z=z))

    def _home(self):
        if self._require_prober():
            self._execute_async(self._prober.home)

    def _stop(self):
        p = self._prober or app_state.prober
        if p is not None:
            try:
                p.stop()
            except Exception as exc:
                log.warning("Prober stop error: %s", exc)

    # ---------------------------------------------------------------- #
    #  Busy state                                                      #
    # ---------------------------------------------------------------- #

    def _set_busy(self, busy: bool) -> None:
        """Disable all motion controls while a command is executing.

        The Stop button is kept enabled at all times so the user can always
        issue an emergency stop regardless of what is running.
        """
        self._prog.setVisible(busy)
        for w in [self._step_btn, self._contact_btn, self._lift_btn,
                  self._home_btn, self._ax, self._ay, self._az,
                  self._col_spin, self._row_spin, self._die_grid]:
            w.setEnabled(not busy)
        # Stop button is always accessible when connected
        if self._prober is not None:
            self._stop_btn.setEnabled(True)

    # ---------------------------------------------------------------- #
    #  Async execution helper                                          #
    # ---------------------------------------------------------------- #

    def _execute_async(self, fn, on_done=None):
        """Run *fn* in a daemon thread so the GUI stays responsive.

        Shows the thin progress bar and locks all motion controls for the
        duration.  The Stop button stays enabled so the user can always
        issue a hardware stop.  *on_done* is called on the GUI thread after
        *fn* completes (whether it succeeded or raised).
        """
        import threading

        self._set_busy(True)

        def _worker():
            try:
                fn()
            except Exception as exc:
                log.warning("Prober action error: %s", exc)
            finally:
                if on_done is not None:
                    QTimer.singleShot(0, on_done)
                QTimer.singleShot(0, self._refresh_position)
                QTimer.singleShot(0, lambda: self._set_busy(False))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # ---------------------------------------------------------------- #
    #  Widget helpers                                                   #
    # ---------------------------------------------------------------- #

    def _readout(self, label: str, initial: str, color: str) -> QWidget:
        """Return a labelled readout widget (label over value)."""
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(4, 4, 4, 4)

        lbl = QLabel(label)
        lbl.setObjectName("sublabel")
        lbl.setAlignment(Qt.AlignCenter)

        val = QLabel(initial)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"font-family:'Menlo','Consolas','Courier New',monospace; font-size:{FONT['readoutSm']}pt; "
            f"color:{color};")

        lay.addWidget(lbl)
        lay.addWidget(val)
        w._val = val
        return w

    def _axis_spin(self, lo: float, hi: float, default: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(default)
        s.setSuffix(" µm")
        s.setDecimals(1)
        s.setFixedWidth(120)
        return s
