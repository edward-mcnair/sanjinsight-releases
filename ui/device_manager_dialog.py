"""
ui/device_manager_dialog.py

Device Manager — floating settings panel accessible from the ⚙ gear
icon in the header.

Layout
------
┌─────────────────────────────────────────────────────────────────┐
│  ⚙  Device Manager                                    [×]       │
├──────────────────┬──────────────────────┬───────────────────────┤
│  DEVICES         │  DEVICE PROFILE       │  DRIVER STORE         │
│  ─────────────── │  ────────────────     │  ────────────────     │
│  Camera          │  Basler acA1920-155um │  🌐 Check for Updates │
│  ● Basler acA... │                       │                       │
│                  │  Address:  USB bus1.. │  [driver cards]       │
│  TEC             │  Serial #: BA9280     │                       │
│  ● Meerstetter.. │  Firmware: 1.4.2      │                       │
│  ○ ATEC-302      │  Driver:   builtin    │                       │
│                  │                       │                       │
│  FPGA            │  [Connect] [Disconn.] │                       │
│  ● NI 9637       │                       │                       │
│  ...             │  Params:              │                       │
│                  │  Port  [COM3 ▼]       │                       │
│  [🔍 Scan]       │  Baud  [57600   ]     │                       │
└──────────────────┴──────────────────────┴───────────────────────┘
"""

from __future__ import annotations
import re
import sys
import threading
from typing import Optional, Dict


def _pt(css: str) -> str:
    """Scale explicit pt font-size values upward for Windows.

    Device Manager stylesheets use compact pt values (7–11 pt) designed
    for macOS.  On macOS Qt renders 1 pt ≈ 1 px (72 DPI baseline).
    On Windows 96 DPI, 1 pt = 96/72 ≈ 1.33 px — fonts are already
    slightly larger — but the dialog was designed with very small text
    that still looks too small on typical Windows/Parallels setups.

    Multiply all pt values by 4/3 to bring them into a comfortably
    readable range on Windows while keeping macOS unaffected.

    Contrast with main_app.py's STYLE scaling which goes ×3/4 (DOWN) for
    large body-text values that otherwise appear too big on Windows.
    """
    if sys.platform != 'win32':
        return css
    return re.sub(
        r'font-size:([\d.]+)pt',
        lambda m: f"font-size:{round(float(m.group(1)) * 4 / 3)}pt",
        css)

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSplitter, QGroupBox,
    QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit,
    QProgressBar, QTextEdit, QSizePolicy, QTabWidget,
    QMessageBox, QApplication, QCheckBox)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui     import QColor, QFont, QIcon

from hardware.device_registry import (
    DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA, DTYPE_STAGE, DTYPE_BIAS,
    DTYPE_UNKNOWN, CONN_SERIAL, CONN_ETHERNET, CONN_USB, CONN_PCIE)
from hardware.device_manager  import DeviceManager, DeviceState, DeviceEntry
from hardware.device_scanner  import DeviceScanner
from hardware.driver_store    import DriverStore, RemoteDriverEntry


# ------------------------------------------------------------------ #
#  Constants                                                           #
# ------------------------------------------------------------------ #

TYPE_ORDER  = [DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA,
               DTYPE_STAGE,  DTYPE_BIAS, DTYPE_UNKNOWN]
TYPE_LABELS = {
    DTYPE_CAMERA:  "Cameras",
    DTYPE_TEC:     "TEC Controllers",
    DTYPE_FPGA:    "FPGA / DAQ",
    DTYPE_STAGE:   "Stage Controllers",
    DTYPE_BIAS:    "Bias Sources",
    DTYPE_UNKNOWN: "Other",
}
CONN_ICONS = {
    CONN_SERIAL:   "⎆",
    CONN_USB:      "⬡",
    CONN_ETHERNET: "⬡",
    CONN_PCIE:     "▣",
}


# ------------------------------------------------------------------ #
#  Device row widget                                                   #
# ------------------------------------------------------------------ #

