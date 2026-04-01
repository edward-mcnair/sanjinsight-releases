"""
ui/widgets/report_dialog.py

Report Generation Dialog — configurable content, format, and metadata.

Matches the wireframe design (analysis-report.pdf, page 2):
  Left:  content checkboxes, format radio, metadata fields
  Right: live preview panel showing enabled sections
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QRadioButton, QButtonGroup, QLineEdit, QTextEdit,
    QGroupBox, QFrame, QGridLayout, QSizePolicy, QScrollArea,
    QWidget, QComboBox, QInputDialog)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import QPainter, QColor, QFont, QPen

from ui.theme import FONT, PALETTE
from ui.icons import set_btn_icon
import config as cfg_mod


class ReportDialog(QDialog):
    """Modal dialog for configuring and generating a report."""

    generate_requested = pyqtSignal(object)  # emits ReportConfig

    def __init__(self, session_label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Report")
        self.setMinimumSize(860, 560)
        self.setModal(True)
        self._session_label = session_label

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setFixedHeight(42)
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(16, 0, 16, 0)
        title_lbl = QLabel("Generate Report")
        title_lbl.setStyleSheet(
            f"font-size: {FONT['readoutSm']}pt; font-weight: bold;")
        tl.addWidget(title_lbl)
        tl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self.reject)
        tl.addWidget(close_btn)
        root.addWidget(title_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        # Body: left options + right preview
        body = QHBoxLayout()
        body.setContentsMargins(16, 12, 16, 12)
        body.setSpacing(16)

        opts_scroll = QScrollArea()
        opts_scroll.setWidgetResizable(True)
        opts_scroll.setFrameShape(QFrame.NoFrame)
        opts_scroll.setWidget(self._build_options())
        body.addWidget(opts_scroll, 1)
        body.addWidget(self._build_preview(), 1)
        root.addLayout(body, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 8, 16, 14)
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(32)
        self._cancel_btn.setMinimumWidth(90)
        self._cancel_btn.clicked.connect(self.reject)

        self._gen_btn = QPushButton("Generate")
        set_btn_icon(self._gen_btn, "fa5s.file-alt", PALETTE['textOnAccent'])
        self._gen_btn.setFixedHeight(32)
        self._gen_btn.setMinimumWidth(110)
        self._gen_btn.clicked.connect(self._on_generate)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._gen_btn)
        root.addLayout(btn_row)

        self._apply_styles()
        self._update_preview()

    # ---------------------------------------------------------------- #
    #  Left: Options panel                                              #
    # ---------------------------------------------------------------- #

    def _build_options(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Template preset selector
        preset_box = QGroupBox("Template Preset")
        pl = QHBoxLayout(preset_box)
        pl.setSpacing(6)
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Custom")
        self._preset_combo.setFixedHeight(26)
        self._save_preset_btn = QPushButton("Save…")
        self._save_preset_btn.setFixedHeight(26)
        self._del_preset_btn = QPushButton("Delete")
        self._del_preset_btn.setFixedHeight(26)
        self._del_preset_btn.setEnabled(False)
        pl.addWidget(self._preset_combo, 1)
        pl.addWidget(self._save_preset_btn)
        pl.addWidget(self._del_preset_btn)

        # Populate with saved presets
        from acquisition.report_presets import list_report_presets
        self._preset_combo.addItems(list_report_presets())

        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        self._save_preset_btn.clicked.connect(self._on_save_preset)
        self._del_preset_btn.clicked.connect(self._on_del_preset)
        lay.addWidget(preset_box)

        # Content checkboxes
        content_box = QGroupBox("Report Content")
        cl = QVBoxLayout(content_box)
        cl.setSpacing(4)

        self._cb_thermal_map = QCheckBox("Thermal map image")
        self._cb_thermal_map.setChecked(True)
        self._cb_hotspot_table = QCheckBox("Hotspot table")
        self._cb_hotspot_table.setChecked(True)
        self._cb_measurement_params = QCheckBox("Measurement parameters")
        self._cb_measurement_params.setChecked(True)
        self._cb_device_info = QCheckBox("Device information")
        self._cb_device_info.setChecked(True)
        self._cb_raw_data = QCheckBox("Raw data summary")
        self._cb_raw_data.setChecked(False)
        self._cb_verdict = QCheckBox("Verdict and recommendations")
        self._cb_verdict.setChecked(True)
        self._cb_calibration = QCheckBox("Calibration details")
        self._cb_calibration.setChecked(False)
        self._cb_scorecard = QCheckBox("Quality scorecard")
        self._cb_scorecard.setChecked(True)

        self._checkboxes = [
            self._cb_thermal_map, self._cb_hotspot_table,
            self._cb_measurement_params, self._cb_device_info,
            self._cb_raw_data, self._cb_verdict,
            self._cb_calibration, self._cb_scorecard,
        ]
        for cb in self._checkboxes:
            cl.addWidget(cb)
            cb.toggled.connect(self._update_preview)

        lay.addWidget(content_box)

        # Format radio buttons
        fmt_box = QGroupBox("Format")
        fl = QHBoxLayout(fmt_box)
        self._fmt_group = QButtonGroup(self)
        self._radio_pdf = QRadioButton("PDF Report")
        self._radio_html = QRadioButton("HTML")
        self._radio_pdf.setChecked(True)
        self._fmt_group.addButton(self._radio_pdf, 0)
        self._fmt_group.addButton(self._radio_html, 1)
        fl.addWidget(self._radio_pdf)
        fl.addWidget(self._radio_html)
        fl.addStretch()
        lay.addWidget(fmt_box)

        # Metadata fields
        meta_box = QGroupBox("Metadata")
        ml = QGridLayout(meta_box)
        ml.setSpacing(6)

        self._operator_edit = QLineEdit()
        self._operator_edit.setPlaceholderText("Operator name")
        self._operator_edit.setText(
            cfg_mod.get_pref("report.operator", ""))

        self._customer_edit = QLineEdit()
        self._customer_edit.setPlaceholderText("Customer / project")

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Additional notes for report")
        self._notes_edit.setMaximumHeight(70)

        ml.addWidget(QLabel("Operator"), 0, 0)
        ml.addWidget(self._operator_edit, 0, 1)
        ml.addWidget(QLabel("Customer"), 1, 0)
        ml.addWidget(self._customer_edit, 1, 1)
        ml.addWidget(QLabel("Notes"), 2, 0, Qt.AlignTop)
        ml.addWidget(self._notes_edit, 2, 1)
        lay.addWidget(meta_box)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Preset handlers                                                  #
    # ---------------------------------------------------------------- #

    def _on_preset_selected(self, name: str):
        self._del_preset_btn.setEnabled(name != "Custom")
        if name == "Custom":
            return
        from acquisition.report_presets import load_report_preset
        p = load_report_preset(name)
        if p is None:
            return
        self._cb_thermal_map.setChecked(p.thermal_map)
        self._cb_hotspot_table.setChecked(p.hotspot_table)
        self._cb_measurement_params.setChecked(p.measurement_params)
        self._cb_device_info.setChecked(p.device_info)
        self._cb_raw_data.setChecked(p.raw_data_summary)
        self._cb_verdict.setChecked(p.verdict_and_recommendations)
        self._cb_calibration.setChecked(p.calibration_details)
        self._cb_scorecard.setChecked(p.quality_scorecard)
        if p.format == "html":
            self._radio_html.setChecked(True)
        else:
            self._radio_pdf.setChecked(True)

    def _on_save_preset(self):
        from acquisition.report_presets import save_report_preset, ReportPreset
        name, ok = QInputDialog.getText(self, "Save Report Template",
                                        "Template name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        save_report_preset(ReportPreset(
            name=name,
            thermal_map=self._cb_thermal_map.isChecked(),
            hotspot_table=self._cb_hotspot_table.isChecked(),
            measurement_params=self._cb_measurement_params.isChecked(),
            device_info=self._cb_device_info.isChecked(),
            raw_data_summary=self._cb_raw_data.isChecked(),
            verdict_and_recommendations=self._cb_verdict.isChecked(),
            calibration_details=self._cb_calibration.isChecked(),
            quality_scorecard=self._cb_scorecard.isChecked(),
            format="html" if self._radio_html.isChecked() else "pdf",
        ))
        self._preset_combo.blockSignals(True)
        if self._preset_combo.findText(name) < 0:
            self._preset_combo.addItem(name)
        self._preset_combo.setCurrentText(name)
        self._preset_combo.blockSignals(False)
        self._del_preset_btn.setEnabled(True)

    def _on_del_preset(self):
        from acquisition.report_presets import delete_report_preset
        name = self._preset_combo.currentText()
        if name == "Custom":
            return
        delete_report_preset(name)
        self._preset_combo.removeItem(self._preset_combo.currentIndex())
        self._preset_combo.setCurrentIndex(0)

    # ---------------------------------------------------------------- #
    #  Right: Preview panel                                             #
    # ---------------------------------------------------------------- #

    def _build_preview(self) -> QWidget:
        self._preview = _PreviewPanel(self._session_label)
        scroll = QScrollArea()
        scroll.setWidget(self._preview)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        return scroll

    def _update_preview(self):
        sections = []
        if self._cb_measurement_params.isChecked():
            sections.append("Acquisition Parameters")
        if self._cb_device_info.isChecked():
            sections.append("Instrument & DUT")
        if self._cb_thermal_map.isChecked():
            sections.append("Thermal Map (ΔR/R)")
        if self._cb_raw_data.isChecked():
            sections.append("Supporting Images")
        if self._cb_calibration.isChecked():
            sections.append("Calibrated ΔT Map")
        if self._cb_verdict.isChecked():
            sections.append("Pass / Fail Analysis")
        if self._cb_hotspot_table.isChecked():
            sections.append("Hotspot Detail")
        if self._cb_scorecard.isChecked():
            sections.append("Quality Scorecard")
        self._preview.set_sections(sections)

    # ---------------------------------------------------------------- #
    #  Config extraction                                                #
    # ---------------------------------------------------------------- #

    def get_config(self):
        from acquisition.report import ReportConfig
        return ReportConfig(
            thermal_map=self._cb_thermal_map.isChecked(),
            hotspot_table=self._cb_hotspot_table.isChecked(),
            measurement_params=self._cb_measurement_params.isChecked(),
            device_info=self._cb_device_info.isChecked(),
            raw_data_summary=self._cb_raw_data.isChecked(),
            verdict_and_recommendations=self._cb_verdict.isChecked(),
            calibration_details=self._cb_calibration.isChecked(),
            quality_scorecard=self._cb_scorecard.isChecked(),
            format="html" if self._radio_html.isChecked() else "pdf",
            operator=self._operator_edit.text().strip(),
            customer=self._customer_edit.text().strip(),
            notes=self._notes_edit.toPlainText().strip(),
        )

    def _on_generate(self):
        # Remember operator for next time
        op = self._operator_edit.text().strip()
        if op:
            cfg_mod.set_pref("report.operator", op)
        self.accept()

    # ---------------------------------------------------------------- #
    #  Theme                                                            #
    # ---------------------------------------------------------------- #

    def _apply_styles(self):
        P = PALETTE
        bg  = P["bg"]
        sur = P["surface"]
        su2 = P["surface2"]
        bdr = P["border"]
        txt = P["text"]
        dim = P["textDim"]
        sub = P["textSub"]
        acc = P["accent"]

        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; color: {txt}; }}
            QGroupBox {{
                color: {dim}; font-size: {FONT['body']}pt;
                border: 1px solid {bdr}; border-radius: 4px;
                margin-top: 10px; padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 8px;
                font-weight: bold;
            }}
            QCheckBox {{ color: {txt}; font-size: {FONT['heading']}pt; }}
            QRadioButton {{ color: {txt}; font-size: {FONT['heading']}pt; }}
            QLabel {{ color: {sub}; font-size: {FONT['body']}pt; }}
            QLineEdit, QTextEdit {{
                background: {sur}; color: {txt};
                border: 1px solid {bdr}; border-radius: 3px;
                padding: 4px 8px; font-size: {FONT['body']}pt;
            }}
            QPushButton {{
                background: {su2}; color: {txt};
                border: 1px solid {bdr}; border-radius: 4px;
                padding: 4px 12px; font-size: {FONT['body']}pt;
            }}
            QPushButton:hover {{ background: {sur}; }}
            QScrollArea {{ border: 1px solid {bdr}; border-radius: 4px; }}
        """)

        # Generate button accent style
        self._gen_btn.setStyleSheet(f"""
            QPushButton {{
                background: {acc}; color: {bg};
                border: none; border-radius: 4px;
                font-weight: bold; font-size: {FONT['body']}pt;
            }}
            QPushButton:hover {{ background: {acc}cc; }}
        """)


