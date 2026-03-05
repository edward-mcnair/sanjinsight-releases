"""
ui/tabs/roi_tab.py

RoiTab — ROI selection tab with interactive RoiSelector and acquisition controls.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSpinBox, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox)
from PyQt5.QtCore    import Qt

from hardware.app_state      import app_state
from acquisition.roi         import Roi
from acquisition.roi_widget  import RoiSelector
from ui.icons import set_btn_icon


class RoiTab(QWidget):
    """
    ROI selection tab.

    Left  — interactive RoiSelector (draw box on live image)
    Right — ROI info, presets, apply/clear controls
    """

    def __init__(self):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- Left: selector canvas ----
        left = QVBoxLayout()
        sel_box = QGroupBox("Draw ROI  (click and drag on image)")
        sl = QVBoxLayout(sel_box)
        self._selector = RoiSelector()
        self._selector.roi_changed.connect(self._on_roi_changed)
        sl.addWidget(self._selector)
        left.addWidget(sel_box)
        root.addLayout(left, 3)

        # ---- Right: controls ----
        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 1)

        # Current ROI readout
        info_box = QGroupBox("Current ROI")
        il = QGridLayout(info_box)

        self._roi_labels = {}
        for r, (key, label) in enumerate([
                ("x",  "X origin"), ("y", "Y origin"),
                ("w",  "Width"),    ("h", "Height"),
                ("area", "Area"),   ("status", "Status")]):
            il.addWidget(self._sub(label), r, 0)
            lbl = QLabel("--")
            lbl.setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#00d4aa;")
            il.addWidget(lbl, r, 1)
            self._roi_labels[key] = lbl

        right.addWidget(info_box)

        # Preset ROIs
        preset_box = QGroupBox("Presets")
        pl = QVBoxLayout(preset_box)
        self._frame_hw = (1200, 1920)   # updated when frames arrive

        presets = [
            ("Centre  25%",  0.375, 0.375, 0.25,  0.25),
            ("Centre  50%",  0.25,  0.25,  0.50,  0.50),
            ("Top-left  25%",0.0,   0.0,   0.25,  0.25),
            ("Full frame",   0.0,   0.0,   1.0,   1.0),
        ]
        for label, rx, ry, rw, rh in presets:
            b = QPushButton(label)
            b.clicked.connect(
                lambda _, rx=rx, ry=ry, rw=rw, rh=rh:
                    self._apply_preset(rx, ry, rw, rh))
            pl.addWidget(b)
        right.addWidget(preset_box)

        # Manual entry
        manual_box = QGroupBox("Manual Entry  (pixels)")
        ml = QGridLayout(manual_box)
        self._mx = self._ispin(0, 9999, 0)
        self._my = self._ispin(0, 9999, 0)
        self._mw = self._ispin(1, 9999, 400)
        self._mh = self._ispin(1, 9999, 300)
        for r, (lbl, sp) in enumerate([
                ("X", self._mx), ("Y", self._my),
                ("W", self._mw), ("H", self._mh)]):
            ml.addWidget(QLabel(lbl), r, 0)
            ml.addWidget(sp, r, 1)
        apply_btn = QPushButton("Apply Manual ROI")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply_manual)
        ml.addWidget(apply_btn, 4, 0, 1, 2)
        right.addWidget(manual_box)

        # Apply to acquisition / clear
        ctrl_box = QGroupBox("Acquisition")
        ctl = QVBoxLayout(ctrl_box)
        self._apply_acq_btn = QPushButton("Apply ROI to Acquisition")
        set_btn_icon(self._apply_acq_btn, "fa5s.check", "#00d4aa")
        self._apply_acq_btn.setObjectName("primary")
        self._clear_acq_btn = QPushButton("Clear  (use full frame)")
        set_btn_icon(self._clear_acq_btn, "fa5s.times")
        self._apply_acq_btn.clicked.connect(self._apply_to_acq)
        self._clear_acq_btn.clicked.connect(self._clear_acq)
        self._acq_status = QLabel("No ROI active")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        ctl.addWidget(self._apply_acq_btn)
        ctl.addWidget(self._clear_acq_btn)
        ctl.addWidget(self._acq_status)
        right.addWidget(ctrl_box)
        right.addStretch()

    # ---------------------------------------------------------------- #

    def _sub(self, text):
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l

    def _ispin(self, lo, hi, val):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setFixedWidth(90)
        return s

    def update_frame(self, frame_data):
        """Feed latest live frame into the selector canvas."""
        self._frame_hw = frame_data.shape[:2]
        self._selector.set_frame(frame_data)

    def _on_roi_changed(self, roi: Roi):
        """Update info labels when ROI changes."""
        if roi.is_empty:
            for k, l in self._roi_labels.items():
                l.setText("--")
            self._roi_labels["status"].setText("Full frame")
            self._roi_labels["status"].setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#555;")
        else:
            self._roi_labels["x"].setText(str(roi.x))
            self._roi_labels["y"].setText(str(roi.y))
            self._roi_labels["w"].setText(str(roi.w))
            self._roi_labels["h"].setText(str(roi.h))
            self._roi_labels["area"].setText(f"{roi.area:,} px")
            self._roi_labels["status"].setText("ROI defined")
            self._roi_labels["status"].setStyleSheet(
                "font-family:Menlo,monospace; font-size:15pt; color:#ffaa44;")

    def _apply_preset(self, rx, ry, rw, rh):
        fh, fw = self._frame_hw
        x = int(rx * fw)
        y = int(ry * fh)
        w = int(rw * fw)
        h = int(rh * fh)
        if w >= fw and h >= fh:
            self._selector._canvas.clear_roi()
        else:
            self._selector._canvas.set_roi(Roi(x=x, y=y, w=w, h=h))

    def _apply_manual(self):
        roi = Roi(x=self._mx.value(), y=self._my.value(),
                  w=self._mw.value(), h=self._mh.value())
        self._selector._canvas.set_roi(roi)

    def _apply_to_acq(self):
        roi = self._selector.roi
        pl = app_state.pipeline
        if pl:
            pl.roi = roi if not roi.is_empty else None
        msg = str(roi) if not roi.is_empty else "Full frame (no ROI)"
        self._acq_status.setText(f"Active: {msg}")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#00d4aa;")
        from ui.app_signals import signals
        signals.log_message.emit(f"ROI applied to acquisition: {msg}")

    def _clear_acq(self):
        self._selector._canvas.clear_roi()
        pl = app_state.pipeline
        if pl:
            pl.roi = None
        self._acq_status.setText("No ROI active (full frame)")
        self._acq_status.setStyleSheet(
            "font-family:Menlo,monospace; font-size:14pt; color:#555;")
        from ui.app_signals import signals
        signals.log_message.emit("ROI cleared — acquisition using full frame")
