"""
ui/tabs/camera_tab.py

CameraTab — live camera preview with exposure/gain controls and frame statistics.
"""

from __future__ import annotations

import time
import threading
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSlider, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QButtonGroup, QRadioButton, QFrame)
from PyQt5.QtCore    import Qt

from hardware.app_state    import app_state
from ui.widgets.image_pane import ImagePane


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #2a2a2a;")
    return f


class CameraTab(QWidget):
    def __init__(self, cam_info=None):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        root.addLayout(top)

        # Image
        img_box = QGroupBox("Frame")
        il = QVBoxLayout(img_box)
        self._pane = ImagePane("", 640, 480)
        il.addWidget(self._pane)
        top.addWidget(img_box, 3)

        # Controls
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        from ui.help import help_label
        cl.addWidget(help_label("Exposure (μs)", "exposure_us"), 0, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(50, 200000)
        self._exp_slider.setValue(5000)
        self._exp_lbl = QLabel("5000")
        self._exp_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        self._exp_slider.valueChanged.connect(
            lambda v: self._exp_lbl.setText(str(v)))
        self._exp_slider.sliderReleased.connect(self._on_exp)
        cl.addWidget(self._exp_slider, 0, 1)
        cl.addWidget(self._exp_lbl, 0, 2)

        # Presets
        pr = QHBoxLayout()
        for lbl, v in [("50μs",50),("1ms",1000),("5ms",5000),
                       ("20ms",20000),("100ms",100000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(55)
            b.clicked.connect(lambda _, val=v: self._set_exp(val))
            pr.addWidget(b)
        pr.addStretch()
        cl.addLayout(pr, 1, 1)

        cl.addWidget(help_label("Gain (dB)", "gain_db"), 2, 0)
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 239)
        self._gain_slider.setValue(0)
        self._gain_lbl = QLabel("0.0")
        self._gain_lbl.setStyleSheet(
            "font-family:Menlo,monospace; font-size:18pt; color:#00d4aa;")
        self._gain_slider.valueChanged.connect(
            lambda v: self._gain_lbl.setText(f"{v/10:.1f}"))
        self._gain_slider.sliderReleased.connect(self._on_gain)
        cl.addWidget(self._gain_slider, 2, 1)
        cl.addWidget(self._gain_lbl, 2, 2)

        cl.addWidget(hline(), 3, 0, 1, 3)

        cl.addWidget(QLabel("Display"), 4, 0)
        self._bg = QButtonGroup()
        dr = QHBoxLayout()
        for i, m in enumerate(["Auto contrast", "12-bit fixed"]):
            rb = QRadioButton(m)
            self._bg.addButton(rb, i)
            dr.addWidget(rb)
        self._bg.button(0).setChecked(True)
        dr.addStretch()
        cl.addLayout(dr, 4, 1)

        save_btn = QPushButton("Save Frame (16-bit PNG)")
        save_btn.clicked.connect(self._save)
        cl.addWidget(save_btn, 5, 1)

        top.addWidget(ctrl_box, 1)

        # Stats
        stats_box = QGroupBox("Frame Statistics")
        sl = QHBoxLayout(stats_box)
        self._stat_min  = self._stat_widget("MIN")
        self._stat_max  = self._stat_widget("MAX")
        self._stat_mean = self._stat_widget("MEAN")
        self._stat_idx  = self._stat_widget("FRAME")
        for w in [self._stat_min, self._stat_max,
                  self._stat_mean, self._stat_idx]:
            sl.addWidget(w)
        root.addWidget(stats_box)

    def _stat_widget(self, label):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        sub = QLabel(label)
        sub.setObjectName("sublabel")
        sub.setAlignment(Qt.AlignCenter)
        val = QLabel("--")
        val.setObjectName("readout")
        val.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        v.addWidget(val)
        w._val = val
        return w

    def update_frame(self, frame):
        d = frame.data
        mode = "auto" if self._bg.checkedId() == 0 else "fixed"
        self._pane.show_array(d, mode=mode)
        self._stat_min._val.setText(str(int(d.min())))
        self._stat_max._val.setText(str(int(d.max())))
        self._stat_mean._val.setText(f"{d.mean():.1f}")
        self._stat_idx._val.setText(str(frame.frame_index))

    def _set_exp(self, val):
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def _on_exp(self):
        self._do_exp(self._exp_slider.value())

    def _do_exp(self, val):
        cam = app_state.cam
        if cam:
            threading.Thread(
                target=cam.set_exposure, args=(float(val),),
                daemon=True).start()

    def _on_gain(self):
        cam = app_state.cam
        if cam:
            val = self._gain_slider.value() / 10.0
            threading.Thread(
                target=cam.set_gain, args=(val,),
                daemon=True).start()

    def _save(self):
        import cv2
        cam = app_state.cam
        if cam:
            f = cam.grab()
            if f:
                name = f"frame_{int(time.time())}.png"
                cv2.imwrite(name, f.data)
                from ui.app_signals import signals
                signals.log_message.emit(f"Saved: {name}")

    def set_exposure(self, us: float):
        """Push a new exposure value from an external source (e.g. profile)."""
        val = int(max(50, min(200000, us)))
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def set_gain(self, db: float):
        """Push a new gain value from an external source (e.g. profile)."""
        val = int(max(0, min(239, db * 10)))
        self._gain_slider.setValue(val)
        cam = app_state.cam
        if cam:
            threading.Thread(
                target=cam.set_gain, args=(db,), daemon=True).start()
