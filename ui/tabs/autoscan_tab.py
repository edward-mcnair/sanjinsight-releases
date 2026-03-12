"""
ui/tabs/autoscan_tab.py

AutoScanTab — guided two-page scan workflow, first item under ACQUIRE.

Page 0  Configure & Preview
    Left  : _ReadinessPanel (stage homing · calibration · camera)
            + settings form (Goal / Stimulus / Scan Area / Speed / Advanced)
            + [  Preview  ]  button at bottom
    Right : _LiveImageView  (live thermal preview)
            + status label
            + [  Scan →  ]  button (disabled until preview completes)

Page 1  Results
    ResultsScreen (reused from ui/autoscan/results_screen.py)
"""

from __future__ import annotations

import threading

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QButtonGroup, QRadioButton, QDoubleSpinBox, QSpinBox,
    QSlider, QScrollArea, QSizePolicy, QFrame, QToolButton,
    QGroupBox, QStackedWidget, QSplitter, QProgressBar)
from PyQt5.QtCore  import Qt, pyqtSignal, QTimer
from PyQt5.QtGui   import QImage, QPixmap, QPainter, QColor

from ui.theme        import FONT, PALETTE, scaled_qss
from ui.icons        import IC, set_btn_icon
from ui.button_utils import apply_hand_cursor, RunningButton


# ── Helpers ──────────────────────────────────────────────────────────────────

def _group(title: str) -> QGroupBox:
    return QGroupBox(title)

