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
    QMessageBox, QApplication, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView)
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal, QSize, QModelIndex
from PyQt5.QtGui     import QColor, QFont, QIcon, QBrush

from hardware.device_registry import (
    DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA, DTYPE_STAGE, DTYPE_BIAS,
    DTYPE_UNKNOWN, CONN_SERIAL, CONN_ETHERNET, CONN_USB, CONN_PCIE)
from hardware.device_manager  import DeviceManager, DeviceState, DeviceEntry
from ui.font_utils import mono_font
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
# ------------------------------------------------------------------ #
#  Left panel — device list  (QTreeWidget-based)                      #
# ------------------------------------------------------------------ #

class _DeviceListPanel(QWidget):
    """Device list panel using QTreeWidget.

    Replaces the previous _DeviceRow-per-device approach, which created
    a full QWidget hierarchy (dot + icon + name + address label) for
    every device row.  Qt's stylesheet cascade evaluation ran across
    all of those widgets on every repopulate, causing 5-10 s GUI freezes
    on Windows before the dialog was even shown.

    QTreeWidgetItem is a lightweight data object — Qt renders all rows
    through a single shared delegate without creating per-row widgets.
    Populate time is effectively instant even for 50+ devices.

    The Scan button doubles as a Cancel button while a scan is running.
    Scan results are summarised in the status bar:
      "3 devices found  ·  2 connected"
      "No devices found  ·  check connections or run in demo mode"
    """

    device_selected  = pyqtSignal(str)
    scan_completed   = pyqtSignal()     # emitted (GUI thread) when scan finishes or cancels
    no_devices_found = pyqtSignal()     # emitted when scan completes with zero results

    _C_DOT  = 0   # ● status dot  (fixed 20 px)
    _C_NAME = 1   # device name   (stretches)
    _C_ADDR = 2   # address       (fixed ~110 px)

    def __init__(self, device_manager: DeviceManager):
        super().__init__()
        self._mgr              = device_manager
        self._selected_uid:    Optional[str] = None
        self._uid_to_item:     Dict[str, QTreeWidgetItem] = {}
        self._scanning         = False
        self._cancel_requested = False
        self._cancel_event     = threading.Event()
        self.setMinimumWidth(180)

        # Build button stylesheets once (_pt() reads sys.platform at runtime)
        self._ss_scan = _pt("""
            QPushButton {
                background:#1a1a1a; color:#00d4aa;
                border:1px solid #00d4aa33; border-radius:3px;
                font-size:7.5pt; padding:0 8px;
            }
            QPushButton:hover    { background:#0d2a1a; }
            QPushButton:disabled { color:#333; border-color:#222; }
        """)
        self._ss_cancel = _pt("""
            QPushButton {
                background:#2a0a0a; color:#ff7777;
                border:1px solid #ff444433; border-radius:3px;
                font-size:7.5pt; padding:0 8px;
            }
            QPushButton:hover    { background:#3a1010; }
            QPushButton:disabled { color:#333; border-color:#222; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────── #
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:#111; border-bottom:1px solid #222;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        title = QLabel("DEVICES")
        title.setStyleSheet(
            "font-size:8.5pt; letter-spacing:2px; color:#888;")
        self._scan_btn = QPushButton("🔍  Scan")
        self._scan_btn.setFixedHeight(24)
        self._scan_btn.setStyleSheet(self._ss_scan)
        self._net_chk = QCheckBox("+ Network")
        self._net_chk.setChecked(False)
        self._net_chk.setToolTip(
            "Also scan the local subnet for Ethernet instruments.\n"
            "Slower (~3 s) — disable on corporate networks with IDS.")
        self._net_chk.setStyleSheet(
            "QCheckBox { color:#888; font-size:7.5pt; } "
            "QCheckBox::indicator { width:12px; height:12px; }")
        hl.addWidget(title, 1)
        hl.addWidget(self._net_chk)
        hl.addWidget(self._scan_btn)
        root.addWidget(hdr)

        # ── Thin progress bar (indeterminate, shown only during scan) ─ #
        self._scan_prog = QProgressBar()
        self._scan_prog.setRange(0, 0)          # indeterminate
        self._scan_prog.setFixedHeight(2)
        self._scan_prog.setTextVisible(False)
        self._scan_prog.setVisible(False)
        self._scan_prog.setStyleSheet(
            "QProgressBar { background:#111; border:none; margin:0; }"
            "QProgressBar::chunk { background:#00d4aa; }")
        root.addWidget(self._scan_prog)

        # ── Device tree ───────────────────────────────────────────── #
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(14)
        self._tree.setAnimated(False)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._tree.setUniformRowHeights(True)
        self._tree.setStyleSheet(_pt("""
            QTreeWidget {
                background: #111;
                border: none;
                outline: none;
                font-size: 8.5pt;
            }
            QTreeWidget::item {
                height: 28px;
                padding: 0 2px;
                border: none;
            }
            QTreeWidget::item:selected {
                background: #0d2a1a;
                border: none;
            }
            QTreeWidget::item:hover:!selected {
                background: #181818;
            }
            QTreeWidget::branch { background: #111; }
            QScrollBar:vertical {
                background: #111; width: 6px; border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #2a2a2a; border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """))

        # Column sizing — dot fixed, name stretches, address fixed
        hv = self._tree.header()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(self._C_DOT,  QHeaderView.Fixed)
        hv.setSectionResizeMode(self._C_NAME, QHeaderView.Stretch)
        hv.setSectionResizeMode(self._C_ADDR, QHeaderView.Fixed)
        self._tree.setColumnWidth(self._C_DOT,  20)
        self._tree.setColumnWidth(self._C_ADDR, 110)

        self._tree.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self._tree, 1)

        # ── Status bar ────────────────────────────────────────────── #
        self._status = QLabel("")
        self._status.setStyleSheet(
            "font-size:7.5pt; color:#888; padding:4px 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._scan_btn.clicked.connect(self.start_scan)
        # Populate synchronously — QTreeWidgetItems are lightweight data
        # objects with no per-row widget construction, so there is no
        # stylesheet cascade overhead and no risk of freezing the GUI thread.
        self._populate()

    # ── Tree population ───────────────────────────────────────────── #

    def _populate(self):
        """Rebuild the device tree from the current DeviceManager state.

        Uses setUpdatesEnabled(False) to batch all item insertions into a
        single repaint.  Building QTreeWidgetItems is O(n) with no per-item
        QWidget creation, so this completes in < 1 ms even for 50 devices.
        """
        self._tree.setUpdatesEnabled(False)
        try:
            self._tree.clear()
            self._uid_to_item.clear()

            entries = self._mgr.all()
            by_type: Dict[str, list] = {t: [] for t in TYPE_ORDER}
            for e in entries:
                by_type.setdefault(e.descriptor.device_type, []).append(e)

            for dtype in TYPE_ORDER:
                group = by_type.get(dtype, [])
                if not group:
                    continue

                # Category header — spans all columns, not selectable
                cat = QTreeWidgetItem(self._tree)
                cat.setText(0, TYPE_LABELS.get(dtype, dtype).upper())
                cat.setFlags(Qt.ItemIsEnabled)      # no selection
                hdr_font = QFont()
                hdr_font.setPointSizeF(8.0)
                cat.setFont(0, hdr_font)
                cat.setForeground(0, QBrush(QColor("#777")))
                row_idx = self._tree.indexOfTopLevelItem(cat)
                self._tree.setFirstColumnSpanned(
                    row_idx, QModelIndex(), True)

                for entry in sorted(group, key=lambda e: e.display_name):
                    item = QTreeWidgetItem(cat)
                    self._update_item(item, entry)
                    self._uid_to_item[entry.uid] = item

            self._tree.expandAll()

            # Restore selection after repopulate
            if (self._selected_uid
                    and self._selected_uid in self._uid_to_item):
                self._uid_to_item[self._selected_uid].setSelected(True)
        finally:
            self._tree.setUpdatesEnabled(True)

    def _update_item(self, item: QTreeWidgetItem, entry: DeviceEntry):
        """Write a DeviceEntry's state into a tree item (no widget destroyed)."""
        item.setData(self._C_DOT, Qt.UserRole, entry.uid)

        # ● dot — color reflects connection state
        item.setText(self._C_DOT, "●")
        dot_font = QFont()
        dot_font.setPointSizeF(7.0)
        item.setFont(self._C_DOT, dot_font)
        item.setForeground(self._C_DOT, QBrush(QColor(entry.status_color)))

        # Device name
        name_color = "#ccc" if entry.state != DeviceState.ABSENT else "#555"
        item.setText(self._C_NAME, entry.display_name)
        item.setForeground(self._C_NAME, QBrush(QColor(name_color)))

        # Address (truncated, monospace)
        addr = entry.address or ""
        if len(addr) > 18:
            addr = "…" + addr[-16:]
        item.setText(self._C_ADDR, addr)
        item.setForeground(self._C_ADDR, QBrush(QColor("#555")))
        item.setTextAlignment(
            self._C_ADDR, Qt.AlignRight | Qt.AlignVCenter)
        addr_font = mono_font(7)
        item.setFont(self._C_ADDR, addr_font)

        item.setToolTip(self._C_NAME,
            f"{entry.display_name}\n"
            f"State:   {entry.status_label}\n"
            f"Address: {entry.address or '—'}")

    # ── Interaction ───────────────────────────────────────────────── #

    def refresh_row(self, uid: str):
        """Update a single row in-place without rebuilding the whole tree."""
        item  = self._uid_to_item.get(uid)
        entry = self._mgr.get(uid)
        if item and entry:
            self._update_item(item, entry)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        uid = item.data(self._C_DOT, Qt.UserRole)
        if not uid:                     # category header — deselect
            self._tree.clearSelection()
            return
        self._selected_uid = uid
        self.device_selected.emit(uid)

    # ── Scan ──────────────────────────────────────────────────────── #

    def start_scan(self):
        """Start a hardware scan, or cancel the one currently in progress."""
        if self._scanning:
            # ── Cancel ────────────────────────────────────────────── #
            self._cancel_requested = True
            self._cancel_event.set()
            self._scan_btn.setEnabled(False)
            self._scan_btn.setText("Cancelling…")
            self._status.setText("Cancelling scan…")
            return

        # ── Start ──────────────────────────────────────────────────── #
        self._scanning         = True
        self._cancel_requested = False
        self._cancel_event.clear()
        self._scan_btn.setText("✕  Cancel")
        self._scan_btn.setStyleSheet(self._ss_cancel)
        self._scan_prog.setVisible(True)
        self._status.setText("Scanning for devices…")

        def _progress(msg: str):
            if self._cancel_event.is_set():
                raise InterruptedError("scan cancelled by user")
            QTimer.singleShot(0, lambda m=msg: self._status.setText(m))

        def _run():
            try:
                scanner = DeviceScanner()
                report  = scanner.scan(
                    include_network=self._net_chk.isChecked(),
                    progress_cb=_progress)
                if not self._cancel_event.is_set():
                    self._mgr.update_from_scan(report)
            except InterruptedError:
                pass   # user cancelled — silently discard partial results
            except Exception as exc:
                if not self._cancel_event.is_set():
                    QTimer.singleShot(0, lambda e=str(exc):
                        self._status.setText(f"Scan error: {e}"))
            finally:
                QTimer.singleShot(0, self._on_scan_done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_scan_done(self):
        """Called on the GUI thread when a scan finishes or is cancelled."""
        cancelled              = self._cancel_requested
        self._scanning         = False
        self._cancel_requested = False

        self._scan_prog.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("🔍  Scan")
        self._scan_btn.setStyleSheet(self._ss_scan)

        if cancelled:
            self._status.setText("Scan cancelled.")
            self.scan_completed.emit()
            return

        try:
            self._populate()
        except Exception:
            pass

        try:
            entries   = self._mgr.all()
            found     = sum(1 for e in entries
                            if e.state != DeviceState.ABSENT)
            connected = sum(1 for e in entries if e.is_connected)
            if found == 0:
                self._status.setText(
                    "No devices found  ·  check connections or run in demo mode")
                self.no_devices_found.emit()
            elif connected == 0:
                self._status.setText(
                    f"{found} device(s) found  ·  none connected")
            else:
                self._status.setText(
                    f"{found} device(s) found  ·  {connected} connected")
        except RuntimeError:
            pass   # panel was destroyed before scan finished

        self.scan_completed.emit()


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
        t.setStyleSheet("font-size:9.5pt; letter-spacing:2px; color:#888;")
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
        lbl.setStyleSheet("color:#888; font-size:8.5pt; font-style:italic;")
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
            f" border-radius:4px; font-size:8.5pt; padding:0 8px;")
        top.addWidget(name_lbl, 1)
        top.addWidget(badge)
        self._body_layout.addLayout(top)

        # ---- Description ----
        if desc.description:
            desc_lbl = QLabel(desc.description)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size:8.5pt; color:#888;")
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
            kl.setStyleSheet("font-size:8.5pt; color:#888;")
            kl.setFixedWidth(110)
            vl = QLabel(str(v))
            vl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:8.5pt; "
                f"color:{'#ff5555' if k == 'Last Error' else '#aaa'}; "
                f"word-break:break-all;")
            vl.setWordWrap(True)
            ig.addWidget(kl, r, 0)
            ig.addWidget(vl, r, 1)

        self._body_layout.addWidget(info)

        # ---- Connection parameters (editable) ----
        self._build_params(entry)

        # ---- Datasheet link ----
        # Placed before action buttons so the 📄 emoji (which renders
        # as a white document icon) is clearly grouped with the info
        # section, not floating below Connect/Disconnect.
        if desc.datasheet_url:
            ds = QLabel(
                f'<a href="{desc.datasheet_url}" style="color:#00d4aa66;">'
                f'Datasheet / Documentation</a>')
            ds.setOpenExternalLinks(True)
            ds.setStyleSheet("font-size:8.5pt;")
            self._body_layout.addWidget(ds)

        if desc.notes:
            notes = QLabel(f"ⓘ  {desc.notes}")
            notes.setWordWrap(True)
            notes.setStyleSheet("font-size:8.5pt; color:#888; font-style:italic;")
            self._body_layout.addWidget(notes)

        # ---- Action buttons ----
        self._build_actions(entry)

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
            # Port selector — populate asynchronously so comports() never
            # blocks the GUI thread (on Windows with no connected devices
            # it can stall for several seconds, freezing the window).
            pg.addWidget(self._sublabel("Port"), r, 0)
            port_combo = QComboBox()
            port_combo.addItem("Scanning…")
            port_combo.setEnabled(False)
            pg.addWidget(port_combo, r, 1)
            self._param_widgets["port"] = port_combo
            r += 1

            def _scan_ports(combo=port_combo, addr=entry.address):
                try:
                    import serial.tools.list_ports as lp
                    ports = [p.device for p in lp.comports()]
                except Exception:
                    ports = []

                def _apply():
                    # Guard: the combo (and its parent panel) may have been
                    # deleted via deleteLater() if the user clicked a different
                    # device or the dialog was closed before the scan finished.
                    try:
                        combo.clear()
                        for p in ports:
                            combo.addItem(p)
                        if addr and addr not in ports:
                            combo.insertItem(0, addr)
                        idx = combo.findText(addr or "")
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                        combo.setEnabled(True)
                    except RuntimeError:
                        pass  # widget was deleted; silently discard

                QTimer.singleShot(0, _apply)

            threading.Thread(target=_scan_ports, daemon=True).start()

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
        l.setStyleSheet("font-size:8.5pt; color:#888;")
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
        name.setStyleSheet("font-size:9.5pt; font-weight:bold; color:#bbb;")

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
            f"font-size:8.5pt; font-family:Menlo,monospace;"
            f" padding:1px 6px;")
        top.addWidget(name, 1)
        top.addWidget(ver_badge)
        lay.addLayout(top)

        # Changelog
        cl = QLabel(entry.changelog[:90] + "…"
                    if len(entry.changelog) > 90 else entry.changelog)
        cl.setStyleSheet("font-size:8.5pt; color:#888;")
        cl.setWordWrap(True)
        lay.addWidget(cl)

        # Bottom row: hot-load indicator + install button
        bot = QHBoxLayout()
        hl_lbl = QLabel(
            "⚡ Hot-loadable" if entry.hot_loadable else "↻ Requires restart")
        hl_lbl.setStyleSheet(
            f"font-size:8.5pt; "
            f"color:{'#00d4aa66' if entry.hot_loadable else '#888'};")

        if entry.already_current:
            self._btn = QPushButton("✓  Up to date")
            self._btn.setEnabled(False)
            self._btn.setStyleSheet(
                "QPushButton{background:#111; color:#333; "
                "border:1px solid #1e1e1e; border-radius:3px; "
                "font-size:8.5pt; padding:2px 10px;}")
        else:
            self._btn = QPushButton("⬇  Install")
            self._btn.setStyleSheet("""
                QPushButton {
                    background:#0d2a1a; color:#00d4aa;
                    border:1px solid #00d4aa44; border-radius:3px;
                    font-size:8.5pt; padding:2px 10px;
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
        t.setStyleSheet("font-size:9.5pt; letter-spacing:2px; color:#888;")
        self._refresh_btn = QPushButton("🌐  Check")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background:#1a1a2a; color:#6688cc;
                border:1px solid #33448866; border-radius:3px;
                font-size:8.5pt; padding:0 8px;
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
            "font-size:8.5pt; color:#888; padding:6px 12px; "
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
                "font-size:9.5pt; letter-spacing:1.5px; color:#00d4aa66; "
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
            "font-size:8.5pt; color:#ff8800; padding:6px 12px; "
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

    Signals
    -------
    hw_status_changed(bool)
        Emitted on the GUI thread whenever hardware connection status changes.
        True  = at least one device is actively connected.
        False = no devices connected (could be absent, discovered, or error).
        Connect this to StatusHeader.set_hw_btn_status() so the header button
        reflects the live hardware state without polling.
    """

    hw_status_changed = pyqtSignal(bool)
    demo_requested    = pyqtSignal()    # user chose "Run in Demo Mode" from the no-devices dialog

    def __init__(self, device_manager: DeviceManager, parent=None,
                 demo_mode_getter=None):
        super().__init__(parent,
                         Qt.Window | Qt.WindowCloseButtonHint)
        self._mgr = device_manager
        self._suppress_auto_scan = False   # set True by suppress_next_scan()
        # Optional zero-argument callable that returns True while demo mode is
        # active.  When set, showEvent suppresses the automatic scan so the UI
        # never probes for hardware just because the user opened the dialog —
        # the user must deliberately click Scan if they want discovery to run.
        self._demo_mode_getter = demo_mode_getter
        self.setWindowTitle("Device Manager")
        self.setMinimumSize(920, 580)
        self.resize(1080, 660)
        self.setStyleSheet(_pt("""
            QDialog {
                background:#111;
            }
            QGroupBox {
                color:#555; font-size:9.5pt; letter-spacing:1px;
                border:1px solid #1e1e1e; border-radius:4px;
                margin-top:10px; padding-top:10px;
            }
            QGroupBox::title {
                subcontrol-origin:margin; left:8px;
                padding:0 4px;
            }
            QLabel { color:#888; font-size:8.5pt; }
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
            "QPushButton { font-size:8.5pt; padding:0 6px; }"
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

        # Propagate scan-done + per-device state changes to hw_status_changed
        self._list_panel.scan_completed.connect(self._emit_hw_status)

        # When a scan finds nothing, offer a modal dialog with Scan Again /
        # Demo Mode choices instead of leaving the user with a status-bar hint.
        self._list_panel.no_devices_found.connect(self._offer_demo_dialog)

        # Auto-scan is deferred to showEvent() so it never runs at __init__
        # time (i.e. during app startup).  The _list_panel._scanning flag
        # prevents concurrent scans if the user opens/closes/reopens quickly.

    # ---------------------------------------------------------------- #
    #  Callbacks from DeviceManager                                     #
    # ---------------------------------------------------------------- #

    def _on_status_change(self, uid: str,
                           state: DeviceState, msg: str):
        QTimer.singleShot(0, lambda: self._refresh_uid(uid))

    def _refresh_uid(self, uid: str):
        self._list_panel.refresh_row(uid)
        self._profile_panel.refresh(uid)
        self._emit_hw_status()

    def _emit_hw_status(self):
        """Emit hw_status_changed with current overall connection state."""
        try:
            any_connected = any(e.is_connected for e in self._mgr.all())
            self.hw_status_changed.emit(any_connected)
        except Exception:
            pass

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

    # ---------------------------------------------------------------- #
    #  First-open auto-scan                                           #
    # ---------------------------------------------------------------- #

    def suppress_next_scan(self):
        """Skip the auto-scan on the next showEvent.

        Call this before show() at app startup so the Device Manager's
        hardware discovery scan does not overlap with hw_service.start(),
        which initialises pyvisa / NI DLLs concurrently on its own threads.
        Two concurrent pyvisa.ResourceManager() calls inside Parallels (or on
        Windows with NI drivers installed) can block for 10–30 s and cause the
        whole UI to freeze.

        The suppression is one-shot: subsequent opens scan normally.
        """
        self._suppress_auto_scan = True

    def showEvent(self, event):
        """Trigger a quick scan every time the dialog is opened.

        Deferring to showEvent (rather than firing from __init__) ensures the
        scan never starts during app startup — at that point the NI/pyvisa
        sub-scanner can hold Windows COM objects for 10–30 s, which competes
        with the hardware-service init threads and causes "Not Responding".

        The ``_list_panel._scanning`` guard prevents a second concurrent scan
        if the user opens the dialog while a previous scan is still running.

        In demo mode the automatic scan is suppressed entirely — the user is
        already running with simulated hardware and doesn't need the app to
        probe for real devices on every DM open.  They can still trigger a
        discovery scan manually via the Scan button.
        """
        super().showEvent(event)
        if self._demo_mode_getter and self._demo_mode_getter():
            return   # demo mode — don't auto-scan; user must click Scan
        if not self._list_panel._scanning:
            QTimer.singleShot(200, self._initial_scan)

    def _initial_scan(self):
        """Kick off the on-open quick scan via the list panel's unified path.

        Routes through start_scan() so the scan button shows "✕ Cancel"
        during the initial scan and all result/error handling is shared.
        The Network checkbox defaults to unchecked, so this is a fast
        serial/USB-only scan identical to what the old _initial_scan did.

        Suppressed at startup (see suppress_next_scan()) to avoid racing
        with hw_service NI/pyvisa initialisation on Windows/Parallels.
        """
        if self._suppress_auto_scan:
            self._suppress_auto_scan = False   # one-shot
            return
        self._list_panel.start_scan()

    # ---------------------------------------------------------------- #
    #  No-devices dialog                                               #
    # ---------------------------------------------------------------- #

    def _offer_demo_dialog(self):
        """Modal dialog shown when a completed scan finds zero devices.

        When not in demo mode:
          • Scan Again    — reruns the scan immediately
          • Demo Mode     — emits demo_requested so main_app.py can activate it
          • Add Manually  — dismisses dialog; Device Manager stays open so the
                            user can add devices via the Add button

        When already in demo mode the "Demo Mode" button is replaced with
        "Continue in Demo Mode" which simply dismisses the dialog — there is
        no mode change needed.
        """
        already_demo = bool(self._demo_mode_getter and self._demo_mode_getter())

        box = QMessageBox(self)
        box.setWindowTitle("No Devices Found")
        box.setIcon(QMessageBox.Warning)
        box.setText("<b>No compatible hardware was detected.</b>")

        if already_demo:
            box.setInformativeText(
                "No new hardware was found.  You are already running in "
                "Demo Mode with simulated hardware.\n\n"
                "Power on your device, check its cable, and click "
                "<i>Scan Again</i> — or close this dialog to keep working "
                "in Demo Mode.")
        else:
            box.setInformativeText(
                "Check that all devices are powered on and their cables are "
                "connected, then scan again.\n\n"
                "Select <i>Demo Mode</i> to explore the full interface with "
                "simulated hardware — no physical devices required.\n\n"
                "Select <i>Add Manually</i> to configure devices by hand in "
                "the Device Manager.")

        scan_btn = box.addButton("Scan Again", QMessageBox.AcceptRole)

        if already_demo:
            box.addButton("Continue in Demo Mode", QMessageBox.RejectRole)
            box.addButton("Add Manually",          QMessageBox.ActionRole)
        else:
            demo_btn = box.addButton("Demo Mode",    QMessageBox.ActionRole)
            box.addButton(           "Add Manually", QMessageBox.RejectRole)

        box.setDefaultButton(scan_btn)
        box.exec_()

        clicked = box.clickedButton()
        if clicked is scan_btn:
            self._list_panel.start_scan()
        elif not already_demo and clicked is demo_btn:
            self.close()          # hide DM before switching mode
            self.demo_requested.emit()
