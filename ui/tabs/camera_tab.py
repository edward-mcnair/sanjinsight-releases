"""
ui/tabs/camera_tab.py

CameraTab — live camera preview with exposure/gain controls and frame statistics.

Layout
------
Basic (always visible)
  • Live frame preview
  • Exposure slider + quick presets
  • Gain slider

Advanced (collapsible, hidden by default)
  • Display mode (Auto / 12-bit fixed)
  • Save Frame button

Frame Statistics (collapsible, hidden by default)
  • MIN / MAX / MEAN / FRAME readouts
"""

from __future__ import annotations

import time
import logging

log = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QSlider, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QButtonGroup, QRadioButton, QFrame, QComboBox,
    QFileDialog)
from PyQt5.QtCore    import Qt, QTimer

from hardware.app_state    import app_state
from ui.widgets.image_pane import ImagePane
from ui.widgets.collapsible_panel import CollapsiblePanel
from ui.theme import FONT, PALETTE
from ui.icons import set_btn_icon


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {PALETTE['border']};")
    return f


def _fmt_exp(us: int) -> str:
    """Format exposure value showing both ms and μs for clarity."""
    if us >= 1000:
        return f"{us / 1000:.1f} ms  ({us} μs)"
    return f"{us} μs"


class CameraTab(QWidget):
    def __init__(self, cam_info=None, hw_service=None):
        super().__init__()
        self._hw = hw_service
        self._last_frame = None
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        root.addLayout(top)

        # ── Image preview ─────────────────────────────────────────────
        img_box = QGroupBox("Frame")
        il = QVBoxLayout(img_box)
        self._pane = ImagePane("", 640, 480)
        il.addWidget(self._pane)
        top.addWidget(img_box, 3)

        # ── Controls ──────────────────────────────────────────────────
        ctrl_box = QGroupBox("Controls")
        cl = QGridLayout(ctrl_box)
        cl.setSpacing(10)

        from ui.help import help_label

        # Exposure (basic)
        cl.addWidget(help_label("Exposure (μs)", "exposure_us"), 0, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(50, 200000)
        self._exp_slider.setValue(5000)
        self._exp_lbl = QLabel(_fmt_exp(5000))
        self._exp_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")
        self._exp_slider.valueChanged.connect(
            lambda v: self._exp_lbl.setText(_fmt_exp(v)))
        self._exp_slider.sliderReleased.connect(self._on_exp)
        cl.addWidget(self._exp_slider, 0, 1)
        cl.addWidget(self._exp_lbl, 0, 2)

        # Exposure sub-label
        sub_exp = QLabel("image brightness  ·  longer = brighter, risk of saturation")
        sub_exp.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;")
        cl.addWidget(sub_exp, 1, 1, 1, 2)

        # Exposure presets
        pr = QHBoxLayout()
        for lbl, v in [("50μs", 50), ("1ms", 1000), ("5ms", 5000),
                       ("20ms", 20000), ("100ms", 100000)]:
            b = QPushButton(lbl)
            b.setFixedWidth(55)
            b.clicked.connect(lambda _, val=v: self._set_exp(val))
            pr.addWidget(b)
        pr.addStretch()
        cl.addLayout(pr, 2, 1)

        # Gain (basic)
        cl.addWidget(help_label("Gain (dB)", "gain_db"), 3, 0)
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 239)
        self._gain_slider.setValue(0)
        self._gain_lbl = QLabel("0.0")
        self._gain_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt; color:{PALETTE['accent']};")
        self._gain_slider.valueChanged.connect(
            lambda v: self._gain_lbl.setText(f"{v/10:.1f}"))
        self._gain_slider.sliderReleased.connect(self._on_gain)
        cl.addWidget(self._gain_slider, 3, 1)
        cl.addWidget(self._gain_lbl, 3, 2)

        # Gain sub-label
        sub_gain = QLabel("amplification  ·  0 dB ideal for best SNR")
        sub_gain.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; padding-left:2px;")
        cl.addWidget(sub_gain, 4, 1, 1, 2)

        # ── Objective Turret selector (row 5 — only shown when turret connected) ──
        self._obj_label = help_label("Objective", "objective_turret")
        self._obj_combo = QComboBox()
        self._obj_combo.setFixedWidth(180)
        self._obj_combo.setToolTip(
            "Select the active objective lens on the motorized turret.\n"
            "Changing the objective updates the field of view and pixel size.")
        self._obj_combo.currentIndexChanged.connect(self._on_objective_changed)

        self._obj_fov_lbl = QLabel("")
        self._obj_fov_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']}; "
            f"padding-left:2px;")

        # These widgets are hidden when no turret is connected
        self._obj_label.setVisible(False)
        self._obj_combo.setVisible(False)
        self._obj_fov_lbl.setVisible(False)

        cl.addWidget(self._obj_label,   5, 0)
        cl.addWidget(self._obj_combo,   5, 1)
        cl.addWidget(self._obj_fov_lbl, 6, 1, 1, 2)

        # ── Advanced section (collapsible) ────────────────────────────
        adv_panel = CollapsiblePanel("Display & save", start_collapsed=True)

        adv_inner = QWidget()
        adv_grid  = QGridLayout(adv_inner)
        adv_grid.setContentsMargins(0, 0, 0, 0)
        adv_grid.setSpacing(8)

        adv_grid.addWidget(QLabel("Display mode"), 0, 0)
        self._bg = QButtonGroup()
        dr = QHBoxLayout()
        for i, m in enumerate(["Auto contrast", "12-bit fixed"]):
            rb = QRadioButton(m)
            self._bg.addButton(rb, i)
            dr.addWidget(rb)
        self._bg.button(0).setChecked(True)
        dr.addStretch()
        adv_grid.addLayout(dr, 0, 1)

        save_btn = QPushButton("Save Frame…")
        set_btn_icon(save_btn, "fa5s.save")
        save_btn.setToolTip("Save the current frame as a 16-bit PNG file")
        save_btn.clicked.connect(self._save)
        adv_grid.addWidget(save_btn, 1, 1)

        adv_panel.addWidget(adv_inner)
        cl.addWidget(adv_panel, 7, 0, 1, 3)

        top.addWidget(ctrl_box, 1)

        # ── Signal Quality strip (always visible) ─────────────────────
        qual_box = QGroupBox("Signal Quality")
        ql = QHBoxLayout(qual_box)
        ql.setContentsMargins(10, 6, 10, 6)
        ql.setSpacing(24)

        self._qual_exp_lbl = QLabel("EXPOSURE  —")
        self._qual_exp_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['label']}pt; "
            f"color:{PALETTE['textDim']};")
        self._qual_sat_lbl = QLabel("SATURATION  —")
        self._qual_sat_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['label']}pt; "
            f"color:{PALETTE['textDim']};")
        ql.addWidget(self._qual_exp_lbl)
        ql.addWidget(self._qual_sat_lbl)
        ql.addStretch()
        root.addWidget(qual_box)

        # ── Simulated Camera panel (visible only when driver == "simulated") ──
        self._simcam_panel = CollapsiblePanel(
            "Simulated Camera", start_collapsed=False)

        simcam_inner = QWidget()
        simcam_grid  = QGridLayout(simcam_inner)
        simcam_grid.setContentsMargins(0, 4, 0, 0)
        simcam_grid.setSpacing(8)

        # Current resolution readout
        simcam_grid.addWidget(QLabel("Resolution"), 0, 0)
        self._simcam_res_lbl = QLabel("—")
        self._simcam_res_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt;"
            f" color:{PALETTE['accent']};")
        simcam_grid.addWidget(self._simcam_res_lbl, 0, 1)

        # Resolution preset buttons
        _PRESETS = [
            ("320×240",    320,  240),
            ("640×480",    640,  480),
            ("1280×720",  1280,  720),
            ("1920×1080", 1920, 1080),
            ("3840×2160", 3840, 2160),
        ]
        pr2 = QHBoxLayout()
        for lbl, w, h in _PRESETS:
            b = QPushButton(lbl)
            b.setFixedWidth(80)
            b.clicked.connect(lambda _, ww=w, hh=h: self._set_simcam_res(ww, hh))
            pr2.addWidget(b)
        pr2.addStretch()
        simcam_grid.addLayout(pr2, 1, 1)

        sub_res = QLabel("lower = faster, higher = more detail  ·  applied immediately")
        sub_res.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};"
            f" padding-left:2px;")
        simcam_grid.addWidget(sub_res, 2, 1)

        # FPS slider
        simcam_grid.addWidget(QLabel("Frame rate"), 3, 0)
        self._simcam_fps_slider = QSlider(Qt.Horizontal)
        self._simcam_fps_slider.setRange(5, 60)
        self._simcam_fps_slider.setValue(30)
        self._simcam_fps_lbl = QLabel("30 fps")
        self._simcam_fps_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt;"
            f" color:{PALETTE['accent']};")
        self._simcam_fps_slider.valueChanged.connect(
            lambda v: self._simcam_fps_lbl.setText(f"{v} fps"))
        self._simcam_fps_slider.sliderReleased.connect(self._on_simcam_fps)
        simcam_grid.addWidget(self._simcam_fps_slider, 3, 1)
        simcam_grid.addWidget(self._simcam_fps_lbl, 3, 2)

        sub_fps = QLabel("higher fps = smoother preview but more CPU  ·  max 60 fps")
        sub_fps.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};"
            f" padding-left:2px;")
        simcam_grid.addWidget(sub_fps, 4, 1)

        self._simcam_panel.addWidget(simcam_inner)
        self._simcam_panel.setVisible(False)   # shown only for simulated driver
        root.addWidget(self._simcam_panel)

        # ── Frame Statistics (collapsible) ────────────────────────────
        stats_panel = CollapsiblePanel("Frame statistics", start_collapsed=True)

        stats_row = QWidget()
        stats_lay = QHBoxLayout(stats_row)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        self._stat_min  = self._stat_widget("MIN")
        self._stat_max  = self._stat_widget("MAX")
        self._stat_mean = self._stat_widget("MEAN")
        self._stat_idx  = self._stat_widget("FRAME")
        self._sat_w     = self._stat_widget("SATURATION")
        for w in [self._stat_min, self._stat_max,
                  self._stat_mean, self._stat_idx, self._sat_w]:
            stats_lay.addWidget(w)

        stats_panel.addWidget(stats_row)
        root.addWidget(stats_panel)

    # ── Stat readout widget ────────────────────────────────────────────

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

    # ── Slots ─────────────────────────────────────────────────────────

    def update_frame(self, frame):
        from ai.instrument_knowledge import CAMERA_SAT_LIMIT, CAMERA_SAT_WARN
        self._last_frame = frame
        d = frame.data
        mode = "auto" if self._bg.checkedId() == 0 else "fixed"
        self._pane.show_array(d, mode=mode)
        self._stat_min._val.setText(str(int(d.min())))
        self._stat_max._val.setText(str(int(d.max())))
        self._stat_mean._val.setText(f"{d.mean():.1f}")
        self._stat_idx._val.setText(str(frame.frame_index))

        # Saturation guard (12-bit sensor: 4095 = clipped)
        mx = int(d.max())
        sat_pct = float((d >= CAMERA_SAT_LIMIT).sum()) / max(d.size, 1) * 100
        if mx >= CAMERA_SAT_LIMIT:
            self._sat_w._val.setText("CLIPPED ✗")
            color = PALETTE["danger"]
        elif mx >= CAMERA_SAT_WARN:
            self._sat_w._val.setText(f"{sat_pct:.2f}%")
            color = PALETTE["warning"]
        else:
            self._sat_w._val.setText("OK")
            color = PALETTE["success"]
        self._sat_w._val.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['readoutSm']}pt;"
            f" color:{color};")

        # Update always-visible quality strip
        mean_val = float(d.mean())
        if mx >= CAMERA_SAT_LIMIT:
            exp_color = PALETTE["danger"]
            exp_text  = "EXPOSURE  SATURATED ✗"
        elif mx >= CAMERA_SAT_WARN:
            exp_color = PALETTE["warning"]
            exp_text  = "EXPOSURE  NEAR SAT ⚠"
        elif mean_val < 200:
            exp_color = PALETTE["warning"]
            exp_text  = "EXPOSURE  DARK ⚠"
        else:
            exp_color = PALETTE["success"]
            exp_text  = "EXPOSURE  OK ✓"
        self._qual_exp_lbl.setText(exp_text)
        self._qual_exp_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['label']}pt; color:{exp_color};")

        if mx >= CAMERA_SAT_LIMIT:
            sat_color = PALETTE["danger"]
            sat_text  = "SATURATION  CLIPPED ✗"
        elif mx >= CAMERA_SAT_WARN:
            sat_color = PALETTE["warning"]
            sat_text  = f"SATURATION  {sat_pct:.2f}% ⚠"
        else:
            sat_color = PALETTE["success"]
            sat_text  = "SATURATION  OK ✓"
        self._qual_sat_lbl.setText(sat_text)
        self._qual_sat_lbl.setStyleSheet(
            f"font-family:Menlo,monospace; font-size:{FONT['label']}pt; color:{sat_color};")

    def _set_exp(self, val):
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def _on_exp(self):
        self._do_exp(self._exp_slider.value())

    def _do_exp(self, val):
        if self._hw:
            self._hw.cam_set_exposure(float(val))
        else:
            cam = app_state.cam
            if cam:
                cam.set_exposure(float(val))

    def _on_gain(self):
        val = self._gain_slider.value() / 10.0
        if self._hw:
            self._hw.cam_set_gain(val)
        else:
            cam = app_state.cam
            if cam:
                cam.set_gain(val)

    def _save(self):
        import cv2
        frame = self._last_frame
        if frame is None:
            return
        default = f"frame_{int(time.time())}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Frame", default,
            "PNG image (*.png);;16-bit TIFF (*.tiff *.tif);;All files (*)")
        if not path:
            return
        cv2.imwrite(path, frame.data)
        from ui.app_signals import signals
        signals.log_message.emit(f"Saved: {path}")

    # ── Simulated camera controls ──────────────────────────────────────

    def _refresh_simcam(self):
        """Show/hide the Simulated Camera panel and sync controls to current state."""
        cam    = app_state.cam
        is_sim = (cam is not None and
                  getattr(cam, "supports_runtime_resolution", lambda: False)())
        self._simcam_panel.setVisible(is_sim)
        if not is_sim:
            return
        w   = cam.info.width
        h   = cam.info.height
        fps = max(5, min(60, int(round(cam.info.max_fps))))
        self._simcam_res_lbl.setText(f"{w} × {h}")
        self._simcam_fps_slider.blockSignals(True)
        self._simcam_fps_slider.setValue(fps)
        self._simcam_fps_slider.blockSignals(False)
        self._simcam_fps_lbl.setText(f"{fps} fps")

    def _set_simcam_res(self, width: int, height: int):
        """Apply a resolution preset to the simulated camera and persist."""
        if self._hw:
            self._hw.cam_set_resolution(width, height)
        else:
            cam = app_state.cam
            if cam and hasattr(cam, "set_resolution"):
                cam.set_resolution(width, height)
        self._simcam_res_lbl.setText(f"{width} × {height}")
        import config as _cfg
        _cfg.update_camera_config({"width": width, "height": height})

    def _on_simcam_fps(self):
        """Apply the FPS slider value to the simulated camera and persist."""
        fps = self._simcam_fps_slider.value()
        if self._hw:
            self._hw.cam_set_fps(float(fps))
        else:
            cam = app_state.cam
            if cam and hasattr(cam, "set_fps"):
                cam.set_fps(float(fps))
        import config as _cfg
        _cfg.update_camera_config({"fps": fps})

    # ── Objective turret ───────────────────────────────────────────────

    def showEvent(self, e):
        self._refresh_turret()
        self._refresh_simcam()
        super().showEvent(e)

    def _refresh_turret(self):
        """Populate the objective combo box from the connected turret."""
        turret = app_state.turret
        has_turret = turret is not None
        self._obj_label.setVisible(has_turret)
        self._obj_combo.setVisible(has_turret)
        self._obj_fov_lbl.setVisible(has_turret)

        if not has_turret:
            return

        # Populate combo without triggering _on_objective_changed
        self._obj_combo.blockSignals(True)
        self._obj_combo.clear()
        try:
            objectives = turret.list_objectives()
            for obj in objectives:
                self._obj_combo.addItem(obj.label, userData=obj)

            # Select current objective
            cur_pos = turret.get_position()
            for i in range(self._obj_combo.count()):
                obj = self._obj_combo.itemData(i)
                if obj is not None and obj.position == cur_pos:
                    self._obj_combo.setCurrentIndex(i)
                    self._update_fov_label(obj)
                    break
        except Exception:
            pass
        self._obj_combo.blockSignals(False)

    def _on_objective_changed(self, index: int):
        """Called when user selects a different objective in the combo."""
        if index < 0:
            return
        obj = self._obj_combo.itemData(index)
        if obj is None:
            return

        self._update_fov_label(obj)

        # Move turret in background thread
        turret = app_state.turret
        if turret is None:
            return

        import threading

        # Disable the combo so the user can't queue another move while this
        # one is in progress, and replace the FOV label with a live status.
        self._obj_combo.setEnabled(False)
        self._obj_fov_lbl.setText("Moving turret…")
        self._obj_fov_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; "
            f"color:{PALETTE['warning']}; padding-left:2px;")

        def _move():
            try:
                turret.move_to(obj.position)
                app_state.active_objective = obj
            except Exception as exc:
                log.warning("Turret move error: %s", exc)
            finally:
                # Re-enable the combo and restore the FOV readout.
                QTimer.singleShot(0, lambda: self._obj_combo.setEnabled(True))
                QTimer.singleShot(0, lambda: self._update_fov_label(obj))

        threading.Thread(target=_move, daemon=True).start()

    def _update_fov_label(self, obj):
        """Update the FOV / pixel-size caption below the combo box."""
        try:
            fov  = obj.fov_um()
            px   = obj.px_size_um()
            self._obj_fov_lbl.setText(
                f"FOV ≈ {fov:.0f} µm wide   ·   pixel ≈ {px:.3f} µm")
        except Exception:
            self._obj_fov_lbl.setText("")

    def set_exposure(self, us: float):
        """Push a new exposure value from an external source (e.g. profile)."""
        val = int(max(50, min(200000, us)))
        self._exp_slider.setValue(val)
        self._do_exp(val)

    def set_gain(self, db: float):
        """Push a new gain value from an external source (e.g. profile)."""
        val = int(max(0, min(239, db * 10)))
        self._gain_slider.setValue(val)
        if self._hw:
            self._hw.cam_set_gain(db)
        else:
            cam = app_state.cam
            if cam:
                cam.set_gain(db)