def _seg_btn(label: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setFixedHeight(28)
    return btn


# ── Readiness panel ───────────────────────────────────────────────────────────

class _StatusRow(QWidget):
    """One readiness item: colored dot · status text · optional action button."""

    action_clicked = pyqtSignal()

    _COL = {"ok": "#00d479", "warn": "#ffb300", "err": "#ff4444", "dim": "#555555"}

    def __init__(self, action_text: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(7)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(12)
        self._txt = QLabel()
        self._txt.setWordWrap(True)
        self._txt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self._dot)
        lay.addWidget(self._txt)

        self._btn = None
        if action_text:
            self._btn = QPushButton(action_text)
            self._btn.setFixedHeight(22)
            self._btn.setFixedWidth(84)
            self._btn.setStyleSheet(scaled_qss(
                "QPushButton { font-size:9pt; padding:0 4px; }"))
            apply_hand_cursor(self._btn)
            self._btn.clicked.connect(self.action_clicked)
            lay.addWidget(self._btn)

    def set_status(self, state: str, text: str) -> None:
        col = self._COL.get(state, self._COL["dim"])
        self._dot.setStyleSheet(f"color:{col}; background:transparent;")
        active = state in ("ok", "warn", "err")
        self._txt.setStyleSheet(
            f"color:{'#ebebeb' if active else '#777'}; background:transparent; "
            f"font-size:{FONT.get('sublabel', 9)}pt;")
        self._txt.setText(text)

    def set_action_enabled(self, enabled: bool, label: str = "") -> None:
        if self._btn:
            self._btn.setEnabled(enabled)
            if label:
                self._btn.setText(label)

    def set_action_tooltip(self, text: str) -> None:
        """Set tooltip on both button and row widget (visible even when disabled)."""
        if self._btn:
            self._btn.setToolTip(text)
        self.setToolTip(text)


class _ReadinessPanel(QGroupBox):
    """Three status rows: Stage homing · Calibration · Camera/exposure."""

    def __init__(self, parent=None):
        super().__init__("Readiness", parent)
        lay = QVBoxLayout(self)
        lay.setSpacing(2)
        lay.setContentsMargins(10, 14, 10, 10)

        self._stage_row = _StatusRow(action_text="Home XY")
        self._cal_row   = _StatusRow()
        self._cam_row   = _StatusRow(action_text="Auto-Focus")

        lay.addWidget(self._stage_row)
        lay.addWidget(self._cal_row)
        lay.addWidget(self._cam_row)

        self._homing    = False
        self._af_driver = None
        self._af_running = False
        self._af_score: float | None = None

        self._stage_row.action_clicked.connect(self._do_home)
        self._cam_row.action_clicked.connect(self._on_af_clicked)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def refresh(self) -> None:
        try:
            from hardware.app_state import app_state

            # ── Stage ─────────────────────────────────────────────────
            stage = getattr(app_state, "stage", None)
            if stage is None:
                self._stage_row.set_status("dim",
                    "Stage — not connected  (single frame scan only)")
                self._stage_row.set_action_enabled(False)
            elif self._homing:
                self._stage_row.set_status("warn", "Stage — homing in progress…")
                self._stage_row.set_action_enabled(False, "Homing…")
            else:
                try:
                    homed = stage.get_status().homed
                except Exception:
                    homed = False
                if homed:
                    self._stage_row.set_status("ok", "Stage — homed ✓")
                    self._stage_row.set_action_enabled(False, "Home XY")
                else:
                    self._stage_row.set_status("warn",
                        "Stage not homed — ROI and Full Map scans require homing")
                    self._stage_row.set_action_enabled(True, "Home XY")

            # ── Calibration ───────────────────────────────────────────
            cal = getattr(app_state, "active_calibration", None)
            if cal and getattr(cal, "valid", False):
                self._cal_row.set_status("ok",
                    "Calibration loaded — ΔT results available ✓")
            else:
                self._cal_row.set_status("warn",
                    "No calibration — results shown as ΔR/R only  "
                    "(run via Analyze → Calibration)")

            # ── Camera / Exposure ─────────────────────────────────────
            cam   = getattr(app_state, "cam",   None)
            stage = getattr(app_state, "stage", None)
            if cam is None:
                self._cam_row.set_status("dim", "Camera — not connected")
                self._cam_row.set_action_enabled(False, "Auto-Focus")
                self._cam_row.set_action_tooltip("")
            elif not self._af_running:
                # Determine exposure text
                try:
                    st  = cam.get_status()
                    exp = getattr(st, "exposure_us", None)
                    exp_txt = f"  {exp/1000:.1f} ms" if exp is not None else ""
                except Exception:
                    exp_txt = ""

                if self._af_score is not None:
                    self._cam_row.set_status("ok",
                        f"Camera — focused ✓  score {self._af_score:.2f}{exp_txt}")
                    self._cam_row.set_action_enabled(bool(stage), "Re-Focus")
                    self._cam_row.set_action_tooltip(
                        "" if stage else "Autofocus requires a Z stage")
                elif stage:
                    self._cam_row.set_status("ok",
                        f"Camera ready{exp_txt}  — click Auto-Focus to optimise Z")
                    self._cam_row.set_action_enabled(True, "Auto-Focus")
                    self._cam_row.set_action_tooltip("")
                else:
                    self._cam_row.set_status("ok",
                        f"Camera ready{exp_txt}")
                    self._cam_row.set_action_enabled(False, "Auto-Focus")
                    self._cam_row.set_action_tooltip("Autofocus requires a Z stage")

        except Exception:
            pass

    def _do_home(self) -> None:
        self._homing = True
        self._stage_row.set_action_enabled(False, "Homing…")
        self._stage_row.set_status("warn", "Stage — homing in progress…")

        def _run():
            try:
                from hardware.app_state import app_state
                if getattr(app_state, "stage", None):
                    app_state.stage.home("xy")
            except Exception:
                pass
            finally:
                self._homing = False
                self.refresh()

        threading.Thread(target=_run, daemon=True).start()

    # ── Autofocus ─────────────────────────────────────────────────────────────

    def _on_af_clicked(self) -> None:
        if self._af_running:
            self._abort_af()
        else:
            self._start_af()

    def _start_af(self) -> None:
        from hardware.app_state import app_state
        cam   = getattr(app_state, "cam",   None)
        stage = getattr(app_state, "stage", None)
        if cam is None or stage is None:
            return

        from hardware.autofocus.factory import create_autofocus
        cfg = {
            "driver":    "sweep",
            "metric":    "laplacian",
            "z_start":   -200,
            "z_end":      200,
            "z_step":     25,
            "settle_ms":  80,
        }
        try:
            self._af_driver = create_autofocus(cfg, cam, stage)
        except Exception:
            return

        self._af_running = True
        self._af_score   = None
        self._cam_row.set_status("warn", "Camera — focusing…")
        self._cam_row.set_action_enabled(True, "Abort")

        def _run():
            result = self._af_driver.run()
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_af_complete(result))

        threading.Thread(target=_run, daemon=True).start()

    def _abort_af(self) -> None:
        if self._af_driver:
            self._af_driver.abort()

    def _on_af_complete(self, result) -> None:
        from hardware.autofocus.base import AfState
        from hardware.app_state import app_state
        self._af_running = False
        self._af_driver  = None
        stage = getattr(app_state, "stage", None)
        has_stage = bool(stage)

        if result.state == AfState.COMPLETE:
            self._af_score = result.best_score
            self._cam_row.set_status("ok",
                f"Camera — focused ✓  score {result.best_score:.2f}")
            self._cam_row.set_action_enabled(has_stage, "Re-Focus")
            self._cam_row.set_action_tooltip(
                "" if has_stage else "Autofocus requires a Z stage")
        elif result.state == AfState.ABORTED:
            self._cam_row.set_status("warn", "Camera — autofocus aborted")
            self._cam_row.set_action_enabled(has_stage, "Auto-Focus")
            self._cam_row.set_action_tooltip(
                "" if has_stage else "Autofocus requires a Z stage")
        else:
            msg = result.message or "unknown error"
            self._cam_row.set_status("err",
                f"Camera — autofocus failed  ({msg})")
            self._cam_row.set_action_enabled(has_stage, "Retry")
            self._cam_row.set_action_tooltip(
                "" if has_stage else "Autofocus requires a Z stage")


