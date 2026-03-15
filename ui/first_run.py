"""
ui/first_run.py

First-Run Hardware Setup Wizard
--------------------------------
Shown automatically the first time SanjINSIGHT is launched, and accessible
at any time from  Settings → Hardware Setup.

Walks the user through:
  Page 1 — Welcome / overview  (auto-scan runs in background)
  Page 2 — TEC controllers     (Meerstetter COM port + ATEC COM port)
  Page 3 — Camera              (driver + NI camera name / Basler serial)
  Page 4 — FPGA                (bitfile path + resource string)
  Page 5 — Bias source / SMU   (Keithley, Rigol DP832, VISA generic)
  Page 6 — Motorised stage     (Thorlabs, serial stage)
  Page 7 — AI assistant        (Ollama install + model pull)
  Page 8 — Done / summary

As soon as the dialog opens, a background DeviceScanner thread enumerates all
connected hardware.  When it finishes, driver and port fields are
pre-populated for any devices that are found in the device registry.  The user
can review, adjust, and confirm — then click Finish to write config.yaml.

If the user cancels (or clicks Skip Setup), config.yaml is left unchanged.

Usage in main_app.py
--------------------
    from ui.first_run import should_show_first_run, FirstRunWizard

    if should_show_first_run(config_path):
        dlg = FirstRunWizard(config_path, parent=window)
        dlg.exec_()

    # Re-run from Settings menu (no sentinel check needed):
    dlg = FirstRunWizard(config_path, parent=window)
    dlg.exec_()
"""

from __future__ import annotations

import os
import sys
import glob
import logging

import yaml

from PyQt5.QtCore    import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QStackedWidget, QWidget, QFrame,
    QFileDialog, QGroupBox, QFormLayout,
    QSizePolicy, QMessageBox, QProgressBar,
)

