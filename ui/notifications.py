"""
ui/notifications.py

Three-layer communication and notification system for SanjINSIGHT.

  1. StartupProgressDialog  — shows each device initializing with live pass/fail
  2. ToastNotification      — non-modal, actionable error/warning/info card
  3. ToastManager           — stacks toasts in the bottom-right of the window
  4. ERROR_GUIDANCE         — maps known error patterns to human-readable advice

Usage
-----
# At startup
dialog = StartupProgressDialog(expected_devices=["Camera", "FPGA", "TEC 1"])
dialog.show()
hw_service.startup_status.connect(dialog.on_device_status)

# For errors anywhere in the app
toast_manager.show_error("Camera: [Errno 10061]...")
toast_manager.show_warning("Exposure clamped to 50 ms")
toast_manager.show_info("Session saved to Desktop/measurements/")
"""

from __future__ import annotations

import re
from PyQt5.QtWidgets import (
    QDialog, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QFrame, QSizePolicy, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QPropertyAnimation,
    QEasingCurve, QRect, QPoint
)
from PyQt5.QtGui import QFont, QColor
from ui.theme import FONT, PALETTE, scaled_qss


# ================================================================== #
#  Error guidance database                                           #
# ================================================================== #
#
# Maps (regex pattern) → (title, bullet list of what to check)
# Patterns are matched case-insensitively against the raw error string.
# First match wins.

