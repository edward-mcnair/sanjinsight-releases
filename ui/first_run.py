"""
ui/first_run.py

First-Run Hardware Setup Wizard
--------------------------------
Shown automatically the first time SanjINSIGHT is launched (or when the user
chooses  Help → Hardware Setup from the menu).

Walks the user through:
  Page 1 — Welcome / overview
  Page 2 — TEC controllers  (Meerstetter COM port + ATEC COM port)
  Page 3 — Camera           (driver + NI camera name / Basler serial)
  Page 4 — FPGA             (bitfile path + resource string)
  Page 5 — Done / summary

On Finish it writes the confirmed values into config.yaml and returns.
If the user cancels, config.yaml is left unchanged.

Usage in main_app.py
--------------------
    from ui.first_run import should_show_first_run, FirstRunWizard

    if should_show_first_run():
        dlg = FirstRunWizard(config_path, parent=window)
        dlg.exec_()
"""

from __future__ import annotations

import os
import re
import sys
import glob
import logging
from typing import Optional

import yaml

from PyQt5.QtCore    import Qt, QThread, pyqtSignal
from PyQt5.QtGui     import QFont, QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QStackedWidget, QWidget, QFrame,
    QFileDialog, QCheckBox, QGroupBox, QFormLayout, QScrollArea,
    QSizePolicy, QApplication, QMessageBox,
)

log = logging.getLogger(__name__)

# ── Sentinel file placed in the config folder after first-run ────────────────
_SENTINEL_FILENAME = ".first_run_complete"


def _sentinel_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(config_path), _SENTINEL_FILENAME)


def should_show_first_run(config_path: str) -> bool:
    """Return True if the first-run wizard has never been completed."""
    return not os.path.exists(_sentinel_path(config_path))


def _mark_first_run_done(config_path: str) -> None:
    try:
        with open(_sentinel_path(config_path), "w") as f:
            f.write("first_run_complete\n")
    except OSError:
        pass


# ── Serial port discovery ─────────────────────────────────────────────────────

def _list_serial_ports() -> list[str]:
    """Return available serial port names for the current OS."""
    ports: list[str] = []
    if sys.platform.startswith("win"):
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, i)
                    ports.append(str(value))
                    i += 1
                except OSError:
                    break
        except Exception:
            # Fall back to brute-force probe
            import serial
            for n in range(1, 33):
                p = f"COM{n}"
                try:
                    s = serial.Serial(p)
                    s.close()
                    ports.append(p)
                except Exception:
                    pass
    else:
        # macOS / Linux
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/tty.usbserial*",
                    "/dev/tty.usbmodem*", "/dev/ttyS*"]
        for pat in patterns:
            ports.extend(sorted(glob.glob(pat)))
    return sorted(set(ports))


# ── Shared style helpers ──────────────────────────────────────────────────────

_BTN_PRIMARY = """
    QPushButton {
        background:#4e73df; color:#fff; border:none; border-radius:6px;
        padding:8px 22px; font-size:13pt; font-weight:600;
    }
    QPushButton:hover   { background:#3a5fc8; }
    QPushButton:pressed { background:#2e4fa8; }
    QPushButton:disabled{ background:#333; color:#666; }
"""
_BTN_SECONDARY = """
    QPushButton {
        background:#1e2337; color:#aaa; border:1px solid #333;
        border-radius:6px; padding:8px 22px; font-size:13pt;
    }
    QPushButton:hover   { background:#2a3249; color:#ccc; }
    QPushButton:pressed { background:#1a1f33; }
"""
_INPUT_SS = """
    QLineEdit, QComboBox {
        background:#13172a; color:#ddd; border:1px solid #2a3249;
        border-radius:4px; padding:5px 10px; font-size:13pt;
        selection-background-color:#4e73df;
    }
    QLineEdit:focus, QComboBox:focus { border-color:#4e73df; }
    QComboBox::drop-down { border:none; }
    QComboBox QAbstractItemView { background:#13172a; color:#ddd; border:1px solid #2a3249; }
"""
_LABEL_H1 = "font-size:20pt; font-weight:700; color:#fff;"
_LABEL_H2 = "font-size:14pt; font-weight:600; color:#c0c8e0;"
_LABEL_BODY = "font-size:12pt; color:#8892a4;"
_LABEL_HINT = "font-size:10pt; color:#5a6480; font-style:italic;"


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#1e2337;")
    return f


# ── Individual wizard pages ───────────────────────────────────────────────────

