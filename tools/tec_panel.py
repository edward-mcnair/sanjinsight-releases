"""
tec_panel.py
Standalone TEC controller UI panel.
Works with any TecDriver — simulated, Meerstetter, or ATEC.

Run:  python tec_panel.py
"""

import sys
import time
import threading
import collections
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QDoubleSpinBox,
    QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QGroupBox, QSizePolicy)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui   import QColor, QPainter, QPen, QFont

import config
from hardware.tec import create_tec

# How often to poll the TEC for status (ms)
POLL_MS = 500
# How many history points to show in the temperature plot
HISTORY = 120


# ------------------------------------------------------------------ #
#  Temperature history plot (pure PyQt5, no matplotlib dependency)   #
# ------------------------------------------------------------------ #

class TempPlot(QWidget):
    """Simple scrolling temperature chart drawn with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._actual  = collections.deque([None] * HISTORY, maxlen=HISTORY)
        self._target  = collections.deque([None] * HISTORY, maxlen=HISTORY)
        self._bg      = QColor(30, 30, 30)
        self._grid    = QColor(60, 60, 60)
        self._actual_color = QColor(0, 200, 100)
        self._target_color = QColor(255, 160, 0)

    def push(self, actual: float, target: float):
        self._actual.append(actual)
        self._target.append(target)
        self.update()

    def paintEvent(self, event):
        p   = QPainter(self)
        w, h = self.width(), self.height()
        pad  = 40

        # Background
        p.fillRect(0, 0, w, h, self._bg)

        # Determine Y range
        vals = [v for v in list(self._actual) + list(self._target)
                if v is not None]
        if not vals:
            return
        lo = min(vals) - 2
        hi = max(vals) + 2
        span = max(hi - lo, 1.0)

        def to_y(v):
            return int(h - pad - (v - lo) / span * (h - 2 * pad))

        def to_x(i):
            return int(pad + i / (HISTORY - 1) * (w - 2 * pad))

        # Grid lines at rounded temperature intervals
        p.setPen(QPen(self._grid, 1))
        step = max(1, int(span / 5))
        t    = (int(lo / step) - 1) * step
        font = QFont("Consolas", 8)
        p.setFont(font)
        p.setPen(QPen(self._grid, 1))
        while t <= hi + step:
            y = to_y(t)
            if pad <= y <= h - pad:
                p.drawLine(pad, y, w - pad, y)
                p.setPen(QPen(QColor(150, 150, 150), 1))
                p.drawText(2, y + 4, f"{t:.0f}°")
                p.setPen(QPen(self._grid, 1))
            t += step

        # Plot lines
        for series, color in [(self._actual, self._actual_color),
                               (self._target, self._target_color)]:
            p.setPen(QPen(color, 2))
            pts = list(series)
            prev = None
            for i, v in enumerate(pts):
                if v is None:
                    prev = None
                    continue
                x, y = to_x(i), to_y(v)
                if prev:
                    p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # Legend
        p.setPen(QPen(self._actual_color, 2))
        p.drawLine(w - 120, 12, w - 100, 12)
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawText(w - 95, 16, "Actual")
        p.setPen(QPen(self._target_color, 2))
        p.drawLine(w - 120, 26, w - 100, 26)
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawText(w - 95, 30, "Target")

        p.end()


# ------------------------------------------------------------------ #
#  Signals                                                            #
# ------------------------------------------------------------------ #

class TecSignals(QObject):
    status_updated = pyqtSignal(object)   # TecStatus
    error          = pyqtSignal(str)


# ------------------------------------------------------------------ #
#  Main window                                                        #
# ------------------------------------------------------------------ #

class TecPanel(QMainWindow):

    def __init__(self, tec_a, tec_b=None):
        """
        tec_a: primary TEC driver (Meerstetter TEC-1089)
        tec_b: secondary TEC driver (ATEC-302) — optional
        """
        super().__init__()
        self.setWindowTitle("Microsanj TEC Controller")
        self._tecs    = [t for t in [tec_a, tec_b] if t is not None]
        self._signals = [TecSignals() for _ in self._tecs]
        self._running = True

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        self._panels = []
        for i, (tec, sig) in enumerate(zip(self._tecs, self._signals)):
            label = ["TEC 1 — Meerstetter TEC-1089",
                     "TEC 2 — ATEC-302"][i]
            panel = self._build_tec_panel(tec, sig, label)
            root.addWidget(panel)
            self._panels.append(panel)
            sig.status_updated.connect(
                lambda s, p=panel: self._update_panel(p, s))
            sig.error.connect(self._on_error)

        # Start polling thread for each TEC
        for i, tec in enumerate(self._tecs):
            threading.Thread(
                target=self._poll_loop,
                args=(tec, self._signals[i]),
                daemon=True).start()

    def _build_tec_panel(self, tec, sig, title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11pt;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 8px;
                padding: 8px;
            }
            QGroupBox::title { subcontrol-position: top left; padding: 0 4px; }
        """)
        layout = QVBoxLayout(box)

        # --- Readouts row ---
        readout_row = QHBoxLayout()

        actual_box = self._value_box("Actual Temp", "-- °C", "font-size:22pt; color:#00c864;")
        target_box = self._value_box("Setpoint",    "-- °C", "font-size:22pt; color:#ffa000;")
        power_box  = self._value_box("Output Power","-- W",  "font-size:18pt; color:#55aaff;")
        stable_box = self._value_box("Status",      "UNKNOWN","font-size:14pt; color:#888;")

        for b in [actual_box, target_box, power_box, stable_box]:
            readout_row.addWidget(b)

        # Store label refs on the box widget for update_panel to find
        box._actual_lbl  = actual_box.findChild(QLabel, "value")
        box._target_lbl  = target_box.findChild(QLabel, "value")
        box._power_lbl   = power_box.findChild(QLabel,  "value")
        box._stable_lbl  = stable_box.findChild(QLabel, "value")

        layout.addLayout(readout_row)

        # --- Plot ---
        plot = TempPlot()
        box._plot = plot
        layout.addWidget(plot)

        # --- Controls row ---
        ctrl_row = QHBoxLayout()

        ctrl_row.addWidget(QLabel("Set target (°C):"))
        spin = QDoubleSpinBox()
        spin.setRange(*tec.temp_range())
        spin.setSingleStep(0.5)
        spin.setValue(25.0)
        spin.setDecimals(1)
        spin.setFixedWidth(90)
        spin.setStyleSheet("font-size:12pt;")
        ctrl_row.addWidget(spin)
        box._spin = spin

        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(60)
        set_btn.clicked.connect(
            lambda _, t=tec, s=spin: self._set_target(t, s.value()))
        ctrl_row.addWidget(set_btn)

        # Preset temperatures
        ctrl_row.addSpacing(16)
        for label, val in [("-20°C", -20), ("0°C", 0), ("25°C", 25),
                           ("50°C", 50), ("85°C", 85)]:
            b = QPushButton(label)
            b.setFixedWidth(56)
            b.clicked.connect(
                lambda _, t=tec, s=spin, v=val: (s.setValue(v),
                                                  self._set_target(t, v)))
            ctrl_row.addWidget(b)

        ctrl_row.addStretch()

        enable_btn  = QPushButton("Enable")
        disable_btn = QPushButton("Disable")
        enable_btn.setFixedWidth(80)
        disable_btn.setFixedWidth(80)
        enable_btn.setStyleSheet("background:#005500; color:white;")
        disable_btn.setStyleSheet("background:#550000; color:white;")
        enable_btn.clicked.connect( lambda _, t=tec: self._enable(t))
        disable_btn.clicked.connect(lambda _, t=tec: self._disable(t))
        ctrl_row.addWidget(enable_btn)
        ctrl_row.addWidget(disable_btn)

        layout.addLayout(ctrl_row)
        return box

    def _value_box(self, label: str, initial: str, style: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size:9pt; color:#aaa;")
        val = QLabel(initial)
        val.setObjectName("value")
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(style)
        v.addWidget(lbl)
        v.addWidget(val)
        return w

    # ---------------------------------------------------------------- #

    def _set_target(self, tec, value: float):
        threading.Thread(
            target=tec.set_target, args=(value,), daemon=True).start()

    def _enable(self, tec):
        threading.Thread(target=tec.enable, daemon=True).start()

    def _disable(self, tec):
        threading.Thread(target=tec.disable, daemon=True).start()

    def _poll_loop(self, tec, sig: TecSignals):
        while self._running:
            try:
                status = tec.get_status()
                sig.status_updated.emit(status)
            except Exception as e:
                sig.error.emit(str(e))
            time.sleep(POLL_MS / 1000.0)

    def _update_panel(self, panel: QGroupBox, status):
        if status.error:
            panel._actual_lbl.setText("ERROR")
            panel._stable_lbl.setText(status.error[:30])
            panel._stable_lbl.setStyleSheet("font-size:11pt; color:#ff4444;")
            return

        panel._actual_lbl.setText(f"{status.actual_temp:.2f} °C")
        panel._target_lbl.setText(f"{status.target_temp:.1f} °C")
        panel._power_lbl.setText( f"{status.output_power:.2f} W")

        if not status.enabled:
            panel._stable_lbl.setText("DISABLED")
            panel._stable_lbl.setStyleSheet("font-size:14pt; color:#888;")
        elif status.stable:
            panel._stable_lbl.setText("STABLE ✓")
            panel._stable_lbl.setStyleSheet("font-size:14pt; color:#00c864;")
        else:
            diff = status.actual_temp - status.target_temp
            arrow = "▼" if diff > 0 else "▲"
            panel._stable_lbl.setText(f"SETTLING {arrow}")
            panel._stable_lbl.setStyleSheet("font-size:14pt; color:#ffa000;")

        panel._plot.push(status.actual_temp, status.target_temp)

    def _on_error(self, msg):
        print(f"TEC error: {msg}")

    def closeEvent(self, event):
        self._running = False
        for tec in self._tecs:
            try:
                tec.disconnect()
            except Exception:
                pass
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    hw = config.get("hardware")

    # Create TEC drivers from config
    cfg_a = hw.get("tec_meerstetter", {})
    cfg_b = hw.get("tec_atec",        {})

    tec_a = create_tec(cfg_a)
    tec_b = create_tec(cfg_b) if cfg_b.get("enabled") else None

    # Connect
    tec_a.connect()
    if tec_b:
        tec_b.connect()

    app    = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TecPanel(tec_a, tec_b)
    window.resize(900, 600)
    window.show()
    sys.exit(app.exec_())
