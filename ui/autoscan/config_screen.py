"""
ui/autoscan/config_screen.py

Screen A — Scan Configuration

Lets the operator choose:
  • Goal        : Find Hotspots | Map Full Area
  • Stimulus    : Off | DC | Pulsed  (+ voltage / current fields)
  • Scan Area   : Single frame | ROI scan | Full map
  • Speed/Quality slider
  • Advanced    : Exposure, Frames/position, Settle time  (collapsible)

Emits ``preview_requested(cfg: dict)`` when the "Preview and Scan →" button
is pressed.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QButtonGroup, QRadioButton, QDoubleSpinBox, QSpinBox,
    QSlider, QScrollArea, QSizePolicy, QFrame, QToolButton,
    QGroupBox)
from PyQt5.QtCore  import Qt, pyqtSignal
from PyQt5.QtGui   import QIcon

from ui.theme import FONT, PALETTE, scaled_qss
from ui.icons import make_icon, IC


# ── Helpers ──────────────────────────────────────────────────────────

def _group(title: str) -> QGroupBox:
    grp = QGroupBox(title)
    grp.setStyleSheet(_group_qss())
    return grp

def _group_qss() -> str:
    P = PALETTE
    return scaled_qss(f"""
        QGroupBox {{
            color: {P.get('textDim','#999999')};
            border: 1px solid {P.get('border','#484848')};
            border-radius: 6px;
            margin-top: 8px;
            padding-top: 10px;
            font-size: {FONT['label']}pt;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
        }}
    """)

def _seg_btn(label: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setFixedHeight(28)
    return btn

def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{PALETTE.get('border','#484848')};")
    return f


# ── Main widget ───────────────────────────────────────────────────────

class ConfigScreen(QWidget):
    """Screen A: scan configuration form."""

    preview_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── Scroll wrapper so small windows don't clip ────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        card = QWidget()
        card.setMaximumWidth(640)
        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(16)
        card_lay.setContentsMargins(24, 24, 24, 24)

        # ── Goal ─────────────────────────────────────────────────
        card_lay.addWidget(self._build_goal_group())

        # ── Stimulus ──────────────────────────────────────────────
        card_lay.addWidget(self._build_stimulus_group())

        # ── Scan Area ─────────────────────────────────────────────
        card_lay.addWidget(self._build_scan_area_group())

        # ── Speed / Quality ───────────────────────────────────────
        card_lay.addWidget(self._build_quality_group())

        # ── Advanced (collapsible) ────────────────────────────────
        card_lay.addWidget(self._build_advanced_group())

        card_lay.addStretch()

        # ── Footer: CTA button ────────────────────────────────────
        footer = QHBoxLayout()
        footer.addStretch()
        self._start_btn = QPushButton("Preview and Scan  →")
        self._start_btn.setFixedHeight(36)
        self._start_btn.setMinimumWidth(180)
        self._start_btn.clicked.connect(self._on_start)
        footer.addWidget(self._start_btn)
        card_lay.addLayout(footer)

        # Centre card in scroll area
        wrapper = QWidget()
        wrapper_lay = QHBoxLayout(wrapper)
        wrapper_lay.addStretch()
        wrapper_lay.addWidget(card)
        wrapper_lay.addStretch()

        scroll.setWidget(wrapper)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self._apply_styles()

    # ── Section builders ─────────────────────────────────────────────

    def _build_goal_group(self) -> QGroupBox:
        grp = _group("Goal")
        lay = QHBoxLayout(grp)
        lay.setSpacing(0)

        self._goal_find = _seg_btn("  Find Hotspots")
        self._goal_map  = _seg_btn("  Map Full Area")
        self._goal_find.setChecked(True)

        self._goal_grp = QButtonGroup(self)
        self._goal_grp.addButton(self._goal_find, 0)
        self._goal_grp.addButton(self._goal_map,  1)
        self._goal_grp.setExclusive(True)
        self._goal_grp.idClicked.connect(lambda _: self._refresh_seg_styles())

        for btn in (self._goal_find, self._goal_map):
            btn.setFixedWidth(140)
            lay.addWidget(btn)
        lay.addStretch()
        return grp

    def _build_stimulus_group(self) -> QGroupBox:
        grp = _group("Stimulus")
        lay = QVBoxLayout(grp)

        # Segmented: Off / DC / Pulsed
        seg_row = QHBoxLayout()
        self._stim_off    = _seg_btn("  Off")
        self._stim_dc     = _seg_btn("  DC")
        self._stim_pulsed = _seg_btn("  Pulsed")
        self._stim_off.setChecked(True)
        self._stim_off.setFixedWidth(80)
        self._stim_dc.setFixedWidth(80)
        self._stim_pulsed.setFixedWidth(80)

        self._stim_grp = QButtonGroup(self)
        self._stim_grp.addButton(self._stim_off,    0)
        self._stim_grp.addButton(self._stim_dc,     1)
        self._stim_grp.addButton(self._stim_pulsed, 2)
        self._stim_grp.setExclusive(True)
        self._stim_grp.idClicked.connect(self._on_stim_changed)

        seg_row.addWidget(self._stim_off)
        seg_row.addWidget(self._stim_dc)
        seg_row.addWidget(self._stim_pulsed)
        seg_row.addStretch()
        lay.addLayout(seg_row)

        # Voltage / Current (hidden when Off)
        self._stim_params = QWidget()
        params_lay = QHBoxLayout(self._stim_params)
        params_lay.setContentsMargins(0, 4, 0, 0)
        params_lay.setSpacing(16)

        v_lbl = QLabel("Voltage")
        self._voltage = QDoubleSpinBox()
        self._voltage.setRange(-100.0, 100.0)
        self._voltage.setSuffix("  V")
        self._voltage.setDecimals(3)
        self._voltage.setValue(0.0)
        self._voltage.setFixedWidth(110)

        i_lbl = QLabel("Current")
        self._current = QDoubleSpinBox()
        self._current.setRange(-5.0, 5.0)
        self._current.setSuffix("  A")
        self._current.setDecimals(4)
        self._current.setValue(0.0)
        self._current.setFixedWidth(110)

        params_lay.addWidget(v_lbl)
        params_lay.addWidget(self._voltage)
        params_lay.addWidget(i_lbl)
        params_lay.addWidget(self._current)
        params_lay.addStretch()
        self._stim_params.setVisible(False)
        lay.addWidget(self._stim_params)
        return grp

    def _build_scan_area_group(self) -> QGroupBox:
        grp = _group("Scan Area")
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        self._area_single = QRadioButton("Single frame  — no stage required")
        self._area_roi    = QRadioButton("ROI scan  — recommended")
        self._area_full   = QRadioButton("Full map  — ⚠ stage required")
        self._area_roi.setChecked(True)

        self._area_grp = QButtonGroup(self)
        self._area_grp.addButton(self._area_single, 0)
        self._area_grp.addButton(self._area_roi,    1)
        self._area_grp.addButton(self._area_full,   2)
        self._area_grp.setExclusive(True)

        for btn in (self._area_single, self._area_roi, self._area_full):
            lay.addWidget(btn)
        return grp

    def _build_quality_group(self) -> QGroupBox:
        grp = _group("Speed / Quality")
        lay = QVBoxLayout(grp)

        self._quality_slider = QSlider(Qt.Horizontal)
        self._quality_slider.setRange(0, 4)
        self._quality_slider.setValue(2)     # "Balanced"
        self._quality_slider.setTickInterval(1)
        self._quality_slider.setTickPosition(QSlider.TicksBelow)
        self._quality_slider.valueChanged.connect(self._on_quality_changed)

        labels_row = QHBoxLayout()
        labels_row.addWidget(QLabel("Fast"))
        labels_row.addStretch()
        self._quality_lbl = QLabel("Balanced  (recommended)")
        self._quality_lbl.setAlignment(Qt.AlignCenter)
        labels_row.addWidget(self._quality_lbl)
        labels_row.addStretch()
        labels_row.addWidget(QLabel("Detailed"))

        lay.addWidget(self._quality_slider)
        lay.addLayout(labels_row)
        return grp

    def _build_advanced_group(self) -> QGroupBox:
        grp = _group("")   # no title — toggle button acts as title
        lay = QVBoxLayout(grp)
        lay.setSpacing(6)

        self._adv_toggle = QToolButton()
        self._adv_toggle.setText("▸  Advanced options")
        self._adv_toggle.setCheckable(True)
        self._adv_toggle.setChecked(False)
        self._adv_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._adv_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._adv_toggle.toggled.connect(self._on_adv_toggled)
        lay.addWidget(self._adv_toggle)

        self._adv_body = QWidget()
        adv_lay = QGridLayout(self._adv_body)
        adv_lay.setSpacing(10)

        self._exposure = QDoubleSpinBox()
        self._exposure.setRange(0.1, 1000.0)
        self._exposure.setSuffix("  ms")
        self._exposure.setValue(10.0)
        self._exposure.setFixedWidth(110)

        self._n_frames = QSpinBox()
        self._n_frames.setRange(5, 500)
        self._n_frames.setValue(20)
        self._n_frames.setSuffix("  frames")
        self._n_frames.setFixedWidth(110)

        self._settle = QDoubleSpinBox()
        self._settle.setRange(0.1, 30.0)
        self._settle.setSuffix("  s")
        self._settle.setDecimals(1)
        self._settle.setValue(0.5)
        self._settle.setFixedWidth(110)

        adv_lay.addWidget(QLabel("Exposure"),       0, 0)
        adv_lay.addWidget(self._exposure,           0, 1)
        adv_lay.addWidget(QLabel("Frames/position"),1, 0)
        adv_lay.addWidget(self._n_frames,           1, 1)
        adv_lay.addWidget(QLabel("Settle time"),    2, 0)
        adv_lay.addWidget(self._settle,             2, 1)
        adv_lay.setColumnStretch(2, 1)

        self._adv_body.setVisible(False)
        lay.addWidget(self._adv_body)
        return grp

    # ── Event handlers ────────────────────────────────────────────────

    def _on_stim_changed(self, idx: int) -> None:
        self._stim_params.setVisible(idx > 0)
        self._refresh_seg_styles()

    def _on_quality_changed(self, val: int) -> None:
        labels = ["Fastest  — fewer frames", "Fast", "Balanced  (recommended)",
                  "Detailed", "Highest detail  — slowest"]
        self._quality_lbl.setText(labels[val])

    def _on_adv_toggled(self, checked: bool) -> None:
        self._adv_toggle.setText(("▾" if checked else "▸") + "  Advanced options")
        self._adv_body.setVisible(checked)

    def _on_start(self) -> None:
        self.preview_requested.emit(self.build_config())

    # ── Public API ────────────────────────────────────────────────────

    def build_config(self) -> dict:
        """Return a dict of current scan configuration."""
        stim_map = {0: "off", 1: "dc", 2: "pulsed"}
        area_map = {0: "single", 1: "roi", 2: "full"}
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
        """Restore controls from a previously built config dict."""
        if not cfg:
            return
        goal_map = {"hotspots": 0, "map": 1}
        self._goal_grp.button(goal_map.get(cfg.get("goal", "hotspots"), 0)).setChecked(True)

        stim_map = {"off": 0, "dc": 1, "pulsed": 2}
        self._stim_grp.button(stim_map.get(cfg.get("stimulus", "off"), 0)).setChecked(True)
        self._stim_params.setVisible(cfg.get("stimulus", "off") != "off")
        self._voltage.setValue(cfg.get("voltage", 0.0))
        self._current.setValue(cfg.get("current", 0.0))

        area_map = {"single": 0, "roi": 1, "full": 2}
        self._area_grp.button(area_map.get(cfg.get("scan_area", "roi"), 1)).setChecked(True)
        self._quality_slider.setValue(cfg.get("quality", 2))
        self._exposure.setValue(cfg.get("exposure_ms", 10.0))
        self._n_frames.setValue(cfg.get("n_frames", 20))
        self._settle.setValue(cfg.get("settle_s", 0.5))
        self._refresh_seg_styles()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        P     = PALETTE
        text  = P.get("text",    "#ebebeb")
        dim   = P.get("textDim", "#999999")
        surf  = P.get("surface", "#2d2d2d")
        surf2 = P.get("surface2","#333333")
        bdr   = P.get("border",  "#484848")
        acc   = P.get("accent",  "#00d4aa")

        self.setStyleSheet(scaled_qss(f"""
            QScrollArea, QWidget {{
                background: {P.get('bg','#242424')};
            }}
            QLabel {{
                color: {text}; font-size: {FONT['body']}pt;
                background: transparent;
            }}
            QGroupBox {{
                color: {dim}; border: 1px solid {bdr}; border-radius: 6px;
                margin-top: 8px; padding-top: 10px;
                font-size: {FONT['label']}pt; font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 12px; padding: 0 4px;
            }}
            QRadioButton {{
                color: {text}; font-size: {FONT['body']}pt;
                spacing: 8px; background: transparent;
            }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
                border: 2px solid {bdr}; border-radius: 7px;
                background: {surf};
            }}
            QRadioButton::indicator:checked {{
                border-color: {acc}; background: {acc};
            }}
            QSlider::groove:horizontal {{
                height: 4px; background: {surf2}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px; margin: -5px 0;
                border-radius: 7px; background: {acc};
            }}
            QSlider::sub-page:horizontal {{
                background: {acc}; border-radius: 2px;
            }}
            QDoubleSpinBox, QSpinBox {{
                background: {surf}; color: {text};
                border: 1px solid {bdr}; border-radius: 4px;
                padding: 3px 6px; font-size: {FONT['body']}pt;
            }}
            QToolButton {{
                background: transparent; color: {dim};
                font-size: {FONT['body']}pt; border: none;
                text-align: left; padding: 2px 0;
            }}
            QToolButton:hover {{ color: {text}; }}
        """))

        # CTA button
        self._start_btn.setStyleSheet(scaled_qss(f"""
            QPushButton {{
                background: {acc}; color: #000;
                border: none; border-radius: 5px;
                font-size: {FONT['body']}pt; font-weight: 700;
                padding: 0 20px;
            }}
            QPushButton:hover   {{ background: {P.get('accentHover', acc)}; }}
            QPushButton:pressed {{ background: {acc}; }}
        """))

        self._refresh_seg_styles()

    def _refresh_seg_styles(self) -> None:
        """Re-apply segmented button styles with current PALETTE."""
        P    = PALETTE
        surf = P.get("surface2", "#333333")
        dim  = P.get("textDim",  "#999999")
        bdr  = P.get("border",   "#484848")
        acc  = P.get("accent",   "#00d4aa")

        base = scaled_qss(f"""
            QPushButton {{
                background: {surf}; color: {dim};
                border: 1px solid {bdr}; padding: 4px 0;
                font-size: {FONT['label']}pt;
            }}
            QPushButton:checked {{ background: {acc}; color: #000; border-color: {acc}; }}
        """)

        # Goal buttons
        self._goal_find.setStyleSheet(base + "QPushButton { border-radius: 4px 0 0 4px; }")
        self._goal_map.setStyleSheet( base + "QPushButton { border-radius: 0 4px 4px 0; border-left: none; }")

        # Stimulus buttons
        self._stim_off.setStyleSheet(   base + "QPushButton { border-radius: 4px 0 0 4px; }")
        self._stim_dc.setStyleSheet(    base + "QPushButton { border-radius: 0; border-left: none; }")
        self._stim_pulsed.setStyleSheet(base + "QPushButton { border-radius: 0 4px 4px 0; border-left: none; }")