ERROR_GUIDANCE: list[tuple[str, str, list[str]]] = [

    # ── Camera ─────────────────────────────────────────────────────────
    (r"camera.*imaq|imaqdx|ni vision",
     "NI-IMAQdx Camera",
     ["Open NI MAX → Devices and Interfaces — is the camera listed?",
      "Check the USB or GigE cable connection to the camera",
      "Verify NI Vision Acquisition Software is installed",
      "Try unplugging and re-plugging the camera, then reconnect in Device Manager"]),

    (r"camera.*pypylon|basler",
     "Basler Camera",
     ["Open pylon Viewer — can it see the camera?",
      "Check the USB 3.0 or GigE cable",
      "Verify the pylon runtime is installed (pylon.baslerweb.com)",
      "On USB: try a different port or hub-free connection"]),

    (r"camera.*not found|no camera|camera.*unavailable",
     "Camera Not Found",
     ["Check that the camera is powered and the cable is connected",
      "Open Device Manager — does the camera appear (possibly with a yellow ⚠)?",
      "Try a different USB port or cable",
      "Restart the camera (power cycle if GigE, unplug/replug if USB)"]),

    (r"camera.*timeout|grab.*timeout",
     "Camera Timeout",
     ["The camera connected but stopped delivering frames",
      "Check for loose cable — even a brief disconnect causes this",
      "Reduce exposure time if it exceeds the frame timeout",
      "Restart the camera from the Device Manager tab"]),

    # ── FPGA ───────────────────────────────────────────────────────────
    (r"fpga.*bitfile|\.lvbitx.*not found|no such file.*lvbitx",
     "FPGA Bitfile Missing",
     ["The .lvbitx bitfile is not in the expected location",
      "Check config.yaml → hardware → fpga → bitfile_path",
      "Copy the bitfile from the Microsanj installation media to that path",
      "Contact Microsanj support if you do not have the bitfile"]),

    (r"fpga.*rio|nifpga|ni-rio|rio device",
     "NI-RIO / FPGA Driver",
     ["Verify NI-RIO drivers are installed (NI MAX → Software)",
      "Check the PCIe or USB RIO device appears in NI MAX → Devices",
      "Try running NI MAX → Self-Test on the RIO device",
      "Reboot after driver installation — RIO drivers require a restart"]),

    (r"fpga.*resource|rio.*resource",
     "FPGA Resource Conflict",
     ["Another application may have the FPGA open (LabVIEW, NI MAX)",
      "Close any NI MAX FPGA Interactive Front Panels",
      "Restart SanjINSIGHT — this releases the FPGA resource",
      "If the issue persists, reboot the PC"]),

    # ── TEC / Temperature Controller ───────────────────────────────────
    (r"tec.*serial|com\d+.*not found|serial.*port.*not found",
     "TEC Serial Port Not Found",
     ["Check config.yaml → hardware → tec → port (e.g. COM3)",
      "Open Device Manager → Ports (COM & LPT) — find the correct COM port",
      "Try unplugging and re-plugging the USB-to-serial adapter",
      "Ensure no other application (PuTTY, LabVIEW) has the port open"]),

    (r"tec.*timeout|meerstetter.*timeout|atec.*timeout",
     "TEC Communication Timeout",
     ["The TEC controller is not responding on the serial port",
      "Verify the correct COM port in config.yaml",
      "Check the cable between the PC and TEC controller",
      "Confirm the TEC controller is powered on (check front panel display)"]),

    (r"tec.*address|meerstetter.*address",
     "TEC Address Mismatch",
     ["Check config.yaml → hardware → tec → address matches the controller",
      "The default Meerstetter address is 1 (check the controller menu)",
      "If multiple TECs share one bus, each must have a unique address"]),

    # ── Bias Source ────────────────────────────────────────────────────
    (r"bias.*visa|pyvisa|visa.*not found",
     "VISA / Bias Source Driver",
     ["Verify NI-VISA or Keysight IO Libraries are installed",
      "Open NI MAX or Keysight Connection Expert — is the instrument listed?",
      "Check the GPIB, USB, or LAN cable to the bias source",
      "Verify the VISA resource string in config.yaml (e.g. GPIB0::24::INSTR)"]),

    (r"bias.*gpib|gpib.*not found|gpib.*timeout",
     "GPIB Communication Error",
     ["Check the GPIB cable and that the instrument address matches config.yaml",
      "Verify NI-488.2 GPIB driver is installed",
      "Only one controller can be the GPIB System Controller — check for conflicts",
      "Try running NI MAX → Scan for Instruments on the GPIB bus"]),

    # ── Stage ──────────────────────────────────────────────────────────
    (r"stage.*serial|thorlabs.*serial|stage.*com\d+",
     "Stage Serial Connection",
     ["Check config.yaml → hardware → stage → port",
      "Open Device Manager → Ports — find the Thorlabs APT USB port",
      "Thorlabs stages need the APT software installed for the USB driver",
      "Try unplugging and re-plugging the USB cable, then reconnect"]),

    (r"stage.*home|stage.*limit",
     "Stage Homing / Limit Error",
     ["The stage may be at a mechanical limit — move it away from the edge manually",
      "Check that the limit switch cables are connected (see stage wiring guide)",
      "Run the stage home command from the Stage tab after clearing the error"]),

    # ── Generic network / connection errors ────────────────────────────
    (r"errno 10061|connection refused",
     "Connection Refused",
     ["The target device is not accepting connections on this port",
      "Check the IP address and port in config.yaml",
      "Verify the device is powered on and its network interface is active",
      "Check that no firewall is blocking the connection"]),

    (r"errno 10060|timed out|connection timed out",
     "Network Timeout",
     ["The device did not respond in time",
      "Check the network cable and IP address in config.yaml",
      "Ping the device IP from Command Prompt: ping <device_ip>",
      "If on a dedicated instrument network, verify the subnet settings"]),

    # ── Generic fallback ───────────────────────────────────────────────
    (r"permission|access denied",
     "Permission Error",
     ["SanjINSIGHT may need to run as Administrator for this hardware",
      "Right-click SanjINSIGHT.exe → Run as Administrator",
      "Check that another application is not locking the resource",
      "Verify the hardware driver is installed for all users, not just one account"]),
]


def get_guidance(error_message: str) -> tuple[str, list[str]] | None:
    """
    Return (title, [bullet, ...]) for the first matching pattern,
    or None if no pattern matches.
    """
    msg = error_message.lower()
    for pattern, title, bullets in ERROR_GUIDANCE:
        if re.search(pattern, msg, re.IGNORECASE):
            return title, bullets
    return None


# ================================================================== #
#  1.  Startup Progress Dialog                                       #
# ================================================================== #

