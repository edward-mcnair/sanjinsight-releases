"""
ui/tabs/roi_tab.py

RoiTab — Multi-ROI selection tab with interactive canvas, ROI list,
presets, manual entry, and acquisition controls.

Operates on the shared ``roi_model`` singleton so ROIs are visible
across all tabs.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSpinBox, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QScrollArea, QFrame, QComboBox)
from PyQt5.QtCore    import Qt

from hardware.app_state      import app_state
from acquisition.roi         import Roi, SHAPE_RECT, SHAPE_ELLIPSE, SHAPE_FREEFORM
from acquisition.roi_model   import roi_model
from acquisition.roi_widget  import MultiRoiSelector
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE, scaled_qss, MONO_FONT
from ui.widgets.tab_helpers import make_sub


class RoiTab(QWidget):
    """
    Multi-ROI selection tab.

    Left  — interactive MultiRoiSelector (draw boxes on live image)
    Right — active ROI info, presets, manual entry, acquisition controls
    """

    def __init__(self):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- Left: multi-ROI selector canvas ----
        left = QVBoxLayout()
        sel_box = QGroupBox("Draw ROIs  (drag to add rect/ellipse, click to add freeform vertices)")
        sl = QVBoxLayout(sel_box)
        self._selector = MultiRoiSelector()
        sl.addWidget(self._selector)
        left.addWidget(sel_box)
        root.addLayout(left, 3)

        # ---- Right: controls (scrollable) ----
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setSpacing(8)
        right.setContentsMargins(0, 0, 0, 0)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right_widget)
        root.addWidget(right_scroll, 1)

        # Active ROI readout
        info_box = QGroupBox("Active ROI")
        il = QGridLayout(info_box)

        self._roi_labels = {}
        for r, (key, label) in enumerate([
                ("label", "Label"), ("shape", "Shape"),
                ("x",  "X origin"), ("y", "Y origin"),
                ("w",  "Width"),    ("h", "Height"),
                ("area", "Area"),   ("status", "Status")]):
            il.addWidget(self._sub(label), r, 0)
            lbl = QLabel("--")
            lbl.setStyleSheet(
                scaled_qss(f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{PALETTE['accent']};"))
            il.addWidget(lbl, r, 1)
            self._roi_labels[key] = lbl

        right.addWidget(info_box)

        # Preset ROIs (adds a new ROI each time)
        preset_box = QGroupBox("Add Preset ROI")
        pl = QVBoxLayout(preset_box)
        self._frame_hw = (1200, 1920)

        presets = [
            ("Centre 25%",    0.375, 0.375, 0.25,  0.25),
            ("Centre 50%",    0.25,  0.25,  0.50,  0.50),
            ("Top-left 25%",  0.0,   0.0,   0.25,  0.25),
            ("Top-right 25%", 0.75,  0.0,   0.25,  0.25),
        ]
        for label, rx, ry, rw, rh in presets:
            b = QPushButton(label)
            b.clicked.connect(
                lambda _, rx=rx, ry=ry, rw=rw, rh=rh:
                    self._add_preset(rx, ry, rw, rh))
            pl.addWidget(b)
        right.addWidget(preset_box)

        # Manual entry
        manual_box = QGroupBox("Add Manual ROI  (pixels)")
        ml = QGridLayout(manual_box)

        # Shape selector
        ml.addWidget(QLabel("Shape"), 0, 0)
        self._shape_combo = QComboBox()
        self._shape_combo.addItem("Rectangle", SHAPE_RECT)
        self._shape_combo.addItem("Ellipse", SHAPE_ELLIPSE)
        self._shape_combo.addItem("Freeform", SHAPE_FREEFORM)
        self._shape_combo.setFixedWidth(120)
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        ml.addWidget(self._shape_combo, 0, 1)

        self._mx = self._ispin(0, 9999, 0)
        self._my = self._ispin(0, 9999, 0)
        self._mw = self._ispin(1, 9999, 400)
        self._mh = self._ispin(1, 9999, 300)
        for r, (lbl, sp) in enumerate([
                ("X", self._mx), ("Y", self._my),
                ("W", self._mw), ("H", self._mh)], start=1):
            ml.addWidget(QLabel(lbl), r, 0)
            ml.addWidget(sp, r, 1)
        self._add_btn = QPushButton("Add ROI")
        self._add_btn.setObjectName("primary")
        self._add_btn.clicked.connect(self._add_manual)
        ml.addWidget(self._add_btn, 5, 0, 1, 2)

        # Freeform hint label (shown when freeform selected)
        self._freeform_hint = QLabel(
            "Draw on canvas: click to add vertices,\n"
            "double-click or click start to close.\n"
            "Esc to cancel, Enter to finish.")
        self._freeform_hint.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:8pt;")
        self._freeform_hint.setVisible(False)
        ml.addWidget(self._freeform_hint, 6, 0, 1, 2)
        right.addWidget(manual_box)

        # Apply to acquisition
        ctrl_box = QGroupBox("Acquisition")
        ctl = QVBoxLayout(ctrl_box)
        self._apply_acq_btn = QPushButton("Apply ROIs to Acquisition")
        set_btn_icon(self._apply_acq_btn, "fa5s.check", PALETTE['accent'])
        self._apply_acq_btn.setObjectName("primary")
        self._clear_acq_btn = QPushButton("Clear All  (use full frame)")
        set_btn_icon(self._clear_acq_btn, "fa5s.times")
        self._apply_acq_btn.clicked.connect(self._apply_to_acq)
        self._clear_acq_btn.clicked.connect(self._clear_acq)
        self._acq_status = QLabel("No ROIs active")
        self._acq_status.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
            f"color:{PALETTE['textSub']};")
        ctl.addWidget(self._apply_acq_btn)
        ctl.addWidget(self._clear_acq_btn)
        ctl.addWidget(self._acq_status)
        right.addWidget(ctrl_box)
        right.addStretch()

        # Wire model signals for info panel updates
        roi_model.rois_changed.connect(self._update_info)
        roi_model.active_changed.connect(lambda _: self._update_info())

    # ---------------------------------------------------------------- #

    def _apply_styles(self):
        acc = PALETTE['accent']
        sub = PALETTE['textSub']
        lbl_ss = scaled_qss(f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{acc};")
        for key, lbl in self._roi_labels.items():
            if key == "status" and lbl.text() not in ("--", ""):
                lbl.setStyleSheet(scaled_qss(
                    f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
                    f"color:{PALETTE['warning']};"))
            else:
                lbl.setStyleSheet(lbl_ss)
        set_btn_icon(self._apply_acq_btn, "fa5s.check", acc)
        if "Active" in self._acq_status.text():
            col = acc
        else:
            col = sub
        self._acq_status.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{col};")
        self._selector._apply_styles()

    def _sub(self, text):
        return make_sub(text)

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

    def _update_info(self):
        """Update info labels from the active ROI in the model."""
        roi = roi_model.active_roi
        if roi is None or roi.is_empty:
            for k, l in self._roi_labels.items():
                l.setText("--")
            count = roi_model.count
            if count:
                self._roi_labels["status"].setText(f"{count} ROI(s), none selected")
            else:
                self._roi_labels["status"].setText("Full frame")
            self._roi_labels["status"].setStyleSheet(
                scaled_qss(f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
                           f"color:{PALETTE['textSub']};"))
        else:
            self._roi_labels["label"].setText(roi.label or "(unnamed)")
            if roi.is_freeform:
                shape_display = f"Freeform ({len(roi.vertices)} pts)"
            elif roi.is_ellipse:
                shape_display = "Ellipse"
            else:
                shape_display = "Rectangle"
            self._roi_labels["shape"].setText(shape_display)
            self._roi_labels["x"].setText(str(roi.x))
            self._roi_labels["y"].setText(str(roi.y))
            self._roi_labels["w"].setText(str(roi.w))
            self._roi_labels["h"].setText(str(roi.h))
            self._roi_labels["area"].setText(f"{roi.area:,} px")
            self._roi_labels["status"].setText(
                f"ROI {roi_model.rois.index(roi) + 1} of {roi_model.count}")
            self._roi_labels["status"].setStyleSheet(
                scaled_qss(f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
                           f"color:{PALETTE['warning']};"))

    def _on_shape_changed(self, _index: int):
        """Push the selected shape to the canvas draw tool."""
        shape = self._shape_combo.currentData() or SHAPE_RECT
        self._selector.set_draw_shape(shape)
        is_freeform = (shape == SHAPE_FREEFORM)
        # Disable manual x/y/w/h entry for freeform — must draw on canvas
        self._mx.setEnabled(not is_freeform)
        self._my.setEnabled(not is_freeform)
        self._mw.setEnabled(not is_freeform)
        self._mh.setEnabled(not is_freeform)
        self._add_btn.setEnabled(not is_freeform)
        self._freeform_hint.setVisible(is_freeform)

    def _add_preset(self, rx, ry, rw, rh):
        fh, fw = self._frame_hw
        x = int(rx * fw)
        y = int(ry * fh)
        w = int(rw * fw)
        h = int(rh * fh)
        roi_model.add(Roi(x=x, y=y, w=w, h=h))

    def _add_manual(self):
        shape = self._shape_combo.currentData() or SHAPE_RECT
        roi = Roi(x=self._mx.value(), y=self._my.value(),
                  w=self._mw.value(), h=self._mh.value(),
                  shape=shape)
        roi_model.add(roi)

    def _apply_to_acq(self):
        """Apply the active ROI to the acquisition pipeline."""
        active = roi_model.active_roi
        pl = app_state.pipeline
        if pl:
            pl.roi = active if (active and not active.is_empty) else None
        count = roi_model.count
        if count:
            msg = f"{count} ROI(s) defined, active: {active}" if active else f"{count} ROI(s) defined"
        else:
            msg = "Full frame (no ROIs)"
        self._acq_status.setText(f"Active: {msg}")
        self._acq_status.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
            f"color:{PALETTE['accent']};")
        from ui.app_signals import signals
        signals.log_message.emit(f"ROIs applied to acquisition: {msg}")

    def _clear_acq(self):
        roi_model.clear()
        pl = app_state.pipeline
        if pl:
            pl.roi = None
        self._acq_status.setText("No ROIs active (full frame)")
        self._acq_status.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; "
            f"color:{PALETTE['textSub']};")
        from ui.app_signals import signals
        signals.log_message.emit("ROIs cleared \u2014 acquisition using full frame")