class _DeviceRow(QWidget):
    clicked = pyqtSignal(str)   # uid

    def __init__(self, entry: DeviceEntry, parent=None):
        super().__init__(parent)
        self.uid = entry.uid
        self._selected = False
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        # Named so _refresh_bg() can scope the CSS selector to this widget only,
        # preventing border-radius from bleeding into child QLabel widgets.
        self.setObjectName("devicerow")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        self._dot = QLabel("●")
        # On Windows, the ● glyph is rendered larger (96 DPI), so reserve
        # extra width to prevent clipping after _pt() font scaling.
        self._dot.setFixedWidth(18 if sys.platform == 'win32' else 12)

        self._name = QLabel(entry.display_name)
        self._name.setStyleSheet(_pt("font-size:8.5pt;"))

        self._addr = QLabel("")
        self._addr.setStyleSheet(
            _pt("font-family:Menlo,monospace; font-size:7.5pt; color:#555;"))
        self._addr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        conn_icon = CONN_ICONS.get(
            entry.descriptor.connection_type, "?")
        icon_lbl = QLabel(conn_icon)
        # color:#777 — visible against the dark background (#333 was near-invisible)
        icon_lbl.setStyleSheet(_pt("font-size:8pt; color:#777;"))
        icon_lbl.setFixedWidth(18 if sys.platform == 'win32' else 14)

        lay.addWidget(self._dot)
        lay.addWidget(icon_lbl)
        lay.addWidget(self._name, 1)
        lay.addWidget(self._addr)

        self.update_entry(entry)
        self._refresh_bg()

    def update_entry(self, entry: DeviceEntry):
        self._dot.setStyleSheet(
            _pt(f"color:{entry.status_color}; font-size:8pt;"))
        self._name.setStyleSheet(
            _pt(f"font-size:8.5pt; "
                f"color:{'#ccc' if entry.state != DeviceState.ABSENT else '#444'};"
                ))
        addr = entry.address
        if len(addr) > 22:
            addr = "…" + addr[-20:]
        self._addr.setText(addr)
        self.setToolTip(
            f"{entry.display_name}\n"
            f"State:  {entry.status_label}\n"
            f"Address: {entry.address or '—'}")

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh_bg()

    def _refresh_bg(self):
        # Use the objectName selector so border-radius stays on THIS widget
        # and does not propagate into child QLabel elements (which would
        # cause each label to render its own rounded background box).
        bg = "#0d2a1a" if self._selected else "transparent"
        self.setStyleSheet(
            f"QWidget#devicerow {{ background:{bg}; border-radius:3px; }}"
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)


# ------------------------------------------------------------------ #
#  Left panel — device list                                           #
# ------------------------------------------------------------------ #