# ── Live image view ───────────────────────────────────────────────────────────

class _LiveImageView(QLabel):
    """QLabel that shows a thermal QPixmap; draws a placeholder when empty."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap_src: QPixmap | None = None

    def set_frame(self, pixmap: QPixmap) -> None:
        self._pixmap_src = pixmap
        self._rescale()

    def resizeEvent(self, e):
        self._rescale()
        super().resizeEvent(e)

    def _rescale(self):
        if self._pixmap_src:
            scaled = self._pixmap_src.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            super().setPixmap(scaled)

    def paintEvent(self, e):
        if self._pixmap_src is None:
            from hardware.app_state import app_state
            from ui.font_utils import sans_font
            cam_connected = app_state.cam is not None
            if cam_connected:
                msg = "Waiting for first frame…\n\nClick  Preview  to capture\na thermal image"
                color = PALETTE.get("textSub", "#6a6a6a")
            else:
                msg = "No camera connected\n\nConnect a camera via\nHardware → Camera"
                color = PALETTE.get("danger", "#ff5555")
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(PALETTE.get("surface", "#2d2d2d")))
            p.setPen(QColor(color))
            p.setFont(sans_font(13))
            p.drawText(self.rect(), Qt.AlignCenter, msg)
            p.end()
        else:
            super().paintEvent(e)


# ── AutoScanTab ───────────────────────────────────────────────────────────────

class AutoScanTab(QWidget):
    """
    Two-page guided scan workflow embedded as a standard nav tab.

    Page 0 — Configure & Preview (QSplitter)
    Page 1 — Results
    """

    scan_requested   = pyqtSignal(dict)    # → main_app._on_autoscan_scan_requested
    send_to_analysis = pyqtSignal(object)  # → main_app._on_autoscan_send_to_analysis
    abort_requested  = pyqtSignal()        # → main_app._on_autoscan_abort_requested

    def __init__(self, parent=None):
        super().__init__(parent)

        from ui.autoscan.results_screen import ResultsScreen
        self._results     = ResultsScreen()
        self._last_result = None
        self._current_op: str | None = None  # "preview" | "scan" | None

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_configure_page())  # 0
        self._stack.addWidget(self._results)                  # 1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._stack)

        # Results page wiring
        self._results.back_clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._results.new_scan_clicked.connect(self._on_new_scan)
        self._results.send_to_analysis.connect(self.send_to_analysis)
        self._results.switch_to_manual.connect(
            lambda: self.send_to_analysis.emit(self._last_result)
            if self._last_result else None)

        self._apply_styles()

    # ── Page 0: Configure + Preview ──────────────────────────────────────────

    def _build_configure_page(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([360, 640])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        return splitter

    # ── Left panel (settings) ─────────────────────────────────────────────────

    def _build_left(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(300)
        container.setMaximumWidth(420)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable area holds readiness + settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(12)

        # Readiness panel
        self._readiness = _ReadinessPanel()
        lay.addWidget(self._readiness)

        # Goal
        goal_grp = _group("Goal")
        g_lay = QHBoxLayout(goal_grp)
        g_lay.setSpacing(0)
        self._goal_find = _seg_btn("  Find Hotspots")
        self._goal_map  = _seg_btn("  Map Full Area")
        self._goal_find.setChecked(True)
        self._goal_find.setFixedWidth(140)
        self._goal_map.setFixedWidth(140)
        self._goal_grp = QButtonGroup(self)
        self._goal_grp.addButton(self._goal_find, 0)
        self._goal_grp.addButton(self._goal_map,  1)
        self._goal_grp.setExclusive(True)
        self._goal_grp.idClicked.connect(lambda _: self._refresh_seg_styles())
        g_lay.addWidget(self._goal_find)
        g_lay.addWidget(self._goal_map)
        g_lay.addStretch()
        lay.addWidget(goal_grp)

        # Stimulus
        stim_grp = _group("Stimulus")
        s_lay = QVBoxLayout(stim_grp)
        seg_row = QHBoxLayout()
        seg_row.setSpacing(0)
        self._stim_off    = _seg_btn("  Off")
        self._stim_dc     = _seg_btn("  DC")
        self._stim_pulsed = _seg_btn("  Pulsed")
        self._stim_off.setChecked(True)
        for b, w in [(self._stim_off, 70), (self._stim_dc, 70),
                     (self._stim_pulsed, 80)]:
            b.setFixedWidth(w)
            seg_row.addWidget(b)
        seg_row.addStretch()
        self._stim_grp = QButtonGroup(self)
        self._stim_grp.addButton(self._stim_off,    0)
        self._stim_grp.addButton(self._stim_dc,     1)
        self._stim_grp.addButton(self._stim_pulsed, 2)
        self._stim_grp.setExclusive(True)
        self._stim_grp.idClicked.connect(self._on_stim_changed)
        s_lay.addLayout(seg_row)

        self._stim_params = QWidget()
        vc_lay = QHBoxLayout(self._stim_params)
        vc_lay.setContentsMargins(0, 4, 0, 0)
        vc_lay.setSpacing(12)
        self._voltage = QDoubleSpinBox()
        self._voltage.setRange(-100, 100); self._voltage.setDecimals(3)
        self._voltage.setSuffix("  V"); self._voltage.setFixedWidth(110)
        self._current = QDoubleSpinBox()
        self._current.setRange(-5, 5); self._current.setDecimals(4)
        self._current.setSuffix("  A"); self._current.setFixedWidth(110)
        vc_lay.addWidget(QLabel("Voltage")); vc_lay.addWidget(self._voltage)
        vc_lay.addWidget(QLabel("Current")); vc_lay.addWidget(self._current)
        vc_lay.addStretch()
        self._stim_params.setVisible(False)
        s_lay.addWidget(self._stim_params)
        lay.addWidget(stim_grp)

        # Scan Area
        area_grp = _group("Scan Area")
        a_lay = QVBoxLayout(area_grp)
        a_lay.setSpacing(8)
        self._area_single = QRadioButton("Single frame  — no stage required")
        self._area_roi    = QRadioButton("ROI scan  — recommended")
        self._area_full   = QRadioButton("Full map  — ⚠ stage required")
        self._area_roi.setChecked(True)
        self._area_grp = QButtonGroup(self)
        for i, r in enumerate([self._area_single, self._area_roi, self._area_full]):
            self._area_grp.addButton(r, i)
            a_lay.addWidget(r)
        self._area_grp.setExclusive(True)
        lay.addWidget(area_grp)

        # Speed / Quality
        qual_grp = _group("Speed / Quality")
        q_lay = QVBoxLayout(qual_grp)
        self._quality_slider = QSlider(Qt.Horizontal)
        self._quality_slider.setRange(0, 4)
        self._quality_slider.setValue(2)
        self._quality_slider.setTickInterval(1)
        self._quality_slider.setTickPosition(QSlider.TicksBelow)
        self._quality_slider.valueChanged.connect(self._on_quality_changed)
        self._quality_lbl = QLabel("Balanced  (recommended)")
        self._quality_lbl.setAlignment(Qt.AlignCenter)
        lbl_row = QHBoxLayout()
        lbl_row.addWidget(QLabel("Fast"))
        lbl_row.addStretch()
        lbl_row.addWidget(self._quality_lbl)
        lbl_row.addStretch()
        lbl_row.addWidget(QLabel("Detailed"))
        q_lay.addWidget(self._quality_slider)
        q_lay.addLayout(lbl_row)
        lay.addWidget(qual_grp)

        # Advanced (collapsible)
        adv_grp = _group("")
        adv_outer = QVBoxLayout(adv_grp)
        adv_outer.setSpacing(4)
        self._adv_toggle = QToolButton()
        self._adv_toggle.setText("▸  Advanced options")
        self._adv_toggle.setCheckable(True)
        self._adv_toggle.setChecked(False)
        self._adv_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._adv_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._adv_toggle.toggled.connect(self._on_adv_toggled)
        adv_outer.addWidget(self._adv_toggle)

        self._adv_body = QWidget()
        adv_grid = QVBoxLayout(self._adv_body)
        adv_grid.setSpacing(6)

        def _adv_row(lbl, widget):
            r = QHBoxLayout()
            l = QLabel(lbl); l.setFixedWidth(130)
            r.addWidget(l); r.addWidget(widget); r.addStretch()
            adv_grid.addLayout(r)

        self._exposure = QDoubleSpinBox()
        self._exposure.setRange(0.1, 1000); self._exposure.setValue(10.0)
        self._exposure.setSuffix("  ms"); self._exposure.setFixedWidth(110)
        self._n_frames = QSpinBox()
        self._n_frames.setRange(5, 500); self._n_frames.setValue(20)
        self._n_frames.setSuffix("  frames"); self._n_frames.setFixedWidth(110)
        self._settle = QDoubleSpinBox()
        self._settle.setRange(0.1, 30); self._settle.setValue(0.5)
        self._settle.setSuffix("  s"); self._settle.setFixedWidth(110)

        _adv_row("Exposure",        self._exposure)
        _adv_row("Frames/position", self._n_frames)
        _adv_row("Settle time",     self._settle)
        self._adv_body.setVisible(False)
        adv_outer.addWidget(self._adv_body)
        lay.addWidget(adv_grp)
        lay.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # Preview button — fixed at bottom, outside scroll
        btn_bar = QWidget()
        btn_bar_lay = QHBoxLayout(btn_bar)
        btn_bar_lay.setContentsMargins(12, 6, 12, 10)
        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setObjectName("primary")
        self._preview_btn.setFixedHeight(36)
        set_btn_icon(self._preview_btn, IC.CAMERA)
        apply_hand_cursor(self._preview_btn)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_runner = RunningButton(self._preview_btn, idle_text="Preview")
        btn_bar_lay.addStretch()
        btn_bar_lay.addWidget(self._preview_btn)
        outer.addWidget(btn_bar)

        return container

    # ── Right panel (live preview image) ──────────────────────────────────────

    def _build_right(self) -> QWidget:
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._live_view = _LiveImageView()
        lay.addWidget(self._live_view, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status_lbl = QLabel("Configure settings and click Preview →")
        self._status_lbl.setObjectName("sublabel")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setWordWrap(True)
        lay.addWidget(self._status_lbl)

        # Scan + Abort buttons side-by-side
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._scan_btn = QPushButton("Scan  →")
        self._scan_btn.setObjectName("primary")
        self._scan_btn.setFixedHeight(40)
        self._scan_btn.setEnabled(False)
        set_btn_icon(self._scan_btn, IC.NEW_SCAN)
        apply_hand_cursor(self._scan_btn)
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        self._scan_runner = RunningButton(self._scan_btn, idle_text="Scan  →")

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setFixedHeight(40)
        self._abort_btn.setFixedWidth(80)
        self._abort_btn.setEnabled(False)
        set_btn_icon(self._abort_btn, IC.STOP, "#ff6666")
        apply_hand_cursor(self._abort_btn)
        self._abort_btn.clicked.connect(self._on_abort_clicked)

        btn_row.addWidget(self._scan_btn, 1)
        btn_row.addWidget(self._abort_btn)
        lay.addLayout(btn_row)

        return container

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_preview_clicked(self) -> None:
        self._current_op = "preview"
        self._preview_btn.setEnabled(False)
        self._preview_runner.set_running(True, "Capturing")
        self._scan_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._progress.setRange(0, 0)          # indeterminate until we know n_frames
        self._progress.setVisible(True)
        self._status_lbl.setText("Capturing preview…")
        self._live_view._pixmap_src = None
        self._live_view.update()
        cfg = self._build_config()
        self.scan_requested.emit(dict(cfg, preview=True, n_frames=10))

    def _on_scan_clicked(self) -> None:
        self._current_op = "scan"
        self._preview_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._scan_runner.set_running(True, "Scanning")
        self._abort_btn.setEnabled(True)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._status_lbl.setText("Scanning…")
        self.scan_requested.emit(self._build_config())

    def _on_abort_clicked(self) -> None:
        self._abort_btn.setEnabled(False)
        self._status_lbl.setText("Aborting…")
        self.abort_requested.emit()

    def _on_stim_changed(self, idx: int) -> None:
        self._stim_params.setVisible(idx > 0)
        self._refresh_seg_styles()

    def _on_quality_changed(self, val: int) -> None:
        labels = ["Fastest — fewer frames", "Fast", "Balanced  (recommended)",
                  "Detailed", "Highest detail — slowest"]
        self._quality_lbl.setText(labels[val])

    def _on_adv_toggled(self, checked: bool) -> None:
        self._adv_toggle.setText(("▾" if checked else "▸") + "  Advanced options")
        self._adv_body.setVisible(checked)

    def _on_new_scan(self) -> None:
        self._current_op = None
        self._scan_btn.setEnabled(False)
        self._scan_runner.set_running(False)
        self._preview_btn.setEnabled(True)
        self._preview_runner.set_running(False)
        self._abort_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._status_lbl.setText("Configure settings and click Preview →")
        self._live_view._pixmap_src = None
        self._live_view.update()
        self._stack.setCurrentIndex(0)

    # ── Public API (called by main_app) ───────────────────────────────────────

    def on_live_frame(self, frame) -> None:
        """Display a live frame in the preview panel (page 0 only).

        ``frame`` is a CameraFrame with ``data: uint16 (H, W)``.
        Normalise to 0-255 and show as grayscale so the user can verify
        focus and exposure before scanning.
        """
        if self._stack.currentIndex() != 0:
            return
        try:
            data = getattr(frame, "data", None)
            if data is None:
                return
            arr = data.astype(np.float32)
            lo, hi = float(arr.min()), float(arr.max())
            if hi > lo:
                arr = ((arr - lo) / (hi - lo) * 255).astype(np.uint8)
            else:
                arr = np.zeros(data.shape, dtype=np.uint8)
            h, w   = arr.shape[:2]
            rgb    = np.stack([arr, arr, arr], axis=-1)
            buf    = rgb.tobytes()
            qi     = QImage(buf, w, h, w * 3, QImage.Format_RGB888)
            self._live_view.set_frame(QPixmap.fromImage(qi))
        except Exception:
            pass

    def on_acq_progress(self, prog) -> None:
        """Frame-level acquisition progress — update progress bar."""
        if self._current_op != "preview":
            return
        total = getattr(prog, "total_frames", 0)
        idx   = getattr(prog, "frame_index",  0)
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(idx + 1)

    def on_acq_complete(self, result) -> None:
        """Brief preview acquisition finished — enable Scan button."""
        if self._stack.currentIndex() != 0 or self._current_op != "preview":
            return
        self._current_op = None
        self._preview_runner.set_running(False)
        self._preview_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._status_lbl.setText(
            "Preview complete — adjust settings or click Scan to begin")

    def on_scan_progress(self, prog) -> None:
        """Tile-level scan progress — update progress bar."""
        if self._current_op != "scan":
            return
        total = getattr(prog, "total_tiles", 0)
        tile  = getattr(prog, "tile",        0)
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(tile)
        msg = getattr(prog, "message", "")
        if msg:
            self._status_lbl.setText(msg)

    def on_scan_complete(self, result) -> None:
        """Full scan finished — switch to Results page."""
        if self._current_op != "scan":
            return
        self._current_op = None
        self._scan_runner.set_running(False)
        self._abort_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._last_result = result
        self._results.set_result(result)
        self._stack.setCurrentIndex(1)

    # ── Config helpers ────────────────────────────────────────────────────────

    def _build_config(self) -> dict:
        area_map = {0: "single", 1: "roi", 2: "full"}
        stim_map = {0: "off",    1: "dc",  2: "pulsed"}
        return {
            "goal":        "hotspots" if self._goal_find.isChecked() else "map",
            "stimulus":    stim_map[self._stim_grp.checkedId()],
            "voltage":     self._voltage.value(),
            "current":     self._current.value(),
            "scan_area":   area_map[self._area_grp.checkedId()],
            "quality":     self._quality_slider.value(),
            "exposure_ms": self._exposure.value(),
            "n_frames":    self._n_frames.value(),
            "settle_s":    self._settle.value(),
        }

    def restore_config(self, cfg: dict) -> None:
        if not cfg:
            return
        if cfg.get("goal") == "map":
            self._goal_map.setChecked(True)
        else:
            self._goal_find.setChecked(True)
        stim = {"off": 0, "dc": 1, "pulsed": 2}.get(cfg.get("stimulus", "off"), 0)
        self._stim_grp.button(stim).setChecked(True)
        self._stim_params.setVisible(stim > 0)
        if "voltage"     in cfg: self._voltage.setValue(cfg["voltage"])
        if "current"     in cfg: self._current.setValue(cfg["current"])
        area = {"single": 0, "roi": 1, "full": 2}.get(cfg.get("scan_area", "roi"), 1)
        self._area_grp.button(area).setChecked(True)
        if "quality"     in cfg: self._quality_slider.setValue(cfg["quality"])
        if "exposure_ms" in cfg: self._exposure.setValue(cfg["exposure_ms"])
        if "n_frames"    in cfg: self._n_frames.setValue(cfg["n_frames"])
        if "settle_s"    in cfg: self._settle.setValue(cfg["settle_s"])
        self._refresh_seg_styles()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P     = PALETTE
        text  = P.get("text",    "#ebebeb")
        dim   = P.get("textDim", "#999999")
        surf  = P.get("surface", "#2d2d2d")
        surf2 = P.get("surface2","#333333")
        bdr   = P.get("border",  "#484848")
        acc   = P.get("accent",  "#00d4aa")

        self.setStyleSheet(scaled_qss(f"""
            QScrollArea, QWidget {{ background:{P.get('bg','#242424')}; }}
            QLabel {{
                color:{text}; font-size:{FONT['body']}pt; background:transparent;
            }}
            QLabel[objectName="sublabel"] {{
                color:{dim}; font-size:{FONT['sublabel']}pt;
            }}
            QGroupBox {{
                color:{dim}; border:1px solid {bdr}; border-radius:6px;
                margin-top:8px; padding-top:10px;
                font-size:{FONT['label']}pt; font-weight:600;
            }}
            QGroupBox::title {{
                subcontrol-origin:margin; left:12px; padding:0 4px;
            }}
            QRadioButton {{
                color:{text}; font-size:{FONT['body']}pt;
                spacing:8px; background:transparent;
            }}
            QRadioButton::indicator {{
                width:14px; height:14px;
                border:2px solid {bdr}; border-radius:7px; background:{surf};
            }}
            QRadioButton::indicator:checked {{
                border-color:{acc}; background:{acc};
            }}
            QSlider::groove:horizontal {{
                height:4px; background:{surf2}; border-radius:2px;
            }}
            QSlider::handle:horizontal {{
                width:14px; height:14px; margin:-5px 0;
                border-radius:7px; background:{acc};
            }}
            QSlider::sub-page:horizontal {{
                background:{acc}; border-radius:2px;
            }}
            QDoubleSpinBox, QSpinBox {{
                background:{surf}; color:{text};
                border:1px solid {bdr}; border-radius:4px;
                padding:3px 6px; font-size:{FONT['body']}pt;
            }}
            QToolButton {{
                background:transparent; color:{dim};
                font-size:{FONT['body']}pt; border:none;
                text-align:left; padding:2px 0;
            }}
            QToolButton:hover {{ color:{text}; }}
        """))
        self._refresh_seg_styles()
        if hasattr(self, "_results"):
            self._results._apply_styles()

    def _refresh_seg_styles(self) -> None:
        P    = PALETTE
        surf = P.get("surface2", "#333333")
        dim  = P.get("textDim",  "#999999")
        bdr  = P.get("border",   "#484848")
        acc  = P.get("accent",   "#00d4aa")

        base = scaled_qss(f"""
            QPushButton {{
                background:{surf}; color:{dim};
                border:1px solid {bdr}; padding:4px 0;
                font-size:{FONT['label']}pt;
            }}
            QPushButton:checked {{ background:{acc}; color:#000; border-color:{acc}; }}
        """)

        self._goal_find.setStyleSheet(
            base + "QPushButton { border-radius:4px 0 0 4px; }")
        self._goal_map.setStyleSheet(
            base + "QPushButton { border-radius:0 4px 4px 0; border-left:none; }")
        self._stim_off.setStyleSheet(
            base + "QPushButton { border-radius:4px 0 0 4px; }")
        self._stim_dc.setStyleSheet(
            base + "QPushButton { border-radius:0; border-left:none; }")
        self._stim_pulsed.setStyleSheet(
            base + "QPushButton { border-radius:0 4px 4px 0; border-left:none; }")