class _DeviceRow(QWidget):
    """Single row in the startup dialog: icon + name + status."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._icon = QLabel("○")
        self._icon.setFixedWidth(20)
        self._icon.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['readoutSm']}pt;")

        self._name = QLabel(name)
        self._name.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['heading']}pt;")
        self._name.setMinimumWidth(160)

        self._status = QLabel("Connecting…")
        self._status.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['body']}pt; font-style:italic;")

        lay.addWidget(self._icon)
        lay.addWidget(self._name)
        lay.addStretch()
        lay.addWidget(self._status)

        # Animated dots timer
        self._dot_count = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._animate)
        self._timer.start(400)

    def _animate(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        self._status.setText(f"Connecting{dots}")

    def set_ok(self, detail: str = ""):
        self._timer.stop()
        self._icon.setStyleSheet(
            f"color:{PALETTE['success']}; font-size:{FONT['readoutSm']}pt;")
        self._icon.setText("●")
        self._name.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt;")
        self._status.setStyleSheet(
            f"color:{PALETTE['success']}; font-size:{FONT['body']}pt;")
        self._status.setText(detail or "Connected")

    def set_failed(self, detail: str = ""):
        self._timer.stop()
        self._icon.setStyleSheet(
            f"color:{PALETTE['danger']}; font-size:{FONT['readoutSm']}pt;")
        self._icon.setText("●")
        self._name.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['heading']}pt;")
        self._status.setStyleSheet(
            f"color:{PALETTE['danger']}; font-size:{FONT['body']}pt;")
        self._status.setText(detail or "Failed")

    def set_skipped(self):
        self._timer.stop()
        self._icon.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:{FONT['readoutSm']}pt;")
        self._icon.setText("○")
        self._name.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['heading']}pt;")
        self._status.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['body']}pt; font-style:italic;")
        self._status.setText("Not configured")


class StartupProgressDialog(QDialog):
    """
    Shown during hardware initialization.
    Each device row shows connecting → connected / failed in real time.

    Usage
    -----
    dlg = StartupProgressDialog(parent=window)
    hw_service.startup_status.connect(dlg.on_device_status)
    dlg.show()                   # non-blocking
    # ... hardware initializes ...
    # dialog auto-closes 1.5 s after all devices report in
    """

    # Emitted when dialog is ready to close (all devices done)
    finished  = pyqtSignal()
    demo_requested = pyqtSignal()   # user clicked "Continue in Demo Mode"

    # Map config key → display name
    DEVICE_NAMES = {
        "camera":          "Camera",
        "fpga":            "FPGA",
        "tec0":            "TEC Controller 1",
        "tec1":            "TEC Controller 2",
        "tec_meerstetter": "TEC Controller 1",
        "tec_atec":        "TEC Controller 2",
        "bias":            "Bias Source",
        "stage":           "Stage",
    }

    def __init__(self, expected_devices: list[str], parent=None):
        """
        expected_devices: list of config keys (e.g. ['camera','fpga','tec0'])
        """
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setModal(False)
        self.setFixedWidth(440)

        self._expected = set(expected_devices)
        self._done     = set()
        self._rows: dict[str, _DeviceRow] = {}

        # ── Layout ────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._sp_header = QWidget()
        self._sp_header.setFixedHeight(52)
        h_lay = QHBoxLayout(self._sp_header)
        h_lay.setContentsMargins(16, 0, 16, 0)

        self._sp_title = QLabel("Starting SanjINSIGHT")
        self._sub_label = QLabel("Initializing hardware…")
        h_col = QVBoxLayout()
        h_col.setSpacing(2)
        h_col.addWidget(self._sp_title)
        h_col.addWidget(self._sub_label)
        h_lay.addLayout(h_col)
        h_lay.addStretch()
        root.addWidget(self._sp_header)

        # Device rows
        self._rows_widget = QWidget()
        rows_lay = QVBoxLayout(self._rows_widget)
        rows_lay.setContentsMargins(0, 8, 0, 8)
        rows_lay.setSpacing(2)

        for key in expected_devices:
            name = self.DEVICE_NAMES.get(key, key.title())
            row  = _DeviceRow(name)
            self._rows[key] = row
            rows_lay.addWidget(row)

        root.addWidget(self._rows_widget)

        # Footer
        self._sp_footer = QWidget()
        self._sp_footer.setFixedHeight(40)
        f_lay = QHBoxLayout(self._sp_footer)
        f_lay.setContentsMargins(16, 0, 16, 0)
        self._footer_label = QLabel("Connecting to hardware…")
        f_lay.addWidget(self._footer_label)
        f_lay.addStretch()

        self._skip_btn = QPushButton("Continue without hardware")
        self._skip_btn.setFixedHeight(24)
        self._skip_btn.clicked.connect(self._on_skip)
        f_lay.addWidget(self._skip_btn)

        # Demo mode button — hidden until a failure occurs
        self._demo_btn = QPushButton("▶  Demo Mode")
        self._demo_btn.setFixedHeight(28)
        self._demo_btn.setVisible(False)
        self._demo_btn.clicked.connect(self._on_demo)
        f_lay.addWidget(self._demo_btn)
        root.addWidget(self._sp_footer)

        self._apply_styles()
        self.adjustSize()

    def _apply_styles(self):
        """Re-apply all styles from PALETTE. Called on init and theme switch."""
        self.setStyleSheet(f"""
            QDialog {{
                background: {PALETTE['surface']};
                border: 1px solid {PALETTE['border']};
                border-radius: 6px;
            }}
        """)
        self._sp_header.setStyleSheet(
            f"background:{PALETTE['bg']}; border-bottom:1px solid {PALETTE['border']}; border-radius:0;")
        self._sp_title.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['readoutSm']}pt; "
            "font-family:'Helvetica Neue',Arial;")
        self._sub_label.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['label']}pt;")
        self._rows_widget.setStyleSheet(f"background:{PALETTE['surface']};")
        self._sp_footer.setStyleSheet(
            f"background:{PALETTE['bg']}; border-top:1px solid {PALETTE['border']};")
        self._footer_label.setStyleSheet(
            f"color:{PALETTE['textSub']}; font-size:{FONT['label']}pt;")
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{PALETTE['textSub']};
                border:none; font-size:{FONT['sublabel']}pt;
            }}
            QPushButton:hover {{ color:{PALETTE['textDim']}; }}
        """)
        self._demo_btn.setStyleSheet(f"""
            QPushButton {{
                background:{PALETTE['surface']}; color:{PALETTE['warning']};
                border:1px solid {PALETTE['warning']}55; border-radius:3px;
                font-size:{FONT['label']}pt; padding: 0 10px;
            }}
            QPushButton:hover {{
                background:{PALETTE['warnBg']}; color:{PALETTE['warning']};
                border-color:{PALETTE['warning']};
            }}
        """)

    def on_device_status(self, key: str, ok: bool, detail: str = ""):
        """
        Slot — call when a device reports its startup result.
        key: config key (e.g. 'camera', 'fpga', 'tec0')
        ok:  True = connected, False = failed
        detail: short message shown in the row
        """
        row = self._rows.get(key)
        if row is None:
            # Device not in expected list — add it dynamically
            name = self.DEVICE_NAMES.get(key, key.title())
            row  = _DeviceRow(name)
            self._rows[key] = row
            self._rows_widget.layout().addWidget(row)
            self.adjustSize()
            if self.parent():
                self._center_on_parent()

        if ok:
            row.set_ok(detail)
        else:
            row.set_failed(detail)

        self._done.add(key)
        self._check_complete()

    def mark_skipped(self, key: str):
        """Call for devices that are not configured (disabled in config)."""
        row = self._rows.get(key)
        if row:
            row.set_skipped()
        self._done.add(key)
        self._check_complete()

    def _check_complete(self):
        remaining = self._expected - self._done
        if not remaining:
            n_ok     = sum(1 for k in self._expected
                          if k in self._rows and
                          self._rows[k]._icon.text() == "●" and
                          PALETTE['success'] in self._rows[k]._icon.styleSheet())
            n_total  = len(self._expected)
            n_failed = n_total - n_ok

            if n_failed == 0:
                self._sub_label.setText("All hardware ready")
                self._sub_label.setStyleSheet(
                    f"color:{PALETTE['success']}; font-size:{FONT['label']}pt;")
                self._footer_label.setText(f"All {n_total} devices connected")
                delay = 1200
            else:
                self._sub_label.setText(
                    f"{n_failed} device(s) failed — check the Log tab for details")
                self._sub_label.setStyleSheet(
                    f"color:{PALETTE['warning']}; font-size:{FONT['label']}pt;")
                self._footer_label.setText(
                    f"{n_ok}/{n_total} connected  •  {n_failed} failed")
                self._footer_label.setStyleSheet(
                    f"color:{PALETTE['warning']}; font-size:{FONT['label']}pt;")
                # Show demo mode button
                self._demo_btn.setVisible(True)
                self.adjustSize()
                delay = 0   # don't auto-close — let user choose

            if delay:
                QTimer.singleShot(delay, self._auto_close)

    def _auto_close(self):
        self.finished.emit()
        self.accept()

    def _on_demo(self):
        self.demo_requested.emit()
        self.finished.emit()
        self.accept()

    def _on_skip(self):
        self.finished.emit()
        self.accept()

    def _center_on_parent(self):
        p = self.parent()
        if p:
            pc = p.geometry().center()
            self.move(pc.x() - self.width() // 2,
                      pc.y() - self.height() // 2)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_parent()


# ================================================================== #
#  2.  Toast Notification                                            #
# ================================================================== #

class ToastNotification(QWidget):
    """
    A single non-modal notification card.

    Shows:
      • Colored left border (severity)
      • Title + message
      • "What to check" expandable section for errors
      • Dismiss (×) button
      • Auto-dismiss timer (optional)

    Levels: 'error' | 'warning' | 'info' | 'success'
    """

    dismissed = pyqtSignal(object)   # emits self

    # Maps toast level → PALETTE key (read at call time so theme switches work)
    _LEVEL_KEY = {
        "error":   "danger",
        "warning": "warning",
        "info":    "info",
        "success": "success",
    }

    @staticmethod
    def level_color(level: str) -> str:
        return PALETTE[ToastNotification._LEVEL_KEY.get(level, "textDim")]
    ICONS = {
        "error":   "⊗",
        "warning": "⚠",
        "info":    "ℹ",
        "success": "✓",
    }

    def __init__(self, title: str, message: str, level: str = "error",
                 guidance: list[str] | None = None,
                 auto_dismiss_ms: int = 0,
                 parent=None):
        super().__init__(parent)
        self.setFixedWidth(380)

        color   = self.level_color(level)
        icon    = self.ICONS.get(level, "●")

        self.setStyleSheet(f"""
            QWidget {{
                background: {PALETTE['surface']};
                border: 1px solid {PALETTE['border']};
                border-left: 4px solid {color};
                border-radius: 4px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 10, 10)
        root.setSpacing(6)

        # ── Top row: icon + title + dismiss ───────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            f"color:{color}; font-size:{FONT['readoutSm']}pt; background:transparent; border:none;")
        icon_lbl.setFixedWidth(22)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color:{PALETTE['text']}; font-size:{FONT['body']}pt; font-weight:bold; "
            "background:transparent; border:none;")
        title_lbl.setWordWrap(True)

        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setStyleSheet(scaled_qss(f"""
            QPushButton {{
                background:transparent; color:{PALETTE['textSub']};
                border:none; font-size:15pt; padding:0;
            }}
            QPushButton:hover {{ color:{PALETTE['text']}; }}
        """))
        dismiss_btn.clicked.connect(self._dismiss)

        top.addWidget(icon_lbl)
        top.addWidget(title_lbl, 1)
        top.addWidget(dismiss_btn)
        root.addLayout(top)

        # ── Message ───────────────────────────────────────────────────
        if message:
            msg_lbl = QLabel(message)
            msg_lbl.setStyleSheet(
                f"color:{PALETTE['textDim']}; font-size:{FONT['label']}pt; "
                "background:transparent; border:none;")
            msg_lbl.setWordWrap(True)
            msg_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(msg_lbl)

        # ── Guidance (expandable) ─────────────────────────────────────
        if guidance:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(
                f"background:{PALETTE['border']}; border:none; max-height:1px;")
            root.addWidget(sep)

            guide_header = QLabel("What to check  ▸")
            guide_header.setStyleSheet(
                f"color:{PALETTE['textSub']}; font-size:{FONT['label']}pt; "
                "background:transparent; border:none;")
            guide_header.setCursor(Qt.PointingHandCursor)

            guide_body = QWidget()
            guide_body.setVisible(False)
            guide_body.setStyleSheet("background:transparent; border:none;")
            gb_lay = QVBoxLayout(guide_body)
            gb_lay.setContentsMargins(4, 4, 0, 0)
            gb_lay.setSpacing(4)
            for bullet in guidance:
                b = QLabel(f"• {bullet}")
                b.setStyleSheet(
                    f"color:{PALETTE['textDim']}; font-size:{FONT['sublabel']}pt; "
                    "background:transparent; border:none;")
                b.setWordWrap(True)
                gb_lay.addWidget(b)

            def _toggle(_=None):
                visible = not guide_body.isVisible()
                guide_body.setVisible(visible)
                guide_header.setText(
                    "What to check  ▾" if visible else "What to check  ▸")
                self.adjustSize()
                if hasattr(self.parent(), '_restack_toasts'):
                    self.parent()._restack_toasts()

            guide_header.mousePressEvent = _toggle

            root.addWidget(guide_header)
            root.addWidget(guide_body)

        self.adjustSize()

        # ── Auto-dismiss ──────────────────────────────────────────────
        if auto_dismiss_ms > 0:
            QTimer.singleShot(auto_dismiss_ms, self._dismiss)

    def _dismiss(self):
        self.dismissed.emit(self)
        self.deleteLater()


# ================================================================== #
#  3.  Toast Manager                                                 #
# ================================================================== #

class ToastManager(QObject):
    """
    Manages a vertical stack of ToastNotification widgets anchored to
    the bottom-right corner of a parent QWidget (the main window).

    Usage
    -----
    toast_manager = ToastManager(window)

    toast_manager.show_error("Camera: [Errno 10061] Connection refused")
    toast_manager.show_warning("Exposure clamped to maximum")
    toast_manager.show_info("Calibration loaded from profile")
    toast_manager.show_success("Session saved")
    """

    MARGIN   = 16   # pixels from window edge
    SPACING  = 8    # gap between stacked toasts
    MAX_TOASTS = 5  # discard oldest if queue exceeds this

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._window = parent_window
        self._toasts: list[ToastNotification] = []

        # Install event filter to reposition on window resize/move
        parent_window.installEventFilter(self)

    # ── Public API ─────────────────────────────────────────────────────

    def show_error(self, message: str, auto_dismiss_ms: int = 0):
        """
        Show an error toast.  Automatically looks up guidance for
        known error patterns.
        """
        guidance = None
        result = get_guidance(message)
        if result:
            title, guidance = result
        else:
            title = "Hardware Error"
        self._show(title, message, "error", guidance, auto_dismiss_ms)

    def show_warning(self, message: str, auto_dismiss_ms: int = 8000):
        self._show("Warning", message, "warning", None, auto_dismiss_ms)

    def show_info(self, message: str, auto_dismiss_ms: int = 5000):
        self._show("", message, "info", None, auto_dismiss_ms)

    def show_success(self, message: str, auto_dismiss_ms: int = 4000):
        self._show("", message, "success", None, auto_dismiss_ms)

    # ── Internal ───────────────────────────────────────────────────────

    def _show(self, title: str = "", message: str = "", level: str = "error",
              guidance: list[str] | None = None, auto_dismiss_ms: int = 0):
        # Deduplicate: if the same message is already showing, skip it.
        # This prevents identical hardware errors from flooding the UI.
        for existing in self._toasts:
            if (getattr(existing, '_msg_key', None) ==
                    f"{level}:{title}:{message}"):
                return

        # Prune if we already have too many
        while len(self._toasts) >= self.MAX_TOASTS:
            oldest = self._toasts.pop(0)
            oldest.dismissed.disconnect()
            oldest.deleteLater()

        toast = ToastNotification(
            title=title,
            message=message,
            level=level,
            guidance=guidance,
            auto_dismiss_ms=auto_dismiss_ms,
            parent=self._window
        )
        toast._msg_key = f"{level}:{title}:{message}"
        toast.dismissed.connect(self._on_dismissed)
        self._toasts.append(toast)
        toast.show()
        toast.raise_()
        self._restack_toasts()

    def _on_dismissed(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._restack_toasts()

    def _restack_toasts(self):
        """Position all visible toasts stacked from bottom-right.

        Toasts are children of the main window, so we use window-local
        coordinates (not mapToGlobal) to keep them anchored correctly
        regardless of window position on screen.

        The bottom offset accounts for the status bar and the bottom
        drawer toggle bar so toasts never overlap fixed UI chrome.
        The right offset accounts for the AI panel dock (when visible)
        so toasts don't float over the chat area.
        """
        win_rect = self._window.rect()

        # Compute right clearance: account for AI panel dock
        right_clearance = self.MARGIN
        ai_dock = getattr(self._window, '_ai_dock', None)
        if ai_dock and ai_dock.isVisible():
            right_clearance += ai_dock.width()
        right = win_rect.right() - right_clearance

        # Compute bottom clearance: status bar + drawer toggle bar
        bottom_clearance = self.MARGIN
        sb = self._window.statusBar() if hasattr(self._window, 'statusBar') else None
        if sb and sb.isVisible():
            bottom_clearance += sb.height()
        # Account for the drawer toggle bar (DrawerToggleBar, 34px)
        bar = getattr(self._window, '_drawer_toggle_bar', None)
        if bar and bar.isVisible():
            bottom_clearance += bar.height()

        bottom = win_rect.bottom() - bottom_clearance

        y = bottom
        for toast in reversed(self._toasts):
            toast.adjustSize()
            h = toast.height()
            w = toast.width()
            x = right - w
            y = y - h
            toast.move(x, y)
            y -= self.SPACING

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is self._window and event.type() in (
                QEvent.Resize, QEvent.Move, QEvent.Show):
            self._restack_toasts()
        return False