from ui.theme import (
    btn_wizard_primary_qss, btn_wizard_secondary_qss, wizard_input_qss,
    FONT, PALETTE, scaled_qss,
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


# ── Background scan worker ────────────────────────────────────────────────────

class _ScanWorker(QThread):
    """
    Runs DeviceScanner.scan() in a background thread so the wizard UI stays
    responsive.

    Signals
    -------
    status_update(str)    — emitted periodically with a progress message
    completed(object)     — emitted once with a ScanReport (or None on failure)
    """

    status_update = pyqtSignal(str)
    completed     = pyqtSignal(object)   # ScanReport | None

    def run(self):
        try:
            from hardware.device_scanner import DeviceScanner
        except Exception as e:
            log.warning("_ScanWorker: cannot import DeviceScanner: %s", e)
            self.completed.emit(None)
            return

        def on_progress(msg: str):
            self.status_update.emit(msg)

        try:
            scanner = DeviceScanner()
            report  = scanner.scan(include_network=False,
                                   progress_cb=on_progress)
            self.completed.emit(report)
        except Exception as e:
            log.warning("_ScanWorker: scan raised: %s", e)
            self.completed.emit(None)


# ── Ollama background workers (wizard copies — no import from settings_tab) ───

class _WizOllamaInstallThread(QThread):
    """Downloads the Ollama Windows installer and launches it (wizard variant).

    Supports mid-download cancellation via requestInterruption(): the reporthook
    raises InterruptedError when the flag is set.  finished(False, "cancelled")
    is emitted so the wizard page can restore its idle state.
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def run(self) -> None:
        import os
        import tempfile
        import subprocess
        import urllib.request

        url      = "https://ollama.com/download/OllamaSetup.exe"
        tmp_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

        def _hook(block_num: int, block_size: int, total_size: int) -> None:
            if self.isInterruptionRequested():
                raise InterruptedError("download cancelled")
            if total_size > 0:
                pct   = min(int(block_num * block_size / total_size * 100), 99)
                mb    = block_num * block_size // 1_000_000
                total = total_size // 1_000_000
                self.progress.emit(pct, f"Downloading…  {pct}%  ({mb} / {total} MB)")

        try:
            self.progress.emit(0, "Connecting to ollama.com…")
            urllib.request.urlretrieve(url, tmp_path, _hook)
            self.progress.emit(100, "Launching installer…")
            subprocess.Popen([tmp_path], shell=False)
            self.finished.emit(
                True,
                "Installer launched.  Complete the setup window,\n"
                "then click  ⟳ Check status  to continue.")
        except InterruptedError:
            self.finished.emit(False, "cancelled")
        except Exception as exc:
            self.finished.emit(False, f"Download failed: {exc}")


class _WizOllamaPullThread(QThread):
    """Runs  ollama pull <model>  in a subprocess (wizard variant).

    Call cancel() to terminate the subprocess; finished(False, "cancelled")
    is then emitted so the wizard page can restore its idle state.
    """

    output_line = pyqtSignal(str)
    finished    = pyqtSignal(bool, str)

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self._model = model
        self._proc  = None   # set once the subprocess is running

    def cancel(self) -> None:
        """Terminate the ollama pull subprocess immediately."""
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        import subprocess
        from ai.remote_runner import ollama_exe_path

        exe = ollama_exe_path()
        if not exe:
            self.finished.emit(
                False,
                "ollama command not found — is the installation complete?")
            return
        try:
            self._proc = subprocess.Popen(
                [exe, "pull", self._model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for raw_line in self._proc.stdout:
                line = raw_line.rstrip()
                if line:
                    self.output_line.emit(line)
            self._proc.wait()
            if self._proc.returncode == 0:
                self.finished.emit(True,  f"✓  {self._model} downloaded and ready")
            elif self._proc.returncode in (-15, -9, 1) and \
                    self.isInterruptionRequested():
                self.finished.emit(False, "cancelled")
            else:
                self.finished.emit(
                    False, f"Pull failed (exit {self._proc.returncode})")
        except Exception as exc:
            self.finished.emit(False, str(exc))
        finally:
            self._proc = None


# ── Shared style helpers (sourced from ui.theme) ──────────────────────────────

_BTN_PRIMARY   = btn_wizard_primary_qss()
_BTN_SECONDARY = btn_wizard_secondary_qss()
_INPUT_SS      = wizard_input_qss()

_LABEL_H1   = scaled_qss("font-size:20pt; font-weight:700; color:#fff;")
_LABEL_BODY = f"font-size:{FONT['body']}pt; color:{PALETTE['textSub']};"
_LABEL_HINT = f"font-size:{FONT['caption']}pt; color:{PALETTE['textSub']}; font-style:italic;"

_SS_BADGE_OK   = f"font-size:{FONT['caption']}pt; color:{PALETTE['accent']};"
_SS_BADGE_WARN = f"font-size:{FONT['caption']}pt; color:{PALETTE['warning']};"


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{PALETTE.get('border','#484848')};")
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

    # ── PALETTE-driven colour properties (shared by all wizard pages) ──
    @property
    def _ACCENT(self): return PALETTE.get("cta",     "#0a84ff")
    @property
    def _GREEN(self):  return PALETTE.get("accent",  "#00d4aa")
    @property
    def _AMBER(self):  return PALETTE.get("warning", "#ff9f0a")
    @property
    def _DANGER(self): return PALETTE.get("danger",  "#ff453a")

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
            "  ②  Camera            — Basler TR camera or Microsanj IR camera\n"
            "  ③  FPGA              — NI 9637 via NI-RIO\n\n"
            "Your answers are saved to  config.yaml  and can be changed at any "
            "time from  Settings → Hardware Setup.")
        body.setStyleSheet(f"font-size:{FONT['body']}pt; color:{PALETTE.get('text','#ebebeb')}; line-height:1.6;")
        body.setWordWrap(True)
        self._content.addWidget(body)

        # ── SDK pre-requisites callout ─────────────────────────────────────────
        prereq = QLabel(
            "<b>Camera SDKs must be installed before your cameras will work.</b><br>"
            "These are OS-level drivers — install them before clicking Next:<br>"
            "<br>"
            "  🔷 &nbsp;<b>Basler TR camera</b> — install "
            '<a href="https://www.baslerweb.com/en-us/downloads/software/">Basler pylon 8</a>'
            " (includes the USB3 Vision driver + pypylon Python bindings)<br>"
            "  🔶 &nbsp;<b>Microsanj IR camera</b> — install "
            '<a href="https://www.flir.com/products/spinnaker-sdk/">FLIR Spinnaker SDK</a>'
            " (includes the PySpin Python wheel — see SDK download page)<br>"
            "<br>"
            "If neither camera is connected, leave the Camera driver set to  simulated.")
        prereq.setOpenExternalLinks(True)
        prereq.setWordWrap(True)
        _cta = PALETTE.get("cta", "#0a84ff")
        prereq.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('text','#ebebeb')}; "
            f"background:{_cta}18; border:1px solid {_cta}55; border-left:3px solid {_cta}; "
            "border-radius:4px; padding:10px;")
        self._content.addWidget(prereq)
        self._content.addStretch(1)

        tip = QLabel(
            "💡  If you are running on a development machine without hardware connected, "
            "leave all drivers set to  simulated  — the app will still open and operate "
            "with synthetic data.")
        tip.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('textDim','#999999')}; font-style:italic; "
            f"background:{PALETTE.get('bg','#242424')}; border:1px solid {PALETTE.get('border','#484848')}; border-radius:5px; "
            "padding:10px;")
        tip.setWordWrap(True)
        self._content.addWidget(tip)

        # Live scan-status line — updated by _ScanWorker signals
        self._scan_label = QLabel("Scanning for connected hardware…")
        self._scan_label.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('textSub','#6a6a6a')}; font-style:italic; padding:4px 0;")
        self._content.addWidget(self._scan_label)

    def set_scan_status(self, msg: str):
        """Called by _ScanWorker.status_update signal."""
        self._scan_label.setText(msg)

    def set_scan_done(self, known_count: int):
        """Called by _ScanWorker.completed signal after pages are updated."""
        if known_count > 0:
            self._scan_label.setText(
                f"✓  Scan complete — {known_count} known device(s) detected. "
                "Settings have been pre-filled on the following pages.")
            self._scan_label.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('accent','#00d4aa')}; padding:4px 0;")
        else:
            self._scan_label.setText(
                "⚠  Scan complete — no known devices found. "
                "Select drivers and ports manually, or check USB connections.")
            self._scan_label.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('warning','#ff9f0a')}; padding:4px 0;")


class _PortRow(QWidget):
    """
    A label + editable combo + refresh-button row for a single serial port,
    with an optional detection badge shown below after auto-scan.

    Replaces the previous QHBoxLayout subclass; QFormLayout.addRow(QWidget)
    behaves identically (widget spans both label and field columns).
    """

    def __init__(self, label: str, default_port: str):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{PALETTE.get('textSub','#6a6a6a')};")
        lbl.setFixedWidth(220)
        row.addWidget(lbl)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setStyleSheet(_INPUT_SS)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setFixedHeight(34)
        row.addWidget(self.combo, 1)

        refresh = QPushButton("⟳")
        refresh.setFixedSize(34, 34)
        refresh.setToolTip("Refresh port list")
        refresh.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:0"))
        refresh.clicked.connect(self._refresh)
        row.addWidget(refresh)

        test_btn = QPushButton("Test")
        test_btn.setFixedSize(50, 34)
        test_btn.setToolTip("Test that this serial port can be opened")
        test_btn.setStyleSheet(_BTN_SECONDARY.replace("padding:8px 22px", "padding:0"))
        test_btn.clicked.connect(self._test_connection)
        row.addWidget(test_btn)

        outer.addLayout(row)

        # Badge — hidden until set_detected / set_not_detected / test is called
        self._badge = QLabel("")
        self._badge.setStyleSheet(_SS_BADGE_OK + " padding-left:228px;")
        self._badge.setVisible(False)
        outer.addWidget(self._badge)

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

    def _test_connection(self):
        """Attempt to open the selected COM port and report accessibility."""
        port = self.combo.currentText().strip()
        if not port:
            self._badge.setText("⚠  No port selected")
            self._badge.setStyleSheet(_SS_BADGE_WARN + " padding-left:228px;")
            self._badge.setVisible(True)
            return
        try:
            import serial
            s = serial.Serial(port, timeout=0.5)
            s.close()
            self._badge.setText(f"✓  Port {port} opened OK")
            self._badge.setStyleSheet(_SS_BADGE_OK + " padding-left:228px;")
        except ImportError:
            self._badge.setText("⚠  pyserial not installed — pip install pyserial")
            self._badge.setStyleSheet(_SS_BADGE_WARN + " padding-left:228px;")
        except Exception as e:
            self._badge.setText(f"⊗  {port}: {str(e)[:60]}")
            self._badge.setStyleSheet(
                f"font-size:{FONT['caption']}pt; color:{PALETTE['danger']};"
                " padding-left:228px;")
        self._badge.setVisible(True)

    def set_detected(self, port: str, device_name: str):
        """Auto-select *port* and show a green ✓ badge."""
        self._set_value(port)
        self._badge.setText(f"✓  Detected: {device_name}")
        self._badge.setStyleSheet(_SS_BADGE_OK + " padding-left:228px;")
        self._badge.setVisible(True)

    def set_not_detected(self):
        """Show an amber ⚠ badge when auto-detection found nothing."""
        self._badge.setText("⚠  Not detected — select port manually")
        self._badge.setStyleSheet(_SS_BADGE_WARN + " padding-left:228px;")
        self._badge.setVisible(True)

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

        _grp_ss = (
            f"QGroupBox {{ color:{PALETTE.get('textSub','#6a6a6a')}; font-size:{FONT['label']}pt; border:1px solid {PALETTE.get('border','#484848')}; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")

        # ── Meerstetter ───────────────────────────────────────────────
        g1 = QGroupBox("Meerstetter TEC-1089")
        g1.setStyleSheet(_grp_ss)
        fl1 = QFormLayout(g1)
        fl1.setSpacing(8)

        self._meer_driver = QComboBox()
        self._meer_driver.addItems(["meerstetter", "simulated"])
        self._meer_driver.setCurrentText(meerstetter_cfg.get("driver", "simulated"))
        self._meer_driver.setStyleSheet(_INPUT_SS)
        self._meer_driver.currentTextChanged.connect(self._on_meer_driver_changed)
        fl1.addRow(_lbl("Driver:"), self._meer_driver)

        self._meer_port = _PortRow("COM Port:", meerstetter_cfg.get("port", "COM3"))
        fl1.addRow(self._meer_port)

        addr_lbl = QLabel(f"Address: {meerstetter_cfg.get('address', 2)}  "
                          f"Baud: {meerstetter_cfg.get('baudrate', 57600)}")
        addr_lbl.setStyleSheet(_LABEL_HINT)
        fl1.addRow(addr_lbl)

        # pyMeCom notice — shown when pyMeCom is not importable
        self._mecom_notice = QLabel(
            '⚠  pyMeCom library is not installed in this application.<br>'
            'pyMeCom provides the MeCom serial protocol used to communicate<br>'
            'with Meerstetter TEC and LDD controllers.<br>'
            '<a href="https://github.com/meerstetter/pyMeCom">'
            'github.com/meerstetter/pyMeCom ↗</a>'
            '&nbsp; — &nbsp;'
            '<a href="https://pypi.org/project/pyMeCom/">'
            'PyPI: pip install pyMeCom ↗</a>'
        )
        self._mecom_notice.setOpenExternalLinks(True)
        self._mecom_notice.setWordWrap(True)
        self._mecom_notice.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['warning']}; "
            f"background:{PALETTE.get('warning','#ff9f0a')}18; border:1px solid {PALETTE.get('warning','#ff9f0a')}44; border-radius:4px; "
            "padding:8px;")
        self._mecom_notice.setVisible(False)
        fl1.addRow(self._mecom_notice)

        # Test connection button + result label
        meer_test_row = QHBoxLayout()
        self._meer_test_btn = QPushButton("Test Connection")
        self._meer_test_btn.setFixedHeight(30)
        self._meer_test_btn.setToolTip(
            "Try to open the selected COM port with the Meerstetter MeCom protocol")
        self._meer_test_btn.setStyleSheet(
            _BTN_SECONDARY.replace("padding:8px 22px", "padding:0 12px"))
        self._meer_test_btn.clicked.connect(self._test_meer)
        self._meer_test_lbl = QLabel("")
        self._meer_test_lbl.setStyleSheet(_SS_BADGE_OK)
        meer_test_row.addWidget(self._meer_test_btn)
        meer_test_row.addSpacing(8)
        meer_test_row.addWidget(self._meer_test_lbl, 1)
        fl1.addRow(meer_test_row)

        self._content.addWidget(g1)

        # ── ATEC ──────────────────────────────────────────────────────
        g2 = QGroupBox("ATEC-302")
        g2.setStyleSheet(_grp_ss)
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

        # Show pyMeCom notice immediately if meerstetter driver is pre-selected
        self._on_meer_driver_changed(self._meer_driver.currentText())

    # ── pyMeCom helpers ───────────────────────────────────────────────

    def _on_meer_driver_changed(self, driver: str) -> None:
        if driver == "meerstetter":
            self._check_mecom_available()
        else:
            if hasattr(self, "_mecom_notice"):
                self._mecom_notice.setVisible(False)

    def _check_mecom_available(self) -> bool:
        """Return True if pyMeCom (import name: mecom) is importable."""
        try:
            import mecom  # noqa: F401
            if hasattr(self, "_mecom_notice"):
                self._mecom_notice.setVisible(False)
            return True
        except ImportError:
            if hasattr(self, "_mecom_notice"):
                self._mecom_notice.setVisible(True)
            return False

    def _test_meer(self) -> None:
        """Try to connect to the Meerstetter TEC on the selected COM port."""
        ok_ss   = _SS_BADGE_OK
        warn_ss = _SS_BADGE_WARN
        err_ss  = f"font-size:{FONT['caption']}pt; color:{PALETTE['danger']};"

        driver = self._meer_driver.currentText()
        if driver == "simulated":
            self._meer_test_lbl.setText("✓  Simulated — no hardware required")
            self._meer_test_lbl.setStyleSheet(ok_ss)
            return

        if not self._check_mecom_available():
            self._meer_test_lbl.setText(
                "⊗  pyMeCom not found — see download link above")
            self._meer_test_lbl.setStyleSheet(err_ss)
            return

        port = self._meer_port.value
        if not port:
            self._meer_test_lbl.setText("⚠  Select a COM port first")
            self._meer_test_lbl.setStyleSheet(warn_ss)
            return

        self._meer_test_lbl.setText("Connecting…")
        self._meer_test_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")

        try:
            from mecom import MeComAPI
            tec = MeComAPI(port)
            info = tec.identify()
            tec.session.close()
            self._meer_test_lbl.setText(
                f"✓  Connected: {info}" if info else f"✓  TEC responded on {port}")
            self._meer_test_lbl.setStyleSheet(ok_ss)
        except ImportError:
            self._meer_test_lbl.setText("⊗  pyMeCom not importable")
            self._meer_test_lbl.setStyleSheet(err_ss)
        except Exception as e:
            msg = str(e)[:80]
            self._meer_test_lbl.setText(f"⊗  {msg}")
            self._meer_test_lbl.setStyleSheet(err_ss)

    # ── Scan results ──────────────────────────────────────────────────

    def apply_scan(self, report) -> int:
        """
        Pre-fill TEC driver and COM port from scan results.
        Returns the number of TEC devices successfully detected.
        """
        try:
            from hardware.device_registry import DTYPE_TEC
            tec_devs = [d for d in report.devices
                        if d.is_known and d.descriptor.device_type == DTYPE_TEC]
        except Exception:
            tec_devs = []

        meer_found = atec_found = False
        for dev in tec_devs:
            uid = dev.descriptor.uid
            if uid.startswith("meerstetter") and not meer_found:
                self._meer_driver.setCurrentText("meerstetter")
                self._meer_port.set_detected(dev.address,
                                             dev.descriptor.display_name)
                meer_found = True
            elif uid.startswith("atec") and not atec_found:
                self._atec_driver.setCurrentText("atec")
                self._atec_port.set_detected(dev.address,
                                             dev.descriptor.display_name)
                atec_found = True

        if not meer_found:
            self._meer_port.set_not_detected()
        if not atec_found:
            self._atec_port.set_not_detected()

        return (1 if meer_found else 0) + (1 if atec_found else 0)

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
            "Choose the camera driver.  "
            "Use  pypylon  for the Basler TR camera, or  "
            "Microsanj IR Camera  for the Microsanj thermal imager.",
            parent)

        g = QGroupBox("Camera")
        g.setStyleSheet(
            f"QGroupBox {{ color:{PALETTE.get('textSub','#6a6a6a')}; font-size:{FONT['label']}pt; border:1px solid {PALETTE.get('border','#484848')}; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl = QFormLayout(g)
        fl.setSpacing(10)

        self._drv = QComboBox()
        for _display, _key in [
            ("pypylon",             "pypylon"),
            ("Microsanj IR Camera", "flir"),
            ("ni_imaqdx",           "ni_imaqdx"),
            ("directshow",          "directshow"),
            ("simulated",           "simulated"),
        ]:
            self._drv.addItem(_display, _key)
        self._set_driver_key(cam_cfg.get("driver", "simulated"))
        self._drv.setStyleSheet(_INPUT_SS)
        self._drv.currentIndexChanged.connect(
            lambda: self._update_hints(self._drv.currentData()))
        fl.addRow(_lbl("Driver:"), self._drv)

        self._cam_name = QLineEdit(cam_cfg.get("camera_name", "cam4"))
        self._cam_name.setStyleSheet(_INPUT_SS)
        self._cam_name.setFixedHeight(34)
        fl.addRow(_lbl("NI Camera Name:"), self._cam_name)

        self._serial = QLineEdit(cam_cfg.get("serial", ""))
        self._serial.setPlaceholderText("Leave blank for first found camera")
        self._serial.setStyleSheet(_INPUT_SS)
        self._serial.setFixedHeight(34)
        fl.addRow(_lbl("Camera Serial #:"), self._serial)

        self._hint = QLabel("")
        self._hint.setStyleSheet(_LABEL_HINT)
        self._hint.setWordWrap(True)
        self._hint.setOpenExternalLinks(True)
        fl.addRow(self._hint)

        # Pylon SDK install notice (shown only when pypylon driver selected
        # and the pylon runtime is not importable)
        self._pylon_notice = QLabel(
            '⚠  Basler pylon SDK is not installed on this machine.<br>'
            'The pylon SDK provides the USB3 Vision driver that Windows '
            'needs to see your camera.<br>'
            '<a href="https://www.baslerweb.com/en-us/downloads/software/'
            '2360853512/?downloadCategory.values.label.data=pylon">'
            'Download pylon 8 for Windows ↗</a>'
            '&nbsp;&nbsp;|&nbsp;&nbsp;'
            '<a href="https://www.baslerweb.com/en-us/software/pylon/pypylon/">'
            'About pypylon ↗</a>'
        )
        self._pylon_notice.setOpenExternalLinks(True)
        self._pylon_notice.setWordWrap(True)
        self._pylon_notice.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['warning']}; "
            f"background:{PALETTE.get('warning','#ff9f0a')}18; border:1px solid {PALETTE.get('warning','#ff9f0a')}44; border-radius:4px; "
            "padding:8px;")
        self._pylon_notice.setVisible(False)
        fl.addRow(self._pylon_notice)

        # FLIR Spinnaker SDK install notice (shown when flir driver is selected
        # and spinnaker_python / PySpin is not importable)
        self._flir_notice = QLabel(
            '⚠  Spinnaker SDK is not installed — required for the Microsanj IR Camera.<br>'
            'The Spinnaker SDK provides the USB3 driver Windows needs to see the camera.  '
            'Download and install it from FLIR, then install the matching Python wheel:<br>'
            '<a href="https://www.flir.com/products/spinnaker-sdk/">'
            'flir.com — Spinnaker SDK download ↗</a>'
            '&nbsp;&nbsp;|&nbsp;&nbsp;'
            '<code>pip install spinnaker_python</code>'
            '&nbsp;(wheel ships inside the SDK package)'
        )
        self._flir_notice.setOpenExternalLinks(True)
        self._flir_notice.setWordWrap(True)
        self._flir_notice.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['warning']}; "
            f"background:{PALETTE.get('warning','#ff9f0a')}18; border:1px solid {PALETTE.get('warning','#ff9f0a')}44; border-radius:4px; "
            "padding:8px;")
        self._flir_notice.setVisible(False)
        fl.addRow(self._flir_notice)

        # Detection badge — hidden until apply_scan() runs
        self._detection_label = QLabel("")
        self._detection_label.setStyleSheet(_SS_BADGE_OK)
        self._detection_label.setWordWrap(True)
        self._detection_label.setVisible(False)
        fl.addRow(self._detection_label)

        # Test Camera button + inline result label
        test_row = QHBoxLayout()
        self._cam_test_btn = QPushButton("Test Camera")
        self._cam_test_btn.setFixedHeight(30)
        self._cam_test_btn.setToolTip(
            "Attempt to enumerate cameras with the selected driver")
        self._cam_test_btn.setStyleSheet(
            _BTN_SECONDARY.replace("padding:8px 22px", "padding:0 12px"))
        self._cam_test_btn.clicked.connect(self._test_camera)
        self._cam_test_lbl = QLabel("")
        self._cam_test_lbl.setStyleSheet(_SS_BADGE_OK)
        test_row.addWidget(self._cam_test_btn)
        test_row.addSpacing(8)
        test_row.addWidget(self._cam_test_lbl, 1)
        fl.addRow(test_row)

        self._content.addWidget(g)
        self._content.addStretch(1)
        self._update_hints(self._drv.currentData())

    def _set_driver_key(self, key: str) -> None:
        """Select the combo item whose userData matches *key* (e.g. "flir")."""
        for i in range(self._drv.count()):
            if self._drv.itemData(i) == key:
                self._drv.setCurrentIndex(i)
                return

    def _update_hints(self, driver: str):
        hints = {
            "pypylon": (
                "Uses Basler pylon SDK + pypylon.  "
                "Supports USB3 Vision and GigE cameras.  "
                "Click  Test Camera  to check if the pylon SDK is installed."
            ),
            "flir": (
                "Microsanj IR Camera — uses the FLIR Spinnaker SDK (PySpin) internally.  "
                "Install the Spinnaker SDK from flir.com, then  pip install spinnaker_python.  "
                "Click  Test Camera  to verify the SDK is installed."
            ),
            "ni_imaqdx":  "Uses NI IMAQdx. Install NI Vision Acquisition Software; "
                          "camera name comes from NI MAX (auto-detected if connected).",
            "directshow": "Generic Windows DirectShow camera (development/fallback only).",
            "simulated":  "No real camera required. Generates synthetic frames.",
        }
        self._hint.setText(hints.get(driver, ""))

        # Auto-check SDK availability and show the appropriate notice
        if driver == "pypylon":
            self._check_pylon_available()
            if hasattr(self, "_flir_notice"):
                self._flir_notice.setVisible(False)
        elif driver == "flir":
            self._check_flir_available()
            if hasattr(self, "_pylon_notice"):
                self._pylon_notice.setVisible(False)
        else:
            if hasattr(self, "_pylon_notice"):
                self._pylon_notice.setVisible(False)
            if hasattr(self, "_flir_notice"):
                self._flir_notice.setVisible(False)

    def _check_pylon_available(self) -> bool:
        """Return True if pypylon is importable; show/hide the notice accordingly."""
        try:
            import pypylon.pylon  # noqa: F401
            if hasattr(self, "_pylon_notice"):
                self._pylon_notice.setVisible(False)
            return True
        except ImportError:
            if hasattr(self, "_pylon_notice"):
                self._pylon_notice.setVisible(True)
            return False

    def _check_flir_available(self) -> bool:
        """Return True if PySpin (spinnaker_python) is importable; show/hide notice."""
        try:
            import PySpin  # noqa: F401
            if hasattr(self, "_flir_notice"):
                self._flir_notice.setVisible(False)
            return True
        except ImportError:
            if hasattr(self, "_flir_notice"):
                self._flir_notice.setVisible(True)
            return False

    def _test_camera(self):
        """Quick enumeration test using the currently selected driver."""
        driver = self._drv.currentData() or self._drv.currentText()
        ok_ss   = _SS_BADGE_OK
        warn_ss = _SS_BADGE_WARN
        err_ss  = f"font-size:{FONT['caption']}pt; color:{PALETTE['danger']};"

        if driver == "simulated":
            self._cam_test_lbl.setText("✓  Simulated — no hardware required")
            self._cam_test_lbl.setStyleSheet(ok_ss)
            return

        if driver == "pypylon":
            try:
                from pypylon import pylon
                if hasattr(self, "_pylon_notice"):
                    self._pylon_notice.setVisible(False)
                tlf  = pylon.TlFactory.GetInstance()
                devs = tlf.EnumerateDevices()
                if devs:
                    names = ", ".join(
                        d.GetModelName() for d in devs[:3])
                    self._cam_test_lbl.setText(
                        f"✓  {len(devs)} Basler camera(s): {names}")
                    self._cam_test_lbl.setStyleSheet(ok_ss)
                else:
                    self._cam_test_lbl.setText(
                        "⚠  pylon SDK found but no cameras detected — "
                        "check USB cable / power")
                    self._cam_test_lbl.setStyleSheet(warn_ss)
            except ImportError:
                # pylon SDK not installed — show the notice with download link
                if hasattr(self, "_pylon_notice"):
                    self._pylon_notice.setVisible(True)
                self._cam_test_lbl.setText(
                    "⊗  Basler pylon SDK not found — see download link above")
                self._cam_test_lbl.setStyleSheet(err_ss)
            except Exception as e:
                self._cam_test_lbl.setText(f"⊗  {str(e)[:80]}")
                self._cam_test_lbl.setStyleSheet(err_ss)
            return

        if driver == "flir":
            try:
                import PySpin
                if hasattr(self, "_flir_notice"):
                    self._flir_notice.setVisible(False)
                system = PySpin.System.GetInstance()
                cam_list = system.GetCameras()
                count = cam_list.GetSize()
                cam_list.Clear()
                system.ReleaseInstance()
                if count > 0:
                    self._cam_test_lbl.setText(
                        f"✓  SDK ready — {count} Microsanj IR camera(s) detected")
                    self._cam_test_lbl.setStyleSheet(ok_ss)
                else:
                    self._cam_test_lbl.setText(
                        "⚠  Spinnaker SDK installed but no camera detected — "
                        "check USB cable / power")
                    self._cam_test_lbl.setStyleSheet(warn_ss)
            except ImportError:
                if hasattr(self, "_flir_notice"):
                    self._flir_notice.setVisible(True)
                self._cam_test_lbl.setText(
                    "⊗  Spinnaker SDK not found — see install instructions above")
                self._cam_test_lbl.setStyleSheet(err_ss)
            except Exception as e:
                self._cam_test_lbl.setText(f"⊗  {str(e)[:80]}")
                self._cam_test_lbl.setStyleSheet(err_ss)
            return

        self._cam_test_lbl.setText(
            f"ℹ  Automated test not available for '{driver}' driver")
        self._cam_test_lbl.setStyleSheet(
            f"font-size:{FONT['caption']}pt; color:{PALETTE['textDim']};")

    def apply_scan(self, report) -> int:
        """
        Pre-fill camera driver / serial # / NI camera name from scan results.
        Returns 1 if a camera was detected, 0 otherwise.
        """
        try:
            from hardware.device_registry import DTYPE_CAMERA, CONN_CAMERA
        except ImportError:
            try:
                from hardware.device_registry import DTYPE_CAMERA
                CONN_CAMERA = "camera"
            except Exception:
                return 0

        # Prefer SDK-enumerated devices (CONN_CAMERA) — they carry richer info
        cam_devs = [d for d in report.devices
                    if d.connection_type == CONN_CAMERA]
        if not cam_devs:
            # Fall back to USB-matched camera devices (e.g. from UsbScanner)
            cam_devs = [d for d in report.devices
                        if d.is_known
                        and d.descriptor.device_type == DTYPE_CAMERA]

        if not cam_devs:
            self._detection_label.setText(
                "⚠  No camera detected — check USB/GigE connection and SDK installation.\n"
                "    Basler TR: install pylon 8 from baslerweb.com, then: pip install pypylon\n"
                "    Microsanj IR: install Spinnaker SDK from flir.com, then: pip install spinnaker_python")
            self._detection_label.setStyleSheet(_SS_BADGE_WARN)
            self._detection_label.setVisible(True)
            return 0

        # Use first detected camera to pre-fill the form.
        # If more than one camera is found, list all of them in the badge
        # so the user knows which serial number to enter for which slot.
        cam    = cam_devs[0]
        module = cam.descriptor.driver_module if cam.descriptor else ""

        if "pypylon" in module or (
                not module and "basler" in cam.description.lower()):
            self._set_driver_key("pypylon")
            if cam.serial_number:
                self._serial.setText(cam.serial_number)
            label = (cam.descriptor.display_name
                     if cam.descriptor else cam.description)
            if cam.serial_number:
                label += f"  (s/n {cam.serial_number})"

        elif "flir" in module or "spinnaker" in cam.description.lower():
            self._set_driver_key("flir")
            if cam.serial_number:
                self._serial.setText(cam.serial_number)
            label = "Microsanj IR Camera"
            if cam.serial_number:
                label += f"  (s/n {cam.serial_number})"

        elif "ni_imaqdx" in module or "imaqdx" in cam.description.lower():
            self._set_driver_key("ni_imaqdx")
            # For NI IMAQdx, the address field holds the NI MAX camera name
            if cam.address:
                self._cam_name.setText(cam.address)
            label = cam.description

        else:
            label = cam.description or cam.address

        # If multiple cameras found, append a summary of the others
        if len(cam_devs) > 1:
            others = []
            for extra in cam_devs[1:]:
                extra_label = extra.description
                if extra.serial_number:
                    extra_label += f" (s/n {extra.serial_number})"
                others.append(extra_label)
            label += f"\n    Also found: {', '.join(others)}"

        self._detection_label.setText(f"✓  Detected: {label}")
        self._detection_label.setStyleSheet(_SS_BADGE_OK)
        self._detection_label.setVisible(True)
        self._update_hints(self._drv.currentData())
        return len(cam_devs)

    def values(self) -> dict:
        return {
            "camera.driver":      self._drv.currentData() or self._drv.currentText(),
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
            f"QGroupBox {{ color:{PALETTE.get('textSub','#6a6a6a')}; font-size:{FONT['label']}pt; border:1px solid {PALETTE.get('border','#484848')}; "
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

        # Detection badge — hidden until apply_scan() runs
        self._detection_label = QLabel("")
        self._detection_label.setStyleSheet(_SS_BADGE_OK)
        self._detection_label.setWordWrap(True)
        self._detection_label.setVisible(False)
        fl.addRow(self._detection_label)

        self._content.addWidget(g)
        self._content.addStretch(1)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FPGA Bitfile", "",
            "FPGA Bitfiles (*.lvbitx);;All Files (*)")
        if path:
            self._bitfile.setText(path)

    def apply_scan(self, report) -> int:
        """
        Pre-fill FPGA driver and resource string from scan results.
        Returns 1 if an FPGA was detected, 0 otherwise.
        """
        try:
            from hardware.device_registry import DTYPE_FPGA
            fpga_devs = [d for d in report.devices
                         if d.is_known and d.descriptor.device_type == DTYPE_FPGA]
        except Exception:
            fpga_devs = []

        if not fpga_devs:
            self._detection_label.setText(
                "⚠  NI FPGA not detected — check NI-RIO drivers and cRIO connection")
            self._detection_label.setStyleSheet(_SS_BADGE_WARN)
            self._detection_label.setVisible(True)
            return 0

        fpga = fpga_devs[0]
        self._drv.setCurrentText("ni9637")
        self._resource.setText(fpga.address)
        self._detection_label.setText(
            f"✓  Detected: {fpga.descriptor.display_name}  ({fpga.address})")
        self._detection_label.setStyleSheet(_SS_BADGE_OK)
        self._detection_label.setVisible(True)
        return 1

    def values(self) -> dict:
        return {
            "fpga.driver":   self._drv.currentText(),
            "fpga.bitfile":  self._bitfile.text().strip(),
            "fpga.resource": self._resource.text().strip(),
        }


class _PageBias(_PageBase):
    """
    Wizard page 5 — Bias source / SMU setup.

    Supports three driver back-ends:
      • keithley    — Keithley 2400/2450/2600 series via pyvisa (GPIB/USB/LAN)
      • visa_generic — any SCPI instrument via pyvisa (Rigol DP8xx, etc.)
      • rigol_dp832  — Rigol DP832 native LAN driver (no NI-VISA required)
      • simulated   — software-only for testing without hardware

    Detects whether pyvisa / pydp832 are installed and shows a notice with
    install links when the selected driver's dependency is missing.
    """

    _MUTED  = PALETTE.get('textSub','#6a6a6a')

    def __init__(self, cfg: dict, parent=None):
        bias_cfg = cfg.get("bias", {})
        super().__init__(
            "Bias Source / SMU",
            "Select the bias source or source-measure unit (SMU) connected to your "
            "device under test.  Leave  simulated  if you don't have one yet.",
            parent)

        # ── GroupBox ──────────────────────────────────────────────────────────
        g = QGroupBox("Bias Source Configuration")
        g.setStyleSheet(
            f"QGroupBox {{ color:{PALETTE.get('textSub','#6a6a6a')}; font-size:{FONT['label']}pt; border:1px solid {PALETTE.get('border','#484848')}; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl = QFormLayout(g)
        fl.setSpacing(10)

        # Driver selector
        self._drv = QComboBox()
        self._drv.addItems(["simulated", "keithley", "visa_generic", "rigol_dp832"])
        self._drv.setCurrentText(bias_cfg.get("driver", "simulated"))
        self._drv.setStyleSheet(_INPUT_SS)
        self._drv.currentTextChanged.connect(self._on_driver_changed)
        fl.addRow(_lbl("Driver:"), self._drv)

        # VISA address (keithley + visa_generic)
        self._addr = QLineEdit(bias_cfg.get("address", ""))
        self._addr.setPlaceholderText(
            "GPIB0::24::INSTR  or  TCPIP::192.168.1.5::INSTR  or  USB0::0x05E6::...")
        self._addr.setStyleSheet(_INPUT_SS)
        self._addr.setFixedHeight(34)
        self._addr_row_lbl = _lbl("VISA address:")
        fl.addRow(self._addr_row_lbl, self._addr)

        # Keithley model dropdown
        self._model_lbl = _lbl("Model:")
        self._model = QComboBox()
        self._model.addItems(["2400", "2410", "2420", "2450",
                               "2601", "2602", "2611", "2612", "2635", "2636"])
        self._model.setCurrentText(str(bias_cfg.get("model", "2400")))
        self._model.setStyleSheet(_INPUT_SS)
        fl.addRow(self._model_lbl, self._model)

        # Rigol DP832 host (rigol_dp832 driver)
        self._host_lbl = _lbl("Host / IP:")
        self._host = QLineEdit(bias_cfg.get("host", "192.168.1.20"))
        self._host.setPlaceholderText("192.168.1.20")
        self._host.setStyleSheet(_INPUT_SS)
        self._host.setFixedHeight(34)
        fl.addRow(self._host_lbl, self._host)

        # Channel (visa_generic + rigol_dp832)
        self._ch_lbl = _lbl("Channel:")
        self._channel = QComboBox()
        self._channel.addItems(["1", "2", "3"])
        ch_str = str(bias_cfg.get("channel", 1))
        self._channel.setCurrentText(ch_str if ch_str in ("1","2","3") else "1")
        self._channel.setStyleSheet(_INPUT_SS)
        fl.addRow(self._ch_lbl, self._channel)

        # ── Test connection ───────────────────────────────────────────────
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setStyleSheet(_BTN_SECONDARY)
        self._test_btn.setFixedHeight(30)
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)
        test_row.addStretch(1)
        fl.addRow(test_row)

        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setStyleSheet(_SS_BADGE_OK)
        self._test_result.setVisible(False)
        fl.addRow(self._test_result)

        self._content.addWidget(g)

        # ── pyvisa notice (shown when pyvisa is missing) ──────────────────
        self._visa_notice = QLabel(
            f'⚠  <b>pyvisa is not installed</b> — required for Keithley and VISA Generic drivers.<br>'
            f'Install: &nbsp;<code>pip install pyvisa pyvisa-py</code><br>'
            f'Or NI-VISA: <a href="https://www.ni.com/en/support/downloads/drivers/'
            f'download.ni-visa.html" style="color:{self._ACCENT};">ni.com/en/support/downloads ↗</a>'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'Also see: <a href="https://github.com/sgoadhouse/dcps" '
            f'style="color:{self._ACCENT};">dcps (Keithley wrapper) ↗</a>'
        )
        self._visa_notice.setOpenExternalLinks(True)
        self._visa_notice.setWordWrap(True)
        self._visa_notice.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{self._AMBER}; background:{PALETTE.get('bg','#242424')}; "
            f"border:1px solid {self._AMBER}44; border-radius:4px; padding:8px;")
        self._visa_notice.setVisible(False)
        self._content.addWidget(self._visa_notice)

        # ── pydp832 notice (shown when pydp832 is missing) ────────────────
        self._dp832_notice = QLabel(
            f'⚠  <b>pydp832 is not installed</b> — required for the Rigol DP832 native driver.<br>'
            f'Install: &nbsp;<code>pip install pydp832</code><br>'
            f'<a href="https://github.com/tspspi/pydp832" '
            f'style="color:{self._ACCENT};">github.com/tspspi/pydp832 ↗</a>'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'Or use <b>visa_generic</b> driver with pyvisa instead.'
        )
        self._dp832_notice.setOpenExternalLinks(True)
        self._dp832_notice.setWordWrap(True)
        self._dp832_notice.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{self._AMBER}; background:{PALETTE.get('bg','#242424')}; "
            f"border:1px solid {self._AMBER}44; border-radius:4px; padding:8px;")
        self._dp832_notice.setVisible(False)
        self._content.addWidget(self._dp832_notice)

        self._content.addStretch(1)

        # Apply initial visibility
        self._on_driver_changed(self._drv.currentText())

    # ── Driver change handler ──────────────────────────────────────────────────

    def _on_driver_changed(self, drv: str) -> None:
        is_keithley    = (drv == "keithley")
        is_visa        = (drv in ("keithley", "visa_generic"))
        is_rigol       = (drv == "rigol_dp832")
        is_multichan   = (drv in ("visa_generic", "rigol_dp832"))

        self._addr_row_lbl.setVisible(is_visa)
        self._addr.setVisible(is_visa)
        self._model_lbl.setVisible(is_keithley)
        self._model.setVisible(is_keithley)
        self._host_lbl.setVisible(is_rigol)
        self._host.setVisible(is_rigol)
        self._ch_lbl.setVisible(is_multichan)
        self._channel.setVisible(is_multichan)

        # Library availability notices
        if is_visa:
            self._visa_notice.setVisible(not self._check_pyvisa())
        else:
            self._visa_notice.setVisible(False)

        if is_rigol:
            self._dp832_notice.setVisible(not self._check_pydp832())
        else:
            self._dp832_notice.setVisible(False)

        self._test_result.setVisible(False)

    @staticmethod
    def _check_pyvisa() -> bool:
        try:
            import pyvisa  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_pydp832() -> bool:
        for mod in ("pydp832", "dp832"):
            try:
                __import__(mod)
                return True
            except ImportError:
                pass
        return False

    # ── Test connection ────────────────────────────────────────────────────────

    def _test_connection(self) -> None:
        drv = self._drv.currentText()
        try:
            if drv == "simulated":
                self._test_result.setText("✓  Simulated driver ready")
                self._test_result.setStyleSheet(
                    f"font-size:{FONT['sublabel']}pt; color:{self._GREEN};")
                self._test_result.setVisible(True)
                return

            cfg = self._build_cfg()
            from hardware.bias.factory import create_bias
            bias = create_bias(cfg)
            bias.connect()
            st = bias.get_status()
            bias.disconnect()
            self._test_result.setText(
                f"✓  Connected  — V = {st.actual_voltage:.3f} V, "
                f"I = {st.actual_current:.4f} A")
            self._test_result.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._GREEN};")
        except Exception as exc:
            self._test_result.setText(f"✗  {exc}")
            self._test_result.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._DANGER};")
        self._test_result.setVisible(True)

    def _build_cfg(self) -> dict:
        drv = self._drv.currentText()
        cfg: dict = {"driver": drv}
        if drv in ("keithley", "visa_generic"):
            cfg["address"] = self._addr.text().strip()
        if drv == "keithley":
            cfg["model"] = self._model.currentText()
        if drv == "rigol_dp832":
            cfg["host"] = self._host.text().strip()
        if drv in ("visa_generic", "rigol_dp832"):
            cfg["channel"] = int(self._channel.currentText())
        return cfg

    def apply_scan(self, report) -> int:
        """Pre-fill bias driver from scan results.  Returns 1 if found."""
        try:
            from hardware.device_registry import DTYPE_BIAS
            bias_devs = [d for d in report.devices
                         if d.is_known and d.descriptor.device_type == DTYPE_BIAS]
        except Exception:
            bias_devs = []

        if not bias_devs:
            return 0

        dev = bias_devs[0]
        drv = getattr(dev.descriptor, "driver_module", "").rsplit(".", 1)[-1]
        if "keithley" in drv:
            self._drv.setCurrentText("keithley")
            self._addr.setText(dev.address)
        elif "rigol" in (dev.descriptor.uid or ""):
            self._drv.setCurrentText("rigol_dp832")
            # For Ethernet Rigol, address is an IP
            self._host.setText(dev.address)
        elif "visa" in drv:
            self._drv.setCurrentText("visa_generic")
            self._addr.setText(dev.address)
        return 1

    def values(self) -> dict:
        drv = self._drv.currentText()
        out: dict = {"bias.driver": drv}
        if drv in ("keithley", "visa_generic"):
            out["bias.address"] = self._addr.text().strip()
        if drv == "keithley":
            out["bias.model"] = self._model.currentText()
        if drv == "rigol_dp832":
            out["bias.host"] = self._host.text().strip()
        if drv in ("visa_generic", "rigol_dp832"):
            out["bias.channel"] = int(self._channel.currentText())
        return out


class _PageStage(_PageBase):
    """
    Wizard page 6 — Motorised stage setup.

    Supports:
      • thorlabs    — Thorlabs BBD302 / KST101 / KDC101 / TDC001 via
                      thorlabs-apt-device + Thorlabs Kinesis software
      • serial_stage — generic serial-port stage controller
      • simulated   — software-only for testing without hardware
    """

    _MUTED  = PALETTE.get('textSub','#6a6a6a')

    def __init__(self, cfg: dict, parent=None):
        stage_cfg = cfg.get("stage", {})
        super().__init__(
            "Motorised Stage",
            "Configure the XYZ stage used for scanning.  "
            "Leave  simulated  if your system does not have a stage.",
            parent)

        # ── GroupBox ──────────────────────────────────────────────────────────
        g = QGroupBox("Stage Configuration")
        g.setStyleSheet(
            f"QGroupBox {{ color:{PALETTE.get('textSub','#6a6a6a')}; font-size:{FONT['label']}pt; border:1px solid {PALETTE.get('border','#484848')}; "
            "border-radius:5px; margin-top:8px; padding:12px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        fl = QFormLayout(g)
        fl.setSpacing(10)

        # Driver selector
        self._drv = QComboBox()
        self._drv.addItems(["simulated", "thorlabs", "serial_stage"])
        self._drv.setCurrentText(stage_cfg.get("driver", "simulated"))
        self._drv.setStyleSheet(_INPUT_SS)
        self._drv.currentTextChanged.connect(self._on_driver_changed)
        fl.addRow(_lbl("Driver:"), self._drv)

        # Thorlabs serial numbers (X / Y / Z axes)
        self._sn_x_lbl = _lbl("Serial X:")
        self._sn_x = QLineEdit(stage_cfg.get("serial_x", ""))
        self._sn_x.setPlaceholderText("e.g. 27000001")
        self._sn_x.setStyleSheet(_INPUT_SS)
        self._sn_x.setFixedHeight(34)
        fl.addRow(self._sn_x_lbl, self._sn_x)

        self._sn_y_lbl = _lbl("Serial Y:")
        self._sn_y = QLineEdit(stage_cfg.get("serial_y", ""))
        self._sn_y.setPlaceholderText("leave blank if Y axis not present")
        self._sn_y.setStyleSheet(_INPUT_SS)
        self._sn_y.setFixedHeight(34)
        fl.addRow(self._sn_y_lbl, self._sn_y)

        self._sn_z_lbl = _lbl("Serial Z:")
        self._sn_z = QLineEdit(stage_cfg.get("serial_z", ""))
        self._sn_z.setPlaceholderText("leave blank if Z axis not present")
        self._sn_z.setStyleSheet(_INPUT_SS)
        self._sn_z.setFixedHeight(34)
        fl.addRow(self._sn_z_lbl, self._sn_z)

        # Serial stage — port + baud
        self._port_lbl = _lbl("Serial port:")
        self._port = QComboBox()
        self._port.setEditable(True)
        for p in _list_serial_ports():
            self._port.addItem(p)
        self._port.setCurrentText(stage_cfg.get("port", ""))
        self._port.setStyleSheet(_INPUT_SS)
        fl.addRow(self._port_lbl, self._port)

        self._baud_lbl = _lbl("Baud rate:")
        self._baud = QComboBox()
        self._baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self._baud.setCurrentText(str(stage_cfg.get("baud", 115200)))
        self._baud.setStyleSheet(_INPUT_SS)
        fl.addRow(self._baud_lbl, self._baud)

        # ── Test connection ───────────────────────────────────────────────
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setStyleSheet(_BTN_SECONDARY)
        self._test_btn.setFixedHeight(30)
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)
        test_row.addStretch(1)
        fl.addRow(test_row)

        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setStyleSheet(_SS_BADGE_OK)
        self._test_result.setVisible(False)
        fl.addRow(self._test_result)

        self._content.addWidget(g)

        # ── thorlabs_apt_device notice ────────────────────────────────────
        self._apt_notice = QLabel(
            f'⚠  <b>thorlabs-apt-device is not installed</b> — required for Thorlabs stages.<br>'
            f'Install: &nbsp;<code>pip install thorlabs-apt-device</code><br>'
            f'Also install <b>Thorlabs Kinesis</b> software (provides USB drivers):<br>'
            f'<a href="https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control" '
            f'style="color:{self._ACCENT};">thorlabs.com — Kinesis download ↗</a>'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'<a href="https://github.com/kzhao1228/pystage_apt" '
            f'style="color:{self._ACCENT};">pystage_apt alternative ↗</a>'
        )
        self._apt_notice.setOpenExternalLinks(True)
        self._apt_notice.setWordWrap(True)
        self._apt_notice.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:{self._AMBER}; background:{PALETTE.get('bg','#242424')}; "
            f"border:1px solid {self._AMBER}44; border-radius:4px; padding:8px;")
        self._apt_notice.setVisible(False)
        self._content.addWidget(self._apt_notice)

        self._content.addStretch(1)

        # Apply initial visibility
        self._on_driver_changed(self._drv.currentText())

    # ── Driver change handler ──────────────────────────────────────────────────

    def _on_driver_changed(self, drv: str) -> None:
        is_thorlabs = (drv == "thorlabs")
        is_serial   = (drv == "serial_stage")

        self._sn_x_lbl.setVisible(is_thorlabs)
        self._sn_x.setVisible(is_thorlabs)
        self._sn_y_lbl.setVisible(is_thorlabs)
        self._sn_y.setVisible(is_thorlabs)
        self._sn_z_lbl.setVisible(is_thorlabs)
        self._sn_z.setVisible(is_thorlabs)
        self._port_lbl.setVisible(is_serial)
        self._port.setVisible(is_serial)
        self._baud_lbl.setVisible(is_serial)
        self._baud.setVisible(is_serial)

        if is_thorlabs:
            self._apt_notice.setVisible(not self._check_apt())
        else:
            self._apt_notice.setVisible(False)

        self._test_result.setVisible(False)

    @staticmethod
    def _check_apt() -> bool:
        try:
            import thorlabs_apt_device  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Test connection ────────────────────────────────────────────────────────

    def _test_connection(self) -> None:
        drv = self._drv.currentText()
        try:
            if drv == "simulated":
                self._test_result.setText("✓  Simulated driver ready")
                self._test_result.setStyleSheet(
                    f"font-size:{FONT['sublabel']}pt; color:{self._GREEN};")
                self._test_result.setVisible(True)
                return

            cfg = self._build_cfg()
            from hardware.stage.factory import create_stage
            stage = create_stage(cfg)
            stage.connect()
            pos = stage.get_position()
            stage.disconnect()
            self._test_result.setText(
                f"✓  Connected — position X={pos.x:.3f} Y={pos.y:.3f} Z={pos.z:.3f} mm")
            self._test_result.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._GREEN};")
        except Exception as exc:
            self._test_result.setText(f"✗  {exc}")
            self._test_result.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._DANGER};")
        self._test_result.setVisible(True)

    def _build_cfg(self) -> dict:
        drv = self._drv.currentText()
        cfg: dict = {"driver": drv}
        if drv == "thorlabs":
            cfg["serial_x"] = self._sn_x.text().strip()
            cfg["serial_y"] = self._sn_y.text().strip()
            cfg["serial_z"] = self._sn_z.text().strip()
        elif drv == "serial_stage":
            cfg["port"] = self._port.currentText().strip()
            cfg["baud"] = int(self._baud.currentText())
        return cfg

    def apply_scan(self, report) -> int:
        """Pre-fill stage driver from scan results.  Returns 1 if found."""
        try:
            from hardware.device_registry import DTYPE_STAGE
            stage_devs = [d for d in report.devices
                          if d.is_known and d.descriptor.device_type == DTYPE_STAGE]
        except Exception:
            stage_devs = []

        if not stage_devs:
            return 0

        dev = stage_devs[0]
        drv = getattr(dev.descriptor, "driver_module", "").rsplit(".", 1)[-1]
        if "thorlabs" in drv:
            self._drv.setCurrentText("thorlabs")
            # Serial numbers are embedded in descriptor extras when scanned
            extras = getattr(dev.descriptor, "extras", {})
            if extras.get("serial_x"):
                self._sn_x.setText(str(extras["serial_x"]))
        elif "serial" in drv:
            self._drv.setCurrentText("serial_stage")
            self._port.setCurrentText(dev.address)
        return 1

    def values(self) -> dict:
        drv = self._drv.currentText()
        out: dict = {"stage.driver": drv}
        if drv == "thorlabs":
            out["stage.serial_x"] = self._sn_x.text().strip()
            out["stage.serial_y"] = self._sn_y.text().strip()
            out["stage.serial_z"] = self._sn_z.text().strip()
        elif drv == "serial_stage":
            out["stage.port"] = self._port.currentText().strip()
            out["stage.baud"] = int(self._baud.currentText())
        return out


class _PageAI(_PageBase):
    """
    Wizard page 7 — AI Assistant setup.

    Detects whether Ollama is installed and, if so, whether any models have
    been pulled.  Guides the user through each step with one-click buttons so
    the user doesn't need to open a terminal.

    The page is entirely optional — clicking  Next →  skips any uncompleted
    steps without breaking anything.
    """

    _MUTED  = PALETTE.get('textSub','#6a6a6a')

    def __init__(self, parent=None):
        super().__init__(
            "AI Assistant (optional)",
            "SanjINSIGHT includes a built-in AI assistant that can help you interpret "
            "measurements, explain errors, and draft reports — all running locally on "
            "your PC.  This step sets up Ollama, the free local AI server it uses.",
            parent)

        # ── Status badge ──────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"font-size:{FONT['label']}pt;")
        self._content.addWidget(self._status_lbl)

        # ── Install section ───────────────────────────────────────────────
        self._install_frame = QFrame()
        self._install_frame.setStyleSheet(
            f"background:{PALETTE.get('bg','#242424')}; border:1px solid {self._AMBER}44; border-radius:6px;")
        if_lay = QVBoxLayout(self._install_frame)
        if_lay.setContentsMargins(14, 12, 14, 12)
        if_lay.setSpacing(8)

        _step1_lbl = QLabel("Step 1 — Install Ollama (free, takes about 1 minute):")
        _step1_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; font-weight:600; color:#fff;")
        if_lay.addWidget(_step1_lbl)

        btn_row = QHBoxLayout()
        self._install_btn = QPushButton("⬇  Install Ollama for me")
        self._install_btn.setStyleSheet(_BTN_PRIMARY)
        self._install_btn.setFixedWidth(230)
        self._install_btn.clicked.connect(self._on_install_clicked)
        btn_row.addWidget(self._install_btn)
        btn_row.addSpacing(12)

        manual = QLabel(
            f'or &nbsp;<a href="https://ollama.com/download" '
            f'style="color:{self._ACCENT};">download manually ↗</a>')
        manual.setOpenExternalLinks(True)
        manual.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
        btn_row.addWidget(manual)
        btn_row.addStretch(1)
        if_lay.addLayout(btn_row)

        self._install_prog = QProgressBar()
        self._install_prog.setRange(0, 100)
        self._install_prog.setFixedHeight(16)
        self._install_prog.setVisible(False)
        if_lay.addWidget(self._install_prog)

        self._install_cancel_btn = QPushButton("✕  Cancel Download")
        self._install_cancel_btn.setStyleSheet(_BTN_SECONDARY)
        self._install_cancel_btn.setFixedWidth(180)
        self._install_cancel_btn.setVisible(False)
        self._install_cancel_btn.clicked.connect(self._on_install_cancel_clicked)
        if_lay.addWidget(self._install_cancel_btn)

        self._install_msg = QLabel("")
        self._install_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
        self._install_msg.setWordWrap(True)
        self._install_msg.setVisible(False)
        if_lay.addWidget(self._install_msg)

        self._content.addWidget(self._install_frame)

        # ── Pull section ──────────────────────────────────────────────────
        self._pull_frame = QFrame()
        self._pull_frame.setStyleSheet(
            f"background:{PALETTE.get('bg','#242424')}; border:1px solid {PALETTE.get('accent','#00d4aa')}44; border-radius:6px;")
        pf_lay = QVBoxLayout(self._pull_frame)
        pf_lay.setContentsMargins(14, 12, 14, 12)
        pf_lay.setSpacing(8)

        step2_hdr = QLabel("Step 2 — Download a model (2 – 4 GB):")
        step2_hdr.setStyleSheet(f"font-size:{FONT['label']}pt; font-weight:600; color:#fff;")
        pf_lay.addWidget(step2_hdr)

        pull_hint = QLabel(
            "Phi-3 Mini is recommended for first-time users "
            "(2.3 GB, good on 4 GB GPU, fast responses).")
        pull_hint.setWordWrap(True)
        pull_hint.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
        pf_lay.addWidget(pull_hint)

        pull_row = QHBoxLayout()
        pull_lbl = QLabel("Model:")
        pull_lbl.setStyleSheet(f"font-size:{FONT['label']}pt; color:{self._MUTED};")
        pull_lbl.setFixedWidth(55)
        pull_row.addWidget(pull_lbl)

        self._pull_combo = QComboBox()
        for m in ["phi3", "phi3:mini", "mistral", "llama3:8b", "gemma2:2b"]:
            self._pull_combo.addItem(m)
        self._pull_combo.setCurrentText("phi3")
        pull_row.addWidget(self._pull_combo, 1)

        self._pull_btn = QPushButton("⬇  Pull Model")
        self._pull_btn.setStyleSheet(_BTN_PRIMARY)
        self._pull_btn.setFixedWidth(140)
        self._pull_btn.clicked.connect(self._on_pull_clicked)
        pull_row.addWidget(self._pull_btn)

        self._pull_cancel_btn = QPushButton("✕  Cancel")
        self._pull_cancel_btn.setStyleSheet(_BTN_SECONDARY)
        self._pull_cancel_btn.setFixedWidth(100)
        self._pull_cancel_btn.setVisible(False)
        self._pull_cancel_btn.clicked.connect(self._on_pull_cancel_clicked)
        pull_row.addWidget(self._pull_cancel_btn)
        pf_lay.addLayout(pull_row)

        self._pull_prog = QProgressBar()
        self._pull_prog.setRange(0, 0)          # indeterminate
        self._pull_prog.setFixedHeight(16)
        self._pull_prog.setVisible(False)
        pf_lay.addWidget(self._pull_prog)

        self._pull_msg = QLabel("")
        self._pull_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
        self._pull_msg.setWordWrap(True)
        self._pull_msg.setVisible(False)
        pf_lay.addWidget(self._pull_msg)

        self._content.addWidget(self._pull_frame)

        self._check_btn = QPushButton("⟳  Check status")
        self._check_btn.setStyleSheet(_BTN_SECONDARY)
        self._check_btn.setFixedWidth(150)
        self._check_btn.clicked.connect(self._detect)
        self._content.addWidget(self._check_btn)

        self._content.addStretch(1)

        # ── Initial detection ─────────────────────────────────────────────
        self._detect()

    # ── Detection ─────────────────────────────────────────────────────────────

    def _detect(self) -> None:
        """Check Ollama state and show appropriate sections."""
        from ai.remote_runner import is_ollama_installed, is_ollama_running, get_ollama_models

        installed = is_ollama_installed()
        self._install_frame.setVisible(not installed)

        if not installed:
            self._pull_frame.setVisible(False)
            self._status_lbl.setText(
                "⚠  Ollama is not installed yet.  "
                "Use  Step 1  below, or skip this page for now.")
            self._status_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{self._AMBER};")
            return

        running = is_ollama_running(timeout=1.5)
        if not running:
            self._pull_frame.setVisible(False)
            self._status_lbl.setText(
                "✓  Ollama installed.  "
                "Launch the Ollama app, then click  ⟳ Check status.")
            self._status_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{self._AMBER};")
            return

        models = get_ollama_models()
        if not models:
            self._pull_frame.setVisible(True)
            self._status_lbl.setText(
                "✓  Ollama is running.  "
                "No models downloaded yet — use Step 2 below.")
            self._status_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{self._AMBER};")
            return

        # All good
        self._pull_frame.setVisible(False)
        names = ", ".join(m["id"] for m in models[:3])
        self._status_lbl.setText(
            f"✓  Ollama ready with {len(models)} model(s): {names}\n"
            "You can connect to it from  Settings → Ollama.")
        self._status_lbl.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{self._GREEN};")

    # ── Install handlers ───────────────────────────────────────────────────────

    def _on_install_clicked(self) -> None:
        import sys
        if sys.platform == "win32":
            self._install_btn.setEnabled(False)
            self._install_prog.setValue(0)
            self._install_prog.setVisible(True)
            self._install_cancel_btn.setVisible(True)
            self._install_cancel_btn.setEnabled(True)
            self._install_cancel_btn.setText("✕  Cancel Download")
            self._install_msg.setText("Connecting to ollama.com…")
            self._install_msg.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
            self._install_msg.setVisible(True)

            self._install_thread = _WizOllamaInstallThread(self)
            self._install_thread.progress.connect(self._on_install_progress)
            self._install_thread.finished.connect(self._on_install_finished)
            self._install_thread.start()
        else:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl("https://ollama.com/download"))
            self._install_msg.setText(
                "Opened  ollama.com/download  in your browser.\n"
                "Install Ollama, then click  ⟳ Check status.")
            self._install_msg.setStyleSheet(
                f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
            self._install_msg.setVisible(True)

    def _on_install_progress(self, pct: int, msg: str) -> None:
        self._install_prog.setValue(pct)
        self._install_msg.setText(msg)

    def _on_install_cancel_clicked(self) -> None:
        if hasattr(self, "_install_thread") and self._install_thread.isRunning():
            self._install_thread.requestInterruption()
        self._install_cancel_btn.setEnabled(False)
        self._install_cancel_btn.setText("Cancelling…")

    def _on_install_finished(self, ok: bool, msg: str) -> None:
        self._install_prog.setVisible(False)
        self._install_cancel_btn.setVisible(False)
        self._install_cancel_btn.setEnabled(True)
        self._install_cancel_btn.setText("✕  Cancel Download")
        _cancelled = (msg == "cancelled")
        self._install_msg.setText(
            "Download cancelled." if _cancelled else msg)
        self._install_msg.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:"
            f"{self._MUTED if _cancelled else (self._GREEN if ok else self._DANGER)};")
        self._install_btn.setEnabled(True)
        if ok:
            self._install_btn.setText("⟳  Re-check")
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(5000, self._detect)

    # ── Pull handlers ──────────────────────────────────────────────────────────

    def _on_pull_clicked(self) -> None:
        model = self._pull_combo.currentText().strip()
        if not model:
            return
        self._pull_btn.setEnabled(False)
        self._pull_cancel_btn.setVisible(True)
        self._pull_cancel_btn.setEnabled(True)
        self._pull_cancel_btn.setText("✕  Cancel")
        self._pull_prog.setVisible(True)
        self._pull_msg.setText(f"Downloading  {model} …  (may take several minutes)")
        self._pull_msg.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{self._MUTED};")
        self._pull_msg.setVisible(True)

        self._pull_thread = _WizOllamaPullThread(model, self)
        self._pull_thread.output_line.connect(self._on_pull_output)
        self._pull_thread.finished.connect(self._on_pull_finished)
        self._pull_thread.start()

    def _on_pull_cancel_clicked(self) -> None:
        if hasattr(self, "_pull_thread") and self._pull_thread.isRunning():
            self._pull_thread.requestInterruption()
            self._pull_thread.cancel()
        self._pull_cancel_btn.setEnabled(False)
        self._pull_cancel_btn.setText("Cancelling…")

    def _on_pull_output(self, line: str) -> None:
        if line.strip():
            self._pull_msg.setText(line[:80])

    def _on_pull_finished(self, ok: bool, msg: str) -> None:
        self._pull_prog.setVisible(False)
        self._pull_cancel_btn.setVisible(False)
        self._pull_cancel_btn.setEnabled(True)
        self._pull_cancel_btn.setText("✕  Cancel")
        self._pull_btn.setEnabled(True)
        _cancelled = (msg == "cancelled")
        self._pull_msg.setText(
            "Pull cancelled." if _cancelled else msg)
        self._pull_msg.setStyleSheet(
            f"font-size:{FONT['sublabel']}pt; color:"
            f"{self._MUTED if _cancelled else (self._GREEN if ok else self._DANGER)};")
        if ok:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(500, self._detect)

    def values(self) -> dict:
        """AI page writes no config keys — Ollama is auto-detected at runtime."""
        return {}


class _PageDone(_PageBase):
    def __init__(self, parent=None):
        super().__init__(
            "All Done!",
            "Your hardware configuration has been saved to config.yaml.",
            parent)

        self._summary = QLabel("(summary will appear here)")
        self._summary.setStyleSheet(
            f"font-size:{FONT['label']}pt; color:{PALETTE.get('textSub','#6a6a6a')}; background:{PALETTE.get('bg','#242424')}; "
            f"border:1px solid {PALETTE.get('border','#484848')}; border-radius:5px; padding:12px;")
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
    l.setStyleSheet(f"font-size:{FONT['label']}pt; color:{PALETTE.get('textSub','#6a6a6a')};")
    return l


# ── Main wizard dialog ────────────────────────────────────────────────────────

class FirstRunWizard(QDialog):
    """
    Multi-page hardware setup wizard.

    On accept, writes updated values into config.yaml and marks first-run done.

    Can be shown at any time — not only on first launch.  When opened from
    Settings → Hardware Setup the sentinel check is bypassed and the wizard
    always shows.  The background scan runs every time the dialog opens so
    newly connected devices are always detected.
    """

    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._all_values: dict = {}

        self.setWindowTitle("SanjINSIGHT — Hardware Setup")
        self.setModal(True)
        self.resize(700, 600)
        self.setStyleSheet(f"""
            QDialog   {{ background:{PALETTE.get('bg','#242424')}; }}
            QGroupBox {{ background:{PALETTE.get('surface','#2d2d2d')}; }}
            QLabel    {{ background:transparent; }}
        """)

        # Load current config
        self._cfg_hw: dict = {}
        try:
            with open(config_path, "r") as f:
                raw = yaml.safe_load(f) or {}
            self._cfg_hw = raw.get("hardware", {})
        except Exception as e:
            log.warning("FirstRunWizard: could not read config: %s", e)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Progress bar (step dots) ──────────────────────────────────
        prog_bar = QWidget()
        prog_bar.setFixedHeight(44)
        prog_bar.setStyleSheet(f"background:{PALETTE.get('bg','#242424')}; border-bottom:1px solid {PALETTE.get('border','#484848')};")
        pb_lay = QHBoxLayout(prog_bar)
        pb_lay.setContentsMargins(30, 0, 30, 0)
        self._dots: list[QLabel] = []
        step_labels = ["Welcome", "TEC", "Camera", "FPGA", "Bias", "Stage", "AI", "Done"]
        for i, lbl in enumerate(step_labels):
            dot = QLabel(f"● {lbl}")
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('border','#484848')};")
            pb_lay.addWidget(dot, 1)
            self._dots.append(dot)
            if i < len(step_labels) - 1:
                line = QLabel("──")
                line.setStyleSheet(f"color:{PALETTE.get('border','#484848')};")
                pb_lay.addWidget(line)
        root.addWidget(prog_bar)

        # ── Page stack ────────────────────────────────────────────────
        self._page_welcome = _PageWelcome()
        self._page_tec     = _PageTEC(self._cfg_hw)
        self._page_camera  = _PageCamera(self._cfg_hw)
        self._page_fpga    = _PageFPGA(self._cfg_hw)
        self._page_bias    = _PageBias(self._cfg_hw)
        self._page_stage   = _PageStage(self._cfg_hw)
        self._page_ai      = _PageAI()
        self._page_done    = _PageDone()

        self._stack = QStackedWidget()
        for p in [self._page_welcome, self._page_tec,
                  self._page_camera, self._page_fpga,
                  self._page_bias, self._page_stage,
                  self._page_ai, self._page_done]:
            self._stack.addWidget(p)
        root.addWidget(self._stack, 1)

        # ── Navigation bar ────────────────────────────────────────────
        nav = QWidget()
        nav.setFixedHeight(60)
        nav.setStyleSheet(f"background:{PALETTE.get('bg','#242424')}; border-top:1px solid {PALETTE.get('border','#484848')};")
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

        # ── Start background hardware scan ────────────────────────────
        self._scan_worker = _ScanWorker(self)
        self._scan_worker.status_update.connect(self._on_scan_status)
        self._scan_worker.completed.connect(self._on_scan_complete)
        self._scan_worker.start()

    # ── Background scan callbacks ──────────────────────────────────────

    def _on_scan_status(self, msg: str):
        self._page_welcome.set_scan_status(msg)

    def _on_scan_complete(self, report):
        if report is None:
            self._page_welcome.set_scan_done(0)
            return
        # Distribute results to each page; they update their own fields
        self._page_tec.apply_scan(report)
        self._page_camera.apply_scan(report)
        self._page_fpga.apply_scan(report)
        self._page_bias.apply_scan(report)
        self._page_stage.apply_scan(report)
        # Use known_only() for the welcome-page count
        self._page_welcome.set_scan_done(len(report.known_only()))

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
                dot.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('cta','#0a84ff')}; font-weight:700;")
            elif i < idx:
                dot.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('accent','#00d4aa')};")
            else:
                dot.setStyleSheet(f"font-size:{FONT['sublabel']}pt; color:{PALETTE.get('border','#484848')};")

    def _on_next(self):
        idx = self._stack.currentIndex()
        page = self._stack.currentWidget()
        self._all_values.update(page.values())

        if idx == self._stack.count() - 1:
            # Finish button
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

    def closeEvent(self, event):
        """Stop the scan worker if the dialog is closed while scanning."""
        if self._scan_worker.isRunning():
            self._scan_worker.quit()
            self._scan_worker.wait(1000)
        super().closeEvent(event)

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
            log.error("FirstRunWizard: cannot read config for writing: %s", e)
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
            log.info("FirstRunWizard: config written to %s", self._config_path)
        except Exception as e:
            log.error("FirstRunWizard: cannot write config: %s", e)
            QMessageBox.warning(
                self, "Config Write Error",
                f"Could not save to {self._config_path}:\n{e}\n\n"
                "Your changes were not saved. Edit config.yaml manually.")
            return

        _mark_first_run_done(self._config_path)