class _PageBase(QWidget):
    """Common layout for a wizard page — title + content area."""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 20)
        root.setSpacing(10)

        h1 = QLabel(title)
        h1.setStyleSheet(_LABEL_H1)
        root.addWidget(h1)

        h2 = QLabel(subtitle)
        h2.setStyleSheet(_LABEL_BODY)
        h2.setWordWrap(True)
        root.addWidget(h2)

        root.addWidget(_sep())
        root.addSpacing(4)

        self._content = QVBoxLayout()
        self._content.setSpacing(14)
        root.addLayout(self._content, 1)

    def values(self) -> dict:
        """Return a flat dict of key→value to be merged into config."""
        return {}


class _PageWelcome(_PageBase):
    def __init__(self, parent=None):
        super().__init__(
            "Welcome to SanjINSIGHT",
            "Let's confirm your hardware connections before the first measurement. "
            "This takes about two minutes and only needs to be done once per installation.",
            parent)

        body = QLabel(
            "You will be asked about:\n\n"
            "  ①  TEC controllers   — Meerstetter TEC-1089 and ATEC-302\n"
            "  ②  Camera            — Basler acA1920-155um\n"
            "  ③  FPGA              — NI 9637 via NI-RIO\n\n"
            "Your answers are saved to  config.yaml  and can be changed at any "
            "time from  Settings → Hardware Setup.")
        body.setStyleSheet("font-size:13pt; color:#c0c8e0; line-height:1.6;")
        body.setWordWrap(True)
        self._content.addWidget(body)
        self._content.addStretch(1)

        tip = QLabel(
            "💡  If you are running on a development machine without hardware connected, "
            "leave all drivers set to  simulated  — the app will still open and operate "
            "with synthetic data.")
        tip.setStyleSheet(
            "font-size:11pt; color:#5a6480; font-style:italic; "
            "background:#13172a; border:1px solid #1e2337; border-radius:5px; "
            "padding:10px;")
        tip.setWordWrap(True)
        self._content.addWidget(tip)


class _PortRow(QHBoxLayout):
    """A label + combo + refresh-button row for a single serial port."""

    def __init__(self, label: str, default_port: str):
        super().__init__()
        self.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size:12pt; color:#8892a4;")
        lbl.setFixedWidth(220)
        self.addWidget(lbl)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setStyleSheet(_INPUT_SS)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setFixedHeight(34)
        self.addWidget(self.combo, 1)

        refresh = QPushButton("⟳")
        refresh.setFixedSize(34, 34)
        refresh.setToolTip("Refresh port list")
        refresh.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:0"))
        refresh.clicked.connect(self._refresh)
        self.addWidget(refresh)

        self._default = default_port
        self._refresh()
        self._set_value(default_port)

    def _refresh(self):
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        ports = _list_serial_ports()
        if not ports:
            ports = [self._default]
        self.combo.addItems(ports)
        if current in ports:
            self.combo.setCurrentText(current)
        elif self._default in ports:
            self.combo.setCurrentText(self._default)
        self.combo.blockSignals(False)

    def _set_value(self, v: str):
        if self.combo.findText(v) == -1:
            self.combo.addItem(v)
        self.combo.setCurrentText(v)

    @property
    def value(self) -> str:
        return self.combo.currentText().strip()


