"""
ui/autoscan/autoscan_mode.py

AutoScan mode — top-level container for the 3-screen guided scan workflow.

Architecture
------------
AutoScanMode (QWidget)
  └─ SidebarNav  [Scan | Settings]
       ├─ AutoScanFlow       ← 3-screen wizard (Configure → Preview → Results)
       └─ SettingsTab        ← fresh instance for Auto mode

AutoScanFlow (QWidget)
  ├─ AutoScanStepBar         ← 3-step progress indicator
  └─ QStackedWidget
       0: ConfigScreen       (Screen A)
       1: PreviewScreen      (Screen B)
       2: ResultsScreen      (Screen C)
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QStackedWidget)
from PyQt5.QtCore  import Qt, pyqtSignal
from PyQt5.QtGui   import QPainter, QColor, QPen, QFont

from ui.theme      import FONT, PALETTE
from ui.icons      import IC
from ui.sidebar_nav import SidebarNav, NavItem as NI


# ──────────────────────────────────────────────────────────────────── #
#  Step progress bar                                                    #
# ──────────────────────────────────────────────────────────────────── #

class AutoScanStepBar(QWidget):
    """3-step progress indicator: ① Configure → ② Preview → ③ Results.

    Reads PALETTE at paint time so it adapts to theme switches without
    needing an explicit ``_apply_styles()`` call.
    """

    STEPS = ["Configure", "Preview", "Results"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._current = 0

    def set_step(self, index: int) -> None:
        self._current = max(0, min(index, len(self.STEPS) - 1))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        bg_c   = QColor(PALETTE['bg'])
        bdr_c  = QColor(PALETTE['border'])
        surf_c = QColor(PALETTE['surface'])
        sub_c  = QColor(PALETTE['textSub'])
        txt_c  = QColor(PALETTE['text'])
        acc_c  = QColor(PALETTE['accent'])
        p.fillRect(0, 0, W, H, bg_c)

        n      = len(self.STEPS)
        step_w = W / n

        for i, label in enumerate(self.STEPS):
            cx = int(step_w * i + step_w / 2)
            cy = H // 2 - 6

            done   = i < self._current
            active = i == self._current

            # Connector line to previous step
            if i > 0:
                prev_cx = int(step_w * (i - 1) + step_w / 2)
                line_c  = acc_c if done else bdr_c
                p.setPen(QPen(line_c, 2))
                p.drawLine(prev_cx + 14, cy + 1, cx - 14, cy + 1)

            # Circle
            r = 12
            if active:
                p.setBrush(acc_c)
                p.setPen(QPen(acc_c, 2))
            elif done:
                p.setBrush(acc_c.darker(140))
                p.setPen(QPen(acc_c, 1))
            else:
                p.setBrush(surf_c)
                p.setPen(QPen(bdr_c, 1))
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            # Number or checkmark inside circle
            num_c = txt_c if (active or done) else sub_c
            p.setPen(QPen(num_c))
            fnt = QFont()
            fnt.setPointSize(int(FONT.get("label", 9)))
            fnt.setBold(active)
            p.setFont(fnt)
            p.drawText(cx - r, cy - r, r * 2, r * 2,
                       Qt.AlignCenter, "✓" if done else str(i + 1))

            # Step label below circle
            lbl_c = txt_c if active else sub_c
            p.setPen(QPen(lbl_c))
            lbl_fnt = QFont()
            lbl_fnt.setPointSize(int(FONT.get("label", 9)))
            lbl_fnt.setBold(active)
            p.setFont(lbl_fnt)
            p.drawText(cx - 60, cy + r + 4, 120, 16,
                       Qt.AlignCenter, label)


# ──────────────────────────────────────────────────────────────────── #
#  AutoScanFlow — 3-screen wizard                                       #
# ──────────────────────────────────────────────────────────────────── #

class AutoScanFlow(QWidget):
    """3-screen guided scan flow: Configure → Preview → Results.

    This widget is the content panel shown when the "Scan" nav item is
    selected in AutoScanMode.  It manages navigation between the three
    screens and routes signals up to main_app.
    """

    # Routed to main_app.py
    send_to_analysis = pyqtSignal(object)   # carries AcquisitionResult | ScanResult
    switch_to_manual = pyqtSignal()         # "Next →" action on Screen C
    scan_requested   = pyqtSignal(dict)     # config dict → main_app starts engine

    def __init__(self, parent=None):
        super().__init__(parent)

        # Import here to avoid circular imports at module level
        from ui.autoscan.config_screen  import ConfigScreen
        from ui.autoscan.preview_screen import PreviewScreen
        from ui.autoscan.results_screen import ResultsScreen

        self._screen_a = ConfigScreen()
        self._screen_b = PreviewScreen()
        self._screen_c = ResultsScreen()

        self._step_bar = AutoScanStepBar()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._screen_a)   # 0
        self._stack.addWidget(self._screen_b)   # 1
        self._stack.addWidget(self._screen_c)   # 2

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._step_bar)
        root.addWidget(self._stack, 1)

        # ── Internal navigation wiring ───────────────────────────
        # Screen A → B: start preview acquisition then show preview screen
        self._screen_a.preview_requested.connect(self._on_preview_requested)

        # Screen B → A: back
        self._screen_b.back_clicked.connect(lambda: self.go_to_screen(0))
        # Screen B → scan: emit scan_requested then start waiting for result
        self._screen_b.scan_requested.connect(self._on_scan_requested)

        # Screen C → B: back
        self._screen_c.back_clicked.connect(lambda: self.go_to_screen(1))
        # Screen C → A: new scan (reset)
        self._screen_c.new_scan_clicked.connect(self._on_new_scan)
        # Screen C → Analysis
        self._screen_c.send_to_analysis.connect(self.send_to_analysis)
        # Screen C → Manual
        self._screen_c.switch_to_manual.connect(self.switch_to_manual)

        # Carry config from A through to B (needed for scan_area selection)
        self._last_cfg: dict = {}

    # ── Screen navigation ────────────────────────────────────────────

    def go_to_screen(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._step_bar.set_step(index)

    # ── Internal handlers ────────────────────────────────────────────

    def _on_preview_requested(self, cfg: dict) -> None:
        """Screen A 'Preview and Scan →' pressed."""
        self._last_cfg = cfg
        self._screen_b.start_preview(cfg)
        self.go_to_screen(1)
        # Trigger a brief acquisition for the preview (10 frames)
        preview_cfg = dict(cfg, preview=True, n_frames=10)
        self.scan_requested.emit(preview_cfg)

    def _on_scan_requested(self, cfg: dict) -> None:
        """Screen B 'Scan →' pressed."""
        self._last_cfg = dict(self._last_cfg, **cfg)
        self._screen_b.set_scanning_state(True)
        self.scan_requested.emit(self._last_cfg)

    def _on_new_scan(self) -> None:
        """Screen C 'New AutoScan' — reset to Screen A, keep last config."""
        self._screen_a.restore_config(self._last_cfg)
        self.go_to_screen(0)

    # ── Public API (called by main_app via AutoScanMode) ─────────────

    def on_live_frame(self, frame) -> None:
        """Pass live frames to Screen B for display."""
        if self._stack.currentIndex() == 1:
            self._screen_b.update_frame(frame)

    def on_acq_complete(self, result) -> None:
        """Called when a brief preview acquisition finishes."""
        if self._stack.currentIndex() == 1:
            self._screen_b.set_analysis_result(result)

    def on_scan_complete(self, result) -> None:
        """Called when the full scan finishes — show Screen C."""
        if self._stack.currentIndex() != 2:
            self._screen_c.set_result(result)
            self.go_to_screen(2)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._step_bar.update()
        self._screen_a._apply_styles()
        self._screen_b._apply_styles()
        self._screen_c._apply_styles()


# ──────────────────────────────────────────────────────────────────── #
#  AutoScanMode — top-level Auto mode widget                            #
# ──────────────────────────────────────────────────────────────────── #

class AutoScanMode(QWidget):
    """Top-level container for Auto mode.

    Embeds a SidebarNav with two items:
      • Scan      → AutoScanFlow (the 3-screen guided workflow)
      • Settings  → SettingsTab  (fresh instance for Auto mode)

    Signals are bubbled up to MainWindow for cross-mode coordination.
    """

    send_to_analysis = pyqtSignal(object)   # push result to Analysis tab
    switch_to_manual = pyqtSignal()         # navigate to Manual mode
    theme_changed    = pyqtSignal(str)      # from inner SettingsTab

    def __init__(self, profile_mgr, hw_service, parent=None):
        super().__init__(parent)

        from ui.settings_tab import SettingsTab

        self._scan_flow    = AutoScanFlow()
        self._settings_tab = SettingsTab()

        self._nav = SidebarNav(app_name="SanjINSIGHT")
        self._nav.add_section("AUTOSCAN", [
            NI("Scan",     IC.NEW_SCAN, self._scan_flow),
        ])
        self._nav.add_section("", [
            NI("Settings", IC.SETTINGS, self._settings_tab),
        ])
        self._nav.finish()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._nav, 1)

        # Bubble signals upward
        self._scan_flow.send_to_analysis.connect(self.send_to_analysis)
        self._scan_flow.switch_to_manual.connect(self.switch_to_manual)
        self._settings_tab.theme_changed.connect(self.theme_changed)

    # ── Public API (called by main_app) ──────────────────────────────

    @property
    def scan_flow(self) -> AutoScanFlow:
        return self._scan_flow

    def on_live_frame(self, frame) -> None:
        self._scan_flow.on_live_frame(frame)

    def on_acq_complete(self, result) -> None:
        self._scan_flow.on_acq_complete(result)

    def on_scan_complete(self, result) -> None:
        self._scan_flow.on_scan_complete(result)

    def start_new_scan(self) -> None:
        """Navigate to the Scan item and reset to Screen A."""
        self._nav.navigate_to(self._scan_flow)
        self._scan_flow.go_to_screen(0)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        self._nav._apply_styles()
        self._settings_tab._apply_styles()
        self._scan_flow._apply_styles()