class _DeviceListPanel(QWidget):
    device_selected = pyqtSignal(str)

    def __init__(self, device_manager: DeviceManager):
        super().__init__()
        self._mgr   = device_manager
        self._rows:  Dict[str, _DeviceRow] = {}
        self._selected_uid: Optional[str] = None
        self.setMinimumWidth(180)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:#111; border-bottom:1px solid #222;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        title = QLabel("DEVICES")
        title.setStyleSheet(
            "font-size:7.5pt; letter-spacing:2px; color:#444;")
        self._scan_btn = QPushButton("🔍  Scan")
        self._scan_btn.setFixedHeight(24)
        self._scan_btn.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#00d4aa;
                border:1px solid #00d4aa33; border-radius:3px;
                font-size:8pt; padding:0 8px;
            }
            QPushButton:hover { background:#0d2a1a; }
            QPushButton:disabled { color:#333; border-color:#222; }
        """)
        self._net_chk = QCheckBox("+ Network")
        self._net_chk.setChecked(False)
        self._net_chk.setToolTip(
            "Also scan the local subnet for Ethernet instruments.\n"
            "Slower (~3 s) — disable on corporate networks with IDS.")
        self._net_chk.setStyleSheet(
            "QCheckBox { color:#555; font-size:8pt; } "
            "QCheckBox::indicator { width:12px; height:12px; }")
        hl.addWidget(title, 1)
        hl.addWidget(self._net_chk)
        hl.addWidget(self._scan_btn)
        root.addWidget(hdr)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:#111;}")
        self._container = QWidget()
        self._layout    = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        scroll.setWidget(self._container)
        root.addWidget(scroll, 1)

        # Scan status
        self._status = QLabel("")
        self._status.setStyleSheet(
            "font-size:7.5pt; color:#444; padding:4px 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._scan_btn.clicked.connect(self.start_scan)
        self._populate()

    def _populate(self):
        # Clear existing rows
        for row in list(self._rows.values()):
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        entries = self._mgr.all()
        by_type: Dict[str, list] = {t: [] for t in TYPE_ORDER}
        for e in entries:
            t = e.descriptor.device_type
            by_type.setdefault(t, []).append(e)

        for dtype in TYPE_ORDER:
            group = by_type.get(dtype, [])
            if not group:
                continue
            # Section header
            sec = QLabel(TYPE_LABELS.get(dtype, dtype).upper())
            sec.setStyleSheet(
                "font-size:7pt; letter-spacing:1.5px; color:#333;"
                " padding:6px 10px 2px 10px;")
            idx = self._layout.count() - 1
            self._layout.insertWidget(idx, sec)

            for entry in sorted(group, key=lambda e: e.display_name):
                row = _DeviceRow(entry)
                row.clicked.connect(self._on_row_clicked)
                self._layout.insertWidget(self._layout.count() - 1, row)
                self._rows[entry.uid] = row

    def refresh_row(self, uid: str):
        row   = self._rows.get(uid)
        entry = self._mgr.get(uid)
        if row and entry:
            row.update_entry(entry)

    def _on_row_clicked(self, uid: str):
        if self._selected_uid and self._selected_uid in self._rows:
            self._rows[self._selected_uid].set_selected(False)
        self._selected_uid = uid
        if uid in self._rows:
            self._rows[uid].set_selected(True)
        self.device_selected.emit(uid)

    def start_scan(self):
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("Scanning…")
        self._status.setText("Scanning all ports…")

        def _run():
            scanner = DeviceScanner()
            report  = scanner.scan(
                include_network=self._net_chk.isChecked(),
                progress_cb=lambda msg: QTimer.singleShot(
                    0, lambda m=msg: self._status.setText(m)))
            self._mgr.update_from_scan(report)
            QTimer.singleShot(0, self._on_scan_done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_scan_done(self):
        self._populate()
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("🔍  Scan")
        entries = self._mgr.all()
        found   = sum(1 for e in entries
                      if e.state != DeviceState.ABSENT)
        self._status.setText(
            f"{found} device(s) found  ·  "
            f"{sum(1 for e in entries if e.is_connected)} connected")


# ------------------------------------------------------------------ #
#  Centre panel — device profile                                      #
# ------------------------------------------------------------------ #

class _DeviceProfilePanel(QWidget):
    def __init__(self, device_manager: DeviceManager):
        super().__init__()
        self._mgr    = device_manager
        self._uid:   Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:#111; border-bottom:1px solid #222;")
        hl  = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        t = QLabel("DEVICE PROFILE")
        t.setStyleSheet("font-size:7.5pt; letter-spacing:2px; color:#444;")
        hl.addWidget(t)
        root.addWidget(hdr)

        # Content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:#111;}")
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(16, 14, 16, 14)
        self._body_layout.setSpacing(12)
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        self._show_placeholder()

    def _clear(self):
        # Recursive helper: takeAt() only removes a QLayoutItem from its parent
        # layout, but widgets inside sub-layouts remain parented to self._body
        # unless explicitly deleted.  _purge() walks the whole tree so that
        # QHBoxLayout rows added via addLayout() (e.g. name+badge, action btns)
        # are fully cleaned up between show_device() calls.
        def _purge(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    _purge(item.layout())
                # spacer items have neither widget nor layout; dropping them
                # from takeAt() is sufficient.

        _purge(self._body_layout)

    def _show_placeholder(self):
        self._clear()
        lbl = QLabel("Select a device to view its profile.")
        lbl.setStyleSheet("color:#333; font-size:9pt; font-style:italic;")
        lbl.setAlignment(Qt.AlignCenter)
        self._body_layout.addStretch()
        self._body_layout.addWidget(lbl)
        self._body_layout.addStretch()

    def show_device(self, uid: str):
        self._uid = uid
        entry = self._mgr.get(uid)
        if entry is None:
            self._show_placeholder()
            return

        # Restore persisted connection params (saved by _save_params)
        try:
            import config as _cfg
            saved = _cfg.get_pref(f"device_params.{uid}", {})
            if saved.get("address"):    entry.address    = saved["address"]
            if saved.get("baud_rate"):  entry.baud_rate  = saved["baud_rate"]
            if saved.get("ip_address"): entry.ip_address = saved["ip_address"]
            if saved.get("timeout_s"):  entry.timeout_s  = saved["timeout_s"]
        except Exception:
            pass

        self._clear()
        desc = entry.descriptor

        # ---- Name + status badge ----
        top = QHBoxLayout()
        name_lbl = QLabel(desc.display_name)
        name_lbl.setStyleSheet(
            "font-size:11pt; font-weight:bold; color:#ccc;")
        name_lbl.setWordWrap(True)
        badge = QLabel(entry.status_label)
        badge.setFixedHeight(22)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background:{entry.status_color}22; color:{entry.status_color};"
            f" border:1px solid {entry.status_color}44;"
            f" border-radius:4px; font-size:8pt; padding:0 8px;")
        top.addWidget(name_lbl, 1)
        top.addWidget(badge)
        self._body_layout.addLayout(top)

        # ---- Description ----
        if desc.description:
            desc_lbl = QLabel(desc.description)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size:8.5pt; color:#555;")
            self._body_layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1e1e1e;")
        self._body_layout.addWidget(sep)

        # ---- Info table ----
        info = QGroupBox("Connection Details")
        ig   = QGridLayout(info)
        ig.setSpacing(6)
        ig.setColumnStretch(1, 1)

        rows = [
            ("Manufacturer",    desc.manufacturer),
            ("Type",            desc.device_type.replace("_", " ").title()),
            ("Transport",       desc.connection_type.upper()),
            ("Address / Port",  entry.address or "—"),
            ("Serial Number",   entry.serial_number or "—"),
            ("Firmware",        entry.firmware_ver  or "—"),
            ("Driver",          entry.driver_ver or desc.driver_version),
        ]
        if entry.error_msg:
            rows.append(("Last Error", entry.error_msg))

        for r, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet("font-size:8pt; color:#444;")
            kl.setFixedWidth(110)
            vl = QLabel(str(v))
            vl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:8pt; "
                f"color:{'#ff5555' if k == 'Last Error' else '#aaa'}; "
                f"word-break:break-all;")
            vl.setWordWrap(True)
            ig.addWidget(kl, r, 0)
            ig.addWidget(vl, r, 1)

        self._body_layout.addWidget(info)

        # ---- Connection parameters (editable) ----
        self._build_params(entry)

        # ---- Action buttons ----
        self._build_actions(entry)

        # ---- Datasheet link ----
        if desc.datasheet_url:
            ds = QLabel(
                f'<a href="{desc.datasheet_url}" style="color:#00d4aa44;">'
                f'📄  Datasheet / Documentation</a>')
            ds.setOpenExternalLinks(True)
            ds.setStyleSheet("font-size:8pt;")
            self._body_layout.addWidget(ds)

        if desc.notes:
            notes = QLabel(f"ⓘ  {desc.notes}")
            notes.setWordWrap(True)
            notes.setStyleSheet("font-size:8pt; color:#444; font-style:italic;")
            self._body_layout.addWidget(notes)

        self._body_layout.addStretch()

    def _build_params(self, entry: DeviceEntry):
        desc = entry.descriptor
        ct   = desc.connection_type
        params_box = QGroupBox("Connection Parameters")
        pg = QGridLayout(params_box)
        pg.setSpacing(8)
        pg.setColumnStretch(1, 1)

        self._param_widgets: dict = {}

        r = 0
        if ct in (CONN_SERIAL, CONN_USB):
            # Port selector
            pg.addWidget(self._sublabel("Port"), r, 0)
            port_combo = QComboBox()
            try:
                import serial.tools.list_ports as lp
                ports = [p.device for p in lp.comports()]
            except Exception:
                ports = []
            for p in ports:
                port_combo.addItem(p)
            if entry.address and entry.address not in ports:
                port_combo.insertItem(0, entry.address)
            idx = port_combo.findText(entry.address)
            if idx >= 0:
                port_combo.setCurrentIndex(idx)
            pg.addWidget(port_combo, r, 1)
            self._param_widgets["port"] = port_combo
            r += 1

            # Baud rate
            if ct == CONN_SERIAL:
                pg.addWidget(self._sublabel("Baud rate"), r, 0)
                baud_combo = QComboBox()
                for b in [9600, 19200, 38400, 57600, 115200, 230400]:
                    baud_combo.addItem(str(b))
                baud = entry.baud_rate or desc.default_baud
                idx = baud_combo.findText(str(baud))
                if idx >= 0:
                    baud_combo.setCurrentIndex(idx)
                pg.addWidget(baud_combo, r, 1)
                self._param_widgets["baud"] = baud_combo
                r += 1

        if ct == CONN_ETHERNET:
            pg.addWidget(self._sublabel("IP Address"), r, 0)
            ip_edit = QLineEdit(entry.ip_address or desc.default_ip)
            ip_edit.setPlaceholderText("e.g. 192.168.1.100")
            pg.addWidget(ip_edit, r, 1)
            self._param_widgets["ip"] = ip_edit
            r += 1

        # Timeout
        pg.addWidget(self._sublabel("Timeout (s)"), r, 0)
        timeout_spin = QDoubleSpinBox()
        timeout_spin.setRange(0.5, 30.0)
        timeout_spin.setSingleStep(0.5)
        timeout_spin.setValue(entry.timeout_s)
        timeout_spin.setFixedWidth(80)
        pg.addWidget(timeout_spin, r, 1)
        self._param_widgets["timeout"] = timeout_spin

        # Save params button
        save_btn = QPushButton("Apply Parameters")
        save_btn.setFixedHeight(28)
        save_btn.clicked.connect(lambda: self._save_params(entry))
        pg.addWidget(save_btn, r + 1, 0, 1, 2)

        self._body_layout.addWidget(params_box)

    def _save_params(self, entry: DeviceEntry):
        pw = self._param_widgets
        if "port"    in pw: entry.address    = pw["port"].currentText()
        if "baud"    in pw: entry.baud_rate  = int(pw["baud"].currentText())
        if "ip"      in pw: entry.ip_address = pw["ip"].text().strip()
        if "timeout" in pw: entry.timeout_s  = pw["timeout"].value()

        # Persist connection parameters to user preferences so they survive
        # dialog close / app restart.
        try:
            import config as _cfg
            pref_key = f"device_params.{entry.uid}"
            _cfg.set_pref(pref_key, {
                "address":    entry.address,
                "baud_rate":  entry.baud_rate,
                "ip_address": entry.ip_address,
                "timeout_s":  entry.timeout_s,
            })
        except Exception:
            pass

        # Refresh display
        self.show_device(entry.uid)

    def _build_actions(self, entry: DeviceEntry):
        row = QHBoxLayout()
        row.setSpacing(8)

        can_connect    = entry.state in (DeviceState.DISCOVERED,
                                          DeviceState.ABSENT,
                                          DeviceState.ERROR)
        can_disconnect = entry.state == DeviceState.CONNECTED

        conn_btn = QPushButton("⚡  Connect")
        conn_btn.setObjectName("primary")
        conn_btn.setFixedHeight(32)
        conn_btn.setEnabled(can_connect)
        conn_btn.clicked.connect(lambda: self._do_connect(entry.uid))

        disc_btn = QPushButton("■  Disconnect")
        disc_btn.setFixedHeight(32)
        disc_btn.setEnabled(can_disconnect)
        disc_btn.setStyleSheet(
            "QPushButton{background:#2a0a0a; color:#ff5555; "
            "border:1px solid #ff444422; border-radius:4px; font-size:8.5pt;}"
            "QPushButton:hover{background:#3a0a0a;}"
            "QPushButton:disabled{color:#333; border-color:#1e1e1e; background:#111;}")
        disc_btn.clicked.connect(lambda: self._do_disconnect(entry.uid))

        row.addWidget(conn_btn)
        row.addWidget(disc_btn)
        row.addStretch()
        self._body_layout.addLayout(row)

        self._conn_btn = conn_btn
        self._disc_btn = disc_btn

    def _do_connect(self, uid: str):
        if self._conn_btn:
            self._conn_btn.setEnabled(False)
            self._conn_btn.setText("Connecting…")

        def _done(ok, msg):
            QTimer.singleShot(0, lambda: self.show_device(uid))

        self._mgr.connect(uid, on_complete=_done)

    def _do_disconnect(self, uid: str):
        if self._disc_btn:
            self._disc_btn.setEnabled(False)

        def _done(ok, msg):
            QTimer.singleShot(0, lambda: self.show_device(uid))

        self._mgr.disconnect(uid, on_complete=_done)

    def refresh(self, uid: str):
        if uid == self._uid:
            self.show_device(uid)

    def _sublabel(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet("font-size:8pt; color:#444;")
        return l


# ------------------------------------------------------------------ #
#  Right panel — driver store                                         #
# ------------------------------------------------------------------ #

class _DriverCard(QFrame):
    install_requested = pyqtSignal(object)   # RemoteDriverEntry

    def __init__(self, entry: RemoteDriverEntry, parent=None):
        super().__init__(parent)
        self._entry = entry
        self.setFixedHeight(110)
        self.setStyleSheet(
            "QFrame{background:#141414; border:1px solid #222;"
            " border-radius:5px;}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        # Top row: name + version badge
        top = QHBoxLayout()
        name = QLabel(entry.display_name)
        name.setStyleSheet("font-size:9pt; font-weight:bold; color:#bbb;")

        ver_color = "#00d4aa" if not entry.already_current else "#444"
        ver_bg    = "#0d2a1a"  if not entry.already_current else "#1a1a1a"
        badge_text = (f"v{entry.version}"
                      if entry.already_current
                      else f"v{entry.installed_version} → v{entry.version}"
                      if entry.installed_version
                      else f"New  v{entry.version}")
        ver_badge = QLabel(badge_text)
        ver_badge.setStyleSheet(
            f"background:{ver_bg}; color:{ver_color}; "
            f"border:1px solid {ver_color}44; border-radius:3px; "
            f"font-size:7.5pt; font-family:Menlo,monospace;"
            f" padding:1px 6px;")
        top.addWidget(name, 1)
        top.addWidget(ver_badge)
        lay.addLayout(top)

        # Changelog
        cl = QLabel(entry.changelog[:90] + "…"
                    if len(entry.changelog) > 90 else entry.changelog)
        cl.setStyleSheet("font-size:8pt; color:#444;")
        cl.setWordWrap(True)
        lay.addWidget(cl)

        # Bottom row: hot-load indicator + install button
        bot = QHBoxLayout()
        hl_lbl = QLabel(
            "⚡ Hot-loadable" if entry.hot_loadable else "↻ Requires restart")
        hl_lbl.setStyleSheet(
            f"font-size:7.5pt; "
            f"color:{'#00d4aa66' if entry.hot_loadable else '#44444a'};")

        if entry.already_current:
            self._btn = QPushButton("✓  Up to date")
            self._btn.setEnabled(False)
            self._btn.setStyleSheet(
                "QPushButton{background:#111; color:#333; "
                "border:1px solid #1e1e1e; border-radius:3px; "
                "font-size:8pt; padding:2px 10px;}")
        else:
            self._btn = QPushButton("⬇  Install")
            self._btn.setStyleSheet("""
                QPushButton {
                    background:#0d2a1a; color:#00d4aa;
                    border:1px solid #00d4aa44; border-radius:3px;
                    font-size:8pt; padding:2px 10px;
                }
                QPushButton:hover { background:#0d3a22; }
                QPushButton:disabled { color:#333; border-color:#1e1e1e;
                                       background:#111; }
            """)
            self._btn.clicked.connect(
                lambda: self.install_requested.emit(self._entry))

        bot.addWidget(hl_lbl, 1)
        bot.addWidget(self._btn)
        lay.addLayout(bot)

    def set_installing(self):
        self._btn.setEnabled(False)
        self._btn.setText("Installing…")

    def set_done(self, hot_loaded: bool):
        self._btn.setText("✓  Installed" +
                          (" (hot-loaded)" if hot_loaded else " (restart)"))


class _DriverStorePanel(QWidget):
    def __init__(self, device_manager: DeviceManager):
        super().__init__()
        self._mgr    = device_manager
        self._store  = DriverStore(device_manager)
        self._cards: Dict[str, _DriverCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:#111; border-bottom:1px solid #222;")
        hl  = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        t = QLabel("DRIVER STORE")
        t.setStyleSheet("font-size:7.5pt; letter-spacing:2px; color:#444;")
        self._refresh_btn = QPushButton("🌐  Check")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background:#1a1a2a; color:#6688cc;
                border:1px solid #33448866; border-radius:3px;
                font-size:8pt; padding:0 8px;
            }
            QPushButton:hover { background:#1e1e3a; }
            QPushButton:disabled { color:#333; border-color:#222; }
        """)
        hl.addWidget(t, 1)
        hl.addWidget(self._refresh_btn)
        root.addWidget(hdr)

        # Progress / status bar
        self._status = QLabel("Click 'Check' to fetch available driver updates.")
        self._status.setStyleSheet(
            "font-size:8pt; color:#444; padding:6px 12px; "
            "background:#0d0d0d; border-bottom:1px solid #1a1a1a;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(3)
        self._prog.setTextVisible(False)
        self._prog.setVisible(False)
        root.addWidget(self._prog)

        # Card scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:#111;}")
        self._card_container = QWidget()
        self._card_layout    = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(8, 8, 8, 8)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        root.addWidget(scroll, 1)

        self._refresh_btn.clicked.connect(self._fetch_index)

    def _fetch_index(self):
        self._refresh_btn.setEnabled(False)
        self._prog.setVisible(True)

        def _run():
            try:
                entries = self._store.fetch_index(
                    progress_cb=lambda m: QTimer.singleShot(
                        0, lambda msg=m: self._status.setText(msg)))
                QTimer.singleShot(0, lambda: self._populate(entries))
            except Exception as e:
                QTimer.singleShot(
                    0, lambda err=str(e): self._on_fetch_error(err))

        threading.Thread(target=_run, daemon=True).start()

    def _populate(self, entries):
        # Clear old cards
        for card in list(self._cards.values()):
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        updates = [e for e in entries if not e.already_current]
        current = [e for e in entries if e.already_current]

        if updates:
            sec = QLabel(f"UPDATES AVAILABLE  ({len(updates)})")
            sec.setStyleSheet(
                "font-size:7pt; letter-spacing:1.5px; color:#00d4aa66; "
                "padding:4px 2px;")
            self._card_layout.insertWidget(
                self._card_layout.count() - 1, sec)

        for e in updates + current:
            card = _DriverCard(e)
            card.install_requested.connect(self._install_driver)
            self._card_layout.insertWidget(
                self._card_layout.count() - 1, card)
            self._cards[e.uid] = card

        self._prog.setVisible(False)
        self._refresh_btn.setEnabled(True)

    def _on_fetch_error(self, err: str):
        self._prog.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._status.setText(f"⚠  {err}")
        self._status.setStyleSheet(
            "font-size:8pt; color:#ff8800; padding:6px 12px; "
            "background:#0d0d0d; border-bottom:1px solid #1a1a1a;")

    def _install_driver(self, entry: RemoteDriverEntry):
        card = self._cards.get(entry.uid)
        if card:
            card.set_installing()

        self._prog.setVisible(True)

        def _run():
            result = self._store.install(
                entry,
                progress_cb=lambda m: QTimer.singleShot(
                    0, lambda msg=m: self._status.setText(msg)))
            QTimer.singleShot(0, lambda: self._on_install_done(result, card))

        threading.Thread(target=_run, daemon=True).start()

    def _on_install_done(self, result, card):
        self._prog.setVisible(False)
        if result.success:
            if card:
                card.set_done(result.hot_loaded)
            if result.needs_restart:
                self._status.setText(
                    "✓  Driver installed. Restart the application to apply.")
            else:
                self._status.setText(
                    f"✓  Driver hot-loaded — active immediately.")
        else:
            self._status.setText(f"✗  Install failed: {result.error}")


# ------------------------------------------------------------------ #
#  Main dialog                                                         #
# ------------------------------------------------------------------ #

class DeviceManagerDialog(QDialog):
    """
    The Device Manager settings panel.
    Instantiated once and shown/hidden via show_device_manager().
    """

    def __init__(self, device_manager: DeviceManager, parent=None):
        super().__init__(parent,
                         Qt.Window | Qt.WindowCloseButtonHint)
        self._mgr = device_manager
        self.setWindowTitle("Device Manager")
        self.setMinimumSize(920, 580)
        self.resize(1080, 660)
        self.setStyleSheet(_pt("""
            QDialog {
                background:#111;
            }
            QGroupBox {
                color:#555; font-size:8pt; letter-spacing:1px;
                border:1px solid #1e1e1e; border-radius:4px;
                margin-top:10px; padding-top:10px;
            }
            QGroupBox::title {
                subcontrol-origin:margin; left:8px;
                padding:0 4px;
            }
            QLabel { color:#888; font-size:8pt; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                background:#1a1a1a; color:#aaa;
                border:1px solid #2a2a2a; border-radius:3px;
                padding:2px 6px; font-size:8.5pt;
            }
            QPushButton {
                background:#1e1e1e; color:#888;
                border:1px solid #2a2a2a; border-radius:4px;
                padding:2px 8px; font-size:8.5pt;
            }
            QPushButton:hover { background:#242424; color:#aaa; }
            QPushButton[objectName="primary"] {
                background:#0d2a1a; color:#00d4aa;
                border:1px solid #00d4aa44;
            }
            QPushButton[objectName="primary"]:hover {
                background:#0d3a22;
            }
            QScrollBar:vertical {
                background:#111; width:6px; border-radius:3px;
            }
            QScrollBar::handle:vertical {
                background:#2a2a2a; border-radius:3px;
            }
        """))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Title bar ----
        title_bar = QWidget()
        title_bar.setFixedHeight(44)
        title_bar.setStyleSheet(
            "background:#0d0d0d; border-bottom:1px solid #1e1e1e;")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(16, 0, 16, 0)
        title_lbl = QLabel("⚙  Device Manager")
        title_lbl.setStyleSheet(
            "font-size:11pt; font-weight:bold; color:#888;")
        tl.addWidget(title_lbl, 1)

        # Log toggle button — explicit stylesheet so the dialog-level rule
        # (which sets font-size:8.5pt and padding) doesn't cause overflow
        # on the fixed 72×28 footprint of this button.
        self._log_btn = QPushButton("📋  Log")
        self._log_btn.setFixedSize(72, 28)
        self._log_btn.setCheckable(True)
        self._log_btn.setStyleSheet(
            "QPushButton { font-size:8pt; padding:0 6px; }"
            "QPushButton:checked { background:#0d2a1a; color:#00d4aa; "
            "border-color:#00d4aa44; }")
        self._log_btn.clicked.connect(self._toggle_log)
        tl.addWidget(self._log_btn)

        root.addWidget(title_bar)

        # ---- Three-panel splitter ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background:#1e1e1e; width:1px; }")
        splitter.setChildrenCollapsible(False)

        self._list_panel    = _DeviceListPanel(device_manager)
        self._profile_panel = _DeviceProfilePanel(device_manager)
        self._store_panel   = _DriverStorePanel(device_manager)

        splitter.addWidget(self._list_panel)
        splitter.addWidget(self._profile_panel)
        splitter.addWidget(self._store_panel)
        splitter.setSizes([230, 430, 300])
        root.addWidget(splitter, 1)

        # ---- Log panel (collapsible) ----
        self._log_widget = QWidget()
        self._log_widget.setFixedHeight(120)
        self._log_widget.setVisible(False)
        ll = QVBoxLayout(self._log_widget)
        ll.setContentsMargins(0, 0, 0, 0)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1e1e1e;")
        ll.addWidget(sep)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setStyleSheet(
            "background:#0a0a0a; color:#555; font-family:Menlo,monospace; "
            "font-size:8pt; border:none;")
        ll.addWidget(self._log_edit)
        root.addWidget(self._log_widget)

        # Wire up manager callbacks
        device_manager.set_status_callback(self._on_status_change)
        device_manager.set_log_callback(self._on_log)

        # Connect list → profile panel
        self._list_panel.device_selected.connect(
            self._profile_panel.show_device)

        # Initial scan on open (quick — no network)
        QTimer.singleShot(200, self._initial_scan)

    # ---------------------------------------------------------------- #
    #  Callbacks from DeviceManager                                     #
    # ---------------------------------------------------------------- #

    def _on_status_change(self, uid: str,
                           state: DeviceState, msg: str):
        QTimer.singleShot(0, lambda: self._refresh_uid(uid))

    def _refresh_uid(self, uid: str):
        self._list_panel.refresh_row(uid)
        self._profile_panel.refresh(uid)

    def _on_log(self, msg: str):
        QTimer.singleShot(0, lambda: self._append_log(msg))

    def _append_log(self, msg: str):
        self._log_edit.append(msg)
        self._log_edit.verticalScrollBar().setValue(
            self._log_edit.verticalScrollBar().maximum())

    # ---------------------------------------------------------------- #
    #  Log panel toggle                                                 #
    # ---------------------------------------------------------------- #

    def _toggle_log(self, checked: bool):
        self._log_widget.setVisible(checked)

    # ---------------------------------------------------------------- #
    #  Initial quick scan (serial + USB only, no network)              #
    # ---------------------------------------------------------------- #

    def _initial_scan(self):
        def _run():
            from hardware.device_scanner import DeviceScanner
            scanner = DeviceScanner()
            report  = scanner.scan(include_network=False)
            self._mgr.update_from_scan(report)
            QTimer.singleShot(0, self._list_panel._on_scan_done)
        threading.Thread(target=_run, daemon=True).start()