class _PageTEC(_PageBase):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            "TEC Controllers",
            "Select the COM ports for the two temperature controllers. "
            "Click ⟳ to refresh the list after plugging in USB adapters.",
            parent)

        meerstetter_cfg = cfg.get("tec_meerstetter", {})
        atec_cfg        = cfg.get("tec_atec",        {})

        # ── Meerstetter ───────────────────────────────────────────────
        g1 = QGroupBox("Meerstetter TEC-1089")
        g1.setStyleSheet(
            "QGroupBox { color:#8892a4; font-size:12pt; border:1px solid #2a3249; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl1 = QFormLayout(g1)
        fl1.setSpacing(8)

        self._meer_driver = QComboBox()
        self._meer_driver.addItems(["meerstetter", "simulated"])
        self._meer_driver.setCurrentText(meerstetter_cfg.get("driver", "simulated"))
        self._meer_driver.setStyleSheet(_INPUT_SS)
        fl1.addRow(_lbl("Driver:"), self._meer_driver)

        self._meer_port = _PortRow("COM Port:", meerstetter_cfg.get("port", "COM3"))
        fl1.addRow(self._meer_port)

        addr_lbl = QLabel(f"Address: {meerstetter_cfg.get('address', 2)}  "
                          f"Baud: {meerstetter_cfg.get('baudrate', 57600)}")
        addr_lbl.setStyleSheet(_LABEL_HINT)
        fl1.addRow(addr_lbl)

        self._content.addWidget(g1)

        # ── ATEC ──────────────────────────────────────────────────────
        g2 = QGroupBox("ATEC-302")
        g2.setStyleSheet(g1.styleSheet())
        fl2 = QFormLayout(g2)
        fl2.setSpacing(8)

        self._atec_driver = QComboBox()
        self._atec_driver.addItems(["atec", "simulated"])
        self._atec_driver.setCurrentText(atec_cfg.get("driver", "simulated"))
        self._atec_driver.setStyleSheet(_INPUT_SS)
        fl2.addRow(_lbl("Driver:"), self._atec_driver)

        self._atec_port = _PortRow("COM Port:", atec_cfg.get("port", "COM4"))
        fl2.addRow(self._atec_port)

        addr2 = QLabel(f"Address: {atec_cfg.get('address', 1)}  "
                       f"Baud: {atec_cfg.get('baudrate', 9600)}")
        addr2.setStyleSheet(_LABEL_HINT)
        fl2.addRow(addr2)

        self._content.addWidget(g2)
        self._content.addStretch(1)

    def values(self) -> dict:
        return {
            "tec_meerstetter.driver": self._meer_driver.currentText(),
            "tec_meerstetter.port":   self._meer_port.value,
            "tec_atec.driver":        self._atec_driver.currentText(),
            "tec_atec.port":          self._atec_port.value,
        }


class _PageCamera(_PageBase):
    def __init__(self, cfg: dict, parent=None):
        cam_cfg = cfg.get("camera", {})
        super().__init__(
            "Camera",
            "Choose the camera driver and connection details. "
            "The Basler acA1920-155um uses the  pypylon  driver.",
            parent)

        g = QGroupBox("Basler acA1920-155um")
        g.setStyleSheet(
            "QGroupBox { color:#8892a4; font-size:12pt; border:1px solid #2a3249; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl = QFormLayout(g)
        fl.setSpacing(10)

        self._drv = QComboBox()
        self._drv.addItems(["pypylon", "ni_imaqdx", "directshow", "simulated"])
        self._drv.setCurrentText(cam_cfg.get("driver", "simulated"))
        self._drv.setStyleSheet(_INPUT_SS)
        self._drv.currentTextChanged.connect(self._update_hints)
        fl.addRow(_lbl("Driver:"), self._drv)

        self._cam_name = QLineEdit(cam_cfg.get("camera_name", "cam4"))
        self._cam_name.setStyleSheet(_INPUT_SS)
        self._cam_name.setFixedHeight(34)
        fl.addRow(_lbl("NI Camera Name:"), self._cam_name)

        self._serial = QLineEdit(cam_cfg.get("serial", ""))
        self._serial.setPlaceholderText("Leave blank for first found camera")
        self._serial.setStyleSheet(_INPUT_SS)
        self._serial.setFixedHeight(34)
        fl.addRow(_lbl("Basler Serial #:"), self._serial)

        self._hint = QLabel("")
        self._hint.setStyleSheet(_LABEL_HINT)
        self._hint.setWordWrap(True)
        fl.addRow(self._hint)

        self._content.addWidget(g)
        self._content.addStretch(1)
        self._update_hints(self._drv.currentText())

    def _update_hints(self, driver: str):
        hints = {
            "pypylon":    "Uses Basler Pylon SDK. Install from basler.com, then: pip install pypylon",
            "ni_imaqdx":  "Uses NI IMAQdx. Install NI Vision Acquisition Software and set the camera name in NI MAX.",
            "directshow": "Generic Windows DirectShow camera (development/fallback only).",
            "simulated":  "No real camera required. Generates synthetic frames.",
        }
        self._hint.setText(hints.get(driver, ""))

    def values(self) -> dict:
        return {
            "camera.driver":      self._drv.currentText(),
            "camera.camera_name": self._cam_name.text().strip(),
            "camera.serial":      self._serial.text().strip(),
        }


class _PageFPGA(_PageBase):
    def __init__(self, cfg: dict, parent=None):
        fpga_cfg = cfg.get("fpga", {})
        super().__init__(
            "FPGA — NI 9637",
            "Specify the compiled bitfile and network resource string. "
            "Find the resource string in NI MAX under  Remote Systems.",
            parent)

        g = QGroupBox("NI 9637 FPGA Module")
        g.setStyleSheet(
            "QGroupBox { color:#8892a4; font-size:12pt; border:1px solid #2a3249; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl = QFormLayout(g)
        fl.setSpacing(10)

        self._drv = QComboBox()
        self._drv.addItems(["ni9637", "simulated"])
        self._drv.setCurrentText(fpga_cfg.get("driver", "simulated"))
        self._drv.setStyleSheet(_INPUT_SS)
        fl.addRow(_lbl("Driver:"), self._drv)

        # Bitfile row with Browse button
        bf_row = QHBoxLayout()
        self._bitfile = QLineEdit(fpga_cfg.get("bitfile", ""))
        self._bitfile.setPlaceholderText("C:/path/to/firmware.lvbitx")
        self._bitfile.setStyleSheet(_INPUT_SS)
        self._bitfile.setFixedHeight(34)
        bf_row.addWidget(self._bitfile, 1)
        browse = QPushButton("Browse…")
        browse.setFixedHeight(34)
        browse.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:0 12px"))
        browse.clicked.connect(self._browse)
        bf_row.addWidget(browse)
        fl.addRow(_lbl("Bitfile path:"), bf_row)

        self._resource = QLineEdit(fpga_cfg.get("resource", "RIO0"))
        self._resource.setStyleSheet(_INPUT_SS)
        self._resource.setFixedHeight(34)
        fl.addRow(_lbl("Resource string:"), self._resource)

        hint = QLabel(
            "Resource examples:  RIO0  ·  rio://169.254.x.x/RIO0  ·  rio://hostname/RIO0\n"
            "The .lvbitx file is compiled from LabVIEW — it ships separately from the software.")
        hint.setStyleSheet(_LABEL_HINT)
        hint.setWordWrap(True)
        fl.addRow(hint)

        self._content.addWidget(g)
        self._content.addStretch(1)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FPGA Bitfile", "",
            "FPGA Bitfiles (*.lvbitx);;All Files (*)")
        if path:
            self._bitfile.setText(path)

    def values(self) -> dict:
        return {
            "fpga.driver":   self._drv.currentText(),
            "fpga.bitfile":  self._bitfile.text().strip(),
            "fpga.resource": self._resource.text().strip(),
        }


class _PageDone(_PageBase):
    def __init__(self, parent=None):
        super().__init__(
            "All Done!",
            "Your hardware configuration has been saved to config.yaml.",
            parent)

        self._summary = QLabel("(summary will appear here)")
        self._summary.setStyleSheet(
            "font-size:12pt; color:#8892a4; background:#13172a; "
            "border:1px solid #1e2337; border-radius:5px; padding:12px;")
        self._summary.setWordWrap(True)
        self._content.addWidget(self._summary)
        self._content.addStretch(1)

        note = QLabel(
            "You can re-run this wizard at any time from  Settings → Hardware Setup.\n"
            "You can also edit  config.yaml  directly — it lives next to main_app.py.")
        note.setStyleSheet(_LABEL_HINT)
        note.setWordWrap(True)
        self._content.addWidget(note)

    def set_summary(self, values: dict):
        lines = []
        for k, v in sorted(values.items()):
            lines.append(f"  {k}: {v!r}")
        self._summary.setText("\n".join(lines) if lines else "(no changes)")


# ── Helper ────────────────────────────────────────────────────────────────────

def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet("font-size:12pt; color:#8892a4;")
    return l


# ── Main wizard dialog ────────────────────────────────────────────────────────

class FirstRunWizard(QDialog):
    """
    Multi-page hardware setup wizard.

    On accept, writes updated values into config.yaml and marks first-run done.
    """

    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._all_values: dict = {}

        self.setWindowTitle("SanjINSIGHT — Hardware Setup")
        self.setModal(True)
        self.resize(680, 560)
        self.setStyleSheet("""
            QDialog   { background:#0e1120; }
            QGroupBox { background:#13172a; }
            QLabel    { background:transparent; }
        """)

        # Load current config
        self._cfg_hw: dict = {}
        try:
            with open(config_path, "r") as f:
                raw = yaml.safe_load(f) or {}
            self._cfg_hw = raw.get("hardware", {})
        except Exception as e:
            log.warning(f"FirstRunWizard: could not read config: {e}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Progress bar (step dots) ──────────────────────────────────
        prog_bar = QWidget()
        prog_bar.setFixedHeight(44)
        prog_bar.setStyleSheet("background:#080b17; border-bottom:1px solid #1a1f33;")
        pb_lay = QHBoxLayout(prog_bar)
        pb_lay.setContentsMargins(30, 0, 30, 0)
        self._dots: list[QLabel] = []
        step_labels = ["Welcome", "TEC", "Camera", "FPGA", "Done"]
        for i, lbl in enumerate(step_labels):
            dot = QLabel(f"● {lbl}")
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("font-size:11pt; color:#2a3249;")
            pb_lay.addWidget(dot, 1)
            self._dots.append(dot)
            if i < len(step_labels) - 1:
                line = QLabel("──")
                line.setStyleSheet("color:#1e2337;")
                pb_lay.addWidget(line)
        root.addWidget(prog_bar)

        # ── Page stack ────────────────────────────────────────────────
        self._page_welcome = _PageWelcome()
        self._page_tec     = _PageTEC(self._cfg_hw)
        self._page_camera  = _PageCamera(self._cfg_hw)
        self._page_fpga    = _PageFPGA(self._cfg_hw)
        self._page_done    = _PageDone()

        self._stack = QStackedWidget()
        for p in [self._page_welcome, self._page_tec,
                  self._page_camera, self._page_fpga, self._page_done]:
            self._stack.addWidget(p)
        root.addWidget(self._stack, 1)

        # ── Navigation bar ────────────────────────────────────────────
        nav = QWidget()
        nav.setFixedHeight(60)
        nav.setStyleSheet("background:#080b17; border-top:1px solid #1a1f33;")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(30, 0, 30, 0)
        nav_lay.setSpacing(10)

        self._skip_btn = QPushButton("Skip Setup")
        self._skip_btn.setStyleSheet(_BTN_SECONDARY)
        self._skip_btn.clicked.connect(self._on_skip)
        nav_lay.addWidget(self._skip_btn)
        nav_lay.addStretch(1)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setStyleSheet(_BTN_SECONDARY)
        self._back_btn.clicked.connect(self._on_back)
        nav_lay.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(_BTN_PRIMARY)
        self._next_btn.clicked.connect(self._on_next)
        nav_lay.addWidget(self._next_btn)
        root.addWidget(nav)

        self._go_to(0)

    # ── Navigation ────────────────────────────────────────────────────

    def _go_to(self, idx: int):
        self._stack.setCurrentIndex(idx)
        n = self._stack.count()
        self._back_btn.setEnabled(idx > 0)
        self._skip_btn.setVisible(idx < n - 1)
        is_last = (idx == n - 1)
        self._next_btn.setText("Finish" if is_last else "Next →")

        for i, dot in enumerate(self._dots):
            if i == idx:
                dot.setStyleSheet("font-size:11pt; color:#4e73df; font-weight:700;")
            elif i < idx:
                dot.setStyleSheet("font-size:11pt; color:#00d4aa;")
            else:
                dot.setStyleSheet("font-size:11pt; color:#2a3249;")

    def _on_next(self):
        idx = self._stack.currentIndex()
        # Collect values from current page
        page = self._stack.currentWidget()
        self._all_values.update(page.values())

        if idx == self._stack.count() - 1:
            # Finish
            self._write_config()
            self.accept()
        else:
            if idx == self._stack.count() - 2:
                # About to show Done page — populate summary
                self._page_done.set_summary(self._all_values)
            self._go_to(idx + 1)

    def _on_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._go_to(idx - 1)

    def _on_skip(self):
        ret = QMessageBox.question(
            self, "Skip Hardware Setup",
            "Skip for now?\n\n"
            "All drivers will remain set to  simulated  until you run the setup again "
            "from  Settings → Hardware Setup.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            _mark_first_run_done(self._config_path)
            self.reject()

    # ── Config writer ─────────────────────────────────────────────────

    def _write_config(self):
        """
        Merge self._all_values into config.yaml using dotted key paths.
        e.g.  "tec_meerstetter.port" → config["hardware"]["tec_meerstetter"]["port"]
        """
        try:
            with open(self._config_path, "r") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as e:
            log.error(f"FirstRunWizard: cannot read config for writing: {e}")
            return

        hw = raw.setdefault("hardware", {})
        for dotted_key, value in self._all_values.items():
            parts = dotted_key.split(".")
            node = hw
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

        try:
            with open(self._config_path, "w") as f:
                yaml.dump(raw, f, default_flow_style=False, sort_keys=False,
                          allow_unicode=True)
            log.info(f"FirstRunWizard: config written to {self._config_path}")
        except Exception as e:
            log.error(f"FirstRunWizard: cannot write config: {e}")
            QMessageBox.warning(
                self, "Config Write Error",
                f"Could not save to {self._config_path}:\n{e}\n\n"
                "Your changes were not saved. Edit config.yaml manually.")
            return

        _mark_first_run_done(self._config_path)
