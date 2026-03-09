"""
viewer.py
Microsanj live camera viewer.

The viewer knows nothing about which camera is connected.
Change  driver:  in config.yaml to switch cameras — no code changes needed.

Available drivers:
    ni_imaqdx   Basler via NI Vision Acquisition Software (current system)
    pypylon      Basler via official Pylon SDK (no NI required)
    directshow   USB thermal cameras, webcams (Windows DirectShow)
    simulated    Synthetic frames for testing without hardware

Run:  python viewer.py
"""

import logging
import sys
import time
import threading
import numpy as np

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
                             QSlider, QPushButton, QHBoxLayout, QVBoxLayout,
                             QGridLayout, QButtonGroup, QRadioButton, QFrame,
                             QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui  import QImage, QPixmap

import config
from hardware.cameras import create_camera


# ------------------------------------------------------------------ #
#  Shared state                                                       #
# ------------------------------------------------------------------ #

class State:
    def __init__(self):
        self.frame         = None      # latest CameraFrame
        self.running       = False
        self.auto_contrast = True
        self.setting_attr  = False
        self.lock          = threading.Lock()

S   = State()
cam = None   # the CameraDriver instance


# ------------------------------------------------------------------ #
#  Capture thread                                                     #
# ------------------------------------------------------------------ #

class Signals(QObject):
    new_frame = pyqtSignal()
    error     = pyqtSignal(str)

signals = Signals()


def capture_loop():
    global cam
    cfg = config.get("hardware").get("camera", {})

    try:
        cam = create_camera(cfg)
        cam.open()
        cam.start()
    except Exception as e:
        signals.error.emit(str(e))
        return

    log.info("Camera open: %s | %s | %dx%d",
             cam.info.driver, cam.info.model,
             cam.info.width, cam.info.height)
    S.running = True

    while S.running:
        if S.setting_attr:
            time.sleep(0.05)
            continue

        frame = cam.grab(timeout_ms=2000)
        if frame is None:
            continue

        with S.lock:
            S.frame = frame

        signals.new_frame.emit()

    cam.close()
    log.info("Camera closed.")


# ------------------------------------------------------------------ #
#  Main window                                                        #
# ------------------------------------------------------------------ #

DISP_W = 960
DISP_H = 600


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Microsanj Camera Viewer")
        self._build_ui()
        signals.new_frame.connect(self._on_new_frame)
        signals.error.connect(self._on_error)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        # Live image
        self.image_label = QLabel()
        self.image_label.setFixedSize(DISP_W, DISP_H)
        self.image_label.setStyleSheet("background: black;")
        self.image_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.image_label)

        # Status
        self.status_lbl = QLabel("Connecting...")
        self.status_lbl.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        root.addWidget(self.status_lbl)

        root.addWidget(self._hline())

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        # Exposure
        grid.addWidget(QLabel("Exposure (us):"), 0, 0)
        self.exp_slider = QSlider(Qt.Horizontal)
        self.exp_slider.setRange(50, 200000)
        self.exp_slider.setValue(5000)
        self.exp_slider.valueChanged.connect(
            lambda v: self.exp_lbl.setText(str(v)))
        self.exp_slider.sliderReleased.connect(self._on_exp_released)
        grid.addWidget(self.exp_slider, 0, 1)
        self.exp_lbl = QLabel("5000")
        self.exp_lbl.setFixedWidth(70)
        grid.addWidget(self.exp_lbl, 0, 2)

        # Exposure presets
        presets = QHBoxLayout()
        for lbl, val in [("50us",50),("500us",500),("1ms",1000),
                         ("5ms",5000),("20ms",20000),("100ms",100000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(60)
            b.clicked.connect(lambda _, v=val: self._set_exposure(v))
            presets.addWidget(b)
        presets.addStretch()
        grid.addLayout(presets, 1, 1)

        # Gain
        grid.addWidget(QLabel("Gain (dB):"), 2, 0)
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 240)
        self.gain_slider.setValue(0)
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_lbl.setText(f"{v/10:.1f}"))
        self.gain_slider.sliderReleased.connect(self._on_gain_released)
        grid.addWidget(self.gain_slider, 2, 1)
        self.gain_lbl = QLabel("0.0")
        self.gain_lbl.setFixedWidth(70)
        grid.addWidget(self.gain_lbl, 2, 2)

        root.addWidget(self._hline())

        # Display mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Display:"))
        self.bg = QButtonGroup()
        for i, m in enumerate(["Auto contrast", "12-bit fixed"]):
            rb = QRadioButton(m)
            self.bg.addButton(rb, i)
            mode_row.addWidget(rb)
        self.bg.button(0).setChecked(True)
        self.bg.buttonClicked.connect(
            lambda: setattr(S, 'auto_contrast', self.bg.checkedId() == 0))
        mode_row.addStretch()
        root.addLayout(mode_row)

        # Stats + save
        bottom = QHBoxLayout()
        self.stats_lbl = QLabel("Min: --   Max: --   Mean: --")
        self.stats_lbl.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        bottom.addWidget(self.stats_lbl)
        bottom.addStretch()
        save_btn = QPushButton("Save Frame (16-bit PNG)")
        save_btn.clicked.connect(self._save)
        bottom.addWidget(save_btn)
        root.addLayout(bottom)

    def _hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        return f

    # ---------------------------------------------------------------- #

    def _set_exposure(self, val):
        self.exp_slider.setValue(val)
        self._apply_attr(lambda: cam.set_exposure(float(val)))

    def _on_exp_released(self):
        val = float(self.exp_slider.value())
        self._apply_attr(lambda: cam.set_exposure(val))

    def _on_gain_released(self):
        val = self.gain_slider.value() / 10.0
        self._apply_attr(lambda: cam.set_gain(val))

    def _apply_attr(self, fn):
        """Run an attribute setter in a thread so the UI stays responsive."""
        def _run():
            S.setting_attr = True
            try:
                fn()
            finally:
                S.setting_attr = False
        threading.Thread(target=_run, daemon=True).start()

    def _save(self):
        import cv2
        with S.lock:
            frame = S.frame
        if frame is not None:
            fname = f"frame_{int(time.time())}.png"
            cv2.imwrite(fname, frame.data)
            self.status_lbl.setText(f"Saved: {fname}")
            log.info("Saved: %s", fname)

    def _on_error(self, msg):
        self.status_lbl.setText(f"ERROR: {msg}")
        QMessageBox.critical(self, "Camera Error", msg)

    def _on_new_frame(self):
        with S.lock:
            frame = S.frame
        if frame is None:
            return

        d = frame.data
        self.stats_lbl.setText(
            f"Min: {d.min():<6} Max: {d.max():<6} "
            f"Mean: {d.mean():<8.1f} Frame: {frame.frame_index}")
        self.status_lbl.setText(
            f"[LIVE]  {cam.info.driver} | {cam.info.model}  "
            f"Exp: {frame.exposure_us:.0f}us  Gain: {frame.gain_db:.1f}dB")

        # Scale to 8-bit for display
        if S.auto_contrast:
            lo, hi = d.min(), d.max()
            disp8 = ((d.astype(np.float32) - lo) / max(hi - lo, 1) * 255
                     ).astype(np.uint8)
        else:
            disp8 = (d >> 4).astype(np.uint8)

        h, w  = disp8.shape
        qimg  = QImage(disp8.data, w, h, w, QImage.Format_Grayscale8)
        pix   = QPixmap.fromImage(qimg).scaled(
            DISP_W, DISP_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)

    def closeEvent(self, event):
        S.running = False
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    threading.Thread(target=capture_loop, daemon=True).start()
    app    = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