# ------------------------------------------------------------------ #
#  Preview panel                                                       #
# ------------------------------------------------------------------ #

class _PreviewPanel(QFrame):
    """Simplified page mockup showing which report sections are enabled."""

    def __init__(self, session_label: str = "", parent=None):
        super().__init__(parent)
        self._label = session_label or "Session"
        self._sections: list[str] = []
        self.setMinimumSize(280, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_sections(self, sections: list[str]):
        self._sections = list(sections)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()

        # Page background (white)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(PALETTE['surface']))
        p.drawRoundedRect(4, 4, W - 8, H - 8, 4, 4)

        # Header bar
        p.setBrush(QColor(PALETTE['bg']))
        p.drawRect(4, 4, W - 8, 30)

        # Title text
        p.setPen(QColor(PALETTE['text']))
        p.setFont(QFont("Helvetica", 8, QFont.Bold))
        p.drawText(12, 24, "Thermal Analysis Report")

        # Teal rule
        p.setPen(QPen(QColor(PALETTE['accent']), 2))
        p.drawLine(4, 36, W - 4, 36)

        # Session label
        p.setPen(QColor(PALETTE['textSub']))
        p.setFont(QFont("Helvetica", 7))
        p.drawText(12, 50, self._label)

        # Section placeholders
        y = 60
        section_font = QFont("Helvetica", 7, QFont.Bold)
        block_font = QFont("Helvetica", 6)

        for section in self._sections:
            if y + 50 > H - 20:
                break

            # Section heading
            p.setPen(QColor(PALETTE['bg']))
            p.setFont(section_font)
            p.drawText(12, y + 10, section)

            # Separator line
            p.setPen(QPen(QColor(PALETTE['border']), 0.5))
            p.drawLine(12, y + 14, W - 16, y + 14)

            # Content placeholder blocks
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(PALETTE['surface']))
            if "Map" in section or "Image" in section:
                # Image placeholder (larger)
                p.drawRoundedRect(12, y + 18, W - 28, 36, 2, 2)
                y += 62
            elif "Table" in section or "Detail" in section:
                # Table placeholder (rows)
                for i in range(3):
                    p.drawRoundedRect(12, y + 18 + i * 8, W - 28, 6, 1, 1)
                y += 48
            else:
                # Text placeholder
                for i in range(2):
                    pw = (W - 28) if i == 0 else int((W - 28) * 0.7)
                    p.drawRoundedRect(12, y + 18 + i * 8, pw, 5, 1, 1)
                y += 38

        # Footer
        p.setPen(QColor(PALETTE['textDim']))
        p.setFont(QFont("Helvetica", 5))
        p.drawText(12, H - 10, "Generated by SanjINSIGHT")

        p.end()
