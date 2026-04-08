"""
ui/widgets/connection_health_panel.py

Real-time connection health dashboard for all configured hardware devices.

Displays a scrollable list of device rows with coloured status indicators,
port/address info, error messages, and per-device reconnect buttons.

Usage
-----
    panel = ConnectionHealthPanel()
    panel.update_device("tec_0", STATE_CONNECTED, "COM3", None, time.time())
    panel.update_all({
        "tec_0": {"state": "connected", "port": "COM3", ...},
        "cam_0": {"state": "error", "port": "USB", "error": "Timeout"},
    })
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from ui.theme import PALETTE, FONT

log = logging.getLogger(__name__)

# ── State constants ──────────────────────────────────────────────────────────

STATE_CONNECTED  = "connected"
STATE_CONNECTING = "connecting"
STATE_ERROR      = "error"
STATE_ABSENT     = "absent"

_STATE_LABELS: dict[str, str] = {
    STATE_CONNECTED:  "Connected",
    STATE_CONNECTING: "Connecting…",
    STATE_ERROR:      "Error",
    STATE_ABSENT:     "Not Found",
}


def _dot_color(state: str) -> str:
    """Return a hex colour for the status dot based on device state."""
    if state == STATE_CONNECTED:
        return PALETTE.get("success", "#00d479")
    if state == STATE_CONNECTING:
        return PALETTE.get("warning", "#ffb300")
    if state == STATE_ERROR:
        return PALETTE.get("danger", "#ff4444")
    # absent / unknown
    return PALETTE.get("textDim", "#888888")


# ── Device row ───────────────────────────────────────────────────────────────

class _DeviceRow(QFrame):
    """Single device row within the health panel."""

    reconnect_clicked = pyqtSignal(str)  # uid

    # Expected poll intervals per device type prefix (ms)
    _EXPECTED_POLL_MS: dict[str, float] = {
        "tec": 500, "fpga": 1000, "bias": 1000,
        "stage": 500, "camera": 1000, "ldd": 500,
        "gpio": 2000, "prober": 2000,
    }

    def __init__(self, uid: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.uid = uid
        self._state = STATE_ABSENT
        self._port = ""
        self._error_msg = ""
        self._last_seen: Optional[float] = None
        self._avg_response_ms: float = 0.0
        self._expected_poll_ms: float = self._guess_expected_poll(uid)

        self.setFrameShape(QFrame.NoFrame)
        self._build_ui()
        self._apply_styles()

        # 1-second timer to update the "last seen" label
        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(1000)
        self._hb_timer.timeout.connect(self._update_heartbeat_display)
        self._hb_timer.start()

    @staticmethod
    def _guess_expected_poll(uid: str) -> float:
        """Guess the expected poll interval for a device UID (ms)."""
        for prefix, ms in _DeviceRow._EXPECTED_POLL_MS.items():
            if uid.startswith(prefix):
                return ms
        return 1000.0

    # ── Build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(2)

        # Top row: dot + name + port + status + reconnect btn
        top = QHBoxLayout()
        top.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._dot.setAlignment(Qt.AlignCenter)
        top.addWidget(self._dot)

        self._name_lbl = QLabel(self.uid)
        self._name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self._name_lbl)

        self._port_lbl = QLabel("")
        self._port_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._port_lbl)

        self._heartbeat_lbl = QLabel("")
        self._heartbeat_lbl.setFixedWidth(64)
        self._heartbeat_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._heartbeat_lbl)

        self._status_lbl = QLabel("")
        self._status_lbl.setFixedWidth(100)
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._status_lbl)

        self._reconnect_btn = QPushButton("Reconnect")
        self._reconnect_btn.setFixedWidth(90)
        self._reconnect_btn.setCursor(Qt.PointingHandCursor)
        self._reconnect_btn.clicked.connect(lambda: self.reconnect_clicked.emit(self.uid))
        self._reconnect_btn.setVisible(False)
        top.addWidget(self._reconnect_btn)

        root.addLayout(top)

        # Bottom row: error message (hidden unless needed)
        self._error_lbl = QLabel("")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setVisible(False)
        root.addWidget(self._error_lbl)

    # ── Update ────────────────────────────────────────────────────────

    def set_data(
        self,
        state: str,
        port: str = "",
        error_msg: str = "",
        last_seen: Optional[float] = None,
        display_name: Optional[str] = None,
    ) -> None:
        self._state = state
        self._port = port
        self._error_msg = error_msg
        self._last_seen = last_seen

        if display_name:
            self._name_lbl.setText(display_name)

        self._port_lbl.setText(port if port else "")
        self._status_lbl.setText(_STATE_LABELS.get(state, state.title()))

        # Dot colour
        colour = _dot_color(state)
        self._dot.setStyleSheet(f"color: {colour}; font-size: 14px;")

        # Status label colour
        self._status_lbl.setStyleSheet(
            f"color: {colour}; font-weight: 600; "
            f"font-size: {FONT.get('sm', 10)}pt;"
        )

        # Error message
        has_error = bool(error_msg) and state in (STATE_ERROR, STATE_ABSENT)
        self._error_lbl.setVisible(has_error)
        if has_error:
            self._error_lbl.setText(error_msg)

        # Reconnect button visibility
        self._reconnect_btn.setVisible(state in (STATE_ERROR, STATE_ABSENT))

        self._apply_styles()

    # ── Heartbeat ─────────────────────────────────────────────────────

    def on_heartbeat(self, timestamp: float, response_time_ms: float) -> None:
        """Record a successful poll from the device."""
        self._last_seen = timestamp
        # Exponential moving average (α = 0.3)
        if self._avg_response_ms <= 0:
            self._avg_response_ms = response_time_ms
        else:
            self._avg_response_ms = 0.7 * self._avg_response_ms + 0.3 * response_time_ms

    def _update_heartbeat_display(self) -> None:
        """Update the 'last seen' text (called every 1 s by timer)."""
        if self._last_seen is None or self._state != STATE_CONNECTED:
            self._heartbeat_lbl.setText("")
            return

        age_s = time.time() - self._last_seen
        if age_s < 2:
            txt = "just now"
        elif age_s < 60:
            txt = f"{int(age_s)}s ago"
        else:
            txt = f"{int(age_s / 60)}m ago"

        # Colour: green if healthy, amber if stale (>2× expected interval)
        stale_threshold_s = (self._expected_poll_ms * 2.5) / 1000.0
        muted = PALETTE.get("textDim", "#888888")
        warning = PALETTE.get("warning", "#ffb300")
        colour = warning if age_s > stale_threshold_s else muted

        self._heartbeat_lbl.setText(txt)
        self._heartbeat_lbl.setStyleSheet(
            f"color: {colour}; font-size: {FONT.get('caption', 9)}pt; border: none;"
        )

        # Also update the dot colour to amber if stale but still "connected"
        if age_s > stale_threshold_s and self._state == STATE_CONNECTED:
            self._dot.setStyleSheet(f"color: {warning}; font-size: 14px;")

    # ── Styles ────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        surface = PALETTE.get("surface", "#1e1e1e")
        border = PALETTE.get("border", "#333333")
        fg = PALETTE.get("text", "#e0e0e0")
        muted = PALETTE.get("textDim", "#888888")
        accent = PALETTE.get("accent", "#00d479")

        self.setStyleSheet(
            f"_DeviceRow {{"
            f"  background: {surface};"
            f"  border: 1px solid {border};"
            f"  border-radius: 6px;"
            f"}}"
        )

        self._name_lbl.setStyleSheet(
            f"color: {fg}; font-weight: 700; "
            f"font-size: {FONT.get('base', 11)}pt; border: none;"
        )
        self._port_lbl.setStyleSheet(
            f"color: {muted}; font-size: {FONT.get('sm', 10)}pt; border: none;"
        )
        self._heartbeat_lbl.setStyleSheet(
            f"color: {muted}; font-size: {FONT.get('caption', 9)}pt; border: none;"
        )
        self._error_lbl.setStyleSheet(
            f"color: {muted}; font-size: {FONT.get('sm', 10)}pt; "
            f"padding-left: 24px; border: none;"
        )

        self._reconnect_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {accent};"
            f"  border: 1px solid {accent};"
            f"  border-radius: 4px;"
            f"  padding: 2px 8px;"
            f"  font-size: {FONT.get('sm', 10)}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {accent};"
            f"  color: {PALETTE.get('bg', '#121212')};"
            f"}}"
        )


# ── Main panel ───────────────────────────────────────────────────────────────

class ConnectionHealthPanel(QWidget):
    """Scrollable dashboard showing real-time health of all hardware devices."""

    reconnect_requested = pyqtSignal(str)   # device uid
    rescan_requested    = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: dict[str, _DeviceRow] = {}
        self._build_ui()
        self._apply_styles()

    # ── Build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header
        self._header = QLabel("Connection Health")
        self._header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self._header)

        # OS warnings banner (hidden until populated)
        self._os_warnings_frame = QFrame()
        self._os_warnings_frame.setVisible(False)
        self._os_warnings_layout = QVBoxLayout(self._os_warnings_frame)
        self._os_warnings_layout.setContentsMargins(8, 6, 8, 6)
        self._os_warnings_layout.setSpacing(4)
        root.addWidget(self._os_warnings_frame)

        # Scroll area containing device rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        # Bottom button bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self._reconnect_all_btn = QPushButton("Reconnect All")
        self._reconnect_all_btn.setCursor(Qt.PointingHandCursor)
        self._reconnect_all_btn.clicked.connect(self._on_reconnect_all)
        btn_bar.addWidget(self._reconnect_all_btn)

        self._rescan_btn = QPushButton("Re-scan Hardware")
        self._rescan_btn.setCursor(Qt.PointingHandCursor)
        self._rescan_btn.clicked.connect(self.rescan_requested.emit)
        btn_bar.addWidget(self._rescan_btn)

        btn_bar.addStretch()
        root.addLayout(btn_bar)

    # ── Public API ────────────────────────────────────────────────────

    def update_device(
        self,
        uid: str,
        state: str,
        port: str = "",
        error_msg: str = "",
        last_seen: Optional[float] = None,
        display_name: Optional[str] = None,
    ) -> None:
        """Create or update a single device row.

        Parameters
        ----------
        uid : str
            Unique device identifier (e.g. ``"tec_0"``).
        state : str
            One of STATE_CONNECTED, STATE_CONNECTING, STATE_ERROR, STATE_ABSENT.
        port : str
            Port or address string (e.g. ``"COM3"``, ``"USB://0x1234"``).
        error_msg : str
            Human-readable error detail (shown only in error/absent states).
        last_seen : float | None
            Unix timestamp of last successful communication.
        display_name : str | None
            Friendly name override; if *None* the uid is shown.
        """
        row = self._rows.get(uid)
        if row is None:
            row = _DeviceRow(uid, parent=self._container)
            row.reconnect_clicked.connect(self.reconnect_requested.emit)
            # Insert before the trailing stretch
            idx = max(self._container_layout.count() - 1, 0)
            self._container_layout.insertWidget(idx, row)
            self._rows[uid] = row
            log.debug("Added health row for device %s", uid)

        row.set_data(
            state=state,
            port=port,
            error_msg=error_msg,
            last_seen=last_seen,
            display_name=display_name or uid,
        )

    def update_all(self, health_dict: Dict[str, Dict[str, Any]]) -> None:
        """Bulk update from a dict keyed by device uid.

        Each value dict may contain:
            state, port, error_msg (or error), last_seen, display_name (or name).
        """
        for uid, info in health_dict.items():
            self.update_device(
                uid=uid,
                state=info.get("state", STATE_ABSENT),
                port=info.get("port", ""),
                error_msg=info.get("error_msg", info.get("error", "")),
                last_seen=info.get("last_seen"),
                display_name=info.get("display_name", info.get("name")),
            )

    def on_heartbeat(self, device_key: str, timestamp: float,
                      response_time_ms: float) -> None:
        """Route a heartbeat signal to the correct device row.

        Called from ``MainWindow`` via::

            hw_service.heartbeat.connect(health_panel.on_heartbeat)
        """
        row = self._rows.get(device_key)
        if row is not None:
            row.on_heartbeat(timestamp, response_time_ms)

    def remove_device(self, uid: str) -> None:
        """Remove a device row from the panel."""
        row = self._rows.pop(uid, None)
        if row is not None:
            self._container_layout.removeWidget(row)
            row.deleteLater()
            log.debug("Removed health row for device %s", uid)

    def set_os_warnings(self, checks: list) -> None:
        """Show OS-level diagnostic warnings above the device rows.

        Parameters
        ----------
        checks : list[OSCheckResult]
            Results from ``hardware.os_checks.run_os_checks()``.
            Only failed checks (``not passed``) are displayed.
        """
        # Clear existing warnings
        while self._os_warnings_layout.count():
            item = self._os_warnings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        failed = [c for c in checks if not getattr(c, 'passed', True)]
        self._os_warnings_frame.setVisible(bool(failed))

        warning_color = PALETTE.get("warning", "#ffb300")
        muted = PALETTE.get("textDim", "#888888")
        surface = PALETTE.get("surface", "#1e1e1e")
        sm = FONT.get("sm", 10)

        if failed:
            self._os_warnings_frame.setStyleSheet(
                f"background: {surface}; "
                f"border: 1px solid {warning_color}; "
                f"border-radius: 6px;"
            )

        for c in failed:
            title = QLabel(f"⚠ {c.display_name}: {c.message}")
            title.setWordWrap(True)
            title.setStyleSheet(
                f"color: {warning_color}; font-size: {sm}pt; "
                f"font-weight: 600; border: none;"
            )
            self._os_warnings_layout.addWidget(title)

            if getattr(c, 'fix_suggestion', ''):
                fix = QLabel(c.fix_suggestion)
                fix.setWordWrap(True)
                fix.setStyleSheet(
                    f"color: {muted}; font-size: {sm}pt; "
                    f"padding-left: 20px; border: none;"
                )
                self._os_warnings_layout.addWidget(fix)

    def clear(self) -> None:
        """Remove all device rows."""
        for uid in list(self._rows):
            self.remove_device(uid)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Refresh all palette-derived styles.  Called by
        ``MainWindow._swap_visual_theme()``."""
        bg = PALETTE.get("bg", "#121212")
        fg = PALETTE.get("text", "#e0e0e0")
        surface = PALETTE.get("surface", "#1e1e1e")
        border = PALETTE.get("border", "#333333")
        accent = PALETTE.get("accent", "#00d479")
        muted = PALETTE.get("textDim", "#888888")

        self.setStyleSheet(f"background: {bg};")

        self._header.setStyleSheet(
            f"color: {fg}; font-weight: 700; "
            f"font-size: {FONT.get('readoutSm', 13)}pt; "
            f"padding: 4px 2px; background: transparent;"
        )

        btn_qss = (
            f"QPushButton {{"
            f"  background: {surface};"
            f"  color: {fg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 4px;"
            f"  padding: 6px 14px;"
            f"  font-size: {FONT.get('sm', 10)}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border-color: {accent};"
            f"  color: {accent};"
            f"}}"
        )
        self._reconnect_all_btn.setStyleSheet(btn_qss)
        self._rescan_btn.setStyleSheet(btn_qss)

        self._scroll.setStyleSheet(f"background: transparent;")
        self._container.setStyleSheet(f"background: transparent;")

        # Refresh existing rows
        for row in self._rows.values():
            row._apply_styles()

    # ── Internal ──────────────────────────────────────────────────────

    def _on_reconnect_all(self) -> None:
        """Emit reconnect_requested for every device in error or absent state."""
        for uid, row in self._rows.items():
            if row._state in (STATE_ERROR, STATE_ABSENT):
                self.reconnect_requested.emit(uid)
                log.info("Reconnect-all: requesting reconnect for %s", uid)
