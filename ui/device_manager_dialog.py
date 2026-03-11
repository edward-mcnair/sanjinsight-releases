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
    DEVICE_REGISTRY,
    DTYPE_CAMERA, DTYPE_TEC, DTYPE_FPGA, DTYPE_STAGE, DTYPE_BIAS,
    DTYPE_UNKNOWN, CONN_SERIAL, CONN_ETHERNET, CONN_USB, CONN_PCIE)
from hardware.device_manager  import DeviceManager, DeviceState, DeviceEntry
from ui.font_utils import mono_font
from ui.theme import FONT, PALETTE, scaled_qss
from hardware.device_scanner  import DeviceScanner
from hardware.driver_store    import DriverStore, RemoteDriverEntry


# ------------------------------------------------------------------ #
#  Live log handler — routes Python logging to the log panel          #
# ------------------------------------------------------------------ #

import logging as _logging

class _QTextEditHandler(_logging.Handler):
    """
    Appends Python log records to a QTextEdit in real-time.

    Colours:
      DEBUG    → #555 (dim grey)
      INFO     → #888 (grey)
      WARNING  → #cc8800 (amber)
      ERROR    → #ff5555 (red)
      CRITICAL → #ff0000 (bright red)
    """
    _COLOURS = {
        _logging.DEBUG:    "#555",
        _logging.INFO:     "#888",
        _logging.WARNING:  "#cc8800",
        _logging.ERROR:    "#ff5555",
        _logging.CRITICAL: "#ff0000",
    }
    _FMT = _logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                               datefmt="%H:%M:%S")

    def __init__(self, text_edit):
        super().__init__()
        self._edit = text_edit
        self.setFormatter(self._FMT)

    def emit(self, record):
        try:
            msg   = self.format(record)
            color = self._COLOURS.get(record.levelno, "#888")
            # Escape HTML characters so angle-brackets in log messages
            # don't break the rich-text rendering.
            msg = (msg.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
            html = f'<span style="color:{color};">{msg}</span>'
            # QTextEdit.append() must be called on the GUI thread.
            # Use QTimer.singleShot so background log threads are safe.
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda h=html: self._safe_append(h))
        except Exception:
            pass   # never let a log handler crash the app

    def _safe_append(self, html: str):
        try:
            self._edit.append(html)
            sb = self._edit.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass


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

        self._build_scan_stylesheets()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────── #
        self._list_hdr = QWidget()
        self._list_hdr.setFixedHeight(36)
        self._list_hdr.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        hl = QHBoxLayout(self._list_hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        self._list_title = QLabel("DEVICES")
        self._list_title.setStyleSheet(
            f"font-size:8.5pt; letter-spacing:2px; color:{PALETTE['textDim']};")
        self._scan_btn = QPushButton("🔍  Scan")
        self._scan_btn.setFixedHeight(24)
        self._scan_btn.setStyleSheet(self._ss_scan)
        self._net_chk = QCheckBox("+ Network")
        self._net_chk.setChecked(False)
        self._net_chk.setToolTip(
            "Also scan the local subnet for Ethernet instruments.\n"
            "Slower (~3 s) — disable on corporate networks with IDS.")
        self._net_chk.setStyleSheet(
            f"QCheckBox {{ color:{PALETTE['textDim']}; font-size:7.5pt; }} "
            "QCheckBox::indicator { width:12px; height:12px; }")
        hl.addWidget(self._list_title, 1)
        hl.addWidget(self._net_chk)
        hl.addWidget(self._scan_btn)
        root.addWidget(self._list_hdr)

        # ── Thin progress bar (indeterminate, shown only during scan) ─ #
        self._scan_prog = QProgressBar()
        self._scan_prog.setRange(0, 0)          # indeterminate
        self._scan_prog.setFixedHeight(2)
        self._scan_prog.setTextVisible(False)
        self._scan_prog.setVisible(False)
        self._scan_prog.setStyleSheet(
            f"QProgressBar {{ background:{PALETTE['surface3']}; border:none; margin:0; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['accent']}; }}")
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
        self._tree.setStyleSheet(_pt(
            f"QTreeWidget {{"
            f"    background: {PALETTE['surface3']};"
            f"    border: none; outline: none; font-size: 8.5pt;"
            f"}}"
            f"QTreeWidget::item {{"
            f"    height: 28px; padding: 0 2px; border: none;"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"    background: {PALETTE['activeItem']}; border: none;"
            f"}}"
            f"QTreeWidget::item:hover:!selected {{"
            f"    background: {PALETTE['surface']};"
            f"}}"
            f"QTreeWidget::branch {{ background: {PALETTE['surface3']}; }}"
            f"QScrollBar:vertical {{"
            f"    background: {PALETTE['surface3']}; width: 6px; border-radius: 3px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background: {PALETTE['border']}; border-radius: 3px; min-height: 20px;"
            f"}}"
            f"QScrollBar::add-line:vertical,"
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        ))

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
            f"font-size:7.5pt; color:{PALETTE['textDim']}; padding:4px 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._scan_btn.clicked.connect(self.start_scan)
        # Populate synchronously — QTreeWidgetItems are lightweight data
        # objects with no per-row widget construction, so there is no
        # stylesheet cascade overhead and no risk of freezing the GUI thread.
        self._populate()
        self._apply_styles()

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

    # ── Theme helpers ─────────────────────────────────────────────── #

    def _build_scan_stylesheets(self):
        self._ss_scan = _pt(
            f"QPushButton {{"
            f"    background:{PALETTE['surface']}; color:{PALETTE['accent']};"
            f"    border:1px solid {PALETTE['accent']}33; border-radius:3px;"
            f"    font-size:7.5pt; padding:0 8px;"
            f"}}"
            f"QPushButton:hover    {{ background:{PALETTE['activeItem']}; }}"
            f"QPushButton:disabled {{ color:{PALETTE['border']}; border-color:{PALETTE['border']}; }}"
        )
        self._ss_cancel = _pt(
            f"QPushButton {{"
            f"    background:#2a0a0a; color:#ff7777;"
            f"    border:1px solid #ff444433; border-radius:3px;"
            f"    font-size:7.5pt; padding:0 8px;"
            f"}}"
            f"QPushButton:hover    {{ background:#3a1010; }}"
            f"QPushButton:disabled {{ color:{PALETTE['border']}; border-color:{PALETTE['border']}; }}"
        )

    def _apply_styles(self) -> None:
        self._build_scan_stylesheets()
        self._list_hdr.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        self._list_title.setStyleSheet(
            f"font-size:8.5pt; letter-spacing:2px; color:{PALETTE['textDim']};")
        self._net_chk.setStyleSheet(
            f"QCheckBox {{ color:{PALETTE['textDim']}; font-size:7.5pt; }} "
            "QCheckBox::indicator { width:12px; height:12px; }")
        self._scan_prog.setStyleSheet(
            f"QProgressBar {{ background:{PALETTE['surface3']}; border:none; margin:0; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['accent']}; }}")
        self._tree.setStyleSheet(_pt(
            f"QTreeWidget {{"
            f"    background: {PALETTE['surface3']};"
            f"    border: none; outline: none; font-size: 8.5pt;"
            f"}}"
            f"QTreeWidget::item {{"
            f"    height: 28px; padding: 0 2px; border: none;"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"    background: {PALETTE['activeItem']}; border: none;"
            f"}}"
            f"QTreeWidget::item:hover:!selected {{"
            f"    background: {PALETTE['surface']};"
            f"}}"
            f"QTreeWidget::branch {{ background: {PALETTE['surface3']}; }}"
            f"QScrollBar:vertical {{"
            f"    background: {PALETTE['surface3']}; width: 6px; border-radius: 3px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background: {PALETTE['border']}; border-radius: 3px; min-height: 20px;"
            f"}}"
            f"QScrollBar::add-line:vertical,"
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        ))
        self._status.setStyleSheet(
            f"font-size:7.5pt; color:{PALETTE['textDim']}; padding:4px 12px;")
        if not self._scanning:
            self._scan_btn.setStyleSheet(self._ss_scan)

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
                    self._last_scan_report = report   # saved for _offer_demo_dialog
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
        hdr.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        hl  = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        t = QLabel("DEVICE PROFILE")
        t.setStyleSheet(
            f"font-size:9.5pt; letter-spacing:2px; color:{PALETTE['textDim']};")
        hl.addWidget(t)
        root.addWidget(hdr)

        # Content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none; background:{PALETTE['surface3']};}}")
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
        lbl.setStyleSheet(
            f"color:{PALETTE['textDim']}; font-size:8.5pt; font-style:italic;")
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
            f"font-size:{FONT['sublabel']}pt; font-weight:bold; color:{PALETTE['text']};")
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
            desc_lbl.setStyleSheet(
                f"font-size:8.5pt; color:{PALETTE['textDim']};")
            self._body_layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{PALETTE['border']};")
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
            kl.setStyleSheet(
                f"font-size:8.5pt; color:{PALETTE['textDim']};")
            kl.setFixedWidth(110)
            vl = QLabel(str(v))
            val_color = PALETTE["danger"] if k == "Last Error" else PALETTE["text"]
            vl.setStyleSheet(
                f"font-family:Menlo,monospace; font-size:8.5pt; "
                f"color:{val_color}; word-break:break-all;")
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
                f'<a href="{desc.datasheet_url}" '
                f'style="color:{PALETTE["accent"]}66;">'
                f'Datasheet / Documentation</a>')
            ds.setOpenExternalLinks(True)
            ds.setStyleSheet("font-size:8.5pt;")
            self._body_layout.addWidget(ds)

        if desc.notes:
            notes = QLabel(f"ⓘ  {desc.notes}")
            notes.setWordWrap(True)
            notes.setStyleSheet(
                f"font-size:8.5pt; color:{PALETTE['textDim']}; font-style:italic;")
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

        # Only show the COM port selector for genuinely serial/USB-serial
        # devices (TECs, stages, bias sources, probers, etc.).
        # Cameras connect via USB3 Vision / pypylon (no COM port).
        # FPGA/NI devices connect via PCIe or NI-DAQmx (no COM port either,
        # even when connection_type is CONN_USB — NI USB-6001 uses Dev1/Dev2
        # resource names assigned by NI MAX, not a COM port string).
        _needs_port = (ct in (CONN_SERIAL, CONN_USB)
                       and desc.device_type not in (DTYPE_CAMERA, DTYPE_FPGA))

        r = 0
        if _needs_port:
            # ── Port row: editable combo + ⟳/✕ refresh-or-cancel button ──────
            pg.addWidget(self._sublabel("Port"), r, 0)
            port_row_w = QWidget()
            port_row_lay = QHBoxLayout(port_row_w)
            port_row_lay.setContentsMargins(0, 0, 0, 0)
            port_row_lay.setSpacing(4)

            port_combo = QComboBox()
            port_combo.setEditable(True)         # user can type any port directly
            port_combo.setInsertPolicy(QComboBox.InsertAtTop)
            port_combo.setMinimumWidth(140)
            port_row_lay.addWidget(port_combo, 1)

            refresh_btn = QPushButton("⟳")
            refresh_btn.setFixedSize(26, 26)
            refresh_btn.setToolTip("Refresh port list")
            refresh_btn.setStyleSheet(
                f"QPushButton{{background:{PALETTE['border']}; color:{PALETTE['textDim']};"
                f" border:1px solid {PALETTE['border']}; border-radius:4px; font-size:{FONT['sublabel']}pt;}}"
                f"QPushButton:hover{{color:{PALETTE['text']}; border-color:{PALETTE['textDim']};}}"
                f"QPushButton:disabled{{color:{PALETTE['textSub']};}}")
            port_row_lay.addWidget(refresh_btn)

            pg.addWidget(port_row_w, r, 1)
            self._param_widgets["port"] = port_combo
            r += 1

            # Shared cancel event; set to abort an in-progress description scan
            _scan_cancel = threading.Event()

            def _port_sort_key(dev: str):
                m = re.match(r"([A-Za-z]+)(\d+)", dev)
                return (m.group(1), int(m.group(2))) if m else (dev, 0)

            def _populate_port_combo(combo, pmap, saved_addr, placeholder=""):
                """Rebuild combo items from pmap dict; always runs on main thread."""
                try:
                    current = (combo.currentData()
                               or combo.currentText().split("  —  ")[0].strip())
                    combo.clear()
                    items = sorted(pmap.items(),
                                   key=lambda kv: _port_sort_key(kv[0]))
                    for device, label in items:
                        combo.addItem(label, device)
                    if saved_addr:
                        existing = [combo.itemData(j) or combo.itemText(j)
                                    for j in range(combo.count())]
                        if saved_addr not in existing:
                            combo.insertItem(0, saved_addr, saved_addr)
                    for sel in (current, saved_addr):
                        if not sel:
                            continue
                        for j in range(combo.count()):
                            stored = (combo.itemData(j)
                                      or combo.itemText(j).split("  —  ")[0].strip())
                            if stored == sel:
                                combo.setCurrentIndex(j)
                                break
                        else:
                            continue
                        break
                    if not pmap and not saved_addr:
                        combo.addItem("No COM ports found")
                    if placeholder and combo.lineEdit():
                        combo.lineEdit().setPlaceholderText(placeholder)
                    combo.setEnabled(True)
                except RuntimeError:
                    pass

            def _set_refresh_btn(scanning: bool):
                try:
                    if scanning:
                        refresh_btn.setText("✕")
                        refresh_btn.setToolTip("Stop scanning")
                    else:
                        refresh_btn.setText("⟳")
                        refresh_btn.setToolTip("Refresh port list")
                except RuntimeError:
                    pass

            def _registry_scan() -> dict:
                """Return {port: label} from the Windows registry (synchronous, no pyserial).

                Three sources, all pure winreg — never touches NI/DAQmx drivers:
                  1. HARDWARE\\DEVICEMAP\\SERIALCOMM — every COM port the OS tracks.
                  2. SYSTEM\\CurrentControlSet\\Enum\\USB — USB devices with VID/PID.
                     Each has a FriendlyName or Device Parameters\\PortName giving the
                     COM assignment.  VID/PID is cross-referenced with DEVICE_REGISTRY
                     to produce instrument-level labels (e.g. "COM7  —  Meerstetter TEC-1089").

                On non-Windows returns an empty dict; pyserial handles it.
                """
                pmap: dict[str, str] = {}
                if not sys.platform.startswith("win"):
                    return pmap
                try:
                    import winreg

                    # ── 1. Bare COM port names ────────────────────────────────────
                    try:
                        _rk = winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DEVICEMAP\SERIALCOMM")
                        _ri = 0
                        while True:
                            try:
                                _, _v, _ = winreg.EnumValue(_rk, _ri)
                                pmap[str(_v)] = str(_v)
                                _ri += 1
                            except OSError:
                                break
                    except Exception:
                        pass

                    # ── 2. VID/PID → [display_name] lookup from DEVICE_REGISTRY ──
                    _vid_pid_names: dict[tuple, list] = {}
                    for _d in DEVICE_REGISTRY.values():
                        if (_d.device_type == DTYPE_CAMERA
                                or _d.connection_type not in (CONN_SERIAL, CONN_USB)):
                            continue
                        if _d.usb_vid and _d.usb_pid:
                            _vp = (_d.usb_vid, _d.usb_pid)
                            _vid_pid_names.setdefault(_vp, []).append(_d.display_name)

                    # ── 3. Walk SYSTEM\CurrentControlSet\Enum\USB ─────────────────
                    def _subkeys(parent):
                        _si = 0
                        while True:
                            try:
                                yield winreg.EnumKey(parent, _si)
                                _si += 1
                            except OSError:
                                break

                    _usb_root = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SYSTEM\CurrentControlSet\Enum\USB")
                    for _vp_str in _subkeys(_usb_root):
                        _mm = re.match(
                            r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})",
                            _vp_str, re.IGNORECASE)
                        if not _mm:
                            continue
                        _vid = int(_mm.group(1), 16)
                        _pid = int(_mm.group(2), 16)
                        _names = _vid_pid_names.get((_vid, _pid))
                        if not _names:
                            continue

                        _instr = "  or  ".join(dict.fromkeys(_names))
                        _vp_key = winreg.OpenKey(_usb_root, _vp_str)
                        for _inst in _subkeys(_vp_key):
                            try:
                                _ik = winreg.OpenKey(_vp_key, _inst)
                                _port_str = None

                                # Method A: Device Parameters\PortName
                                try:
                                    _dp = winreg.OpenKey(_ik, "Device Parameters")
                                    _pn, _ = winreg.QueryValueEx(_dp, "PortName")
                                    if str(_pn).startswith("COM"):
                                        _port_str = str(_pn)
                                except (FileNotFoundError, OSError):
                                    pass

                                # Method B: FriendlyName "(COMx)"
                                if not _port_str:
                                    try:
                                        _fn, _ = winreg.QueryValueEx(
                                            _ik, "FriendlyName")
                                        _mm2 = re.search(
                                            r"\(COM(\d+)\)", str(_fn))
                                        if _mm2:
                                            _port_str = f"COM{_mm2.group(1)}"
                                    except (FileNotFoundError, OSError):
                                        pass

                                if _port_str:
                                    pmap[_port_str] = f"{_port_str}  —  {_instr}"
                            except OSError:
                                pass
                except Exception:
                    pass
                return pmap

            # ── Stage 1: registry scan — instant, runs on main thread ─────────
            port_map_initial = _registry_scan()
            _populate_port_combo(port_combo, port_map_initial, entry.address,
                                 placeholder="type a port or wait for scan…")

            # ── Stage 2: pyserial descriptions — background, cancellable ──────
            # comports() can stall 30+ seconds on NI-hardware systems.
            # shutdown(wait=False) ensures the enrichment thread is never blocked
            # by a hung lp.comports() worker.
            def _enrich_port_descriptions(
                    combo=port_combo,
                    base_map=dict(port_map_initial),
                    saved=entry.address,
                    cancel=_scan_cancel):
                cancel.clear()
                QTimer.singleShot(0, lambda: _set_refresh_btn(True))
                try:
                    import concurrent.futures
                    import serial.tools.list_ports as lp
                    _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    _fut = _ex.submit(lp.comports)
                    try:
                        port_info = _fut.result(timeout=4.0)
                    except concurrent.futures.TimeoutError:
                        port_info = []
                    finally:
                        _ex.shutdown(wait=False)

                    if cancel.is_set():
                        QTimer.singleShot(0, lambda: _set_refresh_btn(False))
                        return

                    enriched = dict(base_map)
                    _on_windows = sys.platform.startswith("win")
                    for pi in port_info:
                        port_desc = (getattr(pi, 'description',  '') or '').strip()
                        hwid      = (getattr(pi, 'hwid',         '') or '').strip()
                        serial_no = (getattr(pi, 'serial_number','') or '').strip()
                        vid       = getattr(pi, 'vid', None)
                        pid       = getattr(pi, 'pid', None)

                        # If Stage 1 (_registry_scan) already produced an enriched
                        # label for this port via VID/PID matching, don't overwrite
                        # it — just append the serial number if pyserial found one.
                        _current = enriched.get(pi.device, pi.device)
                        if _current != pi.device:
                            if serial_no and f"s/n {serial_no}" not in _current:
                                enriched[pi.device] = f"{_current}  s/n {serial_no}"
                            continue

                        # On Windows, Stage 1 already did VID/PID matching via the
                        # registry (without touching NI drivers). Skip repeat here;
                        # only fall through to generic description for unknowns.
                        matched = []
                        if not _on_windows:
                            # ── 1. Exact VID+PID match against device registry ──
                            if vid and pid:
                                matched = [
                                    d for d in DEVICE_REGISTRY.values()
                                    if d.usb_vid == vid and d.usb_pid == pid
                                    and d.device_type != DTYPE_CAMERA
                                    and d.connection_type in (CONN_SERIAL, CONN_USB)
                                ]
                            # ── 2. serial_patterns text match (description/hwid) ─
                            if not matched and (port_desc or hwid):
                                search = (port_desc + " " + hwid).lower()
                                matched = [
                                    d for d in DEVICE_REGISTRY.values()
                                    if d.device_type != DTYPE_CAMERA
                                    and d.connection_type in (CONN_SERIAL, CONN_USB)
                                    and any(p.lower() in search
                                            for p in d.serial_patterns if p)
                                ]

                        # ── 3. Build the dropdown label ──────────────────────
                        if matched:
                            unique_names = list(dict.fromkeys(
                                d.display_name for d in matched))
                            instr = "  or  ".join(unique_names)
                            adapter = (f"  ({port_desc})"
                                       if port_desc and
                                       not any(n.lower() in port_desc.lower()
                                               for n in unique_names)
                                       else "")
                            sn = f"  s/n {serial_no}" if serial_no else ""
                            enriched[pi.device] = (
                                f"{pi.device}  —  {instr}{adapter}{sn}")
                        elif port_desc and port_desc.lower() not in (
                                "", "n/a", pi.device.lower()):
                            sn = f"  s/n {serial_no}" if serial_no else ""
                            enriched[pi.device] = (
                                f"{pi.device}  —  {port_desc}{sn}")
                        else:
                            enriched.setdefault(pi.device, pi.device)

                    def _finish():
                        _populate_port_combo(combo, enriched, saved)
                        _set_refresh_btn(False)
                    QTimer.singleShot(0, _finish)
                except Exception:
                    QTimer.singleShot(0, lambda: _set_refresh_btn(False))

            def _on_refresh_clicked():
                if refresh_btn.text() == "✕":
                    # Cancel in-progress scan
                    _scan_cancel.set()
                else:
                    # Re-read registry immediately then launch new description scan
                    new_map = _registry_scan()
                    _populate_port_combo(port_combo, new_map, entry.address)
                    threading.Thread(target=_enrich_port_descriptions,
                                     kwargs={"base_map": new_map},
                                     daemon=True).start()

            refresh_btn.clicked.connect(_on_refresh_clicked)
            threading.Thread(target=_enrich_port_descriptions,
                             daemon=True).start()

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

        # ── Connection-method note (non-serial, non-Ethernet devices) ──────────
        # Explain to the user why there is no address field to configure.
        if not _needs_port and ct != CONN_ETHERNET:
            if ct == CONN_PCIE:
                _conn_note = ("Connects via PCIe — no COM port required.\n"
                              "Resource name (e.g. RIO0) is assigned in NI MAX.")
            elif desc.device_type == DTYPE_FPGA:
                _conn_note = ("Connects via NI-DAQmx — no COM port required.\n"
                              "Device name (e.g. Dev1) is assigned in NI MAX.")
            elif desc.device_type == DTYPE_CAMERA:
                _conn_note = ("Connects via USB3 Vision / camera SDK.\n"
                              "Camera is enumerated automatically — no COM port needed.")
            else:
                _conn_note = None
            if _conn_note:
                _note_lbl = QLabel(_conn_note)
                _note_lbl.setWordWrap(True)
                _note_lbl.setStyleSheet(
                    _pt(f"font-size:8pt; color:{PALETTE['textDim']}; font-style:italic; "
                        f"padding:4px 6px; border-left:2px solid {PALETTE['border']};"))
                pg.addWidget(_note_lbl, r, 0, 1, 2)
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

        # ── Button row: Apply + Test Port (serial/USB only) ──────────────
        btn_w = QWidget()
        btn_lay = QHBoxLayout(btn_w)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)

        apply_btn = QPushButton("Apply Parameters")
        apply_btn.setFixedHeight(28)
        apply_btn.clicked.connect(lambda: self._save_params(entry))
        btn_lay.addWidget(apply_btn)

        if _needs_port:
            # ── "🔌 Test Port" / "✕ Cancel" toggle button ────────────────────
            # While the test is running the button becomes "✕ Cancel"; clicking
            # it sets _test_cancel so the background thread exits at its next
            # checkpoint.  The on_done callback restores the button to its
            # idle state regardless of how the test ends.
            _test_cancel = threading.Event()
            _TEST_TIP    = ("Open the selected COM port to verify it is "
                            "accessible\nand check whether the device is "
                            "sending data.")

            test_btn = QPushButton("🔌  Test Port")
            test_btn.setFixedHeight(28)
            test_btn.setToolTip(_TEST_TIP)

            # _port_status_lbl is assigned a few lines below; the nested
            # functions capture the variable by reference, so they see the
            # live QLabel once _build_params() has finished executing.
            def _restore_test_btn():
                try:
                    test_btn.setText("🔌  Test Port")
                    test_btn.setToolTip(_TEST_TIP)
                    test_btn.clicked.disconnect()
                    test_btn.clicked.connect(_start_test)
                except RuntimeError:
                    pass   # widget already deleted

            def _start_test():
                _test_cancel.clear()
                try:
                    test_btn.setText("✕  Cancel")
                    test_btn.setToolTip("Stop the port test")
                    test_btn.clicked.disconnect()
                    test_btn.clicked.connect(_test_cancel.set)
                except RuntimeError:
                    return
                self._test_port_connection(
                    entry, self._param_widgets, _port_status_lbl,
                    cancel_event=_test_cancel, on_done=_restore_test_btn)

            test_btn.clicked.connect(_start_test)
            btn_lay.addWidget(test_btn)

        btn_lay.addStretch()
        pg.addWidget(btn_w, r + 1, 0, 1, 2)

        # ── Inline port-test result label (hidden until Test Port is clicked) ─
        if _needs_port:
            _port_status_lbl = QLabel()
            _port_status_lbl.setWordWrap(True)
            _port_status_lbl.setVisible(False)
            _port_status_lbl.setStyleSheet(scaled_qss("font-size:8.5pt; padding:3px 0;"))
            pg.addWidget(_port_status_lbl, r + 2, 0, 1, 2)

        self._body_layout.addWidget(params_box)

    def _save_params(self, entry: DeviceEntry):
        pw = self._param_widgets
        if "port"    in pw:
            # itemData stores the plain device name ("COM7"); currentText()
            # has the display label ("COM7  —  FTDI USB Serial Device").
            # Prefer userData so we always save the bare COM port name.
            entry.address = (pw["port"].currentData()
                             or pw["port"].currentText().split("  —  ")[0].strip())
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

    # ---------------------------------------------------------------- #
    #  Port test                                                        #
    # ---------------------------------------------------------------- #

    def _test_port_connection(self, entry: DeviceEntry,
                               pw: dict, status_lbl: "QLabel",
                               cancel_event=None, on_done=None):
        """Open the selected COM port and report the result inline.

        Outcomes:
          ✓ green  — port opened (device may or may not have sent greeting data)
          ⊘ grey   — user cancelled before the test finished
          ✗ red    — port could not be opened (busy / missing / wrong params)
          ⚠ amber  — unexpected error with raw message for diagnostics

        cancel_event : threading.Event
            Set this from the UI thread to abort the test at its next checkpoint.
        on_done : callable
            Called on the Qt main thread when the test ends (any outcome).
            Used to restore the "✕ Cancel" button back to "🔌 Test Port".

        Both the serial.Serial() constructor and the brief read() are subject
        to a 3-second hard timeout via concurrent.futures so the user is never
        left waiting more than ~3 seconds even if the OS is slow to report
        a missing or occupied port.
        """
        port = (pw["port"].currentData()
                or pw["port"].currentText().split("  —  ")[0].strip()
                if "port" in pw else "")
        port = (port or "").strip()

        def _done(icon, text, color):
            """Report result and fire on_done on the Qt thread."""
            self._set_port_status(status_lbl, icon, text, color)
            if on_done:
                QTimer.singleShot(0, on_done)

        if not port:
            _done("⚠",
                  "No port selected — choose one from the list or type it above.",
                  "#cc8800")
            return

        baud_w = pw.get("baud")
        baud   = int(baud_w.currentText()) if baud_w else (
                     entry.baud_rate
                     or entry.descriptor.default_baud
                     or 115200)

        # Show "testing…" immediately — user sees feedback before thread starts
        self._set_port_status(
            status_lbl, "⏳",
            "Testing " + str(port) + " at " + str(baud) + " baud\u2026  "
            "<span style='color:" + PALETTE["textSub"] + "'>(click \u2715 to cancel)</span>",
            PALETTE["textDim"])

        def _cancelled():
            _done("⊘", "Test cancelled.", "#666")

        def _run():
            import concurrent.futures as _cf
            import serial

            # ── Step 1: open the port (hard 3-second timeout) ─────────────
            if cancel_event and cancel_event.is_set():
                _cancelled(); return

            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            _f  = _ex.submit(lambda: serial.Serial(
                                 port, baudrate=baud, timeout=0.3))
            try:
                ser = _f.result(timeout=3.0)
            except _cf.TimeoutError:
                _ex.shutdown(wait=False)
                if cancel_event and cancel_event.is_set():
                    _cancelled()
                else:
                    _done("✗",
                          f"<b>{port} took too long to open.</b>  "
                          "The port may be held by another process or the "
                          "OS driver is not responding.",
                          "#ff5555")
                return
            except Exception as exc:
                _ex.shutdown(wait=False)
                if cancel_event and cancel_event.is_set():
                    _cancelled(); return
                low = str(exc).lower()
                if "access is denied" in low or "permission denied" in low:
                    _done("✗",
                          f"<b>{port} is in use by another application.</b>  "
                          "Close any terminal programs, firmware updaters, or "
                          "instrument software that may have the port open, "
                          "then try again.",
                          "#ff5555")
                elif any(k in low for k in (
                        "could not open", "no such file",
                        "filenotfound", "no such port", "the system cannot")):
                    _done("✗",
                          f"<b>{port} was not found.</b>  "
                          "Check the USB or serial cable is plugged in, "
                          "then click ⟳ to refresh the list.",
                          "#ff5555")
                elif "baud" in low or "speed" in low:
                    _done("✗",
                          f"<b>Baud rate {baud} is not supported by {port}.</b>  "
                          "Try a different baud rate above.",
                          "#ff5555")
                else:
                    _done("⚠", f"<b>Could not open {port}:</b>  {exc}",
                          "#cc8800")
                return
            finally:
                _ex.shutdown(wait=False)

            # ── Step 2: brief read for unsolicited device data ─────────────
            if cancel_event and cancel_event.is_set():
                try: ser.close()
                except Exception: pass
                _cancelled(); return

            try:
                data = ser.read(4)   # timeout=0.3 s already set on ser
            except Exception:
                data = b""
            finally:
                try: ser.close()
                except Exception: pass

            if cancel_event and cancel_event.is_set():
                _cancelled(); return

            if data:
                _done("✓",
                      f"{port} opened — device is sending data. "
                      "Click <b>Connect</b> to proceed.",
                      "#00d4aa")
            else:
                _done("✓",
                      f"{port} opened at {baud} baud. "
                      "No unsolicited data (normal for most instruments). "
                      "Click <b>Connect</b> to proceed.",
                      "#00d4aa")

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _set_port_status(lbl: "QLabel", icon: str, text: str, color: str):
        """Update the inline port-test status label on the Qt main thread."""
        def _apply():
            try:
                lbl.setText(
                    f"<span style='color:{color}; font-size:10pt'>{icon}</span>"
                    "&nbsp;&nbsp;<span style='color:" + PALETTE["text"] + "'>" + str(text) + "</span>")
                lbl.setVisible(True)
            except RuntimeError:
                pass   # widget was deleted before the timer fired
        QTimer.singleShot(0, _apply)

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
        disc_btn.setStyleSheet(scaled_qss(
            f"QPushButton{{background:#2a0a0a; color:{PALETTE['danger']}; "
            f"border:1px solid {PALETTE['danger']}22; border-radius:4px; font-size:8.5pt;}}"
            f"QPushButton:hover{{background:#3a0a0a;}}"
            f"QPushButton:disabled{{color:{PALETTE['border']}; "
            f"border-color:{PALETTE['border']}; background:{PALETTE['surface3']};}}"))
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
        l.setStyleSheet(f"font-size:8.5pt; color:{PALETTE['textDim']};")
        return l


# ------------------------------------------------------------------ #
#  Right panel — driver store                                         #
# ------------------------------------------------------------------ #

class _DriverCard(QFrame):
    install_requested        = pyqtSignal(object)   # RemoteDriverEntry
    install_cancel_requested = pyqtSignal()          # user hit Cancel while installing

    def __init__(self, entry: RemoteDriverEntry, parent=None):
        super().__init__(parent)
        self._entry = entry
        self.setFixedHeight(110)
        self.setStyleSheet(
            f"QFrame{{background:{PALETTE['surface2']}; border:1px solid {PALETTE['border']};"
            f" border-radius:5px;}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        # Top row: name + version badge
        top = QHBoxLayout()
        name = QLabel(entry.display_name)
        name.setStyleSheet(
            f"font-size:9.5pt; font-weight:bold; color:{PALETTE['text']};")

        ver_color = PALETTE["accent"] if not entry.already_current else PALETTE["border"]
        ver_bg    = PALETTE["activeItem"] if not entry.already_current else PALETTE["surface"]
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
        cl.setStyleSheet(f"font-size:8.5pt; color:{PALETTE['textDim']};")
        cl.setWordWrap(True)
        lay.addWidget(cl)

        # Bottom row: hot-load indicator + install button
        bot = QHBoxLayout()
        hl_lbl = QLabel(
            "⚡ Hot-loadable" if entry.hot_loadable else "↻ Requires restart")
        hl_lbl.setStyleSheet(
            f"font-size:8.5pt; "
            f"color:{PALETTE['accent'] + '66' if entry.hot_loadable else PALETTE['textDim']};")

        if entry.already_current:
            self._btn = QPushButton("✓  Up to date")
            self._btn.setEnabled(False)
            self._btn.setStyleSheet(
                f"QPushButton{{background:{PALETTE['surface3']}; color:{PALETTE['border']}; "
                f"border:1px solid {PALETTE['border']}; border-radius:3px; "
                f"font-size:8.5pt; padding:2px 10px;}}")
        else:
            self._btn = QPushButton("⬇  Install")
            self._btn.setStyleSheet(
                f"QPushButton {{"
                f"    background:{PALETTE['activeItem']}; color:{PALETTE['accent']};"
                f"    border:1px solid {PALETTE['accent']}44; border-radius:3px;"
                f"    font-size:8.5pt; padding:2px 10px;"
                f"}}"
                f"QPushButton:hover {{ background:#0d3a22; }}"
                f"QPushButton:disabled {{ color:{PALETTE['border']}; "
                f"    border-color:{PALETTE['border']}; background:{PALETTE['surface3']}; }}"
            )
            self._btn.clicked.connect(
                lambda: self.install_requested.emit(self._entry))

        bot.addWidget(hl_lbl, 1)
        bot.addWidget(self._btn)
        lay.addLayout(bot)

    def set_installing(self):
        """Replace the Install button with a live ✕ Cancel button."""
        self._btn.setEnabled(True)
        self._btn.setText("✕  Cancel")
        self._btn.setStyleSheet("""
            QPushButton {
                background:#2a0a0a; color:#ff7777;
                border:1px solid #ff444433; border-radius:3px;
                font-size:8.5pt; padding:2px 10px;
            }
            QPushButton:hover { background:#3a1010; }
        """)
        try:
            self._btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._btn.clicked.connect(self.install_cancel_requested.emit)

    def set_install_idle(self):
        """Restore the Install button after a user-cancelled install."""
        self._btn.setEnabled(True)
        self._btn.setText("⬇  Install")
        self._btn.setStyleSheet(
            f"QPushButton {{"
            f"    background:{PALETTE['activeItem']}; color:{PALETTE['accent']};"
            f"    border:1px solid {PALETTE['accent']}44; border-radius:3px;"
            f"    font-size:8.5pt; padding:2px 10px;"
            f"}}"
            f"QPushButton:hover {{ background:#0d3a22; }}"
            f"QPushButton:disabled {{ color:{PALETTE['border']}; "
            f"    border-color:{PALETTE['border']}; background:{PALETTE['surface3']}; }}"
        )
        try:
            self._btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._btn.clicked.connect(
            lambda: self.install_requested.emit(self._entry))

    def set_done(self, hot_loaded: bool):
        self._btn.setText("✓  Installed" +
                          (" (hot-loaded)" if hot_loaded else " (restart)"))


class _DriverStorePanel(QWidget):
    def __init__(self, device_manager: DeviceManager):
        super().__init__()
        self._mgr    = device_manager
        self._store  = DriverStore(device_manager)
        self._cards: Dict[str, _DriverCard] = {}

        # ── Fetch-state flags ─────────────────────────────────────────── #
        self._fetching       = False          # True while index HTTP fetch is running
        self._fetch_cancel   = threading.Event()

        self._build_store_stylesheets()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._store_hdr = QWidget()
        self._store_hdr.setFixedHeight(36)
        self._store_hdr.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        hl  = QHBoxLayout(self._store_hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        self._store_title = QLabel("DRIVER STORE")
        self._store_title.setStyleSheet(
            f"font-size:9.5pt; letter-spacing:2px; color:{PALETTE['textDim']};")
        self._refresh_btn = QPushButton("🌐  Check")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.setStyleSheet(self._ss_check)
        hl.addWidget(self._store_title, 1)
        hl.addWidget(self._refresh_btn)
        root.addWidget(self._store_hdr)

        # Progress / status bar
        self._status = QLabel("Click 'Check' to fetch available driver updates.")
        self._status.setStyleSheet(
            f"font-size:8.5pt; color:{PALETTE['textDim']}; padding:6px 12px; "
            f"background:{PALETTE['surface3']}; border-bottom:1px solid {PALETTE['surface']};")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(3)
        self._prog.setTextVisible(False)
        self._prog.setVisible(False)
        self._prog.setStyleSheet(
            f"QProgressBar {{ background:{PALETTE['surface3']}; border:none; margin:0; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['accent']}; }}")
        root.addWidget(self._prog)

        # Card scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none; background:{PALETTE['surface3']};}}")
        self._card_container = QWidget()
        self._card_layout    = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(8, 8, 8, 8)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        root.addWidget(scroll, 1)

        self._refresh_btn.clicked.connect(self._fetch_index)

    def _build_store_stylesheets(self):
        self._ss_check = _pt(
            f"QPushButton {{"
            f"    background:{PALETTE['surface']}; color:{PALETTE['info']};"
            f"    border:1px solid {PALETTE['info']}66; border-radius:3px;"
            f"    font-size:8.5pt; padding:0 8px;"
            f"}}"
            f"QPushButton:hover {{ background:{PALETTE['surface2']}; }}"
            f"QPushButton:disabled {{ color:{PALETTE['border']}; "
            f"    border-color:{PALETTE['border']}; }}"
        )
        self._ss_cancel = _pt(
            f"QPushButton {{"
            f"    background:#2a0a0a; color:#ff7777;"
            f"    border:1px solid #ff444433; border-radius:3px;"
            f"    font-size:8.5pt; padding:0 8px;"
            f"}}"
            f"QPushButton:hover {{ background:#3a1010; }}"
            f"QPushButton:disabled {{ color:{PALETTE['border']}; "
            f"    border-color:{PALETTE['border']}; }}"
        )

    def _apply_styles(self) -> None:
        self._build_store_stylesheets()
        self._store_hdr.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        self._store_title.setStyleSheet(
            f"font-size:9.5pt; letter-spacing:2px; color:{PALETTE['textDim']};")
        self._status.setStyleSheet(
            f"font-size:8.5pt; color:{PALETTE['textDim']}; padding:6px 12px; "
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['surface']};")
        self._prog.setStyleSheet(
            f"QProgressBar {{ background:{PALETTE['surface3']}; border:none; margin:0; }}"
            f"QProgressBar::chunk {{ background:{PALETTE['accent']}; }}")
        if not self._fetching:
            self._refresh_btn.setStyleSheet(self._ss_check)

    def _fetch_index(self):
        """Toggle between starting a fetch and cancelling one in progress."""
        if self._fetching:
            # ── Cancel ────────────────────────────────────────────────── #
            self._fetch_cancel.set()
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setText("Cancelling…")
            self._status.setText("Cancelling check…")
            return

        # ── Start ──────────────────────────────────────────────────────── #
        self._fetching = True
        self._fetch_cancel.clear()
        self._refresh_btn.setText("✕  Cancel")
        self._refresh_btn.setStyleSheet(self._ss_cancel)
        self._prog.setVisible(True)
        self._status.setText("Connecting to Microsanj driver repository…")

        def _run():
            try:
                entries = self._store.fetch_index(
                    progress_cb=lambda m: QTimer.singleShot(
                        0, lambda msg=m: self._status.setText(msg)),
                    cancel_event=self._fetch_cancel)
                if self._fetch_cancel.is_set():
                    QTimer.singleShot(0, self._on_fetch_cancelled)
                else:
                    QTimer.singleShot(0, lambda: self._populate(entries))
            except InterruptedError:
                QTimer.singleShot(0, self._on_fetch_cancelled)
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
                f"font-size:9.5pt; letter-spacing:1.5px; color:{PALETTE['accent']}66; "
                f"padding:4px 2px;")
            self._card_layout.insertWidget(
                self._card_layout.count() - 1, sec)

        for e in updates + current:
            card = _DriverCard(e)
            card.install_requested.connect(self._install_driver)
            self._card_layout.insertWidget(
                self._card_layout.count() - 1, card)
            self._cards[e.uid] = card

        self._fetching = False
        self._prog.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("🌐  Check")
        self._refresh_btn.setStyleSheet(self._ss_check)

    def _on_fetch_cancelled(self):
        """Called on the Qt thread when the user cancels a fetch."""
        self._fetching = False
        self._prog.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("🌐  Check")
        self._refresh_btn.setStyleSheet(self._ss_check)
        self._status.setText("Check cancelled.")

    def _on_fetch_error(self, err: str):
        self._fetching = False
        self._prog.setVisible(False)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("🌐  Check")
        self._refresh_btn.setStyleSheet(self._ss_check)
        self._status.setText(f"⚠  {err}")
        self._status.setStyleSheet(
            f"font-size:8.5pt; color:{PALETTE['warning']}; padding:6px 12px; "
            f"background:{PALETTE['surface3']}; border-bottom:1px solid {PALETTE['surface']};")

    def _install_driver(self, entry: RemoteDriverEntry):
        card = self._cards.get(entry.uid)
        if card:
            card.set_installing()

        # Disable the Check button while an install is running so we don't
        # start a concurrent fetch that shares the progress bar.
        self._refresh_btn.setEnabled(False)
        self._prog.setVisible(True)

        install_cancel = threading.Event()
        if card:
            # Wire the card's "✕ Cancel" button to our local cancel event.
            card.install_cancel_requested.connect(install_cancel.set)

        def _run():
            result = self._store.install(
                entry,
                progress_cb=lambda m: QTimer.singleShot(
                    0, lambda msg=m: self._status.setText(msg)),
                cancel_event=install_cancel)
            _was_cancelled = install_cancel.is_set() or result.error == "cancelled"
            def _cb():
                self._on_install_done(result, card, _was_cancelled)
            QTimer.singleShot(0, _cb)

        threading.Thread(target=_run, daemon=True).start()

    def _on_install_done(self, result, card, was_cancelled: bool = False):
        self._prog.setVisible(False)
        # Re-enable the Check button now that the install has finished.
        if not self._fetching:
            self._refresh_btn.setEnabled(True)

        if was_cancelled:
            if card:
                try:
                    card.set_install_idle()
                except RuntimeError:
                    pass
            self._status.setText("Install cancelled.")
        elif result.success:
            if card:
                card.set_done(result.hot_loaded)
            if result.needs_restart:
                self._status.setText(
                    "✓  Driver installed. Restart the application to apply.")
            else:
                self._status.setText(
                    "✓  Driver hot-loaded — active immediately.")
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

    hw_status_changed      = pyqtSignal(bool)
    demo_requested         = pyqtSignal()   # user chose "Run in Demo Mode" from the no-devices dialog
    setup_wizard_requested = pyqtSignal()   # user chose "Setup Wizard" from the no-devices dialog

    def __init__(self, device_manager: DeviceManager, parent=None,
                 demo_mode_getter=None):
        super().__init__(parent,
                         Qt.Window | Qt.WindowCloseButtonHint)
        self._mgr = device_manager
        self._suppress_auto_scan = False   # set True by suppress_next_scan()
        self._user_closed        = False   # True after user explicitly closes DM
        self._deferred_scan_timer: Optional[QTimer] = None  # cancellable startup timer
        # Optional zero-argument callable that returns True while demo mode is
        # active.  When set, showEvent suppresses the automatic scan so the UI
        # never probes for hardware just because the user opened the dialog —
        # the user must deliberately click Scan if they want discovery to run.
        self._demo_mode_getter = demo_mode_getter
        self.setWindowTitle("Device Manager")
        self.setMinimumSize(920, 580)
        self.resize(1080, 660)
        self.setStyleSheet(_pt(
            f"QDialog {{ background:{PALETTE['surface3']}; }}"
            f"QGroupBox {{"
            f"    color:{PALETTE['textSub']}; font-size:9.5pt; letter-spacing:1px;"
            f"    border:1px solid {PALETTE['border']}; border-radius:4px;"
            f"    margin-top:10px; padding-top:10px;"
            f"}}"
            f"QGroupBox::title {{"
            f"    subcontrol-origin:margin; left:8px; padding:0 4px;"
            f"}}"
            f"QLabel {{ color:{PALETTE['textDim']}; font-size:8.5pt; }}"
            f"QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{"
            f"    background:{PALETTE['surface']}; color:{PALETTE['text']};"
            f"    border:1px solid {PALETTE['border']}; border-radius:3px;"
            f"    padding:2px 6px; font-size:8.5pt;"
            f"}}"
            f"QPushButton {{"
            f"    background:{PALETTE['border']}; color:{PALETTE['textDim']};"
            f"    border:1px solid {PALETTE['border']}; border-radius:4px;"
            f"    padding:2px 8px; font-size:8.5pt;"
            f"}}"
            f"QPushButton:hover {{ background:{PALETTE['surface2']}; color:{PALETTE['text']}; }}"
            f"QPushButton[objectName=\"primary\"] {{"
            f"    background:{PALETTE['activeItem']}; color:{PALETTE['accent']};"
            f"    border:1px solid {PALETTE['accent']}44;"
            f"}}"
            f"QPushButton[objectName=\"primary\"]:hover {{ background:#0d3a22; }}"
            f"QScrollBar:vertical {{"
            f"    background:{PALETTE['surface3']}; width:6px; border-radius:3px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background:{PALETTE['border']}; border-radius:3px;"
            f"}}"
        ))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Title bar ----
        self._title_bar = QWidget()
        self._title_bar.setFixedHeight(44)
        self._title_bar.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        tl = QHBoxLayout(self._title_bar)
        tl.setContentsMargins(16, 0, 16, 0)
        self._title_lbl = QLabel("⚙  Device Manager")
        self._title_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; font-weight:bold; "
            f"color:{PALETTE['textDim']};")
        tl.addWidget(self._title_lbl, 1)

        # Log toggle button — explicit stylesheet so the dialog-level rule
        # (which sets font-size:8.5pt and padding) doesn't cause overflow
        # on the fixed 72×28 footprint of this button.
        self._log_btn = QPushButton("📋  Log")
        self._log_btn.setFixedSize(72, 28)
        self._log_btn.setCheckable(True)
        self._log_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{ font-size:8.5pt; padding:0 6px; }}"
            f"QPushButton:checked {{ background:{PALETTE['activeItem']}; "
            f"color:{PALETTE['accent']}; border-color:{PALETTE['accent']}44; }}"))
        self._log_btn.clicked.connect(self._toggle_log)
        tl.addWidget(self._log_btn)

        root.addWidget(self._title_bar)

        # ---- Three-panel splitter ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{PALETTE['border']}; width:1px; }}")
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
        self._log_widget.setVisible(False)
        ll = QVBoxLayout(self._log_widget)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self._log_sep = QFrame()
        self._log_sep.setFrameShape(QFrame.HLine)
        self._log_sep.setStyleSheet(f"color:{PALETTE['border']};")
        ll.addWidget(self._log_sep)

        # Log toolbar: label + Copy button
        self._log_toolbar = QWidget()
        self._log_toolbar.setFixedHeight(26)
        self._log_toolbar.setStyleSheet(
            f"background:{PALETTE['surface3']};")
        lt = QHBoxLayout(self._log_toolbar)
        lt.setContentsMargins(10, 0, 6, 0)
        self._log_lbl = QLabel("Startup Diagnostics — live log output")
        self._log_lbl.setStyleSheet(
            f"font-size:7.5pt; color:{PALETTE['textSub']}; font-style:italic;")
        lt.addWidget(self._log_lbl, 1)
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setFixedSize(48, 18)
        self._copy_btn.setStyleSheet(
            f"QPushButton{{font-size:7pt; padding:0; background:{PALETTE['surface']}; "
            f"color:{PALETTE['textDim']}; border:1px solid {PALETTE['border']}; border-radius:3px;}}"
            f"QPushButton:hover{{color:{PALETTE['text']}; border-color:{PALETTE['textDim']};}}")
        self._copy_btn.clicked.connect(self._copy_log)
        lt.addWidget(self._copy_btn)
        ll.addWidget(self._log_toolbar)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(120)
        self._log_edit.setMaximumHeight(220)
        self._log_edit.setStyleSheet(scaled_qss(
            f"background:{PALETTE['surface3']}; color:{PALETTE['textSub']}; "
            f"font-family:Menlo,Consolas,monospace; font-size:8pt; border:none;"))
        ll.addWidget(self._log_edit)
        root.addWidget(self._log_widget)

        # Python logging → log panel: attach a handler so all app log
        # messages are visible in real-time when the panel is open.
        self._log_handler = _QTextEditHandler(self._log_edit)

        # Auto-open the log panel when --debug / --verbose was passed
        import sys as _sys
        if "--debug" in _sys.argv or "--verbose" in _sys.argv:
            self._log_widget.setVisible(True)
            self._log_btn.setChecked(True)
            import logging as _logging
            _logging.getLogger().addHandler(self._log_handler)

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

        self._apply_styles()

    # ---------------------------------------------------------------- #
    #  Theme                                                            #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        self.setStyleSheet(_pt(
            f"QDialog {{ background:{PALETTE['surface3']}; }}"
            f"QGroupBox {{"
            f"    color:{PALETTE['textSub']}; font-size:9.5pt; letter-spacing:1px;"
            f"    border:1px solid {PALETTE['border']}; border-radius:4px;"
            f"    margin-top:10px; padding-top:10px;"
            f"}}"
            f"QGroupBox::title {{"
            f"    subcontrol-origin:margin; left:8px; padding:0 4px;"
            f"}}"
            f"QLabel {{ color:{PALETTE['textDim']}; font-size:8.5pt; }}"
            f"QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{"
            f"    background:{PALETTE['surface']}; color:{PALETTE['text']};"
            f"    border:1px solid {PALETTE['border']}; border-radius:3px;"
            f"    padding:2px 6px; font-size:8.5pt;"
            f"}}"
            f"QPushButton {{"
            f"    background:{PALETTE['border']}; color:{PALETTE['textDim']};"
            f"    border:1px solid {PALETTE['border']}; border-radius:4px;"
            f"    padding:2px 8px; font-size:8.5pt;"
            f"}}"
            f"QPushButton:hover {{ background:{PALETTE['surface2']}; color:{PALETTE['text']}; }}"
            f"QPushButton[objectName=\"primary\"] {{"
            f"    background:{PALETTE['activeItem']}; color:{PALETTE['accent']};"
            f"    border:1px solid {PALETTE['accent']}44;"
            f"}}"
            f"QPushButton[objectName=\"primary\"]:hover {{ background:#0d3a22; }}"
            f"QScrollBar:vertical {{"
            f"    background:{PALETTE['surface3']}; width:6px; border-radius:3px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background:{PALETTE['border']}; border-radius:3px;"
            f"}}"
        ))
        self._title_bar.setStyleSheet(
            f"background:{PALETTE['surface3']}; "
            f"border-bottom:1px solid {PALETTE['border']};")
        self._title_lbl.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; font-weight:bold; "
            f"color:{PALETTE['textDim']};")
        self._log_btn.setStyleSheet(scaled_qss(
            f"QPushButton {{ font-size:8.5pt; padding:0 6px; }}"
            f"QPushButton:checked {{ background:{PALETTE['activeItem']}; "
            f"color:{PALETTE['accent']}; border-color:{PALETTE['accent']}44; }}"))
        self._log_sep.setStyleSheet(f"color:{PALETTE['border']};")
        self._log_toolbar.setStyleSheet(
            f"background:{PALETTE['surface3']};")
        self._log_lbl.setStyleSheet(
            f"font-size:7.5pt; color:{PALETTE['textSub']}; font-style:italic;")
        self._copy_btn.setStyleSheet(
            f"QPushButton{{font-size:7pt; padding:0; background:{PALETTE['surface']}; "
            f"color:{PALETTE['textDim']}; border:1px solid {PALETTE['border']}; border-radius:3px;}}"
            f"QPushButton:hover{{color:{PALETTE['text']}; border-color:{PALETTE['textDim']};}}")
        self._log_edit.setStyleSheet(scaled_qss(
            f"background:{PALETTE['surface3']}; color:{PALETTE['textSub']}; "
            f"font-family:Menlo,Consolas,monospace; font-size:8pt; border:none;"))
        self._list_panel._apply_styles()
        self._store_panel._apply_styles()

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
        import logging as _logging
        root_logger = _logging.getLogger()
        if checked:
            if self._log_handler not in root_logger.handlers:
                root_logger.addHandler(self._log_handler)
        else:
            root_logger.removeHandler(self._log_handler)

    def _copy_log(self):
        """Copy the full log panel text to the clipboard."""
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(self._log_edit.toPlainText())
        except Exception:
            pass

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

        Note: the scan runs even when in demo mode.  The user requirement is
        "when the user launches the Device Manager it should scan for devices"
        regardless of the current mode.  If no devices are found while already
        in demo mode, _offer_demo_dialog shows the "already in demo mode"
        variant instead of the normal demo-mode offer.
        """
        super().showEvent(event)
        self._user_closed = False   # user opened the DM again; re-arm offers
        if not self._list_panel._scanning:
            QTimer.singleShot(200, self._initial_scan)

    def closeEvent(self, event):
        """Mark the dialog as explicitly closed and cancel any pending scan.

        When the user closes the Device Manager the deferred startup scan
        timer (if still counting down) is cancelled so it never fires after
        the dialog is gone.  The ``_user_closed`` flag prevents
        ``_offer_demo_dialog`` from forcing the dialog back open to host a
        QMessageBox — if the user chose to close the DM they do not want it
        reopened automatically.
        """
        self._user_closed = True
        if self._deferred_scan_timer is not None:
            self._deferred_scan_timer.stop()
            self._deferred_scan_timer = None
        super().closeEvent(event)

    def _initial_scan(self):
        """Kick off the on-open quick scan via the list panel's unified path.

        Routes through start_scan() so the scan button shows "✕ Cancel"
        during the initial scan and all result/error handling is shared.
        The Network checkbox defaults to unchecked, so this is a fast
        serial/USB-only scan identical to what the old _initial_scan did.

        At app startup (see suppress_next_scan()), the scan is deferred by
        3 seconds instead of starting immediately.  This avoids a race with
        hw_service which also initialises the NI/pyvisa DLL on startup:
        two threads loading the same Windows DLL concurrently causes a 10–30 s
        stall in Parallels.  By the time the deferred scan fires, hw_service
        will have already loaded the DLL, so the DM scan itself completes in
        well under one second.  The demo-mode offer dialog then appears as
        normal once the (fast) deferred scan finds no devices.
        """
        if self._suppress_auto_scan:
            self._suppress_auto_scan = False   # one-shot
            # Defer the scan rather than skip it entirely — the demo-mode
            # offer must still appear even if the user closes the DM right
            # after launch (before 3 s elapses).  Store the timer so that
            # closeEvent() can cancel it if the user deliberately closes the DM.
            self._deferred_scan_timer = QTimer(self)
            self._deferred_scan_timer.setSingleShot(True)
            self._deferred_scan_timer.timeout.connect(
                self._list_panel.start_scan)
            self._deferred_scan_timer.start(3_000)
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

        # If the user deliberately closed the Device Manager (closeEvent set
        # _user_closed=True), do not force it back open.  The deferred scan
        # may still complete after the DM was closed; silently discard the
        # offer rather than re-opening a window the user just dismissed.
        if self._user_closed:
            return

        box = QMessageBox(self)
        box.setWindowTitle("No Devices Found")
        box.setIcon(QMessageBox.Warning)
        box.setText("<b>No compatible hardware was detected.</b>")

        # Check whether the scan turned up any serial ports that weren't
        # matched to a known device — they may be the user's instruments
        # connected with a cable the auto-detector doesn't recognise yet.
        unrecognized_ports = []
        report = getattr(self, "_last_scan_report", None)
        if report:
            from hardware.device_registry import CONN_SERIAL
            unrecognized_ports = [
                d.address for d in report.devices
                if d.connection_type == CONN_SERIAL and d.descriptor is None
            ]

        ports_hint = ""
        if unrecognized_ports:
            port_list = ", ".join(unrecognized_ports)
            if len(unrecognized_ports) == 1:
                ports_hint = (
                    f"\n\n💡  The scan found one connected serial port "
                    f"({port_list}) that wasn't automatically identified.\n"
                    "This is likely one of your instruments.  Click "
                    "\"Setup Wizard\" to assign it to the correct device."
                )
            else:
                ports_hint = (
                    f"\n\n💡  The scan found {len(unrecognized_ports)} connected "
                    f"serial ports ({port_list}) that weren't automatically "
                    "identified.  These are likely your instruments.  Click "
                    "\"Setup Wizard\" to assign each port to the correct device."
                )

        if already_demo:
            box.setInformativeText(
                "No new hardware was found.  You are already running in "
                "Demo Mode with simulated hardware.\n\n"
                "Make sure your devices are powered on and their USB cables "
                "are connected, then click \"Scan Again\"." + ports_hint)
        else:
            box.setInformativeText(
                "Make sure all devices are powered on and their USB cables "
                "are connected, then scan again.\n\n"
                "Not ready to connect hardware?  Select \"Demo Mode\" to "
                "explore the full interface with simulated devices — "
                "no physical hardware required." + ports_hint)

        scan_btn  = box.addButton("🔍  Scan Again", QMessageBox.AcceptRole)
        wizard_btn = None

        if already_demo:
            continue_btn = box.addButton(
                "Continue in Demo Mode", QMessageBox.RejectRole)
            if unrecognized_ports:
                wizard_btn = box.addButton(
                    "⚙  Setup Wizard", QMessageBox.ActionRole)
            else:
                box.addButton("Add Manually", QMessageBox.ActionRole)
        else:
            demo_btn = box.addButton("Demo Mode", QMessageBox.ActionRole)
            if unrecognized_ports:
                wizard_btn = box.addButton(
                    "⚙  Setup Wizard", QMessageBox.RejectRole)
            else:
                box.addButton("Add Manually", QMessageBox.RejectRole)

        box.setDefaultButton(scan_btn)
        box.exec_()

        clicked = box.clickedButton()
        if clicked is scan_btn:
            self._list_panel.start_scan()
        elif not already_demo and clicked is demo_btn:
            self.close()          # hide DM before switching mode
            self.demo_requested.emit()
        elif already_demo and clicked is continue_btn:
            self.close()          # user confirmed staying in demo mode — close DM
        elif wizard_btn is not None and clicked is wizard_btn:
            self.close()          # close DM, then open guided wizard
            self.setup_wizard_requested.emit()
